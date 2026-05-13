from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from venture_agents.tools import file_parser
from venture_agents.tools.file_parser import parse_files


if TYPE_CHECKING:
    from pathlib import Path


class _FakeResponse:
    output_text = "这是一个100到200字之间的文档概览。"


class _FakeResponses:
    def __init__(self, llm: _FakeLLM) -> None:
        self._llm = llm

    async def create(self, **kwargs: object) -> _FakeResponse:
        self._llm.requests.append(kwargs)
        self._llm.active += 1
        self._llm.max_active = max(self._llm.max_active, self._llm.active)
        await asyncio.sleep(0.01)
        self._llm.active -= 1
        return _FakeResponse()


class _FakeLLM:
    def __init__(self) -> None:
        self.requests: list[dict[str, object]] = []
        self.active = 0
        self.max_active = 0
        self.responses = _FakeResponses(self)


def test_parse_files_reads_txt_and_adds_overview(tmp_path: Path) -> None:
    file_path = tmp_path / "memo.txt"
    file_path.write_text("# Memo\n\n正文内容。", encoding="utf-8")
    llm = _FakeLLM()

    result = parse_files(llm, [file_path], semaphore=1)

    assert result[0].title == "memo"
    assert result[0].content_md == "# Memo\n\n正文内容。"
    assert result[0].overview == "这是一个100到200字之间的文档概览。"
    assert "正文内容" in str(llm.requests[0]["input"])


def test_parse_files_dispatches_excel_parser(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    file_path = tmp_path / "financials.xlsx"
    file_path.write_bytes(b"placeholder")
    llm = _FakeLLM()

    monkeypatch.setattr(file_parser, "_render_excel_markdown", lambda path: f"rendered {path.name}")

    result = parse_files(llm, [file_path], semaphore=1)

    assert result[0].title == "financials"
    assert result[0].content_md == "rendered financials.xlsx"


def test_parse_files_respects_semaphore(tmp_path: Path) -> None:
    files = []
    for index in range(4):
        file_path = tmp_path / f"file-{index}.txt"
        file_path.write_text(f"content {index}", encoding="utf-8")
        files.append(file_path)
    llm = _FakeLLM()

    parse_files(llm, files, semaphore=2)

    assert llm.max_active == 2


def test_parse_files_rejects_unsupported_file(tmp_path: Path) -> None:
    file_path = tmp_path / "archive.zip"
    file_path.write_bytes(b"zip")

    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_files(_FakeLLM(), [file_path])
