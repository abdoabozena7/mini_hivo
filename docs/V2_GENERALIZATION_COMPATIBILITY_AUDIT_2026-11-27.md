# Focused v2 generalization compatibility audit

2026-11-27, Africa/Cairo. **Read-only audit; implementation remains unchanged.** This report is the sole new file. No tests, inference, package installation, project generation, remote access or Git mutation was performed.

## State and methodology availability

- Root: the selected Mini Hivo checkout. Branch `rodina/dev-turn-2026-11-20`; HEAD `ef08b09708a295d5765d4c207141aa8a11d85f72`. Index empty. Before this report: **67 changed/untracked paths**, including four tracked modifications: `mini.py`, `hivo/http_client.py`, `hivo/integration_gate.py`, `tests/test_host_preflight.py`. All prior untracked modules, fixtures, scripts, reports and evidence remain local. No R_UPDATE_011 exists.
- Local remote configuration remains personal `origin`, Tasneem `teammate`, central `teamleader`. Configuration was read locally; no fetch, push, merge, rebase, reset, stash, cleanup or staging occurred. Snapshot history remains independent of Kareem's original Git ancestry.
- **Missing:** `TECHNICAL_METHODOLOGY_v2.pdf`, `TEAM_GUIDEBOOK_v3.pdf`. Repository inventory, including ignored normal project files but excluding Git internals, environments and generated output, found neither. They were not supplied as readable attachments in this audit. The older project-guide and V001 roadmap PDFs are different documents and were not substituted.
- **Also absent:** `CLAUDE.md`, `dev_rules/`, `docs/worklogs/`, its index, `scripts/check.py`, `scripts/update_worklog_index.py`, `.github/` and CODEOWNERS at the checked locations. Their presence in an unmerged team update is unknown; no remote inspection was authorized.
- Actual [AGENTS.md](../AGENTS.md) still specifies the existing lifecycle and A–M numbered updates. The frozen-v1/modular-v2 and Rules/Living Docs/Worklogs separation below are **directions supplied in this request**, not independently verified PDF rules or already installed governance. They must not be retroactively treated as proof that earlier authorized changes violated a newly proposed rule.

Preservation fingerprint before writing: 541 existing tracked/nonignored files; SHA-256 over sorted `relative-path + space + file-byte-SHA256` rows joined by LF: `5d589b9897f00d6d60d4a75d569af45d8ba387308aa4833536bc3a5782356d1c`. This is a local preservation manifest, not staged-blob or publication verification. Ignored raw run directories were read selectively and not modified.

## Ranked findings and Swap Test

Priorities below are audit recommendations, not team-defined tiers.

