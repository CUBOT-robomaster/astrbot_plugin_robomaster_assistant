from __future__ import annotations

import asyncio
import json
import re
import shutil
import time
from dataclasses import dataclass
from ipaddress import ip_address
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

from .core.constants import (
    DEFAULT_MANUAL_DIR,
    DISPLAY_NAME,
    NO_RESULT_TEXT,
    PLUGIN_NAME,
    PLUGIN_VERSION,
)
from .core.plugin_config import ConfigSessionMixin
from .core.privacy import mask_identifier, mask_url
from .core.storage import (
    plugin_backup_dir,
    plugin_download_dir,
    plugin_index_path,
    plugin_manual_dir,
    plugin_state_path,
)
from .manual.downloader import (
    ManualDownloadError,
    PromotionPlan,
    StagedManual,
    compare_manual_identity,
    download_manual_url,
    manual_identity,
    plan_manual_promotion,
)
from .manual.pdf_screenshot import PdfScreenshotError, render_pdf_page
from .manual.search_engine import ManualSearchIndex, SearchResult, rebuild_index
from .monitors.announce_monitor import (
    announcement_url,
    format_announcement_event,
    main_context_hash,
    parse_announcement_html,
)
from .monitors.match_monitor import (
    DJI_CURRENT_API_URL,
    DJI_SCHEDULE_API_URL,
    MatchEvent,
    detect_match_events,
)
from .monitors.monitor_state import MonitorState
from .notifications.lark_enhance_card import send_lark_card
from .notifications.notification import CircuitBreaker, plain_chain


@dataclass
class LocatedResult:
    result: SearchResult
    focus_text: str = ""


