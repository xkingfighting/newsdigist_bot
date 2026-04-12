"""
Ollama 本地大模型摘要服务（v3）

核心原则：
1. 只允许基于输入内容总结，严禁编造
2. 关键词过滤：丢弃不含关键词的资讯，杜绝跨主题污染
3. 标题去重：相似标题只保留一条
4. 内容不足时明确告知，不强行生成
5. 输出结构化：编号事实 + 一句趋势
"""

from __future__ import annotations

import asyncio
import json
import re
from difflib import SequenceMatcher

import httpx

from newsdigest.app.core.config import settings
from newsdigest.app.core.logging import get_logger
from newsdigest.app.schemas.types import NewsItem

_ollama_semaphore: asyncio.Semaphore | None = None


def _get_ollama_sem() -> asyncio.Semaphore:
    global _ollama_semaphore
    if _ollama_semaphore is None:
        _ollama_semaphore = asyncio.Semaphore(5)
    return _ollama_semaphore


logger = get_logger(__name__)

# ─── Prompt ───

SUMMARIZE_PROMPT = """你是新闻编辑，不是AI助手。你的唯一任务是压缩下面的新闻条目。

【铁律】
- 只能使用下方提供的新闻内容，一个字也不能编造
- 禁止出现输入中不存在的公司名、人名、数字、产品名
- 禁止添加"近年来""业内人士""专家指出""市场规模"等泛化表达
- 禁止跨条目混合不同公司/不同事件
- 如果只有1-2条有效信息，就只总结这1-2条，不要凑字数

【输出格式（严格遵守）】
1️⃣ 第一条核心事实（一句话）
2️⃣ 第二条核心事实（一句话）
3️⃣ 第三条核心事实（一句话，如果有的话）

趋势：基于上述事实的一句话总结（不超过20字）

【约束】
- 总字数不超过150字
- 每条事实必须能在输入中找到原文依据
- 没有第三条就只写两条，不要硬凑

以下是关于「{keyword}」的新闻：

{news_content}

请直接按格式输出："""

# 兜底
FALLBACK_MESSAGE = "今日暂未检索到「{keyword}」的相关资讯，明天继续为你关注。"
INSUFFICIENT_MESSAGE = "当前关于「{keyword}」的有效资讯较少，暂无足够信息生成可靠摘要。"

# 模板化检测
_TEMPLATE_PHRASES = [
    "近日", "近年来", "业内人士", "专家指出", "专家表示",
    "市场规模预计", "行业将迎来", "业界普遍认为", "据权威机构",
    "引发广泛关注", "值得关注的是", "备受瞩目",
]

# 输入清洗
_NOISE_PATTERNS = [
    re.compile(r"点击查看全文.*", re.IGNORECASE),
    re.compile(r"展开全文.*", re.IGNORECASE),
    re.compile(r"阅读原文.*", re.IGNORECASE),
    re.compile(r"来源：.*$", re.MULTILINE),
    re.compile(r"责任编辑：.*$", re.MULTILINE),
    re.compile(r"\[.*?图片.*?\]"),
]

_MAX_SNIPPET_LENGTH = 200


