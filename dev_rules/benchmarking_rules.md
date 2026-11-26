# Benchmarking & Evaluation Rules (`dev_rules/benchmarking_rules.md`)

> - **Status:** Living evaluation guardrails (`v0.1`)
> - **Scope:** Benchmark harnesses and runners (`scripts/*swebench*`, `scripts/*bench*`, `scripts/*eval*`, `hivo/benchmarks/`), Stage 0 benchmark self-tests (`tests/test_benchmark_*.py`), `Type: experiment` worklogs, and promotion decisions for Mini Hivo's active v2 asymmetric architecture.
> - **Related Specs:** [Rule-Authoring Methodology (`how_to_make_rules.md`)](how_to_make_rules.md), [Orchestration Guardrails (`orchestration_rules.md`)](orchestration_rules.md), [Tool Rules (`tool_rules.md`)](tool_rules.md), [Documentation & Worklog Rules (`documentation_rules.md`)](documentation_rules.md), [Repository Workflow (`../AGENTS.md`)](../AGENTS.md), [Benchmarking Architecture & 2026 Plan (`../docs/BENCHMARKING_ARCHITECTURE.md`)](../docs/BENCHMARKING_ARCHITECTURE.md), [Benchmark Scorecard (`../docs/BENCHMARK_SCORECARD.md`)](../docs/BENCHMARK_SCORECARD.md)
> - **Rule Standard:** All invariants below are model-, vendor-, and hardware-agnostic. Concrete suite names in §6 are explicitly dated **reference targets** subject to periodic re-audit; live dataset splits, sample budgets, and SOTA comparison tables live in `docs/BENCHMARKING_ARCHITECTURE.md` and `docs/BENCHMARK_SCORECARD.md`.
> - **Tag Legend:** `[ENFORCED]` = verified in current harness/code; `[TARGET]` = validated SOTA requirement to implement in upcoming harness code; `[PROCESS]` = mandatory operational or review gate (`[PROCESS — OPTIONAL]` = recommended human audit).
> - **Historical Reference:** `mini.py`, `reports/`, and `updates/` are preserved historical archives kept for chronological record and earlier baseline findings.

---

## 1. Evaluation Model & Full-System Attribution

Modern SOTA coding evaluation measures the complete `(model + harness)` system — never isolated prompt text or self-reported prose:

1. **Full Unit-Under-Test (UUT) Tuple `[PROCESS]`:** Every benchmark result must record `(Orchestrator Model + Reasoning Effort, Worker Model + Quant/Ctx, Harness Git SHA, ToolProfile Hash, Benchmark Name + Exact Version, Seed, N)`. Never publish a bare percentage.
2. **One-Variable A/B & Version Lock `[PROCESS]`:** Change only one variable per comparison (model, effort, prompt, tool profile, or harness). Never compare scores across different benchmark versions (e.g., Terminal-Bench `4.1` vs. `4.0` vs. `2.0`).
3. **Scaffold-Lift & Asymmetric Attribution `[PROCESS]`:** Quantify both **Harness Lift** (`Mini Hivo` vs. a minimal single-agent loop on identical model weights) and **Asymmetric Efficiency** (`Orchestrator + Light Worker` vs. `Orchestrator-Only` on resolve rate and cost per resolved task).
4. **Dev vs. Held-Out Slice Separation `[PROCESS]`:** Iterate prompts, compaction limits, and tool ergonomics strictly on a designated **Dev Slice**. Reserve the **Held-Out Eval Slice** for locked checkpoint evaluations to prevent harness overfitting.
5. **Target-Parity Calibration `[PROCESS]`:** When developing on oversized free/preview models, spot-check prompt and decomposition assumptions on the target orchestrator capability tier before promoting changes.

---

## 2. Runtime Isolation, Output Verification & Anti-Cheating

Never verify a coding agent by reading its chat response. Grade strictly via independent, privilege-separated execution:

