"""
资讯摘要 Service
协调搜索、去重、摘要、推送的完整流程。
"""

from __future__ import annotations

import json

from newsdigest.app.adapters.base import BotPlatform
from newsdigest.app.core.logging import get_logger
from newsdigest.app.models.orm import Subscription, User
from newsdigest.app.repositories.push_log_repo import PushLogRepository
from newsdigest.app.repositories.user_repo import UserRepository
from newsdigest.app.services.search.base import SearchProvider, deduplicate_items
from newsdigest.app.services.summarizer import SummarizerService
from newsdigest.app.core.config import settings
from newsdigest.app.core.redis import get_redis

logger = get_logger(__name__)


DIGEST_CACHE_TTL = 300  # 同关键词摘要缓存 5 分钟，避免重复调 Ollama


class DigestService:
    """资讯摘要核心业务流程"""

    def __init__(
        self,
        search_provider: SearchProvider,
        summarizer: SummarizerService,
    ) -> None:
        self._search = search_provider
        self._summarizer = summarizer

    async def generate_digest(self, keyword: str) -> str:
        """
        立即生成摘要（用于 /digest 命令）。
        先查 Redis 缓存，命中则直接返回；未命中再走搜索→摘要链路。
        """
        cache_key = f"newsdigest:digest_cache:{keyword}"

        # 尝试读缓存（Redis 不可用时跳过）
        redis_client = None
        try:
            redis_client = get_redis()
            cached = await redis_client.get(cache_key)
            if cached:
                logger.info("Digest cache hit for '%s'", keyword)
                return cached
        except Exception:
            pass

        max_items = settings.digest.max_items

        logger.info("Generating digest for keyword='%s'", keyword)

        items = await self._search.search(keyword, max_results=max_items + 5)
        items = deduplicate_items(items)
        items = items[:max_items]

        logger.info("After dedup: %d items for '%s'", len(items), keyword)

        summary = await self._summarizer.summarize(keyword, items)

        # 只缓存有效摘要（不缓存 fallback/insufficient 文案）
        from newsdigest.app.services.summarizer import FALLBACK_MESSAGE, INSUFFICIENT_MESSAGE
        is_fallback = summary in (
            FALLBACK_MESSAGE.format(keyword=keyword),
            INSUFFICIENT_MESSAGE,
        )
        if redis_client and not is_fallback:
            try:
                await redis_client.set(cache_key, summary, ex=DIGEST_CACHE_TTL)
            except Exception:
                pass

        return summary

    async def execute_scheduled_push(
        self,
        subscription: Subscription,
        user: User,
        platform_adapter: BotPlatform,
        push_log_repo: PushLogRepository,
    ) -> None:
        """
        定时推送完整流程：
        1. Redis 去重检查（防同一分钟重复推送）
        2. 搜索 → 去重 → 摘要
        3. 发送消息
        4. 写 push_log
        """
        # 防重复推送（Redis 不可用时 fail-open，不阻断推送）
        dedup_key = f"newsdigest:push_dedup:{subscription.id}:{_today_key()}"
        try:
            redis = get_redis()
            if await redis.get(dedup_key):
                logger.info("Skipping duplicate push for subscription %d", subscription.id)
                return
        except Exception as e:
            logger.warning("Redis dedup check failed (proceeding anyway): %s", e)

        keyword = subscription.keyword
        logger.info(
            "Executing scheduled push: sub=%d user=%d keyword='%s'",
            subscription.id, user.id, keyword,
        )

        error_msg: str | None = None
        summary: str = ""
        raw_json: str = "[]"

        try:
            max_items = settings.digest.max_items
            items = await self._search.search(keyword, max_results=max_items + 5)
            items = deduplicate_items(items)
            items = items[:max_items]
            raw_json = self._summarizer.items_to_json(items)

            summary = await self._summarizer.summarize(keyword, items)

            # 构建推送消息
            push_text = f"📰 每日资讯 | {keyword}\n\n{summary}"

            # 发送到订阅指定的目标（私聊=user_id, 群聊=group_id）
            chat_id = subscription.chat_id or user.platform_user_id
            chat_type = subscription.chat_type or "private"
            success = await platform_adapter.send_message(
                chat_id=chat_id,
                text=push_text,
                chat_type=chat_type,
            )

            if not success:
                error_msg = "sendMessage failed"

        except Exception as e:
            logger.error("Scheduled push failed for sub %d: %s", subscription.id, e)
            error_msg = str(e)

        # 写推送日志
        status = "success" if error_msg is None else "failed"
        try:
            await push_log_repo.create(
                user_id=user.id,
                subscription_id=subscription.id,
                keyword=keyword,
                raw_sources_json=raw_json,
                summary_text=summary,
                status=status,
                error_message=error_msg,
            )
        except Exception as e:
            logger.error("Failed to write push log: %s", e)

        # 设置 Redis 去重 key，24h 过期
        try:
            await redis.set(dedup_key, "1", ex=86400)
        except Exception as e:
            logger.warning("Failed to set Redis dedup key: %s", e)

        logger.info(
            "Push result: sub=%d status=%s keyword='%s'",
            subscription.id, status, keyword,
        )


def _today_key() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y%m%d")
