from __future__ import annotations

import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    import jieba
except Exception:  # pragma: no cover - fallback for environments before deps install
    jieba = None

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
class ManualPage:
    file_name: str
    file_path: str
    page_number: int
    text: str


@dataclass
class SearchResult:
    file_name: str
    file_path: str
    page_number: int
    snippet: str
    score: float


@dataclass
class RebuildStats:
    pdf_count: int
    page_count: int
    indexed_page_count: int
    errors: list[str]


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def clean_excerpt(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"\b\d{1,3}\s*©\s*20\d{2}\s*大疆\s*版权所有\s*", "", text)
    text = re.sub(r"©\s*20\d{2}\s*大疆\s*版权所有\s*", "", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" ，,。;；")


def tokenize(text: str) -> list[str]:
    text = normalize_text(text).lower()
    if not text:
        return []

    tokens: list[str] = []
    if jieba is not None:
        tokens = [token.strip() for token in jieba.cut(text) if token.strip()]
    else:
        tokens = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text)
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", text))
        tokens.extend(chinese[i : i + 2] for i in range(max(0, len(chinese) - 1)))

    return [token for token in tokens if len(token) > 1 or re.match(r"[a-z0-9]", token)]


class ManualSearchIndex:
    def __init__(self, pages: list[ManualPage] | None = None):
        self.pages = pages or []
        self._tokenized_pages: list[list[str]] = []
        self._bm25: Any | None = None
        self._build_runtime_index()

    @classmethod
    def load(cls, index_path: Path) -> "ManualSearchIndex":
        if not index_path.exists():
            return cls([])

        data = json.loads(index_path.read_text(encoding="utf-8"))
        pages = [
            ManualPage(
                file_name=item["file_name"],
                file_path=item["file_path"],
                page_number=int(item["page_number"]),
                text=item["text"],
            )
            for item in data.get("pages", [])
            if item.get("text")
        ]
        return cls(pages)

    def save(self, index_path: Path, manual_dir: str, stats: RebuildStats) -> None:
        index_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "version": INDEX_VERSION,
            "generated_at": int(time.time()),
            "manual_dir": manual_dir,
            "stats": asdict(stats),
            "pages": [asdict(page) for page in self.pages],
        }
        index_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _build_runtime_index(self) -> None:
        self._tokenized_pages = [tokenize(page.text) for page in self.pages]
        if BM25Okapi is not None and any(self._tokenized_pages):
            self._bm25 = BM25Okapi(self._tokenized_pages)
        else:
            self._bm25 = None

    def search(
        self,
        query: str,
        *,
        max_results: int = 3,
        snippet_chars: int = 180,
        min_score: float = 0.6,
    ) -> list[SearchResult]:
        query = normalize_text(query)
        query_tokens = tokenize(query)
        if not query or not query_tokens or not self.pages:
            return []

        bm25_scores = self._bm25.get_scores(query_tokens) if self._bm25 is not None else []
        query_token_set = set(query_tokens)
        results: list[SearchResult] = []

        for idx, page in enumerate(self.pages):
            page_tokens = self._tokenized_pages[idx] if idx < len(self._tokenized_pages) else []
            page_token_set = set(page_tokens)
            overlap = len(query_token_set & page_token_set) / max(1, len(query_token_set))
            bm25_score = float(bm25_scores[idx]) if len(bm25_scores) else overlap
            fuzzy_score = self._fuzzy_score(query, page.text)
            exact_bonus = 0.35 if query in page.text else 0.0
            score = self._normalize_bm25(bm25_score) + overlap + fuzzy_score + exact_bonus
            score *= self._page_quality_weight(query, page)

            if score >= min_score:
                results.append(
                    SearchResult(
                        file_name=page.file_name,
                        file_path=page.file_path,
                        page_number=page.page_number,
                        snippet=self._make_snippet(page.text, query, query_tokens, snippet_chars),
                        score=score,
                    )
                )

        results.sort(key=lambda item: item.score, reverse=True)
        return results[: max(1, max_results)]

    @staticmethod
    def _normalize_bm25(score: float) -> float:
        if score <= 0:
            return 0.0
        return math.log1p(score) / 2.0

    @staticmethod
    def _fuzzy_score(query: str, text: str) -> float:
        if fuzz is None:
            return 0.0
        return float(fuzz.partial_ratio(query, text)) / 100.0

    @staticmethod
    def _page_quality_weight(query: str, page: ManualPage) -> float:
        if any(keyword in query for keyword in ("版本", "修订", "修改", "目录", "版权")):
            return 1.0

        if page.page_number <= 10:
            return 0.2

        text_head = page.text[:300]
        admin_markers = ("修改日志", "修订记录", "目录", "版权声明")
        if any(marker in text_head for marker in admin_markers):
            return 0.35
        return 1.0

    @staticmethod
    def _make_snippet(text: str, query: str, query_tokens: list[str], snippet_chars: int) -> str:
        text = clean_excerpt(text)
        snippet_chars = max(60, snippet_chars)
        center = text.find(query)

        if center < 0:
            for token in sorted(query_tokens, key=len, reverse=True):
                center = text.lower().find(token.lower())
                if center >= 0:
                    break

        if center < 0:
            center = 0

        start = ManualSearchIndex._find_readable_start(text, center, snippet_chars)
        end = min(len(text), start + snippet_chars)
        start = max(0, end - snippet_chars)
        snippet = text[start:end].strip()
        if start > 0:
            snippet = "..." + snippet
        if end < len(text):
            snippet = snippet + "..."
        return snippet

    @staticmethod
    def _find_readable_start(text: str, center: int, snippet_chars: int) -> int:
        hard_start = max(0, center - snippet_chars // 2)
        left = text[hard_start:center]
        delimiter_positions = [left.rfind(mark) for mark in "。；;：:"]
        best = max(delimiter_positions)
        if best >= 0 and len(left) - best <= snippet_chars // 2:
            return hard_start + best + 1
        return hard_start


def rebuild_index(manual_dir: str) -> tuple[ManualSearchIndex, RebuildStats]:
    root = Path(manual_dir).expanduser()
    if not root.exists():
        return ManualSearchIndex([]), RebuildStats(0, 0, 0, [f"目录不存在：{root}"])
    if not root.is_dir():
        return ManualSearchIndex([]), RebuildStats(0, 0, 0, [f"不是目录：{root}"])

    pdf_files = sorted(root.rglob("*.pdf"))
    if not pdf_files:
        return ManualSearchIndex([]), RebuildStats(0, 0, 0, [f"目录中没有 PDF：{root}"])

    pages: list[ManualPage] = []
    errors: list[str] = []
    page_count = 0

    for pdf_path in pdf_files:
        try:
            extracted_pages = extract_pdf_text_pages(pdf_path)
            page_count += len(extracted_pages)
            for page_index, text in extracted_pages:
                if text:
                    pages.append(
                        ManualPage(
                            file_name=pdf_path.name,
                            file_path=str(pdf_path),
                            page_number=page_index,
                            text=text,
                        )
                    )
        except Exception as exc:
            errors.append(f"{pdf_path.name} 解析失败：{exc}")

    stats = RebuildStats(
        pdf_count=len(pdf_files),
        page_count=page_count,
        indexed_page_count=len(pages),
        errors=errors,
    )
    return ManualSearchIndex(pages), stats


def extract_pdf_text_pages(pdf_path: Path) -> list[tuple[int, str]]:
    try:
        return _extract_with_pypdf(pdf_path)
    except Exception:
        return _extract_with_pymupdf(pdf_path)


def _extract_with_pypdf(pdf_path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    extracted_pages: list[tuple[int, str]] = []
    for page_index, page in enumerate(reader.pages, start=1):
        text = normalize_text(page.extract_text() or "")
        extracted_pages.append((page_index, text))
    return extracted_pages


def _extract_with_pymupdf(pdf_path: Path) -> list[tuple[int, str]]:
    import fitz

    extracted_pages: list[tuple[int, str]] = []
    doc = fitz.open(str(pdf_path))
    try:
        for page_index, page in enumerate(doc, start=1):
            text = normalize_text(page.get_text("text") or "")
            extracted_pages.append((page_index, text))
    finally:
        doc.close()
    return extracted_pages
