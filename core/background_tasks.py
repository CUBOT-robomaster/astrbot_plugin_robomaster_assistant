from __future__ import annotations

import asyncio
from typing import Any

from astrbot.api import logger

from .state import MonitorState


class BackgroundTaskManager:
    def __init__(
        self,
        config: Any,
        monitor_state: MonitorState,
        lark_clients: dict[str, Any],
        announcement: Any,
        match_push: Any,
        forum_monitor: Any,
        forum: Any,
    ):
        self.config = config
        self.monitor_state = monitor_state
        self.lark_clients = lark_clients
        self.announcement = announcement
        self.match_push = match_push
        self.forum_monitor = forum_monitor
        self.forum = forum
        self.tasks: list[asyncio.Task[Any]] = []

    def start(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("无法获取事件循环，监控任务未启动。")
            return

        self.tasks = [task for task in self.tasks if not task.done()]
        active_names = {task.get_name() for task in self.tasks}
        if (
            self.config._config_bool("announce_enabled", False)
            and "rm_announce_monitor" not in active_names
        ):
            self.tasks.append(
                loop.create_task(self._announcement_loop(), name="rm_announce_monitor")
            )
        if (
            self.config._config_bool("match_monitor_enabled", False)
            and "rm_match_monitor" not in active_names
        ):
            self.tasks.append(loop.create_task(self._match_loop(), name="rm_match_monitor"))
        if (
            self.config._config_bool("forum_monitor_enabled", False)
            and "rm_forum_monitor" not in active_names
        ):
            self.tasks.append(loop.create_task(self._forum_loop(), name="rm_forum_monitor"))

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.tasks.clear()

    def status_lines(self) -> list[str]:
        data = self.monitor_state.data
        return [
            "RM 监控状态",
            f"公告监控：{'开启' if self.config._config_bool('announce_enabled', False) else '关闭'}",
            f"赛事监控：{'开启' if self.config._config_bool('match_monitor_enabled', False) else '关闭'}",
            f"开源监控：{'开启' if self.config._config_bool('forum_monitor_enabled', False) else '关闭'}",
            f"订阅会话：{len(self.monitor_state.sessions)}",
            f"飞书卡片通知：{'开启' if self.config._config_bool('enable_lark_card_notifications', False) else '关闭'}",
            f"飞书卡片可用会话：{len(self.lark_clients)}",
            f"公告 last_id：{data.get('announce_last_id') or self.config._config_int('announce_last_id', 0)}",
            f"监控公告页：{len(data.get('announce_page_hashes', {}))}",
            f"赛事缓存赛区：{len(data.get('match_previous', {}))}",
            f"开源文章：{self.forum.article_count()}",
            f"开源抓取模式：{self.config._config_str('forum_fetch_mode', 'http')}",
            f"开源最近检查：{data.get('forum_last_check_at') or 0}",
            f"开源最近错误：{data.get('forum_last_error') or '无'}",
            f"后台任务：{sum(1 for task in self.tasks if not task.done())}",
        ]

    async def _announcement_loop(self) -> None:
        interval = max(5, self.config._config_int("announce_interval_seconds", 60))
        while True:
            try:
                await self.announcement.run_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 公告监控失败：{exc}")
            await asyncio.sleep(interval)

    async def _match_loop(self) -> None:
        interval = max(5, self.config._config_int("match_scan_interval_seconds", 30))
        while True:
            try:
                await self.match_push.run_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 赛事监控失败：{exc}")
            await asyncio.sleep(interval)

    async def _forum_loop(self) -> None:
        while True:
            try:
                await self.forum_monitor.run_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 开源论坛监控失败：{exc}")
                self.monitor_state.data["forum_last_error"] = str(exc)
                self.monitor_state.save()
            await asyncio.sleep(max(30, self.forum.scan_sleep_seconds()))
