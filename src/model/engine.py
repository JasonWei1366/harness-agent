"""Stable streaming engine for model vendors.

Adding a vendor does not change this module. Implement ``VendorCodec.encode``
and a ``StreamParser``: encode the agent turn into a request, and parse raw
response lines into provider events. HTTP, retries, cancellation, and the
assistant-event boundary stay here.
"""

from __future__ import annotations

import ssl
from asyncio import sleep
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import suppress
from dataclasses import dataclass, field
from json import JSONDecodeError, loads
from typing import Any, Literal, Protocol

import httpx
from pydantic import BaseModel, ConfigDict

from agent.assistant_events import (
    AssistantDoneEvent,
    AssistantErrorEvent,
    AssistantMessageEvent,
    AssistantStartEvent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
)
from agent.messages import (
    AgentMessage,
    AssistantMessage,
    AssistantMessageDiagnostic,
    TextContent,
    ThinkingContent,
    Usage,
)
from agent.tools import AgentTool, ToolCall
from agent.types import CancellationToken, JSONValue


@dataclass(frozen=True, slots=True)
class RuntimeProviderAuth:
    """Request auth resolved immediately before a provider call."""

    api_key: str
    base_url: str | None = None
    headers: Mapping[str, str] | None = None


type RuntimeProviderAuthResolver = Callable[[], Awaitable[RuntimeProviderAuth]]
type RuntimeResponseHeadersObserver = Callable[[Mapping[str, str]], None]


class ProviderResponseStartEvent(BaseModel):
    """The provider has started a model response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response_start"] = "response_start"
    model: str
    response_provider: str | None = None


class ProviderRetryEvent(BaseModel):
    """The provider adapter is retrying a transient request failure."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["retry"] = "retry"
    attempt: int
    max_attempts: int
    delay_seconds: float
    message: str
    data: dict[str, JSONValue] | None = None


class ProviderTextDeltaEvent(BaseModel):
    """A streamed text fragment from the provider."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["text_delta"] = "text_delta"
    delta: str


class ProviderThinkingDeltaEvent(BaseModel):
    """A streamed thinking/reasoning fragment from the provider."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["thinking_delta"] = "thinking_delta"
    delta: str


class ProviderToolCallEvent(BaseModel):
    """A complete tool call requested by the model."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["tool_call"] = "tool_call"
    tool_call: ToolCall


class ProviderResponseEndEvent(BaseModel):
    """The provider has completed a model response."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["response_end"] = "response_end"
    message: AssistantMessage
    finish_reason: str | None = None


