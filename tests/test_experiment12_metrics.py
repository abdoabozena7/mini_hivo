import unittest

from scripts.experiment12_fixtures import CASES
from scripts.experiment12_report import browser_pass, gate_passes, rate, summarize, unit_pass


def trial(**changes):
    record = {"completed":True, "verification_executed":False, "verification_pass":False,
        "valid_receipt":False, "child_verified":False, "root_verified":False, "false_reject":False,
        "acceptance_needs_oracle_audit":False, "repairer_calls":0, "model_calls":10, "tool_calls":5,
        "elapsed_seconds":60, "safety_counters":{}, "tests_unchanged":True,
        "first_blocker":{"stage":"worker_mutation_grounding"}}
    from scripts.experiment12_report import SAFETY_KEYS
    record["safety_counters"] = dict.fromkeys(SAFETY_KEYS, 0)
    record.update(changes)
    return record


class Experiment12MetricTests(unittest.TestCase):
    def test_upstream_failure_does_not_dilute_pass_to_receipt_denominator(self):
        rows = [trial(), trial(verification_executed=True, verification_pass=True, valid_receipt=True,
                               child_verified=True, root_verified=True)]
        result = summarize(rows)
        self.assertEqual(result["valid_receipt_rate"], rate(1, 1))
        self.assertEqual(result["root_verified_rate"], rate(1, 2))
        self.assertEqual(result["model_calls_per_root_verified"], 20)
        self.assertEqual(result["seconds_per_root_verified"], 120)

    def test_empty_denominator_is_unavailable_and_zero_root_has_no_cost_ratio(self):
        result = summarize([trial()])
        self.assertIsNone(result["valid_receipt_rate"]["percent"])
        self.assertIsNone(result["model_calls_per_root_verified"])

    def test_page_load_and_fallback_function_call_cannot_count_keyboard_pass(self):
        case = CASES[0]
        payload = {"passed":True, "resolved_entrypoint":case["source"], "interaction_checks":[]}
        self.assertFalse(browser_pass(case, payload))
        payload["interaction_checks"] = [
            {"name":"keyboard_movement", "passed":True, "executed":True, "input":"game.move"},
            {"name":"touch_control", "passed":True, "executed":True, "input":"pointerdown"}]
        self.assertFalse(browser_pass(case, payload))
        payload["interaction_checks"][0]["input"] = "ArrowUp"
        self.assertTrue(browser_pass(case, payload))
        payload["resolved_entrypoint"] = "other.html"
        self.assertFalse(browser_pass(case, payload))

    def test_actual_timer_assertions_without_exp11_execution_flag_stay_in_denominator(self):
        case = CASES[2]
        payload = {"passed":True, "resolved_entrypoint":case["source"], "interaction_checks":[
            {"name":"timer_start_changes_visible_time", "passed":True, "before":{"seconds":120}, "after":{"seconds":119}},
            {"name":"timer_pause_freezes_visible_time", "passed":True, "before":{"seconds":119}, "after":{"seconds":119}},
            {"name":"timer_reset_restores_visible_time", "passed":True, "before":{"seconds":120}, "after":{"seconds":120}}]}
        self.assertTrue(browser_pass(case, payload))
        payload["interaction_checks"][1]["passed"] = False
        self.assertFalse(browser_pass(case, payload))

    def test_real_unit_suite_pass_required_instead_of_syntax_or_wrong_suite(self):
        case = CASES[3]
        item = {"tool":"run_command", "target":case["integration_target"], "result":"[exit_code=0]\nRan 5 tests in 0.01s\nOK"}
        self.assertTrue(unit_pass(case, [item]))
        self.assertFalse(unit_pass(case, [{**item, "target":"python tests/unrelated.py"}]))
        self.assertFalse(unit_pass(case, [{**item, "result":"[exit_code=0] syntax valid"}]))
        self.assertFalse(unit_pass(case, [{**item, "result":"[exit_code=1]\nRan 5 tests\nFAILED"}]))

    def test_pre_execution_or_old_worker_pass_does_not_count_as_completed_child(self):
        case = CASES[3]
        item = {"tool":"run_file", "target":case["test_target"], "result":"[exit_code=0]\nRan 5 tests\nOK"}
        gate = {"inputs":[{"status":"failed", "tool_evidence":[item]}, {"tool_evidence":[]}, {}]}
        self.assertFalse(gate_passes(case, gate))


if __name__ == "__main__":
    unittest.main()
