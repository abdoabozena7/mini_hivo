# Experiment 14 — Strict Aggregation Compatibility

## Fixed inputs

Three eligible Experiment 13 fixtures: `arena_arrow`, `arena_q_restart`,
`node_unique`. Three fresh trials per task under `monotonic` and `strict`:
18 attempts, `gemma4:e4b`, 28 Worker tool steps. Approved contracts and seed
bytes are unchanged. Timer/Python are excluded because of upstream blockers.

`--semantic-evidence-policy strict` enables this experiment. Default remains
`current`; `compatible` and `monotonic` remain available. No default promotion.

The only intervention is legacy browser/focused-test aggregation matching.
Worker prompts, progress, mutation grounding, localization, verifier, recovery,
model, budgets, approval and parent integration remain fixed. Final receipt
factory and validator are byte-identical to Experiment 13. Authority/direct
oracle closures and deterministic syntax validators retain their existing gates.

## Matching

- Browser proof needs the required claim identity, same target/surface,
  compatible assertion parameters, executed native observations, PASS and
  supported controller provenance. A cached PASS summary cannot replace a
  missing, failed or different fresh behavior. The inventory is independently
  reassessed before accepting it.
- Empty extra browser inventory is UNKNOWN. A complete fresh native payload
  can independently supply the exact assertions. Missing assertions or required
  claim identities cannot match.
- Unit proof requires execution of the exact approved suite. That route binds
  the obligation to the suite behavior even if extra semantic fields are absent.
  Declared foreign requirement, behavior, target or provenance is rejected.
  Matching does not search stdout or use a generic tests marker.
- Commands are conservatively recognized as a direct supported interpreter
  invocation with a single suite path. Arbitrary shell wrappers and unsupported
  provenance aliases cannot be guessed compatible.
- Nonapplicable browser routes cannot add an empty inventory to a Node receipt.

The independent final receipt gate stays unchanged. In production the evidence
gate rejects unsuccessful aggregation before committing a verified receipt.
Protocol probes additionally attempt receipt construction for rejected inputs
solely to measure the independent final guard; these are not issued receipts.

## Reproduce

Requires the original Experiment 13 suite, local Ollama model and existing
Node/browser dependencies. Use fresh output directories.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment14_run.py preregister --baseline D:\projects\Ai\mini_hivo_experiment13\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment14\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment14_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment14\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment14_evidence_probe.py --suite D:\projects\Ai\mini_hivo_experiment14\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment14\new-evidence
.venv\Scripts\python.exe -X utf8 scripts/experiment14_handoff_probe.py --baseline D:\projects\Ai\mini_hivo_experiment13\suite-v1 --output-dir D:\projects\Ai\mini_hivo_experiment14\new-handoffs
.venv\Scripts\python.exe -X utf8 scripts/experiment14_report.py --suite D:\projects\Ai\mini_hivo_experiment14\new-suite --probe D:\projects\Ai\mini_hivo_experiment14\new-evidence\comparison.json --handoffs D:\projects\Ai\mini_hivo_experiment14\new-handoffs\comparison.json --output-dir D:\projects\Ai\mini_hivo_experiment14\new-report
```

The complete measured version is `suite-v2`. Source hashes are preregistered;
no production edits occur during its trials. All 18 attempts stay in the fresh
denominator, including pre-verification failures. Calls/time per verified Root
include failed attempts; frozen planning and host preflight costs are excluded.
Root success requires fresh parent proof covering the requirement.

Paired handoffs replay every terminally completed `monotonic` Worker from
Experiment 13 without selecting on PASS. Browser verification is fresh; Node
captured suite results are independently re-executed on reconstructed sources.
These runs claim no new Worker or Root success. Input hashes match across arms.

Protocol cases retain native reference and alternative browser behavior/target
payloads. Requirement/provenance modifications are declared protocol replays,
not model-produced evidence. Their rates do not estimate field error rates.

Development version v1 exposed the skipped-browser empty-artifact bug during
paired Node replay. Its incomplete batch was stopped and retained separately.
After fixing artifact generation within aggregation, all measurements were
repeated on v2. Pilot results are not mixed into the fixed-version rates.

Raw evidence and logs: `D:\projects\Ai\mini_hivo_experiment14`. Summary JSON,
Arabic report and preregistration manifest are stored beside this runbook.
