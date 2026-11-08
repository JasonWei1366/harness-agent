"""Session branch statistics model."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SessionStats:
    """Cumulative activity and billed usage for one active branch."""

    turn_count: int = 0
    tool_call_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cached_input_tokens: int = 0
    cache_write_tokens: int = 0
    latest_prompt_tokens: int = 0
    latest_cached_input_tokens: int = 0
    timed_output_tokens: int = 0
    response_duration_ms: int = 0
    time_to_first_output_ms: int = 0
    timed_first_output_count: int = 0
    estimated_cost: float | None = None

    @property
    def cache_hit_rate(self) -> float | None:
        """Share of prompt tokens served from the provider's cache."""
        if self.input_tokens <= 0:
            return None
        if self.cached_input_tokens == 0 and self.cache_write_tokens == 0:
            return None
        return self.cached_input_tokens / self.input_tokens

    @property
    def latest_cache_hit_rate(self) -> float | None:
        """Share of the latest request's prompt served from cache."""
        if self.latest_prompt_tokens <= 0:
            return None
        if self.cached_input_tokens == 0 and self.cache_write_tokens == 0:
            return None
        return self.latest_cached_input_tokens / self.latest_prompt_tokens

    @property
    def output_tokens_per_second(self) -> float | None:
        """Token-weighted effective output speed across timed responses."""
        if self.timed_output_tokens <= 0 or self.response_duration_ms <= 0:
            return None
        return self.timed_output_tokens * 1000 / self.response_duration_ms

    @property
    def average_time_to_first_output_ms(self) -> float | None:
        """Mean time from request start to the first output event."""
        if self.timed_first_output_count <= 0:
            return None
        return self.time_to_first_output_ms / self.timed_first_output_count
