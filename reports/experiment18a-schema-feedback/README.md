# Focused Experiment 18A schema and invalid-decision feedback correction

## Isolation and scope

Validation branch `fix/experiment18a-evidence-feedback`, created in a separate worktree directly from published implementation commit `5e66d34db1827b814abf98f56b0b77b5ef6f8ee5`. The published implementation branch, original dirty checkout, existing PRs and preserved runs are not modified. No model calls, browsers, Coin Courier or Run-010 were started.

This addresses only the supported evidence-kind advertisement and inconsistent feedback for an invalid context tool decision. It does not implement broader Experiment 18 recovery mechanisms.

## Confirmed causes

1. `context_sufficiency_schema()` advertised `needed_evidence[].kind` as an unrestricted string, while `validate_evidence_request()` accepted only `EVIDENCE_REQUEST_KINDS`.
2. `_context_sufficiency_tool()` rejected invalid input before calling `gate.evaluate()`, preserving the gate's actual state, but fabricated an insufficient/PREPARING_CONTEXT/unauthorized response. After prior successful authorization this contradicted the real state; it also discarded existing terminal failure details.

The baseline reproduction directly compared the tool result to the unchanged gate snapshot. It failed with `insufficient != sufficient`, and with `PREPARING_CONTEXT != CONTEXT_INSUFFICIENT` for an already terminal gate. These are implementation defects, not evidence of the sole reason for historical Repairer model choices.

## Exact changes

- [`hivo/context_sufficiency.py`](../../hivo/context_sufficiency.py): advertise a sorted enum from the existing whitelist. Add explicit `CONTEXT_DECISION_INVALID` feedback before ordinary success feedback, so rejected input is not described as a new successful authorization.
- [`mini.py`](../../mini.py): build invalid-input feedback from the gate's read-only snapshot. Mark the submitted decision invalid, preserve actual lifecycle/context/authorization/failure/round/request/anchor fields, and do not call the evaluator. Exclude rejected decisions from the existing consecutive-success counter, preserving its prior behavior rather than treating retained authorization as a newly successful check.
- [`tests/test_experiment18a_schema_feedback.py`](../../tests/test_experiment18a_schema_feedback.py): nine offline tests, including all 21 supported kinds, unsupported and malformed input, invalid input before/after authorization, preserved terminal failure, no evidence-provider call for invalid input, retained context/impact blocking, and the real compiled greenfield Worker route with repeated invalid checks followed by an authorized write.
- This report: root cause, exact scope, before/after results and remaining limitations.

Invalid tool input neither grants nor revokes existing authorization. The valid-decision route, gate evaluator, validators, Context Sufficiency mutation guard and Impact Authorization guard are unchanged. No whitelist entries, completion budgets, contracts, permissions or policies were broadened. The direct gate evaluator's existing invalid-input semantics are intentionally unchanged; this patch corrects the already non-mutating tool pre-validation path.

## Focused before/after evidence

All results use Python 3.11.9 and the same tests against the published production baseline and patched source. The new fixture was strengthened before the final before/after comparison to assert actual state equality before checking the new invalid-decision marker. Both baseline logs remain preserved.

| Selection | Published production baseline | Patched source |
|---|---|---|
| `test_experiment18a_schema_feedback.py` | 9 methods, 7 failure records including subtests | 9 passed |
| `test_context_sufficiency_gate.py` | 9 passed | 9 passed |
| `test_greenfield_context_progress.py` | 9 passed | 9 passed |
| `test_repair_impact_anchor.py` | 3 passed | 3 passed |

**30 tests passed after the correction. No previously passing selected test regressed.** No unrelated suite was run.

The exact runner commands, interpreter and bootstrap are stored in local `evidence/*-results.json`; each suite has a separate raw log. Logical test command for each filename above:

```text
python -B -m unittest discover -s tests -p <filename> -v
```

Actual execution used a bootstrap that patched `mini.ask_ollama` and `mini.structured_model_call` to raise immediately on unexpected live calls. Individual deterministic test doubles temporarily replace those blockers where required. This provides offline mechanism evidence, not model inference or live recovery evidence. Process-local temporary storage and no-bytecode settings avoid changing existing environments or worktrees.

Before production changes: `run_focused.py before` ran the new fixture and all three existing selections. `run_focused.py before-state-reproduction test_experiment18a_schema_feedback.py` captured the strengthened state-comparison reproduction. After changes: `run_focused.py after` ran all four selections. These scripts and logs are LOCAL-ONLY EVIDENCE beside the isolated worktree, not historical evidence directories.

Additional checks: in-memory syntax compilation of the two modified source files and new test file; AST equality for evaluator/validators/context and impact guards against HEAD; `git diff --check`; original dirty checkout status/HEAD and eight dirty-file hashes; published implementation status/HEAD; all 174 original historical evidence hashes. All passed. During implementation and validation, no commits, pushes, PR actions or remote mutations were performed. Publication is a separately authorized follow-up.

## Remaining limitations before Run-010

- The model can still emit invalid decisions despite an advertised enum. Runtime rejection remains necessary.
- Preserving existing authorization is not granting new authority: denied impact, insufficient context, workspace containment and transaction validation still apply.
- The narrow Worker repetition safeguard does not bound every mixed-tool/recovery loop. Rejected decisions are not valid successful checks and do not become progress evidence.
- This patch does not establish productive live Repairer recovery, required game bridge/behavior success, optional greenfield wrapper activation, transaction acceptance or full Coin Courier completion.
- The Run-009 evidence does not preserve exact original rejected kind strings or full model-visible request bodies; these tests cannot reconstruct them.
- A controlled future run requires separate authorization and a fresh evidence directory. Run-010 has not started. Review this focused patch before deciding on further integration or execution.
