# Mini Hivo

Mini Hivo is a local coding-agent orchestrator pinned to one model:
`gemma4:e4b`. Every model-backed role uses that exact model. Cross-model
routing and fallback are intentionally disabled so experiment results remain
attributable.

## Run

```powershell
.\.venv\Scripts\python.exe mini.py
```

At the workspace prompt, pressing Enter creates the next numbered project under
`list/` (`project-1`, `project-2`, ...). Supplying an existing path uses that
path directly. Legacy files that previously lived directly under `list/` are
migrated once into `list/project-1`.

## Architecture

- `mini.py`: CLI, one adaptive task-tree controller, the reusable leaf engine, tools, transactions, and runtime wiring.
- `hivo/model_policy.py`: immutable Gemma-only model and context policy.
- `hivo/projects.py`: legacy migration and atomic `project-N` allocation.
- `hivo/context.py`: bounded provider context without mutating source history.
- `hivo/http_client.py`: dependency-free local Ollama transport using Python's standard library.
- `hivo/memory.py`: per-project SQLite memory, verified-note retrieval, and a resumable run/task ledger.
- `hivo/playbooks.py`: deterministic project classification and a legacy stage projection; adaptive execution does not call it.
- `hivo/project_understanding.py`: deterministic project-mode classification, bounded read-only repository evidence, repository conflicts, and temporary Task Brain validation/projection.
- `hivo/impact_planning.py`: bounded Impact Map and challenge schemas, evidence/coverage gates, minimal-effective plan reconciliation, immutable plan IDs, and approved-scope projection.
- `hivo/execution_contracts.py`: immutable approved-plan snapshots, deterministic zero-model-call execution contracts, DAG validation, bounded projections, mission checks, and contract-local scope rules.
- `hivo/evidence.py`: latest-evidence semantics; resolved failures do not poison a run.
- `hivo/verification.py`: contract-aware browser pass/fail rules.
- `hivo/browser_checks.py`: deterministic profile-specific interactions for timers and other web apps.
- `tests/`: deterministic regression tests that do not require a live model.

## Browser-game verification contract

Generated browser games must expose `window.AGENT_GAME` with real adapters
to the application logic:

- `getState()`
- `start()`
- `restart()`
- `move(direction)`
- `forceCollision()`, `forceCollect()`, and `forceWin()` when those mechanics
  are part of the requested game

The browser verifier independently checks the document title, canvas, rendered
content, keyboard movement, requested mechanics, score persistence, and mobile
touch controls. A page that merely renders source code or placeholder text is a
failure even when its console is clean.

## Safety boundaries

`write_file` creates new files and may fully revise only a matching, unverified
model-authored artifact after an interrupted run. User-owned and verified files
require focused `edit_file` operations. The Repairer cannot call `write_file`, and visual/model
environment failures never trigger application-code edits. A failed task rolls
back all transaction-captured file changes. Range-based edits are syntax-checked
before they reach the workspace, so a malformed JavaScript, Python, or JSON patch
cannot overwrite the last valid version. Model-artifact ownership is stored with
a content fingerprint, so a user-edited file cannot be mistaken for the model's
unchanged resumable draft.

## Durable memory and weak-model execution

Each project keeps private orchestrator state in `.hivo/memory.sqlite3`. Tool
events and run/task status are written to disk, while prompts receive at most a
small relevance-ranked excerpt. Only notes created after deterministic evidence
passes are retrieved as successful facts. Interrupted tasks remain explicitly
labeled as unfinished and must be re-inspected after restart.

V22 Stage 5C adds one deterministic verified-state promotion boundary after a
`PARENT_VERIFIED` result. A valid, fresh `ParentVerificationReceipt` produces a
bounded `PromotionCandidate`; only structured durable or state-bound facts and
hashed evidence references may be committed to the project-local Project Brain.
The SQLite commit records candidate/promotion hashes, deduplication and
supersession, while state-bound records can be marked stale without automatic
re-verification. Promotion and Task Brain completion compaction use zero model
calls, and raw Worker/model transcripts never enter Project Brain.

