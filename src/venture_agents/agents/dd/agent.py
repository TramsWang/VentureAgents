"""DDAgent - 尽职调查报告生成 Agent"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from time import perf_counter
from typing import TYPE_CHECKING, Any, cast

import httpx
from openai import AsyncOpenAI

from venture_agents.agents.base import BaseAgent
from venture_agents.schemas.enums import Language
from venture_agents.tools.file_parser import parse_files
from venture_agents.utils.config import get_openai_api_key, get_settings
from venture_agents.utils.log import setup_logger


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

    from venture_agents.agents.dd.sections._base import Section
    from venture_agents.schemas.config import ProjectSettings
    from venture_agents.schemas.file_parsing import FileDescription


SETTINGS: ProjectSettings = get_settings()
LOGGER = setup_logger("DDAgent", "DDAgent.log", SETTINGS.agents.dd.log_level)


class DDAgent(BaseAgent):
    """尽职调查报告生成 Agent

    Attributes:
        company: 目标公司名称
        language: 报告语言
        company_intro_file: 公司介绍（PDF）文件路径
        company_financial_statement: 公司财务状况统计信息（Excel）文件路径
    """

    name = "dd_agent"
    description = "Due Diligence Report Generation Agent for Venture Capital"

    def __init__(
        self, company: str, language: Language = Language.Chinese, supplementary_files: list[str] | None = None
    ) -> None:
        super().__init__()

        self._company = company
        self._language = language

        self._logger = setup_logger("DDAgent", "DDAgent.log", SETTINGS.agents.dd.log_level)

        self._async_semaphore = asyncio.Semaphore(
            SETTINGS.agents.dd.async_semaphore,
        )

        self._llm_model = SETTINGS.llm.chat.model
        self._llm_temperature = SETTINGS.llm.chat.temperature
        self._llm_http_client, self._llm_client = self._create_llm_client()

        self._supplementary_files: list[str] = supplementary_files if supplementary_files else []
        self._parsed_supp_files: list[FileDescription] = []

    def run(self, **kwargs: Any) -> Any:  # noqa: ANN401
        """同步运行接口

        调用 generate_report 生成报告。
        RAG Engine 在 asyncio.run() 之前初始化，因为其内部包含同步的
        asyncio.run() 调用（下载报告），不能嵌套在已运行的 event loop 中。
        """

        self._parsed_supp_files = parse_files(self._llm_client, self._supplementary_files, self._async_semaphore)

        async def _run() -> tuple[Path, list[str]]:
            try:
                return await self.generate_report(report_dir=kwargs.get("report_dir", "reports"))
            finally:
                await self.aclose()

        return asyncio.run(_run())

    def _create_llm_client(self) -> tuple[httpx.AsyncClient, AsyncOpenAI]:
        """创建可复用的 OpenAI Responses 客户端。"""
        openai_settings = SETTINGS.llm.openai
        timeout = httpx.Timeout(openai_settings.timeout_seconds, read=openai_settings.read_timeout_seconds)
        http_client = httpx.AsyncClient(proxy=openai_settings.proxy, timeout=timeout)
        client_kwargs: dict[str, Any] = {
            "api_key": get_openai_api_key(),
            "http_client": http_client,
            "max_retries": openai_settings.max_retries,
        }
        if openai_settings.base_url is not None:
            client_kwargs["base_url"] = openai_settings.base_url
        if openai_settings.organization is not None:
            client_kwargs["organization"] = openai_settings.organization
        if openai_settings.project is not None:
            client_kwargs["project"] = openai_settings.project

        return http_client, AsyncOpenAI(**client_kwargs)

    async def aclose(self) -> None:
        """关闭 DDAgent 持有的异步 HTTP 连接。"""
        await self._llm_http_client.aclose()

    async def __aenter__(self) -> DDAgent:
        return self

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        await self.aclose()

    async def check_file_usage(self, task_sys_prompt: str) -> list[FileDescription]:
        """根据任务prompt决定要用哪些supplementary files辅助内容撰写"""
        if not self._parsed_supp_files:
            return []

        _sys_prompt: str = """你是一个“文章筛选助手”。用户会提供一个写作任务要求，以及若干篇文章的 overview 列表，每篇文章都有编号。

你的任务是根据写作任务要求和文章 overview，判断哪些文章需要被进一步阅读和采用。

筛选原则：
1. 只选择与写作任务直接相关、可能为章节撰写提供事实依据、案例、数据、方法、背景或论点支持的文章。
2. 不要因为标题或关键词相似就自动选择，必须结合写作任务判断。
3. 如果 overview 信息不足，但文章看起来可能包含关键内容，可以选择，但需要在原因中说明“不确定但可能相关”。
4. 排除主题泛泛相关但对当前写作任务帮助有限的文章。
5. 优先保证不漏掉关键文章，同时避免选择明显无关文章。
6. 不要编造 overview 中没有的信息。

输出要求：
- 只返回 JSON 数组。
- JSON 数组中的每个元素代表一篇需要采用的文章。
- 每个元素必须包含：
  - "article_id": 文章编号
  - "reason": 选择原因，简洁说明该文章可能如何支持写作任务
- 不要返回不采用的文章。
- 不要输出 Markdown。
- 不要输出 JSON 以外的任何内容。
- 如果没有任何文章需要采用，返回空数组 []。

