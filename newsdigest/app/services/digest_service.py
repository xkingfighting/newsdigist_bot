"""
资讯摘要 Service（v4 — 产品级调优）
完整流程：搜索 → 过滤 → 评分 → 去重 → 摘要 → 推送
每一步都有详细日志，方便调优。
"""

from __future__ import annotations

import json

from newsdigest.app.adapters.base import BotPlatform
from newsdigest.app.core.logging import get_logger
from newsdigest.app.core.config import settings
from newsdigest.app.core.redis import get_redis
from newsdigest.app.models.orm import Subscription, User
from newsdigest.app.repositories.push_log_repo import PushLogRepository
from newsdigest.app.services.search.base import SearchProvider, deduplicate_items
from newsdigest.app.services.news_filter import NewsFilterService
from newsdigest.app.services.news_scorer import NewsScorerService, SCORE_THRESHOLD
from newsdigest.app.services.news_topic import select_mainline, is_broad_keyword
from newsdigest.app.services.summarizer import SummarizerService, FALLBACK_MESSAGE, INSUFFICIENT_MESSAGE
from newsdigest.app.schemas.types import NewsItem

logger = get_logger(__name__)

DIGEST_CACHE_TTL = 300


class DigestService:
    """资讯摘要核心业务流程"""

    def __init__(
        self,
        search_provider: SearchProvider,
        summarizer: SummarizerService,
    ) -> None:
        self._search = search_provider
        self._summarizer = summarizer
        self._filter = NewsFilterService()
        self._scorer = NewsScorerService()

    async def generate_digest(self, keyword: str, skip_cache: bool = False) -> str:
        """
        完整 digest 流程：搜索 → 过滤 → 评分 → 摘要。
        skip_cache=True 时跳过读缓存（用于刷新按钮）。
        """
        cache_key = f"newsdigest:digest_cache:{keyword}"

        # Redis 缓存
        redis_client = None
        try:
            redis_client = get_redis()
            if not skip_cache:
                cached = await redis_client.get(cache_key)
                if cached:
                    logger.info("[%s] Cache hit", keyword)
                    return cached
            else:
                logger.info("[%s] Cache skipped (force refresh)", keyword)
        except Exception:
            pass

        # ── Step 1: 搜索 ──
        raw_items = await self._search.search(keyword, max_results=settings.digest.max_items + 5)
        raw_items = deduplicate_items(raw_items)  # URL/标题基础去重
        logger.info("[%s] Step1 搜索: %d 条原始结果", keyword, len(raw_items))

        if not raw_items:
            return FALLBACK_MESSAGE.format(keyword=keyword)

        # ── Step 2: 质量过滤 ──
        filtered = self._filter.filter(raw_items, keyword)
        logger.info("[%s] Step2 过滤: %d → %d 条", keyword, len(raw_items), len(filtered))

        if len(filtered) < 2:
            logger.info("[%s] 过滤后不足 2 条，返回 insufficient", keyword)
            return INSUFFICIENT_MESSAGE.format(keyword=keyword)

        # ── Step 3: 评分排序 ──
        scored = self._scorer.score_and_rank(filtered, keyword, threshold=SCORE_THRESHOLD)
        logger.info("[%s] Step3 评分: %d → %d 条 (threshold=%d)", keyword, len(filtered), len(scored), SCORE_THRESHOLD)

        if len(scored) < 2:
            logger.info("[%s] 评分后不足 2 条，返回 insufficient", keyword)
            return INSUFFICIENT_MESSAGE.format(keyword=keyword)

        # ── Step 4: 主��聚合（严格模式：3+1） ──
        main_topic, top_items = select_mainline(scored, max_main=3, max_secondary=1)
        logger.info("[%s] Step4 主线聚合: topic='%s', %d 条进入模型", keyword, main_topic, len(top_items))

        if len(top_items) < 2:
            return INSUFFICIENT_MESSAGE.format(keyword=keyword)

        for i, item in enumerate(top_items, 1):
            logger.info("  [%d] [%s] %s", i, item.source or "?", item.title[:50])

        # ── Step 5: 摘要 ──
        summary = await self._summarizer.summarize(keyword, top_items)

        # 宽关键词提示
        if is_broad_keyword(keyword):
            summary += "\n\n(提示：该关键词范围较广，细化为更具体的主题后摘要会更精准)"
            logger.info("[%s] Broad keyword hint appended", keyword)

        # 缓存有效摘要
        is_fallback = summary in (
            FALLBACK_MESSAGE.format(keyword=keyword),
            INSUFFICIENT_MESSAGE.format(keyword=keyword),
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
        """定时推送流程：复用 generate_digest。"""
        dedup_key = f"newsdigest:push_dedup:{subscription.id}:{_today_key()}"
        try:
            redis = get_redis()
            if await redis.get(dedup_key):
                logger.info("Skipping duplicate push for subscription %d", subscription.id)
                return
        except Exception as e:
            logger.warning("Redis dedup check failed (proceeding anyway): %s", e)

        keyword = subscription.keyword
        logger.info("Executing scheduled push: sub=%d user=%d keyword='%s'", subscription.id, user.id, keyword)

        error_msg: str | None = None
        summary: str = ""
        raw_json: str = "[]"

        try:
            # 复用完整的 digest 流程
            summary = await self.generate_digest(keyword)

            push_text = f"每日资讯 | {keyword}\n\n{summary}"

            chat_id = subscription.chat_id or user.platform_user_id
            chat_type = subscription.chat_type or "private"
            success = await platform_adapter.send_message(
                chat_id=chat_id, text=push_text, chat_type=chat_type,
            )

            if not success:
                error_msg = "sendMessage failed"

        except Exception as e:
            logger.error("Scheduled push failed for sub %d: %s", subscription.id, e)
            error_msg = str(e)

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

        try:
            await redis.set(dedup_key, "1", ex=86400)
        except Exception as e:
            logger.warning("Failed to set Redis dedup key: %s", e)

        logger.info("Push result: sub=%d status=%s keyword='%s'", subscription.id, status, keyword)


def _today_key() -> str:
    from datetime import datetime
    return datetime.utcnow().strftime("%Y%m%d")
