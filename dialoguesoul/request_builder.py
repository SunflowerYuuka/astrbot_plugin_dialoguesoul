from __future__ import annotations

from dataclasses import dataclass

from . import config as cfg
from .context.components import (
    collect_forward_ids,
    collect_image_urls,
    component_to_dict,
    exclude_current_message,
)
from .context.prompt import (
    build_environment,
    build_system_prompt,
    format_history,
    sender_label,
)
from .decision import build_reply_instruction
from .models import ChatKey


def history_limit(config, decision: bool) -> int:
    path = "decision.max_context_messages" if decision else "context.history_limit"
    return int(cfg.get(config, path, 20))


@dataclass
class BuiltRequest:
    request: object


class RequestBuilder:
    def __init__(
        self,
        repo,
        persona_resolver,
        caption_service=None,
        forward_renderer=None,
        summary_service=None,
    ):
        self.repo = repo
        self.persona_resolver = persona_resolver
        self.caption_service = caption_service
        self.forward_renderer = forward_renderer
        self.summary_service = summary_service

    async def _caption_history(self, history, caption, config, enabled, event):
        """为最近若干条历史里的图片补转述，默认关闭以免额外开销。"""
        if caption is None or not enabled:
            return {}
        try:
            window = int(
                cfg.get(config, "context.image_caption.history_messages", 0) or 0
            )
        except (TypeError, ValueError):
            window = 0
        if window <= 0:
            return {}
        urls = []
        for message in history[-window:]:
            urls.extend(collect_image_urls(message.components))
        if not urls:
            return {}
        return await caption.caption(urls, umo=event.unified_msg_origin)

    async def build(
        self,
        event,
        config,
        *,
        decision: bool,
        wake_session,
        context,
        decision_format: str = "marker",
        caption_service=None,
        forward_renderer=None,
        summary_service=None,
        wake_starts: bool = False,
        wake_limits=None,
        extra_image_urls=None,
        proactive_reply: bool = False,
    ) -> BuiltRequest:
        key = ChatKey.from_event(event)
        limit = history_limit(config, decision)
        history = exclude_current_message(
            await self.repo.recent(*key.as_tuple(), limit), event
        )
        caption = caption_service or self.caption_service
        caption_enabled = bool(
            cfg.get(config, "context.image_caption.enabled", False)
        )
        caption_map = await self._caption_history(
            history, caption, config, caption_enabled, event
        )
        history_text = format_history(history, captions=caption_map)
        history_map = {
            index: {"id": message.message_id, "sender_id": message.sender_id}
            for index, message in enumerate(history, start=1)
            if message.message_id
        }
        event.set_extra("ds_history_map", history_map)

        components = [
            component_to_dict(component)
            for component in getattr(getattr(event, "message_obj", None), "message", []) or []
        ]
        current_text = "".join(
            str(component.get("text", ""))
            for component in components
            if component.get("type") == "plain"
        ).strip()
        image_urls = collect_image_urls(components)
        seen_urls = set(image_urls)
        for url in extra_image_urls or []:
            if url and url not in seen_urls:
                image_urls.append(url)
                seen_urls.add(url)

        # 图片消息没有正文时也要给出可读内容，避免模型只看到 "[非文本消息]"
        current_block = current_text or ("[图片]" if image_urls else "")
        segments = []
        if current_block:
            label = "" if event.is_private_chat() else sender_label(event)
            segments = [f"{label}: {current_block}" if label else current_block]
        if (
            image_urls
            and caption is not None
            and caption_enabled
        ):
            captions = await caption.caption(
                image_urls, umo=event.unified_msg_origin
            )
            if captions:
                segments.append(
                    "[图片转述]\n"
                    + "\n".join(f"{url}: {text}" for url, text in captions.items())
                )

        forward_ids = collect_forward_ids(components)
        renderer = forward_renderer or self.forward_renderer
        if (
            forward_ids
            and renderer is not None
            and cfg.get(config, "context.forward.parse", False)
        ):
            rendered = [await renderer.render(forward_id) for forward_id in forward_ids]
            segments.append("[合并转发]\n" + "\n".join(rendered))

        summary = summary_service or self.summary_service
        if (
            summary is not None
            and cfg.get(config, "context.summary.enabled", False)
        ):
            history_text = await summary.summarize(
                history, event.unified_msg_origin, fallback=history_text
            )

        persona = await self.persona_resolver(context, event, config)
        extra_prompt = ""
        if cfg.get(config, "extra_prompt.enabled", False):
            extra_prompt = cfg.get(config, "extra_prompt.text", "")
        wake_hint = ""
        wake_limits_for_hint = None
        wake_consumed = 0
        if wake_session is not None:
            wake_limits_for_hint = wake_session.limits
            wake_consumed = wake_session.consumed_replies
        elif wake_starts:
            wake_limits_for_hint = wake_limits
        if wake_limits_for_hint is not None:
            if (
                wake_limits_for_hint.max_replies > 0
                and wake_consumed + 1 >= wake_limits_for_hint.max_replies
            ):
                wake_hint = cfg.get(
                    config,
                    "wake.final_reply_prompt",
                    cfg.DEFAULTS["wake"]["final_reply_prompt"],
                )
        reply_format = "json" if decision_format == "json" else "plain"
        system_prompt = build_system_prompt(
            persona,
            build_environment(event),
            history_text,
            extra_prompt,
            decision and not proactive_reply,
            decision_format=decision_format,
            wake_hint=wake_hint,
            reply_instruction=(
                build_reply_instruction(reply_format) if proactive_reply else ""
            ),
        )
        request = event.request_llm(
            prompt="\n".join(segments) or "[非文本消息]",
            contexts=[],
            system_prompt=system_prompt,
            image_urls=image_urls,
            tool_set=None,
        )
        request.session_id = event.unified_msg_origin
        event.call_llm = True

        if proactive_reply:
            event.set_extra("ds_request_kind", "proactive_reply")
            event.set_extra("ds_reply_format", reply_format)
            event.set_extra("enable_streaming", False)
        elif decision:
            event.set_extra("ds_request_kind", "decision")
            event.set_extra("ds_decision_format", decision_format)
            event.set_extra("enable_streaming", False)
        else:
            event.set_extra("ds_request_kind", "normal")

        return BuiltRequest(request=request)
