# Phase C — Browser harness portability

Status: **VERIFIED** for the declared unit/startup/controlled scope. Executed2026-11-27, Africa/Cairo. Full A–M record: [R_UPDATE_013](../../../../updates/R_UPDATE_013.md). [Results and source hashes](results.json).

Earliest defect: main read its browser path from a private historical m0 result. New `scripts/browser_selection.py` resolves an explicit override or installed bundle/PATH/standard location, then validates actual Chromium launch and version. `scripts/provider_controller_functional.py` records provenance and refuses missing/unusable browsers before any provider or workspace creation. `tests/test_browser_selection.py` covers the contract. No verification architecture or native application oracle was replaced.

12 focused methods pass, zero failures/errors/skips. Unit executable files and launchers are fixtures, not real browser proof. Separate actual Chrome validation and the full controlled browser chain pass: both children, read-only parent/root, increment and persistence. Recorded actual version158.0.8127.88. Auto-discovery also validates the installed-location browser. An actual invalid-override invocation fails nonzero, with zero provider requests and no project workspace. Detailed evidence, commands and failure statuses are in R013; independent packet audit passes all29 packets.

Original baseline1 failure and intermediate11-pass cohort are retained. No package/browser was installed. No model was loaded or called; all model/provider decisions in the controller fixture were scripted. Real local/cloud application delivery remains NOT TESTED.

Builds On: [Phase A](../2026-11-27_packet-compaction-verification/REPORT.md), [Phase B](../2026-11-27_model-configuration-fixes/REPORT.md), [audit](../../../V2_GENERALIZATION_COMPATIBILITY_AUDIT_2026-11-27.md). Rule Proposal: **None**. Provisional contributor documentation; no official generated index, Tier classification or Git publication.
