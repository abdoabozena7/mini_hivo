# Tool Architecture & Design Rules (`dev_rules/tool_rules.md`)

> - **Status:** Living architectural guardrails (`v0.6`)
> - **Scope:** Custom, framework-free tool layer (`hivo/tools/`) serving asymmetric multi-agent coding tiers (**Orchestrator tier** + **Light Worker / SLM tier**).
> - **Related Specs:** [Rule-Authoring Methodology (`how_to_make_rules.md`)](how_to_make_rules.md), [Orchestration Guardrails (`orchestration_rules.md`)](orchestration_rules.md), [Tools Implementation Architecture (`../docs/TOOLS_ARCHITECTURE.md`)](../docs/TOOLS_ARCHITECTURE.md), [Repository Workflow (`../AGENTS.md`)](../AGENTS.md)
> - **Tag Legend:** `[ENFORCED]` = verified in current `hivo/tools/` code; `[TARGET]` = planned/deferred capability not yet built; `[PROCESS]` = review/test gate.

---

## 1. Core Architectural Principles

1. **No External Tool Frameworks `[ENFORCED]`:** All tool definitions, JSON schemas, argument validation, execution, and result envelopes are written directly in clean, testable Python with zero agent-framework abstractions and zero imports from legacy `mini.py`.
2. **Design for the Weakest Executor (Light-Worker-First Ergonomics) `[ENFORCED]`:**
   - Lightweight models (e.g., `~2B–4B` quantized local coders) degrade rapidly beyond **4–5 visible tools**, fail on deeply nested JSON arguments, hallucinate whitespace/indentation in multi-line exact-string search/replace, and fail hunk line math in unified diffs.
   - Every `slm_safe` tool exposed to a Worker must have a **flat schema**, **minimal token burden**, **deterministic safety checks**, and **self-correcting error hints**.
3. **Asymmetric Role Separation (Least Privilege) `[ENFORCED]`:**
   - The **Orchestrator tier** inspects, navigates, plans, delegates, and verifies — it must **never** receive direct file-mutation tools.
   - The **Light Worker tier** executes narrowly scoped file tasks inside explicit target fences with a minimal tool footprint — it must **never** orchestrate, ask the user, or run unrestricted shell commands.
4. **One Orthogonal Tool Per Job `[ENFORCED]`:** Never create overlapping convenience variants (`read_head`, `read_tail`, `insert_line`, `replace_line`, etc.). Overlapping tools split attention and degrade tool-selection accuracy on lightweight executors.
5. **Static Spawn-Time Binding (KV-Cache Protection) `[ENFORCED]`:** Bind each agent's deterministically serialized tool set once at spawn time via `ToolBinding` (and `spawn_worker_binding()` for fenced workers). Never add, remove, or mutate tool schemas mid-loop.
6. **Tool Layer vs. Harness Loop Boundary `[ENFORCED]`:** Keep loop-level orchestration concerns (turn budgets, stagnation classification, context compaction, thinking policies, model/provider routing) **out** of `hivo/tools/`. Tools expose pure, stateless/context-scoped units plus protocol/profile/hook seams.

---

## 2. Canonical Tool Catalog

### 2.1 Core Tools (`hivo/tools/`) `[ENFORCED]`

Split strictly by role profile so no single agent sees every tool:

