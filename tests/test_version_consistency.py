import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def test_release_versions_match(self):
        main = (ROOT / "main.py").read_text("utf-8")
        self.assertIn('"DialoguesSoul"', main)
        self.assertIn('"1.1.0"', main)
        self.assertIn("version: 1.1.0", (ROOT / "metadata.yaml").read_text("utf-8"))
        self.assertIn("version-v1.1.0-", (ROOT / "README.md").read_text("utf-8"))
        self.assertIn("## v1.1.0", (ROOT / "CHANGELOG.md").read_text("utf-8"))
        changelog = ROOT / "changelogs" / "v1.1.0.md"
        self.assertTrue(changelog.exists())
        self.assertIn("# v1.1.0", changelog.read_text("utf-8"))