class ProviderErrorEvent(BaseModel):
    """A provider-level error that can be surfaced by the agent layer."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["error"] = "error"
    message: str
    data: dict[str, JSONValue] | None = None
    response_provider: str | None = None


type ProviderEvent = (
    ProviderResponseStartEvent
    | ProviderRetryEvent
    | ProviderTextDeltaEvent
    | ProviderThinkingDeltaEvent
    | ProviderToolCallEvent
    | ProviderResponseEndEvent
    | ProviderErrorEvent
)


_MAX_ERROR_DETAIL_LENGTH = 1000


def provider_http_error_message(
    *,
    provider_name: str,
    status_code: int,
    body: str,
    model: str | None = None,
) -> str:
    """Return an actionable, secret-free HTTP error message for a provider response."""
    prefix = f"{provider_name} request failed with status {status_code}"
    if model:
        prefix = f"{prefix} for model {model}"
    detail = provider_http_error_detail(body)
    if detail:
        return f"{prefix}: {detail}"
    return prefix


def provider_http_error_detail(body: str) -> str:
    """Extract a concise provider-supplied error detail from an HTTP body."""
    parsed = _loads_error_object(body)
    if parsed is not None:
        detail = provider_error_detail_from_mapping(parsed)
        if detail:
            return detail
    return body.strip()[:_MAX_ERROR_DETAIL_LENGTH]


def provider_error_detail_from_mapping(value: Mapping[str, Any]) -> str:
    """Return the most useful message/code from a provider error object."""
    error = value.get("error")
    if isinstance(error, Mapping):
        message = error.get("message")
        if isinstance(message, str) and message:
            return message
        code = error.get("code")
        if isinstance(code, str) and code:
            return code
    for key in ("message", "detail", "error"):
        detail = value.get(key)
        if isinstance(detail, str) and detail:
            return detail
        if isinstance(detail, Mapping):
            nested = provider_error_detail_from_mapping(detail)
            if nested:
                return nested
    return ""


def _loads_error_object(value: str) -> Mapping[str, Any] | None:
    try:
        parsed = loads(value)
    except JSONDecodeError:
        return None
    return parsed if isinstance(parsed, Mapping) else None


RETRY_POLL_SECONDS = 0.05
RETRY_BASE_DELAY_SECONDS = 0.25

# Transport failures that are safe to retry before any content is emitted.
# httpcore's anyio backend only maps ssl.SSLError during the TLS handshake (to
# ConnectError), so post-handshake record errors such as
# SSLV3_ALERT_BAD_RECORD_MAC escape as raw ssl.SSLError.
RETRYABLE_TRANSPORT_ERRORS: tuple[type[Exception], ...] = (httpx.HTTPError, ssl.SSLError)


def retry_delay_seconds(attempt: int, *, max_delay_seconds: float) -> float:
    """Return an exponential retry delay capped by provider config."""
    if max_delay_seconds <= 0:
        return 0.0
    base_delay = min(RETRY_BASE_DELAY_SECONDS, max_delay_seconds)
    return float(min(max_delay_seconds, base_delay * (2**attempt)))


def provider_retry_event(
    *,
    attempt: int,
    max_retries: int,
    delay_seconds: float,
    reason: str,
    data: dict[str, JSONValue] | None = None,
) -> ProviderRetryEvent:
    """Build a provider-neutral retry progress event."""
    next_attempt = attempt + 2
    max_attempts = max_retries + 1
    delay_suffix = f" in {delay_seconds:g}s" if delay_seconds else ""
    return ProviderRetryEvent(
        attempt=next_attempt,
        max_attempts=max_attempts,
        delay_seconds=delay_seconds,
        message=(
            f"Retrying provider request {next_attempt}/{max_attempts} after {reason}{delay_suffix}."
        ),
        data=data,
    )


async def wait_for_retry(
    delay_seconds: float,
    *,
    signal: CancellationToken | None,
) -> bool:
    """Sleep before a retry while allowing cancellation to interrupt backoff."""
    if delay_seconds <= 0:
        return signal is None or not signal.is_cancelled()

    remaining = delay_seconds
    while remaining > 0:
        if signal is not None and signal.is_cancelled():
            return False
        step = min(RETRY_POLL_SECONDS, remaining)
        await sleep(step)
        remaining -= step
    return signal is None or not signal.is_cancelled()


def _snapshot(message: AssistantMessage) -> AssistantMessage:
    return message.model_copy(deep=True)


async def _end_active_block(
    partial: AssistantMessage,
    index: int | None,
) -> AsyncIterator[AssistantMessageEvent]:
    """End the active text/thinking block before the provider changes channels."""
    if index is None:
        return
    block = partial.content[index]
    if isinstance(block, TextContent):
        yield TextEndEvent(
            content_index=index,
            content=block.text,
            partial=_snapshot(partial),
        )
    elif isinstance(block, ThinkingContent):
        yield ThinkingEndEvent(
            content_index=index,
            content=block.thinking,
            partial=_snapshot(partial),
        )


def _copy_replay_metadata(target: AssistantMessage, source: AssistantMessage) -> None:
    """Copy provider metadata onto streamed blocks without changing their order."""
    source_thinking = [block for block in source.content if isinstance(block, ThinkingContent)]
    target_thinking = [block for block in target.content if isinstance(block, ThinkingContent)]
    for target_block, source_block in zip(target_thinking, source_thinking, strict=False):
        target_block.thinking_signature = source_block.thinking_signature
        target_block.redacted = source_block.redacted

    source_text = [block for block in source.content if isinstance(block, TextContent)]
    target_text = [block for block in target.content if isinstance(block, TextContent)]
    for target_text_block, source_text_block in zip(target_text, source_text, strict=False):
        target_text_block.text_signature = source_text_block.text_signature


def _finish_reason(value: str | None, *, has_tools: bool) -> str:
    if has_tools or value in {"tool_calls", "tool_use", "toolUse"}:
        return "toolUse"
    if value in {"length", "max_tokens", "MAX_TOKENS", "incomplete"}:
        return "length"
    return "stop"


async def canonicalize_provider_stream(
    source: AsyncIterator[ProviderEvent],
    *,
    api: str,
    provider: str,
    model: str,
    independent_channels: bool = False,
) -> AsyncIterator[AssistantMessageEvent]:
    """Canonicalize one old internal parser stream.

    Provider parsers remain isolated behind this private bridge while they are
    migrated incrementally. The public provider protocol exposes only Pi events.
    Chat Completions uses independent channels: a channel switch does not end
    either block. Other transports preserve their sequential block ordering.
    """
    partial = AssistantMessage(api=api, provider=provider, model=model)
    active_index: int | None = None
    active_kind: str | None = None
    channel_indices: dict[str, int] = {}
    started = False
    terminal = False

    async for event in source:
        if isinstance(event, ProviderRetryEvent):
            # Retries are provider-internal at the Pi AI boundary.
            continue
        if isinstance(event, ProviderResponseStartEvent):
            if event.response_provider is not None:
                partial.response_provider = event.response_provider
            if not started:
                started = True
                yield AssistantStartEvent(partial=_snapshot(partial))
            continue
        if not started:
            started = True
            yield AssistantStartEvent(partial=_snapshot(partial))

        if isinstance(event, ProviderTextDeltaEvent):
            if independent_channels:
                active_index = channel_indices.get("text")
                active_kind = "text" if active_index is not None else None
            if active_kind != "text":
                if not independent_channels:
                    async for end_event in _end_active_block(partial, active_index):
                        yield end_event
                active_index = len(partial.content)
                active_kind = "text"
                partial.content.append(TextContent(text=""))
                channel_indices["text"] = active_index
                yield TextStartEvent(content_index=active_index, partial=_snapshot(partial))
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, TextContent)
            block.text += event.delta
            yield TextDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderThinkingDeltaEvent):
            if independent_channels:
                active_index = channel_indices.get("thinking")
                active_kind = "thinking" if active_index is not None else None
            if active_kind != "thinking":
                if not independent_channels:
                    async for end_event in _end_active_block(partial, active_index):
                        yield end_event
                active_index = len(partial.content)
                active_kind = "thinking"
                partial.content.append(ThinkingContent(thinking=""))
                channel_indices["thinking"] = active_index
                yield ThinkingStartEvent(
                    content_index=active_index,
                    partial=_snapshot(partial),
                )
            assert active_index is not None
            block = partial.content[active_index]
            assert isinstance(block, ThinkingContent)
            block.thinking += event.delta
            yield ThinkingDeltaEvent(
                content_index=active_index,
                delta=event.delta,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderToolCallEvent):
            indices = list(channel_indices.values()) if independent_channels else [active_index]
            for index in indices:
                async for end_event in _end_active_block(partial, index):
                    yield end_event
            channel_indices.clear()
            active_index = None
            active_kind = None
            index = len(partial.content)
            partial.content.append(event.tool_call.model_copy(deep=True))
            yield ToolCallStartEvent(content_index=index, partial=_snapshot(partial))
            yield ToolCallEndEvent(
                content_index=index,
                tool_call=event.tool_call,
                partial=_snapshot(partial),
            )
        elif isinstance(event, ProviderResponseEndEvent):
            indices = list(channel_indices.values()) if independent_channels else [active_index]
            for index in indices:
                async for end_event in _end_active_block(partial, index):
                    yield end_event
            channel_indices.clear()
            active_index = None
            active_kind = None

            # Preserve the exact streamed content order. The parser's final
            # message remains authoritative only for response metadata/usage.
            final = event.message.model_copy(deep=True)
            final.api = api
            final.provider = provider
            final.model = model
            final.response_provider = event.message.response_provider or partial.response_provider
            final.content = [block.model_copy(deep=True) for block in partial.content]
            if not final.content and event.message.content:
                final.content = [block.model_copy(deep=True) for block in event.message.content]
            _copy_replay_metadata(final, event.message)
            final.stop_reason = _finish_reason(
                event.finish_reason,
                has_tools=bool(final.tool_calls),
            )  # type: ignore[assignment]
            yield AssistantDoneEvent(reason=final.stop_reason, message=final)  # type: ignore[arg-type]
            terminal = True
        elif isinstance(event, ProviderErrorEvent):
            error = partial.model_copy(deep=True)
            error.response_provider = event.response_provider or partial.response_provider
            error.stop_reason = "error"
            error.error_message = event.message
            error.diagnostics = [
                AssistantMessageDiagnostic(type="provider_error", details=event.data)
            ]
            yield AssistantErrorEvent(reason="error", error=error)
            terminal = True

    if not started:
        yield AssistantStartEvent(partial=_snapshot(partial))
    if not terminal:
        error = partial.model_copy(deep=True)
        error.stop_reason = "error"
        error.error_message = "Provider stream ended without a terminal event"
        error.usage = Usage()
        yield AssistantErrorEvent(reason="error", error=error)



class StreamParser(Protocol):
    """Vendor output parser driven by the shared streaming engine.

    ``feed`` receives each raw response line. Vendors that speak SSE unwrap
    that framing themselves. ``emitted_content`` tells the engine whether a
    dropped connection can still be retried. ``fatal`` means the parser already
    emitted a terminal error and ``finalize`` must not run.
    """

    emitted_content: bool
    fatal: bool

    def feed(self, line: str) -> tuple[list[ProviderEvent], bool]:
        """Consume one response line, returning events and whether to stop."""
        ...

    def finalize(self) -> list[ProviderEvent]:
        """Return the trailing events, including the terminal response."""
        ...


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One provider-neutral model call."""

    model: str
    system: str
    messages: list[AgentMessage]
    tools: list[AgentTool]
    session_id: str | None = None


