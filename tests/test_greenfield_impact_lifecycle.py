"""Real mutation/verification gates, with only model responses scripted."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini
from hivo import pre_mutation_impact as impact


class GreenfieldImpactLifecycleTests(unittest.TestCase):
    def setUp(self):
        names = ('WORKSPACE', 'RUN', 'RUN_ID', 'TASKS', 'ACTIVE_CONTRACT',
                 'ACTIVE_TOOL_CONTRACT', 'ACTIVE_CONTEXT_SUFFICIENCY_GATE',
                 'ACTIVE_PROJECT_WORLD_MODEL', 'ACTIVE_IMPACT_CONTRACT',
                 'ACTIVE_IMPACT_REQUIRED', 'ACTIVE_TRANSACTION', 'LAST_COMMITTED_TRANSACTION')
        saved = {name: getattr(mini, name) for name in names}
        self.addCleanup(lambda: [setattr(mini, name, value) for name, value in saved.items()])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mini.WORKSPACE = self.root
        mini.ACTIVE_PROJECT_WORLD_MODEL = None
        mini.ACTIVE_TOOL_CONTRACT = None
        mini.ACTIVE_TRANSACTION = None
        mini.ACTIVE_IMPACT_CONTRACT = None
        mini.reset_run('baseline')
        mini.RUN['project_mode'] = mini.NEW_PROJECT
        provider = patch.object(mini, 'structured_model_call', side_effect=mini.StructuredOutputError('offline regression'))
        provider.start()
        self.addCleanup(provider.stop)
        self.goal = 'Create a text file named welcone containing exactly welcome.'
        self.contract = mini.get_goal_contract(self.goal, interactive=False)
        mini.RUN['source_contract'] = self.contract
        mini.ACTIVE_CONTRACT = self.contract
        mini.ACTIVE_TOOL_CONTRACT = self.contract
        self.task = mini.root_task_from_contract(self.contract)

    @staticmethod
    def call(name, **args):
        return {'role': 'assistant', 'content': '', 'tool_calls': [
            {'function': {'name': name, 'arguments': args}}]}

    def responses(self, content='welcome', initial_idle=False):
        messages = ([{'role': 'assistant', 'content': 'done', 'tool_calls': []}]
                    if initial_idle else [])
        messages += [self.call('context_sufficiency_check', context_status='sufficient',
                               reason='The exact source filename, text type, content, and empty workspace are supplied.'),
                     self.call('write_file', path='welcone.txt', content=content),
                     self.call('run_file', path='welcone.txt'),
                     {'role': 'assistant', 'content': 'Verified exact bytes.', 'tool_calls': []}]
        return messages

    def execute(self, responses):
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        mini.begin_transaction('ROOT')
        with patch.object(mini, 'ask_ollama', side_effect=responses):
            result = mini.execute_agent_task(
                self.goal, {}, context_sufficiency_enabled=True,
                context_anchor={'root_goal': self.goal, 'local_task': self.goal,
                                'requirements': self.contract['requirements']},
                impact_contract=candidate, impact_contract_required=True,
                max_steps=8,
            )
        return result

    def test_a_simple_greenfield_file_verified_through_leaf(self):
        original_gate = mini.evidence_gate
        def check_gate(*args, **kwargs):
            gate = original_gate(*args, **kwargs)
            self.assertTrue(gate['passed'], gate)
            self.assertTrue(any(row['kind'] == 'LITERAL_ARTIFACT'
                                for row in gate['verification_aggregation']['actual_passes']))
            return gate
        replies = self.responses(initial_idle=True) + [self.call('run_file', path='welcone.txt'),
                  {'role': 'assistant', 'content': 'Falsifier exact-byte check passed.', 'tool_calls': []}]
        with patch.object(mini, 'ask_ollama', side_effect=replies), \
             patch.object(mini, 'evidence_gate', side_effect=check_gate):
            result, _ = mini.run_baseline_request(self.goal, {}, contract_override=self.contract,
                                                repo_snapshot={'files': []}, finish=False)
        self.assertEqual(result['status'], 'done', result)
        self.assertEqual((self.root / 'welcone.txt').read_bytes(), b'welcome')

    def test_b_lifecycle_precedes_mutation(self):
        original = mini.write_file
        observed = []
        def guarded_write(*args, **kwargs):
            observed.append((mini.RUN['impact_contracts_created'], mini.RUN['impact_contracts_validated'],
                             mini.RUN['impact_contract_authorizations']))
            self.assertIsNone(impact.impact_mutation_block_reason(mini.ACTIVE_IMPACT_CONTRACT))
            return original(*args, **kwargs)
        with patch.object(mini, 'write_file', side_effect=guarded_write):
            result = self.execute(self.responses())
        self.assertEqual(observed, [(1, 1, 1)])
        self.assertTrue(result['impact_authorized'])

    def test_c_missing_invalid_rejected_and_out_of_scope_cannot_write(self):
        result = self.execute(self.responses())
        accepted = copy.deepcopy(result['impact_contract'])
        gate = mini.ContextSufficiencyGate if hasattr(mini, 'ContextSufficiencyGate') else mini.stage7_context.ContextSufficiencyGate
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = gate({'root_goal': self.goal, 'local_task': self.goal})
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE.evaluate({'context_status': 'sufficient', 'reason': 'Source contract supplies the complete literal artifact.'})
        for label, contract in [('missing', None), ('unaccepted', self.task['impact_contract_candidate']),
                                ('tampered', dict(accepted, contract_hash='forged')), ('out_of_scope', accepted)]:
            with self.subTest(label=label):
                mini.ACTIVE_IMPACT_REQUIRED = True
                mini.ACTIVE_IMPACT_CONTRACT = contract
                reply = mini.run_tool('write_file', {'path': 'foreign.txt', 'content': 'forbidden'}, role='Builder')
                self.assertIn('error:', reply)
                self.assertFalse((self.root / 'foreign.txt').exists())

    def test_d_requirement_ids_trace_to_source_brain_impact_and_worker(self):
        ids = ['REQ-001', 'REQ-002', 'REQ-003']
        self.assertEqual([r['requirement_id'] for r in mini.ledger_requirements(self.contract['source_requirement_ledger'])], ids)
        understanding = mini.prepare_stage2_context(self.goal, self.contract, {'files': []},
                                                    interactive=False, supplied_contract=True)
        self.assertEqual(understanding['task_brain']['source_requirement_ids'], ids)
        result = self.execute(self.responses())
        self.assertEqual([r['requirement_id'] for r in result['impact_contract']['source_requirements']], ids)
        self.assertEqual([r['id'] for r in result['impact_contract']['verification_obligations']], ids)
        projection = impact.project_impact_contract(result['impact_contract'])
        self.assertEqual([r['id'] for r in projection['verification_obligations']], ids)
        for requirement_id in ids:
            self.assertIn(requirement_id, projection['rendered'])

    def test_e_existing_project_still_requires_plan_approval(self):
        mini.RUN['project_mode'] = mini.EXISTING_PROJECT
        mini.RUN['impact_planning_required'] = True
        gate = mini._stage3_execution_gate(self.task)
        self.assertFalse(gate['allowed'])
        with self.assertRaises(mini.PlanApprovalRequiredError):
            mini.prepare_worker_mission_context(self.task, self.contract, {'files': ['existing.py']})

    def test_f_unsubmitted_context_is_not_reported_as_rejected_impact(self):
        idle = {'role': 'assistant', 'content': 'done', 'tool_calls': []}
        result = self.execute([idle, idle])
        self.assertEqual(result['failure_type'], 'CONTEXT_SUFFICIENCY_REQUIRED')
        self.assertIn('context gate', result['summary'])
        self.assertIsNone(result['impact_validation'])
        self.assertEqual(mini.RUN['impact_contracts_validated'], 0)

    def test_rejected_candidate_is_diagnosed_and_stops_before_write(self):
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        candidate['contract_hash'] = 'forged'
        with patch.object(mini, 'ask_ollama', side_effect=self.responses()):
            result = mini.execute_agent_task(self.goal, {}, context_sufficiency_enabled=True,
                context_anchor={'root_goal': self.goal, 'local_task': self.goal},
                impact_contract=candidate, impact_contract_required=True)
        self.assertEqual(result['failure_type'], impact.IMPACT_INVALID)
        self.assertIn('hash', result['summary'])
        self.assertFalse((self.root / 'welcone.txt').exists())

    def test_wrong_content_cannot_pass_post_state_even_with_claimed_verification(self):
        result = self.execute(self.responses(content='wrong'))
        comparison = mini._impact_post_mutation_check(result['impact_contract'], verification_result={'passed': True})
        self.assertFalse(comparison['passed'])
        self.assertTrue(any(row.get('kind') == 'literal_file_post_state' for row in comparison['missing']))

    def test_other_names_and_extensions_are_not_hardcoded(self):
        for name, expected in [('greeting', 'greeting.txt'), ('notes.md', 'notes.md')]:
            contract = dict(self.contract, goal=f'Create a text file named {name} containing exactly hello.',
                            original_goal=f'Create a text file named {name} containing exactly hello.')
            task = mini.root_task_from_contract(contract)
            candidate = mini._prepare_task_impact_contract(task, contract)
            self.assertEqual(candidate['authorized_mutation_paths'], [expected])

    def test_filename_mapping_requires_the_same_literal_name(self):
        ledger = mini.build_source_requirement_ledger([{'text': "The file name must be 'welcone'."}])
        coverage = mini.specification_coverage(ledger, {'acceptance_criteria': ["A file named 'welcone' exists."]})
        self.assertEqual(coverage[0]['status'], 'MAPPED')
        wrong = mini.specification_coverage(ledger, {'acceptance_criteria': ["A file named 'other' exists."]})
        self.assertEqual(wrong[0]['status'], 'UNMAPPED')

    def test_legacy_goal_interpretation_populates_source_ledger_before_task_brain(self):
        model = {'status': 'ready', 'goal': 'Create a sample file.', 'constraints': [],
                 'requirements': ['Create a text file.', "The file name must be 'sample'.",
                                  "The content must be 'hello'."], 'success_criteria': ['The sample exists.']}
        with patch.object(mini, 'understand_goal', return_value=model):
            contract = mini.get_goal_contract('please do my small thing', interactive=False)
        ids = [item['requirement_id'] for item in mini.ledger_requirements(contract['source_requirement_ledger'])]
        self.assertEqual(ids, ['REQ-001', 'REQ-002', 'REQ-003'])
        self.assertIn("'sample'", contract['requirements'][1])
        self.assertEqual(mini.RUN['source_requirements_extracted'], 3)
        self.assertEqual([item['requirement_id'] for item in mini.ledger_requirements(
            contract['source_contract']['source_requirement_ledger'])], ids)

    def test_unsafe_named_paths_never_authorize_creation(self):
        for name in ['../escape', '.hivo/private']:
            with self.subTest(name=name):
                goal = f'Create a text file named {name} containing exactly hello.'
                contract = dict(self.contract, goal=goal, original_goal=goal)
                candidate = mini._prepare_task_impact_contract(mini.root_task_from_contract(contract), contract)
                self.assertFalse(impact.accept_pre_mutation_impact_contract(candidate)['accepted'])
        compound = dict(self.contract, original_goal=self.goal + ' Also change another file.')
        candidate = mini._prepare_task_impact_contract(mini.root_task_from_contract(compound), compound)
        self.assertFalse(candidate.get('scope_required', False))

    def test_rejection_is_not_generic_missing_context_diagnosis(self):
        diagnosis = mini.diagnose_failure(self.task, {'status': 'failed', 'failure_type': impact.IMPACT_INVALID})
        self.assertEqual(diagnosis['category'], 'orchestration_failure')

    def test_resolved_path_is_mandatory_and_scope_errors_name_it(self):
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        packet = mini._append_impact_contract_projection('bounded source context', self.task)
        self.assertTrue(packet.startswith('NAMED LITERAL ARTIFACT PLAN'))
        self.assertIn('welcone.txt', packet)
        self.assertIn('DERIVED', packet)
        self.assertLessEqual(len(packet), mini.MAX_WORKER_MISSION_CHARS)
        result = self.execute(self.responses())
        mini.ACTIVE_IMPACT_CONTRACT = result['impact_contract']
        mini.ACTIVE_IMPACT_REQUIRED = True
        gate = mini.stage7_context.ContextSufficiencyGate({'root_goal': self.goal, 'local_task': self.goal})
        gate.evaluate({'context_status': 'sufficient', 'reason': 'The literal file contract is completely specified.'})
        mini.ACTIVE_CONTEXT_SUFFICIENCY_GATE = gate
        reply = mini.run_tool('write_file', {'path': 'welcone', 'content': 'welcome'}, role='Builder')
        self.assertIn('welcone.txt', reply)
        self.assertFalse((self.root / 'welcone').exists())

    def test_literal_text_with_code_suffix_is_verified_without_execution(self):
        text = 'raise AssertionError()'
        goal = 'Create a text file named proof.py containing exactly "raise AssertionError()".'
        contract = dict(self.contract, goal=goal, original_goal=goal)
        task = mini.root_task_from_contract(contract)
        candidate = mini._prepare_task_impact_contract(task, contract)
        accepted = impact.accept_pre_mutation_impact_contract(candidate)
        self.assertTrue(accepted['accepted'], accepted)
        mini.ACTIVE_IMPACT_CONTRACT = accepted['contract']
        (self.root / 'proof.py').write_text(text, encoding='utf-8')
        with patch.object(mini.subprocess, 'run', side_effect=AssertionError('literal text must not execute')):
            import json
            self.assertTrue(json.loads(mini.run_file('proof.py'))['passed'])

    def test_reusing_candidate_after_creation_preserves_resolved_scope(self):
        candidate = mini._prepare_task_impact_contract(self.task, self.contract)
        (self.root / 'welcone.txt').write_bytes(b'welcome')
        reused = mini._prepare_task_impact_contract(self.task, self.contract)
        self.assertEqual(reused['path_resolution'], candidate['path_resolution'])
        self.assertEqual(reused['verification_obligations'], candidate['verification_obligations'])

    def test_literal_route_rejects_generic_or_foreign_proof(self):
        from hivo.verification_routing import _evidence_matches
        import json
        result = self.execute(self.responses())
        accepted = result['impact_contract']
        route = {'kind': 'LITERAL_ARTIFACT', 'target': 'welcone.txt',
                 'expected_sha256': accepted['expected_targets'][0]['post_state_sha256'],
                 'impact_contract_hash': accepted['contract_hash']}
        mini.ACTIVE_IMPACT_CONTRACT = accepted
        native = mini.run_file('welcone.txt')
        self.assertTrue(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': native}))
        self.assertFalse(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': 'PASS'}))
        forged = json.loads(native)
        forged['impact_contract_hash'] = 'foreign'
        self.assertFalse(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': forged}))
        forged = json.loads(native)
        forged['actual_sha256'] = 'wrong'
        self.assertFalse(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': forged}))
        for missing in ['actual_sha256', 'passed']:
            forged = json.loads(native)
            forged.pop(missing)
            self.assertFalse(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': forged}))
        forged = json.loads(native)
        forged['passed'] = False
        self.assertFalse(_evidence_matches(route, {'tool': 'run_file', 'target': 'welcone.txt', 'result': forged}))


if __name__ == '__main__':
    unittest.main()
