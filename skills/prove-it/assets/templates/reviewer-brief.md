# Independent behavior review brief

Original user goal and requirement IDs:
Scope and source identity:
Permitted environment, data and operations:
Existing acceptance oracles and protected constraints:
Real product entry point and available tools:
Raw artifact and execution-log paths:

First derive the expected behavior from the original requirement. Then exercise
or inspect actual behavior. Do not start by approving the implementer's summary.
Try representative failure cases and check that the verifier would reject them.
Inspect the actual screenshots/videos where visual claims are made. Check
integrated behavior, not only individual components or child reports.

Record actual reviewer identity and independence level. Cite commands, tool IDs,
source identity, observed outcomes and exact files. Identify contradictions,
untested states, misleading mocks/replay and weakened acceptance. Do not modify
the implementation, evidence, protected datasets or thresholds merely to pass.
Return VERIFIED_FOR_REVIEWED_SCOPE, FAIL or UNVERIFIED with concrete findings.
A separate model is not assumed infallible; describe remaining uncertainty.
