# Repair Cycle 001 — Scoped mutations, bounded context recovery and dependency freshness

Sections 1–7 preserve the initial offline repair checkpoint. **Run 3 subsequently
exposed a scope-resolution regression in that checkpoint. Section 8 records its
correction and the Run 4 readiness assessment at that point.** In particular,
`scope_hint` must not be assumed to contain filesystem paths. Section 9 continues
the repair using assistant-operated real-model attempts after the user's Run 4.
**Attempt 7 subsequently reached verified child acceptance and retained files;
Section 9.5 records the actual live milestone and its limits.**

## 1. Baseline and scope

Work was performed locally on `development`, HEAD
`667d6143e77b2494ee6e286d91ea73c53696eaa2`, in
`E:\MiniHivo\el-samna-el-balady`. No commit, push, merge, dependency installation,
application implementation, browser session or live model benchmark was performed.
The existing uncommitted project-classification correction was retained unchanged.

Primary evidence is `E:\MiniHivo\el-samna-local-tests\todo-20261118-103737`.
Its native trace is
`workspace/.agent_runs/20261118T103839-6ffda1ba.jsonl`.
References to numbered trace lines below are JSONL line numbers, not SQLite event IDs.
The SQLite database contains 68 tool-event rows; these numbering systems differ.

The original prompt SHA256 is
`2132536fd2df4a18c39f434dc43e4344034ed892c8640e94a98a103a82dd5b36`.
The preserved prompt, shared benchmark prompt and existing classification fixture
have identical hashes. All 14 files in the primary evidence preservation manifest
were checked unchanged, including the database and its journal files.

## 2. Confirmed causes and corrections

### A. Impact Contract construction lost the assigned mutation surface

**Observed:** trace line 118 records task 1 failing with nine missing impacts and
three out-of-scope changes. Line 304 records task 2.1 failing with eight missing
impacts and two out-of-scope changes. Changed files included `index.html`,
`style.css` and `app.js`.

**Cause:** `_prepare_task_impact_contract` passed the root/effective contract to
`_impact_candidate_for_worker`, without carrying the greenfield child's assigned
paths. Without allowed mutation paths, `build_pre_mutation_impact_contract` fell
back to `_identifier_candidates`: ordinary words in the local goal became
required symbol impacts. The comparator then correctly rejected changes against
that incorrectly constructed contract. This is not evidence that comparison or
rollback should be disabled.

**Correction in `mini.py`:** for greenfield tasks without an explicit Impact
Contract or formal execution contract, compile bounded paths from the controller's
child assignment, falling back to the compiled mission's targets. Normalize paths
inside the workspace, reject protected metadata, respect an explicit outer
mutation boundary (including an empty boundary), and require a safe assigned
scope before mutation. Paths are compared using the runtime's existing case
normalization. Explicit required targets, preservation constraints, provenance
and verification obligations remain in force.

An allowed path is a permission boundary, not proof that a requirement was
implemented. It does not automatically mean every allowed file must change.
Explicitly required impacts still must be observed, and verification must still
satisfy the task. No observed Worker write is used to retroactively authorize
itself. An absent or unsafe assignment fails closed instead of authorizing prose.

**Evidence limit:** the historical trace retains target counts, but not the full
child scope/mission payload. It cannot prove that every historical write was
inside its intended assignment. The repair does not assume all three files were
legitimate for every child. Future `worker_mission_ready` and
`impact_contract_created` events now include bounded assigned targets and paths
so this distinction is observable.

### B. Context completion had acquisition, feedback and termination gaps

**Observed:** task 2.2 made 27 context decisions: three `REQUEST_EVIDENCE` rounds
with zero returned evidence, followed by 24 terminal `CONTEXT_INSUFFICIENT`
decisions. The three-round gate itself already had a bounded failure state.

**Causes:**

- Greenfield Workers had no formal execution contract and received an empty
  inspection path list. The resolver correctly treated explicit `[]` as no
  inspection permission; it could not read otherwise available task files.
- Requests for a file's definition were treated only as symbol searches. HTML
  or stylesheet source need not contain the requested language symbol.
- Insufficient-context re-anchoring appended new evidence after a long mission
  and then prefix-truncated the combined text. Newly returned evidence could
  disappear from the next model request.
- `execute_agent_task` did not stop when the gate returned its terminal failure.
  It continued asking the model, repeatedly consuming the remaining step budget.

**Corrections:**

- `prepare_worker_mission_context` retains the validated mission and changed
  paths from verified dependency summaries. `_prepare_task_impact_contract`
  builds bounded inspection paths from the assignment and dependency outputs,
  preserving explicit inspection restrictions. `execute_leaf` and `repair_task`
  pass this context to their gates. Permission to inspect a dependency does not
  authorize changing it.
- `hivo/semantic_evidence.py`, `SemanticEvidenceResolver._definition_candidates`:
  an exact file-definition request can return a current, bounded source excerpt
  from an already allowed file. This is not promoted to an authoritative API
  contract; unsupported contract claims remain unresolved.
- `execute_agent_task` preserves the original mission and sends the bounded
  context update as a separate message, avoiding prefix loss.
- A final `CONTEXT_INSUFFICIENT` result terminates the attempt immediately and
  records `context_terminal_stop`. No new authorization is granted. The existing
  three evidence rounds and existing Worker budgets are unchanged.

