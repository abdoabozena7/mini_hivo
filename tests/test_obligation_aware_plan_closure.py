import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import impact_planning as impact


class ObligationAwarePlanClosureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")
        self.goal = "Add Escape pause support without changing current ownership."
        self.requirements = [
            {"requirement_id": "REQ-001", "text": "Add Escape pause/resume support.", "status": "active"},
            {"requirement_id": "REQ-002", "text": "Reuse current input and pause-state owners; no duplicate owner.", "status": "active"},
            {"requirement_id": "REQ-003", "text": "Preserve WASD/arrow controls and persistent best-score behavior.", "status": "active"},
            {"requirement_id": "REQ-004", "text": "Update or add relevant tests.", "status": "active"},
        ]
        self.evidence = [
            self.fact("REPO-001", "CURRENT_ENTRYPOINT", "index.html", "", "index.html is the current entrypoint"),
            self.fact("REPO-002", "CURRENT_OWNER", "src/game.js", "GameState", "GameState owns pause/game-state behavior"),
            self.fact("REPO-003", "CURRENT_STATE_OWNER", "src/game.js", "GameState", "GameState owns paused state"),
            self.fact("REPO-004", "CURRENT_INTERFACE", "src/game.js", "GameState.togglePause", "GameState.togglePause is the current pause transition interface"),
            self.fact("REPO-005", "CURRENT_OWNER", "src/input.js", "InputManager", "InputManager owns keyboard/input behavior"),
            self.fact("REPO-006", "CURRENT_STATE_OWNER", "src/input.js", "InputManager", "InputManager owns keyboard key state"),
            self.fact("REPO-007", "CURRENT_INTERFACE", "src/input.js", "InputManager.isPressed", "InputManager.isPressed is the current keyboard query interface"),
            self.fact("REPO-008", "CURRENT_PERSISTENCE", "src/storage.js", "BEST_SCORE_KEY", "BEST_SCORE_KEY owns persistent best-score behavior"),
            self.fact("REPO-009", "CURRENT_TEST", "tests/input.test.js", "InputManager", "tests/input.test.js protects input behavior"),
        ]
        self.brain = {
            "task_goal": {"text": self.goal, "evidence_ids": []},
            "repository_evidence_ids": [item["evidence_id"] for item in self.evidence],
            "current_owners": [
                self.record("InputManager", "src/input.js", "REPO-005", "CURRENT_OWNER"),
                self.record("GameState", "src/game.js", "REPO-002", "CURRENT_OWNER"),
            ],
            "current_interfaces": [
                self.record("GameState.togglePause", "src/game.js", "REPO-004", "CURRENT_INTERFACE"),
                self.record("InputManager.isPressed", "src/input.js", "REPO-007", "CURRENT_INTERFACE"),
            ],
            "current_state_ownership": [
                self.record("InputManager", "src/input.js", "REPO-006", "CURRENT_STATE_OWNER"),
                self.record("GameState", "src/game.js", "REPO-003", "CURRENT_STATE_OWNER"),
            ],
            "relevant_tests": [
                self.record("InputManager", "tests/input.test.js", "REPO-009", "CURRENT_TEST"),
            ],
            "preservation_constraints": [{
                "text": self.requirements[2]["text"], "requirement_ids": ["REQ-003"],
            }],
        }
        self.registry = impact.build_canonical_surface_registry(self.brain, self.evidence)
        self.seeds = impact.build_impact_seeds(
            self.brain, self.requirements, self.evidence, self.registry,
        )

    def tearDown(self):
        mini.rollback_transaction()
        mini.ACTIVE_TOOL_CONTRACT = None
        self.temp.cleanup()

    @staticmethod
    def fact(evidence_id, category, path, symbol, fact):
        return {
            "evidence_id": evidence_id, "category": category, "path": path,
            "symbol": symbol, "fact": fact, "line_start": 1, "line_end": 2,
            "file_sha256": evidence_id.lower().replace("repo-", "").rjust(64, "0"),
        }

    @staticmethod
    def record(symbol, path, evidence_id, category):
        return {
            "symbol": symbol, "path": path, "evidence_ids": [evidence_id],
            "category": category, "text": symbol,
            "provenance": impact.REPOSITORY_EVIDENCE,
        }

    def weak_decisions(self):
        return {"impacts": [
            {"impact_id": "IMPACT-001", "disposition": "INTERFACE_REUSE",
             "requirement_ids": ["REQ-002", "REQ-003"], "interfaces_to_reuse": ["SURF-004"],
             "action": "Reuse the current input owner."},
            {"impact_id": "IMPACT-002", "disposition": "PRESERVATION_ONLY",
             "requirement_ids": ["REQ-001", "REQ-002", "REQ-003"],
             "action": "Preserve the current game-state owner."},
            {"impact_id": "IMPACT-003", "disposition": "INTERFACE_REUSE",
             "requirement_ids": ["REQ-001", "REQ-002"], "interfaces_to_reuse": ["SURF-003"],
             "action": "Reuse the current pause transition."},
            {"impact_id": "IMPACT-004", "disposition": "INTERFACE_REUSE",
             "requirement_ids": ["REQ-002"], "interfaces_to_reuse": ["SURF-004"],
             "action": "Reuse the current keyboard query."},
            {"impact_id": "IMPACT-005", "disposition": "PRESERVATION_ONLY",
             "requirement_ids": ["REQ-002"], "action": "Preserve current storage behavior."},
        ]}

    def hydrated_weak_map(self):
        value = impact.hydrate_impact_map(
            self.weak_decisions(), self.registry, self.requirements, self.evidence,
            impact_seeds=self.seeds,
        )
        self.assertTrue(value["hydration_valid"], value["hydration_errors"])
        return value

    def closed_fixture(self):
        hydrated = self.hydrated_weak_map()
        challenges = impact.deterministic_challenges(
            hydrated, self.requirements, self.evidence, self.registry,
        )
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, self.registry,
        )
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        plan = impact.build_minimal_change_plan(
            reconciled, self.requirements, self.evidence, resolved, unresolved,
            surface_registry=self.registry, task_goal=self.goal,
        )
        gate = impact.validate_change_plan(
            plan, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=self.goal,
        )
        return hydrated, reconciled, resolved, unresolved, plan, gate

    def test_obligation_ledger_is_deterministic_typed_and_provenance_aware(self):
        first = impact.build_requirement_obligation_ledger(self.requirements)
        second = impact.build_requirement_obligation_ledger(copy.deepcopy(self.requirements))
        self.assertEqual(first, second)
        by_id = {item["requirement_id"]: item for item in first["requirements"]}
        self.assertEqual(by_id["REQ-001"]["obligation_types"], ["BEHAVIOR_CHANGE"])
        self.assertEqual(by_id["REQ-002"]["obligation_types"], ["ARCHITECTURE_REUSE", "PROHIBITION"])
        self.assertEqual(by_id["REQ-003"]["obligation_types"], ["PRESERVATION"])
        self.assertEqual(by_id["REQ-004"]["obligation_types"], ["TEST"])
        self.assertTrue(all(item["classification_provenance"] == impact.DERIVED_PLAN_DECISION for item in by_id.values()))
        compound = impact.build_requirement_obligation_ledger([{
            "requirement_id": "REQ-X",
            "text": "Reuse the existing state service instead of creating another owner.",
            "status": "active",
        }])["requirements"][0]
        self.assertEqual(compound["obligation_types"], ["ARCHITECTURE_REUSE", "PROHIBITION"])

    def test_companion_relationship_enriches_input_seed_without_changing_authority(self):
        input_seed = next(item for item in self.seeds if item["surface_id"] == "SURF-001")
        self.assertEqual(input_seed["impact_id"], "IMPACT-001")
        self.assertEqual(input_seed["canonical_path"], "src/input.js")
        self.assertTrue({"REQ-001", "REQ-002", "REQ-003"}.issubset(input_seed["requirement_ids"]))
        self.assertEqual(input_seed["requirement_relationships"][0]["relationship"], "BEHAVIOR_REUSE_COMPANION")
        packet = impact.build_canonical_planning_packet(
            self.brain, self.requirements, self.evidence, surface_registry=self.registry,
        )
        packet_seed = next(item for item in packet["packet"]["impact_seeds"] if item["surface_id"] == "SURF-001")
        self.assertEqual(packet_seed["requirement_relationships"][0]["relationship"], "COMPANION")

    def test_companion_relationship_is_generic_for_auth_service(self):
        requirements = [
            {"requirement_id": "REQ-A", "text": "Add refresh-token rotation.", "status": "active"},
            {"requirement_id": "REQ-B", "text": "Reuse the current authentication service instead of creating another token owner.", "status": "active"},
        ]
        evidence = [self.fact(
            "REPO-A", "CURRENT_OWNER", "src/auth.js", "AuthService",
            "AuthService owns authentication requests.",
        )]
        brain = {"task_goal": {"text": "rotate tokens"}, "repository_evidence_ids": ["REPO-A"]}
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(brain, requirements, evidence, registry)
        owner = next(item for item in seeds if item["surface_kind"] == "OWNER")
        self.assertEqual(set(owner["requirement_ids"]), {"REQ-A", "REQ-B"})
        self.assertEqual(owner["requirement_relationships"][0]["companion_requirement_id"], "REQ-B")

    def test_id_presence_and_interface_reuse_do_not_cover_behavior(self):
        semantic = impact.evaluate_requirement_obligations(
            self.hydrated_weak_map(), self.requirements, self.evidence, self.registry,
        )
        req1 = next(item for item in semantic["requirements"] if item["requirement_id"] == "REQ-001")
        self.assertEqual(req1["state"], "UNCOVERED")
        self.assertEqual(req1["obligations"][0]["obligation_type"], "BEHAVIOR_CHANGE")

    def test_behavior_coverage_matrix_rejects_preservation_reuse_and_test_only(self):
        requirement = [{"requirement_id": "REQ-A", "text": "Add runtime export behavior.", "status": "active"}]
        base = {
            "requirement_ids": ["REQ-A"], "repository_evidence_ids": ["REPO-005"],
            "surface_kind": "OWNER", "existing_owner": "InputManager",
        }
        variants = [
            {**base, "impact_id": "IMP-P", "disposition": "PRESERVATION_ONLY",
             "impact_kind": "PRESERVATION_ONLY", "preserve": ["existing behavior"]},
            {**base, "impact_id": "IMP-R", "disposition": "INTERFACE_REUSE",
             "impact_kind": "INTERFACE_REUSE", "existing_interfaces_to_reuse": ["current interface"]},
            {**base, "impact_id": "IMP-T", "disposition": "TEST_CHANGE",
             "impact_kind": "TEST_CHANGE"},
        ]
        for item in variants:
            semantic = impact.evaluate_requirement_obligations(
                {"impacts": [item]}, requirement, self.evidence,
            )
            self.assertEqual(semantic["requirements_uncovered"], 1)
        valid = {**base, "impact_id": "IMP-M", "disposition": "MUST_CHANGE",
                 "necessity_status": "MUST_CHANGE", "impact_kind": "BEHAVIOR_CHANGE"}
        self.assertEqual(impact.evaluate_requirement_obligations(
            {"impacts": [valid]}, requirement, self.evidence,
        )["requirements_covered"], 1)

    def test_controlled_closure_promotes_only_input_owner_and_reuses_both_interfaces(self):
        _, reconciled, _, unresolved, plan, gate = self.closed_fixture()
        self.assertFalse(unresolved)
        self.assertTrue(gate["valid"], gate["errors"])
        promoted = next(item for item in reconciled["impacts"] if item["surface_id"] == "SURF-001")
        self.assertEqual(promoted["disposition"], "MUST_CHANGE")
        self.assertEqual(promoted["impact_id"], "IMPACT-001")
        self.assertEqual(set(promoted["interfaces_to_reuse"]), {"SURF-003", "SURF-004"})
        self.assertEqual(reconciled["deterministic_behavior_anchor_promotions"], 1)
        self.assertEqual(plan["mutation_surface_ids"], ["SURF-001", "SURF-006"])
        self.assertEqual(promoted["path"], "src/input.js")
        self.assertEqual(promoted["repository_evidence_ids"], ["REPO-005", "REPO-006"])
        self.assertNotIn("InputManager.paused", json.dumps(reconciled))

    def test_test_gap_repair_supersedes_stale_requirement_gap(self):
        hydrated = self.hydrated_weak_map()
        challenges = impact.normalize_challenges({"challenges": [
            {"challenge_id": "CH-003", "challenge_type": "TEST_GAP", "impact_ids": [],
             "requirement_ids": ["REQ-004"], "repository_evidence_ids": ["REPO-009"],
             "claim": "Tests are missing.", "proposed_resolution": "Add the current test surface.", "blocking": True},
            {"challenge_id": "CH-004", "challenge_type": "REQUIREMENT_GAP", "impact_ids": [],
             "requirement_ids": ["REQ-004"], "repository_evidence_ids": ["REPO-009"],
             "claim": "The test requirement is uncovered.", "proposed_resolution": "Cover the test requirement.", "blocking": True},
        ]}, source="DETERMINISTIC")
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, self.registry,
        )
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], self.requirements, self.evidence,
            self.registry, self.seeds, task_goal=self.goal,
        )
        states = {item["challenge_id"]: item["lifecycle_state"] for item in resolved}
        self.assertEqual(states["CH-003"], "RESOLVED")
        self.assertEqual(states["CH-004"], "SUPERSEDED")
        self.assertFalse(unresolved)
        self.assertTrue(any(item["surface_id"] == "SURF-006" and item["disposition"] == "TEST_CHANGE" for item in reconciled["impacts"]))

    def test_structured_local_and_global_preservation_are_disjoint(self):
        _, reconciled, _, _, plan, _ = self.closed_fixture()
        input_node = next(item for item in plan["approved_change_nodes"] if item["target_surface_ids"] == ["SURF-001"])
        encoded = json.dumps(input_node["local_preservation_constraints"]).casefold()
        self.assertIn("wasd", encoded)
        self.assertIn("arrow", encoded)
        self.assertIn("input ownership", encoded)
        storage = next(item for item in reconciled["impacts"] if item["surface_id"] == "SURF-005")
        self.assertIn("REQ-003", storage["requirement_ids"])
        self.assertIn("SURF-005", plan["do_not_touch_surface_ids"])
        self.assertNotIn("SURF-001", plan["do_not_touch_surface_ids"])
        self.assertNotIn("src/storage.js", input_node["candidate_targets"])
        self.assertIn("SURF-002", plan["do_not_touch_surface_ids"])
        self.assertIn("GameState", json.dumps(plan))

    def test_final_plan_has_exact_goal_hash_semantic_coverage_and_integration_contract(self):
        _, _, resolved, unresolved, plan, gate = self.closed_fixture()
        self.assertEqual(plan["task_goal"], self.goal)
        self.assertEqual(plan["plan_hash"], impact.plan_content_hash(plan))
        self.assertEqual(gate["semantic_requirements_covered"], 4)
        self.assertEqual(gate["requirements_unassigned"], 0)
        self.assertFalse(unresolved)
        self.assertTrue(resolved)
        integration = " ".join(plan["integration_verification"]).casefold()
        for phrase in ("escape", "both directions", "wasd", "arrow", "best-score", "ownership", "test"):
            self.assertIn(phrase, integration)
        self.assertFalse(any("src/game.js" in node["candidate_targets"] for node in plan["approved_change_nodes"]))
        self.assertFalse(any("src/storage.js" in node["candidate_targets"] for node in plan["approved_change_nodes"]))
        summary = mini.format_plan_approval_summary(plan)
        self.assertIn("Escape", summary)

    def test_empty_or_mismatched_task_goal_and_hash_tampering_fail_gate(self):
        _, _, _, _, plan, _ = self.closed_fixture()
        for replacement, expected in (("", "task goal"), ("different root", "task goal")):
            broken = copy.deepcopy(plan)
            broken["task_goal"] = replacement
            broken = impact.finalize_plan_identity(broken)
            gate = impact.validate_change_plan(
                broken, self.requirements, self.evidence, surface_registry=self.registry,
                authoritative_task_goal=self.goal,
            )
            self.assertFalse(gate["valid"])
            self.assertTrue(any(expected in item for item in gate["errors"]))
        stale = copy.deepcopy(plan)
        stale["task_goal"] = "tampered"
        self.assertNotEqual(impact.plan_content_hash(stale), plan["plan_hash"])
        self.assertFalse(impact.validate_change_plan(
            stale, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=self.goal,
        )["valid"])

    def test_plan_gate_recomputes_behavior_semantics_for_nonmutation_substitutes(self):
        _, _, _, _, plan, _ = self.closed_fixture()
        for disposition, kind in (
            ("INTERFACE_REUSE", "INTERFACE_REUSE"),
            ("TEST_CHANGE", "TEST_CHANGE"),
            ("PRESERVATION_ONLY", "PRESERVATION_ONLY"),
        ):
            broken = copy.deepcopy(plan)
            node = next(item for item in broken["approved_change_nodes"] if item["surface_ids"] == ["SURF-001"])
            node.update({
                "disposition": disposition, "impact_kind": kind,
                "mutation_required": False, "verification_only": True,
                "target_surface_ids": [], "candidate_targets": [], "target_paths": [],
                "inspect_surface_ids": ["SURF-001"], "inspect_targets": ["src/input.js"],
            })
            broken["mutation_surface_ids"] = ["SURF-006"]
            # Retain the old COVERED coverage record deliberately: the gate
            # must ignore it and recompute semantics from the final nodes.
            broken = impact.finalize_plan_identity(broken)
            gate = impact.validate_change_plan(
                broken, self.requirements, self.evidence, surface_registry=self.registry,
                authoritative_task_goal=self.goal,
            )
            self.assertFalse(gate["valid"])
            self.assertTrue(any("REQ-001: semantic obligations" in item for item in gate["errors"]))

    def test_only_open_blocking_challenges_fail_plan_gate(self):
        _, _, _, _, plan, _ = self.closed_fixture()
        resolved = copy.deepcopy(plan)
        resolved["unresolved_challenges"] = [{
            "challenge_id": "CH-X", "challenge_type": "REQUIREMENT_GAP",
            "blocking": True, "lifecycle_state": "RESOLVED",
        }]
        resolved = impact.finalize_plan_identity(resolved)
        self.assertTrue(impact.validate_change_plan(
            resolved, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=self.goal,
        )["valid"])
        opened = copy.deepcopy(resolved)
        opened["unresolved_challenges"][0]["lifecycle_state"] = "OPEN"
        opened = impact.finalize_plan_identity(opened)
        gate = impact.validate_change_plan(
            opened, self.requirements, self.evidence, surface_registry=self.registry,
            authoritative_task_goal=self.goal,
        )
        self.assertFalse(gate["valid"])
        self.assertIn("unresolved blocking challenge", gate["errors"])

    def test_zero_and_multiple_safe_owner_candidates_remain_open(self):
        requirements = [
            {"requirement_id": "REQ-A", "text": "Add token refresh handling.", "status": "active"},
            {"requirement_id": "REQ-B", "text": "Reuse the current token owner.", "status": "active"},
        ]
        evidence = [
            self.fact("REPO-A", "CURRENT_OWNER", "src/a.js", "OwnerA", "OwnerA owns token requests"),
            self.fact("REPO-B", "CURRENT_OWNER", "src/b.js", "OwnerB", "OwnerB owns token sessions"),
        ]
        brain = {"task_goal": {"text": "tokens"}, "repository_evidence_ids": ["REPO-A", "REPO-B"]}
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(brain, requirements, evidence, registry)
        raw = {"impacts": [
            {"impact_id": seed["impact_id"], "disposition": "INTERFACE_REUSE",
             "requirement_ids": ["REQ-B"], "action": "Reuse this owner."}
            for seed in seeds
        ]}
        hydrated = impact.hydrate_impact_map(raw, registry, requirements, evidence, impact_seeds=seeds)
        ambiguous, actions = impact.close_behavior_obligation_gaps(
            hydrated, requirements, evidence, registry, seeds,
        )
        self.assertFalse(actions)
        self.assertFalse(any(item["disposition"] == "MUST_CHANGE" for item in ambiguous["impacts"]))
        no_candidate, no_actions = impact.close_behavior_obligation_gaps(
            {"impacts": []}, requirements, evidence, registry, seeds,
        )
        self.assertFalse(no_actions)
        self.assertEqual(no_candidate["impacts"], [])
        challenges = impact.deterministic_challenges(hydrated, requirements, evidence, registry)
        validation = impact.validate_challenges(challenges, hydrated, requirements, evidence, registry)
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], requirements, evidence, registry, seeds,
            task_goal="Token goal",
        )
        self.assertTrue(any(item["challenge_type"] == "REQUIREMENT_GAP" for item in unresolved))
        plan = impact.build_minimal_change_plan(
            reconciled, requirements, evidence, resolved, unresolved,
            surface_registry=registry, task_goal="Token goal",
        )
        self.assertFalse(impact.validate_change_plan(
            plan, requirements, evidence, surface_registry=registry,
            authoritative_task_goal="Token goal",
        )["valid"])

    def test_unique_generic_owner_fixture_closes_behavior_gap(self):
        requirements = [
            {"requirement_id": "REQ-A", "text": "Add refresh-token rotation.", "status": "active"},
            {"requirement_id": "REQ-B", "text": "Reuse the current authentication service instead of creating another token owner.", "status": "active"},
        ]
        evidence = [self.fact(
            "REPO-A", "CURRENT_OWNER", "src/auth.js", "AuthService",
            "AuthService owns authentication requests.",
        )]
        brain = {"task_goal": {"text": "rotate"}, "repository_evidence_ids": ["REPO-A"]}
        registry = impact.build_canonical_surface_registry(brain, evidence)
        seeds = impact.build_impact_seeds(brain, requirements, evidence, registry)
        hydrated = impact.hydrate_impact_map({
            "impact_id": seeds[0]["impact_id"], "disposition": "INTERFACE_REUSE",
            "requirement_ids": ["REQ-B"], "action": "Reuse AuthService.",
        }, registry, requirements, evidence, impact_seeds=seeds)
        closed, actions = impact.close_behavior_obligation_gaps(
            hydrated, requirements, evidence, registry, seeds,
        )
        self.assertEqual(len(actions), 1)
        self.assertEqual(closed["impacts"][0]["disposition"], "MUST_CHANGE")
        self.assertEqual(closed["impacts"][0]["surface_id"], seeds[0]["surface_id"])

    def test_verified_current_behavior_is_the_only_nonmutation_behavior_exception(self):
        requirements = [{"requirement_id": "REQ-A", "text": "Add CSV export.", "status": "active"}]
        evidence = [self.fact(
            "REPO-A", "CURRENT_BEHAVIOR", "src/export.js", "Exporter",
            "Current Exporter already supports CSV export.",
        )]
        registry = impact.build_canonical_surface_registry(
            {"task_goal": {"text": "export"}, "repository_evidence_ids": ["REPO-A"]}, evidence,
        )
        source = {"impacts": []}
        semantic = impact.evaluate_requirement_obligations(source, requirements, evidence, registry)
        self.assertEqual(semantic["requirements_covered"], 1)
        closed, actions = impact.close_behavior_obligation_gaps(source, requirements, evidence, registry, [])
        self.assertFalse(actions)
        self.assertEqual(closed["impacts"], [])

    def test_noninteractive_mocked_flow_stops_at_approval_with_metrics_and_no_mutation(self):
        contract = {
            "goal": self.goal, "original_goal": self.goal,
            "requirements": [item["text"] for item in self.requirements],
            "source_requirement_ledger": mini.build_source_requirement_ledger(self.requirements),
        }
        result = mini.prepare_stage3_context(
            {"project_mode": mini.EXISTING_PROJECT, "task_brain": self.brain,
             "reconnaissance": {"evidence": self.evidence}},
            contract, interactive=False, terminal_available=False,
            planner_structured_call=lambda *_args: self.weak_decisions(),
            challenger_structured_call=lambda *_args: {"challenges": []},
        )
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(result["status"], "plan_approval_required")
        self.assertTrue(result["read_only"])
        self.assertEqual(mini.RUN["impact_planner_calls"], 1)
        self.assertEqual(mini.RUN["impact_challenger_calls"], 1)
        self.assertEqual(mini.RUN["worker_missions_executed"], 0)
        self.assertEqual(mini.RUN["deterministic_behavior_anchor_promotions"], 1)
        self.assertEqual(mini.RUN["behavior_obligations_uncovered"], 0)
        self.assertEqual(mini.RUN["challenges_remaining_open"], 0)
        self.assertEqual(mini.RUN["plan_requirements_covered"], 4)
        self.assertEqual(mini.RUN["plan_requirements_unassigned"], 0)
        self.assertIn("Escape", mini.format_plan_approval_summary(result["plan"]))
        subject_files = [
            path for path in Path(self.temp.name).glob("**/*")
            if path.is_file() and ".agent_runs" not in path.parts
        ]
        self.assertEqual(subject_files, [])
        self.assertEqual(
            mini.RUN["stage3_workspace_fingerprint_before"],
            mini.RUN["stage3_workspace_fingerprint_after"],
        )

    def test_controlled_external_regression_contract_is_eight_of_eight(self):
        _, reconciled, resolved, unresolved, plan, gate = self.closed_fixture()
        checks = [
            gate["valid"],
            gate["semantic_requirements_covered"] == 4,
            reconciled["deterministic_behavior_anchor_promotions"] == 1,
            any(item["surface_id"] == "SURF-001" and item["disposition"] == "MUST_CHANGE" for item in reconciled["impacts"]),
            any(item["surface_id"] == "SURF-006" and item["disposition"] == "TEST_CHANGE" for item in reconciled["impacts"]),
            "SURF-005" in plan["do_not_touch_surface_ids"],
            bool(resolved) and not unresolved,
            plan["task_goal"] == self.goal,
        ]
        self.assertEqual(sum(bool(item) for item in checks), 8)


if __name__ == "__main__":
    unittest.main()
