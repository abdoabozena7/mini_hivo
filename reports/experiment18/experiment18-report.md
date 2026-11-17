# Experiment 18 — Context Sufficiency, Mutation Grounding, and Verification Follow-Up

**Status:** Diagnostic report / partial experimental replication (2026-10-11). **Not a completed end-to-end success study.**
**Pinned source revision:** `4d1760b292d0ba9021b5e957a870053407bbee5c`
**Task:** `timer_pause` — “Fix Pause in the countdown timer so it freezes the visible time without resetting it, while preserving Start and Reset.”

---

## Research question and motivation

We have been conducting controlled experiments to investigate why Mini Hivo fails while performing approved software-engineering tasks. When a Mini Hivo Worker is blocked before or after mutation, our investigation focuses on three distinct operational boundaries:

1. **Context sufficiency:** Does the Worker genuinely have enough semantic evidence to understand the requested change?
2. **Mutation grounding:** Does the Worker have a fresh, exact source observation sufficient to authorize its proposed edit?
3. **Behavioral verification:** Does the verification system actually test whether the implementation satisfies the intended requirements?

These are related but distinct engineering problems. Experiment 18 investigated their interactions under controlled execution. Passing an upstream boundary (such as semantic context sufficiency or legal source mutation) does not imply that downstream behavioral verification has succeeded or even that the verification oracle tests the full contract.

We document our observations carefully, distinguish confirmed facts from hypotheses, and avoid overstating what the experiments prove.

---

## Environment and model identities

| Property | Windows 18A Environment | Colab 18B Environment |
|---|---|---|
| Host OS | Windows 11 | Linux (Colab runtime) |
| GPU | Local / Host CPU/GPU | NVIDIA Tesla T4 (`100% GPU`) |
| Ollama Version | `0.40.2` | `0.40.2` |
| Context Window (`num_ctx`) | Default | `12288` |
| Model Tag | `gemma4:e4b` | `gemma4:e4b` |
| Model Digest | `a3d2b95350da03ff9b1943a753bb6617c49a3ee462b632a758518ec817743986` | `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` |
| Parameter Size | 8.0B reported | 7.5B reported |
| Artifact Size | 9,609,530,651 bytes | 6,583,656,505 bytes |

> [!WARNING]
> **Comparability Limitation:** While both environments pulled the model tag `gemma4:e4b`, the underlying model digests and weight artifacts differed significantly between Windows and Colab. Consequently, differences between Windows Experiment 18A and Colab Experiment 18B are **exploratory** and must **NOT** be interpreted as a controlled hardware-only comparison.

---

## Frozen source/authority identities

The Timer seed, approved plan, and execution contract were reconstructed and matched the frozen authority hashes:

| Control Item | Frozen Hash / Value |
|---|---|
| Pinned commit | `4d1760b292d0ba9021b5e957a870053407bbee5c` |
| Timer seed (`timer.html`) SHA-256 | `84fa3f7e5ef89445b6628a5d1b4f37501e7f68cfe318c5ea3d28dd5ac67a371d` |
| Approved plan hash | `cff3a6c590011c02d59aa6a0c6043e66713672c43029023af7ae842894c8d51a` |
| Approved execution contract hash | `ce528e029aae5fae00f8990f50fa5967cad5ed6a2ff9e8e3d39cd3f71f5233ae` |
| Worker step budget | 28 tool steps |
| Mutation grounding policy | `evidence_bound` |
| Semantic evidence policy | `strict` |
| Execution framework policies | `contract_fallback`, `discovery` (matching Experiments 12, 15, 16) |

These controls pin the **task specification and authority baseline**, ensuring that execution attempts across platforms operate against identical authority artifacts.

---

## Experimental methods

Experiment 18 comprised four distinct empirical procedures:

1. **Experiment 18A (Windows Local Diagnostics):** Two complete eligible Timer Worker trials were run under Windows using an explicit canary preflight timeout extension (180s) to evaluate Worker context sufficiency behavior on local runtime without harness aborts.
2. **Experiment 18B (Colab T4 Live Execution):** Frozen Timer authority and seed were deployed in Google Colab. Separate live trials were executed comparing the baseline `current` verification policy against the `field_scoped` verification policy introduced in Experiment 17.
3. **Controlled Production-Verifier A/B Replay:** The browser verification boundary was isolated from Worker generation variance by evaluating the production verifier (`mini.verify_browser_application`) against byte-identical patched Timer source in isolated workspaces under `current` and `field_scoped` policies.
4. **Independent Behavioral Acceptance Testing:** Headless Playwright automation executed the complete user lifecycle (`Start` → `Pause` → `Start` resume → `Reset`) against the Worker-generated patch to assess whether passing verifier assertions guarantees requirement satisfaction.

