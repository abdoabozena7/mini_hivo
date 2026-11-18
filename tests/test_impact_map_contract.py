import json
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import impact_planning as impact


class ImpactMapContractTests(unittest.TestCase):
    def canonical(self, **overrides):
        value = {
            "impacts": [{
                "impact_id": "IMPACT-001",
                "disposition": "MUST_CHANGE",
                "requirement_ids": ["REQ-001"],
                "reason": "Change the explicitly requested behavior.",
            }],
        }
        value.update(overrides)
        return value

    def test_canonical_impact_map_needs_no_normalization(self):
        candidate = self.canonical()
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["source_envelope"], "CANONICAL_ALREADY")
        self.assertEqual(result["canonicalization"], "NOT_NEEDED")
        self.assertEqual(result["canonical_candidate"], candidate)
        self.assertTrue(impact.validate_planner_output(candidate, []))

    def test_prompt_and_schema_agree_on_canonical_envelope(self):
        prompt = mini._impact_planner_prompt({"task_goal": "generic task"})
        schema = impact.impact_map_schema()
        self.assertIn("{\"impacts\":[...]}", prompt)
        self.assertIn("impact_decisions wrapper", prompt)
        self.assertIn("numbered top-level keys", prompt)
        self.assertIn("impacts", schema["properties"])
        self.assertIn("impact_id", schema["properties"]["impacts"]["items"]["required"])
        self.assertIn("disposition", schema["properties"]["impacts"]["items"]["required"])
        self.assertIn("requirement_ids", schema["properties"]["impacts"]["items"]["required"])

    def test_legacy_impact_decisions_are_canonicalized(self):
        candidate = {
            "impact_decisions": [{
                "impact_id": "IMPACT-001",
                "source_requirement_ids": ["REQ-001"],
                "action": "MUST_CHANGE",
                "reason": "Change the requested behavior.",
            }],
        }
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["source_envelope"], "LEGACY_IMPACT_DECISIONS")
        entry = result["canonical_candidate"]["impacts"][0]
        self.assertEqual(entry["impact_id"], "IMPACT-001")
        self.assertEqual(entry["requirement_ids"], ["REQ-001"])
        self.assertEqual(entry["disposition"], "MUST_CHANGE")
        self.assertEqual(entry["action"], "Change the requested behavior.")
        self.assertTrue(impact.validate_planner_output(candidate, []))

    def test_top_level_impact_ids_are_sorted_and_preserved(self):
        candidate = {
            "IMPACT-002": {
                "source_requirements": "REQ-002",
                "action": "INTERFACE_REUSE",
                "reason": "Reuse the current interface.",
            },
            "IMPACT-001": {
                "source_requirements": ["REQ-001"],
                "action": "MUST_CHANGE",
                "reason": "Change the requested behavior.",
            },
        }
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(result["valid"], result)
        entries = result["canonical_candidate"]["impacts"]
        self.assertEqual([item["impact_id"] for item in entries], ["IMPACT-001", "IMPACT-002"])
        self.assertEqual(entries[1]["requirement_ids"], ["REQ-002"])
        self.assertEqual(entries[1]["disposition"], "INTERFACE_REUSE")
        self.assertTrue(impact.validate_planner_output(candidate, []))

    def test_mixed_legacy_metadata_is_only_mapped_when_unambiguous(self):
        candidate = {
            "impact_decisions": [{
                "impact_id": "IMPACT-001",
                "source_requirement_ids": ["REQ-001"],
                "action": "MUST_CHANGE",
                "reason": "Change the requested behavior.",
            }],
            "canonical_interface_reuses": [],
            "preservation_promises": [],
            "verification_contracts": [],
            "verification_test_contracts": ["Run the focused verification."],
        }
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(result["valid"], result)
        canonical = result["canonical_candidate"]
        self.assertEqual(canonical["integration_verification"], ["Run the focused verification."])
        self.assertNotIn("impact_decisions", canonical)

    def test_missing_semantic_information_is_not_fabricated(self):
        candidate = {
            "impact_decisions": [{
                "impact_id": "IMPACT-001",
                "action": "MUST_CHANGE",
                "reason": "Change the requested behavior.",
            }],
        }
        normalized = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(normalized["valid"], normalized)
        self.assertNotIn("requirement_ids", normalized["canonical_candidate"]["impacts"][0])
        validation = impact.validate_planner_output_detailed(candidate, requirements=[])
        self.assertFalse(validation["valid"])
        self.assertEqual(validation["reason_code"], impact.IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING)

    def test_ambiguous_envelope_is_rejected(self):
        candidate = {
            "impacts": [self.canonical()["impacts"][0]],
            "impact_decisions": [self.canonical()["impacts"][0]],
        }
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason_code"], impact.IMPACT_MAP_CANONICALIZATION_FAILED)

    def test_unknown_semantic_field_is_rejected_conservatively(self):
        candidate = self.canonical()
        candidate["impacts"][0]["semantic_override"] = "meaningful unknown claim"
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertFalse(result["valid"])
        self.assertIn("unrecognized fields", " ".join(result["errors"]))

    def test_malformed_json_still_fails_in_existing_parser(self):
        with self.assertRaises((ValueError, json.JSONDecodeError)):
            mini._parse_json_content('{"impacts": [}')

    def test_ids_and_provenance_are_preserved(self):
        candidate = {
            "impact_decisions": [{
                "impact_id": "IMPACT-009",
                "source_requirement_ids": ["REQ-009"],
                "repository_evidence_ids": ["REPO-009"],
                "action": "VERIFY_ONLY",
                "reason": "Verify the existing behavior.",
                "provenance": "MODEL_OUTPUT",
            }],
        }
        result = impact.canonicalize_impact_map_candidate(candidate)
        self.assertTrue(result["valid"], result)
        entry = result["canonical_candidate"]["impacts"][0]
        self.assertEqual(entry["impact_id"], "IMPACT-009")
        self.assertEqual(entry["requirement_ids"], ["REQ-009"])
        self.assertEqual(entry["repository_evidence_ids"], ["REPO-009"])
        self.assertEqual(entry["provenance"], "MODEL_OUTPUT")

    def test_supported_legacy_and_canonical_forms_are_semantically_equivalent(self):
        canonical = {
            "impacts": [
                {"impact_id": "IMPACT-001", "disposition": "MUST_CHANGE",
                 "requirement_ids": ["REQ-001"], "action": "Change the owner."},
                {"impact_id": "IMPACT-002", "disposition": "PRESERVATION_ONLY",
                 "requirement_ids": ["REQ-002"], "reason": "Preserve the owner."},
            ],
        }
        legacy = {
            "IMPACT-002": {
                "source_requirements": "REQ-002", "action": "PRESERVATION_ONLY",
                "reason": "Preserve the owner.",
            },
            "IMPACT-001": {
                "source_requirement_ids": ["REQ-001"], "action": "MUST_CHANGE",
                "reason": "Change the owner.",
            },
        }
        canonical_result = impact.canonicalize_impact_map_candidate(canonical)
        legacy_result = impact.canonicalize_impact_map_candidate(legacy)
        self.assertTrue(canonical_result["valid"], canonical_result)
        self.assertTrue(legacy_result["valid"], legacy_result)

        def semantic_projection(result):
            return sorted((
                item["impact_id"], item["disposition"], tuple(item["requirement_ids"]),
                item.get("action") or item.get("reason"),
            ) for item in result["canonical_candidate"]["impacts"])

        self.assertEqual(semantic_projection(canonical_result), semantic_projection(legacy_result))

    def test_duplicate_impact_ids_are_semantically_rejected(self):
        candidate = {
            "impact_decisions": [
                {"impact_id": "IMPACT-001", "source_requirement_ids": ["REQ-001"],
                 "action": "MUST_CHANGE", "reason": "Change it."},
                {"impact_id": "IMPACT-001", "source_requirement_ids": ["REQ-001"],
                 "action": "VERIFY_ONLY", "reason": "Verify it."},
            ],
        }
        result = impact.validate_planner_output_detailed(candidate, requirements=[])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason_code"], impact.IMPACT_MAP_SEMANTIC_VALIDATION_FAILED)

    def test_normalization_precedes_hydration_without_downstream_bypass(self):
        mini.reset_run("impact-map-contract-test")
        brain = {
            "task_goal": "Change owner behavior",
            "repository_evidence_ids": ["REPO-001"],
            "current_owners": [{
                "path": "src/x.py", "symbol": "Owner", "evidence_ids": ["REPO-001"],
                "category": "CURRENT_OWNER", "text": "Owner controls behavior",
            }],
        }
        evidence = [{
            "evidence_id": "REPO-001", "category": "CURRENT_OWNER", "path": "src/x.py",
            "symbol": "Owner", "fact": "Owner controls behavior", "line_start": 1,
            "line_end": 2, "file_sha256": "a" * 64,
        }]
        contract = {"requirements": ["Change owner behavior"]}
        legacy = {
            "impact_decisions": [{
                "impact_id": "IMPACT-001", "source_requirement_ids": ["REQ-001"],
                "action": "MUST_CHANGE", "reason": "Change the owner behavior.",
            }],
        }
        with patch.object(
            mini.stage3, "hydrate_impact_map", wraps=impact.hydrate_impact_map,
        ) as hydrate:
            result = mini.create_impact_map(
                brain, contract, evidence, structured_call=lambda *_args: legacy,
            )
        self.assertTrue(result["hydration_valid"])
        passed = hydrate.call_args.args[0]
        self.assertIn("impacts", passed)
        self.assertNotIn("impact_decisions", passed)
        self.assertIn("IMPACT_MAP", mini.RUN["control_flow"])

    def test_invalid_semantic_map_remains_blocked(self):
        candidate = {
            "IMPACT-001": {
                "disposition": "MUST_CHANGE",
                "reason": "A change is needed.",
            },
        }
        result = impact.validate_planner_output_detailed(candidate, requirements=[])
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason_code"], impact.IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING)

    def test_deterministic_contract_benchmark_has_no_false_semantic_acceptances(self):
        cases = [
            ("canonical", self.canonical()),
            ("legacy_wrapper", {
                "impact_decisions": [{"impact_id": "IMPACT-001",
                                       "source_requirement_ids": ["REQ-001"],
                                       "action": "MUST_CHANGE", "reason": "Change it."}],
            }),
            ("top_level_ids", {
                "IMPACT-001": {"source_requirements": "REQ-001",
                                "action": "MUST_CHANGE", "reason": "Change it."},
                "IMPACT-002": {"source_requirements": "REQ-002",
                                "action": "PRESERVATION_ONLY", "reason": "Keep it."},
            }),
            ("optional_metadata", {
                **self.canonical(), "integration_verification": [], "insufficient_evidence": [],
            }),
            ("missing_required", {"impact_decisions": [{"impact_id": "IMPACT-001",
                                                           "action": "MUST_CHANGE",
                                                           "reason": "Change it."}]}),
            ("ambiguous", {"impacts": self.canonical()["impacts"],
                            "impact_decisions": self.canonical()["impacts"]}),
            ("unknown_semantic", {"impacts": [{**self.canonical()["impacts"][0],
                                                  "semantic_override": "unknown"}]}),
            ("multiple_preserve_change", {
                "impact_decisions": [
                    {"impact_id": "IMPACT-001", "source_requirement_ids": ["REQ-001"],
                     "action": "MUST_CHANGE", "reason": "Change it."},
                    {"impact_id": "IMPACT-002", "source_requirement_ids": ["REQ-002"],
                     "action": "PRESERVATION_ONLY", "reason": "Keep it."},
                ],
            }),
            ("unsupported_new_surface", {
                "IMPACT-001": {"source_requirements": "REQ-001",
                                "action": "MUST_CHANGE", "reason": "Change it."},
                "NEW_SURFACE_PROPOSAL": {"surface_id": "SURF-NEW", "description": "new"},
            }),
            ("malformed_json", '{"impacts": [}'),
        ]
        metrics = Counter()
        for name, candidate in cases:
            metrics["cases"] += 1
            if isinstance(candidate, str):
                try:
                    candidate = mini._parse_json_content(candidate)
                except (ValueError, json.JSONDecodeError):
                    metrics["parse_failures"] += 1
                    continue
            result = impact.validate_planner_output_detailed(candidate, requirements=[])
            if result["valid"]:
                metrics["canonical_valid"] += 1
                if result["canonicalization"] == "APPLIED":
                    metrics["normalized_valid"] += 1
            else:
                metrics["correctly_rejected"] += 1
            if result["valid"] and result.get("errors"):
                metrics["false_semantic_acceptances"] += 1
            if name == "missing_required":
                self.assertFalse(result["valid"])
        print("IMPACT_MAP_CONTRACT_BENCHMARK", json.dumps(metrics, sort_keys=True))
        self.assertEqual(metrics["false_semantic_acceptances"], 0)

    def test_captured_diagnostic_responses_replay_without_provider_calls(self):
        root = Path(
            r"D:\projects\Ai\mini_hivo_eval_harness\live_runs\HIVO-CORE-EXPOSURE-INTEGRATED-LIFECYCLE-V1_CURRENT_NATIVE_DIAGNOSTIC_LIVE-2\planner_raw"
        )
        paths = sorted(root.glob("PN*_call_1_attempt_1.txt"))
        if not paths:
            self.skipTest("DIAGNOSTIC_LIVE-2 raw planner artifacts are not available")
        self.assertEqual([path.name.split("_", 1)[0] for path in paths], [f"PN{i:02d}" for i in range(1, 25)])
        results = []
        for path in paths:
            parsed = mini._parse_json_content(path.read_text(encoding="utf-8"))
            results.append(impact.validate_planner_output_detailed(parsed, requirements=[]))
        counts = Counter("VALID" if item["valid"] else item["reason_code"] for item in results)
        self.assertEqual(sum(counts.values()), 24)
        self.assertEqual(counts["VALID"], 9)
        self.assertEqual(counts[impact.IMPACT_MAP_REQUIRED_SEMANTIC_FIELD_MISSING], 11)
        self.assertEqual(counts[impact.IMPACT_MAP_SEMANTIC_VALIDATION_FAILED], 2)
        self.assertEqual(counts[impact.IMPACT_MAP_UNSUPPORTED_ENVELOPE], 2)


if __name__ == "__main__":
    unittest.main()