class SummarizerService:

    def __init__(self) -> None:
        self._base_url = settings.ollama.base_url
        self._model = settings.ollama.model
        self._timeout = settings.ollama.timeout

    # ─── 主入口 ───

    async def summarize(self, keyword: str, items: list[NewsItem]) -> str:
        if not items:
            return FALLBACK_MESSAGE.format(keyword=keyword)

        # Step 1: 关键词过滤 — 只保留与关键词相关的条目
        relevant = self._filter_by_keyword(items, keyword)
        logger.info(
            "Keyword filter '%s': %d → %d items",
            keyword, len(items), len(relevant),
        )

        # Step 2: 去重（标题相似度 > 80%）
        deduped = self._dedup_by_similarity(relevant)

        # Step 3: 清洗、截断
        cleaned = self._clean_items(deduped)

        # Step 5: 兜底检查
        if len(cleaned) < 2:
            return INSUFFICIENT_MESSAGE.format(keyword=keyword)

        # 限量
        cleaned = cleaned[:6]

        # Step 4: 构建输入 → 调用模型
        news_content = self._build_input(cleaned)
        prompt = SUMMARIZE_PROMPT.format(keyword=keyword, news_content=news_content)

        logger.info("Calling Ollama '%s' for '%s' (%d items)", self._model, keyword, len(cleaned))

        try:
            summary = await self._call_ollama(prompt, temperature=0.2)
            summary = self._clean_output(summary)

            if not summary:
                return INSUFFICIENT_MESSAGE.format(keyword=keyword)

            # 模板化检测 → retry
            if self._is_templated(summary):
                logger.info("Template detected for '%s', retrying", keyword)
                retry_prompt = prompt + "\n\n【再次提醒】严禁使用'近日''专家''业内人士'等词，只提取原文事实。"
                retry_summary = await self._call_ollama(retry_prompt, temperature=0.15)
                retry_summary = self._clean_output(retry_summary)
                if retry_summary:
                    summary = retry_summary

            # 验证：检查输出是否提及了不存在于输入中的公司名（基础幻觉检测）
            summary = self._hallucination_check(summary, cleaned, keyword)

            return summary

        except Exception as e:
            logger.error("Ollama summarize failed for '%s': %s", keyword, e)
            return FALLBACK_MESSAGE.format(keyword=keyword)

    # ─── Step 1: 关键词过滤 ───

    @staticmethod
    def _filter_by_keyword(items: list[NewsItem], keyword: str) -> list[NewsItem]:
        """只保留标题或内容前100字包含关键词的条目。"""
        kw_lower = keyword.lower()
        # 中文关键词不转 lower（无意义），英文关键词忽略大小写
        result: list[NewsItem] = []
        for item in items:
            title = item.title.lower()
            content_head = item.snippet[:100].lower()
            if kw_lower in title or kw_lower in content_head:
                result.append(item)
        return result

    # ─── Step 2: 标题相似度去重 ───

    @staticmethod
    def _dedup_by_similarity(items: list[NewsItem], threshold: float = 0.8) -> list[NewsItem]:
        """标题相似度 > threshold 的只保留第一条。"""
        result: list[NewsItem] = []
        for item in items:
            is_dup = False
            for kept in result:
                ratio = SequenceMatcher(None, item.title, kept.title).ratio()
                if ratio > threshold:
                    is_dup = True
                    break
            if not is_dup:
                result.append(item)
        return result

    # ─── Step 3: 清洗 ───

    @staticmethod
    def _clean_items(items: list[NewsItem]) -> list[NewsItem]:
        result: list[NewsItem] = []
        for item in items:
            snippet = item.snippet.strip()
            for pattern in _NOISE_PATTERNS:
                snippet = pattern.sub("", snippet)
            snippet = snippet.strip()

            if not snippet or len(snippet) < 10:
                continue
            if len(snippet) > _MAX_SNIPPET_LENGTH:
                snippet = snippet[:_MAX_SNIPPET_LENGTH] + "…"

            result.append(NewsItem(
                title=item.title.strip(),
                snippet=snippet,
                source=item.source,
                url=item.url,
                published_at=item.published_at,
            ))
        return result

    # ─── 构建模型输入 ───

    @staticmethod
    def _build_input(items: list[NewsItem]) -> str:
        parts: list[str] = []
        for i, item in enumerate(items, 1):
            source_tag = f"（{item.source}）" if item.source else ""
            parts.append(f"[{i}] {item.title}{source_tag}\n{item.snippet}")
        return "\n\n".join(parts)

    # ─── 输出清洗 ───

    @staticmethod
    def _clean_output(text: str) -> str:
        if not text:
            return ""
        text = text.strip()
        for prefix in ("摘要：", "摘要如下：", "总结如下：", "以下是摘要：", "总结："):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        # 去 markdown
        text = re.sub(r"[*#_`]", "", text)
        # 去多余空行
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    # ─── 模板化检测 ───

    @staticmethod
    def _is_templated(text: str) -> bool:
        count = sum(1 for phrase in _TEMPLATE_PHRASES if phrase in text)
        # 命中 2 个以上才判定（单个可能是原文引用）
        return count >= 2

    # ─── 幻觉检测（基础版） ───

    @staticmethod
    def _hallucination_check(summary: str, items: list[NewsItem], keyword: str) -> str:
        """
        检查摘要中是否出现了输入中完全不存在的实体。
        如果检测到明显幻觉，返回安全的纯提取版本。
        """
        # 收集输入中出现过的所有文本
        all_input_text = keyword.lower()
        for item in items:
            all_input_text += " " + item.title.lower() + " " + item.snippet.lower()

        # 检查摘要中的中文引号内容是否在输入中有依据
        quoted = re.findall(r"\u300c(.+?)\u300d|\u201c(.+?)\u201d", summary)
        for groups in quoted:
            for q in groups:
                if q and len(q) > 2 and q.lower() not in all_input_text:
                    logger.warning("Hallucination detected: '%s' not in input, using safe fallback", q)
                    # 回退到安全的纯标题列表
                    titles = [f"· {item.title}" for item in items[:5]]
                    return f"「{keyword}」今日资讯要点：\n" + "\n".join(titles)

        return summary

    # ─── Ollama 调用 ───

    async def _call_ollama(self, prompt: str, temperature: float = 0.2) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.8,
                "num_predict": 350,
            },
        }

        async with _get_ollama_sem():
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.post(
                    f"{self._base_url}/generate",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()

            return data.get("response", "")

    # ─── 序列化 ───

    @staticmethod
    def items_to_json(items: list[NewsItem]) -> str:
        data = []
        for item in items:
            data.append({
                "title": item.title,
                "snippet": item.snippet,
                "source": item.source,
                "url": item.url,
                "published_at": item.published_at.isoformat() if item.published_at else None,
            })
        return json.dumps(data, ensure_ascii=False)
