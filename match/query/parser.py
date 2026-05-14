from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from ..models import LOCAL_TZ
from .types import ParsedMatchQuery


def parse_match_query(text: str) -> ParsedMatchQuery:
    text = text.strip()
    image_style = parse_image_style(text)
    text = strip_image_style_words(text)
    if not text or text in {"帮助", "help", "？", "?"}:
        return ParsedMatchQuery("help")
    date = parse_date_query(text)
    if date:
        zone = date_zone_query(text)
        return ParsedMatchQuery("date", date=date, query=zone, need_image=True, image_style=image_style)
    if text.startswith("历史 "):
        parts = [part for part in re.split(r"[\s,，]+", text.removeprefix("历史 ").strip()) if part]
        return ParsedMatchQuery(
            "history",
            primary=parts[0] if parts else "",
            secondary=parts[1] if len(parts) > 1 else "",
            image_style=image_style,
        )
    history = parse_history_query(text)
    if history:
        history.image_style = image_style
        return history

    match = re.search(r"第\s*(\d+)\s*场", text)
    if match:
        query = clean_detail_query(text[: match.start()] + text[match.end() :])
        return ParsedMatchQuery("detail", query=query, order_number=int(match.group(1)), image_style=image_style)
    return ParsedMatchQuery("search", query=clean_search_query(text), image_style=image_style)


def parse_image_style(text: str) -> str:
    if any(word in text for word in ("流程图", "对阵图", "晋级图", "图表")):
        return "flowchart"
    if "表格" in text:
        return "table"
    return ""


def strip_image_style_words(text: str) -> str:
    return " ".join(re.sub(r"(流程图|对阵图|晋级图|图表|表格)", " ", text).split())


def parse_date_query(text: str) -> str:
    if any(word in text for word in ("今日", "今天")):
        return datetime.now(LOCAL_TZ).strftime("%Y-%m-%d")
    if any(word in text for word in ("明日", "明天")):
        return (datetime.now(LOCAL_TZ) + timedelta(days=1)).strftime("%Y-%m-%d")
    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})日?", text)
    if match:
        return valid_date_text(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return ""


def date_zone_query(text: str) -> str:
    cleaned = re.sub(r"(今日|今天|明日|明天|有哪些|什么|比赛|赛程|的|呢|？|\?)", " ", text)
    cleaned = re.sub(r"\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?", " ", cleaned)
    return " ".join(cleaned.split())


def normalize_date_text(text: str) -> str:
    year, month, day = [int(part) for part in re.split(r"-", text)]
    return valid_date_text(year, month, day)


def valid_date_text(year: int, month: int, day: int) -> str:
    try:
        parsed = date(year, month, day)
    except ValueError:
        return ""
    return parsed.isoformat()


def parse_history_query(text: str) -> ParsedMatchQuery | None:
    if "历史" not in text and "交手" not in text:
        return None
    cleaned = re.sub(r"(历史交手|历史|交手|记录|查询|赛事查询)", " ", text).strip()
    parts = [part.strip() for part in re.split(r"\s*(?:和|vs|VS|对|,|，)\s*", cleaned) if part.strip()]
    if len(parts) >= 2:
        return ParsedMatchQuery("history", primary=parts[0], secondary=parts[1])
    return None


def clean_detail_query(text: str) -> str:
    text = re.sub(r"(是谁打谁|谁打谁|对阵|比赛|赛程|查询|的|呢|？|\?)", " ", text)
    return " ".join(text.split())


def clean_search_query(text: str) -> str:
    text = re.sub(r"(下一场|什么时候|几点|有哪些|什么|比赛|赛程|查询|的|呢|？|\?)", " ", text)
    return " ".join(text.split())
