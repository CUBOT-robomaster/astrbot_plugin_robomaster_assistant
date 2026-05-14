from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...manual.pdf_screenshot import cleanup_old_images
from .html import render_html


RENDERER_VERSION = "match-info-image-v1"
VIEWPORT = {"width": 1280, "height": 900}
RENDER_TIMEOUT_MS = 20_000


class MatchInfoImageRenderer:
    def __init__(self, config: Any):
        self.config = config

    async def render(self, payload: dict[str, Any] | None) -> Path | None:
        if not payload:
            return None
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.info(f"RM 赛事信息图片不可用，未安装 Playwright：{exc}")
            return None

        from ...core.storage import plugin_match_image_dir

        output_dir = plugin_match_image_dir()
        output_dir.mkdir(parents=True, exist_ok=True)
        cleanup_old_images(
            output_dir,
            max_age_seconds=self.config._config_int("image_cache_seconds", 86400),
        )

        digest = payload_digest(payload)
        output = output_dir / f"match-info-{digest}.png"
        if output.exists():
            return output
        temp_path = output_dir / f".match-info-{digest}-{time.time_ns()}.png"

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(viewport=VIEWPORT, device_scale_factor=1)
                    await page.set_content(render_html(payload), wait_until="networkidle", timeout=RENDER_TIMEOUT_MS)
                    await page.locator(".rm-card").screenshot(path=str(temp_path))
                finally:
                    await browser.close()
            temp_path.replace(output)
            return output
        except Exception as exc:
            logger.warning(f"RM 赛事信息图片渲染失败：{exc}")
            temp_path.unlink(missing_ok=True)
            return None


def payload_digest(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha1(f"{RENDERER_VERSION}:{VIEWPORT}:{raw}".encode("utf-8")).hexdigest()[:16]
