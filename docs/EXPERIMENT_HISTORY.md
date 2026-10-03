# Experiment history on `main`

Checkpoint: 2026-10-03. The core feature work preceding these experiments is already a linear series of commits on `main`. Experiments 1–17 continue that same line. Old feature branches are historical snapshots; merging their divergent ancestry again would duplicate earlier work. The branch names can remain for navigation, while `main` carries the reviewable commit sequence.

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
| 17 | `cbed365` | Opt-in field-scoped browser classification, harness, and tests; **fresh-run report pending** |

Commits preserve their original author and commit dates. The saved reports and JSON summaries for Experiments 12–16 are in `reports/`; their large raw run workspaces are local paths outside the Git repository, so the GitHub history alone does not contain every raw trace. Experiments 1–11 are documented in the README and their scripts/commits. Experiment 17 currently has a checked deterministic classification protocol but no completed fresh-run outcome.
