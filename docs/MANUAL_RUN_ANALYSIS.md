# Why the latest manual Three.js run stopped

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE):** Mini Hivo is **v2 only**. This document preserves a historical v1 (`mini.py`) manual run diagnosis only and is no longer used. See [`../README.md`](../README.md) and [`PROJECT_STATUS.md`](PROJECT_STATUS.md) for the active v2 system.

## Evidence boundary

This is a causal analysis of the user's actual manual run,
`20261117T135509-718ad4b8`, dated 2026-11-17. Its immutable source identity in
the recorded metrics is
`3d79f23150e74a8f334acdfa1d8a0ddca44786a5c88fc9b2a1339cf58b68818f`.
It ran through the original checkout, before the current Karim merge and
quiet-terminal integration were delivered.

The original request was a highly detailed, single-HTML-file browser game using
Three.js. The analysis uses the actual workspace's append-only run events,
SQLite tool receipts and final metrics. Those originals remain private and
unchanged. This report publishes selected observations, not the raw model
transcript, machine inventory or database.

The displayed final line was:

```text
child 1 failed: TASK_TOO_BROAD: repeated invalid mutations show the current node exceeds reliable focused capacity
```

`TASK_TOO_BROAD` is the controller's terminal classification. It is not, by
itself, proof that the model lacks the capacity to implement the requested game.

## What actually happened

The controller split the request. Child `1` was responsible for the initial
Three.js scene, camera and renderer in the single HTML file. The intended
handoff was concrete: later children could add movement, geometry, collision
and game behavior to that verified foundation.

The first Builder passed its context gate and actually wrote `index.html`.
The run therefore did not fail before every mutation or because no native
tool execution was possible.

It then attempted two `echo` commands, including one that merely printed
"Verification successful". Both were refused by the existing executable
allowlist. This was a **correct refusal**: printing a sentence is not
verification that the application works. Expanding the allowlist would not
repair the missing proof.

After reading the actual HTML, the Builder repeatedly called `edit_file_range`
without its required `start_line` field. The first malformed call also lacked a
path. The runtime correctly rejected these calls without applying them.

The complete tool-receipt sequence contains:

1. One incomplete range edit without `path` and `start_line`.
2. Four further incomplete range edits against `index.html`, all missing
   `start_line`.
3. The generic per-target invalid-mutation threshold was reached.
4. The Worker was classified as `TASK_TOO_BROAD`.
5. Its active transaction was rolled back.

The observed missing-field feedback is established. The exact upstream reason
why the model omitted the field is not established by that feedback alone.
In particular, an error string containing "incomplete or truncated" does not
prove that the HTTP response was truncated or that the host ran out of memory.

### Why the stopping decision was only partly correct

Stopping an unproductive mutation loop is reasonable. A bounded local model
must not be allowed to make invalid calls indefinitely.

The unsupported leap was:

```text
four refused mutations for one target
    -> the current coding node exceeds reliable focused capacity
```

What the evidence directly establishes is narrower:

```text
the Worker repeatedly violated the range-edit tool's argument contract
```

That is an interaction/protocol failure. It can coexist with a genuinely
difficult task, but it does not measure that difficulty. Changing the task
granularity before distinguishing those causes can make the situation worse.

## The recovery attempts exposed a second, independent defect

The controller did not immediately terminate the entire run after the first
Worker stopped. It attempted alternate recovery strategies.

One strategy proposed extracting code into a separate JavaScript file. The
model's own context requests then questioned whether that was allowed under
the single-file requirement. This shows a real tension between a generic
refactoring strategy and the original source constraint; treating the
constraint as optional would not be a valid recovery.

After rollback, the unverified `index.html` from the first attempt was no longer
present. A subsequent range edit failed with `MISSING_TARGET`. This was not
evidence that a user's pre-existing file had been lost: the transaction began
with an empty workspace, and rollback removed the generated unverified draft.
Recovery still reasoned about the old draft, so a fresh filesystem observation
was needed.

Later attempts used an ES-module import for Three.js. The syntax gate invoked:

```text
node --check -
```

It extracted inline script text without preserving the HTML script's module
mode. Node consequently reported:

```text
SyntaxError: Cannot use import statement outside a module
```

The historical receipts establish that this error rejected three candidate
writes. A fresh controlled reproduction establishes the underlying verifier
configuration defect: a valid `<script type="module">` containing an import and
export was rejected by the old gate, while the same source passed:

```text
node --input-type=module --check -
```

The reproduction performs parsing only. It does not execute the generated code
or download an external library. It establishes a false rejection in the
syntax-verification mode, not that every other aspect of the historical game
candidate was correct.

