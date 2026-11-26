# R_UPDATE_010 — Standalone framework-free tool layer (`hivo/tools/`) and `ToolBinding` connectivity

## A. Update Identification

- **Update ID:** R_UPDATE_010
- **Date and timezone:** 2026-11-26; Africa/Cairo (UTC+02:00)
- **Title:** Standalone framework-free tool layer (`hivo/tools/`) and `ToolBinding` connectivity
- **Status and verified scope:** Completed for standalone offline tool-unit and controlled multi-role connectivity scope; **live-model execution and `mini.py` runtime integration are unverified / out of scope** for this foundational PR.
- **Branch:** `feat/hivo-tools`
- **Actual base revision:** `3c870a64728316c94b581ea98aacec12dc77706e` (`upstream/main` on `abdoabozena7/mini_hivo`), established via `git fetch upstream main` and `git rev-parse upstream/main`.
- **Tested source revision/hashes:** Base `3c870a64728316c94b581ea98aacec12dc77706e` plus the new standalone files under `hivo/tools/`, `tests/test_tools_*.py`, `tool_rules.md`, and `updates/R_UPDATE_010.md`. Zero tracked repository files modified.
- **Containing commit / PR:** Recorded in Git history and upstream PR metadata on `abdoabozena7/mini_hivo` upon publication.
- **Related issue/experiment:** Not applicable (foundational tool-layer architecture defined in [tool_rules.md](../tool_rules.md)).
- **Scope:** Adds a custom, framework-free Python tool subsystem (`hivo/tools/`), design specification (`tool_rules.md` v0.5), and standalone unit + controlled functional connectivity tests (`tests/test_tools_*.py`). Intentionally leaves `mini.py`, `hivo/__init__.py`, and existing runtime modules untouched.

## B. Original Problem

- **Original request to Mini Hivo:** Not applicable to a single runtime failure trace; this update addresses an architectural design requirement to establish a clean, testable, 2B-friendly tool layer and tool connectivity boundary for an asymmetric Orchestrator (large cloud model) + Worker (small local model, e.g., 2B) setup without adding external agent frameworks or mutating legacy `mini.py` prematurely.
- **Expected behavior:**
  - Every tool unit is role-agnostic, enforces a uniform 6-key JSON-serializable envelope (`{ok, data, error, error_code, hint, truncated}`), validates arguments fail-closed, confines paths inside `workspace_root` / `allowed_paths`, blocks secrets and `protected_paths`, and avoids polluting `workspace_root` with scratch/backup/checkpoint artifacts.
  - Small-model (`slm_safe`) tools expose strictly flat parameter schemas, forgiving Hashline anchors, bounded Hashline windows (`updated_window`), and deterministic schema export/GBNF grammar generation.
  - Role allowlists, `ToolContext`, `ToolProtocolAdapter` (`native`, `grammar_json`, `xml_tags`), `ToolProfile`, and `dispatch_worker` packets compose cleanly through `ToolBinding` with least-privilege worker fencing.
- **Observed behavior (before this update):** Tool logic lived inline inside `mini.py` coupled to loop/runtime globals, with overlapping/legacy tool definitions, no standalone `hivo/tools/` package, no swappable edit-strategy layer, no schema-constrained GBNF adapter, and no spawn-time `ToolBinding` bridging orchestrator dispatch packets to fenced worker contexts.
- **Execution evidence:** Verified upstream baseline via `git ls-tree --name-only upstream/main updates/ hivo/ tests/ tool_rules.md` on `3c870a64728316c94b581ea98aacec12dc77706e`; `hivo/tools/` and `tool_rules.md` did not exist, and `updates/` contained `R_UPDATE_002.md` through `R_UPDATE_009.md`.
- **Failure boundary:** Pre-existing tools could not be unit-tested, composed per model profile, or serialized across `native` / `grammar_json` / `xml_tags` protocols in isolation from `mini.py`.
- **Reproduction before the change:** Importing `hivo.tools` on `3c870a64728316c94b581ea98aacec12dc77706e` raised `ModuleNotFoundError` because no standalone `hivo/tools/` package existed.

## C. Why the Update Was Necessary

