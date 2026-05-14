from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..models import MatchRecord


@dataclass
class ParsedMatchQuery:
    kind: str
    query: str = ""
    date: str = ""
    order_number: int = 0
    primary: str = ""
    secondary: str = ""
    need_image: bool = False
    image_style: str = ""


@dataclass
class MatchQueryResponse:
    text: str
    title: str = ""
    matches: list[MatchRecord] | None = None
    is_schedule_list: bool = False
    image_path: Path | None = None
    image_payload: dict[str, Any] | None = None

    def __str__(self) -> str:
        return self.text

    def __contains__(self, item: str) -> bool:
        return item in self.text

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.text == other
        if isinstance(other, MatchQueryResponse):
            return (
                self.text,
                self.title,
                self.matches,
                self.is_schedule_list,
                self.image_path,
                self.image_payload,
            ) == (
                other.text,
                other.title,
                other.matches,
                other.is_schedule_list,
                other.image_path,
                other.image_payload,
            )
        return super().__eq__(other)
