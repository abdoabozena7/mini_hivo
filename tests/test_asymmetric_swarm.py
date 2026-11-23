"""Unit tests for hivo.asymmetric_swarm deterministic primitives."""

from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from hivo.asymmetric_swarm import (
    DECOMPOSITION_REGIMES,
    compute_child_contract_completeness,
    compute_child_contract_indicators,
    compute_plan_completeness_summary,
    load_and_validate_decomposition_plan,
    predict_compositional_pass_probability,
    unwrap_schema_echo_arguments,
    validate_decomposition_regime,
    validate_no_code_leakage,
)


WRITE_FILE_TOOL_DEF = {
    "name": "write_file",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative target path"},
            "content": {"type": "string", "description": "UTF-8 file body"},
        },
        "required": ["path", "content"],
    },
}

RUN_COMMAND_OPENAI_TOOL_DEF = {
    "type": "function",
    "function": {
        "name": "run_command",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "expected_exit_code": {
                    "anyOf": [
                        {"type": "integer"},
                        {"type": "string", "enum": ["nonzero"]},
                    ]
                },
                "expected_stdout": {"type": "string"},
            },
            "required": ["command"],
        },
    },
}

RUN_FILE_TOOL_DEF = {
    "name": "run_file",
    "parameters": {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "function": {"type": "string"},
            "arguments": {"type": "array", "items": {}},
            "expected": {
                "type": ["string", "number", "boolean", "object", "array", "null"],
            },
            "config": {"type": "object"},
            "timeout_seconds": {"type": "number"},
            "strict_mode": {"type": "boolean"},
        },
        "required": ["path"],
    },
}


class DecompositionRegimeTests(unittest.TestCase):
    def test_all_canonical_regimes_accepted_with_case_and_whitespace_normalization(self) -> None:
        self.assertEqual(
            DECOMPOSITION_REGIMES,
            ("auto", "monolithic", "self_recursive", "naive_oversplit", "contract_atomic"),
        )
        for regime in DECOMPOSITION_REGIMES:
            self.assertEqual(validate_decomposition_regime(regime), regime)
            self.assertEqual(
                validate_decomposition_regime(f"  {regime.upper()}\n"),
                regime,
            )

    def test_invalid_or_non_string_regimes_raise_value_error(self) -> None:
        for bad in ("", "   ", "contract-atomic", "unknown_regime", None, 42, True, ["auto"]):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    validate_decomposition_regime(bad)  # type: ignore[arg-type]


