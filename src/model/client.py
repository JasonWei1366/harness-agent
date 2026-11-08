"""Open a model client from project settings.

Vendor wire formats live beside this module. ``engine`` is the fixed pipeline.
``openai`` is the OpenAI-compatible input and output codec.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from tomllib import load
from typing import Protocol

from agent.assistant_events import AssistantMessageEvent
from agent.messages import AgentMessage
from agent.tools import AgentTool
from agent.types import CancellationToken
from entity.model.settings import ModelSettings
from model.engine import RuntimeProviderAuth
from model.openai import (
    DEFAULT_OPENAI_COMPATIBLE_BASE_URL,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
    DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
    DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
)

__all__ = [
    "DEFAULT_OPENAI_COMPATIBLE_BASE_URL",
    "DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES",
    "DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS",
    "DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS",
    "FakeProvider",
    "ModelProvider",
    "ModelSettings",
    "OpenAICompatibleConfig",
    "OpenAICompatibleProvider",
    "RuntimeProviderAuth",
    "bind_client",
    "load_settings",
    "open_client",
    "stream_response",
    "use_client",
]


class ModelProvider(Protocol):
    """Client installed for ``stream_response``. Vendor wire formats stay inside it."""

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
        """Stream one model response as assistant message events."""
        ...


_current_client: ContextVar[ModelProvider | None] = ContextVar("model_client", default=None)


def load_settings(path: Path) -> ModelSettings:
    """Read ``api_key`` and ``base_url`` from a TOML config file."""
    if not path.is_file():
        raise FileNotFoundError(f"Model config not found: {path}")
    with path.open("rb") as handle:
        raw = load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Model config must be a TOML table")
    api_key = raw.get("api_key")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("Model config requires api_key")
    base_url = raw.get("base_url", DEFAULT_OPENAI_COMPATIBLE_BASE_URL)
    if not isinstance(base_url, str) or not base_url.strip():
        raise ValueError("Model config base_url must be a non-empty string")
    return ModelSettings(
        api_key=api_key.strip(),
        base_url=base_url.strip().rstrip("/"),
        timeout_seconds=_positive_float(
            raw.get("timeout_seconds"),
            default=DEFAULT_OPENAI_COMPATIBLE_TIMEOUT_SECONDS,
        ),
        max_retries=_non_negative_int(
            raw.get("max_retries"),
            default=DEFAULT_OPENAI_COMPATIBLE_MAX_RETRIES,
        ),
        max_retry_delay_seconds=_non_negative_float(
            raw.get("max_retry_delay_seconds"),
            default=DEFAULT_OPENAI_COMPATIBLE_MAX_RETRY_DELAY_SECONDS,
        ),
    )


def open_client(settings: ModelSettings) -> OpenAICompatibleProvider:
    """Build the OpenAI client and install it for later ``stream_response`` calls."""
    client = OpenAICompatibleProvider(
        OpenAICompatibleConfig(
            api_key=settings.api_key,
            base_url=settings.base_url,
            timeout_seconds=settings.timeout_seconds,
            max_retries=settings.max_retries,
            max_retry_delay_seconds=settings.max_retry_delay_seconds,
            provider_name="openai",
        )
    )
    use_client(client)
    return client


def use_client(client: ModelProvider) -> Token[ModelProvider | None]:
    """Install ``client`` for ``stream_response`` in this task and its child tasks."""
    return _current_client.set(client)


@contextmanager
def bind_client(client: ModelProvider) -> Iterator[None]:
    """Install ``client`` until the with-block ends."""
    token = use_client(client)
    try:
        yield
    finally:
        _current_client.reset(token)


def stream_response(
    *,
    model: str,
    system: str,
    messages: list[AgentMessage],
    tools: list[AgentTool],
    signal: CancellationToken | None = None,
    session_id: str | None = None,
) -> AsyncIterator[AssistantMessageEvent]:
    """Stream one turn from the client installed for this task.

    The return values are the project's assistant events. Vendor wire formats
    stay inside the installed client.
    """
    client = _current_client.get()
    if client is None:
        raise RuntimeError("Model client is not open")
    return client.stream_response(
        model=model,
        system=system,
        messages=messages,
        tools=tools,
        signal=signal,
        session_id=session_id,
    )


def _positive_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Model config timeout_seconds must be a number")
    if value <= 0:
        raise ValueError("Model config timeout_seconds must be greater than 0")
    return float(value)


def _non_negative_int(value: object, *, default: int) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("Model config max_retries must be an integer")
    if value < 0:
        raise ValueError("Model config max_retries must be 0 or greater")
    return value


def _non_negative_float(value: object, *, default: float) -> float:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("Model config max_retry_delay_seconds must be a number")
    if value < 0:
        raise ValueError("Model config max_retry_delay_seconds must be 0 or greater")
    return float(value)


class FakeProvider:
    """A provider that replays predefined assistant event streams."""

    def __init__(self, streams: Iterable[Iterable[AssistantMessageEvent]]) -> None:
        self._streams = [list(stream) for stream in streams]
        self.calls: list[tuple[str, str, list[AgentMessage], list[AgentTool]]] = []
        self.session_ids: list[str | None] = []

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
        self.calls.append((model, system, list(messages), list(tools)))
        self.session_ids.append(session_id)
        stream = self._streams.pop(0) if self._streams else []

        async def iterator() -> AsyncIterator[AssistantMessageEvent]:
            for event in stream:
                if signal is not None and signal.is_cancelled():
                    return
                yield event

        return iterator()
