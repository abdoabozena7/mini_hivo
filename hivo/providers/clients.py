"""Stdlib-only OpenAI-compatible cloud client and local Ollama worker client."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from hivo.http_client import HttpTransportError

from .env import resolve_api_key
from .types import (
    EndpointConfig,
    ModelResponse,
    ProviderConfigError,
    ProviderError,
    TokenUsage,
)

_THINK_BLOCK_RE = re.compile(r"<think>(.*?)</think>", re.DOTALL | re.IGNORECASE)
_UNCLOSED_THINK_RE = re.compile(r"<think>.*$", re.DOTALL | re.IGNORECASE)
_RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
_SAFE_RATE_HEADER_PREFIXES = ("x-ratelimit-", "retry-after", "x-request-id")


@dataclass(frozen=True)
class RawHttpResponse:
    status_code: int
    text: str
    headers: dict[str, str]


TransportFn = Callable[[str, dict[str, Any], dict[str, str], float], RawHttpResponse]


def _default_post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> RawHttpResponse:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req_headers = {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "User-Agent": "MiniHivo/0.5",
        **headers,
    }
    request = Request(url, data=body, headers=req_headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as resp:
            raw_text = resp.read().decode("utf-8", errors="replace")
            resp_headers = {k.lower(): v for k, v in resp.headers.items()}
            return RawHttpResponse(int(resp.status), raw_text, resp_headers)
    except HTTPError as exc:
        raw_text = exc.read().decode("utf-8", errors="replace")
        resp_headers = {k.lower(): v for k, v in (exc.headers.items() if exc.headers else ())}
        return RawHttpResponse(int(exc.code), raw_text, resp_headers)
    except (URLError, OSError, TimeoutError) as exc:
        raise HttpTransportError(str(exc)) from exc


def extract_rate_limit_headers(headers: Mapping[str, str] | None) -> dict[str, str]:
    if not headers:
        return {}
    out: dict[str, str] = {}
    for key, val in headers.items():
        low = str(key).lower()
        if any(low.startswith(prefix) for prefix in _SAFE_RATE_HEADER_PREFIXES):
            out[low] = str(val)
    return out


def strip_think_blocks(text: str) -> tuple[str, int]:
    """Strip inline ``<think>...</think>`` sections and return ``(clean_text, stripped_chars)``."""
    if not text or "<think" not in text.lower():
        return text, 0
    removed = 0

    def _count(match: re.Match[str]) -> str:
        nonlocal removed
        removed += len(match.group(1))
        return ""

    cleaned = _THINK_BLOCK_RE.sub(_count, text)
    unclosed = _UNCLOSED_THINK_RE.search(cleaned)
    if unclosed:
        removed += len(unclosed.group(0))
        cleaned = cleaned[: unclosed.start()]
    return cleaned.strip(), removed


def normalize_tool_calls(raw_calls: Any) -> tuple[dict[str, Any], ...]:
    """Normalize OpenAI/Ollama tool calls so ``function.arguments`` is parsed when valid JSON."""
    if isinstance(raw_calls, dict):
        raw_calls = [raw_calls]
    if not isinstance(raw_calls, list):
        return ()

    normalized: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_calls):
        if not isinstance(item, dict):
            continue
        fn = item.get("function") if isinstance(item.get("function"), dict) else {}
        name = str(fn.get("name") or item.get("name") or "").strip()
        if not name:
            continue
        call_id = str(item.get("id") or f"call_{idx + 1}")
        raw_args = fn.get("arguments") if "arguments" in fn else item.get("arguments", {})
        if isinstance(raw_args, str):
            stripped = raw_args.strip()
            if not stripped:
                parsed_args: Any = {}
            else:
                try:
                    parsed_args = json.loads(stripped)
                except json.JSONDecodeError:
                    # Preserve raw malformed JSON so ToolProtocolAdapter emits a self-correcting error.
                    parsed_args = raw_args
        elif raw_args is None:
            parsed_args = {}
        else:
            parsed_args = raw_args
        normalized.append({
            "id": call_id,
            "type": "function",
            "function": {"name": name, "arguments": parsed_args},
        })
    return tuple(normalized)


def _coerce_int_opt(value: Any) -> int | None:
    if type(value) is int and value >= 0:
        return value
    return None


_DURATION_PART_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ms|s|m|h)\b", re.IGNORECASE)


def _parse_duration_seconds(raw: str | None) -> float | None:
    """Parse plain seconds ('3', '2.5') or Go-style durations ('24.917s', '1m5.2s', '500ms')."""
    if not raw:
        return None
    text = raw.strip()
    try:
        val = float(text)
        return val if val > 0 else None
    except ValueError:
        pass
    matches = _DURATION_PART_RE.findall(text)
    if not matches:
        return None
    total = 0.0
    for num_str, unit in matches:
        num = float(num_str)
        u = unit.lower()
        if u == "ms":
            total += num / 1000.0
        elif u == "s":
            total += num
        elif u == "m":
            total += num * 60.0
        elif u == "h":
            total += num * 3600.0
    return total if total > 0 else None


def _parse_retry_after(headers: Mapping[str, str], default_sec: float, *, status_code: int = 429) -> float:
    retry_after = _parse_duration_seconds(headers.get("retry-after"))
    if retry_after is not None:
        return min(retry_after, 60.0)
    if status_code == 429:
        # Prefer token-window reset (typically seconds on TPM caps like Groq 8K TPM).
        for key in ("x-ratelimit-reset-tokens", "x-ratelimit-reset-requests"):
            reset_sec = _parse_duration_seconds(headers.get(key))
            if reset_sec is not None and reset_sec <= 60.0:
                return min(reset_sec + 0.25, 60.0)
    return default_sec


def _effective_timeout(base_timeout: float, deadline_monotonic: float | None) -> float:
    if deadline_monotonic is None:
        return base_timeout
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise ProviderError("Run deadline exceeded before provider request.", retryable=False)
    return min(base_timeout, remaining)


def _sleep_respecting_deadline(
    delay: float,
    deadline_monotonic: float | None,
    sleep_fn: Callable[[float], None],
) -> None:
    if deadline_monotonic is not None:
        remaining = deadline_monotonic - time.monotonic()
        if remaining <= 0.05:
            raise ProviderError("Run deadline exceeded during provider retry backoff.", retryable=False)
        delay = min(delay, max(0.0, remaining - 0.05))
    if delay > 0:
        sleep_fn(delay)


def _prepare_wire_messages(
    messages: Sequence[Mapping[str, Any]],
    *,
    wire_format: str,
) -> list[dict[str, Any]]:
    """Serialize canonical messages into OpenAI-compatible or Ollama wire format."""
    prepared: list[dict[str, Any]] = []
    for raw in messages:
        msg: dict[str, Any] = {
            "role": str(raw.get("role", "user")),
            "content": "" if raw.get("content") is None else str(raw.get("content")),
        }
        if raw.get("role") == "tool":
            if wire_format == "openai_compat":
                msg["tool_call_id"] = str(raw.get("tool_call_id") or "call_1")
            if raw.get("name"):
                msg["name"] = str(raw["name"])
        elif raw.get("role") == "assistant" and raw.get("tool_calls"):
            calls: list[dict[str, Any]] = []
            for idx, call in enumerate(raw["tool_calls"]):
                if not isinstance(call, Mapping):
                    continue
                fn = call.get("function") if isinstance(call.get("function"), Mapping) else {}
                name = str(fn.get("name") or "")
                args = fn.get("arguments", {})
                call_id = str(call.get("id") or f"call_{idx + 1}")
                if wire_format == "openai_compat":
                    wire_args = (
                        args
                        if isinstance(args, str)
                        else json.dumps(args, ensure_ascii=False, sort_keys=True)
                    )
                    calls.append({
                        "id": call_id,
                        "type": "function",
                        "function": {"name": name, "arguments": wire_args},
                    })
                else:
                    if isinstance(args, str):
                        try:
                            wire_args_obj = json.loads(args) if args.strip() else {}
                        except json.JSONDecodeError:
                            wire_args_obj = {}
                    else:
                        wire_args_obj = args
                    calls.append({
                        "id": call_id,
                        "function": {"name": name, "arguments": wire_args_obj},
                    })
            if calls:
                msg["tool_calls"] = calls
        prepared.append(msg)
    return prepared


class OpenAICompatClient:
    """Thin OpenAI-compatible ``/chat/completions`` client for cloud orchestrators."""

    def __init__(
        self,
        config: EndpointConfig,
        *,
        api_key: str | None = None,
        dotenv_path: str | None = None,
        transport: TransportFn | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if config.provider_type != "openai_compat":
            raise ProviderConfigError(
                f"OpenAICompatClient requires provider_type='openai_compat', got {config.provider_type!r}"
            )
        self.config = config
        self._explicit_api_key = api_key
        self._dotenv_path = dotenv_path
        self._transport = transport or _default_post_json
        self._sleep = sleep_fn

    def _auth_headers(self) -> dict[str, str]:
        key = (
            self._explicit_api_key
            if self._explicit_api_key is not None
            else resolve_api_key(self.config.api_key_env, dotenv_path=self._dotenv_path)
        )
        headers = dict(self.config.extra_headers)
        if key:
            headers["Authorization"] = f"Bearer {key}"
        return headers

    def _build_payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": _prepare_wire_messages(messages, wire_format="openai_compat"),
            "temperature": self.config.temperature if temperature is None else float(temperature),
            "max_tokens": self.config.max_tokens if max_tokens is None else int(max_tokens),
            "stream": False,
        }
        if tools:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"

        effective_think = self.config.think if think is None else bool(think)
        if effective_think:
            if self.config.reasoning_format:
                payload["reasoning_format"] = self.config.reasoning_format
            if self.config.reasoning_effort:
                payload["reasoning_effort"] = self.config.reasoning_effort

        if response_format is not None:
            mode = self.config.structured_mode
            if mode == "json_schema":
                if "type" in response_format and response_format.get("type") in {"json_schema", "json_object"}:
                    payload["response_format"] = dict(response_format)
                else:
                    payload["response_format"] = {
                        "type": "json_schema",
                        "json_schema": {
                            "name": "structured_response",
                            "strict": True,
                            "schema": dict(response_format),
                        },
                    }
            elif mode == "json_object":
                payload["response_format"] = {"type": "json_object"}
            # mode == "prompt": rely on prompt instructions + caller JSON validation

        for key, value in self.config.extra_body:
            payload[key] = value
        return payload

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
        deadline_monotonic: float | None = None,
    ) -> ModelResponse:
        url = f"{self.config.base_url}/chat/completions"
        headers = self._auth_headers()
        payload = self._build_payload(
            messages,
            tools=tools,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            think=think,
        )

        last_err: ProviderError | None = None
        for attempt in range(self.config.max_retries + 1):
            timeout = _effective_timeout(self.config.timeout_sec, deadline_monotonic)
            t0 = time.perf_counter()
            try:
                resp = self._transport(url, payload, headers, timeout)
            except HttpTransportError as exc:
                last_err = ProviderError(
                    f"Cloud provider transport error ({self.config.base_url}): {exc}",
                    retryable=True,
                    provider_type="openai_compat",
                )
                if attempt < self.config.max_retries:
                    delay = self.config.retry_backoff_sec * (2 ** attempt)
                    _sleep_respecting_deadline(delay, deadline_monotonic, self._sleep)
                    continue
                raise last_err from exc
            latency_ms = (time.perf_counter() - t0) * 1000.0
            rate_headers = extract_rate_limit_headers(resp.headers)

            if resp.status_code == 200:
                try:
                    body = json.loads(resp.text)
                except json.JSONDecodeError as exc:
                    raise ProviderError(
                        f"Cloud provider returned invalid JSON (HTTP 200): {exc}",
                        status_code=200,
                        retryable=False,
                        provider_type="openai_compat",
                    ) from exc
                return self._parse_success(body, latency_ms=latency_ms, rate_headers=rate_headers)

            retryable = resp.status_code in _RETRYABLE_STATUS_CODES
            snippet = resp.text[:400].replace("\n", " ")
            last_err = ProviderError(
                f"Cloud provider HTTP {resp.status_code} from {self.config.model}: {snippet}",
                status_code=resp.status_code,
                retryable=retryable,
                provider_type="openai_compat",
            )
            if retryable and attempt < self.config.max_retries:
                backoff = self.config.retry_backoff_sec * (2 ** attempt)
                delay = _parse_retry_after(resp.headers, backoff, status_code=resp.status_code)
                _sleep_respecting_deadline(delay, deadline_monotonic, self._sleep)
                continue
            raise last_err

        assert last_err is not None
        raise last_err

    def _parse_success(
        self,
        body: Mapping[str, Any],
        *,
        latency_ms: float,
        rate_headers: dict[str, str],
    ) -> ModelResponse:
        if body.get("error"):
            raise ProviderError(
                f"Cloud provider returned error object: {str(body['error'])[:400]}",
                status_code=200,
                retryable=False,
                provider_type="openai_compat",
            )
        choices = body.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
            raise ProviderError(
                "Cloud provider response missing choices[0].",
                status_code=200,
                retryable=False,
                provider_type="openai_compat",
            )
        choice = choices[0]
        msg = choice.get("message") if isinstance(choice.get("message"), Mapping) else {}

        raw_content = msg.get("content")
        if raw_content is None:
            content_str = ""
        elif isinstance(raw_content, str):
            content_str = raw_content
        else:
            content_str = json.dumps(raw_content, ensure_ascii=False)

        clean_content, inline_think_chars = strip_think_blocks(content_str)
        separate_reasoning = (
            msg.get("reasoning_content")
            or msg.get("reasoning")
            or msg.get("thinking")
            or ""
        )
        reasoning_chars = inline_think_chars + len(str(separate_reasoning))
        tool_calls = normalize_tool_calls(msg.get("tool_calls"))

        raw_usage = body.get("usage") if isinstance(body.get("usage"), Mapping) else {}
        completion_details = (
            raw_usage.get("completion_tokens_details")
            if isinstance(raw_usage.get("completion_tokens_details"), Mapping)
            else {}
        )
        prompt_details = (
            raw_usage.get("prompt_tokens_details")
            if isinstance(raw_usage.get("prompt_tokens_details"), Mapping)
            else {}
        )
        usage = TokenUsage(
            prompt_tokens=_coerce_int_opt(raw_usage.get("prompt_tokens")),
            completion_tokens=_coerce_int_opt(raw_usage.get("completion_tokens")),
            total_tokens=_coerce_int_opt(raw_usage.get("total_tokens")),
            reasoning_tokens=_coerce_int_opt(completion_details.get("reasoning_tokens")),
            cached_tokens=_coerce_int_opt(prompt_details.get("cached_tokens")),
        )
        return ModelResponse(
            role=str(msg.get("role") or "assistant"),
            content=clean_content,
            tool_calls=tool_calls,
            reasoning_chars=reasoning_chars,
            finish_reason=str(choice.get("finish_reason") or ""),
            usage=usage,
            latency_ms=latency_ms,
            model=str(body.get("model") or self.config.model),
            provider_type="openai_compat",
            raw_status=200,
            rate_limit_headers=rate_headers,
        )


class OllamaClient:
    """Thin local Ollama ``/api/chat`` client enforcing 4 GB VRAM-safe worker defaults."""

    def __init__(
        self,
        config: EndpointConfig,
        *,
        transport: TransportFn | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        if config.provider_type != "ollama":
            raise ProviderConfigError(
                f"OllamaClient requires provider_type='ollama', got {config.provider_type!r}"
            )
        self.config = config
        self._transport = transport or _default_post_json
        self._sleep = sleep_fn

    def _build_payload(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
    ) -> dict[str, Any]:
        options: dict[str, Any] = {
            "temperature": self.config.temperature if temperature is None else float(temperature),
            "num_predict": self.config.max_tokens if max_tokens is None else int(max_tokens),
        }
        if self.config.num_ctx is not None:
            options["num_ctx"] = int(self.config.num_ctx)

        payload: dict[str, Any] = {
            "model": self.config.model,
            "messages": _prepare_wire_messages(messages, wire_format="ollama"),
            "stream": False,
            "think": self.config.think if think is None else bool(think),
            "options": options,
        }
        if self.config.keep_alive:
            payload["keep_alive"] = self.config.keep_alive
        if tools:
            payload["tools"] = list(tools)
        if response_format is not None:
            payload["format"] = (
                dict(response_format) if isinstance(response_format, Mapping) else response_format
            )
        for key, value in self.config.extra_body:
            payload[key] = value
        return payload

    def chat(
        self,
        messages: Sequence[Mapping[str, Any]],
        *,
        tools: Sequence[Mapping[str, Any]] | None = None,
        response_format: Mapping[str, Any] | str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        think: bool | None = None,
        deadline_monotonic: float | None = None,
    ) -> ModelResponse:
        url = f"{self.config.base_url}/api/chat"
        headers = dict(self.config.extra_headers)
        payload = self._build_payload(
            messages,
            tools=tools,
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            think=think,
        )

        last_err: ProviderError | None = None
        for attempt in range(self.config.max_retries + 1):
            timeout = _effective_timeout(self.config.timeout_sec, deadline_monotonic)
            t0 = time.perf_counter()
            try:
                resp = self._transport(url, payload, headers, timeout)
            except HttpTransportError as exc:
                last_err = ProviderError(
                    f"Local Ollama transport error ({self.config.base_url}): {exc}",
                    retryable=True,
                    provider_type="ollama",
                )
                if attempt < self.config.max_retries:
                    _sleep_respecting_deadline(
                        self.config.retry_backoff_sec * (attempt + 1),
                        deadline_monotonic,
                        self._sleep,
                    )
                    continue
                raise last_err from exc
            latency_ms = (time.perf_counter() - t0) * 1000.0

            if resp.status_code == 200:
                try:
                    body = json.loads(resp.text)
                except json.JSONDecodeError as exc:
                    raise ProviderError(
                        f"Ollama returned invalid JSON (HTTP 200): {exc}",
                        status_code=200,
                        retryable=False,
                        provider_type="ollama",
                    ) from exc
                return self._parse_success(body, latency_ms=latency_ms)

            retryable = resp.status_code in _RETRYABLE_STATUS_CODES
            snippet = resp.text[:400].replace("\n", " ")
            last_err = ProviderError(
                f"Ollama HTTP {resp.status_code} for {self.config.model}: {snippet}",
                status_code=resp.status_code,
                retryable=retryable,
                provider_type="ollama",
            )
            if retryable and attempt < self.config.max_retries:
                _sleep_respecting_deadline(
                    self.config.retry_backoff_sec * (attempt + 1),
                    deadline_monotonic,
                    self._sleep,
                )
                continue
            raise last_err

        assert last_err is not None
        raise last_err

    def _parse_success(self, body: Mapping[str, Any], *, latency_ms: float) -> ModelResponse:
        if body.get("error"):
            raise ProviderError(
                f"Ollama returned error: {str(body['error'])[:400]}",
                status_code=200,
                retryable=False,
                provider_type="ollama",
            )
        msg = body.get("message") if isinstance(body.get("message"), Mapping) else {}
        raw_content = msg.get("content")
        if raw_content is None:
            content_str = ""
        elif isinstance(raw_content, str):
            content_str = raw_content
        else:
            content_str = json.dumps(raw_content, ensure_ascii=False)

        clean_content, inline_think_chars = strip_think_blocks(content_str)
        separate_thinking = msg.get("thinking") or msg.get("reasoning") or ""
        reasoning_chars = inline_think_chars + len(str(separate_thinking))
        tool_calls = normalize_tool_calls(msg.get("tool_calls"))

        prompt_tokens = _coerce_int_opt(body.get("prompt_eval_count"))
        completion_tokens = _coerce_int_opt(body.get("eval_count"))
        total_tokens = (
            prompt_tokens + completion_tokens
            if prompt_tokens is not None and completion_tokens is not None
            else None
        )
        return ModelResponse(
            role=str(msg.get("role") or "assistant"),
            content=clean_content,
            tool_calls=tool_calls,
            reasoning_chars=reasoning_chars,
            finish_reason=str(body.get("done_reason") or ("stop" if body.get("done") else "")),
            usage=TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            ),
            latency_ms=latency_ms,
            model=str(body.get("model") or self.config.model),
            provider_type="ollama",
            raw_status=200,
            rate_limit_headers={},
        )


ModelClient = OpenAICompatClient | OllamaClient


def create_client(
    config: EndpointConfig,
    *,
    api_key: str | None = None,
    dotenv_path: str | None = None,
    transport: TransportFn | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> ModelClient:
    """Create the appropriate provider client strictly from ``EndpointConfig``."""
    if config.provider_type == "openai_compat":
        return OpenAICompatClient(
            config,
            api_key=api_key,
            dotenv_path=dotenv_path,
            transport=transport,
            sleep_fn=sleep_fn,
        )
    if config.provider_type == "ollama":
        return OllamaClient(config, transport=transport, sleep_fn=sleep_fn)
    raise ProviderConfigError(f"Unsupported provider_type: {config.provider_type!r}")
