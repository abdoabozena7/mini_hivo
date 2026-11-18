"""Provider-free V25.4.1 coverage-artifact propagation regressions."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import mini
from hivo import approval_authority as authority
from hivo import approval_bound_execution as stage6cb
from hivo import execution_contracts as stage4
from hivo import verification_obligation_coverage as coverage


ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = ROOT / "output" / "hivo-v25-4-stage6c-b-verification-complete-live-2"
ARTIFACT_ROOT = LIVE_ROOT / "artifacts"
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
HISTORICAL_DB = (
    ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1"
    / ".hivo" / "memory.sqlite3"
)

SUBJECT_FILES = (
    "src/input.js", "src/pause_controller.js", "src/status_view.js",
    "tests/input.test.js", "tests/pause_flow.integration.test.js",
    "tests/status_view.test.js",
)
EXPECTED_PLAN_ID = "PLAN-5E9D01B255C2"
EXPECTED_PLAN_HASH = "5e9d01b255c23753eafa3fa76160b91b8b92486506580ffaf11f582b9522115a"
EXPECTED_COVERAGE_HASH = "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402"
EXPECTED_VERIFICATION_DIGEST = "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51"
EXPECTED_ORACLE_HASH = "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140"
EXPECTED_AUTHORIZATION_HASH = "5368ca67d71796eecd7da20a05311328b55baf5921c6045f4b7cda7d57aef0e7"
EXPECTED_CONTRACT_HASH = "d3213b11ea9822fde9031ad522f1d188f3395089d3be6a6a870507f90a29bf19"
BEHAVIOR_OBLIGATION_ID = "OBL-REQ-PAUSE-INDICATOR-BEHAVIOR-CHANGE-01"


def _load(name: str, field: str | None = None):
    value = json.loads((ARTIFACT_ROOT / name).read_text(encoding="utf-8"))
    return value.get(field) if field else value


class VerificationCoverageArtifactPropagationTests(unittest.TestCase):
    """The complete V25.4.1 proof is deterministic and provider-free."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load("revised_plan_source.json", "plan")
        cls.request = _load("approval_request.json")
        cls.receipt = _load("approval_receipt.json")
        cls.revalidation = _load("preexecution_revalidation.json")
        cls.authorization = _load("execution_authorization.json")
        cls.coverage = _load("verification_obligation_coverage_source.json", "coverage")
        cls.invariant_set = _load("execution_invariant_source.json", "invariant_set")
        cls.stage4_artifacts = _load("stage4_contracts.json")
        cls.contract = cls.stage4_artifacts["contracts"][0]
        cls.packet_audit = _load("worker_packet_audit.json")
        cls.experiment_manifest = _load("experiment_manifest.json")
        cls.final_summary = _load("final_validation_summary.json")
        cls.surface_evidence = json.loads(
            (PLANNING_ROOT / "current_surface_evidence.json").read_text(encoding="utf-8")
        )
        context = json.loads(
            (PLANNING_ROOT / "verified_planning_context.json").read_text(encoding="utf-8")
        )
        freshness = json.loads(
            (PLANNING_ROOT / "planning_context_freshness.json").read_text(encoding="utf-8")
        )
        plan_validation = json.loads(
            (PLANNING_ROOT / "plan_validation.json").read_text(encoding="utf-8")
        )
        contractability = json.loads(
            (PLANNING_ROOT / "stage4_contractability_audit.json").read_text(encoding="utf-8")
        )
        reconciliation = json.loads(
            (PLANNING_ROOT / "challenger_reconciliation.json").read_text(encoding="utf-8")
        )
        brain = authority.read_only_project_brain_identity(
            HISTORICAL_DB, context.get("project_id")
        )
        cls.current_state = authority._live_state(
            PLANNING_ROOT, cls.plan, context, freshness, plan_validation,
            contractability, reconciliation, brain,
        )
        cls.current_state.update({
            "current_brain_hash": cls.authorization["current_brain_hash"],
            "current_subject_aggregate_hash": cls.authorization["current_subject_hash"],
            "interface_binding": copy.deepcopy(
                cls.revalidation["current_binding"]["interface_binding"]
            ),
        })
        cls.project_id = cls.authorization["source_bindings"]["project_id"]
        cls.self_test = mini.run_stage6c_b_v25_4_1_self_test()
        if cls.self_test.get("passed") is not True:
            raise AssertionError(cls.self_test)

    @staticmethod
    def _scope_paths(contract):
        return (
            list(contract.get("allowed_inspection_paths", []) or [])
            + list(contract.get("allowed_mutation_paths", []) or [])
            + list(contract.get("global_do_not_touch", []) or [])
        )

    @classmethod
    def _root_contract(cls):
        return {
            "goal": cls.plan["task_goal"],
            "requirements": copy.deepcopy(cls.plan.get("requirements", [])),
            "success_criteria": copy.deepcopy(cls.plan.get("requirements", [])),
            "original_goal": cls.plan["task_goal"],
            "project_id": cls.project_id,
        }

    @classmethod
    def _coverage_variant(cls, *, readiness=False):
        value = copy.deepcopy(cls.coverage)
        behavior = next(
            item for item in value["obligation_coverage"]
            if item.get("obligation_id") == BEHAVIOR_OBLIGATION_ID
        )
        behavior["coverage_state"] = coverage.UNCOVERED
        value["uncovered_obligation_ids"] = [BEHAVIOR_OBLIGATION_ID]
        value["status"] = coverage.VERIFICATION_OBLIGATION_UNCOVERED
        value["coverage_status"] = coverage.VERIFICATION_OBLIGATION_UNCOVERED
        value["verification_ready"] = False
        if readiness:
            # This is the same canonical incomplete artifact viewed through
            # the readiness failure assertion; no authority is weakened.
            value["new_behavior_oracle_count"] = 0
        value["coverage_hash"] = coverage.canonical_coverage_hash(value)
        return value

    @classmethod
    def _authorization_for_coverage(cls, coverage_artifact):
        return authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
            execution_invariant_set=cls.invariant_set,
            verification_obligation_coverage=coverage_artifact,
        )

    @classmethod
    def _run_worker(cls, coverage_artifact, authorization_value=None):
        """Run only the approval-bound seam against a temporary subject."""
        callbacks = []
        auth_value = authorization_value or cls.authorization
        with tempfile.TemporaryDirectory(prefix="hivo_v2541_worker_gate_") as temp:
            temporary = Path(temp)
            execution_root = temporary / "execution"
            execution_root.mkdir()
            for relative in SUBJECT_FILES:
                target = execution_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((LIVE_ROOT / relative).read_bytes())
            working_root = temporary / "working_brain"
            (working_root / ".hivo").mkdir(parents=True)
            shutil.copy2(HISTORICAL_DB, working_root / ".hivo" / "memory.sqlite3")
            store = mini.MemoryStore(working_root)

            def dispatch(**kwargs):
                callbacks.append(kwargs)
                return {"status": "done", "summary": "unexpected callback", "tool_evidence": []}

            result = stage6cb.execute_approval_bound_worker(
                task={"id": cls.request["task_id"]},
                contract=copy.deepcopy(cls.contract),
                plan=copy.deepcopy(cls.plan),
                authorization=auth_value,
                receipt=copy.deepcopy(cls.receipt),
                revalidation=copy.deepcopy(cls.revalidation),
                request=copy.deepcopy(cls.request),
                current_state=copy.deepcopy(cls.current_state),
                contracts=[copy.deepcopy(cls.contract)],
                graph=copy.deepcopy(cls.stage4_artifacts["graph"]),
                workspace=execution_root,
                worker_context="provider-free coverage propagation test",
                worker_dispatch=dispatch,
                verification_obligation_coverage=coverage_artifact,
                store=store,
                project_id=cls.project_id,
            )
        return result, callbacks

    def test_exact_frozen_identities_are_loaded(self):
        self.assertEqual(self.plan["plan_id"], EXPECTED_PLAN_ID)
        self.assertEqual(self.plan["plan_hash"], EXPECTED_PLAN_HASH)
        self.assertEqual(self.coverage["coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertEqual(self.authorization["authorization_hash"], EXPECTED_AUTHORIZATION_HASH)
        self.assertEqual(self.contract["contract_hash"], EXPECTED_CONTRACT_HASH)
        self.assertEqual(self.authorization["verification_digest"], EXPECTED_VERIFICATION_DIGEST)
        self.assertEqual(self.coverage["new_behavior_oracle_count"], 1)
        self.assertEqual(self.coverage["uncovered_obligation_ids"], [])

    def test_exact_artifact_canonical_hash_and_plan_identity(self):
        checked = coverage.validate_verification_obligation_coverage(
            self.coverage, plan=self.plan,
        )
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(
            coverage.canonical_coverage_hash(self.coverage),
            EXPECTED_COVERAGE_HASH,
        )
        self.assertEqual(self.coverage["plan_id"], self.plan["plan_id"])
        self.assertEqual(self.coverage["plan_hash"], self.plan["plan_hash"])

    def test_exact_artifact_verification_digest_oracle_and_readiness_bind(self):
        checked = authority.validate_approved_execution_authorization(
            self.authorization, self.receipt, self.revalidation,
            request=self.request,
            execution_invariant_set=self.invariant_set,
            verification_obligation_coverage=self.coverage,
        )
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(self.authorization["verification_digest"], EXPECTED_VERIFICATION_DIGEST)
        self.assertEqual(self.coverage["oracle_records"][3]["oracle_id"], "ORACLE-PAUSE-INDICATOR")
        self.assertEqual(self.coverage["oracle_records"][3]["source_hash"], "0f9684c6e0ed12e3cbf6c0e6d94a35c8c84f9bbb1017ff495897baae71321852")
        self.assertEqual(self.coverage["oracle_records"][3]["oracle_id"], "ORACLE-PAUSE-INDICATOR")
        self.assertEqual(self.coverage["coverage_hash"], self.authorization["verification_obligation_coverage_hash"])
        self.assertEqual(self.coverage["status"], self.authorization["verification_obligation_coverage_status"])
        self.assertTrue(self.authorization["verification_obligation_coverage_ready"])

    def test_missing_artifact_reproduces_old_last_moment_blocker(self):
        audit = stage6cb.last_moment_authorization_audit(
            authorization=self.authorization, receipt=self.receipt,
            revalidation=self.revalidation, request=self.request,
            plan=self.plan, current_state=self.current_state,
            contracts=[self.contract], graph=self.stage4_artifacts["graph"],
            contract=self.contract, workspace=LIVE_ROOT,
            project_id=self.project_id, subject_paths=self._scope_paths(self.contract),
            verification_obligation_coverage=None,
        )
        self.assertFalse(audit["allowed"])
        self.assertEqual(audit["code"], authority.EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH)
        self.assertTrue(any(
            item.get("code") == authority.EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH
            for item in audit.get("errors", []) if isinstance(item, dict)
        ))
        result, callbacks = self._run_worker(None)
        self.assertEqual(callbacks, [])
        self.assertEqual(result.get("worker_calls"), 0)

    def test_exact_artifact_closes_missing_artifact_blocker(self):
        audit = stage6cb.last_moment_authorization_audit(
            authorization=self.authorization, receipt=self.receipt,
            revalidation=self.revalidation, request=self.request,
            plan=self.plan, current_state=self.current_state,
            contracts=[self.contract], graph=self.stage4_artifacts["graph"],
            contract=self.contract, workspace=LIVE_ROOT,
            project_id=self.project_id, subject_paths=self._scope_paths(self.contract),
            verification_obligation_coverage=self.coverage,
        )
        self.assertTrue(audit["allowed"], audit)
        self.assertIsNone(audit["code"])
        contract_check = authority.validate_approval_bound_contracts(
            [self.contract], self.authorization, plan=self.plan,
            graph=self.stage4_artifacts["graph"],
            verification_obligation_coverage=self.coverage,
        )
        self.assertTrue(contract_check["valid"], contract_check)

    def test_wrong_canonical_artifact_fails_closed_before_worker(self):
        wrong = copy.deepcopy(self.coverage)
        wrong["task_id"] = "WRONG-COVERAGE-TASK"
        wrong["coverage_hash"] = coverage.canonical_coverage_hash(wrong)
        self.assertTrue(coverage.validate_verification_obligation_coverage(wrong)["valid"])
        gate = authority.worker_authorization_gate(
            self.authorization, self.receipt, self.revalidation,
            request=self.request,
            verification_obligation_coverage=wrong,
        )
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], authority.VERIFICATION_OBLIGATION_COVERAGE_MISMATCH)
        result, callbacks = self._run_worker(wrong)
        self.assertEqual(callbacks, [])
        self.assertEqual(result.get("worker_calls"), 0)

    def test_tampered_artifact_fails_canonical_validation_before_worker(self):
        tampered = copy.deepcopy(self.coverage)
        tampered["coverage_bindings"][0]["coverage_strength"] = "tampered"
        checked = coverage.validate_verification_obligation_coverage(tampered)
        self.assertFalse(checked["valid"])
        self.assertIn("coverage hash does not match canonical content", checked["errors"])
        result, callbacks = self._run_worker(tampered)
        self.assertEqual(callbacks, [])
        self.assertEqual(result.get("worker_calls"), 0)

    def test_not_ready_canonical_artifact_fails_closed_before_worker(self):
        not_ready = self._coverage_variant(readiness=True)
        not_ready_auth = self._authorization_for_coverage(not_ready)
        checked = coverage.validate_verification_obligation_coverage(not_ready)
        self.assertTrue(checked["valid"], checked)
        self.assertFalse(checked["verification_ready"])
        gate = authority.worker_authorization_gate(
            not_ready_auth, self.receipt, self.revalidation,
            request=self.request,
            verification_obligation_coverage=not_ready,
        )
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], authority.VERIFICATION_OBLIGATION_UNCOVERED)
        result, callbacks = self._run_worker(not_ready, not_ready_auth)
        self.assertEqual(callbacks, [])
        self.assertEqual(result.get("worker_calls"), 0)

    def test_uncovered_mandatory_obligation_fails_closed_before_worker(self):
        uncovered = self._coverage_variant()
        uncovered_auth = self._authorization_for_coverage(uncovered)
        self.assertEqual(uncovered["uncovered_obligation_ids"], [BEHAVIOR_OBLIGATION_ID])
        gate = authority.worker_authorization_gate(
            uncovered_auth, self.receipt, self.revalidation,
            request=self.request,
            verification_obligation_coverage=uncovered,
        )
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], authority.VERIFICATION_OBLIGATION_UNCOVERED)
        result, callbacks = self._run_worker(uncovered, uncovered_auth)
        self.assertEqual(callbacks, [])
        self.assertEqual(result.get("worker_calls"), 0)

    def test_stale_artifact_is_rejected_when_source_freshness_is_checked(self):
        stale = copy.deepcopy(self.coverage)
        stale["oracle_records"][3]["source_hash"] = "0" * 64
        stale["coverage_hash"] = coverage.canonical_coverage_hash(stale)
        checked = coverage.validate_verification_obligation_coverage(
            stale, plan=self.plan, execution_contract=self.contract,
            source_root=LIVE_ROOT,
        )
        self.assertFalse(checked["valid"])
        self.assertTrue(any("stale" in error for error in checked["errors"]))

    def test_execution_start_receipt_carries_exact_coverage_binding(self):
        subject = stage6cb.enumerate_execution_subject(LIVE_ROOT)
        start = stage6cb.create_execution_start_receipt(
            self.authorization, self.receipt, self.plan, self.contract,
            pre_subject_hash=subject["hash"],
            pre_brain_hash=self.authorization["current_brain_hash"],
            workspace=LIVE_ROOT, subject_paths=self._scope_paths(self.contract),
            verification_obligation_coverage=self.coverage,
        )
        self.assertEqual(
            start["verification_obligation_coverage_hash"], EXPECTED_COVERAGE_HASH
        )
        self.assertEqual(start["verification_obligation_coverage_status"], coverage.EXECUTION_VERIFICATION_READY)
        self.assertTrue(start["verification_obligation_coverage_ready"])
        self.assertTrue(stage6cb.validate_execution_start_receipt(
            start, authorization=self.authorization,
            verification_obligation_coverage=self.coverage,
        )["valid"])
        self.assertFalse(stage6cb.validate_execution_start_receipt(
            start, authorization=self.authorization,
        )["valid"])

    def test_stage4_compile_keeps_compact_coverage_binding(self):
        compiled = authority.compile_approval_bound_execution_contracts(
            self.plan, self.receipt, self.revalidation, self.authorization,
            request=self.request, requirements=self.plan.get("requirements", []),
            repository_evidence=self.surface_evidence["repository_evidence"],
            canonical_surface_registry=self.surface_evidence["registry"],
            execution_invariant_set=self.invariant_set,
            execution_invariant_source_root=LIVE_ROOT,
            verification_obligation_coverage=self.coverage,
        )
        self.assertTrue(compiled["contract_binding_validation"]["valid"])
        compiled_contract = compiled["contracts"][0]
        self.assertEqual(compiled_contract["contract_hash"], EXPECTED_CONTRACT_HASH)
        self.assertEqual(compiled_contract["verification_obligation_coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertEqual(compiled_contract["verification_obligation_coverage_status"], coverage.EXECUTION_VERIFICATION_READY)
        self.assertNotIn("atomic_obligations", compiled_contract)
        self.assertNotIn("oracle_records", compiled_contract)

    def test_lifecycle_propagates_one_exact_artifact_without_reconstruction(self):
        seen_gate_hashes = []
        seen_contract_hashes = []
        original_gate = authority.worker_authorization_gate
        original_contract_check = authority.validate_approval_bound_contracts

        def gate(*args, **kwargs):
            artifact = kwargs.get("verification_obligation_coverage")
            seen_gate_hashes.append(
                artifact.get("coverage_hash") if isinstance(artifact, dict) else None
            )
            return original_gate(*args, **kwargs)

        def contract_check(*args, **kwargs):
            artifact = kwargs.get("verification_obligation_coverage")
            seen_contract_hashes.append(
                artifact.get("coverage_hash") if isinstance(artifact, dict) else None
            )
            return original_contract_check(*args, **kwargs)

        with mock.patch.object(authority, "worker_authorization_gate", side_effect=gate), \
             mock.patch.object(authority, "validate_approval_bound_contracts", side_effect=contract_check), \
             mock.patch.object(
                 mini.stage6c_coverage,
                 "build_verification_obligation_coverage",
                 side_effect=AssertionError("coverage must not be reconstructed downstream"),
             ):
            result = mini.run_stage6c_b_v25_4_1_self_test()
        self.assertTrue(result["passed"], result)
        self.assertGreaterEqual(len(seen_gate_hashes), 4)
        self.assertGreaterEqual(len(seen_contract_hashes), 2)
        self.assertTrue(seen_gate_hashes)
        self.assertTrue(seen_contract_hashes)
        self.assertEqual(seen_gate_hashes.count(None), 1)
        self.assertEqual(seen_contract_hashes.count(None), 1)
        self.assertTrue(all(
            item == EXPECTED_COVERAGE_HASH for item in seen_gate_hashes if item
        ))
        self.assertTrue(all(
            item == EXPECTED_COVERAGE_HASH for item in seen_contract_hashes if item
        ))

    def test_provider_free_replay_reaches_deeper_mini_gate_once(self):
        self.assertEqual(self.self_test["callback_calls"], 1)
        self.assertEqual(self.self_test["provider_calls"], 0)
        self.assertEqual(self.self_test["execution_start_receipt"]["verification_obligation_coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertTrue(self.self_test["checks"]["final_gate_passed_before_callback"])
        self.assertTrue(self.self_test["checks"]["execution_start_receipt_reached"])
        self.assertEqual(self.self_test["execution_contract_hash"], EXPECTED_CONTRACT_HASH)
        self.assertEqual(self.self_test["terminal_state"], stage6cb.WORKER_NO_APPROVED_MUTATION)

    def test_plan_verification_oracle_scope_dnt_and_packet_are_unchanged(self):
        self.assertEqual(self.packet_audit["provider_facing_packet_chars"], 4192)
        self.assertEqual(self.packet_audit["worker_context_budget"]["context_limit"], 4200)
        self.assertEqual(self.packet_audit["worker_context_budget"]["mandatory_drops"], 0)
        self.assertTrue(self.packet_audit["bounded_only"])
        self.assertEqual(self.experiment_manifest["plan"]["id"], EXPECTED_PLAN_ID)
        self.assertEqual(self.experiment_manifest["plan"]["hash"], EXPECTED_PLAN_HASH)
        self.assertEqual(self.experiment_manifest["verification"]["coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertEqual(self.experiment_manifest["verification"]["digest"], EXPECTED_VERIFICATION_DIGEST)
        self.assertEqual(self.experiment_manifest["verification"]["oracle_id"], "ORACLE-PAUSE-INDICATOR")
        self.assertEqual(self.experiment_manifest["verification"]["oracle_hash"], EXPECTED_ORACLE_HASH)
        self.assertEqual(self.contract["allowed_mutation_paths"], ["src/status_view.js"])
        self.assertEqual(self.contract["global_do_not_touch"], ["src/pause_controller.js"])
        self.assertEqual(self.final_summary["worker_provider_generations"], 0)
        self.assertFalse(self.final_summary["promotion_performed"])

    def test_receipt_is_plan_bound_and_authorization_can_be_recomputed_deterministically(self):
        receipt_check = authority.validate_plan_approval_receipt(
            self.receipt, self.request,
        )
        self.assertTrue(receipt_check["valid"], receipt_check)
        self.assertNotIn("execution_engine_hash", self.receipt)
        self.assertNotIn("source_commit", self.receipt)
        recomputed = self._authorization_for_coverage(self.coverage)
        # The approval receipt is durable for the unchanged plan.  The
        # execution authorization is a separate engine-bound proof and is
        # intentionally recomputed for this changed execution machinery.
        self.assertNotEqual(recomputed["authorization_hash"], EXPECTED_AUTHORIZATION_HASH)
        self.assertEqual(recomputed["canonical_plan_hash"], EXPECTED_PLAN_HASH)
        self.assertEqual(recomputed["verification_obligation_coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertTrue(authority.validate_approved_execution_authorization(
            recomputed, self.receipt, self.revalidation,
            request=self.request,
            execution_invariant_set=self.invariant_set,
            verification_obligation_coverage=self.coverage,
        )["valid"])

    def test_no_model_calls_or_historical_mutation_are_possible_in_self_test(self):
        self.assertEqual(self.self_test["model_calls"], 0)
        self.assertEqual(self.self_test["worker_calls"], 0)
        self.assertEqual(self.self_test["provider_calls"], 0)
        self.assertEqual(self.self_test["historical_brain_writes"], 0)
        self.assertEqual(self.self_test["repository_subject_mutations"], 0)
        self.assertTrue(self.self_test["checks"]["historical_brain_unchanged"])
        self.assertTrue(self.self_test["checks"]["failed_live_subject_unchanged"])


if __name__ == "__main__":
    unittest.main()
