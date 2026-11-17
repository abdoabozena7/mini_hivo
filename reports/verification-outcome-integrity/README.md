# Verification-outcome integrity: local implementation and validation

## Isolation and scope

Branch `fix/verification-outcome-integrity`, in a new isolated worktree based exactly on published Run-010 commit `2a8b94590734cec3375047a18e0dc71df2476f85`. This patch is uncommitted and unpublished. No existing worktree, branch, PR or historical run was modified. No model inference, browser session, full E2E attempt or Run-011 was started.

## Confirmed failure and actual replay

Run-010 native trace line 121 reported aggregate `passed: true` and browser `result: PASS` while retaining `actual_result: FAIL`. SQLite verification events 9 and 10 contain failed game checks of 3,121 and 3,141 characters.

The Worker stored `str(result)[:1600]`. Both prefixes are invalid JSON. Routing `_parse_result` then fell back to a success-word regex that matched the JSON field name `passed` despite its false value. Aggregate route precedence could overwrite the controller's failure with that false pass. Independent final quality checks still rejected the leaf; this is not evidence of successful transaction acceptance.

A read-only offline replay used preserved native line 118 routes, tool events 1–14 and the failed event 10 browser payload. Executing the published baseline routing source against its old 1,600-character projections produced aggregate PASS / browser PASS. Corrected producer/routing produced aggregate FAIL / browser FAIL from the same inputs. The replay JSON is preserved locally; historical inputs were neither edited nor uploaded.

## Exact files and functions

- [`hivo/evidence.py`](../../hivo/evidence.py), new `project_tool_evidence_result`: short results remain unchanged; long structured verification results become bounded valid JSON preserving outcome, target, profile, interaction facts, failure codes and supported identity fields. Display prose is omitted/shortened, with a full-output hash. Oversized retained proof becomes explicit unavailable evidence (or retains explicit failure), never a clipped positive claim. Long unstructured command output needs an explicit exit receipt; existing concrete failure detection still wins. Non-verification display projection remains unchanged.
- [`mini.py`](../../mini.py), `execute_agent_task`: replace only the unsafe evidence slice with that projector and bind each evidence item to its producing role. Raw tool transcripts/event storage and model-facing tool responses remain unchanged.
- [`hivo/verification_routing.py`](../../hivo/verification_routing.py), `_parse_result`: parse structured results once; explicit failure wins over conflicting success labels. Incomplete/malformed JSON, structured arrays, code fences and statusless objects cannot acquire a PASS through word matching. Legacy exit receipts and supported plain-text result handling remain available.
- Same routing file, `_evidence_matches`: browser receipts must match the actual target, not merely the tool name.
- Same routing file, `_aggregate_verification_routes`: in the ordinary legacy route, current controller failure cannot be overwritten by older/weaker receipts, and a cached route label is not execution proof. A newer equivalent receipt can supersede older evidence only within the same explicit role/target/profile; weaker profiles, other roles and outstanding Falsifier failures are retained. Existing explicit semantic-policy routing and approved authority/direct-oracle processing remain separate and unchanged.
- [`tests/test_verification_outcome_integrity.py`](../../tests/test_verification_outcome_integrity.py): minimal offline fixtures shaped from Run-010; 30 producer/parser/aggregation, real Worker-boundary and quality/transaction-control tests.
- This report: evidence, exact validation scope and limitations.

Producer audit: the affected shared Worker evidence path serves Builder, Falsifier and Repairer. `update_memory` records the full result before its existing storage policy; model-facing tool messages keep the full result. The fresh parent-verification path already emits structured proof dictionaries and is untouched. No general prompt-compaction, Builder completion, scheduler, browser requirements, authorization or recovery policy was changed.

## Focused tests and exact results

The original 20-method regression file ran before production changes and produced 15 failure records and 9 errors (including subtests and references to the not-yet-added projector). Additional scope/repair controls expanded the earlier suite to 26 methods; four additional supersession regressions bring the current suite to 30 methods. Initial diagnostic fixture failures are retained in local logs, not presented as passing evidence.

| Suite | Published production baseline | Final reviewed patch |
|---|---:|---:|
| `test_verification_outcome_integrity.py` | Original 20 methods reproduced failures/errors | 30 passed |
| `test_evidence_policy.py` | 9 passed | 9 passed |
| `test_verification_applicability.py` | 15 passed | 15 passed |
| `test_experiment11_evidence_compatibility.py` | 10 passed | 10 passed |
| `test_experiment13_monotonic.py` | 9 passed | 9 passed |
| `test_experiment18a_schema_feedback.py` | 9 passed | 9 passed |
| `test_context_sufficiency_gate.py` | 9 passed | 9 passed |
| `test_greenfield_context_progress.py` | 9 passed | 9 passed |
| `test_repair_impact_anchor.py` | 3 passed | 3 passed |

**103 distinct selected tests passed after the receipt-supersession correction: 30 new plus 73 existing.** The previous reviewed checkpoint had 99 passing tests; its logs remain preserved. These are not accumulated intermediate reruns or a full-suite claim. No previously passing selected test failed.