1. **Artifact-Only Extraction `[ENFORCED]`:** Discard the agent's final prose. Extract only concrete workspace mutations (`git diff` patch) or post-run container state.
2. **Zero Solve-Time Leakage `[ENFORCED]`:** Strictly withhold hidden `test_patch`, ground-truth patches, `FAIL_TO_PASS`/`PASS_TO_PASS` lists, and hints during solve time; lock test paths via `protected_paths` (`ORACLE_LOCKED`).
3. **Strict Workspace Decontamination `[TARGET]`:** Before agent launch, delete `.git` history and re-initialize the workspace as a single fresh orphan commit (eliminating commit logs, reflogs, remotes, and dangling blobs), wipe `/tmp`, mount zero host secrets, and run execution containers with outbound internet disabled (`--network none` or an allowlisted package-registry proxy).
4. **Privilege-Separated Grading Container `[ENFORCED]`:** Apply extracted artifacts and hidden tests inside a **brand-new container** the agent never accessed. Require clean `git apply`, **zero** edits to protected/test files `[TARGET]`, and exact parsed test IDs (`100%` `F2P` + `100%` `P2P` passed; `0` `MISSING`/`SKIPPED` targets counted as pass `[ENFORCED]`).
5. **Pre-Solve Baseline Oracle Gate `[TARGET]`:** Run the unpatched baseline oracle *before* spending agent tokens. Confirm `F2P < total` and `P2P == total`; quarantine broken tasks as `INVALID_BASELINE` (retained in denominators, never scored as passes).
6. **Task-Matched Oracles & Cross-Family Judges `[TARGET / PROCESS]`:**
   - *Repo Fixes:* Containerized `F2P` + `P2P` unit/integration suites.
   - *Headless CLI / Ops:* Hidden post-run container `pytest` assertions on files, exit codes, and runtime state.
   - *Test Authoring:* **No-op stub mutation check** — agent-written tests must **pass** on intact code and **fail** when target functions are replaced with no-op stubs.
   - *Performance & Mergeability:* Deterministic workload recovery under functional pass gates + automated lint/style/minimal-diff zero-edit mergeability gates.
   - *Qualitative Rubrics `[PROCESS]`:* Any LLM judge grading maintainability or refactoring must come from a **different model family** than both Orchestrator and Worker (preventing self-grading bias).
7. **Deterministic Trace Cheat-Audit `[TARGET]`:** Inspect every executed tool/shell call in the saved trace (never trusting reasoning summaries) for `.git` mining (`git log`, `cat-file`, `fsck`), `/tmp` or secret scans, external mirrors, or test tampering. Report **Cheating-Adjusted Accuracy**.

---

## 3. Deterministic KPI Contract & Benchmark Self-Test Suite

### 3.1 Required Non-Prompt KPIs (`results.json`)
Store every benchmark run inside the standard 3-key worklog envelope (`{"meta", "summary", "cases"}`, per [`documentation_rules.md`](documentation_rules.md)) capturing four deterministic layers (exact field schema in [`../docs/BENCHMARKING_ARCHITECTURE.md`](../docs/BENCHMARKING_ARCHITECTURE.md)):

1. **Outcome & Integrity:** Raw `resolved / total_n`, `resolved / valid_non_blocked_n`, **Cheating-Adjusted Accuracy** `[TARGET]`, mutation kill rate (test-writing) `[TARGET]`, and patch hygiene / zero-edit mergeability `%` `[TARGET]`.
2. **Repeatability & Reliability Envelope `[TARGET]`:** **`pass^k`** ($\mathbb{E}_{\text{task}}[\binom{c}{k}/\binom{n}{k}]$, requiring $k \ge 3$ at Stage 3 and Milestone Release gates) across $n$ independent trials, plus worst-case pass rate across **Repeat** (identical runs), **Rephrase** (varied prompt phrasing), **Break** (injected tool/timeout/rate-limit faults), and **Bound** (strict token/turn/time caps).
3. **Economics & Host Health `[TARGET]`:** Cost per task, **cost per resolved task**, **Prompt Cache Hit `%`** (`cached_input / total_input`), per-tier token splits (orchestrator input/cached/output/reasoning vs. worker), latency `p50`/`p95`, and empirically verified local **GPU residency `%`** (flagging VRAM CPU-spill anomalies).
4. **Internal Harness Funnel `[TARGET]`:** Trace-derived diagnostic rates separating where tasks fail: *Tool-Schema Validity `%` → Localization Recall `%` → Worker Edit Fidelity & Rollback `%` → Verification Closure `%`*.

