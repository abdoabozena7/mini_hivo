# Weak-Model Swarm Three.js WebGL Verification Evidence (`R_UPDATE_008`)

This directory contains curated, privacy-reviewed publication artifacts and sanitized derivatives for **R_UPDATE_008** (prepared 2026-11-22, UTC+02:00). Original raw logs, SQLite databases, host preflight markers, and trial workspaces remain preserved untouched in the gitignored local run directory `output/live-threejs-swarm-20261121/`. Zero personal absolute paths, hostnames, usernames, or runtime SQLite files are included in this package.

Related documentation:
- Update record: [`../../updates/R_UPDATE_008.md`](../../updates/R_UPDATE_008.md)
- Graduation North Star: [`../../docs/PROJECT_GOAL.md`](../../docs/PROJECT_GOAL.md)
- Swarm & Recursive Agent Charter: [`../../docs/AGENT_ARCHITECTURE.md`](../../docs/AGENT_ARCHITECTURE.md)

---

## 1. Curated Artifact Manifest & SHA-256 Provenance

Note on line-ending hash policy (`AGENTS.md`): Curated text artifacts under `evidence/threejs-weak-model-swarm/` are pinned to canonical LF (`text eol=lf` in `.gitattributes`) with trailing blank-line whitespace stripped so `git diff --cached --check` passes cleanly and working-tree bytes equal staged Git-blob bytes across platforms. Both the canonical LF staged-blob SHA-256 and the untouched original Windows run SHA-256 (`17,568` bytes, `c1503fa5...` in `deliverable-report-verified.json`) are recorded below.

| Curated artifact | Classification | Canonical LF / staged-blob bytes | Canonical LF / staged-blob SHA-256 | Original private source SHA-256 (`output/live-threejs-swarm-20261121/...`) |
|---|---|---:|---|---|
| [`prompt-neon-starfighter-3d.txt`](prompt-neon-starfighter-3d.txt) | Canonical LF derivative (trailing newline normalized) | `1,879` | `e84a3f3bf6ba02766ae5d78986eda7c8396ed1a08d7037d9f115794bc30fcd25` | `2c4de6c9d0b0e258452e5034d04465abadc26b0d990a494db33ec9f026b366aa` (`prompt-threejs-e2e-v4.txt`, `1,878` B) |
| [`deliverable-report-verified.json`](deliverable-report-verified.json) | Canonical LF derivative (privacy-clean JSON) | `907` | `f1789bb63ea59989fff65733d68a37ecab0c2936bfc2612af2305bc6d40352ba` | `3972f69da5778338238e1a5196da182c6018e8f854a8159d8771a8d2c6aa7dea` (`deliverable-report-e2e-verified-v9.json`, `945` B CRLF) |
| [`neon-starfighter-3d-index.html`](neon-starfighter-3d-index.html) | Canonical LF whitespace-normalized derivative of `gemma4:e4b` deliverable | `16,921` | `49dbf87e0469f7aa71eb2a095184fc1a39384a9c2650daed27ab3dbf514717e8` | `c1503fa5a026e6b1bf97a8d5748dc5107cec4a8f1933f8c8603f0712508160f8` (`workspace-threejs-e2e-verified-v9/index.html`, `17,568` B CRLF) |
| [`sanitized-v9-run-excerpt.txt`](sanitized-v9-run-excerpt.txt) | Sanitized derivative (lines 1..55, LF) | `7,188` | `9d6ed89aaafbdcc99897e4a9d6aabcf5371df02513430d48737d810df956b972` | Full log: `4abe3a513dbd254a6be30df09c65c42abf501a4353b5439bdc6df1d7650788c4` (`111,832` B); raw lines 1..55 slice: `8aff0d19aae42273111fbcccb78fb3c19a49e64527a36d06d7e9f1b3d50f20cf` (`6,604` B) |
| [`screenshots/01-initial-paused-hud.png`](screenshots/01-initial-paused-hud.png) | Binary PNG copy (external Playwright state 1) | `37,263` | `6104caebfedd51c91a0c51d03dab732d8689064d04e53d92bd88f0e0ca39357b` | `6104caebfedd51c91a0c51d03dab732d8689064d04e53d92bd88f0e0ca39357b` (`screenshots-v9-verified/01-initial-arena.png`) |
| [`screenshots/02-active-gameplay-flight-and-collect.png`](screenshots/02-active-gameplay-flight-and-collect.png) | Binary PNG copy (external Playwright state 2) | `155,674` | `e6a8687a787698a5d8b680def0d84e264e2caaa4a1fcdf3a9f7e7fbc18a3dc31` | `e6a8687a787698a5d8b680def0d84e264e2caaa4a1fcdf3a9f7e7fbc18a3dc31` (`screenshots-v9-verified/02-active-gameplay-flight-and-collect.png`) |
| [`screenshots/03-reset-clean-state.png`](screenshots/03-reset-clean-state.png) | Binary PNG copy (external Playwright state 3) | `154,802` | `78232d9baa5a64f22972fa6c2031ecaf97ec9d4465e7bc2994ed31b8c43965f5` | `78232d9baa5a64f22972fa6c2031ecaf97ec9d4465e7bc2994ed31b8c43965f5` (`screenshots-v9-verified/03-reset-clean-state.png`) |
| [`screenshots/04-verifier-victory-proof.png`](screenshots/04-verifier-victory-proof.png) | Binary PNG copy (controller `verify_web_app` proof) | `132,396` | `bed8a0e18a76fafa90354fd0e1ebf5deb16aaca94df8f3e8b8b77bb30e53770d` | `bed8a0e18a76fafa90354fd0e1ebf5deb16aaca94df8f3e8b8b77bb30e53770d` (`workspace-threejs-e2e-verified-v9/.agent_evidence/task_ROOT.png`) |

