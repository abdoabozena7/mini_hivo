# Experiment 18A Follow-up — Historical Evidence-Schema and Rejected-Decision Feedback Corrections

**Status:** Previously implemented and offline-validated correction, now documented retrospectively. No new implementation, test, live trial or full recovery result is introduced by this submission.

**Contribution:** Tasneem's post-handoff evidence investigation, focused implementation and regression validation. Original Experiment 18A's schema-mismatch diagnosis and the pre-existing Context Sufficiency/Impact mechanisms remain prior work, not newly attributed contributions.

## Research question and relationship to existing research

Does aligning the advertised evidence request schema with its existing runtime whitelist, while reporting rejected decisions from the actual unchanged gate snapshot, eliminate contradictory tool feedback without granting, revoking or weakening mutation authority?

The [original Experiment 18A report](../experiment18-report.md) already identified a public-schema/runtime-whitelist mismatch in Timer trials. Tasneem's Coin Courier work corroborated that issue and subsequently implemented its correction. The additional rejected-decision/state inconsistency was established during her focused offline investigation. This follows Experiment 18A rather than re-announcing its original finding as a new experiment.

Hypothesis of the existing implementation: advertised kinds equal the supported set; unsupported input remains invalid; an invalid request does not change gate state and must not be reported as a new context evaluation or a new authorization.

## Fix History / Run Timeline

