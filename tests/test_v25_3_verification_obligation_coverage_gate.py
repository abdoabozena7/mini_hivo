"""Provider-free V25.3 verification-obligation coverage tests."""

from __future__ import annotations

import copy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import approval_authority as authority
from hivo import approval_bound_execution as stage5
from hivo import execution_contracts as stage4
from hivo import execution_invariants as invariants
from hivo import impact_planning as planning
from hivo import verification_obligation_coverage as coverage


ROOT = Path(__file__).resolve().parents[1]
PLANNING_ROOT = ROOT / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
FIXTURE_ROOT = ROOT / "output" / "hivo-v25-stage6c-b-approved-execution-live-1"
HISTORICAL_DB = ROOT / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
EXPECTED_BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"


def _load(path: Path, fallback=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return copy.deepcopy(fallback)


class VerificationObligationCoverageGateTests(unittest.TestCase):
    """Every execution/provider seam in this class is deterministic."""

    @classmethod
    def setUpClass(cls):
        cls.plan = _load(PLANNING_ROOT / "final_plan.json", {})
        cls.context = _load(PLANNING_ROOT / "verified_planning_context.json", {})
        brain = authority.read_only_project_brain_identity(
            HISTORICAL_DB, cls.context.get("project_id"),
        )
        cls.state = {
            "task_id": cls.context.get("task_id"),
            "project_id": cls.context.get("project_id"),
            "planning_mode": cls.context.get("planning_mode"),
            "verified_planning_context": cls.context,
            "planning_context_hash": cls.context.get("planning_context_hash"),
            "brain_hash": brain["logical_hash"],
            "subject_aggregate_hash": (cls.context.get("source_repository_fingerprint") or {}).get("hash"),
            "upstream_bindings": cls.plan.get("upstream_bindings", {}),
            "requirements": cls.plan.get("requirements", []),
            "coverage": cls.plan.get("coverage", []),
            "planning_context_freshness": _load(PLANNING_ROOT / "planning_context_freshness.json", {}),
            "plan_validation": _load(PLANNING_ROOT / "plan_validation.json", {}),
            "stage4_contractability_audit": _load(PLANNING_ROOT / "stage4_contractability_audit.json", {}),
            "challenger_reconciliation": _load(
                PLANNING_ROOT / "challenger_reconciliation.json",
                cls.plan.get("challenger_reconciliation", {}),
            ),
            "terminal_state": authority.PLAN_APPROVAL_REQUIRED,
            "source_repository_fingerprint": cls.context.get("source_repository_fingerprint", {}),
        }
        cls.evidence = _load(PLANNING_ROOT / "current_surface_evidence.json", {}).get(
            "repository_evidence", [],
        )
        cls.registry = _load(PLANNING_ROOT / "current_surface_evidence.json", {}).get(
            "registry", {},
        )
        cls.request = authority.create_plan_approval_request(cls.plan, cls.state)
        cls.receipt = authority.record_plan_approval(
            cls.request,
            authority.make_test_explicit_user_approval_event(cls.request),
        )
        cls.revalidation = authority.pre_execution_approval_revalidation(
            cls.receipt, cls.plan, cls.state, request=cls.request,
        )
        cls.base_authorization = authority.create_approved_execution_authorization(
            cls.receipt, cls.revalidation, request=cls.request,
        )
        cls.base_compiled = authority.compile_approval_bound_execution_contracts(
            cls.plan, cls.receipt, cls.revalidation, cls.base_authorization,
            request=cls.request, requirements=cls.plan.get("requirements", []),
            repository_evidence=cls.evidence,
            canonical_surface_registry=cls.registry,
        )
        cls.base_contract = next(
            item for item in cls.base_compiled["contracts"]
            if item.get("responsibility_type") == stage4.MUTATION
        )
        cls.invariant_set = invariants.build_execution_invariant_set(
            execution_contract=cls.base_contract, approved_plan=cls.plan,
            source_root=FIXTURE_ROOT, repository_evidence=cls.evidence,
        )
        cls.invariant_check = invariants.validate_execution_invariant_set(
            cls.invariant_set, execution_contract=cls.base_contract,
            source_root=FIXTURE_ROOT, require_current_subject=True,
        )
        post_subject = stage5.enumerate_execution_subject(FIXTURE_ROOT)
        cls.applicability = stage5.build_stage5a_verification_input(
            task={"id": cls.state.get("task_id", "ROOT")},
            contract=cls.base_contract,
            authorization=cls.base_authorization,
            workspace=FIXTURE_ROOT,
            post_subject=post_subject,
            execution_result={"execution_contract_hash": cls.base_contract.get("contract_hash")},
        )["artifact"]
        cls.current_coverage = coverage.build_verification_obligation_coverage(
            approved_plan=cls.plan,
            approved_verification_contracts=cls.plan.get("canonical_verification_contracts", []),
            execution_contract=cls.base_contract,
            execution_invariant_set=cls.invariant_set,
            repository_evidence=cls.evidence,
            source_root=FIXTURE_ROOT,
            verification_applicability=cls.applicability,
            task_id=cls.state.get("task_id"),
        )

    @classmethod
    def _obligation_id(cls, kind):
        return next(
            item["obligation_id"]
            for requirement in cls.plan["requirement_obligation_ledger"]["requirements"]
            for item in requirement["obligations"]
            if item.get("obligation_type") == kind
        )

    @classmethod
    def _synthetic_plan_and_contracts(cls, *, behavior_path="tests/pause_indicator.test.js"):
        plan = copy.deepcopy(cls.plan)
        contracts = plan["canonical_verification_contracts"]
        behavior_id = cls._obligation_id(coverage.BEHAVIOR_CHANGE)
        record = next(item for item in contracts if item.get("verification_id") == "VERIFICATION-003")
        record["contract"] = [
            f"{behavior_path} directly asserts the additional user-facing pause indicator"
        ]
        record["oracle_type"] = coverage.FOCUSED_TEST
        record["approved"] = True
        record["obligation_bindings"] = [{
            "obligation_id": behavior_id,
            "coverage_relationship": coverage.DIRECT,
            "coverage_strength": coverage.STRONG,
            "mandatory": True,
            "applicable": True,
            "semantic_binding": {
                "observable": "additional user-facing pause indicator",
                "assertion": "the approved test asserts the indicator is visible when paused",
                "expected_behavior": "pause indicator is visible in the user-facing status surface",
                "called_symbol": "renderStatus",
            },
        }]
        return planning.finalize_plan_identity(plan), contracts, {
            behavior_path: (
                "const assert = require('assert/strict');\n"
                "assert.equal(renderPauseIndicatorWhenPaused(), 'PAUSED');\n"
                "assert.equal(document.querySelector('[data-pause-indicator]').textContent, 'PAUSED');\n"
            ),
        }

    @classmethod
    def _build_coverage(cls, *, plan=None, contracts=None, source_files=None,
                        execution_contract=None, explicit_bindings=None,
                        explicit_oracles=None, verification_applicability=None,
                        **extra):
        selected_plan = copy.deepcopy(plan if plan is not None else cls.plan)
        selected_contracts = (
            copy.deepcopy(contracts)
            if contracts is not None
            else copy.deepcopy(selected_plan.get("canonical_verification_contracts", []))
        )
        return coverage.build_verification_obligation_coverage(
            approved_plan=selected_plan,
            approved_verification_contracts=selected_contracts,
            execution_contract=execution_contract or cls.base_contract,
            execution_invariant_set=cls.invariant_set,
            repository_evidence=cls.evidence,
            source_root=FIXTURE_ROOT,
            source_files=source_files,
            verification_applicability=(
                verification_applicability
                if verification_applicability is not None else cls.applicability
            ),
            coverage_bindings=explicit_bindings,
            verification_oracles=explicit_oracles,
            task_id=cls.state.get("task_id"),
            **extra,
        )

    @classmethod
    def _direct_record(cls, oracle_id, path, *, mandatory=True,
                       target_status=None, semantic=True, source=None):
        behavior_id = cls._obligation_id(coverage.BEHAVIOR_CHANGE)
        record = {
            "verification_id": oracle_id,
            "oracle_type": coverage.FOCUSED_TEST,
            "contract": [f"{path} approved verification oracle"],
            "approved": True,
            "mandatory": mandatory,
            "obligation_bindings": [{
                "obligation_id": behavior_id,
                "coverage_relationship": coverage.DIRECT,
                "coverage_strength": coverage.STRONG,
                "mandatory": mandatory,
                "applicable": True,
                "semantic_binding": (
                    {
                        "observable": "additional user-facing pause indicator",
                        "assertion": "the approved test asserts the pause indicator is visible when paused",
                        "expected_behavior": "visible pause indicator",
                    }
                    if semantic else {"source_presence": "indicator literal exists"}
                ),
            }],
        }
        if target_status is not None:
            record["target_status"] = target_status
        return record, {
            path: source or "const assert = require('assert/strict');\nassert.equal(true, true);\n",
        }

    @classmethod
    def _complete_authority(cls):
        plan, contracts, source_files = cls._synthetic_plan_and_contracts()
        request = authority.create_plan_approval_request(plan, cls.state)
        receipt = authority.record_plan_approval(
            request, authority.make_test_explicit_user_approval_event(request),
        )
        revalidation = authority.pre_execution_approval_revalidation(
            receipt, plan, cls.state, request=request,
        )
        base_authorization = authority.create_approved_execution_authorization(
            receipt, revalidation, request=request,
        )
        base_compiled = authority.compile_approval_bound_execution_contracts(
            plan, receipt, revalidation, base_authorization, request=request,
            requirements=plan.get("requirements", []), repository_evidence=cls.evidence,
            canonical_surface_registry=cls.registry,
        )
        contract = next(
            item for item in base_compiled["contracts"]
            if item.get("responsibility_type") == stage4.MUTATION
        )
        invariant_set = invariants.build_execution_invariant_set(
            execution_contract=contract, approved_plan=plan,
            source_root=FIXTURE_ROOT, repository_evidence=cls.evidence,
        )
        applicability = stage5.build_stage5a_verification_input(
            task={"id": cls.state.get("task_id", "ROOT")}, contract=contract,
            authorization=base_authorization, workspace=FIXTURE_ROOT,
            post_subject=stage5.enumerate_execution_subject(FIXTURE_ROOT),
            execution_result={},
        )["artifact"]
        complete = coverage.build_verification_obligation_coverage(
            approved_plan=plan,
            approved_verification_contracts=contracts,
            execution_contract=contract,
            execution_invariant_set=invariant_set,
            repository_evidence=cls.evidence,
            source_root=FIXTURE_ROOT,
            source_files=source_files,
            verification_applicability=applicability,
            task_id=cls.state.get("task_id"),
        )
        authorization_value = authority.create_approved_execution_authorization(
            receipt, revalidation, request=request,
            stage4_graph=base_compiled.get("graph"),
            execution_invariant_set=invariant_set,
            verification_obligation_coverage=complete,
        )
        compiled = authority.compile_approval_bound_execution_contracts(
            plan, receipt, revalidation, authorization_value, request=request,
            requirements=plan.get("requirements", []), repository_evidence=cls.evidence,
            canonical_surface_registry=cls.registry,
            execution_invariant_set=invariant_set,
            execution_invariant_source_root=FIXTURE_ROOT,
            verification_obligation_coverage=complete,
        )
        return {
            "plan": plan, "contracts": contracts, "source_files": source_files,
            "request": request, "receipt": receipt, "revalidation": revalidation,
            "authorization": authorization_value, "invariants": invariant_set,
            "coverage": complete, "compiled": compiled,
            "contract": next(
                item for item in compiled["contracts"]
                if item.get("responsibility_type") == stage4.MUTATION
            ),
        }

    def test_atomic_obligations_load_from_actual_plan_and_plan_coverage_is_distinct(self):
        obligation_ids = {
            item["obligation_id"] for item in self.current_coverage["atomic_obligations"]
        }
        plan_ids = set(self.plan["coverage"][0]["obligation_ids"])
        self.assertEqual(obligation_ids, plan_ids)
        self.assertEqual(len(obligation_ids), 4)
        self.assertEqual(self.current_coverage["requirement_coverage"], self.plan["coverage"])
        self.assertNotEqual(
            self.current_coverage["requirement_coverage"],
            self.current_coverage["obligation_coverage"],
        )
        self.assertEqual(self.plan["coverage"][0]["status"], "COVERED_BY_CHANGE")

    def test_behavior_change_requires_direct_mandatory_oracle(self):
        behavior = next(
            item for item in self.current_coverage["obligation_coverage"]
            if item["obligation_type"] == coverage.BEHAVIOR_CHANGE
        )
        self.assertEqual(behavior["required_relationship"], coverage.DIRECT)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)
        self.assertFalse(behavior["satisfying_oracle_ids"])

    def test_syntax_only_oracle_cannot_cover_behavior_change(self):
        artifact = self._build_coverage(contracts=[])
        behavior_id = self._obligation_id(coverage.BEHAVIOR_CHANGE)
        self.assertIn(behavior_id, artifact["uncovered_obligation_ids"])
        self.assertFalse(any(
            item["obligation_type"] == coverage.BEHAVIOR_CHANGE
            and item["coverage_relationship"] == coverage.DIRECT
            for item in artifact["coverage_bindings"]
        ))
        self.assertTrue(any(item["oracle_type"] == coverage.SYNTAX_CHECK for item in artifact["oracle_records"]))

    def test_syntax_oracle_with_behavior_binding_is_still_not_direct(self):
        record, source_files = self._direct_record(
            "SYNTAX-BEHAVIOR", "tests/syntax_indicator.test.js",
        )
        record["oracle_type"] = coverage.SYNTAX_CHECK
        record["command"] = "node --check tests/syntax_indicator.test.js"
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)
        self.assertEqual(artifact["new_behavior_oracle_count"], 0)

    def test_generic_regression_test_cannot_cover_behavior_change(self):
        record, source_files = self._direct_record("GENERIC-TEST", "tests/unrelated.test.js")
        record.pop("obligation_bindings")
        artifact = self._build_coverage(
            contracts=[record], source_files=source_files,
        )
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)

    def test_source_presence_check_cannot_cover_behavior_change(self):
        record, source_files = self._direct_record(
            "SOURCE-PRESENCE", "tests/source_presence.test.js", semantic=False,
        )
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)
        self.assertEqual(artifact["new_behavior_oracle_count"], 0)

    def test_worker_prose_cannot_cover_behavior_change(self):
        artifact = self._build_coverage(
            worker_result={"summary": "the pause indicator was implemented"},
            raw_worker_output="indicator added successfully",
        )
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)
        self.assertEqual(artifact["invented_oracles"], [])

    def test_each_legacy_fixture_test_is_supporting_only_for_indicator(self):
        behavior_id = self._obligation_id(coverage.BEHAVIOR_CHANGE)
        by_oracle = {item["oracle_id"]: item for item in self.current_coverage["oracle_records"]}
        for oracle_id in ("VERIFICATION-001", "VERIFICATION-002", "VERIFICATION-003"):
            self.assertIn(oracle_id, by_oracle)
            self.assertFalse(any(
                item["obligation_id"] == behavior_id
                and item["oracle_id"] == oracle_id
                and item["coverage_relationship"] == coverage.DIRECT
                for item in self.current_coverage["coverage_bindings"]
            ))
        supporting = [
            item for item in self.current_coverage["coverage_bindings"]
            if item["obligation_id"] == behavior_id
        ]
        self.assertTrue(supporting)
        self.assertTrue(all(item["coverage_relationship"] == coverage.SUPPORTING for item in supporting))

    def test_exact_fixture_reports_only_indicator_uncovered(self):
        self.assertEqual(
            self.current_coverage["uncovered_obligation_ids"],
            [self._obligation_id(coverage.BEHAVIOR_CHANGE)],
        )
        self.assertEqual(self.current_coverage["status"], coverage.VERIFICATION_OBLIGATION_UNCOVERED)
        self.assertFalse(self.current_coverage["verification_ready"])

    def test_ownership_has_deterministic_preservation_coverage(self):
        owner_id = self._obligation_id(coverage.PRESERVATION_OBLIGATION)
        owner = next(
            item for item in self.current_coverage["obligation_coverage"]
            if item["obligation_id"] == owner_id
        )
        self.assertEqual(owner["coverage_state"], coverage.COVERED)
        self.assertIn("INVARIANT-STATE-OWNER", owner["satisfying_oracle_ids"])

    def test_escape_preservation_is_structurally_mapped(self):
        escape_id = next(
            item["obligation_id"] for item in self.current_coverage["atomic_obligations"]
            if any("ESCAPE_PAUSE_FLOW" in relation for relation in item["structured_relations"])
        )
        matches = [
            item for item in self.current_coverage["coverage_bindings"]
            if item["obligation_id"] == escape_id
        ]
        self.assertTrue(matches)
        self.assertTrue(any(
            item["coverage_relationship"] == coverage.PRESERVATION
            and item["oracle_id"] in {"VERIFICATION-001", "VERIFICATION-002"}
            and item["semantic_binding"]["action"] == "Escape"
            for item in matches
        ))

    def test_movement_preservation_is_structurally_mapped(self):
        movement_id = next(
            item["obligation_id"] for item in self.current_coverage["atomic_obligations"]
            if any("MOVEMENT_INPUT" in relation for relation in item["structured_relations"])
        )
        matches = [
            item for item in self.current_coverage["coverage_bindings"]
            if item["obligation_id"] == movement_id
        ]
        self.assertTrue(any(
            item["coverage_relationship"] == coverage.PRESERVATION
            and item["oracle_id"] in {"VERIFICATION-001", "VERIFICATION-002"}
            and item["semantic_binding"]["action"] == "movement"
            for item in matches
        ))

    def test_test_name_alone_does_not_create_coverage(self):
        record, source_files = self._direct_record("INDICATOR-NAME-ONLY", "tests/pause_indicator.test.js")
        record.pop("obligation_bindings")
        source_files["tests/pause_indicator.test.js"] = "const name = 'pause indicator';\n"
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        self.assertEqual(
            next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)["coverage_state"],
            coverage.UNCOVERED,
        )

    def test_unrelated_test_does_not_gain_obligation_coverage(self):
        record, source_files = self._direct_record("UNRELATED", "tests/math.test.js")
        record.pop("obligation_bindings")
        source_files["tests/math.test.js"] = "const assert = require('assert'); assert.equal(1, 1);\n"
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        self.assertFalse(any(
            item["oracle_id"] == "UNRELATED" and item["obligation_type"] == coverage.BEHAVIOR_CHANGE
            for item in artifact["coverage_bindings"]
        ))

    def test_positive_synthetic_direct_behavior_oracle_makes_all_obligations_ready(self):
        artifact = self._complete_authority()
        self.assertEqual(artifact["coverage"]["status"], coverage.EXECUTION_VERIFICATION_READY)
        self.assertTrue(artifact["coverage"]["verification_ready"])
        self.assertEqual(artifact["coverage"]["uncovered_obligation_ids"], [])
        self.assertEqual(artifact["coverage"]["new_behavior_oracle_count"], 1)

    def test_one_missing_mandatory_behavior_obligation_keeps_readiness_not_ready(self):
        self.assertEqual(self.current_coverage["status"], coverage.VERIFICATION_OBLIGATION_UNCOVERED)
        self.assertFalse(self.current_coverage["verification_ready"])

    def test_optional_oracle_cannot_satisfy_mandatory_behavior(self):
        record, source_files = self._direct_record(
            "OPTIONAL-BEHAVIOR", "tests/optional_indicator.test.js", mandatory=False,
        )
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(behavior["coverage_state"], coverage.UNCOVERED)
        self.assertEqual(artifact["new_behavior_oracle_count"], 0)

    def test_not_applicable_mandatory_oracle_does_not_count(self):
        record, source_files = self._direct_record(
            "NOT-APPLICABLE-BEHAVIOR", "tests/not_applicable.test.js",
            target_status=coverage.NOT_APPLICABLE,
        )
        artifact = self._build_coverage(contracts=[record], source_files=source_files)
        oracle = next(item for item in artifact["oracle_records"] if item["oracle_id"] == "NOT-APPLICABLE-BEHAVIOR")
        self.assertEqual(oracle["target_status"], coverage.NOT_APPLICABLE)
        self.assertFalse(oracle["applicable"])
        self.assertIn(self._obligation_id(coverage.BEHAVIOR_CHANGE), artifact["uncovered_obligation_ids"])

    def test_unresolved_mandatory_oracle_target_does_not_count(self):
        record, _source_files = self._direct_record(
            "UNRESOLVED-BEHAVIOR", "tests/missing_indicator.test.js",
        )
        artifact = self._build_coverage(contracts=[record])
        oracle = next(item for item in artifact["oracle_records"] if item["oracle_id"] == "UNRESOLVED-BEHAVIOR")
        self.assertEqual(oracle["target_status"], coverage.UNRESOLVED)
        self.assertIn(self._obligation_id(coverage.BEHAVIOR_CHANGE), artifact["uncovered_obligation_ids"])

    def test_stale_verification_evidence_is_not_resolved(self):
        artifact = self._build_coverage(
            source_files={"src/status_view.js": "// stale subject\n"},
        )
        syntax = next(item for item in artifact["oracle_records"] if item["oracle_type"] == coverage.SYNTAX_CHECK)
        self.assertEqual(syntax["target_status"], coverage.STALE)

    def test_stale_resolved_verification_target_invalidates_prebuilt_coverage(self):
        authority_value = self._complete_authority()
        source_files = copy.deepcopy(authority_value["source_files"])
        target = "tests/pause_indicator.test.js"
        source_files[target] += "// changed after coverage binding\n"
        checked = coverage.validate_verification_obligation_coverage(
            authority_value["coverage"],
            execution_contract=authority_value["contract"],
            execution_invariant_set=authority_value["invariants"],
            source_root=FIXTURE_ROOT,
            source_files=source_files,
        )
        self.assertFalse(checked["valid"])
        self.assertTrue(any("stale" in item for item in checked["errors"]))

    def test_duplicate_evidence_fans_into_one_oracle_identity(self):
        duplicate = copy.deepcopy(self.plan["canonical_verification_contracts"][0])
        duplicate["evidence_ids"] = ["DUPLICATE-EVIDENCE"]
        artifact = self._build_coverage(
            contracts=self.plan["canonical_verification_contracts"] + [duplicate],
        )
        matching = [item for item in artifact["oracle_records"] if item["oracle_id"] == "VERIFICATION-001"]
        self.assertEqual(len(matching), 1)
        self.assertIn("DUPLICATE-EVIDENCE", matching[0]["evidence_refs"])
        self.assertEqual(len({item["obligation_id"] for item in artifact["atomic_obligations"]}), 4)

    def test_one_oracle_can_cover_multiple_obligations_only_with_separate_bindings(self):
        combined_path = "tests/combined_pause_regression.test.js"
        combined_source = """assert.deepEqual(handleInput({ key: 'Escape' }, controller, position), { type: 'pause', paused: true });
assert.deepEqual(handleInput({ key: 'ArrowRight' }, controller, position), { type: 'move', direction: 'ArrowRight', position: { x: 1, y: 0 } });
"""
        record, _ = self._direct_record("COMBINED-INTEGRATION", combined_path, source=combined_source)
        record["oracle_type"] = coverage.INTEGRATION_TEST
        artifact = self._build_coverage(
            contracts=[record], source_files={combined_path: combined_source},
        )
        covered = [
            item for item in artifact["coverage_bindings"]
            if item["oracle_id"] == "COMBINED-INTEGRATION"
        ]
        obligations = {item["obligation_id"] for item in covered}
        self.assertIn(self._obligation_id(coverage.BEHAVIOR_CHANGE), obligations)
        self.assertGreaterEqual(len(obligations), 3)
        self.assertEqual(len({item["obligation_id"] for item in artifact["atomic_obligations"]}), 4)

    def test_multiple_direct_oracles_fan_into_one_behavior_obligation(self):
        first, first_files = self._direct_record("BEHAVIOR-A", "tests/indicator_a.test.js")
        second, second_files = self._direct_record("BEHAVIOR-B", "tests/indicator_b.test.js")
        artifact = self._build_coverage(
            contracts=[first, second],
            source_files={**first_files, **second_files},
        )
        behavior = next(item for item in artifact["obligation_coverage"] if item["obligation_type"] == coverage.BEHAVIOR_CHANGE)
        self.assertEqual(set(behavior["satisfying_oracle_ids"]), {"BEHAVIOR-A", "BEHAVIOR-B"})
        self.assertEqual(artifact["new_behavior_oracle_count"], 2)

    def test_coverage_is_immutable_and_hash_recomputes(self):
        self.assertEqual(
            self.current_coverage["coverage_hash"],
            coverage.canonical_coverage_hash(self.current_coverage),
        )
        with self.assertRaises(TypeError):
            self.current_coverage["status"] = "tampered"

    def test_each_coverage_identity_change_changes_canonical_hash(self):
        changes = []
        changed = copy.deepcopy(self.current_coverage)
        changed["atomic_obligations"][0]["meaning"] += " changed"
        changes.append(changed)
        changed = copy.deepcopy(self.current_coverage)
        changed["coverage_bindings"][0]["semantic_binding"]["changed"] = True
        changes.append(changed)
        changed = copy.deepcopy(self.current_coverage)
        changed["oracle_records"][0]["mandatory"] = not changed["oracle_records"][0]["mandatory"]
        changes.append(changed)
        changed = copy.deepcopy(self.current_coverage)
        changed["oracle_records"][0]["applicable"] = not changed["oracle_records"][0]["applicable"]
        changes.append(changed)
        changed = copy.deepcopy(self.current_coverage)
        changed["oracle_records"][0]["target"] = "tests/other.test.js"
        changes.append(changed)
        changed = copy.deepcopy(self.current_coverage)
        changed["coverage_bindings"][0]["coverage_relationship"] = coverage.SUPPORTING
        changes.append(changed)
        original_hash = coverage.canonical_coverage_hash(self.current_coverage)
        self.assertTrue(all(
            coverage.canonical_coverage_hash(item) != original_hash for item in changes
        ))

    def test_stage4_contract_binds_coverage_identity_without_matrix(self):
        artifact = self._complete_authority()
        contract = artifact["contract"]
        self.assertEqual(
            contract["verification_obligation_coverage_hash"],
            artifact["coverage"]["coverage_hash"],
        )
        self.assertEqual(contract["verification_obligation_coverage_status"], coverage.EXECUTION_VERIFICATION_READY)
        self.assertNotIn("coverage_bindings", contract)
        self.assertNotIn("atomic_obligations", contract)

    def test_changing_coverage_invalidates_contract_identity(self):
        artifact = self._complete_authority()
        contract = artifact["contract"]
        altered = copy.deepcopy(artifact["coverage"])
        altered["oracle_records"][0]["target"] = "tests/changed.test.js"
        self.assertNotEqual(
            contract["contract_hash"],
            stage4.deterministic_hash({
                **stage4._without(contract, "contract_hash"),
                "verification_obligation_coverage_hash": coverage.canonical_coverage_hash(altered),
            }),
        )

    def test_authorization_binds_coverage_hash_and_changed_coverage_does_not_match(self):
        artifact = self._complete_authority()
        authorization_value = artifact["authorization"]
        self.assertEqual(
            authorization_value["verification_obligation_coverage_hash"],
            artifact["coverage"]["coverage_hash"],
        )
        altered = copy.deepcopy(artifact["coverage"])
        altered["oracle_records"][0]["target"] = "tests/changed.test.js"
        altered["coverage_hash"] = coverage.canonical_coverage_hash(altered)
        gate = authority.worker_authorization_gate(
            authorization_value, artifact["receipt"], artifact["revalidation"],
            request=artifact["request"], execution_invariant_set=artifact["invariants"],
            verification_obligation_coverage=altered,
        )
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], coverage.VERIFICATION_OBLIGATION_COVERAGE_MISMATCH)

    def test_uncovered_behavior_blocks_worker_before_provider(self):
        gated_authorization = authority.create_approved_execution_authorization(
            self.receipt, self.revalidation, request=self.request,
            stage4_graph=self.base_compiled.get("graph"),
            execution_invariant_set=self.invariant_set,
            verification_obligation_coverage=self.current_coverage,
        )
        gate = authority.worker_authorization_gate(
            gated_authorization, self.receipt, self.revalidation,
            request=self.request, execution_invariant_set=self.invariant_set,
            verification_obligation_coverage=self.current_coverage,
        )
        self.assertFalse(gate["allowed"])
        self.assertEqual(gate["code"], coverage.VERIFICATION_OBLIGATION_UNCOVERED)

    def test_approval_receipt_remains_valid_while_coverage_blocks_execution(self):
        receipt_before = copy.deepcopy(self.receipt)
        self.assertTrue(authority.validate_plan_approval_receipt(self.receipt, self.request)["valid"])
        gated_authorization = authority.create_approved_execution_authorization(
            self.receipt, self.revalidation, request=self.request,
            execution_invariant_set=self.invariant_set,
            verification_obligation_coverage=self.current_coverage,
        )
        self.assertEqual(gated_authorization["status"], authority.EXECUTION_AUTHORIZATION_READY)
        self.assertEqual(
            authority.worker_authorization_gate(
                gated_authorization, self.receipt, self.revalidation,
                request=self.request, execution_invariant_set=self.invariant_set,
                verification_obligation_coverage=self.current_coverage,
            )["code"],
            coverage.VERIFICATION_OBLIGATION_UNCOVERED,
        )
        self.assertEqual(dict(self.receipt), receipt_before)

    def test_no_oracle_or_test_is_invented_by_current_plan_replay(self):
        oracle_ids = {item["oracle_id"] for item in self.current_coverage["oracle_records"]}
        self.assertNotIn("PAUSE-INDICATOR-AUTO-ORACLE", oracle_ids)
        self.assertNotIn(
            "tests/pause_indicator.test.js",
            {path for item in self.current_coverage["oracle_records"] for path in item.get("paths", [])},
        )
        self.assertEqual(self.current_coverage["invented_oracles"], [])
        self.assertEqual(self.current_coverage["model_calls"], 0)

    def test_exact_frozen_replay_blocks_with_zero_worker_calls(self):
        result = mini.run_stage6c_b_v25_3_self_test()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["path_a"]["terminal_state"], coverage.VERIFICATION_OBLIGATION_UNCOVERED)
        self.assertEqual(result["path_a"]["worker_calls"], 0)
        self.assertEqual(result["worker_calls"], 0)
        self.assertEqual(result["model_calls"], 0)

    def test_v25_2_invariant_projection_remains_bounded_and_matrix_free(self):
        old_projection = invariants.build_worker_execution_invariant_projection(
            self.invariant_set, self.base_contract, max_chars=4200,
        )
        old_rendered = invariants.render_worker_execution_invariant_projection(
            old_projection, max_chars=4200,
        )
        complete = self._complete_authority()
        new_projection = invariants.build_worker_execution_invariant_projection(
            complete["invariants"], complete["contract"], max_chars=4200,
        )
        new_rendered = invariants.render_worker_execution_invariant_projection(
            new_projection, max_chars=4200,
        )
        self.assertEqual(old_rendered, new_rendered)
        self.assertLessEqual(len(new_rendered), 4200)
        self.assertNotIn("coverage_bindings", new_rendered)
        self.assertNotIn("atomic_obligations", new_rendered)

    def test_promotion_rejects_incomplete_coverage_without_brain_records(self):
        saved = {
            "WORKSPACE": mini.WORKSPACE,
            "RUN": mini.RUN,
            "TASKS": mini.TASKS,
            "RUN_ID": mini.RUN_ID,
        }
        try:
            mini.reset_run("v25.3-test")
            mini.RUN["stage5c_enabled"] = True
            authorization_value = authority.create_approved_execution_authorization(
                self.receipt, self.revalidation, request=self.request,
                execution_invariant_set=self.invariant_set,
                verification_obligation_coverage=self.current_coverage,
            )
            mini.RUN["execution_authorization"] = copy.deepcopy(authorization_value)
            result = mini._stage5c_promote_parent(
                {"id": "PARENT", "goal": "unverified indicator"},
                self.base_contract,
                {
                    "status": "done",
                    "integration_result": mini.PARENT_VERIFIED,
                    "verification_obligation_coverage": copy.deepcopy(self.current_coverage),
                },
                {},
            )
            self.assertEqual(result["promotion_status"], coverage.VERIFICATION_OBLIGATION_UNCOVERED)
            self.assertIsNone((result.get("promotion") or {}).get("candidate"))
            self.assertEqual((result.get("promotion") or {}).get("project_brain_records"), [])
        finally:
            mini.WORKSPACE = saved["WORKSPACE"]
            mini.RUN = saved["RUN"]
            mini.TASKS = saved["TASKS"]
            mini.RUN_ID = saved["RUN_ID"]


if __name__ == "__main__":
    unittest.main()
