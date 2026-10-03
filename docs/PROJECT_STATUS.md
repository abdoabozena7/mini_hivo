# Mini Hivo — architecture and feature status

Checkpoint: 2026-10-03. This page tracks capabilities, not individual defects. The experiment timeline is in [EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md); implementation details are in the [README](../README.md).

## What exists in the code

| Capability | Status | Main implementation |
|---|---|---|
| Local CLI, numbered project workspaces, pinned `gemma4:e4b` transport, bounded context, and persistent SQLite run/task memory | Implemented | `mini.py`, `hivo/projects.py`, `hivo/model_policy.py`, `hivo/http_client.py`, `hivo/context.py`, `hivo/memory.py` |
| Source requirement ledger, clarification, repository reconnaissance, Project Brain, and temporary Task Brain | Implemented | `hivo/requirements.py`, `hivo/project_understanding.py`, `hivo/reentry.py` |
| Impact Map, challenge, minimal change plan, explicit approval, and immutable execution contracts | Implemented | `hivo/impact_planning.py`, `hivo/execution_contracts.py`, `hivo/approval_bound_execution.py` |
| Recursive task decomposition, scoped Worker missions, dependency scheduling, mutation guards, and bounded recovery | Implemented | `mini.py`, `hivo/context_sufficiency.py`, `hivo/pre_mutation_impact.py`, `hivo/mutation_grounding.py`, `hivo/recovery.py` |
| Browser/unit verification routing, verified child receipts, fresh parent integration, verified-state promotion and re-entry | Implemented | `hivo/verification.py`, `hivo/verification_routing.py`, `hivo/atomic_child_receipt.py`, `hivo/integration_gate.py`, `hivo/promotion.py`, `hivo/reentry.py` |
| Experiment runners, deterministic regression tests, paired reports and saved result summaries | Completed report metrics archived through Experiment 16; Experiment 17 in progress | `scripts/`, `tests/`, `reports/` |

“Implemented” means a code path and focused tests exist. It does **not** claim reliable end-to-end completion for every project or that an experimental policy is the default.

## Current working point

Experiment 16 isolated separate first stopping points in the frozen Timer and Python tasks: Timer reached a legal edit but a browser verification profile could be chosen from an unrelated contract hash; Python did not pass its pre-mutation context/impact boundary in three attempts. See [the Experiment 16 report](../reports/experiment16/experiment16-report.md).

Experiment 17 adds an **opt-in** `field_scoped` browser profile policy. It classifies from goal, requirements, approved paths and verification target instead of arbitrary contract metadata. The existing `current` policy remains the default. [Frozen-contract checks](../reports/experiment17/classification-protocol.md) classify Timer correctly in 3/3 instances and both games correctly in 6/6; 27 identity-field perturbations preserve the new classification. Focused deterministic tests pass. Its nine fresh Worker runs, result report, and decision on promotion are still pending. This addresses the Timer classification boundary only; it does not claim to resolve the separate Python path.

## Capabilities still needed for the intended complete architecture

| Milestone | Acceptance evidence needed |
|---|---|
| A chosen, integrated execution policy | Compare the opt-in experiment policies on fixed, representative tasks; record which combination becomes the normal CLI behavior and why. Today many improvements are flags and `current` remains the default. |
| End-to-end behavior across the declared task families | Fresh runs from approved contracts must reach legal mutation, child behavior verification, valid receipt, and fresh parent verification for browser games, Timer, Python unit behavior, and Node unit behavior. The five-task Experiment 12 did not reach executable verification for Timer or Python; Experiment 16 confirms their distinct stopping boundaries. |
| Full request-to-result validation | Exercise source request, clarification, repository evidence, impact plan, user approval, execution, verification, and durable promotion together on representative existing and new projects. Experiments 12–16 start from frozen approved contracts, so they do not measure the planning/approval portion. |
| Reproducible release checkpoint | Keep the selected policy, supported task families, acceptance fixtures, runbook, and measured limits together in the repo; rerun the meaningful regression and live acceptance set before calling the architecture complete. |

These are feature-level acceptance milestones. Individual failures found while meeting them should be tracked separately. The existing modules form the intended pipeline, but current evidence does not support calling the whole architecture complete and reliable yet.