| Historical point | Observation or action | Evidence and scope |
|---|---|---|
| Original Experiment 18A, reported 11 October | Timer evidence requests were rejected because unrestricted advertised kind strings did not match the runtime whitelist | [Original report](../experiment18-report.md), pinned research revision `4d1760b292d0ba9021b5e957a870053407bbee5c`. Prior research, not Tasneem's fix |
| Coin Courier Run-006 | SQLite event 30 contained three unsupported-evidence-kind validation errors | [PR #3 analysis](https://github.com/tasneem-ahmed05/mini_hivo/blob/3d20a720302c05d527bb72a0540e726fc525c9e2/reports/e2e-cross-experiment-integration/NEW-INTEGRATION-FINDINGS.md). Corroborates the mismatch, not exact rejected kind names or Worker 1's earlier stall |
| Run-009, 21 October | After accepted Repairer authorization, event 19 rejected three unsupported kinds and returned insufficient/PREPARING_CONTEXT/mutation disallowed | [Recorded handoff](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/coin-courier-runtime-integration/ENGINEERING-HANDOFF.md), native line 121 and events 14–23. Original rejected kind strings are unavailable |
| Focused investigation, after Run-009 and before Run-010 | Tasneem reproduced invalid feedback without a gate evaluation; response contradicted the actual preserved authorized/terminal state | [Existing implementation report](https://github.com/tasneem-ahmed05/mini_hivo/blob/2a8b94590734cec3375047a18e0dc71df2476f85/reports/experiment18a-schema-feedback/README.md); recorded baseline tests in [ledger](EVIDENCE.json) |
| Isolated correction phase | New worktree based exactly on `5e66d34`; schema enum and read-only invalid-input feedback corrections implemented on `fix/experiment18a-evidence-feedback` | Not applied to the original dirty checkout or the already published Worker branch |
| Before/after offline validation | Same selected cases exercised public schema, validator, existing gate state, terminal failures and real greenfield tools; selected cohort became 30 passing methods | Nine new methods; 21 existing methods retained their pass results. Baseline new suite recorded seven failure records including subtests, not seven independent experiments |
| 22 October, 01:03:49 +03:00 | Committed as `2a8b94590734cec3375047a18e0dc71df2476f85` by Tasneem | [Exact commit](https://github.com/tasneem-ahmed05/mini_hivo/commit/2a8b94590734cec3375047a18e0dc71df2476f85), four files; published on her fork |
| Run-010, 22 October | Exact corrected commit used; Builder and Repairer sufficient-context decisions and impact authorization observed | No unsupported-kind rejection occurred. Thus this run did **not** behaviorally exercise the corrected invalid-input path; no live Repairer mutation or accepted final game was demonstrated |
| Later verification-integrity and Experiment 20 selections | The same nine 18A regression methods passed in recorded 103-method and 176-method cohorts respectively | Repeated regression coverage, not additional independent experimental cases or live recovery proof |
| Follow-up publication preparation | Fork refs and open PR heads verified; fixes remain outside team main | Status below; no merge is inferred from their use in Run-010 |

## Exact historical implementation

Historical worktree: `experiment18a-focused-fix-20261022/worktree`; branch `fix/experiment18a-evidence-feedback`; baseline `5e66d34db1827b814abf98f56b0b77b5ef6f8ee5`; treatment `2a8b94590734cec3375047a18e0dc71df2476f85`.

| Existing fix | Exact files/functions | What changed and what did not |
|---|---|---|
| Advertised evidence kinds | [`hivo/context_sufficiency.py::context_sufficiency_schema`](https://github.com/tasneem-ahmed05/mini_hivo/blob/2a8b94590734cec3375047a18e0dc71df2476f85/hivo/context_sufficiency.py) | Sorted enum comes from the existing 21-kind whitelist. No new supported kind or relaxed validation |
| Rejected-decision feedback | Same module's feedback helper and [`mini.py::_context_sufficiency_tool`](https://github.com/tasneem-ahmed05/mini_hivo/blob/2a8b94590734cec3375047a18e0dc71df2476f85/mini.py) | Invalid input returns the read-only actual gate snapshot plus an explicit invalid-decision marker; no `gate.evaluate()` or evidence-provider call. Preserves real lifecycle, context, authorization and terminal failure |
| Safeguard accounting | `mini.py::execute_agent_task` | Rejected decisions do not count as newly successful repeated context checks, even if existing authorization remains true |
| Regression evidence | [`tests/test_experiment18a_schema_feedback.py`](https://github.com/tasneem-ahmed05/mini_hivo/blob/2a8b94590734cec3375047a18e0dc71df2476f85/tests/test_experiment18a_schema_feedback.py), existing report | Nine methods cover valid kinds, malformed/unsupported input, prior authorization, terminal state, provider interaction and preserved context/impact restrictions |

The old tool rejected input before evaluating the gate but fabricated an insufficient/unauthorized response. The gate's real state was unchanged. The correction makes feedback truthful; it does not turn invalid input into a successful authorization. Direct evaluator semantics, mutation guard, Impact Authorization and whitelist contents remain unchanged.

## Recorded Baseline vs. Treatment

| Existing suite | Baseline `5e66d34` | Existing correction `2a8b945` |
|---|---|---|
| New schema/feedback suite | Nine methods, failed with seven failure records including subtests | 9 passed |
| Context Sufficiency gate | 9 passed | 9 passed |
| Greenfield Worker context/progress | 9 passed | 9 passed |
| Repairer anchor | 3 passed | 3 passed |

Total treatment: **30 selected passing methods**, zero previously passing selected regressions. This is offline component/route evidence, not full-suite success or model-driven recovery. [EVIDENCE.json](EVIDENCE.json) contains curated original ledger summaries and hashes; [REPRODUCIBILITY.md](REPRODUCIBILITY.md) explains the original bootstrap and limitations.

The baseline state comparison captured `insufficient != sufficient` after successful authorization and `PREPARING_CONTEXT != CONTEXT_INSUFFICIENT` for an already terminal gate. Negative tests establish no new authorization before sufficiency, no state mutation after invalid input and continued rejection when impact/context conditions do not permit writes. The greenfield test can progress through repeated invalid checks to a legitimate write without counting rejected input as new successful context.

## Verified Git and PR status

At publication preparation, team main was `f842fb8fb6e63e3064891d26ee0b24981e55c847`; personal main was `7e96a3708d1dd9f0570104f63d70264aa9935fd5`. Neither has the fix commit in its ancestry. Team main still advertises an unrestricted kind string, confirming the mismatch is not fixed there.

- Fork branch [`fix/experiment18a-evidence-feedback`](https://github.com/tasneem-ahmed05/mini_hivo/tree/fix/experiment18a-evidence-feedback) points to exact treatment `2a8b945`.
- [Personal PR #2](https://github.com/tasneem-ahmed05/mini_hivo/pull/2) is open/unmerged against `fix/greenfield-worker-context-progress`.
- [Team PR #7](https://github.com/kareem232003/mini_hivo/pull/7) is open/unmerged with exact head `2a8b945`; [#9](https://github.com/kareem232003/mini_hivo/pull/9) and [#10](https://github.com/kareem232003/mini_hivo/pull/10) contain it through ancestry.
- Its code is published, not local-only, but **not merged into team main**. Its presence in Run-010 is execution provenance, not integration status.

This new follow-up diff is documentation-only, based directly on team main. It does not copy the four-file implementation or change any existing PR. The original implementation report's earlier uncommitted/unpublished wording describes its historical checkpoint, not current publication state.

## Remaining unknowns and limits

The model can still emit invalid kinds despite a correct enum; runtime validation remains necessary. The correction does not prove that rejected-kind feedback alone caused Run-009's Repairer behavior, solve every recovery-tool incompatibility, or activate optional greenfield progress/grounding wrappers. Exact original rejected kind names and complete model-visible requests were not preserved.

Run-010 observed three sufficient decisions with no kind errors; that is not a live negative-path validation. Repairer had not written before interruption, which is not a natural terminal verdict. No complete repair/fresh-game-verification/final-acceptance chain was demonstrated.

Future work is separately authorized controlled integration and investigation of remaining recovery/verification boundaries. Neither a new live attempt nor a broad safety/policy redesign is part of this historical follow-up.
