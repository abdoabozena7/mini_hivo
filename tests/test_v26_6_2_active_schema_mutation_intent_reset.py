from __future__ import annotations

import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import mini
from hivo import recovery


class V2662ActiveSchemaMutationIntentTests(unittest.TestCase):
    EXECUTION = "RECOVERY-EXEC-V2662-TEST-R1"
    SUBJECT = "a" * 64
    OTHER_SUBJECT = "b" * 64
    TARGET = "src/status_view.js"
    OTHER_TARGET = "src/input.js"
    LEGAL = ["edit_file", "edit_file_range"]

    def _state(self, **overrides):
        state = recovery.create_recovery_strategy_state(
            self.EXECUTION,
            target_path=self.TARGET,
            available_legal_mechanisms=self.LEGAL,
            current_subject_hash=self.SUBJECT,
            recovery_authorization={
                "status": recovery.RECOVERY_AUTHORIZATION_READY,
                "authority_delta_empty": True,
                "user_reapproval_required": False,
                "authorization_id": "AUTH-V2662",
                "authorization_hash": "c" * 64,
            },
            lineage={
                "status": recovery.AUTHORIZED_EXECUTION_DESCENDANT,
                "valid": True,
            },
            recovery_mission_id="MISSION-V2662",
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
        })
        state.update(overrides)
        return recovery.initialize_recovery_no_mutation_search_state(state)

    @staticmethod
    def _schema(name, *, mutation=False):
        return {
            "type": "function",
            "function": {
                "name": name,
                "description": (
                    "Apply a behavior-changing mutation to an existing file."
                    if mutation else "Inspect the current project state."
                ),
            },
            "metadata": {"mutation": mutation},
        }

    def _intent(self, name, *, active=None, suppressed=(), known=None):
        return recovery.classify_recovery_tool_intent(
            name,
            active_tool_schema=active or [],
            suppressed_mutation_mechanisms=suppressed,
            known_mutation_mechanisms=(
                self.LEGAL if known is None else known
            ),
        )

    def _observe(self, state, name, ordinal, *, active, intent=None, **overrides):
        if intent is None:
            intent = self._intent(name, active=active)
        values = {
            "tool_name": name,
            "target_path": state.get("target_path", self.TARGET),
            "subject_identity": state.get("current_subject_hash", self.SUBJECT),
            "subject_unchanged": True,
            "event_id": f"v2662-tool-event-{ordinal}",
            "remaining_tool_steps": 20,
            "tool_steps_used": ordinal,
            "recognized_tool": intent in {
                recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
                recovery.RECOVERY_TOOL_INTENT_ACTIVE_NON_MUTATION,
            },
            "mutation_attempt": intent in {
                recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
                recovery.RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION,
            },
        }
        values.update(overrides)
        return recovery.observe_recovery_no_mutation_search_interaction(
            state, **values
        )

    def _three_inspections(self, state=None):
        current = state or self._state()
        active = [self._schema("read_file"), self._schema("list_files")]
        for ordinal, name in enumerate(("read_file", "list_files", "read_file"), 1):
            current = self._observe(current, name, ordinal, active=active)["state"]
        return current, active

    def test_01_classification_is_schema_bound_and_static_membership_is_insufficient(self):
        active = [
            self._schema("edit_file", mutation=True),
            self._schema("read_file"),
        ]
        self.assertEqual(
            recovery.is_recovery_mutation_mechanism("write_file"), True
        )
        self.assertEqual(
            self._intent("write_file", active=active),
            recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
        )
        self.assertEqual(
            self._intent("edit_file", active=active),
            recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
        )
        self.assertEqual(
            self._intent("read_file", active=active),
            recovery.RECOVERY_TOOL_INTENT_ACTIVE_NON_MUTATION,
        )
        self.assertEqual(
            self._intent("totally_unknown_tool", active=active),
            recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
        )

    def test_02_unavailable_write_file_preserves_count_and_does_not_reset(self):
        state, active = self._three_inspections()
        self.assertEqual(state["no_mutation_search_interaction_count"], 3)
        intent = self._intent("write_file", active=active)
        observed = self._observe(state, "write_file", 15, active=active, intent=intent)
        self.assertEqual(intent, recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE)
        self.assertFalse(observed["reset"])
        self.assertFalse(observed["counted"])
        self.assertEqual(
            observed["state"]["no_mutation_search_interaction_count"], 3
        )

    def test_03_active_edit_file_ambiguity_resets_and_v264_owns_followup(self):
        state, active = self._three_inspections()
        active = active + [self._schema("edit_file", mutation=True)]
        observed = self._observe(state, "edit_file", 4, active=active)
        self.assertEqual(
            observed["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_RESET
        )
        self.assertTrue(observed["reset"])
        self.assertEqual(observed["state"]["no_mutation_search_interaction_count"], 0)
        ambiguous = "error: expected 1 exact replacement(s), found 2; file was not changed"
        first = recovery.observe_recovery_tool_contract_failure(
            observed["state"], tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        second = recovery.observe_recovery_tool_contract_failure(
            first["state"], tool="edit_file", target_path=self.TARGET, result=ambiguous,
        )
        self.assertEqual(first["state"]["tool_contract_failure_count"], 1)
        self.assertTrue(second["escalated"])
        self.assertEqual(second["state"]["mutation_path_reorientations_used"], 0)

    def test_04_active_edit_file_range_is_mutation_intent_even_when_validation_fails(self):
        state, _ = self._three_inspections()
        active = [self._schema("edit_file_range", mutation=True)]
        observed = self._observe(state, "edit_file_range", 4, active=active)
        self.assertEqual(
            self._intent("edit_file_range", active=active),
            recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
        )
        self.assertTrue(observed["reset"])
        self.assertEqual(observed["state"]["no_mutation_search_interaction_count"], 0)

    def test_05_suppressed_known_mutation_resets_and_routes_to_v264(self):
        state = self._state(
            suppressed_mutation_mechanisms=["edit_file"],
            current_strategy=recovery.build_recovery_mutation_strategy(
                self.EXECUTION,
                target_path=self.TARGET,
                strategy_epoch=0,
                allowed_mutation_mechanisms=["edit_file_range"],
                suppressed_mutation_mechanisms=["edit_file"],
                source_subject_identity=self.SUBJECT,
            ),
        )
        state, _ = self._three_inspections(state)
        active = [self._schema("read_file"), self._schema("edit_file_range", mutation=True)]
        intent = self._intent(
            "edit_file",
            active=active,
            suppressed=("edit_file",),
            known=("edit_file", "edit_file_range"),
        )
        observed = self._observe(state, "edit_file", 4, active=active, intent=intent)
        self.assertEqual(intent, recovery.RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION)
        self.assertTrue(observed["reset"])
        routed = recovery.observe_suppressed_strategy_tool_request(
            observed["state"],
            requested_tool="edit_file",
            target_path=self.TARGET,
            active_legal_mutation_mechanisms=["edit_file_range"],
            subject_identity=self.SUBJECT,
        )
        self.assertEqual(routed["status"], recovery.SUPPRESSED_STRATEGY_TOOL_REQUESTED)
        self.assertFalse(routed["reanchored"])

    def test_06_unknown_tool_does_not_reset_or_increment(self):
        state, active = self._three_inspections()
        observed = self._observe(
            state,
            "totally_unknown_tool",
            4,
            active=active,
            intent=recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
        )
        self.assertFalse(observed["reset"])
        self.assertFalse(observed["counted"])
        self.assertEqual(observed["state"]["no_mutation_search_interaction_count"], 3)

    def test_07_active_non_mutation_tools_and_rejected_command_still_count(self):
        state = self._state()
        active = [
            self._schema("read_file"),
            self._schema("run_command"),
        ]
        read = self._observe(state, "read_file", 1, active=active)
        command = self._observe(read["state"], "run_command", 2, active=active)
        self.assertTrue(read["counted"])
        self.assertTrue(command["counted"])
        self.assertEqual(command["interaction_count"], 2)

    def test_08_empty_response_and_completion_do_not_count(self):
        state, active = self._three_inspections()
        empty = self._observe(
            state,
            None,
            4,
            active=active,
            intent=recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
            empty_response=True,
        )
        completion = self._observe(
            empty["state"],
            None,
            5,
            active=active,
            intent=recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
            completion_attempt=True,
        )
        self.assertEqual(empty["interaction_count"], 3)
        self.assertEqual(completion["interaction_count"], 3)
        self.assertFalse(empty["counted"])
        self.assertFalse(completion["counted"])

    def test_09_schema_dependent_write_file_is_active_when_authorized_and_exposed(self):
        active = [self._schema("write_file", mutation=True)]
        self.assertEqual(
            self._intent("write_file", active=active),
            recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
        )
        state, _ = self._three_inspections()
        observed = self._observe(state, "write_file", 4, active=active)
        self.assertTrue(observed["reset"])
        self.assertEqual(observed["state"]["no_mutation_search_interaction_count"], 0)

    def test_10_historical_generation_15_and_18_replay_has_correct_reset_ownership(self):
        state, active = self._three_inspections()
        unavailable = self._observe(
            state,
            "write_file",
            15,
            active=active,
            intent=recovery.RECOVERY_TOOL_INTENT_UNAVAILABLE,
        )
        self.assertEqual(
            unavailable["state"]["no_mutation_search_interaction_count"], 3
        )
        exhausted_state = copy.deepcopy(unavailable["state"])
        exhausted_state["mutation_path_reorientations_used"] = 1
        list_event = self._observe(exhausted_state, "list_files", 17, active=active)
        self.assertEqual(list_event["interaction_count"], 4)
        self.assertEqual(list_event["status"], recovery.RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED)
        active_edit = [self._schema("edit_file", mutation=True)]
        edit_event = self._observe(list_event["state"], "edit_file", 18, active=active_edit)
        self.assertTrue(edit_event["reset"])
        self.assertEqual(edit_event["state"]["no_mutation_search_interaction_count"], 0)

    def test_11_reset_dimensions_and_commit_semantics_remain_unchanged(self):
        state, active = self._three_inspections()
        changed_subject = self._observe(
            state,
            "read_file",
            4,
            active=active,
            subject_identity=self.OTHER_SUBJECT,
            subject_unchanged=False,
        )
        self.assertEqual(changed_subject["interaction_count"], 1)
        state = self._state()
        state, active = self._three_inspections(state)
        changed_target = self._observe(
            state,
            "read_file",
            4,
            active=active,
            target_path=self.OTHER_TARGET,
        )
        self.assertEqual(changed_target["interaction_count"], 1)
        state = self._state()
        state, _ = self._three_inspections(state)
        committed = self._observe(
            state,
            "edit_file",
            4,
            active=[self._schema("edit_file", mutation=True)],
            committed=True,
            commit_count=1,
        )
        self.assertTrue(committed["reset"])
        self.assertEqual(committed["state"]["no_mutation_search_interaction_count"], 0)

    def test_12_threshold_safety_floor_and_budget_are_frozen(self):
        self.assertEqual(
            recovery.MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION,
            4,
        )
        self.assertEqual(
            recovery.MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION, 3
        )
        self.assertEqual(recovery.MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_COMPLETION_REPAIRS, 1)
        self.assertEqual(recovery.MAX_RECOVERY_STRATEGY_SWITCHES, 1)

    def test_13_workspace_uniqueness_fixture_is_time_invariant(self):
        historical = Path(
            r"D:\projects\Ai\mini_hivo\output\hivo-v26-6-stage6c-b-no-mutation-recovery-live-1"
        )
        self.assertTrue(historical.is_dir())
        with TemporaryDirectory(prefix="v2662-workspace-uniqueness-") as temp_root:
            synthetic = Path(temp_root) / "candidate-live"
            workspace_is_unused = lambda path: not path.exists()
            self.assertTrue(workspace_is_unused(synthetic))
            synthetic.mkdir()
            self.assertFalse(workspace_is_unused(synthetic))

    def test_14_provider_free_tests_do_not_call_model(self):
        with patch.object(mini, "ask_ollama") as ask:
            active = [self._schema("edit_file", mutation=True)]
            self.assertEqual(
                self._intent("edit_file", active=active),
                recovery.RECOVERY_TOOL_INTENT_ACTIVE_MUTATION,
            )
            ask.assert_not_called()

    def test_15_custom_suppressed_mutation_uses_authoritative_strategy_projection(self):
        intent = self._intent(
            "apply_existing_edit",
            active=[self._schema("read_file")],
            suppressed=("apply_existing_edit",),
            known=("apply_existing_edit",),
        )
        self.assertEqual(
            intent, recovery.RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION
        )


if __name__ == "__main__":
    unittest.main()
