"""Client for the Hermes dashboard REST API.

Everything goes through the dashboard's public API: no Docker socket, no direct
access to the SQLite databases. The bridge therefore needs no special privilege,
and depends on no internal detail — it survives Hermes upgrades.

The REST paths are grouped here, at the top of the module: if your version of
the dashboard exposes them elsewhere, that is the only place to change.
"""

from __future__ import annotations

from typing import Any

import httpx

# --- Dashboard API paths -------------------------------------------------
KANBAN_BOARD = "/api/kanban/board"
KANBAN_TASKS = "/api/kanban/tasks"
VAULT_LIST = "/api/vault/list"
VAULT_READ = "/api/vault/read"
GATEWAY_CHAT = "/v1/chat/completions"

#: Column every card dropped by the bridge is born into.
TRIAGE = "triage"


class HermesError(RuntimeError):
    """The dashboard answered with something other than a success."""


class HermesClient:
    """Thin wrapper over the dashboard API.

    One structural rule: this client exposes no way of changing a card's
    status. Moving a task from `blocked` to `done` is the gesture by which a
    human approves an output; there is no code for it here.
    """

    def __init__(
        self,
        api_url: str,
        api_token: str = "",
        gateway_url: str = "",
        gateway_token: str = "",
        default_board: str = "default",
        default_model: str = "",
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._api_url = api_url.rstrip("/")
        self._api_token = api_token
        self._gateway_url = gateway_url.rstrip("/")
        self._gateway_token = gateway_token
        self._default_board = default_board
        self._default_model = default_model
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    # --- Kanban ---------------------------------------------------------

    async def board(self, board: str = "") -> Any:
        """Kanban state: every column with its cards."""
        return await self._get(
            f"{self._api_url}{KANBAN_BOARD}",
            params={"board": board or self._default_board},
        )

    async def task(self, task_id: str) -> Any:
        """Card detail: body, status, comments, result."""
        return await self._get(f"{self._api_url}{KANBAN_TASKS}/{task_id}")

    async def create_task(self, title: str, body: str = "", board: str = "") -> Any:
        """Drop a card in `triage`, unassigned — therefore frozen.

        Three details combine here, and ignoring them starts work nobody
        approved:

        - without `status`, the card would be born in `ready` and the
          dispatcher would pick it up within the minute;
        - a card in `triage` **with** an assignee is taken over by the
          *specifier*, which rewrites and promotes it: the freeze only holds
          while it is unassigned;
        - `board` is a query parameter, never a body field. In the body it is
          silently ignored and the card lands on the default board.
        """
        return await self._post(
            f"{self._api_url}{KANBAN_TASKS}",
            params={"board": board or self._default_board},
            json={"title": title, "body": body, "status": TRIAGE},
        )

    async def comment(self, task_id: str, text: str) -> Any:
        """Comment on a card, without touching its status.

        This is how you answer a `blocked` card without approving it: the agent
        will read the comment when it resumes.
        """
        return await self._post(
            f"{self._api_url}{KANBAN_TASKS}/{task_id}/comments",
            json={"text": text},
        )

    # --- The agent's writing area ----------------------------------------

    async def vault_list(self, subdir: str = "") -> Any:
        return await self._get(f"{self._api_url}{VAULT_LIST}", params={"subdir": subdir})

    async def vault_read(self, path: str) -> Any:
        return await self._get(f"{self._api_url}{VAULT_READ}", params={"path": path})

    # --- OpenAI-compatible gateway ---------------------------------------

    async def ask(self, question: str, model: str = "") -> str:
        """One-off question to the agent: no tools, no session memory.

        To get real work done, drop a card.
        """
        if not self._gateway_url:
            raise HermesError("HERMES_GATEWAY_URL is not configured")
        payload = {
            "model": model or self._default_model or "default",
            "messages": [{"role": "user", "content": question}],
        }
        headers = {"Authorization": f"Bearer {self._gateway_token}"} if self._gateway_token else {}
        data = await self._request(
            "POST", f"{self._gateway_url}{GATEWAY_CHAT}", json=payload, headers=headers
        )
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HermesError(f"unexpected response from the gateway: {data!r}") from exc

    # --- Plumbing ---------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", url, params=params, headers=self._headers())

    async def _post(self, url: str, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        return await self._request("POST", url, params=params, json=json, headers=self._headers())

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise HermesError(f"{method} {url} → {response.status_code}: {response.text[:500]}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text
