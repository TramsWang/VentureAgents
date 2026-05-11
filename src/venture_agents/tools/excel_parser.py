"""Utilities for converting Excel worksheets into Markdown tables.

This module provides a small parser for Excel workbooks. It reads a workbook
from a local path, skips empty worksheets, and returns each non-empty worksheet
as a standalone Markdown table. The module can also be executed directly for
manual debugging:

    python -m venture_agents.tools.excel_parser path/to/workbook.xlsx
    python -m venture_agents.tools.excel_parser path/to/workbook.xlsx -o out.md
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING

from openpyxl import load_workbook


if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True)
class SheetMd:
    """Markdown representation of one Excel worksheet.

    Attributes:
        sheet_name: Name of the worksheet in the Excel workbook.
        markdown: Worksheet content formatted as a Markdown table.
    """

    sheet_name: str
    markdown: str


def _is_empty_cell(value: object) -> bool:
    """Return whether a cell value should be treated as empty.

    Args:
        value: Raw cell value returned by ``openpyxl``.

    Returns:
        ``True`` when the value is ``None`` or a whitespace-only string;
        otherwise ``False``.
    """
    return value is None or (isinstance(value, str) and value.strip() == "")


def _cell_to_markdown(value: object) -> str:
    """Convert a single cell value into Markdown-safe text.

    Args:
        value: Raw cell value returned by ``openpyxl``.

    Returns:
        A string safe to place inside a Markdown table cell. Empty values are
        returned as an empty string, pipe characters are escaped, and newlines
        are converted to ``<br>``.
    """
    if _is_empty_cell(value):
        return ""
    if isinstance(value, datetime):
        text = value.date().isoformat() if value.time() == time.min else value.isoformat(sep=" ", timespec="seconds")
    elif isinstance(value, date | time):
        text = value.isoformat()
    else:
        text = str(value)
    return (
        text.strip()
        .replace("\\", "\\\\")
        .replace("|", "\\|")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\n", "<br>")
    )


def _sheet_rows(values: Sequence[Sequence[object]]) -> list[list[object]]:
    """Normalize worksheet values into a rectangular non-empty range.

    Args:
        values: Worksheet rows from ``Worksheet.iter_rows(values_only=True)``.

    Returns:
        A list of rows cropped to the smallest rectangle containing non-empty
        cells. Empty rows are removed. Returns an empty list when the worksheet
        contains no non-empty cells.
    """
    non_empty_rows = [list(row) for row in values if any(not _is_empty_cell(cell) for cell in row)]
    if not non_empty_rows:
        return []

    non_empty_columns = [
        col_index
        for col_index in range(max(len(row) for row in non_empty_rows))
        if any(col_index < len(row) and not _is_empty_cell(row[col_index]) for row in non_empty_rows)
    ]
    first_col = min(non_empty_columns)
    last_col = max(non_empty_columns)

    return [
        [row[col_index] if col_index < len(row) else None for col_index in range(first_col, last_col + 1)]
        for row in non_empty_rows
    ]


def _rows_to_markdown(rows: list[list[object]]) -> str:
    """Render normalized worksheet rows as a Markdown table.

    Args:
        rows: Normalized worksheet rows. The first row is used as the Markdown
            table header.

    Returns:
        Markdown table text.
    """
    header = [_cell_to_markdown(cell) for cell in rows[0]]
    body = [[_cell_to_markdown(cell) for cell in row] for row in rows[1:]]
    separator = ["---"] * len(header)
    table_rows = [header, separator, *body]
    return "\n".join("| " + " | ".join(row) + " |" for row in table_rows)


def parse_excel_to_markdown(file_path: str | Path) -> list[SheetMd]:
    """Parse an Excel workbook into Markdown tables.

    Empty worksheets are excluded from the result. For non-empty worksheets,
    leading and trailing empty rows and columns are trimmed before rendering.
    Cell values are read with ``data_only=True``, so formula cells use the last
    cached value stored in the workbook.

    Args:
        file_path: Path to an Excel workbook supported by ``openpyxl``.

    Returns:
        A list of ``SheetMd`` objects, one for each non-empty worksheet.
    """
    workbook = load_workbook(Path(file_path), read_only=True, data_only=True)
    try:
        sheets: list[SheetMd] = []
        for worksheet in workbook.worksheets:
            rows = _sheet_rows(list(worksheet.iter_rows(values_only=True)))
            if not rows:
                continue
            sheets.append(SheetMd(sheet_name=worksheet.title, markdown=_rows_to_markdown(rows)))
    finally:
        workbook.close()

    return sheets


def _build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser for manual debugging.

    Returns:
        Configured ``argparse.ArgumentParser`` instance.
    """
    parser = argparse.ArgumentParser(description="Convert Excel worksheets to Markdown tables.")
    parser.add_argument("file_path", type=Path, help="Path to an Excel workbook.")
    parser.add_argument("-o", "--output", type=Path, help="Optional path to write the rendered Markdown output.")
    return parser


def _render_sheets(sheets: Sequence[SheetMd]) -> str:
    """Render parsed worksheet Markdown for CLI output.

    Args:
        sheets: Parsed worksheet Markdown objects.

    Returns:
        Markdown text containing one ``##`` section per worksheet. Returns an
        empty string when there are no non-empty worksheets.
    """
    return "\n\n".join(f"## {sheet.sheet_name}\n\n{sheet.markdown}" for sheet in sheets)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Excel parser command-line interface.

    Args:
        argv: Optional argument list without the program name. When ``None``,
            arguments are read from ``sys.argv``.

    Returns:
        Process exit code. Returns ``0`` when parsing succeeds.
    """
    args = _build_arg_parser().parse_args(argv)
    sheets = parse_excel_to_markdown(args.file_path)
    output = _render_sheets(sheets)
    if args.output is not None:
        args.output.write_text(output + ("\n" if output else ""), encoding="utf-8")
        return 0
    if output:
        sys.stdout.write(output + "\n")
    return 0


# 兼容旧命名风格
parseExcelToMarkdown = parse_excel_to_markdown


if __name__ == "__main__":
    raise SystemExit(main())
