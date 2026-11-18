import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mini
from hivo import execution_contracts as execution


class StructuralDecompositionTests(unittest.TestCase):
    """Pure V19.4 structural-fit and routing checks; never calls Gemma."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")
        mini.RUN["tasks_created"] = 1

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    @staticmethod
    def contract(**overrides):
        value = {
            "execution_contract_id": "EXEC-STRUCT-001",
            "plan_id": "PLAN-STRUCTURAL-001",
            "plan_hash": "plan-hash-001",
            "contract_hash": "contract-hash-001",
            "responsibility_type": execution.MUTATION,
            "worker_required": True,
            "goal": "Approved responsibility",
            "allowed_mutation_paths": ["src/input.js"],
            "allowed_mutation_surface_ids": ["SURF-INPUT"],
            "allowed_inspection_paths": ["src/input.js", "src/game.js"],
            "allowed_inspection_surface_ids": ["SURF-INPUT", "SURF-GAME"],
            "requirement_ids": ["REQ-001"],
            "requirements": [{"requirement_id": "REQ-001", "text": "one approved requirement"}],
            "obligation_types": ["BEHAVIOR_CHANGE"],
            "done_when": ["the approved responsibility is verified"],
            "interfaces_to_reuse": ["InputManager.isPressed", "GameState.togglePause"],
            "local_preservation_constraints": ["preserve the current owners"],
            "structured_prohibitions": ["do not create a duplicate owner"],
            "global_do_not_touch": ["src/game.js", "src/storage.js"],
            "global_do_not_touch_surface_ids": ["SURF-GAME", "SURF-STORAGE"],
            "test_contract": ["run the focused test"],
        }
        value.update(overrides)
        return value

    @classmethod
    def atomic_contract(cls, **overrides):
        value = cls.contract(
            allowed_mutation_paths=["src/input.js", "src/status_view.js"],
            allowed_mutation_surface_ids=["SURF-INPUT", "SURF-VIEW"],
            allowed_inspection_paths=["src/input.js", "src/status_view.js", "src/game.js"],
            allowed_inspection_surface_ids=["SURF-INPUT", "SURF-VIEW", "SURF-GAME"],
            done_when=["the input behavior is verified", "the view behavior is verified"],
        )
        value.update(overrides)
        return value

    @classmethod
    def stage4b_parent(cls):
        return cls.contract(
            execution_contract_id="EXEC-001",
            plan_id="PLAN-39BFD3539D2F",
            plan_hash="39bfd3539d2fead7ce65d6fc785daaf8feabb982d9ec638b8bb17170ad63bf59",
            contract_hash="d46504ed23df353a1ae4d854ee45d54d9caa11101bbe9c954f5d9d00b9005e50",
            goal=(
                "Add the approved behavior across the existing input, view, and test architecture "
                "while preserving the sole pause owner."
            ),
            allowed_mutation_paths=[
                "src/input.js", "src/status_view.js", "tests/pause_flow.test.js",
            ],
            allowed_mutation_surface_ids=["SURF-INPUT", "SURF-VIEW", "SURF-TEST"],
            allowed_inspection_paths=[
                "src/input.js", "src/status_view.js", "tests/pause_flow.test.js",
                "src/pause_controller.js",
            ],
            allowed_inspection_surface_ids=[
                "SURF-INPUT", "SURF-VIEW", "SURF-TEST", "SURF-PAUSE",
            ],
            requirement_ids=["REQ-001", "REQ-002", "REQ-003", "REQ-004", "REQ-005"],
            requirements=[
                {"requirement_id": f"REQ-00{index}", "text": f"approved requirement {index}"}
                for index in range(1, 6)
            ],
            obligation_types=["BEHAVIOR_CHANGE", "PRESERVATION", "ARCHITECTURE_REUSE", "TEST"],
            done_when=[
                "Input behavior is complete.",
                "View behavior is complete.",
                "Focused tests are complete.",
            ],
            test_contract=["the focused pause-flow test passes"],
            local_preservation_constraints=[
                "preserve existing WASD and arrow movement controls",
                "preserve InputManager ownership",
                "preserve the sole pause-state owner",
            ],
            structured_prohibitions=[
                "do not create duplicate input state",
                "do not create a second pause owner",
            ],
            global_do_not_touch=["src/pause_controller.js"],
            global_do_not_touch_surface_ids=["SURF-PAUSE"],
            interfaces_to_reuse=["PauseController.togglePause()"],
        )

    def task(self, contract):
        return mini.make_task(
            contract["execution_contract_id"], contract["goal"], 1, "ROOT",
            contract.get("done_when", []), contract.get("allowed_mutation_paths", []),
            execution_contract_id=contract["execution_contract_id"],
            execution_contract=contract,
        )

    def test_structural_analyzer_is_zero_model_and_deterministic(self):
        contract = self.stage4b_parent()
        before = copy.deepcopy(contract)
        with patch.object(mini, "structured_model_call", side_effect=AssertionError("model called")):
            first = execution.analyze_structural_fit(contract)
            second = execution.structural_fit_analyzer(contract)
        self.assertEqual(first, second)
        self.assertEqual(first["model_calls"], 0)
        self.assertEqual(first["structural_fit_hash"], execution.deterministic_hash(
            execution._without(first, "structural_fit_hash"),
        ))
        self.assertEqual(contract, before)

    def test_simple_contract_is_direct_allowed(self):
        evidence = execution.analyze_structural_fit(self.contract())
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)
        self.assertEqual(evidence["mutation_path_count"], 1)
        self.assertEqual(evidence["mutation_surface_count"], 1)
        self.assertEqual(evidence["owned_responsibility_count"], 1)

    def test_stage4a_fixture_is_not_forced_to_decompose(self):
        contract = self.contract(
            goal="Add Escape pause/resume while preserving current architecture.",
            allowed_mutation_paths=["src/input.js"],
            allowed_mutation_surface_ids=["SURF-INPUT"],
            allowed_inspection_paths=["src/input.js", "src/game.js"],
        )
        evidence = execution.analyze_structural_fit(contract)
        self.assertIn(evidence["classification"], {execution.DIRECT_ALLOWED, execution.AMBIGUOUS})
        self.assertNotEqual(evidence["classification"], execution.DECOMPOSITION_REQUIRED)

    def test_inspection_only_paths_do_not_count_as_mutation_owners(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_inspection_paths=[
                "src/input.js", "src/game.js", "src/storage.js", "index.html",
            ],
        ))
        self.assertEqual(evidence["mutation_path_count"], 1)
        self.assertEqual(evidence["owned_responsibility_count"], 1)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_dnt_paths_do_not_count_as_mutation_owners(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_inspection_paths=["src/input.js", "src/game.js", "src/storage.js"],
            global_do_not_touch=["src/game.js", "src/storage.js", "index.html"],
        ))
        self.assertEqual(evidence["mutation_path_count"], 1)
        self.assertNotIn("src/game.js", evidence["distinct_mutation_owners"])
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_interface_reuse_alone_does_not_force_split(self):
        evidence = execution.analyze_structural_fit(self.contract(
            interfaces_to_reuse=[f"Interface.{index}" for index in range(12)],
        ))
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)
        self.assertEqual(evidence["owned_responsibility_count"], 1)

    def test_single_mutation_path_is_not_forced_by_completion_count(self):
        evidence = execution.analyze_structural_fit(self.contract(
            done_when=[f"completion {index}" for index in range(8)],
        ))
        self.assertEqual(evidence["done_when_count"], 8)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_many_requirements_on_one_path_are_not_automatic_split(self):
        evidence = execution.analyze_structural_fit(self.contract(
            requirement_ids=[f"REQ-{index:03d}" for index in range(16)],
            requirements=[{"requirement_id": f"REQ-{index:03d}", "text": "approved"} for index in range(16)],
        ))
        self.assertEqual(evidence["requirement_count"], 16)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_many_obligation_types_on_one_path_are_not_automatic_split(self):
        evidence = execution.analyze_structural_fit(self.contract(
            obligation_types=[f"OBLIGATION_{index}" for index in range(12)],
        ))
        self.assertEqual(evidence["obligation_type_count"], 12)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_two_tightly_bound_mutation_paths_are_ambiguous(self):
        evidence = execution.analyze_structural_fit(self.atomic_contract())
        self.assertEqual(evidence["classification"], execution.AMBIGUOUS)
        self.assertEqual(evidence["mutation_path_count"], 2)
        self.assertNotIn(execution.DECOMPOSITION_REQUIRED, evidence["classification"])

    def test_two_paths_with_many_completion_entries_remain_ambiguous(self):
        evidence = execution.analyze_structural_fit(self.atomic_contract(
            done_when=[f"atomic completion {index}" for index in range(8)],
        ))
        self.assertEqual(evidence["classification"], execution.AMBIGUOUS)
        self.assertEqual(evidence["done_when_count"], 8)

    def test_three_owners_with_separate_completion_is_required(self):
        evidence = execution.analyze_structural_fit(self.stage4b_parent())
        self.assertEqual(evidence["classification"], execution.DECOMPOSITION_REQUIRED)
        self.assertEqual(evidence["mutation_path_count"], 3)
        self.assertEqual(evidence["mutation_surface_count"], 3)
        self.assertEqual(evidence["owned_responsibility_count"], 3)
        self.assertEqual(evidence["done_when_count"], 3)
        self.assertIn("THREE_MUTATION_OWNERS_WITH_SEPARATE_COMPLETION", evidence["reason_codes"])

    def test_three_paths_without_separate_completion_are_ambiguous(self):
        contract = self.contract(
            allowed_mutation_paths=["src/input.js", "src/status_view.js", "src/view_model.js"],
            allowed_mutation_surface_ids=["SURF-INPUT", "SURF-VIEW", "SURF-MODEL"],
            done_when=["one atomic completion"],
        )
        evidence = execution.analyze_structural_fit(contract)
        self.assertEqual(evidence["classification"], execution.AMBIGUOUS)
        self.assertEqual(evidence["owned_responsibility_count"], 3)

    def test_mixed_implementation_and_test_mutation_requires_split(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_mutation_paths=["src/input.js", "tests/input.test.js"],
            allowed_mutation_surface_ids=["SURF-INPUT", "SURF-TEST"],
        ))
        self.assertEqual(evidence["has_test_mutation"], True)
        self.assertEqual(evidence["has_non_test_mutation"], True)
        self.assertEqual(evidence["classification"], execution.DECOMPOSITION_REQUIRED)
        self.assertIn("MIXED_IMPLEMENTATION_AND_TEST_MUTATION", evidence["reason_codes"])

    def test_test_only_contract_is_not_mixed_implementation(self):
        evidence = execution.analyze_structural_fit(self.contract(
            execution_contract_id="EXEC-TEST",
            responsibility_type=execution.TEST_MUTATION,
            allowed_mutation_paths=["tests/input.test.js"],
            allowed_mutation_surface_ids=["SURF-TEST"],
        ))
        self.assertTrue(evidence["has_test_mutation"])
        self.assertFalse(evidence["has_non_test_mutation"])
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_explicit_test_mutation_paths_are_structural_metadata(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_mutation_paths=["src/input.js", "src/fixture.js"],
            allowed_mutation_surface_ids=["SURF-INPUT", "SURF-FIXTURE"],
            test_mutation_paths=["src/fixture.js"],
        ))
        self.assertTrue(evidence["has_test_mutation"])
        self.assertEqual(evidence["classification"], execution.DECOMPOSITION_REQUIRED)

    def test_prose_does_not_influence_structural_classification(self):
        first = self.contract(
            goal="and plus then a broad architecture phrase",
            local_preservation_constraints=["pause/resume halt/resume loop/update WASD/arrow"],
            structured_prohibitions=["do not touch everything"],
        )
        second = self.contract(
            goal="one focused responsibility",
            local_preservation_constraints=["keep one owner"],
            structured_prohibitions=["keep scope bounded"],
        )
        self.assertEqual(
            execution.analyze_structural_fit(first)["classification"],
            execution.analyze_structural_fit(second)["classification"],
        )

    def test_explicit_mutation_owner_ids_are_used_without_prose_parsing(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_mutation_paths=["src/a.js", "src/b.js", "src/c.js"],
            allowed_mutation_surface_ids=[],
            distinct_mutation_owners=["OWNER-A", "OWNER-B", "OWNER-C"],
            done_when=["a", "b", "c"],
        ))
        self.assertEqual(evidence["distinct_mutation_owners"], ["OWNER-A", "OWNER-B", "OWNER-C"])
        self.assertEqual(evidence["classification"], execution.DECOMPOSITION_REQUIRED)

    def test_structural_metadata_is_separate_from_contract_hash(self):
        contract = self.stage4b_parent()
        original_hash = contract["contract_hash"]
        evidence = execution.analyze_structural_fit(contract)
        self.assertEqual(contract["contract_hash"], original_hash)
        self.assertNotIn("structural_fit_hash", contract)
        self.assertEqual(evidence["contract_hash"], original_hash)

    def test_public_mini_probe_records_one_cached_artifact(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        first = mini.structural_fit_for_task(task, contract)
        second = mini.structural_fit_for_task(task, contract)
        self.assertEqual(first, second)
        self.assertEqual(mini.RUN["structural_fit_analyzer_calls"], 1)
        self.assertEqual(mini.RUN["structural_fit_decomposition_required"], 1)
        self.assertEqual(mini.RUN["structural_decomposition_obligations"], 1)

    def test_direct_route_skips_existing_task_fit_and_reaches_leaf(self):
        contract = self.contract()
        task = self.task(contract)
        fit = Mock(side_effect=AssertionError("DIRECT_ALLOWED called Task-Fit"))
        leaf = Mock(return_value={"status": "done", "summary": "verified", "memory": {}, "changed_files": []})
        result = mini.solve_task(
            task, 1, contract, {}, {"files": []}, fit_decider=fit, leaf_executor=leaf,
        )
        self.assertEqual(result["status"], "done")
        fit.assert_not_called()
        leaf.assert_called_once()
        self.assertEqual(task["fit_before_execution"]["decision"], "EXECUTE")

    def test_ambiguous_route_uses_existing_bounded_fit_decider(self):
        contract = self.atomic_contract()
        task = self.task(contract)
        fit = Mock(return_value={"decision": "execute", "reason": "atomic"})
        leaf = Mock(return_value={"status": "done", "summary": "verified", "memory": {}, "changed_files": []})
        result = mini.solve_task(
            task, 1, contract, {}, {"files": []}, fit_decider=fit, leaf_executor=leaf,
        )
        self.assertEqual(result["status"], "done")
        fit.assert_called_once()
        self.assertEqual(task["structural_fit"]["classification"], execution.AMBIGUOUS)

    def test_ambiguous_task_fit_prompt_is_contract_local(self):
        contract = self.atomic_contract()
        task = self.task(contract)
        with patch.object(mini, "structured_model_call", return_value={"decision": "execute"}) as model:
            decision = mini.decide_task_fit(task, 1, contract, repo_snapshot={"files": []})
        self.assertEqual(decision["decision"], "execute")
        model.assert_called_once()
        prompt = model.call_args.args[0]
        self.assertIn(contract["execution_contract_id"], prompt)
        self.assertIn(contract["contract_hash"], prompt)
        self.assertNotIn("full_project_brain", prompt.casefold())

    def test_required_route_does_not_call_fit_or_worker(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        fit = Mock(return_value={"decision": "execute", "reason": "model downgrade"})
        leaf = Mock(side_effect=AssertionError("required split reached Worker"))
        decomposer = Mock(return_value=[])
        with patch.object(mini, "decompose_task", decomposer), patch.object(
            mini, "structured_model_call", side_effect=AssertionError("Task-Fit model called")
        ):
            result = mini.solve_task(
                task, 1, contract, {}, {"files": []}, fit_decider=fit, leaf_executor=leaf,
            )
        self.assertEqual(result["failure_type"], execution.STRUCTURAL_DECOMPOSITION_REQUIRED)
        fit.assert_not_called()
        leaf.assert_not_called()
        decomposer.assert_called_once()

    def test_required_route_cannot_be_downgraded_by_execute_answer(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        fit = Mock(return_value={"decision": "execute"})
        decomposer = Mock(return_value=[])
        with patch.object(mini, "decompose_task", decomposer):
            result = mini.solve_task(
                task, 1, contract, {}, {"files": []}, fit_decider=fit,
                leaf_executor=Mock(),
            )
        self.assertEqual(result["failure_type"], execution.STRUCTURAL_DECOMPOSITION_REQUIRED)
        fit.assert_not_called()

    def test_required_route_does_not_fall_through_when_decomposer_has_no_children(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        leaf = Mock()
        with patch.object(mini, "decompose_task", return_value=[]), patch.object(mini, "execute_leaf", leaf):
            result = mini.solve_task(task, 1, contract, {}, {"files": []})
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["failure_type"], execution.STRUCTURAL_DECOMPOSITION_REQUIRED)
        leaf.assert_not_called()

    def test_required_route_is_blocked_at_depth_budget_without_direct_worker(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        mini.RUN["tasks_created"] = mini.MAX_TOTAL_TASKS
        leaf = Mock()
        with patch.object(mini, "decompose_task") as decomposer, patch.object(mini, "execute_leaf", leaf):
            result = mini.solve_task(task, mini.MAX_DEPTH, contract, {}, {"files": []})
        self.assertEqual(result["failure_type"], execution.STRUCTURAL_DECOMPOSITION_REQUIRED)
        decomposer.assert_not_called()
        leaf.assert_not_called()

    def test_non_contract_recursive_task_keeps_existing_fit_injection(self):
        contract = {"status": "ready", "goal": "legacy node", "requirements": ["one"]}
        task = mini.make_task("legacy", "legacy node", 1, "ROOT", ["done"], ["src/app.js"])
        fit = Mock(return_value={"decision": "execute"})
        leaf = Mock(return_value={"status": "done", "summary": "verified", "memory": {}, "changed_files": []})
        result = mini.solve_task(task, 1, contract, {}, {"files": []}, fit_decider=fit, leaf_executor=leaf)
        self.assertEqual(result["status"], "done")
        fit.assert_called_once()

    def test_analyzer_precedes_model_and_downstream_failure_paths(self):
        contract = self.stage4b_parent()
        task = self.task(contract)
        event_kinds = []
        original = mini.record_run_event

        def record(kind, **payload):
            event_kinds.append(kind)
            return original(kind, **payload)

        with patch.object(mini, "record_run_event", side_effect=record), patch.object(
            mini, "decompose_task", return_value=[]
        ):
            mini.solve_task(task, 1, contract, {}, {"files": []})
        self.assertIn("structural_fit_analyzed", event_kinds)
        self.assertNotIn("mission_compilation_failure", event_kinds)
        self.assertLess(event_kinds.index("structural_fit_analyzed"), len(event_kinds))

    def test_analyzer_never_synthesizes_children(self):
        evidence = execution.analyze_structural_fit(self.stage4b_parent())
        self.assertNotIn("children", evidence)
        self.assertNotIn("child_contracts", evidence)

    def test_stage4b_exact_shape_has_expected_structural_counters(self):
        evidence = execution.analyze_structural_fit(self.stage4b_parent())
        expected = {
            "mutation_path_count": 3,
            "mutation_surface_count": 3,
            "owned_responsibility_count": 3,
            "requirement_count": 5,
            "obligation_type_count": 4,
            "done_when_count": 3,
            "has_test_mutation": True,
            "has_non_test_mutation": True,
        }
        for field, value in expected.items():
            with self.subTest(field=field):
                self.assertEqual(evidence[field], value)

    def test_structural_hash_is_stable_across_equivalent_copies(self):
        contract = self.stage4b_parent()
        first = execution.analyze_structural_fit(contract)
        second = execution.analyze_structural_fit(copy.deepcopy(contract))
        self.assertEqual(first["structural_fit_hash"], second["structural_fit_hash"])

    def test_structural_hash_changes_only_when_structural_authority_changes(self):
        contract = self.contract()
        first = execution.analyze_structural_fit(contract)
        changed = copy.deepcopy(contract)
        changed["allowed_mutation_paths"] = ["src/other.js"]
        changed["allowed_mutation_surface_ids"] = ["SURF-OTHER"]
        second = execution.analyze_structural_fit(changed)
        self.assertNotEqual(first["structural_fit_hash"], second["structural_fit_hash"])
        prose = copy.deepcopy(contract)
        prose["goal"] = "a different natural-language goal"
        self.assertEqual(
            first["structural_fit_hash"],
            execution.analyze_structural_fit(prose)["structural_fit_hash"],
        )

    def test_metric_aliases_are_kept_in_sync(self):
        mini.structural_fit_for_task(self.task(self.contract()))
        self.assertEqual(mini.RUN["structural_fit_calls"], 1)
        self.assertEqual(mini.RUN["structural_fit_analyzer_calls"], 1)
        self.assertEqual(mini.RUN["structural_fit_direct_allowed"], 1)

    def test_worker_context_limit_is_unchanged(self):
        self.assertEqual(mini.MAX_WORKER_MISSION_CHARS, 4200)

    def test_non_worker_contract_with_no_mutation_is_direct_allowed(self):
        evidence = execution.analyze_structural_fit(self.contract(
            worker_required=False,
            allowed_mutation_paths=[],
            allowed_mutation_surface_ids=[],
        ))
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)
        self.assertEqual(evidence["mutation_path_count"], 0)
        self.assertIn("NO_MUTATION_RESPONSIBILITY", evidence["reason_codes"])

    def test_preservation_constraints_do_not_create_mutation_owners(self):
        evidence = execution.analyze_structural_fit(self.contract(
            local_preservation_constraints=[f"preservation {index}" for index in range(16)],
        ))
        self.assertEqual(evidence["owned_responsibility_count"], 1)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_prohibitions_do_not_create_mutation_owners(self):
        evidence = execution.analyze_structural_fit(self.contract(
            structured_prohibitions=[f"prohibition {index}" for index in range(16)],
        ))
        self.assertEqual(evidence["owned_responsibility_count"], 1)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_inspection_surface_ids_do_not_create_mutation_owners(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_inspection_surface_ids=[f"SURF-READ-{index}" for index in range(16)],
        ))
        self.assertEqual(evidence["mutation_surface_count"], 1)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_protected_mutation_paths_are_excluded_from_structural_evidence(self):
        evidence = execution.analyze_structural_fit(self.contract(
            allowed_mutation_paths=["src/game.js", "src/storage.js"],
            allowed_mutation_surface_ids=["SURF-GAME", "SURF-STORAGE"],
            global_do_not_touch=["src/game.js", "src/storage.js"],
            global_do_not_touch_surface_ids=["SURF-GAME", "SURF-STORAGE"],
        ))
        self.assertEqual(evidence["mutation_path_count"], 0)
        self.assertEqual(evidence["mutation_surface_count"], 0)
        self.assertEqual(evidence["owned_responsibility_count"], 0)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_child_scope_uses_shrunk_paths_not_inherited_parent_surfaces(self):
        parent = self.stage4b_parent()
        child = execution.child_contract(parent, {
            "child_id": "CHILD-INPUT",
            "scope_hint": ["src/input.js"],
            "done_when": [parent["done_when"][0]],
        })
        evidence = execution.analyze_structural_fit(child)
        self.assertEqual(evidence["mutation_surface_count"], 3)
        self.assertEqual(evidence["owned_responsibility_count"], 1)
        self.assertEqual(evidence["classification"], execution.DIRECT_ALLOWED)

    def test_structural_evidence_validator_accepts_untampered_output(self):
        contract = self.stage4b_parent()
        evidence = execution.analyze_structural_fit(contract)
        self.assertTrue(execution.validate_structural_fit(evidence, contract)["valid"])

    def test_structural_evidence_validator_rejects_tampering(self):
        evidence = execution.analyze_structural_fit(self.stage4b_parent())
        evidence["classification"] = execution.DIRECT_ALLOWED
        self.assertFalse(execution.validate_structural_fit(evidence)["valid"])

    def test_contract_authority_fields_are_not_rewritten_by_routing(self):
        contract = self.stage4b_parent()
        before = copy.deepcopy(contract)
        task = self.task(contract)
        with patch.object(mini, "decompose_task", return_value=[]):
            mini.solve_task(task, 1, contract, {}, {"files": []})
        self.assertEqual(contract, before)

    def test_child_validation_remains_available_after_structural_probe(self):
        parent = self.contract()
        checked = execution.validate_child_specs(parent, [
            {"goal": "focused input", "done_when": parent["done_when"], "scope_hint": ["src/input.js"]},
            {"goal": "focused verification", "done_when": parent["done_when"], "scope_hint": ["src/input.js"]},
        ])
        self.assertTrue(checked["valid"], checked)
        self.assertEqual(execution.analyze_structural_fit(parent)["classification"], execution.DIRECT_ALLOWED)

    def test_structural_probe_does_not_change_mission_compiler_or_projection_constants(self):
        self.assertEqual(execution.WORKER_CONTEXT_RENDERING_VERSION, "v19.3-1")
        self.assertEqual(execution.MAX_HYDRATED_MISSION_CHARS, 26000)
        self.assertEqual(mini.MAX_WORKER_MISSION_CHARS, 4200)
        execution.analyze_structural_fit(self.stage4b_parent())


if __name__ == "__main__":
    unittest.main()
