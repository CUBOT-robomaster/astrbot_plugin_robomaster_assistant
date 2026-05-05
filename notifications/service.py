from __future__ import annotations

from typing import Any

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.network import is_public_url
from ..core.event_platform import is_lark_event
from ..core.privacy import mask_identifier, mask_url
from ..core.state import MonitorState
from .lark_enhance_card import send_lark_card
from .notification import CircuitBreaker, plain_chain


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

    async def notify(self, text: str, payload: dict[str, Any], event_type: str) -> None:
        previous_recover_at = self.circuit_breaker.recovery_timestamp()
        allowed, reason = self.circuit_breaker.allow()
        self._sync_circuit_breaker_state(previous_recover_at)
        if not allowed:
            logger.warning(f"RM 通知熔断：{reason}")
            await self.notify_breaker_once(reason)
            return

        sessions = list(dict.fromkeys(self.monitor_state.sessions + self.config._config_url_list("notify_sessions")))
        for session in sessions:
            if await self.try_send_lark_card_notification(session, text, event_type):
                continue
            try:
                await self.context.send_message(session, plain_chain(text))
            except Exception as exc:
                logger.warning(f"RM 主动推送失败 {mask_identifier(session)}: {exc}")

        if self.config._config_bool("external_webhook_enabled", False):
            await self.send_external_webhooks({"type": event_type, "data": payload})

    async def try_send_lark_card_notification(
        self,
        session: str,
        text: str,
        event_type: str,
    ) -> bool:
        if not self.config._config_bool("enable_lark_card_notifications", False):
            return False
        lark_client = self.lark_clients.get(session)
        chat_id = self.monitor_state.lark_chat_id(session)
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
        recover_at = self.circuit_breaker.recovery_timestamp()
        if recover_at != previous_recover_at:
            self.monitor_state.set_notification_circuit_breaker_recover_at(recover_at)

    def remember_lark_runtime(self, event: AstrMessageEvent, session: str) -> bool:
        if not is_lark_event(event):
            return False
        lark_client = getattr(event, "bot", None)
        chat_id = lark_chat_id_from_event(event)
        if lark_client is None or not chat_id:
            return False
        self.lark_clients[session] = lark_client
        self.monitor_state.set_lark_session(session, chat_id)
        return True

    async def notify_breaker_once(self, reason: str) -> None:
        recover_at = getattr(self.circuit_breaker, "recover_at", 0.0)
        if recover_at <= 0 or recover_at == self.breaker_notice_recover_at:
            return
        self.breaker_notice_recover_at = recover_at
        sessions = list(dict.fromkeys(self.monitor_state.sessions + self.config._config_url_list("notify_sessions")))
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
        except Exception as exc:
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


def lark_chat_id_from_event(event: AstrMessageEvent) -> str:
    message_obj = getattr(event, "message_obj", None)
    if message_obj is not None:
        group_id = str(getattr(message_obj, "group_id", "") or "").strip()
        if group_id:
            return group_id
    getter = getattr(event, "get_sender_id", None)
    if callable(getter):
        try:
            return str(getter() or "").strip()
        except Exception:
            return ""
    return ""
