from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from hermes_mcp_bridge.config import load_config
from hermes_mcp_bridge.server import build_app


@pytest.fixture()
def env(monkeypatch):
    monkeypatch.setenv("HERMES_API_URL", "https://hermes.internal")
    monkeypatch.setenv("ACCESS_VERIFY_JWT", "false")
    monkeypatch.setenv("PUBLIC_HOSTNAMES", "agent.example.com")
    return load_config()


def test_healthz(env):
    with TestClient(build_app(env)) as client:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


def test_public_host_accepted(env):
    """The other side of the 421: the declared name must pass, with and without port."""
    with TestClient(build_app(env), base_url="https://agent.example.com") as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert response.status_code != 421


def test_unknown_host_rejected(env):
    with TestClient(build_app(env), base_url="https://intruder.example.com") as client:
        response = client.get("/mcp", headers={"Accept": "text/event-stream"})
        assert response.status_code == 421


def test_jwt_required_when_enabled(monkeypatch):
    monkeypatch.setenv("HERMES_API_URL", "https://hermes.internal")
    monkeypatch.setenv("ACCESS_VERIFY_JWT", "true")
    monkeypatch.setenv("ACCESS_TEAM_DOMAIN", "https://example.cloudflareaccess.com")
    monkeypatch.setenv("ACCESS_AUD", "aud")
    monkeypatch.setenv("PUBLIC_HOSTNAMES", "agent.example.com")
    app = build_app(load_config())
    with TestClient(
        app, base_url="https://agent.example.com", raise_server_exceptions=False
    ) as client:
        assert client.get("/mcp").status_code == 401
        assert client.get("/healthz").status_code == 200