---

## Experiment 18A results

The Windows investigation executed two complete eligible Timer trials. Both stopped at the context sufficiency boundary before any legal mutation was authorized:

| Trial | Context Gate | Tool Steps Executed | First Blocker Stage | Terminal Blocker Reason |
|---|---|---:|---|---|
| Trial 1 | Insufficient (0/1) | 4 | `CHILD_VERIFICATION` | `CONTEXT_INSUFFICIENT` |
| Trial 2 | Insufficient (0/1) | 4 | `CHILD_VERIFICATION` | `CONTEXT_INSUFFICIENT` |

In both trials, the Worker repeatedly reported `context_status: "insufficient"`. The Worker requested evidence kinds including:
- `code_snippet`
- `function_signature`
- `variable_scope`

Inspection of `hivo/context_sufficiency.py` revealed a schema/validator contract mismatch:
- The advertised tool schema in `context_sufficiency_schema()` accepts any string for `needed_evidence[].kind`: `{"type": "string"}`.
- However, runtime validation in `validate_evidence_request()` strictly rejects any kind not present in the internal whitelist `EVIDENCE_REQUEST_KINDS`:
  ```python
  EVIDENCE_REQUEST_KINDS = {
      'authoritative_contract', 'callee_dependency', 'caller_expectation', 'callers',
      'configuration_dependency', 'consumers', 'contract', 'definition',
      'downstream_impact', 'export_or_public_surface', 'interface', 'invariant',
      'return_expectation', 'schema', 'sibling_implementation', 'state_invariant',
      'state_transition', 'symbol_definition', 'test_expectation', 'tests',
      'type_or_schema'
  }
  ```
The Worker's requests were rejected with validator errors, halting the targeted evidence completion flow.

---

## Experiment 18B results

Experiment 18B evaluated live execution on a Tesla T4 GPU in Google Colab across two policies:

| Execution Run | Policy | Preflight | Context Gate | First Mutation Step | Applied / Rejected | Terminal Blocker | Child / Root Verified |
|---|---|---|---|---:|---|---|---|
| Baseline | `current` | PASS | PASS | Step 3 | 1 applied / 0 rejected | `CHILD_VERIFICATION / VERIFIER_UNAVAILABLE` | Unverified / Unverified |
| Attempt 1 | `field_scoped` | **FAIL** (timeout) | — | — | — | Preflight canary aborted (model load timeout) | Excluded from Worker trials |
| Retry 2 | `field_scoped` | PASS | PASS | Step 3 | 1 applied / 2 rejected | `MUTATION_GROUNDING / MUTATION_TARGET_UNRESOLVED` | Unverified / Unverified |

### Detailed Observations

1. **`current` Policy Baseline:**
   - Host preflight passed. Context sufficiency passed.
   - First legal mutation was authorized and applied at Worker tool step 3.
   - Formal child browser verification was invoked.
   - The verifier inspected the entire contract JSON and substring-matched `3d` in the hash, misclassifying the Timer as a `game`.
   - The Game verifier failed (missing canvas / bridge). Result: `CHILD_VERIFICATION / VERIFIER_UNAVAILABLE`.

2. **`field_scoped` Initial Attempt:**
   - Failed host preflight during the first Ollama canary call while the model was being loaded into GPU memory (`CANARY_PROVIDER_FAILURE`).
   - Properly preserved as a preflight-aborted attempt; not counted as a Worker trial outcome.

