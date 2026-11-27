"""Existing public CLI seams must accept general explicit selections."""
import unittest
import io
from unittest.mock import patch
import mini
from types import SimpleNamespace
from hivo.model_routing import RoutingConfig, RoleRouter
from hivo.providers import ModelSelection, ModelInfo


class ProviderCLIMigrationTests(unittest.TestCase):
    def test_legacy_model_accepts_arbitrary_installed_id(self):
        with patch('sys.argv', ['mini.py', '--model', 'any-installed-model:small']):
            self.assertEqual(mini.parse_args().model, 'any-installed-model:small')

    def test_distinct_provider_roles_are_expressible(self):
        with patch('sys.argv', ['mini.py', '--orchestrator-model', 'openrouter:vendor/planner:free',
                               '--worker-model', 'ollama:local-worker:small']):
            args = mini.parse_args()
            self.assertEqual(args.orchestrator_model, 'openrouter:vendor/planner:free')
            self.assertEqual(args.worker_model, 'ollama:local-worker:small')

    def test_invalid_cli_does_not_echo_accidentally_pasted_secret(self):
        output = io.StringIO()
        with patch('sys.argv', ['mini.py', '--api-key', 'unit-secret-placeholder']), patch('sys.stderr', output):
            with self.assertRaises(SystemExit): mini.parse_args()
        self.assertNotIn('unit-secret-placeholder', output.getvalue())

    def test_qualification_uses_effective_worker_when_all_worker_roles_overridden(self):
        unused = ModelSelection('ollama', 'unused-default:small')
        active = ModelSelection('ollama', 'active-worker:small')
        config = RoutingConfig(active, unused, overrides={r: active for r in ['Builder', 'Falsifier', 'Repairer']})
        router = RoleRouter(config)
        router.infos = {active: ModelInfo('ollama', active.model, frozenset({'completion', 'tools'}), 4096)}
        names = ['PROVIDER_ROUTER', 'MODEL_POLICY', 'MODEL', 'MODEL_TASK_CAPACITY', 'MODEL_CAPABILITIES',
                 'VISION_MODEL', 'ROUTER_MODEL', 'FALLBACK_MODEL', 'CONTEXT_LIMIT_TOKENS']
        with patch.multiple(mini, **{n: getattr(mini, n) for n in names}), \
             patch.object(mini.provider_preflight, 'qualify', return_value={'passed': True}):
            self.assertTrue(mini.qualify_model_routing(router, '.')['passed'])
            self.assertEqual(mini.MODEL, active.model)
            self.assertEqual(mini.MODEL_CAPABILITIES, {'completion', 'tools'})


if __name__ == '__main__': unittest.main()
