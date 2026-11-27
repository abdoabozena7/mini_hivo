"""Oracle validation and production acceptance gate; browser proof is separate."""
import copy
import unittest
from unittest.mock import patch

import mini
from hivo import behavioral_obligations as behavior
from hivo import requirements
import test_repair_cycle_001 as fixtures


def scenario(requirement_id, text, *, reload=False):
    steps = [{'action': 'assert_text', 'selector': '#value', 'expected': '0'},
             {'action': 'click', 'selector': '#increase'},
             {'action': 'assert_text', 'selector': '#value', 'expected': '1'}]
    if reload:
        steps += [{'action': 'reload'}, {'action': 'assert_text', 'selector': '#value', 'expected': '1'}]
    return {'requirement_id': requirement_id, 'source_text': text,
            'kind': 'browser_scenario', 'target': 'index.html', 'steps': steps}


class BehavioralObligationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepairCycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        ledger = requirements.build_source_requirement_ledger([{'text': 'Clicking Increase increments the visible count.'}])
        self.records = mini.ledger_requirements(ledger)
        self.key = self.records[0]['requirement_id']
        self.oracle = scenario(self.key, self.records[0]['text'])
        source = dict(self.fixture.contract, source_requirement_ledger=ledger)
        mini.RUN['source_contract'] = source
        mini.RUN['source_requirement_ledger'] = ledger
        mini.ACTIVE_TOOL_CONTRACT = {'task_id': '2', 'requirement_ids': [self.key],
            'source_obligations_required': True,
            'requirements': [self.records[0]['text']], 'verification_obligations': [self.oracle],
            'allowed_inspection_paths': ['index.html', 'app.js']}
        self.builder = {'status': 'done', 'tool_evidence': [
            {'tool': 'run_command', 'target': 'node --check app.js', 'result': '[exit_code=0]'}]}

    def validate(self, oracle=None, records=None):
        return behavior.validate(records or self.records, [self.key], [oracle or self.oracle], self.root)

    def test_missing_behavior_cannot_pass_with_syntax_evidence(self):
        with patch.object(behavior, 'verify', return_value={'passed': False, 'failure_type': behavior.FAILED, 'errors': ['no state change']}):
            self.assertFalse(mini.evidence_gate(self.builder)['passed'])

    def test_missing_obligations_cannot_pass(self):
        mini.ACTIVE_TOOL_CONTRACT.pop('verification_obligations')
        self.assertFalse(mini.evidence_gate(self.builder)['passed'])

    def test_each_gate_requires_fresh_independent_verification(self):
        with patch.object(behavior, 'verify', side_effect=[{'passed': False}, {'passed': True}]) as verify:
            self.assertFalse(mini.evidence_gate(self.builder)['passed'])
            self.assertTrue(mini.evidence_gate(self.builder)['passed'])
            self.assertEqual(verify.call_count, 2)

    def test_transition_scenario_is_supported(self):
        self.assertEqual(self.validate(), [])

    def test_unknown_source_meaning_is_not_certified_by_unrelated_actions(self):
        self.records[0]['text'] = 'Make the interface beautiful.'
        self.oracle['source_text'] = self.records[0]['text']
        self.assertTrue(self.validate())

    def test_page_visibility_is_not_a_state_change(self):
        self.oracle['steps'] = [{'action': 'click', 'selector': '#increase'},
                                {'action': 'assert_visible', 'selector': 'body', 'expected': True}]
        self.assertTrue(self.validate())

    def test_constant_assertion_cannot_certify_inert_action(self):
        self.oracle['steps'][2]['expected'] = '0'
        self.assertTrue(self.validate())

    def test_persistence_requires_reload(self):
        self.records[0]['text'] = 'The count persists after reload.'
        self.oracle['source_text'] = self.records[0]['text']
        self.assertTrue(self.validate())

    def test_wrong_source_text_and_unsafe_target_fail_closed(self):
        self.oracle['source_text'] = 'Show any page'
        self.assertTrue(self.validate())
        self.oracle['source_text'] = self.records[0]['text']
        self.oracle['target'] = '../index.html'
        self.assertTrue(self.validate())

    def test_generated_javascript_is_not_an_allowed_oracle_action(self):
        self.oracle['steps'].insert(1, {'action': 'evaluate', 'code': 'return true'})
        self.assertTrue(self.validate())

    def test_file_existence_cannot_verify_functionality(self):
        self.oracle = {k: v for k, v in self.oracle.items() if k != 'steps'}
        self.oracle['kind'] = 'file_exists'
        self.assertTrue(self.validate())

    def test_all_explicit_files_need_individual_checks(self):
        record = {'requirement_id': self.key, 'text': 'Create a.html and a.js.', 'explicit_items': ['a.html', 'a.js']}
        oracle = {'requirement_id': self.key, 'source_text': record['text'], 'kind': 'file_exists', 'target': 'a.html'}
        self.assertTrue(self.validate(oracle, [record]))
        self.assertEqual(behavior.validate([record], [self.key], [oracle, dict(oracle, target='a.js')], self.root), [])

    def test_controller_absolute_inspection_path_preserves_existing_authority(self):
        record = {'requirement_id': self.key, 'text': 'Create a.html.', 'explicit_items': ['a.html']}
        (self.root / 'a.html').write_text('<title>Page</title>')
        oracle = {'requirement_id': self.key, 'source_text': record['text'], 'kind': 'file_exists', 'target': 'a.html'}
        actual = behavior.verify(self.root, [record], [self.key], [oracle], {},
                                  allowed_paths=[str(self.root / 'a.html')])
        self.assertTrue(actual['passed'])
        rejected = behavior.verify(self.root, [record], [self.key], [oracle], {},
                                    allowed_paths=[str(self.root.parent / 'a.html')])
        self.assertFalse(rejected['passed'])


if __name__ == '__main__':
    unittest.main()
