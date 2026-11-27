# Orchestration & Providers Architecture (`docs/ORCHESTRATION_ARCHITECTURE.md`)

> - **Status:** Living current-state implementation documentation (`hivo/providers/` + `hivo/hybrid/`)
> - **Governing Rules:** [`../dev_rules/orchestration_rules.md`](../dev_rules/orchestration_rules.md) *(prescriptive guardrails & capability floors)*
> - **Deployment & Provider Reference:** [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md) *(4 GB VRAM tuning, free dev vs. paid target cloud providers, deferred research tracks)*
> - **Active v2 Runtime:** `hivo/providers/` + `hivo/hybrid/` is Mini Hivo's sole active orchestration engine (v2-only), with zero dependencies on the retired v1 historical archive (`mini.py`, `SingleModelPolicy`, `updates/`, `reports/`). Historical creation provenance is preserved read-only in `updates/R_UPDATE_011.md` and `reports/experiment23/`.

---

## 1. Package Module Inventory

### 1.1 Provider-Agnostic Transport Layer (`hivo/providers/`)

| Module | Responsibility | Key Exports / Symbols |
| :--- | :--- | :--- |
| [`env.py`](../hivo/providers/env.py) | Zero-dependency `.env` loader and secret-safe API key resolution (never returns or logs secret values) | `load_dotenv`, `resolve_api_key` |
| [`types.py`](../hivo/providers/types.py) | Frozen endpoint configuration, normalized response & token usage dataclasses, error types, and config-driven endpoint presets | `EndpointConfig`, `TokenUsage`, `ModelResponse`, `ProviderError`, `ProviderConfigError`, `ProviderType`, `StructuredMode`, `DEFAULT_OLLAMA_BASE_URL`, `MAX_LOCAL_WORKER_CTX` (`8192`), `groq_orchestrator`, `nvidia_nim_orchestrator`, `gemini_orchestrator`, `openrouter_orchestrator`, `cerebras_orchestrator`, `ollama_worker` |
| [`clients.py`](../hivo/providers/clients.py) | Stdlib-only (`urllib.request`) OpenAI-compatible cloud client and local Ollama client with wire-format normalization, `<think>`/`reasoning_content` extraction, structured-output fallback, and retryable HTTP backoff (`Retry-After` + Go-style `x-ratelimit-reset-*` duration parser clamped to monotonic deadline) | `ModelClient`, `OpenAICompatClient`, `OllamaClient`, `RawHttpResponse`, `create_client`, `normalize_tool_calls`, `strip_think_blocks`, `extract_rate_limit_headers` |
| [`__init__.py`](../hivo/providers/__init__.py) | Public package surface | Re-exports all config types, presets, clients, and env helpers |

### 1.2 Asymmetric Orchestrator + Worker Runtime (`hivo/hybrid/`)

| Module | Responsibility | Key Exports / Symbols |
| :--- | :--- | :--- |
| [`prompts.py`](../hivo/hybrid/prompts.py) | Role-specific compact system prompts and worker packet formatter (one-small-problem-at-a-time orchestrator planning/delegation/diff-audit rules; ultra-compact worker stop-on-success rules) | `build_orchestrator_system_prompt`, `build_worker_system_prompt`, `format_worker_task_prompt` |
| [`runner.py`](../hivo/hybrid/runner.py) | End-to-end asymmetric loop over `hivo.tools.ToolBinding` and `hivo.providers`: orchestrator turn routing, two-pass anchor-pinned `_compact_history()`, `dispatch_worker` execution, `O(target_files)` atomic byte snapshot/rollback, computed pre/post `unified_diff` handoff (`_compute_snapshot_diff`), circuit breakers, and event callbacks | `HybridAgentRunner`, `HybridRunConfig`, `WorkerRunReport`, `HybridRunResult` |
| [`__init__.py`](../hivo/hybrid/__init__.py) | Public package surface | Re-exports runner, config/result dataclasses, and prompt builders |

