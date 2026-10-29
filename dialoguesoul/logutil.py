from __future__ import annotations

import time

_WARN_INTERVAL = 60.0
_last_warned: dict[str, float] = {}


def warn_once(key: str, message: str, interval: float = _WARN_INTERVAL) -> None:
    """按 key 限流输出警告，避免辅助模型故障时刷屏日志。"""
    now = time.time()
    if now - _last_warned.get(key, 0.0) < interval:
        return
    _last_warned[key] = now
    try:
        from astrbot.api.all import logger

        logger.warning(message)
    except Exception:
        pass
