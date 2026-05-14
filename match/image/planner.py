from __future__ import annotations

import asyncio
import json
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..llm_query import parse_llm_json
from ..models import MatchRecord, format_score, format_time, status_label
from ..query import MatchQueryResponse, ParsedMatchQuery


class MatchInfoImagePlanner:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config

    async def plan(
        self,
        event: AstrMessageEvent | None,
        question: str,
        parsed: ParsedMatchQuery,
        response: MatchQueryResponse,
    ) -> dict[str, Any] | None:
        mode = image_mode(self.config, parsed)
        fallback = fallback_payload(response, mode)
        provider_id = await self.provider_id(event)
        if not provider_id:
            return fallback

        timeout = max(1, self.config._config_int("match_query_llm_timeout_seconds", 15))
        try:
            result = await asyncio.wait_for(
                self.context.llm_generate(
                    chat_provider_id=provider_id,
                    prompt=build_image_prompt(question, response, mode),
                ),
                timeout=timeout,
            )
            planned = normalize_payload(parse_llm_json(getattr(result, "completion_text", "") or ""), mode)
            return planned or fallback
        except Exception as exc:
            logger.warning(f"RM 赛事信息图片 LLM 排版失败：{exc}")
            return fallback

    async def provider_id(self, event: AstrMessageEvent | None) -> str | None:
        if self.context is None:
            return None
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
        return await result if hasattr(result, "__await__") else result


def image_mode(config: Any, parsed: ParsedMatchQuery) -> str:
    configured = config._config_str("match_query_info_image_mode", "auto").strip().lower()
    if configured in {"table", "flowchart"}:
        return configured
    if parsed.image_style in {"table", "flowchart"}:
        return parsed.image_style
    return "table"


def build_image_prompt(question: str, response: MatchQueryResponse, mode: str) -> str:
    facts = response_facts(response)
    return (
        "你是 RoboMaster 赛事信息图片的排版器。只能使用给定 facts 中的事实，"
        "不得补充、改写或编造队伍、比分、时间、赛区、场次。\n"
        "请输出严格 JSON，不要 Markdown，不要解释。\n"
        "JSON 字段：title, subtitle, kind, columns, rows, notes, highlight_rules。\n"
        "kind 只能是 table 或 flowchart。table 使用 columns + rows；flowchart 可额外使用 nodes + edges。\n"
        "rows 必须是二维字符串数组，每行长度必须等于 columns 长度。\n"
        f"期望展示模式：{mode}\n"
        f"用户问题：{question}\n"
        "facts:\n"
        + json.dumps(facts, ensure_ascii=False)
    )


def response_facts(response: MatchQueryResponse) -> dict[str, Any]:
    matches = response.matches or []
    return {
        "title": response.title or "RoboMaster 赛事查询",
        "text": response.text,
        "matches": [match_fact(match) for match in matches],
    }


def match_fact(match: MatchRecord) -> dict[str, Any]:
    return {
        "time": format_time(match.plan_started_at),
        "event": match.event_title,
        "zone": match.zone_name,
        "order": match.order_number,
        "status": status_label(match.status),
        "format": f"BO{match.plan_game_count}",
        "red": match.red.label,
        "blue": match.blue.label,
        "score": format_score(match),
    }


def normalize_payload(data: dict[str, Any] | None, mode: str) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    kind = str(data.get("kind") or mode).strip().lower()
    if kind not in {"table", "flowchart"}:
        return None
    columns = clean_strings(data.get("columns"))
    rows = clean_rows(data.get("rows"), len(columns))
    if not columns or not rows:
        return None
    return {
        "kind": kind,
        "title": one_line(data.get("title")) or "RoboMaster 赛事查询",
        "subtitle": one_line(data.get("subtitle")),
        "columns": columns,
        "rows": rows,
        "notes": clean_strings(data.get("notes")),
        "highlight_rules": clean_strings(data.get("highlight_rules")),
        "nodes": clean_nodes(data.get("nodes")),
        "edges": clean_edges(data.get("edges")),
    }


def fallback_payload(response: MatchQueryResponse, mode: str) -> dict[str, Any]:
    matches = response.matches or []
    if mode == "flowchart" and matches:
        return fallback_flowchart(response, matches)
    if matches:
        return fallback_table(response, matches)
    return text_table(response)


def fallback_table(response: MatchQueryResponse, matches: list[MatchRecord]) -> dict[str, Any]:
    columns = ["时间", "赛区/场次", "状态", "红方", "蓝方", "比分"]
    rows = [
        [
            format_time(match.plan_started_at),
            f"{match.zone_name} 第 {match.order_number} 场",
            status_label(match.status),
            match.red.label,
            match.blue.label,
            format_score(match),
        ]
        for match in matches
    ]
    return {
        "kind": "table",
        "title": response.title or "RoboMaster 赛事查询",
        "subtitle": f"共 {len(matches)} 场比赛",
        "columns": columns,
        "rows": rows,
        "notes": [],
        "highlight_rules": [],
    }


def fallback_flowchart(response: MatchQueryResponse, matches: list[MatchRecord]) -> dict[str, Any]:
    rows = [
        [
            f"{match.zone_name} 第 {match.order_number} 场",
            f"{format_time(match.plan_started_at)} · {status_label(match.status)}",
            match.red.label,
            match.blue.label,
            format_score(match),
        ]
        for match in matches
    ]
    nodes = [
        {
            "id": str(index),
            "title": row[0],
            "subtitle": row[1],
            "red": row[2],
            "blue": row[3],
            "score": row[4],
        }
        for index, row in enumerate(rows, start=1)
    ]
    return {
        "kind": "flowchart",
        "title": response.title or "RoboMaster 赛事查询",
        "subtitle": f"共 {len(matches)} 场比赛",
        "columns": ["场次", "时间/状态", "红方", "蓝方", "比分"],
        "rows": rows,
        "notes": [],
        "highlight_rules": [],
        "nodes": nodes,
        "edges": [[str(index), str(index + 1)] for index in range(1, len(nodes))],
    }


def text_table(response: MatchQueryResponse) -> dict[str, Any]:
    lines = [line for line in response.text.splitlines() if line.strip()]
    title = response.title or (lines[0] if lines else "RoboMaster 赛事查询")
    rows = [[line] for line in lines[1:]] or [["暂无可渲染内容"]]
    return {
        "kind": "table",
        "title": title,
        "subtitle": "",
        "columns": ["内容"],
        "rows": rows,
        "notes": [],
        "highlight_rules": [],
    }


def clean_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [one_line(item)[:80] for item in value if one_line(item)]


def clean_rows(value: Any, width: int) -> list[list[str]]:
    if not isinstance(value, list) or width <= 0:
        return []
    rows: list[list[str]] = []
    for row in value:
        if not isinstance(row, list):
            continue
        cells = [one_line(cell)[:120] for cell in row]
        if len(cells) == width:
            rows.append(cells)
    return rows[:80]


def clean_nodes(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    nodes = []
    for item in value[:80]:
        if isinstance(item, dict):
            nodes.append({str(key): one_line(val)[:120] for key, val in item.items()})
    return nodes


def clean_edges(value: Any) -> list[list[str]]:
    if not isinstance(value, list):
        return []
    edges = []
    for item in value[:120]:
        if isinstance(item, list) and len(item) == 2:
            edges.append([one_line(item[0])[:40], one_line(item[1])[:40]])
    return edges


def one_line(value: Any) -> str:
    return " ".join(str(value or "").split())
