# Mini Hivo v2-Only Documentation Cutover, Rule Alignment & Live Hybrid Model Readiness

## Metadata

- **Date:** `2026-11-27`
- **Author:** `kareem`
- **Type:** `change`
- **Subsystem:** `docs / dev_rules / providers / hybrid`
- **Branch & Base Commit:** `feat/benchmark-harness-stage0` (base `dac866b`)
- **Status:** `verified`
- **Builds On:** [Stage 0 Benchmark Harness Hardening, Self-Test Suite & Host Preflight](../2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md)
- **Next / Open Issue:** Run live v2 prompt / E2E test with Groq (`qwen/qwen3.8-27b` or `openai/gpt-oss-120b`) + local Ollama `qwen3.5:2b-q4_K_M`, then wire user-facing v2 prompt CLI and computed `unified_diff` in `dispatch_worker`
- **Rule Proposal:** `[APPLIED 2026-11-27] AMEND AGENTS.md, dev_rules/orchestration_rules.md (v0.5), dev_rules/documentation_rules.md (v0.6), dev_rules/benchmarking_rules.md (v0.3): formalize v2-only active scope and retired v1 archive boundary`

## TL;DR

Completed the v2-only documentation and rule cutover across `README.md`, `docs/PROJECT_STATUS.md`, all living v2 architecture docs, all 10 legacy v1 markdown files in `docs/`, and (following explicit maintainer approval) `AGENTS.md` plus `dev_rules/{orchestration,documentation,benchmarking}_rules.md` so Mini Hivo is unambiguously **v2-only** with v1 (`mini.py`, `SingleModelPolicy`, Experiments 1–22, `reports/`, `updates/`) retired strictly to read-only history. Verified live hybrid model readiness on the host: local Ollama `qwen3.5:2b-q4_K_M` (`num_ctx=4096`, `think=False`) is **100% GPU-resident** on GTX 1650 (`1.60 GB` VRAM) and passes native `read_file` tool calling in **`883 ms`** warm (`92.2 s` cold warmup + retry), while both Groq cloud orchestrators (`qwen/qwen3.8-27b` and `openai/gpt-oss-120b`) pass live chat, reasoning, and native tool-call probes with **`998 / 1,000`** daily requests remaining (`8,000` TPM). All offline checks pass (`python scripts/check.py -v`: `71` ran, `69` passed, `0` failed, `2` Windows-symlink skips + live `INDEX.md --check` `[OK]`, `0` broken links, `0` whitespace errors).

---

## Setup & Environment

- **Code Revision:** `dac866bfe35c3a94969c7ad84ed4ae7ee0af8538` + uncommitted docs/rules updates
- **Hardware / Runtime:** Windows 11 (`10.0.26300`), Python `3.14.6`, NVIDIA GeForce GTX 1650 (`4096 MiB` VRAM), Ollama `0.40.18`, Docker `29.6.2`
- **Model(s) / Provider(s):**
  - Local Worker: Ollama `qwen3.5:2b-q4_K_M` (`Q4_K_M`, `num_ctx=4096`, `think=False`, `flash_attn=enabled`, KV `q8_0`, `1,604,939,937 / 1,604,939,937` bytes GPU resident = `100%`)
  - Cloud Orchestrator Candidates (Groq via `.env` `GROQ_API_KEY`):
    - `qwen/qwen3.8-27b` (`reasoning_effort=medium`, `reasoning_format=parsed`) — default preset in `groq_orchestrator()`
    - `openai/gpt-oss-120b` (`reasoning_effort=medium`, `reasoning_format=parsed`) — secondary Groq thinking candidate

---

## Problem & Root Cause

