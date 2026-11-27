# Mini Hivo — Graduation Project Goal & Architectural North Star

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE):** Mini Hivo is **v2 only**. This document is preserved strictly as historical record of the retired **v1 single-local-model baseline** (`mini.py` / `SingleModelPolicy`), which is no longer used or maintained. For the active v2 project, see [`../README.md`](../README.md), [`PROJECT_STATUS.md`](PROJECT_STATUS.md), [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md), [`TOOLS_ARCHITECTURE.md`](TOOLS_ARCHITECTURE.md), [`HYBRID_MODEL_STRATEGY.md`](HYBRID_MODEL_STRATEGY.md), and [`../dev_rules/orchestration_rules.md`](../dev_rules/orchestration_rules.md).

**Role of this document:** Authoritative graduation-project charter defining Mini Hivo's core problem statement, engineering thesis, architectural pillars, deliverable backend surfaces, and scientific measurement boundaries. For role-by-role execution mechanics, see [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md); for the formal AGISS synthesis, WDDM VRAM-cliff laws, and live weak-model evaluation, see [RESEARCH_PAPER.md](RESEARCH_PAPER.md); for current capability checkpoints and empirical status, see [PROJECT_STATUS.md](PROJECT_STATUS.md).

---

## 1. The Core Problem & Thesis

### Why Single-Shot Small Local Models Fail on Real Software Tasks

Running software generation locally on consumer hardware requires small, quantized open-weight models (4B–8B parameters, such as `gemma4:e4b`). When driven as a conventional single-shot prompt or unconstrained chat loop, these models systematically fail on non-trivial software engineering tasks in two distinct ways:

1. **Mid-Run Execution Stall & Protocol Collapse:**
   Small models operate under tight effective attention and KV-cache budgets. As tool history, stack traces, and repository text accumulate in one conversation, the model loses track of line anchors, omits required tool-schema fields (for example, invoking `edit_file_range` without `start_line`), edits stale paths after a rollback, or collides with parser/module-mode assumptions (such as ES-module `<script type="module">` checked as CommonJS). Naive controllers misinterpret these harness and protocol failures as intrinsic task difficulty (`TASK_TOO_BROAD`), triggering runaway recursive splitting or premature termination without delivering a working artifact (see [MANUAL_RUN_ANALYSIS.md](MANUAL_RUN_ANALYSIS.md)).
2. **Shallow "Bare-Minimum Draft" Completion:**
   Even when a single-shot small model writes syntactically valid files and exits cleanly, it frequently produces a superficial stub — an HTML shell with an empty or unrendered `<canvas>`, a timer whose controls do not advance or pause state, a 3D game without working collision/restart loops, or a CLI script that handles one nominal example while crashing on boundary inputs. Self-authored prose (`"Verification successful"`) or weak exit-code checks falsely pass these drafts despite broken runtime, visual, and interactive behavior.

### Mini Hivo's North Star Thesis

> **Mini Hivo proves and delivers an Architecture-First Swarm & Recursive Coding Engine in which disciplined multi-role orchestration, provenance-locked contracts, evidence-licensed recovery, domain quality rubrics, and independent deterministic/browser verification amplify a single pinned weak local model to produce genuinely high-quality, end-to-end verified software — without cross-model fallback, silent scope expansion, or fake verification passes.**

Rather than masking small-model weaknesses by escalating hard steps to a frontier cloud API, Mini Hivo treats **controller architecture** as the primary lever of software quality and reliability. Every planning, building, challenging, falsifying, and repairing turn runs on the exact same pinned model, isolating what structured systems engineering can extract from constrained local intelligence.

---

## 2. Core Architectural Pillars

### Pillar 1 — Single-Model-Per-Run Attribution (`SingleModelPolicy`)

Implemented in [`../hivo/model_policy.py`](../hivo/model_policy.py), `SingleModelPolicy` pins all 17 model-backed roles in a run (`requirement_extractor`, `clarifier`, `specifier`, `recon_agent`, `task_brain_compiler`, `impact_planner`, `impact_challenger`, `impact_plan_reviser`, `coordinator`, `mission_compiler`, `builder`, `challenger`, `predictor`, `falsifier`, `quality`, `repairer`, and `visual`) to one declared model (`gemma4:e4b` by default, or an explicitly pinned run-wide alternative via `--model`).

