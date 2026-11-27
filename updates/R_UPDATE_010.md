# R_UPDATE_010 — Route explicit model roles through qualified provider boundaries

## A. Update identification

2026-11-25, Africa/Cairo. Branch `rodina/dev-turn-2026-11-20`; actual unchanged HEAD/base `ef08b09708a295d5765d4c207141aa8a11d85f72`, with earlier uncommitted corrections preserved. Number 010 was unused. Local/uncommitted; containing commit/PR pending. **VERIFIED for offline adapters, controlled controller integration and one bounded genuine local coding/tool probe; hybrid live application completion NOT TESTED.** [Exact source identities and sanitized results](../evidence/provider-generalization-20261125/summary-final.json). Parent acceptance recovery is separately recorded in [009](R_UPDATE_009.md), not attributed to provider generalization.

## B. Original problem

Request: independently select exact OpenRouter free reasoning and local Ollama implementation models, while supporting future compatible selections and preserving functional acceptance. Original CLI accepted only two fixed model IDs; `--model qwen3.5:2b` failed argument parsing before service access. The fresh `20261125-cli-baseline-001` cohort executed two migration tests, both errored with SystemExit. Source tracing also established one global model policy, native Ollama payloads and unconditional local host qualification; the hybrid could not be represented or executed.

## C. Why necessary

Renaming a fixed model would retain global routing, provider-envelope assumptions and incorrect cloud resource requirements. User selection must carry explicit capabilities, context, credentials references and billing consent. Provider changes must not bypass task ownership, mutation authorization, behavioral proof or read-only root acceptance.

## D. Root cause

See the pre-implementation [architecture map](../docs/PROVIDER_ARCHITECTURE_REVIEW_2026-11-25.md). CLI choices and `SingleModelPolicy` represented the earlier experiment's deliberate one-model restriction. `ask_ollama` constructed only `/api/chat` payloads; startup always required a local catalogue and local canaries. Role-specific reasoning/tool formats, authenticated cloud access and strict-free billing constraints had no boundary representation. These are proven source restrictions, not evidence of a defective Qwen/Nemotron service. Historical manual provider successes remain inherited observations.

## E. What changed

| Files | Correction |
|---|---|
| `hivo/providers.py` | Immutable exact selections and capability records, injected standard-library transport, Ollama and OpenRouter adapters, discovery/authentication, typed metadata checks, normalized tools/messages, completeness checks, sanitized failures and bounded same-model retries. |
| `hivo/agent_roles.py`, `hivo/model_routing.py` | Provider-neutral role registry, independent orchestrator/worker selections and per-role overrides; explicit validated configuration; refuse unknown roles, unqualified dispatch and model override substitution. |
| `hivo/provider_preflight.py` | Fresh provider-specific qualification evidence, unchanged host floor, residency/cold-load estimate, real existing local canaries, structured/tool probes and continued resource guards. |
| `hivo/model_configuration.py`, provider sections of `mini.py` | Workflow-first dynamic menu, independent roles, explicit confirmation, credential references, reusable settings with fresh qualification; route normalized responses through existing controller/parser/tool boundaries. Legacy Python seam retained when no router is active. |
| `hivo/http_client.py` | Backward-compatible optional response headers for bounded Retry-After handling; no SSL change. |
| `configs/hybrid-free.example.json` | Data-only exact requested hybrid, worker context 4096, default retries zero, explicit free-only reasoning and bounded request budget. |
| Provider tests and diagnostic scripts | Offline positive/negative boundary coverage; real adapters/controller/browser with scripted HTTP; one safety-qualified real local coding/tool diagnostic. Two existing startup fixtures migrate to the new qualifier without dropping failure-blocks-dispatch assertions. |

No dependency installation, parent write grant, acceptance bypass, production benchmark selector or model-family heuristic was added. The diagnostic's pure-function oracle is test-only.

## F. How it works

Workflow -> model selection/configuration -> review/consent -> discovered metadata and authenticated access -> provider-specific canaries -> qualified explicit role router -> normalized existing structured/tool contract -> unchanged authorization/execution/verification -> read-only parent acceptance. Builder/Falsifier/Repairer default to worker; other registered roles use orchestrator. Unknown, unsupported or missing selections fail; no implicit fallback model exists.

Strict-free requests retain the exact `:free` model, require zero catalogue pricing, disable provider fallback, require parameters, apply zero price ceilings and inspect returned identity/cost. Identity/cost violations quarantine the client. Secrets resolve only into HTTP headers, never configuration or diagnostics. A free-tier key alone is not billing authorization. Paid operation needs a separately non-free selection and explicit paid consent. The free example never enables that path.

Local preflight retains the 512-MiB floor and existing three canaries; a cold-load disk-weight estimate adds an explicitly conservative check, while already selected residency is not charged twice. Unselected residency blocks without stopping anyone's model. Cloud-only checks controller memory, authentication, metadata and contract canaries without requiring local model weights. Hybrid workers still undergo local checks. Unknown memory fails closed.

