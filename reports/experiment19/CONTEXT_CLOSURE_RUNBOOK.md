# Experiment 19 — Mandatory Context Decision Closure

The optional `worker_context_decision_policy=bounded_closure` applies to an
approved mutation Builder after it has obtained new relevant source evidence
but has not submitted `context_sufficiency_check`. A prose or empty stop gets
one re-anchor within the existing 28-round budget. If the Worker still omits
the decision, the controller records `CONTEXT_DECISION_MISSING`. The same
classification applies when the provider filters repeated empty model
responses after that one re-anchor. Actual transport/provider errors retain
their existing path. The default remains `current`.

The A/B comparison holds the Experiment 18 no-tool guard, field-scoped browser
classification, strict semantic evidence, evidence-bound mutation, model
`gemma4:e4b`, approved Python contract, and seed fixed. Each arm has three
fresh runs. The only runtime variant is `worker_context_decision_policy`.

An initial diagnostic batch (`v1`) showed the provider retrying three empty
responses after the context re-anchor, then raising an incomplete-response
error before the controller could classify the missing decision. The final
`v2` batch includes the bounded classification for that exact provider signal
and uses newly pinned, identical production source in both arms. Only `v2`
contributes to the reported A/B rates.

The existing context gate still decides whether evidence is sufficient.
Controller tests prove an `insufficient` decision remains valid and a
`sufficient` claim against contradictory evidence cannot authorize mutation.
The run audit also counts authorizations with empty evidence, contradictions,
or unresolved semantic status. That count is a safety screen; it does not
replace independent behavior verification.
