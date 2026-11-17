# Level 1 native verification evidence

Scope: a single source-bound literal text file, including the colon-delimited multiword syntax used by the original live request. This update has direct controlled functional evidence; live results are reported separately, never inferred from scripted tests.

**Level 1 passed in real Ollama run `20261021T224333-21e91d97`.** This is one independently corroborated completed literal-file run, not verification of complex applications or all future runs.

## Original observation

The [original-run summary](original-run-summary.json) was derived from the complete 141-record JSONL trace and 27 SQLite tool events for run `20261021T220853-7d601075`. A private ZIP snapshot and original byte hashes preserve the source records. SQLite was inspected read-only.

The retained original source text was `Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo`. The user-facing description added a space after the colon; the regression covers both forms. Context and impact authorization passed, and `write_file` reported success. Twenty-five shell verification attempts were refused. The Builder exhausted its budget and the transaction rolled back. Independent inspection now finds no output file. Neither the current workspace nor retained event details establish the transient file's original bytes; a successful write message is not exact-content proof.

## Established failure chain

1. The previous literal recognizer accepted a quoted or one-token payload, but not colon-delimited multiword text. It did not compile an exact-content digest for this source. The generic accepted impact candidate had 11 targets rather than the one source-bound literal target. Native literal readback and its required route were therefore unavailable for this request.
2. The model selected shell-like verification tools. The command allowlist correctly refused them. Recovery hints addressed mutation errors, not this rejected-verification pattern, so no native-route guidance or local refusal limit intervened.
3. Controlled verification exposed another integration gap: the `test_` filename made typed literal readback and rejected commands look like executable-test evidence. This introduced an inappropriate focused-test route and crowded the browser applicability carrier out of the bounded route list. Final aggregation could then be absent. The classifier now excludes refused tool actions and typed literal readback from executable-test evidence; the real literal route remains mandatory.

The update does not allow `cat`, `echo`, `ls`, `type`, inline Python/Node, or shell composition. It adds native guidance only from an accepted source-bound literal contract, removes `run_command` from that attempt's offered tools after refusal, and stops that tool loop after three rejected shell attempts if the model ignores guidance. Refusals stay failed evidence; no command is translated into a native proof or a claimed pass.

## Direct functional oracle

The [controlled replay](controlled-replay/result.json) uses eight scripted provider responses, with real context/impact gates, actual filesystem writes, two rejected verification attempts, Builder native readback, real Falsifier native readback, required verification aggregation, independent post-state comparison and transaction commit.

Observed: status `done`, `root_verified=true`, one Falsifier native readback, and a real `test_level_1.txt` containing exactly 15 UTF-8 bytes `Hello Mini Hivo`, no trailing newline. Its independent SHA-256 is `77fb7dd877d96222a20e410e6fd91151acca5a6bc5ee8f86e7a3f4499a5f6bdb`. Zero real model calls are used in this controlled replay. The persistent disposable artifact remains in the private replay workspace.

Reproduce from the repository root with a **new, nonexisting output directory**:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/level1_native_verification_replay.py --output-dir output/level1-new-replay
```

The harness refuses to overwrite an existing output directory. Its summary is an exported observation, not runtime authorization.

## Real Ollama progression

The [completed manual run](live-completed-result.json), workspace `list/project-9`, used actual `gemma4:e4b` responses and the exact stored request `Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo`. Inspection covered 73 trace records, eight SQLite tool events, preflight and metrics records, and direct readback of the persisted file.

Observed result: **done**, `root_verified=true`, one verified node, zero failed nodes, one Falsifier call and no budget exhaustion. Independent file inspection finds exactly 15 UTF-8 bytes `Hello Mini Hivo`, no BOM/newline, SHA-256 `77fb7dd877d96222a20e410e6fd91151acca5a6bc5ee8f86e7a3f4499a5f6bdb`. This matches both Builder `run_file` proofs. The Falsifier actually called **`read_file`**, returning that content; unlike the controlled replay, it did not call native `run_file`. Required literal-route aggregation and impact post-state comparison passed, and transaction commit is recorded. The conclusion is supported by artifacts, not solely the final agent response.

Remaining inefficiencies: one refused `cat` before native recovery, two writes, two native verification calls, 13 model calls, eight tool calls and 375.51 saved run seconds (about 6 minutes 16 seconds). The recorded `mini.py` hash matches current code and the earlier partial replay. Stored records do not independently pin every imported module.

The [earlier bounded real Ollama replay](live-result.json), run `20261021T223144-04cab4b6`, passed host/context/impact gates, created the exact file, attempted one refused `cat`, then obtained two native literal PASS readbacks. Independent inspection confirms the expected 15 bytes. It subsequently repeated context/write/read work instead of finishing. The 360-second harness limit interrupted it after 360.02 seconds, before Falsifier, transaction commit or Root completion. Eleven model requests and seven tool events were recorded. This original partial result remains unchanged. The later manual run reached the missing completion boundaries; success does not retroactively turn the interrupted run into a pass. Saved run duration and the earlier total harness wall limit have different timing scopes and are not a controlled speed comparison.

The manual launch command was reported as:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 mini.py --no-bootstrap
```

