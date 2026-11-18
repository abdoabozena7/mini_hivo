"""Level 1 regression: real controller/filesystem, scripted provider decisions."""
import hashlib
import json
import unittest
from unittest.mock import patch

import mini
import test_greenfield_impact_lifecycle as lifecycle
from hivo import pre_mutation_impact as impact


class Level1NativeVerificationTests(unittest.TestCase):
    setUp = lifecycle.GreenfieldImpactLifecycleTests.setUp
    call = staticmethod(lifecycle.GreenfieldImpactLifecycleTests.call)
    execute = lifecycle.GreenfieldImpactLifecycleTests.execute

    def prepare_level1(self):
        self.goal = 'Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo'
        self.contract = mini.get_goal_contract(self.goal, interactive=False)
        mini.RUN['source_contract'] = self.contract
        mini.ACTIVE_CONTRACT = self.contract
        mini.ACTIVE_TOOL_CONTRACT = self.contract
        self.task = mini.root_task_from_contract(self.contract)

    def replies(self, content='Hello Mini Hivo', rejected=('cat', 'echo')):
        return [self.call('context_sufficiency_check', context_status='sufficient',
                          reason='The source defines a single exact text artifact.'),
                self.call('write_file', path='test_level_1.txt', content=content),
                *[self.call('run_command', command=f'{cmd} test_level_1.txt') for cmd in rejected],
                self.call('run_file', path='test_level_1.txt'),
                {'role': 'assistant', 'content': 'Native readback completed.', 'tool_calls': []}]

    def test_colon_literal_variants_preserve_exact_multiword_bytes(self):
        for suffix in ['exactly:Hello Mini Hivo', 'exactly: Hello Mini Hivo',
                       'exactly: "Hello Mini Hivo"', 'exactly the text "Hello Mini Hivo".']:
            with self.subTest(suffix=suffix):
                self.assertEqual(mini.literal_file_request(
                    'Create a text file named test_level_1.txt containing ' + suffix),
                    {'name': 'test_level_1.txt', 'content': 'Hello Mini Hivo', 'kind': 'text'})
        self.assertEqual(mini.literal_file_request(
            'Create a text file named message.txt containing exactly: Hello world!')['content'],
            'Hello world!')

    def test_compound_or_multiline_source_does_not_gain_literal_scope(self):
        for suffix in ['Hello Mini Hivo. Also change another file.',
                       'Hello Mini Hivo\nAlso change another file.', '"Hello" Also change another file.']:
            with self.subTest(suffix=suffix):
                self.assertIsNone(mini.literal_file_request(
                    'Create a text file named test_level_1.txt containing exactly:' + suffix))

    def test_source_compiles_to_native_route_authority(self):
        self.prepare_level1()
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        self.assertTrue(candidate['scope_required'])
        self.assertEqual(candidate['authorized_mutation_paths'], ['test_level_1.txt'])
        self.assertEqual(candidate['expected_targets'][0]['post_state_sha256'],
                         hashlib.sha256(b'Hello Mini Hivo').hexdigest())
        self.assertEqual(len(candidate['source_requirements']), 3)
        self.assertEqual(len(candidate['verification_obligations']), 3)

    def test_repeated_rejected_commands_recover_through_real_leaf_and_falsifier(self):
        self.prepare_level1()
        replies = self.replies() + [self.call('run_file', path='test_level_1.txt'),
                  {'role': 'assistant', 'content': 'Falsifier read actual bytes.', 'tool_calls': []}]
        observations = []
        original_gate = mini.evidence_gate

        def provider(messages, **kwargs):
            observations.append((json.dumps(messages),
                                 {t['function']['name'] for t in kwargs.get('tools', [])}))
            return replies.pop(0)

        def check_gate(*args, **kwargs):
            gate = original_gate(*args, **kwargs)
            self.assertTrue(gate['passed'], gate)
            self.assertTrue(any(row['kind'] == 'LITERAL_ARTIFACT'
                                for row in gate['verification_aggregation']['actual_passes']))
            return gate

        with patch.object(mini, 'ask_ollama', side_effect=provider) as ask, \
             patch.object(mini, 'evidence_gate', side_effect=check_gate), \
             patch.object(mini.subprocess, 'run', side_effect=AssertionError('no shell execution')):
            result, _ = mini.run_baseline_request(self.goal, {}, contract_override=self.contract,
                                                repo_snapshot={'files': []}, finish=False)
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual((self.root / 'test_level_1.txt').read_bytes(), b'Hello Mini Hivo')
        self.assertTrue(any('run_file' in transcript and 'command refused' in transcript
                            for transcript, _ in observations))
        self.assertTrue(any('run_command' not in tools and 'run_file' in tools
                            for _, tools in observations[3:]))
        self.assertIn("Falsifier", [call.kwargs["role"] for call in ask.call_args_list])
        self.assertEqual(mini.RUN['impact_contract_authorizations'], 1)

    def test_ignoring_native_guidance_stops_before_budget_exhaustion(self):
        self.prepare_level1()
        replies = self.replies(rejected=('cat', 'cat', 'cat'))
        with patch.object(mini, 'ask_ollama', side_effect=replies) as provider:
            candidate = mini._prepare_task_impact_contract(self.task, self.contract)
            mini.begin_transaction('ROOT')
            result = mini.execute_agent_task(self.goal, {}, context_sufficiency_enabled=True,
                context_anchor={'root_goal': self.goal, 'local_task': self.goal},
                impact_contract=candidate, impact_contract_required=True, max_steps=12)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('LITERAL_VERIFICATION_RETRY_EXHAUSTED', result['summary'])
        self.assertLess(provider.call_count, 12)

    def test_wrong_bytes_still_fail_independent_post_state(self):
        self.prepare_level1()
        result = self.execute(self.replies(content='wrong'))
        comparison = mini._impact_post_mutation_check(result['impact_contract'],
                                                     verification_result={'passed': True})
        self.assertFalse(comparison['passed'])

    def test_shell_security_is_unchanged(self):
        self.prepare_level1()
        with patch.object(mini.subprocess, 'run', side_effect=AssertionError('no shell execution')):
            for command in ['cat test_level_1.txt', 'echo test_level_1.txt',
                            'ls -l test_level_1.txt', 'type test_level_1.txt',
                            'python -c "print(1)"', 'git status && git clean -fd']:
                with self.subTest(command=command):
                    self.assertTrue(mini.run_command(command).startswith('error: command refused:'))
        self.assertIsNone(mini._validated_command_parts('git status')[1])

    def test_unaccepted_or_tampered_authority_cannot_offer_literal_guidance(self):
        self.prepare_level1()
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        for contract in [candidate, dict(candidate, contract_hash='forged')]:
            mini.ACTIVE_IMPACT_CONTRACT = contract
            hint = mini.tool_recovery_hint('run_command', 'error: command refused: executable cat', 1)
            self.assertNotIn('test_level_1.txt', hint)

    def test_literal_and_refusal_evidence_do_not_invent_executable_tests(self):
        from hivo.verification_routing import _is_focused_test_evidence
        for item in [
            {'tool': 'run_command', 'target': 'cat test_level_1.txt',
             'result': "error: command refused: executable 'cat' is not in the verification allowlist"},
            {'tool': 'run_file', 'target': 'test_level_1.txt',
             'result': json.dumps({'verification_kind': 'LITERAL_ARTIFACT', 'passed': True})},
        ]:
            self.assertFalse(_is_focused_test_evidence(item))
        self.assertTrue(_is_focused_test_evidence(
            {'tool': 'run_command', 'target': 'python -m unittest', 'result': '[exit_code=0]\nOK'}))

    def test_native_literal_proof_still_rejects_wrong_bytes(self):
        self.prepare_level1()
        result = self.execute(self.replies(content='wrong', rejected=()))
        proof = next(json.loads(e['result']) for e in result['tool_evidence'] if e['tool'] == 'run_file')
        self.assertEqual(proof['status'], 'FAIL')
        self.assertFalse(proof['passed'])
        self.assertNotEqual(proof['actual_sha256'], proof['expected_sha256'])

    def test_controller_rechecks_literal_bytes_without_trusting_model_verification_choices(self):
        self.prepare_level1()
        result = self.execute(self.replies(rejected=()))
        self.task["impact_contract"] = result["impact_contract"]
        mini.ACTIVE_TOOL_CONTRACT["impact_contract"] = result["impact_contract"]
        for content, expected in (("Hello Mini Hivo", True), ("wrong", False)):
            (self.root / "test_level_1.txt").write_text(content, encoding="utf-8")
            evidence = mini._source_acceptance_evidence(self.task)
            self.assertTrue(evidence)
            self.assertIs(json.loads(evidence[0]["result"])["passed"], expected)
        (self.root / "test_level_1.txt").unlink()
        missing = json.loads(mini._source_acceptance_evidence(self.task)[0]["result"])
        self.assertFalse(missing["passed"])
        self.assertEqual(missing["verification_kind"], "LITERAL_ARTIFACT")
        self.assertIn("does not exist", missing["error"])

    def run_closed_literal_leaf(self, supplied_text, extra_criterion=None):
        self.goal = 'Create proof.txt containing exactly:"Ready for review."\n'
        self.contract = mini.get_goal_contract(self.goal, interactive=False)
        if extra_criterion:
            self.contract["success_criteria"] = [*self.contract["success_criteria"], extra_criterion]
        builder_replies = iter([
            self.call("context_sufficiency_check", context_status="sufficient",
                      reason="The source explicitly supplies the file and exact content."),
            self.call("write_file", path="proof.txt", content=supplied_text),
            {"role": "assistant", "content": "Created the file.", "tool_calls": []},
        ])
        falsifier_replies = iter([
            self.call("read_file", path="proof.txt"),
            {"role": "assistant", "content": "Read the file.", "tool_calls": []},
        ])

        def provider(_messages, *, role, **_kwargs):
            if role == "Repairer":
                self.assertEqual((self.root / "proof.txt").read_bytes(), supplied_text.encode("utf-8"))
                return {"role": "assistant", "content": "Cannot complete the repair.", "tool_calls": []}
            return next({"Builder": builder_replies, "Falsifier": falsifier_replies}[role])

        with patch.object(mini, "ask_ollama", side_effect=provider) as ask:
            result, _ = mini.run_baseline_request(self.goal, {}, contract_override=self.contract,
                                                repo_snapshot={"files": []}, finish=False)
        return result, [call.kwargs["role"] for call in ask.call_args_list]

    def test_closed_literal_uses_real_readback_without_a_model_falsifier(self):
        result, roles = self.run_closed_literal_leaf("Ready for review.")
        self.assertEqual(result["status"], "done", result)
        self.assertEqual((self.root / "proof.txt").read_bytes(), b"Ready for review.")
        self.assertTrue(roles)
        self.assertNotIn("Falsifier", roles)
        self.assertTrue(any(
            item["tool"] == "run_file" and json.loads(item["result"]).get("passed")
            for item in result["falsifier"]["tool_evidence"]
        ))
        self.assertTrue(result["impact_comparison"]["passed"])

    def test_wrong_closed_literal_does_not_get_verified_or_persist(self):
        result, roles = self.run_closed_literal_leaf("Ready for review")
        self.assertEqual(result["status"], "failed", result)
        self.assertFalse(mini.RUN["root_verified"])
        self.assertIn("Repairer", roles)
        self.assertNotIn("Falsifier", roles)
        self.assertFalse((self.root / "proof.txt").exists())

    def test_extra_success_criterion_keeps_model_falsification(self):
        result, roles = self.run_closed_literal_leaf("Ready for review.", "Check the response requirements.")
        self.assertEqual(result["status"], "done", result)
        self.assertIn("Falsifier", roles)


if __name__ == '__main__':
    unittest.main()