| Priority / classification | Exact boundary and current behavior | Smallest future correction; required checks |
|---|---|---|
| P1 — architectural adoption conflict, conditional on verified team policy | `mini.py`: import-time `SingleModelPolicy`/Gemma defaults, `ask_ollama`, `execute_agent_task`, `build_node_context`, `_readonly_parent_acceptance`, `qualify_model_routing`, `main`. New modules exist, but runtime state, dispatch, packet construction and acceptance integration still live in the monolith. A freeze of v1 cannot be achieved by continuing to add integrations there. Configured routing overrides the legacy default; this is not evidence that every current run uses Gemma. | Agree on the exact v1 baseline and v2 entrypoint first. Preserve current changes; extract behavior through explicit run-context, provider, tool and verification interfaces. Require import-isolation checks plus equivalent scoped mutation, child rollback, receipt freshness and read-only root acceptance tests. Never reset `mini.py` to simulate preservation. |
| P1 — unfinished verification, not a newly reproduced defect | `hivo/worker_packets.py::_compact`, `pack_history`, `ToolWindow.project`, and `mini.py::repair_task`. Current compilation recognizes legacy text headings and projection layouts; it raises provider-layer `ProviderFailure`. This representation is coupled to v1 packet construction even though it has no model-ID or Counter filename switch. Current final-source negative acceptance is not demonstrated. | First finish the exact frozen-source controlled checks below. Then adapt typed v2 task/scope/obligation/evidence records to the compiler; keep heading parsing as an explicit compatibility adapter. Test exact reconstruction, missing/stale records, unknown schemas, noncompactable content, repair counters, native schema parameters and both positive/negative parent outcomes. Do not lower reserve or bypass the budget. |
| P1 — residency capability gap; concurrent safety unknown | `hivo/provider_preflight.py::qualify` loops through selections; its selected-name set permits either selected local model to be resident. `hivo/providers.py::ModelSelection` defaults to `keep_alive='5m'`. Individual resource/cold-load checks exist, but no exclusive residency lease, phase unload or aggregate KV/weight qualification is implemented. Swap from one local model to two changes resource behavior. | Design an optional provider-specific residency coordinator, injected into qualification and dispatch. Keep current floor and guards. Offline cases: second-model loading blocked, selected/unselected residency, unknown RAM, release failure, interleaved requests, cancellation and no unauthorized unloading. Separate live qualification requires approval and safe resources. |
| P2 — configuration contract defects, static source evidence | `hivo/model_configuration.py::configure` detects conflicts by exact tokens in global `sys.argv`: `--worker-context=4096` misses a check that recognizes `--worker-context 4096`, leaving JSON settings effective without the intended conflict error. `_choose_model` replaces requested reasoning with `None` for a cloud option. Explicit user control can therefore depend on argument spelling or menu/provider choice. | Track explicit parsed options rather than inspecting process-global argument spelling; retain requested reasoning and validate capability or reject clearly. Targets: this module and, if needed, `mini.py::parse_args`. Tests: both option spellings, programmatic parsing, file/CLI conflicts, unsupported reasoning, unchanged selections and no silent fallback. No cloud calls are needed. |
| P2 — platform/reproduction gaps | `hivo/host_preflight.py::_memory_snapshot` supports Windows and `/proc/meminfo`; a platform such as macOS without either returns unknown RAM, so `provider_preflight.resource_guard` refuses qualification. The refusal is safe; platform telemetry coverage is incomplete. Separately, `scripts/provider_controller_functional.py::main` reads a browser executable from private `output/m0-characterization/20261120-canonical-005/provenance.json`, preventing clean-checkout reproduction without that historical artifact. | Add a verified platform sampler only for declared supported platforms; unknown telemetry must still fail closed. Discover/configure the controlled browser independently of historical results while retaining recorded run provenance. Test platform branches and absent telemetry; fresh-checkout browser discovery, explicit override and missing-browser errors. |

Coverage of the requested audit axes:

- **A, models/providers:** `hivo/providers.py`, `model_routing.py`, `agent_roles.py` already separate exact selections and role assignments. Supported-provider/endpoint allowlists are credential and capability boundaries, not permission to route arbitrary endpoints. Additional providers need reviewed adapters.
- **B, OS/hardware:** gaps above; no current RAM, GPU, installation or readiness measurement was made.
- **C, projects/languages/frameworks:** `behavioral_obligations.validate/file_only` admits file existence and a bounded source-bound HTML/browser scenario vocabulary. This is not a general executable oracle for arbitrary Python, Rust, API or framework behavior. Unsupported meanings must remain unverified. Extend through capability/backend contracts and independent behavioral oracles, not removal of guards. Existing suffix registries are declared scope, not proof of universal language support.
- **D, roles/tools:** fixed Builder/Falsifier/Repairer responsibilities, the registered role set and three-schema window are explicit policy/capacity bounds. The window exposes the permitted catalogue; paging must preserve every argument schema and cannot restore suppressed permissions. These are not arbitrary fixed child counts to delete.
- **E/F, context/acceptance:** retain source IDs, exhaustive scope, full evidence references, fresh receipts and parent completeness. The 512-file/16-MiB read-only snapshot limit is a bounded verifier capability: report a limit, never silently certify a larger project.

## Intentional constraints to retain

Keep the 512-MiB physical-memory floor; unknown-RAM refusal; exact model identities and capability checks; independent routing; unchanged 4096 worker context and 1024 output reserve; bounded retries, schema windows, retrieval and repair; strict-free optional cloud controls; secrets as environment references; source ownership; pre-mutation impact/context authorization; freshness; rollback; and read-only parent verification. A page load is not functional acceptance. Do not weaken `IMPACT_CONTRACT_INCOMPLETE`, schema admission or scope checks to obtain a PASS.

