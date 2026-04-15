"""
跨层共享的数据结构定义
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


# ─── 资讯条目 ───

@dataclass
class NewsItem:
    title: str
    snippet: str
    source: str
    url: str
    published_at: datetime | None = None


# ─── 枚举 ───

class SubscriptionStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DELETED = "deleted"


class PushStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"


# ─── 平台消息 ───

@dataclass
class IncomingMessage:
    platform: str
    update_id: int
    user_id: int
    user_name: str
    chat_id: int
    chat_type: str
    text: str
    timestamp: int = 0
    # callback query 字段（按钮点击时填充）
    callback_query_id: str = ""
    callback_data: str = ""


@dataclass
class BotCommand:
    name: str
    args: list[str] = field(default_factory=list)
    raw_text: str = ""
    message: IncomingMessage | None = None


# ─── Rich Text Entity ───

@dataclass
class TextEntity:
    """富文本实体（粗体、链接等），offset/length 按 UTF-16 计算。"""
    type: str              # bold / italic / code / text_link / underline
    offset: int
    length: int
    url: str = ""          # type=text_link 时必填


# ─── Inline Keyboard Button ───

@dataclass
class InlineButton:
    """内联键盘按钮，三种类型互斥。"""
    text: str
    url: str = ""              # 打开链接
    callback_data: str = ""    # 回调给 Bot
    copy_text: str = ""        # 复制到剪贴板


# ─── Bot 回复 ───

@dataclass
class CardItem:
    title: str
    description: str = ""
    command: str = ""


@dataclass
class CardButton:
    label: str
    command: str
    style: str = ""


@dataclass
class BotReply:
    """
    命令处理器的统一返回结构。
    支持：纯文本 / 旧版卡片 / Rich Text + Inline Keyboard
    """
    text: str = ""

    # 旧版卡片（兼容保留）
    card_type: int = 0
    card_title: str = ""
    card_text: str = ""
    card_items: list[CardItem] = field(default_factory=list)
    card_buttons: list[CardButton] = field(default_factory=list)

    # Rich Text（新特性）
    entities: list[TextEntity] = field(default_factory=list)

    # Inline Keyboard（新特性）
    inline_keyboard: list[list[InlineButton]] = field(default_factory=list)

    @property
    def is_card(self) -> bool:
        return self.card_type in (10, 11)

    @property
    def is_rich(self) -> bool:
        """有 entities 或 inline_keyboard 时走 rich text 通道。"""
        return bool(self.entities or self.inline_keyboard)
