"""Web 搜索工具

提供：
- perform_search: 执行单次 Web 搜索
- perform_all_searches: 并发执行多次搜索
- parse_search_result: 解析搜索结果为结构化数据
- WebReference: 搜索结果引用数据结构
"""

from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, cast

import httpx
from openai import AsyncOpenAI

from venture_agents.utils.config import get_openai_api_key, load_config
from venture_agents.utils.log import setup_logger


# 日志配置
logger = setup_logger("Searcher", "Searcher.log")


# 缓存
CACHE_PATH = Path(".react_search_cache.json")


def _load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        try:
            return cast("dict[str, Any]", json.loads(CACHE_PATH.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_cache(cache: dict[str, Any]) -> None:
    try:
        CACHE_PATH.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError) as e:
        logger.warning("Failed to save cache: %s", e)


def _has_url(text: str) -> bool:
    return bool(re.search(r"https?://", text or ""))


def _dedent_md(text: str) -> str:
    return re.sub(r"\n{3,}", "\n\n", text.strip())


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 200].rstrip() + "\n\n*…truncated…*\n"


def _append_summary(text: str) -> str:
    if "\n### Summary of Insights" in text:
        return text
    return text.rstrip() + "\n\n---\n### Summary of Insights\n- *(Add key takeaways when merging with RAG.)*\n"


def _estimate_cost_from_usage(usage: Any) -> float:  # noqa: ANN401
    try:
        tokens = getattr(usage, "total_tokens", None)
        if tokens is None:
            tokens = usage.get("total_tokens", 0)
        return round((tokens or 0) / 1_000_000 * 5.0, 6)
    except (AttributeError, TypeError, KeyError):
        return 0.0


async def perform_search(
    query: str,
    max_results: int = 5,
    *,
    add_summary: bool = True,
    max_chars: int = 8000,
    use_cache: bool = True,
    verbose: bool = True,
) -> tuple[str, float]:
    """执行一次通用在线搜索（GPT-4o-search-preview）

    Args:
        query: 搜索查询
        max_results: 最大结果数
        add_summary: 是否添加摘要
        max_chars: 最大字符数
        use_cache: 是否使用缓存
        verbose: 是否显示详细信息

    Returns:
        tuple[str, float]: (Markdown 文本, 估算费用)
    """
    cache = _load_cache() if use_cache else {}
    if use_cache and query in cache:
        if verbose:
            logger.info("Cache hit: %s", query)
        item = cache[query]
        return item["text"], float(item.get("cost", 0.0))

    config = load_config("DDAgent.Searcher")
    llm_proxy: str = config.get("llm_proxy", "")
    http_client = httpx.AsyncClient(proxy=llm_proxy) if llm_proxy else httpx.AsyncClient()

    client = AsyncOpenAI(
        api_key=get_openai_api_key(),
        http_client=http_client,
    )
    model = "gpt-4o-search-preview"

    system_prompt = (
        "You are a research assistant supplementing mining due diligence sections. "
        "Search the public web (news, blogs, industry portals, publications). "
        "Every finding must include a clear clickable reference URL (Markdown link). "
        "Keep tone factual and cautious; note uncertainties explicitly.\n\n"
        "IMPORTANT:\n"
        "- ALWAYS return high-signal sources in recent FIVE years."
    )

    user_prompt = f"""
Perform a live web search:

Query: {query}

Instructions:
- Return the most relevant 3–5 findings.
- For each result, include:
  - Title
  - Date (if available)
  - Source name and **Markdown link**
  - 3–6 sentence factual summary (avoid speculation)
- ALWAYS return high-signal sources in recent FIVE years.
- Always include the URL in-line as a reference.
- Output **Markdown** only.

Generate up to {max_results} items.
"""

    started = time.time()
    try:
        resp = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        )
        content = resp.choices[0].message.content
        if content is None:
            text = "⚠️ No content returned from search."
        else:
            text = content.strip()
        cost = _estimate_cost_from_usage(getattr(resp, "usage", {}))
        elapsed = time.time() - started
        if verbose:
            logger.info("Web search done in %.1fs (est. $%.4f)", elapsed, cost)

        if not _has_url(text):
            text = "⚠️ No references (URLs) returned.\n\n" + text

        text = _dedent_md(text)
        text = _truncate(text, max_chars)
        if add_summary:
            text = _append_summary(text)

        if use_cache:
            cache[query] = {"text": text, "cost": cost, "ts": time.time()}
            _save_cache(cache)
    except Exception as e:
        err = f"⚠️ Search failed: {e}"
        if verbose:
            logger.exception("Search failed")
        return err, 0.0
    else:
        return text, cost


