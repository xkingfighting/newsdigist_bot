"""
Summarizer 测试 v3
测试关键词过滤、相似度去重、清洗、模板检测、幻觉检测、兜底逻辑。
"""

import pytest

from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.summarizer import (
    SummarizerService,
    FALLBACK_MESSAGE,
    INSUFFICIENT_MESSAGE,
)


def _item(title: str, snippet: str, source: str = "") -> NewsItem:
    return NewsItem(title=title, snippet=snippet, source=source, url="")


# ─── 关键词过滤 ───

def test_filter_by_keyword_keeps_relevant():
    items = [
        _item("小米发布新手机", "小米15 Ultra正式发售"),
        _item("苹果发布iOS更新", "苹果公司推送了最新系统"),
        _item("雷军谈小米汽车", "小米SU7的产能已经提升"),
    ]
    result = SummarizerService._filter_by_keyword(items, "小米")
    assert len(result) == 2
    assert all("小米" in it.title or "小米" in it.snippet[:100] for it in result)


def test_filter_by_keyword_case_insensitive():
    items = [
        _item("NVIDIA发布新GPU", "nvidia推出最新显卡"),
        _item("Intel发布CPU", "英特尔推出新处理器"),
    ]
    result = SummarizerService._filter_by_keyword(items, "nvidia")
    assert len(result) == 1


def test_filter_removes_all_irrelevant():
    items = [
        _item("天气预报", "明天多云转晴"),
        _item("体育新闻", "足球比赛结果公布"),
    ]
    result = SummarizerService._filter_by_keyword(items, "小米")
    assert len(result) == 0


# ─── 相似度去重 ───

def test_dedup_by_similarity():
    items = [
        _item("小米SU7正式发售，售价21.59万起", "内容A" * 10),
        _item("小米SU7正式发售，售价21.59万元起", "内容B" * 10),  # 高度相似
        _item("小米15 Ultra海外发售", "内容C" * 10),
    ]
    result = SummarizerService._dedup_by_similarity(items)
    assert len(result) == 2


def test_dedup_keeps_different_titles():
    items = [
        _item("小米汽车产能提升", "内容A" * 10),
        _item("小米手机出货量增长", "内容B" * 10),
    ]
    result = SummarizerService._dedup_by_similarity(items)
    assert len(result) == 2


# ─── 清洗 ───

def test_clean_items_filters_short():
    items = [
        _item("有效标题", "这是一条足够长的有效内容用于测试"),
        _item("太短", "短"),
    ]
    result = SummarizerService._clean_items(items)
    assert len(result) == 1


def test_clean_items_truncates_long():
    long_text = "测试内容" * 100
    items = [_item("长文", long_text)]
    result = SummarizerService._clean_items(items)
    assert len(result[0].snippet) <= 203


def test_clean_items_removes_noise():
    items = [_item("测试", "正常新闻内容写在这里。点击查看全文更多内容")]
    result = SummarizerService._clean_items(items)
    assert "点击查看全文" not in result[0].snippet


# ─── 输入构建 ───

def test_build_input_format():
    items = [
        _item("标题A", "内容A", "来源A"),
        _item("标题B", "内容B", ""),
    ]
    text = SummarizerService._build_input(items)
    assert "[1] 标题A（来源A）" in text
    assert "[2] 标题B\n内容B" in text


# ─── 输出清洗 ───

def test_clean_output_removes_prefix():
    assert SummarizerService._clean_output("摘要：内容") == "内容"
    assert SummarizerService._clean_output("总结如下：内容") == "内容"


def test_clean_output_removes_markdown():
    assert "**" not in SummarizerService._clean_output("**加粗**内容")


# ─── 模板化检测 ───

def test_is_templated_requires_two_hits():
    # 单个命中不触发
    assert SummarizerService._is_templated("近日苹果发布新产品") is False
    # 两个命中触发
    assert SummarizerService._is_templated("近日，业内人士认为这很重要") is True


# ─── 幻觉检测 ───

def test_hallucination_check_passes_clean_output():
    items = [_item("小米发布SU7", "小米汽车SU7正式发售")]
    text = "小米发布了SU7汽车"
    result = SummarizerService._hallucination_check(text, items, "小米")
    assert result == text  # 无幻觉，原样返回


def test_hallucination_check_catches_fabrication():
    items = [_item("小米发布SU7", "小米汽车SU7正式发售")]
    text = '小米发布了「量子计算芯片」'  # 输入中不存在
    result = SummarizerService._hallucination_check(text, items, "小米")
    assert "今日资讯要点" in result  # 回退到安全版本


# ─── 兜底 ───

@pytest.mark.asyncio
async def test_summarize_empty():
    svc = SummarizerService()
    result = await svc.summarize("AI", [])
    assert result == FALLBACK_MESSAGE.format(keyword="AI")


@pytest.mark.asyncio
async def test_summarize_insufficient_after_filter():
    """全部被关键词过滤掉后应返回不足文案。"""
    svc = SummarizerService()
    items = [
        _item("天气预报", "明天多云转晴温度适宜出行"),
        _item("体育赛事", "世界杯预选赛今晚开打"),
    ]
    result = await svc.summarize("小米", items)
    assert "有效资讯较少" in result


# ─── 序列化 ───

def test_items_to_json():
    items = [_item("测试", "内容")]
    result = SummarizerService.items_to_json(items)
    import json
    data = json.loads(result)
    assert data[0]["title"] == "测试"
