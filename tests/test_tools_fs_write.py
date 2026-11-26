"""Unit tests for Hashline ``edit_file``, ``write_file``, and ``delete_file``."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from hivo.tools import ToolContext, effective_scratch_dir, execute_tool, line_hash


class TestToolsFsWrite(unittest.TestCase):
    def test_edit_file_replace_insert_delete_and_chained_anchors(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "app.py"
            p.write_text("def add(a, b):\n    return a - b\n\nx = add(1, 2)\n", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            r_read = execute_tool("read_file", {"path": "app.py"}, ctx)
            self.assertTrue(r_read["ok"])
            # Extract line 2 anchor from Hashline output
            a2 = r_read["data"]["content"].splitlines()[1].split("|", 1)[0]

            # Replace line 2
            r_edit1 = execute_tool(
                "edit_file",
                {
                    "path": "app.py",
                    "operation": "replace",
                    "start_anchor": a2,
                    "content": "    return a + b",
                },
                ctx,
            )
            self.assertTrue(r_edit1["ok"])
            self.assertTrue(r_edit1["data"]["syntax_ok"])
            self.assertIn("return a + b", p.read_text(encoding="utf-8"))

            # Use refreshed forgiving anchor ('L2:...| code') from updated_window to insert after line 2
            updated_lines = r_edit1["data"]["updated_window"].splitlines()
            new_a2 = next(ln for ln in updated_lines if ln.startswith("2:"))
            r_edit2 = execute_tool(
                "edit_file",
                {
                    "path": "app.py",
                    "operation": "insert_after",
                    "start_anchor": "L" + new_a2,
                    "content": "# added",
                },
                ctx,
            )
            self.assertTrue(r_edit2["ok"])
            self.assertEqual(
                p.read_text(encoding="utf-8").splitlines(),
                ["def add(a, b):", "    return a + b", "# added", "", "x = add(1, 2)"],
            )

            # Delete lines 3..4
            a3 = f"3:{line_hash('# added')}"
            a4 = f"4:{line_hash('')}"
            r_del = execute_tool(
                "edit_file",
                {"path": "app.py", "operation": "delete", "start_anchor": a3, "end_anchor": a4},
                ctx,
            )
            self.assertTrue(r_del["ok"])
            self.assertEqual(
                p.read_text(encoding="utf-8").splitlines(),
                ["def add(a, b):", "    return a + b", "x = add(1, 2)"],
            )

    def test_edit_file_zero_anchor_on_empty_and_top_of_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "empty.py"
            p.write_text("", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            # 0:00 rejected for replace/delete
            r_bad = execute_tool(
                "edit_file",
                {"path": "empty.py", "operation": "replace", "start_anchor": "0:00", "content": "x = 1"},
                ctx,
            )
            self.assertFalse(r_bad["ok"])

            # 0:00 succeeds for insert_after on empty file
            r_ins = execute_tool(
                "edit_file",
                {"path": "empty.py", "operation": "insert_after", "start_anchor": "0:00", "content": "x = 1"},
                ctx,
            )
            self.assertTrue(r_ins["ok"])
            self.assertEqual(p.read_text(encoding="utf-8"), "x = 1\n")

            # 0:00 inserts at line 1 on non-empty file too
            r_top = execute_tool(
                "edit_file",
                {"path": "empty.py", "operation": "insert_after", "start_anchor": "0:00", "content": "# header"},
                ctx,
            )
            self.assertTrue(r_top["ok"])
            self.assertEqual(p.read_text(encoding="utf-8"), "# header\nx = 1\n")

    def test_edit_file_hash_mismatch_preserves_disk_and_returns_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "mod.py"
            original_bytes = b"a = 1\nb = 2\nc = 3\n"
            p.write_bytes(original_bytes)
            ctx = ToolContext(workspace_root=ws)

            r_stale = execute_tool(
                "edit_file",
                {
                    "path": "mod.py",
                    "operation": "replace",
                    "start_anchor": "2:ff",
                    "content": "b = 999",
                },
                ctx,
            )
            self.assertFalse(r_stale["ok"])
            self.assertEqual(p.read_bytes(), original_bytes)
            self.assertIn("Hash mismatch", r_stale["error"])
            self.assertIn("current_window", r_stale["data"])
            self.assertIn(f"2:{line_hash('b = 2')}| b = 2", r_stale["data"]["current_window"])

    def test_crlf_preservation_syntax_feedback_and_backups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            p = ws / "win.py"
            p.write_bytes(b"x = 1\r\ny = 2\r\nz = 3\r\n")
            ctx = ToolContext(workspace_root=ws, enable_backups=True)

            a2 = f"2:{line_hash('y = 2')}"
            r_edit = execute_tool(
                "edit_file",
                {
                    "path": "win.py",
                    "operation": "replace",
                    "start_anchor": a2,
                    "content": "y = (1 +",  # intentional syntax error
                },
                ctx,
            )
            self.assertTrue(r_edit["ok"])
            self.assertFalse(r_edit["data"]["syntax_ok"])
            self.assertIn("SyntaxError", r_edit["data"]["syntax_error"])
            self.assertIn("post-edit sensor failed", r_edit["hint"])

            # Verify CRLF line endings preserved and no \r\r\n
            raw = p.read_bytes()
            self.assertEqual(raw, b"x = 1\r\ny = (1 +\r\nz = 3\r\n")

            # Verify backup created in external scratch dir and workspace stays clean of .hivo
            self.assertFalse((ws / ".hivo").exists())
            backups = list((effective_scratch_dir(ctx) / "backups").rglob("*.bak"))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_bytes(), b"x = 1\r\ny = 2\r\nz = 3\r\n")

            # Overwrite via write_file preserves CRLF and returns bounded updated_window
            r_wf = execute_tool(
                "write_file",
                {"path": "win.py", "content": "x = 10\ny = 20\n", "overwrite": True},
                ctx,
            )
            self.assertTrue(r_wf["ok"])
            self.assertTrue(r_wf["data"]["syntax_ok"])
            self.assertIn(f"1:{line_hash('x = 10')}| x = 10", r_wf["data"]["updated_window"])
            self.assertEqual(p.read_bytes(), b"x = 10\r\ny = 20\r\n")

            # Writing >40 lines with late syntax error centers updated_window around error line
            lines_55 = [f"v_{i} = {i}" for i in range(1, 56)]
            lines_55[49] = "broken_50 = ("
            r_late = execute_tool(
                "write_file",
                {"path": "late_err.py", "content": "\n".join(lines_55) + "\n"},
                ctx,
            )
            self.assertTrue(r_late["ok"])
            self.assertFalse(r_late["data"]["syntax_ok"])
            win_lines = r_late["data"]["updated_window"].splitlines()
            self.assertLessEqual(len(win_lines), 40)
            self.assertTrue(any(ln.startswith("50:") for ln in win_lines))

    def test_write_file_and_delete_file_safety_cases(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            ctx = ToolContext(workspace_root=ws)

            # Create nested file
            r1 = execute_tool(
                "write_file",
                {"path": "pkg/sub/config.json", "content": '{"ok": true}\n'},
                ctx,
            )
            self.assertTrue(r1["ok"])
            self.assertTrue(r1["data"]["created"])
            self.assertTrue(r1["data"]["syntax_ok"])

            # Refuse overwrite when overwrite=False
            r2 = execute_tool(
                "write_file",
                {"path": "pkg/sub/config.json", "content": "{bad"},
                ctx,
            )
            self.assertFalse(r2["ok"])
            self.assertIn("overwrite=False", r2["error"])

            # Overwrite with broken JSON reports syntax_ok=False
            r3 = execute_tool(
                "write_file",
                {"path": "pkg/sub/config.json", "content": "{bad", "overwrite": True},
                ctx,
            )
            self.assertTrue(r3["ok"])
            self.assertFalse(r3["data"]["syntax_ok"])
            self.assertIn("JSONDecodeError", r3["data"]["syntax_error"])

            # Refuse directory delete
            r_del_dir = execute_tool("delete_file", {"path": "pkg/sub"}, ctx)
            self.assertFalse(r_del_dir["ok"])
            self.assertIn("directory", r_del_dir["error"])

            # Delete single file
            r_del = execute_tool("delete_file", {"path": "pkg/sub/config.json"}, ctx)
            self.assertTrue(r_del["ok"])
            self.assertFalse((ws / "pkg" / "sub" / "config.json").exists())

            # Deleting missing file fails cleanly
            r_del_missing = execute_tool("delete_file", {"path": "pkg/sub/config.json"}, ctx)
            self.assertFalse(r_del_missing["ok"])


if __name__ == "__main__":
    unittest.main()
