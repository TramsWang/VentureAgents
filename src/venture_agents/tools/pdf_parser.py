"""Utilities for extracting PDF content into Markdown.

This module uses PyMuPDF4LLM as the primary PDF-to-Markdown engine so layout
analysis, multi-column reading order, tables, and page chunk metadata are
preserved by the upstream parser. A smaller PyMuPDF-based parser is kept as a
fallback for environments where PyMuPDF4LLM is unavailable or fails at runtime.
The module can also be executed directly for manual debugging:

    python -m venture_agents.tools.pdf_parser path/to/document.pdf
    python -m venture_agents.tools.pdf_parser path/to/document.pdf -o out.md
"""

from __future__ import annotations

import argparse
import importlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import TYPE_CHECKING, cast


if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import fitz  # type: ignore[import-untyped]


_LIST_MARKER_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)]|[a-zA-Z][.)])\s+")
_SECTION_MARKER_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)*[.)]?"
    r"|[一二三四五六七八九十百千万]+[、.．]"
    r"|第[一二三四五六七八九十百千万\d]+[章节部分]"
    r")\s+"
)
_WHITESPACE_RE = re.compile(r"\s+")
_PAGE_SEPARATOR = "\n\n---\n\n"
_PYMUPDF4LLM_OPTIONS: dict[str, object] = {
    "page_chunks": True,
    "write_images": False,
    "embed_images": False,
    "ignore_images": False,
    "table_strategy": "lines_strict",
    "show_progress": False,
}
LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PdfTextLine:
    """Text extracted from one rendered PDF line.

    Attributes:
        page_number: One-based page number where the line appears.
        block_index: Zero-based text block index within the page.
        text: Normalized text content for the line.
        font_size: Representative font size for the line.
        is_bold: Whether any span in the line appears to use a bold font.
    """

    page_number: int
    block_index: int
    text: str
    font_size: float
    is_bold: bool


def _normalize_text(text: str) -> str:
    """Normalize whitespace in extracted PDF text.

    Args:
        text: Raw text extracted from PyMuPDF spans.

    Returns:
        Text with repeated whitespace collapsed to a single space and leading
        or trailing whitespace removed.
    """
    return _WHITESPACE_RE.sub(" ", text).strip()


def _normalize_heading_key(text: str) -> str:
    """Create a stable key for matching extracted text with PDF outlines.

    Args:
        text: Heading text from either the PDF outline or extracted page text.

    Returns:
        Lower-cased heading text with collapsed whitespace.
    """
    return _normalize_text(text).casefold()


def _is_bold_span(span: dict[str, object]) -> bool:
    """Return whether a PyMuPDF span appears to be bold.

    Args:
        span: Span dictionary returned by ``Page.get_text("dict")``.

    Returns:
        ``True`` when the font name or font flags indicate bold text.
    """
    font = str(span.get("font", "")).casefold()
    flags = span.get("flags", 0)
    return (
        "bold" in font
        or "black" in font
        or "semibold" in font
        or (isinstance(flags, int) and bool(flags & 16))
    )


def _span_size(span: dict[str, object]) -> float:
    """Read the font size from a PyMuPDF span.

    Args:
        span: Span dictionary returned by ``Page.get_text("dict")``.

    Returns:
        Font size as a float. Returns ``0.0`` when the span has no numeric
        size value.
    """
    size = span.get("size", 0.0)
    return float(size) if isinstance(size, int | float) else 0.0


def _line_from_raw(page_number: int, block_index: int, raw_line: dict[str, object]) -> PdfTextLine | None:
    """Convert a raw PyMuPDF line dictionary into a ``PdfTextLine``.

    Args:
        page_number: One-based page number containing the line.
        block_index: Zero-based block index containing the line.
        raw_line: Line dictionary returned by ``Page.get_text("dict")``.

    Returns:
        A normalized ``PdfTextLine``. Returns ``None`` when the line has no
        visible text.
    """
    spans = raw_line.get("spans", [])
    if not isinstance(spans, list):
        return None

    span_dicts = [span for span in spans if isinstance(span, dict)]
    text = _normalize_text("".join(str(span.get("text", "")) for span in span_dicts))
    if not text:
        return None

    sizes = [_span_size(span) for span in span_dicts if _span_size(span) > 0]
    font_size = max(sizes) if sizes else 0.0
    is_bold = any(_is_bold_span(span) for span in span_dicts)
    return PdfTextLine(
        page_number=page_number,
        block_index=block_index,
        text=text,
        font_size=font_size,
        is_bold=is_bold,
    )


