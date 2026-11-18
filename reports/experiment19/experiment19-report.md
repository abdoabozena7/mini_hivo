# Experiment 19 — Verification Outcome Integrity

**Live achievement:** Real-model execution demonstrated trustworthy verification handling: a long required-game FAIL survived bounded structured storage, a later basic-web PASS could not override it, and legitimate foundation verification reached transaction acceptance. The Repairer obtained authorization and persisted provisional edits. A separate local infrastructure correction retained the current task in every captured Repairer request. Updated 7 November 2026.

Owner: Tasneem's independent Mini Hivo validation/implementation workstream. The inherited system and Experiments 1–18 retain their original authorship. No other contributor's independent implementation is incorporated.

## Research question and hypothesis

Can Mini Hivo preserve verification outcomes across bounded evidence projection, structured parsing, route aggregation and chronological receipt supersession without manufacturing PASS or permanently rejecting valid fresh success?

Hypothesis: bounded valid structured summaries and conservative outcome interpretation prevent false PASS in the declared protocol, while preserving legitimate PASS and valid newer equivalent results. Unknown/unavailable evidence must not erase an outstanding FAIL. This concerns interpretation of evidence, not whether the original behavioral oracle tests every requirement.

## Original observation and confirmed cause

Coin Courier Run-010 used baseline `2a8b94590734cec3375047a18e0dc71df2476f85` with `gemma4:e4b`. Required game checks failed because `AGENT_GAME` was missing and keyboard/collection checks did not execute. The preserved native trace records:

| Native line | Observation |
|---|---|
| 120 | Child 1 required browser route FAIL |
| 121 | Aggregation `passed: true`, browser result PASS, retaining `actual_result: FAIL` |
| 122 | Separate deterministic quality gate FAIL |

SQLite tool events 9/10 contain failed game-verification payloads exceeding the 1,600-character evidence bound. `execute_agent_task` stored `str(result)[:1600]`; the clipped JSON was incomplete. `_parse_result` fell back to lexical success matching, including the field name `passed` despite a false value. Aggregation could prioritize that apparent PASS over the separate failed browser check.

The final gate still rejected this child. Incorrect intermediate aggregation is not a successful transaction and is not excused by a later rejection. Run-010 ended by supervised interruption, not normal root acceptance; the partial game is not included here.

## Baseline, treatment and intervention

| Arm | Immutable revision |
|---|---|
| Baseline | `2a8b94590734cec3375047a18e0dc71df2476f85` |
| Treatment | `f8bf65ece895f70c1b572b59df229314de09afbe` |

