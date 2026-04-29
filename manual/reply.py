from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, AsyncIterator, Callable

import astrbot.api.message_components as Comp
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.event_platform import is_lark_event
from .models import LocatedResult, ManualSearchResponse
from .pdf_screenshot import PdfScreenshotError, render_pdf_page


class ManualReplyBuilder:
    def __init__(
        self,
        config: Any,
        image_cache_dir: Callable[[], Path],
    ):
        self.config = config
        self._image_cache_dir = image_cache_dir

    async def build(
        self,
        event: AstrMessageEvent,
        response: ManualSearchResponse,
    ) -> AsyncIterator[Any]:
        query = response.query
        located_results = response.located_results
        explanation = response.explanation
        reply_mode = self.reply_mode_for_event(event)
        if reply_mode == "text":
            yield event.plain_result(format_results(query, located_results, explanation))
            return

        if reply_mode in {"image", "chain", "forward", "both"}:
            rendered = await self.render_result_images(located_results)
            if rendered:
                caption = format_image_caption(query, rendered, explanation)
                try:
                    if self.should_split_lark_text_images(event, reply_mode):
                        text = (
                            format_results(query, located_results, explanation)
                            if reply_mode == "both"
                            else caption
                        )
                        yield event.plain_result(text)
                        chain = build_image_only_chain(
                            [image_path for _, image_path in rendered]
                        )
                    elif reply_mode == "forward":
                        chain = build_forward_chain(caption, rendered)
                    elif reply_mode == "both":
                        chain = build_image_chain(
                            format_results(query, located_results, explanation),
                            [image_path for _, image_path in rendered],
                        )
                    else:
                        chain = build_image_chain(
                            caption,
                            [image_path for _, image_path in rendered],
                        )
                    yield event.chain_result(chain)
                except Exception as exc:
                    logger.warning(f"规则手册图文消息构建失败：{exc}")
                    yield event.plain_result(
                        format_results(query, located_results, explanation)
                    )
                return

        yield event.plain_result(format_results(query, located_results, explanation))

    def reply_mode_for_event(self, event: AstrMessageEvent) -> str:
        reply_mode = self.config._config_str("reply_mode", "chain").lower()
        if reply_mode == "forward" and is_lark_event(event):
            logger.info("飞书平台不支持合并转发消息，已自动改用 chain 图文消息。")
            return "chain"
        return reply_mode

    def should_split_lark_text_images(
        self,
        event: AstrMessageEvent,
        reply_mode: str,
    ) -> bool:
        if reply_mode == "text" or not is_lark_event(event):
            return False
        return self.config._config_bool("lark_split_text_and_images", True)

    async def render_result_images(
        self,
        located_results: list[LocatedResult],
    ) -> list[tuple[LocatedResult, Path]]:
        rendered: list[tuple[LocatedResult, Path]] = []
        for located in located_results:
            image_path = await self.render_result_image(located)
            if image_path:
                rendered.append((located, image_path))
        return rendered

    async def render_result_image(self, located: LocatedResult) -> Path | None:
        try:
            return await asyncio.to_thread(
                render_pdf_page,
                located.result.file_path,
                located.result.page_number,
                self._image_cache_dir(),
                zoom=self.config._config_float("image_zoom", 1.8),
                max_age_seconds=self.config._config_int("image_cache_seconds", 86400),
                focus_text=located.focus_text,
                crop_to_focus=self.config._config_bool("crop_to_focus", True),
                crop_full_width=self.config._config_bool("crop_full_width", True),
            )
        except PdfScreenshotError as exc:
            logger.warning(f"规则手册截图生成失败：{exc}")
        except Exception as exc:
            logger.warning(f"规则手册截图生成异常：{exc}")
        return None


def format_results(
    query: str,
    results: list[LocatedResult],
    explanation: str,
) -> str:
    lines = [f"规则手册：{query}"]
    if explanation:
        lines.extend(["", f"结论：{explanation}"])

    lines.extend(["", f"依据：{len(results)} 条"])
    for idx, located in enumerate(results, start=1):
        item = located.result
        lines.extend(
            [
                "",
                f"{idx}. {short_file_name(item.file_name)}",
                f"第 {item.page_number} 页",
                item.snippet,
            ]
        )
    return "\n".join(lines)


def format_image_caption(
    query: str,
    rendered: list[tuple[LocatedResult, Path]],
    explanation: str,
) -> str:
    lines = [f"规则手册：{query}"]
    if explanation:
        lines.extend(["", f"结论：{explanation}"])
    lines.extend(
        [
            "",
            f"截图依据：{len(rendered)} 条",
        ]
    )
    for idx, (located, _) in enumerate(rendered, start=1):
        result = located.result
        lines.append(
            f"{idx}. {short_file_name(result.file_name)} 第 {result.page_number} 页"
        )
    return "\n".join(lines)


def build_image_chain(caption: str, image_paths: list[Path]) -> list[Any]:
    chain: list[Any] = [Comp.Plain(caption + "\n")]
    for image_path in image_paths:
        chain.append(Comp.Image.fromFileSystem(str(image_path)))
    return chain


def build_image_only_chain(image_paths: list[Path]) -> list[Any]:
    return [Comp.Image.fromFileSystem(str(image_path)) for image_path in image_paths]


def build_forward_chain(caption: str, rendered: list[tuple[LocatedResult, Path]]) -> list[Any]:
    nodes = [
        Comp.Node(
            uin=10000,
            name="规则手册检索",
            content=[Comp.Plain(caption)],
        )
    ]
    for idx, (located, image_path) in enumerate(rendered, start=1):
        result = located.result
        nodes.append(
            Comp.Node(
                uin=10000,
                name=f"依据 {idx}",
                content=[
                    Comp.Plain(
                        f"{short_file_name(result.file_name)} 第 {result.page_number} 页"
                    ),
                    Comp.Image.fromFileSystem(str(image_path)),
                ],
            )
        )
    return nodes


def short_file_name(file_name: str) -> str:
    name = Path(file_name).stem
    replacements = (
        "RoboMaster 2026 ",
        "RoboMaster 2025 ",
        "机甲大师",
        "（20260417）",
        "（20260327）",
        "(20260417)",
        "(20260327)",
    )
    for old in replacements:
        name = name.replace(old, "")
    name = " ".join(name.split())
    return name[:36] + "..." if len(name) > 36 else name
