# Experiment 17 — Field-Scoped Verification Classification

The optional `verification_classification_policy=field_scoped` changes only the
text passed to the existing deterministic browser-profile rules. It includes
the task goal plus approved semantic fields (`goal`, `original_goal`,
`requirements`, `success_criteria`) and target paths. It excludes arbitrary
metadata, IDs, digests, hashes, provenance, and nested objects. The existing
word matching and browser verifier are unchanged. The default is `current`.

The deterministic protocol reads three frozen Timer and six frozen game
execution contracts from earlier suites. It checks current and field-scoped
profiles on the same objects, then perturbs identity/metadata fields three
ways per contract (27 invariance checks). No model calls are used there.

Nine fresh runs use the identical approved contracts and seeds from Experiment
12: Timer, ArrowUp game, and Q-restart game, each three times. Model
`gemma4:e4b`, per-Worker budget 28, contract fallback, strict semantic evidence,
evidence-bound mutation, Worker, verifier, repairer, and integration are fixed.
The variant is selected in the manifest and recorded in every run. Browser
profiles used for actual Child checks are audited, as are receipts and safety.

An improved profile classification is a correctness claim about the classifier.
It does not by itself prove the Worker reaches verification or that a patch
passes. All fresh failures stay in denominators and are reported separately.

## Reproduce

Use fresh directories and the same installed model/dependencies.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment17_run.py preregister --baseline D:\projects\Ai\mini_hivo_experiment12\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment17\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment17_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment17\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment17_report.py --suite D:\projects\Ai\mini_hivo_experiment17\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment17\new-report
```

The report currently reads the original frozen-contract suites named in its
source for the deterministic comparison. Fresh workspaces and full original
logs remain outside this repo. The fresh-run report has not been generated or
committed yet.
