# Orchestration Architecture & Guardrails (`dev_rules/orchestration_rules.md`)

> - **Status:** Living architectural guardrails (`v0.4` — aligned with asymmetric orchestration design, Decomposition-Capability Scaling & `benchmarking_rules.md`)
> - **Scope:** Orchestration layer — how Mini Hivo coordinates an **Orchestrator tier** and **Worker tier(s)** across capability floors, contract-complete decomposition, delegation, context budgets, rollback safety, verification handoffs, and provider-agnostic endpoints.
> - **Related Specs:** [Rule-Authoring Methodology (`how_to_make_rules.md`)](how_to_make_rules.md), [Tool Architecture & Design Rules (`tool_rules.md`)](tool_rules.md), [Benchmarking & Evaluation Rules (`benchmarking_rules.md`)](benchmarking_rules.md), [Orchestration Implementation Architecture (`../docs/ORCHESTRATION_ARCHITECTURE.md`)](../docs/ORCHESTRATION_ARCHITECTURE.md), [Hybrid Model & Provider Reference (`../docs/HYBRID_MODEL_STRATEGY.md`)](../docs/HYBRID_MODEL_STRATEGY.md), [Repository Workflow (`../AGENTS.md`)](../AGENTS.md)
> - **Rule Standard:** Guardrails below are **model-, vendor-, and hardware-agnostic invariants**. Any named models or providers are **illustrative examples / reference targets**, never mandatory locks. Live provider pricing, quotas, and hardware tuning live in `docs/`; dated empirical runs live in `docs/worklogs/` (with historical baseline records preserved in `reports/` and `updates/`).
> - **Tag Legend:** `[ENFORCED]` = verified in current orchestration code; `[TARGET]` = empirically validated invariant to enforce in upcoming orchestration work; `[PROCESS]` = operational or verification gate.

---

## 1. Architectural Model — Asymmetric Two-Tier Orchestration

Mini Hivo separates **architectural reasoning & control** from **scoped code execution** across two tiers connected by strict, machine-verifiable contracts:

1. **Orchestrator Tier (Planning, Localization, Contract Authoring & Verification):**
   - Owns problem understanding, repository navigation, decomposition into contract-sealed leaves, worker briefing, diff review, and independent verification.
   - Operates strictly through inspection, planning, delegation, and verification tools — **Zero Orchestrator Code-Writing Invariant**: the Orchestrator never directly edits source files and never leaks full implementation code inside decomposition plans or worker task packets.
2. **Worker Tier (Scoped Execution):**
   - Owns concrete, narrowly scoped file creation or edits strictly inside its assigned `target_files`.
   - Runs as a bounded sub-loop invoked by the Orchestrator (agent-as-a-tool) with a minimal fixed tool surface, flat schemas, non-thinking execution, and fast deterministic feedback.

> **Migration Boundary `[ENFORCED]`:** New orchestration modules (`hivo/providers/`, `hivo/hybrid/`) stay isolated from legacy single-model `mini.py` global state (zero imports from `mini.py`) and log explicit per-run model/endpoint provenance until a full cutover is authorized.

---

## 2. Capability Floors & Reference Model Tiers (Non-Binding Examples)

Orchestration reliability depends on matching each tier to a **minimum behavioral capability floor**, not to a single vendor or model ID.

### 2.1 Orchestrator Tier — Minimum Required Capabilities
To reliably steer even ultra-light workers without collapsing into uncontracted oversplitting, the Orchestrator model **must** satisfy all five capabilities:
1. **Contract-Complete Decomposition:** Partition multi-file tasks into disjoint, single-concern leaves specifying exact file ownership, callable signatures, I/O schemas, error invariants, and declarative verification checks — without leaking implementation bodies.
2. **Multi-File Brownfield Localization:** Navigate large repositories (`10,000+` lines) via bounded inspection tools (`code_intel`, `search_code`, `read_file`) to pinpoint exact symbols and line anchors without losing root requirements.
3. **Active Reasoning / Thinking Support:** Support verifiable reasoning mode (`think=True`) with enough output headroom (`4,096–8,192` tokens) that thinking chains never truncate tool calls or structured JSON.
4. **Sustained Multi-Turn Tool Discipline:** Emit valid native tool calls and structured JSON reliably across `10–20` turns without schema drift or repetition loops.
5. **Diff & Failure Diagnosis:** Inspect compact unified diffs and deterministic test failures, catch subtle single-line worker mistakes (e.g., blank-line deletion or off-by-one logic), and refine the next worker packet instead of repeating a failed prompt.

