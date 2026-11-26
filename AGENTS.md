# Mini Hivo development instructions

These repository-wide instructions apply to **all coding agents (`Antigravity`, `Codex`, `Claude Code` via `CLAUDE.md`) and human contributors**. Keep this file as the single repository-level workflow; link supporting rule files instead of duplicating them.

## Mandatory rule routing (read BEFORE planning or editing)

Before planning, diagnosing deeply, or editing files in any area below, you **MUST** read the matching rule file first:

| If your task touches... | MUST read first | Current-state architecture doc |
| :--- | :--- | :--- |
| `hivo/tools/`, `tests/test_tools_*` | [dev_rules/tool_rules.md](dev_rules/tool_rules.md) | [docs/TOOLS_ARCHITECTURE.md](docs/TOOLS_ARCHITECTURE.md) |
| `hivo/providers/`, `hivo/hybrid/`, `scripts/*hybrid*`, `scripts/*swebench*` | [dev_rules/orchestration_rules.md](dev_rules/orchestration_rules.md) | [docs/ORCHESTRATION_ARCHITECTURE.md](docs/ORCHESTRATION_ARCHITECTURE.md), [docs/HYBRID_MODEL_STRATEGY.md](docs/HYBRID_MODEL_STRATEGY.md) |
| `docs/`, `docs/worklogs/`, PRs, findings, experiments | [dev_rules/documentation_rules.md](dev_rules/documentation_rules.md) | [docs/worklogs/INDEX.md](docs/worklogs/INDEX.md) *(newest-first team radar)* |
| `mini.py` or v1 single-model baseline | `AGENTS.md` (this file) | [docs/PROJECT_GOAL.md](docs/PROJECT_GOAL.md), [docs/AGENT_ARCHITECTURE.md](docs/AGENT_ARCHITECTURE.md) |
| `dev_rules/`, `AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md` | **LOCKED (READ-ONLY)** — see Hard Rule Lock below + [dev_rules/how_to_make_rules.md](dev_rules/how_to_make_rules.md) | — |

## Hard Rule Lock — PROPOSE ONLY, NEVER AUTO-EDIT RULES

- **`AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md`, and every file in `dev_rules/` are STRICTLY READ-ONLY during normal feature, bugfix, analysis, test, or experiment work.**
- **NEVER edit, append to, weaken, reword, or delete any rule file automatically.** Generic requests (*"fix this bug"*, *"implement X"*, *"update docs"*, *"clean up"*) do **NOT** authorize editing rule files.
- **Default is silence (`Rule Proposal: None`).** Most PRs and runs need **zero** rule proposals. Never propose a rule for routine bugfixes, 1-off single-task benchmark failures (wait for systemic proof or `>= 2` independent tasks), Swap-Test-failing details, or unverified hypotheses.
- **When you hit a rule trigger** (a `[TARGET]` rule was just implemented, code conflicts with a rule, a new recurring/systemic failure class emerges, or a rule looks obsolete):
  1. Leave all rule files **100% untouched**.
  2. Emit a structured **Proposed Rule Update (NOT APPLIED)** in the contributor's `docs/worklogs/<person>/YYYY-MM-DD_<slug>/REPORT.md` (including the `Rule Proposal:` metadata line) AND in your final response to the user, following [dev_rules/how_to_make_rules.md](dev_rules/how_to_make_rules.md).
  3. Only edit a rule file when the user **explicitly authorizes editing that specific rule file** in a dedicated rule-review turn (preferring a dedicated rule-only branch/PR).

## Workspace, scope and Git

- The authoritative development workspace is the checkout or managed worktree selected for the current task. Determine its root with Git; do not assume a contributor's local folder name. Preserve separate historical workspaces and backups.
- At the start of work inspect the repository root, status, index, branch, tracking, remotes and relevant diff. Preserve unrelated work, including staged publication changes. Do not reset, unstage, overwrite, or silently incorporate another update.
- Verify actual remotes and the user-requested destination before publishing; do not assume `origin` or a contributor-specific remote points to the intended fork. Push only to your verified contributor fork remote — never push to upstream main or develop directly on main.
- Determine the actual branch base and inspect the changes against it. Attribute only changes supported by the diff; distinguish pre-existing architecture, historical reports, and generated state.
- Use a dedicated branch for each coherent update. Inspect the appropriate current upstream base and previous PR state first. If an earlier PR is unmerged, assess dependencies and recommend the correct base before new implementation. Independent updates should start from current upstream main, not an unrelated feature branch. Do not switch branches with unrelated uncommitted changes or mix updates silently.
- Commit, push, open or merge a PR only with explicit user authorization for that update. Authorization from an earlier update does not carry forward. Destructive Git operations, history rewriting, force pushes, merges, rebases and cherry-picks require separate explicit approval. Prefer normal follow-up commits when publishing corrections.

