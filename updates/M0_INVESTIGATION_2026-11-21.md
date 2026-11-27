# M0 acceptance characterization and manifest provenance investigation

## A. Update Identification

Provisional development-turn record, started November 20 and resumed November 21, 2026 (Africa/Cairo). Branch: `rodina/dev-turn-2026-11-20`. Base: `ef08b09708a295d5765d4c207141aa8a11d85f72`. Update 004 is now allocated only to the verified manifest correction; 001 remains reserved and 002/003 are preserved. The broader M0/M1 effort remains ongoing. No commit/publication is authorized. V001 and all inherited reports remain unchanged.

This record follows [the A-M template](UPDATE_TEMPLATE.md) and [V001](../MINI_HIVO_DEV_JOURNAL/V001_Development_Status_Roadmap.pdf), M0 sections 10-11 and decision rule 21. Component statuses and verification below distinguish investigation from implementation.

## B. Original Problem

Tasneem's accepted foundation does not establish accepted functional successors or final parent acceptance. The original fixture remains [the byte-preserved prompt](../tests/fixtures/new_application_requirements.txt), SHA-256 `2132536fd2df4a18c39f434dc43e4344034ed892c8640e94a98a103a82dd5b36`. M0 must distinguish structural loading, syntax, actual behavior, child obligations and complete parent obligations without weakening gates.

## C. Why the Update Was Necessary

An application must not be considered complete solely because its files load. Sequential edits must preserve accurate ownership and predecessor behavior. Missing evidence must remain explicit rather than disappear between child and parent.

## D. Root Cause Analysis

### Component M0-A: behavioral coverage — diagnosed, implementation deferred

Canonical baseline `output/m0-characterization/20261120-canonical-005` contains two real scheduler/leaf/parent chains and nine native-browser versus independent-DOM cases. Role replies and decomposition were scripted; compiler validation, tools, authorization, transactions, gates and Chromium were real. The source contract was constructed using production normalization and retained all 11 source IDs.

The feature child with an inert script was accepted after genuine Node syntax verification. Independent Add failed. The child route required JavaScript syntax but classified browser verification as not applicable; separately requested browser loading also passed with no required interactions. Generic web profile checks did not encode the assigned add/toggle/delete/persistence obligations. The later-edit control `20261120-regression-001` independently passed before an authorized edit removed Delete, then failed Delete afterward, while the real child returned `done`.

This establishes child-level inadequate behavioral acceptance. It does not establish a false successful root verdict. The inert chain's parent stopped at `IMPACT_CONTRACT_INCOMPLETE`, and the functional chain stopped at the manifest conflict described below. Generalized correction requires requirement-to-owner/artifact/oracle bindings, preserving downstream duties at the parent and fail-closed unresolved coverage. This changes acceptance-policy construction and requires a separately reviewed design before production implementation.

### Component M0-B: shared-file manifest provenance — implemented and controlled-verified

`chain_full/manifests-before-parent.json` records foundation `introduced_symbols=[]`; the successor introduces `input`, `list`, `empty`, `tasks`, `save`, `render`, `li`, `check`. `parent-preflights.json` shows aggregation assigning those same symbols to BOTH children, then rejecting `duplicate_child_symbol`. The final fixture passed the independent interaction oracle. Integration repair was deliberately stopped at unscripted mission compilation, so its final `ORCHESTRATION_FAILURE` is a diagnostic boundary, not an observed failed model repair.

Source trace: `aggregate_task` calls `attach_verified_manifest` again. `_manifest_from_result_source` treats empty manifest fields as missing and reads current files against global `LAST_COMMITTED_TRANSACTION`. For the earlier foundation, those now describe the successor. This changes historical attribution and creates a false duplicate-owner conflict. Five focused tests on the unchanged base produced **three passes and two failures**: empty foundation symbols and historical modified-symbol attribution changed after a successor transaction. Raw baseline, exact failures and pre-correction source are in `20261121-manifest-before-001`.

Proposed minimal correction: preserve a controller-owned per-result manifest snapshot at first attachment, reuse it only for that task, and return copies on later attachment. Do not trust an empty model-provided manifest as that snapshot. Keep current-file syntax/conflict scans and genuine duplicate-owner rejection active. This corrects provenance rather than broadening mutation permission or waiving a conflict gate.

Treatment completed: [R_UPDATE_004](R_UPDATE_004.md) records the isolated production correction, five original checks and 165 passing affected/adjacent methods. Fresh `20261121-manifest-functional-001` preserves the foundation manifest and produces parent preflight PASS with zero conflicts. Both children and independent fixture interactions pass, while root still fails at its separate incomplete scope boundary. No root completion is claimed. The next component remains deferred rather than silently bundled into this fix.

### Component M0-C: ownership completeness and freshness — diagnosed gaps

