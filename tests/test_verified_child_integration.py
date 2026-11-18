import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo.integration_gate import FAIL
from hivo.integration_gate import INTEGRATION_EVIDENCE_UNAVAILABLE
from hivo.integration_gate import INTEGRATION_FAILED
from hivo.integration_gate import INTEGRATION_NOT_READY
from hivo.integration_gate import NOT_READY_CHILD_FAILURE
from hivo.integration_gate import NOT_READY_COVERAGE_GAP
from hivo.integration_gate import NOT_READY_PROVENANCE_VIOLATION
from hivo.integration_gate import NOT_READY_STALE_AUTHORITY
from hivo.integration_gate import NOT_READY_STALE_EVIDENCE
from hivo.integration_gate import PARENT_VERIFIED
from hivo.integration_gate import PASS
from hivo.integration_gate import SKIPPED_NOT_APPLICABLE
from hivo.integration_gate import aggregate_parent_integration
from hivo.integration_gate import assess_integration_readiness
from hivo.integration_gate import create_verified_child_receipt
from hivo.integration_gate import receipt_contains_private_transcript
from hivo.integration_gate import receipt_freshness
from hivo.integration_gate import validate_verified_child_receipt


class VerifiedChildIntegrationGateTests(unittest.TestCase):
    """V21 Stage 5B is deterministic and does not invoke a model."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.temp.name)
        (self.root / "src").mkdir()
        (self.root / "tests").mkdir()
        self.write("src/a.js", "export const a = 1;\n")
        self.write("src/b.js", "export const b = 1;\n")
        self.write("tests/a.test.js", "const a = require('../src/a.js'); test('a', () => a);\n")
        self.write("tests/b.test.js", "const b = require('../src/b.js'); test('b', () => b);\n")
        self.write("tests/integration.test.js", "test('integration', () => {});\n")
        self.parent = {
            "id": "PARENT",
            "goal": "integrate the approved responsibilities",
            "integration_routes": [{
                "kind": "INTEGRATION_TEST", "required": True, "applicable": True,
                "target": "tests/integration.test.js", "result": "PENDING",
            }, {
                "kind": "BROWSER", "required": False, "applicable": False,
                "target": None, "result": SKIPPED_NOT_APPLICABLE,
            }],
        }
        self.parent_contract = {
            "contract_hash": "PARENT-CONTRACT",
            "plan_hash": "PARENT-PLAN",
            "execution_contract_id": "PARENT",
        }
        self.plan = [
            {"child_id": "A", "required": True, "execution_contract_id": "EXEC-A",
             "contract_hash": "CONTRACT-A", "plan_node_ids": ["NODE-A"], "owned_plan_node_ids": ["NODE-A"]},
            {"child_id": "B", "required": True, "execution_contract_id": "EXEC-B",
             "contract_hash": "CONTRACT-B", "plan_node_ids": ["NODE-B"], "owned_plan_node_ids": ["NODE-B"]},
        ]

    def tearDown(self):
        self.temp.cleanup()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def child(self, child_id, source, *, status="done", imports=None, focused=None):
        focused = focused or f"tests/{child_id.lower()}.test.js"
        contract_hash = f"CONTRACT-{child_id}"
        task = {
            "id": child_id, "parent": "PARENT", "status": status,
            "goal": f"Implement {child_id}", "done_when": [f"{child_id} is verified"],
            "plan_node_ids": [f"NODE-{child_id}"], "owned_plan_node_ids": [f"NODE-{child_id}"],
            "execution_contract_id": f"EXEC-{child_id}",
            "execution_contract": {
                "execution_contract_id": f"EXEC-{child_id}",
                "contract_hash": contract_hash, "plan_hash": "PARENT-PLAN",
                "plan_node_ids": [f"NODE-{child_id}"], "owned_plan_node_ids": [f"NODE-{child_id}"],
                "allowed_mutation_paths": [source],
                "done_when": [f"{child_id} is verified"],
            },
        }
        routes = [{
            "kind": "FOCUSED_TEST", "required": True, "applicable": True,
            "target": focused, "result": "PENDING",
        }, {
            "kind": "SYNTAX_STATIC_GATE", "required": True, "applicable": True,
            "target": source, "result": "PENDING",
        }, {
            "kind": "BROWSER", "required": False, "applicable": False,
            "target": None, "result": SKIPPED_NOT_APPLICABLE,
        }]
        evidence = [{
            "tool": "run_command", "target": f"node {focused}",
            "result": "[exit_code=0] focused test passed",
        }]
        aggregation = {
            "passed": status == "done", "evidence_available": status == "done",
            "failure_codes": [] if status == "done" else ["REQUIRED_VERIFICATION_FAILED"],
            "actual_passes": [dict(route, result=PASS) for route in routes[:2]] if status == "done" else [],
            "actual_failures": [] if status == "done" else [dict(routes[0], result=FAIL)],
            "skipped_not_applicable": [routes[2]], "verification_routes": routes,
        }
        result = {
            "status": status, "summary": f"{child_id} result",
            "gate": {"verification_aggregation": aggregation},
            "builder": {"status": status, "tool_evidence": evidence},
        }
        if imports:
            self.write(f"tests/{child_id.lower()}_shared.test.js", imports)
            focused = f"tests/{child_id.lower()}_shared.test.js"
            result["builder"]["tool_evidence"] = [{
                "tool": "run_command", "target": f"node {focused}",
                "result": "[exit_code=0] focused test passed",
            }]
            routes[0]["target"] = focused
            aggregation["actual_passes"] = [routes[0]] if status == "done" else []
            aggregation["verification_routes"] = routes
        return task, result

    def receipt(self, child_id="A", source="src/a.js", **kwargs):
        task, result = self.child(child_id, source, **kwargs)
        receipt = create_verified_child_receipt(
            task, result, parent_id="PARENT", parent_contract=self.parent_contract,
            workspace=self.root,
        )
        return task, result, receipt

    def readiness(self, pairs, receipts, plan=None, parent=None, **kwargs):
        return assess_integration_readiness(
            parent or self.parent, pairs, receipts,
            parent_contract=self.parent_contract,
            validated_child_plan=plan or self.plan,
            workspace=self.root,
            **kwargs,
        )

    def test_exact_v20_partial_tree_is_not_ready_and_never_integrates(self):
        a_task, a_result, a_receipt = self.receipt("A", "src/a.js")
        b_task, b_result = self.child("B", "src/b.js", status="too_broad")
        c_task, c_result = self.child("C", "src/a.js", status="failed")
        c_result.update({"failure_type": "ORCHESTRATION_FAILURE", "orchestration_failure": "MISSION_SEMANTIC_CONFLICT"})
        plan = self.plan + [{"child_id": "C", "required": True, "execution_contract_id": "EXEC-C",
                             "contract_hash": "CONTRACT-C", "plan_node_ids": ["NODE-C"], "owned_plan_node_ids": ["NODE-C"]}]
        gate = self.readiness(
            [(a_task, a_result), (b_task, b_result), (c_task, c_result)],
            {"A": a_receipt}, plan,
        )
        self.assertEqual(gate["status"], INTEGRATION_NOT_READY)
        self.assertEqual(gate["readiness"], "NOT_READY")
        self.assertEqual(gate["reason"], NOT_READY_CHILD_FAILURE)
        integrated = aggregate_parent_integration(self.parent, self.parent_contract, gate, [])
        self.assertEqual(integrated["status"], INTEGRATION_NOT_READY)
        self.assertEqual(integrated["integration_executor_calls"], 0)
        self.assertNotIn("parent_verification_receipt", integrated)

    def test_two_verified_and_one_failed_are_not_ready(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        c_task, c_result = self.child("C", "src/a.js", status="failed")
        plan = self.plan + [{"child_id": "C", "required": True, "plan_node_ids": ["NODE-C"], "owned_plan_node_ids": ["NODE-C"]}]
        gate = self.readiness(
            [(a[0], a[1]), (b[0], b[1]), (c_task, c_result)],
            {"A": a[2], "B": b[2]}, plan,
        )
        self.assertEqual(gate["reason"], NOT_READY_CHILD_FAILURE)

    def test_all_verified_fresh_are_ready(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        self.assertEqual(gate["readiness"], "READY")
        self.assertEqual(gate["model_calls"], 0)
        self.assertTrue(gate["coverage"]["complete"])

    def test_one_stale_receipt_is_not_ready_stale_evidence(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        self.write("src/a.js", "export const a = 2;\n")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        self.assertEqual(gate["reason"], NOT_READY_STALE_EVIDENCE)
        self.assertEqual(gate["freshness"]["stale_child_ids"], ["A"])

    def test_disjoint_mutation_remains_fresh(self):
        a = self.receipt("A", "src/a.js")
        self.write("src/b.js", "export const b = 2;\n")
        self.assertTrue(receipt_freshness(a[2], self.root)["fresh"])

    def test_shared_test_dependency_makes_receipt_stale(self):
        self.write(
            "tests/a_shared.test.js",
            "const a = require('../src/a.js'); const b = require('../src/b.js'); test('shared', () => a && b);\n",
        )
        task, result = self.child("A", "src/a.js", imports="const a = require('../src/a.js'); const b = require('../src/b.js'); test('shared', () => a && b);\n")
        receipt = create_verified_child_receipt(
            task, result, parent_id="PARENT", parent_contract=self.parent_contract,
            workspace=self.root,
        )
        self.write("src/b.js", "export const b = 2;\n")
        freshness = receipt_freshness(receipt, self.root)
        self.assertFalse(freshness["fresh"])
        self.assertIn("src/b.js", freshness["stale_paths"])

    def test_passing_leaves_do_not_make_failed_integration_pass(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        result = aggregate_parent_integration(
            self.parent, self.parent_contract, gate,
            [{"tool": "run_command", "target": "node tests/integration.test.js", "result": "[exit_code=1] assertion failed"}],
            workspace=self.root,
        )
        self.assertEqual(result["status"], INTEGRATION_FAILED)
        self.assertFalse(result["parent_verified"])

    def test_passing_leaves_and_passing_integration_create_parent_receipt(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        before = copy.deepcopy(a[2])
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        result = aggregate_parent_integration(
            self.parent, self.parent_contract, gate,
            [{"tool": "run_command", "target": "node tests/integration.test.js", "result": "[exit_code=0] integration passed"}],
            workspace=self.root,
        )
        self.assertEqual(result["status"], PARENT_VERIFIED)
        self.assertTrue(result["parent_verification_receipt"]["verified"])
        self.assertEqual(result["integration_evidence"][0]["tool"], "run_command")
        self.assertEqual(a[2], before)
        self.assertNotEqual(result["parent_verification_receipt"]["receipt_hash"], a[2]["receipt_hash"])
        self.assertNotEqual(result["parent_verification_receipt"]["receipt_hash"], self.parent_contract["contract_hash"])

    def test_no_integration_evidence_is_unavailable(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        result = aggregate_parent_integration(self.parent, self.parent_contract, gate, [], workspace=self.root)
        self.assertEqual(result["status"], INTEGRATION_EVIDENCE_UNAVAILABLE)
        self.assertFalse(result["parent_verified"])

    def test_optional_browser_skip_is_not_a_parent_pass(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        result = aggregate_parent_integration(
            self.parent, self.parent_contract, gate,
            [{"tool": "run_command", "target": "node tests/integration.test.js", "result": "[exit_code=0] integration passed"}],
            workspace=self.root,
        )
        browser = next(item for item in result["routes"] if item["kind"] == "BROWSER")
        self.assertEqual(browser["result"], SKIPPED_NOT_APPLICABLE)
        self.assertNotEqual(browser["result"], PASS)

    def test_optional_pass_does_not_satisfy_required_integration_route(self):
        parent = copy.deepcopy(self.parent)
        parent["integration_routes"].append({
            "kind": "OPTIONAL_AUXILIARY", "required": False, "applicable": True,
            "target": "tests/optional.test.js", "result": "PENDING",
        })
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness(
            [(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]}, parent=parent,
        )
        result = aggregate_parent_integration(
            parent, self.parent_contract, gate,
            [{"tool": "run_command", "target": "node tests/optional.test.js", "result": "[exit_code=0] optional passed"}],
            workspace=self.root,
        )
        self.assertEqual(result["status"], INTEGRATION_EVIDENCE_UNAVAILABLE)
        self.assertFalse(result["parent_verified"])

    def test_pending_required_route_is_not_real_child_verification_evidence(self):
        task, result = self.child("A", "src/a.js")
        aggregation = result["gate"]["verification_aggregation"]
        aggregation["passed"] = True
        aggregation["evidence_available"] = True
        aggregation["actual_passes"] = [dict(aggregation["verification_routes"][0], result="PENDING")]
        receipt = create_verified_child_receipt(
            task, result, parent_id="PARENT", parent_contract=self.parent_contract,
            workspace=self.root,
        )
        self.assertFalse(receipt["verified"])
        self.assertIn("REQUIRED_FOCUSED_TEST_NOT_PASSED", receipt["verification_failure_reasons"])

    def test_required_integration_target_missing_fails_closed(self):
        parent = copy.deepcopy(self.parent)
        parent["integration_routes"][0]["target"] = None
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]}, parent=parent)
        result = aggregate_parent_integration(parent, self.parent_contract, gate, [], workspace=self.root)
        self.assertEqual(result["status"], INTEGRATION_FAILED)
        self.assertEqual(result["failure_type"], "REQUIRED_INTEGRATION_TARGET_UNRESOLVED")

    def test_unauthorized_mutation_blocks_readiness(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness(
            [(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]},
            unauthorized_mutations=1,
        )
        self.assertEqual(gate["reason"], NOT_READY_PROVENANCE_VIOLATION)

    def test_dnt_violation_blocks_readiness(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness(
            [(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]},
            dnt_violations=1,
        )
        self.assertEqual(gate["reason"], NOT_READY_PROVENANCE_VIOLATION)

    def test_stale_authority_blocks_readiness(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        gate = self.readiness(
            [(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]},
            authority_valid=False, authority_failure="APPROVED_PLAN_STALE",
        )
        self.assertEqual(gate["reason"], NOT_READY_STALE_AUTHORITY)

    def test_receipt_hash_is_deterministic_and_sensitive(self):
        _, _, first = self.receipt("A", "src/a.js")
        _, _, second = self.receipt("A", "src/a.js")
        self.assertEqual(first["receipt_hash"], second["receipt_hash"])
        changed = copy.deepcopy(first)
        changed["verification_failure_reasons"] = ["changed"]
        changed["receipt_hash"] = create_verified_child_receipt(
            {"id": "A", "parent": "PARENT", "execution_contract": {"execution_contract_id": "EXEC-A", "contract_hash": "CONTRACT-A", "plan_hash": "PARENT-PLAN", "allowed_mutation_paths": ["src/a.js"]}},
            {"status": "done", "gate": {"verification_aggregation": {"passed": True, "evidence_available": True, "failure_codes": [], "actual_passes": [{"kind": "FOCUSED_TEST", "required": True, "applicable": True, "target": "tests/a.test.js", "result": "PASS"}], "verification_routes": [{"kind": "FOCUSED_TEST", "required": True, "applicable": True, "target": "tests/a.test.js", "result": "PENDING"}]}}, "builder": {"tool_evidence": [{"tool": "run_command", "target": "node tests/a.test.js", "result": "[exit_code=0]"}]}},
            parent_id="PARENT", parent_contract=self.parent_contract, workspace=self.root,
        )["receipt_hash"]
        self.assertNotEqual(changed["receipt_hash"], first["receipt_hash"])

    def test_receipt_authority_is_immutable_and_validated(self):
        task, result, receipt = self.receipt("A", "src/a.js")
        task_before = copy.deepcopy(task)
        contract_before = copy.deepcopy(self.parent_contract)
        self.assertEqual(task, task_before)
        self.assertEqual(self.parent_contract, contract_before)
        self.assertTrue(validate_verified_child_receipt(
            receipt, workspace=self.root,
            expected_authority={"execution_contract_id": "EXEC-A", "contract_hash": "CONTRACT-A", "plan_hash": "PARENT-PLAN", "parent_contract_hash": "PARENT-CONTRACT"},
        )["valid"])
        tampered = copy.deepcopy(receipt)
        tampered["authority"]["plan_hash"] = "OTHER"
        self.assertFalse(validate_verified_child_receipt(tampered, workspace=self.root)["valid"])

    def test_raw_worker_transcripts_are_excluded(self):
        task, result, receipt = self.receipt("A", "src/a.js")
        result["messages"] = [{"role": "assistant", "content": "private reasoning"}]
        result["thinking"] = "chain_of_thought"
        rebuilt = create_verified_child_receipt(task, result, parent_id="PARENT", parent_contract=self.parent_contract, workspace=self.root)
        self.assertFalse(receipt_contains_private_transcript(rebuilt))
        self.assertNotIn("messages", rebuilt)
        self.assertNotIn("thinking", rebuilt)

    def test_readiness_is_zero_model_and_uses_validated_coverage(self):
        a = self.receipt("A", "src/a.js")
        b = self.receipt("B", "src/b.js")
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("readiness called a model")):
            gate = self.readiness([(a[0], a[1]), (b[0], b[1])], {"A": a[2], "B": b[2]})
        self.assertEqual(gate["model_calls"], 0)
        self.assertEqual(gate["required_child_ids"], ["A", "B"])

    def test_stage5a_optional_browser_route_remains_non_applicable(self):
        mini.WORKSPACE = self.root
        mini.reset_run("recursive")
        task = {
            "id": "A", "goal": "Implement input behavior", "done_when": ["input is verified"],
            "scope_hint": ["src/a.js"], "execution_contract_child": {
                "goal": "Implement input behavior", "done_when": ["input is verified"],
                "allowed_mutation_paths": ["src/a.js"], "allowed_inspection_paths": ["src/a.js", "tests/a.test.js"],
            },
        }
        artifact = mini.analyze_verification_applicability(task, task, mini.inspect_repository())
        browser = next(item for item in artifact["verification_routes"] if item["kind"] == "BROWSER")
        self.assertFalse(browser["required"])
        self.assertFalse(browser["applicable"])
        self.assertIsNone(browser["target"])
        self.assertEqual(browser["result"], SKIPPED_NOT_APPLICABLE)
        self.assertEqual(artifact["model_calls"], 0)

    def test_benchmark_contract_and_no_new_model_role(self):
        self.assertEqual(mini.MODEL, "gemma4:e4b")
        self.assertNotIn("Integrator", mini.MODEL_POLICY.role_models())
        _, _, receipt = self.receipt("A", "src/a.js")
        self.assertEqual(receipt["provenance"]["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
