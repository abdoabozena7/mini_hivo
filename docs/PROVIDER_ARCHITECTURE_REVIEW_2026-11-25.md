# Provider architecture review before generalization

2026-11-25 Africa/Cairo. Local/uncommitted. HEAD `ef08b09708a295d5765d4c207141aa8a11d85f72`, branch `rodina/dev-turn-2026-11-20`. Existing changes/reports through R_UPDATE_008 and unfinished read-only parent code preserved. This is a pre-implementation map, not a provider readiness claim.

## Current path

CLI `--model` (two fixed choices) -> global `SingleModelPolicy` -> mandatory local Ollama host preflight -> local model catalogue/capabilities -> `MODEL`/role contexts -> `ask_ollama` -> `/api/chat` -> Ollama envelope normalization -> structured parser or tool executor -> independent verification/impact/rollback -> parent acceptance.

Structured planning and Worker tool calls share that same provider boundary. Core requirements, mutation authority, browser checks and read-only parent verification do not require a particular model family. They must remain independent of provider choice.

## Confirmed coupling and restrictions

- `hivo/model_policy.py` deliberately pins all roles to one experiment model. It is not a generalized role router.
- `mini.py::parse_args` restricts model IDs; `select_local_ollama_model` updates global MODEL/ROUTER_MODEL and clears fallback. Catalogue filtering treats cloud variants specially. Any selected model receives size-derived heuristic capacity and role-context defaults originally tuned for the old model.
- `ask_ollama` always builds Ollama options/think/format and calls the local URL. Current retry, CPU recovery, response diagnostics and provider errors are Ollama-specific.
- `structured_model_call` independently validates parsed JSON, which should be preserved after provider normalization. Incomplete/truncated responses must not become plans.
- Startup always invokes local-model canaries and expects a local catalogue, even when reasoning would be remote. The 512-MiB controller floor remains useful for all routes; loading remote weights is not a local requirement.
- The existing interactive loop prompts for user input after startup; it does not dynamically configure independent provider/model roles before preflight.
- Token/context and tool capability restrictions are legitimate when measured; model names or parameter counts are not sufficient capability evidence.

## Proposed increments

1. Preserve/document the recovered parent acceptance result separately.
2. Add provider-neutral model selections, discovered capability records, explicit role routing and safe provider adapters using the existing standard-library HTTP transport. Keep the legacy Python `ask_ollama` seam for callers while routing new configured runs through the adapter.
3. Enforce exact free-only selection, verified zero pricing, zero price ceiling, no fallback, protected credential references and returned identity checks at the cloud boundary. Cloud discovery/inference require explicit runtime consent; no real cloud call during development without separate user approval.
4. Add dynamic CLI discovery/configuration and provider-appropriate preflight. Local workers still need the unchanged local resource checks; remote reasoning needs credentials/catalogue/capability checks and controller resources.
5. Offline provider/error/normalization tests, then real controlled-controller integration with scripted provider decisions, then a bounded local capability/coding probe if host state permits. Real OpenRouter and broad campaigns remain approval-gated.

## Parent checkpoint recovered

The prior parent-treatment-002 result contains 108 passing offline methods. Its functional launch was not executed because automatic approval review hit a usage limit; it was not rejected as unsafe. On November 25, `20261125-parent-functional-001` completed the real controlled counter chain: both children accepted, increment/reload behavior independently passed, and root returned `done` through the new read-only path. This is scripted-model controller proof for that exact three-requirement counter, not live-model or full To-Do certification.

## Documentation used

Existing AGENTS workflow/update template, R_UPDATE_007/008, M0 findings and journal index were reviewed. Provider research uses official OpenRouter API, model, provider-selection and rate-limit documentation and official Ollama API source/docs. Cloud free-model catalogue availability and key authentication reported by the user remain inherited manual observations until an approved fresh API check.
