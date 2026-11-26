"""Unit tests for multi-format edit engine (H-12) and anti-tampering oracle lock (H-09)."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hivo.tools import (
    ERR_EDIT_APPLY,
    ERR_ORACLE_LOCKED,
    ToolContext,
    execute_tool,
    line_hash,
)


class TestToolsEditEngine(unittest.TestCase):
    def test_search_replace_crlf_tabs_unicode_duplicates_and_eof(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "tabs_crlf.py"
            original = "def dup():\r\n\treturn 'café'\r\n\r\ndef dup2():\r\n\treturn 'café'\r\n"
            p.write_bytes(original.encode("utf-8"))
            ctx = ToolContext(workspace_root=ws)

            # Ambiguous duplicate rejected cleanly
            r_dup = execute_tool(
                "edit_search_replace",
                {"path": "tabs_crlf.py", "old_string": "\treturn 'café'", "new_string": "\treturn 'tea'"},
                ctx,
            )
            self.assertFalse(r_dup["ok"])
            self.assertEqual(r_dup["error_code"], ERR_EDIT_APPLY)
            self.assertEqual(p.read_bytes(), original.encode("utf-8"))

            # replace_all works and preserves CRLF + tabs + Unicode
            r_all = execute_tool(
                "edit_search_replace",
                {
                    "path": "tabs_crlf.py",
                    "old_string": "\treturn 'café'",
                    "new_string": "\treturn 'thé'",
                    "replace_all": True,
                },
                ctx,
            )
            self.assertTrue(r_all["ok"])
            self.assertEqual(r_all["data"]["replacements"], 2)
            self.assertIn("1:", r_all["data"]["updated_window"])
            self.assertEqual(
                p.read_bytes(),
                "def dup():\r\n\treturn 'thé'\r\n\r\ndef dup2():\r\n\treturn 'thé'\r\n".encode("utf-8"),
            )

            # 0-match indentation mismatch leaves disk untouched and gives hint
            r_miss = execute_tool(
                "edit_search_replace",
                {"path": "tabs_crlf.py", "old_string": "    return 'thé'", "new_string": "x"},
                ctx,
            )
            self.assertFalse(r_miss["ok"])
            self.assertEqual(r_miss["error_code"], ERR_EDIT_APPLY)
            self.assertIn("line(s)", r_miss["error"])

    def test_unified_diff_multi_hunk_empty_file_and_crlf(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "mod.py"
            p.write_bytes(b"def a():\r\n    return 1\r\n\r\ndef b():\r\n    return 2\r\n")
            ctx = ToolContext(workspace_root=ws)

            diff = (
                "--- a/mod.py\n"
                "+++ b/mod.py\n"
                "@@ -1,2 +1,2 @@\n"
                " def a():\n"
                "-    return 1\n"
                "+    return 10\n"
                "@@ -4,2 +4,3 @@\n"
                " def b():\n"
                "-    return 2\n"
                "+    return 20\n"
                "+# end\n"
            )
            r = execute_tool("edit_unified_diff", {"path": "mod.py", "diff": diff}, ctx)
            self.assertTrue(r["ok"])
            self.assertEqual(r["data"]["hunks_applied"], 2)
            self.assertEqual(
                p.read_bytes(),
                b"def a():\r\n    return 10\r\n\r\ndef b():\r\n    return 20\r\n# end\r\n",
            )

            # Empty file population via unified diff defaults to trailing newline
            empty_p = ws / "new.py"
            empty_p.write_text("", encoding="utf-8")
            r_emp = execute_tool(
                "edit_unified_diff",
                {"path": "new.py", "diff": "@@ -0,0 +1,2 @@\n+x = 1\n+y = 2\n"},
                ctx,
            )
            self.assertTrue(r_emp["ok"])
            self.assertEqual(empty_p.read_text(encoding="utf-8"), "x = 1\ny = 2\n")
            self.assertIn("1:", r_emp["data"]["updated_window"])

            # Bad hunk header counts still apply when context matches unambiguously, and monotonic hunk ordering holds
            (ws / "repeat.py").write_text(
                "val = 1\nkeep = 1\nval = 1\nkeep = 2\n",
                encoding="utf-8",
            )
            r_relaxed = execute_tool(
                "edit_unified_diff",
                {
                    "path": "repeat.py",
                    "diff": (
                        "@@ -1,1 +1,1 @@\n"
                        "-val = 1\n"
                        "+val = 10\n"
                        " keep = 1\n"
                        "@@ -3,1 +3,1 @@\n"
                        "-val = 1\n"
                        "+val = 20\n"
                        " keep = 2\n"
                    ),
                },
                ctx,
            )
            self.assertTrue(r_relaxed["ok"])
            self.assertEqual(
                (ws / "repeat.py").read_text(encoding="utf-8"),
                "val = 10\nkeep = 1\nval = 20\nkeep = 2\n",
            )

            # Out-of-order hunk cannot jump backwards to match earlier line
            r_back = execute_tool(
                "edit_unified_diff",
                {
                    "path": "repeat.py",
                    "diff": (
                        "@@ -3,2 +3,2 @@\n"
                        "-val = 20\n"
                        "+val = 200\n"
                        " keep = 2\n"
                        "@@ -1,2 +1,2 @@\n"
                        "-val = 10\n"
                        "+val = 100\n"
                        " keep = 1\n"
                    ),
                },
                ctx,
            )
            self.assertFalse(r_back["ok"])
            self.assertEqual(r_back["error_code"], ERR_EDIT_APPLY)

            # Bad context hunk must fail atomically without mutating disk
            before = p.read_bytes()
            r_bad = execute_tool(
                "edit_unified_diff",
                {"path": "mod.py", "diff": "@@ -1,2 +1,2 @@\n def missing():\n-    return 1\n+    return 9\n"},
                ctx,
            )
            self.assertFalse(r_bad["ok"])
            self.assertEqual(r_bad["error_code"], ERR_EDIT_APPLY)
            self.assertEqual(p.read_bytes(), before)

    def test_line_range_patch_crlf_empty_eof_and_delete(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            empty_p = ws / "empty.py"
            empty_p.write_text("", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            r_init = execute_tool(
                "edit_line_range",
                {"path": "empty.py", "start_line": 0, "end_line": 0, "new_content": "a = 1\nb = 2\nc = 3"},
                ctx,
            )
            self.assertTrue(r_init["ok"])
            self.assertEqual(empty_p.read_text(encoding="utf-8"), "a = 1\nb = 2\nc = 3\n")

            # Edit end-of-file line 3
            r_eof = execute_tool(
                "edit_line_range",
                {"path": "empty.py", "start_line": 3, "end_line": 3, "new_content": "c = 300"},
                ctx,
            )
            self.assertTrue(r_eof["ok"])
            self.assertIn("3:", r_eof["data"]["updated_window"])
            self.assertEqual(empty_p.read_text(encoding="utf-8"), "a = 1\nb = 2\nc = 300\n")

            # Delete line 2
            r_del = execute_tool(
                "edit_line_range",
                {"path": "empty.py", "start_line": 2, "end_line": 2, "delete_lines": True},
                ctx,
            )
            self.assertTrue(r_del["ok"])
            self.assertEqual(empty_p.read_text(encoding="utf-8"), "a = 1\nc = 300\n")

    def test_protected_paths_oracle_lock_blocks_all_mutators(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "tests_eval").mkdir()
            locked_test = ws / "tests_eval" / "test_hidden.py"
            locked_bytes = b"def test_truth():\n    assert 2 + 2 == 4\n"
            locked_test.write_bytes(locked_bytes)
            pyproject = ws / "pyproject.toml"
            pyproject_bytes = b"[tool.ruff]\nselect = ['E', 'F']\n"
            pyproject.write_bytes(pyproject_bytes)

            ctx = ToolContext(
                workspace_root=ws,
                protected_paths=("tests_eval/**", "pyproject.toml"),
            )

            anchor_2 = f"2:{line_hash('    assert 2 + 2 == 4')}"
            attempts = [
                ("edit_file", {"path": "tests_eval/test_hidden.py", "operation": "replace", "start_anchor": anchor_2, "content": "    assert True"}),
                ("edit_search_replace", {"path": "tests_eval/test_hidden.py", "old_string": "assert 2 + 2 == 4", "new_string": "assert True"}),
                ("edit_unified_diff", {"path": "tests_eval/test_hidden.py", "diff": "@@ -1,2 +1,2 @@\n def test_truth():\n-    assert 2 + 2 == 4\n+    assert True\n"}),
                ("edit_line_range", {"path": "tests_eval/test_hidden.py", "start_line": 2, "end_line": 2, "new_content": "    assert True"}),
                ("write_file", {"path": "pyproject.toml", "content": "[tool.ruff]\n", "overwrite": True}),
                ("delete_file", {"path": "pyproject.toml"}),
            ]
            for tool_name, args in attempts:
                res = execute_tool(tool_name, args, ctx)
                self.assertFalse(res["ok"], msg=f"{tool_name} should fail on oracle-locked target")
                self.assertEqual(res["error_code"], ERR_ORACLE_LOCKED, msg=f"Wrong code for {tool_name}")

            self.assertEqual(locked_test.read_bytes(), locked_bytes)
            self.assertEqual(pyproject.read_bytes(), pyproject_bytes)


if __name__ == "__main__":
    unittest.main()
