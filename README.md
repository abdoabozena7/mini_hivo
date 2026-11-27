# Mini Hivo

Mini Hivo is an **asymmetric two-tier coding-agent architecture (v2)** that pairs a **cloud reasoning Orchestrator** with a **lightweight, 100% GPU-resident local Worker** over a standalone, framework-free tool and verification harness.

- **Current Status & Roadmap:** [`docs/PROJECT_STATUS.md`](docs/PROJECT_STATUS.md) · [`docs/worklogs/INDEX.md`](docs/worklogs/INDEX.md) *(newest-first team radar)*
- **Living Architecture Docs:** [`docs/TOOLS_ARCHITECTURE.md`](docs/TOOLS_ARCHITECTURE.md) · [`docs/ORCHESTRATION_ARCHITECTURE.md`](docs/ORCHESTRATION_ARCHITECTURE.md) · [`docs/HYBRID_MODEL_STRATEGY.md`](docs/HYBRID_MODEL_STRATEGY.md) · [`docs/BENCHMARKING_ARCHITECTURE.md`](docs/BENCHMARKING_ARCHITECTURE.md) · [`docs/BENCHMARK_SCORECARD.md`](docs/BENCHMARK_SCORECARD.md)
- **Engineering Rules & Workflows:** [`AGENTS.md`](AGENTS.md) · [`dev_rules/tool_rules.md`](dev_rules/tool_rules.md) · [`dev_rules/orchestration_rules.md`](dev_rules/orchestration_rules.md) · [`dev_rules/benchmarking_rules.md`](dev_rules/benchmarking_rules.md) · [`dev_rules/documentation_rules.md`](dev_rules/documentation_rules.md)

---

## Architecture (Active v2 Codebase)

Mini Hivo is built as four stdlib-first Python packages under `hivo/`:

| Package | Responsibility | Key Entrypoints / Specs |
| :--- | :--- | :--- |
| [`hivo/tools/`](hivo/tools/) | Standalone framework-free tool layer: Hashline `edit_file`, AST/brace `code_intel`, `@scratch/` checkpoints, `run_command` confinement, `ToolProtocolAdapter` (`native` / `grammar_json` / GBNF / `xml_tags`), static `ToolBinding`, and `spawn_worker_binding()` fencing | [`docs/TOOLS_ARCHITECTURE.md`](docs/TOOLS_ARCHITECTURE.md) |
| [`hivo/providers/`](hivo/providers/) | Stdlib-only (`urllib.request`) provider-agnostic transport for OpenAI-compatible cloud endpoints (`groq`, `nvidia`, `openrouter`, `cerebras`, `gemini`) and local Ollama, with `.env` secret isolation, `<think>`/`reasoning_content` telemetry stripping, and deadline-clamped `429`/`5xx` backoff | [`docs/ORCHESTRATION_ARCHITECTURE.md`](docs/ORCHESTRATION_ARCHITECTURE.md), [`docs/HYBRID_MODEL_STRATEGY.md`](docs/HYBRID_MODEL_STRATEGY.md) |
| [`hivo/hybrid/`](hivo/hybrid/) | Asymmetric two-tier runtime (`HybridAgentRunner`): cloud thinking Orchestrator (`think=True`, read/plan/verify/delegate only — never writes code directly) + fenced 3-tool local Worker (`read_file`, `edit_file`, `write_file`; `think=False`, capped `num_ctx`, `O(target_files)` atomic byte rollback, 2-pass anchor-pinned history compaction) | [`docs/ORCHESTRATION_ARCHITECTURE.md`](docs/ORCHESTRATION_ARCHITECTURE.md) |
| [`hivo/benchmarks/`](hivo/benchmarks/) | Sealed evaluation & verification core: `.git` history stripping, `--network none` isolation, pre-solve Baseline Oracle quarantine (`INVALID_BASELINE`), final-diff protected-path anti-tamper gating, deterministic trace cheat-scanner, 3-key KPI aggregator (`pass^k`, `$/resolved`, cache hit `%`), and zero-LLM host preflight CLI | [`docs/BENCHMARKING_ARCHITECTURE.md`](docs/BENCHMARKING_ARCHITECTURE.md), [`docs/BENCHMARK_SCORECARD.md`](docs/BENCHMARK_SCORECARD.md) |

---

## Quick Start

### 1. Offline Verification Gate (No API Keys, Ollama, or Docker Required)

Every contributor and CI run shares the same strictly offline check suite:

```powershell
python scripts/check.py                  # Full active v2 offline test suite + worklog INDEX check
python scripts/check.py --tools          # hivo/tools offline tests only
python scripts/check.py --orchestration  # hivo/providers + hivo/hybrid offline tests only
python scripts/check.py --benchmarks     # Stage 0 benchmark self-tests only
python scripts/check.py --worklogs       # Worklog & INDEX.md hygiene checks only
```

