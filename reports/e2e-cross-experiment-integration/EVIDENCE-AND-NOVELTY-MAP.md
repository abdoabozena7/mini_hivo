# Evidence and novelty map

[Research entry](README.md) · [Findings](NEW-INTEGRATION-FINDINGS.md)

## Comparison against the actual PR #2 publication

The comparison inspected PR #2's body, 17 changed-file blobs, three commits and all eleven published reports at head `1e233845b3e9d26b10bb66238ec13a00f108356e`. Its existing runtime commits are not parents of this branch. No section below claims that previously recorded counts or failures were newly observed.

| Claim | What PR #2 already establishes | New research contribution here | What would be duplication and is excluded |
|---|---|---|---|
| **F1: effective cross-experiment coverage** | Selected CLI defaults and stages reached in the task. | For each Experiment 1–18, join implementation/test presence to selection, route activation, actual execution and the next evidence needed. | Rewriting experiment histories or copying earlier benchmark percentages. |
| **F2: Experiment 3 relationship and greenfield limitation** | Repeated context checks, two budget failures, no mutation; possible role of the optional progress policy. | Compare the earlier current-arm pattern; identify contract-dependent wrapper construction, null mission IDs and missing summaries. Existing tests inject contracts and do not close this route gap. | A second Run-006 chronology or treating the known 55-decision count as a discovery. |
| **F3: event 30 corroboration** | One generic invalid structured context decision. | Recover three whitelist errors from SQLite event 30; connect them to Experiment 18A; distinguish database tool success from decision validity. | Re-announcing the original Experiment 18A defect or inventing the rejected kind names. |
| **F4: feedback-retention hypothesis** | Generic uncertainty about instructions, history and feedback. | Identify the concrete append-then-prefix-compact path and define what next-request evidence could confirm or refute loss. | Claiming truncation caused the loop without the original model-visible payload. |
| **F5: controlled integration obligations** | Withheld ingestion changes and general recommendations for future validation. | Define matched common-source arms, route-aware observations and owner exit criteria; historical Run-006 alone is not controlled if ingestion changes. | Repeating the original acceptance checklist, runtime fix tests or unfinished assessment. |

