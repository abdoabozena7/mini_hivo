"""Offline unit tests for scripts/check.py discovery and PR diff gates."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "check.py"
_SPEC = importlib.util.spec_from_file_location("check_runner", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


class CheckRunnerTests(unittest.TestCase):
    def test_locked_rule_path_detection_positive_and_negative(self) -> None:
        self.assertTrue(_MOD.is_locked_rule_path("AGENTS.md"))
        self.assertTrue(_MOD.is_locked_rule_path("CLAUDE.md"))
        self.assertTrue(_MOD.is_locked_rule_path("hivo/tools/AGENTS.md"))
        self.assertTrue(_MOD.is_locked_rule_path(r"dev_rules\tool_rules.md"))
        self.assertTrue(_MOD.is_locked_rule_path("./dev_rules/how_to_make_rules.md"))

        self.assertFalse(_MOD.is_locked_rule_path("docs/TOOLS_ARCHITECTURE.md"))
        self.assertFalse(_MOD.is_locked_rule_path("docs/worklogs/kareem/2026-11-26_x/REPORT.md"))
        self.assertFalse(_MOD.is_locked_rule_path("hivo/tools/fs_read.py"))

    def test_pr_diff_gate_blocks_unauthorized_rule_edits(self) -> None:
        errors = _MOD.evaluate_pr_diff_gates(["hivo/tools/fs_read.py", "tests/test_tools_fs_read.py", "dev_rules/tool_rules.md"])
        self.assertEqual(len(errors), 1)
        self.assertIn("Hard Rule Lock violation", errors[0])
        self.assertIn("dev_rules/tool_rules.md", errors[0])

        self.assertEqual(
            _MOD.evaluate_pr_diff_gates(
                ["dev_rules/tool_rules.md", "hivo/tools/AGENTS.md"],
                allow_rule_edits=True,
            ),
            [],
        )

    def test_pr_diff_gate_blocks_code_without_tests_and_allows_override(self) -> None:
        errors = _MOD.evaluate_pr_diff_gates(["hivo/hybrid/runner.py"])
        self.assertEqual(len(errors), 1)
        self.assertIn("Missing tests for code change", errors[0])
        self.assertIn("hivo/hybrid/runner.py", errors[0])

        # Updating a test satisfies the gate
        self.assertEqual(
            _MOD.evaluate_pr_diff_gates(["hivo/hybrid/runner.py", "tests/test_hybrid_runner.py"]),
            [],
        )
        # Explicit maintainer override satisfies the gate
        self.assertEqual(
            _MOD.evaluate_pr_diff_gates(["scripts/check.py"], allow_no_tests=True),
            [],
        )
        # Docs-only PRs do not require test edits
        self.assertEqual(
            _MOD.evaluate_pr_diff_gates(["docs/TOOLS_ARCHITECTURE.md", "docs/worklogs/INDEX.md"]),
            [],
        )

    def test_discover_v2_test_modules_excludes_live_legacy_tests(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        all_mods = _MOD.discover_v2_test_modules(repo_root)
        self.assertIn("tests.test_tools_fs_read", all_mods)
        self.assertIn("tests.test_providers", all_mods)
        self.assertIn("tests.test_hybrid_runner", all_mods)
        self.assertIn("tests.test_benchmark_stage0", all_mods)
        self.assertIn("tests.test_worklog_index", all_mods)
        self.assertIn("tests.test_check_runner", all_mods)
        self.assertNotIn("tests.test_requirement_clarification", all_mods)

        tools_only = _MOD.discover_v2_test_modules(repo_root, tools=True)
        self.assertTrue(all(m.startswith("tests.test_tools_") for m in tools_only))
        self.assertGreaterEqual(len(tools_only), 8)

        bench_only = _MOD.discover_v2_test_modules(repo_root, benchmarks=True)
        self.assertEqual(bench_only, ["tests.test_benchmark_stage0"])


if __name__ == "__main__":
    unittest.main()
