# R_UPDATE_<NNN> — <Descriptive title>

> Template only; this filename consumes no update number. Copy into a NEW numbered file only for one coherent, completed development update after the required verification succeeds. Inspect existing/reserved IDs first; never overwrite a record. Keep incomplete investigations in separate provisional notes. Replace every placeholder and use explicit `not applicable`, `not run`, `unknown` or `unverified` with a reason rather than implying success. Read [AGENTS.md](../AGENTS.md).

## A. Update Identification

- **Update ID:** R_UPDATE_<NNN>
- **Date and timezone:** <YYYY-MM-DD; timezone>
- **Title:** <Short descriptive title>
- **Status and verified scope:** <What has been completed and proven; controlled/live boundary>
- **Branch:** <Feature/fix branch>
- **Actual base revision:** <Commit used for the diff; how established>
- **Tested source revision/hashes:** <Commit and any uncommitted source identities>
- **Containing commit / PR:** <If available; otherwise pending, never a guessed future hash>
- **Related issue/experiment:** <Reference or not applicable>
- **Scope:** <Included work and important boundaries>

## B. Original Problem

- **Original request to Mini Hivo:** <Exact relevant request; remove private data>
- **Expected behavior:** <Observable postconditions>
- **Observed behavior:** <Actual filesystem/application state, not just model output>
- **Execution evidence:** <Run identity; relative link; relevant sanitized excerpt>
- **Failure boundary:** <Earliest observed stop; distinguish downstream symptoms>
- **Reproduction before the change:** <Command/scenario and result, or explain why unavailable>

## C. Why the Update Was Necessary

<Explain user impact and what was broken, incomplete or unreliable. State why the former behavior was unacceptable without overstating how widely it occurred.>

## D. Root Cause Analysis

<Trace the original execution path through the affected modules/functions. Explain where it diverged and what evidence establishes causality.>

| Finding | Classification | Supporting evidence | Remaining uncertainty |
|---|---|---|---|
| <Cause or hypothesis> | <Proven cause / observation / hypothesis> | <Relative link or code reference> | <Gap or none established> |

## E. What Changed

| File / function | Before behavior | Implementation change | After behavior | Evidence / test |
|---|---|---|---|---|
| <Relative source path and symbol> | <Supported by base diff or labeled historical record> | <Precise correction> | <Intended/observed, clearly labeled> | <Relative link> |

<List architecture, dependencies, test and configuration changes. Separate new code from pre-existing functionality and copied/generated evidence. Do not invent pre-fix source or attribute an existing module to this update.>

## F. How the Fix Works

<Explain the corrected request-to-result flow and interaction between modules. Describe the invariant/gate that prevents recurrence and how authorization, execution, rollback and verification interact where applicable. Use concise relative code links and symbol names.>

## G. Functional Verification

**Required:** demonstrate the claimed behavior with observable artifacts/state and an independent oracle. A unit-test pass, completion message, process exit or generic verifier PASS alone is insufficient. For documentation-only work, explain the relevant structural/integrity checks and why runtime functionality is not applicable; do not claim an implementation fix.

| Scenario / test | Verification class | Scripted/mocked boundaries versus real components | Expected behavior and oracle | Actual observed artifact/state | Result | Evidence |
|---|---|---|---|---|---|---|
| <Positive reproduction of original failure> | <Unit / integration / controlled functional / live-model E2E> | <Exactly what was replaced and exercised> | <Independent assertion> | <Measured observation> | <Pass / fail / blocked / unverified> | <Relative link> |
| <Relevant invalid/unauthorized case> | <Class> | <Boundaries> | <Operation denied; state unchanged, etc.> | <Observation> | <Outcome> | <Relative link> |

For each scenario record:

- **Run date, ID and source identity:** <Fresh or historical; commit/hashes>
- **Fixture/authority/policy:** <Relevant identities and approved scope>
- **Exact reproduction command:** <From repository root; environment prerequisites>
- **Verification method:** <Direct readback, independent behavior/state assertions, etc.>
- **Before versus after:** <Which original postcondition changed and what proves it>
- **Known verification gaps:** <Untested behavior and limitations of the oracle>

For literal file creation, include:

- Requested filename and expected resolved repository/workspace-relative path.
- Expected content/encoding/newline rule and expected bytes or digest.
- Evidence that the real file exists at that path, actual bytes/digest and comparison.
- Proof that verification read the actual artifact and unauthorized/wrong-content cases fail.

