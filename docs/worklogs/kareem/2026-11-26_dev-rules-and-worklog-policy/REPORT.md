# Modular `dev_rules/`, Living Subsystem Docs & 10-Person Worklog Evidence Locker

## Metadata

- **Date:** `2026-11-26`
- **Author:** `kareem`
- **Type:** `change`
- **Subsystem:** `dev_rules / docs / worklogs`
- **Branch & Base Commit:** `docs/rules-and-worklog-policy` (base `2e396fa`)
- **Status:** `verified`
- **Builds On:** None
- **Next / Open Issue:** Return computed `unified_diff` in `dispatch_worker` (`hivo/hybrid/runner.py`) to catch silent light-worker edit defects immediately
- **Rule Proposal:** None

## TL;DR

Separated Mini Hivo's development governance into three layers — prescriptive subsystem rules (`dev_rules/`), shared living architecture docs (`docs/`), and a collision-free 10-person worklog evidence locker (`docs/worklogs/` with per-contributor Tier 1 `LOG.md` quick logs and Tier 2 dossiers) indexed newest-first by `scripts/update_worklog_index.py`. Added multi-agent auto-invocation (`AGENTS.md`, `CLAUDE.md`, `hivo/*/AGENTS.md`), a strict Propose-Only Hard Rule Lock (default silence + `Pending Rule Proposals` queue), a unified offline test/PR-gate runner (`scripts/check.py`), GitHub Actions CI (`.github/workflows/ci.yml`), `.github/CODEOWNERS`, and two companion PDFs (`docs/TEAM_GUIDEBOOK.pdf` and `docs/TECHNICAL_METHODOLOGY.pdf`), with zero runtime changes to `hivo/` or `mini.py`. Verified offline via `python scripts/check.py -v` (`64` tests ran: `62` passed, `2` Windows-symlink skips, `0` failures), `--ci-diff` gate checks, link/privacy scans, visual PDF inspection, and `git diff --check`.

---

## Problem & Root Cause

1. **Prescriptive rules and descriptive documentation were conflated:** `docs/PROJECT_GOAL.md` and `docs/AGENT_ARCHITECTURE.md` locked v1 `SingleModelPolicy` constraints onto the whole repo while `tool_rules.md` (`249` lines) hardcoded `27B`/`2B`/`Qwen` labels and mixed `v0.3–v0.5` implementation changelogs into design guardrails.
2. **Global sequential update/experiment numbering collided under parallel team work:** Both `reports/experiment18..19` and `updates/R_UPDATE_010.md` were independently allocated on parallel branches, and searching one contributor's findings required hunting across `updates/`, `reports/`, and `evidence/`.
3. **Rigid monolithic templates discouraged everyday traceability:** Forcing a 13-section update form onto pure forensic analyses or profiling runs created boilerplate friction while manual index editing risked merge conflicts across a 10-person team.

## Exact Changes Made

