from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


DEFAULT_STATE: dict[str, Any] = {
    "notify_sessions": [],
    "announce_last_id": 0,
    "announce_page_hashes": {},
    "announce_recent_sent": {},
    "match_previous": {},
    "lark_notify_sessions": {},
    "forum_initialized": False,
    "forum_last_check_at": 0,
    "forum_last_error": "",
    "notification_circuit_breaker_recover_at": 0.0,
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
        except Exception:
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

    def add_session(self, session: str) -> bool:
        sessions = self.sessions
        if session in sessions:
            return False
        sessions.append(session)
        self.data["notify_sessions"] = sessions
        self.save()
        return True

    def remove_session(self, session: str) -> bool:
        sessions = self.sessions
        if session not in sessions:
            return False
        sessions.remove(session)
        self.data["notify_sessions"] = sessions
        lark_sessions = self.data.get("lark_notify_sessions", {})
        if isinstance(lark_sessions, dict):
            lark_sessions.pop(session, None)
            self.data["lark_notify_sessions"] = lark_sessions
        self.save()
        return True

    @property
    def sessions(self) -> list[str]:
        sessions = self.data.get("notify_sessions", [])
        if not isinstance(sessions, list):
            return []
        return [str(session) for session in sessions if str(session).strip()]

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

    def set_lark_session(self, session: str, chat_id: str) -> None:
        lark_sessions = self.data.get("lark_notify_sessions", {})
        if not isinstance(lark_sessions, dict):
            lark_sessions = {}
        lark_sessions[session] = {"chat_id": chat_id}
        self.data["lark_notify_sessions"] = lark_sessions
        self.save()

    def lark_chat_id(self, session: str) -> str:
        lark_sessions = self.data.get("lark_notify_sessions", {})
        if not isinstance(lark_sessions, dict):
            return ""
        item = lark_sessions.get(session, {})
        if not isinstance(item, dict):
            return ""
        return str(item.get("chat_id") or "").strip()

    def notification_circuit_breaker_recover_at(self) -> float:
        try:
            return float(self.data.get("notification_circuit_breaker_recover_at") or 0)
        except (TypeError, ValueError):
            return 0.0

    def set_notification_circuit_breaker_recover_at(self, recover_at: float) -> None:
        self.data["notification_circuit_breaker_recover_at"] = float(recover_at or 0)
        self.save()
