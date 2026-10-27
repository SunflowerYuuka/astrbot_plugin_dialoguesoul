import types
import unittest
from unittest import mock

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.decision import NO_RESPONSE, parse_decision, parse_marker
from dialoguesoul.hooks import Hooks
from dialoguesoul.wake import WakeLimits, WakeManager


class _Event:
    def __init__(self, extras=None, result=None, private=False, group_id="1"):
        self._extra = dict(extras or {})
        self._result = result
        self._private = private
        self._group_id = group_id

    def set_extra(self, key, value):
        self._extra[key] = value

    def get_extra(self, key, default=None):
        return self._extra.get(key, default)

    def get_result(self):
        return self._result

    def clear_result(self):
        self._result = None

    def is_private_chat(self):
        return self._private

    def get_sender_id(self):
        return "u"

    def get_group_id(self):
        return self._group_id

    def get_platform_name(self):
        return "p"

    def get_self_id(self):
        return "bot"


class _Repo:
    def __init__(self):
        self.messages = []
        self.prune_before_calls = []
        self.prune_calls = []

    async def append(self, message):
        self.messages.append(message)

    async def prune_before(self, cutoff):
        self.prune_before_calls.append(cutoff)

    async def prune(self, *key, keep_last):
        self.prune_calls.append((key, keep_last))


class _WakeRecorder:
    def __init__(self):
        self.deliveries = []

    def record_delivery(self, *args, **kwargs):
        self.deliveries.append((args, kwargs))
        return True


