"""
NewsFilter + NewsScorer 测试
"""

from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.news_filter import NewsFilterService
from newsdigest.app.services.news_scorer import NewsScorerService


def _item(title, snippet, source=""):
    return NewsItem(title=title, snippet=snippet, source=source, url="")


# ─── Filter ───

def test_filter_removes_low_value():
    svc = NewsFilterService()
    items = [
        _item("苹果发布iOS 20", "苹果公司推送了最新的iOS系统更新", "新华社"),
        _item("网友热议iPhone外观", "网友们对iPhone新外观议论纷纷", "百家号"),
        _item("开箱全新MacBook", "博主开箱了全新MacBook体验评测", "bilibili"),
    ]
    result = svc.filter(items, "苹果")
    assert len(result) == 1
    assert "iOS" in result[0].title


def test_filter_blocks_high_risk_weak_source():
    svc = NewsFilterService()
    items = [
        _item("苹果收购某AI公司", "苹果据传以10亿收购AI初创公司", "百家号"),
        _item("苹果WWDC确认6月召开", "苹果官方宣布WWDC 2026将于6月9日至13日在Apple Park举行", "新华社"),
    ]
    result = svc.filter(items, "苹果")
    assert len(result) == 1
    assert "WWDC" in result[0].title


def test_filter_keeps_high_risk_strong_source():
    svc = NewsFilterService()
    items = [
        _item("苹果收购AI初创公司", "苹果确认以10亿美元收购AI公司", "Bloomberg"),
    ]
    result = svc.filter(items, "苹果")
    assert len(result) == 1


def test_filter_removes_irrelevant():
    svc = NewsFilterService()
    items = [
        _item("天气预报", "明天多云转晴温度适宜出行建议出门", "央视"),
    ]
    result = svc.filter(items, "苹果")
    assert len(result) == 0


# ─── Scorer ───

def test_scorer_ranks_by_quality():
    svc = NewsScorerService()
    items = [
        _item("小米发布新手机", "小米正式推出小米15系列手机", "驱动之家"),
        _item("小米Q4财报发布", "小米集团发布季度营收报告，营收超预期", "Bloomberg"),
    ]
    scored = svc.score_and_rank(items, "小米")
    assert len(scored) >= 1
    # Bloomberg 来源的财报应该排前面
    assert scored[0].item.source == "Bloomberg"


def test_scorer_drops_low_score():
    svc = NewsScorerService()
    items = [
        _item("某小众论坛讨论", "一些用户在论坛上讨论了小米手机体验", ""),
    ]
    scored = svc.score_and_rank(items, "小米")
    # 无来源 + 低价值信号 → 低分被丢弃
    assert len(scored) == 0 or scored[0].score < 4


def test_scorer_penalizes_risk_words():
    svc = NewsScorerService()
    items = [
        _item("小米据称将收购某公司", "据传小米或将以大额收购某AI公司", "IT之家"),
    ]
    scored = svc.score_and_rank(items, "小米", threshold=0)
    assert scored[0].score < 6  # 有风险词降权
