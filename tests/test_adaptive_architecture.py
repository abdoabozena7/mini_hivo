import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

import mini


def expanded_specification(goal="Build a focused browser application"):
    specification = {field: [] for field in mini._PROJECT_SPECIFICATION_FIELDS}
    specification["root_goal"] = goal
    return specification


class AdaptiveArchitectureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "gemma4:e4b"
        mini.reset_run("recursive")
        mini.RUN["tasks_created"] = 1

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    @staticmethod
    def contract(requirements=None):
        return {
            "status": "ready",
            "goal": "Build a difficult single-file browser application",
            "requirements": requirements or ["foundation", "behavior", "verification"],
            "constraints": ["local workspace only"],
            "success_criteria": ["all requested behavior has executable evidence"],
            "original_goal": "Build a difficult single-file browser application",
        }

    @staticmethod
    def strategy_pair():
        return [
            {
                "name": "state_transition",
                "approach": "set one explicit collision state transition then reset it",
                "scope": "one update function state boundary",
                "why_different": "uses an explicit state transition inside the existing owner",
                "verification_plan": "check the deterministic before and after state",
            },
            {
                "name": "boundary_wrapper",
                "approach": "wrap the existing collision boundary and delegate reset through the caller",
                "scope": "one caller boundary around the existing function",
                "why_different": "moves the implementation boundary to the caller instead of editing the state transition",
                "verification_plan": "check the existing function result at the caller",
            },
        ]

    @staticmethod
    def neutral_budget_failure(evidence=None):
        return {
            "status": "budget_exhausted",
            "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
            "execution_outcome": mini.EXECUTION_BUDGET_EXHAUSTED,
            "summary": "focused execution ended without verified completion",
            "memory": {},
            "step_budget": mini.MAX_TOOL_STEPS,
            "tool_steps_used": mini.MAX_TOOL_STEPS,
            "failure_evidence": evidence or [{
                "tool": "run_command", "target": "pytest", "result": "[exit_code=1]",
            }],
        }

    def test_focused_tool_budget_exhaustion_is_neutral_not_task_too_broad(self):
        tool_call = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "run_command", "arguments": {"command": "pytest"}},
            }],
        }
        with patch.object(mini, "ask_ollama", return_value=tool_call), \
                patch.object(mini, "run_tool", return_value="tool completed without verification"):
            result = mini.execute_agent_task(
                "Implement one focused behavior", {}, role="Builder", task_id="budget", max_steps=2,
            )

        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(result["failure_type"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(result["execution_outcome"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertNotEqual(result["failure_type"], "TASK_TOO_BROAD")
        self.assertEqual(result["tool_steps_used"], 2)
        self.assertEqual(mini.RUN["execution_budget_exhaustions"], 1)
        self.assertEqual(mini.RUN["task_too_broad_count"], 0)

    def test_neutral_bounded_failure_routes_to_existing_strategy_search(self):
        task = mini.make_task(
            "budget-strategy", "Implement collision reset in updateCollision()", 1, "ROOT",
            ["collision reset is verified"], ["src/game.js"],
        )
        mini.TASKS[task["id"]] = task
        failure = self.neutral_budget_failure()
        failure["repair_history"] = [{
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "repair did not satisfy deterministic verification",
        }]

        def strategy_leaf(*_args, **_kwargs):
            return {"status": "done", "summary": "alternative strategy verified", "memory": {},
                    "changed_files": ["src/game.js"]}

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=strategy_leaf):
            result = mini.solve_task(
                task, 1, self.contract(), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(task["fit_before_execution"]["decision"], "EXECUTE")
        self.assertEqual(task["initial_failure_type"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(task["execution_outcome"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(task["budget_exhaustion_routing"], "strategy")
        self.assertEqual(mini.RUN["budget_exhaustion_routed_to_strategy"], 1)
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 0)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)
        row = mini.build_node_diagnosis()[0]
        self.assertEqual(row["initial_result"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(row["final_result"], "PASS")

    def test_budget_observation_alone_does_not_diagnose_scope(self):
        task = mini.make_task(
            "budget-only", "Implement one focused behavior", 2, "ROOT",
            ["behavior is verified", "state is preserved", "result is observable"], ["src/app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        failure = self.neutral_budget_failure(evidence=[{
            "kind": "execution_outcome", "status": "FAIL",
            "evidence": mini.EXECUTION_BUDGET_EXHAUSTED,
        }])

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertEqual(diagnosis["category"], "unknown")
        self.assertNotEqual(diagnosis["category"], "scope_too_broad")

    def test_v10_shape_persistent_syntax_failure_outweighs_budget_and_depth(self):
        task = mini.make_task(
            "v10-shape", "Define and initialize the core state and basic execution loop.", mini.MAX_DEPTH,
            "parent", ["state exists", "loop exists", "update and draw exist"], ["app.js"],
        )
        task["fit_before_execution"] = {
            "decision": "EXECUTE", "reason": "hard recursion/task budget reached",
        }
        failure = self.neutral_budget_failure(evidence=[{
            "tool": "edit_file_range", "target": "app.js",
            "result": "error: JavaScript syntax validation failed: Unexpected token '}'",
        }])
        failure["repair_history"] = [{
            "status": "budget_exhausted", "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
            "summary": "fresh repair reached the focused budget with the same syntax failure",
        }]

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertEqual(diagnosis["category"], "implementation_strategy_wrong")
        self.assertEqual(diagnosis["next_action"], "search_or_mutate")
        self.assertNotEqual(diagnosis["category"], "scope_too_broad")
        self.assertFalse(diagnosis["diagnosis_evidence"]["positive_scope_evidence"])
        self.assertTrue(diagnosis["diagnosis_evidence"]["implementation_evidence"])
        self.assertEqual(
            diagnosis["diagnosis_evidence"]["execution_observation"],
            mini.EXECUTION_BUDGET_EXHAUSTED,
        )
        self.assertTrue(mini._is_bounded_implementation_failure(
            task, failure, failure["failure_evidence"],
        ))

    def test_v12_shape_preserves_repeated_mutation_evidence_at_max_depth(self):
        task = mini.make_task(
            "v12-mutation-shape", "Implement one focused behavior", mini.MAX_DEPTH,
            "parent", ["behavior is verified"], ["app.js"],
        )
        task["fit_before_execution"] = {
            "decision": "EXECUTE", "reason": "bounded focused node",
        }
        mutation = mini.mutation_failure_record(
            "edit_file", "app.js", "error: malformed edit request", role="Builder",
        )
        mutation["count"] = 2
        failure = self.neutral_budget_failure(evidence=[mutation])
        failure["repair_history"] = [{
            "status": "failed", "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
            "summary": "repair retained the mutation failure",
        }]

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertNotEqual(diagnosis["category"], "scope_too_broad")
        self.assertEqual(diagnosis["category"], "implementation_strategy_wrong")
        self.assertTrue(diagnosis["diagnosis_evidence"]["implementation_evidence"])
        self.assertEqual(
            diagnosis["diagnosis_evidence"]["mutation_evidence"][0]["category"],
            "INVALID_MUTATION",
        )

    def test_behavioral_failure_after_repair_does_not_become_scope_from_budget(self):
        task = mini.make_task(
            "behavior-budget", "Implement one focused behavior", 3, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        browser_failure = {
            "passed": False, "environment_error": False,
            "resolved_entrypoint": "index.html", "resolution_status": "RESOLVED",
            "failures": [{"code": "required_behavior", "evidence": "behavior did not occur"}],
        }
        failure = self.neutral_budget_failure(evidence=[{
            "tool": "verify_web_app", "target": "index.html",
            "result": json.dumps(browser_failure),
        }])
        failure["repair_history"] = [
            {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "repair 1 failed"},
            {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "repair 2 failed"},
        ]

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertEqual(diagnosis["category"], "implementation_strategy_wrong")
        self.assertNotEqual(diagnosis["category"], "scope_too_broad")

    def test_execute_failure_reaches_existing_strategy_search_after_evidence_precedence(self):
        task = mini.make_task(
            "syntax-strategy", "Define one focused executable behavior", mini.MAX_DEPTH, "ROOT",
            ["behavior is verified", "syntax remains valid", "the result is observable"], ["app.js"],
        )
        mini.TASKS[task["id"]] = task
        failure = self.neutral_budget_failure(evidence=[{
            "tool": "edit_file_range", "target": "app.js",
            "result": "error: JavaScript syntax validation failed: Unexpected token '}'",
        }])
        failure["repair_history"] = [{
            "status": "budget_exhausted", "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
            "summary": "same syntax failure after repair",
        }]

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                }) as strategy_leaf:
            result = mini.solve_task(
                task, mini.MAX_DEPTH, self.contract(), {}, {},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["budget_exhaustion_routed_to_strategy"], 1)
        strategy_leaf.assert_called_once()

    def test_explicit_split_fit_still_permits_scope_diagnosis(self):
        task = mini.make_task(
            "split-fit", "Implement a node with multiple responsibilities", 2, "ROOT",
            ["first", "second"], ["app.js"],
        )
        task["fit_before_execution"] = {
            "decision": "SPLIT", "reason": "multiple independent responsibilities",
        }
        failure = self.neutral_budget_failure(evidence=[{
            "kind": "execution_outcome", "status": "FAIL",
            "evidence": mini.EXECUTION_BUDGET_EXHAUSTED,
        }])

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertEqual(diagnosis["category"], "scope_too_broad")
        self.assertTrue(diagnosis["diagnosis_evidence"]["positive_scope_evidence"])

    def test_new_explicit_scope_evidence_can_overturn_execute_fit(self):
        task = mini.make_task(
            "new-scope", "Implement one focused behavior", 2, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        failure = self.neutral_budget_failure(evidence=[{
            "kind": "execution_outcome", "status": "FAIL",
            "evidence": mini.EXECUTION_BUDGET_EXHAUSTED,
        }])
        failure["scope_evidence"] = [
            "independent state transition responsibility",
            "independent browser contract responsibility",
        ]

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertEqual(diagnosis["category"], "scope_too_broad")
        self.assertTrue(diagnosis["diagnosis_evidence"]["positive_scope_evidence"])

    def test_depth_repair_limit_and_syntax_are_not_scope_evidence(self):
        cases = [
            ("depth", mini.MAX_DEPTH, mini.EXECUTION_BUDGET_EXHAUSTED, [{
                "kind": "execution_outcome", "status": "FAIL",
                "evidence": mini.EXECUTION_BUDGET_EXHAUSTED,
            }], [], "unknown"),
            ("repair-limit", mini.MAX_DEPTH, "IMPLEMENTATION_ERROR", [], [
                {"status": "failed"}, {"status": "failed"},
            ], "unknown"),
            ("syntax", 2, "IMPLEMENTATION_ERROR", [{
                "tool": "edit_file_range", "target": "app.js",
                "result": "error: JavaScript syntax validation failed: Unexpected token '}'",
            }], [], "implementation_strategy_wrong"),
        ]
        for label, depth, failure_type, evidence, repairs, expected in cases:
            with self.subTest(label=label):
                task = mini.make_task(
                    f"non-scope-{label}", "Implement one focused behavior", depth, "ROOT",
                    ["behavior is verified"], ["app.js"],
                )
                task["fit_before_execution"] = {
                    "decision": "EXECUTE", "reason": "hard recursion/task budget reached",
                }
                result = {
                    "status": "budget_exhausted" if failure_type == mini.EXECUTION_BUDGET_EXHAUSTED else "failed",
                    "failure_type": failure_type,
                    "execution_outcome": failure_type if failure_type == mini.EXECUTION_BUDGET_EXHAUSTED else None,
                    "summary": "failed deterministic evidence gate after repair limit",
                    "failure_evidence": evidence, "repair_history": repairs,
                }

                diagnosis = mini.diagnose_failure(task, result)

                self.assertEqual(diagnosis["category"], expected)
                self.assertNotEqual(diagnosis["category"], "scope_too_broad")

    def test_task_too_broad_requires_scope_assessment_provenance(self):
        def execute_task(depth=2):
            task = mini.make_task(
                "provenance", "Implement one focused behavior", depth, "ROOT",
                ["behavior is verified"], ["app.js"],
            )
            task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
            return task

        cases = [
            (
                "builder-self-report",
                {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "Builder self-report"},
            ),
            (
                "builder-tagged",
                {
                    "status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "Builder self-report",
                    "scope_provenance": {"source": "builder", "decision": "SPLIT"},
                },
            ),
            (
                "budget-marker",
                {
                    "status": "too_broad", "failure_type": "TASK_TOO_BROAD",
                    "execution_outcome": mini.EXECUTION_BUDGET_EXHAUSTED,
                    "summary": "TASK_TOO_BROAD: maximum focused tool-step budget reached",
                },
            ),
            (
                "max-depth",
                {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "max depth"},
            ),
            (
                "propagated-child",
                {
                    "status": "failed", "failure_type": "TASK_TOO_BROAD", "summary": "child failed",
                    "children": [{"result": {
                        "status": "too_broad", "failure_type": "TASK_TOO_BROAD",
                    }}],
                },
            ),
            (
                "generic-phrase",
                {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "too broad"},
            ),
        ]
        for label, result in cases:
            with self.subTest(label=label):
                task = execute_task(mini.MAX_DEPTH if label == "max-depth" else 2)
                if label == "generic-phrase":
                    task["initial_failure_type"] = "TASK_TOO_BROAD"
                    task["initial_result"] = {"failure_type": "TASK_TOO_BROAD", "summary": "another node"}
                self.assertFalse(mini._has_positive_scope_evidence(task, result))
                if label == "propagated-child":
                    diagnosis = mini.diagnose_failure(task, result)
                    self.assertNotEqual(diagnosis["category"], "scope_too_broad")
                    self.assertFalse(diagnosis["diagnosis_evidence"]["positive_scope_evidence"])

    def test_provenanced_task_too_broad_marker_counts_as_scope_evidence(self):
        task = mini.make_task(
            "provenanced-scope", "Implement one focused behavior", 2, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        result = {
            "status": "failed", "failure_type": "TASK_TOO_BROAD", "summary": "scope assessor result",
            "scope_provenance": {"source": "task_fit", "decision": "SPLIT"},
        }

        self.assertTrue(mini._has_positive_scope_evidence(task, result))
        self.assertEqual(mini.diagnose_failure(task, result)["category"], "scope_too_broad")

    def test_fresh_fit_reassessment_is_positive_scope_evidence(self):
        task = mini.make_task(
            "fresh-scope", "Implement one focused behavior", 2, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        result = {
            "status": "failed", "failure_type": "TASK_TOO_BROAD",
            "fresh_fit_assessment": {
                "decision": "SPLIT", "reason": "multiple independent responsibilities remain",
            },
        }

        self.assertTrue(mini._has_positive_scope_evidence(task, result))

    def test_unproven_builder_task_too_broad_reaches_implementation_strategy_route(self):
        task = mini.make_task(
            "builder-too-broad", "Implement one focused behavior", 2, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        mini.TASKS[task["id"]] = task
        failure = {
            "status": "too_broad", "failure_type": "TASK_TOO_BROAD",
            "summary": "Builder stopped after repeated invalid mutations",
            "failure_evidence": [{
                "tool": "edit_file_range", "target": "app.js",
                "result": "error: JavaScript syntax validation failed: Unexpected token '}'",
            }],
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                }) as strategy_leaf:
            result = mini.solve_task(
                task, task["depth"], self.contract(), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertFalse(task["failure_diagnosis"]["diagnosis_evidence"]["positive_scope_evidence"])
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        strategy_leaf.assert_called_once()

    def test_structured_mutation_evidence_reaches_existing_strategy_search(self):
        task = mini.make_task(
            "mutation-strategy", "Implement one focused behavior", mini.MAX_DEPTH, "ROOT",
            ["behavior is verified"], ["app.js"],
        )
        mini.TASKS[task["id"]] = task
        mutation = mini.mutation_failure_record(
            "edit_file", "app.js", "error: malformed edit request", role="Builder",
        )
        failure = {
            "status": "too_broad", "failure_type": "TASK_TOO_BROAD",
            "summary": "Builder stopped after repeated invalid mutations", "memory": {},
            "failure_evidence": [mutation], "mutation_failures": [mutation],
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                }) as strategy_leaf:
            result = mini.solve_task(
                task, task["depth"], self.contract(), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertTrue(task["failure_diagnosis"]["diagnosis_evidence"]["mutation_evidence"])
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        strategy_leaf.assert_called_once()

    def test_final_implementation_diagnosis_routes_after_repair_limit_without_budget_exhaustion(self):
        task = mini.make_task(
            "diagnosis-route",
            "Set up the basic HTML structure, canvas element, and initialize the game loop and core game state.",
            2, "ROOT", ["canvas and loop are verified"], ["index.html", "game.js"],
        )
        mini.TASKS[task["id"]] = task
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": {},
            "failure_evidence": [{
                "name": "browser_contract", "status": "FAIL",
                "evidence": "window.AGENT_GAME verification bridge is unavailable",
            }],
            "repair_history": [
                {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "repair 1 failed"},
                {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "repair 2 failed"},
            ],
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                    "changed_files": ["game.js"],
                }):
            result = mini.solve_task(
                task, 2, self.contract(), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "model × task fit"},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(task["fit_before_execution"]["decision"], "EXECUTE")
        self.assertEqual(task["initial_failure_type"], "IMPLEMENTATION_ERROR")
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(mini.RUN["execution_budget_exhaustions"], 0)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 1)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)
        self.assertIsNone(task["resplit"])

    def test_final_strategy_diagnosis_routes_budget_origin_without_repair_history(self):
        task = mini.make_task(
            "diagnosis-route-budget-origin", "Implement one focused behavior", 1, "ROOT",
            ["behavior is verified"], ["src/app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        mini.TASKS[task["id"]] = task
        failure = {
            "status": "budget_exhausted", "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
            "execution_outcome": mini.EXECUTION_BUDGET_EXHAUSTED,
            "summary": "focused execution exhausted its budget after a deterministic failure",
            "memory": {},
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
            "failure_diagnosis": {
                "category": "implementation_strategy_wrong", "confidence": "medium",
                "next_action": "search_or_mutate",
            },
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                }):
            result = mini.solve_task(
                task, 1, self.contract(), {}, {},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 1)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)

    def test_final_diagnosis_route_preserves_existing_strategy_a_then_b_order(self):
        task = mini.make_task(
            "diagnosis-route-ab", "Implement one focused behavior", 1, "ROOT",
            ["behavior is verified"], ["src/app.js"],
        )
        mini.TASKS[task["id"]] = task
        initial = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": {},
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
            "repair_history": [{"status": "failed", "summary": "repair failed"}],
        }
        strategy_a_failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "Strategy A failed fresh verification", "memory": {},
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        strategy_b_success = {
            "status": "done", "summary": "Strategy B verified", "memory": {},
            "changed_files": ["src/app.js"],
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=[strategy_a_failure, strategy_b_success]):
            result = mini.solve_task(
                task, 1, self.contract(), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                leaf_executor=Mock(return_value=initial),
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 2)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)
        self.assertEqual(
            [item["status"] for item in task["strategy_attempts"]], ["FAIL", "PASS"],
        )

    def test_diagnosis_router_uses_final_category_and_blocks_exclusions_and_double_trigger(self):
        task = mini.make_task(
            "diagnosis-router", "Implement one focused behavior", 1, "ROOT",
            ["behavior is verified"], ["src/app.js"],
        )
        task["fit_before_execution"] = {"decision": "EXECUTE", "reason": "focused node"}
        task["failure_diagnosis"] = {"category": "scope_too_broad"}
        mini.TASKS[task["id"]] = task
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": {},
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
            "repair_history": [{"status": "failed", "summary": "repair failed"}],
        }
        final_diagnosis = {
            "category": "implementation_strategy_wrong", "confidence": "medium",
            "next_action": "search_or_mutate",
        }
        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}) as planner, \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "verified", "memory": {},
                }) as leaf:
            first = mini.route_recovery_from_diagnosis(
                task, self.contract(), failure, final_diagnosis, {}, {},
            )
            second = mini.route_recovery_from_diagnosis(
                task, self.contract(), failure, final_diagnosis, {}, {},
            )

        self.assertEqual(first["status"], "done")
        self.assertIsNone(second)
        self.assertEqual(planner.call_count, 1)
        self.assertEqual(leaf.call_count, 1)
        self.assertEqual(mini.RUN["strategy_searches"], 1)

        for category in (
            "scope_too_broad", "dependency_error", "verifier_builder_mismatch",
            "environment_failure", "model_capability_floor",
        ):
            with self.subTest(category=category), patch.object(mini, "_maybe_search_alternate_strategy") as search:
                self.assertIsNone(mini.route_recovery_from_diagnosis(
                    task, self.contract(), failure, {"category": category}, {}, {},
                ))
                search.assert_not_called()

        integration = mini.make_task(
            "integration-route", "Resolve one integration conflict", 1, "ROOT",
            ["conflict is resolved"], ["app.js"], kind="integration",
        )
        with patch.object(mini, "_maybe_search_alternate_strategy") as search:
            self.assertIsNone(mini.route_recovery_from_diagnosis(
                integration, self.contract(), failure, final_diagnosis, {}, {},
            ))
            search.assert_not_called()

    def test_neutral_broad_failure_routes_to_existing_decomposition(self):
        contract = self.contract(["state", "behavior", "verification"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        failure = self.neutral_budget_failure()
        failure["scope_evidence"] = [
            "independent state responsibility",
            "independent behavior responsibility",
            "independent verification responsibility",
        ]
        leaf_calls = []

        def fit(*_args):
            return {"decision": "execute", "reason": "initial fit accepted"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                child_id = f"{task['id']}.{index}"
                child = mini.make_task(
                    child_id, f"focused child {index}", task["depth"] + 1, task["id"],
                    [f"child {index} is verified"], ["src/game.js"],
                )
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            leaf_calls.append(task["id"])
            return failure if task["id"] == "ROOT" else {
                "status": "done", "summary": f"verified {task['id']}", "memory": memory,
            }

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf,
                aggregator=lambda _task, _contract, _children, memory, _repo, root=False: {
                    "status": "done", "summary": "integrated", "memory": memory,
                },
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(leaf_calls, ["ROOT", "ROOT.1", "ROOT.2"])
        self.assertEqual(root["resplit"]["trigger"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(root["initial_failure_type"], mini.EXECUTION_BUDGET_EXHAUSTED)
        self.assertEqual(mini.RUN["budget_exhaustion_routed_to_scope"], 1)
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 1)
        self.assertEqual(mini.RUN["strategy_searches"], 0)

    def test_neutral_provider_dependency_and_verifier_failures_do_not_route_to_search(self):
        cases = [
            ("environment_failure", [{"tool": "run_command", "result": "provider unavailable"}]),
            ("dependency_error", [{"tool": "run_command", "result": "Module not found: state.js"}]),
            ("verifier_builder_mismatch", [{
                "kind": "builder_tool_evidence", "status": "FAIL",
                "evidence": "no executable verification was attempted",
            }]),
        ]
        for expected, evidence in cases:
            with self.subTest(expected=expected):
                task = mini.make_task(
                    f"budget-{expected}", "Implement one focused behavior", 1, "ROOT",
                    ["behavior is verified"], ["src/app.js"],
                )
                mini.TASKS[task["id"]] = task
                failure = self.neutral_budget_failure(evidence)
                with patch.object(mini, "decompose_task") as decompose, \
                        patch.object(mini, "_maybe_search_alternate_strategy") as strategy:
                    result = mini.solve_task(
                        task, 1, self.contract(["one focused behavior"]), {}, {},
                        fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                        leaf_executor=Mock(return_value=failure),
                    )

                self.assertEqual(result["failure_type"], mini.EXECUTION_BUDGET_EXHAUSTED)
                self.assertEqual(task["failure_diagnosis"]["category"], expected)
                decompose.assert_not_called()
                strategy.assert_not_called()

    def test_budget_neutral_terminal_leaf_is_not_capability_floor_without_strategy_search(self):
        task = mini.make_task(
            "terminal", "Implement collision reset in updateCollision()", mini.MAX_DEPTH, "parent",
            ["collision reset is verified"], ["src/game.js"],
        )
        mini.TASKS[task["id"]] = task
        failure = self.neutral_budget_failure(evidence=[{
            "kind": "budget", "status": "NEUTRAL",
            "evidence": "budget ended before implementation evidence was available",
        }])
        with patch.object(mini, "decompose_task") as decompose, \
                patch.object(mini, "_maybe_search_alternate_strategy", return_value=None) as strategy:
            result = mini.solve_task(
                task, mini.MAX_DEPTH, self.contract(["one focused behavior"]), {}, {},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "budget_exhausted")
        self.assertEqual(task["failure_diagnosis"]["category"], "unknown")
        self.assertNotEqual(task["failure_diagnosis"]["category"], "model_capability_floor")
        strategy.assert_not_called()
        decompose.assert_not_called()
        mini.recompute_search_metrics()
        self.assertEqual(mini.RUN["capability_floor_nodes"], 0)

    def test_neutral_failure_with_two_failed_strategies_can_reach_capability_floor(self):
        task = mini.make_task(
            "strategy-floor", "Implement one focused behavior", 1, "ROOT",
            ["behavior is verified"], ["src/app.js"],
        )
        mini.TASKS[task["id"]] = task
        initial = self.neutral_budget_failure()
        initial["repair_history"] = [{
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "repair did not satisfy deterministic verification",
        }, {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "second repair did not satisfy deterministic verification",
        }]
        strategy_failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "alternate strategy verification failed", "memory": {},
            "failure_evidence": [{"tool": "run_command", "target": "pytest", "result": "[exit_code=1]"}],
        }
        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=[strategy_failure, strategy_failure]):
            result = mini.solve_task(
                task, 1, self.contract(["one focused behavior"]), {}, {},
                fit_decider=lambda *_args: {"decision": "execute", "reason": "focused node"},
                leaf_executor=Mock(return_value=initial),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(task["failure_diagnosis"]["category"], "model_capability_floor")
        self.assertEqual(len(task["strategy_attempts"]), 2)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 2)
        self.assertEqual(mini.RUN["strategy_rescues"], 0)
        floor_evidence = task["failure_diagnosis"]["capability_floor_evidence"]
        self.assertIn("strategy_A", floor_evidence["exhausted_recoveries"])
        self.assertIn("strategy_B", floor_evidence["exhausted_recoveries"])
        self.assertTrue(mini.can_declare_capability_floor(
            task, task["failure_diagnosis"], result["failure_evidence"], result,
        ))
        mini.recompute_search_metrics()
        self.assertEqual(mini.RUN["capability_floor_nodes"], 1)

    def test_budget_outcome_does_not_override_integration_preflight_failure(self):
        builder = {
            "status": "budget_exhausted", "failure_type": mini.EXECUTION_BUDGET_EXHAUSTED,
        }
        gate = {"deterministic_failures": [{
            "name": "integration_preflight", "status": "FAIL", "kind": "integration_preflight",
        }]}

        self.assertEqual(
            mini.classify_failure(builder, gate),
            "INTEGRATION_FAILURE",
        )

    def test_hard_mock_reaches_depth_four_and_exceeds_old_eight_task_limit(self):
        contract = self.contract()
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        observed = []

        def fit(task, depth, *_args):
            return {"decision": "split" if depth < 4 else "execute"}

        def decompose(task, _contract, _repo, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                task_id = str(index) if task["id"] == "ROOT" else f"{task['id']}.{index}"
                child = mini.make_task(
                    task_id,
                    f"{task['goal']} milestone {index}",
                    task["depth"] + 1,
                    task["id"],
                    [f"milestone {index} verified"],
                    ["shared/index.html"],
                )
                mini.TASKS[task_id] = child
                task["children"].append(task_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            observed.append(task["id"])
            return {"status": "done", "summary": f"verified {task['id']}", "memory": memory}

        def aggregate(task, _contract, children, memory, _repo, root=False):
            self.assertTrue(all(item["result"]["status"] == "done" for item in children))
            return {"status": "done", "summary": f"integrated {task['id']}", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN["max_depth"], 4)
        self.assertGreater(mini.RUN["tasks_created"], 8)
        self.assertLessEqual(mini.RUN["tasks_created"], mini.MAX_TOTAL_TASKS)
        self.assertEqual(mini.RUN["splits"], 15)
        self.assertTrue(observed)

    def test_single_file_hard_work_is_allowed_to_split_into_sequential_milestones(self):
        contract = self.contract(["shell", "movement", "collision", "win"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        calls = []

        def fit(task, _depth, *_args):
            return {"decision": "split" if task["id"] == "ROOT" else "execute"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index, name in enumerate(("establish shell", "add behavior", "finish verification"), 1):
                child_id = str(index)
                child = mini.make_task(child_id, name, 1, "ROOT", [f"{name} verified"], ["index.html"])
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            calls.append(task["goal"])
            return {"status": "done", "summary": "verified", "memory": memory, "changed_files": ["index.html"]}

        def aggregate(_task, _contract, _children, memory, _repo, root=False):
            return {"status": "done", "summary": "integrated sequential milestones", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(calls, ["establish shell", "add behavior", "finish verification"])
        self.assertTrue(all(mini.TASKS[str(i)]["scope_hint"] == ["index.html"] for i in range(1, 4)))

    def test_node_packet_contains_only_bounded_contract_and_verified_projections(self):
        contract = self.contract([f"root requirement {index}" for index in range(20)])
        task = mini.make_task(
            "2.1", "Implement the focused behavior", 2, "2", ["behavior passes"], ["src/app.js"],
        )
        packet = mini.build_node_context(
            task,
            contract,
            None,
            {"files": [{"path": "src/app.js", "size": 10}], "languages": ["javascript"],
             "configs": [], "tests": [], "entrypoints": [], "truncated": False},
            parent_summary="parent goal | parent verified summary",
            dependency_summaries=[{
                "task_id": "2.0", "goal": "previous milestone", "status": "done",
                "summary": "verified interface", "conversation": "SECRET SIBLING CHAT HISTORY",
            }],
        )

        self.assertLessEqual(len(packet), mini.MAX_NODE_PACKET_CHARS)
        for marker in ("ROOT CONTRACT:", "CURRENT NODE:", "PARENT", "DEPENDENCIES", "RELEVANT PROJECT MEMORY:",
                       "FAILURE EVIDENCE:", "REPOSITORY HINTS:"):
            self.assertIn(marker, packet)
        self.assertIn("root requirement 0", packet)
        self.assertIn("Implement the focused behavior", packet)
        self.assertIn("parent verified summary", packet)
        self.assertIn("verified interface", packet)
        self.assertNotIn("SECRET SIBLING CHAT HISTORY", packet)

    def test_short_prompt_expansion_is_bounded_and_non_mutating(self):
        contract = self.contract(["timer controls", "persist settings"])
        response = expanded_specification(contract["goal"])
        response.update({
            "root_goal": "model must not replace the authoritative goal",
            "user_visible_behavior": ["the timer starts and pauses visibly"],
            "major_functional_areas": ["timer controls", "settings persistence"],
            "architecture_invariants": ["one authoritative timer state owner"],
            "acceptance_criteria": ["a deterministic timer check passes"],
        })
        calls = []

        def structured(prompt_text, _validator, label, schema):
            calls.append((prompt_text, label, schema))
            return response

        before = sorted(path.relative_to(mini.WORKSPACE).as_posix()
                        for path in mini.WORKSPACE.rglob("*"))
        specification = mini.expand_project_specification(
            "Build a timer", contract, structured_call=structured,
        )
        after = sorted(path.relative_to(mini.WORKSPACE).as_posix()
                       for path in mini.WORKSPACE.rglob("*"))

        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "specification-expansion")
        self.assertIn("Do not write code", calls[0][0])
        self.assertLessEqual(len(json.dumps(specification)), mini.MAX_PROJECT_SPECIFICATION_CHARS)
        self.assertIn("timer controls", specification["major_functional_areas"])
        self.assertEqual(specification["root_goal"], contract["goal"])
        self.assertEqual(before, after)

    def test_project_brain_core_and_verified_state_are_separate(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        specification.update({
            "major_functional_areas": ["HUD rendering"],
            "major_system_components": ["HUD renderer"],
            "state_ownership": ["the HUD reads the authoritative game state"],
            "architecture_invariants": ["preserve one authoritative render loop"],
            "interface_contracts": ["HUD renderer reads gameState.score"],
            "project_specific_coding_constraints": ["keep update and render responsibilities separate"],
        })
        brain = mini.build_project_brain(contract, specification, {
            "files": [{"path": "game.js", "size": 10}], "languages": ["javascript"],
            "configs": [], "tests": [], "entrypoints": ["index.html"], "truncated": False,
        })

        self.assertEqual(brain["core"]["root_goal"], contract["goal"])
        for field in ("product_contract", "major_components", "architecture_invariants",
                      "state_ownership", "interface_contracts", "project_specific_quality_rules",
                      "interaction_contracts", "acceptance_criteria", "non_goals",
                      "explicit_assumptions"):
            self.assertIn(field, brain["core"])
        self.assertNotIn("verified_state", brain["core"])
        self.assertIsInstance(brain["verified_state"]["files"], list)
        self.assertIsNot(brain["core"], brain["verified_state"])

    def test_brain_projection_selects_relevant_invariants_and_excludes_unrelated_sections(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        specification.update({
            "major_functional_areas": ["HUD rendering", "enemy AI"],
            "major_system_components": ["HUD renderer", "enemy controller"],
            "architecture_invariants": ["preserve one authoritative HUD render loop",
                                          "enemy AI owns enemy pursuit state"],
            "project_specific_coding_constraints": ["reuse the existing HUD state projection",
                                                     "do not duplicate enemy AI state"],
        })
        brain = mini.build_project_brain(contract, specification, {"files": []})
        task = mini.make_task("hud", "Implement responsive HUD rendering", 1, "ROOT",
                              ["HUD rendering is verified"], ["style.css"])
        projection = mini.build_brain_projection(brain, task, repo_snapshot={})
        encoded = json.dumps(projection, ensure_ascii=False)

        self.assertIn("HUD", encoded)
        self.assertNotIn("enemy AI", encoded)
        self.assertEqual(projection["root_goal_anchor"], contract["goal"])
        self.assertLessEqual(len(json.dumps(projection)), mini.MAX_BRAIN_PROJECTION_CHARS)

    def test_child_planning_packet_uses_task_projection_not_full_brain(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        specification.update({
            "major_functional_areas": ["HUD rendering", "enemy AI"],
            "major_system_components": ["HUD renderer", "enemy controller"],
            "architecture_invariants": ["preserve one authoritative HUD render loop",
                                          "enemy AI owns enemy pursuit state"],
        })
        mini.RUN["project_brain"] = mini.build_project_brain(contract, specification, {"files": []})
        task = mini.make_task("hud", "Implement responsive HUD rendering", 1, "ROOT",
                              ["HUD rendering is verified"], ["style.css"])
        packet = mini.project_brain_task_planning_packet(task, repo_snapshot={}, max_chars=3000)

        self.assertIn("HUD", packet)
        self.assertNotIn("enemy AI", packet)
        self.assertLessEqual(len(packet), 3000)

    def test_root_decomposition_prompt_consumes_expanded_project_brain(self):
        contract = self.contract(["render the HUD", "persist settings"])
        specification = expanded_specification(contract["goal"])
        specification["major_functional_areas"] = ["HUD rendering"]
        specification["major_system_components"] = ["HUD renderer"]
        brain = mini.build_project_brain(contract, specification, {"files": []})
        mini.RUN["project_brain"] = brain
        task = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = task
        mini.RUN["tasks_created"] = 1
        response = {"children": [
            {"goal": "render HUD", "done_when": ["HUD is verified"], "scope_hint": ["style.css"]},
            {"goal": "persist settings", "done_when": ["settings reload is verified"], "scope_hint": ["storage.js"]},
        ]}
        with patch.object(mini, "structured_model_call", return_value=response) as structured:
            children = mini.decompose_task(task, contract, {"files": []})

        prompt = structured.call_args.args[0]
        self.assertEqual(len(children), 2)
        self.assertIn("PROJECT BRAIN (expanded specification + verified state)", prompt)
        self.assertIn("HUD renderer", prompt)

    def test_recursive_request_expands_raw_prompt_before_tree_execution(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        with patch.object(mini, "get_goal_contract", return_value=contract), \
                patch.object(mini, "expand_project_specification", return_value=specification) as expand, \
                patch.object(mini, "solve_task", return_value={"status": "done", "summary": "verified", "memory": {}}):
            result, _memory = mini.run_recursive_request(
                "Build a short HUD request", {}, repo_snapshot={}, reset=True, finish=False,
            )

        self.assertEqual(result["status"], "done")
        expand.assert_called_once_with("Build a short HUD request", contract)
        self.assertEqual(mini.RUN["project_brain"]["core"]["root_goal"], contract["goal"])

    def test_mission_compiler_receives_one_bounded_node_and_verified_dependencies(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        specification.update({
            "major_functional_areas": ["HUD rendering"],
            "major_system_components": ["HUD renderer"],
            "architecture_invariants": ["preserve one authoritative render loop"],
            "project_specific_coding_constraints": ["keep update and render separate"],
        })
        brain = mini.build_project_brain(contract, specification, {"files": []})
        task = mini.make_task("hud", "Implement responsive HUD rendering", 1, "ROOT",
                              ["HUD rendering is verified"], ["style.css"])
        projection = mini.build_brain_projection(brain, task, repo_snapshot={})
        prompts = []

        def structured(prompt_text, _validator, label, _schema):
            prompts.append((prompt_text, label))
            return {
                "goal_anchor": "wrong anchor is normalized",
                "task": "wrong task is normalized",
                "expected_outcome": "HUD is verified",
                "targets": ["style.css"],
                "existing_facts": ["reuse HUD renderer"],
                "implementation_plan": ["extend the existing HUD owner"],
                "interfaces_to_reuse": ["gameState.score"],
                "invariants": ["preserve one authoritative render loop"],
                "project_specific_quality_rules": ["keep update and render separate"],
                "do_not": ["create a second render loop"],
                "verification_plan": ["run the deterministic HUD check"],
                "done_when": ["HUD rendering is verified"],
            }

        mission = mini.compile_worker_mission(
            task, projection,
            dependency_summaries=[{
                "task_id": "state", "goal": "verified state", "status": "done",
                "summary": "score interface verified", "changed_files": ["game.js"],
                "conversation": "SECRET SIBLING HISTORY MUST NOT LEAK",
            }],
            repo_snapshot={"files": [{"path": "style.css", "size": 10}]},
            structured_call=structured,
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual(prompts[0][1], "mission-compilation")
        self.assertIn('"id": "hud"', prompts[0][0])
        self.assertIn("score interface verified", prompts[0][0])
        self.assertNotIn("SECRET SIBLING HISTORY", prompts[0][0])
        self.assertEqual(mission["task"], task["goal"])
        self.assertEqual(mission["goal_anchor"], brain["core"]["root_goal"])
        self.assertIn("keep update and render separate", mission["project_specific_quality_rules"])
        compiler_context = prompts[0][0].split("BOUNDED COMPILER CONTEXT:\n", 1)[1]
        self.assertLessEqual(len(compiler_context), mini.MAX_MISSION_COMPILER_CONTEXT_CHARS)
        self.assertIsInstance(json.loads(compiler_context), dict)
        self.assertLessEqual(len(json.dumps(mission)), mini.MAX_WORKER_MISSION_CHARS)

    def test_recursive_leaf_compiles_and_injects_structured_mission(self):
        contract = self.contract(["render the HUD"])
        specification = expanded_specification(contract["goal"])
        specification["major_functional_areas"] = ["HUD rendering"]
        brain = mini.build_project_brain(contract, specification, {"files": []})
        mini.RUN["project_brain"] = brain
        task = mini.make_task("hud", "Implement HUD rendering", 1, "ROOT", ["HUD is verified"], ["game.js"])
        mission = {
            "goal_anchor": contract["goal"], "task": task["goal"],
            "expected_outcome": "HUD is verified", "targets": ["game.js"],
            "existing_facts": [], "implementation_plan": ["extend HUD"],
            "interfaces_to_reuse": [], "invariants": [],
            "project_specific_quality_rules": ["preserve HUD owner"], "do_not": [],
            "verification_plan": ["run deterministic verification"],
            "done_when": task["done_when"],
        }
        builder = {
            "status": "done", "summary": "HUD verified", "memory": {},
            "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}],
        }
        with patch.object(mini, "compile_worker_mission", return_value=mission) as compile, \
                patch.object(mini, "execute_agent_task", return_value=builder) as worker, \
                patch.object(mini, "falsify_task", return_value={"status": "done", "memory": {},
                                                                    "tool_evidence": []}), \
                patch.object(mini, "optional_browser_check", return_value=None), \
                patch.object(mini, "evidence_gate", return_value={"passed": True,
                                                                     "deterministic_failures": []}):
            result = mini.execute_leaf(task, contract, {}, {"files": []})

        self.assertEqual(result["status"], "done")
        compile.assert_called_once()
        self.assertIn("WORKER MISSION", worker.call_args.kwargs["extra_context"])
        self.assertIn("preserve HUD owner", worker.call_args.kwargs["extra_context"])

    def test_mission_compilation_failure_is_orchestration_failure_before_worker(self):
        contract = self.contract(["render the HUD"])
        brain = mini.build_project_brain(contract, expanded_specification(contract["goal"]), {"files": []})
        mini.RUN["project_brain"] = brain
        task = mini.make_task("hud", "Implement HUD rendering", 1, "ROOT", ["HUD is verified"], ["game.js"])
        with patch.object(mini, "compile_worker_mission",
                          side_effect=mini.MissionCompilationError("invalid mission")), \
                patch.object(mini, "execute_agent_task") as worker:
            result = mini.execute_leaf(task, contract, {}, {"files": []})

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], "ORCHESTRATION_FAILURE")
        self.assertEqual(result["orchestration_failure"], "MISSION_COMPILATION_FAILURE")
        worker.assert_not_called()
        self.assertEqual(mini.diagnose_failure(task, result)["category"], "orchestration_failure")

    def test_verified_manifests_update_only_brain_verified_state(self):
        contract = self.contract(["render the HUD"])
        brain = mini.build_project_brain(contract, expanded_specification(contract["goal"]), {"files": []})
        mini.RUN["project_brain"] = brain
        core_before = json.dumps(brain["core"], sort_keys=True)
        child = mini.make_task("state", "verified state", 1, "ROOT", ["state verified"], [])
        result = {
            "status": "done", "summary": "state verified", "memory": {}, "changed_files": [],
            "integration_manifest": {
                "interfaces": ["gameState.score"], "invariants": ["one state owner"],
                "verification": ["deterministic check passed"],
            },
        }
        mini._mark_task_result(child, result)

        self.assertEqual(json.dumps(brain["core"], sort_keys=True), core_before)
        self.assertIn("gameState.score", json.dumps(brain["verified_state"], ensure_ascii=False))

    def test_verified_child_exposes_bounded_integration_manifest_to_parent(self):
        child = mini.make_task("1", "own persistence", 1, "ROOT", ["persistence verified"], ["storage.js"])
        result = {
            "status": "done", "summary": "persistence verified", "memory": {},
            "changed_files": [str(mini.WORKSPACE / "storage.js")],
            "integration_manifest": {
                "introduced_symbols": ["STORAGE_KEY"],
                "modified_symbols": ["saveState"],
                "interfaces": ["gameState.settings"],
                "assumptions": ["gameState is the single source of truth"],
                "invariants": ["only one persistence owner exists"],
                "verification": ["storage reload check passed"],
            },
        }

        mini._mark_task_result(child, result)

        manifest = child["integration_manifest"]
        self.assertEqual(manifest["status"], "verified")
        self.assertEqual(manifest["changed_files"], ["storage.js"])
        self.assertIn("STORAGE_KEY", manifest["introduced_symbols"])
        self.assertIn("gameState.settings", manifest["interfaces"])
        self.assertTrue(any(item["kind"] == "verified_invariant" for item in mini.RUN["project_invariants"]))

        packet = mini.build_node_context(
            mini.make_task("2", "connect behavior", 1, "ROOT", ["behavior verified"], ["game.js"]),
            self.contract(), None, {}, dependency_summaries=[{
                "task_id": "1", "goal": child["goal"], "status": "done", "summary": child["summary"],
                "changed_files": child["changed_files"], "integration_manifest": manifest,
            }],
        )
        self.assertIn("PROJECT INVARIANTS", packet)
        self.assertIn("STORAGE_KEY", packet)
        self.assertIn("gameState.settings", packet)
        self.assertFalse(any(item["kind"] == "verified_assumption"
                             for item in mini.RUN["project_invariants"]))

    def test_integration_preflight_catches_obvious_composition_conflicts(self):
        (mini.WORKSPACE / "app.js").write_text(
            "const STORAGE_KEY = 'one';\nconst STORAGE_KEY = 'two';\n",
            encoding="utf-8",
        )
        (mini.WORKSPACE / "loop-a.js").write_text(
            "function loopA() { requestAnimationFrame(loopA); }\n",
            encoding="utf-8",
        )
        (mini.WORKSPACE / "loop-b.js").write_text(
            "function loopB() { requestAnimationFrame(loopB); }\n",
            encoding="utf-8",
        )
        (mini.WORKSPACE / "index.html").write_text(
            "<div id='app'></div><div id='app'></div>", encoding="utf-8",
        )
        (mini.WORKSPACE / "main.html").write_text("<h1>second entry</h1>", encoding="utf-8")

        preflight = mini.run_integration_preflight(
            mini.make_task("ROOT", "integrate", 0, None, ["integrated"], []), [], self.contract(),
        )
        kinds = {item["kind"] for item in preflight["conflicts"]}
        self.assertFalse(preflight["passed"])
        self.assertEqual(preflight["current_syntax"], "FAIL")
        self.assertIn("duplicate_declaration", kinds)
        self.assertIn("syntax_error", kinds)
        self.assertIn("duplicate_html_id", kinds)
        self.assertIn("multiple_obvious_game_loops", kinds)
        self.assertIn("conflicting_entry_points", kinds)
        self.assertIn("multiple_persistence_keys", {item["kind"] for item in preflight["warnings"]})

    def test_persistence_preflight_uses_generic_ownership_patterns(self):
        (mini.WORKSPACE / "storage-a.js").write_text(
            "const APP_SESSION_KEY = 'shared';\nlocalStorage.setItem(APP_SESSION_KEY, 'a');\n",
            encoding="utf-8",
        )
        (mini.WORKSPACE / "storage-b.js").write_text(
            "const CACHE_KEY = 'shared';\nlocalStorage.setItem(CACHE_KEY, 'b');\n",
            encoding="utf-8",
        )

        preflight = mini.run_integration_preflight(
            mini.make_task("ROOT", "integrate", 0, None, ["integrated"], []), [], self.contract(),
        )

        conflicts = {item["kind"] for item in preflight["conflicts"]}
        self.assertIn("conflicting_persistence_ownership", conflicts)
        self.assertTrue(any(item["symbol"] in {"APP_SESSION_KEY", "CACHE_KEY"}
                            for item in preflight["project_invariants"]
                            if item["kind"] == "persistence_owner"))
        self.assertNotIn("STORAGE_KEY", json.dumps(preflight))

    def test_parent_integration_metrics_track_recovery_and_success_rate(self):
        task = mini.make_task("ROOT", "integrate", 0, None, ["integrated"], [])
        before = {
            "passed": False, "error_count": 2, "invariant_violation_count": 2,
            "conflicts": [{"kind": "duplicate_declaration"}, {"kind": "duplicate_html_id"}],
        }
        after = {"passed": True, "error_count": 0, "conflicts": []}

        mini._start_parent_integration(task, before)
        mini._finish_parent_integration(task, passed=True, recovered=True, preflight=after)

        self.assertEqual(mini.RUN["parent_integrations_attempted"], 1)
        self.assertEqual(mini.RUN["parent_integrations_passed"], 1)
        self.assertEqual(mini.RUN["parent_integrations_failed"], 0)
        self.assertEqual(mini.RUN["parent_integrations_recovered"], 1)
        self.assertEqual(mini.RUN["integration_preflight_conflicts"], 2)
        self.assertEqual(mini.RUN["integration_conflicts_resolved"], 2)
        self.assertEqual(mini.RUN["invariant_violations_detected"], 2)
        self.assertEqual(mini.RUN["integration_success_rate"], 100.0)
        self.assertEqual(task["integration_outcome"]["conflicts_resolved"], 2)

    def test_integration_fit_uses_milestones_only_for_corruption_boundary(self):
        children = [{
            "task_id": str(index), "goal": f"child {index}", "status": "done", "verification": "passed",
            "integration_manifest": {
                "status": "verified", "changed_files": [f"file-{index}.js"],
                "introduced_symbols": ["STORAGE_KEY" if index < 3 else f"symbol{index}"],
                "modified_symbols": [], "interfaces": [f"state.part{index}"],
                "assumptions": [], "invariants": [], "verification": ["passed"],
            },
        } for index in (1, 2, 3)]
        preflight = {
            "passed": False, "status": "FAIL", "current_syntax": "FAIL",
            "conflicts": [{"kind": "duplicate_declaration", "severity": "error", "message": "duplicate STORAGE_KEY"}],
            "warnings": [], "project_invariants": [],
        }

        fit = mini.decide_integration_fit({}, children, preflight)
        packet = mini.build_integration_contract(
            {"goal": "integrate", "done_when": []}, self.contract(), children, preflight, root=True, fit=fit,
        )
        self.assertEqual(fit["decision"], "split")
        self.assertEqual(packet["current_syntax"], "FAIL")
        self.assertEqual(packet["verified_children"][0]["manifest"]["status"], "verified")
        self.assertIn("normalize_shared_state", fit["milestones"])

    def test_integration_milestone_path_records_bounded_repair_evidence(self):
        task = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        child_info = [{
            "task_id": str(index), "goal": f"child {index}", "status": "done", "verification": "passed",
            "integration_manifest": {"status": "verified", "changed_files": [f"file-{index}.js"],
                                     "introduced_symbols": [f"symbol{index}"], "modified_symbols": [],
                                     "interfaces": [f"state.part{index}"], "assumptions": [],
                                     "invariants": [], "verification": ["passed"]},
        } for index in (1, 2, 3)]
        preflight = {"passed": False, "status": "FAIL", "current_syntax": "FAIL",
                     "conflicts": [{"kind": "duplicate_declaration", "severity": "error",
                                    "message": "duplicate STORAGE_KEY"}],
                     "warnings": [], "project_invariants": []}
        contract = self.contract()
        integration_contract = mini.build_integration_contract(
            task, contract, child_info, preflight, root=True,
            fit=mini.decide_integration_fit(task, child_info, preflight),
        )
        calls = []

        def builder(goal, memory, **kwargs):
            calls.append(kwargs["task_id"])
            return {"status": "done", "summary": "milestone verified", "memory": memory,
                    "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]}

        with patch.object(mini, "execute_agent_task", side_effect=builder):
            result = mini.run_integration_milestones(task, contract, child_info, {}, {}, integration_contract)

        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["integration_milestones"]), 5)
        self.assertEqual(len(calls), 5)
        self.assertEqual(mini.RUN["integration_milestone_runs"], 1)
        self.assertEqual(mini.RUN["integration_milestone_steps"], 5)
        self.assertIn("current_syntax", result["integration_preflight"])

    def test_parent_too_broad_is_not_reclassified_as_scope_failure(self):
        task = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        children = [{
            "task": {"id": "1", "goal": "child", "verification_status": "passed"},
            "result": {"status": "done", "summary": "verified", "memory": {}, "changed_files": []},
        }, {
            "task": {"id": "2", "goal": "child two", "verification_status": "passed"},
            "result": {"status": "done", "summary": "verified", "memory": {}, "changed_files": []},
        }]
        with patch.object(mini, "execute_agent_task", return_value={
            "status": "too_broad", "failure_type": "TASK_TOO_BROAD",
            "summary": "integration mutation budget exhausted", "memory": {}, "tool_evidence": [],
        }):
            result = mini.aggregate_task(task, self.contract(), children, {}, {}, root=True)

        self.assertEqual(result["failure_type"], "INTEGRATION_TOO_BROAD")
        mini._mark_task_result(task, result)
        self.assertEqual(task["failure_diagnosis"]["category"], "local_integration_state_corruption")
        self.assertEqual(task["failure_diagnosis"]["next_action"], "parent_repair")

    def test_integration_preflight_failure_is_a_deterministic_gate(self):
        gate = mini.evidence_gate(
            {"status": "done", "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]},
            integration_preflight={
                "passed": False, "current_syntax": "FAIL",
                "conflicts": [{"kind": "duplicate_declaration", "message": "duplicate STORAGE_KEY"}],
                "warnings": [],
            },
        )
        self.assertFalse(gate["passed"])
        self.assertIn("integration_preflight", {item["name"] for item in gate["deterministic_failures"]})

    def test_baseline_and_recursive_call_the_same_leaf_engine(self):
        contract = self.contract(["one focused behavior"])
        calls = []

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            calls.append(task["id"])
            return {"status": "done", "summary": "verified", "memory": memory}

        baseline_result, _ = mini.run_baseline_request(
            "same request", {}, contract_override=contract, repo_snapshot={}, leaf_executor=leaf,
            reset=True, finish=False,
        )
        recursive_result, _ = mini.run_recursive_request(
            "same request", {}, contract_override=contract, repo_snapshot={},
            fit_decider=lambda *_args: {"decision": "execute"}, leaf_executor=leaf,
            reset=True, finish=False,
        )

        self.assertEqual(baseline_result["status"], "done")
        self.assertEqual(recursive_result["status"], "done")
        self.assertEqual(calls, ["ROOT", "ROOT"])

    def test_task_too_broad_forces_smaller_children_even_if_second_fit_is_optimistic(self):
        contract = self.contract(["large behavior", "large verification"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        fit_calls = []
        leaf_calls = []

        def fit(task, _depth, _contract, _repo, _parent, _deps, force_smaller):
            fit_calls.append((task["id"], force_smaller))
            return {"decision": "execute"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                child_id = str(index)
                child = mini.make_task(child_id, f"small child {index}", 1, "ROOT", [f"child {index}"], [])
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            leaf_calls.append(task["id"])
            if task["id"] == "ROOT":
                return {
                    "status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "step budget",
                    "memory": memory,
                    "fresh_fit_assessment": {
                        "decision": "SPLIT", "reason": "fresh scope reassessment",
                    },
                }
            return {"status": "done", "summary": "small verified", "memory": memory}

        def aggregate(_task, _contract, _children, memory, _repo, root=False):
            return {"status": "done", "summary": "integrated", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(leaf_calls, ["ROOT", "1", "2"])
        self.assertIn(("ROOT", True), fit_calls)
        self.assertEqual(mini.RUN["re_splits"], 1)

    def test_repeated_deterministic_leaf_failure_can_probe_smaller_granularity(self):
        contract = self.contract(["large behavior", "large verification"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        fit_calls = []
        leaf_calls = []

        def fit(task, _depth, _contract, _repo, _parent, _deps, force_smaller):
            fit_calls.append((task["id"], force_smaller))
            return {"decision": "split" if force_smaller else "execute"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                child_id = str(index)
                child = mini.make_task(child_id, f"small child {index}", 1, "ROOT", [f"child {index}"], [])
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            leaf_calls.append(task["id"])
            if task["id"] == "ROOT":
                return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
                        "summary": "failed deterministic evidence gate after repair limit",
                        "failure_evidence": [{"name": "tests", "status": "FAIL"}], "memory": memory,
                        "failure_diagnosis": {"category": "scope_too_broad"}}
            return {"status": "done", "summary": "small verified", "memory": memory}

        def aggregate(_task, _contract, _children, memory, _repo, root=False):
            return {"status": "done", "summary": "integrated", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(leaf_calls, ["ROOT", "1", "2"])
        self.assertIn(("ROOT", True), fit_calls)
        self.assertEqual(mini.RUN["re_splits"], 1)

    def test_resplit_metrics_preserve_failed_attempt_and_count_full_recovery(self):
        contract = self.contract(["large behavior", "large verification"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root

        def fit(task, _depth, _contract, _repo, _parent, _deps, force_smaller):
            return {"decision": "split" if task["id"] == "ROOT" and force_smaller else "execute"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                child_id = str(index)
                child = mini.make_task(child_id, f"focused child {index}", 1, "ROOT", [f"child {index}"], [])
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            if task["id"] == "ROOT":
                return {
                    "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
                    "summary": "failed deterministic evidence gate after repair limit", "memory": memory,
                    "failure_evidence": [{"tool": "run_command", "target": "pytest", "result": "1 failed"}],
                    "failure_diagnosis": {"category": "scope_too_broad"},
                }
            return {"status": "done", "summary": f"verified {task['id']}", "memory": memory}

        def aggregate(_task, _contract, _children, memory, _repo, root=False):
            return {"status": "done", "summary": "integrated verified subtree", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 1)
        self.assertEqual(mini.RUN["resplit_nodes_with_any_verified_child"], 1)
        self.assertEqual(mini.RUN["resplit_nodes_fully_recovered"], 1)
        self.assertEqual(mini.RUN["granularity_rescue_rate"], 100.0)
        self.assertEqual(root["initial_result"]["status"], "failed")
        self.assertEqual(root["status"], "done")
        self.assertEqual(root["resplit"]["outcome"], "fully_recovered")
        self.assertIn("run_command", json.dumps(root["initial_failure_evidence"]))

    def test_resplit_metrics_count_partial_child_rescue_separately_from_full_recovery(self):
        contract = self.contract(["large behavior", "large verification"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root

        def fit(task, _depth, _contract, _repo, _parent, _deps, force_smaller):
            return {"decision": "split" if task["id"] == "ROOT" and force_smaller else "execute"}

        def decompose(task, *_args, **_kwargs):
            children = []
            for index in (1, 2):
                child_id = str(index)
                child = mini.make_task(child_id, f"focused child {index}", 1, "ROOT", [f"child {index}"], [])
                mini.TASKS[child_id] = child
                task["children"].append(child_id)
                mini.RUN["tasks_created"] += 1
                children.append(child)
            return children

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            if task["id"] == "ROOT":
                return {
                    "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "initial failure",
                    "memory": memory, "failure_evidence": [{"name": "root-check", "status": "FAIL"}],
                    "failure_diagnosis": {"category": "scope_too_broad"},
                }
            if task["id"] == "2":
                return {
                    "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "child failure",
                    "memory": memory, "failure_evidence": [{"name": "child-check", "status": "FAIL"}],
                }
            return {"status": "done", "summary": "child verified", "memory": memory}

        with patch.object(mini, "decompose_task", side_effect=decompose), \
                patch.object(mini, "_maybe_search_alternate_strategy", return_value=None):
            result = mini.solve_task(
                root, 0, contract, {}, {}, fit_decider=fit, leaf_executor=leaf,
                aggregator=Mock(return_value={"status": "done", "summary": "unused", "memory": {}}),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 1)
        self.assertEqual(mini.RUN["resplit_nodes_with_any_verified_child"], 1)
        self.assertEqual(mini.RUN["resplit_nodes_fully_recovered"], 0)
        self.assertEqual(mini.RUN["granularity_rescue_rate"], 100.0)
        self.assertEqual(root["resplit"]["outcome"], "partial_child_rescue")

    def test_max_depth_failure_is_diagnosed_without_automatic_resplit(self):
        contract = self.contract(["one focused behavior"])
        task = mini.make_task(
            "1.2.2.4.1.1", "Implement collision reset for one existing function.", mini.MAX_DEPTH,
            "1.2.2.4.1", ["collision reset is verified"], ["src/game.js"],
        )
        mini.TASKS[task["id"]] = task
        mini.RUN["tasks_created"] = 1
        leaf = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": {},
            "failure_evidence": [{"tool": "run_command", "target": "pytest", "result": "1 failed"}],
        }
        with patch.object(mini, "decompose_task") as decompose, \
                patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "alternate strategy verified", "memory": {},
                }) as strategy_leaf:
            result = mini.solve_task(
                task, mini.MAX_DEPTH, contract, {}, {}, leaf_executor=Mock(return_value=leaf),
            )

        self.assertEqual(result["status"], "done")
        decompose.assert_not_called()
        self.assertEqual(mini.RUN["re_splits"], 0)
        self.assertEqual(mini.RUN["max_depth_failures"], 1)
        diagnosis = task["failure_diagnosis"]
        self.assertTrue(diagnosis["at_max_depth"])
        self.assertTrue(diagnosis["automatic_resplit_blocked"])
        self.assertEqual(diagnosis["category"], "implementation_strategy_wrong")
        self.assertEqual(diagnosis["next_action"], "search_or_mutate")
        self.assertEqual(diagnosis["capability_floor_blocked_by"], "strategy_search_not_attempted")
        self.assertEqual(mini.RUN["capability_floor_guard_blocks"], 1)
        self.assertEqual(mini.RUN["capability_floor_routed_to_strategy"], 1)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        strategy_leaf.assert_called_once()
        self.assertEqual(mini.build_node_diagnosis()[0]["why_failed"], "implementation_strategy_wrong")

    def test_capability_floor_guard_blocks_bounded_failure_before_strategy_search(self):
        task = mini.make_task(
            "guarded", "Implement collision reset for one existing function.", mini.MAX_DEPTH,
            "parent", ["collision reset is verified"], ["src/game.js"],
        )
        task["fit_before_execution"] = {
            "decision": "EXECUTE", "reason": "hard recursion/task budget reached",
        }
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit", "memory": {},
            "failure_evidence": [{"tool": "run_command", "target": "pytest", "result": "1 failed"}],
            "repair_history": [
                {"status": "failed", "summary": "repair 1 failed"},
                {"status": "failed", "summary": "repair 2 failed"},
            ],
        }

        diagnosis = mini.diagnose_failure(task, failure)

        self.assertFalse(mini.can_declare_capability_floor(
            task, "model_capability_floor", failure["failure_evidence"], failure,
        ))
        self.assertEqual(diagnosis["category"], "implementation_strategy_wrong")
        self.assertEqual(diagnosis["next_action"], "search_or_mutate")
        self.assertEqual(diagnosis["capability_floor_blocked_by"], "strategy_search_not_attempted")
        self.assertEqual(mini.RUN["capability_floor_guard_blocks"], 1)
        self.assertEqual(mini.RUN["capability_floor_routed_to_strategy"], 0)
        self.assertNotEqual(diagnosis["category"], "model_capability_floor")

    def test_decomposition_exhaustion_does_not_skip_strategy_for_bounded_node(self):
        task = mini.make_task(
            "bounded-after-backtrack", "Implement collision reset for one existing function.", mini.MAX_DEPTH,
            "parent", ["collision reset is verified"], ["src/game.js"],
        )
        task["fit_before_execution"] = {
            "decision": "EXECUTE", "reason": "hard recursion/task budget reached",
        }
        task["decomposition_search_exhausted"] = True
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "implementation remained incorrect after decomposition backtracking",
            "failure_evidence": [{"name": "collision-check", "status": "FAIL"}],
            "repair_history": [
                {"status": "failed", "summary": "repair 1 failed"},
                {"status": "failed", "summary": "repair 2 failed"},
            ],
        }

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", return_value={
                    "status": "done", "summary": "strategy verified", "memory": {},
                }) as strategy_leaf:
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["capability_floor_guard_blocks"], 1)
        self.assertEqual(mini.RUN["capability_floor_routed_to_strategy"], 1)
        strategy_leaf.assert_called_once()
        self.assertNotEqual(task["failure_diagnosis"]["category"], "model_capability_floor")

    def test_unavailable_strategy_generation_blocks_capability_floor(self):
        task = mini.make_task(
            "unavailable-floor", "Implement collision reset for one existing function.", mini.MAX_DEPTH,
            "parent", ["collision reset is verified"], ["src/game.js"],
        )
        task["fit_before_execution"] = {
            "decision": "EXECUTE", "reason": "hard recursion/task budget reached",
        }
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "failed deterministic evidence gate after repair limit",
            "failure_evidence": [{"name": "collision-check", "status": "FAIL"}],
            "repair_history": [
                {"status": "failed", "summary": "repair 1 failed"},
                {"status": "failed", "summary": "repair 2 failed"},
            ],
        }
        invalid = {"strategies": [{
            "name": "only-one", "approach": "one approach", "scope": ["one function"],
            "why_different": "only candidate",
        }]}

        with patch.object(mini, "structured_model_call", side_effect=[invalid, invalid]), \
                patch.object(mini, "execute_leaf") as execute:
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["strategy_search_status"], mini.STRATEGY_SEARCH_UNAVAILABLE)
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertNotEqual(task["failure_diagnosis"]["category"], "model_capability_floor")
        self.assertEqual(mini.RUN["capability_floor_guard_blocks"], 1)
        self.assertEqual(mini.RUN["capability_floor_routed_to_strategy"], 1)
        execute.assert_not_called()

    def test_terminal_too_broad_backtracks_to_a_materially_different_decomposition(self):
        contract = self.contract(["state", "transition", "verification"])
        parent = mini.make_task(
            "3.1.3.1.1", "Implement the combat behavior", 5, "3.1.3.1",
            ["combat behavior is verified"], ["src/game.js"],
        )
        parent["fit_before_execution"] = {
            "decision": "SPLIT", "reason": "multiple independent responsibilities",
        }
        terminal = mini.make_task(
            "3.1.3.1.1.1", "Finish combat behavior", 6, parent["id"],
            ["combat behavior is verified"], ["src/game.js"],
        )
        mini.TASKS[parent["id"]] = parent
        mini.TASKS[terminal["id"]] = terminal
        parent["children"].append(terminal["id"])
        mini._record_decomposition_branch(
            parent,
            [{"goal": terminal["goal"], "done_when": terminal["done_when"], "scope_hint": terminal["scope_hint"]}],
            [terminal],
            kind="initial",
        )
        alternative_specs = [
            {"goal": "Track one enemy position", "done_when": ["position changes deterministically"], "scope_hint": ["src/game.js"]},
            {"goal": "Spawn one enemy outside the viewport", "done_when": ["exactly one enemy is observable"], "scope_hint": ["src/game.js"]},
        ]

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            if task["id"] == terminal["id"]:
                return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD",
                        "summary": "terminal branch still exceeds capacity", "memory": memory,
                        "fresh_fit_assessment": {
                            "decision": "SPLIT", "reason": "fresh scope reassessment",
                        }}
            return {"status": "done", "summary": f"verified {task['id']}", "memory": memory}

        def aggregate(_task, _contract, children, memory, _repo, root=False):
            self.assertTrue(all(item["result"]["status"] == "done" for item in children))
            return {"status": "done", "summary": "alternative subtree integrated", "memory": memory}

        with patch.object(mini, "decompose_alternative_task", return_value=alternative_specs) as alternative:
            result = mini._execute_children(
                parent, [terminal], parent["depth"], contract, {}, {}, "", [],
                fit_decider=lambda *_args: {"decision": "execute"},
                leaf_executor=leaf, aggregator=aggregate,
            )

        mini.recompute_search_metrics()
        self.assertEqual(result["status"], "done")
        alternative.assert_called_once()
        self.assertEqual(mini.RUN["decomposition_backtracks"], 1)
        self.assertEqual(mini.RUN["alternative_decompositions"], 1)
        self.assertEqual(mini.RUN["alternative_decomposition_rescues"], 1)
        self.assertEqual(parent["decomposition_alternatives"][0]["status"], "verified")
        self.assertEqual(terminal["failure_diagnosis"]["next_action"], "backtrack_decomposition")
        self.assertTrue(parent["failed_decompositions"])
        packet = mini.build_node_context(parent, contract, None, {}, failure_evidence=[])
        self.assertIn("FAILED DECOMPOSITIONS", packet)
        self.assertIn("Finish combat behavior", packet)

    def test_terminal_backtracking_is_bounded_and_records_capability_floor_candidate(self):
        contract = self.contract(["state", "transition"])
        parent = mini.make_task(
            "3.1.3.1.1", "Implement the combat behavior", 5, "3.1.3.1",
            ["combat behavior is verified"], ["src/game.js"],
        )
        parent["fit_before_execution"] = {
            "decision": "SPLIT", "reason": "multiple independent responsibilities",
        }
        terminal = mini.make_task(
            "3.1.3.1.1.1", "Finish combat behavior", 6, parent["id"],
            ["combat behavior is verified"], ["src/game.js"],
        )
        mini.TASKS[parent["id"]] = parent
        mini.TASKS[terminal["id"]] = terminal
        parent["children"].append(terminal["id"])
        mini._record_decomposition_branch(
            parent,
            [{"goal": terminal["goal"], "done_when": terminal["done_when"], "scope_hint": terminal["scope_hint"]}],
            [terminal],
            kind="initial",
        )
        alternatives = [
            [{"goal": "Observe enemy position", "done_when": ["position is observable"], "scope_hint": []},
             {"goal": "Observe spawn count", "done_when": ["spawn count is observable"], "scope_hint": []}],
            [{"goal": "Apply one collision state transition", "done_when": ["collision transition is observable"], "scope_hint": []},
             {"goal": "Verify one reset outcome", "done_when": ["reset outcome is executable"], "scope_hint": []}],
        ]

        def leaf(_task, _contract, memory, _repo, _parent, _deps):
            return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD",
                    "summary": "terminal branch still exceeds capacity", "memory": memory,
                    "fresh_fit_assessment": {
                        "decision": "SPLIT", "reason": "fresh scope reassessment",
                    }}

        aggregator = Mock()
        with patch.object(mini, "decompose_alternative_task", side_effect=alternatives):
            result = mini._execute_children(
                parent, [terminal], parent["depth"], contract, {}, {}, "", [],
                fit_decider=lambda *_args: {"decision": "execute"},
                leaf_executor=leaf, aggregator=aggregator,
            )

        mini.recompute_search_metrics()
        self.assertEqual(result["status"], "failed")
        self.assertEqual(mini.RUN["decomposition_backtracks"], 2)
        self.assertEqual(mini.RUN["alternative_decompositions"], 2)
        self.assertEqual(mini.RUN["alternative_decomposition_rescues"], 0)
        self.assertEqual(mini.RUN["decomposition_backtrack_rescue_rate"], 0.0)
        self.assertTrue(parent["decomposition_search_exhausted"])
        self.assertEqual(parent["failure_diagnosis"]["category"], "model_capability_floor")
        self.assertEqual(mini.RUN["capability_floor_nodes"], 1)
        aggregator.assert_not_called()

    def test_strategy_search_is_bounded_and_uses_fixed_a_then_b_order(self):
        task = mini.make_task(
            "1.2.2.4.1.1", "Implement collision reset in updateCollision()", 6, "1.2.2.4.1",
            ["collision reset is verified"], ["src/game.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "deterministic check failed", "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        strategies = self.strategy_pair()
        prompts = []

        def plan(prompt, *_args):
            prompts.append(prompt)
            return {"strategies": strategies}

        with patch.object(mini, "structured_model_call", side_effect=plan):
            planned = mini.search_alternate_strategies(task, self.contract(), failure, {}, {})
            selected = mini.select_alternate_strategy(task, planned, failure)

        self.assertEqual(len(planned), mini.MAX_STRATEGY_ALTERNATIVES)
        self.assertEqual(selected, 0)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["challenger_calls"], 0)
        self.assertEqual(len(prompts), 1)
        for marker in ("FAILED APPROACH SUMMARY", "FAILED DETERMINISTIC EVIDENCE", "PREVIOUS REPAIR SUMMARY"):
            self.assertIn(marker, prompts[0])
        mini.recompute_search_metrics()
        self.assertEqual(mini.RUN["strategy_rescue_rate"], 0.0)

    def test_bounded_implementation_failure_triggers_strategy_rescue_before_resplit(self):
        task = mini.make_task(
            "1", "Implement collision reset in updateCollision()", 1, "ROOT",
            ["collision reset is verified"], ["src/game.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR",
            "summary": "deterministic check failed",
            "failure_evidence": [{"name": "collision-check", "status": "FAIL"}],
        }
        executed = []

        def leaf(*_args, **kwargs):
            executed.append(kwargs["strategy_context"]["strategy"]["name"])
            return {"status": "done", "summary": "strategy A verified", "memory": {},
                    "changed_files": ["src/game.js"]}

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=leaf):
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["status"], "done")
        self.assertEqual(executed, ["state_transition"])
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 1)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)
        self.assertEqual(mini.RUN["strategy_search_failures"], 0)
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 0)
        self.assertEqual(task["strategy_search"]["outcome"], "rescued")
        self.assertEqual(len(task["strategy_attempts"]), 1)

    def test_strategy_trigger_excludes_non_strategy_failure_diagnoses(self):
        cases = [
            ("scope_too_broad", 1, "TASK_TOO_BROAD", "scope overflow"),
            ("environment_failure", 1, "ENVIRONMENT_ERROR", "provider unavailable"),
            ("dependency_error", 1, "IMPLEMENTATION_ERROR", "Module not found: state.js"),
            ("verifier_builder_mismatch", 1, "IMPLEMENTATION_ERROR", "no executable verification was attempted"),
            ("model_capability_floor", mini.MAX_DEPTH, "IMPLEMENTATION_ERROR",
             "failed deterministic evidence gate after repair limit"),
        ]
        for expected, depth, failure_type, summary in cases:
            with self.subTest(expected=expected):
                task = mini.make_task(
                    f"node-{expected}", "Implement one focused behavior", depth, "ROOT",
                    ["behavior is verified"], ["src/app.js"],
                )
                failure = {
                    "status": "failed", "failure_type": failure_type, "summary": summary,
                    "failure_evidence": [{"name": "deterministic-check", "status": "FAIL"}],
                }
                if expected == "scope_too_broad":
                    failure["fresh_fit_assessment"] = {
                        "decision": "SPLIT", "reason": "explicit scope reassessment",
                    }
                if expected == "model_capability_floor":
                    failed_attempts = [
                        {"status": "FAIL", "name": "state_transition"},
                        {"status": "FAIL", "name": "boundary_wrapper"},
                    ]
                    task["strategy_attempts"] = list(failed_attempts)
                    task["strategy_search"] = {
                        "status": "completed", "outcome": "failed",
                        "attempts": list(failed_attempts),
                    }
                with patch.object(mini, "structured_model_call") as structured, \
                        patch.object(mini, "execute_leaf") as execute:
                    self.assertIsNone(mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {}))
                self.assertEqual(task["failure_diagnosis"]["category"], expected)
                structured.assert_not_called()
                execute.assert_not_called()

    def test_duplicate_strategy_pair_gets_one_bounded_replacement(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        duplicate = [
            {"name": "path_a", "approach": "use existing state and reset the value in one function",
             "scope": "one function", "why_different": "first path"},
            {"name": "path_b", "approach": "use existing state and reset the value in one function",
             "scope": "one function", "why_different": "second path"},
        ]
        responses = [{"strategies": duplicate}, {"strategies": self.strategy_pair()}]
        with patch.object(mini, "structured_model_call", side_effect=responses) as structured:
            planned = mini.search_alternate_strategies(task, self.contract(), failure, {}, {})

        self.assertEqual(structured.call_count, 2)
        self.assertEqual([item["name"] for item in planned], ["state_transition", "boundary_wrapper"])
        self.assertEqual(len(planned), mini.MAX_STRATEGY_ALTERNATIVES)
        self.assertEqual(
            [item["status"] for item in task["strategy_search"]["generation_attempts"]],
            ["rejected", "valid"],
        )

    def test_valid_replacement_strategies_execute_normally(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        invalid = {"strategies": [{"name": "one", "approach": "one path", "scope": ["one function"],
                                    "why_different": "only candidate"}]}
        executed = []

        def leaf(*_args, **kwargs):
            executed.append(kwargs["strategy_context"]["strategy"]["name"])
            return {"status": "done", "summary": "replacement verified", "memory": {}}

        with patch.object(mini, "structured_model_call", side_effect=[invalid, {"strategies": self.strategy_pair()}]) as structured, \
                patch.object(mini, "execute_leaf", side_effect=leaf):
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["status"], "done")
        self.assertEqual(structured.call_count, 2)
        self.assertEqual(executed, ["state_transition"])
        self.assertEqual(mini.RUN["strategy_generation_failures"], 0)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 1)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)

    def test_invalid_strategy_generation_is_unavailable_without_fallback_or_execution(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        invalid = {"strategies": [{"name": "one", "approach": "one path", "scope": ["one function"],
                                    "why_different": "only candidate"}]}
        with patch.object(mini, "structured_model_call", side_effect=[invalid, invalid]) as structured, \
                patch.object(mini, "execute_leaf") as execute:
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["strategy_search_status"], mini.STRATEGY_SEARCH_UNAVAILABLE)
        self.assertEqual(structured.call_count, 2)
        execute.assert_not_called()
        self.assertEqual(task["strategy_search"]["strategies"], [])
        self.assertEqual(task["strategy_search"]["outcome"], "generation_unavailable")
        self.assertEqual(len(task["strategy_search"]["generation_attempts"]), 2)
        self.assertEqual(len(task["strategy_attempts"]), 0)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["strategy_generation_failures"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 0)
        self.assertEqual(mini.RUN["strategy_search_failures"], 0)
        self.assertEqual(mini.RUN["strategy_rescues"], 0)
        self.assertNotEqual(task["failure_diagnosis"]["category"], "model_capability_floor")
        self.assertEqual(task["failure_diagnosis"]["category"], "implementation_strategy_wrong")
        self.assertEqual(
            task["failure_diagnosis"]["strategy_search_unavailable"],
            mini.STRATEGY_SEARCH_UNAVAILABLE,
        )

    def test_paraphrased_pair_and_invalid_replacement_fail_without_false_rescue(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        paraphrased = [
            {"name": "path_a", "approach": "use existing state and reset the value in one function",
             "scope": ["one function"], "why_different": "first path"},
            {"name": "path_b", "approach": "use existing state and reset the value in one function",
             "scope": ["one function"], "why_different": "second path"},
        ]
        with patch.object(mini, "structured_model_call", side_effect=[
            {"strategies": paraphrased}, {"strategies": paraphrased},
        ]) as structured, patch.object(mini, "execute_leaf") as execute:
            result = mini._maybe_search_alternate_strategy(task, self.contract(), failure, {}, {})

        self.assertEqual(result["strategy_search_status"], mini.STRATEGY_SEARCH_UNAVAILABLE)
        self.assertEqual(structured.call_count, 2)
        execute.assert_not_called()
        attempts = task["strategy_search"]["generation_attempts"]
        self.assertEqual([item["reason"] for item in attempts], [
            "strategies_not_materially_different", "strategies_not_materially_different",
        ])
        self.assertEqual(mini.RUN["strategy_generation_failures"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 0)
        self.assertEqual(mini.RUN["strategy_search_failures"], 0)
        self.assertEqual(mini.RUN["strategy_rescues"], 0)

    def test_strategy_generation_is_non_mutating_and_has_bounded_packet(self):
        target = mini.WORKSPACE / "app.js"
        target.write_text("original\n", encoding="utf-8")
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "run_tool") as run_tool, \
                patch.object(mini, "execute_agent_task") as agent:
            planned = mini.search_alternate_strategies(task, self.contract(), failure, {}, {})

        self.assertEqual(len(planned), 2)
        self.assertEqual(target.read_text(encoding="utf-8"), "original\n")
        run_tool.assert_not_called()
        agent.assert_not_called()

    def test_strategy_attempt_uses_normal_leaf_engine_with_active_strategy_packet(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        strategy = self.strategy_pair()[0]
        with patch.object(mini, "execute_leaf", return_value={
            "status": "done", "summary": "verified", "memory": {}, "changed_files": [],
        }) as leaf, patch.object(mini, "execute_agent_task") as agent:
            result = mini.execute_strategy_attempt(task, self.contract(), strategy, failure, {}, {}, attempt_index=0)

        self.assertEqual(result["status"], "done")
        leaf.assert_called_once()
        agent.assert_not_called()
        context = leaf.call_args.kwargs["strategy_context"]
        self.assertEqual(context["strategy"]["name"], "state_transition")
        packet = mini.build_node_context(
            task, self.contract(), None, {}, strategy_context=context,
        )
        self.assertLessEqual(len(packet), mini.MAX_NODE_PACKET_CHARS)
        for marker in ("FAILED APPROACH SUMMARY", "CURRENT DETERMINISTIC FAILURE", "CURRENT ALTERNATIVE STRATEGY"):
            self.assertIn(marker, packet)

    def test_strategy_a_failure_rolls_back_before_b_and_preserves_verified_dependencies(self):
        target = mini.WORKSPACE / "app.js"
        target.write_text("base\n", encoding="utf-8")
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "check failed",
            "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        dependencies = [{"task_id": "0", "status": "done", "summary": "verified dependency"}]
        observations = []

        def leaf(_task, _contract, memory, _repo, _parent, deps, strategy_context=None):
            name = strategy_context["strategy"]["name"]
            observations.append((name, target.read_text(encoding="utf-8"), dict(memory), list(deps)))
            memory["attempt"] = name
            mini.begin_transaction(task["id"])
            mini._transaction_capture(target)
            target.write_text(name, encoding="utf-8")
            if name == "state_transition":
                return {"status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "A failed",
                        "memory": memory, "failure_evidence": [{"name": "check", "status": "FAIL"}]}
            return {"status": "done", "summary": "B verified", "memory": memory}

        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=leaf):
            result = mini._maybe_search_alternate_strategy(
                task, self.contract(), failure, {"seed": "same"}, {}, dependency_summaries=dependencies,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual([item[0] for item in observations], ["state_transition", "boundary_wrapper"])
        self.assertEqual(observations[0][1], "base\n")
        self.assertEqual(observations[1][1], "base\n")
        self.assertEqual(observations[0][2], {"seed": "same"})
        self.assertEqual(observations[1][2], {"seed": "same"})
        self.assertEqual(observations[0][3], dependencies)
        self.assertEqual(observations[1][3], dependencies)
        self.assertEqual(target.read_text(encoding="utf-8"), "boundary_wrapper")
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 2)
        self.assertEqual(mini.RUN["strategy_rescues"], 1)

    def test_both_strategy_failures_record_capability_floor_without_resplit(self):
        task = mini.make_task(
            "1", "Implement one focused behavior", 1, "ROOT", ["behavior is verified"], ["src/app.js"],
        )
        failure = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "initial check failed",
            "memory": {}, "failure_evidence": [{"name": "check", "status": "FAIL"}],
        }
        with patch.object(mini, "structured_model_call", return_value={"strategies": self.strategy_pair()}), \
                patch.object(mini, "execute_leaf", side_effect=[failure, failure]), \
                patch.object(mini, "_resplit_after_leaf_failure") as resplit:
            result = mini.solve_task(
                task, 1, self.contract(), {}, {}, fit_decider=lambda *_args: {"decision": "execute"},
                leaf_executor=Mock(return_value=failure),
            )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(task["failure_diagnosis"]["category"], "model_capability_floor")
        self.assertEqual(len(task["strategy_attempts"]), 2)
        self.assertEqual(mini.RUN["strategy_searches"], 1)
        self.assertEqual(mini.RUN["alternate_strategies_attempted"], 2)
        self.assertEqual(mini.RUN["strategy_rescues"], 0)
        self.assertEqual(mini.RUN["strategy_search_failures"], 1)
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 0)
        resplit.assert_not_called()

    def test_strategy_rescue_rate_is_na_when_no_strategy_search_started(self):
        mini.recompute_search_metrics()
        self.assertIsNone(mini.RUN["strategy_rescue_rate"])
        output = io.StringIO()
        with redirect_stdout(output):
            mini.print_search_metrics()
        self.assertIn("strategy_rescue_rate: N/A", output.getvalue())

    def test_implementation_failure_does_not_force_split_when_fit_rejects_granularity_rescue(self):
        contract = self.contract(["one focused behavior"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root
        leaf = {
            "status": "failed", "failure_type": "IMPLEMENTATION_ERROR", "summary": "strategy failed",
            "memory": {}, "failure_evidence": [{"tool": "run_command", "target": "pytest", "result": "1 failed"}],
        }
        with patch.object(mini, "structured_model_call", return_value={"decision": "execute"}), \
                patch.object(mini, "_maybe_search_alternate_strategy", return_value=None), \
                patch.object(mini, "decompose_task") as decompose:
            result = mini.solve_task(
                root, 0, contract, {}, {}, leaf_executor=Mock(return_value=leaf),
            )

        self.assertEqual(result["status"], "failed")
        decompose.assert_not_called()
        self.assertEqual(mini.RUN["failed_nodes_resplit"], 0)
        self.assertEqual(root["failure_diagnosis"]["category"], "implementation_strategy_wrong")

    def test_malformed_task_fit_falls_back_without_killing_recursive_run(self):
        contract = self.contract(["first", "second", "third"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            return {"status": "done", "summary": "verified", "memory": memory}

        def aggregate(_task, _contract, _children, memory, _repo, root=False):
            return {"status": "done", "summary": "integrated", "memory": memory}

        with patch.object(mini, "structured_model_call", side_effect=mini.StructuredOutputError("bad JSON")):
            result, _memory = mini.run_recursive_request(
                "hard request", {}, contract_override=contract, repo_snapshot={},
                leaf_executor=leaf, aggregator=aggregate, reset=True, finish=False,
            )

        self.assertEqual(result["status"], "done")
        self.assertGreaterEqual(mini.RUN["splits"], 1)

    def test_provider_failure_is_reported_without_recursive_decomposition(self):
        contract = self.contract(["one", "two", "three"])
        root = mini.root_task_from_contract(contract)
        mini.TASKS["ROOT"] = root

        def fit(*_args):
            raise mini.ProviderError("connection refused")

        with patch.object(mini, "decompose_task") as decompose:
            result = mini.solve_task(root, 0, contract, {}, {}, fit_decider=fit,
                                     leaf_executor=Mock(), aggregator=Mock())

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], "ENVIRONMENT_ERROR")
        self.assertEqual(mini.RUN["tasks_created"], 1)
        self.assertEqual(mini.RUN["splits"], 0)
        decompose.assert_not_called()

    def test_concrete_falsifier_command_failure_blocks_but_narrative_does_not(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "run_command", "target": "pytest", "result": "[exit_code=0]"},
        ]}
        falsifier = {"status": "done", "summary": "I suspect a boundary bug", "tool_evidence": [
            {"tool": "run_command", "target": "pytest boundary", "result": "[exit_code=1]\n1 failed"},
        ]}
        self.assertFalse(mini.evidence_gate(builder, falsifier)["passed"])
        narrative = {"status": "failed", "summary": "I suspect a boundary bug", "tool_evidence": []}
        self.assertTrue(mini.evidence_gate(builder, narrative)["passed"])

        # A separate fresh browser pass may resolve the Builder's stale probe,
        # but it cannot erase a later concrete Falsifier failure.
        browser_pass = {"passed": True, "entry_path": "index.html"}
        falsifier_browser_failure = {
            "status": "done", "tool_evidence": [
                {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
            ],
        }
        self.assertFalse(mini.evidence_gate(builder, falsifier_browser_failure, browser_pass)["passed"])

    def test_fresh_repair_verification_does_not_reuse_stale_builder_failure(self):
        contract = self.contract(["repair API"])
        task = mini.make_task("ROOT", "repair API", 0, None, ["tests pass"], [])
        builder = {
            "status": "done", "summary": "implemented", "memory": {},
            "tool_evidence": [{"tool": "run_command", "target": "pytest", "result": "[exit_code=1]"}],
        }
        falsifier = {"status": "done", "summary": "no executable issue", "memory": {}, "tool_evidence": []}
        repaired = {
            "status": "done", "summary": "repaired and freshly verified", "memory": {},
            "tool_evidence": [{"tool": "run_command", "target": "pytest", "result": "[exit_code=0]"}],
        }
        with patch.object(mini, "execute_agent_task", side_effect=[builder, falsifier, repaired]), \
                patch.object(mini, "optional_browser_check", return_value=None):
            result = mini.execute_leaf(task, contract, {}, {}, "", [])

        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN["repairer_calls"], 1)

    def test_reconnaissance_is_bounded_without_reading_source_contents(self):
        for index in range(100):
            path = mini.WORKSPACE / "src" / f"file-{index}.js"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SECRET SOURCE CONTENT", encoding="utf-8")
        snapshot = mini.inspect_repository(max_files=12, max_depth=1, max_chars=900)

        self.assertLessEqual(len(snapshot["files"]), 12)
        self.assertTrue(snapshot["truncated"])
        self.assertNotIn("SECRET SOURCE CONTENT", json.dumps(snapshot))
        self.assertLessEqual(len(json.dumps(snapshot)), 900)

    def test_tree_persistence_has_no_model_messages_or_hidden_reasoning(self):
        mini.record_run_event(
            "test", messages=[{"role": "assistant", "content": "private"}],
            reasoning="private", chain_of_thought="private", summary="bounded fact",
        )
        record = (mini.WORKSPACE / mini.RUNS_DIR / f"{mini.RUN_ID}.jsonl").read_text(encoding="utf-8")
        self.assertNotIn("private", record)
        self.assertIn("bounded fact", record)

    def test_parent_without_blocking_preflight_conflicts_uses_normal_integration(self):
        contract = self.contract(["integrated behavior"])
        parent = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        mini.TASKS["ROOT"] = parent
        child_results = []
        for index in (1, 2):
            child = mini.make_task(str(index), f"child {index}", 1, "ROOT", ["verified"], [])
            child["status"] = "done"
            child["verification_status"] = "passed"
            mini.TASKS[child["id"]] = child
            child_results.append({"task": child, "result": {
                "status": "done", "summary": "verified", "memory": {}, "changed_files": [],
            }})
        preflight = {"passed": True, "status": "PASS", "current_syntax": "PASS",
                     "conflicts": [], "warnings": [], "project_invariants": [],
                     "error_count": 0, "invariant_violation_count": 0}
        builder = {"status": "done", "summary": "parent verified", "memory": {},
                   "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]}
        with patch.object(mini, "run_integration_preflight", return_value=preflight), \
                patch.object(mini, "execute_agent_task", return_value=builder) as execute, \
                patch.object(mini, "falsify_task", return_value={"status": "skipped", "memory": {},
                                                                    "tool_evidence": []}), \
                patch.object(mini, "optional_browser_check", return_value=None):
            result = mini.aggregate_task(parent, contract, child_results, {}, {}, root=True)

        self.assertEqual(result["status"], "done")
        self.assertEqual(execute.call_args.kwargs["task_id"], "ROOT")
        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["integration_tasks_created"], 0)
        self.assertEqual(mini.RUN["integration_splits"], 0)
        self.assertIsNone(mini.RUN["integration_conflict_resolution"])

    def test_blocking_preflight_conflicts_create_sequential_integration_tasks(self):
        contract = self.contract(["integrated behavior"])
        parent = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        mini.TASKS["ROOT"] = parent
        child_results = []
        for index in (1, 2):
            child = mini.make_task(str(index), f"child {index}", 1, "ROOT", ["verified"], [])
            child["status"] = "done"
            child["verification_status"] = "passed"
            mini.TASKS[child["id"]] = child
            child_results.append({"task": child, "result": {
                "status": "done", "summary": "verified", "memory": {}, "changed_files": [],
            }})
        before = {
            "passed": False, "status": "FAIL", "current_syntax": "PASS", "error_count": 2,
            "invariant_violation_count": 2, "warnings": [], "project_invariants": [],
            "conflicts": [
                {"kind": "duplicate_declaration", "severity": "error", "symbol": "formatValue",
                 "files": ["app.js"], "message": "duplicate formatValue declaration"},
                {"kind": "duplicate_html_id", "severity": "error", "id": "settings",
                 "files": ["index.html"], "message": "duplicate HTML id settings"},
            ],
        }
        after = {"passed": True, "status": "PASS", "current_syntax": "PASS", "error_count": 0,
                 "invariant_violation_count": 0, "conflicts": [], "warnings": [],
                 "project_invariants": []}
        preflight_calls = []
        order = []

        def preflight(*_args, **_kwargs):
            preflight_calls.append(True)
            return before if len(preflight_calls) == 1 else after

        def builder(_goal, memory, **kwargs):
            task_id = kwargs["task_id"]
            order.append(task_id)
            if task_id.startswith("I."):
                mini.write_file(f"{task_id}.txt", task_id)
            return {"status": "done", "summary": f"verified {task_id}", "memory": memory,
                    "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]}

        with patch.object(mini, "run_integration_preflight", side_effect=preflight), \
                patch.object(mini, "execute_agent_task", side_effect=builder), \
                patch.object(mini, "falsify_task", return_value={"status": "skipped", "memory": {},
                                                                    "tool_evidence": []}), \
                patch.object(mini, "optional_browser_check", return_value=None), \
                patch.object(mini, "run_integration_milestones") as old_path:
            result = mini.aggregate_task(parent, contract, child_results, {}, {}, root=True)

        self.assertEqual(result["status"], "done")
        self.assertEqual(order, ["I.1", "I.2", "ROOT"])
        old_path.assert_not_called()
        self.assertEqual([mini.TASKS[item]["kind"] for item in ("I.1", "I.2")],
                         ["integration", "integration"])
        self.assertEqual(parent["children"][-2:], ["I.1", "I.2"])
        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["integration_tasks_created"], 2)
        self.assertEqual(mini.RUN["integration_splits"], 1)
        self.assertEqual(mini.RUN["integration_verified_nodes"], 2)
        self.assertGreaterEqual(len(preflight_calls), 5)

    def test_integration_node_packet_contains_only_bounded_relevant_context(self):
        conflict = {"kind": "duplicate_declaration", "type": "duplicate_declaration",
                    "severity": "error", "symbol": "formatValue", "files": ["app.js"],
                    "evidence": "two declarations"}
        task = mini.make_task(
            "I.2", "Resolve duplicate declaration of formatValue", 1, "ROOT",
            ["fresh preflight has no owned conflict", "syntax passes"], ["app.js"],
            kind="integration", integration_conflicts=[conflict], integration_context={
                "parent_goal": "integrate verified children",
                "project_invariants": [{"kind": "persistence_owner", "owner": "app.js",
                                        "symbol": "PERSIST_KEY", "source": "deterministic_scan"}],
                "verified_child_manifests": [{
                    "task_id": "1", "status": "done", "goal": "child one",
                    "integration_manifest": {"status": "verified", "changed_files": ["app.js"],
                                              "interfaces": ["appState"], "verification": ["run_file"]},
                }],
            },
        )
        packet = mini.build_node_context(
            task, self.contract(), None, {}, "parent summary",
            [{"task_id": "previous", "status": "done", "goal": "dependency",
              "summary": "verified", "evidence": "run command passed",
              "integration_manifest": {"status": "verified"},
              "model_history": "must not be copied"}],
            [{"tool": "run_command", "target": "node", "result": "failure evidence"}],
        )

        for label in (
            "ROOT CONTRACT", "PARENT GOAL", "CURRENT INTEGRATION TASK", "PROJECT INVARIANTS",
            "RELEVANT CHILD INTEGRATION MANIFESTS", "RELEVANT PREFLIGHT CONFLICT(S)",
            "VERIFIED DEPENDENCY SUMMARIES", "CURRENT FAILURE EVIDENCE", "BOUNDED REPOSITORY HINTS",
        ):
            self.assertIn(label, packet)
        self.assertIn("formatValue", packet)
        self.assertIn("PERSIST_KEY", packet)
        self.assertNotIn("must not be copied", packet)
        self.assertNotIn("RELEVANT PROJECT MEMORY", packet)
        self.assertLessEqual(len(packet), mini.MAX_NODE_PACKET_CHARS)

    def test_integration_tasks_are_sequential_and_share_verified_workspace_state(self):
        parent = mini.make_task("ROOT", "integrate shared state", 0, None, ["integrated"], [])
        mini.TASKS["ROOT"] = parent
        before = {
            "passed": False, "status": "FAIL", "current_syntax": "PASS", "error_count": 2,
            "invariant_violation_count": 0, "warnings": [], "project_invariants": [],
            "conflicts": [
                {"kind": "duplicate_declaration", "severity": "error", "symbol": "first", "files": ["shared.js"]},
                {"kind": "duplicate_declaration", "severity": "error", "symbol": "second", "files": ["shared.js"]},
            ],
        }
        after = {"passed": True, "status": "PASS", "current_syntax": "PASS", "error_count": 0,
                 "invariant_violation_count": 0, "warnings": [], "project_invariants": [],
                 "conflicts": []}
        parent["integration_preflight"] = {"before": before, "after": None}
        tasks = mini.create_integration_tasks(parent, self.contract(), [], before, root=True)
        observed = []
        preflight_calls = []

        def builder(_goal, memory, **kwargs):
            task_id = kwargs["task_id"]
            if task_id == "I.1":
                mini.write_file("shared.js", "first\n")
            elif task_id == "I.2":
                content = (mini.WORKSPACE / "shared.js").read_text(encoding="utf-8")
                observed.append("first" in content)
                mini.edit_file("shared.js", "first\n", "first\nsecond\n")
            return {"status": "done", "summary": task_id, "memory": memory,
                    "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]}

        def fresh_preflight(*_args, **_kwargs):
            preflight_calls.append(True)
            return after

        with patch.object(mini, "execute_agent_task", side_effect=builder), \
                patch.object(mini, "run_integration_preflight", side_effect=fresh_preflight), \
                patch.object(mini, "falsify_task", return_value={"status": "skipped", "memory": {},
                                                                    "tool_evidence": []}), \
                patch.object(mini, "optional_browser_check", return_value=None):
            result = mini.run_integration_tasks_sequentially(
                parent, self.contract(), [], tasks, {}, {},
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(observed, [True])
        self.assertIn("second", (mini.WORKSPACE / "shared.js").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(preflight_calls), 4)

    def test_integration_too_broad_resplits_through_same_solve_task_path(self):
        task = mini.make_task(
            "I.1", "Normalize persistence ownership", 0, "ROOT", ["ownership is verified"], ["app.js"],
            kind="integration", integration_conflicts=[{
                "kind": "conflicting_persistence_ownership", "severity": "error",
                "symbol": "PERSIST_KEY", "files": ["app.js"], "message": "two owners",
            }], integration_context={"parent_goal": "integrate", "project_invariants": [],
                                       "verified_child_manifests": []},
        )
        mini.TASKS[task["id"]] = task
        mini.RUN["tasks_created"] = 1
        calls = []

        def leaf(node, _contract, memory, _repo, _parent, _deps):
            calls.append(node["id"])
            if node["id"] == "I.1":
                return {"status": "too_broad", "failure_type": "INTEGRATION_TOO_BROAD",
                        "summary": "one integration concern is still too broad", "memory": memory}
            return {"status": "done", "summary": f"verified {node['id']}", "memory": memory}

        with patch.object(mini, "run_integration_preflight", return_value={
            "passed": True, "status": "PASS", "current_syntax": "PASS", "conflicts": [],
            "warnings": [], "project_invariants": [],
        }):
            result = mini.solve_task(
                task, 0, self.contract(), {}, {},
                fit_decider=mini._integration_fit_decider,
                leaf_executor=leaf, aggregator=mini._aggregate_integration_children,
            )

        mini.recompute_integration_metrics()
        self.assertEqual(result["status"], "done")
        self.assertEqual(calls, ["I.1", "I.1.1", "I.1.2"])
        self.assertEqual(task["integration_resplit_attempts"], 1)
        self.assertTrue(task["integration_too_broad"])
        self.assertEqual(mini.RUN["integration_resplits"], 1)
        self.assertEqual(mini.RUN["integration_too_broad_nodes"], 1)
        self.assertEqual(mini.RUN["integration_granularity_rescues"], 1)

    def test_integration_provider_failure_does_not_trigger_decomposition(self):
        task = mini.make_task(
            "I.1", "Resolve one integration conflict", 0, "ROOT", ["verified"], ["app.js"],
            kind="integration", integration_conflicts=[{
                "kind": "duplicate_declaration", "severity": "error", "symbol": "value",
                "files": ["app.js"],
            }], integration_context={"parent_goal": "integrate", "project_invariants": [],
                                       "verified_child_manifests": []},
        )
        mini.TASKS[task["id"]] = task
        mini.RUN["tasks_created"] = 1
        leaf = Mock(return_value={"status": "failed", "failure_type": "ENVIRONMENT_ERROR",
                                  "summary": "provider unavailable", "memory": {}})
        with patch.object(mini, "decompose_task") as decompose:
            result = mini.solve_task(
                task, 0, self.contract(), {}, {},
                fit_decider=mini._integration_fit_decider, leaf_executor=leaf,
            )

        self.assertEqual(result["failure_type"], "ENVIRONMENT_ERROR")
        self.assertEqual(task["integration_resplit_attempts"], 0)
        self.assertEqual(task["children"], [])
        decompose.assert_not_called()

    def test_remaining_blocking_conflict_prevents_parent_verified(self):
        contract = self.contract(["integrated behavior"])
        parent = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        mini.TASKS["ROOT"] = parent
        child = mini.make_task("1", "verified child", 1, "ROOT", ["verified"], [])
        child["status"] = "done"
        child["verification_status"] = "passed"
        mini.TASKS["1"] = child
        child_results = [{"task": child, "result": {"status": "done", "summary": "verified",
                                                       "memory": {}, "changed_files": []}}]
        conflict = {"kind": "duplicate_declaration", "severity": "error", "symbol": "value",
                    "files": ["app.js"], "message": "still duplicated"}
        blocked = {"passed": False, "status": "FAIL", "current_syntax": "PASS", "error_count": 1,
                   "invariant_violation_count": 1, "conflicts": [conflict], "warnings": [],
                   "project_invariants": []}
        integration_task = mini.make_task(
            "I.1", "resolve value", 1, "ROOT", ["resolved"], ["app.js"],
            kind="integration", integration_conflicts=[conflict], integration_context={},
        )
        integration_info = [{"task_id": "I.1", "goal": "resolve value", "status": "done",
                             "summary": "verified", "changed_files": [], "verification": "passed",
                             "integration_manifest": {"status": "verified"}, "evidence": "passed"}]
        with patch.object(mini, "run_integration_preflight", return_value=blocked), \
                patch.object(mini, "create_integration_tasks", return_value=[integration_task]), \
                patch.object(mini, "run_integration_tasks_sequentially", return_value={
                    "status": "done", "memory": {}, "integration_children": integration_info,
                    "integration_preflight": blocked,
                }), \
                patch.object(mini, "execute_agent_task") as execute:
            result = mini.aggregate_task(parent, contract, child_results, {}, {}, root=True)

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], "INTEGRATION_FAILURE")
        execute.assert_not_called()
        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 1)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 0)

    def test_resolved_blocking_conflicts_allow_parent_verification(self):
        contract = self.contract(["integrated behavior"])
        parent = mini.make_task("ROOT", "integrate verified children", 0, None, ["integrated"], [])
        mini.TASKS["ROOT"] = parent
        child = mini.make_task("1", "verified child", 1, "ROOT", ["verified"], [])
        child["status"] = "done"
        child["verification_status"] = "passed"
        mini.TASKS["1"] = child
        child_results = [{"task": child, "result": {"status": "done", "summary": "verified",
                                                       "memory": {}, "changed_files": []}}]
        conflict = {"kind": "duplicate_declaration", "severity": "error", "symbol": "value",
                    "files": ["app.js"], "message": "duplicated"}
        before = {"passed": False, "status": "FAIL", "current_syntax": "PASS", "error_count": 1,
                  "invariant_violation_count": 1, "conflicts": [conflict], "warnings": [],
                  "project_invariants": []}
        after = {"passed": True, "status": "PASS", "current_syntax": "PASS", "error_count": 0,
                 "invariant_violation_count": 0, "conflicts": [], "warnings": [],
                 "project_invariants": []}
        integration_task = mini.make_task(
            "I.1", "resolve value", 1, "ROOT", ["resolved"], ["app.js"],
            kind="integration", integration_conflicts=[conflict], integration_context={},
        )
        integration_info = [{"task_id": "I.1", "goal": "resolve value", "status": "done",
                             "summary": "verified", "changed_files": [], "verification": "passed",
                             "integration_manifest": {"status": "verified"}, "evidence": "passed"}]
        builder = {"status": "done", "summary": "parent verified", "memory": {},
                   "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]"}]}
        with patch.object(mini, "run_integration_preflight", side_effect=[before, after]), \
                patch.object(mini, "create_integration_tasks", return_value=[integration_task]), \
                patch.object(mini, "run_integration_tasks_sequentially", return_value={
                    "status": "done", "memory": {}, "integration_children": integration_info,
                    "integration_preflight": after,
                }), \
                patch.object(mini, "execute_agent_task", return_value=builder) as execute, \
                patch.object(mini, "falsify_task", return_value={"status": "skipped", "memory": {},
                                                                    "tool_evidence": []}), \
                patch.object(mini, "optional_browser_check", return_value=None):
            result = mini.aggregate_task(parent, contract, child_results, {}, {}, root=True)

        self.assertEqual(result["status"], "done")
        execute.assert_called_once()
        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 1)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 1)
        self.assertEqual(mini.RUN["integration_conflict_resolution"], 100.0)

    def test_same_blocking_conflict_in_three_preflights_counts_once(self):
        for line_numbers, message in (
            ([10, 20], "duplicate value declaration"),
            ([31, 44], "duplicate value declaration after edit"),
            ([58, 72], "duplicate value declaration after another edit"),
        ):
            mini._record_preflight_conflict_snapshot({
                "conflicts": [{
                    "kind": "duplicate_declaration", "severity": "error", "symbol": "value",
                    "files": [f"app.js:{line}" for line in line_numbers], "message": message,
                }],
            })

        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 1)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 0)

    def test_two_structurally_different_conflicts_count_twice(self):
        mini._record_preflight_conflict_snapshot({
            "conflicts": [
                {"kind": "duplicate_declaration", "severity": "error", "symbol": "first",
                 "files": ["app.js:1", "app.js:2"]},
                {"kind": "duplicate_declaration", "severity": "error", "symbol": "second",
                 "files": ["app.js:4", "app.js:5"]},
            ],
        })

        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 2)

    def test_conflict_disappearance_is_resolved_once(self):
        conflict = {"kind": "duplicate_html_id", "severity": "error", "id": "game",
                    "files": ["index.html"], "message": "duplicate id"}
        mini._record_preflight_conflict_snapshot({"conflicts": [conflict]})
        mini._record_preflight_conflict_snapshot({"conflicts": []})
        mini._record_preflight_conflict_snapshot({"conflicts": []})

        mini.recompute_integration_metrics()
        fingerprint = mini._preflight_conflict_fingerprint(conflict)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 1)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 1)
        self.assertEqual(mini.PREFLIGHT_CONFLICT_STATE["registry"][fingerprint]["resolved_after"], 2)

    def test_reappearing_conflict_is_not_new_and_is_finally_unresolved(self):
        conflict = {"kind": "duplicate_declaration", "severity": "error", "symbol": "value",
                    "files": ["app.js:10", "app.js:20"]}
        mini._record_preflight_conflict_snapshot({"conflicts": [conflict]})
        mini._record_preflight_conflict_snapshot({"conflicts": []})
        mini._record_preflight_conflict_snapshot({"conflicts": [conflict]})

        mini.recompute_integration_metrics()
        fingerprint = mini._preflight_conflict_fingerprint(conflict)
        record = mini.PREFLIGHT_CONFLICT_STATE["registry"][fingerprint]
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 1)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 0)
        self.assertEqual(record["status"], "unresolved")

    def test_preflight_sequence_a_b_c_then_b_c_then_c_resolves_two_unique_conflicts(self):
        conflicts = {
            name: {"kind": "duplicate_declaration", "severity": "error", "symbol": name,
                   "files": ["app.js:1", "app.js:2"]}
            for name in ("A", "B", "C")
        }
        mini._record_preflight_conflict_snapshot({"conflicts": list(conflicts.values())})
        mini._record_preflight_conflict_snapshot({"conflicts": [conflicts["B"], conflicts["C"]]})
        mini._record_preflight_conflict_snapshot({"conflicts": [conflicts["C"]]})

        mini.recompute_integration_metrics()
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_detected"], 3)
        self.assertEqual(mini.RUN["preflight_blocking_conflicts_resolved"], 2)
        self.assertEqual(mini.RUN["integration_conflict_resolution"], 66.67)

    def test_integration_conflict_resolution_reports_na_when_no_conflicts_exist(self):
        mini.recompute_integration_metrics()
        with patch("builtins.print") as printer:
            mini.print_integration_metrics()
        output = "\n".join(str(call.args[0]) for call in printer.call_args_list)
        self.assertIn("integration_conflict_resolution: 0/0 (N/A)", output)


if __name__ == "__main__":
    unittest.main()
