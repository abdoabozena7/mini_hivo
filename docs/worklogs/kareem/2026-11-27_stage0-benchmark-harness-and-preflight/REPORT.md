# Stage 0 Benchmark Harness Hardening, Self-Test Suite & Host Preflight

## Metadata

- **Date:** `2026-11-27`
- **Author:** `kareem`
- **Type:** `change`
- **Subsystem:** `hivo/benchmarks / scripts / tests`
- **Branch & Base Commit:** `feat/benchmark-harness-stage0` (base `5005210`)
- **Status:** `verified`
- **Builds On:** [SOTA Benchmarking Rules, 2026 Progressive Plan & Initial Scoreboard](../2026-11-26_benchmarking-rules-and-sota-plan/REPORT.md)
- **Next / Open Issue:** Add higher-quota cloud provider key (e.g., `NVIDIA_API_KEY` or OpenRouter) in local `.env`, install `harbor` CLI, and build Stage 1 `Terminal-Bench 4.1` Harbor adapter + sealed `SWE-bench` calibration run
- **Rule Proposal:** `[APPLIED in v0.2] PROMOTE dev_rules/benchmarking_rules.md §2.3, §2.4, §2.5, §2.7, §3.1-§3.3 Stage 0 safeguards [TARGET -> ENFORCED]`

## TL;DR

Implemented Mini Hivo's stdlib-only Stage 0 benchmarking core ([`hivo/benchmarks/`](../../../../hivo/benchmarks/__init__.py)), hardened [`scripts/run_swebench_hybrid.py`](../../../../scripts/run_swebench_hybrid.py) with `.git` history stripping, `--network none` isolation, pre-solve Baseline Oracle quarantine, final-diff anti-tamper gating, deterministic trace cheat-scanning, and canonical 3-key `results.json` emission, and wired the 7-case offline self-test suite ([`tests/test_benchmark_stage0.py`](../../../../tests/test_benchmark_stage0.py)) into `python scripts/check.py --benchmarks`. Verified offline via `python scripts/check.py -v` (`71` tests ran: `69` passed, `0` failed, `2` Windows-symlink skips + live `INDEX.md --check` `[OK]`) and verified the host machine live with zero LLM calls via `python -m hivo.benchmarks.preflight --provider groq` (`ready=True`: Docker `29.6.2` + `--network none`, disk headroom OK, `GROQ_API_KEY` redacted, local `qwen3.5:2b-q4_K_M` pulled on GTX 1650). Following explicit maintainer authorization, promoted the implemented Stage 0 `[TARGET]` safeguards in [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) (`v0.2`) to `[ENFORCED]`.

---

## Problem & Root Cause

Auditing [`scripts/run_swebench_hybrid.py`](../../../../scripts/run_swebench_hybrid.py) against [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) exposed five Stage 0 gaps capable of creating false benchmark results or wasting cloud quota:

