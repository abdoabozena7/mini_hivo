# R_UPDATE_007 — Use exact source proof instead of duplicate model review

## A. Update identification

- **Date:** 2026-11-18 (UTC+02:00). **Branch:** `audit/decision-evidence`, local and uncommitted. This update builds on the uncommitted [R_UPDATE_006](R_UPDATE_006.md) implementation at Git `4096ccc3b405b2ed487040400e757d83c03df4ae`.
- **Measured runtime SHA-256:** baseline `84abeac0981598768c1f3c54a1f154c7a78660d7e05fa10b3793b82fed422f4a`; candidate `8908c10629bf1e6e2656a5cc3c633e55f5edb7515705268abd21eb3ad5f9fe53`. Same ordered `relative-path:SHA256-of-file-bytes` manifest convention as R_UPDATE_006.
- **Harness:** installed HarrTest 4.1.0; direct optimization of a single existing verifier path. **Verification scope:** current-source offline checks and two paired live local-model text-file cases. No larger task or publication is claimed.

## B. Original problem

The user asked to continue the optimizations. On the prior implementation, the controller performed independent source-bound readback, then asked the model to review the same result. A fresh baseline for `Create a text file named lifecycle-check.txt containing exactly:DECISION_READY` saved the correct 14 bytes and spent **two model calls** in the review. The tested readback path also crashed on a missing file: the native failure was plain text, but the collector expected JSON.

## C. Why this update was necessary

For a narrowly defined request, the file path and exact bytes can be checked without predictions about intended behavior. The extra review adds model cost but cannot replace that proof. A failed readback must be recorded as a failure, not throw before the gate can act on it.

## D. Root cause

[`falsify_task`](../mini.py) used task risk to select the model review even after a complete source assertion passed. There was no exclusion for a verified, standalone literal artifact. Its source evidence collector assumed every failed verifier returned JSON, although `run_file` can return a plain-text filesystem error.

## E. What changed

| File | Change |
|---|---|
| [requirements.py](../hivo/requirements.py) | Add a strict recognition mode for a standalone literal: explicit colon delimiter, simple `.txt` basename, and a single token or a quoted payload. Existing literal parsing remains unchanged for other callers. |
| [mini.py](../mini.py) | Allow the fresh native readback to finish the review only when it covers the complete source ledger and matches the sole authorized target and current impact contract. Represent unavailable literal readback as a structured FAIL. Record a counter and a run event when model review is unnecessary. |
| [test_level1_native_verification.py](../tests/test_level1_native_verification.py) | Exercise real filesystem/verification/rollback behavior with scripted model replies and controls for broader scope and an extra acceptance criterion. |

## F. How the optimization works

An eligible new-project root first uses the normal Builder and mutation authorization. The controller reads the persisted provisional bytes and compares the SHA-256 against the source requirement. The verifier takes the deterministic route only when the original request, source ledger, task acceptance criteria, single allowed path, and fresh readback all agree. An extra constraint, confirmation, approval-bound plan, or unsupported literal syntax keeps the ordinary path. The Builder completion check, deterministic evidence gate, impact validation, and commit/rollback still run; neither a model claim nor a missing file can provide a PASS.

## G. Functional verification

The public batch CLI ran Gemma `gemma4:e4b` (digest `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`) on Python 3.13.7 in four fresh workspaces. The two revisions used equal limits: 18 task model calls, 25 proposed tool calls, and a 120-second task admission deadline. The observed order was baseline single, candidate quoted, baseline quoted, candidate single. Normal preflight completed all three canaries each time. The shared-host QA guard disallowed execution of generated code; it did not substitute the model or the controller. An external process read the saved artifact after CLI exit and compared its exact bytes and output inventory.

