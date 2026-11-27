# Mini Hivo — Version-Locked Benchmark Scorecard (`docs/BENCHMARK_SCORECARD.md`)

> - **Snapshot Date:** `2026-11-26` *(initial SOTA frontier comparison + Mini Hivo v2 Day-0 anchor)*
> - **Governing Rules:** [`../dev_rules/benchmarking_rules.md`](../dev_rules/benchmarking_rules.md) *(Truth Check, version lock, UUT attribution)*
> - **Benchmark Plan & Suite Roster:** [`BENCHMARKING_ARCHITECTURE.md`](BENCHMARKING_ARCHITECTURE.md)
> - **Strict Version-Lock Rule:** Never compare scores across different benchmark versions (e.g., Terminal-Bench `4.1` vs. `4.0` vs. `2.0`; CursorBench `4.0` vs. `3.2`). Only **Held-Out** or **Milestone** runs passing all 8 items of the Anti-False-Result Truth Check are promoted into §2; Dev-slice debugging stays in [`worklogs/INDEX.md`](worklogs/INDEX.md).

---

## 1. Initial SOTA Frontier Reference Snapshot (`2026-11-26`) vs. Mini Hivo v2 Baseline

All external frontier numbers below reflect the **`2026-11-26`** landscape with explicit attribution (official leaderboard / independent aggregator vs. vendor-reported model card). Re-verify and date-stamp updates whenever new model cards or benchmark versions ship.

| Benchmark *(Exact Version)* | Stage | SOTA Frontier Reference *(Snapshot `2026-11-26`)* | Source / Known Caveat | Mini Hivo v2 Starting Baseline *(as of `2026-11-26`)* |
| :--- | :---: | :--- | :--- | :--- |
| **`Terminal-Bench 4.1`** *(66 CLI tasks, Harbor)* | `Stage 1` | `Gemini 4 Neon`: **65.2%** *(cheating-adjusted)* | Google model card *(TB `4.1` ≠ `4.0` / `2.0`)* | *Not yet run — queued after Stage 0 self-test gate* |
| **`Terminal-Bench 4.0`** *(66 CLI tasks, Harbor)* | `Stage 1` | `GPT-6.2 Astra (max)`: **64.1%** (AA) · `Gemini 4 Neon (xhigh)`: **63.6%** (AA) · `GPT-6 Astra (Codex)`: **58.2%** (Official) · `Claude Fable 5.1 (Claude Code)`: **57.9%** (Official) | Official TB 4.0 & Artificial Analysis | *Superseded by `4.1` for new Mini Hivo runs* |
| **`SWE-sweep`** *(Scaffold-Lift isolation)* | `Stage 1` | `Gemini 4 Neon`: **39.0%** (`Antigravity` harness) vs. **12.8%** (`mini-SWE` harness) | Google model card *(~3× pure harness multiplier)* | *Not yet run — planned 3-arm control (Minimal vs. Orch-Only vs. Hybrid)* |
| **`SWE-bench Verified`** *(500 Python — Legacy Calibration Only)* | `Stage 1` *(Legacy)* | `Claude Fable 5`: **95.0%** (LLM Stats) · `Claude Opus 4.7`: **87.6%** · `Claude Opus 4.5`: **80.9%** | Deprecated by OpenAI for contamination & test flaws; calibration baseline only | **Historical Exp 23 (`2026-11-26`, `N=3`, `seed=42`):** `1/3` (`33%` raw) · `1/2` (`50%` valid non-blocked; `django__django-16527` PASS; Groq `qwen/qwen3.8-27b` + local `qwen3.5:2b-q4_K_M`, unsealed `.git` pre-Stage-0 harness) — [Exp 23 report](../reports/experiment23/experiment23-report.md) |
| **`DeepSWE v1.1`** *(Uncontaminated Repo)* | `Stage 2` | `GPT-5.6`: **72.7%** · `GPT-6.1 Sol` matches `GPT-6 Astra` at ~1/5 cost | OpenAI-reported | *Not yet run* |
| **`FrontierSWE v2`** *(Long-Horizon Repo)* | `Stage 2` | `Claude Fable 5.2`: **69.9%** · `GPT-6 Astra`: **65.5%** · `Claude Opus 5.5`: **62.3%** · `Gemini 4 Carbon`: **61.2%** | Anthropic vendor table | *Not yet run* |
| **`FrontierCode 2.0` (`AA 2.0`)** *(Zero-Edit Mergeability)* | `Stage 2` | `GPT-6.2 Astra (xhigh)`: **49.0%** · `Gemini 4 Neon`: **44.4%** | Artificial Analysis published | *Not yet run* |
| **`SWE-bench Pro`** *(Strict-Isolated Public Split)* | `Stage 2` | `Claude Opus 4.8 Max`: **73.0%** strict *(vs. 87.1% unsealed, `-14.1` pts)* · `Cursor Composer 2.5`: **54.0%** strict *(vs. 74.7% unsealed, `-20.7` pts)* | Cursor strict harness; ~30% raw public tasks estimated flawed | *Not yet run* |
| **`Multi-SWE-bench`** *(8 languages)* | `Stage 2` | Multilingual reference suite *(Python, Java, TS, JS, Go, Rust, etc.)* | Requires strict `.git` sealing | *Not yet run* |
| **`SWE Atlas`** *(284 Q&A / Test / Refactor tasks)* | `Stage 4B` | Mutation-verified test writing + cross-family rubric refactoring | Single-turn SDLC benchmark | *Not yet run* |
| **`SWE-Chain`** *(1,660 chained upgrade tasks)* | `Stage 4B` | Nine frontier agent-model setups averaged **44.8%** resolve rate under Build+Fix | Exposes compounding cross-release breakage | *Not yet run* |
| **`CursorBench 4.0`** *(Live IDE Sessions)* | `Stage 4` *(Ref)* | `Claude Fable 5.2`: **60.0%** · `Claude Opus 5.5`: **57.8%** · `Claude Sonnet 5.5`: **55.5%** | LLM Stats *(v4.0 ≠ v3.2)* | *Reference only (IDE-session format)* |

