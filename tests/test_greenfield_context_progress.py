"""Greenfield leaf regressions; scripted provider, production gates and file tools."""

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini


def tool_call(name, arguments):
    return {
        "role": "assistant", "content": "",
        "tool_calls": [{"function": {"name": name, "arguments": json.dumps(arguments)}}],
    }


class WorkerBoundary(Exception):
    """Stop the fixture after the real Worker, before application verification."""

    def __init__(self, result):
        self.result = result


class GreenfieldContextProgressTests(unittest.TestCase):
    def setUp(self):
        names = (
            "WORKSPACE", "RUN", "RUN_ID", "ACTIVE_CONTRACT", "ACTIVE_TOOL_CONTRACT",
            "ACTIVE_CONTEXT_SUFFICIENCY_GATE", "ACTIVE_IMPACT_CONTRACT", "ACTIVE_IMPACT_REQUIRED",
            "ACTIVE_PROJECT_WORLD_MODEL", "ACTIVE_TRANSACTION", "LAST_COMMITTED_TRANSACTION", "MEMORY_STORE",
        )
        self.saved = {name: getattr(mini, name) for name in names}
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        mini.WORKSPACE = self.root
        mini.reset_run("recursive")
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        mini.ACTIVE_TOOL_CONTRACT = None
        mini.ACTIVE_TRANSACTION = None
        mini.ACTIVE_PROJECT_WORLD_MODEL = None
        raw = "Build a new standalone page from scratch in this empty workspace. Create artifact.txt."
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        self.contract = mini.normalize_goal_contract(
            raw, mini._deterministic_contract_from_ledger(raw, ledger),
            source_ledger=ledger, confirmed=[], derived=[],
            clarification_questions=[], clarification_answers=[],
        )
        self.contract["source_contract"] = mini.source_contract_from_ledger(raw, ledger)
        self.contract["constraints"] = [
            "Only create artifact.txt; preserve boundary " + str(i) + ": " + "bounded requirement " * 14
            for i in range(8)
        ]
        mini.ACTIVE_CONTRACT = self.contract
        spec = {field: [] for field in mini._PROJECT_SPECIFICATION_FIELDS}
        spec["root_goal"] = raw
        spec["acceptance_criteria"] = ["artifact.txt contains approved output"]
        spec["architecture_invariants"] = list(self.contract["constraints"])
        mini.RUN["project_brain"] = mini.build_project_brain(
            self.contract, spec, mini.inspect_repository(),
        )
        self.task = mini.make_task(
            "1", "Create artifact.txt containing approved output", 1, "ROOT",
            ["artifact.txt contains approved output"], ["artifact.txt"],
        )
        self.mission = {
            "goal_anchor": raw, "task": self.task["goal"],
            "expected_outcome": "artifact.txt contains approved output",
            "targets": ["artifact.txt"], "existing_facts": [],
            "implementation_plan": ["Create the requested local artifact"],
            "interfaces_to_reuse": [], "invariants": list(self.contract["constraints"]),
            "project_specific_quality_rules": [], "do_not": ["Do not write other files"],
            "verification_plan": ["Inspect the artifact content"],
            "done_when": ["artifact.txt contains approved output"],
        }
        self.requests = []

    def tearDown(self):
        mini.rollback_transaction()
        for name, value in self.saved.items():
            setattr(mini, name, value)
        self.temp.cleanup()

    @staticmethod
    def gate_feedback_visible(messages):
        for message in messages:
            if message.get("role") == "tool" and message.get("tool_name") == "context_sufficiency_check":
                try:
                    if json.loads(message["content"]).get("mutation_allowed"):
                        return True
                except (ValueError, TypeError):
                    pass
            if "CONTEXT_SUFFICIENT: the bounded context gate passed" in message.get("content", ""):
                return True
        return False

    def run_greenfield_worker(self, *, repeat=False, script=None, deny_impact=False,
                             evidence_provider=None, progress_policy="current"):
        real_worker = mini.execute_agent_task
        mini.RUN["worker_progress_policy"] = progress_policy

        def compiler(_prompt, validator, _label, _schema, **kwargs):
            self.assertEqual(kwargs["role"], "MissionCompiler")
            self.assertTrue(validator(self.mission))
            return copy.deepcopy(self.mission)

        def ask(messages, tools, **kwargs):
            self.assertEqual(kwargs["role"], "Builder")
            self.requests.append(copy.deepcopy(messages))
            names = {item["function"]["name"] for item in tools}
            if script is not None:
                return script(messages, names)
            if not repeat and self.gate_feedback_visible(messages) and "write_file" in names:
                if (self.root / "artifact.txt").exists():
                    return {"role": "assistant", "content": "Requested artifact created.", "tool_calls": []}
                return tool_call("write_file", {"path": "artifact.txt", "content": "approved output"})
            return tool_call("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "The scoped new-file requirement is explicit.",
            })

        def capture(*args, **kwargs):
            self.assertIsNone(kwargs.get("execution_contract"))
            self.assertTrue(kwargs["context_sufficiency_enabled"])
            self.assertTrue(kwargs["impact_contract_required"])
            if evidence_provider is not None:
                kwargs["context_evidence_provider"] = evidence_provider
            raise WorkerBoundary(real_worker(*args, **kwargs))

        self.assertIsNone(mini._current_execution_contract(self.task))
        self.assertEqual(mini.RUN["worker_progress_policy"], progress_policy)
        with patch.object(mini, "structured_model_call", side_effect=compiler), \
                patch.object(mini, "ask_ollama", side_effect=ask), \
                patch.object(mini, "execute_agent_task", side_effect=capture):
            if deny_impact:
                with patch.object(mini, "_activate_impact_contract", return_value={
                    "accepted": False, "status": "IMPACT_CONTRACT_INVALID",
                }):
                    with self.assertRaises(WorkerBoundary) as completed:
                        mini.execute_leaf(self.task, self.contract, {}, mini.inspect_repository())
            else:
                with self.assertRaises(WorkerBoundary) as completed:
                    mini.execute_leaf(self.task, self.contract, {}, mini.inspect_repository())
        result = completed.exception.result
        print(json.dumps({
            "repeat": repeat, "status": result["status"], "failure_type": result["failure_type"],
            "tool_steps": result["tool_steps_used"], "impact_authorized": result["impact_authorized"],
            "feedback_visible_after_first_check": self.gate_feedback_visible(self.requests[1]),
            "initial_user_chars": len(self.requests[0][-1]["content"]),
            "progress_wrapper": result["worker_progress"],
        }, default=str))
        self.assertIsNone(result["worker_progress"])
        self.assertIsNone(result["mutation_grounding"])
        self.assertGreater(len(mini.compact_text(self.requests[0][-1]["content"], 100000)),
                           mini.MAX_WORKER_MISSION_CHARS)
        return result

    def test_long_greenfield_mission_retains_gate_success_and_can_write(self):
        result = self.run_greenfield_worker()
        self.assertEqual(result["status"], "done", result["summary"])
        self.assertTrue(self.gate_feedback_visible(self.requests[1]))
        self.assertEqual(self.requests[1][1]["content"], self.requests[0][1]["content"])
        self.assertTrue(result["impact_authorized"])
        self.assertEqual((self.root / "artifact.txt").read_text(encoding="utf-8"), "approved output")
        self.assertEqual([e["tool"] for e in result["tool_evidence"]],
                         ["context_sufficiency_check", "write_file"])

    def test_repeated_authorized_checks_stop_without_spending_entire_budget(self):
        result = self.run_greenfield_worker(repeat=True)
        self.assertEqual(result["failure_type"], mini.WORKER_NO_MUTATION_PROGRESS)
        self.assertFalse((self.root / "artifact.txt").exists())
        self.assertLess(result["tool_steps_used"], result["step_budget"])
        self.assertTrue(result["mutation_authorized"])

    def test_constrained_flag_alone_does_not_supply_a_contract_but_guard_still_runs(self):
        result = self.run_greenfield_worker(repeat=True, progress_policy="progress_constrained")
        self.assertEqual(result["failure_type"], mini.WORKER_NO_MUTATION_PROGRESS)
        self.assertEqual(result["tool_steps_used"], 4)

    def test_intervening_task_tool_resets_consecutive_check_guard(self):
        responses = [tool_call("context_sufficiency_check", {"context_status": "sufficient"}) for _ in range(3)]
        responses.append(tool_call("list_files", {}))
        responses += [tool_call("context_sufficiency_check", {"context_status": "sufficient"}) for _ in range(3)]
        responses += [tool_call("write_file", {"path": "artifact.txt", "content": "approved output"}),
                      {"role": "assistant", "content": "Artifact created.", "tool_calls": []}]
        result = self.run_greenfield_worker(script=lambda *_: responses.pop(0))
        self.assertEqual(result["status"], "done")
        self.assertEqual((self.root / "artifact.txt").read_text(encoding="utf-8"), "approved output")

    def test_context_and_mutation_in_same_batch_need_a_fresh_worker_response(self):
        gate = tool_call("context_sufficiency_check", {"context_status": "sufficient"})
        gate["tool_calls"] += tool_call("write_file", {"path": "forbidden.txt", "content": "blocked"})["tool_calls"]

        def script(_messages, _names):
            if len(self.requests) == 1:
                return gate
            self.assertFalse((self.root / "forbidden.txt").exists())
            if len(self.requests) == 2:
                self.assertFalse((self.root / "artifact.txt").exists())
                return tool_call("write_file", {"path": "artifact.txt", "content": "approved output"})
            return {"role": "assistant", "content": "Artifact created.", "tool_calls": []}

        result = self.run_greenfield_worker(script=script)
        self.assertEqual(result["status"], "done")
        self.assertFalse((self.root / "forbidden.txt").exists())
        self.assertEqual((self.root / "artifact.txt").read_text(encoding="utf-8"), "approved output")

    def test_unaccepted_impact_does_not_unlock_write_after_sufficient_context(self):
        responses = [tool_call("context_sufficiency_check", {"context_status": "sufficient"}),
                     tool_call("write_file", {"path": "artifact.txt", "content": "blocked"}),
                     {"role": "assistant", "content": "Cannot complete safely.", "tool_calls": []}]
        result = self.run_greenfield_worker(script=lambda *_: responses.pop(0), deny_impact=True)
        self.assertFalse(result["impact_authorized"])
        self.assertFalse(result["mutation_authorized"])
        self.assertFalse((self.root / "artifact.txt").exists())

    def test_insufficient_context_cannot_mutate(self):
        requests = []
        responses = [tool_call("context_sufficiency_check", {
            "context_status": "insufficient", "reason": "The creation policy remains unresolved.",
            "needed_evidence": [{"kind": "contract", "target": "artifact.txt creation policy",
                                 "why": "Need the missing authority before creating the file."}],
        }), tool_call("write_file", {"path": "artifact.txt", "content": "blocked"}),
            {"role": "assistant", "content": "Cannot complete safely.", "tool_calls": []}]
        result = self.run_greenfield_worker(
            script=lambda *_: responses.pop(0),
            evidence_provider=lambda request, _context: requests.append(request) or [],
        )
        self.assertTrue(requests)
        self.assertFalse(result["context_sufficiency"]["mutation_allowed"])
        self.assertFalse(result["mutation_authorized"])
        self.assertFalse((self.root / "artifact.txt").exists())

    def test_authorized_gate_does_not_allow_workspace_escape(self):
        escaped = self.root.parent / (self.root.name + "-outside.txt")
        self.assertFalse(escaped.exists())
        responses = [tool_call("context_sufficiency_check", {"context_status": "sufficient"}),
                     tool_call("write_file", {"path": "../" + escaped.name, "content": "blocked"}),
                     {"role": "assistant", "content": "Cannot complete safely.", "tool_calls": []}]
        result = self.run_greenfield_worker(script=lambda *_: responses.pop(0))
        self.assertTrue(result["impact_authorized"])
        self.assertFalse(escaped.exists())
        self.assertTrue(any("outside the workspace" in e["result"] for e in result["tool_evidence"]))

    def test_unrelated_candidate_cannot_cross_the_real_precommit_boundary(self):
        responses = [tool_call("context_sufficiency_check", {"context_status": "sufficient"}),
                     tool_call("write_file", {"path": "unrelated.txt", "content": "blocked"}),
                     {"role": "assistant", "content": "Cannot complete safely.", "tool_calls": []}]
        result = self.run_greenfield_worker(script=lambda *_: responses.pop(0))
        self.assertTrue(result["impact_authorized"])
        # Legacy greenfield scope is enforced at precommit, not per write.
        # A synthetic passing verification input must not override that audit.
        self.assertTrue((self.root / "unrelated.txt").exists())
        commit = mini._commit_verified_leaf(
            self.task, self.contract, result, {}, {}, {"passed": True}, {},
        )
        self.assertEqual(commit["status"], "failed")
        self.assertFalse(commit["impact_comparison"]["passed"])
        self.assertTrue(commit["impact_comparison"]["out_of_scope"])
        self.assertFalse((self.root / "unrelated.txt").exists())


if __name__ == "__main__":
    unittest.main()
