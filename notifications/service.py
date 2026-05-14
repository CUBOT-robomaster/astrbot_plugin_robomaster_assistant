from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.network import is_public_url
from ..core.event_platform import is_lark_event
from ..core.privacy import mask_identifier, mask_url
from ..core.state import MonitorState, session_key
from .lark_enhance_card import send_lark_card
from .notification import CircuitBreaker, plain_chain


LARK_CARD_KEYS = {
    "announcement": "announce_enable_lark_card_notifications",
    "match": "match_enable_lark_card_notifications",
    "forum": "forum_enable_lark_card_notifications",
}


class NotificationService:
    def __init__(
        self,
        context: Any,
        config: Any,
        monitor_state: MonitorState,
        lark_clients: dict[str, Any],
        circuit_breaker: CircuitBreaker,
    ):
        self.context = context
        self.config = config
        self.monitor_state = monitor_state
        self.lark_clients = lark_clients
        self.circuit_breaker = circuit_breaker
        self.breaker_notice_recover_at = 0.0

    async def notify(
        self,
        text: str,
        payload: dict[str, Any],
        event_type: str,
        channel: str,
    ) -> None:
        previous_recover_at = self.circuit_breaker.recover_at
        allowed, reason = self.circuit_breaker.allow()
        self._sync_circuit_breaker_state(previous_recover_at)
        if not allowed:
            logger.warning(f"RM 通知熔断：{reason}")
            await self.notify_breaker_once(reason, channel)
            return

        sessions = self.sessions(channel)
        for session in sessions:
            if await self.try_send_lark_card_notification(channel, session, text, event_type):
                continue
            try:
                await self.context.send_message(session, plain_chain(text))
            except Exception as exc:
                logger.warning(f"RM 主动推送失败 {mask_identifier(session)}: {exc}")

        if self.config._config_bool("external_webhook_enabled", False):
            await self.send_external_webhooks({"type": event_type, "data": payload})

    async def try_send_lark_card_notification(
        self,
        channel: str,
        session: str,
        text: str,
        event_type: str,
    ) -> bool:
        if not self.config._config_bool(lark_card_key(channel), False):
            return False
        lark_client = self.lark_clients.get(lark_client_key(channel, session))
        chat_id = self.monitor_state.lark_chat_id(channel, session)
        if lark_client is None or not chat_id:
            return False
        try:
            sent = await send_lark_card(
                lark_client,
                chat_id=chat_id,
                text=text,
                event_type=event_type,
            )
            if not sent:
                logger.warning(f"RM 飞书卡片发送失败，降级文本：{mask_identifier(session)}")
            return sent
        except Exception as exc:
            logger.warning(f"RM 飞书卡片发送异常，降级文本 {mask_identifier(session)}: {exc}")
            return False

    def _sync_circuit_breaker_state(self, previous_recover_at: float) -> None:
        recover_at = self.circuit_breaker.recover_at
        if recover_at != previous_recover_at:
            self.monitor_state.set_notification_circuit_breaker_recover_at(recover_at)

    def remember_lark_runtime(self, channel: str, event: AstrMessageEvent, session: str) -> bool:
        if not is_lark_event(event):
            return False
        lark_client = getattr(event, "bot", None)
        chat_id = lark_chat_id_from_event(event)
        if lark_client is None or not chat_id:
            return False
        self.lark_clients[lark_client_key(channel, session)] = lark_client
        self.monitor_state.set_lark_session(channel, session, chat_id)
        return True

    def forget_lark_runtime(self, channel: str, session: str) -> None:
        self.lark_clients.pop(lark_client_key(channel, session), None)

    def subscribe_session(
        self,
        channel: str,
        event: AstrMessageEvent,
        session: str,
        aliases: set[str] | list[str],
    ) -> tuple[bool, bool]:
        self.monitor_state.remember_session_aliases(session, aliases)
        added = self.monitor_state.add_session(channel, session)
        lark_card_hint = self.remember_lark_runtime(channel, event, session)
        return added, lark_card_hint

    def unsubscribe_session(self, channel: str, session: str) -> bool:
        removed = self.monitor_state.remove_session(channel, session)
        self.forget_lark_runtime(channel, session)
        return removed

    async def notify_breaker_once(self, reason: str, channel: str) -> None:
        recover_at = self.circuit_breaker.recover_at
        if recover_at <= 0 or recover_at == self.breaker_notice_recover_at:
            return
        self.breaker_notice_recover_at = recover_at
        sessions = self.sessions(channel)
        text = f"RM 通知触发熔断，后续通知将暂时静默。\n{reason}"
        for session in sessions:
            try:
                await self.context.send_message(session, plain_chain(text))
            except Exception as exc:
                logger.warning(f"RM 熔断提示发送失败 {mask_identifier(session)}: {exc}")

    async def send_external_webhooks(self, body: dict[str, Any]) -> None:
        urls = self.config._config_url_list("external_webhook_urls")
        if not urls:
            return
        try:
            import httpx
        except ImportError as exc:
            logger.warning(f"RM 外部 Webhook 缺少 httpx：{exc}")
            return

        async with httpx.AsyncClient(timeout=10) as client:
            for url in urls:
                if not await is_public_url(url):
                    logger.warning(f"RM 外部 Webhook 地址不安全或无效，已跳过：{mask_url(url)}")
                    continue
                try:
                    response = await client.post(url, json=body)
                    if response.status_code < 200 or response.status_code >= 300:
                        logger.warning(
                            "RM 外部 Webhook 返回非成功状态 "
                            f"{response.status_code}：{mask_url(url)}"
                        )
                except Exception as exc:
                    logger.warning(f"RM 外部 Webhook 发送失败 {mask_url(url)}: {exc}")

    def sessions(self, channel: str) -> list[str]:
        sessions = list(self.monitor_state.sessions(channel))
        for value in self.config._config_url_list(session_key(channel)):
            resolved = self.monitor_state.resolve_session(value)
            if resolved:
                sessions.append(resolved)
                continue
            logger.warning(
                "RM 推送会话无法解析，已跳过："
                f"{mask_identifier(value)}。请先在目标群执行订阅命令或任意插件命令，让机器人记录会话映射。"
            )
        return list(dict.fromkeys(sessions))


def lark_chat_id_from_event(event: AstrMessageEvent) -> str:
    message_obj = getattr(event, "message_obj", None)
    if message_obj is not None:
        group_id = str(getattr(message_obj, "group_id", "")).strip()
        if group_id:
            return group_id
    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""
    return ""


def lark_card_key(channel: str) -> str:
    return LARK_CARD_KEYS.get(channel, f"{channel}_enable_lark_card_notifications")


def lark_client_key(channel: str, session: str) -> str:
    return f"{channel}:{session}"
