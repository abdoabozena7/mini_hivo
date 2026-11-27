"""Read-only parent controller and negative authority controls; scripted backend."""
import copy
import unittest
from unittest.mock import patch

import mini
from hivo import behavioral_obligations as behavior
from hivo import requirements
from hivo.integration_gate import canonical_hash, fingerprint_dependency_paths
import test_repair_cycle_001 as fixtures
import test_behavioral_obligations as scenarios


class ReadOnlyParentTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepairCycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        rows = [{'text': 'Create index.html, style.css and app.js.', 'explicit_items': ['index.html', 'style.css', 'app.js']},
                {'text': 'Clicking Increase increments the visible count.'}, {'text': 'Count persists after reload.'}]
        ledger = requirements.build_source_requirement_ledger(rows)
        self.records = mini.ledger_requirements(ledger)
        ids = [r['requirement_id'] for r in self.records]
        self.contract = mini.normalize_goal_contract('Build a browser counter.',
            {'goal': 'Build a browser counter.', 'requirements': [r['text'] for r in rows]}, source_ledger=ledger)
        mini.RUN['source_contract'] = self.contract
        mini.RUN['source_requirement_ledger'] = ledger
        self.parent = mini.make_task('ROOT', self.contract['goal'], done_when=self.contract['requirements'])
        self.parent.update(parent_requirement_ids=[], parent_verification_obligations=[])
        preflight = patch.object(mini, 'run_integration_preflight', return_value={
            'passed': True, 'status': 'PASS', 'conflicts': [], 'error_count': 0,
            'checked_files': ['index.html', 'app.js'], 'syntax_errors': [], 'warnings': []})
        preflight.start()
        self.addCleanup(preflight.stop)
        (self.root / 'index.html').write_text('<title>Counter</title><script src="app.js"></script>')
        (self.root / 'style.css').write_text('body {color:navy}')
        (self.root / 'app.js').write_text('let count=0;')
        foundation = mini.make_task('1', 'Create counter files', 1, 'ROOT', ['Files exist'], ['index.html', 'style.css', 'app.js'])
        foundation['requirement_ids'] = ids[:1]
        foundation['verification_obligations'] = [dict(requirement_id=ids[0], source_text=rows[0]['text'],
            kind='file_exists', target=p) for p in ['index.html', 'style.css', 'app.js']]
        feature = mini.make_task('2', 'Implement increment and persistence', 1, 'ROOT', ['Behavior works'], ['app.js'])
        feature.update(requirement_ids=ids[1:], depends_on=['1'], verification_obligations=[
            scenarios.scenario(ids[1], rows[1]['text']), scenarios.scenario(ids[2], rows[2]['text'], reload=True)])
        self.children = []
        for task in [foundation, feature]:
            proof = self.proof(task['verification_obligations'])
            result = {'status': 'done', 'summary': 'Scripted accepted child', 'changed_files': task['scope_hint'],
                      'gate': {'passed': True, 'obligation_verification': proof}}
            self.children.append({'task': task, 'result': result})

    def proof(self, oracles):
        fingerprint = fingerprint_dependency_paths(self.root, ['index.html', 'style.css', 'app.js'])
        p = {'passed': True, 'source_hash': canonical_hash(self.records), 'obligation_hash': canonical_hash(oracles),
             'subject_before': fingerprint, 'subject_after': fingerprint,
             'checks': [{'requirement_id': o['requirement_id'], 'target': o['target'], 'passed': True} for o in oracles]}
        p['receipt_hash'] = canonical_hash(p)
        return p

    def aggregate(self, verifier=None):
        def verify(_root, records, ids, oracles, *args, **kwargs):
            return self.proof(oracles)
        with patch.object(behavior, 'verify', side_effect=verifier or verify), \
             patch.object(mini, 'execute_agent_task', side_effect=AssertionError('Mutable parent Worker dispatched')):
            return mini.aggregate_task(self.parent, self.contract, self.children, {}, mini.inspect_repository(), root=True)

    def test_parent_acceptance_uses_no_mutable_worker_or_project_mutation(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()}
        result = self.aggregate()
        self.assertEqual(result['status'], 'done')
        self.assertEqual(result['changed_files'], [])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir() if p.is_file()})

    def test_source_change_during_parent_verification_cannot_pass(self):
        def tamper(_root, records, ids, oracles, *args, **kwargs):
            (self.root / 'app.js').write_text('// out of band change')
            return self.proof(oracles)
        result = self.aggregate(tamper)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['failure_type'], 'READ_ONLY_PARENT_SOURCE_CHANGED')

    def test_missing_child_proof_blocks_parent(self):
        self.children[1]['result']['gate'].pop('obligation_verification')
        result = self.aggregate()
        self.assertEqual(result['status'], 'failed')

    def test_changed_child_obligation_metadata_cannot_reuse_old_proof(self):
        self.children[1]['task']['verification_obligations'][0]['steps'][2]['expected'] = '9'
        self.assertEqual(self.aggregate()['status'], 'failed')

    def test_missing_parent_requirement_oracle_cannot_pass(self):
        self.children[1]['task']['requirement_ids'].pop()
        self.children[1]['task']['verification_obligations'].pop()
        self.parent['parent_requirement_ids'] = [self.records[2]['requirement_id']]
        self.assertEqual(self.aggregate()['status'], 'failed')

    def test_explicit_empty_parent_inspection_scope_is_preserved(self):
        self.contract['allowed_inspection_paths'] = []
        result = self.aggregate()
        self.assertEqual(result['status'], 'failed')

    def test_parent_cannot_bypass_unresolved_integration_conflict(self):
        failed = {'passed': False, 'status': 'FAIL', 'conflicts': [], 'error_count': 1}
        with patch.object(mini, 'run_integration_preflight', return_value=failed), \
             patch.object(mini, 'create_integration_tasks', return_value=[]):
            self.assertEqual(self.aggregate()['status'], 'failed')

    def test_readonly_tool_boundary_rejects_commands_execution_and_writes(self):
        mini.ACTIVE_TOOL_CONTRACT = {'parent_verification_read_only': True,
                                     'allowed_inspection_paths': ['app.js']}
        for name, args in [('write_file', {'path': 'app.js', 'content': '// bad'}),
                           ('edit_file', {'path': 'app.js', 'old': 'count', 'new': 'bad'}),
                           ('run_command', {'command': 'node mutate.js'}), ('run_file', {'path': 'mutate.py'})]:
            with self.subTest(name=name):
                self.assertIn('PARENT_VERIFICATION_READ_ONLY', mini.run_tool(name, args, role='Builder'))
        self.assertEqual((self.root / 'app.js').read_text(), 'let count=0;')


if __name__ == '__main__':
    unittest.main()
