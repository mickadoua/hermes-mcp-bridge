# Troubleshooting

The symptoms actually hit in production, and what they mean.

## `421 Invalid Host header`

The Python MCP SDK ships DNS-rebinding protection. With no explicit policy, it derives one from the `host` parameter of `streamable_http_app()`, which defaults to `127.0.0.1`: every public hostname is rejected.

The 421 is a plain-text HTTP response, not a JSON-RPC error: the MCP client surfaces only a generic transport error, and the refused hostname appears nowhere but the server logs.

**Fix**: set `PUBLIC_HOSTNAMES` to the name served by the tunnel. The bridge expands each name into a "with port" variant. Behind a reverse proxy that already controls the `Host` header, explicitly disabling the protection is more honest than fiddling with the list — at least the decision is written down.

## "Could not register with the login service"

Claude registers itself dynamically as an OAuth client and declares its callback URL. If the Cloudflare application's "Allowed redirect URIs" field is empty, no URI is accepted, so registration is refused.

**Fix**: declare `https://claude.ai/api/mcp/auth_callback`.

## An Access rule that does not apply

A policy whose action is "Service Auth" evaluates **only** non-identity rules. Adding an email address to it raises no error: the rule is ignored. Conversely, an "Allow" policy with a service-token selector redirects to a login instead of validating the token.

**Fix**: two distinct policies on the same application, one per population.

## A 401 when the token looks fine

In order of likelihood:

1. `ACCESS_AUD` does not match the audience tag of **this** application;
2. `ACCESS_TEAM_DOMAIN` is not exactly the token's issuer (`iss`), `https://` scheme included;
3. the token has expired — Access issues short-lived ones.

The bridge's logs print the exact reason reported by PyJWT.

## The bridge answers without authentication

Check `ACCESS_VERIFY_JWT`. At `false`, the bridge accepts every request that reaches it and logs that at every startup. This mode exists only for local development: on a shared Docker network it hands the kanban to every neighbouring container.

## Testing the passing case

After adding a validation, "no token → 401" and "forged token → 401" are reassuring proofs that prove nothing: **a validator that rejects everything looks exactly like a correct one**. The only proof that counts is that a legitimate token gets through — that is what `tests/test_access.py::test_legitimate_token_passes` covers.
