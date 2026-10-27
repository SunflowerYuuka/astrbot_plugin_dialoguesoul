import asyncio
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.context.forwards import ForwardRenderer
from dialoguesoul.context.images import CaptionService
from dialoguesoul.context.summary import SummaryService


class CaptionServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_caption_dedupes_and_caches(self):
        calls = []

        async def captioner(umo, url):
            calls.append((umo, url))
            return "cat"

        service = CaptionService(captioner=captioner, concurrency=2)
        result = await service.caption(["a", "a", "b"], umo="p:g:1")
        self.assertEqual(result, {"a": "cat", "b": "cat"})
        self.assertEqual(calls, [("p:g:1", "a"), ("p:g:1", "b")])

        again = await service.caption(["a", ""], umo="p:g:1")
        self.assertEqual(again, {"a": "cat"})
        self.assertEqual(len(calls), 2)

    async def test_caption_skips_failures_and_evicts_lru(self):
        async def captioner(umo, url):
            if url == "bad":
                raise RuntimeError("boom")
            return f"seen:{url}"

        service = CaptionService(captioner=captioner, cache_size=1)
        first = await service.caption(["a", "bad"], umo="u")
        self.assertEqual(first, {"a": "seen:a"})

        await service.caption(["b"], umo="u")
        calls = []

        async def counting(umo, url):
            calls.append(url)
            return "again"

        service.captioner = counting
        await service.caption(["a"], umo="u")
        self.assertEqual(calls, ["a"])

    async def test_caption_limits_concurrency(self):
        running = 0
        peak = 0

        async def captioner(umo, url):
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0)
            running -= 1
            return url

        service = CaptionService(captioner=captioner, concurrency=2)
        await service.caption(["a", "b", "c", "d"], umo="u")
        self.assertLessEqual(peak, 2)

    async def test_caption_dedupes_concurrent_same_url(self):
        calls = []

        async def captioner(umo, url):
            calls.append(url)
            await asyncio.sleep(0.05)
            return "cat"

        service = CaptionService(captioner=captioner, concurrency=3)
        first, second = await asyncio.gather(
            service.caption(["a"], umo="u"),
            service.caption(["a"], umo="u"),
        )
        self.assertEqual(first, {"a": "cat"})
        self.assertEqual(second, {"a": "cat"})
        self.assertEqual(calls, ["a"])

    async def test_caption_does_not_cache_failures(self):
        calls = []

        async def captioner(umo, url):
            calls.append(url)
            raise RuntimeError("boom")

        service = CaptionService(captioner=captioner)
        self.assertEqual(await service.caption(["bad"], umo="u"), {})
        self.assertEqual(await service.caption(["bad"], umo="u"), {})
        self.assertEqual(calls, ["bad", "bad"])

    async def test_caption_preserves_input_order(self):
        delays = {"c": 0.03, "a": 0.02, "b": 0.01}

        async def captioner(umo, url):
            await asyncio.sleep(delays[url])
            return url

        service = CaptionService(captioner=captioner, concurrency=3)
        result = await service.caption(["c", "a", "b"], umo="u")
        self.assertEqual(list(result), ["c", "a", "b"])


class ForwardRendererTest(unittest.IsolatedAsyncioTestCase):
    async def test_forward_render(self):
        async def fetcher(forward_id):
            return {
                "messages": [
                    {"sender": {"nickname": "U"}, "content": [{"type": "text", "text": "hi"}]}
                ]
            }

        renderer = ForwardRenderer(fetcher)
        text = await renderer.render("f1")
        self.assertIn("U", text)
        self.assertIn("hi", text)

    async def test_forward_render_handles_errors_and_limits(self):
        async def fetcher(forward_id):
            raise RuntimeError("nope")

        renderer = ForwardRenderer(fetcher)
        self.assertIn("获取失败", await renderer.render("f1"))

        async def slow(forward_id):
            await asyncio.sleep(1)
            return {"messages": []}

        self.assertIn("获取失败", await ForwardRenderer(slow, timeout=0.01).render("f2"))

        async def many(forward_id):
            return {
                "messages": [
                    {"sender": {"card": "C"}, "content": [{"type": "text", "text": str(i)}]}
                    for i in range(6)
                ]
            }

        text = await ForwardRenderer(many, max_nodes=3, max_chars=1000).render("f3")
        self.assertIn("C: 0", text)
        self.assertIn("C: 2", text)
        self.assertNotIn("C: 3", text)
        self.assertIn("还有 3 条", text)

    async def test_forward_render_expands_nested_nodes(self):
        async def fetcher(forward_id):
            return {
                "messages": [
                    {
                        "sender": {"nickname": "A"},
                        "content": [
                            {"type": "text", "text": "outer"},
                            {
                                "type": "forward",
                                "nodes": [
                                    {
                                        "sender": {"nickname": "B"},
                                        "content": [{"type": "text", "text": "inner"}],
                                    },
                                    {
                                        "sender": {"nickname": "C"},
                                        "content": [
                                            {
                                                "type": "forward",
                                                "messages": [
                                                    {
                                                        "sender": {"nickname": "D"},
                                                        "content": [{"type": "text", "text": "deep"}],
                                                    }
                                                ],
                                            }
                                        ],
                                    },
                                ],
                            },
                        ],
                    }
                ]
            }

        text = await ForwardRenderer(fetcher, max_depth=2).render("f1")
        self.assertIn("A: outer", text)
        self.assertIn("B: inner", text)
        self.assertIn("C: ", text)
        self.assertNotIn("D: deep", text)

        deeper = await ForwardRenderer(fetcher, max_depth=3).render("f1")
        self.assertIn("D: deep", deeper)


class SummaryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_summary_below_threshold_returns_fallback(self):
        calls = []

        async def summarizer(umo, fallback):
            calls.append((umo, fallback))
            return "summary"

        service = SummaryService(summarizer=summarizer, threshold=3)
        self.assertEqual(await service.summarize(["m1", "m2"], "u", "fallback"), "fallback")
        self.assertEqual(calls, [])

    async def test_summary_at_threshold_uses_summarizer(self):
        calls = []

        async def summarizer(umo, fallback):
            calls.append((umo, fallback))
            return "summary"

        service = SummaryService(summarizer=summarizer, threshold=3)
        self.assertEqual(await service.summarize(["m1", "m2", "m3"], "u", "fallback"), "summary")
        self.assertEqual(calls, [("u", "fallback")])

    async def test_summary_disabled_returns_fallback(self):
        service = SummaryService(summarizer=None, threshold=1)
        self.assertEqual(await service.summarize(["m1"], "u", "fallback"), "fallback")

    async def test_summary_failure_returns_fallback(self):
        async def summarizer(umo, fallback):
            raise RuntimeError("provider down")

        service = SummaryService(summarizer=summarizer, threshold=1)
        self.assertEqual(await service.summarize(["m1"], "u", "fallback"), "fallback")
