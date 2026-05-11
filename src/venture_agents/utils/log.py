"""全局日志配置

提供：
- setup_logger: 创建带文件和控制台输出的 logger
- get_logger: 快速获取 logger（简化版）
- get_log_level: 从字符串解析日志级别
"""

import logging
import os
from pathlib import Path
from typing import Final


# 日志目录：Lambda 部署时设 MINING_AGENTS_LOG_DIR=/tmp，本地默认 logs/
_LOG_DIR: Final[str] = os.environ.get("MINING_AGENTS_LOG_DIR", "logs")

# 日志级别映射
LOG_LEVEL_MAP: Final[dict[str, int]] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "WARN": logging.WARNING,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
    "FATAL": logging.CRITICAL,
}

# 日志格式
LOG_FORMATTER: Final[logging.Formatter] = logging.Formatter("[%(levelname)s][%(asctime)s][%(name)s] %(message)s")


def get_log_level(level_str: str) -> int:
    """从字符串解析日志级别

    Args:
        level_str: 日志级别字符串，如 "info", "debug"（大小写不敏感）

    Returns:
        logging 模块的日志级别常量

    Example:
        >>> get_log_level("debug")
        10  # logging.DEBUG
    """
    return LOG_LEVEL_MAP.get(level_str.upper(), logging.INFO)


def setup_logger(
    name: str,
    log_file: str | None = None,
    level: int | str = logging.INFO,
    console: bool = True,
) -> logging.Logger:
    """创建日志记录器

    Args:
        name: logger 名称
        log_file: 日志文件路径（None 则自动使用 logs/<name>.log）
        level: 日志级别（int 或 str）
        console: 是否输出到控制台

    Returns:
        配置好的 logger 实例

    Example:
        >>> logger = get_logger("DDAgent")
        >>> logger = get_logger("MyAgent", "MyAgent.log", logging.DEBUG)
    """
    if isinstance(level, str):
        level = get_log_level(level)

    if log_file is None:
        log_file = f"{name}.log"

    logger = logging.getLogger(name)

    # 清除已有 handler，避免重复
    if logger.handlers:
        logger.handlers.clear()

    logger.setLevel(level)

    # 文件输出
    log_path = Path(log_file)
    # 默认放到 _LOG_DIR 目录（环境变量 MINING_AGENTS_LOG_DIR 控制）
    if str(log_path.parent) in ("", "."):
        log_dir = Path(_LOG_DIR)
    else:
        log_dir = log_path.parent
    log_dir.mkdir(parents=True, exist_ok=True)
    full_log_path = log_dir / log_path.name

    file_handler = logging.FileHandler(full_log_path, encoding="utf-8")
    file_handler.setFormatter(LOG_FORMATTER)
    logger.addHandler(file_handler)

    # 控制台输出
    if console:
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(LOG_FORMATTER)
        logger.addHandler(console_handler)

    # 不向上传播，避免重复输出
    logger.propagate = False

    return logger
