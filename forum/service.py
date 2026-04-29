from __future__ import annotations

import asyncio
import json
import random
import time
from pathlib import Path
from typing import Any

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

try:
    from astrbot.api.event import AstrMessageEvent
except Exception:  # pragma: no cover
    AstrMessageEvent = Any

from ..core.storage import (
    plugin_forum_cookies_path,
    plugin_forum_db_path,
    plugin_forum_import_dir,
    plugin_forum_index_path,
)
from .crawler import DEFAULT_FORUM_URL, DEFAULT_USER_AGENT, ForumCrawler, ForumCrawlerSettings
from .models import ForumArticle, ForumArticleInput, ForumSearchHit, ForumSearchResponse
from .search_index import ForumSearchIndex
from .store import ForumArticleStore
from .summarizer import ForumSummarizer, render_article_index_text


NO_FORUM_RESULT_TEXT = "未在论坛开源资料库中找到相关内容，请换个关键词试试。"


class ForumService:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config
        self.store = ForumArticleStore(plugin_forum_db_path())
        self.index_path = plugin_forum_index_path()
        self.index = ForumSearchIndex.load(self.index_path)
        self.crawler = ForumCrawler()
        self.summarizer = ForumSummarizer(context, config)
        self.lock = asyncio.Lock()

    async def close(self) -> None:
        await self.crawler.close()

    async def check(self, *, notify: bool) -> list[ForumArticle]:
        async with self.lock:
            settings = self._crawler_settings()
            articles = await self.crawler.fetch_articles(settings)
            new_articles: list[ForumArticle] = []
            for item in articles:
                stored, inserted = self.store.upsert_article(item)
                if not inserted:
                    continue
                summarized = await self._summarize_and_store(stored)
                new_articles.append(summarized)
            if new_articles:
                await self.rebuild_index()
            return new_articles if notify else []

    async def import_jsonl(self) -> tuple[int, int]:
        async with self.lock:
            import_dir = plugin_forum_import_dir()
            import_dir.mkdir(parents=True, exist_ok=True)
            seen = 0
            inserted_count = 0
            for path in sorted(import_dir.glob("*.jsonl")):
                for line in path.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    seen += 1
                    try:
                        data = json.loads(line)
                        article_input = ForumArticleInput(
                            title=str(data.get("title") or ""),
                            url=str(data.get("url") or ""),
                            author=str(data.get("author") or ""),
                            category=str(data.get("category") or ""),
                            posted_at=str(data.get("posted_at") or ""),
                            raw_text=str(data.get("raw_text") or data.get("content") or ""),
                            detail_error=str(data.get("detail_error") or ""),
                            repo_links=[
                                str(item)
                                for item in data.get("repo_links", [])
                                if str(item).strip()
                            ]
                            if isinstance(data.get("repo_links"), list)
                            else [],
                        )
                    except Exception as exc:
                        logger.warning(f"论坛 JSONL 导入行解析失败 {path.name}: {exc}")
                        continue
                    if not article_input.title or not article_input.url:
                        continue
                    stored, inserted = self.store.upsert_article(article_input)
                    if inserted:
                        inserted_count += 1
                        await self._summarize_and_store(stored)
            if inserted_count:
                await self.rebuild_index()
            return seen, inserted_count

    async def rebuild_index(self) -> str:
        articles = self.store.all_articles()
        self.index = ForumSearchIndex.from_articles(articles)
        await asyncio.to_thread(self.index.save, self.index_path)
        return f"开源资料索引已重建\n文章：{len(articles)}\n可检索文档：{len(self.index.documents)}"

    async def search(self, query: str, event: AstrMessageEvent | None = None) -> ForumSearchResponse:
        if not self.index.documents:
            self.index = ForumSearchIndex.load(self.index_path)
        if not self.index.documents and self.store.article_count() > 0:
            await self.rebuild_index()

        max_results = max(1, self.config._config_int("forum_query_max_results", 5))
        hits = self.index.search(query, max_results=max_results)
        explanation = ""
        if hits and event is not None:
            selected, explanation = await self._select_with_llm(event, query, hits, max_results)
            if selected:
                hits = selected
        return ForumSearchResponse(query=query, hits=hits, explanation=explanation)

    def help_text(self) -> str:
        return (
            "开源查询用法：\n"
            "开源查询 关键词或问题\n"
            "示例：开源查询 自瞄\n"
            "示例：开源查询 电控代码\n"
            "示例：开源查询 视觉定位\n\n"
            "管理员可发送：RM开源检查、RM开源重建索引、RM开源导入"
        )

    def format_search_response(self, response: ForumSearchResponse) -> str:
        if not response.hits:
            return NO_FORUM_RESULT_TEXT
        lines = [f"开源查询：{response.query}"]
        if response.explanation:
            lines.append(f"简述：{response.explanation}")
        for index, hit in enumerate(response.hits, start=1):
            article = hit.article
            lines.extend(
                [
                    "",
                    f"{index}. {article.title}",
                    f"作者/分类：{article.author or '未知'} / {article.category or '未知'}",
                    f"发布时间：{article.posted_at or '未知'}",
                    f"摘要：{article.summary or hit.snippet}",
                ]
            )
            if article.tech_stack:
                lines.append(f"技术栈：{'、'.join(article.tech_stack)}")
            if article.scenarios:
                lines.append(f"适用场景：{'、'.join(article.scenarios)}")
            if article.repo_links:
                lines.append(f"相关链接：{' '.join(article.repo_links[:3])}")
            lines.append(f"论坛链接：{article.url}")
        return "\n".join(lines)

    def notification_text(self, article: ForumArticle) -> str:
        lines = [
            "RoboMaster 论坛开源内容更新",
            f"标题：{article.title}",
            f"作者/分类：{article.author or '未知'} / {article.category or '未知'}",
        ]
        if article.summary:
            lines.append(f"摘要：{article.summary}")
        if article.repo_links:
            lines.append(f"相关链接：{' '.join(article.repo_links[:3])}")
        lines.append(f"论坛链接：{article.url}")
        return "\n".join(lines)

    def article_count(self) -> int:
        return self.store.article_count()

    def scan_sleep_seconds(self) -> float:
        interval = max(30, self.config._config_int("forum_scan_interval_seconds", 300))
        return interval + random.uniform(0, min(30, interval * 0.1))

    async def _summarize_and_store(self, article: ForumArticle) -> ForumArticle:
        summary = await self.summarizer.summarize(article)
        self.store.update_summary(
            article.id,
            summary=summary.summary,
            tech_stack=summary.tech_stack,
            scenarios=summary.scenarios,
            repo_links=summary.repo_links,
            key_points=summary.key_points,
        )
        updated = self.store.get_article(article.id)
        return updated or article

    async def _select_with_llm(
        self,
        event: AstrMessageEvent,
        query: str,
        hits: list[ForumSearchHit],
        max_results: int,
    ) -> tuple[list[ForumSearchHit], str]:
        provider_id = await self._query_provider_id(event)
        if not provider_id:
            return [], ""
        candidates = "\n".join(
            f"[{idx}] {render_article_index_text(hit.article)}\n匹配片段：{hit.snippet}"
            for idx, hit in enumerate(hits, start=1)
        )
        prompt = (
            "你是 RoboMaster 开源项目检索助手。请只根据候选论坛文章选择最相关内容，"
            "不要编造候选之外的信息。返回严格 JSON，不要 Markdown。"
            f"最多选择 {max_results} 条。"
            "JSON 格式：{\"summary\":\"不超过80字的查询结论\","
            "\"items\":[{\"id\":候选编号}]}\n\n"
            f"用户问题：{query}\n\n候选文章：\n{candidates}"
        )
        try:
            response = await self.context.llm_generate(chat_provider_id=provider_id, prompt=prompt)
            text = (getattr(response, "completion_text", "") or "").strip()
            data = parse_llm_json(text)
            if not isinstance(data, dict):
                return [], ""
            selected: list[ForumSearchHit] = []
            seen: set[int] = set()
            for item in data.get("items", []):
                if not isinstance(item, dict):
                    continue
                try:
                    item_id = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if item_id < 1 or item_id > len(hits) or item_id in seen:
                    continue
                seen.add(item_id)
                selected.append(hits[item_id - 1])
            return selected, str(data.get("summary") or "").strip()
        except Exception as exc:
            logger.warning(f"论坛开源 LLM 查询选择失败：{exc}")
            return [], ""

    async def _query_provider_id(self, event: AstrMessageEvent) -> str | None:
        configured = self.config._config_str("forum_query_provider_id", "").strip()
        if configured:
            return configured
        getter = getattr(self.context, "get_current_chat_provider_id", None)
        if getter is None:
            return None
        try:
            result = getter(umo=event.unified_msg_origin)
        except TypeError:
            result = getter(event.unified_msg_origin)
        if hasattr(result, "__await__"):
            return await result
        return result

    def _crawler_settings(self) -> ForumCrawlerSettings:
        return ForumCrawlerSettings(
            article_url=self.config._config_str("forum_article_url", DEFAULT_FORUM_URL),
            username=self.config._config_str("forum_username", ""),
            password=self.config._config_str("forum_password", ""),
            cookies_path=self.config._config_str("forum_cookies_path", str(plugin_forum_cookies_path())),
            chromium_executable_path=self.config._config_str("forum_chromium_executable_path", ""),
            headless=self.config._config_bool("forum_headless", True),
            user_agent=self.config._config_str("forum_user_agent", DEFAULT_USER_AGENT),
            list_limit=max(1, self.config._config_int("forum_list_limit", 10)),
        )


def parse_llm_json(text: str) -> dict[str, Any] | None:
    from .summarizer import parse_llm_json as parse

    return parse(text)


def now_ts() -> int:
    return int(time.time())
