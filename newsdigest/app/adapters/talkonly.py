"""
TalkOnly 平台适配器
支持：Polling / sendMessage / Rich Text (entities) / Inline Keyboard / Callback Query
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
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(
                connect=5.0,
                read=self._timeout + 5.0,
                write=5.0,
                pool=5.0,
            ),
        )
        await self._delete_webhook()
        logger.info("TalkOnly adapter started in polling mode")

    async def stop(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        logger.info("TalkOnly adapter stopped")

    async def _delete_webhook(self) -> None:
        try:
            resp = await self._client.post(f"{self._base_url}/deleteWebhook", headers=self._headers)
            data = resp.json()
            if data.get("ok"):
                logger.info("Switched to polling mode: %s", data.get("result", {}).get("description", ""))
        except Exception as e:
            logger.warning("deleteWebhook failed: %s", e)

    # ─── Polling ───

    async def get_updates(self, offset: int) -> list[IncomingMessage]:
        if not self._client:
            raise RuntimeError("Adapter not started.")

        payload = {"offset": offset, "limit": 100, "timeout": self._timeout}

        try:
            resp = await self._client.post(
                f"{self._base_url}/getUpdates", headers=self._headers, json=payload,
            )
            data = resp.json()
        except httpx.ReadTimeout:
            return []
        except Exception as e:
            logger.error("getUpdates failed: %s", e)
            return []

        if not data.get("ok"):
            error_code = data.get("error_code", "")
            if error_code in ("INVALID_TOKEN", "UNAUTHORIZED", "BOT_DISABLED"):
                logger.error("Auth error: %s (retry in 30s)", error_code)
                await asyncio.sleep(30)
            elif error_code == "CONFLICT":
                logger.error("Webhook active, cannot use polling")
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
        解析 update，支持：
        1. 普通消息 (message.type = text/command)
        2. Callback Query (callback_query 字段)
        """
        # ── Callback Query ──
        cb = update.get("callback_query")
        if cb:
            cb_msg = cb.get("message", {})
            cb_chat = cb_msg.get("chat", {})
            cb_from = cb.get("from", {})
            logger.debug(
                "Raw callback: id=%s from=%s chat=%s data=%s",
                cb.get("id"), cb_from, cb_chat, cb.get("data", "")[:50],
            )
            return IncomingMessage(
                platform="talkonly",
                update_id=update["update_id"],
                user_id=cb_from.get("id", 0),
                user_name=cb_from.get("name", ""),
                chat_id=cb_chat.get("id", 0),
                chat_type=cb_chat.get("type", "private"),
                text="",  # callback query 没有 text
                timestamp=update.get("timestamp", 0),
                callback_query_id=cb.get("id", ""),
                callback_data=cb.get("data", ""),
            )

        # ── 普通消息 ──
        message_data = update.get("message", {})
        msg_type = message_data.get("type", "")
        text = message_data.get("text", "").strip()

        logger.debug("Raw update: id=%s type=%s chat=%s text=%s",
                      update.get("update_id"), msg_type,
                      update.get("chat", {}),
                      text[:50] if text else "(empty)")

        if msg_type not in ("text", "command"):
            logger.debug("Skipping update %s: type '%s'", update.get("update_id"), msg_type)
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

    # ─── Send Message (纯文本) ───

    async def send_message(self, chat_id: int, text: str, chat_type: str = "private") -> bool:
        if not self._client:
            raise RuntimeError("Adapter not started.")

        if len(text) > 4096:
            text = text[:4090] + "\n..."

        payload = {"chat_id": chat_id, "chat_type": chat_type, "text": text, "type": 1}
        return await self._post_send(payload)

    # ─── Send Rich Message (entities + inline_keyboard) ───

    async def send_rich_message(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        """
        发送富文本消息。
        - entities: 文本格式化（粗体/斜体/链接等）
        - reply_markup: inline_keyboard（按钮行列）
        """
        if not self._client:
            raise RuntimeError("Adapter not started.")

        text = reply.text
        if len(text) > 4096:
            text = text[:4090] + "\n..."

        payload: dict = {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "text": text,
        }

        # entities
        if reply.entities:
            payload["entities"] = json.dumps([
                {k: v for k, v in {
                    "type": e.type,
                    "offset": e.offset,
                    "length": e.length,
                    "url": e.url or None,
                }.items() if v is not None}
                for e in reply.entities
            ], ensure_ascii=False)

        # inline_keyboard
        if reply.inline_keyboard:
            keyboard_rows = []
            for row in reply.inline_keyboard:
                btn_row = []
                for btn in row:
                    btn_dict: dict = {"text": btn.text}
                    if btn.url:
                        btn_dict["url"] = btn.url
                    elif btn.callback_data:
                        btn_dict["callback_data"] = btn.callback_data
                    elif btn.copy_text:
                        btn_dict["copy_text"] = btn.copy_text
                    btn_row.append(btn_dict)
                keyboard_rows.append(btn_row)
            payload["reply_markup"] = json.dumps(
                {"inline_keyboard": keyboard_rows}, ensure_ascii=False,
            )

        return await self._post_send(payload)

    # ─── Send Card (旧版兼容) ───

    async def send_card(self, chat_id: int, reply: BotReply, chat_type: str = "private") -> bool:
        if not self._client:
            raise RuntimeError("Adapter not started.")

        card_data: dict = {}
        if reply.card_type == 11:
            card_data["text"] = reply.card_text or reply.card_title
            card_data["items"] = [
                {k: v for k, v in {"title": it.title, "description": it.description, "command": it.command}.items() if v}
                for it in reply.card_items
            ]
        elif reply.card_type == 10:
            card_data["text"] = reply.card_text
            card_data["buttons"] = [
                {k: v for k, v in {"label": b.label, "command": b.command, "style": b.style}.items() if v}
                for b in reply.card_buttons
            ]

        payload = {
            "chat_id": chat_id,
            "chat_type": chat_type,
            "text": json.dumps(card_data, ensure_ascii=False),
            "type": reply.card_type,
        }
        return await self._post_send(payload)

    # ─── Answer Callback Query ───

    async def answer_callback(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> None:
        if not self._client or not callback_query_id:
            return
        payload: dict = {"callback_query_id": callback_query_id}
        if text:
            payload["text"] = text
        if show_alert:
            payload["show_alert"] = True

        try:
            resp = await self._client.post(
                f"{self._base_url}/answerCallbackQuery", headers=self._headers, json=payload,
            )
            data = resp.json()
            if not data.get("ok"):
                logger.warning("answerCallbackQuery failed: %s", data)
        except Exception as e:
            logger.debug("answerCallbackQuery error: %s", e)

    # ─── Typing ───

    async def send_typing(self, chat_id: int, chat_type: str = "private") -> None:
        if not self._client:
            return
        try:
            await self._client.post(
                f"{self._base_url}/sendTyping",
                headers=self._headers,
                json={"chat_id": chat_id, "chat_type": chat_type},
            )
        except Exception as e:
            logger.debug("sendTyping failed: %s", e)

    # ─── 内部工具 ───

    async def _post_send(self, payload: dict) -> bool:
        try:
            resp = await self._client.post(
                f"{self._base_url}/sendMessage", headers=self._headers, json=payload,
            )
            data = resp.json()
            if data.get("ok"):
                return True
            logger.error("sendMessage failed: %s", data)
            return False
        except Exception as e:
            logger.error("sendMessage error: %s", e)
            return False
