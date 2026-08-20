"""The test that counts is the one for the passing case.

A validator that rejects everything looks exactly like a correct one: "no token
→ 401" and "forged token → 401" prove nothing until a legitimate token has been
seen getting through.
"""

from __future__ import annotations

import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from hermes_mcp_bridge.access import JWT_HEADER, AccessJWTMiddleware, AccessJWTVerifier

ISSUER = "https://example.cloudflareaccess.com"
AUD = "aud-of-this-application"
OTHER_AUD = "aud-of-another-application-on-the-same-account"


@pytest.fixture(scope="module")
def key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _token(key, *, aud=AUD, iss=ISSUER, exp_delta=600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta, "email": "me@example.com"},
        key,
        algorithm="RS256",
    )


@pytest.fixture()
def client(key, monkeypatch):
    verifier = AccessJWTVerifier.__new__(AccessJWTVerifier)
    verifier._issuer = ISSUER
    verifier._audience = AUD

    class _JWKS:
        def get_signing_key_from_jwt(self, _token):
            return type("K", (), {"key": key.public_key()})()

    verifier._jwks = _JWKS()

    inner = Starlette(
        routes=[Route("/mcp", lambda request: PlainTextResponse("reached"), methods=["GET"])]
    )
    return TestClient(AccessJWTMiddleware(inner, verifier), raise_server_exceptions=False)


def test_legitimate_token_passes(client, key):
    """The only proof that counts."""
    response = client.get("/mcp", headers={JWT_HEADER: _token(key)})
    assert response.status_code == 200
    assert response.text == "reached"


def test_without_token(client):
    assert client.get("/mcp").status_code == 401


def test_forged_token(client):
    other_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(
        {"aud": AUD, "iss": ISSUER, "iat": 0, "exp": 9e9}, other_key, algorithm="RS256"
    )
    assert client.get("/mcp", headers={JWT_HEADER: forged}).status_code == 401


def test_token_from_another_application_on_the_same_account(client, key):
    """Without the audience check this one would pass: that is the whole point."""
    token = _token(key, aud=OTHER_AUD)
    assert client.get("/mcp", headers={JWT_HEADER: token}).status_code == 401


def test_expired_token(client, key):
    assert client.get("/mcp", headers={JWT_HEADER: _token(key, exp_delta=-60)}).status_code == 401


def test_healthz_is_exempt(client):
    inner_hit = client.get("/healthz")
    assert inner_hit.status_code == 404  # reaches the inner app, not a 401
