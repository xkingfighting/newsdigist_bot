"""
跨层共享的数据结构定义
用 dataclass 而非 ORM model，避免层间耦合。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ─── 资讯条目 ───

@dataclass
class NewsItem:
    """搜索 Provider 返回的标准资讯条目"""
    title: str
    snippet: str
    source: str
    url: str
    published_at: datetime | None = None


# ─── 订阅状态 ───

class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"


# ─── 推送状态 ───

class PushStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


# ─── 平台消息（适配器层对业务层暴露的统一结构）───

@dataclass
class IncomingMessage:
    """从平台收到的用户消息"""
    platform: str
    update_id: int
    user_id: int
    user_name: str
    chat_id: int
    chat_type: str  # "private" | "group"
    text: str
    timestamp: int = 0


@dataclass
class BotCommand:
    """解析后的命令"""
    name: str          # 如 "subscribe", "list", "digest"
    args: list[str] = field(default_factory=list)
    raw_text: str = ""
    message: IncomingMessage | None = None


# ─── Bot 回复（支持纯文本和富卡片）───

@dataclass
class CardItem:
    """ListCard 中的列表项"""
    title: str
    description: str = ""
    command: str = ""


@dataclass
class CardButton:
    """ActionCard 中的按钮"""
    label: str
    command: str
    style: str = ""  # "primary" | ""


@dataclass
class BotReply:
    """
    命令处理器的统一返回结构。
    text 非空时发纯文本；card_type 非空时发富卡片。
    """
    text: str = ""
    card_type: int = 0       # 0=纯文本, 10=ActionCard, 11=ListCard
    card_title: str = ""
    card_text: str = ""
    card_items: list[CardItem] = field(default_factory=list)
    card_buttons: list[CardButton] = field(default_factory=list)

    @property
    def is_card(self) -> bool:
        return self.card_type in (10, 11)
