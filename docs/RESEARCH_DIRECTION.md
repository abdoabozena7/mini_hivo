# One selected paper: evidence-licensed decomposition

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE):** Mini Hivo is **v2 only**. This research note documents the retired v1 single-local-model baseline (`mini.py`) and is preserved strictly for history. For active v2 architecture and strategy, see [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) and [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md).

**Decision date:** 2026-11-17.
**Status:** one research direction selected; proposed mechanism and evaluation,
not an implemented research result or submission-ready paper.

## The contribution to pursue

**Working title: _Before You Split: Evidence-Licensed Decomposition for Small
Coding Agents_.**

Study one decision: **when may a coding-agent controller interpret non-progress
as a reason to split work or abandon it on capability grounds?**

The proposed contribution is a runtime decision gate. Before a capability-based
split or termination, it requires an attributable interaction failure to receive
one bounded, executed correction **within unchanged authority**, followed by a
fresh observation of whether execution or verification actually advanced.

This is not a paper about the whole Mini Hivo architecture, a new generic
multi-agent framework, a failure taxonomy alone, or a more attractive terminal.
Those are implementation context, not separate candidate contributions.

### Research question

> At fixed small-model inference, tool and elapsed-time budgets, can an
> evidence-licensed granularity controller reduce spurious splits and
> capability-based stops, and improve independently verified coding success,
> without weakening permission/verification guards or delaying genuinely useful
> decomposition?

All diagnosis and recovery overhead counts against the same budget.

## Why this project provides a useful starting case

The [actual manual-run analysis](MANUAL_RUN_ANALYSIS.md) establishes a specific
failure chain:

1. A Worker created the HTML foundation.
2. Range edits omitted required arguments.
3. A generic repeated-mutation counter labeled the node `TASK_TOO_BROAD`.
4. Rollback removed the unverified draft.
5. Recovery and later children encountered stale assumptions or missing context.
6. A valid module-syntax route was additionally rejected by a CommonJS-mode
   verifier.
7. More decomposition consumed 64 task nodes and 389 model calls without a
   working final product.

The case distinguishes a **real tool-contract failure**, a **verifier execution-
mode defect**, and **downstream dependency/context failure**. They are three
manifestations relevant to the same decision policy, not three proposed papers.

The runtime evidence justifies investigating that policy. It does **not** show
how common the failure is, establish a causal treatment effect across tasks, or
prove that a different policy would have completed the original game.

## What is already known

A bounded primary-literature review was conducted, and the canonical title,
date and abstract pages below were checked directly. The research assessment
also read the principal method/evaluation sections. Publication status is not
inferred from a search snippet.

