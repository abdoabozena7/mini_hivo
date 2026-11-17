# Experiment 20 — Child-Scoped Verification Obligations and Parent Completion Coverage

**Live achievement:** Real-model execution demonstrated child-scoped verification through production orchestration: the foundation child passed verification and transaction acceptance without premature mechanics, the parent enforced its retained requirements, and the movement child received movement-only checks. Discovery and local correction of the production parent-lineage mismatch enabled this route. Real Builder and Repairer calls persisted application edits. Updated 7 November 2026.

Owner: Tasneem's independent Mini Hivo research/implementation workstream. Baseline retains original authorship and Experiments 1–19. No teammate's independent implementation was incorporated.

## Research question and hypothesis

Can Mini Hivo verify each sequential child against its assigned browser obligations, preserve already verified behavior, and retain the full original source requirements at root verification?

Hypothesis: a controller-owned, conservative verification projection can remove premature downstream checks from recognized child milestones, while full-source root verification and freshly rechecked committed duties prevent requirements disappearing. Unknown assignments must not silently become a weaker generic-web PASS.

The claim is about the existing configured browser-check families, not complete understanding of natural-language assignments or creation of new behavioral oracles.

## Observed Run-010 problem and evidence boundary

The original run used `2a8b945`, `current_recursive`, `field_scoped` classification and the unchanged Coin Courier task. The SQLite task ledger records these goals:

| Child | Stored responsibility |
|---|---|
| 1 | Basic HTML structure, canvas setup and initial game-state management |
| 2 | Player movement, arena boundaries and input |
| 3 | Coin collection, scoring and obstacle collision |
| 4 | Start, Game Over, Restart and High Score persistence |

Native line 25 identifies child 1; line 33 records mission dispatch with a null execution-contract ID. SQLite events 9/10 show required keyboard movement, collection and `AGENT_GAME` checks on child 1. Native lines 82/88/120 record failures. Later children were still pending when the supervised run stopped.

The complete original child `done_when` lists and compiled mission were not preserved. Therefore we establish scope-blind profile inference, not the exact ownership of every historical bridge obligation or a counterfactual successful original run.

## Confirmed causes

1. [`infer_web_profile`](../../hivo/verification.py) classifies project kind and then selects behavioral obligations from the same text. Any game gets keyboard movement and a bridge; `coin` adds collection. The child 1 goal alone exactly reproduces the recorded profile. Product identity and generic game-state wording are not sufficient evidence of local responsibility.
2. Worker `verify_web_app` and controller `optional_browser_check` both used this broad inference. Neither had a recognized milestone projection.
3. The root integration path can receive an active contract reduced to local/integration duties. Controlled fixtures demonstrate that inferring from this projection alone can omit original final obligations. Run-010 did not reach root verification; this third observation is **offline**, not a historical live false acceptance.

4. Live preparation confirmed a production activation mismatch: make_task emits parent, while scope_contract checked parent_id. Original fixtures missed this route. The correction recognizes canonical lineage while refusing narrowing for roots or conflicting aliases.

The verifier correctly rejected its selected missing checks. Experiment 19 corrected outcome corruption; Experiment 20 changes which obligations are selected, without changing result interpretation or final gate logic.

## Baseline, treatment and fixed conditions

- Baseline: `d15b6068f78dd5b9e46daacd81f5543af5c2cf89`, the Experiment 19 submission including treatment `f8bf65e`.
- Treatment implementation: `a91062551c9b346a35eb4abb5f18a6f64f95a72b`.
- Historical offline method: retrospective same-fixture comparison with controlled snapshots and scripted providers.
- Live campaign: base 6ec3bda16e88af764f63ea9fc7319096ffd25cbe plus staged local corrections; real gemma4:e4b and production execution. Controller-declared movement/collection are not new CLI ingestion/decomposition coverage; see [live protocol](supporting/live-protocol-20261107.json).
- Historical offline model/browser calls: zero; later live calls are recorded separately. No role budgets or authorization rules were increased or weakened.
- [Manifest](manifest.json) pins source/fixture identities. [Fixture](../../tests/fixtures/experiment20_scope.json) retains original goals and source contract. Its local acceptance conditions are expressly declared test inputs, not recovered historical assignments.

## Implementation and scope

[`hivo/verification_scope.py`](../../hivo/verification_scope.py) adds a verification-only projection:

1. Narrow only ordinary `NEW_PROJECT` game children with retained source requirements and recognized nonempty local conditions. Explicit local behavior in the goal remains required; a product name alone does not create collection duties.
2. Foundation-only narrowing uses fully recognized structural clauses, not a broad substring exception. Explicit bridge assignments and all recognized local behavior families remain checked. Unsupported/missing assignments conservatively retain full source-game verification.
3. Existing-project, approved execution-contract and timer routes do not receive this child narrowing. The original public classifier remains unchanged.
4. Root retains all original source requirements in its verification projection, even when its active contract or summary is reduced. Unassigned touch/win obligations do not disappear merely because all children are labeled complete.
5. Completed profiles are retained only after a successful quality/transaction result and fresh browser PASS. Later checks for that application must execute the union of current and previously committed duties. Prior results are **requirements to recheck**, not reusable success evidence. Registry is per run and target.

