import copy
import json
import unittest
from unittest.mock import patch

import mini
from hivo import impact_planning as impact


class CanonicalMandatoryPlanningCoreTests(unittest.TestCase):
    """Provider-free V24.2 semantic-core and exact-packet regressions."""

    REQUIREMENT = (
        "Extend the existing pause flow with an additional user-facing pause indicator "
        "while preserving PauseController as the existing pause-state owner and preserving "
        "current Escape and movement behavior."
    )

    def setUp(self):
        mini.reset_run("v24.2-canonical-core")

    @staticmethod
    def _role_renderer(role):
        if role == "ImpactPlanner":
            return mini._planning_provider_renderer(
                mini._impact_planner_prompt, impact.impact_map_schema(),
            )
        if role == "ImpactChallenger":
            return mini._planning_provider_renderer(
                mini._impact_challenger_prompt, impact.challenge_schema(),
            )
        return mini._planning_provider_renderer(
            mini._impact_revision_prompt, impact.impact_map_schema(),
        )

    def _old_live_shape_payload(self):
        requirements = [{
            "requirement_id": "REQ-PAUSE-INDICATOR",
            "text": self.REQUIREMENT,
            "provenance": impact.USER_STATED,
        }]
        surfaces = []
        seeds = []
        for index in range(1, 7):
            surface_id = f"SURF-{index:03d}"
            evidence_id = f"REPO-{index:03d}"
            surfaces.append({
                "surface_id": surface_id,
                "kind": "TEST" if index > 3 else "OWNER",
                "role": "CURRENT_TEST" if index > 3 else "STATE_OWNER",
                "path": f"src/pause_surface_{index}.js",
                "symbol": "PauseController" if index == 1 else f"Surface{index}",
                "verified_fact": f"{surface_id} protects the current pause behavior.",
                "evidence_ids": [evidence_id],
                "owner_surface_id": None,
            })
            seeds.append({
                "impact_id": f"IMPACT-{index:03d}",
                "surface_id": surface_id,
                "requirement_ids": ["REQ-PAUSE-INDICATOR"],
                "evidence_ids": [evidence_id],
                "canonical_path": f"src/pause_surface_{index}.js",
                "canonical_symbol": "PauseController" if index == 1 else f"Surface{index}",
                "eligible": True,
            })
        payload = {
            "version": 1,
            "task_goal": self.REQUIREMENT,
            "requirements": requirements,
            "surfaces": surfaces,
            "impact_seeds": seeds,
            "preservation_constraints": [
                {"text": "PauseController remains the sole pause-state owner.", "constraint_type": "DNT"},
                {"text": "Preserve current Escape behavior.", "constraint_type": "DNT"},
                {"text": "Preserve current movement behavior.", "constraint_type": "DNT"},
            ],
            "current_authority": [
                {
                    "authority_type": "CURRENT_AUTHORITY",
                    "authority_types": ["CURRENT_AUTHORITY", "CURRENT_VERIFIED"],
                    "text": "PauseController remains the sole pause-state owner.",
                    "path": "src/pause_controller.js",
                    "symbol": "PauseController",
                    "source_ids": [f"AUTH-{index:03d}-" + ("a" * 20)],
                }
                for index in range(1, 13)
            ] + [{
                "authority_type": "CURRENT_AUTHORITY",
                "authority_types": ["CURRENT_AUTHORITY", "REQUIRED_INTERFACE"],
                "text": "PauseController.togglePause() is the existing pause transition interface.",
                "path": "src/pause_controller.js",
                "symbol": "PauseController.togglePause()",
                "source_ids": ["IFACE-PAUSE-" + ("b" * 20)],
            }],
            "dnt": [{
                "constraint_id": "DNT-001",
                "requirement_ids": ["REQ-PAUSE-INDICATOR"],
            }],
            "current_vs_desired": [{
                "desired_requirement_ids": ["REQ-PAUSE-INDICATOR"],
                "current_authority_ids": [f"AUTH-{index:03d}" for index in range(1, 13)],
                "current_evidence_ids": [f"REPO-{index:03d}" for index in range(1, 7)],
            }],
            "planning_provenance": {
                "planning_mode": "VERIFIED_STATE_REENTRY",
                "source_planning_context_hash": "c" * 64,
                "source_task_brain_hash": "b" * 64,
                "source_reentry_hash": "r" * 64,
            },
            "planning_rules": [
                "KNOWN_IMPACT_SLOTS_ONLY", "VALID_REQUIREMENT_IDS_ONLY",
                "REUSE_CANONICAL_INTERFACES", "PRESERVE_VERIFIED_STATE_UNLESS_PROVEN",
                "JUSTIFY_NEW_SURFACE_PROPOSALS",
            ],
            "bounds": {
                "max_impact_entries": 12, "max_canonical_surfaces": 32,
                "max_serialized_chars": 9000,
            },
            "packet_complete": True,
        }
        target = 8328
        pad_record = payload["current_authority"][0]["source_ids"]
        for _ in range(6):
            current = len(impact._compact_json(payload))
            if current == target:
                break
            old_length = len(pad_record[0])
            new_length = old_length + target - current
            if new_length < 1:
                raise AssertionError("the deterministic live-shape fixture cannot be fitted")
            pad_record[0] = "P" * new_length
        self.assertEqual(len(impact._compact_json(payload)), target)
        return payload

    def test_exact_recorded_9622_case_fits_after_canonical_normalization(self):
        old_payload = self._old_live_shape_payload()
        renderer = self._role_renderer("ImpactPlanner")
        old_exact = renderer(old_payload)
        self.assertEqual(len(old_exact), 9622)
        self.assertEqual(len(impact._compact_json(old_payload)), 8328)

        audit = impact.audit_mandatory_planning_payload(old_payload)
        core = impact.build_canonical_mandatory_planning_core(old_payload)
        compact = impact._canonical_mandatory_model_payload(old_payload, core)
        first = impact.build_planning_role_packet(
            "ImpactPlanner", compact, [], hard_limit=9000,
            render=renderer, base_render=mini._impact_planner_prompt,
            planning_core_hash=core["mandatory_core_hash"],
            mandatory_payload_audit=audit,
            mandatory_semantic_coverage=core["mandatory_semantic_coverage"],
            mandatory_core_metrics=core["metrics"],
        )
        second = impact.build_planning_role_packet(
            "ImpactPlanner", compact, [], hard_limit=9000,
            render=renderer, base_render=mini._impact_planner_prompt,
            planning_core_hash=core["mandatory_core_hash"],
            mandatory_payload_audit=audit,
            mandatory_semantic_coverage=core["mandatory_semantic_coverage"],
            mandatory_core_metrics=core["metrics"],
        )
        self.assertLessEqual(first["rendered_chars"], 9000)
        self.assertTrue(first["packet_complete"])
        self.assertEqual(first["mandatory_drops"], [])
        self.assertEqual(first["packet_hash"], second["packet_hash"])
        self.assertEqual(first["rendered_chars"], len(first["exact_model_input"]))
        self.assertEqual(first["rendered_packet"], first["exact_model_input"])
        self.assertTrue(first["accounting"]["matches_exact_render"])
        self.assertEqual(core["mandatory_semantic_coverage_rate"], 1.0)
        self.assertEqual(impact.validate_canonical_mandatory_planning_core(core)["valid"], True)
        self.assertEqual(core["metrics"]["planning_core_model_calls"], 0)

        exact_text = impact._compact_json(compact)
        self.assertEqual(exact_text.count(self.REQUIREMENT), 1)
        for required in (
            "PauseController", "togglePause", "Escape", "movement", "DNT",
        ):
            self.assertIn(required, exact_text)

    def test_fan_in_deduplicates_exact_semantics_without_losing_provenance(self):
        phrase = "Keep PauseController as the pause-state owner."
        payload = {
            "task_goal": phrase,
            "requirements": [{"requirement_id": "REQ-1", "text": phrase}],
            "current_authority": [{
                "record_id": "AUTH-1", "text": phrase,
            }],
            "interfaces": [{
                "record_id": "IFACE-1", "text": phrase,
            }],
            "preservation_constraints": [{
                "record_id": "PRES-1", "text": phrase,
            }],
        }
        core = impact.build_canonical_mandatory_planning_core(payload)
        self.assertLess(
            len(core["semantic_units"]),
            len(core["mandatory_semantic_coverage"]),
        )
        unit = next(item for item in core["semantic_units"] if item["semantic_id"].startswith("REQ-"))
        self.assertTrue({"AUTH-1", "IFACE-1", "PRES-1", "REQ-1"}.issubset(
            set(unit["source_references"])
        ))
        self.assertEqual(core["mandatory_semantic_coverage_rate"], 1.0)
        compact = impact._canonical_mandatory_model_payload(payload, core)
        self.assertEqual(impact._compact_json(compact).count(phrase), 1)
        self.assertEqual(
            len(compact["mandatory_core"]["desired_user_change"]), 1,
        )
        self.assertNotIn("meaning", compact["mandatory_core"]["desired_user_change"][0])

    def test_unknown_and_explicitly_distinct_relations_are_not_fuzzy_merged(self):
        unknown = impact.build_canonical_mandatory_planning_core({
            "current_authority": [
                {"record_id": "A", "text": "PauseController owns pause state"},
                {"record_id": "B", "text": "PauseController owns paused state"},
            ],
        })
        self.assertEqual(len(unknown["semantic_units"]), 2)

        explicit = impact.build_canonical_mandatory_planning_core({
            "current_authority": [
                {
                    "record_id": "A", "text": "Pause state authority",
                    "structured_relation": {
                        "subject": "PAUSE_STATE", "predicate": "owner", "object": "PauseController",
                    },
                },
                {
                    "record_id": "B", "text": "Pause state authority",
                    "structured_relation": {
                        "subject": "PAUSE_STATE", "predicate": "owner", "object": "StatusView",
                    },
                },
            ],
        })
        self.assertEqual(len(explicit["semantic_units"]), 2)

    def test_provenance_order_does_not_change_core_hash(self):
        records = [
            {"record_id": "B", "text": "PauseController owns pause state"},
            {"record_id": "A", "text": "PauseController owns pause state"},
        ]
        first = impact.build_canonical_mandatory_planning_core({
            "requirements": [{"requirement_id": "REQ-1", "text": "PauseController owns pause state"}],
            "current_authority": records,
        })
        second = impact.build_canonical_mandatory_planning_core({
            "requirements": [{"requirement_id": "REQ-1", "text": "PauseController owns pause state"}],
            "current_authority": list(reversed(records)),
        })
        self.assertEqual(first["mandatory_core_hash"], second["mandatory_core_hash"])
        self.assertEqual(first["provenance_map"], second["provenance_map"])

    def test_role_specific_renderers_use_frozen_limits(self):
        requirements = [{"requirement_id": "REQ-1", "text": "Add a pause indicator."}]
        brain = {
            "task_goal": {"text": "Add a pause indicator."},
            "current_authority": [{"record_id": "AUTH-1", "text": "PauseController owns pause state"}],
            "preservation_constraints": [{"text": "Preserve Escape behavior."}],
        }
        impact_map = {"task_goal": "Add a pause indicator.", "impacts": [],
                      "integration_verification": [], "insufficient_evidence": []}
        challenger = impact.build_challenger_packet(
            impact_map, requirements, [], task_brain=brain, surface_registry={"surfaces": []},
            render=self._role_renderer("ImpactChallenger"),
            base_render=mini._impact_challenger_prompt,
        )
        self.assertTrue(challenger["packet_complete"], challenger.get("errors"))
        self.assertEqual(challenger["role_packet"]["hard_limit_chars"], 10000)
        self.assertLessEqual(challenger["role_packet"]["rendered_chars"], 10000)

        planning = impact.build_canonical_planning_packet(
            brain, requirements, [], surface_registry={"surfaces": []},
        )
        revision = impact.build_revision_packet(
            {
                "candidate_impact_map": impact_map,
                "validated_challenges": [],
                "planning_packet": planning["packet"],
            },
            render=self._role_renderer("ImpactPlanReviser"),
            base_render=mini._impact_revision_prompt,
        )
        self.assertTrue(revision["packet_complete"], revision.get("errors"))
        self.assertEqual(revision["role_packet"]["hard_limit_chars"], 10000)
        self.assertLessEqual(revision["role_packet"]["rendered_chars"], 10000)

    def test_mandatory_overflow_never_slices_or_calls_provider(self):
        packet = impact.build_planning_role_packet(
            "ImpactPlanner", {"requirements": [{"text": "M" * 700}]}, [],
            hard_limit=80, render=lambda value: "ENV:\n" + impact._compact_json(value),
        )
        self.assertEqual(packet["status"], impact.PLANNING_PACKET_MANDATORY_OVERFLOW)
        self.assertFalse(packet["packet_complete"])
        self.assertEqual(packet["mandatory_drops"], [])
        self.assertEqual(packet["exact_model_input"], packet["rendered_packet"])
        self.assertIn("M" * 700, packet["exact_model_input"])
        with patch.object(mini, "ask_ollama") as ask:
            with self.assertRaises(mini.PlanningPacketBudgetError) as raised:
                mini.structured_model_call(
                    "ignored", lambda value: True, "mandatory-overflow", {},
                    role="ImpactPlanner", role_packet=packet,
                )
        self.assertEqual(raised.exception.code, impact.PLANNING_PACKET_MANDATORY_OVERFLOW)
        ask.assert_not_called()
        self.assertEqual(mini.RUN["model_calls"], 0)

    def test_core_artifact_and_packet_keep_validation_separate(self):
        payload = {
            "task_goal": self.REQUIREMENT,
            "requirements": [{"requirement_id": "REQ-1", "text": self.REQUIREMENT}],
            "current_authority": [{
                "record_id": "AUTH-1", "text": "PauseController owns pause state",
                "fact_hash": "f" * 64,
            }],
            "planning_rules": ["PRESERVE_VERIFIED_STATE_UNLESS_PROVEN"],
        }
        core = impact.build_canonical_mandatory_planning_core(payload)
        compact = impact._canonical_mandatory_model_payload(payload, core)
        self.assertNotIn("source_record_ids", impact._compact_json(compact))
        self.assertIn("AUTH-1", impact._compact_json(core["provenance_map"]))
        packet = impact.build_planning_role_packet(
            "ImpactPlanner", compact, [], hard_limit=9000,
            render=lambda value: impact._compact_json(value),
            planning_core_hash=core["mandatory_core_hash"],
            mandatory_core_metrics=core["metrics"],
        )
        wrapped = {
            "packet": packet["payload"], "role_packet": packet,
            "canonical_mandatory_planning_core": core,
            "packet_complete": packet["packet_complete"],
            "selected_surface_ids": [],
        }
        self.assertTrue(impact.validate_planning_packet(wrapped)["valid"])
        self.assertTrue(impact.audit_current_vs_desired_representation(packet["payload"])["valid"])


if __name__ == "__main__":
    unittest.main()
