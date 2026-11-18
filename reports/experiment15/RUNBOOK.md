# Experiment 15 — Mutation Grounding / Evidence-to-Edit Binding

## Intervention

`--mutation-grounding-policy evidence_bound` is optional. Both arms use the same
`strict` evidence policy, verification, recovery, model `gemma4:e4b`, Worker
strategy, tool set, 28-step budget, approval contracts and parent integration.

Only grounding refresh authorization changes: a complete, exact native read of
the current file can supply the one existing bounded refresh if the file has
at most 80 lines. It observes the same source as a range read over those lines.
Large full reads, truncated/fabricated/stale reads, absent or duplicate anchors
and a retry outside the refreshed span remain rejected. No fuzzy matching.
Refresh does not grant a full rewrite or multiple replacement authority.

The normal full-file-read/write behavior before any refresh is unchanged. Scope,
context and impact guards still authorize mutations independently of grounding.
An unapproved target is rejected by the existing scope layer. Grounding does
not turn read permission into mutation authority.

Telemetry records candidate arguments/hash, source hash before authorization,
underlying evidence reason, refresh state and observed span hashes for both
arms. The same actual file tools execute every accepted candidate. The fresh
runner observes tool calls without changing their decisions or returns.

## Historical case and limits

The Exp13 `arena_arrow/monotonic-3` run already reached its first legal mutation
at step 3 and applied two mutations. It failed at a later candidate at step 9.
After rejection, a full reread did not register as the required range refresh.

The exact old/new strings of the last rejected historical call were not stored.
They cannot be recovered from the saved patch or final source. This experiment
does not claim to replay or repair that exact call. The new telemetry prevents
this loss in future runs.

Declared protocol challenges recreate this class of grounding state with known
reference requests across ArrowUp, Q-restart and Node uniqueness fixtures.
There are nine positives (full-refresh cases plus bounded-range controls) and
24 negatives per arm. These are controlled authorization inputs, not fresh
Worker/Root success rates. Every accepted reference edit runs native behavior
verification. Files are disposable and source/test scope is checked independently.

The first protocol accounting pass included controller logs in scope/input hash
counters. `binding-v2` counts project fixture files and any foreign test target;
instrumentation databases/logs are excluded. Production was unchanged. Raw v1
is retained as a development artifact and is not mixed into the final rates.

## Fresh runs

Three Exp14 eligible tasks × three fresh runs × two grounding arms = 18 attempts.
Contracts and source seeds are exactly the Exp14 inputs. The primary boundary
is frozen approved contract → original Worker → child verification/receipt →
fresh parent proof. Planning and host preflight costs are excluded.

All attempts stay in denominators. Metrics distinguish first legal mutation
from later grounding failure and rollback. Actual applied file edits must match
the recorded fresh source hash. A separate measurement oracle checks whether
the diff touched the keydown handler or `uniqueValues` body. This oracle does
not authorize edits, alter prompts, or substitute for behavioral verification.

The source hashes of strict matching, verifier, receipts, recovery/progress and
integration are fixed. AST pins confirm that the controller Worker, model/tool
dispatch, verifier, receipt handoff and integration functions match Exp14.
The grounding module changes; mini.py only adds the optional policy value.

## Reproduce

Use new directories. Existing Ollama, Node and browser dependencies are needed;
the runner does not install them or choose a different model.

```powershell
.venv\Scripts\python.exe -X utf8 scripts/experiment15_run.py preregister --baseline D:\projects\Ai\mini_hivo_experiment14\suite-v2 --output-dir D:\projects\Ai\mini_hivo_experiment15\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment15_binding_probe.py --suite D:\projects\Ai\mini_hivo_experiment15\new-suite --output-dir D:\projects\Ai\mini_hivo_experiment15\new-binding --history D:\projects\Ai\mini_hivo_experiment13\suite-v1\arena_arrow\monotonic-3
.venv\Scripts\python.exe -X utf8 scripts/experiment15_run.py batch --output-dir D:\projects\Ai\mini_hivo_experiment15\new-suite
.venv\Scripts\python.exe -X utf8 scripts/experiment15_report.py --suite D:\projects\Ai\mini_hivo_experiment15\new-suite --probe D:\projects\Ai\mini_hivo_experiment15\new-binding\comparison.json --output-dir D:\projects\Ai\mini_hivo_experiment15\new-report
```

The report refuses an incomplete final batch. Root success requires fresh parent
proof covering the approved requirement, not reuse of child evidence. Costs
include failed attempts. Timer/Python remain outside this fixed comparison;
no generalization to their other upstream/verifier bottlenecks is claimed.

Protocol improvement alone cannot prove an end-to-end gain. If fresh baseline
already has zero grounding failures, a failure-rate reduction is unmeasurable
on that sample. The report explicitly separates these conclusions and records
whether the new full-refresh path was actually exercised by fresh Workers.

The policy stays experimental. Default grounding/evidence policies are unchanged.
