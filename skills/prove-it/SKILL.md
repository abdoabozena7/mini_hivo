---
name: prove-it
description: Plan, decompose, implement, and verify coding work through actual product use before claiming completion. Use for frontend/UI, backend/API, CLI, coding-agent pipelines, simulation, ML workflows, bug fixes, and autonomous or autopilot development whenever the user expects working behavior rather than code-only delivery. Maintain a dependency-aware TODO list; delegate independent bounded work to real subagents when available, otherwise execute serially. Require observable outcomes, current-source runtime evidence, meaningful negative controls, artifact inspection, integration validation, and honest blocked status. Do not use for purely conversational explanations or requests that explicitly exclude implementation and execution.
---

# Prove It

## Mission and boundaries

Deliver the user's observable result, not a collection of edits, green tests, or
worker reports. Use this loop:

**Understand -> plan -> exercise -> observe -> fix -> re-exercise -> inspect -> integrate -> verify.**

Treat the goal and its acceptance criteria as the authority. Treat tests as tools
for finding mistakes, not permission to declare success. Preserve useful unit
and regression tests; never replace real product acceptance with mocks.

A Markdown instruction cannot create missing tools, extend a host's execution
limits, guarantee arbitrary correctness, or force an uncooperative agent. Use
the bundled gate when possible; describe any missing enforcement honestly.
Follow system, organization, user, repository, safety and spending restrictions.
Never disable a sandbox, borrow protected experiment time, erase failed runs,
weaken thresholds, or reset a budget merely to complete a task.

## 1. Establish the actual goal and capabilities

Read the request, existing instructions and relevant implementation. Preserve
user changes. Identify the real entry point, start command, output, consumers,
and existing acceptance rules. Do not assume documentation proves live behavior.

Inspect available shell, browser, screenshot/image inspection, simulator, GPU,
network, credentials, and actual delegation tools. A listed executable is not
proof that it works. Never invent a tool call, running process, screenshot,
agent identity or permission. Reuse installed tools before adding dependencies.

Record allowed environments and side effects. Prefer local/test accounts and
synthetic test data. Do not buy, send, delete, publish, use real vehicles, or
start unrestricted training without the appropriate authorization. Large model
credits do not imply unlimited disk, GPU, wall time, or external-service access.

For a coding task, initialize a durable task before implementation. Read
[Harness guide](references/harness-guide.md) when scripts are available.
If only this Markdown file is available, follow the same process using a
persistent `TASK_PLAN.md`, `EVIDENCE.md`, actual tool outputs and native TODO
tools. Explicitly call this **instruction-only mode**, not a mechanical gate.
Treat linked files as optional expansions in that mode; do not claim to read
unavailable resources. Apply the self-contained rules below regardless.

## 2. Make a plan and TODO list before changing implementation

Read [Planning and delegation](references/planning-and-delegation.md) and [Hivo-inspired patterns](references/hivo-patterns.md).
Capture requirement provenance (`USER_STATED`, `USER_CONFIRMED`, `DERIVED`,
`REPOSITORY_EVIDENCE`) before planning. Challenge the plan for omitted user
outcomes, circular tests and unsafe scope expansion; preserve original intent.
Translate the requested outcome into requirements and independent expected
results. Include every requested user journey, not just the easiest subset.
For each requirement record an incorrect behavior that verification must catch.

Create a dependency-aware plan. Every task needs:
- Stable ID, concrete outcome, requirements covered and deliverable paths.
- Dependencies, owner, allowed write scope and relevant runtime tools.
- Observable acceptance criterion, verification checks and expected evidence.
- Execution choice: coordinator serially, or an actual delegated worker.

Use native planning/TODO tools when available, but keep durable on-disk state
for resumption. Small changes may use a short plan; do not invent bureaucracy.
Always include integration/final-user-journey validation. A large task may use
bounded milestone contracts plus a parent acceptance plan; no child milestone
can close the parent's original goal.

