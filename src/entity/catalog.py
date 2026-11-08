"""Runtime model catalog metadata."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RuntimeModelLimits:
    """Provider-reported limits for one model on the active serving surface."""

    context_window: int
    max_output_tokens: int | None = None
    effective_context_window_percent: int = 100
    auto_compact_token_limit: int | None = None

    def __post_init__(self) -> None:
        if self.context_window <= 0:
            raise ValueError("context_window must be positive")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if not 1 <= self.effective_context_window_percent <= 100:
            raise ValueError("effective_context_window_percent must be between 1 and 100")
        if self.auto_compact_token_limit is not None and self.auto_compact_token_limit <= 0:
            raise ValueError("auto_compact_token_limit must be positive")

    @property
    def effective_context_window(self) -> int:
        """Return the provider's usable window after its requested headroom."""
        return max(1, self.context_window * self.effective_context_window_percent // 100)

    @property
    def effective_auto_compact_token_limit(self) -> int:
        """Return an explicit limit or the Codex-compatible 90% default."""
        default_limit = max(1, self.context_window * 9 // 10)
        if self.auto_compact_token_limit is None:
            return min(default_limit, self.effective_context_window)
        return min(self.auto_compact_token_limit, self.effective_context_window)


RuntimeInputModality = Literal["text", "image"]
RuntimeThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True, slots=True)
class RuntimeModel:
    """One model advertised by an authenticated provider catalog."""

    id: str
    name: str | None = None
    limits: RuntimeModelLimits | None = None
    input_modalities: tuple[RuntimeInputModality, ...] = ("text",)
    thinking_levels: tuple[RuntimeThinkingLevel, ...] = ()
    default_thinking_level: RuntimeThinkingLevel | None = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("model id must be non-empty")
        if not self.input_modalities:
            raise ValueError("input_modalities must be non-empty")
        if self.default_thinking_level is not None and (
            self.default_thinking_level not in self.thinking_levels
        ):
            raise ValueError("default_thinking_level must be advertised in thinking_levels")


@dataclass(frozen=True, slots=True)
class RuntimeModelCatalog:
    """Complete account-specific model snapshot from a provider."""

    models: tuple[RuntimeModel, ...]

    def model(self, model_id: str) -> RuntimeModel | None:
        """Return one advertised model by exact ID."""
        return next((model for model in self.models if model.id == model_id), None)