[`mini.py`](../../mini.py) supplies the controller projection at leaf dispatch and root aggregation, shares profile selection between Worker and controller, and retains profiles after the existing initial/post-repair acceptance paths. No mutation permission is derived from this projection, and no execution contract is fabricated.

The production correction recognizes canonical parent, supports legacy parent_id, and refuses narrowing for canonical roots or conflicting aliases. Four real-constructor controls supplement the original 34 methods. This update includes only that source/test correction; shared compaction and tool-hint patches remain separate.

## Paired offline comparison

The [probe](../../scripts/experiment20_probe.py) loads exact baseline `mini.py` in an isolated process and compares it with the pinned treatment source. Both use the same controlled fixture and twelve named assertions. In the baseline, tests deliberately use the existing unprojected contract when the new helper is absent. The conditions, browser snapshots and route inputs are unchanged across arms.

| Measure | Baseline | Treatment |
|---|---:|---:|
| Selected assertions satisfied | 4/12 | 12/12 |
| Failing test methods | 8/12 | 0/12 |
| Errors | 0 | 0 |
| Model / browser calls | 0 / 0 | 0 / 0 |

The eight reproduced mismatches include both premature child checks and incomplete root-profile selection. The four preserved baseline controls are unknown-scope rejection, explicit bridge retention, approved-contract exclusion and unchanged legacy classifier behavior. [Per-case results](supporting/comparison.json).

The twelve offline assertions evaluate controlled assignments, rather than independent projects or population reliability.

The [historical-scope artifact](supporting/historical-scope.json) independently records the original event 10 profile/hash and goal-only reproduction. Evaluating that stored snapshot under the declared foundation fixture succeeds; the unavailable original acceptance list prevents treating it as a successful historical child transaction.

## Expanded regression and integration evidence

**Live findings — verified child scope, enforced parent duties and real writes.**

The real Builder/Falsifier/transaction path accepted the foundation's assigned title/canvas work. Fresh parent verification then enforced movement and collection, while the movement child's Falsifier selected only keyboard_movement. This demonstrates the intended scope distinction in production execution: a child can complete its milestone without removing the parent's final obligations.

**Validated production correction.** The make_task parent field is now recognized by scope_contract, with conservative handling of roots and conflicting aliases. The expanded 38-method cohort passed after three reproduced failures, and the live profiles confirmed activation.

**Provisional implementation.** Three Builder writes and one Repairer write persisted under the existing authorization checks. The table separates this execution achievement from functional acceptance.

| Production boundary | Actual result |
|---|---|
| Foundation Builder/Falsifier/transaction | Accepted title/canvas without future mechanics or bridge |
| Fresh parent after foundation | Correctly rejected missing movement and collection |
| Final movement-child Falsifier | Required keyboard_movement only, not future collection |
| Final movement attempt | Three Builder writes and one Repairer write persisted provisionally |
| Movement acceptance | Not obtained: source-dump and bridge movement checks failed |
| Collection and complete parent | Collection not dispatched; positive completion not reached |

The accepted foundation was explicitly reused as a checkpoint with fresh authorization. Earlier malformed tool calls ended in TASK_TOO_BROAD; after schema-feedback corrections, the model progressed to valid writes. The final attempt reached its process cap during repair, with source-dump and bridge-movement failures still present. [Evidence](supporting/live-evidence-20261107.json) retains retry timings, mutation-failure categories and stop provenance.

**Separate infrastructure improvements.** Local task retention preserved all 18 captured Repairer assignments. Schema hints were corrected to report current missing/extra-field/type errors instead of unsupported truncation or stale diagnoses. These shared corrections contributed to the campaign but remain outside both experiment PR updates.

[Live results](supporting/live-results-20261107.json) and [evidence](supporting/live-evidence-20261107.json) retain precise boundaries. The original offline suite table follows unchanged as historical support; its 34 scope methods are not the later 38-method cohort.

| Suite | Baseline existing control | Treatment |
|---|---:|---:|
| `test_experiment20_child_scope.py` | 12 paired assertions above | 34 passed |
| `test_experiment17_field_scoped_profile.py` | 5 passed | 5 passed |
| `test_verified_child_integration.py` | 22 passed | 22 passed |
| `test_experiment9_integration_targets.py` | 12 passed | 12 passed |
| `test_verification_outcome_integrity.py` | 30 passed | 30 passed |
| `test_evidence_policy.py` | 9 passed | 9 passed |
| `test_verification_applicability.py` | 15 passed | 15 passed |
| `test_experiment11_evidence_compatibility.py` | 10 passed | 10 passed |
| `test_experiment13_monotonic.py` | 9 passed | 9 passed |
| `test_experiment18a_schema_feedback.py` | 9 passed | 9 passed |
| `test_context_sufficiency_gate.py` | 9 passed | 9 passed |
| `test_greenfield_context_progress.py` | 9 passed | 9 passed |
| `test_repair_impact_anchor.py` | 3 passed | 3 passed |

