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

    def _nested(self, item, depth: int) -> list:
        if depth + 1 >= self.max_depth or not isinstance(item, dict):
            return []
        content = item.get("content")
        if not isinstance(content, list):
            return []
        nested: list = []
        for child in content:
            if not isinstance(child, dict):
                continue
            for name in ("nodes", "messages"):
                items = child.get(name)
                if isinstance(items, list):
                    nested.extend(items)
                    break
        return nested

    def _count(self, item, depth: int) -> int:
        total = 1
        for child in self._nested(item, depth):
            total += self._count(child, depth + 1)
        return total

    def _lines(self, messages: list, depth: int, budget: list) -> list[str]:
        lines: list[str] = []
        pad = "  " * depth
        for item in messages:
            if budget[0] <= 0:
                budget[1] += self._count(item, depth)
                continue
            budget[0] -= 1
            lines.append(pad + self._line(item))
            nested = self._nested(item, depth)
            if nested:
                lines.extend(self._lines(nested, depth + 1, budget))
        return lines

    async def render(self, forward_id: str) -> str:
        try:
            payload = await asyncio.wait_for(self.fetcher(forward_id), self.timeout)
        except Exception:
            return "[合并转发: 获取失败]"
        messages = payload.get("messages", []) if isinstance(payload, dict) else []
        if not isinstance(messages, list):
            messages = []
        budget = [self.max_nodes, 0]
        text = "\n".join(self._lines(messages, 0, budget))
        if budget[1] > 0:
            text += f"\n(还有 {budget[1]} 条未显示)"
        return text[: self.max_chars]
