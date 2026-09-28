import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from hivo.child_handoff_diagnostics import evidence_match_audit, trace_handoff
from hivo.verification_routing import aggregate_verification_evidence


class ChildHandoffDiagnosticTests(unittest.TestCase):
    def setUp(self):
        self.artifact = {"child_id": "CHILD", "verification_routes": [
            {"kind": "BROWSER", "required": True, "applicable": True, "target": "app.html", "result": "PENDING"}]}
        self.browser = {"passed": True, "behavior_test_executed": True, "verification_applicability": self.artifact}
        self.snapshot = {"task": {"id": "CHILD"}, "tool_contract": {}, "records_complete": True,
                         "builder": {"status": "done", "tool_evidence": [
                             {"tool": "run_file", "target": "app.html", "result": {"passed": True}}],
                             "context_sufficiency": {"context_status": "sufficient"}},
                         "falsifier": {"status": "done"}}

    def backend(self):
        def check(*args, on_start, **kwargs):
            on_start(target="app.html")
            return copy.deepcopy(self.browser)

        def gate(builder, falsifier, browser):
            aggregation = aggregate_verification_evidence(
                self.artifact, builder["tool_evidence"], browser)
            return {"passed": aggregation["passed"], "verification_aggregation": aggregation}

        return SimpleNamespace(
            _authority_terminal_failure=Mock(return_value=None),
            _context_sufficiency_failed=Mock(return_value=False), CONTEXT_INSUFFICIENT_FAILURE="CONTEXT_INSUFFICIENT",
            merged_verification_evidence=lambda b, f: b["tool_evidence"],
            analyze_verification_applicability=Mock(return_value=self.artifact),
            _verification_route=lambda a, k: a["verification_routes"][0], BROWSER_VERIFICATION="BROWSER",
            REQUIRED_VERIFICATION_TARGET_UNRESOLVED="REQUIRED_VERIFICATION_TARGET_UNRESOLVED",
            _combined_syntax_validation_failures=lambda *args: [], observed_browser_check=Mock(side_effect=check),
            evidence_gate=gate, classify_failure=Mock(return_value="IMPLEMENTATION_ERROR"))

    def test_existing_run_file_browser_mismatch_is_explained_without_fixing_it(self):
        before = copy.deepcopy(self.snapshot)
        result = trace_handoff(self.snapshot, self.backend())
        self.assertTrue(result["verification_started"])
        self.assertFalse(result["evidence_gate_passed"])
        self.assertEqual(result["first_blocker"], {"stage": "VERIFICATION_EVIDENCE_AGGREGATION", "reason": "INVALID_RECEIPT"})
        audit = result["evidence_match_audit"][0]
        self.assertEqual(audit["related_tools"], ["run_file"])
        self.assertEqual(audit["matched_tools"], [])
        self.assertTrue(audit["separate_browser_pass"])
        self.assertEqual(self.snapshot, before)
        self.assertNotIn("CHILD_VERIFIED_RECEIPT", [e["kind"] for e in result["events"]])

    def test_same_snapshot_has_same_gate_decision_across_repetitions(self):
        results = [trace_handoff(self.snapshot, self.backend()) for _ in range(5)]
        self.assertEqual(len({r["decision_hash"] for r in results}), 1)
        self.assertTrue(all(r["verification_started"] for r in results))

    def test_worker_context_failure_prevents_browser_and_is_not_relabelled(self):
        backend = self.backend()
        backend._context_sufficiency_failed.return_value = True
        result = trace_handoff(self.snapshot, backend)
        self.assertEqual(result["first_blocker"]["stage"], "WORKER_CONTEXT")
        backend.observed_browser_check.assert_not_called()
        backend.analyze_verification_applicability.assert_not_called()

    def test_missing_projection_records_cannot_be_treated_as_eligible(self):
        self.snapshot["records_complete"] = False
        backend = self.backend()
        result = trace_handoff(self.snapshot, backend)
        self.assertEqual(result["first_blocker"]["reason"], "HANDOFF_SNAPSHOT_INCOMPLETE")
        backend._authority_terminal_failure.assert_not_called()
        backend.observed_browser_check.assert_not_called()

    def test_invalid_authority_missing_target_and_not_applicable_do_not_execute(self):
        for failure in ("authority", "target", "applicability"):
            with self.subTest(failure=failure):
                backend = self.backend()
                if failure == "authority":
                    backend._authority_terminal_failure.return_value = "APPROVED_PLAN_STALE"
                elif failure == "target":
                    self.artifact["verification_routes"][0]["target"] = None
                else:
                    self.artifact["verification_routes"][0].update(required=False, applicable=False)
                result = trace_handoff(self.snapshot, backend)
                self.assertFalse(result["verification_started"])
                backend.observed_browser_check.assert_not_called()
                self.setUp()

    def test_matching_evidence_audit_retains_separate_browser_failure(self):
        self.snapshot["builder"]["tool_evidence"][0]["tool"] = "verify_web_app"
        self.browser["passed"] = False
        result = trace_handoff(self.snapshot, self.backend())
        # Existing aggregation behavior is observed as-is; diagnostic does
        # not substitute its own opinion for the verifier's gate.
        self.assertFalse(result["browser"]["passed"])
        self.assertFalse(result["evidence_match_audit"][0]["related_without_match"])

    def test_gate_pass_cannot_issue_receipt_or_claim_child_completion(self):
        self.snapshot["builder"]["tool_evidence"][0]["tool"] = "verify_web_app"
        result = trace_handoff(self.snapshot, self.backend())
        self.assertTrue(result["evidence_gate_passed"])
        self.assertIsNone(result["first_blocker"])
        self.assertEqual(result["events"][-1]["kind"], "RECEIPT_NOT_REPLAYED")


if __name__ == "__main__":
    unittest.main()
