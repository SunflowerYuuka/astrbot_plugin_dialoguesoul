import types
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.decision import (
    build_reply_instruction,
    parse_decision,
    parse_marker,
    parse_reply,
    rewrite_marker_response,
    rewrite_response,
)


class DecisionTest(unittest.TestCase):
    def test_reply(self):
        d = parse_decision('{"action":"reply","messages":["a","b"],"confidence":0.9,"quote":2}', 3, 0.5)
        self.assertEqual((d.action, d.messages, d.quote), ("reply", ["a", "b"], 2))

    def test_ignore(self):
        d = parse_decision('{"action":"ignore","messages":[],"confidence":0.9}', 3, 0.5)
        self.assertEqual(d.action, "ignore")

    def test_low_confidence(self):
        d = parse_decision('{"action":"reply","messages":["a"],"confidence":0.1}', 3, 0.5)
        self.assertEqual(d.action, "ignore")

    def test_bad_json(self):
        self.assertEqual(parse_decision("no", 3, 0.5).action, "ignore")

    def test_rewrite(self):
        resp = types.SimpleNamespace(completion_text="raw")
        rewrite_response(parse_decision('{"action":"reply","messages":["a","b"],"confidence":0.9}', 3, 0.5), resp)
        self.assertEqual(resp.completion_text, "a\nb")
        rewrite_response(parse_decision('{"action":"ignore","messages":[],"confidence":0.9}', 3, 0.5), resp)
        self.assertEqual(resp.completion_text, "")


class MarkerTest(unittest.TestCase):
    def test_marker_reply(self):
        d = parse_marker("  那就去试试看  ")
        self.assertEqual((d.action, d.messages), ("reply", ["那就去试试看"]))

    def test_marker_ignore(self):
        d = parse_marker("<NO_RESPONSE>")
        self.assertEqual(d.action, "ignore")

    def test_marker_empty(self):
        self.assertEqual(parse_marker("   ").action, "ignore")
        self.assertEqual(parse_marker(None).action, "ignore")

    def test_marker_rewrite(self):
        resp = types.SimpleNamespace(completion_text="raw")
        rewrite_marker_response(parse_marker("接一句"), resp)
        self.assertEqual(resp.completion_text, "接一句")
        rewrite_marker_response(parse_marker("<NO_RESPONSE>"), resp)
        self.assertEqual(resp.completion_text, "")


class ReplyTest(unittest.TestCase):
    def test_reply_json_messages_and_quote(self):
        d = parse_reply('{"messages":["a","b"],"quote":2}', 3)
        self.assertEqual((d.action, d.messages, d.quote), ("reply", ["a", "b"], 2))

    def test_reply_json_respects_max_messages(self):
        d = parse_reply('{"messages":["a","b","c"]}', 2)
        self.assertEqual(d.messages, ["a", "b"])

    def test_reply_json_empty_is_ignore(self):
        self.assertEqual(parse_reply('{"messages":[]}', 3).action, "ignore")

    def test_reply_bad_json_is_ignore(self):
        self.assertEqual(parse_reply("no json", 3).action, "ignore")

    def test_reply_json_instruction_keeps_messages_and_quote(self):
        text = build_reply_instruction("json")
        self.assertIn("messages", text)
        self.assertIn("quote", text)
        self.assertNotIn("action", text)
        self.assertNotIn("confidence", text)

    def test_reply_plain_instruction_disables_json(self):
        text = build_reply_instruction("plain")
        self.assertIn("直接输出", text)
        self.assertNotIn("JSON", text)


if __name__ == "__main__":
    unittest.main()