**Live-model completion:** <Verified with a fresh approved live run / not run / failed / blocked / unverified, with evidence and reason>. Scripted model responses establish only the declared controlled behavior. Ask for approval before costly live-model execution.

## H. Additional Successful Tests

Keep additional regression passes distinct from the direct functional proof above. Link actual logs. Record only successful invocations here; record failures and excluded/skipped coverage in section I. Do not copy old counts as new results.

| Suite / verification class | Fresh or historical; source revision | Exact command | Tests run | Passed | Failed / errors | Skipped | Exit / result | Relevance | Evidence |
|---|---|---|---:|---|---|---|---|---|---|
| <Suite name> | <When and what code> | <Reproducible command> | <Observed> | <Observed or unknown> | <Separate counts> | <Observed> | <Observed> | <Why relevant> | <Relative log link> |

<Explain overlap between suites. Do not sum them as unique coverage, equate discovered with executed tests, count skips as passes, or derive passes by subtracting subtest/error records. Use unknown when the retained output cannot establish a requested count.>

## I. Regression and Compatibility Impact

- **Potentially affected functionality/dependencies:** <List relevant behavior>
- **Preserved behavior:** <Evidence-backed compatibility checks>
- **Baseline comparison:** <Same source/fixtures/policies where reliable; no unsupported causal attribution>
- **Failures/errors:** <Exact outcomes, earliest cause and relative logs>
- **Skipped/excluded/interrupted checks:** <Names, reasons and coverage lost>
- **Untested/uncertain areas:** <Including final-source broad regression status>
- **Environment versus implementation:** <Evidence-based classification; do not automatically blame missing fixtures or environment for every assertion failure>

<Do not change assertions, replace authentic historical evidence or relax authorization merely to obtain green results. If broad discovery can call a live model, inspect and handle that boundary before running it.>

## J. Overall Impact

<State supported improvements in reliability, functional correctness, authorization, verification, execution safety, diagnostics and user-visible behavior. Address only dimensions supported by the diff and evidence. Explain the observed scope rather than claiming universal success.>

## K. Remaining Limitations

- <Unresolved issues and known failures>
- <Incomplete functionality and unverified live-model behavior>
- <Verification exclusions/oracle gaps and missing authentic fixtures>
- <Additional recommended checks and whether they need live-execution approval>

<If these gaps prevent the declared fix from being functionally established, keep the work provisional instead of publishing it as a completed successful fix. A controlled-only completion must say so explicitly.>

## L. Evidence and Reproduction

| Relative evidence link | Fresh / historical / sanitized derivative | Source/run identity | What it proves | What it does not prove |
|---|---|---|---|---|
| <[Descriptive label](../evidence/<update>/<artifact>)> | <Classification> | <Commit/run/hash> | <Specific claim> | <Boundary> |

```powershell
# Repository-root commands; substitute actual verified invocations and prerequisites.
# Do not leave placeholder commands in the completed record or rerun a costly live batch without approval.
```

- **Original preservation:** <Where private raw evidence is retained; use a safe logical location, not a personal absolute path>
- **Sanitization:** <Redactions/omissions and how outcomes/provenance were preserved>
- **Hash policy:** <Original byte hashes versus sanitized derivative hashes; canonical line-ending policy>
- **Actual staged-blob verification:** <Command/method and observed result where publication hashes apply>
- **Reproduction limits:** <Unavailable historical data or unreproducible original command, honestly stated>

Keep secrets, personal absolute paths, private request content, host inventories and runtime databases out of public documentation. Use a new run directory rather than overwriting evidence. Never imply that current-tree cleanup erased previously public history.

## M. Summary for the Team

**Proposed PR title:** <Concrete behavior/problem>

**Why needed:** <Original problem and impact>

**What changed / what was fixed:** <Main implementation changes and established behavior>

**Functional verification:** <Scenario, real oracle, observed result, controlled/live boundary and relative evidence link>

**Additional successful tests:** <Relevant suites, observed counts and links; separate from functional proof>

**Remaining issues:** <Failures, skips, incomplete behavior and unverified live execution>

**Publication state:** <Local/uncommitted, committed or pushed; only actual actions. Explicit authorization is required for each update's commit, push and PR actions.>