class SchemaEchoNormalizationTests(unittest.TestCase):
    def test_unwraps_string_value_and_content_wrappers_without_mutating_caller_dict(self) -> None:
        raw_args = {
            "path": {"type": "STRING", "value": "hello.py", "description": "target file"},
            "content": {"type": "string", "content": "print('hi')\n"},
        }
        snapshot = copy.deepcopy(raw_args)

        normalized, was_unwrapped = unwrap_schema_echo_arguments(raw_args, WRITE_FILE_TOOL_DEF)
        self.assertTrue(was_unwrapped)
        self.assertEqual(
            normalized,
            {"path": "hello.py", "content": "print('hi')\n"},
        )
        self.assertEqual(raw_args, snapshot)
        self.assertIsNot(normalized, raw_args)

    def test_unwraps_integer_and_number_wrappers_and_rejects_booleans_masquerading_as_int(self) -> None:
        int_tool = {
            "name": "edit_file",
            "parameters": {
                "type": "object",
                "properties": {
                    "expected_replacements": {"type": "integer"},
                    "ratio": {"type": "number"},
                },
            },
        }
        args_valid = {
            "expected_replacements": {"type": "integer", "value": 0},
            "ratio": {"type": "integer", "default": 2},
        }
        normalized, was_unwrapped = unwrap_schema_echo_arguments(args_valid, int_tool)
        self.assertTrue(was_unwrapped)
        self.assertEqual(normalized, {"expected_replacements": 0, "ratio": 2})
        self.assertIs(type(normalized["expected_replacements"]), int)

        # In Python isinstance(True, int) is True, so bool must NOT unwrap as an integer!
        args_bool_for_int = {
            "expected_replacements": {"type": "integer", "value": True},
        }
        unchanged, flag = unwrap_schema_echo_arguments(args_bool_for_int, int_tool)
        self.assertFalse(flag)
        self.assertEqual(unchanged, args_bool_for_int)

        # Number wrapper echoed for integer schema with genuine int value should unwrap
        args_num_echo = {
            "expected_replacements": {"type": "number", "const": 3},
        }
        unwrapped_num, flag_num = unwrap_schema_echo_arguments(args_num_echo, int_tool)
        self.assertTrue(flag_num)
        self.assertEqual(unwrapped_num, {"expected_replacements": 3})

    def test_unwraps_array_wrappers_and_deep_copies_list_payload(self) -> None:
        inner_list = [[10.0, 20.0, 30.0]]
        raw_args = {
            "path": "metrics.py",
            "function": "summarize_latencies",
            "arguments": {"type": "array", "value": inner_list, "title": "Arguments"},
        }
        normalized, was_unwrapped = unwrap_schema_echo_arguments(raw_args, RUN_FILE_TOOL_DEF)
        self.assertTrue(was_unwrapped)
        self.assertEqual(normalized["arguments"], [[10.0, 20.0, 30.0]])
        normalized["arguments"][0].append(99.0)
        self.assertEqual(inner_list, [[10.0, 20.0, 30.0]])

    def test_supports_anyof_expected_exit_code_and_openai_wrapped_tool_definition(self) -> None:
        raw_args = {
            "command": {"type": "string", "value": "python -m unittest -v"},
            "expected_exit_code": {"type": "integer", "value": 0},
        }
        normalized, was_unwrapped = unwrap_schema_echo_arguments(
            raw_args,
            RUN_COMMAND_OPENAI_TOOL_DEF,
        )
        self.assertTrue(was_unwrapped)
        self.assertEqual(
            normalized,
            {"command": "python -m unittest -v", "expected_exit_code": 0},
        )

    def test_payload_key_priority_prefers_value_over_content_const_default(self) -> None:
        raw_args = {
            "path": {
                "type": "string",
                "default": "fallback.py",
                "const": "const.py",
                "content": "content.py",
                "value": "winner.py",
            },
            "content": {
                "type": "string",
                "default": "default_body",
                "const": "const_body",
            },
        }
        normalized, was_unwrapped = unwrap_schema_echo_arguments(raw_args, WRITE_FILE_TOOL_DEF)
        self.assertTrue(was_unwrapped)
        self.assertEqual(normalized, {"path": "winner.py", "content": "const_body"})

    def test_never_unwraps_mismatched_schema_types_extra_keys_or_genuine_nested_dicts(self) -> None:
        # 1. Genuine object parameter (`config`) and union-with-object parameter (`expected`)
        genuine_object_args = {
            "path": "metrics.py",
            "expected": {"type": "string", "value": "keep_me_as_dict"},
            "config": {"type": "string", "value": "genuine_config_object"},
        }
        res_obj, flag_obj = unwrap_schema_echo_arguments(genuine_object_args, RUN_FILE_TOOL_DEF)
        self.assertFalse(flag_obj)
        self.assertEqual(res_obj, genuine_object_args)

        # 2. Mismatched type (`integer` wrapper passed for `string` parameter)
        mismatch_type_args = {
            "path": {"type": "integer", "value": 123},
            "content": "x = 1\n",
        }
        res_mis, flag_mis = unwrap_schema_echo_arguments(mismatch_type_args, WRITE_FILE_TOOL_DEF)
        self.assertFalse(flag_mis)
        self.assertEqual(res_mis, mismatch_type_args)

        # 3. Mismatched runtime value (`int` inside `"type": "string"` wrapper)
        mismatch_val_args = {
            "path": {"type": "string", "value": 123},
            "content": "x = 1\n",
        }
        res_val, flag_val = unwrap_schema_echo_arguments(mismatch_val_args, WRITE_FILE_TOOL_DEF)
        self.assertFalse(flag_val)
        self.assertEqual(res_val, mismatch_val_args)

        # 4. Arbitrary dict with non-schema keys (`{"type": "string", "value": "a.py", "owner": "root"}`)
        extra_key_args = {
            "path": {"type": "string", "value": "a.py", "owner": "root"},
            "content": "x = 1\n",
        }
        res_extra, flag_extra = unwrap_schema_echo_arguments(extra_key_args, WRITE_FILE_TOOL_DEF)
        self.assertFalse(flag_extra)
        self.assertEqual(res_extra, extra_key_args)

        # 5. Schema echo missing payload key (`{"type": "string", "description": "path"}`)
        missing_payload_args = {
            "path": {"type": "string", "description": "only metadata"},
            "content": "x = 1\n",
        }
        res_no_val, flag_no_val = unwrap_schema_echo_arguments(
            missing_payload_args, WRITE_FILE_TOOL_DEF
        )
        self.assertFalse(flag_no_val)
        self.assertEqual(res_no_val, missing_payload_args)

    def test_non_dict_args_or_missing_tool_definition_returns_unchanged(self) -> None:
        self.assertEqual(unwrap_schema_echo_arguments(["not", "a", "dict"], WRITE_FILE_TOOL_DEF), (["not", "a", "dict"], False))
        self.assertEqual(unwrap_schema_echo_arguments(None, WRITE_FILE_TOOL_DEF), (None, False))
        self.assertEqual(unwrap_schema_echo_arguments({"path": "a.py"}, None), ({"path": "a.py"}, False))


