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

Recursive mode first performs bounded repository reconnaissance, then asks the
pinned model whether each node fits one focused Builder execution. A split
creates 2–4 small sequential child contracts; a child may become a parent and
split again up to `MAX_DEPTH = 6` and `MAX_TOTAL_TASKS = 64`. A leaf is never
secretly scheduled into deterministic stages. Baseline mode sends the root
through the same `execute_leaf` engine without adaptive decomposition.

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

The v16 requirement boundary runs before that existing expansion. It creates a
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

Every execution receives a fresh, bounded Node Packet containing the compact
root contract, current node contract, parent summary, verified dependency
summaries, relevant verified memory, failure evidence when retrying, and bounded
repository hints. Sibling conversations and hidden reasoning are not copied.
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
