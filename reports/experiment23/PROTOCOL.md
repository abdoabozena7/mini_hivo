# Experiment 23 — Hybrid Cloud Thinking Orchestrator + 4 GB Local Worker Evaluation (`SWE-bench Verified`)

Recorded 26 November 2026. Parent checkpoint: `feat/hybrid-providers` (`886ea71a317af373bde7e4e0c3be9b8180288540`, stacked on PR #5 `feat/hivo-tools` `047179f6a71a6e51c781a4b880a5381518af32e5`). New branch: `feat/experiment23-hybrid-swebench`.

## Question

Can Mini Hivo's new asymmetric hybrid stack — pairing a **cloud thinking orchestrator** (`qwen/qwen3.8-27b` on Groq) with a **100% GPU-resident 4 GB VRAM local worker** (`qwen3.5:2b-q4_K_M` via Ollama, `think=False`) over `hivo/tools/` — localize, patch, and resolve real multi-file GitHub issues from `princeton-nlp/SWE-bench_Verified` when verified inside official SWE-bench Linux Docker containers?

## System architecture delta since Experiment 22

Experiment 22 evaluated offline verification-status integrity on the single-local-model `mini.py` (`SingleModelPolicy`, `gemma4:e4b`) architecture. Between Experiment 22 and Experiment 23, four additive architectural layers were introduced without mutating `mini.py`:

1. **Standalone tool layer (`hivo/tools/`, PR #5 / `R_UPDATE_010`):** 15 flat-schema, framework-free tools (Hashline `edit_file` + syntax diagnostics, `code_intel` AST navigation, external `@scratch/` checkpoints, `ToolProtocolAdapter` with `native`/`grammar_json`/GBNF/`xml_tags`, `ToolProfile`, and static spawn-time `ToolBinding` + `spawn_worker_binding()` fencing).
2. **Provider-agnostic transport (`hivo/providers/`, PR #6 / `R_UPDATE_011`):** Stdlib-only `OpenAICompatClient` and `OllamaClient` behind config-driven `EndpointConfig` presets (swapping free dev to paid endpoints requires config changes only), `<think>`/`reasoning_content` stripping into telemetry, OpenAI JSON-string tool-argument normalization, and `Retry-After` + `x-ratelimit-reset-*` `429` duration backoff.
3. **Hybrid orchestrator-to-worker runtime (`hivo/hybrid/`, PR #6 / `R_UPDATE_011`):** `HybridAgentRunner` routing planning/verification to a cloud thinking model (`think=True`) and scoped file mutations to a fenced 3-tool local worker (`edit_file`, `read_file`, `write_file`; `think=False`, `num_ctx=4096`), with `max_consecutive_worker_errors=2` early abort, `O(target_files)` atomic byte rollback, 2-pass hard-bound history compaction, and `extra_orchestrator_tools`.
4. **SWE-bench Verified Docker benchmark runner (`scripts/run_swebench_hybrid.py`, this experiment):** Zero-leakage task runner extracting `/testbed` via streaming `tarfile` (preserving `.git` and Git-compatible Windows `core.symlinks=false` link stubs), universal `/opt/miniconda3` activation, sandboxed in-container `run_repo_tests`, independent baseline + candidate Docker oracle evaluation, and 1-image-at-a-time cleanup for tight host disk budgets.

## Fixed inputs

- **Dataset:** `princeton-nlp/SWE-bench_Verified` (`split=test`, 500 instances) fetched via Hugging Face Datasets Server.
- **Deterministic sampling (`seed=42`):** Stratified 3-task slice selecting 1 task each (`random.Random(42).choice`) from three pure-Python repositories restricted to `<= 1 hour` difficulty (`<15 min fix`, `15 min - 1 hour`) to fit single-day free-tier cloud quota and 1-image-at-a-time Docker disk limits:
  1. `pytest-dev__pytest-10051` (`pytest-dev/pytest`, `15 min - 1 hour`, `F2P=1`, `P2P=15`)
  2. `django__django-16527` (`django/django`, `15 min - 1 hour`, `F2P=1`, `P2P=6`)
  3. `psf__requests-1724` (`psf/requests`, `<15 min fix`, `F2P=6`, `P2P=79`)
- **Cloud orchestrator:** Groq `qwen/qwen3.8-27b` (`think=True`, `reasoning_effort="medium"`, `max_tokens=1536`, `temperature=0.0`, free tier `7,000` ITPM / `8,000` TPM / `1,000` RPD / `200,000` TPD).
- **Local worker:** Ollama `qwen3.5:2b-q4_K_M` (`think=False`, `num_ctx=4096`, `temperature=0.0`, 100% GPU-resident `1.60 / 1.60 GB` on NVIDIA GTX 1650 4 GB VRAM with `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`).
- **Runner bounds:** `max_orchestrator_turns=14`, `max_worker_turns=5`, `max_worker_dispatches=4`, `max_history_chars=8500`, `orchestrator_max_read_lines=80`, `protected_paths=("tests/**", "testing/**", "test_*.py", "*_test.py")`.
- **Zero-leakage rule:** Only `problem_statement` and repository files at `base_commit` are exposed during solving; `patch`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS`, and `hints_text` are strictly withheld until independent post-run Docker evaluation.

## Hypothesis

Pairing a cloud thinking orchestrator with a 100% GPU-resident 2B local worker over `hivo/tools/` can localize real repository bugs and apply syntactically clean, test-passing patches on scoped `SWE-bench Verified` tasks, while exposing the exact failure boundaries (2B edit accuracy vs. orchestrator turn budget vs. free-tier token ceilings) through independent Docker oracles.

## Procedure

1. Verify offline unit, controlled functional, and core regression gates (`test_providers.py`, `test_hybrid_runner.py`, `test_tools_*.py`, `test_verification_outcome_integrity.py`, `test_execution_contracts.py`) on `886ea71`.
2. Measure local GTX 1650 VRAM residency (`nvidia-smi` + Ollama `/api/ps`) comparing `qwen3.5:2b` (`Q8_0`) vs. `qwen3.5:2b-q4_K_M` (`Q4_K_M`).
3. For each selected `SWE-bench Verified` task:
   - Pull the official Docker image (`swebench/sweb.eval.x86_64.<owner>_1776_<repo>-<id>:latest`), verify `/opt/miniconda3` `testbed` activation before spending LLM tokens, and extract `/testbed` cleanly to a disposable host workspace.
   - Execute `HybridAgentRunner` and capture the resulting `git diff` (`model_patch`).
   - Run **two** fresh official Docker oracle containers: (a) **Baseline** (`test_patch` only, verifying `FAIL_TO_PASS` fails prior to the fix), and (b) **Candidate** (`model_patch` + `test_patch`, verifying clean `git apply`, `100%` `FAIL_TO_PASS`, and `100%` `PASS_TO_PASS`).
   - Remove the task Docker image immediately afterward to keep `C:` disk space healthy.
4. Preserve all aborted diagnostic runs and quota stops honestly alongside passing/failing verdicts without reclassifying errors or dropping denominators.

## Acceptance criteria

- Every reported verdict is backed by an independent fresh-container Docker oracle check with explicit baseline and candidate `F2P`/`P2P` counts.
- `resolved=True` requires non-empty `model_patch`, clean `git apply`, `100%` `FAIL_TO_PASS` pass, and `100%` `PASS_TO_PASS` pass.
- All offline unit, controlled functional, and regression suites pass at their declared counts with zero secret or private-path leakage in published artifacts.
- Sample size ($N=3$), quota blocks, and diagnostic harness failures caught during execution are reported transparently.
