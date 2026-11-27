# Neon Breakout Visual & Gameplay Repair — 4-Run Hybrid Ablation, `unified_diff` Upgrade & Root-Cause Triage

## Metadata

- **Date:** `2026-11-27`
- **Author:** `kareem`
- **Type:** `experiment`
- **Subsystem:** `hivo/hybrid / hivo/tools / live-ablation`
- **Branch & Base Commit:** `feat/benchmark-harness-stage0` (base `dac866b`)
- **Status:** `verified`
- **Builds On:** [Mini Hivo v2-Only Documentation Cutover, Rule Alignment & Live Hybrid Model Readiness](../2026-11-27_v2-only-docs-and-live-model-readiness/REPORT.md)
- **Next / Open Issue:** Fix `_compact_history()` to account for serialized `assistant.tool_calls` JSON (eliminating `HTTP 413`), add inline CSS brace-balance syntax checking in `hivo/tools/base.py`, and re-run Breakout with diff-checked retry + higher-ITPM cloud endpoint (`NVIDIA_API_KEY` or OpenRouter)
- **Rule Proposal:** `PROMOTE orchestration_rules.md §6.2 unified_diff -> ENFORCED; ADD orchestration_rules.md §5.2 tool_calls compaction accounting [TARGET]; AMEND tool_rules.md §4 Contract 4 CSS syntax check [TARGET]`

## TL;DR

Evaluated Mini Hivo v2 across 4 isolated live runs on a zero-hint 3-file Neon Breakout visual & gameplay repair task (`0/10` pre-solve baseline oracle) to separate Cloud Orchestrator decomposition, Harness feedback/compaction, and Local 2B Worker execution. Implementing computed `unified_diff` in `dispatch_worker` and explicit one-problem-at-a-time orchestrator instructions (`72` offline tests passing via `python scripts/check.py -v`) lifted `qwen/qwen3.8-27b` from skipping planning and regressing `.overlay-card` (`Run 1`: `1/10`, `32.2 s` Dispatch 1 + `game.js` rollback) to creating a clean 7-step `update_plan` and a `6.5 s` surgical `.hud` diff with zero regressions (`Run 2`: `1/10`), before `Run 2` (`7,016/7,000`) and `Run 3` (`7,373/7,000`) exposed a concrete bug in `_compact_history()` ignoring `assistant.tool_calls` JSON under Groq's `7,000` ITPM cap. A blind 1-shot Antigravity-to-real-2B Proof of Concept (`Run 4`: `3/10` in `80.5 s`, `$0` cloud tokens) proved local `qwen3.5:2b-q4_K_M` (`1.60 GB` VRAM) writes valid JS/CSS logic fast (`loadHighScore`/`saveHighScore`, `resetGame`, `togglePause`, `.overlay.hidden`) while exposing Hashline boundary off-by-one slips and missing inline CSS syntax validation — all immediately visible in the new `unified_diff` output. This is a Dev-Slice diagnostic ablation (`N=1` task × `4` runs), not a Held-Out leaderboard score.

---

## Setup & Environment

- **Code Revision:** `dac866bfe35c3a94969c7ad84ed4ae7ee0af8538` (Run 1: unmodified base; Runs 2–4: base + uncommitted `unified_diff` & one-by-one prompt implementation in `hivo/hybrid/runner.py`, `hivo/hybrid/prompts.py`, `hivo/tools/orchestration.py`)
- **Hardware / Runtime:** Windows 11 (`10.0.26300`), Python `3.14.6`, Node.js `v24.21.0`, Ollama `0.40.18`, NVIDIA GeForce GTX 1650 (`4096 MiB` VRAM, verified `100%` GPU resident `1.60 GB` VRAM, `flash_attn=enabled`, KV `q8_0`)
- **Model(s) / Provider(s):**
  - Cloud Orchestrator (Runs 1–3): Groq `qwen/qwen3.8-27b` (`reasoning_effort=medium`, `reasoning_format=parsed`, `max_tokens=2048`, `temperature=0.0`, free tier `7K` ITPM / `8K` TPM / `200K` TPD)
  - Controlled Orchestrator (Run 4 PoC): Scripted Antigravity 6-step sequential decomposition (`0` cloud calls, blind 1-shot without diff-inspection retries)
  - Local Worker (All 4 Runs): Ollama `qwen3.5:2b-q4_K_M` (`Q4_K_M`, `num_ctx=4096`, `think=False`, 3 tools: `read_file`, `edit_file`, `write_file`)