class HooksTest(unittest.IsolatedAsyncioTestCase):
    def test_marker_reply_keeps_text_and_records_decision(self):
        hooks = Hooks(repo=None, wake=None, config={})
        event = _Event({"ds_request_kind": "decision"})
        resp = types.SimpleNamespace(completion_text="接一句")
        hooks.on_llm_response(event, resp)
        self.assertEqual(resp.completion_text, "接一句")
        self.assertEqual(event.get_extra("ds_decision").action, "reply")

    def test_marker_ignore_rewrites_to_empty(self):
        hooks = Hooks(repo=None, wake=None, config={})
        event = _Event({"ds_request_kind": "decision"})
        resp = types.SimpleNamespace(completion_text=NO_RESPONSE)
        hooks.on_llm_response(event, resp)
        self.assertEqual(resp.completion_text, "")
        self.assertEqual(event.get_extra("ds_decision").action, "ignore")

    def test_json_response_is_rewritten_and_records_decision(self):
        hooks = Hooks(repo=None, wake=None, config={})
        event = _Event({"ds_request_kind": "decision", "ds_decision_format": "json"})
        resp = types.SimpleNamespace(
            completion_text='{"action":"reply","messages":["hi"],"confidence":0.9,"quote":1}'
        )
        hooks.on_llm_response(event, resp)
        self.assertEqual(resp.completion_text, "hi")
        decision = event.get_extra("ds_decision")
        self.assertEqual((decision.action, decision.messages, decision.quote), ("reply", ["hi"], 1))

    def test_json_ignore_rewrites_to_empty(self):
        hooks = Hooks(repo=None, wake=None, config={})
        event = _Event({"ds_request_kind": "decision", "ds_decision_format": "json"})
        resp = types.SimpleNamespace(
            completion_text='{"action":"ignore","messages":[],"confidence":0.9}'
        )
        hooks.on_llm_response(event, resp)
        self.assertEqual(resp.completion_text, "")

    async def test_marker_reply_leaves_natural_chain_untouched(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[types.SimpleNamespace(text="natural")])
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision": parse_marker("接一句"),
            },
            result=result,
        )
        await hooks.on_decorating_result(event)
        self.assertIs(event.get_result(), result)
        self.assertEqual(result.chain[0].text, "natural")

    async def test_marker_ignore_clears_result(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[{"type": "plain", "text": "natural"}])
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision": parse_marker(NO_RESPONSE),
            },
            result=result,
        )
        await hooks.on_decorating_result(event)
        self.assertIsNone(event.get_result())

    async def test_json_quote_is_applied(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[])
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision_format": "json",
                "ds_decision": parse_decision(
                    '{"action":"reply","messages":["hi"],"confidence":0.9,"quote":1}', 3, 0.5
                ),
                "ds_history_map": {1: {"id": "m1", "sender_id": "u"}},
            },
            result=result,
        )
        await hooks.on_decorating_result(event)
        self.assertEqual(result.chain[0].id, "m1")
        self.assertEqual(result.chain[1].text, "hi")

    async def test_json_reply_without_quote_rebuilds_chain(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[{"type": "plain", "text": "raw"}])
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision_format": "json",
                "ds_decision": parse_decision(
                    '{"action":"reply","messages":["a","b"],"confidence":0.9}', 3, 0.5
                ),
            },
            result=result,
        )
        await hooks.on_decorating_result(event)
        self.assertEqual([component.text for component in result.chain], ["a", "b"])

    async def test_json_ignore_clears_result(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[{"type": "plain", "text": "raw"}])
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision_format": "json",
                "ds_decision": parse_decision(
                    '{"action":"ignore","messages":[],"confidence":0.9}', 3, 0.5
                ),
            },
            result=result,
        )
        await hooks.on_decorating_result(event)
        self.assertIsNone(event.get_result())

    async def test_non_decision_event_is_ignored(self):
        hooks = Hooks(repo=None, wake=None, config={})
        result = types.SimpleNamespace(chain=[{"type": "plain", "text": "natural"}])
        event = _Event({"ds_request_kind": "normal"}, result=result)
        resp = types.SimpleNamespace(completion_text='{"action":"ignore"}')
        hooks.on_llm_response(event, resp)
        self.assertEqual(resp.completion_text, '{"action":"ignore"}')
        self.assertIsNone(event.get_extra("ds_decision"))
        await hooks.on_decorating_result(event)
        self.assertIs(event.get_result(), result)

    async def test_wake_delivery_increments_successful_reply_count(self):
        repo = _Repo()
        wake = WakeManager()
        limits = WakeLimits(300, 2, 120)
        key = ("p", "bot", "group", "1")
        wake.reserve(key, limits, "s1")
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_wake": {"session_id": "s1", "limits": limits, "starts_session": True},
            },
            result=types.SimpleNamespace(chain=[{"type": "plain", "text": "hi"}]),
        )
        await Hooks(repo=repo, wake=wake, config={}).after_message_sent(event)
        self.assertEqual(len(repo.messages), 1)
        self.assertEqual(repo.messages[0].components, [{"type": "plain", "text": "hi"}])
        self.assertEqual(wake.get(key).consumed_replies, 1)

    async def test_ignore_does_not_record_delivery(self):
        repo = _Repo()
        wake = _WakeRecorder()
        limits = WakeLimits(300, 2, 120)
        event = _Event(
            {
                "ds_request_kind": "decision",
                "ds_decision": parse_marker(NO_RESPONSE),
                "ds_wake": {"session_id": "s1", "limits": limits, "starts_session": True},
            },
            result=types.SimpleNamespace(chain=[{"type": "plain", "text": "raw"}]),
        )
        hooks = Hooks(repo=repo, wake=wake, config={})
        await hooks.on_decorating_result(event)
        await hooks.after_message_sent(event)
        self.assertEqual(repo.messages, [])
        self.assertEqual(wake.deliveries, [])

    async def test_command_reply_without_request_kind_is_not_saved(self):
        repo = _Repo()
        wake = _WakeRecorder()
        event = _Event(
            {},
            result=types.SimpleNamespace(chain=[{"type": "plain", "text": "cmd"}]),
        )
        await Hooks(repo=repo, wake=wake, config={}).after_message_sent(event)
        self.assertEqual(repo.messages, [])
        self.assertEqual(wake.deliveries, [])

    async def test_retention_prunes_by_days_and_count(self):
        repo = _Repo()
        event = _Event(
            {"ds_request_kind": "normal"},
            result=types.SimpleNamespace(chain=[{"type": "plain", "text": "hi"}]),
        )
        config = {"storage": {"retention_days": 2, "retention_count": 7}}
        with mock.patch("dialoguesoul.hooks.time.time", return_value=1_000_000.0):
            await Hooks(repo=repo, wake=None, config=config).after_message_sent(event)
        self.assertEqual(repo.messages[0].timestamp, 1_000_000.0)
        self.assertEqual(repo.prune_before_calls, [1_000_000.0 - 2 * 86400])
        self.assertEqual(repo.prune_calls, [(("p", "bot", "group", "1"), 7)])


if __name__ == "__main__":
    unittest.main()
