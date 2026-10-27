from __future__ import annotations


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
    try:
        persona = await manager.get_default_persona_v3(
            umo=event.unified_msg_origin
        )
    except Exception:
        return ""
    if not persona:
        return ""
    return str(persona.get("prompt", "") or "")
