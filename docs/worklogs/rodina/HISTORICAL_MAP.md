# Historical migration map — proposals, not migrated dossiers

Prepared2026-11-27. Existing reports/evidence are immutable references. No original was moved, deleted, deduplicated or reclassified as a fresh test. Proposed historical dossier labels below are subjects only; choose dates/names after inspecting the actual original execution metadata. A date in a filename is not proof of execution time. Tier1/Tier2 remains unassigned without the official definitions. Rule Proposal: **None**.

| Proposed Rodina dossier subject | Original report | Exact retained evidence root | Builds On |
|---|---|---|---|
| M0 source ownership / manifest attribution | [M0](../../../updates/M0_INVESTIGATION_2026-11-21.md) | `evidence/m0-characterization-20261121/` and original private `output/m0-characterization/` | Original teammate handoff and historical repair baseline |
| Verified manifest provenance | [R004](../../../updates/R_UPDATE_004.md) | `evidence/m0-characterization-20261121/manifest.json` | M0 |
| Receipt dependency freshness | [R005](../../../updates/R_UPDATE_005.md) | `evidence/receipt-freshness-20261121/` | R004 |
| Windows path identity | [R006](../../../updates/R_UPDATE_006.md) | `evidence/manifest-path-identity-20261121/` | R004/R005 |
| Requirement ownership | [R007](../../../updates/R_UPDATE_007.md) | `evidence/acceptance-phase-20261121/ownership.json` | M0/R006 |
| Behavioral source obligations | [R008](../../../updates/R_UPDATE_008.md) | `evidence/acceptance-phase-20261121/behavior.json` | R007/R005 |
| Read-only parent acceptance | [R009](../../../updates/R_UPDATE_009.md) | `evidence/acceptance-phase-20261121/parent.json` | R007/R008 |
| Provider/model generalization | [R010](../../../updates/R_UPDATE_010.md) | `evidence/provider-generalization-20261125/summary-final.json`; private `output/provider-generalization/` | R009 |
| Host-resource diagnosis | [Host diagnosis](../../../updates/HOST_PREFLIGHT_MEMORY_DIAGNOSIS_2026-11-21.md) | `evidence/host-preflight-memory-20261121/` | Original preflight observations; R010 local probe is separate |

Follow the individual report's exact run IDs, source hashes, dates and limitations; root directories here are navigation, not substitute evidence. The mapping does not claim every old issue is solved today. New verified work has actual dated dossiers in [LOG.md](LOG.md), with A–M records R011–R013. No historical execution date was inferred or rewritten, and no historical dossier folder was materialized.

Future official migration requires the real team layout/tiers and actual checker/index generator. Do not manually create `docs/worklogs/INDEX.md`; do not edit locked rules, reviewer permissions or CODEOWNERS to implement this map.
