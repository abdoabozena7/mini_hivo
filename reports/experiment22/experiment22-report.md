# Experiment 22 — Verification status fail-closed integration

**8 November 2026. Status: selected offline regression gate passed. No live model or full application E2E result is claimed.**

For a concise handoff covering the fork-to-upstream update, see the [upstream update summary](./UPSTREAM_UPDATE_SUMMARY.md).

## Research question

Can PR #9's verification-outcome integrity implementation and PR #10's child-scoped verification implementation be integrated on the current Experiment 21 baseline, while correcting a parser case where an unrecognized explicit status could be promoted to PASS?

## Findings and implementation

The reported case reproduced on PR #10's head: `_parse_result({"status": "ERROR", "passed": True})` returned `("PASS", True)`. A boolean success must not override an explicit status the parser does not understand. The fix now evaluates all supplied `verification_status`, `status`, and `result` fields rather than selecting only the first non-empty one:

- Any explicit failure state or `passed: false` returns FAIL.
- Pending, skipped, missing, unknown, or conflicting non-failure states return unavailable (`None, False`) and cannot satisfy a required route.
- PASS requires recognized, mutually consistent success states, or a statusless `passed: true`.
- Existing legacy command receipts and ordinary explicit PASS/FAIL receipts remain covered by regression tests.

PR #10's production changes and tests were integrated on a clean worktree based on Experiment 21. PR #9 and #10 share the same verification-integrity changes in `hivo/evidence.py` and `hivo/verification_routing.py`; PR #10 adds `hivo/verification_scope.py` and its integration in `mini.py`. Against current main, these production files auto-merged; the conflicts were publication-only.

## PR review and publication decisions

### PRs #9 and #10

Both proposed heads target the earlier `f842fb8` base, which is an ancestor of the Experiment 21 baseline. PR #10 contains the PR #9 implementation but has later child-scope work; merging both independently would duplicate shared code. This branch integrates the shared code once, plus PR #10's distinct changes, and adds the parser correction. It does not merge or alter the remote PRs.

PR #10's original Experiment 20 report/results collided with this repository's existing Tasneem integration report/results. The existing files are preserved unchanged. The PR #10 versions are retained as [`experiment20-pr10-report.md`](../experiment20/experiment20-pr10-report.md) and [`experiment20-pr10-results.json`](../experiment20/experiment20-pr10-results.json), with its report link corrected to the archived results name.

The PR #10 historical validation runner is not reliable at its current head: its provenance/source checks pin `a910625`, while PR #10's head is `156c616`, and its expected child-scope test count is 34 while the head runs 38. A new [Experiment 22 runner](../../scripts/experiment22_validate.py) records the current selected suite counts and source hashes rather than altering the historical Experiment 20 measurement.

### PRs #11 and #12

These are not documentation for PRs #9 and #10. PR #11 is a retrospective for Experiment 3 feedback/progress fixes; PR #12 is a retrospective for Experiment 18A schema/feedback fixes. Both state they add documentation and evidence only, not production code, tests, or new experiment runs. Their bodies refer to base `f842fb8` and claim PR #7 remains open/unmerged; PR #7 is now closed/merged, so those status statements are stale.

Decision: do not merge #11/#12 as-is and do not duplicate them in this experiment. Their historical evidence may be useful, but should be refreshed against current main and the merged-PR status before publication.

## Verification

The dedicated validation runner executed **181 selected test methods across 13 suites; all 181 passed**. It patched `mini.ask_ollama` and `mini.structured_model_call` to raise if called. The new parser regression is included in the 31-method `test_verification_outcome_integrity.py` suite.

| Suite | Methods | Result |
|---|---:|---|
| Experiment 20 child-scope | 38 | Passed |
| Experiment 17 field-scoped profile | 5 | Passed |
| Verified child integration | 22 | Passed |
| Experiment 9 integration targets | 12 | Passed |
| Verification outcome integrity | 31 | Passed |
| Evidence policy | 9 | Passed |
| Verification applicability | 15 | Passed |
| Experiment 11 evidence compatibility | 10 | Passed |
| Experiment 13 monotonic evidence | 9 | Passed |
| Experiment 18A schema feedback | 9 | Passed |
| Context sufficiency gate | 9 | Passed |
| Greenfield context progress | 9 | Passed |
| Repair impact anchor | 3 | Passed |

Environment: Python 3.12.14, Windows 11 build 26300, Rich 14.3.4, prompt_toolkit 3.0.53, Playwright 1.63.0. These are selected offline regressions, not a full test-suite comparison, live-provider run, or browser end-to-end exercise. Exact results and SHA-256 source identities are in [`experiment22-results.json`](experiment22-results.json) and [`experiment22-provenance.json`](experiment22-provenance.json).

## Limitations

This validates a bounded parser correction and selected compatibility tests. It does not certify all verification receipt producers, full project behavior, live-model reliability, the full repository suite, or the outstanding PRs' merge readiness. The current review also identified documentation merge conflicts in the old PR branches; this experiment resolved its own report collisions without changing remote PR state.
