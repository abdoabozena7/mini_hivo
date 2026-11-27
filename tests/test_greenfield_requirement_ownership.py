"""Canonical greenfield allocation through real decomposition; no providers."""
import copy
import unittest
from unittest.mock import patch

import mini
from hivo import requirements
import test_repair_cycle_001 as fixtures
import test_behavioral_obligations as behavior_fixtures


class RequirementOwnershipTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.RepairCycleTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        ledger = requirements.build_source_requirement_ledger([
            {'text': 'Create index.html, style.css and app.js.', 'explicit_items': ['index.html', 'style.css', 'app.js']},
            {'text': 'Clicking Increase updates the visible count.'}])
        self.contract = mini.normalize_goal_contract('Build a browser counter.',
            {'goal': 'Build a browser counter.', 'requirements': [x['text'] for x in mini.ledger_requirements(ledger)]},
            source_ledger=ledger)
        mini.RUN['source_contract'] = self.contract
        self.ids = [r['requirement_id'] for r in mini.ledger_requirements(ledger)]
        self.parent = mini.make_task('ROOT', self.contract['goal'], done_when=self.contract['requirements'])
        self.plan = {'children': [
            {'goal': 'Create the page and styles', 'done_when': ['Page loads'],
             'scope_hint': ['index.html', 'style.css', 'app.js'], 'depends_on': [],
             'requirement_ids': [self.ids[0]]},
            {'goal': 'Implement counter behavior', 'done_when': ['Increase changes count'],
             'scope_hint': ['app.js'], 'depends_on': ['1'], 'requirement_ids': [self.ids[1]]}],
            'parent_requirement_ids': []}
        records = mini.ledger_requirements(ledger)
        self.plan['children'][0]['verification_obligations'] = [
            {'requirement_id': self.ids[0], 'source_text': records[0]['text'], 'kind': 'file_exists', 'target': name}
            for name in ['index.html', 'style.css', 'app.js']]
        self.plan['children'][1]['verification_obligations'] = [behavior_fixtures.scenario(self.ids[1], records[1]['text'])]
        self.plan['parent_verification_obligations'] = []

    def decompose(self, plan=None):
        with patch.object(mini, 'structured_model_call', return_value=plan or self.plan):
            return mini.decompose_task(self.parent, self.contract, mini.inspect_repository())

    def test_complete_allocation_is_preserved_on_children_and_parent(self):
        children = self.decompose()
        self.assertEqual([c.get('requirement_ids') for c in children], [[self.ids[0]], [self.ids[1]]])
        self.assertTrue(self.parent.get('requirement_ownership', {}).get('valid'))
        self.assertEqual(children[1]['scope_hint'], ['app.js'])
        self.assertEqual(children[1]['depends_on'], ['1'])

    def test_missing_requirement_rejects_plan_before_dispatch(self):
        self.plan['children'][1]['requirement_ids'] = []
        self.assertEqual(self.decompose(), [])
        self.assertEqual(self.parent.get('ownership_failure', {}).get('failure_type'), 'REQUIREMENT_OWNERSHIP_INCOMPLETE')

    def test_unknown_source_id_cannot_replace_missing_source_requirement(self):
        self.plan['children'][1]['requirement_ids'] = ['INVENTED']
        self.assertEqual(self.decompose(), [])

    def test_required_file_needs_real_child_implementation_scope(self):
        self.plan['children'][0]['scope_hint'] = ['index.html', 'style.css']
        self.plan['children'][1]['scope_hint'] = ['style.css']
        self.assertEqual(self.decompose(), [])

    def test_parent_allocation_cannot_hide_unowned_required_file(self):
        self.plan['children'][0]['requirement_ids'] = []
        self.plan['parent_requirement_ids'] = [self.ids[0]]
        self.assertEqual(self.decompose(), [])

    def test_explicit_empty_outer_scope_stays_empty(self):
        self.contract['allowed_mutation_paths'] = []
        self.assertEqual(self.decompose(), [])

    def test_normalized_outer_paths_preserve_existing_permission(self):
        self.contract['allowed_mutation_paths'] = ['./index.html', './style.css', './app.js']
        self.assertEqual(len(self.decompose()), 2)

    def test_oracle_cannot_inspect_predecessor_without_dependency(self):
        self.plan['children'][1]['depends_on'] = []
        self.assertEqual(self.decompose(), [])
        self.assertEqual(self.parent['oracle_failure']['failure_type'], 'VERIFICATION_OBLIGATION_UNCOVERED')

    def test_invalid_metadata_cannot_be_replaced_by_unbound_fallback(self):
        self.plan.pop('parent_requirement_ids')
        for child in self.plan['children']:
            child.pop('requirement_ids')
        self.assertEqual(self.decompose(), [])

    def test_dispatch_seam_rejects_injected_unowned_children(self):
        children = [mini.make_task(str(i), c['goal'], 1, 'ROOT', c['done_when'], c['scope_hint'])
                    for i, c in enumerate(self.plan['children'], 1)]
        with patch.object(mini, 'execute_leaf', side_effect=AssertionError('Unowned child dispatched')):
            result = mini._execute_children(self.parent, children, 0, self.contract, {},
                mini.inspect_repository(), '', [],
                fit_decider=lambda *a, **k: {'decision': 'execute'}, aggregator=None,
                leaf_executor=lambda *a, **k: self.fail('Unowned child dispatched'))
        self.assertEqual(result['failure_type'], 'REQUIREMENT_OWNERSHIP_INCOMPLETE')


if __name__ == '__main__':
    unittest.main()
