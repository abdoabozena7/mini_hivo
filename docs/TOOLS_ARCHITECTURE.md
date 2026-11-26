# Tools Subsystem Architecture (`docs/TOOLS_ARCHITECTURE.md`)

> - **Status:** Living current-state documentation (`hivo/tools/`)
> - **Governing Rules:** [`../dev_rules/tool_rules.md`](../dev_rules/tool_rules.md) *(prescriptive contracts & guardrails)*
> - **Historical Origin:** Introduced in PR #5 (`updates/R_UPDATE_010.md`) as a standalone, framework-free Python package with zero imports from `mini.py`.

---

## 1. Package Module Inventory (`hivo/tools/`)

| Module | Responsibility | Key Exports / Symbols |
| :--- | :--- | :--- |
| [`base.py`](../hivo/tools/base.py) | Core primitives, immutable `ToolContext`, `ToolSpec`, 6-key envelope helpers, strict recursive arg validation, path/secret/oracle confinement, safe UTF-8/CRLF/binary I/O, atomic temp-file writes, inline syntax checks (`.py`, `.json`, `.js`), `.gitignore` matcher, Hashline helpers, and untrusted observation framing | `ToolContext`, `ToolSpec`, `ok_result`, `err_result`, `serialize_envelope`, `ERR_*` (10 codes), `line_hash`, `format_hashline`, `is_secret_path`, `is_protected_path`, `effective_scratch_dir`, `format_tool_observation` |
| [`fs_read.py`](../hivo/tools/fs_read.py) | Bounded read-only workspace inspection | `read_file` (`@scratch/...` aware, Hashline-prefixed), `list_files` (`.gitignore`-aware, recursive `**/` globs), `search_code` (`rg` + pure-Python fallback, `--hidden` excluding `.git/**`, optional `context_lines` `0..5`) |
| [`fs_write.py`](../hivo/tools/fs_write.py) | Atomic file mutations with inline syntax verification | `edit_file` (default Hashline-anchored editor), `write_file` (`overwrite=False` default), `delete_file` (single regular file only) |
| [`edit_strategies.py`](../hivo/tools/edit_strategies.py) | Swappable edit engines for profile calibration & benchmarking | `EDIT_STRATEGY_SPECS`: `edit_search_replace`, `edit_unified_diff` (relaxed hunk count tolerance, monotonic search index), `edit_line_range` — all emit refreshed `updated_window` Hashlines |
| [`code_intel.py`](../hivo/tools/code_intel.py) | Structural navigation & symbol outlines | `code_intel` (`repo_map`, `outline`, `find_symbol`, `find_references`) using Python `ast` (with regex fallback on `SyntaxError`) and `{}` brace-depth tracking for JS/TS/Go/Rust/C/C++/Java, emitting `start_anchor`/`end_anchor` |
| [`exec_tool.py`](../hivo/tools/exec_tool.py) | Safe non-interactive command execution | `run_command`, `build_sanitized_env` — `stdin=DEVNULL`, unquoted shell-operator guard, path/secret checks across args/`--flag=value`/`git <rev>:<path>`, `timeout_sec` process-tree kill, separate `stdout`/`stderr`, head+tail truncation + `@scratch/` overflow offload |
| [`checkpoint_tool.py`](../hivo/tools/checkpoint_tool.py) | External content-addressed workspace snapshots & rollback | `checkpoint` (`create`, `restore`, `list`) stored under `@scratch/`, streaming 64 KiB SHA-256 hashing, symlink skipping, tree-hash verification, `protected_paths` safety |
| [`orchestration.py`](../hivo/tools/orchestration.py) | Orchestrator-only control tools | `PlanState`, `update_plan`, `dispatch_worker`, `ask_user` |
| [`hooks.py`](../hivo/tools/hooks.py) | Pre-tool and post-edit hook seams | `HookRegistry` (`pre_tool`, `post_edit`), `run_post_edit_sensors` |
| [`protocol.py`](../hivo/tools/protocol.py) | 3-mode model tool-call protocol adapter | `ToolProtocolAdapter` (`native`, `grammar_json`, `xml_tags`), `ParsedToolCall`, `build_grammar_json_schema`, `build_gbnf_grammar` (per-tool `args_<idx>` schema-constrained GBNF), `execute_and_format` |
| [`profile.py`](../hivo/tools/profile.py) | Data-driven tool profile config & drift fingerprinting | `ToolProfile` (`ModelProfile` alias), `ENGINE_VERSION`, `load_tool_profile`, `save_tool_profile`, `compute_tool_schema_hash`, `stamp_profile_fingerprint`, `check_profile_drift` (tolerant of unknown YAML keys, zero model-family string branches) |
| [`registry.py`](../hivo/tools/registry.py) | Strict allowlist registry, role profiles, schema export & `ToolBinding` | `ALL_TOOLS` / `CORE_TOOLS` (15 specs), `ROLE_PROFILES`, `build_profile_tools`, `ToolBinding`, `create_tool_binding`, `ToolBinding.spawn_worker_binding`, `export_openai_tools`, `serialize_openai_tools`, `execute_tool` |
| [`__init__.py`](../hivo/tools/__init__.py) | Public package surface | Re-exports all stable primitives, error codes, registry/binding APIs, protocol adapters, profiles, and hooks |

