"""用于文件解析的类型约束"""

from dataclasses import dataclass


@dataclass
class FileDescription:
    """用于描述文件内容的类

    Attributes:
        title: 文件标题
        content_md: 转换成markdown格式的文件内容
        overview: 文件内容概览
    """

    title: str
    content_md: str
    overview: str
