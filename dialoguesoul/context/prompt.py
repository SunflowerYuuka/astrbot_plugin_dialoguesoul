from __future__ import annotations

import time

from ..decision import build_decision_instruction, build_marker_instruction
from ..models import ChatMessage

_TEXT_TYPE = "plain"

# 常见非文本组件的中性占位文本，保证历史记录里不出现"[非文本消息]"这种
# 信息量为零的描述。
_PLACEHOLDERS = {
    "face": "[表情]",
    "mface": "[表情]",
    "record": "[语音]",
    "video": "[视频]",
    "forward": "[合并转发]",
    "reply": "[引用]",
    "atall": "[At:全体成员]",
    "rps": "[猜拳]",
    "dice": "[骰子]",
    "shake": "[抖动]",
    "poke": "[戳一戳]",
    "music": "[音乐]",
    "json": "[卡片]",
    "xml": "[卡片]",
}


def _clock(timestamp, now=None) -> str:
    """把时间戳渲染成 HH:MM:SS（跨天时带上日期），失败返回空串。"""
    try:
        ts = float(timestamp)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    local = time.localtime(ts)
    reference = time.localtime(now if now is not None else time.time())
    if (local.tm_year, local.tm_yday) == (reference.tm_year, reference.tm_yday):
        return time.strftime("%H:%M:%S", local)
    return time.strftime("%m-%d %H:%M", local)


def _safe_call(event, name: str) -> str:
    getter = getattr(event, name, None)
    if not callable(getter):
        return ""
    try:
        return str(getter() or "").strip()
    except Exception:
        return ""


def sender_label(event) -> str:
    """当前消息的发送者，格式与聊天记录一致：昵称(QQ号)。"""
    name = _safe_call(event, "get_sender_name")
    sender_id = _safe_call(event, "get_sender_id")
    if name and sender_id:
        return f"{name}({sender_id})"
    return name or sender_id


def render_components(
    components,
    captions: dict | None = None,
    forwards: dict | None = None,
) -> str:
    """把组件列表渲染成一行文本，非文本组件用可读占位符。

    `captions` 为图片地址到转述文本的映射，`forwards` 为转发 id 到已展开
    正文的映射；没有对应内容时退回占位符。
    """
    captions = captions or {}
    forwards = forwards or {}
    parts: list[str] = []
    for component in components or []:
        if not isinstance(component, dict):
            continue
        kind = str(component.get("type") or "").strip().lower()
        if kind == _TEXT_TYPE:
            parts.append(str(component.get("text", "")))
        elif kind == "image":
            caption = ""
            for name in ("url", "file", "path"):
                value = component.get(name)
                if value:
                    caption = str(captions.get(str(value), "") or "").strip()
                    break
            parts.append(f"[图片:{caption}]" if caption else "[图片]")
        elif kind == "at":
            qq = str(component.get("qq", "") or "").strip()
            parts.append(f"[At:{qq}]" if qq else "[At]")
        elif kind == "forward":
            body = str(forwards.get(str(component.get("id") or ""), "") or "").strip()
            parts.append("[合并转发]\n" + body if body else "[合并转发]")
        elif kind == "file":
            name = str(component.get("name", "") or "").strip()
            parts.append(f"[文件:{name}]" if name else "[文件]")
        else:
            parts.append(_PLACEHOLDERS.get(kind, f"[{kind}]" if kind else "[未知消息]"))
    return "".join(parts).strip()


def format_history(
    messages: list[ChatMessage],
    now=None,
    captions: dict | None = None,
    forwards: dict | None = None,
) -> str:
    """渲染聊天记录：编号 + 时间 + 发送者 + 内容。

    时间必须带上，否则模型无法判断两条消息之间隔了几秒还是几分钟，
    容易把早已过去的旧话题当成刚发生的事来接话。
    """
    lines = []
    for index, message in enumerate(messages, start=1):
        text = render_components(message.components, captions, forwards)
        if not text:
            text = "[非文本消息]"
        elif "\n" in text:
            head, *rest = text.split("\n")
            text = head + "".join("\n      " + line for line in rest)
        clock = _clock(message.timestamp, now)
        prefix = f"{index}. {clock} " if clock else f"{index}. "
        name = message.sender_name or message.sender_id
        lines.append(f"{prefix}{name}({message.sender_id}): {text}")
    return "\n".join(lines)


def build_environment(event, now=None) -> str:
    if event.is_private_chat():
        who = f"正在与用户 {event.get_sender_id()} 私聊"
    else:
        who = f"正在群聊 {event.get_group_id()} 中"
    clock = _clock(now if now is not None else time.time())
    timing = f"当前时间 {clock}。" if clock else ""
    return (
        f"你在聊天软件上的 id 是 {event.get_self_id()}，{who}。"
        f"{timing}"
        "聊天记录按时间从早到晚排列，每条带时间；接话时以最后几条为准，"
        "较早的内容只当背景，不要当成刚刚发生的事，也不要把几段旧内容拼成一句话回。"
        "你不是客服，不需要回复所有消息。"
    )


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
