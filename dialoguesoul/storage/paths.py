from __future__ import annotations

from pathlib import Path

_FALLBACK_DATA_DIR = Path("data") / "plugin_data" / "dialoguesoul"


def _astrbot_data_dir() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_data_path
    except ImportError:
        return Path("data")
    try:
        return Path(get_astrbot_data_path())
    except Exception:
        return Path("data")


def _plugin_data_dir() -> Path:
    return _astrbot_data_dir() / "plugin_data" / "dialoguesoul"


def resolve_db_path(config) -> str:
    storage = config.get("storage", {}) if hasattr(config, "get") else {}
    explicit = str((storage or {}).get("db_path", "") or "").strip()
    if explicit:
        return explicit
    return str(_plugin_data_dir() / "dialoguesoul.sqlite3")


def legacy_history_path() -> str:
    """旧 SpectreCore 历史目录，基于 AstrBot 数据目录而非进程 CWD。"""
    return str(_astrbot_data_dir() / "chat_history")
