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
    def ledger_for(*texts):
        return mini.build_source_requirement_ledger([
            {"text": text, "source_segment": index}
            for index, text in enumerate(texts, 1)
        ])

    @staticmethod
    def source_records(raw):
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        return ledger, mini.ledger_requirements(ledger)

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

    def test_inline_debug_bridge_enumeration_preserves_every_method_and_identifier(self):
        raw = """- Expose a small deterministic debug/testing bridge on window.AGENT_GAME that allows verification of:
  getState()
  start()
  restart()
  move(direction)
  forceCollision()
  forceCollect()
  forceWin()"""
        ledger, records = self.source_records(raw)
        self.assertEqual(len(records), 1)
        record = records[0]
        expected = [
            "window.AGENT_GAME", "getState()", "start()", "restart()",
            "move(direction)", "forceCollision()", "forceCollect()", "forceWin()",
        ]
        self.assertEqual(record["explicit_items"], expected)
        self.assertTrue(all(item in record["text"] for item in expected))
        self.assertEqual(record["source_segments"], [1])
        self.assertEqual(record["provenance"], mini.USER_STATED)
        self.assertIsNone(ledger.get("overflow"))

    def test_unbulleted_colon_introduced_identifier_list_is_preserved(self):
        raw = """Expose a testing bridge on window.AGENT_GAME that supports:
getState()
start()
restart()
move()
forceCollision()
forceCollect()
forceWin()"""
        _ledger, records = self.source_records(raw)
        self.assertEqual(len(records), 1)
        self.assertTrue(records[0]["text"].endswith("forceWin()"))
        self.assertEqual(records[0]["explicit_item_count"], 8)

    def test_inline_comma_conjunction_and_parenthetical_lists_are_lossless(self):
        raw = (
            "Expose an API with create(), read(), update(), delete(), and list().\n"
            "Use formats (json, yaml, and toml), or xml."
        )
        _ledger, records = self.source_records(raw)
        self.assertEqual(len(records), 2)
        self.assertTrue(all(
            item in records[0]["explicit_items"]
            for item in ("create()", "read()", "update()", "delete()", "list()")
        ))
        self.assertTrue(all(item in records[1]["text"] for item in ("json", "yaml", "toml", "xml")))

    def test_bullet_and_numbered_lists_remain_separate_user_stated_records(self):
        raw = """Features:
- alpha behavior
- beta behavior
1. gamma behavior
2. delta behavior"""
        _ledger, records = self.source_records(raw)
        self.assertEqual([item["text"] for item in records], [
            "Features:", "alpha behavior", "beta behavior", "gamma behavior", "delta behavior",
        ])
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in records))

    def test_cli_flags_and_identifier_shapes_are_preserved_exactly(self):
        raw = (
            "The CLI supports --force, --dry-run, --verbose, and --json. "
            "Preserve `window.__TEST_BRIDGE__`, forceCollision(), get_state(), foo.bar, and camelCase."
        )
        _ledger, records = self.source_records(raw)
        text = " ".join(item["text"] for item in records)
        for identifier in (
            "--force", "--dry-run", "--verbose", "--json", "window.__TEST_BRIDGE__",
            "forceCollision()", "get_state()", "foo.bar", "camelCase",
        ):
            self.assertIn(identifier, text)
        items = [item for record in records for item in record.get("explicit_items", [])]
        self.assertIn("window.__TEST_BRIDGE__", items)
        self.assertIn("forceCollision()", items)
        self.assertIn("foo.bar", items)

    def test_identifier_list_source_provenance_and_stable_ids_are_deterministic(self):
        raw = "Methods: create(), read(), update().\n\n- validate()"
        first_ledger, first = self.source_records(raw)
        second_ledger, second = self.source_records(raw)
        self.assertEqual(first, second)
        self.assertEqual(first_ledger["requirements"], second_ledger["requirements"])
        self.assertEqual(first[0]["source_segments"], [1])
        self.assertEqual(first[1]["source_segments"], [2])
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in first))
        self.assertFalse(any(item["provenance"] == mini.DERIVED for item in first))

    def test_descriptive_comma_prose_is_not_aggressively_exploded(self):
        _ledger, records = self.source_records("Build a polished, responsive, maintainable interface.")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["text"], "Build a polished, responsive, maintainable interface.")
        self.assertNotIn("explicit_items", records[0])

    def test_compound_stage2_task_preserves_all_eight_explicit_semantics(self):
        raw = (
            "Add Escape-key pause/resume support to the existing game. "
            "Reuse the current input and pause-state architecture instead of creating duplicate input state "
            "or another game-state owner. "
            "Preserve the current WASD/arrow controls and persistent best-score behavior. "
            "Update or add the relevant tests."
        )
        ledger, records = self.source_records(raw)
        self.assertEqual(
            [item["requirement_id"] for item in records],
            [f"REQ-{index:03d}" for index in range(1, len(records) + 1)],
        )
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in records))
        self.assertTrue(all(item["source_segments"] == [1] for item in records))
        text = " ".join(item["text"] for item in records)
        reuse = next(item["text"] for item in records if item["text"].startswith("Reuse "))
        coverage = (
            "Add Escape-key pause/resume support" in text,
            reuse.startswith("Reuse ") and "current input" in reuse,
            reuse.startswith("Reuse ") and "pause-state architecture" in reuse,
            "duplicate input state" in reuse and "instead of" in reuse,
            "another game-state owner" in reuse and "instead of" in reuse,
            "Preserve the current WASD/arrow controls" in text,
            "persistent best-score behavior" in text,
            "Update or add the relevant tests" in text,
        )
        self.assertEqual(sum(coverage), 8)
        self.assertEqual(
            reuse,
            "Reuse the current input and pause-state architecture instead of creating duplicate input state or another game-state owner.",
        )
        self.assertTrue(ledger["immutable"])

    def test_reuse_instead_of_and_duplicate_owner_constraints_are_lossless(self):
        cases = (
            "Reuse the current authentication service instead of creating another token owner.",
            "Keep the current router and extend it rather than adding a second routing system.",
            "Use the existing cache implementation and do not introduce another cache owner.",
        )
        for raw in cases:
            _ledger, records = self.source_records(raw)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["provenance"], mini.USER_STATED)
            self.assertEqual(records[0]["category"], "constraint")
            self.assertEqual(records[0]["text"], raw)
        self.assertIn("instead of creating another token owner", self.source_records(cases[0])[1][0]["text"])
        self.assertIn("rather than adding a second routing system", self.source_records(cases[1])[1][0]["text"])
        self.assertIn("do not introduce another cache owner", self.source_records(cases[2])[1][0]["text"])

    def test_preserve_replace_and_negative_constraints_survive_normalization(self):
        cases = (
            "Replace the storage layer while preserving the existing API contract.",
            "Do   not   create   another   game loop.",
            "Avoid duplicate state and retain the current ownership boundary.",
        )
        for raw in cases:
            _ledger, records = self.source_records(raw)
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["provenance"], mini.USER_STATED)
        _ledger, records = self.source_records(cases[0])
        self.assertIn("preserving the existing API contract", records[0]["text"])
        _ledger, records = self.source_records(cases[1])
        self.assertEqual(records[0]["text"], "Do not create another game loop.")
        _ledger, records = self.source_records(cases[2])
        self.assertIn("duplicate state", records[0]["text"])
        self.assertIn("ownership boundary", records[0]["text"])

    def test_observations_are_not_user_requirements_without_instruction(self):
        for raw in (
            "This makes the UI easier to understand.",
            "The project currently uses React.",
            "Repository currently uses React.",
            "The repository preserves the existing API.",
            "The code avoids duplicate state.",
        ):
            _ledger, records = self.source_records(raw)
            self.assertEqual(records, [], raw)
        _ledger, records = self.source_records("The repository must preserve the existing API.")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["provenance"], mini.USER_STATED)

    def test_compound_source_ids_and_provenance_are_deterministic(self):
        raw = "Reuse the current auth service instead of creating another token owner."
        _first_ledger, first = self.source_records(raw)
        _second_ledger, second = self.source_records(raw)
        self.assertEqual(first, second)
        self.assertEqual([item["requirement_id"] for item in first], ["REQ-001"])
        self.assertEqual(first[0]["source_segment"], 1)
        self.assertEqual(first[0]["source_segments"], [1])
        self.assertNotIn(mini.DERIVED, {item["provenance"] for item in first})
        self.assertNotIn("repository_evidence_ids", first[0])

    def test_forty_seven_explicit_requirements_remain_separate_and_bounded(self):
        raw = "\n".join(f"- requirement {index}" for index in range(1, 48))
        _ledger, records = self.source_records(raw)
        self.assertEqual(len(records), 47)
        self.assertEqual(records[-1]["requirement_id"], "REQ-047")
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in records))

    def test_requirement_bound_remains_enforced_and_overflow_is_observable(self):
        raw = "\n".join(f"- explicit requirement {index}" for index in range(1, mini.MAX_SOURCE_REQUIREMENTS + 8))
        ledger, records = self.source_records(raw)
        self.assertEqual(len(records), mini.MAX_SOURCE_REQUIREMENTS)
        self.assertEqual([item["requirement_id"] for item in records[:3]], ["REQ-001", "REQ-002", "REQ-003"])
        self.assertGreater(ledger["overflow"]["requirements_truncated"], 0)

    def test_explicit_item_bound_and_text_bound_report_truncation_without_silent_tail_loss(self):
        raw = "Expose methods: " + ", ".join(f"operation_{index:02d}()" for index in range(1, 81))
        ledger, records = self.source_records(raw)
        record = records[0]
        self.assertEqual(record["explicit_item_count"], 80)
        self.assertEqual(len(record["explicit_items"]), mini.MAX_SOURCE_EXPLICIT_ITEMS)
        self.assertTrue(record["explicit_items_truncated"])
        self.assertEqual(ledger["overflow"]["explicit_items_truncated"], 16)
        self.assertIn("operation_64()", record["explicit_items"])

        long_items = [f"operation_{index:02d}_{'x' * 25}()" for index in range(1, 31)]
        long_ledger, long_records = self.source_records("Expose methods: " + ", ".join(long_items))
        long_record = long_records[0]
        self.assertTrue(long_record["text_truncated"])
        self.assertFalse(long_record.get("explicit_items_truncated", False))
        self.assertEqual(long_record["explicit_item_count"], len(long_items))
        self.assertIn(long_items[-1], long_record["explicit_items"])
        self.assertEqual(long_ledger["overflow"]["text_truncated"], 1)

    def test_explicit_list_items_are_not_derived_and_headings_remain_non_semantic_noise(self):
        raw = """Requirements:
Methods: create(), read(), update().
Example upgrades:
- attack speed"""
        _ledger, records = self.source_records(raw)
        self.assertTrue(all(item["provenance"] == mini.USER_STATED for item in records))
        self.assertTrue(any("create()" in item["text"] for item in records))
        self.assertTrue(any(item["text"] == "Example upgrades:" for item in records))

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

    def test_frozen_v16_false_conflicts_are_compatible(self):
        pairs = (
            (
                "Build a polished self-contained browser game.",
                "The final result must be a genuinely playable game, not a static mockup.",
            ),
            (
                "The game is a top-down arena survival game.",
                "The final result must be a genuinely playable game, not a static mockup.",
            ),
            (
                "Full-screen responsive canvas game.",
                "Responsive layout must not overflow at 390px-wide viewport.",
            ),
        )
        for first, second in pairs:
            ledger = self.ledger_for(first, second)
            self.assertEqual(mini.detect_explicit_conflicts(ledger), [])
            result = mini.clarify_request(
                first + "\n" + second,
                ledger,
                structured_call=lambda *_args: {"questions": []},
            )
            self.assertEqual(result["conflicts"], [])
            self.assertEqual(result["questions"], [])

    def test_compatible_relationships_do_not_create_conflicts(self):
        pairs = (
            # SPECIALIZATION
            ("responsive UI", "The UI must fit a 390px viewport."),
            # QUALITY_CONSTRAINT and COMPOSITION
            ("Use vanilla JavaScript.", "The result must be a playable game."),
            ("Maintainable code.", "Automatic attack toward the nearest enemy."),
            # ADDITIVE
            ("Keyboard controls.", "Touch controls."),
            ("Fullscreen.", "Responsive layout."),
            ("Canvas rendering.", "A 390px viewport constraint."),
            ("Pause and resume.", "Restart the game."),
            ("Local best score.", "Game-over displays the score."),
            ("Restart must completely reset game state.",
             "Store best score locally and preserve it after reload."),
            ("Player has smooth acceleration and friction, not grid movement.",
             "Movement speed is adjustable."),
            # DEPENDENT
            ("Enemies have health.", "Enemies can die."),
            ("The game is playable.", "Enemies have health."),
            # Shared vocabulary and category difference alone
            ("A game artifact.", "The game is playable."),
            ("Keyboard controls.", "Enemy health."),
        )
        for first, second in pairs:
            self.assertEqual(
                mini.detect_explicit_conflicts(self.ledger_for(first, second)),
                [],
                msg=f"unexpected conflict for {first!r} / {second!r}",
            )

    def test_heading_like_requirements_are_not_conflict_evidence(self):
        ledger = self.ledger_for(
            "Requirements:",
            "Multiple enemy types must behave differently:",
            "Example upgrades:",
            "Support keyboard controls.",
        )
        self.assertEqual(mini.detect_explicit_conflicts(ledger), [])

    def test_true_conflicts_have_structured_evidence_and_blocking_questions(self):
        cases = (
            (
                "Restart must erase all persisted data.",
                "Best score must persist across restart.",
                "reset_vs_persistence",
            ),
            (
                "Remove keyboard controls.",
                "Keyboard controls must remain unchanged.",
                "opposite_polarity",
            ),
            (
                "Use only offline local data.",
                "Always retrieve required state from the live remote service.",
                "offline_vs_remote",
            ),
        )
        for first, second, conflict_type in cases:
            ledger = self.ledger_for(first, second)
            conflicts = mini.detect_explicit_conflicts(ledger)
            self.assertEqual(len(conflicts), 1)
            conflict = conflicts[0]
            self.assertEqual(conflict["type"], conflict_type)
            self.assertEqual(conflict["relationship"], "CONFLICT")
            self.assertFalse(conflict["can_satisfy_both"])
            for field in ("incompatibility", "choice_a_effect", "choice_b_effect"):
                self.assertTrue(conflict[field])
            result = mini.clarify_request(first + "\n" + second, ledger)
            self.assertEqual(len(result["questions"]), 1)
            self.assertTrue(result["questions"][0]["blocking"])
            self.assertIn("or", result["questions"][0]["question"])

    def test_question_without_two_incompatible_outcomes_is_rejected(self):
        ledger = self.ledger_for("Build a game.")
        incomplete = {
            "conflict_id": "CONFLICT-001",
            "requirement_ids": ["REQ-001", "REQ-002"],
            "relationship": "CONFLICT",
            "incompatibility": "",
            "choice_a_effect": "Keep A",
            "choice_b_effect": "Keep B",
            "can_satisfy_both": None,
        }
        self.assertEqual(mini.conflict_questions(ledger, [incomplete]), [])

    def test_frozen_benchmark_fixture_has_no_false_conflict_questions(self):
        raw = """Build a polished self-contained browser game.
The game is a top-down arena survival game.
Requirements:
- Full-screen responsive canvas game.
- Responsive layout must not overflow at a 390px-wide viewport.
- Support keyboard and touch controls.
- The final result must be a genuinely playable game, not a static mockup.
- Use vanilla HTML, CSS, and JavaScript.
- Enemies have health and can die.
- Kills increase score and provide XP.
- XP causes level-ups.
- Pause and restart are available.
"""
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        result = mini.clarify_request(
            raw,
            ledger,
            structured_call=lambda *_args: {"questions": []},
        )
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["questions"], [])

    def test_noninteractive_compatible_request_proceeds(self):
        raw = "Build a game.\n- Fullscreen responsive canvas.\n- Fit a 390px viewport."
        contract = mini.get_goal_contract(raw, interactive=False)
        self.assertEqual(contract["status"], "ready")

    def test_conflict_detection_does_not_mutate_source_ledger(self):
        ledger = self.ledger_for(
            "Support keyboard controls.",
            "Remove keyboard controls.",
        )
        before = json.dumps(ledger, sort_keys=True)
        mini.detect_explicit_conflicts(ledger)
        mini.conflict_questions(ledger)
        after = json.dumps(ledger, sort_keys=True)
        self.assertEqual(before, after)

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