### 3.2 Stage 0 Benchmark Self-Test Suite (`tests/test_benchmark_*.py`) `[TARGET]`
Every benchmark runner must pass an offline pure-Python self-test suite (zero LLM calls, wired into `python scripts/check.py --benchmarks`) verifying the harness itself cannot emit false positives:
1. **Decontamination check:** Stripped workspace has exactly 1 fresh orphan commit and zero prior history/remotes.
2. **Invalid-baseline quarantine:** Mock pre-passing `F2P` baseline is flagged `INVALID_BASELINE` and never scored `resolved=True`.
3. **Test-tampering rejection:** Candidate diff touching a protected/test path fails with `TAMPER_DETECTED`.
4. **Missing-test anti-inflation:** Partial test output omitting a required `F2P` or `P2P` test ID marks `MISSING` and fails (`resolved=False`).
5. **Planted-cheat scanner:** Mock traces containing `git log`, `git cat-file`, `/tmp` sweeps, or secret reads are detected `100%` and downgrade `cheating_adjusted_rate`.
6. **KPI sanity bounds:** `pass^k`, cost, cache hit, and funnel aggregators assert realistic bounds (`0..1`, zero NaNs, conserved denominators).

### 3.3 Host, Sandbox & New-Runner Preflight Gate `[TARGET / PROCESS]`
1. **Zero-LLM Host & Sandbox Preflight (Mandatory Before Every Live Run) `[TARGET]`:** Run an automated preflight check verifying: (a) container/sandbox runtime is reachable and supports `--network none`, (b) host disk has sufficient headroom for images and disposable workspaces, (c) configured provider credentials resolve cleanly via process env or gitignored `.env` without printing secrets, (d) when a local worker participates, the model is loaded at `100%` GPU residency with zero silent CPU spill, and (e) any suite-specific external CLI (e.g., Harbor) is installed and callable. Abort before spending tokens if any check fails.
2. **Benchmark-Author Onboarding Contract `[PROCESS]`:** Anyone adding a new benchmark runner or suite adapter must wire all six invariants before executing live runs: workspace decontamination (§2.3), pre-solve baseline validity gate (§2.5), privilege-separated grading (§2.4), trace cheat-scanning (§2.7), canonical 3-key `results.json` emission (§3.1), and Stage 0 offline self-tests (§3.2).

---

## 4. Coding-Agent Autopilot Runbook & 8-Point Truth Check `[PROCESS]`

Contributors typically delegate benchmark runs to a coding agent (`Antigravity`, `Codex`, `Claude Code`) in a single prompt. Execute these **7 steps automatically**:

1. **Lock `PROTOCOL.md` & Budget First:** Inspect Git SHA, models, local GPU residency, and task slice; create `docs/worklogs/<person>/YYYY-MM-DD_<slug>/PROTOCOL.md` with pre-run call and cost estimates. **Pause for explicit human approval** before any paid or large multi-task batch.
2. **Run Stage 0 Offline Gate & Host Preflight:** Execute `python scripts/check.py` (including `--benchmarks` self-tests once implemented) AND the zero-LLM Host/Sandbox Preflight (§3.3). Stop immediately if any check fails.
3. **Run Pre-Solve Baseline Preflight:** Confirm baseline oracle validity per task; quarantine `INVALID_BASELINE` cases before spending live tokens.
4. **Execute Decontaminated Run & Save Evidence:** Run inside the sealed sandbox; keep raw traces/logs in gitignored `output/` and save sanitized `results.json`, `provenance.json`, and `patches/` in the worklog dossier.
5. **Execute the Mandatory 8-Point Truth Check (Anti-False-Result Audit):** Record explicit `PASS`/`FAIL` for every item before citing any score:
   - `[ ]` **1. Decontamination active:** `.git` stripped to 1 orphan commit, network sealed, `/tmp` & secrets isolated.
   - `[ ]` **2. Valid baselines only:** Every scored task failed `F2P` and passed `P2P` pre-patch (invalid tasks quarantined).
   - `[ ]` **3. Patch integrity clean:** Candidate diff non-empty, `git apply` succeeded cleanly, `0` protected/test paths modified.
   - `[ ]` **4. Zero phantom test passes:** `100%` of `F2P` and `P2P` IDs explicitly parsed as `PASSED` (`0` `MISSING`/`SKIPPED` treated as pass).
   - `[ ]` **5. Trace cheat-audit passed:** Command/tool scanner returned `0` hits (or Cheating-Adjusted score explicitly downgraded).
   - `[ ]` **6. Full denominators preserved:** Every quota block, timeout, infra crash, and abort remains in `total_n`.
   - `[ ]` **7. Host telemetry valid:** Local GPU residency verified (no silent VRAM CPU-spill corrupting latency/timeouts).
   - `[ ]` **8. Compute, then narrate:** Every number in `REPORT.md` computed programmatically from `results.json` with explicit `N` and `seed` (small-sample honesty when $N < 30$).
   *(If Checks 1–5 fail due to a harness defect, mark the entire run **`INVALID_HARNESS`** — never report it as a benchmark score.)*
