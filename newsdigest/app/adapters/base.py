"""
Bot 平台适配器抽象层
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from newsdigest.app.schemas.types import BotCommand, BotReply, IncomingMessage


class BotPlatform(ABC):

    @property
    @abstractmethod
    def platform_name(self) -> str:
        ...

    @abstractmethod
    async def start(self) -> None:
        ...

    @abstractmethod
    async def stop(self) -> None:
        ...

    @abstractmethod
    async def get_updates(self, offset: int) -> list[IncomingMessage]:
        ...

    @abstractmethod
    async def send_message(self, chat_id: int, text: str, chat_type: str = "private") -> bool:
        ...

    @abstractmethod
    async def send_rich_message(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        """发送富文本消息（entities + inline_keyboard）。"""
        ...

    @abstractmethod
    async def send_card(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        ...

    @abstractmethod
    async def send_typing(self, chat_id: int, chat_type: str = "private") -> None:
        ...

    @abstractmethod
    async def answer_callback(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        """应答 callback query（按钮点击回调）。"""
        ...

    def parse_command(self, message: IncomingMessage) -> BotCommand | None:
        text = message.text.strip()
        if not text.startswith("/"):
            return None

        parts = text.split(maxsplit=-1)
        cmd_name = parts[0][1:].lower()

        if "@" in cmd_name:
            cmd_name = cmd_name.split("@")[0]

        return BotCommand(
            name=cmd_name,
            args=parts[1:],
            raw_text=text,
            message=message,
        )
