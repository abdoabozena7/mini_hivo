# Literal greenfield lifecycle verification evidence

These are curated publication derivatives of preserved local experiment records, prepared on 21 October 2026. They are not new experiment executions or a replacement for the private originals. Local paths are replaced with `<LOCAL_PATH>`; detailed host inventory fields are omitted. Test names, outcomes, counts, requirement IDs and source hashes are retained. Original-to-derivative SHA-256 pairs and transformations are listed in [manifest.json](manifest.json).

Embedded source/contract hashes identify original records. A sanitized JSON file is not byte-identical to its original, must not be checked against the original whole-file digest, and must not be loaded as an authorization receipt. This folder intentionally contains no host-preflight markers, raw experiment markers, SQLite databases, historical update dump or full machine tracebacks.

## Functional behavior

The request was `Create a text file named welcone containing exactly welcome.` The original reproduction showed a candidate created, no context decision, zero impact validations/authorizations and no tool calls. This established a context lifecycle stop with misleading final diagnostics, not a rejected impact validator or proof of incorrect Stage 3 skipping.

The change gives recognized single literal text-file requests a controller-bound path, source requirement obligations and expected UTF-8 digest. An absent context decision gets at most one retry. Accepted scope is enforced before writes. Required literal verification binds native readback to the tool, path, accepted contract and expected/observed digests; independent post-state comparison rejects wrong bytes even when supplied a claimed pass.

The [fresh lifecycle log](fresh/lifecycle.log) records 17 passing tests. The positive leaf test scripts model decisions but uses real context/impact gates, writes, Builder/Falsifier readback, applicability, aggregation and commit. It asserts exact output bytes. Negative cases cover wrong bytes, missing/tampered contracts, unsafe/out-of-scope paths and forged/generic/foreign proofs. Other assertions cover requirement IDs, conservative filename mapping, candidate reuse, and preservation of existing-project plan approval. See [test source](../../tests/test_greenfield_impact_lifecycle.py).

The [historical final controlled replay](historical/controlled-final-result.json) records seven scripted provider responses, zero real model calls, status done, `root_verified=true`, three source requirement IDs and matching final bytes. All four production source pins still match the audited code. This proves controller behavior for the scripted request, not live-model reliability.

## Additional regression checks

The six additional fresh suites passed: impact 27, context 9, authority 23, understanding 32, experiment-focused 122, adaptive 90. [verification-summary.json](verification-summary.json) links each saved log. These checks are separate from the direct functional oracle; they exercise pre-existing behavior as well as changed integration. They are not unique coverage totals or proof of causal improvement across every suite.

Fresh here means the preceding workspace audit on 21 October, at source commit `00c163f37070dede2e6208f8fb029e6da5cda4b2`. Publication preparation inspected those logs without rerunning tests. The first audit attempt encountered temporary-directory permissions; its rerun using workspace-local temporary storage passed. That first error was environmental and is not counted as successful behavioral verification.

## Reproduction

From the repository root, in a Python environment satisfying `requirements.txt`:

```powershell
New-Item -ItemType Directory -Force .verification-temp | Out-Null
$env:TEMP = Join-Path (Get-Location) '.verification-temp'
$env:TMP = $env:TEMP
python -B -X utf8 -m unittest discover -s tests -p test_greenfield_impact_lifecycle.py -v
```

Repeat discovery with `test_pre_mutation_impact.py`, `test_context_sufficiency_gate.py`, `test_authority*.py`, `test_project_understanding.py`, `test_experiment*.py` and `test_adaptive_architecture.py` for the additional suites. The temporary directory and runtime state should remain untracked. This command creates new test state; it does not regenerate the archived results.

## Failures and limits

- Historical broad regression: [1,376 executed, 24 failure records, 18 errors, 10 skips](historical/full-regression-result.json). The [comparison](historical/regression-comparison.json) found the same 42 failure/error identities as the earlier Phase 2 baseline, which ran 1,361 tests. This comparison predates final routing refinements. No final-source broad-suite pass is claimed. Missing historical fixtures and browser availability remain unresolved; setup failures prevented some discovered cases from executing. Do not infer a pass count by subtracting failure records.
- A known requirement-compaction test was excluded because it calls a live model. Full discovery should not be treated as offline verification without addressing that boundary.
- [Live results](historical/live-results-summary.json): final auto task failed at Specifier timeout despite process exit 0; baseline was blocked by memory preflight. An earlier diagnostic was interrupted. Completed live-model implementation remains unverified.
- The [Phase 2 Node pilot](historical/phase2-pilot-audit.json) failed with zero Builder/tool calls despite process exit 0. Its first-blocker classifier placed the issue at Child verification, while the historical trace/report located the timeout earlier at Mission Compiler. No Worker behavioral success is inferred.
- Exact historical unmapped requirement identity is absent. Same-name mapping and ID propagation are directly tested; general mapping correctness is not claimed.
- This supports recognized literal text-file requests, not arbitrary greenfield projects. General impact planning and mutation grounding predate this patch.
- Ignored raw event databases are not included; this package is a selected exported evidence set, not the complete raw archive. Experiment 17 was a pre-existing partial classification check and is not current update evidence.

## Publication byte policy

All files in this package use canonical LF line endings, enforced by the scoped Git attribute `text eol=lf`. Eight sanitized logs were converted from CRLF to LF before publication; their outcomes and text are unchanged. `original_sha256` hashes untouched local source bytes. `publication_sha256` hashes sanitized canonical-LF bytes and is verified against the actual staged Git blob. Original evidence line endings were not changed.
