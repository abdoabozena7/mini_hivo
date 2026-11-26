# R_UPDATE_011 — Provider-agnostic hybrid cloud orchestrator (`hivo/providers/`) and local worker runtime (`hivo/hybrid/`)

## A. Update Identification

- **Update ID:** R_UPDATE_011
- **Date and timezone:** 2026-11-26; Africa/Cairo (UTC+02:00)
- **Title:** Provider-agnostic hybrid cloud orchestrator (`hivo/providers/`) and local worker runtime (`hivo/hybrid/`)
- **Status and verified scope:** Completed for standalone provider unit tests, controlled functional multi-turn E2E tests, local Ollama `qwen3.5:2b` / `qwen3.5:2b-q4_K_M` live probes, live Groq `qwen/qwen3.8-27b` cloud probes, and live cloud-to-local single-file fix verification (`src/calc.py` + `unittest`). Multi-repo `SWE-bench Verified` evaluation is documented separately in Experiment 23 / `R_UPDATE_012`. Legacy `mini.py` (`SingleModelPolicy`) remains untouched.
- **Branch:** `feat/hybrid-providers`
- **Actual base revision:** `047179f6a71a6e51c781a4b880a5381518af32e5` (`feat/hivo-tools`, open upstream PR #5 over `upstream/main` `3c870a64728316c94b581ea98aacec12dc77706e`).
- **Tested source revision/hashes:** Base `047179f` plus new/updated files verified via LF-normalized SHA-256:
  - `hivo/providers/env.py`: `6a7ca2fd61ca37cfaf23c56d8d8c441f65ac119f5faa95fe1722cd0ea664b961`
  - `hivo/providers/types.py`: `c390add71f6958494246022af252ee5d511bd403da7d97e11d5e183fb456915f`
  - `hivo/providers/clients.py`: `16df76440a25ef9fc952b33bf3942103aeb394fdf69b23b1986fe8ec8356a9ac`
  - `hivo/hybrid/prompts.py`: `4e06981ced85c17978a1b2977c69cdcffa6a70dec07a47e242bbabc445b2ae7b`
  - `hivo/hybrid/runner.py`: `def1b774df107450ebf0b07ca273436c732eebae848320568952e04a4debcdd7`
  - `scripts/probe_hybrid_models.py`: `5cc5814680bb86ff373461811e71d54cd4d8e12e955a71b984dc5f1fa1a84fd2`
- **Containing commit / PR:** Recorded in Git history and upstream PR metadata on `abdoabozena7/mini_hivo` upon publication.
- **Related issue/experiment:** Builds directly on PR #5 (`feat/hivo-tools`, [R_UPDATE_010.md](R_UPDATE_010.md)); evaluated on SWE-bench Verified in follow-up Experiment 23.
- **Scope:** Adds a stdlib-only provider layer (`hivo/providers/`), an asymmetric Cloud Thinking Orchestrator + Local Light Worker runtime (`hivo/hybrid/`) wired onto `hivo/tools/ToolBinding`, hybrid architecture documentation (`docs/HYBRID_MODEL_STRATEGY.md`), `.env` gitignore safety + `.env.example`, a live probe CLI (`scripts/probe_hybrid_models.py`), and offline unit + controlled functional test suites (`tests/test_providers.py`, `tests/test_hybrid_runner.py`). `mini.py` and `hivo/model_policy.py` are intentionally untouched.

## B. Original Problem

- **Original request to Mini Hivo:** Wire a swappable cloud thinking orchestrator (e.g., `Qwen3.8-27B` via a free dev API initially, upgradeable to paid endpoints via config alone) together with a lightweight local worker (`qwen3.5:2b` on a 4 GB VRAM GPU) on top of the standalone `hivo/tools/` layer without modifying legacy `mini.py`.
- **Expected behavior:**
  - Any OpenAI-compatible cloud provider (Groq, NVIDIA NIM, OpenRouter, Cerebras, Google AI Studio OpenAI endpoint) and local Ollama worker share one canonical `ModelResponse` envelope (`content`, normalized dict `tool_calls`, stripped `reasoning_chars` telemetry, `TokenUsage`, `rate_limit_headers`).
  - Local 2B workers enforce `think=False`, capped `num_ctx` (`<= 8192`), 3 flat tools (`edit_file`, `read_file`, `write_file`), strict path fences, fast-fail on repeated identical tool errors, and fast atomic rollback on worker failure.
  - Cloud thinking orchestrators run with reasoning enabled, never leak chain-of-thought into worker prompts, respect rate limits (`Retry-After` and `x-ratelimit-reset-*`) and run deadlines, and stay under tight single-request input budgets via 2-pass history compaction.
- **Observed behavior (before this update):** `feat/hivo-tools` (`047179f`) provided standalone tool units and `ToolBinding`, but contained no cloud OpenAI-compatible client, no Ollama worker client decoupled from `mini.py`, no `.env` gitignore rule, and no hybrid orchestrator-to-worker execution loop.
- **Execution evidence:** Confirmed on base `047179f`: neither `hivo/providers/` nor `hivo/hybrid/` existed, and `.gitignore` did not exclude `.env`.
- **Failure boundary:** Could not invoke cloud thinking orchestrators or local `qwen3.5:2b` workers through `hivo/tools/` without building a decoupled provider and runner layer.
- **Reproduction before the change:** Importing `hivo.providers` or `hivo.hybrid` on `047179f` raised `ModuleNotFoundError`.

## C. Why the Update Was Necessary

Running a 7B–27B orchestrator locally on a 4 GB VRAM GPU (such as GTX 1650) forces heavy CPU offload and stalls multi-turn coding loops, while running a 2B model monolithically without strong planning fails on repository localization and decomposition. Decoupling provider transport (`hivo/providers/`) from role execution (`hivo/hybrid/`) lets developers test on free OpenAI-compatible APIs today and switch to paid endpoints (OpenRouter, Cerebras, Chutes, DeepInfra) via a 3-field config swap with zero architectural rewrites, while keeping `mini.py`'s `SingleModelPolicy` research baseline intact.

## D. Root Cause Analysis

Key structural requirements and real-world runtime defects surfaced and fixed during live testing on GTX 1650 (4 GB VRAM) + Groq free tier:

| Finding | Classification | Supporting evidence | Remaining uncertainty |
|---|---|---|---|
| Base `047179f` had `hivo/tools/` but no model transport or hybrid runtime loop, and `.gitignore` did not ignore `.env` | Proven observation | Base commit `047179f` tree inspection and `.gitignore` diff | Legacy `mini.py` integration remains intentionally deferred |
| Groq's `qwen/qwen3.8-27b` defaulted to `reasoning_chars=0` until `reasoning_effort` (`low`/`medium`/`high`) was passed explicitly | Proven cause (observed live on Groq) | Live diagnostic showed `effort=None/default -> 0` vs `effort=medium -> 44-263` reasoning chars | Provider-specific thinking fields vary across non-Groq endpoints |
| Groq free tier enforces `8,000` TPM / `7,000` single-request ITPM with Go-style duration headers (`x-ratelimit-reset-tokens: 24.917s`) rather than always sending numeric `retry-after` | Proven cause (observed live HTTP `429` & `413` responses) | Fixed via `_parse_duration_seconds()` in `hivo/providers/clients.py` and 2-pass hard-bound `_compact_history()` in `hivo/hybrid/runner.py` | Paid endpoints have much higher limits; backoff simply stays idle |
| Full-repo `checkpoint(action="create")` inside `_run_worker` copied all files in multi-thousand-file repositories (~25 min on Django) even though workers are fenced to 1–2 `target_files` | Proven cause (observed during large-repo scaling test) | Replaced with exact `O(target_files)` atomic byte snapshot/restore in `hivo/hybrid/runner.py` (~2 ms) | Unfenced `allowed_paths=None` workers are not spawned by `spawn_worker_binding()` |
| Local `qwen3.5:2b` default Ollama tag (`Q8_0`, 2.94 GB) spilled ~1 GB to CPU on 4 GB VRAM, whereas official `qwen3.5:2b-q4_K_M` (1.60 GB) ran 100% GPU-resident | Proven empirical observation (`nvidia-smi` + `/api/ps`) | Live E2E wall time dropped from `86.4s` (`Q8_0`) -> `65.2s` (fixes) -> `37.3s` (`q4_K_M`) | Model quantization availability is external to repository code |

## E. What Changed

| File / symbol | Before behavior | Implementation change | After behavior | Evidence / test |
|---|---|---|---|---|
| [.gitignore](../.gitignore) & [.env.example](../.env.example) | `.env` not ignored; no template | Added `.env` / `.env.*` ignore rules (preserving `!.env.example`, `!.env.sample`, `!.env.template`) and added placeholder `.env.example` | Local API keys stay untracked; `git check-ignore -v .env` matches `.gitignore:6` | `git check-ignore -v .env` |
| [docs/HYBRID_MODEL_STRATEGY.md](../docs/HYBRID_MODEL_STRATEGY.md) | Absent | Added distilled strategy covering 4 GB VRAM worker rules, live-verified free/paid cloud providers, adapter invariants, and deferred research tracks | Concise engineering reference aligned with `tool_rules.md` | Direct review |
| [hivo/providers/env.py](../hivo/providers/env.py) | Absent | Added stdlib `load_dotenv()` (returns `{key: True}`, never values) and `resolve_api_key()` raising `ProviderConfigError` without leaking secrets | Zero-dependency secret resolution | [test_providers.py](../tests/test_providers.py) |
| [hivo/providers/types.py](../hivo/providers/types.py) | Absent | Added `EndpointConfig`, `ModelResponse`, `TokenUsage`, `ProviderError`/`ProviderConfigError`, and pure config preset factories (`groq_orchestrator`, `nvidia_nim_orchestrator`, `openrouter_orchestrator`, `cerebras_orchestrator`, `gemini_orchestrator`, `ollama_worker`) | Config-only provider swapping with zero hardcoded client branches | [test_providers.py](../tests/test_providers.py) |
| [hivo/providers/clients.py](../hivo/providers/clients.py) & [hivo/providers/__init__.py](../hivo/providers/__init__.py) | Absent | Added `OpenAICompatClient`, `OllamaClient`, `create_client()`, `strip_think_blocks()`, `normalize_tool_calls()`, `_parse_duration_seconds()` (`Retry-After` + `x-ratelimit-reset-*`), and wire-format message serialization | Unified response normalization, thinking isolation, explicit errors (no fabricated fallbacks), and `429`/`503` backoff obeying run deadlines | [test_providers.py](../tests/test_providers.py) |
| [hivo/hybrid/prompts.py](../hivo/hybrid/prompts.py) | Absent | Added concise `build_orchestrator_system_prompt()`, 2B-tuned `build_worker_system_prompt()`, and `format_worker_task_prompt()` | Compact, explicit stop-condition prompts without chain-of-thought bloat | [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| [hivo/hybrid/runner.py](../hivo/hybrid/runner.py) & [hivo/hybrid/__init__.py](../hivo/hybrid/__init__.py) | Absent | Added `HybridRunConfig`, `WorkerRunReport`, `HybridRunResult`, `_compact_history()` (2-pass hard-bound compaction), and `HybridAgentRunner` over `hivo/tools/ToolBinding` with 3-tool default worker (`edit_file`, `read_file`, `write_file`), `think=False`, non-interactive `ask_user` omission, `extra_orchestrator_tools`, `max_consecutive_worker_errors` fast-fail, and `O(target_files)` atomic rollback | End-to-end cloud orchestrator -> fenced local worker -> verification loop preserving `SingleModelPolicy` untouched | [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| [scripts/probe_hybrid_models.py](../scripts/probe_hybrid_models.py) | Absent | Added standalone CLI probe testing cloud chat/thinking/tools/JSON, local Ollama worker tools, and disposable `--live-e2e` fix verification | Reproducible live validation entry point | Live Groq + Ollama runs (Section G) |
| [tests/test_providers.py](../tests/test_providers.py) & [tests/test_hybrid_runner.py](../tests/test_hybrid_runner.py) | Absent | Added 11 provider unit tests and 5 controlled functional E2E tests | 16/16 offline automated coverage | Sections G and H |

## F. How the Fix Works

1. **Config-Driven Transport (`hivo/providers/`):** Callers configure cloud and local models purely via `EndpointConfig`. `create_client()` returns `OpenAICompatClient` (`/chat/completions`) or `OllamaClient` (`/api/chat`). Both emit identical `ModelResponse` objects: `<think>...</think>` and `reasoning_content` are stripped from `content` and counted only in `reasoning_chars` telemetry; OpenAI JSON-string `tool_calls.arguments` are parsed into dicts (preserving malformed strings so `ToolProtocolAdapter` emits self-correcting `ERR_TOOL_SCHEMA` envelopes); and `to_assistant_message(wire_format=...)` re-serializes history cleanly per wire format.
2. **Asymmetric Role Loop (`hivo/hybrid/runner.py`):** `HybridAgentRunner.run()` creates a static `orchestrator` `ToolBinding` (automatically omitting `ask_user` when `user_prompter is None`, and attaching optional `extra_orchestrator_tools`), runs a deadline-bounded loop with 2-pass `_compact_history()` protection, and routes `dispatch_worker` into `_run_worker()`.
3. **Fenced 4 GB VRAM Worker Execution (`_run_worker`):** Each dispatch snapshots exact bytes of `packet["target_files"]` in `O(targets)` time, spawns a 3-tool `coder_worker` `ToolBinding` via `spawn_worker_binding()`, forces `think=False` and capped `num_ctx`, aborts early on `max_consecutive_worker_errors` identical consecutive failures, and atomically restores `target_snapshot` bytes if the worker fails or leaves `syntax_ok=False`.

## G. Functional Verification

| Scenario / test | Verification class | Scripted/mocked boundaries versus real components | Expected behavior and oracle | Actual observed artifact/state | Result | Evidence |
|---|---|---|---|---|---|---|
| Full Cloud Orchestrator -> Fenced Local Worker -> `unittest` (`test_full_cloud_orchestrator_to_local_worker_fix_and_verify`) | Controlled functional | Scripted HTTP transports; **real** `OpenAICompatClient`, `OllamaClient`, `HybridAgentRunner`, `ToolBinding`, `spawn_worker_binding`, filesystem edits, syntax check, and `unittest` subprocess | Orchestrator thinking never leaks to worker; worker enforces `think=False`, `num_ctx=4096`, 3-tool set, blocks `src/secret_neighbor.py` (`ERR_PATH_SECURITY`), self-corrects syntax error, and passes real `unittest` (`exit_code=0`) | Exact disk bytes `return a + b`; `unittest` exited `0`; `ERR_PATH_SECURITY` observed once; zero thinking leakage | Pass | [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| Worker broken syntax rollback & repeated-error early abort (`test_broken_worker_edit_rolls_back_cleanly_via_checkpoint`, `test_worker_aborts_early_on_repeated_identical_tool_error`) | Controlled functional | Scripted transports; **real** atomic snapshot/rollback and filesystem | Broken syntax or 2 consecutive `EDIT_APPLY_ERROR` calls abort early and restore exact original bytes | Aborted at turn 2 (of 6), `rolled_back=True`, exact original bytes verified on disk | Pass | [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| Provider failure & preset config swap (`test_provider_failure_is_explicit_and_config_swap_works_across_presets`, `test_extra_orchestrator_tools_and_history_compaction`) | Controlled functional | Scripted HTTP 500 and Groq/NVIDIA/OpenRouter presets; **real** clients and 2-pass compaction | HTTP 500 returns explicit `status="provider_error"` (never fabricated); preset swap changes only `EndpointConfig`; bulky older tool outputs compacted | Observed explicit `provider_error`, matching endpoint URLs across all 3 presets, and `"compacted from"` in turn-5 payload | Pass | [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| Live Groq `qwen/qwen3.8-27b` (`reasoning_effort="medium"`) + Local Ollama `qwen3.5:2b-q4_K_M` (`think=False`, `num_ctx=4096`) disposable workspace fix | Live-model E2E | **Real** Groq API (`qwen/qwen3.8-27b`), **real** local Ollama (`qwen3.5:2b-q4_K_M` on GTX 1650 4 GB VRAM, `1.60/1.60 GB` VRAM), **real** filesystem and `unittest` subprocess | Cloud orchestrator inspects files, delegates edit to local 2B worker, verifies via `unittest`; independent post-run readback and `unittest` pass | Cloud probe: chat `278ms` (`reasoning_tokens=36`), tool call `1,190ms` (`reasoning_chars=263`), structured JSON `1,661ms`; live hybrid E2E completed in `37.3s` (`orch_turns=5`, `worker_dispatches=2`, Dispatch 2 `4.65s`), exact disk file `return a + b`, independent `unittest` `exit_code=0` | Pass | Verified via [probe_hybrid_models.py](../scripts/probe_hybrid_models.py) |

- **Run date, ID and source identity:** 2026-11-26 on `feat/hybrid-providers` (over `047179f`); Python `3.14.6`, Windows 11 (`10.0.26300`).
- **Exact reproduction commands:**
  - Offline: `python -m unittest tests/test_providers.py tests/test_hybrid_runner.py -v`
  - Live (requires `GROQ_API_KEY` in `.env` and local Ollama `qwen3.5:2b-q4_K_M`): `python -u scripts/probe_hybrid_models.py --provider groq --worker-model qwen3.5:2b-q4_K_M --live-e2e`
- **Live-model completion:** **Verified with fresh approved live runs** on Groq `qwen/qwen3.8-27b` + local Ollama `qwen3.5:2b` (`Q8_0` and `q4_K_M`) for the single-file toy fix. Non-Groq cloud presets (NVIDIA NIM, OpenRouter, Cerebras, Gemini) are unit-tested offline only and **unverified live** until credentials are supplied.

## H. Additional Successful Tests

| Suite / verification class | Fresh or historical; source revision | Exact command | Tests run | Passed | Failed / errors | Skipped | Exit / result | Relevance | Evidence |
|---|---|---|---:|---:|---:|---:|---|---|---|
| Provider unit & hybrid controlled functional | Fresh (2026-11-26); `feat/hybrid-providers` | `python -m unittest tests/test_providers.py tests/test_hybrid_runner.py -v` | 16 | 16 | 0 / 0 | 0 | Exit 0 (`OK`, `0.410s`) | Direct unit & controlled functional coverage of all new code | [test_providers.py](../tests/test_providers.py), [test_hybrid_runner.py](../tests/test_hybrid_runner.py) |
| Standalone tool layer regression | Fresh (2026-11-26); `feat/hybrid-providers` | `python -m unittest discover -s tests -p "test_tools_*.py"` | 37 | 35 | 0 / 0 | 2 | Exit 0 (`OK (skipped=2)`, `2.963s`) | Confirms zero regression in `hivo/tools/` | `tests/test_tools_*.py` |
| Verification outcome integrity regression | Fresh (2026-11-26); `feat/hybrid-providers` | `python -m unittest discover -s tests -p "test_verification_outcome_integrity.py"` | 31 | 31 | 0 / 0 | 0 | Exit 0 (`OK`, `0.760s`) | Confirms zero collateral impact on existing verification modules | [test_verification_outcome_integrity.py](../tests/test_verification_outcome_integrity.py) |
| Execution contracts regression | Fresh (2026-11-26); `feat/hybrid-providers` | `python -m unittest discover -s tests -p "test_execution_contracts.py"` | 36 | 36 | 0 / 0 | 0 | Exit 0 (`OK`, `1.684s`) | Confirms zero collateral impact on execution contracts | [test_execution_contracts.py](../tests/test_execution_contracts.py) |

Note: Counts above are per-command observations and are not summed across suites.

## I. Regression and Compatibility Impact

- **Potentially affected functionality/dependencies:** None in `mini.py` or `hivo/model_policy.py` — both are untouched. Only `.gitignore` was modified among tracked files (purely adding `.env` ignore protection).
- **Preserved behavior:** All 4 offline suites (`16`, `37` w/ 2 OS symlink skips, `31`, `36`) passed with zero failures/errors.
- **Skipped/excluded checks:** 2 pre-existing Windows `os.symlink` skips (`WinError 1314`) in `test_tools_*.py`; broad repo-wide `unittest discover -s tests` intentionally not run because `AGENTS.md` flags tests that can invoke live providers.
- **Untested/uncertain areas:** Live API behavior of NVIDIA NIM, OpenRouter, Cerebras, and Gemini presets (tested offline via transport mocks only); integration into `mini.py`'s legacy 17-role loop (explicitly out of scope).

## J. Overall Impact

Delivers a clean, stdlib-only, config-swappable Cloud Thinking Orchestrator + Local Light Worker runtime layered directly over `hivo/tools/`, proven offline (`16/16` tests) and live on a 4 GB GTX 1650 (`qwen3.5:2b-q4_K_M` 100% GPU-resident) paired with Groq `qwen/qwen3.8-27b` (`37.3s` live E2E) — without breaking `SingleModelPolicy` or adding third-party SDK bloat.

## K. Remaining Limitations

- **Live cloud coverage:** Only Groq (`qwen/qwen3.8-27b`) and local Ollama (`qwen3.5:2b`, `qwen3.5:2b-q4_K_M`) were tested live; NVIDIA NIM / OpenRouter / Cerebras / Gemini presets remain offline-tested only.
- **Groq free-tier rate limits:** `7,000` single-request ITPM, `8,000` TPM, and `200,000` TPD throttle multi-turn repo runs; switching to a higher-quota endpoint requires only changing `EndpointConfig`.
- **Worker edit visibility:** `dispatch_worker` currently returns modified filenames and the worker's text summary rather than a computed unified diff; adding an automatic diff summary from `target_snapshot` is a planned follow-up.
- **Larger real-repo benchmark:** Evaluated separately in follow-up Experiment 23 (`R_UPDATE_012`).

## L. Evidence and Reproduction

| Relative evidence link | Fresh / historical / sanitized derivative | Source/run identity | What it proves | What it does not prove |
|---|---|---|---|---|
| [tests/test_providers.py](../tests/test_providers.py) | Fresh offline unit suite | `feat/hybrid-providers` (2026-11-26) | `.env` resolution, preset round-trips, `<think>` stripping, tool-arg normalization, `429` duration backoff, secret-free errors | Live provider quotas or model intelligence |
| [tests/test_hybrid_runner.py](../tests/test_hybrid_runner.py) | Fresh offline controlled functional suite | `feat/hybrid-providers` (2026-11-26) | Cloud->worker delegation, thinking isolation, 3-tool fencing, rollback, repeated-error abort, 2-pass compaction, preset swap | Live multi-repo SWE-bench solve rate |
| [scripts/probe_hybrid_models.py](../scripts/probe_hybrid_models.py) | Fresh live verification harness | `feat/hybrid-providers` (2026-11-26) | Real Groq `qwen/qwen3.8-27b` thinking/tool/JSON + local `qwen3.5:2b-q4_K_M` 100% VRAM fix passing `unittest` | Generalization across large repositories |

```powershell
# Offline verification (zero network/API calls)
python -m unittest tests/test_providers.py tests/test_hybrid_runner.py -v
python -m unittest discover -s tests -p "test_tools_*.py"

# Optional live probe (requires GROQ_API_KEY in gitignored .env + local Ollama qwen3.5:2b-q4_K_M)
python -u scripts/probe_hybrid_models.py --provider groq --worker-model qwen3.5:2b-q4_K_M --live-e2e
```

- **Sanitization & secrets hygiene:** No `.env` file, API key, organization ID, or personal absolute path is included in any tracked file.

## M. Summary for the Team

**Proposed PR title:** `feat(hybrid): add provider-agnostic cloud orchestrator (hivo/providers) and local worker runner (hivo/hybrid)`

**Why needed:** Enable an asymmetric Cloud Thinking Orchestrator + 4 GB VRAM Local Worker architecture directly on top of `hivo/tools/` (PR #5) so development can start on free OpenAI-compatible APIs and swap to paid models via config only, without modifying `mini.py`'s `SingleModelPolicy` baseline.

**What changed / what was fixed:**
- Added stdlib-only `hivo/providers/` (`env.py`, `types.py`, `clients.py`) supporting OpenAI-compatible cloud endpoints (Groq, NVIDIA NIM, OpenRouter, Cerebras, Gemini presets) and local Ollama workers with thinking isolation, tool-arg normalization, `Retry-After` + `x-ratelimit-reset-*` duration backoff, and explicit failures.
- Added `hivo/hybrid/` (`prompts.py`, `runner.py`) wiring Cloud Thinking Orchestrator + fenced 3-tool Local Worker (`think=False`, capped `num_ctx`, `O(target_files)` atomic rollback, repeated-error fast-fail, 2-pass hard-bound history compaction, and `extra_orchestrator_tools` hook) over `hivo/tools/ToolBinding`.
- Added `.env` gitignore safety, `.env.example`, `docs/HYBRID_MODEL_STRATEGY.md`, `scripts/probe_hybrid_models.py`, and 16 offline unit/controlled-functional tests (`tests/test_providers.py`, `tests/test_hybrid_runner.py`).

**Functional verification:**
- Offline controlled functional + unit suites: **16/16 passed** (`0.41s`).
- Live E2E (`probe_hybrid_models.py --provider groq --worker-model qwen3.5:2b-q4_K_M --live-e2e`): **passed** in `37.3s` with real Groq `qwen/qwen3.8-27b` thinking (`reasoning_effort="medium"`) and 100% GPU-resident `qwen3.5:2b-q4_K_M` (`1.60/1.60 GB` VRAM on GTX 1650), verified by independent `unittest` (`exit_code=0`).

**Additional successful tests:** `test_tools_*.py` (`37` ran, `35` passed, `2` Windows symlink skips), `test_verification_outcome_integrity.py` (`31/31`), `test_execution_contracts.py` (`36/36`).

**Remaining issues:** Non-Groq cloud presets are offline-tested only; Groq free-tier rate limits (`7K` ITPM / `8K` TPM / `200K` TPD) constrain multi-turn repo batches; real-repo SWE-bench Verified results follow in stacked Experiment 23 PR.

**Publication state:** Committed on `feat/hybrid-providers` (stacked on PR #5 `feat/hivo-tools`), pushed to `origin` (`kareem232003/mini_hivo`), and opened as an upstream PR against `abdoabozena7/mini_hivo:main` per explicit user authorization.
