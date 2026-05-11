"""项目配置结构定义。

配置文件由 ``venture_agents.utils.config`` 读取，本模块只负责定义
解析后的嵌套设置对象。
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


def _blank_to_none(value: object) -> object:
    if isinstance(value, str) and not value.strip():
        return None
    return value


def _strip_required(value: str, field_name: str) -> str:
    stripped = value.strip()
    if stripped:
        return stripped
    msg = f"{field_name} cannot be empty"
    raise ValueError(msg)


class ConfigBaseModel(BaseModel):
    """配置模型基类。

    统一禁止未知字段，避免 YAML 中拼错字段名后被静默忽略。
    """

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class OpenAISettings(ConfigBaseModel):
    """OpenAI API 连接参数。"""

    api_key: SecretStr | None = Field(default=None, description="OpenAI API key; 推荐通过环境变量提供")
    base_url: str | None = Field(default=None, description="兼容 OpenAI API 的自定义 base URL")
    organization: str | None = Field(default=None, description="OpenAI organization id")
    project: str | None = Field(default=None, description="OpenAI project id")
    proxy: str | None = Field(default=None, description="HTTP(S) proxy URL")
    timeout_seconds: float = Field(default=60.0, gt=0)
    read_timeout_seconds: float = Field(default=600.0, gt=0)
    max_retries: int = Field(default=2, ge=0)

    @field_validator("api_key", "base_url", "organization", "project", "proxy", mode="before")
    @classmethod
    def _normalize_optional_strings(cls, value: object) -> object:
        return _blank_to_none(value)


class ChatModelSettings(ConfigBaseModel):
    """通用对话模型参数。"""

    model: str = Field(default="gpt-4o", min_length=1)
    temperature: float = Field(default=0.3, ge=0, le=2)
    max_tokens: int | None = Field(default=None, gt=0)

    @field_validator("model")
    @classmethod
    def _normalize_model(cls, value: str) -> str:
        return _strip_required(value, "llm.chat.model")


class SearchModelSettings(ConfigBaseModel):
    """OpenAI 搜索模型参数。"""

    model: str = Field(default="gpt-4o-search-preview", min_length=1)
    max_results: int = Field(default=5, ge=1, le=20)
    add_summary: bool = True
    max_chars: int = Field(default=8000, ge=1000)
    use_cache: bool = True

    @field_validator("model")
    @classmethod
    def _normalize_model(cls, value: str) -> str:
        return _strip_required(value, "llm.search.model")


class LLMSettings(ConfigBaseModel):
    """大模型相关设置。"""

    default_provider: Literal["openai"] = "openai"
    openai: OpenAISettings = Field(default_factory=OpenAISettings)
    chat: ChatModelSettings = Field(default_factory=ChatModelSettings)
    search: SearchModelSettings = Field(default_factory=SearchModelSettings)


class DDAgentSettings(ConfigBaseModel):
    """DDAgent 运行参数。"""

    async_semaphore: int = Field(default=5, ge=1)
    log_level: str = "info"

    _ALLOWED_LOG_LEVELS: ClassVar[set[str]] = {"debug", "info", "warn", "warning", "error", "critical", "fatal"}

    @field_validator("log_level")
    @classmethod
    def _normalize_log_level(cls, value: str) -> str:
        normalized = _strip_required(value, "agents.dd.log_level").lower()
        if normalized in cls._ALLOWED_LOG_LEVELS:
            return normalized
        msg = f"Unsupported log level: {value}"
        raise ValueError(msg)


class AgentsSettings(ConfigBaseModel):
    """Agent 专属设置。"""

    dd: DDAgentSettings = Field(default_factory=DDAgentSettings)


class ProjectSettings(ConfigBaseModel):
    """项目全局配置。"""

    llm: LLMSettings = Field(default_factory=LLMSettings)
    agents: AgentsSettings = Field(default_factory=AgentsSettings)

