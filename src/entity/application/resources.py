"""Resource discovery models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ResourceDiagnostic:
    """A non-fatal resource discovery problem or precedence note."""

    kind: str
    message: str
    path: Path | None = None
    name: str | None = None
    severity: str = "warning"

    def format(self) -> str:
        """Return a concise human-readable diagnostic line."""
        parts = [self.severity, self.kind]
        if self.name is not None:
            parts.append(self.name)
        label = " ".join(parts)
        if self.path is None:
            return f"{label}: {self.message}"
        return f"{label}: {self.message} ({self.path})"


@dataclass(frozen=True, slots=True)
class SystemPromptResources:
    """Discovered Tau-native system-prompt file contents and sources."""

    custom_prompt: str | None = None
    custom_prompt_path: Path | None = None
    append_prompt: str | None = None
    append_prompts: tuple[str, ...] = ()
    append_prompt_paths: tuple[Path, ...] = ()
    diagnostics: tuple[ResourceDiagnostic, ...] = ()
