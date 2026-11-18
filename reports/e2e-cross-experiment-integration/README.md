# E2E cross-experiment integration findings: Experiments 1–18

Research checkpoint: October 21, 2026, Africa/Cairo. This is an independent integration contribution within the Mini Hivo Experiments 1–18 program. The E2E validation workstream evaluates the mechanisms together on a real request; it does not own the principal Experiment 18 fixes.

## Contribution beyond PR #2

[PR #2](https://github.com/kareem232003/mini_hivo/pull/2) already documents Coin Courier execution and runtime fixes. This package contributes a different analysis:

- **F1 — Effective coverage:** an experiment-by-experiment distinction between implementation, selected policy, activated route and observed execution.
- **F2 — Cross-experiment reproduction:** Run-006's non-progress is connected to Experiment 3, with a newly identified greenfield activation limitation for the existing progress/grounding wrappers.
- **F3 — Recovered corroboration:** SQLite event 30 identifies the generic invalid context decision already reported in PR #2 as three unsupported evidence-kind errors, directly corroborating Experiment 18A's schema/validator discrepancy.
- **F4 — Bounded hypothesis:** the source's prefix-truncated context re-anchoring creates a specific feedback-retention question; its causal role remains unproven.
- **F5 — Testable integration obligations:** route-aware owner deliverables and a matched Before/After protocol address these findings without treating historical Run-006 as an automatically controlled reference.

## Review path

| Document | Additional research value |
|---|---|
| [Traceability](CROSS-EXPERIMENT-TRACEABILITY.md) | Classifies every experiment's effective coverage and the evidence still required. |
| [New findings](NEW-INTEGRATION-FINDINGS.md) | Establishes F2–F4 from code, tests and recovered runtime evidence. |
| [Dependencies](INTEGRATION-DEPENDENCIES.md) | Converts findings into mechanism-owner and integration-owner obligations. |
| [Controlled validation](CONTROLLED-VALIDATION-PROTOCOL.md) | Defines the treatment, controls and observations needed for a future integration claim. |
| [Evidence and novelty map](EVIDENCE-AND-NOVELTY-MAP.md) | Identifies original sources, local-only evidence, publication boundaries and overlap with PR #2. |

This branch starts independently from team `main`, `f842fb8fb6e63e3064891d26ee0b24981e55c847`. It contains documentation only. It neither includes PR #2's commits/files nor requires PR #2's reports to exist on `main`: references to those reports use their published immutable revision.

The execution outcome remains the one already established in [PR #2's assessment](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/FINAL-ASSESSMENT.md): no completed Coin Courier application or independent application acceptance. This research does not repeat the six-run chronology, claim new live trials, implement fixes, or promote optional policies.
