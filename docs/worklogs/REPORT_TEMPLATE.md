# <Short Descriptive Title>

> **Template instructions (DELETE THIS BLOCKQUOTE AFTER COPYING):**
> 1. Copy into `docs/worklogs/<person>/YYYY-MM-DD_<short-slug>/REPORT.md`.
> 2. Keep the **Required Core** and **only the Modular Blocks matching your `Type`** (delete unused blocks — never leave empty `"N/A"` tables).
> 3. After saving, run `python scripts/update_worklog_index.py` to refresh `docs/worklogs/INDEX.md` and validate links/hygiene.
> 4. Policy reference: `dev_rules/documentation_rules.md`.

---

<!-- ====================================================================== -->
<!-- REQUIRED CORE (KEEP IN EVERY REPORT.md)                                -->
<!-- ====================================================================== -->

## Metadata

- **Date:** `<YYYY-MM-DD>`
- **Author:** `<name>`
- **Type:** `<analysis | test | change | experiment>`
- **Subsystem:** `<e.g., hivo/tools, hivo/providers, hivo/hybrid, verification, benchmark, docs>`
- **Branch & Base Commit:** `<branch-name>` (base `<short-sha>`)
- **Status:** `<verified | completed-analysis | partial | blocked | in-progress>`
- **Builds On:** `<Relative link to prior dossier you are continuing, or None>`
- **Next / Open Issue:** `<1-line open problem someone can pick up next, or None>`
- **Rule Proposal:** `<1-line summary e.g. "PROMOTE orchestration_rules.md §6.2 unified_diff -> ENFORCED", or None (NEVER auto-edit dev_rules/)>`

## TL;DR

<3–5 concise sentences: what you investigated/changed/ran, the concrete headline finding or verified outcome, and the exact scope boundary (what IS proven vs. NOT proven). The first sentence appears in `docs/worklogs/INDEX.md`.>

---

<!-- ====================================================================== -->
<!-- MODULAR BLOCK A — FOR Type: analysis (DELETE IF NOT APPLICABLE)        -->
<!-- ====================================================================== -->

## Question & Inputs Inspected

- **Question / Trigger:** <Exact bug, design question, or log anomaly investigated.>
- **Sources Inspected:** <Exact repo-relative files/lines, commits, logs, or external references inspected.>

## Detailed Findings & Root Cause

<Trace execution paths, state transitions, or trade-offs precisely. Separate proven causes from hypotheses.>

| Finding | Classification | Concrete Evidence (file/line/trace) | Open Uncertainty |
| :--- | :--- | :--- | :--- |
| <Finding> | `Proven cause` / `Observation` / `Hypothesis` | <Relative path + line or sanitized excerpt> | <None or gap> |

## Recommended Next Actions

1. <Concrete, scoped follow-up action.>

---

<!-- ====================================================================== -->
<!-- MODULAR BLOCK B — FOR Type: test OR experiment (DELETE IF NOT NEEDED)  -->
<!-- ====================================================================== -->

## Setup & Environment

- **Code Revision:** `<commit-sha>` *(plus note if uncommitted changes were tested)*
- **Hardware / Runtime:** `<OS, Python version, GPU/VRAM if relevant, Docker/Ollama versions>`
- **Model(s) / Provider(s):** `<Exact model tags, quantization, context cap, reasoning flags — or "Offline / zero LLM calls">`
- **Protocol:** <Link to sibling `PROTOCOL.md` for `Type: experiment`, or list fixed inputs/seeds here for `Type: test`.>

---

<!-- ====================================================================== -->
<!-- MODULAR BLOCK C — FOR Type: change (OR experiment WITH CODE FIXES)     -->
<!-- ====================================================================== -->

## Problem & Root Cause

<Exact failing scenario or missing capability, earliest observed boundary, and proven root cause.>

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| `<relative/path.py::symbol>` | <Prior behavior or `Absent`> | <Exact edit/addition> | <Observed behavior> | <Test or check> |

---

<!-- ====================================================================== -->
<!-- MODULAR BLOCK D — FOR Type: test, change, OR experiment                -->
<!-- ====================================================================== -->

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| `<suite or scenario>` | `unit` / `integration` / `controlled functional` / `live E2E` / `regression` | <What is real vs. scripted> | `<root-relative command>` | `<e.g., 16/16 pass, 0 skip>` | `0` |

---

<!-- ====================================================================== -->
<!-- MODULAR BLOCK E — FOR Type: experiment (DELETE IF NOT APPLICABLE)      -->
<!-- ====================================================================== -->

## Experiment Results & Intermediate Defects Caught

| Case / Instance | Baseline Oracle | Candidate Oracle | Outcome | Key Metrics (Tokens / Latency / Turns) | Key Finding |
| :--- | :--- | :--- | :---: | :--- | :--- |
| `<case_id>` | `<e.g., F2P=0/1, P2P=6/6>` | `<e.g., F2P=1/1, P2P=6/6>` | `PASS` / `FAIL` / `BLOCKED` | `<metrics>` | `<factual cause>` |

### Intermediate Harness / Environment Defects Caught During Runs
1. <Document every aborted attempt or harness bug discovered and fixed transparently — never drop denominators.>

---

<!-- ====================================================================== -->
<!-- REQUIRED CORE TAIL (KEEP IN EVERY REPORT.md)                           -->
<!-- ====================================================================== -->

## Limitations & Known Gaps

- <Exact unverified areas, small sample size ($N < 30$), quota/environment blocks, or remaining failure modes.>

## Artifacts, Reproduction & Rule Proposals

- **Sibling Artifacts:** <Links to `PROTOCOL.md`, `results.json`, `provenance.json`, `patches/`, `artifacts/` — or "None".>
- **Living Docs Updated (`docs/`):** <Relative links or "None".>
- **Proposed Rule Updates (NOT APPLIED — Pending Maintainer Review):** <If none, write "None". Otherwise fill the block below — NEVER edit `dev_rules/*.md` directly during feature/experiment work.>

```markdown
<!-- Delete this block if no rule update is proposed -->
- Target: dev_rules/<file>.md §<section>
- Action: ADD | PROMOTE [TARGET -> ENFORCED] | AMEND | RETIRE
- Evidence: <this report / test output>
- Proposed Wording (Swap-Test compliant): <exact proposed change>
- Status: PROPOSED — NOT APPLIED (awaiting explicit maintainer review)
```

- **Containing PR / Commit:** `<PR link / commit SHA or pending>`

```powershell
# Exact root-relative reproduction commands (no personal absolute paths or secrets)
```
