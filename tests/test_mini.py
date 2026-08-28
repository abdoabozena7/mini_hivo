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

    def test_explicit_bullets_override_a_lossy_model_contract(self):
        raw = """Build a focus app.
Requirements:
- working timer controls
- persist settings
- responsive keyboard UI
"""
        model_contract = {
            "status": "ready", "goal": "Build app",
            "requirements": ["Build everything"], "constraints": [], "success_criteria": ["works"],
        }
        normalized = mini.normalize_goal_contract(raw, model_contract)
        self.assertEqual(normalized["requirements"], [
            "working timer controls", "persist settings", "responsive keyboard UI",
        ])

    def test_explicit_contract_skips_weak_model_goal_meeting(self):
        raw = "Build a tool.\n- first behavior\n- second behavior"
        with patch.object(mini, "understand_goal") as understand:
            contract = mini.get_goal_contract(raw, interactive=False)
        understand.assert_not_called()
        self.assertEqual(contract["requirements"], ["first behavior", "second behavior"])

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

    def test_numbered_range_edit_is_compact_transactional_and_verified(self):
        target = mini.WORKSPACE / "module.py"
        target.write_text("one\ntwo\nthree\nfour\n", encoding="utf-8")
        mini.begin_transaction("T")
        view = mini.read_file_range("module.py", 2, 3)
        result = mini.edit_file_range("module.py", 2, 3, "TWO\nTHREE")
        self.assertIn("2: two", view)
        self.assertIn("edited lines 2-3", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "one\nTWO\nTHREE\nfour\n")
        mini.rollback_transaction()
        self.assertEqual(target.read_text(encoding="utf-8"), "one\ntwo\nthree\nfour\n")

    def test_syntax_regression_is_rejected_before_it_reaches_workspace(self):
        target = mini.WORKSPACE / "app.js"
        target.write_text("function ok() { return 1; }\n", encoding="utf-8")
        mini.begin_transaction("T")
        result = mini.edit_file_range("app.js", 1, 1, "function broken() {", role="Builder")
        self.assertIn("syntax validation", result)
        self.assertEqual(target.read_text(encoding="utf-8"), "function ok() { return 1; }\n")
        mini.rollback_transaction()

    def test_repeated_exact_edit_mismatch_routes_model_to_range_tool(self):
        hint = mini.tool_recovery_hint(
            "edit_file", "error: expected 1 exact replacement(s), found 0; file was not changed", 2
        )
        self.assertIn("edit_file_range", hint)
        self.assertIn("Stop repeating", hint)

    def test_repeated_stale_range_and_syntax_errors_get_specific_recovery(self):
        range_hint = mini.tool_recovery_hint(
            "edit_file_range", "error: invalid line range 90-110; file has 42 lines", 2,
        )
        syntax_hint = mini.tool_recovery_hint(
            "edit_file_range", "error: JavaScript syntax validation failed", 2,
        )
        self.assertIn("stale or invalid", range_hint)
        self.assertIn("reported total", range_hint)
        self.assertIn("syntactically incomplete", syntax_hint)
        self.assertIn("closing delimiter", syntax_hint)

    def test_browser_failure_digest_preserves_actionable_before_after_evidence(self):
        raw = '{"passed":false,"environment_error":false,"interaction_checks":[' \
              '{"name":"timer_start_changes_visible_time","passed":false,' \
              '"before":{"seconds":1500},"after":{"seconds":1500}}],' \
              '"failures":[{"code":"failed_interaction","evidence":"start"}]}'

        digest = mini.verification_failure_digest(raw)
        signature = mini.verification_failure_signature(raw)

        self.assertIn('"before": {"seconds": 1500}', digest)
        self.assertIn("deterministic browser clock", digest)
        self.assertEqual(signature, ("interaction:timer_start_changes_visible_time",))

    def test_missing_clock_digest_points_to_markup_before_timer_logic(self):
        raw = '{"passed":false,"interaction_checks":[' \
              '{"name":"timer_start_changes_visible_time","passed":false,' \
              '"before":null,"missing":["clock"]}]}'

        digest = mini.verification_failure_digest(raw)

        self.assertIn("combined MM:SS", digest)
        self.assertIn("before changing button or interval logic", digest)

    def test_phase_progress_changes_stagnation_signature_and_missing_count_diagnosis(self):
        phase_stuck = (
            '{"passed":false,"interaction_checks":[{"name":'
            '"timer_phase_switches_and_counts_session","passed":false,'
            '"before_phase":"Focus","after_phase":"Focus",'
            '"before_count":null,"after_count":null}]}'
        )
        phase_fixed = (
            '{"passed":false,"interaction_checks":[{"name":'
            '"timer_phase_switches_and_counts_session","passed":false,'
            '"before_phase":"Focus","after_phase":"Break",'
            '"before_count":null,"after_count":null}]}'
        )

        first = mini.verification_failure_signature(phase_stuck)
        second = mini.verification_failure_signature(phase_fixed)
        digest = mini.verification_failure_digest(phase_fixed)

        self.assertNotEqual(first, second)
        self.assertIn("phase_not_changed", " ".join(first))
        self.assertIn("completed_count_missing", " ".join(second))
        self.assertIn("Completed Sessions: 0", digest)
        self.assertIn("Preserve the working phase transition", digest)

    def test_three_identical_browser_failures_route_to_fresh_focused_context(self):
        failed = (
            '{"passed":false,"environment_error":false,"interaction_checks":['
            '{"name":"timer_start_changes_visible_time","passed":false}],'
            '"failures":[{"code":"failed_interaction","evidence":"start"}]}'
        )
        tool_call = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "verify_web_app", "arguments": {"path": "index.html"}},
            }],
        }
        memory = mini.load_memory()
        with patch.object(mini, "ask_ollama", return_value=tool_call) as ask, \
                patch.object(mini, "run_tool", return_value=failed):
            result = mini.execute_agent_task("fix timer", memory, role="Builder", task_id="T")

        self.assertEqual(result["status"], "too_broad")
        self.assertEqual(result["recovery_strategy"], "fresh_focused")
        self.assertEqual(ask.call_count, 3)
        self.assertIn("STAGNANT_VERIFICATION", result["summary"])

    def test_coherent_rewrite_rejects_catastrophic_fragment_before_mutation(self):
        target = mini.WORKSPACE / "script.js"
        original = "function feature() { return true; }\n" * 80
        target.write_text(original, encoding="utf-8")

        result = mini.coherent_rewrite_preflight({
            "path": "script.js",
            "content": "function saveSettings() { return true; }\n",
        })

        self.assertIn("appears to be a fragment", result)
        self.assertIn("No file was changed", result)
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_successful_stage_verification_stops_before_model_can_regress_it(self):
        verified = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "verify_web_app", "arguments": {"path": "index.html"}},
            }],
        }
        destructive_followup = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {
                    "name": "write_file",
                    "arguments": {"path": "index.html", "content": "broken"},
                },
            }],
        }
        memory = mini.load_memory()

        with patch.object(mini, "ask_ollama", side_effect=[verified, destructive_followup]) as ask, \
                patch.object(mini, "run_tool", return_value='{"passed": true}') as run_tool:
            result = mini.execute_agent_task("build timer", memory, role="Builder", task_id="T")

        self.assertEqual(result["status"], "done")
        self.assertIn("stop-on-proof", result["summary"])
        self.assertEqual(ask.call_count, 1)
        run_tool.assert_called_once_with("verify_web_app", {"path": "index.html"}, role="Builder")

    def test_four_failed_mutations_on_model_draft_route_early_to_rewrite(self):
        target = mini.WORKSPACE / "script.js"
        target.write_text("const version = 1;\n", encoding="utf-8")
        mini.get_memory_store().mark_model_artifact("script.js", mini.RUN_ID)
        tool_call = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {
                    "name": "edit_file",
                    "arguments": {"path": "script.js", "old": "version", "new": "broken"},
                },
            }],
        }
        memory = mini.load_memory()
        with patch.object(mini, "ask_ollama", return_value=tool_call) as ask, \
                patch.object(mini, "run_tool", return_value="error: JavaScript syntax validation failed"):
            result = mini.execute_agent_task("fix script", memory, role="Builder", task_id="T")

        self.assertEqual(result["status"], "too_broad")
        self.assertEqual(result["recovery_strategy"], "rewrite_unverified")
        self.assertEqual(result["recovery_targets"], ["script.js"])
        self.assertEqual(ask.call_count, 4)
        self.assertIn("STAGNANT_MUTATION", result["summary"])

    def test_javascript_syntax_guard_accepts_unicode_on_windows(self):
        target = mini.WORKSPACE / "unicode.js"

        error = mini.source_validation_error(target, "const indicator = '⏳';\n")

        self.assertIsNone(error)

    def test_browser_javascript_is_not_misdiagnosed_by_running_it_under_node(self):
        target = mini.WORKSPACE / "script.js"
        target.write_text(
            "const saved = localStorage.getItem('duration');\n"
            "document.body.dataset.saved = saved || '';\n",
            encoding="utf-8",
        )

        with patch.object(mini.subprocess, "run") as process:
            result = mini.run_file("script.js")

        process.assert_not_called()
        self.assertTrue(result.startswith("[not_applicable]"))
        self.assertIn("verify_web_app", result)
        self.assertFalse(mini.tool_result_failed(result))

    def test_builder_can_resume_only_matching_unverified_model_artifact(self):
        target = mini.WORKSPACE / "draft.js"
        target.write_text("const version = 1;\n", encoding="utf-8")
        store = mini.get_memory_store()
        store.mark_model_artifact("draft.js", mini.RUN_ID)

        mini.begin_transaction("resume")
        allowed = mini.write_file("draft.js", "const version = 2;\n", role="Builder")
        self.assertIn("resumed unverified model artifact", allowed)
        mini.rollback_transaction()
        self.assertEqual(target.read_text(encoding="utf-8"), "const version = 1;\n")
        self.assertTrue(store.is_unverified_model_artifact("draft.js"))

        store.mark_artifacts_verified(["draft.js"], mini.RUN_ID)
        mini.begin_transaction("protected")
        refused = mini.write_file("draft.js", "const version = 3;\n", role="Builder")
        self.assertIn("user-owned or verified", refused)

    def test_web_entrypoint_is_discovered_without_localhost_in_prompt(self):
        (mini.WORKSPACE / "index.html").write_text("<!doctype html>", encoding="utf-8")
        target = mini.discover_web_entrypoint(
            {"id": "T", "goal": "Build a polished 3D browser game"},
            {"goal": "game", "requirements": [], "constraints": [], "success_criteria": []},
        )
        self.assertEqual(target, {"path": "index.html"})

    def test_model_browser_tool_uses_the_active_contract_verification_profile(self):
        contract = {
            "goal": "Build a focus timer",
            "requirements": ["persist settings", "keyboard accessible", "reduced-motion support"],
        }
        mini.begin_durable_run(contract)
        with patch.object(mini, "browser_workspace_snapshot", return_value={"passed": True}) as browser:
            result = mini.run_tool("verify_web_app", {"path": "index.html"}, role="Builder")
        profile = browser.call_args.kwargs["profile"]
        self.assertEqual(profile.kind, "timer")
        self.assertIn("settings_persistence", profile.required_interactions)
        self.assertEqual(result, '{"passed": true}')

    def test_falsifier_is_not_offered_mutating_tools(self):
        names = {item["function"]["name"] for item in mini.tools_for_role("Falsifier")}
        self.assertNotIn("write_file", names)
        self.assertNotIn("edit_file", names)
        self.assertIn("verify_web_app", names)

    def test_coherent_rewrite_pass_cannot_micro_patch(self):
        names = {
            item["function"]["name"]
            for item in mini.tools_for_role("Builder", tool_policy="coherent_rewrite")
        }
        self.assertIn("write_file", names)
        self.assertIn("verify_web_app", names)
        self.assertNotIn("edit_file", names)
        self.assertNotIn("edit_file_range", names)

    def test_coherent_rewrite_policy_rejects_hallucinated_micro_patch_at_execution(self):
        hallucinated_edit = {
            "role": "assistant", "content": "", "tool_calls": [{
                "function": {
                    "name": "edit_file",
                    "arguments": {"path": "app.js", "old": "before", "new": "after"},
                },
            }],
        }
        finishes = {"role": "assistant", "content": "cannot patch", "tool_calls": []}
        memory = mini.load_memory()

        with patch.object(mini, "ask_ollama", side_effect=[hallucinated_edit, finishes]) as ask, \
                patch.object(mini, "run_tool") as run_tool:
            result = mini.execute_agent_task(
                "rewrite the model draft", memory, role="Builder", task_id="T",
                tool_policy="coherent_rewrite",
            )

        run_tool.assert_not_called()
        self.assertEqual(result["status"], "done")
        self.assertIn("unavailable under the active coherent rewrite policy",
                      result["tool_evidence"][0]["result"])
        offered_names = {
            item["function"]["name"]
            for item in ask.call_args_list[0].kwargs["tools"]
        }
        self.assertNotIn("edit_file", offered_names)

    def test_coherent_rewrite_unlocks_focused_edit_only_after_rewrite_and_failed_verify(self):
        responses = [
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "write_file", "arguments": {"path": "app.js", "content": "draft"}},
            }]},
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "verify_web_app", "arguments": {"path": "index.html"}},
            }]},
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {
                    "name": "edit_file",
                    "arguments": {"path": "app.js", "old": "draft", "new": "fixed"},
                },
            }]},
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {"name": "verify_web_app", "arguments": {"path": "index.html"}},
            }]},
        ]

        def tool_result(name, _args, role=None):
            if name == "verify_web_app":
                verification_calls = sum(
                    1 for call in run_tool.call_args_list if call.args[0] == "verify_web_app"
                )
                return '{"passed": false}' if verification_calls == 1 else '{"passed": true}'
            return "mutation succeeded"

        memory = mini.load_memory()
        with patch.object(mini, "ask_ollama", side_effect=responses) as ask, \
                patch.object(mini, "run_tool") as run_tool:
            run_tool.side_effect = tool_result
            result = mini.execute_agent_task(
                "repair draft", memory, role="Builder", task_id="T",
                tool_policy="coherent_rewrite",
            )

        first_names = {item["function"]["name"] for item in ask.call_args_list[0].kwargs["tools"]}
        pre_verify_names = {item["function"]["name"] for item in ask.call_args_list[1].kwargs["tools"]}
        followup_names = {item["function"]["name"] for item in ask.call_args_list[2].kwargs["tools"]}
        self.assertNotIn("edit_file", first_names)
        self.assertNotIn("edit_file", pre_verify_names)
        self.assertIn("edit_file", followup_names)
        self.assertNotIn("write_file", followup_names)
        self.assertEqual(result["status"], "done")

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
        with patch.object(mini, "http_post_json", return_value=failed) as request:
            with self.assertRaises(mini.ProviderError):
                mini.ask_ollama([{"role": "user", "content": "hello"}], tools=None,
                                provider_retries=0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs["payload"]["model"], "gemma4:e4b")

    def test_transient_ollama_worker_crash_retries_the_same_gemma_model(self):
        mini.MODEL = "gemma4:e4b"
        crashed = Mock(status_code=500, text="llama-server process has terminated: CUDA error")
        recovered = Mock(status_code=200)
        recovered.json.return_value = {"message": {"role": "assistant", "content": "recovered"}}
        with patch.object(mini, "http_post_json", side_effect=[crashed, recovered]) as request, \
                patch.object(mini.time, "sleep") as sleep:
            message = mini.ask_ollama(
                [{"role": "user", "content": "continue"}], tools=None,
                provider_retries=1, role="Builder",
            )
        self.assertEqual(message["content"], "recovered")
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.kwargs["payload"]["model"] == "gemma4:e4b" for call in request.call_args_list))
        self.assertEqual(request.call_args_list[1].kwargs["payload"]["options"]["num_gpu"], 0)
        self.assertTrue(mini.FORCE_CPU_FOR_RUN)
        self.assertTrue(sleep.called)

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
        with patch.object(mini, "http_post_json", return_value=response) as request:
            mini.ask_ollama(messages, tools=None, provider_retries=0, role="Builder")
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["options"]["num_predict"], 4096)
        self.assertEqual(payload["options"]["temperature"], 0.1)
        self.assertEqual(payload["options"]["seed"], 0)
        arguments = payload["messages"][1]["tool_calls"][0]["function"]["arguments"]
        self.assertEqual(arguments["old"], "")
        self.assertEqual(arguments["new"], "")

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

    def test_cohesive_web_mode_skips_model_router_call(self):
        contract = {
            "goal": "Create a self-contained web app",
            "requirements": ["feature one", "feature two"],
            "constraints": ["no build step"],
            "original_goal": "Create a self-contained web app",
        }
        with patch.object(mini, "structured_model_call") as structured:
            choice = mini.decide_execution_mode(contract["original_goal"], contract)
        structured.assert_not_called()
        self.assertEqual(choice["mode"], "baseline")

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

    def test_exhausted_stage_gets_one_fresh_context_continuation_in_same_transaction(self):
        contract = {
            "status": "ready",
            "goal": "Build a focus timer",
            "requirements": ["working timer controls"],
            "constraints": [],
            "success_criteria": ["browser verification passes"],
        }
        memory = mini.load_memory()
        calls = []

        def fake_pass(task_text, mem, messages=None, role="Builder", task_id="ROOT", extra_context=""):
            calls.append({"task_id": task_id, "context": extra_context})
            if len(calls) == 1:
                exhausted_memory = dict(mem)
                exhausted_memory["last_error"] = "pauseTimer is not defined"
                return {
                    "status": "too_broad",
                    "summary": "step limit",
                    "messages": ["large stale history"],
                    "memory": exhausted_memory,
                    "tool_evidence": [
                        {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": false}'},
                    ],
                    "provider_error": None,
                }
            return {
                "status": "done",
                "summary": "Gemma fixed and verified the timer",
                "messages": [],
                "memory": mem,
                "tool_evidence": [
                    {"tool": "verify_web_app", "target": "index.html", "result": '{"passed": true}'},
                ],
                "provider_error": None,
            }

        with patch.object(mini, "execute_agent_task", side_effect=fake_pass):
            result = mini.execute_builder_stages(
                {"id": "ROOT", "goal": contract["goal"], "parent": None},
                contract,
                memory,
                base_context="authoritative contract",
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["task_id"], calls[1]["task_id"])
        self.assertIn("CONTINUATION PASS 1/1", calls[1]["context"])
        self.assertIn("pauseTimer is not defined", calls[1]["context"])
        self.assertNotIn("large stale history", calls[1]["context"])
        self.assertEqual(result["stage_records"][0]["continuations"], 1)
        self.assertEqual(mini.RUN["stage_continuations"], 1)
        self.assertEqual(len(result["tool_evidence"]), 2)

    def test_stagnant_stage_continuation_requests_model_owned_coherent_rewrite(self):
        contract = {
            "status": "ready", "goal": "Build a focus timer",
            "requirements": ["working timer controls"], "constraints": [],
            "success_criteria": ["verified"],
        }
        draft = mini.WORKSPACE / "script.js"
        draft.write_text("const broken = true;\n", encoding="utf-8")
        mini.get_memory_store().mark_model_artifact("script.js", mini.RUN_ID)
        memory = mini.load_memory()
        calls = []
        policies = []

        def fake_pass(
            task_text, mem, messages=None, role="Builder", task_id="ROOT", extra_context="", tool_policy=None,
        ):
            calls.append(extra_context)
            policies.append(tool_policy)
            if len(calls) == 1:
                failed_memory = dict(mem)
                failed_memory["last_error"] = "start stayed at 25:00"
                return {
                    "status": "too_broad", "summary": "STAGNANT_VERIFICATION",
                    "messages": [], "memory": failed_memory,
                    "tool_evidence": [{"tool": "verify_web_app", "target": "index.html", "result": "failed"}],
                    "provider_error": None, "recovery_strategy": "rewrite_unverified",
                }
            return {
                "status": "done", "summary": "rewritten", "messages": [], "memory": mem,
                "tool_evidence": [{"tool": "verify_web_app", "target": "index.html", "result": "passed"}],
                "provider_error": None,
            }

        with patch.object(mini, "execute_agent_task", side_effect=fake_pass):
            result = mini.execute_builder_stages(
                {"id": "ROOT", "goal": contract["goal"], "parent": None}, contract, memory,
            )

        self.assertEqual(result["status"], "done")
        self.assertIn("COHERENT REWRITE RECOVERY", calls[1])
        self.assertIn('"script.js"', calls[1])
        self.assertIn("use write_file", calls[1])
        self.assertEqual(policies, [None, "coherent_rewrite"])
        self.assertEqual(mini.RUN["coherent_rewrite_recoveries"], 1)

    def test_each_builder_stage_verifies_only_its_own_contract_slice(self):
        contract = {
            "status": "ready",
            "goal": "Build a focus timer",
            "requirements": [
                "working timer controls",
                "configurable focus and break durations",
                "automatic phase switching and completed sessions",
                "persist settings in localStorage",
                "responsive keyboard-accessible UI",
                "reduced-motion support",
            ],
            "constraints": [],
            "success_criteria": ["all behavior verified"],
        }
        memory = mini.load_memory()
        observed = []

        def fake_stage(task_text, mem, messages=None, role="Builder", task_id="ROOT", extra_context=""):
            active = dict(mini.ACTIVE_TOOL_CONTRACT)
            profile = mini.infer_web_profile(active["goal"], active)
            observed.append({
                "requirements": active["requirements"],
                "checks": set(profile.required_interactions),
            })
            return {
                "status": "done", "summary": "done", "messages": [], "memory": mem,
                "tool_evidence": [{"tool": "run_command", "target": "test", "result": "[exit_code=0]"}],
                "provider_error": None,
            }

        with patch.object(mini, "execute_agent_task", side_effect=fake_stage):
            result = mini.execute_builder_stages(
                {"id": "ROOT", "goal": contract["goal"], "parent": None}, contract, memory,
            )

        self.assertEqual(result["status"], "done")
        self.assertEqual(len(observed), 6)
        self.assertNotIn("settings_persistence", observed[0]["checks"])
        self.assertNotIn("responsive_no_overflow", observed[0]["checks"])
        self.assertNotIn("timer_phase_switches_and_counts_session", observed[1]["checks"])
        self.assertNotIn("settings_persistence", observed[1]["checks"])
        self.assertNotIn("responsive_no_overflow", observed[1]["checks"])
        self.assertIn("timer_phase_switches_and_counts_session", observed[2]["checks"])
        self.assertNotIn("settings_persistence", observed[2]["checks"])
        self.assertNotIn("responsive_no_overflow", observed[2]["checks"])
        self.assertIn("settings_persistence", observed[3]["checks"])
        self.assertNotIn("timer_phase_switches_and_counts_session", observed[3]["checks"])
        self.assertNotIn("responsive_no_overflow", observed[3]["checks"])
        self.assertIn("keyboard_activation", observed[4]["checks"])
        self.assertIn("responsive_no_overflow", observed[4]["checks"])
        self.assertNotIn("reduced_motion", observed[4]["checks"])
        self.assertIn("reduced_motion", observed[5]["checks"])

    def test_only_evidence_gated_outcome_enters_retrievable_memory(self):
        contract = {"goal": "Build API", "requirements": ["health endpoint"]}
        task = {"id": "ROOT", "goal": "Build API"}

        mini.remember_verified_outcome(task, contract, "health endpoint passed tests", ["api.py"])
        context = mini.relevant_memory_context("API health endpoint", role="Builder")

        self.assertIn("Verified task completed", context)
        self.assertIn("api.py", context)


if __name__ == "__main__":
    unittest.main()
