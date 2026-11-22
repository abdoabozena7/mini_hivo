"""Unit tests for Mini Hivo's Evidence-Licensed Granularity & Tool-Contract Gate."""

from __future__ import annotations

import json
import re
import unittest

from hivo import evidence_licensed_gate as gate
from hivo.evidence_licensed_gate import (
    BROWSER_MODULE_OR_RUNTIME_DEFECT,
    CAPABILITY_OR_BREADTH_CANDIDATE,
    HOLD_TERMINAL_FAILURE,
    LICENSE_GRANULARITY_CHANGE,
    PERMISSION_OR_SCOPE_DENIAL,
    REQUIRE_SAME_AUTHORITY_CORRECTION,
    RESOURCE_OR_BUDGET_LIMIT,
    SCHEMA_CONTRACT_FAILURE,
    STALE_TARGET_OR_RANGE,
    STOP_IMMEDIATELY,
    SYNTAX_REJECTED_MUTATION,
    UNATTRIBUTED_NON_PROGRESS,
    build_immediate_mutation_hint,
    build_same_authority_correction_brief,
    classify_failure_episode,
    extract_text_tool_call_fallback,
    license_granularity_decision,
)


class FailureEpisodeClassificationTests(unittest.TestCase):
    def assert_json_safe_episode(self, episode: dict) -> None:
        encoded = json.dumps(episode)
        decoded = json.loads(encoded)
        self.assertEqual(decoded, episode)
        for key in (
            "episode_class",
            "earliest_tool",
            "earliest_target",
            "observed_codes",
            "abstained",
            "rationale",
        ):
            self.assertIn(key, episode)
        self.assertIn(episode["episode_class"], gate.OBSERVED_EPISODE_CLASSES)
        self.assertIsInstance(episode["observed_codes"], list)
        self.assertIsInstance(episode["abstained"], bool)
        self.assertIsInstance(episode["rationale"], str)
        self.assertTrue(episode["rationale"])

    def test_permission_and_scope_denials_take_highest_priority(self) -> None:
        cases = [
            {
                "name": "plan_approval_required",
                "leaf_result": {
                    "status": "blocked",
                    "terminal_state": "PLAN_APPROVAL_REQUIRED",
                    "failure_type": "PLAN_APPROVAL_REQUIRED",
                    "summary": "existing-project mutation cannot begin before approval",
                },
            },
            {
                "name": "impact_contract_violation",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "IMPACT_CONTRACT_INVALID",
                    "summary": "IMPACT_CONTRACT_INVALID: impact contract rejected",
                },
            },
            {
                "name": "worker_authorization_invalid",
                "leaf_result": {
                    "status": "blocked",
                    "failure_type": "WORKER_AUTHORIZATION_INVALID",
                    "orchestration_failure": "WORKER_AUTHORIZATION_INVALID",
                },
            },
            {
                "name": "outside_workspace_mutation",
                "leaf_result": {
                    "status": "failed",
                    "mutation_failures": [
                        {
                            "tool": "write_file",
                            "target": "../outside.py",
                            "category": "SAFETY_REJECTED_MUTATION",
                            "summary": "error: '../outside.py' is outside the workspace.",
                        }
                    ],
                },
            },
            {
                "name": "unauthorized_target_precedes_schema_error",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "MUTATION_ARGUMENT_RETRIES_EXHAUSTED",
                    "mutation_failures": [
                        {
                            "tool": "edit_file_range",
                            "target": "index.html",
                            "category": "TOOL_ARGUMENT_REJECTED",
                            "summary": "error: incomplete or truncated edit_file_range tool call; missing: start_line.",
                        },
                        {
                            "tool": "write_file",
                            "target": "../secret.txt",
                            "category": "SAFETY_REJECTED_MUTATION",
                            "summary": "error: '../secret.txt' is outside the workspace.",
                        },
                    ],
                },
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                ep = classify_failure_episode(case["leaf_result"])
                self.assert_json_safe_episode(ep)
                self.assertEqual(ep["episode_class"], PERMISSION_OR_SCOPE_DENIAL)
                self.assertFalse(ep["abstained"])

    def test_resource_and_global_run_budget_limits_are_prioritized(self) -> None:
        cases = [
            {
                "name": "environment_error",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "ENVIRONMENT_ERROR",
                    "summary": "Ollama connection refused",
                },
            },
            {
                "name": "provider_failure_status",
                "leaf_result": {
                    "status": "provider_failure",
                    "provider_error": "HTTP 503 from local provider",
                    "summary": "provider unavailable",
                },
            },
            {
                "name": "timeout",
                "leaf_result": {
                    "status": "failed",
                    "timed_out": True,
                    "summary": "model request timed out after 600s",
                },
            },
            {
                "name": "global_run_budget_exhausted",
                "leaf_result": {
                    "status": "budget_exhausted",
                    "failure_type": "RUN_BUDGET_EXHAUSTED",
                    "summary": "RUN_BUDGET_EXHAUSTED: max_model_calls",
                },
            },
            {
                "name": "bare_run_level_budget_exhausted",
                "leaf_result": {
                    "status": "budget_exhausted",
                    "summary": "global budget exhausted",
                },
            },
            {
                "name": "browser_environment_error_not_runtime_defect",
                "leaf_result": {
                    "status": "failed",
                    "browser": {
                        "passed": False,
                        "environment_error": True,
                        "console_errors": ["Failed to resolve module specifier 'three'"],
                    },
                },
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                ep = classify_failure_episode(case["leaf_result"])
                self.assert_json_safe_episode(ep)
                self.assertEqual(ep["episode_class"], RESOURCE_OR_BUDGET_LIMIT)
                self.assertFalse(ep["abstained"])

    def test_manual_run_schema_contract_failure_not_misread_as_too_broad_or_permission(self) -> None:
        # Mirrors actual manual run 20261117T135509-718ad4b8: write_file succeeded,
        # echo was refused by command allowlist, then edit_file_range omitted start_line
        # and controller labeled it TASK_TOO_BROAD.
        leaf_result = {
            "status": "too_broad",
            "failure_type": "TASK_TOO_BROAD",
            "summary": "TASK_TOO_BROAD: repeated invalid mutations show the current node exceeds reliable focused capacity",
            "tool_evidence": [
                {"tool": "write_file", "target": "index.html", "result": "wrote file: index.html"},
                {"tool": "run_command", "target": "echo Verification successful", "result": "error: command refused: echo is not allowlisted"},
            ],
            "mutation_failures": [
                {
                    "kind": "mutation_failure",
                    "tool": "edit_file_range",
                    "target": "index.html",
                    "category": "TOOL_ARGUMENT_REJECTED",
                    "summary": "error: incomplete or truncated edit_file_range tool call; missing: path, start_line. No file was changed.",
                    "count": 5,
                }
            ],
        }
        ep = classify_failure_episode(leaf_result)
        self.assert_json_safe_episode(ep)
        self.assertEqual(ep["episode_class"], SCHEMA_CONTRACT_FAILURE)
        self.assertEqual(ep["earliest_tool"], "edit_file_range")
        self.assertEqual(ep["earliest_target"], "index.html")
        self.assertIn("TOOL_ARGUMENT_REJECTED", ep["observed_codes"])
        self.assertFalse(ep["abstained"])

        exhausted_ep = classify_failure_episode({
            "status": "failed",
            "failure_type": "MUTATION_ARGUMENT_RETRIES_EXHAUSTED",
            "summary": "MUTATION_ARGUMENT_RETRIES_EXHAUSTED",
        })
        self.assertEqual(exhausted_ep["episode_class"], SCHEMA_CONTRACT_FAILURE)

    def test_syntax_rejected_mutation_classification(self) -> None:
        leaf_result = {
            "status": "failed",
            "failure_type": "WORKER_NO_MUTATION_PROGRESS",
            "mutation_failures": [
                {
                    "tool": "write_file",
                    "target": "index.html",
                    "category": "SYNTAX_INVALID_MUTATION",
                    "summary": "error: JavaScript syntax validation failed: SyntaxError: Cannot use import statement outside a module",
                }
            ],
        }
        ep = classify_failure_episode(leaf_result)
        self.assert_json_safe_episode(ep)
        self.assertEqual(ep["episode_class"], SYNTAX_REJECTED_MUTATION)
        self.assertEqual(ep["earliest_tool"], "write_file")
        self.assertEqual(ep["earliest_target"], "index.html")
        self.assertFalse(ep["abstained"])

    def test_stale_target_or_range_variants(self) -> None:
        variants = [
            {
                "tool": "edit_file_range",
                "target": "index.html",
                "category": "MISSING_TARGET",
                "summary": "error: file does not exist: index.html",
            },
            {
                "tool": "edit_file_range",
                "target": "app.py",
                "category": "STALE_TARGET",
                "summary": "error: invalid line range 40-50; file has 22 lines",
            },
            {
                "tool": "edit_file",
                "target": "app.py",
                "category": "STALE_TARGET",
                "summary": "error: expected 1 exact replacement(s), found 0; file was not changed",
            },
            {
                "tool": "edit_file",
                "target": "app.py",
                "category": "STALE_TARGET",
                "summary": "error: expected 1 exact replacement(s), found 3; file was not changed",
            },
        ]
        for record in variants:
            with self.subTest(summary=record["summary"]):
                ep = classify_failure_episode({"status": "failed", "mutation_failures": [record]})
                self.assert_json_safe_episode(ep)
                self.assertEqual(ep["episode_class"], STALE_TARGET_OR_RANGE)
                self.assertEqual(ep["earliest_tool"], record["tool"])
                self.assertEqual(ep["earliest_target"], record["target"])
                self.assertFalse(ep["abstained"])

    def test_browser_module_or_runtime_defect_variants(self) -> None:
        cases = [
            {
                "name": "bare_module_specifier",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "IMPLEMENTATION_ERROR",
                    "builder": {"status": "done"},
                    "browser": {
                        "passed": False,
                        "entry_path": "index.html",
                        "console_errors": [
                            "Uncaught TypeError: Failed to resolve module specifier \"three\". Relative references must start with either \"/\", \"./\", or \"../\"."
                        ],
                        "page_errors": [],
                        "failures": [{"code": "console_errors", "evidence": "Failed to resolve module specifier"}],
                    },
                    "gate": {"passed": False, "deterministic_failures": []},
                },
                "expected_code": "bare_module_specifier",
            },
            {
                "name": "zero_size_canvas",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "BROWSER_VERIFICATION_STAGNATION",
                    "browser": {
                        "passed": False,
                        "path": "index.html",
                        "runtime_state": {"canvasCount": 1, "canvasWidth": 0, "canvasHeight": 600},
                        "failures": [{"code": "zero_size_canvas", "evidence": "canvas width is 0"}],
                    },
                },
                "expected_code": "zero_size_canvas",
            },
            {
                "name": "missing_game_bridge",
                "leaf_result": {
                    "status": "failed",
                    "builder": {"status": "done", "mutation_failures": [
                        {"tool": "edit_file", "target": "index.html", "category": "STALE_TARGET", "summary": "error: expected 1 exact replacement(s), found 0"}
                    ]},
                    "browser": {
                        "passed": False,
                        "resolved_entrypoint": "index.html",
                        "failures": [
                            {"code": "missing_game_bridge", "evidence": "window.AGENT_GAME verification bridge is unavailable"}
                        ],
                    },
                    "gate": {"passed": False},
                },
                "expected_code": "missing_game_bridge",
            },
            {
                "name": "uncaught_reference_error",
                "leaf_result": {
                    "status": "failed",
                    "builder": {"status": "done"},
                    "browser": {
                        "passed": False,
                        "entry_path": "game.html",
                        "page_errors": ["Uncaught ReferenceError: requestFrame is not defined"],
                    },
                    "gate": {"passed": False},
                },
                "expected_code": "ReferenceError",
            },
            {
                "name": "nested_builder_verify_web_app_missing_bridge_method",
                "leaf_result": {
                    "status": "failed",
                    "failure_type": "BROWSER_VERIFICATION_STAGNATION",
                    "builder": {
                        "status": "failed",
                        "tool_evidence": [
                            {
                                "tool": "verify_web_app",
                                "target": "index.html",
                                "result": json.dumps({
                                    "passed": False,
                                    "entry_path": "index.html",
                                    "failures": [
                                        {
                                            "code": "failed_interaction",
                                            "evidence": "TypeError: window.AGENT_GAME.advanceFrame is not a function",
                                        }
                                    ],
                                }),
                            }
                        ],
                    },
                },
                "expected_code": "missing_bridge_method",
            },
        ]
        for case in cases:
            with self.subTest(case=case["name"]):
                ep = classify_failure_episode(case["leaf_result"])
                self.assert_json_safe_episode(ep)
                self.assertEqual(ep["episode_class"], BROWSER_MODULE_OR_RUNTIME_DEFECT)
                self.assertEqual(ep["earliest_tool"], "verify_web_app")
                self.assertIsNotNone(ep["earliest_target"])
                self.assertIn(case["expected_code"], ep["observed_codes"])
                self.assertFalse(ep["abstained"])

    def test_capability_or_breadth_candidate_requires_positive_scope_or_valid_mutations(self) -> None:
        # 1. Genuine TASK_TOO_BROAD with positive scope evidence on task.
        ep_scope = classify_failure_episode(
            {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "node spans independent subsystems"},
            task={"fit_assessment": {"decision": "split"}, "responsibilities": ["3D renderer", "collision engine"]},
        )
        self.assert_json_safe_episode(ep_scope)
        self.assertEqual(ep_scope["episode_class"], CAPABILITY_OR_BREADTH_CANDIDATE)
        self.assertFalse(ep_scope["abstained"])

        # 2. Focused step budget exhausted AFTER valid applied mutations.
        ep_step_after_mut = classify_failure_episode({
            "status": "budget_exhausted",
            "failure_type": "EXECUTION_BUDGET_EXHAUSTED",
            "execution_outcome": "EXECUTION_BUDGET_EXHAUSTED",
            "step_budget": 12,
            "tool_steps_used": 12,
            "tool_evidence": [
                {"tool": "write_file", "target": "engine.py", "result": "wrote file: engine.py"},
                {"tool": "edit_file", "target": "engine.py", "result": "edited file: engine.py (1 replacement(s))"},
            ],
            "summary": "EXECUTION_BUDGET_EXHAUSTED: focused execution ended without verified completion",
        })
        self.assert_json_safe_episode(ep_step_after_mut)
        self.assertEqual(ep_step_after_mut["episode_class"], CAPABILITY_OR_BREADTH_CANDIDATE)
        self.assertFalse(ep_step_after_mut["abstained"])

    def test_unattributed_non_progress_abstains_without_scope_evidence(self) -> None:
        # Bare self-reported TASK_TOO_BROAD with NO scope evidence and NO valid mutations.
        bare_too_broad = classify_failure_episode({
            "status": "too_broad",
            "failure_type": "TASK_TOO_BROAD",
            "summary": "Builder self-reported TASK_TOO_BROAD",
            "environment_error": False,
            "timed_out": False,
        })
        self.assert_json_safe_episode(bare_too_broad)
        self.assertEqual(bare_too_broad["episode_class"], UNATTRIBUTED_NON_PROGRESS)
        self.assertTrue(bare_too_broad["abstained"])

        # Step budget exhausted with only read calls and no valid mutations or scope evidence.
        read_only_step_exhausted = classify_failure_episode({
            "status": "budget_exhausted",
            "failure_type": "EXECUTION_BUDGET_EXHAUSTED",
            "execution_outcome": "EXECUTION_BUDGET_EXHAUSTED",
            "step_budget": 8,
            "tool_steps_used": 8,
            "tool_evidence": [{"tool": "read_file", "target": "app.py", "result": "x = 1\n"}],
            "summary": "EXECUTION_BUDGET_EXHAUSTED: focused execution ended without verified completion",
        })
        self.assertEqual(read_only_step_exhausted["episode_class"], UNATTRIBUTED_NON_PROGRESS)
        self.assertTrue(read_only_step_exhausted["abstained"])


