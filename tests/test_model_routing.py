"""Offline routing, interactive selection and local/remote qualification."""
from dataclasses import replace
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from hivo import model_configuration as ui
from hivo import provider_preflight as preflight
from hivo.http_client import JsonResponse
from hivo.model_routing import RoleRouter, RoutingConfig, RoutingPolicy, role_key
from hivo.providers import ModelSelection, ModelInfo, ProviderClient, ProviderFailure


class ModelRoutingTests(unittest.TestCase):
    def setUp(self):
        self.orch = ModelSelection('openrouter', 'vendor/planner:free', context=16384, max_output=4096)
        self.worker = ModelSelection('ollama', 'any-worker:small', reasoning='off')
        self.oi = ModelInfo('openrouter', self.orch.model, frozenset({'completion', 'tools', 'json', 'schema'}), 32768, zero_pricing=True, remote=True)
        self.wi = ModelInfo('ollama', self.worker.model, frozenset({'completion', 'tools'}), 32768, (False, True), size_bytes=100)
        self.client = ProviderClient(environ={}, request_budget=40)
        self.client.inspect = Mock(side_effect=lambda s: self.oi if s.provider == 'openrouter' else self.wi)
        self.client.authenticate = Mock(return_value={'authenticated': True})
        self.client.get = Mock(return_value=JsonResponse(200, '{"models":[]}'))
        self.router = RoleRouter(RoutingConfig(self.orch, self.worker), self.client)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.resources = lambda: {'total_system_ram_bytes': 16 * 2**30, 'available_system_ram_bytes': 8 * 2**30}

    def args(self, **kwargs):
        values = dict(model=None, model_config=None, orchestrator_model=None, worker_model=None, role_model=None,
                      worker_context=4096, worker_output=1024, orchestrator_context=16384, orchestrator_output=4096,
                      worker_thinking=None, model_request_budget=40, confirm_models=False, approve_free_cloud=False,
                      allow_paid_inference=False)
        return SimpleNamespace(**dict(values, **kwargs))

    def test_explicit_role_assignment_and_aliases(self):
        c = self.router.config
        for role in ['Builder', 'Repairer', 'Falsifier', 'Worker']:
            self.assertEqual(c.selection(role), self.worker)
        for role in ['Coordinator', 'MissionCompiler', 'RequirementExtractor', 'ImpactPlanner', 'Quality Review']:
            self.assertEqual(c.selection(role), self.orch)
        with self.assertRaisesRegex(ProviderFailure, 'UNASSIGNED'):
            c.selection('InventedAgent')

    def test_explicit_role_override_does_not_change_other_roles(self):
        c = RoutingConfig(self.orch, self.worker, overrides={'Falsifier': self.orch})
        self.assertEqual(c.selection('Falsifier'), self.orch)
        self.assertEqual(c.selection('Builder'), self.worker)

    def test_all_local_and_cloud_only_same_model_configs(self):
        self.assertEqual(RoutingConfig(self.worker, self.worker).selection('Coordinator'), self.worker)
        self.assertEqual(RoutingConfig(self.orch, self.orch).selection('Builder'), self.orch)

    def test_config_roundtrip_has_secret_reference_only(self):
        value = self.router.config.to_dict()
        self.assertEqual(RoutingConfig.from_dict(value).selection('Builder'), self.worker)
        self.assertIn('auth_env', value['orchestrator'])
        self.assertNotIn('api_key', json.dumps(value))
        value['orchestrator']['api_key'] = 'unit-only-placeholder'
        with self.assertRaisesRegex(ProviderFailure, 'SECRET_FIELDS'):
            RoutingConfig.from_dict(value)

    def test_unqualified_router_cannot_generate(self):
        with self.assertRaisesRegex(ProviderFailure, 'NOT_PREFLIGHTED'):
            self.router.chat('Builder', [])

    def test_model_override_cannot_redirect_role(self):
        self.router.prepare()
        self.router.qualified = True
        with self.assertRaisesRegex(ProviderFailure, 'OVERRIDE_VIOLATES'):
            self.router.chat('Builder', [], model_override=self.orch.model)

    def test_routed_calls_use_both_providers_and_preserve_role_context(self):
        self.router.prepare()
        self.router.qualified = True
        self.client.chat = Mock(return_value={'role': 'assistant', 'content': 'OK'})
        self.router.chat('Coordinator', [{'role': 'user', 'content': 'Plan'}])
        self.router.chat('Builder', [{'role': 'user', 'content': 'Implement'}])
        self.assertEqual([c.args[0] for c in self.client.chat.call_args_list], [self.orch, self.worker])
        self.assertEqual(RoutingPolicy(self.router.config).context_window('Builder'), 4096)

    def test_dynamic_menu_lists_five_local_choices(self):
        names = [f'local-{i}:latest' for i in range(5)]
        self.client.catalog = Mock(return_value=[{'name': n} for n in names])
        self.client.inspect = Mock(side_effect=lambda s: replace(self.wi, model=s.model))
        answers = iter(['1', '5', 'y'])
        output = []
        config = ui.configure(self.args(), self.client, interactive=True, input_fn=lambda _: next(answers), print_fn=output.append)
        self.assertEqual(config.worker.model, names[4])
        self.assertTrue(any(names[4] in line for line in output))
        self.assertTrue(any('OpenRouter not configured' in line for line in output))
        self.assertEqual(self.client.requests, 0)

    def test_menu_decline_does_not_start_inference(self):
        self.client.catalog = Mock(return_value=[{'name': 'one:latest'}])
        self.client.inspect = Mock(return_value=replace(self.wi, model='one:latest'))
        answers = iter(['1', '1', 'n'])
        with self.assertRaisesRegex(ProviderFailure, 'NOT_CONFIRMED'):
            ui.configure(self.args(), self.client, interactive=True, input_fn=lambda _: next(answers), print_fn=lambda _: None)
        self.assertEqual(self.client.requests, 0)

    def test_noninteractive_cloud_requires_explicit_authorization(self):
        args = self.args(orchestrator_model=self.orch.reference, worker_model=self.worker.reference, confirm_models=True)
        with self.assertRaisesRegex(ProviderFailure, 'CLOUD_INFERENCE_APPROVAL_REQUIRED'):
            ui.configure(args, self.client, interactive=False, print_fn=lambda _: None)
        self.client.get.assert_not_called()

    def test_legacy_model_shorthand_assigns_exact_id_to_all_roles(self):
        config = ui.configure(self.args(model='any-installed:tag'), self.client, interactive=False, print_fn=lambda _: None)
        self.assertEqual(config.orchestrator.model, 'any-installed:tag')
        self.assertEqual(config.worker, config.orchestrator)

    def test_conflicting_legacy_and_explicit_groups_are_rejected(self):
        with self.assertRaisesRegex(ProviderFailure, 'CONFLICTING'):
            ui.configure(self.args(model='a', worker_model='ollama:b', orchestrator_model='ollama:c'), self.client,
                         interactive=False, print_fn=lambda _: None)

    def test_cloud_only_does_not_require_local_model_loading_ram(self):
        router = RoleRouter(RoutingConfig(self.orch, self.orch), self.client)
        self.client.chat = Mock(side_effect=[{'content': '{"ok":true}'},
            {'content': '', 'tool_calls': [{'function': {'name': 'hivo_capability_probe', 'arguments': {'ok': True}}}]}])
        host_runner = Mock(side_effect=AssertionError('Local weights must not be loaded'))
        actual = preflight.qualify(router, self.root,
            resource_sampler=lambda: {'available_system_ram_bytes': 1024 * 2**20}, host_runner=host_runner)
        self.assertTrue(actual['passed'], actual)
        host_runner.assert_not_called()
        self.assertTrue(router.qualified)

    def test_controller_memory_floor_still_applies_to_cloud(self):
        actual = preflight.qualify(self.router, self.root, resource_sampler=lambda: {'available_system_ram_bytes': 256 * 2**20})
        self.assertFalse(actual['passed'])
        self.assertEqual(actual['failure_reason'], 'CRITICAL_MEMORY_HEADROOM')
        self.client.inspect.assert_not_called()

    def test_cold_local_estimate_blocks_before_canaries(self):
        router = RoleRouter(RoutingConfig(self.worker, self.worker), self.client)
        self.client.inspect = Mock(return_value=replace(self.wi, size_bytes=4 * 2**30))
        host_runner = Mock()
        actual = preflight.qualify(router, self.root, resource_sampler=lambda: {'available_system_ram_bytes': 2 * 2**30}, host_runner=host_runner)
        self.assertEqual(actual['failure_reason'], 'INSUFFICIENT_COLD_LOAD_HEADROOM_ESTIMATE')
        host_runner.assert_not_called()

    def test_loaded_selected_model_is_not_charged_twice(self):
        router = RoleRouter(RoutingConfig(self.worker, self.worker), self.client)
        self.client.inspect = Mock(return_value=replace(self.wi, size_bytes=4 * 2**30))
        self.client.get.return_value = JsonResponse(200, '{"models":[{"name":"any-worker:small"}]}')
        self.client.chat = Mock(side_effect=[{'content': '{"ok":true}'},
            {'tool_calls': [{'function': {'name': 'hivo_capability_probe', 'arguments': {'ok': True}}}]}])
        actual = preflight.qualify(router, self.root, resource_sampler=lambda: {'available_system_ram_bytes': 2 * 2**30},
                                  host_runner=Mock(return_value={'passed': True}))
        self.assertTrue(actual['passed'], actual)

    def test_failed_local_host_gate_is_not_bypassed(self):
        router = RoleRouter(RoutingConfig(self.worker, self.worker), self.client)
        self.client.chat = Mock()
        actual = preflight.qualify(router, self.root, resource_sampler=self.resources,
            host_runner=Mock(return_value={'passed': False, 'report': {'failure_reason': 'CRITICAL_MEMORY_HEADROOM'}}))
        self.assertEqual(actual['failure_reason'], 'CRITICAL_MEMORY_HEADROOM')
        self.client.chat.assert_not_called()
        self.assertFalse(router.qualified)

    def test_unselected_resident_model_is_not_stopped_or_ignored(self):
        router = RoleRouter(RoutingConfig(self.worker, self.worker), self.client)
        self.client.get.return_value = JsonResponse(200, '{"models":[{"name":"another-model:large"}]}')
        actual = preflight.qualify(router, self.root, resource_sampler=self.resources)
        self.assertEqual(actual['failure_reason'], 'UNSELECTED_LOCAL_MODEL_RESIDENT')

    def test_invalid_structured_canary_is_not_qualification(self):
        router = RoleRouter(RoutingConfig(self.orch, self.orch), self.client)
        self.client.chat = Mock(return_value={'content': '{partial'})
        actual = preflight.qualify(router, self.root, resource_sampler=self.resources)
        self.assertEqual(actual['failure_reason'], 'STRUCTURED_CANARY_FAILED')

    def test_failed_tool_canary_is_not_qualification(self):
        router = RoleRouter(RoutingConfig(self.orch, self.orch), self.client)
        self.client.chat = Mock(side_effect=[{'content': '{"ok":true}'}, {'content': 'I would call the tool'}])
        actual = preflight.qualify(router, self.root, resource_sampler=self.resources)
        self.assertEqual(actual['failure_reason'], 'TOOL_CANARY_FAILED')

    def test_previous_host_evidence_is_never_overwritten(self):
        marker = self.root / '.agent_host_preflight.json'
        marker.write_bytes(b'previous evidence')
        router = RoleRouter(RoutingConfig(self.orch, self.orch), self.client)
        self.client.chat = Mock(side_effect=[{'content': '{"ok":true}'},
            {'tool_calls': [{'function': {'name': 'hivo_capability_probe', 'arguments': {'ok': True}}}]}])
        self.assertTrue(preflight.qualify(router, self.root, resource_sampler=self.resources)['passed'])
        self.assertEqual(marker.read_bytes(), b'previous evidence')
        self.assertEqual(len(list((self.root / '.agent_evidence/provider-preflight').glob('*/result.json'))), 1)


if __name__ == '__main__': unittest.main()
