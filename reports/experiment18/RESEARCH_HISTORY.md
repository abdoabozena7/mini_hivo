# Research History: Experiments 16–18

**Document:** `reports/experiment18/RESEARCH_HISTORY.md`
**Purpose:** Comprehensive progression analysis tracing the diagnostic journey from Experiment 16 through Experiment 18.
**Author:** AI Software Engineering Research Assistant
**Repository Baseline:** `4d1760b292d0ba9021b5e957a870053407bbee5c`
**Status:** Diagnostic Reference / Progression Narrative

---

## 1. Executive Summary & Progression Overview

Across Experiments 16, 17, and 18, our investigation shifted from broad first-blocker isolation to fine-grained boundary diagnostics of Mini Hivo's autonomous coding pipeline:

```
[Experiment 15: Environment Validation & Positive Control]
  └─ Colab T4 Live Run (`arena_q_restart`): 4/4 Child PASS, 4/4 Root PASS, Root verified: True.
     * Established that the cloud Colab runtime executes complete Mini Hivo tasks end-to-end.
       │
       ▼
[Experiment 16: Cross-Domain First-Blocker Isolation]
  ├─ Python Clamp: Blocked before mutation (context insufficient, 0 tool steps).
  └─ Timer Pause: Reached legal mutation (3/3), but formal verification failed (2/3) due to
     an unexpected "Game" profile selection on a Timer application.
       │
       ▼
[Experiment 17: Deterministic Classification Repair]
  ├─ Isolated root cause of profile misclassification: whole-contract JSON substring matching (e.g. "3d" in hashes).
  ├─ Introduced `field_scoped` classifier policy restricting input to approved semantic fields.
  └─ Frozen deterministic tests: 100% Timer classification (3/3) and Game preservation (6/6).
     * Limitation: No live Worker executions were completed.
       │
       ▼
[Experiment 18: Context Sufficiency, Mutation Grounding, and Verification Follow-Up]
  ├─ 18A (Windows): Diagnosed Worker context sufficiency gate; uncovered schema vs validator mismatch in evidence requests.
  ├─ 18B (Colab T4): Live execution comparing `current` vs `field_scoped`; exposed stale mutation anchor recovery failure.
  ├─ Controlled Replay: Confirmed `field_scoped` classifier fix at production browser verifier boundary on identical source.
  └─ Behavioral Gap Test: Discovered that passing the Timer verifier does NOT guarantee requirement satisfaction
     due to an unasserted Start-after-Pause resume transition.
```

---

## 2. Experiment 15 — Positive Control & Environment Validation

To establish that the Google Colab environment (NVIDIA Tesla T4, Ollama `gemma4:e4b`) could reliably execute Mini Hivo tasks end-to-end, an approved historical-control task from Experiment 15—`arena_q_restart`—was reproduced under real Worker execution:

| Execution Check | Measured Outcome |
|---|---|
| Host Preflight | **PASS** |
| Context Authorization | **PASS** |
| First Legal Mutation | Step 3 (cleanly applied) |
| Child Browser Verification | **4/4 PASS** (`keyboard_movement`, `restart_resets_state`, `goal_win_state`, `touch_control`) |
| Root Browser Verification | **4/4 PASS** |
| Root Verified Status | **True** |
| Repairer Invocations | 0 |
| Final Worker Status | `done` |

### Browser Verifier Controls
Sensitivity checks were conducted against known application states:
- **Game Verifier:** Correctly failed a known-broken implementation (`FAIL`) and passed the Worker-fixed implementation (`PASS`).
- **Timer Verifier Audit:** Confirmed an automated verification coverage gap:
  - Broken Pause (no interval clear): `FAIL`
  - Incomplete Pause (`clearInterval(interval);` without `interval = null;`): **PASS**
  - Correct Pause (`clearInterval(interval); interval = null;`): **PASS**
  - **Coverage Gap:** The compound transition `Start` → `Pause` → `Start (resume)` is omitted from the configured Timer verification suite. Because `interval` remains a non-null timer ID, `start()` exits early. An incomplete implementation was accepted.

---

## 3. Experiment 16 — Cross-Domain First-Blocker Isolation

### Research Objective
Experiment 16 tested whether Mini Hivo encountered common, cross-domain blockers when executing tasks in different domains (Countdown Timer web application vs. Python integer clamping module) under identical harness policies (`contract_fallback`, `strict` semantic evidence, `evidence_bound` mutation grounding, 28-step budget, using model tag `gemma4:e4b`).

