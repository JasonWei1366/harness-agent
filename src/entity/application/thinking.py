"""Thinking-level type aliases and constants."""

from __future__ import annotations

from typing import Literal

ThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"]
ThinkingParameter = Literal["reasoning_effort", "reasoning.effort", "anthropic.thinking"]
ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]

THINKING_LEVELS: tuple[ThinkingLevel, ...] = (
    "off",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "max",
)
DEFAULT_THINKING_LEVEL: ThinkingLevel = "medium"

THINKING_LEVEL_DESCRIPTIONS: dict[ThinkingLevel, str] = {
    "off": "No reasoning",
    "minimal": "Very brief reasoning",
    "low": "Light reasoning",
    "medium": "Moderate reasoning",
    "high": "Deep reasoning",
    "xhigh": "Very deep reasoning",
    "max": "Maximum reasoning",
}
