"""
Ollama 本地大模型摘要服务（v4 — 产品级调优）

核心变化：
- Prompt 改为受控压缩，禁止自由发挥
- 去掉"趋势"字段，只输出事实摘要
- 输出为单段自然语言，不编号
- temperature 0.15 / top_p 0.75 极度收敛
- 模板化检测 + 幻觉检测保留
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

SUMMARIZE_PROMPT = """你是资讯编辑。把下面的新闻压缩成一段话。

铁律：
1. 只用输入中已有的事实
2. 围绕一个主线写，最多补充一条其他信息
3. 非顶级媒体来源的重大消息（发布/收购/融资/销量数字），必须用"有消息称""据报道"等不确定语气
4. 禁止"近日/业内人士/专家指出/备受瞩目"
5. "同时/此外/另外"只能出现一次
6. 不要出现与「{keyword}」无关的公司或品牌
7. 100~120字，单段，不分点，不编号，不加标题

关于「{keyword}」：

{news_content}

摘要："""

# 兜底
FALLBACK_MESSAGE = "今日暂未检索到「{keyword}」的相关资讯，明天继续为你关注。"
INSUFFICIENT_MESSAGE = "当前关于「{keyword}」的高质量资讯较少，暂无足够信息生成可靠摘要。"

# 模板化检测
_TEMPLATE_PHRASES = [
    "近日", "近年来", "近期", "业内人士", "专家指出", "专家表示", "专家认为",
    "市场规模预计", "行业将迎来", "业界普遍认为", "据权威机构",
    "引发广泛关注", "值得关注的是", "备受瞩目",
    "多项重大进展", "信心爆棚", "引发热潮",
]

_MAX_SNIPPET_LENGTH = 200

_OLLAMA_MAX_ATTEMPTS = 3
_OLLAMA_RETRY_BACKOFF = 5.0
_OLLAMA_RETRYABLE_EXC = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ReadError,
)


class SummarizerService:

    def __init__(self) -> None:
        self._base_url = settings.ollama.base_url
        self._model = settings.ollama.model
        self._timeout = settings.ollama.timeout

    # ─── 主入口 ───

    async def summarize(self, keyword: str, items: list[NewsItem]) -> str:
        """
        接收已过滤+评分后的高质量条目，生成摘要。
        本方法不再做关键词过滤（由上游 DigestService 完成）。
        """
        if not items:
            return FALLBACK_MESSAGE.format(keyword=keyword)

        # 去重（标题相似度 > 80%）
        deduped = self._dedup_by_similarity(items)

        if len(deduped) < 2:
            return INSUFFICIENT_MESSAGE.format(keyword=keyword)

        # 来源多样性检查：至少 2 个不同来源
        sources = {(it.source or "").strip().lower() for it in deduped if it.source}
        if len(sources) < 2 and len(deduped) >= 3:
            logger.warning("Only %d source(s) for '%s', proceeding with caution", len(sources), keyword)

        # 限量 + 构建输入
        deduped = deduped[:5]
        news_content = self._build_input(deduped)
        prompt = SUMMARIZE_PROMPT.format(keyword=keyword, news_content=news_content)

        logger.info("Calling Ollama '%s' for '%s' (%d items)", self._model, keyword, len(deduped))

        try:
            summary = await self._call_ollama(prompt, temperature=0.15)
            summary = self._clean_output(summary)

            if not summary:
                return INSUFFICIENT_MESSAGE.format(keyword=keyword)

            # 模板化检测 → retry
            if self._is_templated(summary):
                logger.info("Template detected for '%s', retrying", keyword)
                retry_prompt = prompt + "\n\n【警告】你的上一次输出包含模板话术。请只提取原文中的具体事实，不要添加任何总结性、评价性语句。"
                retry_summary = await self._call_ollama(retry_prompt, temperature=0.1)
                retry_summary = self._clean_output(retry_summary)
                if retry_summary:
                    summary = retry_summary

            # 幻觉检测
            summary = self._hallucination_check(summary, deduped, keyword)

            # 高风险语气降级（后处理）
            summary = self._downgrade_risky_tone(summary)

            # 实体一致性：删除与关键词无关的句子
            summary = self._entity_consistency(summary, keyword)

            return summary

        except Exception as e:
            logger.error("Ollama summarize failed for '%s': %s", keyword, e)
            return FALLBACK_MESSAGE.format(keyword=keyword)

    # ─── 标题相似度去重 ───

    @staticmethod
    def _dedup_by_similarity(items: list[NewsItem], threshold: float = 0.8) -> list[NewsItem]:
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

    # ─── 构建模型输入 ───

    @staticmethod
    def _build_input(items: list[NewsItem]) -> str:
        """只给模型标题 + 核心事实 + 来源，不灌杂乱正文。"""
        parts: list[str] = []
        for i, item in enumerate(items, 1):
            source_tag = f"（来源：{item.source}）" if item.source else ""
            # 截断 snippet，只保留核心部分
            snippet = item.snippet.strip()
            if len(snippet) > _MAX_SNIPPET_LENGTH:
                snippet = snippet[:_MAX_SNIPPET_LENGTH] + "…"
            parts.append(f"[{i}] {item.title} {source_tag}\n{snippet}")
        return "\n\n".join(parts)

    # ─── 输出清洗 ───

    @staticmethod
    def _clean_output(text: str) -> str:
        if not text:
            return ""
        text = text.strip()
        # 去常见前缀
        for prefix in ("摘要：", "摘要如下：", "总结如下：", "以下是摘要：", "总结："):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        # 去末尾 (XX字) / （XX字）/ (约XX字) 等字数标注（qwen 模型常见行为）
        text = re.sub(r"[（(]\s*(?:约|共)?\s*\d+\s*字\s*[）)]?\s*$", "", text)
        text = re.sub(r"[（(]\s*(?:约|共)?\s*\d+\s*(?:个字|字符|words)\s*[）)]?\s*$", "", text, flags=re.IGNORECASE)
        # 去 markdown / emoji
        text = re.sub(r"[*#_`]", "", text)
        text = re.sub(r"[\U0001f300-\U0001f9ff]", "", text)
        # 去编号格式（如果模型仍然输出了编号）
        text = re.sub(r"^[1-9][️⃣]?\s*", "", text, flags=re.MULTILINE)
        text = re.sub(r"^[①②③④⑤]\s*", "", text, flags=re.MULTILINE)
        # 去"趋势："行（如果模型仍然输出了）
        text = re.sub(r"趋势[：:].+$", "", text, flags=re.MULTILINE)
        # 去多余空行，合并为单段
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        text = "；".join(lines) if len(lines) > 1 else (lines[0] if lines else "")
        # 确保以句号结尾
        if text and text[-1] not in ("。", ".", "；"):
            text += "。"
        return text.strip()

    # ─── 模板化检测 ───

    @staticmethod
    def _is_templated(text: str) -> bool:
        count = sum(1 for phrase in _TEMPLATE_PHRASES if phrase in text)
        return count >= 2

    # ─── 幻觉检测 ───

    @staticmethod
    def _hallucination_check(summary: str, items: list[NewsItem], keyword: str) -> str:
        all_input_text = keyword.lower()
        for item in items:
            all_input_text += " " + item.title.lower() + " " + item.snippet.lower()

        quoted = re.findall(r"\u300c(.+?)\u300d|\u201c(.+?)\u201d", summary)
        for groups in quoted:
            for q in groups:
                if q and len(q) > 2 and q.lower() not in all_input_text:
                    logger.warning("Hallucination detected: '%s' not in input", q)
                    titles = [f"· {item.title}" for item in items[:5]]
                    return f"{keyword}今日资讯要点：\n" + "\n".join(titles)

        return summary

    # ─── 高风险语�����级 ───

    @staticmethod
    def _downgrade_risky_tone(text: str) -> str:
        """
        将确定语气的高风险表述降级为不确定���气。
        例："苹果将发布" → "有消息称苹果将发布"
        只处理没有保护性前缀的句子。
        """
        # 已经有保护性前缀的不处理
        _safe_prefixes = ("有消���称", "据报道", "据悉", "市场消息显示", "媒体报道称")

        # 需要降级的高风险动词/短语
        _risky_patterns = [
            (re.compile(r"(?<!据报道)(?<!有消息称)(?<!据悉)(确认发布|确认推出|即将发布|即将推出)"), r"据报道\1"),
            (re.compile(r"(?<!据报道)(?<!有消息称)(首款|首个|全球首)"), r"据报道为\1"),
            (re.compile(r"(?<!据报道)(?<!有消息称)(将解决|将实现|将突破)"), r"有望\1".replace("将", "")),
        ]

        for pattern, replacement in _risky_patterns:
            if any(p in text for p in _safe_prefixes):
                break  # 整段已有保护前缀，不再处理
            new_text = pattern.sub(replacement, text)
            if new_text != text:
                logger.info("TONE downgraded: %s", pattern.pattern)
                text = new_text

        return text

    # ─── 实体一致���检查 ───

    @staticmethod
    def _entity_consistency(summary: str, keyword: str) -> str:
        """
        检查摘要中按分号/句号分割的各个分句，
        如果某分句完全不包含关键词且不像补充信息，则删除。
        """
        kw_lower = keyword.lower()
        # 按分号或句号切句
        parts = re.split(r"[；;。]", summary)
        parts = [p.strip() for p in parts if p.strip()]

        if len(parts) <= 1:
            return summary  # 只有一句，不处理

        kept: list[str] = []
        removed = 0
        for i, part in enumerate(parts):
            part_lower = part.lower()
            # 第一句（主线）始终保留
            if i == 0:
                kept.append(part)
                continue
            # 包含关键词，保留
            if kw_lower in part_lower:
                kept.append(part)
                continue
            # 不含关键词但是短补充（< 25 字），保留（可能是紧接上文的补充）
            if len(part) < 25:
                kept.append(part)
                continue
            # 否则删除
            logger.info("ENTITY removed off-topic clause: %s", part[:30])
            removed += 1

        if not kept:
            return summary

        result = "；".join(kept)
        if result and result[-1] not in ("。", "；"):
            result += "。"
        return result

    # ─── Ollama 调用 ───

    async def _call_ollama(self, prompt: str, temperature: float = 0.15) -> str:
        payload = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "top_p": 0.75,
                "num_predict": 300,
            },
        }

        async with _get_ollama_sem():
            last_exc: Exception | None = None
            for attempt in range(1, _OLLAMA_MAX_ATTEMPTS + 1):
                try:
                    # trust_env=False: Ollama 是本地服务，绕过 macOS 系统代理
                    async with httpx.AsyncClient(timeout=self._timeout, trust_env=False) as client:
                        resp = await client.post(
                            f"{self._base_url}/generate",
                            json=payload,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                    return data.get("response", "")
                except httpx.HTTPStatusError as e:
                    # 4xx 客户端错误重试无意义
                    if not (500 <= e.response.status_code < 600):
                        raise
                    last_exc = e
                except _OLLAMA_RETRYABLE_EXC as e:
                    last_exc = e

                if attempt < _OLLAMA_MAX_ATTEMPTS:
                    logger.warning(
                        "Ollama attempt %d/%d failed (%s: %s), retrying in %.1fs",
                        attempt, _OLLAMA_MAX_ATTEMPTS,
                        type(last_exc).__name__, last_exc,
                        _OLLAMA_RETRY_BACKOFF,
                    )
                    await asyncio.sleep(_OLLAMA_RETRY_BACKOFF)

            assert last_exc is not None
            raise last_exc

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