| File / Symbol | Before | Change | After | Verification |
| :--- | :--- | :--- | :--- | :--- |
| [`dev_rules/how_to_make_rules.md`](../../../../dev_rules/how_to_make_rules.md) | Absent | Added rule-authoring meta-policy (3-part split, Mechanism-vs-Instance, Swap Test, capability floors, status tags, rule-amendment workflow) | Governs all `dev_rules/*_rules.md` authoring | Link, hygiene & checklist audit |
| [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md) | Absent | Added 10-person documentation & worklog policy (2-tier Git/PR vs. worklog cutoff, Unified Core + Modular Blocks, `Builds On` continuation, JSON schemas, privacy) | Single source of truth for team documentation | Link & hygiene audit |
| [`dev_rules/tool_rules.md`](../../../../dev_rules/tool_rules.md) | Root `tool_rules.md` (`249` lines, `27` hardcoded model-size lines, stale `ToolContext`/5-key envelope) | Moved via `git mv`; generalized to capability tiers; added `[ENFORCED]`/`[TARGET]`/`[PROCESS]` tags; reconciled promoted tools & 6-key envelope; moved implementation inventory to `docs/TOOLS_ARCHITECTURE.md` | Crisp `116`-line Swap-Test-compliant tool rules | Link, Swap-Test & hygiene audit |
| [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md) | Absent | Added model-, vendor-, and hardware-agnostic orchestration guardrails & Orchestrator/Worker capability floors (grounded in asymmetric decomposition scaling & live hybrid runs) | Governs `hivo/providers/` & `hivo/hybrid/` cleanly | Verified `[ENFORCED]` tags against code |
| [`AGENTS.md`](../../../../AGENTS.md), [`CLAUDE.md`](../../../../CLAUDE.md), `hivo/*/AGENTS.md` | Pointed only to v1 single-model charters; mandated `updates/R_UPDATE_NNN.md`; no Claude Code entrypoint or subtree tripwires | Added Mandatory Rule Routing table + Hard Propose-Only Rule Lock; added root `CLAUDE.md` (`@AGENTS.md`) + thin `hivo/{tools,providers,hybrid}/AGENTS.md` tripwires; reconciled lifecycle & worklog index workflow | Auto-invoked across Antigravity, Codex & Claude Code; rules read-only during normal work | Link, privacy & diff check |
| [`docs/TOOLS_ARCHITECTURE.md`](../../../../docs/TOOLS_ARCHITECTURE.md), [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../../docs/ORCHESTRATION_ARCHITECTURE.md) | Absent (details buried in `tool_rules.md` or missing) | Added current-state module inventories, dataclasses, runtime flows, and offline test commands for `hivo/tools/`, `hivo/providers/`, and `hivo/hybrid/` | Clean global living architecture docs by subsystem | Verified against `hivo/tools/__init__.py`, `base.py`, `registry.py`, `hivo/providers/__init__.py`, `hivo/hybrid/__init__.py` |
| [`docs/HYBRID_MODEL_STRATEGY.md`](../../../../docs/HYBRID_MODEL_STRATEGY.md) | Duplicated adapter invariants & used future-tense Phase 1–4 roadmap | Scoped strictly to 4 GB VRAM hardware sizing, free-dev vs. paid-target provider tables, deferred research, and current milestone status; linked `ORCHESTRATION_ARCHITECTURE.md` | Zero redundancy with `ORCHESTRATION_ARCHITECTURE.md` | Link & hygiene audit |
| [`docs/PROJECT_GOAL.md`](../../../../docs/PROJECT_GOAL.md), [`docs/AGENT_ARCHITECTURE.md`](../../../../docs/AGENT_ARCHITECTURE.md) | Presented `SingleModelPolicy` without noting active v2 track | Added 3-line Architecture Scope Note banner at top of each file (zero edits to existing v1 body) | Clear v1 baseline vs. v2 active track distinction | Link & diff check |
| [`docs/worklogs/`](../../INDEX.md) (`INDEX.md`, templates, 10 contributor folders + `LOG.md`) | Absent | Created unified templates, 10 lowercase POSIX contributor folders (`.gitkeep` + Tier 1 `LOG.md` quick logs), and auto-generated 4-view `INDEX.md` | Ready-to-use 10-person evidence locker tracking both Tier 1 & Tier 2 | `scripts/update_worklog_index.py --check` |
| [`scripts/update_worklog_index.py`](../../../../scripts/update_worklog_index.py), [`tests/test_worklog_index.py`](../../../../tests/test_worklog_index.py) | Absent | Added stdlib worklog index generator + `--check` validator, `Recent Tier 1 Fixes` aggregation from per-person `LOG.md`, `Pending Rule Proposals` queue with `[APPLIED]`/`[REJECTED]`/`[DEFERRED]` clearing, and offline unit tests | Eliminates manual `INDEX.md` merge conflicts and surfaces accumulated Tier 1 + Tier 2 work cleanly | `tests/test_worklog_index.py` (`7/7` pass) + live `--check` |
| [`scripts/check.py`](../../../../scripts/check.py), [`tests/test_check_runner.py`](../../../../tests/test_check_runner.py) | Absent | Added unified offline v2 test + worklog runner and testable `--ci-diff` PR gate checker (Hard Rule Lock + code-requires-tests) | Single local/CI command (`python scripts/check.py`) avoiding live-API legacy tests | `tests/test_check_runner.py` (`4/4` pass) + full `scripts/check.py -v` |
| [`.github/workflows/ci.yml`](../../../../.github/workflows/ci.yml), [`.github/CODEOWNERS`](../../../../.github/CODEOWNERS), [`.github/pull_request_template.md`](../../../../.github/pull_request_template.md), [`.gitattributes`](../../../../.gitattributes) | Absent / partial attributes | Added offline GitHub Actions CI + PR diff gates, maintainer `CODEOWNERS` for rules/CI, updated PR template, and canonical LF attributes | Platform-enforced testing, Hard Rule Lock, and cross-OS LF consistency | `scripts/check.py --ci-diff`, YAML parse & `git diff --check` |
| [`docs/TEAM_GUIDEBOOK.pdf`](../../../../docs/TEAM_GUIDEBOOK.pdf), [`docs/TECHNICAL_METHODOLOGY.pdf`](../../../../docs/TECHNICAL_METHODOLOGY.pdf) | Absent | Built two companion A4 PDFs: an approachable 6-page indie-zine Team Guidebook (parallel lanes, Autopilot vs. Human, steal-these prompts, 8 CI traps) and a detailed 7-page Technical Methodology spec (scaling laws, 5 contracts, CI/Rule Lock, worklog schemas) | Practical daily guide + deep technical reference | `diagram-design` checks (`0` findings) + PNG visual inspection of all 13 pages |

