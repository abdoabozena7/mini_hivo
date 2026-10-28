# Evidence harness guide

Contents: lifecycle; contract fields; plan tracker; running checks; review; gate;
blocked/resume; hooks; revisions and large projects; operational boundaries.

## Lifecycle and paths

Use Python 3.10 or newer. The collector, planner and installer use only the
standard library. Browser execution additionally needs Playwright, Chromium
and its video dependency. Use one installed skill copy consistently; scripts
are fingerprinted, and changing them invalidates sealed evidence.

In the commands below, `PROOF` means the actual absolute path to
`prove-it/scripts/proof.py`; `TASK` is the created task directory. Replace these
notation placeholders with actual paths. Shell arguments are examples, not new
authorization to operate protected simulators or production systems.

```text
python PROOF doctor
python PROOF init --project . --id item-flow --goal "Create and persist an item through the real UI" --kind web
```

Initialization creates `.runtime-proof/item-flow/contract.json` and activates
that task for the checkout. The draft intentionally contains placeholders and
cannot pass. Read the repository and replace them with real requirements,
commands, source scope and a dependency-aware task plan. Do not seal the template
without adapting it. The agent performs this work, not the end user manually.

Use `--session-id ACTUAL_SESSION_ID` for concurrent agent clients in the same
checkout. Otherwise one active task applies to that checkout. Do not start
multiple coordinators with competing progress writes.

Before sealing, create needed verifier/config files under the intended source
scope. A new project may need an initial minimal scaffold before it can be
executed; record that as setup, not verified implementation. Specify at least
one existing source file/directory. Do not hash the whole repository with `.`.

```text
python PROOF seal --task TASK
python PROOF todo --task TASK
```

Sealing binds the requirement/check/plan contract and harness, but permits
implementation changes. Subsequent receipts bind the source actually executed.
`TODO.md` is generated from the plan/progress, not a free-form success claim.

## Contract fields

`schema` is 1. `kind` is web, simulation, cli, api, library or generic.
`source_paths` is an explicit list of relative POSIX paths, including
implementation, important configuration, dependency locks and verification code.
Untracked files inside the selected roots are included. Do not include evidence,
virtual environments, downloaded weights or mutable run outputs. Broad source
scope is conservative but may cause more final reruns.

`scope_rationale` and `authorization` explain what is covered and allowed. They
are declarations, not automatic permission grants or semantic proof of completeness.

Each requirement includes `id`, `claim`, independent `oracle`, `failure_example`,
`runtime_required`, linked `checks`, `negative_checks` (or a specific
`negative_control_exception`) and `review_required`. Web and simulation
requirements require review and artifacts. A runtime-required requirement must
link a live acceptance check; offline, replay and fixture checks cannot satisfy it.

Each check includes:
- `id`, `description`, `mode` (live/offline/replay/fixture) and `role`
  (acceptance/regression/negative_control).
- `command`: an argv array, never an implicitly interpreted shell string.
- Finite `timeout_seconds`, expected exit codes and nontrivial outcome assertions.
- Optional relative `cwd`, `stdin_file`, and required artifact patterns.

Only negative controls may expect nonzero exit codes; they also need a concrete
`fault` and assertions showing the intended failure was detected. A random crash
is not a passing negative control. Preserve real existing experiment limits;
this per-command timeout is not a new artificial diagnostic funding ledger.

Substitutions in command arguments: `{python}`, `{skill}`, `{project}`, `{task}`,
`{run}`. The collector supplies `PROVE_IT_RUN_ID`, `PROVE_IT_OUTPUT_DIR` and
`PROVE_IT_PROJECT_ROOT`. Write fresh outputs to `PROVE_IT_OUTPUT_DIR`.

Assertions support literal stdout/stderr substrings and JSON Pointer fields with
`eq`, `ne`, `gt`, `ge`, `lt`, `le`, `contains`. Use numeric/structured behavior
assertions where possible. A string literal "PASS" from the implementation is
not a sufficient independent oracle even though the collector can compare it.
Artifact globs may require minimum count/size; hashes bind every collected file.
The collector cannot determine whether an arbitrary binary is a genuine video.
Decode/inspect it through an appropriate verifier.

## Plan and TODO states

The contract's `plan` contains `strategy`, `rationale`, actual delegation
capability and task cards. Task IDs/dependencies must form an acyclic graph.
Every task must map to requirements and checks. At least one integration task
must depend transitively on every investigation/implementation task.

```text
python PROOF step --task TASK --id T01 --status IN_PROGRESS --note "Inspecting the existing API contract and reproducing the persistence failure."
python PROOF step --task TASK --id T01 --status IMPLEMENTED --note "Persistence path implemented; integrated runtime evidence is still pending."
```

Allowed states: TODO, IN_PROGRESS, IMPLEMENTED, VERIFIED, BLOCKED. A dependency
must have a usable IMPLEMENTED/VERIFIED deliverable before its consumer starts.
The final gate still requires every step VERIFIED with current checks. Progress
updates are coordinator-owned and archived in history; workers must not race
on these files.

