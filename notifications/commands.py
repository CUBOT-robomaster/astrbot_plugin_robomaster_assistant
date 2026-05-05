from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ..core.background_tasks import BackgroundTaskManager
from ..core.state import MonitorState
from .service import NotificationService


class NotificationCommandHandler:
    def __init__(
        self,
        plugin: Any,
        monitor_state: MonitorState,
        notifications: NotificationService,
        lark_clients: dict[str, Any],
        background_tasks: BackgroundTaskManager,
    ):
        self.plugin = plugin
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.lark_clients = lark_clients
        self.background_tasks = background_tasks

    async def subscribe(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        if not session:
            yield event.plain_result("订阅失败：无法获取当前会话 ID。")
            return
        added = self.monitor_state.add_session(session)
        lark_card_hint = self.notifications.remember_lark_runtime(event, session)
        suffix = "\n已记录飞书卡片运行时信息。" if lark_card_hint else ""
        yield event.plain_result(
            ("已订阅 RM 通知。" if added else "当前会话已订阅 RM 通知。") + suffix
        )

    async def unsubscribe(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        removed = self.monitor_state.remove_session(session)
        self.lark_clients.pop(session, None)
        yield event.plain_result("已取消订阅 RM 通知。" if removed else "当前会话未订阅 RM 通知。")

    async def status(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result("\n".join(self.background_tasks.status_lines()))
