"""Runtime provider construction for Tau coding sessions."""

from __future__ import annotations

import asyncio
from asyncio import AbstractEventLoop, get_running_loop
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import replace
from inspect import isawaitable
from os import environ
from typing import Protocol
from weakref import WeakKeyDictionary

from application.credentials import FileCredentialStore, OAuthCredential
from application.extensions.providers import (
    CredentialReader,
    DynamicProvider,
    OpenAICompatibleTransport,
    ProviderAuthError,
    ProviderModel,
    ProviderRuntimeContext,
    RequiredApiKey,
    ResolvedProviderAuth,
    _MissingRequiredApiKeyError,
    json_compatible_mapping,
    resolve_provider_auth,
)
from application.oauth_registry import get_oauth_provider
from application.oauth_types import OAuthProvider
from application.provider_config import (
    AnthropicProviderConfig,
    OpenAICodexProviderConfig,
    OpenAICompatibleProviderConfig,
    ProviderConfig,
    ProviderConfigError,
    openai_compatible_config_from_provider,
    validate_huggingface_inference_provider,
    validate_provider_model,
)
from application.thinking import ThinkingLevel
from model.client import (
    ModelProvider,
    OpenAICompatibleConfig,
    OpenAICompatibleProvider,
    RuntimeProviderAuth,
)


class ClosableModelProvider(ModelProvider, Protocol):
    """Runtime provider object Tau owns and can close."""

    async def aclose(self) -> None:
        """Close any provider-owned resources."""
        ...


async def create_dynamic_model_provider(
    provider: DynamicProvider,
    *,
    model: str,
    credential_store: CredentialReader | None = None,
    environment: Mapping[str, str] | None = None,
) -> ClosableModelProvider:
    """Create a candidate runtime from a process-local provider definition.

    Authentication is resolved only here, immediately before construction.
    This path never converts or writes the dynamic definition to durable
    ``ProviderConfig`` settings.
    """
    selected_model = _dynamic_model(provider, model)
    auth = await _resolve_dynamic_runtime_auth(
        provider,
        credentials=(credential_store if credential_store is not None else FileCredentialStore()),
        environment=environment if environment is not None else environ,
    )
    context = ProviderRuntimeContext(provider_id=provider.id, auth=auth)
    if provider.runtime_factory is not None:
        candidate = provider.runtime_factory(context, selected_model)
        runtime = await candidate if isawaitable(candidate) else candidate
        try:
            stream_response = getattr(runtime, "stream_response", None)
        except BaseException:  # noqa: BLE001 - extension object validation boundary
            stream_response = None
        try:
            close = getattr(runtime, "aclose", None)
        except BaseException:  # noqa: BLE001 - extension object validation boundary
            close = None
        if not callable(stream_response) or not callable(close):
            error = ProviderConfigError(
                f"Runtime factory for {provider.id} returned an unsupported provider"
            )
            if callable(close):
                try:
                    close_result = close()
                    if isawaitable(close_result):
                        await close_result
                except BaseException:  # noqa: BLE001 - preserve the validation error
                    pass
            raise error
        return runtime

    transport = provider.transport
    assert isinstance(transport, OpenAICompatibleTransport)
    selected_api = selected_model.api or transport.api
    if selected_api not in {"openai-completions", "openai-responses"}:
        raise ProviderConfigError(
            f"OpenAI-compatible dynamic provider {provider.id} cannot use api {selected_api}"
        )
    headers = _merge_dynamic_headers(
        transport.headers,
        selected_model.headers,
        auth.headers,
    )
    has_authorization = any(key.casefold() == "authorization" for key in headers)
    if auth.api_key is not None and auth.omit_authorization_header and not has_authorization:
        raise ProviderConfigError(
            f"OpenAI-compatible dynamic provider {provider.id} resolved an API key "
            "while requesting Authorization omission"
        )
    config = OpenAICompatibleConfig(
        api_key=auth.api_key or "",
        base_url=selected_model.base_url or transport.base_url,
        headers=headers,
        timeout_seconds=transport.timeout_seconds,
        max_retries=transport.max_retries,
        max_retry_delay_seconds=transport.max_retry_delay_seconds,
        api=selected_api,
        max_tokens=selected_model.max_tokens,
        supports_images=(
            selected_model.input_modalities is not None
            and "image" in selected_model.input_modalities
        ),
        compat=json_compatible_mapping(selected_model.compat),
        provider_name=provider.id,
        omit_authorization_header=auth.omit_authorization_header,
        # Dynamic providers explicitly own their API choice. A local model id
        # resembling gpt-* or *codex* must not reroute to /responses.
        infer_api_from_model=False,
    )
    return OpenAICompatibleProvider(config, client=transport.client)