For delegated tasks, pass actual `--agent-ref` and a `--handoff` file relative
to TASK. Handoff is required when marking IMPLEMENTED/VERIFIED. Example:

```text
python PROOF step --task TASK --id T03 --status IMPLEMENTED --agent-ref ACTUAL_TOOL_SESSION_ID --handoff handoffs/T03.md --note "Reviewed the frontend worker's patch and raw browser evidence; integration pending."
```

The tool refuses VERIFIED without passing current linked execution receipts.
It cannot independently authenticate a user-written agent identity. Keep native
tool traces so the reviewer can check provenance.

## Execute actual checks

```text
python PROOF run --task TASK --check actual-check-id
```

This executes the sealed argv with `shell=False`, captures stdout/stderr, PID,
exit status, timestamps, before/after source fingerprints and required artifacts.
It creates a unique run directory and marks that attempt current before launch;
a killed/unfinished attempt cannot fall back to an older passing run.

Start long-lived servers using the host's managed process tools. Do not put an
infinite `npm run dev` into a finite acceptance check and expect it to pass.
The check should exercise the already-owned server or use a task-specific
supervisor that starts, probes and cleans up its own children.

On Windows, explicitly invoke `npm.cmd` through an appropriate approved command
adapter (for example `cmd /d /c`) if a batch executable needs a shell; the
collector does not silently enable one. Use array arguments and quote within
the explicitly selected shell according to that shell's rules.

For native simulation, use its existing supervisor and cleanup protocol. Set
the outer timeout to include the authorized native runtime and cleanup reserve.
On timeout, the wrapper terminates only its owned process tree/group; this is
an interrupted failure, not successful simulator cleanup. Do not run an
unsupervised long-lived CARLA server as a finite check.

The stdout/stderr capture limit is 32 MiB per stream. Exceeding it fails visibly
instead of silently truncating a successful result. Large detailed telemetry
belongs in artifact files. The whole artifact may be hashed again at verification;
choose bounded evidence and allow sufficient hook time, not terabytes of raw video.

## Inspect and record review

Open actual screenshots, play/decode relevant video, examine logs and compare
observed outcomes with the independent oracle. Then adapt the review template.
It records actual reviewer identity, independence level, requirement verdict,
concrete observations and file-level evidence references.

```text
python PROOF review --task TASK --input actual-review.json
python PROOF step --task TASK --id T01 --status VERIFIED --note "Verified the current real API response, persisted row and reload behavior."
python PROOF step --task TASK --id T02 --status VERIFIED --note "Re-ran the integrated browser journey and inspected final evidence."
python PROOF verify --task TASK --write-report
```

A new run makes old review references stale even if source is unchanged. A
source change invalidates all scoped receipts and verified task states. Rerun
final checks, inspect current artifacts and update the task verification states.

## Gate results

Exit 0 and `EVIDENCE_GATE_PASSED` mean the declared execution/evidence/plan
conditions were met. Exit 1 means incomplete/failing verification. Operational
errors normally return 2. All required checks are enforced; optional experiments
should not be silently placed in required checks then skipped.

`gate.json` includes individual checks, requirements, TODO status and errors.
Never replace this result with an agent's prose. Passing the gate cannot prove
oracle quality, visual judgment, complete source scope, optimal planning or the
honesty of another process running as the same user.

## Block and resume truthfully

```text
python PROOF block --task TASK --reason "The operating system denied access to the native sensor recordings." --action "Grant read access to the named approved recording directory." --evidence runs/ACTUAL_CHECK/ACTUAL_RUN/stderr.log
python PROOF resume --task TASK --reason "The approved recording path is now readable; retry the original check."
```

Block requires a nonempty raw evidence file relative to the task. It permits a
truthful handoff but never passes acceptance. Resume preserves the blocker in
history and grants no new operating-system or spending permissions.

## Optional stop hooks

The installer can add a Copilot `agentStop` or Claude `Stop` hook. It invokes
verification, not long product experiments. It requests continuation for an
incomplete active task, giving the next agent turn actual failures to address.
When a forced continuation produces the same failed signature, the hook yields
and writes `needs-attention.json` with PAUSED_UNVERIFIED. External BLOCKED tasks
can also stop truthfully. Neither path creates a passing gate.

Without an active initialized task, the hook is deliberately inactive. The
always-on instruction file and explicit skill invocation initiate coverage.
Hosts can disable, reject, time out or cap hooks. Verify installation in the
actual client; testing emitted JSON locally does not prove host enforcement.
The optional session-ID scope avoids interfering with a different conversation.

## Contract revisions and large projects

Before sealing, edit the draft. After sealing, preserve the original contract
and evidence. Record a reasoned revision, map all original requirements, and
create a new task ID. Do not lower requirements just to pass. If the old task
is externally blocked, record that truthfully before starting another task;
do not invent a blocker to bypass active-task protection.

For large projects, use bounded child contracts plus a parent integration
contract. Keep the original request covered. This initial harness is intentionally
conservative; it does not automatically compute file-level dependency invalidation
or launch a multi-agent scheduler. The coding agent chooses and orchestrates work.
