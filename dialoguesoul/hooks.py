from __future__ import annotations

import json
import time
import uuid

from . import config as cfg
from .context.components import component_to_dict
from .decision import (
    Decision,
    parse_decision,
    parse_marker,
    parse_reply,
    rewrite_marker_response,
    rewrite_response,
)
from .models import ChatKey, ChatMessage

_MARKER = "marker"


def _decision_format(event) -> str:
    return event.get_extra("ds_decision_format", _MARKER) or _MARKER


def _reply_format(event) -> str:
    return event.get_extra("ds_reply_format", "plain") or "plain"


def _chain_text(chain) -> str:
    """取消息链里所有文本段拼接后的文本（忽略引用、图片等非文本段）。"""
    parts = []
    for component in chain or []:
        text = getattr(component, "text", None)
        if isinstance(text, str):
            parts.append(text)
    return "".join(parts).strip()


def _looks_like_json_object(text: str) -> bool:
    stripped = (text or "").strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return False
    try:
        return isinstance(json.loads(stripped), dict)
    except Exception:
        return False


class Hooks:
    def __init__(self, repo, wake, config, gate=None):
        self.repo = repo
        self.wake = wake
        self.config = config
        self.gate = gate

    def on_llm_response(self, event, resp):
        kind = event.get_extra("ds_request_kind")
        role = getattr(resp, "role", "assistant")
        text = getattr(resp, "completion_text", "") or ""

        if kind == "proactive_reply":
            if role != "assistant":
                reply = Decision("ignore", f"role:{role}", [], 0.0, None)
                event.set_extra("ds_reply", reply)
                resp.completion_text = ""
                event.set_extra("ds_llm_text", "")
                return
            if _reply_format(event) == "json":
                reply = parse_reply(
                    text,
                    int(cfg.get(self.config, "decision.max_reply_messages", 3)),
                )
            else:
                reply = parse_marker(text)
            event.set_extra("ds_reply", reply)
            rewrite_response(reply, resp)
            event.set_extra("ds_llm_text", resp.completion_text or "")
            return

        if kind != "decision":
            return
        if role != "assistant":
            event.set_extra(
                "ds_decision", Decision("ignore", f"role:{role}", [], 0.0, None)
            )
            resp.completion_text = ""
            event.set_extra("ds_llm_text", "")
            return
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
        event.set_extra("ds_llm_text", resp.completion_text or "")

    async def on_decorating_result(self, event):
        kind = event.get_extra("ds_request_kind")
        if kind == "proactive_reply":
            reply = event.get_extra("ds_reply")
            if reply is None or reply.action != "reply":
                event.clear_result()
                return
            result = event.get_result()
            if result is None:
                return
            reply = self._apply_cleaned_text(event, result, reply, _reply_format(event))
            if reply.action != "reply":
                event.clear_result()
                return

            from astrbot.api.all import Plain, Reply

            chain = [Plain("\n".join(reply.messages))]
            history_map = event.get_extra("ds_history_map") or {}
            if reply.quote and reply.quote in history_map:
                ref = history_map[reply.quote]
                chain.insert(0, Reply(id=ref["id"], sender_id=ref["sender_id"]))
            result.chain = chain
            return

        if kind != "decision":
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
        decision = self._apply_cleaned_text(event, result, decision, fmt)
        if decision.action != "reply":
            event.clear_result()
            return

        from astrbot.api.all import Plain, Reply

        chain = [Plain("\n".join(decision.messages))]
        history_map = event.get_extra("ds_history_map") or {}
        if decision.quote and decision.quote in history_map:
            ref = history_map[decision.quote]
            chain.insert(0, Reply(id=ref["id"], sender_id=ref["sender_id"]))
        result.chain = chain

    def _max_messages(self) -> int:
        return int(cfg.get(self.config, "decision.max_reply_messages", 3))

    def _apply_cleaned_text(self, event, result, decision, fmt: str) -> Decision:
        """以最终消息链为准重新解析回复，兼容其他插件对文本的清洗。

        ``on_llm_response`` 里已经按原始文本解析过一次；如果之后其他插件
        （如好感度插件）清理了 ``completion_text`` 中的标签或表情标记，
        这里用最终链文本重新解析，避免用清洗前的结果把它们覆盖回去。
        """
        expected = str(event.get_extra("ds_llm_text") or "").strip()
        current = _chain_text(getattr(result, "chain", None))
        if current == expected:
            return decision
        if not current:
            return Decision("ignore", "cleaned_empty", [], 0.0, None)
        if fmt == "json":
            parsed = parse_reply(current, self._max_messages())
            if parsed.action == "reply":
                if parsed.quote is None:
                    parsed.quote = decision.quote
                return parsed
            if _looks_like_json_object(current):
                return Decision("ignore", "parse_failed", [], 0.0, None)
            lines = [line.strip() for line in current.splitlines() if line.strip()]
            messages = lines[: self._max_messages()] or [current]
            return Decision(
                "reply", decision.reason, messages, decision.confidence, decision.quote
            )
        return parse_marker(current)

    @staticmethod
    def _send_confirmed(event) -> bool:
        """aiocqhttp 用 ``_has_send_oper`` 判断发送是否真正完成。

        其他适配器（如 qqofficial）不调用基类 ``send``，该标志始终为
        False；没有可靠失败信号时保持原有 best-effort 行为。
        """
        platform = str(getattr(event, "get_platform_name", lambda: "")() or "")
        if platform.lower() != "aiocqhttp":
            return True
        return bool(getattr(event, "_has_send_oper", False))

    async def after_message_sent(self, event):
        """Record a sent reply and advance per-chat/wake state.

        AstrBot 4.29.1's ``RespondStage`` catches adapter send exceptions and
        still emits ``after_message_sent``. On aiocqhttp, ``_has_send_oper`` is
        set only after the adapter send completes, so failed sends are skipped.
        Other adapters may not set the flag; they keep best-effort accounting.
        """
        if not self.repo:
            return
        if event.get_extra("ds_request_kind") not in (
            "normal",
            "decision",
            "proactive_reply",
        ):
            return

        result = getattr(event, "_result", None)
        chain = getattr(result, "chain", None) if result is not None else None
        if not chain:
            return
        if not self._send_confirmed(event):
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
        if self.gate is not None:
            self.gate.record_reply(event)
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