V23 Stage 6A adds an explicit, read-only verified-state re-entry boundary for
new tasks in an existing project. It validates project identity, reads the
verified Project Brain, observes only bounded current repository evidence, and
deterministically reconciles durable authority, state-bound freshness,
supersession, relevance, and conflicts. Durable authority remains current
across unrelated implementation changes; a state-bound fact becomes stale
when its bound dependency or subject fingerprint changes. Stale facts remain
history and warnings, are never silently promoted to current truth, and are
never automatically re-verified. New user authority has precedence and an
incompatible request is surfaced as an explicit conflict.

The reconciliation is hashed as a bounded `ReentryContext`. Each new task
receives a fresh bounded Task Brain containing only relevant current state,
bounded direct repository observations, authority, stale/superseded warnings,
and continuation provenance. The previous Task Brain is not hydrated, Project
Brain is read-only, and Stage 6A stops before planning, Worker execution, or
any later-stage mechanism. Re-entry, freshness, relevance, and bootstrap use
zero model calls.

Recursive mode completes Stage 1 request ingestion, classifies the workspace as
`NEW_PROJECT` or `EXISTING_PROJECT`, and performs targeted repository
reconnaissance only for existing-project tasks. It then prepares the bounded
specification, Project Brain, and one temporary Task Brain before asking the
pinned model whether each node fits one focused Builder execution. A split
creates 2–4 small sequential child contracts; a child may become a parent and
split again up to `MAX_DEPTH = 6` and `MAX_TOTAL_TASKS = 64`. A leaf is never
secretly scheduled into deterministic stages. Direct baseline mode shares only
project-mode bookkeeping and sends the root through the same `execute_leaf`
engine without targeted Stage 2 context or adaptive decomposition.

In recursive mode, the short request is also expanded into a bounded project
specification before the task tree is planned. Mini Hivo keeps a stable Project
Brain Core for the root contract and a separate verified project-state view for
reconnaissance facts and verified child manifests. Root planning receives the
expanded Brain; child planning and implementation receive deterministic
task-relevant projections. Before each recursive implementation leaf, the
pinned model performs one bounded Mission Compiler call for that node. The
result is a compact Worker mission containing the target, implementation plan,
reusable interfaces, relevant invariants, and deterministic verification
requirements. The Worker still runs in a fresh context, and parent integration
continues to consume compact child manifests rather than raw conversations.

The v16 requirement boundary runs before that expansion. It creates a
bounded immutable Source Requirement Ledger with stable `REQ-*` IDs, source
segments, and `USER_STATED` provenance. Clarification decisions are separate
`USER_CONFIRMED` records; optional defaults are `DERIVED`; repository and tool
facts remain `VERIFIED`. A narrow same-model Clarifier asks at most three
decision-critical questions for the request, never inspects the repository,
and never writes code. Arrow-key/Enter selection, an `Other...` free-text path,
and a non-interactive `CLARIFICATION_REQUIRED` terminal state are supported.
After expansion, deterministic `MAPPED`/`UNMAPPED` coverage accounting keeps
source requirements visible even when the weak Specifier omits one. The full
source ledger is retained in the Project Brain, while Worker contexts receive
only relevant projections.

For `EXISTING_PROJECT`, Stage 2 inventories metadata, searches task terms and
named symbols, and only then reads a bounded set of ranked candidates. Direct
evidence records use stable `REPO-*` IDs, paths, symbols, line locations, file
hashes, bounded support, and `DIRECT_OBSERVATION`; unsupported model guesses
cannot enter Verified Project State. A repository-only preserve/remove conflict
or missing task-named interface may open a second evidence-linked clarification
round through the existing arrow-key UI. Non-interactive blocking questions end
as `CLARIFICATION_REQUIRED`, not an implementation or root failure. Empty
greenfield workspaces skip this reconnaissance entirely.

