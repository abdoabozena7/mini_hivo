# Experiment setup and methodology

[Review entry point](README.md) · [Evidence index](EVIDENCE-INDEX.md)

## Purpose and task selection

The End-to-End Real-Task Execution and Validation workstream evaluated whether Mini Hivo could independently turn a realistic user request into a runnable application through its public interactive workflow. Another workstream owns Experiment 18 research/fixes; another owns integration and smoke testing. This experiment does not repeat timer repair and does not manually drive internal planning functions.

Coin Courier was selected because a small standalone browser game combines visible interaction, state transitions, persistence, terminal conditions, responsive controls, and verifiable adapters. These requirements depend on one another: collection must update both the HUD and persistent maximum; terminal states must freeze movement/scoring; restart must clear round state without losing the best score or duplicating loops. A direct local HTML entry point also avoids introducing backend deployment, external assets, package installation, or new Mini Hivo features.

The existing browser-game verification contract and interactive CLI supported requesting this artifact. Support for the workflow does not establish that the agent can implement the request successfully.

## Exact saved user task

The following is the original prompt text. The original file's byte SHA-256 is `848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256`; this identifies the original file, not the Markdown code block or its line endings.

```text
Build Coin Courier, a complete standalone browser game in this empty workspace. Deliver index.html with any local CSS/JavaScript files needed. It must work by opening index.html directly, without a server, build step, downloaded assets, packages, or external services.

Requirements:
1. Show a titled start screen with clear instructions, a Start button, a canvas play area, current score, and best score. Start begins a fresh playable round.
2. The player is a courier on a visible bounded arena. Arrow keys and WASD move the player in four directions. Prevent game keys from scrolling the page. Keep the player inside the arena.
3. Place a collectible coin away from the player and obstacles. Collecting it adds exactly 10 points, updates the visible score, and places another reachable coin at a valid position. A coin cannot award points repeatedly without another collection.
4. Include clearly visible obstacles. Collision with an obstacle ends the round, displays Game Over and the final score, and stops player movement and further scoring until restart.
5. A visible Restart button and the R key restart after game over. Restart resets score and player position, clears the terminal state, and makes the game playable again. Repeated restart must not accumulate event handlers or animation loops.
6. Preserve the highest score in localStorage across restart and page reload. A lower-scoring round must not replace the best score. If storage is unavailable, keep the game playable and report the limitation.
7. Provide responsive layout and visible touch direction buttons using the same movement logic. The game, HUD, and restart control must remain usable at a 390 by 844 viewport.
8. Support Mini Hivo's browser-game verification contract: expose the global AGENT_GAME object with getState(), start(), restart(), move(direction), forceCollision(), forceCollect(), and forceWin(). Return a serializable state snapshot. These adapters must call real gameplay logic; collision and collection adapters must exercise the same transitions as normal play.
9. Collecting 10 coins (100 points) completes the delivery round: display You Win, stop further movement and scoring, and allow the same Restart button or R key to begin a fresh round. forceWin() must exercise this real terminal transition.

Implement the application through the normal tools. Verify actual browser behavior, including collection, collision, restart, keyboard and touch controls, score persistence, and repeated restarts. Report the entry point, files created, checks performed, and any behavior not verified. Modify only this application workspace. Do not install packages or access remote services.
```

The loopback model service is execution infrastructure; the requested application itself must not need external services. No requirements were removed to get past a gate. In Run-003 the investigator stopped at the false clarification instead of choosing one of two compatible requirements.

## Independent acceptance protocol

These are the original acceptance checks restated as executable review obligations. Every item remains **NOT TESTED** because there is no application artifact. No browser screenshots or behavioral passes are claimed.

| ID | Required independent observation | Status |
|---|---|---|
| A1 | Open local `index.html` directly with external networking blocked. Title, instructions, Start, canvas, current/best scores appear; no uncaught errors, build or backend needed. | NOT TESTED |
| A2 | Start a round; use Arrow keys and WASD in all four directions. Player stays inside bounds and game keys do not scroll the page. | NOT TESTED |
| A3 | Physically collect at least two coins. Each adds exactly 10; replacement coin is valid/reachable; waiting does not repeatedly award points. | NOT TESTED |
| A4 | Physically collide with an obstacle. Game Over/final score appear; subsequent movement and collection do not change terminal state or score. | NOT TESTED |
| A5 | Restart by button and R. Verify score/position/state reset; repeat at least five times and look for extra listeners/animation loops. | NOT TESTED |
| A6 | Earn a nonzero best score; restart, complete a lower-scoring round, and reload the same local URL/profile. Best never decreases. Separately deny storage and verify playable fallback plus disclosed limitation. | NOT TESTED |
| A7 | At 390 × 844, operate all four touch directions and restart; canvas, HUD and controls remain usable. | NOT TESTED |
| A8 | Collect ten coins/100 points; You Win appears and movement/scoring freeze. Both restart methods start a fresh round. | NOT TESTED |
| A9 | Inspect serializable `AGENT_GAME.getState()` and all required adapters; verify that they exercise the same actual gameplay transitions. Adapter-only success is insufficient. | NOT TESTED |
| A10 | Inspect delivered files and observed requests: no external dependency/service/downloaded asset, unexpected artifact or out-of-scope application write. | NOT TESTED |

