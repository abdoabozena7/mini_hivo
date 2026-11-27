# How to Make Rules (`dev_rules/how_to_make_rules.md`)

> - **Status:** Living meta-specification (`v0.6`)
> - **Scope:** Governs how all development rules in `dev_rules/` are authored, auto-invoked by coding agents (`Antigravity`, `Codex`, `Claude Code`), proposed for update, and retired across Mini Hivo.
> - **Related Specs:** [Repository Workflow (`../AGENTS.md`)](../AGENTS.md), [Claude Code Entrypoint (`../CLAUDE.md`)](../CLAUDE.md), [Documentation & Worklog Rules (`documentation_rules.md`)](documentation_rules.md), [Tool Architecture & Design Rules (`tool_rules.md`)](tool_rules.md), [Orchestration Guardrails (`orchestration_rules.md`)](orchestration_rules.md), [Benchmarking & Evaluation Rules (`benchmarking_rules.md`)](benchmarking_rules.md)
> - **Runtime Boundary:** Files in `dev_rules/` are **development-time guardrails for engineers and AI assistants only**. Mini Hivo's runtime code (`hivo/`, `mini.py`) must never import, parse, or depend on `dev_rules/`.
> - **Hard Rule Lock:** `AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md`, and `dev_rules/*.md` are **STRICTLY READ-ONLY** during normal development. Coding agents must **PROPOSE** rule updates in worklogs and responses — **never auto-apply edits** to rule files without explicit maintainer authorization.

---

## 1. Prescriptive Rules vs. Descriptive Documentation (The 3-Part Layout)

Rules become restrictive and stale when concrete changelogs, hardware recipes, vendor quotas, or one-off experiment logs leak into them. Separate **prescriptive rules** (*how we MUST handle work*) from **descriptive documentation** (*how the system currently works and what we actually ran/measured*):

| Layer | Location | Role & Tone | What Belongs Here | Update Cadence |
| :--- | :--- | :--- | :--- | :--- |
| **1. Rules** *(Global)* | Root `AGENTS.md` + `dev_rules/*_rules.md` | **Prescriptive** (*"How we MUST do things"*) | Timeless invariants, subsystem contracts, capability floors, failure-class preventions, and **non-binding `(e.g., ...)` examples** | At completed architectural milestones |
| **2. Living System Docs** *(Global, by Subsystem)* | `docs/` *(and optional package READMEs)* | **Descriptive — Current State** (*"Where we are / how it works today"*) | Subsystem implementation maps, API/config references, provider/hardware guides, research papers | Whenever code, providers, or architecture change |
| **3. Worklogs & Evidence Locker** *(By Person & Task)* | `docs/worklogs/` *(historical reference archives in `reports/`, `updates/`, `mini.py`)* | **Descriptive — Forensic History** (*"What I ran, changed, and found"*) | Per-person, small-scoped forensic records (`REPORT.md`, `PROTOCOL.md`, `results.json`, `provenance.json`, `patches/`) with exact commits, devices, models, commands, and denominators | Append-only per completed work dossier |

> **Core Workflow — Record Concrete → Promote Invariant With a Back-Link:**
> Never dump concrete bug-fix changelogs, GPU specs, or experiment numbers into `dev_rules/`. Record concrete details in `docs/worklogs/` (and update living `docs/` as needed), then **promote only the generalized invariant** into `dev_rules/<subsystem>_rules.md` with a concise back-link in its Revision Log.

> **Root Entrypoint Rule:** Keep [`../AGENTS.md`](../AGENTS.md) at the repository root (coding agents auto-discover it there) for repository-wide Git, workflow, and verification discipline. Put all subsystem engineering rules inside `dev_rules/`. Keep rules as plain Markdown (universal across all team editors and AI tools), reserving custom skills (`skills/`) strictly for repeatable multi-step tool workflows.

---

## 2. The Threshold of Specificity — 3 Mandatory Tests

Good rules avoid two opposite traps: **vague slogans** (*"write clean code"*, *"handle errors nicely"*) that everyone ignores, and **hardcoded developer-machine recipes** that break the moment hardware, models, or vendors change.

