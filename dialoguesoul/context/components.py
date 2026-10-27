from __future__ import annotations


def component_to_dict(component) -> dict:
    data = {"type": str(getattr(component, "type", "unknown") or "unknown")}
    for name in ("text", "url", "file", "id", "qq", "sender_id", "name"):
        value = getattr(component, name, None)
        if value is not None:
            data[name] = value
    chain = getattr(component, "chain", None)
    if chain:
        data["chain"] = [component_to_dict(item) for item in chain]
    return data


def collect_text(components) -> str:
    return "".join(str(c.get("text", "")) for c in components if c.get("type") == "plain")


def collect_image_urls(components) -> list[str]:
    return [str(c.get("url")) for c in components if c.get("type") == "image" and c.get("url")]


def collect_forward_ids(components) -> list[str]:
    return [str(c.get("id")) for c in components if c.get("type") == "forward" and c.get("id")]
