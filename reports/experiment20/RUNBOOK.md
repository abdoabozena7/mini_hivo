# Experiment 20 — Reproduce Locally

**Recorded live campaign:** production observations lead the [report](experiment20-report.md). See [live results](supporting/live-results-20261107.json), [protocol](supporting/live-protocol-20261107.json) and [evidence](supporting/live-evidence-20261107.json). Raw harnesses remain local-only; this is not a portable live runner. No new execution was performed for this update.

**Historical commands below:** require their original pinned source/test revision. Updated parent recognition/tests intentionally fail historical pin/count checks; do not relax those checks or relabel results. Future historical reproduction requires its immutable revision in a separately approved isolated checkout; current-revision checks need a separately defined cohort. None were run for this preparation.

## Fixed inputs

Baseline `d15b6068f78dd5b9e46daacd81f5543af5c2cf89` includes Experiment 19.
Historical treatment implementation: `a91062551c9b346a35eb4abb5f18a6f64f95a72b`.
Both objects must exist in Git. Use existing Python 3.11+ and Mini Hivo test
dependencies. Do not install/download anything for this protocol.

The fixture is [experiment20_scope.json](../../tests/fixtures/experiment20_scope.json).
It has original stored goals/root requirements and **declared synthetic local
conditions**, not recovered original mission payloads. Scoped Git attributes
preserve its LF bytes. [manifest.json](manifest.json) records canonical source
and fixture hashes. Production/fixture drift is rejected by the probe.

The [case protocol](protocol.json) defines each assertion and its expected
baseline/treatment outcome. The [methodology review](METHODOLOGY-REVIEW.md)
compares the package with the actual Experiments 1–19 reporting conventions.
Both runners also check tracked Python runtime/test inputs against treatment
Git blobs and verify inherited dependencies match baseline. Every fresh output
has `provenance.json` with Python/platform/package versions and input/runner
hashes. New metadata does not retroactively describe historical outputs.
Success also requires the declared test counts and no skips. The paired runner
checks expected results in both arms; baseline defects are expected measurements,
not permission for additional unexplained failures. Do not combine the mutually
exclusive `--focused-only` and `--baseline-existing` modes.

## Paired controlled comparison

From repository root, choose a new external output directory:

```powershell
python -B scripts/experiment20_probe.py --output-dir <fresh-paired-directory>
```

This runs twelve selected assertions in separate processes, using the baseline
module loaded from `git show` and the pinned treatment checkout. It does not
check out or modify another worktree. Browser observations and provider seams
are controlled; production applicability, profile, snapshot evaluation and
related routing execute normally. No browser or model runs. Full per-arm logs
are local; the small comparison JSON is publishable.

## Selected treatment regressions

```powershell
python -B scripts/experiment20_validate.py --output-dir <fresh-selected-directory>
```

This runs thirteen suites/176 methods on the recorded source. Unexpected live
model/provider calls raise. There is a 180-second cap per suite; no application
or browser runner is invoked. Outputs include per-suite logs and results JSON.
Temporary files use the output directory's private `tmp` subdirectory.

For focused development only:

```powershell
python -B scripts/experiment20_validate.py --focused-only --output-dir <fresh-focused-directory>
```

The 34-method new suite is a subset of the 176; do not add the counts.

## Existing-suite baseline control

```powershell
python -B scripts/experiment20_validate.py --baseline-existing --output-dir <fresh-baseline-directory>
```

This runs the twelve existing suites/142 methods with exact baseline `mini.py`
loaded in memory and provider calls blocked. Inherited dependencies other than
the new scope module are unchanged. The new module is not used by baseline.
The baseline control does not claim the new Experiment 20 tests pass.

## Review

```text
git diff d15b6068f78dd5b9e46daacd81f5543af5c2cf89 --check
git diff d15b6068f78dd5b9e46daacd81f5543af5c2cf89 --name-only
```

Review only this dependency-relative delta for Experiment 20. PR #10 already targets team main with the disclosed inherited PR #9 dependency. This update remains local; do not push or merge as part of reproduction.

Passing controlled snapshots do not establish physical browser behavior, new
game code, all detailed user acceptance criteria or live E2E completion. Missing
historical fixtures are a disclosed gap, not permission to weaken a test.
