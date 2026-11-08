"""Agent-call diagnostic context model."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AgentCallDiagnosticContext:
    """Non-secret context attached to an agent-call diagnostic entry."""

    provider_name: str
    model: str
    cwd: Path
    session_id: str | None
    run_id: str