The authority-closure suite `test_v25_6_execution_verification_authority_closure.py` was attempted on baseline and initial patch: both ran zero methods and failed setup because the ignored historical fixture `output/hivo-v25-5-stage6c-b-precommit-invariants-live-2/artifacts/stage5a_route_bindings.json` is absent. It was not rerun after that unchanged prerequisite was established. No fixture was copied or invented to make it pass, and full authority-closure coverage is not claimed.

Command form per suite:

```text
python -B -m unittest discover -s tests -p <suite-filename> -v
```

Actual execution used the local `run_focused.py` bootstrap, patching `mini.ask_ollama` and `mini.structured_model_call` to raise on unexpected live calls. Deterministic test replacements execute the production Worker/gates/file tools; no provider was contacted. Exact interpreter argv and outputs are LOCAL-ONLY EVIDENCE in sibling `evidence/before-results.json`, `after-results.json`, `final-reviewed-results.json` and individual logs. The published-baseline routing source was evaluated in memory for the separately recorded `run010-offline-replay.json`.

## Additional receipt-supersession correction

Final review found that deduplication selected the newest same-role/target/profile receipt before parsing its outcome. An incomplete receipt therefore displaced an earlier valid FAIL, allowing a separate controller PASS to satisfy the route. This was an aggregation defect, not evidence that a repair had succeeded.

The focused pre-fix run executed 30 methods and recorded four failing subtests: `passed: null`, `NOT_RUN`, `PENDING`, and a statusless object, each retaining the same profile as the prior failure. A malformed-JSON control already failed closed and remains covered. After correction all 30 methods pass.

`_aggregate_verification_routes` now permits equivalent-receipt replacement only for parsed, available PASS/FAIL outcomes. Unavailable or malformed entries remain independent and cannot erase an outstanding failure. A later valid PASS still supersedes the earlier FAIL only within the existing exact role/target/profile identity. Different roles, targets, weaker profiles, and a later valid FAIL remain protected. Existing controller-failure precedence and authority/semantic-policy routes are unchanged.

Freshness in this legacy path means chronological receipt order within the supplied execution evidence. This correction does not add artifact-hash binding, timestamps, or proof that a repair occurred; separate authority and quality gates retain their existing responsibilities. A valid controller result remains an independent evidence source, but unavailable evidence cannot cancel an outstanding explicit failure.

Local-only before/after records: sibling `evidence/supersession-before-results.json` and `evidence/supersession-after-results.json`, with per-suite logs. Reproduction used the same offline bootstrap described above; no model or browser was invoked.

## Fresh repair and protected transaction controls

The positive repair control uses the existing greenfield test fixture, declares its expected artifact file in the existing controller-contract input, and traverses real contract construction/acceptance, actual Repairer read/edit tools, a fresh content oracle and the unchanged commit boundary. It restores the originally required content and commits with fresh verification; the old failed scope remains failed independently.

An exploratory attempt using the fixture's original free-text impact target inference passed fresh verification but failed precommit: ordinary words from the task goal were interpreted as required targets. An attempted task-level hint was not propagated through the existing wrapper; the valid control therefore uses the supported controller-contract target input. No accepted contract was fabricated or guard disabled. A separate final negative test retains the original inference path and confirms unmet impact targets still prevent commit. This pre-existing impact-target behavior is outside the approved fix and remains a follow-up limitation.

Other new cases cover long failed/successful JSON, unsupported structured shapes, conflicting status/boolean fields, missing proof, wrong targets, weak-profile passes, cached labels, Falsifier failure retention, role/profile-bound freshness, explicit command exits, source-error diagnostics, overflow and identity preservation.

## Review and preservation checks

`git diff --check`, new-file whitespace/link checks and in-memory syntax compilation passed. AST comparisons allow changes only to the producer and the three routing functions above; final quality checks, `evidence_gate`, `_commit_verified_leaf`, Context Sufficiency/Impact guards, planning and recovery functions are unchanged. A diff review caught and removed an accidental Unicode-encoding change before the final test run; no unrelated strings remain changed.

All eight pre-existing worktrees retain their original HEAD/status and dirty-file hashes. All 230 captured Run-010 evidence files and all 174 original historical evidence hashes match preservation records. Git HEAD remains the exact base commit; nothing is staged, committed, pushed or published. No GitHub write operation occurred.

## Remaining risks and review boundary

- This is offline mechanism validation, not live Repairer recovery, game completion or full system acceptance.
- Oversized retained proof is conservatively unavailable. The compact projection is not a complete replacement for raw evidence or every future receipt format; full event data remains the diagnostic source of truth.
- Unknown-role history is conservative and is not automatically superseded. The new role field enables narrow equivalent-receipt freshness for new Worker evidence; arbitrary old failures are not erased by any later pass.
- Explicit semantic policies retain their existing separate behavior; selected Experiment 11/13 tests passed, but missing historical authority fixtures limit broader certification.
- Pre-existing impact-target inference, child verification scope, Worker completion reporting and provider prompt retention remain separate issues. They were not bundled into this patch.
- Run-011 still requires separate approval. No claim is made that this correction alone will make Coin Courier complete autonomously.

The patch is ready for local implementation review with these limitations disclosed. Do not commit or publish it without explicit approval.