| Category | Tool | Default Role Access | Core Behavioral Contract |
| :--- | :--- | :--- | :--- |
| **Inspection** | **`read_file`** | All roles (Base) | Reads an explicit line range (`path`, `start_line`, `end_line`) capped by `ToolContext.max_read_lines`; prefixes every line with Hashlines (`line:short_hash\| content`); supports reading `@scratch/...` overflow logs; handles missing/directory/binary paths cleanly. |
| **Inspection** | **`list_files`** | Orchestrator, Research Worker | `.gitignore`-aware directory/glob listing (supporting `**/` globs) skipping `.git`, `node_modules`, `.venv`, `__pycache__`, and caches; capped by `ToolContext.max_list_entries`. |
| **Inspection** | **`search_code`** | Orchestrator, Research Worker | Ripgrep-backed (`rg`) search with pure-Python fallback; flat params (`query`, `path`, optional `file_glob`, `context_lines`, `is_regex=False` default); searches hidden files excluding `.git/**`; capped by `ToolContext.max_search_matches`. |
| **Inspection** | **`code_intel`** | Orchestrator, Research/Coder/Verifier | AST-based structural outline (`repo_map`, `outline`, `find_symbol`, `find_references`) emitting `start_anchor`/`end_anchor` ranges, with regex/brace-depth fallback on syntax errors and non-Python languages. |
| **Mutation** | **`edit_file`** | Coder Worker *(Workers only)* | Default Hashline-anchored line-range editor (`path`, `start_anchor`, `end_anchor`, `operation`: `"replace"` \| `"insert_after"` \| `"delete"`, `content`; `"0:00"` reserved for top-of-file / empty-file insertion). Forgiving anchor parser verifies hashes before writing, returns refreshed `updated_window` Hashlines + inline syntax check. |
| **Mutation** | **`write_file`** | Coder Worker *(Workers only)* | Creates a new file (auto-creating parent directories) or performs an intentional overwrite (`overwrite=False` default); runs inline syntax check and returns `updated_window` + byte/line counts. |
| **Mutation** | **`delete_file`** | Coder Worker *(opt-in only)* | Deletes a single regular file strictly inside workspace/fence boundaries; refuses directories and recursive deletes. |
| **Mutation** | **Swappable Edit Strategies** | Profile-selected *(benchmark/calibration only)* | `edit_search_replace`, `edit_unified_diff`, `edit_line_range` selectable via `ToolProfile`; each worker sees only **one** configured edit strategy (never overlapping edit tools simultaneously). |
| **Execution** | **`run_command`** | Verifier / Orchestrator *(never unrestricted on Light Workers)* | Non-interactive execution (`stdin=DEVNULL`, scrubbed env) with unquoted shell-operator guard, path/secret inspection across args & `--flag=value` tokens, explicit `timeout_sec` with process-tree kill, separate `stdout`/`stderr`, head+tail truncation, and `@scratch/` overflow log offload. |
| **State** | **`checkpoint`** | Orchestrator | External content-addressed snapshots & 1-step rollback under `@scratch/` with streaming SHA-256 hashing, symlink skipping, and `protected_paths` safety. |
| **Control** | **`dispatch_worker`** | Orchestrator only | Agent-as-a-tool delegation packet (`task`, `target_files`, `context`, `verification_hint`) returning a compact structured result. |
| **Control** | **`update_plan`** | Orchestrator only | Structured JSON plan/progress state (`[{id, title, files, status}]`) avoiding bulky free-form markdown rewrites. |
| **Control** | **`ask_user`** | Orchestrator only *(interactive runs)* | Explicit pause-and-clarify boundary (`question`, optional `options`); omitted automatically in headless/non-interactive runs. |

### 2.2 Deferred High-Leverage Additions `[TARGET]`
Add only when concrete workloads require them and after satisfying all 5 unit contracts:
1. **`get_diff` / `git_status` (Read-Only Change Inspector):** Bounded repository diff inspector for Orchestrator/Verifier review without raw git flags.
2. **LSP Diagnostics & Navigation (`get_diagnostics`, `go_to_definition`, `find_references`):** Cross-file type/import diagnostics beyond single-file syntax checks.
3. **`manage_process` (`start`, `read_output`, `send_input`, `kill`, `list`):** Only when workloads require background dev servers or interactive processes.
4. **`web_search` + `web_fetch` *(Orchestrator only)*:** Documentation/API verification before briefing workers; never exposed to Light Workers.
5. **Browser / Visual Verification *(Verifier / Orchestrator only)*:** For UI/frontend workloads only.

### 2.3 Explicit Prohibitions `[ENFORCED]`

