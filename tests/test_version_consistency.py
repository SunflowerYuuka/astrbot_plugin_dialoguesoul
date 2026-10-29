import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def test_release_versions_match(self):
        main = (ROOT / "main.py").read_text("utf-8")
        metadata = (ROOT / "metadata.yaml").read_text("utf-8")
        # 版本与名称以 metadata.yaml 为准，main.py 不再重复声明
        self.assertIn("class DialoguesSoul(Star)", main)
        self.assertNotIn("1.4.0", main)
        self.assertIn("name: dialoguesoul", metadata)
        self.assertIn("DialoguesSoul", metadata)
        self.assertIn("version: 1.4.0", metadata)
        self.assertIn("version-v1.4.0-", (ROOT / "README.md").read_text("utf-8"))
        self.assertIn("## v1.4.0", (ROOT / "CHANGELOG.md").read_text("utf-8"))
