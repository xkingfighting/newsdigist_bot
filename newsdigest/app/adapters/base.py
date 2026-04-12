"""
Bot 平台适配器抽象层
定义统一接口，业务层只依赖此抽象，不依赖具体平台实现。
未来扩展 Telegram / WhatsApp / Webhook 只需新增子类。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from newsdigest.app.schemas.types import BotCommand, BotReply, IncomingMessage


class BotPlatform(ABC):
    """所有 Bot 平台适配器的基类"""

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台标识名，如 "talkonly", "telegram" """
        ...

    @abstractmethod
    async def start(self) -> None:
        """启动适配器（切换模式、初始化连接等）"""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """停止适配器，释放资源"""
        ...

    @abstractmethod
    async def get_updates(self, offset: int) -> list[IncomingMessage]:
        """
        拉取新消息列表。
        offset: 上次处理的最后一条 update_id + 1
        返回统一的 IncomingMessage 列表。
        """
        ...

    @abstractmethod
    async def send_message(self, chat_id: int, text: str, chat_type: str = "private") -> bool:
        """
        发送文本消息到指定会话。
        返回是否发送成功。
        """
        ...

    @abstractmethod
    async def send_card(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        """
        发送富卡片消息（ListCard / ActionCard）。
        不支持卡片的平台可 fallback 到纯文本。
        """
        ...

    @abstractmethod
    async def send_typing(self, chat_id: int, chat_type: str = "private") -> None:
        """发送 "正在输入" 状态指示"""
        ...

    def parse_command(self, message: IncomingMessage) -> BotCommand | None:
        """
        从消息文本解析命令。
        以 "/" 开头视为命令，否则返回 None。
        默认实现对所有平台通用，子类可覆盖。
        """
        text = message.text.strip()
        if not text.startswith("/"):
            return None

        parts = text.split(maxsplit=-1)
        cmd_name = parts[0][1:].lower()  # 去掉 "/"

        # 处理 /command@botname 格式
        if "@" in cmd_name:
            cmd_name = cmd_name.split("@")[0]

        return BotCommand(
            name=cmd_name,
            args=parts[1:],
            raw_text=text,
            message=message,
        )
