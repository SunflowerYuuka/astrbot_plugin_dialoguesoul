import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def test_release_versions_match(self):
        main = (ROOT / "main.py").read_text("utf-8")
        self.assertIn('"DialoguesSoul"', main)
        self.assertIn('"1.2.1"', main)
        self.assertIn("version: 1.2.1", (ROOT / "metadata.yaml").read_text("utf-8"))
        self.assertIn("version-v1.2.1-", (ROOT / "README.md").read_text("utf-8"))
        self.assertIn("## v1.2.1", (ROOT / "CHANGELOG.md").read_text("utf-8"))
        changelog = ROOT / "changelogs" / "v1.2.1.md"
        self.assertTrue(changelog.exists())
        self.assertIn("# v1.2.1", changelog.read_text("utf-8"))
