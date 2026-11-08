"""Runtime model catalog capabilities."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from entity.catalog import (
    RuntimeInputModality,
    RuntimeModel,
    RuntimeModelCatalog,
    RuntimeModelLimits,
    RuntimeThinkingLevel,
)

__all__ = [
    "ModelCatalogProvider",
    "ModelLimitsProvider",
    "RuntimeInputModality",
    "RuntimeModel",
    "RuntimeModelCatalog",
    "RuntimeModelLimits",
    "RuntimeThinkingLevel",
]


@runtime_checkable
class ModelLimitsProvider(Protocol):
    """Optional provider capability for serving-surface-specific model limits."""

    async def discover_model_limits(self, model: str) -> RuntimeModelLimits | None:
        """Return live limits for ``model``, or ``None`` when it is not advertised."""
        ...


@runtime_checkable
class ModelCatalogProvider(Protocol):
    """Optional provider capability for authenticated model discovery."""

    async def discover_models(self) -> RuntimeModelCatalog:
        """Return the complete model inventory available to the active account."""
        ...
