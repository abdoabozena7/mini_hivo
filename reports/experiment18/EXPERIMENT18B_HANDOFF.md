# Experiment 18B Research Handoff: Grounding, Tool Contracts, and Recovery

**Document:** `reports/experiment18/EXPERIMENT18B_HANDOFF.md`
**Purpose:** Self-contained, consolidated research handoff for new LLM conversations and researchers reconstructing Experiments 15–18 findings.
**Repository Baseline Commit:** `4d1760b292d0ba9021b5e957a870053407bbee5c`
**Date:** October 11, 2026
**Status:** Interim Research Checkpoint — Tool-Contract Mismatch Confirmed; Causal A/B Validation Pending

---

## 1. Research Objective & Experimental Chronology

The primary research objective is to understand why Mini Hivo fails on approved software engineering tasks, isolating failures across three fundamental operational boundaries:
1. **Context Sufficiency:** Does the Worker possess adequate semantic facts to understand the required mutation?
2. **Mutation Grounding:** Does the Worker possess a fresh, exact source observation to authorize each proposed code edit?
3. **Behavioral Verification:** Does the automated verification suite adequately test the required behaviors and state transitions?

### Chronological Progression Overview

- **Experiment 15 (Environment Validation & Positive Control):** Established that the Google Colab environment (NVIDIA Tesla T4, Ollama `gemma4:e4b`) can successfully execute a complete Mini Hivo task (`arena_q_restart`) end-to-end to Root verification.
- **Experiment 16 (Cross-Domain First Blockers):** Showed that Timer tasks reached legal mutation, but failed at formal browser verification because whole-contract JSON string matching (`"3d"` in execution contract hashes) misclassified the Timer as a Game.
- **Experiment 17 (Deterministic Classification Repair):** Introduced the `field_scoped` verification policy, deterministically proving 100% Timer and Game classification precision over 9 frozen contracts and 27 identity perturbations.
- **Experiment 18A (Windows Context Sufficiency):** Tested Timer execution on Windows; both trials halted before mutation because the Worker declared context insufficient. Discovered a schema vs. validator mismatch in evidence request types.
- **Experiment 18B (Colab Live Trials & Recovery Investigation):** Deployed paired live Worker runs (`current` vs. `field_scoped`). The `current` arm reproduced the Game classification failure. The `field_scoped` arm applied an initial patch, but failed on a subsequent edit due to a stale source anchor and an unaligned recovery instruction. Subsequent deterministic tests confirmed that source refreshes safely resolve mutation grounding.

---

## 2. Experiment 15: Positive Control & Environment Validation

To rule out general runtime or environment breakdown in Google Colab, a historical control task from Experiment 15—`arena_q_restart`—was reproduced under real Mini Hivo execution:

| Execution Check | Measured Outcome |
|---|---|
| Host Preflight | **PASS** |
| Context Authorization | **PASS** |
| First Legal Mutation | Step 3 (applied cleanly) |
| Child Browser Verification | **4/4 PASS** (`keyboard_movement`, `restart_resets_state`, `goal_win_state`, `touch_control`) |
| Root Browser Verification | **4/4 PASS** |
| Root Verified Status | **True** |
| Repairer Invocations | 0 |
| Final Worker Status | `done` |

**Conclusion:** The cloud Colab environment, Ollama provider, and browser automation harness are fully capable of executing Mini Hivo tasks from initial contract compilation to verified completion.

---

## 3. Browser Verifier Controls & Classification Context

### Verification Sensitivity Controls
Verification suites were tested against known states:
- **Game Verifier:** Correctly rejected a known-broken implementation (`FAIL`) and accepted the Worker-fixed implementation (`PASS`).
- **Timer Verifier Audit:** Discovered a notable **verification coverage gap**:
  - Broken Pause (no interval clear): `FAIL`
  - Incomplete Pause (`clearInterval(interval);` without `interval = null;`): **PASS**
  - Correct Pause (`clearInterval(interval); interval = null;`): **PASS**
  - **Behavioral Gap:** The transition `Start` → `Pause` → `Start (resume)` is not asserted by the configured Timer verifier. Because `interval` remains non-null, `start()` aborts early. An incomplete implementation was accepted.

### Experiment 16–17 Classification Context
- The legacy `current` classifier inspected serialized execution contract JSON. If hashes contained `"3d"`, the contract was misclassified as a 3D Game.
- Experiment 17 introduced `field_scoped` classification, which limits inspection to semantic fields (`title`, `goal`, `files`), correctly selecting `timer`.
- This is a historical, previously identified defect with a verified correction. It is **not** a newly discovered Experiment 18 defect.

---

## 4. Experiment 18A: Windows Context Sufficiency Diagnostics

