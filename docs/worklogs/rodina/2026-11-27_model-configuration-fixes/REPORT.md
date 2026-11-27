# Phase B — Model configuration consistency

Status: **VERIFIED**, offline/configuration scope. Executed2026-11-27, Africa/Cairo. Full A–M record: [R_UPDATE_012](../../../../updates/R_UPDATE_012.md). [Results and exact tested source hashes](results.json).

Root causes: process-global argv token matching lost parser intent; cloud menu construction discarded reasoning before capability validation. Changed `hivo/model_configuration.py`, `mini.py::parse_args`, and new `tests/test_model_configuration_fixes.py`.

Both syntaxes for seven options now reject JSON conflicts identically, including explicit default values. Parser defaults load JSON normally. Programmatic callers are independent of host argv; explicitly supplied settings remain explicit. Supported cloud reasoning remains selected; unsupported reasoning yields a capability error with no fallback. Native provider adapters, authorization and strict-free policy remain unchanged.

91 focused methods passed, zero failures/errors/skips, exit0. The new tests exercise actual parsing, actual JSON files and actual configuration objects; provider catalogues/capabilities are injected and all HTTP is blocked. Baseline002 preserves7 methods with10 failure records and1 error (including subtests); baseline001 and intermediate88-pass result also remain private and unchanged. No live model or cloud test was run. Commands and exact raw directories are in R012.

Builds On: [R010](../../../../updates/R_UPDATE_010.md), [Phase A](../2026-11-27_packet-compaction-verification/REPORT.md), [audit](../../../V2_GENERALIZATION_COMPATIBILITY_AUDIT_2026-11-27.md). Rule Proposal: **None**. No commit, staging or remote operation. Official v2 integration and Tier classification remain pending maintainer review.
