"""Configuration du pont, lue une fois au démarrage.

Aucun secret n'est stocké dans le dépôt : tout arrive par l'environnement.
Le pont refuse de démarrer si une valeur indispensable manque, plutôt que de
tourner à moitié configuré — un serveur qui écoute sans valider est pire qu'un
serveur qui ne démarre pas.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


class ConfigError(RuntimeError):
    """Configuration absente ou incohérente."""


def _env(name: str, default: str | None = None, *, required: bool = False) -> str:
    value = os.environ.get(name, default if default is not None else "")
    if required and not value:
        raise ConfigError(f"variable d'environnement manquante : {name}")
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

    # --- Transport HTTP --------------------------------------------------
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
        """Noms d'hôte acceptés par la protection anti-DNS-rebinding du SDK.

        Chaque nom est décliné en variante « avec port », sans quoi un
        `Host: agent.example.com:443` est rejeté en 421.
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
