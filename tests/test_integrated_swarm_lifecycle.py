"""Controlled functional and integration tests for Mini Hivo's integrated swarm lifecycle."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import mini


class IntegratedSwarmLifecycleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._saved_argv = list(sys.argv)
        self._saved_globals = {
            name: getattr(mini, name)
            for name in (
                "WORKSPACE",
                "MODEL",
                "MODEL_POLICY",
                "MODEL_CAPABILITIES",
                "ROUTER_MODEL",
                "FALLBACK_MODEL",
                "VISION_MODEL",
                "HOST_PREFLIGHT_RESULT",
                "MEMORY_STORE",
                "RUN",
                "TASKS",
                "RUN_ID",
                "ACTIVE_TRANSACTION",
                "LAST_COMMITTED_TRANSACTION",
                "ACTIVE_CONTRACT",
                "ACTIVE_TOOL_CONTRACT",
                "ACTIVE_CONTEXT_SUFFICIENCY_GATE",
                "ACTIVE_PROJECT_WORLD_MODEL",
                "ACTIVE_IMPACT_CONTRACT",
                "ACTIVE_IMPACT_REQUIRED",
                "ACTIVE_RUN_BUDGET",
            )
        }

        self._http_get_guard = patch.object(
            mini,
            "http_get_json",
            side_effect=AssertionError("Unexpected live network call: mini.http_get_json"),
        )
        self._http_post_guard = patch.object(
            mini,
            "http_post_json",
            side_effect=AssertionError("Unexpected live network call: mini.http_post_json"),
        )
        self._http_get_guard.start()
        self._http_post_guard.start()

        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name) / "workspace"
        mini.WORKSPACE.mkdir(parents=True, exist_ok=True)
        mini.MODEL = "test-model"
        mini.MODEL_CAPABILITIES = set()
        mini.ROUTER_MODEL = ""
        mini.FALLBACK_MODEL = ""
        mini.VISION_MODEL = ""
        mini.MEMORY_STORE = None
        mini.reset_run("recursive")
        mini.RUN["tasks_created"] = 1

    def tearDown(self) -> None:
        try:
            mini.rollback_transaction()
            if mini.MEMORY_STORE is not None and hasattr(mini.MEMORY_STORE, "close"):
                mini.MEMORY_STORE.close()
            mini.MEMORY_STORE = None
        finally:
            self._http_post_guard.stop()
            self._http_get_guard.stop()
            sys.argv = self._saved_argv
            for name, value in self._saved_globals.items():
                setattr(mini, name, value)
            self.temp.cleanup()

    @staticmethod
    def _tool_reply(name: str, arguments: dict) -> dict:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{"function": {"name": name, "arguments": arguments}}],
        }

    @staticmethod
    def _end_reply(content: str = "Completed focused task.") -> dict:
        return {"role": "assistant", "content": content, "tool_calls": []}

    # ------------------------------------------------------------------
    # Test 1: Recursive solve_task Evidence-Licensed Same-Authority Correction
    # ------------------------------------------------------------------
    def test_solve_task_evidence_licensed_same_authority_correction_recovers_and_commits(self) -> None:
        script = mini.WORKSPACE / "status.py"
        initial_bytes = b'print("BROKEN")\n'
        script.write_bytes(initial_bytes)

        goal = "Fix a typo in the status printed by status.py. It must print READY."
        contract = {
            "goal": goal,
            "requirements": [],
            "success_criteria": [],
            "constraints": [],
            "allowed_mutation_paths": ["status.py"],
            "expected_targets": [{"target": "status.py", "path": "status.py"}],
        }
        mini.begin_durable_run(contract)
        mini.RUN["project_mode"] = mini.EXISTING_PROJECT
        mini.RUN["approval_bound_lifecycle"] = False

        task = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = task
        mini.RUN["tasks_created"] = 1

        bad_range_edit = self._tool_reply(
            "edit_file_range",
            {"path": "status.py", "end_line": 1, "new": 'print("READY")\n'},
        )
        attempt_1_replies = iter([
            self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
            bad_range_edit,
            bad_range_edit,
            bad_range_edit,
            bad_range_edit,
            self._end_reply("Attempt 1 exhausted."),
        ])
        attempt_2_replies = iter([
            self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
            self._tool_reply(
                "edit_file_range",
                {"path": "status.py", "start_line": 1, "end_line": 1, "new": 'print("READY")\n'},
            ),
            self._tool_reply(
                "run_command",
                {"command": "python status.py", "expected_stdout": "READY\n"},
            ),
            self._end_reply("Updated status.py to print READY and verified output."),
        ])
        builder_attempts = [attempt_1_replies, attempt_2_replies]
        attempt_index = {"value": -1}
        retry_prompts: list[str] = []
        observed_leaf_tasks: list[dict] = []

        real_execute_leaf = mini.execute_leaf

        def spy_execute_leaf(leaf_task, *args, **kwargs):
            attempt_index["value"] += 1
            observed_leaf_tasks.append({
                "attempt": attempt_index["value"] + 1,
                "disk_before": script.read_bytes(),
                "failure_evidence": list(leaf_task.get("failure_evidence", []) or []),
            })
            return real_execute_leaf(leaf_task, *args, **kwargs)

        def provider(messages, *, role, **_kwargs):
            self.assertEqual(role, "Builder")
            if attempt_index["value"] == 1 and not retry_prompts:
                user_texts = [
                    str(msg.get("content", ""))
                    for msg in messages
                    if isinstance(msg, dict) and msg.get("role") == "user"
                ]
                retry_prompts.extend(user_texts)
            return next(builder_attempts[attempt_index["value"]])

        with patch.object(mini, "ask_ollama", side_effect=provider), \
                patch.object(mini, "execute_leaf", side_effect=spy_execute_leaf), \
                patch.object(mini, "decompose_task", side_effect=AssertionError("Must not split before correction")):
            result = mini.solve_task(
                task,
                0,
                contract,
                mini.load_memory(),
                fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "focused"},
            )

        self.assertEqual(len(observed_leaf_tasks), 2)
        self.assertEqual(observed_leaf_tasks[0]["disk_before"], initial_bytes)
        # Attempt 1 rolled back cleanly; Attempt 2 started with untouched status.py bytes
        # and received the deterministic same-authority correction brief in failure_evidence.
        self.assertEqual(observed_leaf_tasks[1]["disk_before"], initial_bytes)
        retry_evidence_texts = [
            str(item.get("result", ""))
            for item in observed_leaf_tasks[1]["failure_evidence"]
            if isinstance(item, dict)
        ]
        self.assertTrue(
            any(
                "[SAME-AUTHORITY CORRECTION BRIEF | class=SCHEMA_CONTRACT_FAILURE" in text
                and "status.py: exists=True, lines=1" in text
                for text in retry_evidence_texts
            ),
            f"Expected correction brief in retry failure_evidence, got: {retry_evidence_texts!r}",
        )
        self.assertTrue(
            any("[SAME-AUTHORITY CORRECTION BRIEF | class=SCHEMA_CONTRACT_FAILURE" in text for text in retry_prompts),
            "Expected Builder retry prompt to contain the same-authority correction brief.",
        )

        episodes = mini.RUN.get("evidence_licensed_episodes", [])
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0]["episode_class"], "SCHEMA_CONTRACT_FAILURE")
        self.assertEqual(episodes[0]["decision"], "REQUIRE_SAME_AUTHORITY_CORRECTION")
        self.assertFalse(episodes[0]["correction_attempted"])

        self.assertEqual(mini.RUN["splits"], 0)
        self.assertEqual(mini.RUN["evidence_licensed_corrections"], 1)
        self.assertEqual(mini.RUN["evidence_licensed_recoveries"], 1)
        self.assertEqual(result["status"], "done")
        self.assertEqual(task["status"], "done")
        self.assertEqual(script.read_bytes().replace(b"\r\n", b"\n"), b'print("READY")\n')

        proc = subprocess.run(
            [sys.executable, str(script)],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(proc.stdout, "READY\n")

    def test_solve_task_same_authority_correction_is_strictly_bounded_to_one_retry(self) -> None:
        script = mini.WORKSPACE / "status.py"
        initial_bytes = b'print("BROKEN")\n'
        script.write_bytes(initial_bytes)

        goal = "Fix a typo in the status printed by status.py. It must print READY."
        contract = {
            "goal": goal,
            "requirements": [],
            "success_criteria": [],
            "constraints": [],
            "allowed_mutation_paths": ["status.py"],
            "expected_targets": [{"target": "status.py", "path": "status.py"}],
        }
        mini.begin_durable_run(contract)
        mini.RUN["project_mode"] = mini.EXISTING_PROJECT
        mini.RUN["approval_bound_lifecycle"] = False

        task = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = task
        mini.RUN["tasks_created"] = 1

        bad_range_edit = self._tool_reply(
            "edit_file_range",
            {"path": "status.py", "end_line": 1, "new": 'print("READY")\n'},
        )

        def make_failing_attempt():
            return iter([
                self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
                bad_range_edit,
                bad_range_edit,
                bad_range_edit,
                bad_range_edit,
            ])

        attempts = [make_failing_attempt(), make_failing_attempt()]
        leaf_calls = {"count": 0}
        real_execute_leaf = mini.execute_leaf

        def count_leaf_calls(*args, **kwargs):
            leaf_calls["count"] += 1
            return real_execute_leaf(*args, **kwargs)

        with patch.object(mini, "ask_ollama", side_effect=lambda *_a, **_kw: next(attempts[leaf_calls["count"] - 1])), \
                patch.object(mini, "execute_leaf", side_effect=count_leaf_calls), \
                patch.object(mini, "decompose_task", side_effect=AssertionError("Must not split without scope evidence")):
            result = mini.solve_task(
                task,
                mini.MAX_DEPTH,
                contract,
                mini.load_memory(),
                fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "focused"},
            )

        self.assertEqual(leaf_calls["count"], 2)
        self.assertEqual(mini.RUN["evidence_licensed_corrections"], 1)
        self.assertEqual(mini.RUN.get("evidence_licensed_recoveries", 0), 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["granularity_license"]["decision"], "HOLD_TERMINAL_FAILURE")
        self.assertTrue(result["granularity_license"]["correction_attempted"])
        self.assertEqual(script.read_bytes(), initial_bytes)

    # ------------------------------------------------------------------
    # Test 2: Safety Boundary — Approval-Bound & Unauthorized Failures Never Retry or Split
    # ------------------------------------------------------------------
    def test_solve_task_approval_bound_and_unauthorized_failures_stop_immediately(self) -> None:
        goal = "Fix a typo in the status printed by status.py. It must print READY."
        initial_bytes = b'print("BROKEN")\n'

        with self.subTest("approval_bound_lifecycle_stops_immediately"):
            mini.reset_run("recursive")
            script = mini.WORKSPACE / "status.py"
            script.write_bytes(initial_bytes)
            contract = {
                "goal": goal,
                "requirements": [],
                "success_criteria": [],
                "constraints": [],
                "allowed_mutation_paths": ["status.py"],
                "expected_targets": [{"target": "status.py", "path": "status.py"}],
            }
            mini.begin_durable_run(contract)
            mini.RUN["project_mode"] = mini.EXISTING_PROJECT
            mini.RUN["approval_bound_lifecycle"] = True
            task = mini.root_task_from_contract(contract)
            mini.TASKS["ROOT"] = task
            mini.RUN["tasks_created"] = 1

            bad_edit = self._tool_reply(
                "edit_file_range",
                {"path": "status.py", "end_line": 1, "new": 'print("READY")\n'},
            )
            replies = iter([
                self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
                bad_edit,
                bad_edit,
                bad_edit,
                bad_edit,
            ])

            with patch.object(mini, "ask_ollama", side_effect=lambda *_a, **_kw: next(replies)), \
                    patch.object(mini, "decompose_task", side_effect=AssertionError("Approval-bound leaf must not split")):
                result = mini.solve_task(
                    task,
                    0,
                    contract,
                    mini.load_memory(),
                    fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "focused"},
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["granularity_license"]["decision"], "STOP_IMMEDIATELY")
            self.assertFalse(result["granularity_license"]["allow_correction"])
            self.assertFalse(result["granularity_license"]["allow_split"])
            self.assertEqual(mini.RUN.get("evidence_licensed_corrections", 0), 0)
            self.assertEqual(mini.RUN.get("evidence_licensed_recoveries", 0), 0)
            self.assertEqual(mini.RUN["splits"], 0)
            self.assertEqual(mini.RUN["builder_calls"], 1)
            self.assertEqual(script.read_bytes(), initial_bytes)

        with self.subTest("unauthorized_scope_escape_stops_immediately"):
            mini.reset_run("recursive")
            script = mini.WORKSPACE / "status.py"
            script.write_bytes(initial_bytes)
            outside_target = mini.WORKSPACE.parent / "escaped_secret.py"
            if outside_target.exists():
                outside_target.unlink()

            contract = {
                "goal": goal,
                "requirements": [],
                "success_criteria": [],
                "constraints": [],
                "allowed_mutation_paths": ["status.py"],
                "expected_targets": [{"target": "status.py", "path": "status.py"}],
            }
            mini.begin_durable_run(contract)
            mini.RUN["project_mode"] = mini.EXISTING_PROJECT
            mini.RUN["approval_bound_lifecycle"] = False
            task = mini.root_task_from_contract(contract)
            mini.TASKS["ROOT"] = task
            mini.RUN["tasks_created"] = 1

            bad_edit = self._tool_reply(
                "edit_file_range",
                {"path": "status.py", "end_line": 1, "new": 'print("READY")\n'},
            )
            replies = iter([
                self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
                self._tool_reply("write_file", {"path": "../escaped_secret.py", "content": "x = 1\n"}),
                bad_edit,
                bad_edit,
                bad_edit,
                bad_edit,
            ])

            with patch.object(mini, "ask_ollama", side_effect=lambda *_a, **_kw: next(replies)), \
                    patch.object(mini, "decompose_task", side_effect=AssertionError("Unauthorized leaf must not split")):
                result = mini.solve_task(
                    task,
                    0,
                    contract,
                    mini.load_memory(),
                    fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "focused"},
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["evidence_licensed_episode"]["episode_class"], "PERMISSION_OR_SCOPE_DENIAL")
            self.assertEqual(result["granularity_license"]["decision"], "STOP_IMMEDIATELY")
            self.assertFalse(result["granularity_license"]["allow_correction"])
            self.assertFalse(result["granularity_license"]["allow_split"])
            self.assertEqual(mini.RUN.get("evidence_licensed_corrections", 0), 0)
            self.assertEqual(mini.RUN["splits"], 0)
            self.assertEqual(mini.RUN["builder_calls"], 1)
            self.assertEqual(script.read_bytes(), initial_bytes)
            self.assertFalse(outside_target.exists())

        with self.subTest("impact_contract_verification_failure_rolls_back_and_stops_immediately"):
            mini.reset_run("recursive")
            script = mini.WORKSPACE / "status.py"
            script.write_bytes(initial_bytes)
            contract = {
                "goal": goal,
                "requirements": [],
                "success_criteria": [],
                "constraints": [],
                "allowed_mutation_paths": ["status.py", "required.py"],
                "expected_targets": [
                    {"target": "status.py", "path": "status.py"},
                    {"target": "required.py", "path": "required.py"},
                ],
            }
            mini.begin_durable_run(contract)
            mini.RUN["project_mode"] = mini.EXISTING_PROJECT
            mini.RUN["approval_bound_lifecycle"] = False
            task = mini.root_task_from_contract(contract)
            mini.TASKS["ROOT"] = task
            mini.RUN["tasks_created"] = 1

            replies = iter([
                self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
                self._tool_reply("edit_file", {"path": "status.py", "old": '"BROKEN"', "new": '"READY"'}),
                self._tool_reply("run_command", {"command": "python status.py", "expected_stdout": "READY\n"}),
                self._end_reply("Edited only status.py."),
            ])

            with patch.object(mini, "ask_ollama", side_effect=lambda *_a, **_kw: next(replies)), \
                    patch.object(mini, "decompose_task", side_effect=AssertionError("Impact failure must not split")):
                result = mini.solve_task(
                    task,
                    0,
                    contract,
                    mini.load_memory(),
                    fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "focused"},
                )

            self.assertEqual(result["status"], "failed")
            self.assertEqual(result["failure_type"], "IMPACT_CONTRACT_VERIFICATION_FAILED")
            self.assertEqual(result["evidence_licensed_episode"]["episode_class"], "PERMISSION_OR_SCOPE_DENIAL")
            self.assertEqual(result["granularity_license"]["decision"], "STOP_IMMEDIATELY")
            self.assertEqual(mini.RUN.get("evidence_licensed_corrections", 0), 0)
            self.assertEqual(mini.RUN["splits"], 0)
            self.assertEqual(script.read_bytes(), initial_bytes)

    # ------------------------------------------------------------------
    # Test 3: Repairer Safe Unverified Draft Rewrite vs Sibling/Existing Protection
    # ------------------------------------------------------------------
    def test_repairer_unverified_draft_rewrite_vs_sibling_and_existing_protection(self) -> None:
        mini.RUN["project_mode"] = mini.NEW_PROJECT

        # 3A: Sole unverified draft created inside ACTIVE_TRANSACTION (existed=False) ->
        # Repairer keeps edit_file AND gains write_file on that draft.
        mini.begin_transaction("1")
        write_receipt = mini.write_file(
            "index.html",
            "<!doctype html><html><head><title>Draft</title></head><body><canvas></canvas></body></html>\n",
            role="Builder",
        )
        self.assertTrue(write_receipt.startswith("wrote file:"))
        index_path = mini.WORKSPACE / "index.html"
        self.assertFalse(mini.ACTIVE_TRANSACTION["files"][str(index_path)]["existed"])
        repairer_tools = {t["function"]["name"] for t in mini.tools_for_role("Repairer")}
        self.assertIn("edit_file", repairer_tools)
        self.assertIn("write_file", repairer_tools)
        rewrite_receipt = mini.write_file(
            "index.html",
            "<!doctype html><html><head><title>Revised Draft</title></head><body><canvas></canvas></body></html>\n",
            role="Repairer",
        )
        self.assertTrue(rewrite_receipt.startswith("wrote file:"))
        mini.rollback_transaction()
        self.assertFalse(index_path.exists())

        # 3B: Committed sibling file shared.js exists outside ACTIVE_TRANSACTION ->
        # write_file is NOT offered in Repairer toolset and replacing shared.js is refused.
        sibling_path = mini.WORKSPACE / "shared.js"
        sibling_bytes = b"export const SHARED_CONFIG = Object.freeze({ version: 1 });\n"
        sibling_path.write_bytes(sibling_bytes)

        mini.begin_transaction("2")
        mini.write_file(
            "index.html",
            "<!doctype html><html><head><title>Draft 2</title></head><body></body></html>\n",
            role="Builder",
        )
        repairer_tools_with_sibling = {t["function"]["name"] for t in mini.tools_for_role("Repairer")}
        self.assertIn("edit_file", repairer_tools_with_sibling)
        self.assertNotIn("write_file", repairer_tools_with_sibling)
        refused_sibling = mini.write_file("shared.js", "export const BROKEN = true;\n", role="Repairer")
        self.assertTrue(refused_sibling.startswith("error: Repairer cannot replace files with write_file"))
        mini.rollback_transaction()
        self.assertEqual(sibling_path.read_bytes(), sibling_bytes)
        sibling_path.unlink()

        # 3C: Pre-existing file modified inside ACTIVE_TRANSACTION (existed=True) -> refused
        index_path.write_text(
            "<!doctype html><html><head><title>Committed</title></head><body>v1</body></html>\n",
            encoding="utf-8",
        )
        mini.begin_transaction("2")
        edit_receipt = mini.edit_file("index.html", "v1", "v2")
        self.assertTrue(edit_receipt.startswith("edited file:"))
        self.assertTrue(mini.ACTIVE_TRANSACTION["files"][str(index_path)]["existed"])
        refused_existing = mini.write_file("index.html", "replaced", role="Repairer")
        self.assertTrue(refused_existing.startswith("error: Repairer cannot replace files with write_file"))
        mini.rollback_transaction()

    # ------------------------------------------------------------------
    # Test 4: Immediate First-Failure Mutation Hint & Text-JSON Tool-Call Re-anchor
    # ------------------------------------------------------------------
    def test_first_failure_mutation_hint_and_text_json_tool_call_reanchor(self) -> None:
        app_path = mini.WORKSPACE / "app.py"
        app_lines = [f"value_{idx} = {idx}" for idx in range(1, 7)] + ['print("OK")']
        app_path.write_text("\n".join(app_lines) + "\n", encoding="utf-8")

        # 4A: Immediate deterministic hint on repeated_failures == 1 with real line count and zero line-guessing
        hint = mini.tool_recovery_hint(
            "edit_file_range",
            "error: missing start_line",
            1,
            args={"path": "app.py"},
            role="Builder",
        )
        self.assertTrue(hint)
        self.assertIn("start_line", hint)
        self.assertIn(f"has {len(app_lines)} line(s)", hint)
        self.assertIn("Never guess line numbers", hint)
        self.assertNotIn("start_line=1", hint)
        # Safety boundary: unauthorized path errors never emit retry guidance.
        self.assertEqual(
            mini.tool_recovery_hint(
                "write_file",
                "error: '../secret.py' is outside the workspace.",
                1,
                args={"path": "../secret.py"},
                role="Builder",
            ),
            "",
        )

        # 4B: Text-JSON tool call in content triggers re-anchor without executing read_file prematurely
        real_run_tool = mini.run_tool
        executed_tools: list[tuple[str, dict]] = []

        def spy_run_tool(name, args, **kwargs):
            executed_tools.append((name, dict(args) if isinstance(args, dict) else {}))
            return real_run_tool(name, args, **kwargs)

        call_step = {"count": 0}

        def scripted_builder(messages, *, role, **_kwargs):
            self.assertEqual(role, "Builder")
            call_step["count"] += 1
            if call_step["count"] == 1:
                return {
                    "role": "assistant",
                    "content": '{"name": "read_file", "arguments": {"path": "app.py"}}',
                    "tool_calls": [],
                }
            if call_step["count"] == 2:
                # Before sending the real native tool call, verify read_file was NOT executed from text!
                self.assertEqual(executed_tools, [])
                self.assertEqual(mini.RUN.get("worker_tool_format_reanchors", 0), 1)
                self.assertIn("no tool was executed", messages[-1]["content"])
                return self._tool_reply("read_file", {"path": "app.py"})
            if call_step["count"] == 3:
                self.assertEqual([name for name, _ in executed_tools], ["read_file"])
                return self._tool_reply(
                    "run_command",
                    {"command": "python app.py", "expected_stdout": "OK\n"},
                )
            return self._end_reply("Inspected and verified app.py.")

        with patch.object(mini, "ask_ollama", side_effect=scripted_builder), \
                patch.object(mini, "run_tool", side_effect=spy_run_tool):
            worker_result = mini.execute_agent_task(
                "Inspect app.py and verify its output.",
                mini.load_memory(),
                role="Builder",
                task_id="T-REANCHOR",
                context_sufficiency_enabled=False,
            )

        self.assertEqual(worker_result["status"], "done")
        self.assertEqual(mini.RUN.get("worker_tool_format_reanchors", 0), 1)
        self.assertEqual([name for name, _ in executed_tools], ["read_file", "run_command"])

    # ------------------------------------------------------------------
    # Test 5: Real browser_workspace_snapshot Canvas Metrics & CLI Non-Generative Rejection + --json-report
    # ------------------------------------------------------------------
    def test_browser_workspace_snapshot_canvas_metrics(self) -> None:
        if not (mini.PLAYWRIGHT_AVAILABLE and mini.ensure_browser(False)[0]):
            self.skipTest("Playwright Chromium browser is not available in this environment.")

        profile = mini.infer_web_profile("Build a 3D game", {})
        index_html = mini.WORKSPACE / "index.html"

        # 5A-1: 0x0 canvas fails with zero_size_canvas and non-empty repair_hints
        index_html.write_text(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>3D Check</title>
</head>
<body>
  <div id="hud">3D Arena | Score: 0</div>
  <canvas style="width:0;height:0" width="0" height="0"></canvas>
  <script>
    window.AGENT_GAME = {
      getState: () => ({ status: 'playing', score: 0, position: { x: 0 } }),
      start: () => {},
      move: () => {}
    };
  </script>
</body>
</html>
""",
            encoding="utf-8",
        )
        zero_snap = mini.browser_workspace_snapshot("index.html", profile=profile)
        self.assertFalse(zero_snap["environment_error"])
        self.assertFalse(zero_snap["passed"])
        zero_codes = [item["code"] for item in zero_snap.get("failures", [])]
        self.assertIn("zero_size_canvas", zero_codes)
        self.assertTrue(zero_snap.get("repair_hints"))

        # 5A-2: Full-size visible canvas (800x600) with working move('up') mutating position.y passes
        index_html.write_text(
            """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>3D Check</title>
  <style>
    html, body { margin: 0; padding: 0; background: #101820; color: #f4f6f8; }
    #scene { display: block; width: 800px; height: 600px; background: #1d3557; }
  </style>
</head>
<body>
  <div id="hud">3D Arena | Score: <span id="score">0</span></div>
  <canvas id="scene" width="800" height="600"></canvas>
  <script>
    const gameState = { status: 'playing', score: 0, position: { x: 0, y: 0 } };
    window.AGENT_GAME = {
      getState: () => ({
        status: gameState.status,
        score: gameState.score,
        position: { x: gameState.position.x, y: gameState.position.y }
      }),
      start: () => { gameState.status = 'playing'; },
      move: (dir) => {
        if (dir === 'up') {
          gameState.position.y += 1;
        }
      }
    };
  </script>
</body>
</html>
""",
            encoding="utf-8",
        )
        valid_snap = mini.browser_workspace_snapshot("index.html", profile=profile)
        self.assertFalse(valid_snap["environment_error"])
        self.assertTrue(valid_snap["passed"], f"Expected passed=True, got: {valid_snap!r}")
        self.assertEqual(valid_snap.get("failures"), [])
        canvas_metrics = valid_snap["runtime_state"]["canvasMetrics"]
        self.assertGreaterEqual(canvas_metrics["maxWidth"], 64)
        self.assertGreaterEqual(canvas_metrics["maxHeight"], 64)

    def test_cli_main_rejects_non_generative_model_and_writes_json_report(self) -> None:
        cli_root = Path(self.temp.name) / "cli_case"
        cli_ws = cli_root / "ws"
        cli_ws.mkdir(parents=True, exist_ok=True)
        prompt_path = cli_root / "prompt.txt"
        prompt_path.write_text(
            "Fix a typo in the status printed by status.py. It must print READY.\n",
            encoding="utf-8",
        )

        # 5B: Non-generative model (capabilities={"decision"}) rejected with SystemExit(2)
        sys.argv = [
            "mini.py",
            "--model",
            "laya:latest",
            "--workspace",
            str(cli_ws),
            "--prompt-file",
            str(prompt_path),
            "--no-bootstrap",
        ]
        stderr_buf = io.StringIO()
        stdout_buf = io.StringIO()
        with patch.object(mini, "ensure_dependencies", return_value=True), \
                patch.object(mini, "fetch_model_capabilities", return_value={"decision"}), \
                patch.object(mini, "run_host_preflight", side_effect=AssertionError("Preflight must not run")), \
                contextlib.redirect_stdout(stdout_buf), \
                contextlib.redirect_stderr(stderr_buf):
            with self.assertRaises(SystemExit) as exit_ctx:
                mini.main()

        self.assertEqual(exit_ctx.exception.code, 2)
        self.assertIn("laya:latest", stdout_buf.getvalue())

        # 5C: Valid generative CLI run with --json-report writes deterministic, privacy-safe report
        status_file = cli_ws / "status.py"
        status_file.write_bytes(b'print("BROKEN")\n')
        report_path = cli_root / "out" / "deliverable_report.json"

        goal = prompt_path.read_text(encoding="utf-8").strip()
        scoped_contract = {
            "goal": goal,
            "requirements": [],
            "success_criteria": [],
            "constraints": [],
            "allowed_mutation_paths": ["status.py"],
            "expected_targets": [{"target": "status.py", "path": "status.py"}],
        }
        builder_replies = iter([
            self._tool_reply("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
            self._tool_reply("edit_file", {"path": "status.py", "old": '"BROKEN"', "new": '"READY"'}),
            self._tool_reply("run_command", {"command": "python status.py", "expected_stdout": "READY\n"}),
            self._end_reply(f"Verified fix inside {cli_ws / 'status.py'}"),
        ])
        fake_preflight = {
            "passed": True,
            "report": {
                "status": "PASS",
                "model": "gemma4:e4b",
                "canary_calls_completed": 3,
                "canary_calls_requested": 3,
                "inventory": {},
                "resource_snapshots": [{}],
                "warnings": [],
            },
        }
        sys.argv = [
            "mini.py",
            "--mode",
            "baseline",
            "--model",
            "gemma4:e4b",
            "--workspace",
            str(cli_ws),
            "--prompt-file",
            str(prompt_path),
            "--json-report",
            str(report_path),
            "--no-bootstrap",
        ]
        run_stdout = io.StringIO()
        with patch.object(mini, "ensure_dependencies", return_value=True), \
                patch.object(mini, "fetch_model_capabilities", return_value={"completion", "tools"}), \
                patch.object(mini, "run_host_preflight", return_value=fake_preflight), \
                patch.object(mini, "select_local_ollama_model", return_value="gemma4:e4b"), \
                patch.object(mini, "get_goal_contract", return_value=scoped_contract), \
                patch.object(mini, "ask_ollama", side_effect=lambda *_a, **_kw: next(builder_replies)), \
                contextlib.redirect_stdout(run_stdout):
            mini.main()

        self.assertTrue(report_path.is_file())
        report = json.loads(report_path.read_text(encoding="utf-8"))
        expected_bytes = status_file.read_bytes()
        expected_sha = hashlib.sha256(expected_bytes).hexdigest()

        self.assertEqual(report["schema_version"], "1.0")
        self.assertEqual(report["model"], "gemma4:e4b")
        self.assertEqual(report["mode"], "baseline")
        self.assertEqual(report["status"], "done")
        self.assertEqual(report["exit_code"], 0)
        self.assertTrue(report["verified"])
        self.assertNotIn(str(cli_ws), report["summary"])
        self.assertNotIn(cli_ws.as_posix(), report["summary"])
        self.assertEqual(
            report["deliverables"],
            [{"path": "status.py", "size_bytes": len(expected_bytes), "sha256": expected_sha}],
        )

    def test_threejs_library_name_is_not_misread_as_code_path_and_greenfield_child_inherits_index_html(self) -> None:
        # Bare "Three.js" is a library name, whereas "./three.js" or "vendor/three.js" are real paths.
        bare = mini.stage4.classify_code_location_reference("Three.js", {})
        self.assertEqual(bare["classification"], "AMBIGUOUS_TEXT")
        self.assertEqual(bare["confidence_basis"], "ECOSYSTEM_LIBRARY_NAME")
        explicit_rel = mini.stage4.classify_code_location_reference("./three.js", {})
        self.assertEqual(explicit_rel["classification"], "CODE_PATH")
        vendor_rel = mini.stage4.classify_code_location_reference("vendor/three.js", {})
        self.assertEqual(vendor_rel["classification"], "CODE_PATH")

        # Decomposed NEW_PROJECT child mentioning "Three.js" without repeating "index.html"
        # inherits "index.html" from the root contract / worker mission and authorizes write_file("index.html").
        mini.reset_run("recursive")
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        root_goal = (
            'Create a complete, self-contained single-file 3D browser game in `index.html` '
            'titled "Neon Orbit Collector 3D" using Three.js WebGL.'
        )
        root_contract = mini.get_goal_contract(root_goal, interactive=False)
        mini.RUN["source_contract"] = root_contract
        mini.ACTIVE_CONTRACT = root_contract
        mini.ACTIVE_TOOL_CONTRACT = root_contract

        child_task = mini.make_task(
            "1",
            "Set up the basic HTML structure, import map, and core Three.js scene setup.",
            1,
            "ROOT",
            ["The HTML foundation and Three.js imports load cleanly."],
            [],
        )
        candidate = mini._prepare_task_impact_contract(
            child_task,
            root_contract,
            worker_mission={"targets": ["index.html"]},
        )
        target_paths = [item["path"] for item in candidate["expected_targets"]]
        self.assertEqual(target_paths, ["index.html"])
        self.assertNotIn("three.js", [p.lower() for p in target_paths])
        activated = mini._activate_impact_contract(
            candidate,
            context_anchor={"root_goal": root_goal, "local_task": child_task["goal"]},
            execution_contract=root_contract,
            task_id="1",
        )
        self.assertTrue(activated["accepted"], activated)

        # Cyclic Three.js Object3D-like dict inside getState() is sanitized without RecursionError
        scene_dict: dict = {"children": []}
        ship_dict: dict = {
            "isObject3D": True,
            "parent": scene_dict,
            "children": [],
            "position": {"x": 1.5, "y": 0.0, "z": -3.0},
            "matrixWorld": [1] * 16,
        }
        scene_dict["children"].append(ship_dict)
        sanitized_before = mini._acyclic_browser_value({"status": "playing", "player": ship_dict, "score": 0})
        ship_moved = dict(ship_dict, position={"x": 1.5, "y": 0.0, "z": -4.0})
        sanitized_after = mini._acyclic_browser_value({"status": "playing", "player": ship_moved, "score": 0})
        self.assertEqual(sanitized_before["player"], {"x": 1.5, "y": 0.0, "z": -3.0})
        self.assertNotEqual(sanitized_after, sanitized_before)
        self.assertTrue(json.dumps(sanitized_before))

        # Adjective-comma creation prompt yields index.html in _source_creation_requirements()
        # and selects bounded execution before splitting on ROOT.
        mini.RUN["source_requirement_ledger"] = mini.extract_source_requirement_ledger(root_goal, use_model=False)
        mini.RUN["source_contract"] = dict(root_contract, original_goal=root_goal)
        declared = [path for path, _req in mini._source_creation_requirements()]
        self.assertIn("index.html", declared)
        root_node = mini.root_task_from_contract(root_contract)
        fit = mini.decide_task_fit(root_node, 0, root_contract, {"files": []})
        self.assertEqual(fit["decision"], "execute")
        self.assertEqual(fit.get("fit_scope"), "SOURCE_CREATION_NOT_APPROVED_EXECUTION")

    def test_code_review_hardening_cyclic_move_scope_stop_and_target_scoping(self):
        from hivo.evidence_licensed_gate import (
            PERMISSION_OR_SCOPE_DENIAL,
            STOP_IMMEDIATELY,
            build_immediate_mutation_hint,
            classify_failure_episode,
        )
        from hivo.playbooks import classify_project
        from hivo.verification import infer_web_profile

        # 1. Non-web collision/physics library prompt is not misclassified as web_game
        self.assertEqual(
            classify_project({"goal": "Implement a Python hash table library with linear-probing collision resolution"}),
            "library",
        )

        # 2. Greenfield child referencing sibling import/preservation keeps expected_targets scoped to mutated path
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        sibling_cand = mini._impact_candidate_for_worker(
            "Create main.py. Import greet from utils.py; do not modify utils.py.",
            "2",
            context_anchor={"root_goal": "Create utils.py and main.py."},
        )
        self.assertEqual([t["path"] for t in sibling_cand["expected_targets"]], ["main.py"])

        # 3. In-workspace UNEXPECTED_AND_OUT_OF_SCOPE fails closed with 0 retry hints and 0 corrections
        scope_err = (
            "error: UNEXPECTED_AND_OUT_OF_SCOPE: 'unauthorized_in_ws.py' is outside the accepted "
            "impact mutation paths. Use only these authorized targets: [\"status.py\"]"
        )
        self.assertEqual(
            build_immediate_mutation_hint("write_file", {"path": "unauthorized_in_ws.py"}, scope_err),
            "",
        )
        ep = classify_failure_episode({"tool_evidence": [{"tool": "write_file", "target": "unauthorized_in_ws.py", "result": scope_err}]})
        self.assertEqual(ep["episode_class"], PERMISSION_OR_SCOPE_DENIAL)

        # 4. Empty path="" on write_file is rejected as schema error
        self.assertIn(
            "path must be a non-empty file path",
            mini.tool_argument_error("write_file", {"path": "   ", "content": "x = 1\n"}) or "",
        )

        # 5. approval_bound_lifecycle=True + TASK_TOO_BROAD stops immediately without splitting
        (mini.WORKSPACE / "status.py").write_text('print("BROKEN")\n', encoding="utf-8")
        goal = "Fix status.py to print READY."
        contract = {"goal": goal, "requirements": [goal], "constraints": [], "success_criteria": [goal]}
        task_node = mini.root_task_from_contract(contract)
        mini.RUN["approval_bound_lifecycle"] = True
        with patch.object(
            mini,
            "execute_leaf",
            return_value={
                "status": "too_broad",
                "failure_type": "TASK_TOO_BROAD",
                "summary": "TASK_TOO_BROAD",
                "memory": mini.load_memory(),
            },
        ), patch.object(mini, "decompose_task", side_effect=AssertionError("Frozen approval leaf must not split")):
            frozen_res = mini.solve_task(
                task_node,
                0,
                contract,
                mini.load_memory(),
                mini.inspect_repository(),
                fit_decider=lambda *_a, **_kw: {"decision": "execute", "reason": "test"},
            )
        self.assertEqual(frozen_res["granularity_license"]["decision"], STOP_IMMEDIATELY)
        self.assertEqual(mini.RUN.get("splits", 0), 0)
        mini.RUN["approval_bound_lifecycle"] = False

        # 6. Headless Chromium cyclic Object3D inside AGENT_GAME.getState() + move() passes cleanly
        ok, _ = mini.ensure_browser(False)
        if ok:
            (mini.WORKSPACE / "index.html").write_text(
                """<!doctype html>
<html><head><title>Cyclic Object3D Move</title>
<style>html,body{margin:0;height:100%}canvas{width:800px;height:600px;display:block}</style></head>
<body><button id="start">Start</button><canvas id="c" width="800" height="600"></canvas>
<script>
const c = document.getElementById('c');
c.getContext('webgl2') || c.getContext('webgl');
const scene = { children: [] };
const ship = { isObject3D: true, parent: scene, children: [], position: { x: 0, y: 0.5, z: 0 }, matrixWorld: [1,0,0,0] };
scene.children.push(ship);
let status = 'playing', score = 0, tick = 1;
window.AGENT_GAME = {
  getState: () => ({ status, score, player: ship, position: ship, tick: ++tick }),
  start: () => { status = 'playing'; },
  restart: () => { score = 0; ship.position = { x: 0, y: 0.5, z: 0 }; status = 'playing'; },
  move: (dir) => { if (dir === 'forward') ship.position = { x: ship.position.x, y: 0.5, z: ship.position.z - 1 }; }
};
</script></body></html>""",
                encoding="utf-8",
            )
            mini.ACTIVE_TOOL_CONTRACT = {"goal": "Build a 3D Three.js browser game"}
            snap = mini.browser_workspace_snapshot(
                "index.html",
                profile=infer_web_profile("Build a 3D Three.js browser game with keyboard controls and restart", {}),
            )
            self.assertTrue(snap["passed"], snap)
            self.assertEqual(snap["page_errors"], [])


if __name__ == "__main__":
    unittest.main()
