# Experiment 18 — No-Tool Worker Exit Guard

The optional `worker_no_tool_policy=bounded_reanchor` applies only to a Builder
with an approved mutation path and no previous tool call or evidence. One
prose-only or empty response receives one re-anchor inside the existing
28-round budget. A second such response returns `NO_EXECUTION_PROGRESS`.
Once a tool is called, the existing context, impact, grounding, verification,
and integration gates apply unchanged. The default remains `current`.

The 2026-11-16 consolidation extends this same explicit opt-in to a new-project
Builder without pre-approved mutation paths. It still permits only one
re-anchor, consumes the existing round budget, and never authorizes mutation.
The historical measurements below used approved contracts and their pinned
original source; they are not rerun or relabeled by this extension.

The Python A/B uses the same frozen approved contract and seed from Experiment
12, model `gemma4:e4b`, strict evidence, evidence-bound mutation, and
field-scoped verification classification. Each policy has three fresh runs.
The cross-domain suite runs Timer and Python three times each with both
Experiment 17 and 18 options enabled. Original workspaces/logs are outside
this repository; manifests and audited summaries are saved here.

The primary diagnostic is the boundary from Worker start to the first tool
call, context decision, first legal mutation, and verification. Root success
is reported separately. Three runs per case are not a population reliability
estimate, and approved planning cost is excluded.
