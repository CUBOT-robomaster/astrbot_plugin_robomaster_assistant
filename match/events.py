from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .models import MatchRecord, format_score, format_time, status_label


@dataclass
class MatchEvent:
    event_type: str
    match: MatchRecord
    previous: dict[str, Any] | None
    zone_key: str
    text: str


def detect_match_events(
    matches: list[MatchRecord],
    previous_by_key: dict[str, dict[str, Any]],
    zone_allowlist: set[str] | None = None,
) -> tuple[list[MatchEvent], dict[str, dict[str, Any]]]:
    events: list[MatchEvent] = []
    next_previous = dict(previous_by_key)
    seen: set[str] = set()

    for match in matches:
        if zone_allowlist and match.zone_name not in zone_allowlist:
            continue
        key = match.event_key
        seen.add(key)
        current = match_snapshot(match)
        previous = previous_by_key.get(key)
        event = compare_match(match, previous)
        if event:
            events.append(event)
        next_previous[key] = current

    for key in list(previous_by_key):
        if key not in seen:
            next_previous.pop(key, None)

    return events, next_previous


def compare_match(match: MatchRecord, previous: dict[str, Any] | None) -> MatchEvent | None:
    current = match_snapshot(match)
    if previous is None:
        if match.status == "STARTED":
            return _event("match_start", match, previous)
        return None

    previous_status = str(previous.get("status") or "")
    previous_score = tuple(previous.get("score") or ())
    if previous_status != "STARTED" and match.status == "STARTED":
        return _event("match_start", match, previous)
    if previous_status != "DONE" and match.status == "DONE":
        return _event("match_end", match, previous)
    if previous_score and previous_score != match.score_key and match.status in {"STARTED", "PENDING", "DONE"}:
        return _event("match_session_end", match, previous)
    if current != previous and previous_status == "STARTED" and match.status == "PENDING":
        return _event("match_session_end", match, previous)
    return None


def match_snapshot(match: MatchRecord) -> dict[str, Any]:
    return {
        "id": match.match_id,
        "zone": match.zone_name,
        "order": match.order_number,
        "status": str(match.status or ""),
        "score": list(match.score_key),
        "red": match.red.label,
        "blue": match.blue.label,
    }


def format_match_event(event_type: str, match: MatchRecord) -> str:
    titles = {
        "match_start": "比赛开始",
        "match_session_end": "比分更新",
        "match_end": "比赛结束",
    }
    return (
        f"RoboMaster 赛事监控\n"
        f"{titles.get(event_type, event_type)}\n"
        f"赛事：{match.event_title}\n"
        f"赛区：{match.zone_name}\n"
        f"场次：第 {match.order_number} 场  状态：{status_label(match.status)}\n"
        f"时间：{format_time(match.plan_started_at)}\n"
        f"红方：{match.red.label}\n"
        f"蓝方：{match.blue.label}\n"
        f"比分：{format_score(match)}"
    )


def _event(
    event_type: str,
    match: MatchRecord,
    previous: dict[str, Any] | None,
) -> MatchEvent:
    return MatchEvent(
        event_type=event_type,
        match=match,
        previous=previous,
        zone_key=match.zone_name,
        text=format_match_event(event_type, match),
    )
