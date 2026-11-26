# Tool Architecture & Design Rules (`tool_rules.md`)

> - **Status:** Living specification (v0.5 — scope-focused tool hardening & `ToolBinding` connectivity)
> - **Scope:** Custom, framework-free tool layer (`hivo/tools/`) for an asymmetric multi-agent coding architecture
> - **Target Model Split:** Smart cloud **Orchestrator** (e.g., Qwen 27B) + ultra-light **Workers** (e.g., Qwen 2B)
> - **Current Phase:** Harden every tool unit and tool-to-tool / protocol / profile connection inside `hivo/tools/` without loop-level scope creep.

---

## 1. Core Architectural Principles

1. **No External Tool Frameworks:** All tool definitions, schemas, validation, execution, and result envelopes are written directly in clean, testable Python with zero agent-framework abstractions.
2. **Design for the Weakest Executor (2B-First Ergonomics):**
   - Small models (2B–3B) degrade rapidly beyond **4–5 visible tools**, fail on deeply nested JSON arguments, hallucinate whitespace/indentation in exact multi-line `str_replace`, and fail hunk math in unified diffs (`apply_patch`).
   - Every tool exposed to a worker must have a **flat schema**, **minimal token burden**, **deterministic safety checks**, and **self-correcting error hints**.
3. **Asymmetric Role Separation (Least Privilege):**
   - The **Orchestrator (27B)** inspects, plans, decomposes, delegates, and verifies — it does **not** directly edit source lines.
   - **Workers (2B)** execute narrowly scoped tasks on explicit target files with a tiny tool footprint — they do **not** orchestrate, ask the user, or run unrestricted shell commands.
4. **One Orthogonal Tool Per Job:** Never create overlapping convenience variants (`read_head`, `read_tail`, `insert_line`, `replace_line`, etc.). Overlapping tools degrade tool selection, especially on 2B models.
5. **Static Spawn-Time Binding (KV-Cache Protection):** Every agent receives a fixed, deterministically serialized tool set at spawn time. Never add, remove, or mutate tool schemas mid-loop.

---

## 2. Canonical Tool Catalog

### 2.1 MUST ADD — v1 Core Tools (Build & Verify First)

Total codebase footprint: **10 core tools**, split by role so no single agent sees all 10.

#### A. Inspection & Discovery
| Tool | Roles | Core Behavioral Specification |
| :--- | :--- | :--- |
| **`read_file`** | All roles (Base) | Reads an explicit line range (`path`, `start_line`, `end_line`) with a strict per-call cap (e.g., 150–300 lines). **Prefixes every line with `line_num:short_hash\|` (Hashlines)** (e.g., `42:a3\| def login(user):`). Returns clear truncation guidance (`"Showing lines 1-200 of 540..."`). Handles missing files, directories, and binary files cleanly. |
| **`list_files`** | Orchestrator, Research Worker | `.gitignore`-aware directory/glob listing (`path`, optional `pattern`, `max_depth`). Automatically skips `.git`, `node_modules`, `.venv`, `__pycache__`. Hard-capped entry count (e.g., 100–200 paths). |
| **`search_code`** | Orchestrator, Research Worker *(optional for Coder)* | Ripgrep-backed (`rg`) search with pure-Python fallback. Flat params: `query`, `path`, optional `file_glob`, **`is_regex=False` by default** (avoids regex-escaping failures). Returns `file:line:text`, hard-capped (e.g., 50 matches) with overflow count. |

