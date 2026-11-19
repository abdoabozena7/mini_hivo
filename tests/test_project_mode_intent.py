"""Offline regressions for request intent versus application feature verbs."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from hivo import project_understanding as understanding


PROMPT = Path(__file__).with_name('fixtures').joinpath(
    'new_application_requirements.txt',
).read_text(encoding='utf-8')


class ProjectModeIntentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.old_workspace = mini.WORKSPACE
        self.addCleanup(setattr, mini, 'WORKSPACE', self.old_workspace)
        mini.WORKSPACE = self.workspace
        mini.reset_run('recursive')
        for name in ('ask_ollama', 'structured_model_call'):
            blocker = patch.object(mini, name, side_effect=AssertionError('live provider forbidden'))
            blocker.start()
            self.addCleanup(blocker.stop)

    def contract(self, raw):
        ledger = mini.extract_source_requirement_ledger(raw, use_model=False)
        contract = mini.normalize_goal_contract(
            raw, mini._deterministic_contract_from_ledger(raw, ledger),
            source_ledger=ledger, confirmed=[], derived=[],
            clarification_questions=[], clarification_answers=[],
        )
        contract['source_contract'] = mini.source_contract_from_ledger(raw, ledger)
        return contract

    def stage2(self, raw):
        contract = self.contract(raw)
        before = copy.deepcopy(contract['source_requirement_ledger'])
        specification = {key: [] for key in mini._PROJECT_SPECIFICATION_FIELDS}
        specification.update(root_goal=raw, acceptance_criteria=['requested behavior is verified'])
        result = mini.prepare_stage2_context(
            raw, contract, repo_snapshot=mini.inspect_repository(), interactive=False,
            supplied_contract=True, specification_override=specification,
            recon_structured_call=lambda *_args: {'paths': []}, terminal_available=False,
        )
        return result, contract, before

    def test_original_request_is_new_project_in_empty_workspace(self):
        result = mini.classify_project_mode(PROMPT)
        self.assertEqual(result['inventory']['status'], mini.REPOSITORY_EMPTY)
        self.assertEqual(result['project_mode'], mini.NEW_PROJECT)

    def test_feature_operations_do_not_override_construction_intent(self):
        requests = (
            'Build a recipe application. Allow users to delete recipes.',
            'Create a photo website. Users can replace images and update captions.',
            'Develop a contact manager. Remove contacts and change their names.',
            'Please make a dashboard. Display the current values and update them.',
            'Build a notes application. Allow users to edit notes in the current session.',
            'Build a reporting application. Allow users to fix incorrectly entered descriptions.',
        )
        for raw in requests:
            with self.subTest(request=raw):
                self.assertEqual(mini.classify_project_mode(raw)['project_mode'], mini.NEW_PROJECT)

    def test_runtime_metadata_is_not_an_existing_application(self):
        (self.workspace / '.agent_host_preflight.json').write_text('{}')
        (self.workspace / '.hivo').mkdir()
        (self.workspace / '.hivo' / 'state.json').write_text('{}')
        self.assertEqual(mini.classify_project_mode(PROMPT)['project_mode'], mini.NEW_PROJECT)

    def test_real_source_files_take_precedence_over_construction_intent(self):
        (self.workspace / 'app.js').write_text('export const app = {};')
        for raw in (PROMPT, 'Build an application from scratch.'):
            with self.subTest(request=raw):
                self.assertEqual(mini.classify_project_mode(raw)['project_mode'], mini.EXISTING_PROJECT)

    def test_missing_existing_targets_are_not_reinterpreted_as_greenfield(self):
        requests = (
            'Modify the existing SettingsService.',
            'Add to the current application.',
            'Create a report, then fix the existing parser.',
            'Build an empty workspace report, then modify the current service.',
            'Create a report, then modify parser.py.',
            'Build a dashboard and update src/auth.js.',
            'Create a report, then refactor the parser.',
            'Build a status page and fix authentication.',
        )
        for raw in requests:
            with self.subTest(request=raw):
                self.assertEqual(mini.classify_project_mode(raw)['project_mode'], mini.EXISTING_PROJECT)

    def test_no_construction_intent_keeps_existing_modification_behavior(self):
        for raw in ('Fix authentication.', 'Update the login flow.', 'Delete the old implementation.'):
            with self.subTest(request=raw):
                self.assertEqual(mini.classify_project_mode(raw)['project_mode'], mini.EXISTING_PROJECT)

    def test_unavailable_or_truncated_inventory_does_not_establish_empty_workspace(self):
        for inventory in (
            {'status': mini.REPOSITORY_EVIDENCE_UNAVAILABLE, 'files': []},
            {'status': mini.REPOSITORY_EMPTY, 'files': [], 'truncated': True},
        ):
            with self.subTest(inventory=inventory):
                result = understanding.classify_project_mode(PROMPT, inventory)
                self.assertEqual(result['project_mode'], mini.EXISTING_PROJECT)

    def test_original_request_prepares_stage2_without_dropping_requirements(self):
        with patch.object(mini, 'run_repository_reconnaissance',
                          side_effect=AssertionError('greenfield should skip existing-project scout')):
            result, contract, before = self.stage2(PROMPT)
        self.assertEqual(result['status'], 'ready')
        self.assertEqual(mini.RUN['project_mode'], mini.NEW_PROJECT)
        self.assertIn('TASK_BRAIN', mini.RUN['control_flow'])
        self.assertEqual(len(result['task_brain']['source_requirement_ids']), 11)
        self.assertEqual(contract['source_requirement_ledger'], before)
        self.assertEqual(len(mini.ledger_requirements(before)), 11)
        self.assertEqual(understanding.inventory_repository(self.workspace)['files'], [])

    def test_existing_request_still_requires_repository_evidence(self):
        result, _contract, _before = self.stage2('Modify the existing SettingsService.')
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(result['project_mode'], mini.EXISTING_PROJECT)
        self.assertEqual(result['orchestration_failure'], mini.REPOSITORY_EMPTY)
        self.assertEqual(understanding.inventory_repository(self.workspace)['files'], [])

    def test_populated_workspace_still_runs_read_only_reconnaissance(self):
        path = self.workspace / 'app.js'
        contents = b'export function render() { return "ready"; }'
        path.write_bytes(contents)
        raw = 'Update the current render function in app.js.'
        classification = mini.classify_project_mode(raw)
        recon = mini.run_repository_reconnaissance(
            raw, self.contract(raw), inventory=classification['inventory'], use_model_scout=False,
        )
        self.assertEqual(classification['project_mode'], mini.EXISTING_PROJECT)
        self.assertEqual(recon['status'], mini.REPOSITORY_RECONNAISSANCE_COMPLETE)
        self.assertTrue(recon['read_only'])
        self.assertTrue(recon['evidence'])
        self.assertEqual(path.read_bytes(), contents)


if __name__ == '__main__':
    unittest.main()
