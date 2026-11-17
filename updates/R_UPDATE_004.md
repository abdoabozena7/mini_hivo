# R_UPDATE_004 - Calm terminal sessions with real interactive acceptance

## A. Update Identification

- **Date:** 2026-11-17; underlying command records retain exact timestamps.
- **Scope:** quiet interactive terminal, persistent workspace-bound sessions,
  complete private diagnostics, visible native decisions, and the directly
  reproduced Three.js syntax-verifier mode correction.
- **Branch/base:** `integration/karim-pr1-quiet-tui`, after actual two-parent
  Karim merge `14fffa5f1e995b5eb5da10d3860abea8a9752fe3`.
- **Merge parents:** `6887d0bfeda237d841ba6a3ac842d184b5ad55b8` and Karim's
  actual PR head `34a972a0b2feb80a31e06d0b93d6c22ca2961bc8`.
- **Tested source:** fingerprint
  `eb6deae1f335854c0077474108f3d06d438ef94efb3553a750339e9716bbec2f`,
  covering 74 actual checkout implementation files. The live log independently
  recorded the matching `mini.py` SHA-256.
- **Containing commit and remote publication:** pending at this checkpoint;
  final publication is recorded separately rather than inventing a future hash.
- **Related records:** [merge integration](R_UPDATE_003.md),
  [sanitized terminal validation](../reports/integration/quiet-terminal/validation.json).

## B. Original Problem

The user explicitly wanted Karim's changes merged and validated **before**
terminal work. They then requested a calmer Codex-like operating interface:
normal terminal output should not contain the high verbosity intended for
documentation, and sessions should be selectable, switchable and resumable.

The existing line-oriented loop printed model transport shapes, contracts,
task diagnostics and hundreds of metric fields. Existing project memory was
durable, but there was no complete session-oriented terminal navigation flow.

During implementation the user also asked why their latest manual Three.js
game run had stopped, and requested exactly one defensible research direction.
The [actual-run analysis](../docs/MANUAL_RUN_ANALYSIS.md) and
[single selected research contribution](../docs/RESEARCH_DIRECTION.md) answer
those requests without relabeling historical failure as success.

## C. Why the Update Was Necessary

A quiet interface cannot simply discard output or redirect all process stdout:
that could hide the question or scope the user must approve. Nor can session
switching reuse the previous project's active authority, world model or
working-Brain store.

The desired operating surface must be concise **and** traceable. It must
show real activity, preserve exact local diagnostics, keep unfinished work
truthful, make recovery discoverable, and leave the established coding engine
and permission/verification boundaries authoritative.

## D. Root Cause Analysis

| Finding | Evidence-backed cause |
|---|---|
| Verbose normal scrollback | Core `print` calls and `finish_metrics` intentionally expose research diagnostics directly |
| No user-level session switching | Project memory stores engine records, not a separate catalogue of named workspace-bound terminal sessions |
| Cross-session state risk | The synchronous orchestrator has module-global contracts, world model, memory and transaction state |
| Initial native decision defect | Question/scope was printed before entering an alternate-screen radiolist, leaving necessary context in the inactive buffer |
| Truncated skip control | A long button label exceeded the native widget's default button width |
| Historical Three.js false rejection | The syntax gate discarded script attributes and checked explicit module source as CommonJS |
| Ambiguous stop explanation | Repeated invalid range-edit arguments were classified by a generic `TASK_TOO_BROAD` counter; the analysis distinguishes observation from capability inference |

The first independent QA correctly failed the initial decision design.
The issue was repaired rather than waived because selection keys happened to work.

## E. What Changed

| Component | Change | Responsibility boundary |
|---|---|---|
| [sessions.py](../hivo/sessions.py) | SQLite catalogue, stable IDs, name/reference resolution, workspace validation, bounded turn history and explicit terminal status transitions | UI persistence, never coding authority |
| [terminal_ui.py](../hivo/terminal_ui.py) | Rich progress, prompt_toolkit input/chooser, slash commands, safe literal rendering, complete UTF-8 logs, explicit errors and truthful cancellation | Single synchronous operating loop |
| [mini.py](../mini.py) | CLI flags, lazy workspace preflight, state/memory rebinding, temporary module-local print routing, progress events, rollback on exceptional/cancelled requests | Reuses the existing engine and guards |
| Native decision seam | Shared scrollable read-only context pane inside the active dialog, full action labels, keyboard focus/paging and paused activity | Informed selection/approval; no automatic authorization |
| JavaScript validation | Preserve inline script mode; module syntax for explicit modules and `.mjs`; independent module scopes; retain invalid-source rejection | Correct verifier assumptions, not an easier application oracle |
| Tests | Focused persistent-store, terminal, real-glue and syntax-mode regressions | Real filesystem/controller; scripted boundaries labeled |
| Documentation/ignore rules | User guide, current status/index links, detailed analysis/research report, sanitized validation and private `.runtime-proof` exclusion | No raw newly captured databases/transcripts committed |

