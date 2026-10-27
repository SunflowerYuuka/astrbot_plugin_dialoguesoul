from __future__ import annotations

import asyncio
import time
import uuid

from . import config as cfg
from .context.components import exclude_current_message, user_message_from_event
from .context.live import (
    build_caption_service,
    build_forward_renderer,
    build_interest_judge,
    build_summary_service,
)
from .context.persona import resolve_persona_prompt
from .context.prompt import format_history
from .gate import Gate
from .hooks import Hooks
from .models import ChatKey
from .request_builder import RequestBuilder, history_limit
from .strategy import StrategyEngine
from .wake import WakeManager


class DialoguesSoulPlugin:
    def __init__(self, context, config, repo):
        self.context = context
        self.config = config
        self.repo = repo
        self.gate = Gate()
        self.wake = WakeManager()
        self.strategy = StrategyEngine(
            self.gate,
            self.wake,
            interest_judge=build_interest_judge(context, config),
        )
        self.hooks = Hooks(repo, self.wake, config, gate=self.gate)
        self.builder = RequestBuilder(
            repo=repo,
            persona_resolver=resolve_persona_prompt,
            caption_service=build_caption_service(context, config),
            forward_renderer=None,
        )
        self.summary_service = build_summary_service(context, config)
        self._locks = {}
        self._lock_seen = {}

    async def close(self):
        return None

    def prune_idle(self, now=None, ttl=3600):
        now = time.time() if now is None else now
        self.strategy.prune(now, ttl)
        removed = 0
        for key, seen in list(self._lock_seen.items()):
            lock = self._locks.get(key)
            if lock is None:
                self._lock_seen.pop(key, None)
            elif not lock.locked() and now - seen >= ttl:
                self._locks.pop(key, None)
                self._lock_seen.pop(key, None)
                removed += 1
        return removed

    async def handle_message(self, event):
        self.wake.clear_expired()
        key = ChatKey.from_event(event).as_tuple()
        if cfg.chat_enabled(event, self.config) and str(event.get_sender_id()) != str(
            event.get_self_id()
        ):
            await self.repo.append(user_message_from_event(event))

        self.prune_idle()
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        direct = self.gate.is_direct_address(event)
        if lock.locked() and not direct:
            return
        async with lock:
            self._lock_seen[key] = time.time()
            limit = history_limit(self.config, True)
            history = exclude_current_message(
                await self.repo.recent(*key, limit), event
            )
            history_text = format_history(history)
            route = await self.strategy.route(
                event, self.config, history_text=history_text
            )
            if route.kind == "ignore":
                return
            decision = route.kind == "decision"
            built = await self.builder.build(
                event,
                self.config,
                decision=decision,
                wake_session=route.wake_session,
                context=self.context,
                decision_format=cfg.get(self.config, "decision.format", "marker"),
                forward_renderer=build_forward_renderer(event, self.config),
                summary_service=self.summary_service,
            )
            if route.wake_session is not None:
                event.set_extra(
                    "ds_wake",
                    {
                        "session_id": route.wake_session.session_id,
                        "limits": route.wake_session.limits,
                        "starts_session": False,
                    },
                )
            elif decision and cfg.get(self.config, "wake.enabled", False):
                session_id = uuid.uuid4().hex
                limits = self.wake.resolve_limits(event, self.config)
                self.wake.reserve(key, limits, session_id)
                event.set_extra(
                    "ds_wake",
                    {
                        "session_id": session_id,
                        "limits": limits,
                        "starts_session": True,
                    },
                )
            yield built.request
