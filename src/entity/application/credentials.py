"""Stored credential shapes persisted under Tau home."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from entity.types import JSONValue


@dataclass(frozen=True, slots=True)
class OAuthCredential:
    """Refreshable OAuth credential persisted under Tau home."""

    access: str
    refresh: str
    expires: int
    account_id: str | None = None
    metadata: dict[str, JSONValue] = field(default_factory=dict)

    def to_json(self) -> dict[str, JSONValue]:
        """Serialize this OAuth credential to JSON-compatible data."""
        result: dict[str, JSONValue] = {
            "type": "oauth",
            "access": self.access,
            "refresh": self.refresh,
            "expires": self.expires,
        }
        if self.account_id is not None:
            result["account_id"] = self.account_id
        if self.metadata:
            result["metadata"] = dict(self.metadata)
        return result


@dataclass(frozen=True, slots=True)
class ApiKeyCredential:
    """API-key credential persisted under Tau home."""

    key: str

    def to_json(self) -> dict[str, JSONValue]:
        """Serialize this API key credential to JSON-compatible data."""
        return {"type": "api_key", "key": self.key}


type StoredCredential = str | ApiKeyCredential | OAuthCredential
type StoredCredentialKind = Literal["api_key", "oauth"]
