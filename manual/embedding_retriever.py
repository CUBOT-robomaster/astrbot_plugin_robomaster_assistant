from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ..core.storage import plugin_data_dir
from .search_engine import ManualPage, ManualSearchIndex, SearchResult, tokenize


EMBEDDING_CACHE_VERSION = 1


class ManualEmbeddingRetriever:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config
        self._lock = asyncio.Lock()

    async def search(
        self,
        index: ManualSearchIndex,
        query: str,
        *,
        max_results: int,
        snippet_chars: int,
        min_score: float,
    ) -> list[SearchResult]:
        if not self.config._config_bool("enable_embedding_search", False):
            return []
        if not query or not index.pages:
            return []

        provider = await self._provider()
        if provider is None:
            return []

        try:
            page_vectors = await self._page_vectors(index, provider)
            query_vector = _normalize_vector(await provider.get_embedding(query))
        except Exception as exc:
            logger.warning(f"规则手册嵌入检索失败：{exc}")
            return []

        if not query_vector:
            return []

        query_tokens = tokenize(query)
        results: list[SearchResult] = []
        for idx, page in enumerate(index.pages):
            page_vector = page_vectors.get(_page_key(page))
            if not page_vector:
                continue
            score = _cosine_similarity(query_vector, page_vector)
            score *= ManualSearchIndex._page_quality_weight(query, page)
            if score >= min_score:
                results.append(
                    SearchResult(
                        file_name=page.file_name,
                        file_path=page.file_path,
                        page_number=page.page_number,
                        snippet=ManualSearchIndex._make_snippet(
                            page.text,
                            query,
                            query_tokens,
                            snippet_chars,
                        ),
                        score=score,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[: max(1, max_results)]

    async def _provider(self):
        configured_id = self.config._config_str("embedding_provider_id", "").strip()
        if not configured_id:
            return None

        getter = getattr(self.context, "get_all_embedding_providers", None)
        if getter is None:
            logger.warning("规则手册嵌入检索已启用，但当前 AstrBot 不支持嵌入提供商接口。")
            return None

        providers = getter()
        if hasattr(providers, "__await__"):
            providers = await providers
        for provider in providers or []:
            if configured_id in _provider_id_candidates(provider):
                return provider

        logger.warning(f"规则手册嵌入检索找不到提供商：{configured_id}")
        return None

    async def _page_vectors(self, index: ManualSearchIndex, provider) -> dict[str, list[float]]:
        provider_id = _provider_id(provider)
        page_chars = max(200, self.config._config_int("embedding_page_chars", 1200))
        signature = _index_signature(index.pages, page_chars)
        dim = _provider_dim(provider)
        cache_path = _cache_path(provider_id, dim, page_chars, signature)

        async with self._lock:
            cached = await asyncio.to_thread(
                _load_cache,
                cache_path,
                provider_id,
                dim,
                page_chars,
                signature,
            )
            if cached is not None:
                return cached

            vectors = await self._build_page_vectors(index.pages, provider, page_chars)
            await asyncio.to_thread(
                _save_cache,
                cache_path,
                provider_id,
                dim,
                page_chars,
                signature,
                vectors,
            )
            return vectors

    async def _build_page_vectors(
        self,
        pages: list[ManualPage],
        provider,
        page_chars: int,
    ) -> dict[str, list[float]]:
        batch_size = max(1, self.config._config_int("embedding_batch_size", 16))
        vectors: dict[str, list[float]] = {}
        items: list[tuple[str, str]] = []
        for page in pages:
            text = _embedding_text(page, page_chars)
            if text:
                items.append((_page_key(page), text))

        for start in range(0, len(items), batch_size):
            batch = items[start : start + batch_size]
            texts = [text for _, text in batch]
            try:
                raw_vectors = await provider.get_embeddings(texts)
            except Exception:
                raw_vectors = []
                for text in texts:
                    try:
                        raw_vectors.append(await provider.get_embedding(text))
                    except Exception as exc:
                        logger.warning(f"规则手册单页嵌入失败，已跳过：{exc}")
                        raw_vectors.append([])
            for (key, _), vector in zip(batch, raw_vectors):
                normalized = _normalize_vector(vector)
                if normalized:
                    vectors[key] = normalized

        return vectors


def _cache_path(provider_id: str, dim: int, page_chars: int, signature: str) -> Path:
    cache_dir = plugin_data_dir() / "embedding_cache"
    safe_provider = re.sub(r"[^A-Za-z0-9_.-]+", "_", provider_id)[:80] or "embedding"
    return cache_dir / f"{safe_provider}-{dim}-{page_chars}-{signature[:16]}.json"


def _load_cache(
    cache_path: Path,
    provider_id: str,
    dim: int,
    page_chars: int,
    signature: str,
) -> dict[str, list[float]] | None:
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    if data.get("version") != EMBEDDING_CACHE_VERSION:
        return None
    if data.get("provider_id") != provider_id or data.get("dim") != dim:
        return None
    if data.get("page_chars") != page_chars or data.get("signature") != signature:
        return None

    items = data.get("vectors", {})
    if not isinstance(items, dict):
        return None
    vectors: dict[str, list[float]] = {}
    for key, vector in items.items():
        normalized = _normalize_vector(vector)
        if normalized:
            vectors[str(key)] = normalized
    return vectors


def _save_cache(
    cache_path: Path,
    provider_id: str,
    dim: int,
    page_chars: int,
    signature: str,
    vectors: dict[str, list[float]],
) -> None:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": EMBEDDING_CACHE_VERSION,
        "provider_id": provider_id,
        "dim": dim,
        "page_chars": page_chars,
        "signature": signature,
        "vectors": vectors,
    }
    cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _index_signature(pages: list[ManualPage], page_chars: int) -> str:
    digest = hashlib.sha1()
    digest.update(str(page_chars).encode("utf-8"))
    for page in pages:
        digest.update(_page_key(page).encode("utf-8"))
        digest.update(b"\0")
        digest.update(_embedding_text(page, page_chars).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def _page_key(page: ManualPage) -> str:
    raw = f"{page.file_path}:{page.page_number}:{page.file_name}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _embedding_text(page: ManualPage, page_chars: int) -> str:
    text = " ".join(str(page.text or "").split())
    if not text:
        return ""
    return f"文件：{page.file_name}\n页码：{page.page_number}\n{text[:page_chars]}"


def _normalize_vector(vector: Any) -> list[float]:
    if not isinstance(vector, (list, tuple)):
        return []
    values: list[float] = []
    for item in vector:
        try:
            values.append(float(item))
        except (TypeError, ValueError):
            return []
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return []
    return [value / norm for value in values]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if len(left) != len(right):
        return 0.0
    return sum(left_value * right_value for left_value, right_value in zip(left, right))


def _provider_id(provider) -> str:
    candidates = _provider_id_candidates(provider)
    return candidates[0] if candidates else "embedding"


def _provider_id_candidates(provider) -> list[str]:
    candidates: list[str] = []
    config = getattr(provider, "provider_config", None)
    if isinstance(config, dict):
        for key in ("id", "name", "provider_id"):
            value = str(config.get(key) or "").strip()
            if value:
                candidates.append(value)
    for attr in ("id", "name", "provider_id"):
        value = str(getattr(provider, attr, "") or "").strip()
        if value:
            candidates.append(value)

    unique: list[str] = []
    for item in candidates:
        if item not in unique:
            unique.append(item)
    return unique


def _provider_dim(provider) -> int:
    getter = getattr(provider, "get_dim", None)
    if not callable(getter):
        return 0
    try:
        return int(getter())
    except (TypeError, ValueError):
        return 0