Small local workers (2B–3B) degrade sharply when exposed to large, overlapping, or deeply nested tool schemas, strict exact-whitespace diff formats, or unbounded tool outputs. Building and verifying a standalone, strictly scoped tool package before wiring it into the runtime loop prevents regressions in `mini.py`, isolates tool contracts from loop/orchestration churn, and enables deterministic offline verification of security boundaries, edit formats, protocol parsing, and worker fencing.

## D. Root Cause Analysis

Because this is an additive architectural module rather than a regression patch on `mini.py`, the root structural gaps and edge-case bugs resolved during hardening are:

| Finding | Classification | Supporting evidence | Remaining uncertainty |
|---|---|---|---|
| Legacy tools were embedded in `mini.py` without role-agnostic unit boundaries or standalone allowlist composition | Proven observation | Upstream base `3c870a64728316c94b581ea98aacec12dc77706e` lacked `hivo/tools/` | Wiring into `mini.py` is deferred to a subsequent PR |
| Overlapping/verbose tool interfaces and loop-level concerns mixed into tool definitions complicate small-model tool selection and testing | Proven observation | Documented in [tool_rules.md](../tool_rules.md) | Live 27B/2B accuracy benchmarks are not yet run against this package |
| Unconstrained `object` rules in GBNF, strict hunk arithmetic, non-recursive `fnmatch`, and uninspected `--flag=path` / `git <rev>:<path>` tokens create avoidable failure/security modes at the tool boundary | Proven cause (caught during v0.5 hardening audit) | Covered by [test_tools_protocol_and_profile.py](../tests/test_tools_protocol_and_profile.py), [test_tools_edit_engine.py](../tests/test_tools_edit_engine.py), [test_tools_fs_read.py](../tests/test_tools_fs_read.py), [test_tools_exec_and_orch.py](../tests/test_tools_exec_and_orch.py) | OS-level symlink tests skipped on unprivileged Windows (`WinError 1314`) |
| Rapid same-second edit → test → rollback → test on a same-byte-length `.py` file loaded stale `__pycache__/*.pyc` bytecode because `(int(mtime), size)` matched | Proven cause (observed in `test_tools_connectivity_e2e.py` on `upstream/main`) | Fixed via `PYTHONDONTWRITEBYTECODE="1"` in `exec_tool.py::build_sanitized_env()` and `_evict_pycache_for_python_file()` in `checkpoint_tool.py`; 3/3 consecutive runs passed | External non-Python caches are not managed by `checkpoint` |

## E. What Changed

All files below are **new additions** relative to `upstream/main` (`3c870a64728316c94b581ea98aacec12dc77706e`); zero existing tracked files were modified.