## Required lifecycle

Follow **Observe → Investigate → Fix → Verify → Document → Review → Publish** for every meaningful development update. A meaningful update is one coherent implementation change or related group of fixes; tiny edits and intermediate debugging steps do not each consume a numbered update.

1. **Observe:** capture the original request to Mini Hivo, expected behavior, observed output, actual filesystem/application state, run identity and first stopping boundary. Completion text, process exit 0 and a generated response are not proof of task success.
2. **Investigate:** reproduce safely where practical; inspect implementation, relevant tests, dependencies and retained artifacts. Trace the execution path to the earliest evidenced cause. Separate proven causes from hypotheses and downstream symptoms; state gaps when reproduction or evidence is unavailable.
3. **Fix:** within the user's authorized scope, implement the smallest reliable architectural correction and appropriate regression tests. Do not stop at diagnosis/documentation when implementation is authorized. Preserve authorization, context, impact, grounding and verification boundaries; do not weaken gates, alter unrelated defaults or fabricate fixtures to obtain a pass.
4. **Verify:** define the behavioral oracle before running focused checks. Exercise real affected behavior and related negative cases, inspect actual artifacts/state, compare expected versus actual independently, and run relevant regression checks. Assess compatibility with affected dependencies. See the verification rules below.
5. **Document:** for meaningful changes, investigations, profiling, or experiments (Tier 2), record a small-scoped forensic dossier under `docs/worklogs/<person>/YYYY-MM-DD_<slug>/` following [dev_rules/documentation_rules.md](dev_rules/documentation_rules.md) (`REPORT_TEMPLATE.md`), regenerate [docs/worklogs/INDEX.md](docs/worklogs/INDEX.md) with `python scripts/update_worklog_index.py`, and update shared living `docs/` if subsystem behavior changed. **Never auto-edit `dev_rules/`** — record any suggested rule addition, promotion (`[TARGET]` → `[ENFORCED]`), amendment, or retirement as a **Proposed Rule Update (NOT APPLIED)** in `REPORT.md` (`Rule Proposal:` metadata). Trivial fixes (Tier 1) need only clean commits and the PR template.
6. **Review:** check each claim against the diff, actual test results and evidence; confirm **zero unauthorized edits** to `AGENTS.md`, `CLAUDE.md`, `**/AGENTS.md`, or `dev_rules/`; run `python scripts/update_worklog_index.py --check`, inspect the complete intended file list, privacy, staged diff and whitespace. Prepare a professional PR title/body answering why, what changed, what was fixed, functional evidence, additional passing tests and remaining issues using [`.github/pull_request_template.md`](.github/pull_request_template.md).
7. **Publish:** only after the user authorizes publishing this update, stage explicit approved paths, validate the actual staged content, commit/push to the verified fork and verify the remote ref. Respect separate authorization for PR creation/merge. Report the resulting commit and remaining limits.

## Functional verification requirements

- **Mandatory offline test gate (mirrors CI):** Every code change under `hivo/` or `scripts/` **MUST** add or update offline tests under `tests/` and pass `python scripts/check.py` before claiming done (enforced automatically by `.github/workflows/ci.yml`):
  - Full active v2 offline suite + worklog check: `python scripts/check.py` (strictly offline — never invokes live-API legacy tests).
  - Scoped fast runs while iterating: `python scripts/check.py --tools`, `python scripts/check.py --orchestration`, or `python scripts/check.py --worklogs`.
- **Anti-theater testing discipline:**
  - **Bugfixes must be red-first:** Write or demonstrate a test reproducing the exact failure before applying the fix (or prove the assertion fails against the broken behavior).
  - **Negative/boundary coverage required:** Every new or updated test must assert at least one negative or boundary case (invalid args, error code, rollback, path/fence escape, or timeout) — never happy-path-only or `assert result is not None` smoke assertions.
