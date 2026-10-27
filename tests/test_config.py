import json
import unittest
from pathlib import Path

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul import config as cfg

ROOT = Path(__file__).resolve().parents[1]


class ConfigTest(unittest.TestCase):
    def test_defaults_are_off(self):
        self.assertFalse(cfg.DEFAULTS["enabled"])
        self.assertFalse(cfg.DEFAULTS["enable_all_groups"])
        self.assertFalse(cfg.DEFAULTS["enabled_private"])

    def test_dot_get(self):
        data = {"a": {"b": 3}}
        self.assertEqual(cfg.get(data, "a.b"), 3)
        self.assertEqual(cfg.get(data, "a.c", 9), 9)

    def test_chat_enabled_respects_blacklist(self):
        class E:
            def is_private_chat(self): return False
            def get_group_id(self): return "1"

        data = {"enable_all_groups": True, "blocked_groups": ["1"]}
        self.assertFalse(cfg.chat_enabled(E(), data))

    def test_revision2_defaults(self):
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.strategy"), "window")
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.window_seconds"), 30)
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.interest.provider_id"), "")
        self.assertFalse(cfg.get(cfg.DEFAULTS, "trigger.burst.enabled"))
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.burst.groups"), [])
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.burst.threshold"), 50)
        self.assertEqual(cfg.get(cfg.DEFAULTS, "trigger.burst.cooldown_seconds"), 30)
        self.assertEqual(cfg.get(cfg.DEFAULTS, "decision.format"), "marker")
        self.assertEqual(cfg.get(cfg.DEFAULTS, "wake.max_replies"), 5)
        self.assertNotIn("max_messages", cfg.DEFAULTS["wake"])
        self.assertFalse(cfg.get(cfg.DEFAULTS, "context.summary.enabled"))
        self.assertEqual(cfg.get(cfg.DEFAULTS, "context.summary.provider_id"), "")
        self.assertEqual(cfg.get(cfg.DEFAULTS, "context.summary.threshold"), 50)

    def test_schema_is_loadable_by_astrbot_parser(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        defaults = _astrbot_schema_to_defaults(schema)
        self.assertIn("wake", defaults)
        self.assertEqual(defaults["wake"]["groups"], [])

    def test_schema_defaults_match_config_defaults(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        defaults = _astrbot_schema_to_defaults(schema)
        # wake.private / wake.admin 是覆盖项，运行时默认留空表示「不覆盖」
        for override in ("private", "admin"):
            defaults["wake"][override] = cfg.DEFAULTS["wake"][override]
        self.assertEqual(defaults, cfg.DEFAULTS)

    def test_schema_wake_overrides_mirror_parent_values(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        wake = schema["wake"]["items"]
        for field in ("duration_seconds", "max_replies", "idle_timeout_seconds"):
            self.assertEqual(wake["private"]["items"][field]["default"], wake[field]["default"])

    def test_schema_enumerates_strategy_and_format(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        trigger = schema["trigger"]["items"]
        decision = schema["decision"]["items"]
        self.assertEqual(
            trigger["strategy"]["options"],
            ["every_message", "rules", "window", "interest"],
        )
        self.assertEqual(trigger["strategy"]["default"], "window")
        self.assertEqual(decision["format"]["options"], ["marker", "json"])
        self.assertEqual(decision["format"]["default"], "marker")
        self.assertEqual(schema["wake"]["items"]["groups"]["type"], "template_list")


DEFAULT_VALUE_MAP = {
    "int": 0, "float": 0.0, "bool": False, "string": "", "text": "",
    "list": [], "file": [], "object": {}, "template_list": [], "dict": {},
}


def _astrbot_schema_to_defaults(schema):
    conf = {}

    def parse(current, target):
        for key, value in current.items():
            if value["type"] not in DEFAULT_VALUE_MAP:
                raise TypeError(value["type"])
            default = value.get("default", DEFAULT_VALUE_MAP[value["type"]])
            if value["type"] == "object":
                target[key] = {}
                parse(value["items"], target[key])
            else:
                target[key] = default

    parse(schema, conf)
    return conf


if __name__ == "__main__":
    unittest.main()
