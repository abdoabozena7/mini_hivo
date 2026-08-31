import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import impact_planning as impact


class CanonicalImpactSurfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")
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
            "task_goal": {"text": "pause", "evidence_ids": []},
            "repository_evidence_ids": [item["evidence_id"] for item in self.evidence],
            "current_owners": [self.record("InputManager", "src/input.js", "REPO-005", "CURRENT_OWNER"),
                               self.record("GameState", "src/game.js", "REPO-002", "CURRENT_OWNER")],
            "current_interfaces": [self.record("GameState.togglePause", "src/game.js", "REPO-004", "CURRENT_INTERFACE"),
                                    self.record("InputManager.isPressed", "src/input.js", "REPO-007", "CURRENT_INTERFACE")],
            "current_state_ownership": [self.record("InputManager", "src/input.js", "REPO-006", "CURRENT_STATE_OWNER"),
                                         self.record("GameState", "src/game.js", "REPO-003", "CURRENT_STATE_OWNER")],
            "relevant_tests": [self.record("InputManager", "tests/input.test.js", "REPO-009", "CURRENT_TEST")],
            "preservation_constraints": [{"text": self.requirements[2]["text"], "requirement_ids": ["REQ-003"]}],
        }

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
        return {"symbol": symbol, "path": path, "evidence_ids": [evidence_id], "category": category,
                "text": symbol, "provenance": impact.REPOSITORY_EVIDENCE}

    def registry(self):
        value = impact.build_canonical_surface_registry(self.brain, self.evidence)
        self.assertTrue(impact.validate_canonical_surface_registry(value, self.evidence)["valid"])
        return value

    def canonical_candidate(self, registry=None):
        registry = registry or self.registry()
        by_symbol = {
            str(item.get("symbol")): item for item in registry["surfaces"]
            if item.get("kind") != "TEST"
        }
        by_symbol["tests/input.test.js"] = next(
            item for item in registry["surfaces"] if item.get("kind") == "TEST"
        )
        return {
            "task_goal": "pause",
            "impacts": [
                {"impact_id": "IMP-001", "surface_id": by_symbol["InputManager"]["surface_id"],
                 "disposition": "MUST_CHANGE", "requirement_ids": ["REQ-001", "REQ-002", "REQ-003"],
                 "interfaces_to_reuse": [by_symbol["InputManager.isPressed"]["surface_id"]],
                 "action": "Detect Escape through the current input owner.",
                 "preserve": ["WASD/arrow controls"], "verification": ["Escape is detected"]},
                {"impact_id": "IMP-002", "surface_id": by_symbol["GameState.togglePause"]["surface_id"],
                 "disposition": "INTERFACE_REUSE", "requirement_ids": ["REQ-001", "REQ-002"],
                 "interfaces_to_reuse": [by_symbol["GameState.togglePause"]["surface_id"]],
                 "action": "Reuse the current pause transition.", "preserve": ["one pause owner"],
                 "verification": ["paused state toggles"]},
                {"impact_id": "IMP-003", "surface_id": by_symbol["BEST_SCORE_KEY"]["surface_id"],
                 "disposition": "PRESERVATION_ONLY", "requirement_ids": ["REQ-003"],
                 "action": "Preserve persistent best-score behavior."},
                {"impact_id": "IMP-004", "surface_id": by_symbol["tests/input.test.js"]["surface_id"],
                 "disposition": "TEST_CHANGE", "requirement_ids": ["REQ-004"],
                 "action": "Update pause/input tests.", "verification": ["pause tests pass"]},
            ],
            "integration_verification": ["Run relevant pause/input tests."],
            "insufficient_evidence": [],
        }

    def test_registry_is_bounded_and_assigns_expected_roles(self):
        registry = self.registry()
        self.assertEqual(len(registry["surfaces"]), 7)
        self.assertEqual(
            [(item["surface_id"], item["path"], item["symbol"]) for item in registry["surfaces"]],
            [("SURF-001", "src/input.js", "InputManager"),
             ("SURF-002", "src/game.js", "GameState"),
             ("SURF-003", "src/game.js", "GameState.togglePause"),
             ("SURF-004", "src/input.js", "InputManager.isPressed"),
             ("SURF-005", "src/storage.js", "BEST_SCORE_KEY"),
             ("SURF-006", "tests/input.test.js", "InputManager"),
             ("SURF-007", "index.html", "")],
        )
        self.assertEqual(registry["surfaces"][2]["owner_surface_id"], "SURF-002")
        self.assertEqual(registry["surfaces"][3]["owner_surface_id"], "SURF-001")
        self.assertLessEqual(len(json.dumps(registry)), impact.MAX_PLANNER_CONTEXT_CHARS)

    def test_planner_context_exposes_ids_without_raw_source(self):
        registry = self.registry()
        context = impact.build_planner_context(
            self.brain, self.requirements, self.evidence,
            project_invariants=["preserve owners"], surface_registry=registry,
            impact_seeds=impact.build_impact_seeds(self.brain, self.requirements, self.evidence, registry),
        )
        encoded = json.dumps(context)
        self.assertIn("SURF-003", encoded)
        self.assertIn("REPO-004", encoded)
        self.assertNotIn("file_contents", encoded)
        self.assertNotIn("this.paused", encoded)

    def test_hydration_rejects_hallucinated_paths_and_interfaces(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"][0]["path"] = "src/input/InputHandler.cpp"
        candidate["impacts"][0]["interfaces_to_reuse"] = ["InputHandler::process_input(Key)"]
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        self.assertFalse(hydrated["hydration_valid"])
        self.assertGreaterEqual(hydrated["impact_invented_existing_paths_rejected"], 1)
        self.assertGreaterEqual(hydrated["impact_invented_interfaces_rejected"], 1)
        self.assertNotIn("InputHandler.cpp", json.dumps(hydrated["impacts"]))

    def test_exact_live_v18_hallucinations_never_become_authoritative(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"] = [
            {"impact_id": "BAD-001", "surface_id": "SURF-001", "disposition": "MUST_CHANGE",
             "requirement_ids": ["REQ-001"], "repository_evidence_ids": ["REPO-002"],
             "path": "src/input/InputHandler.cpp", "symbols": ["InputHandler"],
             "interfaces_to_reuse": ["InputHandler::process_input(Key)"],
             "action": "Add Escape input.", "preserve": [], "verification": []},
            {"impact_id": "BAD-002", "surface_id": "SURF-002", "disposition": "MUST_CHANGE",
             "requirement_ids": ["REQ-001"], "repository_evidence_ids": ["REPO-005"],
             "path": "src/game/GameLoop.cpp", "symbols": ["GameLoop"],
             "interfaces_to_reuse": ["GameState::is_paused()"],
             "action": "Add pause state.", "preserve": [], "verification": []},
            {"impact_id": "BAD-003", "surface_id": "SURF-005", "disposition": "PRESERVATION_ONLY",
             "requirement_ids": ["REQ-003"], "repository_evidence_ids": ["REPO-001"],
             "path": "src/score/ScoreManager.cpp", "symbols": ["ScoreManager"],
             "interfaces_to_reuse": [], "action": "Preserve score.", "preserve": [], "verification": []},
            {"impact_id": "BAD-004", "surface_id": "SURF-006", "disposition": "TEST_CHANGE",
             "requirement_ids": ["REQ-004"], "repository_evidence_ids": ["REPO-004"],
             "path": "tests/GameTest.cpp", "symbols": ["GameTest"],
             "interfaces_to_reuse": [], "action": "Test pause.", "preserve": [], "verification": []},
            {"impact_id": "BAD-005", "surface_id": "SURF-002", "disposition": "MUST_CHANGE",
             "requirement_ids": ["REQ-002"], "repository_evidence_ids": ["REPO-003"],
             "path": "src/state/GameState.cpp", "symbols": ["GameState"],
             "interfaces_to_reuse": [], "action": "Move pause state.", "preserve": [], "verification": []},
        ]
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        encoded = json.dumps(hydrated["impacts"])
        self.assertFalse(hydrated["hydration_valid"])
        for invented in (
            "InputHandler.cpp", "GameLoop.cpp", "ScoreManager.cpp", "GameTest.cpp",
            "GameState.cpp", "InputHandler::process_input(Key)", "GameState::is_paused()",
        ):
            self.assertNotIn(invented, encoded)
        self.assertGreaterEqual(hydrated["impact_invented_existing_paths_rejected"], 5)
        self.assertGreaterEqual(hydrated["impact_invented_interfaces_rejected"], 2)
        validation = impact.validate_impact_map(
            hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        self.assertEqual(validation["impact_supported"], 0)
        self.assertIn("at least one impact is required", validation["errors"])

    def test_hydration_rejects_mismatched_evidence_and_unknown_surface(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"][0]["surface_id"] = "SURF-999"
        candidate["impacts"][1]["repository_evidence_ids"] = ["REPO-008"]
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        self.assertFalse(hydrated["hydration_valid"])
        self.assertGreaterEqual(hydrated["impact_unknown_surface_references"], 1)
        self.assertGreaterEqual(hydrated["impact_surface_evidence_mismatches"], 1)

    def test_legacy_exact_compatibility_never_fuzzy_maps_unknown_surface_id(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"][0]["surface_id"] = "SURF-999"
        candidate["impacts"][0]["path"] = "src/input.js"
        hydrated = impact.hydrate_impact_map(
            candidate, registry, self.requirements, self.evidence, allow_legacy_exact=True,
        )
        self.assertFalse(hydrated["hydration_valid"])
        self.assertNotIn("IMP-001", {item.get("impact_id") for item in hydrated["impacts"]})

    def test_new_surface_proposal_requires_insufficiency_provenance(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["new_surface_proposals"] = [{
            "proposal_id": "NEW-PAUSE-ADAPTER", "kind": "ADAPTER",
            "requirement_ids": ["REQ-001"], "reason_existing_surfaces_insufficient": "Existing surfaces are insufficient for this responsibility.",
            "parent_scope": "pause", "intended_responsibility": "bridge", "verification_responsibility": "test bridge",
        }]
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        self.assertTrue(hydrated["hydration_valid"])
        self.assertEqual(hydrated["new_surface_proposals"][0]["provenance"], impact.DERIVED_PLAN_DECISION)
        candidate["new_surface_proposals"][0]["reason_existing_surfaces_insufficient"] = "Prefer another abstraction."
        self.assertFalse(impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)["hydration_valid"])

    def test_valid_new_surface_proposal_is_actionable_plan_authority(self):
        registry = self.registry()
        requirements = [{
            "requirement_id": "REQ-NEW", "text": "Add a new adapter module because no existing surface provides it.",
            "status": "active",
        }]
        candidate = {
            "task_goal": "Add the requested adapter.",
            "new_surface_proposals": [{
                "proposal_id": "NEW-ADAPTER", "kind": "MODULE",
                "requirement_ids": ["REQ-NEW"],
                "reason_existing_surfaces_insufficient": "No existing surface provides the explicitly requested adapter responsibility.",
                "parent_scope": "src", "intended_responsibility": "provide the requested adapter",
                "verification_responsibility": "exercise the adapter contract",
            }],
            "impacts": [{
                "impact_id": "IMP-NEW", "new_surface_proposal_ids": ["NEW-ADAPTER"],
                "disposition": "MUST_CHANGE", "requirement_ids": ["REQ-NEW"],
                "action": "Create the requested adapter responsibility.",
                "interfaces_to_reuse": [], "preserve": [],
                "verification": ["The adapter contract is exercised."],
            }],
            "integration_verification": ["Run the adapter contract verification."],
            "insufficient_evidence": [],
        }
        self.assertTrue(impact.validate_planner_output(candidate, requirements))
        hydrated = impact.hydrate_impact_map(candidate, registry, requirements, self.evidence)
        self.assertTrue(hydrated["hydration_valid"], hydrated["hydration_errors"])
        self.assertEqual(hydrated["new_surface_proposals"][0]["provenance"], impact.DERIVED_PLAN_DECISION)
        validation = impact.validate_impact_map(
            hydrated, requirements, self.evidence, surface_registry=registry,
        )
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(validation["impact_supported"], 1)
        plan = impact.build_minimal_change_plan(
            hydrated, requirements, self.evidence, surface_registry=registry,
        )
        node = plan["approved_change_nodes"][0]
        self.assertEqual(node["target_new_surface_proposal_ids"], ["NEW-ADAPTER"])
        self.assertFalse(node["target_surface_ids"])
        self.assertFalse(node["candidate_targets"])
        gate = impact.validate_change_plan(
            plan, requirements, self.evidence, surface_registry=registry,
        )
        self.assertTrue(gate["valid"], gate["errors"])
        contract = impact.approved_plan_node_contract(plan)
        self.assertEqual(
            contract["nodes"][0]["target_new_surface_proposal_ids"], ["NEW-ADAPTER"],
        )
        packet = impact.decomposition_plan_packet(plan)
        self.assertEqual(packet["nodes"][0]["new_surface_proposal_ids"], ["NEW-ADAPTER"])
        scope = impact.mutation_scope(contract)
        self.assertEqual(scope["approved_new_surface_proposal_ids"], ["NEW-ADAPTER"])
        self.assertEqual(scope["approved_new_surface_parent_scopes"], ["src"])

    def test_canonical_plan_derives_disjoint_do_not_touch(self):
        registry = self.registry()
        hydrated = impact.hydrate_impact_map(self.canonical_candidate(registry), registry, self.requirements, self.evidence)
        self.assertTrue(hydrated["hydration_valid"])
        plan = impact.build_minimal_change_plan(hydrated, self.requirements, self.evidence, surface_registry=registry)
        gate = impact.validate_change_plan(plan, self.requirements, self.evidence, surface_registry=registry)
        self.assertTrue(gate["valid"], gate)
        self.assertIn("SURF-005", plan["do_not_touch_surface_ids"])
        self.assertNotIn("SURF-001", plan["do_not_touch_surface_ids"])
        self.assertTrue(set(plan["mutation_surface_ids"]).isdisjoint(plan["do_not_touch_surface_ids"]))
        self.assertEqual(set(plan["mutation_surface_ids"]), {"SURF-001", "SURF-006"})
        self.assertFalse(any(
            "src/game.js" in node.get("candidate_targets", [])
            for node in plan["approved_change_nodes"]
        ))
        self.assertTrue(any(
            "SURF-003" in node.get("inspect_surface_ids", [])
            and node.get("disposition") == "INTERFACE_REUSE"
            for node in plan["approved_change_nodes"]
        ))
        self.assertEqual(plan["tests_to_update_or_add"][0]["test_surface_ids"], ["SURF-006"])
        self.assertIn("SURF-003", plan["interface_surface_ids"])
        self.assertIn("SURF-004", plan["interface_surface_ids"])
        self.assertNotIn(".cpp", json.dumps(plan))

    def test_unsupported_storage_mutation_reconciles_to_preservation_only(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        storage = next(item for item in candidate["impacts"] if item["surface_id"] == "SURF-005")
        storage.update({
            "disposition": "MUST_CHANGE",
            "requirement_ids": ["REQ-001"],
            "action": "Modify storage while adding pause support.",
        })
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        challenges = impact.deterministic_challenges(
            hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        repaired, resolved, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], self.requirements, self.evidence,
            surface_registry=registry,
        )
        storage = next(item for item in repaired["impacts"] if item["surface_id"] == "SURF-005")
        self.assertTrue(any(item["challenge_type"] == "UNSUPPORTED_NECESSITY" for item in resolved))
        self.assertFalse(unresolved)
        self.assertEqual(storage["disposition"], "PRESERVATION_ONLY")
        self.assertEqual(storage["impact_kind"], "PRESERVATION_ONLY")

    def test_deterministic_challenger_repairs_missed_interface_by_surface_id(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"][0]["interfaces_to_reuse"] = []
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        challenges = impact.deterministic_challenges(
            hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        self.assertTrue(any(item["challenge_type"] == "INTERFACE_REUSE_MISSED" for item in validation["validated"]))
        repaired, resolved, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], self.requirements, self.evidence,
            surface_registry=registry,
        )
        self.assertFalse(unresolved)
        input_impact = next(item for item in repaired["impacts"] if item["surface_id"] == "SURF-001")
        self.assertEqual(input_impact["interfaces_to_reuse"], ["SURF-004"])
        self.assertTrue(resolved)

    def test_challenger_unknown_surface_and_mismatched_evidence_are_rejected(self):
        registry = self.registry()
        hydrated = impact.hydrate_impact_map(
            self.canonical_candidate(registry), registry, self.requirements, self.evidence,
        )
        challenges = impact.normalize_challenges({"challenges": [
            {"challenge_id": "CH-BAD-SURFACE", "challenge_type": "WRONG_OWNER",
             "impact_ids": ["IMP-001"], "surface_ids": ["SURF-999"],
             "requirement_ids": ["REQ-002"], "repository_evidence_ids": ["REPO-005"],
             "claim": "The owner is wrong.", "proposed_resolution": "Change it.", "blocking": True},
            {"challenge_id": "CH-BAD-EVIDENCE", "challenge_type": "WRONG_OWNER",
             "impact_ids": ["IMP-001"], "surface_ids": ["SURF-001"],
             "requirement_ids": ["REQ-002"], "repository_evidence_ids": ["REPO-002"],
             "claim": "The owner is wrong.", "proposed_resolution": "Change it.", "blocking": True},
        ]})
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        self.assertFalse(validation["validated"])
        self.assertEqual(len(validation["rejected"]), 2)
        encoded = json.dumps(validation["rejected"])
        self.assertIn("unknown canonical surface reference", encoded)
        self.assertIn("challenge evidence does not support the impacted surface", encoded)

    def test_duplicate_pause_owner_is_rejected_and_reconciled(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        candidate["impacts"][0]["action"] = "Add a paused field to InputManager."
        candidate["impacts"][0]["candidate_change"] = candidate["impacts"][0]["action"]
        hydrated = impact.hydrate_impact_map(candidate, registry, self.requirements, self.evidence)
        challenges = impact.deterministic_challenges(
            hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        types = {item["challenge_type"] for item in challenges}
        self.assertTrue({"DUPLICATE_OWNERSHIP_RISK", "WRONG_OWNER"}.issubset(types))
        validation = impact.validate_challenges(
            challenges, hydrated, self.requirements, self.evidence, surface_registry=registry,
        )
        repaired, _, unresolved = impact.reconcile_impact_map(
            hydrated, validation["validated"], self.requirements, self.evidence,
            surface_registry=registry,
        )
        self.assertFalse(unresolved)
        self.assertNotIn("paused field", repaired["impacts"][0]["candidate_change"])

    def test_same_surface_preservation_is_local_not_global(self):
        registry = self.registry()
        hydrated = impact.hydrate_impact_map(self.canonical_candidate(registry), registry, self.requirements, self.evidence)
        same = copy.deepcopy(hydrated["impacts"][0])
        same.update({"impact_id": "IMP-LOCAL-PRESERVE", "disposition": "PRESERVATION_ONLY",
                     "impact_kind": "PRESERVATION_ONLY", "necessity_status": "PRESERVATION_ONLY"})
        hydrated["impacts"].append(same)
        plan = impact.build_minimal_change_plan(hydrated, self.requirements, self.evidence, surface_registry=registry)
        self.assertIn("SURF-001", plan["mutation_surface_ids"])
        self.assertNotIn("SURF-001", plan["do_not_touch_surface_ids"])

    def test_noninteractive_canonical_prepare_requires_approval_without_worker(self):
        registry = self.registry()
        candidate = self.canonical_candidate(registry)
        contract = {
            "source_requirement_ledger": mini.build_source_requirement_ledger(self.requirements),
            "requirements": [item["text"] for item in self.requirements],
        }
        understanding = {
            "project_mode": mini.EXISTING_PROJECT, "task_brain": self.brain,
            "reconnaissance": {"evidence": self.evidence},
        }
        result = mini.prepare_stage3_context(
            understanding, contract, interactive=False, terminal_available=False,
            planner_structured_call=lambda *_args: candidate,
            challenger_structured_call=lambda *_args: {"challenges": []},
        )
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(result["status"], "plan_approval_required")
        self.assertTrue(result["read_only"])
        self.assertEqual(mini.RUN["impact_planner_calls"], 1)
        self.assertEqual(mini.RUN["impact_challenger_calls"], 1)
        self.assertEqual(mini.RUN["plan_approval_granted"], 0)


if __name__ == "__main__":
    unittest.main()