Existing material remains the authoritative reference for [execution chronology](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/README.md), [Run-006's recorded counts/outcomes](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/RUN-006.md), [runtime fixes and test results](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/FIXES-AND-VALIDATION.md), and [original acceptance/setup](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/EXPERIMENT-SETUP.md). These are immutable public links, not relative references to files absent from team `main`.

## Repository evidence for the new joins

| Evidence ID | Reviewable source | Specific support |
|---|---|---|
| **S1** | [History](../../docs/EXPERIMENT_HISTORY.md), [architecture status](../../docs/PROJECT_STATUS.md), [reports index](../INDEX.md) | Research checkpoints, optional-policy limitations and distinction between approved-contract and full-request validation. Ancestry was checked, not inferred solely from labels. |
| **S2** | [CLI defaults](../../mini.py#L29635-L29666) and [Run-006 setup reference](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/EXPERIMENT-SETUP.md) | Effective selection versus treatment availability. |
| **S3** | [Experiment 3 JSON](../experiment3/rkey_01/report.json), [progress controller](../../hivo/worker_progress.py), [contract-supplied fixture](../../tests/test_experiment3_worker_progress.py#L64-L112) | Earlier non-progress signature, constrained-policy intent and limited fixture route. |
| **S4** | [Contract lookup](../../mini.py#L10381-L10417), [Worker invocation](../../mini.py#L19819-L19842), [wrapper guard](../../mini.py#L14425-L14456), [summary emission](../../mini.py#L15581-L15607) | Source conditions against which null mission IDs and absent summary events are interpreted. |
| **S5** | [Schema](../../hivo/context_sufficiency.py#L249-L276), [validator](../../hivo/context_sufficiency.py#L279-L302), [Experiment 18A diagnosis](../experiment18/EXPERIMENT18B_HANDOFF.md#4-experiment-18a-windows-context-sufficiency-diagnostics) | Independent schema/runtime discrepancy matching the recovered error class. |
| **S6** | [Re-anchoring](../../mini.py#L15245-L15268), [prefix compaction](../../mini.py#L3390-L3392), [4,200-character bound](../../mini.py#L652) | Conditional feedback-retention risk; not proof of actual payload loss. |
| **S7** | [Experiment 18B tool mismatch and controls](../experiment18/EXPERIMENT18B_HANDOFF.md#6-confirmed-tool-contract-mismatch) | Recovery-tool compatibility is a known downstream dependency, not newly exercised by Coin Courier. |

The [matrix](CROSS-EXPERIMENT-TRACEABILITY.md) supplies source/test/report references for each experiment. Tests were inspected as implementation evidence; no product test suite was run for this documentation-only contribution and no historical PASS is relabeled as a new result.

## Newly recovered and cross-checked local evidence

All locators in this subsection are **LOCAL-ONLY EVIDENCE**, relative to the preserved experiment root. They are plain identifiers, not inaccessible absolute paths or promised GitHub downloads. Raw databases, traces and source snapshots are not uploaded.

| ID / locator | Exact observation used |
|---|---|
| **T1:** `runs/run-006/workspace/.agent_runs/20261021T001124-cf9e7589.jsonl` | Lines 33/195: mission IDs null. Lines 180/340: completed budget failures with sufficient context and mutation/impact authorization. Full 361-line scan: zero progress/grounding summaries. Tool-bearing events total 28 checks for task 1, one listing plus 27 checks for task 2. |
| **T2:** `runs/run-006/workspace/.hivo/memory.sqlite3`, `events.id=30` | Task 2 context tool result: three whitelist-kind errors plus no accepted targeted request; decision non-final, permission false and failure code null. Database status `succeeded` is not validation PASS. |
| **T3:** same database, `events.id=31` | Following decision sufficient with mutation permission; no proof that new semantic evidence was obtained. |
| **T4:** same native JSONL, lines 38/44 | Program context estimates change from 3159 to 1489 after Worker 1's context check. This is metadata, not the original HTTP body. |
| **T5:** `runs/run-006/preparation/source-and-readiness.json`, `source-snapshot/` | Historical executable deltas/source identity, including withheld ingestion rewrites; basis for the matched-source requirement. |

The database was opened with SQLite `mode=ro&immutable=1`, avoiding journal/WAL creation. The bounded read used the existing `events` table and selected IDs 30/31. The original requested kind strings are absent from the stored result/details and are not reconstructed here.

Integrity identities, not claims of experimental truth:

| Material | SHA-256 |
|---|---|
| T1 native JSONL | `49b0a90f243b4d5d34ef3f51adff93a2b67bea407b7e25f1bbf54d02b6e06bf9` |
| T2/T3 SQLite database | `ceef93c9cdef14e2ae8b0ca534476826830e9f49106e61c368ecd0ceae85683e` |
| Original prompt file | `848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256` |

The publication workflow preserves hashes of 174 original evidence files and all eight pre-existing modified/untracked project files. It checks PR #2's metadata, commit list and changed-file blobs again after publication. It writes new documentation in an independent worktree; no original evidence or PR #2 file is rewritten.

## Novelty and claim-strength review

| Mandatory review question | Answer / publication boundary |
|---|---|
| What is genuinely new? | F1–F5 above: cross-experiment joins, recovered validator detail and route-specific comparison obligations. |
| Which new claims have direct evidence? | Event 30 errors, subsequent authorization, null IDs, missing summaries, source guards, policy defaults and earlier Experiment 3 records. |
| Which are hypotheses? | Actual feedback loss and its causal role; why the model repeats; whether schema or activation changes produce useful implementation. |
| Does every report add value? | Each has one distinct function: navigation, coverage, causal analysis, owner dependencies, experimental design, or evidence/novelty audit. |
| Is substantial old content duplicated? | No replacement run reports, copied prompt, benchmark survey, runtime fix/test listing or second final assessment. Limited counts/context are explicitly attributed to PR #2. |
| Are Experiment 3/18A relationships accurate? | Shared non-progress signature and corroborated schema error class; neither is declared a complete cause or completed fix. |
| Are all 18 classified without overstating coverage? | Each row separates availability, selection, activation/exercise, status and missing evidence. Diagnostics are not treated as product flags. |
| Are dependencies assigned correctly? | Mechanism/Experiment 18 owners implement; integration/smoke validates supported routes; E2E validates the reviewed combination and artifact independently. |
| Is publication documentation only? | The intended diff is exactly this six-file report folder, on a branch directly from team `main`. Product source, tests and PR #2 commits are excluded. |
| Is PR #2 unchanged? | No edit/comment/review request is part of this workflow; final verification compares its state, title/body, head/base, commits and files against the initial snapshot. |

This package documents observed integration limits, not that all experiments failed or that all optional flags should be enabled. It does not claim integrated Experiment 18 fixes or application acceptance. Unknown model-visible payloads and unavailable teammate work remain explicit evidence gaps.
