# Team Worklogs & Evidence Locker (`docs/worklogs/INDEX.md`)

This is the team's chronological evidence locker for detailed, small-scoped engineering and research work dossiers.
**Row 1 of the Latest Activity table below is always the most recent worklog across all contributors** — check it before starting your assigned track to see what recently landed on adjacent tracks and any open follow-up issues.

- **Policy:** Read [`../../dev_rules/documentation_rules.md`](../../dev_rules/documentation_rules.md) before creating or updating a dossier.
- **Templates:** Copy [`REPORT_TEMPLATE.md`](REPORT_TEMPLATE.md) (every dossier), [`PROTOCOL_TEMPLATE.md`](PROTOCOL_TEMPLATE.md) (`Type: experiment`), and [`PROVENANCE_TEMPLATE.json`](PROVENANCE_TEMPLATE.json) (`test`/`change`/`experiment`).
- **Auto-regenerate & validate (prevents merge conflicts):** Run `python scripts/update_worklog_index.py` (or `--check` in CI/review) after adding a dossier.
- **Folder hygiene:** Keep `.gitkeep` inside each contributor folder so empty directories remain tracked across branches.
- **Frozen legacy archives:** Historical pre-worklog records stay untouched in [`../../reports/INDEX.md`](../../reports/INDEX.md) and `updates/`.

---

## Latest Activity (Newest First)

| Date | Author | Type | Subsystem | Status | Headline & Open Next Issue | Report | Data / Chain |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `2026-11-26` | kareem | `change` | `dev_rules / docs / worklogs` | `verified` | Separated Mini Hivo's development governance into three layers — prescriptive subsystem rules (`dev_rules/`), shared living architecture... **Next:** Return computed `unified_diff` in `dispatch_worker` (`hivo/hybrid/runner.py`) to catch silent light-worker edit defects immediately | [Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker](kareem/2026-11-26_dev-rules-and-worklog-policy/REPORT.md) | [prov](kareem/2026-11-26_dev-rules-and-worklog-policy/provenance.json) |

---

## Recent Tier 1 Fixes (Quick Log)

Accumulated small code fixes, minor refactors, and typo fixes logged as 1-line rows in each contributor's `docs/worklogs/<person>/LOG.md` (newest 25 shown):

| Date | Author | Area | Tier 1 Change | Verification | PR / Commit | Log |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| *(no Tier 1 entries yet)* | — | — | Append 1 row to `docs/worklogs/<person>/LOG.md` and run `update_worklog_index.py` | — | — | — |

---

## Pending Rule Proposals (Maintainer Review Queue)

Coding agents and feature PRs must **never** auto-edit `dev_rules/*.md`, `AGENTS.md`, or `CLAUDE.md`. Any worklog carrying an unresolved `Rule Proposal:` metadata entry appears below for explicit maintainer review (prefix `[APPLIED]`, `[REJECTED]`, or `[DEFERRED]` once resolved to clear this queue while preserving history):

| Date | Author | Subsystem | Proposed Rule Update (NOT APPLIED) | Evidence Dossier |
| :--- | :--- | :--- | :--- | :--- |
| *(no pending rule proposals)* | — | — | — | — |

---

## Contributor Folders

| Contributor | Folder | Tier 2 Dossiers | Tier 1 Quick Log | Latest Tier 2 Entry |
| :--- | :--- | :---: | :---: | :--- |
| Abozena | [`abozena/`](abozena/) | `0` | [`0`](abozena/LOG.md) | — |
| Ahmed | [`ahmed/`](ahmed/) | `0` | [`0`](ahmed/LOG.md) | — |
| Fatma | [`fatma/`](fatma/) | `0` | [`0`](fatma/LOG.md) | — |
| Kareem | [`kareem/`](kareem/) | `1` | [`0`](kareem/LOG.md) | `2026-11-26` — [Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker](kareem/2026-11-26_dev-rules-and-worklog-policy/REPORT.md) |
| Marihan | [`marihan/`](marihan/) | `0` | [`0`](marihan/LOG.md) | — |
| Renad | [`renad/`](renad/) | `0` | [`0`](renad/LOG.md) | — |
| Rodina | [`rodina/`](rodina/) | `0` | [`0`](rodina/LOG.md) | — |
| Shoip | [`shoip/`](shoip/) | `0` | [`0`](shoip/LOG.md) | — |
| Tasneem | [`tasneem/`](tasneem/) | `0` | [`0`](tasneem/LOG.md) | — |
| Youssef | [`youssef/`](youssef/) | `0` | [`0`](youssef/LOG.md) | — |
