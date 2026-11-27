# Mini Hivo — Project Status & Active v2 Roadmap (`docs/PROJECT_STATUS.md`)

> - **Status:** Living v2 project status (`2026-11-27`)
> - **Scope:** Mini Hivo is **v2 only** (asymmetric Cloud Thinking Orchestrator + Local Quantized Worker under `hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`, and `hivo/benchmarks/`).
> - **Retired v1 Notice:** The legacy v1 single-local-model system (`mini.py`, `SingleModelPolicy`, `gemma4:e4b`, Experiments 1–22, `reports/`, `updates/`) is **retired historical archive only** and is no longer used or maintained.
> - **Live Activity Radar:** [`worklogs/INDEX.md`](worklogs/INDEX.md) *(newest-first team activity)* · [`BENCHMARK_SCORECARD.md`](BENCHMARK_SCORECARD.md)

---

## 1. Active v2 Subsystems

| Subsystem | Status | Implementation | Living Spec & Guardrails |
| :--- | :--- | :--- | :--- |
| **Standalone Tool Layer** | Implemented & offline-verified | `hivo/tools/` (15 flat-schema tools, Hashline `edit_file`, AST/brace `code_intel`, `@scratch/` checkpoints, `ToolProtocolAdapter`, static `ToolBinding` + `spawn_worker_binding()`) | [`TOOLS_ARCHITECTURE.md`](TOOLS_ARCHITECTURE.md) · [`../dev_rules/tool_rules.md`](../dev_rules/tool_rules.md) |
| **Provider-Agnostic Clients** | Implemented; offline-verified + live-verified on Groq & Ollama | `hivo/providers/` (`OpenAICompatClient`, `OllamaClient`, `.env` secret isolation, `<think>`/`reasoning_content` stripping, deadline-clamped `429`/`5xx` backoff, config-only presets) | [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) · [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md) |
| **Asymmetric Hybrid Runtime** | Implemented; offline-verified + live-verified on single-file & SWE-bench anchor | `hivo/hybrid/` (`HybridAgentRunner`, cloud orchestrator + fenced 3-tool local worker, `think=False`, `O(target_files)` atomic rollback, 2-pass anchor-pinned history compaction, repeated-error abort) | [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) · [`../dev_rules/orchestration_rules.md`](../dev_rules/orchestration_rules.md) |
| **Stage 0 Sealed Benchmark Harness & Preflight** | Implemented & offline-verified (`7/7` Stage 0 self-tests) | `hivo/benchmarks/` (`decontamination.py`, `audit.py`, `metrics.py`, `preflight.py`) + hardened `scripts/run_swebench_hybrid.py` + `tests/test_benchmark_stage0.py` | [`BENCHMARKING_ARCHITECTURE.md`](BENCHMARKING_ARCHITECTURE.md) · [`../dev_rules/benchmarking_rules.md`](../dev_rules/benchmarking_rules.md) |
| **Governance, CI & Evidence Locker** | Active & enforced | `AGENTS.md`, `CLAUDE.md`, `dev_rules/`, `scripts/check.py`, `scripts/update_worklog_index.py`, `docs/worklogs/` | [`../dev_rules/documentation_rules.md`](../dev_rules/documentation_rules.md) · [`worklogs/INDEX.md`](worklogs/INDEX.md) |

> *"Implemented"* means the code path and deterministic offline tests exist. It does **not** claim universal live reliability across every repository or benchmark suite.

---

## 2. Current Working Point (`2026-11-27`)

- **Offline Gate (`python scripts/check.py`):** All active v2 offline test suites (`hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`, `hivo/benchmarks/`, and worklog/check gates) run deterministically with zero LLM calls and mirror `.github/workflows/ci.yml`.
- **Stage 0 Benchmarking Gate:** Completed and verified (`7/7` adversarial offline self-tests in `tests/test_benchmark_stage0.py`, live zero-LLM host preflight CLI `python -m hivo.benchmarks.preflight`, and sealed `.git` stripping / `--network none` / pre-solve `INVALID_BASELINE` quarantine / anti-tamper / trace cheat-scanning wired into `scripts/run_swebench_hybrid.py`). See [`worklogs/kareem/2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md`](worklogs/kareem/2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md).
- **Live Cloud + Local Baseline Anchor:**
  - Verified live on `GTX 1650` (`4 GB` VRAM) with local Ollama `qwen3.5:2b-q4_K_M` (`100%` GPU resident at `1.60 GB`, `num_ctx=4096`, `think=False`) paired with Groq cloud orchestrators (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`).
  - Historical pre-Stage-0 Day-0 SWE-bench anchor (Experiment 23, `N=3`, `seed=42`): `1/3` (`33%` raw) / `1/2` (`50%` valid non-blocked; `django__django-16527` resolved on 1st worker dispatch). Small-sample anchor only; sealed Stage 1 benchmarks are queued next. See [`BENCHMARK_SCORECARD.md`](BENCHMARK_SCORECARD.md).

---

## 3. Active v2 Engineering & Benchmark Backlog

| Priority | Milestone | Acceptance Evidence Needed |
| :--- | :--- | :--- |
| **Next** | **Computed `unified_diff` in `dispatch_worker`** (`hivo/hybrid/runner.py`) | Return compact pre/post `unified_diff` directly inside worker results (`dev_rules/orchestration_rules.md §6.2 [TARGET]`) with offline regression tests catching silent worker edit defects immediately. |
| **Next** | **User-facing v2 prompt CLI** | Provide a clean v2 CLI entrypoint (`HybridAgentRunner`) for running arbitrary local prompts/workspaces without writing boilerplate Python or touching retired `mini.py`. |
| **Stage 1** | **Higher-quota provider + Sealed Stage 1 Benchmarks** | Configure higher-quota cloud endpoint (`NVIDIA_API_KEY` or OpenRouter), install `harbor`, build Stage 1 `Terminal-Bench 4.1` adapter, and run sealed `SWE-bench` calibration + 3-arm Scaffold-Lift control (`Minimal` vs. `Orch-Only` vs. `Hybrid`). |
| **Upcoming** | **Contract-Complete Multi-File Decomposition ($\kappa \ge 0.90$) & DCVG** | Wire 5-dimension leaf contracts, `< ~60`-line greenfield atomic rewrite, and declarative per-leaf verification oracles into `hivo/hybrid/` (`dev_rules/orchestration_rules.md §3, §6`). |
| **Stage 3–4** | **Repeatability (`pass^k`), Anti-Cheat (`CHEATBENCH`) & Private Gold Gate** | Multi-trial runner (`n=5`), Stage 4A integrity battery, Stage 4B `SWE Atlas` mutation checks, and Stage 4D internal Private Gold regression suite. |

---

## 4. Retired Historical Archive (v1 — Do Not Use)

The earlier **v1 single-local-model baseline** (`mini.py`, `SingleModelPolicy`, `gemma4:e4b`, legacy `scripts/experiment1–22`, `reports/`, `updates/`, and historical v1 charters/notes in `docs/`) is **retired history**. Those artifacts remain preserved read-only for provenance only; all active engineering, testing, prompts, and benchmarks belong strictly to **v2**.