| Prior work | Established overlap | Consequence for our claim |
|---|---|---|
| [ADaPT: As-Needed Decomposition and Planning with Language Models](https://aclanthology.org/2024.findings-naacl.264/), Findings of NAACL 2024 | Recursive as-needed decomposition when an executor cannot complete a task | Failure-triggered adaptive decomposition is not new |
| [Which Agent Causes Task Failures and When?](https://proceedings.mlr.press/v267/zhang25cq.html), ICML 2025 | Formal failure attribution to an agent and decisive step; Who&When dataset | Automated attribution and counterfactual decisive-error reasoning are not new |
| [Why Do Multi-Agent LLM Systems Fail?](https://arxiv.org/abs/2503.13657), 2025, MAST | Systematic failure taxonomy including design, coordination and verification issues | "The system, not just the model, causes failures" is not a new finding |
| [Where LLM Agents Fail and How They can Learn From Failures](https://arxiv.org/abs/2509.25370), AgentDebug, September 2025 preprint | Typed diagnosis, earliest critical errors, targeted feedback and repeated recovery; compute-matched comparisons | Attribution followed by recovery, including smaller models, is not a sufficient novelty claim |
| [AgentRx: Diagnosing AI Agent Failures from Execution Trajectories](https://arxiv.org/abs/2602.02475), February/August 2026 | Schema/policy-derived constraints and auditable step-level evidence for diagnosis | Schema- and policy-grounded diagnosis itself is already covered; the arXiv page reports EMNLP Findings 2026 acceptance, not independently checked against the proceedings here |
| [From Failed Trajectories to Reliable LLM Agents: Diagnosing and Repairing Harness Flaws](https://arxiv.org/abs/2606.06324), HarnessFix, June/July 2026 preprint | Trace-grounded attribution to harness artifacts and scoped harness repairs | Harness-aware diagnosis and verified repair are not new |
| [AgentDebugX: An Open-Source Toolkit for Failure Observability, Attribution, and Recovery in LLM Agents](https://arxiv.org/abs/2607.18754), July 2026 preprint | Detect/attribute/recover/rerun loop, rule-based fault detection and gated recovery | "Add observability, classify malformed calls and retry safely" is not enough |
| [Meta-Agent: From Task Descriptions to Verified Multi-Agent Systems](https://arxiv.org/abs/2605.25233), May 2026 preprint | Error attribution routes to localized retry, upstream re-execution and re-decomposition | Attribution-routed decomposition is also not a first-ever claim |

These are a related-work boundary, not a menu of directions. Published success
numbers from different models, task suites and budgets must not be presented
as directly comparable baselines for this project.

### The narrow gap worth testing

The plausible contribution is the **licensing rule for a capability/granularity
decision**:

```text
observed refusal / failed mutation
  -> evidence-grounded cause or explicit unknown
  -> one admissible correction actually executed
  -> fresh progress evidence
  -> only then permit the capability-based split/stop decision
```

In the bounded literature search, that exact online, same-authority
correction-before-granularity gate was not located. This is **plausible
novelty, not established novelty**. A citation-graph sweep and a fresh review
before submission remain required, especially given the close 2026 work.

## Safety is not conditional on completing a retry

The proposed gate applies to **capability-based** decisions. It must not delay:

- explicit user cancellation;
- a host/provider failure, exhausted budget or deadline;
- a legitimate permission denial or safety prohibition;
- a required approval/clarification that has not been supplied.

Those boundaries stop or block immediately. A legitimate refusal must never
be treated as a bug to route around. No retry may widen accepted scope, invent
approval, manufacture context evidence, disable a verifier, or edit the product
merely to satisfy a known wrong verifier configuration.

For example, `echo "verification successful"` stays invalid proof. A missing
`start_line` is not filled with a guessed number. A module is rechecked in
module mode only when its original accepted execution context establishes that
mode, not by trying permissive configurations until one passes.

## The mechanism to implement

### 1. Evidence-qualified failure episodes

Group the actual failed actions into bounded episodes. Classify from controller-
observed records: argument validation codes, guard reason codes, target hashes
and existence, declared runtime mode, and actual verifier receipts.

An episode should retain:

- the earliest observed failure and its source/tool/target;
- the original source obligation and accepted-authority identity;
- the observed class, supporting records and any unresolved alternatives;
- whether the next action is permitted, blocked, or needs explicit human input;
- the bounded correction attempted and its actual execution receipt;
- fresh post-correction state and verification, not a model's success narrative;
- the eventual decision: continue, split, block, failed budget, or verified done.

The classifier can abstain. A missing explanation is not proof of a model
capability limit.

### 2. A constrained correction, not an unrestricted second agent

Use the existing permission and mutation gates. Correct the interaction or
freshness issue in the same scope: reread current line ranges, use the actual
required schema, refresh a stale target observation, or correct a verifier
mode already determined by the source/runtime contract.

One correction budget is charged to the task. Repeated corrections cannot
reset the global deadline, tool count, depth or token limit. No raw Worker
conversation is promoted into verified project knowledge.

### 3. License the decision, do not claim to measure intelligence

Fresh evidence may show useful progress, an unresolved implementation problem,
a genuine block, or no progress. The gate determines whether a split/stop is
now justified under the controller policy. Even after an unsuccessful correction,
"the model is incapable" is usually stronger than the evidence supports.

The output should say what was observed and what budget remains. A verified
artifact is still required for final success.

## Experimental design

### Phase 0: establish that the target failure occurs naturally

Before building a large benchmark, annotate an untouched sample of natural
small-model coding runs. Measure how often capability-based splits/stops are
preceded by attributable interaction or verifier failures.

Keep the denominator explicit. Count independent tasks and distinct episodes,
not every ancestor carrying an inherited failure summary. The current manual
run's 62 context-failure ledger entries are not 62 independent examples.

If the failure is rare, a large system paper around this gate may not be
worth pursuing. One vivid trace is not enough to establish prevalence.

### Controlled coding tasks with ground truth

Include clean executable tasks and matched fault variants:

- malformed/schema-drift tool interactions;
- stale target evidence;
- verifier/runtime mismatch;
- missing prerequisite or orchestration mismatch.

Also include clean tasks that really benefit from decomposition and
**legitimate-denial tasks** whose correct outcome is blocked, not code execution.

Injected causes provide labels by construction. Keep natural and injected
results separate. Construct cases from successful clean controls where
possible, retain the exact fault schedule, and test that the injected change
alone produces the claimed boundary. An annotation is not automatically
causal ground truth for a natural trace.

Reserve development cases for implementation. Freeze the held-out tasks,
independent oracles and fault schedules before the final comparison.
The historical manual prompt is already a development case and must not be
presented as untouched test-set evidence.

### Comparison arms for this one hypothesis

The decisive comparison is:

| Arm | Purpose |
|---|---|
| Failure-triggered decomposition with the existing bounded counters | Operational baseline |
| The same controller plus equally informative diagnostic text, without a decision gate | Separate better feedback from the proposed licensing mechanism |
| The proposed evidence-licensed controller | Treatment |
| Treatment with cause evidence shuffled or replaced by an equal-budget generic retry | Negative control / ablation |

An oracle-cause version can provide an upper bound, but it is not the deployed
method. A plain loop is useful additional context if affordable. These are
experimental controls for one paper, not separate research directions.

Implement a faithful coding-task adaptation when a published baseline was
developed for a different environment, and identify it as an adaptation rather
than claiming to have reproduced the original paper's headline result.

### Fairness and scope

- Hold model weights, quantization, sampling settings, context length, tool
  schemas, authority rules and final verifier fixed within each comparison.
- Charge diagnosis, correction and any judge calls to the same per-task token,
  tool and wall-clock caps. More retries are not a free treatment.
- Pair task/fault schedules and seeds across arms; counterbalance execution
  order and retain loaded/cold-model and resource conditions.
- Start the implementation pilot on the installed local Gemma model. A
  submission-strength generalization claim needs replication on other feasible
  local models; that evaluation has not been run or authorized as an automatic
  new model installation here.
- Select sample size and a non-inferiority margin after a development-only
  variance/power assessment, then preregister them. Do not select the final
  denominator after seeing which tasks improved.

### Primary measurements

1. **Independent verified task success at equal budget.** Use hidden tests,
   actual browser behavior, byte comparisons or build-and-diff checks outside
   the agent. Include failed, blocked, timed-out and interrupted trials in the
   declared denominator.
2. **Spurious capability/granularity decisions.** Measure decisions under
   labeled non-coding faults, supported by same-authority corrected controls.
   Pair this with missed or delayed needed-decomposition rate on clean hard
   tasks; merely suppressing every split cannot win.
3. **Attribution quality.** Report confusion, unknown/abstention rate and
   per-cause results against controlled labels. Human-check a bounded natural
   sample independently.
4. **Integrity and cost.** Audit unauthorized committed mutations and false
   verification passes; any such violation invalidates that success. Report
   total tokens, tool calls, time and diagnosis/correction overhead.

Use paired confidence intervals with task-family-aware resampling. Multiple
seeds, child nodes and repeated attempts from the same task must not be
treated as independent samples. Report all attempts and null/negative
results. A config hash is useful provenance but does not, alone, prove
permission integrity; inspect actual filesystem/tool effects too.

## What would refute the proposed contribution

The direction should not be sold as successful if:

- natural traces rarely contain the target failure;
- diagnostic text without the gate performs equally well;
- shuffled cause labels provide the same benefit;
- improvements disappear under truly matched budgets;
- the gate prevents useful decomposition or consumes the recovery budget on
  clean difficult tasks;
- any improvement relies on weakened authority, an easier oracle or false PASS;
- the relevant existing work already implements the same mechanism.

A negative result should change the research claim, not lead to removing
the inconvenient tasks or publishing only a winning retry.

## Current readiness

| Item | Actual state |
|---|---|
| A real motivating failure with tool/controller provenance | Available; detailed in the linked analysis |
| A reproduced verifier-mode false rejection | Available; repaired with positive and negative syntax checks |
| Existing durable execution, authority and verification mechanisms | Available as implementation substrate |
| General evidence-licensed granularity policy | **Proposed, not implemented or evaluated as a research method** |
| Natural-failure prevalence study | Not run |
| Frozen multi-task, multi-seed, equal-budget comparison | Not run |
| Cross-model replication | Not run |
| Exhaustive novelty review / submission outcome | Not established |

The current unit/regression test count measures product regression coverage.
It is **not** the sample size of a research experiment.

The next substantive research milestone is a small implemented gate plus the
Phase-0 prevalence/controlled pilot, not drafting an abstract that claims the
method already outperforms prior work. This is the single contribution selected
for this project; publishability depends on the resulting evidence.
