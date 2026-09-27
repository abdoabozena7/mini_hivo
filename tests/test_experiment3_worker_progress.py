import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo.worker_progress import WorkerProgress


def tool_call(name, arguments):
    return {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": json.dumps(arguments)}}],
    }


class WorkerProgressTests(unittest.TestCase):
    def test_repeated_gate_stops_only_constrained_policy(self):
        for policy in ("current", "progress_constrained"):
            tracker = WorkerProgress("child", ("index.html",), policy=policy)
            tracker.observe(name="context_sufficiency_check", target="-", result="ok",
                            successful=True, gate_ready=True)
            for _ in range(3):
                tracker.observe(name="context_sufficiency_check", target="-", result="ok",
                                successful=True, gate_ready=True)
            self.assertEqual(tracker.repeated_gate_checks, 3)
            self.assertEqual(tracker.should_stop(), policy == "progress_constrained")

    def test_new_evidence_resets_streak_and_mutation_records_budget(self):
        tracker = WorkerProgress("child", ("index.html",), policy="progress_constrained")
        tracker.observe(name="context_sufficiency_check", target="-", result="ok",
                        successful=True, gate_ready=True)
        tracker.observe(name="read_file", target="index.html", result="old",
                        successful=True, gate_ready=True)
        tracker.observe(name="read_file", target="index.html", result="old",
                        successful=True, gate_ready=True)
        self.assertEqual(tracker.unique_evidence, 1)
        self.assertEqual(tracker.repeated_inspections, 1)
        self.assertEqual(tracker.no_progress_streak, 1)
        tracker.observe(name="edit_file", target="index.html", result="ok",
                        successful=True, gate_ready=True, changed_file=True,
                        model_round=5, remaining_budget=23)
        self.assertEqual(tracker.first_legal_mutation["tool_step"], 4)
        self.assertEqual(tracker.first_legal_mutation["remaining_budget"], 23)
        self.assertFalse(tracker.should_stop())


class WorkerProgressControllerTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
                      mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("experiment-3-controller")
        (mini.WORKSPACE / "index.html").write_text("old", encoding="utf-8")
        mini.ACTIVE_TOOL_CONTRACT = {"task_id": "child", "goal": "Change index.html"}

    def tearDown(self):
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
         mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE) = self.saved
        self.temp.cleanup()

    def test_constrained_worker_removes_completed_gate_and_reports_blocker(self):
        mini.RUN["worker_progress_policy"] = "progress_constrained"
        observed_tools = []

        def ask(_messages, tools, **_kwargs):
            names = {item["function"]["name"] for item in tools}
            observed_tools.append(names)
            if len(observed_tools) == 1:
                return tool_call("context_sufficiency_check", {
                    "context_status": "sufficient", "reason": "Contract evidence is enough",
                })
            return tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "repeat",
            })

        anchor = {
            "root_goal": "Change index.html", "local_task": "Change index.html",
            "requirements": ["The page contains the new content"],
            "allowed_inspection_paths": ["index.html"],
        }
        facts = [{
            "kind": "contract", "source_identity": "index.html:1",
            "excerpt": "The page contains old content.",
            "claim_key": "page.content", "claim_value": "old",
        }]

        def run_tool(name, args, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(args, role=role, task_id="child")
            return "ok"

        with patch.object(mini, "ask_ollama", side_effect=ask), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Change index.html", {}, role="Builder", task_id="child",
                execution_contract={
                    "allowed_mutation_paths": ["index.html"],
                    "allowed_inspection_paths": ["index.html"],
                },
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=10,
            )

        self.assertEqual(result["failure_type"], mini.WORKER_NO_MUTATION_PROGRESS)
        self.assertTrue(observed_tools[0].__contains__("context_sufficiency_check"))
        self.assertNotIn("context_sufficiency_check", observed_tools[1])
        self.assertLess(result["worker_progress"]["tool_steps"], 10)
        self.assertEqual(result["worker_progress"]["repeated_gate_checks"], 3)
        self.assertEqual((mini.WORKSPACE / "index.html").read_text(encoding="utf-8"), "old")

    def test_first_legal_mutation_requires_authorized_actual_file_change(self):
        mini.RUN["worker_progress_policy"] = "progress_constrained"
        responses = [
            tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "Contract evidence is enough",
            }),
            tool_call("edit_file", {"path": "index.html", "old": "old", "new": "new"}),
            {"role": "assistant", "content": "done", "tool_calls": []},
        ]

        def run_tool(name, args, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(args, role=role, task_id="child")
            if name == "edit_file":
                path = mini.WORKSPACE / args["path"]
                path.write_text(path.read_text(encoding="utf-8").replace(
                    args["old"], args["new"]), encoding="utf-8")
                return "ok"
            return "ok"

        anchor = {
            "root_goal": "Change index.html", "local_task": "Change index.html",
            "requirements": ["The page contains the new content"],
            "allowed_inspection_paths": ["index.html"],
        }
        facts = [{
            "kind": "contract", "source_identity": "index.html:1",
            "excerpt": "The page contains old content.",
            "claim_key": "page.content", "claim_value": "old",
        }]
        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Change index.html", {}, role="Builder", task_id="child",
                execution_contract={
                    "allowed_mutation_paths": ["index.html"],
                    "allowed_inspection_paths": ["index.html"],
                },
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=10,
            )
        first = result["worker_progress"]["first_legal_mutation"]
        self.assertEqual(first["tool_step"], 2)
        self.assertEqual(first["remaining_budget"], 8)
        self.assertEqual(mini.RUN["first_legal_mutation"], first)
        self.assertEqual((mini.WORKSPACE / "index.html").read_text(encoding="utf-8"), "new")


if __name__ == "__main__":
    unittest.main()