### Measured Results (3 fresh runs per task)

| Pipeline Milestone | Timer Task (`timer_pause`) | Python Task (`python_clamp`) |
|---|---:|---:|
| Contract ready | 3/3 (100%) | 3/3 (100%) |
| Worker started | 3/3 (100%) | 3/3 (100%) |
| Context sufficient | 3/3 (100%) | 0/3 (0%) |
| Source actually inspected | 3/3 (100%) | 0/3 (0%) |
| First legal mutation | 3/3 (100%) | 0/3 (0%) |
| File changed before rollback | 3/3 (100%) | 0/3 (0%) |
| Child executable route observed | 0/3 (0%) | 0/3 (0%) |
| Formal child verification invoked | 2/3 (66.7%) | 0/3 (0%) |
| Child verified | 0/3 (0%) | 0/3 (0%) |

### Observed First Blockers
- **Shared First-Blocker:** **None**. The tasks failed for completely orthogonal reasons:
  - **Python clamp:** Blocked at `pre_mutation_context_or_impact` (3/3). The Worker executed 0 tool steps, failed to produce an approved impact contract, and never reached context decisions or source mutations.
  - **Timer pause:** Reached legal mutations in 3/3 runs. However:
    - Run 1 halted at `mutation_grounding_after_worker` (terminal `MUTATION_TARGET_UNRESOLVED`, underlying `REPLACE_NOT_FOUND`, 3 commits, 3 full refreshes, 9 no-op attempts).
    - Run 2 halted at `child_verification_profile_mismatch` (terminal `VERIFIER_UNAVAILABLE`, underlying `MUTATION_ANCHOR_REQUIRED`, 3 commits, 1 full refresh, 1 no-op attempt).
    - Run 3 halted at `child_verification_profile_mismatch` (terminal `MUTATION_TARGET_UNRESOLVED`, underlying `MUTATION_ANCHOR_REQUIRED`, 11 commits, 6 full refreshes, 5 no-op attempts).

### Why the Profile Misclassification Required Investigation
In Runs 2 and 3 of the Timer task, formal browser verification was invoked, opened the page successfully without environment errors (`environment_error=false`), but selected the **Game** verifier profile instead of the **Timer** profile. The Game verifier looked for `<canvas>`, game loops, and keyboard bridges, failing the test immediately.

Investigation revealed that `infer_web_profile()` performed substring searches across the *entire serialized JSON* of the execution contract. When an execution contract hash happened to contain the substring `"3d"`, the classifier inferred the task to be a 3D Game. This showed that upstream milestones (context sufficiency and mutation) could be completely healthy, yet tasks would fail due to an unrelated metadata collision in verification routing.

---

## 4. Experiment 17 — Deterministic Classification Repair

### The Classification Hypothesis
The profile misclassification identified in Experiment 16 was caused by unconstrained string matching over serialized metadata (including hashes, timestamps, and contract IDs). The hypothesis was:
> Restricting classification inputs strictly to approved semantic fields (`title`, `description`, `goal`, `files`) using an opt-in `field_scoped` policy will eliminate false Game classifications for Timer contracts while maintaining 100% accuracy on real Game contracts.

### Implementation Approach
Commit `cbed365` implemented the optional `field_scoped` verification-classification policy in `hivo/verification.py`. The existing `current` classifier was retained as the default baseline.

### Deterministic Test Protocol & Exact Results
Experiment 17 evaluated both classifiers across 9 frozen contracts from prior experiments (3 Timer contracts from Experiment 16, 6 Game contracts from Experiment 15) and applied 3 identity perturbations per contract (27 perturbations total):

| Check | `current` Baseline | `field_scoped` Policy |
|---|---:|---:|
| Timer contracts classified as Timer | 0/3 (0%) | 3/3 (100%) |
| Game contracts classified as Game | 6/6 (100%) | 6/6 (100%) |
| Identity perturbations preserving classification | — | 27/27 (100%) |

### Limitations of Experiment 17
Experiment 17 was strictly a deterministic checkpoint on frozen contract artifacts:
- It involved **no model calls** and **no live Worker runs**.
- It did **not** demonstrate that a Worker could complete an end-to-end task, achieve Child verification, or achieve Root verification.
- Live verification and execution remained unverified under the new policy.

---

## 5. Experiment 18A — Context Sufficiency Diagnostics on Windows