- **Protocol:** [`PROTOCOL.md`](PROTOCOL.md) (frozen 3-file `before/` app + hidden external 10-check Node oracle `verify_breakout.js`)

---

## Problem & Root Cause

Run 1 exposed three immediate architectural defects preventing Mini Hivo v2 from executing tasks one small problem at a time:
1. **No computed `unified_diff` in `dispatch_worker`:** `hivo/hybrid/runner.py` returned only the 2B worker's prose (`diff_summary`). When Dispatch 1 mistakenly wrote `display: none;` into `.overlay-card` instead of `.overlay.hidden`, the Orchestrator burned Turns 4–6 re-reading files instead of catching the error immediately.
2. **Orchestrator prompt lacked one-by-one sequential discipline:** `hivo/hybrid/prompts.py` did not forbid parallel multi-dispatch turns or multi-bug worker packets, so Turn 3 skipped `update_plan`, launched 2 parallel dispatches, and crammed all 4 JS bug groups into one truncated Dispatch 2 packet (which broke JS syntax and rolled back).
3. **Unaccounted `tool_calls` JSON in `_compact_history()` (exposed in Runs 2–3):** `hivo/hybrid/runner.py::_compact_history()` sums only `len(str(m.get("content") or ""))` and ignores `assistant.tool_calls` JSON payloads — allowing Groq requests to breach the `7,000` single-request ITPM limit (`7,016` on Run 2 Turn 7; `7,373` on Run 3 Turn 17) while aggressive `8K` content compaction erased Turn 2 reads and induced a 13-turn `read_file` amnesia loop in Run 3.

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| [`hivo/hybrid/runner.py`](../../../../hivo/hybrid/runner.py) (`HybridRunConfig`, `WorkerRunReport`, `_compute_snapshot_diff`, `HybridAgentRunner._run_worker`) | `dispatch_worker` returned only worker prose (`diff_summary`); `target_snapshot` only taken when `auto_checkpoint_worker=True` | Added `max_worker_diff_chars=2_400`, `WorkerRunReport.unified_diff`, stdlib `_compute_snapshot_diff()` (`O(target_files)`), always snapshotted targets, returned computed `unified_diff` on success (`""` on rollback/failure) and logged `diff_chars` in `worker_finished` | Orchestrator receives exact bounded pre/post `unified_diff` (~1 ms, zero extra turns); rollback clears diff to `""` | Red-first offline tests in `tests/test_hybrid_runner.py` (`72` suite pass) + live Runs 2–4 |
| [`hivo/tools/orchestration.py`](../../../../hivo/tools/orchestration.py) (`_handle_dispatch_worker`) | Normalized result omitted `unified_diff` | Forwarded `"unified_diff": str(raw_result.get("unified_diff", ""))` inside `ok_result` data (leaving `DISPATCH_WORKER_SPEC` schema hash unchanged) | `dispatch_worker` tool observations deliver `unified_diff` cleanly to Orchestrator | Red-first test in `tests/test_tools_exec_and_orch.py` |
| [`hivo/hybrid/prompts.py`](../../../../hivo/hybrid/prompts.py) (`build_orchestrator_system_prompt`) | General guidance; allowed parallel dispatches and multi-bug packets | Enforced explicit 5-step one-small-problem-at-a-time workflow (`update_plan`, targeted `read_file` right before each step, max 1 `dispatch_worker` per turn with 1 atomic edit, immediate `unified_diff` audit, `run_command` verify) | Run 2 Orchestrator emitted 7-step `update_plan` + 1 atomic `.hud` dispatch (`6.5 s` worker success, 0 regressions) | `test_worker_unified_diff_truncates_cleanly_and_prompt_enforces_one_by_one` + live Run 2 |
| [`tests/test_hybrid_runner.py`](../../../../tests/test_hybrid_runner.py) & [`tests/test_tools_exec_and_orch.py`](../../../../tests/test_tools_exec_and_orch.py) | No tests for `unified_diff`, rollback empty-diff, truncation, or one-by-one prompt | Added red-first positive + negative/boundary assertions (`unified_diff` present in turn-3 observation, `""` on syntax rollback, truncation boundary at `max_worker_diff_chars=300`, prompt invariants) | Proved `4` red failures before fix → `72` ran (`70` passed, `0` failed, `2` Windows-symlink skips) after fix | `python scripts/check.py -v` |
| [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../ORCHESTRATION_ARCHITECTURE.md) | Listed `unified_diff` in `dispatch_worker` under Known Current Gaps | Updated runtime flow, config defaults, and module inventory to reflect implemented `unified_diff` + newly diagnosed compaction/CSS gaps | Living doc synchronized with current v2 code | `python scripts/check.py -v` + link audit |

