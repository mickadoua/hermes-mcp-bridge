"""Entry point: `python -m hermes_mcp_bridge`."""

from __future__ import annotations

import logging
import sys

import uvicorn

from .config import ConfigError, load_config
from .server import build_app


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    )
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"invalid configuration: {exc}", file=sys.stderr)
        return 2

    uvicorn.run(build_app(config), host=config.host, port=config.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
