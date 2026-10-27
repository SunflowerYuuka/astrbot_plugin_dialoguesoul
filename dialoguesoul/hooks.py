from __future__ import annotations

import time
import uuid

from dialoguesoul import config as cfg
from dialoguesoul.context.components import component_to_dict
from dialoguesoul.decision import (
    parse_decision,
    parse_marker,
    rewrite_marker_response,
    rewrite_response,
)
from dialoguesoul.models import ChatKey, ChatMessage

_MARKER = "marker"


def _decision_format(event) -> str:
    return event.get_extra("ds_decision_format", _MARKER) or _MARKER


class Hooks:
    def __init__(self, repo, wake, config):
        self.repo = repo
        self.wake = wake
        self.config = config

    def on_llm_response(self, event, resp):
        if event.get_extra("ds_request_kind") != "decision":
            return
        text = getattr(resp, "completion_text", "") or ""
        if _decision_format(event) == _MARKER:
            decision = parse_marker(text)
            rewrite_marker_response(decision, resp)
        else:
            decision = parse_decision(
                text,
                int(cfg.get(self.config, "decision.max_reply_messages", 3)),
                float(cfg.get(self.config, "decision.min_confidence", 0.55)),
            )
            rewrite_response(decision, resp)
        event.set_extra("ds_decision", decision)

    async def on_decorating_result(self, event):
        if event.get_extra("ds_request_kind") != "decision":
            return
        decision = event.get_extra("ds_decision")
        fmt = _decision_format(event)
        if fmt == _MARKER:
            if decision is None or decision.action != "reply":
                event.clear_result()
            return

        result = event.get_result()
        if result is None:
            return
        if decision is None or decision.action != "reply":
            event.clear_result()
            return

        from astrbot.api.all import Plain, Reply

        chain = [Plain(text) for text in decision.messages]
        history_map = event.get_extra("ds_history_map") or {}
        if decision.quote and decision.quote in history_map:
            ref = history_map[decision.quote]
            chain.insert(0, Reply(id=ref["id"], sender_id=ref["sender_id"]))
        result.chain = chain

    async def after_message_sent(self, event):
        if not self.repo:
            return
        if event.get_extra("ds_request_kind") not in ("normal", "decision"):
            return

        result = getattr(event, "_result", None)
        chain = getattr(result, "chain", None) if result is not None else None
        if not chain:
            return

        key = ChatKey.from_event(event)
        now = time.time()
        message = ChatMessage(
            platform=key.platform,
            self_id=key.self_id,
            chat_type=key.chat_type,
            chat_id=key.chat_id,
            message_id="",
            sender_id=key.self_id,
            sender_name="AstrBot",
            timestamp=now,
            components=[component_to_dict(component) for component in chain],
        )
        await self.repo.append(message)

        try:
            days = int(cfg.get(self.config, "storage.retention_days", 30) or 0)
            if days:
                await self.repo.prune_before(now - days * 86400)
            keep = int(cfg.get(self.config, "storage.retention_count", 500) or 0)
            if keep:
                await self.repo.prune(*key.as_tuple(), keep_last=keep)
        except Exception as exc:
            from astrbot.api.all import logger

            logger.warning(f"历史记录清理失败: {exc}")

        wake_meta = event.get_extra("ds_wake")
        if wake_meta and self.wake:
            starts_session = bool(wake_meta.get("starts_session", False))
            session_id = wake_meta.get("session_id") or ""
            if not session_id and starts_session:
                session_id = uuid.uuid4().hex
            self.wake.record_delivery(
                key.as_tuple(),
                wake_meta["limits"],
                session_id,
                starts_session=starts_session,
            )
