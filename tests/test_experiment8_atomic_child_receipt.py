import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo.atomic_child_receipt import create_atomic_child_receipt, validate_atomic_child_receipt
from hivo.integration_gate import create_verified_child_receipt, assess_integration_readiness, canonical_hash
from hivo.verification_routing import build_required_execution_verification_set


class AtomicChildReceiptTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "index.html").write_text("<script>const value=1;</script>", encoding="utf-8")
        self.task = {"id": "EXEC-001", "parent": "ROOT", "plan_node_ids": ["NODE-001"],
                     "execution_contract": {"execution_contract_id": "EXEC-001", "contract_hash": "contract",
                                            "plan_hash": "plan", "allowed_mutation_paths": ["index.html"],
                                            "plan_node_ids": ["NODE-001"], "requirement_ids": ["REQ-001"]}}
        self.routes = [{"kind": kind, "required": True, "applicable": True,
                        "target": "index.html", "result": "PASS"}
                       for kind in ("SYNTAX_STATIC_GATE", "BROWSER")]
        self.artifact = {"child_id": "EXEC-001", "verification_routes": self.routes}
        self.aggregation = {"passed": True, "evidence_available": True, "failure_codes": [],
                            "actual_passes": self.routes, "verification_routes": self.routes,
                            "required_execution_verification_set": build_required_execution_verification_set(self.artifact)}
        self.evidence = [{"tool": "verify_web_app", "target": "index.html", "result": '{"passed":true}'}]
        self.result = {"status": "done", "verification_applicability": self.artifact,
                       "gate": {"verification_aggregation": self.aggregation}, "verification_evidence": self.evidence}

    def receipt(self, **kwargs):
        return create_atomic_child_receipt(
            self.task, self.result, verification_applicability=self.artifact,
            verification_aggregation=self.aggregation, verification_evidence=self.evidence,
            workspace=self.workspace, **kwargs)

    def test_same_pass_evidence_becomes_valid_receipt_and_parent_coverage(self):
        baseline = create_verified_child_receipt(self.task, self.result, workspace=self.workspace)
        self.assertFalse(baseline["verified"])
        self.assertIn("EXECUTION_VERIFICATION_CLOSURE_MISSING", baseline["verification_failure_reasons"])
        receipt = self.receipt()
        self.assertTrue(create_atomic_child_receipt(self.task, self.result, workspace=self.workspace)["verified"])
        self.assertTrue(validate_atomic_child_receipt(receipt, workspace=self.workspace)["verified"])
        readiness = assess_integration_readiness(
            {"id": "ROOT"}, [(self.task, self.result)], {"EXEC-001": receipt}, workspace=self.workspace,
            validated_child_plan=[{"child_id": "EXEC-001", "required": True, "plan_node_ids": ["NODE-001"]}])
        self.assertEqual(readiness["readiness"], "READY")
        self.assertEqual(readiness["coverage"]["received_coverage_ids"], ["NODE-001"])
        self.assertEqual(receipt["verification_evidence_hash"], canonical_hash(receipt["verification_evidence"]))
        self.assertEqual(receipt["contract_hash"], "contract")

    def test_authority_bound_missing_closure_still_blocks(self):
        self.routes[1].update({"authority_id": "VER-1", "authority_type": "APPROVED"})
        self.aggregation["required_execution_verification_set"] = build_required_execution_verification_set(self.artifact)
        self.assertFalse(self.receipt()["verified"])

    def test_failure_or_scope_violation_cannot_be_promoted(self):
        self.aggregation["passed"] = False
        self.assertFalse(self.receipt()["verified"])
        self.aggregation["passed"] = True
        self.assertFalse(self.receipt(scope_violations=1)["verified"])
        self.assertFalse(self.receipt(authority_valid=False)["verified"])

    def test_evidence_coverage_and_subject_tampering_rejected_even_if_rehashed(self):
        for field, value in (("verification_evidence_hash", "bad"), ("covered_node_ids", []),
                             ("subject_after_hash", "bad"), ("contract_hash", "bad")):
            receipt = self.receipt()
            receipt[field] = value
            receipt["receipt_hash"] = canonical_hash({k: v for k, v in receipt.items() if k != "receipt_hash"})
            self.assertFalse(validate_atomic_child_receipt(receipt, workspace=self.workspace)["valid"], field)
        receipt = self.receipt()
        (self.workspace / "index.html").write_text("changed", encoding="utf-8")
        self.assertFalse(validate_atomic_child_receipt(receipt, workspace=self.workspace)["valid"])

    def invoke_mark(self, fail_persistence=False):
        events = []
        run = {"stage5b_enabled": True, "child_receipt_policy": "atomic_verified",
               "planning_route": "decomposition_first_recursive"}
        with patch.object(mini, "WORKSPACE", self.workspace), patch.object(mini, "RUN", run), \
                patch.object(mini, "TASKS", {"ROOT": {}}), \
                patch.object(mini, "_authority_terminal_failure", return_value=None), \
                patch.object(mini, "update_task_ledger"), \
                patch.object(mini, "record_run_event", side_effect=lambda kind, **fields: events.append({"kind": kind, **fields})):
            if fail_persistence:
                with patch.object(mini, "persist_atomic_child_receipt", side_effect=OSError("disk failed")):
                    mini._mark_task_result(self.task, self.result, count=False)
            else:
                mini._mark_task_result(self.task, self.result, count=False)
                mini._mark_task_result(self.task, self.result, count=False)
        return run, events

    def test_success_event_references_persisted_authority_once(self):
        run, events = self.invoke_mark()
        receipt = run["child_receipts"]["EXEC-001"]
        stored = json.loads(Path(self.result["verified_child_receipt_path"]).read_text(encoding="utf-8"))
        self.assertEqual(stored, receipt)
        verified = [event for event in run["experiment_events"] if event["kind"] == "CHILD_VERIFIED"]
        self.assertEqual(len(verified), 1)
        self.assertEqual(verified[0]["receipt_hash"], receipt["receipt_hash"])
        self.assertEqual(run["verified_child_receipts_created"], 1)

    def test_no_success_event_for_failed_or_missing_receipt(self):
        self.aggregation["passed"] = False
        run, _ = self.invoke_mark()
        self.assertEqual(self.result["status"], "failed")
        self.assertFalse(any(e["kind"] == "CHILD_VERIFIED" for e in run.get("experiment_events", [])))

    def test_persistence_failure_prevents_success_publication(self):
        run, _ = self.invoke_mark(fail_persistence=True)
        self.assertEqual(self.result["failure_type"], "CHILD_RECEIPT_PERSISTENCE_FAILED")
        self.assertEqual(self.result["status"], "failed")
        self.assertNotIn("EXEC-001", run.get("child_receipts", {}))
        self.assertFalse(any(e["kind"] == "CHILD_VERIFIED" for e in run.get("experiment_events", [])))


if __name__ == "__main__":
    unittest.main()
