from __future__ import annotations

import asyncio
import re
import shutil
import time
from pathlib import Path
from typing import Any, AsyncIterator

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent

from ..core.constants import DEFAULT_MANUAL_DIR, DISPLAY_NAME
from ..core.storage import (
    plugin_backup_dir,
    plugin_download_dir,
    plugin_index_path,
    plugin_manual_dir,
)
from .downloader import (
    ManualDownloadError,
    PromotionPlan,
    StagedManual,
    compare_manual_identity,
    download_manual_url,
    manual_identity,
    plan_manual_promotion,
)
from .llm_retriever import ManualLlmService
from .models import LocatedResult, ManualSearchResponse
from .search_engine import ManualSearchIndex, rebuild_index


class ManualService:
    def __init__(self, context: Any, config: Any):
        self.context = context
        self.config = config
        self.index_path = plugin_index_path()
        self.index = ManualSearchIndex.load(self.index_path)
        self.lock = asyncio.Lock()
        self.llm = ManualLlmService(context, config, lambda: self.index)

    async def search(self, query: str, event: AstrMessageEvent) -> ManualSearchResponse:
        if not self.index.pages:
            self.index = ManualSearchIndex.load(self.index_path)
        if not self.index.pages:
            await self.try_lazy_rebuild()

        max_results = self.config._config_int("max_results", 3)
        enable_llm = self.config._config_bool("enable_llm_explain", True)
        candidate_count = self.llm.candidate_count(max_results, enable_llm)
        retrieval_mode = self.llm.retrieval_mode()
        located_results: list[LocatedResult] = []
        explanation = ""

        if retrieval_mode == "full_llm":
            located_results, explanation = await self.llm.locate_with_full_manual_llm(event, query)
            return ManualSearchResponse(query, located_results, explanation)

        full_manual_attempted = False
        if retrieval_mode == "auto" and enable_llm and self.llm.full_manual_context_fits_budget(
            self.config._config_int("full_manual_max_chars", 500000)
        ):
            full_manual_attempted = True
            located_results, explanation = await self.llm.locate_with_full_manual_llm(event, query)

        if not located_results:
            candidates = await self.llm.search_candidates(
                event,
                query,
                candidate_count,
            )
        else:
            candidates = []

        if not located_results and not candidates:
            if retrieval_mode == "auto" and enable_llm and not full_manual_attempted:
                located_results, explanation = await self.llm.locate_with_full_manual_llm(
                    event,
                    query,
                )
            return ManualSearchResponse(query, located_results, explanation)

        if candidates:
            located_results = [LocatedResult(result) for result in candidates[:max_results]]
            if enable_llm:
                llm_result_limit = self.llm.result_limit(max_results, len(candidates))
                llm_located_results, llm_explanation = await self.llm.locate_with_llm(
                    event,
                    query,
                    candidates,
                    llm_result_limit,
                )
                if llm_located_results:
                    located_results = llm_located_results
                    explanation = llm_explanation
                elif retrieval_mode == "auto" and not full_manual_attempted:
                    full_results, full_explanation = await self.llm.locate_with_full_manual_llm(
                        event,
                        query,
                    )
                    if full_results:
                        located_results = full_results
                        explanation = full_explanation

        return ManualSearchResponse(query, located_results, explanation)

    async def rebuild(self) -> str:
        async with self.lock:
            manual_dir = self.manual_dir()
            index, stats = await asyncio.to_thread(rebuild_index, manual_dir)
            self.index = index
            await asyncio.to_thread(index.save, self.index_path, manual_dir, stats)

        for error in stats.errors[:10]:
            logger.warning(f"规则手册索引提示：{error}")

        if not index.pages:
            reason = stats.errors[0] if stats.errors else "没有可检索文本"
            return f"规则手册索引重建失败：{reason}"

        text = (
            "规则手册索引已重建\n"
            f"PDF 文件：{stats.pdf_count}\n"
            f"总页数：{stats.page_count}\n"
            f"可检索页：{stats.indexed_page_count}"
        )
        if stats.errors:
            text += f"\n提示：有 {len(stats.errors)} 个解析警告，详情见日志。"
        return text

    async def update_from_text(self, text: str) -> AsyncIterator[str]:
        urls = extract_urls(text)
        https_urls = [url for url in urls if url.lower().startswith("https://")]
        if not urls:
            yield (
                "请在命令后附上规则手册 PDF 的 HTTPS 下载链接。\n"
                "示例：更新规则手册 https://example.com/manual.pdf"
            )
            return
        if not https_urls:
            yield "规则手册更新失败：只支持 HTTPS 下载链接。"
            return

        url = https_urls[0]
        multi_url_notice = "\n提示：检测到多个链接，本次只处理第一个 HTTPS 链接。" if len(urls) > 1 else ""
        yield (
            "开始更新规则手册\n"
            f"链接：{url}\n"
            f"目标目录：{self.manual_dir()}"
            f"{multi_url_notice}"
        )

        staged: list[StagedManual] = []
        try:
            staged.append(
                await download_manual_url(
                    url,
                    plugin_download_dir(),
                    max_bytes=self.config._config_int("download_max_mb", 500) * 1024 * 1024,
                    timeout_seconds=max(10, self.config._config_int("download_timeout_seconds", 600)),
                    free_space_buffer_bytes=max(
                        0,
                        self.config._config_int("download_free_space_buffer_mb", 200),
                    )
                    * 1024
                    * 1024,
                )
            )

            summary = await self.promote_manuals_and_rebuild(staged)
        except ManualDownloadError as exc:
            for staged_manual in staged:
                staged_manual.path.unlink(missing_ok=True)
            yield f"规则手册更新失败：{exc}"
            return
        except Exception as exc:
            for staged_manual in staged:
                staged_manual.path.unlink(missing_ok=True)
            logger.warning(f"规则手册更新异常：{exc}")
            yield f"规则手册更新失败：{exc}"
            return

        yield summary

    async def promote_manuals_and_rebuild(self, staged: list[StagedManual]) -> str:
        if not staged:
            raise ManualDownloadError("没有下载到可更新的规则手册")

        async with self.lock:
            final_names = [item.final_name for item in staged]
            if len(set(final_names)) != len(final_names):
                raise ManualDownloadError("多个下载链接生成了相同文件名，请调整下载链接")

            staged, staged_skipped = filter_latest_staged_manuals(staged)
            manual_dir = Path(self.manual_dir()).expanduser()
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
                backup_obsolete_manuals(plans, backup_dir, backups)
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

    async def try_lazy_rebuild(self) -> None:
        async with self.lock:
            manual_dir = self.manual_dir()
            index, stats = await asyncio.to_thread(rebuild_index, manual_dir)
            self.index = index
            await asyncio.to_thread(index.save, self.index_path, manual_dir, stats)
        if stats.errors:
            logger.info(f"规则手册索引自动构建完成，提示数：{len(stats.errors)}")

    def help_text(self) -> str:
        return (
            f"{DISPLAY_NAME}\n"
            "规则手册检索用法：\n"
            "规则手册 关键词或问题\n"
            "示例：规则手册 自定义客户端\n"
            "示例：规则手册 裁判系统串口协议\n"
            "示例：规则手册 图传链路\n"
            f"PDF 目录：{self.manual_dir()}\n"
            f"临时下载目录：{plugin_download_dir()}\n"
            "回复模式可配置为 text、chain、forward 或 both。\n"
            "飞书会自动使用 chain；forward 仅建议在 OneBot v11/QQ 场景使用。\n"
            "有 LLM 时会先让 LLM 从候选原文页中选择截图依据；没有 LLM 时使用关键词检索。\n"
            "截图被裁切时，可关闭 crop_to_focus 发送整页截图。\n"
            "可在插件配置里设置 allowed_sessions 或 blocked_sessions 限制群聊。\n"
            "结果太长时，可调小 max_results 或 snippet_chars。\n"
            "管理员可发送：更新规则手册 <HTTPS PDF 链接>、重建规则手册索引"
        )

    def image_cache_dir(self) -> Path:
        return self.index_path.parent / "images"

    def manual_dir(self) -> str:
        configured = self.config._config_str("manual_dir", DEFAULT_MANUAL_DIR).strip()
        if configured and configured != DEFAULT_MANUAL_DIR:
            return configured
        return str(plugin_manual_dir())

    def clear(self) -> None:
        self.index = ManualSearchIndex([])


def extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    for match in re.finditer(r"https?://[^\s<>'\"，。；！？，]+", text):
        url = match.group(0).rstrip("，,。；;！!？?)]）>")
        if url:
            urls.append(url)
    return urls


def filter_latest_staged_manuals(
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


def backup_obsolete_manuals(
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
