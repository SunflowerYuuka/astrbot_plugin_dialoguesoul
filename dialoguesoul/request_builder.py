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
)
from .models import ChatKey


def history_limit(config, decision: bool) -> int:
    path = "decision.max_context_messages" if decision else "context.history_limit"
    return int(cfg.get(config, path, 20))


@dataclass
class BuiltRequest:
    request: object
    wake_meta: dict | None


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
    ) -> BuiltRequest:
        key = ChatKey.from_event(event)
        limit = history_limit(config, decision)
        history = exclude_current_message(
            await self.repo.recent(*key.as_tuple(), limit), event
        )
        history_text = format_history(history)
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

        segments = [current_text] if current_text else []
        caption = caption_service or self.caption_service
        if (
            decision
            and image_urls
            and caption is not None
            and cfg.get(config, "context.image_caption.enabled", False)
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
        system_prompt = build_system_prompt(
            persona,
            build_environment(event),
            history_text,
            extra_prompt,
            decision,
            decision_format=decision_format,
            wake_hint=wake_hint,
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

        if decision:
            event.set_extra("ds_request_kind", "decision")
            event.set_extra("ds_decision_format", decision_format)
            event.set_extra("enable_streaming", False)
        else:
            event.set_extra("ds_request_kind", "normal")

        wake_meta = None
        if wake_session is not None:
            wake_meta = {
                "session_id": wake_session.session_id,
                "limits": wake_session.limits,
                "starts_session": False,
            }
        return BuiltRequest(request=request, wake_meta=wake_meta)
