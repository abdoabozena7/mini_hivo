# R_UPDATE_005 — Bind completion decisions to current executable evidence

## A. Update identification

- **Date:** 2026-11-18 (UTC+02:00). **Status:** verified within the controlled controller scope; no new live-model acceptance.
- **Local branch:** `audit/decision-evidence`, based on `4096ccc3b405b2ed487040400e757d83c03df4ae`. At inspection, upstream `main` resolved to the same commit, upstream PR #1 was merged, and upstream had no open PRs.
- **Scope:** current-state verification, structured verification outcomes, mutation-argument exhaustion, and the final root success signal. The [separate research note](../docs/RESEARCH_AUDIT_NOTE.md) covers unanswered scientific questions.
- **Containing commit and PR:** pending; no commit, push, issue, or PR was created. Harness reference: installed HarrTest 4.1.0.
- **Tested working-tree SHA-256** (local file bytes, not staged blobs):

  | File | SHA-256 |
  |---|---|
  | `mini.py` | `cd9e23787ff427147f0b353117b7216756dd4d3c4eb9074c39dcdd896e07a6e7` |
  | `hivo/evidence.py` | `7b1d677af71f226f2879f3e94fbc3f6b93d1b748622e05f5ca74bc2e5dcbd72c` |
  | `hivo/verification_routing.py` | `635873117ca7a4c697edf76dac245a8f512a62933431b9534942959631cda648` |
  | `tests/test_mini.py` | `1711ec98de2f7e40e9d2d1d659010e26689235bac2391ef1f7fd2e5c5843bb88` |

## B. Original problem

The project audit asked whether strict orchestration actually raises quality, to reproduce problems, and to apply changes only after observable improvements. The controlled request was: **“Fix a typo in the status printed by status.py. It must print READY.”** The fixed contract scopes the mutation to `status.py`; a separate negative control additionally requires `required.py` to be observed.

On the base, an exact `READY` check passed, the Worker then edited `status.py` to print `BROKEN`, and the root committed with `done`. Running the persisted program independently printed `BROKEN`. In a different fixture, four calls missing `start_line` were rejected before editing but attributed to task breadth. An impact-rejection fixture also showed `[ROOT VERIFIED] PASS` in the same run in which the changed bytes were rolled back.

## C. Why this update was necessary

The harness is the mechanism meant to compensate for a smaller model. Passing yesterday's check on today's edit is a false acceptance, not independent verification. Refusing malformed calls is correct, but reading those refusals as evidence of complexity risks spending inference on the wrong kind of recovery. The progress log must not be used as a more permissive success oracle than the committed result.

## D. Root causes

| Confirmed cause | First wrong boundary |
|---|---|
| An older executable outcome survived a later successful mutation. | `merged_verification_evidence` fed mixed workspace states into `deterministic_quality_checks`. |
| The generic gate counted a verification tool observation rather than a recognized result. | A real overflow projection produced `NOT_RUN`; a status-only `FAIL` was not recognized by the legacy failure checker. Unlike an explicitly routed verifier, the generic gate could accept either. |
| The per-target mutation threshold counted schema rejections as evidence of scope. | `execute_agent_task` used one terminal interpretation for all four failures, even when the argument validator refused every attempt. |
| A verification sub-gate announced final success before post-mutation impact comparison. | `execute_leaf` and parent verification printed a final marker on an intermediate pass. |

## E. What changed

| Source | Change |
|---|---|
| [Evidence interpretation](../hivo/evidence.py) and [verification routing](../hivo/verification_routing.py) | Share structured outcome interpretation. Preserve explicit failure even when evidence is compacted. Project eligible executable evidence from after the last recorded successful mutation. |
| [Controller](../mini.py) | Require a recognized current PASS for the generic gate; keep historical failures available for diagnosis. Record an argument rejection at its validator seam. When all four counted same-target failures are schema rejections, stop under `MUTATION_ARGUMENT_RETRIES_EXHAUSTED`. Emit the final root marker after the root result is marked successful, not at a sub-gate. |
| [Controller regressions](../tests/test_mini.py) | Run the actual baseline controller with scripted provider replies, real Python execution and independent inspection. Exercise unavailable and contradictory receipts separately at the gate. |

## F. How the fixes work

