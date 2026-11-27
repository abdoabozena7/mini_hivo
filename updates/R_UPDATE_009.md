# R_UPDATE_009 — Verify complete parent obligations through an enforced read-only pass

## A. Identification

PA-001. Implementation/unit checkpoint 2026-11-21; interrupted functional verification completed 2026-11-25, Africa/Cairo. VERIFIED for the controlled supported counter contract, not arbitrary projects or live-model reliability. Branch `rodina/dev-turn-2026-11-20`, HEAD/base `ef08b09708a295d5765d4c207141aa8a11d85f72` plus preserved corrections 004–008. 009 unused before creation. No containing commit/PR. [Source identities/evidence](../evidence/acceptance-phase-20261121/parent.json).

## B. Original problem

The controlled working counter had accepted foundation/functional children and independently passing increment/persistence, but actual root failed with `IMPACT_CONTRACT_INCOMPLETE`: no safe authorized parent mutation path. R008 functional-003 preserves that baseline. A verification-only parent should not require arbitrary implementation permission, and child ownership must not silently grant it.

## C. Why necessary

Setting an impact guard to optional is not an enforceable read-only contract. Root must prove complete current obligations and retain accepted artifacts while keeping real integration edits inside separately authorized missions.

## D. Root cause

Ordinary `aggregate_task` dispatched a mutable Builder path even when preflight conflicts were absent and only final verification was needed. `_prepare_task_impact_contract` correctly refused a mutation-oriented parent with no assignment. The construction mode was wrong; the guard was not bypassed or relaxed.

## E. Exact changes

- New `hivo/readonly_acceptance.py`: contained inspection normalization, an explicit tool allow-list, bounded whole-project source snapshots and child obligation proof identity checks. Parent context denies commands, program execution, writes, edits and backups; only scoped reads and browser verification are offered through that guard.
- `mini.py`: a controller-owned `_readonly_parent_acceptance` path for canonical ordinary greenfield aggregation after successful children and integration preflight. Validate actual allocation, admitted obligations and intact child proof hashes/responsibilities; combine complete source obligations; rerun real current verification; compare source snapshots; recheck integration preflight. Return done only when every condition passes, with zero parent project mutations.
- Existing conflict repair stays before this pass, through the existing bounded integration-task execution/impact path. The new operation neither creates nor waives a mutation contract. Existing approved Stage 5B routes retain their own lifecycle.
- New parent tests and separate evidence/report. All prior source corrections, reports and artifacts preserved.

## F. Mechanism / alternatives

Accepted children -> existing integration/conflict processing -> historical proof identity validation -> explicit empty parent mutation scope / contained inspection scope -> fresh complete source oracles -> whole-source before/after equality -> current integration preflight -> root/parent acceptance. Child historical attribution stays historical; the parent reruns obligations on current shared files instead of requiring a predecessor's old bytes to remain unchanged after a legitimate successor edit.

No blanket parent scope, union of child write permissions, optional-impact bypass or forged Builder completion is used. The parent makes no provider call and opens no mutable transaction. Backend verification receipts are evidence, not new write authority.

## G. Direct functional verification

`20261125-parent-functional-001`, exit 0: real controller, planning admission, mission/context/impact guards, file tools, transactions, Chromium and source-bound obligations; planner/role decisions scripted. Foundation and functional child both `done`. Independent increment and reload persistence PASS. Real root `done`, `parent_verification.mode=read_only`, empty changed_files, identical complete project-source snapshots, zero parent provider calls. All five diagnostic assertions true. Accepted HTML/CSS/JS remain in the isolated run workspace.

This demonstrates one complete root-accepted controlled counter for its three declared requirements. It is not a full original eleven-requirement To-Do run, a real-provider run or universal requirement semantics certification.

## H. Additional tests

Retained November 21 treatment-002: **108 passed, zero failures/errors/skips**, exit 0. This count was inspected on November 25, not represented as a freshly rerun cohort. Eight parent controls cover no mutable Worker, source tampering during verification, missing child proof, changed responsibility metadata, missing parent oracle, explicit empty inspection scope, unresolved integration conflicts and denied mutation/command tools. Unit preflight/backend/child proofs are explicitly scripted; direct functional proof above uses the real paths. Existing adjacent ownership, oracle, repair, scope, manifest and dependency tests also pass in that cohort.

## I. Failed / blocked attempts

The first unit baseline and treatment-001 used scripted child results whose reconstructed manifests triggered unrelated duplicate-symbol conflicts; these are preserved harness/topology failures, not evidence that read-only acceptance succeeded. Treatment-002 explicitly scripts preflight for those controller unit checks; the functional chain independently exercises real preflight.

The November 21 functional launch was not executed: automatic approval review hit a usage limit. The review explicitly stated this was not an unsafe-action determination. On November 25, after that limit elapsed and the user requested continuation, the permitted native-process invocation completed. No sandbox/network weakening or approval bypass was used.

## J. Impact

The observed parent construction blocker is resolved for supported canonical ordinary greenfield projects needing verification only. Read-only acceptance preserves mutation boundaries; authorized integration repairs remain separate. Actual root completion is now demonstrated for the narrow controlled counter contract.

## K. Limitations

All model decisions in the counter proof are scripted. Live/cloud reliability, the original full To-Do source, broader language/project types, unsupported/qualitative oracle meanings and native ES-module syntax handling remain unverified/unresolved. Read-only snapshots are bounded to 512 files/16 MiB and refuse escaping source symlinks. They observe source state at verification boundaries, not permanent immunity from later external edits. Controlled tests cover existing authorized repair behavior; this record does not claim a new live Repairer mutation.

## L. Evidence / reproduction

[Curated parent evidence](../evidence/acceptance-phase-20261121/parent.json), raw original/unit/functional cohorts under `output/acceptance-phase/`. Exact completed functional command (Python 3.14.8, existing Chromium):

```powershell
.\.venv\Scripts\python.exe -u -B -X utf8 scripts/acceptance_phase_functional.py --expect-root done --output-dir output/acceptance-phase/20261125-parent-functional-001
```

Use a new output directory for repetition. Original source and raw outcome hashes are retained separately from reviewed derivatives. Nothing staged; no staged-blob hash claim. Previous update/journal/evidence files were not rewritten.

## M. Team summary

Proposed PR title: Verify complete ordinary parent obligations read-only. The parent now checks real current behavior and source integrity without acquiring implicit write authority; conflicts still require separate authorized integration work. The retained 108-method cohort and newly completed real controlled counter chain support the declared scope. Root accepted for that exact controlled contract; live/general completion remains unproven. Local and uncommitted only; no push, PR, branch/remote/history changes.