- **No hidden frontier fallback:** Cross-model routing and silent cloud escalation are disabled so every quality gain or failure boundary is scientifically attributable to the Swarm/Recursive harness.
- **VRAM-safe dual-boundary budgets & role-conditioned `min_p` decoding ([`../hivo/hyperparams.py`](../hivo/hyperparams.py)):** Pre-preflight idle-model VRAM eviction (`keep_alive: 0`), dual-boundary `num_ctx` selection (`10240` 100%-GPU ceiling when prompt + completion fit, stepping to `12288` only for high-headroom single-file synthesis), and role/epoch-conditioned `min_p` decoding (`--decoding-policy {adaptive,fixed}`: `T=0.05` analytical, `T=0.08` cold Epoch-0 `Builder`, `T=0.20..0.48` + `+7919` seed stride on repair/stagnation) prevent WDDM KV-cache CPU-spill cliffs (`24.5x` collapse) and stochastic tail drift (see [RESEARCH_PAPER.md](RESEARCH_PAPER.md)).

### Pillar 2 — Provenance-Locked Requirements & Bounded Brain Projections

Small models drop constraints when long prompts are paraphrased across stages. Mini Hivo separates authoritative user intent from working projections:

- **Immutable `SourceRequirementLedger` ([`../hivo/requirements.py`](../hivo/requirements.py)):** Extracts stable `REQ-*` identifiers with explicit provenance (`USER_STATED`, `USER_CONFIRMED`, `DERIVED`, `VERIFIED`) and deterministic `MAPPED`/`UNMAPPED` coverage accounting so weak-model specification never silently discards a source obligation.
- **Hybrid Reconnaissance & Semantic World Model ([`../hivo/project_understanding.py`](../hivo/project_understanding.py), [`../hivo/repo_intelligence.py`](../hivo/repo_intelligence.py), [`../hivo/project_world_model.py`](../hivo/project_world_model.py)):** Existing-project tasks run deterministic metadata, lexical, symbol, and graph discovery first, recording hash-anchored `REPO-*` observations (`DIRECT_OBSERVATION`) without mutating files.
- **Project Brain, Anchor-Pinned Context & Assume-Guarantee Sibling Projections ([`../hivo/reentry.py`](../hivo/reentry.py), [`../hivo/context.py`](../hivo/context.py), [`../hivo/assume_guarantee.py`](../hivo/assume_guarantee.py)):** Durable verified project facts live in a SQLite-backed **Project Brain** (`.hivo/memory.sqlite3`), reconciled read-only on re-entry against current file hashes. Anchor-pinned tool-first context compaction (`protected_anchor = 1`) preserves the root user specification even after truncated `19 KB` tool calls. On multi-file splits, `partition_disjoint_child_ownership` enforces disjoint child file ownership ($O_i \cap O_j = \emptyset$) across a 3-tier producer-to-consumer DAG, while `extract_file_certificate` and `verify_compositional_certificates` pass zero-model static interface guarantees (`<= 1,200` chars) to downstream siblings and enforce cross-file compatibility at write time and parent integration preflight.

### Pillar 3 — Pre-Mutation Impact Planning, Adversarial Challenge & Transactional Safety

Before code is touched in an existing repository, Mini Hivo enforces explicit authority and blast-radius control:

- **Impact Map & Adversarial Challenge ([`../hivo/impact_planning.py`](../hivo/impact_planning.py)):** `ImpactPlanner` assigns surfaces to bounded dispositions (`MUST_CHANGE`, `INTERFACE_REUSE`, `TEST_CHANGE`, `PRESERVATION_ONLY`, `VERIFY_ONLY`), `ImpactChallenger` audits scope, minimality, `do_not_touch` boundaries, and missing test coverage, and deterministic reconciliation compiles a Minimal Effective Change Plan gated on explicit operator approval.
- **Immutable Execution Contracts ([`../hivo/execution_contracts.py`](../hivo/execution_contracts.py), [`../hivo/approval_bound_execution.py`](../hivo/approval_bound_execution.py), [`../hivo/pre_mutation_impact.py`](../hivo/pre_mutation_impact.py)):** Approved plans compile with zero model calls into hash-verified DAG contracts separating `allowed_mutation_paths` from `allowed_inspection_paths` and enforcing preservation invariants before and after mutation.
- **Transactional Workspace & Grounded Edits ([`../mini.py`](../mini.py), [`../hivo/mutation_grounding.py`](../hivo/mutation_grounding.py)):** Every leaf executes inside an atomic file transaction. Edits are anchored to observed file hashes and line spans, syntax-checked prior to write, and rolled back completely if verification or budget gates fail.

