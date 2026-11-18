# Reusing the existing schema/feedback validation

This submission reports previous results. It ran no tests, providers, browsers or Coin Courier attempts. [EVIDENCE.json](EVIDENCE.json) contains curated original ledger summaries/hashes, not a new measurement.

## Historical comparison

Baseline `5e66d34db1827b814abf98f56b0b77b5ef6f8ee5`; treatment `2a8b94590734cec3375047a18e0dc71df2476f85`. Both already exist on the personal fork. The existing regression module belongs to the treatment, not the baseline.

The original comparison ran the same new test file against baseline production source before the correction and patched production source afterward, plus the three existing selections. A future controlled reproduction must supply that same test module to an isolated baseline checkout; do not expect the new module to be present in the historical baseline or modify an existing worktree.

## Original selected commands

Python 3.11.9, existing dependencies, `-B`, process-private temporary storage:

```text
python -B -m unittest discover -s tests -p test_experiment18a_schema_feedback.py -v
python -B -m unittest discover -s tests -p test_context_sufficiency_gate.py -v
python -B -m unittest discover -s tests -p test_greenfield_context_progress.py -v
python -B -m unittest discover -s tests -p test_repair_impact_anchor.py -v
```

These are logical test commands. The recorded actual invocations used a bootstrap that patches `mini.ask_ollama` and `mini.structured_model_call` to raise on unexpected provider calls before running unittest. Tests use deterministic substitutions at their declared seams. Reproducing the offline boundary requires the same provider protection, not a live application launch. The four suites contain 9+9+9+3 = 30 methods; supported-kind loop cases are subtests, not 21 extra independent methods.

Original local `run_focused.py` stages were `before`, `before-state-reproduction` (the strengthened state assertions), and `after`. The raw runner/logs remain LOCAL-ONLY, identified by filename/hash in the ledger. Source/test/report links at the immutable treatment commit are public in [REPORT.md](REPORT.md). No raw database, host path, credential, model or generated game is uploaded.

## Interpretation

Schema equality and rejected-input snapshot consistency have offline before/after evidence. The direct gate evaluator, whitelist, Context Sufficiency and Impact guards are unchanged; invalid input does not create or revoke authority. A currently authorized snapshot is not a new successful decision. No claim of full live recovery or accepted Coin Courier completion follows from these tests.
