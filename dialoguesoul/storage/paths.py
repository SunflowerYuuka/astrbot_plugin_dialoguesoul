from __future__ import annotations

from pathlib import Path

_FALLBACK_DATA_DIR = Path("data") / "plugin_data" / "dialoguesoul"


def _plugin_data_dir() -> Path:
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
    except ImportError:
        return _FALLBACK_DATA_DIR
    return Path(get_astrbot_plugin_data_path()) / "dialoguesoul"


def resolve_db_path(config) -> str:
    storage = config.get("storage", {}) if hasattr(config, "get") else {}
    explicit = str((storage or {}).get("db_path", "") or "").strip()
    if explicit:
        return explicit
    return str(_plugin_data_dir() / "dialoguesoul.sqlite3")
