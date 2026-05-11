"""Section 自动发现

扫描当前目录下所有 .py 文件（排除 __init__.py 和 _base.py），
收集每个文件中的 SECTION_DEF 列表，汇总为 Section 注册表。
"""

from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from venture_agents.agents.dd.sections._base import Section


def discover_sections() -> list[Section]:
    """扫描当前包下所有 section 模块，返回 Section 列表（按 order 排序）"""
    sections: list[Section] = []

    # 遍历当前包下的所有模块
    package = importlib.import_module(__name__)
    for _importer, modname, _ispkg in pkgutil.iter_modules(package.__path__):
        if modname.startswith("_"):
            continue  # 跳过 _base.py 等

        module = importlib.import_module(f"{__name__}.{modname}")

        # 每个模块应导出 SECTION_DEF: list[Section]
        module_sections: list[Section] | None = getattr(module, "SECTION_DEF", None)
        if module_sections is None:
            continue

        sections.extend(module_sections)

    # 按 order 排序
    sections.sort(key=lambda s: s.meta.order)
    return sections
