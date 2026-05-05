from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

from ..core.state import MonitorState
from ..notifications.service import NotificationService
from .models import (
    AnnouncementEvent,
    announcement_url,
    format_announcement_event,
    main_context_hash,
    parse_announcement_html,
)


class AnnouncementService:
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

    async def run_check(self) -> list[AnnouncementEvent]:
        async with self.lock:
            return await self._run_check_unlocked()

    async def _run_check_unlocked(self) -> list[AnnouncementEvent]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 公告监控缺少 httpx：{exc}")
            return []

        events: list[AnnouncementEvent] = []
        async with httpx.AsyncClient(timeout=15) as client:
            last_id = int(self.monitor_state.data.get("announce_last_id") or 0)
            if last_id == 0:
                last_id = self.config._config_int("announce_last_id", 0)
                self.monitor_state.data["announce_last_id"] = last_id
                self.monitor_state.save()

            if last_id > 0:
                next_id = last_id + 1
                page = await self.fetch_page(client, next_id)
                if page:
                    self.monitor_state.data["announce_last_id"] = next_id
                    self.monitor_state.save()
                    if self.monitor_state.remember_recent_announcement(next_id):
                        event = format_announcement_event("announcement_new", page)
                        events.append(event)
                        await self.notifications.notify(
                            event.text,
                            {"id": next_id, "title": page.title, "url": page.url},
                            event.event_type,
                        )

            page_hashes = dict(self.monitor_state.data.get("announce_page_hashes", {}))
            for page_id in self.config._config_int_list("announce_monitored_pages"):
                page = await self.fetch_page(client, page_id)
                if page is None:
                    continue
                digest = main_context_hash(page.main_html)
                previous_hash = page_hashes.get(str(page_id))
                page_hashes[str(page_id)] = digest
                if previous_hash and previous_hash != digest:
                    event = format_announcement_event("announcement_update", page)
                    events.append(event)
                    await self.notifications.notify(
                        event.text,
                        {"id": page_id, "title": page.title, "url": page.url},
                        event.event_type,
                    )
            self.monitor_state.data["announce_page_hashes"] = page_hashes
            self.monitor_state.save()
        return events

    async def fetch_page(self, client: Any, announcement_id: int):
        resp = await client.get(announcement_url(announcement_id))
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(f"RM 公告页面请求失败 {announcement_id}: {resp.status_code}")
            return None
        return parse_announcement_html(announcement_id, resp.text)