class DecompositionPlanValidationTests(unittest.TestCase):
    def _valid_contract_atomic_plan(self) -> dict:
        return {
            "schema_version": "1.0",
            "regime": "contract_atomic",
            "orchestrator_id": "frontier-architect-v1",
            "goal": "Build latency summary library, CLI wrapper, and unit tests.",
            "constraints": ["Zero third-party dependencies", "Deterministic float rounding"],
            "success_criteria": ["python -m unittest discover -v exits 0"],
            "children": [
                {
                    "id": "metrics_core",
                    "goal": "Implement metrics.py providing summarize_latencies(values: list[float]) -> dict[str, float | int]",
                    "done_when": [
                        "run_file on metrics.py summarize_latencies([10.0, 20.0, 30.0]) returns {'count': 3, 'min': 10.0, 'max': 30.0, 'mean': 20.0, 'p95': 29.0}",
                        "summarize_latencies([]) raises ValueError on empty input or negative latency (< 0)",
                    ],
                    "scope_hint": ["metrics.py"],
                    "owned_mutation_paths": ["metrics.py"],
                    "interface_contract": (
                        "summarize_latencies(values: list[float]) -> dict[str, float | int]; "
                        'JSON keys: {"count": 3, "min": 10.0, "max": 30.0, "mean": 20.0, "p95": 29.0}; '
                        "raises ValueError when values is empty or any item < 0."
                    ),
                },
                {
                    "id": "metrics_cli",
                    "goal": "Implement cli.py exposing --values comma-separated float flag and printing JSON output",
                    "done_when": [
                        "run_command 'python cli.py --values 10,20,30' prints JSON summary and exits 0",
                        "run_command 'python cli.py --values invalid' exits nonzero",
                    ],
                    "scope_hint": ["cli.py"],
                    "owned_mutation_paths": ["cli.py"],
                    "read_only_sibling_paths": ["metrics.py"],
                    "depends_on": ["metrics_core"],
                    "interface_contract": {
                        "entrypoint": "main(argv: list[str] | None = None) -> int",
                        "cli_flags": ["--values"],
                        "output_schema": {"count": 3, "min": 10.0},
                        "error_behavior": "Exits with nonzero code 2 on empty or malformed input.",
                    },
                },
            ],
        }

    def test_single_line_signatures_and_json_examples_pass_anti_code_leakage(self) -> None:
        valid_contracts = [
            "summarize_latencies(values: list[float]) -> dict[str, float | int]",
            '{"count": 3, "min": 10.0, "max": 30.0, "mean": 20.0, "p95": 29.0}',
            "{\n  \"count\": 3,\n  \"min\": 10.0,\n  \"max\": 30.0,\n  \"p95\": 29.0\n}",
            (
                "parse_values(raw: str) -> list[float]\n"
                "summarize_latencies(values: list[float]) -> dict[str, float | int]\n"
                "format_json(summary: dict[str, float | int]) -> str\n"
                "main(argv: list[str] | None = None) -> int"
            ),
            (
                "- Signature: summarize_latencies(values: list[float]) -> dict[str, float | int]\n"
                "- CLI flag: --values\n"
                "- Invariant: raises ValueError on empty input or values < 0\n"
                "- Output: {\"count\": 3, \"min\": 10.0}\n"
                "- Verification: unittest exits 0"
            ),
        ]
        for text in valid_contracts:
            with self.subTest(text=text[:45]):
                self.assertEqual(validate_no_code_leakage(text), [])

    def test_five_line_python_and_js_function_bodies_and_fenced_blocks_rejected(self) -> None:
        python_body = (
            "def summarize_latencies(values: list[float]) -> dict[str, float | int]:\n"
            "    if not values:\n"
            "        raise ValueError('empty')\n"
            "    ordered = sorted(values)\n"
            "    return {'count': len(ordered), 'min': ordered[0]}"
        )
        js_body = (
            "function stepSimulation(dt) {\n"
            "    if (state.paused) {\n"
            "        return state;\n"
            "    }\n"
            "    state.score += dt * 10;\n"
            "    return state;\n"
            "}"
        )
        fenced_code = (
            "Use this exact implementation:\n"
            "```python\n"
            "import math\n"
            "def norm(x, y):\n"
            "    sq = x * x + y * y\n"
            "    return math.sqrt(sq)\n"
            "```"
        )
        import_script = (
            "import sys\n"
            "import json\n"
            "payload = json.loads(sys.argv[1])\n"
            "print(json.dumps(payload))"
        )
        multiline_dict_return = (
            "def summarize(values):\n"
            "    ordered = sorted(values)\n"
            "    return {\n"
            "        'count': len(ordered),\n"
            "        'min': ordered[0],\n"
            "    }"
        )
        for leaked in (python_body, js_body, fenced_code, import_script, multiline_dict_return):
            with self.subTest(leaked=leaked[:40]):
                violations = validate_no_code_leakage(leaked)
                self.assertGreaterEqual(len(violations), 1)

    def test_load_and_validate_from_dict_and_utf8_json_file_assigns_default_ids(self) -> None:
        raw = {
            "schema_version": "1.0",
            "regime": "  NAIVE_OVERSPLIT ",
            "orchestrator_id": "naive-oversplit-generator",
            "goal": "Create a small greeting script and test.",
            "children": [
                {
                    "goal": "Create greeting module",
                    "done_when": ["module exists"],
                    "scope_hint": ["greeter.py"],
                },
                {
                    "goal": "Create CLI script",
                    "done_when": ["script runs"],
                    "scope_hint": ["main.py"],
                    "depends_on": ["1"],
                },
            ],
        }
        validated_from_dict = load_and_validate_decomposition_plan(raw)
        self.assertEqual(validated_from_dict["regime"], "naive_oversplit")
        self.assertEqual([c["id"] for c in validated_from_dict["children"]], ["1", "2"])
        self.assertEqual(validated_from_dict["constraints"], [])
        self.assertEqual(validated_from_dict["success_criteria"], [])
        self.assertEqual(validated_from_dict["children"][0]["owned_mutation_paths"], [])
        # Original dict was not mutated
        self.assertNotIn("id", raw["children"][0])

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            plan_file = Path(tmp_dir) / "frontier_plan.json"
            plan_file.write_text(
                json.dumps(self._valid_contract_atomic_plan(), indent=2),
                encoding="utf-8",
            )
            loaded_path = load_and_validate_decomposition_plan(plan_file)
            loaded_str = load_and_validate_decomposition_plan(str(plan_file))
            self.assertEqual(loaded_path, loaded_str)
            self.assertEqual(loaded_path["regime"], "contract_atomic")
            self.assertEqual(len(loaded_path["children"]), 2)

    def test_rejects_code_leakage_in_goal_done_when_and_dict_interface_contract(self) -> None:
        five_line_impl = (
            "def summarize_latencies(values):\n"
            "    if not values:\n"
            "        raise ValueError('empty')\n"
            "    vals = sorted(values)\n"
            "    return {'count': len(vals), 'min': vals[0]}"
        )

        # 1. Leakage in child.interface_contract (string)
        plan_ic_str = self._valid_contract_atomic_plan()
        plan_ic_str["children"][0]["interface_contract"] = five_line_impl
        with self.assertRaisesRegex(ValueError, "Decomposition plan rejected: code leakage detected"):
            load_and_validate_decomposition_plan(plan_ic_str)

        # 2. Leakage in child.interface_contract (nested dict)
        plan_ic_dict = self._valid_contract_atomic_plan()
        plan_ic_dict["children"][1]["interface_contract"] = {"helper_source": five_line_impl}
        with self.assertRaisesRegex(ValueError, "Decomposition plan rejected: code leakage detected"):
            load_and_validate_decomposition_plan(plan_ic_dict)

        # 3. Leakage in child.goal
        plan_goal = self._valid_contract_atomic_plan()
        plan_goal["children"][0]["goal"] = f"Write this function:\n{five_line_impl}"
        with self.assertRaisesRegex(ValueError, "Decomposition plan rejected: code leakage detected"):
            load_and_validate_decomposition_plan(plan_goal)

        # 4. Leakage split across child.done_when lines
        plan_done = self._valid_contract_atomic_plan()
        plan_done["children"][0]["done_when"] = five_line_impl.splitlines()
        with self.assertRaisesRegex(ValueError, "Decomposition plan rejected: code leakage detected"):
            load_and_validate_decomposition_plan(plan_done)

    def test_rejects_schema_version_mismatch_bounds_cycles_unknown_deps_and_unknown_keys(self) -> None:
        base = self._valid_contract_atomic_plan()

        bad_ver = copy.deepcopy(base)
        bad_ver["schema_version"] = "2.0"
        with self.assertRaises(ValueError):
            load_and_validate_decomposition_plan(bad_ver)

        empty_children = copy.deepcopy(base)
        empty_children["children"] = []
        with self.assertRaises(ValueError):
            load_and_validate_decomposition_plan(empty_children)

        too_many_children = copy.deepcopy(base)
        too_many_children["children"] = [
            {
                "id": f"c{i}",
                "goal": f"Task {i}",
                "done_when": ["unittest exits 0"],
                "scope_hint": [f"mod_{i}.py"],
            }
            for i in range(9)
        ]
        with self.assertRaises(ValueError):
            load_and_validate_decomposition_plan(too_many_children)

        unknown_dep = copy.deepcopy(base)
        unknown_dep["children"][1]["depends_on"] = ["nonexistent_id"]
        with self.assertRaises(ValueError):
            load_and_validate_decomposition_plan(unknown_dep)

        cyclic = copy.deepcopy(base)
        cyclic["children"][0]["depends_on"] = ["metrics_cli"]
        with self.assertRaises(ValueError):
            load_and_validate_decomposition_plan(cyclic)

        # Benign benchmark metadata (`task_id`) is tolerated and stripped from worker packets,
        # whereas leaked source code smuggled in an extra key is rejected!
        with_meta = copy.deepcopy(base)
        with_meta["task_id"] = "T01_latency"
        with_meta["children"][0]["notes"] = "Producer leaf"
        cleaned_meta = load_and_validate_decomposition_plan(with_meta)
        self.assertNotIn("notes", cleaned_meta["children"][0])

        smuggled_field = copy.deepcopy(base)
        smuggled_field["children"][0]["raw_code"] = (
            "def summarize(values):\n"
            "    vals = sorted(values)\n"
            "    total = sum(vals)\n"
            "    return total"
        )
        with self.assertRaisesRegex(ValueError, "Decomposition plan rejected: code leakage detected"):
            load_and_validate_decomposition_plan(smuggled_field)


