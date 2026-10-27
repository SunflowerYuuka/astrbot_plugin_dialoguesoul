from __future__ import annotations

import asyncio
import uuid

from dialoguesoul import config as cfg
from dialoguesoul.context.components import user_message_from_event
from dialoguesoul.context.live import (
    build_caption_service,
    build_forward_renderer,
    build_interest_judge,
    build_summary_service,
)
from dialoguesoul.context.persona import resolve_persona_prompt
from dialoguesoul.context.prompt import format_history
from dialoguesoul.gate import Gate
from dialoguesoul.hooks import Hooks
from dialoguesoul.models import ChatKey
from dialoguesoul.request_builder import RequestBuilder
from dialoguesoul.strategy import StrategyEngine
from dialoguesoul.wake import WakeManager


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
        self.hooks = Hooks(repo, self.wake, config)
        self.builder = RequestBuilder(
            repo=repo,
            persona_resolver=resolve_persona_prompt,
            caption_service=build_caption_service(context, config),
            forward_renderer=None,
        )
        self.summary_service = build_summary_service(context, config)
        self._locks = {}

    async def close(self):
        return None

    async def handle_message(self, event):
        key = ChatKey.from_event(event).as_tuple()
        if cfg.chat_enabled(event, self.config) and str(event.get_sender_id()) != str(
            event.get_self_id()
        ):
            await self.repo.append(user_message_from_event(event))

        lock = self._locks.setdefault(key, asyncio.Lock())
        direct = self.gate.is_direct_address(event)
        if lock.locked() and not direct:
            return
        async with lock:
            limit = int(cfg.get(self.config, "context.history_limit", 20))
            history = await self.repo.recent(*key, limit)
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
