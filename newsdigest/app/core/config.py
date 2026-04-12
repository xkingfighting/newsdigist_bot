"""
应用配置模块
从 .env 文件加载所有配置项，禁止硬编码敏感信息。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录：newsdigest/ 的上一层（即 talkonly-bot/）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# 加载 .env 文件
load_dotenv(PROJECT_ROOT / ".env")


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


def _env_int(key: str, default: int = 0) -> int:
    return int(os.getenv(key, str(default)))


def _env_bool(key: str, default: bool = False) -> bool:
    return os.getenv(key, str(default)).lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class AppConfig:
    name: str = field(default_factory=lambda: _env("APP_NAME", "NewsDigest"))
    env: str = field(default_factory=lambda: _env("APP_ENV", "development"))
    debug: bool = field(default_factory=lambda: _env_bool("APP_DEBUG", True))
    timezone: str = field(default_factory=lambda: _env("APP_TIMEZONE", "Asia/Singapore"))


@dataclass(frozen=True)
class TalkOnlyConfig:
    bot_name: str = field(default_factory=lambda: _env("TALKONLY_BOT_NAME", "NewsDigest"))
    bot_secret: str = field(default_factory=lambda: _env("TALKONLY_BOT_SECRET"))
    base_url: str = "https://chat.ichuk.com/Open/Bot"
    poll_interval: int = field(default_factory=lambda: _env_int("TALKONLY_POLL_INTERVAL", 3))
    long_poll_timeout: int = field(default_factory=lambda: _env_int("TALKONLY_LONG_POLL_TIMEOUT", 20))


@dataclass(frozen=True)
class MySQLConfig:
    host: str = field(default_factory=lambda: _env("MYSQL_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("MYSQL_PORT", 3306))
    database: str = field(default_factory=lambda: _env("MYSQL_DATABASE", "newsdigest"))
    username: str = field(default_factory=lambda: _env("MYSQL_USERNAME", "dev"))
    password: str = field(default_factory=lambda: _env("MYSQL_PASSWORD"))

    @property
    def async_url(self) -> str:
        return (
            f"mysql+aiomysql://{self.username}:{self.password}"
            f"@{self.host}:{self.port}/{self.database}?charset=utf8mb4"
        )


@dataclass(frozen=True)
class RedisConfig:
    host: str = field(default_factory=lambda: _env("REDIS_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _env_int("REDIS_PORT", 6379))
    password: str = field(default_factory=lambda: _env("REDIS_PASSWORD"))
    db: int = field(default_factory=lambda: _env_int("REDIS_DB", 0))


@dataclass(frozen=True)
class OllamaConfig:
    base_url: str = field(default_factory=lambda: _env("OLLAMA_BASE_URL", "http://127.0.0.1:11434/api"))
    model: str = field(default_factory=lambda: _env("OLLAMA_MODEL", "qwen2.5:7b"))
    timeout: int = field(default_factory=lambda: _env_int("OLLAMA_TIMEOUT", 180))


@dataclass(frozen=True)
class DigestConfig:
    default_timezone: str = field(default_factory=lambda: _env("DEFAULT_USER_TIMEZONE", "Asia/Singapore"))
    max_items: int = field(default_factory=lambda: _env_int("DEFAULT_DIGEST_MAX_ITEMS", 8))
    min_summary_length: int = field(default_factory=lambda: _env_int("DEFAULT_DIGEST_MIN_SUMMARY_LENGTH", 120))
    max_summary_length: int = field(default_factory=lambda: _env_int("DEFAULT_DIGEST_MAX_SUMMARY_LENGTH", 180))
    search_provider: str = field(default_factory=lambda: _env("SEARCH_PROVIDER", "google_news"))


@dataclass(frozen=True)
class LogConfig:
    level: str = field(default_factory=lambda: _env("LOG_LEVEL", "INFO"))
    dir: str = field(default_factory=lambda: _env("LOG_DIR", "storage/logs"))

    @property
    def abs_dir(self) -> Path:
        p = Path(self.dir)
        if p.is_absolute():
            return p
        return PROJECT_ROOT / "newsdigest" / p


@dataclass(frozen=True)
class Settings:
    app: AppConfig = field(default_factory=AppConfig)
    talkonly: TalkOnlyConfig = field(default_factory=TalkOnlyConfig)
    mysql: MySQLConfig = field(default_factory=MySQLConfig)
    redis: RedisConfig = field(default_factory=RedisConfig)
    ollama: OllamaConfig = field(default_factory=OllamaConfig)
    digest: DigestConfig = field(default_factory=DigestConfig)
    log: LogConfig = field(default_factory=LogConfig)


# 全局单例
settings = Settings()