- A task-specific unit test alone does not establish that a claimed functionality works. Every meaningful fix needs direct functional verification against observable postconditions for its stated scope. For documentation/configuration-only work, use relevant structural, link, integrity or configuration checks and label runtime functional tests not applicable; do not invent a runtime fix or test outcome.
- Label evidence as **unit**, **integration**, **controlled functional**, **live-model end-to-end**, or **regression**. A test may serve multiple roles, but identify its oracle and exactly what is scripted/mocked versus real. Keep functional proof distinct from additional regression passes.
- For file creation, record the exact request, expected relative path and contents, actual creation, byte/content comparison and real-artifact verification. Prefer exact UTF-8 bytes/digests when the source requires literal content. Include negative checks for unauthorized paths, invalid authorization/proof and incorrect output where relevant.
- For other features use an independent behavioral oracle: interact with the real application, inspect actual state transitions and preserved behavior, and show whether the original failing scenario now succeeds. A verifier PASS is only as strong as the behavior its assertions cover.
- Use controlled end-to-end scenarios where appropriate, exercising real authorization, execution and verification boundaries. Scripted model responses can establish controller behavior; they cannot establish live-model reliability. Require a fresh approved live run before claiming live-model completion.
- Inspect test/harness code before broad discovery or experiments. Some tests invoke a live provider: in particular `test_requirement_clarification.RequirementClarificationTests.test_root_brain_prompt_compacts_large_source_side_channel_without_dropping_ids` has historically done so. Do not assume the entire suite is offline. Ask before costly live-model execution; do not rerun costly historical batches automatically.
- Record exact commands, source revision/hashes, dates, case/fixture identities, scope, exit code, assertions, outcomes and evidence locations. Separate historical records from fresh runs. Record failures, errors, interruptions, exclusions and skips without reclassifying them as passes. Do not sum overlapping suites or infer a passing-test count from failure/subtest records when unsupported.
- Historical experiment reports in [the results index](reports/INDEX.md) and curated `evidence/` snapshots are baselines, not current success guarantees; inspect applicability and rerun focused checks when warranted, preserving explicit oracles, denominators, and evidence boundaries as the standard of rigor.
- If functional verification fails or remains unavailable, label the work incomplete/failed/unverified, retain the evidence, explain what is needed, and avoid a successful-fix claim. A controlled-only completion must state its limited scope and any unverified live behavior explicitly.

## Worklog & legacy update documentation

- Active team documentation uses per-contributor chronological dossiers under `docs/worklogs/<person>/YYYY-MM-DD_<slug>/` governed by [dev_rules/documentation_rules.md](dev_rules/documentation_rules.md) and indexed newest-first in [docs/worklogs/INDEX.md](docs/worklogs/INDEX.md) via `python scripts/update_worklog_index.py`. Do not allocate new colliding global `R_UPDATE_NNN.md` or `experimentNN` IDs for parallel team work.
- Legacy `updates/R_UPDATE_*.md` records and `reports/experiment*/` directories are frozen historical archives; treat completed historical records as immutable unless the user explicitly requests an addendum/correction.
- `R_UPDATE_001` remains permanently reserved for the existing immutable private historical audit (retained locally and gitignored); never reuse `001` or publish the private file.
- Use commit hashes only when available. A document cannot know its own future commit hash; identify the tested source revision and mark a containing commit pending when necessary. Never fabricate commands, before-code excerpts, results, counts or provenance.

## Evidence preservation and publication

- Preserve original logs, experiment workspaces, manifests and prior reports. Use a fresh output directory for each new run; never overwrite a historical cohort or regenerate an old result as though it were original. Do not modify evidence to make a test pass.
- Keep raw transcripts, SQLite databases/sidecars, runtime caches, preflight/experiment markers and private local machine details out of new public artifacts. Check existing scoped ignore rules; do not blanket-stage ignored/raw directories or use broad `git add .`.
- Publish selected sanitized derivatives when needed, preserving originals privately. Use relative repository links in update documents and runnable root-relative reproduction commands, never personal absolute paths, credentials or unnecessary host inventories. Review task/request content as well as paths for private data.
- Distinguish original source SHA-256 from sanitized derivative SHA-256. When hashes matter, specify canonical bytes/line endings with appropriately scoped attributes and verify hashes against actual staged Git blobs, not only working-tree files. Sanitized contract/receipt copies are evidence, not reusable runtime authorization.
- Before an authorized commit/push, inspect staged paths, run `git diff --cached --check`, verify preserved originals and the publication manifest, scan staged content for credentials/private metadata, and confirm no unrelated implementation changes. Investigate failures before publishing; never claim a failed gate passed.
- Removing tracking does not erase previously published history. Preserve originals on disk during approved index-only cleanup. Do not rewrite history or claim historical erasure without a separately authorized and reviewed procedure.

## Completion report

State what changed, why, which functionality was directly verified, additional regression outcomes, failures/untested areas, evidence and update-document paths, and the proposed PR title/body. State whether files are uncommitted or published. If blocked, identify the exact boundary and remaining evidence/approval without presenting the update as successful.
