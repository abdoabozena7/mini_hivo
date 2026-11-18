# Complete Level 1 native verification and document the real Ollama pass

## Dependency and review scope

This new cumulative PR targets **`kareem232003/mini_hivo:main`** from **`rodinaasfour665-ctrl:codex/level1-native-verification`**, as explicitly selected by the author. Team [PR #5](https://github.com/kareem232003/mini_hivo/pull/5) remains open, unmerged and unchanged. Its commits are intentionally included so this PR contains the complete relevant project snapshot, rather than requiring a separate merge first.

The upstream review boundary is `f842fb8...HEAD` (69 changed files). The new Level 1 delta is `cca388d...HEAD` (44 changed files); earlier dependency work is not attributed to Level 1.

| Already submitted in PR #5 | New in this Level 1 update |
|---|---|
| Initial literal greenfield impact authorization, source requirement propagation and native exact-byte proof route; lifecycle/context tests; sanitized impact evidence and publication rules. | Colon-delimited literal recognition; accepted-authority native guidance and bounded refusal recovery; literal-proof routing correction; ten new regression tests and replay harness; completed real Ollama evidence; full R_UPDATE_002 and permanent workflow/template. |

Review overlap with #5 is deliberate. Neither PR is merged or modified automatically; maintainers can choose their merge strategy after reviewing this cumulative PR.

## Why this update was needed

A real Level 1 request (`Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo`) wrote a file but exhausted its tool budget attempting forbidden shell verification, then rolled back. The initial PR's literal recognizer did not accept that colon-delimited multiword source. Correct command restrictions exposed missing native guidance and bounded refusal handling. Final-gate regression also exposed literal proofs/refusals being misclassified as executable tests because of the `test_` filename.

## What changed and what was fixed

- `hivo/requirements.py`: recognize the bounded colon-delimited literal payload while rejecting unsupported compound forms; preserve exact source-bound content and path obligations.
- `mini.py`: derive native `run_file` guidance only from accepted literal authority; remove the refused shell tool from that attempt's offered schemas; stop after three repeated refusals if guidance is ignored. No command is silently executed or converted into a passing proof.
- `hivo/verification_routing.py`: distinguish refused commands and typed literal proofs from executable-test evidence so the required literal route reaches the final gate.
- Add the complete ten-test Level 1 regression suite and persistent controlled replay harness, not selected excerpts.
- Include the full `updates/R_UPDATE_002.md`, all curated successful/failing/partial evidence, a provenance manifest and a byte-identical copy of the successful 15-byte output.
- Include `AGENTS.md` and `updates/UPDATE_TEMPLATE.md` to establish the permanent investigation, functional-verification, reporting and publication workflow. Scoped ignore/line-ending rules keep private runtime state local and derivative hashes reproducible.

The shell allowlist is unchanged: `cat`, `echo`, `ls`, `type`, inline interpreter commands and shell composition are not broadly enabled. Initial impact planning/native-proof functionality predates this update; only the additional corrections above are attributed here.

## Functional verification: controlled versus real model

**Controlled functional replay:** provider responses are scripted, while actual context/impact gates, writes, rejected commands, Builder/Falsifier native readback, required aggregation, post-state audit and commit are real. The persistent replay reaches `done`, `root_verified=true` and exact output. A fresh publication replay repeats that result. This is controller evidence, not a live-model reliability measurement.

**Completed real Ollama Level 1 run:** `20261021T224333-21e91d97`, `gemma4:e4b`, auto → baseline in a fresh workspace. Independent inspection covered 73 trace records, eight SQLite tool events, preflight and metrics ledgers, and final bytes. Stored outcomes: `done`, `root_verified=true`, `verified_nodes=1`, `failed_nodes=0`, `falsifier_calls=1`, `execution_budget_exhaustions=0`, `model_calls=13`, `tool_calls=8`.

The persisted file is exactly 15 UTF-8 bytes `Hello Mini Hivo`, no BOM/newline; SHA-256 `77fb7dd877d96222a20e410e6fd91151acca5a6bc5ee8f86e7a3f4499a5f6bdb`. Builder's two typed `run_file` proofs match that digest. The real Falsifier used **`read_file`**, unlike the controlled Falsifier's `run_file`. Required literal aggregation, independent impact comparison and transaction commit are recorded. **Level 1 passed in this run**; the conclusion does not rely on completion text alone.

The earlier bounded live run remains an interruption after native PASS, not retroactively a completed success. The original failure evidence is also retained separately.

## Additional regression checks

Fresh offline publication checks passed:

| Suite | Tests |
|---|---:|
| Level 1 | 10 |
| Existing literal lifecycle | 17 |
| Impact contracts | 27 |
| Context sufficiency | 9 |
| Verification applicability | 15 |
| Authority | 23 |
| Experiment-focused | 122 |
| Adaptive architecture | 90 |
| Project understanding | 32 |
| Model policy | 4 |

Counts are not unique-coverage totals. These regression passes are separate from the direct functional oracle. The verification-policy suite has six OK outcomes and two missing historical prompt-fixture errors; its failed log is included. No assertion was suppressed and no fake historical fixture was supplied.

## Reproduction

```powershell
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p test_level1_native_verification.py -v
.\.venv\Scripts\python.exe -B -X utf8 scripts/level1_native_verification_replay.py --output-dir output/level1-new-replay
```

Use a writable temporary directory and a fresh, nonexisting replay output. This replay is provider-free. The real run's reported interactive command is `.\.venv\Scripts\python.exe -B -X utf8 mini.py --no-bootstrap`; select a fresh workspace and enter the exact request above. Publication preparation did not rerun live-model experiments.

## Remaining issues and publication safety

- The real run still attempted one refused shell command, wrote twice, verified natively twice and took 375.51 saved run seconds (about 6 minutes 16 seconds). One pass does not establish efficiency, repeatability, complex-application correctness or Level 2 readiness.
- Full discovery was not rerun because of historical fixture dependencies and a known live-calling test. The earlier broad result remains failed (1,376 executed, 24 failure records, 18 errors, 10 skips). No universal green-suite claim.
- The source grammar is deliberately bounded. Original transient bytes in the first failed/rolled-back run are unavailable.
- Raw databases, generated workspaces, transcripts, machine inventories and the private historical `R_UPDATE_001.md` remain local. Selected exports preserve source/derivative hashes and test failures. Current-tree cleanup does not erase previously public history.
- No previous PR modification, merge, history rewrite or Level 2 work is included.

## Evidence and completeness

All links below are repository-relative for the committed PR description:

- [Complete update report](../../updates/R_UPDATE_002.md)
- [File-by-file inclusion/exclusion audit](PUBLICATION_AUDIT.md)
- [Evidence overview and reproduction](README.md)
- [Successful real-model record](live-completed-result.json)
- [Exact successful output](artifacts/test_level_1.txt)
- [Fresh suite commands/results](publication-checks/results.json)
- [Fresh controlled functional result](publication-checks/controlled-result.json)
- [Original/derivative provenance](manifest.json)
- [Persistent project instructions](../../AGENTS.md)
- [Reusable update template](../../updates/UPDATE_TEMPLATE.md)