Every rule added to `dev_rules/` must pass all three tests:

### Test 1 — Mechanism vs. Instance (Be Specific on *How*, Never Lock to *Who/Where*)
- **BE VERY SPECIFIC about architectural mechanisms, contracts, bounds, and failure classes.** These remain true on every machine and model family.
- **NEVER lock a rule to a concrete instance** — one model tag, one developer's GPU/VRAM size, one OS quirk, one vendor's rate limit or price, or one benchmark ticket ID.
- If naming a model, provider, or tool helps readers understand a tier or pattern, label it explicitly as an **illustrative example** (`e.g., ...`) and state the actual requirement as a **behavioral capability floor or invariant**.

| Too Vague (Useless) | Too Hardcoded (Brittle) | Right Specificity (Timeless Guardrail) |
| :--- | :--- | :--- |
| *"Keep context small."* | *"Stay below Groq's 7,000 ITPM limit on Turn 7."* | *"Enforce per-role inline output caps and two-pass anchor-pinned history compaction before every turn so multi-turn runs stay under configured prompt ceilings."* |
| *"Use a good local model."* | *"Always run `qwen3.5:2b-q4_K_M` on GTX 1650 4 GB."* | *"Keep a single resident local worker sized for 100% GPU residency on the host hardware (verified empirically via GPU/runtime telemetry), with thinking disabled and capped `num_ctx` (e.g., `~2B–4B` `Q4_K_M`)."* |
| *"Check worker edits carefully."* | *"Prevent `pytest-dev__pytest-10051` blank-line deletion on line 345."* | *"Return a computed compact `unified_diff` from `dispatch_worker` (pre-dispatch snapshot vs. post-dispatch disk bytes) so the Orchestrator inspects exact line mutations immediately."* |
| *"Handle API rate limits."* | *"Sleep 25s when Groq returns 429."* | *"Handle retryable HTTP status codes (`408`, `429`, `5xx`) strictly in the transport adapter, parsing both numeric `Retry-After` seconds and duration headers (`ms`/`s`/`m`/`h`) clamped to the run's wall-clock deadline."* |

### Test 2 — The Swap Test (Anti-Hardcoding Litmus Test)
Before keeping any sentence in a rules file, ask:

> *"If a contributor swaps GPU (`4 GB → 24 GB`), OS (`Windows → Linux`), endpoint (`free tier → paid API`), or model family (`Qwen → DeepSeek / Claude / Gemini`), does this rule still make sense without editing it?"*

- **Yes** → It belongs in `dev_rules/`.
- **No** → Rewrite it around the underlying invariant (keeping concrete values only as non-binding examples or moving the recipe to `docs/` / `docs/worklogs/`).

### Test 3 — Single-Concern, Falsifiable & Evidence-Backed
1. **One subsystem per file:** Name each file after the **software responsibility**, not a temporary deployment setup or experiment (e.g., `tool_rules.md`, `orchestration_rules.md`, `documentation_rules.md` — **not** `hybrid_rules.md` or `experiment23_rules.md`).
2. **No speculative rule files:** Create a new `dev_rules/<subsystem>_rules.md` only when that subsystem actually exists or is actively being designed.
3. **Every rule must be verifiable and earned:** Each rule should enforce a checkable contract or prevent a real failure class observed in engineering or research. Delete generic filler that cannot be verified in code review or tests.

---

## 3. Capability Floors Over Pinned Models

Whenever a subsystem depends on LLM capabilities:
1. Define the **minimum behavioral capabilities** required for each role (what the model must reliably do — e.g., contract-complete decomposition, multi-turn tool discipline, diff diagnosis, single-leaf execution).
2. State the **capability band** (e.g., mid-to-high reasoning tier vs. lightweight quantized local/flash tier).
3. If documenting the current development-to-production model path (such as free cloud dev endpoints → paid drop-in endpoints), present named models and providers inside an explicitly labeled **Illustrative Examples** table and link to `docs/` for live pricing, quotas, and model comparisons.

