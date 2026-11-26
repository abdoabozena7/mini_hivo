"""Unit tests for ``read_file``, ``list_files``, and ``search_code``."""

from __future__ import annotations

from pathlib import Path
import re
import tempfile
import unittest

from hivo.tools import ToolContext, execute_tool, line_hash
from hivo.tools.fs_read import _search_python


class TestToolsFsRead(unittest.TestCase):
    def test_read_file_hashlines_ranges_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            lines = [f"line_{i} = {i * 2}" for i in range(1, 21)]
            (ws / "sample.py").write_text("\n".join(lines) + "\n", encoding="utf-8")

            ctx = ToolContext(workspace_root=ws, max_read_lines=5, max_output_chars=16_000)

            # Bounded read with Hashlines
            r1 = execute_tool("read_file", {"path": "sample.py", "start_line": 3, "end_line": 5}, ctx)
            self.assertTrue(r1["ok"])
            self.assertFalse(r1["truncated"])
            self.assertEqual(r1["data"]["start_line"], 3)
            self.assertEqual(r1["data"]["end_line"], 5)
            self.assertEqual(r1["data"]["total_lines"], 20)
            out_lines = r1["data"]["content"].splitlines()
            self.assertEqual(len(out_lines), 3)
            self.assertEqual(out_lines[0], f"3:{line_hash('line_3 = 6')}| line_3 = 6")

            # Exceeding max_read_lines forces truncation + pagination hint
            r2 = execute_tool("read_file", {"path": "sample.py", "start_line": 1, "end_line": 20}, ctx)
            self.assertTrue(r2["ok"])
            self.assertTrue(r2["truncated"])
            self.assertEqual(r2["data"]["end_line"], 5)
            self.assertIn("start_line=6", r2["hint"])

            # Single huge line capped by max_output_chars
            (ws / "huge.txt").write_text("X" * 500 + "\n", encoding="utf-8")
            tight_ctx = ToolContext(workspace_root=ws, max_output_chars=80)
            r3 = execute_tool("read_file", {"path": "huge.txt"}, tight_ctx)
            self.assertTrue(r3["ok"])
            self.assertTrue(r3["truncated"])
            self.assertLessEqual(len(r3["data"]["content"]), 80)

    def test_read_file_edge_cases_and_fence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "empty.py").write_text("", encoding="utf-8")
            (ws / "sub").mkdir()
            (ws / "sub" / "other.py").write_text("x = 1\n", encoding="utf-8")
            (ws / "binary.bin").write_bytes(b"\x00\x01\x02\xff\xfe")
            (ws / "latin.txt").write_bytes(b"\xff\xfe\xfd")

            ctx = ToolContext(workspace_root=ws)

            # Empty 0-line file succeeds cleanly (fixes mini.py read_file_range bug)
            r_empty = execute_tool("read_file", {"path": "empty.py"}, ctx)
            self.assertTrue(r_empty["ok"])
            self.assertEqual(r_empty["data"]["total_lines"], 0)
            self.assertIn("0:00", r_empty["hint"])

            # Missing file
            r_missing = execute_tool("read_file", {"path": "nope.py"}, ctx)
            self.assertFalse(r_missing["ok"])
            self.assertTrue(r_missing["hint"])

            # Directory target
            r_dir = execute_tool("read_file", {"path": "sub"}, ctx)
            self.assertFalse(r_dir["ok"])
            self.assertIn("list_files", r_dir["hint"])

            # Binary and non-UTF8 files never raise UnicodeDecodeError
            r_bin = execute_tool("read_file", {"path": "binary.bin"}, ctx)
            self.assertFalse(r_bin["ok"])
            self.assertIn("binary", r_bin["error"].lower())

            r_bad_utf8 = execute_tool("read_file", {"path": "latin.txt"}, ctx)
            self.assertFalse(r_bad_utf8["ok"])
            self.assertIn("UTF-8", r_bad_utf8["error"])

            # Out-of-bounds start_line
            r_oob = execute_tool("read_file", {"path": "sub/other.py", "start_line": 99}, ctx)
            self.assertFalse(r_oob["ok"])
            self.assertTrue(r_oob["hint"])

            # allowed_paths fence
            fenced = ToolContext(workspace_root=ws, allowed_paths=("empty.py",))
            r_denied = execute_tool("read_file", {"path": "sub/other.py"}, fenced)
            self.assertFalse(r_denied["ok"])
            self.assertIn("allowed_paths", r_denied["error"])
            r_ok = execute_tool("read_file", {"path": "empty.py"}, fenced)
            self.assertTrue(r_ok["ok"])

    def test_list_files_gitignore_depth_glob_and_truncation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / ".gitignore").write_text("ignored_dir/\n*.log\n", encoding="utf-8")
            (ws / "ignored_dir").mkdir()
            (ws / "ignored_dir" / "secret.py").write_text("a=1\n", encoding="utf-8")
            (ws / ".git").mkdir()
            (ws / ".git" / "config").write_text("x", encoding="utf-8")
            (ws / "debug.log").write_text("log", encoding="utf-8")
            (ws / "a.py").write_text("1", encoding="utf-8")
            (ws / "pkg").mkdir()
            (ws / "pkg" / "b.py").write_text("2", encoding="utf-8")
            (ws / "pkg" / "deep").mkdir()
            (ws / "pkg" / "deep" / "c.py").write_text("3", encoding="utf-8")

            ctx = ToolContext(workspace_root=ws)
            r_all = execute_tool("list_files", {"path": ".", "max_depth": 3}, ctx)
            self.assertTrue(r_all["ok"])
            entries = r_all["data"]["entries"]
            self.assertIn("a.py", entries)
            self.assertIn("pkg/", entries)
            self.assertIn("pkg/b.py", entries)
            self.assertIn("pkg/deep/c.py", entries)
            self.assertFalse(
                any("ignored_dir" in e or e == ".git/" or e.startswith(".git/") or "debug.log" in e for e in entries),
                msg=f"Unexpected ignored entries in {entries}",
            )

            # Depth limit
            r_d1 = execute_tool("list_files", {"path": ".", "max_depth": 1}, ctx)
            self.assertNotIn("pkg/b.py", r_d1["data"]["entries"])

            # Glob filter including recursive **/ patterns
            r_py = execute_tool("list_files", {"pattern": "*.py"}, ctx)
            self.assertEqual(r_py["data"]["entries"], ["a.py", "pkg/b.py", "pkg/deep/c.py"])

            r_glob_star = execute_tool("list_files", {"pattern": "**/*.py"}, ctx)
            self.assertEqual(r_glob_star["data"]["entries"], ["a.py", "pkg/b.py", "pkg/deep/c.py"])

            r_glob_pkg = execute_tool("list_files", {"pattern": "pkg/**/*.py"}, ctx)
            self.assertEqual(r_glob_pkg["data"]["entries"], ["pkg/b.py", "pkg/deep/c.py"])

            # Truncation
            tight = ToolContext(workspace_root=ws, max_list_entries=2)
            r_trunc = execute_tool("list_files", {}, tight)
            self.assertTrue(r_trunc["ok"])
            self.assertTrue(r_trunc["truncated"])
            self.assertEqual(len(r_trunc["data"]["entries"]), 2)
            self.assertGreater(r_trunc["data"]["total_found"], 2)

            # Passing a file returns helpful hint
            r_file = execute_tool("list_files", {"path": "a.py"}, ctx)
            self.assertFalse(r_file["ok"])
            self.assertIn("read_file", r_file["hint"])

    def test_search_code_literal_regex_binary_skip_and_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / ".gitignore").write_text("skip.py\n", encoding="utf-8")
            (ws / "skip.py").write_text("foo(bar)[0]\n", encoding="utf-8")
            (ws / "src").mkdir()
            (ws / "src" / "main.py").write_text(
                "val = foo(bar)[0]\nVAL = FOO(BAR)[0]\nother = 123\n",
                encoding="utf-8",
            )
            (ws / "src" / "notes.md").write_text("foo(bar)[0] in docs\n", encoding="utf-8")
            (ws / "src" / "blob.bin").write_bytes(b"\x00foo(bar)[0]\x00")

            ctx = ToolContext(workspace_root=ws, max_search_matches=2)

            # Default literal search matches regex metacharacters cleanly
            r_lit = execute_tool("search_code", {"query": "foo(bar)[0]"}, ctx)
            self.assertTrue(r_lit["ok"])
            self.assertEqual(r_lit["data"]["match_count"], 2)
            paths = {m["path"] for m in r_lit["data"]["matches"]}
            self.assertEqual(paths, {"src/main.py", "src/notes.md"})
            for m in r_lit["data"]["matches"]:
                self.assertRegex(m["anchor"], r"^\d+:[0-9a-f]{2}$")

            # Glob filter
            r_glob = execute_tool("search_code", {"query": "foo(bar)[0]", "file_glob": "*.py"}, ctx)
            self.assertTrue(r_glob["ok"])
            self.assertEqual(r_glob["data"]["match_count"], 1)
            self.assertEqual(r_glob["data"]["matches"][0]["path"], "src/main.py")

            # Case-insensitive
            r_ci = execute_tool("search_code", {"query": "foo(bar)[0]", "file_glob": "*.py", "case_sensitive": False}, ctx)
            self.assertEqual(r_ci["data"]["match_count"], 2)

            # Regex mode + invalid regex
            r_re = execute_tool("search_code", {"query": r"other\s*=\s*\d+", "is_regex": True}, ctx)
            self.assertTrue(r_re["ok"])
            self.assertEqual(r_re["data"]["match_count"], 1)

            r_bad_re = execute_tool("search_code", {"query": "[unclosed", "is_regex": True}, ctx)
            self.assertFalse(r_bad_re["ok"])
            self.assertIn("is_regex=False", r_bad_re["hint"])

            # Cap + overflow
            many = "\n".join(f"hit_{i}" for i in range(10)) + "\n"
            (ws / "src" / "many.txt").write_text(many, encoding="utf-8")
            r_cap = execute_tool("search_code", {"query": "hit_"}, ctx)
            self.assertTrue(r_cap["ok"])
            self.assertTrue(r_cap["truncated"])
            self.assertEqual(r_cap["data"]["match_count"], 2)
            self.assertEqual(r_cap["data"]["total_matches"], 10)

            # Pure-Python fallback helper directly tested regardless of rg presence
            py_matches, py_total, py_trunc = _search_python(
                ws,
                ctx,
                pattern=re.compile(re.escape("hit_")),
                file_glob="*.txt",
            )
            self.assertEqual(len(py_matches), 2)
            self.assertEqual(py_total, 10)
            self.assertTrue(py_trunc)

            # Recursive file_glob + context_lines + hidden safe dotfile parity across rg and Python
            (ws / ".git").mkdir(exist_ok=True)
            (ws / ".git" / "ignored_hit.py").write_text("FIND_ME = 'bad'\n", encoding="utf-8")
            (ws / ".env").write_text("FIND_ME='secret'\n", encoding="utf-8")
            (ws / ".env.example").write_text("FIND_ME=sample\n", encoding="utf-8")
            (ws / "src" / "ctx_demo.py").write_text(
                "line_one = 1\nFIND_ME = 2\nline_three = 3\n",
                encoding="utf-8",
            )
            full_ctx = ToolContext(workspace_root=ws, max_search_matches=20)
            r_ctx = execute_tool(
                "search_code",
                {"query": "FIND_ME", "file_glob": "src/**/*.py", "context_lines": 1},
                full_ctx,
            )
            self.assertTrue(r_ctx["ok"])
            self.assertEqual(r_ctx["data"]["match_count"], 1)
            m0 = r_ctx["data"]["matches"][0]
            self.assertEqual(m0["path"], "src/ctx_demo.py")
            self.assertIn("context", m0)
            self.assertIn("1:", m0["context"])
            self.assertIn("3:", m0["context"])

            r_hidden = execute_tool("search_code", {"query": "FIND_ME"}, full_ctx)
            found_paths = {m["path"] for m in r_hidden["data"]["matches"]}
            self.assertEqual(found_paths, {"src/ctx_demo.py", ".env.example"})


if __name__ == "__main__":
    unittest.main()
