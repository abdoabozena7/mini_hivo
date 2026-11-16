# Experiment history on `main`

Checkpoint: 2026-11-16. The original core feature work was previously transplanted into a linear series on `main`. The [history-preserving consolidation](BRANCH_CONSOLIDATION.md) now also makes the original feature commits ancestors of `main`, without replaying their older implementation over newer fixes. Experiments 17–19 are integrated through a separate content merge. Original branch names and complete commit IDs are retained in the consolidation inventory, so retiring a branch name does not remove its history.

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
| 18 | `9c7b51f` | Opt-in bounded no-tool Worker re-anchor and [Python/Timer audit](../reports/experiment18/experiment18-report.md) |
| 19 | `9ad7daf` | Opt-in mandatory context-decision closure and [controlled Python comparison](../reports/experiment19/experiment19-report.md); no default promotion |
| Consolidation | `f65f1ab`, `1f067ed` | Original core ancestry merge and Experiment 17–19 content merge; [decisions, repairs, and fresh validation](BRANCH_CONSOLIDATION.md) |

Commits preserve their original author and commit dates. Reports and numeric JSON results for Experiments 1–19 are indexed in [reports/INDEX.md](../reports/INDEX.md), along with the available comparison artifacts. Historical raw run workspaces remain outside the Git repository, so GitHub does not contain every old raw trace. In particular, a completed experiment report is not a claim that every task succeeded: Timer still failed child/root completion in Experiment 17, and the Experiment 19 closure policy did not establish a reliability improvement.