Files removed by rollback cannot be recovered by pretending their contents are
known. In that case the correct behavior is a dependency block or explicit
bounded context failure.

### C. Rollback was correct; dependency declaration and snapshots were incomplete

**Observed:** failed task transactions were rolled back, leaving no accepted
application files. Later tasks attempted to consume missing artifacts.

**Cause:** ordinary decomposition exposed only `goal`, `done_when` and
`scope_hint`. Although the scheduler supported explicit dependencies, this route
did not ask the model for them or propagate them to child tasks. Ordering alone
does not establish dependency. `_execute_children` also reused an old repository
snapshot after earlier children committed or rolled back.

**Corrections in `mini.py`:** `children_schema` requests `depends_on`; the prompt
asks for earlier sibling ordinals, and `_children_validator` rejects forward,
cyclic, noncanonical or invalid references. `decompose_task` maps those ordinals
to actual root/nested task IDs. Compact decomposition evidence retains the edges.
`_execute_children` refreshes the repository snapshot immediately before each
dispatch. Verified dependency summaries carry changed paths into inspection.

The existing scheduler still blocks declared dependents after a prerequisite
fails, and still allows independent siblings to run. Rollback is unchanged:
unaccepted new files are removed and modified files are restored. Existing World
Model commit/rollback revalidation remains in use. Failed artifacts are not
promoted into verified dependency context.

### D. Verification PASS remains distinct from transaction acceptance

The captured run did not demonstrate an erroneous final success: a verification
PASS was followed by a failed impact audit and rollback. `_commit_verified_leaf`
already requires the evidence gate, accepted Impact Contract and post-mutation
comparison before commit. The normal Repairer route also performs fresh
verification and an impact audit before commit. These acceptance requirements
were retained, not relaxed.

Regression controls now show that a passing verification input cannot override
a missing required impact or an unauthorized mutation. A production Repairer
edit can commit only after fresh exact-byte verification passes. A failed gate
cannot enter `_commit_verified_leaf`. A log such as `VERIFY PASS` describes that
verification gate, not final transaction acceptance; inspect the subsequent
impact comparison, transaction event and final result.

### E. Project classification is preserved

The previous `hivo/project_understanding.py` correction still distinguishes a
new application's feature operations from requests to edit an existing project.
Its patch is byte-equivalent after newline normalization to the saved pre-cycle
diff. Its ten tests, the existing-project tests and ingestion tests are included
in the selected regression cohort. No classification code was changed this cycle.

## 3. Changed files and why

| File | Change in this cycle |
|---|---|
| `mini.py` | Compile and enforce assigned greenfield scope; retain mission/dependency context; retain context feedback; stop terminal context failure; propagate dependencies; refresh snapshots; record bounded scope evidence. |
| `hivo/semantic_evidence.py` | Resolve exact allowed file-definition requests using real source, without inventing contract authority. |
| `tests/test_repair_cycle_001.py` | New deterministic reproductions and safety/integration controls. |
| `tests/test_greenfield_context_progress.py` | Verify early scope rejection and independently test the precommit backstop; accept either valid workspace-boundary rejection diagnostic. |
| `tests/test_greenfield_impact_lifecycle.py` | Preserve the unsafe/compound literal negative control using actual acceptance and literal-hash behavior, rather than assuming only literal requests can require scope. |
| `tests/test_verification_outcome_integrity.py` | Replace a negative fixture relying on prose-as-targets with an explicitly required, authorized file that is omitted; the acceptance rejection remains required. |
| `updates/REPAIR_CYCLE_001.md` | This single consolidated engineering report. |

Previously dirty classification code, `tests/test_project_mode_intent.py`,
`tests/fixtures/new_application_requirements.txt`,
`evidence/project-mode-intent/results.json` and `updates/R_UPDATE_003.md` were
preserved. They are not newly implemented corrections in this cycle.

## 4. Deterministic evidence and before/after results

Validation artifacts are local-only in
`E:\MiniHivo\el-samna-validation\20261118-repair-cycle-001`.
`run_checks.py` blocks `mini.ask_ollama` and `mini.structured_model_call`; individual
fixtures provide scripted responses. Actual runtime file tools, gates, resolver,
transactions and scheduler paths run where stated. This is offline integration
validation, not real-model validation.

The corrected baseline replay loads the original HEAD versions of `mini.py` and
`hivo/semantic_evidence.py` into memory, with no checkout or Git changes. The
pre-existing classification correction stays in place. Of the 16 new methods,
three controls passed and 13 failed against that baseline, with zero errors.
See `baseline-corrected.log` and `baseline-corrected-results.json`.

The controls cover:

- The recorded nine-word impact miscompilation and authorized multi-file writes.
- Pre-write scope rejection and a separate precommit unauthorized-edit backstop.
- Missing explicit required impacts, invalid/missing assignment and an empty
  outer authorization boundary.
- Case-consistent assigned paths.
- Exact-file evidence with real source, denied/outdated/missing source, and no
  promotion of ordinary source into an authoritative contract.
- Real dependency evidence recovery, while a write to that read-only dependency
  stays blocked.
- Long-mission feedback retention and bounded terminal failure (four context
  decisions in the controlled reproduction, rather than the fixture's full
  twelve-step budget).
- Declared dependency propagation, invalid references, rollback blocking, and
  fresh repository snapshots.
- Real Repairer editing followed by fresh exact-byte verification and transaction
  commit, plus rejection of the earlier failed verification.

