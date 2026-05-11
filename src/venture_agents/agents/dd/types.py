"""DDAgent 类型定义"""

from dataclasses import dataclass


@dataclass
class GPTSectionOutput:
    """GPT 章节输出容器"""

    project_overview: str = ""
    key_project_strengths: str = ""
    key_project_risks: str = ""
    information_gaps: str = ""
