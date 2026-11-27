# R_UPDATE_013 — Discover and validate the controlled browser without historical runs

## A. Identification
2026-11-27, Africa/Cairo. VERIFIED for browser selection/startup and controlled integration. Branch `rodina/dev-turn-2026-11-20`; base `ef08b09708a295d5765d4c207141aa8a11d85f72` plus prior uncommitted work. No containing commit/PR. [Evidence/source identities](../docs/worklogs/rodina/2026-11-27_browser-harness-portability/results.json).
## B. Original problem
The harness unconditionally read a browser executable from private historical m0 output. A clean checkout without that result could not select its browser.
## C. Why necessary
Reproduction must depend on an explicitly selected or discovered installed browser, not another developer's private evidence directory.
## D. Root cause
`provider_controller_functional.py::main` deserialized the historical provenance path before building the controlled fixture. A pre-change structural contract test failed1/1; no old project was regenerated to reproduce this source dependency.
## E. Changes
New standard-library `scripts/browser_selection.py`: explicit override, installed Playwright bundle, PATH, then standard installed Chrome/Edge locations; validate file usability and actual headless Chromium protocol launch/version. Invalid explicit overrides never silently fall back. Harness adds --browser-executable, unique browser-provenance output, source hashing for the helper, and fail-fast unavailable status before provider construction or project creation. New focused tests. No browser/package installation.
## F. Mechanism
Resolve -> launch validation -> close validation instance -> retain exact path/source/version provenance -> unchanged real browser verification per child/parent. A path alone is not compatibility proof. Missing browser, driver, incompatible executable or cleanup failure cannot become READY. Actual application behavior still requires independent checks.
## G. Functional verification
Explicit installed Chrome override: real startup validation then controlled working chain at4096/1024, both children and read-only parent/root done; independent increment and reload persistence true. All source hashes unchanged during execution. Independent audit passes29 packets, maximum2661 estimated input. Automatic discovery independently selected an installed-location browser and validated version158.0.8127.88. Invalid explicit path: nonzero shell exit1, BROWSER_UNAVAILABLE, provider_requests0 and no workspace. Unit main-return contract is2; the PowerShell host reported failure status1. No false successful application is recorded.
## H. Additional tests
12 focused methods pass, zero failures/errors/skips, exit0. Includes explicit valid/invalid overrides, bundle/PATH/installed-location discovery with no historical file reads, absent browser, actual selected-path/version recording through a mocked launcher, incompatible launch, missing version, cleanup failure and harness refusal before provider/project work.
## I. Failures and compatibility
Baseline1 method failed because the source retained the historical dependency. Earlier11-pass cohort retained, not summed. Source helper validates only declared Chromium-compatible engines; other browsers require reviewed support. Explicit executable is operator-controlled. Default discovery does not install anything. No claim of real Linux/macOS browser validation; those paths are limited discovery support.
## J. Impact
Fresh-checkout reproduction no longer needs a private browser-provenance result. Actual browser provenance and functional checks remain separate and required.
## K. Limits
Existing Playwright and a compatible installed browser are prerequisites. This is scripted-provider controller proof, not local-model/cloud/hybrid E2E. Optional provider policies and locked rules are unchanged.
## L. Evidence and reproduction
Private roots: `output/prioritized-handoff/20261127-phase-c-{baseline-001,unit-001,unit-final-001,missing-browser-001,controlled-001,discovery-001}`. Actual executable path is retained privately in browser-provenance.json; curated JSON keeps selection source/version and exact source hashes. No staged-blob/publication claim.
```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/prioritized-handoff/20261127-phase-c-unit-final-001 test_browser_selection
.venv/Scripts/python.exe -B -X utf8 scripts/audit_worker_packets.py --run-dir output/prioritized-handoff/20261127-phase-c-controlled-001
```
The controlled invocation also supplied --browser-executable with the installed path recorded in private provenance. Portable reproduction may omit that option for discovery or supply another validated installed executable; always use a new --output-dir.
## M. Team summary
Proposed PR title: Validate and discover the controlled browser independently of historical evidence.12 methods plus actual Chromium startup/controller/browser proof pass. Builds On R011/R012 and the November27 audit. Rule Proposal: None. Local/uncommitted; no publication.
