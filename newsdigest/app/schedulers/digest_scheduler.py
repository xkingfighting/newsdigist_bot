"""
APScheduler 调度管理
负责定时推送任务的注册、移除、启动恢复。
"""

from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from newsdigest.app.adapters.base import BotPlatform
from newsdigest.app.core.database import get_session_factory
from newsdigest.app.core.logging import get_logger
from newsdigest.app.models.orm import Subscription, User
from newsdigest.app.repositories.push_log_repo import PushLogRepository
from newsdigest.app.repositories.subscription_repo import SubscriptionRepository
from newsdigest.app.repositories.user_repo import UserRepository
from newsdigest.app.services.digest_service import DigestService

logger = get_logger(__name__)


def _job_id(user_id: int, keyword: str) -> str:
    """生成唯一任务 ID。"""
    return f"digest_{user_id}_{keyword}"


class DigestScheduler:
    """
    管理所有定时推送任务。
    每个活跃订阅对应一个 APScheduler CronJob。
    """

    def __init__(
        self,
        platform: BotPlatform,
        digest_service: DigestService,
    ) -> None:
        self._platform = platform
        self._digest_service = digest_service
        self._scheduler = AsyncIOScheduler()

    def start(self) -> None:
        if not self._scheduler.running:
            self._scheduler.start()
            logger.info("APScheduler started")

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            logger.info("APScheduler shut down")

    async def register_job(self, sub: Subscription, user: User) -> None:
        """
        为订阅注册定时任务。
        push_time 格式 "HH:MM"，timezone 来自订阅或用户配置。
        """
        job_id = _job_id(user.id, sub.keyword)

        # 先移除已有同名任务（如恢复订阅时）
        existing = self._scheduler.get_job(job_id)
        if existing:
            self._scheduler.remove_job(job_id)

        hour, minute = sub.push_time.split(":")
        tz = pytz.timezone(sub.timezone or user.timezone or "Asia/Singapore")

        trigger = CronTrigger(hour=int(hour), minute=int(minute), timezone=tz)

        job = self._scheduler.add_job(
            self._execute_push,
            trigger=trigger,
            id=job_id,
            args=[sub.id, user.id],
            replace_existing=True,
            misfire_grace_time=300,  # 5 分钟容错
        )
        logger.info(
            "Scheduled job '%s' at %s tz=%s, next_run=%s",
            job_id, sub.push_time, tz, job.next_run_time,
        )

    def remove_job(self, user_id: int, keyword: str) -> None:
        """移除指定订阅的调度任务。"""
        job_id = _job_id(user_id, keyword)
        existing = self._scheduler.get_job(job_id)
        if existing:
            self._scheduler.remove_job(job_id)
            logger.info("Removed scheduled job '%s'", job_id)

    async def restore_all_jobs(self) -> None:
        """
        系统启动时从数据库恢复所有活跃订阅的调度任务。
        """
        logger.info("Restoring scheduled jobs from database...")
        session_factory = get_session_factory()

        async with session_factory() as session:
            sub_repo = SubscriptionRepository(session)
            user_repo = UserRepository(session)

            active_subs = await sub_repo.get_all_active()
            count = 0
            for sub in active_subs:
                user = await user_repo.get_by_id(sub.user_id)
                if user is None:
                    logger.warning("User %d not found for subscription %d, skipping", sub.user_id, sub.id)
                    continue
                await self.register_job(sub, user)
                count += 1

        logger.info("Restored %d scheduled jobs", count)

    async def _execute_push(self, subscription_id: int, user_id: int) -> None:
        """
        APScheduler 回调：执行定时推送。
        每次执行创建独立的 DB session。
        """
        logger.info("Scheduler firing push: sub=%d user=%d", subscription_id, user_id)

        try:
            session_factory = get_session_factory()

            async with session_factory() as session:
                async with session.begin():
                    sub_repo = SubscriptionRepository(session)
                    user_repo = UserRepository(session)
                    push_log_repo = PushLogRepository(session)

                    sub = await sub_repo.get_by_id(subscription_id)
                    if sub is None or sub.status != "active":
                        logger.info("Subscription %d is no longer active, skipping", subscription_id)
                        return

                    user = await user_repo.get_by_id(user_id)
                    if user is None:
                        logger.warning("User %d not found, skipping push", user_id)
                        return

                    await self._digest_service.execute_scheduled_push(
                        subscription=sub,
                        user=user,
                        platform_adapter=self._platform,
                        push_log_repo=push_log_repo,
                    )

            logger.info("Scheduler push completed: sub=%d user=%d", subscription_id, user_id)
        except Exception as e:
            logger.error("Scheduler push FAILED: sub=%d user=%d error=%s", subscription_id, user_id, e, exc_info=True)
