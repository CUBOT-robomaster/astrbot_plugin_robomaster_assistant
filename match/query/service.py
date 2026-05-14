from __future__ import annotations

from datetime import datetime
from typing import Any

from ..client import MatchApiClient
from ..models import LOCAL_TZ, MatchRecord
from .formatters import (
    OFFICIAL_HISTORY_UNSUPPORTED,
    format_match_detail,
    format_match_list,
)
from .parser import parse_match_query
from .types import MatchQueryResponse, ParsedMatchQuery


class MatchQueryService:
    def __init__(self, config: Any, client: MatchApiClient):
        self.config = config
        self.client = client

    def help_text(self) -> str:
        return (
            "RoboMaster 赛事查询\n"
            "可直接在“赛事查询”后面接问题，例如：\n"
            "赛事查询 今天有哪些比赛\n"
            "赛事查询 华南理工下一场什么时候\n"
            "赛事查询 南部赛区第12场是谁打谁\n"
            "赛事查询 华南理工和电子科技大学历史交手\n\n"
            "也兼容旧格式：\n"
            "赛事查询 今日\n"
            "赛事查询 明日\n"
            "赛事查询 南部赛区\n"
            "赛事查询 华南理工大学\n"
            "赛事查询 南部赛区 第12场\n"
            "赛事查询 历史 华南理工大学 电子科技大学"
        )

    async def query(
        self,
        text: str,
        parsed: ParsedMatchQuery | None = None,
    ) -> MatchQueryResponse:
        parsed = parsed or parse_match_query(text)
        if parsed.kind == "help":
            return MatchQueryResponse(self.help_text(), "RoboMaster 赛事查询")
        if parsed.kind == "history":
            return MatchQueryResponse(
                await self.history(parsed.primary, parsed.secondary),
                f"{parsed.primary} vs {parsed.secondary} 历史交手",
            )

        matches = await self.client.matches()
        if parsed.kind == "date":
            date_matches = [match for match in matches if match.date_key == parsed.date]
            if parsed.query:
                date_matches = [match for match in date_matches if parsed.query in match.zone_name]
            title = f"{parsed.date}{' ' + parsed.query if parsed.query else ''} 赛程"
            return MatchQueryResponse(
                format_match_list(date_matches, title, limit=None),
                title,
                date_matches,
                is_schedule_list=True,
            )
        if parsed.kind == "detail":
            match = self.find_match_detail(matches, parsed.query, parsed.order_number)
            if not match:
                return MatchQueryResponse("没有找到对应场次。", "赛事详情")
            text = await format_match_detail(self.config, self.client, match)
            return MatchQueryResponse(text, f"{match.zone_name} 第 {match.order_number} 场", [match])
        return self.search(matches, parsed.query)

    def search(self, matches: list[MatchRecord], query: str) -> MatchQueryResponse:
        query = query.strip()
        if not query:
            return MatchQueryResponse(self.help_text(), "RoboMaster 赛事查询")

        zone_matches = [match for match in matches if query in match.zone_name]
        if zone_matches:
            nearby = self.nearby_matches(zone_matches)
            title = f"{query} 近期赛程"
            limited = self.limited_matches(nearby)
            return MatchQueryResponse(self.format_match_list(nearby, title), title, limited, True)

        team_matches = [match for match in matches if match.contains_team(query)]
        if team_matches:
            nearby = self.nearby_matches(team_matches)
            title = f"{query} 相关比赛"
            limited = self.limited_matches(nearby)
            return MatchQueryResponse(self.format_match_list(nearby, title), title, limited, True)

        loose = [
            match
            for match in matches
            if query.lower() in f"{match.event_title} {match.zone_name} {match.red.label} {match.blue.label}".lower()
        ]
        nearby = self.nearby_matches(loose)
        title = f"{query} 查询结果"
        limited = self.limited_matches(nearby)
        return MatchQueryResponse(self.format_match_list(nearby, title), title, limited, True)

    def limited_matches(self, matches: list[MatchRecord]) -> list[MatchRecord]:
        limit = max(1, self.config._config_int("match_query_max_results", 8))
        return matches[:limit]

    def nearby_matches(self, matches: list[MatchRecord]) -> list[MatchRecord]:
        now = datetime.now(LOCAL_TZ)

        def key(match: MatchRecord) -> tuple[int, float, int]:
            started_at = match.local_started_at
            if match.is_live:
                group = 0
            elif started_at and started_at >= now:
                group = 1
            else:
                group = 2
            distance = abs((started_at - now).total_seconds()) if started_at else 10**12
            return (group, distance, match.order_number)

        return sorted(matches, key=key)

    def find_match_detail(
        self,
        matches: list[MatchRecord],
        query: str,
        order_number: int,
    ) -> MatchRecord | None:
        candidates = [match for match in matches if match.order_number == order_number]
        query = query.strip()
        if query:
            filtered = [
                match
                for match in candidates
                if query in match.zone_name or query in match.event_title or match.contains_team(query)
            ]
            if filtered:
                candidates = filtered
        return (
            sorted(candidates, key=lambda item: item.local_started_at or datetime.max.replace(tzinfo=LOCAL_TZ))[0]
            if candidates
            else None
        )

    def format_match_list(
        self,
        matches: list[MatchRecord],
        title: str,
        limit: int | None = -1,
    ) -> str:
        if limit == -1:
            limit = max(1, self.config._config_int("match_query_max_results", 8))
        return format_match_list(matches, title, limit=limit)

    async def history(self, primary: str, secondary: str) -> str:
        if not primary or not secondary:
            return "请按格式查询：赛事查询 历史 学校A 学校B"
        if not self.client.supports_schedule_extras():
            return OFFICIAL_HISTORY_UNSUPPORTED
        hits = await self.client.history(primary, secondary)
        if not hits:
            return f"{primary} vs {secondary}\n暂无历史交手记录。"
        lines = [f"{primary} vs {secondary} 历史交手"]
        for item in hits[: self.config._config_int("match_query_max_results", 8)]:
            red = f"{item.get('redCollegeName') or '-'} {item.get('redTeamName') or ''}".strip()
            blue = f"{item.get('blueCollegeName') or '-'} {item.get('blueTeamName') or ''}".strip()
            score = f"{item.get('redSideWinGameCount') or 0}:{item.get('blueSideWinGameCount') or 0}"
            order = item.get("orderNumber")
            if order is None or order == "":
                order = item.get("order") or "-"
            group = item.get("group") or item.get("zoneName") or ""
            lines.append(f"第 {order} 场 {group} | {red} vs {blue} | {score}")
        return "\n".join(lines)
