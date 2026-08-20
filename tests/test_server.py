from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from hermes_mcp_bridge.config import load_config
from hermes_mcp_bridge.server import build_app


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("HERMES_API_URL", "https://hermes.interne")
    monkeypatch.setenv("ACCESS_VERIFY_JWT", "false")
    monkeypatch.setenv("PUBLIC_HOSTNAMES", "agent.exemple.fr")
    return load_config()


def test_healthz(env):
    with TestClient(build_app(env)) as client:
        reponse = client.get("/healthz")
        assert reponse.status_code == 200
        assert reponse.json() == {"status": "ok"}


def test_hote_public_accepte(env):
    """Le pendant du 421 : le nom déclaré doit passer, avec et sans port."""
    with TestClient(build_app(env), base_url="https://agent.exemple.fr") as client:
        reponse = client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert reponse.status_code != 421


def test_hote_inconnu_rejete(env):
    with TestClient(build_app(env), base_url="https://intrus.exemple.fr") as client:
        reponse = client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert reponse.status_code == 421


def test_jwt_exige_quand_active(monkeypatch):
    monkeypatch.setenv("HERMES_API_URL", "https://hermes.interne")
    monkeypatch.setenv("ACCESS_VERIFY_JWT", "true")
    monkeypatch.setenv("ACCESS_TEAM_DOMAIN", "https://exemple.cloudflareaccess.com")
    monkeypatch.setenv("ACCESS_AUD", "aud")
    monkeypatch.setenv("PUBLIC_HOSTNAMES", "agent.exemple.fr")
    app = build_app(load_config())
    with TestClient(
        app, base_url="https://agent.exemple.fr", raise_server_exceptions=False
    ) as client:
        assert client.get("/mcp").status_code == 401
        assert client.get("/healthz").status_code == 200
