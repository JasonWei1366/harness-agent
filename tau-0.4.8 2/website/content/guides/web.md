---
title: Web API and browser client
description: Run Tau as a local HTTP API with a separate browser frontend.
---

`tau web` starts the coding session behind a FastAPI app. The routes are
declared in `src/tau_coding/web/server.py`. The browser client in `frontend/`
is a separate program: it only sends JSON requests and never imports the agent.

The terminal TUI is unchanged. Run `tau` with no subcommand to open it.

## Start

From the project you want Tau to work in:

```bash
tau web
```

Tau prints two addresses:

- `http://0.0.0.0:8765/docs` is the interactive API reference.
- `http://0.0.0.0:8765/api/sessions` lists and opens sessions. Every API call is `POST`.
- `http://0.0.0.0:8765/` is the static client, when `frontend/` is available.

The page opens in a browser unless you pass `--no-browser`. `--api-only` serves
the API and does not serve the client files.

```bash
tau web --host 0.0.0.0 --port 9000 --no-browser
tau web --api-only
```

`tau web` listens on `0.0.0.0`, so other machines on the network can reach it.
A client can read files and run commands through the same tools as the TUI.
Pass `--host` with a loopback address when it should stay on this machine.

To host the client yourself, open `frontend/index.html` with an API base:

```text
http://localhost:8080/?api=http://0.0.0.0:8765
```

`TAU_WEB_FRONTEND` can point at another directory that contains `index.html`.

## API

There are three POST routes. Every body includes `userId`.
`/api/sessions` returns a session list or one session's facts.
`/api/session` runs one JSON action on the `sessionId` in the body.
`/api/events` is only the event stream for that session.

| Request | Body | Result |
| --- | --- | --- |
| `POST /api/sessions` | `{ "userId": "..." }` | Sessions owned by this user, this project first. Does not create a session |
| `POST /api/sessions` | `{ "userId": "...", "sessionId": "..." }` | Open one session this user owns. Returns that session's facts and the user's session list |
| `POST /api/sessions` | `{ "userId": "...", "create": true }` | Start a session. The first create adopts the session the server already started, when nobody owns it |
| `POST /api/session` | `{ "userId": "...", "action": "state", "sessionId": "..." }` | Session id, model, provider, cwd, thinking level, streaming flag, queue depth, context and token usage, compaction, extensions, skills, prompts, context and system-prompt files, tools, and that user's saved sessions |
| `POST /api/session` | `{ "userId": "...", "action": "messages", "sessionId": "..." }` | `{ "messages": [...] }`, the durable transcript |
| `POST /api/session` | `{ "userId": "...", "action": "prompt", "sessionId": "...", "message": "...", "streamingBehavior": "steer" \| "followUp" }` | `204`. Starts `session.prompt`. `streamingBehavior` is required while a turn is running |
| `POST /api/session` | `{ "userId": "...", "action": "command", "sessionId": "...", "text": "/session" }` | Slash command. The body includes the session id that is current afterward |
| `POST /api/session` | `{ "userId": "...", "action": "terminal", "sessionId": "...", "command": "pwd", "addToContext": true }` | Shell command in the session directory |
| `POST /api/session` | `{ "userId": "...", "action": "abort", "sessionId": "..." }` | `204`. `session.cancel()` |
| `POST /api/events` | `{ "userId": "...", "sessionId": "..." }` | One turn as a server-sent event stream, including `message_update`. The response ends when that turn settles |

`/api/events` carries one running turn, the same events an in-process frontend
receives from `session.prompt()`. It closes after `agent_settled`. `message_update`
holds the assistant message accumulated so far. Completed messages come from
`action: "messages"`.
The client decides how to render them.

The browser keeps its user id in `localStorage` under `tau.userId` and sends it as
`userId` in every request body. It keeps the active `sessionId` in the page, so
two tabs can drive two sessions. A new browser profile gets a new id.
Session history is loaded only for that id. A user cannot open another user's session.
A command result can ask for a picker. This API returns that flag; it does not
open a terminal panel.
