import unittest

from scripts.experiment1_report import format_markdown, report


class Experiment1ReportTests(unittest.TestCase):
    def run_record(self, route, events, blocker=None):
        return {
            "run_id": route, "experiment_case_id": "pause-01",
            "planning_route": route, "source_sha256": "same-code",
            "experiment_subject_fingerprint": "same-subject", "model": "gemma4:e4b",
            "project_mode": "EXISTING_PROJECT",
            "experiment_events": [
                {"kind": kind, "elapsed_seconds": index + 1, "model_calls": index}
                for index, kind in enumerate(events)
            ],
            "first_blocker": blocker, "status": "failed" if blocker else "done",
        }

    def test_paired_report_shows_moved_first_blocker(self):
        baseline = self.run_record(
            "current_recursive", ["TASK_ACCEPTED", "TASK_BRAIN_READY", "BLOCKED"],
            {"stage": "GLOBAL_IMPACT_PLANNER", "reason": "PLAN_INCOMPLETE"},
        )
        experiment = self.run_record(
            "decomposition_first_recursive",
            ["TASK_ACCEPTED", "TASK_BRAIN_READY", "EARLY_SPLIT_READY",
             "APPROVAL_REQUIRED", "APPROVED", "FIRST_WORKER_STARTED",
             "CHILD_VERIFIED", "ROOT_VERIFIED"],
        )
        result = report([baseline, experiment])
        self.assertEqual(result["aggregate"]["current_recursive"]["pre_worker_blocked"], 1)
        self.assertEqual(result["aggregate"]["decomposition_first_recursive"]["worker_reached"], 1)
        self.assertEqual(result["aggregate"]["current_recursive"]["first_blocker_stages"],
                         {"GLOBAL_IMPACT_PLANNER": 1})
        self.assertEqual(result["aggregate"]["current_recursive"]["rates"]["worker_reached"],
                         {"count": 0, "total": 1, "percent": 0.0})
        self.assertEqual(result["aggregate"]["decomposition_first_recursive"]["rates"]["worker_reached"],
                         {"count": 1, "total": 1, "percent": 100.0})
        self.assertEqual(result["comparison"]["worker_reached_delta_percentage_points"], 100.0)
        self.assertIn("1/1 (100%)", format_markdown(result))

    def test_unpaired_cases_are_rejected(self):
        with self.assertRaises(ValueError):
            report([self.run_record("current_recursive", ["TASK_ACCEPTED"])])

    def test_approval_wait_is_excluded_from_worker_denominator(self):
        baseline = self.run_record("current_recursive", ["APPROVAL_REQUIRED"])
        experiment = self.run_record("decomposition_first_recursive", ["APPROVAL_REQUIRED"])
        baseline["status"] = experiment["status"] = "plan_approval_required"
        result = report([baseline, experiment])
        self.assertEqual(result["aggregate"]["current_recursive"]["rates"]["worker_reached"],
                         {"count": 0, "total": 0, "percent": None})
        self.assertEqual(result["aggregate"]["current_recursive"]["rates"]["awaiting_approval"],
                         {"count": 1, "total": 1, "percent": 100.0})
        self.assertIn("غير متاح", format_markdown(result))


if __name__ == "__main__":
    unittest.main()