| Prohibited Pattern | Reason |
| :--- | :--- |
| **Default unified-diff (`apply_patch`) editing for Light Workers** | Small executors routinely break hunk counts and context blocks. Keep Hashline `edit_file` as the default; keep `edit_unified_diff` strictly opt-in for profile calibration or stronger tiers. |
| **Unrestricted shell execution for Light Workers** | Causes brittle one-liner edits, interactive hangs, quoting errors, destructive mutations, and context floods. |
| **Overlapping granular file tools** (`read_head`, `read_tail`, `insert_line`, `replace_line`, `append_file`) | Splits tool attention and degrades small-model tool selection. |
| **Semantic / vector embedding search (`codebase_search`)** | High index-staleness overhead; `list_files` + `search_code` + `code_intel` cover navigation deterministically. |
| **Dynamic `tool_search` / heavy MCP registry layer for core tools** | Pure latency/schema overhead for a small (~10–15) native core tool set. |
| **Programmatic Tool Calling (PTC) or free-form `todo.md` rewriting** | High failure rate on lightweight executors and wasted context tokens; use `dispatch_worker` + JSON `update_plan`. |

### 2.4 Legacy Tool Retirement & Quarantine Policy `[ENFORCED]`
When migrating away from legacy tools in `mini.py`:
- **Fold pure overlaps** (`read_file_range` → `read_file`; legacy `edit_file`/`edit_file_range` → Hashline `edit_file`).
- **Retire & quarantine distinct legacy capabilities** (`verify_web_app`, `context_sufficiency_check`, `read_candidate_span`, `backup_file`, `run_file`) outside `hivo/tools/` with zero imports from legacy global state.
- **Strict allowlist profiles only:** Never use denylist filtering over a shared global `TOOLS` list.
- **5-Contract Gate before revival:** Any retired tool revived into `hivo/tools/` must first be rewritten to satisfy all 5 unit contracts (including flat schemas for `slm_safe` tools).

---

## 3. Tool Division & Role-Profile Access Model `[ENFORCED]`

Divide tools into **Base** and **Role-Specific** strictly at the **Registry / Profile layer** — never hardcode role checks inside tool implementations:

1. **Role-Agnostic Tool Units:** Organize code by domain/effect (`fs_read`, `fs_write`, `exec`, `orchestration`, `code_intel`, `checkpoint`), not by role. Each `ToolSpec` declares static `name`, `effect` (`"read" | "write" | "exec" | "control"`), and `model_tier` (`"slm_safe" | "orchestrator_only"`).
2. **Caller-Supplied Immutable `ToolContext`:** Every tool accepts a frozen `ToolContext` enforcing role-specific caps (`workspace_root`, optional `allowed_paths` file fence, `protected_paths` completion-oracle lock, `block_secret_files`, `max_read_lines`, `max_output_chars`, `max_list_entries`, `max_search_matches`, `timeout_sec`, external `scratch_dir`, `allowed_commands`, `hooks`, and control callbacks).
3. **Declarative Allowlist Profiles (`ROLE_PROFILES`):**
   - **Orchestrator:** `read_file`, `list_files`, `search_code`, `code_intel`, `checkpoint`, `update_plan`, `dispatch_worker`, `ask_user` *(+ optional `run_command` when verifying directly; `ask_user` omitted in headless runs)*.
   - **Coder Worker:** `read_file`, configured edit tool (`edit_file` default), `write_file` *(minimal 3-tool default in pre-scoped dispatches; `code_intel` or `delete_file` attached only when needed)*.
   - **Research Worker:** `read_file`, `list_files`, `search_code`, `code_intel`.
   - **Verifier:** `read_file`, `code_intel`, `run_command`.
4. **Protocol & Profile Connectivity:** Support data-driven `ToolProfile` (zero hardcoded model-family string branches + `tool_schema_hash` drift check), 3-mode `ToolProtocolAdapter` (`native`, `grammar_json` with schema-constrained GBNF grammar, `xml_tags`), `HookRegistry` (`pre_tool`, `post_edit`), and `format_tool_observation()` untrusted-data framing.