### 1.3 Live Smoke & Benchmark Harnesses (`scripts/`)
- [`scripts/probe_hybrid_models.py`](../scripts/probe_hybrid_models.py): Standalone smoke probe verifying local worker tool calling, cloud chat/thinking/tool-call/structured JSON + rate-limit headers, and optional `--live-e2e` toy bugfix run.
- [`scripts/run_swebench_hybrid.py`](../scripts/run_swebench_hybrid.py): Zero-leakage official `SWE-bench Verified` Docker runner with streaming `tarfile` extraction (preserving `.git` and Windows `core.symlinks=false` stubs), universal conda activation, pre-solve `[ENV OK]` + baseline oracle check, and 1-image-at-a-time cleanup.

---

## 2. Core Runtime Flow & Current Guarantees

```text
User Task
  -> HybridAgentRunner.run(workspace_root, task)
     1. Build static orchestrator ToolBinding (auto-omits ask_user if headless; attaches extra_orchestrator_tools & optional run_command)
     2. Orchestrator Loop (up to max_orchestrator_turns, max_elapsed_sec):
        - Run 2-pass anchor-pinned _compact_history() (preserves messages[0..1], shrinks older tool outputs first, then oversized tail outputs)
        - Call cloud/orchestrator client (think=True, strips reasoning into telemetry)
        - Execute read/plan/verify tools or dispatch_worker(packet):
            a. Snapshot exact bytes of ONLY packet.target_files (O(target_files))
            b. Spawn fenced static coder worker ToolBinding (default 3 tools: read_file, edit_file, write_file)
            c. Run worker sub-loop (think=False, capped num_ctx, max_worker_turns, max_consecutive_worker_errors=2)
            d. On failure/max-turns/error-abort: restore exact snapshotted bytes via atomic_write_bytes (delete newly created files) and emit empty unified_diff
            e. On success: compute bounded pre/post unified_diff from target_snapshot vs. disk bytes (_compute_snapshot_diff) and return WorkerRunReport + unified_diff to orchestrator
     3. Return HybridRunResult (status, modified_files, per-tier TokenUsage, WorkerRunReports, trace)
```

### Key Configuration Defaults (`HybridRunConfig`)
- `max_orchestrator_turns = 16`, `max_worker_turns = 6`, `max_worker_dispatches = 6`, `max_consecutive_worker_errors = 2`
- `orchestrator_max_read_lines = 200`, `orchestrator_max_output_chars = 16_000`, `worker_max_read_lines = 180`
- `max_history_chars = 20_000`, `worker_max_history_chars = 10_000`, `max_worker_diff_chars = 2_400`, `max_elapsed_sec = 300.0`, `auto_checkpoint_worker = True`
- `protected_paths: tuple[str, ...] = ()`, `extra_orchestrator_tools: tuple[ToolSpec, ...] = ()`

### Known Current Gaps (Tracked in `dev_rules/orchestration_rules.md` & Pending Rule Proposals)
- `_compact_history()` currently counts only `message["content"]` length and does not yet include serialized `assistant.tool_calls` JSON payloads (exposed by Groq `7K` ITPM `HTTP 413` in [`2026-11-27_breakout-visual-repair-hybrid-ablation`](worklogs/kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md)).
- Inline post-edit syntax validation in `hivo/tools/base.py` covers `.py`, `.json`, and `.js`, but does not yet validate `.css` brace balance.
- Contract-complete multi-file decomposition ($\kappa \ge 0.90$), declarative per-leaf verification oracles (DCVG), and `< ~60`-line greenfield whole-file atomic rewrite are not yet wired into `hivo/hybrid/runner.py`.

---

## 3. Standalone Offline Verification Suite

All provider normalization, backoff parsing, `.env` isolation, history compaction, worker fencing, circuit breakers, and atomic rollback behaviors are verified offline with zero LLM calls:

```powershell
python -m unittest tests.test_providers tests.test_hybrid_runner -v
```
