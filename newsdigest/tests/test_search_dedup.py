"""
搜索结果去重与过滤测试
"""

from newsdigest.app.services.search.base import deduplicate_items


def test_deduplicate_filters_empty_title(fake_news_items):
    result = deduplicate_items(fake_news_items)
    titles = [item.title for item in result]
    assert "" not in titles


def test_deduplicate_removes_duplicate_titles(fake_news_items):
    result = deduplicate_items(fake_news_items)
    titles = [item.title.strip().lower() for item in result]
    assert len(titles) == len(set(titles))


def test_deduplicate_keeps_valid_items(fake_news_items):
    result = deduplicate_items(fake_news_items)
    # 4 items input: 1 empty title filtered, 1 dup title filtered => 2 remain
    assert len(result) == 2
