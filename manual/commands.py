from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ..core.constants import NO_RESULT_TEXT
from .reply import ManualReplyBuilder
from .service import ManualService


class ManualCommandHandler:
    def __init__(
        self,
        plugin: Any,
        manual: ManualService,
        reply_builder: ManualReplyBuilder,
    ):
        self.plugin = plugin
        self.manual = manual
        self.reply_builder = reply_builder

    async def reply_help(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result(self.manual.help_text())

    async def rebuild(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result(await self.manual.rebuild())

    async def update_plain_text(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        message = self.plugin._message_text(event)
        if message != "更新规则手册" and not message.startswith("更新规则手册 "):
            return
        if not self.plugin._is_session_allowed(event):
            return
        if not self.plugin._is_admin(event):
            self.plugin._stop_event(event)
            yield event.plain_result(
                "此命令仅管理员可用。请通过 /sid 获取 ID 后让管理员添加权限。"
            )
            return

        self.plugin._stop_event(event)
        text = message.removeprefix("更新规则手册").strip()
        async for message in self.manual.update_from_text(text):
            yield event.plain_result(message)

    async def search(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        message = self.plugin._message_text(event)
        if message == "规则手册帮助":
            async for result in self.reply_help(event):
                yield result
            return

        if not message.startswith("规则手册 "):
            return
        if not self.plugin._is_session_allowed(event):
            return

        query = message.removeprefix("规则手册 ").strip()
        self.plugin._stop_event(event)
        if not query:
            yield event.plain_result(self.manual.help_text())
            return

        response = await self.manual.search(query, event)
        if not response.located_results:
            yield event.plain_result(NO_RESULT_TEXT)
            return

        async for result in self.reply_builder.build(event, response):
            yield result
