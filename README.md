# Mini Hivo

Mini Hivo is a local coding-agent orchestrator pinned to one model:
`gemma4:e4b`. Every model-backed role uses that exact model. Cross-model
routing and fallback are intentionally disabled so experiment results remain
attributable.

## Run

```powershell
.\.venv\Scripts\python.exe mini.py
```

At the workspace prompt, pressing Enter creates the next numbered project under
`list/` (`project-1`, `project-2`, ...). Supplying an existing path uses that
path directly. Legacy files that previously lived directly under `list/` are
migrated once into `list/project-1`.

## Architecture

- `mini.py`: CLI, orchestration loops, tools, transactions, and runtime wiring.
- `hivo/model_policy.py`: immutable Gemma-only model and context policy.
- `hivo/projects.py`: legacy migration and atomic `project-N` allocation.
- `hivo/context.py`: bounded provider context without mutating source history.
- `hivo/memory.py`: per-project SQLite memory, verified-note retrieval, and a resumable run/task ledger.
- `hivo/playbooks.py`: deterministic project classification and bounded vertical execution stages.
- `hivo/evidence.py`: latest-evidence semantics; resolved failures do not poison a run.
- `hivo/verification.py`: contract-aware browser pass/fail rules.
- `tests/`: deterministic regression tests that do not require a live model.

## Browser-game verification contract

Generated browser games must expose `window.__AGENT_GAME__` with real adapters
to the application logic:

- `getState()`
- `start()`
- `restart()`
- `move(direction)`
- `forceCollision()`, `forceCollect()`, and `forceWin()` when those mechanics
  are part of the requested game

The browser verifier independently checks the document title, canvas, rendered
content, keyboard movement, requested mechanics, score persistence, and mobile
touch controls. A page that merely renders source code or placeholder text is a
failure even when its console is clean.

## Safety boundaries

`write_file` creates new files only. Existing files require focused
`edit_file` operations. The Repairer cannot call `write_file`, and visual/model
environment failures never trigger application-code edits. A failed task rolls
back all transaction-captured file changes.

## Durable memory and weak-model execution

Each project keeps private orchestrator state in `.hivo/memory.sqlite3`. Tool
events and run/task status are written to disk, while prompts receive at most a
small relevance-ranked excerpt. Only notes created after deterministic evidence
passes are retrieved as successful facts. Interrupted stages remain explicitly
labeled as unfinished and must be re-inspected after restart.

Complex contracts are divided into at most four vertical stages by deterministic
architecture code. Every stage starts with a fresh bounded conversation and is
implemented by `gemma4:e4b`; Mini Hivo does not write or polish generated project
code itself. The final transaction is committed only after fresh executable and
contract-specific verification succeeds.