---

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Red-first failure proof (pre-fix) | `unit` + `controlled functional` | Scripted transports + real `HybridAgentRunner` & `hivo.tools` | `python -m unittest tests.test_tools_exec_and_orch tests.test_hybrid_runner` | `11` ran: `1` FAIL, `3` ERROR (confirmed assertions catch missing `unified_diff` & prompt rules) | `1` |
| Full active v2 offline test suite + worklog check (post-fix) | `unit` + `integration` + `regression` | Strictly offline (`0` LLM calls); all 13 active v2 suites + real `update_worklog_index.py --check` | `python scripts/check.py -v` | `72` ran (`70` passed, `0` failed, `2` pre-existing Windows-symlink skips) + `INDEX.md` `[OK]` | `0` |
| Pre-solve Baseline Oracle on frozen `before/` | `controlled functional` *(0 LLM calls)* | Real Node `v24.21.0` executing `verify_breakout.js` against `before/` | `node output/live_tests/2026-11-27_breakout-visual-repair/oracle/verify_breakout.js output/live_tests/2026-11-27_breakout-visual-repair/before` | `0 / 10` passed (`all_passed=false` — confirmed valid failing baseline) | `1` |
| Live Run 1 (Baseline v2 harness) | `live E2E` | Real Groq `qwen/qwen3.8-27b` + real Ollama `qwen3.5:2b-q4_K_M` + external Node oracle | `python -u output/live_tests/2026-11-27_breakout-visual-repair/run_live_test.py qwen/qwen3.8-27b qwen3.5:2b-q4_K_M` | `status=provider_error` (deadline `240.0 s`), **`1 / 10`** (`css_hud_no_overlap` PASS; `.overlay-card` regressed; `game.js` rolled back) | `1` |
| Live Run 2 (`+unified_diff`, `+1-by-1`, `14K` history) | `live E2E` | Real Groq `qwen/qwen3.8-27b` + real Ollama `qwen3.5:2b-q4_K_M` + external Node oracle | `python -u output/live_tests/2026-11-27_breakout-visual-repair-run2/run_live_test.py qwen/qwen3.8-27b qwen3.5:2b-q4_K_M` | `status=provider_error` (`HTTP 413` `7,016/7,000` ITPM at Turn 7), **`1 / 10`** (`7`-step plan, `6.5 s` surgical `.hud` diff, `0` regressions) | `1` |
| Live Run 3 (`+unified_diff`, `+1-by-1`, `8K` history) | `live E2E` | Real Groq `qwen/qwen3.8-27b` + real Ollama `qwen3.5:2b-q4_K_M` + external Node oracle | `python -u output/live_tests/2026-11-27_breakout-visual-repair-run3/run_live_test.py qwen/qwen3.8-27b qwen3.5:2b-q4_K_M` | `status=provider_error` (`HTTP 413` `7,373/7,000` ITPM at Turn 17), **`1 / 10`** (`8`-step plan, `13`-turn `read_file` compaction loop, `.hud` overwrote `body` selector) | `1` |
| Live Run 4 PoC (Scripted Antigravity → real 2B) | `controlled orchestrator / live local 2B` | Scripted 6-step blind Orchestrator (`0` cloud tokens) + **real** Ollama `qwen3.5:2b-q4_K_M` + real `HybridAgentRunner` + external Node oracle | `python -u output/live_tests/2026-11-27_breakout-visual-repair-poc-2b/run_poc.py` | `status=completed` (`80.5 s`), **`3 / 10`** (`css_overlay_hidden_nonblocking`, `pause_toggle_and_terminal_guard`, `restart_full_state_reset_preserves_highscore` PASS; `loadHighScore` verified `70`; `4` anchor boundary slips exposed in `unified_diff`) | `1` |