- **Target Capability Band:** Mid-to-high **reasoning-capable coding models** (e.g., `~27B–32B+` dense thinking models, capable MoE reasoning models, or frontier reasoning APIs). Local `<= 4B` models fall below this floor for multi-file contract planning.

### 2.2 Worker Tier — Minimum Required Capabilities
The Worker tier only needs to execute a **single, contract-sealed leaf or targeted edit**:
1. Follow a small (`3–4` tool) flat-schema interface cleanly (via native tool calls or constrained JSON/grammar adapters).
2. Produce a coherent single-concern leaf (`< ~60` lines on greenfield modules) or apply an exact Hashline-anchored edit on an existing file without hallucinating surrounding code.
3. Fit cleanly within the host's compute/VRAM budget (100% GPU resident when running locally).

- **Target Capability Band:** Lightweight quantized coding models in the **`~2B–4B` (`Q4_K_M`)** class for local execution (or ultra-cheap fast/flash cloud models). Sub-`2B` models (`~1.5B`) hit an irreducible single-leaf floor on coupled stateful classes and multi-export modules, succeeding mainly on pure algorithmic leaves.

### 2.3 Development vs. Production Model & Provider Path (Illustrative Examples Only)
Development uses **free cloud endpoints** for the Orchestrator tier (paired with a **local quantized Worker**) to iterate at zero API cost, with a planned **config-only upgrade to paid endpoints** for large-scale benchmarks and production runs:

| Stage | Orchestrator Tier (Examples) | Worker Tier (Examples) | Swap Mechanism |
| :--- | :--- | :--- | :--- |
| **Development (Current — Free Cloud + Local)** | Free OpenAI-compatible reasoning tiers such as Groq (`qwen/qwen3.8-27b`, `openai/gpt-oss-120b`), NVIDIA NIM (`nemotron` / `glm` / `kimi` thinking endpoints), or Google AI Studio (`gemini` flash / `gemma` 31B) | Local quantized Ollama coder (e.g., `qwen3.5:2b-q4_K_M`, `qwen2.5-coder:3b`) | `EndpointConfig` preset + `.env` key |
| **Production / Full Benchmarks (Planned — Paid Drop-In)** | Paid higher-quota / low-latency reasoning endpoints such as `Qwen3.8-27B`, `DeepSeek V4.1-Flash`, or frontier reasoning models via OpenRouter, Cerebras, Chutes, or DeepInfra | Same local quantized worker (or optional fast/flash cloud worker tier) | **Config-only swap** (`base_url`, `api_key_env`, `model`, flags) — zero code changes |

> *See [../docs/HYBRID_MODEL_STRATEGY.md](../docs/HYBRID_MODEL_STRATEGY.md) for current provider comparison, quotas, and pricing notes. Never hardcode provider prices, quotas, or model IDs inside orchestration logic.*

---

## 3. Contract-Complete Decomposition Guardrails

Empirical scaling studies show that **more splitting without complete interface contracts is strictly worse than no splitting** (causing combinatorial signature, schema, and exception drift across module boundaries):

1. **5-Dimension Contract Completeness ($\kappa \ge 0.90$) `[TARGET]`:** Never split work across multiple files/workers unless each leaf contract explicitly seals:
   - *Explicit File Ownership* (disjoint writable paths: $O_i \cap O_j = \emptyset$),
   - *Callable Signatures* (exact function/class/export names and parameter lists),
   - *I/O & Data Schemas* (exact dict keys, types, DOM IDs, or protocol formats),
   - *Error & Edge-Case Invariants*, and
   - *Declarative Executable Verification Oracle* (how the harness verifies the leaf deterministically).
