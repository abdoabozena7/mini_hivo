# Experiment 21 — Rodina Level 1 integration and literal parser correction

**8 November 2026. Status: controlled functional and regression checks passed for this integration.** The whole project still has pre-existing failing tests. No fresh live-model completion is claimed.

## Research question and baseline

Can Rodina's PR #6 (including #5) work alongside the Tasneem changes tested in Experiment 20, while correctly interpreting and verifying compact literal requests such as `Create a text file named note.txt containing exactly:Hello`?

This is a new experiment on `codex/experiment21-rodina`, starting from Experiment 20 commit `003cdd2dc1e6285112e3aafa33307476539e07b9`. The implementation checkpoint is `cc8706ef871c933ffe5ee55a4b9768ac7932112c`. Experiment 20's branch and original report remain intact. The existing managed checkout was reused for the new branch, so its directory still contains `experiment20-tasneem`.

The requested experiment format takes precedence over allocating a contributor-specific `R_UPDATE` number. Imported update documents are preserved as historical contributor evidence. [Protocol](PROTOCOL.md) records the planned comparisons; [results](experiment21-results.json) records the measured outcomes.

## Fresh PR check

The public GitHub API was checked on 8 November 2026. There are eleven open PRs (#2–#12), plus the previously merged #1. PRs #2–#8 retain the heads from the earlier review. The four new PRs are all Tasneem's:

| PR | Current contribution | Current head |
|---|---|---|
| [#9](https://github.com/kareem232003/mini_hivo/pull/9) | Verification integrity: code, tests, reports and curated live evidence; updated 7 November | `af5ed5dded24f2ae8f3bdc10e60eb9362efd0563` |
| [#10](https://github.com/kareem232003/mini_hivo/pull/10) | Child-scoped verification: code, tests, reports and curated live evidence; updated 7 November | `156c616a3a678b803d3e695dcb8386dae040960d` |
| [#11](https://github.com/kareem232003/mini_hivo/pull/11) | Four documentation files recounting earlier greenfield feedback/progress fixes | `2ef3b550ebce33b29656c1c0303b003c68bc8dc4` |
| [#12](https://github.com/kareem232003/mini_hivo/pull/12) | Four documentation files recounting earlier evidence-schema/feedback fixes | `0572f9360698ec42473ad037eb798c8e6966300e` |

This check inspected metadata, bodies and changed filenames; it is not a fresh full code review of #9–#12. They were not integrated. PR #10 uses `reports/experiment20/experiment20-report.md` and the corresponding results filename for a different experiment, so a future integration must reconcile that naming collision explicitly. It must not overwrite the local Tasneem integration history.

[PR snapshot](pr-status-2026-11-08.json) retains exact identities. Rodina's [#5](https://github.com/kareem232003/mini_hivo/pull/5) remains at `cca388daa3537030abdb7b6cf175d847f23b99ec`; [#6](https://github.com/kareem232003/mini_hivo/pull/6) remains at `9957271c8e66d10bdfa5b408c74d26fcd7b78be2`. Git ancestry confirms #6 contains #5. Her draft #8 is unchanged and outside this experiment.

## Implemented updates

- **PR #5:** source-bound single literal-file requirements, precise mutation paths and expected file digest, native exact-byte readback, a literal-artifact verification route, independent post-state checks, and bounded context-start handling. Existing-project and invalid-authority restrictions remain.
- **PR #6:** explicit colon-delimited multiword input, recovery guidance from refused shell commands to native `run_file`, bounded refusal retries, and separation of literal readback from executable-test evidence.
- **Combined Worker state:** the sole textual merge conflict was at variable initialization in `mini.py`. Both Tasneem's context-retention/progress variables and Rodina's `context_start_retries` are retained. No existing Tasneem or cloud-model behavior was intentionally removed.
- **Parser correction:** evaluate the explicit `exactly:` grammar before generic token parsing. Empty/malformed colon syntax cannot fall through and become literal text. Reject CR/LF input in this single-line grammar. Explicit colon payload punctuation is retained; quoted payload spaces and explicitly quoted empty contents are supported. Ordinary existing token syntax remains available.
- **Local workflow adaptation:** imported `AGENTS.md` no longer assumes Rodina's local checkout name or fork remotes. Publication destinations must be verified from the current task.
- **Reproduction tools:** add Experiment 21 runners, regression tests and machine-readable comparison. Extend the existing Level 1 replay with optional independent request/expected-text inputs; defaults preserve Rodina's original replay.

## Original failure and root cause

The generic token branch ran first. Because its `exactly` modifier required trailing whitespace and its unquoted token admitted a colon, `exactly:Hello` was accepted as the entire file content. That also bound the expected digest to the wrong bytes: the native verifier could accept `exactly:Hello` and reject the requested `Hello`. A compact trailing period could also be lost through the generic sentence-punctuation handling.

Before correction, the new seven-test regression module recorded **12 failure records and two passing tests** (several failures are subtests). This included the compact payload, incorrect-payload rejection, punctuation, empty unquoted payload and a newline immediately after the colon. After correction, **all seven tests passed**. The tests use manually specified expected strings/digests rather than deriving their oracle from the parser.

## Functional evidence

Only provider replies are scripted. Contract extraction, impact authorization, actual file writes, native readback, Falsifier readback, verification aggregation and root completion use real application code. The replay's original shell-refusal steps are retained. Each run writes into a fresh output directory and retains its actual file and result JSON.

| Request suffix after `containing` | Expected UTF-8 file bytes | Actual hex | Result |
|---|---|---|---|
| `exactly:Hello Mini Hivo` | `Hello Mini Hivo` | `48656c6c6f204d696e69204869766f` | Exact bytes, Falsifier native readback, root verified |
| `exactly:Hello` | `Hello` | `48656c6c6f` | Exact bytes, Falsifier native readback, root verified |
| `exactly:Hello.` | `Hello.` | `48656c6c6f2e` | Exact bytes, Falsifier native readback, root verified |

All use the filename `test_level_1.txt`, with no newline appended. Independent parser/functional tests additionally verify a quoted empty file, quoted whitespace, Unicode, a URL with colons, ordinary syntax, and malformed input rejection. The old incorrect `exactly:Hello` output is rejected by both native proof and the independent post-state check even when verification is claimed successful. Existing tests cover unauthorized paths, forged or missing authority/proof, incorrect bytes, shell restrictions and bounded nonprogress.

These controlled results establish controller behavior, not live-model reliability or completion of arbitrary tasks.

## Regression results and compatibility

| Run | Tests run | Passed tests | Failure records | Error records | Skips |
|---|---:|---:|---:|---:|---:|
| Fresh Experiment 20 baseline | 1,405 | 1,365 | 24 | 18 | 16 |
| Combined Experiment 21 | 1,439 | 1,399 | 24 | 18 | 16 |
| Focused combined checks | 167 | 162 | 0 | 0 | 5 |
| Focused checks with installed Edge | 167 | 167 | 0 | 0 | 0 |

**No new failure/error IDs, no formerly passing test lost, and 34 additional passing tests.** The same 42 baseline failure/error records remain. Counts are not additive because unittest includes failing subtests and class setup errors. Focused/full runs overlap and must not be summed. The five opt-in favicon tests pass with Edge.

The baseline and treatment used Python 3.12.14, rich 14.3.4, prompt_toolkit 3.0.53 and Playwright 1.63.0 on Windows 11. The one historical prompt test known to potentially invoke a provider was explicitly skipped in both arms. A socket guard blocked external connections and local Ollama port 11434; **zero blocked connection attempts** were observed in completed test runs. This guard and the added skip mean this experiment's exact counts should be compared with its own fresh control rather than directly with Experiment 20's October counts.

The initial restricted-process baseline stalled at browser startup and was interrupted; its partial log is retained and is not counted as a completed run. The completed runs used the same permitted local process access. Default Chromium tests remain unavailable in full discovery; Edge is a separate focused supplement.

Existing failures concern historical recovery controls and unavailable artifacts/fixtures among other baseline issues; they have not been repaired or reclassified as passing. No fresh architecture self-test or full live application campaign was added here.

## Evidence and reproduction

- [Portable measurements and hashes](experiment21-results.json); [PR identities](pr-status-2026-11-08.json).
- Raw logs and per-test JSON remain locally under `reports/experiment21/results/` (ignored by Git).
- Actual replay files/results remain under `output/experiment21/functional-original`, `functional-compact`, and `functional-period` (ignored by Git).
- The tests were run before committing the merge: raw records show the parent HEAD plus working-diff hashes. The final report records the implementation commit and exact application-source hashes. No application code changed after the successful verification.

From the experiment root, using the same Python environment:

```powershell
python scripts/experiment21_run.py --label new-focused --focused
python scripts/experiment21_run.py --label new-full
python scripts/experiment21_functional.py --output-dir output/experiment21/new-compact --request 'Create a text file named test_level_1.txt containing exactly:Hello' --expected-text Hello
```

Set `HIVO_TEST_BROWSER_EXECUTABLE` to an installed browser executable for the focused browser supplement; leave it unset for the matched full-suite comparison. Use fresh labels/directories to preserve earlier runs. `scripts/experiment21_report.py` summarizes the recorded cohort. The baseline must be executed on the pinned Experiment 20 source, not on the integrated implementation.

## Outcome, limits and review summary

The parser defect is fixed and PR #5/#6 are integrated locally with Tasneem's tested changes. The declared deterministic/controlled-functional gate passed. The strict single-file grammar intentionally leaves unsupported or ambiguous prose to the wider requirements flow. This does not resolve Rodina's broader draft #8 issues or establish general recovery reliability.

Suggested review title: **Integrate Level 1 literal verification and correct compact colon parsing**. The change preserves exact source-defined payload bytes, combines both contributors' Worker state, adds direct negative controls, and records the controlled evidence with unchanged baseline failures. No push, GitHub PR merge, or new PR publication was performed.
