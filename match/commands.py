from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from astrbot.api.event import AstrMessageEvent

from .reply import MatchReplyBuilder
from .service import MatchPushService


class MatchCommandHandler:
    def __init__(self, plugin: Any, match_push: MatchPushService):
        self.plugin = plugin
        self.match_push = match_push
        self.reply = MatchReplyBuilder(plugin)

    async def reply_help(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        yield event.plain_result(self.match_push.help_text())

    async def query(self, event: AstrMessageEvent) -> AsyncIterator[Any]:
        message = self.plugin._message_text(event)
        if not self.plugin._is_session_allowed(event):
            return
        self.plugin._stop_event(event)
        query = message.removeprefix("赛事查询").strip()
        response = await self.match_push.query(query, event)
        async for result in self.reply.build(event, response):
            yield result
