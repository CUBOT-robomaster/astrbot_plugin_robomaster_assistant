from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ForumArticleInput:
    title: str
    url: str
    author: str = ""
    category: str = ""
    posted_at: str = ""
    raw_text: str = ""
    detail_error: str = ""
    repo_links: list[str] = field(default_factory=list)


@dataclass
class ForumArticle:
    id: int
    title: str
    url: str
    author: str = ""
    category: str = ""
    posted_at: str = ""
    raw_text: str = ""
    summary: str = ""
    tech_stack: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    repo_links: list[str] = field(default_factory=list)
    key_points: list[str] = field(default_factory=list)
    notified: bool = False
    detail_error: str = ""
    created_at: str = ""
    updated_at: str = ""


@dataclass
class ForumSearchHit:
    article: ForumArticle
    snippet: str
    score: float


@dataclass
class ForumSearchResponse:
    query: str
    hits: list[ForumSearchHit]
    explanation: str = ""