The baseline includes prior work reviewed separately in [team PR #7](https://github.com/kareem232003/mini_hivo/pull/7). Experiment 19 is only the delta after that revision; this does not re-evaluate its earlier fixes.

- [`hivo/evidence.py`](../../hivo/evidence.py), `project_tool_evidence_result`: bounded valid summaries retain supported outcome/target/profile/identity fields. Unrepresentable proof becomes unavailable rather than a clipped positive claim. Full original transcripts remain the diagnostic source.
- [`mini.py`](../../mini.py), `execute_agent_task`: use that projection and record producing role. Raw model-facing tool output remains unchanged.
- [`hivo/verification_routing.py`](../../hivo/verification_routing.py), `_parse_result`: malformed/incomplete structured evidence cannot acquire PASS through keyword fallback; explicit failure dominates conflicting success.
- `_evidence_matches`: match browser targets rather than just tool names.
- `_aggregate_verification_routes`: retain current browser failure, reject cached labels without proof, and allow supersession only for available valid outcomes within the same explicit role/target/profile in receipt order.
- [`tests/test_verification_outcome_integrity.py`](../../tests/test_verification_outcome_integrity.py): producer/parser/aggregation, Worker-boundary and transaction controls.

## Method and controls

The 6–7 November campaign used real gemma4:e4b and production Mission Compiler, roles, tools, browser and quality/transaction paths. The declared component required movement and collection and used the actual model-generated Run-011 candidate. Ingestion/specification/Coordinator decomposition were controlled inputs, not a new full CLI execution. Observers forwarded original calls/results unchanged; ordinary role budgets, authorization and the 1800-second process cap remained.

The [live protocol](supporting/live-protocol-20261107.json) pins source stages and acceptance; actual failed receipt/mission checkpoint inputs were labelled and authorization obtained anew. No game was manually repaired.

Historical offline methodology is unchanged: the [probe](../../scripts/experiment19_probe.py) loads pure pinned modules with git show; baseline clips at 1600 characters and treatment uses its projector. The [curated event-10 fixture](supporting/run010-fixture.json) retains overflow metadata but omits incidental diagnostics. Fourteen challenges expect non-PASS and two PASS: malformed/missing proof, wrong targets, conflicts, cached labels, basic-web precedence and supersession. [Manifest](manifest.json), [comparison](supporting/comparison.json) and [runbook](RUNBOOK.md) preserve original conditions. Disclosed fixture-development pilots remain separate in [historical results](experiment19-results.json), not pooled with final measurements.

## Actual results

**Live findings — trustworthy outcomes, legitimate acceptance and authorized execution.**

The production path preserved the required-game failure from the Falsifier through evidence storage and controller evaluation. It also accepted a legitimate foundation result through the transaction gate. Together, these observations demonstrate that failure protection coexists with successful acceptance for the assigned profile.

**Validated infrastructure improvement.** A separate local task-retention correction kept the exact assignment in all 18 captured Repairer requests. It remains outside this experiment PR's code changes.

**Provisional implementation.** With fresh authorization, the real Repairer made five persisted range edits. Their functional result is recorded separately from permission and file persistence in the observations below.

| Actual production observation | Demonstrated outcome |
|---|---|
| Falsifier game FAIL: 3126 characters; stored projection: 805 characters | Valid structured FAIL survived bounded storage |
| Basic run_file PASS followed required game FAIL | Controller/browser and evidence gate still rejected; no false PASS |
| Separate foundation Falsifier PASS and transaction | Legitimate title/canvas success accepted, not repaired-game proof |
| Initial authorized recovery | No mutation; fresh gate FAIL; natural exit after 733.25 s |
| After local task-retention correction | All 18 actual Repairer requests retained the task; 17 responses and one canceled request |
| Recovery continuation | Five real authorized range edits persisted provisionally |
| Independent final required browser check | Movement and collection remained FAIL; no accepted repaired transaction |

The continuation reused an actual failed receipt and compiled mission as labelled checkpoint inputs with fresh authorization. Recurring nonfunctional bridge edits prompted a supervised stop; the independent browser check preserved the required FAIL. [Live results](supporting/live-results-20261107.json) and [curated evidence](supporting/live-evidence-20261107.json) retain acceptance details and stop provenance.

**Supporting historical offline evidence (28 October).** Original tables and results below remain unchanged; they support the live interpretation and are not additional live cases.

### Same-input offline protocol

| Metric | Baseline | Treatment |
|---|---:|---:|
| Decisions matching declared expectations | 8/16 | 16/16 |
| False PASS among negative challenges | 7/14 | 0/14 |
| False rejection among positive challenges | 1/2 | 0/2 |
| Equal per-case input hashes across arms | Yes | Yes |
| Model calls / browser calls | 0 / 0 | 0 / 0 |

[Complete comparison](supporting/comparison.json). This finite offline challenge matrix supports the later live observations; its counts are not field reliability estimates.

The separately preserved Run-010 replay used original routes, tool events 1–14 and failed event 10, reproducing baseline aggregate/browser PASS versus corrected FAIL. [Results](experiment19-results.json) distinguish this local-only replay from the curated protocol.

### Receipt-supersession review regression

An intermediate, uncommitted treatment deduplicated by role/target/profile before validating the outcome. A newer `passed: null`, NOT_RUN, PENDING or statusless receipt could displace a valid FAIL, allowing a controller PASS. This was discovered during final review, not observed in the original baseline run.

The [historical reproduction](supporting/historical-supersession-before-results.json) records 30 methods with four failing subtests. Final `f8bf65e` only allows available PASS/FAIL outcomes to replace equivalent receipts. Malformed/unavailable receipts cannot cancel the outstanding failure. A valid matching newer PASS remains supported. The final matrix and regression tests protect this behavior.

### Selected regression cohort, freshly rerun

| Suite | Methods | Result |
|---|---:|---|
| `test_verification_outcome_integrity.py` | 30 | PASS |
| `test_evidence_policy.py` | 9 | PASS |
| `test_verification_applicability.py` | 15 | PASS |
| `test_experiment11_evidence_compatibility.py` | 10 | PASS |
| `test_experiment13_monotonic.py` | 9 | PASS |
| `test_experiment18a_schema_feedback.py` | 9 | PASS |
| `test_context_sufficiency_gate.py` | 9 | PASS |
| `test_greenfield_context_progress.py` | 9 | PASS |
| `test_repair_impact_anchor.py` | 3 | PASS |

**103 selected test methods passed: 30 new and 73 existing; no failures, errors or skips in this cohort.** These are not 103 independent experimental cases, a full-suite result or a general reliability estimate. The old 103-test checkpoint is not added to the new 103. [Fresh results](supporting/selected-tests.json); [historical checkpoint](supporting/historical-supersession-after-results.json).

The original 20-method pre-implementation fixture produced failure/error records, including references to the then-missing projector; it is not 20 identical FAIL-to-PASS observations. [Sanitized historical record](supporting/historical-before-results.json).

## Safety and acceptance boundaries

The live campaign exercised distinct permission, persistence, behavioral-verification and transaction boundaries: legal edits were possible, while required verification continued to protect acceptance. Foundation acceptance applies to its title/canvas profile.

Original treatment AST checks left evidence_gate, _commit_verified_leaf, execute_leaf, repair_task, authorization guards, planning and scheduling unchanged. Offline controls retain rejection and valid repair acceptance. Supersession matches receipt order, role, target and profile; it is not independent artifact-hash freshness proof.

Shared campaign improvements are disclosed, not bundled: bounded task retention corrected captured assignment loss, and schema-error hints replaced unsupported truncation/stale diagnoses. Current-task retention was directly observed; preservation of detailed failure diagnostics remains a separate investigation. The 133-method selected cohort passed before final hint changes; nine focused hint methods and one existing validator method passed afterward. Counts overlap and are not full-suite evidence.

## Evidence provenance and reproducibility

- [Live results](supporting/live-results-20261107.json), [source/protocol](supporting/live-protocol-20261107.json), [curated evidence](supporting/live-evidence-20261107.json). Raw campaign traces and games remain LOCAL-ONLY.
- [RUNBOOK](RUNBOOK.md): exact offline command forms, prerequisites and fresh output locations.
- [Results](experiment19-results.json), [manifest](manifest.json), [protocol comparison](supporting/comparison.json), [selected cohort](supporting/selected-tests.json).
- [Earlier implementation checkpoint](../verification-outcome-integrity/README.md): historical detail and local-only raw-log references; its uncommitted wording describes that earlier checkpoint, not current publication status.
- LOCAL-ONLY EVIDENCE: original Run-010 `REPORT.md`, `logs/sqlite-tool-events.json`, native run `20261022T011102-92488c96.jsonl`, screenshots/database/game; original verification-integrity `evidence/*` logs; current submission `evidence/selected-v1` and `protocol-v1/v2/v3/v4` outputs. No broken GitHub links to host-specific paths are provided.

## Limitations and conclusion

Real-model execution demonstrated the practical value of the correction: a required-game FAIL retained its meaning across bounded storage and aggregation, basic-web success could not override it, and legitimate foundation verification reached transaction acceptance. Authorized Repairer execution also produced persisted edits. Mini Hivo can therefore preserve the observed verification distinction while continuing real implementation work.

**Follow-up findings and next validation:**

- **Bridge contract:** a separate movement case exposed ArrowUp handling versus the verifier's move('up') call. The mismatch is confirmed; establish where the intended direction contract must be advertised before changing producer or oracle.
- **Rendered source:** JavaScript appeared as page text. This is a confirmed generated-artifact defect; inspect document structure and edit placement independently of movement semantics.
- **Repair grounding:** the Repairer generated nonfunctional bridge code. Investigate how proposed functions connect to existing application state and transitions.
- **Edit progression:** repeated range changes and a stale exact-match attempt were observed. Inspect current-source reads and feedback after rejection; these observations do not establish a defective file tool or a single controller cause.

These are shared contract/artifact/recovery findings rather than proven defects in Experiment 19 outcome interpretation. The outstanding live acceptance sequence is a functional authorized repair, fresh required PASS, matching successful receipt supersession and transaction acceptance. Malformed/unavailable receipt controls and successful supersession currently have offline evidence; the campaign does not establish complete live recovery or full E2E success. Historical authority-closure fixture coverage, independent artifact freshness and the finite retrospective matrix remain limitations.

Next, clarify the bridge API and inspect grounded repair feedback using the preserved traces, then validate the affected repair-to-acceptance sequence through the existing gates.