class ContractCompletenessTests(unittest.TestCase):
    def test_naive_oversplit_plan_scores_strictly_below_0_45(self) -> None:
        naive_children = [
            {
                "id": "1",
                "goal": "Set up core data structures for the project",
                "done_when": ["Core data structures are ready"],
                "scope_hint": ["data layer"],
            },
            {
                "id": "2",
                "goal": "Implement statistical helper logic in metrics.py",
                "done_when": ["metrics.py implementation is complete"],
                "scope_hint": ["metrics.py"],
            },
            {
                "id": "3",
                "goal": "Add command line argument handling",
                "done_when": ["CLI wrapper works"],
                "scope_hint": ["cli layer"],
            },
            {
                "id": "4",
                "goal": "Format output text nicely",
                "done_when": ["Formatting module is clean"],
                "scope_hint": ["formatter.py"],
            },
            {
                "id": "5",
                "goal": "Create test suite for project modules",
                "done_when": ["Tests are written"],
                "scope_hint": ["testing"],
            },
        ]
        summary = compute_plan_completeness_summary(naive_children)
        self.assertEqual(summary["num_children"], 5)
        self.assertEqual(summary["boundary_count"], 4)
        self.assertLess(summary["mean_kappa"], 0.45)
        for child in naive_children:
            self.assertLess(compute_child_contract_completeness(child), 0.45)

    def test_contract_atomic_python_and_threejs_plans_score_at_least_0_85(self) -> None:
        contract_atomic_children = [
            {
                "id": "metrics_core",
                "goal": "Implement metrics.py with summarize_latencies(values: list[float]) -> dict[str, float | int]",
                "done_when": [
                    "run_file summarize_latencies([10.0, 20.0, 30.0]) returns {'count': 3, 'min': 10.0, 'max': 30.0, 'mean': 20.0, 'p95': 29.0}",
                    "summarize_latencies([]) raises ValueError on empty input or negative values (< 0)",
                ],
                "scope_hint": ["metrics.py"],
                "owned_mutation_paths": ["metrics.py"],
                "interface_contract": "summarize_latencies(values: list[float]) -> dict[str, float | int]",
            },
            {
                "id": "metrics_cli",
                "goal": "Implement cli.py exposing --values CLI flag to print JSON latency summary",
                "done_when": [
                    "run_command 'python cli.py --values 10,20,30' prints JSON object and exits 0",
                    "run_command 'python cli.py --values invalid' exits nonzero",
                ],
                "scope_hint": ["cli.py"],
                "owned_mutation_paths": ["cli.py"],
                "read_only_sibling_paths": ["metrics.py"],
                "depends_on": ["metrics_core"],
                "interface_contract": "main(argv: list[str] | None = None) -> int; supports --values; exits nonzero on invalid/empty input",
            },
            {
                "id": "three_game",
                "goal": "Implement game.js exporting window.AGENT_GAME bridge with step(dt: number) -> Object",
                "done_when": [
                    "verify_web_app on index.html renders #gameCanvas with 0 console errors and paused state false",
                ],
                "scope_hint": ["game.js"],
                "owned_mutation_paths": ["game.js"],
                "interface_contract": {
                    "bridge": "window.AGENT_GAME = { getState() -> Object, step(dt: number) -> Object }",
                    "invariants": "Clamps player position within [-10, 10] and freezes score when paused",
                },
            },
        ]
        summary = compute_plan_completeness_summary(contract_atomic_children)
        self.assertGreaterEqual(summary["mean_kappa"], 0.85)
        self.assertGreaterEqual(summary["min_kappa"], 0.85)
        self.assertEqual(summary["child_kappas"], [1.0, 1.0, 1.0])

    def test_excludes_bare_js_library_names_and_plural_parentheticals_from_false_credit(self) -> None:
        vague_threejs_child = {
            "goal": "Use Three.js to handle scene item(s)",
            "done_when": ["Scene item(s) look good"],
            "scope_hint": ["Three.js"],
            "interface_contract": {},
        }
        indicators = compute_child_contract_indicators(vague_threejs_child)
        self.assertEqual(
            indicators,
            {
                "has_explicit_file_owner": False,
                "has_callable_or_cli_signature": False,
                "has_io_type_or_schema": False,
                "has_edge_or_error_invariant": False,
                "has_executable_oracle": False,
            },
        )
        self.assertEqual(compute_child_contract_completeness(vague_threejs_child), 0.0)

    def test_plan_completeness_summary_computes_exact_boundaries_mean_and_min(self) -> None:
        empty_summary = compute_plan_completeness_summary([])
        self.assertEqual(
            empty_summary,
            {
                "num_children": 0,
                "boundary_count": 0,
                "mean_kappa": 0.0,
                "min_kappa": 0.0,
                "child_kappas": [],
            },
        )
        single_summary = compute_plan_completeness_summary([
            {
                "goal": "Implement app.py with parse_count(raw: str) -> int",
                "done_when": ["run_file parse_count('5') returns 5 and raises ValueError on empty str"],
                "scope_hint": ["app.py"],
            }
        ])
        self.assertEqual(single_summary["num_children"], 1)
        self.assertEqual(single_summary["boundary_count"], 0)
        self.assertEqual(single_summary["mean_kappa"], 1.0)
        self.assertEqual(single_summary["min_kappa"], 1.0)


