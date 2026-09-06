import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import mini


class _FakeHTTPResponse:
    def __init__(self, content, status_code=200):
        self.status_code = status_code
        self._body = {
            "model": "test-model",
            "message": {"role": "assistant", "content": content},
            "done": True,
            "done_reason": "stop",
        }
        self.text = json.dumps(self._body, ensure_ascii=False, sort_keys=True)

    def json(self):
        return self._body


class StructuredWorkerContractTests(unittest.TestCase):
    SCHEMA = {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": False,
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        mini._load_optional_imports()
        mini.WORKSPACE = Path(self.temp.name)
        mini.MODEL = "gemma4:e4b"
        mini.MODEL_CAPABILITIES = set()
        mini.ROUTER_MODEL = ""
        mini.FALLBACK_MODEL = ""
        mini.VISION_MODEL = ""
        mini.reset_run("structured-worker-test")

    def tearDown(self):
        mini.rollback_transaction()
        self.temp.cleanup()

    @staticmethod
    def _validator(value):
        return {
            "valid": isinstance(value, dict) and isinstance(value.get("answer"), str),
            "errors": [] if isinstance(value, dict) and isinstance(value.get("answer"), str)
            else ["answer must be a string"],
        }

    def _run(self, responses, *, retries=2, capture=None):
        with patch.object(mini, "http_post_json", side_effect=responses) as request:
            result = mini.execute_agent_task(
                "return the bounded answer",
                {},
                role="Builder",
                task_id="STRUCTURED-T1",
                max_steps=1,
                structured_response_schema=self.SCHEMA,
                structured_response_validator=self._validator,
                structured_response_label="generation-response",
                structured_response_retries=retries,
                structured_response_capture=capture,
                structured_response_context={
                    "workload": "A",
                    "core_execution_id": "core-test-1",
                    "provider_adapter_id": "generation-adapter",
                },
            )
        return result, request

    def test_worker_uses_existing_structured_path_and_captures_full_request_response(self):
        captured = []

        def capture(event, payload):
            captured.append((event, payload))

        response = _FakeHTTPResponse(json.dumps({"answer": "ready"}))
        result, request = self._run(
            [response],
            retries=2,
            capture=capture,
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["structured_response"], {"answer": "ready"})
        self.assertTrue(result["structured_response_active"])
        self.assertEqual(request.call_count, 1)
        payload = request.call_args.kwargs["payload"]
        self.assertEqual(payload["format"], self.SCHEMA)
        self.assertNotIn("tools", payload)
        self.assertFalse(payload["think"])

        request_events = [item for item in captured if item[0] == "PROVIDER_REQUEST_INTENT"]
        response_events = [item for item in captured if item[0] == "RAW_RESPONSE_CAPTURED"]
        parse_events = [item for item in captured if item[0] == "STRUCTURED_PARSE_ATTEMPTED"]
        self.assertEqual(len(request_events), 1)
        self.assertEqual(len(response_events), 1)
        self.assertEqual(len(parse_events), 1)
        self.assertEqual(request_events[0][1]["request_payload"], payload)
        self.assertEqual(response_events[0][1]["response_text"], response.text)
        self.assertEqual(parse_events[0][1]["status"], "COMPLETED")

    def test_structured_retry_is_bounded_and_preserves_each_raw_attempt(self):
        captured = []

        def capture(event, payload):
            captured.append((event, payload))

        result, request = self._run(
            [
                _FakeHTTPResponse("not json"),
                _FakeHTTPResponse(json.dumps({"answer": "repaired"})),
            ],
            retries=2,
            capture=capture,
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["structured_response"], {"answer": "repaired"})
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            [item[0] for item in captured].count("PROVIDER_REQUEST_INTENT"), 2,
        )
        self.assertEqual(
            [item[0] for item in captured].count("RAW_RESPONSE_CAPTURED"), 2,
        )
        invalid = [item for item in captured if item[0] == "STRUCTURED_PARSE_ATTEMPTED"]
        self.assertEqual([item[1]["status"] for item in invalid], ["INVALID", "COMPLETED"])
        self.assertEqual(mini.RUN["planner_structured_retries"], 1)

    def test_malformed_structured_output_fails_without_an_outer_retry(self):
        captured = []

        def capture(event, payload):
            captured.append((event, payload))

        result, request = self._run(
            [_FakeHTTPResponse("still not json"), _FakeHTTPResponse("still not json")],
            retries=2,
            capture=capture,
        )

        self.assertEqual(result["status"], "structured_response_failure")
        self.assertEqual(result["failure_type"], "STRUCTURED_OUTPUT_INVALID")
        self.assertIsNone(result["structured_response"])
        self.assertEqual(request.call_count, 2)
        self.assertEqual(
            [item[0] for item in captured].count("RAW_RESPONSE_CAPTURED"), 2,
        )
        self.assertEqual(
            [item[0] for item in captured].count("STRUCTURED_PARSE_ATTEMPTED"), 2,
        )

    def test_existing_json_with_prose_parser_remains_usable_through_worker(self):
        result, request = self._run(
            [_FakeHTTPResponse("Here is the result: {\"answer\": \"prose-safe\"}")],
            retries=1,
        )

        self.assertEqual(result["status"], "done")
        self.assertEqual(result["structured_response"], {"answer": "prose-safe"})
        self.assertEqual(request.call_count, 1)


if __name__ == "__main__":
    unittest.main()
