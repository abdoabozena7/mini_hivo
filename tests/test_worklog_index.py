"""Offline unit & controlled functional tests for scripts/update_worklog_index.py."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest

_SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "update_worklog_index.py"
_SPEC = importlib.util.spec_from_file_location("update_worklog_index", _SCRIPT_PATH)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
import sys
sys.modules[_SPEC.name] = _MOD
_SPEC.loader.exec_module(_MOD)


def _write_report(
    root: Path,
    person: str,
    folder: str,
    *,
    title: str = "Sample Dossier",
    date: str = "2026-11-26",
    author: str = "kareem",
    work_type: str = "analysis",
    subsystem: str = "hivo/hybrid",
    status: str = "completed-analysis",
    builds_on: str = "None",
    next_issue: str = "Add unified_diff to dispatch_worker",
    rule_proposal: str = "None",
    tldr: str = "Traced worker edit behavior. Confirmed missing diff handoff.",
) -> Path:
    dossier = root / person / folder
    dossier.mkdir(parents=True, exist_ok=True)
    report = dossier / "REPORT.md"
    report.write_text(
        "\n".join([
            f"# {title}",
            "",
            "## Metadata",
            "",
            f"- **Date:** `{date}`",
            f"- **Author:** `{author}`",
            f"- **Type:** `{work_type}`",
            f"- **Subsystem:** `{subsystem}`",
            "- **Branch & Base Commit:** `feat/test` (base `abc1234`)",
            f"- **Status:** `{status}`",
            f"- **Builds On:** {builds_on}",
            f"- **Next / Open Issue:** {next_issue}",
            f"- **Rule Proposal:** {rule_proposal}",
            "",
            "## TL;DR",
            "",
            tldr,
            "",
        ]),
        encoding="utf-8",
        newline="\n",
    )
    return dossier


class WorklogIndexTests(unittest.TestCase):
    def test_generates_newest_first_index_and_passes_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasneem").mkdir()
            (root / "kareem").mkdir()

            _write_report(
                root,
                "tasneem",
                "2026-11-25_parser-audit",
                title="Parser Audit",
                date="2026-11-25",
                author="tasneem",
                work_type="analysis",
                status="completed-analysis",
                next_issue="Implement fallback parser",
            )
            d2 = _write_report(
                root,
                "kareem",
                "2026-11-26_diff-handoff",
                title="Diff Handoff Experiment",
                date="2026-11-26",
                author="kareem",
                work_type="experiment",
                status="verified",
                builds_on="[Parser Audit](../../tasneem/2026-11-25_parser-audit/REPORT.md)",
                next_issue="None",
                rule_proposal="PROMOTE orchestration_rules.md §6.2 unified_diff -> ENFORCED",
            )
            (d2 / "PROTOCOL.md").write_text("# Protocol\n", encoding="utf-8")
            (d2 / "results.json").write_text("{}\n", encoding="utf-8")
            (d2 / "provenance.json").write_text("{}\n", encoding="utf-8")

            self.assertEqual(_MOD.main(["--worklogs-dir", str(root)]), 0)
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root), "--check"]), 0)

            index_text = (root / "INDEX.md").read_text(encoding="utf-8")
            pos_newer = index_text.index("2026-11-26")
            pos_older = index_text.index("2026-11-25")
            self.assertLess(pos_newer, pos_older)
            self.assertIn("Implement fallback parser", index_text)
            self.assertIn("[protocol](kareem/2026-11-26_diff-handoff/PROTOCOL.md)", index_text)
            self.assertIn("## Pending Rule Proposals (Maintainer Review Queue)", index_text)
            self.assertIn("PROMOTE orchestration_rules.md §6.2 unified_diff -> ENFORCED", index_text)

    def test_check_fails_when_index_is_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_report(root, "kareem", "2026-11-26_initial")
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root), "--check"]), 1)

    def test_rejects_experiment_without_protocol_and_forbidden_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _write_report(root, "ahmed", "2026-11-26_bench", work_type="experiment", status="verified")
            (d / "leak.sqlite3").write_text("x", encoding="utf-8")
            _, _, errors = _MOD.scan_worklogs(root)
            joined = "\n".join(errors)
            self.assertIn("requires sibling PROTOCOL.md", joined)
            self.assertIn("forbidden database file", joined)

    def test_rejects_bad_folder_name_and_host_private_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            d = _write_report(
                root,
                "youssef",
                "BadFolderName",
                tldr=r"Read C:\Users\secret\file.txt during debug.",
            )
            self.assertTrue((d / "REPORT.md").is_file())
            _, _, errors = _MOD.scan_worklogs(root)
            joined = "\n".join(errors)
            self.assertIn("YYYY-MM-DD_<lowercase-slug>", joined)
            self.assertIn("host-private absolute path", joined)

    def test_resolved_rule_proposals_clear_pending_queue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write_report(
                root,
                "kareem",
                "2026-11-26_open-prop",
                title="Open Proposal",
                rule_proposal="ADD orchestration_rules.md §5 compaction anchor guard",
            )
            _write_report(
                root,
                "tasneem",
                "2026-11-25_applied-prop",
                title="Applied Proposal",
                date="2026-11-25",
                author="tasneem",
                rule_proposal="[APPLIED v0.5] PROMOTE tool_rules.md §4",
            )
            _write_report(
                root,
                "ahmed",
                "2026-11-24_rejected-prop",
                title="Rejected Proposal",
                date="2026-11-24",
                author="ahmed",
                rule_proposal="[REJECTED] single-task noise",
            )
            _write_report(
                root,
                "rodina",
                "2026-11-23_deferred-prop",
                title="Deferred Proposal",
                date="2026-11-23",
                author="rodina",
                rule_proposal="`[DEFERRED]` wait for SWE-bench cohort",
            )

            self.assertEqual(_MOD.main(["--worklogs-dir", str(root)]), 0)
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root), "--check"]), 0)

            index_text = (root / "INDEX.md").read_text(encoding="utf-8")
            pending_section = index_text.split("## Pending Rule Proposals")[1].split("## Contributor Folders")[0]
            self.assertIn("ADD orchestration_rules.md §5 compaction anchor guard", pending_section)
            self.assertNotIn("Applied Proposal", pending_section)
            self.assertNotIn("Rejected Proposal", pending_section)
            self.assertNotIn("Deferred Proposal", pending_section)

    def test_indexes_tier1_quick_logs_newest_first(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "kareem").mkdir()
            (root / "ahmed").mkdir()
            (root / "kareem" / "LOG.md").write_text(
                "\n".join([
                    "# Kareem — Tier 1 Quick Change Log",
                    "",
                    "| Date | Area | Tier 1 Change (1 line) | Verification | PR / Commit |",
                    "| :--- | :--- | :--- | :--- | :--- |",
                    "| `2026-11-25` | `hivo/tools` | Handle empty file in search_code | `check.py --tools` | PR #12 |",
                ]) + "\n",
                encoding="utf-8",
            )
            (root / "ahmed" / "LOG.md").write_text(
                "\n".join([
                    "# Ahmed — Tier 1 Quick Change Log",
                    "",
                    "| Date | Area | Tier 1 Change (1 line) | Verification | PR / Commit |",
                    "| :--- | :--- | :--- | :--- | :--- |",
                    "| `2026-11-26` | `hivo/providers` | Clamp negative Retry-After header | `check.py --orchestration` | PR #13 |",
                ]) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root)]), 0)
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root), "--check"]), 0)

            index_text = (root / "INDEX.md").read_text(encoding="utf-8")
            t1_section = index_text.split("## Recent Tier 1 Fixes (Quick Log)")[1].split("## Pending Rule Proposals")[0]
            self.assertIn("Clamp negative Retry-After header", t1_section)
            self.assertIn("Handle empty file in search_code", t1_section)
            self.assertLess(
                t1_section.index("Clamp negative Retry-After header"),
                t1_section.index("Handle empty file in search_code"),
            )
            self.assertIn("[`1`](ahmed/LOG.md)", index_text)

    def test_rejects_bad_tier1_log_date_and_private_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tasneem").mkdir()
            (root / "tasneem" / "LOG.md").write_text(
                "\n".join([
                    "# Tasneem — Tier 1 Quick Change Log",
                    "",
                    "| Date | Area | Tier 1 Change (1 line) | Verification | PR / Commit |",
                    "| :--- | :--- | :--- | :--- | :--- |",
                    r"| `2026/11/26` | `hivo/tools` | Debugged C:\Users\secret\a.py | unit | PR #14 |",
                ]) + "\n",
                encoding="utf-8",
            )
            _, errors = _MOD.scan_tier1_logs(root)
            joined = "\n".join(errors)
            self.assertIn("host-private absolute path", joined)
            self.assertIn("invalid Date (YYYY-MM-DD)", joined)
            self.assertEqual(_MOD.main(["--worklogs-dir", str(root), "--check"]), 1)


if __name__ == "__main__":
    unittest.main()