The temporary Task Brain stores the current task goal, Source Requirement IDs,
confirmed decisions, relevant Project Brain projection, verified repository
evidence/owners/interfaces/tests, preservation constraints, derived task
assumptions, acceptance conditions, and non-goals. Every entry is labeled
`USER_STATED`, `USER_CONFIRMED`, `PROJECT_BRAIN`, `REPOSITORY_EVIDENCE`, or
`DERIVED_TASK_ASSUMPTION`. Its evidence, reference counts, open questions, and
serialized size are deterministically bounded and validated before task-fit or
decomposition. Run evidence retains it for audit, but it is never promoted into
Project Brain; Workers receive only a node-relevant slice through the existing
Mission Compiler.

For an `EXISTING_PROJECT` recursive run, Stage 3 now executes immediately after
that Task Brain and before task-fit: ImpactPlanner → Impact Map → one
ImpactChallenger round → deterministic challenge validation/reconciliation →
Minimal Effective Change Plan → coverage/evidence gate → user plan approval.
Both model-backed planning roles and the optional single ImpactPlanReviser use
the same pinned `gemma4:e4b`; their inputs contain only bounded requirement,
Task Brain, Project Brain invariant, and accepted `REPO-*` fact projections.
The Impact Map distinguishes a relevant surface from a necessary mutation, so
an existing persistence owner can be `PRESERVATION_ONLY` and become an explicit
`do_not_touch` target rather than an edit merely because it matters to
acceptance. Every active requirement is assigned to change, preservation,
test, or cross-cutting responsibility; an unassigned requirement, unsupported
`MUST_CHANGE`, unresolved blocking challenge, missing test responsibility, or
ownership conflict stops as `PLAN_INCOMPLETE` before approval.

The concise approval UI reuses arrow keys and Enter: Approve, Review/change
scope, Cancel, and Other. An explicit revision becomes a separate
`USER_CONFIRMED` task decision and permits at most one bounded plan revision;
the original `USER_STATED` records remain unchanged. Approval records include
the deterministic plan ID/hash. Any content change makes the approval stale.
An existing-project run without an interactive terminal stops cleanly as
`PLAN_APPROVAL_REQUIRED`; rejection stops as `PLAN_REJECTED`. Neither state is
a root implementation failure or clarification request, and subject-project
files remain fingerprint-identical through planning and approval.

Before Stage 4A, an approved existing-project plan was attached to the normal
recursive task tree; root/task-fit and decomposition could still operate on
the broad task packet before a Worker received a node mission. Stage 4A begins
only after an approved existing-project plan and inserts an authoritative
translation boundary. The exact flow is
`ApprovedPlanSnapshot` → deterministic execution-contract compilation → DAG
validation → per-contract task-fit → optional contract-local decomposition →
the existing Mission Compiler → Worker → the existing verification and
recovery lifecycle. The snapshot is immutable and contains only the approved
plan ID/hash, approval record/hash, authoritative goal, canonical plan nodes,
mutation/test/reuse surfaces, preservation-only surfaces, global
`do_not_touch`, structured prohibitions, integration checks, requirement IDs,
and relevant repository evidence. Raw Planner, Challenger, Source Ledger,
Project Brain, and Task Brain transcripts are excluded.

Execution contracts use the small responsibility set `MUTATION`,
`TEST_MUTATION`, `VERIFY_ONLY`, `INTERFACE_REUSE`, and `INTEGRATION_CHECK`.
Each contract carries plan/node/requirement/obligation/impact/surface/evidence
IDs, separate mutation and inspection paths, reusable interfaces, local
preservation, prohibitions, test checks, completion conditions, dependencies,
provenance, and a deterministic contract hash. Pure reuse and preservation
nodes are attached to a relevant executable or verification contract, so they
do not create unnecessary Builder calls. A bounded responsibility that cannot
fit returns `EXECUTION_CONTRACT_TOO_LARGE`; required authority is never
silently trimmed.

