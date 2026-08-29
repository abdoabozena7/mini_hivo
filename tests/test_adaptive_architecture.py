import json
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from contextlib import redirect_stdout

import mini


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
                return {"status": "too_broad", "failure_type": "TASK_TOO_BROAD", "summary": "step budget", "memory": memory}
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
                        "failure_evidence": [{"name": "tests", "status": "FAIL"}], "memory": memory}
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
                patch.object(mini, "_maybe_search_alternate_strategy", return_value=None):
            result = mini.solve_task(
                task, mini.MAX_DEPTH, contract, {}, {}, leaf_executor=Mock(return_value=leaf),
            )

        self.assertEqual(result["status"], "failed")
        decompose.assert_not_called()
        self.assertEqual(mini.RUN["re_splits"], 0)
        self.assertEqual(mini.RUN["max_depth_failures"], 1)
        diagnosis = task["failure_diagnosis"]
        self.assertTrue(diagnosis["at_max_depth"])
        self.assertTrue(diagnosis["automatic_resplit_blocked"])
        self.assertEqual(diagnosis["category"], "model_capability_floor")
        self.assertEqual(diagnosis["next_action"], "declare_limit")
        self.assertEqual(mini.build_node_diagnosis()[0]["why_failed"], "model_capability_floor")

    def test_terminal_too_broad_backtracks_to_a_materially_different_decomposition(self):
        contract = self.contract(["state", "transition", "verification"])
        parent = mini.make_task(
            "3.1.3.1.1", "Implement the combat behavior", 5, "3.1.3.1",
            ["combat behavior is verified"], ["src/game.js"],
        )
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
                        "summary": "terminal branch still exceeds capacity", "memory": memory}
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
                    "summary": "terminal branch still exceeds capacity", "memory": memory}

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
