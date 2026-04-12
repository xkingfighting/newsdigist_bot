"""
Bing News RSS 搜索 Provider
无需 API Key，通过 Bing News RSS Feed 按关键词抓取资讯。
国内可直接访问，无需代理，作为 Google News 的备选方案。

RSS URL: https://www.bing.com/news/search?q={keyword}&format=rss&cc=cn&setlang=zh-hans
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime

import feedparser
import httpx

from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.search.base import SearchProvider

logger = get_logger(__name__)

_BING_NEWS_RSS = "https://www.bing.com/news/search"
_MAX_SNIPPET_LEN = 200
_MIN_SNIPPET_LEN = 20

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_NOISE_RE = re.compile(r"(点击查看全文|展开全文|阅读原文|查看更多).*$")


class BingNewsProvider(SearchProvider):
    """
    通过 Bing News RSS Feed 抓取资讯。
    国内可直接访问，无需 API Key。
    """

    @property
    def provider_name(self) -> str:
        return "bing_news"

    async def search(self, keyword: str, max_results: int = 8) -> list[NewsItem]:
        params = {
            "q": keyword,
            "format": "rss",
            "cc": "cn",
            "setlang": "zh-hans",
            "count": str(max_results + 5),
        }

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 NewsDigest/1.0"},
            ) as client:
                resp = await client.get(_BING_NEWS_RSS, params=params)
                resp.raise_for_status()
                raw_xml = resp.text
        except Exception as e:
            logger.error("Bing News RSS fetch failed for '%s': %s", keyword, e)
            return []

        try:
            feed = feedparser.parse(raw_xml)
        except Exception as e:
            logger.error("Bing News RSS parse failed for '%s': %s", keyword, e)
            return []

        items = self._parse_entries(feed.entries)
        items = self._clean(items, max_results)

        if items:
            logger.info(
                "BingNews: '%s' → %d items. Top3: %s",
                keyword, len(items),
                " | ".join(it.title[:30] for it in items[:3]),
            )
        else:
            logger.warning("BingNews: '%s' → 0 items", keyword)

        return items

    def _parse_entries(self, entries: list) -> list[NewsItem]:
        items: list[NewsItem] = []
        for entry in entries:
            title = self._strip_html(entry.get("title", "")).strip()
            snippet = self._strip_html(
                entry.get("description", entry.get("summary", ""))
            ).strip()
            url = entry.get("link", "")
            published_at = self._parse_date(entry.get("published"))
            source = entry.get("source", {}).get("title", "") if hasattr(entry, "source") else ""

            items.append(NewsItem(
                title=title,
                snippet=snippet,
                source=source,
                url=url,
                published_at=published_at,
            ))
        return items

    def _clean(self, items: list[NewsItem], max_results: int) -> list[NewsItem]:
        seen_titles: set[str] = set()
        seen_urls: set[str] = set()
        result: list[NewsItem] = []

        for item in items:
            title_key = item.title.strip().lower()
            if not title_key or title_key in seen_titles:
                continue
            if item.url and item.url in seen_urls:
                continue

            snippet = _NOISE_RE.sub("", item.snippet).strip()

            if len(snippet) < _MIN_SNIPPET_LEN:
                if len(item.title) >= _MIN_SNIPPET_LEN:
                    snippet = item.title
                else:
                    continue

            if len(snippet) > _MAX_SNIPPET_LEN:
                snippet = snippet[:_MAX_SNIPPET_LEN] + "…"

            seen_titles.add(title_key)
            if item.url:
                seen_urls.add(item.url)

            result.append(NewsItem(
                title=item.title,
                snippet=snippet,
                source=item.source,
                url=item.url,
                published_at=item.published_at,
            ))

            if len(result) >= max_results:
                break

        return result

    @staticmethod
    def _parse_date(date_str: str | None) -> datetime | None:
        if not date_str:
            return None
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            return None

    @staticmethod
    def _strip_html(text: str) -> str:
        return _HTML_TAG_RE.sub("", text).strip()
