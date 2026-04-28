from __future__ import annotations

import asyncio
import ipaddress
import re
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse


PDF_HEADER = b"%PDF-"
CHUNK_SIZE = 1024 * 1024
MAX_REDIRECTS = 5
MAX_FILENAME_BYTES = 180
BLOCKED_HOSTS = {"localhost", "localhost.localdomain"}


class ManualDownloadError(RuntimeError):
    pass


@dataclass(frozen=True)
class ManualSource:
    name: str
    url: str


@dataclass(frozen=True)
class ManualIdentity:
    category: str
    version: tuple[int, ...] | None
    date: str | None

    @property
    def comparable(self) -> bool:
        return self.version is not None or self.date is not None


@dataclass(frozen=True)
class StagedManual:
    source: ManualSource
    path: Path
    final_name: str
    size_bytes: int


@dataclass(frozen=True)
class PromotionPlan:
    staged: StagedManual
    target_path: Path
    obsolete_paths: list[Path]
    skip_reason: str = ""

    @property
    def should_promote(self) -> bool:
        return not self.skip_reason


def validate_source_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme.lower() != "https":
        raise ManualDownloadError(f"只允许 HTTPS 手册链接：{url}")
    if not parsed.netloc:
        raise ManualDownloadError(f"手册链接缺少域名：{url}")
    _check_safe_host(parsed.hostname or "", url)


async def download_manual_url(
    url: str,
    download_dir: Path,
    *,
    max_bytes: int,
    timeout_seconds: int,
    free_space_buffer_bytes: int,
) -> StagedManual:
    validate_source_url(url)
    source = ManualSource(name=source_name_from_url(url), url=url)
    return await download_manual_source(
        source,
        download_dir,
        max_bytes=max_bytes,
        timeout_seconds=timeout_seconds,
        free_space_buffer_bytes=free_space_buffer_bytes,
    )


async def download_manual_source(
    source: ManualSource,
    download_dir: Path,
    *,
    max_bytes: int,
    timeout_seconds: int,
    free_space_buffer_bytes: int,
) -> StagedManual:
    try:
        import httpx
    except Exception as exc:
        raise ManualDownloadError(f"缺少 httpx，无法下载规则手册：{exc}") from exc

    await _validate_download_url(source.url)
    download_dir.mkdir(parents=True, exist_ok=True)
    final_name = final_filename_for_source(source)
    part_path = download_dir / f"{_safe_stem(source.name)}-{time.time_ns()}.part"

    try:
        timeout = httpx.Timeout(timeout_seconds)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            current_url = source.url
            for _ in range(MAX_REDIRECTS + 1):
                await _validate_download_url(current_url)
                async with client.stream("GET", current_url) as response:
                    if 300 <= response.status_code < 400:
                        current_url = _next_redirect_url(current_url, response.headers, source.name)
                        continue
                    if response.status_code >= 400:
                        raise ManualDownloadError(
                            f"{source.name} 下载失败：HTTP {response.status_code}"
                        )
                    expected_size = _content_length(response.headers)
                    _check_size_limit(expected_size, max_bytes, source.name)
                    _check_free_space(download_dir, expected_size, free_space_buffer_bytes)

                    size = 0
                    header = b""
                    with part_path.open("wb") as file:
                        async for chunk in response.aiter_bytes(CHUNK_SIZE):
                            if not chunk:
                                continue
                            if len(header) < len(PDF_HEADER):
                                missing = len(PDF_HEADER) - len(header)
                                header += chunk[:missing]
                                if len(header) == len(PDF_HEADER) and header != PDF_HEADER:
                                    raise ManualDownloadError(
                                        f"{source.name} 不是有效 PDF 文件"
                                    )
                            size += len(chunk)
                            if size > max_bytes:
                                raise ManualDownloadError(
                                    f"{source.name} 超过大小限制：{_format_bytes(max_bytes)}"
                                )
                            file.write(chunk)

                    if size == 0:
                        raise ManualDownloadError(f"{source.name} 下载结果为空")
                    if header != PDF_HEADER:
                        raise ManualDownloadError(f"{source.name} 不是有效 PDF 文件")
                    break
            else:
                raise ManualDownloadError(f"{source.name} 重定向次数过多")
    except Exception:
        part_path.unlink(missing_ok=True)
        raise

    staged_path = part_path.with_suffix(".download")
    part_path.replace(staged_path)
    return StagedManual(
        source=source,
        path=staged_path,
        final_name=final_name,
        size_bytes=size,
    )


def final_filename_for_source(source: ManualSource) -> str:
    parsed = urlparse(source.url)
    basename = unquote(Path(parsed.path).name)
    if basename.lower().endswith(".pdf"):
        return sanitize_pdf_filename(basename)
    return sanitize_pdf_filename(f"{source.name}.pdf")


def source_name_from_url(url: str) -> str:
    parsed = urlparse(url)
    basename = unquote(Path(parsed.path).name)
    if basename:
        return Path(sanitize_pdf_filename(basename)).stem
    return "规则手册"


def _next_redirect_url(current_url: str, headers, source_name: str) -> str:
    location = str(headers.get("location") or "").strip()
    if not location:
        raise ManualDownloadError(f"{source_name} 下载重定向缺少 Location")
    next_url = urljoin(current_url, location)
    validate_source_url(next_url)
    return next_url