1. **Unsealed `.git` history and container networking:** `_extract_testbed_to_host()` preserved original `.git` history and containers ran with default Docker networking rather than `--network none`.
2. **Post-solve baseline oracle:** `[ORACLE 1/2]` ran *after* `HybridAgentRunner.run()` and did not gate `resolved` on `baseline_oracle_valid`, wasting LLM tokens on pre-passing tasks.
3. **Missing post-run diff anti-tamper & trace cheat-audit:** No deterministic check verified that `model_patch` modified zero protected/test files or scanned executed tool/shell calls for Tier 1–3 reward hacking (`git log`, `cat-file`, `/tmp`, `.env`).
4. **Non-canonical telemetry output:** `results.json` emitted flat legacy keys instead of the team-standard 3-key `{"meta", "summary", "cases"}` envelope with `pass^k`, `cheating_adjusted_rate`, `cache_hit_rate`, `usd_per_resolved`, 6-bucket triage, and the 8-Point Truth Check.
5. **No zero-LLM benchmark self-tests or host preflight CLI:** Contributors had no offline regression suite proving the benchmark harness rejects false positives, and no 1-command preflight verifying local Docker/disk/VRAM/credential readiness.

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| [`hivo/benchmarks/decontamination.py`](../../../../hivo/benchmarks/decontamination.py) | Absent | Added `strip_git_and_reinit()`, `verify_workspace_decontaminated()`, `docker_network_args()`, `extract_patch_paths()`, and `check_protected_paths_in_patch()` | Strips `.git` history/tags/remotes into 1 orphan commit, validates `--network none`, and detects protected/test path tampering in unified diffs | `test_decontamination_strips_git_history`, `test_protected_path_tamper_rejected` |
| [`hivo/benchmarks/audit.py`](../../../../hivo/benchmarks/audit.py) | Absent | Added `scan_trace_for_cheats()`, `evaluate_baseline_oracle()`, `evaluate_candidate_verdict()`, and `run_truth_check()` | Detects Tier 1–3 exploits & `ORACLE_LOCKED` across executed tool calls (ignoring prose), enforces pre-solve baseline validity + zero missing/skipped passes, and flags `INVALID_HARNESS` on Checks 1–5 failures | `test_invalid_baseline_quarantined`, `test_missing_or_skipped_test_never_passes`, `test_trace_cheat_scanner_catches_planted_exploits` |
| [`hivo/benchmarks/metrics.py`](../../../../hivo/benchmarks/metrics.py) | Absent | Added `compute_pass_hat_k()`, `compute_percentile()`, `classify_failure_bucket()`, and `build_benchmark_results()` | Exact binomial `pass^k`, `p50`/`p95`, `cache_hit_rate`, `usd_per_resolved`, 6-bucket conservation, monotonicity/NaN assertions, and 3-key `{"meta", "summary", "cases"}` output | `test_kpi_aggregator_sanity_bounds` |
| [`hivo/benchmarks/preflight.py`](../../../../hivo/benchmarks/preflight.py) & [`hivo/benchmarks/__init__.py`](../../../../hivo/benchmarks/__init__.py) | Absent | Added zero-LLM `run_preflight()` CLI (`python -m hivo.benchmarks.preflight`) + lazy `__getattr__` export to avoid `runpy` warnings | Checks Docker + `--network none`, disk headroom, secret-safe `.env` credentials, Ollama + local GPU residency `%`, and optional Harbor CLI | `test_preflight_reports_missing_deps_cleanly` + live host execution |
| [`scripts/run_swebench_hybrid.py`](../../../../scripts/run_swebench_hybrid.py) | Preserved `.git`, default networking, post-solve baseline, legacy flat JSON | Wired `hivo.benchmarks` for `.git` stripping, `--network none`, pre-solve `INVALID_BASELINE` quarantine (`0` tokens spent), trace cheat-scanning, anti-tamper verdict, `--preflight-only`, and canonical 3-key `results.json` | Stage 0 compliant sealed SWE-bench runner | Controlled functional quarantine check in `test_invalid_baseline_quarantined` |
| [`scripts/check.py`](../../../../scripts/check.py) & [`tests/test_check_runner.py`](../../../../tests/test_check_runner.py) | Discovered `--tools`, `--orchestration`, `--worklogs` only | Added `--benchmarks` flag discovering `tests/test_benchmark_*.py` in both scoped and full offline runs | CI and local `scripts/check.py` run all Stage 0 benchmark self-tests automatically | `tests/test_check_runner.py` (`4/4` pass) |
| [`tests/test_benchmark_stage0.py`](../../../../tests/test_benchmark_stage0.py) | Absent | Added all 7 adversarial offline Stage 0 self-tests (positive + negative/boundary coverage) | Proves harness rejects unstripped git, invalid baselines, test tampering, missing/skipped tests, planted cheats, bad KPI bounds, and missing host deps/secret leaks | `python scripts/check.py --benchmarks -v` (`7/7` pass) |
| [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../../docs/BENCHMARKING_ARCHITECTURE.md), [`docs/BENCHMARK_SCORECARD.md`](../../../../docs/BENCHMARK_SCORECARD.md) | Listed Stage 0 items as pending | Recorded implemented Stage 0 modules and live `7/7` Stage 0 scoreboard entry | Living docs synchronized with code | Link, LF & privacy audit |

