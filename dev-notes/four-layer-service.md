# Top-level packages

Sibling Python packages live directly under `src/`:

- `entity` holds Pydantic and typing data models (messages, events, session entries).
- `model` is the model module. `open_client` builds one OpenAI-compatible client from `base_url` and `api_key`.
- `agent` is the core module: the agent loop, messages, tools, and session tree.
- `application` is the business module: sessions, tools, skills, and extensions.
- `server` is the boot module: the FastAPI process.

`config.toml` holds the endpoint and API key. Each HTTP prompt or session request can pass `model`, and that name is forwarded to `stream_response`. The boot module reads the key and opens the client when the process starts.

The terminal UI, JSONL RPC mode, and the Anthropic, Google, Mistral, and Codex adapters are not part of this layout. A caller installs one client with `use_client` or `open_client`. The agent loop and other model call sites then call `stream_response`, which returns the project's assistant events. Vendor wire formats stay in `model`.

Start the boot module with:

```bash
uv run python -m server.main
```
