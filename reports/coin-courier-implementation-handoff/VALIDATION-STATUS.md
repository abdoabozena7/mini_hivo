# Existing validation evidence

[Overview](README.md) ? [Implementation](IMPLEMENTATION-SUMMARY.md) ? [Runs](RUN-RESULTS.md)

All results below were recorded before this publication. **No tests were rerun.** Source/test bytes were compared against the captured Run-009 snapshot during implementation publication. Fixture newline preservation was a later packaging safeguard, not a runtime change.

## Functionality tests

Recorded command form:

```text
python -B -m unittest discover -s tests -p <suite-filename> -v
```

| Suite filename | Recorded passing methods | What the existing evidence establishes |
|---|---:|---|
| `test_greenfield_context_progress.py` | 9 | Real greenfield mission compilation/gates/tools with deterministic providers: retained feedback permits a persisted authorized write; repeated checking stops at four calls; negative authority/context/path/precommit cases remain protected |
| `test_ingestion_integration.py` | 10 | Exact original prompt plus scope/negation, genuine contradictions, existing intent and populated-repository cases |
| `test_browser_implicit_favicon.py` | 5 | Actual browser/verifier positive and negative cases using an explicitly configured existing executable |
| `test_repair_impact_anchor.py` | 3 | Real Builder-to-Repairer authorization and persisted edit with deterministic provider responses; genuine goal drift remains rejected |

Before/after records include a 28-check Worker reproduction, three original-task false conflicts, nine initial ingestion methods producing 13 failure/subtest records, one failure in the original four-case favicon suite, and one failure in the goal-consistent three-case Repairer suite. An expanded favicon negative exposed an intermediate explicit-resource hole; the final five-case suite passed before Run-008. These intermediate failures are preserved, not hidden or counted as passing results.

## Additional recorded regressions

| Selection | Passing methods |
|---|---:|
| Clarification, explicit provider-disabled harness | 50 |
| Project understanding | 32 |
| Context sufficiency gate | 9 |
| Pre-mutation impact | 27 |
| Experiment 3 Worker progress | 4 |
| Experiment 4 Mutation Grounding | 9 |
| Execution contracts | 36 |
| Experiment 6 verification environment | 9 |
| Experiment 7 verification surfaces | 5 |

Together with the four focused suites, these are **208 distinct passing selected tests**, not full-suite certification. The clarification harness deliberately raises `ProviderError` where tests would otherwise reach live extraction; its 50 passes do not demonstrate provider-backed extraction.

The earlier Worker-only checkpoint recorded 138 passing tests with overlapping suites. **Do not add 138 to 208.** Full command records, historical syntax validation and per-suite outputs are indexed in the [Worker checkpoint](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/worker-context-progress/README.md) and [final handoff](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/coin-courier-runtime-integration/ENGINEERING-HANDOFF.md).

## Failed, skipped and unverified coverage

- The eight-method verification-policy suite recorded two missing-historical-fixture errors on both changed and unchanged baselines. It is not a passing suite.
- Two older browser probes skipped unavailable default managed-browser discovery. The five new browser tests used an existing executable via `HIVO_TEST_BROWSER_EXECUTABLE`; no browser download was performed.
- Wider recovery selections had failures/errors matching the unchanged baseline, with ignored historical fixtures absent. Their detailed counts remain in the pinned checkpoint; they are not complete recovery certification.
- Deterministic provider tests establish mechanism behavior, not real-model reliability. Live Runs 007?009 establish authorized implementation progress, not completed game functionality.
- Required-game verification, productive live Repairer mutation, post-verification transaction acceptance, optional greenfield wrapper activation and full independent application acceptance remain unverified or failed as specified in [Run results](RUN-RESULTS.md).

## Evidence accessibility

Published reports and exact implementation/test source are available through the pinned fork links. Raw logs/databases/screenshots and original source snapshots remain LOCAL-ONLY EVIDENCE. This team documentation PR does not upload them or imply independent reproduction by a reviewer.
