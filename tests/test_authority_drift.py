import copy
import unittest

from hivo.reentry import (
    AUTHORITY_IMPLEMENTATION_DRIFT,
    CONFIRMED_CONSISTENT,
    CONFIRMED_DRIFT,
    NOT_EVALUABLE,
    NOT_RELEVANT,
    classify_authority_repository_drift,
)


def _authority(record_id="AUTH-001", relation="owner(PAUSE_STATE) = PauseController"):
    return {
        "record_id": record_id,
        "fact_hash": f"fact-{record_id}",
        "fact": {
            "authority": "USER/REQUIREMENT",
            "field": "state_ownership",
            "fact": relation,
        },
    }


def _evidence(
    evidence_id="REPO-001",
    relation="owner(PAUSE_STATE) = PauseController",
    *,
    category="CURRENT_STATE_OWNER",
):
    return {
        "evidence_id": evidence_id,
        "category": category,
        "fact": relation,
    }


class AuthorityDriftClassificationTests(unittest.TestCase):
    def test_direct_structured_contradiction_is_confirmed_drift(self):
        authority = _authority()
        before = copy.deepcopy(authority)
        result = classify_authority_repository_drift(
            [authority], [_evidence(relation="owner(PAUSE_STATE) = StatusView")],
        )
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["kind"], AUTHORITY_IMPLEMENTATION_DRIFT)
        self.assertEqual(result["audit"][0]["classification"], CONFIRMED_DRIFT)
        self.assertTrue(result["audit"][0]["conflict_emitted"])
        self.assertEqual(result["metrics"]["authority_drift_confirmed"], 1)
        self.assertEqual(authority, before)

    def test_direct_structured_agreement_is_confirmed_consistent(self):
        result = classify_authority_repository_drift(
            [_authority()], [_evidence()],
        )
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["audit"][0]["classification"], CONFIRMED_CONSISTENT)
        self.assertFalse(result["audit"][0]["conflict_emitted"])
        self.assertEqual(result["metrics"]["authority_drift_consistent"], 1)

    def test_missing_semantic_evidence_is_not_evaluable(self):
        result = classify_authority_repository_drift(
            [_authority()],
            [{
                "evidence_id": "REPO-001",
                "category": "CURRENT_STATE_OWNER",
                "path": "src/status_view.js",
                "symbol": "StatusView",
                "fact": "StatusView owns paused state.",
                "support": "// a descriptive observation only",
            }],
        )
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["audit"][0]["classification"], NOT_EVALUABLE)
        self.assertFalse(result["audit"][0]["conflict_emitted"])
        self.assertEqual(result["metrics"]["authority_drift_not_evaluable"], 1)

    def test_unknown_or_unrelated_evidence_is_not_evaluable_not_drift(self):
        result = classify_authority_repository_drift(
            [_authority()],
            [{
                "evidence_id": "REPO-001",
                "category": "CURRENT_INTERFACE",
                "path": "src/status_view.js",
                "symbol": "StatusView.render",
                "fact": "src/status_view.js exists and exposes an interface.",
            }],
        )
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["audit"][0]["classification"], NOT_EVALUABLE)
        self.assertNotIn(
            AUTHORITY_IMPLEMENTATION_DRIFT,
            {item.get("kind") for item in result["conflicts"]},
        )

    def test_hash_comment_and_filename_changes_do_not_imply_semantic_drift(self):
        observations = [
            {
                "evidence_id": "REPO-001",
                "category": "CURRENT_OWNER",
                "path": "src/status_view.js",
                "symbol": "StatusView",
                "fact": "StatusView owns pause state.",
                "support": "// stage6a stale-evidence probe",
            },
            {
                "evidence_id": "REPO-002",
                "category": "CURRENT_OWNER",
                "path": "src/input.js",
                "symbol": "current",
                "fact": "src/input.js exists.",
                "file_sha256": "f" * 64,
            },
        ]
        result = classify_authority_repository_drift([_authority()], observations)
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["audit"][0]["classification"], NOT_EVALUABLE)
        self.assertEqual(result["metrics"]["authority_drift_confirmed"], 0)

    def test_explicit_mapping_relation_is_supported_without_filename_semantics(self):
        result = classify_authority_repository_drift(
            [_authority(relation="owner(PAUSE_STATE) = PauseController")],
            [{
                "evidence_id": "REPO-001",
                "category": "CURRENT_OWNER",
                "path": "renamed_surface.js",
                "subject": "PAUSE_STATE",
                "predicate": "OWNER",
                "object": "StatusView",
                "fact": "unrelated prose",
            }],
        )
        # The prose is intentionally not parsed; only the explicit structured
        # fields establish the incompatible implementation fact.
        self.assertEqual(result["audit"][0]["classification"], CONFIRMED_DRIFT)
        self.assertEqual(len(result["conflicts"]), 1)

    def test_equivalent_confirmed_contradictions_are_deduplicated(self):
        result = classify_authority_repository_drift(
            [_authority("AUTH-A"), _authority("AUTH-B")],
            [
                _evidence("REPO-001", "owner(PAUSE_STATE) = StatusView"),
                _evidence("REPO-002", "owner(PAUSE_STATE) = StatusView"),
            ],
        )
        self.assertEqual(len(result["conflicts"]), 1)
        self.assertEqual(result["conflicts"][0]["authority_record_ids"], ["AUTH-A", "AUTH-B"])
        self.assertEqual(result["conflicts"][0]["repository_evidence_ids"], ["REPO-001", "REPO-002"])
        self.assertGreaterEqual(result["metrics"]["authority_drift_duplicate_conflicts_suppressed"], 2)
        self.assertTrue(all(item["conflict_emitted"] for item in result["audit"]))

    def test_different_confirmed_contradictions_remain_separate(self):
        result = classify_authority_repository_drift(
            [_authority()],
            [
                _evidence("REPO-001", "owner(PAUSE_STATE) = StatusView"),
                _evidence("REPO-002", "owner(PAUSE_STATE) = InputManager"),
            ],
        )
        self.assertEqual(len(result["conflicts"]), 2)
        self.assertEqual(
            {item["repository_relation"]["object"] for item in result["conflicts"]},
            {"statusview", "inputmanager"},
        )

    def test_not_relevant_authority_fact_is_not_promoted_to_drift(self):
        result = classify_authority_repository_drift(
            [{
                "record_id": "AUTH-OTHER",
                "fact_hash": "fact-AUTH-OTHER",
                "fact": {
                    "authority": "USER/REQUIREMENT",
                    "field": "deployment_policy",
                    "fact": "Deployment policy is retained.",
                },
            }],
            [_evidence(relation="owner(PAUSE_STATE) = StatusView")],
        )
        self.assertEqual(result["conflicts"], [])
        self.assertEqual(result["audit"][0]["classification"], NOT_RELEVANT)

    def test_all_classification_paths_are_model_free(self):
        for evidence in (
            [_evidence(relation="owner(PAUSE_STATE) = StatusView")],
            [_evidence()],
            [],
        ):
            result = classify_authority_repository_drift([_authority()], evidence)
            self.assertEqual(result["model_calls"], 0)
            self.assertTrue(all(value == 0 for value in result["metrics"].values()) or result["metrics"]["authority_drift_checks"] == 1)


if __name__ == "__main__":
    unittest.main()