`20261120-controls-002/coverage-probe.json` records an ordinary decomposition that omits JavaScript and all functional duties yet passes the real shape validator. The current ordinary schema carries goals, completion prose, scopes and dependencies, but lacks a mandatory source-ID coverage partition. This is an accepted incomplete plan, not a completed root or proof that a real model will always omit work.

The canonical direct legacy `evidence_gate` probe accepted old receipts after an out-of-band runtime-error edit. This is a narrow gate/freshness limitation, not an end-to-end accepted stale transaction: no new root verdict or commit was fabricated. Existing wrong-target, unavailable-receipt and dependency controls passed separately.

## E. What Changed

Before resumption: untracked `scripts/m0_characterize.py`, `scripts/m0_controls.py`, `scripts/m0_followup.py`, an ignored file-control script, private run artifacts and the existing local handoff note. No tracked production diff existed.

Resumed work adds this provisional record, focused manifest tests, offline validation runners and the isolated correction recorded below. No inherited documentation is edited.

Final resumed production delta: only `mini.py::attach_verified_manifest`, ten inserted lines and one replacement. New component report: `R_UPDATE_004.md`. Reviewed portable observations and ownership mapping: `evidence/m0-characterization-20261121/`. Additional new runner `scripts/m0_manifest_functional.py` verifies the real controlled chain; all remaining new scripts are diagnostic-only.

## F. Mechanism and Ownership Contract

The controlled ownership map uses foundation child 1, feature child 2 and ROOT. It is a review map, not a claim that the runtime emitted enforceable bindings:

| Source ID | Accountable owner | Artifact / scope | Required independent proof / parent duty |
| --- | --- | --- | --- |
| REQ-001 complete app | ROOT | All three files | Complete current behavioral/integration coverage; unverified root |
| REQ-002 named files | 1 creates, 2 edits JS, ROOT checks | 1: HTML/CSS/JS; 2: JS | All files retained, correct linkage, authorized scopes |
| REQ-003 input/list/Add UI | 1; ROOT | HTML/CSS | Visible accessible controls; presence alone is not Add behavior |
| REQ-004 nonempty Add | 2; ROOT | JS consuming HTML | Submit adds one visible task; whitespace adds none |
| REQ-005 completion | 2; ROOT | JS/HTML state | Toggle on and off; preserve prior behavior |
| REQ-006 Delete | 2; ROOT | JS/list | Delete only selected task; later-edit negative control |
| REQ-007 persistence | 2; ROOT | JS/localStorage | Text and completion survive reload |
| REQ-008 empty state | 1 initial, 2 transitions; ROOT | HTML/JS | Empty/occupied transitions; full final transition coverage still limited |
| REQ-009 responsive interface | 1; ROOT | CSS/HTML | Desktop/mobile usability; probe covers narrow overflow only, not full visual quality |
| REQ-010 no external dependencies/backend | Both; ROOT | Entire artifact set | Source/resource audit; no exhaustive runtime enforcement demonstrated |
| REQ-011 HTML entry delivery | ROOT | index.html links style.css and app.js | Current linked files execute correctly, no runtime errors, retained final deliverable |

Actual dependencies: HTML references CSS and JS; JS queries HTML controls and owns rendered state; persistence depends on browser storage and reload. Child 2 declares dependency on child 1, reads accepted HTML/JS and has JS-only mutation permission. Dependency inspection does not authorize HTML/CSS edits. No other runtime files are required by this controlled plain-web fixture.

## G. Functional Verification

Canonical process exit was 0 for completed diagnostics, not application success. Foundation passed in both chains. Inert feature child passed while independent behavior failed. Functional feature child passed and its independent behavior passed; parent preflight falsely attributed successor symbols to both children. No successful root verdict exists.

| Browser fixture | Native browser | Independent behavior |
| --- | --- | --- |
| Functional | PASS | PASS under the recorded assertions |
| Placeholder / inert | PASS | FAIL |
| Missing referenced JS | FAIL | FAIL |
| Runtime exception | FAIL | FAIL |
| Missing Add | PASS | FAIL |
| Missing Delete | PASS | FAIL |
| Missing completion | PASS | FAIL |
| Missing persistence | PASS | FAIL |
| Existing but disconnected script | PASS | FAIL |

These known fixture variants and selectors are test-only. No To-Do-specific production rule was added. The separate later-edit case is seeded from byte-identical controlled output; it is not a resumed live run or fabricated predecessor receipt.

On resumption, the previously unexecuted missing HTML and CSS checks ran successfully as diagnostics: both native verifications returned false. The existing script retains its literal output directory name `20261120-files-001`; execution occurred November 21, with console output `20261121-files-001.console.log`. Missing HTML is a missing-entry failure; missing linked CSS is a browser resource failure. Neither is a root verdict.

## H. Additional Successful Tests

