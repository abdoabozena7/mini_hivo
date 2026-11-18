# Fix literal greenfield impact authorization and exact-byte verification

## Why This Update?

An explicit text-file request could stop before mutation with a misleading impact error when the Builder had never submitted a context decision. The baseline also lacked concrete scope and an applicable exact-content verification route for that request. Source requirement IDs could be established too late for consistent traceability.

## What Changed and What Was Fixed?

- `mini.py`: retry an absent context decision once; preserve context/impact failure diagnostics; stop rejected contracts; compile recognized single literal text-file requests into an exact authorized path and expected UTF-8 digest; reconcile source IDs early; expose native byte verification through `run_file`.
- `hivo/requirements.py`: deterministic literal request extraction and conservative normalization of filename wording.
- `hivo/pre_mutation_impact.py`: validate required scope, source obligations and digest format; independently compare final bytes; retain IDs in Worker projections.
- `hivo/verification_routing.py`: require literal-artifact verification bound to tool, target, accepted contract, expected/observed digests and consistent status.
- Add 17 lifecycle tests and update the existing absent-context diagnostic expectation while retaining denied-mutation assertions.

The recognized request class now has concrete scope and exact-byte verification. Wrong content and generic, foreign or inconsistent proof cannot satisfy that route. Existing-project plan approval remains required. General impact planning, mutation grounding and authorization architecture predate this patch; they are not new features of this update.

## Functional Verification

The 21 October Git-workspace audit passed all **17 lifecycle tests**. The positive leaf test scripts model responses but uses real context/impact gates, writes, Builder/Falsifier readback, routing, aggregation, post-state checks and commit. It asserts that the resolved text file contains exactly `welcome`. Negative cases cover unsafe/out-of-scope paths, missing/tampered contracts, wrong content and invalid proof. Other assertions cover requirement IDs, conservative same-name mapping, candidate reuse and text verification without code execution.

The historical final controller replay independently records seven scripted responses, zero real model calls, status `done`, `root_verified=true` and matching bytes. All four current production hashes match its source pins. This verifies controller behavior under scripted decisions; **completed live-model implementation remains unverified**.

Reproduce from the repository root with dependencies installed and a writable temporary directory:

```powershell
python -B -X utf8 -m unittest discover -s tests -p test_greenfield_impact_lifecycle.py -v
```

The audit's first attempt hit Windows temporary-directory permission errors; its workspace-local-temp rerun passed without source changes. The evidence README provides that setup.

## Additional Successful Regression Tests

The same audit recorded these additional suites as OK:

| Suite pattern | Tests |
|---|---:|
| `test_pre_mutation_impact.py` | 27 |
| `test_context_sufficiency_gate.py` | 9 |
| `test_authority*.py` | 23 |
| `test_project_understanding.py` | 32 |
| `test_experiment*.py` | 122 |
| `test_adaptive_architecture.py` | 90 |

Use the discovery command above with each pattern. These are regression results, separate from the direct functional oracle; they do not prove that pre-existing features were introduced here. Counts overlap broader discovery and are not unique coverage totals. Publication preparation inspected saved results and did not rerun tests or live experiments.

## Remaining Issues

- Historical broad regression failed: **1,376 executed, 24 failure records, 18 errors, 10 skips**. The same 42 failure/error identities were present in the earlier baseline, but the comparison predates final routing refinements. No final-source full-suite pass is claimed.
- Historical fixture dependencies and browser availability remain unresolved. One requirement-compaction test was excluded because it invokes a live model.
- Final live auto execution timed out at Specifier before Worker; baseline was blocked by memory preflight. Process exit 0 was not task success. The earlier diagnostic was interrupted and the Phase 2 Node pilot failed.
- Scope compilation covers recognized single literal text-file requests, not arbitrary greenfield work. The exact historical unmapped requirement ID is unavailable.
- Curated exports omit machine inventories and raw runtime databases and do not constitute the complete raw archive. Experiment 17 is pre-existing partial classification evidence, not a successful current live run.

## Evidence References

The publication package contains sanitized derivatives with original/copy hashes; original evidence is preserved locally. Embedded source/contract hashes identify original records and do not make sanitized files runtime authorization receipts.

- [Functional tests](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/tests/test_greenfield_impact_lifecycle.py)
- [Evidence scope and reproduction](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/README.md)
- [Fresh lifecycle log](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/fresh/lifecycle.log)
- [Regression summary and individual log references](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/verification-summary.json)
- [Historical final controller replay](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/historical/controlled-final-result.json)
- [Historical broad failures](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/historical/full-regression-result.json)
- [Historical live outcomes](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/historical/live-results-summary.json)
- [Derivative provenance manifest](https://github.com/rodinaasfour665-ctrl/mini_hivo/blob/fix/impact-lifecycle-and-regression/evidence/impact-lifecycle-publication/manifest.json)

## Publication Scope

This follow-up publishes curated evidence while retaining raw originals locally. Paths and detailed host inventories are omitted from the publication copies; provenance hashes remain available. Removing raw artifacts from the current tree does not erase their contents from previously public commits. No implementation changes or new experiment runs are part of the publication cleanup.
