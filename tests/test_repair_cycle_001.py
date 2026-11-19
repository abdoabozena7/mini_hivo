"""Controlled architectural regressions; no live providers or benchmark runs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo import pre_mutation_impact as impact
from hivo.semantic_evidence import SemanticEvidenceResolver


def call(name, **args):
    return {'role': 'assistant', 'content': '', 'tool_calls': [
        {'function': {'name': name, 'arguments': json.dumps(args)}}]}


class RepairCycleTests(unittest.TestCase):
    def setUp(self):
        names = ('WORKSPACE', 'RUN', 'RUN_ID', 'TASKS', 'ACTIVE_CONTRACT', 'ACTIVE_TOOL_CONTRACT',
                 'ACTIVE_CONTEXT_SUFFICIENCY_GATE', 'ACTIVE_IMPACT_CONTRACT', 'ACTIVE_IMPACT_REQUIRED',
                 'ACTIVE_PROJECT_WORLD_MODEL', 'ACTIVE_TRANSACTION', 'LAST_COMMITTED_TRANSACTION', 'MEMORY_STORE')
        saved = {n: getattr(mini, n) for n in names}
        self.addCleanup(lambda: [setattr(mini, n, v) for n, v in saved.items()])
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        mini.WORKSPACE = self.root
        mini.ACTIVE_PROJECT_WORLD_MODEL = None
        mini.ACTIVE_TOOL_CONTRACT = None
        mini.ACTIVE_IMPACT_CONTRACT = None
        mini.ACTIVE_TRANSACTION = None
        mini.MEMORY_STORE = None
        mini.reset_run('recursive')
        mini.RUN['project_mode'] = mini.NEW_PROJECT
        self.goal = 'Build a local utility and its presentation assets.'
        self.contract = {'goal': self.goal, 'original_goal': self.goal,
                         'requirements': ['Deliver verified local artifacts'], 'constraints': []}
        mini.RUN['source_contract'] = self.contract
        mini.ACTIVE_CONTRACT = self.contract
        self.provider = patch.object(mini, 'structured_model_call', side_effect=AssertionError('no live model'))
        self.provider.start()
        self.addCleanup(self.provider.stop)

    def task(self, paths=('engine.py', 'theme.css'), goal='Implement the utility and local presentation assets.'):
        task = mini.make_task('1', goal, 1, 'ROOT', ['requested output verified'], list(paths))
        task['worker_mission'] = {'targets': list(paths)}
        mini.TASKS['1'] = task
        return task

    def worker(self, task, replies, role='Builder', provider=None, worker_context=None, contract=None):
        candidate = mini._prepare_task_impact_contract(task, contract or self.contract)
        mini.ACTIVE_TOOL_CONTRACT = {'goal': task['goal'], 'requirements': task['done_when']}
        if 'greenfield_inspection_paths' in task:
            mini.ACTIVE_TOOL_CONTRACT['allowed_inspection_paths'] = task['greenfield_inspection_paths']
        with patch.object(mini, 'ask_ollama', side_effect=replies):
            return mini.execute_agent_task(
                task['goal'], {}, role=role, task_id=task['id'], max_steps=12,
                worker_context=worker_context or 'The assigned local paths and requirements define this task.',
                extra_context=worker_context,
                context_sufficiency_enabled=True,
                context_anchor={'root_goal': self.goal, 'local_task': task['goal'], 'requirements': task['done_when'],
                                'allowed_inspection_paths':task.get('greenfield_inspection_paths',[])},
                context_evidence_provider=provider,
                impact_contract=candidate, impact_contract_required=True,
            )

    def test_recorded_nine_lexical_targets_are_replaced_by_assigned_paths(self):
        task = self.task(('index.html', 'style.css', 'app.js'),
                         'Set up the basic structure and styling for the To-Do List application.')
        candidate = mini._prepare_task_impact_contract(task, self.contract)
        self.assertEqual({x['path'] for x in candidate['expected_targets']}, set(task['scope_hint']))
        self.assertEqual(set(candidate['authorized_mutation_paths']), set(task['scope_hint']))
        self.assertNotIn('structure', {x['target'] for x in candidate['expected_targets']})

    def test_authorized_multifile_mutation_crosses_real_impact_commit_boundary(self):
        task = self.task()
        mini.begin_transaction('1')
        result = self.worker(task, [call('context_sufficiency_check', context_status='sufficient'),
            call('write_file', path='engine.py', content='print("ready")\n'),
            call('write_file', path='theme.css', content='body { color: navy; }'),
            {'role': 'assistant', 'content': 'Implemented', 'tool_calls': []}])
        self.assertEqual(result['status'], 'done', result['summary'])
        # Deliberately isolate the impact/transaction boundary, not the web verifier.
        accepted = mini._commit_verified_leaf(task, self.contract, result, None, None,
                                             {'passed': True}, {})
        self.assertEqual(accepted['status'], 'done', accepted)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)
        self.assertEqual((self.root/'engine.py').read_text(), 'print("ready")\n')

    def test_scope_escape_is_blocked_before_write(self):
        task = self.task(('engine.py',))
        mini.begin_transaction('1')
        result = self.worker(task, [call('context_sufficiency_check', context_status='sufficient'),
            call('write_file', path='foreign.py', content='unauthorized'),
            {'role': 'assistant', 'content': 'stop', 'tool_calls': []}])
        self.assertFalse((self.root/'foreign.py').exists())
        self.assertTrue(any('OUT_OF_SCOPE' in str(x.get('result')) for x in result['tool_evidence']))
        mini.rollback_transaction()

    def test_assigned_path_case_matches_runtime_normalization(self):
        task = self.task(('Engine.py',))
        mini.begin_transaction('1')
        result = self.worker(task, [call('context_sufficiency_check', context_status='sufficient'),
            call('write_file', path='Engine.py', content='value = 1'),
            {'role':'assistant','content':'Implemented','tool_calls':[]}])
        self.assertEqual((self.root/'Engine.py').read_text(), 'value = 1')
        self.assertTrue(result['mutation_authorized'])
        mini.rollback_transaction()

    def test_missing_greenfield_assignment_does_not_authorize_inferred_prose_targets(self):
        task = self.task(())
        result = self.worker(task, [call('context_sufficiency_check', context_status='sufficient'),
            call('write_file',path='unassigned.py',content='blocked'),
            {'role':'assistant','content':'Cannot implement without scope.','tool_calls':[]}])
        self.assertFalse(result['impact_authorized'])
        self.assertFalse((self.root/'unassigned.py').exists())

    def test_terminal_context_failure_stops_without_another_provider_call(self):
        task = self.task(('engine.py',))
        asked = []
        def reply(*_args, **_kwargs):
            asked.append(1)
            return call('context_sufficiency_check', context_status='insufficient',
                        reason='Required return contract is missing.',
                        needed_evidence=[{'kind': 'contract', 'target': 'unavailable.return',
                                          'why': 'Required return contract is missing.'}])
        result = self.worker(task, reply)
        self.assertEqual(result['failure_type'], mini.CONTEXT_INSUFFICIENT_FAILURE)
        self.assertEqual(len(asked), 4)
        self.assertFalse(result['mutation_authorized'])
        self.assertFalse((self.root/'engine.py').exists())

    def test_completion_feedback_survives_a_long_mission(self):
        task = self.task(('engine.py',))
        task['dependency_inspection_paths'] = ['public.py']
        seen = []
        def reply(messages, *_args, **_kwargs):
            seen.append(copy.deepcopy(messages))
            if len(seen) == 1:
                self.assertGreater(len(messages[-1]['content']), mini.MAX_WORKER_MISSION_CHARS)
                return call('context_sufficiency_check', context_status='insufficient',
                            reason='Need the public return type.',
                            needed_evidence=[{'kind': 'contract', 'target': 'public.return',
                                              'why': 'Need the public return type.'}])
            if len(seen) == 2:
                self.assertIn('verified-return-contract', json.dumps(messages))
                return call('context_sufficiency_check', context_status='sufficient')
            return {'role': 'assistant', 'content': 'context resolved', 'tool_calls': []}
        def evidence(request, _context):
            return [{'kind': 'contract', 'target': request['target'],
                     'source_identity': 'public.py:1', 'excerpt': 'verified-return-contract',
                     'authoritative': True, 'claim_key': 'public.return', 'claim_value': 'text'}]
        result = self.worker(task, reply, provider=evidence,
                             worker_context='preserve source authority ' * 500)
        self.assertTrue(result['mutation_authorized'], result)
        self.assertEqual(len(seen), 3)

    def test_real_dependency_source_resolves_context_without_authorizing_its_mutation(self):
        (self.root/'base.py').write_text('def value():\n    return 1\n')
        task = self.task(('consumer.py',))
        task['dependency_inspection_paths'] = ['base.py']
        replies = [call('context_sufficiency_check', context_status='insufficient',
            reason='Need the current dependency source.', needed_evidence=[
                {'kind':'definition','target':'base.py','why':'Inspect dependency before using it.'}]),
            call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='consumer.py',content='from base import value'),
            call('write_file',path='base.py',content='unauthorized replacement'),
            {'role':'assistant','content':'Consumer implemented.','tool_calls':[]}]
        mini.begin_transaction('1')
        result = self.worker(task,replies)
        self.assertTrue(result['mutation_authorized'],result)
        self.assertEqual((self.root/'consumer.py').read_text(),'from base import value')
        self.assertIn('return 1',(self.root/'base.py').read_text())
        self.assertTrue(any('UNEXPECTED_AND_OUT_OF_SCOPE' in row['result'] for row in result['tool_evidence']))
        self.assertIn('base.py', json.dumps(result['tool_evidence'][0]))
        mini.rollback_transaction()

    def test_decomposition_preserves_explicit_dependencies(self):
        parent = mini.make_task('ROOT', 'Build composed utility', done_when=['complete'])
        specs = {'children': [
            {'goal': 'Create base', 'done_when': ['base exists'], 'scope_hint': ['base.py'], 'depends_on': []},
            {'goal': 'Extend base', 'done_when': ['extension works'], 'scope_hint': ['base.py'], 'depends_on': ['1']}]}
        with patch.object(mini, 'structured_model_call', return_value=specs):
            children = mini.decompose_task(parent, self.contract, {'files': []})
        self.assertEqual(mini._scheduler_dependency_ids(children[1]), ['1'])
        self.assertIn('depends_on', mini.children_schema()['properties']['children']['items']['properties'])

    def test_file_definition_uses_only_current_authorized_source(self):
        (self.root/'view.html').write_text('<main>Current source</main>')
        request = {'kind': 'definition', 'target': 'view.html', 'why': 'Need current document structure.'}
        resolver = SemanticEvidenceResolver(self.root, [self.root/'view.html'])
        result = resolver.resolve(request)
        self.assertEqual(result['resolution_status'], 'resolved', result)
        self.assertIn('Current source', json.dumps(result['evidence']))
        denied = SemanticEvidenceResolver(self.root, []).resolve(request)
        self.assertEqual(denied['evidence'], [])
        contract = resolver.resolve(dict(request, kind='authoritative_contract'))
        self.assertNotEqual(contract['resolution_status'], 'resolved')
        (self.root/'view.html').unlink()
        missing = SemanticEvidenceResolver(self.root, [self.root/'view.html']).resolve(request)
        self.assertEqual(missing['evidence'], [])

    def test_explicit_required_target_is_not_downgraded_to_optional_scope(self):
        task = self.task(('engine.py',))
        contract = dict(self.contract, expected_targets=[
            {'target': 'engine.py', 'path': 'engine.py', 'kind': 'path', 'required': True}])
        candidate = mini._prepare_task_impact_contract(task, contract)
        self.assertTrue(any(t['path']=='engine.py' and t['required'] for t in candidate['expected_targets']))
        mini.begin_transaction('1')
        result = self.worker(task, [call('context_sufficiency_check', context_status='sufficient'),
            {'role': 'assistant', 'content': 'claimed complete', 'tool_calls': []}], contract=contract)
        rejected = mini._commit_verified_leaf(task, contract, result, {}, {}, {'passed': True}, {})
        self.assertEqual(rejected['status'], 'failed')

    def test_dependency_schema_rejects_forward_cycles_and_invalid_references(self):
        specs = {'children': [
            {'goal': 'A', 'done_when': ['A'], 'scope_hint': ['a.py'], 'depends_on': ['2']},
            {'goal': 'B', 'done_when': ['B'], 'scope_hint': ['b.py'], 'depends_on': []}]}
        self.assertFalse(mini._children_validator(specs))
        specs['children'][0]['depends_on'] = []
        specs['children'][1]['depends_on'] = ['1']
        self.assertTrue(mini._children_validator(specs))
        specs['children'][1]['depends_on'] = ['0']
        self.assertFalse(mini._children_validator(specs))
        specs['children'][1]['depends_on'] = ['01']
        self.assertFalse(mini._children_validator(specs))

    def test_explicit_empty_outer_scope_cannot_be_expanded_by_child(self):
        task = self.task(('engine.py',))
        candidate = mini._prepare_task_impact_contract(
            task, dict(self.contract, allowed_mutation_paths=[], allowed_inspection_paths=[]))
        self.assertEqual(candidate['authorized_mutation_paths'], [])
        self.assertEqual(task.get('greenfield_inspection_paths'), [])
        checked = impact.validate_pre_mutation_impact_contract(candidate)
        self.assertFalse(checked.get('valid', checked.get('accepted')))

    def test_decomposed_dependent_is_not_dispatched_after_rollback(self):
        parent = mini.make_task('ROOT', 'Compose outputs', done_when=['complete'])
        specs = {'children': [
            {'goal': 'base', 'done_when': ['base'], 'scope_hint': ['base.py'], 'depends_on': []},
            {'goal': 'consumer', 'done_when': ['consumer'], 'scope_hint': ['consumer.py'], 'depends_on': ['1']}]}
        with patch.object(mini, 'structured_model_call', return_value=specs):
            children = mini.decompose_task(parent, self.contract, {'files': []})
        seen = []
        def leaf(task, _contract, memory, _repo, *_args):
            seen.append(task['id'])
            mini.begin_transaction(task['id'])
            mini._transaction_capture(self.root/'base.py')
            (self.root/'base.py').write_text('unaccepted')
            mini.rollback_transaction()
            return {'status':'failed', 'failure_type':'IMPACT_VERIFICATION_FAILED', 'memory':memory}
        result = mini._execute_children(parent,children,0,self.contract,{}, {'files':[]},'',[],
            fit_decider=lambda *_args:{'decision':'execute'},leaf_executor=leaf,
            aggregator=lambda *_args,**_kwargs: self.fail('failed dependency cannot aggregate successfully'))
        self.assertEqual(seen,['1'])
        self.assertEqual(children[1]['status'],'blocked')
        self.assertEqual(result['status'],'failed')
        self.assertFalse((self.root/'base.py').exists())

    def test_real_repair_edit_requires_fresh_verification_before_commit(self):
        # Reuse the existing non-web literal-artifact fixture: real file tools,
        # Context/Impact gates, exact-byte verification and commit; scripted AI.
        from test_greenfield_impact_lifecycle import GreenfieldImpactLifecycleTests
        fixture = GreenfieldImpactLifecycleTests('test_a_simple_greenfield_file_verified_through_leaf')
        fixture.setUp()
        try:
            builder = fixture.execute(fixture.responses(content='defective'))
            fixture.task['impact_contract'] = copy.deepcopy(builder['impact_contract'])
            failed = mini.evidence_gate(builder)
            self.assertFalse(failed['passed'])
            with self.assertRaises(ValueError):
                mini._commit_verified_leaf(fixture.task, fixture.contract, builder, {}, {}, failed, {})
            replies = [call('context_sufficiency_check', context_status='sufficient'),
                call('read_file', path='welcone.txt'),
                call('edit_file', path='welcone.txt', old='defective', new='welcome'),
                call('run_file', path='welcone.txt'),
                {'role':'assistant','content':'Repaired and freshly verified.','tool_calls':[]}]
            with patch.object(mini,'ask_ollama',side_effect=replies):
                repaired = mini.repair_task(fixture.task, fixture.contract,
                    [{'status':'FAIL','evidence':'exact bytes differ'}],{},'Repair only demonstrated content.')
            self.assertTrue(repaired['mutation_authorized'],repaired)
            self.assertEqual((fixture.root/'welcone.txt').read_bytes(),b'welcome')
            fresh = mini.evidence_gate(repaired)
            self.assertTrue(fresh['passed'],fresh)
            accepted = mini._commit_verified_leaf(fixture.task,fixture.contract,repaired,{}, {},fresh,{})
            self.assertEqual(accepted['status'],'done',accepted)
            self.assertIsNone(mini.ACTIVE_TRANSACTION)
        finally:
            fixture.tearDown()

    def test_scheduler_refreshes_disk_context_after_commit_and_rollback(self):
        parent = mini.make_task('ROOT', 'Compose outputs', done_when=['complete'])
        a = mini.make_task('1', 'base', 1, 'ROOT', ['verified'], ['base.py'])
        b = mini.make_task('2', 'consumer', 1, 'ROOT', ['verified'], ['consumer.py'])
        b['dependencies'] = ['1']
        mini.TASKS.update({'ROOT':parent, '1':a, '2':b})
        snapshots = []
        def leaf(task, _contract, memory, repo, *_args):
            snapshots.append({x['path'] if isinstance(x,dict) else x for x in repo.get('files',[])})
            if task['id']=='1':
                (self.root/'base.py').write_text('value=1')
                mini.begin_transaction('scratch')
                mini._transaction_capture(self.root/'discard.py')
                (self.root/'discard.py').write_text('discarded')
                mini.rollback_transaction()
            return {'status':'done','summary':'verified','memory':memory,'changed_files':[]}
        mini._execute_children(parent,[a,b],0,self.contract,{}, {'files':['stale.py']},'',[],
            fit_decider=lambda *_args:{'decision':'execute'},leaf_executor=leaf,
            aggregator=lambda *_args,**_kwargs:{'status':'done','memory':{}})
        self.assertIn('base.py',snapshots[1])
        self.assertNotIn('discard.py',snapshots[1])
        self.assertNotIn('stale.py',snapshots[1])


if __name__ == '__main__': unittest.main()