No application dependency was added. Private PTY validation utilities were
installed outside the product only after an actual missing-module failure.

## F. How the Fix Works

### Operating flow

Interactive TTY startup opens the most recent saved session or allocates a
fresh numbered workspace. An explicit workspace registers/reuses its session.
Listing/navigation does not call the model. The first submitted request in a
workspace performs the authoritative local host/model preflight.

For each request, the catalogue records a running turn and a unique log file
before execution. The terminal runs exactly one engine callback. Core detailed
printing is routed **locally to `mini.py`**, not by globally swallowing stdout.
Progress updates one real-work status row. Diagnostics remain complete in the
log; normal output presents the outcome, bounded summary/files and actual log
location. `--verbose` exposes details and `--plain` retains the old interface.

### State and authority

Before a new workspace request, active contracts, world-model references,
working-Brain state and previous run state are discarded, then the selected
workspace's existing durable memory is loaded. An active transaction prevents
workspace rebinding.

Selecting a session, reading old history or restoring a successful UI turn is
not plan approval, current verification or source authority. Unfinished turns
are shown as unfinished and never automatically replayed.

Cancellation/exception rolls back any still-active transaction before another
prompt can execute. Storage/log failures are explicit; incomplete logging or
unsaved status is not silently reported as durable success.

### Decision visibility

Clarification and approval pause live redraw. The question/reason or actual plan
scope is inside the active native dialog. A read-only focusable review pane
allows preservation/test content to be paged at 60 columns, not removed to make
the screen fit. Space/Tab/Shift+Tab/PgUp/PgDn/Esc and complete buttons are visible.

## G. Functional Verification

Independent QA exercised the actual public entrypoint through **Windows ConPTY**,
with actual keyboard writes and backing sizes independently checked as 100x30
and 60x20. A piped stdin or mocked read function was not called interactive proof.

| Scenario | Class | Independent outcome |
|---|---|---|
| Session create/rename/list/switch/chooser/relaunch | Actual public terminal journey | Stable IDs, workspace bindings, history and logs survived new processes |
| Unknown reference/command and picker cancellation | Actual public terminal journey | Current selection/turn count unchanged; no model request |
| Required decision review | Controlled functional, actual native selectors and keys; no live planner claim | Question/reason, actual scope, preservation/test paging, selection/skip/cancel and recovery pass at both sizes |
| Real Ctrl+C during host qualification | Actual live preflight cancellation, retained historical evidence | Cancelled turn and usable next input; not mislabeled live mutation rollback |
| Active transaction cancellation | Controlled main callback with actual filesystem/rollback | Uncommitted draft removed and print/state routing restored |
| Exact artifact request through `You>` | Fresh live-model E2E | Actual `proof.txt` bytes independently equal the required 11 bytes |
| Completed-session restart | Actual exit and public `--resume` at 60x20 | Completed history/log restored, no replay, artifact/log hashes unchanged |
| Work/idle motion | Temporal real-grid sampling | One busy row with distinct spinner states; idle grid stable |
| Quiet output and complete logs | Independent retained terminal/log parsing | 10 semantic lines against maximum 20, no raw metrics/transport JSON; complete 103469-byte log |
| JavaScript module mode | Controlled actual Node parser checks | Valid module accepted; real malformed module/classic syntax still rejected |

The sole current live request was exactly:

```text
Create proof.txt containing exactly:MERGE_READY
```

Default `auto`, actual local `gemma4:e4b`, new empty workspace, no product
coaching or manual artifact edits. Engine run `20261117T210037-2ef107f3`
completed in **51.517305 seconds**, displaying 51.5s. It had zero provider retries.

- Expected/actual bytes: `4d455247455f5245414459`, with no newline.
- Artifact SHA-256:
  `7046c074dbba4ec74ad46f975f928ae029a8e5491cc3c10e9751c3975dfd6f3b`.
- All live role models and source identity independently matched the pin.
- Three actual preflight canaries passed; preflight remained authoritative.
- The diagnostic log contained the complete result, 500 parsed metric fields
  and five complete JSON model-transport shape records.

Semantic-line counting includes wrapped result/file/log lines. It excludes only
editable input/footer, blank rows and ANSI spinner repaint, not inconvenient
diagnostic text. The measured result is scoped to this request, not all tasks.

## H. Additional Successful Tests

All final checks below used the same `eb6deae1...` implementation fingerprint:

| Check | Command / scope | Observed outcome |
|---|---|---|
| Complete combined regression | `python -X utf8 -m unittest discover -s tests -q`, existing Chromium opt-in enabled | **1950 run, OK, four existing skips**, exit 0 |
| Public self-test | `python -X utf8 mini.py --self-test --no-bootstrap` | PASS, exit 0 |
| Composed terminal/store/main tests | `python -X utf8 -m unittest discover -s tests -q -p test_terminal_*.py` | 46 run, OK |
| Module/decision/clarification/impact regressions | Selected existing suites | 191 run, OK, four existing skips |