Thinking controls use advertised capability values; explicit off must be honored. Reasoning-only and truncated responses do not become plans. Opaque reasoning/tool continuation state is explicitly unsupported and rejected rather than silently discarded. Streaming is disabled. Full mandatory messages/tool schemas count against a conservative context estimate; no authority packet is silently truncated.

## G. Functional verification

All fresh runs below occurred November 25 in Africa/Cairo. Only the model/HTTP and resource samples are scripted in the controlled runs; actual role routing, provider payload/response translation, planning admission, tools, guards, transactions, Chromium, behavioral checks and root aggregation execute.

| Run | Oracle and observed state | Outcome |
|---|---|---|
| `20261125-controller-001` | Exact role models on all 28 scripted HTTP calls; real HTML/CSS/JS counter; independent increment and reload persistence true; both children accepted and root `done` through read-only acceptance. Four diagnostic checks true. | Controlled functional PASS. Synthetic worker context 32768, not a measured local recommendation. |
| `20261125-controller-negative-001` | Page loads but inert interaction; independent increment/persistence false. Feature child reaches bounded repair limit and fails deterministic evidence gate, root fails, accepted foundation retained after rollback. Five checks true; 44 scripted HTTP calls. | Correct rejection/rollback PASS; generated app FAILED. |
| `20261125-controller-budget-001` | Configured 4096 worker context; input estimate 3769 plus output reserve 1024 exceeds budget. Refused before HTTP for that worker packet/project writes; no index.html produced; root fails. Five checks true; eight scripted setup/planning/canary calls. | Safe refusal PASS; full 4096 controller task BLOCKED. |
| `20261125-local-worker-001` | Real exact `qwen3.5:2b`, thinking off, context4096, retries0, budget6, 90s dispatch deadline/15s individual HTTP limit/30s residency. Three existing host canaries plus JSON plus native tool plus one coding/tool request. Proposed `probe.py` passes exact pure-function AST gate then real execution: 0->1, 2->3, -1->0. Actual UTF-8 artifact digest `c1970d9e77515d7c25fd19b2932bedf1c1b4dd2a13e317a163c4345a752c66b2`. | Genuine local bounded coding/tool PASS, six inference requests, exit0. Not an autonomous application E2E. |

The local probe began with 3,755,425,792 available RAM bytes and ended with 1,172,860,928, above 536,870,912. GPU telemetry was unavailable and recorded as unknown. A later read-only `/api/ps` returned an empty model list after the short residency expired; no Gemma model was loaded by this work. Current process OpenRouter key presence was false. No real cloud metadata/authentication/inference calls were made. User-reported cloud authentication remains unconfirmed here.

## H. Additional successful tests

Fresh `20261125-routing-final-002`: **189 tests, zero failures, errors or skips, exit0** across the thirteen explicit modules in section L. Providers, CLI migration and host qualification plus adjacent ownership, behavioral proof, scope, repair, child integration and manifest checks. HTTP responses are injected; no live discovery/campaign. Fresh `20261125-diagnostic-safety-001`: **2 tests, zero failures/errors/skips, exit0**; exact safe function executes, wrong implementation/import/decorator/extra code/invalid syntax are rejected before execution. Counts are separate; earlier overlapping green cohorts are not summed.

`mini.py --help` ran successfully without inference. JSON configuration loads offline. Final review caught an unused-default lookup when all worker roles are explicitly overridden; startup now binds compatibility globals to the effective Builder assignment, with a direct regression check. This last configuration-only correction postdates the controlled/browser/local runs; their original source identities are retained, and they are not relabeled as final-source reruns. The final189 cohort covers that correction. Source/JSON parsing, whitespace, relative documentation links and preservation checks are recorded separately in the final review record.

## I. Failures and compatibility

Retained intermediate cohorts: `routing-001` 52 methods with one failure (empty catalogue was cached while a test expected a fresh request); explicit refresh was added. `routing-002` 75 methods with two errors (old main fixtures lacked the new menu/configuration boundary); fixtures were migrated while retaining dispatch/no-dispatch assertions. Baseline CLI two errors are expected reproduction, not passes. All originals retained. Later184 and188 green cohorts predate the last defensive/configuration changes; final189 is authoritative for its named suite.

Legacy `--model` now means exact installed local model for all roles, default4096; no automatic heuristic context/model substitution. Legacy direct Python callers retain the old adapter seam until configured. Startup qualifiers now include contract probes and consume session budget. No claim of complete broad regression: known live tests and historical experiment batches were deliberately excluded. No live OpenRouter compatibility or rate-limit behavior has been demonstrated. Independent snapshot history remains an integration concern; no ancestry reconstruction attempted.

## J. Overall impact