| File / symbol | Before behavior | Implementation change | After behavior | Evidence / test |
|---|---|---|---|---|
| [tool_rules.md](../tool_rules.md) | Absent | Added v0.5 specification covering asymmetric role profiles, legacy quarantine rules, 5 unit contracts, edit strategies, and `ToolBinding` connectivity | Self-contained specification aligned with `hivo/tools/` | Reviewed directly against code |
| [hivo/tools/base.py](../hivo/tools/base.py) | Absent | Added `ToolContext`, `ToolSpec`, 6-key `ok_result`/`err_result`, strict schema validator, workspace/fence/secret/protected-path guards, forgiving `parse_anchor()`, atomic writes, syntax checks (`.py`/`.json`/`.js`), `.gitignore` matcher, external `effective_scratch_dir()`, and `format_tool_observation()` | Role-agnostic fail-closed foundation with untrusted observation framing | [test_tools_base_and_registry.py](../tests/test_tools_base_and_registry.py) |
| [hivo/tools/fs_read.py](../hivo/tools/fs_read.py) | Absent | Added `read_file` (Hashlines + `@scratch/...` slices), `list_files`, and `search_code` (`rg` + pure-Python fallback, `**/` globs, `--hidden` + `!.git/**`, optional `context_lines` 0–5) | Bounded, deterministic discovery with parity across `rg` and pure-Python search | [test_tools_fs_read.py](../tests/test_tools_fs_read.py) |
| [hivo/tools/fs_write.py](../hivo/tools/fs_write.py) | Absent | Added Hashline `edit_file`, `write_file` (with CRLF preservation + `updated_window` centered on syntax error when present), and `delete_file` | Atomic mutations with refreshed Hashline windows and post-edit diagnostics | [test_tools_fs_write.py](../tests/test_tools_fs_write.py) |
| [hivo/tools/edit_strategies.py](../hivo/tools/edit_strategies.py) | Absent | Added swappable `edit_search_replace`, `edit_unified_diff` (relaxed hunk header counts, monotonic `min_search_idx`, empty-file newline default), and `edit_line_range` sharing `_save_and_sense(..., updated_window)` | Calibrated edit strategies selectable per `ToolProfile` without overlap | [test_tools_edit_engine.py](../tests/test_tools_edit_engine.py) |
| [hivo/tools/exec_tool.py](../hivo/tools/exec_tool.py) | Absent | Added `run_command` with allowlist, unquoted shell-operator guard, `--flag=value` & `git <rev>:<path>` confinement/secret checks, scrubbed non-interactive env (including `PYTHONDONTWRITEBYTECODE=1`), `stdin=DEVNULL`, external `@scratch/` overflow logs, and process-tree timeout kill | Safe non-interactive command execution with clean workspace and no stale `.pyc` writes | [test_tools_exec_and_orch.py](../tests/test_tools_exec_and_orch.py) |
| [hivo/tools/code_intel.py](../hivo/tools/code_intel.py) | Absent | Added `code_intel` (`repo_map`, `outline`, `find_symbol`, `find_references`) with Python AST + top-level variables + `SyntaxError` regex fallback, `end_anchor`, and brace-depth `end_line` tracking | Compact structural navigation across Python and brace-delimited languages | [test_tools_intel_checkpoint_hooks.py](../tests/test_tools_intel_checkpoint_hooks.py) |
| [hivo/tools/checkpoint_tool.py](../hivo/tools/checkpoint_tool.py) | Absent | Added `checkpoint` (`create`, `rollback`, `list`) using external `@scratch/` content-addressed blobs, 64 KiB streaming hashing/copies, symlink skipping, stale `__pycache__/*.pyc` eviction on rollback, tree-hash verification, and `protected_paths` pre-checks | Clean 1-step deterministic workspace rollback without `.hivo/` clutter or stale bytecode | [test_tools_intel_checkpoint_hooks.py](../tests/test_tools_intel_checkpoint_hooks.py), [test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py) |
| [hivo/tools/hooks.py](../hivo/tools/hooks.py) | Absent | Added `HookRegistry` (`pre_tool`, `post_edit`) and `run_post_edit_sensors()` | Deterministic pre-tool policy gates and post-edit static diagnostics | [test_tools_intel_checkpoint_hooks.py](../tests/test_tools_intel_checkpoint_hooks.py) |
| [hivo/tools/orchestration.py](../hivo/tools/orchestration.py) | Absent | Added `PlanState`, `update_plan`, `dispatch_worker`, and `ask_user` | Orchestrator-only control tools decoupled from worker profiles | [test_tools_exec_and_orch.py](../tests/test_tools_exec_and_orch.py) |
| [hivo/tools/profile.py](../hivo/tools/profile.py) | Absent | Added `ToolProfile` (`ModelProfile` alias), YAML persistence, `compute_tool_schema_hash()`, `stamp_profile_fingerprint()`, and `check_profile_drift()` | Zero model-name branches; schema-hash drift detection | [test_tools_protocol_and_profile.py](../tests/test_tools_protocol_and_profile.py) |
| [hivo/tools/protocol.py](../hivo/tools/protocol.py) | Absent | Added `ParsedToolCall`, `build_grammar_json_schema()`, schema-constrained `build_gbnf_grammar()`, and `ToolProtocolAdapter` (`native`, `grammar_json` including JSON arrays, `xml_tags`, `execute_and_format()`) | Protocol-agnostic tool rendering, parsing, execution, and untrusted framing | [test_tools_protocol_and_profile.py](../tests/test_tools_protocol_and_profile.py) |
| [hivo/tools/registry.py](../hivo/tools/registry.py) & [hivo/tools/__init__.py](../hivo/tools/__init__.py) | Absent | Added `ALL_TOOLS`, `ROLE_PROFILES`, `build_profile_tools()`, `execute_tool()`, `ToolBinding`, `create_tool_binding()`, and `ToolBinding.spawn_worker_binding()` | Spawn-time static binding and fenced orchestrator-to-worker handoff | [test_tools_base_and_registry.py](../tests/test_tools_base_and_registry.py), [test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py) |
| `tests/test_tools_*.py` (8 files) | Absent | Added unit tests and controlled E2E connectivity test covering all 15 tools, protocols, profiles, hooks, security locks, GBNF integrity, and multi-role handoff | Automated offline regression and controlled functional coverage | Sections G and H below |

