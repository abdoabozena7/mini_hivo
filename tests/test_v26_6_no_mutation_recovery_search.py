"""Provider-free V26.6 no-mutation recovery search closure tests."""

from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import recovery


class V266NoMutationRecoverySearchTests(unittest.TestCase):
    SUBJECT = "a" * 64
    CHANGED_SUBJECT = "b" * 64
    TARGET = "src/status_view.js"
    OTHER_TARGET = "src/input.js"
    EXECUTION = "RECOVERY-EXEC-V266-TEST-R1"
    MISSION = "MISSION-V266-TEST"
    AUTHORIZATION = {
        "status": recovery.RECOVERY_AUTHORIZATION_READY,
        "authority_delta_empty": True,
        "user_reapproval_required": False,
        "authorization_id": "RECOVERY-AUTH-V266-TEST",
        "authorization_hash": "b" * 64,
        "plan_hash": recovery.LIVE3_PLAN_HASH,
        "approval_receipt_hash": recovery.LIVE3_APPROVAL_RECEIPT_HASH,
    }
    LEGAL = ["edit_file", "edit_file_range"]

    def setUp(self):
        self._run = mini.RUN
        self._workspace = mini.WORKSPACE
        self._memory_store = mini.MEMORY_STORE
        mini.RUN = mini.new_metrics("v26.6-test")
        mini.WORKSPACE = None
        mini.MEMORY_STORE = None

    def tearDown(self):
        mini.RUN = self._run
        mini.WORKSPACE = self._workspace
        mini.MEMORY_STORE = self._memory_store

    def _state(self, **overrides):
        state = recovery.create_recovery_strategy_state(
            self.EXECUTION,
            target_path=self.TARGET,
            available_legal_mechanisms=self.LEGAL,
            current_subject_hash=self.SUBJECT,
            recovery_authorization=copy.deepcopy(self.AUTHORIZATION),
            lineage={
                "status": recovery.AUTHORIZED_EXECUTION_DESCENDANT,
                "valid": True,
            },
            recovery_mission_id=self.MISSION,
        )
        state.update({
            "recovery_mission_unresolved": True,
            "provider_healthy": True,
            "provider_harness_blocked": False,
            "authority_unchanged": True,
            "scope_valid": True,
            "dnt_valid": True,
        })
        state.update(overrides)
        return recovery.initialize_recovery_no_mutation_search_state(state)

    def _observe(self, state, tool_name, ordinal, **overrides):
        values = {
            "tool_name": tool_name,
            "target_path": state.get("target_path", self.TARGET),
            "subject_identity": state.get("current_subject_hash", self.SUBJECT),
            "subject_unchanged": True,
            "event_id": f"tool-event-{ordinal}",
            "remaining_tool_steps": 20,
            "tool_steps_used": ordinal,
        }
        values.update(overrides)
        return recovery.observe_recovery_no_mutation_search_interaction(
            state, **values
        )

    def _four_search_interactions(self, state=None):
        current = state or self._state()
        observations = []
        for ordinal, tool_name in enumerate(
            ("list_files", "list_files", "read_file", "read_file"), 1
        ):
            observation = self._observe(current, tool_name, ordinal)
            observations.append(observation)
            current = observation["state"]
        return current, observations

    def test_01_pattern_is_immutable_hash_stable_and_fail_closed(self):
        pattern = recovery.build_recovery_no_mutation_search_pattern(
            self.EXECUTION,
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            legal_mutation_mechanisms=self.LEGAL,
            interaction_count=4,
            first_interaction_event_id="first",
            latest_interaction_event_id="latest",
            tool_steps_used=4,
            tool_steps_remaining=20,
        )
        same = recovery.build_recovery_no_mutation_search_pattern(
            self.EXECUTION,
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            legal_mutation_mechanisms=self.LEGAL,
            interaction_count=4,
            first_interaction_event_id="first",
            latest_interaction_event_id="latest",
            tool_steps_used=4,
            tool_steps_remaining=20,
        )
        self.assertEqual(pattern["canonical_hash"], same["canonical_hash"])
        self.assertTrue(
            recovery.validate_recovery_no_mutation_search_pattern(pattern)["valid"]
        )
        with self.assertRaises(TypeError):
            pattern["interaction_count"] = 5
        malformed = dict(pattern)
        malformed["interaction_count"] = 4
        malformed["canonical_hash"] = "0" * 64
        self.assertFalse(
            recovery.validate_recovery_no_mutation_search_pattern(malformed)["valid"]
        )

    def test_02_interaction_counter_is_execution_local(self):
        first = self._observe(self._state(), "read_file", 1)
        other = self._observe(
            self._state(recovery_execution_id="RECOVERY-EXEC-OTHER-R1"),
            "read_file",
            1,
        )
        self.assertEqual(first["interaction_count"], 1)
        self.assertEqual(other["interaction_count"], 1)
        self.assertEqual(first["state"]["recovery_execution_id"], self.EXECUTION)
        self.assertNotEqual(
            first["state"]["recovery_execution_id"],
            other["state"]["recovery_execution_id"],
        )

    def test_03_counted_tool_semantics_include_reads_commands_and_rejections(self):
        current = self._state()
        for ordinal, tool_name in enumerate(
            ("read_file", "read_file_range", "list_files", "run_file", "run_command", "verify_web_app"),
            1,
        ):
            result = self._observe(current, tool_name, ordinal)
            current = result["state"]
            self.assertTrue(result["counted"], tool_name)
        self.assertEqual(current["no_mutation_search_interaction_count"], 2)
        rejected = self._observe(
            self._state(), "run_command", 1,
            remaining_tool_steps=20,
        )
        self.assertTrue(rejected["counted"])
        self.assertEqual(rejected["interaction_count"], 1)
        unknown = self._observe(
            self._state(), "unknown_tool", 1, recognized_tool=False
        )
        self.assertFalse(unknown["counted"])
        self.assertEqual(unknown["reason"], "unrecognized_tool")

    def test_04_empty_and_completion_events_are_preserved_but_not_counted(self):
        state = self._state()
        empty = self._observe(
            state, None, 1, recognized_tool=False, empty_response=True
        )
        completion = self._observe(
            empty["state"], None, 2,
            recognized_tool=False, completion_attempt=True,
        )
        self.assertFalse(empty["counted"])
        self.assertFalse(completion["counted"])
        self.assertEqual(completion["interaction_count"], 0)
        self.assertEqual(empty["reason"], "empty_response")
        self.assertEqual(completion["reason"], "completion_attempt")

    def test_05_mutation_attempts_and_commit_reset_the_window(self):
        current, _ = self._four_search_interactions(self._state())
        syntax_invalid = self._observe(
            current, "edit_file", 5, mutation_attempt=True, committed=False
        )
        self.assertTrue(syntax_invalid["reset"])
        self.assertEqual(syntax_invalid["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_RESET)
        self.assertEqual(syntax_invalid["state"]["no_mutation_search_interaction_count"], 0)
        current = self._observe(syntax_invalid["state"], "read_file", 6)["state"]
        committed = self._observe(
            current, "edit_file_range", 7, mutation_attempt=True, committed=True,
            commit_count=1,
        )
        self.assertTrue(committed["reset"])
        self.assertEqual(committed["state"]["no_mutation_search_interaction_count"], 0)

    def test_06_all_identity_changes_reset_without_stale_count(self):
        cases = [
            ("target", {"target_path": self.OTHER_TARGET}),
            ("subject", {"subject_identity": self.CHANGED_SUBJECT, "subject_unchanged": False}),
            ("epoch", {"strategy_epoch": 1}),
            ("execution", {"state_update": {"recovery_execution_id": "RECOVERY-EXEC-OTHER-R1"}}),
            ("authority", {"authority_unchanged": False}),
            ("legal-space", {"legal_mutation_mechanisms": ["edit_file"]}),
        ]
        for label, change in cases:
            with self.subTest(label=label):
                state, _ = self._four_search_interactions(self._state())
                state = copy.deepcopy(state)
                state.update(change.get("state_update", {}))
                args = {
                    key: value for key, value in change.items()
                    if key != "state_update"
                }
                result = self._observe(state, "read_file", 5, **args)
                expected = 0 if label == "authority" else 1
                self.assertEqual(result["interaction_count"], expected)
                self.assertFalse(result["reoriented"])

    def test_07_threshold_alternatives_are_bounded_and_four_matches_history(self):
        rationale = {
            2: "too early; removes ordinary orientation freedom",
            3: "early; intervenes before the historical third orientation action completes",
            4: "matches three orientation actions plus the fourth same-state action",
            5: "too late; waits beyond the historically demonstrated stall",
        }
        self.assertEqual(set(rationale), {2, 3, 4, 5})
        self.assertEqual(
            recovery.MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION,
            4,
        )
        self.assertIn("matches", rationale[4])
        self.assertIn("ordinary", rationale[2])
        self.assertIn("historically", rationale[5])

    def test_08_three_interactions_do_not_trigger_and_fourth_triggers_once(self):
        state = self._state()
        for ordinal in range(1, 4):
            observed = self._observe(state, "read_file", ordinal)
            state = observed["state"]
            self.assertFalse(observed["reoriented"])
            self.assertEqual(observed["interaction_count"], ordinal)
        fourth = self._observe(state, "read_file", 4)
        self.assertTrue(fourth["reoriented"])
        self.assertEqual(fourth["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_STAGNATION)
        self.assertEqual(fourth["state"]["mutation_path_reorientations_used"], 1)
        self.assertEqual(fourth["state"]["no_mutation_search_interaction_count"], 0)
        self.assertEqual(
            recovery.validate_recovery_mutation_path_reorientation_event(
                fourth["event"]
            )["valid"],
            True,
        )

    def test_09_trigger_predicate_fail_closes_provider_authority_scope_mission_and_space(self):
        cases = [
            ("provider", {"provider_healthy": False}),
            ("harness", {"provider_harness_blocked": True}),
            ("authority", {"authority_unchanged": False}),
            ("scope", {"scope_valid": False}),
            ("dnt", {"dnt_valid": False}),
            ("mission", {"recovery_mission_unresolved": False}),
            ("no-space", {"available_legal_mechanisms": []}),
            ("target", {"target_path": ""}),
            ("subject", {"current_subject_hash": None}),
        ]
        for label, overrides in cases:
            with self.subTest(label=label):
                state = self._state(**overrides)
                current = state
                for ordinal in range(1, 5):
                    observed = self._observe(current, "read_file", ordinal)
                    current = observed["state"]
                self.assertFalse(observed["reoriented"])
                self.assertEqual(observed["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_BLOCKED)
                self.assertEqual(observed["state"]["mutation_path_reorientations_used"], 0)

    def test_10_safety_floor_is_smallest_deterministic_floor_and_low_budget_blocks(self):
        self.assertEqual(
            recovery.MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION,
            3,
        )
        blocked = self._observe(
            self._state(), "read_file", 1, remaining_tool_steps=2
        )
        self.assertEqual(blocked["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_BLOCKED)
        self.assertIn("insufficient_remaining_budget", blocked["blockers"])
        allowed = self._observe(
            self._state(), "read_file", 1, remaining_tool_steps=3
        )
        self.assertEqual(allowed["interaction_count"], 1)
        self.assertFalse(allowed["reoriented"])

    def test_11_reorientation_context_is_dynamic_bounded_and_patch_free(self):
        state, observations = self._four_search_interactions(self._state())
        event = observations[-1]["event"]
        context = event["model_visible_context"]
        self.assertLessEqual(len(context), 1800)
        self.assertIn(self.TARGET, context)
        self.assertIn("edit_file", context)
        self.assertIn("edit_file_range", context)
        self.assertIn("behavior-changing RecoveryMission remains unresolved", context)
        self.assertIn("Full verification remains required", context)
        self.assertIn("same RecoveryMission", context)
        self.assertNotIn("renderPauseIndicator", context)
        self.assertNotIn("module.exports", context)
        self.assertNotIn("PRIVATE OLD TRANSCRIPT", context)
        self.assertEqual(event["model_visible_context_hash"], recovery.canonical_hash(context))
        self.assertEqual(event["worker_prose_authority"], 0)
        self.assertEqual(state["recovery_mission_id"], self.MISSION)

    def test_12_same_worker_authority_epoch_strategy_and_schema_are_preserved(self):
        state = self._state()
        before_schema = mini.tools_for_role("Builder", recovery_strategy=state)
        before_hash = recovery.canonical_hash(before_schema)
        state, _ = self._four_search_interactions(state)
        event = state["last_mutation_path_reorientation"]
        after_schema = mini.tools_for_role("Builder", recovery_strategy=state)
        self.assertEqual(before_hash, recovery.canonical_hash(after_schema))
        self.assertEqual(state["recovery_execution_id"], self.EXECUTION)
        self.assertEqual(state["recovery_attempt_index"], 1)
        self.assertEqual(state["recovery_mission_id"], self.MISSION)
        self.assertEqual(state["recovery_authorization"], self.AUTHORIZATION)
        self.assertEqual(state["strategy_epoch"], 0)
        self.assertEqual(state["strategy_switch_count"], 0)
        self.assertEqual(state["mutation_path_reorientations_used"], 1)
        self.assertTrue(event["same_recovery_worker"])
        self.assertEqual(event["recovery_authorization_id"], self.AUTHORIZATION["authorization_id"])
        self.assertEqual(event["recovery_authorization_hash"], self.AUTHORIZATION["authorization_hash"])

    def test_13_second_threshold_records_explicit_exhaustion_without_second_event(self):
        state, _ = self._four_search_interactions(self._state())
        self.assertEqual(state["mutation_path_reorientations_used"], 1)
        current = state
        results = []
        for ordinal in range(5, 9):
            result = self._observe(current, "read_file", ordinal)
            results.append(result)
            current = result["state"]
        self.assertEqual(results[-1]["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED)
        self.assertFalse(results[-1]["reoriented"])
        self.assertTrue(current["no_mutation_search_exhausted"])
        self.assertEqual(len(current["mutation_path_reorientation_events"]), 1)
        self.assertEqual(current["terminal_state"], None)
        self.assertNotEqual(results[-1]["status"], recovery.CAPABILITY_FLOOR)
        self.assertNotEqual(results[-1]["status"], recovery.RECOVERY_STRATEGY_SEARCH_EXHAUSTED)

    def test_14_mutation_before_threshold_keeps_v26_6_dormant(self):
        state = self._state()
        for ordinal, tool_name in enumerate(("read_file", "list_files", "read_file"), 1):
            state = self._observe(state, tool_name, ordinal)["state"]
        mutation = self._observe(state, "edit_file", 4, mutation_attempt=True)
        self.assertFalse(mutation["reoriented"])
        self.assertEqual(mutation["state"]["mutation_path_reorientations_used"], 0)
        self.assertEqual(mutation["state"]["no_mutation_search_interaction_count"], 0)

    def test_15_v264_and_v263_adaptations_own_mutation_failures_after_reorientation(self):
        state, _ = self._four_search_interactions(self._state())
        # The first mutation attempt resets V26.6; two deterministic syntax
        # failures then remain owned by the existing V26.3 state machine.
        for _ in range(2):
            observed = recovery.observe_recovery_mutation(
                state,
                target_path=self.TARGET,
                mutation_mechanism="edit_file_range",
                diagnostic="syntax-invalid candidate",
                available_legal_mechanisms=self.LEGAL,
            )
            state = observed["state"]
        self.assertEqual(state["mutation_path_reorientations_used"], 1)
        self.assertEqual(state["strategy_epoch"], 1)
        self.assertEqual(state["strategy_switch_count"], 1)
        self.assertEqual(state["no_mutation_search_interaction_count"], 0)
        ambiguous = "error: expected 1 exact replacement(s), found 2; file was not changed"
        first = recovery.observe_recovery_tool_contract_failure(
            state, tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"], tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        self.assertTrue(second["escalated"])
        self.assertEqual(second["state"]["mutation_path_reorientations_used"], 1)

    def test_16_strategy_epoch_change_resets_local_search_and_does_not_consume_v266_budget(self):
        state = self._state()
        current = state
        for ordinal in range(1, 4):
            current = self._observe(current, "read_file", ordinal)["state"]
        current["strategy_epoch"] = 1
        current["current_strategy"] = recovery.build_recovery_mutation_strategy(
            self.EXECUTION,
            strategy_epoch=1,
            target_path=self.TARGET,
            allowed_mutation_mechanisms=["edit_file"],
            source_subject_identity=self.SUBJECT,
        )
        next_event = self._observe(
            current, "read_file", 5,
            strategy_epoch=1, legal_mutation_mechanisms=["edit_file"],
        )
        self.assertEqual(next_event["interaction_count"], 1)
        self.assertEqual(next_event["state"]["mutation_path_reorientations_used"], 0)

    def test_17_provider_free_historical_equivalent_replay_reorients_then_enters_mutation(self):
        state = self._state()
        current = state
        for ordinal, tool_name in enumerate(("list_files", "list_files", "read_file"), 1):
            current = self._observe(current, tool_name, ordinal)["state"]
        empty = self._observe(
            current, None, 4, recognized_tool=False, empty_response=True
        )
        self.assertEqual(empty["interaction_count"], 3)
        current = empty["state"]
        fourth = self._observe(current, "read_file", 5)
        self.assertTrue(fourth["reoriented"])
        self.assertEqual(fourth["pattern"]["interaction_count"], 4)
        mutation = self._observe(
            fourth["state"], "edit_file", 6, mutation_attempt=True
        )
        self.assertEqual(mutation["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_RESET)
        self.assertEqual(mutation["state"]["no_mutation_search_interaction_count"], 0)

    def test_18_provider_free_positive_control_preserves_full_downstream_closure(self):
        state, _ = self._four_search_interactions(self._state())
        mutation = self._observe(
            state, "edit_file", 5, mutation_attempt=True, committed=True, commit_count=1
        )
        self.assertEqual(mutation["state"]["mutation_path_reorientations_used"], 1)
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        replay = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        self.assertEqual(replay["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(replay["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(replay["reentry"]["status"], "REENTRY_READY")
        self.assertEqual(replay["gemma_calls"], 0)

    def test_19_execute_loop_delivers_reorientation_to_same_provider_context(self):
        state = self._state()
        offered = []
        visible_contexts = []
        responses = [
            {"tool_calls": [{"function": {"name": "list_files", "arguments": {}}}]},
            {"tool_calls": [{"function": {"name": "list_files", "arguments": {}}}]},
            {"tool_calls": [{"function": {"name": "read_file", "arguments": {"path": self.TARGET}}}]},
            {"tool_calls": [{"function": {"name": "read_file", "arguments": {"path": self.TARGET}}}]},
            {"tool_calls": [{"function": {"name": "edit_file", "arguments": {
                "path": self.TARGET, "old": "old", "new": "new",
            }}}]},
            {"content": "completed", "tool_calls": []},
        ]

        def ask(messages, *, tools, **_kwargs):
            offered.append({item["function"]["name"] for item in tools})
            visible_contexts.append(str(messages[-1].get("content", "")))
            return responses.pop(0)

        def run_tool(name, _args, role="Builder"):
            if name == "list_files":
                return "src/status_view.js"
            if name == "read_file":
                return "current source"
            return "edited file successfully"

        with patch.object(mini, "ask_ollama", side_effect=ask), patch.object(
            mini, "run_tool", side_effect=run_tool
        ):
            result = mini.execute_agent_task(
                "Continue the bounded recovery mission", {}, role="Builder",
                task_id=self.EXECUTION, recovery_strategy=state,
                worker_context="RECOVERY-MISSION-ID=MISSION-TEST; AUTHORITY=UNCHANGED",
            )
        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["recovery_mutation_path_reorientation_events"]), 1)
        self.assertEqual(result["recovery_strategy_state"]["mutation_path_reorientations_used"], 1)
        self.assertEqual(len(offered), 6)
        for tool_set in offered:
            self.assertEqual(tool_set, offered[0])
        self.assertIn("Authorized mutation target: src/status_view.js", visible_contexts[4])
        self.assertIn("Continue the SAME RecoveryMission", visible_contexts[4])
        self.assertNotIn("old", visible_contexts[4])
        self.assertEqual(result["recovery_strategy_state"]["recovery_execution_id"], self.EXECUTION)

    def test_20_budget_and_nonregression_invariants_remain_frozen(self):
        self.assertEqual(recovery.MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_STRATEGY_SWITCHES, 1)
        self.assertEqual(recovery.MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_EPOCH_REANCHORS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS, 1)
        self.assertEqual(recovery.RECOVERY_STRATEGY_STAGNATION_THRESHOLD, 2)
        self.assertEqual(recovery.SYNTAX_INVALID_MUTATION, "SYNTAX_INVALID_MUTATION")
        self.assertEqual(recovery.VERIFICATION_FAILURE, "VERIFICATION_FAILURE")
        self.assertEqual(recovery.WORKER_EXECUTION_FAILURE, "WORKER_EXECUTION_FAILURE")
        self.assertEqual(recovery.LIVE3_INVARIANT_HASH, "257c9d474539fdc74cfb7a6ca088bdf3431013f8e844af45c6d9e95bb7f73424")
        self.assertEqual(recovery.LIVE3_VERIFICATION_DIGEST, "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51")
        self.assertEqual(recovery.LIVE3_COVERAGE_HASH, "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402")
        self.assertEqual(recovery.LIVE3_ORACLE_HASH, "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140")

    def test_21_no_provider_calls_marker_or_live_workspace_are_used(self):
        self.assertFalse(
            Path(
                r"D:\projects\Ai\mini_hivo\output\hivo-v26-6-stage6c-b-no-mutation-recovery-live-1"
            ).exists()
        )
        with patch.object(mini, "ask_ollama") as ask:
            state, _ = self._four_search_interactions(self._state())
            self.assertEqual(state["mutation_path_reorientations_used"], 1)
            ask.assert_not_called()

    def test_22_brain_and_authority_are_unchanged_by_adaptation(self):
        state, _ = self._four_search_interactions(self._state())
        self.assertEqual(state["recovery_authorization"], self.AUTHORIZATION)
        self.assertEqual(state["recovery_authorization"]["user_reapproval_required"], False)
        self.assertNotIn("brain", state)
        self.assertNotIn("learning", state)
        self.assertNotIn("cross_run", state)

    def test_23_counted_interaction_record_is_immutable_and_separate_from_pattern(self):
        observed = self._observe(self._state(), "read_file", 1)
        interaction = observed["interaction"]
        self.assertEqual(
            interaction["artifact_type"],
            recovery.RECOVERY_NO_MUTATION_SEARCH_INTERACTION,
        )
        self.assertTrue(
            recovery.validate_recovery_no_mutation_search_interaction(interaction)[
                "valid"
            ]
        )
        with self.assertRaises(TypeError):
            interaction["tool_name"] = "edit_file"
        self.assertNotEqual(
            interaction["canonical_hash"], observed["pattern"]["canonical_hash"]
        )

    def test_24_dynamic_schema_mutation_mechanism_resets_the_window(self):
        custom_mutation = {
            "type": "function",
            "metadata": {"mutation": True, "requires_existing_target": True},
            "function": {
                "name": "apply_existing_edit",
                "description": "Apply a behavior-changing mutation to an existing file.",
            },
        }
        state = self._state(available_legal_mechanisms=["apply_existing_edit"])
        state["current_strategy"] = recovery.build_recovery_mutation_strategy(
            self.EXECUTION,
            target_path=self.TARGET,
            allowed_mutation_mechanisms=["apply_existing_edit"],
            source_subject_identity=self.SUBJECT,
        )
        for ordinal in range(1, 4):
            state = recovery.observe_recovery_no_mutation_search_interaction(
                state,
                tool_name="read_file",
                target_path=self.TARGET,
                subject_identity=self.SUBJECT,
                event_id=f"custom-read-{ordinal}",
                legal_mutation_mechanisms=["apply_existing_edit"],
                remaining_tool_steps=20,
                tool_steps_used=ordinal,
            )["state"]
        reset = recovery.observe_recovery_no_mutation_search_interaction(
            state,
            tool_name="apply_existing_edit",
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            legal_mutation_mechanisms=["apply_existing_edit"],
            mutation_attempt=None,
            remaining_tool_steps=20,
            tool_steps_used=4,
        )
        self.assertTrue(reset["reset"])
        self.assertEqual(reset["state"]["no_mutation_search_interaction_count"], 0)
        self.assertTrue(recovery.is_recovery_mutation_mechanism(custom_mutation))

    def test_25_explicit_v264_authority_block_does_not_reorient(self):
        state = self._state(
            recovery_authorization={
                "status": recovery.RECOVERY_AUTHORIZATION_BLOCKED,
                "authority_delta_empty": False,
                "user_reapproval_required": True,
            }
        )
        current = state
        for ordinal in range(1, 5):
            result = self._observe(current, "read_file", ordinal)
            current = result["state"]
        self.assertFalse(result["reoriented"])
        self.assertIn("authority_blocked", result["blockers"])
        self.assertEqual(current["mutation_path_reorientations_used"], 0)

    def test_26_subject_target_and_epoch_identity_windows_are_nonconflating(self):
        state = self._state()
        first = self._observe(state, "read_file", 1)
        target = self._observe(
            first["state"], "read_file", 2, target_path=self.OTHER_TARGET
        )
        subject = self._observe(
            target["state"], "read_file", 3,
            subject_identity=self.CHANGED_SUBJECT,
            subject_unchanged=False,
        )
        epoch = self._observe(
            subject["state"], "read_file", 4,
            strategy_epoch=1,
        )
        self.assertEqual(first["interaction_count"], 1)
        self.assertEqual(target["interaction_count"], 1)
        self.assertEqual(subject["interaction_count"], 1)
        self.assertEqual(epoch["interaction_count"], 1)
        self.assertFalse(target["reoriented"])
        self.assertFalse(subject["reoriented"])
        self.assertFalse(epoch["reoriented"])

    def test_27_execution_identity_and_authority_identity_do_not_leak_counts(self):
        state = self._state(authority_state_identity="AUTHORITY-A")
        first = self._observe(state, "read_file", 1)
        changed_execution = copy.deepcopy(first["state"])
        changed_execution["recovery_execution_id"] = "RECOVERY-EXEC-OTHER-R1"
        second = self._observe(changed_execution, "read_file", 2)
        changed_authority = copy.deepcopy(second["state"])
        changed_authority["authority_state_identity"] = "AUTHORITY-B"
        third = self._observe(changed_authority, "read_file", 3)
        self.assertEqual(second["interaction_count"], 1)
        self.assertEqual(third["interaction_count"], 1)
        self.assertFalse(third["reoriented"])

    def test_28_reorientation_event_binds_plan_approval_and_current_subject(self):
        state, _ = self._four_search_interactions(self._state())
        event = state["last_mutation_path_reorientation"]
        self.assertEqual(event["plan_hash"], self.AUTHORIZATION["plan_hash"])
        self.assertEqual(
            event["approval_receipt_hash"],
            self.AUTHORIZATION["approval_receipt_hash"],
        )
        self.assertEqual(event["subject_identity"], self.SUBJECT)
        self.assertEqual(event["strategy_epoch"], state["strategy_epoch"])
        self.assertEqual(event["strategy_switch_count"], state["strategy_switch_count"])

    def test_29_reorientation_state_validates_with_all_older_budgets_intact(self):
        state, _ = self._four_search_interactions(self._state())
        validation = recovery.validate_recovery_strategy_state(state)
        self.assertTrue(validation["valid"], validation["errors"])
        self.assertEqual(state["tool_contract_guidance_events_used"], 0)
        self.assertEqual(state["epoch_reanchors_used"], 0)
        self.assertEqual(state["completion_repairs_used"], 0)
        self.assertEqual(state["strategy_switch_count"], 0)
        self.assertEqual(state["mutation_path_reorientations_used"], 1)

    def test_30_reorientation_does_not_change_tool_projection_or_mission_packet(self):
        state = self._state()
        before = mini.tools_for_role("Builder", recovery_strategy=state)
        state, _ = self._four_search_interactions(state)
        after = mini.tools_for_role("Builder", recovery_strategy=state)
        self.assertEqual(before, after)
        self.assertEqual(state["recovery_mission_id"], self.MISSION)
        self.assertEqual(state["recovery_authorization"], self.AUTHORIZATION)
        self.assertEqual(state["target_path"], self.TARGET)

    def test_31_reorientation_to_v264_guidance_has_no_v266_competition(self):
        state, _ = self._four_search_interactions(self._state())
        ambiguous = "error: expected 1 exact replacement(s), found 2; file was not changed"
        first = recovery.observe_recovery_no_mutation_search_interaction(
            state,
            tool_name="edit_file",
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            mutation_attempt=True,
            remaining_tool_steps=18,
            tool_steps_used=6,
        )
        state = first["state"]
        self.assertEqual(state["no_mutation_search_interaction_count"], 0)
        v264 = recovery.observe_recovery_tool_contract_failure(
            state, tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        v264 = recovery.observe_recovery_tool_contract_failure(
            v264["state"], tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        self.assertTrue(v264["escalated"])
        self.assertEqual(v264["state"]["mutation_path_reorientations_used"], 1)
        self.assertEqual(v264["state"]["no_mutation_search_interaction_count"], 0)

    def test_32_reorientation_to_v263_switch_resets_epoch_local_counter(self):
        state, _ = self._four_search_interactions(self._state())
        state = recovery.observe_recovery_no_mutation_search_interaction(
            state,
            tool_name="edit_file_range",
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            mutation_attempt=True,
            remaining_tool_steps=18,
            tool_steps_used=6,
        )["state"]
        for _ in range(2):
            state = recovery.observe_recovery_mutation(
                state,
                target_path=self.TARGET,
                mutation_mechanism="edit_file_range",
                diagnostic="syntax-invalid",
                available_legal_mechanisms=self.LEGAL,
            )["state"]
        self.assertEqual(state["strategy_epoch"], 1)
        self.assertEqual(state["strategy_switch_count"], 1)
        self.assertEqual(state["mutation_path_reorientations_used"], 1)
        self.assertEqual(state["no_mutation_search_interaction_count"], 0)

    def test_33_exhaustion_is_explicitly_bounded_not_a_terminal_or_capability_floor(self):
        state, _ = self._four_search_interactions(self._state())
        current = state
        for ordinal in range(5, 9):
            current = self._observe(current, "read_file", ordinal)["state"]
        self.assertEqual(
            current["no_mutation_search_terminal_state"],
            recovery.RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED,
        )
        self.assertIsNone(current["terminal_state"])
        self.assertNotEqual(current["no_mutation_search_terminal_state"], recovery.CAPABILITY_FLOOR)
        self.assertNotEqual(current["no_mutation_search_terminal_state"], "TASK_TOO_BROAD")

    def test_34_provider_failure_and_harness_failure_never_look_like_active_search(self):
        for key, value in (("provider_healthy", False), ("provider_harness_blocked", True)):
            state = self._state(**{key: value})
            current = state
            for ordinal in range(1, 5):
                result = self._observe(current, "read_file", ordinal)
                current = result["state"]
            self.assertFalse(result["reoriented"])
            self.assertEqual(result["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_BLOCKED)
            self.assertEqual(current["no_mutation_search_interaction_count"], 0)

    def test_35_successful_and_failed_downstream_replays_remain_provider_free(self):
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        positive = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        negative = recovery.run_provider_free_recovery_replay(live3, outcome="failure")
        self.assertTrue(positive["stage5a"]["passed"])
        self.assertEqual(positive["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(positive["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(positive["reentry"]["status"], "REENTRY_READY")
        self.assertTrue(negative["brain_unchanged"])
        self.assertEqual(positive["gemma_calls"], 0)
        self.assertEqual(negative["real_worker_calls"], 0)

    def test_36_v265_failure_source_matrix_and_v264_budgets_are_not_changed(self):
        self.assertEqual(recovery.VERIFICATION_FAILURE, "VERIFICATION_FAILURE")
        self.assertEqual(recovery.WORKER_EXECUTION_FAILURE, "WORKER_EXECUTION_FAILURE")
        self.assertEqual(recovery.MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_EPOCH_REANCHORS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS, 1)
        self.assertEqual(recovery.RECOVERY_STRATEGY_STAGNATION_THRESHOLD, 2)
        self.assertEqual(recovery.MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS, 1)

    def test_37_historical_fixture_and_future_live_workspace_are_not_touched_or_created(self):
        historical = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v26-5-stage6c-b-pre-verification-recovery-live-1"
        )
        future_live = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v26-6-stage6c-b-no-mutation-recovery-live-1"
        )
        self.assertTrue(historical.is_dir())
        self.assertFalse(future_live.exists())
        self.assertFalse((historical / "marker.json").exists())

    def test_38_model_visible_context_has_no_private_transcript_or_exact_solution(self):
        state = self._state()
        state["obsolete_transcript"] = "PRIVATE OLD TRANSCRIPT"
        state, _ = self._four_search_interactions(state)
        context = state["last_mutation_path_reorientation_context"]
        for forbidden in (
            "PRIVATE OLD TRANSCRIPT", "renderPauseIndicator", "module.exports",
            "exact patch", "final implementation",
        ):
            self.assertNotIn(forbidden, context)
        self.assertIn("src/status_view.js", context)
        self.assertIn("edit_file", context)
        self.assertIn("Full verification", context)

    def test_39_initial_source_and_approval_facts_are_not_rewritten_by_reorientation(self):
        state = self._state()
        before = copy.deepcopy({
            "subject": state["current_subject_hash"],
            "target": state["target_path"],
            "auth": state["recovery_authorization"],
            "mission": state["recovery_mission_id"],
        })
        state, _ = self._four_search_interactions(state)
        self.assertEqual(state["current_subject_hash"], before["subject"])
        self.assertEqual(state["target_path"], before["target"])
        self.assertEqual(state["recovery_authorization"], before["auth"])
        self.assertEqual(state["recovery_mission_id"], before["mission"])

    def test_40_no_real_worker_or_gemma_accounting_is_possible_in_provider_free_api(self):
        state, _ = self._four_search_interactions(self._state())
        self.assertEqual(state["mutation_path_reorientations_used"], 1)
        self.assertEqual(mini.RUN.get("model_calls", 0), 0)
        self.assertEqual(mini.RUN.get("approved_worker_calls", 0), 0)


if __name__ == "__main__":
    unittest.main()
