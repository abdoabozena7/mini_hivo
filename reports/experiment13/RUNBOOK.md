# Experiment 13

## Fixed inputs

`arena_arrow`, `arena_q_restart`, `node_unique`, three fresh runs each under
`current` and `monotonic`: 18 trials. Contracts and seed bytes are identical to
Experiment 12. Model is `gemma4:e4b`, Worker tool budget is 28. Worker prompts,
progress, mutation grounding, localization, verification, recovery, authority
and parent integration are unchanged. Timer/Python are excluded from the verdict.

The optional CLI flag is `--semantic-evidence-policy monotonic`. The default
remains `current`; the previous `compatible` policy remains available.

## Policy boundary

Legacy route matching runs first. A PASS stays a PASS in aggregation. Only
failed legacy browser matching can be rescued by compatible executed semantic
records. Missing inventory is UNKNOWN and cannot itself invalidate a correct
legacy receipt or rescue a missing/failed verification.

The final receipt must still bind any supplied proof identity to the approved
requirement/target/behavior and current source. Known foreign identity is rejected
even when the permissive legacy matcher accepted it. This is required because
literal preservation of all legacy acceptances would retain the false accepts
measured in Experiment 12. Preservation is measured on independently correct
legacy evidence, not on a false-positive matcher return.

The existing `_evidence_matches` and `_aggregate_verification_routes` functions
are unchanged. Incompatible unit evidence can still pass aggregation and is
rejected at the final receipt. Tightening that aggregator is deferred to
Experiment 14. Authority-bound/direct routes retain their existing closures.

## Reproduce

Prerequisite: the original Experiment 12 suite at the path below, existing
Ollama model and browser/Node dependencies. Use new output directories.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment13_run.py preregister --baseline D:\projects\Ai\mini_hivo_experiment12\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment13\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment13_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment13\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment13_evidence_probe.py --suite D:\projects\Ai\mini_hivo_experiment13\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment13\new-evidence
.venv\Scripts\python.exe -X utf8 scripts/experiment13_handoff_probe.py --baseline D:\projects\Ai\mini_hivo_experiment12\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment13\new-handoffs
.venv\Scripts\python.exe -X utf8 scripts/experiment13_report.py --suite D:\projects\Ai\mini_hivo_experiment13\new-suite --probe D:\projects\Ai\mini_hivo_experiment13\new-evidence\comparison.json --handoffs D:\projects\Ai\mini_hivo_experiment13\new-handoffs\comparison.json --output-dir D:\projects\Ai\mini_hivo_experiment13\new-report
```

The report refuses an incomplete final batch. Fresh trials include every
attempt; pre-verification failures do not enter the receipt/PASS denominator.
Calls/time per Root success include failed attempts and exclude fixed planning
and host preflight.

The handoff dataset replays all terminally completed current Workers from
Experiment 12 without selection on PASS. Browser verification is fresh; Node
captured outputs are independently confirmed by executing the suite again.
No new Worker or Root success is attributed to these paired handoff checks.

The protocol dataset executes reference behavior and alternative browser
behavior/targets. Requirement metadata and provenance aliases are explicitly
adversarial replay fixtures. Their rates are not estimates of field error rates.

Raw logs, candidates, native verification payloads and receipts remain under
`D:\projects\Ai\mini_hivo_experiment13`. Summary JSON and the Arabic report are
stored alongside this runbook. No default change is made by this experiment.
