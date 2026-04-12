"""
订阅管理 Service
处理订阅的创建、查询、暂停、恢复、删除等业务逻辑。
所有操作均按聊天上下文隔离：私聊看私聊、群聊看本群。
"""

from __future__ import annotations

import re

from newsdigest.app.core.logging import get_logger
from newsdigest.app.models.orm import Subscription, User
from newsdigest.app.repositories.subscription_repo import SubscriptionRepository
from newsdigest.app.repositories.user_repo import UserRepository

logger = get_logger(__name__)

# 时间格式校验：HH:MM
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


class SubscriptionService:

    def __init__(
        self,
        user_repo: UserRepository,
        sub_repo: SubscriptionRepository,
    ) -> None:
        self._user_repo = user_repo
        self._sub_repo = sub_repo

    async def ensure_user(
        self,
        platform: str,
        platform_user_id: int,
        display_name: str = "",
        timezone: str = "Asia/Singapore",
    ) -> User:
        return await self._user_repo.get_or_create(
            platform=platform,
            platform_user_id=platform_user_id,
            display_name=display_name,
            timezone=timezone,
        )

    async def subscribe(
        self,
        user: User,
        keyword: str,
        push_time: str,
        platform: str,
        chat_id: int = 0,
        chat_type: str = "private",
    ) -> tuple[bool, str, Subscription | None]:
        """
        创建订阅。
        chat_id / chat_type 记录推送目标：私聊发给用户，群聊发到群。
        """
        keyword = keyword.strip()
        if not keyword:
            return False, "关键词不能为空。", None

        if not _TIME_RE.match(push_time):
            return False, f"时间格式不正确，请使用 HH:MM（如 09:00）。收到: {push_time}", None

        if chat_id == 0:
            chat_id = user.platform_user_id

        # 同一聊天上下文中不能重复订阅同一关键词
        existing = await self._sub_repo.find_active(
            user.id, keyword, platform, chat_id=chat_id, chat_type=chat_type,
        )
        if existing:
            return False, f"已订阅「{keyword}」（每天 {existing.push_time}），无需重复创建。", None

        sub = await self._sub_repo.create(
            user_id=user.id,
            keyword=keyword,
            push_time=push_time,
            timezone=user.timezone,
            platform=platform,
            chat_id=chat_id,
            chat_type=chat_type,
        )
        where = "本群" if chat_type == "group" else "私聊"
        logger.info(
            "Subscription created: user=%d keyword='%s' time=%s chat=%s:%d",
            user.id, keyword, push_time, chat_type, chat_id,
        )
        return True, f"订阅成功！将在每天 {push_time} 向{where}推送「{keyword}」的资讯摘要。", sub

    async def list_subscriptions(
        self, user: User, chat_id: int, chat_type: str,
    ) -> list[Subscription]:
        """列出当前聊天上下文中的订阅。"""
        return await self._sub_repo.list_by_chat(user.id, chat_id, chat_type)

    async def unsubscribe(
        self, user: User, keyword: str, chat_id: int, chat_type: str,
    ) -> tuple[bool, str]:
        sub = await self._sub_repo.find_by_keyword_in_chat(
            keyword, chat_id, chat_type, user_id=user.id,
        )
        if not sub:
            return False, f"未找到关键词「{keyword}」的订阅。"

        await self._sub_repo.update_status(sub.id, "deleted")
        logger.info("Subscription deleted: user=%d keyword='%s' chat=%s:%d", user.id, keyword, chat_type, chat_id)
        return True, f"已取消「{keyword}」的订阅。"

    async def pause(
        self, user: User, keyword: str, chat_id: int, chat_type: str,
    ) -> tuple[bool, str, Subscription | None]:
        sub = await self._sub_repo.find_by_keyword_in_chat(
            keyword, chat_id, chat_type, user_id=user.id,
        )
        if not sub:
            return False, f"未找到关键词「{keyword}」的订阅。", None
        if sub.status == "paused":
            return False, f"「{keyword}」订阅已经是暂停状态。", None

        await self._sub_repo.update_status(sub.id, "paused")
        logger.info("Subscription paused: user=%d keyword='%s'", user.id, keyword)
        return True, f"已暂停「{keyword}」的推送。", sub

    async def resume(
        self, user: User, keyword: str, chat_id: int, chat_type: str,
    ) -> tuple[bool, str, Subscription | None]:
        sub = await self._sub_repo.find_by_keyword_in_chat(
            keyword, chat_id, chat_type, user_id=user.id,
        )
        if not sub:
            return False, f"未找到关键词「{keyword}」的订阅。", None
        if sub.status == "active":
            return False, f"「{keyword}」订阅已经在运行中。", None

        await self._sub_repo.update_status(sub.id, "active")
        logger.info("Subscription resumed: user=%d keyword='%s'", user.id, keyword)
        sub = await self._sub_repo.get_by_id(sub.id)
        return True, f"已恢复「{keyword}」的推送。", sub
