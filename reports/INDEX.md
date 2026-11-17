# Measured experiment results

This index identifies the final report and machine-readable measurements for every **completed** experiment. Read each report's denominators and limitations before comparing percentages. Earlier or interim report variants are retained in the same experiment directory, with their original relative paths, to show how the evidence evolved. The [experiment timeline](../docs/EXPERIMENT_HISTORY.md) links the corresponding commits.

| Experiment | Final narrative | Numeric results | Additional measured evidence |
|---|---|---|---|
| 1 | [final report](experiment1/final/report.md) | [JSON](experiment1/final/report.json) | Earlier paired and individual reports in `experiment1/` |
| 2 | [report](experiment2/rkey_01/report.md) | [JSON](experiment2/rkey_01/report.json) | One paired case |
| 3 | [report](experiment3/rkey_01/report.md) | [JSON](experiment3/rkey_01/report.json) | One paired case; [Tasneem follow-up: existing fix history](experiment3/follow-up-greenfield-feedback/REPORT.md) |
| 4 | [latest report](experiment4/rkey_03/report.md) | [JSON](experiment4/rkey_03/report.json) | Prior `rkey_02` report retained |
| 5 | [report](experiment5/rkey_01/report.md) | [JSON](experiment5/rkey_01/report.json) | One paired case |
| 6 | [latest report](experiment6/rkey_02/report.md) | [JSON](experiment6/rkey_02/report.json) | Prior `rkey_01` report retained |
| 7 | [report](experiment7/rkey_01/report.md) | [JSON](experiment7/rkey_01/report.json) | Candidate and live outcomes separated |
| 8 | [report](experiment8/rkey_01/report.md) | [JSON](experiment8/rkey_01/report.json) | [Receipt replay](experiment8/rkey_01/receipt_replay/comparison.json) |
| 9 | [report](experiment9/rkey_01/report.md) | [JSON](experiment9/rkey_01/report.json) | [Parent probe](experiment9/rkey_01/parent_probe/comparison.json), [root continuation](experiment9/rkey_01/root_continuation/comparison.json) |
| 10 | [report](experiment10/rkey_01/report.md) | [JSON](experiment10/rkey_01/report.json) | [Frozen handoff](experiment10/rkey_01/frozen_handoff/comparison.json), [full handoff](experiment10/rkey_01/full_handoff/comparison.json) |
| 11 | [report](experiment11/rkey_01/report.md) | [JSON](experiment11/rkey_01/report.json) | [Frozen comparison](experiment11/rkey_01/frozen-comparison/comparison.json); interim report retained |
| 12 | [report](experiment12/experiment12-report.md) | [JSON](experiment12/experiment12-results.json) | [Evidence matrix](experiment12/supporting/evidence-matrix-v4/matrix.json), [paired handoffs](experiment12/supporting/paired-handoffs/comparison.json) |
| 13 | [report](experiment13/experiment13-report.md) | [JSON](experiment13/experiment13-results.json) | [Evidence protocol](experiment13/supporting/evidence-v1/comparison.json), [handoffs](experiment13/supporting/handoffs-v1/comparison.json) |
| 14 | [report](experiment14/experiment14-report.md) | [JSON](experiment14/experiment14-results.json) | [Evidence protocol](experiment14/supporting/evidence-v2/comparison.json), [handoffs](experiment14/supporting/handoffs-v2/comparison.json); v1 retained |
| 15 | [report](experiment15/experiment15-report.md) | [JSON](experiment15/experiment15-results.json) | [Binding protocol](experiment15/supporting/binding-v2/comparison.json); v1 retained |
| 16 | [report](experiment16/experiment16-report.md) | [JSON](experiment16/experiment16-results.json) | Timer/Python first-blocker diagnosis |
| 17 | [report](experiment17/experiment17-report.md) | [JSON](experiment17/experiment17-results.json) | [Deterministic checkpoint](experiment17/classification-protocol.md), [protocol JSON](experiment17/classification-protocol.json), [runbook](experiment17/RUNBOOK.md) |
| 18 — upstream no-tool policy | [report](experiment18/no-tool-exit-report.md) | [JSON](experiment18/experiment18-results.json) | [Runbook](experiment18/RUNBOOK.md); Python policy comparison and Timer/Python fresh audit |
| 19 — upstream context closure | [report](experiment19/context-decision-closure-report.md) | [JSON](experiment19/context-decision-closure-results.json) | [Runbook](experiment19/CONTEXT_CLOSURE_RUNBOOK.md); current/closure comparison and preserved failure denominators |
| 18 — contributor diagnostics | [diagnostic report](experiment18/experiment18-report.md), [handoff](experiment18/EXPERIMENT18B_HANDOFF.md) | [JSON](experiment18/experiment18-findings.json); **partial diagnostic and verification replay** | Context sufficiency, mutation grounding, tool-contract mismatch, and verification follow-up; [schema follow-up](experiment18/follow-up-schema-feedback/REPORT.md) |
| 19 — contributor verification integrity | [report](experiment19/experiment19-report.md) | [JSON](experiment19/experiment19-results.json); **live FAIL preservation demonstrated; recovery acceptance pending** | [Manifest](experiment19/manifest.json), [paired protocol](experiment19/supporting/comparison.json), [selected tests](experiment19/supporting/selected-tests.json), [runbook](experiment19/RUNBOOK.md) |
| 20 | [Tasneem integration report](experiment20/experiment20-report.md) | [JSON](experiment20/experiment20-results.json); **deterministic comparison, not live E2E** | [Protocol](experiment20/PROTOCOL.md); contributor fork checkpoint |
| 21 | [Rodina integration and parser correction](experiment21/experiment21-report.md) | [JSON](experiment21/experiment21-results.json); **controlled functional comparison** | [Protocol](experiment21/PROTOCOL.md); source-bound exact-byte scripted replays |
| 22 | [Verification status integration](experiment22/experiment22-report.md) | [JSON](experiment22/experiment22-results.json); **181 selected offline methods** | [Protocol](experiment22/PROTOCOL.md), [provenance](experiment22/experiment22-provenance.json), [runner](../scripts/experiment22_validate.py) |

