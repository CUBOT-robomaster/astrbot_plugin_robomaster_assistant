from __future__ import annotations

from dataclasses import dataclass

from .search_engine import SearchResult


@dataclass
class LocatedResult:
    result: SearchResult
    focus_text: str = ""


@dataclass
class ManualSearchResponse:
    query: str
    located_results: list[LocatedResult]
    explanation: str = ""