The execution graph is deterministic and validates dependency existence,
cycles, exact contract identity, duplicate ownership, executable mutation and
test coverage, and attached reuse/preservation/prohibition responsibilities.
MissionCompiler receives only one contract projection and completed dependency
summaries. Its mission must keep targets inside mutation scope, inspection
references inside inspection scope, requirements and completion conditions
inside the contract, and all protections intact. Each Worker receives a fresh
bounded context and can inspect approved read-only paths, but mutation tools
reject out-of-contract, inspect-only, protected, or stale paths with
`CONTRACT_SCOPE_VIOLATION` or `APPROVED_PLAN_STALE`.

Greenfield `NEW_PROJECT` runs keep their existing Stage 1/2-to-task-fit
execution semantics unless an approved Stage 3 plan is actually present.
Direct baseline mode remains the frozen pre-Stage-2 comparison: it shares only
project-mode bookkeeping and the existing approval/safety guard when a caller
explicitly supplies approved-plan state; it does not silently receive the
recursive contract graph. Stage 4A adds no model role, no budget increase, no
parallel scheduler, and no change to mutation recovery.

### Experiment 1: Decomposition-first planning

The recursive CLI has two explicit routes for paired existing-project runs:
`--mode current_recursive` keeps the existing global Stage 3 order, while
`--mode decomposition_first_recursive` splits the goal into 2–4 responsibility
statements before impact reasoning. The early split carries only existing
requirement IDs and responsibility text; it cannot name a file or grant mutation
scope. Each child receives a projected requirement ledger and Task Brain, then
uses the existing ImpactPlanner and ImpactChallenger logic. The local impact
claims are combined under the unchanged Stage 3 bounds and gate. One final
plan still needs the same explicit user approval before the existing contract
compiler or Worker can run. Worker, verification, recovery, model, depth, task
count, and integration behavior are shared by both routes.

Run each case on two isolated copies of the same starting project snapshot,
using the same prompt and case ID. Review and approve each final plan through
the normal interactive terminal UI. A `--prompt-file` run is noninteractive and
will stop at `PLAN_APPROVAL_REQUIRED`, so it can measure planning only.

```powershell
python mini.py --mode current_recursive --workspace D:\cases\pause\baseline --experiment-case-id pause-01
python mini.py --mode decomposition_first_recursive --workspace D:\cases\pause\experiment --experiment-case-id pause-01
python scripts/experiment1_report.py D:\cases\pause\baseline D:\cases\pause\experiment --output D:\cases\pause\report.json --markdown-output D:\cases\pause\report.md
```

The report requires paired runs with the same model, HIVO source hash, and
subject inventory fingerprint. It counts first Worker entry, the exact first
blocking stage, verified children, root verification, model calls, elapsed time
excluding the approval wait, and safety gate activity. An approval wait or user
rejection is recorded separately from an orchestration blocker. The paired
report also shows each outcome as count/total and percent, the difference in
percentage points between routes, and average model calls and elapsed time.
The Markdown view presents these figures in a compact Arabic table. Execution
rates exclude runs awaiting approval or rejected by the user from their
denominator; the approval-wait rate uses all runs. Approval waits are excluded
from the pre-Worker blocker count.
The paired
deterministic fixture in `tests/test_decomposition_first_experiment.py` checks
both routes' handoff and approval boundary; it does not establish a live-model
success rate.

### Experiment 2: Contract mission fallback

`--mission-advice-policy strict` keeps the original Mission Compiler gate.
`--mission-advice-policy contract_fallback` still calls the same compiler. If
its advice is rejected, HIVO discards that advice and builds a deterministic
mission from the approved Execution Contract. The fallback mission must pass
the existing contract identity, scope, dependency, preservation, size, and
Worker projection checks before execution. A bad contract or failed fallback
validation still blocks the Worker. The default remains `strict`.

