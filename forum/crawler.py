from __future__ import annotations

import asyncio
import json
import os
import random
import re
from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from .models import ForumArticleInput


DEFAULT_FORUM_URL = "https://bbs.robomaster.com/article"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)


@dataclass
class ForumCrawlerSettings:
    article_url: str = DEFAULT_FORUM_URL
    username: str = ""
    password: str = ""
    cookies_path: str = ""
    chromium_executable_path: str = ""
    headless: bool = True
    user_agent: str = DEFAULT_USER_AGENT
    list_limit: int = 10


class ForumListParser(HTMLParser):
    def __init__(self, base_url: str, limit: int):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.limit = max(1, limit)
        self.articles: list[ForumArticleInput] = []
        self.current: dict[str, Any] | None = None
        self.depth = 0
        self.class_stack: list[set[str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {key: value or "" for key, value in attrs}
        classes = set(attrs_dict.get("class", "").split())

        if tag == "a" and "articleItem" in classes and self.current is None:
            self.current = {
                "href": attrs_dict.get("href", ""),
                "title": [],
                "author": [],
                "category": [],
                "posted_at": [],
                "pinned": False,
            }
            self.depth = 1
            self.class_stack.append(classes)
            return

        if self.current is not None:
            self.depth += 1
            if tag == "svg" and any("articleItem__titles" in item for item in self.class_stack):
                self.current["pinned"] = True
        self.class_stack.append(classes)

    def handle_endtag(self, tag: str) -> None:
        if self.class_stack:
            self.class_stack.pop()
        if self.current is None:
            return
        self.depth -= 1
        if self.depth <= 0:
            self._finish_current()

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        text = " ".join((data or "").split())
        if not text:
            return
        active = set().union(*self.class_stack) if self.class_stack else set()
        if "articleItem__title" in active:
            self.current["title"].append(text)
        elif "articleItem__info-author" in active:
            self.current["author"].append(text)
        elif "articleItem__category" in active:
            self.current["category"].append(text)
        elif "articleItem__info-time" in active:
            self.current["posted_at"].append(text)

    def _finish_current(self) -> None:
        item = self.current or {}
        self.current = None
        self.depth = 0
        if item.get("pinned") or len(self.articles) >= self.limit:
            return
        href = str(item.get("href") or "").strip()
        title = normalize_text(" ".join(item.get("title") or []))
        if not href or not title:
            return
        self.articles.append(
            ForumArticleInput(
                title=title,
                url=urljoin(self.base_url, unescape(href)),
                author=normalize_text(" ".join(item.get("author") or [])),
                category=normalize_text(" ".join(item.get("category") or [])),
                posted_at=normalize_text(" ".join(item.get("posted_at") or [])),
            )
        )


def parse_article_list_html(html: str, base_url: str = DEFAULT_FORUM_URL, limit: int = 10) -> list[ForumArticleInput]:
    parser = ForumListParser(base_url, limit)
    parser.feed(html or "")
    parser.close()
    return parser.articles


def extract_detail_text_and_links(html: str) -> tuple[str, list[str]]:
    html = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", " ", html or "", flags=re.I | re.S)
    links = extract_links(html)
    text = re.sub(r"<[^>]+>", " ", html)
    text = normalize_text(unescape(text))
    return text, links


def extract_links(text: str) -> list[str]:
    links = re.findall(r"https?://[^\s\"'<>）)]+", text or "")
    seen: set[str] = set()
    cleaned: list[str] = []
    for link in links:
        link = link.rstrip(".,;，。；")
        if link and link not in seen:
            seen.add(link)
            cleaned.append(link)
    return cleaned


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


class ForumCrawler:
    def __init__(self):
        self._playwright: Any | None = None
        self._browser: Any | None = None
        self._browser_key: tuple[Any, ...] | None = None
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        async with self._lock:
            await self._close_unlocked()

    async def fetch_articles(self, settings: ForumCrawlerSettings) -> list[ForumArticleInput]:
        async with self._lock:
            context = await self._new_context(settings)
        try:
            await self._ensure_login(context, settings)
            page = await context.new_page()
            try:
                await page.goto(settings.article_url, wait_until="domcontentloaded", timeout=60000)
                await random_sleep(1000, 2000)
                await page.wait_for_selector("a.articleItem", timeout=30000)
                await smooth_scroll(page)
                await page.evaluate("window.scrollTo({top: 0, behavior: 'smooth'})")
                await random_sleep(500, 1000)
                html = await page.content()
                articles = parse_article_list_html(html, settings.article_url, settings.list_limit)
            finally:
                await page.close()

            for article in articles:
                article.raw_text, article.repo_links, article.detail_error = await self._fetch_detail(context, article.url)
                await random_sleep(700, 1800)
            return articles
        finally:
            await context.close()

    async def _new_context(self, settings: ForumCrawlerSettings):
        browser = await self._browser_for(settings)
        storage_state = self._storage_state_path(settings)
        kwargs: dict[str, Any] = {
            "user_agent": settings.user_agent or DEFAULT_USER_AGENT,
            "viewport": {"width": 1920, "height": 1080},
            "locale": "zh-CN",
        }
        if storage_state and storage_state.exists():
            kwargs["storage_state"] = str(storage_state)
        try:
            context = await browser.new_context(**kwargs)
        except Exception:
            kwargs.pop("storage_state", None)
            context = await browser.new_context(**kwargs)
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
        )
        if "storage_state" not in kwargs:
            await self._try_add_chromedp_cookies(context, storage_state)
        return context

    async def _browser_for(self, settings: ForumCrawlerSettings):
        key = (
            settings.headless,
            self._chromium_executable_path(settings),
            settings.user_agent,
        )
        if self._browser is not None and self._browser_key == key:
            try:
                if self._browser.is_connected():
                    return self._browser
            except Exception:
                pass
        await self._close_unlocked()
        try:
            from playwright.async_api import async_playwright
        except Exception as exc:  # pragma: no cover - depends on deployment env
            raise RuntimeError(
                "论坛监控需要安装 Playwright：pip install playwright && python -m playwright install chromium"
            ) from exc
        self._playwright = await async_playwright().start()
        launch_kwargs: dict[str, Any] = {
            "headless": settings.headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }
        executable_path = self._chromium_executable_path(settings)
        if executable_path:
            launch_kwargs["executable_path"] = executable_path
        self._browser = await self._playwright.chromium.launch(**launch_kwargs)
        self._browser_key = key
        return self._browser

    async def _close_unlocked(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._browser = None
        self._playwright = None
        self._browser_key = None

    async def _ensure_login(self, context: Any, settings: ForumCrawlerSettings) -> None:
        page = await context.new_page()
        try:
            await page.goto(settings.article_url, wait_until="domcontentloaded", timeout=60000)
            await random_sleep(800, 1600)
            try:
                await page.wait_for_selector("a.articleItem", timeout=8000)
            except Exception:
                pass
            if await page.locator("a.articleItem").count():
                await self._save_storage_state(context, settings)
                return
            if not settings.username or not settings.password:
                return
            await self._login_with_password(page, settings)
            await self._save_storage_state(context, settings)
        finally:
            await page.close()

    async def _login_with_password(self, page: Any, settings: ForumCrawlerSettings) -> None:
        await page.wait_for_selector(".loginItem", timeout=30000)
        await random_sleep(300, 600)
        await page.click(".loginItem")
        await random_sleep(2000, 3000)
        await page.click('a[data-usagetag="password_login_tab"]')
        await random_sleep(500, 1000)
        await page.click('input[name="username"]')
        await page.type('input[name="username"]', settings.username, delay=random.randint(50, 150))
        await random_sleep(200, 500)
        await page.click('input[type="password"]')
        await page.type('input[type="password"]', settings.password, delay=random.randint(50, 150))
        await random_sleep(300, 800)
        await page.click('button[data-usagetag="login_button"]')
        await page.wait_for_selector("a.articleItem", timeout=60000)

    async def _fetch_detail(self, context: Any, url: str) -> tuple[str, list[str], str]:
        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            await random_sleep(1000, 2000)
            await smooth_scroll(page)
            html = await page.content()
            text, links = extract_detail_text_and_links(html)
            if not text:
                return "", links, "详情页没有提取到正文"
            return text, links, ""
        except Exception as exc:
            logger.warning(f"论坛详情抓取失败：{url} {exc}")
            return "", [], str(exc)
        finally:
            await page.close()

    async def _save_storage_state(self, context: Any, settings: ForumCrawlerSettings) -> None:
        storage_state = self._storage_state_path(settings)
        if not storage_state:
            return
        storage_state.parent.mkdir(parents=True, exist_ok=True)
        try:
            await context.storage_state(path=str(storage_state))
        except Exception as exc:
            logger.warning(f"论坛 cookies 保存失败：{exc}")

    async def _try_add_chromedp_cookies(self, context: Any, path: Path | None) -> None:
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, list):
                return
            cookies: list[dict[str, Any]] = []
            for item in data:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                cookie = {
                    "name": item.get("name"),
                    "value": item.get("value", ""),
                    "domain": item.get("domain", ".robomaster.com"),
                    "path": item.get("path", "/"),
                }
                if item.get("expires"):
                    cookie["expires"] = item.get("expires")
                cookies.append(cookie)
            if cookies:
                await context.add_cookies(cookies)
        except Exception as exc:
            logger.warning(f"论坛 cookies 加载失败：{exc}")

    @staticmethod
    def _storage_state_path(settings: ForumCrawlerSettings) -> Path | None:
        return Path(settings.cookies_path).expanduser() if settings.cookies_path else None

    @staticmethod
    def _chromium_executable_path(settings: ForumCrawlerSettings) -> str:
        return (
            settings.chromium_executable_path.strip()
            or os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", "").strip()
        )


async def random_sleep(min_ms: int, max_ms: int) -> None:
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000.0)


async def smooth_scroll(page: Any) -> None:
    for _ in range(random.randint(2, 4)):
        amount = random.randint(200, 500)
        await page.evaluate(f"window.scrollBy({{top: {amount}, behavior: 'smooth'}})")
        await random_sleep(300, 800)
