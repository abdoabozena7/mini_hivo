import copy
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hivo import impact_planning as impact
from hivo import project_understanding as understanding
from hivo.integration_gate import fingerprint_dependency_paths
from hivo.memory import MemoryStore
from hivo.reentry import (
    REENTRY_READY,
    build_fresh_task_brain,
    run_verified_state_reentry,
    validate_fresh_task_brain,
    validate_reentry_context,
)
from hivo.verified_planning import (
    assess_planning_context_readiness,
    build_planning_contract,
    build_stage3_task_brain,
    compile_verified_planning_context,
    validate_verified_planning_context,
)


class _ReadOnlyProjectBrain:
    """Read the exact SQLite Brain without constructing a writable store."""

    def __init__(self, database):
        self.db_path = Path(database).resolve()
        self.workspace = self.db_path.parent.parent

    def project_brain_snapshot(self, project_id="default", *, include_inactive=True):
        connection = sqlite3.connect(
            f"file:{self.db_path.as_posix()}?mode=ro", uri=True,
        )
        connection.row_factory = sqlite3.Row
        try:
            helper = MemoryStore.__new__(MemoryStore)
            return {
                "project_id": helper._project_id(project_id),
                "records": helper._records_from_connection(
                    connection, project_id, include_inactive=include_inactive,
                ),
            }
        finally:
            connection.close()


