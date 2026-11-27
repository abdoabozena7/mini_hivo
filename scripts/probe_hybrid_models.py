"""Standalone live probe for Cloud Orchestrator + Local Ollama Worker.

Usage examples (after placing API key(s) in gitignored .env or user env vars):
    python scripts/probe_hybrid_models.py --provider groq
    python scripts/probe_hybrid_models.py --provider nvidia --model z-ai/glm-5.3-flash
    python scripts/probe_hybrid_models.py --provider groq --live-e2e
    python scripts/probe_hybrid_models.py --local-only
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

# Ensure repository root is importable when invoked as `python scripts/probe_hybrid_models.py`.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from hivo.hybrid import HybridAgentRunner, HybridRunConfig
from hivo.providers import (
    EndpointConfig,
    ProviderError,
    cerebras_orchestrator,
    create_client,
    gemini_orchestrator,
    groq_orchestrator,
    load_dotenv,
    nvidia_nim_orchestrator,
    ollama_worker,
    openrouter_orchestrator,
)
from hivo.tools import ToolContext, create_tool_binding


def _build_cloud_config(provider: str, model_override: str | None) -> EndpointConfig:
    p = provider.strip().lower()
    if p == "groq":
        return groq_orchestrator(model=model_override or "qwen/qwen3.8-27b")
    if p == "nvidia":
        return nvidia_nim_orchestrator(model=model_override or "z-ai/glm-5.3-flash")
    if p == "openrouter":
        return openrouter_orchestrator(model=model_override or "qwen/qwen3.8-27b")
    if p == "cerebras":
        return cerebras_orchestrator(model=model_override or "qwen-3.8-27b")
    if p == "gemini":
        return gemini_orchestrator(model=model_override or "gemini-3-flash-preview")
    raise ValueError(f"Unsupported provider {provider!r}")


def probe_cloud(cfg: EndpointConfig) -> bool:
    print(f"\n=== CLOUD PROBE: {cfg.base_url} | model={cfg.model} | think={cfg.think} ===")
    client = create_client(cfg)
    try:
        # 1. Basic thinking + latency + usage + rate headers
        r1 = client.chat([
            {"role": "user", "content": "Compute 17 * 23 and reply with only the integer."}
        ])
        print(
            f"[1/3 chat] ok | latency={r1.latency_ms:.0f}ms | content={r1.content!r} | "
            f"reasoning_chars={r1.reasoning_chars} | usage={r1.usage.to_dict()}"
        )
        if r1.rate_limit_headers:
            print("     rate_limit_headers:", r1.rate_limit_headers)

        # 2. Native tool calling against real hivo.tools orchestrator schema
        with tempfile.TemporaryDirectory() as tmp:
            binding = create_tool_binding("orchestrator", context=ToolContext(workspace_root=Path(tmp)))
            rendered = binding.render_tools()
            r2 = client.chat(
                [
                    {"role": "system", "content": "Use tools to delegate a coding task."},
                    {
                        "role": "user",
                        "content": (
                            "Delegate fixing add(a, b) in 'src/calc.py' to a worker using dispatch_worker."
                        ),
                    },
                ],
                tools=rendered["tools"],
            )
            parsed = binding.adapter.parse_response({"tool_calls": list(r2.tool_calls)})
            print(
                f"[2/3 tool_call] ok | latency={r2.latency_ms:.0f}ms | "
                f"reasoning_chars={r2.reasoning_chars} | parsed={parsed}"
            )

        # 3. Structured JSON output
        r3 = client.chat(
            [
                {"role": "system", "content": 'Return ONLY valid JSON: {"decision": "EXECUTE"|"SPLIT", "reason": "..."}.'},
                {"role": "user", "content": "Task: fix a 1-line return statement bug in calc.py. Decide EXECUTE or SPLIT."},
            ],
            response_format={
                "type": "object",
                "properties": {
                    "decision": {"type": "string", "enum": ["EXECUTE", "SPLIT"]},
                    "reason": {"type": "string"},
                },
                "required": ["decision", "reason"],
                "additionalProperties": False,
            },
        )
        parsed_json = json.loads(r3.content)
        print(
            f"[3/3 structured_json] ok | latency={r3.latency_ms:.0f}ms | "
            f"json={parsed_json} | usage={r3.usage.to_dict()}"
        )
        return True
    except (ProviderError, ValueError, json.JSONDecodeError) as exc:
        print(f"[CLOUD PROBE FAILED] {type(exc).__name__}: {exc}")
        return False


def probe_local(cfg: EndpointConfig) -> bool:
    print(f"\n=== LOCAL WORKER PROBE: {cfg.base_url} | model={cfg.model} | num_ctx={cfg.num_ctx} | think={cfg.think} ===")
    client = create_client(cfg)
    try:
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
            binding = create_tool_binding(
                "coder_worker",
                context=ToolContext(workspace_root=ws, allowed_paths=("calc.py",)),
            )
            rendered = binding.render_tools()
            r1 = client.chat(
                [
                    {"role": "system", "content": "Call read_file on calc.py now. No prose."},
                    {"role": "user", "content": "Read calc.py."},
                ],
                tools=rendered["tools"],
            )
            parsed = binding.adapter.parse_response({"tool_calls": list(r1.tool_calls)})
            print(
                f"[local tool_call] ok | latency={r1.latency_ms:.0f}ms | "
                f"reasoning_chars={r1.reasoning_chars} | usage={r1.usage.to_dict()} | parsed={parsed}"
            )
            return bool(parsed and parsed[0].name == "read_file" and parsed[0].parse_error is None)
    except ProviderError as exc:
        print(f"[LOCAL PROBE FAILED] {exc}")
        return False


def run_live_e2e(orch_cfg: EndpointConfig, worker_cfg: EndpointConfig) -> bool:
    print(f"\n=== LIVE HYBRID E2E: {orch_cfg.model} (cloud) -> {worker_cfg.model} (local) ===")
    with tempfile.TemporaryDirectory() as tmp:
        ws = Path(tmp)
        (ws / "src").mkdir()
        (ws / "tests").mkdir()
        (ws / "src" / "calc.py").write_text(
            "def add(a: int, b: int) -> int:\n    return a - b\n",
            encoding="utf-8",
        )
        (ws / "tests" / "test_calc.py").write_text(
            "import unittest\n"
            "from src.calc import add\n\n"
            "class CalcTest(unittest.TestCase):\n"
            "    def test_add(self):\n"
            "        self.assertEqual(add(2, 3), 5)\n"
            "        self.assertEqual(add(-1, 4), 3)\n",
            encoding="utf-8",
        )

        def on_event(name: str, data: dict) -> None:
            print(f"  [event] {name}: {data}")

        runner = HybridAgentRunner(
            ws,
            HybridRunConfig(
                orchestrator=orch_cfg,
                worker=worker_cfg,
                protected_paths=("tests/**",),
                include_run_command=True,
                max_orchestrator_turns=10,
                max_worker_turns=5,
                max_elapsed_sec=180.0,
            ),
            event_callback=on_event,
        )
        result = runner.run(
            "Fix the bug in src/calc.py so that tests/test_calc.py passes. "
            "Delegate the edit to the worker and verify by running `python -m unittest discover -s tests -v`."
        )
        print(
            f"\n[E2E RESULT] status={result.status} | modified={result.modified_files} | "
            f"orch_turns={result.orchestrator_turns} | worker_dispatches={len(result.worker_runs)} | "
            f"elapsed={result.elapsed_ms:.0f}ms | error={result.error}"
        )
        print("  orchestrator_usage:", result.orchestrator_usage.to_dict())
        print("  worker_usage:", result.worker_usage.to_dict())
        actual_code = (ws / "src" / "calc.py").read_text(encoding="utf-8")
        print("  actual src/calc.py:\n" + actual_code)

        proc = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
            cwd=ws,
            capture_output=True,
            text=True,
            timeout=30,
        )
        print(f"  independent unittest exit_code={proc.returncode}")
        if proc.returncode != 0:
            print(proc.stderr or proc.stdout)
        return result.status == "completed" and proc.returncode == 0


def main() -> int:
    load_dotenv(REPO_ROOT / ".env", override=False)
    parser = argparse.ArgumentParser(description="Live probe for Mini Hivo hybrid cloud+local models.")
    parser.add_argument(
        "--provider",
        choices=("groq", "nvidia", "openrouter", "cerebras", "gemini"),
        default="groq",
        help="Cloud orchestrator preset to test.",
    )
    parser.add_argument("--model", default=None, help="Optional cloud orchestrator model ID override.")
    parser.add_argument("--worker-model", default="qwen3.5:2b", help="Local Ollama worker model.")
    parser.add_argument("--worker-ctx", type=int, default=4096, help="Local Ollama worker num_ctx cap.")
    parser.add_argument("--local-only", action="store_true", help="Only test the local Ollama worker.")
    parser.add_argument("--cloud-only", action="store_true", help="Only test the cloud orchestrator.")
    parser.add_argument("--live-e2e", action="store_true", help="Run a real cloud+local temp-workspace fix test.")
    args = parser.parse_args()

    worker_cfg = ollama_worker(model=args.worker_model, num_ctx=args.worker_ctx, think=False)
    ok = True

    if not args.cloud_only:
        ok = probe_local(worker_cfg) and ok

    if not args.local_only:
        cloud_cfg = _build_cloud_config(args.provider, args.model)
        ok = probe_cloud(cloud_cfg) and ok
        if args.live_e2e and ok:
            ok = run_live_e2e(cloud_cfg, worker_cfg) and ok

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
