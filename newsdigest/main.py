"""
NewsDigest Bot 主入口
消息并发处理架构：polling 主循环只收消息推 offset，
每条消息独立 task 处理，互不阻塞。
offset 内存优先、异步持久化，不阻塞主循环。
"""

from __future__ import annotations

import asyncio
import signal
import sys
import time

from newsdigest.app.core.config import settings
from newsdigest.app.core.logging import setup_logging, get_logger
from newsdigest.app.core.database import get_session_factory, close_engine
from newsdigest.app.core.redis import close_redis
from newsdigest.app.adapters.talkonly import TalkOnlyAdapter
from newsdigest.app.controllers.command_handler import CommandHandler
from newsdigest.app.repositories.offset_repo import OffsetRepository
from newsdigest.app.schedulers.digest_scheduler import DigestScheduler
from newsdigest.app.services.digest_service import DigestService
from newsdigest.app.services.summarizer import SummarizerService
from newsdigest.app.schemas.types import IncomingMessage, BotReply

from newsdigest.app.services.search.fake_provider import FakeSearchProvider
from newsdigest.app.services.search.google_news import GoogleNewsProvider
from newsdigest.app.services.search.bing_news import BingNewsProvider

setup_logging()
logger = get_logger(__name__)

MAX_CONCURRENT_TASKS = 50


