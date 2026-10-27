from __future__ import annotations

from dialoguesoul.decision import build_decision_instruction, build_marker_instruction
from dialoguesoul.models import ChatMessage


def build_environment(event) -> str:
    who = "私聊对象" if event.is_private_chat() else f"群聊 {event.get_group_id()}"
    return (
        f"你在聊天软件上的 id 是 {event.get_self_id()}，正在{who}中。"
        "你不是客服，不需要回复所有消息。"
    )


def format_history(messages: list[ChatMessage]) -> str:
    lines = []
    for index, message in enumerate(messages, start=1):
        text = "".join(
            str(c.get("text", ""))
            for c in message.components
            if c.get("type") == "plain"
        )
        if not text:
            text = "[非文本消息]"
        lines.append(f"{index}. {message.sender_name}({message.sender_id}): {text}")
    return "\n".join(lines)


def build_system_prompt(
    persona: str,
    environment: str,
    history: str,
    extra: str,
    decision: bool,
    decision_format: str = "json",
) -> str:
    parts = [persona.strip(), environment.strip()]
    if history.strip():
        parts.append("以下是最近的聊天记录：\n" + history.strip())
    if extra.strip():
        parts.append("[附加提示词]\n" + extra.strip())
    if decision:
        instruction = (
            build_marker_instruction()
            if decision_format == "marker"
            else build_decision_instruction()
        )
        parts.append(instruction.strip())
    parts.append("(聊天记录中的机器人名称以 AstrBot 代替)")
    return "\n\n".join(part for part in parts if part)