Experiment numbers 18/19 were independently reused by upstream and the contributor workstream. Both original reports and numeric results are retained; their cases, policies and denominators must not be combined.

The [2026-11-16 consolidation report](../docs/BRANCH_CONSOLIDATION.md) records
branch provenance, integration repairs, offline regression results, and new
request-to-result attempts. These are new measurements, not replacements for
the historical Experiment 1–19 results.

The actual [Karim PR integration](../updates/R_UPDATE_003.md) preserves all 36
incoming commits and both independently numbered report workstreams. Its
[validation record](integration/karim-pr1/validation.json) retains successful
and failed live integration attempts. The later
[publication addendum](integration/karim-pr1/publication.json) verifies the
actual closed/merged GitHub state and repeats validation on the delivered main.

The [quiet-terminal update](../updates/R_UPDATE_004.md) adds actual Windows
ConPTY session/navigation/native-decision and local-model request acceptance.
Its [sanitized measurements](integration/quiet-terminal/validation.json)
separate final regression, controlled functional checks, live exact-byte output,
quiet-output thresholds, historical cancellation and formal provenance limits.
The [manual-run analysis](../docs/MANUAL_RUN_ANALYSIS.md) and
[single research direction](../docs/RESEARCH_DIRECTION.md) distinguish an
observed failure from a future, unmeasured research hypothesis.

The [2026-11-17 live end-to-end checkpoint](../docs/LIVE_E2E_VALIDATION.md)
continues that work with three independently accepted default-auto Python
CLI journeys on one delivered source fingerprint. Its [complete attempt
index](e2e/2026-11-17/validation-summary.json) includes false successes,
failures, interruption, host qualification, and the final accepted products;
its [release acceptance](e2e/2026-11-17/release-acceptance.json) binds the
generated output and offline checks to committed source.
For a concise fork-to-upstream handoff covering the update range and verification limits, see the [Experiment 22 upstream update summary](experiment22/UPSTREAM_UPDATE_SUMMARY.md).

The JSON files for Experiments 1–11 and the supporting comparison/matrix JSON for Experiments 12–15 were copied byte-for-byte from the local experiment directories. The source and repository copies were checked with SHA-256. Reports for Experiments 12–16 were already tracked. Raw workspaces, model transcripts, and some native verifier payloads remain outside Git; they are not silently counted as uploaded evidence.

For a cross-experiment narrative, distinguish deterministic probes, same-state replay, fresh approved-contract runs, and full request-to-result runs. A browser PASS, a legal mutation, Child verified, and Root verified are different milestones. Preserve each report's exact numerator, denominator, policy, task family, and boundary; never extrapolate a one-task result to general reliability.