def sanitize_pdf_filename(name: str) -> str:
    cleaned = re.sub(r"[\x00-\x1f<>:\"/\\|?*]+", "_", name).strip(" ._")
    if not cleaned:
        cleaned = "manual.pdf"
    if not cleaned.lower().endswith(".pdf"):
        cleaned += ".pdf"
    return _limit_filename_bytes(cleaned)


def manual_identity(file_name: str) -> ManualIdentity:
    stem = Path(file_name).stem
    date_match = re.search(r"(20\d{6})", stem)
    version_match = re.search(r"(?i)v\s*(\d+(?:\.\d+)*)", stem)
    version = _parse_version(version_match.group(1)) if version_match else None

    category = stem
    if version_match:
        category = category[: version_match.start()] + category[version_match.end() :]
    category = re.sub(r"[（(【\[]?\s*20\d{6}\s*[）)】\]]?", " ", category)
    category = re.sub(r"[_\-—–]+", " ", category)
    category = " ".join(category.split())
    return ManualIdentity(category=category or stem, version=version, date=date_match.group(1) if date_match else None)


def compare_manual_identity(new: ManualIdentity, old: ManualIdentity) -> int | None:
    if new.category != old.category:
        return None
    if new.version is not None and old.version is not None:
        if new.version != old.version:
            return 1 if new.version > old.version else -1
        return _compare_dates(new.date, old.date)
    if new.version is not None and old.version is None:
        return 1
    if new.version is None and old.version is not None:
        return -1
    if new.date is not None and old.date is not None:
        return _compare_dates(new.date, old.date)
    return None


def plan_manual_promotion(staged: StagedManual, manual_dir: Path) -> PromotionPlan:
    target_path = manual_dir / staged.final_name
    new_identity = manual_identity(staged.final_name)
    obsolete_paths: list[Path] = []
    for pdf_path in sorted(manual_dir.glob("*.pdf")):
        if pdf_path == target_path:
            obsolete_paths.append(pdf_path)
            continue
        old_identity = manual_identity(pdf_path.name)
        comparison = compare_manual_identity(new_identity, old_identity)
        if comparison is None:
            continue
        if comparison < 0:
            return PromotionPlan(
                staged=staged,
                target_path=target_path,
                obsolete_paths=[],
                skip_reason=f"已有更新版本：{pdf_path.name}",
            )
        obsolete_paths.append(pdf_path)
    return PromotionPlan(staged=staged, target_path=target_path, obsolete_paths=obsolete_paths)


def _content_length(headers) -> int | None:
    try:
        value = headers.get("content-length")
    except AttributeError:
        value = None
    if not value:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _check_size_limit(expected_size: int | None, max_bytes: int, name: str) -> None:
    if expected_size is not None and expected_size > max_bytes:
        raise ManualDownloadError(
            f"{name} 超过大小限制：{_format_bytes(expected_size)} > {_format_bytes(max_bytes)}"
        )


def _check_free_space(path: Path, expected_size: int | None, buffer_bytes: int) -> None:
    usage = shutil.disk_usage(path)
    required = (expected_size or 0) + buffer_bytes
    if usage.free < required:
        raise ManualDownloadError(
            f"磁盘剩余空间不足：可用 {_format_bytes(usage.free)}，需要至少 {_format_bytes(required)}"
        )


def _parse_version(text: str) -> tuple[int, ...]:
    parts = [int(part) for part in text.split(".")]
    while len(parts) > 1 and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _compare_dates(new_date: str | None, old_date: str | None) -> int:
    if new_date == old_date:
        return 0
    if new_date is None:
        return 0
    if old_date is None:
        return 1
    return 1 if new_date > old_date else -1


def _safe_stem(text: str) -> str:
    safe = re.sub(r"[\x00-\x1f<>:\"/\\|?*\s]+", "_", text).strip("._")
    return safe[:60] or "manual"


def _format_bytes(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / 1024 / 1024:.1f} MB"
    if size >= 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size} B"


async def _validate_download_url(url: str) -> None:
    validate_source_url(url)
    host = urlparse(url).hostname or ""
    await asyncio.to_thread(_check_resolved_host, host)


def _check_safe_host(host: str, url: str) -> None:
    host = host.strip("[]").lower().rstrip(".")
    if not host:
        raise ManualDownloadError(f"手册链接缺少域名：{url}")
    if host in BLOCKED_HOSTS or host.endswith(".localhost"):
        raise ManualDownloadError(f"手册链接指向不安全主机：{url}")
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return
    if _is_blocked_address(address):
        raise ManualDownloadError(f"手册链接指向内网或保留地址：{url}")


def _check_resolved_host(host: str) -> None:
    host = host.strip("[]").lower().rstrip(".")
    try:
        address_infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ManualDownloadError(f"手册链接域名解析失败：{host}") from exc
    for *_, sockaddr in address_infos:
        try:
            address = ipaddress.ip_address(sockaddr[0])
        except (IndexError, ValueError):
            continue
        if _is_blocked_address(address):
            raise ManualDownloadError(f"手册链接域名解析到内网或保留地址：{host}")


def _is_blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def _limit_filename_bytes(name: str) -> str:
    suffix = ".pdf"
    stem = name[:-len(suffix)] if name.lower().endswith(suffix) else name
    while len(f"{stem}{suffix}".encode("utf-8")) > MAX_FILENAME_BYTES and stem:
        stem = stem[:-1].rstrip(" ._")
    return f"{stem or 'manual'}{suffix}"
