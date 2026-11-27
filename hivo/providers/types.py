"""Configuration, normalized response, and telemetry types for hivo.providers."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
from typing import Any, Literal, Mapping

ProviderType = Literal["openai_compat", "ollama"]
StructuredMode = Literal["json_schema", "json_object", "prompt"]

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
MAX_LOCAL_WORKER_CTX = 8192


class ProviderError(RuntimeError):
    """Explicit failure from a model provider (never fabricated or swallowed)."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
        provider_type: str = "",
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = bool(retryable)
        self.provider_type = provider_type


class ProviderConfigError(ProviderError):
    """Invalid or incomplete endpoint configuration (e.g., missing API key env var)."""


@dataclass(frozen=True)
class TokenUsage:
    """Normalized token usage counts reported by a provider."""

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None
    reasoning_tokens: int | None = None
    cached_tokens: int | None = None

    def to_dict(self) -> dict[str, int | None]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cached_tokens": self.cached_tokens,
        }

    def __add__(self, other: TokenUsage) -> TokenUsage:
        def _sum(a: int | None, b: int | None) -> int | None:
            if a is None and b is None:
                return None
            return (a or 0) + (b or 0)

        return TokenUsage(
            prompt_tokens=_sum(self.prompt_tokens, other.prompt_tokens),
            completion_tokens=_sum(self.completion_tokens, other.completion_tokens),
            total_tokens=_sum(self.total_tokens, other.total_tokens),
            reasoning_tokens=_sum(self.reasoning_tokens, other.reasoning_tokens),
            cached_tokens=_sum(self.cached_tokens, other.cached_tokens),
        )


@dataclass(frozen=True)
class EndpointConfig:
    """Config-driven endpoint definition (zero model-family branching in clients)."""

    provider_type: ProviderType
    base_url: str
    model: str
    api_key_env: str | None = None
    think: bool = False
    reasoning_effort: str | None = None
    reasoning_format: str | None = None
    max_tokens: int = 2048
    num_ctx: int | None = None
    keep_alive: str | None = "10m"
    temperature: float = 0.0
    structured_mode: StructuredMode = "json_schema"
    timeout_sec: float = 120.0
    max_retries: int = 3
    retry_backoff_sec: float = 1.5
    extra_headers: tuple[tuple[str, str], ...] = ()
    extra_body: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if self.provider_type not in {"openai_compat", "ollama"}:
            raise ProviderConfigError(
                f"provider_type must be 'openai_compat' or 'ollama', got {self.provider_type!r}"
            )
        if not self.base_url or not self.base_url.strip():
            raise ProviderConfigError("base_url must be a non-empty URL")
        object.__setattr__(self, "base_url", self.base_url.strip().rstrip("/"))
        if not self.model or not self.model.strip():
            raise ProviderConfigError("model must be a non-empty identifier")
        object.__setattr__(self, "model", self.model.strip())
        if self.max_tokens < 1:
            raise ProviderConfigError("max_tokens must be >= 1")
        if self.num_ctx is not None and self.num_ctx < 256:
            raise ProviderConfigError("num_ctx must be >= 256 when set")
        if self.structured_mode not in {"json_schema", "json_object", "prompt"}:
            raise ProviderConfigError(f"Unsupported structured_mode {self.structured_mode!r}")
        if self.timeout_sec <= 0:
            raise ProviderConfigError("timeout_sec must be > 0")
        if self.max_retries < 0:
            raise ProviderConfigError("max_retries must be >= 0")

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_type": self.provider_type,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "think": self.think,
            "reasoning_effort": self.reasoning_effort,
            "reasoning_format": self.reasoning_format,
            "max_tokens": self.max_tokens,
            "num_ctx": self.num_ctx,
            "keep_alive": self.keep_alive,
            "temperature": self.temperature,
            "structured_mode": self.structured_mode,
            "timeout_sec": self.timeout_sec,
            "max_retries": self.max_retries,
            "retry_backoff_sec": self.retry_backoff_sec,
            "extra_headers": dict(self.extra_headers),
            "extra_body": dict(self.extra_body),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EndpointConfig:
        raw_headers = data.get("extra_headers") or {}
        raw_body = data.get("extra_body") or {}
        headers_tuple = (
            tuple((str(k), str(v)) for k, v in raw_headers.items())
            if isinstance(raw_headers, Mapping)
            else tuple((str(k), str(v)) for k, v in raw_headers)
        )
        body_tuple = (
            tuple((str(k), v) for k, v in raw_body.items())
            if isinstance(raw_body, Mapping)
            else tuple((str(k), v) for k, v in raw_body)
        )
        return cls(
            provider_type=str(data["provider_type"]),  # type: ignore[arg-type]
            base_url=str(data["base_url"]),
            model=str(data["model"]),
            api_key_env=(
                None if data.get("api_key_env") in (None, "") else str(data["api_key_env"])
            ),
            think=bool(data.get("think", False)),
            reasoning_effort=(
                None if data.get("reasoning_effort") in (None, "") else str(data["reasoning_effort"])
            ),
            reasoning_format=(
                None if data.get("reasoning_format") in (None, "") else str(data["reasoning_format"])
            ),
            max_tokens=int(data.get("max_tokens", 2048)),
            num_ctx=None if data.get("num_ctx") is None else int(data["num_ctx"]),
            keep_alive=(
                None if data.get("keep_alive") in (None, "") else str(data["keep_alive"])
            ),
            temperature=float(data.get("temperature", 0.0)),
            structured_mode=str(data.get("structured_mode", "json_schema")),  # type: ignore[arg-type]
            timeout_sec=float(data.get("timeout_sec", 120.0)),
            max_retries=int(data.get("max_retries", 3)),
            retry_backoff_sec=float(data.get("retry_backoff_sec", 1.5)),
            extra_headers=headers_tuple,
            extra_body=body_tuple,
        )


