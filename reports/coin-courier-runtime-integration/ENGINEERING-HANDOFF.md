# Coin Courier: local ingestion and runtime integration engineering

This continues the original Experiments 1–18 cross-experiment E2E validation. It is not a new numbered experiment or a replacement benchmark. Historical chronology remains in [Run-006](../real-task-01/RUN-006.md) and the existing reports; this handoff documents new production corrections and real Runs 007–009 only. This report was finalized after the user stopped execution and authorized one implementation publication. Existing PR #2 and PR #3 are not modified.

## Baseline, controls and boundaries

Worktree branch: `fix/greenfield-worker-context-progress`, pre-publication HEAD `1e233845b3e9d26b10bb66238ec13a00f108356e` (reviewed PR #2 runtime base). Existing Worker feedback-retention and consecutive-check protections were present at the start and preserved. The original dirty checkout and historical evidence are separate.

The original prompt is byte-identical, SHA256 `848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256`. The new [test fixture](../../tests/fixtures/coin_courier_prompt.txt) preserves those bytes. Application code in the actual runs was written only by Mini Hivo.

Common launch procedure, with an empty, independently numbered workspace for each attempt:

```powershell
python -B mini.py --no-bootstrap --workspace <fresh-run-workspace> `
  --mode current_recursive --experiment-case-id real-task-01 `
  --verification-classification-policy field_scoped --model gemma4:e4b `
  --prompt-file <unchanged-prompt-copy>
```

`--prompt-file` is the existing CLI path through `main`, request ingestion, planning and execution, not direct Worker dispatch. Unlike historical interactive Run-006, these attempts use noninteractive file input: legitimate unanswered clarification/approval would block rather than receive invented answers. All three live clarification stages retained 16 requirements with no questions or conflicts.

Python 3.11.9, existing local Ollama `gemma4:e4b` (digest `dc35e8d9c6061baa6f0fa870975ab6932e2542b579b13ea0f199fa4bb7300c9c`), and existing Chromium 149.0.7827.55 were reused. Only process-level PATH, model-directory, API URL and temporary-directory settings were supplied. No packages, models or browsers were downloaded. Each actual run performed its own three host canaries and passed; unavailable GPU telemetry remained a warning. Available RAM/warm-model state differed and are recorded per attempt, so these are not a statistically controlled latency comparison.

Policy selections remain strict mission advice; `current` Worker progress, grounding, locator, verification environment/surface, receipt, integration-target and semantic-evidence policies; `field_scoped` verification classification. Worker budget 28, Falsifier budget 8, host-canary deadline 180 seconds, ordinary request timeout 600 seconds, Builder output limit 4096 tokens. Each run has an external 2400-second wall cap. This continuation uses at most three fresh real attempts, each restart justified by a confirmed, tested infrastructure correction.

Historical Run-006 used two withheld ingestion rewrites. These were not restored. The executable sources differ, so historical Run-006 is contextual evidence rather than an automatically matched Before arm for causal measurement of the Worker fix.

## Confirmed blockers and production corrections

### A. Object-word overlap was mistaken for opposite actions

`hivo/requirements.py::_conflict_evidence` treated overlap between positive and negative target words as a certain contradiction. That loses the action and condition: displaying a value is compatible with prohibiting its replacement, and testing collection is compatible with banning repeated awards without another collection. The unchanged full prompt produced three false conflicts before correction.

The new `_scoped_requirement_actions` extracts bounded action/object/negation/condition assertions. Predicate vocabulary remains open: Encrypt, Log, Compress and other arbitrary predicates are handled rather than omitted by a closed action list. Explicit preservation/removal opposition remains recognized. Differing explicit conditions do not establish a certain conflict merely from shared nouns. Negated clauses no longer count as affirmative broad resets in reset/persistence checks.

This is a bounded deterministic recognizer, not a proof of complete natural-language contradiction understanding. Uncovered paraphrases, coordinated prose and mixed conditions still require broader review. The verified claim is the full original task plus the specified regression cases; conflict detection was not disabled.

### B. Empty-workspace build wording lost to modification vocabulary

`hivo/project_understanding.py` recognized a few explicit greenfield phrases but not construction in an empty workspace. Requirements containing current/preserve/modify then selected `EXISTING_PROJECT` despite no implementation files.

The correction recognizes bounded build/create/develop/implement wording tied to an empty/blank location, while explicit existing-target intent prevents that new recognition from winning. Meaningful repository contents still take precedence. Tests include both historical false-greenfield counterexamples involving a report/cache in an empty directory alongside explicit existing-project work.

### C. Optional favicon noise contradicted the verifier's network exception

Run-007's actual Worker wrote a 14,914-byte `index.html`. `run_file` rendered it, with no page errors or required application-resource failure, but failed on a console 404. Independent HTTP observation identified `/favicon.ico`; the document declared no icon. The verifier already exempted this default icon from network errors but counted its matching browser console diagnostic.

The correction retains console source URLs, excludes only same-origin, default-path, no-query 404 diagnostics when the icon is implicit, and keeps excluded diagnostics in `ignored_console_errors`. Declared icons, DOM-declared resources and observed explicit requests prevent the exception. Real application console errors and ordinary missing resources remain failures. Core browser behavior/profile checks are unchanged.

A negative test found that the first correction would wrongly accept a script explicitly named `/favicon.ico`. That intermediate implementation was not used in a real attempt. Page request events alone were insufficient; DOM resource declarations were added, and the five-case real-browser suite passed before Run-008. Intermediate failed logs remain preserved. Coverage is specific, not exhaustive certification of every dynamic browser-loading pattern.

### D. Repair handoff substituted a parent summary for authority

Run-008 passed the basic page-load check, then correctly failed the required game check because `AGENT_GAME` was absent. Both Repairers passed context sufficiency but were rejected with `IMPACT_CONTRACT_INCOMPLETE`: “impact contract changed a stable goal anchor.”

`repair_task` reused the Builder's impact artifact but supplied a different parent anchor when the original task/RUN had none: its `parent_goal` argument came from the caller's `parent_summary`. The execution summary is descriptive context, not new goal authority.

The production correction removes that summary fallback and uses the same task/RUN parent fields as the Builder and candidate construction. No validator, permission, target scope, contract hash or acceptance criterion was relaxed. The regression traverses a real greenfield Builder and actual `repair_task` with production gates/file tools; scripted provider responses are confined to this regression. It simulates a defective temporary artifact and restores the originally required content through a real authorized edit. Explicit parent authority and genuine anchor drift are separately tested.

## Regression evidence

Commands use `python -B -m unittest discover -s tests -p <filename> -v`, unless noted. Exact argv, counts and raw output are preserved in the local validation ledger and logs. Intermediate failures are not passing evidence.

| New suite | Before | Final result | Mechanism evidence |
|---|---|---|---|
| `test_ingestion_integration.py` | Original nine methods produced 13 failure/subtest records; full prompt separately produced three conflicts and wrong mode | 10 passed (full original prompt test added) | Compatible scopes, arbitrary predicates, real contradictions, reset negation, explicit existing intent, populated-repository precedence |
| `test_browser_implicit_favicon.py` | Original four cases: one failure on healthy implicit-icon page; expanded negative exposed an explicit-resource hole in intermediate correction | 5 passed with an existing browser explicitly configured | Actual verifier/browser/server route; explicit icon/resource and application-error negatives |
| `test_repair_impact_anchor.py` | Three methods, one failed in the goal-consistent pre-fix reproduction | 3 passed | Real greenfield Builder → Repairer authorization and file edit; explicit parent and genuine-drift negatives |

Other passing selections: greenfield Worker regressions 9; context gate 9; impact 27; execution contracts 36; project understanding 32; Experiment 3 progress 4; Experiment 4 grounding 9; Experiment 6 environment 9; Experiment 7 surfaces 5. The existing clarification suite passed 50 under an explicitly provider-disabled deterministic harness (`structured_model_call` raises `ProviderError` where a test would otherwise reach live extraction). Those 50 do not demonstrate provider-backed extraction behavior.

Together these are **208 distinct passing selected tests**, not a full-suite claim and not multiple intermediate runs added together. The ordinary verification-policy suite ran eight methods with two errors for a missing ignored historical prompt fixture; the unchanged detached baseline produces the same two errors. Two older browser-probe tests skipped because they launch Playwright's unavailable default managed-browser revision; the five new real-browser tests explicitly reused the installed executable. These gaps are not described as passing tests.

The original Worker implementation and context/impact/path guards were compared by AST with the start-of-continuation snapshot. They remain unchanged. Syntax and final diff checks are recorded in the final local review. No game code was manually created or repaired by the investigator.

## Actual attempts and final interruption

| Attempt | New source relative to preceding state | Actual progression and outcome |
|---|---|---|
| Run-006 (historical reference) | Withheld ingestion rewrites; no new implementation from this PR | Two Workers exhausted their budgets; no application files. The [existing detailed report](../real-task-01/RUN-006.md) remains the source of historical chronology. |
| Run-007 | New ingestion corrections, preserved Worker fixes | All canaries; live clarification/specification/planning/decomposition/Mission Compiler; Builder list → sufficient context → accepted impact → `write_file index.html` → browser check; also wrote placeholder `game.js`. Interrupted for confirmed implicit-favicon false failure. Both files remained on disk, but no normal Worker/root verdict or transaction commit is claimed. |
| Run-008 | Tested implicit-favicon correction | Same ingestion/planning route; Builder created the byte-identical HTML, passed basic `run_file`, finished after four tools; Falsifier dispatched. Required game verification failed missing bridge. Two Repairers were denied impact by parent-anchor drift. Pipeline rolled back HTML and attempted an alternate strategy; interrupted for the reproduced handoff defect. Final application workspace had no application files. |
| Run-009 | Tested Repairer parent-anchor correction | Real planning and Builder execution; two writes and one edit, Builder and Falsifier finished. Basic browser checks passed; required game gate failed. Repairer impact authorization succeeded but no Repairer mutation was recorded before the user-requested stop. Two candidate files remain; no transaction commit, rollback or normal root verdict. |

Run-007 and Run-008 were deliberately interrupted for identified code defects. Exit code 1 after process-tree termination is not a natural root verdict. Their original workspaces, native traces, SQLite data, screenshots, source snapshots and file observations are preserved. Run-008's observer archive retains the generated HTML despite the pipeline's legitimate rollback; archival retention is not application transaction acceptance.

## Independent observations of the preserved candidate

The HTML hash was `205c14071f143efe3f314b08708ee6cd0e0fa69f657595c8e19f8d59ababbd93` in Runs 007 and 008. Direct-file testing of the preserved Run-007 candidate, with external requests blocked, observed a title/start/canvas/score interface, real Arrow/WASD movement, arena clamping, two physical collections awarding exactly +10 each, and no repeated idle scoring. No page errors occurred.

That partial candidate lacked `AGENT_GAME`, visible touch controls and a usable mobile canvas layout: at 390×844 the canvas was 800 pixels wide with left coordinate −205. Full obstacle/game-over/win/restart/persistence acceptance was not established. It was an in-progress leaf artifact, not a delivered application. Source hashes before and after independent testing match. No state injection or adapter-only shortcut was used to claim physical gameplay.

## Mechanism interpretation

| Mechanism | Runtime interpretation supported so far |
|---|---|
| Ingestion/classification | New deterministic corrections tested; actual original task passes live ingestion with requirements retained. |
| Planning, decomposition, Mission Compiler | Actual configured model calls and transitions precede real Workers. Their presence does not prove a complete or optimal plan. |
| Context Sufficiency | Actual sufficient decisions precede implementation. Meaningful insufficient-context acquisition and Experiment 18A evidence-kind completion are not thereby verified. |
| Impact Authorization | Builder acceptance is observed; Run-008 Repairer anchor rejection was corrected with regression coverage and Run-009 records accepted Repairer impact authorization. Authorization is distinct from post-verification impact comparison/commit. |
| Worker Progress | Preserved feedback correction permits real implementation beyond repeated checks. The narrow fallback exists, but threshold termination must not be claimed exercised merely because no loop occurred. |
| Optional progress-constrained / MutationGrounding wrappers | Policies remain `current`; ordinary greenfield missions have null execution-contract IDs. Contract-backed wrappers are not demonstrated active. No contract was injected to change that. |
| Behavioral Verification | Basic web load can pass while the required game gate fails. Missing bridge remains a legitimate failure; clean console output is not application acceptance. |
| Independent application acceptance | Partial gameplay observations above; no complete Coin Courier acceptance claim. |

## Local-only evidence locations

Evidence root: `<implementation-parent>/ingestion-integration-20261021/` (LOCAL-ONLY EVIDENCE; raw logs/databases are not proposed repository documents).

- `baseline.json`, `before/`, `protected-mechanisms.json`: initial branch/status/source and preservation checks.
- `validation-ledger.json` and parent-directory `*-results.json` / per-suite logs: exact test commands, intermediate failures and final results; `logs/clarification-offline.log` for the explicit offline harness.
- `runs/run-00N/preparation/configuration.json`, `source.diff`, `source-snapshot/`: exact CLI, model catalog/digest, source bytes/hashes, environment, budget and original prompt/criteria copies.
- `runs/run-00N/logs/terminal-transcript.txt`: complete child stdout/stderr; `workspace/.agent_runs/*.jsonl`: native orchestration evidence; `workspace/.hivo/memory.sqlite3`: native tool events/artifact state.
- `logs/file-observations.jsonl` and `observed-files/<sha256>`: time-stamped read-only observations of actual generated content, including files later rolled back.
- `evidence-summary.json`, `execution-result.json`, `interruption-reason.txt` where applicable: stage/tool/authorization/outcome and interruption provenance.
- Run-007 `acceptance/`: HTTP favicon diagnosis, physical partial-gameplay results and start/play/mobile screenshots. Native browser screenshots remain under each workspace's `.agent_evidence/`.

Original Runs 001–006 are not rewritten by this package. Historical prompt/evidence and the original dirty checkout remain separate; the final preservation check records their hashes again. Final Run-009 findings and restart instructions follow. No further execution or tests were run during publication.


## Final Run-009 evidence: confirmed versus unverified

Native run `20261021T155855-9d43bc5a` ended by user-requested process-tree termination after 1552.266 seconds (exit 1, external wall limit not reached). This is an interruption, not a normal terminal failure or success. The saved runner result and read-only SQLite extraction contain 171 native events and 23 tool events.

- Native lines 7?8: no conflicts/questions; 16 source requirements. Line 33: compiled mission, null execution-contract ID. Line 36: first Worker started after six model calls.
- Line 46: Builder impact accepted. SQLite events 1?9: list, one sufficient-context decision, two writes, three `run_file` calls, one read and one edit of the placeholder script. Line 85: Builder finished `done`, nine tools, context and impact authorization true.
- SQLite events 10?13: Falsifier listed/read both files and ran the page. Native line 108: Falsifier finished `done`. A finished Falsifier and a basic load pass are not behavioral certification.
- Line 111: required browser route failed. The basic snapshots report `gameBridge: null`; the game bridge requirement remains unsatisfied. This is not suppressed by the favicon correction.
- Line 121: Repairer impact accepted on the same impact-contract ID/hash as the Builder. The parent-anchor fix therefore has live authorization corroboration, beyond its deterministic authorized-edit regression.
- Repairer events 14?23: two context checks, one listing, five reads and two basic page runs; **no Repairer write/edit**. Event 19 rejected three unsupported `needed_evidence` kinds and returned `insufficient` / `PREPARING_CONTEXT`, mutation disallowed. The original rejected kind strings are not preserved in this event; it corroborates the known Experiment 18A schema/whitelist boundary without establishing those strings or proving the cause of earlier Worker behavior. No follow-up repair was attempted during handoff.

Persisted candidates at interruption:

| File | SHA256 | Meaning |
|---|---|---|
| `index.html` | `205c14071f143efe3f314b08708ee6cd0e0fa69f657595c8e19f8d59ababbd93` | Same partial HTML as earlier attempts; 14,914 bytes |
| `game.js` | `d4bcd9abe74db234c055d29580bb891cf0f04d4fc52a02ee62fb3134f196c3f3` | Placeholder comment and console log, not complete game implementation |

There are **zero transaction commits and zero transaction rollbacks** in this attempt. Persisted provisional files are not accepted transaction outputs. The real Worker milestone was reached: sufficient context, accepted impact, implementation tools and disk-retained writes. **Full Coin Courier completion and final application acceptance were not demonstrated.** No new independent Run-009 application acceptance session was performed. Prior partial Run-007 observations do not certify Run-009 or the full requirements.

## Exact publication scope and dependency

This implementation is stacked on PR #2's unmerged fork branch `fix/local-runtime-startup`, at the pre-publication HEAD above. Team main does not contain that branch and the authenticated account has no team write permission. The clean review base is therefore **the fork's `fix/local-runtime-startup`**, not team main. The eventual team integration must wait for PR #2 and then move/recreate the reviewed implementation diff under an explicitly agreed workflow; do not merge this stack or retarget it to team main while that would duplicate PR #2.

Related work: [PR #2](https://github.com/kareem232003/mini_hivo/pull/2) owns historical runtime fixes/evidence; [PR #3](https://github.com/kareem232003/mini_hivo/pull/3) owns cross-experiment research. Neither is changed here. Historical withheld ingestion rewrites are not included: the new implementations have dedicated counterexample coverage, with the bounded-recognizer limitations above.

Intended files (no generated application or raw evidence):

- [`hivo/requirements.py`](../../hivo/requirements.py): action/scope/negation conflict recognition.
- [`hivo/project_understanding.py`](../../hivo/project_understanding.py): empty-workspace construction classification.
- [`mini.py`](../../mini.py): retained context feedback, bounded repeated-check failure, implicit favicon diagnostic handling, stable Repairer parent authority.
- [`test_greenfield_context_progress.py`](../../tests/test_greenfield_context_progress.py): nine Worker-route/safety regressions.
- [`test_ingestion_integration.py`](../../tests/test_ingestion_integration.py): ten ingestion/classification tests.
- [`test_browser_implicit_favicon.py`](../../tests/test_browser_implicit_favicon.py): five real-browser positive/negative cases.
- [`test_repair_impact_anchor.py`](../../tests/test_repair_impact_anchor.py): three parent-authority/repair tests.
- [`coin_courier_prompt.txt`](../../tests/fixtures/coin_courier_prompt.txt): exact prompt fixture, not generated game code. A fixture-local [`.gitattributes`](../../tests/fixtures/.gitattributes) disables newline conversion so Windows checkouts retain its asserted byte hash; this publication safeguard changes no runtime or test logic.
- [Worker-fix checkpoint](../worker-context-progress/README.md): detailed before/after mechanism evidence and recovery-suite limitations.
- This handoff: subsequent fixes, existing test results, actual run outcomes and restart boundaries.

## Resume later: explicit next-session procedure

1. Review the stacked diff and PR #2 dependency before integrating anything. Preserve all original run directories and snapshots; never restart into Runs 007?009.
2. Inspect Run-009 native line 111 / required-game receipt and SQLite event 19 with the Experiment 18 mechanism owner. Prioritize evidence-kind schema alignment and recovery feedback. Do not assume the parent-anchor fix alone makes Repairers productive.
3. Review the required game bridge/behavior contract against the assigned leaf and full mission. Missing bridge remains a valid current gate failure; do not disable it or manually patch the application. Investigate why Repairer basic `run_file` passes did not resolve the required game failure.
4. Before any future run, explicitly authorize a new bounded attempt, verify source revision/diff and model digest, and use a fresh numbered workspace with the unchanged prompt/criteria. Reuse the recorded runner procedure only after reviewing it; record full model-visible gate feedback, tool arguments, authorization, file hashes and terminal reason. Do not blindly continue the interrupted process or treat its provisional files as an accepted starting baseline.
5. Keep `current` policies and null greenfield contracts explicit unless a separately reviewed authority design changes them. WorkerProgress/MutationGrounding wrapper activation is still unverified here. Any future complete artifact needs independent keyboard/scoring/game-over/restart/persistence/mobile acceptance, not only a bridge or basic page-load pass.

No tests, model calls, browser sessions or new attempts were started for this final publication. Existing tests are reported, not rerun. Raw logs, databases, generated games, model caches and local paths are excluded from the commit.