class CurrentSurfacePreservationBindingTests(unittest.TestCase):
    """V24.4.2 production-path and generic binding regressions."""

    ROOT = Path(
        r"D:\projects\Ai\mini_hivo\output\hivo-v22-stage5c-fresh-receipts-live-1"
    )
    PROJECT_ID = "hivo-v22-stage5c-fresh-receipts-live-1"
    DATABASE = ROOT / ".hivo" / "memory.sqlite3"
    REQUIREMENT_ID = "REQ-PAUSE-INDICATOR"
    REQUIREMENT = (
        "Extend the existing pause flow with an additional user-facing pause "
        "indicator while preserving PauseController as the existing pause-state "
        "owner and preserving current Escape and movement behavior."
    )
    SUBJECT = (
        "src/input.js",
        "src/pause_controller.js",
        "src/status_view.js",
        "tests/input.test.js",
        "tests/status_view.test.js",
        "tests/pause_flow.integration.test.js",
    )
    SUBJECT_HASHES = {
        "src/input.js": "3534ebd784e405a9fcc32cba0fec67a56f16731bc8036a0b7fc7ff07d8d77b9b",
        "src/pause_controller.js": "94bf565534236a4dce68e2b0b865a3d52415a221f4e77046558a7facd5e473aa",
        "src/status_view.js": "0f9684c6e0ed12e3cbf6c0e6d94a35c8c84f9bbb1017ff495897baae71321852",
        "tests/input.test.js": "aef72c63ee7e569c3e59a7d8280875e8ad77e696e23d6a1d95e80252254b6d46",
        "tests/status_view.test.js": "928d633bb6c62279fac80eaa1396b5cf28863efeb6545811216adc19f3555015",
        "tests/pause_flow.integration.test.js": "260ec9920c77b7ddf5e61d53878439bdd5aa1fa845778e636043524deff93099",
    }
    BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"
    SUBJECT_AGGREGATE_HASH = "c00fc37444dc64f0f6aecbcd57a5972ddfb9fed495f2ce2ba39be7db1150bbac"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.store = _ReadOnlyProjectBrain(cls.DATABASE)
        cls.db_bytes_before = cls.DATABASE.read_bytes()
        cls.brain_before = cls.store.project_brain_snapshot(cls.PROJECT_ID)
        cls.subject_before = {
            relative: hashlib.sha256((cls.ROOT / relative).read_bytes()).hexdigest()
            for relative in cls.SUBJECT
        }
        cls.requirements = [{
            "requirement_id": cls.REQUIREMENT_ID,
            "text": cls.REQUIREMENT,
            "status": "active",
            "provenance": impact.USER_STATED,
        }]

        cls.reentry = run_verified_state_reentry(
            cls.store,
            cls.PROJECT_ID,
            "V24.4.2-CURRENT-SURFACE-TEST",
            cls.REQUIREMENT,
            workspace=cls.ROOT,
            new_requirements=cls.requirements,
        )
        if cls.reentry.get("status") != REENTRY_READY:
            raise AssertionError(cls.reentry)
        cls.reentry_context = cls.reentry["reentry_context"]
        cls.fresh = cls.reentry["task_brain"]
        cls.context = compile_verified_planning_context(
            cls.fresh,
            cls.reentry_context,
            expected_project_id=cls.PROJECT_ID,
        )
        if cls.context.get("status") != "COMPILED" or not cls.context.get("valid"):
            raise AssertionError(cls.context)
        cls.readiness = assess_planning_context_readiness(cls.context)
        cls.stage3_brain = build_stage3_task_brain(cls.context)
        cls.planning_contract = build_planning_contract(cls.context)
        cls.registry = impact.build_canonical_surface_registry(
            cls.stage3_brain, cls.context["current_repository_evidence"],
        )
        cls.registry_check = impact.validate_canonical_surface_registry(
            cls.registry, cls.context["current_repository_evidence"],
        )
        cls.selection = impact.select_task_relevant_surfaces(
            cls.stage3_brain,
            cls.context["new_requirements"],
            cls.context["current_repository_evidence"],
            registry=cls.registry,
        )
        cls.seeds = impact.build_impact_seeds(
            cls.stage3_brain,
            cls.context["new_requirements"],
            cls.context["current_repository_evidence"],
            registry=cls.registry,
            selected_surface_ids=cls.selection["selected_surface_ids"],
        )
        cls.core = impact.build_canonical_mandatory_planning_core({
            "project_id": cls.context["project_id"],
            "task_id": cls.context["task_id"],
            "task_goal": cls.context["task_goal"],
            "requirements": cls.context["new_requirements"],
            "surfaces": cls.registry["surfaces"],
            "impact_seeds": cls.seeds,
            "preservation_constraints": cls.stage3_brain.get(
                "preservation_constraints", [],
            ),
            "dnt": cls.stage3_brain.get("dnt", []),
            "prohibitions": cls.stage3_brain.get("prohibitions", []),
            "current_repository_evidence": cls.context["current_repository_evidence"],
        })
        cls.ledger = impact.build_requirement_obligation_ledger(cls.requirements)
        cls.frame = impact.build_impact_decision_frame(
            cls.stage3_brain,
            cls.context["new_requirements"],
            cls.context["current_repository_evidence"],
            surface_registry=cls.registry,
            impact_seeds=cls.seeds,
            mandatory_core=cls.core,
            obligation_ledger=cls.ledger,
            verified_planning_context=cls.context,
        )
        cls.frame_check = impact.validate_impact_decision_frame(cls.frame)
        cls.coverage_check = impact.validate_impact_decision_frame_coverage(
            cls.frame,
        )

    @classmethod
    def _slot(cls, role):
        return next(
            item for item in cls.frame["decision_slots"]
            if item.get("surface_role") == role
        )

    @classmethod
    def _obligation(cls, obligation_type, *, relation=None):
        values = [
            item for item in cls.frame["impact_decision_frame_coverage"]["obligations"]
            if item.get("obligation_type") == obligation_type
        ]
        if relation is not None:
            values = [
                item for item in values
                if relation in set(item.get("structured_relations", []))
            ]
        return values[0]

    @classmethod
    def _choices(cls, *, decision_by_role=None):
        decision_by_role = decision_by_role or {}
        result = []
        for slot in cls.frame["decision_slots"]:
            role = slot["surface_role"]
            decision = decision_by_role.get(role, "INSPECT_ONLY")
            if decision == "INTERFACE_REUSE":
                target = slot["required_interfaces"][0]
            else:
                target = slot["surface_id"]
            result.append({
                "slot_id": slot["slot_id"],
                "decision": decision,
                "chosen_target": target,
                "reason_code": "V2442_TEST",
                "bounded_rationale": "Use the bounded production-path choice.",
            })
        return {"decisions": result}

    @classmethod
    def _legacy_behavior_fixture(cls):
        requirement = [{
            "requirement_id": "REQ-LEGACY-EXPORT",
            "text": "Add export behavior.",
            "status": "active",
            "provenance": impact.USER_STATED,
        }]
        evidence = [{
            "evidence_id": "REPO-LEGACY-001",
            "category": "CURRENT_OWNER",
            "path": "src/export.js",
            "symbol": "ExportController",
            "fact": "ExportController owns export behavior.",
            "file_sha256": "a" * 64,
            "provenance": "REPOSITORY_EVIDENCE",
            "evidence_type": "DIRECT_OBSERVATION",
            "support": "class ExportController { export() { return true; } }",
            "line_start": 1,
            "line_end": 1,
            "source_kind": "SOURCE",
        }]
        brain = {
            "project_id": "legacy-export-project",
            "task_id": "legacy-export-task",
            "task_goal": {"text": requirement[0]["text"]},
            "current_owners": [{
                "text": evidence[0]["fact"],
                "path": evidence[0]["path"],
                "symbol": evidence[0]["symbol"],
                "category": evidence[0]["category"],
                "evidence_ids": [evidence[0]["evidence_id"]],
            }],
        }
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(
            brain, requirement, evidence, registry=registry,
        )
        core = impact.build_canonical_mandatory_planning_core({
            "project_id": brain["project_id"],
            "task_id": brain["task_id"],
            "task_goal": brain["task_goal"],
            "requirements": requirement,
            "surfaces": registry["surfaces"],
            "impact_seeds": seeds,
        })
        frame = impact.build_impact_decision_frame(
            brain,
            requirement,
            evidence,
            surface_registry=registry,
            impact_seeds=seeds,
            mandatory_core=core,
        )
        return requirement, evidence, brain, registry, seeds, frame

    def test_01_exact_brain_hash_and_record_classes(self):
        self.assertEqual(
            MemoryStore._canonical_hash(self.brain_before), self.BRAIN_HASH,
        )
        self.assertEqual(len(self.brain_before["records"]), 12)
        self.assertEqual(
            {item["durability_class"] for item in self.brain_before["records"]},
            {"DURABLE_VERIFIED", "STATE_BOUND_VERIFIED"},
        )
        self.assertEqual(
            sum(item["durability_class"] == "DURABLE_VERIFIED" for item in self.brain_before["records"]),
            11,
        )
        self.assertEqual(
            sum(item["durability_class"] == "STATE_BOUND_VERIFIED" for item in self.brain_before["records"]),
            1,
        )

    def test_02_exact_subject_hashes_and_aggregate(self):
        self.assertEqual(self.subject_before, self.SUBJECT_HASHES)
        fingerprint = fingerprint_dependency_paths(self.ROOT, self.SUBJECT)
        self.assertEqual(fingerprint["hash"], self.SUBJECT_AGGREGATE_HASH)

    def test_03_reentry_is_ready_read_only_and_zero_model(self):
        self.assertEqual(self.reentry["status"], REENTRY_READY)
        self.assertTrue(self.reentry["ready"])
        self.assertEqual(self.reentry["model_calls"], 0)
        self.assertTrue(self.reentry["read_only"])
        self.assertTrue(self.reentry["project_brain_read_only"])
        self.assertFalse(self.reentry["project_brain_mutated"])
        self.assertFalse(self.reentry["execution_started"])
        self.assertEqual(self.reentry["metrics"]["reentry_model_calls"], 0)
        self.assertEqual(self.reentry["metrics"]["freshness_model_calls"], 0)
        self.assertEqual(self.reentry["metrics"]["relevance_model_calls"], 0)

    def test_04_fresh_task_brain_is_bounded_and_structured(self):
        self.assertEqual(self.fresh["artifact_type"], "FreshTaskBrain")
        self.assertLessEqual(self.fresh["bounds"]["serialized_chars"], 10_000)
        self.assertTrue(self.fresh["current_repository_evidence"])
        self.assertTrue(any(
            "CURRENT_RENDER_SURFACE" in item.get("structured_relations", [])
            for item in self.fresh["current_repository_evidence"]
        ))
        self.assertEqual(self.fresh["model_calls"], 0)
        self.assertTrue(validate_fresh_task_brain(self.fresh)["valid"])

    def test_05_reentry_context_preserves_direct_and_one_hop_edges(self):
        self.assertTrue(validate_reentry_context(self.reentry_context)["valid"])
        links = [
            link
            for record in self.reentry_context["current_repository_evidence"]
            for link in record.get("source_links", [])
        ]
        self.assertTrue(links)
        self.assertTrue(all(int(link.get("hop", 0) or 0) in {0, 1} for link in links))
        self.assertTrue(any(
            int(link.get("hop", 0) or 0) == 0
            and str(link.get("from", "")).startswith("tests/")
            for link in links
        ))
        self.assertTrue(any(
            int(link.get("hop", 0) or 0) == 1
            and str(link.get("from", "")).startswith("src/")
            for link in links
        ))

    def test_06_verified_planning_context_is_compiled_and_bounded(self):
        self.assertEqual(self.context["status"], "COMPILED")
        self.assertTrue(self.context["valid"])
        self.assertEqual(self.context["planning_mode"], "VERIFIED_STATE_REENTRY")
        self.assertEqual(self.context["model_calls"], 0)
        self.assertLessEqual(
            len(str(self.context)),
            int(self.context["bounds"]["max_serialized_chars"]),
        )
        self.assertTrue(validate_verified_planning_context(self.context)["valid"])

    def test_07_planning_readiness_is_ready_without_provider(self):
        self.assertEqual(self.readiness["status"], "PLANNING_CONTEXT_READY")
        self.assertTrue(self.readiness["ready"])
        self.assertEqual(self.readiness["model_calls"], 0)
        self.assertGreater(self.readiness["current_repository_evidence_count"], 0)

    def test_08_ledger_contains_four_atomic_obligations(self):
        atoms = self.ledger["requirements"][0]["obligations"]
        self.assertEqual(len(atoms), 4)
        self.assertEqual(
            [item["obligation_type"] for item in atoms],
            ["BEHAVIOR_CHANGE", "PRESERVATION", "PRESERVATION", "PRESERVATION"],
        )
        self.assertEqual(
            {item["obligation_id"] for item in atoms},
            {
                f"OBL-{self.REQUIREMENT_ID}-BEHAVIOR-CHANGE-01",
                f"OBL-{self.REQUIREMENT_ID}-PRESERVATION-02",
                f"OBL-{self.REQUIREMENT_ID}-PRESERVATION-03",
                f"OBL-{self.REQUIREMENT_ID}-PRESERVATION-04",
            },
        )

    def test_09_ledger_types_are_mapped_to_named_relations(self):
        atoms = self.ledger["requirements"][0]["obligations"]
        by_type = {
            item["obligation_type"]: item
            for item in atoms
            if item["obligation_type"] == "BEHAVIOR_CHANGE"
        }
        behavior = by_type["BEHAVIOR_CHANGE"]
        self.assertIn("USER_FACING_PAUSE_INDICATOR", behavior["structured_relations"])
        self.assertIn(
            "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER",
            next(item for item in atoms if "PauseController" in item["meaning"])["structured_relations"],
        )
        self.assertIn(
            "PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW",
            next(item for item in atoms if "Escape" in item["meaning"])["structured_relations"],
        )
        self.assertIn(
            "PRESERVE_BEHAVIOR:MOVEMENT_INPUT",
            next(item for item in atoms if "movement" in item["meaning"])["structured_relations"],
        )

    def test_10_stage3_adapter_and_contract_are_derived_from_vpc(self):
        self.assertEqual(
            self.stage3_brain["verified_planning_context_hash"],
            self.context["planning_context_hash"],
        )
        self.assertEqual(
            self.planning_contract["verified_planning_context_hash"],
            self.context["planning_context_hash"],
        )
        self.assertEqual(self.planning_contract["planning_mode"], "VERIFIED_STATE_REENTRY")
        self.assertEqual(self.planning_contract["source_requirement_ledger"]["requirements"][0]["requirement_id"], self.REQUIREMENT_ID)

    def test_11_registry_validation_and_structured_surface_count(self):
        self.assertTrue(self.registry_check["valid"], self.registry_check)
        self.assertGreaterEqual(self.registry_check["surface_count"], 4)
        self.assertTrue(all(
            item.get("structured_relations")
            for item in self.registry["surfaces"]
        ))

    def test_12_render_surface_is_selected_from_structural_evidence(self):
        render_evidence = next(
            item for item in self.context["current_repository_evidence"]
            if "USER_FACING_PAUSE_INDICATOR" in item.get("structured_relations", [])
        )
        render_surface = next(
            item for item in self.registry["surfaces"]
            if "CURRENT_RENDER_SURFACE" in item.get("structured_relations", [])
        )
        self.assertEqual(render_surface["path"], render_evidence["path"])
        self.assertEqual(render_surface["symbol"], render_evidence["symbol"])
        self.assertEqual(render_surface["role"], "RENDER_SURFACE")
        self.assertIn(render_surface["surface_id"], self.selection["selected_surface_ids"])
        self.assertIn(
            "structured_requirement_relation",
            self.selection["scores"][render_surface["surface_id"]]["reasons"],
        )

    def test_13_requirement_to_render_surface_evidence_is_structured_and_bounded(self):
        render_evidence = next(
            item for item in self.context["current_repository_evidence"]
            if "CURRENT_RENDER_SURFACE" in item.get("structured_relations", [])
        )
        self.assertEqual(render_evidence["category"], "CURRENT_OWNER")
        self.assertEqual(render_evidence["source_kind"], "SOURCE")
        self.assertIn("CURRENT_IMPLEMENTATION_SURFACE", render_evidence["structured_relations"])
        self.assertIn("USER_FACING_PAUSE_INDICATOR", render_evidence["structured_relations"])
        self.assertTrue(render_evidence["source_links"])
        self.assertTrue(any(
            link.get("relation") == "TEST_TO_SOURCE_IMPORT"
            and int(link.get("hop", 0) or 0) == 0
            for link in render_evidence["source_links"]
        ))

    def test_14_input_surface_carries_escape_and_movement_relations(self):
        input_surface = next(
            item for item in self.registry["surfaces"]
            if item.get("role") == "INPUT_OWNER"
        )
        relations = set(input_surface["structured_relations"])
        self.assertIn("PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW", relations)
        self.assertIn("PRESERVE_BEHAVIOR:MOVEMENT_INPUT", relations)
        self.assertIn("CURRENT_BEHAVIOR_OWNER", relations)

    def test_15_owner_surface_carries_ownership_relation(self):
        owner_surface = next(
            item for item in self.registry["surfaces"]
            if item.get("role") == "STATE_OWNER"
        )
        self.assertIn(
            "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER",
            owner_surface["structured_relations"],
        )

    def test_16_selection_keeps_current_sources_and_tests_bounded(self):
        selected = self.selection["selected"]
        self.assertEqual(
            len({item["surface_id"] for item in selected}), len(selected),
        )
        self.assertTrue(any(item["role"] == "RENDER_SURFACE" for item in selected))
        self.assertTrue(any(item["role"] == "INPUT_OWNER" for item in selected))
        self.assertTrue(any(item["role"] == "CURRENT_TEST" for item in selected))
        self.assertTrue(all(
            item["surface_id"] in self.selection["selected_surface_ids"]
            for item in selected
        ))

    def test_17_frame_is_complete_and_pre_model_coverage_ready(self):
        self.assertTrue(self.frame["frame_complete"])
        self.assertTrue(self.frame["frame_coverage_ready"])
        self.assertTrue(self.frame["structured_obligation_binding"])
        self.assertTrue(self.frame_check["valid"], self.frame_check)
        self.assertEqual(self.frame_check["status"], "READY")
        self.assertEqual(
            self.frame_check["coverage_status"], impact.IMPACT_FRAME_COVERAGE_READY,
        )
        self.assertTrue(self.coverage_check["valid"], self.coverage_check)

    def test_18_frame_coverage_has_zero_uncovered_obligations(self):
        coverage = self.frame["impact_decision_frame_coverage"]
        self.assertEqual(coverage["coverage_status"], impact.IMPACT_FRAME_COVERAGE_READY)
        self.assertEqual(coverage["uncovered_obligations"], [])
        self.assertEqual(coverage["uncovered_requirement_ids"], [])
        self.assertEqual(coverage["metrics"]["impact_obligations_total"], 4)
        self.assertEqual(coverage["metrics"]["impact_frame_covered_obligations"], 4)
        self.assertEqual(coverage["metrics"]["impact_frame_uncovered_obligations"], 0)

    def test_19_behavior_change_has_an_authorized_implementation_candidate(self):
        behavior = self._obligation("BEHAVIOR_CHANGE")
        candidate_ids = set(behavior["candidate_slots"])
        self.assertTrue(candidate_ids)
        candidates = [
            slot for slot in self.frame["decision_slots"]
            if slot["slot_id"] in candidate_ids
        ]
        self.assertTrue(any(
            "MUST_CHANGE" in slot["allowed_decisions"]
            and "IMPLEMENTATION_CHANGE" in slot["decision_capabilities"]["MUST_CHANGE"]
            and "USER_FACING_PAUSE_INDICATOR" in slot["surface_structured_relations"]
            and slot["surface_id"] not in set(slot["dnt_surface_ids"])
            and slot["surface_id"] not in set(slot["prohibited_surface_ids"])
            for slot in candidates
        ))
        render = self._slot("RENDER_SURFACE")
        self.assertIn(
            behavior["obligation_id"],
            render["obligations_satisfied_by_decision"]["MUST_CHANGE"],
        )

    def test_20_every_slot_exposes_complete_decision_capability_projection(self):
        taxonomy = impact.impact_decision_capability_taxonomy()
        for slot in self.frame["decision_slots"]:
            self.assertTrue(slot["surface_id"])
            self.assertTrue(slot["surface_path"])
            self.assertTrue(slot["surface_role"])
            self.assertIsInstance(slot["dnt"], list)
            self.assertIsInstance(slot["prohibitions"], list)
            self.assertIsInstance(slot["allowed_decisions"], list)
            self.assertEqual(set(slot["decision_capabilities"]), set(slot["allowed_decisions"]))
            self.assertEqual(
                set(slot["obligations_satisfied_by_decision"]),
                set(slot["allowed_decisions"]),
            )
            for decision in slot["allowed_decisions"]:
                self.assertEqual(
                    slot["decision_capabilities"][decision], taxonomy[decision],
                )
                self.assertIsInstance(
                    slot["obligations_satisfied_by_decision"][decision], list,
                )

    def test_21_controller_slots_offer_no_implementation_decision(self):
        controller_slots = [
            slot for slot in self.frame["decision_slots"]
            if slot["surface_path"] == "src/pause_controller.js"
        ]
        self.assertGreaterEqual(len(controller_slots), 2)
        for slot in controller_slots:
            self.assertNotIn("MUST_CHANGE", slot["allowed_decisions"])
            self.assertNotIn("IMPLEMENTATION_CHANGE", {
                capability
                for values in slot["decision_capabilities"].values()
                for capability in values
            })

    def test_22_test_surfaces_keep_test_only_capability(self):
        test_slots = [
            slot for slot in self.frame["decision_slots"]
            if slot["surface_role"] == "CURRENT_TEST"
        ]
        self.assertTrue(test_slots)
        for slot in test_slots:
            self.assertIn("TEST_CHANGE", slot["allowed_decisions"])
            self.assertEqual(slot["surface_capabilities"], ["TEST_CHANGE"])
            self.assertNotIn("IMPLEMENTATION_CHANGE", {
                capability
                for values in slot["decision_capabilities"].values()
                for capability in values
            })

    def test_23_test_change_is_not_the_behavior_change_candidate(self):
        behavior = self._obligation("BEHAVIOR_CHANGE")
        test_slot_ids = {
            slot["slot_id"] for slot in self.frame["decision_slots"]
            if slot["surface_role"] == "CURRENT_TEST"
        }
        self.assertFalse(test_slot_ids.intersection(behavior["candidate_slots"]))
        self.assertEqual(behavior["candidate_decisions"], ["MUST_CHANGE"])
        self.assertNotIn("TEST_CHANGE", behavior["candidate_decisions"])

    def test_24_all_preservation_obligations_are_inherited_current_state(self):
        for item in self.frame["impact_decision_frame_coverage"]["obligations"]:
            if item["obligation_type"] != "PRESERVATION":
                continue
            self.assertTrue(item["inherited_satisfaction"], item)
            self.assertTrue(item["inherited_slots"], item)
            self.assertIn("INHERITED_CURRENT", item["coverage_reasons"])
            self.assertTrue(item["coverage_ready"], item)

    def test_25_ownership_migration_and_new_owner_are_unavailable(self):
        for slot in self.frame["decision_slots"]:
            self.assertNotIn("NEW_OWNER", slot["allowed_decisions"])
            self.assertNotIn("OWNER_MIGRATION", slot["allowed_decisions"])
            self.assertNotIn("AUTHORITY_CHANGE", slot["allowed_decisions"])
            self.assertEqual(slot["authority_change_targets"], [])
        self.assertFalse(self.frame["authority_change_authorized"])
        self.assertEqual(self.frame["authority_change_targets"], [])

    def test_26_exact_frame_hash_and_coverage_hash_are_canonical(self):
        coverage = self.frame["impact_decision_frame_coverage"]
        self.assertEqual(
            self.frame["frame_hash"], impact.impact_decision_frame_hash(self.frame),
        )
        self.assertEqual(
            coverage["coverage_hash"], impact.impact_decision_coverage_hash(coverage),
        )
        self.assertEqual(
            self.frame_check["frame_hash"], self.frame["frame_hash"],
        )
        self.assertEqual(
            self.coverage_check["coverage_hash"], coverage["coverage_hash"],
        )

    def test_27_weak_inspect_only_choice_stops_before_challenger(self):
        weak = self._choices()
        structural = impact.validate_impact_decision_choices(
            weak, self.frame, include_coverage=False,
        )
        self.assertTrue(structural["valid"], structural)
        semantic = impact.validate_impact_decision_choices(weak, self.frame)
        self.assertFalse(semantic["valid"])
        self.assertTrue(semantic["status"].startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP))
        self.assertIn(
            self._obligation("BEHAVIOR_CHANGE")["obligation_id"],
            semantic["uncovered_obligations"],
        )
        self.assertEqual(semantic["model_calls"], 0)

    def test_28_actionable_choice_compiles_map_and_assigns_requirement(self):
        choices = impact.deterministic_impact_decision_choices(self.frame)
        checked = impact.validate_impact_decision_choices(choices, self.frame)
        self.assertTrue(checked["valid"], checked)
        render_choice = next(
            item for item in choices["decisions"]
            if item["slot_id"] == self._slot("RENDER_SURFACE")["slot_id"]
        )
        self.assertEqual(render_choice["decision"], "MUST_CHANGE")
        compiled = impact.compile_impact_map_from_choices(
            self.frame,
            choices,
            self.requirements,
            self.context["current_repository_evidence"],
            surface_registry=self.registry,
            impact_seeds=self.seeds,
            task_goal=self.REQUIREMENT,
        )
        self.assertTrue(compiled["valid"], compiled)
        self.assertIsNotNone(compiled["impact_map"])
        assignments = compiled["impact_map"]["obligation_assignments"]
        behavior_id = self._obligation("BEHAVIOR_CHANGE")["obligation_id"]
        behavior_assignment = next(
            item for item in assignments if item["obligation_id"] == behavior_id
        )
        self.assertEqual(behavior_assignment["chosen_decision"], "MUST_CHANGE")
        self.assertIn("IMPLEMENTATION_CHANGE", behavior_assignment["decision_capability"])
        self.assertEqual(behavior_assignment["requirement_id"], self.REQUIREMENT_ID)

    def test_29_actionable_map_has_no_requirement_gap_challenge(self):
        choices = impact.deterministic_impact_decision_choices(self.frame)
        compiled = impact.compile_impact_map_from_choices(
            self.frame,
            choices,
            self.requirements,
            self.context["current_repository_evidence"],
            surface_registry=self.registry,
            impact_seeds=self.seeds,
            task_goal=self.REQUIREMENT,
        )
        self.assertTrue(compiled["valid"], compiled)
        challenges = impact.deterministic_challenges(
            compiled["impact_map"],
            self.requirements,
            self.context["current_repository_evidence"],
            self.registry,
        )
        self.assertNotIn(
            "REQUIREMENT_GAP",
            {item.get("challenge_type") for item in challenges},
        )
        self.assertEqual(compiled["model_calls"], 0)

    def test_30_dnt_targeting_is_explicit_not_token_based(self):
        protected = {
            "surface_id": "SURF-CONTROLLER",
            "kind": "OWNER",
            "role": "STATE_OWNER",
            "path": "src/pause_controller.js",
            "symbol": "PauseController",
        }
        test_surface = {
            "surface_id": "SURF-TEST",
            "kind": "TEST",
            "role": "CURRENT_TEST",
            "path": "tests/input.test.js",
            "symbol": "PauseController",
        }
        constraint = {
            "dnt": ["Do not modify src/pause_controller.js."],
            "prohibitions": ["Do not modify src/pause_controller.js."],
            "dnt_surface_ids": [],
            "prohibited_surface_ids": [],
        }
        self.assertTrue(impact._frame_surface_is_forbidden(protected, constraint))
        self.assertFalse(impact._frame_surface_is_forbidden(test_surface, constraint))

    def test_31_deterministic_fallback_does_not_mutate_unbound_input(self):
        choices = impact.deterministic_impact_decision_choices(self.frame)
        input_slot = self._slot("INPUT_OWNER")
        input_choice = next(
            item for item in choices["decisions"]
            if item["slot_id"] == input_slot["slot_id"]
        )
        self.assertEqual(input_choice["decision"], "INSPECT_ONLY")
        self.assertEqual(input_choice["chosen_target"], input_slot["surface_id"])
        self.assertEqual(
            input_slot["obligations_satisfied_by_decision"]["MUST_CHANGE"], [],
        )

    def test_32_stale_current_preservation_does_not_inherit(self):
        input_slot = copy.deepcopy(self._slot("INPUT_OWNER"))
        input_slot["required_preservation_promises"] = [{
            "text": "Escape flows through the existing pause interface.",
            "requirement_ids": [self.REQUIREMENT_ID],
            "structured_relations": ["PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW"],
            "status": "STALE",
        }]
        escape = self._obligation(
            "PRESERVATION", relation="PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW",
        )
        self.assertFalse(impact._frame_inherited_obligation(escape, input_slot))

    def test_33_mismatched_preservation_relation_fails_closed(self):
        input_slot = copy.deepcopy(self._slot("INPUT_OWNER"))
        input_slot["required_preservation_promises"] = [{
            "text": "Movement behavior remains intact.",
            "requirement_ids": [self.REQUIREMENT_ID],
            "structured_relations": ["PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW"],
        }]
        movement = self._obligation(
            "PRESERVATION", relation="PRESERVE_BEHAVIOR:MOVEMENT_INPUT",
        )
        self.assertFalse(impact._frame_inherited_obligation(movement, input_slot))

    def test_34_preservation_only_semantics_do_not_force_owner_mutation(self):
        requirement = [{
            "requirement_id": "REQ-LEGACY-PRESERVE",
            "text": "Preserve the existing export owner.",
            "status": "active",
        }]
        evidence = [{
            "evidence_id": "REPO-LEGACY-002",
            "category": "CURRENT_STATE_OWNER",
            "path": "src/export.js",
            "symbol": "ExportController",
            "fact": "ExportController remains the existing owner.",
            "file_sha256": "b" * 64,
        }]
        brain = {
            "project_id": "legacy-preserve-project",
            "task_id": "legacy-preserve-task",
            "task_goal": {"text": requirement[0]["text"]},
            "current_owners": [{
                "text": evidence[0]["fact"],
                "path": evidence[0]["path"],
                "symbol": evidence[0]["symbol"],
                "category": evidence[0]["category"],
                "evidence_ids": [evidence[0]["evidence_id"]],
            }],
            "current_state_ownership": [{
                "text": evidence[0]["fact"],
                "path": evidence[0]["path"],
                "symbol": evidence[0]["symbol"],
                "category": evidence[0]["category"],
                "evidence_ids": [evidence[0]["evidence_id"]],
            }],
            "preservation_constraints": [{
                "text": requirement[0]["text"],
                "requirement_ids": [requirement[0]["requirement_id"]],
            }],
        }
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(brain, requirement, evidence, registry=registry)
        core = impact.build_canonical_mandatory_planning_core({
            "requirements": requirement,
            "surfaces": registry["surfaces"],
            "impact_seeds": seeds,
            "preservation_constraints": brain["preservation_constraints"],
        })
        frame = impact.build_impact_decision_frame(
            brain, requirement, evidence,
            surface_registry=registry, impact_seeds=seeds, mandatory_core=core,
        )
        owner = frame["decision_slots"][0]
        self.assertNotIn("MUST_CHANGE", owner["allowed_decisions"])
        self.assertIn("PRESERVATION_ONLY", owner["allowed_decisions"])

    def test_35_legacy_artifacts_do_not_enter_structured_binding_mode(self):
        _, _, _, registry, _, frame = self._legacy_behavior_fixture()
        self.assertFalse(frame["structured_obligation_binding"])
        self.assertTrue(any(
            "MUST_CHANGE" in slot["allowed_decisions"]
            for slot in frame["decision_slots"]
        ))
        self.assertTrue(impact.validate_impact_decision_frame(frame)["valid"])
        self.assertEqual(registry["provenance"], "REPOSITORY_EVIDENCE")

    def test_36_no_render_signal_does_not_promote_generic_source(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v2442_render_gap_") as name:
            root = Path(name)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "plain.js").write_text(
                "function transform(value) { return value + 1; }\n"
                "module.exports = { transform };\n",
                encoding="utf-8",
            )
            (root / "tests" / "plain.test.js").write_text(
                "const assert = require('assert/strict');\n"
                "const { transform } = require('../src/plain');\n"
                "assert.equal(transform(1), 2);\n",
                encoding="utf-8",
            )
            inventory = understanding.inventory_repository(root)
            search = understanding.search_repository(root, inventory, ["transform"])
            inspected = understanding.inspect_repository_candidates(
                root,
                inventory,
                search["candidates"],
                task_terms=["transform"],
            )
            self.assertTrue(inspected["evidence"])
            self.assertFalse(any(
                "CURRENT_RENDER_SURFACE" in item.get("structured_relations", [])
                for item in inspected["evidence"]
            ))

    def test_37_comments_do_not_create_import_edges(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v2442_import_edges_") as name:
            root = Path(name)
            (root / "src").mkdir()
            (root / "tests").mkdir()
            (root / "src" / "real.js").write_text(
                "function real(value) { return value; }\n"
                "module.exports = { real };\n",
                encoding="utf-8",
            )
            (root / "src" / "ghost.js").write_text(
                "function ghost(value) { return value; }\n"
                "module.exports = { ghost };\n",
                encoding="utf-8",
            )
            (root / "tests" / "real.test.js").write_text(
                "const assert = require('assert/strict');\n"
                "// const { ghost } = require('../src/ghost');\n"
                "const { real } = require('../src/real');\n"
                "assert.equal(real(1), 1);\n",
                encoding="utf-8",
            )
            inventory = understanding.inventory_repository(root)
            search = understanding.search_repository(root, inventory, ["real"])
            candidates = {
                item["path"]: item for item in search["candidates"]
            }
            self.assertIn("tests/real.test.js", candidates)
            self.assertIn("src/real.js", candidates)
            self.assertNotIn("src/ghost.js", candidates)
            self.assertFalse(any(
                link.get("path") == "src/ghost.js"
                for item in candidates.values()
                for link in item.get("source_links", [])
            ))

    def test_38_frame_and_choice_operations_are_zero_model(self):
        choices = impact.deterministic_impact_decision_choices(self.frame)
        results = [
            self.frame_check,
            self.coverage_check,
            impact.validate_impact_decision_choices(
                choices, self.frame, include_coverage=False,
            ),
            impact.build_impact_decision_choice_coverage(self.frame, choices),
            self.core,
            self.ledger,
        ]
        for result in results:
            self.assertEqual(int(result.get("model_calls", 0) or 0), 0, result)
        self.assertEqual(self.reentry["model_calls"], 0)
        self.assertEqual(self.fresh["model_calls"], 0)
        self.assertEqual(self.context["model_calls"], 0)
        self.assertEqual(
            self.context["model_call_accounting"]["gemma_total"], 0,
        )

    def test_39_no_provider_role_or_challenger_is_started(self):
        self.assertNotIn("provider_generation_identity", self.frame)
        self.assertNotIn("ImpactChallenger", self.frame)
        self.assertFalse(self.reentry["execution_started"])
        self.assertFalse(self.reentry["stage6b_invoked"])
        self.assertEqual(self.context["source_provenance"]["execution_started"], False)
        self.assertEqual(self.context["source_provenance"]["model_calls"], 0)

    def test_40_project_brain_and_subject_remain_byte_identical(self):
        brain_after = self.store.project_brain_snapshot(self.PROJECT_ID)
        self.assertEqual(brain_after, self.brain_before)
        self.assertEqual(
            MemoryStore._canonical_hash(brain_after), self.BRAIN_HASH,
        )
        self.assertEqual(self.DATABASE.read_bytes(), self.db_bytes_before)
        self.assertEqual(
            {
                relative: hashlib.sha256((self.ROOT / relative).read_bytes()).hexdigest()
                for relative in self.SUBJECT
            },
            self.SUBJECT_HASHES,
        )

    def test_41_requirements_and_surface_ids_are_conserved(self):
        self.assertEqual(
            {item["requirement_id"] for item in self.context["new_requirements"]},
            {self.REQUIREMENT_ID},
        )
        self.assertEqual(
            set(self.selection["selected_surface_ids"]),
            {item["surface_id"] for item in self.seeds},
        )
        self.assertTrue(all(
            item["surface_id"] in self.selection["registry_surface_ids"]
            for item in self.seeds
        ))

    def test_42_coverage_does_not_grant_mutation_authority(self):
        render = self._slot("RENDER_SURFACE")
        self.assertIn("MUST_CHANGE", render["allowed_decisions"])
        self.assertNotIn("NEW_OWNER", render["allowed_decisions"])
        self.assertNotIn("OWNER_MIGRATION", render["allowed_decisions"])
        self.assertEqual(render["authority_change_targets"], [])
        self.assertEqual(render["allowed_targets"][0], render["surface_id"])
        self.assertTrue(all(
            target in {
                slot["surface_id"]
                for slot in self.frame["decision_slots"]
            } | set(render["required_interfaces"])
            for target in render["allowed_targets"]
        ))


if __name__ == "__main__":
    unittest.main()
