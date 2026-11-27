"""Offline parsed-option and provider-neutral reasoning contracts."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import mini
from hivo import model_configuration as ui
from hivo.model_routing import RoutingConfig
from hivo.providers import ModelSelection, ModelInfo, ProviderClient, ProviderFailure


class ConfigurationFixTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / 'models.json'
        local = ModelSelection('ollama', 'installed:custom')
        self.file.write_text(json.dumps(RoutingConfig(local, local).to_dict()), encoding='utf-8')
        self.client = ProviderClient(get=Mock(side_effect=AssertionError('No HTTP')),
                                     post=Mock(side_effect=AssertionError('No HTTP')), environ={})

    def configure(self, args):
        return ui.configure(args, self.client, interactive=False, print_fn=lambda _: None)

    def parse(self, options):
        with patch('sys.argv', ['mini.py'] + options):
            return mini.parse_args()

    def test_both_spellings_reject_explicit_model_settings_with_json(self):
        settings = {'worker-context': '4096', 'worker-output': '1024', 'orchestrator-context': '16384',
                    'orchestrator-output': '4096', 'worker-thinking': 'off',
                    'ollama-url': 'http://127.0.0.1:11434', 'model-request-budget': '40'}
        for flag, value in settings.items():
            for supplied in [[f'--{flag}', value], [f'--{flag}={value}']]:
                with self.subTest(options=supplied):
                    with patch('sys.argv', ['mini.py', '--model-config', str(self.file)] + supplied):
                        args = mini.parse_args()
                        with self.assertRaisesRegex(ProviderFailure, 'CONFIG_FILE_AND_CLI_SETTING_CONFLICT'):
                            self.configure(args)

    def test_parser_defaults_do_not_conflict_with_json(self):
        args = self.parse(['--model-config', str(self.file)])
        self.assertEqual(self.configure(args).worker.context, 4096)

    def test_programmatic_explicit_default_is_still_a_conflict(self):
        with patch('sys.argv', ['embedding-host']):
            with self.assertRaisesRegex(ProviderFailure, 'CONFIG_FILE_AND_CLI_SETTING_CONFLICT'):
                self.configure(SimpleNamespace(model_config=str(self.file), worker_context=4096))

    def test_programmatic_configuration_ignores_other_process_arguments(self):
        with patch('sys.argv', ['embedding-host', '--worker-context', '8192']):
            config = self.configure(SimpleNamespace(model_config=str(self.file)))
        self.assertEqual(config.worker.model, 'installed:custom')

    def test_explicit_default_provenance_can_be_supplied_programmatically(self):
        args = SimpleNamespace(model_config=str(self.file), worker_context=4096,
                               model_options_provided=frozenset())
        self.assertEqual(self.configure(args).worker.context, 4096)

    def test_parse_args_accepts_an_explicit_argument_vector(self):
        with patch('sys.argv', ['unrelated-host', '--worker-context', '8192']):
            args = mini.parse_args(['--model-config', str(self.file)])
            self.assertEqual(self.configure(args).worker.context, 4096)
        explicit = mini.parse_args(['--worker-context=4096'])
        self.assertEqual(explicit.model_options_provided, frozenset({'worker_context'}))

    def test_mixed_model_sources_still_fail_without_fallback(self):
        for extra in [['--model', 'installed:other'], ['--worker-model', 'ollama:a', '--orchestrator-model', 'ollama:b']]:
            args = mini.parse_args(['--model-config', str(self.file)] + extra)
            with self.assertRaisesRegex(ProviderFailure, 'CONFLICTING_MODEL_CONFIGURATION'):
                self.configure(args)

    def test_invalid_programmatic_provenance_is_rejected(self):
        for marker in ['worker_context', {'unknown'}, [{}]]:
            with self.assertRaisesRegex(ProviderFailure, 'INVALID_MODEL_OPTION_PROVENANCE'):
                self.configure(SimpleNamespace(model_config=str(self.file), model_options_provided=marker))

    def cloud_client(self, thinking):
        client = ProviderClient(get=Mock(side_effect=AssertionError('No HTTP')),
                                post=Mock(side_effect=AssertionError('No HTTP')), environ={},
                                cloud_catalog_authorized=True)
        client.catalog = Mock(side_effect=lambda provider: [] if provider == 'ollama' else [
            {'id': 'vendor/selected:free', 'pricing': {'prompt': '0', 'completion': '0'}}])
        caps = {'completion', 'tools', 'json'} | ({'thinking'} if thinking else set())
        client.inspect = Mock(return_value=ModelInfo('openrouter', 'vendor/selected:free', frozenset(caps),
                                                   32768, zero_pricing=True, remote=True))
        return client

    def test_cloud_requested_reasoning_is_preserved_when_supported(self):
        client = self.cloud_client(True)
        selection = ui._choose_model(client, 'worker', context=4096, output=1024, reasoning='off',
                                     input_fn=lambda _: '1', print_fn=lambda _: None)
        self.assertEqual(selection.reasoning, 'off')
        self.assertEqual(selection.model, 'vendor/selected:free')
        client.post.assert_not_called()

    def test_cloud_requested_reasoning_is_not_silently_dropped_when_unsupported(self):
        client = self.cloud_client(False); output = []
        with self.assertRaisesRegex(ProviderFailure, 'NO_COMPATIBLE_MODEL_CHOICES'):
            ui._choose_model(client, 'worker', context=4096, output=1024, reasoning='off',
                             input_fn=lambda _: '1', print_fn=output.append)
        self.assertTrue(any('REASONING_CONTROL_UNSUPPORTED' in line for line in output))
        client.post.assert_not_called()


if __name__ == '__main__': unittest.main()
