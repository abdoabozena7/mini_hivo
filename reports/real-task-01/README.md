# Independent end-to-end validation: Coin Courier

This is the review and handoff record for **real-task-01**, an independent evaluation of Mini Hivo's actual interactive CLI on a connected, multi-requirement application-building request. It is separate from Experiment 18's timer-repair experiment. The six attempts took place on October 20–21, 2026; this documentation cross-checks the preserved reports, structured traces, preparation snapshots, recorded tests, and subsequent publication review.

**Coin Courier was NOT completed. No application files were generated in Run-006. Independent application acceptance criteria were NOT TESTED. Run-006 was deliberately stopped before a normal root verdict. The Worker progress issue remains unresolved.**

## How to review this record

Start with [setup and the exact original prompt](EXPERIMENT-SETUP.md), then read the individual run histories. [Run-006](RUN-006.md) contains the detailed Worker investigation. [Fixes and validation](FIXES-AND-VALIDATION.md) separates published runtime fixes from withheld ingestion rewrites. The [evidence index](EVIDENCE-INDEX.md) gives source identities, selected trace extracts, local-only evidence locations, and test provenance. The [final assessment](FINAL-ASSESSMENT.md) assigns practical follow-up work.

These reports are published through the existing [PR #2](https://github.com/kareem232003/mini_hivo/pull/2). They document the experiment; they do not publish every experimental source revision. In particular, reproducing Run-006 requires the historical local snapshots, because two ingestion rewrites used in that attempt were subsequently withheld after broader review found regressions.

## Attempt comparison

| Attempt | Source/configuration added since preceding attempt | Last stage reached | Observed result |
|---|---|---|---|
| [001](RUN-001.md) | Original base, Python 3.11.9 | Import | `SyntaxError` in `hivo/reentry.py:1189`; no prompt or inference |
| [002](RUN-002.md) | Python compatibility expression correction | Host preflight | First canary exceeded the original 30-second deadline; no task submission |
| [003](RUN-003.md) | Per-canary deadline 180 seconds | Request clarification | Three canaries passed; false requirement conflicts blocked planning; stopped unanswered |
| [004](RUN-004.md) | Attempted scoped conflict rewrite | Project classification/reconnaissance | Empty new-application workspace classified as existing; `TASK_BRAIN / REPOSITORY_EMPTY` |
| [005](RUN-005.md) | Attempted explicit-greenfield rewrite | Specification request | Separate 120-second provider deadline; `TASK_BRAIN / ENVIRONMENT_ERROR` |
| [006](RUN-006.md) | Normal request deadline 600 seconds | Specification, adaptive planning, Mission Compiler, two Workers | Both Workers exhausted 28-step budgets without mutations; root later interrupted during recursive planning |

All attempts used fresh isolated workspaces and the same saved prompt, model `gemma4:e4b`, planning route, and experiment policies. Runs 001–002 never reached `You>` and therefore did not submit the task. Runs 003–006 submitted it once. There was no Run-007 and no manual implementation of the application.

## Published versus experimental changes

| Change | Publication status | Interpretation |
|---|---|---|
| Python 3.11-compatible conflict-ID construction | Published in PR #2 | Preserves canonical hash identity; actual mechanism tested |
| Host-preflight deadline 30 → 180 seconds | Published in PR #2 | Longer finite wait; retains all three canaries and failure gates |
| Normal Ollama request deadline 120 → 600 seconds | Published in PR #2 | Longer finite wait; preserves model/payload and timeout failure behavior |
| Requirement-conflict rewrite | **Withheld** | Narrow tests passed, but broader review missed genuine contradictions |
| Greenfield classification rewrite | **Withheld** | Narrow tests passed, but broader review misclassified explicit existing-project intent |
| Repeated context checking without Worker progress | **Unresolved** | No Worker policy, reasoning, or application repair published |

The final runtime PR revision has **57 recorded passing mechanism/regression tests** and **197 Python files compiled in memory**. Earlier continuation test totals concern different local source snapshots, including the withheld changes. They are not interchangeable test totals and do not establish application success.

## Reading historical evidence correctly

The original `FINAL-REPORT.md` is a checkpoint ending at Run-003. Its statements that later runs had not started and ingestion logic had not been changed were correct at that checkpoint. `CONTINUATION-REPORT.md` records the subsequently authorized Runs 004–006 and calls the ingestion edits corrections based on then-available tests. The later publication review found counterexamples and withheld both. This documentation preserves all three stages of knowledge rather than rewriting the earlier reports.

Observed events, test results, hypotheses, and missing evidence are labeled separately. Full raw transcripts, SQLite memory, source snapshots, and logs remain **LOCAL-ONLY EVIDENCE**. Small selected facts and trace projections are included here so the team can understand the chronology on GitHub without downloading private machine state. See [evidence access and limitations](EVIDENCE-INDEX.md).
