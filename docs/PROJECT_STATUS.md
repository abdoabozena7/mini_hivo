# Mini Hivo — architecture and feature status

Checkpoint: 2026-11-16. This page tracks capabilities, not individual defects. The experiment timeline is in [EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md); implementation details are in the [README](../README.md). The [consolidation report](BRANCH_CONSOLIDATION.md) records original branch ancestry, integration decisions, and fresh validation separately.

## What exists in the code

| Capability | Status | Main implementation |
|---|---|---|
| Local CLI, numbered project workspaces, pinned `gemma4:e4b` transport, bounded context, and persistent SQLite run/task memory | Implemented | `mini.py`, `hivo/projects.py`, `hivo/model_policy.py`, `hivo/http_client.py`, `hivo/context.py`, `hivo/memory.py` |
| Source requirement ledger, clarification, repository reconnaissance, Project Brain, and temporary Task Brain | Implemented | `hivo/requirements.py`, `hivo/project_understanding.py`, `hivo/reentry.py` |
| Impact Map, challenge, minimal change plan, explicit approval, and immutable execution contracts | Implemented | `hivo/impact_planning.py`, `hivo/execution_contracts.py`, `hivo/approval_bound_execution.py` |
| Recursive task decomposition, scoped Worker missions, dependency scheduling, mutation guards, and bounded recovery | Implemented | `mini.py`, `hivo/context_sufficiency.py`, `hivo/pre_mutation_impact.py`, `hivo/mutation_grounding.py`, `hivo/recovery.py` |
| Browser/unit verification routing, verified child receipts, fresh parent integration, verified-state promotion and re-entry | Implemented | `hivo/verification.py`, `hivo/verification_routing.py`, `hivo/atomic_child_receipt.py`, `hivo/integration_gate.py`, `hivo/promotion.py`, `hivo/reentry.py` |
| Experiment runners, deterministic regression tests, paired reports and saved result summaries | Reports and numeric results archived through Experiment 19; original histories integrated without rewriting | `scripts/`, `tests/`, `reports/` |

“Implemented” means a code path and focused tests exist. It does **not** claim reliable end-to-end completion for every project or that an experimental policy is the default.

## Current working point

Experiment 17's [completed report](../reports/experiment17/experiment17-report.md) retains the **opt-in** `field_scoped` browser classifier. It classified all measured Timer/game contracts correctly, and the two game tasks each reached Root verified in 3/3 fresh approved-contract runs. Timer reached Root verified in 0/3: correct classification and browser behavior did not close its later receipt/grounding failures.

Experiment 18's [report](../reports/experiment18/experiment18-report.md) shows that the opt-in no-tool re-anchor moved Python into source inspection, but not into a context decision or legal mutation. Experiment 19's [report](../reports/experiment19/experiment19-report.md) found 0/3 Python context decisions in both comparison arms; its closure guard remains experimental and is not promoted to a default.

The consolidation adds focused repairs for false source conflicts, provider/runtime context-schema drift, context-only false completion, negated browser requirements, nonzero replacement-count recovery, requirement-grounded creation impact targets, native tool-call protocol mismatches, and honest batch exit status. Source-authorized new outputs are distinguished from missing dependencies without claiming existing implementation evidence. The deterministic self-test uses independent-task fixtures.

The final deterministic suite ran 1729 tests successfully with four pre-existing legacy skips. Two fresh public-CLI Python clamp repairs on `92aee80` reached Root verified; each passed eight independent behavior cases and preserved the original test file. Sixteen other live attempts across earlier revisions and different cases failed or stopped, including greenfield and default `auto` requests. The [consolidation report](BRANCH_CONSOLIDATION.md) preserves every attempt and the actual scope of acceptance. This establishes a working existing-code path, **not** reliable completion for every task family, and does not retroactively change historical experiment percentages.

## Capabilities still needed for the intended complete architecture

| Milestone | Acceptance evidence needed |
|---|---|
| A chosen, integrated execution policy | Compare the opt-in experiment policies on fixed, representative tasks; record which combination becomes the normal CLI behavior and why. Today many improvements are flags and `current` remains the default. |
| End-to-end behavior across the declared task families | Fresh runs from approved contracts must reach legal mutation, child behavior verification, valid receipt, and fresh parent verification for browser games, Timer, Python unit behavior, and Node unit behavior. The five-task Experiment 12 did not reach executable verification for Timer or Python; Experiment 16 confirms their distinct stopping boundaries. |
| Full request-to-result validation | Exercise source request, clarification, repository evidence, impact plan, user approval, execution, verification, and durable promotion together on representative existing and new projects. Experiments 12–16 start from frozen approved contracts, so they do not measure the planning/approval portion. |
| Reproducible release checkpoint | Keep the selected policy, supported task families, acceptance fixtures, runbook, and measured limits together in the repo; rerun the meaningful regression and live acceptance set before calling the architecture complete. |

These are feature-level acceptance milestones. Individual failures found while meeting them should be tracked separately. The existing modules form the intended pipeline, but current evidence does not support calling the whole architecture complete and reliable yet.
