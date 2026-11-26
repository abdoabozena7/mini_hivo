"""Controlled functional end-to-end verification of asymmetric tool connectivity.

Exercises Orchestrator (native) -> dispatch_worker -> spawn_worker_binding ->
Coder Worker (grammar_json) -> Verifier (xml_tags) -> Checkpoint rollback
against a real temporary workspace with independent filesystem and subprocess oracles.
"""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from hivo.tools import (
    ERR_COMMAND_REFUSED,
    ERR_PATH_SECURITY,
    ERR_TOOL_SCHEMA,
    HookRegistry,
    PlanState,
    ToolContext,
    ToolProfile,
    create_tool_binding,
)


class TestToolsConnectivityControlledE2E(unittest.TestCase):
    def test_orchestrator_worker_verifier_rollback_lifecycle(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "src").mkdir()
            (ws / "tests").mkdir()

            original_calc = "def add(a: int, b: int) -> int:\n    return a - b\n"
            (ws / "src" / "calc.py").write_text(original_calc, encoding="utf-8")
            (ws / "src" / "other.py").write_text("SECRET_HELPER = 1\n", encoding="utf-8")
            (ws / ".env").write_text("API_TOKEN=super_secret_123\n", encoding="utf-8")
            (ws / "tests" / "test_calc.py").write_text(
                "import unittest\n"
                "from src.calc import add\n\n"
                "class CalcTest(unittest.TestCase):\n"
                "    def test_add(self):\n"
                "        self.assertEqual(add(2, 3), 5)\n",
                encoding="utf-8",
            )

            plan = PlanState()
            hooks = HookRegistry()
            post_edit_events: list[str] = []

            @hooks.on_post_edit
            def record_edit(tool_name, rel_posix, resolved_path, ctx):
                post_edit_events.append(f"{tool_name}:{rel_posix}")
                return []

            worker_profile = ToolProfile(
                primary_edit_tool="hashline",
                tool_protocol="grammar_json",
                max_active_tools=4,
                error_verbosity="detailed",
            )

            orch_binding_holder: dict = {}

            def run_scripted_worker(packet: dict) -> dict:
                worker = orch_binding_holder["orch"].spawn_worker_binding(
                    packet,
                    worker_profile=worker_profile,
                    max_read_lines=120,
                )
                self.assertEqual(worker.role, "coder_worker")
                self.assertEqual(worker.context.allowed_paths, ("src/calc.py",))
                self.assertEqual(worker.context.max_read_lines, 120)
                self.assertIsNone(worker.context.plan_store)
                self.assertIsNone(worker.context.worker_dispatcher)
                self.assertIsNone(worker.context.user_prompter)

                # Negative security checks inside worker binding
                env_other, _ = worker.execute_call("read_file", {"path": "src/other.py"})
                self.assertFalse(env_other["ok"])
                self.assertEqual(env_other["error_code"], ERR_PATH_SECURITY)

                env_env, _ = worker.execute_call("read_file", {"path": ".env"})
                self.assertFalse(env_env["ok"])
                self.assertEqual(env_env["error_code"], ERR_PATH_SECURITY)

                env_cmd, _ = worker.execute_call("run_command", {"command": "python --version"})
                self.assertFalse(env_cmd["ok"])
                self.assertEqual(env_cmd["error_code"], ERR_TOOL_SCHEMA)

                # Step A: Worker reads target via grammar_json array response
                read_out = worker.execute_response(
                    json.dumps([{"tool": "read_file", "arguments": {"path": "src/calc.py"}}])
                )
                self.assertEqual(len(read_out), 1)
                read_env = read_out[0][1]
                self.assertTrue(read_env["ok"])
                line2_hashline = read_env["data"]["content"].splitlines()[1]

                # Step B: Worker makes a broken edit using forgiving L-prefixed anchor;
                # post-edit sensor reports syntax_ok=False + refreshed updated_window
                bad_edit_out = worker.execute_response(
                    json.dumps({
                        "tool": "edit_file",
                        "arguments": {
                            "path": "src/calc.py",
                            "operation": "replace",
                            "start_anchor": "L" + line2_hashline,
                            "content": "    return a + (",
                        },
                    })
                )
                bad_env = bad_edit_out[0][1]
                self.assertTrue(bad_env["ok"])
                self.assertFalse(bad_env["data"]["syntax_ok"])
                self.assertIn("SyntaxError", bad_env["data"]["syntax_error"])
                refreshed_line2 = next(
                    ln for ln in bad_env["data"]["updated_window"].splitlines() if ln.startswith("2:")
                )

                # Step C: Worker self-corrects using refreshed anchor from updated_window
                fix_out = worker.execute_response(
                    json.dumps({
                        "tool": "edit_file",
                        "arguments": {
                            "path": "src/calc.py",
                            "operation": "replace",
                            "start_anchor": refreshed_line2,
                            "content": "    return a + b",
                        },
                    })
                )
                fix_env, fix_obs = fix_out[0][1], fix_out[0][2]
                self.assertTrue(fix_env["ok"])
                self.assertTrue(fix_env["data"]["syntax_ok"])
                self.assertIn('<tool_observation tool="edit_file" untrusted_data="true">', fix_obs)

                return {
                    "status": "done",
                    "modified_files": ["src/calc.py"],
                    "diff_summary": "Fixed subtraction bug in src/calc.py:add",
                }

            orch_ctx = ToolContext(
                workspace_root=ws,
                protected_paths=("tests/**",),
                hooks=hooks,
                plan_store=plan,
                worker_dispatcher=run_scripted_worker,
            )
            orch = create_tool_binding("orchestrator", context=orch_ctx, protocol="native")
            orch_binding_holder["orch"] = orch

            # 1. Orchestrator locates symbol and snapshots clean workspace before edits
            sym_res = orch.execute_response({
                "tool_calls": [
                    {
                        "id": "c1",
                        "function": {
                            "name": "code_intel",
                            "arguments": json.dumps({"action": "find_symbol", "symbol": "add"}),
                        },
                    },
                    {
                        "id": "c2",
                        "function": {
                            "name": "update_plan",
                            "arguments": json.dumps({
                                "steps": [
                                    {"id": "s1", "title": "Fix add()", "status": "in_progress", "files": ["src/calc.py"]}
                                ]
                            }),
                        },
                    },
                    {
                        "id": "c3",
                        "function": {
                            "name": "checkpoint",
                            "arguments": json.dumps({"action": "create", "checkpoint_id": "pre_fix"}),
                        },
                    },
                ]
            })
            self.assertEqual(len(sym_res), 3)
            self.assertEqual(sym_res[0][1]["data"]["matches"][0]["path"], "src/calc.py")
            self.assertIn("end_anchor", sym_res[0][1]["data"]["matches"][0])
            self.assertEqual(plan.counts()["in_progress"], 1)
            cp_env = sym_res[2][1]
            self.assertTrue(cp_env["ok"])
            orig_tree_hash = cp_env["data"]["tree_hash"]
            self.assertFalse((ws / ".hivo").exists())

            # 2. Orchestrator dispatches fenced worker
            disp_env, _ = orch.execute_call(
                "dispatch_worker",
                {
                    "task": "Fix add(a, b) in src/calc.py to return a + b",
                    "target_files": ["src/calc.py"],
                },
            )
            self.assertTrue(disp_env["ok"])
            self.assertEqual(disp_env["data"]["status"], "done")
            self.assertEqual((ws / "src" / "calc.py").read_text(encoding="utf-8"), "def add(a: int, b: int) -> int:\n    return a + b\n")
            self.assertEqual(post_edit_events, ["edit_file:src/calc.py", "edit_file:src/calc.py"])

            # 3. Verifier (xml_tags protocol) runs real unittest oracle and cannot mutate or read secrets
            verifier = create_tool_binding("verifier", context=orch_ctx, protocol="xml_tags")
            ver_out = verifier.execute_response(
                '<tool_call>{"name": "run_command", "arguments": {"command": "python -m unittest discover -s tests -v"}}</tool_call>'
            )
            self.assertTrue(ver_out[0][1]["ok"])
            self.assertEqual(ver_out[0][1]["data"]["exit_code"], 0)
            self.assertIn("OK", ver_out[0][1]["data"]["stderr"] + ver_out[0][1]["data"]["stdout"])

            ver_mutate, _ = verifier.execute_call("edit_file", {"path": "src/calc.py", "operation": "delete", "start_anchor": "1:00"})
            self.assertFalse(ver_mutate["ok"])
            self.assertEqual(ver_mutate["error_code"], ERR_TOOL_SCHEMA)

            ver_secret, _ = verifier.execute_call("run_command", {"command": "python --cfg=.env"})
            self.assertFalse(ver_secret["ok"])
            self.assertEqual(ver_secret["error_code"], ERR_COMMAND_REFUSED)

            # 4. Orchestrator rolls back to pre_fix checkpoint; disk bytes & test failure restore identically
            rb_env, _ = orch.execute_call("checkpoint", {"action": "rollback", "checkpoint_id": "pre_fix"})
            self.assertTrue(rb_env["ok"])
            self.assertTrue(rb_env["data"]["exact_match"])
            self.assertEqual(rb_env["data"]["tree_hash"], orig_tree_hash)
            self.assertEqual((ws / "src" / "calc.py").read_text(encoding="utf-8"), original_calc)

            ver_after_rb, _ = verifier.execute_call(
                "run_command",
                {"command": "python -m unittest discover -s tests -v"},
            )
            self.assertTrue(ver_after_rb["ok"])
            self.assertNotEqual(ver_after_rb["data"]["exit_code"], 0)


if __name__ == "__main__":
    unittest.main()
