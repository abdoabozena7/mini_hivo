"""Unit and boundary tests for hivo.hyperparams and hivo.job_runtime option validation."""

from __future__ import annotations

import time
import unittest
from unittest.mock import patch

from hivo import job_runtime as runtime
from hivo.hyperparams import (
    DECODING_POLICIES,
    PRIME_SEED_STRIDE,
    resolve_decoding_options,
    validate_decoding_policy,
)


def _valid_chat_payload(options: dict) -> dict:
    return {
        "model": runtime.GEMMA_MODEL,
        "messages": [{"role": "user", "content": "probe"}],
        "options": options,
    }


class HyperparamsAndRuntimeValidationTests(unittest.TestCase):
    def test_validate_decoding_policy_accepts_known_and_rejects_unknown(self):
        self.assertEqual(DECODING_POLICIES, ("fixed", "adaptive"))
        self.assertEqual(validate_decoding_policy("fixed"), "fixed")
        self.assertEqual(validate_decoding_policy("adaptive"), "adaptive")
        self.assertEqual(validate_decoding_policy("  Adaptive "), "adaptive")
        for invalid in ("greedy", "beam", "", None, 1, True):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    validate_decoding_policy(invalid)  # type: ignore[arg-type]

    def test_fixed_policy_preserves_exact_legacy_options_dict(self):
        options = resolve_decoding_options("Builder", policy="fixed")
        self.assertEqual(options, {"temperature": 0.1, "seed": 0})
        self.assertEqual(set(options.keys()), {"temperature", "seed"})
        self.assertIs(type(options["temperature"]), float)
        self.assertIs(type(options["seed"]), int)
        # Default policy is also "fixed" even when epoch/stagnant/structured are set.
        default_opts = resolve_decoding_options(
            "Builder", structured=True, epoch=3, stagnant_count=2
        )
        self.assertEqual(default_opts, {"temperature": 0.1, "seed": 0})

    def test_fixed_policy_respects_base_temperature_override_and_seed_base(self):
        self.assertEqual(
            resolve_decoding_options("Planner", policy="fixed", base_temperature=0.0, seed_base=42),
            {"temperature": 0.0, "seed": 42},
        )
        self.assertEqual(
            resolve_decoding_options(
                "Builder",
                policy="fixed",
                base_temperature=0.1,
                temperature_override=0.25,
                seed_base=11,
            ),
            {"temperature": 0.25, "seed": 11},
        )

    def test_adaptive_structured_calls_use_analytical_schema_strict_tier(self):
        clean = resolve_decoding_options("Builder", policy="adaptive", structured=True)
        self.assertEqual(
            clean,
            {
                "temperature": 0.05,
                "min_p": 0.05,
                "top_p": 0.85,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 0,
            },
        )
        retried = resolve_decoding_options(
            "Builder", policy="adaptive", structured=True, epoch=1, stagnant_count=1, seed_base=100
        )
        self.assertEqual(
            retried,
            {
                "temperature": 0.15,
                "min_p": 0.05,
                "top_p": 0.85,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 100 + PRIME_SEED_STRIDE * 2,
            },
        )

    def test_adaptive_planner_and_analytical_roles_schedule_and_cap(self):
        for role in (
            "Specifier",
            "Clarifier",
            "Planner",
            "Decomposer",
            "Challenger",
            "Reviser",
            "Quality Review",
            "Reviewer",
            "Classifier",
            "Integrator",
        ):
            with self.subTest(role=role):
                opts = resolve_decoding_options(role, policy="adaptive")
                self.assertEqual(opts["temperature"], 0.05)
                self.assertEqual(opts["min_p"], 0.05)
                self.assertEqual(opts["top_p"], 0.85)
                self.assertEqual(opts["repeat_penalty"], 1.0)
                self.assertEqual(opts["repeat_last_n"], 64)
                self.assertEqual(opts["seed"], 0)

        capped = resolve_decoding_options(
            "Planner", policy="adaptive", epoch=4, stagnant_count=3, seed_base=5
        )
        self.assertEqual(capped["temperature"], 0.20)
        self.assertEqual(capped["repeat_penalty"], 1.0)
        self.assertEqual(capped["seed"], 5 + PRIME_SEED_STRIDE * 7)

    def test_adaptive_falsifier_uses_analytical_tier_and_rotates_seed_on_retry(self):
        base = resolve_decoding_options("Falsifier", policy="adaptive")
        self.assertEqual(
            base,
            {
                "temperature": 0.05,
                "min_p": 0.05,
                "top_p": 0.85,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 0,
            },
        )
        retry = resolve_decoding_options("Falsifier", policy="adaptive", epoch=1)
        self.assertEqual(retry["temperature"], 0.10)
        self.assertEqual(retry["seed"], PRIME_SEED_STRIDE)

    def test_adaptive_builder_epoch_zero_clean_synthesis_never_penalizes_repeats(self):
        opts = resolve_decoding_options(
            "Builder", policy="adaptive", epoch=0, stagnant_count=0, seed_base=0
        )
        self.assertEqual(
            opts,
            {
                "temperature": 0.08,
                "min_p": 0.08,
                "top_p": 0.90,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 0,
            },
        )

    def test_adaptive_builder_epoch_one_escalates_temp_and_seed_without_repeat_penalty(self):
        opts = resolve_decoding_options(
            "Builder", policy="adaptive", epoch=1, stagnant_count=0, seed_base=0
        )
        self.assertEqual(
            opts,
            {
                "temperature": 0.28,
                "min_p": 0.095,
                "top_p": 0.94,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": PRIME_SEED_STRIDE,
            },
        )

    def test_adaptive_builder_stagnation_escape_applies_repeat_penalty_and_rotates_seed(self):
        opts = resolve_decoding_options(
            "Builder", policy="adaptive", epoch=0, stagnant_count=2, seed_base=0
        )
        self.assertEqual(
            opts,
            {
                "temperature": 0.36,
                "min_p": 0.12,
                "top_p": 0.94,
                "repeat_penalty": 1.09,
                "repeat_last_n": 192,
                "seed": PRIME_SEED_STRIDE * 2,
            },
        )
        self.assertGreater(opts["repeat_penalty"], 1.0)
        self.assertLessEqual(opts["repeat_penalty"], 1.15)

    def test_adaptive_repairer_base_and_stagnation_caps(self):
        clean_repair = resolve_decoding_options(
            "Repairer", policy="adaptive", epoch=0, stagnant_count=0, seed_base=10
        )
        self.assertEqual(
            clean_repair,
            {
                "temperature": 0.20,
                "min_p": 0.07,
                "top_p": 0.94,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 10 + PRIME_SEED_STRIDE,
            },
        )
        saturated_repair = resolve_decoding_options(
            "Repairer", policy="adaptive", epoch=5, stagnant_count=6, seed_base=10
        )
        self.assertEqual(saturated_repair["temperature"], 0.48)
        self.assertEqual(saturated_repair["min_p"], 0.16)
        self.assertEqual(saturated_repair["top_p"], 0.94)
        self.assertEqual(saturated_repair["repeat_penalty"], 1.15)
        self.assertEqual(saturated_repair["repeat_last_n"], 192)
        self.assertEqual(saturated_repair["seed"], 10 + PRIME_SEED_STRIDE * 11)

    def test_negative_epoch_and_stagnant_counts_normalize_and_override_applies(self):
        normalized = resolve_decoding_options(
            "Builder",
            policy="adaptive",
            epoch=-3,
            stagnant_count=-2,
            temperature_override=0.33,
            seed_base=7,
        )
        self.assertEqual(
            normalized,
            {
                "temperature": 0.33,
                "min_p": 0.08,
                "top_p": 0.90,
                "repeat_penalty": 1.0,
                "repeat_last_n": 64,
                "seed": 7,
            },
        )

    def test_boolean_and_nonfinite_inputs_rejected_by_hyperparams(self):
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", policy="unknown")
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", base_temperature=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", temperature_override=float("nan"))
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", epoch=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", stagnant_count=True)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            resolve_decoding_options("Builder", seed_base=False)  # type: ignore[arg-type]

    def test_all_adaptive_regimes_and_new_decoding_bounds_accepted_by_job_runtime(self):
        regimes = [
            resolve_decoding_options("Builder", policy="fixed"),
            resolve_decoding_options("Planner", policy="adaptive"),
            resolve_decoding_options("Falsifier", policy="adaptive", epoch=2),
            resolve_decoding_options("Builder", policy="adaptive", structured=True),
            resolve_decoding_options("Builder", policy="adaptive", epoch=0, stagnant_count=0),
            resolve_decoding_options("Builder", policy="adaptive", epoch=1, stagnant_count=0),
            resolve_decoding_options("Builder", policy="adaptive", epoch=0, stagnant_count=2),
            resolve_decoding_options("Repairer", policy="adaptive", epoch=4, stagnant_count=5),
            resolve_decoding_options(
                "Repairer", policy="adaptive", epoch=10, stagnant_count=10, seed_base=2147483640
            ),
            {
                "num_ctx": 8192,
                "num_predict": 2048,
                "temperature": 0.2,
                "seed": 42,
                "num_gpu": 0,
                "min_p": 0.0,
                "top_p": 1.0,
                "top_k": 1,
                "repeat_penalty": 1.0,
                "repeat_last_n": 0,
            },
            {
                "min_p": 0.5,
                "top_p": 0.001,
                "top_k": 200,
                "repeat_penalty": 1.3,
                "repeat_last_n": 512,
            },
        ]
        for index, opts in enumerate(regimes):
            with self.subTest(index=index, opts=opts):
                accepted = runtime._chat_payload(_valid_chat_payload(opts))
                self.assertIsNotNone(accepted)
                for key, value in opts.items():
                    self.assertEqual(accepted["options"][key], value)

    def test_job_runtime_rejects_out_of_range_booleans_and_unknown_option_keys(self):
        invalid_option_cases = [
            {"min_p": -0.001},
            {"min_p": 0.5001},
            {"min_p": 0.9},
            {"min_p": True},
            {"min_p": False},
            {"min_p": float("nan")},
            {"top_p": 0.0},
            {"top_p": 0},
            {"top_p": 1.01},
            {"top_p": True},
            {"top_p": False},
            {"top_k": 0},
            {"top_k": 201},
            {"top_k": 40.0},
            {"top_k": True},
            {"repeat_penalty": 0.99},
            {"repeat_penalty": 1.31},
            {"repeat_penalty": 2.0},
            {"repeat_penalty": True},
            {"repeat_last_n": -1},
            {"repeat_last_n": 513},
            {"repeat_last_n": 64.0},
            {"repeat_last_n": False},
            {"mirostat": 1},
            {"unknown_option": 0.1},
        ]
        with patch.object(runtime, "_local_http") as http:
            for opts in invalid_option_cases:
                with self.subTest(opts=opts):
                    bridge = runtime._Bridge(1, time.monotonic() + 5, lambda: False)
                    payload = _valid_chat_payload(opts)
                    self.assertIsNone(runtime._chat_payload(payload))
                    reply = bridge.handle(
                        {
                            "kind": "provider",
                            "op": "post",
                            "path": "/api/chat",
                            "timeout": 1,
                            "payload": payload,
                        }
                    )
                    self.assertEqual(reply.get("error"), "provider_request_denied")
            http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