On Windows host execution, two complete eligible Timer Worker trials were run with canary timeouts extended to 180s:
- **Trial 1 & 2:** Both executed 4 tool steps and halted at `CHILD_VERIFICATION` / `CONTEXT_INSUFFICIENT` before any mutation could be authorized.
- **Discovered Schema Discrepancy:** The Worker requested evidence kinds `code_snippet`, `function_signature`, and `variable_scope`. The public tool schema in `hivo/context_sufficiency.py` advertised `needed_evidence[].kind` as `{ "type": "string" }`, but runtime validation enforced the 21-element whitelist `EVIDENCE_REQUEST_KINDS`. The requests were rejected with validator errors.
- **Unresolved Attribution:** We have not proven whether the Worker genuinely lacked information, was confused by the schema error, or misjudged adequate evidence.
- **Model Divergence:** Windows model artifact (`a3d2b953...`, 8.0B) differed from Colab (`dc35e8d9...`, 7.5B). Behavioral differences cannot be attributed to hardware alone.

---

## 5. Experiment 18B: Original Worker Trials & Recovered Trace

In Colab, live trials were conducted with pinned seed `timer.html` and approved plan/contract authorities:

### Arm Results

1. **`current` Policy Arm:**
   - Host Preflight: PASS
   - Context Authorization: PASS
   - First Legal Mutation: Step 3 (1 applied)
   - Formal Verification Reached: Invoked `verify_browser_application`
   - Terminal Blocker: `CHILD_VERIFICATION / VERIFIER_UNAVAILABLE` (misclassified as Game due to `"3d"` in hash)
   - Root Verified: `False`

2. **`field_scoped_retry1` Policy Arm:**
   - Host Preflight: PASS (an earlier attempt timed out during model loading and was excluded)
   - Context Authorization: PASS
   - First Legal Mutation: Step 3 (1 applied)
   - Step 5: Second edit rejected with `MUTATION_ANCHOR_REQUIRED`
   - Step 6: Another edit attempted without refresh; terminal rejection `MUTATION_TARGET_UNRESOLVED`
   - Mutation Counters: 3 attempts, 1 applied, 2 rejected, 0 bounded refreshes
   - Root Verified: `False`

### Recovered Trace Sequence (`run_id: 20261011T084608-0769014d`)

```
Step 1:  Worker calls read_candidate_span('timer.html') -> receives lines 2-16.
Step 2:  Worker calls context_sufficiency_check() -> context_status: "sufficient".
Step 3:  Worker calls edit_file('timer.html')
         -> Applies: function pause() { clearInterval(interval); }
Step 4:  Worker calls run_file('timer.html') -> preview succeeds.
Step 5:  Worker calls edit_file('timer.html')
         -> Attempts: function pause() { clearInterval(interval); interval = null; }
         -> REJECTED: MUTATION_ANCHOR_REQUIRED.
         -> Controller Message: "proposed mutation is not anchored to exact current source in timer.html;
            file was not changed. Call read_file_range on the same file for at most 80 lines
            around the intended location, then retry once with the exact observed text."
Step 6:  Worker immediately calls edit_file('timer.html') without executing any read or refresh.
         -> TERMINAL REJECTION: MUTATION_TARGET_UNRESOLVED ("one bounded source refresh did not
            establish an exact mutation span in timer.html; file was not changed").
Step 7+: Worker shuts down. Rollback transaction executes.
```

---

## 6. Confirmed Tool-Contract Mismatch

Detailed examination of the recovered agent configuration and tool projections revealed an interface conflict:

- **Configured Target Locator:** `target_locator_policy = "evidence_directed"`
- **Offered Tool Schema Projected to Worker:**
  - `read_file`: **AVAILABLE**
  - `read_file_range`: **UNAVAILABLE** (removed from schema by locator policy)
  - `read_candidate_span`: **AVAILABLE**
- **The Conflict:** When the Worker's second edit failed at Step 5, the mutation-grounding controller returned an instruction explicitly telling the Worker:
  > *"Call read_file_range on the same file for at most 80 lines around the intended location, then retry once with the exact observed text."*
- However, `read_file_range` was **not present** in the Worker's active tool schema!
- Furthermore, the locator's `candidate_span` was stale because it reflected the pre-edit source hash.
- **Scientific Interpretation:** This is a confirmed, reproducible tool-contract and recovery instruction inconsistency. However, it has **not yet been proven** to be the sole cause of Worker failure because `read_file` remained available and the Worker attempted no read tool whatsoever.

---

## 7. Deterministic Mutation-Grounding Recovery Controls

To verify whether the mutation-grounding safety mechanism correctly recovers when a source refresh is performed, deterministic harness tests were executed using the identical 17-line Timer fixture and mutation sequence:

