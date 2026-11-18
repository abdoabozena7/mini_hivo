import unittest

from scripts.experiment3_report import format_markdown, report


def run(policy, mutation=None):
    return {
        "worker_progress_policy": policy,
        "experiment_case_id": "rkey_01",
        "planning_route": "decomposition_first_recursive",
        "mission_advice_policy": "contract_fallback",
        "model": "gemma4:e4b",
        "source_sha256": "source",
        "experiment_subject_fingerprint": "subject",
        "project_mode": "EXISTING_PROJECT",
        "plan_approval": {"approval_status": "APPROVED", "plan_hash": "approved"},
        "experiment_events": [{"kind": "FIRST_WORKER_STARTED"}],
        "worker_progress_runs": [{
            "tool_steps": 5,
            "pre_mutation_read_steps": 1,
            "unique_evidence": 1,
            "repeated_inspections": 0,
            "repeated_gate_checks": 2,
            "same_file_revisits_without_new_info": 0,
            "invalid_rejected_tool_calls": 2,
            "first_legal_mutation": mutation,
        }],
        "first_blocker": {"stage": "WORKER_PROGRESS", "reason": "WORKER_NO_MUTATION_PROGRESS"},
    }


class Experiment3ReportTests(unittest.TestCase):
    def test_reports_mutation_and_percent_without_inventing_success_rate(self):
        mutation = {"tool_step": 4, "model_round": 6, "remaining_budget": 22}
        result = report(run("current"), run("progress_constrained", mutation))
        constrained = result["runs"]["progress_constrained"]
        self.assertEqual(constrained["steps_to_first_legal_mutation"], 4)
        self.assertEqual(constrained["budget_remaining_at_first_mutation"], 22)
        self.assertEqual(constrained["budget_usage_percent_before_mutation"], 21.4)
        self.assertIn("حالة واحدة لا تمثل نسبة نجاح عامة", format_markdown(result))

    def test_rejects_unpaired_snapshot(self):
        current, constrained = run("current"), run("progress_constrained")
        constrained["experiment_subject_fingerprint"] = "other"
        with self.assertRaisesRegex(ValueError, "experiment_subject_fingerprint"):
            report(current, constrained)


if __name__ == "__main__":
    unittest.main()
