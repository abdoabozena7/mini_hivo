import unittest

from scripts.experiment5_report import format_markdown, report


EXPECTED = {"path": "index.html", "start_line": 406, "end_line": 411}


def run(policy):
    return {
        "target_locator_policy": policy,
        "worker_progress_policy": "progress_constrained",
        "mutation_grounding_policy": "evidence_grounded",
        "experiment_case_id": "rkey_01",
        "planning_route": "decomposition_first_recursive",
        "model": "gemma4:e4b",
        "source_sha256": "mini",
        "worker_progress_source_sha256": "progress",
        "mutation_grounding_source_sha256": "grounding",
        "target_locator_source_sha256": "locator",
        "experiment_subject_fingerprint": "subject",
        "mission_advice_policy": "contract_fallback",
        "project_mode": "EXISTING_PROJECT",
        "plan_approval": {"approval_status": "APPROVED", "plan_hash": "approved"},
        "experiment_events": [{"kind": "FIRST_WORKER_STARTED"}],
        "target_locator_runs": [{"candidates": [
            {"candidate_id": "LOC-001", "path": "index.html",
             "start_line": 397, "end_line": 411},
        ]}],
        "worker_read_spans": [
            {"task_id": "EXEC-001", "tool_step": 2, "path": "index.html",
             "start_line": 90, "end_line": 100},
            {"task_id": "EXEC-001", "tool_step": 4, "path": "index.html",
             "start_line": 397, "end_line": 411},
        ],
        "worker_progress_runs": [{"first_legal_mutation": {"tool_step": 5,
                                                           "remaining_budget": 23},
                                  "events": [{"tool_step": 6, "tool": "run_command"}]}],
        "mutation_grounding_runs": [{"mutation_attempts": 2,
                                     "grounded_mutation_attempts": 1}],
    }


class Experiment5ReportTests(unittest.TestCase):
    def test_reports_top1_relevant_read_and_grounding_ratio(self):
        result = report(run("current"), run("evidence_directed"), EXPECTED)
        directed = result["runs"]["evidence_directed"]
        self.assertTrue(directed["true_target_top1"])
        self.assertTrue(directed["true_target_top3"])
        self.assertEqual(directed["first_relevant_bounded_read_step"], 4)
        self.assertEqual(directed["irrelevant_bounded_reads"], 1)
        self.assertEqual(directed["grounded_attempt_percent"], 50.0)
        self.assertTrue(directed["verification_attempted_after_change"])
        self.assertIn("حالة واحدة لا تمثل نسبة نجاح عامة", format_markdown(result))

    def test_rejects_different_locator_code(self):
        current, directed = run("current"), run("evidence_directed")
        directed["target_locator_source_sha256"] = "different"
        with self.assertRaisesRegex(ValueError, "target_locator_source_sha256"):
            report(current, directed, EXPECTED)


if __name__ == "__main__":
    unittest.main()