---

## 2. Verified Live `gemma4:e4b` Three.js E2E Run (`20261122T035103-a23aed75`)

- **Run ID:** `20261122T035103-a23aed75`
- **Model & policy:** `gemma4:e4b` under `SingleModelPolicy` (all 17 role slots pinned to `gemma4:e4b`, local Ollama only, zero cross-model fallback)
- **Tested `mini.py` `source_sha256`:** `3dec9b8e60a646c559135293f5a5ca11eb4fdd905304ef0f42785f9071a332ab` (on base commit `a3f1199`)
- **Mode & route:** `recursive` (`NEW_PROJECT` -> `TASK_BRAIN` -> `[FIT ROOT] EXECUTE` -> `Builder` -> `verify_web_app` -> `Falsifier` -> `[VERIFY ROOT] PASS` -> `[ROOT VERIFIED] PASS`)
- **Outcome & exit code:** `status = "done"`, `verified = true`, `exit_code = 0`
- **Telemetry ([`deliverable-report-verified.json`](deliverable-report-verified.json)):**
  - `model_calls`: `14` (`45,137` reported input tokens, `13,687` reported output tokens)
  - `tool_calls`: `9` (`context_sufficiency_check`, initial `write_file index.html`, two `VERIFICATION_NOT_APPLICABLE` `npm` probes cleanly handled without poisoning routes, refined `write_file index.html`, `list_files`, `read_file index.html`, `verify_web_app index.html`, and one rightly refused `Falsifier` `write_file` mutation probe)
  - `browser_checks`: `2`, `repairer_calls`: `0`, `splits`: `0`, `elapsed_seconds`: `284.67`
- **Persisted deliverable ([`neon-starfighter-3d-index.html`](neon-starfighter-3d-index.html)):**
  - `17,568` bytes (`sha256: c1503fa5a026e6b1bf97a8d5748dc5107cec4a8f1933f8c8603f0712508160f8`)
  - Valid `<script type="importmap">` + `<script type="module">` loading `three@0.160.0` (`WebGLRenderer`, `PerspectiveCamera` at `(0, 9, 14)`, `AmbientLight` + `DirectionalLight`, `GridHelper(24, 24, 0x00f5ff, 0x1e293b)`, 10,000-vertex `THREE.Points` starfield, glowing cyan `ConeGeometry` + `BoxGeometry`-winged starship, and 8 rotating golden `OctahedronGeometry` crystals).

