from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ..core.background_tasks import BackgroundTaskManager
from ..core.state import MonitorState
from .service import NotificationService


CHANNEL_LABELS = {
    "announcement": "公告",
    "match": "赛事",
    "forum": "开源",
}


class NotificationCommandHandler:
    def __init__(
        self,
        plugin: Any,
        monitor_state: MonitorState,
        notifications: NotificationService,
        background_tasks: BackgroundTaskManager,
    ):
        self.plugin = plugin
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.background_tasks = background_tasks

    async def subscribe(self, event: AstrMessageEvent, channel: str) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        if not session:
            yield event.plain_result("订阅失败：无法获取当前会话 ID。")
            return
        label = CHANNEL_LABELS.get(channel, channel)
        added, lark_card_hint = self.notifications.subscribe_session(
            channel,
            event,
            session,
            self.plugin.event_session_ids(event),
        )
        suffix = "\n已记录飞书卡片运行时信息。" if lark_card_hint else ""
        yield event.plain_result(
            (f"已订阅 RM {label}通知。" if added else f"当前会话已订阅 RM {label}通知。")
            + suffix
        )

    async def unsubscribe(self, event: AstrMessageEvent, channel: str) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        label = CHANNEL_LABELS.get(channel, channel)
        removed = self.notifications.unsubscribe_session(channel, session)
        yield event.plain_result(
            f"已取消订阅 RM {label}通知。" if removed else f"当前会话未订阅 RM {label}通知。"
        )

    async def status(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result("\n".join(self.background_tasks.status_lines()))
