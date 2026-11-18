# Final technical assessment and handoff

[Overview](README.md) · [Detailed Run-006](RUN-006.md) · [Fixes and validation](FIXES-AND-VALIDATION.md) · [Evidence index](EVIDENCE-INDEX.md)

## Outcome

**Coin Courier was NOT completed.**

**No application files were generated in Run-006.**

**Independent application acceptance criteria were NOT TESTED.**

**Run-006 was deliberately stopped before a normal root verdict.**

**The Worker progress issue remains unresolved.**

The experiment successfully reached a meaningful capability observation after several startup/transport and ingestion boundaries were diagnosed. That observation is not application success: two real Workers failed to implement anything within their tool budgets while repeatedly checking context. Subsequent recursive planning was interrupted, so the final natural root outcome is unknown. The completed child failures are not erased by that uncertainty.

## What Mini Hivo demonstrated

With recorded local changes, the actual interactive CLI passed three real preflight canaries, accepted the original multi-requirement request, retained a 16-ID source ledger, completed specification expansion, created bounded Project/Task Brain state, chose adaptive splitting, compiled two Worker missions and entered focused execution. A malformed context decision was rejected; later decisions authorized mutations and accepted impact contracts. Tool-step limits stopped both non-progressing Workers, and the root continued scheduling/decomposing remaining work.

These are observed stage transitions. They do not establish complete requirement allocation, a high-quality plan, adequate semantic context, useful recovery, correct grounding, or an integrated application. Run-006 included two experimental ingestion rewrites that are not published; the final PR cannot be described as sufficient on its own to reproduce all of this progression.

## What was not demonstrated

There was no application mutation, runnable entry point, HUD, keyboard or touch behavior, scoring, collision, restart, localStorage handling, win condition, implemented `AGENT_GAME` adapter, browser-based application verification, or independent behavioral test. There was no normal root `FINAL` in Run-006 and no completed native final metrics ledger. No successful application artifact was later repaired manually or supplied by the investigator.

The acceptance status remains **NOT TESTED** for all A1–A10, as [defined in setup](EXPERIMENT-SETUP.md). Absence of an artifact is a failed overall delivery objective, but it does not justify inventing individual gameplay FAIL/PASS measurements. There are no application screenshots or videos to publish.

## Addressed infrastructure boundaries

The [published runtime changes](FIXES-AND-VALIDATION.md) address three concrete mechanisms: Python 3.11 parsing of reentry conflict-ID construction, a host-canary wait extended from 30 to 180 seconds, and a separate normal Ollama request wait extended from 120 to 600 seconds. The two original code-fix commits include actual mechanism assertions and retain the model, payload budgets, finite waits and failure gates. The final recorded runtime selection passed 57 tests, with 197 Python files compiled.

Those results support compatibility and transport behavior. They do not establish why inference was slow, GPU/CPU placement, provider cancellation, general model reliability, or agent success. Longer deadlines also increase time spent waiting on a genuinely stuck service. Configurable deadlines and clearer timeout labels are potential separate integration work; they were not implemented here.

## Ingestion boundaries remain unresolved in published source

Run-003 exposed predicate/negation scope loss: displaying a value was treated as conflicting with not lowering its persisted maximum. A local lexical rewrite cleared that prompt and passed selected regression suites, but missed genuine encrypt/log/compress contradictions in broader review. It is withheld.

Run-004 exposed incorrect existing-project classification of an empty greenfield build. A local bounded-phrase rewrite enabled the next attempts, but also misclassified explicit existing-project requests containing incidental empty-directory/cache language. It is withheld.

Accordingly, the original failed observations remain important, and neither attempted rewrite should be called a verified published capability fix. A future study must specify which corrected ingestion revision it uses; it cannot assume the runtime PR already contains those revisions.

## Worker progress: strongest supported conclusion

Worker 1 used all 28 steps on `context_sufficiency_check`. Worker 2 used one `list_files` and 27 context checks. Together they produced 55 context decisions, 54 sufficient and one invalid structured submission, with no file mutation. Both completed `budget_exhausted` results ended with sufficient context and mutation/impact authorization.

The first remaining blocker in Run-006 was therefore Worker 1's **failure to translate authorized context into implementation before tool-budget exhaustion**. The default policy's continued availability of the context tool is a plausible contributor, not an isolated causal explanation. Model instructions, conversation retention, tool feedback and controller state also require investigation. No Worker policy was modified and no alternate-policy success is claimed.