| Experimental Condition | Mutation Attempts | Applied | Rejected | Source Refreshes | Terminal State | Result |
|---|---:|---:|---:|---:|---|---|
| **A. Without Refresh (reproducing original)** | 3 | 1 | 2 | 0 | `MUTATION_TARGET_UNRESOLVED` | **Terminal Rejection** |
| **B. With `read_file_range` Refresh** | 3 | 2 | 1 | 1 | None | **PASS (Fully Grounded)** |
| **C. With `read_file` Refresh (17-line fixture)** | 3 | 2 | 1 | 1 | None | **PASS (Fully Grounded)** |

### Findings from Controls
1. Mutation grounding functioned exactly as designed by refusing to authorize an ungrounded edit against stale hashes.
2. Both valid refresh mechanisms (`read_file_range` and whole-file `read_file`) allowed the second mutation (`interval = null`) to apply cleanly without compromising grounding invariants.
3. These are deterministic harness controls, not new live Worker trials.

---

## 8. Recovery-Packet Event Logging Detail

In the agent execution log (`0769014d.jsonl`):
- The Step 5 rejection was categorized internally as `category: "INVALID_MUTATION"` (logged as `mutation_failure_recorded`).
- Mini Hivo's `_mutation_recovery_packet()` generator formats specific recovery packets for distinct categories (e.g., span mismatches), but does not emit a separate `recovery_packet` event for general `INVALID_MUTATION`.
- The production Worker loop nevertheless appends the tool failure summary directly to the model's message history as the tool result.
- The exact raw HTTP wire payload sent to the Ollama endpoint was not captured separately.

---

## 9. Scientific Separation: Confirmed Facts vs. Hypotheses

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                             CONFIRMED FACTS                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│ 1. Colab positive control (Exp 15) completes end-to-end to Root verified.   │
│ 2. Field-scoped classifier eliminates false Game selection at verifier.    │
│ 3. Stale source anchors trigger MUTATION_ANCHOR_REQUIRED as designed.      │
│ 4. Grounding controller instructed read_file_range when it was unavailable. │
│ 5. Deterministic refresh (read_file or read_file_range) fully recovers.    │
│ 6. Timer verifier exhibits a coverage gap on Start-after-Pause resume.     │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          UNRESOLVED HYPOTHESES                              │
├─────────────────────────────────────────────────────────────────────────────┤
│ H1. Did the tool-contract mismatch alone cause Worker failure in Step 6?    │
│ H2. Would providing an aligned instruction cause the Worker to refresh?    │
│ H3. Does the Worker fail to refresh due to prompt or instruction parsing?   │
│ H4. Was Windows 18A context failure caused by schema mismatch or model gap? │
│ H5. Are Windows vs. Colab differences driven by model weights (8.0B vs 7.5B)?│
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 10. Frozen Authority & Environment Identities

| Parameter | Value / SHA-256 |
|---|---|
| Repository Commit | `4d1760b292d0ba9021b5e957a870053407bbee5c` |
| Timer Seed (`timer.html`) | `84fa3f7e5ef89445b6628a5d1b4f37501e7f68cfe318c5ea3d28dd5ac67a371d` |
| Approved Plan Hash | `cff3a6c590011c02d59aa6a0c6043e66713672c43029023af7ae842894c8d51a` |
| Execution Contract Hash | `ce528e029aae5fae00f8990f50fa5967cad5ed6a2ff9e8e3d39cd3f71f5233ae` |
| Patched Timer Source | `b18903dd1d6d13bfeb33ed012fa2a728f7c31a5899baf5efe3ac28ab58a8161e` |
| Colab Model Tag / Digest | `gemma4:e4b` / `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` |
| Colab Host Specs | Google Colab, NVIDIA Tesla T4 (`100% GPU`), Ollama 0.40.2 |

---

## 11. Next Planned Causal A/B Experiment

To resolve whether the tool-contract inconsistency caused the live Worker failure, the next recommended research step is a controlled live A/B trial:

1. **Baseline Arm (Frozen):** Keep existing `evidence_directed` target locator, which omits `read_file_range` while instructing it.
2. **Treatment Arm (Aligned):** Align the controller's recovery instruction to point strictly to available tools (e.g., instructing `read_file` or including `read_file_range` in schema).
3. **Controls Fixed:** Pinned commit, frozen authority hashes, identical model artifact (`dc35...`), identical prompt budget (28 steps), and unchanged mutation grounding invariants.
4. **Outcome Metric:** Measure whether the Worker executes a valid source refresh and recovers to apply the second edit.

---

## 12. Related Documents & Research Navigation

- [Primary Experiment 18 Report](experiment18-report.md)
- [Comprehensive Research History (Exps 16–18)](RESEARCH_HISTORY.md)
- [Experiment 18 Findings JSON](experiment18-findings.json)
- [Experiment 16 Report](../experiment16/experiment16-report.md)
- [Experiment 17 Classification Protocol](../experiment17/classification-protocol.md)
- [Master Experiment Index](../INDEX.md)
