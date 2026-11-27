# Team Worklogs & Evidence Locker (`docs/worklogs/INDEX.md`)

This is the team's chronological evidence locker for detailed, small-scoped engineering and research work dossiers.
**Row 1 of the Latest Activity table below is always the most recent worklog across all contributors** — check it before starting your assigned track to see what recently landed on adjacent tracks and any open follow-up issues.

- **Policy:** Read [`../../dev_rules/documentation_rules.md`](../../dev_rules/documentation_rules.md) before creating or updating a dossier.
- **Templates:** Copy [`REPORT_TEMPLATE.md`](REPORT_TEMPLATE.md) (every dossier), [`PROTOCOL_TEMPLATE.md`](PROTOCOL_TEMPLATE.md) (`Type: experiment`), and [`PROVENANCE_TEMPLATE.json`](PROVENANCE_TEMPLATE.json) (`test`/`change`/`experiment`).
- **Auto-regenerate & validate (prevents merge conflicts):** Run `python scripts/update_worklog_index.py` (or `--check` in CI/review) after adding a dossier.
- **Folder hygiene:** Keep `.gitkeep` inside each contributor folder so empty directories remain tracked across branches.
- **Frozen legacy archives:** Historical pre-worklog records stay untouched in [`../../reports/INDEX.md`](../../reports/INDEX.md) and `updates/`.

---

## Latest Activity (Newest First)

| Date | Author | Type | Subsystem | Status | Headline & Open Next Issue | Report | Data / Chain |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `2026-11-27` | kareem | `change` | `docs / dev_rules / providers / hybrid` | `verified` | Completed the v2-only documentation and rule cutover across `README.md`, `docs/PROJECT_STATUS.md`, all living v2 architecture docs, all 1... **Next:** Run live v2 prompt / E2E test with Groq (`qwen/qwen3.8-27b` or `openai/gpt-oss-120b`) + local Ollama `qwen3.5:2b-q4_K_M`, then wire user-facing v2 prompt CLI and computed `unified_diff` in `dispatch_worker | [Mini Hivo v2-Only Documentation Cutover, Rule Alignment & Live Hybrid Model Readiness](kareem/2026-11-27_v2-only-docs-and-live-model-readiness/REPORT.md) | [prov](kareem/2026-11-27_v2-only-docs-and-live-model-readiness/provenance.json), from [Stage 0 Benchmark Harness Hardening, Self-Test Suite & Host Preflight](../2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md) |
| `2026-11-27` | kareem | `change` | `hivo/benchmarks / scripts / tests` | `verified` | Implemented Mini Hivo's stdlib-only Stage 0 benchmarking core ([`hivo/benchmarks/`](../../../../hivo/benchmarks/__init__.py)), hardened [... **Next:** Add higher-quota cloud provider key (e.g., `NVIDIA_API_KEY` or OpenRouter) in local `.env`, install `harbor` CLI, and build Stage 1 `Terminal-Bench 4.1` Harbor adapter + sealed `SWE-bench` calibration run | [Stage 0 Benchmark Harness Hardening, Self-Test Suite & Host Preflight](kareem/2026-11-27_stage0-benchmark-harness-and-preflight/REPORT.md) | [prov](kareem/2026-11-27_stage0-benchmark-harness-and-preflight/provenance.json), from [SOTA Benchmarking Rules, 2026 Progressive Plan & Initial Scoreboard](../2026-11-26_benchmarking-rules-and-sota-plan/REPORT.md) |
| `2026-11-27` | kareem | `experiment` | `hivo/hybrid / hivo/tools / live-ablation` | `verified` | Evaluated Mini Hivo v2 across 4 isolated live runs on a zero-hint 3-file Neon Breakout visual & gameplay repair task (`0/10` pre-solve ba... **Next:** Fix `_compact_history()` to account for serialized `assistant.tool_calls` JSON (eliminating `HTTP 413`), add inline CSS brace-balance syntax checking in `hivo/tools/base.py`, and re-run Breakout with diff-checked retry + higher-ITPM cloud endpoint (`NVIDIA_API_KEY` or OpenRouter) | [Neon Breakout Visual & Gameplay Repair — 4-Run Hybrid Ablation, `unified_diff` Upgrade & Root-Cause Triage](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md) | [protocol](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/PROTOCOL.md), [results](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/results.json), [prov](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/provenance.json), [patches](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/patches/), from [Mini Hivo v2-Only Documentation Cutover, Rule Alignment & Live Hybrid Model Readiness](../2026-11-27_v2-only-docs-and-live-model-readiness/REPORT.md) |
| `2026-11-26` | kareem | `change` | `dev_rules / docs / worklogs` | `verified` | Separated Mini Hivo's development governance into three layers — prescriptive subsystem rules (`dev_rules/`), shared living architecture... **Next:** Return computed `unified_diff` in `dispatch_worker` (`hivo/hybrid/runner.py`) to catch silent light-worker edit defects immediately | [Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker](kareem/2026-11-26_dev-rules-and-worklog-policy/REPORT.md) | [prov](kareem/2026-11-26_dev-rules-and-worklog-policy/provenance.json) |
| `2026-11-26` | kareem | `change` | `dev_rules / docs / benchmarking` | `verified` | Added Mini Hivo's dedicated SOTA benchmarking guardrails ([`dev_rules/benchmarking_rules.md`](../../../../dev_rules/benchmarking_rules.md... **Next:** Implement Stage 0 benchmark runner hardening (`.git` strip, `--network none`, pre-solve baseline quarantine, trace cheat-scanner, 3-key KPI emitter, host/sandbox preflight CLI) + offline self-test suite `tests/test_benchmark_*.py` wired into `python scripts/check.py --benchmarks | [SOTA Benchmarking Rules, 2026 Progressive Plan & Initial Scoreboard](kareem/2026-11-26_benchmarking-rules-and-sota-plan/REPORT.md) | [prov](kareem/2026-11-26_benchmarking-rules-and-sota-plan/provenance.json), from [Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker](../2026-11-26_dev-rules-and-worklog-policy/REPORT.md) |

