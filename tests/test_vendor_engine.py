"""A new vendor supplies request encoding and response parsing only."""

import json

import httpx
import pytest

from agent.assistant_events import AssistantDoneEvent
from agent.messages import AssistantMessage, TextContent
from model.engine import (
    EncodedRequest,
    ModelTurn,
    ProviderResponseEndEvent,
    ProviderTextDeltaEvent,
    VendorProvider,
)


class _LineParser:
    def __init__(self) -> None:
        self.emitted_content = False
        self.fatal = False

    def feed(self, line: str) -> tuple[list[ProviderTextDeltaEvent], bool]:
        if line.strip() == "data: [DONE]":
            return [], True
        if line.startswith("data: "):
            self.emitted_content = True
            return [ProviderTextDeltaEvent(delta=line.removeprefix("data: ").strip())], False
        return [], False

    def finalize(self) -> list[ProviderResponseEndEvent]:
        return [
            ProviderResponseEndEvent(
                message=AssistantMessage(model="m", content=[TextContent(text="ok")]),
                finish_reason="stop",
            )
        ]


class _Codec:
    def encode(self, turn: ModelTurn) -> EncodedRequest:
        return EncodedRequest(
            path="/vendor",
            payload={"model": turn.model, "echo": True},
            parser_factory=_LineParser,
            api="vendor",
        )


class _Transport:
    api_key = "secret"
    base_url = "https://vendor.test/v1"
    headers = None
    timeout_seconds = 5.0
    max_retries = 0
    max_retry_delay_seconds = 0.0
    provider_name = "example"
    response_provider_header = None
    omit_authorization_header = False
    credential_resolver = None
    response_headers_observer = None


@pytest.mark.anyio
async def test_vendor_codec_only_supplies_request_and_parser() -> None:
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        seen["authorization"] = request.headers["authorization"]
        return httpx.Response(200, text="data: ok\n\ndata: [DONE]\n\n")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = VendorProvider(_Codec(), _Transport(), client=client)
        events = [
            event
            async for event in provider.stream_response(
                model="m", system="s", messages=[], tools=[]
            )
        ]

    assert seen == {
        "path": "/v1/vendor",
        "body": {"model": "m", "echo": True},
        "authorization": "Bearer secret",
    }
    done = events[-1]
    assert isinstance(done, AssistantDoneEvent)
    assert done.message.text == "ok"
