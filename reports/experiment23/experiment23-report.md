# Experiment 23 — Hybrid Cloud Thinking Orchestrator + 4 GB Local Worker Evaluation (`SWE-bench Verified`)

**26 November 2026. Status: `1/3` resolved overall on official `SWE-bench Verified` (`seed=42`, $N=3$); `1/2` resolved on non-quota-blocked tasks with valid Docker baselines (`django__django-16527` RESOLVED `F2P=1/1, P2P=6/6`). Offline unit, controlled functional, and regression suites all passed (`16/16` hybrid/provider, `37` tools w/ 2 OS symlink skips, `31/31` verification integrity, `36/36` execution contracts). Because $N=3$, this is a small-sample empirical checkpoint, not a universal reliability claim.**

For the preregistered inputs and acceptance boundaries, see [PROTOCOL.md](./PROTOCOL.md). For the underlying hybrid architecture update preceding this benchmark, see [R_UPDATE_011.md](../../updates/R_UPDATE_011.md).

## Research question

Can an asymmetric hybrid stack — **cloud thinking orchestrator (`qwen/qwen3.8-27b`) + 4 GB VRAM local worker (`qwen3.5:2b-q4_K_M`, `think=False`)** built over `hivo/tools/` — localize, patch, and resolve real repository issues on `princeton-nlp/SWE-bench_Verified` under independent official Docker container evaluation?

## System architecture summary (changes since Experiment 22)

Experiment 22 ran entirely offline on the legacy single-local-model `mini.py` architecture (`SingleModelPolicy`, `gemma4:e4b`). Every architectural shift introduced since Experiment 22 is additive and leaves `mini.py` and `SingleModelPolicy` untouched:

| Layer | Added In | Key Architectural Change |
|---|---|---|
| **Standalone Tool Layer** (`hivo/tools/`) | PR #5 (`R_UPDATE_010`) | 15 role-agnostic, flat-schema tools (Hashline `edit_file` + syntax checks, `code_intel` AST outlines, `@scratch/` checkpoints), 3-mode `ToolProtocolAdapter` (`native`/`grammar_json`/GBNF/`xml_tags`), `ToolProfile`, and static spawn-time `ToolBinding` + `spawn_worker_binding()` fencing. |
| **Provider-Agnostic Clients** (`hivo/providers/`) | PR #6 (`R_UPDATE_011`) | Stdlib-only `OpenAICompatClient` + `OllamaClient` driven strictly by `EndpointConfig` presets (free dev → paid swap via config only), `.env` secret isolation, `<think>`/`reasoning_content` stripping into telemetry, OpenAI JSON-string tool-arg normalization, and `Retry-After` + `x-ratelimit-reset-*` duration backoff. |
| **Hybrid Orchestrator + Local Worker Runtime** (`hivo/hybrid/`) | PR #6 (`R_UPDATE_011`) | `HybridAgentRunner` pairing a cloud thinking orchestrator (`think=True`, `reasoning_effort="medium"`, auto-omitting `ask_user` in non-interactive runs) with a 3-tool local worker (`edit_file`, `read_file`, `write_file`; `think=False`, `num_ctx=4096`), `max_consecutive_worker_errors=2` fast-fail, `O(target_files)` atomic byte rollback, 2-pass hard-bound history compaction, and `extra_orchestrator_tools`. |
| **SWE-bench Docker Harness** (`scripts/run_swebench_hybrid.py`) | Experiment 23 (`R_UPDATE_012`) | Zero-leakage official `SWE-bench Verified` runner: streaming `tarfile` extraction preserving `.git` + Windows `core.symlinks=false` link stubs, universal `/opt/miniconda3` activation, sandboxed `run_repo_tests`, independent baseline + candidate Docker container evaluation, and 1-image-at-a-time cleanup. |

## Empirical hardware & live smoke baseline (GTX 1650 4 GB VRAM)

