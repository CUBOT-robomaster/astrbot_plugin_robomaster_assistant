from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .models import ForumArticle, ForumArticleInput


class ForumArticleStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.init_db()

    def init_db(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS forum_articles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    url TEXT NOT NULL UNIQUE,
                    author TEXT DEFAULT '',
                    category TEXT DEFAULT '',
                    posted_at TEXT DEFAULT '',
                    raw_text TEXT DEFAULT '',
                    summary TEXT DEFAULT '',
                    tech_stack TEXT DEFAULT '[]',
                    scenarios TEXT DEFAULT '[]',
                    repo_links TEXT DEFAULT '[]',
                    key_points TEXT DEFAULT '[]',
                    notified INTEGER DEFAULT 0,
                    detail_error TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )

    def upsert_article(self, article: ForumArticleInput) -> tuple[ForumArticle, bool]:
        repo_links = encode_list(article.repo_links)
        with self._connect() as conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO forum_articles
                    (title, url, author, category, posted_at, raw_text, repo_links, detail_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    article.title,
                    article.url,
                    article.author,
                    article.category,
                    article.posted_at,
                    article.raw_text,
                    repo_links,
                    article.detail_error,
                ),
            )
            inserted = cursor.rowcount > 0
            if not inserted:
                conn.execute(
                    """
                    UPDATE forum_articles
                    SET title = ?, author = ?, category = ?, posted_at = ?,
                        raw_text = COALESCE(NULLIF(?, ''), raw_text),
                        repo_links = CASE WHEN ? != '[]' THEN ? ELSE repo_links END,
                        detail_error = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE url = ?
                    """,
                    (
                        article.title,
                        article.author,
                        article.category,
                        article.posted_at,
                        article.raw_text,
                        repo_links,
                        repo_links,
                        article.detail_error,
                        article.url,
                    ),
                )
            row = conn.execute("SELECT * FROM forum_articles WHERE url = ?", (article.url,)).fetchone()
        return article_from_row(row), inserted

    def update_summary(
        self,
        article_id: int,
        *,
        summary: str,
        tech_stack: list[str],
        scenarios: list[str],
        repo_links: list[str],
        key_points: list[str],
    ) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE forum_articles
                SET summary = ?, tech_stack = ?, scenarios = ?, repo_links = ?,
                    key_points = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    summary,
                    encode_list(tech_stack),
                    encode_list(scenarios),
                    encode_list(repo_links),
                    encode_list(key_points),
                    article_id,
                ),
            )

    def mark_notified(self, article_id: int) -> None:
        with self._connect() as conn:
            conn.execute(
                "UPDATE forum_articles SET notified = 1, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (article_id,),
            )

    def article_count(self) -> int:
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS count FROM forum_articles").fetchone()
        return int(row["count"] if row else 0)

    def all_articles(self) -> list[ForumArticle]:
        with self._connect() as conn:
            rows = conn.execute("SELECT * FROM forum_articles ORDER BY id DESC").fetchall()
        return [article_from_row(row) for row in rows]

    def get_article(self, article_id: int) -> ForumArticle | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM forum_articles WHERE id = ?", (article_id,)).fetchone()
        return article_from_row(row) if row else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn


def encode_list(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return json.dumps(cleaned, ensure_ascii=False)


def decode_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        data = json.loads(str(value))
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    return [str(item) for item in data if str(item).strip()]


def article_from_row(row: sqlite3.Row) -> ForumArticle:
    return ForumArticle(
        id=int(row["id"]),
        title=str(row["title"] or ""),
        url=str(row["url"] or ""),
        author=str(row["author"] or ""),
        category=str(row["category"] or ""),
        posted_at=str(row["posted_at"] or ""),
        raw_text=str(row["raw_text"] or ""),
        summary=str(row["summary"] or ""),
        tech_stack=decode_list(row["tech_stack"]),
        scenarios=decode_list(row["scenarios"]),
        repo_links=decode_list(row["repo_links"]),
        key_points=decode_list(row["key_points"]),
        notified=bool(row["notified"]),
        detail_error=str(row["detail_error"] or ""),
        created_at=str(row["created_at"] or ""),
        updated_at=str(row["updated_at"] or ""),
    )
