"""Section 基础设施

提供 SectionMeta / SectionBuilder / Section 三个核心类型，
以及 analyze_section() 通用章节生成骨架，
供所有 section 文件和 DDAgent 编排逻辑使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

from venture_agents.utils.log import setup_logger


if TYPE_CHECKING:
    from venture_agents.agents.dd.agent import DDAgent

logger = setup_logger("DDAgent.sections", console=False)


@dataclass
class SectionMeta:
    """章节元数据

    Attributes:
        name: 唯一标识符，如 "geology", "mining", "overview"
        title: 多语言标题列表 [中文, English, Español, Português, العربية]
        phase: 生成阶段
            - "primary": 第一阶段，可并行生成（章节 4-9 的主体内容）
            - "post": 第二阶段，依赖 article_body（概述、亮点、风险、缺口、追问）
        order: 层级编号列表，天然表达章节层级关系，用于排序和推导
            - [4]     → heading_level=2 (##),  parent_order=None
            - [4, 1]  → heading_level=3 (###), parent_order=[4]
            - [4, 1, 1] → heading_level=4 (####), parent_order=[4, 1]
            - post phase 示例: [1], [2], [3], [100], [110]
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


# ------------------------------------------------------------------
# 空 build —— 用于仅需标题的父章节
# ------------------------------------------------------------------


async def build_noop(agent: DDAgent, **kwargs: object) -> tuple[str, list[str]]:
    """空 build，用于仅需标题的父章节。"""
    return "", []
