"""Append-only session tree primitives for Tau."""

from __future__ import annotations

from agent.session.jsonl import (
    SessionJsonlError,
    entries_from_json_lines,
    entry_from_json_line,
    entry_to_json_line,
)
from agent.session.memory import SessionState
from agent.session.storage import InMemorySessionStorage, JsonlSessionStorage, SessionStorage
from agent.session.tree import SessionTreeError, entries_by_id, path_to_entry
from entity.session.entries import (
    BaseSessionEntry,
    BranchSummaryEntry,
    CompactionEntry,
    CustomEntry,
    CustomMessageEntry,
    LabelEntry,
    LeafEntry,
    MessageEntry,
    ModelChangeEntry,
    SessionEntry,
    SessionInfoEntry,
    ThinkingLevelChangeEntry,
)

__all__ = [
    "BaseSessionEntry",
    "BranchSummaryEntry",
    "CompactionEntry",
    "CustomEntry",
    "CustomMessageEntry",
    "InMemorySessionStorage",
    "JsonlSessionStorage",
    "LabelEntry",
    "LeafEntry",
    "MessageEntry",
    "ModelChangeEntry",
    "SessionEntry",
    "SessionInfoEntry",
    "SessionJsonlError",
    "SessionState",
    "SessionStorage",
    "SessionTreeError",
    "ThinkingLevelChangeEntry",
    "entries_by_id",
    "entries_from_json_lines",
    "entry_from_json_line",
    "entry_to_json_line",
    "path_to_entry",
]
