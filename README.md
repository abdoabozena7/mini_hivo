# El Samna El Balady — Mini Hivo Runtime

El Samna El Balady is our private development continuation of **Mini Hivo**, a local multi-agent coding system. It turns a supported user request into requirements, executable child missions, authorized file changes, independent verification, and an acceptance decision. The goal is reliable delivery of usable artifacts, not merely generated code or a successful process exit.

The source baseline was Kareem's integration PR [#1](https://github.com/abdoabozena7/mini_hivo/pull/1), commit `34a972a0b2feb80a31e06d0b93d6c22ca2961bc8`. Existing source attribution and research history are preserved. This continuation does not grant a new repository-wide open-source license.

**Current checkpoint:** the November 18, 2026 To-Do live campaign reached an **accepted, retained foundation child** in Run 7. Full To-Do application behavior and root acceptance have not been established.

- [Detailed repair report](updates/REPAIR_CYCLE_001.md)
- [Curated Run 7 evidence](evidence/repair-cycle-001/accepted-child-1.json)
- [Publication regression results](evidence/repair-cycle-001/publication-checks.json)
- [Historical experiment index](reports/INDEX.md) and [architecture checkpoint](docs/PROJECT_STATUS.md)
- [Original project guide](EL_SAMNA_EL_BALADY_PROJECT_GUIDE.pdf)

## Architecture: request to accepted output

1. **Host preflight** checks the selected local model and runtime readiness.
2. **Ingestion / Clarifier** retain source requirements and surface genuine blocking decisions.
3. **Project understanding / Specifier** distinguish new projects from existing repositories, gather applicable evidence, and build bounded project/task context.
4. **Coordinator** evaluates task size and decomposes work into sequential children with explicit dependencies. **MissionCompiler** defines each Worker's local target, prerequisites, and completion conditions.
5. **Builder** uses real workspace tools. Context Sufficiency and the Impact Contract must authorize mutation; a successful tool response alone does not establish task completion.
6. **Falsifier and deterministic verification** inspect the result and execute applicable checks, including syntax and Chromium verification. Actual requirements determine the browser profile.
7. **Repairer**, when required, performs bounded authorized edits followed by fresh verification. Failed or unauthorized work is not promoted to success.
8. **Impact audit and transaction acceptance** compare actual changes with the contract. Accepted artifacts are retained; failed transaction changes roll back. Parent integration must still establish the complete task's obligations.

| Code | Responsibility |
| --- | --- |
| `mini.py` | CLI, orchestration, roles, tool dispatch, browser wiring, transactions and acceptance |
| `hivo/project_understanding.py` | Project classification and bounded repository evidence |
| `hivo/context_sufficiency.py`, `hivo/semantic_evidence.py` | Context decisions and evidence acquisition |
| `hivo/impact_planning.py`, `hivo/execution_contracts.py`, `hivo/pre_mutation_impact.py` | Planning authority, approved scope and impact validation |
| `hivo/evidence.py`, `hivo/verification_routing.py` | Structured verification evidence and required routes |
| `hivo/verification_scope.py`, `hivo/verification.py`, `hivo/browser_checks.py` | Requirement-derived browser profiles and actual checks |
| `hivo/memory.py` | Project-local SQLite events, tasks and artifact records |
| `tests/` | Controlled functional, integration and regression tests |

These components are implemented; their presence does not establish universal live reliability. Optional research policies remain opt-in. The documented Run 7 command used defaults, not all optional policies together.

## Local setup (Windows / PowerShell)

Use Python 3.11 and a working local Ollama installation. Reuse an existing compatible virtual environment, model and Playwright browser if already installed. The following installation commands are for a new environment; they are not needed after every code update.

