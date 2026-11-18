import copy
import unittest

import mini
from hivo import impact_planning as impact
from tests import test_v24_4_2_current_surface_preservation_binding as current_surface_fixture


class ChallengerReviewRelevantProjectionTests(unittest.TestCase):
    """Provider-free V24.4.4 Challenger projection and compatibility tests."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        current_surface_fixture.CurrentSurfacePreservationBindingTests.setUpClass()
        source = current_surface_fixture.CurrentSurfacePreservationBindingTests
        cls.frame = copy.deepcopy(source.frame)
        cls.core = copy.deepcopy(source.core)
        cls.requirements = copy.deepcopy(source.requirements)
        cls.evidence = copy.deepcopy(source.context["current_repository_evidence"])
        cls.registry = copy.deepcopy(source.registry)
        cls.seeds = copy.deepcopy(source.seeds)
        cls.brain = copy.deepcopy(source.stage3_brain)
        cls.verified_context = copy.deepcopy(source.context)
        cls.choices = source._choices(decision_by_role={"RENDER_SURFACE": "MUST_CHANGE"})
        cls.choice_check = impact.validate_impact_decision_choices(cls.choices, cls.frame)
        cls.compiled = impact.compile_impact_map_from_choices(
            cls.frame,
            cls.choices,
            cls.requirements,
            cls.evidence,
            surface_registry=cls.registry,
            impact_seeds=cls.seeds,
            task_goal=cls.requirements[0]["text"],
        )
        cls.impact_map = copy.deepcopy(cls.compiled["impact_map"])
        cls.renderer = mini._planning_provider_renderer(
            mini._impact_challenger_prompt,
            impact.challenge_schema(),
        )
        cls.packet = impact.build_challenger_packet(
            cls.impact_map,
            cls.requirements,
            cls.evidence,
            task_brain=cls.brain,
            surface_registry=cls.registry,
            max_chars=impact.MAX_CHALLENGER_CONTEXT_CHARS,
            role="ImpactChallenger",
            render=cls.renderer,
            base_render=mini._impact_challenger_prompt,
            verified_planning_context=cls.verified_context,
        )
        cls.projection = cls.packet["challenger_review_projection"]

    @classmethod
    def tearDownClass(cls):
        current_surface_fixture.CurrentSurfacePreservationBindingTests.tearDownClass()
        super().tearDownClass()

    def test_exact_fixture_closes_challenger_budget_without_provider(self):
        self.assertTrue(self.choice_check["valid"], self.choice_check)
        self.assertTrue(self.compiled["valid"], self.compiled)
        self.assertTrue(self.packet["packet_complete"], self.packet)
        self.assertEqual(self.packet["status"], "READY")
        self.assertLessEqual(self.packet["packet_chars"], 10000)
        self.assertEqual(
            self.packet["role_packet"]["exact_model_input"],
            self.packet["role_packet"]["rendered_packet"],
        )
        self.assertEqual(self.packet["role_packet"]["mandatory_drops"], [])
        self.assertEqual(self.packet["role_packet"]["optional_items_dropped_ids"], [])
        self.assertEqual(self.packet["reviewed_impact_ids"], self.packet["serialized_impact_ids"])
        self.assertEqual(self.packet["dropped_impact_ids"], [])
        budget = self.packet["packet_budget_audit"]
        self.assertEqual(budget["exact_rendered_chars"], self.packet["packet_chars"])
        self.assertEqual(budget["hard_limit_chars"], impact.MAX_CHALLENGER_CONTEXT_CHARS)
        self.assertGreaterEqual(budget["remaining_chars"], 250)
        self.assertEqual(budget["optional_chars"], 0)
        self.assertEqual(self.packet["model_calls"], 0)

    def test_projection_is_deterministic_and_has_complete_reachability(self):
        again = impact.build_challenger_review_projection(
            self.impact_map,
            self.requirements,
            self.evidence,
            self.registry,
            self.brain,
            self.verified_context,
        )
        self.assertEqual(self.projection, again)
        checked = impact.validate_challenger_review_projection(
            self.projection,
            self.impact_map,
            self.requirements,
            self.evidence,
            self.registry,
            self.brain,
            self.verified_context,
        )
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(checked["model_calls"], 0)
        self.assertEqual(
            self.projection["projection_hash"],
            impact.challenger_review_projection_hash(self.projection),
        )
        self.assertEqual(self.projection["full_map_authority_coverage"], 1.0)
        self.assertEqual(self.projection["full_provenance_reachable"], 1.0)
        self.assertEqual(self.projection["full_impact_ids"], self.projection["serialized_impact_ids"])

    def test_taxonomy_keeps_primary_fixed_and_test_responsibilities(self):
        classes = {
            item["impact_id"]: item["classification"]
            for item in self.projection["slot_classification"]
        }
        self.assertEqual(classes["IMPACT-003"], impact.CHALLENGER_REVIEW_PRIMARY)
        self.assertEqual(
            [item for item, value in classes.items() if value == impact.DETERMINISTIC_FIXED_CONTEXT],
            ["IMPACT-001", "IMPACT-002", "IMPACT-004"],
        )
        self.assertEqual(
            [item for item, value in classes.items() if value == impact.EVIDENCE_ONLY],
            ["IMPACT-005", "IMPACT-006", "IMPACT-007"],
        )
        metrics = self.projection["metrics"]
        self.assertEqual(metrics["challenger_impacts_total"], 7)
        self.assertEqual(metrics["challenger_primary_impacts"], 1)
        self.assertEqual(metrics["challenger_fixed_context_units"], 3)
        self.assertEqual(metrics["challenger_evidence_support_units"], 3)
        self.assertEqual(metrics["challenger_review_semantic_coverage"], 1.0)

    def test_full_compiled_map_and_source_provenance_are_retained(self):
        self.assertEqual(self.packet["full_compiled_impact_map"], self.impact_map)
        self.assertEqual(
            self.projection["full_provenance"]["source_impact_map"],
            self.impact_map,
        )
        self.assertEqual(
            set(self.projection["provenance_map"]["impacts"]),
            {item["impact_id"] for item in self.impact_map["impacts"]},
        )
        self.assertEqual(
            self.projection["source_frame_hash"],
            self.impact_map["impact_decision_frame_hash"],
        )
        self.assertEqual(
            self.projection["source_choice_hash"],
            self.impact_map["impact_decision_choice_hash"],
        )
        for item in self.impact_map["impacts"]:
            for field in (
                "requirement_ids", "obligation_ids", "decision_capabilities",
                "frame_provenance", "choice_provenance", "dnt", "prohibitions",
            ):
                self.assertIn(field, item)

    def test_four_atomic_obligations_and_coverage_remain_visible(self):
        full = self.projection["obligation_coverage"]
        model = self.projection["model_payload"]["obligation_coverage"]
        self.assertEqual(len(full), 4)
        self.assertEqual(len(model), 4)
        self.assertEqual(
            {item["obligation_type"] for item in full},
            {"BEHAVIOR_CHANGE", "PRESERVATION"},
        )
        self.assertEqual({item["coverage_state"] for item in model}, {"COVERED"})
        self.assertEqual(
            {item["obligation_id"] for item in full},
            {item["obligation_id"] for item in model},
        )
        self.assertEqual(
            {item["meaning"] for item in full},
            {item["meaning"] for item in model},
        )
        self.assertEqual(self.projection["coverage_status"], self.impact_map["impact_decision_frame_coverage"]["coverage_status"])
        self.assertEqual(self.projection["choice_coverage_status"], self.impact_map["impact_decision_choice_coverage"]["coverage_status"])
        behavior = next(item for item in model if item["obligation_type"] == "BEHAVIOR_CHANGE")
        self.assertEqual(behavior["candidate_slot_ids"], ["SLOT-003"])
        self.assertIn("MUST_CHANGE", behavior["candidate_decision_kinds"])
        self.assertIn("IMPLEMENTATION_CHANGE", behavior["covered_by"][0]["decision_capabilities"])

    def test_primary_change_contains_review_relevant_evidence_without_conclusion(self):
        primary = next(
            item for item in self.projection["model_payload"]["candidate_impact_map"]["impacts"]
            if item["classification"] == impact.CHALLENGER_REVIEW_PRIMARY
        )
        self.assertEqual(primary["surface_id"], "SURF-003")
        self.assertEqual(primary["path"], "src/status_view.js")
        self.assertEqual(primary["chosen_decision"], "MUST_CHANGE")
        self.assertIn("IMPLEMENTATION_CHANGE", primary["decision_capabilities"])
        self.assertIn("REQ-PAUSE-INDICATOR", primary["requirement_ids"])
        self.assertIn("OBL-REQ-PAUSE-INDICATOR-BEHAVIOR-CHANGE-01", primary["obligation_ids"])
        self.assertIn("REPO-005", primary["repository_evidence_ids"])
        self.assertEqual(primary["current_owner"]["path"], "src/status_view.js")
        self.assertIn("preservation", primary)
        self.assertIn("verification", primary)
        evidence = next(
            item for item in self.projection["model_payload"]["repository_evidence"]
            if item["evidence_id"] == "REPO-005"
        )
        self.assertIn("USER_FACING_PAUSE_INDICATOR", evidence["structured_relations"])
        serialized = impact._compact_json(self.projection["model_payload"])
        for conclusion in (
            "MINIMALITY_PASS", "ARCHITECTURE_PASS", "VERIFICATION_SUFFICIENT",
            "NO_REQUIREMENT_GAP", "requirement_gap=false",
        ):
            self.assertNotIn(conclusion, serialized)

    def test_fixed_context_dnt_and_ownership_safety_are_visible(self):
        fixed = [
            item for item in self.projection["model_payload"]["candidate_impact_map"]["impacts"]
            if item["classification"] == impact.DETERMINISTIC_FIXED_CONTEXT
        ]
        self.assertIn("src/pause_controller.js", [item["path"] for item in fixed])
        self.assertFalse(any("IMPLEMENTATION_CHANGE" in item.get("decision_capabilities", []) for item in fixed))
        constraints = self.projection["model_payload"]["fixed_constraints"]
        self.assertTrue(any("Do not modify src/pause_controller.js." == item["text"] for item in constraints))
        payload = impact._compact_json(self.projection["model_payload"])
        for forbidden in ("NEW_OWNER", "OWNER_MIGRATION", "AUTHORITY_CHANGE"):
            self.assertNotIn(forbidden, payload)

    def test_test_impacts_remain_explicit_verification_support(self):
        impacts = self.projection["model_payload"]["candidate_impact_map"]["impacts"]
        test_impacts = [item for item in impacts if item.get("review_support") == "TEST_EVIDENCE"]
        self.assertEqual({item["impact_id"] for item in test_impacts}, {"IMPACT-005", "IMPACT-006", "IMPACT-007"})
        self.assertFalse(any(item.get("classification") == impact.CHALLENGER_REVIEW_PRIMARY for item in test_impacts))
        self.assertEqual(
            set(self.projection["model_payload"]["verification_support"]["evidence_ids"]),
            {"REPO-006", "REPO-007", "REPO-008"},
        )

    def test_model_payload_uses_relative_paths_and_no_full_provenance(self):
        payload = self.projection["model_payload"]
        serialized = impact._compact_json(payload)
        self.assertNotIn("file_sha256", serialized)
        self.assertNotIn("full_provenance", serialized)
        paths = []

        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.endswith("path") or key == "path":
                        paths.append(item)
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)

        collect(payload)
        self.assertTrue(paths)
        self.assertTrue(all(
            isinstance(path, str)
            and not path.startswith(("/", "\\"))
            and not (len(path) > 1 and path[1] == ":")
            for path in paths if path
        ))

    def test_legacy_inputs_keep_the_pre_v24_4_packet_path(self):
        requirements, evidence, brain, registry, seeds, legacy_frame = (
            current_surface_fixture.CurrentSurfacePreservationBindingTests._legacy_behavior_fixture()
        )
        packet = impact.build_challenger_packet(
            legacy_frame,
            requirements,
            evidence,
            task_brain=brain,
            surface_registry=registry,
            render=mini._impact_challenger_prompt,
            base_render=mini._impact_challenger_prompt,
        )
        self.assertNotIn("challenger_review_projection", packet)
        self.assertNotIn("packet_budget_audit", packet)
        self.assertFalse(impact._challenger_review_projection_enabled(legacy_frame))

    def test_gap_authority_minimality_dnt_and_stale_semantics_are_not_hidden(self):
        gap_map = copy.deepcopy(self.impact_map)
        gap_map["impacts"][2]["disposition"] = "INSPECT_ONLY"
        gap_map["impacts"][2]["necessity_status"] = "INSPECT_ONLY"
        gap_projection = impact.build_challenger_review_projection(
            gap_map, self.requirements, self.evidence, self.registry, self.brain, self.verified_context,
        )
        behavior = next(
            item for item in gap_projection["model_payload"]["obligation_coverage"]
            if item["obligation_type"] == "BEHAVIOR_CHANGE"
        )
        self.assertEqual(behavior["coverage_state"], "COVERED")
        gap_challenges = impact.deterministic_challenges(
            gap_map, self.requirements, self.evidence, surface_registry=self.registry,
        )
        self.assertTrue(any(item["challenge_type"] == "REQUIREMENT_GAP" for item in gap_challenges))

        authority_map = copy.deepcopy(self.impact_map)
        authority_map["impacts"][2]["current_owner"] = {
            "surface_id": "SURF-002",
            "path": "src/pause_controller.js",
            "symbol": "PauseController",
        }
        authority_projection = impact.build_challenger_review_projection(
            authority_map, self.requirements, self.evidence, self.registry, self.brain, self.verified_context,
        )
        authority_primary = next(
            item for item in authority_projection["model_payload"]["candidate_impact_map"]["impacts"]
            if item["classification"] == impact.CHALLENGER_REVIEW_PRIMARY
        )
        self.assertEqual(authority_primary["current_owner"]["path"], "src/pause_controller.js")
        self.assertTrue(any(item["text"] == "Do not modify src/pause_controller.js." for item in authority_projection["model_payload"]["fixed_constraints"]))

        minimality_map = copy.deepcopy(self.impact_map)
        extra = copy.deepcopy(minimality_map["impacts"][2])
        extra["impact_id"] = "IMPACT-008"
        extra["decision_slot_id"] = "SLOT-008"
        minimality_map["impacts"].append(extra)
        minimality_projection = impact.build_challenger_review_projection(
            minimality_map, self.requirements, self.evidence, self.registry, self.brain, self.verified_context,
        )
        primary_ids = [
            item["impact_id"]
            for item in minimality_projection["model_payload"]["candidate_impact_map"]["impacts"]
            if item["classification"] == impact.CHALLENGER_REVIEW_PRIMARY
        ]
        self.assertEqual(primary_ids, ["IMPACT-003", "IMPACT-008"])

        dnt_map = copy.deepcopy(self.impact_map)
        dnt_map["impacts"][2]["path"] = "src/pause_controller.js"
        dnt_projection = impact.build_challenger_review_projection(
            dnt_map, self.requirements, self.evidence, self.registry, self.brain, self.verified_context,
        )
        dnt_primary = next(
            item for item in dnt_projection["model_payload"]["candidate_impact_map"]["impacts"]
            if item["classification"] == impact.CHALLENGER_REVIEW_PRIMARY
        )
        self.assertEqual(dnt_primary["path"], "src/pause_controller.js")
        self.assertTrue(any("Do not modify src/pause_controller.js." == item["text"] for item in dnt_projection["model_payload"]["fixed_constraints"]))

        stale_context = copy.deepcopy(self.verified_context)
        stale_context["stale_evidence_warnings"] = [{
            "record_id": "STALE-REPO-005",
            "fact_hash": "f" * 64,
            "stale_reason": "The current render evidence requires reverification.",
            "evidence_ids": ["REPO-005"],
        }]
        stale_projection = impact.build_challenger_review_projection(
            self.impact_map,
            self.requirements,
            self.evidence,
            self.registry,
            self.brain,
            stale_context,
        )
        warnings = stale_projection["model_payload"]["stale_evidence_warnings"]
        self.assertEqual(warnings[0]["record_id"], "STALE-REPO-005")
        self.assertIn("STALE_WARNING", impact._compact_json(warnings))
        self.assertNotIn("fact_hash", impact._compact_json(warnings))

    def test_valid_and_blocking_challenger_outputs_reach_existing_reconciliation(self):
        candidate = {
            "challenges": [{
                "challenge_id": "MODEL-VALID",
                "challenge_type": "UNSUPPORTED_NECESSITY",
                "impact_ids": ["IMPACT-003"],
                "surface_ids": ["SURF-003"],
                "requirement_ids": ["REQ-PAUSE-INDICATOR"],
                "repository_evidence_ids": ["REPO-005"],
                "claim": "Question whether renderStatus is necessary for the user-facing pause indicator.",
                "proposed_resolution": "Retain only the smallest required rendering change.",
                "blocking": True,
            }],
        }
        normalized = impact.normalize_challenges(candidate, source="MODEL")
        validation = impact.validate_challenges(
            normalized,
            self.impact_map,
            self.requirements,
            self.evidence,
            surface_registry=self.registry,
        )
        self.assertEqual(len(validation["validated"]), 1)
        self.assertEqual(len(validation["applicable"]), 1)
        self.assertTrue(validation["validated"][0]["blocking"])
        merged = impact.merge_challenges(validation["validated"], [])
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["challenge_type"], "UNSUPPORTED_NECESSITY")
        self.assertEqual(self.packet["model_calls"], 0)


if __name__ == "__main__":
    unittest.main()
