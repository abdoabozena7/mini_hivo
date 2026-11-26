# Mini Hivo — Benchmarking Architecture & 2026 SOTA Plan (`docs/BENCHMARKING_ARCHITECTURE.md`)

> - **Status:** Living benchmark plan, harness inventory & KPI schema (`v0.1`, initial suite selection `2026-11-26`)
> - **Governing Rules:** [`../dev_rules/benchmarking_rules.md`](../dev_rules/benchmarking_rules.md) *(prescriptive invariants, autopilot runbook, 8-point Truth Check, promotion gates)*
> - **Companion Scoreboard:** [`BENCHMARK_SCORECARD.md`](BENCHMARK_SCORECARD.md) *(version-locked `2026-11-26` SOTA reference snapshot & Mini Hivo v2 tracking tables)*
> - **Related Living Docs:** [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md), [`TOOLS_ARCHITECTURE.md`](TOOLS_ARCHITECTURE.md), [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md), [`worklogs/INDEX.md`](worklogs/INDEX.md)
> - **Historical Reference:** `mini.py`, `reports/`, and `updates/` remain read-only historical archives preserving Mini Hivo's chronological evolution and earlier v1/v2 baseline findings (including Experiment 23).

---

## 1. Selected Benchmark Roster (Decision Date: `2026-11-26`)

Every benchmark below was selected on **`2026-11-26`** to progress Mini Hivo's active v2 asymmetric architecture (`hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`) from zero-cost harness self-checks through frontier SOTA parity. Re-audit this roster before each major milestone to verify no suite has saturated, leaked, or been superseded.

