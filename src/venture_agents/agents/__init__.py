"""Agents 层 - 智能体实现

包含：
- base.py: Agent 基类
- dd/: DDAgent 主报告生成
- comps/: CompsValuationAgent 公司比较法估值分析
"""

from venture_agents.agents.base import BaseAgent


__all__ = ["BaseAgent"]


def __getattr__(name: str) -> type:
    """延迟加载 Agent 类"""
    if name == "DDAgent":
        from venture_agents.agents.dd import DDAgent

        return DDAgent
    
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)
