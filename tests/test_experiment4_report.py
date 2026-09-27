import unittest

from scripts.experiment4_report import format_markdown, report


def run(policy, first_applied=None):
    return {
        "mutation_grounding_policy": policy,
        "worker_progress_policy": "progress_constrained",
        "experiment_case_id": "rkey_01",
        "planning_route": "decomposition_first_recursive",
        "mission_advice_policy": "contract_fallback",
        "model": "gemma4:e4b",
        "source_sha256": "source",
        "mutation_grounding_source_sha256": "grounding-source",
        "experiment_subject_fingerprint": "subject",
        "project_mode": "EXISTING_PROJECT",
        "plan_approval": {"approval_status": "APPROVED", "plan_hash": "approved"},
        "experiment_events": [{"kind": "FIRST_WORKER_STARTED"}],
        "mutation_grounding_runs": [{
            "first_mutation_attempt_step": 3,
            "mutation_attempts": 2,
            "grounded_mutation_attempts": int(first_applied is not None),
            "rejected_mutation_attempts": 1,
            "bounded_refreshes": 1,
            "attempts": [{"tool_step": 3}, {"tool_step": 5}],
        }],
        "worker_progress_runs": [{
            "tool_steps": 6,
            "first_legal_mutation": first_applied,
            "events": [{"tool_step": 6, "tool": "run_command"}],
        }],
        "child_receipts": {"EXEC-001": {"verification_evidence": [
            {"tool": "read_file_range", "target": "index.html",
             "result": "[lines 90-100 of 558]\n90: ..."},
        ]}},
    }


class Experiment4ReportTests(unittest.TestCase):
    def test_distinguishes_file_change_from_verified_commit(self):
        current = run("current")
        grounded = run("evidence_grounded", {
            "tool_step": 5, "remaining_budget": 23,
        })
        result = report(current, grounded)
        summary = result["runs"]["evidence_grounded"]
        self.assertEqual(summary["grounded_attempt_percent"], 50.0)
        self.assertEqual(summary["first_applied_legal_mutation_step"], 5)
        self.assertTrue(summary["verification_attempted_after_mutation"])
        self.assertEqual(summary["read_ranges"], ["index.html:90-100"])
        self.assertFalse(summary["verified_child_commit"])
        self.assertIn("حالة واحدة لا تمثل نسبة نجاح عامة", format_markdown(result))

    def test_requires_same_source_and_progress_policy(self):
        current, grounded = run("current"), run("evidence_grounded")
        grounded["source_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "source_sha256"):
            report(current, grounded)


if __name__ == "__main__":
    unittest.main()
