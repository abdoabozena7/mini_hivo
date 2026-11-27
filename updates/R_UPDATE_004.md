# R_UPDATE_004 — Preserve verified child manifest provenance across sequential edits

## A. Update Identification

- Date: 2026-11-21, Africa/Cairo. Owner: Rodina's development turn.
- Status: implemented and verified within controlled transaction/integration scope; uncommitted and unpublished. This is not complete application or live-model certification.
- Branch: `rodina/dev-turn-2026-11-20`.
- Actual base: `ef08b09708a295d5765d4c207141aa8a11d85f72`; production diff is confined to `mini.py::attach_verified_manifest`.
- Tested source: base plus the local manifest correction. Exact source/test hashes are in [summary.json](../evidence/m0-characterization-20261121/summary.json), `manifest_after.source_sha256`.
- Containing commit / PR: none. No commit, push or PR is authorized.
- Related investigation: [provisional M0 record](M0_INVESTIGATION_2026-11-21.md), component M0-B; V001 milestones M0/M2/M4.
- Numbering: 001 reserved, 002/003 present, 004 available before exclusive creation. No journal version allocated.

## B. Original Problem

The controlled foundation creates HTML/CSS and an inert JavaScript companion. A dependent functional child legally edits that same JavaScript and supplies working interactions. Both children pass their actual leaf gates. Parent aggregation then reports both children introduced the successor's symbols, including `render` and `save`, and creates a duplicate-ownership repair task.

Expected: the foundation's historical empty symbol set remains empty; symbols introduced by the successor remain attributed to that successor. Sequential editing must not manufacture competing ownership. Genuine conflicts and current-file errors must still block integration.

Observed: baseline `chain_full/manifests-before-parent.json` records an empty foundation symbol set; `parent-preflights.json` records the successor set attributed to BOTH children. Independent browser behavior passes for the retained fixture, but parent preflight rejects `duplicate_child_symbol`.

## C. Why the Update Was Necessary

The parent was rejecting legitimate sequential reuse before it could evaluate complete project obligations. This is a provenance defect, distinct from M0's behavioral-verification gap. Removing the duplicate-owner gate would hide real conflicts and would not correct attribution.

## D. Root Cause Analysis

`aggregate_task` calls `attach_verified_manifest` again for successful children. `_manifest_from_result_source` treats empty `introduced_symbols`, `modified_symbols` or `interfaces` as absent and reconstructs them from current files and global `LAST_COMMITTED_TRANSACTION`. After child 2 commits, those inputs describe child 2, including when reconstructing child 1.

| Finding | Classification | Evidence | Limit |
| --- | --- | --- | --- |
| Foundation acquires successor symbols during aggregation | Reproduced defect | Original before-parent/preflight records; new failing focused test | Controlled execution, scripted model |
| Prior modified-symbol history changes under later transaction | Reproduced defect | Second failing focused test | Manifest API/transaction path |
| Global latest-transaction inference is reused for historical result | Confirmed source cause | `attach_verified_manifest` -> `_manifest_from_result_source` | Delayed first attachment without a prior snapshot remains outside this correction |

Baseline focused result: five tests executed, three passed, two failed, no errors. The two failures reproduce changed historical attribution. Baseline process exit 1 is expected reproduction evidence, not a passing suite.

## E. What Changed

| File / function | Change | Scope |
| --- | --- | --- |
| `mini.py::attach_verified_manifest` | Store a controller-created per-result manifest snapshot at first attachment; reuse a deep copy only for the same task identity | Historical attribution only; ten inserted lines and one replaced line |
| `tests/test_verified_manifest_provenance.py` | Five focused regression/safety tests | Real filesystem transactions and preflight; no provider |
| `scripts/m0_manifest_checks.py` | Exclusive-output offline focused/adjacent runner | Commands, logs, counts and source hashes |
| `scripts/m0_manifest_functional.py` | Fresh controlled successor/parent verification runner | Real execution paths; independent DOM oracle; explicit failed root |
| This record and reviewed evidence | Separate component verification from broader ongoing M0 work | No inherited report edits |

Other new `m0_*` scripts are investigation harnesses from the interrupted M0 work, not additional production fixes attributed to this correction.

## F. How the Fix Works

The first `attach_verified_manifest` builds attribution using the existing inference mechanism and saves a private controller snapshot on the result. Reattachment uses a deep copy of that bounded snapshot for the matching task instead of consulting another transaction. Empty symbol sets remain valid observations.

The snapshot is separate from model-proposed `builder.manifest`; empty model claims do not disable initial source inference. The task/result's public projection can change independently without changing the controller snapshot. The correction does not convert a historical manifest into fresh behavioral proof, remove current source scans, bypass child/parent gates or broaden mutation paths.

Alternatives considered: treating every empty model manifest as complete would allow untrusted omissions; removing duplicate-owner checks would hide genuine conflicts; reconstructing historical manifests from current files recreates the original defect. Per-result controller provenance is the smallest correction for the demonstrated normal attachment lifecycle.

## G. Functional Verification

Fresh controlled chain: `output/m0-characterization/20261121-manifest-functional-001`, process exit 0. Same byte-preserved original prompt and canonical source ledger as the baseline; fresh workspace. Model decomposition, missions and role choices scripted. Scheduler, task lineage, dependency inspection, scope guards, real writes/edits, Falsifier tools, Chromium, impact checks and runtime commit/rollback were exercised.

