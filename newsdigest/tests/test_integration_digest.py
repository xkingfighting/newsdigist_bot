"""
集成测试 v4
"""

import pytest

from newsdigest.app.services.digest_service import DigestService
from newsdigest.app.services.search.fake_provider import FakeSearchProvider
from newsdigest.app.services.summarizer import SummarizerService, FALLBACK_MESSAGE


class MockSummarizer(SummarizerService):
    async def _call_ollama(self, prompt, temperature=0.15):
        return "小米SU7 Ultra量产版下线售价52.99万元；小米15 Ultra获DXOMark影像评分第一；小米集团Q4营收1090亿元同比增49%。"


@pytest.mark.asyncio
async def test_generate_digest_with_fake_provider():
    provider = FakeSearchProvider()
    summarizer = MockSummarizer()
    svc = DigestService(provider, summarizer)
    result = await svc.generate_digest("小米")
    assert "SU7" in result or "小米" in result


@pytest.mark.asyncio
async def test_generate_digest_empty_keyword():
    class EmptyProvider(FakeSearchProvider):
        async def search(self, keyword, max_results=8):
            return []

    svc = DigestService(EmptyProvider(), SummarizerService())
    result = await svc.generate_digest("xyznotexist")
    assert "暂未检索到" in result