### 2. Local + Cloud Setup (For Live Runs)

1. **Configure a cloud orchestrator API key in gitignored `.env`:**
   ```powershell
   Copy-Item .env.example .env
   ```
   Fill in one OpenAI-compatible provider key (`GROQ_API_KEY`, `NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, or `CEREBRAS_API_KEY`). Switching providers or moving from free dev endpoints to paid production endpoints requires changing `EndpointConfig` only — zero architecture changes. See [`docs/HYBRID_MODEL_STRATEGY.md`](docs/HYBRID_MODEL_STRATEGY.md).
2. **Start Ollama with a GPU-resident local worker** (e.g., `qwen3.5:2b-q4_K_M` for 4 GB VRAM hosts):
   ```powershell
   ollama pull qwen3.5:2b-q4_K_M
   ```
3. **Run the zero-LLM host preflight before spending tokens:**
   ```powershell
   python -m hivo.benchmarks.preflight --provider groq --worker-model qwen3.5:2b-q4_K_M
   # Add --skip-docker when running outside containerized benchmarks
   ```

### 3. Running Live Probes, Prompts & Benchmarks

- **Smoke probe & disposable live E2E test** ([`scripts/probe_hybrid_models.py`](scripts/probe_hybrid_models.py)):
  ```powershell
  python scripts/probe_hybrid_models.py --local-only --worker-model qwen3.5:2b-q4_K_M
  python scripts/probe_hybrid_models.py --provider groq --worker-model qwen3.5:2b-q4_K_M --live-e2e
  ```
- **Run a task programmatically via `HybridAgentRunner`:**
  ```python
  from hivo.hybrid import HybridAgentRunner, HybridRunConfig
  from hivo.providers import groq_orchestrator, load_dotenv, ollama_worker

  load_dotenv(".env")
  runner = HybridAgentRunner(
      workspace_root="path/to/workspace",
      config=HybridRunConfig(
          orchestrator=groq_orchestrator(model="qwen/qwen3.8-27b"),
          worker=ollama_worker(model="qwen3.5:2b-q4_K_M", num_ctx=4096, think=False),
      ),
  )
  result = runner.run("Describe the coding task here.")
  print(result.status, result.modified_files, result.final_response)
  ```
- **Sealed containerized SWE-bench calibration** ([`scripts/run_swebench_hybrid.py`](scripts/run_swebench_hybrid.py), requires Docker):
  ```powershell
  python scripts/run_swebench_hybrid.py --provider groq --worker-model qwen3.5:2b-q4_K_M --preflight-only
  ```

---

## Contributing & Worklogs

- Follow [`AGENTS.md`](AGENTS.md) and read the matching subsystem guardrail in `dev_rules/` before editing code.
- Record active team work in `docs/worklogs/<person>/` (Tier 2 dossiers or Tier 1 `LOG.md`) and regenerate [`docs/worklogs/INDEX.md`](docs/worklogs/INDEX.md) with `python scripts/update_worklog_index.py`.
- All rule files (`AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md`, `dev_rules/*.md`) are strictly read-only during normal work (propose updates via worklogs).

---

## Historical Archive (Retired v1 — Do Not Use)

Mini Hivo is **v2 only**. The legacy **v1 single-local-model prototype** and its old experiment pipeline are **retired and no longer used or maintained**:

- `mini.py` and legacy single-model `hivo/*.py` modules (`SingleModelPolicy`, `gemma4:e4b` CLI, legacy `list/project-N` sessions)
- The legacy experiment route (`scripts/experiment1_*.py`–`scripts/experiment22_*.py`, `reports/experiment1`–`reports/experiment22`, `docs/EXPERIMENT_HISTORY.md`)
- `reports/` and `updates/` (chronological historical records preserved read-only for provenance — including Experiment 23's pre-Stage-0 v2 Day-0 anchor)
- Legacy v1 charters and reports in `docs/` (`PROJECT_GOAL.md`, `AGENT_ARCHITECTURE.md`, `RESEARCH_PAPER.md`, `RESEARCH_DIRECTION.md`, `RESEARCH_AUDIT_NOTE.md`, `TERMINAL_SESSIONS.md`, `LIVE_E2E_VALIDATION.md`, `MANUAL_RUN_ANALYSIS.md`, `BRANCH_CONSOLIDATION.md`, `EXPERIMENT_HISTORY.md`), each explicitly marked as retired historical archive.

Keep these historical artifacts untouched for provenance; build, test, and run exclusively on the **v2** packages (`hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`, `hivo/benchmarks/`).