## Packet checkpoint recovered from retained records

All outcomes here are **inherited evidence inspected today, not tests run during this audit**.

- Baseline: 3769 input estimate + 1024 reserve = 4793 against 4096; refusal before project writes.
- `output/packet-compaction/20261126-working-final-001`: controlled real tools/browser with scripted providers; root `done`. Its retained independent audit reports 29 packets, first estimate 2354, maximum 3056; 249 JSON-object comparisons, 192 history-message comparisons and 71 oracle-occurrence checks. These are repeated checks across packets, not unique requirements or live-model proof.
- `20261126-regression-001`: 222 tests, no failures/errors/skips. Later `20261126-regression-final-001`: **226 tests, successful=true, zero failures/errors/skips**. All source hashes listed in that later result match the inspected current files. No broad suite was rerun.
- Latest completed negative `20261126-inert-final-005`: root failed, independent broken behavior correctly observed and foundation retained; **all_worker_packets_fit=false**, with Repairer input estimate **3076** plus reserve 1024 = 4100. That is a historical stopping boundary, not proof that the current later edits still fail identically or are fixed.
- Final `20261126-working-frozen-001` and `20261126-inert-frozen-001` directories/results do not exist. The prior native-browser launch was not executed because automatic approval review hit a usage limit, not because it determined the action unsafe. Do not bypass that review.
- **First unfinished verification:** freeze current source, run the working and inert 4096/1024 controlled chains, require source-before/after equality, then independently audit both packet captures. If recovery still overflows, diagnose that exact packet; do not restart the whole investigation. Current code already contains start-source capture support.
- No completed Packet Compaction A–M update exists. Do not allocate a successful numbered update or claim final-source root/recovery completion yet. Live Qwen packet interoperability and live application delivery remain unverified; the earlier bounded Qwen coding probe is separate inherited evidence.

## v1/v2 migration and interface plan

1. **Establish the target, without code movement:** obtain the exact PDFs and approved team tree/commit through an authorized review. Confirm baseline, allowed integration seams, Tier definitions, filenames and actual checker/index commands. No merge/cherry-pick is implied.
2. **Finish preservation evidence:** complete the missing frozen packet checks in a separately approved session. Pin source hashes and curate safe derivatives while retaining raw originals. Do not turn an incomplete negative run into a pass.
3. **Introduce v2 seams incrementally:** per-run context replaces dependence on `WORKSPACE/RUN/TASKS`; inject normalized provider chat, scoped tool execution, evidence storage and read-only verification interfaces. `providers.py`, routing, ownership, obligations and read-only snapshots are reusable components, not a reason to import the legacy entrypoint into v2. Consider a provider-neutral error type so packet-domain errors do not depend on the HTTP adapter module. No direct `import mini` was found in the inspected `hivo/` files, but orchestration and tests still call the monolith.
4. **Migrate one lifecycle increment at a time:** provider/configuration seam, packet/evidence seam, then child/parent orchestration. Independently reprove ownership, unauthorized-path rejection, preserved native schemas, current-artifact freshness, bounded repair/rollback and zero parent mutations after each affected migration. Test import isolation so v2 provider/tool modules cannot initialize legacy runtime through an adapter.
5. **Only then reconcile docs/worklogs and team integration:** resolve overlapping symbols against the actual unmerged update; never reconstruct unrelated history or overwrite another developer's work automatically.

## Documentation mapping — proposals only

Future contributor dossiers belong under `docs/worklogs/rodina/`, using names and tiers approved from the actual methodology. Each should cite originals through **Builds On**, retain original dates/run IDs/hashes/results/limits, and link living API/architecture documents. Do not copy raw evidence into dossiers or rewrite old records.

