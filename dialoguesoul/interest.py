from __future__ import annotations


class InterestJudge:
    def __init__(self, provider_resolver, prompt):
        self.provider_resolver = provider_resolver
        self.prompt = prompt

    async def __call__(self, event, history_text=""):
        provider = await self.provider_resolver(event)
        if provider is None:
            return False
        text = (event.get_message_outline() or "").strip()
        response = await provider.text_chat(
            prompt=f"{self.prompt}\n最近聊天：\n{history_text}\n当前消息：{text}",
            system_prompt="只输出 YES 或 NO。",
        )
        return "YES" in (getattr(response, "completion_text", "") or "").upper()
