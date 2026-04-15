"""
Summarizer v4 测试
"""

import pytest

from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.summarizer import (
    SummarizerService,
    FALLBACK_MESSAGE,
    INSUFFICIENT_MESSAGE,
)


def _item(title, snippet, source=""):
    return NewsItem(title=title, snippet=snippet, source=source, url="")


def test_dedup_by_similarity():
    items = [
        _item("小米SU7正式发售，售价21.59万起", "内容A" * 10),
        _item("小米SU7正式发售，售价21.59万元起", "内容B" * 10),
        _item("小米15 Ultra海外发售", "内容C" * 10),
    ]
    result = SummarizerService._dedup_by_similarity(items)
    assert len(result) == 2


def test_build_input_includes_source():
    items = [_item("标题A", "内容A", "36氪"), _item("标题B", "内容B", "")]
    text = SummarizerService._build_input(items)
    assert "来源：36氪" in text
    assert "[2] 标题B" in text


def test_clean_output_single_paragraph():
    raw = "1️⃣ 事实一\n2️⃣ 事实二\n趋势：xxx"
    cleaned = SummarizerService._clean_output(raw)
    assert "趋势" not in cleaned
    assert "\n" not in cleaned  # 单段


def test_clean_output_ensures_period():
    assert SummarizerService._clean_output("内容结尾没句号")[-1] == "。"


def test_is_templated_requires_two():
    assert SummarizerService._is_templated("近日苹果发布新产品") is False
    assert SummarizerService._is_templated("近日，业内人士认为很重要") is True


def test_hallucination_check_clean():
    items = [_item("小米发布SU7", "小米汽车SU7正式发售")]
    text = "小米发布了SU7汽车。"
    result = SummarizerService._hallucination_check(text, items, "小米")
    assert result == text


@pytest.mark.asyncio
async def test_summarize_empty():
    svc = SummarizerService()
    result = await svc.summarize("AI", [])
    assert "暂未检索到" in result


@pytest.mark.asyncio
async def test_summarize_insufficient():
    svc = SummarizerService()
    result = await svc.summarize("AI", [_item("只有一条", "内容不够")])
    assert "高质量资讯较少" in result


def test_items_to_json():
    import json
    items = [_item("测试", "内容")]
    data = json.loads(SummarizerService.items_to_json(items))
    assert data[0]["title"] == "测试"
