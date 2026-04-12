"""
Bot 更新偏移量 Repository
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from newsdigest.app.models.orm import BotUpdateOffset


class OffsetRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_offset(self, platform: str) -> int:
        stmt = select(BotUpdateOffset).where(BotUpdateOffset.platform == platform)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()
        return record.last_update_id if record else 0

    async def save_offset(self, platform: str, offset: int) -> None:
        stmt = select(BotUpdateOffset).where(BotUpdateOffset.platform == platform)
        result = await self._session.execute(stmt)
        record = result.scalar_one_or_none()

        if record is None:
            record = BotUpdateOffset(platform=platform, last_update_id=offset)
            self._session.add(record)
        else:
            record.last_update_id = offset

        await self._session.flush()
