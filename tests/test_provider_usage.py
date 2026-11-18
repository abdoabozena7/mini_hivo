import json
import unittest

from hivo.provider_usage import record_provider_usage


# Reconstructed from the response keys in the 2026-11-17 e2e-greeting-auto-03
# model_response_shape log. Message content and numeric values are synthetic.
CHAT_RESPONSE = """{
    "model": "gemma4:e4b",
    "created_at": "2026-11-17T00:20:22.000Z",
    "message": {
        "role": "assistant",
        "content": "",
        "tool_calls": [
            {"function": {"name": "read_file", "arguments": {"path": "status.py"}}}
        ]
    },
    "done": true,
    "done_reason": "stop",
    "total_duration": 1020271600,
    "load_duration": 14202500,
    "prompt_eval_count": 764,
    "prompt_eval_cached_count": 700,
    "prompt_eval_duration": 208123400,
    "eval_count": 38,
    "eval_duration": 797945700
}"""


class ProviderUsageTests(unittest.TestCase):
    def test_counts_raw_envelopes_for_primary_and_auxiliary_roles(self):
        usage = {}
        self.assertIsNone(record_provider_usage(usage, "Builder", json.loads(CHAT_RESPONSE)))
        # A failed attempt can still report usage; its error does not erase it.
        record_provider_usage(usage, "Builder", {"error": "runner stopped", "prompt_eval_count": 7})
        record_provider_usage(usage, "Clarifier", {"eval_count": 9})
        record_provider_usage(usage, "Falsifier", None)  # Timeout, no decoded body.

        self.assertEqual(json.loads(json.dumps(usage, allow_nan=False)), {
            "total": {
                "attempts": 4, "prompt_eval_count": 771, "eval_count": 47,
                "missing_prompt_eval_count": 2, "missing_eval_count": 2,
            },
            "by_role": {
                "Builder": {
                    "attempts": 2, "prompt_eval_count": 771, "eval_count": 38,
                    "missing_prompt_eval_count": 0, "missing_eval_count": 1,
                },
                "Clarifier": {
                    "attempts": 1, "prompt_eval_count": None, "eval_count": 9,
                    "missing_prompt_eval_count": 1, "missing_eval_count": 0,
                },
                "Falsifier": {
                    "attempts": 1, "prompt_eval_count": None, "eval_count": None,
                    "missing_prompt_eval_count": 1, "missing_eval_count": 1,
                },
            },
        })

    def test_reported_zero_is_not_missing_and_survives_later_missing_data(self):
        usage = {}
        record_provider_usage(usage, "Quality", {"eval_count": 0})
        record_provider_usage(usage, "Quality", [{"prompt_eval_count": 6, "eval_count": 7}])
        record_provider_usage(usage, "ImpactPlanner", {"prompt_eval_count": 0})

        for row in (usage["total"], usage["by_role"]["Quality"]):
            self.assertIs(type(row["eval_count"]), int)
            self.assertEqual(row["eval_count"], 0)
        self.assertIs(type(usage["total"]["prompt_eval_count"]), int)
        self.assertEqual(usage["total"], {
            "attempts": 3, "prompt_eval_count": 0, "eval_count": 0,
            "missing_prompt_eval_count": 2, "missing_eval_count": 2,
        })
        self.assertIsNone(usage["by_role"]["Quality"]["prompt_eval_count"])
        self.assertIsNone(usage["by_role"]["ImpactPlanner"]["eval_count"])

    def test_rejects_invalid_count_types_without_dropping_the_other_count(self):
        for invalid in (True, False, -1, 4.0, "4", None, [], {"count": 4}):
            with self.subTest(invalid=invalid):
                usage = {}
                record_provider_usage(usage, "Repairer", {"prompt_eval_count": invalid, "eval_count": 4})
                record_provider_usage(usage, "Repairer", {"prompt_eval_count": 5, "eval_count": invalid})
                expected = {
                    "attempts": 2, "prompt_eval_count": 5, "eval_count": 4,
                    "missing_prompt_eval_count": 1, "missing_eval_count": 1,
                }
                self.assertEqual(usage, {"total": expected, "by_role": {"Repairer": expected}})


if __name__ == "__main__":
    unittest.main()