def _extract_lines(document: fitz.Document) -> list[PdfTextLine]:
    """Extract normalized text lines from a PDF document.

    Args:
        document: Open PyMuPDF document.

    Returns:
        Text lines in page order and reading order. Non-text blocks and empty
        lines are excluded.
    """
    lines: list[PdfTextLine] = []
    for page_index, page in enumerate(document):
        page_data = cast("dict[str, object]", page.get_text("dict", sort=True))
        blocks = page_data.get("blocks", [])
        if not isinstance(blocks, list):
            continue

        for block_index, block in enumerate(blocks):
            if not isinstance(block, dict):
                continue
            raw_lines = block.get("lines", [])
            if not isinstance(raw_lines, list):
                continue
            for raw_line in raw_lines:
                if not isinstance(raw_line, dict):
                    continue
                line = _line_from_raw(page_index + 1, block_index, raw_line)
                if line is not None:
                    lines.append(line)
    return lines


def _toc_heading_levels(document: fitz.Document) -> dict[str, int]:
    """Build a heading-level lookup from the PDF outline.

    Args:
        document: Open PyMuPDF document.

    Returns:
        Mapping from normalized outline title to Markdown heading level. Levels
        are capped at six because Markdown only defines six heading levels.
    """
    levels: dict[str, int] = {}
    for item in document.get_toc(simple=True):
        if len(item) < 2:
            continue
        level, title = item[0], item[1]
        if not isinstance(level, int) or not isinstance(title, str):
            continue
        key = _normalize_heading_key(title)
        if key:
            levels[key] = min(max(level, 1), 6)
    return levels


def _body_font_size(lines: Iterable[PdfTextLine]) -> float:
    """Estimate the body-text font size for a document.

    Args:
        lines: Extracted PDF text lines.

    Returns:
        Median font size across extracted lines. Returns ``0.0`` when no line
        has a positive font size.
    """
    sizes = [line.font_size for line in lines if line.font_size > 0]
    return float(median(sizes)) if sizes else 0.0


def _heading_size_levels(lines: Iterable[PdfTextLine], body_size: float) -> dict[float, int]:
    """Infer heading levels from font sizes larger than body text.

    Args:
        lines: Extracted PDF text lines.
        body_size: Estimated body-text font size.

    Returns:
        Mapping from rounded font size to Markdown heading level. Larger font
        sizes receive shallower heading levels.
    """
    if body_size <= 0:
        return {}

    heading_sizes = sorted({round(line.font_size, 1) for line in lines if line.font_size >= body_size + 1.5}, reverse=True)
    return {font_size: min(index + 1, 6) for index, font_size in enumerate(heading_sizes)}


def _is_section_like(line: PdfTextLine, body_size: float) -> bool:
    """Return whether a line resembles a section heading.

    Args:
        line: Extracted PDF line.
        body_size: Estimated body-text font size.

    Returns:
        ``True`` when the line is short, bold or slightly larger than body
        text, and starts with a common section marker.
    """
    if len(line.text) > 120:
        return False
    if not _SECTION_MARKER_RE.match(line.text):
        return False
    return line.is_bold or (body_size > 0 and line.font_size >= body_size + 0.5)


def _heading_level(
    line: PdfTextLine,
    toc_levels: dict[str, int],
    size_levels: dict[float, int],
    body_size: float,
) -> int | None:
    """Determine the Markdown heading level for a PDF line.

    Args:
        line: Extracted PDF line.
        toc_levels: Heading levels read from the PDF outline.
        size_levels: Heading levels inferred from font sizes.
        body_size: Estimated body-text font size.

    Returns:
        Markdown heading level from ``1`` to ``6`` when the line should be
        rendered as a heading; otherwise ``None``.
    """
    toc_level = toc_levels.get(_normalize_heading_key(line.text))
    if toc_level is not None:
        return toc_level

    size_level = size_levels.get(round(line.font_size, 1))
    if size_level is not None and len(line.text) <= 160:
        return size_level

    if _is_section_like(line, body_size):
        return 2
    return None


def _is_list_line(text: str) -> bool:
    """Return whether extracted text should be rendered as a Markdown list line.

    Args:
        text: Normalized line text.

    Returns:
        ``True`` when the line starts with a common bullet or ordered-list
        marker.
    """
    return bool(_LIST_MARKER_RE.match(text))


