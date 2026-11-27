# Experiment Protocol — Neon Breakout Visual & Gameplay Repair Hybrid Ablation

- **Date:** `2026-11-27`
- **Author:** `kareem`
- **Branch & Base Commit:** `feat/benchmark-harness-stage0` (`dac866bfe35c3a94969c7ad84ed4ae7ee0af8538`)

## 1. Research / Engineering Question

Can Mini Hivo v2's asymmetric two-tier runtime (**Cloud Thinking Orchestrator `qwen/qwen3.8-27b` + 4 GB VRAM Local Worker `qwen3.5:2b-q4_K_M`**) decompose a realistic multi-file visual web-app repair (**Neon Breakout**: `index.html`, `style.css`, `game.js` with 6 coupled layout + gameplay bugs) into sequential one-by-one micro-tasks, verify each worker edit, and repair all 10 hidden oracle checks — and where do failures separate between **Orchestrator/quota limits**, **Harness mechanics (`unified_diff`, compaction, syntax checks)**, and **2B Local Worker execution**?

## 2. Fixed Inputs & Controlled Variables

- **Benchmark Stage, Suite & Exact Version:** Dev-Slice Diagnostic Live Experiment (`N = 1` multi-file visual web-app task across `4` controlled runs: `Run 1` baseline harness, `Run 2` upgraded harness `14K` history, `Run 3` upgraded harness `8K` history, `Run 4` controlled Antigravity-to-real-2B worker proof-of-concept). Not a Held-Out leaderboard promotion (not promoted to `docs/BENCHMARK_SCORECARD.md`).
- **Frozen Subject Fixture (`before/`):** 3-file Neon Breakout HTML5 Canvas app (`index.html` `1,594` B, `style.css` `2,350` B, `game.js` ~250 lines) containing 6 realistic, zero-hint bugs (no `BUG:` comments in source code):
  1. `.hud` uses `position: absolute` overlapping the top brick rows.
  2. `.overlay.hidden` uses only `opacity: 0;` and blocks pointer events over `<canvas>`.
  3. Right-wall collision in `stepGame()` fails to clamp `ball.x` and sets `ball.dx = Math.abs(ball.dx)` (pushing the ball off-screen right).
  4. Brick collision never increments `score`, never updates/persists `highScore` (`loadHighScore`/`saveHighScore` stubbed), and never triggers `"won"` when all 32 bricks are cleared.
  5. Bottom miss never decrements `lives` or transitions to `"gameover"` at `0` lives.
  6. `togglePause()` cannot unpause or guard `"gameover"`/`"won"`, and `resetGame()` fails to restore `score`, `lives`, `status`, and `bricks`.
- **Model(s) & Endpoint Config:**
  - **Cloud Orchestrator (Runs 1–3):** Groq OpenAI-compatible endpoint (`qwen/qwen3.8-27b`, `think=True`, `reasoning_effort="medium"`, `reasoning_format="parsed"`, `max_tokens=2048`, `temperature=0.0`).
  - **Controlled Orchestrator (Run 4 PoC):** Scripted Antigravity 6-step sequential decomposition (`0` cloud tokens, blind 1-shot with zero diff-review retries) driving the **real** local 2B worker through `HybridAgentRunner`.
  - **Local Worker (All 4 Runs):** Ollama `qwen3.5:2b-q4_K_M` (`Q4_K_M`, `num_ctx=4096`, `max_tokens=2048`, `think=False`, `temperature=0.0`, `keep_alive="20m"`, 3-tool static binding: `read_file`, `edit_file`, `write_file`).