### Pillar 4 — Evidence-Licensed Decomposition & Recovery (*Before You Split*)

Grounded in the project's research formulation ([RESEARCH_DIRECTION.md](RESEARCH_DIRECTION.md)) and implemented through [`../hivo/evidence_licensed_gate.py`](../hivo/evidence_licensed_gate.py), Mini Hivo refuses to equate tool-protocol friction with model incapacity:

- **Attributable Failure Separation:** Controller-observed tool receipts distinguish malformed tool schemas, omitted range-edit parameters, stale file-hash anchors, and module/syntax-verifier mismatches from genuine implementation breadth.
- **Same-Authority Bounded Correction:** Before licensing a capability-based split (`TASK_TOO_BROAD`) or capability-floor stop, an attributable interaction or harness refusal receives **one bounded, executed correction within unchanged scope and budget**, followed by a fresh progress observation.
- **Unconditional Safety Stops:** User cancellation, host/provider outages, exhausted budgets, missing approvals/clarifications, and legitimate permission or scope denials halt immediately — the gate never routes around safety boundaries or fabricates missing arguments.

### Pillar 5 — Quality-Amplifying Domain Rubrics & Independent Oracles

To overcome the "bare-minimum draft" failure mode, Mini Hivo pairs proactive quality rubrics with independent multi-layer verification:

- **Domain Playbooks & Quality Rubrics ([`../hivo/playbooks.py`](../hivo/playbooks.py), [`../hivo/quality_rubric.py`](../hivo/quality_rubric.py)):** Project profiles (`web_game`, `web_app`, `api`, `cli`, `library`, `data`, `documentation`) inject explicit structural, state-flow, edge-case, and UX completeness criteria into mission compilation and acceptance evaluation.
- **Independent Deterministic & Headless-Browser Oracles ([`../hivo/verification.py`](../hivo/verification.py), [`../hivo/verification_routing.py`](../hivo/verification_routing.py), [`../hivo/browser_checks.py`](../hivo/browser_checks.py), [`../hivo/python_checks.py`](../hivo/python_checks.py)):**
  - *Python & Node execution:* Subprocess CLI assertions (`expected_stdout`, `expected_exit_code`, invalid-argument rejection), public function behavioral checks, ES-module/CommonJS-aware syntax gates, and unit test suites.
  - *Headless Chromium / Playwright / WebGL & Perceptual Workmanship Oracles:* Real HTTP-served browser execution verifying document title, non-zero `<canvas>` geometry (`>= 64x64`), pre-start inner-playfield luminance (`blank_initial_canvas`, $\sigma_Y \ge 0.75$ before `start()`), pairwise DOM bounding-box HUD anti-overlap (`hud_layout_overlap`, `hudOverlapCount == 0`), zero console/page/network errors, responsive mobile viewports (`390x844` overflow and word-boundary-scoped touch-control checks), deterministic clock progression for timers (`start`/`pause`/`reset`/phase transitions/`localStorage` reload persistence), and live `window.AGENT_GAME` adapters (`getState()`, `start()`, `restart()`, `move()`, `forceCollision()`, `forceCollect()`, `forceWin()`).
