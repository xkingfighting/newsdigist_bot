"""
资讯搜索 Provider 抽象层
可插拔设计，未来可接 SearXNG / Tavily / SerpAPI / 自有搜索服务。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from newsdigest.app.schemas.types import NewsItem


class SearchProvider(ABC):
    """搜索 Provider 抽象基类"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...

    @abstractmethod
    async def search(self, keyword: str, max_results: int = 8) -> list[NewsItem]:
        """
        根据关键词搜索资讯。
        返回标准化的 NewsItem 列表。
        """
        ...


def deduplicate_items(items: list[NewsItem]) -> list[NewsItem]:
    """按 URL 和标题去重，过滤无效条目。"""
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result: list[NewsItem] = []

    for item in items:
        # 过滤空标题或空摘要
        if not item.title.strip() or not item.snippet.strip():
            continue
        # URL 去重
        if item.url and item.url in seen_urls:
            continue
        # 标题去重
        title_key = item.title.strip().lower()
        if title_key in seen_titles:
            continue

        seen_urls.add(item.url)
        seen_titles.add(title_key)
        result.append(item)

    return result
