# Subtree Guardrail Tripwire (`hivo/providers/`)

**STOP before planning or editing any file in `hivo/providers/`:**
1. Read [`../../dev_rules/orchestration_rules.md`](../../dev_rules/orchestration_rules.md) (config-only swapping, stdlib transport, thinking isolation, deadline-clamped backoff, zero fabricated fallbacks).
2. Read [`../../docs/ORCHESTRATION_ARCHITECTURE.md`](../../docs/ORCHESTRATION_ARCHITECTURE.md) (current implemented module map & `EndpointConfig`).
3. **HARD LOCK:** Do **NOT** edit `dev_rules/*.md`, `AGENTS.md`, or `CLAUDE.md` during normal provider work. Record any suggested rule change as a **Proposed Rule Update (NOT APPLIED)** in your worklog `REPORT.md` and final response.
