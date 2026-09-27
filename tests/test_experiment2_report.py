import unittest

from scripts.experiment2_report import format_markdown, report


class Experiment2ReportTests(unittest.TestCase):
    def run_record(self, policy, worker):
        return {
            "mission_advice_policy": policy,
            "experiment_case_id": "rkey-01",
            "planning_route": "decomposition_first_recursive",
            "model": "gemma4:e4b",
            "source_sha256": "same-code",
            "experiment_subject_fingerprint": "same-subject",
            "project_mode": "EXISTING_PROJECT",
            "plan_approval": {"approval_status": "APPROVED", "plan_hash": "same-plan"},
            "experiment_events": ([{"kind": "FIRST_WORKER_STARTED"}] if worker else []),
            "first_blocker": None if worker else {
                "stage": "MISSION_COMPILATION", "reason": "MISSION_COMPILATION_FAILURE",
            },
        }

    def test_report_tracks_fallback_worker_handoff_and_plan_identity(self):
        strict = self.run_record("strict", False)
        fallback = self.run_record("contract_fallback", True)
        fallback["mission_advice_fallbacks"] = 1
        result = report(strict, fallback)
        self.assertFalse(result["runs"]["strict"]["worker_started"])
        self.assertTrue(result["runs"]["contract_fallback"]["worker_started"])
        self.assertEqual(result["runs"]["contract_fallback"]["fallback_used"], 1)
        self.assertIn("Mission fallback مستخدمة", format_markdown(result))

    def test_mismatched_approved_plans_are_rejected(self):
        strict = self.run_record("strict", False)
        fallback = self.run_record("contract_fallback", True)
        fallback["plan_approval"]["plan_hash"] = "different"
        with self.assertRaises(ValueError):
            report(strict, fallback)


if __name__ == "__main__":
    unittest.main()
