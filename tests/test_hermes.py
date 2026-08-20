"""The bridge proposes work, it does not start it.

These tests pin down the three details that, ignored, would start a task nobody
approved.
"""

from __future__ import annotations

import json

import httpx
import pytest

from hermes_mcp_bridge.hermes import HermesClient, HermesError


def _client(handler) -> HermesClient:
    transport = httpx.MockTransport(handler)
    return HermesClient(
        api_url="https://hermes.internal",
        api_token="token",
        default_board="personal",
        client=httpx.AsyncClient(transport=transport),
    )


@pytest.mark.anyio
async def test_card_created_in_triage_unassigned():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = request.url
        seen["body"] = request.read().decode()
        return httpx.Response(200, json={"id": "T-1"})

    hermes = _client(handler)
    await hermes.create_task(title="Draft an email", body="…")

    body = json.loads(seen["body"])
    assert body["status"] == "triage", "without status, the card would be born in ready"
    assert "assignee" not in body, "an assigned card is promoted by the specifier"
    assert seen["url"].params["board"] == "personal", "board is a query parameter"
    assert "board" not in body, "in the body, board is silently ignored"
    await hermes.aclose()


@pytest.mark.anyio
async def test_no_method_changes_a_status():
    """Safeguard: nothing in the client may approve a card."""
    forbidden = {"approve", "validate", "set_status", "transition", "done", "complete"}
    public = {n for n in dir(HermesClient) if not n.startswith("_")}
    assert public & forbidden == set()


@pytest.mark.anyio
async def test_http_error_is_surfaced():
    hermes = _client(lambda request: httpx.Response(503, text="dashboard unavailable"))
    with pytest.raises(HermesError, match="503"):
        await hermes.board()
    await hermes.aclose()


@pytest.mark.anyio
async def test_ask_extracts_the_answer():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/chat/completions"
        return httpx.Response(200, json={"choices": [{"message": {"content": "42"}}]})

    hermes = HermesClient(
        api_url="https://hermes.internal",
        gateway_url="https://gateway.internal",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    assert await hermes.ask("the answer?") == "42"
    await hermes.aclose()


@pytest.fixture
def anyio_backend():
    return "asyncio"
