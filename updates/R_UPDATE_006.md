# R_UPDATE_006 — Repair handoff evidence and measure the live run budget

## A. Update identification

- **Date:** 2026-11-18 (UTC+02:00). **Branch:** `audit/decision-evidence`, local and uncommitted.
- **Baseline:** Git `4096ccc3b405b2ed487040400e757d83c03df4ae` plus the uncommitted implementation recorded in [R_UPDATE_005](R_UPDATE_005.md), frozen before the team edits.
- **Tested runtime SHA-256:** baseline `5f87348506a50601e909e1f0afa712644192d9c77bf2da9a5f735bbfb8a3dbf2`; candidate `84abeac0981598768c1f3c54a1f154c7a78660d7e05fa10b3793b82fed422f4a`. These hash a newline-separated ordered manifest of `relative-path:SHA256-of-file-bytes` for `mini.py` followed by sorted top-level `hivo/*.py`; they are not commit IDs.
- **Acceptance scope:** selected controlled and offline repairs, real Edge on authored fixtures, and a live local-model exact-text success plus a live budget-stop control. No research efficacy or full-stack model acceptance is claimed.

## B. Original problem

When asked to audit and improve Mini Hivo, the earlier update found false verification successes and unsupported task-breadth verdicts. The follow-up requested parallel repairs, execution on the live CLI, and a separate research note. The measurable failures included undefined impact targets invented from prose, reference files misrouted as syntax targets, real failures erased by later unavailable observations, stale child evidence reused across dependency changes, and dependency consumers receiving an old sibling summary.

The fixed live request used in clean workspaces was: **“Create a text file named lifecycle-check.txt containing exactly:DECISION_READY”**. The expected product is the 14 UTF-8 bytes `DECISION_READY`, without a newline or another application file.

## C. Why this update was necessary

An agent can do the right work and still be stopped by invented scope or by checks on the wrong file. Conversely, an unrelated PASS cannot certify that an earlier failed check recovered. These cases would contaminate a comparison of smaller models or split strategies, especially if repairs, retries, and verifier calls were free in one arm.

## D. Root causes

| Boundary | Confirmed cause |
|---|---|
| Repair intent and impact | Missing common repair verbs and clause qualifiers made the implementation/reference distinction ambiguous. When structured targets were missing, the impact fallback treated ordinary words as required symbols. Legacy verification could then select a mentioned inspection file rather than the mutation target. |
| Verification evidence | Latest-by-tool-and-target did not preserve an unresolved executable failure when the new observation was unavailable, or distinguish browser role/profile/oracle scope. |
| Child handoff | Local dependency traversal recognized JS-style imports but missed the executed fixture's Python import chain. The atomic path could select an older gate alongside a terminal rejection. |
| Scheduler and stop decisions | Declared prerequisites could appear after their consumers in the list. Inherited summaries could occupy a local sibling ID. Repeated mixed tool refusals and a repeated browser symptom were interpreted as task breadth. |
| Research measurement | Per-leaf budgets did not directly bound the root's paid-in-compute generation attempts. Missing token observations were not retained per role and attempt. |

## E. What changed

- [Execution contracts](../hivo/execution_contracts.py), [pre-mutation impact](../hivo/pre_mutation_impact.py), and the [controller](../mini.py) preserve explicit mutation authority and distinguish repair targets from reference-only files. No target is manufactured for ambiguous prose. A unique accepted legacy mutation target feeds verification without changing the exact approved route.
- [Evidence](../hivo/evidence.py), [integration](../hivo/integration_gate.py), and [atomic child receipt validation](../hivo/atomic_child_receipt.py) keep unresolved failures, follow bounded local Python dependencies, and reject contradictory/incomplete terminal receipts on the atomic path.
- [Dependency ordering](../hivo/dependency_schedule.py) respects explicit edges and uses current sibling results. It remains sequential; cycles and ambiguous IDs fail closed. [Failure decisions](../hivo/failure_decision.py) report bounded observations without inferring incapacity.
- [Budget](../hivo/run_budget.py) and [usage metering](../hivo/provider_usage.py) add optional shared admission limits and provider-reported token counts. The [paired-report CLI](../scripts/paired_quality_audit.py) reports declared comparisons, missing, blocked, and timed-out cases; it neither runs nor independently verifies a model.

## F. How the fixes work

The context and impact gates still run before writing. A names-only request with no authoritative mutable target fails before editing; denied paths and exact approved routes retain their boundaries. Proof of a changed workspace must be fresh. A blocked or unavailable repeat is evidence about the verifier, not evidence that the earlier failure disappeared. A required atomic receipt route must match an executed PASS with the same scope.

A child starts only after its explicit prerequisites, with local results taking precedence over inherited IDs. A run-wide limit charges admitted generation retries and proposed tool calls across roles. The deadline is for admission and final commit checks, not a promise to preempt an in-flight child process. An exhausted budget reports a stop and rolls back an active transaction without reversing earlier verified commits.

## G. Functional verification

**Controlled functional** — The repair fixture ran the real controller, exact Python command verifier, transaction and impact gates using scripted model responses. `Fix a typo in status.py based on example.py. It must print READY.` produced a saved `status.py` that independently printed `READY`; attempted editing of `example.py` was refused and its original bytes were unchanged. In a separate fixture, a real Python check importing through three local modules passed before a dependency edit; a change to an unrelated module retained freshness, while a change affecting the actual result invalidated the child receipt. No model-quality conclusion is drawn from either fixture.

