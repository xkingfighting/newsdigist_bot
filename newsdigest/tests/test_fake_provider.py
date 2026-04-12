"""
FakeSearchProvider 测试
"""

import pytest

from newsdigest.app.services.search.fake_provider import FakeSearchProvider


@pytest.mark.asyncio
async def test_fake_provider_returns_items():
    provider = FakeSearchProvider()
    items = await provider.search("AI", max_results=3)
    assert len(items) == 3
    assert all(item.title for item in items)
    assert all(item.snippet for item in items)


@pytest.mark.asyncio
async def test_fake_provider_respects_max_results():
    provider = FakeSearchProvider()
    items = await provider.search("AI", max_results=2)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_fake_provider_fallback_for_unknown_keyword():
    provider = FakeSearchProvider()
    items = await provider.search("未知关键词", max_results=3)
    assert len(items) == 3


@pytest.mark.asyncio
async def test_fake_provider_name():
    provider = FakeSearchProvider()
    assert provider.provider_name == "fake"
