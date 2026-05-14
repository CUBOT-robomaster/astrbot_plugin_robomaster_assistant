from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


LOCAL_TZ = ZoneInfo("Asia/Shanghai")


@dataclass
class MatchTeam:
    school: str = ""
    team: str = ""
    player_name: str = ""

    @property
    def label(self) -> str:
        if self.school and self.team:
            return f"{self.school} {self.team}"
        return self.school or self.team or self.player_name or "待定"

    def contains(self, query: str) -> bool:
        text = f"{self.school} {self.team} {self.player_name}".lower()
        return query.lower() in text


@dataclass
class MatchRecord:
    match_id: str
    event_title: str
    zone_id: str
    zone_name: str
    order_number: int
    match_type: str
    status: str
    plan_started_at: str
    plan_game_count: int
    red: MatchTeam
    blue: MatchTeam
    red_wins: int
    blue_wins: int
    round: Any = None
    raw: dict[str, Any] | None = None

    @property
    def event_key(self) -> str:
        return f"{self.zone_name or self.zone_id}:{self.match_id or self.order_number}"

    @property
    def score_key(self) -> tuple[int, int, str]:
        return (self.red_wins, self.blue_wins, str(self.round or ""))

    @property
    def local_started_at(self) -> datetime | None:
        return parse_time(self.plan_started_at)

    @property
    def date_key(self) -> str:
        started_at = self.local_started_at
        return started_at.strftime("%Y-%m-%d") if started_at else ""

    def is_live(self) -> bool:
        return self.status in {"STARTED", "PENDING"}

    def contains_team(self, query: str) -> bool:
        return self.red.contains(query) or self.blue.contains(query)


def normalize_schedule(payload: Any) -> list[MatchRecord]:
    event = ((payload or {}).get("data") or {}).get("event") if isinstance(payload, dict) else {}
    event_title = str((event or {}).get("title") or "RoboMaster")
    zones = (((event or {}).get("zones") or {}).get("nodes") or [])
    matches: list[MatchRecord] = []
    for zone in zones:
        if not isinstance(zone, dict):
            continue
        for key in ("groupMatches", "knockoutMatches"):
            nodes = ((zone.get(key) or {}).get("nodes") or [])
            for match in nodes:
                if isinstance(match, dict):
                    matches.append(match_from_raw(match, zone=zone, event_title=event_title))
    return sorted(matches, key=lambda item: (item.local_started_at or datetime.max.replace(tzinfo=LOCAL_TZ), item.order_number))


def normalize_current_items(items: Any) -> list[MatchRecord]:
    if not isinstance(items, list):
        return []
    records: list[MatchRecord] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        match = item.get("currentMatch")
        if not isinstance(match, dict) or not match:
            continue
        zone = match.get("zone") if isinstance(match.get("zone"), dict) else {}
        event_title = (((zone or {}).get("event") or {}).get("title")) or "RoboMaster"
        records.append(match_from_raw(match, zone=zone or {}, event_title=event_title))
    return records


def match_from_raw(
    match: dict[str, Any],
    *,
    zone: dict[str, Any] | None = None,
    event_title: str = "RoboMaster",
) -> MatchRecord:
    zone = zone or {}
    return MatchRecord(
        match_id=str(match.get("id") or ""),
        event_title=str(event_title or "RoboMaster"),
        zone_id=str(zone.get("id") or match.get("zoneId") or ""),
        zone_name=str(zone.get("name") or "未知赛区"),
        order_number=_int(match.get("orderNumber")),
        match_type=str(match.get("matchType") or ""),
        status=str(match.get("status") or ""),
        plan_started_at=str(match.get("planStartedAt") or ""),
        plan_game_count=_int(match.get("planGameCount"), 3),
        red=side_team(match.get("redSide")),
        blue=side_team(match.get("blueSide")),
        red_wins=_int(match.get("redSideWinGameCount")),
        blue_wins=_int(match.get("blueSideWinGameCount")),
        round=match.get("round"),
        raw=match,
    )


def side_team(side: Any) -> MatchTeam:
    side = side if isinstance(side, dict) else {}
    player = side.get("player") if isinstance(side.get("player"), dict) else {}
    team = player.get("team") if isinstance(player.get("team"), dict) else {}
    return MatchTeam(
        school=str(team.get("collegeName") or ""),
        team=str(team.get("name") or ""),
        player_name=str(player.get("name") or ""),
    )


def parse_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TZ)
    except ValueError:
        return None


def status_label(status: str) -> str:
    return {
        "WAITING": "未开始",
        "STARTED": "直播中",
        "PENDING": "成绩待确认",
        "DONE": "已结束",
    }.get(status or "", status or "未知")


def format_time(value: str) -> str:
    parsed = parse_time(value)
    if not parsed:
        return "-"
    return parsed.strftime("%m-%d %H:%M")


def format_score(match: MatchRecord) -> str:
    if match.status == "WAITING" and match.red_wins == 0 and match.blue_wins == 0:
        return "- : -"
    return f"{match.red_wins} : {match.blue_wins}"


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default