2. **Bounded Leaf Horizon & Single-Concern Splits `[TARGET]`:** For lightweight (`<= 4B`) greenfield workers, bound each leaf to one cohesive concern (`< ~60` lines / small export surface) rather than combining unrelated subsystems (e.g., UI wiring + core state + render loop) in one file.
3. **Single-Syntax Leaf Law `[TARGET]`:** Never require a lightweight worker (especially JSON-envelope workers) to embed one programming language inside another (such as inline `<script>` JS inside HTML) where multi-level quoting/escaping degrades reliability.
4. **Anti-Code-Leakage Discipline `[TARGET]`:** Plans and task packets specify *contracts and behavioral expectations*, never full copy-paste code bodies written by the Orchestrator.

---

## 4. Role Separation, Tool Bindings & Provider Boundaries

1. **Least Privilege Enforced in Code `[ENFORCED]`:** Enforce Orchestrator vs. Worker authority at the `ToolBinding` and `ToolContext` layer (workspace confinement + `allowed_paths` file fence), never by prompt wording alone.
2. **Minimal Fixed Worker Surface `[ENFORCED]`:** Default coding workers to a 3-tool surface (`read_file`, `edit_file`, `write_file`; attach `delete_file` only when deletion is explicitly required). Never expose search, orchestration, `ask_user`, or unrestricted shell tools to a pre-scoped coding worker.
3. **Static Spawn-Time Binding `[ENFORCED]`:** Serialize and bind tool schemas deterministically once at spawn time; never add, remove, or mutate schemas mid-loop (protects prompt-prefix / KV-cache stability).
4. **Non-Interactive Mode Awareness `[ENFORCED]`:** Automatically omit interactive tools (`ask_user`) whenever no user callback is attached (batch, CI, or benchmark runs).
5. **Config-Only Provider Adaptation `[ENFORCED]`:** Keep all endpoint quirks inside stdlib-only adapters (`hivo/providers/clients.py`) driven purely by `EndpointConfig`:
   - Normalize tool call arguments between JSON-string (OpenAI) and dict (Ollama) wire formats without swallowing malformed JSON (let `ToolProtocolAdapter` emit self-correcting errors).
   - Support configurable structured-output fallback (`json_schema` → `json_object` → `prompt`).
   - Verify active thinking empirically (`reasoning_chars > 0` when `think=True`, passing endpoint-specific effort controls like `reasoning_effort` via config), and strip `reasoning_content` / `reasoning` / `<think>...</think>` blocks from persisted history and worker packets.
6. **Transport-Only Backoff & Explicit Failures `[ENFORCED]`:** Handle retryable HTTP errors (`408`, `429`, `5xx`) strictly inside the transport layer — parsing both numeric `Retry-After` seconds and duration-formatted rate-limit reset headers (`ms`/`s`/`m`/`h` such as `x-ratelimit-reset-tokens`) while clamping sleep to the run's monotonic wall-clock deadline. On quota exhaustion or outage, fail explicitly (`ProviderError`) and **never** fabricate placeholder outputs or silently swap models.

---

## 5. Context, Resource & Loop-Control Guardrails

1. **Hardware-Aligned Local Worker Residency `[ENFORCED / PROCESS]`:**
   - Keep a single resident local worker warm (`keep_alive` set, no multi-model VRAM thrashing), disable thinking on local workers (`think=False`), and cap local `num_ctx` cleanly (e.g., `4096` default, hard ceiling `<= 8192`).
   - Verify **100% GPU residency** empirically on the target host (e.g., `ollama ps` + `nvidia-smi` with Flash Attention / KV-cache quantization enabled) rather than assuming a quantization fits without CPU spill.
2. **Bounded Inline Outputs & Two-Pass Anchor-Pinned Compaction `[ENFORCED]`:**
   - Enforce per-role inline tool output caps (`orchestrator_max_output_chars`, `max_read_lines`) and offload oversized logs to external scratch storage.
   - Before every turn, enforce a hard serialized history ceiling via multi-pass compaction: shrink older tool observations first (preserving system prompt and the root task specification anchor), then trim oversized recent tool observations if still above ceiling — preventing mid-run payload-limit (`413`) or context-overflow crashes.
