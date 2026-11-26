# SOTA Benchmarking Rules, 2026 Progressive Plan & Initial Scoreboard

## Metadata

- **Date:** `2026-11-26`
- **Author:** `kareem`
- **Type:** `change`
- **Subsystem:** `dev_rules / docs / benchmarking`
- **Branch & Base Commit:** `docs/benchmarking-rules` (base `27bb0a1`)
- **Status:** `verified`
- **Builds On:** [Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker](../2026-11-26_dev-rules-and-worklog-policy/REPORT.md)
- **Next / Open Issue:** Implement Stage 0 benchmark runner hardening (`.git` strip, `--network none`, pre-solve baseline quarantine, trace cheat-scanner, 3-key KPI emitter, host/sandbox preflight CLI) + offline self-test suite `tests/test_benchmark_*.py` wired into `python scripts/check.py --benchmarks`
- **Rule Proposal:** None

## TL;DR

Added Mini Hivo's dedicated SOTA benchmarking guardrails ([`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md), `141` lines), concrete 2026 progressive evaluation plan, local setup/preflight runbook, and KPI/self-test specification ([`docs/BENCHMARKING_ARCHITECTURE.md`](../../../../docs/BENCHMARKING_ARCHITECTURE.md)), and version-locked `2026-11-26` SOTA reference scorecard ([`docs/BENCHMARK_SCORECARD.md`](../../../../docs/BENCHMARK_SCORECARD.md)) on dedicated rule branch `docs/benchmarking-rules`. Wired auto-invocation in [`AGENTS.md`](../../../../AGENTS.md), deduplicated sibling rule links, standardized positive historical-archive phrasing for `mini.py`/`reports/`/`updates/`, and added anti-false-result Truth Check & Proven-Fix-vs-Hypothesis hooks to the worklog templates with zero runtime Python changes. Verified offline via `python scripts/check.py -v` (`64` tests ran: `62` passed, `0` failed, `2` Windows-symlink skips + live `INDEX.md --check` `[OK]`), cross-file link/LF/privacy scans (`0` errors), and `git diff --check`.

---

## Problem & Root Cause

1. **Missing dedicated SOTA evaluation guardrails:** Benchmarking rules were previously limited to two bullets inside `dev_rules/orchestration_rules.md §6.4` without explicit output-verification mechanics, workspace decontamination (`.git` stripping / `--network none`), pre-solve baseline quarantine, deterministic non-prompt KPIs (`pass^k`, Cheating-Adjusted Accuracy, cost per resolved task, cache hit %, harness funnel), or a Stage 0 benchmark self-test suite.
2. **Coding agents lacked an autopilot benchmarking runbook:** Contributors delegating benchmark runs via a single prompt needed deterministic rules enforcing an 8-point anti-false-result Truth Check, earliest-turn failure tracing, and a strict split between evidence-backed Proven Fix Proposals and unproven Open Hypotheses.
3. **Rule phrasing and v1 archive alignment needed cleanup:** `AGENTS.md` and `documentation_rules.md` used negative *"do not allocate old IDs"* wording and routed v1 `mini.py` as an active track, while `orchestration_rules.md` line 6 still pointed dated empirical runs to `reports/` and `updates/`.

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md) | Absent | Added `141`-line Swap-Test-compliant benchmarking guardrails (UUT attribution, privilege-separated output verification, deterministic KPIs, Stage 0 self-test contract, host/sandbox preflight & new-runner onboarding gate, 7-step coding-agent autopilot runbook + 8-point Truth Check, 6-bucket Evidence-vs-Hypothesis triage, 5-stage progressive gate with dated `2026-11-26` reference suite roster, and optional human-in-the-loop audits) | Single canonical prescriptive source for Mini Hivo v2 evaluation (`[ENFORCED]` / `[TARGET]` / `[PROCESS]` audited against `scripts/run_swebench_hybrid.py`) | Link, LF, Swap-Test & privacy audit |
| [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../../docs/BENCHMARKING_ARCHITECTURE.md) | Absent | Added living 2026 SOTA plan: 14-entry dated (`2026-11-26`) benchmark roster, 6-step verification pipeline, operational defaults (`pass^3` over `n=5`, `> $5` / `> 20` task cost sign-off), canonical 3-key `results.json` schema, Stage 0 harness & preflight backlog, 7-case `tests/test_benchmark_*.py` self-test spec, contributor local-setup/new-runner checklist, and optional human-audit guide | Living descriptive companion editable during normal engineering work | Link, LF & privacy audit |
| [`docs/BENCHMARK_SCORECARD.md`](../../../../docs/BENCHMARK_SCORECARD.md) | Absent | Added version-locked scoreboard with `2026-11-26` SOTA reference snapshot (`Terminal-Bench 4.1/4.0`, `SWE-sweep`, `SWE-bench Verified`, `DeepSWE v1.1`, `FrontierSWE v2`, `FrontierCode 2.0`, `SWE-bench Pro`, `Multi-SWE-bench`, `SWE Atlas`, `SWE-Chain`, `CursorBench 4.0`) + Experiment 23 Day-0 v2 anchor and Stage 0–4 tracking tables | Longitudinal version-locked comparison surface | Link, LF & privacy audit |
| [`AGENTS.md`](../../../../AGENTS.md) | Routed `scripts/*swebench*` to `orchestration_rules.md`; listed `mini.py` as active row; used negative legacy-ID prohibition wording | Added dedicated `benchmarking_rules.md` routing row; replaced negative legacy phrasing with direct positive worklog instructions and quiet read-only archive note for `mini.py`, `reports/`, and `updates/` | Auto-invokes `benchmarking_rules.md` across Antigravity, Codex & Claude Code with clean positive framing | Link, LF & `git diff --check` |
| [`dev_rules/how_to_make_rules.md`](../../../../dev_rules/how_to_make_rules.md), [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md), [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md) | No `benchmarking_rules.md` cross-links; duplicate §6.4 benchmark bullets & stale `reports/` reference in `orchestration_rules.md`; negative archive phrasing in `documentation_rules.md` | Added `benchmarking_rules.md` cross-links; deduplicated `orchestration_rules.md §6.4` to a single pointer + fixed line 6 to `docs/worklogs/`; simplified archive wording to positive framing; updated Revision Logs | Zero cross-rule duplication or contradiction | Link, LF & `git diff --check` |
| [`docs/worklogs/PROTOCOL_TEMPLATE.md`](../../../../docs/worklogs/PROTOCOL_TEMPLATE.md), [`docs/worklogs/REPORT_TEMPLATE.md`](../../../../docs/worklogs/REPORT_TEMPLATE.md) | Generic experiment protocol & Block E table without Truth Check or Proven-Fix-vs-Hypothesis subsections | Added Stage/Version, Decontamination Controls & Pre-Run Cost Estimate bullets to `PROTOCOL_TEMPLATE.md`, plus 8-Point Truth Check, Human Audit Tier, Bucket (`1–6`), and Proven-Fix-vs-Hypothesis hooks in `REPORT_TEMPLATE.md` Block E | Coding agents automatically capture Truth Checks and trace-backed triage on every `Type: experiment` run | `update_worklog_index.py --check` + link/LF audit |

