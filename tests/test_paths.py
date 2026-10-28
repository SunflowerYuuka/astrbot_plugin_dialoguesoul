import sys
import tempfile
import types
import unittest
from pathlib import Path

from tests._helpers import install_astrbot_stub

install_astrbot_stub()

from dialoguesoul.storage import paths


class PathsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        module = types.ModuleType("astrbot.core.utils.astrbot_path")
        module.get_astrbot_data_path = lambda: str(self.root / "data")
        sys.modules["astrbot.core.utils.astrbot_path"] = module
        self.addCleanup(sys.modules.pop, "astrbot.core.utils.astrbot_path", None)

    def test_legacy_history_path_is_relative_to_data_dir(self):
        expected = str(self.root / "data" / "chat_history")
        self.assertEqual(paths.legacy_history_path(), expected)

    def test_default_db_path_uses_plugin_data_dir(self):
        expected = str(
            self.root / "data" / "plugin_data" / "dialoguesoul" / "dialoguesoul.sqlite3"
        )
        self.assertEqual(paths.resolve_db_path({}), expected)

    def test_explicit_db_path_wins(self):
        self.assertEqual(
            paths.resolve_db_path({"storage": {"db_path": "custom.db"}}), "custom.db"
        )


if __name__ == "__main__":
    unittest.main()
