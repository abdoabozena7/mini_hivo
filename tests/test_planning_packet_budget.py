import copy
import json
import unittest
from unittest.mock import patch

import mini
from hivo import impact_planning as impact
from hivo import verified_planning


class PlanningPacketBudgetTests(unittest.TestCase):
    """V24.1 packet compilation tests; all cases are provider-free."""

    def setUp(self):
        mini.reset_run("planning-packet-budget")

    @staticmethod
    def render(value):
        return "ROLE ENVELOPE:\nCOMPLETE PACKET:\n" + impact._compact_json(value)

    def test_live_two_shape_old_9008_case_is_compacted_without_slicing(self):
        mandatory = {"requirement": "R" * 128, "optional_evidence": None}
        seed = {
            "item_id": "OPTIONAL-EVIDENCE-001", "priority": 60,
            "field": "optional_evidence", "value": "x",
        }

        def with_completion_marker(items):
            value = impact._role_payload_factory(mandatory, items)
            value["packet_complete"] = True
            return value

        # Reproduce the old boundary generically: the payload fit before the
        # final completion marker, while the exact final render was 9008.
        old_one_char = impact._role_payload_factory(mandatory, [seed])
        marker_delta = len(self.render(with_completion_marker([seed]))) - len(self.render(old_one_char))
        optional_length = 9008 - len(self.render(with_completion_marker([seed]))) + 1
        seed["value"] = "x" * optional_length
        old_payload = impact._role_payload_factory(mandatory, [seed])
        old_final_payload = with_completion_marker([seed])
        self.assertEqual(len(self.render(old_final_payload)), 9008)
        self.assertLessEqual(len(self.render(old_payload)), 9000)
        self.assertGreater(marker_delta, 0)

        packet = impact.build_planning_role_packet(
            "ImpactPlanner", mandatory,
            [{
                "item_id": "OPTIONAL-EVIDENCE-001", "priority": 60,
                "field": "optional_evidence", "value": "x" * optional_length,
            }],
            hard_limit=9000, render=self.render,
            payload_factory=lambda selected: with_completion_marker(selected),
        )
        self.assertLessEqual(packet["rendered_chars"], 9000)
        self.assertTrue(packet["packet_complete"])
        self.assertEqual(packet["mandatory_drops"], [])
        self.assertIn("OPTIONAL-EVIDENCE-001", packet["optional_items_dropped_ids"])
        self.assertEqual(json.loads(impact._compact_json(packet["payload"])), packet["payload"])
        self.assertNotIn("x" * 100, impact._compact_json(packet["payload"]))

    def test_packet_hash_and_exact_accounting_are_deterministic(self):
        optional = [{
            "item_id": "OPTIONAL-001", "priority": 20,
            "path": ("evidence",), "value": {"id": "REPO-1", "fact": "support"},
        }]
        first = impact.build_planning_role_packet(
            "ImpactPlanner", {"required": "user requirement", "evidence": []},
            optional, hard_limit=9000, render=self.render,
        )
        second = impact.build_planning_role_packet(
            "ImpactPlanner", {"required": "user requirement", "evidence": []},
            optional, hard_limit=9000, render=self.render,
        )
        self.assertEqual(first["packet_hash"], second["packet_hash"])
        self.assertEqual(first["rendered_chars"], len(first["exact_model_input"]))
        self.assertEqual(first["rendered_chars"], len(first["rendered_packet"]))
        self.assertTrue(first["accounting"]["matches_exact_render"])
        self.assertEqual(
            first["accounting"]["envelope_plus_payload_plus_separators"],
            first["rendered_chars"],
        )

    def test_optional_units_trim_by_priority_and_repeat_deterministically(self):
        mandatory = {"required": "requirement", "items": []}
        high = {"item_id": "HIGH", "priority": 90, "path": ("items",), "index": 0,
                "value": {"id": "HIGH", "text": "high"}}
        low = {"item_id": "LOW", "priority": 10, "path": ("items",), "index": 1,
               "value": {"id": "LOW", "text": "L" * 200}}
        high_limit = len(self.render({"required": "requirement", "items": [high["value"]]}))
        first = impact.build_planning_role_packet(
            "ImpactPlanner", mandatory, [low, high], hard_limit=high_limit, render=self.render,
        )
        second = impact.build_planning_role_packet(
            "ImpactPlanner", mandatory, [low, high], hard_limit=high_limit, render=self.render,
        )
        self.assertEqual(first["optional_items_selected"], ["HIGH"])
        self.assertEqual(first["optional_items_dropped_ids"], ["LOW"])
        self.assertEqual(first["optional_items_dropped_ids"], second["optional_items_dropped_ids"])
        self.assertTrue(first["packet_complete"])
        self.assertEqual(first["payload"]["items"], [high["value"]])

    def test_mandatory_overflow_fails_closed_before_provider(self):
        packet = impact.build_planning_role_packet(
            "ImpactPlanner", {"requirement": "M" * 400}, [], hard_limit=80,
            render=self.render,
        )
        self.assertEqual(packet["status"], impact.PLANNING_PACKET_MANDATORY_OVERFLOW)
        self.assertFalse(packet["packet_complete"])
        self.assertEqual(packet["mandatory_drops"], [])
        self.assertEqual(packet["optional_items_selected"], [])
        with self.assertRaises(mini.PlanningPacketBudgetError):
            mini.structured_model_call(
                "ignored", lambda value: True, "budget-test", {},
                role="ImpactPlanner", role_packet=packet,
            )
        self.assertEqual(mini.RUN["model_calls"], 0)

    def test_provider_receives_the_hash_audited_exact_packet_once(self):
        packet = impact.build_planning_role_packet(
            "ImpactPlanner", {"required": "requirement"}, [],
            render=self.render, hard_limit=9000,
        )
        captured = []

        def fake_ask(messages, **kwargs):
            captured.append((copy.deepcopy(messages), kwargs))
            return {"content": "{}"}

        with patch.object(mini, "ask_ollama", side_effect=fake_ask):
            mini.structured_model_call(
                "a different prompt", lambda value: True, "budget-test", {},
                role="ImpactPlanner", role_packet=packet,
            )
        self.assertEqual(len(captured), 1)
        self.assertEqual(captured[0][0][-1]["content"], packet["exact_model_input"])
        self.assertNotIn("JSON SCHEMA:", packet["exact_model_input"])

    def test_oversized_exact_packet_blocks_provider_before_transport(self):
        packet = impact.build_planning_role_packet(
            "ImpactPlanner", {"required": "requirement"}, [],
            render=self.render, hard_limit=9000,
        )
        oversized = copy.deepcopy(packet)
        oversized["exact_model_input"] = "x" * 9001
        with patch.object(mini, "ask_ollama") as ask:
            with self.assertRaises(mini.PlanningPacketBudgetError) as raised:
                mini.structured_model_call(
                    "ignored", lambda value: True, "budget-test", {},
                    role="ImpactPlanner", role_packet=oversized,
                )
        self.assertEqual(raised.exception.code, impact.PLANNING_PACKET_PROVIDER_OVERFLOW)
        ask.assert_not_called()
        self.assertEqual(mini.RUN["model_calls"], 0)
        self.assertEqual(mini.RUN["planning_role_provider_calls_blocked_by_budget"], 1)

    def test_all_frozen_planning_roles_use_their_own_exact_limit(self):
        for role in ("ImpactPlanner", "ImpactChallenger", "ImpactPlanReviser"):
            limit = impact.planning_role_limit(role)
            packet = impact.build_planning_role_packet(
                role, {"required": role}, [], hard_limit=limit, render=self.render,
            )
            self.assertEqual(packet["hard_limit_chars"], limit)
            self.assertLessEqual(packet["rendered_chars"], limit)
            self.assertTrue(packet["packet_complete"])

    def test_semantic_dedup_keeps_source_ids_and_one_bounded_statement(self):
        authority = impact._planner_authority_projection({
            "current_authority": [{
                "record_id": "AUTH-1", "text": "PauseController owns pause state",
            }],
            "current_verified_facts": [{
                "record_id": "FACT-1", "fact_hash": "f" * 64,
                "text": "PauseController owns pause state",
            }],
        })
        self.assertEqual(len(authority), 1)
        self.assertIn("AUTH-1", authority[0]["source_ids"])
        self.assertIn("FACT-1", authority[0]["source_ids"])

        preservation = impact._planner_preservation_projection(
            {"preservation_constraints": [{"text": "Keep PauseController unchanged"}]},
            [{"requirement_id": "REQ-1", "text": "Keep PauseController unchanged", "status": "active"}],
        )
        self.assertEqual(len(preservation), 1)
        self.assertNotIn("text", preservation[0])
        self.assertEqual(preservation[0]["requirement_ids"], ["REQ-1"])

    def test_v24_context_remains_unchanged_and_live_shape_fits_impact_limit(self):
        from tests.test_verified_state_planning import VerifiedStatePlanningTests

        fixture = VerifiedStatePlanningTests("context")
        fixture.setUp()
        try:
            verified_context = fixture.context()
            original_context = copy.deepcopy(verified_context)
            task_brain = verified_planning.build_stage3_task_brain(verified_context)
            evidence = verified_context["current_repository_evidence"]
            requirements = verified_context["new_requirements"]
            registry = impact.build_canonical_surface_registry(task_brain, evidence)
            packet = impact.build_canonical_planning_packet(
                task_brain, requirements, evidence, surface_registry=registry,
                role="ImpactPlanner", render=self.render, base_render=self.render,
                verified_planning_context=verified_context,
            )
            role_packet = packet["role_packet"]
            self.assertLessEqual(role_packet["rendered_chars"], 9000)
            self.assertTrue(packet["packet_complete"])
            self.assertEqual(role_packet["mandatory_drops"], [])
            self.assertEqual(
                role_packet["source_planning_context_hash"],
                verified_context["planning_context_hash"],
            )
            rendered = role_packet["exact_model_input"]
            for required_text in (
                "Add a user-facing pause indicator", "PauseController", "Escape",
                "movement", "togglePause", "DNT",
            ):
                self.assertIn(required_text, rendered)
            self.assertEqual(verified_context, original_context)
        finally:
            fixture.tearDown()

    def test_stale_warning_stays_warning_and_confirmed_drift_is_mandatory(self):
        from tests.test_verified_state_planning import VerifiedStatePlanningTests

        fixture = VerifiedStatePlanningTests("context")
        fixture.setUp()
        try:
            stale = fixture.context(stale=True)
            stale_brain = verified_planning.build_stage3_task_brain(stale)
            stale_evidence = stale["current_repository_evidence"]
            stale_packet = impact.build_canonical_planning_packet(
                stale_brain, stale["new_requirements"], stale_evidence,
                surface_registry=impact.build_canonical_surface_registry(stale_brain, stale_evidence),
                role="ImpactPlanner", render=self.render, base_render=self.render,
                verified_planning_context=stale,
            )
            warnings = stale_packet["packet"].get("stale_evidence_warnings", [])
            self.assertTrue(all(item.get("classification") == "STALE_WARNING" for item in warnings))
            self.assertFalse(any(item.get("record_id") == "STALE-PAUSE-INTEGRATION"
                                 for item in stale_packet["packet"].get("current_verified_facts", [])))

            drift = fixture.context(
                conflicts=[fixture.drift_conflict()],
                audits=[fixture.audit(classification="CONFIRMED_DRIFT")],
            )
            drift_brain = verified_planning.build_stage3_task_brain(drift)
            drift_evidence = drift["current_repository_evidence"]
            drift_packet = impact.build_canonical_planning_packet(
                drift_brain, drift["new_requirements"], drift_evidence,
                surface_registry=impact.build_canonical_surface_registry(drift_brain, drift_evidence),
                role="ImpactPlanner", render=self.render, base_render=self.render,
                verified_planning_context=drift,
            )
            self.assertTrue(drift_packet["packet"]["confirmed_conflicts"])
            self.assertEqual(drift_packet["role_packet"]["mandatory_drops"], [])
        finally:
            fixture.tearDown()


if __name__ == "__main__":
    unittest.main()
