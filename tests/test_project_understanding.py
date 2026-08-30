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

    def write_controlled_fixture(self):
        """Small deterministic existing project used by the v17.2 evidence tests."""
        src = mini.WORKSPACE / "src"
        tests = mini.WORKSPACE / "tests"
        src.mkdir(parents=True, exist_ok=True)
        tests.mkdir(parents=True, exist_ok=True)
        (src / "input.js").write_text(
            """export class InputManager {
  constructor() {
    this.keys = new Set();
  }
  onKeyDown(event) {
    const key = event.key;
    if (["ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight", "w", "a", "s", "d"].includes(key)) {
      this.keys.add(key);
    }
  }
  isPressed(key) {
    return this.keys.has(key);
  }
}
""",
            encoding="utf-8",
        )
        (src / "game.js").write_text(
            """export class GameState {
  constructor() {
    this.paused = false;
    this.score = 0;
  }
  togglePause() {
    this.paused = !this.paused;
  }
  addScore(points) {
    this.score += points;
  }
}
""",
            encoding="utf-8",
        )
        (src / "storage.js").write_text(
            """const BEST_SCORE_KEY = "existing-game.best-score";
export function loadBestScore(storage = localStorage) {
  return Number(storage.getItem(BEST_SCORE_KEY) || 0);
}
export function saveBestScore(score, storage = localStorage) {
  storage.setItem(BEST_SCORE_KEY, String(score));
}
""",
            encoding="utf-8",
        )
        (tests / "input.test.js").write_text(
            """import { InputManager } from "../src/input.js";
describe("keyboard input", () => {
  it("keeps arrow controls", () => {
    const input = new InputManager();
    expect(input.isPressed("ArrowUp")).toBe(false);
  });
});
""",
            encoding="utf-8",
        )
        (mini.WORKSPACE / "index.html").write_text(
            """<!doctype html>
<html><body>
  <script type="module" src="src/input.js"></script>
  <script type="module" src="src/game.js"></script>
  <script type="module" src="src/storage.js"></script>
</body></html>
""",
            encoding="utf-8",
        )

    @staticmethod
    def controlled_task():
        return (
            "Add Escape-key pause/resume support to the existing game. Reuse the current input and "
            "pause-state architecture instead of creating duplicate input state or another game-state owner. "
            "Preserve the current WASD/arrow controls and persistent best-score behavior. "
            "Update or add the relevant tests."
        )

    def controlled_recon(self):
        self.write_controlled_fixture()
        raw = self.controlled_task()
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        contract = self.contract(raw)
        inventory = understanding.inventory_repository(mini.WORKSPACE)
        recon = understanding.run_repository_reconnaissance(
            mini.WORKSPACE, raw, mini.ledger_requirements(ledger), inventory=inventory,
        )
        return raw, ledger, contract, inventory, recon

    def pause_recon(self):
        raw = "Change pause keyboard behavior.\n- Escape toggles pause."
        contract = self.contract(raw)
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, contract, inventory=classification["inventory"], use_model_scout=False,
        )
        return raw, contract, classification, recon

    def test_task_grounded_search_vocabulary_is_bounded_and_semantic(self):
        raw = self.controlled_task()
        terms = understanding.repository_search_terms(raw)
        self.assertLessEqual(len(terms), understanding.MAX_RECON_SEARCHES)
        self.assertIn("WASD", terms)
        self.assertIn("tests", terms)
        self.assertTrue(any("pause" in item.casefold() for item in terms))
        self.assertTrue(any("state" in item.casefold() for item in terms))
        self.assertTrue(any("score" in item.casefold() for item in terms))
        self.assertTrue(any("input" in item.casefold() for item in terms))
        self.assertNotIn("Reuse", terms)
        self.assertNotIn("Preserve", terms)
        self.assertNotIn("Update", terms)
        self.assertNotIn("InputManager", terms)
        self.assertEqual(
            understanding._search_term_variants("pause-state"),
            ["pause-state", "pause state", "pause", "state"],
        )

    def test_compound_source_requirements_preserve_all_explicit_constraints(self):
        raw = self.controlled_task()
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        records = mini.ledger_requirements(ledger)
        text = " ".join(item.get("text", "") for item in records)
        self.assertEqual(ledger.get("immutable"), True)
        self.assertEqual(sum([
            "Escape-key pause/resume" in text,
            "current input" in text and "architecture" in text,
            "pause-state architecture" in text,
            "duplicate input state" in text,
            "another game-state owner" in text,
            "WASD/arrow controls" in text,
            "persistent best-score behavior" in text,
            "relevant tests" in text,
        ]), 8)
        self.assertTrue(all(item.get("provenance") == mini.USER_STATED for item in records))
        self.assertTrue(all(item.get("source_segments") == [1] for item in records))

    def test_equivalent_compound_reuse_and_preservation_constraints_stay_user_stated(self):
        examples = (
            "Reuse the current authentication service instead of creating another token owner.",
            "Preserve the existing API contract while replacing the storage layer.",
            "Keep the current router and extend it rather than adding a second routing system.",
            "Use the existing cache implementation and do not introduce another cache owner.",
            "Replace X while preserving Y.",
        )
        for raw in examples:
            records = mini.ledger_requirements(mini.extract_source_requirement_ledger(raw, use_model=False))
            self.assertTrue(records, raw)
            text = " ".join(item.get("text", "") for item in records)
            self.assertIn(raw.split(".")[0], text)
            self.assertTrue(all(item.get("provenance") == mini.USER_STATED for item in records))
            self.assertTrue(all(item.get("source_segments") == [1] for item in records))

    def test_descriptive_or_repository_observation_is_not_promoted_as_user_constraint(self):
        descriptive = mini.ledger_requirements(
            mini.extract_source_requirement_ledger("This makes the UI easier to understand.", use_model=False)
        )
        observation = mini.ledger_requirements(
            mini.extract_source_requirement_ledger("The project currently uses React.", use_model=False)
        )
        self.assertFalse(descriptive)
        self.assertFalse(observation)

    def test_controlled_recon_extracts_owner_state_interfaces_persistence_and_test(self):
        _raw, _ledger, _contract, _inventory, recon = self.controlled_recon()
        evidence = recon["evidence"]
        ranked_paths = [item.get("path") for item in recon["search"]["candidates"]]
        self.assertLess(ranked_paths.index("src/game.js"), ranked_paths.index("index.html"))
        self.assertLess(ranked_paths.index("src/input.js"), ranked_paths.index("index.html"))
        self.assertEqual(recon["status"], understanding.REPOSITORY_RECONNAISSANCE_COMPLETE)
        self.assertTrue(recon["read_only"])
        self.assertLessEqual(len(evidence), understanding.MAX_TASK_BRAIN_EVIDENCE)
        self.assertTrue(any(item.get("category") == "CURRENT_OWNER" and item.get("symbol") == "InputManager" for item in evidence))
        self.assertTrue(any(item.get("category") == "CURRENT_STATE_OWNER" and item.get("symbol") == "InputManager" for item in evidence))
        self.assertTrue(any(item.get("category") == "CURRENT_STATE_OWNER" and item.get("symbol") == "GameState" and "paused" in item.get("fact", "") for item in evidence))
        self.assertTrue(any(item.get("category") == "CURRENT_INTERFACE" and "togglePause" in item.get("symbol", "") for item in evidence))
        self.assertTrue(any(item.get("category") == "CURRENT_INTERFACE" and "isPressed" in item.get("symbol", "") for item in evidence))
        persistence = [item for item in evidence if item.get("category") == "CURRENT_PERSISTENCE"]
        self.assertTrue(any(item.get("path") == "src/storage.js" and item.get("symbol") == "BEST_SCORE_KEY" for item in persistence))
        self.assertFalse(any(item.get("path") == "index.html" for item in persistence))
        self.assertTrue(any(item.get("category") == "CURRENT_TEST" and item.get("path") == "tests/input.test.js" and item.get("symbol") == "InputManager" for item in evidence))
        self.assertFalse(any(item.get("category") == "CURRENT_INTERFACE" and item.get("symbol") in {"assert", "input"} for item in evidence))
        self.assertTrue(all(understanding.validate_repository_evidence(item, mini.WORKSPACE) for item in evidence))

    def test_repository_evidence_validation_rejects_wrong_category_stale_hash_and_guesses(self):
        _raw, _ledger, _contract, _inventory, recon = self.controlled_recon()
        owner = next(item for item in recon["evidence"] if item.get("symbol") == "InputManager" and item.get("category") == "CURRENT_OWNER")
        fake = dict(owner, evidence_id="REPO-999", symbol="NoSuchOwner", fact="NoSuchOwner owns input", support="NoSuchOwner owns input")
        self.assertFalse(understanding.validate_repository_evidence(fake, mini.WORKSPACE))
        stale = dict(owner, evidence_id="REPO-998", file_sha256="0" * 64)
        self.assertFalse(understanding.validate_repository_evidence(stale, mini.WORKSPACE))
        html = next(item for item in recon["evidence"] if item.get("category") == "CURRENT_ENTRYPOINT")
        script_as_persistence = dict(html, evidence_id="REPO-997", category="CURRENT_PERSISTENCE")
        self.assertFalse(understanding.validate_repository_evidence(script_as_persistence, mini.WORKSPACE))
        test_fact = next(item for item in recon["evidence"] if item.get("category") == "CURRENT_TEST")
        assert_as_interface = dict(test_fact, evidence_id="REPO-994", category="CURRENT_INTERFACE", symbol="assert")
        input_as_interface = dict(test_fact, evidence_id="REPO-993", category="CURRENT_INTERFACE", symbol="input")
        self.assertFalse(understanding.validate_repository_evidence(assert_as_interface, mini.WORKSPACE))
        self.assertFalse(understanding.validate_repository_evidence(input_as_interface, mini.WORKSPACE))
        model_guess = {"evidence_id": "REPO-996", "category": "CURRENT_OWNER", "path": "src/input.js", "fact": "probably owns input", "evidence_type": understanding.DIRECT_OBSERVATION, "provenance": understanding.REPOSITORY_EVIDENCE}
        self.assertFalse(understanding.validate_repository_evidence(model_guess, mini.WORKSPACE))
        self.assertFalse(understanding.validate_repository_evidence(
            dict(fake, evidence_id="REPO-995", file_sha256=owner["file_sha256"]),
        ))

    def test_evidence_deduplication_and_category_diversity_happen_before_cap(self):
        _raw, _ledger, _contract, _inventory, recon = self.controlled_recon()
        evidence = recon["evidence"]
        duplicates = [dict(item, evidence_id=f"REPO-{100 + index:03d}") for index, item in enumerate(evidence)]
        entrypoint = next(item for item in evidence if item.get("category") == "CURRENT_ENTRYPOINT")
        low_value_flood = [
            dict(entrypoint, evidence_id=f"REPO-{200 + index:03d}", _semantic_key=f"flood-{index}")
            for index in range(40)
        ]
        selected, duplicate_count, truncated = understanding._select_evidence(
            evidence + duplicates + low_value_flood,
            recon.get("search_terms", []), understanding.MAX_TASK_BRAIN_EVIDENCE,
        )
        categories = {item.get("category") for item in selected}
        self.assertGreaterEqual(duplicate_count, len(evidence))
        self.assertLessEqual(len(selected), understanding.MAX_TASK_BRAIN_EVIDENCE)
        self.assertGreater(truncated, 0)
        self.assertTrue({"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_INTERFACE", "CURRENT_PERSISTENCE", "CURRENT_TEST"}.issubset(categories))

    def test_task_brain_contains_semantic_facts_without_raw_repository_payloads(self):
        raw, ledger, contract, _inventory, recon = self.controlled_recon()
        project_brain = mini.build_project_brain(
            contract, empty_specification(contract["goal"]), mini.inspect_repository(),
            repository_evidence=recon["evidence"],
        )
        task_brain = understanding.build_task_brain(
            "ROOT", raw, mini.EXISTING_PROJECT, contract, {}, recon["evidence"], [],
        )
        encoded = json.dumps(task_brain, ensure_ascii=False)
        self.assertTrue(any("InputManager" in json.dumps(item) for item in task_brain["current_owners"]))
        self.assertTrue(any("GameState" in json.dumps(item) and "paused" in json.dumps(item) for item in task_brain["current_state_ownership"]))
        self.assertTrue(any("togglePause" in json.dumps(item) for item in task_brain["current_interfaces"]))
        self.assertTrue(any("InputManager" in json.dumps(item) for item in task_brain["relevant_tests"]))
        self.assertIn("BEST_SCORE_KEY", encoded)
        self.assertNotIn("const BEST_SCORE_KEY", encoded)
        self.assertNotIn("this.keys = new Set", encoded)
        self.assertNotIn("this.paused = !this.paused", encoded)
        self.assertNotIn("source_requirement_ledger", encoded)
        self.assertLessEqual(len(encoded), understanding.MAX_TASK_BRAIN_CHARS)
        valid = understanding.validate_task_brain(
            task_brain, [item.get("requirement_id") for item in mini.ledger_requirements(ledger)], recon["evidence"],
        )
        self.assertTrue(valid["valid"], valid["errors"])
        self.assertIn("core", project_brain)

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
