from __future__ import annotations

import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..core.text_utils import normalize_text, tokenize
from .models import ForumArticle, ForumSearchHit

try:
    from rank_bm25 import BM25Okapi
except Exception:  # pragma: no cover
    BM25Okapi = None

try:
    from rapidfuzz import fuzz
except Exception:  # pragma: no cover
    fuzz = None


INDEX_VERSION = 1


@dataclass
class ForumDocument:
    id: int
    title: str
    url: str
    author: str = ""
    category: str = ""
    posted_at: str = ""
    summary: str = ""
    tech_stack: list[str] | None = None
    scenarios: list[str] | None = None
    repo_links: list[str] | None = None
    key_points: list[str] | None = None
    raw_text: str = ""

    def to_article(self) -> ForumArticle:
        return ForumArticle(
            id=self.id,
            title=self.title,
            url=self.url,
            author=self.author,
            category=self.category,
            posted_at=self.posted_at,
            summary=self.summary,
            tech_stack=list(self.tech_stack or []),
            scenarios=list(self.scenarios or []),
            repo_links=list(self.repo_links or []),
            key_points=list(self.key_points or []),
            raw_text=self.raw_text,
        )

    @property
    def searchable_text(self) -> str:
        sections = [
            self.title,
            self.author,
            self.category,
            self.posted_at,
            self.summary,
            " ".join(self.tech_stack or []),
            " ".join(self.scenarios or []),
            " ".join(self.repo_links or []),
            " ".join(self.key_points or []),
            self.raw_text[:3000],
        ]
        return normalize_text(" ".join(section for section in sections if section))