def _is_cjk_character(char: str) -> bool:
    """Return whether a character belongs to a common CJK Unicode block.

    Args:
        char: Single character to inspect.

    Returns:
        ``True`` for common Chinese, Japanese, or Korean ideograph ranges.
    """
    return "\u3400" <= char <= "\u9fff" or "\uf900" <= char <= "\ufaff"


def _join_paragraph(lines: list[str]) -> str:
    """Join extracted PDF lines into one Markdown paragraph.

    Args:
        lines: Text lines that belong to the same paragraph.

    Returns:
        Paragraph text. Hyphenated line breaks are repaired, and CJK text is
        joined without inserting extra spaces between adjacent CJK characters.
    """
    paragraph = ""
    for line in lines:
        if not paragraph:
            paragraph = line
        elif paragraph.endswith("-"):
            paragraph = paragraph[:-1] + line
        elif paragraph[-1:] and line[:1] and _is_cjk_character(paragraph[-1]) and _is_cjk_character(line[0]):
            paragraph += line
        else:
            paragraph += " " + line
    return paragraph


def _render_markdown(lines: Sequence[PdfTextLine], toc_levels: dict[str, int]) -> str:
    """Render extracted PDF lines as Markdown.

    Args:
        lines: Extracted text lines in reading order.
        toc_levels: Heading levels read from the PDF outline.

    Returns:
        Markdown representation of the PDF text content.
    """
    body_size = _body_font_size(lines)
    size_levels = _heading_size_levels(lines, body_size)
    blocks: list[str] = []
    paragraph: list[str] = []
    paragraph_key: tuple[int, int] | None = None

    def flush_paragraph() -> None:
        nonlocal paragraph, paragraph_key
        if paragraph:
            blocks.append(_join_paragraph(paragraph))
            paragraph = []
            paragraph_key = None

    for line in lines:
        level = _heading_level(line, toc_levels, size_levels, body_size)
        if level is not None:
            flush_paragraph()
            blocks.append(f"{'#' * level} {line.text}")
            continue

        if _is_list_line(line.text):
            flush_paragraph()
            blocks.append(line.text)
            continue

        line_key = (line.page_number, line.block_index)
        if paragraph_key is not None and line_key != paragraph_key:
            flush_paragraph()
        paragraph_key = line_key
        paragraph.append(line.text)

    flush_paragraph()
    return "\n\n".join(blocks)


def _open_pdf_document(file_path: str | Path) -> fitz.Document:
    """Open a PDF document with PyMuPDF.

    Args:
        file_path: Path to a local PDF file.

    Returns:
        Open PyMuPDF document. Callers are responsible for closing it.

    Raises:
        RuntimeError: If PyMuPDF is not installed.
    """
    try:
        import fitz
    except ImportError as exc:
        message = "PyMuPDF is required to parse PDF files. Install the 'dd' extra or add PyMuPDF to the environment."
        raise RuntimeError(message) from exc

    return fitz.open(Path(file_path))


def _validate_pdf_file(file_path: str | Path) -> Path:
    """Validate that a PDF path exists and contains at least one page.

    Args:
        file_path: Path to a local PDF file.

    Returns:
        Normalized ``Path`` object for the PDF file.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ValueError: If ``file_path`` is not a file or the PDF has no pages.
        RuntimeError: If PyMuPDF is not installed and the file cannot be
            validated.
    """
    path = Path(file_path)
    if not path.exists():
        message = f"PDF file does not exist: {path}"
        raise FileNotFoundError(message)
    if not path.is_file():
        message = f"PDF path is not a file: {path}"
        raise ValueError(message)

    document = _open_pdf_document(path)
    try:
        if document.page_count == 0:
            message = f"PDF file contains no pages: {path}"
            raise ValueError(message)
    finally:
        document.close()

    return path


def _page_chunk_text(chunk: object) -> str:
    """Extract Markdown text from one PyMuPDF4LLM page chunk.

    Args:
        chunk: One item returned by ``pymupdf4llm.to_markdown`` with
            ``page_chunks=True``.

    Returns:
        Markdown text from the page chunk. Unsupported chunk shapes return an
        empty string.
    """
    if isinstance(chunk, dict):
        text = chunk.get("text", "")
        return text if isinstance(text, str) else str(text)
    if isinstance(chunk, str):
        return chunk
    return ""


