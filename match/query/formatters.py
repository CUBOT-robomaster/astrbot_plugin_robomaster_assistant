from __future__ import annotations

from typing import Any

from ..models import MatchRecord, format_score, format_time, status_label


OFFICIAL_HISTORY_UNSUPPORTED = "官方 live_json 数据源不支持历史交手，请切换到 schedule 或 auto。"
OFFICIAL_EXTRAS_UNSUPPORTED = "官方 live_json 数据源不支持投票和回放。"


def format_match_list(
    matches: list[MatchRecord],
    title: str,
    *,
    limit: int | None,
) -> str:
    if not matches:
        return f"{title}\n暂无匹配比赛。"
    lines = [title]
    shown = matches if limit is None else matches[:limit]
    for match in shown:
        lines.append(format_match_line(match))
    if limit is not None and len(matches) > limit:
        lines.append(f"仅显示前 {limit} 场，共 {len(matches)} 场。")
    return "\n".join(lines)


async def format_match_detail(config: Any, client: Any, match: MatchRecord) -> str:
    lines = [
        "RoboMaster 赛事查询",
        f"{match.zone_name} 第 {match.order_number} 场",
        f"赛事：{match.event_title}",
        f"状态：{status_label(match.status)}",
        f"时间：{format_time(match.plan_started_at)}",
        f"赛制：BO{match.plan_game_count}",
        f"红方：{match.red.label}",
        f"蓝方：{match.blue.label}",
        f"比分：{format_score(match)}",
    ]
    supports_extras = client.supports_schedule_extras()
    if config._config_bool("match_query_include_vote", True):
        if supports_extras:
            vote = await client.mp_match(match.match_id)
            if vote:
                lines.append(format_vote(vote))
    if config._config_bool("match_query_include_replay", True):
        if supports_extras:
            replay = await client.match_replay(match)
            if replay:
                lines.append(format_replay(replay))
    if not supports_extras and (
        config._config_bool("match_query_include_vote", True)
        or config._config_bool("match_query_include_replay", True)
    ):
        lines.append(OFFICIAL_EXTRAS_UNSUPPORTED)
    return "\n".join(lines)


def format_match_line(match: MatchRecord) -> str:
    return (
        f"{format_time(match.plan_started_at)} "
        f"{match.zone_name} 第 {match.order_number} 场 "
        f"[{status_label(match.status)}] "
        f"{match.red.label} vs {match.blue.label} "
        f"{format_score(match)}"
    )


def format_vote(vote: dict[str, Any]) -> str:
    total = vote.get("totalCount") or 0
    red_rate = _percent(vote.get("redRate"))
    blue_rate = _percent(vote.get("blueRate"))
    tie_rate = _percent(vote.get("tieRate"))
    return f"投票：红 {red_rate} / 蓝 {blue_rate} / 平 {tie_rate}，共 {total} 票"


def format_replay(replay: dict[str, Any]) -> str:
    title = replay.get("title") or "B 站回放"
    bvid = replay.get("bvid") or ""
    url = f"https://www.bilibili.com/video/{bvid}" if bvid else str(replay.get("url") or "")
    return f"回放：{title}\n{url}" if url else f"回放：{title}"


def _percent(value: Any) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    if number < 0:
        return "-"
    return f"{number * 100:.1f}%"