class GranularityLicensingDecisionTests(unittest.TestCase):
    def test_permission_resource_and_approval_bound_never_retry_or_split(self) -> None:
        for stop_cls in (PERMISSION_OR_SCOPE_DENIAL, RESOURCE_OR_BUDGET_LIMIT):
            for corr in (False, True):
                for budget in (False, True):
                    for can_split in (False, True):
                        with self.subTest(cls=stop_cls, corr=corr, budget=budget, can_split=can_split):
                            decision = license_granularity_decision(
                                {"episode_class": stop_cls, "abstained": False},
                                correction_attempted=corr,
                                budget_remaining=budget,
                                approval_bound=False,
                                can_split=can_split,
                            )
                            self.assertEqual(decision["decision"], STOP_IMMEDIATELY)
                            self.assertFalse(decision["allow_split"])
                            self.assertFalse(decision["allow_correction"])

        for any_cls in gate.OBSERVED_EPISODE_CLASSES:
            with self.subTest(approval_bound_cls=any_cls):
                decision = license_granularity_decision(
                    {"episode_class": any_cls},
                    correction_attempted=False,
                    budget_remaining=True,
                    approval_bound=True,
                    can_split=True,
                )
                self.assertEqual(decision["decision"], STOP_IMMEDIATELY)
                self.assertFalse(decision["allow_split"])
                self.assertFalse(decision["allow_correction"])

    def test_attributable_defects_require_correction_before_licensing_split(self) -> None:
        for cls in (
            SCHEMA_CONTRACT_FAILURE,
            STALE_TARGET_OR_RANGE,
            SYNTAX_REJECTED_MUTATION,
            BROWSER_MODULE_OR_RUNTIME_DEFECT,
        ):
            with self.subTest(cls=cls):
                first = license_granularity_decision(
                    {"episode_class": cls, "abstained": False},
                    correction_attempted=False,
                    budget_remaining=True,
                    approval_bound=False,
                    can_split=True,
                )
                self.assertEqual(first["decision"], REQUIRE_SAME_AUTHORITY_CORRECTION)
                self.assertTrue(first["allow_correction"])
                self.assertFalse(first["allow_split"])

                after_correction_can_split = license_granularity_decision(
                    {"episode_class": cls, "abstained": False},
                    correction_attempted=True,
                    budget_remaining=True,
                    approval_bound=False,
                    can_split=True,
                )
                self.assertEqual(after_correction_can_split["decision"], LICENSE_GRANULARITY_CHANGE)
                self.assertTrue(after_correction_can_split["allow_split"])
                self.assertFalse(after_correction_can_split["allow_correction"])

                after_correction_max_depth = license_granularity_decision(
                    {"episode_class": cls, "abstained": False},
                    correction_attempted=True,
                    budget_remaining=True,
                    approval_bound=False,
                    can_split=False,
                )
                self.assertEqual(after_correction_max_depth["decision"], HOLD_TERMINAL_FAILURE)
                self.assertFalse(after_correction_max_depth["allow_split"])
                self.assertFalse(after_correction_max_depth["allow_correction"])

                no_budget = license_granularity_decision(
                    {"episode_class": cls, "abstained": False},
                    correction_attempted=False,
                    budget_remaining=False,
                    approval_bound=False,
                    can_split=True,
                )
                self.assertEqual(no_budget["decision"], HOLD_TERMINAL_FAILURE)
                self.assertFalse(no_budget["allow_split"])
                self.assertFalse(no_budget["allow_correction"])

    def test_capability_candidate_splits_immediately_when_permitted(self) -> None:
        licensed = license_granularity_decision(
            {"episode_class": CAPABILITY_OR_BREADTH_CANDIDATE, "abstained": False},
            correction_attempted=False,
            budget_remaining=True,
            approval_bound=False,
            can_split=True,
        )
        self.assertEqual(licensed["decision"], LICENSE_GRANULARITY_CHANGE)
        self.assertTrue(licensed["allow_split"])
        self.assertFalse(licensed["allow_correction"])

        terminal_at_max_depth = license_granularity_decision(
            {"episode_class": CAPABILITY_OR_BREADTH_CANDIDATE, "abstained": False},
            correction_attempted=False,
            budget_remaining=True,
            approval_bound=False,
            can_split=False,
        )
        self.assertEqual(terminal_at_max_depth["decision"], HOLD_TERMINAL_FAILURE)
        self.assertFalse(terminal_at_max_depth["allow_split"])

    def test_unattributed_non_progress_allows_one_correction_and_never_spuriously_splits(self) -> None:
        first = license_granularity_decision(
            {"episode_class": UNATTRIBUTED_NON_PROGRESS, "abstained": True},
            correction_attempted=False,
            budget_remaining=True,
            approval_bound=False,
            can_split=True,
        )
        self.assertEqual(first["decision"], REQUIRE_SAME_AUTHORITY_CORRECTION)
        self.assertTrue(first["allow_correction"])
        self.assertFalse(first["allow_split"])
        self.assertTrue(first["abstained"])

        second = license_granularity_decision(
            {"episode_class": UNATTRIBUTED_NON_PROGRESS, "abstained": True},
            correction_attempted=True,
            budget_remaining=True,
            approval_bound=False,
            can_split=True,
        )
        self.assertEqual(second["decision"], HOLD_TERMINAL_FAILURE)
        self.assertFalse(second["allow_split"])
        self.assertFalse(second["allow_correction"])


