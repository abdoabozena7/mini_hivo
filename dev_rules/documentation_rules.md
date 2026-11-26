# Team Documentation & Worklog Rules (`dev_rules/documentation_rules.md`)

> - **Status:** Living team policy (`v0.5`)
> - **Scope:** Governs how all contributors and coding agents document current system architecture (`docs/`), trace individual engineering/research work (`docs/worklogs/`), find the latest open problem, and **propose** (never auto-apply) rule updates for `dev_rules/`.
> - **Related Specs:** [Rule-Authoring Methodology (`how_to_make_rules.md`)](how_to_make_rules.md), [Benchmarking & Evaluation Rules (`benchmarking_rules.md`)](benchmarking_rules.md), [Repository Workflow (`../AGENTS.md`)](../AGENTS.md), [Worklogs Master Index (`../docs/worklogs/INDEX.md`)](../docs/worklogs/INDEX.md)
> - **Tag Legend:** `[ENFORCED]` = enforced via templates, `.gitattributes`, or `scripts/update_worklog_index.py --check`; `[PROCESS]` = contributor & PR review gate.

---

## 1. The 3-Part Documentation Boundary `[PROCESS]`

Keep prescriptive rules, current-state system documentation, and per-person forensic work records strictly separated:

| Layer | Location | Owner | Purpose | Lifespan |
| :--- | :--- | :--- | :--- | :--- |
| **1. Rules** *(Prescriptive)* | Root `AGENTS.md` + `dev_rules/*_rules.md` | Shared team | **How we MUST do things** — timeless invariants, contracts, capability floors (must obey `how_to_make_rules.md`). | Living (edited via rule-amendment PRs) |
| **2. Living System Docs** *(Descriptive — Current State)* | `docs/` *(top-level, by subsystem)* | Shared team | **Where we are / how each subsystem works today** — implementation maps (`TOOLS_ARCHITECTURE.md`, `ORCHESTRATION_ARCHITECTURE.md`), provider/hardware guides (`HYBRID_MODEL_STRATEGY.md`), papers. **Never stored inside a person's folder.** | Living (updated when code/stack changes) |
| **3. Evidence Locker / Worklogs** *(Descriptive — Forensic History)* | `docs/worklogs/<person>/YYYY-MM-DD_<slug>/` | Individual author | **What this contributor ran, changed, measured, and found** — small-scoped, experiment-grade traceable dossiers. | Append-only (immutable once verified) |

> **Historical Reference Archives `[PROCESS]`:** `reports/`, `updates/`, and `mini.py` are read-only historical archives preserved for chronological record and earlier baseline findings — cite them as reference artifacts and keep them immutable.

---

## 2. Two-Tier Traceability & Parallel Track Visibility `[PROCESS]`

Every contribution must be traceable without creating busywork on trivial edits:

1. **Tier 1 — Small Code Fix / Typo / Minor Refactor (No New Investigation or Metrics):**
   - **No separate dossier subfolder or `REPORT.md` required.**
   - Append **1 row** to your personal quick log (**`docs/worklogs/<person>/LOG.md`**) and run **`python scripts/update_worklog_index.py`** so accumulated small fixes stay visible in [`../docs/worklogs/INDEX.md`](../docs/worklogs/INDEX.md) with zero cross-contributor merge conflicts.
   - Pair with descriptive commits (`type(scope): concise summary`) and [`.github/pull_request_template.md`](../.github/pull_request_template.md).
2. **Tier 2 — Meaningful Feature, Architectural Change, Forensic Analysis, Profiling/Test Run, or Experiment:**
   - Create a dedicated dossier folder under **`docs/worklogs/<person>/YYYY-MM-DD_<short-slug>/`** using lowercase POSIX folder names (date prefix guarantees chronological sorting and zero collisions across parallel branches).
   - Run **`python scripts/update_worklog_index.py`** to regenerate [`../docs/worklogs/INDEX.md`](../docs/worklogs/INDEX.md) deterministically (avoiding manual merge conflicts) and link the dossier in the PR description.
3. **Parallel Track Coordination & Seeing What Recently Landed:**
   - **Cross-track radar:** Before starting your assigned track, open [`../docs/worklogs/INDEX.md`](../docs/worklogs/INDEX.md) — **Row 1 of *Latest Activity (Newest First)*** shows the latest Tier 2 work across all contributors, and ***Recent Tier 1 Fixes (Quick Log)*** shows accumulated small fixes from every contributor's `LOG.md`.
   - **Sequential Continuation (`Builds On`):** When continuing work traced in another contributor's dossier, create a **new dossier in your own folder** and link their report in the **`Builds On:`** metadata field so handoffs form an unbroken chain without duplicating folders.

