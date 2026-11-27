# R_UPDATE_011 — Complete controlled 4096-context child and root verification

## A. Identification
2026-11-27, Africa/Cairo; branch `rodina/dev-turn-2026-11-20`; base HEAD `ef08b09708a295d5765d4c207141aa8a11d85f72` plus preserved local corrections. VERIFIED controlled scope; containing commit/PR pending. [Full contributor report](../docs/worklogs/rodina/2026-11-27_packet-compaction-verification/REPORT.md).
## B. Original problem
Final frozen negative reproduction: Repairer3076 input +1024 reserve exceeded4096; project correctly refused it. Earlier first-Builder baseline was3769+1024. No live inference was used.
## C. Why necessary
Safe recovery must retain required diagnostics while fitting the configured contract; page loading and verifier prose cannot certify behavior.
## D. Root cause
Repeated derived cache lengths and escaped/provenance-heavy verification diagnostics inflated the packet. After the first small correction, actual second-repair evidence exposed3342 input tokens. Retain both failed frozen cohorts001/002.
## E. Changes
`hivo/worker_packets.py`: digest-only references, bounded derived length retrieval, exact same-field references for diagnostic details, explicit required-route state and unknown constraints; shorter equivalent metadata captions. `scripts/audit_worker_packets.py`: independently reconstruct field references and validate visible state. `tests/test_worker_packets.py`: regression additions. Existing mini integration preserved.
## F. Mechanism
Full records remain SHA-256-bound and per-execution. Scope, required behavior, IDs and native arguments remain intact. Diagnostic references are data, never reusable authorization. No context/reserve, RAM floor, impact gate, parent permission or provider fallback was changed.
## G. Functional verification
Frozen working003: both children done, independent increment/persistence true, read-only parent/root done. Frozen inert003: behavior false, two bounded repairs, correctly failed root and retained foundation. All source-before/after checks pass. Independent audits:29/39 packets, maxima2659/3061 respectively, each plus1024 fits4096. These are controlled scripted-provider runs with real tools/browser, not live-model E2E.
## H. Additional tests
39 focused tests passed, zero failures/errors/skips, exit0. The inherited226-method cohort was inspected, not rerun or summed.
## I. Compatibility and failures
Frozen001 retained3076 overflow; frozen002 exposed3342 second-repair overflow. All originals retained. Negative alternate-strategy fixture replies remain semantically invalid and are bounded/rejected. This is not a successful repair claim.
## J. Impact
The declared working fixture reaches justified read-only acceptance; broken behavior cannot exploit page loading or missing diagnostics to pass.
## K. Limits
Estimated tokens only; no fresh local/cloud inference. Three-requirement fixture only. Unknown/noncompactable contracts still fail closed. Full v2 migration and browser portability are separate.
## L. Evidence and reproduction
[Curated source hashes/outcomes](../docs/worklogs/rodina/2026-11-27_packet-compaction-verification/results.json). Original raw results remain private under `output/packet-compaction/`; hashes identify exact working-tree bytes, not staged Git blobs. Use new output directories on reproduction:
```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/prioritized-handoff/20261127-phase-a-unit-002 test_worker_packets
.venv/Scripts/python.exe -u -B -X utf8 scripts/provider_controller_functional.py --worker-context 4096 --expect-compact-success --capture-packets --output-dir output/packet-compaction/20261127-working-frozen-003
.venv/Scripts/python.exe -u -B -X utf8 scripts/provider_controller_functional.py --variant inert --worker-context 4096 --expect-compact-success --capture-packets --output-dir output/packet-compaction/20261127-inert-frozen-003
.venv/Scripts/python.exe -B -X utf8 scripts/audit_worker_packets.py --run-dir output/packet-compaction/20261127-working-frozen-003
.venv/Scripts/python.exe -B -X utf8 scripts/audit_worker_packets.py --run-dir output/packet-compaction/20261127-inert-frozen-003
```
## M. Team summary
Proposed PR title: Preserve complete worker diagnostics within the configured4096 context. Root acceptance and safe rejection are controlled-verified;39 focused tests pass. Local/uncommitted, no publication. Builds On R010/R009/R008. Rule Proposal: None.
