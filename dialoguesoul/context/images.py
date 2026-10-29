from __future__ import annotations

import asyncio
from collections import OrderedDict

from ..logutil import warn_once


class CaptionService:
    """图片转述服务：去重、并发受限、带 LRU 缓存。"""

    def __init__(self, captioner, concurrency: int = 3, cache_size: int = 128):
        self.captioner = captioner
        self._sem = asyncio.Semaphore(max(1, concurrency))
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._cache_size = max(0, cache_size)
        self._lock = asyncio.Lock()
        self._inflight: dict[str, asyncio.Lock] = {}

    async def _lock_for(self, url: str) -> asyncio.Lock:
        async with self._lock:
            lock = self._inflight.get(url)
            if lock is None:
                lock = asyncio.Lock()
                self._inflight[url] = lock
            return lock

    async def _cached(self, url: str) -> str | None:
        async with self._lock:
            if url in self._cache:
                self._cache.move_to_end(url)
                return self._cache[url]
        return None

    async def _store(self, url: str, text: str) -> None:
        if self._cache_size <= 0:
            return
        async with self._lock:
            self._cache[url] = text
            self._cache.move_to_end(url)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)

    async def _one(self, umo: str, url: str) -> tuple[str, str]:
        cached = await self._cached(url)
        if cached is not None:
            return url, cached
        lock = await self._lock_for(url)
        try:
            async with lock:
                cached = await self._cached(url)
                if cached is not None:
                    return url, cached
                async with self._sem:
                    text = await self.captioner(umo, url)
                await self._store(url, text)
                return url, text
        finally:
            async with self._lock:
                if self._inflight.get(url) is lock:
                    del self._inflight[url]

    async def caption(self, urls: list[str], umo: str = "") -> dict[str, str]:
        unique = list(dict.fromkeys(url for url in urls if url))
        results = await asyncio.gather(
            *(self._one(umo, url) for url in unique), return_exceptions=True
        )
        output: dict[str, str] = {}
        failed = 0
        for result in results:
            if isinstance(result, Exception):
                failed += 1
                continue
            url, text = result
            output[url] = text
        if failed:
            warn_once(
                "dialoguesoul.caption",
                f"Dialoguesoul: {failed} 张图片转述失败，本次跳过这些图片",
            )
        return output