### Motivation
With the classification fix deterministically verified, Experiment 18 sought to observe whether live Worker runs would now pass all boundaries. However, running Timer trials on Windows resulted in early stoppages before any mutations could be authorized. Experiment 18A investigated whether this stoppage was caused by harness timeouts, model reasoning failure, or a context sufficiency failure.

To isolate harness effects, the host-preflight canary timeout was temporarily increased from 30 seconds to 180 seconds during preflight.

### Measured Results (2 eligible completed trials)
Both complete eligible trials halted before legal mutation at the context sufficiency gate:
- Trial 1: Tool steps executed: 4. Terminal blocker: `CHILD_VERIFICATION` / `CONTEXT_INSUFFICIENT`.
- Trial 2: Tool steps executed: 4. Terminal blocker: `CHILD_VERIFICATION` / `CONTEXT_INSUFFICIENT`.

### Uncovered Schema vs. Validator Contract Mismatch
In both trials, the Worker declared `context_status: "insufficient"` and attempted to request additional context evidence. The Worker requested evidence kinds such as:
- `code_snippet`
- `function_signature`
- `variable_scope`

Inspection of `hivo/context_sufficiency.py` revealed an internal contract discrepancy:
1. **Public Tool Schema:** `context_sufficiency_schema()` advertised `needed_evidence[].kind` as an unconstrained string: `{"type": "string"}`.
2. **Runtime Validator:** `validate_evidence_request()` rejected any request whose `kind` was not in `EVIDENCE_REQUEST_KINDS` (a hardcoded set of 21 domain terms like `callers`, `callee_dependency`, `interface`, etc.).

Because the schema did not inform the Worker of the restricted vocabulary, the Worker's requests were rejected with validator errors, halting the evidence completion flow.

### Unresolved Hypotheses
While the schema/validator discrepancy was confirmed, Experiment 18A did **not** prove:
- That the Worker genuinely lacked semantic evidence to solve the task.
- That the Worker's judgment of "insufficient" was objectively sound.
- That fixing the schema enum alone would result in task completion.

---

## 6. Experiment 18B — Colab T4 Live Execution

### Motivation and Setup
To eliminate local hardware resource constraints and evaluate the `field_scoped` policy in live Worker execution, the frozen Timer task was reconstructed in Google Colab using a cloud GPU (NVIDIA Tesla T4).

### Comparability Limitation: Model Artifact Divergence
Both Windows and Colab pulled model tag `gemma4:e4b` via Ollama 0.40.2. However, inspecting the downloaded artifacts revealed a critical divergence:
- **Windows Digest:** `a3d2b95350da03ff9b1943a753bb6617c49a3ee462b632a758518ec817743986` (8.0B parameters, 9.61 GB).
- **Colab Digest:** `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` (7.5B parameters, 6.58 GB).

Because the underlying weight artifacts differed, comparisons between Windows and Colab are **exploratory** and cannot be attributed to GPU vs. CPU differences alone.

### Live Paired-Policy Observations

#### 1. Baseline Run (`current` policy)
- Host Preflight: PASS.
- Context Sufficiency: PASS (unlike Windows 18A, the cloud model artifact judged context sufficient).
- First Legal Mutation: Authorized at tool step 3; 1 edit applied.
- Verification Invoked: Reached formal child browser verification.
- Outcome: Selected **Game** profile (due to hash substring `3d`). Game verifier failed.
- Blocker: `CHILD_VERIFICATION / VERIFIER_UNAVAILABLE`. Child and Root unverified.

#### 2. Initial `field_scoped` Attempt (Preflight Timeout)
- The first attempt timed out during Ollama model loading (`CANARY_PROVIDER_FAILURE`).
- Preserved as a preflight-aborted attempt; correctly excluded from Worker trial statistics.

#### 3. Live Retry (`field_scoped` policy)
- Host Preflight: PASS.
- Context Sufficiency: PASS.
- First Legal Mutation: Authorized at step 3. The Worker applied:
  ```javascript
  function pause() { clearInterval(interval); }
  ```
- Second Mutation Attempt: The Worker immediately attempted a second edit to add `interval = null`:
  ```javascript
  function pause() { clearInterval(interval); interval = null; }
  ```
- Blocker: Rejected with `MUTATION_ANCHOR_REQUIRED` because the Worker supplied the pre-mutation source hash.
- Recovery Noncompliance: The tool error provided an explicit bounded recovery instruction to call `read_file_range` for at most 80 lines. Instead of reading the updated file, the Worker immediately retried `edit_file` with the same stale anchor.
- Terminal Outcome: Halted at `MUTATION_TARGET_UNRESOLVED`.
- Counters: 3 mutation attempts, 1 applied, 2 rejected, 0 bounded refreshes. Formal browser verification was never reached.

