"""Skill resource models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Skill:
    """A markdown skill resource."""

    name: str
    path: Path
    content: str
    description: str | None = None
    disable_model_invocation: bool = False


@dataclass(frozen=True, slots=True)
class SkillInvocation:
    """Parsed expanded skill invocation message."""

    name: str
    location: str
    content: str
    additional_instructions: str | None = None
