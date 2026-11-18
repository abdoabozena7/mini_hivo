import unittest

from hivo.failure_decision import classify_mutation_exhaustion


class MutationExhaustionTests(unittest.TestCase):
    def test_only_validator_refusals_keep_the_specific_terminal_code(self):
        categories = ("TOOL_ARGUMENT_REJECTED" for _ in range(4))
        self.assertEqual(classify_mutation_exhaustion(categories), "MUTATION_ARGUMENT_RETRIES_EXHAUSTED")

    def test_mixed_failures_remain_neutral_in_either_order(self):
        for other in ("STALE_TARGET", "SYNTAX_INVALID_MUTATION", "MISSING_TARGET",
                      "SAFETY_REJECTED_MUTATION", "ENVIRONMENT_FAILURE", "INVALID_MUTATION"):
            categories = ["TOOL_ARGUMENT_REJECTED", other] * 2
            for episode in (categories, categories[::-1]):
                with self.subTest(episode=episode):
                    self.assertEqual(classify_mutation_exhaustion(episode), "WORKER_NO_MUTATION_PROGRESS")

    def test_repeating_one_non_schema_failure_does_not_make_it_scope_evidence(self):
        for category in ("STALE_TARGET", "SYNTAX_INVALID_MUTATION", "SAFETY_REJECTED_MUTATION"):
            with self.subTest(category=category):
                self.assertEqual(classify_mutation_exhaustion([category] * 4), "WORKER_NO_MUTATION_PROGRESS")

    def test_absent_or_unqualified_categories_do_not_promote_a_diagnosis(self):
        for categories in ([], ["TOOL_ARGUMENT_REJECTED"] * 3 + [None],
                           ["TASK_TOO_BROAD"] * 4,
                           ["TOOL_ARGUMENT_REJECTED: missing start_line"] * 4):
            with self.subTest(categories=categories):
                self.assertEqual(classify_mutation_exhaustion(categories), "WORKER_NO_MUTATION_PROGRESS")
