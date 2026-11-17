# Experiment 20 — Tasneem update integration

**Date:** 27 October 2026. **Status:** deterministic integration gate passed after one test-only correction; full suite and architecture self-test retain existing failures. **Scope:** local integration and deterministic regression testing, including real browser fixtures. Full application/model completion is not measured.

## Research question

Can Tasneem's cumulative updates run alongside Kareem's existing local cloud-model support without introducing new deterministic regressions? This experiment follows the previous research format: fixed source identities, a recorded protocol, measured outcomes, first failure analysis, and explicit limits.

## Fixed sources and environment

| Input | Identity |
|---|---|
| Fork main | `f842fb8fb6e63e3064891d26ee0b24981e55c847` |
| Original local main | `4d1760b292d0ba9021b5e957a870053407bbee5c` |
| Control: fork main plus existing local cloud-model edits/test | `0500351cf60e61a8a40baf786741278fa890fe42` |
| Tasneem PR #7, including all PR #2 changes | `2a8b94590734cec3375047a18e0dc71df2476f85` |
| Tasneem documentation PR #3 | `3d20a720302c05d527bb72a0540e726fc525c9e2` |
| Tasneem documentation PR #4 | `d5acac182a5f3340968c2676d70a35369d81c3c5` |
| Original combined treatment | `2420473ec3234f9c413042b482e10551103913ee` |
| Treatment after local test-only correction | `a4ad142` |
| Branch | `codex/experiment20-tasneem` |
| Python / OS | Python 3.12.14 / Windows 11 build 26300 |
| Installed packages | rich 14.3.4; prompt_toolkit 3.0.53; Playwright 1.63.0 |
| Supplemental browser | Installed Microsoft Edge 156.0.4314.42, launched headlessly by Python Playwright |
| Model calls | No live model run was requested or used as an experimental outcome |

Fork main differs from original local main only in research documentation. The control additionally preserves the three locally edited tracked files and the cloud-model regression test. Original generated workspaces and the separate Experiment 18 audit branch are not included. Both comparison arms use the same Python environment.

Experiment 20 is a distinct identifier because a checkout named experiment19 already exists; it does not assert that Experiment 19 has completed. This report belongs to the isolated branch, not to published main.

## Implemented updates and coverage

| Area | Tasneem's implementation | Verification in this experiment |
|---|---|---|
| Startup compatibility | Build the reentry conflict ID with compatible concatenation instead of a Python 3.12-only f-string | Authority/reentry tests under Python 3.12; no Python 3.11 runtime claim |
| Model timeouts | Startup canary 30 to 180 seconds; normal transport 120 to 600 seconds | Host preflight and transport timeout tests; existing cloud-model tests |
| Requirement ingestion | Compare action, object, polarity and conditions; avoid treating prohibited resets as required resets | Ingestion integration tests and the existing requirement suite |
| New-project recognition | Recognize explicit construction in an empty workspace while retaining existing-project protections | Ingestion classification fixtures |
| Worker context retention | Preserve successful context feedback and the original mission across reanchoring | Scripted Worker tests with real context/impact gates and file mutations |
| Bounded progress | Stop consecutive successful context checks at the same anchor when no task tool intervenes | Repetition, intervening-tool, authorization and workspace-scope negative controls |
| Context schema and rejection feedback | Expose supported evidence kinds and return actual gate state after invalid input | Schema alignment and invalid-decision state tests |
| Browser diagnostics | Ignore only optional implicit favicon 404 noise; keep real application failures visible | Five real Edge fixtures, including explicit icon/script failures and console errors |
| Repair authorization identity | Use stable task/RUN parent goal for Repairer impact anchor | Repair impact-anchor regression |
| Research history | Import PR #3 and #4 reports without rewriting their historical claims | Documentation integration; no runtime behavior attributed to these PRs |

PR #7 contains PR #2, so #2 is not applied twice. All three merges completed automatically. Comparing application files with PR #7 leaves only the preserved local cloud-model changes; Tasneem's application code was not rewritten during integration.

## Results