---

## 3. Unified Core + Modular Blocks (Detailed, Never Boilerplate)

Work dossiers vary in scope (a read-only forensic analysis differs from a full benchmarked code change). Keep a **unified traceability core** across every `REPORT.md`, and attach **only** the modular blocks and data files matching your `Type` (delete unused blocks — never leave empty `"N/A"` tables).

- **Templates `[ENFORCED]`:** [`../docs/worklogs/REPORT_TEMPLATE.md`](../docs/worklogs/REPORT_TEMPLATE.md), [`../docs/worklogs/PROTOCOL_TEMPLATE.md`](../docs/worklogs/PROTOCOL_TEMPLATE.md), and [`../docs/worklogs/PROVENANCE_TEMPLATE.json`](../docs/worklogs/PROVENANCE_TEMPLATE.json).
- **Automated Linter `[ENFORCED]`:** `python scripts/update_worklog_index.py --check` validates folder names, required core metadata, `TL;DR`, sibling `PROTOCOL.md` for experiments, link integrity, privacy hygiene, and `INDEX.md` freshness.

### 3.1 Mandatory Core (Every `REPORT.md`) `[ENFORCED]`
1. **Metadata Block:** `Date` (`YYYY-MM-DD`), `Author`, `Type` (`analysis` | `test` | `change` | `experiment`), `Subsystem`, `Branch & Base Commit`, `Status` (`verified` | `completed-analysis` | `partial` | `blocked` | `in-progress`), plus optional `Builds On`, `Next / Open Issue`, and `Rule Proposal` (1-line summary of any proposed rule update, or `None`).
2. **TL;DR (3–5 lines):** What was done, the headline outcome/finding, and the verified scope boundary (the first sentence populates `INDEX.md`).
3. **Limitations, Artifacts, Reproduction & Rule Proposals:** Exact root-relative commands/inputs inspected, honest gaps/failures, links to sibling artifacts/living `docs/` updates, and any structured **Proposed Rule Update (NOT APPLIED)** block (never auto-editing `dev_rules/`).

### 3.2 Modular Blocks & Sibling Files by `Type` `[PROCESS]`
If a session spans multiple activities (e.g., code fixes + a formal benchmark), set **`Type`** to the highest precedence (**`experiment > change > test > analysis`**) and include every modular block that applies (for example, an `experiment` that also fixed harness bugs includes Block C `Exact Changes Made`).

| `Type` | When to Use | Required Modular Blocks in `REPORT.md` | Expected Sibling Files |
| :--- | :--- | :--- | :--- |
| **`analysis`** | Forensic debugging, root-cause trace, log/code audit, paper/option comparison *(no code changed)* | Block A (`Question & Inputs Inspected`, `Detailed Findings & Root Cause` separating **proven causes** vs. **hypotheses**, `Recommended Next Actions`) | Optional curated excerpts/logs in `artifacts/` |
| **`test`** | Hardware/VRAM profiling, reproducing a bug, running verification passes on a branch | Block B (`Setup & Environment`) + Block D (`Verification & Checks`) | `provenance.json`, `results.json` |
| **`change`** | Implementing a feature, fix, or refactor + verifying it | Block C (`Problem & Root Cause`, `Exact Changes Made` before → after table) + Block D (`Verification & Checks`) | `provenance.json` *(+ `results.json` if metrics measured)* |
| **`experiment`** | Hypothesis-driven benchmark or A/B evaluation *(follow [`benchmarking_rules.md`](benchmarking_rules.md) for KPIs, 8-point Truth Check & failure triage)* | Block B (`Setup & Environment`) + Block D (`Verification & Checks`) + Block E (`Experiment Results & Intermediate Defects Caught`) *(+ Block C if code changed)* | **`PROTOCOL.md`** *(enforced)* + `results.json` + `provenance.json` + `patches/` or `artifacts/` |

### 3.3 Machine-Readable JSON Conventions `[PROCESS]`
- **`provenance.json`:** Copy [`../docs/worklogs/PROVENANCE_TEMPLATE.json`](../docs/worklogs/PROVENANCE_TEMPLATE.json) (`date`, `author`, `type`, `subsystem`, `branch`, `base_commit`, `tested_revision`, `source_sha256`, `environment`, `models`, `reproduction_commands`).
- **`results.json`:** Use a uniform 3-key top-level envelope: `{"meta": {...}, "summary": {...}, "cases": [...]}` so per-case metrics stay flexible while remaining machine-readable across the team.

---

## 4. Forensic Rigor & Honesty Requirements `[PROCESS]`