**176 selected treatment methods passed: 34 new and 142 existing, zero failures/errors/skips.** All 142 existing methods also pass with pinned baseline `mini.py` loaded in memory. Counts overlap the twelve-method comparison and earlier cohorts; do not add them together or claim full-suite success. [Treatment results](supporting/selected-tests.json), [baseline control](supporting/baseline-existing.json).

New controls cover Worker/controller agreement, missing/unknown/mixed scope, explicit bridge and Game Over ownership, other-domain/existing/approved exclusions, malformed scope metadata, same-target prior obligations, separate-target isolation and full root touch/win coverage. Real `evidence_gate` rejects incomplete parent snapshots and accepts a complete declared profile with matching tool evidence.

The historical leaf test traverses actual `execute_leaf`, a real read tool, verification routing, quality checks and transaction acceptance, recording the profile afterward. Providers/browser observations are deterministic substitutes and the inert HTML fixture pre-exists; this is offline integration evidence, separate from the later live writes.

## Review findings and safety

Context/Impact checks permitted actual provisional writes while required verification rejected defective candidates. Parent recognition changes verification lineage only, not permission, transaction rules, budgets or quality gates. Ordinary greenfield execution contracts were null; optional progress_constrained and contract-bound MutationGrounding activation are not claimed.

Historical negative controls for invalid generic-web fallback, explicit Game Over and unsupported mixed clauses remain in [fallback](supporting/fallback-review-failure.json), [Game Over](supporting/gameover-review-failure.json) and [clause safety](supporting/clause-safety-before.json) records. Fully recognized clauses govern narrowing; complete-game children cannot opt into foundation-only checks. Fixture assumptions were corrected without relaxing gates. Final a910625 superseded local ancestor a6cd0c5.

Shared local retention/schema feedback patches were used but are not bundled. A selected 133-method cohort passed before final hint changes; nine focused hint methods and one existing validator passed afterward. The larger cohort was not rerun at that final revision. Counts overlap and do not certify full recovery.

## Limitations and remaining work

| Follow-up finding or target | Interpretation and next action |
|---|---|
| Candidate accepts ArrowUp/WASD; probe calls move('up') | Confirmed adapter/verifier mismatch. Captured assignment names move(direction) without its enum; establish and advertise the intended API before changing producer or oracle. |
| Physical ArrowRight and ArrowUp moved the candidate | Verified for those inputs only via file URL; production probe used HTTP on identical bytes. Not full controls, collection or acceptance proof. |
| JavaScript appeared as page text; source_dump rejected it | Confirmed generated-artifact defect independent of the direction mismatch. Inspect document structure and edit placement. |
| Nonfunctional bridge repairs, repeated ranges and stale exact match | Observed recovery problem; a defective file tool or single controller root cause is not established. Inspect current-source reads and retained diagnostics. |
| Accepted movement, collection retaining movement, complete-parent PASS | Pending live acceptance, not confirmed independent defects. Validate the affected scenario after a supported correction. |

The nonfunctional bridge output and the stale-edit sequence are distinct findings: first inspect whether generated calls reach real application functions/state; separately inspect fresh reads and recovery after stale-target rejection. Neither alone proves a file-tool defect or a single controller root cause. The remaining acceptance targets in the table are validation gaps, not confirmed independent defects. Full live recovery and complete game acceptance are outside the demonstrated results.

Recognition remains bounded English clauses with conservative fallback. Original Run-010 full child conditions are unavailable. The registry is per run/target, not restart-persistent or artifact-hash proof. Full seven-family coverage, unknown clauses and authority exclusions have offline controls, not comprehensive live coverage. Exact scoring, repeated restart, storage denial and detailed user oracles are not newly supplied. Historical fixture-dependent authority/recovery suites remain uncertified.

## Conclusion and reproducibility

Real-model execution demonstrated the scope improvement in production: foundation verification reached transaction acceptance without premature mechanics, the parent enforced retained requirements, and the movement child received its own checks. Correcting canonical parent recognition connected the implementation to the actual task constructor. Authorized Builder and Repairer writes show that the campaign progressed from verification selection to persisted implementation.

The [RUNBOOK](RUNBOOK.md), [live results](supporting/live-results-20261107.json), [live protocol](supporting/live-protocol-20261107.json) and [curated evidence](supporting/live-evidence-20261107.json) connect these observations to their controls. Original [offline results](experiment20-pr10-results.json), [protocol](protocol.json), [methodology review](METHODOLOGY-REVIEW.md) and [regression tests](../../tests/test_experiment20_child_scope.py) remain supporting evidence. Raw traces/game files stay LOCAL-ONLY; existing PR #10 depends on PR #9, and this preparation changes neither PR.

Next, align the advertised bridge contract and investigate structural repair and stale-edit feedback. Then validate movement-child acceptance, collection with fresh retained-movement checks, and complete declared-parent acceptance.
