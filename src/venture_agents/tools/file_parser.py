"""将文件（通常是用于向Agent提供辅助内容的文件）解析转换为markdown格式的工具"""

from __future__ import annotations

import asyncio
import concurrent.futures
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from venture_agents.schemas.file_parsing import FileDescription
from venture_agents.tools.excel_parser import parse_excel_to_markdown
from venture_agents.tools.pdf_parser import parse_pdf_to_markdown
from venture_agents.tools.word_parser import parse_word_to_markdown


if TYPE_CHECKING:
    from collections.abc import Callable, Coroutine

_EXCEL_SUFFIXES = {".xlsx", ".xlsm", ".xltx", ".xltm"}
_PDF_SUFFIXES = {".pdf"}
_TEXT_SUFFIXES = {".txt"}
_WORD_SUFFIXES = {".docx"}
_SUMMARY_CONTENT_LIMIT = 20_000


def _normalize_files(files: list[str] | list[Path] | None) -> list[Path]:
    """Normalize user provided file paths and validate basic existence."""
    if files is None:
        return []

    paths = [Path(file).expanduser() for file in files]
    for path in paths:
        if not path.is_file():
            msg = f"File does not exist or is not a regular file: {path}"
            raise FileNotFoundError(msg)
    return paths


def _render_excel_markdown(file_path: Path) -> str:
    """Render all non-empty Excel sheets as one Markdown document."""
    sheets = parse_excel_to_markdown(file_path)
    return "\n\n".join(f"## {sheet.sheet_name}\n\n{sheet.markdown}" for sheet in sheets)


def _parse_file_to_markdown(file_path: Path) -> str:
    """Dispatch one file to the parser matching its suffix."""
    suffix = file_path.suffix.lower()
    if suffix in _TEXT_SUFFIXES:
        return file_path.read_text(encoding="utf-8")
    if suffix in _WORD_SUFFIXES:
        return parse_word_to_markdown(file_path)
    if suffix in _EXCEL_SUFFIXES:
        return _render_excel_markdown(file_path)
    if suffix in _PDF_SUFFIXES:
        return parse_pdf_to_markdown(file_path)

    msg = f"Unsupported file type: {file_path.suffix or '<none>'} ({file_path})"
    raise ValueError(msg)


async def _run_blocking(
    executor: concurrent.futures.Executor,
    func: Callable[..., object],
    *args: object,
) -> object:
    """Run blocking parser work in a thread without relying on loop thread callbacks."""
    future = executor.submit(func, *args)
    try:
        while not future.done():
            await asyncio.sleep(0.01)
        return future.result()
    except asyncio.CancelledError:
        future.cancel()
        raise


def _response_text(response: object) -> str:
    """Extract generated text from common OpenAI-compatible response shapes."""
    output_text = getattr(response, "output_text", None)
    if output_text is not None:
        return str(output_text).strip()

    choices = getattr(response, "choices", None)
    if choices:
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None)
        if content is not None:
            return str(content).strip()

    return ""


async def _summarize_with_llm(llm_client: object, title: str, content_md: str) -> str:
    """Ask the configured AsyncOpenAI client for a 100-200 Chinese-character overview."""
    system_prompt = (
        "你是严谨的文档分析助手。请根据用户提供的文档内容生成中文内容概览，"
        "只输出总结正文，不要使用标题、列表、引用或额外说明。"
    )
    user_prompt = (
        f"文档标题：{title}\n\n"
        "请用100-200字总结该文档的核心内容、关键信息和用途。"
        "如果文档内容为空，请说明文档未包含可总结的文本内容。\n\n"
        f"文档内容（Markdown）：\n{content_md}"
    )

    from venture_agents.utils.config import get_settings

    settings = get_settings()
    response = await cast("Any", llm_client).responses.create(
        model=settings.llm.chat.model,
        temperature=settings.llm.chat.temperature,
        instructions=system_prompt,
        input=user_prompt,
        max_output_tokens=settings.llm.chat.max_tokens,
    )
    return _response_text(response)


def _run_async(coro: Coroutine[object, object, list[FileDescription]]) -> list[FileDescription]:
    """Run an async parser coroutine from the synchronous public API."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(asyncio.run, coro)
        return future.result()


def _resolve_semaphore(semaphore: int | asyncio.Semaphore | None) -> asyncio.Semaphore | None:
    """Convert the public semaphore argument into an asyncio.Semaphore."""
    if semaphore is None:
        return None
    if isinstance(semaphore, int):
        if semaphore < 1:
            msg = "semaphore must be greater than or equal to 1"
            raise ValueError(msg)
        return asyncio.Semaphore(semaphore)
    return semaphore


async def _parse_files_async(
    llm_client: object,
    files: list[str] | list[Path] | None = None,
    semaphore: int | asyncio.Semaphore | None = 5,
) -> list[FileDescription]:
    """解析文件内容，以FileDescription格式保存

    当前解析支持：TXT, WORD, EXCEL, PDF

    Args:
        llm_client: 辅助文件内容解析的大模型Client
        files: 文件路径列表
        semaphore: 最大并行解析文件数。可传入整数或已创建的 ``asyncio.Semaphore``；
            传入 ``None`` 时不额外限制并发。
    """
    paths = _normalize_files(files)
    if not paths:
        return []

    limiter = _resolve_semaphore(semaphore)
    max_workers = semaphore if isinstance(semaphore, int) else len(paths)

    async def _parse_one(
        file_path: Path,
        executor: concurrent.futures.Executor,
    ) -> FileDescription:
        async def _run() -> FileDescription:
            content_md = cast("str", await _run_blocking(executor, _parse_file_to_markdown, file_path))
            overview = await _summarize_with_llm(llm_client, file_path.stem, content_md)
            return FileDescription(title=file_path.stem, content_md=content_md, overview=overview)

        if limiter is None:
            return await _run()
        async with limiter:
            return await _run()

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
    try:
        return list(await asyncio.gather(*[_parse_one(path, executor) for path in paths]))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)


def parse_files(
    llm_client: object,
    files: list[str] | list[Path] | None = None,
    semaphore: int | asyncio.Semaphore | None = 5,
) -> list[FileDescription]:
    """解析文件内容，以FileDescription格式保存

    当前解析支持：TXT, WORD, EXCEL, PDF

    Args:
        llm_client: 辅助文件内容解析的大模型Client
        files: 文件路径列表
        semaphore: 最大并行解析文件数。可传入整数或已创建的 ``asyncio.Semaphore``；
            传入 ``None`` 时不额外限制并发。
    """
    return _run_async(_parse_files_async(llm_client, files, semaphore))
