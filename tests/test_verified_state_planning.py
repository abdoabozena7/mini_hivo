import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import verified_planning as planning
from hivo.integration_gate import canonical_hash
from hivo.project_understanding import DIRECT_OBSERVATION, REPOSITORY_EVIDENCE
from hivo.reentry import (
    CONFIRMED_CONSISTENT,
    CONFIRMED_DRIFT,
    CURRENT_DURABLE_AUTHORITY,
    CURRENT_VERIFIED,
    FRESH_TASK_BRAIN_TYPE,
    NOT_EVALUABLE,
    SCHEMA_VERSION,
    STALE_VERIFIED,
)


class VerifiedStatePlanningTests(unittest.TestCase):
    """Deterministic V24 Stage 6B tests; no model provider is used."""

    PROJECT = "planning-project"
    TASK = "planning-task"
    RELATION = {
        "subject": "PAUSE_STATE",
        "predicate": "owner",
        "object": "PauseController",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hivo_v24_planning_")
        self.root = Path(self.temp.name)
        self.old_workspace = mini.WORKSPACE
        mini.WORKSPACE = self.root
        mini.reset_run("recursive")

    def tearDown(self):
        mini.WORKSPACE = self.old_workspace
        mini.rollback_transaction()
        self.temp.cleanup()

    @classmethod
    def requirement(cls, *, authorized=False):
        value = {
            "requirement_id": "REQ-PAUSE-INDICATOR",
            "text": (
                "Add a user-facing pause indicator while preserving PauseController "
                "as the sole pause-state owner, Escape behavior, and movement behavior."
            ),
            "provenance": "USER_STATED",
            "authority": "USER/REQUIREMENT",
            "status": "CURRENT",
        }
        if authorized:
            value["authority_change_authorized"] = True
            value["authority_change"] = {
                "type": "AUTHORITY_CHANGE",
                "from": "PauseController",
                "to": "StatusView",
                "authorized": True,
            }
        return value

    @classmethod
    def repo(cls, *, owner="PauseController", relation=None, include=True):
        if not include:
            return []
        relation = relation or {
            "subject": "PAUSE_STATE",
            "predicate": "owner",
            "object": owner,
        }
        return [
            {
                "evidence_id": "REPO-OWNER",
                "category": "CURRENT_STATE_OWNER",
                "path": "src/pause_controller.js",
                "symbol": owner,
                "fact": f"owner(PAUSE_STATE) = {owner}",
                "source_kind": "JS",
                "evidence_type": DIRECT_OBSERVATION,
                "provenance": REPOSITORY_EVIDENCE,
                "line_start": 1,
                "line_end": 2,
                "file_sha256": "a" * 64,
                "support": "explicit structured repository ownership observation",
                "structured_relation": relation,
            },
            {
                "evidence_id": "REPO-INTERFACE",
                "category": "CURRENT_INTERFACE",
                "path": "src/pause_controller.js",
                "symbol": "PauseController.togglePause",
                "fact": "PauseController.togglePause is the current pause transition interface",
                "source_kind": "JS",
                "evidence_type": DIRECT_OBSERVATION,
                "provenance": REPOSITORY_EVIDENCE,
                "line_start": 4,
                "line_end": 8,
                "file_sha256": "b" * 64,
                "support": "explicit interface observation",
            },
            {
                "evidence_id": "REPO-INPUT",
                "category": "CURRENT_BEHAVIOR",
                "path": "src/input.js",
                "symbol": "handleInput",
                "fact": "Escape flows through PauseController.togglePause and movement remains intact",
                "source_kind": "JS",
                "evidence_type": DIRECT_OBSERVATION,
                "provenance": REPOSITORY_EVIDENCE,
                "line_start": 10,
                "line_end": 20,
                "file_sha256": "c" * 64,
                "support": "explicit behavior observation",
            },
            {
                "evidence_id": "REPO-TEST",
                "category": "CURRENT_TEST",
                "path": "tests/input.test.js",
                "symbol": "pause flow",
                "fact": "focused input tests cover Escape and movement behavior",
                "source_kind": "JS",
                "evidence_type": DIRECT_OBSERVATION,
                "provenance": REPOSITORY_EVIDENCE,
                "line_start": 1,
                "line_end": 20,
                "file_sha256": "d" * 64,
                "support": "explicit test observation",
            },
        ]

    @classmethod
    def fact(cls, *, classification=CURRENT_DURABLE_AUTHORITY):
        return {
            "record_id": "AUTH-PAUSE-OWNER",
            "fact_hash": "f" * 64,
            "fact": {
                "fact": "PauseController remains the sole pause-state owner",
                "category": "verified_state_ownership",
                "authority": "USER/REQUIREMENT",
                "structured_relation": cls.RELATION,
            },
            "classification": classification,
            "durability_class": "DURABLE_VERIFIED",
            "project_id": cls.PROJECT,
        }

    @classmethod
    def brain(
        cls,
        *,
        facts=True,
        repository=True,
        stale=False,
        conflicts=None,
        audits=None,
        authorized=False,
    ):
        current = [cls.fact()] if facts else []
        value = {
            "artifact_type": FRESH_TASK_BRAIN_TYPE,
            "schema_version": SCHEMA_VERSION,
            "project_id": cls.PROJECT,
            "task_id": cls.TASK,
            "task_goal": {
                "text": "Add a pause indicator while preserving current ownership and movement behavior.",
                "provenance": "USER_STATED",
            },
            "authority": [],
            "new_requirements": [cls.requirement(authorized=authorized)],
            "current_verified_facts": copy.deepcopy(current),
            "current_durable_authority": copy.deepcopy(current),
            "current_repository_evidence": cls.repo(include=repository),
            "stale_verified_facts": [
                {
                    "record_id": "STALE-PAUSE-INTEGRATION",
                    "fact_hash": "s" * 64,
                    "classification": STALE_VERIFIED,
                    "fact_summary": "old pause integration evidence",
                    "stale_reason": "subject dependency changed",
                    "changed_dependency_paths": ["src/input.js"],
                    "dependency_paths": ["src/input.js"],
                }
            ] if stale else [],
            "superseded_facts": [],
            "conflicts": copy.deepcopy(conflicts or []),
            "source_promotion_hashes": ["p" * 64],
            "authority_drift_audit": copy.deepcopy(audits or []),
            "reentry_hash": "r" * 64,
            "provenance": {
                "model_calls": 0,
                "old_task_brain_reused": False,
                "private_execution_material_loaded": False,
                "automatic_reverification": False,
            },
            "bounds": {"serialized_chars": 0},
            "model_calls": 0,
        }
        value["task_brain_hash"] = canonical_hash({
            key: item for key, item in value.items() if key != "task_brain_hash"
        })
        return value

    def context(self, **kwargs):
        return planning.compile_verified_planning_context(self.brain(**kwargs))

    @staticmethod
    def audit(authority_id="AUTH-PAUSE-OWNER", evidence_refs=None, classification=NOT_EVALUABLE):
        return {
            "authority_record_id": authority_id,
            "evidence_refs": list(evidence_refs or []),
            "classification": classification,
            "reason_code": "DIRECT_STRUCTURED_EVIDENCE" if classification != NOT_EVALUABLE else "SEMANTIC_EVIDENCE_UNAVAILABLE",
            "conflict_emitted": classification == CONFIRMED_DRIFT,
        }

    @classmethod
    def drift_conflict(cls, *, conflict_id="DRIFT-1", evidence_id="REPO-OWNER", owner="StatusView"):
        relation = {"subject": "PAUSE_STATE", "predicate": "owner", "object": owner}
        return {
            "conflict_id": conflict_id,
            "kind": "AUTHORITY_IMPLEMENTATION_DRIFT",
            "authority_record_id": "AUTH-PAUSE-OWNER",
            "authority_fact": "owner(PAUSE_STATE) = PauseController",
            "authority_fact_hash": "f" * 64,
            "authority_relation": cls.RELATION,
            "repository_evidence_ids": [evidence_id],
            "repository_relation": relation,
            "drift_classification": CONFIRMED_DRIFT,
        }

    def valid_plan(self, context, *, include_conflict=False, stale=False, unauthorized=False):
        plan = {
            "task_goal": (
                "Add a user-facing pause indicator while preserving PauseController "
                "as the sole pause-state owner, Escape behavior, and movement behavior. "
                "PauseController remains the sole pause-state owner."
            ),
            "coverage": [{
                "requirement_id": "REQ-PAUSE-INDICATOR",
                "status": "ASSIGNED",
                "node_ids": ["NODE-001"],
            }],
            "approved_change_nodes": [{
                "node_id": "NODE-001",
                "requirement_ids": ["REQ-PAUSE-INDICATOR"],
                "goal": (
                    "Add the indicator through the existing PauseController interface; "
                    "preserve Escape and movement behavior."
                ),
                "evidence_ids": ["REPO-OWNER", "REPO-INTERFACE", "REPO-INPUT"],
                "current_owner": "PauseController",
                "done_when": ["the requirement is covered"],
            }],
        }
        if include_conflict:
            plan["conflict_ids"] = [item["conflict_id"] for item in context["confirmed_conflicts"]]
        if stale:
            plan["approved_change_nodes"][0]["evidence_ids"].append("STALE-PAUSE-INTEGRATION")
        if unauthorized:
            plan["approved_change_nodes"][0].update({
                "target_owner": "StatusView",
                "goal": "Make StatusView the pause-state owner by moving ownership.",
            })
        return planning.attach_plan_binding(plan, context)

    def test_compiler_preserves_priority_and_excludes_stale_truth(self):
        value = self.context(stale=True)
        self.assertEqual(value["status"], "COMPILED")
        self.assertTrue(planning.validate_verified_planning_context(value)["valid"])
        self.assertEqual(value["planning_mode"], planning.VERIFIED_STATE_REENTRY)
        self.assertEqual(value["model_calls"], 0)
        self.assertTrue(value["new_requirements"])
        self.assertTrue(value["current_authority"])
        self.assertTrue(value["current_verified_facts"])
        self.assertTrue(value["stale_evidence_warnings"])
        self.assertEqual(value["dnt"], value["prohibitions"])
        self.assertEqual(value["source_priority"][:3], [
            "NEW_REQUIREMENT", "CURRENT_AUTHORITY", "CURRENT_VERIFIED",
        ])
        self.assertNotIn("STALE-PAUSE-INTEGRATION", json.dumps(value["current_verified_facts"]))
        self.assertLessEqual(
            len(json.dumps(value, ensure_ascii=False)), planning.MAX_CONTEXT_CHARS,
        )

    def test_readiness_is_zero_model_and_fails_closed_without_current_evidence(self):
        value = self.context(facts=False, repository=False)
        result = planning.assess_planning_context_readiness(value)
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], planning.PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE)
        self.assertEqual(result["model_calls"], 0)

    def test_readiness_detects_context_staleness_without_reverification(self):
        value = self.context()
        changed = self.repo()
        changed[0]["file_sha256"] = "z" * 64
        result = planning.assess_planning_context_readiness(
            value, current_repository_evidence=changed,
        )
        self.assertFalse(result["ready"])
        self.assertEqual(result["status"], planning.PLANNING_CONTEXT_STALE)
        self.assertEqual(result["model_calls"], 0)

    def test_valid_plan_is_bound_to_context_and_stale_evidence_is_rejected(self):
        value = self.context(stale=True)
        valid = planning.validate_verified_plan(self.valid_plan(value), value)
        self.assertTrue(valid["valid"], valid)
        rejected = planning.validate_verified_plan(
            self.valid_plan(value, stale=True), value,
        )
        self.assertFalse(rejected["valid"])
        self.assertIn(planning.PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE, rejected["errors"])

    def test_unauthorized_authority_migration_is_rejected(self):
        value = self.context()
        result = planning.validate_verified_plan(
            self.valid_plan(value, unauthorized=True), value,
        )
        self.assertFalse(result["valid"])
        self.assertIn(planning.UNAUTHORIZED_AUTHORITY_CHANGE, result["errors"])

    def test_explicit_authorized_authority_migration_is_an_approval_candidate(self):
        value = self.context(authorized=True)
        plan = self.valid_plan(value, unauthorized=True)
        plan["authority_change"] = {
            "type": "AUTHORITY_CHANGE",
            "from": "PauseController",
            "to": "StatusView",
            "authorized": True,
        }
        plan["authority_transition"] = "explicitly authorized transition candidate"
        result = planning.validate_verified_plan(plan, value)
        self.assertTrue(result["valid"], result)

    def test_only_confirmed_drift_enters_conflict_projection(self):
        drift = self.drift_conflict()
        value = self.context(
            conflicts=[drift],
            audits=[self.audit(evidence_refs=["REPO-OWNER"], classification=CONFIRMED_DRIFT)],
        )
        self.assertEqual(len(value["confirmed_conflicts"]), 1)
        self.assertEqual(value["confirmed_conflicts"][0]["drift_conflict_key"], planning._stable_conflict_key(drift))
        plan = self.valid_plan(value, include_conflict=True)
        self.assertTrue(planning.validate_verified_plan(plan, value)["valid"])

    def test_not_evaluable_is_audit_metadata_not_a_planning_conflict(self):
        value = self.context(
            conflicts=[self.drift_conflict()],
            audits=[self.audit(evidence_refs=["REPO-OWNER"], classification=NOT_EVALUABLE)],
        )
        self.assertEqual(value["confirmed_conflicts"], [])
        self.assertEqual(len(value["not_evaluable_audit"]), 1)
        self.assertNotIn("AUTHORITY_IMPLEMENTATION_DRIFT", json.dumps(value["confirmed_conflicts"]))

    def test_equivalent_conflicts_dedupe_but_distinct_contradictions_remain(self):
        first = self.drift_conflict(conflict_id="DRIFT-1")
        duplicate = self.drift_conflict(conflict_id="DRIFT-2")
        distinct = self.drift_conflict(conflict_id="DRIFT-3", evidence_id="REPO-OTHER", owner="OtherView")
        value = self.context(
            conflicts=[first, duplicate, distinct],
            audits=[
                self.audit(evidence_refs=["REPO-OWNER"], classification=CONFIRMED_DRIFT),
                self.audit(evidence_refs=["REPO-OTHER"], classification=CONFIRMED_DRIFT),
            ],
        )
        self.assertEqual(len(value["confirmed_conflicts"]), 2)
        self.assertEqual(value["duplicate_conflicts_suppressed"], 1)

    def test_explicit_source_binding_rejects_wrong_context(self):
        value = self.context()
        other = copy.deepcopy(value)
        other["task_id"] = "different-task"
        other["planning_context_hash"] = planning.planning_context_hash(other)
        result = planning.validate_verified_plan(self.valid_plan(value), other)
        self.assertFalse(result["valid"])

    def test_existing_stage3_boundary_stops_at_approval_without_execution(self):
        source = self.brain()
        result, _memory = mini.run_verified_state_aware_planning(
            fresh_task_brain=source,
            memory={},
            workspace=self.root,
            finish=False,
        )
        self.assertEqual(result["status"], "plan_approval_required", result)
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(result["approval_boundary"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(mini.RUN["planning_mode"], planning.VERIFIED_STATE_REENTRY)
        self.assertEqual(mini.RUN["planning_context_compiler_model_calls"], 0)
        self.assertEqual(mini.RUN["planning_readiness_model_calls"], 0)
        self.assertEqual(mini.RUN["worker_missions_executed"], 0)
        self.assertEqual(mini.RUN.get("verification_attempts", 0), 0)
        self.assertEqual(mini.RUN["promotion_model_calls"], 0)
        self.assertFalse(mini.RUN.get("execution_contracts_created"))

    def test_recursive_entrypoint_routes_fresh_state_without_stage2(self):
        with patch.object(mini, "prepare_stage2_context", side_effect=AssertionError("Stage 2 must not run")):
            result, _memory = mini.run_recursive_request(
                "ignored after Stage 6A",
                {},
                verified_state_reentry=self.brain(),
                current_repository_evidence=self.repo(),
                finish=False,
            )
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED, result)
        self.assertEqual(mini.RUN["planning_mode"], planning.VERIFIED_STATE_REENTRY)

    def test_explicit_dnt_path_blocks_a_mutation_target(self):
        value = self.context()
        dnt = {
            "text": "Do not modify src/pause_controller.js.",
            "provenance": "PROJECT_BRAIN",
            "path": "src/pause_controller.js",
            "category": "verified_prohibitions",
        }
        value["prohibitions"].append(dnt)
        value["dnt"] = copy.deepcopy(value["prohibitions"])
        value["planning_context_hash"] = planning.planning_context_hash(value)
        value["context_hash"] = value["planning_context_hash"]
        plan = self.valid_plan(value)
        plan["approved_change_nodes"][0]["candidate_targets"] = ["src/pause_controller.js"]
        result = planning.validate_verified_plan(plan, value)
        self.assertFalse(result["valid"])
        self.assertIn("PLAN_VIOLATES_DO_NOT_TOUCH", result["errors"])

    def test_plan_hash_binding_changes_when_context_changes(self):
        first = self.context()
        second = self.context(stale=True)
        self.assertNotEqual(first["planning_context_hash"], second["planning_context_hash"])
        first_plan = self.valid_plan(first)
        second_plan = self.valid_plan(second)
        self.assertNotEqual(
            canonical_hash(first_plan), canonical_hash(second_plan),
        )

    def test_architecture_self_test_covers_v24_boundary_controls(self):
        result = planning.run_verified_planning_self_test()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(result["checks"]["true_structured_drift_retained"])
        self.assertTrue(result["checks"]["unknown_evidence_not_conflict"])
        self.assertTrue(result["checks"]["stale_evidence_plan_blocked"])


if __name__ == "__main__":
    unittest.main()
