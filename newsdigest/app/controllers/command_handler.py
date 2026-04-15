"""
命令控制器
接收解析后的 BotCommand，调用 Service 层处理，返回 BotReply。
所有操作按聊天上下文隔离：私聊看私聊订阅，群聊看本群订阅。

交互流程：
  /unsubscribe        → ListCard 选择 → ActionCard 确认 → 执行
  /pause              → ListCard 选择 → 执行
  /resume             → ListCard 选择 → 执行
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from newsdigest.app.adapters.base import BotPlatform
from newsdigest.app.core.logging import get_logger
from newsdigest.app.repositories.subscription_repo import SubscriptionRepository
from newsdigest.app.repositories.user_repo import UserRepository
from newsdigest.app.schemas.types import BotCommand, BotReply, CardButton, CardItem
from newsdigest.app.services.digest_service import DigestService
from newsdigest.app.services.subscription_service import SubscriptionService

logger = get_logger(__name__)

WELCOME_TEXT = """👋 欢迎使用 NewsDigest！

我是你的每日资讯助手，可以帮你追踪关键词并每天推送摘要。

📋 可用命令：
/subscribe <关键词> <HH:MM> - 创建订阅
/list - 查看所有订阅
/unsubscribe - 取消订阅
/settime <HH:MM> - 统一修改推送时间
/pause - 暂停订阅
/resume - 恢复订阅
/digest <关键词> - 立即获取摘要
/help - 显示帮助"""

HELP_TEXT = """📖 NewsDigest 命令帮助

/subscribe <关键词> <HH:MM>
  创建每日资讯订阅
  示例：/subscribe AI 09:00

/list
  查看当前会话的所有订阅

/unsubscribe
  取消订阅（交互式选择）

/settime <HH:MM>
  统一修改所有订阅的推送时间
  示例：/settime 08:00

/pause
  暂停推送（交互式选择）

/resume
  恢复已暂停的订阅（交互式选择）

/digest <关键词>
  立即获取该关键词的资讯摘要

