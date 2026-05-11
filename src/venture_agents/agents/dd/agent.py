"""DDAgent - 尽职调查报告生成 Agent"""

from __future__ import annotations

import asyncio
import re
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any

from venture_agents.agents.base import BaseAgent
from venture_agents.utils.config import get_openai_api_key, get_settings
from venture_agents.utils.log import setup_logger


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from venture_agents.agents.dd.sections._base import Section
    from venture_agents.schemas.config import ProjectSettings
    from venture_agents.schemas.enums import Language


class DDAgent(BaseAgent):
    """尽职调查报告生成 Agent"""

    # name = "dd_agent"
    # description = "Mining Due Diligence Report Generation Agent"

    def __init__(
        self,
        company: str,
        mine: str,
        language: Language,
        user_upload_dir: str | None = None,
        use_dynamodb: bool = True,
    ) -> None:
        super().__init__()

        self._company = company
        self._mine = mine
        self._language = language
        self._user_upload_dir = user_upload_dir
        self._use_dynamodb = use_dynamodb

        self._settings: ProjectSettings = get_settings()
        self._logger = setup_logger("DDAgent", "DDAgent.log", self._settings.agents.dd.log_level)

        self._async_semaphore = asyncio.Semaphore(
            self._settings.agents.dd.async_semaphore,
        )

        self._llm_model = self._settings.llm.chat.model
        self._llm_temperature = self._settings.llm.chat.temperature

    def run(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """同步运行接口

        调用 generate_report 生成报告。
        RAG Engine 在 asyncio.run() 之前初始化，因为其内部包含同步的
        asyncio.run() 调用（下载报告），不能嵌套在已运行的 event loop 中。
        """
        return asyncio.run(self.generate_report(report_dir=kwargs.get("report_dir", "reports")))

    # ------------------------------------------------------------------
    # 编排主流程
    # ------------------------------------------------------------------

    async def generate_report(
        self,
        report_dir: str = "reports",
    ) -> tuple[Path, list[str]]:
        """生成尽职调查报告

        流程:
        1. 自动发现所有 sections
        2. 并行运行 primary phase sections
        3. 合并 references + 组装 article_body
        4. 并行运行 post phase sections（传入 article_body）
        5. 组装最终报告

        Returns:
            tuple[Path, list[str]]: (报告文件路径, 追问问题列表)
        """
        from venture_agents.agents.dd.sections import discover_sections

        time_start = perf_counter()
        all_sections = discover_sections()

        # 按 phase 分组
        primary_sections = [s for s in all_sections if s.meta.phase == "primary"]
        post_sections = [s for s in all_sections if s.meta.phase == "post"]

        # ===== Phase 1: 并行运行所有 primary sections =====
        self._logger.info("Phase 1: 并行生成 %d 个主体章节...", len(primary_sections))

        async def _run_with_semaphore(
            coro: Coroutine[Any, Any, tuple[str, list[str]]],
        ) -> tuple[str, list[str]]:
            async with self._async_semaphore:
                return await coro

        primary_results: list[tuple[str, list[str]]] = await asyncio.gather(
            *[_run_with_semaphore(s.build(self)) for s in primary_sections],
        )

        # 合并 references（照搬老代码 _merge_paragraphs_with_references）
        paragraphs = [r[0] for r in primary_results]
        ref_lists = [r[1] for r in primary_results]
        fixed_paras, fixed_references = self._merge_paragraphs_with_references(paragraphs, ref_lists)
        fixed_paras, fixed_references = self._deduplicate_references(fixed_paras, fixed_references)

        # 组装 article_body（按 order 排列，插入 Markdown 标题）
        article_body = self._assemble_article_body(primary_sections, fixed_paras)

        time_article_body = perf_counter()
        self._logger.info("Phase 1 完成（耗时：%.2fs）", time_article_body - time_start)

        # ===== Phase 2: 运行 post sections =====
        self._logger.info("Phase 2: 生成 %d 个总结性章节...", len(post_sections))
        post_results: list[tuple[str, list[str]]] = await asyncio.gather(
            *[
                _run_with_semaphore(s.build(self, article_body=article_body, fixed_references=fixed_references))
                for s in post_sections
            ],
        )

        # ===== Phase 3: 最终组装 =====
        report_text = self._assemble_final_report(
            primary_sections,
            fixed_paras,
            post_sections,
            post_results,
            fixed_references,
        )

        # 写入文件
        report_path = Path(report_dir)
        report_path.mkdir(parents=True, exist_ok=True)
        local_path = report_path / f"{self._company}.md"
        local_path.write_text(report_text, encoding="utf-8")

        time_done = perf_counter()
        self._logger.info("报告全部撰写完成（总耗时：%.2fs）", time_done - time_start)

        # followup 的追问问题列表
        followup_questions: list[str] = []
        for s, r in zip(post_sections, post_results, strict=True):
            if s.meta.name == "followup":
                # followup build 返回的 references 实际上是 questions
                followup_questions = r[1]

        return local_path, followup_questions

    # ------------------------------------------------------------------
    # 引用合并与清理
    # ------------------------------------------------------------------

    def _merge_paragraphs_with_references(
        self,
        passages: list[str],
        reference_lists: list[list[str]],
    ) -> tuple[list[str], list[str]]:
        """合并多个独立 passage 与其 reference 列表，重新分配全局唯一引用编号。

        Parameters
        ----------
        passages :
            多个文本段落，每个段内自行使用 [1], [2], ... 引用编号。
        reference_lists :
            每个 passage 对应的 reference 列表，第一个元素对应 [1]。

        Returns
        -------
        tuple[list[str], list[str]]:
            修改过编号的 passage list，顺序与之前相同；
            融合后的 reference list
        """
        global_ref_list: list[str] = []
        fixed_passages: list[str] = []
        current_index: int = 1  # 全局 reference 编号计数器

        for passage, refs in zip(passages, reference_lists, strict=True):
            local_to_global: dict[int, int] = {}

            # 查找并处理所有引用编号（去重）
            for match in re.finditer(r"\[\s*(\d+)\s*\]", passage):
                local_num = int(match.group(1))
                if local_num not in local_to_global and 1 <= local_num <= len(refs):
                    local_to_global[local_num] = current_index
                    global_ref_list.append(refs[local_num - 1])
                    current_index += 1

            # 替换引用编号，无效的引用会被移除
            # 使用闭包捕获局部变量，避免循环变量绑定问题
            def make_replace_func(local_map: dict[int, int]) -> Callable[[re.Match[str]], str]:
                def replace_match(m: re.Match[str]) -> str:
                    num = int(m.group(1))
                    return f"[{local_map[num]}]" if num in local_map else ""

                return replace_match

            new_passage: str = re.sub(r"\[\s*(\d+)\s*\]", make_replace_func(local_to_global), passage)
            fixed_passages.append(new_passage)

        return fixed_passages, global_ref_list

    def _deduplicate_references(
        self,
        passages: list[str],
        references: list[str],
    ) -> tuple[list[str], list[str]]:
        """去重引用列表，并将正文中的重复引用编号重定向到最早出现的位置。"""
        ref_to_index: dict[str, int] = {}
        old_to_new: dict[int, int] = {}
        unique_refs: list[str] = []

        # 构建引用文本 -> 新编号 的映射
        for idx, ref in enumerate(references, 1):
            if ref in ref_to_index:
                old_to_new[idx] = ref_to_index[ref]
            else:
                new_idx = len(unique_refs) + 1
                ref_to_index[ref] = new_idx
                old_to_new[idx] = new_idx
                unique_refs.append(ref)

        def replace_match(match: re.Match[str]) -> str:
            old_idx = int(match.group(1))
            new_idx = old_to_new.get(old_idx, old_idx)
            return f"[{new_idx}]"

        fixed_passages = [re.sub(r"\[\s*(\d+)\s*\]", replace_match, passage) for passage in passages]

        # 在这里做引用压缩
        fixed_passages = [self._clean_repeated_citations(p) for p in fixed_passages]

        return fixed_passages, unique_refs

    def _clean_repeated_citations(self, text: str) -> str:
        """清理正文中重复的引用编号：
        1. 连续相同的引用 [15][15][15] -> [15]
        2. 同一串中的重复引用 [15][43][15][43] -> [15][43]
        """
        # 1) 先把连续完全一样的引用压缩成一个
        #    例如 [15][15][15] -> [15]
        text = re.sub(r"(\[\s*(\d+)\s*\])(?:\s*\[\s*\2\s*\])+", r"[\2]", text)

        # 2) 再对「一整串引用」去重（保持顺序）
        #    例如 [15][43][15][21][43] -> [15][43][21]
        def dedup_cluster(match: re.Match[str]) -> str:
            cluster = match.group(0)
            nums = re.findall(r"\d+", cluster)
            seen: list[str] = []
            for n in nums:
                if n not in seen:
                    seen.append(n)
            return "".join(f"[{n}]" for n in seen)

        # 匹配一串连续的 [数字] 引用（至少两个）
        return re.sub(r"(?:\[\s*\d+\s*\]\s*){2,}", dedup_cluster, text)

    # ------------------------------------------------------------------
    # 报告组装
    # ------------------------------------------------------------------

    def _assemble_article_body(
        self,
        sections: list[Section],
        fixed_paras: list[str],
    ) -> str:
        """根据 section 元数据组装 article_body

        父章节（如 order=[4]）也是正式的 Section，build 返回空内容，
        discover_sections() 按 order 排序后天然排在子章节前面，
        此处只需简单遍历即可还原完整章节结构。
        """
        parts: list[str] = []
        lang_idx: int = self._language

        for section, para in zip(sections, fixed_paras, strict=True):
            level = section.meta.heading_level
            order_str = ".".join(str(n) for n in section.meta.order)
            if len(section.meta.order) == 1:
                order_str += "."
            title = section.meta.title[lang_idx]
            heading = f"{'#' * level} {order_str} {title}"
            parts.append(f"{heading}\n\n{para}" if para else heading)

        return "\n\n".join(parts)

    def _assemble_final_report(
        self,
        primary_sections: list[Section],
        fixed_paras: list[str],
        post_sections: list[Section],
        post_results: list[tuple[str, list[str]]],
        fixed_references: list[str],
    ) -> str:
        """最终报告组装

        将 post sections（概述、亮点、风险等）+ primary sections（正文）+ references 组装为完整报告。
        """
        article_title: list[str] = [
            "桌面尽职调查报告",
            "Desk Due Diligence Report",
            "Informe de Diligencia Debida de Escritorio",
            "Relatório de Due Diligence de Mesa",
            "تقرير العناية الواجبة المكتبي",
        ]
        ref_title: list[str] = ["参考文献", "References", "Referencias", "Referências", "المراجع"]

        lang_idx: int = self._language

        # 重建 article_body
        article_body = self._assemble_article_body(primary_sections, fixed_paras)

        # 分割 post sections：primary 最小顶级 order 之前 vs 之后
        min_primary_top = min(s.meta.order[0] for s in primary_sections)
        before_parts: list[str] = []
        after_parts: list[str] = []

        for section, (text, _) in zip(post_sections, post_results, strict=True):
            # 老代码中 followup 章节在最终报告中已被注释掉，此处保持一致
            if section.meta.name == "followup":
                continue

            order_num = section.meta.order[0]
            order_str = ".".join(str(n) for n in section.meta.order)
            if len(section.meta.order) == 1:
                order_str += "."
            title = section.meta.title[lang_idx]
            entry = f"{'#' * section.meta.heading_level} {order_str} {title}\n\n{text}"

            if order_num < min_primary_top:
                before_parts.append(entry)
            else:
                after_parts.append(entry)

        # 组装最终报告
        report = f"# {article_title[lang_idx]}: {self._company}\n\n"
        for part in before_parts:
            report += part + "\n\n"
        report += article_body + "\n\n"
        for part in after_parts:
            report += part + "\n\n"
        report += f"## {ref_title[lang_idx]}\n\n"
        for i, ref in enumerate(fixed_references, 1):
            report += f"{i}. {ref}\n"

        return report

    # ------------------------------------------------------------------
    # LLM 调用（已实现）
    # ------------------------------------------------------------------

    async def _ainvoke_llm(self, msgs: list[dict[str, str]]) -> str:
        """调用 LLM 并返回文本内容"""
        import httpx
        from openai import AsyncOpenAI

        openai_settings = self._settings.llm.openai
        timeout = httpx.Timeout(openai_settings.timeout_seconds, read=openai_settings.read_timeout_seconds)
        client_kwargs: dict[str, Any] = {
            "api_key": get_openai_api_key(),
            "max_retries": openai_settings.max_retries,
        }
        if openai_settings.base_url is not None:
            client_kwargs["base_url"] = openai_settings.base_url
        if openai_settings.organization is not None:
            client_kwargs["organization"] = openai_settings.organization

        async with httpx.AsyncClient(proxy=openai_settings.proxy, timeout=timeout) as http_client:
            client = AsyncOpenAI(http_client=http_client, **client_kwargs)
            request_kwargs: dict[str, Any] = {
                "model": self._llm_model,
                "temperature": self._llm_temperature,
                "messages": msgs,
            }
            if self._settings.llm.chat.max_tokens is not None:
                request_kwargs["max_tokens"] = self._settings.llm.chat.max_tokens

            resp = await client.chat.completions.create(**request_kwargs)

        content = resp.choices[0].message.content
        if content is None:
            return ""
        return content.strip()

    def _strip_inline_citations(self, text: str) -> str:
        """移除行内引用标记（如 [12] 或 [1, 2, 24]）"""
        return re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", " ", text)