For a paired comparison, use the same planning route, prompt, model, approved
plan, and starting project snapshot in two isolated workspaces, changing only
the mission advice policy. The run metrics record rejected advice,
`mission_advice_fallback`, and `FIRST_WORKER_STARTED` separately. The fallback
does not change Worker prompts, tool permissions, budgets, verification, or
integration.

```powershell
python scripts/experiment2_report.py D:\cases\rkey\strict D:\cases\rkey\fallback --output D:\cases\rkey\report.json --markdown-output D:\cases\rkey\report.md
```

The report requires the same approved plan hash, planning route, model, code,
and starting project snapshot in both runs.

### Experiment 3: Progress-constrained Worker

`--worker-progress-policy current` preserves the existing Worker controller.
`--worker-progress-policy progress_constrained` records contract-relevant evidence
and actual authorized file changes. After the context gate succeeds, the
controller removes the completed `context_sufficiency_check` from the offered
tools. Three consecutive tool calls without new relevant evidence or a legal
file mutation stop the initial Builder attempt with
`WORKER_NO_MUTATION_PROGRESS` and a `WORKER_PROGRESS` blocker. The existing
28-step budget, Worker prompt, model, approval, contract authority, scope
guards, verification, recovery, and integration remain unchanged. The default
remains `current`.

The paired run must use the same task, project snapshot, route, approved plan,
and Mission advice policy in separate workspaces. The run records first legal
mutation, remaining budget, reads before mutation, unique evidence, repeated
inspections and gate checks, rejected calls, and the exact first blocker.
"Legal mutation" here means an authorized mutation tool changed bytes at its
target; child verification still determines whether that edit is correct.

```powershell
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\current --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --worker-progress-policy current
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\progress_constrained --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --worker-progress-policy progress_constrained
python scripts/experiment3_report.py D:\cases\rkey\current D:\cases\rkey\progress_constrained --output D:\cases\rkey\report.json --markdown-output D:\cases\rkey\report.md
```

### Experiment 4: Evidence-grounded mutation

`--mutation-grounding-policy current` keeps the original mutation behavior.
`--mutation-grounding-policy evidence_grounded` requires an initial Builder
mutation to reference source observed through `read_file` or `read_file_range`
at the current file hash. Exact replacement text must occur in the observed
source with the requested match count; line edits must stay inside an observed
span. Overwriting an existing file requires a full-file read. Creating a file
requires a read that observed its absence. The contract and existing mutation
guards remain authoritative.

An unanchored replace returns `REPLACE_NOT_FOUND` or
`MUTATION_ANCHOR_REQUIRED` before any write. The Worker may perform one
`read_file_range` refresh of at most 80 lines on that file and retry once.
A second unanchored attempt returns `MUTATION_TARGET_UNRESOLVED` to the
controller. The default remains `current`. This policy does not change the
Worker prompt, model, budget, progress constraint, verifier, recovery, or
integration.

Compare two fresh copies of the same project with
`--worker-progress-policy progress_constrained` and
`--mission-advice-policy contract_fallback` in both runs, varying only
`--mutation-grounding-policy`:

```powershell
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\current --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --worker-progress-policy progress_constrained --mutation-grounding-policy current
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\evidence_grounded --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --worker-progress-policy progress_constrained --mutation-grounding-policy evidence_grounded
python scripts/experiment4_report.py D:\cases\rkey\current D:\cases\rkey\evidence_grounded --output D:\cases\rkey\report.json --markdown-output D:\cases\rkey\report.md
```

### Experiment 5: Evidence-directed target localization

`--target-locator-policy current` keeps the Experiment 4 Worker path.
`--target-locator-policy evidence_directed` searches only the approved
inspection paths. It scores source lines using lexical terms from the local
task and Execution Contract, including interface names and common keyboard
event identifier variants when the requirement mentions keys. It returns up
to three ranked, non-overlapping spans. The Worker sees candidate IDs and
uses `read_candidate_span`; the controller fixes the path and range and rejects
a candidate if the source changed. The focused read remains subject to the
existing inspection scope guard and supplies Experiment 4's exact mutation
anchor. In this variant, `read_file_range` is removed from the initial
Builder's offered tools so narrow reads use candidate IDs.