---

## 4. Honest Status Tagging

A rules file must never mislead an engineer or agent into assuming a planned guardrail is already built in code. Tag individual rules or sections consistently:

- **`[ENFORCED]`** — Implemented in code and covered by automated tests.
- **`[TARGET]`** — Empirically validated requirement or design invariant to implement next (not yet enforced everywhere in code).
- **`[PROCESS]`** — Human, benchmark, or operational gate outside runtime code.

Promote `[TARGET]` → `[ENFORCED]` **only after** implementation and verification pass.

---

## 5. Standard Structure for Every `dev_rules/*_rules.md`

Keep subsystem rule files concise, scannable (ideally `~80–200` lines), and consistently structured:

```markdown
# <Subsystem> Architecture & Guardrails (`dev_rules/<name>_rules.md`)

> - **Status:** Living architectural guardrails (`v0.1`)
> - **Scope:** Exact modules/responsibility governed by this file
> - **Related Specs:** Relative links to `how_to_make_rules.md`, `../AGENTS.md`, and relevant `../docs/`
> - **Tag Legend:** `[ENFORCED]` | `[TARGET]` | `[PROCESS]`

## 1. Architectural Model (How This Subsystem Works)
## 2..N. Focused Guardrail Sections (Contracts, Boundaries, Failure-Class Preventions)
## Final Section. Revision Log (`Version | Date | Summary`)
```

---

## 6. Strict Propose-Only Rule Lifecycle & Update Triggers

### 6.1 The 5-Stage Lifecycle (Recommendation-First — Zero Auto-Edits)
1. **Born (`[TARGET]`):** Proposed when a verified worklog or subsystem design exposes a new invariant passing the 3 tests above.
2. **Enforced (`[ENFORCED]`):** Proposed for promotion (`[TARGET]` → `[ENFORCED]`) once implementation and offline tests verify the contract.
3. **Obeyed (Auto-Invoked):** Coding agents auto-load rules via root `AGENTS.md` (Antigravity/Codex), root `CLAUDE.md` (Claude Code), and subtree tripwires (`hivo/*/AGENTS.md`) before planning or editing.
4. **Amended (Proposal Only):** When real evidence shows a rule is incomplete or blocks a better verified design, **do not edit the rule file** — log a structured proposal backed by `docs/worklogs/` evidence.
5. **Retired (Proposal Only):** When a rule becomes obsolete or superseded, propose deleting it (with a 1-line Revision Log reason) so rule files stay concise (`~80–200` lines) instead of accumulating dead constraints.

