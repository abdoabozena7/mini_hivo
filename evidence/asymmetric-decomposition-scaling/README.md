# Curated Evidence: Asymmetric Decomposition-Capability Scaling (`R_UPDATE_010`)

This directory contains the sanitized, reproducible public evidence corpus supporting [`docs/DECOMPOSITION_CAPABILITY_PAPER.md`](../../docs/DECOMPOSITION_CAPABILITY_PAPER.md) and [`updates/R_UPDATE_010.md`](../../updates/R_UPDATE_010.md) on branch `research/asymmetric-decomposition-weak-workers`.

## Summary of Empirical Corpus (`135` Multi-File System Builds, `211+` Worker Invocations)

1. **`local_scaling_summary.json` (`98` Local GPU Multi-File Runs, `0` Model Downloads)**
   - Executed on an NVIDIA GeForce RTX 3060 Laptop GPU (`6 GB` VRAM) across three already-installed quantized Ollama models:
     - `qwen2.5-coder:1.5b` (`986 MB` disk, `1,304 MB` VRAM, `167.8 tok/s`, `native_tool_calls=false`)
     - `qwen2.5-coder:3b` (`1.9 GB` disk, `2,300 MB` VRAM, `121.9 tok/s`, `native_tool_calls=false`)
     - `gemma4:e4b` (`3.1 GB` disk, `3,088 MB` VRAM, `76.7 tok/s`, `native_tool_calls=true`)
   - Captures all five cohorts:
     - `cohort_a_baseline_39` (`39` runs): `D0` Monolithic (`0/12` pass), `D1` `4B` Self-Split (`1/5` pass), `D2` Naive Oversplit (`0/5` pass), and `D4` Pre-DCVG exposing **Worker Verification Omission** (`VERIFICATION_NOT_APPLICABLE`).
     - `cohort_b1_dcvg_diff_repair_12` (`12` runs): Enabling **DCVG**, lifting `3B` on `B1` to `6/6` (`100%`) and `1.5B` to `5/6` (`83.3%`), while exposing `45`-call `edit_file_range` diff thrashing.
     - `cohort_b2_full_method_12` (`12` runs) + `cohort_b2_postfix_3b_3` (`3` runs): Full `D4 + DCVG + Whole-File Atomic Repair` (`3B` hits `100%` `6/6` on `B1_telemetry` in `30.76s` and `100%` `6/6` on `B5_rate_limiter` in `43.15s`, plus `4/6` on `B2_dag_scheduler`).
     - `cohort_d_threejs_granularity_sweep_32` (`32` runs): Full `3 -> 4 -> 5 -> 6 -> 7` module granularity sweep on *Orbital Prism Harvester 3D* (`threejs_showcase_7mod_3b_v9_flat_strict`: `RC=0`, `verified=true`, `8/8` nodes in `144.86s` on `qwen2.5-coder:3b` with `0` code-leakage violations), plus `1.5B` capability-floor control (`threejs_showcase_6mod_1_5b`: `0/7` nodes).

2. **`cloud_scaling_summary.json` (`37` Multi-File Weak/Legacy Cloud System Builds = `113` Worker Invocations)**
   - Evaluates 4 weak, legacy, or low-effort cloud worker models (`mai-code-1.1-flash`, `gpt-5.6-luna [low]`, `gemini-3.8-flash`, `claude-haiku-5.5 [low]`) across `B6_query_engine`, `B7_bytecode_vm`, and `B8_event_ledger`:
     - `D0` Monolithic: `8/12` (`66.7%` systems, `53/72` checks)
     - `D2` Naive Oversplit ($\kappa = 0.35$): **`0/12` (`0.0%` systems, `0/72` checks)** — universal interface-drift collapse
     - `D4` Contract-Atomic (`R=0`, $\kappa = 1.00$): **`11/12` (`91.7%` systems, `66/72` checks)**
     - `D4 + VG(1)` (`R<=1`, $\kappa = 1.00$): **`12/12` (`100.0%` systems, `72/72` checks)**

3. **`threejs-7mod-3b-deliverables/` (Complete 7-Module Three.js 3D WebGL Game Built `100%` by `qwen2.5-coder:3b`)**
   - `b9_7mod_plan.json`: Strict zero-code-leakage 7-leaf decomposition plan ($\kappa = 1.00$).
   - `game_state.js`, `arena_env.js`, `entities3d.js`, `bridge.js`, `hud_ui.js`, `app.js`, `index.html`: Exact LF-normalized deliverables produced by `qwen2.5-coder:3b` (`1.9 GB`) in `run_id: 20261123T062836-65b98eef`.
   - `deliverable_report.json`: Sanitized Mini Hivo run report (`exit_code: 0`, `verified: true`, `done_nodes: 8`, `total_nodes: 8`, `elapsed_seconds: 144.86`).

4. **`screenshots/` (Headless Chromium Playwright WebGL Visual Proofs)**
   - `01-3b-threejs-initial-8prisms.png`: Initial 3D arena (`8` crystals, `SCORE: 0`, `PRISMS: 0 / 8`, `PLAYING` status).
   - `02-3b-threejs-harvesting-75pts.png`: Active harvesting (ship moved to `(0, 6)`, `SCORE: 75`, `PRISMS: 3 / 8`, `PLAYING`).
   - `03-3b-threejs-paused-hud.png`: Paused state (`PAUSED` status, `Resume` button, position frozen under `move('up')`).
   - `04-3b-threejs-victory-200pts.png`: Victory state (`SCORE: 200`, `PRISMS: 8 / 8`, `VICTORY` status).

## Reproduction Commands (From Repository Root)

```powershell
# 1. Offline architectural, policy, DCVG, and applicability unit tests
.\.venv\Scripts\python.exe mini.py --self-test --no-bootstrap
.\.venv\Scripts\python.exe -m unittest tests.test_model_policy tests.test_asymmetric_swarm tests.test_verification_applicability -v

# 2. Reproduce the 7-module Three.js 3D WebGL build on local qwen2.5-coder:3b (requires local Ollama with gemma4:e4b & qwen2.5-coder:3b)
New-Item -ItemType Directory -Force output/repro-threejs-7mod-3b/workspace | Out-Null
Set-Content -Path output/repro-threejs-7mod-3b/prompt.txt -Value "Build Orbital Prism Harvester 3D modular WebGL game with game_state.js, arena_env.js, entities3d.js, bridge.js, hud_ui.js, app.js, and index.html."
.\.venv\Scripts\python.exe mini.py `
  --mode recursive `
  --decoding-policy fixed `
  --workspace output/repro-threejs-7mod-3b/workspace `
  --orchestrator-model gemma4:e4b `
  --worker-model qwen2.5-coder:3b `
  --decomposition-regime contract_atomic `
  --decomposition-plan evidence/asymmetric-decomposition-scaling/threejs-7mod-3b-deliverables/b9_7mod_plan.json `
  --prompt-file output/repro-threejs-7mod-3b/prompt.txt `
  --json-report output/repro-threejs-7mod-3b/deliverable_report.json `
  --no-bootstrap
```

## Privacy & Sanitization Policy

All raw SQLite state stores, runtime caches, and host-specific absolute paths remain privately preserved in ignored `output/asymmetric-decomposition-paper-20261122/`. Public JSON summaries replace local filesystem prefixes with `<workspace-path>` and use canonical LF line endings (`MANIFEST.json`).