1. **Never copy source trees into `docs/worklogs/`:** Code lives strictly in the codebase (`hivo/`, `scripts/`, `tests/`); worklogs link to files, commits, and diffs.
2. **Separate verification classes explicitly:** Label every check as **unit**, **integration**, **controlled functional**, **live-model E2E**, or **regression**, stating exact commands, exit codes, and mocked vs. real boundaries.
3. **Preserve full denominators & failures:** Never drop aborted runs, quota blocks, environment failures, or skips from reported counts. State sample size explicitly alongside percentages whenever $N < 30$.
4. **Lock `PROTOCOL.md` before interpreting benchmark results:** For `Type: experiment`, record fixed inputs, sampling seeds, zero-leakage boundaries, and acceptance criteria cleanly.

---

## 5. Living-Doc Updates & Strict Propose-Only Rule Workflow `[PROCESS]`

1. **Updating Living Architecture Docs (`docs/`):** Whenever a worklog changes current subsystem modules, APIs, or deployment/provider guidance, update the shared subsystem doc under `docs/` (e.g., `docs/TOOLS_ARCHITECTURE.md`, `docs/ORCHESTRATION_ARCHITECTURE.md`, `docs/HYBRID_MODEL_STRATEGY.md`).
2. **Proposing Rule Updates (`dev_rules/` — STRICTLY READ-ONLY DURING NORMAL WORK):**
   - Contributors and coding agents must **NEVER auto-edit `dev_rules/*.md`, `AGENTS.md`, `CLAUDE.md`, or `**/AGENTS.md`** inside a feature, bugfix, analysis, test, or experiment branch.
   - When real evidence hits one of the 5 update triggers in [`how_to_make_rules.md`](how_to_make_rules.md) (`ADD`, `PROMOTE [TARGET -> ENFORCED]`, `AMEND`, or `RETIRE`):
     1. Record the concrete evidence + structured **Proposed Rule Update (NOT APPLIED)** block inside your `docs/worklogs/<person>/YYYY-MM-DD_<slug>/REPORT.md`.
     2. Populate `- **Rule Proposal:** <short action + target file>` in `Metadata` and run `python scripts/update_worklog_index.py` so `docs/worklogs/INDEX.md` automatically lists it in the **Pending Rule Proposals** review queue.
     3. Wait for explicit maintainer review and approval before any edit is applied on a dedicated rule-only branch/PR.

---

## 6. Privacy, Sanitization & Git Hygiene

1. **Zero secrets or private metadata `[ENFORCED]`:** Never commit `.env`, API keys, real vendor key prefixes, SQLite databases/sidecars (`.sqlite*`, `.db`), raw unredacted logs, account/org IDs, or personal absolute paths into `docs/worklogs/` or `docs/` (checked by `scripts/update_worklog_index.py --check`). Keep raw run outputs strictly inside gitignored `output/`.
2. **Relative links & canonical line endings `[ENFORCED]`:** Use repository-relative Markdown links and runnable root-relative commands. `.gitattributes` enforces canonical LF line endings across `dev_rules/*.md`, `docs/worklogs/**/*.md`, `docs/worklogs/**/*.json`, and `-whitespace` on `docs/worklogs/**/patches/*.diff`.
3. **Dedicated branches & contributor ownership `[PROCESS]`:** Keep unrelated worklogs on dedicated branches; never force-push or overwrite another contributor's completed dossier (continue their work in your own folder via `Builds On:`).

---

## 7. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial team documentation & worklog policy establishing the 3-part boundary, 2-tier cutoff, Unified Core + Modular Blocks, rule-promotion loop, and privacy hygiene. |
| `v0.2` | 2026-11-26 | Added `scripts/update_worklog_index.py` auto-index & `--check` validation, chronological lookup & sequential continuation (`Builds On` + `Next / Open Issue`), `PROVENANCE_TEMPLATE.json` & `results.json` envelope, primary `Type` precedence + Block E, explicit Rule-Amendment Proposal workflow, and clean per-item status tags. |
| `v0.3` | 2026-11-26 | Enforced strict Propose-Only Rule Lock (zero auto-edits to `dev_rules/` during normal work) and added `Rule Proposal:` metadata field feeding `docs/worklogs/INDEX.md`'s Pending Rule Proposals review queue. |
| `v0.4` | 2026-11-26 | Added per-contributor Tier 1 quick logs (`docs/worklogs/<person>/LOG.md`) auto-indexed into `INDEX.md`'s Recent Tier 1 Fixes view, and aligned section 2.3 to parallel assigned-track coordination. |
| `v0.5` | 2026-11-26 | Linked `benchmarking_rules.md` for `Type: experiment` KPI/Truth-Check standards and simplified historical-archive wording to positive framing. |