## F. How the Fix Works

1. **Static Spawn-Time Binding (`registry.py`):** `create_tool_binding(role, context=..., profile=..., protocol=...)` composes a fixed `ToolBinding` pairing a role allowlist (`orchestrator`, `coder_worker`, `research_worker`, `verifier`), immutable `ToolContext`, `ToolProtocolAdapter`, and optional `ToolProfile`. Tool schemas are never mutated mid-loop and serialize deterministically (`schema_hash()`).
2. **Protocol-to-Execution Pipeline (`protocol.py` -> `registry.py` -> `base.py`):** `ToolBinding.render_tools()` exports OpenAI-compatible tool specs (`native`), JSON Schema + property-constrained GBNF (`grammar_json`), or XML tool prompts (`xml_tags`). Model responses pass through `adapter.parse_response()` -> `execute_tool()` (allowlist check -> recursive schema validation -> `HookRegistry.run_pre_tool()` -> handler) -> `format_tool_observation()` (`<tool_observation untrusted_data="true">`).
3. **Fenced Worker Handoff (`orchestration.py` -> `registry.py`):** When the orchestrator invokes `dispatch_worker`, target paths are validated inside `workspace_root` and normalized into a task packet. `ToolBinding.spawn_worker_binding(packet, worker_profile=..., max_read_lines=...)` constructs a `coder_worker` binding whose `ToolContext` narrows `allowed_paths` strictly to `packet["target_files"]`, caps `max_read_lines`, clears `allowed_commands`, and strips `plan_store`, `worker_dispatcher`, and `user_prompter`.
4. **Post-Edit Feedback & Rollback (`fs_write.py`, `edit_strategies.py`, `hooks.py`, `checkpoint_tool.py`, `exec_tool.py`):** Every file mutation verifies `protected_paths` and `is_secret_path()` before disk I/O, writes atomically via temp file + `os.replace`, executes `run_post_edit_sensors()`, and returns a bounded Hashline `updated_window` for immediate self-correction. `checkpoint` snapshots and rolls back workspace files using external `@scratch/` blobs with SHA-256 tree-hash verification and evicts stale `__pycache__/*.pyc` entries for restored/deleted `.py` files, while `run_command` sets `PYTHONDONTWRITEBYTECODE=1`.

## G. Functional Verification

| Scenario / test | Verification class | Scripted/mocked boundaries versus real components | Expected behavior and oracle | Actual observed artifact/state | Result | Evidence |
|---|---|---|---|---|---|---|
| Full Orchestrator -> Worker -> Verifier -> Rollback lifecycle (`test_orchestrator_worker_verifier_rollback_lifecycle`) | Controlled functional | Scripted tool-call payloads in `native`, `grammar_json`, and `xml_tags` formats; **real** filesystem workspace, `code_intel`, `checkpoint`, `dispatch_worker`, `spawn_worker_binding`, `read_file`, `edit_file`, `HookRegistry`, post-edit syntax sensor, and `run_command` executing real `unittest` subprocess | Symbol located with `end_anchor`; external snapshot keeps workspace free of `.hivo/`; worker fenced to `src/calc.py` rejects `src/other.py`, `.env`, and `run_command`; broken edit triggers `syntax_ok=False` + refreshed `updated_window`; fixed edit passes real `unittest` (`exit_code=0`); rollback restores exact original bytes and tree hash and causes `unittest` to fail again (`exit_code!=0`) | Observed `src/calc.py` disk contents updated to `return a + b`, real `unittest` subprocess exited `0` (`OK`), rollback returned `exact_match=True` matching `orig_tree_hash`, original bytes restored verbatim, and post-rollback `unittest` exited non-zero across 3/3 consecutive runs | Pass | [test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py) |
| Unauthorized/negative cases inside E2E & unit tests | Controlled functional / unit | Real `ToolContext` path/secret/oracle/command guards against real temporary files and subprocess validation | Worker read of `src/other.py` and `.env` denied (`ERR_PATH_SECURITY`); worker `run_command` and verifier `edit_file` denied (`ERR_TOOL_SCHEMA`); verifier `python --cfg=.env` denied (`ERR_COMMAND_REFUSED`); all mutators blocked on `protected_paths` (`ERR_ORACLE_LOCKED`) | All unauthorized calls failed closed with expected `error_code` and zero disk mutation | Pass | [test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py), [test_tools_edit_engine.py](../tests/test_tools_edit_engine.py), [test_tools_exec_and_orch.py](../tests/test_tools_exec_and_orch.py) |

