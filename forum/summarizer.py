from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from .crawler import extract_links
from .models import ForumArticle


@dataclass
class ForumSummary:
    summary: str
    tech_stack: list[str]
    scenarios: list[str]
    repo_links: list[str]
    key_points: list[str]


class ForumSummarizer:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config

    async def summarize(self, article: ForumArticle) -> ForumSummary:
        fallback = fallback_summary(article)
        provider_id = self.config._config_str("forum_summary_provider_id", "").strip()
        if not provider_id:
            return fallback
        text = article.raw_text or article.summary or article.title
        if not text:
            return fallback
        max_chars = max(1000, self.config._config_int("forum_summary_max_chars", 6000))
        prompt = build_summary_prompt(article, text[:max_chars])
        try:
            response = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
            data = parse_llm_json((getattr(response, "completion_text", "") or "").strip())
            if not isinstance(data, dict):
                return fallback
            repo_links = clean_list(data.get("repo_links")) or article.repo_links or extract_links(article.raw_text)
            return ForumSummary(
                summary=one_line(data.get("summary"))[:300] or fallback.summary,
                tech_stack=clean_list(data.get("tech_stack")),
                scenarios=clean_list(data.get("scenarios")),
                repo_links=repo_links[:8],
                key_points=clean_list(data.get("key_points"))[:8],
            )
        except Exception as exc:
            logger.warning(f"论坛文章 LLM 归纳失败：{exc}")
            return fallback


def build_summary_prompt(article: ForumArticle, text: str) -> str:
    return (
        "你是 RoboMaster 开源项目资料整理助手。请只根据给定论坛文章内容归纳，"
        "不要编造链接、仓库、功能或技术栈。返回严格 JSON，不要 Markdown。"
        "summary 不超过 300 字，key_points 每条不超过 40 字。"
        "JSON 格式："
        "{\"summary\":\"项目/文章摘要\","
        "\"tech_stack\":[\"技术栈\"],"
        "\"scenarios\":[\"适用场景\"],"
        "\"repo_links\":[\"仓库或资料链接\"],"
        "\"key_points\":[\"关键点\"]}"
        "\n\n"
        f"标题：{article.title}\n"
        f"作者：{article.author}\n"
        f"分类：{article.category}\n"
        f"发布时间：{article.posted_at}\n"
        f"链接：{article.url}\n\n"
        f"正文：\n{text}"
    )


def fallback_summary(article: ForumArticle) -> ForumSummary:
    links = article.repo_links or extract_links(article.raw_text)
    summary = article.summary or article.raw_text[:220] or "暂无正文摘要。"
    return ForumSummary(
        summary=one_line(summary)[:300],
        tech_stack=[],
        scenarios=[],
        repo_links=links[:8],
        key_points=[],
    )


def render_article_index_text(article: ForumArticle) -> str:
    lines = [
        f"标题：{article.title}",
        f"作者：{article.author}",
        f"分类：{article.category}",
        f"发布时间：{article.posted_at}",
        f"链接：{article.url}",
    ]
    if article.summary:
        lines.append(f"摘要：{article.summary}")
    if article.tech_stack:
        lines.append(f"技术栈：{'、'.join(article.tech_stack)}")
    if article.scenarios:
        lines.append(f"适用场景：{'、'.join(article.scenarios)}")
    if article.repo_links:
        lines.append(f"相关链接：{' '.join(article.repo_links)}")
    if article.key_points:
        lines.append(f"关键点：{'；'.join(article.key_points)}")
    if article.raw_text:
        lines.append(f"正文摘录：{article.raw_text[:1200]}")
    return "\n".join(line for line in lines if line and not line.endswith("："))


def parse_llm_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None
    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.I | re.S)
    if fence:
        candidates.insert(0, fence.group(1).strip())
    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    data, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                return data if isinstance(data, dict) else None
        else:
            return data if isinstance(data, dict) else None
    return None


def clean_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = re.split(r"[\n,，;；]+", value)
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = one_line(item)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def one_line(value: Any) -> str:
    return " ".join(str(value or "").split())