### Confirmed Tool-Contract & Recovery Interface Mismatch
Inspection of the active agent configuration revealed an interface conflict:
- **Configured Target Locator:** `target_locator_policy = "evidence_directed"`
- **Offered Tool Schema Projected to Worker:**
  - `read_file`: **AVAILABLE**
  - `read_file_range`: **UNAVAILABLE** (removed from schema by locator configuration)
  - `read_candidate_span`: **AVAILABLE**
- **The Conflict:** When the Worker's second edit failed at Step 5 (`MUTATION_ANCHOR_REQUIRED`), the controller instructed the Worker:
  > *"Call read_file_range on the same file for at most 80 lines around the intended location, then retry once with the exact observed text."*
- However, `read_file_range` was **not present** in the active tool schema offered to the Worker!
- Furthermore, the locator candidate span was stale because it reflected the pre-edit source hash.
- **Scientific Interpretation:** This is a confirmed, reproducible tool-contract and recovery instruction inconsistency. However, it has **not yet been proven** to be the sole cause of Worker failure because `read_file` remained available and the Worker attempted no read tool whatsoever.

### Deterministic Mutation-Grounding Recovery Controls
To determine whether mutation grounding safely recovers after a valid source refresh, deterministic harness tests were run on the identical 17-line Timer fixture:

| Experimental Condition | Attempts | Applied | Rejected | Refreshes | Terminal State | Result |
|---|---:|---:|---:|---:|---|---|
| Without Refresh (original reproduction) | 3 | 1 | 2 | 0 | `MUTATION_TARGET_UNRESOLVED` | Terminal Rejection |
| With `read_file_range` Refresh | 3 | 2 | 1 | 1 | None | **PASS (Fully Grounded)** |
| With `read_file` Refresh (17-line fixture) | 3 | 2 | 1 | 1 | None | **PASS (Fully Grounded)** |

Both valid refresh mechanisms allowed the second mutation (`interval = null`) to apply cleanly without weakening grounding invariants.

---

## 7. Controlled Production-Verifier Replay

### Motivation
Because the live `field_scoped` run halted at mutation grounding before reaching verification, live execution did not demonstrate whether the classifier fix worked in an actual browser. To isolate this question, a controlled replay was conducted using byte-identical patched source (SHA-256: `b18903dd1d6d13bfeb33ed012fa2a728f7c31a5899baf5efe3ac28ab58a8161e`) across separate workspaces.

