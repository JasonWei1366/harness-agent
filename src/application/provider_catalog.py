"""Built-in provider catalog for Tau login/setup flows."""

from __future__ import annotations

from entity.application.provider_catalog import (
    AuthMethod,
    ModelCatalogMetadata,
    ModelCostTier,
    ModelInput,
    ProviderApi,
    ProviderCatalogEntry,
    ProviderKind,
    ThinkingLevelMap,
)

__all__ = [
    "AuthMethod",
    "BUILTIN_PROVIDER_CATALOG",
    "ModelCatalogMetadata",
    "ModelCostTier",
    "ModelInput",
    "ProviderApi",
    "ProviderCatalogEntry",
    "ProviderKind",
    "ThinkingLevelMap",
    "builtin_provider_entry",
    "model_cost_for_input_tokens",
]


def model_cost_for_input_tokens(
    metadata: ModelCatalogMetadata,
    input_tokens: int,
) -> dict[str, float] | None:
    """Return model rates for an input size, falling back to the flat base cost."""
    if not isinstance(input_tokens, int) or isinstance(input_tokens, bool) or input_tokens < 0:
        raise ValueError("input_tokens must be a non-negative integer")
    for tier in metadata.cost_tiers:
        if tier.max_input_tokens is None or input_tokens <= tier.max_input_tokens:
            return dict(tier.cost)
    return dict(metadata.cost) if metadata.cost is not None else None


def _load_builtin_catalog() -> tuple[ProviderCatalogEntry, ...]:
    # Imported lazily: catalog_loader imports ProviderCatalogEntry from this module.
    from application.catalog_loader import builtin_catalog

    return builtin_catalog()


BUILTIN_PROVIDER_CATALOG: tuple[ProviderCatalogEntry, ...] = _load_builtin_catalog()


def builtin_provider_entry(name: str) -> ProviderCatalogEntry | None:
    """Return a built-in catalog entry by provider name."""
    for entry in BUILTIN_PROVIDER_CATALOG:
        if entry.name == name:
            return entry
    return None
