import copy
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import recovery


class V267ProgressAwareCompletionRecoveryTests(unittest.TestCase):
    EXECUTION = "RECOVERY-EXEC-V267-TEST-R1"
    OTHER_EXECUTION = "RECOVERY-EXEC-V267-TEST-R2"
    MISSION = "MISSION-V267-TEST"
    TARGET = "src/status_view.js"
    OTHER_TARGET = "src/input.js"
    SUBJECT = "a" * 64
    CHANGED_SUBJECT = "b" * 64
    LEGAL = ["edit_file", "edit_file_range"]
    AUTHORIZATION = {
        "status": recovery.RECOVERY_AUTHORIZATION_READY,
        "authority_delta_empty": True,
        "user_reapproval_required": False,
        "authorization_id": "AUTH-V267-TEST",
        "authorization_hash": "c" * 64,
        "plan_hash": recovery.LIVE3_PLAN_HASH,
        "approval_receipt_hash": recovery.LIVE3_APPROVAL_RECEIPT_HASH,
    }

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
            progress_aware_completion=True,
        )
        state.update({
            "recovery_mission_unresolved": True,
            "provider_healthy": True,
            "provider_harness_blocked": False,
            "authority_unchanged": True,
            "scope_valid": True,
            "dnt_valid": True,
            "current_target_known": True,
            "worker_lifecycle_active": True,
            "completion_contract": recovery.build_recovery_completion_contract(),
        })
        state.update(overrides)
        return state

    @staticmethod
    def _schema(*names):
        wanted = {str(name) for name in names}
        return [
            copy.deepcopy(item)
            for item in mini.TOOLS
            if item["function"]["name"] in wanted
        ]

    def _progress(
        self,
        state,
        name,
        *,
        schema=None,
        suppressed=None,
        known=None,
        target=None,
        subject=None,
        event_id=None,
        **kwargs,
    ):
        schema = self._schema(
            "edit_file", "edit_file_range", "read_file", "read_file_range",
            "list_files", "run_file", "run_command", "verify_web_app",
        ) if schema is None else schema
        suppressed = list(suppressed or [])
        known = list(known if known is not None else self.LEGAL) + suppressed
        intent = recovery.classify_recovery_tool_intent(
            name,
            active_tool_schema=schema,
            suppressed_mutation_mechanisms=suppressed,
            known_mutation_mechanisms=known,
        )
        progress_kwargs = dict(kwargs)
        progress_kwargs.setdefault("target_path", target or self.TARGET)
        progress_kwargs.setdefault("subject_identity", subject or self.SUBJECT)
        return recovery.observe_recovery_completion_progress(
            state,
            tool_name=name,
            tool_intent=intent,
            active_tool_schema=schema,
            suppressed_mutation_mechanisms=suppressed,
            known_mutation_mechanisms=known,
            triggering_tool_event_id=event_id or f"{self.EXECUTION}:{name}:event",
            **progress_kwargs,
        )

    def _invalid_completion(self, state, remaining=17):
        return recovery.observe_recovery_completion_attempt(
            state,
            completion_payload={},
            required_completion_fields=[
                "verified_child_receipt",
                "worker_execution",
                "execution_verification_closure",
            ],
            required_coverage_ids=["NODE-002"],
            verification_handoff_ready=False,
            remaining_tool_steps=remaining,
            child_status="failed",
            completed=False,
            failure_type=recovery.WORKER_OUTPUT_INVALID,
        )

    def test_00_execute_loop_applies_both_repairs_to_the_same_worker(self):
        previous_run = mini.RUN
        previous_workspace = mini.WORKSPACE
        previous_memory = mini.MEMORY_STORE
        mini.RUN = mini.new_metrics("v26.7-execute-test")
        mini.WORKSPACE = None
        mini.MEMORY_STORE = None
        responses = [
            {"content": "premature completion"},
            {"tool_calls": [{"function": {"name": "edit_file", "arguments": {
                "path": self.TARGET, "old": "old", "new": "new",
            }}}]},
            {"content": "premature completion after mutation search"},
            {"content": "premature completion after second repair"},
        ]

        def ask(_messages, **_kwargs):
            return responses.pop(0)

        try:
            with patch.object(mini, "ask_ollama", side_effect=ask), patch.object(
                mini, "run_tool", return_value=(
                    "error: expected 1 exact replacement(s), found 2; "
                    "file was not changed"
                ),
            ):
                result = mini.execute_agent_task(
                    "Continue the bounded recovery mission",
                    {},
                    role="Builder",
                    task_id=self.EXECUTION,
                    recovery_strategy=self._state(),
                    worker_context="RECOVERY-MISSION-ID=MISSION-V267-TEST",
                    max_steps=8,
                )
        finally:
            mini.RUN = previous_run
            mini.WORKSPACE = previous_workspace
            mini.MEMORY_STORE = previous_memory
        self.assertEqual(
            result["failure_type"],
            recovery.RECOVERY_COMPLETION_REPAIR_TOTAL_BUDGET_EXHAUSTED,
        )
        self.assertEqual(len(result["recovery_completion_events"]), 2)
        self.assertEqual(len(result["recovery_completion_progress_events"]), 1)
        self.assertEqual(
            result["recovery_strategy_state"]["completion_progress_epoch"],
            "MUTATION_PATH_ENTERED",
        )
        self.assertEqual(
            result["recovery_strategy_state"]["completion_repairs_total"], 2
        )
        self.assertTrue(
            recovery.validate_recovery_strategy_state(
                result["recovery_strategy_state"]
            )["valid"]
        )

    def test_01_constants_and_initial_state_are_two_state_bounded(self):
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS_PER_PROGRESS_EPOCH, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS_TOTAL, 2)
        state = self._state()
        self.assertEqual(
            state["completion_progress_epoch"],
            recovery.RECOVERY_COMPLETION_PROGRESS_EPOCH_PRE_MUTATION,
        )
        self.assertEqual(state["completion_repairs_total"], 0)
        self.assertEqual(state["completion_repairs_used_in_progress_epoch"], 0)
        self.assertTrue(state["completion_progress_aware"])

    def test_02_progress_epoch_record_is_immutable_and_hash_bound(self):
        record = self._state()["completion_progress_epoch_record"]
        self.assertTrue(recovery.validate_recovery_completion_progress_epoch(record)["valid"])
        self.assertEqual(
            record["canonical_hash"],
            recovery.canonical_hash({
                key: value for key, value in record.items()
                if key != "canonical_hash"
            }),
        )
        with self.assertRaises(TypeError):
            record["progress_epoch"] = "MUTATION_PATH_ENTERED"

    def test_03_pre_mutation_completion_repair_one_is_allowed(self):
        observed = self._invalid_completion(self._state())
        self.assertTrue(observed["repair"])
        self.assertEqual(observed["progress_epoch"], "PRE_MUTATION")
        self.assertEqual(observed["state"]["completion_repairs_used"], 1)
        self.assertEqual(observed["state"]["completion_repairs_total"], 1)
        self.assertEqual(
            observed["state"]["completion_repairs_used_in_progress_epoch"], 1
        )
        self.assertTrue(recovery.validate_recovery_completion_repair_event(observed["event"])["valid"])

    def test_04_second_pre_mutation_completion_is_per_epoch_exhausted(self):
        first = self._invalid_completion(self._state())
        second = self._invalid_completion(first["state"], remaining=15)
        self.assertFalse(second["repair"])
        self.assertEqual(
            second["status"],
            recovery.RECOVERY_COMPLETION_REPAIR_PROGRESS_EPOCH_EXHAUSTED,
        )
        self.assertEqual(second["state"]["completion_repairs_total"], 1)
        self.assertNotEqual(
            second["status"], recovery.RECOVERY_COMPLETION_REPAIR_TOTAL_BUDGET_EXHAUSTED
        )

    def test_05_active_edit_file_is_authoritative_progress_boundary(self):
        observed = self._progress(self._state(), "edit_file", event_id="tool-edit-1")
        self.assertTrue(observed["transitioned"])
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION)
        self.assertEqual(observed["state"]["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(observed["event"]["tool"], "edit_file")
        self.assertEqual(observed["event"]["triggering_tool_event_id"], "tool-edit-1")
        self.assertEqual(observed["state"]["completion_repairs_used_in_progress_epoch"], 0)

    def test_06_active_edit_file_range_is_authoritative_progress_boundary(self):
        observed = self._progress(self._state(), "edit_file_range")
        self.assertTrue(observed["transitioned"])
        self.assertEqual(
            observed["state"]["completion_progress_epoch"],
            recovery.RECOVERY_COMPLETION_PROGRESS_EPOCH_MUTATION_PATH_ENTERED,
        )

    def test_07_ambiguity_syntax_and_v255_failures_still_advance_once(self):
        for diagnostic in ("EDIT_EXACT_MATCH_AMBIGUOUS", "SYNTAX_INVALID_MUTATION", "V25.5 rejected"):
            with self.subTest(diagnostic=diagnostic):
                state = self._state()
                observed = self._progress(state, "edit_file")
                self.assertTrue(observed["transitioned"])
                self.assertEqual(observed["state"]["completion_progress_transition_count"], 1)
                self.assertEqual(observed["state"]["completion_progress_epoch"], "MUTATION_PATH_ENTERED")

    def test_08_unavailable_write_file_does_not_advance_or_reset_progress(self):
        first = self._progress(self._state(), "read_file")
        unavailable_schema = self._schema(
            "edit_file", "edit_file_range", "read_file", "read_file_range",
            "list_files", "run_file", "run_command", "verify_web_app",
        )
        observed = self._progress(
            first["state"], "write_file", schema=unavailable_schema,
            event_id="tool-write-file-unavailable",
        )
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE)
        self.assertFalse(observed["recognized_mutation_path"])
        self.assertFalse(observed["transitioned"])
        self.assertEqual(observed["state"]["completion_progress_epoch"], "PRE_MUTATION")
        self.assertEqual(observed["state"]["completion_progress_transition_count"], 0)

    def test_08b_active_schema_rejects_stale_static_mutation_intent(self):
        observed = recovery.observe_recovery_completion_progress(
            self._state(),
            tool_name="write_file",
            tool_intent=recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
            active_tool_schema=self._schema("edit_file", "edit_file_range", "read_file"),
            known_mutation_mechanisms=["write_file", "edit_file", "edit_file_range"],
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            triggering_tool_event_id="stale-static-intent",
        )
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE)
        self.assertFalse(observed["transitioned"])
        self.assertEqual(observed["state"]["completion_progress_epoch"], "PRE_MUTATION")

    def test_08c_missing_active_schema_fails_closed_even_with_intent_label(self):
        observed = recovery.observe_recovery_completion_progress(
            self._state(),
            tool_name="edit_file",
            tool_intent=recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
        )
        self.assertEqual(observed["reason"], "active_tool_schema_unknown")
        self.assertFalse(observed["transitioned"])

    def test_09_unknown_tool_does_not_advance_progress(self):
        observed = self._progress(self._state(), "totally_unknown_tool")
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE)
        self.assertFalse(observed["transitioned"])
        self.assertEqual(observed["state"]["completion_progress_epoch"], "PRE_MUTATION")

    def test_10_non_mutation_tools_and_runtime_silence_do_not_advance_progress(self):
        state = self._state()
        for name in ("read_file", "list_files", "run_file", "read_file_range", "run_command", "verify_web_app"):
            observed = self._progress(state, name)
            self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_ACTIVE_NON_MUTATION)
            self.assertFalse(observed["transitioned"])
            state = observed["state"]
        self.assertEqual(state["completion_progress_epoch"], "PRE_MUTATION")
        self.assertEqual(
            self._progress(state, "", schema=[])["reason"],
            "unavailable_or_unknown_tool",
        )

    def test_11_active_schema_write_file_is_mutation_when_authorized(self):
        schema = self._schema("write_file", "edit_file", "edit_file_range")
        observed = self._progress(
            self._state(), "write_file", schema=schema,
            known=["write_file", "edit_file", "edit_file_range"],
        )
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION)
        self.assertTrue(observed["transitioned"])

    def test_12_suppressed_known_mutation_advances_and_routes_to_v264(self):
        state = self._state(suppressed_mutation_mechanisms=["edit_file"])
        state["current_strategy"] = recovery.build_recovery_mutation_strategy(
            self.EXECUTION,
            strategy_epoch=0,
            target_path=self.TARGET,
            allowed_mutation_mechanisms=["edit_file_range"],
            suppressed_mutation_mechanisms=["edit_file"],
            source_subject_identity=self.SUBJECT,
            recovery_authorization=self.AUTHORIZATION,
        )
        schema = self._schema("edit_file_range", "read_file", "list_files")
        observed = self._progress(
            state, "edit_file", schema=schema,
            suppressed=["edit_file"],
            known=["edit_file", "edit_file_range"],
        )
        self.assertEqual(observed["intent"], recovery.RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION)
        self.assertTrue(observed["transitioned"])
        suppressed = recovery.observe_suppressed_strategy_tool_request(
            observed["state"],
            requested_tool="edit_file",
            target_path=self.TARGET,
            active_legal_mutation_mechanisms=["edit_file_range"],
            subject_identity=self.SUBJECT,
        )
        self.assertTrue(suppressed["recognized"])
        self.assertEqual(suppressed["status"], recovery.SUPPRESSED_STRATEGY_TOOL_REQUESTED)
        self.assertEqual(suppressed["state"]["completion_progress_epoch"], "MUTATION_PATH_ENTERED")

    def test_13_v266_search_observer_keeps_unavailable_tool_uncounted(self):
        state = self._state()
        for index, name in enumerate(("read_file", "list_files", "read_file"), 1):
            state = recovery.observe_recovery_no_mutation_search_interaction(
                state,
                tool_name=name,
                target_path=self.TARGET,
                subject_identity=self.SUBJECT,
                event_id=f"search-{index}",
                recognized_tool=True,
                mutation_attempt=False,
                legal_mutation_mechanisms=self.LEGAL,
                remaining_tool_steps=20,
                tool_steps_used=index,
            )["state"]
        before = state["no_mutation_search_interaction_count"]
        observed = recovery.observe_recovery_no_mutation_search_interaction(
            state,
            tool_name="write_file",
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
            event_id="search-write-unavailable",
            recognized_tool=False,
            mutation_attempt=False,
            legal_mutation_mechanisms=self.LEGAL,
            remaining_tool_steps=19,
            tool_steps_used=4,
        )
        self.assertEqual(observed["state"]["no_mutation_search_interaction_count"], before)
        self.assertEqual(observed["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED)

    def test_14_completion_progress_does_not_create_third_epoch(self):
        state = self._state()
        state = self._progress(state, "edit_file")["state"]
        for name in ("edit_file", "edit_file_range", "read_file", "list_files"):
            state = self._progress(state, name)["state"]
        self.assertEqual(state["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(state["completion_progress_transition_count"], 1)
        self.assertEqual(len(state["completion_progress_transition_events"]), 1)

    def test_15_completion_repair_two_is_allowed_only_after_real_progress(self):
        first = self._invalid_completion(self._state(), remaining=17)
        transitioned = self._progress(first["state"], "edit_file", event_id="generation-18-edit")
        second = self._invalid_completion(transitioned["state"], remaining=7)
        self.assertTrue(second["repair"])
        self.assertEqual(second["event"]["repair_ordinal"], 2)
        self.assertEqual(second["event"]["progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(second["event"]["total_repairs_before"], 1)
        self.assertEqual(second["event"]["total_repairs_after"], 2)
        self.assertEqual(second["state"]["completion_repairs_total"], 2)
        self.assertEqual(second["state"]["completion_repairs_used_in_progress_epoch"], 1)
        self.assertTrue(recovery.validate_recovery_completion_repair_event(second["event"])["valid"])

    def test_16_third_invalid_completion_is_global_total_exhaustion(self):
        first = self._invalid_completion(self._state())
        progressed = self._progress(first["state"], "edit_file")["state"]
        second = self._invalid_completion(progressed)
        third = self._invalid_completion(second["state"])
        self.assertFalse(third["repair"])
        self.assertEqual(third["status"], recovery.RECOVERY_COMPLETION_REPAIR_TOTAL_BUDGET_EXHAUSTED)
        self.assertEqual(third["state"]["completion_repairs_total"], 2)
        self.assertEqual(third["repair_denial_reason"], "global_completion_repair_budget_exhausted")

    def test_17_progress_transition_and_repairs_bind_same_worker_authority(self):
        first = self._invalid_completion(self._state())
        transitioned = self._progress(first["state"], "edit_file", event_id="mutation-seam")
        second = self._invalid_completion(transitioned["state"])
        self.assertEqual(second["state"]["recovery_execution_id"], self.EXECUTION)
        self.assertEqual(second["state"]["recovery_mission_id"], self.MISSION)
        self.assertEqual(second["state"]["recovery_authorization"], self.AUTHORIZATION)
        self.assertEqual(second["event"]["recovery_execution_id"], self.EXECUTION)
        self.assertEqual(second["event"]["recovery_authorization_id"], self.AUTHORIZATION["authorization_id"])
        self.assertEqual(second["state"]["target_path"], self.TARGET)
        self.assertEqual(second["state"]["current_subject_hash"], self.SUBJECT)
        self.assertFalse(second["state"]["recovery_authorization"]["user_reapproval_required"])

    def test_18_repair_feedback_is_bounded_non_authoritative_and_patch_free(self):
        observed = self._invalid_completion(self._state())
        feedback = observed["feedback"]
        self.assertLessEqual(len(feedback), 1500)
        self.assertIn("Continue the SAME RecoveryMission", feedback)
        self.assertIn("PRE_MUTATION", feedback)
        self.assertNotIn("renderPauseIndicator", feedback)
        self.assertNotIn("module.exports", feedback)
        self.assertTrue(observed["event"]["worker_self_report_non_authoritative"])
        self.assertEqual(observed["event"]["worker_prose_authority"], 0)
        self.assertFalse(observed["event"]["verification_handoff_ready"])

    def test_19_reads_empty_response_prose_and_completion_do_not_open_epoch(self):
        state = self._state()
        for name in ("read_file", "list_files", "run_file", ""):
            state = self._progress(state, name, schema=[] if not name else None)["state"]
        self.assertEqual(state["completion_progress_epoch"], "PRE_MUTATION")
        self.assertEqual(state["completion_progress_transition_count"], 0)
        repaired = self._invalid_completion(state)
        self.assertEqual(repaired["state"]["completion_progress_epoch"], "PRE_MUTATION")
        self.assertTrue(repaired["repair"])

    def test_20_strategy_switch_and_epoch_reanchor_do_not_reset_repair_total(self):
        first = self._invalid_completion(self._state())
        state = self._progress(first["state"], "edit_file")["state"]
        total = state["completion_repairs_total"]
        for _ in range(2):
            state = recovery.observe_recovery_mutation(
                state,
                target_path=self.TARGET,
                mutation_mechanism="edit_file",
                diagnostic="syntax-invalid candidate",
                available_legal_mechanisms=self.LEGAL,
            )["state"]
        self.assertEqual(state["strategy_switch_count"], 1)
        self.assertEqual(state["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(state["completion_repairs_total"], total)
        state["suppressed_mutation_mechanisms"] = ["edit_file"]
        reanchored = recovery.observe_suppressed_strategy_tool_request(
            state,
            requested_tool="edit_file",
            target_path=self.TARGET,
            active_legal_mutation_mechanisms=["edit_file_range"],
            subject_identity=self.SUBJECT,
        )
        self.assertEqual(reanchored["state"]["completion_repairs_total"], total)

    def test_21_v266_reorientation_does_not_advance_completion_progress(self):
        state = self._state()
        for index in range(1, 5):
            observed = recovery.observe_recovery_no_mutation_search_interaction(
                state,
                tool_name="read_file",
                target_path=self.TARGET,
                subject_identity=self.SUBJECT,
                event_id=f"search-{index}",
                recognized_tool=True,
                mutation_attempt=False,
                legal_mutation_mechanisms=self.LEGAL,
                remaining_tool_steps=20,
                tool_steps_used=index,
            )
            state = observed["state"]
        self.assertTrue(observed["reoriented"])
        self.assertEqual(state["completion_progress_epoch"], "PRE_MUTATION")
        self.assertEqual(state["completion_repairs_total"], 0)

    def test_22_low_budget_blocks_completion_repair_even_with_epoch_quota(self):
        observed = self._invalid_completion(self._state(), remaining=0)
        self.assertFalse(observed["repair"])
        self.assertEqual(observed["status"], recovery.WORKER_OUTPUT_INVALID)
        self.assertEqual(observed["repair_denial_reason"], "insufficient_remaining_tool_steps")
        self.assertEqual(observed["state"]["completion_repairs_total"], 0)

    def test_23_subject_target_and_execution_changes_do_not_advance_stale_epoch(self):
        for kwargs in (
            {"subject_identity": self.CHANGED_SUBJECT, "subject_unchanged": False},
            {"target_path": self.OTHER_TARGET},
        ):
            observed = self._progress(self._state(), "edit_file", **kwargs)
            self.assertFalse(observed["transitioned"], kwargs)
            self.assertEqual(observed["state"]["completion_progress_epoch"], "PRE_MUTATION")
        state = self._state()
        state["recovery_execution_id"] = self.OTHER_EXECUTION
        observed = self._progress(state, "edit_file")
        self.assertTrue(observed["transitioned"])
        self.assertEqual(observed["event"]["recovery_execution_id"], self.OTHER_EXECUTION)

    def test_24_progress_state_is_execution_local_and_new_worker_starts_fresh(self):
        first = self._progress(self._state(), "edit_file")["state"]
        self.assertEqual(first["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        fresh = self._state()
        fresh["recovery_execution_id"] = self.OTHER_EXECUTION
        fresh["completion_progress_epoch_record"] = recovery.build_recovery_completion_progress_epoch(
            self.OTHER_EXECUTION,
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
        )
        self.assertEqual(fresh["completion_progress_epoch"], "PRE_MUTATION")
        self.assertEqual(fresh["completion_repairs_total"], 0)

    def test_25_progress_projection_exposes_epoch_transition_and_budget(self):
        first = self._invalid_completion(self._state())
        state = self._progress(first["state"], "edit_file")["state"]
        projection = recovery.recovery_strategy_state_projection(state)
        self.assertEqual(projection["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(projection["completion_repairs_total"], 1)
        self.assertEqual(projection["completion_repairs_used_in_progress_epoch"], 0)
        self.assertEqual(projection["completion_progress_transition_count"], 1)
        self.assertEqual(len(projection["completion_progress_transition_events"]), 1)

    def test_26_state_validation_rejects_third_epoch_or_budget_overrun(self):
        state = self._state()
        state["completion_progress_epoch"] = "PROGRESS_EPOCH_2"
        self.assertFalse(recovery.validate_recovery_strategy_state(state)["valid"])
        state = self._state()
        state["completion_repairs_total"] = 3
        state["completion_repairs_used"] = 3
        self.assertFalse(recovery.validate_recovery_strategy_state(state)["valid"])
        state = self._state()
        state["completion_progress_epoch"] = "MUTATION_PATH_ENTERED"
        state["completion_progress_epoch_record"] = recovery.build_recovery_completion_progress_epoch(
            self.EXECUTION,
            progress_epoch="MUTATION_PATH_ENTERED",
            recognized_mutation_mechanism="edit_file",
            target_path=self.TARGET,
            subject_identity=self.SUBJECT,
        )
        self.assertFalse(recovery.validate_recovery_strategy_state(state)["valid"])
        self.assertEqual(
            recovery.initialize_recovery_completion_progress_state(
                state, target_path=self.TARGET, subject_identity=self.SUBJECT
            )["completion_progress_epoch"],
            "PRE_MUTATION",
        )

    def test_27_suppressed_progress_does_not_create_duplicate_completion_transition(self):
        state = self._state(suppressed_mutation_mechanisms=["edit_file"])
        schema = self._schema("edit_file_range", "read_file")
        first = self._progress(
            state, "edit_file", schema=schema, suppressed=["edit_file"],
            known=["edit_file", "edit_file_range"],
        )
        second = self._progress(
            first["state"], "edit_file", schema=schema, suppressed=["edit_file"],
            known=["edit_file", "edit_file_range"],
        )
        self.assertTrue(first["transitioned"])
        self.assertFalse(second["transitioned"])
        self.assertEqual(second["state"]["completion_progress_transition_count"], 1)

    def test_28_v264_ambiguity_owns_active_mutation_after_progress(self):
        state = self._progress(self._state(), "edit_file")["state"]
        ambiguous = "error: expected 1 exact replacement(s), found 2; file was not changed"
        first = recovery.observe_recovery_tool_contract_failure(
            state,
            tool="edit_file",
            target_path=self.TARGET,
            result=ambiguous,
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"],
            tool="edit_file",
            target_path=self.TARGET,
            result=ambiguous,
        )
        self.assertTrue(second["escalated"])
        self.assertEqual(second["state"]["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(second["state"]["mutation_path_reorientations_used"], 0)

    def test_29_v263_switch_composes_without_new_completion_epoch(self):
        state = self._progress(self._state(), "edit_file")["state"]
        for _ in range(2):
            state = recovery.observe_recovery_mutation(
                state,
                target_path=self.TARGET,
                mutation_mechanism="edit_file",
                diagnostic="syntax-invalid candidate",
                available_legal_mechanisms=self.LEGAL,
            )["state"]
        self.assertEqual(state["strategy_epoch"], 1)
        self.assertEqual(state["strategy_switch_count"], 1)
        self.assertEqual(state["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(state["completion_progress_transition_count"], 1)

    def test_30_provider_free_full_continuation_reaches_promotion_and_reentry(self):
        first = self._invalid_completion(self._state())
        progressed = self._progress(first["state"], "edit_file")["state"]
        second = self._invalid_completion(progressed)
        self.assertTrue(second["repair"])
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        replay = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        self.assertEqual(replay["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(replay["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(replay["reentry"]["status"], "REENTRY_READY")
        self.assertEqual(replay["gemma_calls"], 0)
        self.assertEqual(replay["real_worker_calls"], 0)

    def test_31_provider_free_no_model_calls_or_live_artifacts(self):
        with patch.object(mini, "ask_ollama") as ask:
            first = self._invalid_completion(self._state())
            self._progress(first["state"], "edit_file")
            ask.assert_not_called()
        self.assertFalse(
            (Path(r"D:\projects\Ai\mini_hivo\output") / "hivo-v26-7-stage6c-b-progress-aware-completion-live-1").exists()
        )

    def test_32_all_frozen_budgets_and_failure_sources_remain_unchanged(self):
        self.assertEqual(recovery.MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_STRATEGY_SWITCHES, 1)
        self.assertEqual(recovery.MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_EPOCH_REANCHORS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION, 4)
        self.assertEqual(recovery.MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION, 3)
        self.assertEqual(recovery.MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS, 1)
        self.assertEqual(recovery.RECOVERY_STRATEGY_STAGNATION_THRESHOLD, 2)
        self.assertEqual(recovery.VERIFICATION_FAILURE, "VERIFICATION_FAILURE")
        self.assertEqual(recovery.WORKER_EXECUTION_FAILURE, "WORKER_EXECUTION_FAILURE")
        self.assertEqual(recovery.LIVE3_INVARIANT_HASH, "257c9d474539fdc74cfb7a6ca088bdf3431013f8e844af45c6d9e95bb7f73424")
        self.assertEqual(recovery.LIVE3_VERIFICATION_DIGEST, "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51")

    def test_33_completion_repair_legacy_state_retains_one_repair(self):
        state = {
            "recovery_execution_id": "LEGACY-V264",
            "completion_repairs_used": 0,
        }
        first = self._invalid_completion(state, remaining=5)
        second = self._invalid_completion(first["state"], remaining=4)
        self.assertTrue(first["repair"])
        self.assertFalse(second["repair"])
        self.assertEqual(second["status"], recovery.RECOVERY_COMPLETION_REPAIR_BUDGET_EXHAUSTED)

    def test_33b_legacy_repair_is_not_reopened_by_v267_opt_in_without_progress(self):
        state = self._state(completion_repairs_used=1, completion_repairs_total=1)
        state["completion_progress_epoch_record"] = None
        state = recovery.initialize_recovery_completion_progress_state(
            state, target_path=self.TARGET, subject_identity=self.SUBJECT
        )
        observed = self._invalid_completion(state, remaining=5)
        self.assertFalse(observed["repair"])
        self.assertEqual(
            observed["status"],
            recovery.RECOVERY_COMPLETION_REPAIR_PROGRESS_EPOCH_EXHAUSTED,
        )

    def test_34_failed_provider_and_authority_do_not_fabricate_progress(self):
        for overrides in (
            {"provider_healthy": False},
            {"provider_harness_blocked": True},
            {"authority_unchanged": False},
            {"scope_valid": False},
            {"dnt_valid": False},
            {"recovery_mission_unresolved": False},
        ):
            with self.subTest(overrides=overrides):
                observed = self._progress(self._state(**overrides), "edit_file")
                self.assertFalse(observed["transitioned"])
                self.assertEqual(observed["state"]["completion_progress_epoch"], "PRE_MUTATION")

    def test_35_commit_and_subject_change_are_evidence_not_new_progress_epochs(self):
        state = self._progress(self._state(), "edit_file")["state"]
        state = recovery.observe_recovery_mutation(
            state,
            target_path=self.TARGET,
            mutation_mechanism="edit_file",
            failure_class="MUTATION_COMMITTED",
            diagnostic="candidate committed",
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.CHANGED_SUBJECT,
            subject_unchanged=False,
            committed=True,
            commit_count=1,
            available_legal_mechanisms=self.LEGAL,
        )["state"]
        self.assertEqual(state["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(state["completion_progress_transition_count"], 1)

    def test_36_historical_equivalent_completion_sequence_has_exact_bounded_accounting(self):
        state = self._state()
        first = self._invalid_completion(state, remaining=17)
        self.assertTrue(first["repair"])
        for name in ("read_file", "list_files"):
            state = self._progress(first["state"], name)["state"]
        unavailable = self._progress(
            state,
            "write_file",
            schema=self._schema("edit_file", "edit_file_range", "read_file", "list_files"),
        )
        self.assertEqual(unavailable["intent"], recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE)
        transitioned = self._progress(unavailable["state"], "edit_file", event_id="generation-18-edit")
        second = self._invalid_completion(transitioned["state"], remaining=7)
        self.assertEqual(second["state"]["completion_progress_epoch"], "MUTATION_PATH_ENTERED")
        self.assertEqual(second["state"]["completion_repairs_total"], 2)
        self.assertEqual(len(second["state"]["completion_repair_events"]), 2)
        self.assertEqual(second["event"]["progress_evidence_hash"], transitioned["state"]["completion_progress_epoch_record"]["canonical_hash"])


if __name__ == "__main__":
    unittest.main()
