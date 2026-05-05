from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .announcement.service import AnnouncementService
from .core.background_tasks import BackgroundTaskManager
from .core.constants import PLUGIN_NAME, PLUGIN_VERSION
from .core.plugin_config import ConfigSessionMixin
from .core.state import MonitorState
from .core.storage import plugin_state_path
from .forum.commands import ForumCommandHandler
from .forum.monitor import ForumMonitor
from .forum.service import ForumService
from .manual.commands import ManualCommandHandler
from .manual.reply import ManualReplyBuilder
from .manual.service import ManualService
from .match.service import MatchPushService
from .notifications.commands import NotificationCommandHandler
from .notifications.notification import CircuitBreaker
from .notifications.service import NotificationService


@register(
    PLUGIN_NAME,
    "RoboMaster赛事助手 contributors",
    "RoboMaster赛事助手：规则手册检索、RM 公告监控、赛事监控",
    PLUGIN_VERSION,
)
class Main(ConfigSessionMixin, Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config
        self.monitor_state = MonitorState(plugin_state_path())
        self.circuit_breaker = CircuitBreaker(
            recover_at=self.monitor_state.notification_circuit_breaker_recover_at()
        )
        self._lark_clients: dict[str, Any] = {}
        self.manual = ManualService(context, self)
        self.manual_reply = ManualReplyBuilder(self, self.manual.image_cache_dir)
        self.forum = ForumService(context, self)
        self.notifications = NotificationService(
            context,
            self,
            self.monitor_state,
            self._lark_clients,
            self.circuit_breaker,
        )
        self.announcement = AnnouncementService(
            self,
            self.monitor_state,
            self.notifications,
        )
        self.match_push = MatchPushService(
            self,
            self.monitor_state,
            self.notifications,
        )
        self.forum_monitor = ForumMonitor(
            self.monitor_state,
            self.notifications,
            self.forum,
        )
        self.background_tasks = BackgroundTaskManager(
            self,
            self.monitor_state,
            self._lark_clients,
            self.announcement,
            self.match_push,
            self.forum_monitor,
            self.forum,
        )
        self.manual_commands = ManualCommandHandler(self, self.manual, self.manual_reply)
        self.forum_commands = ForumCommandHandler(self, self.forum, self.forum_monitor)
        self.notification_commands = NotificationCommandHandler(
            self,
            self.monitor_state,
            self.notifications,
            self._lark_clients,
            self.background_tasks,
        )

    @filter.on_astrbot_loaded()
    async def on_astrbot_loaded(self):
        """AstrBot 初始化完成后启动后台监控任务。"""
        self.background_tasks.start()

    @filter.command("规则手册帮助")
    async def manual_help_command(self, event: AstrMessageEvent):
        """查看 RoboMaster 规则手册检索插件帮助。"""
        async for result in self.manual_commands.reply_help(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("重建规则手册索引")
    async def rebuild_command(self, event: AstrMessageEvent):
        """管理员重新扫描 PDF 目录并更新规则手册索引。"""
        async for result in self.manual_commands.rebuild(event):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def route_plain_text_commands(self, event: AstrMessageEvent):
        """路由需要自行解析前缀的纯文本命令。"""
        message = self._message_text(event)
        if message.startswith("更新规则手册 "):
            async for result in self.manual_commands.update_plain_text(event):
                yield result
            return
        if message.startswith("规则手册 "):
            async for result in self.manual_commands.search(event):
                yield result
            return
        if message.startswith("开源查询 "):
            async for result in self.forum_commands.search(event):
                yield result

    @filter.command("开源查询帮助")
    async def forum_help_command(self, event: AstrMessageEvent):
        """查看 RoboMaster 论坛开源查询帮助。"""
        async for result in self.forum_commands.reply_help(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM订阅通知")
    async def subscribe_rm_notifications(self, event: AstrMessageEvent):
        """订阅 RM 公告和赛事监控通知。"""
        async for result in self.notification_commands.subscribe(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM取消订阅")
    async def unsubscribe_rm_notifications(self, event: AstrMessageEvent):
        """取消订阅 RM 公告和赛事监控通知。"""
        async for result in self.notification_commands.unsubscribe(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM监控状态")
    async def rm_monitor_status(self, event: AstrMessageEvent):
        """查看 RM 公告和赛事监控状态。"""
        async for result in self.notification_commands.status(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM公告检查")
    async def rm_announce_check(self, event: AstrMessageEvent):
        """立即执行一次 RM 官网公告检查。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        events = await self.announcement.run_check()
        yield event.plain_result(f"RM 公告检查完成，发现 {len(events)} 条通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM赛事检查")
    async def rm_match_check(self, event: AstrMessageEvent):
        """立即执行一次 RoboMaster 赛事状态检查。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        events = await self.match_push.run_check()
        yield event.plain_result(f"RM 赛事检查完成，发现 {len(events)} 条通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源检查")
    async def rm_forum_check(self, event: AstrMessageEvent):
        """立即执行一次 RoboMaster 论坛开源检查。"""
        async for result in self.forum_commands.check(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源重建索引")
    async def rm_forum_rebuild_index(self, event: AstrMessageEvent):
        """从论坛文章库重建开源资料索引。"""
        async for result in self.forum_commands.rebuild_index(event):
            yield result

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源导入")
    async def rm_forum_import(self, event: AstrMessageEvent):
        """导入 forum/imports 目录中的外部 JSONL 开源文章。"""
        async for result in self.forum_commands.import_jsonl(event):
            yield result

    async def terminate(self):
        """插件卸载时释放后台任务和内存索引。"""
        await self.background_tasks.stop()
        await self.forum.close()
        self.manual.clear()
        self.monitor_state.save()
