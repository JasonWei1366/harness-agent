"""Token usage dashboard models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class RequestUsage:
    """Token usage for a single assistant response."""

    number: int
    kind: str
    timestamp: str
    provider: str
    model: str
    response_provider: str | None
    fresh: int
    cached: int
    cache_write: int
    cache_write_1h: int
    output: int
    reasoning: int
    stop_reason: str
    estimated_cost: float | None

    @property
    def prompt(self) -> int:
        return self.fresh + self.cached + self.cache_write

    @property
    def hit_rate(self) -> float:
        return self.cached / self.prompt if self.prompt else 0.0


@dataclass(frozen=True, slots=True)
class UsageEvent:
    """A notable session event positioned against the next model request."""

    request_number: int
    timestamp: str
    kind: str
    label: str
    position: Literal["before", "after"] = "before"


@dataclass(frozen=True, slots=True)
class SessionUsage:
    """Aggregated usage for the entries shown in an export."""

    requests: tuple[RequestUsage, ...]
    tool_calls: tuple[tuple[str, int], ...]
    compactions: int
    events: tuple[UsageEvent, ...] = ()

    @property
    def total_fresh(self) -> int:
        return sum(item.fresh for item in self.requests)

    @property
    def total_cached(self) -> int:
        return sum(item.cached for item in self.requests)

    @property
    def total_cache_write(self) -> int:
        return sum(item.cache_write for item in self.requests)

    @property
    def total_prompt(self) -> int:
        return self.total_fresh + self.total_cached + self.total_cache_write

    @property
    def total_output(self) -> int:
        return sum(item.output for item in self.requests)

    @property
    def hit_rate(self) -> float | None:
        if self.total_prompt <= 0:
            return None
        if self.total_cached == 0 and self.total_cache_write == 0:
            return None
        return self.total_cached / self.total_prompt

    @property
    def total_cost(self) -> float | None:
        costs = [item.estimated_cost for item in self.requests if item.estimated_cost is not None]
        return sum(costs) if costs else None
