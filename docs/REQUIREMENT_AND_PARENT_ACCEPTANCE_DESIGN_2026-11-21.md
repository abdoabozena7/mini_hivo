# Proposed requirement and parent acceptance design — approval pending

This is a concrete design for unresolved M1/parent boundaries, not an implemented correction or evidence of success. It follows the local 2026-11-21 checkpoint and the preserved M0 findings. R_UPDATE_005 and R_UPDATE_006 are separate controlled-verified corrections; neither closes these acceptance gaps.

## Why approval is required

The user's engineering instructions require approval before changing authority, permission policy, trust boundaries or model settings. This proposal makes a new source-to-obligation binding mandatory in ordinary greenfield planning and replaces the parent's ambiguous mutation-oriented verification role with an explicit read-only pass. It therefore changes what proof may authorize success and how parent execution is constrained. Existing permission scopes, model policy and host thresholds must remain unchanged. The scope is broader than the already verified path/dependency derivation corrections.

## Earliest evidenced boundaries

1. `_children_validator` / `children_schema` require goals, completion prose, scope hints and dependencies, but not complete canonical source-ID allocation. A two-child HTML/CSS plan can omit JS and interactions yet remain shape-valid.
2. A feature child can satisfy JS syntax while required browser behavior is classified not applicable; a generic clean-load profile cannot assert add/delete/toggle/persistence. This is insufficient child acceptance, not demonstrated false root acceptance.
3. `aggregate_task` builds a parent candidate through `_prepare_task_impact_contract`. A greenfield root has no concrete child assignment/mission and is treated as needing mutation. The impact validator rejects `scope_required` with no effective authorized paths. Child acceptance does not authorize arbitrary parent writes; the existing guard correctly refuses the candidate.
4. Ordinary legacy `evidence_gate` lacks mandatory current-subject binding. The Stage 5B receipt path corrected in R_UPDATE_005 is separate and must not be claimed active in ordinary greenfield runs.

## Proposed binding artifact

Reuse canonical source requirement IDs, existing obligation-coverage machinery and existing child/parent receipt validation. Do not introduce an alternative authority issuer. Proposed fields per binding:

```json
{
  "source_requirement_id": "REQ-004",
  "obligation_id": "REQ-004/observable-outcome",
  "owner_task_id": "2",
  "implementation_paths": ["app.js"],
  "inspection_dependencies": ["1"],
  "verification": {
    "kind": "browser_scenario",
    "scenario_id": "source-grounded-scenario",
    "artifact_dependencies": ["index.html", "style.css", "app.js"],
    "expected_postconditions": ["source-grounded observable outcome"]
  },
  "parent_obligation": "recheck-current-integrated-result"
}
```

This example names test-fixture artifacts only; production policy must not contain To-Do filenames, selectors or handler names. Actual scenarios are compiled per source request. Model-proposed selectors/actions are verification plans, not proof or new authority. Unknown meaning, unsupported assertions or ungrounded expected outcomes remain unresolved and require bounded clarification/planning recovery.

## Planning and ownership invariants

- Every canonical supported source requirement must map to concrete child obligations or an explicit parent obligation. Split multi-artifact/multi-behavior requirements into traceable obligations retaining the original ID; do not claim one trivial subcheck covers an entire compound requirement.
- Every required artifact and behavior has an owner; every child's implementation paths stay within its existing mission/outer authority intersection. Requirements do not themselves grant new paths.
- A foundation may certify only its assigned structure/style/linkage obligations. Downstream functional duties remain open at the parent and assigned to later children.
- A consumer may inspect accepted predecessor artifacts through declared dependencies; mutation remains separately scoped. Editing shared files needs explicit existing authorization, not dependency permission alone.
- Reject an incomplete partition before dispatch, using bounded replanning/clarification. Never silently discard an unsupported requirement or substitute syntax for an interaction.

## Independent execution and evidence

Implement a bounded generic action/assertion adapter for supported browser scenarios: navigate, inspect resource/runtime errors, locate controls, fill/click/toggle, inspect rendered state and reload in the same browser context when persistence is required. All expected outcomes must trace to source obligations. Do not infer behavior from labels, page load, model statements or the presence of event-handler text.

Bind each proof to task identity, obligation/scenario identity, requested/resolved target, scope/authority identity and a complete bounded fingerprint of current relevant artifacts. Capture subject identity before and after verification; changes during verification invalidate the proof. Missing, malformed, wrong-target, stale or incomplete proofs cannot authorize success. Existing old receipts remain evidence of their historical checkpoint, not automatically upgraded current proof.

## Parent verification versus integration mutation

After successful children and integration preflight:

1. Build a controller-owned read-only parent verification mission, scoped to relevant accepted artifacts and complete parent obligations. Do not run an unrestricted Builder to discover what it might change.
2. Use existing read-only tool restrictions and an explicit empty mutation surface; also compare source artifacts before/after verification. Runtime evidence output must be kept separate from project mutations. Read-only is an enforceable execution mode, not a prompt instruction.
3. If integration requires edits, create a separate bounded integration task with explicit already reviewed authority and affected owner/dependency obligations. Do not union all child writes into implicit parent permission or disable impact contracts.
4. After any accepted integration edit or repair, invalidate affected proofs and verify the current integrated result. Root success requires complete source coverage, valid child responsibilities, current parent evidence, no unresolved failures and retained deliverables.

The present `verification_only` flags and `worker_required` fields are not enough by themselves to authorize this design: some existing impact paths treat a non-required impact guard as inactive. Simply setting a flag could disable a safeguard without enforcing a read-only tool boundary. Implementation must test actual rejected mutations before enabling the parent pass.

## Bounded recovery

Attribute failed child obligations to their responsible child; attribute cross-artifact compatibility/final composition failures to explicit parent integration obligations. Replanning or Repairer gets only the affected existing scope and fresh diagnostic context. Stale evidence requests fresh verification, not invented implementation changes. Reaching a bound returns explicit incomplete/blocked status; never drop the obligation or widen scope. Controlled Python Repairer tests already cover mutation/fresh-check/commit/rollback; this proposal needs browser-obligation equivalents before any live claim.

## Verification gate for implementation

Baseline and treatment must use the same source ledger and independent observable oracles. Required controls:

- Complete plan versus omitted artifact/behavior/owner; wrong or unsupported oracle; invalid dependency/scope.
- Foundation accepted for its own duties while downstream obligations remain pending.
- Working multi-file project versus missing/disconnected/inert/runtime-failing/partially functional JS; absent required persistence; later edits removing prior behavior.
- Parent read-only verification succeeds without mutations; attempted writes, including via commands, are denied; real integration edits require separate bounded authority.
- Changed dependencies invalidate proof; unchanged unrelated artifacts do not; graph overflow, wrong target, malformed/unavailable evidence and changed-during-verification controls fail closed.
- Bounded repair, fresh independent rechecks, rollback on rejection and preservation of previously accepted artifacts.
- Final root acceptance only after complete source coverage and current full integrated proof. Scripted controller success remains distinct from live-model reliability.

## Explicit scope of requested approval

Approval would cover local implementation/tests of mandatory greenfield obligation bindings, bounded generic browser scenarios, current-subject legacy evidence checks and an enforced read-only parent verification pass with separately authorized integration repair. It would not authorize broader file permissions, automatic model/provider changes, threshold changes, expensive live campaigns, commits, publication, history reconstruction or an automatic merge.
