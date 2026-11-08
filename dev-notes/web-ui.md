# Web API and browser client

`tau web` is another frontend over `CodingSession`. The agent packages stay
UI-free. The HTTP API is a transport of the session, the same split documented
for an in-process frontend:

The HTTP API is three POST routes. `userId` in the JSON body names the caller.
`sessionId` in the body selects which of that user's sessions an action applies
to. A request for one session cannot land on another.

- `POST /api/sessions` with only `userId` lists that caller's sessions and does
  not create one. `sessionId` opens a session that user owns. `create` starts
  one. The first create adopts the session the server process already started,
  when that session has no owner yet.
- `POST /api/session` carries `action`. `messages` is `session.messages`.
  `state` is the session facts a frontend reads beside the event stream,
  including context size, token usage, compaction, extensions, skills, prompts,
  context and system-prompt files, tools, and saved sessions from this project and
  from other directories. Only sessions owned by the calling user are included.
  The browser client stores its user id in `localStorage` and sends that `userId`
  in each request body, so one browser keeps the same id and does not see another browser's
  sessions. `prompt` is `session.prompt`. A second prompt while a turn is running
  requires `streamingBehavior` of `steer` or `followUp`. `abort` is `session.cancel`.
  `command` is `handle_command` plus the session effects that command asks for.
  Picker flags stay in the result for the client. Resuming a session checks
  ownership, and the result carries the session id that is current afterward.
  `terminal` is `run_terminal_command`. The `!` prefix is client input syntax.
- `POST /api/events` publishes one turn as a server-sent stream. The client opens
  it when a turn is running and the response ends at `agent_settled`. An idle
  page does not keep this connection open. It is separate because its response
  is not JSON.

`frontend/` is one client of those routes. It keeps the in-progress assistant
message, tool rows, and command text locally. A separately hosted page passes
`?api=` as the API origin.

The Textual TUI remains the default `tau` command. `tau web explain this` is
still a TUI prompt; only `tau web` with no extra words, or with web flags,
starts the server.

The transcript gains an assistant message only when that message ends. Until
then the client renders the assistant message carried by `message_update`.