Before running `SWE-bench Verified`, local worker residency and end-to-end latency were measured directly via `nvidia-smi`, Ollama `/api/ps`, and `scripts/probe_hybrid_models.py` on a 1-file Python bugfix (`src/calc.py` + `unittest`):

| Local Worker Tag | Loaded Size / VRAM (`ollama ps`) | GPU Residency | Live Hybrid E2E Wall Time | Local Dispatch 2 Time | Independent `unittest` |
|---|---|---:|---:|---:|---|
| `qwen3.5:2b` (`Q8_0`, initial) | `2.94 GB` / `1.91 GB` (`ctx=4096`) | ~65% (~1 GB CPU spill) | `86.4 s` | `8.28 s` | PASS (`exit 0`) |
| `qwen3.5:2b` (`Q8_0`, post-fixes + `effort=medium`) | `2.94 GB` / `1.91 GB` (`ctx=4096`) | ~65% (~1 GB CPU spill) | `65.2 s` *(incl. 13.9s cold load)* | `8.84 s` | PASS (`exit 0`) |
| **`qwen3.5:2b-q4_K_M` (`Q4_K_M`)** | **`1.60 GB` / `1.60 GB` (`ctx=4096`)** | **100% GPU resident (`1.60 GB` VRAM free)** | **`37.3 s`** | **`4.65 s`** | **PASS (`exit 0`)** |

Doubling `qwen3.5:2b` context from `4096` to `8192` under `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` increased total memory by only `+40 MB` (`2.94 GB -> 2.98 GB`), empirically confirming Qwen3.5's hybrid-attention (8/32 KV layers) memory profile.

## Official `SWE-bench Verified` results (`seed=42`, $N=3$)

All candidate patches were evaluated in fresh official `swebench/sweb.eval.x86_64.*` Linux containers against the hidden `test_patch`. Full machine-readable measurements are in [`experiment23-results.json`](experiment23-results.json).

