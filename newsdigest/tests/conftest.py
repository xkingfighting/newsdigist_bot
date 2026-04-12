"""
测试配置与 fixtures
"""

import pytest


@pytest.fixture
def fake_news_items():
    """提供一组标准测试用 NewsItem。"""
    from datetime import datetime, timedelta
    from newsdigest.app.schemas.types import NewsItem

    now = datetime.utcnow()
    return [
        NewsItem(
            title="AI 领域重大突破",
            snippet="多家企业联合发布新技术框架，降低开发门槛。",
            source="科技日报",
            url="https://example.com/1",
            published_at=now - timedelta(hours=2),
        ),
        NewsItem(
            title="全球 AI 市场预计突破千亿",
            snippet="权威机构报告显示市场高速增长。",
            source="第一财经",
            url="https://example.com/2",
            published_at=now - timedelta(hours=5),
        ),
        NewsItem(
            title="",
            snippet="这条应该被过滤掉",
            source="",
            url="https://example.com/empty-title",
            published_at=None,
        ),
        NewsItem(
            title="AI 领域重大突破",
            snippet="重复标题应该被去重。",
            source="另一家",
            url="https://example.com/dup",
            published_at=None,
        ),
    ]