For a paired comparison, use the same model, task, project snapshot,
approved plan, `contract_fallback`, `progress_constrained`,
`evidence_grounded`, 28-step budget, and verifier. Vary only the target
locator policy. The expected target span is evaluation data passed to the
reporter; it is never shown to the Worker or used in ranking.

```powershell
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\current --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --mission-advice-policy contract_fallback --worker-progress-policy progress_constrained --mutation-grounding-policy evidence_grounded --target-locator-policy current
.\.venv\Scripts\python.exe scripts/experiment3_approved_run.py --workspace D:\cases\rkey\evidence_directed --prompt-file D:\cases\rkey\prompt.txt --route decomposition_first_recursive --case-id rkey_01 --approved-hash <approved-plan-hash> --approved-path index.html --mission-advice-policy contract_fallback --worker-progress-policy progress_constrained --mutation-grounding-policy evidence_grounded --target-locator-policy evidence_directed
python scripts/experiment5_report.py D:\cases\rkey\current D:\cases\rkey\evidence_directed --expected-path index.html --expected-start 406 --expected-end 411 --output D:\cases\rkey\report.json --markdown-output D:\cases\rkey\report.md
```

### Existing execution lifecycle

Outside the approved Stage 4A contract handoff, each execution receives a
fresh, bounded Node Packet containing the compact root contract, current node
contract, parent summary, verified dependency summaries, relevant verified
memory, failure evidence when retrying, and bounded repository hints. Stage 4A
replaces that broad packet with the single immutable contract projection.
Sibling conversations and hidden reasoning are not copied.
The final transaction is committed only after executable evidence, a read-only
adversarial Falsifier pass, and the deterministic evidence gate succeed. A
`TASK_TOO_BROAD` result triggers a materially smaller re-split when budget
remains. A repeated deterministic implementation failure gets one bounded
capacity probe and may re-split when the fit decision confirms that smaller
granularity is appropriate; provider/environment failures are reported without
decomposition.

Parent nodes receive only compact child statuses, summaries, changed-file hints,
and verification evidence. They integrate the shared workspace and run a fresh
parent verification pass; the root additionally checks fidelity against the
original Goal Contract.
Browser verification is behavioral rather than screenshot-only: a timer profile
drives Start/Pause/Reset, advances a fake clock through a phase transition,
reloads persisted settings, exercises keyboard activation, checks mobile
overflow, and enforces reduced-motion when the contract requests it.

### Re-split rescue metrics and terminal diagnosis

Each completed run now reports four granularity metrics derived from the task
tree, not from model-call volume:

```yaml
failed_nodes_resplit: 12
resplit_nodes_with_any_verified_child: 9
resplit_nodes_fully_recovered: 6
granularity_rescue_rate: 75.0
```

`failed_nodes_resplit` counts distinct failed nodes that actually produced a
new child set. `resplit_nodes_with_any_verified_child` counts nodes with at
least one verified child/subtree, while `resplit_nodes_fully_recovered` also
requires every new child and the re-integrated parent to pass. The rescue rate
is `any-child rescue / failed nodes re-split * 100`, so the example is 9/12.
The same run record preserves the original failed attempt, bounded
deterministic evidence, child outcomes, and final node status in
`task_tree`/`node_diagnosis`.

Composition is reported separately from granularity. Each run also records
`parent_integrations_attempted`, `parent_integrations_passed`,
`parent_integrations_failed`, `parent_integrations_recovered`,
`integration_preflight_conflicts`, `integration_conflicts_resolved`,
`invariant_violations_detected`, and `integration_milestone_runs`.
`integration_success_rate` is `parent_integrations_passed /
parent_integrations_attempted * 100`; it is not a model-call metric.

