import unittest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from hivo.run_budget import RunBudget, RunBudgetExceeded


class Clock:
    def __init__(self, now=100.0):
        self.now = now

    def __call__(self):
        return self.now


class RunBudgetTests(unittest.TestCase):
    def assert_denied(self, budget, resource, exhausted):
        with self.assertRaises(RunBudgetExceeded) as denied:
            budget.claim(resource)
        self.assertEqual(denied.exception.resource, exhausted)

    def test_one_run_charges_across_roles_and_retries_before_dispatch(self):
        budget = RunBudget(max_model_calls=2, max_tool_calls=1, clock=Clock())
        dispatched = []

        def dispatch(resource, role, fail=False):
            budget.claim(resource)
            dispatched.append((resource, role))
            if fail:
                raise RuntimeError("scripted failed dispatch")

        with self.assertRaisesRegex(RuntimeError, "^scripted failed dispatch$"):
            dispatch("model", "Planner", fail=True)
        dispatch("model", "Worker")
        with self.assertRaises(RunBudgetExceeded) as denied:
            dispatch("model", "Falsifier")
        self.assertEqual(denied.exception.resource, "model")
        dispatch("tool", "Worker")
        with self.assertRaises(RunBudgetExceeded) as denied:
            dispatch("tool", "Repairer")
        self.assertEqual(denied.exception.resource, "tool")

        self.assertEqual(dispatched, [
            ("model", "Planner"), ("model", "Worker"), ("tool", "Worker"),
        ])
        self.assertEqual(budget.snapshot(), {
            "max_model_calls": 2,
            "max_tool_calls": 1,
            "max_elapsed_seconds": None,
            "model_calls": 2,
            "tool_calls": 1,
            "elapsed_seconds": 0.0,
            "remaining_seconds": None,
        })

    def test_fractional_deadline_denies_both_at_the_boundary(self):
        clock = Clock()
        budget = RunBudget(max_elapsed_seconds=0.1, clock=clock)
        self.assertEqual(budget.remaining_seconds(), 0.1)
        clock.now = 100.0625
        self.assertAlmostEqual(budget.remaining_seconds(), 0.0375)
        budget.claim("model")

        # 100.1 - 100.0 is a little below 0.1 in binary floating point.
        clock.now = 100.1
        self.assert_denied(budget, "tool", "elapsed")
        self.assert_denied(budget, "model", "elapsed")
        self.assertEqual(budget.remaining_seconds(), 0.0)
        before = budget.snapshot()
        clock.now = 102
        after = budget.snapshot()
        self.assertGreater(after["elapsed_seconds"], before["elapsed_seconds"])
        self.assertEqual((after["model_calls"], after["tool_calls"]), (1, 0))
        self.assertEqual(after["remaining_seconds"], 0.0)

    def test_zero_limits_never_dispatch_the_matching_call(self):
        budget = RunBudget(max_model_calls=0, clock=Clock())
        self.assert_denied(budget, "model", "model")
        budget.claim("tool")
        budget = RunBudget(max_tool_calls=0, clock=Clock())
        self.assert_denied(budget, "tool", "tool")
        budget.claim("model")
        budget = RunBudget(max_elapsed_seconds=0, clock=Clock())
        self.assert_denied(budget, "model", "elapsed")
        self.assert_denied(budget, "tool", "elapsed")

    def test_unlimited_defaults_keep_tally_and_each_run_starts_fresh(self):
        clock = Clock()
        budget = RunBudget(clock=clock)
        clock.now += 1000
        for _ in range(100):
            budget.claim("model")
            budget.claim("tool")
        self.assertIsNone(budget.remaining_seconds())
        snapshot = budget.snapshot()
        self.assertEqual((snapshot["model_calls"], snapshot["tool_calls"]), (100, 100))
        snapshot["model_calls"] = 0
        self.assertEqual(budget.snapshot()["model_calls"], 100)
        fresh = RunBudget(max_model_calls=1, max_elapsed_seconds=1, clock=clock)
        self.assertEqual(fresh.remaining_seconds(), 1)
        fresh.claim("model")
        self.assertEqual(fresh.snapshot()["model_calls"], 1)

    def test_invalid_limits_and_claims_do_not_become_unlimited(self):
        for limit in ("max_model_calls", "max_tool_calls", "max_elapsed_seconds"):
            for value in (True, -1, "1", float("nan"), float("inf")):
                with self.subTest(limit=limit, value=value):
                    with self.assertRaises(ValueError):
                        RunBudget(**{limit: value})
        for limit in ("max_model_calls", "max_tool_calls"):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                RunBudget(**{limit: 1.5})
        budget = RunBudget(clock=Clock())
        with self.assertRaises(ValueError):
            budget.claim("other")
        self.assertEqual(budget.snapshot()["model_calls"], 0)
        self.assertEqual(budget.snapshot()["tool_calls"], 0)

    def test_bad_clock_does_not_regain_time_or_admit_more_work(self):
        for bad_reading in (100.5, float("nan"), float("inf")):
            with self.subTest(bad_reading=bad_reading):
                clock = Clock()
                budget = RunBudget(max_elapsed_seconds=10, clock=clock)
                clock.now = 101
                budget.claim("model")
                clock.now = bad_reading
                self.assert_denied(budget, "tool", "elapsed")
                clock.now = 102
                self.assert_denied(budget, "model", "elapsed")
                snapshot = budget.snapshot()
                self.assertEqual(snapshot["elapsed_seconds"], 1.0)
                self.assertEqual(snapshot["remaining_seconds"], 0.0)
                self.assertEqual((snapshot["model_calls"], snapshot["tool_calls"]), (1, 0))

    def test_competing_claims_cannot_overspend(self):
        budget = RunBudget(max_model_calls=7, clock=Clock())
        start = Barrier(8, timeout=10)

        def contend(_):
            start.wait()
            admitted = 0
            for _ in range(12):
                try:
                    budget.claim("model")
                except RunBudgetExceeded as denied:
                    self.assertEqual(denied.resource, "model")
                else:
                    admitted += 1
            return admitted

        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertEqual(sum(pool.map(contend, range(8))), 7)
        self.assertEqual(budget.snapshot()["model_calls"], 7)
