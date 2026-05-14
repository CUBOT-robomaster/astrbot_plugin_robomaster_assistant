from __future__ import annotations

from pathlib import Path
from typing import Any, AsyncIterator

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from .models import MatchRecord
from .query.formatters import format_match_line
from .query.types import MatchQueryResponse


class MatchReplyBuilder:
    def __init__(self, config: Any):
        self.config = config

    async def build(
        self,
        event: AstrMessageEvent,
        response: MatchQueryResponse,
    ) -> AsyncIterator[Any]:
        if self.should_forward(event, response):
            try:
                yield event.chain_result(self.build_forward_chain(response))
                return
            except Exception as exc:
                logger.warning(f"RM 赛事合并转发消息构建失败：{exc}")

        if response.image_path:
            try:
                yield event.chain_result(build_image_chain(response.text, response.image_path))
                return
            except Exception as exc:
                logger.warning(f"RM 赛事图文消息构建失败：{exc}")

        yield event.plain_result(response.text)

    def should_forward(self, event: AstrMessageEvent, response: MatchQueryResponse) -> bool:
        matches = response.matches or []
        if not response.is_schedule_list or not matches:
            return False
        if not is_forward_capable_event(event):
            return False
        threshold = max(1, self.config._config_int("match_query_forward_threshold_matches", 8))
        return len(matches) > threshold or len(response.text) > 1200

    def build_forward_chain(self, response: MatchQueryResponse) -> list[Any]:
        matches = response.matches or []
        chunk_size = max(1, self.config._config_int("match_query_forward_chunk_size", 8))
        nodes = [
            Comp.Node(
                uin=10000,
                name="RM 赛事查询",
                content=summary_content(response),
            )
        ]
        for index, chunk in enumerate(chunks(matches, chunk_size), start=1):
            nodes.append(
                Comp.Node(
                    uin=10000,
                    name=f"赛程 {index}",
                    content=[Comp.Plain("\n".join(format_match_line(match) for match in chunk))],
                )
            )
        return nodes


def summary_content(response: MatchQueryResponse) -> list[Any]:
    lines = [
        response.title or "RoboMaster 赛事查询",
        f"共 {len(response.matches or [])} 场比赛。",
    ]
    content: list[Any] = [Comp.Plain("\n".join(lines))]
    if response.image_path:
        content.extend([Comp.Plain("\n赛程截图："), Comp.Image.fromFileSystem(str(response.image_path))])
    return content


def build_image_chain(text: str, image_path: Path) -> list[Any]:
    return [Comp.Plain(text + "\n"), Comp.Image.fromFileSystem(str(image_path))]


def chunks(items: list[MatchRecord], size: int) -> list[list[MatchRecord]]:
    return [items[index : index + size] for index in range(0, len(items), size)]


def is_forward_capable_event(event: AstrMessageEvent) -> bool:
    names: list[str] = []
    getter = getattr(event, "get_platform_name", None)
    if callable(getter):
        try:
            names.append(str(getter()))
        except Exception:
            pass
    message_obj = getattr(event, "message_obj", None)
    if message_obj is not None:
        names.append(str(getattr(message_obj, "platform_name", "") or ""))
        names.append(str(getattr(message_obj, "adapter", "") or ""))
    names.append(str(getattr(event, "unified_msg_origin", "") or ""))
    text = " ".join(names).lower()
    return any(token in text for token in ("onebot", "aiocqhttp"))