When a node fails at `MAX_DEPTH = 6`, the controller records a conservative
diagnosis and blocks automatic re-splitting. The diagnosis can route future
work toward `split`, `search_or_mutate`, `parent_repair`, `declare_limit`,
verifier-contract inspection, dependency inspection, or more evidence. An
ambiguous terminal leaf remains `unknown` instead of being mislabeled as a
granularity problem. The console prints a compact failure table alongside the
task tree, for example:

```text
node | scope | initial | re-split | children | why failed | next action
1.2.2.4 | small | FAIL | yes | 1:PASS, 2:FAIL | implementation_strategy_wrong | search_or_mutate
1.2.2.4.1.1 | terminal leaf | FAIL | no | - | scope_too_broad | backtrack_decomposition
```

An ordinary `IMPLEMENTATION_ERROR` gets only a capacity probe; an `EXECUTE`
fit decision does not get silently upgraded to `SPLIT`. This leaves room for
the bounded strategy-search route to handle implementation failures.

### v3 decomposition backtracking and v5 bounded strategy search

The v3 controller keeps `MAX_DEPTH = 6` and `MAX_TOTAL_TASKS = 64`. A
`TASK_TOO_BROAD` leaf at the depth limit is not immediately labeled a model
capability floor. Its parent records the failed child boundaries, terminal
evidence, and the failed decomposition in the next Node Packet, then requests
up to `MAX_DECOMPOSITION_ALTERNATIVES = 2` materially different decompositions.
Alternative child IDs are kept as separate `altN.*` branches so the original
failure is never overwritten. A lexical boundary check rejects an alternative
that merely paraphrases every failed child; the prompt also asks for observable
state, input/output, interface, or deterministic behavior boundaries.

The controller declares a capability-floor candidate only after the bounded
alternative search is exhausted. The v3 search metrics are:

```yaml
terminal_too_broad_nodes: 1
decomposition_backtracks: 1
alternative_decompositions: 1
alternative_decomposition_rescues: 1
decomposition_backtrack_rescue_rate: 100.0
strategy_searches: 0
strategy_generation_failures: 0
alternate_strategies_attempted: 0
strategy_rescues: 0
strategy_search_failures: 0
strategy_rescue_rate: N/A
capability_floor_nodes: 0
```

For a sufficiently bounded `IMPLEMENTATION_ERROR`, the controller first
requires the evidence-based `implementation_strategy_wrong` diagnosis. It can
then generate at most two non-mutating implementation strategies. Strategy A
is executed through the normal leaf engine; Strategy B is attempted only after
A fails and its transaction is rolled back. There is no Challenger, ranking,
voting, or parallel candidate execution. If both materially different
strategies fail fresh deterministic verification, the node is recorded as a
`model_capability_floor` candidate and is not automatically split again. This
route is bounded separately from decomposition and is not used for
`TASK_TOO_BROAD`, dependency, verifier, integration, or environment failures.
If the model cannot produce two valid materially different strategies after
the single bounded replacement request, the search records
`STRATEGY_SEARCH_UNAVAILABLE` and executes no candidate. It does not fabricate
a deterministic fallback pair; fresh existing diagnosis remains in control.

The v5 strategy-search metrics are `strategy_searches` (nodes where planning
started), `strategy_generation_failures` (triggered searches with no valid pair
after generation and replacement), `alternate_strategies_attempted` (candidates
actually executed), `strategy_rescues`, `strategy_search_failures` (valid
candidates executed but all failed), and `strategy_rescue_rate`. A strategy
rescue remains separate from the v3 granularity-rescue metrics.

### Hierarchical Integration Contract

Verified children publish a compact deterministic manifest upward instead of
only a prose summary:

