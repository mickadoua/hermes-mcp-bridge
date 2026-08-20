"""MCP server (Streamable HTTP) exposing seven Hermes tools.

Seven tools, and an eighth deliberately absent: approving a card. An agent able
to sign off its own work is no longer supervised, it just has one more step to
clear. So this server will never move a task from `blocked` to `done`.
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

INSTRUCTIONS = """MCP bridge to a Hermes agent.

Exposes the kanban and reports of a Hermes instance to a remote MCP client,
going through its dashboard REST API.

What this server will never do: approve a card. Moving a task from `blocked` to
`done` is the gesture by which a human approves an output.
"""


def _dump(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_mcp_server(hermes: HermesClient) -> MCPServer:
    mcp = MCPServer(name="hermes", instructions=INSTRUCTIONS)

    @mcp.tool()
    async def kanban_board(board: str = "") -> str:
        """Kanban state: every column with its cards.

        A reading note: `todo` does not mean "to do" but "blocked by a
        dependency". The only columns that call for a human gesture are
        `triage` (to start) and `blocked` (to approve).
        """
        return _dump(await hermes.board(board))

    @mcp.tool()
    async def kanban_task(task_id: str) -> str:
        """Card detail: body, status, comments, result."""
        return _dump(await hermes.task(task_id))

    @mcp.tool()
    async def kanban_create(title: str, body: str = "", board: str = "") -> str:
        """Drop a new card in `triage`, unassigned — therefore frozen.

        The remote agent can propose work, not start it: assigning the card is
        precisely the gesture by which a human decides to get going.
        """
        return _dump(await hermes.create_task(title=title, body=body, board=board))

    @mcp.tool()
    async def kanban_comment(task_id: str, text: str) -> str:
        """Add a comment to a card, without approving it."""
        return _dump(await hermes.comment(task_id, text))

    @mcp.tool()
    async def vault_list(subdir: str = "") -> str:
        """List the files produced by the agent in its writing area."""
        return _dump(await hermes.vault_list(subdir))

    @mcp.tool()
    async def vault_read(path: str) -> str:
        """Read a file from the agent's writing area (reports, notes)."""
        return _dump(await hermes.vault_read(path))

    @mcp.tool()
    async def ask(question: str, model: str = "") -> str:
        """Ask the agent a question through its OpenAI-compatible gateway.

        A one-off answer, with no tools and no session memory: to get real work
        done, drop a card with `kanban_create`.
        """
        return await hermes.ask(question, model)

    return mcp


def build_app(config: Config | None = None) -> Starlette:
    """Assemble the complete ASGI application: health, MCP, token validation."""
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

    # Pitfall no. 5 of getting this into production: without
    # `transport_security`, the SDK derives its DNS-rebinding policy from the
    # `host` parameter, which defaults to `127.0.0.1`. Every public hostname is
    # then rejected with a 421, leaving nothing behind but a server-side log
    # line.
    if config.public_hostnames:
        security = TransportSecuritySettings(
            allowed_hosts=config.allowed_hosts,
            allowed_origins=config.allowed_origins,
        )
    else:
        # No public name declared: stay on the loopback, which is the right
        # default for a development machine.
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
        "ACCESS_VERIFY_JWT=false: the bridge accepts every request that reaches it. "
        "Only use this for local development."
    )
    return app
