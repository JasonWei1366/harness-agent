# Tau

A coding agent served over HTTP. It reads files, edits code, runs commands, and keeps the session on disk. The browser page in `frontend/` is the client.

This checkout is based on [Tau](https://github.com/huggingface/tau), a Python implementation of a Pi-style coding-agent harness. The agent loop, built-in tools, skills, and extensions remain. The process exposes one FastAPI service. Models are reached through the OpenAI-compatible protocol.

Python 3.12 or newer and [uv](https://docs.astral.sh/uv/) are required.

## Layout

```text
models        read the config and open the OpenAI-compatible client
agent    messages, tools, events, and the agent loop
application   sessions, built-in tools, skills, and extensions
service       the FastAPI process
```

`agent` does not depend on the page, the command line, or config file paths. `service` opens the model client at startup and hands that client to the session. The model name arrives on each request.

## Configuration

From the repository root:

```bash
cp config.toml.example config.toml
```

`config.toml` holds the endpoint and the API key:

```toml
base_url = "https://api.openai.com/v1"
api_key = "replace-me"
```

The model name is not in this file. The model field on the page is sent with each message. The default is `qwen3.8-max`. The default model, bind address, and port are the constants at the top of `src/server/main.py`:

```python
CONFIG_PATH = Path("config.toml")
HOST = "127.0.0.1"
PORT = 8765
DEFAULT_MODEL = "qwen3.8-max"
```

## Start

From the repository root:

```bash
uv sync
uv run python -m server.main
```

The terminal prints:

```text
Serving http://127.0.0.1:8765/
```

Open that address. The page and the API are the same process. Each request is written to the terminal. Press Ctrl+C to stop.

- `http://127.0.0.1:8765/` is the page
- `http://127.0.0.1:8765/docs` is the FastAPI reference

## API

Every route is `POST` with a JSON body, and every body includes `userId`.

| Path | Purpose |
| --- | --- |
| `/api/sessions` | List sessions, open one, or create one |
| `/api/session` | Run one action: read state, send a message, run a slash command, run a shell command, or abort |
| `/api/events` | Stream the current turn. The response ends when that turn settles |

Send a message:

```json
{
  "userId": "local",
  "action": "prompt",
  "sessionId": "the session id",
  "model": "qwen3.8-max",
  "message": "explain what this repository does"
}
```

`model` is required until the session already has one. Omit it to keep the current model, or send a new name to switch.

On the page, text that starts with `/` is a slash command. Text that starts with `!` runs in the session directory.

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy
```

## License

Released under the [MIT License](LICENSE). The code comes from [huggingface/tau](https://github.com/huggingface/tau).
