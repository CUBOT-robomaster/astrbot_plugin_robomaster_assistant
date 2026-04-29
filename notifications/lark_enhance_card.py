from __future__ import annotations

import json
import uuid
from typing import Any


class LarkCardBuilder:
    """Small card builder adapted from astrbot_lark_enhance's runtime-client style."""

    def __init__(self):
        self._elements: list[dict[str, Any]] = []
        self._config = {"wide_screen_mode": True}

    def markdown(self, content: str) -> "LarkCardBuilder":
        self._elements.append({"tag": "markdown", "content": content})
        return self

    def divider(self) -> "LarkCardBuilder":
        self._elements.append({"tag": "hr"})
        return self

    def build(self) -> str:
        card = {
            "schema": "2.0",
            "config": self._config,
            "body": {
                "elements": self._elements,
            },
        }
        return json.dumps(card, ensure_ascii=False)

    @classmethod
    def notification_card(cls, text: str, event_type: str) -> str:
        title, body = _split_title_body(text)
        return (
            cls()
            .markdown(f"**{_event_title(event_type, title)}**")
            .divider()
            .markdown(body or title)
            .build()
        )


async def send_lark_card(
    lark_client: Any,
    *,
    chat_id: str,
    text: str,
    event_type: str,
) -> bool:
    from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

    im = getattr(lark_client, "im", None)
    if im is None or im.v1 is None or im.v1.message is None:
        return False

    content = LarkCardBuilder.notification_card(text, event_type)
    request = (
        CreateMessageRequest.builder()
        .receive_id_type("chat_id")
        .request_body(
            CreateMessageRequestBody.builder()
            .receive_id(chat_id)
            .msg_type("interactive")
            .content(content)
            .uuid(str(uuid.uuid4()))
            .build()
        )
        .build()
    )
    response = await im.v1.message.acreate(request)
    return bool(response.success())


def _split_title_body(text: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in text.splitlines()]
    title = next((line for line in lines if line.strip()), "RM 通知")
    body = "\n".join(lines[1:]).strip() if len(lines) > 1 else ""
    return title, body


def _event_title(event_type: str, fallback: str) -> str:
    titles = {
        "announcement_new": "RM 官网公告新增",
        "announcement_update": "RM 官网公告更新",
        "match_start": "RoboMaster 比赛开始",
        "match_session_end": "RoboMaster 单局结束",
        "match_end": "RoboMaster 比赛结束",
        "forum_article_new": "RoboMaster 论坛开源更新",
    }
    return titles.get(event_type, fallback)
