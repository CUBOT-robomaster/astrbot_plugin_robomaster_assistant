from __future__ import annotations

import hashlib
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger

from ...manual.pdf_screenshot import cleanup_old_images


VIEWPORT = {"width": 1440, "height": 1600}
SCREENSHOT_TIMEOUT_MS = 20_000


class MatchScheduleScreenshotService:
    def __init__(self, config: Any):
        self.config = config

    async def render(self, date: str) -> Path | None:
        if not self.config._config_bool("match_query_enable_schedule_screenshot", False):
            return None

        try:
            from playwright.async_api import async_playwright
        except Exception as exc:
            logger.info(f"RM 赛程网页截图不可用，未安装 Playwright：{exc}")
            return None

        url = self.config._config_str("schedule_api_base_url", "https://schedule.scutbot.cn").rstrip("/")
        from ...core.storage import plugin_match_image_dir

        cache_dir = plugin_match_image_dir()
        cache_dir.mkdir(parents=True, exist_ok=True)
        cleanup_old_images(
            cache_dir,
            max_age_seconds=self.config._config_int("image_cache_seconds", 86400),
        )
        digest = hashlib.sha1(f"{url}:{date}:{VIEWPORT}".encode("utf-8")).hexdigest()[:12]
        output = cache_dir / f"schedule-{date}-{digest}.png"
        if output.exists():
            return output
        temp_path = cache_dir / f".schedule-{date}-{digest}-{time.time_ns()}.png"

        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(headless=True)
                try:
                    page = await browser.new_page(viewport=VIEWPORT)
                    await page.goto(url, wait_until="networkidle", timeout=SCREENSHOT_TIMEOUT_MS)
                    await page.screenshot(path=str(temp_path), full_page=True)
                finally:
                    await browser.close()
            temp_path.replace(output)
            return output
        except Exception as exc:
            logger.warning(f"RM 赛程网页截图失败：{exc}")
            temp_path.unlink(missing_ok=True)
            return None
