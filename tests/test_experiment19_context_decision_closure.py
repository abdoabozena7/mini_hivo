"""The optional closure guard requires a real bounded context decision."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini


def prose(text="I am done inspecting"):
    return {"role": "assistant", "content": text, "tool_calls": []}


def tool(name, arguments):
    return {"role": "assistant", "content": "", "tool_calls": [{
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }]}


class ContextDecisionClosureTests(unittest.TestCase):
    def setUp(self):
        self.saved = (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
                      mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE)
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        (mini.WORKSPACE / "numbers_api.py").write_text(
            "def clamp_number(x, lower, upper):\n    return x\n", encoding="utf-8")
        mini.reset_run("experiment19-controller")
        mini.RUN["worker_progress_policy"] = "progress_constrained"
        mini.RUN["worker_no_tool_policy"] = "bounded_reanchor"

    def tearDown(self):
        (mini.WORKSPACE, mini.RUN, mini.RUN_ID,
         mini.ACTIVE_TOOL_CONTRACT, mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE) = self.saved
        self.temp.cleanup()

    def run_worker(self, answers, *, closure="bounded_closure", max_steps=5,
                   initial_evidence=None):
        mini.RUN["worker_context_decision_policy"] = closure
        seen = []

        def ask(messages, tools=None, **_kwargs):
            seen.append(messages[-1].get("content", ""))
            answer = answers[len(seen) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        def run_tool(name, args, role="Builder"):
            if name == "read_file":
                return (mini.WORKSPACE / args["path"]).read_text(encoding="utf-8")
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(args, role=role, task_id="EXEC-001")
            return "error: unexpected tool"

        anchor = {"root_goal": "Fix clamp_number", "local_task": "Fix clamp_number",
                  "requirements": ["Clamp to upper bound"],
                  "allowed_inspection_paths": ["numbers_api.py"]}
        with patch.object(mini, "ask_ollama", side_effect=ask), \
             patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Fix clamp_number", {}, role="Builder", task_id="EXEC-001",
                execution_contract={"allowed_mutation_paths": ["numbers_api.py"],
                                    "allowed_inspection_paths": ["numbers_api.py"]},
                context_sufficiency_enabled=True, context_anchor=anchor,
                initial_context_evidence=initial_evidence, max_steps=max_steps,
            )
        return result, seen

    def test_one_reanchor_after_inspection_then_missing_decision(self):
        result, seen = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(), prose(),
        ])
        self.assertEqual(len(seen), 3)
        self.assertIn("required context decision", seen[2])
        self.assertEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)
        self.assertEqual(mini.RUN["context_decision_reanchors"], 1)
        self.assertEqual(mini.RUN["context_decision_missing_exits"], 1)
        self.assertEqual(mini.RUN["context_sufficiency_checks"], 0)
        self.assertFalse(result["mutation_authorized"])

    def test_current_policy_stops_without_reanchor(self):
        result, seen = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
        ], closure="current")
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)
        self.assertEqual(mini.RUN.get("context_decision_reanchors", 0), 0)

    def test_reanchor_consumes_existing_budget(self):
        result, seen = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
        ], max_steps=2)
        self.assertEqual(len(seen), 2)
        self.assertEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)
        self.assertEqual(mini.RUN.get("context_decision_reanchors", 0), 0)

    def test_provider_filtered_empty_response_is_missing_decision(self):
        result, seen = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
            mini.ProviderError("Ollama returned no actionable content or tool_calls: empty response"),
        ])
        self.assertEqual(len(seen), 3)
        self.assertEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)
        self.assertEqual(mini.RUN["context_decision_missing_exits"], 1)

    def test_real_provider_failure_is_not_mislabeled_as_missing_decision(self):
        result, _ = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
            mini.ProviderError("connection refused"),
        ])
        self.assertNotEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)
        self.assertEqual(mini.RUN.get("context_decision_missing_exits", 0), 0)

    def test_insufficient_decision_is_allowed_without_mutation(self):
        result, seen = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
            tool("context_sufficiency_check", {"context_status": "insufficient",
                  "reason": "Caller expectations are absent",
                  "needed_evidence": [{"kind": "callers", "target": "clamp_number users",
                                       "why": "Need callers' expected bound behavior"}]}),
        ], max_steps=3)
        self.assertEqual(len(seen), 3)
        self.assertEqual(mini.RUN["context_sufficiency_checks"], 1)
        self.assertFalse(result["mutation_authorized"])
        self.assertNotEqual(result["failure_type"], mini.CONTEXT_DECISION_MISSING)

    def test_unsupported_sufficient_claim_does_not_bypass_gate(self):
        contradictory = [
            {"kind": "caller", "source_identity": "numbers_api.py:1",
             "excerpt": "upper inclusive", "claim_key": "clamp.upper", "claim_value": "inclusive"},
            {"kind": "test", "source_identity": "tests/test_clamp.py:1",
             "excerpt": "upper exclusive", "claim_key": "clamp.upper", "claim_value": "exclusive"},
        ]
        result, _ = self.run_worker([
            tool("read_file", {"path": "numbers_api.py"}), prose(),
            tool("context_sufficiency_check", {"context_status": "sufficient",
                  "reason": "I think I can edit now"}),
        ], max_steps=3, initial_evidence=contradictory)
        self.assertEqual(mini.RUN["context_sufficiency_checks"], 1)
        self.assertFalse(result["mutation_authorized"])
        self.assertFalse(result["context_sufficiency"]["mutation_allowed"])
        self.assertTrue(result["context_sufficiency"]["contradictions"])


if __name__ == "__main__":
    unittest.main()