3. **`field_scoped` Live Retry:**
   - Host preflight passed. Context sufficiency passed.
   - First legal mutation applied at step 3:
     ```javascript
     function pause() { clearInterval(interval); }
     ```
   - Worker then attempted a second edit:
     ```javascript
     function pause() { clearInterval(interval); interval = null; }
     ```
   - The second mutation was rejected with `MUTATION_ANCHOR_REQUIRED` because the Worker used a source hash from before the first edit.
   - The controller explicitly instructed the Worker to execute a bounded `read_file_range` (max 80 lines) to refresh its anchor.
   - **Tool-Contract Inconsistency:** Under the active `target_locator_policy="evidence_directed"`, the Worker's active schema offered `read_file` and `read_candidate_span`, but `read_file_range` was unavailable. The locator candidate span was also stale after the first edit.
   - Instead of using available `read_file` to refresh, the Worker immediately retried `edit_file`, triggering terminal blocker `MUTATION_TARGET_UNRESOLVED`.
   - Mutation counters: Attempts: 3, Applied: 1, Rejected: 2, Bounded source refreshes: 0. Formal child browser verification was never reached.
   - **Deterministic Recovery Controls:** Subsequent deterministic tests confirmed that executing a source refresh (either `read_file_range` or `read_file` on the 17-line fixture) successfully recovers the second mutation (2 applied, 1 rejected, 1 refresh, PASS) without weakening grounding invariants.

---

## Controlled verification replay

To test whether Experiment 17's `field_scoped` classifier resolves the browser verification error independently of Worker generation variance, both policies were evaluated on identical workspaces containing the patched source (SHA-256: `b18903dd1d6d13bfeb33ed012fa2a728f7c31a5899baf5efe3ac28ab58a8161e`).

| Policy | Selected Web Profile | Browser Environment Error | Verification Outcome | Passed Checks |
|---|---|---:|---|---|
| `current` | `game` | `false` | **FAIL** | None (canvas / game surface absent) |
| `field_scoped` | `timer` | `false` | **PASS** | `timer_start_changes_visible_time`<br>`timer_pause_freezes_visible_time`<br>`timer_reset_restores_visible_time` |

> [!NOTE]
> **Harness Distinction:** An initial notebook replay failed when Playwright Sync API was called inside the notebook's active `asyncio` event loop. That attempt was an environment harness artifact. The subsequent subprocess-based replay ran cleanly in isolated Python processes without environment errors, confirming the classifier fix at the verifier boundary.

---

## Independent behavioral acceptance test

While the patch `function pause() { clearInterval(interval); }` passed all three assertions of the configured Timer verifier, an independent headless Playwright test evaluated the full lifecycle:

| Interaction Step | Expected Behavior | Observed Behavior | Status |
|---|---|---|---|
| 1. Initial Start | Clock counts down from `02:00` | Decrements to `01:59` | **PASS** |
| 2. Pause | Clock freezes at current time | Visible time remains unchanged | **PASS** |
| 3. Start after Pause | Clock resumes countdown | **Clock remains frozen** | **FAIL** |
| 4. Reset | Clock restores `02:00` | Displays `02:00` | **PASS** |

### Cause of Failure
The Worker patch clears the interval ID but does not reset the variable:
```javascript
function pause() { clearInterval(interval); }
```
In the original `timer.html`, the `start()` function guards against duplicate intervals:
```javascript
function start() {
    if (interval !== null) return;
    interval = setInterval(() => { remaining = Math.max(0, remaining - 1); render(); }, 1000);
}
```
Because `interval` remains a non-null timer handle, `start()` returns immediately without resuming.

This represents an **observed false acceptance**: an incomplete implementation passed the configured verification suite because the suite did not assert the `Start` → `Pause` → `Start` resume transition.

---

## Confirmed findings

1. **Finding A — Context Request Schema/Validator Mismatch:**
   In `hivo/context_sufficiency.py`, `context_sufficiency_schema()` advertises an unrestricted string for `needed_evidence[].kind`, whereas `validate_evidence_request()` enforces `EVIDENCE_REQUEST_KINDS`. In 18A, this discrepancy caused immediate validation errors when the Worker requested `code_snippet`, `function_signature`, or `variable_scope`.
2. **Finding B — Stale Mutation Anchor and Recovery Interface Conflict:**
   Applying an edit invalidates the Worker's prior source observation hash. In 18B `field_scoped`, the Worker attempted a subsequent edit with a stale hash (`MUTATION_ANCHOR_REQUIRED`). The controller instructed the Worker to call `read_file_range`, but under `target_locator_policy="evidence_directed"`, that tool was omitted from the Worker's active schema while `read_file` remained available. The Worker retried `edit_file` without reading, triggering `MUTATION_TARGET_UNRESOLVED`. Deterministic controls confirmed that source refresh safely resolves mutation grounding.