The multi-file impact-boundary test deliberately supplies a passing verification
input to isolate impact acceptance; it is not a browser or behavioral success
claim. The separate Repairer test uses actual literal-artifact verification.

### Final selected cohort

| Validation | Actual result |
|---|---|
| Corrected pre-repair source replay, 16 new methods | 3 passed, 13 failed, zero errors. Expected reproduction failures. |
| Final treatment cohort, 22 modules / 493 selected methods | 492 passed, 1 skipped, zero failures, zero errors. |
| New repair regressions within that cohort | 16/16 passed. |
| Orchestration plus greenfield lifecycle check | 107/107 passed; these overlap the final cohort and are not added to its count. |
| Syntax compilation | 76 source/test files passed; no model invocation. |
| Diff formatting | `git diff --check` passed. |
| Evidence preservation | All 14 original files matched their saved SHA256 hashes; prompt unchanged; prior classification patch unchanged. |

Final counts and exact module/skip names are recorded in `final-results.json`
and `final-cohort.log`. The single skipped method is
`test_captured_diagnostic_responses_replay_without_provider_calls`: its
`DIAGNOSTIC_LIVE-2` raw planner artifacts are unavailable. This is a selected
cohort, not the entire inherited test suite.

An exploratory run also attempted
`test_v25_3_verification_obligation_coverage_gate`. Its class could not initialize:
the required historical `output/hivo-v22-stage5c-fresh-receipts-live-1/.hivo/memory.sqlite3`
and associated planning fixtures are absent. Its 35 methods were not validated.
No replacement database or invented passing evidence was supplied. That setup
error is retained in `regression-final.log`.

Earlier development logs retain test-harness errors and assertions changed to
reflect earlier scope enforcement. They are not represented as final passes.
The fixture updates preserve the negative safety behavior rather than deleting
the tests or weakening their acceptance assertions.

### Reproduction commands

From PowerShell, using the existing environment (no installation):

```powershell
$python = '.\.venv\Scripts\python.exe'
$checks = 'E:\MiniHivo\el-samna-validation\20261118-repair-cycle-001\run_checks.py'
Set-Location 'E:\MiniHivo\el-samna-el-balady'
& $python $checks --baseline  # expected failing reproductions; source loaded in memory
& $python $checks            # selected treatment cohort, live inference blocked
git diff --check
```

## 5. Remaining limitations and next live acceptance

- No model-backed rerun or browser session was performed. Live planning quality,
  production of a complete To-Do app, browser behavior, complete root acceptance
  and model response to the new context feedback remain unverified.
- Dependency declarations are now available and enforced; this does not prove
  the model will identify every semantic dependency correctly. Missing/incorrect
  planning edges remain a live observation target. No blanket rule makes every
  sequential sibling dependent on every predecessor.
- Greenfield mutation scope must identify safe assigned paths. Ambiguous or
  absent assignments cannot authorize a Worker to choose arbitrary files.
  Formal existing-project execution contracts and their approval rules remain
  authoritative and unchanged.
- The historical evidence does not retain full child scope/mission payloads.
  Newly added bounded trace fields improve future diagnosis without changing
  old evidence or inventing historical permission.
- One diagnostic replay fixture and the separate historical authority database
  suite are unavailable. These gaps are not full-suite success.
- No new files are manually retained as accepted output after a failed audit.
  Rollback still intentionally removes provisional application artifacts.

## 6. Exact next local benchmark

Use the same Ollama service/model and existing Playwright installation used by
the preserved run. Do not change verification policies or download dependencies.
If Ollama is not running, start the existing executable in a separate window
with its existing model directory (`OLLAMA_MODELS=E:\ollama_models`); do not start
a second server when the service is already running.

Run this **once** in PowerShell. It creates a new directory and copies the prompt
without re-encoding it. These commands were inspected, not executed in this cycle.

```powershell
Set-Location 'E:\MiniHivo\el-samna-el-balady'
$python = '.\.venv\Scripts\python.exe'
$original = 'E:\MiniHivo\el-samna-local-tests\todo-20261118-103737\prompt.txt'
$run = 'E:\MiniHivo\el-samna-local-tests\todo-' + (Get-Date -Format 'yyyyMMdd-HHmmss')
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path "$run\workspace" -ErrorAction Stop | Out-Null
Copy-Item -LiteralPath $original -Destination "$run\prompt.txt" -ErrorAction Stop
if ((Get-FileHash -LiteralPath "$run\prompt.txt" -Algorithm SHA256).Hash -ne
    '2132536FD2DF4A18C39F434DC43E4344034ED892C8640E94A98A103A82DD5B36') {
    throw 'Prompt hash mismatch; do not run.'
}
git rev-parse HEAD | Set-Content "$run\commit.txt"
git status --short | Set-Content "$run\git-status.txt"
git diff --binary | Set-Content "$run\source-diff.txt"
Get-FileHash mini.py,hivo\semantic_evidence.py,hivo\project_understanding.py |
    Format-List | Out-File "$run\source-hashes.txt"
& $python -u .\mini.py --model gemma4:e4b --mode auto --no-bootstrap `
    --workspace "$run\workspace" --prompt-file "$run\prompt.txt" 2>&1 |
    Tee-Object -FilePath "$run\console.log"
