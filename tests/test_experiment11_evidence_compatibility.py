import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo import evidence_compatibility as semantic
from hivo.atomic_child_receipt import create_atomic_child_receipt, validate_atomic_child_receipt
from hivo.integration_gate import fingerprint_dependency_paths
from hivo.verification_routing import aggregate_verification_evidence


class SemanticEvidenceCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "index.html").write_text("<script>const value=1;</script>", encoding="utf-8")
        self.requirements = [{"requirement_id": "REQ-001", "text":
                              "Allow the R key to restart the game after game over or win, while preserving existing keyboard and touch controls."}]
        self.subject = fingerprint_dependency_paths(self.workspace, ["index.html"])
        self.claims = semantic.required_claims(self.requirements, contract_hash="approved-contract", child_id="EXEC-001",
                                              target="index.html", subject_hash=self.subject["hash"], subject_paths=["index.html"])
        self.payload = {"resolved_entrypoint": "index.html", "passed": True, "behavior_test_executed": True,
                        "environment_error": False, "interaction_checks": [
                            {"name": name, "executed": True, "passed": True} for name in (
                                "keyboard_movement", "restart_resets_state", "goal_win_state", "touch_control")]}
        self.payload["interaction_checks"][1].update(input="r", cases=[
            {"setup": name, "precondition_met": True, "passed": True} for name in ("forceCollision", "forceWin")])
        self.artifact = {"child_id": "EXEC-001", "verification_routes": [
            {"kind": "BROWSER", "required": True, "applicable": True, "target": "index.html", "result": "PENDING"}]}
        self.raw = [{"tool": "run_file", "target": "index.html", "result": {"passed": True}}]

    def records(self, payload=None, tool="verify_web_app"):
        return semantic.normalize_browser_result(payload or self.payload, self.claims, tool=tool,
                                                 source="controller_tool_result", subject_before_hash=self.subject["hash"],
                                                 subject_after_hash=self.subject["hash"])

    def assess(self, records):
        return semantic.assess(self.claims, records, required_requirement_ids=["REQ-001"])

    def aggregate(self, records, artifact=None):
        return aggregate_verification_evidence(artifact or self.artifact, self.raw, self.payload,
                                               semantic_browser_evidence={"index.html": self.assess(records)})

    def test_same_obligation_behavior_and_target_accept_across_tools(self):
        records = self.records(tool="run_file") + self.records(tool="verify_web_app")
        self.assertEqual(self.assess(records)["status"], "PASS")
        self.assertEqual({r["provenance"]["tool"] for r in records}, {"run_file", "verify_web_app"})
        self.assertTrue(self.aggregate(records)["passed"])
        baseline = aggregate_verification_evidence(self.artifact, self.raw, self.payload)
        self.assertEqual(baseline["actual_failures"][0]["result"], "INVALID_RECEIPT")

    def test_same_file_different_behavior_rejected(self):
        payload = copy.deepcopy(self.payload)
        payload["interaction_checks"] = [{"name": "pause_freezes_state", "passed": True, "executed": True}]
        self.assertFalse(self.aggregate(self.records(payload))["passed"])

    def test_different_target_requirement_key_or_requirement_text_rejected(self):
        for field, value in (("target", "other.html"), ("requirement_id", "REQ-002"),
                             ("requirement_text_hash", "different-text"), ("contract_hash", "other-contract"),
                             ("child_id", "OTHER-CHILD")):
            records = copy.deepcopy(self.records())
            for record in records:
                record[field] = value
                record["record_hash"] = semantic.canonical_hash({k: v for k, v in record.items() if k != "record_hash"})
            self.assertFalse(self.aggregate(records)["passed"], field)
        payload = copy.deepcopy(self.payload)
        payload["interaction_checks"][1]["input"] = "q"
        self.assertFalse(self.aggregate(self.records(payload))["passed"])

    def test_page_load_prose_missing_execution_and_incomplete_cases_cannot_cover_behavior(self):
        for mutation in ("page_load", "not_executed", "one_terminal_case"):
            payload = copy.deepcopy(self.payload)
            if mutation == "page_load":
                payload["behavior_test_executed"] = False
            elif mutation == "not_executed":
                payload["interaction_checks"][1]["executed"] = False
            else:
                payload["interaction_checks"][1]["cases"] = payload["interaction_checks"][1]["cases"][:1]
            self.assertFalse(self.aggregate(self.records(payload))["passed"], mutation)
        self.assertEqual(semantic.normalize_browser_result("PASS all requirements", self.claims, tool="run_file",
                         source="controller_tool_result", subject_before_hash="x", subject_after_hash="x"), [])

    def test_real_fail_beats_compatible_pass_and_failed_browser_contract_stays_failed(self):
        payload = copy.deepcopy(self.payload)
        payload["passed"] = False
        payload["interaction_checks"][1]["passed"] = False
        self.assertFalse(self.aggregate(self.records() + self.records(payload))["passed"])

    def test_failed_terminal_case_cannot_hide_behind_summary_pass(self):
        payload = copy.deepcopy(self.payload)
        payload["interaction_checks"][1]["cases"][1]["passed"] = False
        self.assertFalse(self.aggregate(self.records(payload))["passed"])

    def test_stale_subject_and_tampered_record_rejected(self):
        records = self.records()
        records[0]["result"] = "FAIL"
        self.assertFalse(semantic.record_valid(records[0]))
        changed = semantic.normalize_browser_result(self.payload, self.claims, tool="run_file", source="controller_tool_result",
                                                    subject_before_hash="before", subject_after_hash="after")
        self.assertEqual(changed, [])
        changed_claims = copy.deepcopy(self.claims)
        for claim in changed_claims:
            claim["subject_hash"] = "new-current-subject"
        self.assertNotEqual(semantic.assess(changed_claims, self.records(), required_requirement_ids=["REQ-001"])["status"], "PASS")

    def test_authority_bound_browser_routes_retain_existing_receipt_gates(self):
        artifact = copy.deepcopy(self.artifact)
        artifact["verification_routes"][0].update(authority_id="APPROVED-VERIFY", authority_type="APPROVED")
        self.assertFalse(self.aggregate(self.records(), artifact)["passed"])

    def test_normalized_receipt_bound_to_approved_claims_and_current_source(self):
        contract = {"execution_contract_id": "EXEC-001", "contract_hash": "approved-contract", "plan_hash": "plan",
                    "allowed_mutation_paths": ["index.html"], "allowed_inspection_paths": ["index.html"],
                    "plan_node_ids": ["NODE-001"], "requirement_ids": ["REQ-001"], "requirements": self.requirements}
        task = {"id": "EXEC-001", "parent": "ROOT", "execution_contract": contract, "plan_node_ids": ["NODE-001"]}
        result = {"status": "done", "gate": {"verification_aggregation": self.aggregate(self.records())}}
        receipt = create_atomic_child_receipt(task, result, workspace=self.workspace, verification_applicability=self.artifact)
        self.assertTrue(validate_atomic_child_receipt(receipt, workspace=self.workspace, expected_requirements=self.requirements)["valid"])
        changed_requirements = [{"requirement_id": "REQ-001", "text": "Pause the game while Escape is pressed."}]
        self.assertFalse(validate_atomic_child_receipt(receipt, workspace=self.workspace, expected_requirements=changed_requirements)["valid"])
        rejected = create_atomic_child_receipt(task, result, workspace=self.workspace, verification_applicability=self.artifact, scope_violations=1)
        self.assertFalse(rejected["verified"])
        (self.workspace / "index.html").write_text("changed", encoding="utf-8")
        self.assertFalse(validate_atomic_child_receipt(receipt, workspace=self.workspace)["valid"])

    def test_runtime_collector_cannot_promote_python_stdout_as_browser_proof(self):
        with patch.object(mini, "RUN", {"semantic_evidence_policy": "compatible"}):
            records = mini._collect_semantic_browser_evidence("run_file", json.dumps(self.payload), task_id="EXEC-001",
                                                              source="controller_tool_result", requested_target="tests/test.py")
        self.assertEqual(records, [])


if __name__ == "__main__":
    unittest.main()
