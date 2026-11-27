"""Pure-Python unit tests for hivo.providers (zero live network calls)."""

from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest import mock

from hivo.http_client import HttpTransportError
from hivo.providers import (
    MAX_LOCAL_WORKER_CTX,
    EndpointConfig,
    OllamaClient,
    OpenAICompatClient,
    ProviderConfigError,
    ProviderError,
    RawHttpResponse,
    TokenUsage,
    cerebras_orchestrator,
    create_client,
    gemini_orchestrator,
    groq_orchestrator,
    load_dotenv,
    normalize_tool_calls,
    nvidia_nim_orchestrator,
    ollama_worker,
    openrouter_orchestrator,
    resolve_api_key,
    strip_think_blocks,
)


class TestEnvAndConfig(unittest.TestCase):
    def test_load_dotenv_parses_quotes_comments_and_respects_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env_file = Path(tmp) / ".env"
            env_file.write_text(
                "# comment\n"
                "TEST_HIVO_A=alpha # inline comment\n"
                'export TEST_HIVO_B="beta value"\n'
                "TEST_HIVO_C='gamma'\n"
                "TEST_HIVO_EMPTY=\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"TEST_HIVO_A": "preset"}, clear=False):
                os.environ.pop("TEST_HIVO_B", None)
                os.environ.pop("TEST_HIVO_C", None)
                loaded = load_dotenv(env_file, override=False)
                # Returns bool flags only, never values
                self.assertEqual(loaded, {"TEST_HIVO_B": True, "TEST_HIVO_C": True})
                self.assertEqual(os.environ["TEST_HIVO_A"], "preset")
                self.assertEqual(os.environ["TEST_HIVO_B"], "beta value")
                self.assertEqual(os.environ["TEST_HIVO_C"], "gamma")

    def test_resolve_api_key_missing_raises_without_leaking_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("TEST_HIVO_MISSING_KEY", None)
                with self.assertRaises(ProviderConfigError) as ctx:
                    resolve_api_key("TEST_HIVO_MISSING_KEY", dotenv_path=Path(tmp) / ".env")
                self.assertIn("TEST_HIVO_MISSING_KEY", str(ctx.exception))

    def test_presets_and_serialization_roundtrip(self) -> None:
        g = groq_orchestrator()
        self.assertEqual(g.provider_type, "openai_compat")
        self.assertTrue(g.think)
        self.assertEqual(g.reasoning_effort, "medium")
        self.assertEqual(g.reasoning_format, "parsed")
        self.assertEqual(g.max_tokens, 2048)
        self.assertEqual(EndpointConfig.from_dict(g.to_dict()), g)

        n = nvidia_nim_orchestrator()
        self.assertIn("integrate.api.nvidia.com", n.base_url)
        self.assertTrue(n.think)

        o = openrouter_orchestrator()
        self.assertIn("openrouter.ai", o.base_url)

        c = cerebras_orchestrator()
        self.assertEqual(c.structured_mode, "json_object")

        gem = gemini_orchestrator()
        self.assertIn("generativelanguage.googleapis.com", gem.base_url)

        w = ollama_worker(model="qwen3.5:2b", num_ctx=32768)
        self.assertEqual(w.provider_type, "ollama")
        self.assertFalse(w.think)
        self.assertEqual(w.num_ctx, MAX_LOCAL_WORKER_CTX)
        self.assertEqual(EndpointConfig.from_dict(w.to_dict()), w)

    def test_token_usage_addition(self) -> None:
        a = TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15, reasoning_tokens=3)
        b = TokenUsage(prompt_tokens=20, completion_tokens=None, total_tokens=25, cached_tokens=4)
        total = a + b
        self.assertEqual(total.prompt_tokens, 30)
        self.assertEqual(total.completion_tokens, 5)
        self.assertEqual(total.total_tokens, 40)
        self.assertEqual(total.reasoning_tokens, 3)
        self.assertEqual(total.cached_tokens, 4)


class TestNormalizationHelpers(unittest.TestCase):
    def test_strip_think_blocks_closed_and_unclosed(self) -> None:
        clean, n = strip_think_blocks("<think>step 1\nstep 2</think>\nFinal answer")
        self.assertEqual(clean, "Final answer")
        self.assertEqual(n, len("step 1\nstep 2"))

        clean2, n2 = strip_think_blocks("Prefix <think>cut off mid thought")
        self.assertEqual(clean2, "Prefix")
        self.assertGreater(n2, 0)

    def test_normalize_tool_calls_parses_json_strings_and_preserves_malformed(self) -> None:
        calls = normalize_tool_calls([
            {
                "id": "call_1",
                "type": "function",
                "function": {"name": "read_file", "arguments": '{"path": "a.py", "start_line": 1}'},
            },
            {
                "id": "call_2",
                "function": {"name": "edit_file", "arguments": "{bad json"},
            },
        ])
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0]["function"]["arguments"], {"path": "a.py", "start_line": 1})
        self.assertEqual(calls[1]["function"]["arguments"], "{bad json")


