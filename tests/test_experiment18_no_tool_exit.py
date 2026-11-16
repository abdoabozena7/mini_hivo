import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini


def prose(text="I think the change is complete"):
    return {"role": "assistant", "content": text, "tool_calls": []}


def tool(name, args):
    import json
    return {"role": "assistant", "content": "", "tool_calls": [{
        "function": {"name": name, "arguments": json.dumps(args)}}]}


class NoToolExitGuardTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
                      mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        (mini.WORKSPACE / "numbers_api.py").write_text("def clamp_number(x): return x\n", encoding="utf-8")
        mini.reset_run("experiment18-controller")
        mini.RUN["worker_progress_policy"] = "progress_constrained"

    def tearDown(self):
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
         mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE) = self.saved
        self.temp.cleanup()

    def run_worker(self, answers, *, policy="bounded_reanchor", max_steps=5, tool_handler=None):
        mini.RUN["worker_no_tool_policy"] = policy
        seen = []

        def ask(messages, tools=None, **_kwargs):
            seen.append(messages[-1].get("content", ""))
            return answers[len(seen) - 1]

        anchor = {"root_goal": "Fix clamp_number", "local_task": "Fix clamp_number",
                  "requirements": ["Clamp to upper bound"],
                  "allowed_inspection_paths": ["numbers_api.py"]}
        facts = [{"kind": "contract", "source_identity": "numbers_api.py:1",
                  "excerpt": "The current function returns x unchanged.",
                  "claim_key": "clamp.upper", "claim_value": "missing"}]
        def observed_tool(name, args, role="Builder"):
            if tool_handler:
                return tool_handler(name, args, role)
            return mini._context_sufficiency_tool(args, role=role, task_id="EXEC-001")

        with patch.object(mini, "ask_ollama", side_effect=ask), \
             patch.object(mini, "run_tool", side_effect=observed_tool):
            result = mini.execute_agent_task(
                "Fix clamp_number", {}, role="Builder", task_id="EXEC-001",
                execution_contract={"allowed_mutation_paths": ["numbers_api.py"],
                                    "allowed_inspection_paths": ["numbers_api.py"]},
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=facts, max_steps=max_steps,
            )
        return result, seen

    def test_one_reanchor_then_explicit_no_progress_failure(self):
        result, seen = self.run_worker([prose(), prose("BLOCKED: cannot locate implementation")])
        self.assertEqual(len(seen), 2)
        self.assertIn("not inspected or modified", seen[1])
        self.assertEqual(result["failure_type"], mini.NO_EXECUTION_PROGRESS)
        self.assertEqual(result["worker_progress"]["tool_steps"], 0)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(mini.RUN["worker_no_tool_reanchors"], 1)
        self.assertEqual(mini.RUN["worker_no_progress_exits"], 1)

    def test_default_still_stops_after_first_prose_response(self):
        result, seen = self.run_worker([prose()], policy="current")
        self.assertEqual(len(seen), 1)
        self.assertNotEqual(result["failure_type"], mini.NO_EXECUTION_PROGRESS)

    def test_explicit_reanchor_also_covers_a_new_project_without_approved_paths(self):
        mini.RUN["worker_no_tool_policy"] = "bounded_reanchor"
        with patch.object(mini, "ask_ollama", side_effect=[prose(), prose()]) as ask:
            result = mini.execute_agent_task(
                "Create a new Python greeting utility.", {}, task_id="ROOT",
                context_sufficiency_enabled=True, max_steps=2,
            )
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(result["failure_type"], mini.NO_EXECUTION_PROGRESS)
        self.assertFalse(result["mutation_authorized"])
        self.assertEqual(mini.RUN["worker_no_tool_reanchors"], 1)

    def test_reanchor_is_inside_original_budget(self):
        result, seen = self.run_worker([prose()], max_steps=1)
        self.assertEqual(len(seen), 1)
        self.assertEqual(result["failure_type"], mini.NO_EXECUTION_PROGRESS)
        self.assertEqual(mini.RUN.get("worker_no_tool_reanchors", 0), 0)

    def test_second_response_can_enter_context_protocol(self):
        answers = [prose(), tool("context_sufficiency_check", {
            "context_status": "sufficient", "reason": "Current source and contract are known",
        }), prose("still need an edit")]
        result, seen = self.run_worker(answers)
        self.assertEqual(len(seen), 3)
        self.assertEqual(mini.RUN["worker_no_tool_reanchors"], 1)
        self.assertGreater(mini.RUN["context_sufficiency_checks"], 0)
        self.assertGreater(result["worker_progress"]["tool_steps"], 0)
        self.assertIsNone(result["worker_progress"]["first_legal_mutation"])
        self.assertEqual(result["status"], "failed")


if __name__ == "__main__":
    unittest.main()