class NewsDigestBot:

    def __init__(self) -> None:
        self._platform = TalkOnlyAdapter()

        # 搜索 Provider 由配置决定，不再绑定 debug 模式
        provider_name = settings.digest.search_provider
        _providers = {
            "google_news": GoogleNewsProvider,
            "bing_news": BingNewsProvider,
            "fake": FakeSearchProvider,
        }
        provider_cls = _providers.get(provider_name)
        if provider_cls is None:
            logger.warning("Unknown SEARCH_PROVIDER '%s', falling back to google_news", provider_name)
            provider_cls = GoogleNewsProvider
        self._search_provider = provider_cls()
        logger.info("Using SearchProvider: %s", self._search_provider.provider_name)

        self._summarizer = SummarizerService()
        self._digest_service = DigestService(self._search_provider, self._summarizer)
        self._scheduler = DigestScheduler(self._platform, self._digest_service)

        self._command_handler = CommandHandler(
            platform=self._platform,
            digest_service=self._digest_service,
            scheduler_register_fn=self._scheduler.register_job,
            scheduler_remove_fn=self._scheduler.remove_job,
        )

        self._running = False
        self._global_sem = asyncio.Semaphore(MAX_CONCURRENT_TASKS)
        self._active_tasks: set[asyncio.Task] = set()

        # offset 状态：内存保存，异步刷盘
        self._offset: int = 0
        self._offset_dirty: bool = False

    async def start(self) -> None:
        logger.info("Starting %s (env=%s)", settings.app.name, settings.app.env)

        # 预热 DB 连接池（避免空闲后首次请求慢）
        await self._warmup_db()

        await self._platform.start()
        self._scheduler.start()
        await self._scheduler.restore_all_jobs()

        self._running = True

        # 并行启动 polling 和 offset 刷盘
        await asyncio.gather(
            self._polling_loop(),
            self._offset_flush_loop(),
        )

    async def stop(self) -> None:
        logger.info("Shutting down...")
        self._running = False

        if self._active_tasks:
            logger.info("Waiting for %d active tasks...", len(self._active_tasks))
            _, pending = await asyncio.wait(self._active_tasks, timeout=10)
            for t in pending:
                t.cancel()

        # 最后刷一次 offset
        await self._flush_offset()

        self._scheduler.shutdown()
        await self._platform.stop()
        await close_engine()
        await close_redis()
        logger.info("Shutdown complete")

    async def _warmup_db(self) -> None:
        """启动时预热 DB 连接，避免首次请求慢。"""
        session_factory = get_session_factory()
        async with session_factory() as session:
            offset_repo = OffsetRepository(session)
            self._offset = await offset_repo.get_offset(self._platform.platform_name)
        logger.info("DB warmed up, offset=%d", self._offset)

    async def _send_reply(self, msg: IncomingMessage, reply: BotReply) -> None:
        """发送回复：优先 rich text → 旧卡片 → 纯文本。"""
        if reply.is_rich:
            await self._platform.send_rich_message(
                chat_id=msg.chat_id, reply=reply, chat_type=msg.chat_type,
            )
        elif reply.is_card:
            await self._platform.send_card(
                chat_id=msg.chat_id, reply=reply, chat_type=msg.chat_type,
            )
        else:
            await self._platform.send_message(
                chat_id=msg.chat_id, text=reply.text, chat_type=msg.chat_type,
            )

    # ─── Offset 异步刷盘 ───

    async def _flush_offset(self) -> None:
        """将内存 offset 写入 DB。"""
        if not self._offset_dirty:
            return
        try:
            session_factory = get_session_factory()
            async with session_factory() as session:
                async with session.begin():
                    repo = OffsetRepository(session)
                    await repo.save_offset(self._platform.platform_name, self._offset)
            self._offset_dirty = False
        except Exception as e:
            logger.error("Failed to flush offset: %s", e)

    async def _offset_flush_loop(self) -> None:
        """每 3 秒异步刷盘 offset，不阻塞主循环。"""
        while self._running:
            await asyncio.sleep(3)
            await self._flush_offset()

    # ─── Polling 主循环 ───

    async def _polling_loop(self) -> None:
        logger.info("Polling started with offset=%d", self._offset)

        while self._running:
            try:
                t0 = time.monotonic()
                messages = await self._platform.get_updates(self._offset)
                poll_ms = int((time.monotonic() - t0) * 1000)

                if messages:
                    self._offset = messages[-1].update_id + 1
                    self._offset_dirty = True

                    logger.info(
                        "Poll returned %d msgs in %dms, offset→%d",
                        len(messages), poll_ms, self._offset,
                    )

                    for msg in messages:
                        task = asyncio.create_task(self._process_message(msg))
                        self._active_tasks.add(task)
                        task.add_done_callback(self._active_tasks.discard)
                # 长轮询模式下空轮询不需要额外 sleep，服务端已阻塞等待

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Polling loop error: %s", e, exc_info=True)
                await asyncio.sleep(3)

    # ─── 单条消息处理 ───

    async def _process_message(self, msg: IncomingMessage) -> None:
        async with self._global_sem:
            try:
                await self._handle_message(msg)
            except Exception as e:
                logger.error(
                    "Failed to process msg from user=%d: %s",
                    msg.user_id, e, exc_info=True,
                )

    async def _handle_message(self, msg: IncomingMessage) -> None:
        session_factory = get_session_factory()

        # ── Callback Query 处理 ──
        if msg.callback_data:
            await self._handle_callback(msg, session_factory)
            return

        cmd = self._platform.parse_command(msg)

        # send_typing fire-and-forget
        asyncio.create_task(self._platform.send_typing(msg.chat_id, msg.chat_type))

        if cmd is None:
            if msg.chat_type != "private":
                return

            async with session_factory() as session:
                async with session.begin():
                    reply = await self._command_handler.handle_text(msg, session)

            await self._send_reply(msg, reply)
            return

        async with session_factory() as session:
            async with session.begin():
                reply = await self._command_handler.handle(cmd, session)

        await self._send_reply(msg, reply)

    async def _handle_callback(self, msg: IncomingMessage, session_factory) -> None:
        """
        处理 inline keyboard 按钮点击回调。
        callback_data 格式约定: "action:payload"，例如 "digest:小米"、"subscribe:AI 08:00"
        """
        data = msg.callback_data
        logger.info("Callback query: user=%d data='%s'", msg.user_id, data)

        # 防连点去重（同一 callback_query_id 只处理一次）
        dedup_key = f"newsdigest:cb_dedup:{msg.callback_query_id}"
        try:
            from newsdigest.app.core.redis import get_redis
            redis = get_redis()
            if await redis.get(dedup_key):
                logger.info("Duplicate callback ignored: %s", msg.callback_query_id)
                asyncio.create_task(self._platform.answer_callback(msg.callback_query_id))
                return
            await redis.set(dedup_key, "1", ex=60)
        except Exception:
            pass

        # 解析 action:payload
        if ":" in data:
            action, payload = data.split(":", 1)
        else:
            action, payload = data, ""

        # 应答回调（先应答，30 秒内必须）
        asyncio.create_task(
            self._platform.answer_callback(msg.callback_query_id, text="处理中...")
        )

        # 将 callback 转为命令处理
        cmd_msg = IncomingMessage(
            platform=msg.platform,
            update_id=msg.update_id,
            user_id=msg.user_id,
            user_name=msg.user_name,
            chat_id=msg.chat_id,
            chat_type=msg.chat_type,
            text=f"/{action} {payload}".strip() if payload else f"/{action}",
            timestamp=msg.timestamp,
        )

        cmd = self._platform.parse_command(cmd_msg)
        if cmd is None:
            return

        async with session_factory() as session:
            async with session.begin():
                reply = await self._command_handler.handle(cmd, session)

        await self._send_reply(msg, reply)


async def main() -> None:
    bot = NewsDigestBot()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(bot.stop()))

    try:
        await bot.start()
    except asyncio.CancelledError:
        pass
    finally:
        await bot.stop()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        sys.exit(0)
