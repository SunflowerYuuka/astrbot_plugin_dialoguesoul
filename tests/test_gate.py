import types
import unittest

from tests._helpers import _At, install_astrbot_stub

install_astrbot_stub()

from dialoguesoul import config as cfg
from dialoguesoul.gate import Gate
from dialoguesoul.models import ChatKey


class E:
    def __init__(self, text="hi", components=None, private=False, message_id="m1"):
        self.text = text
        self.message_obj = types.SimpleNamespace(message=components or [], message_id=message_id)
        self.private = private

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"

    def get_sender_id(self):
        return "u"

    def get_group_id(self):
        return None if self.private else "1"

    def is_private_chat(self):
        return self.private

    def get_message_outline(self):
        return self.text


def mention(text="hi", message_id="m1"):
    return E(text, [_At(qq="bot")], message_id=message_id)


def config(**overrides):
    base = {
        "enabled": True,
        "enable_all_groups": True,
        "enabled_private": True,
        "trigger": {
            "probability": 0.0,
            "keywords": ["触发"],
            "blacklist_keywords": ["拉黑"],
            "ignored_prefixes": ["/"],
        },
        "decision": {"cooldown_ms": 3000, "max_replies_per_minute": 6},
    }
    base.update(overrides)
    return base


class HardCheckTest(unittest.TestCase):
    def setUp(self):
        self.gate = Gate()

    def test_hard_check_passes_message_without_trigger(self):
        self.assertIsNone(self.gate.hard_check(E("hi"), config()))

    def test_hard_check_skips_ignored_prefix(self):
        result = self.gate.hard_check(E("/help"), config())
        self.assertEqual((result.action, result.reason), ("skip", "command_prefix"))

    def test_hard_check_skips_blacklist(self):
        result = self.gate.hard_check(E("别拉黑我"), config())
        self.assertEqual((result.action, result.reason), ("skip", "blacklist_keyword"))

    def test_hard_check_skips_non_direct_cooldown(self):
        self.gate.record_reply(E("触发"), now=1000.0)
        result = self.gate.hard_check(E("触发", message_id="m2"), config(), now=1001.0)
        self.assertEqual((result.action, result.reason), ("skip", "cooldown"))

    def test_hard_check_skips_non_direct_rate_limit(self):
        for index in range(6):
            self.gate.record_reply(E("触发", message_id=f"r{index}"), now=1000.0 + index)
        result = self.gate.hard_check(E("触发", message_id="m2"), config(), now=1020.0)
        self.assertEqual((result.action, result.reason), ("skip", "rate_limited"))

    def test_hard_check_lets_direct_address_bypass_cooldown(self):
        self.gate.record_reply(E("hi"), now=1000.0)
        self.assertIsNone(self.gate.hard_check(mention(message_id="m2"), config(), now=1001.0))

    def test_hard_check_lets_direct_address_bypass_rate_limit(self):
        for index in range(6):
            self.gate.record_reply(E("hi", message_id=f"r{index}"), now=1000.0 + index)
        self.assertIsNone(self.gate.hard_check(mention(message_id="m2"), config(), now=1020.0))

    def test_hard_check_skips_self(self):
        event = E("触发")
        event.get_sender_id = lambda: "bot"
        self.assertEqual(self.gate.hard_check(event, config()).reason, "self")

    def test_hard_check_skips_disabled_chat(self):
        result = self.gate.hard_check(E("触发"), config(enable_all_groups=False))
        self.assertEqual(result.reason, "chat_disabled")

    def test_hard_check_skips_muted_chat(self):
        data = config()
        data["_temp_mute"] = {"until": 2000.0}
        self.assertEqual(self.gate.hard_check(E("触发"), data, now=1000.0).reason, "muted")

    def test_hard_check_skips_only_muted_chat(self):
        data = config()
        muted_key = ChatKey.from_event(E("触发", message_id="m1"))
        data["_temp_mute"] = {cfg.chat_key_id(muted_key): {"until": 2000.0}}
        self.assertEqual(
            self.gate.hard_check(E("触发", message_id="m1"), data, now=1000.0).reason,
            "muted",
        )
        other = E("触发", message_id="m2")
        other.get_group_id = lambda: "2"
        self.assertIsNone(self.gate.hard_check(other, data, now=1000.0))

    def test_hard_check_skips_empty_without_direct(self):
        result = self.gate.hard_check(E(""), config())
        self.assertEqual((result.action, result.reason), ("skip", "empty"))

    def test_hard_check_passes_empty_text_with_direct_address(self):
        self.assertIsNone(self.gate.hard_check(mention(text=""), config()))

    def test_hard_check_skips_duplicate_message(self):
        self.assertIsNone(self.gate.hard_check(E("触发", message_id="d1"), config(), now=1000.0))
        result = self.gate.hard_check(E("触发", message_id="d1"), config(), now=1001.0)
        self.assertEqual((result.action, result.reason), ("skip", "duplicate"))

    def test_hard_check_seen_key_includes_self_id(self):
        self.assertIsNone(self.gate.hard_check(E("触发", message_id="d1"), config(), now=1000.0))
        other = E("触发", message_id="d1")
        other.get_self_id = lambda: "bot2"
        self.assertIsNone(self.gate.hard_check(other, config(), now=1001.0))