---

## Verification & Checks

| Check / Suite | Verification Class | Mocked vs. Real | Exact Command | Outcome (Pass / Fail / Skip) | Exit |
| :--- | :--- | :--- | :--- | :--- | :---: |
| Unified offline check runner (all 12 active v2 suites + live `INDEX.md --check`) | `unit` + `integration` + `regression` | Real scripts & offline suites (zero LLM calls) | `python scripts/check.py -v` | `64` ran (`62` passed, `0` failed, `2` skipped on Windows symlink perms) + `INDEX.md` `[OK]` | `0` |
| PR diff gate negative & positive checks (`evaluate_pr_diff_gates`) | `unit` + `controlled functional` | Scripted PR file lists in `test_check_runner.py` + real uncommitted changed-file list | `python -m unittest tests.test_check_runner -v` + direct gate audit on current branch files | `4/4` unit tests pass; current branch correctly flagged on Hard Rule Lock unless `allow_rule_edits=True` | `0` |
| Cross-repo Markdown links, YAML/JSON validity, secret/path hygiene & whitespace | `structural` | Real workspace files + `git diff --check` | `git diff --check` + Python link/YAML/JSON/privacy audit | `0` broken links, valid JSON/YAML, `0` secret/path leaks, `0` whitespace errors | `0` |
| Companion PDFs (`TEAM_GUIDEBOOK.pdf` 6p + `TECHNICAL_METHODOLOGY.pdf` 7p) visual inspection | `visual / structural` | Real rendered PDFs + 13 PNG page previews | `build_fun_guidebook.py` + `build_two_pdfs.py` + `render_both_pdfs.py` + visual inspection of every page | Exact page counts (`6/6` + `7/7`), `0` diagram findings, all 13 A4 pages visually verified | `0` |

---

## Limitations & Known Gaps

- Runtime agent execution (`mini.py`, `hivo/tools/`, `hivo/providers/`, `hivo/hybrid/`) was intentionally untouched; live-model end-to-end tests are **not applicable** to this governance/documentation update.
- `updates/R_UPDATE_010.md` and `updates/R_UPDATE_011.md` retain historical links to root `tool_rules.md` because completed legacy update records are preserved as immutable history.
- `[TARGET]` orchestration items documented in `dev_rules/orchestration_rules.md` (computed `unified_diff` in `dispatch_worker`, $\kappa \ge 0.90$ contract completeness, DCVG) remain to be implemented in follow-up feature branches.

## Artifacts, Reproduction & Promoted Updates

- **Sibling Artifacts:** [`provenance.json`](provenance.json)
- **Living Docs Updated (`docs/`):** [`docs/TOOLS_ARCHITECTURE.md`](../../../../docs/TOOLS_ARCHITECTURE.md), [`docs/ORCHESTRATION_ARCHITECTURE.md`](../../../../docs/ORCHESTRATION_ARCHITECTURE.md), [`docs/HYBRID_MODEL_STRATEGY.md`](../../../../docs/HYBRID_MODEL_STRATEGY.md), [`docs/PROJECT_GOAL.md`](../../../../docs/PROJECT_GOAL.md), [`docs/AGENT_ARCHITECTURE.md`](../../../../docs/AGENT_ARCHITECTURE.md)
- **Rules Promoted (`dev_rules/`):** [`dev_rules/how_to_make_rules.md`](../../../../dev_rules/how_to_make_rules.md), [`dev_rules/documentation_rules.md`](../../../../dev_rules/documentation_rules.md), [`dev_rules/tool_rules.md`](../../../../dev_rules/tool_rules.md), [`dev_rules/orchestration_rules.md`](../../../../dev_rules/orchestration_rules.md)
- **Containing PR / Commit:** Pending (uncommitted on branch `docs/rules-and-worklog-policy`)

```powershell
python scripts/check.py -v
git diff --check
# After committing on this governance branch:
python scripts/check.py --ci-diff 2e396fa --allow-rule-edits
```
