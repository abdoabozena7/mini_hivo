## What Changed
- <Concise list of files/modules added, modified, or removed>

## Why
- <Problem solved, issue fixed, or architectural goal>

## How Verified
- **Unified offline check:** `python scripts/check.py -v` → `<pass/fail/skip counts>`
- **New / updated test(s) & negative case covered:** `<test file::test_name — state the failure/boundary case verified; or "N/A — docs-only PR">`
- **Live / benchmark checks (if any):** `<exact command + outcome, or "Not applicable">`

## Rule Lock & Traceability Check
- [ ] **Confirmed: zero unauthorized edits to `AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md`, or `dev_rules/*.md`** *(CI blocks rule edits unless a maintainer applies the `rule-approved` label on a dedicated rule PR)*
- [ ] **Confirmed: any code change under `hivo/` or `scripts/` includes offline tests under `tests/`** *(or `no-tests-needed` label approved)*
- **Worklog / Quick Log:** <Relative link to Tier 2 `docs/worklogs/<person>/YYYY-MM-DD_<slug>/REPORT.md`, or `"Tier 1 — logged in docs/worklogs/<person>/LOG.md"`>
- **Living docs updated (`docs/`):** <Relative link, or "None">
- **Proposed rule updates (NOT applied here):** <1-line summary + link to `REPORT.md` proposal block, or "None">
