"""
推送日志 Repository
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from newsdigest.app.models.orm import PushLog


class PushLogRepository:

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        user_id: int,
        subscription_id: int,
        keyword: str,
        raw_sources_json: str | None,
        summary_text: str | None,
        status: str,
        error_message: str | None = None,
    ) -> PushLog:
        log = PushLog(
            user_id=user_id,
            subscription_id=subscription_id,
            keyword=keyword,
            raw_sources_json=raw_sources_json,
            summary_text=summary_text,
            status=status,
            error_message=error_message,
            pushed_at=datetime.utcnow(),
        )
        self._session.add(log)
        await self._session.flush()
        return log
