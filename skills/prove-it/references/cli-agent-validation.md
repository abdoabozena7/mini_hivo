# CLI, Mini Hivo and generated-artifact validation

## Exercise the real boundary

Discover the actual documented CLI or UI entry point. Use the configured real
models/providers and permissioned tools. Send a representative prompt through
that boundary; do not call a mocked internal function and describe it as a full
agent run. Record prompt, run/session ID, configuration, model identity where
available, tool calls, task plan, worker outputs, stderr, exit status and artifacts.
Do not log credentials or private corporate prompts unnecessarily.

A shell process is enough for a noninteractive CLI. For a true interactive/TUI
workflow use the host's terminal interaction tools or an approved PTY adapter.
`scripts/proof.py` supports argv plus optional stdin from a file; it is not a
universal Windows terminal GUI automation tool. Never claim interactive coverage
when only a noninteractive command was exercised.

## Judge both orchestration and the produced result

For a Mini Hivo-style task, inspect whether the plan covers the original request,
its task boundaries are executable, dependencies are correct, workers receive
needed context, and useful failures reach the coordinator. Observe the actual
point where progress stops. Do not infer worker execution from a generated plan.

Then inspect and run the output as a user would. A generated web feature needs
a real browser journey; a generated API needs requests and observable state;
a generated CLI needs real inputs and independent outputs. The pipeline claiming
"completed" is not the oracle for its own generated product.

Compare with the original user request. Verify the requested feature, not merely
that some code was produced. Check that generated tests actually fail for known
incorrect behavior. Do not let the worker's own tests be the sole final judge.

## Useful bounded prompt set

Use a small explicit development set appropriate to the request: a new feature,
a targeted bug fix, a cross-file integration, an error/recovery case, and a
constraint-preservation case. Avoid inventing a huge benchmark for a tiny change.
For stochastic claims, repeat the specified runs with recorded seeds/configs and
retain all outcomes; no best-of-N reporting disguised as the first run.

If a reserved evaluation set exists, do not tune on it. Keep prompts, expected
behavior and evaluation sources separate from the code being optimized. For
quality improvements, report baseline and modified results on comparable tasks,
not a single attractive anecdote.

## Observe and repair

Record the exact prompt, actual task graph, tool trace, generated diff, observed
failure, hypothesis, targeted fix and re-execution. Distinguish planner failures,
worker implementation failures, unavailable tools, context omissions, interface
mismatches and validator blind spots. More subagents is not a default solution.
A serial decomposition may be better when work is tightly coupled.

Validate error cases: malformed input, missing credentials, worker timeouts,
invalid generated code, retry loops, incomplete task coverage and false final
success. Preserve genuine external blockers; do not mock them away in final
acceptance. Do not send work to paid external providers without authority.

## Report

Provide the exact real entry command or interaction, prompt/run IDs, observed
plan/worker behavior, produced artifact path, independent runtime results,
failed cases and remaining gaps. Report separately:
- Pipeline executed.
- Required subtasks covered and integrated.
- Generated artifact actually ran.
- Requested behavior independently verified.

Only the conjunction supports a full pipeline task-completion claim.
