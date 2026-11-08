"""Thinking-mode primitives for Tau coding sessions."""

from __future__ import annotations

from collections.abc import Sequence

from entity.application.thinking import (
    DEFAULT_THINKING_LEVEL,
    THINKING_LEVEL_DESCRIPTIONS,
    THINKING_LEVELS,
    ReasoningEffort,
    ThinkingLevel,
    ThinkingParameter,
)

__all__ = [
    "DEFAULT_THINKING_LEVEL",
    "THINKING_LEVELS",
    "THINKING_LEVEL_DESCRIPTIONS",
    "ReasoningEffort",
    "ThinkingLevel",
    "ThinkingParameter",
    "anthropic_thinking_budget_for_level",
    "next_thinking_level",
    "normalize_thinking_level",
    "normalize_thinking_levels",
    "reasoning_effort_for_level",
]


def normalize_thinking_level(value: str | None) -> ThinkingLevel:
    """Return a valid Tau thinking level or raise a user-facing error."""
    if value is None:
        return DEFAULT_THINKING_LEVEL
    normalized = value.strip().lower()
    if normalized in THINKING_LEVELS:
        return normalized
    allowed = ", ".join(THINKING_LEVELS)
    raise ValueError(f"Unknown thinking mode: {value}. Available modes: {allowed}")


def normalize_thinking_levels(values: Sequence[str]) -> tuple[ThinkingLevel, ...]:
    """Return a validated, duplicate-free thinking level tuple."""
    if isinstance(values, str) or not values:
        allowed = ", ".join(THINKING_LEVELS)
        raise ValueError(f"Thinking modes must be a non-empty list. Available modes: {allowed}")

    normalized = tuple(normalize_thinking_level(value) for value in values)
    if len(set(normalized)) != len(normalized):
        raise ValueError("Thinking modes must be unique")
    return normalized


def reasoning_effort_for_level(level: str | None) -> ReasoningEffort:
    """Map Tau's UI thinking level to an OpenAI-compatible reasoning effort."""
    normalized = normalize_thinking_level(level)
    if normalized == "off":
        return "none"
    return normalized


def anthropic_thinking_budget_for_level(level: str | None) -> int | None:
    """Map Tau's UI thinking level to Anthropic extended-thinking tokens."""
    normalized = normalize_thinking_level(level)
    if normalized == "off":
        return None
    return {
        "minimal": 1024,
        "low": 2048,
        "medium": 4096,
        "high": 8192,
        "xhigh": 16384,
        "max": 32768,
    }[normalized]


def next_thinking_level(
    current: str | None,
    *,
    available: tuple[ThinkingLevel, ...] = THINKING_LEVELS,
) -> ThinkingLevel:
    """Return the next thinking level in a stable cycle."""
    if not available:
        return DEFAULT_THINKING_LEVEL
    try:
        normalized_current = normalize_thinking_level(current)
        index = available.index(normalized_current)
    except ValueError:
        return available[0]
    return available[(index + 1) % len(available)]
