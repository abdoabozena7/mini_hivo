# Local Mini Hivo handoff — Rodina

2026-11-27, Africa/Cairo. **Local review-ready package; Git handoff/publication is not complete.** Branch `rodina/dev-turn-2026-11-20`; HEAD `ef08b09708a295d5765d4c207141aa8a11d85f72`; index empty. All changes remain uncommitted. The underlying snapshot history remains independent of Kareem's original ancestry; future integration requires its own reviewed plan.

## Phase checklist

| Phase | Result | Exact scope / primary record |
|---|---|---|
| A | PASS | Final-source4096/1024 packet preservation, positive root acceptance and negative bounded repair/rollback; [report](2026-11-27_packet-compaction-verification/REPORT.md) / R011 |
| B | PASS | Parsed-option consistency and preserved requested reasoning; [report](2026-11-27_model-configuration-fixes/REPORT.md) / R012 |
| C | PASS | Portable browser selection, launch provenance and fail-fast absence handling; [report](2026-11-27_browser-harness-portability/REPORT.md) / R013 |
| D | PASS | Three actual dated dossiers, [personal log](LOG.md) and [historical map](HISTORICAL_MAP.md); no official index or rules changed |
| E | PASS | This local package, [complete path inventory](WORKTREE_INVENTORY.md), per-phase source manifests and [final focused checks](FINAL_CHECKS.json); unpublished |

## Definitive changes

- Packet references no longer repeat derived lengths. Full hash-bound records remain retrievable; diagnostics use canonical same-field references and preserve required route state, observations, IDs, scopes and unknown constraints. Independent reconstruction confirms full original JSON, history, oracle and native argument schema data. No source/verification gate, context/reserve or512-MiB floor was lowered.
- CLI assignments carry explicit parser provenance. Both option spellings, explicit defaults, JSON conflicts and programmatic callers behave consistently. Cloud reasoning is retained and capability-checked; unsupported controls are not silently erased. Provider adapters/free-only protections were preserved.
- Browser selection uses an explicit executable or installed bundle/PATH/standard location, then a real Chromium launch/version check. Historical private browser records are unnecessary. Missing/incompatible browsers stop before provider or project creation. No installation is automatic.

New source: `scripts/browser_selection.py`, `tests/test_model_configuration_fixes.py`, `tests/test_browser_selection.py`. Modified existing development source in this session: `hivo/worker_packets.py`, `scripts/audit_worker_packets.py`, `tests/test_worker_packets.py`, `hivo/model_configuration.py`, `mini.py` (parsed settings only), `scripts/provider_controller_functional.py`. The inventory includes all preserved earlier modifications/untracked files; it is not a staging list.

## Verification boundaries and source identities

| Evidence class | Actual result | Source identity / retained run |
|---|---|---|
| Offline focused A |39 pass; zero failures/errors/skips | A results manifest; `output/prioritized-handoff/20261127-phase-a-unit-002` |
| Controlled scripted-provider A, real tools/browser | Working: both children/read-only parent/root done; increment+persistence true. Broken: behavior rejected, two repairs bounded, failed child rolled back, foundation retained, root failed.29/39 worker packets, max2659/3061 plus1024 within4096; independent audits pass. | Full runtime source hashes in A results; `output/packet-compaction/20261127-{working,inert}-frozen-003` |
| Offline affected B |91 pass; zero failures/errors/skips;10 new configuration methods exercise real parser/JSON/config objects with scripted metadata and blocked HTTP | B results; `output/prioritized-handoff/20261127-phase-b-checks-final-001` |
| Offline C |12 pass; zero failures/errors/skips; launchers are mocked here | C results; `output/prioritized-handoff/20261127-phase-c-unit-final-001` |
| Actual browser + scripted-provider C | Explicit Chrome and automatic discovery validate actual version158.0.8127.88. Controlled application reaches read-only root acceptance; independent audit max2661+1024. Invalid override fails nonzero with zero provider requests/no workspace. | C runtime manifest includes browser helper; `output/prioritized-handoff/20261127-phase-c-{controlled-001,discovery-001,missing-browser-001}` |
| Final focused offline composition |61 pass; zero failures/errors/skips; overlaps earlier methods and is not added to them | FINAL_CHECKS.json; `output/prioritized-handoff/20261127-final-focused-001` |
| Real local-model inference | NOT RUN in these phases. Earlier R010 Qwen coding/tool probe is inherited evidence only. | Original R010 record and private provider-generalization output |
| Genuine cloud/hybrid live E2E | NOT RUN; no Nemotron/OpenRouter calls, Gemma/Qwen inference, or live To-Do generation | Requires separate user approval |