3. **Stop-On-Success & Circuit Breakers `[ENFORCED]`:**
   - Instruct lightweight workers to **stop immediately** once a mutation returns `ok: true` and `syntax_ok: true` for the requested change (never re-applying edits with stale anchors).
   - Enforce hard ceilings on orchestrator turns, worker turns, consecutive worker errors (default `2`), total worker dispatches, and global wall-clock elapsed time.
4. **Target-Scoped Atomic Rollback (`O(target_files)`) `[ENFORCED]`:**
   - Snapshot exact raw bytes of **only** `target_files` prior to each worker dispatch and restore them atomically (`atomic_write_bytes`, removing newly created files) on worker failure or abort. Never run full-repository tree hashing inside the per-dispatch hot path.

---

## 6. Repair, Diff Handoff & Independent Verification Guardrails

1. **Scope-Matched Repair Strategy:**
   - **Small Greenfield Leaves (`< ~60` lines owned solely by the leaf) `[TARGET]`:** Prefer **whole-file atomic replacement (`write_file`)** on repair to avoid multi-turn line-offset thrashing on ultra-light workers.
   - **Brownfield / Large Existing Files `[ENFORCED]`:** Use **Hashline-anchored targeted edits (`edit_file`)** with refreshed post-edit anchors and inline syntax validation so untouched surrounding code is never clobbered.
2. **Mandatory Computed `unified_diff` in Worker Results `[TARGET]`:**
   - Immediately after a worker modifies files, compute a compact `unified_diff` directly from the pre-dispatch `target_snapshot` bytes vs. post-dispatch disk state and return it inside `dispatch_worker`'s payload.
   - *Why:* Prevents silent semantic damage (such as a lightweight worker replacing a line with a blank line while returning `ok: true`) by letting the Orchestrator audit the exact diff on the very next turn before burning test turns.
3. **Deterministic Verification Gates Over Weak Self-Verification:**
   - **Never trust prose self-certification `[ENFORCED]`:** Do not treat worker completion text — or a weak LLM's self-authored test pass — as proof of success. Lightweight workers routinely omit post-write verification, and weak LLM reviewers hallucinate assertions.
   - **Inline + external verification `[ENFORCED]`:** Pair inline syntax checks with deterministic harness verification (unit tests or independent container test suites).
   - **Declarative component verification oracles (DCVG) `[TARGET]`:** Attach declarative per-leaf verification oracles at planning time for contract-decomposed multi-file builds so every leaf is verified deterministically at zero extra LLM cost.
4. **Benchmarking & Independent Evaluation `[PROCESS]`:** All benchmark isolation, workspace decontamination, privilege-separated output verification, deterministic KPIs, and promotion gates are governed by [`benchmarking_rules.md`](benchmarking_rules.md).
5. **Secrets, Privacy & Offline-First Testability `[ENFORCED]`:**
   - Load credentials strictly from process env or gitignored `.env`; never emit real vendor key prefixes, private host paths, or account IDs into prompts, logs, traces, tests, or tracked docs.
   - Keep core orchestration mechanics (turn routing, compaction, backoff parsing, rollback, diff handoff, error handling) deterministically testable offline with scripted mock clients before running live inference.

---

## 7. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial model-, vendor-, and hardware-agnostic orchestration guardrails. |
| `v0.2` | 2026-11-26 | Added Orchestrator/Worker behavioral capability floors (informed by the Decomposition-Capability Scaling Law & live hybrid runs), non-binding dev-free → paid-target model/provider examples, 5-dimension contract-completeness & single-syntax guardrails, scope-matched greenfield vs. brownfield repair rules, and moved into `dev_rules/`. |
| `v0.3` | 2026-11-26 | Updated `tool_rules.md` link after `dev_rules/` move and split mixed `[ENFORCED]` / `[TARGET]` / `[PROCESS]` status tags per sub-bullet for strict 1:1 accuracy against current code. |
| `v0.4` | 2026-11-26 | Linked `benchmarking_rules.md`, deduplicated §6.4 benchmark guardrails into a single pointer, and updated empirical-run path to `docs/worklogs/`. |
