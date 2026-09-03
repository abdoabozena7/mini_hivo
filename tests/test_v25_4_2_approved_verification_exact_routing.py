"""Provider-free V25.4.2 exact approved-verification routing regressions."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import approval_bound_execution as stage5
from hivo import verification_routing as routing


ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = ROOT / "output" / "hivo-v25-4-1-stage6c-b-verification-complete-live-1"
ARTIFACT_ROOT = LIVE_ROOT / "artifacts"
HISTORICAL_DB = (
    ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1"
    / ".hivo" / "memory.sqlite3"
)
SUBJECT_FILES = (
    "src/input.js", "src/pause_controller.js", "src/status_view.js",
    "tests/input.test.js", "tests/pause_flow.integration.test.js",
    "tests/status_view.test.js",
)
EXPECTED_TARGETS = {
    "tests/input.test.js", "src/input.js",
    "tests/pause_flow.integration.test.js", "tests/status_view.test.js",
}
EXPECTED_PLAN_HASH = "5e9d01b255c23753eafa3fa76160b91b8b92486506580ffaf11f582b9522115a"
EXPECTED_COVERAGE_HASH = "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402"
EXPECTED_VERIFICATION_DIGEST = "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51"
EXPECTED_ORACLE_HASH = "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140"
EXPECTED_RECEIPT_HASH = "b94af87ad1847cd277a5f671dedcd276827c137219504cd9f3b0361360f194a3"


def _load(name: str, field: str | None = None):
    value = json.loads((ARTIFACT_ROOT / name).read_text(encoding="utf-8"))
    return value.get(field) if field else value


class ApprovedVerificationExactRoutingTests(unittest.TestCase):
    """The approved set is closed at execution time and remains fail-closed."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load("revised_plan_source.json", "plan")
        cls.authorization = _load("execution_authorization.json")
        stage4 = _load("stage4_contracts.json")
        cls.contract = next(
            item for item in stage4["contracts"]
            if item.get("responsibility_type") == "MUTATION"
        )
        cls.persisted_applicability = _load("verification_applicability.json")
        cls.oracle = _load("direct_behavior_oracle_source.json")["oracle"]
        cls.final_summary = _load("final_validation_summary.json")
        cls.packet_audit = _load("worker_packet_audit.json")
        cls.approval_validation = _load("approval_receipt_validation.json")
        cls.receipt = _load("approval_receipt.json")
        cls.self_test = mini.run_stage6c_b_v25_4_2_self_test(
            artifact_root=LIVE_ROOT,
            brain_database_path=HISTORICAL_DB,
        )

    def build(self, *, workspace=LIVE_ROOT, authorization=None, contract=None):
        return stage5.build_stage5a_verification_input(
            task={"id": "EXEC-001"},
            contract=contract or self.contract,
            authorization=authorization or self.authorization,
            workspace=workspace,
            post_subject=stage5.enumerate_execution_subject(workspace),
            execution_result={},
        )

    def test_01_latest_live_null_route_reproduced_pre_fix(self):
        records = self.authorization["approved_verification_contracts"]
        direct = next(item for item in records if item["verification_id"] == "VERIFICATION-004")
        lossy = {"verification_id": direct["verification_id"], "contract": direct["contract"]}
        known_files = [item["path"] for item in stage5.enumerate_execution_subject(LIVE_ROOT)["paths"]]
        known_tests = stage5._known_test_files(LIVE_ROOT, known_files)
        artifact = routing.analyze_verification_applicability(
            {"id": "EXEC-001"}, self.contract,
            {"files": known_files, "tests": known_tests, "entrypoints": []},
            test_contract=lossy["contract"],
            mutation_paths=self.contract.get("allowed_mutation_paths", []),
            inspection_paths=self.contract.get("allowed_inspection_paths", []),
            workspace=LIVE_ROOT, known_test_files=known_tests,
        )
        route = next(item for item in artifact["verification_routes"] if item.get("required"))
        self.assertIsNone(route["target"])
        self.assertIn(routing.AMBIGUOUS_SUPPORTED_TARGET, route["reason_codes"])
        self.assertEqual(route["result"], routing.BLOCKED_REQUIRED_TARGET_MISSING)

    def test_02_exact_origin_is_metadata_loss_then_generic_inference(self):
        record = next(
            item for item in self.authorization["approved_verification_contracts"]
            if item["verification_id"] == "VERIFICATION-004"
        )
        preserved = next(
            item for item in stage5._verification_contract_records(self.authorization, self.contract)
            if item["verification_id"] == "VERIFICATION-004"
        )
        self.assertEqual(preserved["target"], "src/status_view.js")
        self.assertEqual(preserved["oracle_id"], "ORACLE-PAUSE-INDICATOR")
        self.assertEqual(record["target"], preserved["target"])
        self.assertEqual(
            self.self_test["pre_fix"]["source"],
            "lossy approved-record projection -> generic _test_target",
        )

    def test_03_exact_approved_target_precedes_discovery(self):
        authority = {
            "verification_id": "V-EXACT",
            "contract": ["tests/approved.test.js protects the behavior"],
            "mandatory": True,
        }
        artifact = routing.analyze_verification_applicability(
            {"id": "C"}, {}, {"files": [], "tests": []},
            test_contract=authority["contract"],
            known_test_files=["tests/approved.test.js", "tests/other.test.js"],
            approved_verification_authority=authority,
        )
        route = artifact["verification_routes"][0]
        self.assertEqual(route["target"], "tests/approved.test.js")
        self.assertEqual(route["resolution_mode"], routing.EXACT_APPROVED_TARGET)

    def test_04_exact_target_survives_multiple_alternatives(self):
        authority = {
            "verification_id": "V-EXACT-MANY",
            "contract": ["tests/approved.test.js protects behavior"],
        }
        artifact = routing.analyze_verification_applicability(
            {"id": "C"}, {}, {},
            test_contract=authority["contract"],
            known_test_files=[
                "tests/approved.test.js", "tests/other.test.js",
                "tests/third.test.js",
            ],
            approved_verification_authority=authority,
        )
        self.assertEqual(artifact["verification_routes"][0]["target"], "tests/approved.test.js")
        self.assertNotEqual(artifact["verification_routes"][0]["resolution_mode"], routing.UNRESOLVED)

    def test_05_no_duplicate_generic_route_in_corrected_live_build(self):
        artifact = self.build()["artifact"]
        required = [item for item in artifact["verification_routes"] if item.get("required")]
        self.assertEqual(len(required), 4)
        self.assertEqual({item["target"] for item in required}, EXPECTED_TARGETS)
        self.assertFalse(any(item.get("target") is None for item in required))

    def test_06_every_mandatory_route_has_authority_provenance(self):
        artifact = self.build()["artifact"]
        for route in artifact["verification_route_bindings"]:
            if route.get("required") is True:
                self.assertTrue(route.get("authority_id"), route)
                self.assertTrue(route.get("authority_source"), route)
                self.assertTrue(route.get("authority_type"), route)

    def test_07_unauthorized_discovered_test_never_becomes_required(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v2542_unauthorized_test_") as temp:
            root = Path(temp)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "a.js").write_text("module.exports = 1;\n", encoding="utf-8")
            (root / "tests" / "approved.test.js").write_text("test('approved', () => true);\n", encoding="utf-8")
            (root / "tests" / "unauthorized.test.js").write_text("test('extra', () => true);\n", encoding="utf-8")
            authority = {
                "verification_id": "V-AUTHORIZED",
                "contract": ["tests/approved.test.js protects behavior"],
                "mandatory": True,
            }
            artifact = routing.analyze_verification_applicability(
                {"id": "C"}, {"allowed_mutation_paths": ["src/a.js"]}, {},
                test_contract=authority["contract"],
                mutation_paths=["src/a.js"],
                workspace=root,
                known_test_files=["tests/approved.test.js", "tests/unauthorized.test.js"],
                approved_verification_authority=authority,
            )
            routes = artifact["verification_routes"]
            self.assertEqual([item["target"] for item in routes], ["tests/approved.test.js"])

    def test_08_direct_oracle_is_exact_and_not_generic(self):
        artifact = self.build()["artifact"]
        direct = artifact["direct_oracle_routes"]
        self.assertEqual(len(direct), 1)
        self.assertEqual(direct[0]["oracle_id"], "ORACLE-PAUSE-INDICATOR")
        self.assertEqual(direct[0]["target"], "src/status_view.js")
        self.assertEqual(direct[0]["route_type"], routing.DIRECT_ORACLE)
        self.assertEqual(direct[0]["resolution_mode"], routing.EXACT_APPROVED_TARGET)
        self.assertEqual(direct[0]["execution_channel"], routing.DIRECT_ORACLE_EXECUTION)
        self.assertNotIn(direct[0], artifact["verification_routes"])

    def test_09_system_syntax_route_remains_exact(self):
        artifact = self.build()["artifact"]
        route = next(item for item in artifact["verification_routes"] if item["kind"] == routing.SYNTAX_STATIC_GATE)
        self.assertEqual(route["target"], "src/input.js")
        self.assertEqual(route["route_type"], routing.DETERMINISTIC_SYSTEM_SAFETY_CHECK)
        self.assertEqual(route["resolution_mode"], routing.DETERMINISTIC_SYSTEM_TARGET)
        self.assertEqual(route["authority_source"], "STAGE5A_DETERMINISTIC_ROUTE")

    def test_10_genuine_ambiguity_stays_fail_closed(self):
        authority = {"verification_id": "V-AMBIGUOUS", "contract": ["run the focused test"]}
        artifact = routing.analyze_verification_applicability(
            {"id": "C"}, {}, {}, test_contract=authority["contract"],
            known_test_files=["tests/a.test.js", "tests/b.test.js"],
            approved_verification_authority=authority,
        )
        route = artifact["verification_routes"][0]
        self.assertIsNone(route["target"])
        self.assertEqual(route["resolution_mode"], routing.UNRESOLVED)
        self.assertEqual(route["result"], routing.BLOCKED_REQUIRED_TARGET_MISSING)
        aggregation = routing.aggregate_verification_evidence(artifact, [])
        self.assertFalse(aggregation["passed"])
        self.assertIn(routing.REQUIRED_VERIFICATION_TARGET_UNRESOLVED, aggregation["failure_codes"])

    def test_11_target_null_requires_genuine_unresolved_authority(self):
        authority = {"verification_id": "V-EXACT-NULL", "contract": ["tests/a.test.js"], "target": "tests/a.test.js"}
        artifact = routing.analyze_verification_applicability(
            {"id": "C"}, {}, {}, test_contract=authority["contract"],
            known_test_files=["tests/a.test.js"],
            approved_verification_authority=authority,
        )
        bad = copy.deepcopy(artifact["verification_routes"][0])
        bad["target"] = None
        bad["selected_target"] = None
        bad["resolution_mode"] = routing.UNRESOLVED
        bad["canonical_hash"] = routing.canonical_route_hash(bad)
        checked = routing.validate_verification_route_bindings([bad], approved_authorities=[authority])
        self.assertFalse(checked["valid"])
        self.assertTrue(any("dropped an exact approved target" in item for item in checked["errors"]))

    def test_12_two_exact_contracts_emit_only_their_routes(self):
        authorities = [
            {"verification_id": "V-A", "contract": ["tests/a.test.js protects A"]},
            {"verification_id": "V-B", "contract": ["tests/b.test.js protects B"]},
        ]
        routes = []
        for authority in authorities:
            artifact = routing.analyze_verification_applicability(
                {"id": "C"}, {}, {}, test_contract=authority["contract"],
                known_test_files=["tests/a.test.js", "tests/b.test.js", "tests/extra.test.js"],
                approved_verification_authority=authority,
            )
            routes.extend(artifact["verification_routes"])
        merged = routing.deduplicate_verification_routes(routes)
        self.assertEqual({item["target"] for item in merged}, {"tests/a.test.js", "tests/b.test.js"})
        self.assertFalse(any(item.get("target") is None for item in merged))

    def test_13_route_identity_is_canonical(self):
        authority = {"verification_id": "V-HASH", "contract": ["tests/a.test.js"]}
        route = routing.analyze_verification_applicability(
            {"id": "C"}, {}, {}, test_contract=authority["contract"],
            known_test_files=["tests/a.test.js"], approved_verification_authority=authority,
        )["verification_routes"][0]
        self.assertEqual(route["canonical_hash"], routing.canonical_route_hash(route))
        self.assertTrue(route["route_id"].startswith("ROUTE-"))

    def test_14_target_change_changes_route_hash(self):
        route = self.build()["artifact"]["verification_routes"][0]
        changed = copy.deepcopy(route)
        changed["target"] = "tests/other.test.js"
        self.assertNotEqual(routing.canonical_route_hash(route), routing.canonical_route_hash(changed))

    def test_15_authority_change_changes_route_hash(self):
        route = self.build()["artifact"]["verification_routes"][0]
        changed = copy.deepcopy(route)
        changed["authority_id"] = "VERIFICATION-OTHER"
        self.assertNotEqual(routing.canonical_route_hash(route), routing.canonical_route_hash(changed))

    def test_16_required_status_change_changes_route_hash(self):
        route = self.build()["artifact"]["verification_routes"][0]
        changed = copy.deepcopy(route)
        changed["required"] = False
        self.assertNotEqual(routing.canonical_route_hash(route), routing.canonical_route_hash(changed))

    def test_17_command_change_changes_route_hash(self):
        route = self.build()["artifact"]["verification_routes"][0]
        changed = copy.deepcopy(route)
        changed["command"] = "node tests/other.test.js"
        self.assertNotEqual(routing.canonical_route_hash(route), routing.canonical_route_hash(changed))

    def test_18_resolution_mode_change_changes_route_hash(self):
        route = self.build()["artifact"]["verification_routes"][0]
        changed = copy.deepcopy(route)
        changed["resolution_mode"] = routing.SUPPORTED_TARGET_DISCOVERY
        self.assertNotEqual(routing.canonical_route_hash(route), routing.canonical_route_hash(changed))

    def test_19_route_validator_accepts_corrected_live_artifact(self):
        artifact = self.build()["artifact"]
        self.assertTrue(artifact["route_validation"]["valid"], artifact["route_validation"])
        self.assertEqual(artifact["route_validation"]["mandatory_routes"], 5)

    def test_20_route_validator_rejects_tampered_canonical_hash(self):
        artifact = self.build()["artifact"]
        tampered = copy.deepcopy(artifact["verification_route_bindings"])
        tampered[0]["target"] = "tests/tampered.test.js"
        checked = routing.validate_verification_route_bindings(
            tampered,
            approved_authorities=self.authorization["approved_verification_contracts"],
            deterministic_system_authorities=["SYSTEM-SYNTAX-SRC_INPUT_JS"],
        )
        self.assertFalse(checked["valid"])

    def test_21_live_replay_has_zero_phantom_required_routes(self):
        self.assertTrue(self.self_test["checks"]["no_required_phantom_route"])
        self.assertEqual(self.self_test["pre_fix"]["candidate_targets"], [
            "tests/input.test.js", "tests/pause_flow.integration.test.js",
            "tests/status_view.test.js",
        ])

    def test_22_live_replay_all_legitimate_routes_resolve(self):
        self.assertTrue(self.self_test["checks"]["corrected_required_targets_exact"])
        self.assertTrue(self.self_test["checks"]["all_mandatory_routes_have_authority"])

    def test_23_all_node_commands_pass_on_temp_subject(self):
        self.assertTrue(self.self_test["checks"]["legacy_verification_commands_pass"])
        self.assertEqual(
            {item["target"] for item in self.self_test["command_results"] if item.get("passed")},
            EXPECTED_TARGETS,
        )

    def test_24_direct_oracle_passes_on_temp_subject(self):
        self.assertTrue(self.self_test["checks"]["direct_oracle_passes"])
        self.assertEqual(self.self_test["direct_oracle"]["oracle_hash"], EXPECTED_ORACLE_HASH)

    def test_25_verified_child_readiness_is_ready(self):
        self.assertTrue(self.self_test["checks"]["verified_child_readiness_ready"])
        self.assertEqual(self.self_test["stage5b_readiness"]["readiness"], "READY")

    def test_26_stage5b_is_not_blocked_by_old_route(self):
        self.assertTrue(self.self_test["checks"]["stage5b_not_blocked_by_old_route"])
        self.assertEqual(self.self_test["stage5b_integration"]["status"], "PARENT_VERIFIED")

    def test_27_temporary_promotion_reaches_existing_boundary(self):
        self.assertTrue(self.self_test["checks"]["temporary_promotion_preconditions_ready"])
        self.assertEqual(self.self_test["temporary_promotion"]["status"], "PROMOTED")

    def test_28_plan_digest_coverage_and_oracle_hashes_unchanged(self):
        self.assertEqual(self.plan["plan_hash"], EXPECTED_PLAN_HASH)
        self.assertEqual(self.authorization["verification_digest"], EXPECTED_VERIFICATION_DIGEST)
        self.assertEqual(self.authorization["verification_obligation_coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertEqual(self.oracle["oracle_hash"], EXPECTED_ORACLE_HASH)

    def test_29_worker_packet_and_approval_receipt_unchanged(self):
        self.assertEqual(self.packet_audit["historical_provider_facing_packet_chars"], 4192)
        self.assertEqual(self.packet_audit["context_limit"], 4200)
        self.assertEqual(self.packet_audit["mandatory_drops"], 0)
        self.assertTrue(self.approval_validation["valid"])
        self.assertEqual(self.receipt["receipt_hash"], EXPECTED_RECEIPT_HASH)

    def test_30_no_provider_worker_live_experiment_or_historical_promotion(self):
        self.assertEqual(self.self_test["model_calls"], 0)
        self.assertEqual(self.self_test["worker_calls"], 0)
        self.assertEqual(self.self_test["provider_calls"], 0)
        self.assertEqual(self.self_test["historical_brain_writes"], 0)
        self.assertEqual(self.self_test["repository_subject_mutations"], 0)
        self.assertTrue(self.self_test["checks"]["historical_promotion_not_attempted"])
        self.assertEqual(self.final_summary["terminal_state"], "VERIFICATION_FAILED")


if __name__ == "__main__":
    unittest.main()