The controller can represent and execute independent provider/model roles while retaining real functional acceptance and safe refusal. Controlled evidence establishes a complete counter across actual provider adapters; negative controls show page loading cannot certify behavior and insufficient context cannot silently drop required context. The real local worker can satisfy a small native coding/tool contract safely at4096. This does not establish initial hybrid readiness or general model reliability.

## K. Remaining limitations and next work

1. **Full worker packet at4096 is blocked.** Design bounded, source-preserving task/tool packet compaction with positive/negative context-authority tests; do not increase context or weaken contracts to obtain PASS.
2. **Live Nemotron/cloud NOT TESTED.** Key absent from this process; explicit limited cloud approval still required. Proposed next cloud step: fresh catalogue/auth checks and at most one exact-free structured planning request, no tools/application execution, retries0, strict identity/finish/schema/cost checks and short timeout. No automatic broad campaign.
3. **Live hybrid application E2E NOT TESTED**; depends on preceding blockers. Controlled32768 is synthetic only. Local memory is time-varying and must requalify on each run.
4. Only Ollama/OpenRouter adapters and nonstreaming responses implemented. Opaque reasoning-tool continuation unsupported; capability metadata and provider policy can change. No exact tokenizer-based full-prompt estimate; unsupported fields/states fail closed.
5. Behavioral obligations remain the supported source-bound DSL, not a universal semantic oracle. No full original eleven-requirement To-Do live/root demonstration. Parent remains read-only; integration repair still needs explicit mission authorization/fresh evidence.

## L. Evidence and reproduction

[Final curated outcomes, exact source hashes and original raw result hashes](../evidence/provider-generalization-20261125/summary-final.json); the earlier summary is preserved alongside it. Private originals remain under `output/provider-generalization/`, each unique run directory retained. Curated JSON excludes raw transcripts, credentials, personal paths and host inventories. Hashes are exact working-tree bytes, not staged Git blobs; no staging/publication occurred. Full path inventory is [separate](PROVIDER_WORKTREE_INVENTORY_2026-11-25.md). Windows launch/configuration guide: [operator instructions](../docs/MODEL_PROVIDER_CONFIGURATION_2026-11-25.md).

Executed commands, from repository root (each output directory must be new for a future invocation):

```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/provider-generalization/20261125-routing-final-002 test_providers test_model_routing test_provider_cli_migration test_host_preflight test_readonly_parent_acceptance test_behavioral_obligations test_greenfield_requirement_ownership test_repair_cycle_001 test_run4_scope_regression test_verified_manifest_provenance test_browser_dependency_freshness test_manifest_path_identity test_verified_child_integration
.venv/Scripts/python.exe -u -B -X utf8 scripts/provider_controller_functional.py --output-dir output/provider-generalization/20261125-controller-001
.venv/Scripts/python.exe -u -B -X utf8 scripts/provider_controller_functional.py --variant inert --output-dir output/provider-generalization/20261125-controller-negative-001
.venv/Scripts/python.exe -u -B -X utf8 scripts/provider_controller_functional.py --worker-context 4096 --output-dir output/provider-generalization/20261125-controller-budget-001
.venv/Scripts/python.exe -u -B -X utf8 scripts/local_worker_diagnostic.py --model qwen3.5:2b --output-dir output/provider-generalization/20261125-local-worker-001
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/provider-generalization/20261125-diagnostic-safety-001 test_local_worker_diagnostic
```

Browser functional commands require the already installed local Chromium and appropriate native process permission. Do not rerun live diagnostics as ordinary offline regression. A pre-provider 86-file hash snapshot shows only `mini.py` and `hivo/http_client.py` changed among those baseline files; prior reports and safety/acceptance modules remained identical. New provider files are separately hashed. Root acceptance009 predates these provider changes and has independent evidence.

Research: official [provider selection](https://openrouter.ai/docs/guides/routing/provider-selection), [auth/limits](https://openrouter.ai/docs/api_reference/limits), [model metadata](https://openrouter.ai/docs/guides/overview/models), [Ollama reasoning controls](https://docs.ollama.com/capabilities/thinking). These define wire behavior; they do not establish this account's current availability.

## M. Summary for the team

**Proposed PR title:** Route independent model roles through qualified Ollama and strict-free OpenRouter adapters.

**Why / what:** Remove the fixed one-model CLI/provider coupling, add exact role configuration, secure free-only cloud boundary, capability-aware normalization and appropriate host/provider qualification while preserving child/root acceptance. Parent recovery is separate009.

**Functional proof:** Real adapter/controller/browser counter accepted; inert behavior rejected with rollback; oversized4096 packet blocked before mutation; one genuine local Qwen coding/tool contract passed. **Additional regression:** final189 and separate diagnostic2, no failures/errors/skips; limited suites, no broad live campaign.

**Remaining:** Full4096 worker packet blocked; real OpenRouter/hybrid application unverified; initial profile is an example rather than a readiness certificate. Obtain specific limited cloud approval only after review. All changes local and uncommitted, index untouched, no push/PR/merge/remote modification.
