from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .models import LOCAL_TZ
from .query.types import ParsedMatchQuery


class MatchLlmQueryParser:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config

    async def parse(self, event: AstrMessageEvent | None, text: str) -> ParsedMatchQuery | None:
        if not self.config._config_bool("match_query_enable_llm_parse", True):
            return None
        provider_id = await self.provider_id(event)
        if not provider_id:
            return None

        timeout = max(1, self.config._config_int("match_query_llm_timeout_seconds", 15))
        try:
            response = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=build_query_prompt(text),
                ),
                timeout=timeout,
            )
            data = parse_llm_json((getattr(response, "completion_text", "") or "").strip())
            return parsed_query_from_llm(data)
        except Exception as exc:
            logger.warning(f"RM 赛事查询 LLM 理解失败：{exc}")
            return None

    async def provider_id(self, event: AstrMessageEvent | None) -> str | None:
        configured = self.config._config_str("match_query_llm_provider_id", "").strip()
        if configured:
            return configured
        if event is None:
            return None
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


def build_query_prompt(text: str) -> str:
    today = datetime.now(LOCAL_TZ).date()
    tomorrow = today + timedelta(days=1)
    return (
        "你是 RoboMaster 赛事查询参数解析器。"
        "你的任务是把用户问题转换成插件可执行的严格 JSON，不要回答赛事内容，"
        "不要编造队伍、比分或赛程。只能输出 JSON 对象，不要 Markdown。\n"
        f"今天是 {today.isoformat()}，明天是 {tomorrow.isoformat()}，时区为 Asia/Shanghai。\n"
        "可用 kind：\n"
        "可选字段 image_style=table/flowchart；用户提到流程图、对阵图、晋级图时使用 flowchart。\n"
        "date_schedule：查询某天赛程，字段 date=YYYY-MM-DD，可选 zone，need_image=true/false。\n"
        "team_schedule：查询某学校或战队相关比赛，字段 team。\n"
        "zone_schedule：查询某赛区相关比赛，字段 zone。\n"
        "match_detail：查询单场详情，字段 order_number，可选 zone 或 team。\n"
        "history：查询历史交手，字段 primary、secondary。\n"
        "search：无法判断时的关键词查询，字段 query。\n"
        "help：用户想看帮助。\n\n"
        "示例：今天有哪些比赛 -> "
        + json.dumps(
            {"kind": "date_schedule", "date": today.isoformat(), "need_image": True},
            ensure_ascii=False,
        )
        + "\n"
        "示例：南部赛区第12场是谁打谁 -> {\"kind\":\"match_detail\",\"zone\":\"南部赛区\",\"order_number\":12}\n"
        "示例：华南理工和电子科技大学历史交手 -> {\"kind\":\"history\",\"primary\":\"华南理工大学\",\"secondary\":\"电子科技大学\"}\n\n"
        f"用户问题：{text}"
    )


def parsed_query_from_llm(data: dict[str, Any] | None) -> ParsedMatchQuery | None:
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind") or "").strip().lower()
    if kind == "date_schedule":
        date = str(data.get("date") or "").strip()
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
            return None
        return ParsedMatchQuery(
            "date",
            date=date,
            query=one_line(data.get("zone")),
            need_image=bool(data.get("need_image", True)),
            image_style=image_style_from_llm(data),
        )
    if kind == "team_schedule":
        query = one_line(data.get("team"))
        return ParsedMatchQuery("search", query=query, image_style=image_style_from_llm(data)) if query else None
    if kind == "zone_schedule":
        query = one_line(data.get("zone"))
        return ParsedMatchQuery("search", query=query, image_style=image_style_from_llm(data)) if query else None
    if kind == "match_detail":
        order = int_or_zero(data.get("order_number"))
        query = one_line(data.get("zone")) or one_line(data.get("team"))
        return (
            ParsedMatchQuery("detail", query=query, order_number=order, image_style=image_style_from_llm(data))
            if order > 0
            else None
        )
    if kind == "history":
        primary = one_line(data.get("primary"))
        secondary = one_line(data.get("secondary"))
        return (
            ParsedMatchQuery("history", primary=primary, secondary=secondary, image_style=image_style_from_llm(data))
            if primary and secondary
            else None
        )
    if kind == "search":
        query = one_line(data.get("query"))
        return ParsedMatchQuery("search", query=query, image_style=image_style_from_llm(data)) if query else None
    if kind == "help":
        return ParsedMatchQuery("help")
    return None


def parse_llm_json(text: str) -> dict[str, Any] | None:
    text = (text or "").strip()
    if not text:
        return None

    candidates = [text]
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.I | re.S)
    if fence:
        candidates.insert(0, fence.group(1).strip())

    decoder = json.JSONDecoder()
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            for index, char in enumerate(candidate):
                if char != "{":
                    continue
                try:
                    data, _ = decoder.raw_decode(candidate[index:])
                except json.JSONDecodeError:
                    continue
                return data if isinstance(data, dict) else None
        else:
            return data if isinstance(data, dict) else None
    return None


def one_line(value: Any) -> str:
    return " ".join(str(value or "").split())


def image_style_from_llm(data: dict[str, Any]) -> str:
    value = one_line(data.get("image_style")).lower()
    return value if value in {"table", "flowchart"} else ""


def int_or_zero(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