| Instance ID | Repo & Difficulty | Baseline Oracle (`test_patch` only) | Candidate Oracle (`model_patch` + `test_patch`) | Resolved | Orch / Worker Tokens | Worker Dispatches (Rollbacks) | Key Finding |
|---|---|---|---|---|---:|---:|---|
| **`django__django-16527`** | `django/django` (`15m–1h`) | `F2P=0/1`, `P2P=6/6` (valid) | **`F2P=1/1`, `P2P=6/6`** | **YES (`True`)** | `15,722` / `5,758` | `1` (`0`) | **Solved on 1st worker dispatch (3 turns, `19.4s`).** Local `qwen3.5:2b-q4_K_M` wrote exact `+ and has_add_permission` in `django/contrib/admin/templatetags/admin_modify.py` ([patch](patches/django__django-16527.diff)). Turn 5 post-edit check hit Groq's 200K TPD after fix was saved. |
| **`pytest-dev__pytest-10051`** | `pytest-dev/pytest` (`15m–1h`) | `F2P=0/1`, `P2P=15/15` (valid) | `F2P=0/1`, `P2P=9/15` | **NO (`False`)** | `70,735` / `9,276` | `1` (`0`) | Orchestrator localized the **exact buggy line** (`src/_pytest/logging.py:345`, `self.records = []`), but local 2B replaced it with a **blank line** instead of `self.records.clear()` ([patch](patches/pytest-dev__pytest-10051.diff)). Orchestrator ran `run_repo_tests`, detected failures, and hit `max_turns=14` before re-dispatching. |
| **`psf__requests-1724`** | `psf/requests` (`<15m`) | `F2P=6/6`, `P2P=77/79` *(non-standard baseline)* | `F2P=6/6`, `P2P=77/79` | **NO (`False`, Quota Blocked)** | `3,019` / `0` | `0` (`0`) | Blocked on Turn 2 by Groq free-tier daily cap (`198,265 / 200,000` TPD exhausted across day's runs; `patch_bytes=0`). Baseline also showed non-standard `F2P=6/6` pre-patch in container. |

- **Overall resolved ($N=3$):** **`1 / 3` (`33.3%`, small sample $N=3$)**; **`1 / 2` (`50.0%`, $N=2$)** among non-quota-blocked tasks with valid failing baselines.

### Diagnostic harness defects caught and fixed during Experiment 23

In line with repository rigor, earlier aborted benchmark attempts are preserved rather than hidden. Running real multi-thousand-file repositories surfaced 4 concrete harness defects that were fixed and re-verified before the final measurements above:

1. **Groq `7,000` single-request ITPM cap (`HTTP 413` on aborted `psf__requests-1724` Turn 7, `7,171 > 7,000`):** Fixed via 2-pass hard-bound `_compact_history()` and `orchestrator_max_output_chars=4_000` in `hivo/hybrid/runner.py`; zero `413` errors occurred afterward across 14-turn runs.
2. **Official container conda path (`/opt/miniconda3` vs `/opt/conda`):** Fixed via universal conda detection + pre-solve `[ENV OK]` container check before spending any LLM tokens.
3. **Windows `docker cp` symlink privilege error (`WinError 1314`) and `lstrip("./")` stripping `.git`:** Fixed via streaming `docker cp ... -` + `tarfile` using prefix stripping (`./`) + Git-compatible `core.symlinks=false` link stubs + explicit `(dest_repo / ".git").exists()` assertion.
4. **Full-repo `checkpoint(action="create")` latency on 7,000-file Django (~25 min):** Replaced in `hivo/hybrid/runner.py` with `O(target_files)` atomic byte snapshots (~2 ms, 100% rollback fidelity).

## Offline verification and regression gate

Executed on base commit `886ea71a317af373bde7e4e0c3be9b8180288540` (Python `3.14.6`, Windows 11 `10.0.26300`, Docker `29.6.2`). Exact source SHA-256 digests are recorded in [`experiment23-provenance.json`](experiment23-provenance.json).

| Suite | Verification Class | Tests Run | Passed | Failed / Errors | Skipped | Exit |
|---|---|---:|---:|---|---:|---|
| `tests/test_providers.py` + `tests/test_hybrid_runner.py` | Unit + Controlled functional | 16 | 16 | 0 / 0 | 0 | `0` (`0.410s`) |
| `tests/test_tools_*.py` (8 files) | Tool unit + Controlled functional | 37 | 35 | 0 / 0 | 2 (`WinError 1314`) | `0` (`2.963s`) |
| `tests/test_verification_outcome_integrity.py` | Core offline regression | 31 | 31 | 0 / 0 | 0 | `0` (`0.760s`) |
| `tests/test_execution_contracts.py` | Core offline regression | 36 | 36 | 0 / 0 | 0 | `0` (`1.684s`) |

## Limitations and next engineering levers

- **Small sample size ($N=3$):** One resolved real-world Django issue proves end-to-end mechanism viability on 4 GB VRAM, not benchmark-wide solve rate.
- **Groq free-tier ceiling (`200K` TPD / `7K` ITPM):** Exhausted daily TPD during Task 3 (`198,265 / 200,000`). Larger slices (10–50 tasks) require a higher-quota endpoint (e.g., NVIDIA NIM, OpenRouter, Chutes, or Cerebras — a config-only change via `EndpointConfig`).
- **Highest-ROI harness improvement exposed by `pytest-dev__pytest-10051`:** Include a computed compact `unified_diff` directly inside `dispatch_worker`'s return payload (derived from `target_snapshot` in ~1 ms) so the cloud orchestrator immediately sees blank-line or mangled 2B edits on the very next turn rather than spending test turns discovering them.
- **Non-standard baseline on `psf__requests-1724`:** Pre-patch `F2P` reported `6/6` in the container; future `SWE-bench` slices should filter or flag instances whose baseline oracle does not reproduce `F2P < total`.