@dataclass(frozen=True, slots=True)
class EncodedRequest:
    """A vendor's encoded HTTP call plus the parser for its response."""

    path: str
    payload: Mapping[str, JSONValue]
    parser_factory: Callable[[], StreamParser]
    api: str
    independent_channels: bool = True
    headers: Mapping[str, str] = field(default_factory=dict)
    trailing_headers: Mapping[str, str] = field(default_factory=dict)


class VendorCodec(Protocol):
    """The only extension point for a model vendor.

    ``encode`` is the input parser: agent messages in, request path, JSON body,
    and headers out. The parser factory on that request is the output parser.
    """

    def encode(self, turn: ModelTurn) -> EncodedRequest:
        """Encode one turn and choose the parser for its response."""
        ...


class VendorTransport(Protocol):
    """Connection settings the engine reads for every vendor."""

    @property
    def api_key(self) -> str: ...

    @property
    def base_url(self) -> str: ...

    @property
    def headers(self) -> Mapping[str, str] | None: ...

    @property
    def timeout_seconds(self) -> float: ...

    @property
    def max_retries(self) -> int: ...

    @property
    def max_retry_delay_seconds(self) -> float: ...

    @property
    def provider_name(self) -> str: ...

    @property
    def response_provider_header(self) -> str | None: ...

    @property
    def omit_authorization_header(self) -> bool: ...

    @property
    def credential_resolver(self) -> RuntimeProviderAuthResolver | None: ...

    @property
    def response_headers_observer(self) -> RuntimeResponseHeadersObserver | None: ...