---

## Experiment Results & Intermediate Defects Caught

- **8-Point Anti-False-Result Truth Check (`dev_rules/benchmarking_rules.md §4`):** **`DIAGNOSTIC DEV-SLICE ONLY`** *(Not eligible for `docs/BENCHMARK_SCORECARD.md` promotion: local host run without Docker `--network none` or `.git` stripping [Check 1 N/A for local dev fixture]; Checks 2–4 & 6–8 verified PASS: `0/10` pre-solve baseline, external untouched oracle, `0` missing/skipped passes, full denominators preserved across all 4 runs, `100%` GPU residency verified, all numbers computed directly from JSON).*
- **Human Audit Tier:** `Spot-Checked (4/4 diffs & full traces inspected line-by-line)`
- **Headline Summary *(computed from [`results.json`](results.json), small sample $N=1$ task × `4` runs)*:**
  - Full live cloud+local runs (Runs 1–3): `0 / 3` (`0%`) full-task resolved (`1/10` checks passed in each; `3/3` terminated by Groq free-tier rate/ITPM limits: `1` deadline during `429` backoff, `2` `HTTP 413` ITPM breaches).
  - Controlled-Orchestrator → real local 2B PoC (Run 4, blind 1-shot, no diff retries): `0 / 1` full-task resolved, **`3 / 10` (`30%`)** checks passed (`5/6` dispatches syntactically valid, `1/6` rolled back cleanly) in **`80.5 s`**, **`$0.00`** cloud cost.

