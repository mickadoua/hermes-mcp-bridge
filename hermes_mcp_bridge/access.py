"""Validation of the JWT injected by Cloudflare Access.

Why the origin validates when the edge already filters: because the container
listens on a shared Docker network. Without this layer, any neighbouring
container reaches the bridge directly, never going through Cloudflare. The
upstream filtering protects you from the Internet, not from the neighbours.

Cloudflare's "managed OAuth" documentation states the condition explicitly
anyway: only enable it for an MCP server that validates the Access JWT.
"""

from __future__ import annotations

import logging

import jwt
from jwt import PyJWKClient
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

#: Header set by Access on every request that has passed a policy.
JWT_HEADER = "cf-access-jwt-assertion"
#: Equivalent cookie, used by browsers.
JWT_COOKIE = "CF_Authorization"


class AccessJWTError(Exception):
    """The token is missing, unreadable, or not meant for this application."""


class AccessJWTVerifier:
    """Checks signature, issuer, audience and expiry.

    The audience is the part not to miss: it is what tells *this* application
    apart from the other applications on the same Cloudflare account. Without
    it, a token issued for another app would pass validation.
    """

    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict:
        if not token:
            raise AccessJWTError("missing token")
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(token).key
            return jwt.decode(
                token,
                signing_key,
                algorithms=["RS256", "ES256"],
                audience=self._audience,
                issuer=self._issuer,
                options={"require": ["exp", "iat", "aud", "iss"]},
            )
        except AccessJWTError:
            raise
        except Exception as exc:  # pragma: no cover - depends on PyJWT
            raise AccessJWTError(str(exc)) from exc


class AccessJWTMiddleware:
    """ASGI middleware: 401 until the token is valid.

    Sitting in front of the MCP application, it therefore also covers the
    discovery routes. `exempt_paths` is there for health probes, which must
    reveal nothing beyond "I am alive".
    """

    def __init__(
        self,
        app: ASGIApp,
        verifier: AccessJWTVerifier,
        exempt_paths: tuple[str, ...] = ("/healthz",),
    ) -> None:
        self.app = app
        self.verifier = verifier
        self.exempt_paths = exempt_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path", "") in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        token = _extract_token(scope)
        try:
            claims = self.verifier.verify(token)
        except AccessJWTError as exc:
            logger.warning("request refused: %s", exc)
            response = JSONResponse(
                {"error": "unauthorized", "detail": "invalid Cloudflare Access token"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # The validated identity is made available to the layers above; it is
        # used for logging, never to grant an extra right.
        scope.setdefault("state", {})["access_identity"] = claims.get("email") or claims.get("sub")
        await self.app(scope, receive, send)


def _extract_token(scope: Scope) -> str:
    headers = {
        k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])
    }
    if token := headers.get(JWT_HEADER):
        return token
    for chunk in headers.get("cookie", "").split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == JWT_COOKIE:
            return value
    return ""
