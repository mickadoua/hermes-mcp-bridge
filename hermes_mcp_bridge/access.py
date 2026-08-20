"""Validation du JWT injecté par Cloudflare Access.

Pourquoi l'origine valide alors que le bord filtre déjà : parce que le
conteneur écoute sur un réseau Docker partagé. Sans cette couche, n'importe
quel conteneur voisin joint le pont directement, sans jamais passer par
Cloudflare. Le filtrage en amont protège d'Internet, pas des voisins.

La documentation de l'« OAuth géré » de Cloudflare pose d'ailleurs la
condition explicitement : ne l'activer que pour un serveur MCP qui valide le
JWT d'Access.
"""

from __future__ import annotations

import logging

import jwt
from jwt import PyJWKClient
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

logger = logging.getLogger(__name__)

#: En-tête posé par Access sur chaque requête qui a passé une politique.
JWT_HEADER = "cf-access-jwt-assertion"
#: Cookie équivalent, utilisé par les navigateurs.
JWT_COOKIE = "CF_Authorization"


class AccessJWTError(Exception):
    """Le jeton est absent, illisible, ou ne vise pas cette application."""


class AccessJWTVerifier:
    """Vérifie signature, émetteur, audience et expiration.

    L'audience est le point à ne pas rater : c'est elle qui distingue *cette*
    application des autres applications du même compte Cloudflare. Sans elle,
    un jeton émis pour une autre app passerait la validation.
    """

    def __init__(self, issuer: str, audience: str, jwks_url: str) -> None:
        self._issuer = issuer
        self._audience = audience
        self._jwks = PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, token: str) -> dict:
        if not token:
            raise AccessJWTError("jeton absent")
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
        except Exception as exc:  # pragma: no cover - dépend de PyJWT
            raise AccessJWTError(str(exc)) from exc


class AccessJWTMiddleware:
    """Middleware ASGI : 401 tant que le jeton n'est pas valide.

    Placé devant l'application MCP, il s'applique donc aussi aux routes de
    découverte. `exempt_paths` sert aux sondes de santé, qui ne doivent rien
    révéler d'autre qu'un « je suis vivant ».
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
            logger.warning("requête refusée : %s", exc)
            response = JSONResponse(
                {"error": "unauthorized", "detail": "jeton Cloudflare Access invalide"},
                status_code=401,
            )
            await response(scope, receive, send)
            return

        # L'identité validée est mise à disposition des couches suivantes ;
        # elle sert aux journaux, jamais à décider d'un droit supplémentaire.
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