| # | Stage | Benchmark *(Exact Version)* | Decision Date | Dataset / Planned Slice (`seed=42`) | Verification Mechanism | Status | Selection Rationale |
|---:|---|---|---|---|---|---|---|
| **1** | **Stage 0** | **Mini Hivo Offline & Benchmark Self-Test Suite** (`scripts/check.py --benchmarks`) | `2026-11-26` | Pure-Python offline unit + adversarial mock fixtures (`tests/test_benchmark_*.py`) | Deterministic assertions (`.git` strip, invalid baseline, tamper, cheat trace, KPI bounds) | **Mandatory (Build First)** | Guarantees the benchmark runner itself cannot emit false positives before spending API tokens |
| **2** | **Stage 1** | **`Terminal-Bench 4.1`** *(Harbor)* | `2026-11-26` | 66 containerized CLI tasks (`Dev: 15–20` → `Held-Out: full 66`) | Hidden post-run container `pytest` + Cheating-Adjusted Accuracy | **Active (Must-Do #1)** | Primary 2026 industry standard for headless shell execution, recovery, and anti-cheat discipline |
| **3** | **Stage 1** | **`SWE-bench Verified`** *(Legacy Calibration)* | `2026-11-26` | `princeton-nlp/SWE-bench_Verified` valid-baseline filtered slice (`Dev: 10`, `Calib: 15–25`) | Official Docker `F2P` + `P2P` (pre-solve baseline gated) | **Active (Calibration Only)** | Direct bridge from Experiment 23 (`1/3`) to validate immediate harness upgrades; explicitly labeled legacy/contaminated |
| **4** | **Stage 1** | **`SWE-sweep` / 3-Arm Scaffold-Lift Control** | `2026-11-26` | Paired `N=15` slice across 3 arms: *(A)* Minimal Loop vs. *(B)* Orch-Only vs. *(C)* Hybrid (`Orch + Local Worker`) | Same containerized `F2P`/`P2P` + Harness Lift (`B - A`) + Asymmetric Cost Ratio (`C vs. B`) | **Active (Thesis Proof)** | Quantifies pure harness multiplier (`Δ_harness`) and cost-efficiency of asymmetric worker delegation |
| **5** | **Stage 2** | **`SWE-bench-Live`** *(or `SWE-rebench`)* | `2026-11-26` | Continuously updated post-cutoff GitHub issue-PR pairs (`N=25–50`) | Isolated Docker `F2P` + `P2P` | **Queued (Stage 2)** | Eliminates pretraining memorization from repository fix rates |
| **6** | **Stage 2** | **`Multi-SWE-bench`** | `2026-11-26` | Stratified `N=20–40` across TypeScript/JS, Java, Go, Rust | Isolated multi-language Docker `F2P` + `P2P` | **Queued (Stage 2)** | Proves `code_intel` regex/brace fallback and Hashline editing generalize outside Python |
| **7** | **Stage 2** | **`DeepSWE v1.1` / `FrontierSWE v2`** | `2026-11-26` | Uncontaminated long-horizon real-repo tasks (`N=20–30`) | Isolated container execution oracle | **Queued (Stage 2)** | High-ceiling uncontaminated 2026 frontier discriminators |
| **8** | **Stage 2** | **`SWE-bench Pro`** *(Strict-Isolated & Filtered)* | `2026-11-26` | Filtered subset of 731 public multi-file/commercial tasks (quarantining broken/invalid baselines) | Strict `.git`-stripped, network-sealed Docker `F2P` + `P2P` | **Queued (Stage 2)** | Tests commercial multi-file complexity while filtering the ~30% raw flawed tasks |
| **9** | **Stage 2** | **`FrontierCode 2.0`** *(Zero-Edit Mergeability)* | `2026-11-26` | Mergeability slice + automated lint/diff hygiene gate (+ optional blind human PR review) | Clean diff, minimal scope, style/lint pass, zero human cleanup | **Queued (Stage 2)** | Enforces merge-ready production craft beyond bare test passage |
| **10** | **Stage 3** | **Core Cohort `pass^k` + 4-Axis Reliability Envelope** | `2026-11-26` | Frozen `15–20` tasks spanning Stages 1–2 × `n=5` trials (`n=8` milestones) + Repeat/Rephrase/Break/Bound | `pass^1`/`pass^3`/`pass^5`, fault recovery, `$/resolved`, Cache Hit `%`, GPU residency `%` | **Queued (Stage 3)** | Separates operational repeatability and Pareto economics from single-run flukes |
| **11** | **Stage 4A** | **`CHEATBENCH` + `ImpossibleBench` + `Blocker Deception` + `Destructive Action Avoidance`** | `2026-11-26` | Curated adversarial integrity/safety battery (`N=20–30` across all 4 checks) | Honeypot trace audit, `ORACLE_LOCKED` tamper check, obstacle disclosure check | **Mandatory Release Gate** | Verifies Mini Hivo resists cheating, test editing, fabricating success, and destructive commands |
| **12** | **Stage 4B** | **`SWE Atlas` + `Commit0` / `FeatureBench` + `SWE-Chain`** | `2026-11-26` | Q&A, test authoring, refactors (`SWE Atlas`), greenfield/features (`Commit0`/`FeatureBench`), chained upgrades (`SWE-Chain`) | **No-op stub mutation kill rate**, cross-family LLM judge (human-calibrated), multi-file suites | **Queued (Stage 4 Primary)** | Directly validates v2 contract-complete decomposition ($\kappa \ge 0.90$) and DCVG beyond bugfixes |
| **13** | **Stage 4C** | **Opt-In Specialized Tracks** (`SWE-Together`/`τ²-bench`, `CyberGym`/`SecureSWE`, `MicroPerf-Bench`, `SWE-bench Multimodal`/`KingBench 4`, `MCP-Atlas`/`MultiAgentBench`/`GraphWalks`) | `2026-11-26` | Activated selectively only when Mini Hivo actively targets that domain | Domain-specific deterministic containers, traffic generators, or simulated users | **Opt-In (Roadmap-Gated)** | Prevents benchmark bloat while keeping an exact SOTA target ready per capability |
| **14** | **Stage 4D** | **Mini Hivo Private Gold Suite + Human PR Audit** | `2026-11-26` | `20–50` internal tasks from real Mini Hivo PRs, past bugs, and escaped failures (`Dev` vs. `Release` split) | Independent deterministic oracles + PR Smoke Gate + Milestone `pass^3` + blind PR check | **Active (Bootstrap Early)** | Eliminates overfitting to public repos and permanently ratchets every resolved failure |

---

## 2. SOTA Output Verification Pipeline (Zero-False-Result Mechanics)

Every automated benchmark runner executes this **6-step privilege-separated pipeline** — never trusting final agent prose:

```text
[1. Freeze UUT]      Pin (Orchestrator + Effort, Worker + Quant/Ctx, Harness Git SHA, ToolProfile Hash, Version, Seed)
        │
        ▼
[2. Pre-Solve Base]  Fresh container (0 LLM tokens): apply hidden test_patch to unpatched repo.
                     Require F2P < total AND P2P == total; quarantine failures as INVALID_BASELINE.
        │
        ▼
[3. Sealed Solve]    Strip .git -> 1 fresh orphan commit, wipe /tmp, mount 0 host secrets, --network none
                     (or allowlisted proxy), withhold test_patch & hints. Run bounded agent; log full trace to output/.
        │
        ▼
[4. Artifact Only]   Discard chat reply. Extract ONLY git diff (model_patch) or post-run container state.
        │
        ▼
[5. Fresh Grader]    Boot brand-new container untouched by agent: check non-empty diff -> clean git apply ->
                     0 protected/test file edits -> apply hidden tests / mutation / CLI pytest assertions
                     (100% F2P + 100% P2P parsed; 0 MISSING/SKIPPED counted as pass).
        │
        ▼
[6. Audit & Report]  Run deterministic command/tool cheat-scanner on full trace -> compute pass^k, $/resolved,
                     cache hit %, 6-stage funnel -> execute 8-Point Truth Check -> write results.json & REPORT.md.
```

---

## 3. Operational Defaults & Budget Controls (`2026-11-26`)

Concrete numeric defaults live here (keeping [`../dev_rules/benchmarking_rules.md`](../dev_rules/benchmarking_rules.md) Swap-Test compliant):

- **Repeatability Floor (Stage 3 & Releases):** **`pass^3`** computed over **`n = 5`** independent trials per task (`n = 8` for major milestone releases).
- **Pre-Run Cost & Scale Approval Trigger:** Require explicit human approval in chat before launching any live batch estimated at **`> $5` USD** OR **`> 20` tasks** (or any run switching to a paid endpoint preset in [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md)).
- **Dev vs. Held-Out Slice Rule:** Keep task ID manifests frozen and versioned inside the dossier `PROTOCOL.md` (or a dedicated slice manifest). Never report tuning scores from a Dev Slice on [`BENCHMARK_SCORECARD.md`](BENCHMARK_SCORECARD.md).
- **Stage 4 Activation Order:** Run **4A (Integrity/Safety)** + **4B (`SWE Atlas`, `Commit0`/`FeatureBench`)** + **4D (Private Gold)** first; enable **4C** tracks only when the corresponding subsystem is actively developed.
- **Disk & VRAM Hygiene:** On tight host drives (e.g., 4 GB VRAM laptops), remove per-task Docker images after grading (`1-image-at-a-time`), keep raw container logs/traces strictly in gitignored `output/`, and record local GPU residency (`ollama ps` / `nvidia-smi`) in `provenance.json`.

---

## 4. Canonical `results.json` Benchmark Payload Schema

Every `Type: experiment` benchmark worklog uses [`../dev_rules/documentation_rules.md`](../dev_rules/documentation_rules.md)'s uniform 3-key envelope (`{"meta", "summary", "cases"}`) with standardized deterministic fields:

```json
{
  "meta": {
    "date": "2026-11-26",
    "stage": "stage-1",
    "slice_role": "dev | held-out | calibration",
    "benchmark_name": "Terminal-Bench",
    "benchmark_version": "4.1",
    "seed": 42,
    "harness_sha": "<full-40-char-sha>",
    "tool_profile_hash": "<sha256-hex>",
    "orchestrator": {"provider": "openrouter", "model": "qwen/qwen3.8-27b", "effort": "medium"},
    "worker": {"runtime": "ollama", "model": "qwen3.5:2b-q4_K_M", "num_ctx": 4096, "gpu_residency_pct": 100.0},
    "decontamination": {"git_stripped": true, "network_mode": "none", "tmp_clean": true, "secrets_isolated": true},
    "truth_check": {"passed": true, "checks": {"1_decontam": true, "2_valid_baseline": true, "3_patch_integrity": true, "4_no_missing_tests": true, "5_cheat_audit": true, "6_full_denominators": true, "7_host_health": true, "8_computed_report": true}},
    "human_audit": "None (Automated) | Spot-Checked (3 pass, 3 fail) | Blind PR Reviewed"
  },
  "summary": {
    "total_n": 15,
    "invalid_baseline_n": 1,
    "infra_or_quota_blocked_n": 0,
    "valid_non_blocked_n": 14,
    "resolved_n": 6,
    "raw_resolve_rate": 0.4,
    "valid_resolve_rate": 0.429,
    "cheating_adjusted_rate": 0.429,
    "pass_hat_k": {"k": 1, "n_trials": 1, "value": 0.429},
    "total_usd": 0.84,
    "usd_per_resolved": 0.14,
    "cache_hit_rate": 0.62,
    "latency_p50_ms": 48200.0,
    "latency_p95_ms": 112500.0,
    "funnel": {
      "tool_schema_validity_rate": 0.98,
      "localization_recall_rate": 0.79,
      "worker_edit_fidelity_rate": 0.71,
      "worker_rollback_rate": 0.14
    },
    "failure_buckets": {
      "1_infra_quota_baseline": 1,
      "2_tool_protocol_anchor": 1,
      "3_localization": 2,
      "4_worker_edit_fidelity": 3,
      "5_verification_turn_budget": 1,
      "6_reasoning_ceiling": 1
    }
  },
  "cases": [
    {
      "task_id": "<instance-id>",
      "baseline_oracle": {"valid": true, "f2p_passed": 0, "f2p_total": 1, "p2p_passed": 6, "p2p_total": 6},
      "candidate_oracle": {"patch_applied": true, "protected_touched": [], "f2p_passed": 1, "f2p_total": 1, "p2p_passed": 6, "p2p_total": 6, "missing_tests": 0},
      "resolved": true,
      "trial_outcomes": [true],
      "cheat_flags": [],
      "failure_bucket": null,
      "earliest_failure_turn": null,
      "tokens": {"orch_in": 12400, "orch_cached_in": 8100, "orch_out": 1520, "orch_reasoning": 1800, "worker_in": 4900, "worker_out": 858},
      "usd": 0.04,
      "latency_ms": 19400.0,
      "funnel": {"localized": true, "dispatches": 1, "rollbacks": 0, "tool_schema_errors": 0}
    }
  ]
}
```

---

## 5. Current Harness Inventory & Stage 0 Implementation Backlog

### 5.1 Current Runner Status (`scripts/run_swebench_hybrid.py`)
Inspected on `2026-11-26`:
- **Already `[ENFORCED]`:** Artifact-only `git diff` extraction, zero solve-time leakage of `test_patch`/`F2P`/`P2P`/`hints_text`, `protected_paths` write-time lock, privilege-separated fresh Docker grading containers (`_docker_eval_once`), strict test-ID parsing (`MISSING != PASSED`), and 1-image-at-a-time cleanup.
- **Stage 0 `[TARGET]` Gaps to Implement Next (dedicated feature PR `feat/benchmark-harness-stage0`):**
  1. **Workspace decontamination:** Strip `.git` and re-init a single fresh orphan commit inside `_extract_testbed_to_host`; run containers with `--network none`; isolate `/tmp` and host env.
  2. **Move Baseline Oracle pre-solve:** Run `[ORACLE 1/2]` *before* `HybridAgentRunner.run()`, skip live solving when `F2P == total` or `P2P < total`, quarantine as `INVALID_BASELINE`, and gate `resolved` on `baseline_oracle_valid`.
  3. **Final-diff protected-path assertion:** Deterministically inspect `model_patch` headers (`+++ b/...`) before grading and reject (`TAMPER_DETECTED`) if any protected/test path appears.
  4. **Deterministic Trace Cheat-Scanner:** Scan executed tool/shell arguments in `agent_res.trace` for `.git` history mining (`git log`, `cat-file`, `fsck`, `reflog`), `/tmp` or secret scans, and network exfiltration; compute `cheating_adjusted_rate`.
  5. **Unified KPI Aggregator & 3-Key Emitter:** Emit §4's `{"meta", "summary", "cases"}` JSON with `pass^k`, `cache_hit_rate`, `estimated_usd` / `usd_per_resolved`, `latency_p50`/`p95`, and 6-stage funnel metrics.
  6. **Host & Sandbox Preflight Checker (`hivo/benchmarks/preflight.py`):** Zero-LLM CLI preflight checking Docker daemon + `--network none` capability, free disk space on container/workspace drives, `.env` provider key presence (zero secret output), Ollama + `100%` local GPU residency (when local worker enabled), and optional suite CLI availability (e.g., Harbor).
  7. **Harbor Adapter (`Terminal-Bench 4.1`):** Wrap Mini Hivo's `HybridAgentRunner` as a standardized Harbor agent runner for Stage 1 CLI benchmarking.

### 5.2 Stage 0 Benchmark Self-Test Suite Specification (`tests/test_benchmark_*.py`)
Wire into `python scripts/check.py --benchmarks` (zero LLM calls, required before every live run):
1. `test_decontamination_strips_git_history`: Creates a temp multi-commit repo with tags/remotes, runs the decontamination helper, and asserts `git rev-list --count HEAD == 1`, zero remotes, and zero prior commit messages reachable.
2. `test_invalid_baseline_quarantined`: Feeds a pre-passing `F2P` baseline output (`6/6`) and asserts `status == "INVALID_BASELINE"`, zero agent dispatch, and `resolved is False`.
3. `test_protected_path_tamper_rejected`: Feeds a candidate `model_patch` modifying `tests/test_app.py` and asserts `TAMPER_DETECTED` and `resolved is False`.
4. `test_missing_or_skipped_test_never_passes`: Feeds partial pytest/Django output missing a required `F2P` or `P2P` target and asserts `missing_tests > 0` and `resolved is False`.
5. `test_trace_cheat_scanner_catches_planted_exploits`: Feeds synthetic traces with `git log -n 5`, `git cat-file`, `cat /tmp/oracle`, and `.env` probes and asserts `100%` detection and downgraded `cheating_adjusted_rate`.
6. `test_kpi_aggregator_sanity_bounds`: Tests `pass^k` (`E[C(c,k)/C(n,k)]` against exact hand-verified binomial values), `usd_per_resolved`, `cache_hit_rate`, and 6-bucket conservation (`sum(buckets) == total_n - resolved_n`, all rates in `[0, 1]`, zero NaNs).
7. `test_preflight_reports_missing_deps_cleanly`: Verifies the host preflight fails closed with actionable remediation hints when Docker, disk headroom, local GPU residency, or API credentials are unavailable (and never prints secret values).

---

## 6. Contributor Reference: Local Setup, Preflight & New-Runner Checklist

### 6.1 Who Needs Local Setup?
- **Normal feature/tool/doc contributors:** Only run `git pull` and `python scripts/check.py` (strictly offline; zero Docker, Ollama, or API keys required).
- **Contributors executing *live* benchmarks locally (one-time machine setup):**
  1. **Provider key in local gitignored `.env`:** Copy `.env.example` → `.env` and set the chosen orchestrator provider key (see [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md)). Never commit `.env`.
  2. **Docker running & disk headroom:** Confirm `docker info` succeeds and keep sufficient free space on both the Docker image drive (1-image-at-a-time cleanup enabled by default) and the repo `output/` workspace drive.
  3. **Local worker warm & 100% GPU resident *(if running the hybrid local-worker arm)*:** Pull the target quantized worker in Ollama (e.g., `ollama pull qwen3.5:2b-q4_K_M`), enable Flash Attention + KV-cache quantization, and verify `100%` GPU residency with `ollama ps` + `nvidia-smi`.
  4. **Suite CLI *(only for suites that require it)*:** Install `harbor` once before running `Terminal-Bench 4.1`.
  5. **Run Preflight + Stage 0 Gate:** Execute `python scripts/check.py` (plus the Stage 0 host preflight once built in `feat/benchmark-harness-stage0`) before spending any live tokens.

### 6.2 Checklist for Anyone Authoring a New Benchmark Runner
Before running a newly added benchmark runner live, confirm all 6 items are wired and covered by offline tests in `tests/test_benchmark_*.py`:
- `[ ]` Workspace decontamination (`.git` stripped to 1 orphan commit, `--network none`, `/tmp` & secrets isolated).
- `[ ]` Pre-solve Baseline Oracle validity gate & `INVALID_BASELINE` quarantine.
- `[ ]` Privilege-separated fresh grading container + final-diff protected-path anti-tamper check.
- `[ ]` Deterministic trace cheat-scanner computing `cheating_adjusted_rate`.
- `[ ]` Canonical 3-key `results.json` (`{"meta", "summary", "cases"}`) + `provenance.json` emission.
- `[ ]` Host preflight hook + `1-image-at-a-time` cleanup when containers are heavy.

---

## 7. Optional Human-in-the-Loop Evaluation Guide

Keep execution and primary grading 100% automated, and layer optional human audits at milestones (recorded in `meta.human_audit` and `REPORT.md`):

1. **Milestone Diff & Trace Spot-Audit (~10–15 min):** Inspect 3 passing diffs, 3 failing traces, and every `0%` task across runs to catch weak-test hacks, underspecified benchmark tasks, or novel cheat tricks.
2. **Blind *"Would I Merge This PR?"* Review (~30 min per major release):** Strip branch/model labels on `5–10` tasks and have 1–2 teammates grade: *(a)* zero-edit mergeability (`Yes / Minor Edit / Reject`), *(b)* human review minutes, *(c)* repo-convention cleanliness.
3. **One-Time LLM-Judge Calibration (~20 min):** Human-score `5–10` Stage 4B refactoring outputs before trusting a cross-family LLM judge to score automatically.
4. **Live Dogfooding & Time-Trial:** Record real multi-turn usage (acceptance, manual rework minutes, net time saved) and convert every human-caught defect directly into a Stage 4D Private Gold automated test case.

---

## 8. Periodic Benchmark Review Log

| Review Date | Scope | Changes / Notes |
| :--- | :--- | :--- |
| `2026-11-26` | Initial 2026 SOTA roster (Stages 0–4) | Locked initial 14-entry roster (`Terminal-Bench 4.1`, `SWE-bench Verified` legacy calibration, `SWE-sweep`, `SWE-bench-Live`, `Multi-SWE-bench`, `DeepSWE v1.1` / `FrontierSWE v2`, filtered `SWE-bench Pro`, `FrontierCode 2.0`, `pass^k` Reliability Envelope, Stage 4A safety/anti-cheat, `SWE Atlas` / `Commit0` / `FeatureBench` / `SWE-Chain`, opt-in Stage 4C, and Private Gold Suite). |
