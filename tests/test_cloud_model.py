import unittest
from unittest.mock import Mock, patch

import mini
from hivo import host_preflight
from hivo.model_policy import SingleModelPolicy


class CloudModelTests(unittest.TestCase):
    def test_cli_accepts_cloud_model_and_every_role_uses_it(self):
        with patch("sys.argv", ["mini.py", "--model", "gpt-oss:20b-cloud"]):
            model = mini.parse_args().model
        policy = SingleModelPolicy(model)
        self.assertEqual(set(policy.role_models().values()), {model})
        with self.assertRaises(ValueError):
            policy.validate("gemma4:e4b")

    def test_catalog_includes_only_selected_cloud_model(self):
        response = Mock(status_code=200)
        response.json.return_value = {"models": [
            {"name": "gemma4:e4b"}, {"name": "gpt-oss:20b-cloud"},
            {"name": "gpt-oss:120b-cloud"},
        ]}
        with patch.object(mini, "MODEL_POLICY", SingleModelPolicy("gpt-oss:20b-cloud")), \
                patch.object(mini, "http_get_json", return_value=response):
            models = mini.fetch_local_ollama_models()
        self.assertEqual([item["name"] for item in models],
                         ["gemma4:e4b", "gpt-oss:20b-cloud"])

    def test_canary_allows_reasoning_before_visible_answer(self):
        response = Mock(status_code=200, text="")
        response.json.return_value = {"message": {"content": "HIVO_PREFLIGHT_OK"}}
        with patch.object(host_preflight, "post_json", return_value=response) as post:
            host_preflight._default_canary_call(
                "gpt-oss:20b-cloud", host_preflight.CANARY_PROMPT, 30,
                "http://127.0.0.1:11434",
            )
        payload = post.call_args.kwargs["payload"]
        self.assertEqual(payload["model"], "gpt-oss:20b-cloud")
        self.assertEqual(payload["think"], "low")
        self.assertGreater(payload["options"]["num_predict"], 32)
