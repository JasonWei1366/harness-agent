"""Provider-neutral OAuth contracts used by Tau's coding application."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Protocol

from entity.application.credentials import OAuthCredential
from entity.application.oauth import (
    AuthCallback,
    DeviceCodeCallback,
    ManualCodeCallback,
    OAuthAuthInfo,
    OAuthDeviceCodeInfo,
    OAuthFlowKind,
    OAuthLoginCallbacks,
    OAuthPrompt,
    OAuthRuntimeAuth,
    OAuthSelectOption,
    OAuthSelectPrompt,
    ProgressCallback,
    PromptCallback,
    SelectCallback,
)
from entity.types import JSONValue

__all__ = [
    "AuthCallback",
    "DeviceCodeCallback",
    "ManualCodeCallback",
    "OAuthAuthInfo",
    "OAuthCredential",
    "OAuthDeviceCodeInfo",
    "OAuthFlowKind",
    "OAuthLoginCallbacks",
    "OAuthPrompt",
    "OAuthProvider",
    "OAuthRuntimeAuth",
    "OAuthSelectOption",
    "OAuthSelectPrompt",
    "ProgressCallback",
    "PromptCallback",
    "SelectCallback",
    "oauth_metadata_string",
]


class OAuthProvider(Protocol):
    """Provider-specific OAuth behavior registered with Tau."""

    @property
    def id(self) -> str:
        """Stable provider/credential identifier."""
        ...

    @property
    def name(self) -> str:
        """User-facing provider name."""
        ...

    @property
    def flow_kinds(self) -> Sequence[OAuthFlowKind]:
        """Interactive flow families supported by this provider."""
        ...

    async def login(self, callbacks: OAuthLoginCallbacks) -> OAuthCredential:
        """Complete login and return credentials to persist."""
        ...

    async def refresh(self, credential: OAuthCredential) -> OAuthCredential:
        """Refresh an expired credential."""
        ...

    def runtime_auth(self, credential: OAuthCredential) -> OAuthRuntimeAuth:
        """Convert stored credentials to request auth."""
        ...


def oauth_metadata_string(
    metadata: Mapping[str, JSONValue],
    name: str,
) -> str | None:
    """Return one non-empty string from provider-specific OAuth metadata."""
    value = metadata.get(name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