async def _resolve_dynamic_runtime_auth(
    provider: DynamicProvider,
    *,
    credentials: CredentialReader,
    environment: Mapping[str, str],
) -> ResolvedProviderAuth:
    """Resolve extension auth behind a categorical secret-safe boundary."""
    try:
        return await resolve_provider_auth(
            provider.auth,
            credentials=credentials,
            environment=environment,
        )
    except asyncio.CancelledError:
        # Keep cancellation semantics without retaining an extension-authored
        # cancellation message that could contain credential material.
        raise asyncio.CancelledError from None
    except _MissingRequiredApiKeyError:
        # Preserve only Tau's exact strategy and host-authored missing-key error.
        if type(provider.auth) is RequiredApiKey:
            raise
        raise ProviderAuthError("Dynamic provider authentication resolution failed") from None
    except ProviderAuthError:
        # Custom strategies can raise ProviderAuthError too, so their arbitrary
        # text crosses the same categorical boundary as any extension exception.
        raise ProviderAuthError("Dynamic provider authentication resolution failed") from None
    except BaseException:  # noqa: BLE001 - extension authentication boundary
        raise ProviderAuthError("Dynamic provider authentication resolution failed") from None


def _dynamic_model(provider: DynamicProvider, model: str) -> ProviderModel:
    for candidate in provider.models:
        if candidate.id == model:
            return candidate
    raise ProviderConfigError(f"Model is not configured for provider {provider.id}: {model}")


def _merge_dynamic_headers(*values: Mapping[str, str]) -> dict[str, str]:
    """Merge transport/model/auth headers case-insensitively, latest value winning."""
    merged: dict[str, str] = {}
    names: dict[str, str] = {}
    for value in values:
        for key, item in value.items():
            normalized = key.casefold()
            previous = names.get(normalized)
            if previous is not None:
                merged.pop(previous)
            names[normalized] = key
            merged[key] = item
    return merged


def create_model_provider(
    provider: ProviderConfig,
    *,
    credential_store: FileCredentialStore | None = None,
    model: str | None = None,
    thinking_level: ThinkingLevel | None = None,
    inference_provider: str | None = None,
    response_headers_observer: Callable[[Mapping[str, str]], None] | None = None,
) -> ClosableModelProvider:
    """Create a runtime model provider from durable provider settings."""
    if model is not None:
        validate_provider_model(provider, model)
    if inference_provider is not None:
        if provider.name != "huggingface" or model is None:
            raise ProviderConfigError(
                "Inference-provider pinning is only available for Hugging Face models"
            )
        inference_provider = validate_huggingface_inference_provider(inference_provider)
    credentials = credential_store or FileCredentialStore()
    if isinstance(provider, AnthropicProviderConfig | OpenAICodexProviderConfig):
        raise ProviderConfigError("Only the OpenAI API protocol is enabled")
    if isinstance(provider, OpenAICompatibleProviderConfig):
        credential = _oauth_credential(provider, credentials)
        compatible_config = openai_compatible_config_from_provider(
            provider,
            credential_reader=credentials,
            model=model,
            thinking_level=thinking_level,
        )
        if inference_provider is not None and model is not None:
            compatible_config = replace(
                compatible_config,
                model_aliases={model: f"{model}:{inference_provider}"},
            )
        if response_headers_observer is not None:
            compatible_config = replace(
                compatible_config,
                response_headers_observer=response_headers_observer,
            )
        if credential is not None:
            runtime_auth = _required_oauth_provider(provider.name).runtime_auth(credential)
            compatible_config = replace(
                compatible_config,
                api_key=runtime_auth.api_key,
                base_url=runtime_auth.base_url or compatible_config.base_url,
                headers={
                    **dict(compatible_config.headers or {}),
                    **dict(runtime_auth.headers or {}),
                },
                credential_resolver=OAuthRuntimeCredentialResolver(
                    provider,
                    credential_store=credentials,
                ),
            )
        if compatible_config.api not in {"openai-completions", "openai-responses"}:
            raise ProviderConfigError("Only the OpenAI API protocol is enabled")
        return OpenAICompatibleProvider(compatible_config)
    raise ProviderConfigError(f"Unsupported provider config: {provider.name}")


