"""Unit tests for ``code_intel`` (H-13), ``checkpoint`` (H-24), and ``HookRegistry``/sensors (H-21, H-22)."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from hivo.tools import (
    ERR_HOOK_BLOCKED,
    ERR_ORACLE_LOCKED,
    HookRegistry,
    ToolContext,
    execute_tool,
)


class TestToolsIntelCheckpointHooks(unittest.TestCase):
    def test_code_intel_outline_repo_map_find_symbol_and_references(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "pkg").mkdir()
            (ws / "pkg" / "math_ops.py").write_text(
                "class Calculator:\n"
                "    def add(self, a, b):\n"
                "        return a + b\n\n"
                "def helper(x):\n"
                "    return Calculator().add(x, 1)\n",
                encoding="utf-8",
            )
            (ws / "pkg" / "ui.ts").write_text(
                "export interface Config {\n  mode: string;\n}\n"
                "export function renderApp(cfg: Config) {\n  return cfg.mode;\n}\n",
                encoding="utf-8",
            )
            ctx = ToolContext(workspace_root=ws)

            # Python outline without bodies
            r_out = execute_tool("code_intel", {"action": "outline", "path": "pkg/math_ops.py"}, ctx)
            self.assertTrue(r_out["ok"])
            names = [s["name"] for s in r_out["data"]["symbols"]]
            self.assertEqual(names, ["Calculator", "Calculator.add", "helper"])
            self.assertNotIn("return a + b", str(r_out["data"]))

            # TypeScript outline checks brace-tracked end_line and end_anchor
            r_ts = execute_tool("code_intel", {"action": "outline", "path": "pkg/ui.ts"}, ctx)
            self.assertTrue(r_ts["ok"])
            ts_syms = r_ts["data"]["symbols"]
            self.assertEqual([s["name"] for s in ts_syms], ["Config", "renderApp"])
            self.assertEqual((ts_syms[0]["start_line"], ts_syms[0]["end_line"]), (1, 3))
            self.assertEqual((ts_syms[1]["start_line"], ts_syms[1]["end_line"]), (4, 6))
            for s in ts_syms:
                self.assertIn("end_anchor", s)
                self.assertRegex(s["end_anchor"], r"^\d+:[0-9a-f]{2}$")

            # repo_map
            r_map = execute_tool("code_intel", {"action": "repo_map"}, ctx)
            self.assertTrue(r_map["ok"])
            self.assertEqual(r_map["data"]["file_count"], 2)

            # find_symbol
            r_sym = execute_tool("code_intel", {"action": "find_symbol", "symbol": "add"}, ctx)
            self.assertTrue(r_sym["ok"])
            self.assertEqual(r_sym["data"]["match_count"], 1)
            self.assertEqual(r_sym["data"]["matches"][0]["path"], "pkg/math_ops.py")
            self.assertEqual(r_sym["data"]["matches"][0]["start_line"], 2)

            # find_references
            r_ref = execute_tool("code_intel", {"action": "find_references", "symbol": "Calculator"}, ctx)
            self.assertTrue(r_ref["ok"])
            self.assertEqual(r_ref["data"]["match_count"], 2)
            self.assertTrue(any(m["is_definition"] for m in r_ref["data"]["matches"]))
            self.assertTrue(any(not m["is_definition"] for m in r_ref["data"]["matches"]))

    def test_checkpoint_create_rollback_and_clean_workspace(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "a.py").write_text("a = 1\n", encoding="utf-8")
            (ws / "b.py").write_text("b = 2\n", encoding="utf-8")
            (ws / "sub").mkdir()
            (ws / "sub" / "c.py").write_text("c = 3\n", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            r_cp1 = execute_tool("checkpoint", {"action": "create"}, ctx)
            self.assertTrue(r_cp1["ok"])
            cp_id = r_cp1["data"]["checkpoint_id"]
            tree_hash_1 = r_cp1["data"]["tree_hash"]
            self.assertEqual(r_cp1["data"]["file_count"], 3)
            # Zero untracked checkpoint files inside workspace root (H-33)
            self.assertFalse((ws / ".hivo").exists())

            # Modify 2 files, delete 1 file, add 1 new nested file
            (ws / "a.py").write_text("a = 999\n", encoding="utf-8")
            (ws / "b.py").write_text("b = 999\n", encoding="utf-8")
            (ws / "sub" / "c.py").unlink()
            (ws / "extra").mkdir()
            (ws / "extra" / "temp.py").write_text("temp = True\n", encoding="utf-8")

            r_list = execute_tool("checkpoint", {"action": "list"}, ctx)
            self.assertTrue(r_list["ok"])
            self.assertEqual(r_list["data"]["count"], 1)

            r_rb = execute_tool("checkpoint", {"action": "rollback", "checkpoint_id": cp_id}, ctx)
            self.assertTrue(r_rb["ok"])
            self.assertTrue(r_rb["data"]["exact_match"])
            self.assertEqual(r_rb["data"]["tree_hash"], tree_hash_1)
            self.assertEqual((ws / "a.py").read_text(encoding="utf-8"), "a = 1\n")
            self.assertEqual((ws / "b.py").read_text(encoding="utf-8"), "b = 2\n")
            self.assertEqual((ws / "sub" / "c.py").read_text(encoding="utf-8"), "c = 3\n")
            self.assertFalse((ws / "extra" / "temp.py").exists())
            self.assertFalse((ws / "extra").exists())

            # Rollback respects protected_paths oracle lock
            (ws / "locked.py").write_text("v = 2\n", encoding="utf-8")
            locked_ctx = ToolContext(workspace_root=ws, protected_paths=("locked.py",))
            # Even if an old snapshot didn't have locked.py, rollback won't delete an oracle-locked file
            r_locked_rb = execute_tool("checkpoint", {"action": "rollback", "checkpoint_id": cp_id}, locked_ctx)
            self.assertFalse(r_locked_rb["ok"])
            self.assertEqual(r_locked_rb["error_code"], ERR_ORACLE_LOCKED)

    def test_code_intel_variables_syntax_fallback_and_brace_comments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "cfg.py").write_text(
                "API_PORT: int = 8080\nTIMEOUT = 30\n\ndef boot():\n    return API_PORT\n",
                encoding="utf-8",
            )
            (ws / "broken.py").write_text(
                "def recovered_fn(a, b):\n    x = (\n\nclass RecoveredCls:\n    pass\n",
                encoding="utf-8",
            )
            (ws / "brace.js").write_text(
                "export function fmt(x) {\n  const s = '}'; // }\n  return s + x;\n}\n",
                encoding="utf-8",
            )
            ctx = ToolContext(workspace_root=ws)

            r_cfg = execute_tool("code_intel", {"action": "outline", "path": "cfg.py"}, ctx)
            self.assertTrue(r_cfg["ok"])
            cfg_syms = {s["name"]: s for s in r_cfg["data"]["symbols"]}
            self.assertEqual(cfg_syms["API_PORT"]["kind"], "variable")
            self.assertEqual(cfg_syms["TIMEOUT"]["kind"], "variable")
            self.assertRegex(cfg_syms["boot"]["end_anchor"], r"^\d+:[0-9a-f]{2}$")

            r_brk = execute_tool("code_intel", {"action": "outline", "path": "broken.py"}, ctx)
            self.assertTrue(r_brk["ok"])
            self.assertEqual([s["name"] for s in r_brk["data"]["symbols"]], ["recovered_fn", "RecoveredCls"])

            r_js = execute_tool("code_intel", {"action": "outline", "path": "brace.js"}, ctx)
            self.assertTrue(r_js["ok"])
            self.assertEqual((r_js["data"]["symbols"][0]["start_line"], r_js["data"]["symbols"][0]["end_line"]), (1, 4))

    def test_checkpoint_skips_symlinks(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            outer_path = Path(outer)
            ws = outer_path / "ws"
            ws.mkdir()
            ext = outer_path / "outside.txt"
            ext.write_text("OUTSIDE", encoding="utf-8")
            (ws / "real.py").write_text("x = 1\n", encoding="utf-8")
            try:
                os.symlink(ext, ws / "sym.txt")
            except OSError as exc:
                self.skipTest(f"OS symlink creation unavailable without privileges: {exc}")

            ctx = ToolContext(workspace_root=ws)
            r_cp = execute_tool("checkpoint", {"action": "create"}, ctx)
            self.assertTrue(r_cp["ok"])
            self.assertEqual(r_cp["data"]["file_count"], 1)

    def test_lifecycle_hooks_pre_tool_and_post_edit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            hooks = HookRegistry()
            events: list[str] = []

            @hooks.on_pre_tool
            def block_forbidden(tool_name, args, ctx):
                events.append(f"pre:{tool_name}")
                if tool_name == "write_file" and "forbidden" in args.get("path", ""):
                    return {"ok": False, "error": "forbidden path", "hint": "choose another path"}
                return None

            @hooks.on_post_edit
            def check_todo(tool_name, rel_posix, resolved_path, ctx):
                events.append(f"post:{tool_name}:{rel_posix}")
                if "TODO_FORBIDDEN" in resolved_path.read_text(encoding="utf-8"):
                    return ["post_edit policy: remove TODO_FORBIDDEN marker"]
                return []

            # Loop-level pre_complete hooks were trimmed out of hivo/tools/hooks.py
            self.assertFalse(hasattr(hooks, "on_pre_complete"))
            self.assertFalse(hasattr(hooks, "run_pre_complete"))

            ctx = ToolContext(workspace_root=ws, hooks=hooks)

            # pre_tool blocks write before touching disk
            r_blk = execute_tool("write_file", {"path": "forbidden.py", "content": "x = 1\n"}, ctx)
            self.assertFalse(r_blk["ok"])
            self.assertEqual(r_blk["error_code"], ERR_HOOK_BLOCKED)
            self.assertFalse((ws / "forbidden.py").exists())

            # post_edit injects diagnostics alongside syntax check
            r_post = execute_tool(
                "write_file",
                {"path": "ok.py", "content": "# TODO_FORBIDDEN\nx = 1\n"},
                ctx,
            )
            self.assertTrue(r_post["ok"])
            self.assertFalse(r_post["data"]["syntax_ok"])
            self.assertIn("remove TODO_FORBIDDEN marker", r_post["data"]["diagnostics"][0])
            self.assertIn("pre:write_file", events)
            self.assertIn("post:write_file:ok.py", events)


if __name__ == "__main__":
    unittest.main()