- **Run date, ID and source identity:** 2026-11-26 (fresh offline runs on branch `feat/hivo-tools` based on `upstream/main` `3c870a64728316c94b581ea98aacec12dc77706e`).
- **Fixture/authority/policy:** Temporary directories (`tempfile.TemporaryDirectory`) with `protected_paths=("tests/**",)`, `block_secret_files=True`, and `allowed_paths=("src/calc.py",)` on the spawned worker.
- **Exact reproduction command:** `python -m unittest discover -s tests -p "test_tools_connectivity_e2e.py" -v` (observed: `Ran 1 test in 0.405s` and `Ran 1 test in 0.389s`, `OK`, exit code `0`).
- **Verification method:** Independent disk byte readback, SHA-256 tree-hash equality, real subprocess `unittest` exit code before and after rollback, and observation envelope inspection.
- **Before versus after:** Before this update, no standalone `hivo.tools` package or `ToolBinding` handoff existed; after this update, the full multi-role tool flow executes end-to-end offline with independent filesystem and subprocess verification.
- **Known verification gaps:** Scripted model responses do not prove live LLM tool-calling accuracy; Windows symlink security tests could not execute without symlink privilege (`WinError 1314`).

**Live-model completion:** **Not run / unverified** — intentionally deferred until a follow-up PR wires `hivo/tools/` into the live agent loop and obtains explicit approval for live-model runs.

## H. Additional Successful Tests

| Suite / verification class | Fresh or historical; source revision | Exact command | Tests run | Passed | Failed / errors | Skipped | Exit / result | Relevance | Evidence |
|---|---|---|---:|---:|---:|---:|---|---|---|
| Standalone tool suite (unit + controlled functional) | Fresh (2026-11-26); `feat/hivo-tools` over `3c870a6` | `python -m unittest discover -s tests -p "test_tools_*.py" -v` | 37 | 35 | 0 / 0 | 2 | Exit 0 (`OK (skipped=2)`) | Covers all 15 tools, GBNF referential integrity, profiles, hooks, security guards, and controlled E2E connectivity | [tests/test_tools_base_and_registry.py](../tests/test_tools_base_and_registry.py) et al. (8 files) |
| Offline core verification integrity regression | Fresh (2026-11-26); `feat/hivo-tools` over `3c870a6` | `python -m unittest discover -s tests -p "test_verification_outcome_integrity.py"` | 31 | 31 | 0 / 0 | 0 | Exit 0 (`OK`) | Confirms zero collateral impact on existing verification integrity logic | [tests/test_verification_outcome_integrity.py](../tests/test_verification_outcome_integrity.py) |
| Offline core execution contracts regression | Fresh (2026-11-26); `feat/hivo-tools` over `3c870a6` | `python -m unittest discover -s tests -p "test_execution_contracts.py"` | 36 | 36 | 0 / 0 | 0 | Exit 0 (`OK`) | Confirms zero collateral impact on approved plan execution contracts | [tests/test_execution_contracts.py](../tests/test_execution_contracts.py) |
| Offline structured worker contract regression | Fresh (2026-11-26); `feat/hivo-tools` over `3c870a6` | `python -m unittest discover -s tests -p "test_structured_worker_contract.py"` | 8 | 8 | 0 / 0 | 0 | Exit 0 (`OK`) | Confirms zero collateral impact on structured worker contract parsing | [tests/test_structured_worker_contract.py](../tests/test_structured_worker_contract.py) |

Note: `test_tools_*.py` includes `test_tools_connectivity_e2e.py` (1 test already shown in Section G); counts above are per-command observations and are not summed across overlapping invocations.

## I. Regression and Compatibility Impact

