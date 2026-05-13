"""Section 基础设施

提供 SectionMeta / SectionBuilder / Section 三个核心类型，
以及 analyze_section() 通用章节生成骨架，
供所有 section 文件和 DDAgent 编排逻辑使用。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from venture_agents.utils.log import setup_logger


if TYPE_CHECKING:
    from venture_agents.agents.dd.agent import DDAgent

logger = setup_logger("DDAgent.sections", console=False)

_REFERENCE_HEADING_RE = re.compile(r"(?im)^[ \t]{0,3}(?:#{1,6}\s*)?(?:references?|参考文献|参考内容)\s*[:：]?\s*$")
_REFERENCE_ENTRY_RE = re.compile(r"^\s*(?:[-*]\s*)?(?:\[(\d+)\]|(\d+)[.)、])\s*(.*)$")
_MULTI_CITATION_RE = re.compile(r"\[\s*(\d+(?:\s*[,，]\s*\d+)+)\s*\]")
_CITATION_RE = re.compile(r"\[\s*(\d+)\s*\]")


@dataclass
class SectionMeta:
    """章节元数据

    Attributes:
        name: 唯一标识符，如 "geology", "mining", "overview"
        title: 多语言标题列表 [中文, English, Español, Português, العربية]
        phase: 生成阶段
            - "primary": 第一阶段，可并行生成的主体章节
            - "post": 第二阶段，依赖 article_body 的后置章节
        order: 层级编号列表，天然表达章节层级关系，用于排序和推导
            - [4]     → heading_level=2 (##),  parent_order=None
            - [4, 1]  → heading_level=3 (###), parent_order=[4]
            - [4, 1, 1] → heading_level=4 (####), parent_order=[4, 1]
            - post phase 示例: [7], [8], [100], [110]
        depends_on: post phase 中依赖的其他 section names
    """

    name: str
    title: list[str]
    phase: str  # "primary" | "post"
    order: list[int]
    depends_on: list[str] = field(default_factory=list)

    @property
    def heading_level(self) -> int:
        """从 order 层级深度自动推导 Markdown 标题级别"""
        return len(self.order) + 1

    @property
    def parent_order(self) -> list[int] | None:
        """从 order 自动推导父章节的 order，顶层章节返回 None"""
        if len(self.order) > 1:
            return self.order[:-1]
        return None


class SectionBuilder(Protocol):
    """Section build 函数的类型协议"""

    async def __call__(
        self,
        agent: DDAgent,
        **kwargs: object,
    ) -> tuple[str, list[str]]:
        """构建章节内容

        Args:
            agent: DDAgent 实例，提供 analyze_section / _ainvoke_llm 等能力
            **kwargs: 额外参数（post phase 会传入 article_body 等）

        Returns:
            tuple[str, list[str]]: (章节文本, 引用列表)
        """
        ...


@dataclass
class Section:
    """已注册的章节"""

    meta: SectionMeta
    build: SectionBuilder


def _normalize_citation_clusters(text: str) -> str:
    """Convert citations like [1, 2] to [1][2] for downstream reference merging."""

    def replace_match(match: re.Match[str]) -> str:
        numbers = re.findall(r"\d+", match.group(1))
        return "".join(f"[{number}]" for number in numbers)

    return _MULTI_CITATION_RE.sub(replace_match, text)


def parse_references(response: str) -> tuple[str, list[str]]:
    """Split an LLM section response into body text and local references.

    The DD report assembler expects each section to return body text with local
    citations and a reference list where local citation ``[n]`` maps to
    ``references[n - 1]``. This parser removes a trailing References section,
    extracts entries such as ``[1] ...`` or ``1. ...``, and normalizes local
    citation numbers if the model emits non-contiguous reference numbering.
    """
    text = response.strip()
    if not text:
        return "", []

    heading_matches = list(_REFERENCE_HEADING_RE.finditer(text))
    if not heading_matches:
        return _normalize_citation_clusters(text), []

    heading_match = heading_matches[-1]
    body = text[: heading_match.start()].rstrip()
    reference_block = text[heading_match.end() :].strip()

    entries: list[tuple[int, str]] = []
    current_number: int | None = None
    current_lines: list[str] = []

    def flush_current() -> None:
        nonlocal current_number, current_lines
        if current_number is None:
            return
        reference_text = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        if reference_text:
            entries.append((current_number, reference_text))
        current_number = None
        current_lines = []

    for line in reference_block.splitlines():
        entry_match = _REFERENCE_ENTRY_RE.match(line)
        if entry_match:
            flush_current()
            number_text = entry_match.group(1) or entry_match.group(2)
            current_number = int(number_text)
            current_lines = [entry_match.group(3)]
            continue
        if current_number is not None:
            current_lines.append(line)
    flush_current()

    if not entries:
        logger.warning("No parseable references found in References section.")
        return _normalize_citation_clusters(body), []

    references_by_number: dict[int, str] = {}
    for number, reference in entries:
        references_by_number.setdefault(number, reference)

    old_to_new: dict[int, int] = {}
    references: list[str] = []
    for old_number in sorted(references_by_number):
        old_to_new[old_number] = len(references) + 1
        references.append(references_by_number[old_number])

    body = _normalize_citation_clusters(body)

    def replace_citation(match: re.Match[str]) -> str:
        old_number = int(match.group(1))
        new_number = old_to_new.get(old_number)
        return f"[{new_number}]" if new_number is not None else ""

    body = _CITATION_RE.sub(replace_citation, body).strip()
    return body, references


# ------------------------------------------------------------------
# 空 build —— 用于仅需标题的父章节
# ------------------------------------------------------------------


async def build_noop(agent: DDAgent, **kwargs: object) -> tuple[str, list[str]]:
    """空 build，用于仅需标题的父章节。"""
    return "", []
