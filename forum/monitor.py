from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable

from ..core.state import MonitorState
from ..notifications.service import NotificationService
from .models import ForumArticle
from .service import ForumService


class ForumMonitor:
    def __init__(
        self,
        monitor_state: MonitorState,
        notifications: NotificationService,
        forum: ForumService,
    ):
        self.monitor_state = monitor_state
        self.notifications = notifications
        self.forum = forum
        self.lock = asyncio.Lock()

    async def run_check(
        self,
        force_notify: bool = False,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> list[ForumArticle]:
        async with self.lock:
            return await self._run_check_unlocked(
                force_notify=force_notify,
                on_progress=on_progress,
            )

    async def _run_check_unlocked(
        self,
        force_notify: bool = False,
        on_progress: Callable[[str], Awaitable[None]] | None = None,
    ) -> list[ForumArticle]:
        initialized = bool(self.monitor_state.data.get("forum_initialized", False))
        notify = True if force_notify else initialized
        events = await self.forum.check(notify=notify, on_progress=on_progress)
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
