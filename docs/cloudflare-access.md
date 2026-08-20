# Putting the bridge behind Cloudflare Access

Goal: make the bridge reachable from Claude on any device, without opening a single port on the router, and without any public IP to protect.

The hostnames, application identifiers and addresses in this document are placeholders.

## 1. The tunnel

Create a tunnel in Zero Trust, then publish the bridge on it. The `cloudflared` connector runs alongside the bridge (see [`compose.yaml`](../compose.yaml)) and dials **out** to Cloudflare: nothing comes in.

Public route of the tunnel:

```
agent.example.com  →  http://hermes-mcp-bridge:8080
```

Put the same name in `PUBLIC_HOSTNAMES`, otherwise the MCP SDK answers 421 (see [troubleshooting](troubleshooting.md)).

## 2. The Access application

Create a **self-hosted** application on `agent.example.com`.

Then, and this is the part that costs time: **two populations, two distinct policies**.

### The "machines" policy — action *Service Auth*

For scripts, using a service token (a `CF-Access-Client-Id` / `CF-Access-Client-Secret` header pair).

> A policy whose action is "Service Auth" evaluates **only** non-identity rules: tokens, mTLS, IP. Adding an email-address rule to it raises no error — the rule is simply ignored.

### The "humans" policy — action *Allow*

For you, through your identity provider (email, Google, GitHub…).

> The converse holds too: an "Allow" policy with a service-token selector does not validate the token, it redirects to a login page.

Access evaluates service policies first, the others afterwards.

## 3. The audience

Pick up the application's **Audience (AUD) tag** and put it in `ACCESS_AUD`. It is what distinguishes *this* application from the other applications on the same account: without that check, a token issued for another app would pass the bridge's validation.

Also fill in `ACCESS_TEAM_DOMAIN` with `https://<your-team>.cloudflareaccess.com`.

## 4. Managed OAuth

Claude's connector UI only offers OAuth: no bearer token, no custom header. But a Cloudflare service token **is** a header pair — so the whole "machine" setup is structurally unusable from a web connector.

So enable **managed OAuth** on the application, which makes Access the OAuth provider. Its documentation sets one condition: only enable it for an MCP server that validates the Access JWT. That is exactly what this bridge does — keep `ACCESS_VERIFY_JWT=true`.

Declare the redirect URI, without which dynamic client registration fails ("Could not register with the login service"):

```
https://claude.ai/api/mcp/auth_callback
```

## 5. Wiring up the connector

In Claude, add a remote MCP connector pointing at:

```
https://agent.example.com/mcp
```

The first connection opens the Access login page; the seven tools show up afterwards.

## Verifying, in the right order

Isolate one variable at a time. Before wiring up the connector, test the chain with a plain **service token**: Cloudflare then issues a real JWT **without involving OAuth**.

```bash
curl -sS https://agent.example.com/healthz \
  -H "CF-Access-Client-Id: $CF_ID" \
  -H "CF-Access-Client-Secret: $CF_SECRET"
```

Then, from the NAS and **with no header whatsoever**, check that the origin does refuse:

```bash
curl -sS -o /dev/null -w '%{http_code}\n' http://hermes-mcp-bridge:8080/mcp   # expected: 401
```

If this one answers anything other than a 401, the bridge is validating nothing and any neighbouring container can drive the kanban.
