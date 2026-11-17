# Calm terminal and saved sessions

The normal interactive interface separates **operating the agent** from
**investigating the agent**. A coding request needs a readable activity
indicator and an honest result, not hundreds of metric and contract lines.
Detailed diagnostics remain available on disk and through `--verbose`.

This interface uses the existing Rich and prompt_toolkit dependencies. It is
a terminal application, not a browser dashboard or a second execution engine.

## Starting and returning

```powershell
.\.venv\Scripts\python.exe mini.py --no-bootstrap
.\.venv\Scripts\python.exe mini.py --sessions --no-bootstrap
.\.venv\Scripts\python.exe mini.py --resume --no-bootstrap
.\.venv\Scripts\python.exe mini.py --resume session-name --no-bootstrap
```

In a real interactive terminal, a normal launch returns to the most recently
active saved session. With no saved sessions, it creates the next numbered
workspace under `list` and a session bound to it. `/new` creates another
fresh numbered workspace. Neither operation asks the model to change files.

To register an existing project rather than create a new one:

```powershell
.\.venv\Scripts\python.exe mini.py --workspace .\list\project-1 --no-bootstrap
```

An existing saved session for that resolved workspace is reused; otherwise
a new session references the folder. This does not copy, relocate, reset or
approve changes to the project's files. `--workspace` and `--resume` are
mutually exclusive.

Session listing, selection and navigation do not require a model request.
The authoritative host/model preflight runs lazily when the first actual
request is submitted in a workspace during that process. A failing preflight
still prevents execution.

## Controls

| Action | Control |
|---|---|
| Submit the current request | Enter |
| Insert a newline | Alt+Enter |
| Create a new session/workspace | Ctrl+N or `/new [name]` |
| Choose a saved session | Ctrl+R or `/resume` |
| List saved sessions | `/sessions` |
| Switch by ID, unique ID prefix or name | `/switch ID-or-name` |
| Resume a particular saved session | `/resume ID-or-name` |
| Rename the current session | `/rename name` |
| Read recent recorded turns | `/history` |
| Find the latest detailed request log | `/logs` |
| Show the command reference | `/help` |
| Cancel current work | Ctrl+C |
| Leave without deleting history | `/quit` or EOF at the prompt |

Names are readable labels, not filesystem paths. IDs stay stable after a
rename. Ambiguous names or ID prefixes are rejected rather than selecting
an arbitrary session. Use the ID shown by `/sessions` when names collide.

Session switching is an idle operation. There is only one synchronous
engine request at a time; a keyboard command cannot replace the workspace
under an active transaction. A nested clarification answer is an answer,
not a slash command.

## What stays visible

The interface shows the selected session and workspace, discoverable controls,
and one moving activity indicator while real work is running. Progress follows
the current role/action/tool instead of appending the complete tool protocol.
The final result distinguishes completion from failure, blockage or cancellation.

Clarification and plan approval remain explicit native keyboard dialogs.
Live redraw pauses while a decision is on screen. Selecting a session,
viewing its history, or seeing an old successful turn is **not** approval
of a new plan or evidence that the current task is complete.

Errors are not hidden to make the screen look quieter. The normal interface
provides a short explanation and the diagnostic log location. Detailed model
transport shapes, contracts, task ledgers and metrics go to that log.

```powershell
# Keep the session UI but also print detailed diagnostics.
.\.venv\Scripts\python.exe mini.py --verbose --no-bootstrap

# Explicitly use the former line-oriented, verbose interface.
.\.venv\Scripts\python.exe mini.py --plain --no-bootstrap
```

The original workspace prompt remains available in `--plain`: Enter allocates
the next numbered project, and an existing path selects it. Numbered-project
allocation and the existing one-time legacy `list` migration use the same
`ProjectStore`, not a new naming convention.

## Persistence and tracing

Two different stores have different responsibilities:

| Location | Responsibility |
|---|---|
| Repository-private `.hivo/terminal/sessions.sqlite3` | Session IDs, names, absolute resolved workspace bindings, turn prompts, truthful UI statuses, timestamps, engine run IDs and log locations |
| Repository-private `.hivo/terminal/logs/<session-id>/<turn-id>.log` | Per-request UTF-8 diagnostics, including the actual engine output and failure traceback where applicable |
| Each workspace's `.hivo/memory.sqlite3` | Existing engine run/task/tool ledger and evidence-qualified project memory |
| Each workspace's `.agent_runs` and `.agent_experiment.jsonl` | Existing detailed execution provenance and metrics |

The catalogue deliberately does **not** live in the `list` root: the legacy
project migration treats non-project entries there as old project contents.
Session names and prompt text are never used as log directory names.

`HIVO_SESSION_HOME` can point the catalogue, input history and request logs at
another private state directory, for example to isolate an acceptance run.
This changes UI state storage, not the selected project's execution authority
or the local model provider. Keep such a directory out of version control.

Resuming restores a conversation/workspace reference and its recorded history.
The engine reloads that workspace's existing durable memory. Previous
workspace authority, world-model caches, active contracts and working-Brain
references are discarded before a new workspace request begins. The UI
history itself is never injected as new user authorization or verified facts.

An unfinished turn stays visibly unfinished after process restart. It is
not automatically replayed or marked complete. Submit a new request to
continue deliberately; the normal context, impact, approval and verification
boundaries still apply.

Ctrl+C during a request closes that UI turn as cancelled and rolls back any
still-active transaction through the existing rollback mechanism. Earlier
committed/verified requests are not undone. A hard process kill is different:
it can leave a running/unfinished record for inspection at the next launch.

## Batch compatibility

Prompt-file execution remains line-oriented and noninteractive, even if launched
from a terminal. It does not create UI sessions or open session/approval pickers.

```powershell
.\.venv\Scripts\python.exe mini.py --workspace D:\cases\new-project --prompt-file D:\cases\prompt.txt --no-bootstrap
```

The existing exit contract remains: `0` for `done`, `1` for unsuccessful or
blocked work, and `2` for setup/preflight errors. `--resume` requires the
interactive session interface; it is rejected with `--plain`, a prompt file
or a noninteractive terminal rather than silently ignored.

## Recovery

- **A saved workspace was moved or deleted:** list sessions with `--sessions`,
  choose another with `--resume ID`, or explicitly register an existing folder
  with `--workspace`. The application never recreates a missing project behind
  a saved session's identity.
- **The model or host is unavailable:** inspect `/logs`, restore the local
  provider/resources and submit a new request. A failed preflight is not a
  successful coding run.
- **A session reference is unknown or ambiguous:** the current session remains
  selected. Use its explicit ID from `/sessions`.
- **A diagnostic is needed:** open the actual file named by `/logs`, or rerun
  deliberately with `--verbose`. Logs and prompts can contain private project
  content; do not blanket-stage the state directories.

For measured implementation evidence and limits, see the numbered records
under [updates](../updates/) and the [results index](../reports/INDEX.md).