6. **Trace Failures & Separate Proven Fixes From Hypotheses:** Complete §5 for every non-passing case.
7. **Document & Validate:** Write `REPORT.md`, update `docs/BENCHMARK_SCORECARD.md` (Held-Out / Milestone runs only), run `python scripts/update_worklog_index.py` and `python scripts/check.py`, and leave `dev_rules/` untouched (emit a `Rule Proposal:` only on strict triggers).

---

## 5. Failure Tracing, Evidence-vs-Hypothesis Triage & Promotion Gate `[PROCESS]`

1. **6-Bucket Deterministic Failure Triage:** Trace every failed/blocked task to its **earliest failing turn** and assign exactly one root bucket:
   - **(1) Infra / Quota / Invalid Baseline** *(fix runner/provider or quarantine — never tweak agent prompts for Bucket 1)*,
   - **(2) Tool / Protocol / Anchor Friction**,
   - **(3) Localization Failure**,
   - **(4) Worker Edit Fidelity**,
   - **(5) Verification / Turn-Budget Exhaustion**,
   - **(6) True Model Reasoning / Architecture Ceiling**.
2. **`0%` `pass@k` Grader-First Rule:** When strong baselines score `0%` repeatedly on a task, audit the task specification and container grader before blaming the agent.
3. **Mandatory Evidence vs. Hypothesis Split (Zero Guesswork Disguised as Fixes):**
   - **Proven Fix Proposal (`PROVEN CAUSE`):** Permitted **only** when directly evidenced by trace, diff, or code (citing exact `file:line`, turn #, error envelope, or patch). Must specify: *exact target symbol*, *trace proof*, *expected funnel effect*, and *Stage 0 offline regression test*.
   - **Open Hypothesis (`HYPOTHESIS — UNPROVEN`):** Required whenever causality is ambiguous or multi-factor. State the missing evidence and propose the **cheapest 1-variable diagnostic probe** to confirm or falsify before changing code.
4. **Pareto Promotion Gate & Regression Ratchet:** Promote a change to default only if accuracy / `pass^k` improves (or holds equal at lower cost per resolved task) with **zero** Stage 0 or Stage 4A safety/integrity regressions. Ratchet every fixed harness bug into a Stage 0 offline test and every escaped real coding failure into a Stage 4D Private Gold case.

---

## 6. Progressive 5-Stage Complexity Gate & Reference Suite Roster `[PROCESS]`

Advance strictly from Stage 0 → Stage 4; never fund a harder stage while an earlier stage's exit gate is red.

> **Periodic Suite Validity & Replacement Rule `[PROCESS]`:** Benchmarks contaminate, saturate, and deprecate quickly. Before starting a new milestone cohort, verify whether each reference suite below remains uncontaminated, maintained, and competitive with newer SOTA suites. Update active splits, replacements, and SOTA reference numbers in [`../docs/BENCHMARKING_ARCHITECTURE.md`](../docs/BENCHMARKING_ARCHITECTURE.md) and [`../docs/BENCHMARK_SCORECARD.md`](../docs/BENCHMARK_SCORECARD.md), and propose updating this reference table whenever a stage suite is replaced or retired.

### Current Reference Suite Selection *(Last Reviewed: `2026-11-26` — Non-Binding Periodic Re-Audit Target)*

| Stage | Capability Gate | Reference Benchmark Suites *(Decided `2026-11-26`)* | Exit Gate to Next Stage |
| :--- | :--- | :--- | :--- |
| **Stage 0** | Offline Harness & Self-Test | `scripts/check.py` + `tests/test_benchmark_*.py` (`--benchmarks`) | `100%` offline green before any live token spend |
| **Stage 1** | Core Execution & Asymmetric Lift | `Terminal-Bench 4.1` (Harbor), `SWE-bench Verified` *(legacy calibration only)*, `SWE-sweep` / 3-arm control (Minimal vs. Orch-Only vs. Hybrid) | `0` cheat flags, `100%` valid baselines, positive harness lift or cost win |
| **Stage 2** | Decontaminated Frontier & Multilingual | `SWE-bench-Live` / `SWE-rebench`, `Multi-SWE-bench`, `DeepSWE v1.1` / `FrontierSWE v2`, filtered strict-isolated `SWE-bench Pro`, `FrontierCode 2.0` | Verified solves on unseen post-cutoff & non-Python repos with clean diffs |
| **Stage 3** | Repeatability, Stress & Pareto | Frozen Core Cohort `pass^k` ($k \ge 3$), 4-axis Reliability Envelope (*Repeat/Rephrase/Break/Bound*), effort/edit-strategy/cache Pareto sweeps | Meets target `pass^3` floor, clean fault recovery, Pareto-optimal defaults |
| **Stage 4** | Full-SDLC, Safety & Private Gold | **4A (Mandatory):** `CHEATBENCH`, `ImpossibleBench`, `Blocker Deception`, `Destructive Action Avoidance`; **4B (Primary):** `SWE Atlas`, `Commit0`/`FeatureBench`, `SWE-Chain`; **4C (Opt-In):** `SWE-Together`/`τ²-bench`, `CyberGym`/`SecureSWE`, `MicroPerf-Bench`, UI/MCP/Swarm suites; **4D:** Private Gold Suite (`20–50` internal tasks) | `0` safety/anti-cheat regressions; Private Gold `pass^3` + Pareto release gate green |

---

## 7. Optional Human-in-the-Loop Evaluation Checks `[PROCESS — OPTIONAL]`

Human audits are **optional** and never block automated coding-agent runs, but provide high-signal oversight at milestones. Record the audit tier explicitly in `REPORT.md` (`Human Audit: None (Automated) | Spot-Checked | Blind PR Reviewed`):

1. **Milestone Diff & Trace Spot-Audit:** Inspect a small sample (e.g., 3 passing diffs, 3 failing traces, and any `0%` task) to catch weak-test hacks, broken benchmark specs, or novel cheat patterns.
2. **Blind "Would I Merge This PR?" Review:** Review label-stripped diffs from 5–10 tasks like real GitHub PRs, recording *zero-edit mergeability*, *human review time*, and *repo-convention fit*.
3. **LLM-Judge Calibration:** Human-score 5–10 samples once before trusting an automated cross-family rubric judge (Stage 4B).
4. **Live Dogfooding & Time-Trial:** Track real multi-turn sessions (acceptance rate, manual rework minutes) and convert every human-caught defect into a permanent Stage 4D Private Gold automated oracle.

---

## 8. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial SOTA benchmarking & evaluation guardrails: full-system UUT attribution, strict decontamination & privilege-separated output verification, deterministic KPI contract, Stage 0 self-test suite & host/sandbox preflight gate, 7-step coding-agent autopilot runbook with 8-point Truth Check, 6-bucket Evidence-vs-Hypothesis triage, progressive 5-stage ladder with dated (`2026-11-26`) reference suite roster, and optional human-in-the-loop audit checks. |