1. A successful source mutation invalidates older verification for acceptance. A rejected edit leaves the current state intact and does not invalidate its proof. The raw transcript is unchanged. An executable check after the mutation may satisfy the gate again.
2. Both the generic and routed paths use the same interpretation of explicit statuses: failure dominates; unavailable or conflicting success is not a PASS. A different passing command cannot erase a recorded explicit failure.
3. The four-rejection cap and rollback are unchanged. The typed outcome applies only when all counted failures for that target were refused by the argument validator. It does not repair or guess arguments, permit mutation, or invoke a new strategy. Mixed failures and browser stagnation remain separate work.
4. `[VERIFY ROOT] PASS` is a sub-gate signal. A root that later fails impact comparison keeps its original failure and never emits `[ROOT VERIFIED] PASS`.

## G. Functional verification

Run on 2026-11-18, Python 3.13.7 on Windows. The same final fixture code ran on a temporary `git archive` export of the pinned baseline `mini.py` and `hivo` and on the delivered working tree. In the **six controlled functional replays**, goal ingestion receives the fixed contract and provider replies are scripted. The real context/impact gates, tool dispatch, filesystem transaction, Python command verifier, and final task result execute. After the run, a separate Python process executes the persisted `status.py`, and the test checks its output and the file bytes. Successful edits may use native line endings; rollback and rejection require exact seed bytes.

| Scenario | Baseline | Delivered candidate |
|---|---|---|
| Correct output checked, then changed to `BROKEN` without fresh proof | `done`; persisted program prints `BROKEN` | Failure; exact initial bytes restored; program prints `READY` |
| Corrective edit followed by exact executable proof | `done`; program prints `READY` | Same, with final root marker |
| Correct program checked, then edit rejected before applying | `done`; exact original bytes and output preserved | Same |
| Four range calls missing `start_line` | Four rejections; no change; `TASK_TOO_BROAD` | Four rejections; no change; `MUTATION_ARGUMENT_RETRIES_EXHAUSTED`; no breadth count or repair |
| First range call malformed; next call valid; fresh exact check | `done`; program prints `READY` | Same |
| Fresh command passes but required `required.py` is unobserved | Impact failure and exact rollback, **with** premature root success marker | Same impact failure and exact rollback, **without** final root success marker |

The seventh method is a **gate-level integration probe** (no browser is launched): the real evidence projector produces an unavailable receipt from the bounded fixture, and the real generic gate is fed that receipt, `ERROR` with `passed: true`, and explicit `FAIL` with and without a separate real-format zero-exit receipt. False accepts **4/4 → 0/4**; the explicit-PASS control passes on the candidate. The original controller satisfied **3/7 test methods**; the candidate satisfies **7/7**. The baseline command exited 1 with seven failure records (some are subtests); the candidate exited 0.

**Live-model completion:** not run on this revision. These are not measurements of browser/app quality, model intelligence, or decomposition success rates.

## H. Additional successful tests

The final selected regression invocation discovered `test_mini.py`, `test_evidence_policy.py`, `test_verification_outcome_integrity.py`, `test_adaptive_architecture.py`, `test_dependency_aware_scheduler.py`, `test_v26_4_tool_contract_recovery.py`, and `test_pre_mutation_impact.py`. Model HTTP GET and POST raised on unexpected use; tests could supply their own transport or provider fixtures. **298 methods reported, 294 passed, no failures or errors, 4 skipped, exit 0.** The seven new methods are included; do not add them to the regression total.

## I. Regression and compatibility impact

- Mutating only after authorization, applying real verifier failures, rejecting incorrect scope, accepting valid corrected tools, and preserving an unmodified verified state remain covered. This update changes no model, policy defaults, authorization, dependency, or retry thresholds.
- The four skips are the existing deterministic-stage, stage-slice, continuation, and coherent-rewrite tests in `test_mini.py`. Full test discovery, public CLI self-test, and live default-auto browser and approved-plan paths were not rerun here.
- Retained intermediate failures: an initial scripted provider signature mismatch; an unscoped fixture that exposed impact target inference; platform newline mismatches in success controls; and the stale-proof assertion initially looked for a builder payload not returned after repair. These were fixture/observation corrections. The final fixture was rerun on both revisions without changing its acceptance criteria between arms.
- The underlying executable verification and impact decisions still differ from terminal hints. Verbose root logs now explicitly distinguish the intermediate and final signals.

## J. Overall impact

In the tested cases, the harness no longer certifies changed but untested output or missing/failed receipts, and does not mislabel schema exhaustion or rollback as terminal success. Positive controls preserve valid progress. This supports a narrower **controller correctness** claim, not a population-wide improvement in output quality or lower inference cost.

## K. Remaining workflow findings and next checks

