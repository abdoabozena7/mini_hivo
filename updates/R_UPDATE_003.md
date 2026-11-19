# R_UPDATE_003 - Separate construction intent from application feature verbs

## A. Update Identification

- Date: 2026-11-18, Africa/Cairo.
- Scope/status: offline-validated project classification and Stage 2 routing; live rerun pending.
- Branch: `development`. Base: `667d6143e77b2494ee6e286d91ea73c53696eaa2`.
- Source identities/results: [curated verification record](../evidence/project-mode-intent/results.json).
- Containing commit/PR: none; local uncommitted changes. No publication authorized.
- This update does not change Worker behavior, mutation authority, verification or acceptance.

## B. Original Problem

The user asked Mini Hivo to build a new application. The opening directive was
“Build a complete, working To-Do List web application using plain HTML, CSS, and
JavaScript.” A later requirement said “Allow users to delete tasks.”

The unchanged [request fixture](../tests/fixtures/new_application_requirements.txt)
is copied byte-for-byte from run `20261118T101729-c6e86150`. SHA-256:
`2132536fd2df4a18c39f434dc43e4344034ed892c8640e94a98a103a82dd5b36`.

The saved run retained 11 requirements, but classified an empty workspace as
`EXISTING_PROJECT`. Reconnaissance returned `REPOSITORY_EMPTY`; Stage 2 failed
with `required existing-project repository evidence is unavailable`. No task
or Builder was created. Raw console, native JSONL and database remain LOCAL-ONLY.

## C. Why the Update Was Necessary

An application's requested delete/update/replace features are not by themselves
evidence that the user wants to modify an existing source repository. The wrong
route prevented an otherwise supported new-project request from reaching planning.

## D. Root Cause Analysis

`classify_project_mode` in [project_understanding.py](../hivo/project_understanding.py)
tested `_MODIFICATION_RE` against the entire request. The original prompt did not
contain the classifier's explicit greenfield phrases, so the feature verb `delete`
selected existing-project mode. `mini.prepare_stage2_context` then correctly
required repository evidence for that mode. The evidence gate was not defective
and has not been relaxed.

This is a source-supported deterministic cause, reproduced offline before the
production change. It is not attributed to the model, host preflight or browser.

## E. What Changed

- `hivo/project_understanding.py`: recognize an opening construction directive
  in a confirmed empty, non-truncated workspace. Existing/legacy targets,
  explicit source-file edits and separate fix/refactor/migrate instructions
  prevent this new interpretation. Meaningful existing source always takes precedence.
- `tests/test_project_mode_intent.py`: ten test methods covering construction,
  feature operations, metadata, mixed requests, inventory uncertainty, real
  existing source, missing existing targets and actual Stage 2 behavior.
- `tests/fixtures/new_application_requirements.txt`: exact original prompt.
- `evidence/project-mode-intent/results.json`: small curated results and hashes;
  no raw logs, databases or personal filesystem paths.
- This update record. No other production module changed.

## F. How the Fix Works

The classifier distinguishes the opening construction instruction from subordinate
feature verbs instead of letting any modification word override construction.
It does not contain To-Do-specific terms, filename exceptions or feature exceptions.

Existing source still selects `EXISTING_PROJECT`. A request to modify a missing
existing service still fails its required repository-evidence gate. The new branch
does not establish workspace emptiness from unavailable or truncated inventory.
The existing explicit-greenfield behavior remains unchanged.

## G. Functional Verification

Controlled functional checks use real temporary directories, production inventory,
classification, requirement extraction, Stage 2 and Task Brain creation. The
specification is supplied deterministically and both model entry points are
blocked; this is not live-model validation.

- Original request: `NEW_PROJECT`; Stage 2 returns `ready`; Task Brain retains
  all 11 source requirement IDs; source ledger remains unchanged. Existing-project
  scouting is prohibited by the test, and no application files are written.
