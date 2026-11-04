from __future__ import annotations

import asyncio

from .logutil import warn_once


def _seconds(value: float) -> str:
    """把秒数格式化成 45 这样的短文本，用于日志文案。"""
    return f"{float(value):g}"


def _attr(event, name: str) -> str:
    """安全读取 event 上的取字符串方法，缺字段时返回空串。"""
    getter = getattr(event, name, None)
    if not callable(getter):
        return ""
    try:
        return str(getter() or "").strip()
    except Exception:
        return ""


def _sender_label(event) -> str:
    """当前消息的发送者，格式与聊天记录一致：昵称(QQ号)。"""
    name = _attr(event, "get_sender_name")
    sender_id = _attr(event, "get_sender_id")
    if name and sender_id:
        return f"{name}({sender_id})"
    return name or sender_id


def _identity_line(event) -> str:
    """告诉判断模型机器人自己的 id，否则 [At:数字] 无从对照。"""
    self_id = _attr(event, "get_self_id")
    if not self_id:
        return ""
    return (
        f"你在聊天软件上的 id 是 {self_id}；消息里的 [At:数字] 表示艾特了该 QQ，"
        f"[At:{self_id}] 才是直接艾特你。"
    )


def build_judge_prompt(prompt: str, event, history_text: str = "") -> str:
    """组装判断提示词：带上当前消息的发送者与机器人自身 id。

    判断规则里写「先辨认发送者 / 引用对象 / 艾特对象」时，模型必须能看到
    这些信息才能执行；只给正文会让规则变成空话。
    """
    text = (event.get_message_outline() or "").strip()
    sender = _sender_label(event)
    current = f"{sender}: {text}" if sender else text
    parts = [prompt]
    identity = _identity_line(event)
    if identity:
        parts.append(identity)
    parts.append("最近聊天：\n" + history_text + "\n当前消息：" + current)
    return "\n".join(parts)


class InterestJudge:
    def __init__(
        self,
        provider_resolver,
        prompt,
        timeout: float = 15.0,
        name: str = "辅助判断",
    ):
        self.provider_resolver = provider_resolver
        self.prompt = prompt
        self.timeout = float(timeout or 0)
        self.name = name

    def build_prompt(self, event, history_text: str = "") -> str:
        return build_judge_prompt(self.prompt, event, history_text)

    async def __call__(self, event, history_text=""):
        try:
            provider = await self.provider_resolver(event)
            if provider is None:
                warn_once(
                    f"dialoguesoul.{self.name}.provider",
                    f"Dialoguesoul: 未找到可用的{self.name}模型，本次按不介入处理",
                )
                return False
            call = provider.text_chat(
                prompt=self.build_prompt(event, history_text),
                system_prompt="只输出 YES 或 NO。",
            )
            if self.timeout > 0:
                response = await asyncio.wait_for(call, timeout=self.timeout)
            else:
                response = await call
            return "YES" in (getattr(response, "completion_text", "") or "").upper()
        except asyncio.TimeoutError:
            warn_once(
                f"dialoguesoul.{self.name}.timeout",
                f"Dialoguesoul: {self.name}超时（{_seconds(self.timeout)} 秒内"
                "未返回结果），本次按不介入处理；"
                "可调大 decision.aux_timeout_seconds 或改用更快的判断模型",
            )
            return False
        except Exception as exc:
            detail = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
            warn_once(
                f"dialoguesoul.{self.name}",
                f"Dialoguesoul: {self.name}调用失败（{detail}），本次按不介入处理",
            )
            return False