```powershell
Set-Location 'E:\MiniHivo\el-samna-el-balady'
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

In a separate terminal, start Ollama **only if it is not already running**:

```powershell
ollama serve
```

In your run terminal:

```powershell
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
ollama list
# Only if gemma4:e4b is absent (downloads model files):
# ollama pull gemma4:e4b
```

The validated campaign used `gemma4:e4b` for every model-backed role. No model substitution or cloud fallback was used. Node.js is useful for JavaScript syntax checks and is required for workflows invoking Node-based tools. Runtime checks still determine actual availability; do not bypass a failing preflight.

## Run with an isolated output workspace

Keep application output outside the source checkout. The included fixture is the unchanged To-Do benchmark prompt; its SHA256 is `2132536fd2df4a18c39f434dc43e4344034ed892c8640e94a98a103a82dd5b36`.

```powershell
Set-Location 'E:\MiniHivo\el-samna-el-balady'
$python = (Resolve-Path '.\.venv\Scripts\python.exe').Path
$run = Join-Path 'E:\MiniHivo\el-samna-local-tests' ('todo-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $run -ErrorAction Stop | Out-Null
New-Item -ItemType Directory -Path "$run\workspace", "$run\tmp" | Out-Null
Copy-Item '.\tests\fixtures\new_application_requirements.txt' "$run\prompt.txt"
Get-FileHash "$run\prompt.txt" -Algorithm SHA256
$env:TEMP = "$run\tmp"
$env:TMP = "$run\tmp"
$env:TMPDIR = "$run\tmp"
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:OLLAMA_BASE_URL = 'http://127.0.0.1:11434'
& $python -u -B .\mini.py --model gemma4:e4b --mode auto --no-bootstrap `
  --workspace "$run\workspace" --prompt-file "$run\prompt.txt" 2>&1 |
  Tee-Object -FilePath "$run\console.log"
$LASTEXITCODE | Set-Content "$run\exit-code.txt"
```

If reusing a different environment, set `$python` to that environment's interpreter. `--no-bootstrap` assumes dependencies are already installed; it does not skip model preflight or verification. This command starts real model inference and is an instruction for future use, not a claim that another run was performed during publication.

For an interactive request instead, run `& $python .\mini.py --model gemma4:e4b --workspace <fresh-path>` and use the actual CLI prompts.

### Output and diagnostics

- `$run/workspace/`: generated application files.
- `$run/console.log`: captured console output; `$run/exit-code.txt`: process result.
- `workspace/.agent_runs/*.jsonl`: native stage/model/tool trace.
- `workspace/.hivo/memory.sqlite3`: task, tool-event and artifact ledger.
- `workspace/.agent_evidence/`: screenshots and verification artifacts.
- `workspace/.agent_host_preflight.json`: preflight evidence.

A manual interruption is not a final runtime verdict. Do not infer successful root acceptance from a child PASS, clean page load, file existence or exit code. Preserve the full run directory locally for diagnosis; do not upload raw databases, transcripts or temporary workspaces by default.

## Architectural repairs preserved in this update

- **Project intent:** an empty workspace containing a construction request remains a new project even when feature requirements contain verbs such as delete/update. Existing-source and explicit repository-edit controls remain protected.
- **Mutation scope:** concrete controller/mission file assignments replace accidental goal-word targets. Hard outer boundaries and genuine required impacts remain enforced; repeated scope refusals terminate explicitly instead of masquerading as task-size problems.
- **Context and progress:** Workers receive observed creation state, retained context feedback and inspectable dependency information. Terminal insufficiency is bounded; available exact-file evidence can be returned without inventing authoritative API definitions.
- **Dependencies and rollback:** decomposition exposes explicit sibling dependencies and each next child receives fresh repository observations after commits or rollbacks.
- **Verification/recovery handoff:** actual failed verification can reach independent review without being relabeled PASS. Repairer scope failures remain terminal and roll back.
- **Browser authority:** receipt hashes and diagnostics cannot invent game requirements. HTML execution and explicit browser verification derive the same authorized profile; CSS execution is marked not applicable, never accepted as a passing receipt.

The [repair report](updates/REPAIR_CYCLE_001.md) explains original failures, intermediate regressions, exact fixes and test boundaries. [R_UPDATE_003](updates/R_UPDATE_003.md) preserves the earlier classification-only checkpoint; its original live-rerun-pending wording describes that historical point.

## Live-run history and Run 7 result

All runs used the fixed To-Do prompt. Raw evidence is preserved locally outside Git; the [curated evidence](evidence/repair-cycle-001/accepted-child-1.json) provides the portable checkpoint.

| Run | Observed result |
| --- | --- |
| 1 | Preflight passed, but empty new application was classified as existing; stopped before task creation. |
| 2 | Builder, Falsifier, browser and Repairer reached; impact acceptance failed and provisional files rolled back. |
| 3 | File assignment resolution regressed: semantic scope labels blocked writes; stopped before Falsifier. |
| 4 | Builder requested definitions of its absent outputs; evidence remained unavailable and context terminated without implementation. |
| 5 | Real HTML/CSS writes; missing out-of-scope JavaScript caused browser failure. Stopped for diagnosis. |
| 6 | Three writes and browser loading succeeded; independent Falsifier exposed a receipt-hash-induced false game profile. Repairer inspected files; stopped before an inappropriate repair. |
| 7 | First context check sufficient; three authorized files written, independently verified, impact-audited, committed and retained. Stopped during child 2 planning after the accepted-child milestone. |

**Run 7 proved:** real Builder → Falsifier → Chromium verification → passing impact audit → workspace transaction commit. At 16:47:37 (+02:00), child 1 committed `index.html` (722 bytes), `style.css` (1,462 bytes), and `app.js` (239 bytes). Audit counts were zero for missing, out-of-scope, unexpected-related and preservation violations. Artifact records had `verified=1`, with hashes matching retained disk contents. SQLite verification event 11 and native trace transaction line 106 support this result.

**Scope:** this child implemented structure and styling. Its JavaScript is a placeholder. Add, complete, delete, reload persistence, complete responsive behavior and final root acceptance remain unverified. Browser receipts had no interaction assertions, so they prove the foundation loads cleanly, not full application behavior. Run 7 needed no repair. Successful live Repairer mutation followed by fresh verification and acceptance remains unverified; controlled deterministic integration tests cover that lifecycle. The run was deliberately stopped, not naturally completed.

## Validation and remaining work

Run the selected offline checks without invoking the model:

```powershell
.\.venv\Scripts\python.exe -B scripts/repair_cycle_001_checks.py
```

The runner explicitly blocks model calls at the shared runtime entry points and uses temporary workspaces. It covers authorized writes and retained commits, rejected scope changes and rollback, actual controlled repair/fresh verification, context recovery/termination, dependencies, project modes, evidence integrity and browser authority. Scripted model replies in these tests are **not live-model validation**.

Historical cohorts: 503 passed / 1 skipped before later live fixes; subsequent overlapping selections passed 49, 85 and 110 tests, followed by 7 authority tests. Do not add overlapping counts or describe them as full-suite success. The November 19 publication cohort ran 517 tests: **516 passed, 1 skipped, zero failures/errors**. The skip requires unavailable historical planner artifacts. Its result is recorded in [publication-checks.json](evidence/repair-cycle-001/publication-checks.json). Some inherited historical replay tests require unavailable fixtures; those limitations remain disclosed in the repair report.

Next engineering validation should establish accepted functional children and a genuine parent/root verdict, including independent behavior checks for adding tasks, rejecting empty input, completion toggling, deletion and persistence. Diagnose actual future receipts before making more changes. No full E2E success or universal reliability is claimed.

Existing research documentation remains available under `reports/` and `docs/`; inherited findings and optional mechanisms should be read in their original evidence scope.
