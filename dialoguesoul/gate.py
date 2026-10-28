from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass

from . import config as cfg
from .context.components import collect_text
from .models import ChatKey

_QUESTION = re.compile(r"[?？]|^(吗|呢|怎么|为什么|如何|什么|谁|哪|几|多少|是不是|能不能|可不可以)")
_RATE_WINDOW = 60.0


def plain_text(event) -> str:
    """去掉 At/Reply 等非文本段后的可见文本。"""
    components = getattr(getattr(event, "message_obj", None), "message", None) or []
    if components:
        return collect_text(components).strip()
    return (event.get_message_outline() or "").strip()


@dataclass(frozen=True)
class GateResult:
    action: str
    reason: str
    trigger: str = "none"
    priority: int = 0


class Gate:
    """硬门控与触发判定。

    ``hard_check`` 只做与触发无关的硬性拦截；``check`` 在其结果之上再做
    直接呼唤、关键词、提问与概率判定。
    """

    def __init__(self):
        self._last_reply: dict[tuple, float] = {}
        self._reply_times: dict[tuple, list[float]] = {}
        self._seen: dict[str, float] = {}
        self._mutes: dict[tuple, float] = {}
        self._seen_ttl = 300.0

    def reset(self):
        self._last_reply.clear()
        self._reply_times.clear()
        self._seen.clear()
        self._mutes.clear()

    def mute(self, key, until: float) -> None:
        self._mutes[tuple(key)] = float(until)

    def unmute(self, key) -> None:
        self._mutes.pop(tuple(key), None)

    def muted(self, key, now: float) -> bool:
        until = self._mutes.get(tuple(key))
        if until is None:
            return False
        if until <= now:
            self._mutes.pop(tuple(key), None)
            return False
        return True

    @staticmethod
    def is_direct_address(event) -> bool:
        self_id = str(event.get_self_id())
        components = getattr(getattr(event, "message_obj", None), "message", None) or []
        for component in components:
            if str(getattr(component, "qq", "")) == self_id:
                return True
            if str(getattr(component, "sender_id", "")) == self_id:
                return True
        return False

    def _limited(self, key, config, bypass: bool, now: float) -> str | None:
        if bypass:
            return None
        cooldown = cfg.get(config, "decision.cooldown_ms", 3000) / 1000
        if now - self._last_reply.get(key, 0) < cooldown:
            return "cooldown"
        times = [t for t in self._reply_times.get(key, []) if now - t < _RATE_WINDOW]
        self._reply_times[key] = times
        if len(times) >= cfg.get(config, "decision.max_replies_per_minute", 6):
            return "rate_limited"
        return None

    def hard_check(self, event, config, now: float | None = None) -> GateResult | None:
        """只做硬门控；通过返回 ``None``，被拦截返回 skip 结果。"""
        now = time.time() if now is None else now
        key = ChatKey.from_event(event)
        if not cfg.chat_enabled(event, config):
            return GateResult("skip", "chat_disabled")
        if self.muted(key.as_tuple(), now):
            return GateResult("skip", "muted")
        direct = self.is_direct_address(event)
        text = (event.get_message_outline() or "").strip()
        if not text and not direct:
            return GateResult("skip", "empty")
        prefixes = cfg.get(config, "trigger.ignored_prefixes", []) or []
        stripped = plain_text(event).lstrip()
        if any(prefix and stripped.startswith(prefix) for prefix in prefixes):
            return GateResult("skip", "command_prefix")
        if str(event.get_sender_id()) == str(event.get_self_id()):
            return GateResult("skip", "self")

        message_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        seen_key = (
            f"{event.get_platform_name()}:{event.get_self_id()}"
            f":{event.get_group_id() or event.get_sender_id()}:{message_id}"
        )
        self._seen = {k: t for k, t in self._seen.items() if now - t < self._seen_ttl}
        if message_id and seen_key in self._seen:
            return GateResult("skip", "duplicate")

        blacklist = cfg.get(config, "trigger.blacklist_keywords", []) or []
        if any(word in text for word in blacklist):
            return GateResult("skip", "blacklist_keyword")

        limited = self._limited(key.as_tuple(), config, bypass=direct, now=now)
        if limited:
            return GateResult("skip", limited)
        # 仅在真正通过硬门控后才记入去重表，避免被冷却/限流拦下的消息被误判为重复
        if message_id:
            self._seen[seen_key] = now
        return None

    def check(self, event, config, now: float | None = None) -> GateResult:
        """硬门控 + 触发判定；并发拦截由调用方的 per-chat 锁负责。"""
        hard = self.hard_check(event, config, now)
        if hard is not None:
            return hard
        text = plain_text(event)
        if self.is_direct_address(event):
            return GateResult("candidate", "mentioned", "mention", 2)
        keywords = cfg.get(config, "trigger.keywords", []) or []
        if any(word in text for word in keywords):
            return GateResult("candidate", "keyword", "keyword", 1)
        if _QUESTION.search(text):
            return GateResult("candidate", "question", "question", 1)
        probability = float(cfg.get(config, "trigger.probability", 0.0) or 0.0)
        if probability > 0 and random.random() < probability:
            return GateResult("candidate", "random", "random", 0)
        return GateResult("skip", "no_trigger")

    def record_reply(self, event, now: float | None = None) -> float:
        now = time.time() if now is None else now
        key = ChatKey.from_event(event).as_tuple()
        self._last_reply[key] = now
        # 顺带裁剪过期记录：直接呼唤会绕过 _limited，若只在那里裁剪，列表会无界增长
        times = [t for t in self._reply_times.get(key, []) if now - t < _RATE_WINDOW]
        times.append(now)
        self._reply_times[key] = times
        return now