```json
{
  "status": "verified",
  "changed_files": ["game.js"],
  "introduced_symbols": ["spawnEnemy"],
  "modified_symbols": ["update"],
  "interfaces": ["gameState.enemies"],
  "assumptions": ["gameState is the single source of game state"],
  "invariants": ["only one animation loop exists"],
  "verification": ["enemy spawning verified"]
}
```

Most fields are inferred and compacted from changed files and deterministic
evidence; a model does not need to author the whole manifest. Only facts from
the existing workspace scan or a verified child manifest enter the bounded
project-invariant ledger. Free-form child assumptions and contract prose stay
context/evidence, not canonical facts. The parent packet can therefore carry
evidence-backed persistence, loop, input, and root DOM/canvas ownership.

Before any parent integration mutation, a cheap `Integration Preflight` checks
syntax, duplicate `const`/`let`/`class`/`function` declarations, duplicate HTML
IDs, multiple obvious loop owners, generic persistence-constant/key ownership
conflicts, conflicting browser entry points, and collisions in child symbols.
Persistence detection uses identifier patterns and actual storage use; it does
not depend on a hardcoded symbol such as `STORAGE_KEY`. The result
is preserved as `integration_preflight` in `task_tree`, `node_diagnosis`, and
the run event log. A failing preflight is routed as
`local_integration_state_corruption`, with concrete conflicts and current
syntax (`PASS`/`FAIL`) in the parent packet; blocking conflicts then enter the
bounded integration-task path described below.

Integration has its own bounded fit decision. A small integration uses one
focused parent pass. When the preflight reports blocking conflicts, the
controller groups the actual conflicts into small `kind: integration` task
contracts and executes them sequentially through the same `solve_task()` /
transaction / evidence-gate machinery. Each task receives only the root
contract, parent goal, project invariants, relevant verified manifests,
owned preflight conflicts, verified dependency summaries, current failure
evidence, and bounded repository hints. It does not receive sibling chat
histories or hidden reasoning.

After every integration task, the workspace is checked with a fresh preflight;
after the complete integration task set, a fresh preflight must show no
blocking conflicts before parent-level verification can pass. If an
integration task returns `INTEGRATION_TOO_BROAD` or `TASK_TOO_BROAD`, the same
`solve_task()` path decomposes that concern into smaller integration children
while budget remains. Provider/environment failures do not trigger a split.
This is a bounded integration specialization, not a second recursive
orchestrator, and it does not turn unrelated implementation failures into
recursive splitting.

The v4 integration-granularity metrics are
`integration_tasks_created`, `integration_splits`, `integration_resplits`,
`integration_verified_nodes`, `integration_too_broad_nodes`,
`integration_granularity_rescues`,
`preflight_blocking_conflicts_detected`, and
`preflight_blocking_conflicts_resolved`. The reported
`integration_conflict_resolution` is the absolute ratio
`resolved/detected`; it is `N/A` when no blocking conflict was detected.

The failure router therefore distinguishes `scope_too_broad` → re-split,
`implementation_strategy_wrong` → bounded strategy search, `dependency_error` →
dependency/interface repair, `verifier_builder_mismatch` → contract inspection,
`local_integration_state_corruption` → parent normalization/integration repair,
and `model_capability_floor` → record the limit.

The target experiment for the next version is one clean end-to-end hard-task
rescue: the monolithic Gemma attempt fails, HIVO reaches `ROOT VERIFIED`, and
the persisted tree/evidence shows which failed nodes became solvable after
granularity reduction.

If Ollama's CUDA worker crashes because the model exceeds available VRAM, the
same `gemma4:e4b` model is retried CPU-only for the rest of that run. This never
falls back to a different model. SQLite memory remains on disk; active inference
still necessarily uses system RAM and/or VRAM. The run ledger distinguishes
HTTP 200 envelopes, tool-call responses, thinking-bearing responses, terminal
empty messages after a tool result, incomplete non-terminal replies, timeouts,
and runner/VRAM failures. Runtime requests are explicitly non-streaming so a
partial NDJSON chunk cannot be mistaken for a completed assistant message.