| Run / Case | Pre-Solve Oracle | Post-Run Oracle | Status | Bucket (`1–6`) | Key Metrics (Orch / Worker Tokens · Wall Time · Dispatches/Rollbacks) | Earliest Failure Turn & Factual Cause |
| :--- | :---: | :---: | :---: | :---: | :--- | :--- |
| **`run1_baseline_hybrid`** ([diff](patches/run1_baseline.diff)) | `0/10` | **`1/10`** | `BLOCKED` (`provider_error`) | `1` + `4` | Orch `33,854` tok (`7` turns, `plan=0`) · Worker `38,370` tok (`2` disp, `1` rb, `32.2s`+`26.9s`) · `240.0 s` | **Turn 3:** Skipped plan, parallel dispatches, truncated 4-bug JS packet → `SyntaxError` rollback; Dispatch 1 edited `.overlay-card` instead of `.overlay.hidden`; Turn 7 hit `240 s` deadline in Groq `429` backoff |
| **`run2_unified_diff_1by1_14k`** ([diff](patches/run2_unified_diff_14k.diff)) | `0/10` | **`1/10`** | `BLOCKED` (`HTTP 413`) | `1` | Orch `33,639` tok (`7` turns, `plan=7`) · Worker `5,052` tok (`1` disp, `0` rb, **`6.5 s`**) · `226.0 s` | **Turn 7:** After textbook 7-step plan + surgical 5-line `.hud` diff (`diff_chars=184`, `0` regressions), `max_history_chars=14_000` + unaccounted `tool_calls` JSON exceeded Groq's `7,000` ITPM cap (`7,016 / 7,000`) |
| **`run3_unified_diff_1by1_8k`** ([diff](patches/run3_unified_diff_8k.diff)) | `0/10` | **`1/10`** | `BLOCKED` (`HTTP 413`) | `1` + `2` | Orch `87,729` tok (`16,384` cached, `17` turns, `plan=8`) · Worker `5,580` tok (`1` disp, `0` rb, `8.9 s`) · `530.8 s` | **Turns 2–14 & 17:** Aggressive `8K` compaction shrank earlier reads → `13`-turn `read_file` amnesia loop; Turn 15 `.hud` edit overwrote `*`/`body` lines 8–20; Turn 17 still breached Groq `7,000` ITPM (`7,373 / 7,000`) due to uncounted `tool_calls` JSON |
| **`run4_poc_antigravity_to_2b`** ([diff](patches/run4_poc_2b.diff)) | `0/10` | **`3/10`** | `FAIL` *(blind 1-shot)* | `2` + `4` | Orch `0` tok (scripted `8` turns) · Worker `61,329` tok (`6` disp, `1` rb, `5.2–18.7 s`/step) · **`80.5 s`** | **Dispatches 1, 2, 5, 6:** Local 2B nailed `loadHighScore`/`saveHighScore`, `resetGame`, `togglePause`, `.overlay.hidden`, but made Hashline boundary off-by-one slips (`-.hud {`, `-}`, left-wall `if` instead of right-wall `else if`) and dropped `}` on 2-block Dispatch 6 (rolled back cleanly) |

### Failure Triage: Proven Fix Proposals vs. Open Hypotheses

- **Proven Fix Proposals (`PROVEN CAUSE` — directly observed in trace/diff/code):**
  1. **`hivo/hybrid/runner.py::_compact_history()` | Proof:** Runs 2 & 3 both threw Groq `HTTP 413` (`7,016/7,000` and `7,373/7,000` ITPM) because `_compact_history` sums only `len(str(m.get("content") or ""))` and ignores serialized `assistant.tool_calls` JSON arguments (`runner.py:128`). **Fix:** Compute full serialized message length (`json.dumps(m)`), compact older bulky `tool_calls` arguments/outputs cleanly, and preserve recent file reads without erasing active working context. **Expected funnel effect:** Eliminates `HTTP 413` mid-run crashes (`Bucket 1 -> 0`) and breaks compaction-induced `read_file` loops. **Stage 0 test:** Add offline test in `tests/test_hybrid_runner.py` with large `assistant.tool_calls` payloads asserting serialized payload stays strictly below `max_history_chars`.
  2. **`hivo/tools/base.py::check_inline_syntax()` | Proof:** Run 1 (`.overlay-card`), Run 4 Dispatch 1 (deleted opening `.hud {`, leaving orphan `}`), and Run 4 Dispatch 2 (deleted closing `}` of `.overlay.hidden`) all returned `ok: true` with no syntax feedback because `.css` files have no inline syntax check (only `.py`, `.json`, `.js`). **Fix:** Add deterministic stdlib CSS brace/comment balance checker (`{` / `}` depth never negative and ends at `0` outside strings/comments) returning `syntax_ok: false` + line hint on mismatch. **Expected funnel effect:** Forces 2B worker self-correction inside the same dispatch (`Bucket 4` CSS corruptions caught in `~2 s`). **Stage 0 test:** Add positive + negative CSS brace-mismatch tests in `tests/test_tools_fs_write.py`.
  3. **Split multi-block JS dispatches strictly to 1 block per dispatch + enforce diff-checked retry loop | Proof:** In Run 4 PoC, single-block JS dispatches succeeded (`Dispatches 3, 4, 5` syntactically valid), while `Dispatch 6` (bundling brick collision + bottom miss) dropped a closing `}` and rolled back; meanwhile `unified_diff` immediately printed every off-by-one slip (`-.hud {`, `-}`, wrong `if` branch). **Fix:** Keep each worker dispatch to **1 contiguous block/function**, and pair a non-`7K`-ITPM orchestrator endpoint (e.g., `NVIDIA_API_KEY`, Gemini, or OpenRouter) with `unified_diff` inspection so any 2B boundary slip triggers a targeted 1-line corrective retry. **Stage 0 test:** Offline controlled E2E test where scripted Orchestrator inspects a wrong-branch `unified_diff` and issues a corrective follow-up dispatch.

