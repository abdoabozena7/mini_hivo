# Experiment 20 — Tasneem update integration

Preregistered 27 October 2026. Deterministic integration experiment, following the question / fixed inputs / measurements / limitations structure of Experiments 16 and 18. Experiment 20 uses a distinct name because a local checkout named experiment19 already exists; this does not imply Experiment 19 is complete.

## Question and hypothesis

Can Tasneem's cumulative fixes be integrated with Kareem's local cloud-model support without introducing additional deterministic test failures? Do the supplied focused tests pass on this Windows/Python environment?

## Fixed inputs

- Fork main: `f842fb8fb6e63e3064891d26ee0b24981e55c847`; its differences from local main `4d1760b292d0ba9021b5e957a870053407bbee5c` are research documentation only.
- Local baseline: `0500351` preserves the existing README, mini.py and host_preflight.py changes plus test_cloud_model.py. Original checkout and generated projects remain untouched.
- Treatment PR #7: `2a8b94590734cec3375047a18e0dc71df2476f85`, which includes PR #2. Documentation PR #3: `3d20a720302c05d527bb72a0540e726fc525c9e2`; PR #4: `d5acac182a5f3340968c2676d70a35369d81c3c5`.
- Same existing Python environment for both arms: `F:/Projects/Python/GitHub/mini_hivo/.venv/Scripts/python.exe`. Record actual version and installed dependency versions in each result.
- Rodina's changes and the separate Experiment 18 audit branch are excluded from both arms.

## Ordered checks and decision rule

1. Run baseline full deterministic discovery; preserve every failure/error/skip and exact test IDs.
2. Integrate PR #7 and documentation PRs #3/#4 on this isolated branch, preserving contributor history. Record conflicts and resolutions, if any.
3. Run the focused modules for startup, timeouts, reentry, requirements ingestion, context progress/schema, favicon filtering, repair impact anchor, and local cloud-model support.
4. Run the full deterministic suite under identical environment; compare common test IDs and classify added tests separately. Existing failures must remain visible, not be attributed to this update without evidence.
5. Run the architecture self-test and whitespace/conflict checks. If a newly failing test appears, inspect its cause and report whether the update needs correction before adoption. Any correction must be recorded separately from Tasneem's original changes.

## Measurements and limits

Record tests run, passes, failures, errors, skips, environment, source revisions, wall time, new/resolved failure IDs, and merge results. Preserve raw local logs and machine-readable JSON; publish only relevant summaries after inspecting logs for machine-specific data.

Passing these checks supports deterministic compatibility, not full game completion, model reliability, productive Repairer recovery, or Python 3.11 runtime compatibility. No live inference is part of this first experiment. The previous Run-010 remains contributor-reported historical evidence, not a new local outcome. A subsequent live experiment needs its own fixed task, model identity, budgets, and acceptance criteria.

## Recorded follow-up decisions

- The first focused run skipped five opt-in browser tests. Run a separate focused supplement with the installed Microsoft Edge executable using `HIVO_TEST_BROWSER_EXECUTABLE`. Preserve the original full-suite environment for the matched comparison.
- The original treatment full run produced one additional failure: the legacy mutation-recovery test selects the first tool message, which is now correctly the retained context-check result. Correct only that test to select `edit_file` by tool identity and additionally assert that successful context feedback remains present. Keep all original recovery/outcome assertions. Preserve the original failing run and rerun the corrected test and full suite. No application-code correction is proposed for this finding.
- An initial sandbox launch could not create the result directory; no tests ran in that attempt. The permitted retry produced the baseline measurements.