---

## 3. Independent Interactive Playwright State Transitions & Visual Proof

In addition to Mini Hivo's internal `verify_web_app` check (which exercised `keyboard_movement`, `collection_updates_state`, `collision_game_over`, `restart_resets_state`, and `goal_win_state`, saving [`screenshots/04-verifier-victory-proof.png`](screenshots/04-verifier-victory-proof.png)), an independent external headless Chromium Playwright session served the persisted `index.html` over HTTP at `1440x900` and verified live state transitions via `window.AGENT_GAME` and keyboard events with zero console, page, or network errors:

1. **Initial Load (`paused`) — [`screenshots/01-initial-paused-hud.png`](screenshots/01-initial-paused-hud.png):**
   - `window.AGENT_GAME.getState()` -> `status = "paused"`, `score = 0`, `collected = 0`, `position = {x: 0, y: 0.5, z: 0}`.
   - Renders `#050816` space backdrop, glowing cyan `"Neon Starfighter 3D"` HUD header, amber `PAUSED` badge, `SCORE: 0`, `CRYSTALS: 0`, `START GAME` / `RESET` controls, and `WASD / Arrows: Move` legend (`renderer.render` starts when `animate()` begins on `START GAME` / `start()`).
2. **Active Flight & Crystal Collection (`playing`) — [`screenshots/02-active-gameplay-flight-and-collect.png`](screenshots/02-active-gameplay-flight-and-collect.png):**
   - Clicking `START GAME` (`start()`), holding `ArrowUp`/`KeyW` + `ArrowRight`/`KeyD` (6 steps x `0.15` units along `-Z` and `+X`), and triggering 3 crystal collections transitions `getState()` to `status = "playing"`, `score = 30`, `collected = 3`, `player = {x: 0.9, z: -0.9}`, `position = {x: 0.9, y: 0.5, z: -0.9}`.
   - Screenshot confirms full-viewport WebGL rendering: 3D `THREE.Points` starfield, perspective cyan/slate `GridHelper`, 8 golden `OctahedronGeometry` crystals, green `PLAYING` badge, `SCORE: 30`, `CRYSTALS: 3`, and the cyan starship visibly displaced forward-right off the origin crosshairs.
3. **Clean Reset (`restart()`) — [`screenshots/03-reset-clean-state.png`](screenshots/03-reset-clean-state.png):**
   - Clicking `RESET` (`restart()`) restores `getState()` to `status = "playing"`, `score = 0`, `collected = 0`, `player = {x: 0, z: 0}`, `position = {x: 0, y: 0.5, z: 0}`.
   - Screenshot confirms HUD counters return to `SCORE: 0` / `CRYSTALS: 0`, the cyan starship snaps back onto the `(0, 0.5, 0)` origin crosshairs, and all 8 golden crystals are visible.
4. **Controller Verifier Victory Proof — [`screenshots/04-verifier-victory-proof.png`](screenshots/04-verifier-victory-proof.png):**
   - Saved automatically at `.agent_evidence/task_ROOT.png` during `run_id: 20261122T035103-a23aed75` after `forceWin()`, showing green `VICTORY!` badge over the rendered 3D arena.

---

## 4. Negative Model-Capability Control (`--model laya:latest`)

To verify that `validate_generative_model_capabilities` (`hivo/model_policy.py`) blocks encoder/classifier-only local Ollama models before wasting preflight or task budgets, `mini.py` was invoked against installed `laya:latest` (a 421M `modern-bert` encoder reporting Ollama capabilities `['decision']` without `'completion'` or `'chat'`):

