# Experiment 19 — Offline Reproduction

**Recorded live campaign:** production observations lead the [report](experiment19-report.md). See [live results](supporting/live-results-20261107.json), [protocol](supporting/live-protocol-20261107.json) and [evidence](supporting/live-evidence-20261107.json). Raw harnesses remain local-only; this is not a portable live runner. No new execution was performed for this update.

**Historical commands below:** require their original pinned source/test revision. Updated parent recognition/tests intentionally fail historical pin/count checks; do not relax those checks or relabel results. Future historical reproduction requires its immutable revision in a separately approved isolated checkout; current-revision checks need a separately defined cohort. None were run for this preparation.

## Prerequisites and fixed boundary

Use Python 3.11 or a supported later version, existing Mini Hivo test dependencies,
and this submission checkout. No package/model/browser installation is required.
Git must contain baseline `2a8b94590734cec3375047a18e0dc71df2476f85` and
treatment `f8bf65ece895f70c1b572b59df229314de09afbe`. The probe loads those immutable
pure modules without checking out either revision. It requires the committed
curated fixture, not the private SQLite database.
The local `.gitattributes` preserves supporting JSON bytes across checkouts so
the recorded fixture SHA-256 remains reproducible on Windows and other hosts.

The regression runner tests the current checkout. Its production source must
match treatment; [manifest.json](manifest.json) provides canonical Git-blob
hashes. Normal CRLF checkout conversion is not a production change. The fresh
results here used Python 3.11.9 with the three treatment source files unchanged.

## Paired protocol

From repository root, choose a NEW output directory outside the repository:

```powershell
python -B scripts/experiment19_probe.py --output-dir <fresh-protocol-output-directory>
```

The directory must not exist. `comparison.json` contains each case's input hash,
expected/actual result, route status and arm totals. The final recorded matrix
is [supporting/comparison.json](supporting/comparison.json). There are 16 cases
per arm, not 32 independent software tasks. A nonzero exit signals a treatment
expectation mismatch or unequal inputs; baseline defects are measured rather
than required to pass.

## Selected regression cohort

```powershell
python -B scripts/experiment19_validate.py --output-dir <fresh-selected-test-output-directory>
```

This runs the nine named suites in separate processes, with a 180-second cap per
suite. Unexpected `mini.ask_ollama` and `mini.structured_model_call` calls raise
instead of reaching a provider. Test-specific deterministic providers exercise
the real selected Worker/gate/file-tool paths. No browser/E2E runner is invoked.
Each suite log and `results.json` stay in the fresh output directory. Temporary
test files use its own `tmp` subdirectory. Full argv is visible in the runner;
the logical per-suite command is:

```text
python -B -m unittest discover -s tests -p <suite-filename> -v
```

The extra bootstrap is necessary to prevent accidental live provider calls.
Tests import inherited regression helpers, including the greenfield fixture
already present at the PR #7 baseline. Do not copy only this test into an older
checkout and call missing-helper failures a treatment regression.

## Review checks and interpretation

```text
git diff --check
git diff 2a8b94590734cec3375047a18e0dc71df2476f85 --name-only
```

The intended review boundary is the unmerged PR #7 head, not current team main.
The historical preparation proposed a stacked base. PR #9 was subsequently published cumulatively against team main by explicit approval; the dependency-relative Experiment 19 boundary remains unchanged. This local preparation does not alter its target or history.

Read the [report](experiment19-report.md) before interpreting denominators.
Protocol decisions, unit methods, Worker progress, final transaction acceptance
and live E2E success are different measures. These commands do not establish
live application success. Missing historical authority fixtures remain a stated
validation gap; do not invent them or relax gates to make a suite green.
