from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest


if TYPE_CHECKING:
    from pathlib import Path

from venture_agents.agents.dd.agent import DDAgent
from venture_agents.schemas import Language
from venture_agents.schemas.file_parsing import FileDescription
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
    def __init__(self, response: object | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.kwargs: dict[str, Any] | None = None
        self.response = response or _FakeResponse()

    async def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        self.kwargs = kwargs
        return self.response


class _FakeAsyncOpenAI:
    instances: ClassVar[list[_FakeAsyncOpenAI]] = []
    response: ClassVar[object | None] = None

    def __init__(self, **kwargs: Any) -> None:
        self.client_kwargs = kwargs
        self.responses = _FakeResponses(self.response)
        self.instances.append(self)


class _DummyLogger:
    def debug(self, *_args: object, **_kwargs: object) -> None:
        pass

    def info(self, *_args: object, **_kwargs: object) -> None:
        pass

    def warning(self, *_args: object, **_kwargs: object) -> None:
        pass

    def exception(self, *_args: object, **_kwargs: object) -> None:
        pass


def _make_file_usage_agent(response_text: str) -> DDAgent:
    agent = cast("Any", DDAgent.__new__(DDAgent))
    agent._parsed_supp_files = [
        FileDescription(title="财务数据", content_md="financial content", overview="包含收入、利润和现金流数据。"),
        FileDescription(title="矿权文件", content_md="permit content", overview="包含采矿许可和矿权期限信息。"),
        FileDescription(title="ESG报告", content_md="esg content", overview="包含环境治理和社区关系信息。"),
    ]
    agent._logger = _DummyLogger()

    async def _fake_ainvoke_llm(
        _system_prompt: str,
        _user_prompt: str,
        use_web_search: bool = True,
    ) -> str:
        return response_text

    agent._ainvoke_llm = _fake_ainvoke_llm
    return cast("DDAgent", agent)


def test_dd_agent_reads_supplementary_files_from_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DDAgent, "_create_llm_client", lambda _self: (object(), object()))
    supplementary_dir = tmp_path / "supplementary"
    nested_dir = supplementary_dir / "nested"
    nested_dir.mkdir(parents=True)
    (supplementary_dir / "overview.txt").write_text("overview", encoding="utf-8")
    (nested_dir / "finance.pdf").write_text("finance", encoding="utf-8")

    agent = DDAgent("Example Mining", Language.English, supplementary_files=supplementary_dir)

    assert agent._supplementary_files == sorted(
        [
            str(supplementary_dir / "overview.txt"),
            str(nested_dir / "finance.pdf"),
        ],
    )


def test_dd_agent_rejects_non_directory_supplementary_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(DDAgent, "_create_llm_client", lambda _self: (object(), object()))
    file_path = tmp_path / "overview.txt"
    file_path.write_text("overview", encoding="utf-8")

    with pytest.raises(NotADirectoryError, match="Supplementary files path must be a directory"):
        DDAgent("Example Mining", Language.English, supplementary_files=file_path)


def test_check_file_usage_accepts_json_code_block() -> None:
    agent = _make_file_usage_agent(
        """```json
[
  {"article_id": 1, "reason": "可支持财务分析。"},
  {"article_id": 3, "reason": "可支持ESG分析。"}
]
```""",
    )

    selected = asyncio.run(agent.check_file_usage("撰写财务与ESG分析"))

    assert [file.title for file in selected] == ["财务数据", "ESG报告"]


def test_check_file_usage_accepts_bare_json() -> None:
    agent = _make_file_usage_agent(
        '[{"article_id": 2, "reason": "可支持矿权分析。"}]',
    )

    selected = asyncio.run(agent.check_file_usage("撰写矿权和许可章节"))

    assert [file.title for file in selected] == ["矿权文件"]


def test_check_file_usage_skips_invalid_json_schema_items() -> None:
    agent = _make_file_usage_agent(
        '[{"article_id": 1, "note": "缺少 reason 字段"}, {"article_id": 2, "reason": "可支持矿权分析。"}]',
    )

    selected = asyncio.run(agent.check_file_usage("撰写财务分析"))

    assert [file.title for file in selected] == ["矿权文件"]