- **Retained private log:** `output/live-threejs-swarm-20261121/neg-laya.log` (`702` bytes UTF-16LE, `original_sha256: 47c14c5e3b892573faafc35ac8884834ac38e410168a9cb07959783959e40e73`)
- **Observed exit code:** `2` (`[SETUP_ERROR]`, zero canary calls, zero task model calls, workspace untouched)
- **Sanitized output:**
  ```text
  workspace set to: <workspace>/neg-laya-workspace

  [SETUP_ERROR] model 'laya:latest' reports capabilities ['decision'] without text/chat 'completion' support (e.g., encoder/classifier/embedding-only model) and cannot run generative coding roles; choose a generative Ollama model such as 'gemma4:e4b'
  ```

---

## 5. Retained Diagnostic Progression (`v1..v8`) & Multi-File Recursive Boundary Runs

In accordance with `AGENTS.md`, every failed, budget-exhausted, and boundary run executed during live `gemma4:e4b` validation is preserved unmodified in `output/live-threejs-swarm-20261121/` and reported below without omission.

### 5.1 Single-File Three.js E2E Diagnostic Progression (`v1..v9`)

| Trial | Run ID | Status (`exit_code`) | Model / tool calls | Browser checks | `evidence_licensed_corrections` | Primary stopping boundary / bug uncovered & fixed before `v9` |
|---|---|---|---:|---:|---:|---|
| `v1` | `20261122T015534-16e67389` | `budget_exhausted` (`1`) | `45` / `35` | `6` | `0` | `RUN_BUDGET_EXHAUSTED: model` — exposed `Object3D` cycle risk, verbose `verify_web_app` receipt overflow (`>1600` chars), and `Repairer` inability to rewrite unverified greenfield drafts |
| `v2` | `20261122T020904-a8859c14` | `failed` (`1`) | `32` / `27` | `6` | `1` | `BROWSER_VERIFICATION_STAGNATION` — ES-module CDN load race evaluated `window.AGENT_GAME` before module script execution finished |
| `v3` | `20261122T022220-ce4bd3e9` | `failed` (`1`) | `41` / `36` | `6` | `1` | `BROWSER_VERIFICATION_STAGNATION` — `result_failed` substring false-positive on nested optional fields + pre-mutation failure carry-over |
| `v4` | `20261122T023327-ba4af3b1` | `failed` (`1`) | `36` / `28` | `6` | `1` | `BROWSER_VERIFICATION_STAGNATION` — rendered full 3D scene and passed 4/5 game checks, missing only `keyboard_movement` prior to multi-direction `move('forward')` + held-key `ArrowUp`/`KeyW` probe |
| `v5` | `20261122T024634-ecfc3e67` | `failed` (`1`) | `43` / `34` | `9` | `0` | `CONTEXT_INSUFFICIENT` on fallback strategy after `Builder` repeated `read_file` + `run_file("index.html")` 9 times without mutating (`stagnant_verifications` previously watched `verify_web_app` only, not `run_file` on `.html`) |
| `v6` | `20261122T025628-e1b9f659` | `budget_exhausted` (`1`) | `36` / `25` | `4` | `0` | `RUN_BUDGET_EXHAUSTED: elapsed` (`600.05s` wall-clock admission limit) |
| `v7` | `20261122T032447-9b3145e1` | `failed` (`1`) | `31` / `24` | `6` | `1` | `BROWSER_VERIFICATION_STAGNATION` — unclosed `<script type="importmap">` tag swallowed subsequent module code before `_InlineJavaScript` importmap JSON validator was added |
| `v8` | `20261122T033900-dd9ae153` | `failed` (`1`) | `30` / `23` | `3` | `0` | `CONTEXT_INSUFFICIENT` on post-failure strategy retry in rolled-back empty greenfield workspace |
| **`v9`** | **`20261122T035103-a23aed75`** | **`done` (`0`, `verified=true`)** | **`14` / `9`** | **`2`** | **`0`** | **Passed all deterministic syntax, WebGL canvas, 5-interaction `AGENT_GAME`, and `Falsifier` gates; persisted `17,568`-byte `index.html`** |

