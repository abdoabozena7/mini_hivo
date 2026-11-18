import copy
import json
import tempfile
import unittest
from pathlib import Path

import mini
from hivo import impact_planning as impact


class ImpactPlanningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "gemma4:e4b"
        mini.reset_run("recursive")
        self.requirements = [
            {
                "requirement_id": "REQ-001",
                "text": "Add Escape-key pause/resume support to the existing game.",
                "provenance": mini.USER_STATED,
                "status": "active",
            },
            {
                "requirement_id": "REQ-002",
                "text": "Reuse the current input and pause-state architecture instead of creating duplicate input state or another game-state owner.",
                "provenance": mini.USER_STATED,
                "status": "active",
            },
            {
                "requirement_id": "REQ-003",
                "text": "Preserve the current WASD/arrow controls and persistent best-score behavior.",
                "provenance": mini.USER_STATED,
                "status": "active",
            },
            {
                "requirement_id": "REQ-004",
                "text": "Update or add the relevant tests.",
                "provenance": mini.USER_STATED,
                "status": "active",
            },
        ]
        self.evidence = [
            self.fact("REPO-001", "CURRENT_OWNER", "src/input.js", "InputManager", "InputManager owns keyboard input."),
            self.fact("REPO-002", "CURRENT_STATE_OWNER", "src/input.js", "InputManager", "InputManager owns the current keyboard key state."),
            self.fact("REPO-003", "CURRENT_OWNER", "src/game.js", "GameState", "GameState owns game state."),
            self.fact("REPO-004", "CURRENT_STATE_OWNER", "src/game.js", "GameState.paused", "GameState.paused is the current pause-state owner."),
            self.fact("REPO-005", "CURRENT_INTERFACE", "src/game.js", "GameState.togglePause", "GameState.togglePause is the current pause transition interface."),
            self.fact("REPO-006", "CURRENT_INTERFACE", "src/input.js", "InputManager.isPressed", "InputManager.isPressed is the current keyboard query interface."),
            self.fact("REPO-007", "CURRENT_PERSISTENCE", "src/storage.js", "BEST_SCORE_KEY", "BEST_SCORE_KEY owns persistent best-score behavior."),
            self.fact("REPO-008", "CURRENT_TEST", "tests/input.test.js", "InputManager", "tests/input.test.js verifies current input behavior."),
        ]
        self.contract = self.make_contract()
        self.task_brain = self.make_task_brain()

    def tearDown(self):
        mini.rollback_transaction()
        mini.ACTIVE_TOOL_CONTRACT = None
        self.temp.cleanup()

    @staticmethod
    def fact(evidence_id, category, path, symbol, text):
        return {
            "evidence_id": evidence_id,
            "category": category,
            "path": path,
            "symbol": symbol,
            "fact": text,
            "line_start": 1,
            "line_end": 2,
            "file_sha256": evidence_id.lower().replace("repo-", "").rjust(64, "0"),
        }

    def make_contract(self):
        ledger = mini.build_source_requirement_ledger(self.requirements)
        return {
            "status": "ready",
            "goal": "Add Escape pause support without changing current ownership.",
            "requirements": [item["text"] for item in self.requirements],
            "constraints": ["preserve current ownership"],
            "success_criteria": ["the relevant tests pass"],
            "original_goal": "Add Escape pause support without changing current ownership.",
            "source_requirement_ledger": ledger,
            "source_contract": mini.source_contract_from_ledger(
                "Add Escape pause support", ledger,
            ),
            "user_confirmed_requirements": [],
            "derived_assumptions": [],
        }

    def make_task_brain(self):
        def entry(text, evidence_ids=None, path=None, symbol=None, category=None):
            value = {
                "text": text,
                "provenance": mini.REPOSITORY_EVIDENCE,
                "requirement_ids": [],
                "evidence_ids": list(evidence_ids or []),
            }
            if path:
                value["path"] = path
            if symbol:
                value["symbol"] = symbol
            if category:
                value["category"] = category
            return value

        return {
            "version": 1,
            "task_id": "ROOT",
            "task_goal": {
                "text": self.contract["goal"], "provenance": mini.USER_STATED,
                "requirement_ids": [item["requirement_id"] for item in self.requirements],
                "evidence_ids": [],
            },
            "project_mode": mini.EXISTING_PROJECT,
            "source_requirement_ids": [item["requirement_id"] for item in self.requirements],
            "user_confirmed_decisions": [],
            "relevant_project_brain_projection": [{
                "text": "preserve one authoritative pause owner", "provenance": mini.PROJECT_BRAIN,
                "requirement_ids": [], "evidence_ids": [],
            }],
            "current_owners": [
                entry("InputManager owns keyboard input", ["REPO-001"], "src/input.js", "InputManager", "CURRENT_OWNER"),
                entry("GameState owns game state", ["REPO-003"], "src/game.js", "GameState", "CURRENT_OWNER"),
            ],
            "current_interfaces": [
                entry("GameState.togglePause is current", ["REPO-005"], "src/game.js", "GameState.togglePause", "CURRENT_INTERFACE"),
                entry("InputManager.isPressed is current", ["REPO-006"], "src/input.js", "InputManager.isPressed", "CURRENT_INTERFACE"),
            ],
            "current_state_ownership": [
                entry("InputManager owns key state", ["REPO-002"], "src/input.js", "InputManager", "CURRENT_STATE_OWNER"),
                entry("GameState.paused owns pause state", ["REPO-004"], "src/game.js", "GameState.paused", "CURRENT_STATE_OWNER"),
            ],
            "relevant_dependencies": [],
            "relevant_tests": [
                entry("input tests are current", ["REPO-008"], "tests/input.test.js", "InputManager", "CURRENT_TEST"),
            ],
            "preservation_constraints": [{
                "text": self.requirements[2]["text"], "provenance": mini.USER_STATED,
                "requirement_ids": ["REQ-003"], "evidence_ids": [],
            }],
            "derived_task_assumptions": [],
            "open_questions": [],
            "acceptance_conditions": [],
            "known_non_goals": [],
        }

    def candidate_map(self, include_storage=True, include_test=True):
        impacts = [
            {
                "impact_id": "IMP-001", "component": "InputManager", "path": "src/input.js",
                "symbols": ["InputManager", "InputManager.isPressed"],
                "impact_kind": "BEHAVIOR_CHANGE", "requirement_ids": ["REQ-001", "REQ-002", "REQ-003"],
                "repository_evidence_ids": ["REPO-001", "REPO-002", "REPO-006"],
                "reason": "The current keyboard owner must recognize Escape.",
                "existing_owner": "InputManager", "existing_interfaces_to_reuse": ["InputManager.isPressed"],
                "preserve": ["current WASD/arrow controls"],
                "candidate_change": "Integrate Escape detection through the current InputManager.",
                "local_verification": ["Escape is detected and WASD/arrow controls still work"],
                "necessity_status": "MUST_CHANGE",
            },
            {
                "impact_id": "IMP-002", "component": "GameState", "path": "src/game.js",
                "symbols": ["GameState", "GameState.paused", "GameState.togglePause"],
                "impact_kind": "INTEGRATION_CHANGE", "requirement_ids": ["REQ-001", "REQ-002"],
                "repository_evidence_ids": ["REPO-003", "REPO-004", "REPO-005"],
                "reason": "Pause integration must use the current pause owner.",
                "existing_owner": "GameState", "existing_interfaces_to_reuse": ["GameState.togglePause"],
                "preserve": ["GameState remains the authoritative paused-state owner"],
                "candidate_change": "Connect Escape handling to GameState.togglePause without duplicate state.",
                "local_verification": ["Escape toggles GameState.paused through togglePause"],
                "necessity_status": "CANDIDATE",
            },
        ]
        if include_storage:
            impacts.append({
                "impact_id": "IMP-003", "component": "best-score persistence", "path": "src/storage.js",
                "symbols": ["BEST_SCORE_KEY"], "impact_kind": "INTEGRATION_CHANGE",
                "requirement_ids": ["REQ-003"], "repository_evidence_ids": ["REPO-007"],
                "reason": "Best-score persistence must remain intact.", "existing_owner": "BEST_SCORE_KEY",
                "existing_interfaces_to_reuse": [], "preserve": ["persistent best-score behavior"],
                "candidate_change": "Modify storage while adding pause support.",
                "local_verification": ["best-score persistence remains unchanged"],
                "necessity_status": "MUST_CHANGE",
            })
        if include_test:
            impacts.append({
                "impact_id": f"IMP-{len(impacts) + 1:03d}", "component": "input tests",
                "path": "tests/input.test.js", "symbols": ["InputManager"],
                "impact_kind": "TEST_CHANGE", "requirement_ids": ["REQ-004"],
                "repository_evidence_ids": ["REPO-008"], "reason": "Current input tests are relevant.",
                "existing_owner": "", "existing_interfaces_to_reuse": [],
                "preserve": ["existing input assertions"],
                "candidate_change": "Update or add relevant Escape pause/input tests.",
                "local_verification": ["pause/input tests pass"], "necessity_status": "CANDIDATE",
            })
        return impact.normalize_impact_map({
            "task_goal": self.contract["goal"],
            "impacts": impacts,
            "integration_verification": [
                "Escape toggles current GameState.paused", "WASD/arrow controls still work",
                "best-score persistence is unchanged", "no duplicate pause/input owner exists",
                "relevant tests pass",
            ],
            "insufficient_evidence": [],
        })

    def final_plan(self):
        candidate = self.candidate_map()
        deterministic = impact.deterministic_challenges(candidate, self.requirements, self.evidence)
        validation = impact.validate_challenges(
            deterministic, candidate, self.requirements, self.evidence,
        )
        reconciled, resolved, unresolved = impact.reconcile_impact_map(
            candidate, validation["validated"], self.requirements, self.evidence,
        )
        return impact.build_minimal_change_plan(
            reconciled, self.requirements, self.evidence, resolved, unresolved,
        )

    def understanding(self):
        return {
            "status": "ready", "project_mode": mini.EXISTING_PROJECT,
            "task_brain": self.task_brain,
            "reconnaissance": {"evidence": self.evidence, "read_only": True},
            "contract": self.contract,
        }

    def test_planner_context_is_bounded_and_contains_only_semantic_stage1_stage2_facts(self):
        context = impact.build_planner_context(
            self.task_brain, self.requirements, self.evidence,
            ["preserve one authoritative owner"],
        )
        encoded = json.dumps(context)
        self.assertLessEqual(len(encoded), impact.MAX_PLANNER_CONTEXT_CHARS)
        self.assertIn("REQ-001", encoded)
        self.assertIn("REPO-005", encoded)
        self.assertIn("GameState.togglePause", encoded)
        self.assertNotIn("file_contents", encoded)
        self.assertNotIn("raw_repository", encoded)
        self.assertNotIn("support", context["accepted_repository_evidence"][0])

    def test_impact_map_schema_and_validation_require_evidence_and_requirements(self):
        candidate = self.candidate_map()
        self.assertTrue(impact.validate_impact_map(candidate, self.requirements, self.evidence)["valid"])
        bad = copy.deepcopy(candidate)
        bad["impacts"][0]["repository_evidence_ids"] = []
        validation = impact.validate_impact_map(bad, self.requirements, self.evidence)
        self.assertFalse(validation["valid"])
        self.assertTrue(any("repository evidence" in item for item in validation["errors"]))

    def test_relevant_surface_does_not_automatically_become_must_change(self):
        fallback = impact.deterministic_impact_map(
            self.contract["goal"], self.requirements, self.evidence,
        )
        storage = next(item for item in fallback["impacts"] if item["path"] == "src/storage.js")
        self.assertEqual(storage["impact_kind"], "PRESERVATION_ONLY")
        self.assertEqual(storage["necessity_status"], "PRESERVATION_ONLY")

    def test_controlled_candidate_surfaces_are_evidence_grounded(self):
        candidate = self.candidate_map()
        by_path = {item["path"]: item for item in candidate["impacts"]}
        self.assertIn("REPO-001", by_path["src/input.js"]["repository_evidence_ids"])
        self.assertIn("REPO-005", by_path["src/game.js"]["repository_evidence_ids"])
        self.assertIn("REPO-008", by_path["tests/input.test.js"]["repository_evidence_ids"])
        self.assertIn("REPO-007", by_path["src/storage.js"]["repository_evidence_ids"])

    def test_challenger_context_is_bounded_and_has_no_raw_repository(self):
        context = impact.build_challenger_context(
            self.candidate_map(), self.requirements, self.evidence, self.task_brain,
        )
        encoded = json.dumps(context)
        self.assertLessEqual(len(encoded), impact.MAX_CHALLENGER_CONTEXT_CHARS)
        self.assertIn("candidate_impact_map", context)
        self.assertNotIn("full_file_contents", encoded)
        self.assertNotIn("this.paused =", encoded)

    def test_challenger_detects_unsupported_storage_mutation(self):
        challenges = impact.deterministic_challenges(
            self.candidate_map(), self.requirements, self.evidence,
        )
        storage = [item for item in challenges if "IMP-003" in item["impact_ids"]]
        self.assertTrue(any(item["challenge_type"] == "UNSUPPORTED_NECESSITY" for item in storage))

    def test_duplicate_state_and_wrong_owner_are_detected(self):
        candidate = self.candidate_map(include_storage=False)
        candidate["impacts"][0].update({
            "candidate_change": "Add a paused field to InputManager.",
            "repository_evidence_ids": ["REPO-001", "REPO-004", "REPO-005"],
        })
        types = {item["challenge_type"] for item in impact.deterministic_challenges(
            candidate, self.requirements, self.evidence,
        )}
        self.assertIn("DUPLICATE_OWNERSHIP_RISK", types)
        self.assertIn("WRONG_OWNER", types)

    def test_wrong_interface_creation_is_challenged_when_toggle_exists(self):
        candidate = self.candidate_map(include_storage=False)
        game = candidate["impacts"][1]
        game["candidate_change"] = "Create newPauseController() for the pause transition."
        game["existing_interfaces_to_reuse"] = []
        types = {item["challenge_type"] for item in impact.deterministic_challenges(
            candidate, self.requirements, self.evidence,
        )}
        self.assertIn("INTERFACE_REUSE_MISSED", types)

    def test_missing_test_responsibility_is_detected_and_reconciled(self):
        candidate = self.candidate_map(include_storage=False, include_test=False)
        challenges = impact.deterministic_challenges(candidate, self.requirements, self.evidence)
        test_gap = next(item for item in challenges if item["challenge_type"] == "TEST_GAP")
        validated = impact.validate_challenges(
            [test_gap], candidate, self.requirements, self.evidence,
        )["validated"]
        revised, resolved, unresolved = impact.reconcile_impact_map(
            candidate, validated, self.requirements, self.evidence,
        )
        self.assertTrue(any(item["impact_kind"] == "TEST_CHANGE" for item in revised["impacts"]))
        self.assertTrue(resolved)
        self.assertFalse(unresolved)

    def test_unrelated_rendering_change_is_detected(self):
        candidate = self.candidate_map(include_storage=False)
        candidate["impacts"].append({
            "impact_id": "IMP-099", "component": "theme renderer", "path": "src/theme.js",
            "symbols": ["ThemeRenderer"], "impact_kind": "BEHAVIOR_CHANGE",
            "requirement_ids": ["REQ-001"], "repository_evidence_ids": ["REPO-007"],
            "reason": "Change colors and theme rendering.", "existing_owner": "ThemeRenderer",
            "existing_interfaces_to_reuse": [], "preserve": [],
            "candidate_change": "Edit unrelated theme colors.",
            "local_verification": ["theme colors changed"], "necessity_status": "MUST_CHANGE",
            "provenance": impact.DERIVED_PLAN_DECISION,
        })
        types = {item["challenge_type"] for item in impact.deterministic_challenges(
            candidate, self.requirements, self.evidence,
        )}
        self.assertIn("UNRELATED_CHANGE", types)

    def test_missing_state_api_test_surfaces_are_requirement_gaps_not_file_minimization(self):
        requirements = [
            {"requirement_id": "REQ-S", "text": "Update state behavior.", "status": "active"},
            {"requirement_id": "REQ-A", "text": "Update API behavior.", "status": "active"},
            {"requirement_id": "REQ-T", "text": "Update relevant tests.", "status": "active"},
        ]
        candidate = copy.deepcopy(self.candidate_map(include_storage=False, include_test=False))
        candidate["impacts"] = [candidate["impacts"][0]]
        candidate["impacts"][0]["requirement_ids"] = ["REQ-S"]
        challenges = impact.deterministic_challenges(candidate, requirements, self.evidence)
        gaps = [item for item in challenges if item["challenge_type"] == "REQUIREMENT_GAP"]
        self.assertEqual({item["requirement_ids"][0] for item in gaps}, {"REQ-A", "REQ-T"})

    def test_unsupported_challenger_assertion_is_rejected(self):
        bad = impact.normalize_challenges({"challenges": [{
            "challenge_id": "CH-X", "challenge_type": "WRONG_OWNER",
            "impact_ids": ["IMP-001"], "requirement_ids": ["REQ-001"],
            "repository_evidence_ids": ["REPO-999"], "claim": "wrong",
            "proposed_resolution": "move it", "blocking": True,
        }]})
        result = impact.validate_challenges(
            bad, self.candidate_map(), self.requirements, self.evidence,
        )
        self.assertFalse(result["validated"])
        self.assertEqual(result["rejected"][0]["validation_status"], "REJECTED")

    def test_valid_evidence_backed_challenge_is_accepted(self):
        challenges = impact.deterministic_challenges(
            self.candidate_map(), self.requirements, self.evidence,
        )
        result = impact.validate_challenges(
            challenges, self.candidate_map(), self.requirements, self.evidence,
        )
        self.assertTrue(result["validated"])
        self.assertTrue(all(item["validation_status"] == "VALIDATED" for item in result["validated"]))

    def test_challenge_and_revision_rounds_are_hard_bounded(self):
        self.assertEqual(impact.MAX_CHALLENGE_ROUNDS, 1)
        self.assertEqual(impact.MAX_REVISION_ROUNDS, 1)
        self.assertLessEqual(impact.MAX_CHALLENGES, 12)

    def test_final_plan_excludes_storage_mutation_but_retains_preservation(self):
        plan = self.final_plan()
        targets = {
            item for node in plan["approved_change_nodes"] for item in node["candidate_targets"]
        }
        self.assertNotIn("src/storage.js", targets)
        self.assertIn("src/storage.js", plan["do_not_touch"])
        self.assertTrue(any(item["path"] == "src/storage.js" for item in plan["preservation_only_surfaces"]))

    def test_final_plan_preserves_owner_reuses_interface_and_carries_tests(self):
        plan = self.final_plan()
        encoded = json.dumps(plan)
        self.assertIn("GameState", encoded)
        self.assertIn("GameState.togglePause", plan["interfaces_to_reuse"])
        self.assertIn("InputManager.isPressed", plan["interfaces_to_reuse"])
        self.assertTrue(plan["tests_to_update_or_add"])
        behavior = next(node for node in plan["approved_change_nodes"] if node["current_owner"] == "InputManager")
        self.assertTrue(behavior["local_test_contract"])

    def test_every_active_requirement_has_explicit_coverage(self):
        plan = self.final_plan()
        statuses = {item["requirement_id"]: item["status"] for item in plan["coverage"]}
        self.assertEqual(set(statuses), {item["requirement_id"] for item in self.requirements})
        self.assertNotIn("UNASSIGNED", statuses.values())

    def test_unassigned_requirement_fails_plan_gate(self):
        plan = self.final_plan()
        broken = copy.deepcopy(plan)
        broken["coverage"][0]["status"] = "UNASSIGNED"
        broken = impact.finalize_plan_identity(broken)
        result = impact.validate_change_plan(broken, self.requirements, self.evidence)
        self.assertFalse(result["valid"])
        self.assertTrue(any("unassigned" in item for item in result["errors"]))

    def test_unresolved_blocking_challenge_fails_plan_gate(self):
        plan = self.final_plan()
        broken = copy.deepcopy(plan)
        broken["unresolved_challenges"] = [{"blocking": True, "challenge_type": "TEST_GAP"}]
        broken = impact.finalize_plan_identity(broken)
        self.assertFalse(impact.validate_change_plan(broken, self.requirements, self.evidence)["valid"])

    def test_each_plan_node_has_done_when_provenance_and_evidence(self):
        plan = self.final_plan()
        for node in plan["approved_change_nodes"]:
            self.assertTrue(node["done_when"])
            self.assertTrue(node["evidence_ids"])
            self.assertEqual(node["provenance"], impact.DERIVED_PLAN_DECISION)

    def test_minimal_effective_plan_keeps_all_three_required_responsibilities(self):
        plan = self.final_plan()
        kinds = {item["impact_kind"] for item in plan["approved_change_nodes"]}
        self.assertIn("BEHAVIOR_CHANGE", kinds)
        self.assertIn("INTEGRATION_CHANGE", kinds)
        self.assertIn("TEST_CHANGE", kinds)
        self.assertGreaterEqual(len(plan["approved_change_nodes"]), 3)

    def test_plan_identity_is_deterministic_and_content_changes_stale_approval(self):
        first = self.final_plan()
        second = self.final_plan()
        self.assertEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(first["plan_hash"], second["plan_hash"])
        approval = {
            "plan_id": first["plan_id"], "plan_hash": first["plan_hash"],
            "approval_status": "APPROVED",
        }
        self.assertTrue(impact.approval_is_current(first, approval))
        changed = copy.deepcopy(first)
        changed["integration_verification"].append("new acceptance")
        self.assertFalse(impact.approval_is_current(changed, approval))

    def test_arrow_key_plan_ui_uses_recommended_approve_without_numeric_typing(self):
        labels = mini.plan_approval_option_labels()
        self.assertTrue(labels[0].endswith("Recommended"))
        self.assertEqual(mini.navigate_plan_approval_options(["down", "up", "enter"]), 0)
        self.assertEqual(mini.navigate_plan_approval_options(["down", "down", "enter"]), 2)

    def test_noninteractive_existing_plan_returns_clean_approval_required_state(self):
        result = mini.prepare_stage3_context(
            self.understanding(), self.contract, interactive=False, terminal_available=False,
            planner_structured_call=lambda *_args: self.candidate_map(),
            challenger_structured_call=lambda *_args: {"challenges": []},
        )
        self.assertEqual(result["terminal_state"], mini.PLAN_APPROVAL_REQUIRED)
        self.assertEqual(result["status"], "plan_approval_required")
        self.assertNotEqual(result["status"], "failed")
        self.assertNotEqual(result["terminal_state"], "CLARIFICATION_REQUIRED")
        self.assertTrue(result["read_only"])

    def test_interactive_approval_enables_downstream_execution(self):
        calls = []
        result, _ = mini.run_recursive_request(
            self.contract["goal"], {}, contract_override=self.contract,
            repo_snapshot={}, understanding_override=self.understanding(),
            impact_planner_structured_call=lambda *_args: self.candidate_map(),
            impact_challenger_structured_call=lambda *_args: {"challenges": []},
            plan_approval_selector=lambda *_args, **_kwargs: 0,
            terminal_available=True, fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=lambda task, _contract, memory, _repo, _parent, _deps: (
                calls.append(task.get("approved_plan_hash"))
                or {"status": "done", "summary": "verified", "memory": memory}
            ),
            reset=True, finish=False,
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(calls, [mini.RUN["approved_change_plan"]["plan_hash"]])
        flow = mini.RUN["control_flow"]
        self.assertLess(flow.index("IMPACT_MAP"), flow.index("TASK_FIT"))
        self.assertLess(flow.index("USER_PLAN_APPROVAL"), flow.index("TASK_FIT"))

    def test_preapproved_auto_handoff_reuses_plan_without_replanning(self):
        plan = self.final_plan()
        approval = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "approval_status": "APPROVED"}
        mini.RUN.update({
            "impact_planning_required": True, "project_mode": mini.EXISTING_PROJECT,
            "approved_change_plan": plan, "plan_approval": approval,
        })
        result, _ = mini.run_recursive_request(
            self.contract["goal"], {}, contract_override=self.contract,
            repo_snapshot={}, understanding_override=self.understanding(),
            impact_planning_override={
                "status": "ready", "contract": self.contract,
                "plan": plan, "approval": approval,
            },
            fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=lambda task, _contract, memory, _repo, _parent, _deps: {
                "status": "done", "summary": task.get("approved_plan_id"), "memory": memory,
            },
            reset=False, finish=False,
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(result["summary"], plan["plan_id"])
        self.assertEqual(mini.RUN["impact_planner_calls"], 0)

    def test_plan_rejection_stops_before_worker_and_is_not_root_fail(self):
        calls = []
        result, _ = mini.run_recursive_request(
            self.contract["goal"], {}, contract_override=self.contract,
            repo_snapshot={}, understanding_override=self.understanding(),
            impact_planner_structured_call=lambda *_args: self.candidate_map(),
            impact_challenger_structured_call=lambda *_args: {"challenges": []},
            plan_approval_selector=lambda *_args, **_kwargs: 2,
            terminal_available=True,
            leaf_executor=lambda *_args: calls.append(True), reset=True, finish=False,
        )
        self.assertEqual(result["terminal_state"], mini.PLAN_REJECTED)
        self.assertEqual(calls, [])
        self.assertTrue(result["read_only"])

    def test_user_revision_adds_user_confirmed_requirement_without_overwriting_stated(self):
        original = [item["text"] for item in mini.ledger_requirements(
            self.contract["source_requirement_ledger"]
        )]
        updated, decision = mini.apply_plan_user_revision(
            self.contract, "Keep the existing input module public API unchanged.",
        )
        self.assertEqual(decision["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(
            [item["text"] for item in mini.ledger_requirements(updated["source_requirement_ledger"])],
            original,
        )
        confirmed = mini.ledger_requirements(updated["source_requirement_ledger"], include_confirmed=True)
        self.assertEqual(confirmed[-1]["provenance"], mini.USER_CONFIRMED)

    def test_decomposition_binding_assigns_every_approved_node_and_rejects_scope_expansion(self):
        plan = self.final_plan()
        bound = impact.bind_decomposition_to_plan([
            {"goal": "input behavior", "done_when": ["input done"], "scope_hint": ["src/input.js"]},
            {"goal": "pause and tests", "done_when": ["pause tested"], "scope_hint": ["src/game.js"]},
            {"goal": "unrelated theme", "done_when": ["theme"], "scope_hint": ["src/theme.js"]},
        ], plan)
        covered = {item for spec in bound["specs"] for item in spec["plan_node_ids"]}
        expected = {item["node_id"] for item in plan["approved_change_nodes"]}
        self.assertEqual(covered, expected)
        self.assertIn("src/theme.js", bound["scope_expansions"])

    def test_verification_only_responsibility_has_no_mutation_target(self):
        candidate = self.candidate_map(include_storage=False)
        candidate["impacts"][1]["impact_kind"] = "INTERFACE_REUSE"
        candidate["impacts"][1]["necessity_status"] = "CANDIDATE"
        plan = impact.build_minimal_change_plan(candidate, self.requirements, self.evidence)
        node = next(item for item in plan["approved_change_nodes"] if item["current_owner"] == "GameState")
        self.assertTrue(node["verification_only"])
        self.assertEqual(node["candidate_targets"], [])
        self.assertEqual(node["inspect_targets"], ["src/game.js"])

    def test_mission_node_contract_preserves_test_and_do_not_touch_responsibility(self):
        plan = self.final_plan()
        contract = impact.approved_plan_node_contract(plan, [
            item["node_id"] for item in plan["approved_change_nodes"]
        ])
        compact = mini._compact_approved_plan_node_contract(contract)
        encoded = json.dumps(compact)
        self.assertIn("local_test_contract", compact)
        self.assertIn("src/storage.js", encoded)
        self.assertNotIn("candidate_impact_map", encoded)
        self.assertNotIn("task_brain", encoded)

    def test_mission_compiler_receives_only_bounded_approved_node_contract(self):
        plan = self.final_plan()
        contract = impact.approved_plan_node_contract(plan)
        prompts = []

        def compile_call(prompt, *_args):
            prompts.append(prompt)
            return {
                "goal_anchor": "root", "task": "node", "expected_outcome": "verified",
                "targets": ["src/input.js"], "existing_facts": ["InputManager owns input"],
                "implementation_plan": ["extend current input owner"],
                "interfaces_to_reuse": ["InputManager.isPressed", "GameState.togglePause"],
                "invariants": ["preserve current state ownership"],
                "project_specific_quality_rules": [], "do_not": ["edit src/storage.js"],
                "verification_plan": ["run pause/input tests"], "done_when": ["tests pass"],
            }

        task = mini.make_task("1", "Add Escape handling", 1, "ROOT", ["tests pass"], ["src/input.js"])
        mission = mini.compile_worker_mission(
            task, {"root_goal_anchor": "pause task"}, structured_call=compile_call,
            plan_node_contract=contract,
        )
        self.assertIn("APPROVED_PLAN", prompts[0].upper().replace(" ", "_"))
        self.assertIn("approved_plan_node_contract", mission)
        self.assertIn("local_test_contract", mission["approved_plan_node_contract"])
        self.assertNotIn("candidate_impact_map", json.dumps(mission))
        self.assertLessEqual(len(json.dumps(mission)), mini.MAX_WORKER_MISSION_CHARS)

    def test_decomposition_receives_plan_hash_and_projects_plan_nodes_to_children(self):
        plan = self.final_plan()
        approval = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "approval_status": "APPROVED"}
        mini.RUN.update({
            "impact_planning_required": True, "project_mode": mini.EXISTING_PROJECT,
            "approved_change_plan": plan, "plan_approval": approval, "tasks_created": 1,
        })
        root = mini.attach_approved_plan_to_task(mini.root_task_from_contract(self.contract), plan)
        mini.TASKS = {"ROOT": root}
        prompts = []
        response = {"children": [
            {"goal": "input behavior", "done_when": ["input done"], "scope_hint": ["src/input.js"]},
            {"goal": "pause integration and tests", "done_when": ["tested"], "scope_hint": ["src/game.js"]},
        ]}

        def structured(prompt, *_args):
            prompts.append(prompt)
            return response

        original = mini.structured_model_call
        mini.structured_model_call = structured
        try:
            children = mini.decompose_task(root, self.contract, {"files": []})
        finally:
            mini.structured_model_call = original
        covered = {item for child in children for item in child.get("plan_node_ids", [])}
        self.assertIn(plan["plan_hash"], prompts[0])
        self.assertEqual(covered, {item["node_id"] for item in plan["approved_change_nodes"]})
        self.assertTrue(all(child.get("approved_plan_hash") == plan["plan_hash"] for child in children))

    def test_user_revision_is_bounded_replanned_and_reapproved_read_only(self):
        selections = iter([1, 0])

        # The reviser closure needs the updated contract. Capture it from the
        # prompt's structured Source Requirement IDs instead of repository data.
        def reviser(prompt, *_args):
            candidate = copy.deepcopy(self.candidate_map())
            ids = sorted(set(__import__("re").findall(r"REQ-\d+", prompt)))
            candidate["impacts"][0]["requirement_ids"] = list(dict.fromkeys(
                candidate["impacts"][0]["requirement_ids"] + ids
            ))
            candidate["impacts"][0]["preserve"].append("existing input module public API")
            return candidate

        result = mini.prepare_stage3_context(
            self.understanding(), self.contract, interactive=True, terminal_available=True,
            planner_structured_call=lambda *_args: self.candidate_map(),
            challenger_structured_call=lambda *_args: {"challenges": []},
            reviser_structured_call=reviser,
            approval_selector=lambda *_args, **_kwargs: next(selections),
            approval_answer_reader=lambda *_args: "Keep the existing input module public API unchanged.",
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(mini.RUN["impact_plan_revision_calls"], 1)
        self.assertEqual(mini.RUN["plan_approval_requests"], 2)
        self.assertEqual(mini.RUN["plan_user_revision"]["provenance"], mini.USER_CONFIRMED)
        self.assertTrue(result["read_only"])

    def test_plan_gate_rejects_unresolved_duplicate_owner(self):
        plan = self.final_plan()
        broken = copy.deepcopy(plan)
        node = broken["approved_change_nodes"][0]
        node["goal"] = "Add a paused field to InputManager."
        node["current_owner"] = "InputManager"
        node["evidence_ids"] = ["REPO-004"]
        broken = impact.finalize_plan_identity(broken)
        result = impact.validate_change_plan(broken, self.requirements, self.evidence)
        self.assertFalse(result["valid"])
        self.assertTrue(any("ownership conflict" in item for item in result["errors"]))

    def test_normal_challenger_cannot_run_a_second_debate_round(self):
        mini.challenge_impact_map(
            self.candidate_map(), self.task_brain, self.contract, self.evidence,
            structured_call=lambda *_args: {"challenges": []},
        )
        with self.assertRaises(mini.ImpactPlanningError):
            mini.challenge_impact_map(
                self.candidate_map(), self.task_brain, self.contract, self.evidence,
                structured_call=lambda *_args: {"challenges": []},
            )

    def test_worker_mutation_guard_rejects_unapproved_and_do_not_touch_paths(self):
        for path in ("src/input.js", "src/storage.js", "src/theme.js"):
            target = mini.WORKSPACE / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("old\n", encoding="utf-8")
        plan = self.final_plan()
        approval = {"plan_id": plan["plan_id"], "plan_hash": plan["plan_hash"], "approval_status": "APPROVED"}
        mini.RUN.update({
            "impact_planning_required": True, "project_mode": mini.EXISTING_PROJECT,
            "approved_change_plan": plan, "plan_approval": approval,
        })
        task = mini.attach_approved_plan_to_task(mini.root_task_from_contract(self.contract), plan)
        mini.ACTIVE_TOOL_CONTRACT = mini._active_plan_tool_contract_fields(task)
        storage = mini.run_tool("edit_file", {"path": "src/storage.js", "old": "old", "new": "new"}, role="Builder")
        theme = mini.run_tool("edit_file", {"path": "src/theme.js", "old": "old", "new": "new"}, role="Builder")
        self.assertIn(mini.UNAPPROVED_SCOPE_EXPANSION, storage)
        self.assertIn(mini.UNAPPROVED_SCOPE_EXPANSION, theme)
        self.assertEqual((mini.WORKSPACE / "src/storage.js").read_text(encoding="utf-8"), "old\n")

    def test_worker_mutation_guard_requires_current_approval_hash(self):
        plan = self.final_plan()
        mini.RUN.update({
            "impact_planning_required": True, "project_mode": mini.EXISTING_PROJECT,
            "approved_change_plan": plan,
            "plan_approval": {"plan_id": plan["plan_id"], "plan_hash": "stale", "approval_status": "APPROVED"},
        })
        mini.ACTIVE_TOOL_CONTRACT = {"approved_plan_hash": plan["plan_hash"]}
        result = mini.run_tool("write_file", {"path": "src/input.js", "content": "x"}, role="Builder")
        self.assertIn(mini.PLAN_APPROVAL_REQUIRED, result)
        self.assertFalse((mini.WORKSPACE / "src/input.js").exists())

    def test_new_project_flow_skips_repository_approval_without_planner_calls(self):
        result = mini.prepare_stage3_context(
            {"project_mode": mini.NEW_PROJECT}, self.contract,
            interactive=False, terminal_available=False,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(mini.RUN["impact_planner_calls"], 0)
        self.assertIn("IMPACT_PLANNING_SKIPPED_GREENFIELD", mini.RUN["control_flow"])

    def test_role_metrics_account_for_one_planner_one_challenger_and_approval(self):
        result = mini.prepare_stage3_context(
            self.understanding(), self.contract, interactive=True, terminal_available=True,
            planner_structured_call=lambda *_args: self.candidate_map(),
            challenger_structured_call=lambda *_args: {"challenges": []},
            approval_selector=lambda *_args, **_kwargs: 0,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(mini.RUN["impact_planner_calls"], 1)
        self.assertEqual(mini.RUN["impact_challenger_calls"], 1)
        self.assertEqual(mini.RUN["impact_plan_revision_calls"], 0)
        self.assertEqual(mini.RUN["plan_approval_requests"], 1)
        self.assertEqual(mini.RUN["model_calls"], 0)  # all role calls were injected mocks

    def test_baseline_has_no_recursive_stage3_worker_context(self):
        mini.reset_run("baseline")
        self.assertIsNone(mini.current_approved_change_plan())
        self.assertFalse(mini.RUN.get("impact_planning_required", False))
        self.assertEqual(mini.RUN["impact_planner_calls"], 0)


if __name__ == "__main__":
    unittest.main()
