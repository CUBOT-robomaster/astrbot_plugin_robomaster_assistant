from __future__ import annotations

import asyncio
import traceback
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.state import MonitorState
from ..notifications.service import NotificationService
from .client import MatchApiClient
from .events import MatchEvent, detect_match_events
from .image import MatchInfoImagePlanner, MatchInfoImageRenderer
from .llm_query import MatchLlmQueryParser
from .query.parser import parse_match_query
from .query.service import MatchQueryService
from .query.types import MatchQueryResponse, ParsedMatchQuery
from .image.screenshot import MatchScheduleScreenshotService


class MatchPushService:
    def __init__(
        self,
        config: Any,
        monitor_state: MonitorState,
        notifications: NotificationService,
        client: MatchApiClient | None = None,
        context: Any | None = None,
    ):
        self.config = config
        self.context = context or getattr(config, "context", None)
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.client = client or MatchApiClient(config)
        self.query_service = MatchQueryService(config, self.client)
        self.llm_query = MatchLlmQueryParser(self.context, config) if self.context else None
        self.info_image = MatchInfoImagePlanner(self.context, config)
        self.info_image_renderer = MatchInfoImageRenderer(config)
        self.screenshot = MatchScheduleScreenshotService(config)
        self.lock = asyncio.Lock()

    async def run_check(self) -> list[MatchEvent]:
        async with self.lock:
            return await self._run_check_unlocked()

    async def query(
        self,
        text: str,
        event: AstrMessageEvent | None = None,
    ) -> MatchQueryResponse:
        try:
            parsed = await self.parse_query(event, text)
            response = await self.query_service.query(text, parsed)
            if self.config._config_bool("match_query_enable_info_image", False) and parsed.kind != "help":
                response.image_payload = await self.info_image.plan(event, text, parsed, response)
                response.image_path = await self.info_image_renderer.render(response.image_payload)
                if not response.image_path and parsed.kind == "date" and parsed.need_image and response.is_schedule_list:
                    response.image_path = await self.screenshot.render(parsed.date)
            return response
        except Exception as exc:
            logger.warning(f"RM 赛事查询失败：{exc}\n{traceback.format_exc()}")
            return MatchQueryResponse(f"RM 赛事查询失败：{exc}", "RM 赛事查询")

    async def close(self) -> None:
        close = getattr(self.client, "close", None)
        if callable(close):
            await close()

    async def query_text(self, text: str) -> str:
        return (await self.query(text)).text

    async def parse_query(
        self,
        event: AstrMessageEvent | None,
        text: str,
    ) -> ParsedMatchQuery:
        if self.llm_query:
            parsed = await self.llm_query.parse(event, text)
            if parsed:
                return parsed
        return parse_match_query(text)

    def help_text(self) -> str:
        return self.query_service.help_text()

    async def _run_check_unlocked(self) -> list[MatchEvent]:
        try:
            matches = await self.client.current_matches()
        except Exception as exc:
            logger.warning(f"RM 赛事数据请求失败：{exc}")
            return []

        previous = self.monitor_state.data.get("match_previous", {})
        if not isinstance(previous, dict):
            previous = {}
        zone_allowlist = self.config._config_id_set("match_zone_allowlist")
        events, next_previous = detect_match_events(matches, previous, zone_allowlist or None)
        self.monitor_state.data["match_previous"] = next_previous
        self.monitor_state.save()

        for event in events:
            await self.handle_event(event)
        return events

    async def handle_event(self, event: MatchEvent) -> None:
        await self.notifications.notify(
            event.text,
            event.match.raw or {},
            event.event_type,
            "match",
        )
