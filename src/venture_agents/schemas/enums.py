"""共享枚举定义

只包含真正被多个 Agent 使用的枚举
"""

from enum import IntEnum, unique


@unique
class Language(IntEnum):
    """报告语言

    用于 DDAgent 和 CompanyCompareAgent 的多语言支持
    """

    Chinese = 0
    English = 1
    Spanish = 2
    Portuguese = 3
    Arabic = 4

    @classmethod
    def from_string(cls, name: str) -> "Language":
        """从字符串解析语言枚举

        Args:
            name: 语言名称，如 "chinese", "English"（大小写不敏感）

        Returns:
            对应的 Language 枚举值

        Raises:
            ValueError: 未知的语言名称
        """
        name_lower = name.lower()
        for lang in cls:
            if lang.name.lower() == name_lower:
                return lang
        msg = f"Unknown language: {name}"
        raise ValueError(msg)
