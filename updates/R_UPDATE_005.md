# R_UPDATE_005 — Include HTML resources in verified-receipt freshness

## A. Identification

2026-11-21, Africa/Cairo. Issue RF-001. **VERIFIED within controlled receipt-freshness scope**, not complete application acceptance. Branch `rodina/dev-turn-2026-11-20`; HEAD/base `ef08b09708a295d5765d4c207141aa8a11d85f72`. Existing uncommitted M0 manifest correction preserved. Containing commit/PR: none. Number 005 was unused after reserved 001 and existing 002–004. Source hashes: [reviewed evidence](../evidence/receipt-freshness-20261121/summary.json). Subsequent independent changes must retain their own source identity and report.

## B. Original problem

The existing Stage 5B receipt dependency derivation followed JavaScript imports, but not HTML script/stylesheet links. A browser receipt naming only `index.html` could remain fresh after its executable JavaScript changed. The original nine focused controls produced six failures, three passes, zero errors/skips. Parent readiness remained READY after a linked-script edit. This is a deterministic freshness defect; it is distinct from ordinary legacy-route behavior coverage.

## C. Why necessary

An unchanged HTML entry does not establish unchanged executable behavior. Linked resources must participate in the existing subject fingerprint without acquiring mutation permission. A stale receipt cannot establish readiness for parent verification.

## D. Root cause

`hivo/integration_gate.py::_read_local_imports` recognized JavaScript import syntax only. `derive_evidence_dependency_paths` therefore omitted HTML-linked resources unless another evidence field happened to name them. `create_verified_child_receipt` fingerprinted that incomplete set; `receipt_freshness` correctly compared only the recorded paths. The existing 120-path truncation also allowed a partial graph to issue a VERIFIED receipt: an added overflow control failed before its correction (14 methods: 13 passed, one failed, zero errors/skips).

## E. Exact changes

- `hivo/integration_gate.py`: parse HTML script sources and stylesheet/module-preload links with standard-library HTMLParser; resolve local base URLs, root/relative references, encoding and query/fragment components; exclude remote/data/navigation/commented references; reject resolved paths outside the workspace. Missing local resources remain recorded inputs. Existing JavaScript import traversal supplies transitive local-module coverage.
- Keep graph traversal at 120 paths, track incompleteness and issue an UNVERIFIED receipt with `EVIDENCE_DEPENDENCY_LIMIT_EXCEEDED` if traversal would overflow. No truncated graph is represented as a complete verified fingerprint.
- `tests/test_browser_dependency_freshness.py`: 14 focused positive/negative controls.
- `scripts/resume_engineering_checks.py`: bounded offline cohort with exclusive output directories and blocked shared provider entry points.
- `scripts/browser_freshness_functional.py`: real browser/receipt/readiness comparison against preserved baseline code, using a counter fixture rather than application-specific production logic.
- This report and sanitized evidence. No mutation scope, approval policy, model setting or host threshold changed.

## F. Mechanism and alternatives

Evidence names the HTML entry; bounded derivation follows its executable/style links, then existing local imports. The resulting files and missing-file states enter the same canonical fingerprint already used by child receipts. Later changes invalidate readiness through the existing stale-evidence gate. An overflow returns an unverified receipt instead of expanding the safety bound or silently losing inputs.

Alternatives rejected: fingerprinting the entire repository would overinvalidate unrelated work; trusting only entry bytes misses behavior; guessing filenames or hardcoding To-Do handlers is not general; allowing a partial graph to certify freshness is unsafe. This change derives evidence dependencies only and grants no write access.

## G. Direct functional verification

Final controlled-browser run: `output/resume-engineering/20261121-browser-003`, exit 0, ten diagnostic assertions true. Chromium, Mini Hivo's native browser verification, filesystem reads/writes, receipt creation and parent readiness were real. Planned task/authority metadata was scripted. Test-driver corruption/restoration is not a Repairer run.

| Independent oracle / gate | Observed result |
|---|---|
| Initial native verification, increment button, visible output, reload persistence | PASS |
| Initial parent readiness | READY |
| Replace only linked app.js with inert code | Independent increment/persistence FAIL; clean-load check still PASS |
| Preserved pre-correction receipt | Incorrectly remains fresh, reproducing defect |
| Corrected receipt after same edit | Stale; parent readiness blocked by stale evidence |
| Restore functional fixture to different bytes, rerun browser/behavior, create fresh receipt | Behavior PASS; readiness READY |

The counter's classic-script fixture uses HTML, CSS and two JS files; browser actions independently inspect actual visible state and localStorage persistence. Artifacts remain in its isolated workspace. Final run hashes identify the exact tested source; it is not a live-model run or a root-acceptance demonstration.

## H. Additional tests

Final offline cohort: **202 passed, zero failures/errors/skips**, exit 0, `20261121-checks-004`. Eight modules cover the new 14 controls plus existing manifest attribution, adaptive architecture, verified-child integration, verification-outcome integrity, repair/scope, repair-cycle and browser-authority behavior. Module list and hashes are retained in the reviewed summary. Wrong-target, unavailable/malformed receipts and scope controls are included in these existing suites.