The scheduler's later recursion continued an unfinished root; it did not demonstrate successful recovery. Two leaf and two node-result failure events must not be counted as four independent failed Workers. Likewise, 68 model-request events include the last unfinished request, while only 67 model-response events were present.

## Context Sufficiency findings

Observed: schema rejection protected against one invalid decision; later evaluations returned sufficient and final, enabling mutation. The repeated calls largely did not gather new evidence or advance context rounds. This points to a progress/controller/model interaction after reported sufficiency rather than a sustained terminal insufficient-context refusal.

Unknown: whether all task-relevant semantic context was actually adequate; whether the model consistently retained the successful result; whether repetition came from tool exposure, instructions, compacted history or another cause. A sufficient flag is not an independent semantic oracle. The mechanism is neither proven fully correct nor proven universally broken by this trace.

## Mutation Grounding findings

Observed: impact authorization and mutation authorization were true at both Worker finishes. No write/edit call attempted to exercise grounding at the mutation boundary, and rollbacks restored no files.

Unknown: whether an actual edit would have valid anchors, correct scope and valid evidence; whether stale-anchor rejection, path authorization and post-mutation checks work on this task. There is no basis for attributing this failure to a grounding rejection or treating unused authorization as a successful grounding evaluation.

## Behavioral Verification findings

No application existed and no application browser verification occurred. There is no false-acceptance observation, gameplay-verifier failure or independent acceptance pass. The browser readiness check proved only a blank page could launch. The runtime unit tests exercise mechanisms with controlled inputs, not delivered game behavior.

## Evidence quality, gaps, and risks

Native JSONL and completed metrics where available are stronger stage evidence than outer shell exit codes or partial prompt-toolkit transcripts. Runs 004–005 have completed native failed-task metrics; Runs 003 and 006 are interrupted roots without normal final metrics. Run-006's 31 terminal chunks are tool-returned captures, not a lossless OS-level terminal recording. Run-003's full first question depends on a labeled investigator transcription. At least one Run-004 capture was truncated.

Original reports, snapshots, prompt, source diffs and evidence files were preserved locally. Small selected projections, exact prompt text, test commands/counts, source identities and checksums are published here. Raw logs, project memory, full source snapshots and review JSON remain local-only. GitHub readers can review the reasoning and published mechanism tests; independent full replay of the historical traces requires access to those original local records. No unavailable material is disguised as a working GitHub link.

The sequential recovery attempts are not controlled timing benchmarks: model loading/cache state was not reset between runs. The two withheld ingestion changes also confound any claim that extending the provider timeout alone caused end-to-end progress. Native worker failures remain measurable despite the later root interruption; ultimate completion remains unknown.

## Prioritized next investigations and ownership

| Priority | Owner | Concrete next work | Evidence required before claiming a fix |
|---|---|---|---|
| 1 | Experiment 18 research/fixes teammate | Reproduce sufficient-context repetition in a deterministic Worker/controller fixture; inspect offered tools, actual next model messages, state transitions and feedback retention. | A failing-before/passing-after mechanism test proving progress or an explicit bounded failure without bypassing context, grounding or authorization. |
| 2 | Experiment 18 research/fixes teammate, with integration review | Redesign requirement predicate/negation scope; include compatible display/persistence and unknown-action contradictions. | Positive and negative fixtures including encrypt/log/compress; no Coin Courier exception and no gate weakening. |
| 3 | Integration/smoke teammate | Review classification intent precedence, incidental empty locations, missing targets and meaningful-tree evidence. | Both genuine new builds and explicit existing-project mixed-intent cases remain correctly classified. |
| 4 | Integration/smoke teammate | Review runtime PR, supported Python coverage, configurable bounded deadlines, native exit propagation and reliable terminal capture. | Mechanism-level tests and explicit observability guarantees; no inference of task success from shell status. |
| 5 | End-to-End Execution and Validation | After separately reviewed fixes and future authorization, compare the unchanged prompt in a fresh workspace and execute independent acceptance only if an artifact exists. | Revision/config identity, preserved full trace, real browser/physical input checks and honest PASS/FAIL/BLOCKED/NOT TESTED results. |

No new experiment, application repair, policy substitution or implementation of these next steps is included in this documentation update. The practical handoff is one existing Draft PR containing reviewed runtime fixes and this complete diagnostic record, with the unresolved capability outcome kept visible.
