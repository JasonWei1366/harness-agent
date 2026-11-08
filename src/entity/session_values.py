"""Value objects used by the coding session service."""

from __future__ import annotations

from dataclasses import dataclass

from entity.messages import AgentMessage, Usage
from entity.session.entries import CustomMessageEntry, MessageEntry


@dataclass(frozen=True, slots=True)
class ModelChoice:
    """A selectable model and the provider that serves it."""

    provider_name: str
    model: str


@dataclass(frozen=True, slots=True)
class ModelSelectionResult:
    """Result of a candidate-first provider/model selection."""

    choice: ModelChoice
    changed: bool


@dataclass(frozen=True, slots=True)
class TerminalCommandResult:
    """Result of an input-bar terminal command."""

    command: str
    output: str
    exit_code: int | None
    ok: bool
    added_to_context: bool


@dataclass(frozen=True, slots=True)
class SessionTreeChoice:
    """One branchable entry in the active session tree."""

    entry_id: str
    label: str
    active: bool = False
    is_tool_call: bool = False
    bookmark_label: str | None = None
    label_timestamp: float | None = None


@dataclass(frozen=True, slots=True)
class SessionTreeBranchResult:
    """Result of moving the active session tree leaf."""

    message: str
    input_prefill: str | None = None


@dataclass(frozen=True, slots=True)
class TerminalCommandRequest:
    """Parsed input-bar terminal command request."""

    command: str
    add_to_context: bool


@dataclass(frozen=True, slots=True)
class CompactionPlan:
    """Prepared active-context entries for a compaction run."""

    first_kept_entry_id: str
    replaced_entry_count: int
    messages_to_summarize: tuple[AgentMessage, ...]


@dataclass(frozen=True, slots=True)
class GeneratedSummary:
    """Summary text paired with the provider usage spent producing it."""

    text: str
    usage: Usage | None
    provider: str | None = None
    model: str | None = None
    response_provider: str | None = None


@dataclass(frozen=True, slots=True)
class ManualCompactionResult:
    """Structured result from one manual compaction."""

    summary: str
    first_kept_entry_id: str
    tokens_before: int
    estimated_tokens_after: int
    replaced_entry_count: int


@dataclass(frozen=True, slots=True)
class PendingMessageWrite:
    """Stable entry retained while a message persistence attempt is retried."""

    message: AgentMessage
    entry: MessageEntry | CustomMessageEntry
