from __future__ import annotations


def mask_identifier(value: object, keep: int = 4) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= keep:
        return "*" * len(text)
    return f"...{text[-keep:]}"


def mask_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    if "://" not in text:
        return mask_identifier(text)
    scheme, rest = text.split("://", 1)
    host = rest.split("/", 1)[0]
    return f"{scheme}://{host}/..."
