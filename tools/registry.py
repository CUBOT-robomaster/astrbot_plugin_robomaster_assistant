from __future__ import annotations

from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass

from astrbot.api.event import MessageChain
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool, ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

from ..core.constants import LAZY_REBUILD_NOTICE, NO_RESULT_TEXT


SESSION_DENIED_TEXT = "当前会话不允许使用 RoboMaster 赛事助手。"
ADMIN_DENIED_TEXT = "此 Tool 仅管理员可用。"
NO_EVENT_TEXT = "无法获取当前会话上下文。"


def build_llm_tools(plugin: Any) -> list[FunctionTool[AstrAgentContext]]:
    return [
        RmManualSearchTool(plugin=plugin),
        RmManualHelpTool(plugin=plugin),
        RmForumSearchTool(plugin=plugin),
        RmForumHelpTool(plugin=plugin),
        RmMonitorStatusTool(plugin=plugin),
        RmManualUpdateTool(plugin=plugin),
        RmManualRebuildIndexTool(plugin=plugin),
        RmForumCheckTool(plugin=plugin),
        RmForumRebuildIndexTool(plugin=plugin),
        RmForumImportJsonlTool(plugin=plugin),
        RmNotificationSubscribeTool(plugin=plugin),
        RmNotificationUnsubscribeTool(plugin=plugin),
        RmAnnouncementCheckTool(plugin=plugin),
        RmMatchCheckTool(plugin=plugin),
    ]


@dataclass(config={"arbitrary_types_allowed": True})
class RmBaseTool(FunctionTool[AstrAgentContext]):
    plugin: Any = Field(default=None, exclude=True)

    def event_from_context(self, context: ContextWrapper[AstrAgentContext]) -> Any | None:
        agent_context = getattr(context, "context", None)
        return getattr(agent_context, "event", None)

    def permission_error(
        self,
        context: ContextWrapper[AstrAgentContext],
        *,
        admin: bool = False,
    ) -> str | None:
        event = self.event_from_context(context)
        if event is None:
            return NO_EVENT_TEXT
        if not self.plugin._is_session_allowed(event):
            return SESSION_DENIED_TEXT
        if admin and not self.plugin._is_admin(event):
            return ADMIN_DENIED_TEXT
        return None


@dataclass(config={"arbitrary_types_allowed": True})
class RmManualSearchTool(RmBaseTool):
    name: str = "rm_manual_search"
    description: str = (
        "查询 RoboMaster 规则手册，并按插件配置向当前会话发送文本、截图、"
        "合并转发或完整图文结果。"
    )
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查询的规则、术语、接口、协议或问题。",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context):
            return error
        event = self.event_from_context(context)
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return self.plugin.manual.help_text()
        if self.plugin.manual.needs_lazy_rebuild():
            await send_event_result(event, event.plain_result(LAZY_REBUILD_NOTICE))
        response = await self.plugin.manual.search(query, event)
        if not response.located_results:
            await send_event_result(event, event.plain_result(NO_RESULT_TEXT))
            return "规则手册检索未找到可靠依据，已发送提示；不要再重复回复用户。"
        async for result in self.plugin.manual_reply.build(event, response):
            await send_event_result(event, result)
        return "已按规则手册命令流程发送检索结果；不要再重复回复用户。"


@dataclass(config={"arbitrary_types_allowed": True})
class RmManualHelpTool(RmBaseTool):
    name: str = "rm_manual_help"
    description: str = "查看 RoboMaster 规则手册检索功能帮助。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context):
            return error
        return self.plugin.manual.help_text()


@dataclass(config={"arbitrary_types_allowed": True})
class RmForumSearchTool(RmBaseTool):
    name: str = "rm_forum_search"
    description: str = "查询已收录的 RoboMaster 论坛开源资料。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "要查询的开源项目、技术栈、场景或关键词。",
                },
            },
            "required": ["query"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context):
            return error
        event = self.event_from_context(context)
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return self.plugin.forum.help_text()
        response = await self.plugin.forum.search(query, event)
        return self.plugin.forum.format_search_response(response)


@dataclass(config={"arbitrary_types_allowed": True})
class RmForumHelpTool(RmBaseTool):
    name: str = "rm_forum_help"
    description: str = "查看 RoboMaster 论坛开源资料查询功能帮助。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context):
            return error
        return self.plugin.forum.help_text()


@dataclass(config={"arbitrary_types_allowed": True})
class RmMonitorStatusTool(RmBaseTool):
    name: str = "rm_monitor_status"
    description: str = "查看 RM 公告、赛事、论坛、订阅和后台任务状态。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context):
            return error
        return "\n".join(self.plugin.background_tasks.status_lines())


