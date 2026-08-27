import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
NUMBERED_GAME = ROOT / "list" / "project-1" / "index.html"
GAME = NUMBERED_GAME if NUMBERED_GAME.exists() else ROOT / "list" / "index.html"


class GameArtifactTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.html = GAME.read_text(encoding="utf-8")

    def test_required_gameplay_and_ui_contracts_exist(self):
        required = (
            "function requestMove", "function checkCollisions", "function startGame",
            "function restartGame", "function endGame", "window.__HOPLINE__",
            "forceCollision", "forceWin", "mobile-pad", "aria-live",
        )
        for marker in required:
            self.assertIn(marker, self.html)

    def test_inline_javascript_has_valid_syntax(self):
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", self.html, flags=re.S | re.I)
        self.assertTrue(scripts)
        result = subprocess.run(
            ["node", "--check", "-"], input=scripts[-1], text=True,
            cwd=ROOT, capture_output=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_placeholder_language_was_removed(self):
        lower = self.html.lower()
        for phrase in ("simple representation for now", "todo", "placeholder"):
            self.assertNotIn(phrase, lower)


if __name__ == "__main__":
    unittest.main()
