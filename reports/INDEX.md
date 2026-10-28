# Measured experiment results

This index identifies the final report and machine-readable measurements for every **completed** experiment. Read each report's denominators and limitations before comparing percentages. Earlier or interim report variants are retained in the same experiment directory, with their original relative paths, to show how the evidence evolved. The [experiment timeline](../docs/EXPERIMENT_HISTORY.md) links the corresponding commits.

| Experiment | Final narrative | Numeric results | Additional measured evidence |
|---|---|---|---|
| 1 | [final report](experiment1/final/report.md) | [JSON](experiment1/final/report.json) | Earlier paired and individual reports in `experiment1/` |
| 2 | [report](experiment2/rkey_01/report.md) | [JSON](experiment2/rkey_01/report.json) | One paired case |
| 3 | [report](experiment3/rkey_01/report.md) | [JSON](experiment3/rkey_01/report.json) | One paired case  [Tasneem follow-up: existing fix history](experiment3/follow-up-greenfield-feedback/REPORT.md) |
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
| 17 | [partial classification checkpoint](experiment17/classification-protocol.md) | [Protocol JSON](experiment17/classification-protocol.json); **no completed final run results yet** | [Runbook](experiment17/RUNBOOK.md); fresh execution is in progress outside this repository |
| 18 | [diagnostic report](experiment18/experiment18-report.md), [handoff](experiment18/EXPERIMENT18B_HANDOFF.md) | [JSON](experiment18/experiment18-findings.json); **partial diagnostic and verification replay** | Context sufficiency, mutation grounding, tool-contract mismatch, and verification follow-up; positive control verified; [Tasneem follow-up: existing fix history](experiment18/follow-up-schema-feedback/REPORT.md) |
| 19 | [Verification Outcome Integrity](experiment19/experiment19-report.md) | [JSON](experiment19/experiment19-results.json); **live FAIL preservation demonstrated; recovery acceptance pending** | [Manifest](experiment19/manifest.json), [paired protocol](experiment19/supporting/comparison.json), [selected tests](experiment19/supporting/selected-tests.json), [runbook](experiment19/RUNBOOK.md); 16 cases/arm and 103 selected methods are separate measures |
| 20 | [Tasneem integration report](experiment20/experiment20-report.md) | [JSON](experiment20/experiment20-results.json); **completed deterministic comparison, not live E2E** | [Protocol](experiment20/PROTOCOL.md); 91 focused checks pass with Edge, no new final failure/error IDs, existing full-suite and architecture failures remain; isolated branch |
| 21 | [Rodina integration and parser correction](experiment21/experiment21-report.md) | [JSON](experiment21/experiment21-results.json); **controlled functional and regression comparison** | [Protocol](experiment21/PROTOCOL.md); PR #6 includes #5, 167 focused checks pass with Edge, three exact-byte root-verified scripted-provider replays, no new failure/error IDs; local experiment branch |
| 22 | [Verification status fail-closed integration](experiment22/experiment22-report.md) | [JSON](experiment22/experiment22-results.json); **181 selected offline regression methods passed** | [Protocol](experiment22/PROTOCOL.md), [provenance](experiment22/experiment22-provenance.json), [validation runner](../scripts/experiment22_validate.py); PR #9/#10 integration plus status-conflict correction |

For a concise fork-to-upstream handoff covering the update range and verification limits, see the [Experiment 22 upstream update summary](experiment22/UPSTREAM_UPDATE_SUMMARY.md).

The JSON files for Experiments 1–11 and the supporting comparison/matrix JSON for Experiments 12–15 were copied byte-for-byte from the local experiment directories. The source and repository copies were checked with SHA-256. Reports for Experiments 12–16 were already tracked. Raw workspaces, model transcripts, and some native verifier payloads remain outside Git; they are not silently counted as uploaded evidence.

For a cross-experiment narrative, distinguish deterministic probes, same-state replay, fresh approved-contract runs, and full request-to-result runs. A browser PASS, a legal mutation, Child verified, and Root verified are different milestones. Preserve each report's exact numerator, denominator, policy, task family, and boundary; never extrapolate a one-task result to general reliability.
