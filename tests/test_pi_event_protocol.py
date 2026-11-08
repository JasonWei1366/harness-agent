"""Focused contract tests for the canonical Pi-shaped event stream."""

from pathlib import Path

import pytest

from agent import (
    AgentEndEvent,
    AgentHarness,
    AgentHarnessConfig,
    AssistantMessage,
    MessageEndEvent,
    MessageUpdateEvent,
    TextContent,
    ToolCall,
    ToolExecutionEndEvent,
    ToolExecutionStartEvent,
    ToolResultMessage,
)
from agent.assistant_events import (
    AssistantDoneEvent,
    AssistantStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from model.client import FakeProvider, bind_client


def test_only_the_agent_loop_imports_the_model_layer() -> None:
    """Model calls are imported at the loop. The rest of the harness stays free of them."""
    for path in Path("src/agent").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        imports_models = "from model" in source or "import model" in source
        if path.name == "loop.py":
            assert imports_models, path
        else:
            assert not imports_models, path


@pytest.mark.anyio
async def test_text_stream_has_nested_updates_and_terminal_messages() -> None:
    empty = AssistantMessage(model="fake")
    hello = AssistantMessage(model="fake", content=[TextContent(text="hello")])
    provider = FakeProvider(
        [
            [
                AssistantStartEvent(partial=empty),
                TextStartEvent(content_index=0, partial=empty),
                TextDeltaEvent(content_index=0, delta="hello", partial=hello),
                TextEndEvent(content_index=0, content="hello", partial=hello),
                AssistantDoneEvent(reason="stop", message=hello),
            ]
        ]
    )
    harness = AgentHarness(AgentHarnessConfig(model="fake", system="test"))

    with bind_client(provider):
        events = [event async for event in harness.prompt("hi")]

    assert [event.type for event in events] == [
        "agent_start",
        "turn_start",
        "message_start",
        "message_end",
        "message_start",
        "message_update",
        "message_update",
        "message_update",
        "message_end",
        "turn_end",
        "agent_end",
    ]
    updates = [event for event in events if isinstance(event, MessageUpdateEvent)]
    assert [event.assistant_message_event.type for event in updates] == [
        "text_start",
        "text_delta",
        "text_end",
    ]
    assert isinstance(events[-1], AgentEndEvent)
    assert events[-1].messages[-1] == hello


@pytest.mark.anyio
async def test_tool_result_gets_execution_and_message_lifecycle_events() -> None:
    call = ToolCall(id="call-1", name="missing", arguments={})
    partial = AssistantMessage(model="fake", content=[call])
    provider = FakeProvider(
        [
            [
                AssistantStartEvent(partial=AssistantMessage(model="fake")),
                ToolCallStartEvent(content_index=0, partial=partial),
                ToolCallEndEvent(content_index=0, tool_call=call, partial=partial),
                AssistantDoneEvent(reason="toolUse", message=partial),
            ],
            [
                AssistantStartEvent(partial=AssistantMessage(model="fake")),
                AssistantDoneEvent(
                    reason="stop",
                    message=AssistantMessage(model="fake", content=[TextContent(text="done")]),
                ),
            ],
        ]
    )
    harness = AgentHarness(AgentHarnessConfig(model="fake", system="test"))

    with bind_client(provider):
        events = [event async for event in harness.prompt("use it")]

    start = next(event for event in events if isinstance(event, ToolExecutionStartEvent))
    end = next(event for event in events if isinstance(event, ToolExecutionEndEvent))
    result_end = next(
        event
        for event in events
        if isinstance(event, MessageEndEvent) and isinstance(event.message, ToolResultMessage)
    )
    assert start.tool_call_id == end.tool_call_id == result_end.message.tool_call_id
    assert end.is_error is True
