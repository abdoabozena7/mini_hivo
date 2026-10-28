# Existing evidence and reproducibility boundary

This documentation publication performed **no new tests, model calls, browser checks or E2E runs**. [EVIDENCE.json](EVIDENCE.json) is a curated extraction of existing ledgers, with original-file hashes and diagnostic fields. It is not freshly generated experimental output.

## Fixed historical versions

- Baseline: `1e233845b3e9d26b10bb66238ec13a00f108356e`.
- Published treatment: `5e66d34db1827b814abf98f56b0b77b5ef6f8ee5`.
- Original feedback-only and both-fixes phases were uncommitted intermediate states, preserved in logs. No immutable intermediate treatment commit exists; do not invent one or infer it from commit dates.
- The published treatment commit also contains later independent engineering fixes. Its exact Worker functions and archived two-case fixture isolate the initial comparison; comparing whole live runs does not isolate it.

## Reusing the existing regression tests

Use the published treatment source/test checkout and existing Python 3.11.9 dependencies. The existing suite is `tests/test_greenfield_context_progress.py`. The original logical command was:

```text
python -B -m unittest discover -s tests -p test_greenfield_context_progress.py -v
```

The recorded nine-suite selection adds `test_context_sufficiency_gate.py` (9), `test_pre_mutation_impact.py` (27), `test_experiment3_worker_progress.py` (4), `test_experiment4_mutation_grounding.py` (9), `test_experiment15_evidence_edit.py` (9), `test_context_policy.py` (3), `test_execution_contracts.py` (36) and `test_project_understanding.py` (32), to the nine new methods: 138 total. These are selected methods, not 138 independent experiment cases.

The new deterministic test module does not exist on the historical baseline. An exact repeated comparison needs the archived `two-case-regression-snapshot.py` and provider-controlled fixture, applied in an isolated comparison environment, not a destructive checkout. The archives remain LOCAL-ONLY. The full final fixture at the published commit and before/after diagnostic summaries are public; the exact archived intermediate comparison is not fully self-contained in this documentation-only PR.

The test environment reused existing packages, used `-B` and process-local temporary directories. No live model is required for the deterministic cases. Do not run the whole application or assume missing historical recovery fixtures are available. A future reproduction should block unexpected provider calls and preserve separate output directories, as the original review did.

## Evidence access and limits

The original local ledgers are named in [EVIDENCE.json](EVIDENCE.json), with hashes but no host-specific absolute paths. Raw logs, workspaces and databases are intentionally not uploaded. Published source/tests/reports are linked at immutable commits in [REPORT.md](REPORT.md). This package makes the history reviewable without claiming that private raw logs are GitHub-accessible.

The original report's statements about being uncommitted/unpublished describe its earlier checkpoint; the later commit and current PR status in this follow-up supersede that publication-status wording only, not its recorded results.