def _combine_page_chunks(chunks: object) -> str:
    """Combine PyMuPDF4LLM output into the legacy whole-document string.

    Args:
        chunks: Return value from ``pymupdf4llm.to_markdown``.

    Returns:
        Whole-document Markdown text. Page-chunk output is joined with a
        Markdown horizontal-rule separator so callers can still identify page
        boundaries.
    """
    if isinstance(chunks, str):
        return chunks.strip()
    if not isinstance(chunks, list):
        return ""

    page_texts = [_page_chunk_text(chunk).strip() for chunk in chunks]
    if not any(page_texts):
        return ""
    return _PAGE_SEPARATOR.join(page_texts)


def _parse_pdf_to_markdown_with_pymupdf4llm(file_path: Path) -> str:
    """Parse a PDF into Markdown with PyMuPDF4LLM.

    Args:
        file_path: Path to a validated local PDF file.

    Returns:
        Markdown representation of the PDF content.

    Raises:
        RuntimeError: If PyMuPDF4LLM is not installed.
        Exception: Propagates any parsing error from PyMuPDF4LLM so callers can
            decide whether to fall back.
    """
    try:
        pymupdf4llm = importlib.import_module("pymupdf4llm")
    except ImportError as exc:
        message = "PyMuPDF4LLM is required for the primary PDF parser."
        raise RuntimeError(message) from exc

    chunks = pymupdf4llm.to_markdown(str(file_path), **_PYMUPDF4LLM_OPTIONS)
    return _combine_page_chunks(chunks)


def _parse_pdf_to_markdown_with_pymupdf(file_path: str | Path) -> str:
    """Parse a PDF into Markdown with the legacy PyMuPDF fallback.

    The fallback uses PDF outline entries when available to identify headings.
    If the document has no usable outline, it falls back to font-size and
    section-marker heuristics. This path intentionally remains separate from
    the PyMuPDF4LLM path so it does not override PyMuPDF4LLM's layout-aware
    reading order for PPT or BP style PDFs.

    Args:
        file_path: Path to a local PDF file.

    Returns:
        Markdown representation of the PDF content.

    Raises:
        RuntimeError: If PyMuPDF is not installed.
    """
    document = _open_pdf_document(file_path)
    try:
        lines = _extract_lines(document)
        toc_levels = _toc_heading_levels(document)
        return _render_markdown(lines, toc_levels)
    finally:
        document.close()


def parse_pdf_to_markdown(file_path: str | Path) -> str:
    """Parse a PDF file into Markdown text.

    The parser first uses ``pymupdf4llm.to_markdown`` with page chunks enabled
    and layout-aware parsing options. The public return value remains a single
    Markdown string for compatibility with existing callers. When page chunks
    are returned, each page's ``text`` value is joined with a Markdown page
    separator. If PyMuPDF4LLM is unavailable or fails, the function logs the
    error and falls back to the legacy PyMuPDF parser.

    Args:
        file_path: Path to a local PDF file.

    Returns:
        Markdown representation of the PDF content. Returns an empty string for
        PDFs without extractable text.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ValueError: If ``file_path`` is not a file or the PDF has no pages.
        RuntimeError: If neither PyMuPDF4LLM nor the PyMuPDF fallback can parse
            the file.
    """
    path = _validate_pdf_file(file_path)
    try:
        return _parse_pdf_to_markdown_with_pymupdf4llm(path)
    except Exception:
        LOGGER.exception("PyMuPDF4LLM failed to parse PDF. Falling back to PyMuPDF parser: %s", path)
        return _parse_pdf_to_markdown_with_pymupdf(path)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser for manual debugging.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(description="Convert a PDF file to Markdown text.")
    parser.add_argument("file_path", type=Path, help="Path to a PDF file.")
    parser.add_argument("-o", "--output", type=Path, help="Optional path to write the rendered Markdown output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the PDF parser command-line interface.

    Args:
        argv: Optional argument list without the program name. When ``None``,
            arguments are read from ``sys.argv``.

    Returns:
        Process exit code. Returns ``0`` when parsing succeeds.
    """
    args = _build_arg_parser().parse_args(argv)
    output = parse_pdf_to_markdown(args.file_path)
    if args.output is not None:
        args.output.write_text(output + ("\n" if output else ""), encoding="utf-8")
        return 0
    if output:
        sys.stdout.write(output + "\n")
    return 0


# 兼容旧命名风格
parsePdfToMarkdown = parse_pdf_to_markdown


if __name__ == "__main__":
    raise SystemExit(main())
