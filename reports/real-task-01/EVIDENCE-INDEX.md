# Evidence index and traceability

[Overview](README.md) · [Setup and exact prompt](EXPERIMENT-SETUP.md) · [Validation](FIXES-AND-VALIDATION.md) · [Assessment](FINAL-ASSESSMENT.md)

## Evidence access and labeling

This folder contains the published, cross-checked experiment narrative and bounded selected trace projections. **LOCAL-ONLY EVIDENCE** means a preserved file outside this repository's published reports; its path is printed as a relative locator, not a broken GitHub link. The experiment-root label denotes the original `real-task-01` directory; the PR-workflow-root label denotes the separate original publication-review directory. Machine-specific drive/user paths are intentionally omitted.

Source priority is: original native structured events/preflight records and captured errors; exact preparation/source snapshots and recorded test output; labeled observer summaries; historical narrative reports. Summaries were checked against native events rather than treated as their replacement. No raw log bundle, SQLite memory, temporary workspace, browser binary or withheld source snapshot is uploaded.

**Observed fact** means directly supported by a preserved event, file, or capture. **Verified test result** means a recorded executed test/compilation outcome. **Hypothesis** is a plausible explanation not isolated experimentally. **Missing evidence** means the record cannot establish the claim. These categories constrain the run reports and assessment.

## Run-to-failure map

All locators in the last column are **LOCAL-ONLY EVIDENCE**, relative to experiment root. The links in the first column target the reports actually committed here.

| Published report | First blocker / stopping point | Primary original locators |
|---|---|---|
| [Run-001](RUN-001.md) | Python import SyntaxError | `runs/run-001/logs/terminal-transcript.txt`; `runs/run-001/result.json` |
| [Run-002](RUN-002.md) | First canary, 30.595 seconds, 0/3 | `runs/run-002/workspace/.agent_host_preflight.json`; `runs/run-002/result.json` |
| [Run-003](RUN-003.md) | Three false conflicts; unanswered clarification, investigator stop | `runs/run-003/workspace/.agent_runs/20261020T233615-91477f88.jsonl`; `runs/run-003/logs/terminal-observation.txt`; `runs/run-003/acceptance/requirement-conflict-diagnosis.json` |
| [Run-004](RUN-004.md) | `TASK_BRAIN / REPOSITORY_EMPTY`, wrong existing-project mode | `runs/run-004/workspace/.agent_runs/20261020T235652-b35fb476.jsonl`; `runs/run-004/workspace/.agent_experiment.jsonl` |
| [Run-005](RUN-005.md) | `TASK_BRAIN / ENVIRONMENT_ERROR`, 120-second Specifier deadline | `runs/run-005/workspace/.agent_runs/20261021T000242-4abbf01c.jsonl`; `runs/run-005/workspace/.agent_experiment.jsonl` |
| [Run-006](RUN-006.md) | First Worker budget failure; second followed; root later interrupted | `runs/run-006/workspace/.agent_runs/20261021T001124-cf9e7589.jsonl`; `runs/run-006/result.json`; `CONTINUATION-RESULTS.json` |

Every run also has `acceptance/results.md`; no application acceptance is recorded as passed. Runs 001–002 have no task JSONL because task submission never occurred. Runs 003/006 lack normal finalized root metrics because the investigator stopped them. Absence is documented, not filled with a synthetic record.

## Setup and revision provenance

LOCAL-ONLY EVIDENCE at experiment root:

| Original locator | Use in these reports |
|---|---|
| `prompt.txt` | Exact text in [setup](EXPERIMENT-SETUP.md); same prompt throughout |
| `acceptance-criteria.md` | A1–A10 independent behavioral protocol, all NOT TESTED |
| `preparation-manifest.json` | Packages, model digest, browser, base revision and policies |
| `baseline/snapshot.json`, `baseline/workspace` | Immutable empty initial seed |
| `browser-readiness.json` | Existing browser discovery/blank launch only |
| `launch-run-001.ps1` through `launch-run-006.ps1` | Real interactive command, fresh-workspace guards, process-local configuration and transcript |
| `runs/run-002/preparation/validation-results.json` | Python compatibility reproduction, equivalence and original ten-test result |
| `runs/run-003/preparation/timeout-applied-validation.json` | Applied 180-second preflight delta and historical 20-test validation |
| `runs/run-004/preparation/source-and-readiness-final.json` | Actual final Run-004 launch snapshot; do not substitute earlier failed readiness file |
| `runs/run-005/preparation/source-and-readiness.json` | Local classifier revision and 95-test validation |
| `runs/run-006/preparation/source-and-readiness.json`, `source-snapshot/` | Exact five-production-file historical delta, new tests and 199-file hash set |

