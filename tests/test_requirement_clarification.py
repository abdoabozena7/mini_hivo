import json
import tempfile
import unittest
from pathlib import Path

import mini


class RequirementClarificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "gemma4:e4b"
        mini.reset_run("recursive")

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def raw_request():
        return """Build a focused timer.
Requirements:
- Start and pause the timer.
- Persist the best score.
- Support WASD.
"""

    @staticmethod
    def specification(goal, **overrides):
        result = {field: [] for field in mini._PROJECT_SPECIFICATION_FIELDS}
        result["root_goal"] = goal
        result.update(overrides)
        return result

    @staticmethod
    def optional_question(requirement_id="REQ-001"):
        return {
            "question": "Should this saved setting survive a reload?",
            "reason": "This changes persistence behavior.",
            "affected_requirement_ids": [requirement_id],
            "impact_if_unknown": "The acceptance behavior changes if the setting is lost.",
            "recommended_option": "Keep it",
            "options": ["Keep it", "Reset it"],
            "allow_other": True,
            "blocking": False,
        }

    def test_source_requirements_have_stable_ids_and_user_stated_provenance(self):
        ledger = mini.extract_source_requirement_ledger(self.raw_request())
        records = mini.ledger_requirements(ledger)
        self.assertEqual([item["requirement_id"] for item in records], ["REQ-001", "REQ-002", "REQ-003"])
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in records))
        self.assertEqual(records[0]["source_segment"], 1)

    def test_source_ledger_is_frozen_and_confirmed_addition_does_not_renumber_stated_ids(self):
        ledger = mini.extract_source_requirement_ledger(self.raw_request())
        original_ids = [item["requirement_id"] for item in mini.ledger_requirements(ledger)]
        with self.assertRaises(TypeError):
            ledger["requirements"][0]["text"] = "changed"
        updated = mini.append_confirmed_requirement(ledger, "Use localStorage", question_id="Q-001")
        self.assertEqual([item["requirement_id"] for item in mini.ledger_requirements(updated)], original_ids)
        self.assertEqual(updated["confirmed_requirements"][0]["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(updated["confirmed_requirements"][0]["requirement_id"], "REQ-004")
        self.assertEqual(ledger["confirmed_requirements"], [])

    def test_long_prompt_segmentation_is_bounded_and_keeps_source_segments(self):
        raw = "Build an app.\n\n" + "\n\n".join(
            f"- explicit requirement {index} " + ("detail " * 12) for index in range(1, 40)
        )
        segments = mini.bounded_source_segments(raw)
        self.assertLessEqual(len(segments), mini.MAX_SOURCE_SEGMENTS)
        self.assertTrue(all(len(item["text"]) <= mini.MAX_SOURCE_SEGMENT_CHARS for item in segments))
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        self.assertTrue(all(item["source_segment"] for item in mini.ledger_requirements(ledger)))

    def test_extraction_failure_is_distinct_from_later_specification_omission(self):
        ledger = mini.extract_source_requirement_ledger(
            "Build an app.\n- preserve the visible timer",
            structured_call=lambda *_args: (_ for _ in ()).throw(mini.StructuredOutputError("bad extract")),
            use_model=True,
        )
        self.assertEqual(ledger["extraction"]["status"], "partial_fallback")
        self.assertEqual(ledger["extraction"]["failure_count"], 1)
        brain = mini.build_project_brain(
            mini.get_goal_contract("Build an app.\n- preserve the visible timer", interactive=False),
            self.specification("Build an app."), {"files": []},
        )
        self.assertEqual(brain["source_requirement_coverage"][0]["status"], "UNMAPPED")

    def test_wasd_deduplication_keeps_all_source_provenance(self):
        raw = """- Support WASD.

- Player should move with W/A/S/D.
"""
        ledger = mini.extract_source_requirement_ledger(raw)
        records = mini.ledger_requirements(ledger)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["source_segments"], [1, 2])
        self.assertEqual(len(records[0]["source_variants"]), 2)

    def test_get_goal_contract_keeps_all_stated_requirements_before_specification(self):
        contract = mini.get_goal_contract(self.raw_request(), interactive=False)
        self.assertEqual(contract["requirements"], [
            "Start and pause the timer.", "Persist the best score.", "Support WASD.",
        ])
        self.assertEqual(len(contract["source_requirement_ledger"]["requirements"]), 3)
        self.assertEqual(contract["source_contract"]["user_stated_requirements"][1]["provenance"], mini.USER_STATED)

    def test_derived_optional_default_is_not_user_confirmed(self):
        response = {"questions": [self.optional_question()]}
        contract = mini.get_goal_contract(
            "Build a timer.\n- save settings", interactive=False,
            clarifier_call=lambda *_args: response,
        )
        self.assertEqual(contract["status"], "ready")
        self.assertEqual(contract["derived_assumptions"][0]["provenance"], mini.DERIVED)
        self.assertEqual(contract["user_confirmed_requirements"], [])
        self.assertEqual(contract["source_requirement_ledger"]["confirmed_requirements"], [])

    def test_verified_state_is_separate_and_provenance_is_not_source(self):
        contract = mini.get_goal_contract(self.raw_request(), interactive=False)
        brain = mini.build_project_brain(contract, self.specification(contract["goal"]), {"files": []})
        self.assertIsNot(brain["source_contract"], brain["verified_state"])
        self.assertEqual(brain["verified_state"]["provenance"], mini.VERIFIED)
        self.assertNotIn("VERIFIED", {
            item["provenance"] for item in mini.ledger_requirements(brain["source_requirement_ledger"])
        })
        self.assertEqual(
            len(brain["source_contract"]["user_stated_requirements"]),
            len(mini.ledger_requirements(brain["source_requirement_ledger"])),
        )

    def test_specifier_omission_cannot_delete_source_requirement_and_is_unmapped(self):
        contract = mini.get_goal_contract(self.raw_request(), interactive=False)
        brain = mini.build_project_brain(
            contract, self.specification(contract["goal"], major_functional_areas=["Start and pause the timer"]),
            {"files": []},
        )
        coverage = {item["requirement_id"]: item["status"] for item in brain["source_requirement_coverage"]}
        self.assertEqual(len(coverage), 3)
        self.assertEqual(coverage["REQ-001"], "MAPPED")
        self.assertEqual(coverage["REQ-002"], "UNMAPPED")
        self.assertEqual(coverage["REQ-003"], "UNMAPPED")
        self.assertIn("Persist the best score", json.dumps(brain["source_contract"], ensure_ascii=False))
        self.assertEqual(mini.RUN["source_requirements_retained"], 3)
        self.assertEqual(mini.RUN["source_requirement_retention_numerator"], 3)
        self.assertEqual(mini.RUN["source_requirement_retention_denominator"], 3)
        self.assertEqual(mini.RUN["source_requirement_retention_rate"], 1.0)

    def test_source_and_confirmed_decision_reach_specifier_prompt(self):
        question = self.optional_question()
        contract = mini.get_goal_contract(
            "Build a timer.\n- save settings", interactive=True, terminal_available=True,
            clarifier_call=lambda *_args: {"questions": [question]},
            selector=lambda _question, **_kwargs: 0,
        )
        prompts = []
        response = self.specification(contract["goal"], major_functional_areas=["save settings"])
        mini.expand_project_specification(
            contract["original_goal"], contract,
            structured_call=lambda prompt, *_args: prompts.append(prompt) or response,
        )
        self.assertIn("REQ-001", prompts[0])
        self.assertIn("USER-CONFIRMED CLARIFICATION DECISIONS", prompts[0])
        self.assertIn("Keep it", prompts[0])
        self.assertGreaterEqual(mini.RUN["user_confirmed_requirements"], 1)

    def test_root_compact_brain_retains_all_source_ids_but_worker_projection_is_relevant(self):
        raw = "Build a tool.\n" + "\n".join(f"- requirement {index}" for index in range(1, 30))
        contract = mini.get_goal_contract(raw, interactive=False)
        brain = mini.build_project_brain(contract, self.specification(contract["goal"]), {"files": []})
        compact = mini.compact_project_brain(brain)
        self.assertLessEqual(len(compact), mini.MAX_PROJECT_BRAIN_CHARS)
        self.assertIn("REQ-029", compact)
        task = mini.make_task("feature-29", "Implement requirement 29", 1, "ROOT", [], [])
        projection = mini.build_brain_projection(brain, task, repo_snapshot={})
        encoded = json.dumps(projection, ensure_ascii=False)
        self.assertLessEqual(len(encoded), mini.MAX_BRAIN_PROJECTION_CHARS)
        self.assertIn("REQ-029", encoded)
        self.assertLess(encoded.count("REQ-"), len(contract["source_requirement_ledger"]["requirements"]))
        packet = mini.build_node_context(task, contract, None, {}, brain_projection=projection)
        self.assertNotIn('"source_requirement_ledger"', packet)

    def test_root_brain_prompt_compacts_large_source_side_channel_without_dropping_ids(self):
        raw = "Build a tool.\n" + "\n".join(
            f"- explicit requirement {index} " + ("detail " * 20) for index in range(1, 65)
        )
        contract = mini.get_goal_contract(raw, interactive=False)
        brain = mini.build_project_brain(contract, self.specification(contract["goal"]), {"files": []})
        compact = mini.compact_project_brain(brain)
        self.assertLessEqual(len(compact), mini.MAX_PROJECT_BRAIN_CHARS)
        self.assertIn("REQ-064", compact)

    def test_fully_specified_and_low_friction_requests_produce_no_trivia_questions(self):
        ledger = mini.extract_source_requirement_ledger(
            "Build a fun survival game.\n- player can move\n- player can restart"
        )
        result = mini.clarify_request("Build a fun survival game.", ledger)
        self.assertEqual(result["questions"], [])
        self.assertEqual(result["interaction_style"], "LOW_FRICTION")

    def test_explicit_conflict_produces_one_blocking_source_linked_question(self):
        raw = """Build a game.
- Restart resets everything.
- Persist the best score.
"""
        ledger = mini.extract_source_requirement_ledger(raw)
        result = mini.clarify_request(raw, ledger)
        self.assertEqual(len(result["questions"]), 1)
        question = result["questions"][0]
        self.assertTrue(question["blocking"])
        self.assertEqual(question["affected_requirement_ids"], ["REQ-001", "REQ-002"])

    def test_acceptance_ambiguity_can_be_admitted_but_internal_trivia_is_filtered(self):
        ledger = mini.extract_source_requirement_ledger("Build a timer.\n- timer must be verifiable")
        acceptance = mini.normalize_question({
            "question": "What should count as success?", "reason": "Acceptance criteria are ambiguous.",
            "affected_requirement_ids": ["REQ-001"], "impact_if_unknown": "Tests cannot determine success.",
            "recommended_option": "", "options": ["The timer reaches zero", "The timer starts"],
            "allow_other": True, "blocking": True,
        }, 1, ledger, "LOW_FRICTION", [])
        trivia = mini.normalize_question({
            "question": "What helper function name should be used?", "reason": "Implementation detail.",
            "affected_requirement_ids": ["REQ-001"], "impact_if_unknown": "A helper name is unknown.",
            "recommended_option": "", "options": ["Any name"], "allow_other": True, "blocking": False,
        }, 1, ledger, "LOW_FRICTION", [])
        self.assertIsNotNone(acceptance)
        self.assertIsNone(trivia)

    def test_clarification_question_count_is_bounded(self):
        ledger = mini.extract_source_requirement_ledger("Replace an existing API compatibly.\n- preserve existing API")
        questions = []
        for index in range(3):
            item = self.optional_question("REQ-001")
            item["question"] = f"Which compatible behavior {index}?"
            questions.append(item)
        result = mini.clarify_request("Replace an existing API compatibly.", ledger,
                                      structured_call=lambda *_args: {"questions": questions})
        self.assertLessEqual(len(result["questions"]), mini.MAX_CLARIFICATION_QUESTIONS)

    def test_recommended_option_is_first_and_labelled(self):
        q = mini.normalize_question({
            "question": "Which API behavior should be retained?", "reason": "Compatibility is unresolved.",
            "affected_requirement_ids": ["REQ-001"], "impact_if_unknown": "Existing clients may break.",
            "recommended_option": "Keep compatibility", "options": ["Break compatibility", "Keep compatibility"],
            "allow_other": True, "blocking": True,
        }, 1, mini.extract_source_requirement_ledger("- preserve existing API"), "PRECISION_SENSITIVE", [])
        labels = mini.clarification_option_labels(q)
        self.assertTrue(labels[0].endswith("Recommended"))
        self.assertEqual(labels[-1], "Other...")

    def test_recommendation_label_is_absent_without_defensible_recommendation(self):
        q = mini.normalize_question({
            "question": "Which visible behavior should be used?", "reason": "Acceptance behavior is ambiguous.",
            "affected_requirement_ids": ["REQ-001"], "impact_if_unknown": "The acceptance result differs.",
            "recommended_option": "", "options": ["Behavior A", "Behavior B"],
            "allow_other": True, "blocking": True,
        }, 1, mini.extract_source_requirement_ledger("- support either behavior"), "PRECISION_SENSITIVE", [])
        self.assertIsNotNone(q)
        self.assertFalse(any("Recommended" in label for label in mini.clarification_option_labels(q)))

    def test_arrow_key_selection_and_other_free_text(self):
        q = mini.normalize_question(self.optional_question(), 1,
                                    mini.extract_source_requirement_ledger("- save settings"), "LOW_FRICTION", [])
        self.assertEqual(mini.navigate_clarification_options(mini.clarification_option_labels(q), ["down", "enter"]), 1)
        self.assertEqual(mini.clarification_option_labels(q)[-1], "Other...")
        result = mini.resolve_clarification_questions(
            {"questions": [dict(q, blocking=True)]}, interactive=True, terminal_available=True,
            selector=lambda _question, **_kwargs: 2, answer_reader=lambda *_args: "localStorage",
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["answers"][0]["answer"], "localStorage")
        self.assertEqual(result["answers"][0]["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(result["answers"][0]["selected_option"], "Other...")

    def test_recommended_label_is_presentation_only(self):
        q = mini.normalize_question(self.optional_question(), 1,
                                    mini.extract_source_requirement_ledger("- save settings"), "LOW_FRICTION", [])
        result = mini.resolve_clarification_questions(
            {"questions": [dict(q, blocking=True)]}, interactive=True, terminal_available=True,
            selector=lambda _question, **_kwargs: 0,
        )
        self.assertEqual(result["answers"][0]["answer"], "Keep it")
        self.assertNotIn("Recommended", result["answers"][0]["answer"])

    def test_conflict_resolution_adds_decision_without_deleting_original_source_statements(self):
        raw = "Build a game.\n- restart resets everything\n- persist the best score"
        contract = mini.get_goal_contract(raw, interactive=True, terminal_available=True,
                                          selector=lambda _question, **_kwargs: 1)
        records = mini.ledger_requirements(contract["source_requirement_ledger"])
        self.assertEqual([item["text"] for item in records], [
            "restart resets everything", "persist the best score",
        ])
        self.assertEqual(contract["user_confirmed_requirements"][0]["provenance"], mini.USER_CONFIRMED)
        self.assertEqual(contract["user_confirmed_requirements"][0]["question_id"], "Q-001")
        self.assertEqual(contract["source_requirement_ledger"]["confirmed_requirements"][0]["provenance"], mini.USER_CONFIRMED)

    def test_noninteractive_blocking_clarification_has_distinct_terminal_state(self):
        raw = "Build a game.\n- restart resets everything\n- persist the best score"
        contract = mini.get_goal_contract(raw, interactive=False)
        self.assertEqual(contract["status"], "clarification_required")
        self.assertEqual(contract["terminal_state"], "CLARIFICATION_REQUIRED")
        self.assertEqual(mini.RUN["clarification_terminal_state"], "CLARIFICATION_REQUIRED")
        self.assertEqual(mini.RUN["root_verified"], False)

    def test_noninteractive_optional_resolution_never_waits_for_input(self):
        q = mini.normalize_question(self.optional_question(), 1,
                                    mini.extract_source_requirement_ledger("- save settings"), "LOW_FRICTION", [])
        result = mini.resolve_clarification_questions(
            {"questions": [q]}, interactive=True, terminal_available=False,
        )
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["derived"][0]["provenance"], mini.DERIVED)
        self.assertEqual(mini.RUN["optional_clarifications_skipped"], 1)

    def test_noninteractive_blocking_resolution_does_not_hang_or_become_root_fail(self):
        q = mini.normalize_question(dict(self.optional_question(), blocking=True), 1,
                                    mini.extract_source_requirement_ledger("- save settings"), "LOW_FRICTION", [])
        result = mini.resolve_clarification_questions(
            {"questions": [q]}, interactive=True, terminal_available=False,
        )
        self.assertEqual(result["status"], "clarification_required")
        self.assertEqual(result["unanswered"][0]["question_id"], "Q-001")
        self.assertEqual(mini.RUN["clarification_terminal_state"], "CLARIFICATION_REQUIRED")

    def test_extractor_and_clarifier_calls_are_accounted_separately(self):
        mini.extract_source_requirement_ledger(
            "Replace an existing API compatibly.",
            structured_call=lambda *_args: {"requirements": []}, use_model=True,
        )
        ledger = mini.extract_source_requirement_ledger("- preserve existing API")
        mini.clarify_request("Replace an existing API compatibly.", ledger,
                             structured_call=lambda *_args: {"questions": []})
        self.assertEqual(mini.RUN["requirement_extractor_calls"], 1)
        self.assertEqual(mini.RUN["clarifier_calls"], 1)

    def test_legacy_v15_budgets_and_strategy_limits_are_unchanged(self):
        self.assertEqual(mini.MAX_TOOL_STEPS, 28)
        self.assertEqual(mini.MAX_DEPTH, 6)
        self.assertEqual(mini.MAX_REPAIRS_PER_LEAF, 2)
        self.assertEqual(mini.MAX_STRATEGY_ALTERNATIVES, 2)


if __name__ == "__main__":
    unittest.main()
