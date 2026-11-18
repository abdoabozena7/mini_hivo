"""Controlled scope fixtures, production routing/gates, no model or browser."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo.verification import evaluate_web_snapshot, infer_web_profile


FIXTURE = json.loads((Path(__file__).parent / "fixtures/experiment20_scope.json").read_text(encoding="utf-8"))
ALL_GAME_CHECKS = {"keyboard_movement", "collection_updates_state", "collision_game_over",
                   "restart_resets_state", "score_persistence", "touch_control", "goal_win_state"}


class Experiment20ScopeTests(unittest.TestCase):
    def setUp(self):
        self.saved = {k: getattr(mini, k) for k in (
            "WORKSPACE", "RUN", "RUN_ID", "ACTIVE_TOOL_CONTRACT", "ACTIVE_TRANSACTION",
            "MEMORY_STORE", "ACTIVE_CONTRACT", "LAST_COMMITTED_TRANSACTION")}
        self.temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        mini.RUN["verification_classification_policy"] = "field_scoped"
        mini.RUN["source_contract"] = copy.deepcopy(FIXTURE["source_contract"])
        mini.ACTIVE_TRANSACTION = None
        mini.MEMORY_STORE = None
        (mini.WORKSPACE / "index.html").write_text("<title>Scope fixture</title><canvas></canvas>", encoding="utf-8")
        self.profiles = []

    def tearDown(self):
        mini.rollback_transaction()
        for k, v in self.saved.items():
            setattr(mini, k, v)
        self.temp.cleanup()

    def child(self, number=1):
        return copy.deepcopy(FIXTURE["children"][number - 1])

    def contract(self, task):
        value = {"goal": task["goal"], "requirements": task.get("done_when", []),
                 "success_criteria": task.get("done_when", []), "task_id": task["id"],
                 "constraints": FIXTURE["source_contract"]["constraints"]}
        prepare = getattr(mini, "_task_web_verification_contract", lambda t, c: c)
        return prepare(task, value)

    def browser(self, _path, _task_id, profile=None, evidence=None):
        self.profiles.append(profile)
        return evaluate_web_snapshot(self.snapshot, profile)

    def check(self, task, checks=(), bridge=False, tool=False):
        self.snapshot = {"title": "Scope fixture", "text": "Test page", "console_errors": [],
                         "page_errors": [], "network_errors": [],
                         "runtime_state": {"canvasCount": 1, "gameBridge": {"state": {}} if bridge else None},
                         "interaction_checks": [{"name": n, "passed": True} for n in checks],
                         "resolved_entrypoint": "index.html"}
        contract = self.contract(task)
        mini.ACTIVE_TOOL_CONTRACT = contract
        with patch.object(mini, "verify_browser_application", side_effect=self.browser):
            if tool:
                return json.loads(mini.run_tool("verify_web_app", {"path": "index.html"}, role="Builder"))
            return mini.optional_browser_check(task, contract)

    def test_foundation_controller_does_not_require_later_movement_collection(self):
        result = self.check(self.child())
        self.assertTrue(result["passed"], result.get("failures"))
        self.assertEqual(self.profiles[-1].required_interactions, ())
        self.assertTrue(self.profiles[-1].require_canvas)

    def test_production_constructor_foundation_activates_scope(self):
        seed = self.child()
        task = mini.make_task(seed["id"], seed["goal"], parent="ROOT",
                              done_when=seed["done_when"], scope_hint=seed["scope_hint"])
        self.assertNotIn("parent_id", task)
        self.assertTrue(self.check(task)["passed"])
        self.assertEqual(self.profiles[-1].required_interactions, ())

    def test_production_constructor_movement_keeps_only_assigned_behavior(self):
        seed = self.child(2)
        task = mini.make_task(seed["id"], seed["goal"], parent="ROOT",
                              done_when=seed["done_when"], scope_hint=seed["scope_hint"])
        self.assertTrue(self.check(task, ["keyboard_movement"], bridge=True)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"keyboard_movement"})

    def test_production_constructor_without_parent_cannot_narrow(self):
        seed = self.child()
        task = mini.make_task("standalone", seed["goal"], done_when=seed["done_when"])
        self.assertFalse(self.check(task)["passed"])

    def test_conflicting_parent_aliases_cannot_narrow(self):
        seed = self.child()
        task = mini.make_task(seed["id"], seed["goal"], parent="ROOT", done_when=seed["done_when"])
        task["parent_id"] = "OTHER"
        self.assertFalse(self.check(task)["passed"])

    def test_foundation_worker_tool_uses_same_scope(self):
        result = self.check(self.child(), tool=True)
        self.assertTrue(result["passed"], result.get("failures"))
        self.assertEqual(self.profiles[-1].required_interactions, ())

    def test_movement_child_requires_movement_not_product_name_collection(self):
        failed = self.check(self.child(2))
        self.assertFalse(failed["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"keyboard_movement"})
        self.assertTrue(self.check(self.child(2), ["keyboard_movement"], bridge=True)["passed"])

    def test_mechanics_child_requires_collection_and_collision(self):
        self.assertFalse(self.check(self.child(3), ["collection_updates_state"], bridge=True)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"collection_updates_state", "collision_game_over"})
        self.assertTrue(self.check(self.child(3), ["collection_updates_state", "collision_game_over"], bridge=True)["passed"])

    def test_flow_child_keeps_restart_and_persistence(self):
        self.assertFalse(self.check(self.child(4), ["restart_resets_state"], bridge=True)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"restart_resets_state", "score_persistence", "collision_game_over", "keyboard_movement"})

    def test_explicit_game_over_assignment_requires_terminal_check(self):
        task = self.child(4); task["done_when"] = ["Game Over freezes movement and scoring."]
        self.check(task, ["restart_resets_state", "score_persistence"], bridge=True)
        self.assertIn("collision_game_over", self.profiles[-1].required_interactions)

    def test_missing_or_unknown_assignment_does_not_opt_out(self):
        for conditions in ([], ["Everything is fine"]):
            task = self.child(); task["done_when"] = conditions
            self.assertFalse(self.check(task)["passed"])
            self.assertTrue(self.profiles[-1].require_game_bridge)

    def test_single_full_task_keeps_legacy_game_requirements(self):
        task = {"id": "ROOT", "goal": FIXTURE["source_contract"]["goal"], "scope_hint": ["index.html"]}
        result = self.check(task, ["keyboard_movement", "collection_updates_state"], bridge=True)
        self.assertFalse(result["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_complete_parent_profile_accepts_all_checks(self):
        task = {"id": "ROOT", "goal": FIXTURE["source_contract"]["goal"], "children": ["1", "2", "3", "4"]}
        result = self.check(task, ALL_GAME_CHECKS, bridge=True)
        self.assertTrue(result["passed"], result.get("failures"))
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_parent_cannot_forget_unassigned_touch_or_win(self):
        task = {"id": "ROOT", "goal": FIXTURE["source_contract"]["goal"], "children": ["1", "2", "3", "4"]}
        subset = ALL_GAME_CHECKS - {"touch_control", "goal_win_state"}
        self.assertFalse(self.check(task, subset, bridge=True)["passed"])

    def test_explicit_bridge_assignment_is_not_removed(self):
        task = self.child(); task["done_when"].append("Expose AGENT_GAME with getState().")
        self.assertFalse(self.check(task)["passed"])
        self.assertTrue(self.profiles[-1].require_game_bridge)

    def test_approved_execution_contract_does_not_get_narrowed(self):
        task = self.child(); task["execution_contract_id"] = "APPROVED-1"
        self.assertFalse(self.check(task)["passed"])
        self.assertTrue(self.profiles[-1].require_game_bridge)

    def test_plain_profile_api_retains_existing_behavior(self):
        profile = infer_web_profile(self.child()["goal"], {}, classification_policy="field_scoped")
        self.assertEqual(set(profile.required_interactions), {"keyboard_movement", "collection_updates_state"})

    def retain(self, browser, **changes):
        result = {"status": "done", "gate": {"passed": True}, "browser": browser,
                  "changed_files": ["index.html"]}
        result.update(changes)
        mini._retain_committed_browser_profile(result)

    def test_later_child_cannot_regress_committed_movement(self):
        moved = self.check(self.child(2), ["keyboard_movement"], bridge=True)
        self.retain(moved)
        self.assertFalse(self.check(self.child())["passed"])
        self.assertIn("keyboard_movement", self.profiles[-1].required_interactions)
        self.assertTrue(self.check(self.child(), ["keyboard_movement"], bridge=True)["passed"])

    def test_later_child_keeps_all_prior_behaviors_not_receipt_success(self):
        moved = self.check(self.child(2), ["keyboard_movement"], bridge=True)
        self.retain(moved)
        checks = {"keyboard_movement", "collection_updates_state", "collision_game_over"}
        mechanics = self.check(self.child(3), checks, bridge=True)
        self.retain(mechanics)
        self.assertFalse(self.check(self.child(4), ["restart_resets_state", "score_persistence"], bridge=True)["passed"])
        self.assertTrue(checks <= set(self.profiles[-1].required_interactions))

    def test_failed_or_worker_only_outcomes_do_not_create_completed_duties(self):
        browser = self.check(self.child(2), ["keyboard_movement"], bridge=True)
        for changes in ({"status": "failed"}, {"gate": {"passed": False}}, {"changed_files": None}):
            mini.RUN["committed_browser_profiles"] = {}
            self.retain(browser, **changes)
            self.assertFalse(mini.RUN["committed_browser_profiles"])
        mini.RUN["committed_browser_profiles"] = {}
        mini._retain_committed_browser_profile({"status": "done", "browser": browser})
        self.assertFalse(mini.RUN["committed_browser_profiles"])

    def test_prior_behavior_for_another_application_does_not_leak(self):
        browser = self.check(self.child(2), ["keyboard_movement"], bridge=True)
        browser["resolved_entrypoint"] = "other.html"
        self.retain(browser)
        self.assertTrue(self.check(self.child())["passed"])

    def test_existing_project_and_timer_paths_keep_legacy_profile(self):
        mini.RUN["project_mode"] = mini.EXISTING_PROJECT
        self.assertFalse(self.check(self.child())["passed"])
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        mini.RUN["source_contract"] = {"goal": "Build a countdown timer"}
        task = {"id": "T", "parent_id": "ROOT", "goal": "Create timer HTML", "done_when": ["The page has a title and canvas."]}
        self.check(task)
        self.assertEqual(self.profiles[-1].kind, "timer")
        self.assertIn("timer_pause_freezes_visible_time", self.profiles[-1].required_interactions)

    def test_parent_gate_rejects_missing_final_behaviors(self):
        task = {"id": "ROOT", "goal": FIXTURE["source_contract"]["goal"], "children": ["1", "2", "3", "4"]}
        browser = self.check(task, ["keyboard_movement", "collection_updates_state"], bridge=True)
        gate = mini.evidence_gate({"status": "done", "tool_evidence": [{"tool": "verify_web_app", "target": "index.html", "result": json.dumps(browser)}]}, browser_result=browser)
        self.assertFalse(gate["passed"])

    def test_parent_gate_accepts_complete_declared_profile(self):
        task = {"id": "ROOT", "goal": FIXTURE["source_contract"]["goal"], "children": ["1", "2", "3", "4"]}
        browser = self.check(task, ALL_GAME_CHECKS, bridge=True)
        gate = mini.evidence_gate({"status": "done", "tool_evidence": [{"tool": "verify_web_app", "target": "index.html", "result": json.dumps(browser)}]}, browser_result=browser)
        self.assertTrue(gate["passed"], gate)

    def test_real_leaf_dispatch_receives_controller_scope(self):
        task = self.child()
        class Dispatched(Exception):
            pass
        def worker(*args, **kwargs):
            self.assertEqual(kwargs["role"], "Builder")
            self.assertIn("child_browser_scope", mini.ACTIVE_TOOL_CONTRACT)
            raise Dispatched()
        with patch.object(mini, "prepare_worker_mission_context", return_value=({}, {})), \
                patch.object(mini, "build_node_context", return_value="fixture"), \
                patch.object(mini, "_prepare_task_impact_contract", return_value=None), \
                patch.object(mini, "execute_agent_task", side_effect=worker):
            with self.assertRaises(Dispatched):
                mini.execute_leaf(task, FIXTURE["source_contract"], {}, {})

    def test_root_source_requirements_survive_reduced_active_contract(self):
        task = {"id": "ROOT", "goal": "Combine the completed steps", "done_when": ["The page has a title and canvas."], "children": ["1", "2"]}
        browser = self.check(task, ["keyboard_movement", "collection_updates_state"], bridge=True)
        self.assertFalse(browser["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_scope_does_not_mutate_authority_inputs(self):
        task = self.child(); original = copy.deepcopy(task)
        source = copy.deepcopy(mini.RUN["source_contract"])
        self.check(task)
        self.assertEqual({k: task[k] for k in original}, original)
        self.assertEqual(mini.RUN["source_contract"], source)

    def test_leaf_records_profile_only_after_real_quality_and_commit_boundary(self):
        task = self.child()
        self.snapshot = {"title": "Scope fixture", "text": "Fixture page", "console_errors": [],
                         "page_errors": [], "network_errors": [],
                         "runtime_state": {"canvasCount": 1, "gameBridge": None},
                         "interaction_checks": [], "resolved_entrypoint": "index.html"}
        def worker(*args, **kwargs):
            # Scripted provider boundary; actual read tool, gate and transaction.
            text = mini.run_tool("read_file", {"path": "index.html"}, role=kwargs["role"])
            return {"status": "done", "summary": "Inspected fixture", "memory": {},
                    "tool_evidence": [{"tool": "read_file", "target": "index.html", "result": text}]}
        with patch.object(mini, "prepare_worker_mission_context", return_value=({}, {})), \
                patch.object(mini, "build_node_context", return_value="fixture"), \
                patch.object(mini, "_prepare_task_impact_contract", return_value=None), \
                patch.object(mini, "execute_agent_task", side_effect=worker), \
                patch.object(mini, "verify_browser_application", side_effect=self.browser):
            result = mini.execute_leaf(task, FIXTURE["source_contract"], {}, {})
        self.assertEqual(result["status"], "done", result)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)
        self.assertIn("index.html", mini.RUN["committed_browser_profiles"])
        self.assertEqual(mini.RUN["committed_browser_profiles"]["index.html"]["required_interactions"], [])

    def test_reduced_child_claim_cannot_satisfy_root_with_complete_labels(self):
        task = {"id": "ROOT", "goal": "Combine completed steps", "children": ["1", "2", "3", "4"]}
        browser = self.check(task)  # Child labels supply no behavioral evidence.
        gate = mini.evidence_gate({"status": "done", "tool_evidence": [
            {"tool": "verify_web_app", "target": "index.html", "result": json.dumps(browser)}]}, browser_result=browser)
        self.assertFalse(gate["passed"])

    def test_mixed_unknown_foundation_clause_retains_legacy_checks(self):
        task = self.child()
        task["done_when"] = ["The page has a title and canvas and satisfies an unspecified behavior."]
        self.assertFalse(self.check(task)["passed"])
        self.assertTrue(self.profiles[-1].require_game_bridge)

    def test_changed_scope_metadata_cannot_remove_current_assignment(self):
        task = self.child(2)
        contract = self.contract(task)
        contract["child_browser_scope"]["requirements"] = []
        profile = mini._scoped_browser_profile(task["goal"], contract, "index.html")
        self.assertTrue(profile.require_game_bridge)
        self.assertIn("keyboard_movement", profile.required_interactions)

    def test_unknown_movement_scope_cannot_fall_back_to_generic_web(self):
        task = self.child(2); task["done_when"] = ["Everything is fine"]
        self.assertFalse(self.check(task)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_missing_source_authority_cannot_enable_narrowing(self):
        mini.RUN["source_contract"] = {}
        self.assertFalse(self.check(self.child())["passed"])
        self.assertTrue(self.profiles[-1].require_game_bridge)

    def test_mixed_interactive_clause_does_not_hide_unknown_responsibility(self):
        task = self.child(2)
        task["done_when"] = ["Keyboard movement works inside arena bounds and supports winning."]
        self.check(task)
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_terminal_freeze_clause_does_not_assign_coin_collection(self):
        task = self.child(4); task["done_when"] = ["Game Over freezes movement and scoring."]
        self.check(task)
        self.assertNotIn("collection_updates_state", self.profiles[-1].required_interactions)

    def test_complete_game_child_cannot_claim_foundation_only(self):
        task = self.child(); task["goal"] = "Build the complete Coin Courier game"
        self.assertFalse(self.check(task)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), ALL_GAME_CHECKS)

    def test_touch_child_keeps_its_owned_behavior(self):
        task = self.child(); task.update(goal="Implement touch controls", done_when=["Touch controls work."])
        self.assertFalse(self.check(task)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"touch_control"})
        self.assertTrue(self.check(task, ["touch_control"], bridge=True)["passed"])

    def test_win_child_keeps_terminal_behavior_without_collection_ownership(self):
        task = self.child(); task.update(goal="Implement winning transition", done_when=["Winning stops movement and scoring."])
        self.assertFalse(self.check(task)["passed"])
        self.assertEqual(set(self.profiles[-1].required_interactions), {"goal_win_state"})
        self.assertTrue(self.check(task, ["goal_win_state"], bridge=True)["passed"])