All six attempts derive from base `f842fb8fb6e63e3064891d26ee0b24981e55c847` plus the documented local deltas. The original experiment branch and its uncommitted work were preserved. The publication worktree separately isolated the three approved runtime changes. It is incorrect to label the final PR head as the exact historical source for Run-006.

## Small diagnostic excerpts

These excerpts preserve relevant error text or selected native fields; they are not claimed to be complete raw records.

### Run-001 import

```text
hivo/reentry.py, line 1189
SyntaxError: unterminated string literal (detected at line 1189)
```

This traceback is before task submission. The [compatibility analysis](RUN-001.md) explains why the closing quote is present yet Python 3.11 rejects the expression.

### Run-003 deterministic gate

```text
kind: source_requirement_ledger_created
requirement_count: 16
source_requirement_items_truncated: 0
kind: clarification_gate_evaluated
question_ids: Q-001, Q-002, Q-003
conflict_count: 3
```

Native JSONL lines 3–4. The full visible first question is a labeled observer transcription; the native gate event independently establishes the three conflicts, not the complete displayed wording.

### Run-005 deadline

```text
00:03:26.870 Specifier model_request
00:05:26.888 specification provider failure
could not reach Ollama at http://127.0.0.1:11434/api/chat: timed out
```

Host-local timestamps, October 21. The elapsed time supports the separate client deadline; it does not isolate why inference was slow or establish that the API server was absent.

### Run-006 authorization and child failure

Native line 180, selected fields:

```json
{
  "kind": "agent_finished",
  "role": "Builder",
  "task_id": "1",
  "status": "budget_exhausted",
  "context_status": "sufficient",
  "context_lifecycle_state": "MUTATION_ALLOWED",
  "mutation_authorized": true,
  "impact_authorized": true,
  "impact_contract_status": "IMPACT_CONTRACT_ACCEPTED"
}
```

Native line 206, selected fields:

```json
{
  "kind": "context_sufficiency_decision",
  "task_id": "2",
  "context_status": "insufficient",
  "final": false,
  "failure_code": null,
  "reason": "Invalid structured sufficiency decision; submit the bounded schema again."
}
```

Worker 2 later finished sufficient/authorized at line 340. The last event at line 361 is a Coordinator request, not a root verdict. [Run-006](RUN-006.md) provides the complete bounded sequence, counts, time context and interpretation.

## Fix-to-test and publication map

The source/test links below are valid repository links. Historical new ingestion tests are intentionally plain local locators because they are withheld.

| Attempted/published change | Mechanism evidence | Status |
|---|---|---|
| Python syntax-compatible conflict identity | [reentry](../../hivo/reentry.py), [authority tests](../../tests/test_authority_drift.py), [verified reentry tests](../../tests/test_verified_state_reentry.py); original six equivalence cases and 196-file compilation local | Published, PR #2 commit `6f6bbc273dc194811c82170e633896b1c67e4e56` |
| Host timeout 180 | [host preflight](../../hivo/host_preflight.py), [tests](../../tests/test_host_preflight.py); Run-003 real 3/3 canaries | Published, PR #2 commit `922270b46d661e7e577bbfb7d48d195d3b5e80a7` |
| Provider timeout 600 | [provider entry](../../mini.py), [transport tests](../../tests/test_model_transport_timeout.py), [context policy tests](../../tests/test_context_policy.py), selected retry tests in [test_mini.py](../../tests/test_mini.py) | Published, same second commit |
| Requirement-conflict scope rewrite | LOCAL ONLY: `runs/run-004/preparation/*test_requirement_conflict_scope.py.txt`, other clarification/project suites; publication `conflict-review.json` | Withheld: broader genuine-conflict regressions |
| Greenfield rewrite | LOCAL ONLY: `runs/run-005/preparation/before-test_greenfield_request_scope.py.txt`, `after-test_*.txt`; publication `greenfield-review.json` | Withheld: explicit existing-intent regressions |
| Worker progress | Run-006 native lines 41–184, 195–344; [progress source](../../hivo/worker_progress.py) and policy branches in [mini.py](../../mini.py) inspected without editing | Unresolved, no fix claimed |

Exact executed commands, test counts, original failures and what they prove are in [fixes and validation](FIXES-AND-VALIDATION.md). The seven final publication commands total 57 tests. Their recorded outputs are LOCAL ONLY under PR-workflow root, `validation/runtime-final/results.json` and `suite-1.log` through `suite-7.log`. The original review JSON counterexamples also live under that PR-workflow root, not inside the experiment directory.

## Unresolved-issue evidence map