class DziriCompositionalReliabilityTests(unittest.TestCase):
    def test_exact_closed_form_values_and_single_leaf_zero_boundary_case(self) -> None:
        # k = 1 has 0 boundaries, so boundary_mismatch_rate does not penalize k = 1
        p_monolithic = predict_compositional_pass_probability(
            num_children=1,
            leaf_error_rate=0.25,
            boundary_mismatch_rate=0.40,
            verification_recovery_prob=0.20,
        )
        # eps_eff = 0.25 * (1 - 0.20) = 0.20 => P_sys = 0.80^1 * 0.60^0 = 0.8
        self.assertEqual(p_monolithic, 0.8)

        # k = 3, eps_w = 0.20, v = 0.50 => eps_eff = 0.10; delta = 0.10
        # P_sys = 0.9^3 * 0.9^2 = 0.729 * 0.81 = 0.59049
        p_three = predict_compositional_pass_probability(
            num_children=3,
            leaf_error_rate=0.20,
            boundary_mismatch_rate=0.10,
            verification_recovery_prob=0.50,
        )
        self.assertEqual(p_three, 0.59049)

    def test_monotonicity_across_children_leaf_error_boundary_mismatch_and_recovery(self) -> None:
        # Monotonically decreasing in num_children for fixed positive error/mismatch rates
        by_k = [
            predict_compositional_pass_probability(k, 0.12, 0.08, 0.25)
            for k in range(1, 8)
        ]
        for prev_p, next_p in zip(by_k, by_k[1:]):
            self.assertGreater(prev_p, next_p)

        # Monotonically decreasing in boundary_mismatch_rate (for k >= 2)
        by_delta = [
            predict_compositional_pass_probability(4, 0.10, delta, 0.30)
            for delta in (0.0, 0.05, 0.15, 0.30, 0.50)
        ]
        for prev_p, next_p in zip(by_delta, by_delta[1:]):
            self.assertGreater(prev_p, next_p)

        # Monotonically increasing in verification_recovery_prob
        by_recovery = [
            predict_compositional_pass_probability(4, 0.25, 0.05, v)
            for v in (0.0, 0.25, 0.50, 0.75, 1.0)
        ]
        for prev_p, next_p in zip(by_recovery, by_recovery[1:]):
            self.assertLess(prev_p, next_p)

    def test_interior_optimum_k_star_under_positive_boundary_mismatch_vs_contract_atomic_delta_near_zero(self) -> None:
        # Weak worker leaf error rate drops past context/reasoning capacity cliff as task is split:
        leaf_error_by_k = {
            1: 0.92,  # monolithic exceeds weak-worker horizon
            2: 0.22,
            3: 0.09,
            4: 0.06,
            5: 0.05,
            6: 0.045,
            7: 0.042,
            8: 0.04,
        }

        # Arm A: naive_oversplit (high boundary mismatch delta = 0.35, no verification recovery)
        naive_curve = {
            k: predict_compositional_pass_probability(
                num_children=k,
                leaf_error_rate=eps,
                boundary_mismatch_rate=0.35,
                verification_recovery_prob=0.0,
            )
            for k, eps in leaf_error_by_k.items()
        }
        k_star_naive = max(naive_curve, key=naive_curve.get)  # type: ignore[arg-type]
        # Interior optimum 1 < k* < 8, followed by oversplit collapse at k = 8
        self.assertIn(k_star_naive, {2, 3})
        self.assertGreater(naive_curve[k_star_naive], naive_curve[1])
        self.assertGreater(naive_curve[k_star_naive], naive_curve[8])

        # Arm B: contract_atomic + verification gate (delta -> 0.005, recovery v = 0.60)
        contract_curve = {
            k: predict_compositional_pass_probability(
                num_children=k,
                leaf_error_rate=eps,
                boundary_mismatch_rate=0.005,
                verification_recovery_prob=0.60,
            )
            for k, eps in leaf_error_by_k.items()
        }
        k_star_contract = max(contract_curve, key=contract_curve.get)  # type: ignore[arg-type]
        self.assertGreaterEqual(k_star_contract, k_star_naive)
        for k in range(2, 9):
            self.assertGreater(contract_curve[k], naive_curve[k])
        self.assertGreater(contract_curve[k_star_contract], 0.85)

    def test_invalid_compositional_inputs_raise_value_error(self) -> None:
        invalid_calls = [
            (0, 0.1, 0.1, 0.0),
            (-2, 0.1, 0.1, 0.0),
            (True, 0.1, 0.1, 0.0),
            (2.5, 0.1, 0.1, 0.0),
            (2, -0.01, 0.1, 0.0),
            (2, 1.01, 0.1, 0.0),
            (2, 0.1, -0.1, 0.0),
            (2, 0.1, 1.2, 0.0),
            (2, 0.1, 0.1, -0.5),
            (2, 0.1, 0.1, 1.5),
            (2, True, 0.1, 0.0),
            (2, float("nan"), 0.1, 0.0),
        ]
        for args in invalid_calls:
            with self.subTest(args=args):
                with self.assertRaises(ValueError):
                    predict_compositional_pass_probability(*args)  # type: ignore[arg-type]


