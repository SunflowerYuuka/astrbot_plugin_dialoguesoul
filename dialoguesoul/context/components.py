from __future__ import annotations

import time

from ..models import ChatKey, ChatMessage

_SCALAR_FIELDS = ("text", "url", "file", "path", "id", "qq", "sender_id", "name")
_RECURSIVE_FIELDS = ("chain", "nodes")
_IMAGE_SOURCE_FIELDS = ("url", "file", "path")


def normalize_component_type(component) -> str:
    """Normalize component type names across AstrBot enums and dict payloads."""
    if isinstance(component, dict):
        raw = component.get("type")
    else:
        raw = getattr(component, "type", None)
    value = getattr(raw, "value", raw)
    if value is None:
        value = type(component).__name__
    name = str(value).strip().lower()
    if not name:
        name = type(component).__name__.lower()
    if name == "text":
        name = "plain"
    return name


def component_to_dict(component) -> dict:
    if isinstance(component, dict):
        data = dict(component)
        data["type"] = normalize_component_type(component)
        for name in _RECURSIVE_FIELDS:
            items = data.get(name)
            if isinstance(items, (list, tuple)):
                data[name] = [component_to_dict(item) for item in items]
        return data
    data = {"type": normalize_component_type(component)}
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
    return component_to_dict(component)


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


def exclude_current_message(messages, event) -> list[ChatMessage]:
    """Drop the triggering message from history because it is already the prompt."""
    current_id = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
    if not current_id:
        return list(messages)
    return [message for message in messages if str(message.message_id) != current_id]


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
