# R_UPDATE_002 — Native verification recovery for the Level 1 literal-file request

## A. Update Identification

- **Date:** 21 October 2026, Africa/Cairo.
- **Publication preparation:** 22 October 2026, Africa/Cairo; complete implementation, tests, evidence and persistent workflow guidance.
- **Status:** Publication authorized as a new dependent PR; **Level 1 passed in completed real Ollama run `20261021T224333-21e91d97`**, independently corroborated below. Controlled tests remain separate; no general live-model reliability claim.
- **Branch:** `codex/level1-native-verification`.
- **Actual base:** `cca388daa3537030abdb7b6cf175d847f23b99ec`, including the prior literal verification implementation and publication cleanup. This is a dependent update, not an independent patch on upstream main.
- **Tested revision:** that base plus the uncommitted changes listed in section E. Tested production SHA-256 values are in the [controlled replay result](../evidence/level1-native-verification/controlled-replay/result.json).
- **Containing commit / PR:** recorded in Git history and the new PR metadata when published. Tested source identities are explicit; no future self-referential commit hash is invented.
- **Related scenario:** real Ollama Level 1 run `20261021T220853-7d601075`, model `gemma4:e4b`.
- **Completed live confirmation:** `list/project-9`, run `20261021T224333-21e91d97`, same model. The recorded `mini.py` hash matches the current source and the earlier partial replay; this evidence update changes no implementation.
- **Scope:** source-bound literal text requests, native verification guidance, bounded rejected-command handling and executable-test evidence classification. Command permissions, model settings and ordinary execution budgets are unchanged.

## B. Original Problem

The user wanted a real file `test_level_1.txt` containing exactly `Hello Mini Hivo`, without a newline. The retained source request is `Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo`; the user-facing description includes a space after the colon. Both forms are covered by the new tests.

Host preflight, context sufficiency and impact authorization passed. `write_file` reported success. The next 25 tool actions attempted shell verification using `cat`, `echo`, `ls` or `type`; all were refused by the allowlist. The Builder exhausted its 28-step model-loop budget, with 27 tool actions recorded, then the transaction rolled back. Root was not verified.

The [original summary](../evidence/level1-native-verification/original-run-summary.json) comes from all 141 JSONL trace records and all 27 SQLite tool events. The original run was snapshotted privately before investigation. Read-only inspection confirms that the output is now **absent**. The successful write message does not establish its transient bytes; those bytes were not retained in the inspected event details and cannot honestly be independently verified after rollback.

## C. Why the Update Was Necessary

The system had a native exact-content verification mechanism, but this ordinary spelling of the request did not acquire its source-bound contract. Correct command security then exposed a guidance/retry gap: refused verification was repeatedly attempted without progress. A task that wrote a file could neither prove completion nor retain the result. The fix must make valid native verification reachable while keeping shell restrictions intact.

## D. Root Cause Analysis

**Established source-routing cause:** `hivo/requirements.py::literal_file_request` recognized a quoted or single-token payload after `containing`, but not `exactly:` followed by unquoted multiword text. `_prepare_task_impact_contract` deliberately uses the original request, so the Coordinator's quoted paraphrase did not repair that gap. The original run created a generic 11-target impact candidate; acceptance of that candidate was not acceptance of a literal content digest. Thus `run_file`'s typed literal route was not applicable to that original source.

**Established recovery interaction:** the model chose `run_command`; its allowlist correctly rejected the commands. `tool_recovery_hint` had mutation/syntax hints but none for this verification pattern. The ordinary path had no refusal-specific bound for a recognized literal artifact. Model choice was the trigger, but controller recognition and guidance were causal integration gaps. The original trace does not archive every full prompt, so the model's internal reasoning is not knowable.

**Additional defect exposed by the controlled final-gate test:** `_is_focused_test_evidence` matched the `test_` target name even when evidence was a refused command or a typed literal readback. That generated an inappropriate executable-test route. Adding it to the bounded route list could crowd out the browser applicability carrier, leaving final aggregation absent. The regression explicitly requires the real final gate to contain a passing `LITERAL_ARTIFACT` route; a generic completion or absent aggregation is insufficient.

