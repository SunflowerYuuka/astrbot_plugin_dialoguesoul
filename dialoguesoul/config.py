from __future__ import annotations

from typing import Any

DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "enable_all_groups": False,
    "enabled_groups": [],
    "blocked_groups": [],
    "enabled_private": False,
    "trigger": {
        "probability": 0.1,
        "strategy": "window",
        "window_seconds": 30,
        "interest": {"provider_id": ""},
        "burst": {
            "enabled": False,
            "groups": [],
            "threshold": 50,
            "cooldown_seconds": 30,
        },
        "keywords": [],
        "blacklist_keywords": [],
        "ignored_prefixes": [],
    },
    "decision": {
        "format": "marker",
        "max_reply_messages": 3,
        "min_confidence": 0.55,
        "timeout_ms": 2000,
        "max_context_messages": 20,
        "cooldown_ms": 3000,
        "max_replies_per_minute": 6,
    },
    "wake": {
        "enabled": False,
        "duration_seconds": 300,
        "max_replies": 5,
        "idle_timeout_seconds": 120,
        # 私聊默认与全局一致；管理员默认三项均为 0（不限）
        "private": {
            "duration_seconds": 300,
            "max_replies": 5,
            "idle_timeout_seconds": 120,
        },
        "admin": {
            "duration_seconds": 0,
            "max_replies": 0,
            "idle_timeout_seconds": 0,
        },
        "groups": [],
    },
    "context": {
        "history_limit": 20,
        "summary": {
            "enabled": False,
            "provider_id": "",
            "threshold": 20,
        },
        "image_caption": {
            "enabled": False,
            "provider_id": "",
            "prompt": "请直接简短描述这张图片",
            "concurrency": 3,
            "cache_size": 128,
        },
        "forward": {
            "parse": False,
            "max_depth": 2,
            "max_nodes": 50,
            "max_chars": 2000,
            "timeout": 5,
        },
    },
    "persona": {"enabled": True, "name": ""},
    "extra_prompt": {"enabled": False, "text": ""},
    "storage": {"db_path": "", "retention_days": 30, "retention_count": 500},
}


def get(config: Any, path: str, default=None):
    current = config
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def chat_key_id(key) -> str:
    return "|".join(str(part) for part in key.as_tuple())


def _until(value) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def mute_until(config, key) -> float:
    mute = config.get("_temp_mute", {}) or {}
    if not isinstance(mute, dict):
        return 0.0
    until = _until(mute.get("until", 0))
    entry = mute.get(chat_key_id(key))
    if isinstance(entry, dict):
        until = max(until, _until(entry.get("until", 0)))
    return until


def chat_enabled(event, config) -> bool:
    if event.is_private_chat():
        return bool(get(config, "enabled_private", False))
    group_id = str(event.get_group_id() or "").strip()
    if not group_id:
        return False
    blocked = {str(g).strip() for g in get(config, "blocked_groups", [])}
    if group_id in blocked:
        return False
    if get(config, "enable_all_groups", False):
        return True
    enabled = {str(g).strip() for g in get(config, "enabled_groups", [])}
    return group_id in enabled