class DeterministicVerificationOracleAndStrictTargetTests(unittest.TestCase):
    def test_verification_oracles_accepted_and_normalized_across_all_four_kinds(self) -> None:
        plan = {
            "schema_version": "1.0",
            "regime": "contract_atomic",
            "orchestrator_id": "frontier-architect",
            "goal": "Build modular verified project.",
            "children": [
                {
                    "id": "1",
                    "goal": "Create metrics.py",
                    "done_when": ["run_file passes"],
                    "owned_mutation_paths": ["metrics.py"],
                    "verification_oracles": [
                        {
                            "kind": "RUN_FILE",
                            "target": "metrics.py",
                            "function": "summarize_latencies",
                            "arguments": [[10.0, 20.0]],
                            "expected": {"count": 2, "mean": 15.0},
                        },
                        {
                            "kind": "run_command",
                            "target": "bridge.js",
                            "command": "node --check bridge.js",
                            "expected_exports": ["createGameBridge"],
                            "expected_source_substrings": ["forceCollect", "restart"],
                        },
                        {"kind": "unittest", "target": "test_metrics.py"},
                        {"kind": "verify_web_app", "target": "index.html"},
                    ],
                }
            ],
        }
        validated = load_and_validate_decomposition_plan(plan)
        oracles = validated["children"][0]["verification_oracles"]
        self.assertEqual([o["kind"] for o in oracles], ["run_file", "run_command", "unittest", "verify_web_app"])
        self.assertEqual(oracles[1]["expected_exports"], ["createGameBridge"])

    def test_verification_oracles_reject_unknown_kinds_unknown_keys_and_leaked_code(self) -> None:
        base = {
            "schema_version": "1.0",
            "regime": "contract_atomic",
            "orchestrator_id": "frontier-architect",
            "goal": "Build project.",
            "children": [
                {
                    "id": "1",
                    "goal": "Create metrics.py",
                    "done_when": ["passes"],
                    "owned_mutation_paths": ["metrics.py"],
                }
            ],
        }
        bad_kind = copy.deepcopy(base)
        bad_kind["children"][0]["verification_oracles"] = [{"kind": "shell_exec", "command": "ls"}]
        with self.assertRaisesRegex(ValueError, "Invalid oracle kind"):
            load_and_validate_decomposition_plan(bad_kind)

        bad_key = copy.deepcopy(base)
        bad_key["children"][0]["verification_oracles"] = [
            {"kind": "unittest", "target": "test_x.py", "secret_impl": "x = 1"}
        ]
        with self.assertRaisesRegex(ValueError, "Unsupported oracle keys"):
            load_and_validate_decomposition_plan(bad_key)

        leaked_cmd = copy.deepcopy(base)
        leaked_cmd["children"][0]["verification_oracles"] = [
            {
                "kind": "run_command",
                "command": (
                    "def f(x):\n"
                    "    y = x + 1\n"
                    "    z = y * 2\n"
                    "    return z"
                ),
            }
        ]
        with self.assertRaisesRegex(ValueError, "code leakage detected"):
            load_and_validate_decomposition_plan(leaked_cmd)

    def test_evidence_strict_target_resolves_four_token_python_m_unittest_and_pytest(self) -> None:
        from hivo import evidence_strict

        self.assertEqual(
            evidence_strict.target("python -m unittest test_metrics.py", "run_command"),
            "test_metrics.py",
        )
        self.assertEqual(
            evidence_strict.target("python3 -m pytest tests/test_store.py", "run_command"),
            "tests/test_store.py",
        )
        # Flag-only discovery without explicit file path must still return None
        self.assertIsNone(
            evidence_strict.target("python -m unittest -v", "run_command"),
        )
        # DCVG ::dcvg:<sig> suffixes must strip cleanly across run_file and run_command
        self.assertEqual(
            evidence_strict.target("metrics.py::dcvg:0123456789abcdef", "run_file"),
            "metrics.py",
        )
        self.assertEqual(
            evidence_strict.target("py -m unittest test_metrics.py::dcvg:0123456789abcdef", "run_command"),
            "test_metrics.py",
        )

    def test_rejects_single_line_semicolon_packed_code_and_oracle_field_type_mismatches(self) -> None:
        packed_js = (
            "import {createGameState} from './game_state.js'; "
            "const state = createGameState(); "
            "const el = document.getElementById('app'); "
            "window.AGENT_GAME = state;"
        )
        self.assertGreaterEqual(len(validate_no_code_leakage(packed_js)), 1)

        base = {
            "schema_version": "1.0",
            "regime": "contract_atomic",
            "orchestrator_id": "frontier-architect",
            "goal": "Build project.",
            "children": [
                {
                    "id": "1",
                    "goal": "Create metrics.py",
                    "done_when": ["passes"],
                    "owned_mutation_paths": ["metrics.py"],
                }
            ],
        }
        # Leakage inside expected_source_substrings must be rejected
        leaked_sub = copy.deepcopy(base)
        leaked_sub["children"][0]["verification_oracles"] = [
            {
                "kind": "run_command",
                "target": "metrics.py",
                "command": "python -m py_compile metrics.py",
                "expected_source_substrings": [packed_js],
            }
        ]
        with self.assertRaisesRegex(ValueError, "code leakage detected"):
            load_and_validate_decomposition_plan(leaked_sub)

        # expected_exports without explicit target must be rejected
        missing_target = copy.deepcopy(base)
        missing_target["children"][0]["verification_oracles"] = [
            {
                "kind": "run_command",
                "command": "node --check app.js",
                "expected_exports": ["initApp"],
            }
        ]
        with self.assertRaisesRegex(ValueError, "requires explicit non-empty 'target'"):
            load_and_validate_decomposition_plan(missing_target)

    def test_python_checks_check_call_fails_closed_on_arity_mismatch(self) -> None:
        from hivo.python_checks import check_call

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as tmp_dir:
            mod_path = Path(tmp_dir) / "math_mod.py"
            mod_path.write_text("def compute(vals):\n    return sum(vals)\n", encoding="utf-8")
            res = check_call(Path(tmp_dir), "math_mod.py", "compute", [2, 3], 5)
            self.assertFalse(res["passed"])


if __name__ == "__main__":
    unittest.main()
