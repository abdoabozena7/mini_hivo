import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import context_sufficiency as stage7


class ContextSufficiencyGateTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            "workspace": mini.WORKSPACE,
            "run": mini.RUN,
            "run_id": mini.RUN_ID,
            "active_contract": mini.ACTIVE_CONTRACT,
            "active_tool_contract": mini.ACTIVE_TOOL_CONTRACT,
            "active_gate": mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE,
            "active_world_model": mini.ACTIVE_PROJECT_WORLD_MODEL,
        }
        self._temp = tempfile.TemporaryDirectory()
        mini.WORKSPACE = Path(self._temp.name)
        mini.reset_run("context-gate-test")
        mini.ACTIVE_TOOL_CONTRACT = {"task_id": "gate-test", "goal": "preserve the task"}

    def tearDown(self):
        mini.WORKSPACE = self._saved["workspace"]
        mini.RUN = self._saved["run"]
        mini.RUN_ID = self._saved["run_id"]
        mini.ACTIVE_CONTRACT = self._saved["active_contract"]
        mini.ACTIVE_TOOL_CONTRACT = self._saved["active_tool_contract"]
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = self._saved["active_gate"]
        mini.ACTIVE_PROJECT_WORLD_MODEL = self._saved["active_world_model"]
        self._temp.cleanup()

    @staticmethod
    def _anchor():
        return {
            "root_goal": "Ship the token refresh fix without changing the public API",
            "parent_goal": "Repair token refresh behavior",
            "local_task": "Update refresh_token implementation",
            "requirements": ["callers continue to receive the declared token value"],
            "constraints": ["preserve the existing return contract"],
            "allowed_inspection_paths": ["src/auth.py", "tests/test_auth.py"],
        }

    @staticmethod
    def _tool_response(name, arguments):
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [{
                "function": {"name": name, "arguments": json.dumps(arguments)},
            }],
        }

    def test_sufficient_initial_packet_is_cheap_and_authorizes_mutation(self):
        provider_calls = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[{
                "kind": "contract", "source_identity": "src/auth.py:10",
                "excerpt": "refresh_token returns a string token.",
                "claim_key": "refresh_token.return", "claim_value": "string",
            }],
            evidence_provider=lambda request, context: provider_calls.append(request),
        )

        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "The contract and dependency evidence establish the return behavior.",
        })

        self.assertTrue(result["mutation_allowed"])
        self.assertEqual(result["lifecycle_state"], stage7.MUTATION_ALLOWED)
        self.assertEqual(provider_calls, [])

    def test_provider_schema_and_runtime_agree_on_evidence_request_kinds(self):
        parameters = next(
            tool["function"]["parameters"] for tool in mini.TOOLS
            if tool["function"]["name"] == "context_sufficiency_check"
        )
        kind_schema = parameters["properties"]["needed_evidence"]["items"]["properties"]["kind"]
        for kind in ("contract", "callers", "tests", "workspace", "file"):
            with self.subTest(kind=kind):
                advertised = "enum" not in kind_schema or kind in kind_schema["enum"]
                checked = stage7.validate_evidence_request({
                    "kind": kind, "target": "greet.py output contract",
                    "why": "Establish the expected greeting before implementing the CLI.",
                })
                self.assertEqual(advertised, checked["valid"])

    def test_completed_context_decision_is_not_worker_completion(self):
        responses = [
            self._tool_response("context_sufficiency_check", {
                "context_status": "sufficient",
                "reason": "The creation contract fully specifies the greeting.",
            }),
            {"role": "assistant", "content": "The context check is complete.", "tool_calls": []},
            self._tool_response("write_file", {
                "path": "greet.py", "content": 'print("Hello, World!")\n',
            }),
            self._tool_response("run_command", {"command": "python greet.py"}),
            {"role": "assistant", "content": "Greeting implemented and verified.", "tool_calls": []},
        ]
        mutations = []

        def run_tool(name, arguments, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(arguments, role=role, task_id="creation")
            if name == "write_file":
                mutations.append(arguments["path"])
                return "wrote file"
            return "[exit_code=0]\nHello, World!\n"

        mini.RUN["project_mode"] = mini.NEW_PROJECT
        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Create greet.py and verify its greeting.", {}, task_id="creation",
                context_sufficiency_enabled=True, max_steps=5,
            )
        self.assertEqual(mutations, ["greet.py"])
        self.assertEqual(result["status"], "done")
        self.assertTrue(any(item["tool"] == "run_command" for item in result["tool_evidence"]))

    def test_textual_context_call_requires_a_real_tool_invocation_before_mutation(self):
        prose_call = {
            "role": "assistant", "tool_calls": [],
            "content": "context_sufficiency_check(context_status='sufficient', needed_evidence=[])",
        }
        responses = [
            prose_call,
            self._tool_response("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "The creation contract is complete.",
            }),
            self._tool_response("write_file", {
                "path": "greet.py", "content": 'print("Hello, World!")\n',
            }),
            self._tool_response("run_command", {"command": "python greet.py"}),
            {"role": "assistant", "content": "Verified greeting.", "tool_calls": []},
        ]
        mutations = []

        def run_tool(name, arguments, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(arguments, role=role, task_id="native")
            if name == "write_file":
                self.assertEqual(mini.RUN["context_sufficiency_checks"], 1)
                mutations.append(arguments["path"])
                return "wrote file"
            return "[exit_code=0]\nHello, World!\n"

        with patch.object(mini, "ask_ollama", side_effect=responses) as ask, \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Create greet.py and verify its greeting.", {}, task_id="native",
                context_sufficiency_enabled=True, max_steps=5,
            )
        self.assertEqual(mutations, ["greet.py"])
        self.assertEqual(result["status"], "done")
        self.assertEqual(ask.call_count, 5)
        self.assertEqual(mini.RUN["context_sufficiency_checks"], 1)

    def test_textual_tool_call_repair_is_bounded_and_never_grants_authority(self):
        prose_call = {
            "role": "assistant", "tool_calls": [],
            "content": "context_sufficiency_check(context_status='sufficient')",
        }
        with patch.object(mini, "ask_ollama", side_effect=[prose_call, prose_call]) as ask:
            result = mini.execute_agent_task(
                "Create greet.py.", {}, task_id="native-invalid",
                context_sufficiency_enabled=True, max_steps=4,
            )
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["mutation_authorized"])
        self.assertEqual(mini.RUN["context_sufficiency_checks"], 0)
        self.assertIn("CONTEXT_SUFFICIENCY_REQUIRED", result["summary"])

    def test_explicit_new_outputs_need_creation_contracts_not_existing_definitions(self):
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        mini.RUN["source_requirement_ledger"] = mini.extract_source_requirement_ledger(
            "Create a greeting utility.\n"
            "- Create hello.py that prints MERGE_OK.\n"
            "- Create test_hello.py with unittest checks of the exact output.",
            use_model=False,
        )
        gate = stage7.ContextSufficiencyGate(
            {"root_goal": "Create a greeting utility.", "local_task": "Create hello.py."},
            evidence_provider=mini._provide_targeted_context_evidence,
        )
        result = gate.evaluate({
            "context_status": "insufficient",
            "reason": "The requested files do not exist yet.",
            "needed_evidence": [
                {"kind": "definition", "target": "hello.py",
                 "why": "Need the source definition before implementing the utility."},
                {"kind": "test_expectation", "target": "test_hello.py",
                 "why": "Need the requested test contract before implementing its checks."},
            ],
        })
        self.assertFalse(result["mutation_allowed"])
        self.assertTrue(result["evidence"])
        self.assertTrue(all(
            item["resolution_status"] == "not_applicable"
            for item in result["semantic_resolutions"]
        ))
        self.assertTrue(any(
            item.get("source_kind") == mini.USER_STATED for item in result["evidence"]
        ))
        self.assertTrue(any(
            item.get("source_kind") == "DIRECT_OBSERVATION" for item in result["evidence"]
        ))
        authorized = gate.evaluate({
            "context_status": "sufficient",
            "reason": "The user specifies new outputs, not missing pre-existing dependencies.",
        })
        self.assertTrue(authorized["mutation_allowed"])
        self.assertFalse((mini.WORKSPACE / "hello.py").exists())

    def test_missing_dependency_cannot_be_exempted_without_source_creation_authority(self):
        mini.RUN["project_mode"] = mini.NEW_PROJECT
        mini.RUN["source_requirement_ledger"] = mini.extract_source_requirement_ledger(
            "Create a utility.\n- Create hello.py using an external_api.py dependency.",
            use_model=False,
        )
        gate = stage7.ContextSufficiencyGate(
            {"local_task": "Create hello.py."},
            evidence_provider=mini._provide_targeted_context_evidence,
        )
        result = gate.evaluate({
            "context_status": "insufficient", "reason": "The external dependency is absent.",
            "needed_evidence": [{
                "kind": "definition", "target": "external_api.py",
                "why": "Need the actual external dependency interface before implementing its caller.",
            }],
        })
        self.assertEqual(result["semantic_resolutions"][0]["resolution_status"], "unresolved")
        self.assertFalse(gate.evaluate({
            "context_status": "sufficient", "reason": "Assume the dependency is available.",
        })["mutation_allowed"])

    def test_unproven_not_applicable_provider_claim_does_not_authorize_mutation(self):
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            evidence_provider=lambda *_args: {
                "resolution_status": "not_applicable", "facts_established": [],
                "evidence": [],
            },
        )
        gate.evaluate({
            "context_status": "insufficient", "reason": "The external contract is missing.",
            "needed_evidence": [{
                "kind": "contract", "target": "external_api",
                "why": "Need the actual interface before changing the implementation.",
            }],
        })
        result = gate.evaluate({"context_status": "sufficient", "reason": "Assume it is safe."})
        self.assertFalse(result["mutation_allowed"])

    def test_missing_contract_is_completed_before_mutation(self):
        requests = []
        mutation_calls = []
        responses = [
            self._tool_response("context_sufficiency_check", {
                "context_status": "insufficient",
                "reason": "The public return contract is absent from the initial packet.",
                "needed_evidence": [{
                    "kind": "contract", "target": "refresh_token return value",
                    "why": "Need the public contract to avoid changing callers' expected return type.",
                }],
            }),
            self._tool_response("context_sufficiency_check", {
                "context_status": "sufficient",
                "reason": "The returned contract resolves the implementation's return type.",
            }),
            self._tool_response("edit_file", {
                "path": "src/auth.py", "old": "old", "new": "new",
            }),
            self._tool_response("run_command", {"command": "python -m unittest"}),
            {"role": "assistant", "content": "completed", "tool_calls": []},
        ]

        def provider(request, _context):
            requests.append(request)
            return [{
                "kind": "contract", "target": request["target"],
                "source_identity": "src/auth.py:10",
                "excerpt": "refresh_token returns a string token.",
                "purpose": request["why"],
                "claim_key": "refresh_token.return", "claim_value": "string",
                "authoritative": True,
            }]

        def run_tool(name, arguments, role="Builder"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(arguments, role=role, task_id="contract")
            if name == "edit_file":
                mutation_calls.append((name, arguments))
            return "ok"

        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Update refresh_token implementation", {}, role="Builder", task_id="contract",
                extra_context="INITIAL BOUNDED PACKET: implementation only",
                context_sufficiency_enabled=True,
                context_anchor=self._anchor(),
                context_evidence_provider=provider,
                max_steps=5,
            )

        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0]["kind"], "contract")
        self.assertTrue(mutation_calls)
        self.assertTrue(result["mutation_authorized"])
        self.assertEqual(result["context_sufficiency"]["anchor"]["root_goal"], self._anchor()["root_goal"])

    def test_missing_caller_expectation_requests_narrow_reasoned_evidence(self):
        calls = []
        gate = stage7.ContextSufficiencyGate(self._anchor(), evidence_provider=lambda request, context: calls.append(request) or [])
        result = gate.evaluate({
            "context_status": "insufficient",
            "reason": "The implementation is present but caller expectations are not shown.",
            "needed_evidence": [{
                "kind": "callers", "target": "refresh_token consumers",
                "why": "Need to verify whether callers consume a string token or a structured refresh result.",
            }],
        })

        self.assertEqual(calls[0]["kind"], "callers")
        self.assertEqual(calls[0]["target"], "refresh_token consumers")
        self.assertIn("callers", calls[0]["why"])
        self.assertLessEqual(result["working_evidence_chars"], stage7.MAX_CONTEXT_EVIDENCE_CHARS)

    def test_completion_evidence_reaches_worker_after_a_full_initial_packet(self):
        fact = "AUTHORITATIVE_RETURN_CONTRACT: refresh_token returns a string token."
        seen = []
        responses = [
            self._tool_response("context_sufficiency_check", {
                "context_status": "insufficient", "reason": "The return contract is missing.",
                "needed_evidence": [{
                    "kind": "contract", "target": "refresh_token",
                    "why": "Need the return shape to preserve the public API.",
                }],
            }),
            self._tool_response("context_sufficiency_check", {
                "context_status": "sufficient", "reason": "The returned contract resolves the type.",
            }),
            {"role": "assistant", "content": "Blocked for this test.", "tool_calls": []},
        ]

        def ask(messages, **_kwargs):
            seen.append(mini.compact_messages(
                messages, max_chars=int(mini.MODEL_POLICY.context_window("Builder") * 1.5),
                keep_recent=4,
            ))
            return responses[len(seen) - 1]

        with patch.object(mini, "ask_ollama", side_effect=ask):
            mini.execute_agent_task(
                "Update refresh_token.", {}, task_id="full-packet",
                extra_context="ROOT_AUTHORITY: preserve the public API.\n" + "bounded context " * 300,
                context_anchor=self._anchor(), context_sufficiency_enabled=True,
                context_evidence_provider=lambda *_args: [{
                    "kind": "contract", "source_identity": "api.pyi:4", "excerpt": fact,
                }],
                max_steps=3,
            )
        self.assertIn(fact, json.dumps(seen[1]))
        self.assertIn("ROOT_AUTHORITY: preserve the public API.", json.dumps(seen[1]))

    def test_runtime_tool_contract_is_resolved_without_repository_search_or_execution(self):
        gate = stage7.ContextSufficiencyGate(
            self._anchor(), evidence_provider=mini._provide_targeted_context_evidence,
        )
        with patch.object(mini.stage7_semantic, "resolve_targeted_evidence") as resolve, \
                patch.object(mini, "run_tool") as execute:
            result = gate.evaluate({
                "context_status": "insufficient",
                "reason": "The verification tool's argument contract is missing.",
                "needed_evidence": [{
                    "kind": "authoritative_contract", "target": "run_command",
                    "why": "Need the real tool arguments before running the verification command.",
                }],
            })
        resolve.assert_not_called()
        execute.assert_not_called()
        self.assertEqual(result["semantic_resolutions"][0]["resolution_status"], "resolved")
        self.assertIn('"command"', result["evidence"][0]["excerpt"])
        self.assertEqual(result["evidence"][0]["source_kind"], "RUNTIME_TOOL_CONTRACT")
        self.assertFalse(result["mutation_allowed"])
        self.assertTrue(gate.evaluate({
            "context_status": "sufficient", "reason": "The runtime tool contract is now available.",
        })["mutation_allowed"])

    def test_unbound_creation_repair_can_inspect_its_source_declared_files(self):
        mini.RUN["source_requirement_ledger"] = mini.extract_source_requirement_ledger(
            "Create a module.\n- Create values.py with the required conversion.\n",
            use_model=False,
        )
        (mini.WORKSPACE / "values.py").write_text("def convert(value):\n    return value\n", encoding="utf-8")
        (mini.WORKSPACE / "unrelated.py").write_text("unrelated = True\n", encoding="utf-8")
        gate = mini._context_gate_for_execution("Repair values.py.", "repair", enabled=True)
        self.assertIn("values.py", gate.anchor["allowed_inspection_paths"])
        self.assertNotIn("unrelated.py", gate.anchor["allowed_inspection_paths"])
        result = gate.evaluate({
            "context_status": "insufficient", "reason": "The current implementation is needed.",
            "needed_evidence": [{
                "kind": "definition", "target": "values.py",
                "why": "Need the actual current source before making a focused correction.",
            }],
        })
        self.assertEqual(result["semantic_resolutions"][0]["resolution_status"], "resolved")
        self.assertIn("def convert", result["evidence"][0]["excerpt"])
        protected = mini._context_gate_for_execution(
            "Repair values.py.", "approved", enabled=True,
            execution_contract={"allowed_inspection_paths": [], "allowed_mutation_paths": ["values.py"]},
        )
        self.assertEqual(protected.anchor["allowed_inspection_paths"], [])

    def test_source_contract_and_line_qualified_expectations_are_not_missing_repository_facts(self):
        mini.RUN["source_requirement_ledger"] = mini.extract_source_requirement_ledger(
            "Create a display utility.\n"
            "- Running python display.py Guest prints exactly Welcome! followed by a newline.\n"
            '- Expose a display(name="Guest") function that returns the same output without a newline.',
            use_model=False,
        )
        for kind, target in (
            ("authoritative_contract", "ROOT CONTRACT"),
            ("contract", "display.py"), ("tests", "display.py:16"),
        ):
            with self.subTest(kind=kind, target=target):
                result = mini._provide_targeted_context_evidence({
                    "kind": kind, "target": target,
                    "why": "Need the source-authorized expected behavior before correcting the implementation.",
                }, {})
                self.assertEqual(result["resolution_status"], "resolved")
                self.assertIn("Welcome!", json.dumps(result["evidence"]))
                self.assertTrue(all(
                    item["source_kind"] == "SOURCE_REQUIREMENT_LEDGER"
                    and "does not claim" in item["purpose"]
                    for item in result["evidence"]
                ))

    def test_terminal_context_failure_stops_without_consuming_the_worker_budget(self):
        decision = self._tool_response("context_sufficiency_check", {
            "context_status": "insufficient", "reason": "The external contract is missing.",
            "needed_evidence": [{
                "kind": "contract", "target": "external_api",
                "why": "Need the actual external interface before editing its caller.",
            }],
        })
        with patch.object(mini, "ask_ollama", return_value=decision) as ask:
            result = mini.execute_agent_task(
                "Update the external API caller.", {}, task_id="bounded-failure",
                context_sufficiency_enabled=True, context_evidence_provider=lambda *_args: None,
                max_steps=mini.MAX_TOOL_STEPS,
            )
        self.assertEqual(ask.call_count, stage7.MAX_CONTEXT_COMPLETION_ROUNDS + 1)
        self.assertFalse(result["mutation_authorized"])
        self.assertEqual(result["failure_type"], mini.CONTEXT_INSUFFICIENT_FAILURE)

    def test_returned_evidence_requires_a_structured_decision_not_prose_completion(self):
        seen = []
        answers = [
            self._tool_response("context_sufficiency_check", {
                "context_status": "insufficient", "reason": "The current contract is missing.",
                "needed_evidence": [{
                    "kind": "contract", "target": "refresh_token",
                    "why": "Need the return contract before repairing the implementation.",
                }],
            }),
            {"role": "assistant", "content": "I can now repair it.", "tool_calls": []},
            {"role": "assistant", "content": '{"context_status":"sufficient","reason":"The evidence resolves the return contract."}'},
            self._tool_response("run_command", {"command": "python -m unittest"}),
            {"role": "assistant", "content": "verified", "tool_calls": []},
        ]

        def ask(_messages, **kwargs):
            seen.append(kwargs)
            return answers[len(seen) - 1]

        def tool(name, arguments, role="Repairer"):
            if name == "context_sufficiency_check":
                return mini._context_sufficiency_tool(arguments, role=role, task_id="repair")
            return "[exit_code=0]\nOK"

        with patch.object(mini, "ask_ollama", side_effect=ask), \
                patch.object(mini, "run_tool", side_effect=tool):
            result = mini.execute_agent_task(
                "Repair the focused return behavior.", {}, role="Repairer", task_id="repair",
                context_sufficiency_enabled=True, context_anchor=self._anchor(), max_steps=5,
                context_evidence_provider=lambda *_args: [{
                    "kind": "contract", "source_identity": "api.pyi:4",
                    "excerpt": "refresh_token returns a string token.",
                }],
            )
        self.assertIsNone(seen[2]["tools"])
        self.assertEqual(seen[2]["response_format"], stage7.context_sufficiency_schema())
        self.assertTrue(result["mutation_authorized"])
        self.assertEqual(result["status"], "done")

    def test_goal_anchor_survives_completion(self):
        anchor = self._anchor()
        gate = stage7.ContextSufficiencyGate(
            anchor,
            evidence_provider=lambda request, context: [{
                "kind": request["kind"], "target": request["target"],
                "source_identity": "src/auth.py:20", "excerpt": "caller uses token",
            }],
        )
        before = gate.snapshot()
        gate.evaluate({
            "context_status": "insufficient",
            "reason": "Need the caller contract before changing the implementation.",
            "needed_evidence": [{
                "kind": "callers", "target": "refresh_token caller",
                "why": "Need the caller's expected value shape before editing the return path.",
            }],
        })
        after = gate.snapshot()

        self.assertEqual(after["anchor"], before["anchor"])
        self.assertEqual(after["anchor_hash"], before["anchor_hash"])
        self.assertEqual(after["anchor"]["local_task"], "Update refresh_token implementation")
        self.assertNotEqual(after["working_evidence"], before["working_evidence"])

    def test_completion_budget_is_bounded_and_fails_closed(self):
        calls = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            evidence_provider=lambda request, context: calls.append(request) or [],
        )
        decision = {
            "context_status": "insufficient",
            "reason": "The required contract remains unresolved.",
            "needed_evidence": [{
                "kind": "contract", "target": "refresh_token contract",
                "why": "Need the return contract to resolve the mutation safely.",
            }],
        }
        result = None
        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS + 1):
            result = gate.evaluate(decision)

        self.assertEqual(len(calls), stage7.MAX_CONTEXT_COMPLETION_ROUNDS)
        self.assertTrue(result["final"])
        self.assertEqual(result["failure_code"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_allowed"])

    def test_contradictory_evidence_requires_authoritative_resolution(self):
        requests = []
        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[
                {"kind": "caller", "source_identity": "src/a.py:1", "excerpt": "expects string", "claim_key": "refresh.return", "claim_value": "string"},
                {"kind": "test", "source_identity": "tests/test_a.py:1", "excerpt": "expects object", "claim_key": "refresh.return", "claim_value": "object"},
            ],
            evidence_provider=lambda request, context: requests.append(request) or [],
        )
        result = gate.evaluate({
            "context_status": "sufficient",
            "reason": "There is enough text to edit.",
        })

        self.assertFalse(result["mutation_allowed"])
        self.assertEqual(requests[0]["kind"], "authoritative_contract")
        self.assertIn("conflict", result["reason"])

        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS):
            result = gate.evaluate({
                "context_status": "sufficient",
                "reason": "The contradiction remains unresolved.",
            })
        self.assertEqual(result["failure_code"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_allowed"])

    def test_runtime_rejects_mutation_attempt_before_gate(self):
        mutation_calls = []
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = stage7.ContextSufficiencyGate(self._anchor())
        direct_block = mini.run_tool(
            "edit_file", {"path": "src/auth.py", "old": "old", "new": "new"}, role="Builder",
        )
        self.assertIn("CONTEXT_SUFFICIENCY_REQUIRED", direct_block)
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = None
        responses = [
            self._tool_response("edit_file", {
                "path": "src/auth.py", "old": "old", "new": "new",
            }),
            {"role": "assistant", "content": "I have enough context", "tool_calls": []},
        ]

        def run_tool(name, arguments, role="Builder"):
            if name in {"edit_file", "write_file", "edit_file_range"}:
                mutation_calls.append(name)
            return "unexpected tool execution"

        with patch.object(mini, "ask_ollama", side_effect=responses), \
                patch.object(mini, "run_tool", side_effect=run_tool):
            result = mini.execute_agent_task(
                "Change the implementation", {}, role="Builder", task_id="blocked",
                context_sufficiency_enabled=True, context_anchor=self._anchor(), max_steps=2,
            )

        self.assertEqual(mutation_calls, [])
        self.assertEqual(result["failure_type"], stage7.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertFalse(result["mutation_authorized"])

    def test_evidence_completion_replaces_slots_and_stays_bounded(self):
        counter = {"round": 0}

        def provider(request, context):
            counter["round"] += 1
            return [{
                "kind": request["kind"], "target": request["target"],
                "source_identity": f"src/{counter['round']}.py:1",
                "excerpt": "semantic evidence " * 20,
            } for _ in range(stage7.MAX_EVIDENCE_REQUESTS_PER_ROUND)]

        gate = stage7.ContextSufficiencyGate(
            self._anchor(),
            initial_evidence=[{
                "kind": "initial", "source_identity": f"src/initial-{i}.py",
                "excerpt": "initial fact " * 10,
            } for i in range(stage7.MAX_CONTEXT_EVIDENCE_ITEMS)],
            evidence_provider=provider,
        )
        decision = {
            "context_status": "insufficient",
            "reason": "Need the semantic dependency before the edit.",
            "needed_evidence": [{
                "kind": "definition", "target": "refresh_token return type",
                "why": "Need the type definition to preserve interface compatibility.",
            }],
        }
        for _ in range(stage7.MAX_CONTEXT_COMPLETION_ROUNDS):
            gate.evaluate(decision)
        snapshot = gate.snapshot()

        self.assertLessEqual(snapshot["working_evidence_count"], stage7.MAX_CONTEXT_EVIDENCE_ITEMS)
        self.assertLessEqual(snapshot["working_evidence_chars"], stage7.MAX_CONTEXT_EVIDENCE_CHARS)
        self.assertLessEqual(len(snapshot["history"]), stage7.MAX_CONTEXT_COMPLETION_ROUNDS + 1)
        self.assertEqual(snapshot["anchor_hash"], stage7.canonical_hash(snapshot["anchor"]))

    def test_gate_disabled_preserves_existing_worker_tool_projection(self):
        responses = [{"role": "assistant", "content": "done", "tool_calls": []}]
        seen = []

        def ask(messages, tools=None, **_kwargs):
            seen.append({item["function"]["name"] for item in tools or []})
            return responses[0]

        with patch.object(mini, "ask_ollama", side_effect=ask):
            result = mini.execute_agent_task(
                "Inspect the current implementation", {}, role="Builder", task_id="legacy",
                max_steps=1,
            )

        self.assertEqual(result["status"], "failed")
        self.assertIsNone(result["context_sufficiency"])
        self.assertIn("write_file", seen[0])


if __name__ == "__main__":
    unittest.main()