class TestOpenAICompatClient(unittest.TestCase):
    def test_chat_strips_thinking_normalizes_tool_calls_and_captures_rate_headers(self) -> None:
        captured: list[tuple[str, dict, dict]] = []

        def fake_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            captured.append((url, payload, headers))
            body = {
                "model": "qwen/qwen3.8-27b",
                "choices": [{
                    "finish_reason": "tool_calls",
                    "message": {
                        "role": "assistant",
                        "content": "<think>internal plan</think>Calling tool",
                        "reasoning_content": "extra chain of thought",
                        "tool_calls": [{
                            "id": "tc_1",
                            "type": "function",
                            "function": {
                                "name": "dispatch_worker",
                                "arguments": json.dumps({"task": "fix add", "target_files": ["a.py"]}),
                            },
                        }],
                    },
                }],
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 45,
                    "total_tokens": 165,
                    "completion_tokens_details": {"reasoning_tokens": 20},
                    "prompt_tokens_details": {"cached_tokens": 50},
                },
            }
            return RawHttpResponse(
                200,
                json.dumps(body),
                {"x-ratelimit-remaining-requests": "999", "x-ratelimit-remaining-tokens": "7800"},
            )

        cfg = groq_orchestrator()
        client = create_client(cfg, api_key="sk-test-secret-xyz", transport=fake_transport)
        self.assertIsInstance(client, OpenAICompatClient)

        resp = client.chat(
            [{"role": "user", "content": "Fix a.py"}],
            tools=[{"type": "function", "function": {"name": "dispatch_worker", "parameters": {}}}],
        )
        self.assertEqual(captured[0][0], "https://api.groq.com/openai/v1/chat/completions")
        self.assertEqual(captured[0][1]["reasoning_effort"], "medium")
        self.assertEqual(captured[0][1]["reasoning_format"], "parsed")
        self.assertEqual(captured[0][1]["max_tokens"], 2048)
        self.assertEqual(captured[0][2]["Authorization"], "Bearer sk-test-secret-xyz")

        # Thinking stripped from content and measured only as telemetry
        self.assertEqual(resp.content, "Calling tool")
        self.assertEqual(resp.reasoning_chars, len("internal plan") + len("extra chain of thought"))
        self.assertEqual(resp.tool_calls[0]["function"]["name"], "dispatch_worker")
        self.assertEqual(resp.tool_calls[0]["function"]["arguments"], {"task": "fix add", "target_files": ["a.py"]})
        self.assertEqual(resp.usage.reasoning_tokens, 20)
        self.assertEqual(resp.usage.cached_tokens, 50)
        self.assertEqual(resp.rate_limit_headers["x-ratelimit-remaining-requests"], "999")

        # Wire message round-trip stringifies OpenAI arguments cleanly
        wire_msg = resp.to_assistant_message(wire_format="openai_compat")
        self.assertIsInstance(wire_msg["tool_calls"][0]["function"]["arguments"], str)
        self.assertNotIn("internal plan", wire_msg["content"])

    def test_retries_429_respecting_retry_after_and_fails_explicitly_on_401(self) -> None:
        sleeps: list[float] = []
        calls = {"n": 0}

        def transport_429(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            calls["n"] += 1
            if calls["n"] == 1:
                return RawHttpResponse(429, '{"error": "rate limited"}', {"retry-after": "3"})
            return RawHttpResponse(
                200,
                json.dumps({"choices": [{"message": {"role": "assistant", "content": "OK"}, "finish_reason": "stop"}]}),
                {},
            )

        cfg = nvidia_nim_orchestrator()
        client = OpenAICompatClient(cfg, api_key="fake-test-key", transport=transport_429, sleep_fn=sleeps.append)
        resp = client.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp.content, "OK")
        self.assertEqual(calls["n"], 2)
        self.assertEqual(sleeps, [3.0])

        # Also parses Groq-style x-ratelimit-reset-tokens duration strings when retry-after is absent
        groq_sleeps: list[float] = []
        gcalls = {"n": 0}

        def transport_groq_429(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            gcalls["n"] += 1
            if gcalls["n"] == 1:
                return RawHttpResponse(429, '{"error": "tpm exceeded"}', {"x-ratelimit-reset-tokens": "12.5s"})
            return RawHttpResponse(
                200,
                json.dumps({"choices": [{"message": {"role": "assistant", "content": "OK2"}, "finish_reason": "stop"}]}),
                {},
            )

        gclient = OpenAICompatClient(groq_orchestrator(), api_key="fake-groq-key", transport=transport_groq_429, sleep_fn=groq_sleeps.append)
        resp2 = gclient.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp2.content, "OK2")
        self.assertEqual(groq_sleeps, [12.75])

        # Non-retryable 401 fails immediately without leaking secret
        secret = "sk-super-secret-do-not-leak"

        def transport_401(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            return RawHttpResponse(401, '{"error": "invalid api key"}', {})

        client_401 = OpenAICompatClient(cfg, api_key=secret, transport=transport_401, sleep_fn=sleeps.append)
        with self.assertRaises(ProviderError) as err:
            client_401.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(err.exception.status_code, 401)
        self.assertFalse(err.exception.retryable)
        self.assertNotIn(secret, str(err.exception))

    def test_structured_modes_and_transport_error(self) -> None:
        schema = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}
        for mode, expected_rf in (
            ("json_schema", {"type": "json_schema", "json_schema": {"name": "structured_response", "strict": True, "schema": schema}}),
            ("json_object", {"type": "json_object"}),
            ("prompt", None),
        ):
            seen: list[dict] = []

            def transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
                seen.append(payload)
                return RawHttpResponse(
                    200,
                    json.dumps({"choices": [{"message": {"role": "assistant", "content": '{"ok": true}'}}]}),
                    {},
                )

            cfg = EndpointConfig(
                provider_type="openai_compat",
                base_url="https://example.invalid/v1",
                model="test-model",
                structured_mode=mode,  # type: ignore[arg-type]
            )
            client = OpenAICompatClient(cfg, api_key="k", transport=transport)
            client.chat([{"role": "user", "content": "go"}], response_format=schema)
            self.assertEqual(seen[0].get("response_format"), expected_rf)

        def broken_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            raise HttpTransportError("connection refused")

        cfg = EndpointConfig(
            provider_type="openai_compat",
            base_url="https://example.invalid/v1",
            model="test-model",
            max_retries=1,
            retry_backoff_sec=0.0,
        )
        client = OpenAICompatClient(cfg, api_key="k", transport=broken_transport, sleep_fn=lambda _: None)
        with self.assertRaises(ProviderError):
            client.chat([{"role": "user", "content": "go"}])


