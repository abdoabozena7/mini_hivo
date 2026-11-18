import json
import unittest
from unittest.mock import patch

import mini
from hivo.http_client import JsonResponse


class LocalModelTransportTimeoutTests(unittest.TestCase):
    def setUp(self):
        mini.WORKSPACE = None
        mini.reset_run('recursive')
        mini.MODEL = 'gemma4:e4b'

    def test_local_request_gets_longer_finite_timeout_without_payload_changes(self):
        response = JsonResponse(200, json.dumps({'message': {'role': 'assistant', 'content': '{}'}}))
        with patch.object(mini, 'http_post_json', return_value=response) as request:
            mini.ask_ollama([{'role': 'user', 'content': 'Specify the application.'}], tools=None,
                            role='Specifier', provider_retries=0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(request.call_args.kwargs['timeout'], 600)
        payload = request.call_args.kwargs['payload']
        self.assertEqual(payload['model'], 'gemma4:e4b')
        self.assertEqual(payload['options']['num_ctx'], 4096)
        self.assertEqual(payload['options']['num_predict'], 1536)
        self.assertFalse(payload['stream'])
        self.assertFalse(payload['think'])

    def test_timeout_still_fails_without_bypassing_provider_gate(self):
        with patch.object(mini, 'http_post_json', side_effect=mini.HttpTransportError('timed out')) as request:
            with self.assertRaises(mini.ProviderError):
                mini.ask_ollama([{'role': 'user', 'content': 'Specify the application.'}], tools=None,
                                role='Specifier', provider_retries=0)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(mini.RUN['ollama_timeout_failures'], 1)
        self.assertFalse(mini.FORCE_CPU_FOR_RUN)
