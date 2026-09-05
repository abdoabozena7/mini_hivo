"""Provider-free V26.4 bounded tool-contract recovery tests."""

from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import recovery


class V264ToolContractRecoveryTests(unittest.TestCase):
    SUBJECT = "a" * 64
    CHANGED_SUBJECT = "b" * 64
    TARGET = "src/status_view.js"
    OTHER_TARGET = "src/input.js"
    AMBIGUOUS = (
        "error: expected 1 exact replacement(s), found 2; "
        "file was not changed"
    )

    def setUp(self):
        self._run = mini.RUN
        self._workspace = mini.WORKSPACE
        self._memory_store = mini.MEMORY_STORE
        mini.RUN = mini.new_metrics("v26.4-test")
        mini.WORKSPACE = None
        mini.MEMORY_STORE = None

    def tearDown(self):
        mini.RUN = self._run
        mini.WORKSPACE = self._workspace
        mini.MEMORY_STORE = self._memory_store

    def _state(self, **overrides):
        authorization = {
            "status": recovery.RECOVERY_AUTHORIZATION_READY,
            "authority_delta_empty": True,
            "user_reapproval_required": False,
            "authorization_id": "RECOVERY-AUTH-V264-TEST",
            "authorization_hash": "b" * 64,
            "plan_hash": recovery.LIVE3_PLAN_HASH,
            "approval_receipt_hash": recovery.LIVE3_APPROVAL_RECEIPT_HASH,
        }
        state = recovery.create_recovery_strategy_state(
            "RECOVERY-EXEC-V264-TEST-R1",
            target_path=self.TARGET,
            tool_schemas=mini.TOOLS,
            target_state={"exists": True, "protected": True},
            current_subject_hash=self.SUBJECT,
            recovery_authorization=authorization,
            lineage={
                "status": recovery.AUTHORIZED_EXECUTION_DESCENDANT,
                "valid": True,
            },
        )
        state.update(overrides)
        return state

    def _epoch_one_state(self):
        state = self._state()
        for _ in range(2):
            state = recovery.observe_recovery_mutation(
                state,
                target_path=self.TARGET,
                mutation_mechanism="edit_file_range",
                diagnostic="syntax-invalid candidate",
                tool_schemas=mini.TOOLS,
            )["state"]
        return state

    def test_01_generic_ambiguity_classifier_is_fixture_independent(self):
        parsed = recovery.classify_edit_exact_match_ambiguity(self.AMBIGUOUS)
        self.assertEqual(parsed["failure_class"], recovery.EDIT_EXACT_MATCH_AMBIGUOUS)
        self.assertEqual(parsed["expected_replacements"], 1)
        self.assertEqual(parsed["actual_matches"], 2)
        self.assertIsNone(
            recovery.classify_edit_exact_match_ambiguity(
                "error: expected 1 exact replacement(s), found 1"
            )
        )
        self.assertIsNone(
            recovery.classify_edit_exact_match_ambiguity(
                "error: exact text not found"
            )
        )

    def test_02_pattern_is_immutable_and_valid(self):
        pattern = recovery.build_recovery_tool_contract_failure_pattern(
            "RECOVERY-EXEC-V264-TEST-R1",
            strategy_epoch=1,
            tool="edit_file",
            target_path=self.TARGET,
            expected_replacements=1,
            actual_matches=2,
            failure_count=1,
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.SUBJECT,
            subject_unchanged=True,
            active_tool_schema_hash="c" * 64,
            deterministic_diagnostic=self.AMBIGUOUS,
        )
        self.assertTrue(
            recovery.validate_recovery_tool_contract_failure_pattern(pattern)[
                "valid"
            ]
        )
        with self.assertRaises(TypeError):
            pattern["failure_count"] = 2

    def test_02a_real_edit_file_ambiguity_is_precommit_and_non_mutating(self):
        with tempfile.TemporaryDirectory(prefix="hivo_v264_edit_contract_") as root:
            mini.WORKSPACE = Path(root)
            target = Path(root) / self.TARGET
            target.parent.mkdir(parents=True, exist_ok=True)
            original = "const value = 1;\nconst value = 1;\n"
            target.write_text(original, encoding="utf-8")
            result = mini.edit_file(self.TARGET, "const value = 1;", "const value = 2;")
            self.assertIn("expected 1 exact replacement(s), found 2", result)
            self.assertEqual(target.read_text(encoding="utf-8"), original)
            parsed = recovery.classify_edit_exact_match_ambiguity(result)
            self.assertEqual(parsed["failure_class"], recovery.EDIT_EXACT_MATCH_AMBIGUOUS)
            self.assertFalse(parsed["commit"])
            self.assertFalse(parsed["filesystem_changed"])

    def test_03_first_ambiguity_is_feedback_only(self):
        observed = recovery.observe_recovery_tool_contract_failure(
            self._epoch_one_state(),
            tool="edit_file",
            target_path=self.TARGET,
            result=self.AMBIGUOUS,
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.SUBJECT,
            active_legal_mutation_mechanisms=["edit_file"],
        )
        self.assertEqual(observed["status"], recovery.TOOL_CONTRACT_FEEDBACK_ONLY)
        self.assertFalse(observed["escalated"])
        self.assertEqual(observed["failure_count"], 1)
        self.assertIsNone(observed["guidance_event"])
        self.assertEqual(observed["pattern"]["expected_replacements"], 1)
        self.assertEqual(observed["pattern"]["actual_matches"], 2)

    def test_03a_unrelated_tool_error_does_not_become_contract_ambiguity(self):
        observed = recovery.observe_recovery_tool_contract_failure(
            self._epoch_one_state(),
            tool="edit_file",
            target_path=self.TARGET,
            result="error: exact text was not found; file was not changed",
        )
        self.assertFalse(observed["recognized"])
        self.assertIsNone(observed["pattern"])

    def test_04_second_identical_ambiguity_escalates_once(self):
        state = self._epoch_one_state()
        first = recovery.observe_recovery_tool_contract_failure(
            state,
            result=self.AMBIGUOUS,
            target_path=self.TARGET,
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.SUBJECT,
            active_legal_mutation_mechanisms=["edit_file"],
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"],
            result=self.AMBIGUOUS,
            target_path=self.TARGET,
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.SUBJECT,
            active_legal_mutation_mechanisms=["edit_file"],
        )
        self.assertEqual(
            second["status"], recovery.TOOL_CONTRACT_STAGNATION_DETECTED
        )
        self.assertTrue(second["escalated"])
        self.assertEqual(
            second["state"]["tool_contract_guidance_events_used"], 1
        )
        guidance = second["guidance"]
        self.assertIn("matched 2 locations", guidance)
        self.assertIn("exactly 1 replacement", guidance)
        self.assertIn("filesystem was unchanged", guidance)
        self.assertIn("uniquely identifying old fragment", guidance)
        self.assertNotIn("renderPauseIndicator", guidance)
        self.assertNotIn("module.exports", guidance)
        self.assertTrue(
            recovery.validate_recovery_tool_contract_guidance_event(
                second["guidance_event"]
            )["valid"]
        )

    def test_05_guidance_budget_is_bounded_and_filesystem_fact_is_preserved(self):
        state = self._epoch_one_state()
        first = recovery.observe_recovery_tool_contract_failure(
            state, result=self.AMBIGUOUS, target_path=self.TARGET
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"], result=self.AMBIGUOUS, target_path=self.TARGET
        )
        third = recovery.observe_recovery_tool_contract_failure(
            second["state"], result=self.AMBIGUOUS, target_path=self.TARGET
        )
        self.assertEqual(
            third["status"], recovery.TOOL_CONTRACT_GUIDANCE_BUDGET_EXHAUSTED
        )
        self.assertFalse(third["escalated"])
        self.assertEqual(third["state"]["tool_contract_guidance_events_used"], 1)
        self.assertFalse(third["pattern"]["commit_count"])

    def test_06_contract_failure_resets_on_tool_target_class_subject_and_commit(self):
        state = self._epoch_one_state()
        first = recovery.observe_recovery_tool_contract_failure(
            state, result=self.AMBIGUOUS, target_path=self.TARGET
        )
        target_change = recovery.observe_recovery_tool_contract_failure(
            first["state"], result=self.AMBIGUOUS, target_path=self.OTHER_TARGET
        )
        tool_change = recovery.observe_recovery_tool_contract_failure(
            target_change["state"],
            tool="edit_file_range",
            target_path=self.TARGET,
            result="error: invalid line range",
            failure_class="INVALID_LINE_RANGE",
            normalized_error_class="INVALID_LINE_RANGE",
        )
        subject_change = recovery.observe_recovery_tool_contract_failure(
            tool_change["state"],
            result=self.AMBIGUOUS,
            target_path=self.TARGET,
            subject_identity_before=self.SUBJECT,
            subject_identity_after=self.CHANGED_SUBJECT,
            subject_unchanged=False,
        )
        committed = recovery.observe_recovery_tool_contract_failure(
            subject_change["state"],
            result="edited file",
            target_path=self.TARGET,
            commit_count=1,
        )
        for observed in (target_change, tool_change, subject_change):
            self.assertEqual(observed["failure_count"], 1)
        self.assertEqual(committed["state"]["tool_contract_failure_count"], 0)
        self.assertIsNone(committed["state"]["last_tool_contract_failure_key"])

    def test_06a_reset_helper_breaks_nonconsecutive_ambiguity_sequence(self):
        state = self._epoch_one_state()
        first = recovery.observe_recovery_tool_contract_failure(
            state, result=self.AMBIGUOUS, target_path=self.TARGET
        )
        reset = recovery.reset_recovery_tool_contract_failure_pattern(first["state"])
        self.assertEqual(reset["tool_contract_failure_count"], 0)
        self.assertIsNone(reset["last_tool_contract_failure_key"])
        next_failure = recovery.observe_recovery_tool_contract_failure(
            reset, result=self.AMBIGUOUS, target_path=self.TARGET
        )
        self.assertEqual(next_failure["failure_count"], 1)
        self.assertFalse(next_failure["escalated"])

    def test_07_suppressed_tool_is_distinct_from_unknown_tool(self):
        state = self._epoch_one_state()
        unknown = recovery.observe_suppressed_strategy_tool_request(
            state, requested_tool="unknown_tool", target_path=self.TARGET
        )
        self.assertFalse(unknown["recognized"])
        self.assertFalse(unknown["reanchored"])
        suppressed = recovery.observe_suppressed_strategy_tool_request(
            state, requested_tool="edit_file_range", target_path=self.TARGET
        )
        self.assertTrue(suppressed["recognized"])
        self.assertEqual(
            suppressed["status"], recovery.SUPPRESSED_STRATEGY_TOOL_REQUESTED
        )
        self.assertIn("prior epoch", suppressed["feedback"])
        self.assertIn("edit_file", suppressed["feedback"])

    def test_08_repeated_suppressed_tool_triggers_one_same_worker_reanchor(self):
        state = self._epoch_one_state()
        state["recovery_mission_id"] = "MISSION-V264-TEST"
        state["obsolete_transcript"] = "PRIVATE OLD TRANSCRIPT"
        first = recovery.observe_suppressed_strategy_tool_request(
            state,
            requested_tool="edit_file_range",
            target_path=self.TARGET,
            active_tool_schema_hash="d" * 64,
            active_legal_mutation_mechanisms=["edit_file"],
            base_context="bounded mission anchor",
            latest_feedback="tool unavailable",
            remaining_tool_steps=10,
        )
        second = recovery.observe_suppressed_strategy_tool_request(
            first["state"],
            requested_tool="edit_file_range",
            target_path=self.TARGET,
            active_tool_schema_hash="d" * 64,
            active_legal_mutation_mechanisms=["edit_file"],
            base_context="bounded mission anchor",
            latest_feedback="tool unavailable",
            remaining_tool_steps=9,
        )
        self.assertTrue(second["reanchored"])
        self.assertEqual(
            second["status"], recovery.STRATEGY_EPOCH_CONTEXT_STALE_OR_IGNORED
        )
        reanchor = second["event"]
        self.assertTrue(
            recovery.validate_recovery_epoch_reanchor_event(reanchor)["valid"]
        )
        self.assertEqual(second["state"]["epoch_reanchors_used"], 1)
        self.assertEqual(second["state"]["strategy_epoch"], 1)
        self.assertEqual(second["state"]["strategy_switch_count"], 1)
        self.assertEqual(
            second["state"]["recovery_execution_id"],
            "RECOVERY-EXEC-V264-TEST-R1",
        )
        self.assertIn("edit_file", reanchor["legal_tools"])
        self.assertIn("edit_file_range", reanchor["suppressed_tools"])
        self.assertNotIn("PRIVATE OLD TRANSCRIPT", reanchor["context_projection"])
        self.assertNotIn("edit_file_range", reanchor["context_projection"].split(
            "Active legal mutation mechanisms:", 1
        )[-1])

    def test_09_second_reanchor_is_blocked_without_epoch_two(self):
        state = self._epoch_one_state()
        first = recovery.observe_suppressed_strategy_tool_request(
            state, requested_tool="edit_file_range", target_path=self.TARGET
        )
        second = recovery.observe_suppressed_strategy_tool_request(
            first["state"], requested_tool="edit_file_range", target_path=self.TARGET
        )
        third = recovery.observe_suppressed_strategy_tool_request(
            second["state"], requested_tool="edit_file_range", target_path=self.TARGET
        )
        self.assertEqual(
            third["status"], recovery.RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED
        )
        self.assertEqual(
            third["state"]["terminal_state"],
            recovery.RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED,
        )
        self.assertEqual(third["state"]["strategy_epoch"], 1)
        self.assertEqual(third["state"]["strategy_switch_count"], 1)

    def test_10_reanchor_context_is_bounded_and_authority_clean(self):
        state = self._epoch_one_state()
        context = recovery.build_recovery_epoch_reanchor_context(
            state,
            requested_tool="edit_file_range",
            latest_feedback="error: unavailable",
            base_context="MISSION-ID=bounded",
            remaining_tool_steps=15,
        )
        self.assertLessEqual(len(context), 1800)
        self.assertIn("MISSION-ID=bounded", context)
        self.assertIn("same RecoveryMission", context)
        self.assertIn("edit_file", context)
        self.assertNotIn("renderPauseIndicator", context)
        self.assertNotIn("module.exports", context)

    def test_11_completion_validation_reports_missing_contract_without_authority(self):
        validation = recovery.validate_recovery_completion_contract(
            {"status": "done"},
            required_completion_fields=["verified_child_receipt", "worker_execution"],
            required_coverage_ids=["NODE-002"],
        )
        self.assertFalse(validation["valid"])
        self.assertEqual(
            validation["missing_completion_fields"],
            ["verified_child_receipt", "worker_execution"],
        )
        self.assertEqual(validation["missing_coverage_ids"], ["NODE-002"])
        self.assertTrue(validation["worker_self_report_non_authoritative"])

    def test_12_one_completion_repair_is_allowed_only_with_remaining_budget(self):
        state = self._state()
        repaired = recovery.observe_recovery_completion_attempt(
            state,
            completion_payload={"status": "done"},
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=4,
            child_status="done",
            completed=True,
        )
        self.assertTrue(repaired["repair"])
        self.assertEqual(
            repaired["status"], recovery.COMPLETION_CONTRACT_REPAIR_READY
        )
        self.assertEqual(repaired["state"]["completion_repairs_used"], 1)
        self.assertIn("verified_child_receipt", repaired["feedback"])
        self.assertIn("NODE-002", repaired["feedback"])
        self.assertIn("Do not self-certify", repaired["feedback"])
        self.assertTrue(
            recovery.validate_recovery_completion_repair_event(
                repaired["event"]
            )["valid"]
        )

    def test_13_second_invalid_completion_is_bounded(self):
        state = self._state()
        first = recovery.observe_recovery_completion_attempt(
            state,
            completion_payload={},
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=4,
        )
        second = recovery.observe_recovery_completion_attempt(
            first["state"],
            completion_payload={},
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=3,
        )
        self.assertFalse(second["repair"])
        self.assertEqual(
            second["status"],
            recovery.RECOVERY_COMPLETION_REPAIR_BUDGET_EXHAUSTED,
        )
        self.assertEqual(second["state"]["completion_repairs_used"], 1)

    def test_14_completion_repair_does_not_run_when_budget_is_exhausted(self):
        observed = recovery.observe_recovery_completion_attempt(
            self._state(),
            completion_payload={},
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=0,
        )
        self.assertFalse(observed["repair"])
        self.assertEqual(observed["status"], recovery.WORKER_OUTPUT_INVALID)
        self.assertEqual(observed["state"]["completion_repairs_used"], 0)

    def test_15_valid_completion_is_dormant_and_does_not_repair(self):
        observed = recovery.observe_recovery_completion_attempt(
            self._state(),
            completion_payload={
                "verified_child_receipt": {"receipt_status": "VERIFIED"},
                "coverage_ids": ["NODE-002"],
                "completed": True,
            },
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=4,
        )
        self.assertFalse(observed["repair"])
        self.assertEqual(observed["status"], "COMPLETION_CONTRACT_VALID")
        self.assertEqual(observed["state"]["completion_repairs_used"], 0)

    def test_16_execute_loop_delivers_guidance_reanchor_and_completion_repair(self):
        state = self._epoch_one_state()
        state["recovery_mission_id"] = "MISSION-V264-EXECUTE"
        offered = []
        visible = []
        responses = [
            {
                "tool_calls": [{
                    "function": {
                        "name": "edit_file",
                        "arguments": {
                            "path": self.TARGET,
                            "old": "ambiguous",
                            "new": "candidate",
                            "expected_replacements": 1,
                        },
                    }
                }]
            },
            {
                "tool_calls": [{
                    "function": {
                        "name": "edit_file",
                        "arguments": {
                            "path": self.TARGET,
                            "old": "ambiguous",
                            "new": "candidate",
                            "expected_replacements": 1,
                        },
                    }
                }]
            },
            {
                "tool_calls": [{
                    "function": {
                        "name": "edit_file_range",
                        "arguments": {
                            "path": self.TARGET,
                            "start_line": 1,
                            "end_line": 1,
                            "new": "obsolete",
                        },
                    }
                }]
            },
            {
                "tool_calls": [{
                    "function": {
                        "name": "edit_file_range",
                        "arguments": {
                            "path": self.TARGET,
                            "start_line": 1,
                            "end_line": 1,
                            "new": "obsolete",
                        },
                    }
                }]
            },
            {
                "tool_calls": [{
                    "function": {
                        "name": "edit_file",
                        "arguments": {
                            "path": self.TARGET,
                            "old": "unique",
                            "new": "legal",
                            "expected_replacements": 1,
                        },
                    }
                }]
            },
            {"content": "not complete"},
            {
                "content": "complete",
                "completed": True,
                "verified_child_receipt": {"receipt_status": "VERIFIED"},
                "coverage_ids": ["NODE-002"],
            },
        ]

        def ask(messages, *, tools, **_kwargs):
            offered.append(
                {item["function"]["name"] for item in tools}
            )
            visible.append(
                str(messages[-1].get("content", "")) if messages else ""
            )
            return responses.pop(0)

        def run_tool(name, _args, role="Builder"):
            if name == "edit_file":
                if len([item for item in visible if "TOOL CONTRACT GUIDANCE" in item]) == 0:
                    return self.AMBIGUOUS
                return "edited file successfully"
            if name == "edit_file_range":
                return "error: tool 'edit_file_range' is unavailable for role Builder"
            return "read succeeded"

        with patch.object(mini, "ask_ollama", side_effect=ask), patch.object(
            mini, "run_tool", side_effect=run_tool
        ):
            result = mini.execute_agent_task(
                "Continue the bounded recovery mission",
                {},
                role="Builder",
                task_id=state["recovery_execution_id"],
                recovery_strategy=state,
                worker_context="MISSION-ID=MISSION-V264-EXECUTE",
                recovery_completion_contract={
                    "enabled": True,
                    "required_completion_fields": ["verified_child_receipt"],
                    "required_coverage_ids": ["NODE-002"],
                },
                max_steps=10,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["recovery_completion_events"]), 1)
        self.assertEqual(len(result["recovery_epoch_reanchor_events"]), 1)
        self.assertEqual(
            result["recovery_strategy_state"]["completion_repairs_used"], 1
        )
        self.assertEqual(
            result["recovery_strategy_state"]["epoch_reanchors_used"], 1
        )
        self.assertEqual(
            result["recovery_strategy_state"]["strategy_switch_count"], 1
        )
        self.assertEqual(
            result["recovery_strategy_state"]["recovery_execution_id"],
            "RECOVERY-EXEC-V264-TEST-R1",
        )
        self.assertIn("edit_file", offered[0])
        self.assertNotIn("edit_file_range", offered[0])
        self.assertIn("TOOL CONTRACT GUIDANCE", " ".join(visible))
        self.assertIn("RECOVERY EPOCH RE-ANCHOR", " ".join(visible))
        self.assertIn("COMPLETION CONTRACT REPAIR", " ".join(visible))
        self.assertEqual(responses, [])

    def test_16a_empty_completion_signal_is_checked_before_generic_continue(self):
        state = self._state()
        responses = [
            {
                "tool_calls": [{
                    "function": {
                        "name": "read_file",
                        "arguments": {"path": self.TARGET},
                    }
                }]
            },
            {"content": "", "completed": True},
            {
                "content": "",
                "completed": True,
                "verified_child_receipt": {"receipt_status": "VERIFIED"},
                "coverage_ids": ["NODE-002"],
            },
        ]

        def ask(_messages, **_kwargs):
            return responses.pop(0)

        with patch.object(mini, "ask_ollama", side_effect=ask), patch.object(
            mini, "run_tool", return_value="read succeeded"
        ):
            result = mini.execute_agent_task(
                "Continue the bounded recovery mission",
                {},
                role="Builder",
                task_id=state["recovery_execution_id"],
                recovery_strategy=state,
                recovery_completion_contract={
                    "enabled": True,
                    "required_completion_fields": ["verified_child_receipt"],
                    "required_coverage_ids": ["NODE-002"],
                },
                max_steps=5,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(len(result["recovery_completion_events"]), 1)
        self.assertEqual(
            result["recovery_strategy_state"]["completion_repairs_used"], 1
        )
        self.assertEqual(responses, [])

    def test_17_recovery_state_validator_caps_all_v264_budgets(self):
        state = self._state(
            tool_contract_guidance_events_used=99,
            epoch_reanchors_used=99,
            completion_repairs_used=99,
        )
        checked = recovery.validate_recovery_strategy_state(state)
        self.assertFalse(checked["valid"])
        self.assertTrue(any("budget" in error for error in checked["errors"]))

    def test_18_reanchor_preserves_authorization_and_does_not_create_approval(self):
        state = self._epoch_one_state()
        auth = copy.deepcopy(state["recovery_authorization"])
        observed = recovery.observe_suppressed_strategy_tool_request(
            recovery.observe_suppressed_strategy_tool_request(
                state,
                requested_tool="edit_file_range",
                target_path=self.TARGET,
            )["state"],
            requested_tool="edit_file_range",
            target_path=self.TARGET,
        )
        self.assertEqual(
            observed["state"]["recovery_authorization"], auth
        )
        self.assertNotIn("new_approval", observed["state"])
        self.assertEqual(observed["state"]["recovery_attempt_index"], 1)

    def test_19_authority_and_verification_weakening_do_not_get_repaired(self):
        state = self._state(
            recovery_authorization={
                "status": recovery.RECOVERY_AUTHORIZATION_BLOCKED,
                "authority_delta_empty": False,
                "user_reapproval_required": True,
            }
        )
        guidance = recovery.observe_recovery_tool_contract_failure(
            state,
            result=self.AMBIGUOUS,
            target_path=self.TARGET,
        )
        self.assertEqual(guidance["failure_count"], 1)
        completion = recovery.observe_recovery_completion_attempt(
            self._state(),
            completion_payload={
                "verified_child_receipt": False,
                "coverage_ids": ["NODE-002"],
            },
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=2,
        )
        self.assertTrue(completion["repair"])
        self.assertTrue(
            completion["event"]["worker_self_report_non_authoritative"]
        )

    def test_20_existing_v26_provider_free_replays_and_brain_safety_remain_intact(self):
        self.assertEqual(recovery.MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_STRATEGY_SWITCHES, 1)
        self.assertEqual(recovery.RECOVERY_STRATEGY_STAGNATION_THRESHOLD, 2)
        self.assertEqual(recovery.LIVE3_BRAIN_HASH, "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb")

    def test_21_generic_validator_dispatches_v264_records(self):
        state = self._epoch_one_state()
        pattern = recovery.observe_recovery_tool_contract_failure(
            state, result=self.AMBIGUOUS, target_path=self.TARGET
        )["pattern"]
        guidance = recovery.observe_recovery_tool_contract_failure(
            recovery.observe_recovery_tool_contract_failure(
                state, result=self.AMBIGUOUS, target_path=self.TARGET
            )["state"],
            result=self.AMBIGUOUS,
            target_path=self.TARGET,
        )["guidance_event"]
        reanchor = recovery.observe_suppressed_strategy_tool_request(
            recovery.observe_suppressed_strategy_tool_request(
                state, requested_tool="edit_file_range", target_path=self.TARGET
            )["state"],
            requested_tool="edit_file_range",
            target_path=self.TARGET,
        )["event"]
        repair = recovery.observe_recovery_completion_attempt(
            state,
            completion_payload={},
            required_completion_fields=["verified_child_receipt"],
            required_coverage_ids=["NODE-002"],
            remaining_tool_steps=2,
        )["event"]
        for artifact in (pattern, guidance, reanchor, repair):
            self.assertTrue(recovery.validate_recovery_strategy(artifact)["valid"])

    def test_22_positive_v26_replay_remains_provider_free_after_v264_prefix(self):
        live3 = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
        if not live3.is_dir():
            self.skipTest("historical V25.6 live-3 fixture unavailable")
        state = self._epoch_one_state()
        first = recovery.observe_recovery_tool_contract_failure(
            state, result=self.AMBIGUOUS, target_path=self.TARGET
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"], result=self.AMBIGUOUS, target_path=self.TARGET
        )
        self.assertEqual(second["status"], recovery.TOOL_CONTRACT_STAGNATION_DETECTED)
        replay = recovery.run_provider_free_recovery_replay(live3, outcome="success")
        self.assertTrue(replay["stage5a"]["passed"])
        self.assertEqual(replay["stage5b"]["status"], "PARENT_VERIFIED")
        self.assertEqual(replay["stage5c"]["promotion_status"], "PROMOTED")
        self.assertEqual(replay["reentry"]["status"], "REENTRY_READY")
        self.assertEqual(replay["gemma_calls"], 0)
        self.assertEqual(replay["real_worker_calls"], 0)


if __name__ == "__main__":
    unittest.main()
