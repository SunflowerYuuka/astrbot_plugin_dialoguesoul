from __future__ import annotations

import asyncio


class InterestJudge:
    def __init__(self, provider_resolver, prompt, timeout: float = 15.0):
        self.provider_resolver = provider_resolver
        self.prompt = prompt
        self.timeout = float(timeout or 0)

    async def __call__(self, event, history_text=""):
        try:
            provider = await self.provider_resolver(event)
            if provider is None:
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
        except Exception:
            return False
