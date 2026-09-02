import copy
import unittest

import mini
from hivo import impact_planning as impact
from tests import test_v24_4_2_current_surface_preservation_binding as current_surface_fixture


class DecisionRelevantImpactChoiceProjectionTests(unittest.TestCase):
    """Provider-free V24.4.3 projection and full-frame boundary tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        current_surface_fixture.CurrentSurfacePreservationBindingTests.setUpClass()
        cls.frame = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.frame)
        cls.core = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.core)
        cls.requirements = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.requirements)
        cls.evidence = copy.deepcopy(
            current_surface_fixture.CurrentSurfacePreservationBindingTests.context["current_repository_evidence"]
        )
        cls.registry = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.registry)
        cls.seeds = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.seeds)
        cls.brain = copy.deepcopy(current_surface_fixture.CurrentSurfacePreservationBindingTests.stage3_brain)

    @classmethod
    def tearDownClass(cls):
        current_surface_fixture.CurrentSurfacePreservationBindingTests.tearDownClass()
        super().tearDownClass()

    def projection(self):
        return impact.build_decision_relevant_impact_choice_projection(self.frame)

    def projected_choices(self, projection=None):
        projection = projection or self.projection()
        return impact.deterministic_impact_decision_choices(
            self.frame, projection=projection,
        )

    def test_full_frame_hash_and_contents_are_unchanged(self):
        before = copy.deepcopy(self.frame)
        before_hash = impact.impact_decision_frame_hash(self.frame)
        projection = self.projection()
        self.assertEqual(self.frame, before)
        self.assertEqual(self.frame["frame_hash"], before_hash)
        self.assertEqual(
            projection["source_frame_hash"], self.frame["frame_hash"],
        )
        self.assertEqual(
            projection["full_frame_semantic_coverage"], 1.0,
        )
        self.assertEqual(projection["full_provenance_reachable"], 1.0)

    def test_real_seven_slot_responsibility_taxonomy(self):
        projection = self.projection()
        classes = {
            item["slot_id"]: item["classification"]
            for item in projection["slot_classification"]
        }
        self.assertEqual(len(classes), 7)
        self.assertEqual(projection["required_choice_slot_ids"], ["SLOT-003"])
        self.assertEqual(
            [slot for slot, value in classes.items() if value == "DETERMINISTIC_INHERITED_ONLY"],
            ["SLOT-001", "SLOT-002", "SLOT-004"],
        )
        self.assertEqual(
            [slot for slot, value in classes.items() if value == "EVIDENCE_ONLY"],
            ["SLOT-005", "SLOT-006", "SLOT-007"],
        )
        required = projection["provenance_map"]["slots"]["SLOT-003"]
        self.assertEqual(required["surface_id"], "SURF-003")
        self.assertIn("IMPLEMENTATION_CHANGE", required["decision_capabilities"]["MUST_CHANGE"])

    def test_projection_is_deterministic_and_valid(self):
        first = self.projection()
        second = self.projection()
        self.assertEqual(first, second)
        checked = impact.validate_decision_relevant_impact_choice_projection(
            first, self.frame,
        )
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(checked["model_calls"], 0)
        self.assertEqual(
            first["projection_hash"],
            impact.decision_relevant_impact_choice_projection_hash(first),
        )

    def test_packet_uses_exact_required_choice_projection(self):
        projection = self.projection()
        packet = impact.build_impact_decision_packet(
            self.frame,
            render=mini._impact_decision_frame_prompt,
            base_render=mini._impact_decision_frame_prompt,
            legacy_render=mini._impact_decision_frame_prompt_v24_4_2,
            mandatory_core=self.core,
        )
        self.assertTrue(packet["packet_complete"], packet)
        self.assertLessEqual(packet["packet_chars"], impact.MAX_PLANNER_CONTEXT_CHARS)
        role_packet = packet["role_packet"]
        self.assertEqual(role_packet["exact_model_input"], role_packet["rendered_packet"])
        self.assertEqual(packet["required_choice_slot_ids"], ["SLOT-003"])
        self.assertEqual(
            packet["required_model_choice_slot_coverage_rate"], 1.0,
        )
        self.assertEqual(packet["full_frame_semantic_coverage"], 1.0)
        self.assertEqual(packet["full_provenance_reachable"], 1.0)
        self.assertEqual(
            packet["legacy_payload_audit"]["representation"],
            "V24.4.2_FULL_SLOT_PAYLOAD",
        )
        self.assertEqual(
            packet["projection"]["projection_hash"], projection["projection_hash"],
        )
        model_slots = packet["packet"]["required_choice_slots"]
        self.assertEqual([item["slot_id"] for item in model_slots], ["SLOT-003"])
        self.assertIn("MUST_CHANGE", model_slots[0]["allowed_decisions"])
        self.assertIn("IMPLEMENTATION_CHANGE", model_slots[0]["decision_capabilities"]["MUST_CHANGE"])

    def test_shared_constraints_are_fanned_in_once(self):
        projection = self.projection()
        dnt_text = "Do not modify src/pause_controller.js."
        fixed = [item for item in projection["fixed_constraints"] if item["text"] == dnt_text]
        self.assertEqual(len(fixed), 1)
        alias = fixed[0]["alias"]
        self.assertEqual(
            projection["provenance_map"]["constraints"][alias]["slot_ids"],
            ["SLOT-001", "SLOT-002", "SLOT-003", "SLOT-004", "SLOT-005", "SLOT-006", "SLOT-007"],
        )
        self.assertEqual(
            sum(item["text"] == dnt_text for item in projection["model_payload"]["fixed_constraints"]),
            1,
        )

    def test_model_paths_are_relative(self):
        projection = self.projection()
        values = list(projection["model_payload"]["required_choice_slots"])
        values.extend(projection["model_payload"]["support_context"])
        for item in values:
            path = item.get("surface_path", "")
            self.assertFalse(path.startswith("/"))
            self.assertFalse(path.startswith("\\"))
            self.assertFalse(len(path) > 1 and path[1] == ":")

    def test_required_cardinality_rejects_missing_duplicate_and_excluded(self):
        projection = self.projection()
        choices = self.projected_choices(projection)
        self.assertTrue(
            impact.validate_impact_decision_choices(
                choices, self.frame, projection=projection,
            )["valid"]
        )
        missing = {"decisions": []}
        missing_check = impact.validate_impact_decision_choices(
            missing, self.frame, projection=projection,
        )
        self.assertFalse(missing_check["valid"])
        self.assertIn(impact.MISSING_IMPACT_DECISION_SLOT, missing_check["errors"])
        duplicate = {"decisions": [choices["decisions"][0], choices["decisions"][0]]}
        duplicate_check = impact.validate_impact_decision_choices(
            duplicate, self.frame, projection=projection,
        )
        self.assertFalse(duplicate_check["valid"])
        self.assertIn(impact.DUPLICATE_IMPACT_DECISION_SLOT, duplicate_check["errors"])
        legacy = impact.deterministic_impact_decision_choices(self.frame)
        excluded = {"decisions": [choices["decisions"][0], legacy["decisions"][0]]}
        excluded_check = impact.validate_impact_decision_choices(
            excluded, self.frame, projection=projection,
        )
        self.assertFalse(excluded_check["valid"])
        self.assertIn(impact.EXCLUDED_IMPACT_DECISION_SLOT, excluded_check["errors"])

    def test_valid_projected_must_change_compiles_full_map(self):
        projection = self.projection()
        choices = self.projected_choices(projection)
        checked = impact.validate_impact_decision_choices(
            choices, self.frame, projection=projection,
        )
        self.assertTrue(checked["valid"], checked)
        compiled = impact.compile_impact_map_from_choices(
            self.frame, choices, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            task_goal=self.requirements[0]["text"], projection=projection,
        )
        self.assertTrue(compiled["valid"], compiled)
        self.assertEqual(len(compiled["impact_map"]["impacts"]), 7)
        self.assertEqual(len(compiled["effective_choices"]["decisions"]), 7)
        self.assertEqual(compiled["model_calls"], 0)
        self.assertEqual(
            compiled["impact_map"]["impacts"][2]["chosen_decision"],
            "MUST_CHANGE",
        )
        for impact_item in compiled["impact_map"]["impacts"]:
            self.assertIn("required_preservation_promises", impact_item)
            self.assertIn("required_verification_contracts", impact_item)
            self.assertIn("obligation_ids", impact_item)
            self.assertIn("frame_provenance", impact_item)
            self.assertIn("dnt", impact_item)
            self.assertIn("prohibitions", impact_item)

    def test_inspect_only_behavior_choice_fails_post_choice_coverage(self):
        projection = self.projection()
        weak = self.projected_choices(projection)
        weak["decisions"][0]["decision"] = "INSPECT_ONLY"
        structural = impact.validate_impact_decision_choices(
            weak, self.frame, include_coverage=False, projection=projection,
        )
        self.assertTrue(structural["valid"], structural)
        semantic = impact.validate_impact_decision_choices(
            weak, self.frame, projection=projection,
        )
        self.assertFalse(semantic["valid"])
        self.assertTrue(semantic["status"].startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP))
        self.assertEqual(semantic["model_calls"], 0)

    def test_dnt_owner_is_not_model_required_and_has_no_mutation_choice(self):
        projection = self.projection()
        owner = next(
            item for item in projection["slot_classification"]
            if item["slot_id"] == "SLOT-002"
        )
        self.assertEqual(owner["classification"], "DETERMINISTIC_INHERITED_ONLY")
        self.assertTrue(owner["dnt_targeted"])
        self.assertNotIn("SLOT-002", projection["required_choice_slot_ids"])
        self.assertNotIn(
            "SLOT-002",
            [item["slot_id"] for item in projection["model_payload"]["required_choice_slots"]],
        )

    def test_explicit_test_obligation_can_require_its_bound_test_slot(self):
        requirement = copy.deepcopy(self.requirements)
        ledger = impact.build_requirement_obligation_ledger(requirement)
        record = ledger["requirements"][0]
        record["obligations"].append({
            "obligation_id": "OBL-EXPLICIT-TEST",
            "requirement_id": requirement[0]["requirement_id"],
            "obligation_type": "TEST",
            "meaning": "Update the input test for the pause indicator.",
            "text": "Update the input test for the pause indicator.",
            "candidate_surface_ids": ["SURF-005"],
            "provenance": impact.USER_STATED,
            "classification_provenance": impact.DERIVED_PLAN_DECISION,
        })
        record["obligation_types"].append("TEST")
        ledger["obligation_count"] += 1
        ledger["bounds"]["max_obligations"] = ledger["obligation_count"]
        frame = impact.build_impact_decision_frame(
            self.brain, requirement, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            mandatory_core=self.core, obligation_ledger=ledger,
            verified_planning_context=current_surface_fixture.CurrentSurfacePreservationBindingTests.context,
        )
        self.assertEqual(impact.validate_impact_decision_frame(frame)["status"], "READY")
        projection = impact.build_decision_relevant_impact_choice_projection(frame)
        test_slot = next(
            item for item in projection["slot_classification"]
            if item["slot_id"] == "SLOT-005"
        )
        self.assertEqual(test_slot["classification"], "MODEL_CHOICE_REQUIRED")
        self.assertIn("SLOT-005", projection["required_choice_slot_ids"])

    def test_architecture_self_test_remains_zero_model(self):
        result = impact.impact_decision_frame_self_test()
        self.assertTrue(result["passed"], result)
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(result["checks"]["projection_valid"])


if __name__ == "__main__":
    unittest.main()