class TestOllamaClient(unittest.TestCase):
    def test_enforces_think_false_num_ctx_keep_alive_and_normalizes_usage(self) -> None:
        seen_payloads: list[dict] = []

        def fake_transport(url: str, payload: dict, headers: dict, timeout: float) -> RawHttpResponse:
            seen_payloads.append(payload)
            return RawHttpResponse(
                200,
                json.dumps({
                    "model": "qwen3.5:2b",
                    "done": True,
                    "done_reason": "stop",
                    "prompt_eval_count": 88,
                    "eval_count": 21,
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": "call_1",
                            "function": {"name": "read_file", "arguments": {"path": "calc.py"}},
                        }],
                    },
                }),
                {},
            )

        cfg = ollama_worker(model="qwen3.5:2b", num_ctx=4096)
        client = create_client(cfg, transport=fake_transport)
        self.assertIsInstance(client, OllamaClient)

        resp = client.chat([{"role": "user", "content": "Read calc.py"}])
        self.assertFalse(seen_payloads[0]["think"])
        self.assertEqual(seen_payloads[0]["options"]["num_ctx"], 4096)
        self.assertEqual(seen_payloads[0]["keep_alive"], "10m")
        self.assertEqual(resp.usage.prompt_tokens, 88)
        self.assertEqual(resp.usage.completion_tokens, 21)
        self.assertEqual(resp.usage.total_tokens, 109)
        self.assertEqual(resp.tool_calls[0]["function"]["name"], "read_file")
        self.assertEqual(resp.tool_calls[0]["function"]["arguments"], {"path": "calc.py"})

    def test_deadline_exceeded_fails_before_request(self) -> None:
        cfg = ollama_worker()
        client = OllamaClient(cfg, transport=lambda *_: RawHttpResponse(200, "{}", {}))
        with self.assertRaises(ProviderError):
            client.chat([{"role": "user", "content": "hi"}], deadline_monotonic=time.monotonic() - 1.0)


if __name__ == "__main__":
    unittest.main()