- **Adversarial `Falsifier` (6-Angle QA) & Evidence-Directed `Repairer` ([`../mini.py`](../mini.py), [`../hivo/recovery.py`](../hivo/recovery.py)):** After the `Builder` claims completion, a read-only `Falsifier` guided by `build_six_angle_qa_checklist` actively probes functional, interface, resilience, visual/HUD, and single-RAF reset invariants to break the candidate. If deterministic checks fail on an `IMPLEMENTATION_ERROR`, a scoped `Repairer` repairs only evidenced defects (preserving verified sibling immutability while allowing `coherent_rewrite` solely on a child's own unverified greenfield draft), followed by fresh verification from scratch.

---

## 3. Deliverable Backend Scope vs. Research Measurement Boundary

Mini Hivo is engineered simultaneously as a **usable graduation-project backend software system** and a **rigorous scientific instrument** for studying small-model coding orchestration. Keeping both honest requires an explicit boundary between what the backend delivers operationally and what empirical experiments have measured to date.

### Operational Backend Surfaces Delivered Today

1. **Interactive Session-Persistent TUI (`mini.py`):**
   A calm Rich/`prompt_toolkit` terminal interface ([`../hivo/terminal_ui.py`](../hivo/terminal_ui.py), [`../hivo/sessions.py`](../hivo/sessions.py), [TERMINAL_SESSIONS.md](TERMINAL_SESSIONS.md)) supporting automatic numbered workspaces (`list/project-N`), persistent named sessions across restarts (`/new`, `/sessions`, `/switch`, `/resume`, `/history`, `/logs`), native arrow-key clarification and plan-approval dialogs, and complete local SQLite/JSONL telemetry.
2. **Non-Interactive Batch & Evaluation CLI (`mini.py --prompt-file ...`):**
   Scriptable batch execution for CI, reproducible experiments, and external orchestrators with strict exit codes (`0` for verified completion, `1` for task failure or block, `2` for setup/preflight error), shared task budgets (`--max-model-calls`, `--max-tool-calls`, `--max-elapsed-seconds`), explicit ablation policy flags, and machine-readable deliverable reports via `--json-report` ([`../hivo/deliverable_report.py`](../hivo/deliverable_report.py)).

   ```powershell
   .\.venv\Scripts\python.exe mini.py --mode recursive --workspace .\cases\trial --prompt-file .\cases\prompt.txt --decoding-policy adaptive --json-report .\cases\deliverable-report.json --no-bootstrap
   ```

3. **Headless Callable Job Service API (`hivo.job_service.JobService`):**
   Version 1 of an internal host-composed Python backend ([`../hivo/job_service.py`](../hivo/job_service.py), [`../hivo/job_runtime.py`](../hivo/job_runtime.py), [`../hivo/job_store.py`](../hivo/job_store.py), [`../hivo/job_result.py`](../hivo/job_result.py)) decoupled from terminal I/O. A host submits registered Git repositories with full base commit SHA and idempotency keys, polls structured status/events (`queued`, `running`, `waiting_clarification`, `waiting_approval`, `verified`, `failed`, `blocked`), supplies authenticated operator decisions bound to exact plan hashes, and executes candidate code plus caller-owned `independent_checker` oracles inside isolated Linux Docker containers on disposable workspace copies. Only `verified` jobs emit a patch diff and SHA-256 digests; the original repository is never mutated directly.

### Scientific Measurement & Claim Boundaries

In accordance with repository engineering standards ([PROJECT_STATUS.md](PROJECT_STATUS.md), [RESEARCH_DIRECTION.md](RESEARCH_DIRECTION.md), [RESEARCH_AUDIT_NOTE.md](RESEARCH_AUDIT_NOTE.md), [AGENT_ARCHITECTURE.md](AGENT_ARCHITECTURE.md)):

- **Implemented mechanism $\neq$ universal live-model reliability:** An implemented module backed by deterministic unit and controlled-functional tests establishes that the controller enforces its authority, recovery, and verification contracts cleanly. It does **not** claim guaranteed live-model completion across all task families or model weights.
- **Strict evidence labeling:** Repository records keep **unit**, **integration**, **controlled functional** (scripted model responses exercising real controller/sandbox gates), **live-model end-to-end** (real `gemma4:e4b` inference to persisted, independently verified artifacts — including single-file CLI tasks in [LIVE_E2E_VALIDATION.md](LIVE_E2E_VALIDATION.md), `4/4`-node multi-file recursive Python synthesis (`metrics.py` + `cli.py` + `test_metrics.py`), and human-ready 3D WebGL game synthesis with `initialFrameBlank == False` and `hudOverlapCount == 0` in [RESEARCH_PAPER.md](RESEARCH_PAPER.md)), and **regression** checks strictly separate.
- **Unedited denominators & negative results:** Historical and ongoing evaluations ([EXPERIMENT_HISTORY.md](EXPERIMENT_HISTORY.md), [`../reports/INDEX.md`](../reports/INDEX.md)) preserve every failed, blocked, host-memory-limited, and interrupted run alongside successes. Diagnostic labels (`ROOT VERIFIED`, `CHILD_VERIFIED`, `TASK_TOO_BROAD`) are controller telemetry; independent external acceptance at matched inference/tool/wall-clock budgets remains the decisive scientific endpoint for the *Before You Split* research program ([RESEARCH_DIRECTION.md](RESEARCH_DIRECTION.md), [RESEARCH_AUDIT_NOTE.md](RESEARCH_AUDIT_NOTE.md)).