### Correction made during this investigation

The current integration now preserves inline script attributes using Python's
HTML parser. Explicit HTML modules and `.mjs` files are parsed as modules.
Classic scripts remain classic; independent module scripts are not concatenated
into one scope; external script bodies and JSON/import-map data blocks are not
misread as executable inline JavaScript.

Focused checks retain the opposite boundary: broken module syntax, imports in
classic scripts and a broken classic script next to a valid module are still
rejected. The correction changes the verifier's execution assumptions, not
the user's program to satisfy a misconfigured verifier.

This correction alone is **not** a fresh live acceptance of the original
complete Three.js game. No such claim is made.

## Why the failure spread through so many children

Later tasks required the shared HTML foundation. The actual context requests
asked for the structure/contract of `index.html`, Three.js setup code and
expected tests. Other requests asked for game rules or data structures the
new project had not yet established.

These are not all identical situations:

- A real prerequisite created by an earlier child must exist and be verified
  before a dependent child can safely build on it.
- A source-authorized future artifact should not be mistaken for a missing
  external dependency.
- A genuinely unspecified design choice needs an explicit bounded assumption
  or clarification; more recursive children do not supply user authority.

In this run, more splitting repeatedly encountered unresolved context rather
than repairing the earliest failed handoff. The final ROOT summary propagated
the first failed child; it did not describe every later attempt.

The final recorded scale was:

| Measurement | Actual recorded value | Interpretation |
|---|---:|---|
| Elapsed time | 3371.66 seconds, about 56.2 minutes | One complete failed run, not the duration of a single tool call |
| Model calls | 389 | All orchestration calls in this run, not 389 independent benchmark tasks |
| Tool calls | 234 | Actual tool requests recorded by the controller |
| Created task nodes | 64 | The configured total-node bound was reached |
| Splits | 17 | Recursive planning activity, not evidence of useful implementation progress |
| Maximum depth | 6 | The configured depth bound was reached |
| Leaf executions | 49 | Recorded leaf execution attempts, not 49 verified products |
| Recorded mutation failures | 9 | Five invalid argument calls, one missing target, three syntax-gate rejections |
| `task_too_broad_count` | 2 | Two recorded classifications; not a measured model-capability limit |
| Transport failures / timeouts | 0 / 0 | This run's retained counters do not support blaming an Ollama outage |
| Final task ledger | 63 failed, 1 too broad | Includes propagated ancestor outcomes, not 64 independent root causes |

Sixty-two initial ledger entries carry `CONTEXT_INSUFFICIENT`, including inherited
failure summaries. They must not be reported as 62 independent observed
root-cause trials.

The workspace has no final application artifact: unverified transaction-owned
files were rolled back. The evidence images and original logs remain available.
There was no honest `ROOT VERIFIED` result to preserve as a working product.

## What this means for repair

Three different observations must remain distinct:

| Observation | Appropriate response | Response that would not fix the cause |
|---|---|---|
| A tool call omits `start_line` | Correct/re-anchor the interaction under the same valid tool contract, with a bounded retry and fresh target evidence | Declare the game intrinsically too difficult or invent a missing line number |
| Valid module source is checked as CommonJS | Correct the verifier mode and rerun the same source | Remove a valid import merely to appease the wrong parser or disable syntax verification |
| A required shared foundation was rolled back | Re-establish the prerequisite or report dependency blockage honestly | Repeatedly split dependent work or pretend the previous draft still exists |

The syntax-mode correction is implemented and directly reproduced. A general
evidence-grounded attribution policy before adaptive splitting remains research
work, not a feature already proven by this one diagnosis.

Raising the retry, depth or node limits is not the proposed solution. Neither
is relaxing source constraints, accepting `echo` as verification, or converting
unresolved context into an automatic pass.

## Reproducible investigation boundaries

- Original run identity and source hash above bind the observations to the
  actual manual attempt, not the subsequent integration CLI.
- Original tool receipts establish what was accepted, refused and rolled back.
- The module-parser reproduction is controlled functional evidence on actual
  Node, distinct from a new live-model run.
- Current regression checks cover the positive module route and real invalid
  syntax; they are not a benchmark of full game completion.
- No historical workspace, transcript or outcome was rewritten to obtain a
  successful result.
- The user's append-only run ledger advanced after the initial protection
  snapshot while their original process completed. The old bytes remain an
  exact prefix; the database's matching run completion was retained, not
  restored to an obsolete snapshot.

This failure is useful experimental evidence precisely because its causal
layers are preserved. It should motivate a falsifiable controller experiment,
not become an unsupported claim that recursive agents, safety gates or a
particular local model are universally incapable.