| Priority / confidence | Finding | Proposed next check or change |
|---|---|---|
| High / reproduced in a supplied-contract baseline fixture | Without explicit scoped targets, the ordinary sentence used in this audit made `_identifier_candidates` promote `Fix`, `typo`, `the`, and other prose to mandatory impact symbols. Eight invented targets blocked a correct executable edit. This does not measure frequency in live default-auto ingestion. | Separate authoritative mutation targets from lexical hints. Freeze paired requests with explicit editable scope, read-only file mentions, and genuinely missing scope; check correct edits commit, protected paths remain untouched, and ambiguous scope blocks before editing rather than failing late. |
| High / code and historical trace | The four-schema-only fix does not cover mixed failure sequences, repeated browser symptoms, or dependency rollback. Syntax/target/verifier causes can still require different actions; the historical [Three.js syntax-mode defect](../docs/MANUAL_RUN_ANALYSIS.md) was already fixed, not changed here. | Replay the same scheduled faults with and without one admissible correction under unchanged authority. Track the earliest decisive failure, real correction result, and later split or stop, not the count of propagated child failures. |
| High / coverage gap | Freshness here is ordered tool evidence within the generic gate. It is not a dependency-closure fingerprint across processes, nor proof that a syntactically valid/zero-exit command covers the original behavior. A low-risk leaf can skip the independent Falsifier role; that role is not the final external oracle. | Test source-obligation coverage with protected hidden checks and versioned handoffs; require independent front-to-back behavior before crediting full-stack completion. |
| High / code and history | Legacy children run sequentially in a shared workspace. More divisions can multiply context/handoff cost, and mutually dependent API/UI work can pass child-local checks on incompatible assumptions. Parallel writes into that shared transaction model are not a measured improvement. | Compare one focused unit, a dependency-aware split, and a finer split on the **same frozen interfaces and budget**, stratified by coupling. Test the actual HTTP/browser contract and restoration of prerequisites before experimenting with isolated parallel workers. |
| High / historical trade-off | [Experiment 12](../reports/experiment12/experiment12-report.md) reduced bad receipts in a protocol probe but fresh Node fell from 3/3 Root verified to 0/3 while the two game cases improved. A flag that helps one verifier family can hurt another. [Experiment 19](../reports/experiment19/context-decision-closure-report.md) added overhead without advancing its measured Python gate. | Re-test proposed policy combinations on the current source, not historical ratios. Require per-family compatibility and a fixed independent oracle; keep deterministic, frozen-contract, and full-request evidence separate. |
| High / experimental gap | Current node/step and per-request caps are not a common whole-task token, tool, and time budget. `baseline` and `recursive` differ in preparation as well as splitting. | Freeze equal charged budgets and one execution engine/authority across the treatment arms before measuring the causal effect of decomposition. See the [research note](../docs/RESEARCH_AUDIT_NOTE.md). |

## L. Evidence and reproduction

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_mini.py -k decision_evidence -v
```

For the matched baseline, export `mini.py` and `hivo` from the exact base commit into a fresh temporary directory with `git archive`. Use it as the process working directory, the same Python executable and final `tests` directory, and no alternate `PYTHONPATH`. Run the same discovery selector and `-k decision_evidence -v`. The candidate run uses the repository working directory. Reproduce the selected regression by loading the seven patterns in Section H with `unittest.TestLoader().discover("tests", pattern)` into one suite; block unexpected `mini.http_get_json` and `mini.http_post_json` before `TextTestRunner(verbosity=2, buffer=True).run(suite)`.

Raw logs are in the private session files: `decision-evidence-baseline-delivered.log`, `decision-evidence-candidate-delivered.log`, and `decision-evidence-delivered-regressions.log`. Earlier diagnostic logs remain private. The table above is a curated derivative; historical reports and original attempts were not changed. Staged-blob verification is not applicable: nothing is staged or published.

## M. Summary for the team

**Proposed PR title:** Require current executable proof before marking Mini Hivo tasks verified.

**Proposed body:** An old PASS could certify a changed program, and the generic gate could count unavailable or explicitly failed evidence as proof. Separate the current proof set from history, unify receipt interpretation, report exhausted malformed tool calls accurately, and move the root success signal after the terminal verification decision. Identical replay cases went from 3/7 to 7/7 with actual Python output, rollback checks, and bounded receipt controls. Selected regressions: 294 passed, 4 legacy skips. No new live-model, full-stack, or whole-suite acceptance is claimed. Impact target inference and the equal-budget research comparison remain open. Local uncommitted changes only.
