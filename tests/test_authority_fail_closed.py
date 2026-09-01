import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import execution_contracts as execution


class AuthorityFailClosedTests(unittest.TestCase):
    """Deterministic V19.4.1 routing checks; never contacts Gemma."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")

    def tearDown(self):
        mini.rollback_transaction()
        mini.ACTIVE_TOOL_CONTRACT = None
        self.temp.cleanup()

    @staticmethod
    def contract():
        return {
            "status": "ready",
            "goal": "Add the approved behavior while preserving current ownership.",
            "original_goal": "Add the approved behavior while preserving current ownership.",
            "source_contract": {
                "root_goal": "Add the approved behavior while preserving current ownership.",
            },
            "requirements": ["the approved behavior is implemented"],
            "constraints": ["preserve current ownership"],
            "success_criteria": ["the focused verification passes"],
        }

    def seed_stale_authority(self, *, approval_source="STAGE4B_SYNTHETIC_FIXTURE"):
        contract = self.contract()
        plan = {
            "plan_id": "PLAN-STALE-ROUTING-001",
            "plan_hash": "stored-plan-hash",
            "task_goal": contract["goal"],
            "approved_change_nodes": [],
            "synthetic_only": approval_source != "USER_CONFIRMED",
        }
        approval = {
            "approval_status": "APPROVED",
            "approval_source": approval_source,
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
        }
        mini.RUN.update({
            "project_mode": mini.EXISTING_PROJECT,
            "impact_planning_required": True,
            "source_contract": contract,
            "approved_change_plan": plan,
            "plan_approval": approval,
        })
        return contract, plan, approval

    def run_stale_request(self, approval_source="STAGE4B_SYNTHETIC_FIXTURE"):
        contract, plan, approval = self.seed_stale_authority(
            approval_source=approval_source,
        )
        fit_calls = []
        decompose_calls = []
        leaf_calls = []

        def fit(*_args):
            fit_calls.append(True)
            return {"decision": "split"}

        def decompose(*_args, **_kwargs):
            decompose_calls.append(True)
            return []

        def leaf(*_args, **_kwargs):
            leaf_calls.append(True)
            return {"status": "done", "summary": "unexpected Worker", "memory": {}}

        understanding = {
            "status": "ready",
            "project_mode": mini.EXISTING_PROJECT,
            "contract": contract,
            "reconnaissance": {"evidence": [], "read_only": True},
        }
        impact = {
            "status": "ready",
            "project_mode": mini.EXISTING_PROJECT,
            "contract": contract,
            "plan": plan,
            "approval": approval,
        }
        with patch.object(
            mini, "structured_model_call",
            side_effect=AssertionError("generic model call after terminal authority failure"),
        ), patch.object(mini, "decompose_task", side_effect=decompose):
            result, _ = mini.run_recursive_request(
                contract["goal"], {}, contract_override=contract,
                repo_snapshot={"files": []}, understanding_override=understanding,
                impact_planning_override=impact, fit_decider=fit,
                leaf_executor=leaf, reset=False, finish=False,
            )
        return result, fit_calls, decompose_calls, leaf_calls

    def test_stale_synthetic_authority_is_terminal_before_generic_root(self):
        result, fit_calls, decompose_calls, leaf_calls = self.run_stale_request()
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["execution_mode"], "AUTHORITY_BOUND")
        self.assertEqual(result["authority_status"], "STALE")
        self.assertFalse(result["fallback_allowed"])
        self.assertEqual(fit_calls, [])
        self.assertEqual(decompose_calls, [])
        self.assertEqual(leaf_calls, [])
        self.assertEqual(mini.RUN["authority_fail_closed_blocks"], 1)
        self.assertNotIn("TASK_FIT", mini.RUN["control_flow"])
        self.assertNotIn("DECOMPOSITION", mini.RUN["control_flow"])

    def test_stale_user_confirmed_authority_has_the_same_terminal_route(self):
        result, fit_calls, decompose_calls, leaf_calls = self.run_stale_request(
            approval_source="USER_CONFIRMED",
        )
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(result["authority_status"], "STALE")
        self.assertEqual(fit_calls, [])
        self.assertEqual(decompose_calls, [])
        self.assertEqual(leaf_calls, [])

    def test_stale_authority_blocks_direct_task_fit_and_decomposition_helpers(self):
        contract, _plan, _approval = self.seed_stale_authority()
        task = mini.make_task("ROOT", contract["goal"], 0, None, ["done"], [])
        with patch.object(
            mini, "structured_model_call",
            side_effect=AssertionError("model call after stale authority"),
        ):
            decision = mini.decide_task_fit(task, 0, contract, {"files": []})
            children = mini.decompose_task(task, contract, {"files": []})
        self.assertEqual(decision["decision"], "blocked")
        self.assertEqual(decision["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(children, [])

    def test_stale_authority_blocks_direct_solve_before_fit_leaf_or_worker(self):
        contract, _plan, _approval = self.seed_stale_authority()
        task = mini.make_task("ROOT", contract["goal"], 0, None, ["done"], [])
        fit_calls = []
        leaf_calls = []
        with patch.object(
            mini, "structured_model_call",
            side_effect=AssertionError("model call after stale authority"),
        ):
            result = mini.solve_task(
                task, 0, contract, {}, {"files": []},
                fit_decider=lambda *_args: fit_calls.append(True) or {"decision": "execute"},
                leaf_executor=lambda *_args: leaf_calls.append(True) or {
                    "status": "done", "summary": "unexpected", "memory": {},
                },
            )
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(fit_calls, [])
        self.assertEqual(leaf_calls, [])
        self.assertEqual(task["status"], "blocked")

    def test_stale_authority_does_not_create_contracts_missions_projection_or_worker(self):
        contract, _plan, _approval = self.seed_stale_authority()
        with patch.object(mini, "compile_worker_mission") as mission, \
                patch.object(mini, "build_worker_context_projection") as projection, \
                patch.object(mini, "execute_agent_task") as worker:
            result, *_ = self.run_stale_request()
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        mission.assert_not_called()
        projection.assert_not_called()
        worker.assert_not_called()
        self.assertEqual(mini.RUN.get("execution_contracts"), None)
        self.assertEqual(mini.RUN.get("hydrated_worker_missions_created", 0), 0)
        self.assertEqual(mini.RUN.get("worker_context_projections_created", 0), 0)

    def test_stale_authority_does_not_activate_subject_mutation(self):
        contract, _plan, _approval = self.seed_stale_authority()
        writes = []

        def write(*_args, **_kwargs):
            writes.append(True)
            return {"status": "done", "memory": {}}

        with patch.object(mini, "run_tool", side_effect=write):
            result, *_ = self.run_stale_request()
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(writes, [])

    def test_stale_authority_status_is_fail_closed_for_reused_run(self):
        contract, plan, approval = self.seed_stale_authority()
        mini.RUN["execution_contract_status"] = mini.APPROVED_PLAN_STALE
        mini.RUN["orchestration_failure"] = mini.APPROVED_PLAN_STALE
        result, fit_calls, decompose_calls, leaf_calls = self.run_stale_request()
        self.assertEqual(result["terminal_reason"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(result["fallback_allowed"], False)
        self.assertEqual(fit_calls, [])
        self.assertEqual(decompose_calls, [])
        self.assertEqual(leaf_calls, [])
        self.assertEqual(mini.RUN["approved_change_plan"], plan)
        self.assertEqual(mini.RUN["plan_approval"], approval)
        self.assertEqual(mini.RUN["source_contract"], contract)

    def test_stale_authority_in_auto_route_cannot_fall_into_generic_root(self):
        contract = self.contract()
        plan = {
            "plan_id": "PLAN-STALE-AUTO-001",
            "plan_hash": "stored-plan-hash",
            "task_goal": contract["goal"],
            "approved_change_nodes": [],
        }
        approval = {
            "approval_status": "APPROVED",
            "approval_source": "USER_CONFIRMED",
            "plan_id": plan["plan_id"],
            "plan_hash": plan["plan_hash"],
        }

        def stage3_ready(_understanding, _contract, **_kwargs):
            mini.RUN.update({
                "project_mode": mini.EXISTING_PROJECT,
                "impact_planning_required": True,
                "approved_change_plan": plan,
                "plan_approval": approval,
                "source_contract": contract,
            })
            return {
                "status": "ready", "project_mode": mini.EXISTING_PROJECT,
                "contract": contract, "plan": plan, "approval": approval,
            }

        with patch.object(mini, "get_goal_contract", return_value=contract), \
                patch.object(mini, "inspect_repository", return_value={"files": []}), \
                patch.object(
                    mini, "prepare_stage2_context",
                    return_value={
                        "status": "ready", "project_mode": mini.EXISTING_PROJECT,
                        "contract": contract,
                        "reconnaissance": {"evidence": [], "read_only": True},
                    },
                ), patch.object(mini, "prepare_stage3_context", side_effect=stage3_ready), \
                patch.object(
                    mini, "decide_task_fit",
                    side_effect=AssertionError("generic auto Task-Fit after stale authority"),
                ), patch.object(
                    mini, "structured_model_call",
                    side_effect=AssertionError("model call after stale authority"),
                ):
            result, _ = mini.run_auto_request(contract["goal"], {}, interactive=False)
        self.assertEqual(result["terminal_state"], mini.APPROVED_PLAN_STALE)
        self.assertEqual(result["execution_mode"], "AUTHORITY_BOUND")
        self.assertNotIn("TASK_FIT", mini.RUN["control_flow"])
        self.assertNotIn("DECOMPOSITION", mini.RUN["control_flow"])

    def test_valid_broad_contract_reaches_structural_fit_and_existing_decomposer_route(self):
        from tests.test_structural_decomposition import StructuralDecompositionTests

        contract = StructuralDecompositionTests.stage4b_parent()
        mini.reset_run("recursive")
        mini.RUN.update({
            "project_mode": mini.NEW_PROJECT,
            "impact_planning_required": False,
            "tasks_created": 1,
        })
        task = mini.make_task(
            "ROOT", contract["goal"], 0, None, contract["done_when"],
            contract["allowed_mutation_paths"],
            execution_contract_id=contract["execution_contract_id"],
            execution_contract=contract,
        )
        children = [{"id": "1"}, {"id": "2"}]
        with patch.object(
            mini, "structured_model_call",
            side_effect=AssertionError("Structural Fit must remain zero-model"),
        ), patch.object(mini, "decompose_task", return_value=children) as decomposer, \
                patch.object(
                    mini, "_execute_children",
                    return_value={"status": "done", "summary": "mocked children", "memory": {}},
                ):
            result = mini.solve_task(
                task, 0, contract, {}, {"files": []},
                fit_decider=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("Structural Fit should decide the broad route"),
                ),
                leaf_executor=lambda *_args: (_ for _ in ()).throw(
                    AssertionError("broad parent must not execute directly"),
                ),
            )
        self.assertEqual(result["status"], "done")
        decomposer.assert_called_once()
        self.assertEqual(mini.RUN["structural_fit_analyzer_calls"], 1)
        self.assertEqual(mini.RUN["structural_fit_decomposition_required"], 1)

    def test_unbound_generic_legacy_flow_remains_available(self):
        contract = {
            "status": "ready", "goal": "unbound legacy task",
            "requirements": ["legacy behavior"], "success_criteria": ["verified"],
        }
        task = mini.make_task("ROOT", contract["goal"], 0, None, ["verified"], [])
        fit_calls = []
        result = mini.solve_task(
            task, 0, contract, {}, {"files": []},
            fit_decider=lambda *_args: fit_calls.append(True) or {"decision": "execute"},
            leaf_executor=lambda _task, _contract, memory, *_args: {
                "status": "done", "summary": "legacy verified", "memory": memory,
            },
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(fit_calls), 1)

    def test_new_project_recursive_flow_remains_available(self):
        contract = {
            "status": "ready", "goal": "create a new project",
            "requirements": ["new behavior"], "success_criteria": ["verified"],
        }
        understanding = {
            "status": "ready", "project_mode": mini.NEW_PROJECT,
            "contract": contract, "reconnaissance": {"evidence": [], "read_only": True},
        }
        impact = {"status": "ready", "project_mode": mini.NEW_PROJECT, "contract": contract}
        result, _ = mini.run_recursive_request(
            contract["goal"], {}, contract_override=contract,
            repo_snapshot={"files": []}, understanding_override=understanding,
            impact_planning_override=impact,
            fit_decider=lambda *_args: {"decision": "execute"},
            leaf_executor=lambda _task, _contract, memory, *_args: {
                "status": "done", "summary": "new project verified", "memory": memory,
            },
            reset=True, finish=False,
        )
        self.assertEqual(result["status"], "done")
        self.assertEqual(mini.RUN.get("authority_fail_closed_blocks", 0), 0)

    def test_authority_detection_uses_state_not_task_wording(self):
        mini.reset_run("recursive")
        task = mini.make_task("ROOT", "stale sounding wording", 0, None, ["done"], [])
        self.assertFalse(mini._authority_bound_execution_attempt(task))
        self.assertIsNone(mini._authority_terminal_failure(task))
        mini.RUN["project_mode"] = mini.EXISTING_PROJECT
        mini.RUN["impact_planning_required"] = True
        mini.RUN["approved_change_plan"] = {"plan_id": "P", "plan_hash": "H"}
        mini.RUN["plan_approval"] = {"approval_status": "APPROVED", "plan_id": "P", "plan_hash": "H"}
        mini.RUN["execution_contract_status"] = mini.APPROVED_PLAN_STALE
        mini.RUN["orchestration_failure"] = mini.APPROVED_PLAN_STALE
        self.assertTrue(mini._authority_bound_execution_attempt(task))
        self.assertEqual(mini._authority_terminal_failure(task), mini.APPROVED_PLAN_STALE)

    def test_authority_failure_set_contains_existing_preexecution_statuses_only(self):
        self.assertIn(mini.PLAN_APPROVAL_REQUIRED, mini.AUTHORITY_VALIDATION_FAILURES)
        self.assertIn(mini.APPROVED_PLAN_STALE, mini.AUTHORITY_VALIDATION_FAILURES)
        self.assertIn(mini.EXECUTION_CONTRACT_BLOCKED, mini.AUTHORITY_VALIDATION_FAILURES)
        self.assertIn(mini.EXECUTION_GRAPH_INVALID, mini.AUTHORITY_VALIDATION_FAILURES)
        self.assertNotIn(mini.EXECUTION_DEPENDENCY_BLOCKED, mini.AUTHORITY_VALIDATION_FAILURES)


if __name__ == "__main__":
    unittest.main()