@register(
    PLUGIN_NAME,
    "RoboMaster赛事助手 contributors",
    "RoboMaster赛事助手：规则手册检索、RM 公告监控、赛事监控",
    PLUGIN_VERSION,
)
class Main(ConfigSessionMixin, Star):
    def __init__(self, context: Context, config: AstrBotConfig | None = None):
        super().__init__(context)
        self.config = config or {}
        self.index_path = self._get_index_path()
        self.index = self._load_index()
        self.monitor_state = self._load_monitor_state()
        self.circuit_breaker = CircuitBreaker()
        self._breaker_notice_recover_at = 0.0
        self._lark_clients: dict[str, Any] = {}
        self.monitor_tasks: list[asyncio.Task] = []
        self._manual_lock = asyncio.Lock()
        self._announce_lock = asyncio.Lock()
        self._match_lock = asyncio.Lock()
        self._start_monitor_tasks()

    def _start_monitor_tasks(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("无法获取事件循环，监控任务未启动。")
            return
        if self._config_bool("announce_enabled", False):
            self.monitor_tasks.append(loop.create_task(self._announce_loop()))
        if self._config_bool("match_monitor_enabled", False):
            self.monitor_tasks.append(loop.create_task(self._match_loop()))

    @filter.command("规则手册帮助")
    async def manual_help_command(self, event: AstrMessageEvent):
        """查看 RoboMaster 规则手册检索插件帮助。"""
        if not self._is_session_allowed(event):
            return
        self._stop_event(event)
        yield event.plain_result(self._help_text())

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("重建规则手册索引")
    async def rebuild_command(self, event: AstrMessageEvent):
        """管理员重新扫描 PDF 目录并更新规则手册索引。"""
        if not self._is_session_allowed(event):
            return
        async for result in self._rebuild_and_reply(event):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def rebuild_plain_text(self, event: AstrMessageEvent):
        """兼容不带命令前缀的管理员重建消息。"""
        if self._message_text(event) != "重建规则手册索引":
            return
        if not self._is_session_allowed(event):
            return
        if not self._is_admin(event):
            self._stop_event(event)
            yield event.plain_result(
                "此命令仅管理员可用。请通过 /sid 获取 ID 后让管理员添加权限。"
            )
            return
        async for result in self._rebuild_and_reply(event):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def update_manual_plain_text(self, event: AstrMessageEvent):
        """管理员发送 HTTPS 链接下载并更新规则手册。"""
        message = self._message_text(event)
        if message != "更新规则手册" and not message.startswith("更新规则手册 "):
            return
        if not self._is_session_allowed(event):
            return
        if not self._is_admin(event):
            self._stop_event(event)
            yield event.plain_result(
                "此命令仅管理员可用。请通过 /sid 获取 ID 后让管理员添加权限。"
            )
            return

        text = message.removeprefix("更新规则手册").strip()
        async for result in self._update_manuals_and_reply(event, text):
            yield result

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def search_manual(self, event: AstrMessageEvent):
        """监听“规则手册 xxx”并检索本地 PDF 规则手册。"""
        message = self._message_text(event)
        if message == "规则手册帮助":
            if not self._is_session_allowed(event):
                return
            self._stop_event(event)
            yield event.plain_result(self._help_text())
            return

        if not message.startswith("规则手册 "):
            return
        if not self._is_session_allowed(event):
            return

        query = message.removeprefix("规则手册 ").strip()
        self._stop_event(event)
        if not query:
            yield event.plain_result(self._help_text())
            return

        if not self.index.pages:
            self.index = ManualSearchIndex.load(self.index_path)
        if not self.index.pages:
            await self._try_lazy_rebuild()

        max_results = self._config_int("max_results", 3)
        enable_llm = self._config_bool("enable_llm_explain", True)
        candidate_count = self._candidate_count(max_results, enable_llm)
        candidates = self.index.search(
            query,
            max_results=candidate_count,
            snippet_chars=self._config_int("llm_candidate_chars", 260),
            min_score=self._config_float("min_score", 0.6),
        )
        if not candidates:
            yield event.plain_result(NO_RESULT_TEXT)
            return

        located_results = [LocatedResult(result) for result in candidates[:max_results]]
        explanation = ""
        if enable_llm:
            llm_result_limit = self._llm_result_limit(max_results, len(candidates))
            llm_located_results, llm_explanation = await self._locate_with_llm(
                event,
                query,
                candidates,
                llm_result_limit,
            )
            if llm_located_results:
                located_results = llm_located_results
            explanation = llm_explanation

        reply_mode = self._reply_mode_for_event(event)
        if reply_mode == "text":
            yield event.plain_result(self._format_results(query, located_results, explanation))
            return

        if reply_mode in {"image", "chain", "forward", "both"}:
            rendered = await self._render_result_images(located_results)
            if rendered:
                caption = self._format_image_caption(query, rendered, explanation)
                try:
                    if self._should_split_lark_text_images(event, reply_mode):
                        text = (
                            self._format_results(query, located_results, explanation)
                            if reply_mode == "both"
                            else caption
                        )
                        yield event.plain_result(text)
                        chain = self._build_image_only_chain(
                            [image_path for _, image_path in rendered]
                        )
                    elif reply_mode == "forward":
                        chain = self._build_forward_chain(caption, rendered)
                    elif reply_mode == "both":
                        chain = self._build_image_chain(
                            self._format_results(query, located_results, explanation),
                            [image_path for _, image_path in rendered],
                        )
                    else:
                        chain = self._build_image_chain(
                            caption,
                            [image_path for _, image_path in rendered],
                        )
                    yield event.chain_result(chain)
                except Exception as exc:
                    logger.warning(f"规则手册图文消息构建失败：{exc}")
                    yield event.plain_result(
                        self._format_results(query, located_results, explanation)
                    )
                return

        yield event.plain_result(self._format_results(query, located_results, explanation))

    async def _rebuild_and_reply(self, event: AstrMessageEvent):
        self._stop_event(event)
        async with self._manual_lock:
            manual_dir = self._manual_dir()
            index, stats = await asyncio.to_thread(rebuild_index, manual_dir)
            self.index = index
            await asyncio.to_thread(index.save, self.index_path, manual_dir, stats)

        for error in stats.errors[:10]:
            logger.warning(f"规则手册索引提示：{error}")

        if not index.pages:
            reason = stats.errors[0] if stats.errors else "没有可检索文本"
            yield event.plain_result(f"规则手册索引重建失败：{reason}")
            return

        text = (
            "规则手册索引已重建\n"
            f"PDF 文件：{stats.pdf_count}\n"
            f"总页数：{stats.page_count}\n"
            f"可检索页：{stats.indexed_page_count}"
        )
        if stats.errors:
            text += f"\n提示：有 {len(stats.errors)} 个解析警告，详情见日志。"
        yield event.plain_result(text)

    async def _update_manuals_and_reply(self, event: AstrMessageEvent, text: str):
        self._stop_event(event)
        urls = self._extract_urls(text)
        https_urls = [url for url in urls if url.lower().startswith("https://")]
        if not urls:
            yield event.plain_result(
                "请在命令后附上规则手册 PDF 的 HTTPS 下载链接。\n"
                "示例：更新规则手册 https://example.com/manual.pdf"
            )
            return
        if not https_urls:
            yield event.plain_result("规则手册更新失败：只支持 HTTPS 下载链接。")
            return

        url = https_urls[0]
        multi_url_notice = "\n提示：检测到多个链接，本次只处理第一个 HTTPS 链接。" if len(urls) > 1 else ""
        yield event.plain_result(
            "开始更新规则手册\n"
            f"链接：{url}\n"
            f"目标目录：{self._manual_dir()}"
            f"{multi_url_notice}"
        )

        staged: list[StagedManual] = []
        try:
            staged.append(
                await download_manual_url(
                    url,
                    plugin_download_dir(),
                    max_bytes=self._config_int("download_max_mb", 500) * 1024 * 1024,
                    timeout_seconds=max(10, self._config_int("download_timeout_seconds", 600)),
                    free_space_buffer_bytes=max(
                        0,
                        self._config_int("download_free_space_buffer_mb", 200),
                    )
                    * 1024
                    * 1024,
                )
            )

            summary = await self._promote_manuals_and_rebuild(staged)
        except ManualDownloadError as exc:
            for staged_manual in staged:
                staged_manual.path.unlink(missing_ok=True)
            yield event.plain_result(f"规则手册更新失败：{exc}")
            return
        except Exception as exc:
            for staged_manual in staged:
                staged_manual.path.unlink(missing_ok=True)
            logger.warning(f"规则手册更新异常：{exc}")
            yield event.plain_result(f"规则手册更新失败：{exc}")
            return

        yield event.plain_result(summary)

    @staticmethod
    def _extract_urls(text: str) -> list[str]:
        urls: list[str] = []
        for match in re.finditer(r"https?://[^\s<>'\"，。；！？，]+", text):
            url = match.group(0).rstrip("，,。；;！!？?)]）>")
            if url:
                urls.append(url)
        return urls

    async def _promote_manuals_and_rebuild(self, staged: list[StagedManual]) -> str:
        if not staged:
            raise ManualDownloadError("没有下载到可更新的规则手册")

        async with self._manual_lock:
            final_names = [item.final_name for item in staged]
            if len(set(final_names)) != len(final_names):
                raise ManualDownloadError("多个下载链接生成了相同文件名，请调整下载链接")

            staged, staged_skipped = self._filter_latest_staged_manuals(staged)
            manual_dir = Path(self._manual_dir()).expanduser()
            manual_dir.mkdir(parents=True, exist_ok=True)
            plans = [plan_manual_promotion(item, manual_dir) for item in staged]
            skipped = staged_skipped + [
                f"{plan.staged.source.name}：{plan.skip_reason}"
                for plan in plans
                if plan.skip_reason
            ]
            plans = [plan for plan in plans if plan.should_promote]

            for item in staged:
                if not any(plan.staged is item for plan in plans):
                    item.path.unlink(missing_ok=True)

            if not plans:
                lines = ["规则手册无需更新"]
                if skipped:
                    lines.extend(skipped)
                return "\n".join(lines)

            backup_dir = plugin_backup_dir() / str(int(time.time() * 1000))
            backup_dir.mkdir(parents=True, exist_ok=True)
            backups: list[tuple[Path, Path]] = []
            promoted_paths: list[Path] = []
            old_index = self.index
            try:
                self._backup_obsolete_manuals(plans, backup_dir, backups)
                for plan in plans:
                    plan.staged.path.replace(plan.target_path)
                    promoted_paths.append(plan.target_path)

                index, stats = await asyncio.to_thread(rebuild_index, str(manual_dir))
                if not index.pages:
                    reason = stats.errors[0] if stats.errors else "没有可检索文本"
                    raise ManualDownloadError(f"新规则手册索引重建失败：{reason}")
                await asyncio.to_thread(index.save, self.index_path, str(manual_dir), stats)
                self.index = index
            except Exception:
                for path in promoted_paths:
                    path.unlink(missing_ok=True)
                for backup_path, original_path in reversed(backups):
                    original_path.parent.mkdir(parents=True, exist_ok=True)
                    backup_path.replace(original_path)
                self.index = old_index
                raise
            finally:
                for plan in plans:
                    plan.staged.path.unlink(missing_ok=True)
                if backup_dir.exists():
                    shutil.rmtree(backup_dir, ignore_errors=True)

            lines = [
                "规则手册更新完成",
                f"更新文件：{len(promoted_paths)}",
                f"PDF 文件：{stats.pdf_count}",
                f"总页数：{stats.page_count}",
                f"可检索页：{stats.indexed_page_count}",
            ]
            if backups:
                lines.append(f"清理旧版本：{len(backups)}")
            if skipped:
                lines.extend(["跳过：", *skipped])
            if stats.errors:
                lines.append(f"提示：有 {len(stats.errors)} 个解析警告，详情见日志。")
            return "\n".join(lines)

    @staticmethod
    def _filter_latest_staged_manuals(
        staged: list[StagedManual],
    ) -> tuple[list[StagedManual], list[str]]:
        latest_by_category: dict[str, StagedManual] = {}
        skipped: dict[StagedManual, str] = {}
        for item in staged:
            identity = manual_identity(item.final_name)
            if not identity.comparable:
                continue
            previous = latest_by_category.get(identity.category)
            if previous is None:
                latest_by_category[identity.category] = item
                continue
            comparison = compare_manual_identity(identity, manual_identity(previous.final_name))
            if comparison is None:
                continue
            if comparison <= 0:
                skipped[item] = f"{item.source.name}：同批次已有更新版本"
            else:
                skipped[previous] = f"{previous.source.name}：同批次已有更新版本"
                latest_by_category[identity.category] = item

        kept = [item for item in staged if item not in skipped]
        for item in skipped:
            item.path.unlink(missing_ok=True)
        return kept, list(skipped.values())

    @staticmethod
    def _backup_obsolete_manuals(
        plans: list[PromotionPlan],
        backup_dir: Path,
        backups: list[tuple[Path, Path]],
    ) -> None:
        seen: set[Path] = set()
        for plan in plans:
            for old_path in plan.obsolete_paths:
                if old_path in seen or not old_path.exists():
                    continue
                seen.add(old_path)
                backup_path = backup_dir / old_path.name
                counter = 1
                while backup_path.exists():
                    backup_path = backup_dir / f"{old_path.stem}.{counter}{old_path.suffix}"
                    counter += 1
                old_path.replace(backup_path)
                backups.append((backup_path, old_path))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM订阅通知")
    async def subscribe_rm_notifications(self, event: AstrMessageEvent):
        """订阅 RM 公告和赛事监控通知。"""
        self._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        if not session:
            yield event.plain_result("订阅失败：无法获取当前会话 ID。")
            return
        added = self.monitor_state.add_session(session)
        lark_card_hint = self._remember_lark_runtime(event, session)
        suffix = "\n已记录飞书卡片运行时信息。" if lark_card_hint else ""
        yield event.plain_result(
            ("已订阅 RM 通知。" if added else "当前会话已订阅 RM 通知。") + suffix
        )

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM取消订阅")
    async def unsubscribe_rm_notifications(self, event: AstrMessageEvent):
        """取消订阅 RM 公告和赛事监控通知。"""
        self._stop_event(event)
        session = getattr(event, "unified_msg_origin", "")
        removed = self.monitor_state.remove_session(session)
        self._lark_clients.pop(session, None)
        yield event.plain_result("已取消订阅 RM 通知。" if removed else "当前会话未订阅 RM 通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM监控状态")
    async def rm_monitor_status(self, event: AstrMessageEvent):
        """查看 RM 公告和赛事监控状态。"""
        self._stop_event(event)
        data = self.monitor_state.data
        text = (
            "RM 监控状态\n"
            f"公告监控：{'开启' if self._config_bool('announce_enabled', False) else '关闭'}\n"
            f"赛事监控：{'开启' if self._config_bool('match_monitor_enabled', False) else '关闭'}\n"
            f"订阅会话：{len(self.monitor_state.sessions)}\n"
            f"飞书卡片通知：{'开启' if self._config_bool('enable_lark_card_notifications', False) else '关闭'}\n"
            f"飞书卡片可用会话：{len(self._lark_clients)}\n"
            f"公告 last_id：{data.get('announce_last_id') or self._config_int('announce_last_id', 0)}\n"
            f"监控公告页：{len(data.get('announce_page_hashes', {}))}\n"
            f"赛事缓存赛区：{len(data.get('match_previous', {}))}\n"
            f"后台任务：{sum(1 for task in self.monitor_tasks if not task.done())}"
        )
        yield event.plain_result(text)

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM公告检查")
    async def rm_announce_check(self, event: AstrMessageEvent):
        """立即执行一次 RM 官网公告检查。"""
        self._stop_event(event)
        events = await self._run_announce_check()
        yield event.plain_result(f"RM 公告检查完成，发现 {len(events)} 条通知。")

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("RM赛事检查")
    async def rm_match_check(self, event: AstrMessageEvent):
        """立即执行一次 RoboMaster 赛事状态检查。"""
        self._stop_event(event)
        events = await self._run_match_check()
        yield event.plain_result(f"RM 赛事检查完成，发现 {len(events)} 条通知。")

    async def _try_lazy_rebuild(self) -> None:
        async with self._manual_lock:
            manual_dir = self._manual_dir()
            index, stats = await asyncio.to_thread(rebuild_index, manual_dir)
            self.index = index
            await asyncio.to_thread(index.save, self.index_path, manual_dir, stats)
        if stats.errors:
            logger.info(f"规则手册索引自动构建完成，提示数：{len(stats.errors)}")

    async def _announce_loop(self) -> None:
        interval = max(5, self._config_int("announce_interval_seconds", 60))
        while True:
            try:
                await self._run_announce_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 公告监控失败：{exc}")
            await asyncio.sleep(interval)

    async def _match_loop(self) -> None:
        interval = max(5, self._config_int("match_scan_interval_seconds", 30))
        while True:
            try:
                await self._run_match_check()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning(f"RM 赛事监控失败：{exc}")
            await asyncio.sleep(interval)

    async def _run_announce_check(self) -> list[Any]:
        async with self._announce_lock:
            return await self._run_announce_check_unlocked()

    async def _run_announce_check_unlocked(self) -> list[Any]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 公告监控缺少 httpx：{exc}")
            return []

        events: list[Any] = []
        async with httpx.AsyncClient(timeout=15) as client:
            last_id = int(self.monitor_state.data.get("announce_last_id") or 0)
            if last_id == 0:
                last_id = self._config_int("announce_last_id", 0)
                self.monitor_state.data["announce_last_id"] = last_id
                self.monitor_state.save()

            if last_id > 0:
                next_id = last_id + 1
                page = await self._fetch_announcement_page(client, next_id)
                if page:
                    self.monitor_state.data["announce_last_id"] = next_id
                    self.monitor_state.save()
                    if self.monitor_state.remember_recent_announcement(next_id):
                        event = format_announcement_event("announcement_new", page)
                        events.append(event)
                        await self._notify(event.text, {"id": next_id, "title": page.title, "url": page.url}, event.event_type)

            page_hashes = dict(self.monitor_state.data.get("announce_page_hashes", {}))
            for page_id in self._config_int_list("announce_monitored_pages"):
                page = await self._fetch_announcement_page(client, page_id)
                if page is None:
                    continue
                digest = main_context_hash(page.main_html)
                previous_hash = page_hashes.get(str(page_id))
                page_hashes[str(page_id)] = digest
                if previous_hash and previous_hash != digest:
                    event = format_announcement_event("announcement_update", page)
                    events.append(event)
                    await self._notify(event.text, {"id": page_id, "title": page.title, "url": page.url}, event.event_type)
            self.monitor_state.data["announce_page_hashes"] = page_hashes
            self.monitor_state.save()
        return events

    async def _fetch_announcement_page(self, client: Any, announcement_id: int):
        resp = await client.get(announcement_url(announcement_id))
        if resp.status_code == 404:
            return None
        if resp.status_code >= 400:
            logger.warning(f"RM 公告页面请求失败 {announcement_id}: {resp.status_code}")
            return None
        return parse_announcement_html(announcement_id, resp.text)

    async def _run_match_check(self) -> list[MatchEvent]:
        async with self._match_lock:
            return await self._run_match_check_unlocked()

    async def _run_match_check_unlocked(self) -> list[MatchEvent]:
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 赛事监控缺少 httpx：{exc}")
            return []

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(self._config_str("dji_current_api_url", DJI_CURRENT_API_URL))
            resp.raise_for_status()
            items = resp.json()
            if not isinstance(items, list):
                items = []

        previous = self.monitor_state.data.get("match_previous", {})
        zone_allowlist = self._config_id_set("match_zone_allowlist")
        events, next_previous = detect_match_events(items, previous, zone_allowlist or None)
        self.monitor_state.data["match_previous"] = next_previous
        self.monitor_state.save()

        for event in events:
            await self._handle_match_event(event)
        return events

    async def _handle_match_event(self, event: MatchEvent) -> None:
        data = event.match
        if event.event_type == "match_end":
            scheduled = await self._fetch_scheduled_match(data)
            if scheduled:
                data = {**data, **scheduled}
                event.match = data
                event.text = event.text + "\n最终比分已尝试从赛程接口补充。"

        await self._notify(event.text, event.match, event.event_type)

    async def _fetch_scheduled_match(self, match: dict[str, Any]) -> dict[str, Any] | None:
        # 轻量实现：先保留接口请求能力，复杂 JsonPath 匹配失败时不影响主流程。
        try:
            import httpx

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(self._config_str("dji_schedule_api_url", DJI_SCHEDULE_API_URL))
                if resp.status_code >= 400:
                    return None
                schedule = resp.json()
        except Exception as exc:
            logger.warning(f"RM 赛程接口请求失败：{exc}")
            return None
        match_id = str(match.get("id") or "")
        return self._find_match_by_id(schedule, match_id) if match_id else None

    def _find_match_by_id(self, node: Any, match_id: str) -> dict[str, Any] | None:
        if isinstance(node, dict):
            if str(node.get("id") or "") == match_id:
                return node
            for value in node.values():
                found = self._find_match_by_id(value, match_id)
                if found:
                    return found
        elif isinstance(node, list):
            for item in node:
                found = self._find_match_by_id(item, match_id)
                if found:
                    return found
        return None

    async def _notify(self, text: str, payload: dict[str, Any], event_type: str) -> None:
        allowed, reason = self.circuit_breaker.allow()
        if not allowed:
            logger.warning(f"RM 通知熔断：{reason}")
            await self._notify_breaker_once(reason)
            return

        sessions = list(dict.fromkeys(self.monitor_state.sessions + self._config_url_list("notify_sessions")))
        for session in sessions:
            if await self._try_send_lark_card_notification(session, text, event_type):
                continue
            try:
                await self.context.send_message(session, plain_chain(text))
            except Exception as exc:
                logger.warning(f"RM 主动推送失败 {mask_identifier(session)}: {exc}")

        if self._config_bool("external_webhook_enabled", False):
            await self._send_external_webhooks({"type": event_type, "data": payload})

    async def _try_send_lark_card_notification(
        self,
        session: str,
        text: str,
        event_type: str,
    ) -> bool:
        if not self._config_bool("enable_lark_card_notifications", False):
            return False
        lark_client = self._lark_clients.get(session)
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

    def _remember_lark_runtime(self, event: AstrMessageEvent, session: str) -> bool:
        if not self._is_lark_event(event):
            return False
        lark_client = getattr(event, "bot", None)
        chat_id = self._lark_chat_id_from_event(event)
        if lark_client is None or not chat_id:
            return False
        self._lark_clients[session] = lark_client
        self.monitor_state.set_lark_session(session, chat_id)
        return True

    @staticmethod
    def _lark_chat_id_from_event(event: AstrMessageEvent) -> str:
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

    async def _notify_breaker_once(self, reason: str) -> None:
        recover_at = getattr(self.circuit_breaker, "recover_at", 0.0)
        if recover_at <= 0 or recover_at == self._breaker_notice_recover_at:
            return
        self._breaker_notice_recover_at = recover_at
        sessions = list(dict.fromkeys(self.monitor_state.sessions + self._config_url_list("notify_sessions")))
        text = f"RM 通知触发熔断，后续通知将暂时静默。\n{reason}"
        for session in sessions:
            try:
                await self.context.send_message(session, plain_chain(text))
            except Exception as exc:
                logger.warning(f"RM 熔断提示发送失败 {mask_identifier(session)}: {exc}")

    async def _send_external_webhooks(self, body: dict[str, Any]) -> None:
        urls = self._config_url_list("external_webhook_urls")
        if not urls:
            return
        try:
            import httpx
        except Exception as exc:
            logger.warning(f"RM 外部 Webhook 缺少 httpx：{exc}")
            return

        async with httpx.AsyncClient(timeout=10) as client:
            for url in urls:
                if not self._is_allowed_webhook_url(url):
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

    @staticmethod
    def _is_allowed_webhook_url(url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return False

        hostname = parsed.hostname.strip().lower()
        if hostname in {"localhost", "0.0.0.0"} or hostname.endswith(".localhost"):
            return False

        try:
            address = ip_address(hostname)
        except ValueError:
            return True
        return not (
            address.is_private
            or address.is_loopback
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
        )

    async def _explain_with_llm(
        self,
        event: AstrMessageEvent,
        query: str,
        results: list[SearchResult],
    ) -> str:
        try:
            provider_id = await self._get_current_provider_id(event)
            if not provider_id:
                return ""

            evidence = "\n".join(
                f"{idx}. {item.file_name} 第 {item.page_number} 页：{item.snippet}"
                for idx, item in enumerate(results, start=1)
            )
            prompt = (
                "你是 RoboMaster 规则手册检索助手。请只根据下面给出的原文片段，"
                "用不超过 80 个中文字符回答用户问题。不得补充片段外规则；"
                "如果片段不足以回答，请回答“原文片段不足以支持进一步解释”。\n\n"
                f"用户问题：{query}\n\n"
                f"原文片段：\n{evidence}"
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            return (getattr(llm_resp, "completion_text", "") or "").strip()
        except Exception as exc:
            logger.warning(f"规则手册 LLM 解释失败：{exc}")
            return ""

    async def _locate_with_llm(
        self,
        event: AstrMessageEvent,
        query: str,
        candidates: list[SearchResult],
        max_results: int,
    ) -> tuple[list[LocatedResult], str]:
        try:
            provider_id = await self._get_current_provider_id(event)
            if not provider_id:
                return [], ""

            evidence = "\n".join(
                f"[{idx}] 文件：{item.file_name}；页码：{item.page_number}；原文：{item.snippet}"
                for idx, item in enumerate(candidates, start=1)
            )
            prompt = (
                "你是 RoboMaster 规则手册定位助手。请只根据候选原文页判断用户问题最相关的依据。"
                "不要编造候选之外的规则。请返回严格 JSON，不要 Markdown，不要额外解释。"
                f"请选择所有必须作为依据的候选页，最多 {max_results} 条。"
                "不要为了凑数量选择弱相关内容；优先选择正文规则页，避免目录、版权页、修改日志页，"
                "除非用户明确询问目录/版本/修订。"
                "每条依据的 quote 必须直接来自候选原文，用于截图定位，尽量选择包含答案的短句或表格行。"
                "JSON 格式："
                "{\"summary\":\"不超过80字的简短结论；依据不足则说明不足\","
                "\"items\":[{\"id\":候选编号,\"quote\":\"候选原文中的定位短句\"}]}"
                "\n\n"
                f"用户问题：{query}\n\n候选原文页：\n{evidence}"
            )
            llm_resp = await self.context.llm_generate(
                chat_provider_id=provider_id,
                prompt=prompt,
            )
            text = (getattr(llm_resp, "completion_text", "") or "").strip()
            data = self._parse_llm_json(text)
            if not data:
                return [], ""

            located: list[LocatedResult] = []
            seen_ids: set[int] = set()
            for item in data.get("items", []):
                try:
                    item_id = int(item.get("id", 0))
                except (TypeError, ValueError):
                    continue
                if item_id < 1 or item_id > len(candidates) or item_id in seen_ids:
                    continue
                seen_ids.add(item_id)
                quote = str(item.get("quote", "") or "").strip()
                located.append(LocatedResult(candidates[item_id - 1], quote))
                if len(located) >= max_results:
                    break

            summary = str(data.get("summary", "") or "").strip()
            return located, summary
        except Exception as exc:
            logger.warning(f"规则手册 LLM 定位失败：{exc}")
            return [], ""

    @staticmethod
    def _parse_llm_json(text: str) -> dict[str, Any] | None:
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    def _candidate_count(self, max_results: int, enable_llm: bool) -> int:
        if enable_llm:
            return max(1, self._config_int("llm_candidate_pages", 10))
        return max(1, max_results)

    def _llm_result_limit(self, max_results: int, candidate_count: int) -> int:
        if not self._config_bool("llm_select_all_evidence", True):
            return max(1, max_results)

        llm_max_results = self._config_int("llm_max_results", 0)
        if llm_max_results > 0:
            return max(1, min(llm_max_results, candidate_count))
        return max(1, candidate_count)

    def _reply_mode_for_event(self, event: AstrMessageEvent) -> str:
        reply_mode = self._config_str("reply_mode", "chain").lower()
        if reply_mode == "forward" and self._is_lark_event(event):
            logger.info("飞书平台不支持合并转发消息，已自动改用 chain 图文消息。")
            return "chain"
        return reply_mode

    def _should_split_lark_text_images(
        self,
        event: AstrMessageEvent,
        reply_mode: str,
    ) -> bool:
        if reply_mode == "text" or not self._is_lark_event(event):
            return False
        return self._config_bool("lark_split_text_and_images", True)

    @staticmethod
    def _is_lark_event(event: AstrMessageEvent) -> bool:
        platform_names: list[str] = []
        getter = getattr(event, "get_platform_name", None)
        if callable(getter):
            try:
                platform_names.append(str(getter()))
            except Exception:
                pass

        platform_meta = getattr(event, "platform_meta", None)
        if platform_meta is not None:
            platform_names.append(str(getattr(platform_meta, "name", "") or ""))

        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            platform_names.append(str(getattr(message_obj, "platform_name", "") or ""))
            platform_names.append(str(getattr(message_obj, "adapter", "") or ""))

        platform_names.append(str(getattr(event, "unified_msg_origin", "") or ""))
        platform_text = " ".join(platform_names).lower()
        return "lark" in platform_text or "feishu" in platform_text

    async def _render_result_images(
        self,
        located_results: list[LocatedResult],
    ) -> list[tuple[LocatedResult, Path]]:
        rendered: list[tuple[LocatedResult, Path]] = []
        for located in located_results:
            image_path = await self._render_result_image(located)
            if image_path:
                rendered.append((located, image_path))
        return rendered

    async def _render_result_image(self, located: LocatedResult) -> Path | None:
        try:
            return await asyncio.to_thread(
                render_pdf_page,
                located.result.file_path,
                located.result.page_number,
                self._image_cache_dir(),
                zoom=self._config_float("image_zoom", 1.8),
                max_age_seconds=self._config_int("image_cache_seconds", 86400),
                focus_text=located.focus_text,
                crop_to_focus=self._config_bool("crop_to_focus", True),
                crop_full_width=self._config_bool("crop_full_width", True),
            )
        except PdfScreenshotError as exc:
            logger.warning(f"规则手册截图生成失败：{exc}")
        except Exception as exc:
            logger.warning(f"规则手册截图生成异常：{exc}")
        return None

    async def _get_current_provider_id(self, event: AstrMessageEvent) -> str | None:
        getter = getattr(self.context, "get_current_chat_provider_id", None)
        if getter is None:
            return None
        try:
            return await getter(umo=event.unified_msg_origin)
        except TypeError:
            return await getter(event.unified_msg_origin)

    def _format_results(
        self,
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
                    f"{idx}. {self._short_file_name(item.file_name)}",
                    f"第 {item.page_number} 页",
                    item.snippet,
                ]
            )
        return "\n".join(lines)

    def _format_image_caption(
        self,
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
                f"{idx}. {self._short_file_name(result.file_name)} 第 {result.page_number} 页"
            )
        return "\n".join(lines)

    @staticmethod
    def _build_image_chain(caption: str, image_paths: list[Path]) -> list[Any]:
        if Comp is None:
            raise RuntimeError("AstrBot message_components 不可用")
        chain: list[Any] = [Comp.Plain(caption + "\n")]
        for image_path in image_paths:
            chain.append(Comp.Image.fromFileSystem(str(image_path)))
        return chain

    @staticmethod
    def _build_image_only_chain(image_paths: list[Path]) -> list[Any]:
        if Comp is None:
            raise RuntimeError("AstrBot message_components 不可用")
        return [Comp.Image.fromFileSystem(str(image_path)) for image_path in image_paths]

    @staticmethod
    def _build_forward_chain(caption: str, rendered: list[tuple[LocatedResult, Path]]) -> list[Any]:
        if Comp is None:
            raise RuntimeError("AstrBot message_components 不可用")
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
                            f"{Main._short_file_name(result.file_name)} 第 {result.page_number} 页"
                        ),
                        Comp.Image.fromFileSystem(str(image_path)),
                    ],
                )
            )
        return nodes

    def _help_text(self) -> str:
        return (
            f"{DISPLAY_NAME}\n"
            "规则手册检索用法：\n"
            "规则手册 关键词或问题\n"
            "示例：规则手册 自定义客户端\n"
            "示例：规则手册 裁判系统串口协议\n"
            "示例：规则手册 图传链路\n"
            f"PDF 目录：{self._manual_dir()}\n"
            f"临时下载目录：{plugin_download_dir()}\n"
            "回复模式可配置为 text、chain、forward 或 both。\n"
            "飞书会自动使用 chain；forward 仅建议在 OneBot v11/QQ 场景使用。\n"
            "有 LLM 时会先让 LLM 从候选原文页中选择截图依据；没有 LLM 时使用关键词检索。\n"
            "截图被裁切时，可关闭 crop_to_focus 发送整页截图。\n"
            "可在插件配置里设置 allowed_sessions 或 blocked_sessions 限制群聊。\n"
            "结果太长时，可调小 max_results 或 snippet_chars。\n"
            "管理员可发送：更新规则手册 <HTTPS PDF 链接>、重建规则手册索引"
        )

    @staticmethod
    def _short_file_name(file_name: str) -> str:
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

    def _get_index_path(self) -> Path:
        return plugin_index_path()

    def _load_index(self) -> ManualSearchIndex:
        return ManualSearchIndex.load(self.index_path)

    def _load_monitor_state(self) -> MonitorState:
        state_path = plugin_state_path()
        return MonitorState(state_path)

    def _image_cache_dir(self) -> Path:
        return self.index_path.parent / "images"

    def _manual_dir(self) -> str:
        configured = self._config_str("manual_dir", DEFAULT_MANUAL_DIR).strip()
        if configured and configured != DEFAULT_MANUAL_DIR:
            return configured
        return str(plugin_manual_dir())

    async def terminate(self):
        """插件卸载时释放内存索引。"""
        for task in self.monitor_tasks:
            task.cancel()
        if self.monitor_tasks:
            await asyncio.gather(*self.monitor_tasks, return_exceptions=True)
        self.index = ManualSearchIndex([])
        self.monitor_state.save()
