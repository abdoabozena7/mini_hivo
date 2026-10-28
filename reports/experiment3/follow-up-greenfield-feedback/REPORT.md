# Experiment 3 Follow-up — Historical Greenfield Feedback Retention and Worker Progress Fixes

**Status:** Existing implementation, retrospectively documented; offline mechanism validation and later live mutation observations. No new fix, test run or E2E trial was performed for this submission.

**Contribution:** Tasneem's post-handoff investigation, implementation and validation. The original Experiment 3 and inherited progress/grounding mechanisms retain their original authorship. This is a follow-up, not a newly numbered experiment or a claim to have implemented those original mechanisms.

## Research question and relation to Experiment 3

Can the ordinary greenfield Worker retain a successful Context Sufficiency decision in its next model request, perform a legitimately authorized mutation, and terminate a persistent context-only loop before exhausting its budget?

The [original Experiment 3](../rkey_01/report.md) compared `current` and `progress_constrained`: the current arm repeated 26 context checks within 28 observed steps; the treatment attempted two rejected mutations and made no legal mutation. It did not establish productive greenfield execution. Tasneem's Run-006 reproduced a related non-progress signature on a different task and route; it was not a byte-identical repeat of Experiment 3.

Hypothesis tested during the previous implementation: retaining actual successful gate feedback permits a feedback-dependent Worker to progress; a separate bounded repetition check terminates a Worker that ignores feedback. Neither correction grants authority or forces a write.

## Fix History / Run Timeline

