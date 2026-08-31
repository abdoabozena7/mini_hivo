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

    def mission_task(self, contract):
        return mini.make_task(
            contract["execution_contract_id"], contract["goal"], 1, "ROOT",
            contract["done_when"], contract["allowed_mutation_paths"],
            execution_contract_id=contract["execution_contract_id"],
            execution_contract=contract,
        )

    def compile_advice(self, contract, advice, dependency_summaries=None):
        return mini.compile_worker_mission(
            self.mission_task(contract), {}, repo_snapshot={"files": []},
            execution_contract=contract,
            dependency_summaries=dependency_summaries,
            structured_call=lambda _prompt, _validator, _label, _schema: advice,
        )

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

    def test_contract_hydrated_mission_uses_compact_advice_and_ignores_legacy_authority(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        prompts = []
        schemas = []
        raw = {
            "goal_anchor": "Extend InputManager Escape handling using the existing pause interface.",
            "mutation_targets": ["src/input.js", "src/game.js"],
            "interfaces_to_reuse": ["InputManager.isPressed", "GameState.togglePause"],
            "implementation_plan": [
                "Inspect GameState.togglePause in src/game.js and reuse it.",
                "Modify src/input.js.",
            ],
            "verification_plan": ["Verify Escape behavior without changing storage."],
            # These are intentionally absent from the semantic response.
        }

        def structured(prompt, validator, _label, schema):
            prompts.append(prompt)
            schemas.append((validator, schema))
            return raw

        mission = mini.compile_worker_mission(
            self.mission_task(contract),
            {"full_project_brain": "must not enter the contract handoff"},
            repo_snapshot={"files": []}, execution_contract=contract,
            structured_call=structured,
        )
        self.assertEqual(len(prompts), 1)
        self.assertEqual(schemas[0][1]["required"], [])
        self.assertNotIn("targets", schemas[0][1]["properties"])
        self.assertNotIn("requirements", schemas[0][1]["properties"])
        self.assertTrue(schemas[0][0](raw))
        self.assertIn("execution scope is already fixed", prompts[0].casefold())
        self.assertIn("do not propose new mutation targets", prompts[0].casefold())
        self.assertNotIn("approved_change_nodes", prompts[0])
        self.assertNotIn("full_project_brain", prompts[0])
        self.assertEqual(mission["allowed_mutation_paths"], ["src/input.js"])
        self.assertEqual(mission["targets"], ["src/input.js"])
        self.assertEqual(mission["allowed_inspection_paths"], contract["allowed_inspection_paths"])
        self.assertEqual(mission["requirements"], contract["requirements"])
        self.assertEqual(mission["interfaces_to_reuse"], contract["interfaces_to_reuse"])
        self.assertEqual(mission["preservation"], contract["local_preservation_constraints"])
        self.assertEqual(mission["prohibitions"], contract["structured_prohibitions"])
        self.assertEqual(mission["do_not_touch"], contract["global_do_not_touch"])
        self.assertEqual(mission["approved_plan_hash"], contract["plan_hash"])
        self.assertEqual(mission["execution_contract_hash"], contract["contract_hash"])
        self.assertTrue(execution.validate_hydrated_worker_mission(mission, contract, [])["valid"])
        tampered = copy.deepcopy(mission)
        tampered["allowed_mutation_paths"] = ["src/game.js"]
        self.assertFalse(execution.validate_hydrated_worker_mission(tampered, contract, [])["valid"])
        tampered = copy.deepcopy(mission)
        tampered["mutation_targets"] = ["src/game.js"]
        self.assertFalse(execution.validate_hydrated_worker_mission(tampered, contract, [])["valid"])
        encoded = json.dumps(mission, ensure_ascii=False)
        self.assertNotIn("mutation_targets", encoded)
        self.assertIn("GameState.togglePause", encoded)
        run_files = list((mini.WORKSPACE / mini.RUNS_DIR).glob("*.jsonl"))
        run_log = "\n".join(path.read_text(encoding="utf-8") for path in run_files)
        self.assertIn("raw_mission_compiler_output", run_log)
        self.assertIn("rejected_non_authoritative_fields", run_log)
        self.assertIn("hydrated_worker_mission", run_log)
        self.assertGreaterEqual(mini.RUN["mission_advice_received"], 1)
        self.assertGreaterEqual(mini.RUN["mission_advice_validated"], 1)
        self.assertGreaterEqual(mini.RUN["mission_non_authoritative_fields_rejected"], 1)
        self.assertGreaterEqual(mini.RUN["hydrated_worker_missions_created"], 1)

    def test_semantic_conflict_blocks_but_safe_game_inspection_is_valid(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        with self.assertRaises(mini.MissionCompilationError) as raised:
            self.compile_advice(contract, {
                "objective": "Modify src/game.js and add a new paused state owned by InputManager.",
            })
        self.assertIn(execution.MISSION_CONTRACT_VIOLATION, str(raised.exception))
        self.assertGreaterEqual(mini.RUN["mission_semantic_conflicts"], 1)
        self.assertGreaterEqual(mini.RUN["mission_advice_rejected"], 1)
        self.assertEqual(mini.RUN["hydrated_worker_missions_created"], 0)

        safe = self.compile_advice(contract, {
            "objective": "Extend InputManager Escape handling.",
            "implementation_steps": [
                "Inspect GameState.togglePause in src/game.js and reuse the existing interface.",
                "Modify src/input.js.",
            ],
            "interface_usage": ["GameState.togglePause", "InventedPauseInterface"],
        })
        self.assertTrue(execution.validate_hydrated_worker_mission(safe, contract, [])["valid"])
        self.assertEqual(safe["allowed_mutation_paths"], ["src/input.js"])
        self.assertIn("src/game.js", safe["allowed_inspection_paths"])
        self.assertEqual(safe["implementation_advice"]["interface_usage"], ["GameState.togglePause"])

        verify_only = copy.deepcopy(contract)
        verify_only["responsibility_type"] = execution.VERIFY_ONLY
        wrong_responsibility = execution.sanitize_mission_advice({
            "objective": "Modify src/input.js during verification.",
        }, verify_only)
        self.assertFalse(wrong_responsibility["valid"])
        self.assertTrue(wrong_responsibility["semantic_conflicts"])

    def test_code_location_classifier_requires_evidence_for_slash_compounds(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        for value in (
            "pause/resume", "halt/resume", "start/stop", "read/write",
            "input/output", "WASD/arrow", "client/server", "request/response",
            "on/off", "loop/update", "foo/bar",
        ):
            with self.subTest(value=value):
                reference = execution.classify_code_location_reference(value, contract)
                self.assertEqual(reference["classification"], "AMBIGUOUS_TEXT")
                self.assertEqual(reference["confidence_basis"], "BARE_SLASH_COMPOUND")

    def test_code_location_classifier_recognizes_generic_path_evidence(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        expected = {
            "src/game.js": "CANONICAL_PATH",
            "tests/input.test.js": "FILE_EXTENSION",
            "./src/input.js": "CANONICAL_PATH",
            "../config.json": "EXPLICIT_RELATIVE_PATH",
            "foo/bar.py": "FILE_EXTENSION",
            r"C:\project\file.py": "WINDOWS_PATH",
            "/home/user/file.ts": "ABSOLUTE_PATH",
            "src/generated": "KNOWN_REPOSITORY_ROOT",
            "services/pause_handler.py": "FILE_EXTENSION",
        }
        for value, basis in expected.items():
            with self.subTest(value=value):
                reference = execution.classify_code_location_reference(value, contract)
                self.assertEqual(reference["classification"], "CODE_PATH")
                self.assertEqual(reference["confidence_basis"], basis)

    def test_semantic_path_intent_is_local_and_distinguishes_safe_reuse(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]

        def intents(text):
            return {
                item["path"]: item["intent"]
                for item in execution._advice_path_references(text, contract)
            }

        self.assertEqual(
            intents("Read src/game.js to confirm the signature and effect of GameState.togglePause()."),
            {"src/game.js": "INSPECTION"},
        )
        self.assertEqual(
            intents("On Escape key press, call the existing GameState.togglePause() method (src/game.js)."),
            {"src/game.js": "REUSE"},
        )
        self.assertEqual(
            intents("Modify InputManager (src/input.js) to listen for Escape."),
            {"src/input.js": "MUTATION"},
        )
        self.assertEqual(
            intents("Modify src/input.js after inspecting src/game.js."),
            {"src/input.js": "MUTATION", "src/game.js": "INSPECTION"},
        )
        self.assertEqual(
            intents("Read src/game.js and then update src/input.js."),
            {"src/game.js": "INSPECTION", "src/input.js": "MUTATION"},
        )
        self.assertEqual(
            intents("Confirm src/game.js remains the verified implementation."),
            {"src/game.js": "INSPECTION"},
        )
        self.assertEqual(
            intents("add verification that reads src/game.js"),
            {"src/game.js": "INSPECTION"},
        )

        for text in ("Do not modify src/game.js.", "Never write src/storage.js."):
            with self.subTest(text=text):
                checked = execution.sanitize_mission_advice({"objective": text}, contract)
                self.assertTrue(checked["valid"], checked)
                self.assertFalse(checked["semantic_conflicts"], checked)

        later_allowed = execution.sanitize_mission_advice(
            {"objective": "Do not modify src/game.js. Modify src/input.js."}, contract,
        )
        self.assertTrue(later_allowed["valid"], later_allowed)
        later_dnt = execution.sanitize_mission_advice(
            {"objective": "Do not modify src/game.js. Modify src/storage.js."}, contract,
        )
        self.assertFalse(later_dnt["valid"], later_dnt)
        self.assertTrue(later_dnt["semantic_conflicts"], later_dnt)

    def test_exact_live_advice_is_accepted_and_hydrated_deterministically(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        raw = {
            "implementation_notes": [
                "Do not introduce new state variables for pause status; rely entirely on the state managed by GameState or the existing input flow.",
                "The pause logic must integrate seamlessly with the existing game loop/update cycle to halt/resume correctly.",
                "The primary focus is wiring the key event to the existing state toggle function.",
            ],
            "implementation_steps": [
                "Modify InputManager (src/input.js) to listen for the Escape key press.",
                "On Escape key press, call the existing GameState.togglePause() method (src/game.js).",
                "Ensure that the pause state correctly halts game logic updates and input processing when active, and resumes them when unpaused.",
                "Verify that WASD/arrow controls and best-score persistence remain unaffected by this addition.",
            ],
            "inspection_order": [
                "Read src/input.js to understand current input event handling.",
                "Read src/game.js to confirm the signature and effect of GameState.togglePause().",
                "Review existing test files to identify necessary additions for Escape key testing.",
            ],
            "interface_usage": [
                "Use the existing input event listener mechanism within InputManager.",
                "Call GameState.togglePause() to manage the game's pause state.",
                "Rely on the existing GameState object for pause status checks.",
            ],
            "objective": "Implement Escape-key handling within InputManager to trigger the game's pause/resume functionality, strictly reusing existing state management and input handling mechanisms.",
            "verification_notes": [
                "Thoroughly test pausing and unpausing via Escape key while ensuring WASD movement and score persistence are maintained.",
                "Confirm that the input system correctly ignores movement inputs when the game is paused.",
            ],
        }
        checked = execution.sanitize_mission_advice(raw, contract)
        self.assertTrue(checked["valid"], checked)
        self.assertFalse(checked["semantic_conflicts"], checked)
        self.assertGreaterEqual(checked["semantic_path_false_positive_avoided"], 4)
        by_text = {
            item["text"]: item for item in checked["semantic_path_candidates"]
        }
        for value in ("pause/resume", "halt/resume", "loop/update", "WASD/arrow"):
            self.assertEqual(by_text[value]["classification"], "AMBIGUOUS_TEXT")

        mission = execution.hydrate_worker_mission(contract, checked["advice"], [])
        self.assertTrue(execution.validate_hydrated_worker_mission(mission, contract, [])[
            "valid"
        ])
        self.assertEqual(mission["allowed_mutation_paths"], ["src/input.js"])
        self.assertEqual(mission["allowed_inspection_paths"], ["src/input.js", "src/game.js"])
        self.assertEqual(
            mission["interfaces_to_reuse"], ["InputManager.isPressed", "GameState.togglePause"],
        )
        self.assertNotIn("src/game.js", mission["targets"])
        self.assertNotIn("mutation_targets", mission)
        self.assertEqual(
            mission["implementation_advice"]["interface_usage"], ["GameState.togglePause"],
        )
        packet = mini.build_node_context(
            self.mission_task(contract), {}, None, {"files": []},
            worker_mission=mission, execution_contract=contract,
        )
        self.assertIn(mission["mission_id"], packet)
        self.assertIn("AUTHORITATIVE EXECUTION CONTRACT", packet)
        self.assertIn("IMPLEMENTATION ADVICE", packet)
        self.assertNotIn("mutation_targets", packet)

    def test_real_paths_and_contract_local_scope_still_conflict(self):
        _, compiled, _ = self.compiled()
        mutation = compiled["contracts"][0]
        for objective in (
            "Modify src/game.js to add a new pause state.",
            "Refactor src/game.js.",
            "Rewrite src/storage.js.",
            "Modify services/pause_handler.py.",
            "Create tests/pause.test.js.",
            "Write files into src/generated.",
            "Modify tests/input.test.js.",
        ):
            with self.subTest(objective=objective):
                checked = execution.sanitize_mission_advice({"objective": objective}, mutation)
                self.assertFalse(checked["valid"], checked)
                self.assertTrue(checked["semantic_conflicts"], checked)

    def test_duplicate_state_and_ownership_conflicts_are_path_independent(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        for objective in (
            "Add a new paused state inside InputManager.",
            "Move pause-state ownership from GameState to InputManager.",
        ):
            with self.subTest(objective=objective):
                checked = execution.sanitize_mission_advice({"objective": objective}, contract)
                self.assertFalse(checked["valid"], checked)
                self.assertTrue(checked["semantic_conflicts"], checked)

    def test_safe_interface_and_test_review_advice_remain_non_mutating(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        for objective in (
            "Inspect src/game.js.",
            "Use GameState.togglePause() from src/game.js.",
            "Review existing test files to identify necessary additions.",
        ):
            with self.subTest(objective=objective):
                checked = execution.sanitize_mission_advice({"objective": objective}, contract)
                self.assertTrue(checked["valid"], checked)
                self.assertFalse(checked["semantic_conflicts"], checked)

    def test_hashes_dependencies_test_contract_and_child_scope_are_contract_bound(self):
        _, compiled, _ = self.compiled()
        mutation, test_contract = compiled["contracts"]
        dependency = [{
            "task_id": mutation["execution_contract_id"], "status": "done",
            "summary": "verified input change", "changed_files": ["src/input.js"],
        }]
        test_mission = self.compile_advice(test_contract, {
            "objective": "Update the existing focused input test.",
            "implementation_steps": ["Modify tests/input.test.js."],
            "test_file": "tests/pause.test.js",
            "mutation_targets": ["tests/input.test.js", "tests/pause.test.js"],
            "requirements": ["REQ-999"], "plan_hash": "bogus", "execution_contract_hash": "bogus",
        }, dependency_summaries=dependency)
        self.assertEqual(test_mission["allowed_mutation_paths"], ["tests/input.test.js"])
        self.assertNotIn("tests/pause.test.js", test_mission["allowed_mutation_paths"])
        self.assertEqual(test_mission["dependency_ids"], ["EXEC-001"])
        self.assertEqual(test_mission["dependencies"][0]["task_id"], "EXEC-001")
        self.assertTrue(execution.validate_hydrated_worker_mission(test_mission, test_contract, dependency)["valid"])
        self.assertGreaterEqual(mini.RUN["mission_non_authoritative_fields_rejected"], 3)

        with self.assertRaises(mini.MissionCompilationError):
            self.compile_advice(test_contract, {
                "objective": "Create tests/pause.test.js for the new behavior.",
            }, dependency_summaries=dependency)

        advice_a = {"objective": "Extend input handling.", "implementation_steps": ["Modify src/input.js."]}
        advice_b = {"objective": "Extend input handling with Escape.", "implementation_steps": ["Modify src/input.js."]}
        mission_a = self.compile_advice(mutation, advice_a)
        mission_b = self.compile_advice(mutation, advice_b)
        self.assertNotEqual(mission_a["mission_hash"], mission_b["mission_hash"])
        changed_contract = copy.deepcopy(mutation)
        changed_contract["goal"] += " with a changed approved responsibility"
        changed_contract["contract_hash"] = execution.deterministic_hash(
            execution._without(changed_contract, "contract_hash"),
        )
        changed_mission = execution.hydrate_worker_mission(changed_contract, advice_a, [])
        self.assertNotEqual(mission_a["mission_hash"], changed_mission["mission_hash"])
        child = execution.child_contract(
            mutation, {"child_id": "CHILD-INPUT", "done_when": mutation["done_when"][:1],
                       "scope_hint": ["src/input.js"]},
        )
        child_mission = execution.hydrate_worker_mission(
            child, {"objective": "Modify src/input.js.", "implementation_steps": ["Update the input owner."]}, [],
        )
        self.assertTrue(execution.validate_hydrated_worker_mission(child_mission, child, [])["valid"])
        self.assertEqual(child_mission["allowed_mutation_paths"], ["src/input.js"])
        self.assertNotIn("src/game.js", child_mission["allowed_mutation_paths"])

    def test_hydrated_worker_context_separates_authority_from_advice(self):
        _, compiled, _ = self.compiled()
        contract = compiled["contracts"][0]
        mission = self.compile_advice(contract, {
            "objective": "Extend InputManager Escape handling.",
            "implementation_steps": ["Modify src/input.js."],
            "inspection_order": ["Read src/game.js only to reuse GameState.togglePause."],
        })
        packet = mini.build_node_context(
            self.mission_task(contract), {}, None, {"files": []},
            brain_projection={"full_project_brain": "must not appear"},
            worker_mission=mission, execution_contract=contract,
        )
        self.assertIn("AUTHORITATIVE EXECUTION CONTRACT", packet)
        self.assertIn("IMPLEMENTATION ADVICE", packet)
        self.assertIn(mission["mission_id"], packet)
        self.assertIn("Extend InputManager Escape handling", packet)
        self.assertNotIn("mutation_targets", packet)
        self.assertNotIn("full_project_brain", packet)
        self.assertIn("src/game.js", packet)
        self.assertIn("src/input.js", packet)

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
        for path in ("src/storage.js", "tests/pause.test.js"):
            with self.subTest(path=path):
                mutation_result = mini.run_tool(
                    "edit_file", {"path": path, "old": "false", "new": "true"}, role="Builder",
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
