import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import mini


class MiniAgentRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "test-model"
        mini.MODEL_CAPABILITIES = set()
        mini.ROUTER_MODEL = ""
        mini.FALLBACK_MODEL = ""
        mini.VISION_MODEL = ""
        mini.reset_run("recursive")
        mini.RUN["tasks_created"] = 1

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    def test_task_fit_contract_rejects_contradictions(self):
        self.assertTrue(mini._fit_validator({"decision": "execute", "reason": "small", "subtasks": []}))
        self.assertFalse(mini._fit_validator({"decision": "execute", "reason": "bad", "subtasks": ["x"]}))
        self.assertTrue(mini._fit_validator({"decision": "split", "reason": "broad", "subtasks": ["a", "b"]}))
        self.assertFalse(mini._fit_validator({"decision": "split", "reason": "bad", "subtasks": []}))

    def test_invalid_structured_task_fit_uses_nonfatal_fallback(self):
        task = {"id": "ROOT", "goal": "build several features", "depth": 0}
        contract = {"requirements": ["core", "tests", "polish"], "constraints": [], "success_criteria": []}
        for failure in (mini.StructuredOutputError("invalid"), mini.ProviderError("cuda failure")):
            with self.subTest(failure=type(failure).__name__), \
                    patch.object(mini, "structured_model_call", side_effect=failure):
                decision = mini.decide_task_fit(task, 0, contract)
                self.assertEqual(decision["decision"], "split")
                self.assertGreaterEqual(len(decision["subtasks"]), 2)

    def test_invalid_goal_json_fallback_preserves_the_full_request(self):
        raw = "Build a project with requirement " + ("detailed behavior " * 200)
        with patch.object(mini, "structured_model_call", side_effect=mini.StructuredOutputError("invalid")):
            contract = mini.understand_goal(raw, "use local files")
        self.assertEqual(contract["status"], "ready")
        self.assertEqual(contract["requirements"], [raw])
        self.assertEqual(contract["constraints"], ["use local files"])

    def test_transaction_restores_modified_and_created_files(self):
        original = mini.WORKSPACE / "original.txt"
        original.write_text("before", encoding="utf-8")
        mini.begin_transaction("T")
        mini.write_file("original.txt", "after")
        mini.write_file("created.txt", "temporary")
        mini.rollback_transaction()
        self.assertEqual(original.read_text(encoding="utf-8"), "before")
        self.assertFalse((mini.WORKSPACE / "created.txt").exists())

    def test_builder_can_revise_only_a_file_it_created_in_the_active_transaction(self):
        mini.begin_transaction("T")
        first = mini.write_file("generated.html", "version one", role="Builder")
        second = mini.write_file("generated.html", "version two", role="Builder")
        self.assertIn("wrote file", first)
        self.assertIn("wrote file", second)
        self.assertEqual((mini.WORKSPACE / "generated.html").read_text(encoding="utf-8"), "version two")
        mini.rollback_transaction()
        self.assertFalse((mini.WORKSPACE / "generated.html").exists())

    def test_web_entrypoint_is_discovered_without_localhost_in_prompt(self):
        (mini.WORKSPACE / "index.html").write_text("<!doctype html>", encoding="utf-8")
        target = mini.discover_web_entrypoint(
            {"id": "T", "goal": "Build a polished 3D browser game"},
            {"goal": "game", "requirements": [], "constraints": [], "success_criteria": []},
        )
        self.assertEqual(target, {"path": "index.html"})

    def test_falsifier_is_not_offered_mutating_tools(self):
        names = {item["function"]["name"] for item in mini.tools_for_role("Falsifier")}
        self.assertNotIn("write_file", names)
        self.assertNotIn("edit_file", names)
        self.assertIn("verify_web_app", names)

    def test_role_models_are_all_pinned_to_the_selected_gemma_model(self):
        models = [
            {"name": "gemma4:e4b", "size": 9_600, "details": {"parameter_size": "8B"}},
            {"name": "code-coder:7b", "size": 4_700, "details": {"parameter_size": "7B"}},
            {"name": "vision:4b", "size": 3_300, "details": {"parameter_size": "4B"}},
        ]
        capabilities = {
            "gemma4:e4b": {"completion", "tools", "vision"},
            "code-coder:7b": {"completion", "tools"},
            "vision:4b": {"completion", "tools", "vision"},
        }
        with patch.object(mini, "fetch_model_capabilities", side_effect=lambda name: capabilities[name]):
            mini.configure_role_models(models, "gemma4:e4b")
        self.assertEqual(mini.ROUTER_MODEL, "gemma4:e4b")
        self.assertEqual(mini.FALLBACK_MODEL, "")
        self.assertEqual(mini.VISION_MODEL, "gemma4:e4b")

    def test_provider_failure_never_falls_back_to_another_model(self):
        mini.MODEL = "gemma4:e4b"
        mini.FALLBACK_MODEL = ""
        failed = Mock(status_code=500, text="CUDA error")
        with patch.object(mini.requests, "post", return_value=failed) as request:
            with self.assertRaises(mini.ProviderError):
                mini.ask_ollama([{"role": "user", "content": "hello"}], tools=None,
                                provider_retries=0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["json"]["model"], "gemma4:e4b")

    def test_builder_reserves_output_budget_and_compacts_old_tool_arguments(self):
        mini.MODEL = "gemma4:e4b"
        response = Mock(status_code=200)
        response.json.return_value = {"message": {"role": "assistant", "content": "done"}}
        messages = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "edit_file", "arguments": {
                    "path": "index.html", "old": "a" * 20_000, "new": "b" * 20_000,
                }}
            }]},
            {"role": "tool", "tool_name": "edit_file", "content": "error"},
        ]
        with patch.object(mini.requests, "post", return_value=response) as request:
            mini.ask_ollama(messages, tools=None, provider_retries=0, role="Builder")
        payload = request.call_args.kwargs["json"]
        self.assertEqual(payload["options"]["num_predict"], 4096)
        arguments = payload["messages"][1]["tool_calls"][0]["function"]["arguments"]
        self.assertIn("compacted prior content", arguments["old"])

    def test_repairer_cannot_replace_an_existing_file(self):
        target = mini.WORKSPACE / "index.html"
        target.write_text("original", encoding="utf-8")
        result = mini.run_tool("write_file", {"path": "index.html", "content": "replacement"}, role="Repairer")
        self.assertTrue(result.startswith("error:"))
        self.assertEqual(target.read_text(encoding="utf-8"), "original")
        self.assertNotIn("write_file", {item["function"]["name"] for item in mini.tools_for_role("Repairer")})
        new_result = mini.run_tool("write_file", {"path": "new.py", "content": "pass"}, role="Repairer")
        self.assertTrue(new_result.startswith("error:"))
        self.assertFalse((mini.WORKSPACE / "new.py").exists())

    def test_no_tool_evidence_cannot_pass_quality_gate(self):
        builder = {"status": "done", "tool_evidence": []}
        quality = {"checks": mini.deterministic_quality_checks(builder)}
        self.assertFalse(mini.evidence_gate(builder, quality)["passed"])

    def test_model_only_quality_claim_cannot_trigger_a_code_repair_failure(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "run_command", "target": "python -m unittest", "result": "[exit_code=0]"},
        ]}
        quality = {"checks": [
            {"name": "correctness", "status": "FAIL", "source": "model",
             "evidence": "not confirmed"},
        ]}
        gate = mini.evidence_gate(builder, quality)
        self.assertTrue(gate["passed"])
        self.assertEqual(len(gate["advisory_failures"]), 1)

    def test_resolved_historical_verification_does_not_poison_quality(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
        ]}
        checks = mini.deterministic_quality_checks(builder)
        self.assertNotIn("tool_execution", {check["name"] for check in checks})

    def test_fresh_browser_result_supersedes_an_old_builder_browser_failure(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
        ]}
        browser = {"passed": True, "entry_path": "index.html"}
        checks = mini.deterministic_quality_checks(builder, browser_result=browser)
        self.assertNotIn("tool_execution", {check["name"] for check in checks})

    def test_visual_provider_failure_is_environmental_and_never_a_code_repair_signal(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
        ]}
        vision = {"passed": False, "environment_error": True, "status": "ERROR",
                  "evidence": "CUDA out of memory"}
        self.assertEqual(
            mini.classify_failure(builder, {"checks": []}, {"passed": True}, vision),
            "ENVIRONMENT_ERROR",
        )

    def test_visual_model_opinion_is_advisory_not_a_deterministic_code_failure(self):
        builder = {"status": "done", "tool_evidence": [
            {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
        ]}
        vision = {"passed": False, "environment_error": False, "status": "FAIL",
                  "evidence": "screenshot cannot demonstrate persistence"}
        checks = mini.deterministic_quality_checks(
            builder,
            browser_result={"passed": True, "entry_path": "index.html"},
            vision_review=vision,
        )
        self.assertNotIn("visual_verification", {check["name"] for check in checks})

    def test_child_verification_contract_does_not_require_unbuilt_sibling_features(self):
        root_contract = {
            "goal": "Build complete timer",
            "requirements": ["timer logic", "visual polish", "persistence"],
            "constraints": ["local only"],
            "success_criteria": ["complete app works"],
        }
        child = {"id": "1", "goal": "Implement timer logic"}
        leaf = mini.contract_for_task(child, root_contract)
        self.assertEqual(leaf["requirements"], ["Implement timer logic"])
        self.assertNotIn("visual polish", leaf["requirements"])
        self.assertEqual(mini.contract_for_task({"id": "ROOT", "goal": "root"}, root_contract), root_contract)

    def test_incomplete_tool_call_gets_targeted_non_mutating_error(self):
        error = mini.tool_argument_error("edit_file", {"new": "large replacement"})
        self.assertIn("incomplete or truncated", error)
        self.assertIn("path", error)
        self.assertIn("smaller", error)
        self.assertEqual(mini.list_files(), "(workspace is empty)")

    def test_generated_unicode_cannot_crash_a_legacy_windows_console(self):
        raw = io.BytesIO()
        stream = io.TextIOWrapper(raw, encoding="cp1256", errors="strict")
        mini.configure_console_streams([stream])
        stream.write("Focus \u2728")
        stream.flush()
        self.assertIn(b"Focus", raw.getvalue())

    def test_cohesive_web_artifact_uses_vertical_stages_not_conflicting_recursive_children(self):
        contract = {
            "goal": "Create a self-contained browser focus timer",
            "requirements": ["timer", "settings", "persistence", "responsive UI"],
            "constraints": ["one local HTML entry point", "no build step"],
            "success_criteria": ["works in browser"],
            "original_goal": "Create a self-contained browser focus timer in one local HTML file",
        }
        choice = mini.normalize_execution_choice(
            {"mode": "recursive", "reason": "many features"}, contract
        )
        self.assertEqual(choice["mode"], "baseline")
        self.assertIn("vertical stages", choice["reason"])

    def test_parent_aggregation_attempts_recovery_when_a_child_failed(self):
        task = {"id": "ROOT", "goal": "integrate the complete app"}
        contract = {"goal": task["goal"], "requirements": ["a", "b"], "constraints": [],
                    "success_criteria": ["verified"], "original_goal": task["goal"]}
        children = [
            {"task": "a", "result": {"status": "done", "summary": "done"}},
            {"task": "b", "result": {"status": "failed", "summary": "failed"}},
        ]
        builder = {"status": "done", "summary": "recovered", "memory": {},
                   "tool_evidence": [{"tool": "run_command", "result": "[exit_code=0]\nverified"}]}
        quality = {"checks": [{"name": "tests", "status": "PASS", "evidence": "verified"}]}
        with patch.object(mini, "execute_agent_task", return_value=builder) as execute, \
                patch.object(mini, "optional_browser_check", return_value=None), \
                patch.object(mini, "maybe_vision_review", return_value=None), \
                patch.object(mini, "review_quality", return_value=quality):
            result = mini.aggregate_task(task, contract, children, {}, root=True)
        self.assertTrue(execute.called)
        self.assertEqual(result["status"], "done")
        self.assertTrue(any(item["task"] == "b" and item["status"] == "failed"
                            for item in result["children"]))

    def test_shell_composition_and_inline_code_are_refused(self):
        self.assertIsNotNone(mini._validated_command_parts("python -c \"print(1)\"")[1])
        self.assertIsNotNone(mini._validated_command_parts("git status && git clean -fd")[1])
        self.assertIsNone(mini._validated_command_parts("git status")[1])

    def test_tool_history_is_persisted_in_sqlite_not_rewritten_json(self):
        memory = mini.load_memory()
        mini.update_memory(
            memory,
            "run_command",
            {"command": "python -m unittest"},
            "[exit_code=0] 3 passed",
            role="Builder",
            task_id="ROOT.S1",
        )

        store = mini.get_memory_store()
        self.assertEqual(store.event_count(), 1)
        self.assertTrue(store.db_path.exists())
        self.assertFalse((mini.WORKSPACE / mini.MEMORY_FILE).exists())
        self.assertLessEqual(len(memory["operations"]), 8)

    def test_complex_builder_uses_bounded_gemma_authored_stages(self):
        contract = {
            "status": "ready",
            "goal": "Build a web app",
            "requirements": ["data flow", "error state", "responsive UI", "browser checks"],
            "constraints": [],
            "success_criteria": ["verified"],
        }
        mini.begin_durable_run(contract)
        memory = mini.load_memory()
        calls = []

        def fake_stage(task_text, mem, messages=None, role="Builder", task_id="ROOT", extra_context=""):
            calls.append({"task": task_text, "task_id": task_id, "context": extra_context})
            return {
                "status": "done",
                "summary": f"Gemma completed {task_id}",
                "messages": [],
                "memory": mem,
                "tool_evidence": [
                    {"tool": "run_command", "target": "python -m unittest", "result": "[exit_code=0]"}
                ],
                "provider_error": None,
            }

        with patch.object(mini, "execute_agent_task", side_effect=fake_stage):
            result = mini.execute_builder_stages(
                {"id": "ROOT", "goal": contract["goal"], "parent": None},
                contract,
                memory,
                base_context="authoritative contract",
            )

        self.assertEqual(result["status"], "done")
        self.assertGreaterEqual(len(calls), 2)
        self.assertLessEqual(len(calls), 4)
        self.assertEqual([call["task_id"] for call in calls], [f"ROOT.S{i}" for i in range(1, len(calls) + 1)])
        self.assertTrue(all("sole author" in call["context"] for call in calls))

    def test_only_evidence_gated_outcome_enters_retrievable_memory(self):
        contract = {"goal": "Build API", "requirements": ["health endpoint"]}
        task = {"id": "ROOT", "goal": "Build API"}

        mini.remember_verified_outcome(task, contract, "health endpoint passed tests", ["api.py"])
        context = mini.relevant_memory_context("API health endpoint", role="Builder")

        self.assertIn("Verified task completed", context)
        self.assertIn("api.py", context)


if __name__ == "__main__":
    unittest.main()
