# Experiment 12

## Scope

Compare the existing `current` and `compatible` policies from Experiment 11.
Production implementation, model (`gemma4:e4b`), Worker budget (28), prompts,
verification, recovery, authority gates and integration are unchanged.

Five public fixtures, three fresh attempts per policy per task: 30 trials.
These start from frozen, user-authorized disposable fixture contracts; they
measure contract-to-Root execution. They do not measure free-form upstream
planning, and no repair to an upstream failure is smuggled into this comparison.

Each contract passes native Stage 3/Stage 4 validation. Only its source file is
mutable; tests are read-only. Original controller results are observed and
saved without replacing decisions. A capture retains the candidate source
before verification/rollback. Failed upstream attempts remain in the cohort;
only real, assertion-bearing verification PASS enters the receipt denominator.

## Reproduce on this host

Use a new output directory. The local dependencies and Ollama model must
already be available; the harness does not install anything.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment12_run.py preregister --output-dir D:\projects\Ai\mini_hivo_experiment12\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment12_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment12\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment12_handoff_probe.py --suite D:\projects\Ai\mini_hivo_experiment12\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment12\new-paired
foreach ($trialNumber in 1..3) {
    .venv\Scripts\python.exe -X utf8 scripts/experiment12_evidence_matrix.py --suite D:\projects\Ai\mini_hivo_experiment12\new-suite --output-dir "D:\projects\Ai\mini_hivo_experiment12\new-matrix-$trialNumber"
}
.venv\Scripts\python.exe -X utf8 scripts/experiment12_report.py --suite D:\projects\Ai\mini_hivo_experiment12\new-suite --matrix D:\projects\Ai\mini_hivo_experiment12\new-matrix-1\matrix.json --matrix-repeat D:\projects\Ai\mini_hivo_experiment12\new-matrix-2\matrix.json --matrix-repeat D:\projects\Ai\mini_hivo_experiment12\new-matrix-3\matrix.json --paired D:\projects\Ai\mini_hivo_experiment12\new-paired\comparison.json --output-dir D:\projects\Ai\mini_hivo_experiment12\new-report
```

Batch is sequential, with alternating policy order between repeats. Resuming
skips completed trials and refuses an incomplete workspace for manual audit.
Source hashes, model, policy set, plan and contract identities are checked.

## Three distinct datasets

1. **Fresh model trials**: original Worker, child verification/receipt and fresh
   parent integration. Costs include all execution attempts, including failures,
   divided by Root successes. Setup/preflight and frozen upstream planning are
   excluded. Model calls and agent tool calls are reported separately.
2. **Actual paired handoffs**: earliest completed Worker for each qualifying
   task, with no PASS selection. Reconstruct the exact captured state and run
   fresh native verification under both policies. No model/Repairer/Root claims.
3. **Reference protocol checks**: independently corrected candidate fixtures
   execute real Browser/Python/Node verification before policy evaluation.
   Native alternatives prove different behavior/target. Requirement mismatches
   and provenance aliases are explicitly constructed replay records. Three fresh
   verifier cycles repeat the same unique scenarios; these are not independent
   samples of field error rates. Solutions are never exposed to fresh Workers.

Page load and syntax-only success are not behavioral evidence. Timer before/
after assertions are counted even when the normalizer's expected flags are
missing. Both aggregation false acceptance and final verified receipt false
acceptance are reported; a later rejection does not hide an earlier bad match.

## Result files

`experiment12-report.md` is the Arabic percentage report.
`experiment12-results.json` contains all 30 trial rows and their evidence paths.
`manifest.json` is the preregistration used by the completed batch.

Raw observations, candidate captures, reference payloads and native receipts
remain in `D:\projects\Ai\mini_hivo_experiment12`. Partial diagnostic matrix
versions are retained separately and excluded from the final dataset. No trial
is discarded because its Worker failed before verification.

The decision for this experiment is to retain `compatible` as experimental.
It improves game evidence but currently rejects correct non-game evidence.
Experiment 12 makes no default or production policy change.