---

## 2. Mini Hivo v2 Active Runs (Held-Out & Milestone Checkpoints Only)

### 2.1 Stage 0 — Offline Harness & Self-Test Gate

| Date | Harness SHA | Command | Offline Suites | Self-Test Checks (7/7) | Status | Dossier |
| :--- | :--- | :--- | :--- | :---: | :---: | :--- |
| `2026-11-27` | `5005210`+Stage 0 | `python scripts/check.py --benchmarks` | `tests/test_benchmark_stage0.py` | **`7/7` PASS** | **`PASS`** | [Stage 0 Harness & Preflight](worklogs/kareem/2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md) |

### 2.2 Stage 1 & Stage 2 — Execution & Frontier Repo Runs

| Date | Benchmark *(Exact Version)* | Harness SHA | UUT *(Orch + Effort / Worker + Ctx)* | Slice / `N` / `seed` | Raw `%` | Valid Non-Blocked `%` | Cheating-Adj `%` | `$/Resolved` | Cache Hit `%` | Truth Check | Human Audit | Dossier |
| :--- | :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| `2026-11-26` *(Historical Anchor)* | `SWE-bench Verified` *(Legacy)* | `886ea71` | Groq `qwen/qwen3.8-27b` (`med`) + local `qwen3.5:2b-q4_K_M` (`4096`) | Calib / `N=3` / `42` | `1/3` (`33%`) | `1/2` (`50%`) | *N/A (pre-Stage-0)* | `$0` *(free tier)* | *Not logged* | Pre-Stage-0 *(unsealed `.git`)* | `Spot-Checked (3/3)` | [Exp 23](../reports/experiment23/experiment23-report.md) |
| *(next: Stage 1 sealed runs)* | — | — | — | — | — | — | — | — | — | — | — | — |

### 2.3 Stage 1 — 3-Arm Scaffold-Lift & Asymmetric Efficiency Table

| Date | Benchmark & Slice (`N`, `seed`) | Harness SHA | Orchestrator Model + Effort | Arm A *(Minimal Loop)* | Arm B *(Mini Hivo Orch-Only)* | Arm C *(Mini Hivo Hybrid + Local Worker)* | Harness Lift (`B - A`) | Cost Ratio (`C vs. B`) | Dossier |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :--- |
| *(pending Stage 1 control)* | — | — | — | — | — | — | — | — | — |

### 2.4 Stage 3 & Stage 4 — Repeatability (`pass^k`), Safety/Integrity & Private Gold Gate

| Date | Suite / Gate *(Exact Version)* | Harness SHA | UUT *(Orch / Worker)* | `N` × `n` Trials | `pass^1` | `pass^3` | Worst-Case Envelope | Tamper / Cheat Hits | `$/Resolved` | Human Audit | Dossier |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| *(pending Stage 3–4 runs)* | — | — | — | — | — | — | — | — | — | — | — |

---

## 3. Update Protocol

1. **Held-Out / Milestone Only:** Add a row to §2 only after a full `Type: experiment` worklog dossier exists in `docs/worklogs/<person>/YYYY-MM-DD_<slug>/` and passes all 8 checks of the Truth Check in [`../dev_rules/benchmarking_rules.md`](../dev_rules/benchmarking_rules.md).
2. **Compute From JSON:** Copy numbers strictly from the dossier's verified `results.json` (preserving raw and valid denominators, `N`, and `seed`).
3. **Never Overwrite Historical Rows:** Append new rows chronologically so progress (and regressions) remain auditable across harness commits.
