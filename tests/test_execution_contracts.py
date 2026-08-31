import copy
import json
import unittest
from unittest.mock import patch

import mini
from hivo import execution_contracts as execution
from tests import test_obligation_aware_plan_closure as pause_fixture


class ApprovedPlanExecutionContractTests(unittest.TestCase):
    """Deterministic Stage 4A checks; no live model or benchmark is used."""

    def setUp(self):
        self.fixture = pause_fixture.ObligationAwarePlanClosureTests(
            "test_obligation_ledger_is_deterministic_typed_and_provenance_aware",
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        _, _, _, _, self.plan, self.plan_gate = self.fixture.closed_fixture()
        self.goal = self.fixture.goal
        self.requirements = self.fixture.requirements
        self.evidence = self.fixture.evidence
        self.registry = self.fixture.registry
        self.approval = {
            "approval_status": "APPROVED",
            "plan_id": self.plan["plan_id"],
            "plan_hash": self.plan["plan_hash"],
            "approval_source": "DETERMINISTIC_TEST",
        }

    def snapshot(self):
        return execution.create_approved_plan_snapshot(
            self.plan, self.approval, self.goal, self.requirements,
            self.evidence, self.registry,
        )

    def compiled(self):
        snapshot = self.snapshot()
        compiled = execution.compile_execution_contracts(snapshot)
        graph = execution.build_execution_graph(snapshot, compiled["contracts"])
        return snapshot, compiled, graph

    def root_contract(self):
        return {
            "status": "ready", "goal": self.goal,
            "original_goal": self.goal,
            "requirements": [item["text"] for item in self.requirements],
            "success_criteria": ["the approved graph is verified"],
            "source_contract": {"root_goal": self.goal},
        }

    def test_snapshot_is_approved_bounded_immutable_and_hygienic(self):
        snapshot = self.snapshot()
        checked = execution.validate_snapshot(
            snapshot, self.plan, self.approval, self.goal,
        )
        self.assertTrue(checked["valid"], checked["errors"])
        self.assertTrue(snapshot["immutable"])
        self.assertLessEqual(checked["serialized_chars"], execution.MAX_SNAPSHOT_CHARS)
        with self.assertRaises(TypeError):
            snapshot["task_goal"] = "changed"
        with self.assertRaises(TypeError):
            snapshot["plan_nodes"][0]["goal"] = "changed"
        encoded = json.dumps(snapshot, ensure_ascii=False, default=str).casefold()
        for forbidden in (
            "raw_impact_planner_output", "raw_impact_challenger_output",
            "planner_transcript", "challenger_transcript", "full_project_brain",
            "full_task_brain", "source_ledger",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_approval_is_required_and_stale_hash_is_blocked(self):
        pending = dict(self.approval, approval_status="PENDING")
        with self.assertRaises(execution.ApprovedPlanSnapshotError) as raised:
            execution.create_approved_plan_snapshot(
                self.plan, pending, self.goal, self.requirements,
                self.evidence, self.registry,
            )
        self.assertEqual(raised.exception.code, execution.PLAN_APPROVAL_REQUIRED)

        changed = copy.deepcopy(self.plan)
        changed["integration_verification"] = list(
            changed["integration_verification"],
        ) + ["materially changed after approval"]
        validation = execution.validate_approved_plan(
            changed, self.approval, self.goal, current_plan=changed,
        )
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["code"], execution.APPROVED_PLAN_STALE)
        with self.assertRaises(execution.ApprovedPlanSnapshotError) as raised:
            execution.create_approved_plan_snapshot(
                changed, self.approval, self.goal, self.requirements,
                self.evidence, self.registry,
            )
        self.assertEqual(raised.exception.code, execution.APPROVED_PLAN_STALE)

    def test_required_authority_overflow_fails_without_silent_trimming(self):
        oversized = copy.deepcopy(self.plan)
        oversized["do_not_touch"] = [
            f"src/protected-{index}.js"
            for index in range(execution.MAX_SURFACES_PER_CONTRACT + 1)
        ]
        oversized = mini.stage3.finalize_plan_identity(oversized)
        approval = {
            "approval_status": "APPROVED",
            "plan_id": oversized["plan_id"],
            "plan_hash": oversized["plan_hash"],
        }
        with self.assertRaises(execution.ExecutionContractTooLargeError) as raised:
            execution.create_approved_plan_snapshot(
                oversized, approval, self.goal, self.requirements,
                self.evidence, self.registry,
            )
        self.assertEqual(raised.exception.code, execution.EXECUTION_CONTRACT_TOO_LARGE)

    def test_compiler_is_deterministic_zero_model_calls_and_preserves_traceability(self):
        first_snapshot, first, first_graph = self.compiled()
        second_snapshot, second, second_graph = self.compiled()
        self.assertEqual(first_snapshot, second_snapshot)
        self.assertEqual(first["contracts"], second["contracts"])
        self.assertEqual(first_graph, second_graph)
        self.assertEqual(first["metrics"]["execution_contract_mutation"], 1)
        self.assertEqual(first["metrics"]["execution_contract_test"], 1)
        self.assertEqual(first["metrics"]["execution_contract_verify_only"], 0)
        with patch.object(mini, "structured_model_call", side_effect=AssertionError("compiler called a model")):
            execution.compile_execution_contracts(first_snapshot)
        for contract in first["contracts"]:
            self.assertEqual(contract["plan_id"], self.plan["plan_id"])
            self.assertEqual(contract["plan_hash"], self.plan["plan_hash"])
            self.assertTrue(contract["plan_node_ids"])
            self.assertTrue(contract["requirement_ids"])
            self.assertEqual(
                contract["contract_hash"],
                execution.deterministic_hash(execution._without(contract, "contract_hash")),
            )

        changed = copy.deepcopy(first["contracts"][0])
        changed["goal"] += " with a changed approved responsibility"
        changed["contract_hash"] = execution.deterministic_hash(
            execution._without(changed, "contract_hash"),
        )
        self.assertNotEqual(changed["contract_hash"], first["contracts"][0]["contract_hash"])

    def test_controlled_pause_graph_is_minimal_and_carries_all_authority(self):
        snapshot, compiled, graph = self.compiled()
        contracts = {item["execution_contract_id"]: item for item in compiled["contracts"]}
        mutation = contracts["EXEC-001"]
        test = contracts["EXEC-002"]
        self.assertEqual(mutation["responsibility_type"], execution.MUTATION)
        self.assertEqual(mutation["allowed_mutation_paths"], ["src/input.js"])
        self.assertEqual(test["responsibility_type"], execution.TEST_MUTATION)
        self.assertEqual(test["allowed_mutation_paths"], ["tests/input.test.js"])
        self.assertEqual(test["dependencies"], ["EXEC-001"])
        self.assertEqual(graph["topological_order"], ["EXEC-001", "EXEC-002"])
        self.assertNotIn("src/storage.js", mutation["allowed_mutation_paths"])
        self.assertNotIn("src/game.js", mutation["allowed_mutation_paths"])
        self.assertIn("src/game.js", mutation["allowed_inspection_paths"])
        self.assertIn("InputManager.isPressed", mutation["interfaces_to_reuse"])
        self.assertIn("GameState.togglePause", mutation["interfaces_to_reuse"])
        for text in (
            "WASD", "arrow", "input ownership", "storage behavior",
        ):
            self.assertIn(text.casefold(), json.dumps(mutation).casefold())
        self.assertTrue(set(snapshot["global_do_not_touch"]).issubset(mutation["global_do_not_touch"]))
        self.assertTrue(set(snapshot["structured_prohibitions"]).issubset(mutation["structured_prohibitions"]))
        self.assertTrue(execution.validate_execution_graph(snapshot, graph, compiled["contracts"])["valid"])

    def test_preservation_only_plan_gets_verification_authority_without_worker(self):
        preservation_plan = copy.deepcopy(self.plan)
        preservation_plan["approved_change_nodes"] = []
        preservation_plan = mini.stage3.finalize_plan_identity(preservation_plan)
        approval = {
            "approval_status": "APPROVED",
            "plan_id": preservation_plan["plan_id"],
            "plan_hash": preservation_plan["plan_hash"],
        }
        snapshot = execution.create_approved_plan_snapshot(
            preservation_plan, approval, self.goal, self.requirements,
            self.evidence, self.registry,
        )
        compiled = execution.compile_execution_contracts(snapshot)
        self.assertTrue(compiled["contracts"])
        self.assertFalse(any(item["worker_required"] for item in compiled["contracts"]))
        self.assertTrue(all(item["responsibility_type"] == execution.VERIFY_ONLY for item in compiled["contracts"]))
        self.assertTrue(execution.validate_contracts(snapshot, compiled["contracts"])["valid"])

    def test_dag_coverage_duplicate_and_dependency_validation(self):
        snapshot, compiled, graph = self.compiled()
        missing = [compiled["contracts"][1]]
        with self.assertRaises(execution.ExecutionGraphError) as raised:
            execution.build_execution_graph(snapshot, missing)
        self.assertEqual(raised.exception.code, execution.EXECUTION_GRAPH_INVALID)

        duplicate = copy.deepcopy(compiled["contracts"])
        duplicate[1]["plan_node_ids"].append(duplicate[0]["plan_node_ids"][0])
        duplicate[1]["contract_hash"] = execution.deterministic_hash(
            execution._without(duplicate[1], "contract_hash"),
        )
        checked = execution.validate_contracts(snapshot, duplicate)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("duplicate ownership" in item for item in checked["errors"]))

        unknown_dependency = copy.deepcopy(compiled["contracts"])
        unknown_dependency[1]["dependencies"] = ["EXEC-999"]
        unknown_dependency[1]["contract_hash"] = execution.deterministic_hash(
            execution._without(unknown_dependency[1], "contract_hash"),
        )
        with self.assertRaises(execution.ExecutionGraphError):
            execution.build_execution_graph(snapshot, unknown_dependency)

        cycle = copy.deepcopy(compiled["contracts"])
        cycle[0]["dependencies"] = ["EXEC-002"]
        cycle[1]["dependencies"] = ["EXEC-001"]
        for item in cycle:
            item["contract_hash"] = execution.deterministic_hash(
                execution._without(item, "contract_hash"),
            )
        with self.assertRaises(execution.ExecutionGraphError):
            execution.build_execution_graph(snapshot, cycle)

    def test_mutation_and_inspection_are_separate_and_protected(self):
        _, compiled, _ = self.compiled()
        mutation = compiled["contracts"][0]
        self.assertTrue(execution.tool_scope(mutation, "src/input.js", mutation=True)["allowed"])
        self.assertTrue(execution.tool_scope(mutation, "src/game.js", mutation=False)["allowed"])
        for path in ("src/game.js", "src/storage.js", "tests/pause.test.js"):
            result = execution.tool_scope(mutation, path, mutation=True)
            self.assertFalse(result["allowed"], path)
            self.assertEqual(result["code"], execution.CONTRACT_SCOPE_VIOLATION)

    def test_validated_new_surface_proposal_retains_scoped_mutation_authority(self):
        proposal_plan = copy.deepcopy(self.plan)
        node = proposal_plan["approved_change_nodes"][0]
        node["surface_ids"] = []
        node["target_surface_ids"] = []
        node["candidate_targets"] = []
        node["target_paths"] = []
        node["new_surface_proposal_ids"] = ["NEW-ADAPTER"]
        node["target_new_surface_proposal_ids"] = ["NEW-ADAPTER"]
        node["parent_scopes"] = ["src"]
        proposal_plan["new_surface_proposals"] = [{
            "proposal_id": "NEW-ADAPTER", "kind": "MODULE", "parent_scope": "src",
            "intended_responsibility": "approved adapter", "verification_responsibility": "verify adapter",
            "requirement_ids": list(node["requirement_ids"]),
        }]
        proposal_plan = mini.stage3.finalize_plan_identity(proposal_plan)
        approval = {
            "approval_status": "APPROVED", "plan_id": proposal_plan["plan_id"],
            "plan_hash": proposal_plan["plan_hash"],
        }
        snapshot = execution.create_approved_plan_snapshot(
            proposal_plan, approval, self.goal, self.requirements,
            self.evidence, self.registry,
        )
        compiled = execution.compile_execution_contracts(snapshot)
        contract = next(
            item for item in compiled["contracts"]
            if item["target_new_surface_proposal_ids"] == ["NEW-ADAPTER"]
        )
        self.assertEqual(contract["approved_new_surface_parent_scopes"], ["src"])
        self.assertTrue(execution.tool_scope(contract, "src/new_adapter.js", mutation=True)["allowed"])
        self.assertFalse(execution.tool_scope(contract, "tests/new_adapter.js", mutation=True)["allowed"])

    def test_child_contracts_only_shrink_and_keep_protections_and_completion(self):
        _, compiled, _ = self.compiled()
        parent = compiled["contracts"][0]
        bad = execution.validate_child_specs(parent, [{
            "goal": "expand into game state",
            "done_when": list(parent["done_when"]),
            "scope_hint": ["src/input.js", "src/game.js"],
        }])
        self.assertFalse(bad["valid"])
        self.assertTrue(bad["rejected"])

        done = list(parent["done_when"])
        good = execution.validate_child_specs(parent, [
            {"goal": "focused input boundary", "done_when": done[:1], "scope_hint": ["src/input.js"]},
            {"goal": "focused input verification", "done_when": done[1:] or done[:1], "scope_hint": ["src/input.js"]},
        ])
        self.assertTrue(good["valid"], good["rejected"])
        for child in good["children"]:
            self.assertEqual(child["execution_contract_id"], parent["execution_contract_id"])
            self.assertEqual(child["contract_hash"], parent["contract_hash"])
            self.assertTrue(set(parent["local_preservation_constraints"]).issubset(child["local_preservation_constraints"]))
            self.assertTrue(set(parent["structured_prohibitions"]).issubset(child["structured_prohibitions"]))

        omitted = execution.child_contract(
            parent, {"child_id": "CHILD-BAD", "done_when": list(parent["done_when"])},
            restore_protections=False,
        )
        self.assertFalse(execution.validate_child_contract(parent, omitted)["valid"])

    def test_mission_and_clean_context_cannot_expand_authority(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        valid_mission = {
            "execution_contract_id": contract["execution_contract_id"],
            "execution_contract_hash": contract["contract_hash"],
            "approved_plan_hash": contract["plan_hash"],
            "goal_anchor": contract["goal"], "task": contract["goal"],
            "expected_outcome": "Escape behavior is verified",
            "targets": ["src/input.js"],
            "existing_facts": ["InputManager owns keyboard input"],
            "implementation_plan": ["Integrate Escape in src/input.js"],
            "interfaces_to_reuse": list(contract["interfaces_to_reuse"]),
            "invariants": list(contract["local_preservation_constraints"]),
            "project_specific_quality_rules": ["keep current owners"],
            "do_not": list(contract["global_do_not_touch"])
            + list(contract["structured_prohibitions"]),
            "verification_plan": ["verify the bounded Escape behavior"],
            "done_when": list(contract["done_when"]),
        }
        self.assertTrue(
            execution.validate_mission_against_contract(
                valid_mission, contract, require_identity=True,
            )["valid"]
        )
        outside = copy.deepcopy(valid_mission)
        outside["targets"] = ["src/game.js"]
        self.assertFalse(execution.validate_mission_against_contract(outside, contract)["valid"])
        missing_protection = copy.deepcopy(valid_mission)
        missing_protection["do_not"] = []
        missing_protection["invariants"] = []
        self.assertFalse(execution.validate_mission_against_contract(missing_protection, contract)["valid"])

        context = execution.build_worker_contract_context(
            contract,
            [{"task_id": "EXEC-000", "status": "done", "summary": "verified prerequisite"}],
        )
        encoded = json.dumps(context, ensure_ascii=False, default=str)
        for forbidden in (
            "raw_impact_planner_output", "raw_impact_challenger_output",
            "full_project_brain", "full_task_brain", "source_ledger",
            "unrelated contract",
        ):
            self.assertNotIn(forbidden, encoded.casefold())
        for required in (
            contract["goal"], "src/input.js", "src/game.js",
            "GameState.togglePause", "WASD", "do not violate", "Add Escape",
            contract["plan_hash"], contract["contract_hash"],
        ):
            self.assertIn(str(required).casefold(), encoded.casefold())

    def test_mission_compiler_receives_only_contract_projection(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        task = mini.make_task(
            "EXEC-001", contract["goal"], 1, "ROOT", contract["done_when"],
            contract["allowed_mutation_paths"], execution_contract_id="EXEC-001",
            execution_contract=contract,
        )
        prompts = []

        def structured(prompt, _validator, _label, _schema):
            prompts.append(prompt)
            return {
                "goal_anchor": contract["goal"], "task": contract["goal"],
                "expected_outcome": "Escape behavior is verified",
                "targets": ["src/input.js"],
                "existing_facts": ["InputManager owns keyboard input"],
                "implementation_plan": ["Integrate Escape in src/input.js"],
                "interfaces_to_reuse": list(contract["interfaces_to_reuse"]),
                "invariants": list(contract["local_preservation_constraints"]),
                "project_specific_quality_rules": ["keep current owners"],
                "do_not": list(contract["global_do_not_touch"])
                + list(contract["structured_prohibitions"]),
                "verification_plan": ["verify bounded Escape behavior"],
                "done_when": list(contract["done_when"]),
            }

        mission = mini.compile_worker_mission(
            task,
            {"full_project_brain": "must not be copied", "raw_impact_map": "must not be copied"},
            repo_snapshot={"files": []}, execution_contract=contract,
            strategy_context={"strategy": {"name": "unrelated strategy"}},
            task_context={"full_task_brain": "must not be copied"},
            structured_call=structured,
        )
        self.assertEqual(mission["execution_contract_id"], contract["execution_contract_id"])
        self.assertEqual(mission["execution_contract_hash"], contract["contract_hash"])
        self.assertEqual(len(prompts), 1)
        for forbidden in (
            "full_project_brain", "full_task_brain", "raw_impact_map",
            "approved_change_nodes", "unrelated strategy",
        ):
            self.assertNotIn(forbidden.casefold(), prompts[0].casefold())
        self.assertIn(contract["execution_contract_id"], prompts[0])
        self.assertIn(contract["plan_hash"], prompts[0])

    def test_worker_tool_guard_allows_inspection_but_rejects_mutation(self):
        root_contract = self.root_contract()
        mini.reset_run("recursive")
        mini.RUN.update({
            "project_mode": mini.EXISTING_PROJECT,
            "impact_planning_required": True,
            "source_contract": root_contract,
            "approved_change_plan": self.plan,
            "plan_approval": self.approval,
            "repository_evidence": self.evidence,
            "canonical_surface_registry": self.registry,
        })
        state = mini.compile_approved_plan_execution_contracts(
            contract=root_contract, plan=self.plan, approval=self.approval,
        )
        contract = state["contracts"][0]
        mini.ACTIVE_TOOL_CONTRACT = {
            "execution_contract_id": contract["execution_contract_id"],
            "execution_contract_hash": contract["contract_hash"],
        }
        (mini.WORKSPACE / "src").mkdir(parents=True, exist_ok=True)
        (mini.WORKSPACE / "src" / "game.js").write_text("export const paused = false;\n", encoding="utf-8")
        read_result = mini.run_tool("read_file", {"path": "src/game.js"}, role="Builder")
        self.assertNotIn(execution.CONTRACT_SCOPE_VIOLATION, read_result)
        mutation_result = mini.run_tool(
            "edit_file", {"path": "src/game.js", "old": "false", "new": "true"}, role="Builder",
        )
        self.assertIn(execution.CONTRACT_SCOPE_VIOLATION, mutation_result)

    def test_mini_gate_and_graph_execute_only_approved_contracts_in_order(self):
        root_contract = self.root_contract()
        mini.RUN.update({
            "project_mode": mini.EXISTING_PROJECT,
            "impact_planning_required": True,
            "source_contract": root_contract,
            "approved_change_plan": self.plan,
            "plan_approval": self.approval,
            "repository_evidence": self.evidence,
            "canonical_surface_registry": self.registry,
        })
        calls = []

        def leaf(task, _contract, memory, _repo, _parent, _deps):
            calls.append(task["execution_contract_id"])
            return {"status": "done", "summary": "verified", "memory": memory, "changed_files": []}

        result, _ = mini.execute_approved_plan_graph(
            root_contract, {}, repo_snapshot={"files": []},
            fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=leaf,
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(calls, ["EXEC-001", "EXEC-002"])
        self.assertEqual(
            [item["execution_contract_id"] for item in result["contract_results"]],
            ["EXEC-001", "EXEC-002"],
        )

        mini.reset_run("recursive")
        mini.RUN.update({
            "project_mode": mini.EXISTING_PROJECT,
            "impact_planning_required": True,
            "source_contract": root_contract,
            "approved_change_plan": self.plan,
            "plan_approval": dict(self.approval, approval_status="PENDING"),
            "repository_evidence": self.evidence,
            "canonical_surface_registry": self.registry,
        })
        blocked = mini.compile_approved_plan_execution_contracts(
            contract=root_contract, plan=self.plan,
            approval=mini.RUN["plan_approval"],
        )
        self.assertEqual(blocked["status"], "blocked")
        self.assertEqual(blocked["terminal_state"], execution.PLAN_APPROVAL_REQUIRED)
        self.assertFalse(mini.RUN.get("execution_contracts"))


if __name__ == "__main__":
    unittest.main()
