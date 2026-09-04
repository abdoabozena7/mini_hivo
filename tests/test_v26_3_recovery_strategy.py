"""Provider-free V26.3 bounded recovery-strategy tests."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import recovery


class V263RecoveryStrategyTests(unittest.TestCase):
    SUBJECT = "a" * 64
    TARGET = "src/status_view.js"

    def setUp(self):
        self._run = mini.RUN
        self._workspace = mini.WORKSPACE
        self._memory_store = mini.MEMORY_STORE
        mini.RUN = mini.new_metrics("v26.3-test")
        mini.WORKSPACE = None
        mini.MEMORY_STORE = None

    def tearDown(self):
        mini.RUN = self._run
        mini.WORKSPACE = self._workspace
        mini.MEMORY_STORE = self._memory_store

    @staticmethod
    def _syntax_error(line=8):
        return (
            f"error: JavaScript syntax validation failed: [stdin]:{line} "
            "SyntaxError: Unexpected token '}'\nedit rejected and file was not changed"
        )

    def _schemas(self):
        return mini.TOOLS

    def _state(self, **overrides):
        authorization = {
            "status": recovery.RECOVERY_AUTHORIZATION_READY,
            "authority_delta_empty": True,
            "user_reapproval_required": False,
            "authorization_id": "RECOVERY-AUTH-TEST",
            "authorization_hash": "b" * 64,
            "plan_hash": recovery.LIVE3_PLAN_HASH,
            "approval_receipt_hash": recovery.LIVE3_APPROVAL_RECEIPT_HASH,
        }
        state = recovery.create_recovery_strategy_state(
            "RECOVERY-EXEC-TEST-R1",
            target_path=self.TARGET,
            tool_schemas=self._schemas(),
            target_state={"exists": True, "protected": True},
            current_subject_hash=self.SUBJECT,
            recovery_authorization=authorization,
            lineage={"status": recovery.AUTHORIZED_EXECUTION_DESCENDANT, "valid": True},
        )
        state.update(overrides)
        return state

    def test_01_pattern_is_immutable_and_one_failure_does_not_switch(self):
        pattern = recovery.build_recovery_strategy_failure_pattern(
            "RECOVERY-EXEC-TEST-R1", target_path=self.TARGET,
            mutation_mechanism="edit_file_range", failure_count=1,
            subject_identity_before=self.SUBJECT, subject_identity_after=self.SUBJECT,
            latest_deterministic_diagnostic=self._syntax_error(),
            available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        self.assertTrue(recovery.validate_recovery_strategy_failure_pattern(pattern)["valid"])
        self.assertEqual(
            recovery.decide_recovery_strategy_diversification(
                pattern,
                current_strategy=recovery.build_recovery_mutation_strategy(
                    "RECOVERY-EXEC-TEST-R1", target_path=self.TARGET,
                    allowed_mutation_mechanisms=["edit_file_range", "edit_file"],
                    source_subject_identity=self.SUBJECT,
                ),
            )["decision"],
            recovery.NO_SWITCH_REQUIRED,
        )
        with self.assertRaises(TypeError):
            pattern["failure_count"] = 2

    def test_02_second_same_state_syntax_failure_switches_once(self):
        state = self._state()
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
        )
        self.assertFalse(first["switched"])
        self.assertEqual(first["decision"]["decision"], recovery.NO_SWITCH_REQUIRED)
        second = recovery.observe_recovery_mutation(
            first["state"], target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
        )
        self.assertTrue(second["switched"])
        self.assertEqual(second["decision"]["decision"], recovery.STRATEGY_SWITCH_READY)
        self.assertEqual(second["state"]["strategy_epoch"], 1)
        self.assertEqual(second["state"]["strategy_switch_count"], 1)
        self.assertEqual(second["state"]["suppressed_mutation_mechanisms"], ["edit_file_range"])
        self.assertEqual(
            second["state"]["current_strategy"]["recovery_authorization_id"],
            "RECOVERY-AUTH-TEST",
        )
        self.assertEqual(second["state"]["recovery_attempt_index"], 1)
        self.assertEqual(len(second["state"]["strategy_epoch_starts"]), 2)

    def test_03_epoch_one_schema_suppresses_only_exhausted_mutation(self):
        state = self._state()
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        epoch_zero = {item["function"]["name"] for item in mini.tools_for_role("Builder")}
        epoch_one = {
            item["function"]["name"]
            for item in mini.tools_for_role("Builder", recovery_strategy=state)
        }
        self.assertIn("edit_file_range", epoch_zero)
        self.assertIn("edit_file", epoch_zero)
        self.assertNotIn("edit_file_range", epoch_one)
        self.assertIn("edit_file", epoch_one)
        self.assertIn("read_file", epoch_one)
        self.assertIn("list_files", epoch_one)

    def test_04_alternatives_are_schema_derived_and_write_file_is_protected(self):
        legal = recovery.discover_legal_recovery_mutation_mechanisms(
            self._schemas(), target=self.TARGET,
            target_state={"exists": True, "protected": True},
            mutation_authority={"paths": [self.TARGET]},
        )
        self.assertIn("edit_file", legal)
        self.assertIn("edit_file_range", legal)
        self.assertNotIn("write_file", legal)

    def test_05_epoch_one_refreshes_current_source_without_full_transcript(self):
        state = self._state()
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        with tempfile.TemporaryDirectory(prefix="hivo_v263_refresh_") as root:
            target = Path(root) / self.TARGET
            target.parent.mkdir(parents=True)
            target.write_text("const current = true;\n", encoding="utf-8")
            refreshed = recovery.refresh_recovery_strategy_source(
                state, workspace=root, target_path=self.TARGET,
            )
        self.assertTrue(refreshed["current_source_refreshed"])
        self.assertTrue(refreshed["current_source_refresh"]["source_available"])
        feedback = refreshed["last_transition_feedback"] if "last_transition_feedback" in refreshed else ""
        if feedback:
            self.assertNotIn("module.exports =", feedback)

    def test_06_transition_feedback_is_bounded_and_patch_free(self):
        state = self._state()
        observed = None
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        feedback = recovery.build_recovery_strategy_transition_feedback(
            observed["pattern"], observed["decision"], state["current_strategy"],
        )
        self.assertLessEqual(len(feedback), 1800)
        self.assertIn("Continue the SAME RecoveryMission", feedback)
        self.assertNotIn("renderPauseIndicator", feedback)
        self.assertNotIn("module.exports", feedback)

    def test_07_same_worker_positive_epoch_one_continuation(self):
        state = self._state()
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        self.assertEqual(state["recovery_attempt_index"], 1)
        success = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file",
            failure_class="MUTATION_COMMITTED", committed=True,
            subject_identity_before=self.SUBJECT, subject_identity_after="c" * 64,
            subject_unchanged=False, tool_schemas=self._schemas(),
        )
        self.assertEqual(success["state"]["strategy_epoch"], 1)
        self.assertEqual(success["state"]["strategy_switch_count"], 1)
        self.assertEqual(success["state"]["consecutive_failure_count"], 0)
        self.assertIsNone(success["state"]["terminal_state"])

    def test_08_execute_agent_task_switches_actual_schema_inside_one_loop(self):
        state = self._state()
        offered = []
        visible_contexts = []
        responses = [
            {"tool_calls": [{"function": {"name": "edit_file_range", "arguments": {
                "path": self.TARGET, "start_line": 1, "end_line": 1, "new": "bad",
            }}}]},
            {"tool_calls": [{"function": {"name": "edit_file_range", "arguments": {
                "path": self.TARGET, "start_line": 1, "end_line": 1, "new": "bad",
            }}}]},
            {"tool_calls": [{"function": {"name": "edit_file", "arguments": {
                "path": self.TARGET, "old": "old", "new": "new",
            }}}]},
            {"content": "completed", "tool_calls": []},
        ]

        def ask(_messages, *, tools, **_kwargs):
            offered.append({item["function"]["name"] for item in tools})
            visible_contexts.append(str(_messages[-1].get("content", "")) if _messages else "")
            return responses.pop(0)

        def run_tool(name, _args, role="Builder"):
            if name == "edit_file_range":
                return self._syntax_error()
            return "edited file successfully"

        with patch.object(mini, "ask_ollama", side_effect=ask), patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Continue the bounded recovery mission", {}, role="Builder",
                task_id="RECOVERY-EXEC-TEST-R1", recovery_strategy=state,
                worker_context="RECOVERY-MISSION-ID=MISSION-TEST; AUTHORITY=UNCHANGED",
            )
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(offered), 4)
        self.assertIn("edit_file_range", offered[0])
        self.assertIn("edit_file_range", offered[1])
        self.assertNotIn("edit_file_range", offered[2])
        self.assertIn("edit_file", offered[2])
        self.assertEqual(result["recovery_strategy"]["strategy_switch_count"], 1)
        self.assertEqual(result["recovery_strategy"]["strategy_epoch"], 1)
        self.assertEqual(result["recovery_strategy_state"]["recovery_attempt_index"], 1)
        self.assertIn("RECOVERY-MISSION-ID=MISSION-TEST", visible_contexts[2])
        self.assertNotIn("bad", visible_contexts[2])

    def test_09_epoch_one_repeated_failure_is_search_exhausted_not_decomposition(self):
        state = self._state()
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file",
            diagnostic=self._syntax_error(9), tool_schemas=self._schemas(),
        )
        second = recovery.observe_recovery_mutation(
            first["state"], target_path=self.TARGET, mutation_mechanism="edit_file",
            diagnostic=self._syntax_error(9), tool_schemas=self._schemas(),
        )
        self.assertEqual(second["terminal_state"], recovery.RECOVERY_STRATEGY_SEARCH_EXHAUSTED)
        self.assertEqual(second["decision"]["decision"], recovery.STRATEGY_SWITCH_BUDGET_EXHAUSTED)
        self.assertNotIn("decomposition", " ".join(second["state"]["strategy_search_summary"].keys()).casefold())
        self.assertEqual(second["state"]["strategy_switch_count"], 1)
        self.assertEqual(second["state"]["recovery_attempt_index"], 1)
        self.assertTrue(second["state"]["strategy_epoch_terminals"])
        self.assertEqual(
            second["state"]["strategy_epoch_terminals"][-1]["terminal_state"],
            recovery.RECOVERY_STRATEGY_SEARCH_EXHAUSTED,
        )
        self.assertTrue(
            recovery.validate_recovery_strategy_diversification_decision(
                second["decision"]
            )["valid"]
        )

    def test_10_no_legal_alternative_is_unavailable(self):
        state = self._state(available_legal_mechanisms=["edit_file_range"])
        state["current_strategy"] = recovery.build_recovery_mutation_strategy(
            state["recovery_execution_id"], target_path=self.TARGET,
            allowed_mutation_mechanisms=["edit_file_range"],
            source_subject_identity=self.SUBJECT,
        )
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range"],
        )
        second = recovery.observe_recovery_mutation(
            first["state"], target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range"],
        )
        self.assertEqual(second["decision"]["decision"], recovery.STRATEGY_SWITCH_UNAVAILABLE)
        self.assertFalse(second["switched"])

    def test_11_authority_blocked_alternative_is_not_switched(self):
        state = self._state(
            available_legal_mechanisms=["edit_file_range", "edit_file"],
            recovery_authorization={
                "status": recovery.RECOVERY_AUTHORIZATION_BLOCKED,
                "authority_delta_empty": False,
                "user_reapproval_required": True,
            },
        )
        state["current_strategy"] = recovery.build_recovery_mutation_strategy(
            state["recovery_execution_id"], target_path=self.TARGET,
            allowed_mutation_mechanisms=["edit_file_range", "edit_file"],
            source_subject_identity=self.SUBJECT,
        )
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        second = recovery.observe_recovery_mutation(
            first["state"], target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        self.assertEqual(second["decision"]["decision"], recovery.STRATEGY_SWITCH_BLOCKED_AUTHORITY)
        self.assertFalse(second["switched"])
        self.assertTrue(second["decision"]["USER_REAPPROVAL_REQUIRED"])

    def test_12_reset_semantics_do_not_combine_unrelated_failures(self):
        state = self._state()
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        target_change = recovery.observe_recovery_mutation(
            first["state"], target_path="src/other.js", mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        tool_change = recovery.observe_recovery_mutation(
            target_change["state"], target_path=self.TARGET, mutation_mechanism="edit_file",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        class_change = recovery.observe_recovery_mutation(
            tool_change["state"], target_path=self.TARGET, mutation_mechanism="edit_file",
            failure_class="DNT_REJECTED_MUTATION", diagnostic="DNT rejection",
            available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        self.assertEqual(target_change["pattern"]["failure_count"], 1)
        self.assertEqual(tool_change["pattern"]["failure_count"], 1)
        self.assertEqual(class_change["pattern"]["failure_count"], 1)
        self.assertFalse(class_change["stagnation"]["detected"])

    def test_13_subject_change_and_commit_reset_failure_accumulation(self):
        state = self._state()
        first = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        changed = recovery.observe_recovery_mutation(
            first["state"], target_path=self.TARGET, mutation_mechanism="edit_file_range",
            diagnostic=self._syntax_error(), subject_identity_before=self.SUBJECT,
            subject_identity_after="c" * 64, subject_unchanged=False,
            available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        committed = recovery.observe_recovery_mutation(
            changed["state"], target_path=self.TARGET, mutation_mechanism="edit_file",
            failure_class="MUTATION_COMMITTED", committed=True,
            subject_identity_before="c" * 64, subject_identity_after="d" * 64,
            subject_unchanged=False, available_legal_mechanisms=["edit_file"],
        )
        self.assertEqual(changed["pattern"]["failure_count"], 1)
        self.assertEqual(committed["state"]["consecutive_failure_count"], 0)

    def test_14_strategy_budget_and_identity_are_bounded(self):
        state = self._state()
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )
            state = observed["state"]
        self.assertEqual(state["strategy_switch_count"], recovery.MAX_RECOVERY_STRATEGY_SWITCHES)
        self.assertEqual(state["recovery_attempt_index"], 1)
        self.assertEqual(state["recovery_execution_id"], "RECOVERY-EXEC-TEST-R1")
        self.assertEqual(state["current_strategy"]["recovery_execution_id"], state["recovery_execution_id"])
        self.assertEqual(state["current_strategy"]["strategy_epoch"], 1)

    def test_15_other_recovery_state_starts_epoch_zero_and_projection_is_local(self):
        state_a = self._state()
        state_b = self._state(recovery_execution_id="RECOVERY-EXEC-OTHER-R1")
        for _ in range(2):
            state_a = recovery.observe_recovery_mutation(
                state_a, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )["state"]
        self.assertEqual(state_a["strategy_epoch"], 1)
        self.assertEqual(state_b["strategy_epoch"], 0)
        self.assertIn(
            "edit_file_range",
            {item["function"]["name"] for item in mini.tools_for_role("Builder", recovery_strategy=state_b)},
        )
        self.assertIn(
            "edit_file_range",
            {item["function"]["name"] for item in mini.tools_for_role("Builder")},
        )

    def test_16_identity_gates_prevent_unrelated_switches(self):
        pattern = recovery.build_recovery_strategy_failure_pattern(
            "RECOVERY-EXEC-TEST-R1", strategy_epoch=0, target_path=self.TARGET,
            mutation_mechanism="edit_file_range", failure_count=2,
            subject_identity_before=self.SUBJECT, subject_identity_after=self.SUBJECT,
            available_legal_mechanisms=["edit_file_range", "edit_file"],
        )
        strategy = recovery.build_recovery_mutation_strategy(
            "RECOVERY-EXEC-TEST-R1", strategy_epoch=0, target_path=self.TARGET,
            allowed_mutation_mechanisms=["edit_file_range", "edit_file"],
            source_subject_identity=self.SUBJECT,
        )
        scenarios = [
            ("OTHER", self.SUBJECT, strategy),
            ("RECOVERY-EXEC-TEST-R1", "b" * 64, strategy),
            (
                "RECOVERY-EXEC-TEST-R1", self.SUBJECT,
                recovery.build_recovery_mutation_strategy(
                    "RECOVERY-EXEC-TEST-R1", strategy_epoch=0, target_path="src/other.js",
                    allowed_mutation_mechanisms=["edit_file_range", "edit_file"],
                    source_subject_identity=self.SUBJECT,
                ),
            ),
        ]
        for execution_id, subject, current_strategy in scenarios:
            decision = recovery.decide_recovery_strategy_diversification(
                pattern, current_strategy=current_strategy,
                recovery_execution_id=execution_id, current_subject_hash=subject,
                available_legal_mechanisms=["edit_file_range", "edit_file"],
            )
            self.assertNotEqual(decision["decision"], recovery.STRATEGY_SWITCH_READY)

    def test_17_malformed_records_fail_closed_and_budget_is_capped(self):
        self.assertFalse(
            recovery.validate_recovery_strategy_failure_pattern({"failure_count": "bad"})["valid"]
        )
        state = recovery.create_recovery_strategy_state(
            "RECOVERY-EXEC-TEST-R1", target_path=self.TARGET, max_strategy_switches=99,
        )
        self.assertEqual(state["max_strategy_switches"], recovery.MAX_RECOVERY_STRATEGY_SWITCHES)
        self.assertFalse(recovery.validate_recovery_strategy_state({})["valid"])

    def test_18_positive_and_negative_existing_v26_replays_remain_provider_free(self):
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        if not live3.is_dir():
            self.skipTest("historical V25.6 live-3 fixture unavailable")
        positive = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        negative = recovery.run_provider_free_recovery_replay(live3, outcome="failure")
        self.assertEqual(positive["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(positive["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(positive["reentry"]["status"], "REENTRY_READY")
        self.assertTrue(negative["brain_unchanged"])
        self.assertEqual(negative["second_dispatch"]["status"], recovery.RECOVERY_BUDGET_EXHAUSTED)
        self.assertEqual(positive["gemma_calls"], 0)
        self.assertEqual(negative["real_worker_calls"], 0)

    def test_19_positive_diversified_prefix_preserves_full_v26_closure(self):
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        if not live3.is_dir():
            self.skipTest("historical V25.6 live-3 fixture unavailable")
        state = self._state()
        for _ in range(2):
            state = recovery.observe_recovery_mutation(
                state, target_path=self.TARGET, mutation_mechanism="edit_file_range",
                diagnostic=self._syntax_error(), tool_schemas=self._schemas(),
            )["state"]
        committed = recovery.observe_recovery_mutation(
            state, target_path=self.TARGET, mutation_mechanism="edit_file",
            failure_class="MUTATION_COMMITTED", committed=True, commit_count=1,
            subject_identity_before=self.SUBJECT, subject_identity_after="c" * 64,
            subject_unchanged=False, tool_schemas=self._schemas(),
        )
        self.assertEqual(committed["state"]["strategy_epoch"], 1)
        self.assertEqual(committed["state"]["strategy_switch_count"], 1)
        continuation = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        self.assertTrue(continuation["stage5a"]["passed"])
        self.assertEqual(continuation["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(continuation["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(continuation["reentry"]["status"], "REENTRY_READY")
        self.assertEqual(continuation["model_calls"], 0)
        self.assertEqual(continuation["worker_calls"], 0)


if __name__ == "__main__":
    unittest.main()
