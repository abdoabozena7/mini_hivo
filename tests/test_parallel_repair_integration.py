import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo.http_client import JsonResponse
from hivo.run_budget import RunBudget, RunBudgetExceeded


class ParallelRepairIntegrationTests(unittest.TestCase):
    def setUp(self):
        temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(temp)
        self.enterContext(patch.multiple(
            mini, WORKSPACE=self.root, RUN={}, TASKS={}, RUN_ID="",
            ACTIVE_RUN_BUDGET=None, ACTIVE_TRANSACTION=None, LAST_COMMITTED_TRANSACTION=None,
            ACTIVE_CONTEXT_SUFFICIENCY_GATE=None, ACTIVE_IMPACT_CONTRACT=None,
            ACTIVE_IMPACT_REQUIRED=False, ACTIVE_TOOL_CONTRACT=None, ACTIVE_PROJECT_WORLD_MODEL=None,
            MEMORY_STORE=None,
        ))
        self.enterContext(contextlib.redirect_stdout(io.StringIO()))

    def test_one_run_charges_provider_retry_and_both_roles(self):
        mini.reset_run("baseline")
        incomplete = JsonResponse(200, '{"message":{"content":""},"prompt_eval_count":12}')
        completed = JsonResponse(200, '{"message":{"content":"ready"},"prompt_eval_count":9,"eval_count":2}')
        budget = RunBudget(max_model_calls=2)
        with patch.object(mini, "ACTIVE_RUN_BUDGET", budget), \
                patch.object(mini, "http_post_json", side_effect=[incomplete, completed]) as request, \
                patch.object(mini.time, "sleep"):
            result = mini.ask_ollama([{"role": "user", "content": "ready"}], provider_retries=1)
            self.assertEqual(result["content"], "ready")
            with self.assertRaises(RunBudgetExceeded) as denied:
                mini.ask_ollama([{"role": "user", "content": "verify"}], role="Falsifier")
        self.assertEqual(denied.exception.resource, "model")
        self.assertEqual((request.call_count, mini.RUN["model_calls"]), (2, 2))
        total = mini.RUN["provider_usage"]["total"]
        self.assertEqual(total, {"attempts": 2, "prompt_eval_count": 21, "eval_count": 2,
                                 "missing_prompt_eval_count": 0, "missing_eval_count": 1})

    def test_tool_limit_stops_second_operation_in_same_provider_batch(self):
        doc = self.root / "note.txt"
        doc.write_bytes(b"untouched")
        mini.reset_run("baseline")
        reply = {
            "role": "assistant", "content": "",
            "tool_calls": [
                {"function": {"name": "read_file", "arguments": {"path": "note.txt"}}},
                {"function": {"name": "edit_file", "arguments": {
                    "path": "note.txt", "old": "untouched", "new": "changed",
                }}},
            ],
        }
        with patch.object(mini, "ACTIVE_RUN_BUDGET", RunBudget(max_tool_calls=1)), \
                patch.object(mini, "ask_ollama", return_value=reply), \
                patch.object(mini, "run_tool", wraps=mini.run_tool) as tool:
            with self.assertRaises(RunBudgetExceeded) as denied:
                mini.execute_agent_task("read the note", mini.load_memory(), role="Builder")
        self.assertEqual(denied.exception.resource, "tool")
        tool.assert_called_once_with("read_file", {"path": "note.txt"}, role="Builder")
        self.assertEqual(doc.read_bytes(), b"untouched")

    def test_cli_records_budget_stop_and_rolls_back_active_bytes(self):
        prompt = self.root / "prompt.txt"
        prompt.write_text("Revise note.txt", encoding="utf-8")
        doc = self.root / "note.txt"
        doc.write_bytes(b"original")

        def run(*_args, **_kwargs):
            mini.reset_run("auto")
            mini.begin_transaction("ROOT")
            mini._transaction_capture(doc)
            doc.write_bytes(b"provisional")
            mini._claim_run_budget("model")
            self.fail("zero-budget generation was not refused")

        argv = ["mini.py", "--workspace", str(self.root), "--prompt-file", str(prompt),
                "--no-bootstrap", "--max-model-calls", "0"]
        with patch.object(mini.sys, "argv", argv), \
                patch.object(mini, "ensure_dependencies", return_value=True), \
                patch.object(mini, "run_host_preflight", return_value={"passed": True, "report": {}}), \
                patch.object(mini, "format_host_preflight_report", return_value="preflight ok"), \
                patch.object(mini, "select_local_ollama_model"), \
                patch.object(mini, "configure_console_streams"), \
                patch.object(mini, "run_auto_request", side_effect=run):
            with self.assertRaises(SystemExit) as stopped:
                mini.main()
        self.assertEqual(stopped.exception.code, 1)
        metrics = json.loads((self.root / mini.EXPERIMENT_FILE).read_text(encoding="utf-8"))
        self.assertEqual((metrics["status"], metrics["run_budget_stop_resource"]), ("budget_exhausted", "model"))
        self.assertEqual(metrics["run_budget"]["model_calls"], 0)
        self.assertEqual(doc.read_bytes(), b"original")
        self.assertIsNone(mini.ACTIVE_TRANSACTION)
        self.assertIsNone(mini.ACTIVE_RUN_BUDGET)

    def test_plain_repair_goal_commits_the_named_file_and_protects_reference(self):
        target = self.root / "status.py"
        target.write_bytes(b'print("WRONG")\n')
        reference = self.root / "example.py"
        original_reference = b'print("EXAMPLE")\n'
        reference.write_bytes(original_reference)
        goal = "Fix a typo in status.py based on example.py. It must print READY."
        contract = {"goal": goal, "requirements": [], "constraints": [], "success_criteria": []}

        def tool(name, arguments):
            return {"content": "", "role": "assistant", "tool_calls": [
                {"function": {"name": name, "arguments": arguments}},
            ]}

        responses = [
            tool("context_sufficiency_check", {"context_status": "sufficient", "reason": goal}),
            tool("edit_file", {"path": "example.py", "old": "EXAMPLE", "new": "CHANGED"}),
            tool("edit_file", {"path": "status.py", "old": "WRONG", "new": "READY"}),
            tool("run_command", {"command": "python status.py", "expected_stdout": "READY\n"}),
            {"role": "assistant", "content": "Done", "tool_calls": []},
        ]
        with patch.object(mini, "ask_ollama", side_effect=responses):
            result, _ = mini.run_baseline_request(
                goal, mini.load_memory(), contract_override=contract, interactive=False, finish=False,
            )
        self.assertEqual(result["status"], "done")
        self.assertEqual([(self.root / path).resolve() for path in result["changed_files"]], [target.resolve()])
        self.assertIn("outside the accepted impact mutation paths",
                      result["builder"]["tool_evidence"][1]["result"])
        actual = subprocess.run([sys.executable, "-B", str(target)], capture_output=True,
                                text=True, timeout=10, check=True).stdout
        self.assertEqual(actual, "READY\n")
        self.assertEqual(reference.read_bytes(), original_reference)


if __name__ == "__main__":
    unittest.main()