### 5.2 Multi-File Recursive Weak-Model Boundary Trials (Unverified Live Completion)

| Trial / Deliverable domain | Run ID & `source_sha256` | Topology | Telemetry | Outcome (`exit_code`) | Honest boundary diagnosis |
|---|---|---|---|---|---|
| Modular Three.js `"Cyber Prism Arena 3D"` (`index.html` + `game.js` + `style.css`) | `20261122T040024-19968a9e` (`3dec9b8e...`) | `[FIT ROOT] SPLIT` (`splits=1`, `max_depth=1`, `leaf_tasks=4`, `total_nodes=5`) | `model_calls=65`, `tool_calls=57`, `browser_checks=4`, **`evidence_licensed_corrections=2`**, `770.66s` | `budget_exhausted` (`1`, `verified=false`) | Proved live `Evidence-Licensed Gate` activation (`[EVIDENCE-LICENSED CORRECTION 1] STALE_TARGET_OR_RANGE` + second same-authority correction) without runaway re-splitting, but cross-file ES-module coordination (`index.html` <-> `game.js` <-> `style.css`) consumed the 65-call budget before Root integration |
| Multi-file Python `"Swarm Telemetry Analyzer"` (`metrics.py`, `cli.py`, `test_metrics.py`) | `20261122T045001-11fb390d` (`8fe5905c...`) | `[FIT ROOT] SPLIT` (`splits=1`, `max_depth=1`, `leaf_tasks=3`, `total_nodes=4`, `done_nodes=1`, `failed_nodes=3`) | `model_calls=73`, `tool_calls=62`, `browser_checks=0`, `evidence_licensed_corrections=0`, `465.64s` | `failed` (`1`, `verified=false`) | Child 1 (`metrics.py` + `test_metrics.py`) passed `unittest`, `Falsifier`, and `[VERIFY 1] PASS` (committing `metrics.py` `764` B and `test_metrics.py` `2,026` B), but Child 2 (`cli.py`) repeatedly attempted unauthorized/refused edits to Child 1's verified files and stopped at `WORKER_NO_MUTATION_PROGRESS` |

---

## 6. Root-Relative Reproduction Commands

From the repository root, using workspace-local temporary storage:

```powershell
New-Item -ItemType Directory -Force .verification-temp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.verification-temp'
$env:TMP = $env:TEMP

# 1. Focused deterministic, controlled-functional, and real-Playwright suites (71 tests, offline)
.\.venv\Scripts\python.exe -B -X utf8 -m unittest `
  tests.test_evidence_licensed_gate `
  tests.test_threejs_quality_verification `
  tests.test_deliverable_backend `
  tests.test_integrated_swarm_lifecycle `
  tests.test_evidence_policy `
  tests.test_ingestion_integration -v

# 2. Built-in deterministic self-test (offline)
.\.venv\Scripts\python.exe -B -X utf8 mini.py --self-test --no-bootstrap

# 3. Negative capability control (requires local non-generative model, e.g. laya:latest; exits 2)
New-Item -ItemType Directory -Force .\output\repro-neg-laya | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 mini.py `
  --workspace .\output\repro-neg-laya `
  --prompt-file .\evidence\threejs-weak-model-swarm\prompt-neon-starfighter-3d.txt `
  --model laya:latest `
  --no-bootstrap

# 4. Fresh live weak-model Three.js E2E run (requires explicit live-execution approval + Ollama gemma4:e4b)
New-Item -ItemType Directory -Force .\output\repro-threejs-live | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 mini.py `
  --mode recursive `
  --workspace .\output\repro-threejs-live `
  --prompt-file .\evidence\threejs-weak-model-swarm\prompt-neon-starfighter-3d.txt `
  --model gemma4:e4b `
  --json-report .\output\repro-threejs-live-report.json `
  --no-bootstrap `
  --max-model-calls 45 `
  --max-tool-calls 50 `
  --max-elapsed-seconds 600
```
