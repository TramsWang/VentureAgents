"""Run DDAgent from the command line for local testing.

Usage:
    python scripts/run_dd_agent.py --company COMPANY [options]

Required arguments:
    --company COMPANY
        Target company name used in the DD report title and output filename.

Options:
    --language {Chinese,English,Spanish,Portuguese,Arabic}
        Report language. Defaults to Chinese.
    --supplementary-files-dir PATH, --supplementary-dir PATH
        Directory containing supplementary files. All regular files under this
        directory are parsed as supplementary files.
    -o PATH, --output-file PATH
        Markdown report output path. Defaults to reports/<company>.md.

Examples:
    python scripts/run_dd_agent.py --company "Example Mining"

    python scripts/run_dd_agent.py --company "Example Mining" \
        --language English \
        --supplementary-files-dir ./data/example_mining/supplementary \
        --output-file ./reports/example_mining_dd.md
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from venture_agents.agents.dd.agent import DDAgent
from venture_agents.schemas import Language


if TYPE_CHECKING:
    from collections.abc import Sequence


def _build_arg_parser() -> argparse.ArgumentParser:
    """Create the command-line argument parser."""
    parser = argparse.ArgumentParser(description="Run DDAgent and write the generated Markdown report.")
    parser.add_argument("--company", required=True, help="Target company name used in the DD report.")
    parser.add_argument(
        "--language",
        default=Language.Chinese.name,
        choices=[language.name for language in Language],
        help="Report language.",
    )
    parser.add_argument(
        "--supplementary-files-dir",
        "--supplementary-dir",
        dest="supplementary_files_dir",
        type=Path,
        help="Directory containing supplementary files. All regular files under it are parsed.",
    )
    parser.add_argument(
        "-o",
        "--output-file",
        type=Path,
        help="Optional output Markdown file path. Defaults to reports/<company>.md.",
    )
    return parser


def _move_report(generated_path: Path, output_file: Path) -> Path:
    """Move the generated report to the requested output path."""
    output_path = output_file.expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if generated_path.resolve() == output_path.resolve():
        return generated_path

    shutil.move(str(generated_path), str(output_path))
    return output_path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the DDAgent CLI."""
    args = _build_arg_parser().parse_args(argv)
    language = Language.from_string(args.language)
    output_file = args.output_file.expanduser() if args.output_file is not None else None
    report_dir = str(output_file.parent) if output_file is not None else "reports"

    agent = DDAgent(
        company=args.company,
        language=language,
        supplementary_files=args.supplementary_files_dir,
    )
    generated_path, followup_questions = agent.run(report_dir=report_dir)
    final_path = _move_report(generated_path, output_file) if output_file is not None else generated_path

    sys.stdout.write(f"Report written to: {final_path}\n")
    if followup_questions:
        sys.stdout.write("Follow-up questions:\n")
        for question in followup_questions:
            sys.stdout.write(f"- {question}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