---

## 2. Core Data Contracts & Conventions

### 2.1 `ToolContext` Fields (`hivo/tools/base.py`)
Frozen per-execution dataclass supplied by the harness:
- **Confinement & Security:** `workspace_root: Path`, `allowed_paths: tuple[str, ...] | None = None`, `protected_paths: tuple[str, ...] = ()`, `block_secret_files: bool = True`, `allowed_commands: tuple[str, ...] | None = None`
- **Resource & Output Caps:** `max_read_lines: int = 250`, `max_output_chars: int = 16_000`, `max_list_entries: int = 200`, `max_search_matches: int = 50`, `timeout_sec: int = 30`, `scratch_dir: Path | None = None`
- **Hooks, Backups & Control Callbacks:** `enable_backups: bool = False`, `error_verbosity: Literal["detailed", "compact"] = "detailed"`, `hooks: Any | None = None`, `post_edit_commands: tuple[tuple[str, ...], ...] = ()`, `worker_dispatcher`, `plan_store`, `user_prompter`

### 2.2 6-Key Uniform Return Envelope & Error Taxonomy
Every tool returns:
```json
{
  "ok": true,
  "data": {},
  "error": null,
  "error_code": null,
  "hint": null,
  "truncated": false
}
```
Stable `error_code` constants (`hivo/tools/base.py`): `TOOL_SCHEMA_ERROR`, `EDIT_APPLY_ERROR`, `PATH_SECURITY_ERROR`, `ORACLE_LOCKED`, `COMMAND_REFUSED`, `COMMAND_TIMEOUT`, `NOT_FOUND`, `INVALID_TARGET`, `HOOK_BLOCKED`, `INFRA_ERROR`.

### 2.3 Hashline Anchor Specification
- `line_hash(line)` computes `blake2b(line.encode("utf-8"), digest_size=1).hexdigest()` (2 lowercase hex characters), rendered as `<line_num>:<hash>| <content>`.
- `parse_anchor()` accepts forgiving light-worker variants (`"42:a3"`, `"L42:a3"`, `"42:a3| ..."`) while rejecting invalid hashes.
- `"0:00"` is reserved exclusively for `edit_file(operation="insert_after", start_anchor="0:00")` to insert at the top of a file or populate an empty 0-line file.

### 2.4 Built-In Role Allowlist Profiles (`ROLE_PROFILES`)
- **`orchestrator`:** `read_file`, `list_files`, `search_code`, `code_intel`, `checkpoint`, `update_plan`, `dispatch_worker`, `ask_user` *(+ optional `run_command` via `include_run_command=True`; `ask_user` omitted when headless)*.
- **`coder_worker`:** `read_file`, `edit_file`, `write_file`, `code_intel` *(orchestration harness may narrow to 3 tools `read_file`, `edit_file`, `write_file` on pre-scoped dispatches; optional `delete_file` via `allow_delete=True`)*.
- **`research_worker`:** `read_file`, `list_files`, `search_code`, `code_intel`.
- **`verifier`:** `read_file`, `code_intel`, `run_command`.

### 2.5 Security & Scratch Isolation Defaults
- **Blocked secret paths** (`is_secret_path`, when `block_secret_files=True`): `.env`, `.env.*` *(except `.env.example`, `.env.sample`, `.env.template`)*, SSH keys (`id_rsa`, `id_ed25519`, `id_ecdsa`, `id_dsa`), `.netrc`, `.npmrc`, `.pypirc`, and `*.pem`/`*.key`/`*.p12`/`*.pfx`.
- **External `@scratch/` storage:** `effective_scratch_dir(ctx)` places overflow logs, backups, and checkpoints outside `workspace_root` so zero untracked artifacts pollute target repositories.
- **Untrusted observation framing:** `format_tool_observation()` wraps returned tool payloads in `<tool_observation untrusted_data="true">...</tool_observation>`.

---

## 3. Standalone Offline Test Suite

All tool contracts are verified offline (zero LLM calls) across 8 test modules:

```powershell
python -m unittest discover -s tests -p "test_tools_*.py" -v
```
