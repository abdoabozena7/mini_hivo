# Experiment 16 — Cross-Domain First-Blocker Isolation

This is a diagnostic run. Production code, prompts, policy defaults, verification,
recovery, integration, and the 28-step per-Worker budget are unchanged. The runner
uses the exact frozen approved authority and seed fixtures from Experiment 12 for
`timer_pause` and `python_clamp` only. Each has three clean fresh attempts with
`contract_fallback`, `strict` evidence, and `evidence_bound` grounding. Model:
`gemma4:e4b`. Planning is frozen and outside the measured boundary.

The production source SHA-256 pins are in `manifest.json`. Read-only wrappers
record Builder tool calls, the entry to formal Child verification, actual native
verifier calls, mutation before/after hashes, and the unchanged original return
values. The report independently checks all six runs against the approved plan,
execution contract, model, policies, source pins, receipt, source bindings,
parent proof where applicable, and protected test files. No decision is replaced.

For each run, the report distinguishes:

- A candidate offered by the locator from actual source inspection.
- The first legal mutation from an actual file change before possible rollback.
- A browser call during Worker execution from formal Child verification.
- A ROOT applicability artifact from a Child route actually evaluated.
- The first causal failure from the final `BLOCKED` event. Recovery may continue
  after the first failure, so these can differ.
- A downstream `PARENT_INTEGRATION` failure from the Child failure that caused it.

The controlled fixtures are small and not representative of arbitrary projects.
Three runs per task give a failure-location observation, not a reliable estimate
of domain success rates. A correct patch is not inferred from a file edit.

## Reproduce

Use a fresh output directory. The existing local Ollama model and project
dependencies are required; the scripts do not install or select alternatives.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment16_run.py preregister --baseline D:\projects\Ai\mini_hivo_experiment12\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment16\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment16_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment16\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment16_report.py --suite D:\projects\Ai\mini_hivo_experiment16\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment16\new-report
```

The report refuses a missing trial. Full workspace logs and candidate patches
remain outside the repository under the suite directory; committed results
contain the per-run boundary outcomes and links to their raw evidence.
