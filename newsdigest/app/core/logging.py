"""
统一日志模块
控制台 + 文件双输出，按日期轮转。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import TimedRotatingFileHandler

from newsdigest.app.core.config import settings

_INITIALIZED = False


def setup_logging() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    _INITIALIZED = True

    log_dir = settings.log.abs_dir
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.log.level.upper(), logging.INFO)

    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台 handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(log_level)
    console_handler.setFormatter(fmt)

    # 文件 handler：按天轮转，保留 30 天
    file_handler = TimedRotatingFileHandler(
        filename=log_dir / "newsdigest.log",
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(log_level)
    file_handler.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(log_level)
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    # 降低第三方库日志噪音（保留 apscheduler 以便排查调度问题）
    for noisy in ("httpx", "httpcore", "aiomysql"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