### 6.2 Hard Rule Lock (Mandatory for All Coding Agents)
- **Zero Auto-Editing:** During any feature, bugfix, analysis, test, or experiment task, **NEVER modify `dev_rules/*.md`, `AGENTS.md`, `CLAUDE.md`, or `**/AGENTS.md`**.
- **Generic permission is NOT rule authorization:** Instructions like *"fix the bug"*, *"implement feature X"*, or *"update docs"* never authorize changing rules. Only an explicit maintainer instruction targeting a specific rule file in a dedicated rule-review turn authorizes editing `dev_rules/`.
- **Default is silence (`Rule Proposal: None`):** Most PRs and runs require **zero** rule proposals. Never spam proposals on routine fixes, 1-off single-task benchmark failures, Swap-Test violations, or unverified hypotheses.
- **How to submit & close a recommendation:** Record the proposal inside `docs/worklogs/<person>/YYYY-MM-DD_<slug>/REPORT.md` (and populate the `- **Rule Proposal:**` metadata line so `scripts/update_worklog_index.py` surfaces it in `docs/worklogs/INDEX.md`'s **Pending Rule Proposals** review queue), AND echo it in your final reply using the block below. Once reviewed, a maintainer prefixes `[APPLIED ...]`, `[REJECTED ...]`, or `[DEFERRED ...]` on the `Rule Proposal:` line so it leaves the pending queue while preserving full audit history:

```markdown
### Proposed Rule Update (NOT APPLIED)
- **Target:** `dev_rules/<file>.md §<section>`
- **Action:** `ADD` | `PROMOTE [TARGET -> ENFORCED]` | `AMEND` | `RETIRE`
- **Evidence:** `<relative link to worklog REPORT.md / test output>`
- **Proposed Wording (Swap-Test compliant):** <exact proposed rule text or deletion>
- **Status:** PROPOSED — NOT APPLIED (awaiting explicit maintainer review)
```

### 6.3 Exact Update Triggers (When to Propose vs. Leave Rules Alone)

| Propose a Rule Update (`Rule Proposal:` in worklog) | Do **NOT** Propose a Rule Update |
| :--- | :--- |
| A `[TARGET]` rule was just built & verified (`PROMOTE` to `[ENFORCED]`) | One-off bugfix or internal refactor that preserves existing contracts → Tier 1 PR / worklog only |
| Code drifted from an `[ENFORCED]` rule (either fix code or propose rule amendment) | 1-off single-task benchmark failure not yet proven systemic → log in `REPORT.md` only |
| A systemic failure class is proven (`>= 2` independent tasks or clear missing contract, passes Swap Test) | Added/renamed internal modules, fields, or helpers → update living `docs/`, not `dev_rules/` |
| A benchmark/verified design proves an existing rule/threshold is wrong or too restrictive (`AMEND`) | Changed model tags, vendor quotas/prices, or GPU settings → update `docs/HYBRID_MODEL_STRATEGY.md` or `docs/worklogs/` |
| A rule is obsolete or superseded (`RETIRE` / delete) | Unverified hypothesis, temporary debugging workaround, or speculative future subsystem |

### 6.4 Maintainer Pre-Commit Review Checklist (When Applying an Approved Proposal)
Isolate approved rule edits on a dedicated rule-update branch and verify all 6 points:
1. **Swap Test:** No hardcoded developer hardware, OS quirks, live vendor prices/quotas, or specific benchmark ticket IDs.
2. **Single Concern:** Every rule belongs strictly to this file's declared subsystem.
3. **Concrete & Actionable:** Zero vague filler; concrete contracts/mechanisms are clearly stated.
4. **Honest Status:** Every `[ENFORCED]` rule actually exists in current code; unbuilt items are marked `[TARGET]`.
5. **Privacy & Hygiene:** Zero real vendor key prefixes, personal absolute paths, or account identifiers; all Markdown links are relative and resolve cleanly.
6. **Revision Log:** Version and concise summary (with worklog back-link) updated at the bottom of the file.

---

## 7. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial rule-authoring methodology defining the 3-layer repo split, 3-test specificity threshold, capability-floor guidance, honest status tagging, standard template, and pre-commit checklist. |
| `v0.2` | 2026-11-26 | Clarified prescriptive rules vs. descriptive documentation (`dev_rules/` vs. global `docs/` vs. `docs/worklogs/` evidence locker), added the Record-Concrete-Then-Promote workflow, plain-Markdown vs. custom-skills boundary, and linked `tool_rules.md`. |
| `v0.3` | 2026-11-26 | Added explicit Rule-Amendment Proposal workflow for multi-contributor rule updates backed by `docs/worklogs/` evidence. |
| `v0.4` | 2026-11-26 | Hardened into strict Propose-Only Rule Lock (zero auto-edits by coding agents), added full 5-stage lifecycle including Rule Retirement, explicit 5 Update Triggers vs. Do-Not-Update table, exact Proposal Format block, and multi-agent auto-invocation (`AGENTS.md`, `CLAUDE.md`, `hivo/*/AGENTS.md`). |
| `v0.5` | 2026-11-26 | Added explicit Default-is-Silence anti-noise guard (excluding 1-off single-task failures until systemic proof or `>= 2` tasks) and `[APPLIED]`/`[REJECTED]`/`[DEFERRED]` proposal resolution prefixes. |
| `v0.6` | 2026-11-26 | Linked `benchmarking_rules.md` in `Related Specs` and aligned positive historical-archive wording. |