@dataclass(frozen=True)
class ModelResponse:
    """Canonical normalized assistant response across cloud OpenAI-compat and local Ollama."""

    role: str = "assistant"
    content: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    reasoning_chars: int = 0
    finish_reason: str = ""
    usage: TokenUsage = field(default_factory=TokenUsage)
    latency_ms: float = 0.0
    model: str = ""
    provider_type: str = ""
    raw_status: int = 200
    rate_limit_headers: dict[str, str] = field(default_factory=dict)

    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_assistant_message(self, *, wire_format: ProviderType = "openai_compat") -> dict[str, Any]:
        """Serialize this response cleanly back into chat history without leaking thinking text."""
        msg: dict[str, Any] = {"role": self.role or "assistant", "content": self.content}
        if self.tool_calls:
            serialized_calls: list[dict[str, Any]] = []
            for idx, call in enumerate(self.tool_calls):
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
                    serialized_calls.append({
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
                    serialized_calls.append({
                        "id": call_id,
                        "function": {"name": name, "arguments": wire_args_obj},
                    })
            msg["tool_calls"] = serialized_calls
        return msg


# ---------------------------------------------------------------------------
# Pure config preset factories (config only; clients have zero model branches)
# ---------------------------------------------------------------------------


def groq_orchestrator(
    model: str = "qwen/qwen3.8-27b",
    *,
    api_key_env: str = "GROQ_API_KEY",
    think: bool = True,
    reasoning_effort: str | None = "medium",
    max_tokens: int = 2048,
    temperature: float = 0.0,
    structured_mode: StructuredMode = "json_object",
) -> EndpointConfig:
    """Preset for Groq OpenAI-compatible cloud orchestrator."""
    return EndpointConfig(
        provider_type="openai_compat",
        base_url="https://api.groq.com/openai/v1",
        model=model,
        api_key_env=api_key_env,
        think=think,
        reasoning_effort=reasoning_effort if think else None,
        reasoning_format="parsed" if think else None,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        timeout_sec=120.0,
        max_retries=4,
        retry_backoff_sec=2.0,
    )


def nvidia_nim_orchestrator(
    model: str = "z-ai/glm-5.3-flash",
    *,
    api_key_env: str = "NVIDIA_API_KEY",
    think: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    structured_mode: StructuredMode = "json_object",
) -> EndpointConfig:
    """Preset for NVIDIA NIM free/developer OpenAI-compatible cloud orchestrator."""
    return EndpointConfig(
        provider_type="openai_compat",
        base_url="https://integrate.api.nvidia.com/v1",
        model=model,
        api_key_env=api_key_env,
        think=think,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        timeout_sec=180.0,
        max_retries=4,
        retry_backoff_sec=2.0,
    )


def openrouter_orchestrator(
    model: str = "qwen/qwen3.8-27b",
    *,
    api_key_env: str = "OPENROUTER_API_KEY",
    think: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    structured_mode: StructuredMode = "json_schema",
) -> EndpointConfig:
    """Preset for OpenRouter OpenAI-compatible cloud orchestrator (paid or :free)."""
    return EndpointConfig(
        provider_type="openai_compat",
        base_url="https://openrouter.ai/api/v1",
        model=model,
        api_key_env=api_key_env,
        think=think,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        timeout_sec=150.0,
        max_retries=4,
        retry_backoff_sec=2.0,
        extra_headers=(("X-Title", "Mini Hivo"),),
    )


def cerebras_orchestrator(
    model: str = "qwen-3.8-27b",
    *,
    api_key_env: str = "CEREBRAS_API_KEY",
    think: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    structured_mode: StructuredMode = "json_object",
) -> EndpointConfig:
    """Preset for Cerebras ultra-fast OpenAI-compatible cloud orchestrator."""
    return EndpointConfig(
        provider_type="openai_compat",
        base_url="https://api.cerebras.ai/v1",
        model=model,
        api_key_env=api_key_env,
        think=think,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        timeout_sec=90.0,
        max_retries=3,
        retry_backoff_sec=1.5,
    )


def gemini_orchestrator(
    model: str = "gemini-3-flash-preview",
    *,
    api_key_env: str = "GEMINI_API_KEY",
    think: bool = True,
    max_tokens: int = 4096,
    temperature: float = 0.0,
    structured_mode: StructuredMode = "json_schema",
) -> EndpointConfig:
    """Preset for Google AI Studio OpenAI-compatible endpoint."""
    return EndpointConfig(
        provider_type="openai_compat",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model=model,
        api_key_env=api_key_env,
        think=think,
        max_tokens=max_tokens,
        temperature=temperature,
        structured_mode=structured_mode,
        timeout_sec=120.0,
        max_retries=4,
        retry_backoff_sec=2.0,
    )


def ollama_worker(
    model: str = "qwen3.5:2b",
    *,
    base_url: str | None = None,
    num_ctx: int = 4096,
    max_tokens: int = 2048,
    temperature: float = 0.0,
    think: bool = False,
    keep_alive: str = "10m",
) -> EndpointConfig:
    """Preset for a local 4 GB VRAM-safe Ollama worker (thinking OFF, capped num_ctx)."""
    resolved_url = (base_url or os.environ.get("OLLAMA_BASE_URL") or DEFAULT_OLLAMA_BASE_URL).strip()
    bounded_ctx = min(max(512, int(num_ctx)), MAX_LOCAL_WORKER_CTX)
    return EndpointConfig(
        provider_type="ollama",
        base_url=resolved_url,
        model=model,
        api_key_env=None,
        think=bool(think),
        max_tokens=max_tokens,
        num_ctx=bounded_ctx,
        keep_alive=keep_alive,
        temperature=temperature,
        structured_mode="json_schema",
        timeout_sec=180.0,
        max_retries=2,
        retry_backoff_sec=0.5,
    )