_REFRESH_LOCKS: MutableMapping[AbstractEventLoop, dict[str, asyncio.Lock]] = WeakKeyDictionary()


def _refresh_lock(credential_name: str) -> asyncio.Lock:
    """Return this loop's refresh lock for one stored credential.

    Providers rotate the refresh token on use: the old one dies the moment a
    refresh succeeds. A session issues provider calls concurrently (the agent
    loop and session auto-naming, for two), so without serialization several
    tasks read the same expired credential and spend the same refresh token.
    One of them wins, the losers 400, and whichever write lands last can leave
    a superseded token on disk — which fails on the *next* run, long after the
    race that caused it. Holding this lock across the network call, and
    re-reading the store inside it, keeps a token spent at most once.

    Locks are cached per event loop because ``asyncio.Lock`` binds to the
    running loop on first contention: a lock cached across loops appears to
    work — the uncontended path never touches the loop — until two tasks
    contend it in a later loop and it raises.
    """
    locks = _REFRESH_LOCKS.setdefault(get_running_loop(), {})
    lock = locks.get(credential_name)
    if lock is None:
        lock = asyncio.Lock()
        locks[credential_name] = lock
    return lock


def _oauth_credential(
    provider: ProviderConfig,
    credential_store: FileCredentialStore,
) -> OAuthCredential | None:
    if provider.credential_name is None or get_oauth_provider(provider.name) is None:
        return None
    return credential_store.get_oauth(provider.credential_name)


class OAuthRuntimeCredentialResolver:
    """Refresh provider-neutral OAuth credentials immediately before a request."""

    def __init__(
        self,
        provider: ProviderConfig,
        *,
        credential_store: FileCredentialStore,
    ) -> None:
        self._provider = provider
        self._credential_store = credential_store

    async def __call__(self) -> RuntimeProviderAuth:
        credential_name = self._provider.credential_name
        if credential_name is None:
            raise RuntimeError(f"Provider {self._provider.name} has no credential name")
        oauth_provider = _required_oauth_provider(self._provider.name)
        async with _refresh_lock(credential_name):
            # Read inside the lock: a task that waited here while another
            # refreshed sees the rotated credential and skips its own refresh.
            credential = self._credential_store.get_oauth(credential_name)
            if credential is None:
                raise RuntimeError(
                    f"Missing OAuth credentials for {self._provider.name}. "
                    f"Run /login {self._provider.name}."
                )
            refreshed = await oauth_provider.refresh(credential)
            if refreshed != credential:
                self._credential_store.set_oauth(credential_name, refreshed)
        auth = oauth_provider.runtime_auth(refreshed)
        return RuntimeProviderAuth(
            api_key=auth.api_key,
            base_url=auth.base_url,
            headers=auth.headers,
        )


def _required_oauth_provider(provider_name: str) -> OAuthProvider:
    oauth_provider = get_oauth_provider(provider_name)
    if oauth_provider is None:
        raise RuntimeError(f"No OAuth implementation is registered for {provider_name}")
    return oauth_provider