class GateTest(unittest.TestCase):
    def setUp(self):
        self.gate = Gate()

    def test_ignored_prefix(self):
        result = self.gate.check(E("/help"), config())
        self.assertEqual((result.action, result.reason), ("skip", "command_prefix"))

    def test_direct_address_is_priority(self):
        result = self.gate.check(mention(), config())
        self.assertEqual((result.action, result.trigger, result.priority), ("candidate", "mention", 2))

    def test_keyword_candidate(self):
        result = self.gate.check(E("触发"), config())
        self.assertEqual((result.action, result.trigger), ("candidate", "keyword"))

    def test_question_candidate(self):
        result = self.gate.check(E("为什么这样"), config())
        self.assertEqual((result.action, result.trigger), ("candidate", "question"))

    def test_probability_candidate(self):
        data = config()
        data["trigger"]["probability"] = 1.0
        self.assertEqual(self.gate.check(E("随便说说"), data).trigger, "random")

    def test_no_trigger_skips(self):
        result = self.gate.check(E("随便说说"), config())
        self.assertEqual((result.action, result.reason), ("skip", "no_trigger"))

    def test_direct_address_bypasses_cooldown(self):
        event = mention()
        self.gate.record_reply(event)
        self.assertEqual(self.gate.check(mention(message_id="m2"), config()).action, "candidate")

    def test_non_direct_respects_cooldown(self):
        event = E("触发")
        self.gate.record_reply(event)
        self.assertEqual(self.gate.check(E("触发", message_id="m2"), config()).reason, "cooldown")

    def test_blacklist(self):
        self.assertEqual(self.gate.check(E("拉黑"), config()).reason, "blacklist_keyword")

    def test_record_reply_returns_timestamp(self):
        self.assertEqual(self.gate.record_reply(E("触发"), now=1234.5), 1234.5)

    def test_empty_text_skips(self):
        result = self.gate.check(E(""), config())
        self.assertEqual((result.action, result.reason), ("skip", "empty"))

    def test_direct_address_with_empty_text_is_candidate(self):
        result = self.gate.check(mention(text=""), config())
        self.assertEqual((result.action, result.trigger, result.priority), ("candidate", "mention", 2))

    def test_duplicate_message_skips(self):
        self.assertEqual(self.gate.check(E("触发", message_id="d1"), config()).action, "candidate")
        result = self.gate.check(E("触发", message_id="d1"), config())
        self.assertEqual((result.action, result.reason), ("skip", "duplicate"))

    def test_cooldown_skip_does_not_poison_message(self):
        self.gate.record_reply(E("触发"), now=1000.0)
        blocked = self.gate.check(E("触发", message_id="c1"), config(), now=1001.0)
        self.assertEqual(blocked.reason, "cooldown")
        retried = self.gate.check(E("触发", message_id="c1"), config(), now=1100.0)
        self.assertEqual((retried.action, retried.trigger), ("candidate", "keyword"))

    def test_reset_clears_cooldown_and_seen(self):
        self.assertEqual(self.gate.check(E("触发", message_id="r1"), config(), now=1000.0).action, "candidate")
        self.assertEqual(self.gate.check(E("触发", message_id="r1"), config(), now=1000.0).reason, "duplicate")
        self.gate.record_reply(E("触发"), now=1000.0)
        self.assertEqual(self.gate.check(E("触发", message_id="r2"), config(), now=1001.0).reason, "cooldown")
        self.gate.reset()
        self.assertEqual(self.gate.check(E("触发", message_id="r1"), config(), now=1001.0).action, "candidate")

    def test_record_reply_prunes_stale_times(self):
        self.gate.record_reply(E("触发"), now=1000.0)
        self.gate.record_reply(E("触发"), now=1200.0)
        key = ChatKey.from_event(E("触发")).as_tuple()
        self.assertEqual(self.gate._reply_times[key], [1200.0])


if __name__ == "__main__":
    unittest.main()