- **Open Hypotheses (`HYPOTHESIS — UNPROVEN` — do not blindly patch):**
  1. **Passing Orchestrator-verified `start_anchor`/`end_anchor` Hashlines directly in `dispatch_worker.context` may eliminate 2B boundary off-by-one slips:** Unproven yet; cheapest 1-variable probe is re-running `Run 4 PoC` with exact Hashline anchors supplied in `context` vs. line-number hints only and comparing off-by-one rate across the 6 dispatches.
  2. **Upgrading local worker from `qwen3.5:2b-q4_K_M` to `imatrix` `qwen3.5:4b` (if 100% GPU-resident on 4 GB VRAM) may reduce Hashline anchor slips:** Unproven on GTX 1650; requires `nvidia-smi` + `ollama ps` residency verification before testing.

### Intermediate Harness / Environment Defects Caught During Runs

1. **Pre-Run 2 harness upgrade (`unified_diff` + one-by-one prompt):** Verified red-first offline (`1` FAIL, `3` ERROR → `72` tests green) and immediately confirmed live in Run 2 (`plan_steps: 0 -> 7`, Dispatch 1 latency `32.2 s -> 6.5 s`, `.overlay-card` regression eliminated).
2. **Groq free-tier `7,000` single-request ITPM & `8,000` TPM pacing wall:** Exposed cleanly in Runs 1, 2, and 3; confirms [`docs/HYBRID_MODEL_STRATEGY.md`](../../../HYBRID_MODEL_STRATEGY.md) guidance that multi-turn benchmarks need a higher-quota endpoint (e.g., NVIDIA NIM or OpenRouter) once `_compact_history()` counts `tool_calls` JSON.
3. **Run 3 hidden false-positive caveat spotted during human diff audit:** Even though `css_hud_no_overlap` reported `PASS` in Run 3 (`1/10`), inspecting [`patches/run3_unified_diff_8k.diff`](patches/run3_unified_diff_8k.diff) revealed the worker overwrote `*` and `body` rules (lines 8–20) with `.hud` — proving why human diff spot-audits and stronger CSS syntax/selector checks matter.

---

## Limitations & Known Gaps

- **Small sample size ($N = 1$ task across `4` runs):** Proves specific architectural mechanisms and exposes concrete harness/2B failure modes, not general benchmark pass rate.
- **Dev-Slice local execution (not Docker-sealed):** Raw artifacts stay in gitignored `output/live_tests/`; not promoted to [`docs/BENCHMARK_SCORECARD.md`](../../../BENCHMARK_SCORECARD.md).
- **Run 4 PoC used a blind scripted Orchestrator:** It intentionally did **not** read `unified_diff` or retry failed/mangled dispatches, so `3/10` measures the 2B worker's **unassisted 1-shot floor**, not the closed-loop ceiling.
- **Uncommitted code & docs:** The `unified_diff` + one-by-one prompt changes in `hivo/hybrid/` and `hivo/tools/orchestration.py` plus this dossier remain uncommitted on `feat/benchmark-harness-stage0`.

## Artifacts, Reproduction & Rule Proposals

