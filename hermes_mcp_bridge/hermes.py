"""Client de l'API REST du dashboard Hermes.

Tout passe par l'API publique du dashboard : ni socket Docker, ni accès direct
aux bases SQLite. Le pont n'a donc besoin d'aucun privilège particulier, et il
ne dépend d'aucun détail interne — il survit aux mises à jour d'Hermes.

Les chemins REST sont regroupés ici, en haut du module : si votre version du
dashboard les expose ailleurs, c'est le seul endroit à modifier.
"""

from __future__ import annotations

from typing import Any

import httpx

# --- Chemins de l'API du dashboard --------------------------------------
KANBAN_BOARD = "/api/kanban/board"
KANBAN_TASKS = "/api/kanban/tasks"
VAULT_LIST = "/api/vault/list"
VAULT_READ = "/api/vault/read"
GATEWAY_CHAT = "/v1/chat/completions"

#: Colonne dans laquelle naît toute carte déposée par le pont.
TRIAGE = "triage"


class HermesError(RuntimeError):
    """Le dashboard a répondu autre chose qu'un succès."""


class HermesClient:
    """Enveloppe fine sur l'API du dashboard.

    Une seule règle structurante : ce client n'expose aucun moyen de changer
    le statut d'une carte. Faire passer une tâche de `blocked` à `done` est le
    geste par lequel un humain valide une sortie ; il n'a pas de code ici.
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
        """État du kanban : chaque colonne avec ses cartes."""
        return await self._get(
            f"{self._api_url}{KANBAN_BOARD}",
            params={"board": board or self._default_board},
        )

    async def task(self, task_id: str) -> Any:
        """Détail d'une carte : corps, statut, commentaires, résultat."""
        return await self._get(f"{self._api_url}{KANBAN_TASKS}/{task_id}")

    async def create_task(self, title: str, body: str = "", board: str = "") -> Any:
        """Dépose une carte en `triage`, sans assignée — donc gelée.

        Trois détails se combinent, et les ignorer fait démarrer un travail que
        personne n'a validé :

        - sans `status`, la carte naîtrait en `ready` et le dispatcher la
          ramasserait dans la minute ;
        - une carte en `triage` **avec** une assignée est reprise par le
          *specifier*, qui la réécrit et la promeut : le gel ne tient que sans
          assignée ;
        - `board` est un paramètre de requête, jamais un champ du corps. Dans
          le corps il est ignoré en silence et la carte part dans le board par
          défaut.
        """
        return await self._post(
            f"{self._api_url}{KANBAN_TASKS}",
            params={"board": board or self._default_board},
            json={"title": title, "body": body, "status": TRIAGE},
        )

    async def comment(self, task_id: str, text: str) -> Any:
        """Commente une carte, sans toucher à son statut.

        C'est la façon de répondre à une carte `blocked` sans la valider :
        l'agent lira le commentaire à la reprise.
        """
        return await self._post(
            f"{self._api_url}{KANBAN_TASKS}/{task_id}/comments",
            json={"text": text},
        )

    # --- Zone d'écriture de l'agent --------------------------------------

    async def vault_list(self, subdir: str = "") -> Any:
        return await self._get(f"{self._api_url}{VAULT_LIST}", params={"subdir": subdir})

    async def vault_read(self, path: str) -> Any:
        return await self._get(f"{self._api_url}{VAULT_READ}", params={"path": path})

    # --- Gateway compatible OpenAI ---------------------------------------

    async def ask(self, question: str, model: str = "") -> str:
        """Question ponctuelle à l'agent : sans outils, sans mémoire de session.

        Pour faire exécuter un vrai travail, on dépose une carte.
        """
        if not self._gateway_url:
            raise HermesError("HERMES_GATEWAY_URL n'est pas configurée")
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
            raise HermesError(f"réponse inattendue de la gateway : {data!r}") from exc

    # --- Plomberie --------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_token}"} if self._api_token else {}

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> Any:
        return await self._request("GET", url, params=params, headers=self._headers())

    async def _post(self, url: str, params: dict[str, Any] | None = None, json: Any = None) -> Any:
        return await self._request("POST", url, params=params, json=json, headers=self._headers())

    async def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        response = await self._client.request(method, url, **kwargs)
        if response.status_code >= 400:
            raise HermesError(f"{method} {url} → {response.status_code} : {response.text[:500]}")
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return response.text
