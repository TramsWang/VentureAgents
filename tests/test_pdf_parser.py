from __future__ import annotations

import sys
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from venture_agents.tools.pdf_parser import main, parse_pdf_to_markdown


if TYPE_CHECKING:
    from pathlib import Path


fitz = pytest.importorskip("fitz")


def _write_pdf(pdf_path: Path, lines: list[tuple[str, int]]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for text, font_size in lines:
        page.insert_text((72, y), text, fontsize=font_size)
        y += 36
    document.save(pdf_path)
    document.close()


def test_parse_pdf_to_markdown_uses_pymupdf4llm(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "normal.pdf"
    _write_pdf(pdf_path, [("Ignored by mocked parser", 11)])
    calls: list[tuple[str, dict[str, object]]] = []

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        calls.append((file_path, options))
        return [{"text": "# Executive Summary\n\nThis is the first paragraph."}]

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert markdown == "# Executive Summary\n\nThis is the first paragraph."
    assert calls == [
        (
            str(pdf_path),
            {
                "page_chunks": True,
                "write_images": False,
                "embed_images": False,
                "ignore_images": False,
                "table_strategy": "lines_strict",
                "show_progress": False,
            },
        )
    ]


def test_parse_pdf_to_markdown_joins_page_chunks(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "multi-page.pdf"
    document = fitz.open()
    page_one = document.new_page()
    page_one.insert_text((72, 72), "Page one", fontsize=11)
    page_two = document.new_page()
    page_two.insert_text((72, 72), "Page two", fontsize=11)
    document.save(pdf_path)
    document.close()

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        return [{"text": "# Page One\n\nBody one."}, {"text": "# Page Two\n\nBody two."}]

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert markdown == "# Page One\n\nBody one.\n\n---\n\n# Page Two\n\nBody two."


def test_parse_pdf_to_markdown_returns_empty_string_for_empty_text_pdf(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "empty-text.pdf"
    document = fitz.open()
    document.new_page()
    document.save(pdf_path)
    document.close()

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        return [{"text": ""}]

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    assert parse_pdf_to_markdown(pdf_path) == ""


def test_parse_pdf_to_markdown_falls_back_to_pymupdf(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "fallback.pdf"
    _write_pdf(pdf_path, [("Fallback Title", 20), ("Fallback body.", 11)])

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        raise RuntimeError("parser failed")

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert markdown == "# Fallback Title\n\nFallback body."


def test_parse_pdf_to_markdown_returns_legacy_string_format(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "compat.pdf"
    _write_pdf(pdf_path, [("Compatibility", 11)])

    def to_markdown(file_path: str, **options: object) -> str:
        return "# Compatibility\n\nBody.\n"

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert isinstance(markdown, str)
    assert markdown == "# Compatibility\n\nBody."


def test_legacy_pymupdf_fallback_uses_toc_headings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "toc.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Executive Summary", fontsize=20)
    page.insert_text((72, 110), "This is the first paragraph.", fontsize=11)
    page.insert_text((72, 150), "Market", fontsize=16)
    page.insert_text((72, 188), "The market is large.", fontsize=11)
    document.set_toc([[1, "Executive Summary", 1], [2, "Market", 1]])
    document.save(pdf_path)
    document.close()

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        raise RuntimeError("parser failed")

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert markdown == (
        "# Executive Summary\n\n"
        "This is the first paragraph.\n\n"
        "## Market\n\n"
        "The market is large."
    )


def test_legacy_pymupdf_fallback_infers_headings_from_font_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    pdf_path = tmp_path / "font-size.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Investment Memo", fontsize=20)
    page.insert_text((72, 110), "1. Company Overview", fontsize=15)
    page.insert_text((72, 145), "The company builds useful software.", fontsize=11)
    page.insert_text((72, 170), "Its product is sold to enterprise customers.", fontsize=11)
    page.insert_text((72, 195), "Revenue has grown quickly.", fontsize=11)
    document.save(pdf_path)
    document.close()

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        raise RuntimeError("parser failed")

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    markdown = parse_pdf_to_markdown(pdf_path)

    assert markdown == (
        "# Investment Memo\n\n"
        "## 1. Company Overview\n\n"
        "The company builds useful software.\n\n"
        "Its product is sold to enterprise customers.\n\n"
        "Revenue has grown quickly."
    )


def test_pdf_parser_cli_writes_markdown_to_output_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    pdf_path = tmp_path / "cli.pdf"
    output_path = tmp_path / "output.md"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "CLI PDF", fontsize=18)
    page.insert_text((72, 110), "Rendered from the command line.", fontsize=11)
    document.save(pdf_path)
    document.close()

    def to_markdown(file_path: str, **options: object) -> list[dict[str, str]]:
        return [{"text": "# CLI PDF\n\nRendered from the command line."}]

    monkeypatch.setitem(sys.modules, "pymupdf4llm", SimpleNamespace(to_markdown=to_markdown))

    assert main([str(pdf_path), "--output", str(output_path)]) == 0
    assert output_path.read_text(encoding="utf-8") == "# CLI PDF\n\nRendered from the command line.\n"