Choose **serial**, **parallel**, or **hybrid** deliberately. Parallelize only
ready, sufficiently independent work with nonconflicting write/resource
ownership. Fix shared API/schema contracts before parallel FE/BE work.
Serialize dependent changes and single-owner simulators, ports and databases.
Never mandate one worker per bullet. Never pretend role-play is a subagent.
If delegation is unavailable, execute the same acceptance plan serially.

Before each worker's first mutation, check context sufficiency: authoritative
interfaces, callers/consumers, legal scope and a runnable acceptance route.
When a required fact is missing, request targeted evidence; never guess from
a broad repository search or inflate the prompt with an entire transcript.

Use explicit task states:
`TODO -> IN_PROGRESS -> IMPLEMENTED -> VERIFIED`; use `BLOCKED` when necessary.
**IMPLEMENTED is not done.** Record actual agent invocation IDs and handoffs.
Do not check off a task solely because its worker says "done". The coordinator
owns the shared ledger, reviews artifacts, resolves conflicts and verifies the
integrated product. Require current evidence before the final TODO is closed.

## 3. Define acceptance before implementation

Read [Acceptance and test quality](references/acceptance-and-test-quality.md).
Specify inputs, preconditions, actual action, expected externally observable
outcome, failure conditions and evidence. Preserve original acceptance rules;
do not tune expected values to whatever the new implementation produces.

Separate:
- Live execution of the target product.
- Offline unit/integration checks.
- Saved replay or prerecorded media.
- Synthetic fixtures/mocks.

All four can be useful, but only the evidence class appropriate to a claim can
support it. A fixture browser success does not prove a live backend. A short
CARLA smoke run does not prove a full route. A generated project's build does
not prove that the generated feature works.

Build a bounded but explicit coverage inventory: required controls, states,
viewports, modes, errors and recovery paths. Do not claim every imaginable state
was tested. Any requested behavior left untested remains visible and unverified.
Do not click dangerous controls blindly; exercise safe equivalents only with
accurate scope labels, or report the real action as untested.

For high-value checks, demonstrate that an appropriate safe negative control
or known broken implementation fails. Do not inject faults in production,
physical hardware or protected holdouts. Record a specific exception when a
negative control is unsafe or disproportionate. A generic "not needed" is not
an adequate review rationale.

Seal the contract, task DAG and oracles before implementation/execution. Keep
source paths complete: implementation, configuration, dependency locks,
verification code and relevant model identifiers. Keep raw recordings, secrets,
weights and generated evidence outside the source fingerprint. Do not edit a
sealed contract to make a failure disappear; preserve and explain revisions.

## 4. Execute the real product early and throughout development

For an existing product, reproduce the relevant behavior before speculative
editing. For a new product, build the smallest runnable slice, then exercise it
before expanding. Select the relevant adapter:

- **Web/UI:** [Web validation](references/web-validation.md). Start the real
  application, use its browser UI, inspect rendered states and console/network
  outcomes. Prefer headed operation where supported. Capture and actually
  inspect screenshots; a screenshot file alone proves no design quality.
- **Simulation/ML:** [Simulation validation](references/simulation-validation.md).
  Use the actual engine, sensors, control loop and permitted scenarios. Check
  ticks, physical outcomes, full required routes and genuine recorded evidence.
  Distinguish rendering, inference, training and replay.
- **CLI / Mini Hivo / agent pipelines:** [CLI and agent validation](references/cli-agent-validation.md).
  Send an actual representative prompt through the real entry point, inspect
  planning/worker/tool traces, then run and evaluate the generated result.
- **API/library:** Invoke the real public boundary. Observe actual responses,
  state changes, persistence and invalid-input behavior using independent
  expected results. A browser is not mandatory for a nonvisual library task.

Use small reproducible experiments while diagnosing, then run the complete
required acceptance scope on the final source. Keep failures and raw outputs.
Apply the smallest justified fix, run meaningful regressions and repeat the
same failed user action. Compare observations, not confidence or test counts.
Do not keep changing code without a runtime feedback point.

Give concise progress grounded in actual actions: what was tried, what was
observed, the relevant artifact and the next experiment. Keep TODO state current
after each meaningful milestone. Do not narrate invented background activity.