- **Hardware & Runtime:** Windows 11 (`10.0.26300`), Python `3.14.6`, Node.js `v24.21.0`, Ollama `0.40.18`, NVIDIA GeForce GTX 1650 (`4096 MiB` VRAM, verified `100%` GPU resident `1,604,939,937 / 1,604,939,937` bytes, `flash_attn=enabled`, KV `q8_0`).
- **Run Budgets & Cost Estimate:**
  - Groq free tier (`$0.00` USD; `8,000` TPM / `7,000` single-request ITPM / `200,000` TPD) + local Ollama (`$0.00` USD).
  - Run 1: `max_orchestrator_turns=16`, `max_worker_turns=6`, `max_worker_dispatches=6`, `max_history_chars=10_000`, `max_elapsed_sec=240.0`.
  - Run 2: `max_orchestrator_turns=24`, `max_worker_turns=6`, `max_worker_dispatches=10`, `max_history_chars=14_000`, `max_worker_diff_chars=2_000`, `max_elapsed_sec=360.0`.
  - Run 3: `max_orchestrator_turns=26`, `max_worker_turns=6`, `max_worker_dispatches=10`, `max_history_chars=8_000`, `max_worker_diff_chars=1_200`, `max_elapsed_sec=600.0`.
  - Run 4 (PoC): `max_orchestrator_turns=12`, `max_worker_turns=6`, `max_worker_dispatches=8`, `max_elapsed_sec=240.0`.
- **Decontamination, Isolation & Zero-Leakage Controls:**
  - Each run operates on a fresh isolated copy (`after/`) copied from frozen `before/` under gitignored `output/live_tests/<run>/`.
  - External independent grading script (`oracle/verify_breakout.js`) lives **outside** `after/`, unreachable by `ToolContext` workspace confinement (`allowed_commands=("node",)` only; inline `node -e` blocked by `run_command`).
  - No `.env` or host secrets inside workspace; zero `BUG:` hint comments inside `before/` files.
  - Note: Local Windows host run (not Docker `--network none`), so graded explicitly as a **Dev-Slice diagnostic experiment**, never a sealed Stage 1–2 leaderboard claim.

## 3. Hypothesis

1. **H1 (Harness Decomposition & Diff Visibility):** Replacing the baseline prompt + prose-only worker return with **computed `unified_diff` in `dispatch_worker`** and **explicit one-problem-at-a-time sequential instructions** will push `qwen/qwen3.8-27b` to create a structured `update_plan`, emit clean single-concern worker packets, and cut local 2B worker latency/rollbacks.
2. **H2 (2B Worker Feasibility Floor):** Given clean single-concern atomic packets from an external decomposer (Run 4 PoC), local `qwen3.5:2b-q4_K_M` (`1.60 GB` VRAM) can implement real JavaScript & CSS fixes fast — exposing the exact boundary between Orchestrator/quota failures and local 2B tool-edit failure modes.

## 4. Procedure

1. Run Pre-Solve Baseline Oracle (`node oracle/verify_breakout.js before/`) before spending any LLM tokens and require `passed == 0 / 10`.
2. Execute Run 1 on the unmodified v2 harness (`dac866b`); preserve all raw outputs in gitignored `output/live_tests/2026-11-27_breakout-visual-repair/`.
3. Implement computed `unified_diff` (`hivo/hybrid/runner.py`, `hivo/tools/orchestration.py`) + one-by-one orchestrator prompt (`hivo/hybrid/prompts.py`) with red-first offline tests (`tests/test_hybrid_runner.py`, `tests/test_tools_exec_and_orch.py`) passing `python scripts/check.py -v`.
4. Execute Run 2 (`14K` history) and Run 3 (`8K` history) in fresh isolated folders; inspect every failure, diff, and quota/token boundary without dropping failed runs.
5. Execute Run 4 (Controlled Antigravity-to-real-2B PoC) in a fresh isolated folder on the identical frozen `before/` snapshot.
6. Grade every run identically via independent `node oracle/verify_breakout.js after/` and preserve sanitized diffs in `patches/`.

## 5. Acceptance Criteria

- **Objective Task Pass:** Independent Node oracle passes `10 / 10` checks (`css_hud_no_overlap`, `css_overlay_hidden_nonblocking`, `physics_right_wall_bounce`, `brick_hit_increments_score`, `clear_last_brick_triggers_win`, `bottom_miss_decrements_lives`, `zero_lives_triggers_gameover`, `pause_toggle_and_terminal_guard`, `restart_full_state_reset_preserves_highscore`, `highscore_persistence`) with zero regressions.
- **Forensic Honesty:** Retain all 4 runs (including quota/HTTP-413 blocks and blind-PoC failures), separate proven root causes from hypotheses, redact any vendor org IDs and local absolute paths, and clearly distinguish controlled-orchestrator PoC evidence from full live cloud+local runs.
