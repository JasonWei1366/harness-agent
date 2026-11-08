---
title: "Phase 2: AI Provider Layer"
---

Phase 2 creates Tau's provider/model streaming layer in `models`.

The purpose of this layer is to let Tau talk to model APIs without letting provider-specific details leak into the reusable agent loop.

## What was added

Phase 2 added these modules:

```text
src/models/events.py              provider-neutral stream events
src/models/provider.py            ModelProvider protocol
src/models/fake.py                deterministic fake provider for tests
src/models/env.py                 environment-based provider configuration
src/models/openai_compatible.py   OpenAI-compatible chat completions adapter
```

## Why the provider layer exists

Model APIs do not all stream responses the same way. Each provider has its own request format, response chunks, tool-call encoding, error shape, and authentication rules.

Tau does not want the agent loop to know those details.

Instead, the split is:

```text
Provider API payloads
        ↓
models adapter
        ↓
ProviderEvent stream
        ↓
agent_core loop
```

The future agent loop can consume the same Tau event stream regardless of the backend model.

## Provider events

Provider events are lower-level than agent events.

They describe what the model is streaming, not what the full agent is doing.

Current provider events are:

- `ProviderResponseStartEvent`
- `ProviderTextDeltaEvent`
- `ProviderToolCallEvent`
- `ProviderResponseEndEvent`
- `ProviderErrorEvent`

A simple text response may look like this:

```text
response_start
text_delta       "Hel"
text_delta       "lo"
response_end     AssistantMessage(content="Hello")
```

A response with a tool call may look like this:

```text
response_start
text_delta       "I'll inspect that file."
tool_call        ToolCall(name="read", arguments={"path": "README.md"})
response_end     AssistantMessage(... tool_calls=[...])
```

## `ModelProvider`

`ModelProvider` is the protocol every model adapter must satisfy.

Conceptually, it says:

```python
provider.stream_response(
    model="...",
    system="...",
    messages=[...],
    tools=[...],
)
```

and returns an async stream of provider events.

This is the seam that lets Tau support multiple backends later.

## Fake provider

`FakeProvider` replays scripted provider events.

This is important because Tau should be testable without:

- network access
- API keys
- nondeterministic model output
- provider rate limits

Later, the pure agent loop can be tested by giving it a fake provider that emits exactly the text and tool calls a test needs.

## OpenAI-compatible provider

The first real adapter targets OpenAI-compatible `/chat/completions` APIs.

It handles:

- bearer token authentication
- chat message formatting
- tool schema formatting
- server-sent event streaming
- streamed text deltas
- streamed tool-call argument assembly
- provider errors

Connection settings come from the caller. The HTTP service reads `config.toml` through `load_settings()` and `open_client()`. Coding sessions build an `OpenAICompatibleConfig` from provider settings. The default base URL is:

```text
https://api.openai.com/v1
```

## Important boundary

`models` does not execute tools.

If a model asks for a tool, the provider layer only emits a `ProviderToolCallEvent` containing a neutral `ToolCall`.

Tool execution belongs to the future `agent_core` loop:

```text
models:
  "The model requested this tool call."

agent_core:
  "Find the registered AgentTool, execute it, append the result, continue."
```

Keeping this boundary clean makes it possible to reuse the same provider layer for CLIs, tests, Rich output, Textual, and other frontends.

## How Phase 2 supports later phases

### Phase 3: pure agent loop

The loop consumes `ProviderEvent`s, converts them into higher-level
`AgentEvent`s, executes tools, and decides whether another model turn is needed.
Later provider hardening added retry and thinking-delta events to that same
conversion path without giving providers any knowledge of the CLI or TUI.

### Phase 4: harness

The harness owns a provider instance, passes the current transcript into
`stream_response()`, and exposes prompt/continue APIs that can be used by print
mode, JSON event streaming, Rich rendering, and Textual.

### Phase 6: print-mode CLI

The CLI chooses a provider/model from configuration or command-line flags, then
displays streamed output as it arrives.

### Future providers

Additional providers can implement the same `ModelProvider` protocol without changing the agent loop.
