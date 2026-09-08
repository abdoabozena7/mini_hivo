import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import context_sufficiency as stage7


class ContextSufficiencyGateTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "workspace": mini.WORKSPACE,
            "run": mini.RUN,
            "run_id": mini.RUN_ID,
            "active_contract": mini.ACTIVE_CONTRACT,
            "active_tool_contract": mini.ACTIVE_TOOL_CONTRACT,
            "active_gate": mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE,
        }
        self._temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self._temp.name)
        mini.reset_run("context-gate-test")
        mini.ACTIVE_TOOL_CONTRACT = {"task_id": "gate-test", "goal": "preserve the task"}

    def tearDown(self):
        mini.WORKSPACE = self._saved["workspace"]
        mini.RUN = self._saved["run"]
        mini.RUN_ID = self._saved["run_id"]
        mini.ACTIVE_CONTRACT = self._saved["active_contract"]
        mini.ACTIVE_TOOL_CONTRACT = self._saved["active_tool_contract"]
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = self._saved["active_gate"]
        self._temp.cleanup()

    @staticmethod
    def _anchor():
        return {
            "root_goal": "Ship the token refresh fix without changing the public API",
            "parent_goal": "Repair token refresh behavior",
            "local_task": "Update refresh_token implementation",
            "requirements": ["callers continue to receive the declared token value"],
            "constraints": ["preserve the existing return contract"],
            "allowed_inspection_paths": ["src/auth.py", "tests/test_auth.py"],
        }

    @staticmethod
    def _tool_response(name, arguments):
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }],
        }

    def test_sufficient_initial_packet_is_cheap_and_authorizes_mutation(self):
        provider_calls = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[{
                "kind": "contract", "source_identity": "src/auth.py:10",
                "excerpt": "refresh_token returns a string token.",
                "claim_key": "refresh_token.return", "claim_value": "string",
            }],
            evidence_provider=lambda request, context: provider_calls.append(request),
        )

        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "The contract and dependency evidence establish the return behavior.",
        })

        self.assertTrue(result["mutation_allowed"])
        self.assertEqual(result["lifecycle_state"], stage7.MUTATION_ALLOWED)
        self.assertEqual(provider_calls, [])

    def test_missing_contract_is_completed_before_mutation(self):
        requests = []
        mutation_calls = []
        responses = [
            self._tool_response("context_sufficiency_check", {
                "context_status": "insufficient",
                "reason": "The public return contract is absent from the initial packet.",
                "needed_evidence": [{
                    "kind": "contract", "target": "refresh_token return value",
                    "why": "Need the public contract to avoid changing callers' expected return type.",
                }],
            }),
            self._tool_response("context_sufficiency_check", {
                "context_status": "sufficient",
                "reason": "The returned contract resolves the implementation's return type.",
            }),
            self._tool_response("edit_file", {
                "path": "src/auth.py", "old": "old", "new": "new",
            }),
            self._tool_response("run_command", {"command": "python -m unittest"}),
            {"role": "assistant", "content": "completed", "tool_calls": []},
        ]

        def provider(request, _context):
            requests.append(request)
            return [{
                "kind": "contract", "target": request["target"],
                "source_identity": "src/auth.py:10",
                "excerpt": "refresh_token returns a string token.",
                "purpose": request["why"],
                "claim_key": "refresh_token.return", "claim_value": "string",
                "authoritative": True,
            }]

        def run_tool(name, arguments, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(arguments, role=role, task_id="contract")
            if name == "edit_file":
                mutation_calls.append((name, arguments))
            return "ok"

        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Update refresh_token implementation", {}, role="Builder", task_id="contract",
                extra_context="INITIAL BOUNDED PACKET: implementation only",
                context_sufficiency_enabled=True,
                context_anchor=self._anchor(),
                context_evidence_provider=provider,
                max_steps=5,
            )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["kind"], "contract")
        self.assertTrue(mutation_calls)
        self.assertTrue(result["mutation_authorized"])
        self.assertEqual(result["context_sufficiency"]["anchor"]["root_goal"], self._anchor()["root_goal"])

    def test_missing_caller_expectation_requests_narrow_reasoned_evidence(self):
        calls = []
        gate = stage7.ContextSufficiencyGate(self._anchor(), evidence_provider=lambda request, context: calls.append(request) or [])
        result = gate.evaluate({
            "context_status": "insufficient",
            "reason": "The implementation is present but caller expectations are not shown.",
            "needed_evidence": [{
                "kind": "callers", "target": "refresh_token consumers",
                "why": "Need to verify whether callers consume a string token or a structured refresh result.",
            }],
        })

        self.assertEqual(calls[0]["kind"], "callers")
        self.assertEqual(calls[0]["target"], "refresh_token consumers")
        self.assertIn("callers", calls[0]["why"])
        self.assertLessEqual(result["working_evidence_chars"], stage7.MAX_CONTEXT_EVIDENCE_CHARS)

    def test_goal_anchor_survives_completion(self):
        anchor = self._anchor()
        gate = stage7.ContextSufficiencyGate(
            anchor,
            evidence_provider=lambda request, context: [{
                "kind": request["kind"], "target": request["target"],
                "source_identity": "src/auth.py:20", "excerpt": "caller uses token",
            }],
        )
        before = gate.snapshot()
        gate.evaluate({
            "context_status": "insufficient",
            "reason": "Need the caller contract before changing the implementation.",
            "needed_evidence": [{
                "kind": "callers", "target": "refresh_token caller",
                "why": "Need the caller's expected value shape before editing the return path.",
            }],
        })
        after = gate.snapshot()

        self.assertEqual(after["anchor"], before["anchor"])
        self.assertEqual(after["anchor_hash"], before["anchor_hash"])
        self.assertEqual(after["anchor"]["local_task"], "Update refresh_token implementation")
        self.assertNotEqual(after["working_evidence"], before["working_evidence"])

    def test_completion_budget_is_bounded_and_fails_closed(self):
        calls = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            evidence_provider=lambda request, context: calls.append(request) or [],
        )
        decision = {
            "context_status": "insufficient",
            "reason": "The required contract remains unresolved.",
            "needed_evidence": [{
                "kind": "contract", "target": "refresh_token contract",
                "why": "Need the return contract to resolve the mutation safely.",
            }],
        }
        result = None
        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS + 1):
            result = gate.evaluate(decision)

        self.assertEqual(len(calls), stage7.MAX_CONTEXT_COMPLETION_ROUNDS)
        self.assertTrue(result["final"])
        self.assertEqual(result["failure_code"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_allowed"])

    def test_contradictory_evidence_requires_authoritative_resolution(self):
        requests = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[
                {"kind": "caller", "source_identity": "src/a.py:1", "excerpt": "expects string", "claim_key": "refresh.return", "claim_value": "string"},
                {"kind": "test", "source_identity": "tests/test_a.py:1", "excerpt": "expects object", "claim_key": "refresh.return", "claim_value": "object"},
            ],
            evidence_provider=lambda request, context: requests.append(request) or [],
        )
        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "There is enough text to edit.",
        })

        self.assertFalse(result["mutation_allowed"])
        self.assertEqual(requests[0]["kind"], "authoritative_contract")
        self.assertIn("conflict", result["reason"])

        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS):
            result = gate.evaluate({
                "context_status": "sufficient",
                "reason": "The contradiction remains unresolved.",
            })
        self.assertEqual(result["failure_code"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_allowed"])

    def test_runtime_rejects_mutation_attempt_before_gate(self):
        mutation_calls = []
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = stage7.ContextSufficiencyGate(self._anchor())
        direct_block = mini.run_tool(
            "edit_file", {"path": "src/auth.py", "old": "old", "new": "new"}, role="Builder",
        )
        self.assertIn("CONTEXT_SUFFICIENCY_REQUIRED", direct_block)
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = None
        responses = [
            self._tool_response("edit_file", {
                "path": "src/auth.py", "old": "old", "new": "new",
            }),
            {"role": "assistant", "content": "I have enough context", "tool_calls": []},
        ]

        def run_tool(name, arguments, role="Builder"):
            if name in {"edit_file", "write_file", "edit_file_range"}:
                mutation_calls.append(name)
            return "unexpected tool execution"

        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Change the implementation", {}, role="Builder", task_id="blocked",
                context_sufficiency_enabled=True, context_anchor=self._anchor(), max_steps=2,
            )

        self.assertEqual(mutation_calls, [])
        self.assertEqual(result["failure_type"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_authorized"])

    def test_evidence_completion_replaces_slots_and_stays_bounded(self):
        counter = {"round": 0}

        def provider(request, context):
            counter["round"] += 1
            return [{
                "kind": request["kind"], "target": request["target"],
                "source_identity": f"src/{counter['round']}.py:1",
                "excerpt": "semantic evidence " * 20,
            } for _ in range(stage7.MAX_EVIDENCE_REQUESTS_PER_ROUND)]

        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[{
                "kind": "initial", "source_identity": f"src/initial-{i}.py",
                "excerpt": "initial fact " * 10,
            } for i in range(stage7.MAX_CONTEXT_EVIDENCE_ITEMS)],
            evidence_provider=provider,
        )
        decision = {
            "context_status": "insufficient",
            "reason": "Need the semantic dependency before the edit.",
            "needed_evidence": [{
                "kind": "definition", "target": "refresh_token return type",
                "why": "Need the type definition to preserve interface compatibility.",
            }],
        }
        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS):
            gate.evaluate(decision)
        snapshot = gate.snapshot()

        self.assertLessEqual(snapshot["working_evidence_count"], stage7.MAX_CONTEXT_EVIDENCE_ITEMS)
        self.assertLessEqual(snapshot["working_evidence_chars"], stage7.MAX_CONTEXT_EVIDENCE_CHARS)
        self.assertLessEqual(len(snapshot["history"]), stage7.MAX_CONTEXT_COMPLETION_ROUNDS + 1)
        self.assertEqual(snapshot["anchor_hash"], stage7.canonical_hash(snapshot["anchor"]))

    def test_gate_disabled_preserves_existing_worker_tool_projection(self):
        responses = [{"role": "assistant", "content": "done", "tool_calls": []}]
        seen = []

        def ask(messages, tools=None, **_kwargs):
            seen.append({item["function"]["name"] for item in tools or []})
            return responses[0]

        with patch.object(mini, "ask_ollama", side_effect=ask):
            result = mini.execute_agent_task(
                "Inspect the current implementation", {}, role="Builder", task_id="legacy",
                max_steps=1,
            )

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["context_sufficiency"])
        self.assertIn("write_file", seen[0])


if __name__ == "__main__":
    unittest.main()