| Existing work | Proposed living-document subject | Proposed dossier Builds On |
|---|---|---|
| [M0 investigation](../updates/M0_INVESTIGATION_2026-11-21.md), manifest attribution | Handoff gaps, artifact ownership | Existing handoff and M0 evidence; historical repair baseline |
| [R004](../updates/R_UPDATE_004.md) | Verified-manifest provenance | M0 investigation |
| [R005](../updates/R_UPDATE_005.md) | Receipt dependency freshness | R004 |
| [R006](../updates/R_UPDATE_006.md) | Filesystem path identity | R004/R005 |
| [R007](../updates/R_UPDATE_007.md) | Requirement ownership and scope | M0/R006 |
| [R008](../updates/R_UPDATE_008.md) | Behavioral verification contracts | R007/R005 |
| [R009](../updates/R_UPDATE_009.md) | Read-only parent/root acceptance | R007/R008 |
| [R010](../updates/R_UPDATE_010.md) | Providers, routing and configuration | R009 and preserved provider evidence |
| Packet Compaction WIP | Packet/evidence API and unresolved recovery limit | R010/R009/R008; the exact retained packet cohorts above |
| [Host diagnosis](../updates/HOST_PREFLIGHT_MEMORY_DIAGNOSIS_2026-11-21.md) | Resource qualification and limits | Original preflight measurements; later R010 local probe kept separate |
| Existing R002/R003 | Literal-artifact lifecycle and construction-intent classification | Their original baselines and evidence, without attributing them to this audit |

**Tier 1/Tier 2: unassigned pending the actual definitions.** Assigning either now would invent methodology. The code/lifecycle dossiers need functional evidence; documentation-only reconciliation needs structural checks, but those descriptions are not a guessed tier taxonomy. Existing dated `docs/PROJECT_STATUS.md` is an older checkpoint, not evidence that current routing remains Gemma-only. Later living-document reconciliation must label dates and preserve links to historical records. Neither dossiers nor an index were created; use the real generator/checker only after they exist and are reviewed.

**Rule Proposal: None.** Trigger/specificity criteria cannot be verified without the PDFs. Any later qualifying proposal remains unapplied for designated maintainer review. Locked rules and reviewer permissions stay unchanged.

## Preferred next configuration: feasibility versus readiness

The current `RoutingConfig/ModelSelection` can represent `ollama:gemma4:e4b` for reasoning and `ollama:qwen3.5:2b` for workers, with independent settings. **Representable does not mean qualified.** Do not inherit the CLI's 16384 orchestrator default as a measured safe Gemma context. No configuration was changed and neither model was started.

Earlier Gemma pressure and the bounded Qwen 4096 coding probe remain historical observations. Joint residency, KV-cache peaks and present headroom are unknown. Individual checks and disk-weight estimates do not establish safe simultaneous operation.

Future option, not implemented: an exclusive local-model lease; qualify each exact context independently; release only session-owned residency at explicit planning/worker boundaries; verify release and RAM before the other model loads; retain immutable task/authorization/evidence state outside model memory. Prevent overlap, bound transitions and retries, and fail closed on release/resource uncertainty. Do not unload an unrelated user's model, auto-substitute models or use cloud fallback. OpenRouter remains optional supported code and must not be dismantled or used in this phase.

## Small next-session scope and approval boundaries

First obtain/review missing methodology, then authorize the frozen controlled verification only. After its result, choose **one** small correction: remaining recovery packet defect if reproduced; otherwise parsed-option configuration consistency. Plan residency separately before any two-model live trial.

Exact future candidate paths: `hivo/worker_packets.py`, `mini.py::repair_task/execute_agent_task` only within the subsequently agreed v1/v2 boundary; `scripts/provider_controller_functional.py`, `scripts/audit_worker_packets.py`, `tests/test_worker_packets.py` for final packet verification/reproducibility; `hivo/model_configuration.py`, `tests/test_provider_cli_migration.py`, `tests/test_model_routing.py` for option consistency; `hivo/provider_preflight.py`, `hivo/providers.py`, `hivo/model_routing.py`, `tests/test_host_preflight.py` for a separately reviewed residency design. A new residency component or v2 entrypoint is a proposal, not an existing team file. Platform sampling belongs in `hivo/host_preflight.py` with platform-specific regression cases.

Required approvals: new implementation scope after this audit; maintainer choice of governance/baseline and dossier tiers/layout; any later live model trial that is not already safely qualified; separate Git publication authorization. No approval to edit locked rules, CODEOWNERS, migrate dossiers, use OpenRouter or merge team changes is inferred. This audit stops with this report.
