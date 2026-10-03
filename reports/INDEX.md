# Measured experiment results

This index identifies the final report and machine-readable measurements for every **completed** experiment. Read each report's denominators and limitations before comparing percentages. Earlier or interim report variants are retained in the same experiment directory, with their original relative paths, to show how the evidence evolved. The [experiment timeline](../docs/EXPERIMENT_HISTORY.md) links the corresponding commits.

| Experiment | Final narrative | Numeric results | Additional measured evidence |
|---|---|---|---|
| 1 | [final report](experiment1/final/report.md) | [JSON](experiment1/final/report.json) | Earlier paired and individual reports in `experiment1/` |
| 2 | [report](experiment2/rkey_01/report.md) | [JSON](experiment2/rkey_01/report.json) | One paired case |
| 3 | [report](experiment3/rkey_01/report.md) | [JSON](experiment3/rkey_01/report.json) | One paired case |
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
| 17 | [runbook and status](experiment17/RUNBOOK.md) | **No completed final results yet** | Opt-in code and deterministic tests are committed; fresh run is in progress outside this repository |

The JSON files for Experiments 1–11 and the supporting comparison/matrix JSON for Experiments 12–15 were copied byte-for-byte from the local experiment directories. The source and repository copies were checked with SHA-256. Reports for Experiments 12–16 were already tracked. Raw workspaces, model transcripts, and some native verifier payloads remain outside Git; they are not silently counted as uploaded evidence.

For a cross-experiment narrative, distinguish deterministic probes, same-state replay, fresh approved-contract runs, and full request-to-result runs. A browser PASS, a legal mutation, Child verified, and Root verified are different milestones. Preserve each report's exact numerator, denominator, policy, task family, and boundary; never extrapolate a one-task result to general reliability.
