from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

from ..core.state import MonitorState
from ..notifications.service import NotificationService
from .events import (
    DJI_CURRENT_API_URL,
    DJI_SCHEDULE_API_URL,
    MatchEvent,
    detect_match_events,
)


class MatchPushService:
    def __init__(
        self,
        config: Any,
        monitor_state: MonitorState,
        notifications: NotificationService,
    ):
        self.config = config
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.lock = asyncio.Lock()

    async def run_check(self) -> list[MatchEvent]:
        async with self.lock:
            return await self._run_check_unlocked()

    async def _run_check_unlocked(self) -> list[MatchEvent]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 赛事监控缺少 httpx：{exc}")
            return []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                self.config._config_str("dji_current_api_url", DJI_CURRENT_API_URL)
            )
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                items = []

        previous = self.monitor_state.data.get("match_previous", {})
        zone_allowlist = self.config._config_id_set("match_zone_allowlist")
        events, next_previous = detect_match_events(items, previous, zone_allowlist or None)
        self.monitor_state.data["match_previous"] = next_previous
        self.monitor_state.save()

        for event in events:
            await self.handle_event(event)
        return events

    async def handle_event(self, event: MatchEvent) -> None:
        data = event.match
        if event.event_type == "match_end":
            scheduled = await self.fetch_scheduled_match(data)
            if scheduled:
                data = {**data, **scheduled}
                event.match = data
                event.text = event.text + "\n最终比分已尝试从赛程接口补充。"

        await self.notifications.notify(event.text, event.match, event.event_type)

    async def fetch_scheduled_match(self, match: dict[str, Any]) -> dict[str, Any] | None:
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(
                    self.config._config_str("dji_schedule_api_url", DJI_SCHEDULE_API_URL)
                )
                if resp.status_code >= 400:
                    return None
                schedule = resp.json()
        except Exception as exc:
            logger.warning(f"RM 赛程接口请求失败：{exc}")
            return None
        match_id = str(match.get("id") or "")
        return find_match_by_id(schedule, match_id) if match_id else None


def find_match_by_id(node: Any, match_id: str) -> dict[str, Any] | None:
    if isinstance(node, dict):
        if str(node.get("id") or "") == match_id:
            return node
        for value in node.values():
            found = find_match_by_id(value, match_id)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = find_match_by_id(item, match_id)
            if found:
                return found
    return None
