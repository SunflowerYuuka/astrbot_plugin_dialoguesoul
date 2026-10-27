import itertools
import types
import unittest

from tests._helpers import _At, install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.gate import Gate
from dialoguesoul.strategy import StrategyEngine
from dialoguesoul.wake import WakeLimits, WakeManager

_ids = itertools.count(1)


class E:
    def __init__(self, text="hi", group="1", components=None, message_id=None):
        self.text = text
        self.group = group
        self.message_obj = types.SimpleNamespace(
            message=components or [],
            message_id=message_id or f"m{next(_ids)}",
        )

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"

    def get_sender_id(self):
        return "u"

    def get_group_id(self):
        return self.group

    def is_private_chat(self):
        return False

    def get_message_outline(self):
        return self.text


def config(strategy, trigger=None, **extra):
    base = {
        "enabled": True,
        "enable_all_groups": True,
        "trigger": {
            "strategy": strategy,
            "window_seconds": 30,
            "probability": 0.0,
            "keywords": ["触发"],
            "blacklist_keywords": [],
            "ignored_prefixes": [],
        },
        "decision": {"cooldown_ms": 0, "max_replies_per_minute": 99},
        "wake": {"enabled": False},
    }
    if trigger is not None:
        base["trigger"] = trigger
    base.update(extra)
    return base


class StrategyTest(unittest.IsolatedAsyncioTestCase):
    async def test_every_message_and_window(self):
        engine = StrategyEngine(Gate(), WakeManager())
        self.assertEqual(
            (await engine.route(E("普通"), config("every_message"))).kind,
            "decision",
        )
        first = await engine.route(E("普通"), config("window"))
        second = await engine.route(E("普通"), config("window"))
        self.assertEqual(first.kind, "decision")
        self.assertEqual(second.kind, "ignore")

    async def test_window_counts_from_last_decision_only(self):
        engine = StrategyEngine(Gate(), WakeManager())
        first = await engine.route(E("普通"), config("window"), now=100)
        second = await engine.route(E("普通"), config("window"), now=110)
        third = await engine.route(E("普通"), config("window"), now=131)
        self.assertEqual(first.kind, "decision")
        self.assertEqual(second.kind, "ignore")
        self.assertEqual(third.kind, "decision")

    async def test_rules_requires_trigger(self):
        engine = StrategyEngine(Gate(), WakeManager())
        self.assertEqual((await engine.route(E("普通"), config("rules"))).kind, "ignore")
        self.assertEqual(
            (await engine.route(E("触发"), config("rules"))).kind, "decision"
        )

    async def test_interest_judge_receives_history(self):
        seen = []

        async def judge(event, history_text=""):
            seen.append(history_text)
            return event.text == "想聊"

        engine = StrategyEngine(Gate(), WakeManager(), interest_judge=judge)
        self.assertEqual(
            (await engine.route(E("不想"), config("interest"), history_text="记录")).kind,
            "ignore",
        )
        self.assertEqual(
            (await engine.route(E("想聊"), config("interest"), history_text="记录")).kind,
            "decision",
        )
        self.assertEqual(seen, ["记录", "记录"])

    async def test_missing_interest_judge_ignores(self):
        engine = StrategyEngine(Gate(), WakeManager())
        self.assertEqual((await engine.route(E("想聊"), config("interest"))).kind, "ignore")

    async def test_interest_disabled_falls_back_to_window(self):
        called = []

        async def judge(event, history_text=""):
            called.append(history_text)
            return False

        engine = StrategyEngine(Gate(), WakeManager(), interest_judge=judge)
        data = config(
            "interest",
            trigger={
                "strategy": "interest",
                "window_seconds": 30,
                "probability": 0.0,
                "keywords": [],
                "blacklist_keywords": [],
                "ignored_prefixes": [],
                "interest": {"enabled": False},
            },
        )
        first = await engine.route(E("普通"), data, now=100)
        second = await engine.route(E("普通"), data, now=110)
        third = await engine.route(E("普通"), data, now=131)
        self.assertEqual(first.kind, "decision")
        self.assertEqual(second.kind, "ignore")
        self.assertEqual(third.kind, "decision")
        self.assertEqual(called, [])

    async def test_burst_only_configured_group(self):
        engine = StrategyEngine(Gate(), WakeManager())
        data = config(
            "every_message",
            trigger={
                "strategy": "every_message",
                "burst": {
                    "enabled": True,
                    "groups": ["1"],
                    "threshold": 2,
                    "cooldown_seconds": 30,
                },
            },
        )
        self.assertEqual((await engine.route(E("a"), data)).kind, "decision")
        self.assertEqual((await engine.route(E("b"), data)).kind, "ignore")
        self.assertEqual((await engine.route(E("c"), data)).kind, "ignore")
        self.assertEqual((await engine.route(E("d", group="2"), data)).kind, "decision")

    async def test_burst_empty_groups_disables_burst(self):
        engine = StrategyEngine(Gate(), WakeManager())
        data = config(
            "every_message",
            trigger={
                "strategy": "every_message",
                "burst": {
                    "enabled": True,
                    "groups": [],
                    "threshold": 1,
                    "cooldown_seconds": 30,
                },
            },
        )
        self.assertEqual((await engine.route(E("a"), data)).kind, "decision")
        self.assertEqual((await engine.route(E("b"), data)).kind, "decision")

    async def test_wake_session_bypasses_strategy(self):
        wake = WakeManager()
        limits = WakeLimits(300, 5, 120)
        key = ("p", "bot", "group", "1")
        wake.reserve(key, limits, "s1", now=0)
        wake.record_delivery(key, limits, "s1", starts_session=True, now=0)
        engine = StrategyEngine(Gate(), wake)

        route = await engine.route(
            E("普通"), config("rules", wake={"enabled": True}), now=1
        )

        self.assertEqual(route.kind, "decision")
        self.assertEqual(route.wake_session.session_id, "s1")

    async def test_direct_address_is_normal(self):
        engine = StrategyEngine(Gate(), WakeManager())
        event = E("hi", components=[_At(qq="bot")])
        self.assertEqual((await engine.route(event, config("rules"))).kind, "normal")

    async def test_prune_removes_idle_state(self):
        engine = StrategyEngine(Gate(), WakeManager())
        await engine.route(E("普通"), config("window"), now=1000)
        key = ("p", "bot", "group", "1")
        self.assertIn(key, engine._last_considered)
        self.assertIn(key, engine.burst._times)

        engine.prune(now=1000 + 3600, ttl=3600)

        self.assertEqual(engine._last_considered, {})
        self.assertEqual(engine.burst._times, {})
        self.assertEqual(engine.burst._burst_until, {})


if __name__ == "__main__":
    unittest.main()