Counts overlap and are not summed as unique coverage. The complete suite
actually executed the five contributor browser cases instead of skipping them.
The remaining four skips are the historical removed legacy scheduler tests.

## I. Regression and Compatibility Impact

- Prompt-file execution keeps the existing line-oriented/noninteractive behavior
  and exit contract. Session resume is rejected where the session UI cannot run.
- Plain mode retains the original workspace prompt and verbose trace.
- Existing context, impact, source assertion, mutation and verification guards
  remain in place. Session history is not injected as fresh authorization.
- Existing numbered-project allocation/migration is reused. The catalogue is
  outside the `list` root so migration cannot absorb it into an old project.
- Real missing-workspace/reference/storage errors remain explicit and recoverable.

### Retained failures and corrections

Initial independent native-dialog QA failed because question/scope was hidden
and a skip button clipped. Both are closed by current actual frames, key
selection and scroll tests. Their original failed evidence remains.

Private validator defects were diagnosed separately: incremental ANSI matching,
alternate buffers/full-cell backgrounds, wrapped punctuation, key:value metrics
parsing, path-object comparison and duplicate derivative-crop names. Corrected
measurements retained the original frames/results rather than overwriting them.
They were not additional attempts at the live model task.

Early parent glue tests also exposed a stdout-patching order error and a
wrapping-sensitive assertion. Both were test-harness corrections, not relaxed
product postconditions.

## J. Overall Impact

The terminal now offers a calm operating surface with actual animation,
functional persistent sessions and complete private diagnostics. Real
interactive/independent evidence replaces a claim based only on screenshots,
unit tests or a success banner.

The manual-run analysis additionally separates a repeated tool-contract failure,
a real verifier mode defect and the later context cascade. Its proposed research
policy is explicitly not presented as an already implemented system improvement.

## K. Remaining Limitations

- One accepted current short TUI task is not a statistical coding reliability
  benchmark or proof of arbitrary game/project completion.
- The user's original full Three.js game has not received a new successful
  complete live acceptance in this update.
- General evidence-licensed decomposition remains proposed research work.
- Live preflight cancellation and controlled mutating rollback are different
  proofs; a newly mutating live cancellation was not claimed.
- Formal HarrTest Team verification remains **unverified/blocked** on this
  Copilot host: its parent-thread adapter is Codex-specific, and the original UI
  worker failed before its repair handoff. Coordinator takeover and stale
  original receipts are recorded, not replaced with synthetic owner provenance.
- GitHub PR merge status requires the separate actual non-force publication
  check; a local merge alone is not called a remote merge.

## L. Evidence and Reproduction

Public sanitized data: [validation.json](../reports/integration/quiet-terminal/validation.json).
Usage and recovery: [terminal guide](../docs/TERMINAL_SESSIONS.md).
Failure analysis: [manual run](../docs/MANUAL_RUN_ANALYSIS.md).
Research selection: [one direction](../docs/RESEARCH_DIRECTION.md).

Original raw ANSI, screenshots/detail crops, timing grids, SQLite records,
host reports, full request logs and QA reports remain private in the session
evidence area and the ignored integration-worktree proof directory. Paths/host
inventories were intentionally omitted from new public derivatives.

```powershell
.\.venv\Scripts\python.exe mini.py --no-bootstrap
.\.venv\Scripts\python.exe mini.py --sessions --no-bootstrap
.\.venv\Scripts\python.exe mini.py --resume --no-bootstrap
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -q
.\.venv\Scripts\python.exe -X utf8 mini.py --self-test --no-bootstrap
```

For isolated interactive acceptance, set `HIVO_SESSION_HOME` to a new private
directory and pass a new empty existing workspace. Submit the exact prompt
above through a real TTY, then independently read the file bytes. Never reuse
historical run directories or count an agent's own summary as the byte oracle.

Recorded implementation hashes identify actual tested checkout bytes.
Git's text normalization can give committed LF blobs different byte hashes;
final delivery checks compare source content and revalidate the final main
checkout separately rather than silently treating those identities as equal.

## M. Summary for the Team

**Title:** Add calm persistent-session terminal with traceable diagnostics.

**Why:** preserve detailed investigation without flooding normal use, and support
real session navigation without leaking execution authority between projects.

**Production contributions:** an implementation worker supplied the session
catalogue; another supplied initial terminal rendering/input/logging. The
coordinator assembled the engine, repaired evidenced native-decision/status/
startup issues after the UI worker's transport failure, and corrected the
manual-run module verifier. Independent QA performed actual read-only terminal
journeys, live artifact/log/state audits and inspected temporal/full/detail frames.

**Functional proof:** exact live Gemma artifact, truthful completed turn,
10/20 semantic output lines, complete diagnostics and actual process resume;
native decisions readable and operable at both terminal sizes.

**Regression:** 1950 run, OK with four historical skips; public self-test PASS.

**Limits:** bounded task coverage and formal Codex-only provenance limitations
remain explicit; no full-game or research-treatment success is invented.

**Publication:** locally verified source before its containing commit. A separate
publication record will identify actual final main/remote/PR state.
