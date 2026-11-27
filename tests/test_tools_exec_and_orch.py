"""Unit tests for ``run_command``, ``update_plan``, ``dispatch_worker``, and ``ask_user``."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from hivo.tools import (
    ERR_COMMAND_REFUSED,
    ERR_COMMAND_TIMEOUT,
    PlanState,
    ToolContext,
    effective_scratch_dir,
    execute_tool,
)


class TestToolsExecAndOrch(unittest.TestCase):
    def test_run_command_stdout_stderr_separation_and_external_scratch_offload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            script = ws / "emit.py"
            script.write_text(
                "import sys\n"
                "for i in range(150):\n"
                "    print(f'OUT_{i}')\n"
                "print('ERR_MSG', file=sys.stderr)\n"
                "sys.exit(int(sys.argv[1]) if len(sys.argv) > 1 else 0)\n",
                encoding="utf-8",
            )
            ctx = ToolContext(workspace_root=ws, max_output_chars=2_000, timeout_sec=15)

            r_ok = execute_tool("run_command", {"command": "python emit.py 0"}, ctx)
            self.assertTrue(r_ok["ok"])
            self.assertTrue(r_ok["truncated"])
            self.assertEqual(r_ok["data"]["exit_code"], 0)
            self.assertIn("OUT_0", r_ok["data"]["stdout"])
            self.assertIn("OUT_149", r_ok["data"]["stdout"])
            self.assertIn("ERR_MSG", r_ok["data"]["stderr"])
            self.assertNotIn("ERR_MSG", r_ok["data"]["stdout"])

            # Overflow log stored outside workspace root (H-33) and readable in slices via read_file (H-15)
            self.assertFalse((ws / ".hivo").exists())
            log_rel = r_ok["data"]["log_path"]
            self.assertIsNotNone(log_rel)
            self.assertTrue(log_rel.startswith("@scratch/tool_logs/"))
            scratch_file = effective_scratch_dir(ctx) / log_rel[len("@scratch/") :]
            self.assertTrue(scratch_file.is_file())

            r_slice = execute_tool(
                "read_file",
                {"path": log_rel, "start_line": 70, "end_line": 85},
                ctx,
            )
            self.assertTrue(r_slice["ok"])
            self.assertIn("OUT_75", r_slice["data"]["content"])

            # Non-zero exit code is ok=True with exit_code=2 and hint combining exit code + log_path
            r_fail = execute_tool("run_command", {"command": "python emit.py 2"}, ctx)
            self.assertTrue(r_fail["ok"])
            self.assertEqual(r_fail["data"]["exit_code"], 2)
            self.assertIn("exited with code 2", r_fail["hint"])
            self.assertIn("@scratch/tool_logs/", r_fail["hint"])

    def test_run_command_stdin_devnull_and_secret_env_scrubbing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "ask_input.py").write_text("input('Name: ')\n", encoding="utf-8")
            (ws / "show_env.py").write_text(
                "import os\n"
                "print('KEY=' + os.environ.get('OPENAI_API_KEY', 'MISSING'))\n"
                "print('CI=' + os.environ.get('CI', ''))\n",
                encoding="utf-8",
            )
            ctx = ToolContext(workspace_root=ws, timeout_sec=5)

            # input() must fail immediately with EOFError rather than hanging until timeout (H-10)
            r_in = execute_tool("run_command", {"command": "python ask_input.py"}, ctx)
            self.assertTrue(r_in["ok"])
            self.assertFalse(r_in["data"]["timed_out"])
            self.assertNotEqual(r_in["data"]["exit_code"], 0)
            self.assertIn("EOFError", r_in["data"]["stderr"])

            # Host API secrets must be scrubbed from child env (H-08)
            old_val = os.environ.get("OPENAI_API_KEY")
            os.environ["OPENAI_API_KEY"] = "sk-test-secret-value"
            try:
                r_env = execute_tool("run_command", {"command": "python show_env.py"}, ctx)
            finally:
                if old_val is None:
                    os.environ.pop("OPENAI_API_KEY", None)
                else:
                    os.environ["OPENAI_API_KEY"] = old_val
            self.assertTrue(r_env["ok"])
            self.assertIn("KEY=MISSING", r_env["data"]["stdout"])
            self.assertIn("CI=true", r_env["data"]["stdout"])
            self.assertNotIn("sk-test-secret-value", r_env["data"]["stdout"])

    def test_run_command_timeout_kills_tree_and_captures_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            pid_file = ws / "child.pid"
            (ws / "hang.py").write_text(
                "import subprocess, sys, time\n"
                "print('PARTIAL_LINE', flush=True)\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
                "open('child.pid', 'w').write(str(child.pid))\n"
                "time.sleep(60)\n",
                encoding="utf-8",
            )
            ctx = ToolContext(workspace_root=ws, timeout_sec=1)
            r_to = execute_tool("run_command", {"command": "python hang.py", "timeout_sec": 1}, ctx)
            self.assertFalse(r_to["ok"])
            self.assertEqual(r_to["error_code"], ERR_COMMAND_TIMEOUT)
            self.assertTrue(r_to["data"]["timed_out"])
            self.assertIsNone(r_to["data"]["exit_code"])
            self.assertIn("timed out", r_to["error"].lower())
            self.assertIn("PARTIAL_LINE", r_to["data"]["stdout"])

            if pid_file.exists():
                child_pid = int(pid_file.read_text(encoding="utf-8").strip())
                try:
                    os.kill(child_pid, 0)
                except OSError:
                    pass

    def test_run_command_security_guards_and_allowlist(self) -> None:
        with tempfile.TemporaryDirectory() as outer:
            ws = Path(outer) / "ws"
            ws.mkdir()
            (ws / "sub").mkdir()
            (ws / "sub" / "hello.py").write_text("print('hi')\n", encoding="utf-8")
            ctx = ToolContext(workspace_root=ws)

            for bad_cmd in ("python --version && echo hi", "python --version | cat", "python --version > out.txt"):
                r = execute_tool("run_command", {"command": bad_cmd}, ctx)
                self.assertFalse(r["ok"], msg=f"Should refuse {bad_cmd!r}")
                self.assertEqual(r["error_code"], ERR_COMMAND_REFUSED)

            self.assertFalse(execute_tool("run_command", {"command": "python -c \"print(1)\""}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "node -e \"console.log(1)\""}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "git commit -m test"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "git branch -D main"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "python ../outside.py"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "python --file=../../secret.txt"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "python --config=.env"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "python sub/hello.py .env"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "git show HEAD:.env"}, ctx)["ok"])
            self.assertFalse(execute_tool("run_command", {"command": "git show HEAD:../../etc/passwd"}, ctx)["ok"])

            # Safe example file & workspace-confined --flag=path remain permitted
            (ws / ".env.example").write_text("SAMPLE=1\n", encoding="utf-8")
            r_safe_flag = execute_tool("run_command", {"command": "python sub/hello.py --cfg=.env.example"}, ctx)
            self.assertTrue(r_safe_flag["ok"])

            r_sub = execute_tool("run_command", {"command": "python hello.py", "cwd": "sub"}, ctx)
            self.assertTrue(r_sub["ok"])
            self.assertEqual(r_sub["data"]["stdout"].strip(), "hi")

            restricted = ToolContext(workspace_root=ws, allowed_commands=("pytest",))
            r_blocked = execute_tool("run_command", {"command": "python hello.py"}, restricted)
            self.assertFalse(r_blocked["ok"])
            self.assertEqual(r_blocked["error_code"], ERR_COMMAND_REFUSED)

    def test_orchestration_tools_update_plan_dispatch_worker_ask_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            plan = PlanState()
            dispatched: list[dict] = []

            def fake_worker(packet: dict) -> dict:
                dispatched.append(packet)
                return {
                    "status": "done",
                    "modified_files": packet["target_files"],
                    "diff_summary": "Updated 1 function",
                }

            def fake_ask(question: str, options: list[str]) -> str:
                return options[0] if options else "yes"

            bare_ctx = ToolContext(workspace_root=ws)
            self.assertFalse(
                execute_tool(
                    "update_plan",
                    {"steps": [{"id": "s1", "title": "Init", "status": "pending"}]},
                    bare_ctx,
                )["ok"]
            )
            self.assertFalse(
                execute_tool(
                    "dispatch_worker",
                    {"task": "Edit file", "target_files": ["a.py"]},
                    bare_ctx,
                )["ok"]
            )
            self.assertFalse(execute_tool("ask_user", {"question": "Proceed?"}, bare_ctx)["ok"])

            ctx = ToolContext(
                workspace_root=ws,
                plan_store=plan,
                worker_dispatcher=fake_worker,
                user_prompter=fake_ask,
            )

            r_plan = execute_tool(
                "update_plan",
                {
                    "steps": [
                        {"id": "s1", "title": "Read code", "status": "done", "files": ["src/a.py"]},
                        {"id": "s2", "title": "Fix bug", "status": "in_progress", "files": ["src/b.py"]},
                    ]
                },
                ctx,
            )
            self.assertTrue(r_plan["ok"])
            self.assertEqual(plan.counts()["done"], 1)
            self.assertEqual(plan.counts()["in_progress"], 1)

            r_plan_esc = execute_tool(
                "update_plan",
                {"steps": [{"id": "s1", "title": "Bad", "status": "pending", "files": ["../evil.py"]}]},
                ctx,
            )
            self.assertFalse(r_plan_esc["ok"])

            r_plan_dup = execute_tool(
                "update_plan",
                {
                    "steps": [
                        {"id": "s1", "title": "One", "status": "pending"},
                        {"id": "s1", "title": "Two", "status": "pending"},
                    ]
                },
                ctx,
            )
            self.assertFalse(r_plan_dup["ok"])
            self.assertIn("Duplicate", r_plan_dup["error"])

            r_disp = execute_tool(
                "dispatch_worker",
                {
                    "task": "Fix calculation",
                    "target_files": ["src/a.py", "src\\a.py"],
                    "context": "def calc(): ...",
                },
                ctx,
            )
            self.assertTrue(r_disp["ok"])
            self.assertEqual(dispatched[0]["target_files"], ["src/a.py"])
            self.assertEqual(r_disp["data"]["status"], "done")

            r_disp_esc = execute_tool(
                "dispatch_worker",
                {"task": "Bad", "target_files": ["../../etc/passwd"]},
                ctx,
            )
            self.assertFalse(r_disp_esc["ok"])

            r_ask = execute_tool(
                "ask_user",
                {"question": "Which option?", "options": ["A", "B"]},
                ctx,
            )
            self.assertTrue(r_ask["ok"])
            self.assertEqual(r_ask["data"]["answer"], "A")
            self.assertFalse(execute_tool("ask_user", {"question": "   "}, ctx)["ok"])


if __name__ == "__main__":
    unittest.main()
