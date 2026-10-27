from __future__ import annotations

import asyncio


class ForwardRenderer:
    """把合并转发内容压缩成纯文本。"""

    def __init__(
        self,
        fetcher,
        max_depth: int = 2,
        max_nodes: int = 50,
        max_chars: int = 2000,
        timeout: float = 5,
    ):
        self.fetcher = fetcher
        self.max_depth = max_depth
        self.max_nodes = max_nodes
        self.max_chars = max_chars
        self.timeout = timeout

    def _line(self, item) -> str:
        sender = item.get("sender", {}) if isinstance(item, dict) else {}
        name = sender.get("nickname") or sender.get("card") or "未知"
        content = item.get("content", []) if isinstance(item, dict) else []
        text = "".join(
            str(c.get("text", ""))
            for c in content
            if isinstance(c, dict) and c.get("type") == "text"
        )
        return f"{name}: {text}"

    async def render(self, forward_id: str) -> str:
        try:
            payload = await asyncio.wait_for(self.fetcher(forward_id), self.timeout)
        except Exception:
            return "[合并转发: 获取失败]"
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            messages = []
        lines = [self._line(item) for item in messages[: self.max_nodes]]
        text = "\n".join(lines)
        if len(messages) > self.max_nodes:
            text += f"\n(还有 {len(messages) - self.max_nodes} 条未显示)"
        return text[: self.max_chars]
