# Mini Hivo — Hybrid Model Strategy & Optimization Notes

> - **Status:** Reference & Integration Plan (v0.1 — distilled from small-model optimization playbook + live provider verification on 2026-11-26)
> - **Immediate Scope:** Plug in a swappable **Cloud Thinking Orchestrator** (free tier during dev → paid model later with zero architecture changes) paired with a fast **Local Worker** (`qwen3.5:2b` on 4 GB VRAM)
> - **Related Specs:** [Tool Architecture & Design Rules (`../tool_rules.md`)](../tool_rules.md), [Agent Architecture Charter](AGENT_ARCHITECTURE.md), [Project Goal](PROJECT_GOAL.md)

---

## 1. Core Architectural Principle

Split execution into two asymmetric tiers separated by a strict, schema-enforced boundary:

1. **Cloud Thinking Orchestrator (Heavy Lifting):**
   - Owns planning, requirement extraction, repository navigation, task decomposition, worker briefing, and verification review.
   - Uses explicit **thinking/reasoning mode** (`enable_thinking=True` / reasoning tokens enabled) with generous output token headroom (`4,096–8,192` tokens) so thinking chains do not truncate final JSON or tool calls.
   - Never directly edits source lines (enforced via role profiles in [`../hivo/tools/registry.py`](../hivo/tools/registry.py)).
2. **Local Resident Worker (Fast Scoped Execution — 4 GB VRAM Baseline):**
   - Runs a single resident lightweight model (starting with **`qwen3.5:2b`** via local Ollama) dedicated to tightly scoped file edits and bounded execution tasks.
   - Operates with **thinking disabled**, **tight local context**, and **3–4 flat-schema tools** (`read_file`, Hashline `edit_file`, `write_file`).

> **Attribution Boundary:** Mini Hivo's existing [`SingleModelPolicy`](../hivo/model_policy.py) remains intact as the default single-local-model research baseline. Hybrid cloud+local orchestration is introduced strictly as an **explicit opt-in mode** with full model/provider provenance recorded per run.

---

## 2. Validated Local-Worker Rules (4 GB VRAM / GTX 1650 Baseline)

These zero-retraining rules directly prevent WDDM VRAM-spill cliffs and small-model tool collapse:

1. **Keep Exactly One Local Model Resident:** Never swap two local models in and out of 4 GB VRAM during a run; differentiate worker behavior via system prompts, static tool profiles, and `ToolContext` fences over one resident server.
2. **Disable Thinking Mode on Local Workers (`think=False`):** Small local workers must not burn latency, VRAM, or output budget on hidden reasoning chains during routine tool calls. Reserve thinking strictly for the cloud orchestrator.
3. **Cap Local Context (`num_ctx = 4096–8192`):** Even though `Qwen3.5` advertises a 262K native window, cap local worker context at `4096–8192` tokens so the KV cache stays 100% resident in GPU VRAM.
4. **Leverage `Qwen3.5` Hybrid Attention & Empirical VRAM Checks:**
   - `Qwen3.5` uses a 3:1 Gated DeltaNet (linear attention) to full-attention layout — only **8 of 32 layers** accumulate a growing KV cache, giving it a much smaller KV-cache footprint than full-attention models or heavier effective-parameter models (e.g., `gemma4:e4b` loads ~8B total weights).
   - Enable Flash Attention (`OLLAMA_FLASH_ATTENTION`) and KV-cache quantization (`OLLAMA_KV_CACHE_TYPE=q8_0` or `q4_0`), and **verify empirically with `nvidia-smi`** at two context sizes rather than assuming flags took effect.
   - Keep `qwen3.5:2b` as the safe default worker for maximum VRAM headroom; if more local coding capacity is needed later, benchmark an `imatrix`-calibrated `Qwen3.5-4B` (`IQ4_XS`) with capped `num_ctx` and verify zero CPU spill via `nvidia-smi`.
5. **Static Spawn-Time Tool Binding & Constrained Formats:**
   - Bind a worker's tool list once at spawn time (already enforced by [`ToolBinding`](../hivo/tools/registry.py)) so KV-cache prefixes stay byte-identical across turns.
   - Use [`ToolProtocolAdapter`](../hivo/tools/protocol.py) (`native` / `grammar_json` / `xml_tags`) to eliminate malformed tool JSON. Remember: grammar/schema constraints guarantee *syntactic* validity only — deterministic tool guards and verification checks remain the semantic oracle.
6. **Execution-Grounded Loops, Not Chatty Swarms:**
   - Avoid free-text multi-agent debate; keep handoffs compact and schema-enforced (`dispatch_worker` packets + structured envelopes + Hashline anchors).
   - Cap local retry loops (2–3 attempts) backed by [`checkpoint`](../hivo/tools/checkpoint_tool.py) rollbacks and clean state resets so stale stack traces do not poison the 2B worker's context.