#### B. File Mutation *(Workers Only — Never Exposed to Orchestrator)*
| Tool | Roles | Core Behavioral Specification |
| :--- | :--- | :--- |
| **`edit_file`** | Coder Worker | **Hashline / anchored line-range editor** (the #1 critical tool for 2B workers). Flat params: `path`, `start_anchor` (e.g. `"42:a3"`), `end_anchor` (e.g. `"47:f1"`), `operation` (`"replace"` \| `"insert_after"` \| `"delete"`), `content`. Verifies hashes before writing so stale reads fail safely without corrupting code. Returns updated lines with **refreshed hashes** plus an **immediate syntax check** (e.g., Python `ast.parse`) inline. |
| **`write_file`** | Coder Worker | Creates a new file (auto-creating parent directories) or performs an intentional overwrite (`overwrite=False` by default to prevent silent clobbering). Runs an immediate syntax check on save and returns line count + byte size. |
| **`delete_file`** | Coder Worker *(only when task requires deletion)* | Deletes a single file strictly inside the workspace boundary. Refuses directories and recursive deletes. |

#### C. Execution & Verification
| Tool | Roles | Core Behavioral Specification |
| :--- | :--- | :--- |
| **`run_command`** | Verifier / Orchestrator *(never unrestricted on 2B)* | Executes a command in an explicit `cwd` with a **hard timeout** (e.g., 30–60s). Separates `stdout` and `stderr`, returns `exit_code` and `timed_out`. Applies **head+tail truncation** inline (e.g., first 40 + last 60 lines) and writes the full output to a temp log file whose path is returned in the response. *(If ever exposed to a worker, must be strictly allowlisted to orchestrator-supplied test/lint commands.)* |

#### D. Orchestrator Control *(Orchestrator Only — Never Exposed to 2B)*
| Tool | Roles | Core Behavioral Specification |
| :--- | :--- | :--- |
| **`dispatch_worker`** | Orchestrator | "Agent-as-a-Tool" delegation boundary. Accepts a tightly scoped task packet (`task`, `target_files`, `context`, `verification_hint`) and returns a compact structured result (`status`, `modified_files`, `diff_summary`, `error`). |
| **`update_plan`** | Orchestrator | Maintains structured JSON decomposition/progress state (`[{id, title, files, status}]`) across turns without rewriting bulky markdown files. |
| **`ask_user`** | Orchestrator | Explicit pause-and-clarify boundary (`question`, optional `options`) when requirements or risky decisions are ambiguous. |

---

### 2.2 GOOD TO HAVE — v2 High-Leverage Additions (Defer Until v1 Core Passes All Unit Tests)

1. **`list_symbols` (AST / Tree-sitter Outline) — *Highest-ROI v2 tool for 27B + 2B***
   - Returns only class/function signatures and exact line ranges for a file so the 27B planner can inspect file skeletons cheaply and hand 2B workers exact `(path, start_line, end_line)` targets.
2. **`get_diff` / `git_status` (Read-Only Change Inspector)**
   - Gives the Orchestrator a clean, bounded diff of exactly what a worker modified without crafting raw git flags.
3. **LSP Diagnostics & Navigation (`get_diagnostics`, `go_to_definition`, `find_references`)**
   - Catches cross-file type, import, and reference errors that single-file syntax checks cannot see.
4. **`manage_process` (`start`, `read_output`, `send_input`, `kill`, `list`)**
   - Add only when workloads require background dev servers, databases, or interactive PTY sessions.
5. **`web_search` + `web_fetch` *(Orchestrator Only)***
   - For checking current library APIs/docs before briefing workers. Never expose to 2B workers.
6. **Browser / Visual Verification *(Verifier / Orchestrator Only)***
   - Only for frontend/UI workloads with a vision-capable verifier model.

---

### 2.3 DO NOT ADD — Explicit Prohibitions

| Prohibited Tool / Pattern | Reason |
| :--- | :--- |
| **`apply_patch` (Unified diff format) for 2B workers** | Requires model-specific post-training; 2B models constantly break hunk line counts and context blocks. Use Hashline `edit_file` instead. |
| **Unrestricted `bash` / `powershell` for 2B workers** | Causes brittle `sed`/one-liner edits, interactive hangs, OS-quoting errors, destructive mutations, and context floods. |
| **Semantic / Vector Embedding Search (`codebase_search`)** | High infrastructure/index-staleness overhead; `list_files` + `search_code` + AST `list_symbols` covers ~95% of needs cleanly. |
| **Overlapping / Granular File Tools** (`read_head`, `read_tail`, `read_many`, `insert_line`, `replace_line`, `append_file`) | Splits attention and severely degrades 2B tool-selection accuracy. |
| **Dynamic `tool_search` / MCP Registry Layer** | Only justified at 50–500 external tools; pure overhead and extra latency for ~10 native tools. |
| **Programmatic Tool Calling (PTC)** | Over-engineered for v1; 2B models fail at meta-scripting and the orchestrator already delegates via `dispatch_worker`. |
| **Free-form `todo.md` Rewriting Tools** | Wastes ~20–30% context tokens and drifts; use structured JSON `update_plan` on the orchestrator only. |
| **Niche Format Tools (`NotebookEdit`, etc.)** | Unnecessary schema noise unless notebooks become a primary workload. |

---

### 2.4 Legacy Tool Retirement & Isolation Policy

When migrating away from legacy tools in `mini.py`, **retire and isolate rather than delete** any tool that introduces a genuinely distinct capability, while **folding or removing pure overlaps** that directly degrade 2B workers.

#### Triage of Existing Extra Tools
- **Must Fold / Remove (pure overlaps — 2):**
  - `read_file_range` → fold `start_line` / `end_line` directly into `read_file`.
  - `edit_file_range` → replace both `edit_file` and `edit_file_range` with one Hashline-anchored `edit_file`.
- **Retire & Isolate (preserve hidden/opt-in — 5):**
  - **`verify_web_app`** → keep as an optional task-specific tool attached *only* to the Verifier profile on web/HTML tasks, never globally.
  - **`context_sufficiency_check`** → quarantine for now; if revived later for 2B workers, flatten its nested `needed_evidence` array schema (e.g., `request_context(target, reason)`).
  - **`read_candidate_span`** → quarantine as an archive for potential strict enum-only 2B reading experiments.
  - **`backup_file`** → retire as an LLM-facing tool; keep the internal `backup()` helper for automatic harness/write snapshots.
  - **`run_file`** → quarantine for now; preserve its browser-JS detection and literal-artifact SHA-256 verification logic for reuse inside the Verifier layer.

#### 3 Mandatory Isolation Rules
1. **Strict Allowlist Profiles Only:** Never use denylist filtering over a shared global `TOOLS` list. Retired and optional tools live in a separate namespace/registry and are never auto-exposed in any default profile.
2. **Hard Boundary From Legacy Global State:** Retired tools stay quarantined in legacy code / `retired/` with zero imports from the new core tool package (never mix `mini.py` globals with `ToolContext` tools).
3. **5-Contract Gate Before Revival:** Any retired tool brought back into active use must first be rewritten to satisfy all 5 unit-level contracts (including flat schemas for `slm_safe` tools).

---

## 3. Tool Division & Access Model (Global Base + Specific Profiles)

We divide tools into **Global (Base)** and **Specific (Role/Task)** **at the Registry/Profile layer — NEVER hardcoded inside the tool implementations themselves.**

### 3.1 Layer 1: Role-Agnostic Tool Units (Code Organization)
- Every tool is a pure, standalone unit that does **not** know which model or agent role called it.
- Do **not** split source files into `global_tools/` vs. `specific_tools/` (roles evolve; tool semantics don't). Organize by domain/effect instead (`fs_read`, `fs_write`, `exec`, `orchestration`).
- Each tool declares lightweight static metadata:
  - `name`: unique snake_case identifier
  - `effect`: `"read"` | `"write"` | `"exec"` | `"control"`
  - `model_tier`: `"slm_safe"` (flat schema, 2B-ready) | `"orchestrator_only"`
- Every tool accepts a caller-supplied immutable **`ToolContext`** so the *same* tool automatically enforces tighter caps and path fences for 2B workers:

```python
@dataclass(frozen=True)
class ToolContext:
    workspace_root: Path
    allowed_paths: tuple[str, ...] | None = None  # Optional strict file fence for a worker
    max_read_lines: int = 250                     # e.g., 400 for 27B, 150-200 for 2B
    max_output_chars: int = 16_000                # Hard cap on inline tool payload
    timeout_sec: int = 30                         # Subprocess timeout
    scratch_dir: Path | None = None               # Overflow log offload directory
```

### 3.2 Layer 2: Declarative Role Profiles (Global Base + Specific Overlay)

| Profile | Base ("Global") | Specific Tools Attached | Total Visible |
| :--- | :--- | :--- | :---: |
| **Orchestrator (27B)** | `read_file` | `list_files`, `search_code`, `update_plan`, `dispatch_worker`, `ask_user` *(+ `run_command` if orchestrator verifies directly)* | 6–7 |
| **Coder Worker (2B)** | `read_file` | `edit_file`, `write_file` *(+ `delete_file` ONLY if task requires deletion)* | 3–4 |
| **Research Worker (optional)** | `read_file` | `list_files`, `search_code` | 3 |
| **Verifier / Test Runner** | `read_file` | `run_command` *(+ `get_diff` in v2)* | 2 |

### 3.3 Exposure Rules
1. **No tool is blindly global with identical limits:** Even `read_file` uses role-appropriate `ToolContext` (`max_read_lines`, optional `allowed_paths`).
2. **Don't give search tools to a pre-scoped 2B coder by default:** If the Orchestrator already provided exact file paths and line ranges, omitting `list_files` / `search_code` prevents the 2B worker from wandering and exhausting its context.
3. **Bind once at spawn time:** A worker's `Base + Specific` tool list is fixed when the worker is spawned and never mutated during its turn loop (preserves KV-cache and prevents schema drift).

---

## 4. The 5 Non-Negotiable Unit-Level Contracts

Every rewritten tool unit **must** satisfy all five contracts before it is wired into the harness:

### Contract 1: Flat, Deterministic JSON Schemas
- Parameters must be flat primitives (`str`, `int`, `bool`) or flat lists — **no deeply nested objects or complex union schemas** on any `slm_safe` tool.
- Minimize required parameters; provide explicit, sensible defaults for optional ones.
- Serialize tool schemas with deterministic key ordering so prompt prefixes remain byte-identical across turns.

### Contract 2: Uniform Structured Return Envelope & Self-Correcting Errors
Every tool returns the exact same envelope shape (never raise raw uncaught exceptions to the model):

```json
{
  "ok": true,
  "data": {},
  "error": null,
  "hint": null,
  "truncated": false
}
```

- When `ok` is `false`:
  - `error` states the exact factual cause (never a raw Python traceback or bare `"failed"`).
  - `hint` gives the exact corrective next call (e.g., `"Hash mismatch at line 42 (expected a3, found 9f). Call read_file(path, 35, 55) to refresh anchors before editing."`).

### Contract 3: Hard Safety & Output Boundaries Inside the Tool
Never rely on the system prompt to enforce safety or output size:
- **Path confinement:** Resolve `Path.resolve()` (including symlinks and `..`) and reject any path outside `ToolContext.workspace_root` (and outside `ToolContext.allowed_paths` when set).
- **Encoding & binary safety:** Read/write UTF-8 cleanly; preserve original file line endings (`\n` vs `\r\n`); reject binary files with a clean `ok=false` error on text tools.
- **Hard output bounding:** Every read, search, and command tool enforces line/character caps internally. When truncated, set `truncated=true` and either give exact pagination params (`read_file`) or write full output to `scratch_dir` and return the file path (`run_command`).
- **Hard execution timeouts:** Any subprocess tool must enforce `timeout_sec`, kill the entire process tree on timeout, and return partial captured output + `timed_out=true`.

### Contract 4: Deterministic, Atomic Writes & Immediate Feedback
- Validate paths, permissions, `overwrite` flags, and Hashline anchors **completely before touching disk**.
- Perform writes atomically (write temp file in target directory + `os.replace`) so a failure never leaves a truncated/corrupted source file.
- Run a fast, non-blocking syntax check on supported languages (e.g., `ast.parse` for `.py`, `json.loads` for `.json`) immediately after `edit_file` / `write_file` and report any syntax error right inside the response so the worker can self-correct on the next turn.

### Contract 5: Standalone Pure-Python Unit Test Gate
No tool is considered done until it passes a standalone unit test suite (with **zero LLM calls**) covering at minimum:
1. Happy path (normal valid inputs and expected disk/data state)
2. Boundary & truncation behavior (large files, high match counts, long command output + offload)
3. Invalid / malformed arguments (clean `ok=false` + `hint`, no uncaught exception)
4. Security / boundary escapes (`../` traversal, symlink outside workspace, disallowed path fence)
5. Conflict & staleness cases (hash mismatch on `edit_file`, existing file with `overwrite=False` on `write_file`, deleting a directory on `delete_file`)
6. Edge files & runtime hazards (missing file, empty file, CRLF line endings, binary file, command timeout)

### 4.1 Implemented Package & Hashline Convention (`hivo/tools/`)
- **Package modules (zero imports from `mini.py`):**
  - `hivo/tools/base.py`: `ToolContext`, `ToolSpec`, uniform return envelope (`ok_result`/`err_result`), strict recursive argument validation, workspace/fence path confinement, safe UTF-8/binary/line-ending I/O, atomic temp-file writes, syntax checks (`.py`, `.json`, `.js`), `.gitignore` matcher, and Hashline helpers.
  - `hivo/tools/fs_read.py`: `read_file`, `list_files`, `search_code` (ripgrep + pure-Python fallback).
  - `hivo/tools/fs_write.py`: `edit_file`, `write_file`, `delete_file`.
  - `hivo/tools/exec_tool.py`: `run_command` (unquoted operator guard, read-only `git` & path checks, separate `stdout`/`stderr`, head+tail truncation, overflow log offload, process-tree kill on timeout).
  - `hivo/tools/orchestration.py`: `PlanState`, `update_plan`, `dispatch_worker`, `ask_user`.
  - `hivo/tools/registry.py` & `hivo/tools/__init__.py`: `CORE_TOOLS`, strict allowlist `ROLE_PROFILES`, `build_profile_tools`, deterministic schema export (`export_openai_tools` / `serialize_openai_tools`), and fail-closed `execute_tool`.
- **Hashline anchor specification:** `line_hash(line)` uses `blake2b(line.encode("utf-8"), digest_size=1).hexdigest()` (2 lowercase hex characters, formatted `line:hash| content`). `"0:00"` is reserved exclusively for `edit_file(operation="insert_after", start_anchor="0:00")` to insert at the top of a file or populate an empty 0-line file.

### 4.2 Hardening & Calibration Upgrades (`v0.4` — tool-layer items)
- **6-Key Uniform Envelope:** `{ok, data, error, error_code, hint, truncated}` (loop-level stagnation/taxonomy logic stays out of `hivo/tools/`).
- **Swappable Multi-Format Edit Engine (`hivo/tools/edit_strategies.py`):** Supports `hashline` (`edit_file`), `search_and_replace` (`edit_search_replace`), `unified_diff` (`edit_unified_diff`), `line_range_patch` (`edit_line_range`), and `whole_file_rewrite` (`write_file`), selected via `ToolProfile` (`tool_profile.yaml` / YAML config). Each worker still sees only its configured edit strategy (no uncalibrated overlap).
- **Promoted v1 Tools:**
  - `code_intel` (`hivo/tools/code_intel.py`): `repo_map`, `outline`, `find_symbol`, `find_references` (AST for Python + regex fallback/extractor for broken syntax & JS/TS/Go/Rust/C/C++/Java).
  - `checkpoint` (`hivo/tools/checkpoint_tool.py`): external content-addressed snapshots & 1-step rollback with streaming SHA-256 hashing, tree-hash verification, symlink skipping, and `protected_paths` safety.
- **Security, Non-Interactive Execution & Clean Scratch:**
  - Secret file blocking (`is_secret_path`, `.env` / keys / credentials) and scrubbed non-interactive `build_sanitized_env()` + `stdin=subprocess.DEVNULL` in `run_command`.
  - `ToolContext.protected_paths` completion-oracle lock returning `ERR_ORACLE_LOCKED` before any disk write.
  - External `effective_scratch_dir(ctx)` (`@scratch/...`) for overflow logs, backups, and checkpoints so zero untracked files pollute `workspace_root`; `read_file` supports reading `@scratch/...` slices.
  - Untrusted output framing via `format_tool_observation()` (`<tool_observation untrusted_data="true">`).
- **Connection Layer (`hooks.py`, `protocol.py`, `profile.py`, `registry.py`):**
  - `HookRegistry` (`pre_tool`, `post_edit`) + `run_post_edit_sensors()` across all mutating tools.
  - 3-mode `ToolProtocolAdapter` (`native`, `grammar_json` with JSON Schema + schema-constrained GBNF grammar, `xml_tags`).
  - Data-driven `ToolProfile` (`ModelProfile` alias preserved) with zero hardcoded model-family string branches and `tool_schema_hash` drift detection (`check_profile_drift`).

### 4.3 Scope Trim, Tool Bug Fixes & `ToolBinding` Connectivity (`v0.5`)
- **Boundary cleanup:** Removed loop-level concerns from `hivo/tools/` (`HookRegistry.pre_complete`, `classify_failure_bucket`, `compute_error_signature`, `compaction_trigger_tokens`, `thinking_policy`, `quantization_or_provider`), keeping `ToolProfile.from_dict()` tolerant of unknown YAML keys.
- **Tool ergonomics & safety hardening:**
  - `parse_anchor()` accepts forgiving 2B anchor variants (`"42:a3"`, `"L42:a3"`, `"42:a3| ..."`) while rejecting malformed hashes.
  - `list_files` and `search_code` support recursive `**/` globs consistently across `rg` and pure-Python search; `search_code` enables `--hidden` (with `!.git/**`) plus optional `context_lines` (`0..5`) rendered via `format_hashline_range()`.
  - `run_command` inspects `--flag=value` RHS tokens, bare secret filenames, and `git <rev>:<path>` arguments against workspace confinement and `is_secret_path()`.
  - `write_file` and all `edit_strategies.py` tools return `data.updated_window` Hashlines; `edit_unified_diff` tolerates mismatched hunk header counts, enforces monotonic `min_search_idx`, and defaults trailing newline on edits to 0-line files.
  - `code_intel` emits `end_anchor`, extracts top-level Python variables, falls back to regex extraction on Python `SyntaxError`, and tracks `{}` brace depth for `end_line`/`end_anchor` in brace-delimited languages.
  - `checkpoint` skips symlinked files/dirs and streams 64 KiB file chunks for hashing and blob copies.
- **Schema-driven connectivity:**
  - `build_gbnf_grammar()` emits exact per-tool `args_<idx>` rules constrained to schema property keys, required fields, enums, integers, booleans, arrays, and nested objects.
  - `ToolProtocolAdapter` supports JSON arrays of tool calls in `_parse_grammar_json` and adds `execute_and_format()`.
  - `registry.py` exposes `ToolBinding`, `create_tool_binding()`, and `ToolBinding.spawn_worker_binding(packet, ...)` wiring `dispatch_worker` packets directly into tightly fenced `coder_worker` bindings.

---

## 5. Revision Log

| Version | Date | Summary |
| :--- | :--- | :--- |
| `v0.1` | 2026-11-26 | Initial baseline capturing asymmetric 27B/2B tool catalog (Must-Add / Good-to-Have / Do-Not-Add), Global Base + Specific Profile architecture, `ToolContext`, and the 5 unit-level tool contracts. |
| `v0.2` | 2026-11-26 | Added Legacy Tool Retirement & Isolation Policy (2 must-fold overlaps, 5 isolated/retired tools, and 3 anti-leakage/quarantine rules). |
| `v0.3` | 2026-11-26 | Implemented all 10 v1 Core Tool Units in standalone `hivo/tools/` package and verified with standalone pure-Python unit test suite (`tests/test_tools_*.py`). |
| `v0.4` | 2026-11-26 | Upgraded `hivo/tools/` and `tool_rules.md` with swappable edit strategies, `code_intel`, `checkpoint`, `HookRegistry` + post-edit sensors, secret/oracle locks, external `@scratch/` storage, 3-mode `ToolProtocolAdapter`, `ToolProfile` + drift fingerprinting, and `error_code` taxonomy. |
| `v0.5` | 2026-11-26 | Removed non-tool harness scope (`pre_complete`, loop telemetry/knobs), renamed `ToolProfile`, fixed edge cases across Hashline anchors, `**/` globs/`context_lines`, command path/secret validation, `updated_window` + relaxed unified diff counts, `code_intel` AST fallback + brace tracking, streaming symlink-safe checkpoints, and added schema-constrained GBNF + `ToolBinding` connectivity. |
