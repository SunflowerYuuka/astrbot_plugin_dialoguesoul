from __future__ import annotations

import time

from dialoguesoul.models import ChatKey, ChatMessage

_SCALAR_FIELDS = ("text", "url", "file", "path", "id", "qq", "sender_id", "name")
_RECURSIVE_FIELDS = ("chain", "nodes")
_IMAGE_SOURCE_FIELDS = ("url", "file", "path")


def component_to_dict(component) -> dict:
    if isinstance(component, dict):
        data = dict(component)
        for name in _RECURSIVE_FIELDS:
            items = data.get(name)
            if isinstance(items, (list, tuple)):
                data[name] = [component_to_dict(item) for item in items]
        return data
    data = {"type": str(getattr(component, "type", "unknown") or "unknown")}
    for name in _SCALAR_FIELDS:
        value = getattr(component, name, None)
        if value is not None:
            data[name] = value
    for name in _RECURSIVE_FIELDS:
        items = getattr(component, name, None)
        if items:
            data[name] = [component_to_dict(item) for item in items]
    return data


def _as_dict(component) -> dict:
    return component if isinstance(component, dict) else component_to_dict(component)


def collect_text(components) -> str:
    return "".join(
        str(c.get("text", "")) for c in map(_as_dict, components) if c.get("type") == "plain"
    )


def collect_image_urls(components) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for component in map(_as_dict, components):
        if component.get("type") != "image":
            continue
        for name in _IMAGE_SOURCE_FIELDS:
            value = component.get(name)
            if value:
                candidate = str(value)
                if candidate not in seen:
                    seen.add(candidate)
                    urls.append(candidate)
                break
    return urls


def collect_forward_ids(components) -> list[str]:
    return [
        str(c.get("id"))
        for c in map(_as_dict, components)
        if c.get("type") == "forward" and c.get("id")
    ]


def user_message_from_event(event) -> ChatMessage:
    key = ChatKey.from_event(event)
    return ChatMessage(
        platform=key.platform,
        self_id=key.self_id,
        chat_type=key.chat_type,
        chat_id=key.chat_id,
        message_id=str(getattr(event.message_obj, "message_id", "") or ""),
        sender_id=str(event.get_sender_id()),
        sender_name=str(event.get_sender_name() or ""),
        timestamp=time.time(),
        components=[component_to_dict(c) for c in event.message_obj.message],
    )
