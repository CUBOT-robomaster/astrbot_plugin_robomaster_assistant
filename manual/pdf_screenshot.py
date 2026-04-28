from __future__ import annotations

import hashlib
import time
from pathlib import Path


class PdfScreenshotError(RuntimeError):
    pass


def render_pdf_page(
    pdf_path: str,
    page_number: int,
    output_dir: Path,
    *,
    zoom: float = 1.8,
    max_age_seconds: int = 86400,
    focus_text: str = "",
    crop_to_focus: bool = True,
    crop_full_width: bool = True,
) -> Path:
    try:
        import fitz
    except Exception as exc:  # pragma: no cover - dependency may be unavailable
        raise PdfScreenshotError(f"缺少 PyMuPDF 依赖或导入失败：{exc}") from exc

    source = Path(pdf_path)
    if not source.exists():
        raise PdfScreenshotError(f"PDF 不存在：{source}")
    if page_number < 1:
        raise PdfScreenshotError(f"页码无效：{page_number}")

    output_dir.mkdir(parents=True, exist_ok=True)
    cleanup_old_images(output_dir, max_age_seconds=max_age_seconds)

    cache_key = _cache_key(
        source,
        page_number,
        zoom,
        focus_text if crop_to_focus else "",
        crop_full_width,
    )
    output_path = output_dir / f"{cache_key}.png"
    if output_path.exists():
        return output_path

    doc = fitz.open(str(source))
    try:
        if page_number > doc.page_count:
            raise PdfScreenshotError(f"页码超出范围：{page_number}/{doc.page_count}")
        page = doc.load_page(page_number - 1)
        matrix = fitz.Matrix(zoom, zoom)
        clip = (
            _focus_clip(page, focus_text, crop_full_width=crop_full_width)
            if crop_to_focus and focus_text
            else None
        )
        pixmap = page.get_pixmap(matrix=matrix, alpha=False, clip=clip)
        pixmap.save(str(output_path))
    finally:
        doc.close()

    return output_path


def cleanup_old_images(output_dir: Path, *, max_age_seconds: int = 86400) -> None:
    if max_age_seconds <= 0 or not output_dir.exists():
        return

    now = time.time()
    for image_path in output_dir.glob("*.png"):
        try:
            if now - image_path.stat().st_mtime > max_age_seconds:
                image_path.unlink()
        except OSError:
            continue


def _focus_clip(page, focus_text: str, *, crop_full_width: bool = True):
    rect = _find_focus_rect(page, focus_text)
    if rect is None:
        return None

    page_rect = page.rect
    y_margin = page_rect.height * 0.12

    if crop_full_width:
        clip = page_rect
        clip.y0 = max(page_rect.y0, rect.y0 - y_margin)
        clip.y1 = min(page_rect.y1, rect.y1 + y_margin)
    else:
        x_margin = page_rect.width * 0.12
        clip = rect + (-x_margin, -y_margin, x_margin, y_margin)
        clip &= page_rect

    min_height = page_rect.height * 0.38
    if clip.height < min_height:
        extra = (min_height - clip.height) / 2
        clip = clip + (0, -extra, 0, extra)
        clip &= page_rect

    return clip


def _find_focus_rect(page, focus_text: str):
    candidates = _focus_candidates(focus_text)
    for candidate in candidates:
        rects = page.search_for(candidate)
        if rects:
            rect = rects[0]
            for extra_rect in rects[1:4]:
                rect |= extra_rect
            return rect
    return None


def _focus_candidates(focus_text: str) -> list[str]:
    text = " ".join((focus_text or "").split())
    if not text:
        return []

    candidates = [text]
    for delimiter in ("。", "；", ";", "，", ",", "\n"):
        candidates.extend(part.strip() for part in text.split(delimiter) if len(part.strip()) >= 6)

    words = [word.strip() for word in text.replace("，", " ").replace("。", " ").split()]
    candidates.extend(word for word in words if len(word) >= 6)

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in sorted(candidates, key=len, reverse=True):
        if candidate not in seen:
            seen.add(candidate)
            unique.append(candidate[:80])
    return unique


def _cache_key(
    pdf_path: Path,
    page_number: int,
    zoom: float,
    focus_text: str = "",
    crop_full_width: bool = True,
) -> str:
    stat = pdf_path.stat()
    raw = (
        f"{pdf_path.resolve()}:{stat.st_mtime_ns}:{page_number}:"
        f"{zoom:.2f}:{focus_text[:120]}:{crop_full_width}"
    )
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()
