"""
Google News RSS 搜索 Provider
无需 API Key，通过 Google News RSS Feed 按关键词抓取真实资讯。

RSS URL: https://news.google.com/rss/search?q={keyword}&hl=zh-CN&gl=CN&ceid=CN:zh-Hans

注意：Google News RSS 在部分地区可能需要代理访问。
"""

from __future__ import annotations

import re
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import feedparser
import httpx

from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem
from newsdigest.app.services.search.base import SearchProvider

logger = get_logger(__name__)

_GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
_MAX_SNIPPET_LEN = 200
_MIN_SNIPPET_LEN = 20

# HTML 标签清理
_HTML_TAG_RE = re.compile(r"<[^>]+>")
# 无意义尾部内容
_NOISE_RE = re.compile(r"(点击查看全文|展开全文|阅读原文|查看更多).*$")


class GoogleNewsProvider(SearchProvider):
    """
    通过 Google News RSS Feed 抓取真实资讯。
    每次请求携带 keyword，返回 Google News 的搜索结果。
    """

    @property
    def provider_name(self) -> str:
        return "google_news"

    async def search(self, keyword: str, max_results: int = 8) -> list[NewsItem]:
        # 尝试中文和英文两种 locale，取结果多的
        items = await self._fetch_rss(keyword, hl="zh-CN", gl="CN", ceid="CN:zh-Hans")

        if len(items) < 3:
            # 中文结果不足，尝试英文补充
            en_items = await self._fetch_rss(keyword, hl="en", gl="US", ceid="US:en")
            # 合并去重
            seen_urls = {it.url for it in items}
            for it in en_items:
                if it.url not in seen_urls:
                    items.append(it)
                    seen_urls.add(it.url)

        # 清洗 + 截取
        items = self._clean(items, max_results)

        # 日志
        if items:
            logger.info(
                "GoogleNews: '%s' → %d items. Top3: %s",
                keyword, len(items),
                " | ".join(it.title[:30] for it in items[:3]),
            )
        else:
            logger.warning("GoogleNews: '%s' → 0 items", keyword)

        return items

    async def _fetch_rss(
        self, keyword: str, hl: str, gl: str, ceid: str,
    ) -> list[NewsItem]:
        """请求 Google News RSS 并解析。"""
        params = {"q": keyword, "hl": hl, "gl": gl, "ceid": ceid}

        try:
            async with httpx.AsyncClient(
                timeout=15.0,
                follow_redirects=True,
                headers={"User-Agent": "Mozilla/5.0 NewsDigest/1.0"},
            ) as client:
                resp = await client.get(_GOOGLE_NEWS_RSS, params=params)
                resp.raise_for_status()
                raw_xml = resp.text
        except Exception as e:
            logger.error("GoogleNews RSS fetch failed for '%s' (hl=%s): %s", keyword, hl, e)
            return []

        try:
            feed = feedparser.parse(raw_xml)
        except Exception as e:
            logger.error("GoogleNews RSS parse failed for '%s': %s", keyword, e)
            return []

        items: list[NewsItem] = []
        for entry in feed.entries:
            title = self._strip_html(entry.get("title", "")).strip()
            snippet = self._strip_html(
                entry.get("description", entry.get("summary", ""))
            ).strip()
            url = entry.get("link", "")
            published_at = self._parse_date(entry.get("published"))

            # 提取来源（Google News RSS 格式：标题末尾 " - 来源名"）
            source = ""
            if hasattr(entry, "source") and isinstance(entry.source, dict):
                source = entry.source.get("title", "")
            # 无论 source 从哪来，都尝试从标题末尾剥离 " - 来源名"
            if " - " in title:
                candidate_source = title.rsplit(" - ", 1)[-1].strip()
                title = title.rsplit(" - ", 1)[0].strip()
                if not source:
                    source = candidate_source

            items.append(NewsItem(
                title=title,
                snippet=snippet,
                source=source,
                url=url,
                published_at=published_at,
            ))

        return items

    def _clean(self, items: list[NewsItem], max_results: int) -> list[NewsItem]:
        """清洗：去重、过滤、截断。"""
        seen_titles: set[str] = set()
        seen_urls: set[str] = set()
        result: list[NewsItem] = []

        for item in items:
            # 标题去重
            title_key = item.title.strip().lower()
            if not title_key or title_key in seen_titles:
                continue
            # URL 去重
            if item.url and item.url in seen_urls:
                continue

            # 清理 snippet
            snippet = _NOISE_RE.sub("", item.snippet).strip()

            # Google News RSS 的 description 经常就是标题重复
            # 如果 snippet 和标题高度重复，直接用标题+来源作为内容
            title_normalized = item.title.strip().lower()
            snippet_normalized = snippet.lower()
            if not snippet or snippet_normalized.startswith(title_normalized):
                source_str = f"（来源：{item.source}）" if item.source else ""
                snippet = item.title + source_str

            # 过滤内容过短
            if len(snippet) < _MIN_SNIPPET_LEN:
                if len(item.title) >= _MIN_SNIPPET_LEN:
                    snippet = item.title
                else:
                    continue

            # 截断过长
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
        text = _HTML_TAG_RE.sub("", text)
        # 清理 HTML 实体
        text = text.replace("&nbsp;", " ").replace("&amp;", "&")
        text = text.replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"')
        return text.strip()