1. **Stale v1-first documentation and soft cutover rules:** Root [`README.md`](../../../../README.md) (901 lines) and [`docs/PROJECT_STATUS.md`](../../../PROJECT_STATUS.md) still presented retired v1 (`mini.py`, `gemma4:e4b`, `SingleModelPolicy`, Experiments 1–22) as the active Mini Hivo system; living v2 docs framed hybrid orchestration as *"opt-in"*; 8 of 10 legacy v1 docs in `docs/` had no archive banner; and `dev_rules/orchestration_rules.md §1` still read *"until a full cutover is authorized"*.
2. **Unverified live runtime state before live testing:** Needed empirical confirmation that local Ollama `qwen3.5:2b-q4_K_M` runs 100% GPU-resident with working native tool calling and which of the two Groq cloud orchestrator models has active quota and passing tool calls.

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| [`README.md`](../../../../README.md) | 901-line v1 `mini.py` / `gemma4:e4b` / Experiments 1–9 guide with zero mention of v2 packages | Rewrote cleanly for Mini Hivo v2 (`hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`, `hivo/benchmarks/`, `scripts/check.py`, `preflight`, `HybridAgentRunner`) + explicit retired-v1 archive notice | Primary repo entrypoint documents v2 exclusively and retires v1/experiments/updates/reports to read-only history | `python scripts/check.py -v` + link/diff audit |
| [`docs/PROJECT_STATUS.md`](../../../PROJECT_STATUS.md) | Dated `2026-11-21`, tracking only legacy `mini.py` v1 milestones | Rewrote for v2 (`2026-11-27`) covering all 4 v2 packages, Stage 0 verification, active v2 backlog, and retired-v1 archive boundary | Accurately reflects current v2 codebase & priorities | `python scripts/check.py -v` |
| [`docs/HYBRID_MODEL_STRATEGY.md`](../../../HYBRID_MODEL_STRATEGY.md), [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../ORCHESTRATION_ARCHITECTURE.md), [`docs/TOOLS_ARCHITECTURE.md`](../../../TOOLS_ARCHITECTURE.md), [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../BENCHMARKING_ARCHITECTURE.md) | Framed v2 as *"opt-in"* alongside active v1 baseline | Clarified that v2 **is** Mini Hivo and legacy v1 (`mini.py`, `SingleModelPolicy`, Experiments 1–22, `reports/`, `updates/`) is retired read-only history | Consistent v2-only framing across all living architecture docs | `git diff --check` + link audit |
| 10 legacy v1 docs in `docs/` (`PROJECT_GOAL.md`, `AGENT_ARCHITECTURE.md`, `TERMINAL_SESSIONS.md`, `EXPERIMENT_HISTORY.md`, `BRANCH_CONSOLIDATION.md`, `LIVE_E2E_VALIDATION.md`, `MANUAL_RUN_ANALYSIS.md`, `RESEARCH_DIRECTION.md`, `RESEARCH_AUDIT_NOTE.md`, `RESEARCH_PAPER.md`) | Soft scope notes (2 files) or no archival warning (8 files) | Added top-of-file `HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE)` warning banners while preserving paths so frozen archive links stay valid | Every legacy v1 doc visibly redirects readers to v2 without breaking frozen references | `git diff --check` + link audit |
| [`AGENTS.md`](../../../../AGENTS.md), [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md) (`v0.5`), [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md) (`v0.6`), [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) (`v0.3`) | Described v1 as *"baseline"* and kept *"until a full cutover is authorized"* in `orchestration_rules.md §1` | Applied maintainer-approved rule updates formalizing v2-only active scope and retiring v1 / Experiments 1–22 / `reports/` / `updates/` strictly to read-only historical archives (updating Revision Logs) | All coding agents and rules enforce v2-only development (`rule-approved` PR label required on publish) | `python scripts/check.py -v` + Swap-Test / link / `git diff --check` audit |