- **Potentially affected functionality/dependencies:** None in the active legacy runtime; `hivo/tools/` is purely additive and is not imported by `mini.py` or `hivo/__init__.py`.
- **Preserved behavior:** Existing offline regression suites (`test_verification_outcome_integrity.py` 31/31, `test_execution_contracts.py` 36/36, `test_structured_worker_contract.py` 8/8) all passed with 0 failures and 0 errors, and `git diff` against `3c870a6` shows zero changes to tracked files.
- **Baseline comparison:** Verified `git status --short` shows only new untracked files (`hivo/tools/`, `tests/test_tools_*.py`, `tool_rules.md`, `updates/R_UPDATE_010.md`).
- **Failures/errors:** 0 failures and 0 errors in final runs. (An initial run of `test_tools_connectivity_e2e.py` surfaced same-second `.pyc` cache staleness on rollback, which was fixed in `exec_tool.py` and `checkpoint_tool.py` and re-verified 3/3 times.)
- **Skipped/excluded/interrupted checks:**
  - 2 skipped tests in `test_tools_*.py`: `test_workspace_confinement_and_symlink_escape` ([test_tools_base_and_registry.py](../tests/test_tools_base_and_registry.py)) and `test_checkpoint_skips_symlinks` ([test_tools_intel_checkpoint_hooks.py](../tests/test_tools_intel_checkpoint_hooks.py)), both skipped because unprivileged Windows raised `WinError 1314` on `os.symlink`.
  - Broad `unittest discover -s tests` was intentionally not run because `AGENTS.md` documents that parts of the broader suite (such as `test_requirement_clarification.py`) can invoke a live model provider.
- **Untested/uncertain areas:** Live-model invocation with 27B/2B models, external `llama.cpp` runtime GBNF parser execution against `build_gbnf_grammar()` output, and symlink escape/skip paths on POSIX or Windows with Developer Mode enabled.
- **Environment versus implementation:** The 2 skips are host OS privilege constraints (`WinError 1314`), not tool implementation errors.

## J. Overall Impact

Establishes a clean, framework-free, independently verified `hivo/tools/` layer on current `upstream/main` with strict allowlist composition, hardened path/secret/oracle/command guards, swappable edit strategies with Hashline `updated_window` feedback, streaming symlink-safe external checkpoints with `.pyc` cache eviction, schema-constrained GBNF grammar generation, and `ToolBinding` connectivity from orchestrator dispatch packets to fenced worker bindings—without disturbing `mini.py` or introducing harness-loop scope creep.

## K. Remaining Limitations

- **Not wired into `mini.py` yet:** Runtime integration into Mini Hivo's agent loop is intentionally left for a separate PR.
- **Live-model execution unverified:** Controlled tests use scripted tool-call responses; live 27B/2B reliability and calibration benchmarks remain to be run once wired.
- **Windows symlink skips:** Two symlink security tests (`test_workspace_confinement_and_symlink_escape`, `test_checkpoint_skips_symlinks`) skipped on unprivileged Windows (`WinError 1314`) and should be run on Linux/CI or Windows with Developer Mode enabled.
- **GBNF runtime parser check:** Unit tests prove referential integrity and presence of all required keys/enums across all 15 tools, but external `llama.cpp` parser validation has not been executed in this environment.

## L. Evidence and Reproduction

| Relative evidence link | Fresh / historical / sanitized derivative | Source/run identity | What it proves | What it does not prove |
|---|---|---|---|---|
| [tests/test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py) | Fresh controlled functional test | `feat/hivo-tools` (base `3c870a6`) | End-to-end multi-role `ToolBinding` handoff, fencing, post-edit self-correction, real `unittest` execution, and exact checkpoint rollback | Live LLM tool-calling reliability |
| [tests/test_tools_protocol_and_profile.py](../tests/test_tools_protocol_and_profile.py) | Fresh unit test | `feat/hivo-tools` (base `3c870a6`) | 3-mode protocol parsing/formatting, `ToolProfile` YAML drift checks, zero model-family branches, and GBNF referential integrity | External `llama.cpp` C++ GBNF execution |
| [tool_rules.md](../tool_rules.md) | Fresh living specification (`v0.5`) | `feat/hivo-tools` (base `3c870a6`) | Design contracts, role allowlists, legacy isolation policy, and revision history | Runtime execution by itself |