---

## 4. The 5 Non-Negotiable Unit-Level Contracts `[ENFORCED]`

Every tool in `hivo/tools/` must satisfy all five contracts before being wired into any harness:

1. **Contract 1 — Flat, Deterministic JSON Schemas:** Flat primitives (`str`, `int`, `bool`) or flat lists (no deeply nested objects or complex unions on `slm_safe` tools); minimal required params with sensible defaults; deterministic key ordering so prompt prefixes remain byte-identical across turns.
2. **Contract 2 — 6-Key Uniform Return Envelope & Self-Correcting Errors:** Every tool returns `{ok, data, error, error_code, hint, truncated}` (never raising uncaught exceptions to the model). On `ok: false`, `error` states the factual cause, `error_code` emits a stable taxonomy code, and `hint` prescribes the exact corrective next call.
3. **Contract 3 — Hard Safety, Secret, Oracle & Output Boundaries Inside the Tool:** Never rely on prompts to enforce safety:
   - Resolve `Path.resolve()` (including symlinks and `..`) and enforce `workspace_root` + `allowed_paths`.
   - Block secret files (`.env`, private keys, credential files — while permitting `.env.example`/`.sample`/`.template`) and reject writes to `protected_paths` (`ORACLE_LOCKED`) before touching disk.
   - Preserve UTF-8 and original line endings (`\n` vs `\r\n`); reject binary files cleanly on text tools.
   - Enforce output line/char caps internally, offloading overflow logs and checkpoints to external `scratch_dir` (`@scratch/...`) so zero untracked artifacts pollute the workspace.
   - Enforce `timeout_sec` with full process-tree termination on subprocess tools.
4. **Contract 4 — Deterministic, Atomic Writes & Immediate Feedback:** Validate paths, `overwrite` flags, locks, and Hashline anchors completely before touching disk; write atomically (temp file in target directory + `os.replace`); run fast inline syntax checks (e.g., Python `ast.parse`, `json.loads`) + `post_edit` sensors immediately and return refreshed `updated_window` Hashlines.
5. **Contract 5 — Standalone Offline Unit Test Gate `[PROCESS]`:** No tool is complete until pure-Python tests (zero LLM calls) verify: (1) happy path, (2) boundary/truncation & `@scratch/` offload, (3) invalid/malformed args (`ok: false` + `hint`), (4) security escapes (`..`, symlinks, path fences, secret/oracle locks), (5) conflict/staleness (hash mismatch, `overwrite=False`, deleting a directory), and (6) edge hazards (missing/empty/CRLF/binary files, timeouts).

---

## 5. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial asymmetric tool catalog, Base + Role Profile model, `ToolContext`, and 5 unit contracts. |
| `v0.2` | 2026-11-26 | Added Legacy Tool Retirement & Quarantine Policy. |
| `v0.3` | 2026-11-26 | Implemented core `hivo/tools/` units and offline unit tests (`updates/R_UPDATE_010.md`). |
| `v0.4` | 2026-11-26 | Added swappable edit strategies, `code_intel`, `checkpoint`, `HookRegistry`, secret/oracle locks, `@scratch/`, 3-mode `ToolProtocolAdapter`, `ToolProfile`, and 6-key `error_code` envelope. |
| `v0.5` | 2026-11-26 | Trimmed loop-level scope from `hivo/tools/`, hardened anchors/globs/command security/AST fallback, and added schema-constrained GBNF + `ToolBinding` connectivity (`updates/R_UPDATE_010.md`). |
| `v0.6` | 2026-11-26 | Moved to `dev_rules/tool_rules.md`; generalized hardcoded model-size labels to capability tiers per `how_to_make_rules.md`; added `[ENFORCED]`/`[TARGET]`/`[PROCESS]` tags; reconciled promoted tools, `ToolContext`, and 6-key envelope; removed changelog bloat from rule body. |
