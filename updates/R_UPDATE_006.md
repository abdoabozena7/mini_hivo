# R_UPDATE_006 — Preserve manifest history across Windows path-case aliases

## A. Identification

Issue MP-001; 2026-11-21, Africa/Cairo. **VERIFIED within Windows controlled manifest scope**, uncommitted/unpublished. Branch `rodina/dev-turn-2026-11-20`; HEAD/base `ef08b09708a295d5765d4c207141aa8a11d85f72`, plus preserved R_UPDATE_004 and R_UPDATE_005 local corrections. Number 006 was unused after 001 reserved and 002–005 allocated. Source identity: [evidence](../evidence/manifest-path-identity-20261121/summary.json). No containing commit/PR.

## B. Original problem

The preliminary receipt-freshness cohort ran 100 methods, with three manifest failures and no errors/skips. A workspace-local temporary directory passed the same affected tests. Treating this as only a sandbox nuisance was insufficient: resumption investigated the discrepancy instead of discarding the failed run.

## C. Why necessary

Identical existing Windows files can be referred to with different letter casing. Missing a transaction's original snapshot corrupts introduced-versus-modified attribution and can weaken parent conflict detection. Test-environment consistency alone would hide this production lookup defect.

## D. Root cause

`_transaction_capture` stored the caller's string as a map key. `mini.py::_manifest_from_result_source` resolved the file path and performed `previous_files.get(str(path))`. In the observed sandbox, the stored package-directory spelling contained lower-case `openai.codex`, while resolution returned `OpenAI.Codex`. Filesystem reads succeeded, but the Python string-key lookup failed. Because `previous_files` was nonempty, the source-inference fallback did not classify newly introduced symbols. This explains the three original failures. The `#!sandbox` text itself was not demonstrated to be the cause.

`path-key-baseline.json` proves exact-key lookup false and normalized-key lookup true for the same file. A portable-on-Windows case-alias control reproduced the problem in workspace-local temporary storage too: **three methods, one pass, two failures, no errors/skips** (`path-baseline-002`). Thus this is a genuine manifest path-identity defect exposed by environment spelling, not universal test failure or missing source content.

## E. Exact changes

- `mini.py::_manifest_from_result_source`: retain the exact-key fast path, then locate the first matching snapshot using `os.path.normcase(os.path.realpath(...))` when that lookup is missing. Preserve earliest captured pre-edit state. No transaction content, write permission or historical result is rewritten.
- `tests/test_manifest_path_identity.py`: Windows controls for new-file attribution, modified-versus-new symbols and rejection of an unrelated file's snapshot.
- Add that module to the existing scoped offline runner. New reviewed evidence and this independent report. The R_UPDATE_004 controller-snapshot correction remains intact.

## F. Mechanism and alternatives

The resolved file identity and stored transaction-key identity are compared using the operating system's path normalization. Windows case aliases match; distinct full paths do not. Existing exact matches remain unchanged. On case-sensitive platforms normcase does not turn distinct file names into equivalent ones. Restricting this correction to manifest lookup avoids changing the transaction's capture/rollback contract. Broadly lowercasing every path or modifying global transaction keys would have wider consequences and was unnecessary for this reproduced boundary.

## G. Direct verification

- Real disposable filesystem transactions with upper-case `APP.JS` capture and lower-case `app.js` access reproduce the old miss. Treatment identifies `render` as introduced for creation, modified for replacement, and `added` as newly introduced. An unrelated `other.js` snapshot cannot supply prior history.
- Original default sandbox temporary environment: **eight methods passed**, zero failures/errors/skips, including all five original manifest tests and the three new path controls. This closes the original environment ambiguity for the measured cases.
- Fresh real controlled chain `20261121-chain-002`: both children accepted; independent add/toggle/delete/reload controls pass; foundation attribution remains unchanged; no false duplicate owner; successor artifacts remain retained. All six diagnostic assertions true. Scripted role/planning choices; real tools, transactions, authorization and Chromium. Actual root remains FAILED at the separate impact-scope boundary.

## H. Additional tests

Final cohort for this correction: **205 passed, zero failures/errors/skips**, exit 0, `20261121-checks-005`. Nine modules, including the 14 freshness controls and original manifest/architecture/integration/repair/verification suites. Counts overlap previous cohorts and are not additive.

## I. Failures and compatibility

The initial baseline command discovered eight methods because a fixture class was directly imported into the new module; that preserved result includes five existing methods and two failing new controls. The import was changed to a module reference before the three-method baseline, avoiding duplicate discovery. Neither result was discarded. Broad suite discovery, non-Windows execution and arbitrary filesystem aliases remain NOT TESTED. Windows-only tests explicitly skip elsewhere.

## J. Impact

Manifest inference now tolerates real Windows path-case aliases without importing a sibling file's history. No claim is made about all filesystem alias combinations. No host, model, authority or mutation-policy setting changed.

## K. Limitations

The correction addresses initial source attribution lookup, not durable recovery of historical transactions. Missing snapshots remain missing. It does not broaden the accepted scope of R_UPDATE_004 or close ordinary requirement/oracle coverage, native module syntax handling, parent impact scope, legacy stale receipts or live-model validation. Full root acceptance is not demonstrated.

## L. Evidence and reproduction

[Reviewed summary and original hashes](../evidence/manifest-path-identity-20261121/summary.json). Original results, source snapshots and failing logs remain under `output/resume-engineering/`, including path-baseline-001/002, checks-005 and chain-002. Default-temp observations and diagnostics are in 20261121-001; raw machine paths remain private. Prior reports, M0 evidence and V001 remain unchanged.

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/resume_engineering_checks.py --output-dir output/resume-engineering/20261121-checks-005
.\.venv\Scripts\python.exe -u -B -X utf8 scripts/m0_manifest_functional.py --output-dir output/resume-engineering/20261121-chain-002
```

Commands above were executed using Python 3.14.8. Use new directory names for future repeats. Provider entry points were blocked. Hashes identify tested source/retained originals, not staged blobs; nothing was staged. Default-temp treatment also ran the eight named path/manifest methods through unittest with its unmodified default temporary root; exact raw command/probe results are retained locally.

## M. Team summary / future PR text

**Title:** Match manifest transaction snapshots by filesystem identity.

**Why/result:** Windows path casing caused an exact dictionary lookup to lose source history. A normalized fallback preserves attribution while keeping full-path separation. Two focused failures reproduce the defect; original sandbox treatment passes eight methods; workspace-local cohort passes 205; the real controlled child chain preserves provenance and retained behavior. Root impact scope remains failed and live testing remains blocked/unverified. No commit, push, PR, branch/remote change or history operation performed.
