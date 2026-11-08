from pathlib import Path

import pytest

from model.client import OpenAICompatibleProvider, load_settings, open_client


def test_load_settings_reads_endpoint_and_not_a_model_name(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'base_url = "https://example.invalid/v1"\napi_key = "secret"\n',
        encoding="utf-8",
    )

    settings = load_settings(path)

    assert settings.base_url == "https://example.invalid/v1"
    assert settings.api_key == "secret"
    assert settings.timeout_seconds == 60.0
    assert settings.max_retries == 2
    assert settings.max_retry_delay_seconds == 1.0
    assert not hasattr(settings, "model")


def test_open_client_binds_the_endpoint_and_keeps_model_per_call(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text(
        'base_url = "https://example.invalid/v1/"\napi_key = "secret"\n',
        encoding="utf-8",
    )

    client = open_client(load_settings(path))

    assert isinstance(client, OpenAICompatibleProvider)
    assert client._config.base_url == "https://example.invalid/v1"
    assert client._config.api_key == "secret"
    assert client._config.timeout_seconds == 60.0


def test_load_settings_rejects_a_missing_api_key(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('base_url = "https://example.invalid/v1"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="api_key"):
        load_settings(path)