### Replay 1: Notebook Asyncio Harness Failure
The first replay attempt was executed directly inside a Colab Jupyter notebook cell. Both `current` and `field_scoped` crashed immediately with:
`playwright._impl._api_types.Error: It looks like you are using Playwright Sync API inside the asyncio loop.`
This was an execution harness incompatibility (running synchronous Playwright inside Jupyter's running asyncio loop), not a failure of Mini Hivo's verification logic. It was properly classified as an invalid replay and excluded from results.

### Replay 2: Clean Subprocess Replay
The replay was re-executed by launching isolated Python subprocesses executing Mini Hivo's production `mini.verify_browser_application()`:

| Policy | Selected Web Profile | Browser Environment Error | Verification Result | Checks Passed |
|---|---|---:|---|---|
| `current` | `game` | `false` | **FAIL** | 0/3 (missing canvas / bridge) |
| `field_scoped` | `timer` | `false` | **PASS** | 3/3 (`timer_start_changes_visible_time`, `timer_pause_freezes_visible_time`, `timer_reset_restores_visible_time`) |

This confirmed that Experiment 17's `field_scoped` classifier successfully repairs the profile misclassification at the browser verification boundary under identical source conditions.

---

## 8. Independent Behavioral Acceptance Test

### Motivation
The Worker patch applied in Experiment 18B (`function pause() { clearInterval(interval); }`) passed all three configured checks in Mini Hivo's Timer verifier. However, does passing those three checks mean the Timer actually works according to user expectations?

### The Lifecycle Test
An independent headless Playwright test executed the complete user interaction flow:
1. `Start` → verify countdown begins.
2. `Pause` → verify countdown freezes.
3. `Start` (after Pause) → verify countdown resumes.
4. `Reset` → verify display returns to `02:00`.

### Observed Results

| Step | Expected Action | Observed Result | Status |
|---|---|---|---|
| 1. Initial Start | Clock decrements from `02:00` to `01:59` | Clock decremented | **PASS** |
| 2. Pause | Clock freezes at `01:59` | Clock frozen | **PASS** |
| 3. Resume (Start after Pause) | Clock decrements from `01:59` to `01:58` | **Clock remained frozen** | **FAIL** |
| 4. Reset | Clock restores `02:00` | Clock restored | **PASS** |

### Root Cause of Behavioral Failure
In the seed `timer.html`, the `start()` function guards against multiple interval timers:
```javascript
function start() {
    if (interval !== null) return;
    interval = setInterval(() => { remaining = Math.max(0, remaining - 1); render(); }, 1000);
}
```
The Worker's patch cleared the timer via `clearInterval(interval)`, but did not reset `interval = null`. Consequently:
- `interval` remained a non-null integer handle.
- When the user clicked `Start` after `Pause`, `start()` hit the guard `if (interval !== null) return;` and returned immediately without resuming countdown.

### Significance
This demonstrates a **verification coverage gap** and a **behavioral false acceptance**. Mini Hivo's Timer verifier tested `Start`, `Pause`, and `Reset` as isolated actions, but never asserted the state transition `Start` → `Pause` → `Start`. Thus, an incomplete implementation was certified as passing by the automated verifier even though key functional behavior was broken.

---

## 9. Cross-Experiment Chronological Matrix

| Dimension | Experiment 16 | Experiment 17 | Experiment 18A | Experiment 18B (Live) | Experiment 18B (Replay) |
|---|---|---|---|---|---|
| **Scope / Goal** | Cross-domain first blockers | Deterministic classification repair | Windows context sufficiency diagnosis | Colab paired-policy live execution | Production verifier boundary A/B isolation |
| **Tasks Evaluated** | Timer (3 runs), Python (3 runs) | 9 frozen contracts (3 Timer, 6 Game) | Timer (2 eligible trials) | Timer (1 baseline, 1 retry) | Timer (1 baseline, 1 retry) |
| **Model & Platform** | `gemma4:e4b` (Windows) | None (deterministic script) | `gemma4:e4b` (`a3d2...`, Windows) | `gemma4:e4b` (`dc35...`, Colab T4) | None (production verifier) |
| **Context Gate** | Timer: 3/3 PASS; Python: 0/3 FAIL | Not applicable | 0/2 PASS (both insufficient) | 2/2 PASS | Not applicable |
| **First Legal Mutation** | Timer: 3/3; Python: 0/3 | Not applicable | 0/2 | Step 3 in both runs | Source pre-patched |
| **Mutation Grounding** | 1/3 terminal grounding blocker | Not applicable | Not reached | Stale anchor failure in `field_scoped` retry | Not applicable |
| **Formal Browser Call** | 2/3 reached | Not applicable | 0/2 | 1/2 reached (`current` run only) | 2/2 evaluated |
| **Profile Inferred** | `game` (misclassified) | `current`: `game`; `field_scoped`: `timer` | Not reached | `current`: `game`; `field_scoped`: not reached | `current`: `game`; `field_scoped`: `timer` |
| **Verifier Outcome** | 0/2 passed (Game mismatch) | Deterministic test passed | Not reached | `current`: FAIL (Game verifier) | `current`: FAIL; `field_scoped`: PASS |
| **Overall Success** | 0/3 Child verified | Not tested | 0/2 Child verified | 0/2 Child verified | Verifier-only pass |

---

## 10. Comprehensive Evidence & Artifact Inventory

| Artifact / Identifier | Category | Location / Path | Key Hashes / Identifiers | Status & Custody |
|---|---|---|---|---|
| Pinned Repository Revision | Git Commit | Repository root | `4d1760b292d0ba9021b5e957a870053407bbee5c` | Committed in Git history |
| Timer Seed (`timer.html`) | Task Input | `suite-v1/timer_pause/timer.html` | SHA-256: `84fa3f7e5ef89445b6628a5d1b4f37501e7f68cfe318c5ea3d28dd5ac67a371d` | Verified identical across all runs |
| Approved Plan Hash | Authority | Task metadata | Hash: `cff3a6c590011c02d59aa6a0c6043e66713672c43029023af7ae842894c8d51a` | Verified identical across all runs |
| Execution Contract Hash | Authority | Task metadata | Hash: `ce528e029aae5fae00f8990f50fa5967cad5ed6a2ff9e8e3d39cd3f71f5233ae` | Verified identical across all runs |
| Patched Timer Source | Replay Input | Replay workspaces | SHA-256: `b18903dd1d6d13bfeb33ed012fa2a728f7c31a5899baf5efe3ac28ab58a8161e` | Byte-identical across both replay sides |
| Windows Model Artifact | Inference | Local Ollama store | Digest: `a3d2b95350da03ff9b1943a753bb6617c49a3ee462b632a758518ec817743986` (8.0B) | Retained locally on Windows host |
| Colab Model Artifact | Inference | Colab Ollama cache | Digest: `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c` (7.5B) | Ephemeral Colab environment |
| Experiment 16 Report | Report | `reports/experiment16/experiment16-report.md` | — | Tracked in Git |
| Experiment 16 Results | Data | `reports/experiment16/experiment16-results.json` | — | Tracked in Git |
| Experiment 17 Protocol | Report | `reports/experiment17/classification-protocol.md` | — | Tracked in Git |
| Experiment 17 Data | Data | `reports/experiment17/classification-protocol.json` | — | Tracked in Git |
| Experiment 18 Report | Report | `reports/experiment18/experiment18-report.md` | — | Tracked in Git (`research/experiment18-diagnostics`) |
| Experiment 18 Findings | Data | `reports/experiment18/experiment18-findings.json` | — | Tracked in Git (`research/experiment18-diagnostics`) |
| Experiment 18A Local Logs | Raw Traces | `mini_hivo_exp18_data/experiment18a_windows/` | `trial-1.log`, `trial-2.log` | Local Windows storage (outside Git) |
| Experiment 18B Evidence | Raw Traces | `experiment18b_evidence.tar.gz` | Cloud workspace archives, logs, replays | External download archive |

---

## 11. Cross-Experiment Conclusions & Scientific Distinctions

To maintain strict scientific integrity, we clearly divide our findings into four categories:

### A. Demonstrated Bugs (Confirmed Root Causes)
1. **Metadata Hash Substring Collision in Classifier:** `infer_web_profile()` performed unstructured substring matching on serialized execution contracts. Hashes containing substrings like `"3d"` caused Timer contracts to be misrouted to Game verification.
2. **Context Tool Schema vs. Validator Discrepancy:** `context_sufficiency_schema()` advertised `needed_evidence[].kind` as an open string, while `validate_evidence_request()` enforced the closed `EVIDENCE_REQUEST_KINDS` whitelist, breaking evidence completion.
3. **Stale Source Hash on Secondary Edits:** Applying an edit updates source code without automatically updating the Worker's cached observation hash, causing immediate `MUTATION_ANCHOR_REQUIRED` on subsequent mutations.

### B. Verified Fixes
1. **`field_scoped` Verification Classification:** Verified both deterministically (Exp 17: 3/3 Timer, 6/6 Game) and at the live production browser verifier boundary (Exp 18B replay: Timer profile selected, 3/3 checks passing).

### C. Newly Discovered Gaps
1. **Verification Coverage Gap (Behavioral False Acceptance):** The Timer verification suite omits compound transition assertions (`Start` → `Pause` → `Start`). As a result, incomplete code that fails to clear `interval = null` passes verification.
2. **Worker Recovery Fragility:** When presented with explicit recovery instructions (`read_file_range` for 80 lines), the Worker ignored the instruction and repeated the failing action.

### D. Unresolved Causal Hypotheses
- **H1–H3 (Context Deficit vs. Representation):** We have not resolved whether the Worker in 18A genuinely lacked information, was confused by context representation, or simply failed due to the schema mismatch.
- **H4–H7 (Recovery Routing & Budgets):** Whether controller-level intervention (e.g., automated read-refresh) is superior to prompt-based instructions remains unproven.
- **H9 (Model Weight Sensitivity):** The divergent context decisions between Windows and Colab may stem from model parameter size / quantization differences (8.0B vs 7.5B) rather than environment factors.

---

## 12. Navigation & Related Documents

- [Experiment 18B Research Handoff](EXPERIMENT18B_HANDOFF.md)
- [Experiment 18 Primary Report](experiment18-report.md)
- [Experiment 18 Findings JSON](experiment18-findings.json)
- [Experiment 16 Report](../experiment16/experiment16-report.md)
- [Experiment 17 Classification Protocol](../experiment17/classification-protocol.md)
- [Master Experiment Index](../INDEX.md)
