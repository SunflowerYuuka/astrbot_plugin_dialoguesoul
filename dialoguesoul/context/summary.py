from __future__ import annotations


class SummaryService:
    """可选摘要：仅在消息量达到阈值时交给注入的摘要器。"""

    def __init__(self, summarizer, threshold: int = 20):
        self.summarizer = summarizer
        self.threshold = threshold

    async def summarize(self, messages, umo: str, fallback: str) -> str:
        if self.summarizer is None or len(messages) < self.threshold:
            return fallback
        return await self.summarizer(umo, fallback)
