# Integration dependencies revealed by the new findings

[Findings](NEW-INTEGRATION-FINDINGS.md) · [Controlled comparison](CONTROLLED-VALIDATION-PROTOCOL.md)

## F5: owner deliverables, not an E2E-owned mechanism patch

PR #2 already requests further Worker investigation. The additional contribution here is a set of route-specific obligations and observable exit criteria derived from F1–F4. The E2E role validates reviewed mechanisms together; it does not implement the main Experiment 18 changes or supply game code.

| Dependency / evidence class | Why it matters now | Appropriate owner | Evidence required before an integration claim |
|---|---|---|---|
| **Greenfield wrapper activation — confirmed coverage gap** | Null execution-contract IDs and absent summaries contrast with contract-dependent wrapper construction. | Mechanism owner with integration/smoke reviewer | A supported authority path for real greenfield CLI Workers, plus activation/non-activation records and regression tests that do not inject an artificial approved contract to hide the gap. Preserve context, impact and scope gates. |
| **Progress after sufficiency — confirmed observed failure; cause unresolved** | Existing Experiment 3 protection was neither selected nor demonstrated active on this route. | Worker/progress mechanism owner | A failing-before/passing-after controller fixture for the actual route; bounded repeated checks; retained gate state. Earlier safe failure alone must not be described as application success. |
| **Context feedback retention — specific hypothesis** | Prefix compaction can remove appended feedback; actual subsequent request bodies are unavailable. | Context/controller mechanism owner | Long-mission fixture proving which obligations and final authorization feedback reach the next request. Safe bounded captures or hashes/field-presence assertions; no invented reconstruction of the old payload. |
| **Experiment 18 schema alignment — confirmed discrepancy, newly corroborated** | Event 30 rejected three kind requests permitted by the schema's unrestricted string field. | Experiment 18 context mechanism owner | Advertised/accepted request-kind agreement; valid requests supported; unsupported, broad or malformed evidence still rejected clearly. Demonstrate whether meaningful completion occurs, not merely a sufficient flag. |
| **Recovery-tool compatibility — previously diagnosed, future integration dependency** | Experiment 18B's instruction names a tool that the locator can remove; Coin Courier never reached that sequence. | Experiment 18 grounding/recovery owner with locator reviewer | Active schema and recovery guidance agree; fresh-source recovery works under the chosen locator policy; stale/foreign edits remain blocked. Do not count current Coin Courier as a reproduction of this defect. |
| **Regression-safe ingestion — previously known prerequisite, newly explicit comparison control** | Historical Run-006 needed two withheld rewrites; replacing them changes the executable Before state. | Ingestion/project-understanding owners and integration reviewer | Compatible requirements accepted while genuine contradictions remain detectable; genuine greenfield and explicit existing-project intent both preserved. Freeze the same reviewed ingestion revision in both comparison arms. |
| **Verification and independent acceptance — missing observation** | `field_scoped` was selected but no application verifier ran. A future integrated policy may expose new downstream failures. | Verification owner; E2E validator independently assesses the artifact | Actual profile/behavior evidence, valid receipts and fresh parent proof where applicable; independent original acceptance results. Never use a verifier PASS as the sole completion oracle. |

## Availability is not integration approval

At the inspected publication checkpoint, team `main` is `f842fb8`; merged [PR #1](https://github.com/kareem232003/mini_hivo/pull/1) adds Experiment 18 documentation/findings, not mechanism code. [PR #2](https://github.com/kareem232003/mini_hivo/pull/2) remains a separate Draft with runtime changes and execution documentation. Neither establishes a merged correction for these Worker/schema integration findings. Unpublished or private teammate work is unavailable evidence; it must not be assumed present in a future executable baseline.

Experiment 17's classifier and Experiment 15's bounded refresh already exist as optional policies. They are not newly merged Experiment 18 fixes. A future owner handoff must identify exact source commits, relevant regression evidence, effective policies, supported project modes and limitations. The [coverage matrix](CROSS-EXPERIMENT-TRACEABILITY.md) identifies what still needs live exercise.

## What the E2E validator can complete without another run

- Audit proposed owner changes against the matrix and request missing route/activation evidence.
- Map the existing Coin Courier acceptance obligations to actual production assertions, identifying obligations still requiring independent checks.
- Freeze a proposed matched source/configuration pair and document which finding each treatment tests.
- Preserve the old traces and publish targeted evidence projections such as event 30, without changing their conclusions.

Meaningful downstream rerun validation should wait for a reviewed executable source/policy combination and a regression-safe ingestion path. Investigating Worker progress does not require waiting for an unrelated Timer-specific oracle improvement, but it does require preserving grounding/authorization and documenting downstream untested boundaries. No integration change, alternate-policy run, or new application attempt is performed by this research package.
