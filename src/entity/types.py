"""Shared low-level types for Tau's portable agent layer."""

from __future__ import annotations

from typing import Protocol

# Pydantic needs PEP 695 named recursive aliases for JSON-like values.
type JSONPrimitive = str | int | float | bool | None
type JSONValue = JSONPrimitive | list[JSONValue] | dict[str, JSONValue]
type JSONObject = dict[str, JSONValue]


class CancellationToken(Protocol):
    """Object the loop passes so a model stream or tool can see a cancel request."""

    def is_cancelled(self) -> bool:
        """Return whether the current operation should stop."""
        ...
