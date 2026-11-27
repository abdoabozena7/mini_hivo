# Mini Hivo — Hybrid Model & Provider Deployment Reference

> - **Status:** Living deployment & hardware reference (`v0.2` — provider landscape & 4 GB VRAM tuning, last verified 2026-11-26)
> - **Scope:** Hardware-specific local-worker sizing (4 GB VRAM / GTX 1650 baseline), live free-dev vs. paid-target cloud provider comparisons (pricing/quotas), and deferred long-term research tracks.
> - **Related Docs & Rules:** [Orchestration Implementation Architecture (`ORCHESTRATION_ARCHITECTURE.md`)](ORCHESTRATION_ARCHITECTURE.md) *(implemented modules & runtime flow)*, [Orchestration Guardrails (`../dev_rules/orchestration_rules.md`)](../dev_rules/orchestration_rules.md) *(timeless rules & capability floors)*, [Tool Rules (`../dev_rules/tool_rules.md`)](../dev_rules/tool_rules.md)

---

## 1. Deployment Topology Overview

This guide documents Mini Hivo's concrete **Cloud Thinking Orchestrator + 4 GB VRAM Local Worker** deployment profile (free dev cloud endpoints during iteration → paid drop-in endpoints via `EndpointConfig` swap). For the implemented module map (`hivo/providers/`, `hivo/hybrid/`) and runtime loop details, see [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md); for timeless architectural invariants, see [`../dev_rules/orchestration_rules.md`](../dev_rules/orchestration_rules.md).

> **Active v2 Scope:** Asymmetric hybrid orchestration (`hivo/providers/`, `hivo/hybrid/`, `hivo/tools/`) **is** Mini Hivo, logging explicit per-run model/endpoint provenance. The legacy v1 single-local-model baseline (`mini.py`, `SingleModelPolicy`, `gemma4:e4b`, `updates/`, `reports/`) is **retired historical archive only** and is no longer used.

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

### 3.3 Provider Adapter Checklist (Implemented in `hivo/providers/`)
Concrete provider-agnostic adapter mechanics (unified message/tool-arg normalization, `<think>`/`reasoning_content` extraction, `max_tokens` headroom, `structured_mode` fallback, and `429`/`Retry-After`/`x-ratelimit-reset-*` deadline-clamped backoff) are implemented in [`../hivo/providers/clients.py`](../hivo/providers/clients.py) — see [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) and [`../dev_rules/orchestration_rules.md`](../dev_rules/orchestration_rules.md) for the authoritative specs.

- **Intelligence-Parity Discipline:** Developing on a massive free model (e.g., `nemotron-3-ultra-550b-a55b` or `kimi-k3.1-pro`) can hide prompt fragility on smaller paid models. Spot-check prompts against `qwen/qwen3.8-27b` (via Groq free or paid) before locking in prompt assumptions.

---

## 4. Explicitly Deferred / Out of Scope for Now

Valid long-term research ideas intentionally **excluded** from the current deployment milestone:

- **Harness Trajectory Distillation (SFT + LoRA) & Verifiable RL (GRPO / HarnessAdapt-RL):** Requires cloud GPU budget and a locked 50-task automated benchmark first. *(Optional passive prep: log clean execution-verified runs cleanly so traces exist later if needed.)*
- **Multi-LoRA Serving (`vLLM --enable-lora`):** Not suited to a local Windows 4 GB GTX 1650 runtime; revisit only on Linux/workstation/cloud GPU infrastructure.
- **Model Compression Research (QAT, Structured Pruning, Custom PTQ Math):** Low ROI compared to using commodity `imatrix` / dynamic quants (`qwen3.5:2b-q4_K_M`, 100% GPU resident at `1.60 GB` on 4 GB VRAM) and stronger deterministic harness verification.
- **Switching Local Runtime From Ollama to Raw `llama-server`:** Defer asymmetric KV cache (`-ctk q8_0 -ctv q4_0`) and raw `.gbnf` sampler enforcement via `llama-server` unless real tests show Ollama's `qwen3.5:2b-q4_K_M` tool calling or VRAM footprint hits a hard wall.
- **Full LSP Server Integration:** Defer until `hivo/tools/code_intel.py` (AST/outline/references) + inline syntax checks show concrete cross-file type-error gaps on real tasks.

---

## 5. Deployment Milestone Status

| Phase | Scope | Status | Reference |
| :--- | :--- | :--- | :--- |
| **Phase 1** | Live free cloud + local 4 GB VRAM smoke probe & residency verification (`Q8_0` vs `Q4_K_M`) | **Done** | [`../scripts/probe_hybrid_models.py`](../scripts/probe_hybrid_models.py), [`../reports/experiment23/experiment23-report.md`](../reports/experiment23/experiment23-report.md) |
| **Phase 2** | Stdlib-only provider-agnostic client layer (`hivo/providers/`) | **Done** | [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) |
| **Phase 3** | Asymmetric Cloud Orchestrator + Local Worker runner (`hivo/hybrid/`) over `hivo/tools/ToolBinding` | **Done** | [`ORCHESTRATION_ARCHITECTURE.md`](ORCHESTRATION_ARCHITECTURE.md) |
| **Phase 4** | Initial live `SWE-bench Verified` Docker evaluation (`N=3` free tier) → Next: `unified_diff` handoff & larger paid-endpoint slice (`N=10–50`) | **In Progress** | [`../reports/experiment23/experiment23-report.md`](../reports/experiment23/experiment23-report.md) |
