from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass

from . import config as cfg
from .gate import GateResult
from .models import ChatKey


@dataclass(frozen=True)
class RouteDecision:
    kind: str
    gate: GateResult | None = None
    wake_session: object = None


class BurstGate:
    def __init__(self):
        self._times = defaultdict(list)
        self._burst_until = {}

    def record(self, key, now=None):
        now = time.time() if now is None else now
        self._times[key] = [t for t in self._times[key] if now - t < 60]
        self._times[key].append(now)

    def is_bursting(self, key, config, now=None):
        now = time.time() if now is None else now
        if not cfg.get(config, "trigger.burst.enabled", False):
            return False
        groups = {str(g) for g in cfg.get(config, "trigger.burst.groups", [])}
        if key[3] not in groups:
            return False
        threshold = int(cfg.get(config, "trigger.burst.threshold", 50))
        recent = [t for t in self._times[key] if now - t < 30]
        if len(recent) >= threshold:
            self._burst_until[key] = now + int(
                cfg.get(config, "trigger.burst.cooldown_seconds", 30)
            )
            return True
        return self._burst_until.get(key, 0) > now

    def prune(self, now=None, ttl=3600):
        now = time.time() if now is None else now
        removed = 0
        for key, times in list(self._times.items()):
            kept = [t for t in times if now - t < 60]
            if not kept or now - max(kept) >= ttl:
                self._times.pop(key, None)
                removed += 1
            else:
                self._times[key] = kept
        for key, until in list(self._burst_until.items()):
            if until <= now:
                self._burst_until.pop(key, None)
                removed += 1
        return removed


class StrategyEngine:
    def __init__(self, gate, wake, interest_judge=None):
        self.gate = gate
        self.wake = wake
        self.interest_judge = interest_judge
        self.burst = BurstGate()
        self._last_considered = {}

    async def route(self, event, config, history_text="", now=None):
        now = time.time() if now is None else now
        key = ChatKey.from_event(event).as_tuple()
        self.burst.record(key, now)
        direct = self.gate.is_direct_address(event)

        session = None
        if cfg.get(config, "wake.enabled", False):
            session = self.wake.get(key, now)
        if session is not None:
            hard = self.gate.hard_check(event, config, now)
            if hard is None:
                return RouteDecision("decision", None, session)
            return RouteDecision("ignore", hard)

        if direct:
            hard = self.gate.hard_check(event, config, now)
            if hard is None:
                return RouteDecision("normal")
            return RouteDecision("ignore", hard)

        if self.burst.is_bursting(key, config, now):
            return RouteDecision("ignore")

        strategy = cfg.get(config, "trigger.strategy", "window")
        if strategy == "rules":
            result = self.gate.check(event, config, now=now)
            if result.action != "candidate":
                return RouteDecision("ignore", result)
            return RouteDecision("decision", result)

        hard = self.gate.hard_check(event, config, now)
        if hard is not None:
            return RouteDecision("ignore", hard)

        if strategy == "window":
            window = float(cfg.get(config, "trigger.window_seconds", 30))
            if now - self._last_considered.get(key, 0) < window:
                return RouteDecision("ignore")
        elif strategy == "interest":
            if self.interest_judge is None:
                return RouteDecision("ignore")
            if not await self.interest_judge(event, history_text):
                return RouteDecision("ignore")

        if strategy == "window":
            self._last_considered[key] = now
        return RouteDecision("decision", GateResult("candidate", strategy, strategy, 1))

    def prune(self, now=None, ttl=3600):
        now = time.time() if now is None else now
        removed = 0
        for key, last in list(self._last_considered.items()):
            if now - last >= ttl:
                self._last_considered.pop(key, None)
                removed += 1
        return removed + self.burst.prune(now, ttl)
