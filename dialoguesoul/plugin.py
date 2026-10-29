from __future__ import annotations

import asyncio
import time
import uuid

from . import config as cfg
from .context.components import (
    collect_image_urls,
    exclude_current_message,
    user_message_from_event,
)
from .context.live import (
    build_caption_service,
    build_forward_renderer,
    build_interest_judge,
    build_intervention_judge,
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

# 直呼消息等待该聊天上一条回复的最长时间。超时后不再串行等待，
# 避免某次模型调用卡死时该聊天永久失去响应。
_LOCK_WAIT_SECONDS = 120.0


def _warn_lock_timeout() -> None:
    try:
        from astrbot.api.all import logger

        logger.warning(
            "DialoguesSoul: 等待该聊天的上一条回复超过 %.0f 秒，本次未串行等待",
            _LOCK_WAIT_SECONDS,
        )
    except Exception:
        pass


class _TimedLock:
    """带超时的聊天锁：超时后放行并记录日志，而不是无限等待。"""

    def __init__(self, lock: asyncio.Lock, timeout: float):
        self.lock = lock
        self.timeout = timeout
        self.acquired = False

    async def __aenter__(self):
        try:
            await asyncio.wait_for(self.lock.acquire(), timeout=self.timeout)
            self.acquired = True
        except asyncio.TimeoutError:
            self.acquired = False
            _warn_lock_timeout()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.acquired:
            self.lock.release()
        return False


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
        self.intervention_judge = build_intervention_judge(context, config)
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
        self._delay_cancels = {}

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

    async def _wait_window_images(self, key, since):
        messages = await self.repo.recent(*key, history_limit(self.config, True))
        urls = []
        for message in messages:
            if message.timestamp >= since:
                urls.extend(collect_image_urls(message.components))
        return urls

    async def _wait_delay(self, cancel, delay):
        try:
            await asyncio.wait_for(cancel.wait(), timeout=delay)
        except asyncio.TimeoutError:
            return False
        return True

    def cancel_pending(self, key) -> bool:
        """打断该聊天正在等待的主动回复。"""
        cancel = self._delay_cancels.get(tuple(key))
        if cancel is None:
            return False
        cancel.set()
        return True

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
        if direct:
            cancel = self._delay_cancels.get(key)
            if cancel is not None:
                cancel.set()
        if lock.locked() and not direct:
            return
        async with _TimedLock(lock, _LOCK_WAIT_SECONDS):
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
            # 私聊在唤醒会话中仍先等待，以便把等待窗口内到达的图片一起送入模型；
            # 但私聊不注入 "群成员参与判断" 的决策协议，也不做介入判断。
            private_normal = decision and event.is_private_chat()
            extra_image_urls = []
            if decision and not direct:
                delay = float(
                    cfg.get(self.config, "trigger.proactive_delay_seconds", 5) or 0
                )
                if delay > 0:
                    wait_started = time.time()
                    cancel = asyncio.Event()
                    self._delay_cancels[key] = cancel
                    try:
                        cancelled = await self._wait_delay(cancel, delay)
                    finally:
                        if self._delay_cancels.get(key) is cancel:
                            self._delay_cancels.pop(key, None)
                    if cancelled:
                        return
                    extra_image_urls = await self._wait_window_images(key, wait_started)
            intervention = (
                decision
                and not direct
                and not private_normal
                and self.intervention_judge is not None
            )
            if intervention:
                gate_history = exclude_current_message(
                    await self.repo.recent(*key, limit), event
                )
                if not await self.intervention_judge(
                    event, format_history(gate_history)
                ):
                    return
            starts_session = (
                route.wake_session is None
                and cfg.get(self.config, "wake.enabled", False)
                and (decision or event.is_private_chat())
            )
            session_id = uuid.uuid4().hex if starts_session else ""
            limits = (
                self.wake.resolve_limits(event, self.config)
                if starts_session
                else None
            )
            built = await self.builder.build(
                event,
                self.config,
                decision=decision and not private_normal,
                wake_session=route.wake_session,
                context=self.context,
                decision_format=cfg.get(self.config, "decision.format", "marker"),
                forward_renderer=build_forward_renderer(event, self.config),
                summary_service=self.summary_service,
                wake_starts=starts_session,
                wake_limits=limits,
                extra_image_urls=extra_image_urls,
                proactive_reply=intervention,
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
            elif starts_session:
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