| Run | Tests run | Passed tests | Failure records | Error records | Skips |
|---|---:|---:|---:|---:|---:|
| Control full suite | 1,365 | 1,331 | 24 | 18 | 10 |
| Original treatment full suite | 1,405 | 1,365 | 25 | 18 | 15 |
| Final treatment after test correction | 1,405 | 1,366 | 24 | 18 | 15 |
| Initial focused check | 91 | 86 | 0 | 0 | 5 |
| Focused supplement with Edge | 91 | 91 | 0 | 0 | 0 |

Counts are deliberately not summed: unittest records individual failing subtests, while setup errors can prevent whole classes from running. Focused runs overlap the full suite. Full-suite elapsed times were 90.37 seconds (control), 83.416 seconds (original treatment), and 77.796 seconds (final treatment); these single runs are not a performance benchmark.

**Final comparison:** zero new failure/error IDs, zero previously passing tests lost, 35 additional passing tests, and the same 42 baseline failure/error records retained. The additional five opt-in browser tests pass in the separate Edge supplement. All supplied focused modules were found. No manual merge conflict resolution was required.

**Architecture self-test:** both control and treatment exit 1 and have identical PASS/FAIL status lines. Existing failed checks include deep recursion, more-than-eight tasks, and the v25.1–v25.4.2 fixture-dependent checks. This is not an architecture-wide pass. The control self-test used an export of the pinned baseline under an isolated output directory, with the same Python environment and no additional historical fixtures.

Whitespace checks pass for the integrated diff. The original failing treatment run and raw output are retained locally, and their SHA-256 values are recorded in the portable results.

## First additional failure and correction

The uncorrected treatment adds one failure in `test_strategy_a_and_b_receive_the_shared_mutation_recovery_packet`. The existing test takes the first tool message and expects `MUTATION_RECOVERY`. Tasneem's intended context-retention change now makes that first message the successful `context_sufficiency_check` result.

The correction selects the `edit_file` result by tool identity, still requires the recovery marker, and additionally checks that the retained context result permits mutation. All original checks remain: both strategies complete, two mutation failures and two recovery packets are counted, and final file content is correct. The corrected isolated test passed. This is a test compatibility correction, not an application-code workaround. Commit: `a4ad142`.

## Existing failures and limitations

The baseline is not green. Its failure records include recovery-foundation and downstream recovery controls; setup errors include historical SQLite/planning artifacts and a frozen prompt absent from this checkout. Two positive controls also raise `TypeError` in the baseline. These are retained and compared by test identity, not silently dismissed or fixed in this experiment.

Default browser discovery lacks its expected Chromium binary. Five new opt-in favicon tests are additionally skipped when no executable is configured. The separate Edge supplement supplies the installed browser and passes all 91 focused tests, including the five real browser checks. It does not convert missing historical replay artifacts into measured passes.

Passing the focused suite does not establish full Coin Courier completion, general recovery reliability, complete contract coverage, productive Repairer mutations, or successful child/parent integration under a live model. Tasneem's historical Run-010 remained incomplete; no new live run here supersedes it. Longer timeout defaults may also mean longer waits on a failed provider.

## Reproduction and evidence

The preregistered sequence and later decisions are in [PROTOCOL.md](PROTOCOL.md). The machine-readable comparison is [experiment20-results.json](experiment20-results.json). `scripts/experiment20_run.py` writes full raw logs and JSON into local `results/`, which is intentionally excluded from Git. `scripts/experiment20_report.py` derives the portable comparison from those records.

Use the same Python environment for both revisions. Run the baseline label on the control source before integration, then the treatment/final labels on their recorded revisions. The raw records identify each source revision and package version. For the browser supplement set `HIVO_TEST_BROWSER_EXECUTABLE` to the installed browser path and use `--focused`; leave it unset for the matched full-suite runs. Focused and full results overlap and must not be added together as independent tests.

## Next decision

The evidence supports retaining Tasneem's integration on this experiment branch: no additional deterministic regressions remain after the test correction, and all focused/browser checks pass. It does not justify describing the whole project as failure-free. Rodina's changes remain a separate treatment, to be compared against this integrated Tasneem baseline in the next experiment. Full application acceptance requires a separate bounded live run with its task, model identity, budget, verification requirements and stopping rule fixed in advance.