class ImmediateMutationHintTests(unittest.TestCase):
    def test_edit_file_range_first_error_never_guesses_line_numbers_and_supports_draft_rewrite(self) -> None:
        hint = build_immediate_mutation_hint(
            "edit_file_range",
            {"path": "index.html", "end_line": 25, "new": "<canvas id='c'></canvas>"},
            "error: incomplete or truncated edit_file_range tool call; missing: start_line. No file was changed.",
            target_path="index.html",
            target_exists=True,
            target_line_count=42,
            draft_writable=True,
            repeated_count=1,
        )
        self.assertTrue(hint)
        self.assertIn("path (str)", hint)
        self.assertIn("start_line (1-based int)", hint)
        self.assertIn("end_line (1-based int >= start_line)", hint)
        self.assertIn("new (str)", hint)
        self.assertIn("Missing required field(s): start_line.", hint)
        self.assertIn(
            "Current file 'index.html' has 42 line(s); call read_file with start_line/end_line first to inspect exact line numbers.",
            hint,
        )
        self.assertIn(
            "Because 'index.html' is an unverified draft created in this transaction, you may also replace it cleanly in one call using write_file(path, content).",
            hint,
        )
        # Confirm zero line-number guessing (no start_line=1, start_line: 25, etc.)
        self.assertIsNone(re.search(r"start_line\s*[=:]\s*\d+", hint))
        self.assertIsNone(re.search(r"end_line\s*[=:]\s*\d+", hint))
        self.assertNotIn("25", hint)

        non_draft_hint = build_immediate_mutation_hint(
            "edit_file_range",
            {"path": "index.html", "start_line": 50, "end_line": 60, "new": "x"},
            "error: invalid line range 50-60; file has 42 lines",
            target_path="index.html",
            target_exists=True,
            target_line_count=42,
            draft_writable=False,
            repeated_count=1,
        )
        self.assertNotIn("write_file(path, content)", non_draft_hint)
        self.assertIn("out of bounds", non_draft_hint)

    def test_edit_file_and_write_file_and_syntax_hints(self) -> None:
        missing_old = build_immediate_mutation_hint(
            "edit_file",
            {"path": "app.py", "new": "x = 2"},
            "error: incomplete or truncated edit_file tool call; missing: old. No file was changed.",
            target_path="app.py",
            target_exists=True,
            target_line_count=15,
        )
        self.assertIn("Missing required field(s): old.", missing_old)
        self.assertIn("Current file 'app.py' has 15 line(s);", missing_old)

        zero_match = build_immediate_mutation_hint(
            "edit_file",
            {"path": "app.py", "old": "stale()", "new": "fresh()"},
            "error: expected 1 exact replacement(s), found 0; file was not changed",
            target_path="app.py",
            target_exists=True,
            target_line_count=15,
        )
        self.assertIn("matched 0 times", zero_match)

        multi_match = build_immediate_mutation_hint(
            "edit_file",
            {"path": "app.py", "old": "return 1", "new": "return 2"},
            "error: expected 1 exact replacement(s), found 3; file was not changed",
            target_path="app.py",
            target_exists=True,
            target_line_count=15,
        )
        self.assertIn("matched 3 locations", multi_match)

        missing_content = build_immediate_mutation_hint(
            "write_file",
            {"path": "index.html"},
            "error: incomplete or truncated write_file tool call; missing: content. No file was changed.",
            target_path="index.html",
            target_exists=False,
        )
        self.assertIn("write_file requires path (str) and content (str).", missing_content)
        self.assertIn("Missing required field(s): content.", missing_content)

        syntax_hint = build_immediate_mutation_hint(
            "write_file",
            {"path": "index.html", "content": "<script>import x from 'y'</script>"},
            "error: JavaScript syntax validation failed: SyntaxError: Cannot use import statement outside a module",
            target_path="index.html",
            target_exists=False,
        )
        self.assertIn("failed syntax validation", syntax_hint)
        self.assertIn("<script type=\"module\">", syntax_hint)

    def test_safety_environment_and_non_errors_emit_no_hint(self) -> None:
        self.assertEqual(
            build_immediate_mutation_hint(
                "write_file",
                {"path": "../secret.txt", "content": "x"},
                "error: '../secret.txt' is outside the workspace.",
            ),
            "",
        )
        self.assertEqual(
            build_immediate_mutation_hint(
                "write_file",
                {"path": "app.py", "content": "x"},
                "error: Repairer cannot replace files with write_file; use focused edits",
            ),
            "",
        )
        self.assertEqual(
            build_immediate_mutation_hint(
                "edit_file",
                {"path": "app.py", "old": "a", "new": "b"},
                "error writing file: permission denied",
            ),
            "",
        )
        self.assertEqual(
            build_immediate_mutation_hint(
                "write_file",
                {"path": "app.py", "content": "x = 1\n"},
                "wrote file: app.py",
            ),
            "",
        )
        self.assertEqual(
            build_immediate_mutation_hint(
                "edit_file_range",
                {"path": "app.py"},
                "error: incomplete edit_file_range tool call; missing: start_line",
                repeated_count=0,
            ),
            "",
        )


