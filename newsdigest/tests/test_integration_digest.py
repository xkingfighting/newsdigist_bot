"""
集成测试
使用 FakeProvider + MockSummarizer 验证完整 digest 流程。
"""

import pytest

from newsdigest.app.services.digest_service import DigestService
from newsdigest.app.services.search.fake_provider import FakeSearchProvider
from newsdigest.app.services.summarizer import SummarizerService, FALLBACK_MESSAGE, INSUFFICIENT_MESSAGE


class MockSummarizer(SummarizerService):
    """替换 Ollama 调用的 Mock，直接返回固定文本。"""

    async def _call_ollama(self, prompt: str, temperature: float = 0.2) -> str:
        return "1️⃣ 小米SU7 Ultra量产版下线，售价52.99万元\n2️⃣ 小米15 Ultra获DXOMark评分第一\n趋势：小米高端化战略持续推进"


@pytest.mark.asyncio
async def test_generate_digest_with_fake_provider():
    """完整链路：FakeProvider → 关键词过滤 → MockSummarizer → 输出。"""
    provider = FakeSearchProvider()
    summarizer = MockSummarizer()
    svc = DigestService(provider, summarizer)

    # 用"小米"——FakeProvider 有对应数据且标题含关键词
    result = await svc.generate_digest("小米")
    assert "SU7" in result or "小米" in result


@pytest.mark.asyncio
async def test_generate_digest_empty_keyword():
    """无结果时应返回兜底文案。"""

    class EmptyProvider(FakeSearchProvider):
        async def search(self, keyword, max_results=8):
            return []

    provider = EmptyProvider()
    summarizer = SummarizerService()
    svc = DigestService(provider, summarizer)

    result = await svc.generate_digest("xyznotexist")
    assert "暂未检索到" in result