Inspecting an empty directory proves absence of generated output; it does not count as passing A10 for a delivered application. Internal verification, a printed `FINAL`, and a blank-browser readiness test would not substitute for this protocol.

## Environment recorded at preparation

| Component | Recorded setup |
|---|---|
| Host | Windows; Python inventory reports 3.11.9; approximately 16 GB RAM |
| Python dependencies | Existing virtual environment: `rich 14.3.4`, `prompt_toolkit 3.0.53`, `playwright 1.63.0` |
| Model service | Existing Ollama `0.40.4`, loopback `http://127.0.0.1:11434` |
| Model | `gemma4:e4b`; digest `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` |
| Browser | Existing cached Chromium revision 1228, version `149.0.7827.55` |
| Planning | `current_recursive` |
| Browser classification | `field_scoped` |
| Other experiment policies | CLI defaults, including `worker_progress=current` and `mutation_grounding=current` |

GPU telemetry was unavailable/`UNKNOWN`; these records do not prove the hardware execution placement or why a request was slow. The existing model, Python environment and browser were reused. No model, package or browser download was performed for the runs or their documented validation.

Playwright's default expected browser revision was not the installed one. The existing launcher could discover `chromium.exe` on PATH, so preparation used a disposable full copy of the installed browser directory with an executable alias, then added only that directory to the launcher process's PATH. The unchanged discovery function and a real blank-page browser launch were checked. This established browser readiness, not Coin Courier functionality. Host-specific installation paths stay local.

## Actual CLI launch and task submission

Each `launch-run-NNN.ps1` was invoked interactively. The script checked that its numbered workspace was empty and transcript absent, set process-local PATH/model service/model storage/temp settings, changed to the repository for imports, started a non-clobbering transcript, and invoked the existing Python environment. It restored environment and location on exit.

The exact CLI arguments below are preserved; executable and directory paths are normalized placeholders rather than a copy-and-run command for another machine:

```powershell
& <existing-python.exe> -B <repository>/mini.py --no-bootstrap --workspace <experiment-root>/runs/run-NNN/workspace --mode current_recursive --experiment-case-id real-task-01 --verification-classification-policy field_scoped
```

At `You>`, the saved prompt was submitted once using bracketed paste and Enter. Runs 001–002 stopped before this point. No direct call to a Worker, manually supplied plan, implementation patch, synthetic tool result, or successful verifier result was injected. Native failures in 004–005 returned to the CLI, followed by `exit`; 003 and 006 required deliberate process termination as explained in their reports.

The outer PowerShell script printed Python's exit code rather than propagating it. Therefore outer exit 0 is not evidence of task success. Native structured events and the Python exit must be considered together.

## Expected pipeline and observed reach

The inspected workflow runs imports/dependencies and workspace setup, then host preflight, interactive submission, source ledger and clarification, project classification, conditional repository reconnaissance, specification and Project/Task Brain construction, adaptive task-fit/decomposition, Mission Compiler, Worker context preparation/authorization, tool execution, verification/recovery, and output delivery. Relevant entry code is [mini.py](../../mini.py); mechanisms include [host preflight](../../hivo/host_preflight.py), [requirement ingestion](../../hivo/requirements.py), [project understanding](../../hivo/project_understanding.py), [context sufficiency](../../hivo/context_sufficiency.py), and [Worker progress](../../hivo/worker_progress.py).

Only Run-006 reached actual Workers. It did not reach application mutation, application browser verification, integration of completed application work, or a normal root final verdict. The configured 28-step Worker budget should not be confused with context-gathering rounds: repeated checks consumed tool steps even while context remained at round zero.

## Isolation, evidence, and outcome definitions

All attempts started with a new `runs/run-NNN/workspace`, seeded from an immutable empty baseline. Logs, preparations and independent results were outside that subject workspace; Mini Hivo's hidden runtime state was retained inside it. Fresh workspaces prevented generated files or project memory from carrying across attempts. They did not reset model-service cache/loading state, so timing comparisons are observational, not a controlled performance benchmark.

The experiment used source base `f842fb8fb6e63e3064891d26ee0b24981e55c847` plus recorded uncommitted deltas. Per-attempt hashes/diffs, prompt copies, transcripts, structured JSONL, preflight records, observer summaries and acceptance records preserve revision identity. Later PR commits are publication revisions, not the historical commits used to execute the runs.

| Term | Meaning here |
|---|---|
| Successful stage | Evidence shows the stage completed; this does not imply later stages or the application passed. |
| Failure | A native unsuccessful result, import exception, exhausted request, or completed Worker budget failure. |
| Blocked | Progress prevented at an identified gate; preserve the native status separately from observer terminology. |
| Interrupted | Investigator stopped a still-active root; there is no natural root final result. Earlier completed child failures remain real observations. |
| NOT TESTED | No independent application behavior was exercised; no pass/fail score is invented. |
| Functional regression PASS | A specific Mini Hivo mechanism behaved as asserted in a recorded test, often with mocks; this is separate from agent capability. |

Original evidence files remain immutable. This published record normalizes unnecessary machine paths and includes bounded excerpts; it does not upload SQLite memory, full native prompts, raw terminal dumps, caches, browsers, temporary workspaces, or credentials. The [evidence index](EVIDENCE-INDEX.md) identifies what cannot be independently replayed from GitHub alone.
