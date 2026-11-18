# Fixes, attempted changes, and mechanism validation

[Overview](README.md) · [Run-006](RUN-006.md) · [Evidence index](EVIDENCE-INDEX.md)

## Publication boundary and source identity

The existing [PR #2](https://github.com/kareem232003/mini_hivo/pull/2) contains two reviewed code-fix commits, preserved unchanged by the documentation update:

| Commit | Scope |
|---|---|
| `6f6bbc273dc194811c82170e633896b1c67e4e56` | Python 3.11 compatibility plus actual conflict-ID mechanism assertion |
| `922270b46d661e7e577bbfb7d48d195d3b5e80a7` | Finite host/provider deadlines and regression coverage |

Their parent/base is `f842fb8fb6e63e3064891d26ee0b24981e55c847`. Historical experiments ran from that base with per-attempt uncommitted deltas, not from these later publication commits. The documentation commit adds reports only. No product source, Worker policy or application code is modified by this documentation update.

The six code/test files already in PR #2 are [hivo/reentry.py](../../hivo/reentry.py), [hivo/host_preflight.py](../../hivo/host_preflight.py), [mini.py](../../mini.py), [tests/test_authority_drift.py](../../tests/test_authority_drift.py), [tests/test_host_preflight.py](../../tests/test_host_preflight.py), and [tests/test_model_transport_timeout.py](../../tests/test_model_transport_timeout.py). Neither withheld ingestion source rewrite nor its experimental new regression file is included.

## Published fix 1: Python 3.11 startup compatibility

**Original defect:** Run-001 failed before `main()` at `hivo/reentry.py:1189`, with `SyntaxError: unterminated string literal`. A normal double-quoted f-string used a multiline dictionary expression and same-quoted keys; Python 3.11 could not parse it, although Python 3.12's expanded grammar can.

**Intended behavior:** Construct deterministic authority/implementation drift IDs without making model calls or changing semantic classification.

**Implementation:** Lines 1189/1192 use `"REENTRY-CONFLICT-" + canonical_hash({...})[:16]`. Dictionary keys/values, canonical hash, prefix, truncation, append flow and deduplication remain unchanged.

**Functional verification:** The added authority-drift test calls `classify_authority_repository_drift` with a real structured contradictory relation, obtains its actual conflict, independently constructs the expected canonical digest using that conflict's stable key, and asserts exact ID equality plus `model_calls == 0`. This exercises the mechanism rather than only compiling text. Existing suite cases cover confirmed contradiction/agreement, insufficient evidence and deduplication.

**Additional coverage:** Verified-state reentry tests check related authority/reentry behavior. Historical preparation compiled 196 Python files, ran six expression equivalence cases and ten existing authority tests. The later published assertion makes the final authority suite **11** tests. Historical and final counts are deliberately kept separate.

**Limitations:** Syntax compatibility and selected authority behavior do not validate all Python versions, the entire agent pipeline, or application generation. This does not change requirement-conflict ingestion; similarly named conflicts in those mechanisms are different issues.

## Published fix 2: host canary deadline 180 seconds

**Original defect:** Run-002's first canary exhausted its 30-second transport deadline; 0/3 completed in 30.595 seconds. Catalog readiness did not guarantee a timely inference response.

**Implementation:** `hivo/host_preflight.py:33`, `CANARY_TIMEOUT_SECONDS = 30.0` → `180.0`. No existing environment/CLI override was found. No check was disabled or skipped.

**Preserved behavior:** Three exact-response canaries; original prompt, model and small output/context budget; temperature zero; cooldowns after each call; provider failure, unexpected response, resource monitoring and startup failure boundaries. Client timeout still does not prove provider-side cancellation.

**Functional tests:** The transport-facing assertion verifies timeout 180.0 actually reaches the request. A new successful preflight test verifies three calls, each with 180.0, three completed canaries and cooldowns `[2.0, 2.0, 2.0]`. The original negative cases continue protecting failure gates. Final suite: **21 passed**.

**Live observation:** Run-003 passed all three real canaries in 49.877 seconds. This is evidence that this attempt cleared the earlier startup boundary, not a benchmark or proof that every request needs that much time. Historical initial preflight suite count was 20; the added publication assertion raised it to 21.

**Limitations:** The deadline remains a module constant and is not new user configuration. Worst-case startup waiting is longer. The timeout-label mismatch discussed in [Run-002](RUN-002.md) was not changed.

## Published fix 3: normal provider deadline 600 seconds

**Original defect:** Run-005 reached Specifier but its non-streaming request hit the separate original 120-second deadline. API/model readiness persisted afterward.

**Implementation:** `mini.py:660`, `OLLAMA_TIMEOUT_SECONDS = 120` → `600`, used by ordinary Ollama requests. It remains a finite per-request limit; no model, context/output budget, sampling, retries, Worker policy, safety gate or verification logic changed.

**Functional tests:** Two tests invoke `ask_ollama` with controlled transport. They verify one request receives timeout 600, selected model `gemma4:e4b`, Specifier `num_ctx=4096`, `num_predict=1536`, and `stream=False`, `think=False`. A mocked `HttpTransportError('timed out')` still raises `ProviderError`, records one timeout failure, makes no unsolicited retry when retries are explicitly zero, and leaves CPU fallback disabled.

**Additional coverage:** Three context-policy tests and two selected existing timeout/crash-retry tests passed. They protect role budgets and established error/retry behavior; they do not introduce a new retry policy. Run-006 completed specification with this deadline, while also using the later-withheld ingestion rewrites.

**Limitations:** Controlled transport tests do not measure hardware performance or guarantee live model reliability. The reason live generation exceeded 120 seconds was not isolated. Multiple requests can still make total execution long. A client timeout cannot establish server-side cancellation.

## Withheld attempt 1: scoped requirement-conflict rewrite

**Defect investigated:** Run-003's detector treated a prohibition on lowering a stored value as conflicting with displaying that value. Original positive/negative target token overlap lost predicate scope and negation boundaries.

**Attempted implementation:** Local `hivo/requirements.py` compared bounded action/object/polarity/condition assertions, preserved exclusion-list scope, filtered prohibited resets and distinguished control labels/adjectives from actions. Production logic did not hard-code Coin Courier or `best score`.

**Historical tests:** The new local `tests/test_requirement_conflict_scope.py` grew from five to nine test methods. Initial reproduction reported 30 failed assertions/subtests; an expanded seven-method revision still had one failure; final nine methods plus 50 clarification and 32 project-understanding tests passed (91). Full original prompt yielded zero deterministic conflicts at final launch readiness.

**Broader review failure:** The proposed bounded action vocabulary missed predicates outside its recognized set:

| Requirements | Original conflicts | Proposed conflicts | Review result |
|---|---:|---:|---|
| `Encrypt stored records.` / `Do not encrypt stored records.` | 1 | 0 | Regression |
| `Log authentication attempts.` / `Do not log authentication attempts.` | 1 | 0 | Regression |
| `Compress archived records.` / `Never compress archived records.` | 1 | 0 | Regression |
| `Display account details.` / `Do not display account details.` | 1 | 1 | Selected protected case retained |

**Publication status: WITHHELD.** The narrow passing tests were real but inadequate to establish a safe general fix. Neither rewrite nor experimental test is included in PR #2. Local snapshots and `conflict-review.json` preserve it for redesign. The original ingestion false positive remains unresolved in published source.

## Withheld attempt 2: explicit-greenfield recognition rewrite

**Defect investigated:** Run-004 selected `EXISTING_PROJECT` for a build request in an empty workspace. Existing greenfield phrases did not cover that wording; modification words inside new-game requirements won classification.

**Attempted implementation:** Local `hivo/project_understanding.py` recognized a build/create/develop/implement phrase within a bounded sentence span of empty/blank workspace/directory/folder. Tests preserved meaningful-tree precedence and selected explicit existing-target cases.

**Historical tests:** Local `tests/test_greenfield_request_scope.py`: four methods, three failures before; four passed after. With 32 project-understanding, nine scope and 50 clarification tests, final local set was 95 passed; 198 Python files compiled.

**Broader review failure:** Both following empty-location phrases were incidental to explicit existing-project work, yet the rewrite selected `NEW_PROJECT`:

```text
Create a report in an empty directory. Fix the existing SettingsService.
Create a cache in an empty folder for the existing application. Modify the current renderer.
```

The original classifier and review expectation were `EXISTING_PROJECT`. A positive editor-in-empty-workspace case did improve, but did not offset these regressions.

**Publication status: WITHHELD.** Neither source rewrite nor experimental test is in PR #2. A safer correction needs mixed-intent counterexamples and explicit precedence analysis, not another task-specific phrase exception.

## Unresolved Worker progress issue

Run-006's two completed Workers exhausted 28-step budgets with 55 context checks and one listing, despite final sufficient context and mutation/impact authorization. No application mutation or application verification occurred. The [detailed trace analysis](RUN-006.md) documents the observed lifecycle and hypothesis boundary. No fix is claimed, and no `progress_constrained` policy was substituted. This issue is not covered by claiming the runtime suites passed.

## Exact final published-runtime validation

The following seven commands were actually executed during PR preparation on the final runtime checkout, using Python **3.11.9**, without live inference. Commands below normalize the machine-specific Python executable to `python`; arguments are retained. Recorded originals are in the separate local PR-workflow directory under `validation/runtime-final/results.json` and `suite-1.log` through `suite-7.log`.

```text
python -B -m unittest discover -s tests -p test_authority_drift.py -v
python -B -m unittest discover -s tests -p test_verified_state_reentry.py -v
python -B -m unittest discover -s tests -p test_model_transport_timeout.py -v
python -B -m unittest discover -s tests -p test_host_preflight.py -v
python -B -m unittest discover -s tests -p test_context_policy.py -v
python -B -m unittest discover -s tests -p test_mini.py -k timeout_retries_without_misclassifying_it_as_empty_response -v
python -B -m unittest discover -s tests -p test_mini.py -k transient_ollama_worker_crash_retries_the_same_gemma_model -v
```

| Suite, in command order | Tests | Recorded result |
|---|---:|---|
| Authority drift | 11 | OK, exit 0 |
| Verified-state reentry | 18 | OK, exit 0 |
| Model transport timeout | 2 | OK, exit 0 |
| Host preflight | 21 | OK, exit 0 |
| Context policy | 3 | OK, exit 0 |
| Timeout classification/retry selection | 1 | OK, exit 0 |
| Transient crash/same-model retry selection | 1 | OK, exit 0 |
| **Total** | **57** | **All passed** |

In-memory syntax compilation passed for **197 Python files** on this publication revision:

```text
python -B -c "from pathlib import Path; files=[p for d in (Path('.'),Path('hivo'),Path('tests'),Path('scripts')) for p in d.glob('*.py')]; [compile(p.read_bytes(),str(p),'exec') for p in files]; print(len(files))"
```

`git diff --check` and the base-to-head file/whitespace audit passed during that validation. These are the preserved code-fix results; the documentation update does not relabel them as a newly executed live experiment. Mock output such as preflight PASS or agent completion is not another Coin Courier run. No application capability pass is inferred.

## What these results collectively establish

The published changes restore parsing on the observed Python version and extend two bounded transport waits while preserving tested payloads and error gates. Independent unit assertions are the validation oracle for these mechanisms. Narrow historical ingestion tests were insufficient for publication, and that negative review result is part of the handoff. Nothing here establishes a working Coin Courier game, completed Worker progress, exercised Mutation Grounding, or successful Behavioral Verification.
