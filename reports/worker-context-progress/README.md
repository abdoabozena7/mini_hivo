# Greenfield Worker context-to-execution repair

> Historical implementation checkpoint: the no-rerun/no-publication statements below describe the first Worker-fix phase only. See the [final engineering handoff](../coin-courier-runtime-integration/ENGINEERING-HANDOFF.md) for subsequent Runs 007?009 and the stacked publication.

## Scope and baseline

This implementation follows [PR #3](https://github.com/kareem232003/mini_hivo/pull/3)'s feedback-retention and activation findings. It does not change that research or the original experiment. No model inference or Coin Courier rerun was performed.

Local implementation branch: `fix/greenfield-worker-context-progress`.
Base: `1e233845b3e9d26b10bb66238ec13a00f108356e`, PR #2's reviewed runtime head, not merged team main. Team main was `f842fb8fb6e63e3064891d26ee0b24981e55c847` at inspection. This base permits Python 3.11 imports without copying the original checkout's uncommitted ingestion rewrites. Before opening an independent PR, resolve this base dependency with the runtime-fix owner; do not duplicate PR #2's history accidentally.

Read-only GitHub inspection found PR #2 and PR #3 open, Draft and unmerged. No accessible newer Worker implementation fix was found on inspected team/main, diagnostic branch or contributor heads. This does not establish the status of private/unpushed work.

The baseline `execute_agent_task`, `compile_worker_mission` and `prepare_worker_mission_context` ASTs match the original experimental checkout's corresponding functions. Other ingestion changes in that checkout are deliberately excluded.

## Established defect and historical causal limits

Run-006 observed 55 context decisions (54 sufficient, one invalid), two exhausted 28-step Workers and no application files. Both missions had null execution-contract IDs and no progress/grounding summaries. See the original [Run-006 report](../real-task-01/RUN-006.md); the independent integration interpretation remains in PR #3.

The current route rebuilt the next model request after a context decision using:

```python
compact_text(base_worker_prompt + "\n\nCONTEXT GATE UPDATE:\n" + feedback,
             MAX_WORKER_MISSION_CHARS)  # 4200; prefix truncation
```

A sufficiently long base mission therefore displaced the successful tool result and appended authorization feedback. It also discarded the existing tool transcript. The state-driven regression demonstrates this on a real compiled greenfield leaf: the initial user prompt is 10,297 characters, its next request loses the successful gate result, and the Worker consumes all 28 steps checking context again.

This is now a confirmed implementation defect and deterministic route-level reproduction, rather than only the source-level hypothesis recorded in PR #3. It is **not proof that it was the sole cause of gemma4's historical Run-006 choices**. Full historical model-visible request bodies were not preserved. Model behavior, other instruction effects and subsequent recovery remain unmeasured here.

## Actual route and wrapper boundary

The regression traverses `execute_leaf` -> `prepare_worker_mission_context` -> real `compile_worker_mission` -> node context -> real `execute_agent_task`. The structured provider's mission payload and Worker responses are deterministic test doubles; compilation validation, context gate, impact acceptance, tool projection, file tools and transaction machinery execute normally. The fixture stops after the Worker, before ordinary application verification; one negative test additionally invokes the real precommit boundary.

`_current_execution_contract` returns `None` on this ordinary greenfield route. A mission is not an approved Stage 4A execution contract. `WorkerProgress` and `MutationGrounding` require a Builder, a dictionary execution contract, allowed mutation paths, and no recovery state. They consequently remain absent in this fixture, as in the source-supported interpretation of Run-006. Merely selecting `progress_constrained` does not construct them or activate that treatment's contract-backed tool removal.

This contributes to the missing bounded-progress protection, but it does not mean context and impact authorization are absent. Both run and must pass before the positive test's write. Creating greenfield Stage 4A authority from mission hints would be a separate authority-design change; this patch does not do that.

## Two isolated corrections in mini.py

1. **Retain successful context feedback.** After a successful gate, retain the actual assistant/tool transcript and original mission for the next Worker response, regardless of whether a progress wrapper exists. This generalizes the existing contract-backed constrained branch. Keep the fresh-response boundary: a write later in the same tool-call batch does not spend newly returned authorization. Existing policy-specific tool projection, model limits and guard acceptance rules remain unchanged.
2. **Bound unwrapped initial Builder repetition.** Track consecutive successful context decisions on the same nonempty anchor. The first pass starts at zero repeats; three repeats (`worker_progress.NO_PROGRESS_LIMIT`) stop after four total gate calls with `WORKER_NO_MUTATION_PROGRESS` and a `worker_no_mutation_progress` event. This applies only when no progress wrapper or recovery state is active. Any intervening task tool, invalid/insufficient decision or anchor change resets the streak. It neither fabricates a contract nor forces a mutation.

The second correction is intentionally narrow: it does not detect all alternating-tool loops, redesign recovery, replace the existing contract-backed `current` control policy, or promise productive behavior from an uncooperative model. It turns the reproduced gate-only loop into a diagnostic bounded failure while the first correction permits productive execution.

Insufficient-context re-anchoring remains unchanged and can still be subject to prefix truncation. Broader prompt-retention redesign is outside this patch.

## Before/after reproduction

The identical original two-case fixture was retained separately before adding safety cases.

| Revision | Feedback-dependent Worker | Worker that ignores feedback and repeats |
|---|---|---|
| Unmodified base | Budget exhausted, 28 context calls; successful feedback absent | Budget exhausted, 28 context calls |
| Feedback correction only | Real authorized `write_file`, 2 tool steps, exact expected content | Budget exhausted, 28 context calls |
| Both corrections | Real authorized `write_file`, 2 tool steps | Explicit `WORKER_NO_MUTATION_PROGRESS`, 4 tool steps, no artifact |

The positive provider double selects a write only after seeing an actual successful gate tool result (or explicit successful gate feedback); it is not a turn-number script that writes regardless of feedback. No Coin Courier code was supplied. Its artifact is a temporary `artifact.txt`, removed by test cleanup.

## Safety and interpretation of a failed probe

The final focused suite has nine tests:

- Long greenfield mission retains successful tool feedback and the original full user mission; authorized content is written in two steps.
- A persistent same-anchor checker fails explicitly before budget exhaustion.
- The optional constrained flag alone still supplies no contract; the fallback remains effective.
- An intervening file listing resets consecutive-check accounting and later writing remains possible.
- Context check plus write in one response requires a fresh Worker response; the same-batch write does not execute.
- Denied impact acceptance cannot unlock writing after context sufficiency.
- Truly insufficient context with no completing evidence cannot mutate.
- Even after authorization, a workspace-escape write remains blocked.
- An unrelated provisional file cannot cross the real precommit impact audit; rollback removes it.

An earlier probe incorrectly expected the last case to fail at the **Worker write** boundary. It failed both here and on the unchanged baseline: the legacy greenfield impact gate validates controller acceptance, while unrelated-file comparison happens before commit. The corrected test deliberately feeds a synthetic passing verification input to `_commit_verified_leaf` and still gets an out-of-scope impact failure and rollback. That synthetic input stress-tests the negative audit boundary; it is not evidence of successful application verification. The initial failed logs remain preserved. No product change was made to conceal this distinction.

## Validation commands and actual results

All commands used the existing Python 3.11.9 virtual environment, `-B`, and process-local temporary storage on the experiment drive. The system drive was full; no installation, cleanup or global configuration change was made. For each suite below the exact command form was:

```powershell
python -B -m unittest discover -s tests -p <suite-filename> -v
```

The local runner stores the full interpreter argv and raw output for every invocation. Results below refer to the final source, not all intermediate executions added together.

| Suite filename | Tests | Result |
|---|---:|---|
| `test_greenfield_context_progress.py` | 9 | PASS |
| `test_context_sufficiency_gate.py` | 9 | PASS |
| `test_pre_mutation_impact.py` | 27 | PASS |
| `test_experiment3_worker_progress.py` | 4 | PASS |
| `test_experiment4_mutation_grounding.py` | 9 | PASS |
| `test_experiment15_evidence_edit.py` | 9 | PASS |
| `test_context_policy.py` | 3 | PASS |
| `test_execution_contracts.py` | 36 | PASS |
| `test_project_understanding.py` | 32 | PASS |

**138 focused/mechanism tests passed.** Existing grounding tests include stale/unobserved edit rejection and a real observed edit; execution-contract tests cover existing authority/scope protections. They do not demonstrate greenfield grounding-wrapper activation.

Broader provider-free recovery tests were also run on both the patch and unchanged detached baseline:

| Suite | Tests | Patched and unchanged-baseline result |
|---|---:|---|
| `test_v26_recovery_foundation.py` | 25 | FAIL: 18 failure records, including parameterized subtests |
| `test_v26_3_recovery_strategy.py` | 19 | OK, 2 skipped |
| `test_v26_4_tool_contract_recovery.py` | 26 | OK, 1 skipped |
| `test_v26_5_preverification_recovery.py` | 21 | FAIL: 3 failure records |
| `test_v26_6_no_mutation_recovery_search.py` | 40 | FAIL: 2 failures, 1 error |
| `test_v26_7_progress_aware_completion_recovery.py` | 40 | FAIL: 1 error |
| `test_v26_6_2_active_schema_mutation_intent_reset.py` | 15 | FAIL: 1 failure |

Failure/error headers, counts and suite summaries match the unchanged baseline. The clean checkout lacks ignored historical `output/hivo-v25-6-stage6c-b-verification-closure-live-3` fixture material; some tests explicitly assert its presence and downstream replay closure fails without it. Fixture-dependent skip guards account for the three skips. No historical output was copied in to obtain an artificially green result. These suites are **not a complete passing recovery certification**. Restore a reviewed fixture in an independent test environment before claiming that coverage.

Syntax validation compiles `mini.py`, the new regression file and all `hivo/**/*.py` in memory without writing bytecode; the exact count and Git/preservation checks are recorded in the local review results. `git diff --check` and new-file whitespace/link checks are separate final-review checks. No full suite, browser acceptance test, live provider run or Coin Courier rerun was performed.

## Evidence and preservation

Local-only implementation evidence is kept beside the isolated worktree (not in the original evidence tree). Relevant filenames:

- `preservation-before.json`: original Git status, eight dirty-file hashes, 174 original evidence hashes and read-only PR snapshots.
- `baseline-tests.txt`, `two-case-regression-snapshot.py`: pre-fix two-case failure and exact initial fixture.
- `feedback-only-results.json`, `targeted-fixes-results.json`: each correction tested independently and together.
- `safety-expanded-results.json`, `baseline-unrelated-target.log`: failed early-boundary probe and baseline confirmation (the baseline substring selection also ran the denied-impact case).
- `final-focused-results.json`, `mechanism-regressions-results.json`: final focused and mechanism results, with per-suite logs.
- `recovery-regressions-results.json`, `baseline-recovery-results.json`, `baseline-schema-results.json`: broader results and baseline controls.
- `review-results.json`: syntax, matching recovery failure headers, original checkout/evidence integrity and unchanged PR snapshots.

These materials contain local paths and are not proposed for publication as raw logs. Original E2E evidence, original dirty checkout, PR #2 and PR #3 remain outside this implementation's changes. No commits, pushes or PR updates were requested or performed for this patch.

## Readiness and remaining work

The two narrow corrections are suitable for implementation review with the recovery-fixture limitation disclosed. They establish a safe improvement in the deterministic real greenfield Worker route, not a completed application or a proven historical sole cause.

Before a full controlled integration run: review the branch/base dependency; agree on regression-safe ingestion prerequisites; capture model-visible context after each decision; retain policy selections, contract/null IDs, wrapper summaries, authorization, exact tool arguments/results, mutation hashes and terminal reason. Apply the same unchanged Coin Courier prompt, environment and independent acceptance criteria. Historical Run-006's withheld ingestion rewrites prevent treating it automatically as a matched Before arm.

The mechanism owners still need to decide greenfield execution-contract/grounding-wrapper semantics. Experiment 18A schema alignment and recovery-tool compatibility remain separate pending work. This patch neither bundles those changes nor claims they caused both historical Workers to stall. A controlled rerun is justified after review and readiness controls; it has not been executed.
