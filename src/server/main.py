"""Start the HTTP service with a model client built from the project config."""

from __future__ import annotations

from pathlib import Path

import anyio

from model.client import load_settings, open_client
from server.server import serve

CONFIG_PATH = Path("config.toml")
HOST = "127.0.0.1"
PORT = 8765
DEFAULT_MODEL = "qwen3.8-max"


async def serve_from_config(path: Path, *, host: str, port: int) -> None:
    """Read the model config, open one OpenAI client, and serve the HTTP API."""
    settings = load_settings(path)
    client = open_client(settings)
    try:
        await serve(client, model=DEFAULT_MODEL, host=host, port=port)
    finally:
        await client.aclose()


def main() -> None:
    """Read ``config.toml`` and serve the HTTP API."""

    async def _serve() -> None:
        await serve_from_config(CONFIG_PATH, host=HOST, port=PORT)

    anyio.run(_serve)


if __name__ == "__main__":
    main()
