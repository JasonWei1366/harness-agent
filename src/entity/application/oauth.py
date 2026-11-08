"""OAuth flow data models."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Literal

OAuthFlowKind = Literal["browser", "device_code"]


@dataclass(frozen=True, slots=True)
class OAuthAuthInfo:
    """Authorization URL and optional instructions for a browser flow."""

    url: str
    instructions: str | None = None


@dataclass(frozen=True, slots=True)
class OAuthDeviceCodeInfo:
    """User-facing values returned by an OAuth device authorization request."""

    user_code: str
    verification_uri: str
    interval_seconds: float | None = None
    expires_in_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class OAuthPrompt:
    """Text input requested by an OAuth provider before or during login."""

    message: str
    placeholder: str | None = None
    allow_empty: bool = False


@dataclass(frozen=True, slots=True)
class OAuthSelectOption:
    """One choice in a provider-defined OAuth selection prompt."""

    id: str
    label: str


@dataclass(frozen=True, slots=True)
class OAuthSelectPrompt:
    """Selection input requested by an OAuth provider."""

    message: str
    options: tuple[OAuthSelectOption, ...]


@dataclass(frozen=True, slots=True)
class OAuthRuntimeAuth:
    """Request authentication derived from a stored OAuth credential."""

    api_key: str
    base_url: str | None = None
    headers: Mapping[str, str] | None = None


AuthCallback = Callable[[OAuthAuthInfo], None]
DeviceCodeCallback = Callable[[OAuthDeviceCodeInfo], None]
PromptCallback = Callable[[OAuthPrompt], Awaitable[str]]
SelectCallback = Callable[[OAuthSelectPrompt], Awaitable[str | None]]
ManualCodeCallback = Callable[[], Awaitable[str]]
ProgressCallback = Callable[[str], None]


@dataclass(frozen=True, slots=True)
class OAuthLoginCallbacks:
    """Frontend-independent callbacks available to an OAuth login flow."""

    on_auth: AuthCallback
    on_device_code: DeviceCodeCallback
    on_prompt: PromptCallback
    on_select: SelectCallback
    on_progress: ProgressCallback | None = None
    on_manual_code_input: ManualCodeCallback | None = None
    method: OAuthFlowKind | None = None