def test_check_file_usage_ignores_out_of_range_article_ids() -> None:
    agent = _make_file_usage_agent(
        '[{"article_id": 1, "reason": "可支持财务分析。"}, {"article_id": 99, "reason": "越界编号。"}]',
    )

    selected = asyncio.run(agent.check_file_usage("撰写财务分析"))

    assert [file.title for file in selected] == ["财务数据"]


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
    settings = reload_settings()
    monkeypatch.setattr("venture_agents.agents.dd.agent.SETTINGS", settings)
    _FakeAsyncOpenAI.instances.clear()
    _FakeAsyncOpenAI.response = None
    monkeypatch.setattr("venture_agents.agents.dd.agent.AsyncOpenAI", _FakeAsyncOpenAI)

    agent = DDAgent("Example Mining", Language.English)

    async def _invoke_twice() -> tuple[str, str]:
        try:
            return (
                await agent._ainvoke_llm("system prompt", "user prompt"),
                await agent._ainvoke_llm("system prompt 2", "user prompt 2", use_web_search=False),
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

    assert len(client.responses.calls) == 2
    default_request_kwargs = client.responses.calls[0]
    assert default_request_kwargs["model"] == "gpt-4.1"
    assert default_request_kwargs["temperature"] == 0.2
    assert default_request_kwargs["instructions"] == "system prompt"
    assert default_request_kwargs["input"] == "user prompt"
    assert default_request_kwargs["tools"] == [{"type": "web_search"}]
    assert default_request_kwargs["max_output_tokens"] == 123
    assert "messages" not in default_request_kwargs
    assert "max_tokens" not in default_request_kwargs

    disabled_request_kwargs = client.responses.calls[1]
    assert disabled_request_kwargs["model"] == "gpt-4.1"
    assert disabled_request_kwargs["temperature"] == 0.2
    assert disabled_request_kwargs["instructions"] == "system prompt 2"
    assert disabled_request_kwargs["input"] == "user prompt 2"
    assert "tools" not in disabled_request_kwargs
    assert disabled_request_kwargs["max_output_tokens"] == 123
    assert "messages" not in disabled_request_kwargs
    assert "max_tokens" not in disabled_request_kwargs


def test_ainvoke_llm_extracts_nested_responses_output(
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
  chat:
    model: gpt-4.1
    temperature: 0.2
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VENTURE_AGENTS_CONFIG", str(config_path))
    settings = reload_settings()
    monkeypatch.setattr("venture_agents.agents.dd.agent.SETTINGS", settings)
    _FakeAsyncOpenAI.instances.clear()
    _FakeAsyncOpenAI.response = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "  nested generated text  ",
                    },
                ],
            },
        ],
    }
    monkeypatch.setattr("venture_agents.agents.dd.agent.AsyncOpenAI", _FakeAsyncOpenAI)

    agent = DDAgent("Example Mining", Language.English)

    async def _invoke() -> str:
        try:
            return await agent._ainvoke_llm("system prompt", "user prompt", use_web_search=False)
        finally:
            await agent.aclose()

    try:
        result = asyncio.run(_invoke())
    finally:
        _FakeAsyncOpenAI.response = None

    assert result == "nested generated text"


def test_ainvoke_llm_raises_for_empty_response(
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
  chat:
    model: gpt-4.1
    temperature: 0.2
""",
        encoding="utf-8",
    )
    monkeypatch.setenv("VENTURE_AGENTS_CONFIG", str(config_path))
    settings = reload_settings()
    monkeypatch.setattr("venture_agents.agents.dd.agent.SETTINGS", settings)
    _FakeAsyncOpenAI.instances.clear()
    _FakeAsyncOpenAI.response = {"id": "resp_empty", "output": []}
    monkeypatch.setattr("venture_agents.agents.dd.agent.AsyncOpenAI", _FakeAsyncOpenAI)

    agent = DDAgent("Example Mining", Language.English)

    async def _invoke() -> None:
        try:
            await agent._ainvoke_llm("system prompt", "user prompt", use_web_search=False)
        finally:
            await agent.aclose()

    try:
        with pytest.raises(RuntimeError, match="did not contain generated text"):
            asyncio.run(_invoke())
    finally:
        _FakeAsyncOpenAI.response = None