The A negative chain was executed before the later CLI/browser-selection changes; its worker/acceptance source remains unchanged. C re-executed the positive controller/browser chain on the later source, and the final61-method check uses the final source. Do not describe this as a final live application campaign or universal framework proof. Each phase's full hashes pin its actual uncommitted revision; HEAD alone does not identify these changes.

## Root causes, original failures and preservation

Original first-Builder packet3769+1024 could not fit4096. The frozen negative run on November27 reproduced3076, then a second repair exposed3342. Those runs remain under `output/packet-compaction/20261127-{working,inert}-frozen-001/002`; older November25/26 runs are preserved. Current verified A negative max3061 leaves11 estimated tokens of headroom; larger mandatory packets can still fail closed. Character-based estimates are not measured tokenizer guarantees.

Configuration baseline002 reports7 methods with10 failure records and1 error, including subtests. Browser baseline reports1 structural failure. Neither is reclassified as a passing run. Unit logs/results and temporary test cohorts remain in their unique ignored output directories. Source-snapshot and receipt/provenance audits are distinct from model reliability.

Historical R004–R010 and their curated/private originals remain in place. [Historical map](HISTORICAL_MAP.md) links them without assigning guessed execution dates or creating duplicate historical dossiers. The November27 audit is immutable. No official v2 files, locked rules, CODEOWNERS, reviewer approval, Tier designation or generated `docs/worklogs/INDEX.md` were fabricated.

## Reproduction without live providers

Use the checkout's existing Python environment and dependencies; no installation is part of these commands. All output directories must be NEW. The offline runner patches model seams; the controlled harness injects provider HTTP/model decisions and uses the real local browser.

```powershell
# From repository root. Example new directories; do not overwrite retained runs.
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/my-new-offline-check test_worker_packets test_model_configuration_fixes test_browser_selection
.venv/Scripts/python.exe -B -X utf8 scripts/provider_controller_functional.py --worker-context 4096 --expect-compact-success --capture-packets --output-dir output/my-new-working-check
.venv/Scripts/python.exe -B -X utf8 scripts/provider_controller_functional.py --variant inert --worker-context 4096 --expect-compact-success --capture-packets --output-dir output/my-new-inert-check
.venv/Scripts/python.exe -B -X utf8 scripts/audit_worker_packets.py --run-dir output/my-new-working-check
.venv/Scripts/python.exe -B -X utf8 scripts/audit_worker_packets.py --run-dir output/my-new-inert-check
```

For explicit browser selection add `--browser-executable` with an installed compatible executable. Actual executed commands/counts are also in R011–R013; the original exact executable path is private browser provenance, not a shared fixed path. Browser/native-process permission may still be required by the execution environment; do not bypass its review. Do not substitute broad test discovery: some historical tests call live providers.

## Minimal continuation and remaining risks

1. Review these reports, source manifests and the full inventory. Continue only the next separately approved scope. Keep the provider adapter, authorization/freshness/rollback and read-only parent contracts intact.
2. Before any small live test, agree on the exact configurable provider/model pair and request budget. The preferred all-local Gemma reasoning/Qwen worker arrangement is representable, but simultaneous residency is not qualified; no coordinator was implemented. Do not load both automatically, weaken memory checks, raise context or substitute models. A single-model/phase qualification strategy needs its own safe design and approval where applicable.
3. Live Qwen handling of the compact representation and live request-to-delivery remain unverified. The proven fixture has three Counter requirements; it is not a full To-Do acceptance result. Schema discovery consumes existing model rounds; limits were not expanded. Alternate-strategy fixture replies in the negative test are invalid and bounded/rejected, not a proven successful repair.
4. Obtain the actual official v2 tree/methodology when integration is authorized. Decide the frozen v1 baseline and modular adapter seams; do not move the monolith or merge/cherry-pick the team update automatically. Official tiers/checker/index generation remain pending.
5. Publishing needs separate explicit authorization and privacy review. Never stage all paths blindly: the preserved inventory includes raw/runtime material such as `list/project-1/.agent_host_preflight.json`. Future approved personal/teamleader update branches should share the reviewed final commit; never overwrite another branch or touch Team Leader main. No Git publication has been performed.

Builds On: [R010](../../../updates/R_UPDATE_010.md), [R011](../../../updates/R_UPDATE_011.md), [R012](../../../updates/R_UPDATE_012.md), [R013](../../../updates/R_UPDATE_013.md), [audit](../../V2_GENERALIZATION_COMPATIBILITY_AUDIT_2026-11-27.md). Rule Proposal: **None**.
