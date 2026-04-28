from __future__ import annotations

import re
from typing import Any

from astrbot.api import logger

from .constants import CONFIG_GROUPS
from .privacy import mask_identifier


class ConfigSessionMixin:
    @staticmethod
    def _message_text(event) -> str:
        return getattr(event, "message_str", "").strip()

    @staticmethod
    def _stop_event(event) -> None:
        stopper = getattr(event, "stop_event", None)
        if callable(stopper):
            stopper()

    @staticmethod
    def _is_admin(event) -> bool:
        return getattr(event, "role", "") == "admin"

    def _is_session_allowed(self, event) -> bool:
        session_ids = self._event_session_ids(event)
        blocked_sessions = self._config_id_set("blocked_sessions")
        if blocked_sessions and session_ids & blocked_sessions:
            logger.info(
                "RoboMaster赛事助手忽略黑名单会话："
                f"{[mask_identifier(item) for item in sorted(session_ids)]}"
            )
            return False

        allowed_sessions = self._config_id_set("allowed_sessions")
        if allowed_sessions and not (session_ids & allowed_sessions):
            logger.info(
                "RoboMaster赛事助手忽略非白名单会话："
                f"{[mask_identifier(item) for item in sorted(session_ids)]}"
            )
            return False

        return True

    def _event_session_ids(self, event) -> set[str]:
        ids: set[str] = set()
        for value in self._event_scope_values(event):
            self._add_id_variants(ids, value)
        return ids

    @staticmethod
    def _event_scope_values(event) -> list[Any]:
        values: list[Any] = []
        for attr in (
            "unified_msg_origin",
            "session_id",
            "group_id",
            "user_id",
            "sender_id",
        ):
            values.append(getattr(event, attr, None))

        message_obj = getattr(event, "message_obj", None)
        if message_obj is not None:
            for attr in (
                "session_id",
                "group_id",
                "user_id",
                "sender_id",
                "self_id",
            ):
                values.append(getattr(message_obj, attr, None))

        return values

    @staticmethod
    def _add_id_variants(ids: set[str], value: Any) -> None:
        if value is None:
            return
        text = str(value).strip()
        if not text:
            return
        ids.add(text)
        for number in re.findall(r"\d{5,}", text):
            ids.add(number)

    def _config_id_set(self, key: str) -> set[str]:
        value = self._config_get(key, "")
        if value is None:
            return set()
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = re.split(r"[\s,，;；]+", str(value))
        return {item.strip() for item in raw_items if item.strip()}

    def _config_int_list(self, key: str) -> list[int]:
        values: list[int] = []
        for item in self._config_id_set(key):
            try:
                values.append(int(item))
            except ValueError:
                continue
        return values

    def _config_url_list(self, key: str) -> list[str]:
        value = self._config_get(key, "")
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(item) for item in value]
        else:
            raw_items = re.split(r"[\s,，]+", str(value))
        return [item.strip() for item in raw_items if item.strip()]

    def _config_str(self, key: str, default: str) -> str:
        value = self._config_get(key, default)
        return str(value or default)

    def _config_int(self, key: str, default: int) -> int:
        try:
            return int(self._config_get(key, default))
        except (TypeError, ValueError):
            return default

    def _config_float(self, key: str, default: float) -> float:
        try:
            return float(self._config_get(key, default))
        except (TypeError, ValueError):
            return default

    def _config_bool(self, key: str, default: bool) -> bool:
        value = self._config_get(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on", "启用", "是"}
        return bool(value)

    def _config_get(self, key: str, default: Any) -> Any:
        group_path = CONFIG_GROUPS.get(key)
        if group_path:
            value = self._nested_config_get(group_path, key)
            if value is not _MISSING:
                return value
        return default

    def _nested_config_get(self, group_path: tuple[str, ...], key: str) -> Any:
        group: Any = self.config
        for segment in group_path:
            group = _mapping_get(group, segment)
            if group is _MISSING:
                return _MISSING

        return _mapping_get(group, key)


_MISSING = object()


def _mapping_get(mapping: Any, key: str) -> Any:
    getter = getattr(mapping, "get", None)
    if callable(getter):
        return getter(key, _MISSING)
    if isinstance(mapping, dict) and key in mapping:
        return mapping[key]
    return _MISSING
