"""
新闻过滤服务
过滤低质量、八卦、论坛、自媒体等不适合进入商业摘要的内容。
"""

from __future__ import annotations

import re

from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem

logger = get_logger(__name__)

# ─── 标题黑名单关键词（命中即丢弃） ───
LOW_VALUE_KEYWORDS = [
    # 自媒体/八卦
    "网友", "热议", "曝光", "震惊", "居然", "开箱", "上手",
    "测评", "打磨", "论坛", "爆料", "粉丝", "博主", "自制",
    "教程", "拆解", "翻车", "吐槽", "口水", "段子", "沙雕",
    "壁纸", "铃声", "美化", "主题", "抢购攻略", "省钱",
    # 人物参观/情绪/体验 — 非核心事件
    "参观", "参访", "点赞", "怒赞", "喜欢", "太棒了",
    "真香", "体验分享", "使用感受", "用后感", "种草",
    "带回", "想买", "心动", "安利", "晒单", "好评",
    "差评", "吐血", "崩溃", "无语", "笑哭",
]

# ─── 低可信来源黑名单（命中则丢弃） ───
LOW_CREDIBILITY_SOURCES = [
    "百家号", "搜狐号", "头条号", "企鹅号", "大风号",
    "知乎专栏", "贴吧", "豆瓣", "什么值得买",
    "bilibili", "b站", "抖音", "快手",
    "小红书", "微博", "weibo",
]

# ─── 高风险关键词（需要高可信来源才能保留） ───
HIGH_RISK_KEYWORDS = [
    "收购", "出售", "并购", "融资", "IPO", "上市",
    "裁员", "破产", "诉讼", "起诉", "罚款", "处罚",
    "事故", "召回", "泄露", "数据泄露",
]

# ─── 高可信来源白名单 ───
HIGH_CREDIBILITY_SOURCES = [
    "reuters", "bloomberg", "ap", "wsj", "ft",
    "techcrunch", "the verge", "wired", "ars technica",
    "36氪", "36kr", "晚点", "晚点latepost", "财新", "caixin",
    "第一财经", "界面新闻", "澎湃", "澎湃新闻",
    "新华社", "新华网", "人民网", "人民日报",
    "中国证券报", "证券时报", "经济日报",
    "cnbc", "bbc", "nytimes", "guardian",
    "新浪财经", "凤凰网", "凤凰财经",
    "环球时报", "中新网", "中国新闻网",
]

# 内容噪音清洗
_NOISE_PATTERNS = [
    re.compile(r"点击查看全文.*", re.IGNORECASE),
    re.compile(r"展开全文.*", re.IGNORECASE),
    re.compile(r"阅读原文.*", re.IGNORECASE),
    re.compile(r"来源：.*$", re.MULTILINE),
    re.compile(r"责任编辑：.*$", re.MULTILINE),
    re.compile(r"\[.*?图片.*?\]"),
]

_MAX_SNIPPET_LEN = 200


class NewsFilterService:
    """对搜索结果进行质量过滤。"""

    def filter(self, items: list[NewsItem], keyword: str) -> list[NewsItem]:
        """
        过滤流程：
        1. 关键词相关性
        2. 低质量标题过滤
        3. 低可信来源过滤
        4. 高风险事实来源检查
        5. 内容清洗
        返回过滤后的列表，并打印每条被丢弃的原因。
        """
        result: list[NewsItem] = []
        kw_lower = keyword.lower()

        for item in items:
            title_lower = item.title.lower()
            snippet_lower = item.snippet.lower()
            source_lower = (item.source or "").lower()

            # 1) 关键词相关性
            if kw_lower not in title_lower and kw_lower not in snippet_lower[:100]:
                logger.debug("FILTERED [keyword miss] %s", item.title[:40])
                continue

            # 2) 低质量标题
            hit = self._match_low_value(title_lower)
            if hit:
                logger.info("FILTERED [low-value: '%s'] %s", hit, item.title[:40])
                continue

            # 3) 低可信来源
            if self._is_low_credibility_source(source_lower):
                logger.info("FILTERED [low-source: '%s'] %s", item.source, item.title[:40])
                continue

            # 4) 高风险事实 + 来源不够强
            risk_hit = self._match_high_risk(title_lower + " " + snippet_lower[:100])
            if risk_hit and not self._is_high_credibility_source(source_lower):
                logger.info(
                    "FILTERED [high-risk '%s' + weak source '%s'] %s",
                    risk_hit, item.source, item.title[:40],
                )
                continue

            # 5) 内容清洗
            snippet = item.snippet.strip()
            for pattern in _NOISE_PATTERNS:
                snippet = pattern.sub("", snippet)
            snippet = snippet.strip()

            if not snippet or len(snippet) < 15:
                logger.debug("FILTERED [too short] %s", item.title[:40])
                continue
            if len(snippet) > _MAX_SNIPPET_LEN:
                snippet = snippet[:_MAX_SNIPPET_LEN] + "…"

            result.append(NewsItem(
                title=item.title.strip(),
                snippet=snippet,
                source=item.source,
                url=item.url,
                published_at=item.published_at,
            ))

        return result

    @staticmethod
    def _match_low_value(title_lower: str) -> str | None:
        for kw in LOW_VALUE_KEYWORDS:
            if kw in title_lower:
                return kw
        return None

    @staticmethod
    def _match_high_risk(text_lower: str) -> str | None:
        for kw in HIGH_RISK_KEYWORDS:
            if kw in text_lower:
                return kw
        return None

    @staticmethod
    def _is_low_credibility_source(source_lower: str) -> bool:
        if not source_lower:
            return False
        for s in LOW_CREDIBILITY_SOURCES:
            if s in source_lower:
                return True
        return False

    @staticmethod
    def _is_high_credibility_source(source_lower: str) -> bool:
        if not source_lower:
            return False
        for s in HIGH_CREDIBILITY_SOURCES:
            if s in source_lower:
                return True
        return False
