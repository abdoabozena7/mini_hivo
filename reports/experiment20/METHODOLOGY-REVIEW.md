# Experiment 20 — Methodology and Reproducibility Review

## Review boundary

This review compares the actual repository reports indexed by
[reports/INDEX.md](../INDEX.md), not an assumed universal template. It changes
research documentation and reproduction tooling only. The production treatment
remains `a91062551c9b346a35eb4abb5f18a6f64f95a72b`.

## Established conventions and Experiment 20 compliance

| Existing evidence | Established convention | Experiment 20 |
|---|---|---|
| [1](../experiment1/final/report.md), [2](../experiment2/rkey_01/report.md), [3](../experiment3/rkey_01/report.md), [4](../experiment4/rkey_03/report.md), [5](../experiment5/rkey_01/report.md), [6](../experiment6/rkey_02/report.md) | Paired conditions, explicit boundary reached, legal mutation and Child/Root success distinguished; small denominators are not general reliability | Twelve assertions per arm; no live Worker or Root success claimed |
| [7](../experiment7/rkey_01/report.md), [8](../experiment8/rkey_01/report.md), [9](../experiment9/rkey_01/report.md), [10](../experiment10/rkey_01/report.md), [11](../experiment11/rkey_01/report.md) | Candidate checks, historical replay, fresh live execution and final acceptance reported separately | Historical profile reproduction is separate from controlled synthetic assignments and transaction integration |
| [12](../experiment12/experiment12-report.md), [13](../experiment13/experiment13-report.md), [14 runbook](../experiment14/RUNBOOK.md), [15 manifest](../experiment15/manifest.json) | Named cases, frozen inputs, explicit interventions, positive/negative controls, paired results, unchanged final gates, retained pilots | Report/results/manifest/runbook/supporting artifacts; case-level protocol added in this review |
| [16](../experiment16/experiment16-report.md), [17](../experiment17/classification-protocol.md), [18](../experiment18/experiment18-report.md) | First-blocker diagnosis and partial results do not establish full workflow completion; hypotheses and missing evidence disclosed | Original child acceptance conditions unavailable; bounded recognizer and live/oracle gaps remain explicit |
| [19 report](../experiment19/experiment19-report.md), [manifest](../experiment19/manifest.json), [runbook](../experiment19/RUNBOOK.md) | Retrospective controlled offline protocol, pinned baseline/treatment, per-case expectations, input hashes, selected-test denominator separate from cases | Same offline methodology; provenance and dependency checks strengthened below |

The early `rkey_*` layout is not the only repository convention. Experiment 20
uses the later established `experimentN-report.md`, `experimentN-results.json`,
`manifest.json`, `RUNBOOK.md`, scripts, tests and small supporting JSON layout.
It does not alter any existing experiment or require an expensive live batch
merely to imitate the live experiments' scope.

## Gaps found and corrected

1. **Explicit case oracle:** the manifest previously gave only the case count.
   [protocol.json](protocol.json) now names all twelve assertions, their expected
   behavior, controls and expected baseline/treatment assertion results. These
   are test-method outcomes, not twelve autonomous software tasks. Several
   methods contain both positive and negative checks.
2. **Runtime and test input identity:** the probe pinned four inputs, but the
   regression runner pinned only two production files. Both now use
   [experiment20_provenance.py](../../scripts/experiment20_provenance.py), which
   checks all tracked Python inputs in `hivo/` and `tests/`, `mini.py`, the scope
   fixture and requirements against treatment Git blobs, normalizing CRLF to LF.
   Inherited inputs must also match baseline Git blobs. Neither arm changes
   other worktrees. This is a reproducibility check, not a security sandbox.
3. **Execution environment:** each fresh output directory now contains
   `provenance.json`: Python/platform/package versions, input and runner hashes,
   pinned revisions, invocation and provider-call guards. The recorded invocation
   redacts the host-specific output path. Existing historical output is retained
   unchanged rather than retroactively acquiring new metadata.
4. **Ambiguous command:** the regression runner now rejects simultaneously
   selecting `--focused-only` and `--baseline-existing`.
5. **Missing/partial execution:** exit success now additionally requires the
   declared method count, zero skips and successful expected assertions. The
   paired runner checks both arms against the explicit case protocol; a missing
   test or skipped assertion cannot silently satisfy the protocol.

These changes do not add new production behavior or new experimental cases.
The original results remain [4/12 versus 12/12](supporting/comparison.json),
[176 selected treatment methods](supporting/selected-tests.json) and
[142 existing baseline methods](supporting/baseline-existing.json).
Fresh review outputs are separately retained under `supporting/review-*`.

## Review validation results

The finalized runners were executed with CPython 3.11.9 on Windows AMD64,
using existing `rich` 14.3.4, `prompt_toolkit` 3.0.53 and `playwright` 1.63.0.
Playwright was not launched. These describe this recorded offline environment,
not an assertion that other environments were tested.

| Check | Actual review result |
|---|---|
| [Paired assertions](supporting/review-comparison.json) | Baseline 4/12; treatment 12/12; zero errors/skips |
| [Selected treatment regressions](supporting/review-selected-tests.json) | 176/176, all declared cohort counts matched, no skips |
| [Existing baseline control](supporting/review-baseline-existing.json) | 142/142, all declared cohort counts matched, no skips |
| [Shared provenance](supporting/review-provenance.json) | Runtime/test, fixture and runner identities checked equal across the three executions |
| [Review checks](supporting/review-quality.json) | JSON/link validation and `git diff --check` passed; modified-runtime and unequal-inherited-dependency negative controls rejected |

Preservation checks matched all ten pre-existing worktrees' HEAD/status and
recorded dirty-file hashes, plus all 230 files in the Run-010 preservation
snapshot. Only the current Experiment 20 package/tooling was edited. No commit,
push, PR change or merge was performed in this review.

## Decision rules and validity limits

- A protocol assertion succeeds only if its declared checks all hold; baseline
  failures are measured defects, not unexpected runner failures. Treatment must
  satisfy all twelve assertions with zero errors.
- Unknown or missing child assignments must retain conservative checks; explicit
  bridge/approved-contract requirements cannot be silently removed. Root must
  retain source requirements and require all configured game-check families.
- The selected regression cohort must pass without weakening final quality,
  Context Sufficiency, Impact Authorization or transaction gates. It is not a
  full-suite claim. Method counts are not added across repeated cohorts.
- Recorded source goals/root requirements come from Run-010, but local child
  acceptance clauses are declared synthetic controls. The complete original
  compiled mission is unavailable; no exact historical child PASS is inferred.
- No model/browser/E2E execution, completed Coin Courier application or complete
  user-acceptance coverage is established. Existing oracle gaps, conservative
  language coverage and per-process obligation retention remain limitations.

**Assessment:** aligned with the established offline/replay methodology for the
declared boundary; ready for review of that bounded claim, not certified for
full live E2E completion. Publication remains a separate authorized action.
