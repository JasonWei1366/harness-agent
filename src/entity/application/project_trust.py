"""Project trust policy data models."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

TrustDefault = Literal["ask", "always", "never"]
TrustDecision = Literal["trusted", "untrusted"]
TrustOverride = Literal["approve", "decline"]
TrustScope = Literal["exact", "parent", "run"]
TrustSource = Literal["override", "empty", "extension", "saved", "default", "ui"]
TrustChoice = Literal["trust-exact", "trust-parent", "trust-run", "decline-exact", "decline-run"]


@dataclass(frozen=True, slots=True)
class CanonicalProjectPath:
    """An existing, canonical project working directory."""

    value: Path


@dataclass(frozen=True, slots=True)
class ProtectedResourceSummary:
    """Bounded metadata-only summary of protected project inputs."""

    cwd: CanonicalProjectPath
    categories: tuple[str, ...]
    counts: Mapping[str, int]
    sample_paths: tuple[Path, ...] = ()

    @property
    def total(self) -> int:
        return sum(self.counts.values())


@dataclass(frozen=True, slots=True)
class SavedTrustEntry:
    """A validated saved exact or inherited decision."""

    path: CanonicalProjectPath
    decision: TrustDecision


@dataclass(frozen=True, slots=True)
class ProjectTrustRequest:
    """Frontend-neutral request for an interactive trust decision."""

    cwd: CanonicalProjectPath
    resources: ProtectedResourceSummary
    inherited_entry: SavedTrustEntry | None
    choices: tuple[TrustChoice, ...] = (
        "trust-exact",
        "trust-parent",
        "trust-run",
        "decline-exact",
        "decline-run",
    )


@dataclass(frozen=True, slots=True)
class ProjectTrustResolution:
    """Completed decision for one canonical cwd."""

    trusted: bool
    source: TrustSource
    saved_path: CanonicalProjectPath | None = None
    diagnostics: tuple[str, ...] = ()
    had_candidates: bool = True
    cancelled: bool = False
    needs_persistence: bool = False


@dataclass(frozen=True, slots=True)
class ExtensionTrustResult:
    """Result returned by an eligible pre-trust extension."""

    decision: Literal["approve", "decline", "defer"] = "defer"
    remember: bool = False


@dataclass(frozen=True, slots=True)
class ProjectTrustEvent:
    """Content-free payload sent to eligible pre-trust extensions."""

    cwd: Path
    mode: Literal["interactive", "headless"]
    has_ui: bool
    categories: tuple[str, ...]
    counts: Mapping[str, int]
