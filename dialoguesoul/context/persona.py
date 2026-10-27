from __future__ import annotations

import inspect


async def _awaited(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def resolve_persona_prompt(context, event, config) -> str:
    persona_config = {}
    if hasattr(config, "get"):
        candidate = config.get("persona")
        if isinstance(candidate, dict):
            persona_config = candidate
    if not persona_config.get("enabled", True):
        return ""
    manager = getattr(context, "persona_manager", None)
    if manager is None:
        return ""

    persona = None
    name = str(persona_config.get("name", "") or "").strip()
    if name:
        getter = getattr(manager, "get_persona_v3_by_id", None)
        if callable(getter):
            try:
                persona = await _awaited(getter(name))
            except Exception:
                persona = None

    if not persona:
        try:
            persona = await _awaited(
                manager.get_default_persona_v3(umo=event.unified_msg_origin)
            )
        except Exception:
            return ""
    if not persona:
        return ""
    return str(persona.get("prompt", "") or "")
