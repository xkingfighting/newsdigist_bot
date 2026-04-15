"""
新闻主题聚类服务
将候选新闻按主题归类，选出主线，避免多主题混写。
"""

from __future__ import annotations

from collections import defaultdict

from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.news_scorer import ScoredItem

logger = get_logger(__name__)

# ─── 主题分类关键词 ───
# 按优先级排列，命中第一个即归类

TOPIC_RULES: list[tuple[str, list[str]]] = [
    ("产品发布", [
        "发布", "推出", "上市", "亮相", "发售", "开售", "预售",
        "新品", "新款", "首发", "官宣", "正式推送",
    ]),
    ("财报业绩", [
        "财报", "营收", "利润", "净利", "毛利", "季度", "年报",
        "同比", "环比", "出货量", "市场份额", "业绩",
    ]),
    ("供应链", [
        "供应链", "产能", "产线", "工厂", "代工", "芯片",
        "量产", "备货", "零部件", "良率",
    ]),
    ("技术能力", [
        "技术", "专利", "算法", "模型", "架构", "性能",
        "基准测试", "评分", "跑分", "突破",
    ]),
    ("市场价格", [
        "价格", "售价", "降价", "涨价", "优惠", "补贴",
        "成本", "定价",
    ]),
    ("政策监管", [
        "政策", "监管", "法案", "合规", "审查", "禁令",
        "处罚", "罚款", "反垄断",
    ]),
    ("投融资", [
        "融资", "收购", "并购", "投资", "ipo", "上市",
        "估值", "股价",
    ]),
    ("人事变动", [
        "裁员", "离职", "入职", "任命", "换帅", "ceo",
    ]),
]

# ─── 宽关键词列表 ───
BROAD_KEYWORDS = {
    "ai", "人工智能", "芯片", "手机", "内存", "黄金", "电池",
    "新能源", "汽车", "半导体", "显卡", "gpu", "cpu",
    "5g", "机器人", "无人机", "卫星", "区块链", "加密货币",
    "股票", "基金", "房价",
}


def classify_topic(item: NewsItem) -> str:
    """将单条新闻归入主题。未命中任何规则则归为"综合"。"""
    text = (item.title + " " + item.snippet[:100]).lower()
    for topic_name, keywords in TOPIC_RULES:
        for kw in keywords:
            if kw in text:
                return topic_name
    return "综合"


def select_mainline(
    scored_items: list[ScoredItem],
    max_main: int = 3,
    max_secondary: int = 1,
) -> tuple[str, list[NewsItem]]:
    """
    主线聚合（严格模式）：
    1. 对每条新闻分类
    2. 选累计得分最高的主题作为主线
    3. 主线最多 3 条
    4. 次主线最多补 1 条（且分数须 >= 主线平均分的 70%）
    5. 最终结果最多来自 2 个主题

    返回 (主线主题名, 选中的 NewsItem 列表)
    """
    topic_map: dict[str, list[ScoredItem]] = defaultdict(list)
    for si in scored_items:
        topic = classify_topic(si.item)
        topic_map[topic].append(si)
        logger.info("TOPIC [%s] score=%d %s", topic, si.score, si.item.title[:40])

    if not topic_map:
        return "综合", []

    # 每个主题的累计分数
    topic_scores = {t: sum(si.score for si in items) for t, items in topic_map.items()}
    ranked_topics = sorted(topic_scores.items(), key=lambda x: x[1], reverse=True)

    main_topic = ranked_topics[0][0]
    main_items = topic_map[main_topic]
    main_items.sort(key=lambda x: x.score, reverse=True)

    logger.info("MAINLINE: '%s' (total_score=%d, %d items)", main_topic, ranked_topics[0][1], len(main_items))

    result = [si.item for si in main_items[:max_main]]

    # 次主线补充：须达到主线平均分的 70%
    if max_secondary > 0 and len(ranked_topics) > 1:
        main_avg = ranked_topics[0][1] / max(len(main_items), 1)
        sec_topic = ranked_topics[1][0]
        sec_items = sorted(topic_map[sec_topic], key=lambda x: x.score, reverse=True)

        for si in sec_items[:max_secondary]:
            if si.score >= main_avg * 0.7:
                result.append(si.item)
                logger.info("SECONDARY [%s] score=%d %s", sec_topic, si.score, si.item.title[:40])
            else:
                logger.info("DROPPED secondary-too-weak [%s] score=%d < %.1f %s",
                            sec_topic, si.score, main_avg * 0.7, si.item.title[:40])

    # 记录所有被丢弃的跨主线新闻
    selected_set = {id(it) for it in result}
    for topic, items in topic_map.items():
        for si in items:
            if id(si.item) not in selected_set:
                logger.info("DROPPED cross-topic [%s] %s", topic, si.item.title[:40])

    return main_topic, result


def is_broad_keyword(keyword: str) -> bool:
    """检测是否为宽泛关键词。"""
    return keyword.lower().strip() in BROAD_KEYWORDS
