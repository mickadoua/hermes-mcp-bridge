"""Le pont propose du travail, il n'en lance pas.

Ces tests figent les trois détails qui, ignorés, feraient démarrer une tâche
que personne n'a validée.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hermes_mcp_bridge.hermes import HermesClient, HermesError


def _client(handler) -> HermesClient:
    transport = httpx.MockTransport(handler)
    return HermesClient(
        api_url="https://hermes.interne",
        api_token="jeton",
        default_board="perso",
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.anyio
async def test_carte_creee_en_triage_sans_assignee():
    vues = {}

    def handler(request: httpx.Request) -> httpx.Response:
        vues["url"] = request.url
        vues["body"] = request.read().decode()
        return httpx.Response(200, json={"id": "T-1"})

    hermes = _client(handler)
    await hermes.create_task(title="Préparer un mail", body="…")

    corps = json.loads(vues["body"])
    assert corps["status"] == "triage", "sans status, la carte naîtrait en ready"
    assert "assignee" not in corps, "une carte assignée est promue par le specifier"
    assert vues["url"].params["board"] == "perso", "le board est un paramètre de requête"
    assert "board" not in corps, "dans le corps, board est ignoré en silence"
    await hermes.aclose()


@pytest.mark.anyio
async def test_aucune_methode_ne_change_un_statut():
    """Garde-fou : rien dans le client ne doit valider une carte."""
    interdits = {"approve", "validate", "set_status", "transition", "done", "complete"}
    publiques = {n for n in dir(HermesClient) if not n.startswith("_")}
    assert publiques & interdits == set()


@pytest.mark.anyio
async def test_erreur_http_remontee():
    hermes = _client(lambda request: httpx.Response(503, text="dashboard indisponible"))
    with pytest.raises(HermesError, match="503"):
        await hermes.board()
    await hermes.aclose()


@pytest.mark.anyio
async def test_ask_extrait_la_reponse():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "42"}}]})

    hermes = HermesClient(
        api_url="https://hermes.interne",
        gateway_url="https://gateway.interne",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await hermes.ask("la réponse ?") == "42"
    await hermes.aclose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
