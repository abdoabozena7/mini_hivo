"""Offline provider contracts; all credentials/data are synthetic test values."""
import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import Mock

from hivo.http_client import JsonResponse
from hivo.providers import ModelInfo, ModelSelection, ProviderClient, ProviderFailure, openai_messages, parse_reference


def response(body, status=200): return JsonResponse(status, json.dumps(body))


class ProviderTests(unittest.TestCase):
    def setUp(self):
        self.local = ModelSelection('ollama', 'local-worker:small', reasoning='off')
        self.cloud = ModelSelection('openrouter', 'vendor/planner:free', context=8192)
        self.li = ModelInfo('ollama', self.local.model, frozenset({'completion', 'tools', 'vision', 'thinking'}), 32768, (False, True))
        self.ci = ModelInfo('openrouter', self.cloud.model, frozenset({'completion', 'tools', 'json', 'schema', 'thinking'}), 32768, zero_pricing=True, remote=True)
        self.messages = [{'role': 'user', 'content': 'Return a bounded result'}]
        self.tool = {'type': 'function', 'function': {'name': 'propose_file', 'parameters': {'type': 'object'}}}
        self.post, self.get = Mock(), Mock()
        self.client = ProviderClient(post=self.post, get=self.get, environ={'OPENROUTER_API_KEY': 'unit-only-not-a-key'},
            cloud_catalog_authorized=True, cloud_inference_authorized=True, sleep=Mock())

    def local_body(self, **extra):
        return {'model': self.local.model, 'done': True, 'done_reason': 'stop',
                'message': {'role': 'assistant', 'content': 'OK'}, **extra}

    def cloud_body(self, **extra):
        return {'model': self.cloud.model, 'choices': [{'finish_reason': 'stop',
                 'message': {'role': 'assistant', 'content': 'OK'}}], 'usage': {'cost': 0}, **extra}

    def test_local_payload_uses_selected_context_and_supported_thinking(self):
        self.post.return_value = response(self.local_body())
        self.assertEqual(self.client.chat(self.local, self.li, self.messages)['content'], 'OK')
        payload = self.post.call_args.kwargs['payload']
        self.assertEqual(payload['model'], self.local.model)
        self.assertEqual(payload['options']['num_ctx'], 4096)
        self.assertIs(payload['think'], False)
        self.assertNotIn('Authorization', self.post.call_args.kwargs['headers'])

    def test_default_reasoning_is_not_forced_to_false(self):
        self.post.return_value = response(self.local_body())
        self.client.chat(replace(self.local, reasoning=None), self.li, self.messages)
        self.assertNotIn('think', self.post.call_args.kwargs['payload'])

    def test_free_only_payload_has_exact_model_and_no_fallback(self):
        self.post.return_value = response(self.cloud_body())
        self.client.chat(self.cloud, self.ci, self.messages, response_format={'type': 'object'})
        payload = self.post.call_args.kwargs['payload']
        self.assertEqual(payload['model'], 'vendor/planner:free')
        self.assertNotIn('models', payload)
        self.assertFalse(payload['provider']['allow_fallbacks'])
        self.assertTrue(payload['provider']['require_parameters'])
        self.assertTrue(all(x == 0 for x in payload['provider']['max_price'].values()))
        self.assertEqual(payload['response_format']['type'], 'json_schema')

    def test_paid_model_rejected_before_request(self):
        with self.assertRaisesRegex(ProviderFailure, 'FREE_ONLY_POLICY'):
            self.client.chat(replace(self.cloud, model='vendor/planner'), replace(self.ci, model='vendor/planner'), self.messages)
        self.post.assert_not_called()

    def test_zero_pricing_must_be_verified(self):
        with self.assertRaisesRegex(ProviderFailure, 'FREE_ONLY_POLICY'):
            self.client.chat(self.cloud, replace(self.ci, zero_pricing=False), self.messages)
        self.post.assert_not_called()

    def test_paid_mode_requires_separate_authorization(self):
        with self.assertRaisesRegex(ProviderFailure, 'PAID_INFERENCE_APPROVAL_REQUIRED'):
            self.client.chat(replace(self.cloud, free_only=False), self.ci, self.messages)

    def test_missing_key_and_no_cloud_consent_stop_before_http(self):
        self.client.environ = {}
        with self.assertRaisesRegex(ProviderFailure, 'MISSING_API_KEY'):
            self.client.chat(self.cloud, self.ci, self.messages)
        self.client.cloud_inference_authorized = False
        with self.assertRaisesRegex(ProviderFailure, 'CLOUD_INFERENCE_APPROVAL_REQUIRED'):
            self.client.chat(self.cloud, self.ci, self.messages)
        self.post.assert_not_called()

    def test_catalog_needs_its_own_permission(self):
        self.client.cloud_catalog_authorized = False
        with self.assertRaisesRegex(ProviderFailure, 'CLOUD_CATALOG_APPROVAL_REQUIRED'):
            self.client.catalog('openrouter')
        self.get.assert_not_called()

    def test_http_errors_do_not_leak_response_or_credential(self):
        for status in [401, 402, 404, 429, 500]:
            with self.subTest(status=status):
                self.post.return_value = response({'error': 'unit-only-not-a-key raw sensitive error'}, status)
                with self.assertRaises(ProviderFailure) as caught:
                    self.client.chat(self.cloud, self.ci, self.messages)
                self.assertEqual(caught.exception.status, status)
                self.assertNotIn('unit-only-not-a-key', str(caught.exception))
                self.assertNotIn('raw sensitive', str(caught.exception))

    def test_timeout_is_sanitized_and_bounded(self):
        self.post.side_effect = TimeoutError('unit-only-not-a-key')
        with self.assertRaisesRegex(ProviderFailure, '^PROVIDER_UNREACHABLE$'):
            self.client.chat(self.cloud, self.ci, self.messages)
        self.assertEqual(self.post.call_count, 1)

    def test_safe_retry_keeps_exact_model_and_policy(self):
        self.post.side_effect = [response({'error': 'busy'}, 500), response(self.cloud_body())]
        self.client.chat(replace(self.cloud, retries=1), self.ci, self.messages)
        self.assertEqual(self.post.call_count, 2)
        self.assertEqual(self.post.call_args_list[0].kwargs['payload'], self.post.call_args_list[1].kwargs['payload'])

    def test_retry_budget_has_hard_limit(self):
        with self.assertRaisesRegex(ProviderFailure, 'INVALID_RETRY'):
            replace(self.cloud, retries=10)

    def test_actual_paid_identity_is_rejected_not_rewritten(self):
        self.post.return_value = response(self.cloud_body(model='vendor/planner'))
        with self.assertRaisesRegex(ProviderFailure, 'RESPONSE_MODEL_IDENTITY_MISMATCH'):
            self.client.chat(self.cloud, self.ci, self.messages)
        self.assertTrue(self.client.blocked)

    def test_reported_nonzero_cost_quarantines_client(self):
        self.post.return_value = response(self.cloud_body(usage={'cost': 0.01}))
        with self.assertRaisesRegex(ProviderFailure, 'REPORTED_COST'):
            self.client.chat(self.cloud, self.ci, self.messages)
        self.assertTrue(self.client.blocked)

    def test_tools_normalize_json_arguments_without_reasoning_instructions(self):
        message = {'role': 'assistant', 'content': '', 'reasoning': 'private reasoning',
                   'tool_calls': [{'id': 'call-a', 'type': 'function', 'function': {'name': 'propose_file', 'arguments': '{"path":"a.py"}'}}]}
        self.post.return_value = response(self.cloud_body(choices=[{'finish_reason': 'tool_calls', 'message': message}]))
        actual = self.client.chat(self.cloud, self.ci, self.messages, tools=[self.tool])
        self.assertEqual(actual['tool_calls'][0]['function']['arguments'], {'path': 'a.py'})
        self.assertNotIn('reasoning', actual)
        self.assertNotIn('private reasoning', json.dumps(self.client.last_diagnostics))

    def test_tool_json_must_be_complete_object(self):
        for args in ['{"path":', '[1]', 'null', None]:
            self.post.return_value = response(self.local_body(message={'role': 'assistant', 'content': '',
                'tool_calls': [{'function': {'name': 'propose_file', 'arguments': args}}]}))
            with self.subTest(args=args), self.assertRaises(ProviderFailure):
                self.client.chat(self.local, self.li, self.messages, tools=[self.tool])

    def test_unoffered_tool_cannot_escape_provider_normalization(self):
        self.post.return_value = response(self.local_body(message={'role': 'assistant', 'content': '',
            'tool_calls': [{'function': {'name': 'delete_everything', 'arguments': {}}}]}))
        with self.assertRaisesRegex(ProviderFailure, 'TOOL_NOT_OFFERED'):
            self.client.chat(self.local, self.li, self.messages, tools=[self.tool])

    def test_truncation_is_never_usable_plan(self):
        self.post.return_value = response(self.cloud_body(choices=[{'finish_reason': 'length', 'message': {'role': 'assistant', 'content': '{"children":['}}]))
        with self.assertRaisesRegex(ProviderFailure, 'TRUNCATED'):
            self.client.chat(self.cloud, self.ci, self.messages)

    def test_thinking_only_response_is_not_a_final_answer(self):
        self.post.return_value = response(self.local_body(message={'role': 'assistant', 'content': '', 'thinking': 'Reasoning only'}))
        with self.assertRaisesRegex(ProviderFailure, 'EMPTY_FINAL'):
            self.client.chat(replace(self.local, reasoning=None), self.li, self.messages)

    def test_reasoning_off_must_actually_be_honored(self):
        self.post.return_value = response(self.local_body(message={'role': 'assistant', 'content': 'OK', 'thinking': 'still thinking'}))
        with self.assertRaisesRegex(ProviderFailure, 'REASONING_OFF_NOT_HONORED'):
            self.client.chat(self.local, self.li, self.messages)

    def test_unsupported_reasoning_continuation_is_not_silently_dropped(self):
        message = {'role': 'assistant', 'content': '', 'reasoning_details': [{'type': 'reasoning.encrypted', 'data': 'fixture-opaque'}],
                   'tool_calls': [{'id': 'call-a', 'function': {'name': 'propose_file', 'arguments': '{}'}}]}
        self.post.return_value = response(self.cloud_body(choices=[{'finish_reason': 'tool_calls', 'message': message}]))
        with self.assertRaisesRegex(ProviderFailure, 'UNSUPPORTED_REASONING_TOOL_CONTINUATION'):
            self.client.chat(self.cloud, self.ci, self.messages, tools=[self.tool])

    def test_capability_mismatch_stops_before_http(self):
        with self.assertRaisesRegex(ProviderFailure, 'CAPABILITY'):
            self.client.chat(self.local, replace(self.li, capabilities=frozenset({'completion'})), self.messages, tools=[self.tool])
        self.post.assert_not_called()

    def test_unknown_thinking_controls_are_not_guessed_from_name(self):
        with self.assertRaisesRegex(ProviderFailure, 'REASONING_CONTROL'):
            self.client.chat(self.local, replace(self.li, thinking_values=()), self.messages)

    def test_context_budget_refuses_oversized_schema_and_prompt(self):
        with self.assertRaisesRegex(ProviderFailure, 'CONTEXT_BUDGET_EXCEEDED'):
            self.client.chat(self.local, self.li, [{'role': 'user', 'content': 'x' * 20000}])
        self.post.assert_not_called()

    def test_request_budget_stops_without_more_calls(self):
        self.client.request_budget = 1
        self.post.return_value = response(self.local_body())
        self.client.chat(self.local, self.li, self.messages)
        with self.assertRaisesRegex(ProviderFailure, 'BUDGET_EXHAUSTED'):
            self.client.chat(self.local, self.li, self.messages)
        self.assertEqual(self.post.call_count, 1)

    def test_local_catalog_has_dynamic_ids_and_metadata(self):
        names = ['model-a:small', 'model-b:large', 'model-c:latest', 'model-d:custom', 'model-e:latest']
        self.get.return_value = response({'models': [{'name': n, 'size': 100} for n in names]})
        self.assertEqual([r['name'] for r in self.client.catalog('ollama')], names)
        self.post.return_value = response({'capabilities': ['completion', 'tools'], 'model_info': {'arch.context_length': 8192}, 'thinking': {'values': [False], 'default': False}})
        info = self.client.inspect(replace(self.local, model=names[0]))
        self.assertEqual(info.context, 8192)
        self.assertIn('tools', info.capabilities)

    def test_empty_missing_and_unreachable_catalogs_do_not_fallback(self):
        self.get.return_value = response({'models': []})
        self.assertEqual(self.client.catalog('ollama'), [])
        with self.assertRaisesRegex(ProviderFailure, 'SELECTED_MODEL_UNAVAILABLE'):
            self.client.inspect(self.local)
        self.get.side_effect = OSError('private details')
        with self.assertRaisesRegex(ProviderFailure, '^PROVIDER_UNREACHABLE$'):
            self.client.catalog('ollama', refresh=True)

    def test_retry_after_longer_than_budget_is_respected_without_retry(self):
        self.post.return_value = JsonResponse(429, '{"error":"busy"}', {'Retry-After': '60'})
        with self.assertRaisesRegex(ProviderFailure, 'RATE_LIMIT_RETRY_DEFERRED'):
            self.client.chat(replace(self.cloud, retries=1), self.ci, self.messages)
        self.assertEqual(self.post.call_count, 1)

    def test_authentication_is_distinct_from_public_model_catalog(self):
        self.get.return_value = response({'data': {'is_free_tier': True}})
        self.assertTrue(self.client.authenticate(self.cloud)['authenticated'])
        self.assertTrue(self.get.call_args.args[0].endswith('/key'))
        self.get.return_value = response({'error': 'unit-only-not-a-key'}, 401)
        with self.assertRaisesRegex(ProviderFailure, 'AUTHENTICATION_FAILED'):
            self.client.authenticate(self.cloud)

    def test_cloud_capabilities_and_price_are_metadata_not_name_heuristics(self):
        self.get.return_value = response({'data': [{'id': self.cloud.model, 'context_length': 32768,
            'supported_parameters': ['tools', 'response_format', 'structured_outputs', 'reasoning'],
            'pricing': {'prompt': '0', 'completion': '0', 'request': '0'}}]})
        info = self.client.inspect(self.cloud)
        self.assertTrue(info.zero_pricing)
        self.assertIn('schema', info.capabilities)

    def test_secret_endpoints_and_remote_local_aliases_are_refused(self):
        with self.assertRaises(ProviderFailure): replace(self.cloud, endpoint='https://example.invalid/api')
        with self.assertRaises(ProviderFailure): replace(self.local, endpoint='http://example.invalid:11434')
        with self.assertRaisesRegex(ProviderFailure, 'SEPARATE_CLOUD_POLICY'):
            self.client.validate_assignment(self.local, replace(self.li, remote=True))

    def test_tool_result_ids_are_preserved_across_provider_boundary(self):
        messages = [{'role': 'assistant', 'content': '', 'tool_calls': [{'function': {'name': 'propose_file', 'arguments': {'path': 'a.py'}}}]},
                    {'role': 'tool', 'tool_name': 'propose_file', 'content': 'accepted'}]
        actual = openai_messages(messages)
        self.assertEqual(actual[0]['tool_calls'][0]['id'], actual[1]['tool_call_id'])
        self.assertIsInstance(actual[0]['tool_calls'][0]['function']['arguments'], str)
        self.assertNotIn('id', messages[0]['tool_calls'][0])

    def test_references_preserve_free_suffix_exactly(self):
        self.assertEqual(parse_reference('openrouter:vendor/planner:free').model, 'vendor/planner:free')
        with self.assertRaises(ProviderFailure): parse_reference('vendor/planner')

    def test_malformed_local_capabilities_fail_closed(self):
        self.get.return_value = response({'models': [{'name': self.local.model, 'size': 100}]})
        for malformed in ({'model_info': 'invalid'}, {'thinking': 'invalid'}, {'capabilities': 'completion'}):
            with self.subTest(metadata=malformed):
                self.post.return_value = response(malformed)
                with self.assertRaisesRegex(ProviderFailure, 'INVALID_CAPABILITY_METADATA'):
                    self.client.inspect(self.local)

    def test_malformed_cloud_capabilities_fail_closed(self):
        self.get.return_value = response({'data': [{'id': self.cloud.model, 'supported_parameters': [['tools']]}]})
        with self.assertRaisesRegex(ProviderFailure, 'INVALID_CAPABILITY_METADATA'):
            self.client.inspect(self.cloud)


if __name__ == '__main__': unittest.main()
