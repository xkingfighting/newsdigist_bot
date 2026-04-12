"""
异步 MySQL 数据库连接管理
基于 SQLAlchemy 2.0 async engine。
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from newsdigest.app.core.config import settings

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.mysql.async_url,
            echo=False,
            pool_size=10,
            max_overflow=30,
            pool_recycle=300,      # 5 分钟回收，避免长时间空闲后死连接
            pool_pre_ping=True,
            pool_timeout=5,        # 等连接最多 5 秒
        )
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            bind=get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


async def close_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
