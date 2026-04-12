"""
SQLAlchemy 2.0 ORM 模型
所有业务表定义。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="talkonly")
    platform_user_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    username: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Singapore")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("platform", "platform_user_id", name="uq_platform_user"),
        Index("idx_platform_user_id", "platform", "platform_user_id"),
    )


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    push_time: Mapped[str] = mapped_column(String(8), nullable=False, comment="HH:MM")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="Asia/Singapore")
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0, comment="推送目标：私聊=user_id, 群聊=group_id")
    chat_type: Mapped[str] = mapped_column(String(16), nullable=False, default="private", comment="private|group")
    status: Mapped[str] = mapped_column(
        Enum("active", "paused", "deleted", name="subscription_status"),
        nullable=False,
        default="active",
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False, default="talkonly")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("idx_user_status", "user_id", "status"),
        Index("idx_user_keyword_chat", "user_id", "keyword", "platform", "chat_id", "chat_type"),
    )


class PushLog(Base):
    __tablename__ = "push_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    subscription_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    keyword: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_sources_json: Mapped[str] = mapped_column(Text, nullable=True)
    summary_text: Mapped[str] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        Enum("success", "failed", name="push_status"),
        nullable=False,
        default="success",
    )
    error_message: Mapped[str] = mapped_column(Text, nullable=True)
    pushed_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (
        Index("idx_push_user_time", "user_id", "pushed_at"),
    )


class BotUpdateOffset(Base):
    __tablename__ = "bot_update_offsets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    last_update_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
