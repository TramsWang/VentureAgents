from __future__ import annotations

from pathlib import Path

import pytest

from venture_agents.utils.config import ConfigError, get_openai_api_key, load_config, load_settings, reload_settings


def _clear_config_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "VENTURE_AGENTS_CONFIG",
        "VENTURE_AGENTS_OPENAI_API_KEY",
        "OPENAI_API_KEY",
        "VENTURE_AGENTS_OPENAI_BASE_URL",
        "OPENAI_BASE_URL",
        "VENTURE_AGENTS_OPENAI_ORGANIZATION",
        "OPENAI_ORGANIZATION",
        "VENTURE_AGENTS_OPENAI_PROJECT",
        "OPENAI_PROJECT",
        "VENTURE_AGENTS_LLM_PROXY",
        "OPENAI_PROXY",
        "VENTURE_AGENTS_LLM_MODEL",
        "OPENAI_MODEL",
        "VENTURE_AGENTS_SEARCH_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_settings_from_yaml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  openai:
    api_key: yaml-key
    proxy: http://127.0.0.1:7890
  chat:
    model: gpt-4o-mini
    temperature: 0.1
  search:
    model: gpt-4o-search-preview
    max_results: 7
agents:
  dd:
    async_semaphore: 3
    log_level: debug
""",
        encoding="utf-8",
    )

    settings = load_settings(config_path)

    assert settings.llm.openai.api_key is not None
    assert settings.llm.openai.api_key.get_secret_value() == "yaml-key"
    assert settings.llm.openai.proxy == "http://127.0.0.1:7890"
    assert settings.llm.chat.model == "gpt-4o-mini"
    assert settings.llm.chat.temperature == 0.1
    assert settings.llm.search.max_results == 7
    assert settings.agents.dd.async_semaphore == 3
    assert settings.agents.dd.log_level == "debug"


def test_environment_overrides_yaml_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  openai:
    api_key: yaml-key
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    settings = load_settings(config_path)

    assert settings.llm.openai.api_key is not None
    assert settings.llm.openai.api_key.get_secret_value() == "env-key"


def test_legacy_load_config_section(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  openai:
    proxy: http://127.0.0.1:7890
  search:
    model: gpt-4o-search-preview
    max_results: 4
""",
        encoding="utf-8",
    )

    section = load_config("DDAgent.Searcher", config_path)

    assert section["llm_proxy"] == "http://127.0.0.1:7890"
    assert section["llm_model"] == "gpt-4o-search-preview"
    assert section["max_results"] == 4


def test_get_openai_api_key_reports_missing_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("VENTURE_AGENTS_CONFIG", str(config_path))
    reload_settings()

    with pytest.raises(ConfigError):
        get_openai_api_key()
