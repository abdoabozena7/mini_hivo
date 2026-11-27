# R_UPDATE_007 — Require canonical source ownership before greenfield dispatch

## A. Identification

RO-001, 2026-11-21 Africa/Cairo. VERIFIED within controlled planning/accountability scope; not behavioral or root certification. Branch `rodina/dev-turn-2026-11-20`, HEAD/base `ef08b09708a295d5765d4c207141aa8a11d85f72` plus preserved local corrections 004–006. 007 was unused; containing commit/PR none. Source hashes: [reviewed evidence](../evidence/acceptance-phase-20261121/ownership.json). User approved the requirement/oracle/read-only parent design before this phase. Historical design/report wording remains unchanged.

## B. Original problem

Ordinary canonical greenfield decomposition accepted an HTML/CSS-only plan without complete requirement accountability. A file or behavior could disappear between source ledger and child dispatch. Baseline tests exercise the real `decompose_task` and scheduler seam with scripted planner data. Corrected baseline: eight methods, eight failures, zero errors/skips. No model call occurred.

## C. Why necessary

Child shape, dependency order and completion prose do not establish who implements each source duty. The parent must retain its complete obligation set; merely assigning a requirement to parent verification must not conceal an unimplemented source file.

## D. Root cause

The ordinary `children_schema` and post-planner path carried goal/done_when/scope/dependencies but no mandatory canonical ID partition. Approved-plan allocation belonged to a different route and was not activated by canonical NEW_PROJECT decomposition. Fallback and injected child dispatch could bypass a planner-only check.

## E. Exact changes

- New `hivo/requirement_ownership.py`: immutable hashed allocation derived from the existing canonical ledger. Reject absent/unknown IDs, unowned supported explicit file artifacts, missing concrete child scope and scope outside an explicit outer mutation boundary. Parent-only ownership is insufficient for source files needing implementation.
- `mini.py`: conditional ordinary-greenfield schema/prompt fields `requirement_ids` and `parent_requirement_ids`; post-planner allocation validation before creating children; propagation of child IDs; fresh dispatch-seam validation; explicit failed result on an invalid allocation rather than unbound leaf fallback. Nested bound tasks use their assigned subset. Existing approved execution-contract routes retain their own validation.
- Reuse existing concrete-path checks and canonical hashes; normalize outer scope paths using the existing resolver and platform case rules. IDs do not authorize writes or certify behavior.
- New focused tests, `scripts/acceptance_phase_checks.py`, `scripts/acceptance_phase_functional.py`, reviewed evidence and this report. Existing diagnostic scripts/reports/evidence were preserved.

## F. Mechanism / alternatives

Canonical ledger -> explicit owner allocation -> validate paths and coverage -> freeze/hash -> materialize scoped children -> validate actual children again before dispatch. Invalid allocation returns `REQUIREMENT_OWNERSHIP_INCOMPLETE`; it cannot silently become an unbound Worker. Missing allocation is an explicit incomplete planning outcome, not an automatic permission expansion.

Keyword-matching completion prose was rejected because it can manufacture coverage. Assigning every duty to the foundation would certify downstream work prematurely. Reusing an approved existing-project authority object without its approval lifecycle would misrepresent authority. This first increment establishes accountability only; independently executable obligations follow separately.

## G. Direct functional verification

`20261121-ownership-functional-003`: real scheduler, mission/context/impact guards, filesystem writes/edits, transaction commit/rollback, dependencies and Chromium; scripted planner/role choices and no provider HTTP. Counter foundation creates HTML/CSS/companion JS under its assigned paths. Functional successor inspects predecessor files and modifies JS only. Both children accepted. Independent actual click increments rendered count and reload preserves state. Allocation covers all three source IDs. Parent still FAILED at `INTEGRATION_FAILURE` / `IMPACT_CONTRACT_INCOMPLETE`: named greenfield artifact has no safe authorized path. No successful root claim. All five diagnostic assertions true, process exit 0. Independent behavior is compatibility evidence for this fixture, not proof the old generic acceptance rules enforce it.

## H. Additional tests

Final R007 cohort: **86 passed, zero failures/errors/skips**, exit 0, treatment-002; nine ownership methods plus affected/adjacent repair-cycle, scope, manifest, browser-dependency, Windows path and verified-child integration tests. Intermediate treatment-001 passed 85 before adding the outer-path normalization control. Counts overlap and are not additive. Final unit source includes outer-path normalization; functional-003 source hashes are separately retained and precede that path-alias hardening.

## I. Failures / compatibility

Baseline-001 had seven assertion failures and one harness error (missing scheduler callback arguments). Baseline-002 corrected only the harness and reproduced eight assertion failures. Functional-001 failed on a callback signature; functional-002 reached the parent but stopped at the intentionally blocked unscripted model seam. Functional-003 scripts that role too and retains the real failed parent outcome. None is reclassified as success. Existing scope/repair/provenance checks pass; broad discovery and live inference were not run.

## J. Overall impact

An ordinary canonical greenfield split cannot dispatch a supported explicitly named file or source requirement without accountable allocation. Writes still require all existing mission/context/impact authority. Allocation does not imply semantic completeness or executable proof.

## K. Limitations

Behavioral oracle binding, legacy proof freshness and read-only parent acceptance are the next approved increments and remain unresolved at this checkpoint. Noncanonical legacy fixtures retain compatibility; normal ingestion emits the canonical ledger. Supported explicit-file recognition uses existing source suffix capabilities, not arbitrary dotted API names. Unsupported meanings and semantic adequacy cannot be inferred from IDs. A coupling refinement that loses requirement metadata fails closed at dispatch; no permission is inferred to recover it. No complete root or live-model application was verified.

## L. Evidence / reproduction

[Curated ownership evidence](../evidence/acceptance-phase-20261121/ownership.json). Private raw cohorts under `output/acceptance-phase/`; source/starting status and 216 preservation hashes under start-001. Exact commands used checkout Python 3.14.8:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/acceptance-phase/20261121-ownership-treatment-002 test_greenfield_requirement_ownership test_repair_cycle_001 test_run4_scope_regression test_verified_manifest_provenance test_browser_dependency_freshness test_manifest_path_identity test_verified_child_integration
.\.venv\Scripts\python.exe -u -B -X utf8 scripts/acceptance_phase_functional.py --output-dir output/acceptance-phase/20261121-ownership-functional-003
```

Directories are exclusive and now exist; use new names for replay. Browser ran in the permitted native-process environment. Raw source hashes and outcome identities remain private/curated as indicated; no staged Git-blob claim because nothing is staged. Failed preliminary logs are preserved.

## M. Team summary

Proposed future PR title: Require canonical source ownership before greenfield child dispatch. Full ledger accountability and concrete file ownership now gate ordinary decomposition/dispatch without granting mutation permission. Eight baseline failures corrected; final 86-method cohort and real controlled counter child progression pass within declared scope. Parent remains failed; behavior enforcement and read-only final acceptance remain separate approved work. Local/uncommitted only; no commit, push, PR, remote, branch or history change.
