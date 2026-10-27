import types
import unittest

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.decision import (
    parse_decision,
    parse_marker,
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


if __name__ == "__main__":
    unittest.main()
