import copy
import json
import tempfile
import unittest

import mini
from hivo import impact_planning as impact
from hivo import verified_planning as planning
from tests.test_verified_state_planning import VerifiedStatePlanningTests


class ImpactDecisionFrameTests(unittest.TestCase):
    """Provider-free V24.3 frame, choice, and compiler regressions."""

    REQUIREMENT_ID = "REQ-PAUSE-INDICATOR"

    def setUp(self):
        mini.reset_run("v24.3-decision-frame")
        self.requirements = [{
            "requirement_id": self.REQUIREMENT_ID,
            "text": (
                "Add a user-facing pause indicator while preserving PauseController "
                "as the sole pause-state owner, Escape behavior, and movement behavior."
            ),
            "provenance": impact.USER_STATED,
            "status": "active",
        }]
        self.evidence = [
            {
                "evidence_id": "REPO-OWNER", "category": "CURRENT_STATE_OWNER",
                "path": "src/pause_controller.js", "symbol": "PauseController",
                "fact": "PauseController owns pause state", "file_sha256": "a" * 64,
            },
            {
                "evidence_id": "REPO-INTERFACE", "category": "CURRENT_INTERFACE",
                "path": "src/pause_controller.js", "symbol": "PauseController.togglePause",
                "fact": "PauseController.togglePause is the current pause transition interface",
                "file_sha256": "b" * 64,
            },
            {
                "evidence_id": "REPO-INPUT", "category": "CURRENT_BEHAVIOR",
                "path": "src/input.js", "symbol": "handleInput",
                "fact": "Escape flows through PauseController.togglePause and movement remains intact",
                "file_sha256": "c" * 64,
            },
            {
                "evidence_id": "REPO-TEST", "category": "CURRENT_TEST",
                "path": "tests/pause.test.js", "symbol": "pause flow",
                "fact": "focused input tests cover Escape and movement behavior",
                "file_sha256": "d" * 64,
            },
        ]
        self.brain = {
            "project_id": "v24.3-project", "task_id": "v24.3-task",
            "task_goal": {"text": self.requirements[0]["text"]},
            "current_owners": [{
                "record_id": "OWNER-RECORD", "text": "PauseController owns pause state",
                "path": "src/pause_controller.js", "symbol": "PauseController",
                "category": "CURRENT_STATE_OWNER", "evidence_ids": ["REPO-OWNER"],
            }],
            "current_state_ownership": [{
                "record_id": "STATE-RECORD", "text": "PauseController owns pause state",
                "path": "src/pause_controller.js", "symbol": "PauseController",
                "category": "CURRENT_STATE_OWNER", "evidence_ids": ["REPO-OWNER"],
            }],
            "current_interfaces": [{
                "record_id": "INTERFACE-RECORD",
                "text": "PauseController.togglePause is the current pause transition interface",
                "path": "src/pause_controller.js", "symbol": "PauseController.togglePause",
                "category": "CURRENT_INTERFACE", "evidence_ids": ["REPO-INTERFACE"],
            }],
            "relevant_tests": [{
                "record_id": "TEST-RECORD",
                "text": "focused input tests cover Escape and movement behavior",
                "path": "tests/pause.test.js", "symbol": "pause flow",
                "category": "CURRENT_TEST", "evidence_ids": ["REPO-TEST"],
            }],
            "preservation_constraints": [
                {
                    "record_id": "PRES-OWNER",
                    "text": "PauseController remains the sole pause-state owner.",
                    "requirement_ids": [self.REQUIREMENT_ID],
                },
                {
                    "record_id": "PRES-ESCAPE", "text": "Preserve current Escape behavior.",
                    "requirement_ids": [self.REQUIREMENT_ID], "evidence_ids": ["REPO-INPUT"],
                },
                {
                    "record_id": "PRES-MOVEMENT", "text": "Preserve current movement behavior.",
                    "requirement_ids": [self.REQUIREMENT_ID], "evidence_ids": ["REPO-INPUT"],
                },
            ],
            "dnt": ["Do not create a second pause-state owner."],
            "prohibitions": ["Do not create a second pause-state owner."],
        }
        self.registry = impact.build_canonical_surface_registry(self.brain, self.evidence)
        self.seeds = impact.build_impact_seeds(
            self.brain, self.requirements, self.evidence, registry=self.registry,
        )
        self.core = impact.build_canonical_mandatory_planning_core({
            "project_id": self.brain["project_id"], "task_id": self.brain["task_id"],
            "task_goal": self.brain["task_goal"], "requirements": self.requirements,
            "surfaces": self.registry["surfaces"], "impact_seeds": self.seeds,
            "preservation_constraints": self.brain["preservation_constraints"],
            "dnt": self.brain["dnt"], "prohibitions": self.brain["prohibitions"],
        })
        self.frame = impact.build_impact_decision_frame(
            self.brain, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            mandatory_core=self.core,
        )
        self.frame_check = impact.validate_impact_decision_frame(self.frame)
        self.choices = impact.deterministic_impact_decision_choices(self.frame)

    def test_field_ownership_audit_covers_required_fields(self):
        audit = impact.impact_map_field_ownership()
        required = {
            "impact_id", "seed_id", "surface_id", "decision_kind", "disposition",
            "preservation_promises", "verification_contracts", "mutation_target",
            "reuse_target", "rationale", "scope_notes", "risk_notes",
        }
        self.assertTrue(required.issubset(audit))
        self.assertTrue(all(audit[field].get("owner") for field in required))
        self.assertEqual(audit["impact_id"]["owner"], "DETERMINISTIC_AUTHORITY")
        self.assertEqual(audit["path"]["owner"], "DETERMINISTIC_REPOSITORY_EVIDENCE")
        self.assertEqual(audit["disposition"]["owner"], "MODEL_DECISION")
        self.assertEqual(audit["rationale"]["owner"], "MODEL_OPTIONAL")

    def test_frame_is_complete_hash_bound_and_zero_model(self):
        self.assertTrue(self.frame_check["valid"], self.frame_check)
        self.assertEqual(self.frame_check["model_calls"], 0)
        self.assertEqual(self.frame["frame_hash"], impact.impact_decision_frame_hash(self.frame))
        self.assertEqual(len(self.frame["decision_slots"]), len(self.seeds))
        self.assertEqual(self.frame["frame_hash"], impact.build_impact_decision_frame(
            self.brain, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            mandatory_core=self.core,
        )["frame_hash"])

    def test_frame_contains_owner_interface_dnt_and_bounded_choices(self):
        encoded = json.dumps(self.frame, ensure_ascii=False, sort_keys=True)
        self.assertIn("PauseController", encoded)
        self.assertIn("PauseController.togglePause", encoded)
        self.assertIn("Do not create a second pause-state owner.", encoded)
        owner_slots = [
            item for item in self.frame["decision_slots"]
            if (item.get("current_owner") or {}).get("symbol") == "PauseController"
        ]
        self.assertTrue(owner_slots)
        self.assertTrue(any("SURF-" in item for item in owner_slots[0]["required_interfaces"]))
        self.assertTrue(all("NEW_OWNER" not in item["allowed_decisions"] for item in self.frame["decision_slots"]))

    def test_frame_hash_changes_when_authority_changes(self):
        for field, mutation in (
            ("allowed_decisions", lambda value: value.append("INSPECT_ONLY")),
            ("required_preservation_promises", lambda value: value.append({
                "obligation_id": "PRES-NEW", "text": "Preserve a new obligation.",
                "requirement_ids": [self.REQUIREMENT_ID], "evidence_refs": [],
            })),
            ("required_verification_contracts", lambda value: value.append({
                "obligation_id": "VERIFY-NEW", "text": "Run the existing focused test.",
                "requirement_ids": [self.REQUIREMENT_ID], "evidence_refs": [],
            })),
            ("authority_refs", lambda value: value.append("AUTH-NEW")),
        ):
            changed = copy.deepcopy(self.frame)
            mutation(changed["decision_slots"][0][field])
            self.assertNotEqual(self.frame["frame_hash"], impact.impact_decision_frame_hash(changed))

    def test_minimal_choices_are_valid_and_order_independent(self):
        result = impact.validate_impact_decision_choices(self.choices, self.frame)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["model_calls"], 0)
        reverse = {"decisions": list(reversed(self.choices["decisions"]))}
        reverse_result = impact.validate_impact_decision_choices(reverse, self.frame)
        self.assertTrue(reverse_result["valid"], reverse_result)
        self.assertEqual(result["choice_hash"], reverse_result["choice_hash"])

    def test_duplicate_missing_unknown_forbidden_and_target_fail_closed(self):
        duplicate = {"decisions": [self.choices["decisions"][0], self.choices["decisions"][0]]}
        self.assertIn(
            impact.DUPLICATE_IMPACT_DECISION_SLOT,
            impact.validate_impact_decision_choices(duplicate, self.frame)["errors"],
        )
        missing = {"decisions": self.choices["decisions"][:-1]}
        self.assertIn(
            impact.MISSING_IMPACT_DECISION_SLOT,
            impact.validate_impact_decision_choices(missing, self.frame)["errors"],
        )
        unknown = copy.deepcopy(self.choices)
        unknown["decisions"][-1]["slot_id"] = "SLOT-999"
        self.assertIn(
            impact.UNKNOWN_IMPACT_DECISION_SLOT,
            impact.validate_impact_decision_choices(unknown, self.frame)["errors"],
        )
        forbidden = copy.deepcopy(self.choices)
        forbidden["decisions"][0]["decision"] = "NEW_OWNER"
        self.assertIn(
            impact.IMPACT_DECISION_NOT_ALLOWED,
            impact.validate_impact_decision_choices(forbidden, self.frame)["errors"],
        )
        target = copy.deepcopy(self.choices)
        target["decisions"][0]["chosen_target"] = "SURF-999"
        self.assertIn(
            impact.IMPACT_DECISION_TARGET_NOT_ALLOWED,
            impact.validate_impact_decision_choices(target, self.frame)["errors"],
        )

    def test_authority_fields_cannot_be_overwritten_and_empty_model_fields_fail(self):
        authority = copy.deepcopy(self.choices)
        authority["decisions"][0]["preservation_promises"] = ["overwrite"]
        result = impact.validate_impact_decision_choices(authority, self.frame)
        self.assertFalse(result["valid"])
        self.assertIn(impact.IMPACT_DECISION_OUTPUT_MALFORMED, result["errors"][0])
        empty = copy.deepcopy(self.choices)
        empty["decisions"][0]["bounded_rationale"] = ""
        result = impact.validate_impact_decision_choices(empty, self.frame)
        self.assertFalse(result["valid"])
        self.assertIn(impact.IMPACT_DECISION_OUTPUT_MALFORMED, result["errors"])

    def test_legacy_failed_live_shape_is_invalid_and_not_repaired(self):
        legacy = {
            "impacts": [
                {
                    "impact_id": "IMPACT-001", "surface_id": "IFACE-1",
                    "disposition": "INTERFACE_REUSE", "action": "Reuse IFACE-1",
                    "preservation_promises": [], "verification_contracts": [],
                    "requirement_ids": [self.REQUIREMENT_ID],
                },
                {
                    "impact_id": "IMPACT-002", "surface_id": "IFACE-1",
                    "disposition": "INTERFACE_REUSE", "action": "Reuse IFACE-1",
                    "preservation_promises": [], "verification_contracts": [],
                    "requirement_ids": [self.REQUIREMENT_ID],
                },
            ],
        }
        validation = impact.validate_impact_decision_choices(legacy, self.frame)
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["status"], impact.IMPACT_DECISION_OUTPUT_MALFORMED)
        compiled = impact.compile_impact_map_from_choices(
            self.frame, legacy, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
        )
        self.assertFalse(compiled["valid"])
        self.assertIsNone(compiled["impact_map"])
        self.assertEqual(compiled["model_calls"], 0)

    def test_valid_choices_compile_inherited_obligations_and_pass_existing_validator(self):
        compiled = impact.compile_impact_map_from_choices(
            self.frame, self.choices, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            task_goal=self.requirements[0]["text"],
            provider_generation_identity={"model": "gemma4:e4b", "generation": 1},
        )
        self.assertTrue(compiled["valid"], compiled)
        self.assertEqual(compiled["model_calls"], 0)
        self.assertTrue(compiled["semantic_validation"]["valid"])
        self.assertEqual(compiled["impact_map"]["impact_decision_frame_hash"], self.frame["frame_hash"])
        self.assertIn("impact_decision_choice_hash", compiled["impact_map"])
        self.assertIn("source_planning_context_hash", compiled["impact_map"]["planning_provenance"])
        for item in compiled["impact_map"]["impacts"]:
            if item["surface_id"] in {
                slot["surface_id"] for slot in self.frame["decision_slots"]
                if slot["required_preservation_promises"]
            }:
                self.assertTrue(item["preservation_promises"])
        self.assertGreater(compiled["inherited_verification_count"], 0)
        self.assertEqual(
            impact.validate_impact_map(
                compiled["impact_map"], self.requirements, self.evidence,
                surface_registry=self.registry,
            )["valid"],
            True,
        )

    def test_duplicate_surface_is_one_slot_unless_explicitly_separate(self):
        duplicate_seeds = copy.deepcopy(self.seeds)
        duplicate_seeds.append(copy.deepcopy(duplicate_seeds[0]))
        merged = impact.build_impact_decision_frame(
            self.brain, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=duplicate_seeds,
            mandatory_core=self.core,
        )
        self.assertEqual(len(merged["decision_slots"]), len(self.frame["decision_slots"]))
        separate_seeds = copy.deepcopy(self.seeds)
        separate = copy.deepcopy(separate_seeds[0])
        separate["separate_decision"] = True
        separate_seeds.append(separate)
        separate_frame = impact.build_impact_decision_frame(
            self.brain, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=separate_seeds,
            mandatory_core=self.core,
        )
        self.assertEqual(len(separate_frame["decision_slots"]), len(self.frame["decision_slots"]) + 1)

    def test_indicator_only_frame_does_not_expose_authority_change(self):
        for slot in self.frame["decision_slots"]:
            self.assertNotIn("AUTHORITY_CHANGE", slot["allowed_decisions"])
            self.assertNotIn("NEW_OWNER", slot["allowed_decisions"])

    def test_explicit_future_authority_change_is_bounded_and_still_an_approval_candidate(self):
        requirements = copy.deepcopy(self.requirements)
        requirements[0]["authority_change_authorized"] = True
        requirements[0]["authority_change"] = {
            "type": "AUTHORITY_CHANGE", "from": "PauseController",
            "to": "StatusView", "authorized": True,
        }
        frame = impact.build_impact_decision_frame(
            self.brain, requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            mandatory_core=self.core,
        )
        owner = next(item for item in frame["decision_slots"] if item.get("current_owner"))
        self.assertIn("AUTHORITY_CHANGE", owner["allowed_decisions"])
        self.assertIn("StatusView", owner["allowed_targets"])
        self.assertEqual(
            impact.validate_impact_decision_frame(frame)["valid"], True,
        )

    def test_missing_explicit_required_authority_blocks_before_model(self):
        brain = copy.deepcopy(self.brain)
        brain["preservation_constraints"] = []
        brain["required_preservation_promises"] = [{"obligation_id": "PRES-REQUIRED"}]
        requirements = [{
            "requirement_id": "REQ-NO-AUTH", "text": "Add a pause indicator.",
            "provenance": impact.USER_STATED,
        }]
        frame = impact.build_impact_decision_frame(
            brain, requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
        )
        result = impact.validate_impact_decision_frame(frame)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], impact.IMPACT_DECISION_FRAME_INCOMPLETE)
        self.assertEqual(result["model_calls"], 0)

    def test_packet_is_bounded_exactly_rendered_and_keeps_core_coverage(self):
        renderer = lambda value: "IMPACT DECISION PACKET:\n" + impact._compact_json(value)
        packet = impact.build_impact_decision_packet(
            self.frame, render=renderer, base_render=renderer, mandatory_core=self.core,
        )
        role_packet = packet["role_packet"]
        self.assertTrue(packet["packet_complete"], packet)
        self.assertLessEqual(packet["packet_chars"], impact.MAX_PLANNER_CONTEXT_CHARS)
        self.assertEqual(role_packet["exact_model_input"], role_packet["rendered_packet"])
        self.assertTrue(role_packet["accounting"]["matches_exact_render"])
        self.assertEqual(role_packet["mandatory_semantic_coverage_rate"], 1.0)
        self.assertNotIn("JSON SCHEMA", role_packet["exact_model_input"])

    def test_create_impact_map_uses_choice_schema_and_reaches_existing_boundary(self):
        source = VerifiedStatePlanningTests.brain()
        context = planning.compile_verified_planning_context(source)
        contract = planning.build_planning_contract(context)
        stage3_brain = planning.build_stage3_task_brain(context)
        seen = {}

        def callback(prompt, validator, label, schema):
            seen.update({"prompt": prompt, "label": label, "schema": schema})
            return impact.deterministic_impact_decision_choices(mini.RUN["impact_decision_frame"])

        result = mini.create_impact_map(
            stage3_brain, contract, context["current_repository_evidence"],
            structured_call=callback, verified_planning_context=context,
        )
        self.assertEqual(seen["label"], "impact-decision")
        self.assertEqual(seen["schema"], impact.impact_decision_choice_schema())
        self.assertTrue(impact.validate_impact_map(
            result, contract.get("source_requirement_ledger", {}).get("requirements", []),
            context["current_repository_evidence"], surface_registry=mini.RUN["canonical_surface_registry"],
        )["valid"])
        self.assertEqual(mini.RUN["impact_planner_calls"], 1)
        self.assertEqual(mini.RUN["impact_decision_frames_created"], 1)
        self.assertEqual(mini.RUN["impact_maps_compiled_from_choices"], 1)
        self.assertEqual(mini.RUN["impact_decision_frame_validation"]["model_calls"], 0)

    def test_run_verified_state_planning_stops_at_approval_without_execution(self):
        source = VerifiedStatePlanningTests.brain()
        with tempfile.TemporaryDirectory(prefix="hivo_v24_3_frame_") as root:
            result, _memory = mini.run_verified_state_aware_planning(
                fresh_task_brain=source, memory={}, workspace=root, finish=False,
            )
        self.assertEqual(result["status"], "plan_approval_required", result)
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(mini.RUN["impact_decision_frames_created"], 1)
        self.assertEqual(mini.RUN["impact_maps_compiled_from_choices"], 1)
        self.assertEqual(mini.RUN["worker_missions_executed"], 0)


if __name__ == "__main__":
    unittest.main()
