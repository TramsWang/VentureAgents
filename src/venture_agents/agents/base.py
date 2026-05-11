"""Agent 抽象基类

所有 Agent 的公共接口定义
"""

from abc import ABC, abstractmethod
from typing import Any

from venture_agents.utils.log import setup_logger


class BaseAgent(ABC):
    """Agent 抽象基类

    所有业务 Agent 必须继承此类并实现核心方法
    """

    name: str = "base_agent"
    description: str = ""

    def __init__(self) -> None:
        self._logger = setup_logger(self.__class__.__name__)

    @abstractmethod
    def run(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """执行 Agent 主逻辑

        Args:
            **kwargs: Agent 特定参数

        Returns:
            Agent 执行结果
        """
        pass

    def get_metadata(self) -> dict[str, Any]:
        """返回 Agent 元数据"""
        return {
            "name": self.name,
            "description": self.description,
            "class": self.__class__.__name__,
        }
