import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import project_understanding as understanding


def empty_specification(goal):
    result = {field: [] for field in mini._PROJECT_SPECIFICATION_FIELDS}
    result["root_goal"] = goal
    result["acceptance_criteria"] = ["the requested behavior is verified"]
    return result


class ProjectUnderstandingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "gemma4:e4b"
        mini.reset_run("recursive")

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    @staticmethod
    def contract(raw):
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        contract = mini.normalize_goal_contract(
            raw, mini._deterministic_contract_from_ledger(raw, ledger),
            source_ledger=ledger, confirmed=[], derived=[],
            clarification_questions=[], clarification_answers=[],
        )
        contract["source_contract"] = mini.source_contract_from_ledger(raw, ledger)
        return contract

    def write_pause_fixture(self):
        src = mini.WORKSPACE / "src"
        tests = mini.WORKSPACE / "tests"
        src.mkdir()
        tests.mkdir()
        (src / "input.js").write_text(
            """export class InputManager {
  // InputManager owns keyboard state.
  handleKeyboard(key) { return key === 'Escape'; }
}
""", encoding="utf-8")
        (src / "game.js").write_text(
            """export class GameState {
  constructor() { this.paused = false; }
  togglePause() { this.paused = !this.paused; }
}
""", encoding="utf-8")
        (src / "storage.js").write_text(
            "export const BEST_SCORE_KEY = 'best-score';\n" + ("// unrelated storage implementation\n" * 200),
            encoding="utf-8",
        )
        (tests / "input.test.js").write_text(
            """describe('pause keyboard', () => {
  it('uses Escape', () => expect(new InputManager().handleKeyboard('Escape')).toBe(true));
});
""", encoding="utf-8")

    def write_auth_fixture(self):
        src = mini.WORKSPACE / "src"
        src.mkdir(exist_ok=True)
        (src / "legacy-auth.js").write_text(
            """export function legacyAuthCallback(request) {
  // Legacy auth owns SSO callback handling and session completion.
  return completeSsoCallback(request);
}
""", encoding="utf-8")

    def pause_recon(self):
        raw = "Change pause keyboard behavior.\n- Escape toggles pause."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"], use_model_scout=False,
        )
        return raw, contract, classification, recon

    def test_empty_and_explicit_greenfield_workspaces_are_new_projects(self):
        first = mini.classify_project_mode("Create a todo app")
        second = mini.classify_project_mode("Build a game from scratch")
        self.assertEqual(first["project_mode"], mini.NEW_PROJECT)
        self.assertEqual(second["project_mode"], mini.NEW_PROJECT)
        self.assertEqual(first["inventory"]["status"], mini.REPOSITORY_EMPTY)

    def test_existing_source_tree_and_missing_modification_target_classify_existing(self):
        (mini.WORKSPACE / "app.py").write_text("def main():\n    return True\n", encoding="utf-8")
        present = mini.classify_project_mode("Add dark mode")
        (mini.WORKSPACE / "app.py").unlink()
        missing = mini.classify_project_mode("Modify the existing SettingsService")
        self.assertEqual(present["project_mode"], mini.EXISTING_PROJECT)
        self.assertEqual(missing["project_mode"], mini.EXISTING_PROJECT)

    def test_targeted_recon_is_read_only_and_search_precedes_candidate_reads(self):
        self.write_pause_fixture()
        _raw, _contract, classification, recon = self.pause_recon()
        operations = recon["operations"]
        first_read = next(index for index, item in enumerate(operations) if item["operation"] == "READ")
        search_indexes = [index for index, item in enumerate(operations) if item["operation"] == "SEARCH"]
        self.assertEqual(classification["project_mode"], mini.EXISTING_PROJECT)
        self.assertEqual(recon["status"], mini.REPOSITORY_RECONNAISSANCE_COMPLETE)
        self.assertTrue(recon["read_only"])
        self.assertEqual(recon["mutations_detected"], [])
        self.assertTrue(search_indexes)
        self.assertLess(max(search_indexes), first_read)
        self.assertLessEqual(recon["files_inspected"], mini.MAX_TARGETED_RECON_FILES)
        self.assertLessEqual(recon["snippets"], mini.MAX_RECON_SNIPPETS)

    def test_pause_recon_discovers_owner_interface_state_owner_and_test(self):
        self.write_pause_fixture()
        _raw, _contract, _classification, recon = self.pause_recon()
        evidence = recon["evidence"]
        encoded = json.dumps(evidence, ensure_ascii=False)
        categories = {item["category"] for item in evidence}
        paths = {item["path"] for item in evidence}
        self.assertIn("CURRENT_OWNER", categories)
        self.assertIn("CURRENT_INTERFACE", categories)
        self.assertIn("CURRENT_STATE_OWNER", categories)
        self.assertIn("CURRENT_TEST", categories)
        self.assertIn("InputManager", encoded)
        self.assertIn("src/input.js", paths)
        self.assertIn("src/game.js", paths)
        self.assertIn("tests/input.test.js", paths)

    def test_irrelevant_storage_area_is_not_read_or_injected(self):
        self.write_pause_fixture()
        _raw, _contract, _classification, recon = self.pause_recon()
        read_paths = {
            item["path"] for item in recon["operations"] if item.get("operation") == "READ"
        }
        encoded = json.dumps(recon["evidence"], ensure_ascii=False)
        self.assertNotIn("src/storage.js", read_paths)
        self.assertNotIn("unrelated storage implementation", encoded)

    def test_repository_evidence_requires_direct_source_support(self):
        self.write_pause_fixture()
        _raw, _contract, _classification, recon = self.pause_recon()
        self.assertTrue(recon["evidence"])
        self.assertTrue(all(understanding.validate_repository_evidence(item) for item in recon["evidence"]))
        self.assertEqual(
            [item["evidence_id"] for item in recon["evidence"]],
            [f"REPO-{index:03d}" for index in range(1, len(recon["evidence"]) + 1)],
        )
        model_guess = {
            "evidence_id": "REPO-999", "category": "CURRENT_OWNER",
            "fact": "InputManager probably owns input", "path": "src/input.js",
            "evidence_type": understanding.DIRECT_OBSERVATION,
            "provenance": understanding.REPOSITORY_EVIDENCE,
        }
        self.assertFalse(understanding.validate_repository_evidence(model_guess))

    def test_real_repository_conflict_requires_source_and_evidence_ids(self):
        self.write_auth_fixture()
        raw = "Remove legacy auth while preserving SSO."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"],
            structured_call=lambda *_args: {"paths": ["src/legacy-auth.js"]},
        )
        clarification = mini.repository_grounded_clarification(raw, contract, recon)
        question = clarification["questions"][0]
        self.assertEqual(question["phase"], "REPOSITORY_GROUNDED_CLARIFICATION")
        self.assertTrue(question["affected_requirement_ids"])
        self.assertTrue(question["repository_evidence_ids"])
        invalid = dict(question, repository_evidence_ids=[])
        self.assertFalse(understanding.validate_repository_question(
            invalid, question["affected_requirement_ids"],
            {item["evidence_id"] for item in recon["evidence"]},
        ))

    def test_unrelated_repository_complexity_does_not_create_a_question(self):
        self.write_auth_fixture()
        raw = "Change button text."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"],
            structured_call=lambda *_args: {"paths": ["src/legacy-auth.js"]},
        )
        clarification = mini.repository_grounded_clarification(raw, contract, recon)
        self.assertEqual(clarification["questions"], [])

    def test_missing_task_named_interface_is_recorded_without_hallucinating_it(self):
        (mini.WORKSPACE / "settings.py").write_text(
            "def load_settings():\n    return {}\n", encoding="utf-8",
        )
        raw = "Modify the existing SettingsService to cache settings."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"],
            structured_call=lambda *_args: {"paths": ["settings.py"]},
        )
        discrepancy = [
            item for item in recon["evidence"] if item.get("symbol") == "SettingsService"
        ]
        self.assertEqual(len(discrepancy), 1)
        self.assertIn("was not found", discrepancy[0]["fact"])
        self.assertNotIn(
            "SettingsService is an observed", json.dumps(recon["evidence"], ensure_ascii=False),
        )
        clarification = mini.repository_grounded_clarification(raw, contract, recon)
        self.assertEqual(len(clarification["questions"]), 1)
        self.assertEqual(
            clarification["questions"][0]["repository_evidence_ids"],
            [discrepancy[0]["evidence_id"]],
        )

    def test_noninteractive_repo_conflict_returns_clarification_required_not_root_fail(self):
        self.write_auth_fixture()
        raw = "Remove legacy auth while preserving SSO."
        contract = self.contract(raw)
        result = mini.prepare_stage2_context(
            raw, contract, repo_snapshot=mini.inspect_repository(), interactive=False,
            supplied_contract=True, specification_override=empty_specification(contract["goal"]),
            recon_structured_call=lambda *_args: {"paths": ["src/legacy-auth.js"]},
            terminal_available=False,
        )
        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(result["terminal_state"], "CLARIFICATION_REQUIRED")
        self.assertEqual(result["phase"], "REPOSITORY_GROUNDED_CLARIFICATION")
        self.assertNotEqual(result.get("failure_type"), "IMPLEMENTATION_ERROR")
        self.assertNotIn("ROOT", mini.TASKS)

    def test_repo_answer_is_user_confirmed_without_rewriting_user_stated_requirement(self):
        self.write_auth_fixture()
        raw = "Remove legacy auth while preserving SSO."
        contract = self.contract(raw)
        stated_before = copy.deepcopy(mini.ledger_requirements(contract["source_requirement_ledger"]))
        result = mini.prepare_stage2_context(
            raw, contract, repo_snapshot=mini.inspect_repository(), interactive=True,
            supplied_contract=True, specification_override=empty_specification(contract["goal"]),
            recon_structured_call=lambda *_args: {"paths": ["src/legacy-auth.js"]},
            terminal_available=True, selector=lambda *_args, **_kwargs: 0,
        )
        self.assertEqual(result["status"], "ready")
        answer = result["contract"]["repository_clarification_answers"][0]
        self.assertEqual(answer["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(answer["phase"], "REPOSITORY_GROUNDED_CLARIFICATION")
        self.assertTrue(answer["repository_evidence_ids"])
        self.assertEqual(
            mini.ledger_requirements(contract["source_requirement_ledger"]), stated_before,
        )
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in stated_before))

    def test_existing_specifier_receives_bounded_current_observed_summary(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        summary = understanding.bounded_repository_summary(recon, mini.EXISTING_PROJECT)
        prompts = []
        mini.expand_project_specification(
            raw, contract,
            structured_call=lambda prompt, *_args: prompts.append(prompt) or empty_specification(contract["goal"]),
            repository_summary=summary,
        )
        self.assertIn("CURRENT OBSERVED REPOSITORY FACTS", prompts[0])
        self.assertIn("CURRENT_OBSERVED_REPOSITORY_STATE", prompts[0])
        self.assertIn("PROPOSED / DERIVED", prompts[0])
        self.assertLessEqual(len(summary), 4200)

    def test_existing_flow_prepares_recon_and_task_brain_before_task_fit(self):
        self.write_pause_fixture()
        raw = "Change pause keyboard behavior.\n- Escape toggles pause."
        contract = self.contract(raw)
        result, _ = mini.run_recursive_request(
            raw, {}, contract_override=contract, repo_snapshot=mini.inspect_repository(),
            fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=lambda _task, _contract, memory, _repo, _parent, _deps: {
                "status": "done", "summary": "verified", "memory": memory,
            },
            reset=True, finish=False,
            specification_override=empty_specification(contract["goal"]),
        )
        flow = mini.RUN["control_flow"]
        self.assertEqual(result["status"], "done")
        self.assertLess(flow.index("REPOSITORY_RECONNAISSANCE"), flow.index("SPECIFICATION_EXPANSION"))
        self.assertLess(flow.index("SPECIFICATION_EXPANSION"), flow.index("PROJECT_BRAIN"))
        self.assertLess(flow.index("PROJECT_BRAIN"), flow.index("TASK_BRAIN"))
        self.assertLess(flow.index("TASK_BRAIN"), flow.index("TASK_FIT"))

    def test_new_project_skips_recon_and_still_creates_one_task_brain(self):
        raw = "Build a browser game from scratch.\n" + "\n".join(
            f"- requirement {index}" for index in range(1, 48)
        )
        contract = self.contract(raw)
        result = mini.prepare_stage2_context(
            raw, contract, repo_snapshot={}, interactive=False, supplied_contract=True,
            specification_override=empty_specification(contract["goal"]),
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["project_mode"], mini.NEW_PROJECT)
        self.assertEqual(result["reconnaissance"]["status"], mini.REPOSITORY_EMPTY)
        self.assertEqual(mini.RUN["repository_reconnaissance_runs"], 0)
        self.assertEqual(mini.RUN["repository_reconnaissance_skipped"], 1)
        self.assertEqual(mini.RUN["repo_grounded_clarification_questions"], 0)
        self.assertEqual(mini.RUN["task_brains_created"], 1)
        self.assertEqual(len(result["task_brain"]["source_requirement_ids"]), 47)
        self.assertEqual(result["task_brain"]["repository_evidence_ids"], [])

    def test_task_brain_contains_relevant_pause_evidence_not_storage_body(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        projection = mini.build_brain_projection(
            brain, mini.root_task_from_contract(contract), repo_snapshot={}, record=False,
        )
        task_brain = understanding.build_task_brain(
            "ROOT", raw, mini.EXISTING_PROJECT, contract, projection, recon["evidence"], [],
        )
        encoded = json.dumps(task_brain, ensure_ascii=False)
        self.assertIn("InputManager", encoded)
        self.assertIn("src/game.js", encoded)
        self.assertIn("tests/input.test.js", encoded)
        self.assertNotIn("unrelated storage implementation", encoded)
        self.assertNotIn("support", task_brain["evidence_index"][0])

    def test_task_brain_provenance_classes_remain_distinct(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        contract["user_confirmed_requirements"] = [{
            "answer": "Use Escape", "provenance": mini.USER_CONFIRMED,
            "affected_requirement_ids": ["REQ-001"], "decision_id": "DEC-001",
        }]
        contract["derived_assumptions"] = [{"text": "Reuse current event dispatch", "provenance": mini.DERIVED}]
        specification = empty_specification(contract["goal"])
        specification["architecture_invariants"] = ["preserve one keyboard owner"]
        brain = mini.build_project_brain(
            contract, specification, mini.inspect_repository(), repository_evidence=recon["evidence"],
        )
        projection = mini.build_brain_projection(
            brain, mini.root_task_from_contract(contract), repo_snapshot={}, record=False,
        )
        task_brain = understanding.build_task_brain(
            "ROOT", raw, mini.EXISTING_PROJECT, contract, projection, recon["evidence"], [],
        )
        self.assertEqual(task_brain["task_goal"]["provenance"], mini.USER_STATED)
        self.assertEqual(task_brain["user_confirmed_decisions"][0]["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(
            task_brain["relevant_project_brain_projection"][0]["provenance"], mini.PROJECT_BRAIN,
        )
        self.assertEqual(task_brain["current_owners"][0]["provenance"], mini.REPOSITORY_EVIDENCE)
        self.assertEqual(
            task_brain["derived_task_assumptions"][0]["provenance"],
            mini.DERIVED_TASK_ASSUMPTION,
        )

    def test_task_brain_is_bounded_and_rejects_transcript_or_unknown_evidence(self):
        raw = "Create a tool.\n- verify it"
        contract = self.contract(raw)
        brain = understanding.build_task_brain(
            "ROOT", raw, mini.NEW_PROJECT, contract, {}, [], [],
        )
        valid_ids = [item["requirement_id"] for item in mini.ledger_requirements(contract["source_requirement_ledger"])]
        valid = understanding.validate_task_brain(brain, valid_ids, [])
        self.assertTrue(valid["valid"], valid["errors"])
        self.assertLessEqual(valid["serialized_chars"], mini.MAX_TASK_BRAIN_CHARS)
        leaked = copy.deepcopy(brain)
        leaked["raw_conversation"] = ["secret chat log"]
        self.assertFalse(understanding.validate_task_brain(leaked, valid_ids, [])["valid"])
        bad_reference = copy.deepcopy(brain)
        bad_reference["repository_evidence_ids"] = ["REPO-999"]
        self.assertFalse(understanding.validate_task_brain(bad_reference, valid_ids, [])["valid"])

    def test_task_brain_does_not_mutate_or_promote_into_project_brain(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        core_before = json.dumps(brain["core"], ensure_ascii=False, sort_keys=True)
        projection = mini.build_brain_projection(
            brain, mini.root_task_from_contract(contract), repo_snapshot={}, record=False,
        )
        task_brain = understanding.build_task_brain(
            "ROOT", raw, mini.EXISTING_PROJECT, contract, projection, recon["evidence"], [],
        )
        self.assertEqual(json.dumps(brain["core"], ensure_ascii=False, sort_keys=True), core_before)
        self.assertNotIn("task_brain", brain)
        self.assertNotIn("derived_task_assumptions", json.dumps(brain["core"], ensure_ascii=False))
        self.assertIsInstance(task_brain, dict)

    def test_verified_project_state_accepts_only_direct_repository_evidence(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        guess = {
            "evidence_id": "REPO-999", "category": "CURRENT_OWNER", "path": "fake.js",
            "fact": "probably an owner", "provenance": mini.REPOSITORY_EVIDENCE,
            "evidence_type": understanding.DIRECT_OBSERVATION,
        }
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"] + [guess],
        )
        encoded = json.dumps(brain["verified_state"], ensure_ascii=False)
        self.assertIn("REPO-001", encoded)
        self.assertNotIn("REPO-999", encoded)
        self.assertEqual(brain["verified_state"]["provenance"], mini.VERIFIED)
        mini.RUN["project_brain"] = brain
        mini.RUN.pop("repository_evidence", None)
        mini.refresh_project_brain_verified_state(mini.inspect_repository())
        self.assertIn("REPO-001", json.dumps(brain["verified_state"], ensure_ascii=False))

    def test_downstream_planning_receives_bounded_task_slice_not_full_ledgers_or_files(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        mini.RUN["project_brain"] = brain
        mini.create_task_brain(
            "ROOT", raw, contract, brain, mini.EXISTING_PROJECT,
            repository_evidence=recon["evidence"], open_questions=[],
        )
        task = mini.root_task_from_contract(contract)
        packet = mini.project_brain_task_planning_packet(task, repo_snapshot={}, max_chars=4200)
        self.assertIn("task_brain_slice", packet)
        self.assertIn("project_brain_projection", packet)
        self.assertNotIn("source_requirement_ledger", packet)
        self.assertNotIn("unrelated storage implementation", packet)
        self.assertLessEqual(len(packet), 4200)

    def test_worker_receives_task_brain_only_through_bounded_mission_compiler_slice(self):
        self.write_pause_fixture()
        raw, contract, _classification, recon = self.pause_recon()
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        mini.RUN["project_brain"] = brain
        task_brain = mini.create_task_brain(
            "ROOT", raw, contract, brain, mini.EXISTING_PROJECT,
            repository_evidence=recon["evidence"], open_questions=[],
        )
        task = mini.make_task("pause", "Implement pause keyboard handling", 1, "ROOT", ["pause verified"], [])
        mission = {
            "goal_anchor": contract["goal"], "task": task["goal"], "expected_outcome": "pause verified",
            "targets": ["src/input.js"], "existing_facts": [], "implementation_plan": ["reuse owner"],
            "interfaces_to_reuse": [], "invariants": [], "project_specific_quality_rules": [],
            "do_not": [], "verification_plan": ["run input test"], "done_when": ["pause verified"],
        }
        with patch.object(mini, "compile_worker_mission", return_value=mission) as compiler:
            mini.prepare_worker_mission_context(task, contract, mini.inspect_repository())
        task_context = compiler.call_args.kwargs["task_context"]
        self.assertLessEqual(len(json.dumps(task_context)), mini.MAX_TASK_BRAIN_PROJECTION_CHARS)
        self.assertNotEqual(task_context, task_brain)
        self.assertNotIn("evidence_index", task_context)

    def test_metrics_account_for_recon_task_brain_and_mocked_recon_agent_role(self):
        self.write_auth_fixture()
        raw = "Update authentication behavior."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"],
            structured_call=lambda *_args: {"paths": ["src/legacy-auth.js"]},
        )
        brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        mini.create_task_brain(
            "ROOT", raw, contract, brain, mini.EXISTING_PROJECT,
            repository_evidence=recon["evidence"], open_questions=[],
        )
        self.assertEqual(mini.RUN["repository_reconnaissance_runs"], 1)
        self.assertGreater(mini.RUN["repository_searches"], 0)
        self.assertGreater(mini.RUN["repository_files_considered"], 0)
        self.assertGreater(mini.RUN["repository_files_inspected"], 0)
        self.assertEqual(mini.RUN["repository_evidence_records"], len(recon["evidence"]))
        self.assertEqual(mini.RUN["recon_agent_calls"], 1)
        self.assertEqual(mini.RUN["task_brains_created"], 1)
        self.assertEqual(mini.RUN["task_brain_compiler_calls"], 0)

    def test_baseline_keeps_task_brain_architecture_out_of_worker_execution(self):
        raw = "Create one focused file."
        contract = self.contract(raw)
        seen = []

        def leaf(_task, _contract, memory, _repo, _parent, _deps):
            seen.append(mini.RUN.get("project_brain"))
            return {"status": "done", "summary": "verified", "memory": memory}

        result, _ = mini.run_baseline_request(
            raw, {}, contract_override=contract, repo_snapshot={}, leaf_executor=leaf,
            reset=True, finish=False,
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(seen, [None])
        self.assertNotIn("task_brain", mini.RUN)
        self.assertEqual(mini.RUN["baseline_stage2_scope"], "PROJECT_MODE_BOOKKEEPING_ONLY")

    def test_frozen_limits_and_game_bridge_contract_remain_unchanged(self):
        self.assertEqual(mini.MODEL, "gemma4:e4b")
        self.assertEqual(mini.MAX_TOOL_STEPS, 28)
        self.assertEqual(mini.MAX_DEPTH, 6)
        self.assertEqual(mini.MAX_REPAIRS_PER_LEAF, 2)
        self.assertEqual(mini.MAX_STRATEGY_ALTERNATIVES, 2)
        self.assertEqual(mini.GAME_BRIDGE_EXPRESSION, "window.AGENT_GAME")
        self.assertEqual(mini.GAME_BRIDGE_NAME, "AGENT_GAME")
        for method in (
            "getState()", "start()", "restart()", "move(direction)",
            "forceCollision", "forceCollect", "forceWin",
        ):
            self.assertIn(method, mini.SYSTEM_PROMPT)
        self.assertNotIn("window.__AGENT_GAME__", mini.SYSTEM_PROMPT)


if __name__ == "__main__":
    unittest.main()