The prior canonical `20261120-controls-002` record contains **13 passed, zero failures/errors/skips**, newly executed then and reviewed now. It covers dependency propagation/blocking, snapshot refresh, scope restrictions, required impacts, controlled Python repair/commit/rollback, wrong-target evidence and unavailable-receipt handling. Its earlier repeated 13-method cohort is not added to this count. These controlled checks do not establish live JavaScript repair.

Fresh resumed manifest correction: **165 passed, zero failures/errors/skips** across five modules; separate fresh functional chain satisfies six diagnostic assertions while root remains failed. Two additional missing-file controls returned the expected native rejection. These measures are different denominators and are not summed. See R_UPDATE_004 for exact commands, source identities and scope.

## I. Failures and Compatibility Boundaries

- Preliminary chain-001 and boundary-003 lacked a required explicit JS syntax receipt; their rejection was correct and did not establish a functional defect.
- Observed-002 and syntax-004 include diagnostic errors on unscripted recovery/repair planning. Their logs and result files remain unchanged. Canonical-005 corrected diagnostic source representation and bounded planning stops; do not label earlier diagnostic errors as application passes.
- Original terminal outputs for the first probe were conversation-only; later canonical commands, console logs and native traces are retained locally. Earlier harness revisions were not all snapshotted, limiting exact replay of preliminary attempts. Final canonical provenance pins its harness digest.
- The reuse environment is Python 3.14.8 with an explicit existing Chromium executable, not Tasneem's Python 3.11 environment. No package/browser installation or model call occurred.
- The original sandbox browser probe stalled. Two surviving availability-probe processes were identified on resumption and stopped after command identity verification; no model/experiment/evidence-writing process was terminated.
- The previous missing-file command was not executed because automatic approval review hit a usage limit. This was a review-system failure, not an unsafe-action finding. Resumption used the normal approval path successfully.

## J. Overall Impact

M0 identifies separate behavioral coverage and provenance problems. Syntax/load success is weaker than behavior. Immutable child attribution must coexist with fresh parent verification; preserving historical manifests must not make old receipts sufficient for current output.

## K. Remaining Limitations

No live Ollama/cloud run, complete accepted root, full application certification or successful live Repairer mutation is demonstrated. Parent scope construction and generalized behavioral obligation binding remain separate work. Direct legacy stale-receipt acceptance is not evidence that every authority-bound route accepts stale bytes. The fixture does not validate arbitrary browser workflows or all qualitative requirements.

## L. Evidence and Reproduction

Private evidence root: `output/m0-characterization/` (ignored). Exact argv, source identities, model boundaries, native events, results, screenshots and retained workspaces are under the named cohorts above. Commands used the existing compatible interpreter with `-B -X utf8`. Completed runs are never overwritten.

Key runners: [characterization](../scripts/m0_characterize.py), [controls](../scripts/m0_controls.py), [later-edit control](../scripts/m0_followup.py), [manifest checks](../scripts/m0_manifest_checks.py). The missing-file probe remains in the ignored raw evidence root. A portable reviewed summary is added after verification; raw databases/host-specific transcripts remain local. Original fixture and historical evidence remain unchanged.

Reviewed summary now available: [observations](../evidence/m0-characterization-20261121/summary.json), [all 11 requirement responsibilities](../evidence/m0-characterization-20261121/ownership-map.json), [source and derivative hashes](../evidence/m0-characterization-20261121/manifest.json). The ownership map is authored review guidance, not a runtime-issued authorization or proof that mandatory coverage binding exists.

## M. Summary for the Team

Current stopping boundary: no successful root result; child behavioral acceptance remains insufficient. The reproduced false ownership attribution is corrected within the verified scope of R_UPDATE_004. The remaining parent scope failure is unchanged: `aggregate_task` constructs a greenfield impact candidate without a concrete root mission/assignment, so the existing guard rejects its empty safe mutation surface. No arbitrary root scope is inferred from a child's writes.

Next reviewed design decision: distinguish a controller-declared read-only parent verification pass from a separately authorized integration mutation/repair mission. In parallel, M1 must bind each source ID to child responsibility, file/dependency scope and a supported independent oracle; preserve the complete parent obligation set; bind receipts to current linked-file fingerprints; and keep unsupported or missing duties unresolved. Reuse existing requirement/coverage/routing contracts. A generic browser action/assertion adapter may be needed; fixture-specific selectors do not belong in production policy. Do not force an accepted root by bypassing the scope failure or replacing missing behavioral proof with syntax/load success.

These changes affect acceptance/authority construction and require the user's approval of the concrete design before production implementation. They are deferred, not silently combined with the provenance correction. No new live run is authorized.

Publication: local and uncommitted only. No push, PR, merge, rebase, remote update or historical report modification. Independent snapshot history remains as approved; no original ancestry was reconstructed.
