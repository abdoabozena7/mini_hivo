# Assume-Guarantee Swarm Contracts, Hardware-Aware Adaptive Decoding & Visual-Execution Verification Evidence (`R_UPDATE_009`)

This directory contains curated, privacy-reviewed publication artifacts, deliverables, screenshots, and sanitized execution excerpts for **R_UPDATE_009** (prepared 2026-11-22, UTC+02:00). Original raw logs, `.agent_experiment.jsonl` traces, `.agent_runs/` telemetry, `.agent_host_preflight.json` markers, SQLite databases, and trial workspaces remain preserved untouched in the gitignored local run directory `output/live-agiss-paper-cohort-20261122/`. Zero personal absolute paths, usernames, host inventories, or runtime SQLite files are included in this package.

Related documentation:
- Update record: [`../../updates/R_UPDATE_009.md`](../../updates/R_UPDATE_009.md)
- Prior baseline update: [`../../updates/R_UPDATE_008.md`](../../updates/R_UPDATE_008.md)
- Research paper: [`../../docs/RESEARCH_PAPER.md`](../../docs/RESEARCH_PAPER.md)
- Graduation North Star: [`../../docs/PROJECT_GOAL.md`](../../docs/PROJECT_GOAL.md)
- Swarm & Recursive Agent Charter: [`../../docs/AGENT_ARCHITECTURE.md`](../../docs/AGENT_ARCHITECTURE.md)

---

## 1. Curated Artifact Manifest & SHA-256 Provenance

Note on line-ending hash policy (`AGENTS.md`): Curated text, code, JSON, and HTML artifacts under `evidence/agiss-swarm-research/**` are pinned to canonical LF (`text eol=lf` in `.gitattributes`) with trailing line whitespace stripped so `git diff --cached --check` passes cleanly and working-tree bytes match staged Git-blob bytes across platforms. PNG screenshots are pinned to `binary` and match their untouched private sources byte-for-byte. Both canonical LF / staged-blob SHA-256 digests and untouched original Windows source SHA-256 digests (`hashlib.sha256`) are recorded below.