| Observable oracle | Actual result |
| --- | --- |
| Foundation and functional successor accepted by real leaf gates | Both `done` |
| Feature child consumes predecessor artifacts and edits only assigned JS | Recorded real read/edit path; sibling scope unchanged |
| Foundation manifest before/after aggregation identical | True |
| No false duplicate-child-owner conflict | True; parent preflight PASS, zero conflicts |
| Independent fixture actions | All recorded assertions pass: add, empty input, completion, deletion, reload text/completion, narrow mobile overflow and runtime-error checks |
| Retained successor artifact hashes after failed parent attempt | Match accepted successor bytes |
| Root acceptance remains real | Failed at `IMPACT_CONTRACT_INCOMPLETE`; no successful root verdict fabricated |

The direct functional claim is removal of false historical ownership in this controlled chain. The application is not declared completely accepted. A full qualitative responsive-interface review and all generic task families are outside this proof.

## H. Additional Successful Tests

Fresh offline affected/adjacent selection: **165 passed, zero failures, zero errors, zero skips**, process exit 0. Modules:

- `test_verified_manifest_provenance`
- `test_adaptive_architecture`
- `test_verified_child_integration`
- `test_verification_outcome_integrity`
- `test_run4_scope_regression`

Model entry points were blocked and individual fixtures disclosed scripted replacements. The existing tests include mocked orchestration checks as well as real controlled tools; the suite count is not a count of independent end-to-end applications. Earlier 13-control cohorts overlap and are not added to 165. Tasneem's inherited 516-pass result was not rerun or represented as fresh evidence.

## I. Regression and Compatibility Impact

Negative controls still pass: two genuinely independent child owners of a symbol are rejected; current duplicate declarations remain rejected; empty untrusted Builder manifest data does not suppress source inference. Adjacent integration, verification integrity, repair and scope checks pass. Parent scope and behavioral gates remain blocking as before.

The two original focused failures and all preliminary diagnostic failures remain preserved. No broad discovery, dependency installation or live-model run was performed. Validation reused Python 3.14.8 and existing Chromium, differing from the teammate's Python 3.11 environment. Full cross-version certification remains unverified.

## J. Overall Impact

The accepted result now preserves its own historical manifest rather than inheriting successor changes. This restores correct provenance for the demonstrated sequential shared-file route while preserving real conflict detection. It does not solve requirement coverage, browser behavior policy or root authority construction.

## K. Remaining Limitations

- M0-A: missing functional behaviors can still pass child verification. M1 requires a reviewed requirement/owner/oracle binding design.
- Parent verification/mutation scope still stops the successful-feature chain; no blanket authority was granted.
- A first-ever late reconstruction without an existing controller snapshot is not historical recovery. No old stored receipt is migrated or silently refreshed.
- Legacy direct-gate stale-receipt acceptance remains a separately scoped finding.
- No complete root, genuine model reliability or retained successful live Repairer mutation is proved.

## L. Evidence and Reproduction

Reviewed portable observations: [summary](../evidence/m0-characterization-20261121/summary.json), [ownership map](../evidence/m0-characterization-20261121/ownership-map.json), [original/derivative hashes](../evidence/m0-characterization-20261121/manifest.json). These derivatives are evidence, not reusable authorization.

Private raw originals remain under `output/m0-characterization/`: `20261121-manifest-before-001` (five-test failing baseline and pre-fix source), `20261121-manifest-after-001` (165-test selection, source/test snapshots), and `20261121-manifest-functional-001` (native trace, gate/tool results, screenshots, actual manifests and retained files). Baseline November 20 cohorts remain unchanged.

Executed argument forms from the repository root, using the existing compatible interpreter with `-B -X utf8`:

```powershell
python -B -X utf8 scripts/m0_manifest_checks.py --output-dir output/m0-characterization/20261121-manifest-before-001
python -B -X utf8 scripts/m0_manifest_checks.py --adjacent --output-dir output/m0-characterization/20261121-manifest-after-001
python -u -B -X utf8 scripts/m0_manifest_functional.py --output-dir output/m0-characterization/20261121-manifest-functional-001
```

The baseline command ran before the production change. These output directories now exist; use NEW names for any authorized repeat. The shell's exact interpreter path is local-only, with version and source hashes in raw records. Browser executable selection changes only the diagnostic environment, not verification policy. `git diff --check` passed. No staged publication validation applies because nothing is staged or published.

## M. Summary for the Team

**Proposed PR title:** Preserve verified child manifest provenance across sequential edits.

**Why / fix:** parent aggregation inferred earlier-child symbols from later files/transaction state; retain a controller-owned per-result snapshot.

**Verification:** two baseline failures reproduced; 165 focused/adjacent tests passed after correction; fresh controlled chain preserves attribution, passes independent fixture interactions and clears the false parent ownership conflict. Root remains explicitly failed at the separate scope boundary.

**Next teammate handoff:** continue from this uncommitted branch and reviewed file list. Inspect the fresh failed root scope evidence, then review M1's source requirement -> child/parent -> artifact -> independent oracle -> current receipt design before changing acceptance policy. No model process is handed over. Preserve all source/evidence snapshots and use a new output directory for future runs.

**Publication:** no commit, push, PR, remote branch change, merge or rebase. Future publication and the independent-history integration concern remain subject to the user's explicit authorization.