New controls cover HTML links, transitive imports, changed/deleted scripts, changed CSS, unchanged unrelated files, missing-file appearance, base/root/encoded URLs, external/data/commented/malformed/escaped references, cycles, literal URL metacharacters and overflow rejection. These tests use disposable workspaces and disclosed synthetic PASS records to test freshness; those records are not evidence that a missing resource passed real browser verification.

The earlier 197- and 198-method passing cohorts overlap this final cohort; do not add their counts. The preliminary 100-method run had three manifest failures, not universal success. A workspace-local temporary directory reproduced the earlier environment's passes. Further investigation identified an independent Windows path-case snapshot lookup defect, recorded separately rather than editing historical results.

## I. Compatibility and failed attempts

The first browser attempt (`20261121-browser-001`, exit 1) used a valid ES-module counter. Independent HTTP-served behavior passed, but native verification never reached Chromium: `source_validation_error` sent the module to `node --check -` in CommonJS mode, causing `Cannot use import statement outside a module`. Its receipt metadata was synthetic and does not establish native acceptance. The corrected diagnostic asserts native PASS before issuing any success receipt and uses classic scripts supported by that route. Original failed artifacts remain unchanged. This is a separate native module-verification limitation, not a repaired module-runtime claim.

`20261121-browser-002` passed the revised control; final 003 verifies the final source after URL/container/overflow hardening. Broad test discovery was not run. No optional policy was enabled or host preflight bypassed.

## J. Actual child, parent and root impact

A fresh existing production-controller chain (`20261121-chain-001`, exit 0 for diagnostics) accepted both foundation and functional child, passed independent To-Do fixture interactions, preserved original attribution, cleared the false duplicate-owner conflict and retained successor bytes. Parent preflight PASS had zero conflicts. **Actual root result remained FAILED**, `INTEGRATION_FAILURE` / `IMPACT_CONTRACT_INCOMPLETE`: no safe authorized parent mutation path. This ordinary greenfield route does not activate the corrected Stage 5B receipt gate, so the chain is compatibility/progression evidence, not proof that RF-001 fixes the legacy route.

## K. Remaining limitations

- This fixes HTML-linked dependency derivation for existing Stage 5B receipts; legacy direct `evidence_gate` has no equivalent mandatory subject binding. Old receipts are not silently migrated or refreshed.
- Clean-load/syntax checks still cannot certify promised interactions. Mandatory requirement-to-child/oracle allocation and full parent completeness remain unresolved.
- Static dependency discovery is bounded, not a general runtime dependency observer. Computed imports, CSS imports/resources, service workers and other dynamically loaded inputs require explicit dependency declarations or additional future support. External resources are not local fingerprint inputs; native browser errors must still fail on those routes.
- Exact original module fixture native syntax handling remains uncorrected in this report.
- No genuine Ollama call, live Repairer mutation or complete root-accepted application demonstrated. Live testing withheld: last cold host snapshot had roughly 7.45 GiB available, no resident model; the prior 7.10-GiB cold attempt left only 415 MiB after loading. Loaded headroom for larger role contexts is not established. This is a conservative eligibility decision, not a new measured host-preflight FAIL.

## L. Evidence and reproduction

[Reviewed summary and original-byte hashes](../evidence/receipt-freshness-20261121/summary.json). Private originals remain under `output/resume-engineering/`: 001 contains the original baseline, failed preliminary cohort, source snapshots and Windows case probes; checks-002/003/004 retain each passing cohort; browser-001/002/003 retain each browser attempt; chain-001 retains native controller traces and artifacts. Original M0 evidence hashes (13 records) matched on resumption. R_UPDATE_004, M0 notes, REPAIR_CYCLE_001 and V001 remain unchanged.

Commands actually used, from repository root, isolated checkout Python 3.14.8:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/resume_engineering_checks.py --output-dir output/resume-engineering/20261121-checks-004
.\.venv\Scripts\python.exe -B -X utf8 scripts/browser_freshness_functional.py --output-dir output/resume-engineering/20261121-browser-003
.\.venv\Scripts\python.exe -u -B -X utf8 scripts/m0_manifest_functional.py --output-dir output/resume-engineering/20261121-chain-001
```

These directories now exist; replays require fresh names. Browser execution used the existing Chromium executable and approved native-process execution environment. Provider calls were blocked. Raw artifacts retain local paths privately; reviewed derivatives omit host paths and transcripts. Hashes refer to original bytes or explicitly named derivatives, not staged Git blobs. Nothing is staged.

## M. Team / proposed future PR summary

**Title:** Include HTML-linked resources in verified child receipt freshness.

**Problem/result:** receipts could omit linked executable/style inputs; track those inputs and refuse graph-overflow certification. Preserve mutation boundaries. Real counter interactions and parent-readiness comparison reproduce the old false-fresh decision and verify rejection after the correction. Final offline cohort: 202 passes; real controlled child chain still fails honestly at root impact scope. Remaining work is mandatory owner/oracle allocation, legacy freshness, parent read-only-versus-mutation design, module syntax handling and safe live validation. Local, uncommitted and unpublished; no PR, remote, branch or history modification.
