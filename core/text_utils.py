from __future__ import annotations

import re

try:
    import jieba
except Exception:  # pragma: no cover
    jieba = None


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def tokenize(text: str) -> list[str]:
    text = normalize_text(text).lower()
    if not text:
        return []

    if jieba is not None:
        tokens = [token.strip() for token in jieba.cut(text) if token.strip()]
    else:
        tokens = re.findall(r"[a-z0-9_]+", text)
        chinese = "".join(re.findall(r"[一-鿿]", text))
        tokens.extend(chinese[i : i + 2] for i in range(max(0, len(chinese) - 1)))

    return [token for token in tokens if len(token) > 1 or re.match(r"[a-z0-9]", token)]