For a future reproduction, select a **fresh** workspace at the prompt and enter the exact request above. Do not overwrite `project-9` or previous evidence. The shell command itself is user-reported; model, request, workspace, tools and outcomes are independently corroborated. No new live run or test rerun was performed for this documentation-only confirmation. Level 2 was not started.

## Tests and limits

The [final 10-test regression](test_level1_native_verification-final.log) checks colon syntax and exact bytes, compound-source rejection, source obligations, rejected-command recovery through the final gate, bounded failure when native guidance is ignored, wrong-content rejection, unchanged command security, unaccepted/forged authority and classifier separation. The model boundary is scripted; runtime gates/readback are real.

[test-results.json](test-results.json) records exact commands, executed counts and individual outcomes for the fresh suites. Additional suites passed: lifecycle 17, impact 27, context 9, applicability 15, authority 23, experiment-focused 122 and adaptive 90. These regression checks are separate from the direct functional oracle and are not summed as unique coverage.

The verification-policy suite is **not green**: eight executed, six individual OK outcomes and two errors due to the missing historical `output/gemma-only-rescue-recursive-v9-hard-prompt.txt`. The [sanitized failed log](test_verification_policy.log) is retained. No replacement historical fixture or assertion suppression was introduced.

Reproduce focused tests:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p test_level1_native_verification.py -v
```

Use a writable temporary directory. Other suite commands are in the results JSON. Full discovery was not run: it includes known historical fixture dependencies and a live-calling requirement-compaction test. The earlier broad regression (before this update) was also failed: 1,376 executed, 24 failure records, 18 errors, 10 skips. No current broad-suite pass is claimed.

Development attempts, including failing regressions before the fix and intermediate test-harness errors, are preserved privately; only final suite outcomes are labeled final here. Previous Experiment 17 is a partial classifier protocol, not evidence of this update's live completion.

## Preservation and provenance

The [manifest](manifest.json) separates original raw input SHA-256 values from sanitized derivative hashes. Publication copies use LF and replace absolute machine paths while retaining test names, results and failure types. No source log, original run database or historical update record was changed. Publication requires staged Git-blob hash verification before the authorized push. Raw files can remain in earlier public history independently of current-tree curation.

Production source hashes tested by the controlled replay are in its result JSON. The investigation used a working tree based on `cca388d`; the complete Level 1 publication is now committed as `117342c`. The original investigation did not authorize publication; the later complete-update request explicitly authorizes a separate new PR.

## Complete-update publication — 22 October 2026

This package ships with all three implementation changes, the new regression suite, persistent replay harness, `AGENTS.md`, `updates/UPDATE_TEMPLATE.md`, and the full `updates/R_UPDATE_002.md` report. The previous PR #5 remains open and unchanged. The author selected a cumulative new PR to team upstream `main`, intentionally including its earlier commits and distinguishing them from the new Level 1 delta. The [file-by-file audit](PUBLICATION_AUDIT.md) records every initial modified/untracked path and the intended public scope; the [PR description](PR_DESCRIPTION.md) records the publication target and review boundaries.

[Fresh publication checks](publication-checks/results.json) repeat the relevant offline suites and controlled functional replay without new live-model experiments. Ten suites pass; verification-policy still has two authentic missing-fixture errors. Existing logs remain preserved. The [curated successful output](artifacts/test_level_1.txt) is byte-identical to the independently inspected project-9 file, with no newline. Hashes for all derived artifacts are in the manifest. No Level 2 work is included.
