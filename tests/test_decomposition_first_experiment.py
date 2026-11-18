import copy
import unittest

import mini
from hivo import decomposition_first as early
from tests.test_impact_planning import ImpactPlanningTests


class DecompositionFirstExperimentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ImpactPlanningTests("test_plan_identity_is_deterministic_and_content_changes_stale_approval")
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def split(*_args):
        return {"children": [
            {"responsibility": "Connect Escape input to the existing pause state",
             "requirement_ids": ["REQ-001", "REQ-002"]},
            {"responsibility": "Preserve controls and score while covering the change with tests",
             "requirement_ids": ["REQ-003", "REQ-004"]},
        ]}

    def planner(self, *_args):
        count = mini.RUN.get("impact_planner_calls", 0)
        candidate = copy.deepcopy(self.fixture.candidate_map())
        candidate["impacts"] = candidate["impacts"][:2] if count == 1 else candidate["impacts"][2:]
        allowed = {"REQ-001", "REQ-002"} if count == 1 else {"REQ-003", "REQ-004"}
        for index, impact in enumerate(candidate["impacts"], 1):
            impact["impact_id"] = f"IMP-{index:03d}"
            impact["requirement_ids"] = [value for value in impact["requirement_ids"] if value in allowed]
        return candidate

    def test_split_rejects_file_selection_and_omitted_requirements(self):
        requirements = self.fixture.requirements
        with self.assertRaises(early.EarlySplitError):
            early.validate_split({"children": [
                {"responsibility": "Edit src/game.js", "requirement_ids": ["REQ-001"]},
                {"responsibility": "Check controls", "requirement_ids": ["REQ-002"]},
            ]}, requirements)
        with self.assertRaises(early.EarlySplitError):
            early.validate_split({"children": [
                {"responsibility": "Pause behavior", "requirement_ids": ["REQ-001"]},
                {"responsibility": "Controls", "requirement_ids": ["REQ-002"]},
            ]}, requirements)

    def test_reuse_on_mutated_surface_is_attached_without_losing_obligations(self):
        impact_map = {"impacts": [
            {"impact_id": "IMP-001", "surface_id": "SURF-001",
             "disposition": "MUST_CHANGE", "requirement_ids": ["REQ-001"]},
            {"impact_id": "IMP-002", "surface_id": "SURF-001",
             "disposition": "INTERFACE_REUSE", "requirement_ids": ["REQ-002"],
             "preserve": ["existing interface"]},
        ]}
        compact, bindings = early.compact_attached_reuse(
            impact_map, [{"IMP-001": "IMP-001", "IMP-002": "IMP-002"}],
        )
        self.assertEqual(len(compact["impacts"]), 1)
        self.assertEqual(compact["impacts"][0]["requirement_ids"], ["REQ-001", "REQ-002"])
        self.assertEqual(compact["impacts"][0]["preserve"], ["existing interface"])
        self.assertEqual(bindings[0]["IMP-002"], "IMP-001")

    def test_local_plans_reach_same_approval_boundary(self):
        mini.RUN["planning_route"] = "decomposition_first_recursive"
        result = mini.prepare_decomposition_first_stage3_context(
            self.fixture.understanding(), self.fixture.contract,
            interactive=False, terminal_available=False,
            planner_structured_call=self.planner,
            challenger_structured_call=lambda *_args: {"challenges": []},
            early_split_structured_call=self.split,
        )
        self.assertEqual(result["status"], "plan_approval_required", result)
        self.assertTrue(result["plan_gate"]["valid"])
        self.assertTrue(result["read_only"])
        events = [item["kind"] for item in mini.RUN["experiment_events"]]
        self.assertEqual(events.count("CHILD_PLAN_READY"), 2)
        self.assertLess(events.index("EARLY_SPLIT_READY"), events.index("CHILD_PLAN_STARTED"))
        self.assertLess(events.index("SCOPE_AGGREGATION_READY"), events.index("APPROVAL_REQUIRED"))
        self.assertNotIn("first_blocker", mini.RUN)

    def test_approved_local_plan_compiles_existing_contract_graph(self):
        mini.RUN["planning_route"] = "decomposition_first_recursive"
        result = mini.prepare_decomposition_first_stage3_context(
            self.fixture.understanding(), self.fixture.contract,
            interactive=True, terminal_available=True,
            planner_structured_call=self.planner,
            challenger_structured_call=lambda *_args: {"challenges": []},
            early_split_structured_call=self.split,
            approval_selector=lambda *_args, **_kwargs: 0,
        )
        self.assertEqual(result["status"], "ready", result)
        self.assertTrue(result["execution_contracts"])
        self.assertEqual(result["plan"]["plan_hash"], result["approval"]["plan_hash"])
        self.assertTrue(result["read_only"])
        graph_result, _ = mini.execute_approved_plan_graph(
            self.fixture.contract, {}, repo_snapshot={},
            fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=lambda _task, _contract, memory, *_args: {
                "status": "done", "summary": "verified", "memory": memory,
            },
        )
        self.assertEqual(graph_result["status"], "done", graph_result)
        events = [item["kind"] for item in mini.RUN["experiment_events"]]
        self.assertIn("CHILD_VERIFIED", events)
        self.assertIn("EARLY_CHILD_VERIFIED", events)
        self.assertIn("ROOT_VERIFIED", events)

    def test_paired_routes_keep_approval_before_injected_leaf(self):
        outcomes = {}
        for route in ("current_recursive", "decomposition_first_recursive"):
            calls = []
            result, _ = mini.run_recursive_request(
                self.fixture.contract["goal"], {},
                contract_override=self.fixture.contract,
                repo_snapshot={}, understanding_override=self.fixture.understanding(),
                planning_route=route,
                early_split_structured_call=self.split,
                impact_planner_structured_call=(
                    self.planner if route == "decomposition_first_recursive"
                    else lambda *_args: self.fixture.candidate_map()
                ),
                impact_challenger_structured_call=lambda *_args: {"challenges": []},
                plan_approval_selector=lambda *_args, **_kwargs: 0,
                terminal_available=True,
                fit_decider=lambda *_args: {"decision": "execute"},
                leaf_executor=lambda task, _contract, memory, _repo, _parent, _deps: (
                    calls.append(task.get("approved_plan_hash"))
                    or {"status": "done", "summary": "verified", "memory": memory}
                ),
                reset=True, finish=False,
            )
            self.assertEqual(result["status"], "done", result)
            self.assertEqual(calls, [mini.RUN["approved_change_plan"]["plan_hash"]])
            outcomes[route] = [event["kind"] for event in mini.RUN["experiment_events"]]
        self.assertLess(outcomes["current_recursive"].index("APPROVED"),
                        len(outcomes["current_recursive"]))
        self.assertLess(outcomes["decomposition_first_recursive"].index("EARLY_SPLIT_READY"),
                        outcomes["decomposition_first_recursive"].index("APPROVED"))


if __name__ == "__main__":
    unittest.main()