| Question | Supporting observation | What remains unknown |
|---|---|---|
| Why no Worker progress after context PASS? | 55 context checks; final sufficient/authorized child outcomes; 56 total tools and zero mutations | Actual causal contribution of model, instruction retention, feedback or tool availability |
| Did Context Sufficiency reject the task permanently? | One invalid schema, `final=false`; 54 sufficient decisions | Independent semantic adequacy of the asserted context |
| Did Mutation Grounding block the writes? | No write/edit tool call; mutation/impact authorization true | Grounding behavior on an actual attempted edit |
| Did Behavioral Verification falsely pass? | No application, no browser/game verification result | All application/verifier behavior remains unassessed |
| Was the root a natural final failure? | Two completed child failures, then continued recursion; last request lacks response; investigator exit -1 | Natural root outcome if allowed to continue |

## Integrity identities and preservation

The publication update verified historical hash entries from `CONTINUATION-INTEGRITY.json` and `runs/run-004/preparation/previous-evidence.json`: **144 entries matched** (entries can overlap; this is not a claim of 144 unique files). A separate before/after inventory covers **174 original evidence files**, excluding the disposable browser/tools and temporary directories. It includes original reports, prompt, all run evidence and source/test snapshots. These checks are preservation checks, not cryptographic proof of experimental truth or application behavior.

Original checkpoint report identities:

| LOCAL-ONLY EVIDENCE | SHA-256 |
|---|---|
| `FINAL-REPORT.md` | `0f3b33c809c9ea91dc178265adefa4f0914651e42dfbca3accb6e40ca39251e8` |
| `CONTINUATION-REPORT.md` | `c99004ec3c69f989473b383a9d72ccbadc6983e84d587ab7731b4026561129ca` |
| `prompt.txt` | `848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256` |

Original narrative reports remain unchanged. Their time-specific conclusions and the subsequent withholding review are reconciled in the [overview](README.md); the older reports were not edited to erase failed attempts or unsuccessful proposed fixes.

Native task-trace SHA-256 identities (all LOCAL-ONLY EVIDENCE under the run locators above):

| Run | Native task JSONL SHA-256 |
|---|---|
| 003 | `00cbd2170434cca3f1e6febb283a78d1605986920d9a5da38ae9b765ba92cf54` |
| 004 | `93630a1117638ef441f659bcf279a5ba42f63e47959cb34db9f8b819a9cf1b34` |
| 005 | `51f11eb9a8fc2837252a99d61e6b6fd1842adc8a10984daf043b78b807c78596` |
| 006 | `49b0a90f243b4d5d34ef3f51adff93a2b67bea407b7e25f1bbf54d02b6e06bf9` |

Selected recorded-test identities make the principal historical claims traceable without uploading full outputs:

| LOCAL-ONLY EVIDENCE | Recorded result | SHA-256 |
|---|---|---|
| `runs/run-004/preparation/validated-test_requirement_conflict_scope.py.txt` | 9 tests, OK | `e68e3aa195e4f389f5da83dafe68f07a66963756438fed100e62a72cc190bbd1` |
| `runs/run-005/preparation/before-test_greenfield_request_scope.py.txt` | 4 tests, 3 failures | `5fcc66d53c99c29d33368d223ca60f9eed5f3a7424f0028bf63b95bf2baabd8b` |
| `runs/run-005/preparation/after-test_greenfield_request_scope.py.txt` | 4 tests, OK | `1107aea4512e2e34f29bc3216d48c91edbcdf028c3dcfd39e236e0491143eab1` |
| `runs/run-006/preparation/before-test_model_transport_timeout.txt` | 2 tests, 1 failure | `1473e79d341d946fed1a8cd85eb3dce4b5294ab053660dcb73401b1c30bd9ff1` |
| `runs/run-006/preparation/after-test_model_transport_timeout.txt` | 2 tests, OK | `beaa93ecbef9c00b837af230c30f6ddb697b2f5ec11b611e99c8527456d3152a` |

The preserved local test-runner scripts use unittest discovery or named-suite loading. Where exact historical shell strings are unavailable, run reports label direct CLI commands as equivalents. Final publication commands, in contrast, are retained explicitly in `validation/runtime-final/results.json` with exit codes and counts.

## Capture limitations and excluded materials

The Run-003 transcript is partial; its investigator question transcription is labeled. Later runs have PTY chunk captures, including 31 for Run-006, but these are tool-returned chunks rather than a complete raw OS terminal stream. At least one Run-004 chunk was truncated. Completed native metrics exist for 004/005, not for interrupted roots 003/006. Provider-side cancellation was not independently measured. No application screenshot or acceptance-test execution exists.

Large raw traces, full model packets, hidden memory databases, original machine-specific launch scripts, copied browser files, caches and temporary artifacts remain local. These exclusions preserve relevant diagnostic content in GitHub while avoiding upload of private machine state. If an investigation needs exact model messages or full replay, request the original local evidence through the team's appropriate private review process; no upload or remote sync of that material was performed here.