| Historical point | What actually happened | Evidence and interpretation |
|---|---|---|
| Original Experiment 3, before Tasneem's handoff work | Current-arm repetition and budget exhaustion; optional constrained treatment changed behavior but produced no legal mutation | [Original results](../rkey_01/report.json). Prior research, not Tasneem's implementation |
| Coin Courier Run-006 | Worker 1: 28 context checks; Worker 2: listing then 27 checks. Of 55 decisions, 54 sufficient and one invalid. Both exhausted budgets; no game files | [Original Run-006 report](https://github.com/tasneem-ahmed05/mini_hivo/blob/1e233845b3e9d26b10bb66238ec13a00f108356e/reports/real-task-01/RUN-006.md). Missions had null execution-contract IDs |
| Subsequent cross-experiment investigation | Identified missing wrapper activation and a feedback-loss hypothesis, not yet a proven historical cause | [PR #3 findings](https://github.com/tasneem-ahmed05/mini_hivo/blob/3d20a720302c05d527bb72a0540e726fc525c9e2/reports/e2e-cross-experiment-integration/NEW-INTEGRATION-FINDINGS.md) |
| 21 October implementation phase, before Run-007 | Tasneem reproduced feedback loss through the compiled greenfield route; implemented retention first, then the bounded safeguard in `mini.py` in the isolated Worker worktree | Base `1e233845b3e9d26b10bb66238ec13a00f108356e`; branch `fix/greenfield-worker-context-progress`. Intermediate corrections were uncommitted states, not separately published commits |
| Recorded offline comparison | Same two provider-controlled cases tested baseline, feedback-only and both corrections | [Evidence ledger](EVIDENCE.json), [original implementation report](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/worker-context-progress/README.md) |
| Run-007 | Corrected Worker passed context/impact checks and wrote `index.html`; browser failure was investigated as implicit-favicon noise | [Runs 007–009 handoff](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/coin-courier-runtime-integration/ENGINEERING-HANDOFF.md). No final transaction acceptance |
| Run-008 | Builder wrote the candidate and passed basic loading; required game check failed; Repairer anchor defect caused denial and rollback | Same handoff. Progress observed, not complete game verification |
| Run-009 | Builder performed two writes and one edit after authorization; Repairer was authorized after the separate anchor correction but made no mutation before interruption | Same handoff, native lines 46/85/121 and SQLite events 1–9/14–23. No accepted final transaction |
| 21 October, 16:38:26 +03:00 | Existing changes and tests committed as `5e66d34db1827b814abf98f56b0b77b5ef6f8ee5` by Tasneem | [Exact implementation commit](https://github.com/tasneem-ahmed05/mini_hivo/commit/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5). Commit also contains independent ingestion/browser/Repairer work; those are not copied here |
| Run-010, 22 October | Descendant `2a8b945` included these fixes. Builder used one sufficient context check, received impact authorization and persisted a 13,012-byte HTML candidate | Original Run-010 `REPORT.md` and extraction are LOCAL-ONLY, hashes in [ledger](EVIDENCE.json). Required gameplay failed; no optional wrapper activation or final acceptance established |
| Publication status checked for this follow-up | Fix is on the personal fork and in open cumulative team PRs; not in team main | Exact heads and ancestry recorded below. Inclusion in a run is not merge evidence |

## Exact implementation and original location

Local implementation location: the isolated `worker-progress-implementation-20261021/worktree`, branch `fix/greenfield-worker-context-progress`; relative location is historical context, not a link to an inaccessible host.

| Fix | Actual production change | Existing test |
|---|---|---|
| Successful-context feedback retention | [`mini.py::execute_agent_task`](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/mini.py) preserves the assistant/tool transcript and original mission after a successful gate, including on the unwrapped route | [`test_long_greenfield_mission_retains_gate_success_and_can_write`](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/tests/test_greenfield_context_progress.py) |
| Repeated successful-check safeguard | Same function counts consecutive same-anchor successes only on the unwrapped initial Builder route. Three repeats after the first success give an explicit `WORKER_NO_MUTATION_PROGRESS` after four calls | Same test module: repeated checks, intervening tools, denied impact, insufficient context, path escape and precommit negative controls |

The old reconstruction applied prefix compaction to `base_worker_prompt + CONTEXT GATE UPDATE + feedback` with a 4,200-character limit and discarded prior tool messages. The controlled initial user mission was 10,297 characters; appended success feedback was absent from the following request. The implementation defect is confirmed by deterministic reproduction. Complete original model-visible requests from Run-006 are unavailable, so sole historical causation remains unproven.

## Recorded Baseline vs. Treatment results

| Existing two-case protocol | Feedback-dependent provider | Provider that keeps checking |
|---|---|---|
| Baseline | 28 checks, budget exhausted, success feedback absent | 28 checks, budget exhausted |
| Retention correction alone | Authorized real file write in two tool steps | Still exhausted 28-step budget |
| Both existing corrections | Authorized real file write in two steps | Explicit failure in four steps; no artifact |

The feedback-only suite exits with one failing test because the safeguard case is intentionally still unresolved. That is an informative intermediate result, not an all-green treatment. Two methods are not independent live software tasks.

The final recorded cohort has nine new greenfield methods and 129 existing mechanism methods: **138 selected passing methods**, not full-suite success. Cases traverse real compilation, context/impact gates and file tools with deterministic mission/provider seams. The temporary artifact is `artifact.txt`, not manually implemented Coin Courier code. Test cleanup removes it. Follow [REPRODUCIBILITY.md](REPRODUCIBILITY.md) for original test identities and access limits; nothing was rerun for this documentation.

## Verified Git status, not inferred integration

At publication preparation, team `main` was `f842fb8fb6e63e3064891d26ee0b24981e55c847`; personal `main` was `7e96a3708d1dd9f0570104f63d70264aa9935fd5`. Neither contains the implementation commit in its ancestry. Team main still has the old successful-feedback reconstruction and lacks the new repetition counter. Therefore these fixes are **published, but not merged into team main**.

- Personal branch [`fix/greenfield-worker-context-progress`](https://github.com/tasneem-ahmed05/mini_hivo/tree/fix/greenfield-worker-context-progress) points to `5e66d34`.
- [Personal PR #1](https://github.com/tasneem-ahmed05/mini_hivo/pull/1) is open, unmerged, targeting the earlier runtime-fix branch.
- [Team PR #7](https://github.com/kareem232003/mini_hivo/pull/7) is open, unmerged, head `2a8b945`, and includes `5e66d34` in its ancestry. Team PRs [#9](https://github.com/kareem232003/mini_hivo/pull/9) and [#10](https://github.com/kareem232003/mini_hivo/pull/10) also inherit it.
- [Team PR #4](https://github.com/kareem232003/mini_hivo/pull/4) is related handoff documentation, not the implementation submission.

This follow-up branch is based directly on team main. Its diff contains only this documentation/evidence and its index link; it does **not** carry the implementation commit, inherited code or regression tests again. Reviewers can read it before any implementation PR is merged.

## Safety, limitations and remaining work

- Existing context sufficiency, impact authorization, fresh-response requirements, workspace containment and precommit checks remain enforced by the correction. Successful context alone is not write permission.
- The optional `progress_constrained`/grounding wrappers still require an eligible execution contract and allowed paths. Greenfield missions had null IDs; a policy flag alone was not demonstrated to activate them. This correction is not a new greenfield authority design.
- The bounded safeguard does not cover arbitrary alternating read/verify loops, recovery loops or insufficient-context feedback reconstruction. No generic autonomous-progress guarantee is supported.
- Recorded broad recovery tests had baseline-matching failures/errors/skips, including missing historical fixtures. The 138 passing selected tests do not certify full recovery.
- Runs 007–010 corroborate real Worker mutations, but differ in other fixes, runtime conditions and ingestion history. Run-006 used withheld ingestion rewrites. They are not matched live Before/After arms isolating this fix.
- No successful live Repairer mutation/complete Coin Courier transaction is established. No new live validation was performed here.

The useful contribution is the traceable existing correction and isolated separation of feedback retention from bounded failure—not a claim that the whole Experiment 3 problem is solved.
