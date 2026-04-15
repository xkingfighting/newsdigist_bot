"""
订阅 Repository
"""

from __future__ import annotations

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from newsdigest.app.models.orm import Subscription


class SubscriptionRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: int,
        keyword: str,
        push_time: str,
        timezone: str,
        platform: str,
        chat_id: int = 0,
        chat_type: str = "private",
    ) -> Subscription:
        sub = Subscription(
            user_id=user_id,
            keyword=keyword,
            push_time=push_time,
            timezone=timezone,
            chat_id=chat_id,
            chat_type=chat_type,
            platform=platform,
            status="active",
        )
        self._session.add(sub)
        await self._session.flush()
        return sub

    async def find_active(
        self, user_id: int, keyword: str, platform: str,
        chat_id: int = 0, chat_type: str = "private",
    ) -> Subscription | None:
        """查找同一聊天上下文中同关键词的活跃订阅。"""
        stmt = select(Subscription).where(
            and_(
                Subscription.user_id == user_id,
                Subscription.keyword == keyword,
                Subscription.platform == platform,
                Subscription.chat_id == chat_id,
                Subscription.chat_type == chat_type,
                Subscription.status == "active",
            )
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_chat(
        self, user_id: int, chat_id: int, chat_type: str,
    ) -> list[Subscription]:
        """列出当前聊天上下文中的订阅。
        私聊：该用户的私聊订阅
        群聊：该群的所有订阅（不限创建者）
        """
        if chat_type == "group":
            # 群内看群的全部订阅
            conditions = [
                Subscription.chat_id == chat_id,
                Subscription.chat_type == "group",
                Subscription.status != "deleted",
            ]
        else:
            # 私聊只看自己的私聊订阅
            conditions = [
                Subscription.user_id == user_id,
                Subscription.chat_type == "private",
                Subscription.status != "deleted",
            ]

        stmt = (
            select(Subscription)
            .where(and_(*conditions))
            .order_by(Subscription.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def find_by_keyword_in_chat(
        self, keyword: str, chat_id: int, chat_type: str, user_id: int = 0,
    ) -> Subscription | None:
        """在当前聊天上下文中查找非删除状态的订阅。"""
        if chat_type == "group":
            conditions = [
                Subscription.keyword == keyword,
                Subscription.chat_id == chat_id,
                Subscription.chat_type == "group",
                Subscription.status != "deleted",
            ]
        else:
            conditions = [
                Subscription.user_id == user_id,
                Subscription.keyword == keyword,
                Subscription.chat_type == "private",
                Subscription.status != "deleted",
            ]

        stmt = select(Subscription).where(and_(*conditions))
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_push_time(self, subscription_id: int, push_time: str) -> None:
        sub = await self._session.get(Subscription, subscription_id)
        if sub is not None:
            sub.push_time = push_time
            await self._session.flush()

    async def update_status(self, subscription_id: int, status: str) -> None:
        sub = await self._session.get(Subscription, subscription_id)
        if sub is not None:
            if status == "deleted":
                # 物理删除，避免唯一约束冲突
                await self._session.delete(sub)
            else:
                sub.status = status
            await self._session.flush()

    async def get_all_active(self) -> list[Subscription]:
        """获取所有活跃订阅，用于启动时恢复调度。"""
        stmt = select(Subscription).where(Subscription.status == "active")
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_by_id(self, subscription_id: int) -> Subscription | None:
        return await self._session.get(Subscription, subscription_id)
