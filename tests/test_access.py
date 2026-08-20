"""Le test qui compte est celui du cas passant.

Un validateur qui refuse tout ressemble trait pour trait à un validateur
correct : « sans jeton → 401 » et « jeton forgé → 401 » ne prouvent rien tant
qu'on n'a pas vu un jeton légitime passer.
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

ISSUER = "https://exemple.cloudflareaccess.com"
AUD = "aud-de-cette-application"
AUTRE_AUD = "aud-d-une-autre-application-du-meme-compte"


@pytest.fixture(scope="module")
def cle():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jeton(cle, *, aud=AUD, iss=ISSUER, exp_delta=600) -> str:
    now = int(time.time())
    return jwt.encode(
        {"aud": aud, "iss": iss, "iat": now, "exp": now + exp_delta, "email": "moi@exemple.fr"},
        cle,
        algorithm="RS256",
    )


@pytest.fixture()
def client(cle, monkeypatch):
    verifier = AccessJWTVerifier.__new__(AccessJWTVerifier)
    verifier._issuer = ISSUER
    verifier._audience = AUD

    class _JWKS:
        def get_signing_key_from_jwt(self, _token):
            return type("K", (), {"key": cle.public_key()})()

    verifier._jwks = _JWKS()

    inner = Starlette(
        routes=[Route("/mcp", lambda request: PlainTextResponse("atteint"), methods=["GET"])]
    )
    return TestClient(AccessJWTMiddleware(inner, verifier), raise_server_exceptions=False)


def test_jeton_legitime_passe(client, cle):
    """La seule preuve qui compte."""
    reponse = client.get("/mcp", headers={JWT_HEADER: _jeton(cle)})
    assert reponse.status_code == 200
    assert reponse.text == "atteint"


def test_sans_jeton(client):
    assert client.get("/mcp").status_code == 401


def test_jeton_forge(client):
    autre_cle = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forge = jwt.encode(
        {"aud": AUD, "iss": ISSUER, "iat": 0, "exp": 9e9}, autre_cle, algorithm="RS256"
    )
    assert client.get("/mcp", headers={JWT_HEADER: forge}).status_code == 401


def test_jeton_d_une_autre_application_du_meme_compte(client, cle):
    """Sans contrôle d'audience, celui-ci passerait : c'est tout l'intérêt."""
    jeton = _jeton(cle, aud=AUTRE_AUD)
    assert client.get("/mcp", headers={JWT_HEADER: jeton}).status_code == 401


def test_jeton_expire(client, cle):
    assert client.get("/mcp", headers={JWT_HEADER: _jeton(cle, exp_delta=-60)}).status_code == 401


def test_healthz_est_exempte(client):
    inner_hit = client.get("/healthz")
    assert inner_hit.status_code == 404  # atteint l'app interne, pas un 401
