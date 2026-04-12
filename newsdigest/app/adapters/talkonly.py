"""
TalkOnly 平台适配器
基于 TalkOnly Bot Polling API V1 / Open API V1 实现。

API Base URL: https://chat.ichuk.com/Open/Bot/{method}
认证方式: Authorization: Bearer {bot_token}
路由大小写敏感: Open / Bot 首字母大写，方法名 camelCase。
"""

from __future__ import annotations

import asyncio
import json

import httpx

from newsdigest.app.adapters.base import BotPlatform
from newsdigest.app.core.config import settings
from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import BotReply, IncomingMessage

logger = get_logger(__name__)


class TalkOnlyAdapter(BotPlatform):
    """
    TalkOnly Polling 模式适配器。
    使用 getUpdates 长轮询拉取消息，sendMessage 发送回复。
    """

    def __init__(self) -> None:
        self._base_url = settings.talkonly.base_url
        self._token = settings.talkonly.bot_secret
        self._timeout = settings.talkonly.long_poll_timeout
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    @property
    def platform_name(self) -> str:
        return "talkonly"

    async def start(self) -> None:
        """初始化 HTTP 客户端，并切换到 polling 模式。"""
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._timeout + 5.0,  # 比 poll timeout 宽松几秒即可
                write=5.0,
                pool=5.0,
            ),
        )
        # 切换到 polling 模式（调用 deleteWebhook）
        await self._delete_webhook()
        logger.info("TalkOnly adapter started in polling mode")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("TalkOnly adapter stopped")

    async def _delete_webhook(self) -> None:
        """切换到 polling 模式，删除已有 webhook。"""
        try:
            resp = await self._client.post(
                f"{self._base_url}/deleteWebhook",
                headers=self._headers,
            )
            data = resp.json()
            if data.get("ok"):
                logger.info("Switched to polling mode: %s", data.get("result", {}).get("description", ""))
            else:
                logger.warning("deleteWebhook response: %s", data)
        except Exception as e:
            logger.warning("Failed to delete webhook (may already be in polling mode): %s", e)

    async def get_updates(self, offset: int) -> list[IncomingMessage]:
        """
        调用 getUpdates 长轮询获取消息。

        offset 确认机制（Telegram 风格）：
        传入 offset=N 时，服务端将 update_id < N 的所有 update 标记为已确认。
        """
        if not self._client:
            raise RuntimeError("Adapter not started. Call start() first.")

        payload: dict = {
            "offset": offset,
            "limit": 100,
            "timeout": self._timeout,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/getUpdates",
                headers=self._headers,
                json=payload,
            )
            data = resp.json()
        except httpx.ReadTimeout:
            # 长轮询超时是正常的，返回空列表
            return []
        except Exception as e:
            logger.error("getUpdates request failed: %s", e)
            return []

        if not data.get("ok"):
            error_code = data.get("error_code", "")
            if error_code == "CONFLICT":
                logger.error("Cannot use polling: webhook is active. Call deleteWebhook first.")
            elif error_code in ("INVALID_TOKEN", "UNAUTHORIZED", "BOT_DISABLED"):
                logger.error("getUpdates auth error: %s (retrying in 30s)", error_code)
                await asyncio.sleep(30)
            else:
                logger.warning("getUpdates error: %s", data)
                await asyncio.sleep(3)
            return []

        messages: list[IncomingMessage] = []
        for update in data.get("result", []):
            try:
                msg = self._parse_update(update)
                if msg is not None:
                    messages.append(msg)
            except Exception as e:
                logger.error("Failed to parse update %s: %s", update.get("update_id"), e)

        return messages

    def _parse_update(self, update: dict) -> IncomingMessage | None:
        """
        将 TalkOnly Update 对象转为统一 IncomingMessage。

        TalkOnly Update 结构：
        {
          "update_id": 101,
          "bot": {"id": 5, "user_id": 100, "name": "My Bot", "username": "my_bot"},
          "from_user": {"id": 15, "name": "John", ...},
          "chat": {"id": 15, "type": "private"},
          "message": {"id": 500, "type": "text", "text": "Hello"},
          "trigger": {"type": "private"},
          "timestamp": 1711180800
        }
        """
        message_data = update.get("message", {})
        msg_type = message_data.get("type", "")
        text = message_data.get("text", "").strip()

        logger.debug(
            "Raw update: id=%s type=%s text=%s",
            update.get("update_id"), msg_type, text[:60] if text else "(empty)",
        )

        # 接收 text 和 command 类型消息
        if msg_type not in ("text", "command"):
            logger.debug("Skipping update %s: unsupported type '%s'", update.get("update_id"), msg_type)
            return None

        if not text:
            return None

        from_user = update.get("from_user", {})
        chat = update.get("chat", {})

        return IncomingMessage(
            platform="talkonly",
            update_id=update["update_id"],
            user_id=from_user.get("id", 0),
            user_name=from_user.get("name", ""),
            chat_id=chat.get("id", 0),
            chat_type=chat.get("type", "private"),
            text=text,
            timestamp=update.get("timestamp", 0),
        )

    async def send_message(self, chat_id: int, text: str, chat_type: str = "private") -> bool:
        """
        调用 sendMessage 发送文本消息。

        参数:
          chat_id: 私聊时为 user_id，群聊时为 group_id
          text: 消息内容，最大 4096 字符
          chat_type: "private" 或 "group"
        """
        if not self._client:
            raise RuntimeError("Adapter not started.")

        # TalkOnly 限制消息最大 4096 字符
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        payload = {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "text": text,
            "type": 1,  # 纯文本
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/sendMessage",
                headers=self._headers,
                json=payload,
            )
            data = resp.json()

            if data.get("ok"):
                logger.debug("Message sent to chat_id=%s", chat_id)
                return True
            else:
                logger.error("sendMessage failed: %s", data)
                return False
        except Exception as e:
            logger.error("sendMessage request error: %s", e)
            return False

    async def send_card(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        """
        发送富卡片消息。

        TalkOnly 卡片类型：
          type=10 ActionCard: {"text":"...", "buttons":[{"label":"...", "command":"...", "style":"primary"}]}
          type=11 ListCard:   {"text":"...", "items":[{"title":"...", "description":"...", "command":"..."}]}
        """
        if not self._client:
            raise RuntimeError("Adapter not started.")

        card_data: dict = {}

        if reply.card_type == 11:
            # ListCard
            card_data["text"] = reply.card_text or reply.card_title
            card_data["items"] = [
                {k: v for k, v in {
                    "title": item.title,
                    "description": item.description,
                    "command": item.command,
                }.items() if v}
                for item in reply.card_items
            ]
        elif reply.card_type == 10:
            # ActionCard
            card_data["text"] = reply.card_text
            card_data["buttons"] = [
                {k: v for k, v in {
                    "label": btn.label,
                    "command": btn.command,
                    "style": btn.style,
                }.items() if v}
                for btn in reply.card_buttons
            ]

        payload = {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "text": json.dumps(card_data, ensure_ascii=False),
            "type": reply.card_type,
        }

        try:
            resp = await self._client.post(
                f"{self._base_url}/sendMessage",
                headers=self._headers,
                json=payload,
            )
            data = resp.json()
            if data.get("ok"):
                logger.debug("Card (type=%d) sent to chat_id=%s", reply.card_type, chat_id)
                return True
            else:
                logger.error("sendCard failed: %s", data)
                return False
        except Exception as e:
            logger.error("sendCard request error: %s", e)
            return False

    async def send_typing(self, chat_id: int, chat_type: str = "private") -> None:
        """发送 typing 状态指示。"""
        if not self._client:
            return

        try:
            await self._client.post(
                f"{self._base_url}/sendTyping",
                headers=self._headers,
                json={"chat_id": chat_id, "chat_type": chat_type},
            )
        except Exception as e:
            logger.debug("sendTyping failed (non-critical): %s", e)