async def perform_all_searches(
    queries: list[str],
    *,
    add_summary: bool = True,
    max_chars: int = 8000,
    use_cache: bool = True,
    verbose: bool = True,
) -> tuple[dict[str, str], float]:
    """并发执行多次搜索

    Args:
        queries: 搜索查询列表
        add_summary: 是否添加摘要
        max_chars: 最大字符数
        use_cache: 是否使用缓存
        verbose: 是否显示详细信息

    Returns:
        tuple[dict[str, str], float]: (查询到结果的映射, 累计费用)
    """
    cache = _load_cache() if use_cache else {}
    total_cost = 0.0
    results: dict[str, str] = {}

    async def _run(q: str) -> tuple[str, str, float]:
        if use_cache and q in cache:
            if verbose:
                logger.info("Cache hit: %s", q)
            item = cache[q]
            return q, item["text"], float(item.get("cost", 0.0))
        text, cost = await perform_search(
            q,
            add_summary=add_summary,
            max_chars=max_chars,
            use_cache=use_cache,
            verbose=verbose,
        )
        return q, text, cost

    coros = [_run(q) for q in queries]
    responses = await asyncio.gather(*coros, return_exceptions=False)

    for q, text, cost in responses:
        results[q] = text
        total_cost += float(cost)
        if use_cache:
            cache[q] = {"text": text, "cost": cost, "ts": time.time()}

    if use_cache:
        _save_cache(cache)

    if verbose:
        logger.info("Total fallback search cost: $%.6f", total_cost)

    return results, total_cost


@dataclass
class WebReference:
    """Web 搜索结果引用"""

    summary: str
    source: str
    url: str
    date: datetime | None


def parse_search_result(result_text: str) -> list[WebReference]:
    """将搜索结果解析为 WebReference 结构

    Args:
        result_text: 搜索结果文本

    Returns:
        list[WebReference]: 解析后的引用列表
    """
    web_references: list[WebReference] = []
    if "🌐 Source" in result_text:
        # Case 1: 结构化格式
        raw_sections: list[str] = re.split(r"(?=^### )", result_text, flags=re.MULTILINE)

        for sec_raw in raw_sections:
            sec = sec_raw.strip()
            if not sec:
                continue

            date_match = re.search(r"Date:[*\s]*([^\n]+)", sec)
            date_str: str | None = date_match.group(1).strip() if date_match else None

            def parse_date(ds: str | None) -> datetime | None:
                if not ds:
                    return None
                cleaned = re.sub(r"\([^)]*\)", "", ds)
                cleaned = re.sub(r"\b([A-Za-z]{3})\.", r"\1", cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()

                date_formats = [
                    "%Y-%m-%d",
                    "%Y-%m",
                    "%Y",
                    "%B %d, %Y",
                    "%b %d, %Y",
                    "%B %d %Y",
                    "%b %d %Y",
                    "%B %Y",
                    "%b %Y",
                ]

                candidates = [cleaned]
                if "," in cleaned:
                    candidates.append(cleaned.replace(",", ""))

                for candidate in candidates:
                    for fmt in date_formats:
                        try:
                            return datetime.strptime(candidate, fmt)
                        except ValueError:
                            continue
                return None

            date: datetime | None = parse_date(date_str)

            source_match = re.search(r"Source:[*\s]*\[([^\]]+)\]\(([^)]+)\)", sec)
            source_name: str = source_match.group(1).strip() if source_match else "Unknown"
            source_url: str = source_match.group(2).strip() if source_match else "Unknown URL"

            summary_match = re.search(r"\*\*Summary:\*\*([\s\S]+)", sec)
            summary: str = summary_match.group(1).strip() if summary_match else ""
            summary = re.sub(r"\(\[[^\]]+\]\([^)]+\)\)\s*$", "", summary).strip()

            if not summary:
                continue

            web_references.append(WebReference(summary, source_name, source_url, date))
    else:
        # Case 2: 简单格式
        for item in re.split("\n+", result_text):
            match = re.search(r"^(?P<body>.*?)(?:\s*\(\[(?P<source>[^\]]+)\]\((?P<url>[^)]+)\)\)\s*)$", item)
            if match:
                body = match.group("body").rstrip()
                source = match.group("source")
                url = match.group("url")
                url = re.sub(r"\??utm_source=openai$", "", url)

                if not body:
                    continue

                web_references.append(WebReference(body, source, url, None))
    return web_references


# 兼容旧命名
performSearch = perform_search
performAllSearches = perform_all_searches
parseSearchResult = parse_search_result
