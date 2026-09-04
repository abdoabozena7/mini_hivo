"""Provider-free V25.6 execution-verification authority closure tests."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import integration_gate
from hivo import promotion
from hivo import verification_routing


ROOT = Path(__file__).resolve().parents[1]
LIVE2 = ROOT / "output" / "hivo-v25-5-stage6c-b-precommit-invariants-live-2"
ARTIFACTS = LIVE2 / "artifacts"
HISTORICAL_BRAIN = (
    ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1"
    / ".hivo" / "memory.sqlite3"
)

EXPECTED_PLAN_ID = "PLAN-5E9D01B255C2"
EXPECTED_PLAN_HASH = "5e9d01b255c23753eafa3fa76160b91b8b92486506580ffaf11f582b9522115a"
EXPECTED_VERIFICATION_DIGEST = "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51"
EXPECTED_COVERAGE_HASH = "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402"
EXPECTED_ORACLE_HASH = "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140"
EXPECTED_INVARIANT_HASH = "257c9d474539fdc74cfb7a6ca088bdf3431013f8e844af45c6d9e95bb7f73424"
HISTORICAL_SUBJECT = (
    "src/input.js", "src/pause_controller.js", "src/status_view.js",
    "tests/input.test.js", "tests/status_view.test.js",
    "tests/pause_flow.integration.test.js",
)


def _read_artifact(name: str, field: str | None = None):
    value = json.loads((ARTIFACTS / name).read_text(encoding="utf-8"))
    return value.get(field) if field else value


class V256ExecutionVerificationAuthorityClosureTests(unittest.TestCase):
    """The required authority set is closed before Stage 5B or Stage 5C."""

    @classmethod
    def setUpClass(cls):
        cls.artifact = _read_artifact("stage5a_route_bindings.json")
        cls.evidence = _read_artifact("verification_runner_evidence.json")
        cls.coverage = _read_artifact("verification_coverage.json")
        cls.invariant_audits = _read_artifact("precommit_invariant_audits.json")
        cls.artifact.update({
            "plan_id": EXPECTED_PLAN_ID,
            "plan_hash": EXPECTED_PLAN_HASH,
            "verification_digest": EXPECTED_VERIFICATION_DIGEST,
            "verification_obligation_coverage_hash": EXPECTED_COVERAGE_HASH,
        })
        cls.before_live2 = {
            name: (LIVE2 / name).read_bytes()
            for name in (
                "artifacts/stage5a_route_bindings.json",
                "artifacts/direct_behavior_oracle_result.json",
            )
        }
        cls.before_live2_subject = {
            name: (LIVE2 / name).read_bytes() for name in HISTORICAL_SUBJECT
        }
        cls.before_brain = HISTORICAL_BRAIN.read_bytes()

    def command_evidence(self):
        return copy.deepcopy(self.evidence[:4])

    def direct_evidence(self, *, passed: bool = False, oracle_hash: str | None = None):
        direct = copy.deepcopy(self.evidence[4])
        direct["result"]["passed"] = passed
        direct["result"]["verification_status"] = (
            verification_routing.PASS if passed else verification_routing.FAIL
        )
        if oracle_hash is not None:
            direct["result"]["oracle_hash"] = oracle_hash
        return direct

    def execution_obligation_evidence(self):
        accepted = next(
            item for item in reversed(self.invariant_audits)
            if isinstance(item, dict) and item.get("allowed") is True
        )
        audit_hash = accepted["canonical_hash"]
        return [{
            "authority_id": "INVARIANT-STATE-OWNER",
            "oracle_id": "INVARIANT-STATE-OWNER",
            "result": {
                "passed": True,
                "verification_status": verification_routing.PASS,
            },
            "receipt_identity": "PRECOMMIT-AUDIT-" + audit_hash.upper(),
            "receipt_hash": audit_hash,
            "receipt_channel": "PRECOMMIT_EXECUTION_INVARIANT_GATE",
            "execution_channel": "PRECOMMIT_EXECUTION_INVARIANT_GATE",
            "receipt_valid": True,
            "source": "V25.5_PreCommitExecutionInvariantGate",
            "authority_set_hash": EXPECTED_INVARIANT_HASH,
            "evidence_hash": audit_hash,
        }]

    def aggregate(self, *, direct_pass: bool = False, evidence=None):
        evidence = (
            list(evidence)
            if evidence is not None
            else self.command_evidence() + [self.direct_evidence(passed=direct_pass)]
        )
        return verification_routing.aggregate_verification_evidence(
            self.artifact,
            evidence,
            execution_obligation_evidence=self.execution_obligation_evidence(),
            verification_obligation_coverage=self.coverage,
        )

    def test_01_historical_live2_command_pass_direct_oracle_fail_closes(self):
        result = self.aggregate()
        closure = result["execution_verification_closure"]
        self.assertFalse(result["passed"])
        self.assertEqual(
            {item["authority_id"] for item in result["actual_passes"]},
            {
                "VERIFICATION-001", "VERIFICATION-002", "VERIFICATION-003",
                "SYSTEM-SYNTAX-SRC_INPUT_JS",
            },
        )
        self.assertEqual(
            [item["authority_id"] for item in result["actual_failures"]],
            ["VERIFICATION-004"],
        )
        self.assertEqual(closure["failed_authorities"], ["VERIFICATION-004"])
        self.assertFalse(closure["all_required_passed"])
        self.assertIn(
            verification_routing.REQUIRED_VERIFICATION_CLOSURE_FAILED,
            result["failure_codes"],
        )
        behavior_id = "OBL-REQ-PAUSE-INDICATOR-BEHAVIOR-CHANGE-01"
        self.assertIn(
            behavior_id,
            (result["execution_time_coverage"] or {}).get(
                "failed_obligation_ids", [],
            ),
        )

    def test_02_required_set_contains_direct_oracle_once(self):
        required = verification_routing.build_required_execution_verification_set(
            self.artifact,
        )
        self.assertEqual(len(required["required_authority_ids"]), 5)
        self.assertIn("VERIFICATION-004", required["required_authority_ids"])
        self.assertEqual(
            len(required["required_authority_ids"]),
            len(set(required["required_authority_ids"])),
        )
        self.assertEqual(
            required["approved_verification_authority_ids"],
            ["VERIFICATION-001", "VERIFICATION-002", "VERIFICATION-003", "VERIFICATION-004"],
        )
        self.assertEqual(
            required["system_authority_ids"], ["SYSTEM-SYNTAX-SRC_INPUT_JS"],
        )
        self.assertEqual(required["plan_id"], EXPECTED_PLAN_ID)
        self.assertEqual(required["plan_hash"], EXPECTED_PLAN_HASH)
        self.assertEqual(required["verification_digest"], EXPECTED_VERIFICATION_DIGEST)
        self.assertEqual(required["coverage_hash"], EXPECTED_COVERAGE_HASH)
        self.assertEqual(
            set(required["applicable_authority_ids"]),
            set(required["required_authority_ids"]),
        )
        self.assertEqual(
            required["required_authority_ids"],
            (self.aggregate()["execution_verification_closure"][
                "required_authority_ids"
            ]),
        )

    def test_03_missing_direct_receipt_is_not_run_and_fails(self):
        result = self.aggregate(evidence=self.command_evidence())
        closure = result["execution_verification_closure"]
        self.assertFalse(result["passed"])
        self.assertEqual(closure["not_run_authorities"], ["VERIFICATION-004"])
        self.assertEqual(closure["missing_authorities"], ["VERIFICATION-004"])
        self.assertIn(
            verification_routing.REQUIRED_VERIFICATION_NOT_RUN,
            result["failure_codes"],
        )

    def test_04_pending_direct_receipt_is_not_a_pass(self):
        direct = self.direct_evidence()
        direct["result"]["passed"] = None
        direct["result"]["verification_status"] = verification_routing.PENDING
        result = self.aggregate(
            evidence=self.command_evidence() + [direct],
        )
        closure = result["execution_verification_closure"]
        self.assertFalse(result["passed"])
        self.assertEqual(closure["not_run_authorities"], ["VERIFICATION-004"])
        self.assertFalse(closure["all_required_passed"])

    def test_05_tampered_direct_oracle_hash_is_invalid_receipt(self):
        result = self.aggregate(
            evidence=self.command_evidence() + [
                self.direct_evidence(oracle_hash="0" * 64),
            ],
        )
        closure = result["execution_verification_closure"]
        self.assertFalse(result["passed"])
        self.assertEqual(closure["invalid_authorities"], ["VERIFICATION-004"])
        self.assertIn(
            verification_routing.INVALID_RECEIPT,
            {
                item["status"] for item in closure["authority_receipts"]
                if item["authority_id"] == "VERIFICATION-004"
            },
        )

    def test_06_wrong_authority_receipt_cannot_satisfy_direct_oracle(self):
        direct = self.direct_evidence(passed=True)
        direct["verification_id"] = "VERIFICATION-001"
        result = self.aggregate(
            evidence=self.command_evidence() + [direct],
        )
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["execution_verification_closure"]["invalid_authorities"],
            ["VERIFICATION-004"],
        )

    def test_07_command_failure_cannot_be_overridden_by_oracle_pass(self):
        evidence = self.command_evidence()
        evidence[0]["result"] = "[exit_code=1] assertion failed"
        result = self.aggregate(
            evidence=evidence + [self.direct_evidence(passed=True)],
        )
        self.assertFalse(result["passed"])
        self.assertEqual(
            result["execution_verification_closure"]["failed_authorities"],
            ["VERIFICATION-001"],
        )

    def test_08_positive_all_required_authorities_pass_and_validate(self):
        result = self.aggregate(direct_pass=True)
        closure = result["execution_verification_closure"]
        self.assertTrue(result["passed"], result)
        self.assertTrue(closure["required_receipt_set_complete"])
        self.assertTrue(closure["all_required_passed"])
        self.assertTrue(
            result["execution_time_coverage"]["all_required_passed"],
        )
        self.assertTrue(
            verification_routing.validate_execution_verification_closure(
                closure, applicability=self.artifact,
            )["valid"],
        )

    def test_08b_plan_time_coverage_cannot_create_execution_pass(self):
        result = verification_routing.aggregate_verification_evidence(
            self.artifact,
            self.command_evidence() + [self.direct_evidence(passed=True)],
            execution_obligation_evidence=self.execution_obligation_evidence(),
        )
        closure = result["execution_verification_closure"]
        self.assertFalse(result["passed"])
        self.assertFalse(closure["all_required_passed"])
        self.assertFalse(
            closure["execution_time_obligation_closure"]["all_required_passed"]
        )
        self.assertIn(
            verification_routing.REQUIRED_VERIFICATION_CLOSURE_FAILED,
            result["failure_codes"],
        )

    def test_08c_execution_coverage_requires_every_bound_authority(self):
        coverage = copy.deepcopy(self.coverage)
        binding = next(
            item for item in coverage["obligation_coverage"]
            if isinstance(item, dict) and item.get("mandatory") is True
        )
        binding["satisfying_oracle_ids"] = list(
            binding.get("satisfying_oracle_ids", [])
        ) + ["UNOBSERVED-AUTHORITY"]
        result = verification_routing.aggregate_verification_evidence(
            self.artifact,
            self.command_evidence() + [self.direct_evidence(passed=True)],
            execution_obligation_evidence=self.execution_obligation_evidence(),
            verification_obligation_coverage=coverage,
        )
        execution_coverage = result["execution_time_coverage"]
        self.assertFalse(result["passed"])
        self.assertFalse(execution_coverage["all_required_passed"])
        self.assertIn(
            "UNOBSERVED-AUTHORITY",
            execution_coverage["obligations"][0]["missing_authority_ids"],
        )

    def test_09_duplicate_direct_route_does_not_double_count_authority(self):
        artifact = copy.deepcopy(self.artifact)
        artifact["verification_routes"].append(
            copy.deepcopy(artifact["direct_oracle_routes"][0]),
        )
        result = verification_routing.aggregate_verification_evidence(
            artifact,
            self.command_evidence() + [self.direct_evidence(passed=True)],
            execution_obligation_evidence=self.execution_obligation_evidence(),
            verification_obligation_coverage=self.coverage,
        )
        required = result["required_execution_verification_set"]
        self.assertTrue(result["passed"], result)
        self.assertEqual(
            required["required_authority_ids"].count("VERIFICATION-004"), 1,
        )
        self.assertEqual(
            [item["authority_id"] for item in result["actual_passes"]].count(
                "VERIFICATION-004",
            ),
            1,
        )

    def test_10_closure_hash_tamper_is_rejected(self):
        closure = self.aggregate(direct_pass=True)["execution_verification_closure"]
        tampered = copy.deepcopy(closure)
        tampered["all_required_passed"] = False
        checked = verification_routing.validate_execution_verification_closure(
            tampered, applicability=self.artifact,
        )
        self.assertFalse(checked["valid"])
        self.assertIn("execution verification closure hash is invalid", checked["errors"])

    def test_11_failed_closure_blocks_child_receipt_and_parent_executor(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v256_closure_") as temp:
            workspace = Path(temp)
            for relative in (
                "src/input.js", "src/pause_controller.js", "src/status_view.js",
                "tests/input.test.js", "tests/pause_flow.integration.test.js",
                "tests/status_view.test.js",
            ):
                source = LIVE2 / relative
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            aggregation = self.aggregate()
            contract = {
                "contract_hash": "PARENT-CONTRACT",
                "plan_hash": self.artifact.get("plan_hash") or "PLAN",
                "execution_contract_id": "PARENT",
            }
            task = {
                "id": "EXEC-001", "parent": "PARENT", "status": "done",
                "approved_plan_hash": contract["plan_hash"],
                "execution_contract": {
                    "execution_contract_id": "EXEC-001",
                    "contract_hash": "EXECUTION-CONTRACT",
                    "plan_hash": contract["plan_hash"],
                    "allowed_mutation_paths": ["src/status_view.js"],
                    "plan_node_ids": ["NODE-001"],
                    "owned_plan_node_ids": ["NODE-001"],
                },
                "plan_node_ids": ["NODE-001"],
                "owned_plan_node_ids": ["NODE-001"],
            }
            result = {
                "status": "done",
                "gate": {"verification_aggregation": aggregation},
                "verification_applicability": self.artifact,
                "verification_aggregation": aggregation,
                "verification_evidence": self.command_evidence() + [
                    self.direct_evidence()
                ],
                "builder": {
                    "status": "done",
                    "tool_evidence": self.command_evidence() + [
                        self.direct_evidence()
                    ],
                },
            }
            receipt = integration_gate.create_verified_child_receipt(
                task, result, parent_id="PARENT", parent_contract=contract,
                verification_applicability=self.artifact,
                verification_aggregation=aggregation,
                verification_evidence=result["verification_evidence"],
                workspace=workspace,
            )
            self.assertFalse(receipt["verified"])
            self.assertIn(
                "EXECUTION_VERIFICATION_CLOSURE_FAILED",
                receipt["verification_failure_reasons"],
            )
            parent = {
                "id": "PARENT",
                "integration_routes": [{
                    "kind": "INTEGRATION_TEST", "required": True,
                    "applicable": True,
                    "target": "tests/pause_flow.integration.test.js",
                    "result": verification_routing.PENDING,
                }],
            }
            plan = [{
                "child_id": "EXEC-001", "required": True,
                "execution_contract_id": "EXEC-001",
                "contract_hash": "EXECUTION-CONTRACT",
                "plan_node_ids": ["NODE-001"],
                "owned_plan_node_ids": ["NODE-001"],
            }]
            readiness = integration_gate.assess_integration_readiness(
                parent, [(task, result)], {"EXEC-001": receipt},
                parent_contract=contract, validated_child_plan=plan,
                workspace=workspace,
                parent_verification_applicability=self.artifact,
            )
            self.assertNotEqual(readiness["readiness"], integration_gate.READY)
            self.assertEqual(readiness["integration_executor_calls"], 0)
            integrated = integration_gate.aggregate_parent_integration(
                parent, contract, readiness, [], workspace=workspace,
            )
            self.assertFalse(integrated["parent_verified"])
            self.assertEqual(integrated["integration_executor_calls"], 0)
            self.assertEqual(integrated.get("promotion_calls", 0), 0)
            self.assertNotIn("parent_verification_receipt", integrated)
            self.assertNotIn("post_promotion_reentry", integrated)

    def test_12_raw_parent_verified_projection_cannot_override_failed_closure(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v256_parent_") as temp:
            workspace = Path(temp)
            for relative in (
                "src/input.js", "src/pause_controller.js", "src/status_view.js",
                "tests/input.test.js", "tests/pause_flow.integration.test.js",
                "tests/status_view.test.js",
            ):
                source = LIVE2 / relative
                target = workspace / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            aggregation = self.aggregate(direct_pass=True)
            contract = {
                "contract_hash": "PARENT-CONTRACT",
                "plan_hash": self.artifact.get("plan_hash") or "PLAN",
                "execution_contract_id": "PARENT",
            }
            task = {
                "id": "EXEC-001", "parent": "PARENT", "status": "done",
                "approved_plan_hash": contract["plan_hash"],
                "execution_contract": {
                    "execution_contract_id": "EXEC-001",
                    "contract_hash": "EXECUTION-CONTRACT",
                    "plan_hash": contract["plan_hash"],
                    "allowed_mutation_paths": ["src/status_view.js"],
                    "plan_node_ids": ["NODE-001"],
                    "owned_plan_node_ids": ["NODE-001"],
                },
                "plan_node_ids": ["NODE-001"],
                "owned_plan_node_ids": ["NODE-001"],
            }
            evidence = self.command_evidence() + [self.direct_evidence(passed=True)]
            child_result = {
                "status": "done",
                "gate": {"verification_aggregation": aggregation},
                "verification_applicability": self.artifact,
                "builder": {"status": "done", "tool_evidence": evidence},
            }
            receipt = integration_gate.create_verified_child_receipt(
                task, child_result, parent_id="PARENT",
                parent_contract=contract,
                verification_applicability=self.artifact,
                verification_aggregation=aggregation,
                verification_evidence=evidence,
                workspace=workspace,
            )
            parent = {
                "id": "PARENT",
                "integration_routes": [{
                    "kind": "INTEGRATION_TEST", "required": True,
                    "applicable": True,
                    "target": "tests/pause_flow.integration.test.js",
                    "result": verification_routing.PENDING,
                }],
            }
            plan = [{
                "child_id": "EXEC-001", "required": True,
                "execution_contract_id": "EXEC-001",
                "contract_hash": "EXECUTION-CONTRACT",
                "plan_node_ids": ["NODE-001"],
                "owned_plan_node_ids": ["NODE-001"],
            }]
            readiness = integration_gate.assess_integration_readiness(
                parent, [(task, child_result)], {"EXEC-001": receipt},
                parent_contract=contract, validated_child_plan=plan,
                workspace=workspace,
                parent_verification_applicability=self.artifact,
            )
            self.assertEqual(readiness["readiness"], integration_gate.READY)
            integrated = integration_gate.aggregate_parent_integration(
                parent, contract, readiness,
                [{
                    "tool": "run_command",
                    "target": "tests/pause_flow.integration.test.js",
                    "result": "[exit_code=0] integration passed",
                }],
                workspace=workspace,
            )
            self.assertEqual(integrated["status"], integration_gate.PARENT_VERIFIED)
            forged_parent_result = copy.deepcopy(integrated)
            forged_parent_result["verification_aggregation"] = self.aggregate()
            checked = promotion.validate_parent_verification_receipt(
                integrated["parent_verification_receipt"],
                parent=parent,
                parent_result=forged_parent_result,
                parent_contract=contract,
                child_receipts={"EXEC-001": receipt},
                workspace=workspace,
            )
            self.assertFalse(checked["valid"])
            self.assertTrue(any(
                "closure" in str(error).casefold()
                for error in checked["errors"]
            ))

    def test_13_historical_live2_and_brain_are_unchanged(self):
        self.assertEqual(
            self.before_live2["artifacts/stage5a_route_bindings.json"],
            (LIVE2 / "artifacts/stage5a_route_bindings.json").read_bytes(),
        )
        self.assertEqual(
            self.before_live2["artifacts/direct_behavior_oracle_result.json"],
            (LIVE2 / "artifacts/direct_behavior_oracle_result.json").read_bytes(),
        )
        for name, before in self.before_live2_subject.items():
            self.assertEqual(before, (LIVE2 / name).read_bytes(), name)
        self.assertEqual(self.before_brain, HISTORICAL_BRAIN.read_bytes())

    def test_14_no_provider_calls_are_possible_in_aggregation(self):
        result = self.aggregate(direct_pass=True)
        self.assertEqual(result.get("model_calls"), 0)
        self.assertEqual(
            (result.get("execution_verification_closure") or {}).get("model_calls"),
            0,
        )

    def test_15_binding_tamper_is_rejected_even_with_recomputed_closure_hash(self):
        closure = self.aggregate(direct_pass=True)["execution_verification_closure"]
        for field in ("plan_hash", "verification_digest", "coverage_hash"):
            tampered = copy.deepcopy(closure)
            tampered[field] = "0" * 64
            body = {
                key: value for key, value in tampered.items()
                if key not in {"closure_hash", "canonical_hash"}
            }
            tampered_hash = verification_routing.deterministic_hash(body)
            tampered["closure_hash"] = tampered_hash
            tampered["canonical_hash"] = tampered_hash
            checked = verification_routing.validate_execution_verification_closure(
                tampered, applicability=self.artifact,
            )
            self.assertFalse(checked["valid"], field)
            self.assertTrue(any(field in error for error in checked["errors"]), checked)

    def test_16_optional_browser_route_does_not_block_complete_closure(self):
        result = self.aggregate(direct_pass=True)
        self.assertTrue(result["passed"])
        self.assertEqual(len(result["skipped_not_applicable"]), 1)
        self.assertFalse(result["skipped_not_applicable"][0]["required"])

    def test_17_positive_complete_replay_reaches_temporary_promotion_and_reentry(self):
        replay = mini.run_stage6c_b_v25_4_2_self_test(
            artifact_root=ROOT / "output" / "hivo-v25-4-1-stage6c-b-verification-complete-live-1",
            brain_database_path=HISTORICAL_BRAIN,
        )
        self.assertTrue(replay["passed"], replay)
        self.assertTrue(
            replay["verification_aggregation"]["execution_verification_closure"][
                "all_required_passed"
            ]
        )
        self.assertEqual(replay["stage5b_readiness"]["readiness"], "READY")
        self.assertEqual(replay["stage5b_integration"]["status"], integration_gate.PARENT_VERIFIED)
        self.assertIn(replay["temporary_promotion"]["status"], {"PROMOTED", "ALREADY_PROMOTED"})
        self.assertTrue(replay["temporary_reentry"]["passed"])


if __name__ == "__main__":
    unittest.main()
