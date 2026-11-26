# Experiment Protocol — <Short Descriptive Title>

> **Template instructions:** Required for `Type: experiment` dossiers. Copy into `docs/worklogs/<person>/YYYY-MM-DD_<short-slug>/PROTOCOL.md` and lock fixed inputs and acceptance criteria before interpreting results.

- **Date:** `<YYYY-MM-DD>`
- **Author:** `<name>`
- **Branch & Base Commit:** `<branch-name>` (`<full-commit-sha>`)

## 1. Research / Engineering Question

<One clear, falsifiable question this experiment answers.>

## 2. Fixed Inputs & Controlled Variables

- **Dataset / Task Set:** <Exact dataset, version, split, and deterministic sampling seed (`seed=...`) or fixed case list.>
- **Model(s) & Endpoint Config:** <Exact Orchestrator & Worker model tags, quantization, `think`/reasoning flags, `max_tokens`, `num_ctx`, provider.>
- **Hardware & Runtime:** <GPU/VRAM, OS, Python/Docker/Ollama versions.>
- **Run Budgets & Limits:** <Max turns, worker turns/dispatches, history char ceiling, timeouts, wall-clock caps.>
- **Zero-Leakage & Isolation Rules:** <What is strictly withheld from the agent during solve time, and how evaluation runs independently.>

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
