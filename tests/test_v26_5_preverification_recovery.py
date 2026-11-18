"""Provider-free V26.5 pre-verification recovery eligibility tests."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

import mini
from hivo import recovery


ROOT = Path(__file__).resolve().parents[1]
LIVE3 = ROOT / "output" / "hivo-v25-6-stage6c-b-verification-closure-live-3"


class V265PreVerificationRecoveryTests(unittest.TestCase):
    """Exercise the explicit failure-source contract without a provider."""

    @classmethod
    def setUpClass(cls):
        cls.data = recovery.load_live3_recovery_evidence(LIVE3)
        cls.authority = copy.deepcopy(cls.data["execution_authorization"])
        cls.subject = recovery.LIVE3_FAILED_SUBJECT_HASH

    def _worker_evidence(self, **overrides):
        values = {
            "execution_id": "WORKER-EXEC-V265-TEST",
            "terminal_code": recovery.WORKER_NO_APPROVED_MUTATION,
            "subject_before_hash": self.subject,
            "subject_after_hash": self.subject,
            "current_subject_hash": self.subject,
        }
        values.update(overrides)
        return recovery.build_worker_execution_failure_evidence(**values)

    def _worker_envelope(self, **overrides):
        evidence = self._worker_evidence(**overrides)
        envelope = recovery.build_recovery_failure_envelope(
            self.data,
            failure_evidence=evidence,
        )
        return evidence, envelope

    def _pipeline(self, envelope):
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        delta = classification["authority_delta"]
        lineage = recovery.build_authorized_execution_lineage(
            envelope,
            authorization=self.authority,
        )
        eligibility = recovery.decide_recovery_eligibility(
            envelope,
            classification,
            authority_delta=delta,
            lineage=lineage,
            current_subject_hash=envelope["current_subject_hash"],
            authorization=self.authority,
        )
        authorization = recovery.build_approved_recovery_authorization(
            envelope,
            classification=classification,
            authority_delta=delta,
            lineage=lineage,
            eligibility=eligibility,
            approved_authority=self.authority,
        )
        mission = recovery.build_recovery_mission(
            envelope,
            authorization,
            classification=classification,
        )
        packet = recovery.build_recovery_worker_packet(mission, authorization)
        return classification, delta, lineage, eligibility, authorization, mission, packet

    @staticmethod
    def _rehash_evidence(value):
        result = copy.deepcopy(value)
        digest = recovery.canonical_hash({
            key: item
            for key, item in result.items()
            if key not in {"canonical_hash", "failure_evidence_hash"}
        })
        result["canonical_hash"] = digest
        result["failure_evidence_hash"] = digest
        return result

    def test_01_explicit_union_has_distinct_immutable_variants(self):
        verification = recovery.build_verification_failure_evidence(
            "EXEC-V265-VERIFICATION",
            subject_before_hash=self.subject,
            subject_after_hash=self.subject,
            current_subject_hash=self.subject,
        )
        worker = self._worker_evidence()
        self.assertIsInstance(verification, recovery.VerificationFailureEvidence)
        self.assertIsInstance(worker, recovery.WorkerExecutionFailureEvidence)
        self.assertEqual(verification["failure_source"], recovery.VERIFICATION_FAILURE)
        self.assertEqual(worker["failure_source"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertTrue(recovery.validate_recovery_failure_evidence(verification)["valid"])
        self.assertTrue(recovery.validate_recovery_failure_evidence(worker)["valid"])
        self.assertNotEqual(verification["canonical_hash"], worker["canonical_hash"])
        with self.assertRaises(TypeError):
            worker["worker_terminal_code"] = "changed"

    def test_02_builder_dispatch_and_unknown_variant_fail_closed(self):
        worker = recovery.build_recovery_failure_evidence(
            recovery.WORKER_EXECUTION_FAILURE,
            execution_id="EXEC-V265-WORKER",
        )
        verification = recovery.build_recovery_failure_evidence(
            recovery.VERIFICATION_FAILURE,
            execution_id="EXEC-V265-VERIFICATION",
        )
        unknown = recovery.build_recovery_failure_evidence(
            "EXEC-V265-UNKNOWN",
            failure_source="UNSUPPORTED_FAILURE_SOURCE",
        )
        missing = recovery.build_recovery_failure_evidence("EXEC-V265-MISSING")
        self.assertEqual(worker["source_variant"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertEqual(verification["source_variant"], recovery.VERIFICATION_FAILURE)
        self.assertFalse(recovery.validate_recovery_failure_evidence(unknown)["valid"])
        self.assertFalse(recovery.validate_recovery_failure_evidence(missing)["valid"])
        self.assertEqual(unknown["failure_source"], "UNSUPPORTED_FAILURE_SOURCE")
        unknown_envelope = recovery.build_recovery_failure_envelope(
            self.data,
            failure_evidence=unknown,
        )
        self.assertEqual(unknown_envelope["failure_source"], "UNSUPPORTED_FAILURE_SOURCE")
        self.assertEqual(
            recovery.classify_recovery_failure(unknown_envelope)["classification"],
            recovery.RECOVERY_CLASSIFICATION_UNCERTAIN,
        )

    def test_03_worker_evidence_is_complete_deterministic_and_private_reasoning_free(self):
        first = self._worker_evidence(
            reasoning="private chain of thought must not persist",
            messages=["private transcript"],
            timestamp="do-not-add",
        )
        second = self._worker_evidence(
            reasoning="different private reasoning",
            messages=["different transcript"],
        )
        self.assertTrue(recovery.validate_recovery_failure_evidence(first)["valid"])
        self.assertEqual(first, second)
        self.assertNotIn("timestamp", first)
        self.assertNotIn("reasoning", first)
        self.assertNotIn("messages", first)
        self.assertNotIn("chain_of_thought", json.dumps(first, ensure_ascii=False))
        self.assertEqual(first["worker_terminal_code"], recovery.WORKER_NO_APPROVED_MUTATION)
        self.assertFalse(first["v25_6_executed"])
        self.assertFalse(first["verified_successful_completion"])
        self.assertFalse(first["commit"])
        self.assertEqual(first["commit_count"], 0)

    def test_04_worker_variant_rejects_verification_field_mixing(self):
        mixed = self._rehash_evidence({
            **dict(self._worker_evidence()),
            "authority_id": "VERIFICATION-004",
        })
        checked = recovery.validate_recovery_failure_evidence(mixed)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("mixes verification field" in item for item in checked["errors"]))

    def test_05_worker_envelope_has_no_fake_verification_receipt(self):
        evidence, envelope = self._worker_envelope()
        checked = recovery.validate_recovery_failure_envelope(envelope)
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(envelope["failure_source"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertEqual(envelope["failure_evidence"]["canonical_hash"], evidence["canonical_hash"])
        self.assertEqual(envelope["failed_verification_authority_ids"], [])
        self.assertEqual(envelope["failed_verification"], {})
        self.assertEqual(envelope["execution_verification_closure"], {})
        self.assertEqual(envelope["execution_verification_closure_hash"], "")
        self.assertEqual(envelope["worker_prose_authority"], 0)

    def test_06_legacy_verification_path_remains_valid_and_distinct(self):
        envelope = recovery.build_recovery_failure_envelope(self.data)
        checked = recovery.validate_recovery_failure_envelope(envelope)
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(envelope["failure_source"], recovery.VERIFICATION_FAILURE)
        self.assertTrue(envelope["failed_verification_authority_ids"])
        self.assertTrue(envelope["failure_evidence"]["verification_executed"])
        self.assertTrue(envelope["failure_evidence"]["v25_6_executed"])
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        self.assertEqual(classification["classification"], recovery.WORKER_RECOVERABLE)

    def test_06a_missing_verification_receipt_does_not_infer_a_failure_variant(self):
        source = copy.deepcopy(self.data)
        source["verification_evidence"] = []
        source["verification_aggregation"] = {}
        source["execution_verification_closure"] = {}
        source["execution_time_coverage"] = {}
        if isinstance(source.get("worker_result"), dict):
            source["worker_result"]["verification_evidence"] = []
            source["worker_result"]["verification_aggregation"] = {}
            source["worker_result"]["execution_verification_closure"] = {}
            source["worker_result"]["execution_time_coverage"] = {}
        if isinstance(source.get("artifacts"), dict):
            for key in (
                "verification_runner_evidence", "verification_runner_evidence.json",
                "verification_coverage", "verification_coverage.json",
            ):
                source["artifacts"].pop(key, None)
        envelope = recovery.build_recovery_failure_envelope(source)
        self.assertEqual(envelope["failure_source"], "")
        self.assertEqual(envelope["failed_verification_authority_ids"], [])
        self.assertFalse(recovery.validate_recovery_failure_envelope(envelope)["valid"])
        self.assertEqual(
            recovery.classify_recovery_failure(envelope)["classification"],
            recovery.RECOVERY_CLASSIFICATION_UNCERTAIN,
        )

    def test_07_positive_worker_pipeline_has_same_authority_and_bounded_packet(self):
        _, envelope = self._worker_envelope()
        classification, delta, lineage, eligibility, authorization, mission, packet = self._pipeline(envelope)
        self.assertEqual(classification["classification"], recovery.WORKER_RECOVERABLE)
        self.assertEqual(classification["failure_source"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertTrue(classification["preverification_eligibility"]["eligible"])
        self.assertTrue(delta["empty"])
        self.assertTrue(recovery.validate_authorized_execution_lineage(lineage, envelope=envelope)["valid"])
        self.assertEqual(eligibility["status"], recovery.RECOVERY_ELIGIBLE)
        self.assertFalse(eligibility["USER_REAPPROVAL_REQUIRED"])
        self.assertEqual(authorization["status"], recovery.RECOVERY_AUTHORIZATION_READY)
        self.assertTrue(authorization["derived_from_existing_approval"])
        self.assertFalse(authorization["new_user_approval_created"])
        self.assertEqual(mission["status"], recovery.RECOVERY_MISSION_READY)
        self.assertEqual(mission["failure_source"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertEqual(mission["failed_verification"], {})
        self.assertTrue(mission["no_fake_verification_authority"])
        self.assertTrue(recovery.validate_recovery_worker_packet(packet)["valid"])
        self.assertLessEqual(packet["packet_chars"], 4200)
        self.assertEqual(packet["worker_prose_authority"], 0)

    def test_08_preverification_positive_policy_requires_all_predicates(self):
        _, envelope = self._worker_envelope()
        policy = recovery.evaluate_preverification_recovery_eligibility(envelope)
        self.assertTrue(policy["variant_valid"])
        self.assertTrue(policy["complete"])
        self.assertTrue(policy["eligible"])
        self.assertTrue(all(policy["checks"].values()))
        required = {
            "actual_worker_lifecycle", "provider_healthy", "valid_provider_handoff",
            "worker_execution_failure", "no_verified_successful_completion",
            "v25_6_not_executed", "subject_known", "subject_unchanged",
            "known_lineage", "no_unknown_manual_drift", "scope_pass", "dnt_pass",
            "plan_unchanged", "approval_unchanged", "brain_valid", "not_promoted",
            "authority_delta_empty", "legal_solution_space",
            "full_verification_universe_available", "recovery_budget_available",
            "not_harness_failure", "commit_free", "v25_5_authority_valid",
        }
        self.assertTrue(required.issubset(policy["checks"]))

    def test_09_negative_policy_matrix_fails_closed_without_uncertain_overclaim(self):
        cases = (
            (
                "provider",
                {"provider_health": "UNHEALTHY", "provider_failure": True},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER,
            ),
            (
                "provider_handoff",
                {"provider_handoff_valid": False},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER,
            ),
            (
                "harness",
                {"harness_failure": True},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_HARNESS,
            ),
            (
                "drift",
                {"unknown_manual_drift": True},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_DRIFT,
            ),
            (
                "no_legal_space",
                {"legal_solution_space_available": False, "allowed_mutation_paths": []},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_NO_LEGAL_SPACE,
            ),
            (
                "budget",
                {"recovery_budget_available": False},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_BUDGET,
            ),
            (
                "unsupported_terminal",
                {"terminal_code": "UNSUPPORTED_WORKER_TERMINAL"},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
            ),
            (
                "v25_6_executed",
                {"v25_6_executed": True},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
            ),
            (
                "verified_completion",
                {"verified_successful_completion": True},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
            ),
            (
                "approved_mutation_present",
                {"approved_mutation_count": 1, "changed_paths": ["src/status_view.js"]},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
            ),
            (
                "promoted_state",
                {"promoted": True, "promotion_status": "PROMOTED"},
                recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
            ),
        )
        for name, overrides, expected in cases:
            with self.subTest(name=name):
                _, envelope = self._worker_envelope(**overrides)
                classification = recovery.classify_recovery_failure(
                    envelope,
                    approved_authority=self.authority,
                )
                policy = recovery.evaluate_preverification_recovery_eligibility(
                    envelope,
                    authority_delta=classification["authority_delta"],
                )
                self.assertFalse(policy["eligible"])
                self.assertEqual(classification["classification"], expected)
                self.assertFalse(classification["recoverable"])
                self.assertTrue(recovery.validate_recovery_failure_envelope(envelope)["valid"])

    def test_10_authority_delta_is_explicit_and_requires_reapproval(self):
        _, envelope = self._worker_envelope(authority_delta_empty=False)
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        self.assertEqual(classification["classification"], recovery.AUTHORITY_CHANGE_REQUIRED)
        self.assertFalse(classification["authority_delta_empty"])
        self.assertTrue(classification["USER_REAPPROVAL_REQUIRED"])
        self.assertFalse(
            recovery.evaluate_preverification_recovery_eligibility(
                envelope,
                authority_delta=classification["authority_delta"],
            )["eligible"]
        )

    def test_10a_commit_and_subject_change_observations_cannot_be_eligible(self):
        evidence, envelope = self._worker_envelope(
            commit_count=1,
            commit=True,
            filesystem_changed=True,
        )
        self.assertEqual(evidence["commit_count"], 1)
        self.assertTrue(evidence["commit"])
        self.assertTrue(evidence["filesystem_changed"])
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        self.assertEqual(
            classification["classification"],
            recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE,
        )
        self.assertFalse(classification["preverification_eligibility"]["eligible"])

    def test_11_incomplete_evidence_is_uncertain_and_reporting_never_says_not_required(self):
        incomplete = dict(self._worker_evidence())
        incomplete.pop("worker_terminal_code")
        incomplete = self._rehash_evidence(incomplete)
        envelope = recovery.build_recovery_failure_envelope(
            self.data,
            failure_evidence=incomplete,
        )
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        self.assertEqual(classification["classification"], recovery.RECOVERY_CLASSIFICATION_UNCERTAIN)
        report = recovery.derive_recovery_reporting_state(
            initial_verification_passed=False,
            initial_worker_succeeded=False,
            recovery_required=True,
            classification=classification,
        )
        self.assertEqual(report["state"], recovery.RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN)
        self.assertNotEqual(report["state"], "RECOVERY_NOT_REQUIRED")

    def test_11a_envelope_binds_failure_evidence_hash(self):
        _, envelope = self._worker_envelope()
        tampered = copy.deepcopy(envelope)
        tampered["failure_evidence_hash"] = "f" * 64
        tampered["canonical_failure_envelope_hash"] = recovery.canonical_hash({
            key: item
            for key, item in tampered.items()
            if key not in {
                "canonical_failure_envelope_hash", "failure_envelope_hash", "canonical_hash",
            }
        })
        tampered["failure_envelope_hash"] = tampered["canonical_failure_envelope_hash"]
        tampered["canonical_hash"] = tampered["canonical_failure_envelope_hash"]
        checked = recovery.validate_recovery_failure_envelope(tampered)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("evidence hash" in item for item in checked["errors"]))

    def test_12_terminal_label_alone_cannot_grant_recovery(self):
        _, envelope = self._worker_envelope(
            actual_worker_lifecycle=False,
            harness_failure=True,
        )
        classification = recovery.classify_recovery_failure(
            envelope,
            approved_authority=self.authority,
        )
        self.assertNotEqual(classification["classification"], recovery.WORKER_RECOVERABLE)
        self.assertEqual(classification["classification"], recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_HARNESS)
        self.assertFalse(classification["preverification_eligibility"]["eligible"])

    def test_13_reporting_projection_distinguishes_success_blocked_unknown_and_dispatched(self):
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                initial_verification_passed=True,
                initial_worker_succeeded=True,
            )["state"],
            "RECOVERY_NOT_REQUIRED",
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER,
            )["state"],
            recovery.RECOVERY_REQUIRED_BUT_NOT_DISPATCHABLE,
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.RECOVERY_CLASSIFICATION_UNCERTAIN,
            )["state"],
            recovery.RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN,
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.WORKER_RECOVERABLE,
                recovery_dispatched=True,
            )["state"],
            recovery.RECOVERY_REQUIRED_DISPATCHED,
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.WORKER_RECOVERABLE,
                eligibility={"eligible": True},
            )["state"],
            recovery.RECOVERY_REQUIRED_CLASSIFIED,
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.AUTHORITY_CHANGE_REQUIRED,
                eligibility={"eligible": False, "user_reapproval_required": True},
            )["state"],
            recovery.RECOVERY_REQUIRED_AUTHORITY_CHANGE,
        )
        self.assertEqual(
            recovery.derive_recovery_reporting_state(
                recovery_required=True,
                classification=recovery.WORKER_RECOVERABLE,
                recovery_completed=True,
            )["state"],
            recovery.RECOVERY_COMPLETED,
        )

    def test_14_provider_free_worker_execution_replay_reaches_full_existing_gates(self):
        evidence = self._worker_evidence()
        result = recovery.run_provider_free_recovery_replay(
            LIVE3,
            outcome="success",
            failure_evidence=evidence,
        )
        self.assertEqual(result["status"], "RECOVERY_REPLAY_PROMOTED")
        self.assertEqual(result["classification"]["classification"], recovery.WORKER_RECOVERABLE)
        self.assertTrue(result["eligibility"]["eligible"])
        self.assertTrue(result["stage5a"]["passed"])
        self.assertEqual(result["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(result["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(result["reentry"]["status"], "REENTRY_READY")
        self.assertTrue(result["brain_unchanged"] is False or result["stage5c"]["promotion_status"] == "PROMOTED")
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)
        self.assertEqual(result["worker_calls"], 0)

    def test_15_provider_free_worker_execution_failure_has_no_promotion_and_consumes_one_attempt(self):
        result = recovery.run_provider_free_recovery_replay(
            LIVE3,
            outcome="failure",
            failure_evidence=self._worker_evidence(),
        )
        self.assertEqual(result["status"], "RECOVERY_REPLAY_VERIFICATION_FAILED")
        self.assertEqual(result["classification"]["classification"], recovery.WORKER_RECOVERABLE)
        self.assertFalse(result["stage5a"]["passed"])
        self.assertIsNone(result["stage5c"])
        self.assertIsNone(result["reentry"])
        self.assertTrue(result["brain_unchanged"])
        self.assertEqual(result["second_dispatch"]["status"], recovery.RECOVERY_BUDGET_EXHAUSTED)
        self.assertEqual(result["recovery_callback_calls"], 1)
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)

    def test_16_v26_4_composition_and_budgets_remain_provider_free(self):
        self.assertEqual(recovery.MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_STRATEGY_SWITCHES, 1)
        self.assertEqual(recovery.RECOVERY_STRATEGY_STAGNATION_THRESHOLD, 2)
        self.assertEqual(recovery.MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_EPOCH_REANCHORS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS, 1)
        self.assertTrue(recovery.run_recovery_architecture_self_test(LIVE3)["passed"])
        self.assertEqual(mini.WORKER_EXECUTION_FAILURE, recovery.WORKER_EXECUTION_FAILURE)
        self.assertEqual(mini.RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN, recovery.RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN)

    def test_17_budget_accounting_blocks_a_second_worker_without_provider_calls(self):
        accounting = recovery.create_recovery_attempt_accounting()
        self.assertTrue(recovery.can_start_recovery_attempt(accounting, attempt_index=1)["allowed"])
        first = recovery.consume_recovery_attempt(accounting, attempt_index=1, outcome="failure")
        self.assertFalse(recovery.can_start_recovery_attempt(first, attempt_index=2)["allowed"])
        self.assertEqual(
            recovery.can_start_recovery_attempt(first, attempt_index=2)["status"],
            recovery.RECOVERY_BUDGET_EXHAUSTED,
        )
        self.assertEqual(first["recovery_attempts_started"], 1)
        self.assertEqual(first["gemma_calls"], 0)
        self.assertEqual(first["worker_calls"], 0)

    def test_18_authority_and_plan_ids_are_unchanged_through_execution_failure_pipeline(self):
        _, envelope = self._worker_envelope()
        classification, _, lineage, eligibility, authorization, mission, packet = self._pipeline(envelope)
        self.assertEqual(classification["classification"], recovery.WORKER_RECOVERABLE)
        self.assertEqual(authorization["approval_id"], recovery.LIVE3_APPROVAL_ID)
        self.assertEqual(authorization["approval_receipt_hash"], recovery.LIVE3_APPROVAL_RECEIPT_HASH)
        self.assertEqual(authorization["plan_hash"], recovery.LIVE3_PLAN_HASH)
        self.assertEqual(mission["parent_plan_hash"], recovery.LIVE3_PLAN_HASH)
        self.assertEqual(packet["approval_receipt_hash"], recovery.LIVE3_APPROVAL_RECEIPT_HASH)
        self.assertEqual(lineage["failure_source"], recovery.WORKER_EXECUTION_FAILURE)
        self.assertEqual(lineage["execution_failure_code"], recovery.WORKER_NO_APPROVED_MUTATION)
        self.assertFalse(eligibility["USER_REAPPROVAL_REQUIRED"])
        self.assertFalse(authorization["user_reapproval_required"])


if __name__ == "__main__":
    unittest.main()