```powershell
# Run standalone controlled E2E connectivity test (from repository root)
python -m unittest discover -s tests -p "test_tools_connectivity_e2e.py" -v

# Run full standalone tool unit + controlled functional suite
python -m unittest discover -s tests -p "test_tools_*.py" -v

# Run offline core regression checks
python -m unittest discover -s tests -p "test_verification_outcome_integrity.py"
python -m unittest discover -s tests -p "test_execution_contracts.py"
python -m unittest discover -s tests -p "test_structured_worker_contract.py"
```

- **Original preservation:** No raw live-model runs or private transcripts were generated for this offline update.
- **Sanitization:** Checked all new files for personal absolute paths, credentials, and external local checklist references.
- **Hash policy:** Commit SHA is recorded in Git history upon authorized commit.
- **Actual staged-blob verification:** Validated with `git diff --cached --check` prior to commit.
- **Reproduction limits:** Symlink tests require POSIX or Windows symlink privileges.

## M. Summary for the Team

**Proposed PR title:** `feat(tools): add standalone framework-free hivo/tools layer and ToolBinding connectivity`

**Why needed:** Provide a clean, flat-schema, least-privilege tool subsystem designed for an asymmetric Orchestrator + small-model Worker architecture—verifiable in isolation without external frameworks or premature churn in `mini.py`.

**What changed / what was fixed:**
- Added standalone `hivo/tools/` package (15 core/strategy tools across `base.py`, `fs_read.py`, `fs_write.py`, `edit_strategies.py`, `exec_tool.py`, `code_intel.py`, `checkpoint_tool.py`, `hooks.py`, `orchestration.py`, `profile.py`, `protocol.py`, `registry.py`, `__init__.py`).
- Hardened tool ergonomics and security: forgiving Hashline `parse_anchor()`, recursive `**/` globs and `context_lines` in `search_code` with `--hidden`/`!.git/**`, `--flag=path` and `git <rev>:<path>` secret/confinement checks + `PYTHONDONTWRITEBYTECODE=1` in `run_command`, `updated_window` feedback across all mutators, relaxed unified-diff hunk count parsing with monotonic hunk search, `code_intel` Python `SyntaxError` regex fallback + brace-depth `end_line`/`end_anchor`, and 64 KiB streaming symlink-safe external checkpoints with stale `.pyc` eviction on rollback.
- Connected tools via schema-constrained `build_gbnf_grammar()`, 3-mode `ToolProtocolAdapter` (`native`, `grammar_json`, `xml_tags`), `ToolProfile` YAML drift detection, and `ToolBinding` / `create_tool_binding()` / `spawn_worker_binding()` bridging `dispatch_worker` packets to fenced `coder_worker` bindings.
- Added [tool_rules.md](../tool_rules.md) (`v0.5`), [updates/R_UPDATE_010.md](../updates/R_UPDATE_010.md), and 8 test modules under `tests/test_tools_*.py`. Left `mini.py` and `hivo/__init__.py` untouched.

**Functional verification:** Controlled end-to-end test ([tests/test_tools_connectivity_e2e.py](../tests/test_tools_connectivity_e2e.py)) passed (`1/1`, `exit 0`, 3/3 consecutive runs), verifying Orchestrator (`native`) -> `code_intel` + `checkpoint(create)` -> `dispatch_worker` -> `spawn_worker_binding` -> fenced Coder Worker (`grammar_json`) edit + post-edit syntax feedback + self-correction -> Verifier (`xml_tags`) running a real `unittest` subprocess (`exit_code=0`) -> `checkpoint(rollback)` restoring exact original bytes and tree hash. Live-model completion is **not run / unverified**.

**Additional successful tests:**
- `tests/test_tools_*.py`: 37 ran, 35 passed, 2 skipped (Windows `WinError 1314` symlink privilege), 0 failures (`exit 0`).
- Offline core regressions on `upstream/main` (`3c870a6`): `test_verification_outcome_integrity.py` (31/31), `test_execution_contracts.py` (36/36), `test_structured_worker_contract.py` (8/8) — all `exit 0`.

**Remaining issues:** Two symlink tests skipped on unprivileged Windows; live-model verification and `mini.py` loop wiring are deferred to a follow-up PR; external `llama.cpp` GBNF runtime validation not yet run.

**Publication state:** Authorized for publication on branch `feat/hivo-tools` (based on `upstream/main` `3c870a6`) to `origin` (`kareem232003/mini_hivo.git`) with PR targeting `abdoabozena7/mini_hivo:main`; containing commit SHA is recorded in Git history.
