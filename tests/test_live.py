import asyncio
import types
import unittest
from unittest import mock

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.context.live import (
    build_caption_service,
    build_interest_judge,
    build_intervention_judge,
    build_summary_service,
)


class Provider:
    def __init__(self, text="OK"):
        self.text = text
        self.calls = []

    async def text_chat(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(completion_text=self.text)


class FailingProvider:
    async def text_chat(self, **kwargs):
        raise RuntimeError("provider down")


class SlowProvider:
    async def text_chat(self, **kwargs):
        await asyncio.sleep(5)
        return types.SimpleNamespace(completion_text="YES")


class Context:
    def __init__(self, current=None, by_id=None):
        self.current = current
        self.by_id = by_id
        self.current_umos = []
        self.by_id_ids = []

    def get_provider_by_id(self, provider_id):
        self.by_id_ids.append(provider_id)
        return self.by_id

    def get_using_provider(self, umo):
        self.current_umos.append(umo)
        return self.current


class LiveServiceTest(unittest.IsolatedAsyncioTestCase):
    async def test_caption_uses_configured_provider(self):
        provider = Provider(" 猫 ")
        context = Context(by_id=provider)
        config = {
            "context": {
                "image_caption": {
                    "enabled": True,
                    "provider_id": "vision",
                    "prompt": "描述图片",
                    "concurrency": 1,
                    "cache_size": 4,
                }
            }
        }

        service = build_caption_service(context, config)
        result = await service.caption(["http://img"], umo="umo")

        self.assertEqual(result, {"http://img": "猫"})
        self.assertEqual(context.by_id_ids, ["vision"])
        self.assertEqual(context.current_umos, [])
        self.assertEqual(provider.calls[0]["prompt"], "描述图片")
        self.assertEqual(provider.calls[0]["image_urls"], ["http://img"])

    async def test_caption_disabled_returns_none(self):
        self.assertIsNone(
            build_caption_service(Context(), {"context": {"image_caption": {"enabled": False}}})
        )

    async def test_summary_uses_current_provider_and_threshold_boundary(self):
        provider = Provider("摘要")
        context = Context(current=provider)
        config = {
            "context": {
                "summary": {"enabled": True, "provider_id": "", "threshold": 20}
            }
        }
        service = build_summary_service(context, config)

        self.assertEqual(
            await service.summarize([object()] * 19, "umo", "原文"),
            "原文",
        )
        self.assertEqual(provider.calls, [])

        result = await service.summarize([object()] * 20, "umo", "原文")

        self.assertEqual(result, "摘要")
        self.assertEqual(context.current_umos, ["umo"])
        self.assertIn("原文", provider.calls[0]["prompt"])
        self.assertEqual(provider.calls[0]["system_prompt"], "只输出摘要正文。")

    async def test_summary_disabled_returns_none(self):
        self.assertIsNone(
            build_summary_service(Context(), {"context": {"summary": {"enabled": False}}})
        )

    async def test_interest_judge_uses_provider_and_history(self):
        provider = Provider("YES")
        context = Context(by_id=provider)
        config = {
            "trigger": {
                "strategy": "interest",
                "interest": {"provider_id": "judge"},
            }
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )

        judge = build_interest_judge(context, config)

        self.assertTrue(await judge(event, "最近聊天"))
        self.assertEqual(context.by_id_ids, ["judge"])
        self.assertIn("最近聊天", provider.calls[0]["prompt"])
        self.assertIn("当前消息", provider.calls[0]["prompt"])
        self.assertEqual(provider.calls[0]["system_prompt"], "只输出 YES 或 NO。")

    async def test_interest_judge_disabled_for_other_strategies(self):
        config = {"trigger": {"strategy": "window", "interest": {"provider_id": ""}}}
        self.assertIsNone(build_interest_judge(Context(), config))

    async def test_interest_judge_disabled_by_switch(self):
        config = {
            "trigger": {
                "strategy": "interest",
                "interest": {"enabled": False, "provider_id": "judge"},
            }
        }
        self.assertIsNone(build_interest_judge(Context(by_id=Provider("YES")), config))

    async def test_interest_judge_provider_errors_degrade_to_false(self):
        context = Context(by_id=FailingProvider())
        config = {
            "trigger": {
                "strategy": "interest",
                "interest": {"provider_id": "judge"},
            }
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )
        judge = build_interest_judge(context, config)
        self.assertFalse(await judge(event, "最近聊天"))

    async def test_intervention_judge_uses_extra_prompt_and_provider(self):
        provider = Provider("YES")
        context = Context(by_id=provider)
        config = {
            "extra_prompt": {
                "enabled": True,
                "text": "只回复技术问题",
                "provider_id": "judge",
            }
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )

        judge = build_intervention_judge(context, config)

        self.assertTrue(await judge(event, "最近聊天"))
        self.assertEqual(context.by_id_ids, ["judge"])
        prompt = provider.calls[0]["prompt"]
        self.assertIn("只回复技术问题", prompt)
        self.assertIn("最近聊天", prompt)
        self.assertIn("当前消息", prompt)
        self.assertIn("只输出 YES 或 NO", prompt)
        self.assertEqual(provider.calls[0]["system_prompt"], "只输出 YES 或 NO。")

    async def test_intervention_judge_disabled_without_extra_prompt(self):
        self.assertIsNone(
            build_intervention_judge(
                Context(), {"extra_prompt": {"enabled": False, "text": "忽略"}}
            )
        )

    async def test_intervention_judge_uses_default_criteria_when_text_empty(self):
        provider = Provider("NO")
        context = Context(current=provider)
        config = {
            "extra_prompt": {"enabled": True, "text": "", "provider_id": ""}
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )

        judge = build_intervention_judge(context, config)

        self.assertFalse(await judge(event, "最近聊天"))
        self.assertIn("判断当前聊天是否值得你介入", provider.calls[0]["prompt"])

    async def test_intervention_judge_provider_errors_degrade_to_false(self):
        context = Context(by_id=FailingProvider())
        config = {
            "extra_prompt": {
                "enabled": True,
                "text": "只回复技术问题",
                "provider_id": "judge",
            }
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )

        judge = build_intervention_judge(context, config)

        self.assertFalse(await judge(event, "最近聊天"))

    async def test_intervention_judge_times_out_and_degrades(self):
        context = Context(current=SlowProvider())
        config = {
            "decision": {"aux_timeout_seconds": 0.01},
            "extra_prompt": {"enabled": True, "text": "只回复技术问题"},
        }
        event = types.SimpleNamespace(
            unified_msg_origin="umo",
            get_message_outline=lambda: "当前消息",
        )

        judge = build_intervention_judge(context, config)

        self.assertFalse(await judge(event, "最近聊天"))

    async def test_caption_provider_errors_are_skipped(self):
        context = Context(by_id=FailingProvider())
        config = {
            "context": {
                "image_caption": {
                    "enabled": True,
                    "provider_id": "vision",
                    "prompt": "描述图片",
                    "concurrency": 1,
                    "cache_size": 4,
                }
            }
        }
        service = build_caption_service(context, config)
        with mock.patch("dialoguesoul.context.images.warn_once") as warn:
            self.assertEqual(await service.caption(["http://img"], umo="umo"), {})
        warn.assert_called_once()
        self.assertEqual(warn.call_args[0][0], "dialoguesoul.caption")

    async def test_async_provider_lookup_is_preferred(self):
        class AsyncContext:
            def __init__(self):
                self.used = []

            async def get_using_provider_async(self, umo):
                self.used.append("async")
                return Provider("摘要")

            def get_using_provider(self, umo):
                self.used.append("sync")
                return Provider("旧")

        context = AsyncContext()
        service = build_summary_service(
            context,
            {"context": {"summary": {"enabled": True, "provider_id": "", "threshold": 2}}},
        )
        messages = [
            types.SimpleNamespace(components=[{"type": "plain", "text": "x"}]),
            types.SimpleNamespace(components=[{"type": "plain", "text": "y"}]),
        ]

        self.assertEqual(await service.summarize(messages, "umo", "fallback"), "摘要")
        self.assertEqual(context.used, ["async"])


if __name__ == "__main__":
    unittest.main()
