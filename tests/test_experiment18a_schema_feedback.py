"""Offline regression coverage for the advertised schema and rejected tool decisions."""
import copy
import json
import unittest
from unittest.mock import patch

import mini
from hivo import context_sufficiency as context
import test_greenfield_context_progress as greenfield


def request(kind="contract"):
    return {"context_status": "insufficient", "reason": "The artifact contract needs clarification.",
            "needed_evidence": [{"kind": kind, "target": "artifact.txt return contract",
                                 "why": "Determine the required artifact contents before editing."}]}


class EvidenceKindSchemaTests(unittest.TestCase):
    def test_advertised_kind_enum_matches_runtime_whitelist(self):
        schema = context.context_sufficiency_schema()
        kind = schema["properties"]["needed_evidence"]["items"]["properties"]["kind"]
        self.assertEqual(kind.get("enum"), sorted(context.EVIDENCE_REQUEST_KINDS))
        tool = next(t for t in mini.TOOLS if t["function"]["name"] == "context_sufficiency_check")
        self.assertEqual(tool["function"]["parameters"], schema)

    def test_all_supported_kinds_validate(self):
        for kind in sorted(context.EVIDENCE_REQUEST_KINDS):
            with self.subTest(kind=kind):
                self.assertTrue(context.validate_sufficiency_decision(request(kind))["valid"])

    def test_unsupported_kinds_and_malformed_requests_remain_invalid(self):
        for kind in ("invented_kind", "", None):
            with self.subTest(kind=kind):
                checked = context.validate_sufficiency_decision(request(kind))
                self.assertFalse(checked["valid"])
                self.assertTrue(any("kind must be one of" in e for e in checked["errors"]))
        malformed = request()
        malformed["needed_evidence"][0]["target"] = ""
        self.assertFalse(context.validate_sufficiency_decision(malformed)["valid"])


class InvalidDecisionFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.fixture = greenfield.GreenfieldContextProgressTests(
            "test_long_greenfield_mission_retains_gate_success_and_can_write")
        self.fixture.setUp()
        self.provider_calls = []
        self.gate = context.ContextSufficiencyGate(
            {"root_goal": "Create artifact.txt", "local_task": "Create approved output"},
            evidence_provider=lambda req, ctx: self.provider_calls.append(req) or [])
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = self.gate

    def tearDown(self):
        self.fixture.tearDown()

    def call(self, decision):
        return json.loads(mini._context_sufficiency_tool(decision, role="Repairer", task_id="1"))

    def assert_rejected_without_state_change(self, decision):
        before = copy.deepcopy(self.gate.snapshot())
        with patch.object(self.gate, "evaluate", wraps=self.gate.evaluate) as evaluate:
            result = self.call(decision)
            evaluate.assert_not_called()
        self.assertEqual(self.gate.snapshot(), before)
        self.assertTrue(result["errors"])
        self.assertEqual(result["context_status"], before["context_status"])
        self.assertEqual(result["lifecycle_state"], before["state"])
        self.assertEqual(result["mutation_allowed"], before["mutation_allowed"])
        self.assertEqual(result["failure_code"], before["failure_code"])
        self.assertEqual(result["round"], before["round"])
        self.assertEqual(result["request_count"], before["request_count"])
        self.assertEqual(result["anchor_hash"], before["anchor_hash"])
        self.assertIs(result.get("decision_valid"), False)
        feedback = context.feedback_for_result(result)
        self.assertIn("CONTEXT_DECISION_INVALID", feedback)
        self.assertIn("unchanged", feedback)
        self.assertNotIn("CONTEXT_SUFFICIENT:", feedback)
        return result

    def test_supported_request_reaches_existing_evidence_provider(self):
        self.call(request())
        self.assertEqual(len(self.provider_calls), 1)
        self.assertEqual(self.provider_calls[0]["kind"], "contract")
        self.assertFalse(self.gate.mutation_allowed)

    def test_invalid_request_before_authorization_does_not_grant_it(self):
        self.assert_rejected_without_state_change(request("invented_kind"))
        self.assertFalse(self.gate.mutation_allowed)
        self.assertIsNotNone(mini._context_gate_mutation_guard("write_file", role="Repairer"))
        self.assertEqual(self.provider_calls, [])
        self.assertFalse((self.fixture.root / "artifact.txt").exists())

    def test_invalid_request_after_authorization_preserves_authority(self):
        self.call({"context_status": "sufficient"})
        self.assertTrue(self.gate.mutation_allowed)
        for _ in range(4):
            self.assert_rejected_without_state_change(request("invented_kind"))
        self.assertEqual(self.provider_calls, [])
        self.assertIsNone(mini._context_gate_mutation_guard("write_file", role="Repairer"))
        with patch.object(mini, "ACTIVE_IMPACT_REQUIRED", True), \
                patch.object(mini, "ACTIVE_IMPACT_CONTRACT", None):
            self.assertIsNotNone(mini._impact_gate_mutation_guard("write_file", role="Repairer"))
        self.assertFalse((self.fixture.root / "artifact.txt").exists())

    def test_malformed_decision_after_authorization_does_not_change_state(self):
        self.call({"context_status": "sufficient"})
        for invalid in ({"context_status": "unknown"}, {"context_status": "sufficient", "extra": True}, []):
            with self.subTest(decision=invalid):
                self.assert_rejected_without_state_change(invalid)

    def test_invalid_input_preserves_existing_terminal_failure(self):
        for _ in range(self.gate.max_rounds + 1):
            self.gate.evaluate(request())
        self.assertIsNotNone(self.gate.snapshot()["failure_code"])
        result = self.assert_rejected_without_state_change(request("invented_kind"))
        self.assertFalse(result["mutation_allowed"])
        self.assertTrue(result["final"])


class InvalidDecisionWorkerRouteTests(unittest.TestCase):
    def test_invalid_decisions_are_not_counted_as_successful_repeated_checks(self):
        fixture = greenfield.GreenfieldContextProgressTests(
            "test_long_greenfield_mission_retains_gate_success_and_can_write")
        fixture.setUp()
        try:
            responses = [greenfield.tool_call("context_sufficiency_check", {"context_status": "sufficient"})]
            responses += [greenfield.tool_call("context_sufficiency_check", request("invented_kind")) for _ in range(4)]
            responses += [greenfield.tool_call("write_file", {"path": "artifact.txt", "content": "approved output"}),
                          {"role": "assistant", "content": "Done", "tool_calls": []}]
            result = fixture.run_greenfield_worker(script=lambda *args: responses.pop(0))
            self.assertEqual(result["status"], "done", result["summary"])
            self.assertTrue(result["impact_authorized"])
            self.assertEqual((fixture.root / "artifact.txt").read_text(), "approved output")
        finally:
            fixture.tearDown()
