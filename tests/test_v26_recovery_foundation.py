"""Provider-free V26 authority-bounded autonomous-recovery tests."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from hivo import recovery


ROOT = Path(__file__).resolve().parents[1]
LIVE3 = ROOT / "output" / "hivo-v25-6-stage6c-b-verification-closure-live-3"


class V26RecoveryFoundationTests(unittest.TestCase):
    """Exercise the V26 foundation without Gemma or a real Worker."""

    @classmethod
    def setUpClass(cls):
        cls.live3_bytes = {
            path.relative_to(LIVE3).as_posix(): path.read_bytes()
            for path in LIVE3.rglob("*")
            if path.is_file()
        }
        cls.data = recovery.load_live3_recovery_evidence(LIVE3)
        cls.envelope = recovery.build_recovery_failure_envelope(cls.data)
        cls.approved_authority = copy.deepcopy(cls.data["execution_authorization"])
        cls.classification = recovery.classify_recovery_failure(
            cls.envelope,
            approved_authority=cls.approved_authority,
        )
        cls.lineage = recovery.build_authorized_execution_lineage(
            cls.envelope,
            authorization=cls.approved_authority,
        )
        cls.lineage_validation = recovery.validate_authorized_execution_lineage(
            cls.lineage,
            envelope=cls.envelope,
        )
        cls.eligibility = recovery.decide_recovery_eligibility(
            cls.envelope,
            cls.classification,
            authority_delta=cls.classification["authority_delta"],
            lineage=cls.lineage,
            current_subject_hash=cls.envelope["current_subject_hash"],
            authorization=cls.approved_authority,
        )
        cls.recovery_authorization = recovery.build_approved_recovery_authorization(
            cls.envelope,
            classification=cls.classification,
            authority_delta=cls.classification["authority_delta"],
            lineage=cls.lineage,
            eligibility=cls.eligibility,
            approved_authority=cls.approved_authority,
        )
        cls.mission = recovery.build_recovery_mission(
            cls.envelope,
            cls.recovery_authorization,
            classification=cls.classification,
        )
        cls.packet = recovery.build_recovery_worker_packet(
            cls.mission,
            cls.recovery_authorization,
        )

    @staticmethod
    def _rehash_envelope(value):
        value["canonical_failure_envelope_hash"] = recovery.canonical_hash({
            key: item for key, item in value.items()
            if key not in {
                "canonical_failure_envelope_hash", "failure_envelope_hash",
                "canonical_hash",
            }
        })
        value["canonical_hash"] = value["canonical_failure_envelope_hash"]
        value["failure_envelope_hash"] = value["canonical_failure_envelope_hash"]
        return value

    def test_01_live3_failure_envelope_is_immutable_and_valid(self):
        self.assertIsInstance(self.envelope, recovery.RecoveryFailureEnvelope)
        self.assertTrue(recovery.validate_recovery_failure_envelope(self.envelope)["valid"])
        with self.assertRaises(TypeError):
            self.envelope["worker_result_status"] = "done"
        with self.assertRaises(TypeError):
            self.envelope["failed_verification_authority_ids"].append("OTHER")

    def test_02_live3_failure_identity_is_preserved_exactly(self):
        self.assertEqual(self.envelope["execution_id"], "WORKER-C0E7A209FF98944142C4142E")
        self.assertEqual(self.envelope["current_subject_hash"], recovery.LIVE3_FAILED_SUBJECT_HASH)
        for key, expected in {
            "authority_id": "VERIFICATION-004",
            "oracle_id": "ORACLE-PAUSE-INDICATOR",
            "oracle_hash": recovery.LIVE3_ORACLE_HASH,
            "failed_check": "export_callable",
            "detail": "renderPauseIndicator",
            "status": "FAIL",
            "execution_channel": "DIRECT_ORACLE_EXECUTION",
            "evidence_basis": "deterministic_failed_verification_receipt",
        }.items():
            self.assertEqual(self.envelope["failed_verification"][key], expected)
        self.assertEqual(self.envelope["scope_audit"]["status"], "PASS")
        self.assertEqual(self.envelope["dnt_audit"]["status"], "PASS")
        self.assertEqual(self.envelope["precommit_audit_summary"]["status"], "PASS")
        self.assertEqual(self.envelope["stage5b_status"], "INTEGRATION_NOT_READY")
        self.assertEqual(self.envelope["promotion_status"], "NOT_REACHED")
        self.assertTrue(self.envelope["brain_unchanged"])

    def test_03_worker_prose_has_zero_authority_and_is_not_copied(self):
        self.assertEqual(self.envelope["worker_prose_authority"], 0)
        self.assertTrue(self.envelope["worker_prose_excluded"])
        self.assertFalse(recovery.contains_forbidden_recovery_transcript(self.envelope))
        self.assertNotIn("worker_result", self.envelope)
        self.assertNotIn("messages", json.dumps(self.packet, ensure_ascii=False))
        self.assertFalse(recovery.contains_forbidden_recovery_transcript(self.packet))

    def test_04_live3_is_worker_recoverable_without_reapproval(self):
        self.assertEqual(self.classification["classification"], recovery.WORKER_RECOVERABLE)
        self.assertTrue(self.classification["authority_delta_empty"])
        self.assertFalse(self.classification["USER_REAPPROVAL_REQUIRED"])
        self.assertEqual(self.eligibility["status"], recovery.RECOVERY_ELIGIBLE)
        self.assertFalse(self.eligibility["USER_REAPPROVAL_REQUIRED"])

    def test_05_authority_delta_is_empty_and_immutable(self):
        delta = self.classification["authority_delta"]
        self.assertIsInstance(delta, recovery.RecoveryAuthorityDelta)
        self.assertTrue(delta["empty"])
        self.assertEqual(delta["changed_dimensions"], [])
        self.assertTrue(recovery.validate_recovery_authority_delta(delta)["valid"])
        with self.assertRaises(TypeError):
            delta["dimensions"]["new_requirements"].append({"bad": True})

    def test_06_lineage_validates_as_authorized_descendant(self):
        self.assertIsInstance(self.lineage, recovery.AuthorizedExecutionLineage)
        self.assertTrue(self.lineage_validation["valid"])
        self.assertEqual(
            self.lineage_validation["status"],
            recovery.AUTHORIZED_EXECUTION_DESCENDANT,
        )
        self.assertEqual(
            self.lineage["original_approved_subject_hash"],
            recovery.LIVE3_BASELINE_SUBJECT_HASH,
        )
        self.assertEqual(
            self.lineage["current_failed_subject_hash"],
            recovery.LIVE3_FAILED_SUBJECT_HASH,
        )
        self.assertEqual(
            self.lineage["resulting_subject_hash"],
            self.envelope["current_subject_hash"],
        )

    def test_07_mission_stays_under_same_authority(self):
        self.assertEqual(self.mission["status"], recovery.RECOVERY_MISSION_READY)
        self.assertEqual(self.mission["parent_plan_id"], recovery.LIVE3_PLAN_ID)
        self.assertEqual(self.mission["parent_plan_hash"], recovery.LIVE3_PLAN_HASH)
        self.assertEqual(self.mission["approval_id"], recovery.LIVE3_APPROVAL_ID)
        self.assertEqual(
            self.mission["approval_receipt_hash"],
            recovery.LIVE3_APPROVAL_RECEIPT_HASH,
        )
        self.assertEqual(
            self.mission["authorized_mutation_scope"]["paths"],
            ["src/status_view.js"],
        )
        self.assertIn("src/pause_controller.js", self.mission["dnt"]["paths"])
        self.assertIn("renderStatus primitive string", " ".join(self.mission["preservation_constraints"]))
        self.assertIn("PauseController", json.dumps(self.mission, ensure_ascii=False))
        self.assertEqual(self.mission["execution_invariant_set_hash"], recovery.LIVE3_INVARIANT_HASH)
        self.assertEqual(self.mission["verification_digest"], recovery.LIVE3_VERIFICATION_DIGEST)
        self.assertEqual(self.mission["coverage_hash"], recovery.LIVE3_COVERAGE_HASH)
        self.assertFalse(self.mission["new_plan_created"])
        self.assertFalse(self.mission["new_approval_created"])
        self.assertFalse(self.mission["new_requirement_ledger_created"])

    def test_08_recovery_authorization_is_derived_not_new_approval(self):
        self.assertIsInstance(
            self.recovery_authorization,
            recovery.ApprovedRecoveryAuthorization,
        )
        self.assertEqual(
            self.recovery_authorization["status"],
            recovery.RECOVERY_AUTHORIZATION_READY,
        )
        self.assertTrue(self.recovery_authorization["derived_from_existing_approval"])
        self.assertFalse(self.recovery_authorization["new_user_approval_created"])
        self.assertFalse(self.recovery_authorization["user_reapproval_required"])
        self.assertEqual(self.recovery_authorization["plan_hash"], recovery.LIVE3_PLAN_HASH)
        self.assertEqual(
            self.recovery_authorization["approval_receipt_hash"],
            recovery.LIVE3_APPROVAL_RECEIPT_HASH,
        )
        self.assertTrue(
            recovery.validate_approved_recovery_authorization(
                self.recovery_authorization,
                envelope=self.envelope,
            )["valid"],
        )

    def test_09_recovery_packet_is_fresh_bounded_and_complete(self):
        checked = recovery.validate_recovery_worker_packet(self.packet)
        self.assertTrue(checked["valid"], checked)
        self.assertLessEqual(checked["packet_chars"], recovery.RECOVERY_WORKER_PACKET_MAX_CHARS)
        self.assertLessEqual(self.packet["packet_chars"], 4200)
        self.assertEqual(self.packet["failed_verification"]["failed_check"], "export_callable")
        self.assertEqual(self.packet["failed_verification"]["detail"], "renderPauseIndicator")
        self.assertFalse(self.packet["historical_transcript_included"])
        self.assertEqual(self.packet["historical_generation_count"], 0)
        self.assertEqual(self.packet["worker_prose_authority"], 0)

    def test_10_provider_free_dispatch_reaches_injected_seam_once(self):
        calls = []

        def injected(**kwargs):
            calls.append(kwargs)
            return {"status": "failed", "messages": ["private prose must not escape"]}

        accounting = recovery.create_recovery_attempt_accounting()
        result = recovery.dispatch_recovery_worker(
            self.mission,
            self.recovery_authorization,
            {"subject_hash": recovery.LIVE3_FAILED_SUBJECT_HASH},
            {"execution_invariant_set_hash": recovery.LIVE3_INVARIANT_HASH},
            {"paths": ["src/pause_controller.js"]},
            {"authority_ids": ["VERIFICATION-004"]},
            injected,
            accounting=accounting,
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(result["recovery_dispatch_count"], 1)
        self.assertEqual(result["recovery_callback_calls"], 1)
        self.assertEqual(result["injected_recovery_worker_seam"], "REACHED_ONCE")
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)
        self.assertEqual(result["worker_calls"], 0)
        self.assertNotIn("messages", result["callback_result"])

    def test_11_callback_type_error_is_not_retried(self):
        calls = []

        def injected(**kwargs):
            calls.append(1)
            raise TypeError("synthetic callback failure")

        result = recovery.dispatch_recovery_worker(
            self.mission,
            self.recovery_authorization,
            {},
            {},
            {},
            {},
            injected,
        )
        self.assertEqual(calls, [1])
        self.assertEqual(result["status"], recovery.RECOVERY_CALLBACK_FAILED)
        self.assertEqual(result["recovery_callback_calls"], 1)

    def test_12_authority_change_dimensions_fail_closed(self):
        cases = (
            ({"required_mutation_paths": ["src/new_file.js"]}, "new_mutation_paths"),
            ({"requires_dnt_change": True, "dnt_paths": ["src/pause_controller.js"]}, "dnt_changes"),
            ({"renderStatus_return_type_change": "primitive string -> object"}, "interface_semantic_changes"),
            ({"owner_migration": "StatusView"}, "ownership_changes"),
            ({"verification_weakening": ["VERIFICATION-004"]}, "verification_authority_changes"),
        )
        for proposal, dimension in cases:
            with self.subTest(dimension=dimension):
                classified = recovery.classify_recovery_failure(
                    self.envelope,
                    approved_authority=self.approved_authority,
                    recovery_need=proposal,
                )
                self.assertEqual(classified["classification"], recovery.AUTHORITY_CHANGE_REQUIRED)
                self.assertIn(dimension, classified["authority_delta"]["changed_dimensions"])
                self.assertTrue(classified["USER_REAPPROVAL_REQUIRED"])
                blocked = recovery.decide_recovery_eligibility(
                    self.envelope,
                    classified,
                    authority_delta=classified["authority_delta"],
                    lineage=self.lineage,
                    current_subject_hash=self.envelope["current_subject_hash"],
                    authorization=self.approved_authority,
                )
                self.assertFalse(blocked["eligible"])
                self.assertTrue(blocked["USER_REAPPROVAL_REQUIRED"])

    def test_13_verification_weakening_is_not_an_automatic_retry(self):
        proposal = {"ignore_verification": ["VERIFICATION-004"]}
        delta = recovery.build_recovery_authority_delta(
            self.approved_authority,
            proposal,
        )
        auth = recovery.build_approved_recovery_authorization(
            self.envelope,
            classification=recovery.AUTHORITY_CHANGE_REQUIRED,
            authority_delta=delta,
            lineage=self.lineage,
            approved_authority=self.approved_authority,
        )
        self.assertEqual(auth["status"], recovery.RECOVERY_AUTHORIZATION_BLOCKED)
        self.assertTrue(auth["user_reapproval_required"])

    def test_14_external_drift_is_not_an_authorized_descendant(self):
        checked = recovery.validate_authorized_execution_lineage(
            self.lineage,
            current_subject_hash="b" * 64,
            envelope=self.envelope,
        )
        self.assertFalse(checked["valid"])
        self.assertEqual(checked["subject_drift"], recovery.EXTERNAL_UNAUTHORIZED_DRIFT)
        self.assertTrue(checked["external_unauthorized_drift"])
        eligibility = recovery.decide_recovery_eligibility(
            self.envelope,
            self.classification,
            authority_delta=self.classification["authority_delta"],
            lineage=self.lineage,
            current_subject_hash="b" * 64,
            authorization=self.approved_authority,
        )
        self.assertFalse(eligibility["eligible"])

    def test_15_tampered_mutation_scope_and_dnt_receipts_block(self):
        for receipt_name, field, replacement in (
            ("mutation_receipt", "changed_paths", ["src/unknown.js"]),
            ("scope_receipt", "passed", False),
            ("dnt_receipt", "changed_paths", ["src/pause_controller.js"]),
        ):
            with self.subTest(receipt=receipt_name):
                tampered = copy.deepcopy(self.lineage)
                tampered[receipt_name][field] = replacement
                checked = recovery.validate_authorized_execution_lineage(
                    tampered,
                    envelope=self.envelope,
                )
                self.assertFalse(checked["valid"])
                self.assertEqual(checked["status"], recovery.INVALID_AUTHORIZED_EXECUTION_DESCENDANT)
                self.assertTrue(checked["errors"])

    def test_16_tampered_start_binding_or_failed_closure_blocks(self):
        for field, replacement in (
            ("execution_start_id", "START-TAMPERED"),
            ("failed_verification_closure_hash", "0" * 64),
        ):
            with self.subTest(field=field):
                tampered = copy.deepcopy(self.lineage)
                tampered[field] = replacement
                checked = recovery.validate_authorized_execution_lineage(
                    tampered,
                    envelope=self.envelope,
                )
                self.assertFalse(checked["valid"])

    def test_17_contaminated_brain_is_architecture_failure(self):
        contaminated = self._rehash_envelope(copy.deepcopy(self.envelope))
        contaminated["brain_unchanged"] = False
        self._rehash_envelope(contaminated)
        classified = recovery.classify_recovery_failure(
            contaminated,
            approved_authority=self.approved_authority,
        )
        self.assertEqual(
            classified["classification"],
            recovery.NON_RECOVERABLE_ARCHITECTURE_FAILURE,
        )

    def test_18_uncertain_evidence_does_not_guess_worker_recoverable(self):
        uncertain = {
            "schema_version": recovery.SCHEMA_VERSION,
            "artifact_type": recovery.RECOVERY_FAILURE_ENVELOPE,
            "worker_result_status": "failed",
            "failure": "verification failed",
        }
        classified = recovery.classify_recovery_failure(uncertain)
        self.assertEqual(
            classified["classification"],
            recovery.RECOVERY_CLASSIFICATION_UNCERTAIN,
        )

    def test_19_known_harness_failure_is_harness_recoverable(self):
        harness = copy.deepcopy(self.envelope)
        harness["subject_after_hash"] = harness["subject_before_hash"]
        harness["current_subject_hash"] = harness["subject_before_hash"]
        harness["failure_code"] = "RUNNER_INVOCATION_FAILURE"
        self._rehash_envelope(harness)
        classified = recovery.classify_recovery_failure(
            harness,
            approved_authority=self.approved_authority,
        )
        self.assertEqual(classified["classification"], recovery.HARNESS_RECOVERABLE)

    def test_20_capability_floor_requires_bounded_repeated_evidence(self):
        first = recovery.classify_recovery_failure(self.envelope)
        self.assertNotEqual(first["classification"], recovery.CAPABILITY_FLOOR)
        history = [
            {"clean": True},
            {"clean": True},
        ]
        classified = recovery.classify_recovery_failure(
            self.envelope,
            recovery_attempt_history=history,
        )
        self.assertEqual(classified["classification"], recovery.CAPABILITY_FLOOR)

    def test_21_attempt_budget_allows_one_and_blocks_second(self):
        accounting = recovery.create_recovery_attempt_accounting()
        self.assertTrue(recovery.can_start_recovery_attempt(accounting)["allowed"])
        consumed = recovery.consume_recovery_attempt(accounting, outcome="failed")
        self.assertEqual(consumed["recovery_attempts_started"], 1)
        self.assertFalse(recovery.can_start_recovery_attempt(consumed, attempt_index=2)["allowed"])
        self.assertEqual(
            recovery.consume_recovery_attempt(consumed, attempt_index=2)["status"],
            recovery.RECOVERY_BUDGET_EXHAUSTED,
        )

    def test_22_positive_injected_replay_reaches_all_future_boundaries(self):
        result = recovery.run_provider_free_recovery_replay(LIVE3, outcome="success")
        self.assertEqual(result["stage5a"]["status"], "PASS")
        self.assertTrue(result["stage5a"]["execution_verification_closure"]["all_required_passed"])
        self.assertEqual(result["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(result["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(result["reentry"]["status"], "REENTRY_READY")
        self.assertEqual(result["recovery_callback_calls"], 1)
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)
        self.assertFalse(result["new_approval_created"])
        self.assertFalse(result["new_plan_created"])

    def test_23_negative_injected_replay_stops_without_promotion(self):
        result = recovery.run_provider_free_recovery_replay(LIVE3, outcome="failure")
        self.assertFalse(result["stage5a"]["passed"])
        self.assertEqual(result["stage5a"]["status"], "FAIL")
        self.assertIsNone(result["stage5b"])
        self.assertIsNone(result["stage5c"])
        self.assertIsNone(result["reentry"])
        self.assertTrue(result["brain_unchanged"])
        self.assertEqual(result["second_dispatch"]["status"], recovery.RECOVERY_BUDGET_EXHAUSTED)
        self.assertEqual(result["recovery_callback_calls"], 1)
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)

    def test_24_historical_live3_is_unchanged_after_all_replays(self):
        recovery.run_provider_free_recovery_replay(LIVE3, outcome="success")
        recovery.run_provider_free_recovery_replay(LIVE3, outcome="failure")
        for relative, before in self.live3_bytes.items():
            self.assertEqual((LIVE3 / relative).read_bytes(), before, relative)

    def test_25_architecture_self_test_passes_provider_free(self):
        result = recovery.run_recovery_architecture_self_test(LIVE3)
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["gemma_calls"], 0)
        self.assertEqual(result["real_worker_calls"], 0)
        self.assertEqual(result["worker_calls"], 0)


if __name__ == "__main__":
    unittest.main()