These findings are supported by the original records, source diff and fresh controlled assertions. They do not establish that every model or arbitrary greenfield request will now succeed.

## E. What Changed

### Changes since the previous PR

The preceding [team PR #5](https://github.com/kareem232003/mini_hivo/pull/5) introduced the initial literal greenfield contract, source requirement propagation and native proof route, followed by publication cleanup. At publication preflight it is **open and unmerged**. This update depends on its final head `cca388d`; it does not attribute that earlier functionality to the new patch. The author selected a cumulative new PR to team upstream `main`: inherited PR #5 commits are intentionally included, with the Level 1 delta separately identified. No merge/rebase or change to PR #5 is part of the work.

The additional defects were observed in the real Level 1 progression: colon-delimited multiword source did not acquire literal scope; refused shell verification lacked native guidance and a local retry bound; and typed proofs/refusals with a `test_` filename were misclassified as executable-test evidence. The new PR includes the **entire** three-file implementation delta, all ten new regressions, the replay harness, completed real-model evidence and permanent development/documentation workflow. No relevant source/test file is omitted because it began as untracked.


| File / functions | Change | Behavioral difference |
|---|---|---|
| `hivo/requirements.py::literal_file_request` | Add a bounded colon-delimited single-line payload form, including multiword and quoted contents; conservatively reject mixed/compound requests | The actual source can compile to one authorized path, three source obligations and the expected UTF-8 digest |
| `mini.py::_literal_artifact_verification_paths`, `tool_recovery_hint` | Derive native readback paths only from accepted, source-bound literal authority; explain that shell refusals did not verify anything and direct the model to `run_file` | Native guidance is actionable and authority-bound, not a command-permission workaround |
| `mini.py::execute_agent_task` | On refused shell verification under that authority, remove `run_command` from this attempt's offered schemas; stop its loop after three rejected attempts if guidance is ignored | The loop can recover via `run_file`, or fail before consuming its full step budget; refusals remain failed evidence |
| `hivo/verification_routing.py::_is_focused_test_evidence` | Exclude tool refusals and typed literal readback from executable-test evidence | A `test_` literal filename does not invent an executable-test obligation from these observations; the actual literal verification route is retained |
| `tests/test_level1_native_verification.py` | Add ten focused regressions, including positive leaf/Falsifier and negative security/content cases | Verify actual output and final aggregation, not just a task summary |
| `scripts/level1_native_verification_replay.py` | Add a provider-free persistent replay using real controller and filesystem, refusing existing output directories | Produce independently inspectable output and a result record without overwriting prior evidence |
| `evidence/level1-native-verification/` | Add selected sanitized observations, logs and provenance | Keep functional proof, regressions and failures reviewable without publishing machine paths |

Additional workflow/publication files are part of this same complete update:

- `AGENTS.md` and `updates/UPDATE_TEMPLATE.md`: persistent Observe → Investigate → Fix → Verify → Document → Review → Publish instructions and the reusable A–M report template.
- `.gitignore` and `.gitattributes`: scoped exclusions for four private generated test workspaces and canonical LF rules for curated evidence/workflow documents.
- `evidence/level1-native-verification/PUBLICATION_AUDIT.md` and `PR_DESCRIPTION.md`: complete inclusion/exclusion decisions and the professional new PR description.

No allowlist executable was added. Inline interpreter execution, shell composition and the rejected shell commands remain forbidden. The previous PR files, prior published evidence and historical numbered update were not changed. Existing untracked instructions, templates and user workspaces were preserved.

## F. How the Fix Works

The source parser extracts the filename and literal payload before model paraphrasing can change them. Existing requirement and impact compilation bind source IDs, the exact target and expected bytes. The existing context decision and deterministic impact acceptance still precede mutation.

If the Builder asks for forbidden shell verification, the original refusal is returned unchanged as failed tool evidence. A separate controller hint directs it to native `run_file`; the shell tool is removed from that literal attempt's model-visible schemas. Continuing to request it cannot execute it and eventually stops that loop at the third refusal. No shell call is silently rewritten into a proof.

`run_file` independently reads the actual bytes and emits the existing contract-bound literal proof. The classifier now distinguishes that proof from an executable test despite a `test_` filename. Real Falsifier readback and the required literal route reach final aggregation; independent impact post-state comparison precedes transaction commit. The positive functional replay asserts that every relevant final boundary passed.

## G. Functional Verification

| Scenario | Class / model boundary | Expected versus observed | Result / evidence |
|---|---|---|---|
| Exact Level 1 request, then refused `cat` and `echo`, then native readback | Controlled functional integration; eight provider responses scripted, gates/tools/filesystem/Falsifier/aggregation/commit real | File exists with exactly 15 UTF-8 bytes, one Falsifier native readback, final required literal route and post-state comparison pass | **Passed**, status `done`, `root_verified=true`; [result](../evidence/level1-native-verification/controlled-replay/result.json), [log](../evidence/level1-native-verification/controlled-replay.log) |
| Model ignores native guidance and repeats three rejected shell calls | Scripted provider, real gated tool loop | Third rejection terminates the loop before its 12-step test limit; no successful verification claimed | **Passed negative case** in [focused log](../evidence/level1-native-verification/test_level1_native_verification-final.log) |
| Wrong bytes with a claimed passing result | Scripted provider, actual write/readback and post-state audit | Native proof says FAIL; independent content audit rejects the state | **Passed negative case** in the same focused log |
| Missing/tampered authority; unsafe/compound source; command security | Focused integration/regression | No source-bound guidance from invalid authority; no scope for unsupported compound requests; shell restrictions remain | **Passed** in focused and existing lifecycle logs |
| Manual Level 1 run in `list/project-9` | Real local Ollama end-to-end; model responses not scripted | Exact file persists, Builder native proofs PASS, Falsifier reads the real file, required literal aggregation and impact comparison pass, transaction commits | **Level 1 passed for this run**, status `done`, `root_verified=true`; [completed live evidence](../evidence/level1-native-verification/live-completed-result.json) |

The persistent controlled artifact's independent SHA-256 is `77fb7dd877d96222a20e410e6fd91151acca5a6bc5ee8f86e7a3f4499a5f6bdb`, corresponding to exactly `Hello Mini Hivo`. There were zero real model calls in that replay. Source hashes and observations are recorded in its result JSON.

Controlled reproduction, from the repository root with dependencies installed and a fresh output name:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 scripts/level1_native_verification_replay.py --output-dir output/level1-new-replay
```

**Earlier partial real Ollama replay:** one fresh CLI auto-mode attempt was authorized and started with a 360-second wall limit, normal host preflight and unchanged model/runtime settings. Its final observed result is recorded in the live-results artifact referenced by section L; later success does not reclassify that interrupted trial.

Observed run `20261021T223144-04cab4b6`: preflight passed; the real model passed context and impact authorization, wrote the exact expected bytes, attempted one refused `cat`, then used native `run_file` successfully. Two native literal proofs report PASS and independent file readback confirms the same 15 bytes/digest as the controlled replay. The model subsequently repeated context/write/read operations rather than completing. The harness interrupted the process after 360.02 seconds. Eleven model requests and seven tool events were recorded; Falsifier, transaction commit and Root verification were **not observed**. This is partial live functional progress, **not a completed live end-to-end success**. See [live-result.json](../evidence/level1-native-verification/live-result.json).

### Completed real Ollama replay — Level 1 passed

The user subsequently ran the CLI manually in a fresh numbered workspace, `list/project-9`, using the reported command:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 mini.py --no-bootstrap
```

The exact stored request was `Create a text file named test_level_1.txt containing exactly:Hello Mini Hivo`. Read-only inspection of all **73 trace records**, all **eight SQLite tool events**, the metrics ledger, preflight record and final artifact corroborates the successful result for run `20261021T224333-21e91d97`. The exact interactive shell argv is user-reported rather than independently stored; the workspace, request, model and outcomes are independently recorded.

- Preflight PASS with 3/3 canaries; `NEW_PROJECT`, auto routing to baseline; context sufficient and impact created/validated/authorized once.
- Builder sequence: context decision, write, one refused `cat`, native `run_file`, another context decision, second write and second native `run_file`. Both typed native proofs bind the accepted contract and matching expected/actual content digest.
- **The real Falsifier used `read_file`, not `run_file`**, returning exactly `Hello Mini Hivo`. This differs from the scripted controlled replay, whose Falsifier performed native `run_file` readback. The completed live run's typed proofs came from Builder; the final required literal route and independent impact post-state comparison passed before commit.
- Actual persisted file: **15 UTF-8 bytes**, hexadecimal `48656c6c6f204d696e69204869766f`, no BOM or trailing newline. Independent SHA-256: `77fb7dd877d96222a20e410e6fd91151acca5a6bc5ee8f86e7a3f4499a5f6bdb`, matching both native proofs.
- Metrics and SQLite status: **done**, `root_verified=true`, `verified_nodes=1`, `failed_nodes=0`, `falsifier_calls=1`, `execution_budget_exhaustions=0`, `model_calls=13`, `tool_calls=8`, saved `elapsed_seconds=375.51` (about 6 minutes 16 seconds).
- The trace records required `LITERAL_ARTIFACT` aggregation PASS, `IMPACT_CONTRACT_PASSED`, and transaction commit. The result is not inferred from the final agent sentence alone.

The earlier harness trial stopped at its six-minute wall limit without Falsifier/Root completion. This separate manual trial continued to completion, including Falsifier, final checks and commit. Its saved run duration and the earlier total harness wall limit are different timing scopes; they are not a controlled performance comparison. We cannot infer that the interrupted trial would necessarily have completed if allowed longer. One refused shell command, repeated writes/readbacks and roughly six minutes remain inefficiencies, not reasons to disregard the established pass. See [live-completed-result.json](../evidence/level1-native-verification/live-completed-result.json).

For a future reproduction, launch the command above and select a **fresh** workspace at the prompt, then enter the exact request. Preserve `project-9` and earlier workspaces; do not rerun into them. No new model execution or tests were performed for this evidence-only confirmation.

## H. Additional Successful Tests

All results below were newly executed on the working source for this update. Each suite's exact command and individual outcomes are in [test-results.json](../evidence/level1-native-verification/test-results.json); invocation uses `.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover -s tests -p <pattern> -v` and a writable workspace-local temporary directory.

| Pattern | Run / passed | Failures / errors / skips | Relevance |
|---|---:|---|---|
| `test_level1_native_verification.py` | 10 / 10 | 0 / 0 / 0 | New source/route/retry/security behavior and direct functional oracle |
| `test_greenfield_impact_lifecycle.py` | 17 / 17 | 0 / 0 / 0 | Existing literal lifecycle, permissions and proof rejection |
| `test_pre_mutation_impact.py` | 27 / 27 | 0 / 0 / 0 | Impact contract behavior |
| `test_context_sufficiency_gate.py` | 9 / 9 | 0 / 0 / 0 | Context authorization preserved |
| `test_verification_applicability.py` | 15 / 15 | 0 / 0 / 0 | Existing applicability and required routes |
| `test_authority*.py` | 23 / 23 | 0 / 0 / 0 | Authorization regressions |
| `test_experiment*.py` | 122 / 122 | 0 / 0 / 0 | Existing experiment/harness regressions, not new live experiments |
| `test_adaptive_architecture.py` | 90 / 90 | 0 / 0 / 0 | Adaptive controller compatibility |

Do not add these as unique coverage totals or attribute all their pre-existing behavior to this patch. Direct functional proof is the real-artifact replay and corresponding assertions, not simply the count of passing regressions.

## I. Regression and Compatibility Impact

The verification-policy suite executed eight tests: six individual OK outcomes and **two errors**, both missing the authentic historical `output/gemma-only-rescue-recursive-v9-hard-prompt.txt`. See the [failed suite log](../evidence/level1-native-verification/test_verification_policy.log). The known fixture failure is retained; no substitute file, assertion change or skip was introduced.

Full discovery was not run because it includes historical fixture dependencies and a known live-calling requirement-compaction test. The earlier broad comparison recorded 1,376 executed, 24 failure records, 18 errors and 10 skips; that historical result remains failed and does not establish current broad compatibility.

The new source recognizer conservatively supports the declared colon syntax, not arbitrary unquoted prose, multiple operations or every content format. Existing quoted/single-token syntax, unsafe-path rejection and existing-project approval retain their regressions. Typed literal readback remains distinct from genuine executable test evidence; normal unittest evidence is explicitly checked by the new classifier regression.

Development runs were not all green: the initial eight new tests exposed five failure records and two errors before the fix; an intermediate final-gate test exposed absent aggregation; an expanded test initially used the wrong result dictionary key and was corrected. Those raw logs are preserved privately. Final new tests and the persistent controlled replay pass on the final source; intermediate outcomes are not labeled final successes.

## J. Overall Impact

For the tested Level 1 source form, literal scope and exact-content verification now reach the existing controller boundaries. Rejected command feedback points to the appropriate native tool, repeated refusals are bounded locally, and test-like filenames no longer turn literal proofs or refused commands into executable-test evidence. Controlled execution produces and verifies the actual requested file while retaining authorization and command security.

This establishes correctness for the measured controlled cases. It is not evidence of universal reliability, a fully green test repository, or successful arbitrary live-model execution.

The separately inspected manual run now also establishes **one completed real-model Level 1 pass** for this literal-file scenario. It does not establish Level 2, complex-application correctness, a success rate, or a guarantee for later runs.

## K. Remaining Limitations

- Original transient bytes cannot be recovered from the retained records after rollback; only the successful write message and subsequent removal are established.
- Real live replay results must be assessed independently; one attempt cannot establish reliability across runs or task families.
- The earlier bounded attempt remains interrupted and lacks Falsifier/Root completion. The later manual run does complete those boundaries, so live Level 1 completion is now verified for that run only. Completion latency and redundant work remain follow-up concerns; no new stopping policy is introduced by this documentation update.
- The completed run still made one refused shell attempt, two writes and two native readbacks, taking 375.51 saved run seconds. One successful run does not establish repeatability or efficient execution.
- Unsupported/ambiguous source syntax remains outside the bounded literal compiler. Additional duties must not be silently converted into literal-only authority.
- The local refusal bound controls one tool loop; it does not replace existing higher-level failure handling or authorize an alternative operation.
- Historical fixture errors and final-source broad discovery remain unresolved/unexecuted. No browser installation, model change or expensive historical experiment batch was performed.
- At the original investigation checkpoint these derivatives and this document were uncommitted. The authorized publication subsequently committed the complete Level 1 update as `117342c` after staged-blob integrity and privacy checks. The previously public raw evidence is not erased by this work.

## L. Evidence and Reproduction

- [Evidence overview](../evidence/level1-native-verification/README.md): scope, diagnosis, functional oracle and reproduction.
- [Original run summary](../evidence/level1-native-verification/original-run-summary.json): full trace/tool-event inventory, snapshot hashes and rollback limitation.
- [Controlled replay result](../evidence/level1-native-verification/controlled-replay/result.json): exact bytes, source hashes, native Falsifier and final gate observations.
- [Bounded real Ollama outcome](../evidence/level1-native-verification/live-result.json): exact file creation and native PASS, followed by repeated work and wall-limit interruption; no live Root success.
- [Completed manual real Ollama outcome](../evidence/level1-native-verification/live-completed-result.json): independently observed exact bytes, Builder proofs, actual Falsifier `read_file`, final aggregation, post-state PASS, commit and completed metrics. **Level 1 passed in this run.**
- [Fresh suite commands and results](../evidence/level1-native-verification/test-results.json): individual outcomes, including the failed verification-policy suite.
- [Original/derivative manifest](../evidence/level1-native-verification/manifest.json): preservation and LF sanitization provenance. Original hashes identify untouched raw bytes; publication hashes identify sanitized LF copies. At the original investigation checkpoint nothing was staged; the later publication validated all 27 derivative hashes against staged Git blobs.
- [Regression source](../tests/test_level1_native_verification.py) and [persistent replay harness](../scripts/level1_native_verification_replay.py).

Original run files and private intermediate logs remain in their original/local audit locations with byte hashes and a snapshot backup. New trial outputs use fresh directories. Public copies replace personal absolute paths and omit host inventories. No original logs or `R_UPDATE_001.md` were modified.

## M. Summary for the Team

**Proposed PR title:** Fix native verification routing and rejected-command recovery for literal text requests

**Why needed:** A real Level 1 request wrote a file but exhausted its tool budget trying forbidden shell verification, then rolled back without verified completion.

**What changed / fixed:** Recognize colon-delimited literal payloads, provide accepted-contract-bound `run_file` guidance, bound repeated refused commands and separate native literal proofs/refusals from executable-test evidence. The command allowlist remains unchanged.

**Functional verification:** The exact-content controlled replay exercises real gates, write, two refused commands, Builder/Falsifier native readback, required aggregation, independent post-state audit and commit. Observed status is done, Root verified, and the file has exactly the expected 15 bytes. Model decisions are scripted, not live reliability evidence.

**Real-model confirmation:** Manual Ollama run `20261021T224333-21e91d97` independently confirms Level 1 PASS: the exact 15-byte file persists; Builder native proofs, Falsifier `read_file`, final required literal aggregation, impact audit and commit are recorded. Metrics report done, Root verified, one verified node, zero failed nodes, one Falsifier call and no budget exhaustion. This real run is distinct from the controlled replay.

**Additional tests:** Ten new regressions and the existing lifecycle 17, impact 27, context 9, applicability 15, authority 23, experiment-focused 122 and adaptive 90 all pass. The verification-policy suite has six OK outcomes and two missing-fixture errors. Full broad compatibility is not claimed.

**Remaining issues:** See the separately recorded bounded live result, unavailable original transient bytes, limited source grammar and historical fixture dependencies. No universal/live-success claim follows from the controlled result.

The earlier bounded live trial remains interrupted before Falsifier/Root completion; the later manual run completed successfully. Remaining inefficiencies are one refused shell command, repeated writing/native verification, 13 model calls and 375.51 saved run seconds. Repeatability and more complex scenarios remain unverified. No Level 2 work was started.

**Publication scope:** The complete update was committed on `codex/level1-native-verification`. The selected new PR targets team upstream `main` and intentionally includes inherited PR #5 changes alongside the complete Level 1 delta. The preceding branch/PR remains unchanged and private raw workspaces remain local. Actual publication identifiers are recorded in Git/PR metadata.

### Complete-update publication checks — 22 October 2026

The later publication request authorizes one new PR for all of this update, including the previously untracked instructions and template. See the [complete inclusion/exclusion audit](../evidence/level1-native-verification/PUBLICATION_AUDIT.md) and [new PR description](../evidence/level1-native-verification/PR_DESCRIPTION.md).

Fresh offline checks on the unchanged implementation passed Level 1 (10), lifecycle (17), impact (27), context (9), applicability (15), authority (23), experiment-focused (122), adaptive (90), project understanding (32) and model policy (4). The verification-policy suite again records six OK outcomes and two missing historical prompt-fixture errors. A fresh persistent controlled replay again reached exact-byte output, real Falsifier native readback, final aggregation and Root verification. Full discovery and live-model trials were not rerun for publication. Exact commands and outcomes are in [publication-checks/results.json](../evidence/level1-native-verification/publication-checks/results.json).

The successful manual run was independently rechecked against the persisted 15-byte artifact, stored metrics and final trace gates. A [byte-identical curated copy](../evidence/level1-native-verification/artifacts/test_level_1.txt) is included with source/derivative hashes. Raw databases and generated workspaces remain private; earlier failed/partial evidence remains separate.
