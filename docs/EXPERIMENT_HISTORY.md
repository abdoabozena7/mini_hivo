# Experiment history on `main`

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 EXPERIMENT ROUTE (DO NOT USE):** Mini Hivo is **v2 only**. The legacy v1 single-model experiment route (Experiments 1–22, `reports/`, `updates/`, `mini.py`) is retired historical record and is no longer used. Active v2 work and benchmarks are tracked in [`worklogs/INDEX.md`](worklogs/INDEX.md), [`BENCHMARKING_ARCHITECTURE.md`](BENCHMARKING_ARCHITECTURE.md), and [`BENCHMARK_SCORECARD.md`](BENCHMARK_SCORECARD.md).

Checkpoint: 2026-11-16. The original core feature work was previously transplanted into a linear series on `main`. The [history-preserving consolidation](BRANCH_CONSOLIDATION.md) now also makes the original feature commits ancestors of `main`, without replaying their older implementation over newer fixes. Experiments 17–19 are integrated through a separate content merge. Original branch names and complete commit IDs are retained in the consolidation inventory, so retiring a branch name does not remove its history.

## Contributor fork history, preserved during PR #1 integration

The following entries describe the contributor fork's earlier checkpoints, not publication to this upstream repository. Independent workstreams reused Experiment 18/19 identifiers: their reports and measurements are retained separately in the [results index](../reports/INDEX.md), never pooled or overwritten.

### Unified contributor `main` integration — 16 November 2026

`main` fast-forwarded to `codex/experiment22-verification-integrity` (`4502318`, integrating Experiment 22 and PR #9/#10's production verification-integrity and child-scoped verification changes), cherry-picked PR #9's live-evidence documentation commit (`ac85b95`, reconciling `reports/INDEX.md`), and integrated the retrospective Experiment 3 / Experiment 18A follow-up reports from PRs #11 and #12 (`ac49c44`, `97e125a`) with explicit integration addenda clarifying that PR #7 (`5e66d34` / `2a8b945`) was already merged via Experiment 20 (`68000c7`). Draft WIP PR #8 remains unmerged and outside `main`.

## Isolated follow-up on this branch — 8 November 2026

Experiment 22 builds on Experiment 21 `56b328d` and integrates PR #9's verification-outcome integrity implementation once with PR #10's child-scoped verification changes. It fixes a reproduced parser case where `{"status":"ERROR","passed":true}` was treated as PASS. The parser now requires recognized, mutually consistent statuses; unknown/conflicting receipts are unavailable and explicit failures remain failures. [Report](../reports/experiment22/experiment22-report.md), [protocol](../reports/experiment22/PROTOCOL.md), and [181-method selected regression results](../reports/experiment22/experiment22-results.json). PRs #11/#12 are unrelated retrospective documentation submissions with stale PR #7 status claims; neither was merged into this experiment. No live-model or full E2E result is claimed.

## Isolated follow-up on this branch — 8 November 2026

Experiment 21 builds on Experiment 20 and integrates Rodina's PR #6 (including #5), fixing compact literal-colon parsing. Implementation: `cc8706e`, branch `codex/experiment21-rodina`. [Report](../reports/experiment21/experiment21-report.md), [protocol](../reports/experiment21/PROTOCOL.md), [results](../reports/experiment21/experiment21-results.json). All 167 focused checks pass with Edge and three scripted-provider functional replays verify exact file bytes and root completion. Full regression retains the same baseline failure/error IDs. This is local integration, not a published-main or live-model success claim.

## Isolated follow-up on this branch — 27 October 2026

Experiment 20 integrates Tasneem's PR #7 (including #2), #3 and #4 on `codex/experiment20-tasneem`, preserving local cloud-model support. Source merges: `68000c7`, `0cd4a77`, `2420473`; test-only correction: `a4ad142`. [Report](../reports/experiment20/experiment20-report.md), [protocol](../reports/experiment20/PROTOCOL.md), [results](../reports/experiment20/experiment20-results.json). All 91 focused checks pass with installed Edge; the full comparison has no new failure/error IDs after the test correction, but retains existing suite/architecture failures. This entry does not claim these commits are published on main or that a new live application run succeeded.

## Original upstream experiment history

| Experiment | Commit(s) | What the commit records |
|---|---|---|
| 1 | `e89e2e5`, `5d56599` | Decomposition-first planning and outcome percentages |
| 2 | `c697cc6`, `19e877f` | Contract mission fallback and paired report |
| 3 | `d83876e` | Progress-constrained Worker and paired metrics |
| 4 | `7f2f4d3` | Evidence-grounded mutation and paired report |
| 5 | `fc21e38` | Evidence-directed target localization |
| 6 | `7849040` | Verification environment failure classification |
| 7 | `0859b8a` | Browser verification surface discovery |
| 8 | `e31fe36` | Atomic verified child receipt and comparison |
| 9 | `c367eae` | Integration target resolution and fresh parent verification |
| 10 | `5c03694` | Child verification handoff diagnostics and replay |
| 11 | `9db6907` | Semantic evidence compatibility and receipt validation |
| 12 | `19f6317` | Five-task generalization and reliability benchmark; [report](../reports/experiment12/experiment12-report.md) |
| 13 | `85a57f7` | Monotonic semantic compatibility; [report](../reports/experiment13/experiment13-report.md) |
| 14 | `b61c474` | Strict aggregation compatibility; [report](../reports/experiment14/experiment14-report.md) |
| 15 | `e768fda` | Bounded evidence-to-edit binding; [report](../reports/experiment15/experiment15-report.md) |
| 16 | `6eeca6c` | Timer/Python first-blocker isolation; [report](../reports/experiment16/experiment16-report.md) |
| 17 | `cbed365`, `a855283` | Opt-in field-scoped browser classification, [deterministic checkpoint](../reports/experiment17/classification-protocol.md), and [nine fresh approved-contract outcomes](../reports/experiment17/experiment17-report.md) |
| 18 | `9c7b51f` | Opt-in bounded no-tool Worker re-anchor and [Python/Timer audit](../reports/experiment18/no-tool-exit-report.md) |
| 19 | `9ad7daf` | Opt-in mandatory context-decision closure and [controlled Python comparison](../reports/experiment19/context-decision-closure-report.md); no default promotion |
| Consolidation | `f65f1ab`, `1f067ed` | Original core ancestry merge and Experiment 17–19 content merge; [decisions, repairs, and fresh validation](BRANCH_CONSOLIDATION.md) |

Commits preserve their original author and commit dates. Reports and numeric JSON results for Experiments 1–19 are indexed in [reports/INDEX.md](../reports/INDEX.md), along with the available comparison artifacts. Historical raw run workspaces remain outside the Git repository, so GitHub does not contain every old raw trace. In particular, a completed experiment report is not a claim that every task succeeded: Timer still failed child/root completion in Experiment 17, and the Experiment 19 closure policy did not establish a reliability improvement.