class ForumSearchIndex:
    def __init__(self, documents: list[ForumDocument] | None = None):
        self.documents = documents or []
        self._tokenized_docs: list[list[str]] = []
        self._bm25: Any | None = None
        self._tfidf_docs: list[dict[str, float]] = []
        self._tfidf_norms: list[float] = []
        self._idf: dict[str, float] = {}
        self._build_runtime_index()

    @classmethod
    def from_articles(cls, articles: list[ForumArticle]) -> "ForumSearchIndex":
        return cls([document_from_article(article) for article in articles])

    @classmethod
    def load(cls, path: Path) -> "ForumSearchIndex":
        if not path.exists():
            return cls([])
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if data.get("version") != INDEX_VERSION:
                return cls([])
            docs = [
                ForumDocument(
                    id=int(item["id"]),
                    title=str(item["title"]),
                    url=str(item["url"]),
                    author=str(item.get("author", "")),
                    category=str(item.get("category", "")),
                    posted_at=str(item.get("posted_at", "")),
                    summary=str(item.get("summary", "")),
                    tech_stack=list(item.get("tech_stack") or []),
                    scenarios=list(item.get("scenarios") or []),
                    repo_links=list(item.get("repo_links") or []),
                    key_points=list(item.get("key_points") or []),
                    raw_text=str(item.get("raw_text", "")),
                )
                for item in data.get("documents", [])
                if isinstance(item, dict) and item.get("title") and item.get("url")
            ]
        except Exception:
            return cls([])
        return cls(docs)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": INDEX_VERSION,
            "generated_at": int(time.time()),
            "documents": [asdict(doc) for doc in self.documents],
        }
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def search(self, query: str, *, max_results: int = 5, snippet_chars: int = 220) -> list[ForumSearchHit]:
        query = normalize_text(query)
        query_tokens = tokenize(query)
        if not query or not query_tokens or not self.documents:
            return []

        bm25_scores = self._bm25.get_scores(query_tokens) if self._bm25 is not None else []
        query_vector = self._tfidf_vector(query_tokens)
        query_norm = self._vector_norm(query_vector)
        query_token_set = set(query_tokens)
        hits: list[ForumSearchHit] = []

        for idx, document in enumerate(self.documents):
            text = document.searchable_text
            tokens = self._tokenized_docs[idx] if idx < len(self._tokenized_docs) else []
            overlap = len(query_token_set & set(tokens)) / max(1, len(query_token_set))
            bm25_score = self._normalize_bm25(float(bm25_scores[idx]) if len(bm25_scores) else overlap)
            fuzzy_score = self._fuzzy_score(query, text)
            exact_bonus = 0.4 if query in text else 0.0
            vector_score = 0.0
            if query_norm > 0 and idx < len(self._tfidf_docs):
                vector_score = self._cosine_similarity(
                    query_vector,
                    query_norm,
                    self._tfidf_docs[idx],
                    self._tfidf_norms[idx],
                )
            score = bm25_score + overlap + fuzzy_score + exact_bonus + vector_score
            if score <= 0:
                continue
            hits.append(
                ForumSearchHit(
                    article=document.to_article(),
                    snippet=self._make_snippet(text, query, query_tokens, snippet_chars),
                    score=score,
                )
            )

        hits.sort(key=lambda item: item.score, reverse=True)
        return hits[: max(1, max_results)]

    def _build_runtime_index(self) -> None:
        self._tokenized_docs = [tokenize(doc.searchable_text) for doc in self.documents]
        self._bm25 = BM25Okapi(self._tokenized_docs) if BM25Okapi is not None and any(self._tokenized_docs) else None
        self._build_vector_index()

    def _build_vector_index(self) -> None:
        self._tfidf_docs = []
        self._tfidf_norms = []
        self._idf = {}
        if not self._tokenized_docs:
            return
        doc_count = len(self._tokenized_docs)
        df: Counter[str] = Counter()
        for tokens in self._tokenized_docs:
            df.update(set(tokens))
        self._idf = {token: math.log((doc_count + 1) / (freq + 1)) + 1.0 for token, freq in df.items()}
        for tokens in self._tokenized_docs:
            vector = self._tfidf_vector(tokens)
            self._tfidf_docs.append(vector)
            self._tfidf_norms.append(self._vector_norm(vector))

    def _tfidf_vector(self, tokens: list[str]) -> dict[str, float]:
        counts = Counter(token for token in tokens if token in self._idf)
        total = sum(counts.values())
        if total <= 0:
            return {}
        return {token: (count / total) * self._idf[token] for token, count in counts.items()}

    @staticmethod
    def _vector_norm(vector: dict[str, float]) -> float:
        return math.sqrt(sum(value * value for value in vector.values()))

    @staticmethod
    def _cosine_similarity(left: dict[str, float], left_norm: float, right: dict[str, float], right_norm: float) -> float:
        if left_norm <= 0 or right_norm <= 0:
            return 0.0
        if len(left) > len(right):
            left, right = right, left
        return sum(value * right.get(token, 0.0) for token, value in left.items()) / (left_norm * right_norm)

    @staticmethod
    def _normalize_bm25(score: float) -> float:
        return math.log1p(score) / 2.0 if score > 0 else 0.0

    @staticmethod
    def _fuzzy_score(query: str, text: str) -> float:
        return float(fuzz.partial_ratio(query, text)) / 100.0 if fuzz is not None else 0.0

    @staticmethod
    def _make_snippet(text: str, query: str, query_tokens: list[str], snippet_chars: int) -> str:
        snippet_chars = max(80, snippet_chars)
        center = text.find(query)
        if center < 0:
            for token in sorted(query_tokens, key=len, reverse=True):
                center = text.lower().find(token.lower())
                if center >= 0:
                    break
        if center < 0:
            center = 0
        start = max(0, center - snippet_chars // 2)
        end = min(len(text), start + snippet_chars)
        start = max(0, end - snippet_chars)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet += "..."
        return snippet


def document_from_article(article: ForumArticle) -> ForumDocument:
    return ForumDocument(
        id=article.id,
        title=article.title,
        url=article.url,
        author=article.author,
        category=article.category,
        posted_at=article.posted_at,
        summary=article.summary,
        tech_stack=article.tech_stack,
        scenarios=article.scenarios,
        repo_links=article.repo_links,
        key_points=article.key_points,
        raw_text=article.raw_text,
    )


