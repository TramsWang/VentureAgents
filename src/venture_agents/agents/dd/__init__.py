"""DDAgent - 矿业尽职调查报告生成 Agent

提供：
- DDAgent: 主 Agent 类（使用 TemplatedReactAgent 实现）
- RagQuery / RagQueryType: RAG 查询相关类型
- Language: 语言枚举
"""

from venture_agents.agents.dd.types import GPTSectionOutput


__all__ = [
    "GPTSectionOutput",
]


def __getattr__(name: str) -> type:
    """延迟加载 DDAgent"""
    if name == "DDAgent":
        from venture_agents.agents.dd.agent import DDAgent

        return DDAgent
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