- Populated repository: remains `EXISTING_PROJECT`; real reconnaissance returns
  directly observed evidence, remains read-only, and preserves original source bytes.
- Missing existing target: remains `EXISTING_PROJECT` and fails with
  `REPOSITORY_EMPTY`, preserving the evidence requirement.
- Unavailable/truncated inventories do not authorize the new construction shortcut.

Before the change, the initial nine-method reproduction reported eight failure
entries, including subtests. Test-harness assumptions about runtime metadata and
the Stage 2 event name were corrected before that recorded reproduction. The final
ten-method suite adds an inventory-safety check and further mixed-request controls.
All ten final methods pass; the two cohorts are not claimed to be identical.

## H. Additional Successful Tests

Fresh Python 3.11.9 results; suites are disjoint test-method cohorts:

| Suite | Test methods | Failures/errors/skips |
|---|---:|---|
| `test_project_mode_intent.py` | 10 | 0 / 0 / 0 |
| `test_project_understanding.py` | 32 | 0 / 0 / 0 |
| `test_ingestion_integration.py` | 10 | 0 / 0 / 0 |
| `test_greenfield_impact_lifecycle.py` | 17 | 0 / 0 / 0 |

Total: 69 passing methods, not 69 independent live scenarios. Production source
compilation also succeeded for `mini.py` and all `hivo` modules: 71 files.

## I. Regression and Compatibility Impact

The selected cohort protects existing reconnaissance, ingestion, source retention
and greenfield impact/mutation gates. No failures, errors or skips occurred.
Model calls were blocked throughout the cohort. Broad discovery was not run.
`git diff --check` passed. Runtime authorization and final acceptance code did not change.

## J. Overall Impact

The fixed request can reach Task Brain readiness without inventing an existing
implementation or bypassing existing-project evidence. This resolves the observed
pre-planning classification blocker within the verified scope.

## K. Remaining Limitations

Classification remains bounded deterministic language matching, not complete
natural-language understanding. Complex or differently phrased mixed requests may
need further evidence and tests. This patch does not address unrelated inventory
semantics or replace established explicit-greenfield rules.

Live specification, planning, Workers, browser behavior, recovery and final
application acceptance after this patch are NOT TESTED. The user will perform the
next live run with the original prompt. No application was manually implemented.

## L. Evidence and Reproduction

The fixture and [results JSON](../evidence/project-mode-intent/results.json) are
safe local source artifacts. Raw before/after test logs, the focused provider-blocked
runner and original-evidence integrity manifest are LOCAL-ONLY in the project's
separate validation area (`20261118-project-mode-001`). Original benchmark files
and hashes were checked unchanged; no historical evidence was overwritten.

From the repository root, using the existing Python environment:

```powershell
python -B -m unittest discover -s tests -p test_project_mode_intent.py -v
python -B -m unittest discover -s tests -p test_project_understanding.py -v
python -B -m unittest discover -s tests -p test_ingestion_integration.py -v
python -B -m unittest discover -s tests -p test_greenfield_impact_lifecycle.py -v
```

The recorded cohort used a local wrapper around these discoveries that patched
`mini.ask_ollama` and `mini.structured_model_call` to raise on any live call.
The new suite also blocks those entry points itself. Only the selected suites
were inspected/run; do not infer that all inherited tests are provider-free.
No files are staged; staged-blob publication validation is not applicable yet.

## M. Summary for the Team

**Proposed PR title:** Distinguish new-project construction from application feature operations.

**Why / fix:** preserve the meaning of the root construction request instead of
misclassifying it from a subordinate delete/update feature.

**Proof:** actual Stage 2 readiness with all 11 requirements retained; existing
repository and missing-target controls remain protected; 69 selected methods pass.

**Next action:** fresh isolated local benchmark with the byte-identical original
prompt. Retain logs, native traces, generated outputs and final verification.

**Publication:** uncommitted local changes only; no commit, push, PR or merge.
