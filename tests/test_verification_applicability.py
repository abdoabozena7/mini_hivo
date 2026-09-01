import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo.verification_routing import BROWSER
from hivo.verification_routing import FOCUSED_TEST
from hivo.verification_routing import REQUIRED_VERIFICATION_TARGET_UNRESOLVED
from hivo.verification_routing import SKIPPED_NOT_APPLICABLE
from hivo.verification_routing import SYNTAX_STATIC_GATE
from hivo.verification_routing import VERIFICATION_EVIDENCE_UNAVAILABLE
from hivo.verification_routing import aggregate_verification_evidence
from hivo.verification_routing import deterministic_hash


class VerificationApplicabilityTests(unittest.TestCase):
    """Stage 5A routing is deterministic and never calls the model."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    @staticmethod
    def task(task_id="CHILD", goal="Implement one module", done_when=None, scope=None, **extra):
        task = {
            "id": task_id,
            "goal": goal,
            "done_when": list(done_when or ["the module behavior is verified"]),
            "scope_hint": list(["src/module.js"] if scope is None else scope),
        }
        task.update(extra)
        return task

    @staticmethod
    def route(artifact, kind):
        return next(item for item in artifact["verification_routes"] if item["kind"] == kind)

    def snapshot(self):
        return mini.inspect_repository()

    def write(self, relative, content="const ready = true;\n"):
        path = mini.WORKSPACE / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def test_analyzer_is_zero_model_deterministic_and_hashes_derived_metadata(self):
        self.write("src/module.js")
        self.write("tests/module.test.js", "test('module', () => { if (!true) throw Error(); });\n")
        contract = {
            "goal": "Implement one module",
            "done_when": ["the module behavior is verified"],
            "allowed_mutation_paths": ["src/module.js"],
            "allowed_inspection_paths": ["src/module.js", "tests/module.test.js"],
            "test_contract": ["tests/module.test.js passes"],
            "contract_hash": "contract-hash-001",
            "plan_hash": "plan-hash-001",
        }
        task = self.task(scope=["src/module.js"])
        before = copy.deepcopy(contract)
        with patch.object(mini, "ask_ollama", side_effect=AssertionError("Stage 5A called a model")):
            first = mini.analyze_verification_applicability(task, contract, self.snapshot())
            second = mini.analyze_verification_applicability(task, contract, self.snapshot())

        self.assertEqual(first, second)
        self.assertEqual(first["model_calls"], 0)
        self.assertEqual(contract, before)
        self.assertTrue(first["verification_applicability_hash"])
        self.assertEqual(first["verification_applicability_hash"], first["verification_routes_hash"])
        self.assertEqual(mini.RUN["verification_applicability_checks"], 1)

    def test_exact_four_file_fixture_skips_optional_browser_without_calling_verifier(self):
        self.write("src/input.js", "export function input() { return true; }\n")
        self.write("src/pause_controller.js")
        self.write("src/status_view.js", "export function render() {}\n")
        self.write("tests/pause_flow.test.js", "test('pause flow', () => { if (!true) throw Error(); });\n")
        task = self.task(
            "EXEC-001.1", "Implement input behavior", ["input behavior is complete"], ["src/input.js"],
            execution_contract_child={
                "goal": "Implement input behavior",
                "done_when": ["input behavior is complete"],
                "allowed_mutation_paths": ["src/input.js"],
                "allowed_inspection_paths": ["src/input.js", "tests/pause_flow.test.js"],
            },
        )
        builder = {
            "status": "done",
            "summary": "focused test ok",
            "tool_evidence": [{
                "tool": "run_command", "target": "node tests/pause_flow.test.js",
                "result": "[exit_code=0]\npause flow ok",
            }],
        }
        falsifier = {
            "status": "done",
            "tool_evidence": [{
                "tool": "run_command", "target": "node tests/pause_flow.test.js",
                "result": "[exit_code=0]\nfalsifier ok",
            }],
        }
        with patch.object(mini, "verify_browser_application", side_effect=AssertionError("browser called")):
            browser = mini.optional_browser_check(
                task, task["execution_contract_child"],
                execution_evidence=builder["tool_evidence"] + falsifier["tool_evidence"],
            )

        route = self.route(browser["verification_applicability"], BROWSER)
        self.assertFalse(route["required"])
        self.assertFalse(route["applicable"])
        self.assertIsNone(route["target"])
        self.assertEqual(route["result"], SKIPPED_NOT_APPLICABLE)
        self.assertEqual(browser["verification_status"], SKIPPED_NOT_APPLICABLE)
        self.assertEqual(mini.RUN["browser_checks"], 0)
        self.assertGreaterEqual(mini.RUN["verification_applicability_checks"], 1)
        self.assertGreaterEqual(mini.RUN["verification_optional_targets_skipped"], 1)
        self.assertEqual(mini.RUN["verification_required_targets_unresolved"], 0)
        self.assertGreaterEqual(mini.RUN["browser_verifier_calls_avoided"], 1)
        gate = mini.evidence_gate(builder, falsifier, browser)
        self.assertTrue(gate["passed"], gate)
        self.assertFalse(any(
            item.get("failure_type") == mini.VERIFICATION_TARGET_UNRESOLVED
            for item in gate["deterministic_failures"]
        ))

    def test_legacy_optional_target_unresolved_observation_is_reclassified_as_skip(self):
        self.write("src/input.js")
        task = self.task(
            "EXEC-001.1-LEGACY", "Implement input behavior", ["input behavior is complete"], ["src/input.js"],
        )
        browser = mini.optional_browser_check(task, task)
        old_failure = json.dumps({
            "passed": False,
            "environment_error": False,
            "failure_type": mini.VERIFICATION_TARGET_UNRESOLVED,
            "resolution_status": mini.VERIFICATION_TARGET_UNRESOLVED,
        })
        builder = {
            "status": "done",
            "tool_evidence": [
                {"tool": "run_command", "target": "node --check src/input.js", "result": "[exit_code=0]"},
                {"tool": "verify_web_app", "target": "src/status_view.js", "result": old_failure},
            ],
        }
        falsifier = {
            "status": "done",
            "tool_evidence": [{
                "tool": "run_command", "target": "node tests/pause_flow.test.js",
                "result": "[exit_code=0]",
            }],
        }
        gate = mini.evidence_gate(builder, falsifier, browser)
        self.assertTrue(gate["passed"], gate)
        self.assertFalse(any(
            check.get("name") == "executable_failures"
            for check in gate["deterministic_failures"]
        ))

    def test_explicit_browser_requirement_without_html_fails_closed_before_verifier(self):
        self.write("src/app.js")
        task = self.task(
            "BROWSER-MISSING", "Verify browser-rendered behavior", [
                "the behavior is visible in the browser",
            ], ["src/app.js"],
        )
        with patch.object(mini, "verify_browser_application", side_effect=AssertionError("browser called")):
            result = mini.optional_browser_check(task, task)

        route = self.route(result["verification_applicability"], BROWSER)
        self.assertTrue(route["required"])
        self.assertTrue(route["applicable"])
        self.assertIsNone(route["target"])
        self.assertEqual(result["failure_type"], REQUIRED_VERIFICATION_TARGET_UNRESOLVED)
        self.assertEqual(result["verification_status"], "BLOCKED_REQUIRED_TARGET_MISSING")
        self.assertEqual(
            self.route(result["verification_applicability"], BROWSER)["result"],
            "BLOCKED_REQUIRED_TARGET_MISSING",
        )
        self.assertEqual(mini.classify_failure(
            {"status": "done"}, {"verification_aggregation": {}}, result,
        ), REQUIRED_VERIFICATION_TARGET_UNRESOLVED)
        self.assertEqual(mini.RUN["browser_checks"], 0)

    def test_supported_html_target_is_applicable_and_existing_verifier_path_is_reachable(self):
        self.write("index.html", "<!doctype html><title>App</title><main>App</main>")
        task = self.task(
            "BROWSER-PRESENT", "Verify browser-rendered behavior", ["browser-visible behavior works"], [],
        )
        with patch.object(
            mini, "browser_workspace_snapshot", return_value={"passed": True},
        ) as browser_executor:
            result = mini.optional_browser_check(task, task)

        route = self.route(result["verification_applicability"], BROWSER)
        self.assertTrue(route["required"])
        self.assertTrue(route["applicable"])
        self.assertEqual(route["target"], "index.html")
        self.assertTrue(result["passed"])
        browser_executor.assert_called_once()
        self.assertEqual(browser_executor.call_args.args[:2], ("index.html", "BROWSER-PRESENT"))

    def test_arbitrary_javascript_and_status_view_name_do_not_require_browser(self):
        self.write("src/app.js")
        self.write("src/status_view.js")
        self.write("tests/module.test.js", "test('module', () => {});\n")
        for path in ("src/app.js", "src/status_view.js"):
            artifact = mini.analyze_verification_applicability(
                self.task(path=path, goal=f"Update {Path(path).stem} module"),
                {"goal": f"Update {Path(path).stem} module"}, self.snapshot(),
            )
            route = self.route(artifact, BROWSER)
            self.assertFalse(route["required"])
            self.assertFalse(route["applicable"])
            self.assertIsNone(route["target"])
            self.assertIn("VERIFIER_NOT_REQUIRED", route["reason_codes"])

    def test_test_files_are_focused_test_evidence_not_browser_evidence(self):
        self.write("src/module.js")
        self.write("tests/module.test.js", "test('module', () => {});\n")
        artifact = mini.analyze_verification_applicability(
            self.task(goal="Run the focused test", done_when=["focused test passes"], scope=["src/module.js"]),
            {"goal": "Run the focused test", "test_contract": ["tests/module.test.js passes"]},
            self.snapshot(),
        )
        focused = self.route(artifact, FOCUSED_TEST)
        browser = self.route(artifact, BROWSER)
        self.assertTrue(focused["required"])
        self.assertTrue(focused["applicable"])
        self.assertEqual(focused["target"], "tests/module.test.js")
        self.assertFalse(browser["required"])
        self.assertFalse(browser["applicable"])

    def test_multiple_browser_targets_are_not_guessed(self):
        self.write("admin.html", "<!doctype html><title>Admin</title>")
        self.write("application.html", "<!doctype html><title>Application</title>")
        task = self.task(
            "AMBIGUOUS", "Verify browser-rendered behavior", ["browser behavior works"], [],
        )
        artifact = mini.analyze_verification_applicability(task, task, self.snapshot())
        route = self.route(artifact, BROWSER)
        self.assertTrue(route["required"])
        self.assertTrue(route["applicable"])
        self.assertIsNone(route["target"])
        self.assertIn("AMBIGUOUS_SUPPORTED_TARGET", route["reason_codes"])

    def test_optional_browser_skip_is_neither_pass_nor_fail_and_cannot_fake_evidence(self):
        artifact = mini.analyze_verification_applicability(
            self.task(goal="Update a Python module", scope=[]),
            {"goal": "Update a Python module"}, self.snapshot(),
        )
        browser = self.route(artifact, BROWSER)
        self.assertEqual(browser["result"], SKIPPED_NOT_APPLICABLE)
        aggregate = aggregate_verification_evidence(artifact, [], {
            "verification_status": SKIPPED_NOT_APPLICABLE,
            "passed": None,
        })
        self.assertFalse(aggregate["passed"])
        self.assertIn(VERIFICATION_EVIDENCE_UNAVAILABLE, aggregate["failure_codes"])
        self.assertEqual(len(aggregate["actual_passes"]), 0)
        self.assertEqual(len(aggregate["actual_failures"]), 0)
        self.assertTrue(any(
            item["kind"] == BROWSER for item in aggregate["skipped_not_applicable"]
        ))

    def test_required_failure_dominates_optional_skip(self):
        artifact = {
            "child_id": "C",
            "verification_routes": [
                {"kind": SYNTAX_STATIC_GATE, "required": True, "applicable": True,
                 "target": "src/app.js", "result": "PENDING", "reason_codes": [], "evidence_refs": []},
                {"kind": BROWSER, "required": False, "applicable": False,
                 "target": None, "result": SKIPPED_NOT_APPLICABLE,
                 "reason_codes": [], "evidence_refs": []},
            ],
        }
        aggregate = aggregate_verification_evidence(artifact, [{
            "tool": "run_command", "target": "node --check src/app.js",
            "result": "[exit_code=1]\nSyntaxError",
        }], {"verification_status": SKIPPED_NOT_APPLICABLE, "passed": None})
        self.assertFalse(aggregate["passed"])
        self.assertEqual(len(aggregate["actual_failures"]), 1)
        self.assertEqual(len(aggregate["skipped_not_applicable"]), 1)

    def test_no_actual_required_evidence_fails_closed(self):
        self.write("src/module.js")
        task = self.task(scope=["src/module.js"])
        browser = mini.optional_browser_check(task, task)
        gate = mini.evidence_gate({"status": "done", "tool_evidence": []}, browser_result=browser)
        self.assertFalse(gate["passed"])
        self.assertTrue(any(
            check.get("name") == "verification_evidence"
            for check in gate["deterministic_failures"]
        ))
        self.assertEqual(mini.RUN["verification_evidence_unavailable"], 1)

    def test_child_local_routes_do_not_copy_parent_test_route_to_every_sibling(self):
        self.write("src/input.js")
        self.write("src/status_view.js")
        self.write("tests/pause_flow.test.js", "test('pause', () => {});\n")
        parent = {
            "goal": "Add pause behavior across input and view",
            "test_contract": ["tests/pause_flow.test.js passes"],
            "allowed_mutation_paths": ["src/input.js", "src/status_view.js", "tests/pause_flow.test.js"],
        }
        input_task = self.task("INPUT", "Implement input behavior", ["input behavior complete"], ["src/input.js"], execution_contract_child={
            "goal": "Implement input behavior", "done_when": ["input behavior complete"],
            "allowed_mutation_paths": ["src/input.js"],
            "allowed_inspection_paths": ["src/input.js", "tests/pause_flow.test.js"],
            "test_contract": parent["test_contract"],
        })
        view_task = self.task("VIEW", "Implement status view behavior", ["view behavior complete"], ["src/status_view.js"], execution_contract_child={
            "goal": "Implement status view behavior", "done_when": ["view behavior complete"],
            "allowed_mutation_paths": ["src/status_view.js"],
            "allowed_inspection_paths": ["src/status_view.js", "tests/pause_flow.test.js"],
            "test_contract": parent["test_contract"],
        })
        test_task = self.task("TEST", "Update the focused pause test", ["focused test passes"], ["tests/pause_flow.test.js"], execution_contract_child={
            "goal": "Update the focused pause test", "done_when": ["focused test passes"],
            "allowed_mutation_paths": ["tests/pause_flow.test.js"],
            "allowed_inspection_paths": ["tests/pause_flow.test.js"],
            "test_contract": parent["test_contract"],
        })
        input_routes = mini.analyze_verification_applicability(input_task, parent, self.snapshot())
        view_routes = mini.analyze_verification_applicability(view_task, parent, self.snapshot())
        test_routes = mini.analyze_verification_applicability(test_task, parent, self.snapshot())
        self.assertFalse(any(item["kind"] == FOCUSED_TEST for item in input_routes["verification_routes"]))
        self.assertFalse(any(item["kind"] == FOCUSED_TEST for item in view_routes["verification_routes"]))
        self.assertTrue(any(item["kind"] == FOCUSED_TEST for item in test_routes["verification_routes"]))

    def test_run_tool_skips_optional_browser_before_existing_executor(self):
        mini.ACTIVE_TOOL_CONTRACT = {
            "goal": "Implement status view behavior",
            "task_id": "STATUS",
            "requirements": ["status view is updated"],
            "success_criteria": ["status view is updated"],
        }
        with patch.object(mini, "verify_browser_application", side_effect=AssertionError("browser called")):
            result = mini.run_tool("verify_web_app", {"path": "status_view.js"}, role="Builder")
        self.assertTrue(result.startswith("[not_applicable]"))
        payload = json.loads(result[len("[not_applicable] "):])
        self.assertEqual(payload["verification_status"], SKIPPED_NOT_APPLICABLE)
        self.assertEqual(mini.RUN["browser_checks"], 0)

    def test_invalid_authority_blocks_run_tool_before_browser_executor(self):
        mini.ACTIVE_TOOL_CONTRACT = {
            "goal": "Verify browser-rendered behavior",
            "task_id": "STALE-BROWSER",
        }
        with patch.object(mini, "_authority_terminal_failure", return_value=mini.APPROVED_PLAN_STALE), \
                patch.object(mini, "verify_browser_application", side_effect=AssertionError("browser called")):
            result = mini.run_tool("verify_web_app", {"path": "index.html"}, role="Builder")
        payload = json.loads(result)
        self.assertEqual(payload["failure_type"], mini.APPROVED_PLAN_STALE)
        self.assertFalse(payload["fallback_allowed"])
        self.assertEqual(mini.RUN["browser_checks"], 0)

    def test_route_hash_is_separate_from_authority_hash(self):
        contract = {
            "contract_hash": "immutable-contract",
            "plan_hash": "immutable-plan",
            "goal": "Update one module",
            "allowed_mutation_paths": ["src/module.js"],
        }
        task = self.task(scope=["src/module.js"])
        before = copy.deepcopy(contract)
        artifact = mini.analyze_verification_applicability(task, contract, self.snapshot())
        self.assertEqual(contract, before)
        self.assertEqual(contract["contract_hash"], "immutable-contract")
        self.assertNotIn("verification_applicability_hash", contract)
        self.assertTrue(artifact["verification_applicability_hash"])
        self.assertNotEqual(artifact["verification_applicability_hash"], contract["contract_hash"])
        self.assertEqual(
            deterministic_hash({"kind": "BROWSER", "required": True}),
            deterministic_hash({"required": True, "kind": "BROWSER"}),
        )
        same_object = {
            "id": "SAME",
            "goal": "Update one module",
            "allowed_mutation_paths": ["src/module.js"],
            "contract_hash": "same-object-contract",
        }
        same_before = copy.deepcopy(same_object)
        mini.analyze_verification_applicability(same_object, same_object, self.snapshot())
        self.assertEqual(same_object, same_before)


if __name__ == "__main__":
    unittest.main()