3. **Finding C — Verifier Classification Repair Confirmed in Production Replay:**
   Experiment 17's `field_scoped` classifier eliminates false Game profile selection on Timer contracts at the production verifier boundary (`mini.verify_browser_application`), allowing all three Timer checks to pass without environment error.
4. **Finding D — Verification Coverage Gap (Behavioral False Acceptance):**
   The existing Timer browser verifier checks Start, Pause, and Reset independently, but omits the compound state transition `Start` → `Pause` → `Start (resume)`. Consequently, a broken patch passed verification.

---

## Unresolved hypotheses

The following items are explicit hypotheses for subsequent investigation, **not** confirmed root causes:

- **H1:** The context schema does not communicate the validator's allowed evidence request kinds precisely enough.
- **H2:** The Worker incorrectly reports insufficient context despite receiving adequate evidence.
- **H3:** Relevant semantic evidence is available but represented poorly in the Worker context packet.
- **H4:** The Worker fails to follow recovery instructions after rejected mutations.
- **H5:** Mutation-grounding refresh rules are appropriate, but the controller does not reliably guide the Worker through recovery.
- **H6:** Bounded refresh and retry budgets prematurely terminate recoverable workflows.
- **H7:** The Worker may misunderstand source-state freshness following successful edits.
- **H8:** The browser verification contract lacks important state-transition tests.
- **H9:** Differences in model artifacts or inference behavior influence Worker decisions.
- **H10:** Context sufficiency, mutation grounding, and verification sufficiency are insufficiently distinguished at the system level.

---

## Threats to validity and limitations

1. **Model Artifact Divergence:** Windows (`a3d2b953...`, 8.0B) and Colab (`dc35e8d9...`, 7.5B) used different model weights under the same `gemma4:e4b` tag. Platform differences cannot be attributed to hardware alone.
2. **Exploratory Sample Size:** Findings derive from two complete Windows trials, two completed Colab trials, and controlled replays on a single task (`timer_pause`). They do not establish population reliability across all task types.
3. **Evidence Custody:** Colab environments are ephemeral. Full raw model transcripts and browser captures reside in external archives (`experiment18b_evidence.tar.gz`) and local directories, not directly in Git.
4. **Adjudication of Information Deficit:** We have confirmed the schema mismatch in 18A, but have not objectively established whether the semantic context provided was objectively adequate for the Worker's task.

---

## Recommended next experiments

1. **Context Schema Enum Alignment:** Align `context_sufficiency_schema()` with `EVIDENCE_REQUEST_KINDS` in a separate research branch and test Worker evidence request validity.
2. **Semantic Evidence Adequacy Benchmark:** Manually score context packets to distinguish sound `insufficient` declarations from model hallucinations or representation issues.
3. **Mutation Refresh Recovery Prompting:** Evaluate prompt and controller modifications that force or automate a `read_file_range` refresh following a `MUTATION_ANCHOR_REQUIRED` rejection.
4. **Verification Oracle Hardening:** Propose extending the Timer verification suite to test the `Start` → `Pause` → `Start` resume transition, measuring reduction in behavioral false acceptances.
5. **Controlled Weight-Identical Re-evaluation:** Re-run 18A and 18B using bitwise-identical model weights and quantization to isolate GPU/platform effects.

---

## References to Experiments 16 and 17

- [Experiment 16 Report](../experiment16/experiment16-report.md) — Cross-domain first-blocker diagnosis isolating Timer misclassification.
- [Experiment 17 Classification Protocol](../experiment17/classification-protocol.md) — Deterministic evaluation of `field_scoped` classifier.
- [Experiment 17 Runbook](../experiment17/RUNBOOK.md) — Operational instructions for classification testing.
- [Experiment 18B Research Handoff](EXPERIMENT18B_HANDOFF.md) — Self-contained synthesis of Experiment 18B recovery, tool-contract mismatch, and positive-control findings.
- [Comprehensive Research History (Experiments 16–18)](RESEARCH_HISTORY.md) — Detailed chronological progression and cross-experiment boundary analysis.
- Production modules: [`hivo/context_sufficiency.py`](../../hivo/context_sufficiency.py), [`hivo/mutation_grounding.py`](../../hivo/mutation_grounding.py), [`hivo/verification.py`](../../hivo/verification.py).
- Machine-readable evidence: [`experiment18-findings.json`](experiment18-findings.json).
