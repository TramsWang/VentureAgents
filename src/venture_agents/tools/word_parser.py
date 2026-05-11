"""Utilities for converting Word documents into Markdown text.

This module parses local ``.docx`` files with ``python-docx`` and renders their
content as Markdown. It preserves common document structure including headings,
paragraphs, bullet lists, numbered lists, nested list indentation, and tables.
The module can also be executed directly for manual debugging:

    python -m venture_agents.tools.word_parser path/to/document.docx
    python -m venture_agents.tools.word_parser path/to/document.docx --output out.md
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from docx import Document as open_docx_document
from docx.oxml.ns import qn
from docx.table import Table, _Cell
from docx.text.paragraph import Paragraph


if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from docx.document import Document as DocxDocument
    from docx.oxml.table import CT_Tbl
    from docx.oxml.text.paragraph import CT_P


class XmlElementLike(Protocol):
    """Protocol for the XML operations used from ``python-docx`` elements."""

    tag: str

    def find(self, path: str) -> XmlElementLike | None:
        """Return the first matching child element."""

    def findall(self, path: str) -> list[XmlElementLike]:
        """Return all matching child elements."""

    def get(self, key: str) -> object | None:
        """Return an XML attribute value."""


_HEADING_STYLE_RE = re.compile(r"^(?:heading|标题)\s*(\d+)$", re.IGNORECASE)
_LIST_STYLE_LEVEL_RE = re.compile(r"\s+(\d+)$")
_WHITESPACE_RE = re.compile(r"[ \t\r\f\v]+")


@dataclass(frozen=True)
class NumberingLevel:
    """Numbering metadata for one Word list level.

    Attributes:
        level: Zero-based indentation level from Word numbering metadata.
        num_format: Word numbering format, such as ``bullet`` or ``decimal``.
    """

    level: int
    num_format: str


@dataclass(frozen=True)
class ParagraphNumbering:
    """Resolved list metadata for one paragraph.

    Attributes:
        num_id: Word numbering definition ID. This is used to keep ordered-list
            counters independent across list definitions.
        level: Zero-based indentation level.
        num_format: Word numbering format, such as ``bullet`` or ``decimal``.
    """

    num_id: int
    level: int
    num_format: str


class NumberingDefinitions:
    """Resolver for Word numbering definitions.

    Word stores list metadata separately from paragraphs. A paragraph may point
    directly to a numbering ID, or it may inherit numbering from its paragraph
    style. This class reads the document numbering part and resolves those
    references into Markdown-friendly list metadata.
    """

    def __init__(self, document: DocxDocument) -> None:
        """Initialize numbering lookups for a Word document.

        Args:
            document: ``python-docx`` document object.
        """
        self._num_to_abstract: dict[int, int] = {}
        self._abstract_levels: dict[tuple[int, int], NumberingLevel] = {}
        self._read_numbering_part(document)

    def resolve(self, paragraph: Paragraph) -> ParagraphNumbering | None:
        """Resolve list metadata for a paragraph.

        Args:
            paragraph: Paragraph to inspect.

        Returns:
            List metadata when the paragraph is part of a Word list; otherwise
            ``None``.
        """
        num_pr = self._paragraph_num_pr(paragraph)
        if num_pr is None:
            return None

        num_id = self._child_int_value(num_pr, "w:numId")
        if num_id is None:
            return None

        level = self._child_int_value(num_pr, "w:ilvl")
        if level is None:
            level = self._style_list_level(paragraph)

        num_format = self._num_format(num_id, level)
        return ParagraphNumbering(num_id=num_id, level=level, num_format=num_format)

    def _read_numbering_part(self, document: DocxDocument) -> None:
        """Read numbering definitions from the document numbering part.

        Args:
            document: ``python-docx`` document object.
        """
        try:
            numbering = cast("XmlElementLike", document.part.numbering_part.element)
        except (AttributeError, KeyError, NotImplementedError):
            return

        for abstract_num in numbering.findall(qn("w:abstractNum")):
            abstract_id = self._int_attr(abstract_num, "w:abstractNumId")
            if abstract_id is None:
                continue
            for level_element in abstract_num.findall(qn("w:lvl")):
                level = self._int_attr(level_element, "w:ilvl")
                if level is None:
                    continue
                num_format = self._child_value(level_element, "w:numFmt") or "decimal"
                self._abstract_levels[(abstract_id, level)] = NumberingLevel(level=level, num_format=num_format)

        for num_element in numbering.findall(qn("w:num")):
            num_id = self._int_attr(num_element, "w:numId")
            abstract_id = self._child_int_value(num_element, "w:abstractNumId")
            if num_id is None or abstract_id is None:
                continue
            self._num_to_abstract[num_id] = abstract_id

    def _num_format(self, num_id: int, level: int) -> str:
        """Return the Word numbering format for a list item.

        Args:
            num_id: Word numbering definition ID.
            level: Zero-based list level.

        Returns:
            Word numbering format. Defaults to ``decimal`` when the format
            cannot be resolved.
        """
        abstract_id = self._num_to_abstract.get(num_id)
        if abstract_id is None:
            return "decimal"
        numbering_level = self._abstract_levels.get((abstract_id, level))
        if numbering_level is None and level > 0:
            numbering_level = self._abstract_levels.get((abstract_id, 0))
        return numbering_level.num_format if numbering_level is not None else "decimal"

    @staticmethod
    def _paragraph_num_pr(paragraph: Paragraph) -> XmlElementLike | None:
        """Read paragraph numbering properties from paragraph or style.

        Args:
            paragraph: Paragraph to inspect.

        Returns:
            Numbering properties XML element when present; otherwise ``None``.
        """
        if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None:
            return cast("XmlElementLike", paragraph._p.pPr.numPr)

        style_element = getattr(paragraph.style, "_element", None)
        style_p_pr = getattr(style_element, "pPr", None)
        return cast("XmlElementLike | None", getattr(style_p_pr, "numPr", None))

    @staticmethod
    def _style_list_level(paragraph: Paragraph) -> int:
        """Infer list indentation level from a paragraph style name.

        Args:
            paragraph: Paragraph whose style should be inspected.

        Returns:
            Zero-based list level. Built-in styles such as ``List Bullet 2`` are
            mapped to level ``1``. Styles without an explicit suffix use level
            ``0``.
        """
        style_name = paragraph.style.name if paragraph.style is not None else ""
        match = _LIST_STYLE_LEVEL_RE.search(style_name)
        if match is None:
            return 0
        return max(int(match.group(1)) - 1, 0)

    @staticmethod
    def _child_value(element: XmlElementLike, child_tag: str) -> str | None:
        """Read a child element's ``w:val`` attribute.

        Args:
            element: Parent XML element.
            child_tag: Qualified child tag name, such as ``w:numId``.

        Returns:
            Child ``w:val`` value when present; otherwise ``None``.
        """
        child = element.find(qn(child_tag))
        if child is None:
            return None
        value = child.get(qn("w:val"))
        return str(value) if value is not None else None

    @classmethod
    def _child_int_value(cls, element: XmlElementLike, child_tag: str) -> int | None:
        """Read a child element's ``w:val`` attribute as an integer.

        Args:
            element: Parent XML element.
            child_tag: Qualified child tag name, such as ``w:numId``.

        Returns:
            Integer child value when present and valid; otherwise ``None``.
        """
        value = cls._child_value(element, child_tag)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    @staticmethod
    def _int_attr(element: XmlElementLike, attr_tag: str) -> int | None:
        """Read an XML attribute as an integer.

        Args:
            element: XML element.
            attr_tag: Qualified attribute tag name, such as
                ``w:abstractNumId``.

        Returns:
            Integer attribute value when present and valid; otherwise ``None``.
        """
        value = element.get(qn(attr_tag))
        if not isinstance(value, str):
            return None
        try:
            return int(value)
        except ValueError:
            return None


class OrderedListCounters:
    """Tracks Markdown counters for ordered Word lists."""

    def __init__(self) -> None:
        """Initialize empty ordered-list counters."""
        self._counters: dict[tuple[int, int], int] = {}

    def next_marker(self, numbering: ParagraphNumbering) -> str:
        """Return the next ordered-list marker for a paragraph.

        Args:
            numbering: Resolved paragraph numbering metadata.

        Returns:
            Ordered-list marker such as ``1.`` or ``2.``.
        """
        counter_key = (numbering.num_id, numbering.level)
        self._counters[counter_key] = self._counters.get(counter_key, 0) + 1
        for key in list(self._counters):
            same_list = key[0] == numbering.num_id
            deeper_level = key[1] > numbering.level
            if same_list and deeper_level:
                del self._counters[key]
        return f"{self._counters[counter_key]}."

    def reset(self) -> None:
        """Reset all ordered-list counters."""
        self._counters.clear()


def _normalize_text(text: str) -> str:
    """Normalize text extracted from Word paragraphs.

    Args:
        text: Raw paragraph or cell text.

    Returns:
        Text with repeated horizontal whitespace collapsed and leading or
        trailing whitespace removed. Newlines are preserved.
    """
    return "\n".join(_WHITESPACE_RE.sub(" ", line).strip() for line in text.splitlines()).strip()


def _escape_table_cell(text: str) -> str:
    """Escape text for use inside a Markdown table cell.

    Args:
        text: Raw table cell text.

    Returns:
        Markdown-safe cell text with pipes escaped and line breaks converted to
        ``<br>``.
    """
    return (
        _normalize_text(text)
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _iter_body_blocks(document: DocxDocument) -> Iterator[Paragraph | Table]:
    """Yield paragraphs and tables in document body order.

    Args:
        document: ``python-docx`` document object.

    Yields:
        ``Paragraph`` and ``Table`` objects in the same order they appear in the
        Word document body.
    """
    for child in document.element.body.iterchildren():
        if child.tag == qn("w:p"):
            yield Paragraph(cast("CT_P", child), document)
        elif child.tag == qn("w:tbl"):
            yield Table(cast("CT_Tbl", child), document)


def _heading_level(paragraph: Paragraph) -> int | None:
    """Return the Markdown heading level for a Word paragraph.

    Args:
        paragraph: Paragraph to inspect.

    Returns:
        Heading level from ``1`` to ``6`` when the paragraph uses a built-in
        heading style; otherwise ``None``.
    """
    style = paragraph.style
    if style is None:
        return None

    style_candidates = [style.name, getattr(style, "style_id", "")]
    for style_name in style_candidates:
        match = _HEADING_STYLE_RE.match(str(style_name).replace("Heading", "Heading "))
        if match is None:
            continue
        return min(max(int(match.group(1)), 1), 6)

    if style.name.casefold() == "title":
        return 1
    return None


def _is_bullet_numbering(numbering: ParagraphNumbering) -> bool:
    """Return whether numbering metadata represents a bullet list.

    Args:
        numbering: Resolved paragraph numbering metadata.

    Returns:
        ``True`` for Word bullet formats; otherwise ``False``.
    """
    return numbering.num_format.casefold() == "bullet"


def _list_marker(numbering: ParagraphNumbering, counters: OrderedListCounters) -> str:
    """Return a Markdown list marker for a Word list item.

    Args:
        numbering: Resolved paragraph numbering metadata.
        counters: Ordered-list counter state.

    Returns:
        ``-`` for bullets or a numbered marker such as ``1.`` for ordered
        lists.
    """
    if _is_bullet_numbering(numbering):
        return "-"
    return counters.next_marker(numbering)


def _render_paragraph(
    paragraph: Paragraph,
    numbering_definitions: NumberingDefinitions,
    counters: OrderedListCounters,
) -> tuple[str, bool] | None:
    """Render a Word paragraph as Markdown.

    Args:
        paragraph: Paragraph to render.
        numbering_definitions: Resolver for Word numbering definitions.
        counters: Ordered-list counter state.

    Returns:
        Tuple of rendered Markdown and a boolean indicating whether the line is
        a list item. Returns ``None`` for empty paragraphs.
    """
    text = _normalize_text(paragraph.text)
    if not text:
        return None

    level = _heading_level(paragraph)
    if level is not None:
        counters.reset()
        return f"{'#' * level} {text}", False

    numbering = numbering_definitions.resolve(paragraph)
    if numbering is not None:
        indent = "  " * numbering.level
        marker = _list_marker(numbering, counters)
        return f"{indent}{marker} {text}", True

    counters.reset()
    return text, False


def _cell_text(cell: _Cell) -> str:
    """Render a Word table cell as plain Markdown-safe text.

    Args:
        cell: Word table cell.

    Returns:
        Cell text suitable for a Markdown table cell.
    """
    paragraphs = [_normalize_text(paragraph.text) for paragraph in cell.paragraphs]
    return _escape_table_cell("\n".join(paragraph for paragraph in paragraphs if paragraph))


def _table_rows(table: Table) -> list[list[str]]:
    """Extract non-empty rows from a Word table.

    Args:
        table: Word table.

    Returns:
        Table rows as Markdown-safe cell strings. Rows with no non-empty cells
        are excluded.
    """
    rows: list[list[str]] = []
    for row in table.rows:
        values = [_cell_text(cell) for cell in row.cells]
        if any(value for value in values):
            rows.append(values)
    return rows


def _render_table(table: Table) -> str | None:
    """Render a Word table as a Markdown table.

    Args:
        table: Word table.

    Returns:
        Markdown table text, or ``None`` when the table has no non-empty rows.
    """
    rows = _table_rows(table)
    if not rows:
        return None

    width = max(len(row) for row in rows)
    normalized_rows = [row + [""] * (width - len(row)) for row in rows]
    separator = ["---"] * width
    table_rows = [normalized_rows[0], separator, *normalized_rows[1:]]
    return "\n".join("| " + " | ".join(row) + " |" for row in table_rows)


def _append_block(blocks: list[str], pending_list: list[str], block: str, is_list_item: bool) -> None:
    """Append a rendered block while keeping list items grouped.

    Args:
        blocks: Completed Markdown blocks.
        pending_list: Current consecutive list item lines.
        block: Rendered Markdown block.
        is_list_item: Whether ``block`` is a list item.
    """
    if is_list_item:
        pending_list.append(block)
        return

    if pending_list:
        blocks.append("\n".join(pending_list))
        pending_list.clear()
    blocks.append(block)


def _render_markdown(document: DocxDocument) -> str:
    """Render a Word document object as Markdown.

    Args:
        document: ``python-docx`` document object.

    Returns:
        Markdown representation of the document content.
    """
    numbering_definitions = NumberingDefinitions(document)
    counters = OrderedListCounters()
    blocks: list[str] = []
    pending_list: list[str] = []

    for block in _iter_body_blocks(document):
        if isinstance(block, Paragraph):
            rendered = _render_paragraph(block, numbering_definitions, counters)
            if rendered is None:
                continue
            markdown, is_list_item = rendered
            _append_block(blocks, pending_list, markdown, is_list_item)
            continue

        counters.reset()
        table_markdown = _render_table(block)
        if table_markdown is not None:
            _append_block(blocks, pending_list, table_markdown, False)

    if pending_list:
        blocks.append("\n".join(pending_list))

    return "\n\n".join(blocks)


def parse_word_to_markdown(file_path: str | Path) -> str:
    """Parse a Word ``.docx`` file into Markdown text.

    Args:
        file_path: Path to a local ``.docx`` file.

    Returns:
        Markdown representation of the Word document. Returns an empty string
        for documents without visible text or table content.

    Raises:
        FileNotFoundError: If ``file_path`` does not exist.
        ValueError: If ``file_path`` does not point to a ``.docx`` file.
    """
    path = Path(file_path)
    if path.suffix.casefold() != ".docx":
        message = "Only .docx Word documents are supported."
        raise ValueError(message)
    if not path.is_file():
        message = f"Word document not found: {path}"
        raise FileNotFoundError(message)

    document = open_docx_document(str(path))
    return _render_markdown(document)


def _build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser for manual debugging.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(description="Convert a Word .docx file to Markdown text.")
    parser.add_argument("file_path", type=Path, help="Path to a Word .docx file.")
    parser.add_argument("-o", "--output", type=Path, help="Optional path to write the rendered Markdown output.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Word parser command-line interface.

    Args:
        argv: Optional argument list without the program name. When ``None``,
            arguments are read from ``sys.argv``.

    Returns:
        Process exit code. Returns ``0`` when parsing succeeds.
    """
    args = _build_arg_parser().parse_args(argv)
    try:
        output = parse_word_to_markdown(args.file_path)
    except (FileNotFoundError, ValueError) as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1

    if args.output is not None:
        args.output.write_text(output + ("\n" if output else ""), encoding="utf-8")
        return 0
    if output:
        sys.stdout.write(output + "\n")
    return 0


# 兼容旧命名风格
parseWordToMarkdown = parse_word_to_markdown


if __name__ == "__main__":
    raise SystemExit(main())
