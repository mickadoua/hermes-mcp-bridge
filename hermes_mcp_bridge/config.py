"""Bridge configuration, read once at startup.

No secret is stored in the repository: everything arrives through the
environment. The bridge refuses to start when a required value is missing,
rather than running half-configured — a server that listens without validating
is worse than a server that does not start.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Configuration missing or inconsistent."""


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default if default is not None else "")
    if required and not value:
        raise ConfigError(f"missing environment variable: {name}")
    return value


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


@dataclass(frozen=True)
class Config:
    # --- Hermes ---------------------------------------------------------
    hermes_api_url: str
    hermes_api_token: str
    hermes_gateway_url: str
    hermes_gateway_token: str
    hermes_default_board: str
    hermes_default_model: str
    request_timeout: float

    # --- Cloudflare Access ----------------------------------------------
    access_team_domain: str
    access_aud: str
    verify_access_jwt: bool

    # --- HTTP transport --------------------------------------------------
    host: str
    port: int
    public_hostnames: list[str] = field(default_factory=list)
    allowed_origins: list[str] = field(default_factory=list)

    @property
    def access_issuer(self) -> str:
        return self.access_team_domain.rstrip("/")

    @property
    def access_jwks_url(self) -> str:
        return f"{self.access_issuer}/cdn-cgi/access/certs"

    @property
    def allowed_hosts(self) -> list[str]:
        """Hostnames accepted by the SDK's DNS-rebinding protection.

        Each name is expanded into a "with port" variant, without which a
        `Host: agent.example.com:443` is rejected with a 421.
        """
        hosts: list[str] = []
        for name in self.public_hostnames:
            hosts.extend([name, f"{name}:*"])
        return hosts


def load_config() -> Config:
    verify = _env("ACCESS_VERIFY_JWT", "true").lower() not in {"0", "false", "no"}
    return Config(
        hermes_api_url=_env("HERMES_API_URL", required=True).rstrip("/"),
        hermes_api_token=_env("HERMES_API_TOKEN"),
        hermes_gateway_url=_env("HERMES_GATEWAY_URL").rstrip("/"),
        hermes_gateway_token=_env("HERMES_GATEWAY_TOKEN"),
        hermes_default_board=_env("HERMES_DEFAULT_BOARD", "default"),
        hermes_default_model=_env("HERMES_DEFAULT_MODEL", ""),
        request_timeout=float(_env("HERMES_TIMEOUT", "60")),
        access_team_domain=_env("ACCESS_TEAM_DOMAIN", required=verify),
        access_aud=_env("ACCESS_AUD", required=verify),
        verify_access_jwt=verify,
        host=_env("BIND_HOST", "0.0.0.0"),
        port=int(_env("BIND_PORT", "8080")),
        public_hostnames=_env_list("PUBLIC_HOSTNAMES"),
        allowed_origins=_env_list("ALLOWED_ORIGINS", "https://claude.ai"),
    )