| Curated artifact | Classification | Canonical LF / binary bytes | Canonical LF / staged-blob SHA-256 | Untouched private source (`output/live-agiss-paper-cohort-20261122/...`) | Original source bytes | Original source SHA-256 |
|---|---|---:|---|---|---:|---|
| [`prompt-python-recursive-swarm.txt`](prompt-python-recursive-swarm.txt) | Canonical LF prompt copy | `977` | `e5cf961ed81e1dab5be3da3e477700debb6cd8357c2cc2e4f8e8ae43e708414e` | `prompt-python-recursive-swarm.txt` | `981` | `9e71a86c14224c0830e8deaef01e0a2b9a7563bcaaa248e41132ad5f190b3f40` |
| [`report-python-multifile-verified.json`](report-python-multifile-verified.json) | Canonical LF `--json-report` (`py v9`) | `1,789` | `822f542a226e8345544236753a0d2cc8f0d03bd6f4911b0d8f91361da2529d54` | `report-py-multifile-gemma-agiss-live-v9.json` | `1,835` | `c3115efc97c3e61ffed53f87804219334f53021c3d879dc1058723c6685de409` |
| [`python-deliverables/metrics.py`](python-deliverables/metrics.py) | Canonical LF whitespace-clean Child 1 artifact | `739` | `f5265c7fc21e49a2a301a6862c3b5f256346ef708b6419e5ce8f6621bcc42e75` | `workspace-py-multifile-gemma-agiss-live-v9/metrics.py` | `767` | `b4bfde1f26c427d53f46f90b2a118eaeeed05693ad206e2766ac02a47a1bb238` |
| [`python-deliverables/cli.py`](python-deliverables/cli.py) | Canonical LF whitespace-clean Child 2 artifact | `2,054` | `a5a8b0506599e1e49f69f9eb1f5e34c75af039421ff6f475c4111d6e1e8448a4` | `workspace-py-multifile-gemma-agiss-live-v9/cli.py` | `2,148` | `28decbd9e8af4ed2d59f5f42fa4abe6c12ad7b02a0b6aab5eaa1e44cb40c6f56` |
| [`python-deliverables/test_metrics.py`](python-deliverables/test_metrics.py) | Canonical LF whitespace-clean Child 3 artifact | `1,514` | `002978e932cb92b7d8f4039b02186731dce71cf0a166cc6dc0c3215f44153f21` | `workspace-py-multifile-gemma-agiss-live-v9/test_metrics.py` | `1,545` | `04375991a45362933057ad23a589db0e26e2e2466307c4c085ceff1125db9f8b` |
| [`sanitized-python-v9-excerpt.txt`](sanitized-python-v9-excerpt.txt) | Sanitized LF excerpt (lines 1..165) | `22,812` | `681e2a7e0a46315d3f150bb16f2ddce6cb49754b8a472cf66bc081db4e2862f8` | `run-py-multifile-gemma-agiss-live-v9.log` (raw slice `1..165`: `22,256` B, `14dcea32...`) | `96,041` | `d74eb80be5d9558e827402351f9d01092c3ef26728a747a5833706a1f805840a` |
| [`report-threejs-starfighter-agiss-verified.json`](report-threejs-starfighter-agiss-verified.json) | Canonical LF `--json-report` (`threejs v8`) | `905` | `ac42271eecff8e2a64d8f22d45a978c24080a1a3e1722ef7b1bd350b26c13e61` | `report-threejs-starfighter-agiss-live-v8.json` | `943` | `3b54e00dbe77af22ff79b391790a1d284c40cb317e37a09b8a3f7582b2978c8b` |
| [`neon-starfighter-3d-agiss-index.html`](neon-starfighter-3d-agiss-index.html) | Canonical LF whitespace-clean `gemma4:e4b` Three.js HTML | `18,099` | `bfeeefc183be89b6da631153a4f0d8d0826d005e95ca029bc6c51610706041de` | `workspace-threejs-starfighter-agiss-live-v8/index.html` | `18,751` | `f6673118af7169b0400430f824d8d8e6e41a1d840e0e2a0b23f0a8dde58f1665` |
| [`sanitized-threejs-v8-excerpt.txt`](sanitized-threejs-v8-excerpt.txt) | Sanitized LF excerpt (lines 1..63) | `4,804` | `958c356542572b8bd20289167a4d6fb19503e1016f59730cafd42fef33314ece` | `run-threejs-starfighter-agiss-live-v8.log` (raw slice `1..63`: `4,328` B, `63226c7a...`) | `108,715` | `1f3644d8ecc684138e5e5b02e394227bbca253fa863174be586ad4acd22a5b77` |
| [`screenshots/01-initial-load-live-3d-before-start.png`](screenshots/01-initial-load-live-3d-before-start.png) | Exact binary PNG (external Playwright state 1) | `140,293` | `7d5ae44d62019f9d457f20b2efd440e13bfa0ad1604046d233a409cd079b3049` | `screenshots-v8-human-verified/01-initial-load-live-3d-before-start.png` | `140,293` | `7d5ae44d62019f9d457f20b2efd440e13bfa0ad1604046d233a409cd079b3049` |
| [`screenshots/02-active-flight-and-crystal-collection.png`](screenshots/02-active-flight-and-crystal-collection.png) | Exact binary PNG (external Playwright state 2) | `143,280` | `c54ac8a5a434e8498ede5f738a9fb1fcd7dff0b6b90bca9c92ec48dfcd9f4d7d` | `screenshots-v8-human-verified/02-active-flight-and-crystal-collection.png` | `143,280` | `c54ac8a5a434e8498ede5f738a9fb1fcd7dff0b6b90bca9c92ec48dfcd9f4d7d` |
| [`screenshots/03-reset-clean-origin-state.png`](screenshots/03-reset-clean-origin-state.png) | Exact binary PNG (external Playwright state 3) | `143,196` | `e268758cc88e6d034efa004bd43f7d708b9c9f75dcd00b78382da534f9fd8f32` | `screenshots-v8-human-verified/03-reset-clean-origin-state.png` | `143,196` | `e268758cc88e6d034efa004bd43f7d708b9c9f75dcd00b78382da534f9fd8f32` |
| [`screenshots/04-controller-verifier-proof.png`](screenshots/04-controller-verifier-proof.png) | Exact binary PNG (`.agent_evidence/task_ROOT.png`) | `139,440` | `4c0d39835281506ad58352ab21c6694ae3b629336ae0294a4d0537af5207cc3a` | `screenshots-v8-human-verified/04-controller-verifier-proof.png` | `139,440` | `4c0d39835281506ad58352ab21c6694ae3b629336ae0294a4d0537af5207cc3a` |

