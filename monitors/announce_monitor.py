from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from html import unescape

try:
    from bs4 import BeautifulSoup
except Exception:  # pragma: no cover - dependency may be installed by AstrBot
    BeautifulSoup = None


ANNOUNCEMENT_URL = "https://www.robomaster.com/zh-CN/resource/pages/announcement/{id}"


@dataclass
class AnnouncementPage:
    announcement_id: int
    url: str
    title: str
    main_html: str
    is_empty: bool = False


@dataclass
class AnnouncementEvent:
    event_type: str
    announcement_id: int
    title: str
    url: str
    text: str


def announcement_url(announcement_id: int) -> str:
    return ANNOUNCEMENT_URL.format(id=announcement_id)


def parse_announcement_html(announcement_id: int, html: str) -> AnnouncementPage | None:
    if "您访问的页面不存在" in html:
        return None
    if BeautifulSoup is None:
        return _parse_announcement_html_fallback(announcement_id, html)

    soup = BeautifulSoup(html, "html.parser")
    title_node = soup.find("p", class_="main-title")
    context_node = soup.find("div", class_="main-context")
    if title_node is None:
        return None

    title = title_node.get_text(strip=True)
    main_html = str(context_node) if context_node is not None else ""
    return AnnouncementPage(
        announcement_id=announcement_id,
        url=announcement_url(announcement_id),
        title=title or f"公告 {announcement_id}",
        main_html=main_html,
        is_empty=context_node is None or not context_node.get_text(strip=True),
    )


def _parse_announcement_html_fallback(announcement_id: int, html: str) -> AnnouncementPage | None:
    title_html = _find_tag_by_class(html, "p", "main-title")
    if title_html is None:
        return None
    context_html = _find_tag_by_class(html, "div", "main-context") or ""
    title = _strip_html(title_html)
    return AnnouncementPage(
        announcement_id=announcement_id,
        url=announcement_url(announcement_id),
        title=title or f"公告 {announcement_id}",
        main_html=context_html,
        is_empty=not _strip_html(context_html),
    )


def _find_tag_by_class(html: str, tag: str, class_name: str) -> str | None:
    pattern = re.compile(
        rf"<{tag}\b[^>]*class=[\"'][^\"']*\b{re.escape(class_name)}\b[^\"']*[\"'][^>]*>.*?</{tag}>",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(html)
    return match.group(0) if match else None


def _strip_html(value: str) -> str:
    text = re.sub(r"<script\b.*?</script>", "", value, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<style\b.*?</style>", "", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def main_context_hash(main_html: str) -> str:
    return hashlib.sha256(main_html.encode("utf-8")).hexdigest().upper()


def format_announcement_event(event_type: str, page: AnnouncementPage) -> AnnouncementEvent:
    prefix = "[新增]" if event_type == "announcement_new" else "[更新]"
    if event_type == "announcement_new" and page.is_empty:
        prefix = "[空白]"
    text = f"RoboMaster 资料站公告\n{prefix} {page.title}\n{page.url}"
    return AnnouncementEvent(event_type, page.announcement_id, page.title, page.url, text)
