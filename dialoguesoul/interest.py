from __future__ import annotations

import asyncio

from .logutil import warn_once


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

    async def __call__(self, event, history_text=""):
        try:
            provider = await self.provider_resolver(event)
            if provider is None:
                warn_once(
                    f"dialoguesoul.{self.name}.provider",
                    f"Dialoguesoul: 未找到可用的{self.name}模型，本次按不介入处理",
                )
                return False
            text = (event.get_message_outline() or "").strip()
            call = provider.text_chat(
                prompt=f"{self.prompt}\n最近聊天：\n{history_text}\n当前消息：{text}",
                system_prompt="只输出 YES 或 NO。",
            )
            if self.timeout > 0:
                response = await asyncio.wait_for(call, timeout=self.timeout)
            else:
                response = await call
            return "YES" in (getattr(response, "completion_text", "") or "").upper()
        except Exception as exc:
            warn_once(
                f"dialoguesoul.{self.name}",
                f"Dialoguesoul: {self.name}调用失败"
                f"（{type(exc).__name__}: {exc}），本次按不介入处理",
            )
            return False