---

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Unified offline v2 test suite + live worklog index check | `unit` + `integration` + `regression` | Real offline suites & live `docs/worklogs/` scan (zero LLM calls) | `python scripts/check.py -v` | `64` ran (`62` passed, `0` failed, `2` Windows-symlink skips) + `INDEX.md` `[OK]` | `0` |
| Cross-file Markdown links, canonical LF endings & privacy/secret scan | `structural` | Real workspace files across all 9 created/updated rule, doc, and template files | Python link/LF/privacy audit + `git diff --check` | `0` broken links, `0` CRLF violations, `0` secret/path leaks, `0` whitespace errors | `0` |
| PR diff Hard Rule Lock audit (maintainer rule-approved mode) | `structural` | Real changed files vs. base `27bb0a1` | `python scripts/check.py --ci-diff 27bb0a1 --allow-rule-edits` | `[OK]` (and fails closed without `--allow-rule-edits`, confirming Hard Rule Lock) | `0` |

---

## Limitations & Known Gaps

- This pass is **rules, living documentation, and templates only** (`0` Python code edits under `hivo/` or `scripts/`); runtime functional and live-model tests are **not applicable**.
- Every unbuilt Stage 0 benchmark safeguard (`.git` stripping, `--network none`, pre-solve baseline quarantine, final-diff protected-path assertion, trace cheat-scanner, 3-key KPI emitter, and `tests/test_benchmark_*.py` / `--benchmarks` runner scope) is explicitly tagged **`[TARGET]`** in `dev_rules/benchmarking_rules.md` and queued for the next dedicated implementation PR (`feat/benchmark-harness-stage0`).
- `scripts/update_worklog_index.py` was intentionally left untouched on this rule-only branch so zero governed `.py` code paths are mixed into a `rule-approved` governance PR.

## Artifacts, Reproduction & Promoted Updates

- **Sibling Artifacts:** [`provenance.json`](provenance.json)
- **Living Docs Created (`docs/`):** [`docs/BENCHMARKING_ARCHITECTURE.md`](../../../../docs/BENCHMARKING_ARCHITECTURE.md), [`docs/BENCHMARK_SCORECARD.md`](../../../../docs/BENCHMARK_SCORECARD.md)
- **Rules Added / Aligned (`dev_rules/` & root):** [`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md), [`AGENTS.md`](../../../../AGENTS.md), [`dev_rules/how_to_make_rules.md`](../../../../dev_rules/how_to_make_rules.md), [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md), [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md)
- **Containing PR / Commit:** Pending (uncommitted on branch `docs/benchmarking-rules`, base `27bb0a1`)

```powershell
python scripts/update_worklog_index.py --check
python scripts/check.py -v
git diff --check
# After committing on this dedicated rule-review branch:
python scripts/check.py --ci-diff 27bb0a1 --allow-rule-edits
```
