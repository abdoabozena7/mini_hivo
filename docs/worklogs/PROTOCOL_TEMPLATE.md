# Experiment Protocol — <Short Descriptive Title>

> **Template instructions:** Required for `Type: experiment` dossiers. Copy into `docs/worklogs/<person>/YYYY-MM-DD_<short-slug>/PROTOCOL.md` and lock fixed inputs, decontamination rules, cost estimates, and acceptance criteria before running (see `dev_rules/benchmarking_rules.md`).

- **Date:** `<YYYY-MM-DD>`
- **Author:** `<name>`
- **Branch & Base Commit:** `<branch-name>` (`<full-commit-sha>`)

## 1. Research / Engineering Question

<One clear, falsifiable question this experiment answers.>

## 2. Fixed Inputs & Controlled Variables

- **Benchmark Stage, Suite & Exact Version:** `<e.g., Stage 1 | Terminal-Bench 4.1 | Slice: Dev (N=15, seed=42)>`
- **Dataset / Task Set:** <Exact dataset, version, split, and deterministic sampling seed (`seed=...`) or fixed case list (state Dev vs. Held-Out).>
- **Model(s) & Endpoint Config:** <Exact Orchestrator & Worker model tags, quantization, `think`/reasoning effort flags, `max_tokens`, `num_ctx`, `ToolProfile` hash, provider.>
- **Hardware & Runtime:** <GPU/VRAM + verified local residency `%`, OS, Python/Docker/Ollama versions.>
- **Run Budgets & Pre-Run Cost Estimate:** <Max turns, worker turns/dispatches, history char ceiling, timeouts, estimated total LLM calls & worst-case USD spend + human sign-off status.>
- **Decontamination, Isolation & Zero-Leakage Controls:** <`.git` stripped to 1 orphan commit, network mode (`--network none`/allowlist), `/tmp` & secrets isolated, hidden `test_patch`/hints withheld, privilege-separated grading container.>

## 3. Hypothesis

<Expected outcome and specific failure boundaries being tested.>

## 4. Procedure

1. <Pre-flight offline verification & environment/baseline oracle check before spending live calls.>
2. <Execution steps per task/arm.>
3. <Independent oracle evaluation & artifact capture.>
4. <Preservation rule: retain all aborted, quota-blocked, and failed attempts in raw `output/` and report full denominators.>

## 5. Acceptance Criteria

- <Exact objective pass/fail oracle per task (e.g., clean `git apply`, `100%` `F2P` + `P2P`, byte-exact match, browser checks).>
- <Exact reporting honesty criteria (separate offline vs. live evidence, report $N$, separate quota/env blocks from solve failures).>