---

## 2. Verified Live Multi-File Recursive Python Swarm Runs (`v8` & `v9` on `gemma4:e4b`)

In `R_UPDATE_008` (`run_id: 20261122T045001-11fb390d`), multi-file recursive Python generation on `gemma4:e4b` failed (`0/5` verified multi-file completions overall; Child 1 stole `test_metrics.py` alongside `metrics.py`, and Child 2 stalled on `WORKER_NO_MUTATION_PROGRESS` attempting refused edits against Child 1's locked files). With **Assume-Guarantee Disjoint Child Ownership** (`hivo/assume_guarantee.py`), **read-only sibling AST certificate projection**, **deferred sibling test `[not_applicable]` guards**, **RFC-8259 numeric `check_call` equivalence**, and **hardware-aware adaptive decoding (`--decoding-policy adaptive`)**, `gemma4:e4b` achieved **two consecutive `4/4`-node verified completions**:

- **Prompt ([`prompt-python-recursive-swarm.txt`](prompt-python-recursive-swarm.txt)):** 3-file Python stdlib `"Swarm Telemetry Analyzer"` (`metrics.py`, `cli.py`, `test_metrics.py`).
- **Model & policy:** `gemma4:e4b` under `SingleModelPolicy` (all 17 role slots pinned to `gemma4:e4b`, local Ollama only, `--decoding-policy adaptive`).
- **Tested `mini.py` `source_sha256`:** Live `py v8`/`py v9` and `threejs v8` runs executed at `3bf32fbdab883b9f17ab1baaf73abe28d02383e335ae15a8b18acc89e0a97492` (`1,699,110` B, on base commit `3b2d8b5`); final post-review `mini.py` verified across all `2,163` offline tests (`2,152` passed, `0` failed, `11` skipped) + `--self-test` is `03ebfa8af7cd1ff01e0ab70ef9b476c7a1f5ff83eac380d30a6e423d8cd62b61` (`1,699,800` B).
- **Recursive execution topology ([`sanitized-python-v9-excerpt.txt`](sanitized-python-v9-excerpt.txt)):**
  1. `[FIT ROOT] SPLIT` (`splits = 1`, `leaf_tasks = 3`, `total_nodes = 4`) with disjoint ownership: Child 1 owns `["metrics.py"]`, Child 2 owns `["cli.py"]` (reading `metrics.py` certificate), Child 3 owns `["test_metrics.py"]` (reading `metrics.py` and `cli.py` certificates).
  2. **Child 1 (`metrics.py`):** `Builder` writes `metrics.py` and executes `run_file("metrics.py")`; `Falsifier` audits; `[VERIFY 1] PASS` -> `[DONE 1]`.
  3. **Child 2 (`cli.py`):** Receives sealed `ASSUME-GUARANTEE SIBLING CONTRACT` for `metrics.summarize_latencies(values: List[float]) -> Dict[str, float]`; `Builder` writes `cli.py` with `json.dumps(result, sort_keys=True)` and exit code `2` on invalid/empty `--values`, verifies `python cli.py --values 10.5,20.1,30.0`; `Falsifier` attempts cross-file mutation probes (`test_metrics.py`), blocked deterministically by disjoint scope; `[VERIFY 2] PASS` -> `[DONE 2]`.
  4. **Child 3 (`test_metrics.py`):** Writes and refines `unittest` suite `test_metrics.py`, runs `python -m unittest test_metrics.py` (`OK`); `Falsifier` audits `metrics.py` and `test_metrics.py`; `[VERIFY 3] PASS` -> `[DONE 3]`.
  5. **Root Aggregation (`[AGGREGATE ROOT]`):** `[INTEGRATION PREFLIGHT ROOT] PASS (0 conflict(s))` (`verify_compositional_certificates` confirms zero cross-file symbol/import conflicts); Root `Builder` and `Falsifier` verify `python -m unittest test_metrics.py` (`exit 0`) and `python cli.py --values ""` (`exit 2`); `[VERIFY ROOT] PASS` -> `[ROOT VERIFIED] PASS` -> `exit_code = 0`.

| Verified run | Run ID | Status (`exit_code`) | Topology (`done/total`) | Model / tool calls | Input / output tokens | Elapsed (s) | Persisted deliverables (untouched source bytes & SHA-256) |
|---|---|---|---:|---:|---:|---:|---|
| **`py v8`** | `20261122T140443-fb94f671` | `done` (`0`, `verified=true`) | `splits=1`, `4/4` | `38` / `23` | `126,220` / `9,818` | `198.46` | `metrics.py` (`767` B, `b4bfde1f...`), `cli.py` (`2,558` B, `d8deabca...`), `test_metrics.py` (`1,416` B, `7ed7096e...`) |
| **`py v9`** ([report](report-python-multifile-verified.json)) | `20261122T140910-1b993032` | `done` (`0`, `verified=true`) | `splits=1`, `4/4` | `49` / `33` | `159,905` / `10,879` | `211.89` | [`metrics.py`](python-deliverables/metrics.py) (`767` B, `b4bfde1f...`), [`cli.py`](python-deliverables/cli.py) (`2,148` B, `28decbd9...`), [`test_metrics.py`](python-deliverables/test_metrics.py) (`1,545` B, `04375991...`) |

---

## 3. Verified Live Three.js 3D WebGL Run (`v8`, `20261122T153409-45b4cd0f`) & Visual Proof

In `R_UPDATE_008` (`20261122T035103-a23aed75`), the verified Three.js artifact left `<canvas>` unrendered during initial `PAUSED` load (`initialCenterLuminanceStd = 0.0` until `START GAME` was clicked), hid collected crystals without respawning, and required `14` model calls (`284.67s`). With the upgraded `threejs_3d` visual-workmanship rubric, pre-`start()` JPEG center-playfield luminance oracle (`initialFrameBlank`), HUD bounding-box anti-overlap gate (`hudOverlapCount`), word-boundary profile inference (`\b(?:win|won|goal|finish)\b`, `\b(?:touch|mobile|responsive controls)\b`), `projected[1]` task-prompt protection in `hivo/context.py`, and calibrated `T_0 = 0.08` adaptive `Builder` decoding:

- **Run ID:** `20261122T153409-45b4cd0f` ([`report-threejs-starfighter-agiss-verified.json`](report-threejs-starfighter-agiss-verified.json), [`sanitized-threejs-v8-excerpt.txt`](sanitized-threejs-v8-excerpt.txt))
- **Outcome:** First-draft pass (`status = "done"`, `verified = true`, `exit_code = 0`, `repairer_calls = 0`, `evidence_licensed_corrections = 0`)
- **Telemetry:** `model_calls = 8` (`43%` fewer than `R_UPDATE_008`), `tool_calls = 4` (`context_sufficiency_check`, `write_file index.html`, `Builder` `verify_web_app`, `Falsifier` `verify_web_app`), `browser_checks = 3`, `input_tokens = 32,138`, `output_tokens = 7,574`, `elapsed_seconds = 184.04` (`35%` faster than `R_UPDATE_008`).
- **Persisted deliverable ([`neon-starfighter-3d-agiss-index.html`](neon-starfighter-3d-agiss-index.html)):** `18,751` bytes (`sha256: f6673118af7169b0400430f824d8d8e6e41a1d840e0e2a0b23f0a8dde58f1665`), featuring continuous `animate()` WebGL rendering from `init()` (even while `PAUSED`), immediate random spherical crystal respawn on collection (`radius = 4 + Math.random() * 5`), `hudOverlapCount = 0`, and `initialFrameBlank = False`.

### Independent External Playwright 3-State Verification (`1440x900`) & Controller Proof

1. **Initial Load (`PAUSED`, Pre-Start Live 3D Render) — [`screenshots/01-initial-load-live-3d-before-start.png`](screenshots/01-initial-load-live-3d-before-start.png):**
   - Captured immediately on page load **before** clicking `START GAME`: `status = "paused"`, `Score: 0`, `Crystals: 0`, `initialFrameBlank = False`, `hudOverlapCount = 0`.
   - Full 3D starfield (`THREE.Points`), perspective cyan/slate `GridHelper`, glowing cyan starfighter at `(0, 0.5, 0)`, and 8 golden `OctahedronGeometry` crystals are visibly rendered behind the non-overlapping top HUD and bottom control bar.
2. **Active Flight & Crystal Collection (`PLAYING` + Respawn) — [`screenshots/02-active-flight-and-crystal-collection.png`](screenshots/02-active-flight-and-crystal-collection.png):**
   - Clicking `START GAME`, flying via keyboard input, and collecting 3 crystals transitions HUD to green `PLAYING`, `Score: 30`, `Crystals: 3`, while collected crystals respawn at fresh coordinates.
3. **Clean Origin Reset (`RESET`) — [`screenshots/03-reset-clean-origin-state.png`](screenshots/03-reset-clean-origin-state.png):**
   - Clicking `RESET` restores `Score: 0`, `Crystals: 0`, centers the cyan starfighter back at `(0, 0.5, 0)`, and re-randomizes the 8 golden crystals with zero console/page/network errors.
4. **Controller Verifier Proof — [`screenshots/04-controller-verifier-proof.png`](screenshots/04-controller-verifier-proof.png):**
   - Automatically captured at `.agent_evidence/task_ROOT.png` during `run_id: 20261122T153409-45b4cd0f`.

---

## 4. Hardware-Aware Hyperparameter Law (RTX 3060 6GB WDDM `num_ctx` Phase Transition)

Empirical profiling of `gemma4:e4b` on a 6 GB WDDM Laptop GPU (`5,985 MB` usable VRAM) uncovered a sharp step-function latency cliff governed by KV-cache sizing (`num_ctx`) and resident Ollama `/api/ps` eviction:

| Regime & model | `num_ctx` | Total memory footprint | GPU VRAM residency | Decode throughput (`tok/s`) | Architectural consequence & controller invariant |
|---|---:|---:|---:|---:|---|
| `gemma4:e4b` (default / compact) | `4,096` | `3,083 MB` | `3,083 MB` (`100%` GPU) | **`98.5 tok/s`** | Fast baseline leaf execution |
| `gemma4:e4b` (medium context) | `6,144` | `3,085 MB` | `3,085 MB` (`100%` GPU) | **`97.9 tok/s`** | Zero throughput penalty vs. `4,096` |
| `gemma4:e4b` (**un-evicted** concurrent `/api/ps` resident model) | `8,192` | `9,020 MB` (`+5.94 GB`) | `0 MB` (`0%` GPU, CPU-spilled) | **`4.0 tok/s` (`24.5x` slower)** | Caused `py agiss-v2` (`20261122T115130-55e22179`) to exhaust `540.09s` in 15 calls; fixed by pre-preflight `/api/ps` `keep_alive: 0` eviction (`mini.py`) |
| `gemma4:e4b` (**evicted** sole-resident GPU regime) | `8,192`–`10,240` | `~3,085 MB` | `100%` GPU | **`~98 tok/s`** | `ask_ollama` (`decoding_policy="adaptive"`) caps `context_window <= 10,240` when `estimate + builder_predict <= 10,240`, preventing truncation on `6,144`-token greenfield drafts |
| `gemma4:e4b` (**KV-cache VRAM cliff**) | `>= 11,264` | `+5.95 GB` jump (`~9.03 GB`) | WDDM CPU spill | Severe CPU-offload degradation | Hard ceiling avoided by `10,240` adaptive cap unless prompt tokens exceed `8,192` |
| `qwen2.5-coder:3b` (cross-model reference) | `8,192` | `2,299 MB` | `2,299 MB` (`100%` GPU) | **`100.0 tok/s`** | Fits comfortably in 6 GB VRAM; emits content-JSON tool calls handled via `text_json_tool_adapter_active` |

In addition, calibrating Epoch-0 `Builder` adaptive decoding from `T_0 = 0.15` (`threejs v6`: `34,656` output tokens, `660.05s` timeout) down to **`T_0 = 0.08, min_p = 0.08, top_p = 0.90`** while reserving higher temperatures (`0.20..0.48`) + prime-stride `7919` seed rotation strictly for `epoch >= 1` / `stagnant_count >= 1` / `Repairer` reduced `threejs v8` output generation `4.6x` (`7,574` tokens, `184.04s`, `exit_code = 0`).

---

## 5. Complete Retained Diagnostic Progression (`output/live-agiss-paper-cohort-20261122/`)

Per `AGENTS.md`, every failed, host-preflight-blocked, cross-model, and budget-exhausted trial executed during this research cohort is preserved untouched and accounted for below without reclassification.

### 5.1 Multi-File Recursive Python Progression (`py` Cohort)

| Trial label (log / report) | Run ID & model | Status (`exit_code`) | `done/total` nodes | Model / tool calls | Output tokens | Elapsed (s) | Earliest stopping boundary & engineering defect uncovered |
|---|---|---|---:|---:|---:|---:|---|
| `agiss-v1` (`run-py-multifile-agiss-v1.log`) | `(preflight)` `gemma4:e4b` | `preflight_fail` (`2`) | `0/0` | `0` / `0` | `0` | `<5` | `HIVO HOST PREFLIGHT: FAIL` under un-evicted resident VRAM contention -> motivated pre-preflight `/api/ps` `keep_alive: 0` eviction |
| `agiss-v2` (`report-py-multifile-agiss-v2.json`) | `20261122T115130-55e22179` (`gemma4:e4b`) | `budget_exhausted` (`1`) | `0/4` | `15` / `7` | `4,364` | `540.09` | `RUN_BUDGET_EXHAUSTED: elapsed` — exposed the `24.5x` (`4.0 tok/s`) WDDM VRAM-cliff slowdown at `num_ctx=8192` with un-evicted models |
| `qwen3b` (`report-py-multifile-qwen3b-agiss.json`) | `20261122T122340-d28245d6` (`qwen2.5-coder:3b`) | `failed` (`1`) | `0/1` | `6` / `0` | `1,326` | `25.05` | `CONTEXT_SUFFICIENCY_REQUIRED` — `qwen2.5-coder:3b` serialized tool calls as `<tool_call>`/JSON text in `message["content"]` |
| `qwen3b-v2` (`report-py-multifile-qwen3b-agiss-v2.json`) | `20261122T122922-93962157` (`qwen2.5-coder:3b`) | `failed` (`1`) | `0/1` | `31` / `26` | `4,897` | `51.76` | `CONTEXT_SUFFICIENCY_REQUIRED` — re-anchored tool calls dropped `assistant_message["content"]` from history -> fixed via `text_json_tool_adapter_active` |
| `qwen3b-v3` (`report-py-multifile-qwen3b-agiss-v3.json`) | `20261122T123339-621de6ba` (`qwen2.5-coder:3b`) | `budget_exhausted` (`1`) | `0/5` | `24` / `15` | `5,651` | `360.07` | `[FIT ROOT] SPLIT` (`splits=1`), Child 1 failed verification and hit `360s` wall-clock cap (`qwen3b-v4/v5` failed host preflight `exit 2`) |
| `gemma-live-v1` (`report-py-multifile-gemma-agiss-live.json`) | `20261122T132837-5be1f25e` (`gemma4:e4b`) | `failed` (`1`) | `0/4` | `41` / `33` | `7,676` | `144.13` | Child 1 (`metrics.py`) tried running not-yet-created `test_metrics.py` -> fixed by deferred sibling test `[not_applicable]` guard + stripping test markers from producer `done_when` |
| `gemma-live-v2` (`report-py-multifile-gemma-agiss-live-v2.json`) | `20261122T133529-daa531ff` (`gemma4:e4b`) | `failed` (`1`) | `0/4` | `10` / `2` | `2,370` | `56.54` | `ENVIRONMENT_ERROR`: occasional empty `<end_of_turn>` (`0` content, `0` `tool_calls`) -> fixed by adaptive seed-rotated retry in `ask_ollama` |
| `gemma-live-v3` (`report-py-multifile-gemma-agiss-live-v3.json`) | `20261122T133853-1278875e` (`gemma4:e4b`) | `failed` (`1`) | `0/4` | `15` / `9` | `3,067` | `61.51` | `REQUIRED_VERIFICATION_TARGET_UNRESOLVED` on Child 1 (`check_call` `10` vs `10.0` float/int JSON mismatch) |
| `gemma-live-v4` (`report-py-multifile-gemma-agiss-live-v4.json`) | `20261122T134127-b1fa72f5` (`gemma4:e4b`) | `failed` (`1`) | `0/4` | `23` / `18` | `5,814` | `109.00` | `REQUIRED_VERIFICATION_TARGET_UNRESOLVED` — `[not_applicable]` deferred sibling test runs were still matched as `_is_focused_test_evidence` |
| `gemma-live-v5` (`report-py-multifile-gemma-agiss-live-v5.json`) | `20261122T134538-f762f576` (`gemma4:e4b`) | `failed` (`1`) | `0/4` | `35` / `23` | `8,379` | `144.74` | `REQUIRED_VERIFICATION_TARGET_UNRESOLVED` — fixed via RFC-8259 `_json_values_equal` in `hivo/python_checks.py` and `result_not_applicable` exclusion in `hivo/verification_routing.py` |
| `gemma-live-v6` (`report-py-multifile-gemma-agiss-live-v6.json`) | `20261122T135018-3e2ac364` (`gemma4:e4b`) | `failed` (`1`) | `1/4` | `54` / `42` | `11,668` | `225.71` | **Child 1 (`metrics.py`) passed & committed!** Child 2 (`cli.py`) omitted `sort_keys=True`; `Repairer` spent budget on `write_file` refusals (`sibling metrics.py` existed) |
| `gemma-live-v7` (`report-py-multifile-gemma-agiss-live-v7.json`) | `20261122T135607-7ed7c4f9` (`gemma4:e4b`) | `failed` (`1`) | `1/4` | `51` / `40` | `18,627` | `322.59` | Child 1 (`metrics.py`) passed; Child 2 `Repairer` hit `EXECUTION_BUDGET_EXHAUSTED` before explicit `read_file` -> `edit_file` guidance & `JSON STDOUT MISMATCH` recovery hint |
| **`gemma-live-v8`** (`report-py-multifile-gemma-agiss-live-v8.json`) | **`20261122T140443-fb94f671` (`gemma4:e4b`)** | **`done` (`0`, `verified=true`)** | **`4/4`** | **`38` / `23`** | **`9,818`** | **`198.46`** | **Full 3-child recursive split + Root integration & `Falsifier` verification passed (`metrics.py`, `cli.py`, `test_metrics.py`)** |
| **`gemma-live-v9`** ([`report-python-multifile-verified.json`](report-python-multifile-verified.json)) | **`20261122T140910-1b993032` (`gemma4:e4b`)** | **`done` (`0`, `verified=true`)** | **`4/4`** | **`49` / `33`** | **`10,879`** | **`211.89`** | **Second consecutive `4/4` verified completion confirming repeatability (`0` preflight conflicts, `[ROOT VERIFIED] PASS`)** |

### 5.2 Standalone Three.js 3D WebGL Progression (`threejs` Cohort on `gemma4:e4b`)

| Trial label | Run ID | Status (`exit_code`) | Model / tool calls | Browser checks | `evidence_licensed_corrections` | Output tokens | Elapsed (s) | Earliest stopping boundary & engineering defect uncovered |
|---|---|---|---:|---:|---:|---:|---:|---|
| `v1` (`live`) | `20261122T141405-62906c41` | `failed` (`1`) | `15` / `11` | `0` | `1` | `17,281` | `331.75` | `CONTEXT_INSUFFICIENT` — truncated `19 KB` `write_file` payload triggered **Truncated-Tool-Call Specification Amnesia** in `hivo/context.py` (overwriting `projected[1]` task prompt with `[HIVO HISTORY OMITTED]`) |
| `v2` | `20261122T142356-03704885` | `failed` (`1`) | `10` / `5` | `0` | `0` | `7,931` | `149.35` | `REQUIRED_VERIFICATION_TARGET_UNRESOLVED` — truncated `write_file` left `index.html` unverified before `Falsifier` |
| `v3` | `20261122T143139-8e9a4a98` | `budget_exhausted` (`1`) | `11` / `7` | `1` | `1` | `25,337` | `420.03` | `RUN_BUDGET_EXHAUSTED: elapsed` (`420s`) after `[EVIDENCE-LICENSED CORRECTION ROOT] SCHEMA_CONTRACT_FAILURE` on truncated `write_file` |
| `v4` | `20261122T144656-0d47c2d2` | `budget_exhausted` (`1`) | `20` / `14` | `6` | `1` | `15,246` | `420.03` | `RUN_BUDGET_EXHAUSTED: elapsed` — exposed `"window"` -> `"win"` (`goal_win_state`) and `"untouched"` -> `"touch"` (`touch_control`) substring contamination in `hivo/verification.py::infer_web_profile` |
| `v5` | `20261122T145725-eb676a65` | `budget_exhausted` (`1`) | `11` / `7` | `2` | `0` | `17,947` | `420.04` | `RUN_BUDGET_EXHAUSTED: elapsed` (`420s` admission ceiling too tight for multi-pass 18KB WebGL generation + Chromium checks) |
| `v6` | `20261122T150726-38e4aa08` | `budget_exhausted` (`1`) | `16` / `12` | `3` | `0` | **`34,656`** | `660.05` | `RUN_BUDGET_EXHAUSTED: elapsed` — Epoch-0 `Builder` temperature `T_0 = 0.15` induced verbose `34,656`-token drafts hitting `num_predict` length cutoffs |
| `v7` | `20261122T152037-751884be` | `budget_exhausted` (`1`) | `14` / `10` | `2` | `0` | `34,029` | `660.04` | `RUN_BUDGET_EXHAUSTED: elapsed` prior to protecting `projected[1]` in `hivo/context.py` + calibrating Epoch-0 `Builder` to `T_0 = 0.08` (`min_p = 0.08`, `top_p = 0.90`) |
| **`v8`** ([report](report-threejs-starfighter-agiss-verified.json)) | **`20261122T153409-45b4cd0f`** | **`done` (`0`, `verified=true`)** | **`8` / `4`** | **`3`** | **`0`** | **`7,574`** | **`184.04`** | **One-shot first-draft pass (`initialFrameBlank=False`, `hudOverlapCount=0`, `18,751`-byte `index.html`, `[ROOT VERIFIED] PASS`)** |

---

## 6. Root-Relative Reproduction Commands

From the repository root, using workspace-local temporary storage:

```powershell
New-Item -ItemType Directory -Force .verification-temp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.verification-temp'
$env:TMP = $env:TEMP

# 1. Focused unit, controlled-functional, and real-Playwright WebGL suites (offline)
.\.venv\Scripts\python.exe -B -X utf8 -m unittest `
  tests.test_assume_guarantee `
  tests.test_hyperparams `
  tests.test_agiss_multifile_and_visual_e2e `
  tests.test_threejs_quality_verification `
  tests.test_context_policy `
  tests.test_evidence_licensed_gate -v

# 2. Verify curated multi-file Python deliverables directly (offline)
.\.venv\Scripts\python.exe -B -X utf8 -m unittest discover `
  -s .\evidence\agiss-swarm-research\python-deliverables `
  -p "test_*.py" -v
.\.venv\Scripts\python.exe -B -X utf8 .\evidence\agiss-swarm-research\python-deliverables\cli.py --values 10,20,30

# 3. Built-in deterministic self-test (offline)
.\.venv\Scripts\python.exe -B -X utf8 mini.py --self-test --no-bootstrap

# 4. Live multi-file recursive Python E2E run (requires explicit live-execution approval + Ollama gemma4:e4b)
New-Item -ItemType Directory -Force .\output\repro-py-agiss | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 mini.py `
  --mode recursive `
  --decoding-policy adaptive `
  --workspace .\output\repro-py-agiss `
  --prompt-file .\evidence\agiss-swarm-research\prompt-python-recursive-swarm.txt `
  --model gemma4:e4b `
  --json-report .\output\repro-py-agiss-report.json `
  --no-bootstrap `
  --max-model-calls 65 `
  --max-tool-calls 65 `
  --max-elapsed-seconds 540

# 5. Live human-ready Three.js 3D WebGL E2E run (requires explicit live-execution approval + Ollama gemma4:e4b)
New-Item -ItemType Directory -Force .\output\repro-threejs-agiss | Out-Null
.\.venv\Scripts\python.exe -B -X utf8 mini.py `
  --mode recursive `
  --decoding-policy adaptive `
  --workspace .\output\repro-threejs-agiss `
  --prompt-file .\evidence\threejs-weak-model-swarm\prompt-neon-starfighter-3d.txt `
  --model gemma4:e4b `
  --json-report .\output\repro-threejs-agiss-report.json `
  --no-bootstrap `
  --max-model-calls 60 `
  --max-tool-calls 60 `
  --max-elapsed-seconds 660
```
