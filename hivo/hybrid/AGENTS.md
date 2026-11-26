# Subtree Guardrail Tripwire (`hivo/hybrid/`)

**STOP before planning or editing any file in `hivo/hybrid/`:**
1. Read [`../../dev_rules/orchestration_rules.md`](../../dev_rules/orchestration_rules.md) (asymmetric roles, zero orchestrator code-writing, two-pass compaction, `O(target_files)` rollback, diff handoffs, contract-complete splits).
2. Read [`../../docs/ORCHESTRATION_ARCHITECTURE.md`](../../docs/ORCHESTRATION_ARCHITECTURE.md) (current runtime flow & `HybridRunConfig`).
3. **HARD LOCK:** Do **NOT** edit `dev_rules/*.md`, `AGENTS.md`, or `CLAUDE.md` during normal orchestration work. Record any suggested rule change as a **Proposed Rule Update (NOT APPLIED)** in your worklog `REPORT.md` and final response.
