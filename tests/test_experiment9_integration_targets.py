import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo.integration_gate import assess_integration_readiness, create_verified_child_receipt
from hivo.integration_targets import resolve_integration_targets, resolved_readiness


class IntegrationTargetTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        (self.workspace / "index.html").write_text("<html><title>game</title></html>", encoding="utf-8")
        self.parent = {"id": "ROOT", "goal": "Allow the Q key to restart the game after game over or win, preserving keyboard and touch controls."}
        self.contract = {"source_requirements": [{"requirement_id": "REQ-1", "text": self.parent["goal"]}]}
        self.child = {"id": "CHILD", "parent": "ROOT", "execution_contract": {
            "execution_contract_id": "CHILD", "contract_hash": "hash", "plan_node_ids": ["NODE-1"],
            "allowed_mutation_paths": ["index.html"]}}
        route = {"kind": "BROWSER", "target": "index.html", "required": True, "applicable": True, "result": "PASS"}
        self.child_result = {"status": "done", "gate": {"verification_aggregation": {
            "passed": True, "evidence_available": True, "verification_routes": [route], "actual_passes": [route]}}}
        self.receipt = create_verified_child_receipt(self.child, self.child_result, workspace=self.workspace)
        self.receipts = {"CHILD": self.receipt}
        self.readiness = assess_integration_readiness(
            self.parent, [(self.child, self.child_result)], self.receipts, workspace=self.workspace,
            validated_child_plan=[{"child_id": "CHILD", "required": True, "plan_node_ids": ["NODE-1"]}],
            parent_verification_applicability={"verification_routes": [route]})
        self.assertEqual(self.readiness["readiness"], "READY")

    def resolve(self, parent=None, contract=None, snapshot=None, readiness=None):
        return resolve_integration_targets(parent or self.parent, contract or self.contract,
                                           readiness or self.readiness, self.receipts,
                                           workspace=self.workspace, repository_snapshot=snapshot)

    def test_verified_browser_location_resolves_but_never_copies_child_pass(self):
        resolution = self.resolve()
        self.assertEqual(resolution["status"], "RESOLVED")
        self.assertEqual(resolution["resolutions"][0]["source"], "verified_child_browser_target")
        self.assertEqual(resolution["routes"][0]["target"], "index.html")
        self.assertEqual(resolution["routes"][0]["result"], "PENDING")
        self.assertEqual(len(resolution["executions"]), 1)
        self.assertEqual(resolution["child_evidence_reused_as_proof"], 0)
        self.assertNotEqual(resolved_readiness(self.readiness, resolution)["readiness_hash"], self.readiness["readiness_hash"])
        self.assertIsNone(self.readiness["integration_routes"][0]["target"])

    def test_explicit_target_and_parent_surface_precede_child_location(self):
        (self.workspace / "parent.html").write_text("<html></html>", encoding="utf-8")
        for key, value, source in (("integration_test_target", "parent.html", "explicit_parent_target"),
                                   ("integration_surfaces", [{"path": "parent.html"}], "parent_integration_surface")):
            parent = dict(self.parent, **{key: value})
            resolution = self.resolve(parent=parent)
            self.assertEqual(resolution["resolutions"][0]["target"], "parent.html")
            self.assertEqual(resolution["resolutions"][0]["source"], source)

    def test_explicit_missing_or_outside_target_is_not_replaced(self):
        for target in ("missing.html", "../outside.html"):
            resolution = self.resolve(parent=dict(self.parent, integration_test_target=target))
            self.assertEqual(resolution["status"], "UNRESOLVED")

    def test_saved_backup_is_not_an_integrated_project_target(self):
        backup = self.workspace / ".agent_backups" / "index.html"
        backup.parent.mkdir()
        backup.write_text("<html>old application</html>", encoding="utf-8")
        result = self.resolve(parent=dict(self.parent, integration_test_target=".agent_backups/index.html"))
        self.assertEqual(result["status"], "UNRESOLVED")

    def test_project_entrypoint_fallback_and_ambiguity(self):
        readiness = dict(self.readiness, child_receipts=[], integration_routes=[self.readiness["integration_routes"][0]])
        result = self.resolve(readiness=readiness, snapshot={"entrypoints": ["index.html"]})
        self.assertEqual(result["resolutions"][0]["source"], "project_entrypoint")
        for name in ("a.html", "b.html"):
            (self.workspace / name).write_text("<html></html>", encoding="utf-8")
        result = self.resolve(readiness=readiness, snapshot={"entrypoints": ["a.html", "b.html"]})
        self.assertEqual(result["status"], "UNRESOLVED")

    def test_stale_receipt_or_not_ready_parent_cannot_execute(self):
        self.assertEqual(self.resolve(readiness=dict(self.readiness, readiness="NOT_READY"))["reason"], "PARENT_NOT_READY")
        (self.workspace / "index.html").write_text("changed", encoding="utf-8")
        self.assertEqual(self.resolve(snapshot={"entrypoints": ["index.html"]})["reason"], "STALE_OR_INVALID_CHILD_RECEIPT")

    def test_explicit_test_command_is_one_executable_target(self):
        result = self.resolve(parent=dict(self.parent, integration_test_target="npm test"))
        self.assertEqual(result["resolutions"][0]["tool"], "run_command")
        self.assertEqual(result["executions"][0]["command"], "npm test")

    def aggregate(self, browser_result, *, ready=None):
        task = copy.deepcopy(self.parent)
        run = {"integration_target_policy": "resolved", "child_receipts": self.receipts}
        # A historical child PASS explicitly offered as integration evidence
        # must never satisfy this variant's parent checks.
        completed = [{"task": self.child, "result": dict(self.child_result,
                      integration_evidence=[{"tool": "verify_web_app", "target": "index.html", "result": {"passed": True}}])}]
        with patch.object(mini, "WORKSPACE", self.workspace), patch.object(mini, "RUN", run), \
                patch.object(mini, "record_run_event"), patch.object(mini, "_start_parent_integration"), \
                patch.object(mini, "_finish_parent_integration"), patch.object(mini, "_stage5c_enabled", return_value=False), \
                patch.object(mini, "verify_browser_application", **(
                    {"side_effect": browser_result} if isinstance(browser_result, list)
                    else {"return_value": browser_result})) as browser:
            result = mini._aggregate_stage5b_parent(task, self.contract, completed, {},
                        repo_snapshot={"entrypoints": ["index.html"]}, root=True, readiness=ready or self.readiness)
        return result, run, browser

    def test_fresh_parent_checks_must_pass_and_proof_is_new(self):
        profile = mini.infer_web_profile(self.parent["goal"], {})
        payload = {"passed": True, "behavior_test_executed": True,
                   "interaction_checks": [{"name": name, "executed": True, "passed": True}
                                          for name in profile.required_interactions]}
        result, run, browser = self.aggregate(payload)
        self.assertEqual(result["status"], "done")
        self.assertEqual(browser.call_count, 1)
        self.assertIn("Q key", browser.call_args.kwargs["evidence"]["verification_requirement"])
        record = run["parent_verification_runs"][0]
        self.assertEqual(record["covered_requirement_ids"], ["REQ-1"])
        self.assertEqual(record["child_evidence_reused_as_proof"], 0)
        self.assertNotEqual(record["evidence_hash"], self.receipt["receipt_hash"])
        self.assertEqual(result["parent_verification_receipt"]["integration_evidence"][0]["result"]["verification_id"], record["verification_id"])
        self.assertTrue(Path(record["artifact_path"]).is_file())

    def test_real_failure_beats_historical_child_pass(self):
        result, run, browser = self.aggregate({"passed": False, "behavior_test_executed": True,
            "interaction_checks": [{"name": "restart_resets_state", "executed": True, "passed": False}]})
        self.assertEqual(browser.call_count, 1)
        self.assertEqual(result["integration_result"], "INTEGRATION_FAILED")
        self.assertEqual(run["parent_verification_runs"][0]["covered_requirement_ids"], [])

    def test_environment_unavailable_or_unexecuted_behavior_cannot_verify_parent(self):
        for payload in ({"passed": False, "environment_error": True},
                        {"passed": True, "behavior_test_executed": False, "interaction_checks": []}):
            result, _, _ = self.aggregate(payload)
            self.assertEqual(result["integration_result"], "INTEGRATION_EVIDENCE_UNAVAILABLE")
            self.assertNotIn("parent_verification_receipt", result)

    def test_success_at_one_target_cannot_cover_an_unavailable_required_target(self):
        (self.workspace / "parent.html").write_text("<html></html>", encoding="utf-8")
        self.readiness["integration_routes"][1]["target"] = "parent.html"
        profile = mini.infer_web_profile(self.parent["goal"], {})
        passed = {"passed": True, "behavior_test_executed": True,
                  "interaction_checks": [{"name": name, "executed": True, "passed": True}
                                         for name in profile.required_interactions]}
        result, _, browser = self.aggregate([passed, {"passed": False, "environment_error": True}])
        self.assertEqual(browser.call_count, 2)
        self.assertEqual(result["integration_result"], "INTEGRATION_EVIDENCE_UNAVAILABLE")
        self.assertEqual(result["parent_requirement_coverage"]["covered_requirement_ids"], [])

    def test_not_ready_never_calls_parent_verifier(self):
        result, _, browser = self.aggregate({"passed": True}, ready=dict(self.readiness, readiness="NOT_READY"))
        self.assertEqual(browser.call_count, 0)
        self.assertEqual(result["integration_result"], "INTEGRATION_NOT_READY")


if __name__ == "__main__":
    unittest.main()
