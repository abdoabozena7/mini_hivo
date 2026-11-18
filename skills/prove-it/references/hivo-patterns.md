# Hivo-inspired decision patterns (Prove It v1)

Adapt architectural ideas, not Hivo's project-specific model, prompt budget, or claim of proven success. This guide is universal for coding agents with different tool permissions.

## 1. Requirement provenance and coverage (before planning)

Build a **Source Requirement Ledger** from the user's exact request. Give each material requirement a stable `REQ-001` ID and distinguish:
- `USER_STATED`: explicit user requirement, quote or stable source reference.
- `USER_CONFIRMED`: later explicit clarification/decision.
- `DERIVED`: helpful assumption, not authorization to expand scope.
- `REPOSITORY_EVIDENCE`: observed current implementation fact, include file/line/hash.

Do not silently re-label an assumption as a user requirement. Attach each requested user journey to acceptance outcomes and to one or more plan tasks. Before acting, audit for omitted requirements, fabricated obligations, contradictory existing constraints and destructive changes.

Minimal ledger:

```markdown
| ID | Origin | User outcome | Acceptance oracle | Covered by |
|---|---|---|---|---|
| REQ-001 | USER_STATED | Camera switch changes rendered view | Switch camera and inspect changed live feed | T03,T07 |
```

## 2. Impact map + adversarial plan challenge

For changes to existing projects, locate actual owners, callers, consumers, data contracts, persistence and UX surfaces before deciding what to edit. Mark surfaces as `MUST_CHANGE`, `MAY_CHANGE`, `PRESERVE_ONLY`, or `INSPECT_ONLY`. Preserve legacy interfaces deliberately; a relevant file does not automatically require mutation.

Challenge the draft plan at least once: Can all tasks pass while a user requirement is still broken? Is the acceptance oracle circular? Could two workers edit the same owner? Is the final integration journey missing? Are there unapproved side effects? Make corrections before implementation; for small tasks, this review can be a single paragraph.

Freeze the approved/user-supplied scope in the plan and track changes explicitly. The skill does not invent formal user approval requirements, but any genuinely risky expansion still needs permission.

## 3. Context-sufficiency preflight

Before each worker's first edit, verify: concrete output, legal write scope, authoritative interface, relevant caller/consumer, preservation rule, test oracle and runnable tool path. If something critical is absent, obtain **specific** information (a symbol definition, schema, state transition, error trace, or caller expectation), not generic "read whole repo". Bound the reconnaissance and stop asking once enough facts exist.

If context is still insufficient, mark task `BLOCKED_CONTEXT` rather than mutate files speculatively. Report what evidence was sought and why it matters. Only treat an actual tool call as a tool call, and never synthesize missing results.

## 4. Adaptive decomposition and worker isolation

Start with an outcome-based DAG; split tasks when the subtask has a separately verifiable user-visible result, a stable interface, or a distinct dependency. Do not split solely to produce more agents. Replan a failed oversized leaf by replacing it with bounded descendants; retain the parent requirement and its final integration check.

Give subagents focused task projections, not entire chats. Each handoff includes exact change, inspected source hash, contract, known limitations and evidence. Coordinator alone owns shared TODO state. On return, independently run the integrated product; a passed child check does not imply parent success.

## 5. Failure classification and evidence-directed recovery

Classify before fixing:
- `PRODUCT_DEFECT`: actual user-visible behavior violated; repair source then re-run.
- `TEST_DEFECT`: oracle, fixture, or test runner invalid; repair verifier and retain unverified product state until real check.
- `TOOL_ENVIRONMENT`: missing browser/GPU/process, network/sandbox denial; diagnose host/instructions, never patch product to conceal it.
- `CONTRACT_GAP`: requirement or plan not executable; replan while preserving original authority.
- `CONTEXT_GAP`: missing semantic fact; targeted read then continue.
- `RESOURCE_LIMIT`: storage, time, credits, or external quota; report exact source of limit and legal options.
- `STAGNATION`: repeated actions produce no new relevant evidence; change hypothesis, worker, or inspection technique.

Every retry must state new hypothesis, intended observable effect and a falsifiable check. Repeating the same attempt with identical inputs isn't progress. Never bypass sandbox, acceptance budget, protected experiment, safety gate, or user-requested stop.

## 6. Verified-state memory and restart

Store compact known facts across sessions, not raw model explanations. Separate `DURABLE` facts (stable user requirements/authoritative contracts) from `STATE_BOUND` facts (passed behavior tied to exact source/config/inputs). Stale facts remain historical and never automatically count as fresh verification. On restart reload original requirements, approved scope, source fingerprints, completed evidence, unresolved failures and next ready task. Avoid dragging the entire old transcript into a new worker.

## 7. Independent quality measurement

Measure whether a real user journey succeeds on an agreed baseline and the final source. Prefer independent outcomes over self-authored tests. Keep negative-control failures, original crash logs, screenshots, comparisons, and incomplete runs. Code changes, agent claims, commits, or green mock tests alone never increase an acceptance score.

**Mini Hivo inspiration:** requirement ledger, evidence-guided impact planning, context sufficiency, contract-bound workers, parent verification, recovery classification and verified-memory reentry. This document is a reusable adaptation, not a claim that Mini Hivo's experimental policies have been proven universally effective.