---

## 3. Cloud Orchestrator Provider Landscape (Swappable by Design)

All candidate cloud providers (free and paid) expose an **OpenAI-compatible `/v1/chat/completions` API**. Switching from a free development endpoint to a paid production/evaluation endpoint must require **config changes only** (`base_url`, `api_key_env`, `model`, and capability flags) — zero architecture changes.

### 3.1 Free Development Providers (Verified 2026-11-26)

> **Correction to outdated guides:** Neither `qwen/qwen3.8-27b` nor `deepseek/deepseek-v4.1-flash` is free on OpenRouter today, and OpenRouter `:free` routes cap accounts at **50 requests/day** without a \$10 lifetime credit purchase.

| Provider | Endpoint | Top Thinking Candidate(s) | Free Rate Limits / Quotas | Role in Dev |
|---|---|---|---|---|
| **NVIDIA NIM** *(Primary Dev Pick)* | `https://integrate.api.nvidia.com/v1` | `nvidia/nemotron-3-ultra-550b-a55b`, `z-ai/glm-5.3-flash`, `moonshotai/kimi-k3.1-pro`, `nvidia/nemotron-3.5-super-vl-120b-a12b` | ~40 RPM, no tight 50 RPD or 8K TPM wall (dev/research/prototyping only; no card) | High-volume uninterrupted dev & multi-model fallback under one key |
| **Google AI Studio** *(Backup)* | `https://generativelanguage.googleapis.com/v1beta/openai/` | Gemini Flash (current free 3.x Flash/Flash-Lite), `gemma-4-31b-it` | Dynamic per project (typically ~15 RPM, ~500–1,500 RPD; high TPM on Flash, tighter TPM on Gemma 4 31B) | Reliable high-TPM backup (note: free tier data may be used to improve products) |
| **Groq** *(1:1 Qwen3.8 Parity)* | `https://api.groq.com/openai/v1` | `qwen/qwen3.8-27b`, `openai/gpt-oss-120b` | 30 RPM / 1,000 RPD **but 8,000 TPM / 200,000 TPD per model** (cached input exempt) | Spot-checking exact `Qwen3.8-27B` prompt & schema fidelity for free |
| **OpenRouter `:free`** *(Secondary Only)* | `https://openrouter.ai/api/v1` | `nvidia/nemotron-3-ultra-550b-a55b:free`, `google/gemma-4-31b-it:free` | 20 RPM / **50 RPD** (1,000 RPD only after \$10 lifetime deposit) | Fallback only unless \$10 unlock is deposited |

### 3.2 Paid Target Providers (Drop-In Upgrade Later, Verified 2026-11-26)

| Provider | Target Model ID | Live Indicative Pricing (per 1M tokens) | Primary Strength |
|---|---|---|---|
| **OpenRouter** | `qwen/qwen3.8-27b` *(or `deepseek/deepseek-v4.1-flash` / `deepseek/deepseek-v4-flash`)* | Qwen3.8-27B from \$0.035 in / \$1.50 out (Chutes FP8 \$0.039 / \$1.25); DeepSeek V4.1-Flash \$0.14 / \$0.42 | Single key, 23 live Qwen3.8-27B backends, instant provider/model switching |
| **Cerebras** | `qwen-3.8-27b` | \$0.99 in / \$1.49 out (+ one-time \$5 trial credit w/ payment method) | Ultra-low latency (~1,400–1,850 tok/s, FP16, 300 RPM) |
| **Chutes (Direct)** | `Qwen/Qwen3.8-27B-TEE` | \$0.039 in / \$1.25 out (**\$0.0039/M cached input**) | 10× prompt-caching discount for repeated orchestrator system prompts |
| **DeepInfra (Direct)** | `Qwen/Qwen3.8-27B` | ~\$0.15–\$0.20 in / \$1.875–\$2.50 out | Straightforward direct FP8 OpenAI-compatible endpoint |

### 3.3 Provider-Agnostic Adapter Invariants (Keep Free → Paid Seamless)

Every cloud provider quirk must stay isolated inside one thin adapter layer:

