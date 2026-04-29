from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from .announce_monitor import (
    announcement_url,
    format_announcement_event,
    main_context_hash,
    parse_announcement_html,
)
from .match_monitor import (
    DJI_CURRENT_API_URL,
    DJI_SCHEDULE_API_URL,
    MatchEvent,
    detect_match_events,
)
from .monitor_state import MonitorState
from ..forum.service import ForumService
from ..notifications.service import NotificationService


class MonitorService:
    def __init__(
        self,
        config: Any,
        monitor_state: MonitorState,
        notifications: NotificationService,
        lark_clients: dict[str, Any],
        forum: ForumService | None = None,
    ):
        self.config = config
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.lark_clients = lark_clients
        self.forum = forum
        self.tasks: list[asyncio.Task] = []
        self.announce_lock = asyncio.Lock()
        self.match_lock = asyncio.Lock()
        self.forum_lock = asyncio.Lock()

    def start_tasks(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("无法获取事件循环，监控任务未启动。")
            return
        if self.config._config_bool("announce_enabled", False):
            self.tasks.append(loop.create_task(self.announce_loop()))
        if self.config._config_bool("match_monitor_enabled", False):
            self.tasks.append(loop.create_task(self.match_loop()))
        if self.forum is not None and self.config._config_bool("forum_monitor_enabled", False):
            self.tasks.append(loop.create_task(self.forum_loop()))

    async def stop_tasks(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)

    def status_text(self) -> str:
        data = self.monitor_state.data
        return (
            "RM 监控状态\n"
            f"公告监控：{'开启' if self.config._config_bool('announce_enabled', False) else '关闭'}\n"
            f"赛事监控：{'开启' if self.config._config_bool('match_monitor_enabled', False) else '关闭'}\n"
            f"开源监控：{'开启' if self.config._config_bool('forum_monitor_enabled', False) else '关闭'}\n"
            f"订阅会话：{len(self.monitor_state.sessions)}\n"
            f"飞书卡片通知：{'开启' if self.config._config_bool('enable_lark_card_notifications', False) else '关闭'}\n"
            f"飞书卡片可用会话：{len(self.lark_clients)}\n"
            f"公告 last_id：{data.get('announce_last_id') or self.config._config_int('announce_last_id', 0)}\n"
            f"监控公告页：{len(data.get('announce_page_hashes', {}))}\n"
            f"赛事缓存赛区：{len(data.get('match_previous', {}))}\n"
            f"开源文章：{self.forum.article_count() if self.forum is not None else 0}\n"
            f"开源抓取模式：{self.config._config_str('forum_fetch_mode', 'http')}\n"
            f"开源最近检查：{data.get('forum_last_check_at') or 0}\n"
            f"开源最近错误：{data.get('forum_last_error') or '无'}\n"
            f"后台任务：{sum(1 for task in self.tasks if not task.done())}"
        )

    async def announce_loop(self) -> None:
        interval = max(5, self.config._config_int("announce_interval_seconds", 60))
        while True:
            try:
                await self.run_announce_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 公告监控失败：{exc}")
            await asyncio.sleep(interval)

    async def match_loop(self) -> None:
        interval = max(5, self.config._config_int("match_scan_interval_seconds", 30))
        while True:
            try:
                await self.run_match_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 赛事监控失败：{exc}")
            await asyncio.sleep(interval)

    async def forum_loop(self) -> None:
        while True:
            try:
                await self.run_forum_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 开源论坛监控失败：{exc}")
                self.monitor_state.data["forum_last_error"] = str(exc)
                self.monitor_state.save()
            if self.forum is None:
                return
            await asyncio.sleep(self.forum.scan_sleep_seconds())

    async def run_announce_check(self) -> list[Any]:
        async with self.announce_lock:
            return await self.run_announce_check_unlocked()

    async def run_announce_check_unlocked(self) -> list[Any]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 公告监控缺少 httpx：{exc}")
            return []

        events: list[Any] = []
        async with httpx.AsyncClient(timeout=15) as client:
            last_id = int(self.monitor_state.data.get("announce_last_id") or 0)
            if last_id == 0:
                last_id = self.config._config_int("announce_last_id", 0)
                self.monitor_state.data["announce_last_id"] = last_id
                self.monitor_state.save()

            if last_id > 0:
                next_id = last_id + 1
                page = await self.fetch_announcement_page(client, next_id)
                if page:
                    self.monitor_state.data["announce_last_id"] = next_id
                    self.monitor_state.save()
                    if self.monitor_state.remember_recent_announcement(next_id):
                        event = format_announcement_event("announcement_new", page)
                        events.append(event)
                        await self.notifications.notify(event.text, {"id": next_id, "title": page.title, "url": page.url}, event.event_type)

            page_hashes = dict(self.monitor_state.data.get("announce_page_hashes", {}))
            for page_id in self.config._config_int_list("announce_monitored_pages"):
                page = await self.fetch_announcement_page(client, page_id)
                if page is None:
                    continue
                digest = main_context_hash(page.main_html)
                previous_hash = page_hashes.get(str(page_id))
                page_hashes[str(page_id)] = digest
                if previous_hash and previous_hash != digest:
                    event = format_announcement_event("announcement_update", page)
                    events.append(event)
                    await self.notifications.notify(event.text, {"id": page_id, "title": page.title, "url": page.url}, event.event_type)
            self.monitor_state.data["announce_page_hashes"] = page_hashes
            self.monitor_state.save()
        return events

    async def fetch_announcement_page(self, client: Any, announcement_id: int):
        resp = await client.get(announcement_url(announcement_id))
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(f"RM 公告页面请求失败 {announcement_id}: {resp.status_code}")
            return None
        return parse_announcement_html(announcement_id, resp.text)

    async def run_match_check(self) -> list[MatchEvent]:
        async with self.match_lock:
            return await self.run_match_check_unlocked()

    async def run_forum_check(self) -> list[Any]:
        async with self.forum_lock:
            return await self.run_forum_check_unlocked()

    async def run_forum_check_unlocked(self) -> list[Any]:
        if self.forum is None:
            return []
        initialized = bool(self.monitor_state.data.get("forum_initialized", False))
        events = await self.forum.check(notify=initialized)
        self.monitor_state.data["forum_initialized"] = True
        self.monitor_state.data["forum_last_check_at"] = int(time.time())
        self.monitor_state.data["forum_last_error"] = ""
        self.monitor_state.save()
        for article in events:
            await self.notifications.notify(
                self.forum.notification_text(article),
                {
                    "id": article.id,
                    "title": article.title,
                    "url": article.url,
                    "author": article.author,
                    "category": article.category,
                },
                "forum_article_new",
            )
            self.forum.store.mark_notified(article.id)
        return events

    async def run_match_check_unlocked(self) -> list[MatchEvent]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 赛事监控缺少 httpx：{exc}")
            return []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self.config._config_str("dji_current_api_url", DJI_CURRENT_API_URL))
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
            await self.handle_match_event(event)
        return events

    async def handle_match_event(self, event: MatchEvent) -> None:
        data = event.match
        if event.event_type == "match_end":
            scheduled = await self.fetch_scheduled_match(data)
            if scheduled:
                data = {**data, **scheduled}
                event.match = data
                event.text = event.text + "\n最终比分已尝试从赛程接口补充。"

        await self.notifications.notify(event.text, event.match, event.event_type)

    async def fetch_scheduled_match(self, match: dict[str, Any]) -> dict[str, Any] | None:
        # 轻量实现：先保留接口请求能力，复杂 JsonPath 匹配失败时不影响主流程。
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self.config._config_str("dji_schedule_api_url", DJI_SCHEDULE_API_URL))
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