class SameAuthorityCorrectionBriefTests(unittest.TestCase):
    def test_rolled_back_files_are_explicitly_reported_as_exists_false_and_bounded(self) -> None:
        episode = {
            "episode_class": STALE_TARGET_OR_RANGE,
            "earliest_tool": "edit_file_range",
            "earliest_target": "index.html",
            "observed_codes": ["MISSING_TARGET", "TOOL_ARGUMENT_REJECTED"],
            "abstained": False,
            "rationale": "Unverified index.html draft was rolled back; subsequent range edit failed with MISSING_TARGET.",
        }
        brief = build_same_authority_correction_brief(
            episode,
            target_states=[
                {"path": "index.html", "exists": False, "line_count": None},
                {"path": "README.md", "exists": True, "line_count": 18},
            ],
            allow_draft_rewrite=False,
        )
        self.assertLess(len(brief), 1400)
        self.assertIn("index.html: exists=False", brief)
        self.assertIn("README.md: exists=True, lines=18", brief)
        self.assertIn("Authority boundary: UNCHANGED", brief)

    def test_brief_stays_under_1400_chars_under_large_inputs(self) -> None:
        episode = {
            "episode_class": BROWSER_MODULE_OR_RUNTIME_DEFECT,
            "earliest_tool": "verify_web_app",
            "earliest_target": "index.html",
            "observed_codes": ["bare_module_specifier", "missing_game_bridge", "zero_size_canvas", "page_errors"],
            "abstained": False,
            "rationale": "x" * 2000,
        }
        many_targets = [
            {"path": f"src/deeply/nested/module_{idx}.js", "exists": idx % 2 == 0, "line_count": idx * 35}
            for idx in range(20)
        ]
        brief = build_same_authority_correction_brief(
            episode,
            target_states=many_targets,
            allow_draft_rewrite=True,
        )
        self.assertLess(len(brief), 1400)
        self.assertIn("Authority boundary: UNCHANGED", brief)
        self.assertIn("exists=False", brief)
        self.assertIn("write_file(path, content)", brief)


class TextToolCallFallbackExtractionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.offered = {"read_file", "write_file", "edit_file", "edit_file_range", "verify_web_app"}

    def test_extracts_pure_json_and_single_fenced_json_variants(self) -> None:
        raw_direct = '{"name": "write_file", "arguments": {"path": "index.html", "content": "<h1>Hi</h1>"}}'
        extracted = extract_text_tool_call_fallback(raw_direct, self.offered)
        self.assertEqual(
            extracted,
            [{"function": {"name": "write_file", "arguments": {"path": "index.html", "content": "<h1>Hi</h1>"}}}],
        )

        fenced_openai = (
            "```json\n"
            '{"type": "function", "function": {"name": "edit_file_range", '
            '"arguments": {"path": "index.html", "start_line": 1, "end_line": 3, "new": "<p>ok</p>"}}}\n'
            "```"
        )
        self.assertEqual(
            extract_text_tool_call_fallback(fenced_openai, frozenset(self.offered)),
            [{
                "function": {
                    "name": "edit_file_range",
                    "arguments": {"path": "index.html", "start_line": 1, "end_line": 3, "new": "<p>ok</p>"},
                }
            }],
        )

        alt_keys = '{"tool": "read_file", "parameters": {"path": "index.html"}}'
        self.assertEqual(
            extract_text_tool_call_fallback(alt_keys, list(self.offered)),
            [{"function": {"name": "read_file", "arguments": {"path": "index.html"}}}],
        )

        wrapped_list = '{"tool_calls": [{"tool": "read_file", "args": {"path": "a.py"}}]}'
        self.assertEqual(
            extract_text_tool_call_fallback(wrapped_list, self.offered),
            [{"function": {"name": "read_file", "arguments": {"path": "a.py"}}}],
        )

        # Mixed valid + unoffered tool batch fails closed
        mixed_batch = json.dumps([
            {"name": "read_file", "arguments": {"path": "a.py"}},
            {"name": "shell_exec", "arguments": {"cmd": "whoami"}},
        ])
        self.assertEqual(extract_text_tool_call_fallback(mixed_batch, self.offered), [])

    def test_rejects_unoffered_tools_non_dict_args_and_embedded_prose_examples(self) -> None:
        # Empty offered set
        self.assertEqual(
            extract_text_tool_call_fallback('{"name": "read_file", "arguments": {"path": "a.py"}}', set()),
            [],
        )
        # Unoffered / dangerous tool name
        self.assertEqual(
            extract_text_tool_call_fallback('{"name": "delete_everything", "arguments": {"path": "."}}', self.offered),
            [],
        )
        # Non-dict arguments (string, list, missing)
        for bad_payload in (
            '{"name": "read_file", "arguments": "{\\"path\\": \\"a.py\\"}"}',
            '{"name": "read_file", "arguments": ["a.py"]}',
            '{"name": "read_file", "arguments": null}',
            '{"name": "read_file"}',
            '{"name": "read_file", "function": {"name": "write_file", "arguments": {"path": "a.py"}}}',
        ):
            with self.subTest(payload=bad_payload):
                self.assertEqual(extract_text_tool_call_fallback(bad_payload, self.offered), [])

        # Embedded inside multi-paragraph explanatory prose or negated prose
        prose_cases = [
            (
                "I analyzed the issue in detail.\n\n"
                "For example, if you wanted to inspect the file, the JSON payload would look like:\n"
                "```json\n"
                '{"name": "read_file", "arguments": {"path": "index.html"}}\n'
                "```\n\n"
                "However, the task is already finished."
            ),
            (
                "Do not execute this tool call:\n"
                "```json\n"
                '{"name": "write_file", "arguments": {"path": "index.html", "content": "bad"}}\n'
                "```"
            ),
            (
                "```json\n"
                '{"name": "read_file", "arguments": {"path": "index.html"}}\n'
                "```\n"
                "After reading that file, we will decide what to do next."
            ),
            (
                "```json\n"
                '{"name": "read_file", "arguments": {"path": "a.py"}}\n'
                "```\n"
                "```json\n"
                '{"name": "read_file", "arguments": {"path": "b.py"}}\n'
                "```"
            ),
            (
                "```python\n"
                '{"name": "read_file", "arguments": {"path": "a.py"}}\n'
                "```"
            ),
        ]
        for prose in prose_cases:
            with self.subTest(prose=prose[:45]):
                self.assertEqual(extract_text_tool_call_fallback(prose, self.offered), [])


if __name__ == "__main__":
    unittest.main()
