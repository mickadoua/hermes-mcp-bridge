# hermes-mcp-bridge

A **Streamable HTTP** MCP bridge between a self-hosted [Hermes](https://github.com/mickadoua) agent and a remote MCP client (Claude on the web or mobile, or any other compatible client), behind **Cloudflare Access**.

Two constraints define it, and they pull in opposite directions: expose nothing to the Internet, and give no automated process the rights it would need to do real damage.

> The full account of getting this into production, including the five walls hit along the way (in French):
> [Brancher un agent self-hosted sur Claude sans lui donner les clés de la maison](https://dm-consulting.tech/fr/blog/brancher-agent-self-hosted-sur-claude).

## What it does

Seven tools, all going through Hermes' **dashboard REST API** — not the Docker socket, not its SQLite databases:

| Tool | Role |
|---|---|
| `kanban_board` | kanban state, column by column |
| `kanban_task` | card detail: body, status, comments, result |
| `kanban_create` | drops a card **in `triage`, unassigned** |
| `kanban_comment` | comments on a card without approving it |
| `vault_list` | lists the files produced by the agent |
| `vault_read` | reads one of those files |
| `ask` | one-off question through the OpenAI-compatible gateway |

Going through the public API pays off three times over: the bridge needs no special privilege, it depends on no internal detail (so it survives Hermes upgrades), and its surface is exactly that of an API already designed to be called.

## What it will never do

**Approve a card.**

The agent is allowed to draft a cold outreach email. It is not allowed to send it. Between the two sits a kanban column: the card stops there awaiting approval, and a human is the one who moves it to "done". That gesture *is* the safeguard.

Exposing that transition would have emptied it of meaning: an agent able to approve its own work is no longer supervised, it just has one more step to clear. So there is no code for it in this repository, and [a test](tests/test_hermes.py) fails if anyone adds some.

Same logic at creation time: a card dropped by the bridge is born in `triage`, unassigned, therefore frozen. The remote agent can **propose** work, not **start** it.

## Quick start

```bash
git clone https://github.com/mickadoua/hermes-mcp-bridge.git
cd hermes-mcp-bridge
cp .env.example .env      # then fill in HERMES_API_URL, ACCESS_AUD, PUBLIC_HOSTNAMES
pip install -e ".[dev]"
python -m hermes_mcp_bridge
```

In a container, with the tunnel connector alongside:

```bash
docker compose up -d --build
```

No port is published on the host: the tunnel goes out, nothing comes in.

## Configuration

Everything comes from the environment; see [`.env.example`](.env.example) for the annotated list. The four values that matter:

| Variable | Why it matters |
|---|---|
| `HERMES_API_URL` | the dashboard's internal URL, as the bridge container reaches it |
| `ACCESS_TEAM_DOMAIN` | the expected JWT issuer (`https://<team>.cloudflareaccess.com`) |
| `ACCESS_AUD` | the audience tag **of this application** — without it, a token issued for another app on the same account would pass |
| `PUBLIC_HOSTNAMES` | the public hostnames served by the tunnel; left empty, the SDK rejects everything with a 421 (see below) |

The dashboard's REST paths are grouped at the top of [`hermes_mcp_bridge/hermes.py`](hermes_mcp_bridge/hermes.py). If your version of Hermes exposes them elsewhere, that is the only place to change.

## Security

The bridge **validates for itself** the JWT that Cloudflare Access injects into every request: signature against the account's public keys, issuer, audience, expiry.

This is not redundant with the filtering at the edge. The container listens on `0.0.0.0` and shares a Docker network with other services: without this layer, any neighbouring container drives the kanban with no authentication at all, never going through Cloudflare. The edge protects you from the Internet, not from the neighbours. It is also the condition Cloudflare sets for enabling "managed OAuth": only enable it for an MCP server that validates the Access JWT.

`ACCESS_VERIFY_JWT=false` exists for local development, and the bridge logs it loudly at every startup.

The Cloudflare-side setup — tunnel, the **two** policies (machines and humans, which do not mix), managed OAuth, redirect URI — is described in [`docs/cloudflare-access.md`](docs/cloudflare-access.md).

## The 421 that catches everyone out

The Python MCP SDK ships DNS-rebinding protection. `streamable_http_app()` takes a `host` parameter that defaults to `127.0.0.1`, and **if the policy is not configured explicitly, the SDK derives one restricted to the loopback**: every public hostname is rejected with `421 Invalid Host header`, leaving nothing behind but a single server-side log line — the client only sees a generic transport error.

That is what `PUBLIC_HOSTNAMES` is for: each name is expanded into a "with port" variant, then handed to the SDK. Two tests pin the behaviour in both directions ([`tests/test_server.py`](tests/test_server.py)).

## Tests

```bash
pytest
```

The suite checks above all the thing people forget to check: that a **legitimate token gets through**. A validator that rejects everything looks exactly like a correct one; "no token → 401" and "forged token → 401" prove nothing on their own.

## Licence

MIT.