- **Sibling Artifacts:** [`PROTOCOL.md`](PROTOCOL.md), [`results.json`](results.json), [`provenance.json`](provenance.json), [`patches/run1_baseline.diff`](patches/run1_baseline.diff), [`patches/run2_unified_diff_14k.diff`](patches/run2_unified_diff_14k.diff), [`patches/run3_unified_diff_8k.diff`](patches/run3_unified_diff_8k.diff), [`patches/run4_poc_2b.diff`](patches/run4_poc_2b.diff)
- **Living Docs Updated (`docs/`):** [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../ORCHESTRATION_ARCHITECTURE.md)
- **Proposed Rule Updates (NOT APPLIED — Pending Maintainer Review):**

```markdown
### Proposed Rule Update 1 (NOT APPLIED)
- Target: dev_rules/orchestration_rules.md §6.2 (Mandatory Computed unified_diff in Worker Results)
- Action: PROMOTE [TARGET -> ENFORCED]
- Evidence: docs/worklogs/kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md (implemented _compute_snapshot_diff in hivo/hybrid/runner.py and forwarded unified_diff in hivo/tools/orchestration.py; verified by red-first offline tests in tests/test_hybrid_runner.py & tests/test_tools_exec_and_orch.py passing python scripts/check.py -v [72 tests] and live Runs 2–4)
- Proposed Wording (Swap-Test compliant): Promote §6.2 tag from `[TARGET]` to `[ENFORCED]`: immediately after a worker modifies files, compute a bounded `unified_diff` directly from pre-dispatch `target_snapshot` bytes vs. post-dispatch disk state and return it inside `dispatch_worker`'s payload (empty string on failure or rollback).
- Status: PROPOSED — NOT APPLIED (awaiting explicit maintainer review)

### Proposed Rule Update 2 (NOT APPLIED)
- Target: dev_rules/orchestration_rules.md §5.2 (Bounded Inline Outputs & Two-Pass Anchor-Pinned Compaction)
- Action: ADD [TARGET]
- Evidence: docs/worklogs/kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md (systemic failure proven across 2 independent runs: Run 2 HTTP 413 at 7,016/7,000 ITPM and Run 3 HTTP 413 at 7,373/7,000 ITPM because _compact_history counted only message content and ignored assistant tool_calls JSON)
- Proposed Wording (Swap-Test compliant): Enforce history character/token ceilings over **full serialized messages** (including `assistant.tool_calls` JSON arguments, not only `content` strings) `[TARGET]`, compacting stale tool-call payloads alongside older tool outputs so single-request payload limits are never silently exceeded.
- Status: PROPOSED — NOT APPLIED (awaiting explicit maintainer review)

### Proposed Rule Update 3 (NOT APPLIED)
- Target: dev_rules/tool_rules.md §4 Contract 4 (Deterministic, Atomic Writes & Immediate Feedback)
- Action: AMEND [TARGET]
- Evidence: docs/worklogs/kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md (systemic failure proven across 3 independent CSS dispatches: Run 1 .overlay-card corruption, Run 4 Dispatch 1 deleted `.hud {`, Run 4 Dispatch 2 deleted closing `}` — all returned ok=true with zero syntax warning)
- Proposed Wording (Swap-Test compliant): Extend inline post-edit syntax validation beyond Python/JSON/JS to include lightweight structural checks for stylesheet/web surfaces (e.g., deterministic CSS brace-balance validation) `[TARGET]` so unbalanced edits fail fast and trigger immediate worker self-correction.
- Status: PROPOSED — NOT APPLIED (awaiting explicit maintainer review)
```

- **Containing PR / Commit:** Pending (uncommitted on branch `feat/benchmark-harness-stage0`, base `dac866b`)

```powershell
python scripts/check.py -v
python scripts/update_worklog_index.py --check
node output/live_tests/2026-11-27_breakout-visual-repair/oracle/verify_breakout.js output/live_tests/2026-11-27_breakout-visual-repair/before
python -u output/live_tests/2026-11-27_breakout-visual-repair-poc-2b/run_poc.py
git diff --check
```
