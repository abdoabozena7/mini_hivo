import copy
import json
import unittest

import mini
from hivo import impact_planning as impact
from tests import test_obligation_aware_plan_closure as v183_fixture


class ObligationConservingReconciliationTests(unittest.TestCase):
    """Focused v18.4 regressions around typed challenge/obligation closure."""

    def setUp(self):
        self.fixture = v183_fixture.ObligationAwarePlanClosureTests(
            "test_obligation_ledger_is_deterministic_typed_and_provenance_aware"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.requirements = self.fixture.requirements
        self.evidence = self.fixture.evidence
        self.registry = self.fixture.registry
        self.seeds = self.fixture.seeds
        self.goal = self.fixture.goal

    def partial_map(self, count=3):
        raw = self.fixture.weak_decisions()
        raw["impacts"] = copy.deepcopy(raw["impacts"][:count])
        value = impact.hydrate_impact_map(
            raw, self.registry, self.requirements, self.evidence,
            impact_seeds=self.seeds,
        )
        self.assertTrue(value.get("hydration_valid"), value.get("hydration_errors"))
        return value

    def impact_for_surface(self, value, surface_id):
        return next(item for item in value.get("impacts", [])
                    if item.get("surface_id") == surface_id)

    @staticmethod
    def challenge(challenge_id, challenge_type, impact_ids=(), requirement_ids=(),
                  evidence_ids=(), surface_ids=(), blocking=True):
        return {
            "challenge_id": challenge_id,
            "challenge_type": challenge_type,
            "impact_ids": list(impact_ids),
            "requirement_ids": list(requirement_ids),
            "repository_evidence_ids": list(evidence_ids),
            "surface_ids": list(surface_ids),
            "claim": f"{challenge_type} is relevant to the cited responsibility.",
            "proposed_resolution": "Apply the validated deterministic correction.",
            "blocking": blocking,
        }

    def validate_one(self, value, challenge):
        result = impact.validate_challenges(
            [challenge], value, self.requirements, self.evidence, self.registry,
        )
        self.assertFalse(result.get("rejected"), result.get("rejected"))
        self.assertEqual(len(result.get("validated", [])), 1)
        return result

    def test_valid_references_are_not_semantic_applicability(self):
        cases = (
            ("IMPACT-001", "SURF-001", "INTERFACE_REUSE", "INTERFACE_REUSE", "REQ-002", "REPO-005"),
            ("IMPACT-002", "SURF-002", "PRESERVATION_ONLY", "PRESERVATION_ONLY", "REQ-003", "REPO-003"),
            ("IMPACT-V", "SURF-001", "VERIFY_ONLY", "CROSS_CUTTING_VERIFICATION", "REQ-002", "REPO-005"),
            ("IMPACT-T", "SURF-006", "TEST_CHANGE", "TEST_CHANGE", "REQ-004", "REPO-009"),
        )
        for impact_id, surface_id, disposition, kind, requirement_id, evidence_id in cases:
            value = impact.normalize_impact_map({"impacts": [{
                "impact_id": impact_id, "surface_id": surface_id,
                "disposition": disposition, "necessity_status": disposition,
                "impact_kind": kind, "requirement_ids": [requirement_id],
                "repository_evidence_ids": [evidence_id],
                "candidate_change": "Reuse or verify the current responsibility.",
            }]}, authoritative=True)
            challenge = self.challenge(
                f"CH-{impact_id}", "UNSUPPORTED_NECESSITY", [impact_id],
                [requirement_id], [evidence_id], [surface_id], blocking=False,
            )
            result = impact.evaluate_challenge_applicability(
                challenge, value, self.requirements, self.evidence, self.registry,
            )
            with self.subTest(disposition=disposition):
                self.assertEqual(result["reference_status"], "VALID_REFERENCES")
                self.assertEqual(result["status"], "VALIDATED_NON_APPLICABLE")
                self.assertIn("non-mutating", result["reason"])

        stale = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-STALE", "surface_id": "SURF-001",
            "disposition": "INTERFACE_REUSE", "necessity_status": "MUST_CHANGE",
            "impact_kind": "INTERFACE_REUSE", "requirement_ids": ["REQ-002"],
            "repository_evidence_ids": ["REPO-005"],
            "candidate_change": "Reuse the current input owner.",
        }]}, authoritative=True)
        result = impact.evaluate_challenge_applicability(
            self.challenge("CH-STALE", "UNSUPPORTED_NECESSITY", ["IMPACT-STALE"],
                           ["REQ-002"], ["REPO-005"], ["SURF-001"]),
            stale, self.requirements, self.evidence, self.registry,
        )
        self.assertEqual(result["status"], "VALIDATED_NON_APPLICABLE")

    def test_unsupported_necessity_remains_applicable_to_unsupported_mutation(self):
        requirements = [{
            "requirement_id": "REQ-X", "text": "Add unrelated export behavior.",
            "status": "active",
        }]
        value = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-X", "disposition": "MUST_CHANGE",
            "necessity_status": "MUST_CHANGE", "impact_kind": "BEHAVIOR_CHANGE",
            "requirement_ids": [], "repository_evidence_ids": [],
            "candidate_change": "Mutate an unrelated surface.",
        }]})
        challenge = self.challenge("CH-X", "UNSUPPORTED_NECESSITY", ["IMPACT-X"])
        result = impact.validate_challenges(challenge and [challenge], value, requirements, [], None)
        self.assertEqual(len(result["applicable"]), 1)
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, result["validated"], requirements, [], task_goal="Add unrelated export behavior.",
        )
        target = reconciled["impacts"][0]
        self.assertEqual(target["disposition"], "INSUFFICIENT_EVIDENCE")
        self.assertEqual(result["validated"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        self.assertEqual(reconciled["challenge_effects_applied"], 1)
        self.assertFalse(unresolved)
        self.assertEqual(resolved[0]["lifecycle_state"], "RESOLVED")

    def test_wrong_owner_and_duplicate_owner_are_type_applicable_and_corrective(self):
        wrong = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-W", "surface_id": "SURF-002",
            "disposition": "MUST_CHANGE", "necessity_status": "MUST_CHANGE",
            "impact_kind": "BEHAVIOR_CHANGE", "component": "OtherState",
            "existing_owner": "OtherState", "requirement_ids": ["REQ-001"],
            "repository_evidence_ids": ["REPO-003"],
            "candidate_change": "Use OtherState for pause state.",
        }]}, authoritative=True)
        wrong_challenge = self.challenge(
            "CH-W", "WRONG_OWNER", ["IMPACT-W"], ["REQ-001"], ["REPO-003"], ["SURF-002"],
        )
        wrong_result = self.validate_one(wrong, wrong_challenge)
        self.assertEqual(wrong_result["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        corrected, _, _ = impact.reconcile_impact_map(
            wrong, wrong_result["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        self.assertEqual(corrected["impacts"][0]["existing_owner"], "GameState")

        duplicate = copy.deepcopy(wrong)
        duplicate["impacts"][0].update({
            "impact_id": "IMPACT-D",
            "component": "GameState",
            "existing_owner": "GameState",
            "candidate_change": "Use a second paused state owner.",
        })
        duplicate_challenge = self.challenge(
            "CH-D", "DUPLICATE_OWNERSHIP_RISK", ["IMPACT-D"],
            ["REQ-001"], ["REPO-003"], ["SURF-002"],
        )
        duplicate_result = self.validate_one(duplicate, duplicate_challenge)
        self.assertEqual(
            duplicate_result["applicable"][0]["applicability_status"],
            "VALIDATED_APPLICABLE",
        )
        corrected, duplicate_resolved, duplicate_unresolved = impact.reconcile_impact_map(
            duplicate, duplicate_result["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        self.assertEqual(corrected["challenge_effects_applied"], 1)
        self.assertEqual(corrected["impacts"][0]["existing_owner"], "GameState")
        self.assertFalse(duplicate_unresolved)
        self.assertEqual(duplicate_resolved[0]["lifecycle_state"], "RESOLVED")

    def test_interface_reuse_missed_and_test_gap_use_verified_evidence(self):
        interface_value = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-I", "surface_id": "SURF-001",
            "disposition": "MUST_CHANGE", "necessity_status": "MUST_CHANGE",
            "impact_kind": "BEHAVIOR_CHANGE", "requirement_ids": ["REQ-001"],
            "repository_evidence_ids": ["REPO-005"],
            "candidate_change": "Add Escape handling to the current owner.",
        }]}, authoritative=True)
        interface_challenge = self.challenge(
            "CH-I", "INTERFACE_REUSE_MISSED", ["IMPACT-I"], ["REQ-001"],
            ["REPO-007"], ["SURF-001"],
        )
        interface_result = self.validate_one(interface_value, interface_challenge)
        self.assertEqual(interface_result["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        corrected, _, _ = impact.reconcile_impact_map(
            interface_value, interface_result["validated"], self.requirements,
            self.evidence, self.registry, self.seeds, task_goal=self.goal,
        )
        self.assertIn("SURF-004", corrected["impacts"][0]["interface_surface_ids"])

        test_value = self.partial_map()
        test_challenge = self.challenge(
            "CH-T", "TEST_GAP", [], ["REQ-004"], ["REPO-009"], [],
        )
        test_result = self.validate_one(test_value, test_challenge)
        self.assertEqual(test_result["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        corrected, _, _ = impact.reconcile_impact_map(
            test_value, test_result["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        self.assertTrue(any(
            item.get("surface_id") == "SURF-006" and item.get("disposition") == "TEST_CHANGE"
            for item in corrected["impacts"]
        ))

    def test_preservation_unrelated_missing_impact_and_dependency_rules_are_typed(self):
        preservation_value = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-P", "surface_id": "SURF-001",
            "disposition": "MUST_CHANGE", "necessity_status": "MUST_CHANGE",
            "impact_kind": "BEHAVIOR_CHANGE", "requirement_ids": ["REQ-003"],
            "repository_evidence_ids": ["REPO-005"],
            "candidate_change": "Add Escape handling to InputManager.",
        }]}, authoritative=True)
        preservation = self.validate_one(
            preservation_value,
            self.challenge("CH-P", "PRESERVATION_RISK", ["IMPACT-P"], ["REQ-003"],
                           ["REPO-005"], ["SURF-001"]),
        )
        self.assertEqual(preservation["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")

        unrelated_requirements = [{
            "requirement_id": "REQ-U", "text": "Add CSV export.",
            "status": "active",
        }]
        unrelated_value = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-U", "surface_id": "SURF-001",
            "disposition": "MUST_CHANGE", "necessity_status": "MUST_CHANGE",
            "impact_kind": "BEHAVIOR_CHANGE", "requirement_ids": ["REQ-U"],
            "repository_evidence_ids": ["REPO-005"],
            "candidate_change": "Add an unrelated database migration.",
        }]}, authoritative=True)
        unrelated = impact.validate_challenges(
            [self.challenge("CH-U", "UNRELATED_CHANGE", ["IMPACT-U"], ["REQ-U"],
                             ["REPO-005"], ["SURF-001"])],
            unrelated_value, unrelated_requirements, self.evidence, self.registry,
        )
        self.assertFalse(unrelated["rejected"], unrelated["rejected"])
        self.assertEqual(unrelated["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        corrected, corrected_resolved, corrected_unresolved = impact.reconcile_impact_map(
            unrelated_value, unrelated["validated"], unrelated_requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        self.assertEqual(corrected["impacts"][0]["disposition"], "INSUFFICIENT_EVIDENCE")
        self.assertFalse(corrected_unresolved)
        self.assertEqual(corrected_resolved[0]["lifecycle_state"], "RESOLVED")

        missing = self.challenge("CH-M", "MISSING_IMPACT", [], ["REQ-001"], ["REPO-005"])
        missing_result = impact.validate_challenges(
            [missing], {"impacts": []}, self.requirements, self.evidence, None,
        )
        self.assertEqual(missing_result["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")

        dependency_evidence = copy.deepcopy(self.evidence)
        dependency_evidence.append({
            "evidence_id": "REPO-DEP", "category": "CURRENT_DEPENDENCY",
            "path": "src/input.js", "symbol": "GameState.togglePause",
            "fact": "InputManager integrates with GameState.togglePause.",
        })
        dependency_value = impact.normalize_impact_map({"impacts": [{
            "impact_id": "IMPACT-DEP", "disposition": "MUST_CHANGE",
            "necessity_status": "MUST_CHANGE", "impact_kind": "INTEGRATION_CHANGE",
            "requirement_ids": ["REQ-002"], "repository_evidence_ids": ["REPO-DEP"],
            "candidate_change": "Connect the current dependency.",
        }]})
        dependency = self.challenge(
            "CH-DEP", "DEPENDENCY_GAP", ["IMPACT-DEP"], ["REQ-002"], ["REPO-DEP"],
        )
        dependency_result = impact.validate_challenges(
            [dependency], dependency_value, self.requirements, dependency_evidence, None,
        )
        self.assertEqual(
            dependency_result["applicable"][0]["applicability_status"],
            "VALIDATED_APPLICABLE",
        )

    def test_requirement_gap_is_obligation_aware_and_behavior_closes_from_canonical_owner(self):
        value = self.partial_map()
        challenge = self.challenge(
            "CH-R", "REQUIREMENT_GAP", [], ["REQ-001"], ["REPO-005"], [],
        )
        result = self.validate_one(value, challenge)
        self.assertEqual(result["applicable"][0]["applicability_status"], "VALIDATED_APPLICABLE")
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, result["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        input_owner = self.impact_for_surface(reconciled, "SURF-001")
        self.assertEqual(input_owner["disposition"], "MUST_CHANGE")
        self.assertEqual(
            reconciled["semantic_obligation_coverage"]["behavior_obligations_uncovered"], 0,
        )
        self.assertEqual(resolved[0]["lifecycle_state"], "SUPERSEDED")
        self.assertFalse(unresolved)

    def test_controlled_non_applicable_challenge_cannot_remove_unique_input_anchor(self):
        value = self.partial_map()
        challenge = self.challenge(
            "CH-001", "UNSUPPORTED_NECESSITY", ["IMPACT-001"],
            ["REQ-002"], ["REPO-005"], ["SURF-001"], blocking=False,
        )
        validation = self.validate_one(value, challenge)
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, validation["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        input_owner = self.impact_for_surface(reconciled, "SURF-001")
        self.assertEqual(input_owner["disposition"], "MUST_CHANGE")
        self.assertEqual(input_owner["path"], "src/input.js")
        self.assertEqual(validation["validated"][0]["effect_status"], "NOT_APPLICABLE")
        self.assertEqual(reconciled["challenge_effects_suppressed"], 1)
        self.assertEqual(reconciled["impact_challenges_non_applicable"], 1)
        self.assertEqual(resolved[0]["lifecycle_state"], "SUPERSEDED")
        self.assertFalse(unresolved)

    def test_omitted_storage_test_and_interface_are_restored_from_seed_identity(self):
        value = self.partial_map()
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, [], self.requirements, self.evidence, self.registry, self.seeds,
            task_goal=self.goal,
        )
        by_surface = {item["surface_id"]: item for item in reconciled["impacts"]}
        for surface_id in ("SURF-005", "SURF-006", "SURF-004"):
            self.assertIn(surface_id, by_surface)
            seed = next(item for item in self.seeds if item["surface_id"] == surface_id)
            item = by_surface[surface_id]
            self.assertEqual(item["impact_id"], impact.normalize_impact_id(seed["impact_id"]))
            self.assertEqual(item["path"], seed["canonical_path"])
            self.assertEqual(item["repository_evidence_ids"], seed["canonical_evidence_ids"])
            self.assertEqual(item["provenance"], impact.DERIVED_PLAN_DECISION)
        self.assertEqual(by_surface["SURF-005"]["disposition"], "PRESERVATION_ONLY")
        self.assertEqual(by_surface["SURF-006"]["disposition"], "TEST_CHANGE")
        self.assertEqual(by_surface["SURF-004"]["disposition"], "INTERFACE_REUSE")
        storage_seed = next(item for item in self.seeds if item["surface_id"] == "SURF-005")
        self.assertIn(storage_seed["verified_symbol"], by_surface["SURF-005"]["symbols"])
        self.assertFalse(unresolved)
        self.assertTrue(resolved == [] or all(item.get("lifecycle_state") != "OPEN" for item in resolved))
        closure_types = {
            item.get("closure_metadata", {}).get("closure_type")
            for item in by_surface.values()
            if isinstance(item.get("closure_metadata"), dict)
        }
        self.assertIn("OBLIGATION_CLOSURE_PRESERVATION", closure_types)
        self.assertIn("OBLIGATION_CLOSURE_TEST", closure_types)
        self.assertIn("OBLIGATION_CLOSURE_REUSE", closure_types)

        plan = impact.build_minimal_change_plan(
            reconciled, self.requirements, self.evidence, resolved, unresolved,
            surface_registry=self.registry, task_goal=self.goal,
        )
        self.assertIn("SURF-005", plan["do_not_touch_surface_ids"])
        self.assertTrue(any(
            item.get("surface_id") == "SURF-006" for item in plan["tests_to_update_or_add"]
        ))
        self.assertIn("SURF-004", plan["interface_surface_ids"])

    def test_structured_reuse_prohibition_and_local_preservation_close_separately(self):
        value = self.partial_map()
        reconciled, _, _ = impact.reconcile_impact_map(
            value, [], self.requirements, self.evidence, self.registry, self.seeds,
            task_goal=self.goal,
        )
        input_owner = self.impact_for_surface(reconciled, "SURF-001")
        encoded_local = json.dumps(input_owner["local_preservation_constraints"]).casefold()
        self.assertIn("wasd", encoded_local)
        self.assertIn("arrow", encoded_local)
        self.assertIn("input ownership", encoded_local)
        prohibitions = json.dumps(reconciled["prohibition_constraints"]).casefold()
        self.assertIn("sole pause-state owner", prohibitions)
        self.assertIn("duplicate input state ownership", prohibitions)
        self.assertEqual(reconciled["reuse_obligations_closed"], 1)
        self.assertEqual(reconciled["preservation_obligations_closed"], 1)
        self.assertEqual(reconciled["test_obligations_closed"], 1)
        self.assertEqual(reconciled["prohibition_obligations_closed"], 1)

        plan = impact.build_minimal_change_plan(
            reconciled, self.requirements, self.evidence, [], [],
            surface_registry=self.registry, task_goal=self.goal,
        )
        plan_text = json.dumps(plan).casefold()
        self.assertIn("sole pause-state owner", plan_text)
        self.assertIn("duplicate input state ownership", plan_text)
        self.assertNotIn("surf-001", {item.casefold() for item in plan["do_not_touch_surface_ids"]})
        self.assertIn("surf-005", {item.casefold() for item in plan["do_not_touch_surface_ids"]})

    def test_final_challenge_lifecycle_recomputes_after_closure(self):
        value = self.partial_map()
        challenges = [
            self.challenge("CH-003", "TEST_GAP", [], ["REQ-004"], ["REPO-009"]),
            self.challenge("CH-004", "REQUIREMENT_GAP", [], ["REQ-004"], ["REPO-009"]),
        ]
        validation = impact.validate_challenges(
            challenges, value, self.requirements, self.evidence, self.registry,
        )
        self.assertFalse(validation["rejected"], validation["rejected"])
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, validation["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        states = {item["challenge_id"]: item["lifecycle_state"] for item in resolved}
        self.assertEqual(states["CH-003"], "RESOLVED")
        self.assertEqual(states["CH-004"], "SUPERSEDED")
        self.assertEqual(reconciled["challenges_remaining_open"], 0)
        self.assertFalse(unresolved)

        missing_requirements = [{
            "requirement_id": "REQ-MISSING",
            "text": "Add an unrepresented quantum export protocol.",
            "status": "active",
        }]
        missing = self.challenge("CH-OPEN", "REQUIREMENT_GAP", [], ["REQ-MISSING"])
        missing_validation = impact.validate_challenges(
            [missing], {"impacts": []}, missing_requirements, [], None,
        )
        self.assertFalse(missing_validation["rejected"], missing_validation["rejected"])
        _, _, still_open = impact.reconcile_impact_map(
            {"impacts": []}, missing_validation["validated"],
            missing_requirements, [], task_goal="missing",
        )
        self.assertEqual(still_open[0]["lifecycle_state"], "OPEN")

    def test_final_plan_semantics_are_recomputed_and_approval_stays_read_only(self):
        _, _, _, _, plan, gate = self.fixture.closed_fixture()
        self.assertTrue(gate["valid"], gate["errors"])
        stale = copy.deepcopy(plan)
        node = next(item for item in stale["approved_change_nodes"]
                    if item.get("target_surface_ids") == ["SURF-001"])
        node.update({
            "mutation_required": False, "verification_only": True,
            "target_surface_ids": [], "candidate_targets": [],
            "inspect_surface_ids": ["SURF-001"], "inspect_targets": ["src/input.js"],
            "disposition": "INTERFACE_REUSE", "impact_kind": "INTERFACE_REUSE",
        })
        stale["mutation_surface_ids"] = ["SURF-006"]
        stale = impact.finalize_plan_identity(stale)
        stale_gate = impact.validate_change_plan(
            stale, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=self.goal,
        )
        self.assertFalse(stale_gate["valid"])
        self.assertTrue(any("REQ-001: semantic obligations" in error for error in stale_gate["errors"]))

        approval = mini.request_plan_approval(
            plan, interactive=False, terminal_available=False,
        )
        self.assertEqual(approval["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(approval["status"], "plan_approval_required")
        self.assertEqual(mini.RUN["worker_missions_executed"], 0)
        self.assertEqual(mini.RUN.get("mutations_applied", 0), 0)

    def test_source_contract_root_goal_is_exact_and_hash_authoritative(self):
        source_goal = "Do X."
        contract = {
            "source_contract": {"root_goal": source_goal},
            "goal": source_goal + "\n",
            "original_goal": "wrong goal",
        }
        self.assertEqual(mini._authoritative_stage3_task_goal(contract), source_goal)
        value = self.partial_map()
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            value, [], self.requirements, self.evidence, self.registry, self.seeds,
            task_goal=mini._authoritative_stage3_task_goal(contract),
        )
        plan = impact.build_minimal_change_plan(
            reconciled, self.requirements, self.evidence, resolved, unresolved,
            surface_registry=self.registry, task_goal=source_goal,
        )
        self.assertEqual(plan["task_goal"], source_goal)
        self.assertNotEqual(plan["task_goal"], contract["goal"])
        self.assertEqual(plan["plan_hash"], impact.plan_content_hash(plan))
        wrong = impact.validate_change_plan(
            plan, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=contract["goal"],
        )
        self.assertFalse(wrong["valid"])
        self.assertTrue(any("authoritative root goal" in error for error in wrong["errors"]))


if __name__ == "__main__":
    unittest.main()
