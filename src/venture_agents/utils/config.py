"""全局配置管理。

配置以 YAML 文件保存，由 Pydantic schema 解析为嵌套设置对象。
默认查找顺序：

1. 环境变量 ``VENTURE_AGENTS_CONFIG`` 指定的文件
2. 当前工作目录及其父目录下的 ``config.yaml`` / ``config.yml``
3. 当前工作目录及其父目录下的 ``configs/config.yaml`` / ``configs/config.yml``

敏感信息推荐通过环境变量提供，例如 ``OPENAI_API_KEY``。
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final, cast

import yaml

from venture_agents.schemas.config import ProjectSettings


CONFIG_ENV_VAR: Final[str] = "VENTURE_AGENTS_CONFIG"
OPENAI_API_KEY_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_OPENAI_API_KEY", "OPENAI_API_KEY")
OPENAI_BASE_URL_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_OPENAI_BASE_URL", "OPENAI_BASE_URL")
OPENAI_ORG_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_OPENAI_ORGANIZATION", "OPENAI_ORGANIZATION")
OPENAI_PROJECT_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_OPENAI_PROJECT", "OPENAI_PROJECT")
OPENAI_PROXY_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_LLM_PROXY", "OPENAI_PROXY")
CHAT_MODEL_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_LLM_MODEL", "OPENAI_MODEL")
SEARCH_MODEL_ENV_VARS: Final[tuple[str, ...]] = ("VENTURE_AGENTS_SEARCH_MODEL",)

_CONFIG_FILE_CANDIDATES: Final[tuple[Path, ...]] = (
    Path("config.yaml"),
    Path("config.yml"),
    Path("configs/config.yaml"),
    Path("configs/config.yml"),
)

_SETTINGS_CACHE: ProjectSettings | None = None
_SETTINGS_CACHE_PATH: Path | None = None


class ConfigError(RuntimeError):
    """配置加载或校验失败。"""


def _first_env_value(names: tuple[str, ...]) -> str | None:
    for name in names:
        value = os.environ.get(name)
        if value is not None and value.strip():
            return value.strip()
    return None


def _candidate_base_dirs() -> list[Path]:
    cwd = Path.cwd().resolve()
    dirs = [cwd, *cwd.parents]

    package_root = Path(__file__).resolve().parents[3]
    if package_root not in dirs:
        dirs.append(package_root)
    return dirs


def _resolve_config_path(config_path: str | Path | None = None) -> Path | None:
    if config_path is not None:
        return Path(config_path).expanduser().resolve()

    env_path = _first_env_value((CONFIG_ENV_VAR,))
    if env_path is not None:
        return Path(env_path).expanduser().resolve()

    for base_dir in _candidate_base_dirs():
        for candidate in _CONFIG_FILE_CANDIDATES:
            path = base_dir / candidate
            if path.is_file():
                return path.resolve()

    return None


def _read_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read config file: {path}"
        raise ConfigError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML config file: {path}"
        raise ConfigError(msg) from exc

    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        msg = f"Config file must contain a YAML mapping at the top level: {path}"
        raise ConfigError(msg)
    return dict(cast("Mapping[str, Any]", raw))


def _apply_env_overrides(settings: ProjectSettings) -> ProjectSettings:
    data = settings.model_dump(mode="python")

    openai_settings = data["llm"]["openai"]
    chat_settings = data["llm"]["chat"]
    search_settings = data["llm"]["search"]

    env_api_key = _first_env_value(OPENAI_API_KEY_ENV_VARS)
    if env_api_key is not None:
        openai_settings["api_key"] = env_api_key

    env_base_url = _first_env_value(OPENAI_BASE_URL_ENV_VARS)
    if env_base_url is not None:
        openai_settings["base_url"] = env_base_url

    env_org = _first_env_value(OPENAI_ORG_ENV_VARS)
    if env_org is not None:
        openai_settings["organization"] = env_org

    env_project = _first_env_value(OPENAI_PROJECT_ENV_VARS)
    if env_project is not None:
        openai_settings["project"] = env_project

    env_proxy = _first_env_value(OPENAI_PROXY_ENV_VARS)
    if env_proxy is not None:
        openai_settings["proxy"] = env_proxy

    env_chat_model = _first_env_value(CHAT_MODEL_ENV_VARS)
    if env_chat_model is not None:
        chat_settings["model"] = env_chat_model

    env_search_model = _first_env_value(SEARCH_MODEL_ENV_VARS)
    if env_search_model is not None:
        search_settings["model"] = env_search_model

    return ProjectSettings.model_validate(data)


def load_settings(config_path: str | Path | None = None) -> ProjectSettings:
    """读取 YAML 配置并返回嵌套的 ``ProjectSettings`` 对象。

    Args:
        config_path: 显式配置文件路径。为 ``None`` 时按默认规则查找；
            找不到文件则使用 schema 默认值和环境变量覆盖。

    Raises:
        ConfigError: 显式指定或环境变量指定的配置文件不存在，或 YAML 格式无效。
        pydantic.ValidationError: YAML 内容不符合 schema。
    """
    resolved_path = _resolve_config_path(config_path)
    if resolved_path is None:
        data: dict[str, Any] = {}
    else:
        if not resolved_path.is_file():
            msg = f"Config file does not exist: {resolved_path}"
            raise ConfigError(msg)
        data = _read_yaml_mapping(resolved_path)

    settings = ProjectSettings.model_validate(data)
    return _apply_env_overrides(settings)


def get_settings(config_path: str | Path | None = None) -> ProjectSettings:
    """返回缓存后的项目设置对象。"""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_PATH

    resolved_path = _resolve_config_path(config_path)
    cached = _SETTINGS_CACHE
    if cached is None or _SETTINGS_CACHE_PATH != resolved_path:
        cached = load_settings(resolved_path)
        _SETTINGS_CACHE = cached
        _SETTINGS_CACHE_PATH = resolved_path
    return cached


def reload_settings(config_path: str | Path | None = None) -> ProjectSettings:
    """强制重新读取配置文件并刷新缓存。"""
    global _SETTINGS_CACHE, _SETTINGS_CACHE_PATH

    resolved_path = _resolve_config_path(config_path)
    settings = load_settings(resolved_path)
    _SETTINGS_CACHE = settings
    _SETTINGS_CACHE_PATH = resolved_path
    return settings


def get_openai_api_key(*, required: bool = True) -> str:
    """获取 OpenAI API key。

    Args:
        required: 为 ``True`` 时，缺少 key 会抛出 ``ConfigError``。
    """
    secret = get_settings().llm.openai.api_key
    api_key = secret.get_secret_value() if secret is not None else ""
    if required and not api_key:
        msg = "OpenAI API key is not configured; set OPENAI_API_KEY or llm.openai.api_key in config YAML."
        raise ConfigError(msg)
    return api_key


def _legacy_section(section: str, settings: ProjectSettings) -> dict[str, Any] | None:
    openai_settings = settings.llm.openai
    dd_settings = settings.agents.dd

    if section == "DDAgent.Searcher":
        return {
            "llm_proxy": openai_settings.proxy or "",
            "llm_model": settings.llm.search.model,
            "max_results": settings.llm.search.max_results,
            "add_summary": settings.llm.search.add_summary,
            "max_chars": settings.llm.search.max_chars,
            "use_cache": settings.llm.search.use_cache,
        }

    if section == "DDAgent.TemplatedReactAgent":
        return {
            "llm_model": settings.llm.chat.model,
            "llm_proxy": openai_settings.proxy or "",
            "llm_temperature": settings.llm.chat.temperature,
            "async_semaphore": dd_settings.async_semaphore,
            "log_level": dd_settings.log_level,
        }

    return None


def _section_from_settings(section: str, settings: ProjectSettings) -> dict[str, Any]:
    current: object = settings.model_dump(mode="json")
    for part in section.split("."):
        if not isinstance(current, Mapping):
            return {}
        current = current.get(part)
        if current is None:
            return {}

    if isinstance(current, Mapping):
        return dict(cast("Mapping[str, Any]", current))
    return {"value": current}


def load_config(section: str | None = None, config_path: str | Path | None = None) -> dict[str, Any]:
    """兼容旧代码的字典式配置读取入口。

    新代码应优先使用 ``get_settings()``：

    >>> settings = get_settings()
    >>> settings.llm.chat.model
    'gpt-4o'
    """
    settings = load_settings(config_path) if config_path is not None else get_settings()
    if section is None:
        return settings.model_dump(mode="json")

    legacy = _legacy_section(section, settings)
    if legacy is not None:
        return legacy
    return _section_from_settings(section, settings)


__all__ = [
    "CONFIG_ENV_VAR",
    "ConfigError",
    "get_openai_api_key",
    "get_settings",
    "load_config",
    "load_settings",
    "reload_settings",
]
