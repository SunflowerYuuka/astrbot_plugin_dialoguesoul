from __future__ import annotations

from ..decision import build_decision_instruction, build_marker_instruction
from ..models import ChatMessage


def build_environment(event) -> str:
    if event.is_private_chat():
        who = f"正在与用户 {event.get_sender_id()} 私聊"
    else:
        who = f"正在群聊 {event.get_group_id()} 中"
    return (
        f"你在聊天软件上的 id 是 {event.get_self_id()}，{who}。"
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
    wake_hint: str = "",
    reply_instruction: str = "",
) -> str:
    parts = [persona.strip(), environment.strip()]
    if history.strip():
        parts.append("以下是最近的聊天记录：\n" + history.strip())
    if extra.strip():
        parts.append("[附加提示词]\n" + extra.strip())
    if wake_hint.strip():
        parts.append("[唤醒收尾提示]\n" + wake_hint.strip())
    if reply_instruction.strip():
        parts.append(reply_instruction.strip())
    elif decision:
        instruction = (
            build_marker_instruction()
            if decision_format == "marker"
            else build_decision_instruction()
        )
        parts.append(instruction.strip())
    parts.append("(聊天记录中的机器人名称以 AstrBot 代替)")
    return "\n\n".join(part for part in parts if part)
