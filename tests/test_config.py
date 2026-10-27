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

        data = {"enabled": True, "enable_all_groups": True, "blocked_groups": ["1"]}
        self.assertFalse(cfg.chat_enabled(E(), data))

    def test_master_switch_disables_group_and_private(self):
        class E:
            def __init__(self, private=False):
                self.private = private

            def is_private_chat(self):
                return self.private

            def get_group_id(self):
                return "1"

        group = {"enabled": False, "enable_all_groups": True, "enabled_private": True}
        private = {"enabled": False, "enable_all_groups": True, "enabled_private": True}
        self.assertFalse(cfg.chat_enabled(E(), group))
        self.assertFalse(cfg.chat_enabled(E(private=True), private))
        self.assertTrue(
            cfg.chat_enabled(E(), {"enabled": True, "enable_all_groups": True})
        )

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
        self.assertEqual(cfg.get(cfg.DEFAULTS, "context.summary.threshold"), 20)

    def test_schema_is_loadable_by_astrbot_parser(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        defaults = _astrbot_schema_to_defaults(schema)
        self.assertIn("wake", defaults)
        self.assertEqual(defaults["wake"]["groups"], [])

    def test_schema_defaults_match_config_defaults(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        defaults = _astrbot_schema_to_defaults(schema)
        self.assertEqual(defaults, cfg.DEFAULTS)

    def test_wake_scope_defaults_are_explicit(self):
        wake = cfg.DEFAULTS["wake"]
        self.assertEqual(
            wake["private"],
            {"duration_seconds": 300, "max_replies": 5, "idle_timeout_seconds": 120},
        )
        self.assertEqual(
            wake["admin"],
            {"duration_seconds": 0, "max_replies": 0, "idle_timeout_seconds": 0},
        )

    def test_schema_and_defaults_agree_on_wake_scopes(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        wake_schema = schema["wake"]["items"]
        for scope in ("private", "admin"):
            fields = wake_schema[scope]["items"]
            mirrored = {
                field: fields[field]["default"]
                for field in ("duration_seconds", "max_replies", "idle_timeout_seconds")
            }
            self.assertEqual(mirrored, cfg.DEFAULTS["wake"][scope])

    def test_schema_wake_overrides_mirror_parent_values(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        wake = schema["wake"]["items"]
        for field in ("duration_seconds", "max_replies", "idle_timeout_seconds"):
            self.assertEqual(wake["private"]["items"][field]["default"], wake[field]["default"])

    def test_admin_zero_means_unlimited_wording(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        wake = schema["wake"]["items"]
        for field in ("duration_seconds", "max_replies", "idle_timeout_seconds"):
            self.assertIn("0 表示不限", wake[field]["hint"])
            self.assertIn("0 表示不限", wake["admin"]["items"][field]["hint"])
        self.assertNotIn("沿用默认", json.dumps(schema, ensure_ascii=False))

    def test_provider_fields_use_select_provider(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        self.assertEqual(
            schema["trigger"]["items"]["interest"]["items"]["provider_id"]["_special"],
            "select_provider",
        )
        self.assertEqual(
            schema["context"]["items"]["summary"]["items"]["provider_id"]["_special"],
            "select_provider",
        )
        self.assertEqual(
            schema["context"]["items"]["image_caption"]["items"]["provider_id"]["_special"],
            "select_provider",
        )

    def test_decision_timeout_is_not_exposed(self):
        schema = json.loads((ROOT / "_conf_schema.json").read_text("utf-8"))
        self.assertNotIn("timeout_ms", schema["decision"]["items"])
        self.assertNotIn("timeout_ms", cfg.DEFAULTS["decision"])

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
        burst_groups = trigger["burst"]["items"]["groups"]
        self.assertEqual(burst_groups["default"], [])
        self.assertNotIn("所有群", burst_groups["hint"])
        self.assertIn("留空", burst_groups["hint"])


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