## 5. Make delegation accountable

Provide every worker the outcome, dependency inputs, interface contract,
exclusive write scope, constraints, acceptance oracle, permitted tools and
required evidence. Use [Worker brief](assets/templates/worker-brief.md).
Pass the relevant skill rules explicitly; do not assume skill/context inheritance.

Require raw commands/tool IDs, source identity, artifact paths, failed attempts,
remaining gaps and a handoff. A worker may return IMPLEMENTED without runtime
proof, but that task cannot be called VERIFIED. Do not allow multiple workers
to rewrite the shared task/evidence ledger. Do not create branches or worktrees
when the project/user requires one checkout.

Use a fresh-context reviewer when available and worthwhile. Have the reviewer
try the behavior independently, not simply approve the implementer's narrative.
Disclose shared-model/shared-context limitations. When no reviewer tool exists,
perform a separate adversarial verification pass; do not pretend it is an
independent agent.

## 6. Inspect evidence and run the completion gate

Review real screenshots, videos, logs and measurements. Check that they belong
to the final source, current environment, intended scenario and claimed mode.
A static frame is not proof of motion; a clicked selector is not proof of the
requested effect; GPU activity is not proof of learning or correct decisions.

With the bundle, use `scripts/proof.py` to run specified commands, collect
fresh receipts and hashes, record reviews and verify every plan item. Use the
same installed Python interpreter consistently. Never hand-author execution
receipts or edit the collector to pass. Read the harness guide for exact commands.

Before the final response, require:
1. Every requested requirement linked to meaningful current execution evidence.
2. Every required TODO verified, with real delegation provenance where used.
3. Full integration journey executed after relevant final changes.
4. Required visual/behavioral inspection recorded with exact artifact references.
5. No hidden failed, skipped, blocked, mocked or stale acceptance item.

Any relevant source/configuration/test change invalidates affected evidence.
The bundled collector conservatively invalidates all scoped evidence on a source
change. Rerun and re-review; do not reuse stale success from an earlier revision.

Call `proof.py verify --task TASK_DIRECTORY --write-report` when available.
An `EVIDENCE_GATE_PASSED` result means the declared evidence contract passed;
it is not mathematical proof, broad safety certification, or truth of every
assertion authored by the same agent. Independently judge oracle adequacy.

## 7. Continue intelligently; stop truthfully

Continue while there is a concrete, authorized next experiment or fix. On a
failure, classify PRODUCT_DEFECT / TEST_DEFECT / TOOL_ENVIRONMENT /
CONTRACT_GAP / CONTEXT_GAP / RESOURCE_LIMIT / STAGNATION; record a
falsifiable hypothesis and try a justified change.
Do not repeat identical failures without new information or spin indefinitely.
If an external restriction remains, record the exact denied operation/error,
what was tried, the required action and `BLOCKED_UNVERIFIED`. Do not redefine
the task as complete. Never cancel user stop requests or evade host limits.

The optional stop hook requests continuation for incomplete active tasks. It
self-limits when forced continuation makes no evidence progress. That may end
the agent turn, **not** grant completion. Require `gate.json` plus the final
behavioral review, not the client's "Task completed" banner.

At resumption, read the contract, TODO, last failure and source identity first.
Keep validated work, reopen stale items and continue the next ready task.
Retain durable user constraints separately from state-bound source facts.
Never promote an old success to current truth after relevant source drift.

## Final response

Use [Final report](assets/templates/final-report.md). State one of:
**VERIFIED_WITHIN_SCOPE**, **PARTIAL**, **FAILED**, **BLOCKED_UNVERIFIED**.
Describe actual behavior, exact evidence, TODO completion, integration result,
failed attempts, untested cases and reproduction commands. Label historical,
fixture, replay and live evidence explicitly. Never say "works" when only the
code was read, a worker claimed success, or a mock returned the desired result.

Read [Security and limits](references/security-and-limitations.md) before using
hooks or applying this workflow to sensitive, costly or shared environments.
