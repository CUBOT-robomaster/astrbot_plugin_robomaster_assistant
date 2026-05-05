from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DJI_CURRENT_API_URL = (
    "https://pro-robomasters-hz-n5i3.oss-cn-hangzhou.aliyuncs.com/"
    "live_json/current_and_next_matches.json"
)
DJI_SCHEDULE_API_URL = (
    "https://pro-robomasters-hz-n5i3.oss-cn-hangzhou.aliyuncs.com/live_json/schedule.json"
)


@dataclass
class MatchEvent:
    event_type: str
    match: dict[str, Any]
    previous: dict[str, Any] | None
    zone_key: str
    text: str


def extract_zone_key(item: dict[str, Any]) -> str:
    match = item.get("currentMatch") or item.get("nextMatch") or {}
    zone_name = ((match.get("zone") or {}).get("name")) or "default"
    return f"RM-Dispatcher-{zone_name}"


def current_match(item: dict[str, Any]) -> dict[str, Any]:
    return item.get("currentMatch") or {}


def name_key(match: dict[str, Any] | None) -> tuple[str, str]:
    match = match or {}
    return (
        _college_name(match.get("redSide")),
        _college_name(match.get("blueSide")),
    )


def score_key(match: dict[str, Any] | None) -> Any:
    return (match or {}).get("round")


def is_empty_match(match: dict[str, Any] | None) -> bool:
    return not match or name_key(match) == ("", "")


def detect_match_events(
    items: list[dict[str, Any]],
    previous_by_zone: dict[str, dict[str, Any]],
    zone_allowlist: set[str] | None = None,
) -> tuple[list[MatchEvent], dict[str, dict[str, Any]]]:
    events: list[MatchEvent] = []
    next_previous = dict(previous_by_zone)
    seen_keys: set[str] = set()

    for item in items:
        zone_key = extract_zone_key(item)
        match = current_match(item)
        zone_name = zone_key.removeprefix("RM-Dispatcher-")
        if zone_allowlist and zone_name not in zone_allowlist:
            continue
        seen_keys.add(zone_key)
        previous = previous_by_zone.get(zone_key) or {}
        event = compare_match(zone_key, previous, match)
        if event is not None:
            events.append(event)
            next_previous[zone_key] = match

    for zone_key, previous in previous_by_zone.items():
        if zone_key in seen_keys:
            continue
        zone_name = zone_key.removeprefix("RM-Dispatcher-")
        if zone_allowlist and zone_name not in zone_allowlist:
            continue
        if previous:
            event = compare_match(zone_key, previous, {})
            if event is not None:
                events.append(event)
            next_previous.pop(zone_key, None)

    return events, next_previous


def compare_match(
    zone_key: str,
    previous: dict[str, Any],
    current: dict[str, Any],
) -> MatchEvent | None:
    previous_empty = is_empty_match(previous)
    current_empty = is_empty_match(current)
    names_equal = name_key(previous) == name_key(current)
    scores_equal = score_key(previous) == score_key(current)

    if not names_equal and not current_empty:
        return MatchEvent(
            "match_start",
            current,
            previous or None,
            zone_key,
            format_match_event("match_start", current),
        )
    if not names_equal and not previous_empty:
        return MatchEvent(
            "match_end",
            previous,
            previous,
            zone_key,
            format_match_event("match_end", previous),
        )
    if not current_empty and names_equal and not scores_equal:
        return MatchEvent(
            "match_session_end",
            current,
            previous or None,
            zone_key,
            format_match_event("match_session_end", current),
        )
    return None


def format_match_event(event_type: str, match: dict[str, Any]) -> str:
    titles = {
        "match_start": "比赛开始",
        "match_session_end": "单局结束",
        "match_end": "比赛结束",
    }
    zone = ((match.get("zone") or {}).get("name")) or "未知赛区"
    event_title = (((match.get("zone") or {}).get("event") or {}).get("title")) or "RoboMaster"
    red = _team_label(match.get("redSide"))
    blue = _team_label(match.get("blueSide"))
    round_text = f"{match.get('round') or '-'} / {match.get('totalRound') or '-'}"
    score_text = f"{match.get('redSideWinGameCount') or 0} : {match.get('blueSideWinGameCount') or 0}"
    return (
        f"RoboMaster 赛事监控\n"
        f"{titles.get(event_type, event_type)}\n"
        f"赛事：{event_title}\n"
        f"赛区：{zone}\n"
        f"场次：{match.get('orderNumber') or '-'}  小局：{round_text}\n"
        f"红方：{red}\n"
        f"蓝方：{blue}\n"
        f"比分：{score_text}"
    )


def _team_label(side: dict[str, Any] | None) -> str:
    school = _college_name(side)
    team = _team_name(side)
    if school and team:
        return f"{school} {team}"
    return school or team or "待定"


def _college_name(side: dict[str, Any] | None) -> str:
    return (((side or {}).get("player") or {}).get("team") or {}).get("collegeName") or ""


def _team_name(side: dict[str, Any] | None) -> str:
    return (((side or {}).get("player") or {}).get("team") or {}).get("name") or ""