$LASTEXITCODE | Set-Content "$run\exit-code.txt"
Write-Host "Evidence directory: $run"
```

Keep the run bounded (30 minutes is a reasonable observation cap); interrupt
with Ctrl+C if necessary and record that it was interrupted. Do not overwrite
the workspace or repeatedly restart the same failure. Send the new directory,
`console.log`, exit status, `workspace/.agent_runs/*.jsonl`, `workspace/.hivo`
database/journals, generated files and any browser evidence. Before sharing,
remove credentials if the new task ever introduces any.

Check in order: project mode and all 11 retained requirements; explicit scopes
and dependencies; Context/Impact authorization; real persisted mutations;
verification; post-mutation comparison; transaction commit/rollback; child
dependency state; and final root acceptance. Browser PASS alone is insufficient.

## 7. Final review and preservation

The final review checks the exact diff, syntax compilation, prompt hash,
classification patch preservation, historical file hashes and clean diff
formatting. All changes remain uncommitted on `development`; no staged changes,
remote operations or edits to earlier worktrees are part of this repair cycle.

## 8. Run 3 regression correction and Run 4 readiness

### 8.1 Exact comparison and evidence preservation

Both runs used HEAD `667d6143e77b2494ee6e286d91ea73c53696eaa2` with local changes.
The initial repair's `mini.py` was reconstructed **in memory** from the saved
pre-correction diff. Its SHA256 exactly matches Run 3's `run_started` source
hash. The HEAD `mini.py` hash exactly matches Run 2's recorded hash. This is a
proven local repair regression, not a claim based only on similar console lines.

| Evidence | Run 2: `todo-20261118-103737` | Run 3: `todo-20261118-123923` |
|---|---|---|
| `mini.py` SHA256 | `adefb2e74af5eef58e5e0a47801eca5dbfb0615088c3e38c7d6940415d1974d5` | `b270e1b00bf583528eb070ee4ef7b14b99125cd0d729db729c7eede038844644` |
| Complete native trace records reviewed | 489 | 167 |
| Preserved SQLite tool-event rows reviewed | 68 | 22 |
| Builder writes | Six successful write calls | Thirteen failed write calls |
| Falsifier / browser / Repairer | All reached; impact audits failed afterward | None reached |
| Impact failure | Task 1: 9 missing / 3 out-of-scope; task 2.1: 8 missing / 2 out-of-scope | Thirteen scope refusals before verification |
| Application files retained | None, after rollbacks | None |
| Process record | Exit `-1`; no successful root acceptance established | Exit `-1`, manually stopped |

Run 2's tool status `succeeded` establishes execution of a tool, not that every
application requirement passed. Its recorded Builder, Falsifier and Repairer
progress does not override the failed impact audits. Neither run establishes a
successful final root verdict.

Run 3 native trace:
`workspace/.agent_runs/20261118T124029-b478c52d.jsonl`.
At 12:46:50, `worker_mission_ready` explicitly records `index.html` and
`style.css`. The following `impact_contract_created` instead authorizes
`HTML structure`, `CSS styling`, and `Basic layout`. The same erroneous scope
reappears for the alternate strategy at 13:16:00. Write refusals continue through
13:30:48. This also recovers the concrete mission paths that the older Run 2
trace did not retain.

Read-only comparison artifacts and new validation logs are in
`E:\MiniHivo\el-samna-validation\20261118-run4-readiness`:
`comparison.json`, `inspect_runs.py`, both preservation manifests,
`pre-correction.patch`, focused test logs and the selected cohort results.
No earlier validation results were replaced. SQLite inspection used immutable,
read-only connections; no journals or historical databases were rewritten.

### 8.2 What regressed and what changed

**Regression 1 — semantic responsibility became file permission.** The initial
repair preferred `scope_hint` over compiled mission targets and accepted any
safe-looking workspace name as a path. Therefore semantic descriptions replaced
the correct executable assignment. Run 2 had discarded the assignment entirely;
Run 3 retained the wrong representation of it.

**Correction:** `mini._greenfield_concrete_paths` separates file-shaped
assignments from semantic labels. `_prepare_task_impact_contract` now uses the
compiled mission's concrete paths when the child's hints are descriptive.
Genuine concrete child paths remain authoritative, even if the mission names
only a subset; omitted required impacts must still be audited. The compiler
cannot broaden concrete child paths or outer contract boundaries.
Prose, traversal, protected runtime/Git metadata and wildcard targets do not
grant permission. An extensionless new filename can be explicitly identified as
`./name`; filenames containing spaces and a real suffix are supported. A parent
path cannot be substituted for an authorized descendant file.

The greenfield Mission Compiler prompt now explicitly requests concrete
workspace-relative file targets for the current child. No To-Do filename or
keyword is hardcoded in production. No path is inferred from a rejected Worker
write. `app.js` is **not** automatically added to the historical first child's
two-file mission merely because the Worker requested it.

If no concrete authorized assignment can be compiled, `execute_leaf` returns
`IMPACT_CONTRACT_INCOMPLETE` before dispatching a Worker or opening its
transaction. It does not spend model/tool budgets on an unusable scope.

**Regression 2 — a permission refusal became task-size evidence.** Four invalid
mutations of the same target previously caused `TASK_TOO_BROAD`. In Run 3 that
launched `HTML-First Structure Definition` with the same bad contract. Retrying
the same authority mismatch could not make a file write legitimate.

**Correction:** scope refusals are counted separately. Three refusals under the
active assignment end the attempt with `IMPACT_CONTRACT_INVALID` and an
`impact_scope_retry_exhausted` event, rather than `TASK_TOO_BROAD`. The existing
controller consequently does not split the task or start an alternate strategy
for that unchanged scope failure. An isolated refusal can still be corrected:
the Worker can select an authorized path, obtain fresh verification, and commit
valid output. Guards are retained; refusals are never converted into successes.

**Repairer terminal propagation:** the new terminal impact outcome must also
survive the Repairer caller. A focused test found the ordinary leaf repair loop
would otherwise proceed to a fresh gate and another repair attempt. The gate
rejected that attempt; no false acceptance was demonstrated. `execute_leaf` now
propagates the specific terminal impact failure and rolls back immediately.
This is a safety integration correction for the new failure path, not evidence
that Run 3 reached a Repairer (it did not).

### 8.3 Functional validation and preserved boundaries

New file: `tests/test_run4_scope_regression.py`. Only `mini.py`, that new test
file, and this report were changed in this follow-up. The earlier context,
dependency, classification, verification and rollback corrections remain in
place; no full repair-cycle revert was used.

The first eight new fixtures were executed before correction: five assertions
failed and three full-leaf scripts exhausted their finite responses after the
bad scope prevented their expected progress. Those `StopIteration` errors are
test-harness consequences, not errors observed in either live run. See
`before.log`. A separate focused reproduction recorded the terminal Repairer
outcome falling through into another repair attempt in
`repairer-boundary-before.log`.

After correction, the eleven focused tests pass. They include:

- Exact reproduction of Run 3's descriptive hints versus concrete mission paths.
- Explicit child/root path restrictions, malformed/unsafe scopes, metadata,
  extensionless files and filenames containing spaces.
- Rejection of descriptive-only scope before Worker dispatch.
- Bounded repeated scope refusal with the actual controller: no alternate
  strategy and no decomposition is invoked.
- A recoverable single refusal followed by authorized writes and acceptance.
- A production leaf sequence with scripted AI but real file tools, Python
  self-check execution, Falsifier, evidence gate, impact comparison, commit and
  independent persisted-content assertions.
- A real failing self-check followed by a production Repairer read/edit, fresh
  successful verification, impact acceptance and retained corrected content.
- Rollback of provisional authorized writes when the attempt subsequently ends
  in terminal scope failure, including the Repairer case. No foreign file is
  created and no commit is recorded.

These are **deterministic production-path integration tests**, not real-model
or browser validation. Their small calculation utility is an offline fixture;
the actual To-Do application and original prompt were not modified or generated.
The original Run 2 regression cases remain covered in `test_repair_cycle_001.py`,
including required impacts, context recovery, terminal context bounds, dependency
blocking and fresh post-rollback snapshots.

An adjacent cohort exposed two additional compatibility boundaries: narrowing a
concrete child assignment to the compiler's subset could remove an explicitly
required impact, and the new preflight assumed a contract existed even when the
Impact policy was inactive. Both were corrected in production; the existing
verification-integrity and child-scope tests were left unchanged. The affected
80-test cohort then passed. Its initial failures and final results are preserved
in `cohort-initial-results.json`, `cohort.log` and `authority-regression-after.log`.

The broader selected cohort results are recorded in this follow-up's
`final-results.json` and `cohort-final.log`:

| Final Run 4 readiness validation | Actual result |
|---|---|
| Selected regression cohort: 23 modules, 504 methods | 503 passed, 1 skipped, zero failures, zero errors. |
| New Run 4 methods within that cohort | 11/11 passed. |
| Targeted scope + verification-integrity + child-scope cohort | 80/80 passed; overlaps the final cohort. |
| Syntax compilation | 77 source/test files passed. |
| Diff formatting | `git diff --check` passed. |
| Run 2 preservation | All 14 original files matched their saved hashes. |
| Run 3 preservation | All 9 original files matched their saved hashes. |

The one skip is the same unavailable `DIAGNOSTIC_LIVE-2` planner replay artifact
identified in section 4. Existing verification-integrity, child-scope, context,
Impact, dependency, existing/new-project, World Model and adaptive orchestration
regressions passed. Counts are selected methods, not independent research cases.
Tested source hashes are in `tested-source-hashes.json`.

The Repairer integration test follows the ordinary leaf's real fresh gate using
the Repairer's executable proof. It does not claim a second Falsifier dispatch
or an actual browser check after repair.
The historical unavailable authority database and diagnostic replay limitations
in section 4 still apply. No full-suite or live success claim is made.

Reproduce the selected offline validation without inference:

```powershell
Set-Location 'E:\MiniHivo\el-samna-el-balady'
& '.\.venv\Scripts\python.exe' `
  'E:\MiniHivo\el-samna-validation\20261118-run4-readiness\run_checks.py'
git diff --check
```

### 8.4 Run 4 conditions and observation targets

Use the unchanged section 6 launch procedure, the exact preserved prompt and a
**new empty workspace**. Do not reuse either historical workspace, carry its
agent memory forward, or remove a requirement. Keep `gemma4:e4b`, auto routing
and existing policies/budgets. This repair does not start Run 4.

**Readiness verdict: ready for one controlled local Run 4.** Reusing your Run 3
PowerShell launcher is appropriate: create a new timestamped `$run`, copy the
same original prompt, capture the current uncommitted diff, and invoke
`$repo\mini.py` by its absolute path. Retain `--model gemma4:e4b --mode auto
--no-bootstrap --workspace ... --prompt-file ...`. You can keep the shell's
working directory in the new run folder, as in Runs 2 and 3. No old source needs
to be copied back and no prior worktree needs to be changed.

Run 4 should demonstrate, in order:

1. NEW_PROJECT classification and all 11 retained source requirements.
2. Concrete compiled child targets matching the accepted Impact Contract paths.
3. Successful authorized file writes and persisted contents, not just tool calls.
4. Falsifier/executable/browser checks where applicable.
5. If repair is needed, authorized edits and fresh verification.
6. Passing post-mutation impacts, transaction commit and retained artifacts.
7. Correct dependency progression and ultimately complete root acceptance.

The offline results establish the controller path and its safety controls. They
cannot guarantee the model will follow the assignment, that the generated
browser app will be correct, or that the next run will reach full acceptance.
Scope conflicts must remain explicit failures rather than be resolved by
silently expanding permission. Save the full run evidence and keep a bounded
observation window; do not run another automatic campaign after a failure.

## 9. Assistant-operated live debugging after Run 4

### 9.1 Run 4 and the creation-context handoff

Evidence: `E:\MiniHivo\el-samna-local-tests\todo-20261118-143414`, native trace
`20261118T143552-0c884699.jsonl`. The user run correctly classified NEW_PROJECT,
retained all 11 requirements, planned children and dispatched a Builder. That
Builder requested definitions of the files it was meant to create. Four checks,
three evidence rounds and nine requests returned zero evidence; it terminated
with CONTEXT_INSUFFICIENT. Dependent tasks were blocked. Falsifier and Repairer
were not reached. The bounded termination worked; useful implementation did not.

`mini._greenfield_creation_context` now provides an explicit controller packet:
assigned files, observed absent/present state, local completion conditions and
the compiled expected outcome. An absent assigned artifact is an output to
create, not a pre-existing symbol to retrieve. Present files and genuinely
missing external dependencies still require inspection/evidence. This packet
does not mark context sufficient, fabricate source, authorize mutation or change
the Context Sufficiency state machine. The model must still submit its decision
and the Impact Contract must still be accepted.

### 9.2 Live attempt 5: actual writes and a failed verification handoff

Evidence: `E:\MiniHivo\el-samna-local-tests\todo-live-005-20261118-150450`.
Trace: `workspace/.agent_runs/20261118T150633-7e1974a7.jsonl`.
The unchanged prompt and local `gemma4:e4b` were used through the real CLI.

- Host preflight, ingestion, NEW_PROJECT classification and planning succeeded.
- At 15:16:39 the Builder's first context check returned MUTATION_ALLOWED, and
  the two-file Impact Contract was authorized without any evidence requests.
- SQLite event 2 records a successful `index.html` write; the real file was
  independently read and hashed. `style.css` was subsequently persisted too.
- SQLite event 9 records actual Chromium verification failing on a 404 for
  `app.js`, referenced by HTML but outside this two-file assignment. The actual
  screenshot and receipts are preserved in `checkpoints/first-verification`.
- Repeated forbidden writes and shell inspection/status commands did not repair
  the defect. The attempt was stopped for diagnosis; `stop-reason.json` records
  the intervention. Its files remain provisional, not accepted. Forced stopping
  does not manufacture a normal rollback or a natural root verdict.

Three additional corrections followed:

1. **Truthful failed-verification handoff.** An empty Worker completion after
   failed execution used to be forced back into a loop demanding success before
   independent review. `_failed_verification_handoff` recognizes actual current
   structured FAILs or nonzero native exit receipts; malformed, unavailable,
   optional, stale-after-mutation and superseded results do not manufacture an
   outcome. `execute_agent_task` returns `verification_failed`, never `done` or
   PASS, and `falsify_task` allows that outcome into independent review. Quality
   and commit gates remain unchanged. The controlled integration test reaches
   Falsifier, authorized Repairer editing, fresh execution, impact audit and
   actual transaction commit.
2. **Usable command contract.** The tool schema and command validator share
   `VERIFICATION_EXECUTABLES`, containing the exact previous allowlist. The
   description exposes it and directs inventory/inspection to their dedicated
   tools. `ls`, `pwd`, `echo`, composition and inline-code refusals are not
   converted into successful verification or newly permitted commands.
3. **Executable milestone planning.** The Mission Compiler is instructed to
   include permitted local companion artifacts needed to verify its milestone,
   without implementing future child behavior or expanding explicit ownership.
   This is generic prerequisite planning, not a To-Do filename exception or a
   retrospective grant to a rejected write.

### 9.3 Live attempt 6: independent Falsifier execution exposed profile contamination

Evidence: `E:\MiniHivo\el-samna-local-tests\todo-live-006-20261118-154436`.
Trace: `workspace/.agent_runs/20261118T154614-77f9cfa4.jsonl`.

The real compiler declared `index.html`, `style.css`, and `app.js` before any
mutation; the Impact Contract matched. Context passed and all three writes
succeeded. Chromium loaded the page with no console/page/network errors.
`checkpoints/builder-verification` preserves the files, screenshot and database:
event 5 is the Builder's actual passing browser result.

Falsifier then executed independently. Its event 7 also passed browser loading.
However, its explicit `verify_web_app` call (event 10) unexpectedly required a
game canvas, AGENT_GAME, movement, win and touch controls. Those are not source
requirements. A Repairer started and inspected the three files. The attempt
was stopped at 16:08:55 before repair could act on the wrong contract; all three
file sizes remained 722 / 1462 / 239 bytes. No accepted transaction or successful
repair is claimed. See `stop-reason.json` and `checkpoints/falsifier-verification`.

The exact applicability hash was
`a369fb73ad53f3dcceaa96a94351c98563761aac25f02d652b61c38a6edfe91c`.
Routing attaches this artifact to the active contract. The legacy classifier's
`current` path flattened the entire contract to JSON and tested substrings,
including `3d`; this hash alone reproduces the false game classification. The
old HTML `run_file` path also defaulted to a generic web profile, making the two
browser routes disagree. This was a latent verifier-authority defect exposed
after reaching Falsifier, not an actual missing game feature in the application.

The runtime correction is in `hivo/verification_scope.py`: profile inference
receives canonical semantic requirement values, not receipt hashes, diagnostics
or arbitrary serialized metadata. Explicit verification requirements and text
records remain included. Root-source coverage, recognized child scope and
committed-profile preservation remain in place. The chosen policy flag stays
unchanged; the standalone legacy experimental classifier was not rewritten.
`verify_browser_application` also derives the same authorized profile when a
caller omits one, so HTML `run_file` does not bypass real game/timer obligations.
Receipt hashes remain intact for identity/freshness checking.

Falsifier also attempted to execute CSS. `run_file` now labels that invocation
not applicable and directs it to the owning HTML/browser route. This is not a
CSS PASS: a skip alone cannot satisfy verification, genuine browser errors still
fail, and existing syntax/mutation/acceptance checks remain unchanged. Literal
controller-bound byte verification still precedes this branch.

### 9.4 Focused validation and live evidence boundaries

- Initial creation-state integration cohort: 12 tests passed, followed by 49
  related context/Worker/Repairer tests passing.
- Handoff, actual controlled repair/commit and adjacent integrity cohort: 85
  tests passed after correcting the Falsifier entry guard for the new outcome.
- Profile baseline: four failing assertions across five methods reproduced hash
  contamination, timer misclassification and CSS execution misuse.
- Browser authority/routing, child/parent coverage, verification integrity and
  pipeline cohort: 110 tests passed. Seven final authority methods also passed,
  including real game/timer obligations, requirement text records, real web FAIL,
  consistent browser entry paths and no acceptance from CSS skips.
- Two separately attempted frozen-prompt tests could not read their missing
  historical `output/gemma-only-rescue-recursive-v9-hard-prompt.txt` fixture.
  They are not claimed as passing and their errors remain in the validation log.

These cohorts overlap; their counts are not added together or presented as a
full-suite result. Logs are in
`E:\MiniHivo\el-samna-validation\20261118-run4-readiness`, including
`creation-adjacent.log`, `handoff-adjacent-final.log`,
`profile-authority-before.log`, `browser-authority-final.log`, and
`profile-preservation-final.log`. Failed intermediate tests remain preserved.
New regression file: `tests/test_browser_requirement_authority.py`.

The live code is frozen during each attempt. Every new run copies the original
prompt byte-for-byte, records HEAD/local diff/source hashes, and places its
workspace, stdout/stderr, screenshots and temporary files on E:. Local model,
memory and disk checks are recorded without changing hardware/model policies.
No Mini Hivo source commit, push, merge, branch change or GitHub operation was
performed. Only this consolidated repair report is being updated.

### 9.5 Live attempt 7: verified child acceptance and retained artifacts

Evidence root:
`E:\MiniHivo\el-samna-local-tests\todo-live-007-20261118-162436`.
Native trace: `workspace/.agent_runs/20261118T162614-b7a0b6c8.jsonl`.
Machine-readable audit: `accepted-milestone.json`.
All timestamps below are local (+02:00); SQLite timestamps use UTC.

The real CLI used the unchanged original prompt and `gemma4:e4b`. HEAD remained
`667d6143e77b2494ee6e286d91ea73c53696eaa2` plus the recorded local patch in
`source-diff.txt`; `source-hashes.json` identifies the exact four runtime files.
The final audit confirms those files did not change during the run.

| Actual checkpoint | Evidence |
| --- | --- |
| Host preflight, all 11 requirements, NEW_PROJECT, real decomposition | stdout and native trace; four children persisted in SQLite |
| Mission and Impact Contract agreed on three assigned files before mutation | `worker_mission_ready` and `impact_contract_created`, 16:34:06 |
| First context decision sufficient; Impact Contract authorized | trace lines 41–42, 16:36:05; SQLite event 1; no evidence-request loop |
| Real Builder writes | SQLite events 2–4: index.html, style.css, app.js |
| Actual Builder browser PASS | SQLite event 5, `run_file`; web profile, no page/console/network errors |
| Independent Falsifier verification | event 7 `run_file` PASS; file reads events 8–10; event 11 `verify_web_app` PASS |
| Required BROWSER route PASS | `verification_route_result`, 16:47:14; no erroneous game obligations |
| Impact acceptance | trace line 104, 16:47:37.087: IMPACT_CONTRACT_PASSED, missing=0, out_of_scope=0, unexpected_related=0, preservation_violations=0, mutation_authorized=true |
| Actual workspace transaction commit | trace line 106, 16:47:37.125, all three changed files |
| Accepted child and scheduler progression | `[VERIFY 1] PASS`, `[DONE 1]`; SQLite task 1 `done`; scheduler COMPLETED and child 2 planning started |

The accepted artifact registry independently records `verified=1` and the
following SHA256 values. Each matches the file bytes still on disk after stopping:

| File | Bytes | SHA256 |
| --- | ---: | --- |
| index.html | 722 | c7bf2f535158828853c2561ef1e1c0bb75f9708dbd3bde2e988f3d8c79a4d26e |
| style.css | 1462 | 9ad0720bd5ad5681703010f703761fd5ae047b7fb36cd21ad5cfcecce6d5ea3b |
| app.js | 239 | db67e57a20d091a7cd7cfbc859b069b7dd79b7431c9f9dfd0f8d79d3d7b68c56 |

Files remain in `workspace`; accepted copies, the SQLite snapshot and screenshots
are in `checkpoints/accepted-child-1`. The actual Falsifier screenshot is
`workspace/.agent_evidence/task_1.png`. Events and receipts are preserved in
`workspace/.hivo/memory.sqlite3`, with earlier checkpoints preserving changing
screenshots and live WAL evidence. Full stdout/stderr are in the run root.

**Scope of the achievement:** this exceeds Run 2's rollback outcome: a real
Builder → independent Falsifier → browser verification → passing Impact Contract
audit → transaction commit path retained all three authorized files. No Codex
application implementation or manual file repair occurred. The first child was
structure and styling; its JavaScript is explicitly a placeholder. Adding,
completion toggling, deletion and persistence belong to later children and are
not established by this child browser-load check.

Verification passed naturally, so no Repairer was artificially triggered in
attempt 7. The actual Repairer started and inspected files in attempt 6; it did
not make a live mutation. Authorized Repairer editing, fresh verification,
commit and rollback protections are demonstrated by deterministic integration
tests in `tests/test_run4_scope_regression.py`, not claimed as live recovery.

The attempt was deliberately stopped after the milestone, during child 2's
Coordinator call and before another child mutation. `stop-reason.json` records
the scoped process termination; wrapper exit code is -1, not a normal final
verdict. Root/child-2 status in the preserved database remains `running` because
execution was interrupted; it was not rewritten. There was no time-limit failure
or new stall at this checkpoint. Full root acceptance and full To-Do behavior
remain unverified, rather than failed by inference from the manual stop.

Before stopping, approximately 3 GB RAM remained available; C: remained near
1.53 GB free and E: near 325 GB. Model/resource observations are preserved in
`resources.jsonl`. No timeout, token, retry, policy or model setting was increased.

Final integrity checks: Run 2's 14 preserved files, Run 3's 9 files and Run 4's
10 files all retained their recorded hashes. The prompt SHA256 is unchanged.
`git diff --check` passes. Development branch and HEAD are unchanged; no source
commit, push, merge or GitHub operation occurred.

**Next local validation:** use a fresh workspace and the same launcher/prompt
to continue the full application campaign when desired. Do not treat this
terminated in-flight process as resumable. Preserve this accepted-child evidence
as the checkpoint: the next goal is accepted functional children and a genuine
root verdict, with behavioral checks of add/empty-input/completion/delete/reload
persistence/responsive layout. A later failure should be diagnosed from its
actual receipts; no such future failure is asserted here.


## 10. Publication validation — November 19, 2026

The existing `main` and `development` branches and their origin refs were all
`667d6143e77b2494ee6e286d91ea73c53696eaa2` before publication preparation.
The uncommitted work was carried safely onto the existing `main` branch with
no merge, reset, new branch, or overwritten file. The requested destination is
`tasneem-ahmed05/el-samna-el-balady:main`; development is not being pushed.

The README now leads with the architecture, actual setup/run commands, live
history and the precise accepted-child boundary. Historical numbered update
records remain unchanged. Raw evidence paths mentioned in this report are
**LOCAL-ONLY EVIDENCE**, not GitHub links. Original logs, SQLite files, generated
application files and screenshots remain outside the publication.

Portable reproduction from the repository root (existing Python environment):

```powershell
python -B scripts/repair_cycle_001_checks.py
```

A fresh run using the existing Python 3.11 environment executed 517 selected
tests: **516 passed, 1 skipped, no failures/errors**. The skip is
`DIAGNOSTIC_LIVE-2 raw planner artifacts are not available`. Shared runtime model
entry points were patched to reject inference. This is a selected offline
controlled-functional/integration/regression cohort, not a full suite or a new
live run. Its command used `--output evidence/repair-cycle-001/publication-checks.json`;
that small result file records the module list, exclusions and runtime hashes.
The original log remains local under the publication validation directory.

`evidence/repair-cycle-001/accepted-child-1.json` is a small curated derivative
of the preserved Run 7 checkpoint, carrying the original summary digest, trace
references, artifact hashes, actual tool-verification results and acceptance
boundary. It is evidence, not reusable mutation authorization. Runtime source
hashes in the fresh test result match those recorded for Run 7.

Syntax inspection covered the 12 changed Python files. The original prompt
fixture is explicitly stored without Git text conversion so its recorded
CRLF byte hash survives a future clone. Environment/cache/model exclusions
were added without deleting or changing any existing local output. No model,
application or browser session was started for publication. Full functional
To-Do and parent/root acceptance remain unverified as described in Section 9.5.
