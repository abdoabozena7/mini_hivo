# New integration findings

[Research scope](README.md) · [Evidence identities](EVIDENCE-AND-NOVELTY-MAP.md)

## F2: Experiment 3's current-arm pattern recurs on a different runtime route

**New relationship, not new execution counts.** PR #2 already records 55 Run-006 context decisions: 54 sufficient and one invalid; Worker 1 used 28 context checks, Worker 2 used one listing and 27 checks. Both exhausted their 28-step budgets with no mutation. The contribution here is the connection to [Experiment 3's recorded pair](../experiment3/rkey_01/report.json), whose `current` arm likewise consumed 28 steps, recorded 26 repeated gate checks and made no mutation attempt. These are comparable non-progress signatures on different tasks, not byte-identical replications or a reliability estimate.

Experiment 3's alternative `progress_constrained` policy reduces repeated-gate availability and stops bounded non-progress. Its historical treatment still made no legal mutation; early stopping is not application completion. [Existing tests](../../tests/test_experiment3_worker_progress.py#L19-L28) distinguish current from constrained stopping, and the [controller fixture](../../tests/test_experiment3_worker_progress.py#L64-L112) supplies an execution contract with allowed mutation paths. That fixture is not the greenfield CLI route observed in Coin Courier. Tests were inspected, not rerun for this research publication.

### Newly identified activation limitation

The following joins source conditions to evidence that PR #2 did not analyze:

| Boundary | Source fact at the baseline | Run-006 observation | Supported conclusion |
|---|---|---|---|
| Contract lookup | [`_current_execution_contract`](../../mini.py#L10381-L10417) returns `None` outside its supported contract path unless a suitable embedded execution contract exists. | Both `worker_mission_ready` events have `execution_contract_id: null`. | An ordinary compiled mission must not be assumed to be an approved execution contract. A null ID alone is not sufficient proof of every downstream object value. |
| Wrapper construction | [`execute_agent_task`](../../mini.py#L14425-L14456) creates `WorkerProgress` and `MutationGrounding` only for a Builder with a dictionary execution contract, allowed mutation paths and no active recovery state. | Both completed Workers have no progress or grounding summary events. | Combined with the source path, evidence supports non-activation of these approved-contract wrappers on the observed greenfield attempts. |
| Observability | [Summary emission](../../mini.py#L15581-L15607) records wrapper summaries whenever those objects exist at ordinary Worker completion. | Two completed `agent_finished` events exist, but zero `worker_progress_summary` and zero `mutation_grounding_summary`. | Wrapper activation was not demonstrated; this is an integration-coverage gap, not evidence that all mutation guards were bypassed. |
| Existing gates | [Context/impact tool projection](../../mini.py#L1941-L1963) is separate from those wrapper objects. | Both final child results retain sufficient context and mutation/impact authorization. | Context and impact gates ran even though the approved-contract wrappers were not activated. Authorization is not a source mutation. |

The source continues offering the context tool under `current`. Its constrained removal also requires a non-null progress object: [post-context projection](../../mini.py#L14801-L14832). Therefore a policy-flag-only change is **not an established greenfield solution**. This is stronger than PR #2's existing observation that another policy might help, but it is not a proven complete cause of repetition. Determining intended greenfield authority and safe wrapper activation belongs to the mechanism/integration owners; no contract is injected or gate bypassed here.

The relevant local native events are mission lines 33/195 and completed Worker lines 180/340. The absence claim is over the complete preserved 361-line JSONL, not over a clipped terminal transcript. Evidence locators and hashes are in the [novelty map](EVIDENCE-AND-NOVELTY-MAP.md).

## F3: SQLite event 30 directly corroborates the Experiment 18A mismatch

**Newly recovered evidence.** PR #2 describes an invalid structured context decision but does not identify its underlying validator errors. Immutable read-only SQLite inspection recovered event **30**, task **2**, role `Builder`, tool `context_sufficiency_check`. Its stored result contains three `needed_evidence` errors, one for each request, requiring a kind from the runtime whitelist, followed by:

```text
insufficient context requires at least one targeted evidence request
```

The decision fields include:

```json
{
  "context_status": "insufficient",
  "lifecycle_state": "PREPARING_CONTEXT",
  "mutation_allowed": false,
  "final": false,
  "failure_code": null,
  "reason": "Invalid structured sufficiency decision; submit the bounded schema again."
}
```

The tool-event database column says `status=succeeded`; that means the tool returned a result, not that the structured decision passed validation. Event 31 subsequently records sufficient context and mutation permission. It does not establish that new semantic evidence was acquired.

The source discrepancy is explicit: [public schema](../../hivo/context_sufficiency.py#L249-L276) advertises `needed_evidence[].kind` as `{"type": "string"}`, while [runtime validation](../../hivo/context_sufficiency.py#L279-L302) rejects kinds outside `EVIDENCE_REQUEST_KINDS`. [Experiment 18A's handoff](../experiment18/EXPERIMENT18B_HANDOFF.md#4-experiment-18a-windows-context-sufficiency-diagnostics) documents the same class of mismatch. The new contribution is corroboration in this independent real-task execution, not discovery of the original schema defect.

### Causal limits

- **Confirmed:** three evidence-kind requests were rejected by the whitelist; the advertised kind field does not encode that whitelist.
- **Unavailable:** the original rejected kind strings are not retained in this event. Do not label them `code_snippet`, `function_signature` or `variable_scope` merely because Experiment 18A recorded those names.
- **Confirmed temporal limit:** Worker 1 exhausted its budget before Worker 2 reached event 30. This event cannot explain Worker 1's earlier failure.
- **Unproven:** whether schema alignment would have changed Worker 2's later behavior, improved semantic evidence acquisition, or produced any application file.

Unlike Experiment 18A's terminal insufficient-context trials, this decision was non-final and followed by authorization. The shared defect class and the differing outcomes must both remain visible.

## F4: a specific feedback-retention risk, not an established root cause

PR #2 already lists instruction/history retention as possible causes. Static inspection now narrows one concrete candidate. Under the current route, [context re-anchoring](../../mini.py#L15245-L15268) rebuilds messages from:

```text
base_worker_prompt + CONTEXT GATE UPDATE + context_feedback
```

The combined text is passed to `compact_text` with `MAX_WORKER_MISSION_CHARS = 4200`. [Compaction](../../mini.py#L3390-L3392) normalizes whitespace and keeps a prefix when over the limit. Therefore sufficiently long base text can discard the appended update, including successful context feedback. This is a source-level conditional risk, not proof that the relevant words were lost in this run.

Native request metadata reports Worker 1's initial context estimate as 3159 tokens and its immediate post-check estimate as 1489. These are the program's estimates, not measured provider token counts or a saved request body. They support investigating re-anchoring but cannot reconstruct the actual model-visible payload.

The priority mechanism test is to inspect whether a long greenfield mission retains final context status, authorization feedback and required task obligations in the next model request. No prompt capture was invented, no new model call was made, and no fix was attempted.

## Claims this evidence does not support

These findings do not demonstrate failure of every experiment, a broken grounding decision on an actual edit, a behavioral-verifier false pass, successful activation of the constrained treatment, or a working Coin Courier application. Experiment 18B's stale-anchor/tool-refresh failure was not reproduced because no edit/refresh sequence occurred. The integrated policy and route remain explicit research variables, addressed in the [dependencies](INTEGRATION-DEPENDENCIES.md) and [comparison protocol](CONTROLLED-VALIDATION-PROTOCOL.md).
