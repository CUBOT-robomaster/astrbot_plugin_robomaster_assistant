from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Callable

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .embedding_retriever import ManualEmbeddingRetriever
from .models import LocatedResult
from .search_engine import ManualPage, ManualSearchIndex, SearchResult


class ManualLlmService:
    def __init__(
        self,
        context: Any,
        config: Any,
        index_getter: Callable[[], ManualSearchIndex],
    ):
        self.context = context
        self.config = config
        self._index_getter = index_getter
        self.embedding = ManualEmbeddingRetriever(context, config)

    @property
    def index(self) -> ManualSearchIndex:
        return self._index_getter()

    async def search_candidates(
        self,
        event: AstrMessageEvent,
        query: str,
        candidate_count: int,
    ) -> list[SearchResult]:
        retrieval_mode = self.retrieval_mode()
        snippet_chars = self.config._config_int("llm_candidate_chars", 600)
        min_score = self.config._config_float("min_score", 0.6)
        rewrite_queries: list[str] = []
        if retrieval_mode != "keyword" and self.config._config_bool("enable_llm_explain", True) and self.config._config_bool(
            "enable_query_rewrite",
            True,
        ):
            rewrite_queries = await self.rewrite_queries(event, query)

        queries = [query, *rewrite_queries]
        vector_enabled = retrieval_mode in {"auto", "hybrid"} and self.config._config_bool(
            "enable_vector_search",
            True,
        )
        embedding_enabled = retrieval_mode in {"auto", "hybrid"} and self.config._config_bool(
            "enable_embedding_search",
            False,
        )
        per_query_limit = max(
            candidate_count,
            self.config._config_int("query_rewrite_result_limit", 12),
        )
        vector_limit = max(
            candidate_count,
            self.config._config_int("vector_result_limit", 12),
        )
        vector_min_score = self.config._config_float("vector_min_score", 0.05)
        index = self.index
        result_lists = await asyncio.to_thread(
            _search_candidates_sync,
            index,
            queries,
            vector_enabled,
            candidate_count,
            snippet_chars,
            min_score,
            per_query_limit,
            vector_limit,
            vector_min_score,
        )
        if embedding_enabled:
            embedding_limit = max(
                candidate_count,
                self.config._config_int("embedding_result_limit", 12),
            )
            embedding_min_score = self.config._config_float("embedding_min_score", 0.25)
            embedding_results = await self.embedding.search(
                index,
                query,
                max_results=embedding_limit,
                snippet_chars=snippet_chars,
                min_score=embedding_min_score,
            )
            if embedding_results:
                result_lists.append(embedding_results)

        return merge_search_results_rrf(result_lists, candidate_count)

    async def rewrite_queries(
        self,
        event: AstrMessageEvent,
        query: str,
    ) -> list[str]:
        limit = max(0, self.config._config_int("query_rewrite_count", 4))
        if limit <= 0:
            return []
        try:
            provider_id = await self.provider_id_for(event, "query_rewrite_provider_id")
            if not provider_id:
                return []

            prompt = (
                "你是 RoboMaster 规则手册检索查询改写助手。"
                "请将用户问题改写为适合 BM25 关键词检索的中文查询词。"
                "只提取和补充规则手册中可能出现的专业术语、同义表达、接口名、模块名，"
                "不要回答问题，不要编造具体规则数值。"
                f"返回严格 JSON，不要 Markdown，格式为：{{\"queries\":[\"查询1\",\"查询2\"]}}。"
                f"最多返回 {limit} 条。\n\n"
                "示例：用户问题：电源怎么接\n"
                "{\"queries\":[\"供电接口 连接方式\",\"电源接线 规范\",\"底盘供电 接口定义\"]}\n\n"
                f"用户问题：{query}"
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            text = (getattr(llm_resp, "completion_text", "") or "").strip()
            return parse_rewritten_queries(text, query, limit)
        except Exception as exc:
            logger.warning(f"规则手册查询改写失败：{exc}")
            return []

    def retrieval_mode(self) -> str:
        mode = self.config._config_str("retrieval_mode", "auto").strip().lower()
        if mode not in {"auto", "hybrid", "full_llm", "keyword"}:
            return "auto"
        return mode

    async def locate_with_full_manual_llm(
        self,
        event: AstrMessageEvent,
        query: str,
    ) -> tuple[list[LocatedResult], str]:
        try:
            provider_id = await self.provider_id_for(event, "full_manual_provider_id")
            if not provider_id:
                return [], ""

            manual_context, pages = self.build_full_manual_context(
                self.config._config_int("full_manual_max_chars", 500000)
            )
            if not manual_context or not pages:
                return [], ""

            prompt = (
                "你是 RoboMaster 规则手册全文检索助手。下面给出按页编号的规则手册全文片段。"
                "请只根据这些原文回答用户问题，不要编造原文之外的规则。"
                "请返回严格 JSON，不要 Markdown，不要额外解释。"
                "每条依据必须选择一个页面 id，并给出直接来自该页原文的 quote。"
                "JSON 格式："
                "{\"summary\":\"不超过80字的简短结论；依据不足则说明不足\","
                "\"items\":[{\"id\":页面编号,\"quote\":\"页面原文中的定位短句\"}]}"
                "\n\n"
                f"用户问题：{query}\n\n规则手册全文页：\n{manual_context}"
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            text = (getattr(llm_resp, "completion_text", "") or "").strip()
            data = parse_llm_json(text)
            if not isinstance(data, dict):
                return [], ""

            items = data.get("items", [])
            if not isinstance(items, list):
                return [], ""

            located: list[LocatedResult] = []
            seen_ids: set[int] = set()
            for rank, item in enumerate(items, start=1):
                if not isinstance(item, dict):
                    continue
                try:
                    item_id = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                quote = str(item.get("quote", "") or "").strip()
                if not quote or item_id < 1 or item_id > len(pages) or item_id in seen_ids:
                    continue
                page = pages[item_id - 1]
                if not quote_matches_text(quote, page.text):
                    continue
                seen_ids.add(item_id)
                located.append(
                    LocatedResult(
                        SearchResult(
                            file_name=page.file_name,
                            file_path=page.file_path,
                            page_number=page.page_number,
                            snippet=quote,
                            score=1.0 / rank,
                        ),
                        quote,
                    )
                )

            summary = str(data.get("summary", "") or "").strip()
            return located, summary
        except Exception as exc:
            logger.warning(f"规则手册全文 LLM 检索失败：{exc}")
            return [], ""

    def build_full_manual_context(self, max_chars: int) -> tuple[str, list[ManualPage]]:
        max_chars = max(1000, max_chars)
        chunks: list[str] = []
        pages: list[ManualPage] = []
        used_chars = 0

        for page in self.index.pages:
            text = " ".join(str(page.text or "").split())
            if not text:
                continue
            item_id = len(pages) + 1
            header = f"[{item_id}] 文件：{page.file_name}；页码：{page.page_number}\n原文："
            block = f"{header}{text}\n"
            remaining = max_chars - used_chars
            if remaining <= len(header) + 20:
                logger.info("规则手册全文 LLM 上下文达到长度上限，已截断后续页面。")
                break
            if len(block) > remaining:
                block = f"{header}{text[: max(0, remaining - len(header) - 1)]}\n"
                chunks.append(block)
                pages.append(page)
                logger.info("规则手册全文 LLM 上下文达到长度上限，已截断当前页面。")
                break
            chunks.append(block)
            pages.append(page)
            used_chars += len(block)

        return "\n".join(chunks), pages

    def full_manual_context_fits_budget(self, max_chars: int) -> bool:
        max_chars = max(1000, max_chars)
        used_chars = 0
        item_id = 0

        for page in self.index.pages:
            text = " ".join(str(page.text or "").split())
            if not text:
                continue
            item_id += 1
            header = f"[{item_id}] 文件：{page.file_name}；页码：{page.page_number}\n原文："
            block_length = len(f"{header}{text}\n")
            used_chars += block_length
            if used_chars > max_chars:
                return False

        return item_id > 0

    async def locate_with_llm(
        self,
        event: AstrMessageEvent,
        query: str,
        candidates: list[SearchResult],
        max_results: int,
    ) -> tuple[list[LocatedResult], str]:
        try:
            provider_id = await self.provider_id_for(event, "evidence_provider_id")
            if not provider_id:
                return [], ""

            evidence = "\n".join(
                f"[{idx}] 文件：{item.file_name}；页码：{item.page_number}；原文：{item.snippet}"
                for idx, item in enumerate(candidates, start=1)
            )
            prompt = (
                "你是 RoboMaster 规则手册定位助手。候选原文页来自原始问题和语义改写查询的混合召回。"
                "请只根据候选原文页判断用户问题最相关的依据。"
                "不要编造候选之外的规则。请返回严格 JSON，不要 Markdown，不要额外解释。"
                f"请选择所有必须作为依据的候选页，最多 {max_results} 条。"
                "不要为了凑数量选择弱相关内容；优先选择正文规则页，避免目录、版权页、修改日志页，"
                "除非用户明确询问目录/版本/修订。"
                "每条依据的 quote 必须直接来自候选原文，用于截图定位，尽量选择包含答案的短句或表格行。"
                "JSON 格式："
                "{\"summary\":\"不超过80字的简短结论；依据不足则说明不足\","
                "\"items\":[{\"id\":候选编号,\"quote\":\"候选原文中的定位短句\"}]}"
                "示例1：{\"summary\":\"电源接口应按供电接口定义连接。\","
                "\"items\":[{\"id\":1,\"quote\":\"供电接口定义\"}]}"
                "示例2：{\"summary\":\"候选原文不足以支持进一步解释。\",\"items\":[]}"
                "\n\n"
                f"用户问题：{query}\n\n候选原文页：\n{evidence}"
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            text = (getattr(llm_resp, "completion_text", "") or "").strip()
            data = parse_llm_json(text)
            if not data:
                return [], ""

            located: list[LocatedResult] = []
            seen_ids: set[int] = set()
            for item in data.get("items", []):
                if not isinstance(item, dict):
                    continue
                try:
                    item_id = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if item_id < 1 or item_id > len(candidates) or item_id in seen_ids:
                    continue
                quote = str(item.get("quote", "") or "").strip()
                if not quote or not quote_matches_text(quote, candidates[item_id - 1].snippet):
                    continue
                seen_ids.add(item_id)
                located.append(LocatedResult(candidates[item_id - 1], quote))
                if len(located) >= max_results:
                    break

            summary = str(data.get("summary", "") or "").strip()
            return located, summary
        except Exception as exc:
            logger.warning(f"规则手册 LLM 定位失败：{exc}")
            return [], ""

    async def get_current_provider_id(self, event: AstrMessageEvent) -> str | None:
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

    async def provider_id_for(self, event: AstrMessageEvent, config_key: str) -> str | None:
        configured = self.config._config_str(config_key, "").strip()
        if configured:
            return configured
        return await self.get_current_provider_id(event)

    def candidate_count(self, max_results: int, enable_llm: bool) -> int:
        if enable_llm:
            return max(1, self.config._config_int("llm_candidate_pages", 10))
        return max(1, max_results)

    def result_limit(self, max_results: int, candidate_count: int) -> int:
        if not self.config._config_bool("llm_select_all_evidence", True):
            return max(1, max_results)

        llm_max_results = self.config._config_int("llm_max_results", 0)
        if llm_max_results > 0:
            return max(1, min(llm_max_results, candidate_count))
        return max(1, candidate_count)


def _search_candidates_sync(
    index: ManualSearchIndex,
    queries: list[str],
    vector_enabled: bool,
    candidate_count: int,
    snippet_chars: int,
    min_score: float,
    per_query_limit: int,
    vector_limit: int,
    vector_min_score: float,
) -> list[list[SearchResult]]:
    if len(queries) == 1 and not vector_enabled:
        return [
            index.search(
                queries[0],
                max_results=candidate_count,
                snippet_chars=snippet_chars,
                min_score=min_score,
            )
        ]

    result_lists: list[list[SearchResult]] = []
    for item in queries:
        result_lists.append(
            index.search(
                item,
                max_results=per_query_limit,
                snippet_chars=snippet_chars,
                min_score=min_score,
            )
        )

    if vector_enabled:
        for item in queries:
            result_lists.append(
                index.vector_search(
                    item,
                    max_results=vector_limit,
                    snippet_chars=snippet_chars,
                    min_score=vector_min_score,
                )
            )

    return result_lists


def parse_rewritten_queries(text: str, original_query: str, limit: int) -> list[str]:
    data = parse_llm_json(text)
    if not isinstance(data, dict):
        return []
    raw_queries = data.get("queries")
    if not isinstance(raw_queries, list):
        return []

    original_key = query_dedupe_key(original_query)
    seen = {original_key}
    queries: list[str] = []
    for item in raw_queries:
        query = " ".join(str(item or "").split())
        key = query_dedupe_key(query)
        if not query or not key or key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= limit:
            break
    return queries


def query_dedupe_key(query: str) -> str:
    return " ".join(str(query or "").lower().split())


def merge_search_results_rrf(
    result_lists: list[list[SearchResult]],
    max_results: int,
) -> list[SearchResult]:
    scores: dict[tuple[str, int], float] = {}
    merged: dict[tuple[str, int], SearchResult] = {}
    rrf_k = 60

    for results in result_lists:
        for rank, result in enumerate(results, start=1):
            key = (result.file_path, result.page_number)
            scores[key] = scores.get(key, 0.0) + 1.0 / (rrf_k + rank)
            if key not in merged:
                merged[key] = SearchResult(
                    file_name=result.file_name,
                    file_path=result.file_path,
                    page_number=result.page_number,
                    snippet=result.snippet,
                    score=0.0,
                )

    for key, score in scores.items():
        merged[key].score = score

    ranked = sorted(
        merged.values(),
        key=lambda item: item.score,
        reverse=True,
    )
    return ranked[: max(1, max_results)]


def parse_llm_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    candidates = [text]
    fence_match = re.search(r"```(?:json)?\s*(.*?)```", text, re.S | re.I)
    if fence_match:
        candidates.insert(0, fence_match.group(1).strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            pass
        else:
            return data if isinstance(data, dict) else None

        for index, char in enumerate(candidate):
            if char != "{":
                continue
            try:
                data, _ = decoder.raw_decode(candidate[index:])
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict):
                return data
    return None


def quote_matches_text(quote: str, text: str) -> bool:
    normalized_quote = normalize_quote_for_match(quote)
    normalized_text = normalize_quote_for_match(text)
    if not normalized_quote or not normalized_text:
        return False
    if normalized_quote in normalized_text:
        return True
    return normalized_quote.replace(" ", "") in normalized_text.replace(" ", "")


def normalize_quote_for_match(text: str) -> str:
    return " ".join(str(text or "").split()).lower()
