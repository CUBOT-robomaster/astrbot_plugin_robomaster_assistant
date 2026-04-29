from __future__ import annotations

from typing import Any

from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.constants import NO_RESULT_TEXT, PLUGIN_NAME, PLUGIN_VERSION
from .core.plugin_config import ConfigSessionMixin
from .core.storage import plugin_state_path
from .forum.service import ForumService
from .manual.reply import ManualReplyBuilder
from .manual.service import ManualService
from .monitors.monitor_state import MonitorState
from .monitors.service import MonitorService
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
        self.config = config if config is not None else {}
        self.monitor_state = MonitorState(plugin_state_path())
        self.circuit_breaker = CircuitBreaker()
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
        self.monitors = MonitorService(
            self,
            self.monitor_state,
            self.notifications,
            self._lark_clients,
            self.forum,
        )
        self.monitors.start_tasks()

    @filter.command("规则手册帮助")
    async def manual_help_command(self, event: AstrMessageEvent):
        """查看 RoboMaster 规则手册检索插件帮助。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        yield event.plain_result(self.manual.help_text())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("重建规则手册索引")
    async def rebuild_command(self, event: AstrMessageEvent):
        """管理员重新扫描 PDF 目录并更新规则手册索引。"""
        if not self._is_session_allowed(event):
            return
        async for result in self._rebuild_and_reply(event):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def update_manual_plain_text(self, event: AstrMessageEvent):
        """管理员发送 HTTPS 链接下载并更新规则手册。"""
        message = self._message_text(event)
        if message != "更新规则手册" and not message.startswith("更新规则手册 "):
            return
        if not self._is_session_allowed(event):
            return
        if not self._is_admin(event):
            self._stop_event(event)
            yield event.plain_result(
                "此命令仅管理员可用。请通过 /sid 获取 ID 后让管理员添加权限。"
            )
            return

        text = message.removeprefix("更新规则手册").strip()
        async for result in self._update_manuals_and_reply(event, text):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def search_manual(self, event: AstrMessageEvent):
        """监听“规则手册 xxx”并检索本地 PDF 规则手册。"""
        message = self._message_text(event)
        if message == "规则手册帮助":
            if not self._is_session_allowed(event):
                return
            self._stop_event(event)
            yield event.plain_result(self.manual.help_text())
            return

        if not message.startswith("规则手册 "):
            return
        if not self._is_session_allowed(event):
            return

        query = message.removeprefix("规则手册 ").strip()
        self._stop_event(event)
        if not query:
            yield event.plain_result(self.manual.help_text())
            return

        response = await self.manual.search(query, event)
        if not response.located_results:
            yield event.plain_result(NO_RESULT_TEXT)
            return

        async for result in self.manual_reply.build(event, response):
            yield result

    @filter.command("开源查询帮助")
    async def forum_help_command(self, event: AstrMessageEvent):
        """查看 RoboMaster 论坛开源查询帮助。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        yield event.plain_result(self.forum.help_text())

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def search_forum(self, event: AstrMessageEvent):
        """监听“开源查询 xxx”并检索论坛开源资料库。"""
        message = self._message_text(event)
        if message == "开源查询帮助":
            if not self._is_session_allowed(event):
                return
            self._stop_event(event)
            yield event.plain_result(self.forum.help_text())
            return

        if not message.startswith("开源查询 "):
            return
        if not self._is_session_allowed(event):
            return

        query = message.removeprefix("开源查询 ").strip()
        self._stop_event(event)
        if not query:
            yield event.plain_result(self.forum.help_text())
            return

        response = await self.forum.search(query, event)
        yield event.plain_result(self.forum.format_search_response(response))

    async def _rebuild_and_reply(self, event: AstrMessageEvent):
        self._stop_event(event)
        yield event.plain_result(await self.manual.rebuild())

    async def _update_manuals_and_reply(self, event: AstrMessageEvent, text: str):
        self._stop_event(event)
        async for message in self.manual.update_from_text(text):
            yield event.plain_result(message)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM订阅通知")
    async def subscribe_rm_notifications(self, event: AstrMessageEvent):
        """订阅 RM 公告和赛事监控通知。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
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

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM取消订阅")
    async def unsubscribe_rm_notifications(self, event: AstrMessageEvent):
        """取消订阅 RM 公告和赛事监控通知。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        removed = self.monitor_state.remove_session(session)
        self._lark_clients.pop(session, None)
        yield event.plain_result("已取消订阅 RM 通知。" if removed else "当前会话未订阅 RM 通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM监控状态")
    async def rm_monitor_status(self, event: AstrMessageEvent):
        """查看 RM 公告和赛事监控状态。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        yield event.plain_result(self.monitors.status_text())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM公告检查")
    async def rm_announce_check(self, event: AstrMessageEvent):
        """立即执行一次 RM 官网公告检查。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        events = await self.monitors.run_announce_check()
        yield event.plain_result(f"RM 公告检查完成，发现 {len(events)} 条通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM赛事检查")
    async def rm_match_check(self, event: AstrMessageEvent):
        """立即执行一次 RoboMaster 赛事状态检查。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        events = await self.monitors.run_match_check()
        yield event.plain_result(f"RM 赛事检查完成，发现 {len(events)} 条通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源检查")
    async def rm_forum_check(self, event: AstrMessageEvent):
        """立即执行一次 RoboMaster 论坛开源检查。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        events = await self.monitors.run_forum_check()
        yield event.plain_result(f"RM 开源检查完成，发现 {len(events)} 条新推送。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源重建索引")
    async def rm_forum_rebuild_index(self, event: AstrMessageEvent):
        """从论坛文章库重建开源资料索引。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        yield event.plain_result(await self.forum.rebuild_index())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM开源导入")
    async def rm_forum_import(self, event: AstrMessageEvent):
        """导入 forum/imports 目录中的外部 JSONL 开源文章。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        seen, inserted = await self.forum.import_jsonl()
        yield event.plain_result(f"RM 开源导入完成\n读取行：{seen}\n新增文章：{inserted}")

    async def terminate(self):
        """插件卸载时释放后台任务和内存索引。"""
        await self.monitors.stop_tasks()
        await self.forum.close()
        self.manual.clear()
        self.monitor_state.save()
