from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar


if TYPE_CHECKING:
    from pathlib import Path

    import pytest

from venture_agents.agents.dd.agent import DDAgent
from venture_agents.schemas import Language
from venture_agents.utils.config import reload_settings


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


class _FakeResponse:
    output_text = "  generated text  "


class _FakeResponses:
    def __init__(self) -> None:
        self.kwargs: dict[str, Any] | None = None

    async def create(self, **kwargs: Any) -> _FakeResponse:
        self.kwargs = kwargs
        return _FakeResponse()


class _FakeAsyncOpenAI:
    instances: ClassVar[list[_FakeAsyncOpenAI]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.client_kwargs = kwargs
        self.responses = _FakeResponses()
        self.instances.append(self)


def test_ainvoke_llm_uses_responses_api_with_web_search(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_config_env(monkeypatch)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
llm:
  openai:
    api_key: test-key
    organization: test-org
    project: test-project
  chat:
    model: gpt-4.1
    temperature: 0.2
    max_tokens: 123
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VENTURE_AGENTS_CONFIG", str(config_path))
    reload_settings()
    _FakeAsyncOpenAI.instances.clear()
    monkeypatch.setattr("openai.AsyncOpenAI", _FakeAsyncOpenAI)

    agent = DDAgent("Example Mining", Language.English)

    async def _invoke_twice() -> tuple[str, str]:
        try:
            return (
                await agent._ainvoke_llm("system prompt", "user prompt"),
                await agent._ainvoke_llm("system prompt 2", "user prompt 2"),
            )
        finally:
            await agent.aclose()

    result, second_result = asyncio.run(_invoke_twice())

    assert result == "generated text"
    assert second_result == "generated text"
    assert len(_FakeAsyncOpenAI.instances) == 1
    client = _FakeAsyncOpenAI.instances[-1]
    assert client.client_kwargs["api_key"] == "test-key"
    assert client.client_kwargs["organization"] == "test-org"
    assert client.client_kwargs["project"] == "test-project"
    assert client.client_kwargs["http_client"] is agent._llm_http_client

    request_kwargs = client.responses.kwargs
    assert request_kwargs is not None
    assert request_kwargs["model"] == "gpt-4.1"
    assert request_kwargs["temperature"] == 0.2
    assert request_kwargs["instructions"] == "system prompt 2"
    assert request_kwargs["input"] == "user prompt 2"
    assert request_kwargs["tools"] == [{"type": "web_search"}]
    assert request_kwargs["max_output_tokens"] == 123
    assert "messages" not in request_kwargs
    assert "max_tokens" not in request_kwargs