**Live model** — Same installed `gemma4:e4b` digest `c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb`, Python 3.13.7, fresh workspaces. The public batch CLI used normal host qualification. A local QA guard prevented execution of generated code; it did not substitute the provider or the controller. An external process read the product after CLI exit and compared exact bytes and extra products.

| Trial | Outcome | Task model calls / proposed tool calls | Wall time, including setup |
|---|---|---:|---:|
| Baseline initial | `MemoryError` during app import; no task | 0 / not reached | 1.440 s |
| Baseline retry | `CRITICAL_MEMORY_HEADROOM` after 3/3 true canaries; no task | 0 / not reached | 15.879 s |
| Candidate `20261118T095408-aa09c5a2` | Exit 0, `done`, independent exact bytes and no extra product | 10 / 5 | 53.459 s |
| Candidate with `--max-model-calls 1`, `20261118T095543-16008c2d` | Exit 1, `budget_exhausted`, no final success/no file | 1 / 0 | 25.069 s |
| Qualified baseline `20261118T095609-82d8e155` | Exit 0, `done`, same independently verified bytes | 10 / 5 | 54.605 s |

Both positive products hash to `7600a986a22cdd440d20f201e55b48f7a2af6ab43bbee710d92275fe092343aa`. `auto` selected `baseline` in both. The candidate received **20,701 input tokens and 926 output tokens reported by Ollama** for the 10 task generation attempts, with no missing count; earlier infrastructure canaries are excluded. The baseline did not record those counts. The single qualified pair cannot establish a speed or success-rate improvement.

## H. Additional successful tests

| Check | Result | Boundary |
|---|---|---|
| Same final five-suite subset, baseline and candidate | **74/88 → 88/88** methods meeting assertions, no skips. Baseline had 14 distinct failing/errored methods (36 failure and 3 error records, including subtests). | Exact pinned base; provider transport blocked; test cases include evidence, repair intent, impact, child freshness, and atomic receipt outcomes. |
| Selected 26-suite regression | **574 reported, 570 passed, 4 existing skips**, exit 0. | No real provider requests. Includes the 88 above and earlier controller tests; totals are not additive. |
| Existing opt-in Edge fixtures | **5/5**, exit 0. | Real headless Edge on trusted HTML/JS fixtures, including deliberate errors and missing assets; no model-generated full stack. |

## I. Regression and compatibility

Earlier integrated snapshots failed before completion. They exposed stale summary precedence, syntax routing through a read-only reference, and mismatch with exact approved routes. The final implementation leaves approved routes unchanged; the last selected regression includes their dedicated tests. The authored fixture for `status.py` requires independently executed behavior, not a passing receipt alone. The pending initial logs and failed live trials remain retained.

Ten native workers were dispatched together with separate ownership. The budget, provider usage, and paired-report workers left handoffs. The other seven original scopes became unavailable after the session interruption; partial work was retained and the coordinator finished and tested the remaining changes. Full HarrTest native provenance was **not verified** (the formal verifier required a Codex parent thread); no missing handoff was manufactured.

## J. Overall impact

The measured acceptance changes improve the correctness of controller decisions: scoped edits can be accepted with a real current verification; incomplete receipts and misleading granularity conclusions are no longer treated as success or proof of task size in the tested scenarios. Live evidence establishes exact artifact delivery and one shared call-limit stop on the candidate. It shows no difference in final quality for the qualified literal pair.

## K. Remaining limitations

- No live full-stack, approved multi-child recovery, or equal-budget adaptive-splitting efficacy claim. The scope was limited to a benign exact-file live prompt on the shared host; trusted runtime fixtures separately exercised Python/Node/Edge.
- Static dependency discovery is bounded and does not infer arbitrary dynamic imports. The attribution changes do not implement a general correction-before-split policy.
- Model-call and tool-call limits are not token limits. The new comparer validates declared equality and record structure, not the underlying runtime's compliance by itself.
- Whole-suite discovery and multi-seed held-out comparisons were not run. See the [research note](../docs/RESEARCH_AUDIT_NOTE.md) for what would actually answer the paper question.

## L. Evidence and reproduction

```powershell
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_parallel_repair_integration.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_dependency_aware_scheduler.py -v
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -p test_verified_child_integration.py -v
```

In the matched offline subset, discovery used the same `tests` directory for `test_evidence_policy.py`, `test_structured_worker_contract.py`, `test_pre_mutation_impact.py`, `test_verified_child_integration.py`, and `test_experiment8_atomic_child_receipt.py`, with the current tree or frozen baseline as working directory and unexpected provider transport blocked. In the live probe the public command was `python -B mini.py --workspace <fresh-dir> --prompt-file <fixed-request> --model gemma4:e4b --no-bootstrap`, with only the negative arm adding `--max-model-calls 1`. Raw receipts and logs are retained privately under the ignored `.runtime-proof` team directory. No staged-blob verification or external publication occurred.

## M. Summary for the team

**Proposed PR title:** Keep Mini Hivo decisions tied to current scope, handoff proof, and run budgets.

**Proposed body:** Repair scope inference and verification routing, retain unresolved proof failures, bind child receipts to local dependencies, and record bounded attempt cost. Matched offline methods improved from 74/88 to 88/88; the selected regression had 570 passes and 4 legacy skips. Actual local Gemma independently produced exact bytes on both qualified sources. The candidate additionally stopped at the declared one-call limit with no file or root success. No general live quality or swarm uplift is claimed. Local changes only.