@dataclass(config={"arbitrary_types_allowed": True})
class RmManualUpdateTool(RmBaseTool):
    name: str = "rm_manual_update"
    description: str = "管理员工具：通过 HTTPS PDF 链接更新规则手册并重建索引。"
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "pdf_url": {
                    "type": "string",
                    "description": "规则手册 PDF 的 HTTPS 下载链接。",
                },
            },
            "required": ["pdf_url"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        pdf_url = str(kwargs.get("pdf_url") or "").strip()
        if not pdf_url:
            return "请提供规则手册 PDF 的 HTTPS 下载链接。"
        messages = [message async for message in self.plugin.manual.update_from_text(pdf_url)]
        return "\n\n".join(messages)


@dataclass(config={"arbitrary_types_allowed": True})
class RmManualRebuildIndexTool(RmBaseTool):
    name: str = "rm_manual_rebuild_index"
    description: str = "管理员工具：重建规则手册 PDF 检索索引。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        return await self.plugin.manual.rebuild()


@dataclass(config={"arbitrary_types_allowed": True})
class RmForumCheckTool(RmBaseTool):
    name: str = "rm_forum_check"
    description: str = "管理员工具：立即检查 RoboMaster 论坛开源内容，可能触发新文章通知。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        try:
            events = await self.plugin.forum_monitor.run_check(force_notify=True)
        except Exception as exc:
            return f"RM 开源检查失败：{exc}"
        return self.plugin.forum.format_check_response(events)


@dataclass(config={"arbitrary_types_allowed": True})
class RmForumRebuildIndexTool(RmBaseTool):
    name: str = "rm_forum_rebuild_index"
    description: str = "管理员工具：从论坛文章库重建开源资料索引。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        return await self.plugin.forum.rebuild_index()


@dataclass(config={"arbitrary_types_allowed": True})
class RmForumImportJsonlTool(RmBaseTool):
    name: str = "rm_forum_import_jsonl"
    description: str = "管理员工具：导入 forum/imports 目录中的外部 JSONL 开源文章。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        seen, inserted = await self.plugin.forum.import_jsonl()
        return f"RM 开源导入完成\n读取行：{seen}\n新增文章：{inserted}"


@dataclass(config={"arbitrary_types_allowed": True})
class RmNotificationSubscribeTool(RmBaseTool):
    name: str = "rm_notification_subscribe"
    description: str = "管理员工具：订阅当前会话接收 RM 公告、赛事和论坛开源通知。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        event = self.event_from_context(context)
        session = getattr(event, "unified_msg_origin", "")
        if not session:
            return "订阅失败：无法获取当前会话 ID。"
        added = self.plugin.monitor_state.add_session(session)
        lark_card_hint = self.plugin.notifications.remember_lark_runtime(event, session)
        suffix = "\n已记录飞书卡片运行时信息。" if lark_card_hint else ""
        return ("已订阅 RM 通知。" if added else "当前会话已订阅 RM 通知。") + suffix


@dataclass(config={"arbitrary_types_allowed": True})
class RmNotificationUnsubscribeTool(RmBaseTool):
    name: str = "rm_notification_unsubscribe"
    description: str = "管理员工具：取消当前会话的 RM 通知订阅。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        event = self.event_from_context(context)
        session = getattr(event, "unified_msg_origin", "")
        removed = self.plugin.monitor_state.remove_session(session)
        self.plugin._lark_clients.pop(session, None)
        return "已取消订阅 RM 通知。" if removed else "当前会话未订阅 RM 通知。"


@dataclass(config={"arbitrary_types_allowed": True})
class RmAnnouncementCheckTool(RmBaseTool):
    name: str = "rm_announcement_check"
    description: str = "管理员工具：立即执行一次 RM 官网公告检查，可能触发通知推送。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        events = await self.plugin.announcement.run_check()
        return f"RM 公告检查完成，发现 {len(events)} 条通知。"


@dataclass(config={"arbitrary_types_allowed": True})
class RmMatchCheckTool(RmBaseTool):
    name: str = "rm_match_check"
    description: str = "管理员工具：立即执行一次 RoboMaster 赛事状态检查，可能触发通知推送。"
    parameters: dict = Field(default_factory=lambda: {"type": "object", "properties": {}})

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if error := self.permission_error(context, admin=True):
            return error
        events = await self.plugin.match_push.run_check()
        return f"RM 赛事检查完成，发现 {len(events)} 条通知。"


async def send_event_result(event: Any, result: Any) -> None:
    sender = getattr(event, "send", None)
    if not callable(sender):
        raise RuntimeError("当前事件不支持主动发送消息。")
    if isinstance(result, MessageChain):
        await sender(MessageChain(chain=list(result.chain)))
        return
    if isinstance(result, str):
        await sender(MessageChain().message(result))
        return
    raise TypeError(f"不支持的消息结果类型：{type(result).__name__}")