/help
  显示此帮助信息"""


def _text(content: str) -> BotReply:
    return BotReply(text=content)


class CommandHandler:

    def __init__(
        self,
        platform: BotPlatform,
        digest_service: DigestService,
        scheduler_register_fn=None,
        scheduler_remove_fn=None,
    ) -> None:
        self._platform = platform
        self._digest_service = digest_service
        self._scheduler_register = scheduler_register_fn
        self._scheduler_remove = scheduler_remove_fn

    async def handle(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        logger.info(
            "Command received: /%s args=%s user=%s chat=%s:%s",
            cmd.name, cmd.args,
            cmd.message.user_id if cmd.message else "?",
            cmd.message.chat_type if cmd.message else "?",
            cmd.message.chat_id if cmd.message else "?",
        )

        handler_map = {
            "start": self._handle_start,
            "help": self._handle_help,
            "subscribe": self._handle_subscribe,
            "list": self._handle_list,
            "unsubscribe": self._handle_unsubscribe,
            "unsub_yes": self._handle_unsub_yes,
            "unsub_all": self._handle_unsub_all,
            "unsub_all_yes": self._handle_unsub_all_yes,
            "settime": self._handle_settime,
            "pause": self._handle_pause,
            "resume": self._handle_resume,
            "digest": self._handle_digest,
            "digest_refresh": self._handle_digest_refresh,
        }

        handler = handler_map.get(cmd.name)
        if handler is None:
            return _text(f"未知命令: /{cmd.name}\n输入 /help 查看帮助。")

        return await handler(cmd, session)

    # ─── 基础命令 ───

    async def _handle_start(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        return _text(WELCOME_TEXT)

    async def _handle_help(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        return _text(HELP_TEXT)

    # ─── 订阅 ───

    async def _handle_subscribe(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        if len(cmd.args) < 2:
            return _text("用法：/subscribe <关键词> <HH:MM>\n示例：/subscribe AI 09:00")

        keyword = cmd.args[0]
        push_time = cmd.args[1]
        msg = cmd.message
        svc = self._build_svc(session)

        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        success, reply, sub = await svc.subscribe(
            user, keyword, push_time, msg.platform,
            chat_id=msg.chat_id, chat_type=msg.chat_type,
        )

        if success and sub and self._scheduler_register:
            await self._scheduler_register(sub, user)

        return _text(reply)

    # ─── 列表 ───

    async def _handle_list(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        msg = cmd.message
        svc = self._build_svc(session)

        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        if not subs:
            where = "本群" if msg.chat_type == "group" else ""
            return _text(f"{where}还没有任何订阅。\n使用 /subscribe <关键词> <HH:MM> 创建一个。")

        items: list[CardItem] = []
        for s in subs:
            icon = "🟢" if s.status == "active" else "⏸️"
            items.append(CardItem(
                title=f"{icon} {s.keyword}",
                description=f"每天 {s.push_time} · {s.status}",
                command=f"/digest {s.keyword}",
            ))

        title = "📋 本群订阅列表" if msg.chat_type == "group" else "📋 你的订阅列表"
        return BotReply(
            card_type=11,
            card_text=f"{title}\n点击可立即获取摘要",
            card_items=items,
        )

    # ─── 取消订阅 ───

    async def _handle_unsubscribe(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        # 有参数 → 展示确认卡片
        if cmd.args:
            keyword = cmd.args[0]
            sub = await SubscriptionRepository(session).find_by_keyword_in_chat(
                keyword, msg.chat_id, msg.chat_type, user_id=user.id,
            )
            if not sub:
                return _text(f"未找到关键词「{keyword}」的订阅。")

            return BotReply(
                card_type=10,
                card_text=f"确定要取消「{keyword}」的订阅吗？\n每天 {sub.push_time} · {sub.status}",
                card_buttons=[
                    CardButton(label="确认取消", command=f"/unsub_yes {keyword}", style="primary"),
                    CardButton(label="不了", command="/list"),
                ],
            )

        # 无参数 → 列出可取消的订阅
        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        if not subs:
            return _text("没有可取消的订阅。")

        items: list[CardItem] = []
        for s in subs:
            icon = "🟢" if s.status == "active" else "⏸️"
            items.append(CardItem(
                title=f"{icon} {s.keyword}",
                description=f"每天 {s.push_time} · {s.status}",
                command=f"/unsubscribe {s.keyword}",
            ))

        # 多于 1 个订阅时，末尾加「取消全部」
        if len(subs) > 1:
            items.append(CardItem(
                title="🗑 取消全部订阅",
                description=f"一键清除全部 {len(subs)} 个订阅",
                command="/unsub_all",
            ))

        return BotReply(
            card_type=11,
            card_text="选择要取消的订阅",
            card_items=items,
        )

    async def _handle_unsub_yes(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        if not cmd.args:
            return _text("操作无效。")

        keyword = cmd.args[0]
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        success, reply = await svc.unsubscribe(user, keyword, msg.chat_id, msg.chat_type)

        if success and self._scheduler_remove:
            self._scheduler_remove(user.id, keyword)

        return _text(reply)

    async def _handle_unsub_all(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        """展示取消全部的确认卡片。"""
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )
        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        if not subs:
            return _text("没有可取消的订阅。")

        keywords = "、".join(f"「{s.keyword}」" for s in subs)
        return BotReply(
            card_type=10,
            card_text=f"确定要取消全部 {len(subs)} 个订阅吗？\n{keywords}",
            card_buttons=[
                CardButton(label=f"确认取消全部（{len(subs)}个）", command="/unsub_all_yes", style="primary"),
                CardButton(label="不了", command="/list"),
            ],
        )

    async def _handle_unsub_all_yes(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        """执行取消全部订阅。"""
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )
        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        if not subs:
            return _text("没有可取消的订阅。")

        count = 0
        for s in subs:
            success, _ = await svc.unsubscribe(user, s.keyword, msg.chat_id, msg.chat_type)
            if success:
                if self._scheduler_remove:
                    self._scheduler_remove(user.id, s.keyword)
                count += 1

        return _text(f"已取消全部 {count} 个订阅。")

    # ─── 统一修改时间 ───

    async def _handle_settime(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        """
        /settime HH:MM — 将所有活跃订阅的推送时间统一修改。
        """
        if not cmd.args:
            return _text("用法：/settime <HH:MM>\n示例：/settime 08:00\n将所有订阅的推送时间统一修改。")

        push_time = cmd.args[0]
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        import re
        if not re.match(r"^([01]\d|2[0-3]):([0-5]\d)$", push_time):
            return _text(f"时间格式不正确，请使用 HH:MM（如 08:00）。收到: {push_time}")

        count, updated_subs = await svc.set_all_time(user, push_time, msg.chat_id, msg.chat_type)

        if count == 0:
            return _text("没有活跃的订阅可以修改。")

        # 重新注册所有调度任务
        if self._scheduler_register and self._scheduler_remove:
            for sub in updated_subs:
                self._scheduler_remove(user.id, sub.keyword)
                await self._scheduler_register(sub, user)

        keywords = "、".join(f"「{s.keyword}」" for s in updated_subs)
        return _text(f"已将 {count} 个订阅的推送时间统一修改为 {push_time}。\n{keywords}")

    # ─── 暂停 ───

    async def _handle_pause(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        if cmd.args:
            keyword = cmd.args[0]
            success, reply, sub = await svc.pause(user, keyword, msg.chat_id, msg.chat_type)
            if success and self._scheduler_remove:
                self._scheduler_remove(user.id, keyword)
            return _text(reply)

        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        active_subs = [s for s in subs if s.status == "active"]

        if not active_subs:
            return _text("没有���在运行的订阅可以暂停。")

        items: list[CardItem] = []
        for s in active_subs:
            items.append(CardItem(
                title=f"🟢 {s.keyword}",
                description=f"每天 {s.push_time}",
                command=f"/pause {s.keyword}",
            ))

        return BotReply(
            card_type=11,
            card_text="选择要暂停的订阅",
            card_items=items,
        )

    # ─── 恢复 ───

    async def _handle_resume(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        msg = cmd.message
        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        if cmd.args:
            keyword = cmd.args[0]
            success, reply, sub = await svc.resume(user, keyword, msg.chat_id, msg.chat_type)
            if success and sub and self._scheduler_register:
                await self._scheduler_register(sub, user)
            return _text(reply)

        subs = await svc.list_subscriptions(user, msg.chat_id, msg.chat_type)
        paused_subs = [s for s in subs if s.status == "paused"]

        if not paused_subs:
            return _text("没有已暂停的订阅可以恢复。")

        items: list[CardItem] = []
        for s in paused_subs:
            items.append(CardItem(
                title=f"⏸️ {s.keyword}",
                description=f"每天 {s.push_time}",
                command=f"/resume {s.keyword}",
            ))

        return BotReply(
            card_type=11,
            card_text="选择要恢复的订阅",
            card_items=items,
        )

    # ─── 立即摘要 ───

    async def _handle_digest(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        if not cmd.args:
            return _text("用法：/digest <关键词>\n示例：/digest AI")

        keyword = cmd.args[0]
        logger.info("Immediate digest requested for '%s'", keyword)

        summary = await self._digest_service.generate_digest(keyword)
        return self._build_digest_reply(keyword, summary)

    async def _handle_digest_refresh(self, cmd: BotCommand, session: AsyncSession) -> BotReply:
        """刷新按钮：跳过缓存重新生成摘要。"""
        if not cmd.args:
            return _text("操作无效。")

        keyword = cmd.args[0]
        logger.info("Digest refresh requested for '%s'", keyword)

        summary = await self._digest_service.generate_digest(keyword, skip_cache=True)
        return self._build_digest_reply(keyword, summary)

    # ─── 摘要富文本构建 ───

    @staticmethod
    def _build_digest_reply(keyword: str, summary: str) -> BotReply:
        """
        构建摘要回复：
        - 标题加粗（entities）
        - inline keyboard：刷新 / 订阅 / 复制
        """
        from newsdigest.app.schemas.types import TextEntity, InlineButton
        from datetime import datetime
        import pytz
        from newsdigest.app.core.config import settings

        title = f"{keyword} 资讯摘要"
        full_text = f"{title}\n\n{summary}"

        # 标题加粗 entity（UTF-16 长度计算）
        title_utf16_len = len(title.encode("utf-16-le")) // 2
        entities = [TextEntity(type="bold", offset=0, length=title_utf16_len)]

        # 默认订阅时间 = 当前时间
        tz = pytz.timezone(settings.digest.default_timezone)
        now_str = datetime.now(tz).strftime("%H:%M")

        # Inline keyboard
        keyboard = [[
            InlineButton(text="刷新", callback_data=f"digest_refresh:{keyword}"),
            InlineButton(text=f"订阅（每天 {now_str}）", callback_data=f"subscribe:{keyword} {now_str}"),
            InlineButton(text="复制摘要", copy_text=summary),
        ]]

        return BotReply(
            text=full_text,
            entities=entities,
            inline_keyboard=keyboard,
        )

    # ─── 私聊纯文本智能响应 ───

    async def handle_text(self, msg, session: AsyncSession) -> BotReply:
        """
        私聊中用户发送非命令文本时，用 inline keyboard 引导。
        """
        from newsdigest.app.schemas.types import InlineButton

        text = msg.text.strip()
        if not text:
            return _text("输入 /help 查看可用命令。")

        svc = self._build_svc(session)
        user = await svc.ensure_user(
            platform=msg.platform,
            platform_user_id=msg.user_id,
            display_name=msg.user_name,
        )

        sub = await SubscriptionRepository(session).find_by_keyword_in_chat(
            keyword=text, chat_id=msg.chat_id, chat_type=msg.chat_type, user_id=user.id,
        )

        if sub:
            return BotReply(
                text=f"「{text}」已在你的订阅中（每天 {sub.push_time}）",
                inline_keyboard=[[
                    InlineButton(text="立即获取摘要", callback_data=f"digest:{text}"),
                    InlineButton(text="取消订阅", callback_data=f"unsubscribe:{text}"),
                ]],
            )
        else:
            from datetime import datetime
            import pytz
            from newsdigest.app.core.config import settings
            tz = pytz.timezone(settings.digest.default_timezone)
            now_str = datetime.now(tz).strftime("%H:%M")

            return BotReply(
                text=f"你想了解「{text}」的最新资讯吗？",
                inline_keyboard=[[
                    InlineButton(text="立即获取摘要", callback_data=f"digest:{text}"),
                    InlineButton(text=f"订阅（每天 {now_str}）", callback_data=f"subscribe:{text} {now_str}"),
                ]],
            )

    # ─── 工具 ───

    def _build_svc(self, session: AsyncSession) -> SubscriptionService:
        return SubscriptionService(UserRepository(session), SubscriptionRepository(session))