def _response_header_value(response: httpx.Response, header_name: str | None) -> str | None:
    """Return one normalized response metadata header when configured."""
    if header_name is None:
        return None
    value = response.headers.get(header_name)
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


def _append_response_observer_diagnostic(
    events: list[ProviderEvent],
    exc: Exception,
) -> None:
    for event in events:
        if isinstance(event, ProviderResponseEndEvent):
            diagnostic = AssistantMessageDiagnostic(
                type="response_headers_observer_error",
                details={
                    "error": str(exc),
                    "error_type": type(exc).__name__,
                },
            )
            event.message.diagnostics = [
                *(event.message.diagnostics or []),
                diagnostic,
            ]
            return


def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429} or status_code >= 500


class VendorProvider:
    """Run any vendor codec through the fixed HTTP and event pipeline."""

    def __init__(
        self,
        codec: VendorCodec,
        transport: VendorTransport,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._codec = codec
        self._transport = transport
        self._client = client
        self._owns_client = client is None

    async def aclose(self) -> None:
        """Close the underlying HTTP client if this provider created it."""
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def stream_response(
        self,
        *,
        model: str,
        system: str,
        messages: list[AgentMessage],
        tools: list[AgentTool],
        signal: CancellationToken | None = None,
        session_id: str | None = None,
    ) -> AsyncIterator[AssistantMessageEvent]:
        """Encode one turn with the vendor, then stream assistant events."""
        turn = ModelTurn(
            model=model,
            system=system,
            messages=messages,
            tools=tools,
            session_id=session_id,
        )
        encoded = self._codec.encode(turn)
        raw = self._stream(encoded, model=model, signal=signal)
        return canonicalize_provider_stream(
            raw,
            api=encoded.api,
            provider=self._transport.provider_name,
            model=model,
            independent_channels=encoded.independent_channels,
        )

    def _stream(
        self,
        encoded: EncodedRequest,
        *,
        model: str,
        signal: CancellationToken | None,
    ) -> AsyncIterator[ProviderEvent]:
        """POST one encoded request, retrying before any content is emitted."""

        async def iterator() -> AsyncIterator[ProviderEvent]:
            client = self._get_client()
            transport = self._transport
            api_key = transport.api_key
            request_url = f"{transport.base_url.rstrip('/')}{encoded.path}"
            headers = dict(transport.headers or {})
            headers.update(encoded.headers)
            if transport.credential_resolver is not None:
                auth = await transport.credential_resolver()
                api_key = auth.api_key
                headers.update(auth.headers or {})
                if auth.base_url is not None:
                    request_url = f"{auth.base_url.rstrip('/')}{encoded.path}"
            if not transport.omit_authorization_header:
                has_authorization = any(key.casefold() == "authorization" for key in headers)
                if not has_authorization:
                    headers["Authorization"] = f"Bearer {api_key}"
            headers.update(encoded.trailing_headers)

            attempt = 0
            while True:
                parser = encoded.parser_factory()
                try:
                    async with client.stream(
                        "POST", request_url, json=encoded.payload, headers=headers
                    ) as response:
                        response_provider = _response_header_value(
                            response,
                            transport.response_provider_header,
                        )
                        if response.status_code >= 400:
                            body = await response.aread()
                            body_text = body.decode(errors="replace")
                            if self._should_retry(attempt, status_code=response.status_code):
                                delay = retry_delay_seconds(
                                    attempt,
                                    max_delay_seconds=transport.max_retry_delay_seconds,
                                )
                                yield provider_retry_event(
                                    attempt=attempt,
                                    max_retries=transport.max_retries,
                                    delay_seconds=delay,
                                    reason=f"HTTP {response.status_code}",
                                    data={
                                        "status_code": response.status_code,
                                        "body": body_text,
                                    },
                                )
                                attempt += 1
                                if not await wait_for_retry(delay, signal=signal):
                                    return
                                continue
                            yield ProviderErrorEvent(
                                message=provider_http_error_message(
                                    provider_name=transport.provider_name,
                                    status_code=response.status_code,
                                    body=body_text,
                                    model=model,
                                ),
                                data={
                                    "status_code": response.status_code,
                                    "body": body_text,
                                    "attempts": attempt + 1,
                                },
                                response_provider=response_provider,
                            )
                            return

                        yield ProviderResponseStartEvent(
                            model=model,
                            response_provider=response_provider,
                        )

                        async for line in response.aiter_lines():
                            if signal is not None and signal.is_cancelled():
                                return
                            events, stop = parser.feed(line)
                            for parser_event in events:
                                yield parser_event
                            if stop:
                                break

                        if parser.fatal:
                            return
                        final_events = parser.finalize()
                        observer = transport.response_headers_observer
                        if observer is not None:
                            try:
                                observer(dict(response.headers))
                            except Exception as exc:
                                with suppress(Exception):
                                    _append_response_observer_diagnostic(final_events, exc)
                        for parser_event in final_events:
                            yield parser_event
                        return
                except RETRYABLE_TRANSPORT_ERRORS as exc:
                    if not parser.emitted_content and self._should_retry(attempt):
                        delay = retry_delay_seconds(
                            attempt,
                            max_delay_seconds=transport.max_retry_delay_seconds,
                        )
                        yield provider_retry_event(
                            attempt=attempt,
                            max_retries=transport.max_retries,
                            delay_seconds=delay,
                            reason="network error",
                            data={
                                "error": str(exc),
                                "error_type": type(exc).__name__,
                            },
                        )
                        attempt += 1
                        if not await wait_for_retry(delay, signal=signal):
                            return
                        continue
                    yield ProviderErrorEvent(
                        message=str(exc),
                        data={"attempts": attempt + 1},
                    )
                    return

        return iterator()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._transport.timeout_seconds)
        return self._client

    def _should_retry(self, attempt: int, *, status_code: int | None = None) -> bool:
        if attempt >= self._transport.max_retries:
            return False
        return status_code is None or _is_transient_status(status_code)