1. **Unified Normalized Output:** Translate OpenAI `choices[0].message` (content, `tool_calls`, `usage`) into one canonical message shape. Normalize OpenAI JSON-string `function.arguments` into dicts and map `usage` (`prompt_tokens`, `completion_tokens`) cleanly into provider accounting.
2. **Thinking Extraction & Isolation:** Strip `reasoning_content`, `reasoning`, and `<think>...</think>` blocks from persisted conversation history and worker packets; record thinking token/char telemetry separately without leaking private chain-of-thought into the 2B worker.
3. **Thinking-Aware Output Ceilings:** Cloud thinking roles require `max_tokens` of `4,096–8,192` (not the legacy `1,024–1,536` non-thinking local caps) so reasoning never starves the final answer or tool call.
4. **Configurable Structured-Output Mode:** Support `json_schema` → `json_object` → prompt-enforced JSON fallback per endpoint (some fast endpoints like Cerebras FP16 advertise `tools=True` without strict `structured_outputs`).
5. **Transport-Only Rate-Limit Backoff:** Handle HTTP `429` / `503` + `Retry-After` strictly inside the HTTP client while respecting global wall-clock run budgets. Never fabricate fallback responses on provider failure.
6. **Intelligence-Parity Discipline:** Developing on a massive free model (e.g., `nemotron-3-ultra-550b-a55b` or `kimi-k3.1-pro`) can hide prompt fragility on smaller paid models. Spot-check prompts against `qwen/qwen3.8-27b` (via Groq free or paid) before locking in prompt assumptions.

---

## 4. Quick Wins Included in Immediate Scope

These low-effort, high-ROI items will be wired directly during provider integration:

- [x] **Explicit `think=False` enforcement on local worker calls** (and explicit thinking/reasoning headroom on cloud orchestrator calls).
- [x] **Explicit local worker `num_ctx` ceiling (`4096–8192`)** + `keep_alive` to keep one resident worker warm in VRAM without eviction thrashing.
- [x] **Verified local VRAM & Ollama config check** (`OLLAMA_FLASH_ATTENTION`, `OLLAMA_KV_CACHE_TYPE`, `nvidia-smi` memory delta check at 4K vs 8K context).
- [x] **Native reuse of `hivo/tools/`** (`ToolBinding`, 3–4 worker tools, Hashline `edit_file`, `code_intel`, `checkpoint`, `ToolProtocolAdapter` with `native` / `grammar_json` / `xml_tags`).
- [x] **Gitignored secrets hygiene:** Ensure `.env` is listed in `.gitignore` before storing any local API key (or use Windows user environment variables exclusively).

---

## 5. Explicitly Deferred / Out of Scope for Now

Valid long-term research ideas intentionally **excluded** from the current milestone so we ship the working hybrid cloud+local loop first:

- **Harness Trajectory Distillation (SFT + LoRA) & Verifiable RL (GRPO / HarnessAdapt-RL):** Requires cloud GPU budget and a locked 50-task automated benchmark first. *(Optional passive prep: log clean execution-verified runs cleanly so traces exist later if needed.)*
- **Multi-LoRA Serving (`vLLM --enable-lora`):** Not suited to a local Windows 4 GB GTX 1650 runtime; revisit only on Linux/workstation/cloud GPU infrastructure.
- **Model Compression Research (QAT, Structured Pruning, Custom PTQ Math):** Low ROI compared to using commodity `imatrix` / dynamic quants and stronger deterministic harness verification.
- **Switching Local Runtime From Ollama to Raw `llama-server`:** Defer asymmetric KV cache (`-ctk q8_0 -ctv q4_0`) and raw `.gbnf` sampler enforcement via `llama-server` unless real tests show Ollama's `qwen3.5:2b` tool calling or VRAM footprint hits a hard wall.
- **Full LSP Server Integration:** Defer until `hivo/tools/code_intel.py` (AST/outline/references) + inline syntax checks show concrete cross-file type-error gaps on real tasks.

---

## 6. High-Level Integration Roadmap

1. **Phase 1 — Live API & Local Worker Smoke Test (Standalone):**
   - Verify `.env` gitignore safety; test chosen free cloud provider(s) (latency, thinking extraction, native tool calling, structured JSON, rate-limit headers) and local Ollama `qwen3.5:2b` (`think=False`, `num_ctx` 4096/8192, `nvidia-smi` VRAM check, tool-calling sanity).
2. **Phase 2 — Provider-Agnostic Client & Role Split Layer (`hivo/providers/`):**
   - Implement a stdlib-only OpenAI-compatible cloud client + local Ollama worker client built on [`../hivo/http_client.py`](../hivo/http_client.py), normalizing responses, tool arguments, thinking separation, `429` backoff, and token usage — driven strictly by config so free → paid is a 3-field swap.
3. **Phase 3 — Wire Cloud Orchestrator + Local `Qwen3.5-2B` Worker Loop:**
   - Connect the cloud orchestrator (thinking ON, `orchestrator` profile) and local worker (thinking OFF, `coder_worker` profile, capped `num_ctx`) through [`ToolBinding`](../hivo/tools/registry.py) / [`ToolProtocolAdapter`](../hivo/tools/protocol.py) with explicit opt-in config (preserving `SingleModelPolicy` default).
4. **Phase 4 — End-to-End Verification & Drop-In Paid Swap Benchmark:**
   - Run real coding tasks (single-file edit → multi-file bugfix/feature) verifying real disk diffs, syntax/unit tests, VRAM ceiling, and clean provider swap from free dev endpoint to paid `Qwen3.8-27B` with zero code changes.
