"""Provider-free V25.4 verification-complete plan revision tests."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import approval_authority as authority
from hivo import verification_gap_remediation as remediation
from hivo import verification_obligation_coverage as coverage


ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
HISTORICAL_DB = (
    ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1"
    / ".hivo" / "memory.sqlite3"
)
BEHAVIOR_ID = "OBL-REQ-PAUSE-INDICATOR-BEHAVIOR-CHANGE-01"
OLD_PLAN_ID = "PLAN-D8B51EE5EC97"
OLD_PLAN_HASH = "d8b51ee5ec97a54f1d4e5caff5ccbb9d2f5c9f02935c4ea8a88745f4f9275a73"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class VerificationCompletePlanRevisionTests(unittest.TestCase):
    """All revision and oracle paths are deterministic and provider-free."""

    @classmethod
    def setUpClass(cls):
        cls.result = mini.run_stage6c_b_v25_4_self_test()
        if cls.result.get("passed") is not True:
            raise AssertionError(cls.result)
        cls.old_plan = _load(PLANNING_ROOT / "final_plan.json")
        cls.observable = cls.result["observable_contract"]
        cls.oracle = cls.result["direct_behavior_oracle"]
        cls.proposal = cls.result["proposal"]
        cls.revised_plan = cls.result["revised_plan"]
        cls.coverage = cls.result["revised_coverage"]

    @staticmethod
    def _generic_parts():
        observable = remediation.build_behavior_observable_contract(
            contract_id="BOC-GENERIC-BANNER",
            target_path="lib/banner_view.js",
            symbol="renderBanner",
            signature="renderBanner(sessionState)",
            export={
                "kind": remediation.ADDITIVE_EXPORT,
                "path": "lib/banner_view.js",
                "symbol": "renderBanner",
            },
            state_source={"owner": "SessionState", "interface": "isActive"},
            running={"return_type": "primitive string", "equals": "", "non_empty": False},
            paused={"return_type": "primitive string", "non_empty": True},
            legacy_interface={
                "symbol": "renderLegacyBanner",
                "signature": "renderLegacyBanner(sessionState)",
                "return_type": "primitive string",
                "outputs": ["idle", "active"],
                "change_authorized": False,
            },
        )
        oracle = remediation.build_direct_behavior_oracle_spec(
            oracle_id="ORACLE-GENERIC-BANNER",
            obligation_id="OBL-GENERIC-BANNER",
            target_module_path="lib/banner_view.js",
            target_symbol="renderBanner",
            function_signature="renderBanner(sessionState)",
            controller_module_path="lib/session_state.js",
            controller_symbol="SessionState",
            state_query_symbol="isActive",
            toggle_symbol="toggle",
            running_expectation={
                "return_type": "primitive string", "equals": "", "non_empty": False,
            },
            paused_expectation={
                "return_type": "primitive string", "non_empty": True,
            },
            legacy_compatibility=[{
                "symbol": "renderLegacyBanner",
                "signature": "renderLegacyBanner(sessionState)",
                "return_type": "primitive string",
                "outputs": ["idle", "active"],
                "preserve": True,
            }],
            source_plan_reference={"plan_id": "PLAN-GENERIC", "plan_hash": "a" * 64},
            observable_contract_hash=observable["contract_hash"],
        )
        proposal = remediation.build_verification_gap_remediation_proposal(
            proposal_id="REMEDIATION-GENERIC-BANNER",
            old_plan_id="PLAN-GENERIC",
            old_plan_hash="a" * 64,
            v25_3_coverage_hash="b" * 64,
            uncovered_obligation_id="OBL-GENERIC-BANNER",
            obligation_type=coverage.BEHAVIOR_CHANGE,
            proposed_observable_contract=observable,
            proposed_direct_oracle=oracle,
            affected_mutation_surface={
                "paths": ["lib/banner_view.js"],
                "surface_ids": ["SURF-GENERIC"],
            },
            preservation_references=["SessionState ownership", "legacy banner output"],
        )
        return observable, oracle, proposal

    def test_exact_uncovered_behavior_obligation_is_loaded(self):
        self.assertEqual(
            self.result["old_plan"]["uncovered_obligation_ids"], [BEHAVIOR_ID]
        )
        self.assertEqual(self.result["old_plan"]["plan_id"], OLD_PLAN_ID)
        self.assertEqual(self.result["old_plan"]["plan_hash"], OLD_PLAN_HASH)

    def test_proposal_targets_exact_obligation_and_is_not_authority(self):
        self.assertEqual(self.proposal["uncovered_obligation_id"], BEHAVIOR_ID)
        self.assertFalse(self.proposal["execution_authority"])
        self.assertTrue(self.proposal["fresh_approval_required"])
        self.assertFalse(self.proposal["worker_mutable"])
        self.assertEqual(
            self.proposal["proposal_provenance"],
            remediation.VERIFICATION_OBLIGATION_UNCOVERED,
        )

    def test_observable_contract_canonicalizes_and_is_immutable(self):
        rebuilt = remediation.build_behavior_observable_contract(
            contract_id=self.observable["contract_id"],
            target_path=self.observable["target_path"],
            symbol=self.observable["symbol"],
            signature=self.observable["signature"],
            export=self.observable["export"],
            state_source=self.observable["state_source"],
            running=self.observable["running"],
            paused=self.observable["paused"],
            legacy_interface=self.observable["legacy_interface"],
        )
        self.assertEqual(rebuilt["contract_hash"], self.observable["contract_hash"])
        self.assertEqual(
            remediation.validate_behavior_observable_contract(rebuilt)["valid"], True
        )
        with self.assertRaises(TypeError):
            rebuilt["new_state_owner"] = True

    def test_observable_preserves_legacy_interface_and_state_owner(self):
        self.assertEqual(self.observable["target_path"], "src/status_view.js")
        self.assertEqual(self.observable["export"]["kind"], remediation.ADDITIVE_EXPORT)
        self.assertFalse(self.observable["new_state_owner"])
        self.assertFalse(self.observable["worker_mutable"])
        self.assertEqual(self.observable["state_source"]["owner"], "PauseController")
        legacy = self.observable["legacy_interface"]
        self.assertEqual(legacy["symbol"], "renderStatus")
        self.assertEqual(legacy["return_type"], "primitive string")
        self.assertEqual(legacy["outputs"], ["Running", "Paused"])
        self.assertFalse(legacy["change_authorized"])

    def test_observable_stays_inside_approved_mutation_surface(self):
        self.assertEqual(
            self.proposal["affected_mutation_surface"]["paths"], ["src/status_view.js"]
        )
        self.assertEqual(self.observable["target_path"], "src/status_view.js")
        self.assertNotIn("src/pause_controller.js", self.proposal["affected_mutation_surface"]["paths"])

    def test_direct_oracle_canonicalizes_and_is_verifier_owned(self):
        self.assertEqual(
            remediation.validate_direct_behavior_oracle_spec(
                self.oracle, self.observable,
            )["valid"], True
        )
        self.assertEqual(self.oracle["oracle_hash"], remediation.direct_behavior_oracle_hash(self.oracle))
        self.assertEqual(self.oracle["oracle_type"], coverage.FOCUSED_TEST)
        self.assertEqual(self.oracle["coverage_relationship"], coverage.DIRECT)
        self.assertTrue(self.oracle["mandatory"])
        self.assertTrue(self.oracle["applicable"])
        self.assertEqual(self.oracle["oracle_owner"], remediation.HIVO_VERIFIER)
        self.assertFalse(self.oracle["worker_mutable"])
        self.assertEqual(self.oracle["oracle_artifact_paths"], [])
        _observable, frozen_oracle, _proposal = self._generic_parts()
        with self.assertRaises(TypeError):
            frozen_oracle["mandatory"] = False

    def test_oracle_represents_running_paused_and_legacy_assertions(self):
        self.assertEqual(self.oracle["running_expectation"]["equals"], "")
        self.assertFalse(self.oracle["running_expectation"]["non_empty"])
        self.assertEqual(self.oracle["running_expectation"]["return_type"], "primitive string")
        self.assertTrue(self.oracle["paused_expectation"]["non_empty"])
        self.assertEqual(self.oracle["paused_expectation"]["return_type"], "primitive string")
        self.assertEqual(self.oracle["checks"][0]["kind"], "EXPORT_CALLABLE")
        self.assertEqual(self.oracle["checks"][1]["kind"], "RUNNING_PRIMITIVE_STRING")
        self.assertEqual(self.oracle["checks"][2]["kind"], "PAUSED_PRIMITIVE_STRING_NON_EMPTY")
        legacy = self.oracle["legacy_compatibility"][0]
        self.assertEqual(legacy["symbol"], "renderStatus")
        self.assertEqual(legacy["outputs"], ["Running", "Paused"])
        self.assertTrue(legacy["preserve"])

    def test_positive_oracle_fixture_passes(self):
        self.assertEqual(self.result["oracle_runs"]["positive"]["status"], remediation.PASS)
        names = {item["name"] for item in self.result["oracle_runs"]["positive"]["checks"]}
        self.assertIn("running_primitive_string", names)
        self.assertIn("paused_non_empty", names)
        self.assertIn("state_source_is_supplied_controller", names)

    def test_missing_export_fixture_fails(self):
        self.assertEqual(self.result["oracle_runs"]["missing_export"]["status"], remediation.FAIL)

    def test_paused_empty_fixture_fails(self):
        self.assertEqual(self.result["oracle_runs"]["paused_empty"]["status"], remediation.FAIL)

    def test_non_string_fixture_fails(self):
        self.assertEqual(self.result["oracle_runs"]["paused_non_string"]["status"], remediation.FAIL)

    def test_legacy_render_status_break_fixture_fails(self):
        self.assertEqual(self.result["oracle_runs"]["legacy_render_break"]["status"], remediation.FAIL)

    def test_old_three_verification_contracts_remain_unchanged(self):
        revised = self.revised_plan["canonical_verification_contracts"]
        self.assertEqual(revised[:3], self.old_plan["canonical_verification_contracts"])
        self.assertEqual(len(revised), 4)
        self.assertEqual(revised[3]["verification_id"], "VERIFICATION-004")

    def test_fourth_contract_is_mandatory_direct_oracle_authority(self):
        record = self.revised_plan["canonical_verification_contracts"][3]
        self.assertTrue(record["approved"])
        self.assertTrue(record["mandatory"])
        self.assertEqual(record["oracle_type"], coverage.FOCUSED_TEST)
        self.assertEqual(record["oracle_id"], self.oracle["oracle_id"])
        self.assertEqual(record["oracle_hash"], self.oracle["oracle_hash"])
        self.assertEqual(record["obligation_bindings"][0]["obligation_id"], BEHAVIOR_ID)
        self.assertEqual(record["obligation_bindings"][0]["coverage_relationship"], coverage.DIRECT)

    def test_revised_coverage_is_four_of_four(self):
        self.assertEqual(self.coverage["status"], remediation.EXECUTION_VERIFICATION_READY)
        self.assertEqual(self.coverage["uncovered_obligation_ids"], [])
        self.assertEqual(self.coverage["new_behavior_oracle_count"], 1)
        self.assertEqual(
            [item["coverage_state"] for item in self.coverage["obligation_coverage"]],
            [coverage.COVERED] * 4,
        )

    def test_ownership_escape_and_movement_obligations_remain_covered(self):
        by_id = {
            item["obligation_id"]: item
            for item in self.coverage["obligation_coverage"]
        }
        for obligation_id in (
            "OBL-REQ-PAUSE-INDICATOR-PRESERVATION-02",
            "OBL-REQ-PAUSE-INDICATOR-PRESERVATION-03",
            "OBL-REQ-PAUSE-INDICATOR-PRESERVATION-04",
        ):
            self.assertEqual(by_id[obligation_id]["coverage_state"], coverage.COVERED)

    def test_old_plan_remains_uncovered(self):
        self.assertEqual(
            self.result["old_plan"]["coverage_status"],
            remediation.VERIFICATION_OBLIGATION_UNCOVERED,
        )
        self.assertEqual(self.result["old_plan"]["uncovered_obligation_ids"], [BEHAVIOR_ID])

    def test_revised_digest_and_identity_are_new(self):
        self.assertNotEqual(
            self.result["old_verification_digest"],
            self.result["revised_request"]["verification_contract_digest"],
        )
        self.assertNotEqual(self.revised_plan["plan_id"], OLD_PLAN_ID)
        self.assertNotEqual(self.revised_plan["plan_hash"], OLD_PLAN_HASH)

    def test_old_approval_is_historically_valid_but_not_revised_authority(self):
        self.assertTrue(self.result["checks"]["old_receipt_remains_valid_alone"])
        self.assertTrue(self.result["checks"]["old_receipt_matches_old_request"])
        self.assertTrue(self.result["checks"]["old_receipt_rejected_for_revised_request"])
        self.assertEqual(
            self.result["historical_approval"]["approval_id"],
            "APPROVAL-40A2E163818B30E1",
        )
        self.assertEqual(
            self.result["historical_approval"]["receipt_hash"],
            "42c10f682f0a94ba2588aff727399c7a5aa745f570703020cb137ec8ab11e2c3",
        )
        self.assertEqual(
            self.result["historical_approval"]["plan_id"], OLD_PLAN_ID,
        )
        self.assertEqual(
            self.result["historical_approval"]["plan_hash"], OLD_PLAN_HASH,
        )

    def test_fresh_approval_boundary_stops_before_execution(self):
        self.assertEqual(
            self.revised_plan["terminal_state"], remediation.PLAN_APPROVAL_REQUIRED
        )
        self.assertTrue(self.revised_plan["approval_required"])
        self.assertFalse(self.revised_plan["approval_granted"])
        self.assertTrue(self.result["checks"]["no_revised_approval_or_authorization"])

    def test_stage4_contractability_binds_scope_dnt_oracle_and_coverage(self):
        self.assertTrue(self.result["checks"]["contractability_passes_but_is_ineligible"])
        self.assertTrue(self.result["checks"]["coverage_bound_contract_is_ready"])
        mutation = next(
            item for item in self.result["contractability"]["contracts"]
            if item["responsibility_type"] == "MUTATION"
        )
        self.assertEqual(mutation["allowed_mutation_paths"], ["src/status_view.js"])
        self.assertEqual(mutation["global_do_not_touch"], ["src/pause_controller.js"])
        self.assertEqual(len(mutation["approved_additive_observables"]), 1)
        self.assertEqual(
            mutation["verification_obligation_coverage_status"],
            remediation.EXECUTION_VERIFICATION_READY,
        )
        self.assertEqual(
            mutation["verification_obligation_coverage_hash"],
            self.coverage["coverage_hash"],
        )

    def test_worker_packet_contains_new_semantics_and_legacy_invariants(self):
        packet = self.result["worker_packet_budget"]
        packet_text = self.result["worker_packet"]
        self.assertEqual(self.observable["symbol"], "renderPauseIndicator")
        self.assertTrue(self.result["checks"]["worker_packet_contains_new_authority"])
        for marker in (
            "renderPauseIndicator(pauseController)",
            'run=""',
            "pause=non-empty primitive string",
            "renderStatus",
            "CURRENT EXECUTION INVARIANTS",
        ):
            self.assertIn(marker, packet_text)
        self.assertTrue(self.result["checks"]["worker_projection_valid"])
        self.assertEqual(packet["mandatory_drops"], 0)
        self.assertEqual(packet["context_limit"], 4200)

    def test_worker_packet_budget_has_only_deterministic_fan_in(self):
        packet = self.result["worker_packet_budget"]
        self.assertEqual(packet["old_v25_2_chars"], 4151)
        self.assertEqual(packet["raw_revised_chars"], 4296)
        self.assertEqual(packet["final_revised_chars"], 4192)
        self.assertEqual(packet["headroom"], 8)
        self.assertEqual(packet["deduplicated_chars"], 104)
        self.assertEqual(packet["authority_items_dropped"], 0)
        self.assertEqual(packet["invariant_items_dropped"], 0)
        self.assertEqual(len(packet["deduplication"]), 4)

    def test_revised_plan_and_packet_limits_remain_fixed(self):
        self.assertLessEqual(self.revised_plan["serialized_chars"], 18000)
        self.assertEqual(self.result["worker_packet_budget"]["context_limit"], 4200)
        revision = self.revised_plan["verification_authority_revision"]
        self.assertEqual(revision["reason"], remediation.VERIFICATION_OBLIGATION_UNCOVERED)
        self.assertTrue(self.result["checks"]["revised_authority_valid"])

    def test_approval_summary_is_compact_immutable_and_complete(self):
        summary = self.result["approval_summary"]
        self.assertEqual(summary["plan_id"], self.revised_plan["plan_id"])
        self.assertEqual(summary["plan_hash"], self.revised_plan["plan_hash"])
        self.assertEqual(summary["verification_coverage"]["covered"], 4)
        self.assertEqual(summary["verification_coverage"]["required"], 4)
        self.assertTrue(summary["fresh_approval_required"])
        self.assertFalse(summary["approval_granted"])
        self.assertEqual(
            summary["summary_hash"], remediation.approval_summary_hash(summary)
        )

    def test_hash_chain_changes_when_oracle_semantics_change(self):
        changed = copy.deepcopy(self.oracle)
        changed["paused_expectation"]["non_empty"] = False
        changed["oracle_hash"] = remediation.direct_behavior_oracle_hash(changed)
        self.assertNotEqual(changed["oracle_hash"], self.oracle["oracle_hash"])

        revised_records = copy.deepcopy(self.revised_plan["canonical_verification_contracts"])
        revised_records[3]["oracle_hash"] = changed["oracle_hash"]
        altered_plan = {"canonical_verification_contracts": revised_records}
        original_binding = authority.build_approval_authority_binding(
            {"canonical_verification_contracts": self.revised_plan["canonical_verification_contracts"]},
            {},
        )
        altered_binding = authority.build_approval_authority_binding(altered_plan, {})
        self.assertNotEqual(
            original_binding["verification_contract_digest"],
            altered_binding["verification_contract_digest"],
        )

        altered_coverage = copy.deepcopy(self.coverage)
        altered_coverage["coverage_hash"] = coverage.canonical_coverage_hash(
            altered_coverage
        )
        self.assertNotEqual(altered_coverage["coverage_hash"], self.coverage["coverage_hash"])

    def test_generic_alternate_remediation_has_no_fixture_hardcoding(self):
        observable, oracle, proposal = self._generic_parts()
        self.assertTrue(
            remediation.validate_verification_gap_remediation_proposal(proposal)["valid"]
        )
        with tempfile.TemporaryDirectory(prefix="hivo_v25_4_generic_") as temp:
            root = Path(temp)
            (root / "lib").mkdir()
            (root / "lib" / "session_state.js").write_text(
                """class SessionState {
  constructor() { this.active = false; }
  isActive() { return this.active; }
  toggle() { this.active = !this.active; }
}
module.exports = { SessionState };
""",
                encoding="utf-8",
            )
            (root / "lib" / "banner_view.js").write_text(
                """function renderBanner(sessionState) {
  return sessionState.isActive() ? 'ACTIVE' : '';
}
function renderLegacyBanner(sessionState) {
  return sessionState.isActive() ? 'active' : 'idle';
}
module.exports = { renderBanner, renderLegacyBanner };
""",
                encoding="utf-8",
            )
            result = remediation.execute_direct_behavior_oracle(
                oracle, root, observable_contract=observable,
            )
        self.assertEqual(result["status"], remediation.PASS)
        self.assertEqual(result["model_calls"], 0)
        self.assertEqual(result["worker_calls"], 0)

    def test_out_of_scope_remediation_is_rejected(self):
        _observable, _oracle, proposal = self._generic_parts()
        checked = remediation.validate_verification_gap_remediation_proposal(
            proposal, old_plan=self.old_plan,
        )
        self.assertFalse(checked["valid"])
        self.assertTrue(any("outside approved mutation scope" in item for item in checked["errors"]))

    def test_interface_breaking_remediation_is_rejected(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["proposed_observable_contract"]["legacy_interface"]["return_type"] = "object"
        checked = remediation.validate_verification_gap_remediation_proposal(proposal)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("legacy interface" in item for item in checked["errors"]))

    def test_worker_owned_oracle_is_rejected(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["proposed_direct_oracle"]["oracle_owner"] = "WORKER"
        proposal["proposed_direct_oracle"]["worker_mutable"] = True
        checked = remediation.validate_verification_gap_remediation_proposal(proposal)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("owned by the HIVO verifier" in item for item in checked["errors"]))

    def test_source_presence_only_oracle_is_rejected(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["proposed_direct_oracle"]["checks"] = [{"kind": "SOURCE_PRESENCE_ONLY"}]
        checked = remediation.validate_verification_gap_remediation_proposal(proposal)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("direct oracle" in item for item in checked["errors"]))

    def test_missing_direct_oracle_is_rejected(self):
        proposal = copy.deepcopy(self.proposal)
        proposal["proposed_direct_oracle"] = {}
        checked = remediation.validate_verification_gap_remediation_proposal(proposal)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("direct oracle" in item for item in checked["errors"]))

    def test_all_model_worker_brain_counters_are_zero(self):
        self.assertEqual(self.result["model_calls"], 0)
        self.assertEqual(self.result["worker_calls"], 0)
        self.assertEqual(self.result["historical_brain_writes"], 0)
        self.assertEqual(self.result["repository_subject_mutations"], 0)
        self.assertTrue(self.result["checks"]["zero_model_and_worker_calls"])

    def test_historical_plan_approval_and_subject_are_unchanged(self):
        self.assertTrue(self.result["checks"]["historical_brain_unchanged"])
        self.assertTrue(self.result["checks"]["historical_subject_unchanged"])
        self.assertEqual(self.old_plan["plan_id"], OLD_PLAN_ID)
        self.assertEqual(self.old_plan["plan_hash"], OLD_PLAN_HASH)
        self.assertTrue(HISTORICAL_DB.is_file())


if __name__ == "__main__":
    unittest.main()