| Exact request and expected UTF-8 bytes | Baseline: run ID, calls, reported tokens | Candidate: run ID, calls, reported tokens |
|---|---|---|
| `Create a text file named lifecycle-check.txt containing exactly:DECISION_READY` → `DECISION_READY` (14 bytes) | `20261118T184243-b3cb7a62`: 10, 21,588 | `20261118T185020-643b55f2`: 8, 18,015 |
| `Create a text file named proof-paired.txt containing exactly:"Ready for review."` → `Ready for review.` (17 bytes) | `20261118T184920-9eaa363a`: 11, 23,255 | `20261118T184819-b72ab79e`: 9, 19,720 |

All four exited 0, selected the same `auto` → `baseline` route, and saved the expected bytes without a newline or another user-visible output. Respective SHA-256 digests matched across arms: `7600a986a22cdd440d20f201e55b48f7a2af6ab43bbee710d92275fe092343aa` and `831f459250b9f3c646ab17f5ea11e48ced5c55d8be471eda0737eba9d8c46a10`. The model review used two requests in each baseline and none in either candidate. Task totals: **21 → 17 model calls**, **10 → 8 proposed tool calls**, and **44,843 → 37,735 reported input-plus-output tokens (15.85% fewer)**. Reported token fields were present for every task attempt; preflight calls are not included.

**Controlled functional controls:** Model replies only were scripted. The native readback kept the exact file and punctuation when valid, rejected a missing file with a structured FAIL, and rejected the wrong bytes even though the Builder claimed completion. The wrong provisional file was observed in the real Repairer path; with no successful repair, the rollback left no file. An extra success criterion and a non-closed request kept model review.

## H. Additional successful tests

Five focused offline suites (literal lifecycle, literal parser, greenfield impact, clarification, and verification outcome integrity) ran with unexpected provider transport blocked. The same final tests satisfied **120/122** on the pinned base (one failure and one error) and **122/122** on the candidate, no skips. The two baseline observations were the redundant review and the missing-file decoding exception. The matched offline count includes the controlled tests above; it is not additional coverage.

## I. Regression and compatibility

The initial negative fixture forced zero repairs and hit a separate assumption about repair history on both arms. It was replaced with scripted normal Repairer refusal, making the final comparison exercise the supported rollback path without changing the product's repair budget. Both fixture versions and their results are retained. The final offline suites include authorization and verification negatives. No full discovery or application-wide live run was performed.

## J. Overall impact

The measured literal requests cost less without weakening the exact-output requirement. This is measured savings within one verifier class, not evidence that the smaller model improved or that decomposition boosts quality. Observed task times were 40.28 → 31.63 seconds and 44.50 → 35.20 seconds; one observation per pair is not a latency benchmark.

## K. Remaining limitations

Multi-file, ambiguous, existing-project, and behavior-based work are not covered by this optimization. Both live requests were development fixtures and selected the focused path; the study does not estimate reliability on a population. A future study of adaptive splitting must hold proof coverage and verification policy constant, or test their effects separately. See the [research note](../docs/RESEARCH_AUDIT_NOTE.md).

## L. Evidence and reproduction

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_level1_native_verification.py -v
```

The other offline selectors were `test_literal_parser_regression.py`, `test_greenfield_impact_lifecycle.py`, `test_requirement_clarification.py`, and `test_verification_outcome_integrity.py`, with `mini.http_get_json` and `mini.http_post_json` guarded against unplanned requests. The live wrapper launched `python -B mini.py --workspace <fresh-dir> --prompt-file <fixed-request> --model gemma4:e4b --no-bootstrap --max-model-calls 18 --max-tool-calls 25 --max-elapsed-seconds 120`. The pinned uncommitted baseline, actual outputs, and separate `result.json`, CLI and offline logs per attempt are retained under the ignored `.runtime-proof` run directory `closed-literal-review-20261118`. Nothing is staged.

## M. Summary for the team

**Proposed PR title:** Skip duplicate model review when exact source proof covers the entire text-file request.

**Proposed body:** Keep authorization, independent readback, and final commit gates intact. Use a deterministic review only for a closed `.txt` request, and keep a missing readback as an explicit failure. Both matched live pairs delivered identical, independently accepted artifacts while saving four model calls and 15.85% of reported task tokens. The focused offline suites passed 122/122. Local changes only.
