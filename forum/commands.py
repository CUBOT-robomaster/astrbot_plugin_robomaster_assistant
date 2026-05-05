from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.privacy import mask_identifier
from ..notifications.notification import plain_chain
from .monitor import ForumMonitor
from .service import ForumService


class ForumCommandHandler:
    def __init__(
        self,
        plugin: Any,
        forum: ForumService,
        forum_monitor: ForumMonitor,
    ):
        self.plugin = plugin
        self.forum = forum
        self.forum_monitor = forum_monitor

    async def reply_help(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result(self.forum.help_text())

    async def search(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        message = self.plugin._message_text(event)
        if message == "开源查询帮助":
            async for result in self.reply_help(event):
                yield result
            return

        if not message.startswith("开源查询 "):
            return
        if not self.plugin._is_session_allowed(event):
            return

        query = message.removeprefix("开源查询 ").strip()
        self.plugin._stop_event(event)
        if not query:
            yield event.plain_result(self.forum.help_text())
            return

        response = await self.forum.search(query, event)
        yield event.plain_result(self.forum.format_search_response(response))

    async def check(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result("正在检查 RM 论坛开源内容...")

        session = getattr(event, "unified_msg_origin", "")
        try:
            events = await self.forum_monitor.run_check(
                force_notify=True,
                on_progress=lambda text: self.send_progress(session, text),
            )
        except Exception as exc:
            yield event.plain_result(f"RM 开源检查失败：{exc}")
            return

        yield event.plain_result(self.forum.format_check_response(events))

    async def rebuild_index(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result(await self.forum.rebuild_index())

    async def import_jsonl(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        seen, inserted = await self.forum.import_jsonl()
        yield event.plain_result(f"RM 开源导入完成\n读取行：{seen}\n新增文章：{inserted}")

    async def send_progress(self, session: str, text: str) -> None:
        if not session:
            return
        try:
            await self.plugin.context.send_message(session, plain_chain(text))
        except Exception as exc:
            logger.warning(
                f"RM 开源检查进度通知发送失败 {mask_identifier(session)}: {exc}"
            )
