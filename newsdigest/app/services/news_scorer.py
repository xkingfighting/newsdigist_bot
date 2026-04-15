"""
新闻评分服务
多维度评分，只有 score >= 阈值的新闻进入摘要候选集。
"""

from __future__ import annotations

from dataclasses import dataclass

from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem

logger = get_logger(__name__)

# 评分阈值：低于此分数不进入最终摘要
SCORE_THRESHOLD = 4

# ─── 来源可信度分级 ───

_HIGH_SOURCES = [
    "reuters", "bloomberg", "ap", "wsj", "ft", "financial times",
    "techcrunch", "the verge", "wired", "ars technica",
    "36氪", "36kr", "晚点", "latepost", "财新", "caixin",
    "第一财经", "界面新闻", "澎湃", "澎湃新闻",
    "新华社", "新华网", "人民网", "人民日报",
    "cnbc", "bbc", "nytimes", "guardian",
    "中国证券报", "证券时报", "经济日报",
    "新浪财经", "凤凰网", "环球时报", "中新网",
]

_MID_SOURCES = [
    "cnbeta", "ithome", "it之家", "快科技", "驱动之家",
    "电子工程专辑", "半导体行业观察", "infoq", "oschina",
    "虎嗅", "钛媒体", "创业邦", "投资界",
    "雷锋网", "量子位", "机器之心",
    "sohu", "搜狐", "网易", "腾讯",
    "gsmarena", "electrek", "9to5mac", "macrumors",
    "汽车之家", "懂车帝",
]

# ─── 风险词（降权） ───

_RISK_WORDS = [
    "传闻", "爆料", "据称", "或将", "未证实", "网传",
    "疑似", "可能", "有望", "预计将",
]

# ─── 低价值信号词（降权） ───

_LOW_VALUE_SIGNALS = [
    "用户体验", "个人感受", "改装", "diy", "自制",
    "壁纸", "铃声", "口水", "撕逼", "互怼",
]


@dataclass
class ScoredItem:
    item: NewsItem
    score: int
    reasons: list[str]


class NewsScorerService:

    def score_and_rank(
        self, items: list[NewsItem], keyword: str, threshold: int = SCORE_THRESHOLD,
    ) -> list[ScoredItem]:
        """
        对每条新闻打分，返回 score >= threshold 的条目（按分数降序）。
        """
        kw_lower = keyword.lower()
        scored: list[ScoredItem] = []

        for item in items:
            score = 0
            reasons: list[str] = []
            title_lower = item.title.lower()
            snippet_lower = item.snippet.lower()
            source_lower = (item.source or "").lower()

            # 1) 来源可信度
            src_score = self._source_score(source_lower)
            score += src_score
            if src_score > 0:
                reasons.append(f"source:{'+' if src_score > 0 else ''}{src_score}")

            # 2) 关键词匹配强度
            kw_score = self._keyword_score(kw_lower, title_lower, snippet_lower)
            score += kw_score
            reasons.append(f"keyword:{'+' if kw_score > 0 else ''}{kw_score}")

            # 3) 官方实体加分
            official = self._official_score(snippet_lower)
            if official > 0:
                score += official
                reasons.append(f"official:+{official}")

            # 4) 风险内容降权
            risk = self._risk_penalty(title_lower + " " + snippet_lower)
            if risk < 0:
                score += risk
                reasons.append(f"risk:{risk}")

            # 5) 低价值题材降权
            low_val = self._low_value_penalty(title_lower + " " + snippet_lower)
            if low_val < 0:
                score += low_val
                reasons.append(f"low-val:{low_val}")

            if score >= threshold:
                scored.append(ScoredItem(item=item, score=score, reasons=reasons))
                logger.info("SCORED [%d] %s %s", score, " ".join(reasons), item.title[:40])
            else:
                logger.info("DROPPED [%d < %d] %s %s", score, threshold, " ".join(reasons), item.title[:40])

        # 按分数降序
        scored.sort(key=lambda x: x.score, reverse=True)
        return scored

    @staticmethod
    def _source_score(source_lower: str) -> int:
        if not source_lower:
            return 0
        for s in _HIGH_SOURCES:
            if s in source_lower:
                return 4
        for s in _MID_SOURCES:
            if s in source_lower:
                return 2
        return 0

    @staticmethod
    def _keyword_score(kw: str, title: str, snippet: str) -> int:
        # 标题精确包含
        if kw in title:
            return 4
        # 正文前 80 字包含
        if kw in snippet[:80]:
            return 2
        # 正文深处
        if kw in snippet:
            return 0
        return -1

    @staticmethod
    def _official_score(snippet_lower: str) -> int:
        official_signals = [
            "发布会", "财报", "官方声明", "官方公告", "官方博客",
            "ceo", "创始人", "总裁", "董事长", "首席",
            "季度营收", "年度报告", "出货量",
        ]
        hits = sum(1 for s in official_signals if s in snippet_lower)
        return min(hits * 2, 4)  # 最多 +4

    @staticmethod
    def _risk_penalty(text: str) -> int:
        hits = sum(1 for w in _RISK_WORDS if w in text)
        return -min(hits * 2, 4)  # 每命中一个 -2，最多 -4

    @staticmethod
    def _low_value_penalty(text: str) -> int:
        hits = sum(1 for w in _LOW_VALUE_SIGNALS if w in text)
        return -min(hits * 2, 4)