---

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Live host preflight (`groq` + `qwen3.5:2b-q4_K_M`) | `integration` *(zero LLM calls)* | Real Docker `29.6.2`, real disk stats, real `.env` (`GROQ_API_KEY` redacted), real Ollama `/api/tags` + `nvidia-smi` | `python -m hivo.benchmarks.preflight --provider groq --skip-docker` | `ready=True` (all required checks PASS; GTX 1650 `3850/4096 MiB` free before load) | `0` |
| Live local Ollama worker cold + warm tool-call probe | `live E2E` *(local model)* | Real Ollama `0.40.18` + `qwen3.5:2b-q4_K_M` (`num_ctx=4096`, `think=False`) + real `hivo.tools` `coder_worker` binding | `python -u scripts/probe_hybrid_models.py --local-only --worker-model qwen3.5:2b-q4_K_M` | Cold load: `PASS` (`92,184 ms` after 111.4s llama-server cold warmup + automatic retry); Warm: **`PASS` (`883 ms`, `reasoning_chars=0`, `read_file(path='calc.py')`, `parse_error=None`, `100%` GPU resident `1.60 GB` VRAM)** | `0` |
| Live Groq cloud orchestrator availability & quota probe (2 models) | `live E2E` *(cloud API)* | Real Groq `/openai/v1/chat/completions` + real `hivo.tools` `orchestrator` schema | Targeted 2-call probe per model (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`) via `groq_orchestrator(max_tokens=512, reasoning_effort='medium')` | Both **PASS**: `qwen/qwen3.8-27b` (`chat 485ms`, `reasoning_chars=44`, `tool_call 592ms` `['read_file']`, `998/1000` RPD, `6184/8000` TPM); `openai/gpt-oss-120b` (`chat 224ms`, `reasoning_chars=99`, `tool_call 562ms`, `reasoning_chars=88` `['list_files']`, `998/1000` RPD, `6512/8000` TPM) | `0` |
| Full active v2 offline test suite + worklog linter | `unit` + `integration` + `regression` | Strictly offline (zero LLM calls); real `update_worklog_index.py --check` | `python scripts/check.py -v` | `71` ran (`69` passed, `0` failed, `2` Windows-symlink skips) + `INDEX.md` `[OK]` | `0` |
| Working-tree diff gates + Markdown link & whitespace audit | `structural` | Real working-tree modified & added files (`23` files, with explicit maintainer rule authorization) | `evaluate_pr_diff_gates(..., allow_rule_edits=True)` + `git diff --check` + relative link scanner | `0` errors (`4` maintainer-authorized rule files verified), `0` broken relative links, `0` whitespace errors | `0` |

---

## Limitations & Known Gaps

- **No end-to-end user coding prompt executed yet:** Only lightweight health/tool-call probes were run (`2` tiny calls per Groq model + local worker probe); full live coding test is the next step.
- **No dedicated user-facing v2 CLI yet:** Running arbitrary prompts on v2 currently uses Python (`HybridAgentRunner`) or `scripts/probe_hybrid_models.py --live-e2e`; a dedicated v2 prompt CLI remains on the active backlog.
- **Cold-start local load time:** First cold start of `qwen3.5:2b-q4_K_M` on this host took `~111 s` in `llama-server` warmup (triggering one `180 s` timeout before automatic retry succeeded); once warm (`keep_alive="10m"`), native tool calls take `< 1 s` (`883 ms`).
- **PR label reminder:** Because maintainer-authorized rule files (`AGENTS.md` and `dev_rules/*.md`) were updated, any PR carrying these rule edits requires the `rule-approved` label (or isolating rule updates onto a dedicated rule-review PR per `dev_rules/how_to_make_rules.md §6.4`).

## Artifacts, Reproduction & Rule Proposals

- **Sibling Artifacts:** [`provenance.json`](provenance.json)
- **Living Docs Updated (`docs/`):** [`README.md`](../../../../README.md), [`docs/PROJECT_STATUS.md`](../../../PROJECT_STATUS.md), [`docs/HYBRID_MODEL_STRATEGY.md`](../../../HYBRID_MODEL_STRATEGY.md), [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../ORCHESTRATION_ARCHITECTURE.md), [`docs/TOOLS_ARCHITECTURE.md`](../../../TOOLS_ARCHITECTURE.md), [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../BENCHMARKING_ARCHITECTURE.md), plus retired-v1 archive banners on all 10 legacy v1 files in `docs/`.
- **Rule Updates Applied (`AGENTS.md` & `dev_rules/` — Explicit Maintainer Authorization):** [`AGENTS.md`](../../../../AGENTS.md), [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md) (`v0.4` → `v0.5`), [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md) (`v0.5` → `v0.6`), [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) (`v0.2` → `v0.3`).

```markdown
- Target: AGENTS.md, dev_rules/orchestration_rules.md §1, dev_rules/documentation_rules.md §1, dev_rules/benchmarking_rules.md (header)
- Action: AMEND
- Evidence: docs/worklogs/kareem/2026-11-27_v2-only-docs-and-live-model-readiness/REPORT.md
- Proposed Wording (Swap-Test compliant): Formalize Mini Hivo as v2-only (`hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`, `hivo/benchmarks/`) and explicitly mark legacy v1 (`mini.py`, `SingleModelPolicy`, Experiments 1–22, `reports/`, `updates/`) as retired read-only historical archives never used for active development, prompts, or new benchmarks.
- Status: APPLIED (explicit maintainer approval on 2026-11-27; updated orchestration_rules.md v0.5, documentation_rules.md v0.6, benchmarking_rules.md v0.3, and AGENTS.md)
```

- **Containing PR / Commit:** Pending (uncommitted on branch `feat/benchmark-harness-stage0`, base `dac866b`)

```powershell
python scripts/update_worklog_index.py --check
python scripts/check.py -v
python -m hivo.benchmarks.preflight --provider groq --skip-docker
python -u scripts/probe_hybrid_models.py --local-only --worker-model qwen3.5:2b-q4_K_M
git diff --check
```
