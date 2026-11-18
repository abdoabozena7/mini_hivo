"""Provider-free Stage 6C-A approval-boundary regression tests."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hivo import approval_authority as authority
from hivo import execution_contracts as stage4


ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
BRAIN_DB = ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
EXPECTED_BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"


def _load(name, fallback=None):
    try:
        with (LIVE_ROOT / name).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


class ApprovalBoundExecutionAuthorizationTests(unittest.TestCase):
    """The test fixture never invokes Gemma, Worker, Verifier, or mutation tools."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load("final_plan.json", {})
        cls.context = _load("verified_planning_context.json", {})
        cls.freshness = _load("planning_context_freshness.json", {})
        cls.plan_validation = _load("plan_validation.json", {})
        cls.contractability = _load("stage4_contractability_audit.json", {})
        cls.reconciliation = _load("challenger_reconciliation.json", cls.plan.get("challenger_reconciliation", {}))
        cls.brain = authority.read_only_project_brain_identity(
            BRAIN_DB, cls.context.get("project_id"),
        )
        cls.state = {
            "task_id": cls.context.get("task_id"),
            "project_id": cls.context.get("project_id"),
            "planning_mode": cls.context.get("planning_mode"),
            "verified_planning_context": cls.context,
            "planning_context_hash": cls.context.get("planning_context_hash"),
            "brain_hash": cls.brain["logical_hash"],
            "subject_aggregate_hash": (cls.context.get("source_repository_fingerprint") or {}).get("hash"),
            "upstream_bindings": cls.plan.get("upstream_bindings", {}),
            "requirements": cls.plan.get("requirements", []),
            "coverage": cls.plan.get("coverage", []),
            "planning_context_freshness": cls.freshness,
            "plan_validation": cls.plan_validation,
            "stage4_contractability_audit": cls.contractability,
            "challenger_reconciliation": cls.reconciliation,
            "terminal_state": authority.PLAN_APPROVAL_REQUIRED,
            "source_repository_fingerprint": cls.context.get("source_repository_fingerprint", {}),
        }
        cls.request = authority.create_plan_approval_request(cls.plan, cls.state)
        cls.event = authority.make_test_explicit_user_approval_event(cls.request)
        cls.receipt = authority.record_plan_approval(cls.request, cls.event)
        cls.revalidation = authority.pre_execution_approval_revalidation(
            cls.receipt, cls.plan, cls.state, request=cls.request,
        )
        cls.authorization = authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
        )
        cls.compiled = authority.compile_approval_bound_execution_contracts(
            cls.plan, cls.receipt, cls.revalidation, cls.authorization,
            request=cls.request, requirements=cls.plan.get("requirements", []),
        )

    def test_live_fixture_identity_and_positive_path(self):
        self.assertEqual(self.brain["logical_hash"], EXPECTED_BRAIN_HASH)
        self.assertEqual(self.brain["record_count"], 12)
        self.assertEqual(self.brain["durability_counts"], {"DURABLE_VERIFIED": 11, "STATE_BOUND_VERIFIED": 1})
        self.assertEqual(self.plan["plan_id"], "PLAN-D8B51EE5EC97")
        self.assertEqual(self.plan["plan_hash"], "d8b51ee5ec97a54f1d4e5caff5ccbb9d2f5c9f02935c4ea8a88745f4f9275a73")
        self.assertEqual(self.request["status"], authority.APPROVAL_REQUEST_READY)
        self.assertEqual(self.receipt["approval_source"], authority.EXPLICIT_USER_APPROVAL)
        self.assertEqual(self.revalidation["valid"], True)
        self.assertEqual(self.authorization["status"], authority.EXECUTION_AUTHORIZATION_READY)
        self.assertEqual(self.compiled["status"], authority.EXECUTION_AUTHORIZATION_READY)

    def test_request_is_immutable_and_invalid_plan_is_rejected(self):
        with self.assertRaises(TypeError):
            self.request["canonical_plan_hash"] = "tampered"
        invalid = copy.deepcopy(self.plan)
        invalid_state = copy.deepcopy(self.state)
        invalid_state["plan_validation"] = {"valid": False, "status": "FAIL"}
        with self.assertRaises(authority.ApprovalRequestError):
            authority.create_plan_approval_request(invalid, invalid_state)

    def test_approval_required_alone_does_not_authorize(self):
        gate = authority.worker_authorization_gate(None)
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], authority.REAPPROVAL_REQUIRED)

    def test_explicit_event_receipt_and_idempotency(self):
        store = {}
        first = authority.record_plan_approval(self.request, self.event, idempotency_store=store)
        second = authority.record_plan_approval(self.request, self.event, idempotency_store=store)
        self.assertEqual(first, second)
        self.assertEqual(first["approval_event_source"], authority.TEST_EXPLICIT_USER_APPROVAL)
        with self.assertRaises(TypeError):
            first["receipt_hash"] = "tampered"

    def test_receipt_binds_all_required_authority_references(self):
        binding = self.request["binding"]
        self.assertEqual(binding["canonical_plan_id"], self.plan["plan_id"])
        self.assertEqual(binding["canonical_plan_hash"], self.plan["plan_hash"])
        self.assertEqual(binding["requirement_ids"], ["REQ-PAUSE-INDICATOR"])
        self.assertEqual(binding["mutation_scope"]["paths"], ["src/status_view.js"])
        self.assertEqual(binding["dnt"]["paths"], ["src/pause_controller.js"])
        self.assertEqual(binding["interface_binding"]["interfaces"], ["PauseController.togglePause"])
        for field in (
            "approved_mutation_scope_digest", "approved_dnt_digest", "approved_dependency_digest",
            "approved_verification_digest", "approved_interface_binding_digest",
            "approved_brain_hash", "approved_subject_aggregate_hash", "approved_planning_context_hash",
            "approved_challenger_reconciliation_hash",
        ):
            self.assertTrue(self.receipt[field], field)

    def _revalidate(self, *, plan=None, state=None, receipt=None):
        return authority.pre_execution_approval_revalidation(
            receipt or self.receipt,
            plan or self.plan,
            copy.deepcopy(state or self.state),
            request=self.request,
        )

    def test_unchanged_state_passes_and_authorization_is_accepted_without_worker(self):
        self.assertTrue(self.revalidation["valid"])
        gate = authority.worker_authorization_gate(
            self.authorization, self.receipt, self.revalidation, request=self.request,
        )
        self.assertTrue(gate["allowed"])
        self.assertEqual(gate["status"], authority.EXECUTION_AUTHORIZATION_READY)

    def test_plan_hash_and_cross_task_drift_fail_closed(self):
        changed = copy.deepcopy(self.plan)
        changed["integration_verification"] = list(changed.get("integration_verification", [])) + ["changed"]
        result = self._revalidate(plan=changed)
        self.assertFalse(result["valid"])
        self.assertIn(authority.APPROVAL_PLAN_HASH_MISMATCH, [item["code"] for item in result["mismatches"]])
        wrong_task = copy.deepcopy(self.state)
        wrong_task["task_id"] = "OTHER-TASK"
        result = self._revalidate(state=wrong_task)
        self.assertFalse(result["valid"])
        self.assertIn(authority.APPROVAL_TASK_MISMATCH, [item["code"] for item in result["mismatches"]])

    def test_subject_brain_dnt_scope_verification_dependency_interface_reconciliation_drift(self):
        cases = (
            ("subject_aggregate_hash", "different", authority.APPROVAL_SUBJECT_STALE),
            ("brain_hash", "different", authority.APPROVAL_BRAIN_STALE),
            ("planning_context_hash", "different", authority.APPROVAL_PLANNING_CONTEXT_MISMATCH),
        )
        for field, value, code in cases:
            with self.subTest(field=field):
                state = copy.deepcopy(self.state)
                state[field] = value
                result = self._revalidate(state=state)
                self.assertFalse(result["valid"])
                self.assertIn(code, [item["code"] for item in result["mismatches"]])
        plan_cases = (
            ("do_not_touch", ["src/pause_controller.js", "src/input.js"], authority.APPROVAL_DNT_MISMATCH),
            ("interfaces_to_reuse", ["Other.togglePause"], authority.APPROVAL_INTERFACE_MISMATCH),
        )
        for field, value, code in plan_cases:
            with self.subTest(field=field):
                plan = copy.deepcopy(self.plan)
                plan[field] = value
                result = self._revalidate(plan=plan)
                self.assertFalse(result["valid"])
                self.assertIn(code, [item["code"] for item in result["mismatches"]])
        state = copy.deepcopy(self.state)
        state["challenger_reconciliation"] = copy.deepcopy(self.reconciliation)
        state["challenger_reconciliation"]["reconciliation_hash"] = "changed"
        result = self._revalidate(state=state)
        self.assertFalse(result["valid"])
        self.assertIn(authority.APPROVAL_RECONCILIATION_MISMATCH, [item["code"] for item in result["mismatches"]])

    def test_verification_and_dependency_drift_are_distinct(self):
        state = copy.deepcopy(self.state)
        state["canonical_verification_contracts"] = copy.deepcopy(self.plan["canonical_verification_contracts"][:-1])
        result = self._revalidate(state=state)
        self.assertFalse(result["valid"])
        self.assertIn(authority.APPROVAL_VERIFICATION_MISMATCH, [item["code"] for item in result["mismatches"]])
        plan = copy.deepcopy(self.plan)
        plan["approved_change_nodes"][1]["dependencies"] = ["NODE-001"]
        result = self._revalidate(plan=plan)
        self.assertFalse(result["valid"])
        self.assertIn(authority.APPROVAL_DEPENDENCY_MISMATCH, [item["code"] for item in result["mismatches"]])

    def test_tampered_receipt_and_wrong_hash_are_rejected(self):
        tampered = copy.deepcopy(self.receipt)
        tampered["canonical_plan_hash"] = "wrong"
        self.assertFalse(authority.validate_plan_approval_receipt(tampered, self.request)["valid"])
        wrong_hash = copy.deepcopy(self.receipt)
        wrong_hash["canonical_plan_hash"] = "wrong"
        wrong_hash["receipt_hash"] = authority.canonical_hash({key: value for key, value in wrong_hash.items() if key != "receipt_hash"})
        self.assertFalse(authority.validate_plan_approval_receipt(wrong_hash, self.request)["valid"])

    def test_contracts_bind_exact_approval_and_scope_dnt_verification_dependencies(self):
        contracts = self.compiled["contracts"]
        self.assertTrue(contracts)
        for contract in contracts:
            self.assertEqual(contract["plan_hash"], self.plan["plan_hash"])
            self.assertEqual(contract["approved_plan_hash"], self.plan["plan_hash"])
            self.assertEqual(contract["approval_receipt_hash"], self.receipt["receipt_hash"])
            self.assertEqual(contract["execution_authorization_hash"], self.authorization["authorization_hash"])
            self.assertEqual(contract["approved_mutation_scope_digest"], self.authorization["mutation_scope_digest"])
            self.assertEqual(contract["approved_dnt_digest"], self.authorization["dnt_digest"])
            self.assertEqual(contract["approved_verification_digest"], self.authorization["verification_digest"])
            self.assertEqual(contract["approved_dependency_digest"], self.authorization["dependency_digest"])
            self.assertEqual(contract["contract_hash"], stage4.deterministic_hash(stage4._without(contract, "contract_hash")))
        self.assertEqual(self.compiled["contract_binding_validation"]["valid"], True)

    def test_contract_scope_expansion_dnt_override_and_binding_hash_change_fail(self):
        expanded = copy.deepcopy(self.compiled["contracts"])
        expanded[0]["allowed_mutation_paths"].append("src/input.js")
        expanded[0]["contract_hash"] = stage4.deterministic_hash(stage4._without(expanded[0], "contract_hash"))
        check = authority.validate_approval_bound_contracts(expanded, self.authorization, plan=self.plan, graph=self.compiled["graph"])
        self.assertFalse(check["valid"])
        protected = copy.deepcopy(self.compiled["contracts"])
        protected[0]["allowed_mutation_paths"] = ["src/pause_controller.js"]
        protected[0]["contract_hash"] = stage4.deterministic_hash(stage4._without(protected[0], "contract_hash"))
        check = authority.validate_approval_bound_contracts(protected, self.authorization, plan=self.plan)
        self.assertFalse(check["valid"])
        changed_binding = copy.deepcopy(self.compiled["contracts"][0])
        before = changed_binding["contract_hash"]
        changed_binding["approval_receipt_hash"] = "different-receipt"
        changed_binding["contract_hash"] = stage4.deterministic_hash(stage4._without(changed_binding, "contract_hash"))
        self.assertNotEqual(before, changed_binding["contract_hash"])
        self.assertFalse(authority.validate_approval_bound_contracts([changed_binding], self.authorization)["valid"])

    def test_authority_change_and_blocking_challenge_cannot_be_approved(self):
        changed = copy.deepcopy(self.plan)
        changed["authority_constraints"] = {"AUTHORITY_CHANGE": True}
        with self.assertRaises(authority.ApprovalRequestError):
            authority.create_plan_approval_request(changed, self.state)
        blocked_state = copy.deepcopy(self.state)
        blocked_state["challenger_reconciliation"] = copy.deepcopy(self.reconciliation)
        blocked_state["challenger_reconciliation"]["open_blocking_count"] = 1
        blocked_state["challenger_reconciliation"]["open_blocking_challenge_ids"] = ["CH-BLOCK"]
        with self.assertRaises(authority.ApprovalRequestError):
            authority.create_plan_approval_request(self.plan, blocked_state)

    def test_exact_live_replay_is_provider_free_and_stops_before_execution(self):
        replay = authority.run_stage6c_a_live_replay(
            LIVE_ROOT, brain_database_path=BRAIN_DB,
            expected_brain_hash=EXPECTED_BRAIN_HASH,
        )
        self.assertEqual(replay["status"], authority.EXECUTION_AUTHORIZATION_READY)
        self.assertTrue(replay["stop_before_execution"])
        self.assertEqual(replay["worker_calls"], 0)
        self.assertEqual(replay["gemma_generations"], 0)
        self.assertEqual(replay["subject_mutations"], 0)
        self.assertEqual(replay["brain_writes"], 0)
        self.assertEqual(replay["verifier_calls"], 0)
        self.assertEqual(replay["promotion_calls"], 0)


if __name__ == "__main__":
    unittest.main()