---

## Recent Tier 1 Fixes (Quick Log)

Accumulated small code fixes, minor refactors, and typo fixes logged as 1-line rows in each contributor's `docs/worklogs/<person>/LOG.md` (newest 25 shown):

| Date | Author | Area | Tier 1 Change | Verification | PR / Commit | Log |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *(no Tier 1 entries yet)* | — | — | Append 1 row to `docs/worklogs/<person>/LOG.md` and run `update_worklog_index.py` | — | — | — |

---

## Pending Rule Proposals (Maintainer Review Queue)

Coding agents and feature PRs must **never** auto-edit `dev_rules/*.md`, `AGENTS.md`, or `CLAUDE.md`. Any worklog carrying an unresolved `Rule Proposal:` metadata entry appears below for explicit maintainer review (prefix `[APPLIED]`, `[REJECTED]`, or `[DEFERRED]` once resolved to clear this queue while preserving history):

| Date | Author | Subsystem | Proposed Rule Update (NOT APPLIED) | Evidence Dossier |
| :--- | :--- | :--- | :--- | :--- |
| `2026-11-27` | kareem | `hivo/hybrid / hivo/tools / live-ablation` | PROMOTE orchestration_rules.md §6.2 unified_diff -> ENFORCED; ADD orchestration_rules.md §5.2 tool_calls compaction accounting [TARGET]; AMEND tool_rules.md §4 Contract 4 CSS syntax check [TARGET] | [Neon Breakout Visual & Gameplay Repair — 4-Run Hybrid Ablation, `unified_diff` Upgrade & Root-Cause Triage](kareem/2026-11-27_breakout-visual-repair-hybrid-ablation/REPORT.md) |

---

## Contributor Folders

| Contributor | Folder | Tier 2 Dossiers | Tier 1 Quick Log | Latest Tier 2 Entry |
| :--- | :--- | :---: | :---: | :--- |
| Abozena | [`abozena/`](abozena/) | `0` | [`0`](abozena/LOG.md) | — |
| Ahmed | [`ahmed/`](ahmed/) | `0` | [`0`](ahmed/LOG.md) | — |
| Fatma | [`fatma/`](fatma/) | `0` | [`0`](fatma/LOG.md) | — |
| Kareem | [`kareem/`](kareem/) | `5` | [`0`](kareem/LOG.md) | `2026-11-27` — [Mini Hivo v2-Only Documentation Cutover, Rule Alignment & Live Hybrid Model Readiness](kareem/2026-11-27_v2-only-docs-and-live-model-readiness/REPORT.md) |
| Marihan | [`marihan/`](marihan/) | `0` | [`0`](marihan/LOG.md) | — |
| Renad | [`renad/`](renad/) | `0` | [`0`](renad/LOG.md) | — |
| Rodina | [`rodina/`](rodina/) | `0` | [`0`](rodina/LOG.md) | — |
| Shoip | [`shoip/`](shoip/) | `0` | [`0`](shoip/LOG.md) | — |
| Tasneem | [`tasneem/`](tasneem/) | `0` | [`0`](tasneem/LOG.md) | — |
| Youssef | [`youssef/`](youssef/) | `0` | [`0`](youssef/LOG.md) | — |
