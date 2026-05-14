from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any

from astrbot.api import logger


DEFAULT_STATE: dict[str, Any] = {
    "notify_sessions": [],
    "announce_notify_sessions": [],
    "match_notify_sessions": [],
    "forum_notify_sessions": [],
    "announce_last_id": 0,
    "announce_page_hashes": {},
    "announce_recent_sent": {},
    "match_previous": {},
    "lark_notify_sessions": {},
    "known_sessions": {},
    "forum_initialized": False,
    "forum_last_check_at": 0,
    "forum_last_error": "",
    "notification_circuit_breaker_recover_at": 0.0,
}


SESSION_KEYS = {
    "announcement": "announce_notify_sessions",
    "match": "match_notify_sessions",
    "forum": "forum_notify_sessions",
}


class MonitorState:
    def __init__(self, path: Path):
        self.path = path
        self.data = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return dict(DEFAULT_STATE)
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"RM 状态文件加载失败，使用默认状态：{self.path} {exc}")
            return dict(DEFAULT_STATE)
        data = dict(DEFAULT_STATE)
        data.update(loaded if isinstance(loaded, dict) else {})
        return data

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add_session(self, channel: str, session: str) -> bool:
        sessions = self.sessions(channel)
        if session in sessions:
            return False
        sessions.append(session)
        self.data[session_key(channel)] = sessions
        self.save()
        return True

    def remove_session(self, channel: str, session: str) -> bool:
        sessions = self.sessions(channel)
        if session not in sessions:
            return False
        sessions.remove(session)
        self.data[session_key(channel)] = sessions
        self.remove_lark_session(channel, session)
        self.save()
        return True

    def sessions(self, channel: str) -> list[str]:
        sessions = self.data.get(session_key(channel), [])
        if not isinstance(sessions, list):
            return []
        return [str(session) for session in sessions if str(session).strip()]

    def remember_session_aliases(self, session: str, aliases: set[str] | list[str]) -> None:
        session = str(session or "").strip()
        if not session:
            return
        known = self.known_sessions()
        known[session] = session
        for alias in aliases:
            text = str(alias or "").strip()
            if not text:
                continue
            known[text] = session
            for number in re.findall(r"\d{5,}", text):
                known[number] = session
        self.data["known_sessions"] = known
        self.save()

    def resolve_session(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        known = self.known_sessions()
        if text in known:
            return known[text]
        if _is_bare_id(text):
            return ""
        return text

    def known_sessions(self) -> dict[str, str]:
        known = self.data.get("known_sessions", {})
        if not isinstance(known, dict):
            return {}
        return {
            str(alias).strip(): str(session).strip()
            for alias, session in known.items()
            if str(alias).strip() and str(session).strip()
        }

    def remember_recent_announcement(self, announcement_id: int, ttl_seconds: int = 3600) -> bool:
        now = int(time.time())
        recent = {
            str(key): int(value)
            for key, value in self.data.get("announce_recent_sent", {}).items()
            if now - int(value) <= ttl_seconds
        }
        key = str(announcement_id)
        if key in recent:
            self.data["announce_recent_sent"] = recent
            self.save()
            return False
        recent[key] = now
        self.data["announce_recent_sent"] = recent
        self.save()
        return True

    def set_lark_session(self, channel: str, session: str, chat_id: str) -> None:
        channel_sessions = self._lark_channel_sessions(channel)
        channel_sessions[session] = {"chat_id": chat_id}
        self.save()

    def remove_lark_session(self, channel: str, session: str) -> None:
        channel_sessions = self._lark_channel_sessions(channel)
        channel_sessions.pop(session, None)

    def lark_chat_id(self, channel: str, session: str) -> str:
        item = self._lark_channel_sessions(channel).get(session, {})
        if not isinstance(item, dict):
            return ""
        return str(item.get("chat_id") or "").strip()

    def _lark_channel_sessions(self, channel: str) -> dict[str, Any]:
        lark_sessions = self.data.get("lark_notify_sessions", {})
        if not isinstance(lark_sessions, dict):
            lark_sessions = {}
        channel_sessions = lark_sessions.get(channel)
        if not isinstance(channel_sessions, dict):
            channel_sessions = {}
        lark_sessions[channel] = channel_sessions
        self.data["lark_notify_sessions"] = lark_sessions
        return channel_sessions

    def notification_circuit_breaker_recover_at(self) -> float:
        try:
            return float(self.data.get("notification_circuit_breaker_recover_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    def set_notification_circuit_breaker_recover_at(self, recover_at: float) -> None:
        self.data["notification_circuit_breaker_recover_at"] = float(recover_at or 0)
        self.save()


def session_key(channel: str) -> str:
    return SESSION_KEYS.get(channel, f"{channel}_notify_sessions")


def _is_bare_id(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5,}", value.strip()))