---

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Stage 0 Benchmark Self-Test Suite | `unit` + `controlled functional` | Real local Git repo for decontamination + adversarial mock fixtures & mocked Docker/runner quarantine check | `python scripts/check.py --benchmarks -v` | `7/7` passed, `0` failed, `0` skipped | `0` |
| Full active v2 offline suite + live `INDEX.md --check` | `unit` + `integration` + `regression` | All 13 active v2 offline suites + real worklog index validator (zero LLM calls) | `python scripts/check.py -v` | `71` ran (`69` passed, `0` failed, `2` Windows-symlink skips) + `INDEX.md` `[OK]` | `0` |
| Live host preflight (`groq` arm) | `integration` *(zero LLM calls)* | Real host Docker `29.6.2`, real disk stats, real `.env` check (redacted), real Ollama `/api/tags` + `nvidia-smi` | `python -m hivo.benchmarks.preflight --provider groq` | `ready=True` (Docker + `--network none` PASS; workspace drive `497.3 GB` / system drive `7.4 GB` PASS; `GROQ_API_KEY` PASS; `qwen3.5:2b-q4_K_M` pulled on GTX 1650 `3685/4096 MiB` free PASS; Harbor INFO optional) | `0` |
| Live host preflight (`nvidia` arm negative check) | `integration` *(zero LLM calls)* | Real host `.env` without `NVIDIA_API_KEY` | `python -m hivo.benchmarks.preflight --provider nvidia` | `ready=False` (`provider_credentials` FAIL with actionable hint; `0` secrets leaked) | `1` |
| PR diff gates (Hard Rule Lock + code-requires-tests) | `structural` | Real changed files vs. base `5005210` | `python scripts/check.py --ci-diff 5005210 --allow-rule-edits` + `git diff --check` | `0` missing-tests errors, `0` whitespace errors; `dev_rules/benchmarking_rules.md` promotion explicitly maintainer-authorized (`rule-approved` label required on PR) | `0` |

---

## Limitations & Known Gaps

- **No live LLM benchmark sweep executed in this PR:** Stage 0 builds and verifies the harness/preflight mechanics offline (`0` LLM tokens spent). Live Stage 1 execution (`Terminal-Bench 4.1` via Harbor + sealed `SWE-bench` calibration + 3-arm Scaffold-Lift control) is the next milestone.
- **Host live-run readiness observations from real preflight:**
  - `groq` is ready immediately for small spot checks (`GROQ_API_KEY` set), while higher-quota multi-task providers (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `GEMINI_API_KEY`, `CEREBRAS_API_KEY`) are not yet configured in local `.env`.
  - System drive has `7.4 GB` free (above the `5.0 GB` threshold, reinforcing why 1-image-at-a-time Docker cleanup remains mandatory).
  - `harbor` CLI is not yet installed on PATH (install once when ready for Stage 1 `Terminal-Bench 4.1`).
- **Remaining `[TARGET]` items in `dev_rules/benchmarking_rules.md` not yet built:** No-op stub mutation checking (Stage 4B `SWE Atlas`), multi-trial runner orchestration for `pass^k` / 4-axis Reliability Envelope (Stage 3), and Harbor CLI adapter for `Terminal-Bench 4.1` (Stage 1).

## Artifacts, Reproduction & Rule Proposals

- **Sibling Artifacts:** [`provenance.json`](provenance.json)
- **Living Docs Updated (`docs/`):** [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../../docs/BENCHMARKING_ARCHITECTURE.md), [`docs/BENCHMARK_SCORECARD.md`](../../../../docs/BENCHMARK_SCORECARD.md)
- **Rule Updates Applied (`dev_rules/` — Explicit Maintainer Authorization):** [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) (`v0.1` → `v0.2`)

```markdown
- Target: dev_rules/benchmarking_rules.md §2.3, §2.4, §2.5, §2.7, §3.1, §3.2, §3.3
- Action: PROMOTE [TARGET -> ENFORCED]
- Evidence: docs/worklogs/kareem/2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md (`python scripts/check.py --benchmarks -v` 7/7 pass; `python scripts/check.py -v` 71 ran, 69 pass, 2 Windows-symlink skips; live zero-LLM `python -m hivo.benchmarks.preflight` verified)
- Proposed Wording (Swap-Test compliant): Promote implemented Stage 0 clauses from `[TARGET]` to `[ENFORCED]` in `dev_rules/benchmarking_rules.md`: workspace `.git` stripping & `--network none` isolation (§2.3), final-diff protected-path anti-tamper check (§2.4), pre-solve Baseline Oracle validity gate & `INVALID_BASELINE` quarantine (§2.5), deterministic trace cheat-scanner (§2.7), `cheating_adjusted_rate` / cost / cache / funnel / 3-key `results.json` aggregator (§3.1), Stage 0 offline benchmark self-test suite `tests/test_benchmark_*.py` wired into `scripts/check.py --benchmarks` (§3.2), and zero-LLM Host & Sandbox Preflight CLI (§3.3). Keep Stage 3 Reliability Envelope orchestration and Stage 4B mutation-check runners tagged `[TARGET]`.
- Status: APPLIED (explicit maintainer approval on 2026-11-27; updated to v0.2)
```

- **Containing PR / Commit:** Pending (uncommitted on branch `feat/benchmark-harness-stage0`, base `5005210`)

```powershell
python scripts/check.py --benchmarks -v
python scripts/check.py -v
python -m hivo.benchmarks.preflight --provider groq
git diff --check
```
