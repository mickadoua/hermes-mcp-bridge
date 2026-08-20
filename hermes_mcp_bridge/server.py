"""Serveur MCP (Streamable HTTP) exposant sept outils Hermes.

Sept outils, et un huitième délibérément absent : approuver une carte. Un
agent capable de valider son propre travail n'est plus sous supervision, il a
juste une étape de plus à franchir. Ce serveur ne fera donc jamais passer une
tâche de `blocked` à `done`.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Route

from .access import AccessJWTMiddleware, AccessJWTVerifier
from .config import Config, load_config
from .hermes import HermesClient

logger = logging.getLogger(__name__)

INSTRUCTIONS = """Pont MCP vers un agent Hermes.

Expose le kanban et les rapports d'une instance Hermes à un client MCP distant,
en passant par l'API REST de son dashboard.

Ce que ce serveur ne fera jamais : approuver une carte. Faire passer une tâche
de `blocked` à `done` est le geste par lequel un humain valide une sortie.
"""


def _dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_mcp_server(hermes: HermesClient) -> MCPServer:
    mcp = MCPServer(name="hermes", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def kanban_board(board: str = "") -> str:
        """État du kanban : chaque colonne avec ses cartes.

        Rappel de lecture : `todo` ne veut pas dire « à faire » mais « bloqué
        par une dépendance ». Les seules colonnes qui appellent un geste humain
        sont `triage` (à lancer) et `blocked` (à valider).
        """
        return _dump(await hermes.board(board))

    @mcp.tool()
    async def kanban_task(task_id: str) -> str:
        """Détail d'une carte : corps, statut, commentaires, résultat."""
        return _dump(await hermes.task(task_id))

    @mcp.tool()
    async def kanban_create(title: str, body: str = "", board: str = "") -> str:
        """Dépose une nouvelle carte en `triage`, sans assignée — donc gelée.

        L'agent distant peut proposer du travail, pas en lancer : assigner la
        carte est précisément le geste par lequel un humain décide de démarrer.
        """
        return _dump(await hermes.create_task(title=title, body=body, board=board))

    @mcp.tool()
    async def kanban_comment(task_id: str, text: str) -> str:
        """Ajoute un commentaire à une carte, sans la valider."""
        return _dump(await hermes.comment(task_id, text))

    @mcp.tool()
    async def vault_list(subdir: str = "") -> str:
        """Liste les fichiers produits par l'agent dans sa zone d'écriture."""
        return _dump(await hermes.vault_list(subdir))

    @mcp.tool()
    async def vault_read(path: str) -> str:
        """Lit un fichier de la zone d'écriture de l'agent (rapports, notes)."""
        return _dump(await hermes.vault_read(path))

    @mcp.tool()
    async def ask(question: str, model: str = "") -> str:
        """Pose une question à l'agent via sa gateway compatible OpenAI.

        Réponse ponctuelle, sans outils ni mémoire de session : pour faire
        exécuter un vrai travail, déposer une carte avec `kanban_create`.
        """
        return await hermes.ask(question, model)

    return mcp


def build_app(config: Config | None = None) -> Starlette:
    """Assemble l'application ASGI complète : santé, MCP, validation du jeton."""
    config = config or load_config()
    hermes = HermesClient(
        api_url=config.hermes_api_url,
        api_token=config.hermes_api_token,
        gateway_url=config.hermes_gateway_url,
        gateway_token=config.hermes_gateway_token,
        default_board=config.hermes_default_board,
        default_model=config.hermes_default_model,
        timeout=config.request_timeout,
    )
    mcp = build_mcp_server(hermes)

    # Piège n°5 de la mise en service : sans `transport_security`, le SDK
    # dérive sa politique anti-DNS-rebinding du paramètre `host`, qui vaut
    # `127.0.0.1` par défaut. Tout nom d'hôte public est alors rejeté en 421,
    # avec pour seule trace une ligne de log côté serveur.
    if config.public_hostnames:
        security = TransportSecuritySettings(
            allowed_hosts=config.allowed_hosts,
            allowed_origins=config.allowed_origins,
        )
    else:
        # Aucun nom public déclaré : on reste en loopback, ce qui est le bon
        # défaut pour un poste de développement.
        security = TransportSecuritySettings(
            allowed_hosts=["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*"],
            allowed_origins=config.allowed_origins,
        )

    mcp_app = mcp.streamable_http_app(transport_security=security, host=config.host)

    async def healthz(_request: Any) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    app = Starlette(
        routes=[Route("/healthz", healthz, methods=["GET"])],
        lifespan=mcp_app.router.lifespan_context,
    )
    app.mount("/", mcp_app)

    if config.verify_access_jwt:
        verifier = AccessJWTVerifier(
            issuer=config.access_issuer,
            audience=config.access_aud,
            jwks_url=config.access_jwks_url,
        )
        return AccessJWTMiddleware(app, verifier)  # type: ignore[return-value]

    logger.warning(
        "ACCESS_VERIFY_JWT=false : le pont accepte toute requête qui l'atteint. "
        "À n'utiliser qu'en développement local."
    )
    return app