输出格式示例：
[
  {
    "article_id": 1,
    "reason": "overview 显示该文章包含与任务主题直接相关的背景和案例，可用于章节论证。"
  },
  {
    "article_id": 3,
    "reason": "overview 提到该文章包含相关方法和数据，可能支持任务中的技术分析部分。"
  }
]"""

        file_overviews: str = "\n\n".join(
            (
                f"文章编号: {idx}\n"
                f"文章标题: {file_desc.title}\n"
                f"文章Overview: {file_desc.overview or '（无 overview）'}"
            )
            for idx, file_desc in enumerate(self._parsed_supp_files, 1)
        )

        _user_prompt: str = f"""## 写作任务要求:

{task_sys_prompt}

---

## 可选的文章列表:

{file_overviews}
"""
        # 和大模型API交互，解析结果，生成返回的筛选列表
        response_text = await self._ainvoke_llm(_sys_prompt, _user_prompt, use_web_search=False)
        raw_json = response_text.strip()
        if raw_json.startswith("```"):
            raw_json = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_json, flags=re.IGNORECASE).strip()

        import json

        try:
            selected_articles = json.loads(raw_json)
        except json.JSONDecodeError:
            json_match = re.search(r"\[[\s\S]*\]", raw_json)
            if json_match is None:
                self._logger.warning("Failed to parse supplementary file selection response: %s", response_text)
                return []
            try:
                selected_articles = json.loads(json_match.group(0))
            except json.JSONDecodeError:
                self._logger.warning("Failed to parse supplementary file selection response: %s", response_text)
                return []

        if not isinstance(selected_articles, list):
            self._logger.warning("Supplementary file selection response is not a JSON array: %s", response_text)
            return []

        selected_files: list[FileDescription] = []
        seen_ids: set[int] = set()
        for article in selected_articles:
            if not isinstance(article, dict):
                self._logger.warning("Skipping invalid supplementary file selection item: %s", article)
                continue

            article_data = cast("dict[str, object]", article)
            if "article_id" not in article_data or not isinstance(article_data.get("reason"), str):
                self._logger.warning(
                    "Skipping supplementary file selection item without article_id/reason: %s",
                    article,
                )
                continue

            article_id = article_data["article_id"]
            if not isinstance(article_id, int | str):
                self._logger.warning("Skipping supplementary file selection item with invalid article_id: %s", article)
                continue
            try:
                article_idx = int(article_id)
            except ValueError:
                self._logger.warning("Skipping supplementary file selection item with invalid article_id: %s", article)
                continue

            if article_idx in seen_ids or not 1 <= article_idx <= len(self._parsed_supp_files):
                continue

            seen_ids.add(article_idx)
            selected_files.append(self._parsed_supp_files[article_idx - 1])

        return selected_files

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

    def _response_value(self, item: object, key: str) -> object | None:
        """Read a field from OpenAI SDK models or OpenAI-compatible dicts."""
        if isinstance(item, Mapping):
            return item.get(key)
        return getattr(item, key, None)

    def _collect_text_parts(self, value: object) -> list[str]:
        """Collect text fragments from common OpenAI response content shapes."""
        if value is None or isinstance(value, str | bytes):
            return [str(value).strip()] if isinstance(value, str) and value.strip() else []
        if isinstance(value, Mapping):
            for key in ("text", "content"):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    return [text.strip()]
            return []
        if isinstance(value, Sequence):
            parts: list[str] = []
            for item in value:
                parts.extend(self._collect_text_parts(item))
            return parts

        parts = []
        for key in ("text", "content"):
            text = getattr(value, key, None)
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return parts

    def _extract_response_text(self, response: object) -> str:
        """Extract generated text from Responses API and compatible response shapes."""
        output_text = self._response_value(response, "output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = self._response_value(response, "output")
        if isinstance(output, Sequence) and not isinstance(output, str | bytes):
            parts: list[str] = []
            for output_item in output:
                content = self._response_value(output_item, "content")
                parts.extend(self._collect_text_parts(content))
                parts.extend(self._collect_text_parts(self._response_value(output_item, "text")))
            text = "".join(parts).strip()
            if text:
                return text

        choices = self._response_value(response, "choices")
        if isinstance(choices, Sequence) and not isinstance(choices, str | bytes):
            parts = []
            for choice in choices:
                message = self._response_value(choice, "message")
                content = self._response_value(message, "content")
                parts.extend(self._collect_text_parts(content))
            text = "".join(parts).strip()
            if text:
                return text

        return ""

    async def _ainvoke_llm(self, system_prompt: str, user_prompt: str, use_web_search: bool = True) -> str:
        """使用 OpenAI Responses API 调用 LLM 并返回文本内容。"""
        request_kwargs: dict[str, Any] = {
            "model": self._llm_model,
            "temperature": self._llm_temperature,
            "instructions": system_prompt,
            "input": user_prompt,
        }
        if use_web_search:
            request_kwargs["tools"] = [{"type": "web_search"}]
        if SETTINGS.llm.chat.max_tokens is not None:
            request_kwargs["max_output_tokens"] = SETTINGS.llm.chat.max_tokens

        resp = await self._llm_client.responses.create(**request_kwargs)

        content = self._extract_response_text(resp)
        if not content:
            self._logger.warning(
                "LLM response did not contain generated text; response_id=%s",
                self._response_value(resp, "id"),
            )
            msg = "LLM response did not contain generated text"
            raise RuntimeError(msg)
        return content

    def _strip_inline_citations(self, text: str) -> str:
        """移除行内引用标记（如 [12] 或 [1, 2, 24]）"""
        return re.sub(r"\[\s*\d+(?:\s*,\s*\d+)*\s*\]", " ", text)
