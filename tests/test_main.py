import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

from tests._helpers import install_astrbot_stub, load_plugin_main

install_astrbot_stub()

from dialoguesoul.storage.paths import _plugin_data_dir, resolve_db_path


class DbPathTest(unittest.TestCase):
    def test_explicit_path_wins(self):
        config = {"storage": {"db_path": "custom/location.sqlite3"}}
        self.assertEqual(resolve_db_path(config), "custom/location.sqlite3")

    def test_empty_path_uses_plugin_data_dir(self):
        with mock.patch(
            "dialoguesoul.storage.paths._plugin_data_dir",
            return_value=Path("base") / "dialoguesoul",
        ):
            self.assertEqual(
                resolve_db_path({"storage": {"db_path": ""}}),
                str(Path("base") / "dialoguesoul" / "dialoguesoul.sqlite3"),
            )

    def test_import_failure_uses_local_fallback(self):
        with mock.patch.dict(
            sys.modules,
            {
                "astrbot.core.utils": None,
                "astrbot.core.utils.astrbot_path": None,
            },
        ):
            self.assertEqual(
                str(_plugin_data_dir()),
                str(Path("data") / "plugin_data" / "dialoguesoul"),
            )


class MainWiringTest(unittest.IsolatedAsyncioTestCase):
    async def test_constructor_wires_components_and_db_path(self):
        module = load_plugin_main()
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "dialoguesoul.sqlite3")
            plugin = module.DialoguesSoul(
                context=object(),
                config={"storage": {"db_path": db_path}},
            )
            try:
                self.assertEqual(plugin.db.path, db_path)
                self.assertIs(plugin.core.repo, plugin.repo)
                self.assertIs(plugin.commands.repo, plugin.repo)
                self.assertIs(plugin.commands.config, plugin.config)
            finally:
                await plugin.terminate()

    def test_metadata_and_hook_decorators_are_present(self):
        module = load_plugin_main()
        cls = module.DialoguesSoul

        metadata = yaml.safe_load(
            (Path(__file__).resolve().parents[1] / "metadata.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(metadata["name"], "dialoguesoul")
        self.assertEqual(metadata["author"], "SunflowerYuuka")
        self.assertEqual(metadata["version"], "1.3.0")
        # 新版 AstrBot 自动识别 Star 子类，不再需要（已弃用的）@register
        self.assertFalse(hasattr(cls, "__register__"))
        self.assertTrue(hasattr(cls.ds, "__command_group__"))
        for name in ("on_group_message", "on_private_message"):
            self.assertTrue(hasattr(getattr(cls, name), "__event_message_type__"))
        for name in ("on_llm_response", "on_decorating_result", "after_message_sent"):
            self.assertTrue(hasattr(getattr(cls, name), f"__{name}__"))
        for name in ("help", "history", "reset", "mute", "unmute", "status"):
            self.assertTrue(hasattr(getattr(cls, name), "__command__"))
        self.assertEqual(
            cls.on_decorating_result.__on_decorating_result__[1]["priority"], 10000
        )

    def test_destructive_commands_require_admin(self):
        module = load_plugin_main()
        cls = module.DialoguesSoul
        for name in ("history", "reset", "mute", "unmute"):
            marker = getattr(cls, name).__permission_type__
            self.assertEqual(marker[0], (module.filter.PermissionType.ADMIN,))
        self.assertFalse(hasattr(cls.help, "__permission_type__"))
        self.assertFalse(hasattr(cls.status, "__permission_type__"))


if __name__ == "__main__":
    unittest.main()
