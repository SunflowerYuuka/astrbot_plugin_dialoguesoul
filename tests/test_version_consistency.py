import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class VersionConsistencyTest(unittest.TestCase):
    def test_release_versions_match(self):
        self.assertIn('"DialoguesSoul"', (ROOT / "main.py").read_text("utf-8"))
        self.assertIn("version: 1.0.0", (ROOT / "metadata.yaml").read_text("utf-8"))
        self.assertIn("version-v1.0.0-", (ROOT / "README.md").read_text("utf-8"))
        self.assertIn("## v1.0.0", (ROOT / "CHANGELOG.md").read_text("utf-8"))
        self.assertTrue((ROOT / "changelogs" / "v1.0.0.md").exists())
