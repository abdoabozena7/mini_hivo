# Model/provider configuration and Windows launch guide

2026-11-25, Africa/Cairo. Local implementation; real hybrid readiness remains unverified. See [architecture diagnosis](PROVIDER_ARCHITECTURE_REVIEW_2026-11-25.md) and [provider update](../updates/R_UPDATE_010.md).

## Launch from this checkout

Use the checkout's existing isolated environment. No dependency installation is required for the new adapters: they use the existing standard-library HTTP client.

```powershell
Set-Location (Join-Path (Get-Location) '.') # run from the checkout root
.\.venv\Scripts\python.exe -B -X utf8 .\mini.py --help
# Interactive launch; this starts qualification after you confirm selections.
.\.venv\Scripts\python.exe -B -X utf8 .\mini.py --no-bootstrap
```

With an interactive terminal, choose workflow, then orchestrator and worker independently from discovered compatible models, review settings and confirm. Metadata compatibility is explicitly provisional until canaries pass. Cloud choices require the named environment credential and consent to catalogue access; absent credentials produce a setup message. Confirmation authorizes the selected configuration's qualification requests. After PASS, expect `You>`; enter your request yourself. Use Ctrl+C to cancel. No background application server is required.

`--model qwen3.5:2b` is a compatibility shorthand for that **exact installed local ID in every role**, with a 4,096-token default context. It does not choose a separate reasoning model. No selected model is replaced automatically. Default orchestrator context in independent role selection is 16,384; worker context is 4,096 with 1,024 output tokens reserved. Metadata maximum context is not measured safe host capacity.

The 4,096 worker profile currently refuses the complete controlled controller packet: estimated input 3,769 plus output reserve 1,024 exceeds 4,096. This conservative character-based estimate is not a tokenizer measurement or proof that Qwen itself cannot handle the task. Do not remove mandatory authority/context or raise host context blindly. Bounded packet compaction needs a separately verified correction.

## Initial hybrid profile

[hybrid-free.example.json](../configs/hybrid-free.example.json) selects exact OpenRouter `nvidia/nemotron-3-ultra-550b-a55b:free` and local `qwen3.5:2b`. It stores settings and the **name** `OPENROUTER_API_KEY`, never a key or cached approval. Every launch requalifies. The configuration is an example, not evidence that either provider currently passes.

After the separately approved cloud smoke test and resolution of current blockers, an operator can launch:

```powershell
# Set OPENROUTER_API_KEY securely in THIS launching PowerShell process first.
# Never paste it into chat, source, command history, JSON, logs or reports.
.\.venv\Scripts\python.exe -B -X utf8 .\mini.py --no-bootstrap `
  --model-config .\configs\hybrid-free.example.json `
  --workspace .\output\my-new-project
```

The command retains interactive confirmation; it is not a one-call cloud smoke test and may use the configured session budget. Do not run it merely to inspect configuration. Check presence without printing a key using `[bool]$env:OPENROUTER_API_KEY`. A key in another terminal does not imply this process inherited it.

Explicit alternative to a JSON file:

```powershell
.\.venv\Scripts\python.exe -B -X utf8 .\mini.py --no-bootstrap `
  --orchestrator-model 'openrouter:nvidia/nemotron-3-ultra-550b-a55b:free' `
  --worker-model 'ollama:qwen3.5:2b' --worker-thinking off
```

All-local/all-cloud configurations use the same interface. Builder, Falsifier and Repairer use worker selection; planning/reasoning roles use orchestrator selection. Repeat `--role-model 'Repairer=ollama:exact-installed-id'` for explicit exceptions; JSON role entries support individual context/reasoning/endpoint settings. JSON contains no credentials or approval. `--save-model-config` writes only a new file after successful qualification. Configuration-file context settings cannot be silently overridden by competing CLI settings.

Noninteractive cloud use requires explicit selections, `--confirm-models` and `--approve-free-cloud`. That consent covers canaries and subsequent workflow calls within the session budget, not only a metadata fetch. Do not use these switches until the relevant operation is authorized. Paid inference additionally requires explicit non-free configuration and `--allow-paid-inference`; never use that for the initial free profile.

## Safety and diagnostics

- Strict-free selections require the exact `:free` suffix and zero catalogue pricing. Requests disable fallback, require supported parameters and set zero price ceilings. Returned identity/cost violations quarantine the client. No paid-model or auto-router substitution exists.
- Local preflight checks actual installation/capabilities/residency, the existing three host canaries, JSON and native tools. Unknown RAM, less than the unchanged 512-MiB floor, unselected resident models and insufficient estimated cold-load headroom block startup. Disk weight size plus the floor is a conservative loading estimate, not an exact RAM forecast. Accepted local residency is not charged twice.
- Cloud qualification checks controller resources, authenticated `/key`, catalogue access, context/capabilities and JSON; tool canary is required for worker assignments. Remote weights need no local model RAM. Cloud-only does not contact Ollama. Local workers retain all local checks in a hybrid profile.
- Reasoning controls are sent only with advertised support. Explicit off must be honored. Reasoning alone is not a final answer. Unsupported opaque reasoning/tool continuation state fails closed. Streaming is disabled; retries default to zero and explicit retries remain bounded to the same selected model. Truncation is rejected before dispatch.
- `CONTEXT_BUDGET_EXCEEDED` occurs before HTTP and project mutation; numeric diagnostics distinguish it from provider failure. `CRITICAL_MEMORY_HEADROOM`/cold-load estimates are environment/resource boundaries. 401/missing key are authentication; 429 is quota/rate limiting; malformed/truncated/tool/schema output is a provider/contract failure. Child/root verification failures after valid execution need artifact investigation, not credential changes.

Generated application artifacts use the selected `--workspace`; choose a new directory. Qualification evidence uses `<workspace>/.agent_evidence/provider-preflight/<unique-id>/result.json`. Existing runtime traces/logs remain under the configured workspace/runtime output layout. Raw diagnostic results under `output/provider-generalization/` are private local evidence; curated summaries are separate. Do not overwrite prior output cohorts.

The controller's source-bound verification and read-only parent remain required regardless of provider. A passing menu, canary, plan or loaded page is not a complete application. Only the declared controlled counter has demonstrated root acceptance; the real initial hybrid has not.

Provider behavior references: [OpenRouter provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [API limits/authentication](https://openrouter.ai/docs/api_reference/limits), [model metadata](https://openrouter.ai/docs/guides/overview/models), [Ollama thinking capabilities](https://docs.ollama.com/capabilities/thinking).
