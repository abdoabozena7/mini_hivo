import copy
import unittest

import mini
from hivo import impact_planning as impact
from tests.test_v24_3_impact_decision_frame import ImpactDecisionFrameTests


class ObligationAnchoredImpactCoverageTests(ImpactDecisionFrameTests):
    """Provider-free V24.4 obligation-to-decision conservation regressions."""

    @staticmethod
    def _frame_fixture(requirements, evidence, brain):
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(
            brain, requirements, evidence, registry=registry,
        )
        core = impact.build_canonical_mandatory_planning_core({
            "project_id": brain.get("project_id"),
            "task_id": brain.get("task_id"),
            "task_goal": brain.get("task_goal", ""),
            "requirements": requirements,
            "surfaces": registry.get("surfaces", []),
            "impact_seeds": seeds,
            "preservation_constraints": brain.get("preservation_constraints", []),
            "dnt": brain.get("dnt", []),
            "prohibitions": brain.get("prohibitions", []),
        })
        frame = impact.build_impact_decision_frame(
            brain, requirements, evidence,
            surface_registry=registry, impact_seeds=seeds,
            mandatory_core=core,
        )
        return registry, seeds, core, frame

    @staticmethod
    def _choices(frame, decision="INSPECT_ONLY"):
        return {"decisions": [{
            "slot_id": slot.get("slot_id"),
            "decision": decision,
            "chosen_target": slot.get("surface_id"),
            "reason_code": "TEST_ONLY_REGRESSION",
            "bounded_rationale": "Use the selected decision for this deterministic regression.",
        } for slot in frame.get("decision_slots", [])]}

    def _compile_parent_fixture(self):
        return impact.compile_impact_map_from_choices(
            self.frame, self.choices, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
            task_goal=self.requirements[0]["text"],
            provider_generation_identity={"model": "gemma4:e4b", "generation": 1},
        )

    def _test_only_frame_fixture(self):
        requirements = [{
            "requirement_id": "REQ-V244-BAD-FRAME",
            "text": "Add a user-facing pause indicator.",
            "status": "active",
            "provenance": impact.USER_STATED,
        }]
        evidence = [{
            "evidence_id": "REPO-V244-TEST-1",
            "category": "CURRENT_TEST",
            "path": "tests/pause.test.js",
            "symbol": "pause flow",
            "fact": "The current pause indicator boundary is covered by focused tests.",
            "file_sha256": "a" * 64,
        }]
        brain = {
            "project_id": "v244-test-project",
            "task_id": "v244-bad-frame",
            "task_goal": {"text": requirements[0]["text"]},
            "relevant_tests": [{
                "text": "The current pause indicator boundary is covered by focused tests.",
                "path": "tests/pause.test.js",
                "symbol": "pause flow",
                "category": "CURRENT_TEST",
                "evidence_ids": ["REPO-V244-TEST-1"],
            }],
        }
        return (requirements, evidence, brain) + self._frame_fixture(
            requirements, evidence, brain,
        )

    def _compound_test_fixture(self):
        requirements = [{
            "requirement_id": "REQ-V244-MIXED",
            "text": "Add export behavior and tests.",
            "status": "active",
            "provenance": impact.USER_STATED,
        }]
        evidence = [
            {
                "evidence_id": "REPO-V244-EXPORT",
                "category": "CURRENT_OWNER",
                "path": "src/export.js",
                "symbol": "ExportController",
                "fact": "ExportController owns export behavior.",
                "file_sha256": "b" * 64,
            },
            {
                "evidence_id": "REPO-V244-EXPORT-TEST",
                "category": "CURRENT_TEST",
                "path": "tests/export.test.js",
                "symbol": "export flow",
                "fact": "Focused export tests cover the current boundary.",
                "file_sha256": "c" * 64,
            },
        ]
        brain = {
            "project_id": "v244-mixed-project",
            "task_id": "v244-mixed",
            "task_goal": {"text": requirements[0]["text"]},
            "current_owners": [{
                "text": "ExportController owns export behavior.",
                "path": "src/export.js",
                "symbol": "ExportController",
                "category": "CURRENT_OWNER",
                "evidence_ids": ["REPO-V244-EXPORT"],
            }],
            "relevant_tests": [{
                "text": "Focused export tests cover the current boundary.",
                "path": "tests/export.test.js",
                "symbol": "export flow",
                "category": "CURRENT_TEST",
                "evidence_ids": ["REPO-V244-EXPORT-TEST"],
            }],
        }
        return (requirements, evidence, brain) + self._frame_fixture(
            requirements, evidence, brain,
        )

    def _preservation_only_fixture(self):
        requirements = [{
            "requirement_id": "REQ-V244-PRESERVE",
            "text": "Preserve the current pause-state owner.",
            "status": "active",
            "provenance": impact.USER_STATED,
        }]
        evidence = [{
            "evidence_id": "REPO-V244-PRESERVE",
            "category": "CURRENT_STATE_OWNER",
            "path": "src/pause_controller.js",
            "symbol": "PauseController",
            "fact": "PauseController owns pause state.",
            "file_sha256": "d" * 64,
        }]
        brain = {
            "project_id": "v244-preserve-project",
            "task_id": "v244-preserve",
            "task_goal": {"text": requirements[0]["text"]},
            "current_owners": [{
                "text": "PauseController owns pause state.",
                "path": "src/pause_controller.js",
                "symbol": "PauseController",
                "category": "CURRENT_STATE_OWNER",
                "evidence_ids": ["REPO-V244-PRESERVE"],
            }],
            "current_state_ownership": [{
                "text": "PauseController owns pause state.",
                "path": "src/pause_controller.js",
                "symbol": "PauseController",
                "category": "CURRENT_STATE_OWNER",
                "evidence_ids": ["REPO-V244-PRESERVE"],
            }],
            "preservation_constraints": [{
                "text": requirements[0]["text"],
                "requirement_ids": [requirements[0]["requirement_id"]],
            }],
        }
        return (requirements, evidence, brain) + self._frame_fixture(
            requirements, evidence, brain,
        )

    def test_01_source_ledger_loads_structured_active_requirement(self):
        ledger = impact.build_requirement_obligation_ledger(self.requirements)
        record = ledger["requirements"][0]
        self.assertEqual(record["requirement_id"], self.REQUIREMENT_ID)
        self.assertEqual(record["source_provenance"], impact.USER_STATED)
        self.assertEqual(record["classification_provenance"], impact.DERIVED_PLAN_DECISION)

    def test_02_behavior_change_is_an_atomic_obligation(self):
        ledger = impact.build_requirement_obligation_ledger([{
            "requirement_id": "REQ-V244-BEHAVIOR",
            "text": "Add an additional user-facing pause indicator.",
            "status": "active",
        }])
        atoms = ledger["requirements"][0]["obligations"]
        self.assertEqual(len(atoms), 1)
        self.assertEqual(atoms[0]["obligation_type"], "BEHAVIOR_CHANGE")
        self.assertIn("pause indicator", atoms[0]["meaning"])

    def test_03_compound_pause_requirement_preserves_four_distinct_obligations(self):
        atoms = impact.build_requirement_obligation_ledger(self.requirements)["requirements"][0]["obligations"]
        self.assertEqual([item["obligation_type"] for item in atoms], [
            "BEHAVIOR_CHANGE", "PRESERVATION", "PRESERVATION", "PRESERVATION",
        ])
        meanings = " ".join(item["meaning"] for item in atoms)
        for phrase in ("pause indicator", "PauseController", "Escape", "movement"):
            self.assertIn(phrase, meanings)
        self.assertEqual(len({item["obligation_id"] for item in atoms}), 4)

    def test_03b_test_clause_is_not_promoted_to_behavior_change(self):
        ledger = impact.build_requirement_obligation_ledger([{
            "requirement_id": "REQ-V244-COMPOUND-TEST",
            "text": "Add export behavior and update relevant tests.",
            "status": "active",
        }])
        self.assertEqual(
            [item["obligation_type"] for item in ledger["requirements"][0]["obligations"]],
            ["BEHAVIOR_CHANGE", "TEST"],
        )

    def test_04_decision_kinds_have_deterministic_capabilities(self):
        taxonomy = impact.impact_decision_capability_taxonomy()
        self.assertEqual(taxonomy["MUST_CHANGE"], ["IMPLEMENTATION_CHANGE"])
        self.assertEqual(taxonomy["TEST_CHANGE"], ["TEST_CHANGE"])
        self.assertEqual(taxonomy["INSPECT_ONLY"], ["INSPECTION_ONLY"])
        self.assertEqual(taxonomy["INTERFACE_REUSE"], ["REUSE_ONLY"])
        self.assertEqual(taxonomy["PRESERVATION_ONLY"], ["PRESERVATION_ONLY"])

    def test_05_inspect_only_has_zero_behavior_coverage(self):
        coverage = impact.build_impact_decision_choice_coverage(
            self.frame, self._choices(self.frame, "INSPECT_ONLY"),
        )
        behavior = next(
            item for item in coverage["obligations"]
            if item["obligation_type"] == "BEHAVIOR_CHANGE"
        )
        self.assertFalse(behavior["coverage_ready"])
        self.assertIn(behavior["obligation_id"], coverage["uncovered_obligations"])

    def test_06_test_change_alone_has_zero_behavior_coverage(self):
        coverage = impact.build_impact_decision_choice_coverage(
            self.frame, self._choices(self.frame, "TEST_CHANGE"),
        )
        behavior = next(
            item for item in coverage["obligations"]
            if item["obligation_type"] == "BEHAVIOR_CHANGE"
        )
        self.assertFalse(behavior["coverage_ready"])
        self.assertEqual(behavior["covered_by"], [])

    def test_07_authorized_must_change_covers_behavior(self):
        owner = next(
            slot for slot in self.frame["decision_slots"]
            if "MUST_CHANGE" in slot["allowed_decisions"]
            and slot["obligations_satisfied_by_decision"].get("MUST_CHANGE")
        )
        behavior_id = owner["obligations_satisfied_by_decision"]["MUST_CHANGE"][0]
        self.assertIn("IMPLEMENTATION_CHANGE", owner["decision_capabilities"]["MUST_CHANGE"])
        self.assertIn(behavior_id, owner["candidate_obligation_ids"])

    def test_08_prohibited_surface_cannot_cover_behavior(self):
        requirements, evidence, brain = self._test_only_frame_fixture()[:3]
        owner = impact.build_canonical_surface_registry(brain, evidence)["surfaces"][0]
        brain["prohibitions"] = [{
            "text": "Do not modify the verified pause owner.",
            "surface_ids": [owner["surface_id"]],
        }]
        _, _, _, frame = self._frame_fixture(requirements, evidence, brain)
        self.assertEqual(
            impact.validate_impact_decision_frame(frame)["status"],
            impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP,
        )
        self.assertFalse(any(
            item.get("obligations_satisfied_by_decision", {}).get("MUST_CHANGE")
            for item in frame["decision_slots"]
        ))

    def test_09_dnt_surface_is_not_an_implementation_candidate(self):
        requirements, evidence, brain = self._test_only_frame_fixture()[:3]
        owner = impact.build_canonical_surface_registry(brain, evidence)["surfaces"][0]
        brain["dnt"] = [{
            "text": "Do not modify the verified pause owner.",
            "surface_ids": [owner["surface_id"]],
        }]
        _, _, _, frame = self._frame_fixture(requirements, evidence, brain)
        coverage = frame["impact_decision_frame_coverage"]
        self.assertEqual(coverage["coverage_status"], impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP)
        self.assertEqual(coverage["uncovered_obligations"], [
            frame["requirement_obligation_ledger"]["requirements"][0]["obligations"][0]["obligation_id"]
        ])

    def test_10_behavior_frame_without_capable_decision_fails(self):
        frame = self._test_only_frame_fixture()[-1]
        result = impact.validate_impact_decision_frame(frame)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP)
        self.assertTrue(result["uncovered_obligations"])

    def test_11_frame_capability_gap_has_zero_planner_calls(self):
        requirements, evidence, brain, registry, seeds, core, _ = self._test_only_frame_fixture()
        mini.reset_run("v24.4-bad-frame")
        called = []

        def provider_must_not_run(*args):
            called.append(args)
            raise AssertionError("ImpactPlanner provider must not run on a frame gap")

        with self.assertRaises(mini.ImpactPlanningError) as raised:
            mini._create_impact_map_from_decision_frame(
                brain, {"goal": requirements[0]["text"]}, evidence, requirements,
                registry, seeds, {"canonical_mandatory_planning_core": core},
                provider_must_not_run, None,
            )
        self.assertEqual(raised.exception.status, impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP)
        self.assertEqual(called, [])
        self.assertEqual(mini.RUN["impact_planner_calls"], 0)
        self.assertEqual(mini.RUN["impact_decision_frame_validation"]["model_calls"], 0)

    def test_12_capable_frame_is_coverage_ready(self):
        frame_result = impact.validate_impact_decision_frame(self.frame)
        self.assertTrue(frame_result["valid"], frame_result)
        self.assertEqual(frame_result["coverage_status"], impact.IMPACT_FRAME_COVERAGE_READY)
        self.assertEqual(frame_result["uncovered_obligations"], [])

    def test_13_all_inspect_choices_fail_post_choice_coverage(self):
        choices = self._choices(self.frame, "INSPECT_ONLY")
        result = impact.validate_impact_decision_choices(choices, self.frame)
        self.assertFalse(result["valid"])
        self.assertTrue(result["status"].startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP))
        self.assertIn(impact.BEHAVIOR_CHANGE_UNCOVERED, result["errors"])
        self.assertEqual(result["model_calls"], 0)
        self.assertTrue(result["uncovered_obligations"])

    def test_14_all_test_choices_fail_behavior_coverage(self):
        choices = self._choices(self.frame, "TEST_CHANGE")
        result = impact.validate_impact_decision_choice_coverage(self.frame, choices["decisions"])
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], impact.IMPACT_CHOICE_REQUIREMENT_GAP)
        self.assertTrue(any(
            item["obligation_type"] == "BEHAVIOR_CHANGE" and not item["coverage_ready"]
            for item in result["coverage"]["obligations"]
        ))

    def test_15_actionable_choice_covers_behavior(self):
        result = impact.validate_impact_decision_choices(self.choices, self.frame)
        self.assertTrue(result["valid"], result)
        behavior = next(
            item for item in result["choice_coverage"]["obligations"]
            if item["obligation_type"] == "BEHAVIOR_CHANGE"
        )
        self.assertTrue(behavior["coverage_ready"])
        self.assertEqual(result["uncovered_obligations"], [])

    def test_16_mixed_implementation_and_test_choices_retain_verification(self):
        requirements, evidence, brain, registry, seeds, core, frame = self._compound_test_fixture()
        self.assertTrue(impact.validate_impact_decision_frame(frame)["valid"])
        choices = impact.deterministic_impact_decision_choices(frame)
        choice_check = impact.validate_impact_decision_choices(choices, frame)
        self.assertTrue(choice_check["valid"], choice_check)
        compiled = impact.compile_impact_map_from_choices(
            frame, choices, requirements, evidence,
            surface_registry=registry, impact_seeds=seeds,
            task_goal=requirements[0]["text"],
        )
        self.assertTrue(compiled["valid"], compiled)
        self.assertTrue(any(
            item.get("chosen_decision") == "MUST_CHANGE"
            and "BEHAVIOR_CHANGE" in {
                assignment.get("obligation_type")
                for assignment in item.get("obligation_assignments", [])
            }
            for item in compiled["impact_map"]["impacts"]
        ))
        self.assertTrue(any(
            item.get("disposition") == "TEST_CHANGE"
            and item.get("verification_contracts")
            for item in compiled["impact_map"]["impacts"]
        ))

    def test_17_preservation_can_be_inherited_without_mutation(self):
        requirements, evidence, brain, registry, seeds, core, frame = self._preservation_only_fixture()
        self.assertTrue(impact.validate_impact_decision_frame(frame)["valid"])
        coverage = frame["impact_decision_frame_coverage"]
        preservation = next(item for item in coverage["obligations"] if item["obligation_type"] == "PRESERVATION")
        self.assertTrue(preservation["inherited_satisfaction"])
        compiled = impact.compile_impact_map_from_choices(
            frame, impact.deterministic_impact_decision_choices(frame), requirements, evidence,
            surface_registry=registry, impact_seeds=seeds,
        )
        self.assertTrue(compiled["valid"], compiled)
        self.assertFalse(any(
            item.get("disposition") == "MUST_CHANGE"
            for item in compiled["impact_map"]["impacts"]
        ))

    def test_18_requirement_ids_propagate_into_compiled_impacts(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        self.assertTrue(all(item.get("requirement_ids") for item in compiled["impact_map"]["impacts"]))
        self.assertIn(self.REQUIREMENT_ID, {
            req_id for item in compiled["impact_map"]["impacts"]
            for req_id in item.get("requirement_ids", [])
        })

    def test_19_obligation_ids_propagate_into_compiled_impacts(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        assignments = compiled["impact_map"]["obligation_assignments"]
        self.assertTrue(assignments)
        ledger_ids = {
            atom["obligation_id"]
            for record in compiled["impact_map"]["requirement_obligation_ledger"]["requirements"]
            for atom in record.get("obligations", [])
        }
        self.assertTrue(ledger_ids.issuperset(
            item["obligation_id"] for item in assignments
        ))
        self.assertTrue(any(item.get("obligation_ids") for item in compiled["impact_map"]["impacts"]))

    def test_20_active_changed_requirement_receives_an_impact_assignment(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        self.assertIn(self.REQUIREMENT_ID, compiled["assigned_requirement_ids"])
        self.assertIn(self.REQUIREMENT_ID, compiled["impact_map"]["obligation_assignment_requirement_ids"])

    def test_21_zero_assigned_behavior_requirement_is_rejected(self):
        choices = self._choices(self.frame, "INSPECT_ONLY")
        compiled = impact.compile_impact_map_from_choices(
            self.frame, choices, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
        )
        self.assertFalse(compiled["valid"])
        self.assertTrue(compiled["status"].startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP))
        self.assertIsNone(compiled["impact_map"])
        self.assertEqual(compiled["model_calls"], 0)

    def test_22_compiled_map_passes_existing_semantic_validator(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        self.assertTrue(compiled["semantic_validation"]["valid"])
        self.assertTrue(impact.validate_impact_map(
            compiled["impact_map"], self.requirements, self.evidence,
            surface_registry=self.registry,
        )["valid"])

    def test_23_complete_compiled_map_has_no_requirement_gap_challenge(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        challenges = impact.deterministic_challenges(
            compiled["impact_map"], self.requirements, self.evidence, self.registry,
        )
        self.assertNotIn("REQUIREMENT_GAP", {
            item.get("challenge_type") for item in challenges
        })

    def test_24_unrelated_challenger_objection_remains_applicable(self):
        unrelated_evidence = self.evidence + [{
            "evidence_id": "REPO-V244-UNRELATED",
            "category": "CURRENT_BEHAVIOR",
            "path": "src/theme.js",
            "symbol": "ThemeRenderer",
            "fact": "ThemeRenderer renders unrelated theme colors.",
            "file_sha256": "e" * 64,
        }]
        impact_map = {
            "impacts": [{
                "impact_id": "IMPACT-UNRELATED",
                "disposition": "MUST_CHANGE",
                "necessity_status": "MUST_CHANGE",
                "impact_kind": "BEHAVIOR_CHANGE",
                "requirement_ids": [self.REQUIREMENT_ID],
                "repository_evidence_ids": ["REPO-V244-UNRELATED"],
                "component": "ThemeRenderer",
                "path": "src/theme.js",
                "action": "Edit unrelated theme colors.",
            }],
        }
        challenge = impact.normalize_challenges({"challenges": [{
            "challenge_id": "CH-UNRELATED-V244",
            "challenge_type": "UNRELATED_CHANGE",
            "impact_ids": ["IMPACT-UNRELATED"],
            "requirement_ids": [self.REQUIREMENT_ID],
            "repository_evidence_ids": ["REPO-V244-UNRELATED"],
            "claim": "The theme color mutation is unrelated to the pause indicator requirement.",
            "proposed_resolution": "Exclude the unrelated theme mutation.",
            "blocking": True,
        }]}, source="MODEL")
        result = impact.validate_challenges(
            challenge, impact_map, self.requirements, unrelated_evidence,
        )
        self.assertTrue(result["validated"])
        self.assertEqual(result["validated"][0]["challenge_type"], "UNRELATED_CHANGE")
        self.assertTrue(result["applicable"])

    def test_25_indicator_frame_does_not_expose_ownership_migration(self):
        self.assertFalse(any(
            "AUTHORITY_CHANGE" in slot["allowed_decisions"]
            or "NEW_OWNER" in slot["allowed_decisions"]
            for slot in self.frame["decision_slots"]
        ))

    def test_26_current_pause_interface_reuse_remains_available(self):
        interface_slots = [
            slot for slot in self.frame["decision_slots"]
            if slot["surface_kind"] == "INTERFACE"
        ]
        self.assertTrue(interface_slots)
        self.assertTrue(any(
            "INTERFACE_REUSE" in slot["allowed_decisions"]
            and slot["required_interfaces"]
            for slot in interface_slots
        ))

    def test_27_duplicate_slot_behavior_is_unchanged(self):
        duplicate = copy.deepcopy(self.choices)
        duplicate["decisions"] = [duplicate["decisions"][0], duplicate["decisions"][0]]
        result = impact.validate_impact_decision_choices(duplicate, self.frame)
        self.assertIn(impact.DUPLICATE_IMPACT_DECISION_SLOT, result["errors"])

    def test_28_missing_slot_behavior_is_unchanged(self):
        missing = {"decisions": self.choices["decisions"][:-1]}
        result = impact.validate_impact_decision_choices(missing, self.frame)
        self.assertIn(impact.MISSING_IMPACT_DECISION_SLOT, result["errors"])

    def test_29_unknown_slot_behavior_is_unchanged(self):
        unknown = copy.deepcopy(self.choices)
        unknown["decisions"][-1]["slot_id"] = "SLOT-999"
        result = impact.validate_impact_decision_choices(unknown, self.frame)
        self.assertIn(impact.UNKNOWN_IMPACT_DECISION_SLOT, result["errors"])

    def test_30_legacy_full_map_shape_is_still_rejected(self):
        legacy = {
            "impacts": [{
                "impact_id": "IMPACT-001",
                "disposition": "INTERFACE_REUSE",
                "requirement_ids": [self.REQUIREMENT_ID],
                "action": "Reuse the current interface.",
            }],
        }
        result = impact.validate_impact_decision_choices(legacy, self.frame)
        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], impact.IMPACT_DECISION_OUTPUT_MALFORMED)

    def test_31_coverage_hash_is_deterministic_and_capability_sensitive(self):
        frame_coverage = impact.build_impact_decision_frame_coverage(self.frame)
        self.assertEqual(
            frame_coverage["coverage_hash"],
            impact.impact_decision_coverage_hash(frame_coverage),
        )
        same = impact.build_impact_decision_frame_coverage(copy.deepcopy(self.frame))
        self.assertEqual(frame_coverage["coverage_hash"], same["coverage_hash"])
        first = impact.build_impact_decision_choice_coverage(self.frame, self.choices["decisions"])
        weak = self._choices(self.frame, "INSPECT_ONLY")
        second = impact.build_impact_decision_choice_coverage(self.frame, weak["decisions"])
        self.assertNotEqual(first["coverage_hash"], second["coverage_hash"])

    def test_32_all_coverage_operations_report_zero_model_calls(self):
        frame_check = impact.validate_impact_decision_frame(self.frame)
        choice_check = impact.validate_impact_decision_choices(self.choices, self.frame)
        frame_coverage = impact.validate_impact_decision_frame_coverage(self.frame)
        choice_coverage = impact.validate_impact_decision_choice_coverage(
            self.frame, self.choices["decisions"],
        )
        compiled = self._compile_parent_fixture()
        for result in (frame_check, choice_check, frame_coverage, choice_coverage, compiled):
            self.assertEqual(result.get("model_calls"), 0, result)

    def test_33_architecture_self_test_contains_cases_a_through_d(self):
        result = impact.impact_decision_frame_self_test()
        self.assertTrue(result["passed"], result)
        for name in (
            "case_a_live_bad_frame", "case_b_weak_bad_choice",
            "case_c_valid_choice_assignment", "case_d_preservation_only",
        ):
            self.assertTrue(result["checks"].get(name), result["checks"])

    def test_34_indicator_surface_is_derived_and_not_hardcoded(self):
        encoded = str(self.frame)
        self.assertNotIn("src/status_view.js", encoded)
        surface_ids = {slot["surface_id"] for slot in self.frame["decision_slots"]}
        self.assertTrue(surface_ids)
        self.assertTrue(all(slot["surface_path"] for slot in self.frame["decision_slots"]))

    def test_35_planning_context_and_frame_coverage_are_distinct_statuses(self):
        bad_frame = self._test_only_frame_fixture()[-1]
        check = impact.validate_impact_decision_frame(bad_frame)
        self.assertEqual(check["coverage_status"], impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP)
        self.assertNotEqual(check["coverage_status"], "PLANNING_CONTEXT_READY")
        self.assertTrue(self.frame["frame_coverage_ready"])

    def test_36_compiler_rejects_choice_coverage_before_hydration(self):
        weak = self._choices(self.frame, "INSPECT_ONLY")
        compiled = impact.compile_impact_map_from_choices(
            self.frame, weak, self.requirements, self.evidence,
            surface_registry=self.registry, impact_seeds=self.seeds,
        )
        self.assertFalse(compiled["valid"])
        self.assertIsNone(compiled["impact_map"])
        self.assertFalse(compiled.get("hydration"))

    def test_37_compiled_assignment_provenance_is_complete(self):
        compiled = self._compile_parent_fixture()
        self.assertTrue(compiled["valid"], compiled)
        for assignment in compiled["impact_map"]["obligation_assignments"]:
            for field in (
                "requirement_id", "obligation_id", "obligation_type", "surface_id",
                "slot_id", "chosen_decision", "decision_capability",
                "coverage_contribution", "frame_provenance", "choice_provenance",
            ):
                self.assertIn(field, assignment)
            self.assertEqual(
                assignment["frame_provenance"]["impact_decision_frame_hash"],
                self.frame["frame_hash"],
            )

    def test_38_explicit_multi_obligation_bindings_stay_on_distinct_surfaces(self):
        requirements = [{
            "requirement_id": "REQ-V244-EXPLICIT-MULTI",
            "text": "Add export behavior and import behavior.",
            "obligations": [
                {
                    "obligation_id": "OBL-V244-EXPORT",
                    "obligation_type": "BEHAVIOR_CHANGE",
                    "meaning": "Add export behavior.",
                    "candidate_surface_ids": ["SURF-001"],
                },
                {
                    "obligation_id": "OBL-V244-IMPORT",
                    "obligation_type": "BEHAVIOR_CHANGE",
                    "meaning": "Add import behavior.",
                    "candidate_surface_ids": ["SURF-002"],
                },
            ],
            "status": "active",
        }]
        evidence = [
            {
                "evidence_id": "REPO-V244-EXPLICIT-EXPORT",
                "category": "CURRENT_OWNER",
                "path": "src/export.js",
                "symbol": "ExportController",
                "fact": "ExportController owns export behavior.",
                "file_sha256": "f" * 64,
            },
            {
                "evidence_id": "REPO-V244-EXPLICIT-IMPORT",
                "category": "CURRENT_OWNER",
                "path": "src/import.js",
                "symbol": "ImportController",
                "fact": "ImportController owns import behavior.",
                "file_sha256": "1" * 64,
            },
        ]
        brain = {
            "project_id": "v244-explicit-project",
            "task_id": "v244-explicit",
            "task_goal": {"text": requirements[0]["text"]},
            "current_owners": [
                {
                    "text": "ExportController owns export behavior.",
                    "path": "src/export.js", "symbol": "ExportController",
                    "category": "CURRENT_OWNER", "evidence_ids": ["REPO-V244-EXPLICIT-EXPORT"],
                },
                {
                    "text": "ImportController owns import behavior.",
                    "path": "src/import.js", "symbol": "ImportController",
                    "category": "CURRENT_OWNER", "evidence_ids": ["REPO-V244-EXPLICIT-IMPORT"],
                },
            ],
        }
        registry = impact.build_canonical_surface_registry(brain, evidence)
        owner_ids = [
            item["surface_id"] for item in registry["surfaces"] if item["kind"] == "OWNER"
        ]
        requirements[0]["obligations"][0]["candidate_surface_ids"] = [owner_ids[0]]
        requirements[0]["obligations"][1]["candidate_surface_ids"] = [owner_ids[1]]
        registry, seeds, core, frame = self._frame_fixture(requirements, evidence, brain)
        self.assertEqual(impact.validate_impact_decision_frame(frame)["status"], "READY")
        locations = {
            item["obligation_id"]: item["candidate_slots"]
            for item in frame["impact_decision_frame_coverage"]["obligations"]
        }
        self.assertEqual(len(locations["OBL-V244-EXPORT"]), 1)
        self.assertEqual(len(locations["OBL-V244-IMPORT"]), 1)
        self.assertNotEqual(
            locations["OBL-V244-EXPORT"], locations["OBL-V244-IMPORT"],
        )

    def test_39_two_unbound_behavior_clauses_fail_closed(self):
        requirements = [{
            "requirement_id": "REQ-V244-UNBOUND-MULTI",
            "text": "Add export behavior and add import behavior.",
            "status": "active",
        }]
        evidence = [
            {
                "evidence_id": "REPO-V244-UNBOUND-EXPORT",
                "category": "CURRENT_OWNER", "path": "src/export.js",
                "symbol": "ExportController", "fact": "ExportController owns export behavior.",
                "file_sha256": "2" * 64,
            },
            {
                "evidence_id": "REPO-V244-UNBOUND-IMPORT",
                "category": "CURRENT_OWNER", "path": "src/import.js",
                "symbol": "ImportController", "fact": "ImportController owns import behavior.",
                "file_sha256": "3" * 64,
            },
        ]
        brain = {
            "project_id": "v244-unbound-project", "task_id": "v244-unbound",
            "task_goal": {"text": requirements[0]["text"]},
            "current_owners": [
                {"text": "ExportController owns export behavior.", "path": "src/export.js", "symbol": "ExportController", "category": "CURRENT_OWNER", "evidence_ids": ["REPO-V244-UNBOUND-EXPORT"]},
                {"text": "ImportController owns import behavior.", "path": "src/import.js", "symbol": "ImportController", "category": "CURRENT_OWNER", "evidence_ids": ["REPO-V244-UNBOUND-IMPORT"]},
            ],
        }
        _, _, _, frame = self._frame_fixture(requirements, evidence, brain)
        coverage = frame["impact_decision_frame_coverage"]
        self.assertEqual(coverage["coverage_status"], impact.IMPACT_FRAME_REQUIREMENT_CAPABILITY_GAP)
        self.assertEqual(len(coverage["uncovered_obligations"]), 2)

    def test_40_frame_schema_declares_capability_and_coverage_fields(self):
        schema = impact.impact_decision_frame_schema()
        self.assertIn("requirement_obligation_ledger", schema["properties"])
        self.assertIn("impact_decision_frame_coverage", schema["properties"])
        slot = schema["properties"]["decision_slots"]["items"]
        for field in (
            "candidate_obligation_ids", "decision_capabilities",
            "obligations_satisfied_by_decision", "surface_capabilities",
        ):
            self.assertIn(field, slot["properties"])
            self.assertIn(field, slot["required"])

    def test_41_negative_change_is_a_constraint_not_a_mutation_request(self):
        record = impact.build_requirement_obligation_ledger([{
            "requirement_id": "REQ-V244-DNT",
            "text": "Do not modify the current owner.",
            "status": "active",
        }])["requirements"][0]
        self.assertNotIn("BEHAVIOR_CHANGE", record["obligation_types"])
        self.assertIn("PROHIBITION", record["obligation_types"])

    def test_42_metrics_add_only_the_compact_v244_fields(self):
        metrics = mini.new_metrics("v24.4")
        fields = {
            "impact_obligations_total", "impact_behavior_change_obligations",
            "impact_frame_covered_obligations", "impact_frame_uncovered_obligations",
            "impact_choice_covered_obligations", "impact_choice_uncovered_obligations",
            "impact_frame_capability_gaps", "impact_choice_requirement_gaps",
            "impact_requirements_assigned",
        }
        self.assertTrue(fields.issubset(metrics))
        self.assertTrue(all(metrics[field] == 0 for field in fields))

    def test_43_frame_and_choice_artifacts_are_structurally_linked(self):
        frame_coverage = self.frame["impact_decision_frame_coverage"]
        choice_coverage = impact.build_impact_decision_choice_coverage(
            self.frame, self.choices["decisions"],
        )
        self.assertEqual(
            choice_coverage["frame_coverage_hash"], frame_coverage["coverage_hash"],
        )
        self.assertEqual(
            choice_coverage["coverage_status"], impact.IMPACT_CHOICE_COVERAGE_READY,
        )

    def test_44_frame_coverage_validator_detects_tampered_artifact(self):
        tampered = copy.deepcopy(self.frame)
        tampered["impact_decision_frame_coverage"]["uncovered_obligations"] = ["FAKE-OBLIGATION"]
        tampered["coverage"] = copy.deepcopy(tampered["impact_decision_frame_coverage"])
        result = impact.validate_impact_decision_frame_coverage(tampered)
        self.assertFalse(result["valid"])
        self.assertIn("FAKE-OBLIGATION", tampered["impact_decision_frame_coverage"]["uncovered_obligations"])
        self.assertTrue(any("stale" in error or "canonical" in error for error in result["errors"]))

    def test_45_weak_choice_is_classified_downstream_before_challenger(self):
        mini.reset_run("v24.4-downstream-weak-choice")
        calls = []

        def weak_choice(prompt, validator, label, schema):
            calls.append((label, schema))
            candidate = self._choices(self.frame, "INSPECT_ONLY")
            structural = validator(candidate)
            self.assertTrue(structural["valid"], structural)
            self.assertIsNone(structural.get("coverage_status"))
            return candidate

        with self.assertRaises(mini.ImpactPlanningError) as raised:
            mini._create_impact_map_from_decision_frame(
                self.brain, {"goal": self.requirements[0]["text"]}, self.evidence,
                self.requirements, self.registry, self.seeds,
                {"canonical_mandatory_planning_core": self.core},
                weak_choice, {},
            )
        self.assertTrue(
            raised.exception.status.startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP),
        )
        self.assertTrue(mini.RUN["impact_decision_choice_validation"]["structural_valid"])
        self.assertFalse(mini.RUN["impact_decision_choice_validation"]["coverage_valid"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(mini.RUN["impact_planner_calls"], 1)
        self.assertEqual(mini.RUN["impact_challenger_calls"], 0)
        self.assertEqual(
            mini.RUN["impact_choice_coverage_failure"],
            impact.DOWNSTREAM_WEAK_IMPACT_CHOICE_COVERAGE_FAILURE,
        )
        self.assertEqual(mini.RUN["impact_choice_requirement_gaps"], 1)

    def test_46_provider_callback_keeps_semantic_coverage_out_of_retry_gate(self):
        structural = impact.validate_impact_decision_choices(
            self._choices(self.frame, "INSPECT_ONLY"), self.frame,
            include_coverage=False,
        )
        semantic = impact.validate_impact_decision_choices(
            self._choices(self.frame, "INSPECT_ONLY"), self.frame,
        )
        self.assertTrue(structural["valid"], structural)
        self.assertIsNone(structural.get("coverage_status"))
        self.assertFalse(semantic["valid"], semantic)
        self.assertTrue(
            semantic["status"].startswith(impact.IMPACT_CHOICE_REQUIREMENT_GAP),
        )


if __name__ == "__main__":
    unittest.main()
