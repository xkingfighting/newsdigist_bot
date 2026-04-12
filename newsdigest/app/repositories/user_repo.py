"""
用户 Repository
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsdigest.app.models.orm import User


class UserRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_or_create(
        self,
        platform: str,
        platform_user_id: int,
        display_name: str = "",
        timezone: str = "Asia/Singapore",
    ) -> User:
        """获取或创建用户，返回 User 实例。"""
        stmt = select(User).where(
            User.platform == platform,
            User.platform_user_id == platform_user_id,
        )
        result = await self._session.execute(stmt)
        user = result.scalar_one_or_none()

        if user is not None:
            # 更新 display_name（用户可能改名）
            if display_name and user.display_name != display_name:
                user.display_name = display_name
                await self._session.flush()
            return user

        user = User(
            platform=platform,
            platform_user_id=platform_user_id,
            display_name=display_name,
            timezone=timezone,
        )
        self._session.add(user)
        await self._session.flush()
        return user

    async def get_by_id(self, user_id: int) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_platform(self, platform: str, platform_user_id: int) -> User | None:
        stmt = select(User).where(
            User.platform == platform,
            User.platform_user_id == platform_user_id,
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()
