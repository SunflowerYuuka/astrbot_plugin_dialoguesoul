import asyncio
import time
import types
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.plugin import DialoguesSoulPlugin


def _base_config():
    return {
        "enabled": True,
        "enable_all_groups": True,
        "trigger": {
            "strategy": "every_message",
            "probability": 0.0,
            "keywords": [],
            "blacklist_keywords": [],
            "ignored_prefixes": [],
        },
        "decision": {"cooldown_ms": 0, "max_replies_per_minute": 99},
        "context": {
            "history_limit": 5,
            "image_caption": {"enabled": False},
            "forward": {"parse": False},
            "summary": {"enabled": False},
        },
        "persona": {"enabled": False},
        "wake": {"enabled": False},
    }


class FakeRepo:
    def __init__(self, history=None):
        self.history = list(history or [])
        self.appended = []
        self.recent_calls = []

    async def recent(self, *args, **kwargs):
        self.recent_calls.append(args)
        return list(self.history)

    async def append(self, message):
        self.appended.append(message)


class BlockingRepo(FakeRepo):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.calls = 0

    async def recent(self, *args, **kwargs):
        self.recent_calls.append(args)
        self.calls += 1
        if self.calls == 1:
            self.entered.set()
            await self.release.wait()
        return []


class FakeEvent:
    def __init__(self, text="hello", message_id="m1", components=None):
        self.unified_msg_origin = "p:group:1"
        self.message_obj = types.SimpleNamespace(
            message=list(components)
            if components is not None
            else [types.SimpleNamespace(type="plain", text=text)],
            message_id=message_id,
        )
        self.text = text
        self._extra = {}
        self.request = None
        self.call_llm = False

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"

    def get_group_id(self):
        return "1"

    def get_sender_id(self):
        return "u"

    def get_sender_name(self):
        return "U"

    def is_private_chat(self):
        return False

    def get_message_outline(self):
        return self.text

    def set_extra(self, key, value):
        self._extra[key] = value

    def get_extra(self, key, default=None):
        return self._extra.get(key, default)

    def request_llm(self, **kwargs):
        self.request = types.SimpleNamespace(**kwargs)
        self.request.conversation = None
        return self.request


async def _collect(plugin, event):
    return [item async for item in plugin.handle_message(event)]


class PluginFlowTest(unittest.IsolatedAsyncioTestCase):
    def _plugin(self, config=None, repo=None):
        return DialoguesSoulPlugin(
            context=object(),
            config=config or _base_config(),
            repo=repo or FakeRepo(),
        )

    async def test_every_message_produces_decision_request(self):
        plugin = self._plugin()
        event = FakeEvent()

        requests = await _collect(plugin, event)

        self.assertEqual(len(requests), 1)
        self.assertIs(requests[0], event.request)
        self.assertEqual(event.get_extra("ds_request_kind"), "decision")
        self.assertTrue(event.call_llm)

    async def test_rules_without_trigger_produces_no_request(self):
        config = _base_config()
        config["trigger"]["strategy"] = "rules"
        plugin = self._plugin(config=config)
        event = FakeEvent()

        requests = await _collect(plugin, event)

        self.assertEqual(requests, [])
        self.assertIsNone(event.request)
        self.assertIsNone(event.get_extra("ds_request_kind"))

    async def test_non_direct_skips_while_lock_held_and_direct_waits(self):
        repo = BlockingRepo()
        plugin = self._plugin(repo=repo)
        first_event = FakeEvent("first", "m1")
        skipped_event = FakeEvent("second", "m2")
        direct_event = FakeEvent(
            "third",
            "m3",
            components=[
                types.SimpleNamespace(type="plain", text="third"),
                types.SimpleNamespace(type="at", qq="bot"),
            ],
        )

        first_task = asyncio.create_task(_collect(plugin, first_event))
        await asyncio.wait_for(repo.entered.wait(), 1)
        key = ("p", "bot", "group", "1")
        self.assertTrue(plugin._locks[key].locked())

        skipped = await asyncio.wait_for(_collect(plugin, skipped_event), 1)
        self.assertEqual(skipped, [])
        self.assertIsNone(skipped_event.request)

        direct_task = asyncio.create_task(_collect(plugin, direct_event))
        await asyncio.sleep(0.05)
        self.assertIsNone(direct_event.request)

        repo.release.set()
        first_requests, direct_requests = await asyncio.wait_for(
            asyncio.gather(first_task, direct_task), 1
        )

        self.assertEqual(len(first_requests), 1)
        self.assertEqual(first_event.get_extra("ds_request_kind"), "decision")
        self.assertEqual(len(direct_requests), 1)
        self.assertEqual(direct_event.get_extra("ds_request_kind"), "normal")

    async def test_user_message_is_saved_before_routing(self):
        repo = FakeRepo()
        plugin = self._plugin(repo=repo)
        event = FakeEvent("hello", "m9")

        await _collect(plugin, event)

        self.assertEqual(len(repo.appended), 1)
        message = repo.appended[0]
        self.assertEqual(
            (message.platform, message.self_id, message.chat_type, message.chat_id),
            ("p", "bot", "group", "1"),
        )
        self.assertEqual(message.message_id, "m9")
        self.assertEqual((message.sender_id, message.sender_name), ("u", "U"))
        self.assertEqual(message.components, [{"type": "plain", "text": "hello"}])

    async def test_wake_enabled_reserves_first_decision_session(self):
        config = _base_config()
        config["wake"]["enabled"] = True
        plugin = self._plugin(config=config)
        event = FakeEvent()

        requests = await _collect(plugin, event)

        self.assertEqual(len(requests), 1)
        wake_meta = event.get_extra("ds_wake")
        self.assertTrue(wake_meta["starts_session"])
        self.assertTrue(wake_meta["session_id"])
        self.assertIsNotNone(wake_meta["limits"])
        key = ("p", "bot", "group", "1")
        self.assertIsNone(plugin.wake.get(key))
        self.assertTrue(
            plugin.wake.record_delivery(
                key,
                wake_meta["limits"],
                wake_meta["session_id"],
                starts_session=True,
            )
        )
        self.assertEqual(plugin.wake.get(key).session_id, wake_meta["session_id"])

    async def test_prune_idle_removes_unlocked_chat_lock(self):
        plugin = self._plugin()
        await _collect(plugin, FakeEvent())
        key = ("p", "bot", "group", "1")
        self.assertIn(key, plugin._locks)
        self.assertIn(key, plugin._lock_seen)

        removed = plugin.prune_idle(now=time.time() + 4000, ttl=3600)

        self.assertEqual(removed, 1)
        self.assertNotIn(key, plugin._locks)
        self.assertNotIn(key, plugin._lock_seen)


if __name__ == "__main__":
    unittest.main()
