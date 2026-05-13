from __future__ import annotations

import asyncio
from typing import Any, cast

from venture_agents.agents.dd.sections._base import parse_references
from venture_agents.agents.dd.sections.overview import build_overview


def test_parse_references_splits_trailing_references_section() -> None:
    body, references = parse_references(
        """### 1.1 Company Basics

The company was founded in 2024[1][2].

## References

[1] User file: company deck, page 2.
[2] Public source: company website,
accessed 2026-05-12.
""",
    )

    assert body == "### 1.1 Company Basics\n\nThe company was founded in 2024[1][2]."
    assert references == [
        "User file: company deck, page 2.",
        "Public source: company website, accessed 2026-05-12.",
    ]


def test_parse_references_compacts_non_contiguous_reference_numbers() -> None:
    body, references = parse_references(
        """Product traction is supported by customer evidence[2, 4].

References
[2] User file: customer case appendix.
[4] Public source: press release.
""",
    )

    assert body == "Product traction is supported by customer evidence[1][2]."
    assert references == [
        "User file: customer case appendix.",
        "Public source: press release.",
    ]


def test_build_overview_returns_body_and_references() -> None:
    class FakeAgent:
        async def check_file_usage(self, _task_sys_prompt: str) -> list[object]:
            return []

        async def _ainvoke_llm(
            self,
            system_prompt: str,
            user_prompt: str,
            use_web_search: bool = True,
        ) -> str:
            assert system_prompt
            assert user_prompt.startswith("## 材料内容:")
            assert use_web_search is True
            return """### 1.1 Company Basics

The company was founded in 2024[1].

References
[1] User file: company deck, page 2.
"""

    body, references = asyncio.run(build_overview(cast("Any", FakeAgent())))

    assert body == "### 1.1 Company Basics\n\nThe company was founded in 2024[1]."
    assert references == ["User file: company deck, page 2."]
