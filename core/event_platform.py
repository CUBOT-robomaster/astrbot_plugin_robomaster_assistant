from __future__ import annotations

from typing import Any


def is_lark_event(event: Any) -> bool:
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
