from __future__ import annotations

import time
from dataclasses import dataclass

from . import config as cfg
from .models import ChatKey

_RESERVATION_TTL = 60.0


@dataclass(frozen=True)
class WakeLimits:
    duration_seconds: int = 300
    max_replies: int = 5
    idle_timeout_seconds: int = 120


@dataclass
class WakeSession:
    limits: WakeLimits
    started_at: float
    last_activity_at: float
    session_id: str
    consumed_replies: int = 0


class WakeManager:
    def __init__(self):
        self._sessions: dict[tuple, WakeSession] = {}
        self._reserved: dict[tuple, tuple[str, float]] = {}

    @staticmethod
    def key_for(event) -> tuple:
        return ChatKey.from_event(event).as_tuple()

    def _group_overrides(self, wake) -> dict:
        groups = wake.get("groups", []) or []
        if isinstance(groups, dict):
            return groups
        overrides = {}
        if isinstance(groups, list):
            for entry in groups:
                if isinstance(entry, dict) and str(entry.get("group_id", "")).strip():
                    overrides[str(entry["group_id"]).strip()] = entry
        return overrides

    def resolve_limits(self, event, config) -> WakeLimits:
        wake = config.get("wake", {}) or {}
        if getattr(event, "is_admin", lambda: False)():
            override = wake.get("admin", {}) or {}
        elif event.is_private_chat():
            override = wake.get("private", {}) or {}
        else:
            override = self._group_overrides(wake).get(str(event.get_group_id()), {}) or {}

        defaults = cfg.DEFAULTS["wake"]

        def value(name):
            raw = override.get(name, "")
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                raw = wake.get(name, defaults[name])
            try:
                return int(raw)
            except (TypeError, ValueError):
                try:
                    return int(wake.get(name, defaults[name]))
                except (TypeError, ValueError):
                    return int(defaults[name])

        return WakeLimits(
            value("duration_seconds"),
            value("max_replies"),
            value("idle_timeout_seconds"),
        )

    def _expired(self, session: WakeSession, now: float) -> bool:
        limits = session.limits
        return bool(
            (limits.duration_seconds > 0 and now - session.started_at >= limits.duration_seconds)
            or (
                limits.idle_timeout_seconds > 0
                and now - session.last_activity_at >= limits.idle_timeout_seconds
            )
            or (limits.max_replies > 0 and session.consumed_replies >= limits.max_replies)
        )

    def _drop_session(self, key, session: WakeSession) -> None:
        self._sessions.pop(key, None)
        reserved = self._reserved.get(key)
        if reserved is not None and reserved[0] == session.session_id:
            self._reserved.pop(key, None)

    @staticmethod
    def _reservation_expired(reserved, now: float) -> bool:
        return now - reserved[1] >= _RESERVATION_TTL

    def _prune_reservations(self, now: float) -> None:
        for key, reserved in list(self._reserved.items()):
            if self._reservation_expired(reserved, now):
                self._reserved.pop(key, None)

    def clear_expired(self, now: float | None = None):
        now = time.time() if now is None else now
        for key, session in list(self._sessions.items()):
            if self._expired(session, now):
                self._drop_session(key, session)
        self._prune_reservations(now)

    def get(self, key, now: float | None = None) -> WakeSession | None:
        now = time.time() if now is None else now
        self._prune_reservations(now)
        session = self._sessions.get(key)
        if session is not None and self._expired(session, now):
            self._drop_session(key, session)
            return None
        return session

    def is_active(self, key, now: float | None = None) -> bool:
        return self.get(key, now) is not None

    def clear_chat(self, key) -> bool:
        """立即结束该聊天的唤醒会话与预留。"""
        removed = self._sessions.pop(tuple(key), None) is not None
        self._reserved.pop(tuple(key), None)
        return removed

    def reserve(self, key, limits, session_id, now: float | None = None):
        now = time.time() if now is None else now
        self._prune_reservations(now)
        self.get(key, now)
        self._reserved[key] = (session_id, now)

    def record_delivery(
        self,
        key,
        limits: WakeLimits,
        session_id: str,
        starts_session: bool = False,
        now: float | None = None,
    ) -> bool:
        now = time.time() if now is None else now
        session = self.get(key, now)
        if session is not None:
            if session.session_id != session_id:
                return False
            session.limits = limits
            session.consumed_replies += 1
            session.last_activity_at = now
            reserved = self._reserved.get(key)
            if reserved is not None and reserved[0] == session_id:
                self._reserved.pop(key, None)
            return True

        reserved = self._reserved.get(key)
        if not starts_session or not reserved or reserved[0] != session_id:
            return False
        if self._reservation_expired(reserved, now):
            self._reserved.pop(key, None)
            return False
        self._reserved.pop(key, None)
        self._sessions[key] = WakeSession(
            limits=limits,
            started_at=now,
            last_activity_at=now,
            session_id=session_id,
            consumed_replies=1,
        )
        return True
