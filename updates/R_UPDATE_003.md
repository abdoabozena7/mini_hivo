# R_UPDATE_003 - Integrating Karim PR #1 without losing working behavior

## A. Update Identification

- **Date:** 2026-11-17; command records retain the local timestamps.
- **Verified scope:** local content integration of all 36 commits at Karim's actual PR head, compatible execution gates, complete regression, and fresh local-model product acceptance.
- **Branch:** `integration/karim-pr1-quiet-tui`, based on `6887d0bfeda237d841ba6a3ac842d184b5ad55b8`.
- **Incoming PR:** [#1](https://github.com/abdoabozena7/mini_hivo/pull/1), head `34a972a0b2feb80a31e06d0b93d6c22ca2961bc8`.
- **Tested implementation fingerprint:** `51d6004ca2e5fe225a517a3e12362224cfb7c5da446638b80923bc18515ae67f`. The mapping covers the actual working-tree bytes of `mini.py` and `hivo/*.py`; it is not an assertion that the uncommitted merge was already a commit.
- **Containing merge commit / remote state:** pending at this document's checkpoint. Subsequent publication must verify the two parents, ancestry and actual GitHub `merged` state.
- **Separate follow-up:** the requested calm session-oriented terminal UI begins only after this merge checkpoint. No UI acceptance is claimed here.

## B. Original Problem

The user asked to merge Karim's actual changes, preserve traceability, retain the useful behavior from both implementations, repair problems, and test the result with a real local model. An earlier branch consolidation had preserved local histories, but **had not included Karim's external-fork PR**. Inspection established that PR #1 was still open and its head was not an ancestor of local `main`.

The expected result is not just a conflict-free index or an application that imports. Both original histories must remain reachable, previous source-to-output safeguards must still work, contributor verification improvements must be usable, and actual requests must produce independently correct artifacts.

The original checkout also held a user's untracked manual-test project. Development therefore used a separate integration worktree rather than modifying that project or replacing its files.

## C. Why the Update Was Necessary

A source-level transplant without the PR's original commits would not meet the tracing requirement. Taking either side of every conflict would also lose useful work:

- Main contained measured fixes for native tool recovery, new-artifact context, source-derived Python acceptance, safe new-draft rewriting and fresh post-repair verification.
- Karim's branch contained exact literal-artifact contracts, fail-closed verification parsing, bounded structured evidence, scoped browser results, child verification ownership and context progress improvements.

Some experiments independently reused the numbers 18 and 19. Resolving their reports by choosing one version would erase the other workstream's evidence from the current tree even if Git retained old blobs.

## D. Root Cause Analysis

| Finding | Classification | Evidence and consequence |
|---|---|---|
| The external PR tip was absent from local ancestry | Observed Git state | 36 incoming commits remained outside the previous consolidation |
| JSON clipping and permissive result parsing could lose authoritative verdict meaning | Contributor implementation and tests | Preserved the bounded structured projection and strict parsing rather than reverting them |
| The shorthand literal request plus trailing prompt-file newline missed a deliberately narrow parser | Reproduced live integration failure | The generic impact contract had no expected-byte digest; creating correct bytes alone could not pass the typed literal route |
| Model-selected `read_file` is not a native verification receipt | Observed live diagnostic | Independent controller readback is needed; prose or a plain read must not be relabeled as executed verification |
| A missing exclamation mark remained wrong even when generated tests were changed to agree | Reproduced live negative result | Source-derived acceptance correctly rejected the candidate |
| Whole-draft-only repair refused the focused edits needed for that source mismatch | Recorded actual tool receipts | Source-observed mismatches now use the existing focused Repairer; new-draft creation policy itself is unchanged |
| Historical fixture paths were absent in a new worktree | Reproduced environment difference | Authentic pre-existing output fixtures were exposed read-only by convention through a local directory junction; no replacement fixtures were invented |
| One nominal unit test could invoke the live clarification provider | Test inspection and full-suite observation | That specific test now scripts its clarification result so broad regression remains an offline controller check |

The unsuccessful attempts remain in the evidence record. They are not counted as successful live runs.

## E. What Changed

| Area | Integration decision / correction | Verification |
|---|---|---|
| [mini.py](../mini.py) | Retain main's source/callable assertions and terminal context classifications alongside contributor native literal readback, structured feedback and bounded context progress | Combined suite and fresh real-model requests |
| [requirements.py](../hivo/requirements.py) | Retain action/object/polarity conflict comparison; split coordinated object groups so real removal-versus-preservation contradictions remain visible | Requirement and authority regressions |
| Literal request ingestion | Accept explicit file/filename forms and harmless outer source whitespace; reject compound/internal multiline requests and ambiguous bare names | Parser positive/negative controls and actual prompt-file replay |
| Source acceptance | ROOT independently invokes the existing native `run_file` readback under already accepted literal authority, recording actual bytes/digests | Correct/wrong-byte regression and real exact-byte artifact |
| Repair selection | Source-observed expected/actual mismatches use focused Repairer tools instead of rejecting a legitimate small correction under whole-draft policy | Real filesystem repair regression and greeting replay |
| Initial context recovery | Do not stack contributor greenfield retry on top of a consumed native-tool reanchor budget | Existing opt-in policy and context regressions |
| Insufficient-context handling | Do not run a structured format repair when the model explicitly states it cannot proceed | Terminal context regressions |
| Negative impact fixture | Declare an actually unproduced required target, rather than expecting the repaired goal-to-target binding to remain broken | Verification integrity regression |
| Syntax assertion fixture | Parse the JSON verdict instead of asserting whitespace formatting | Browser syntax regression |
| Report collisions | Keep both complete report histories under explicit names and distinguish them in the indexes | Original byte-hash comparison |
| Large-source clarification test | Mock only that test's provider boundary with an empty clarification response | Full offline regression |

The PR's other nonconflicting modules, tests, scripts, reports, publication records and workflow instructions are retained. The merge does not claim that every historical experiment becomes newly successful.

## F. How the Fix Works

The literal path starts with the **original user source**, not a shortened model goal. A recognized single-file request compiles to a bounded impact candidate containing the relative target, source requirement identities, verification obligations and SHA-256 of the required UTF-8 bytes.

The existing context and impact gates still authorize mutation. The model cannot install an accepted contract, widen its path set, authorize metadata writes or overwrite an existing user file by describing permission in text.

After creation, native readback hashes the real artifact. ROOT also performs that read independently of the model's choice of verification tool. A missing file, wrong content, forged authority or unsupported proof is not a pass. Existing post-state checks remain separate.

For Python tasks, source-derived command/function assertions remain the oracle. If the function must return `Hello, Ada!`, changing a generated test to expect `Hello, Ada` cannot satisfy the source. When such a mismatch is observed, repair receives the concrete expected/actual pair first and uses the existing focused editing path. Fresh verification then runs against the corrected state; old failures are not blindly retained and old successes are not reused as current proof.

## G. Functional Verification

All live roles used local Ollama `gemma4:e4b`; no alternate cloud model was substituted. The retained model digest is in the [sanitized validation record](../reports/integration/karim-pr1/validation.json).

| Scenario | Class and real boundary | Independent oracle | Observed result |
|---|---|---|---|
| `Create proof.txt containing exactly:MERGE_READY` from a file ending in newline | Fresh live-model E2E through default `auto` and actual filesystem | Read actual bytes, not the agent summary | Exit 0; `proof.txt` was exactly hex `4d455247455f5245414459`, with no newline |
| Original greeting utility request, unchanged from prior acceptance | Fresh live-model E2E through default `auto` | Separate subprocess calls plus imported public function | Default, Ada and Bob CLI output correct; all three function values preserve punctuation and omit newline |
| Generated greeting test execution | Real generated artifact | Run `python -m unittest test_greet.py -q` independently | Two tests executed; exit 0 |
| Wrong literal bytes | Controlled functional; real controller and filesystem, scripted provider decisions | Compare expected digest and actual file bytes | Native proof and post-state comparison reject wrong content |
| Literal source with model choosing only ordinary file reading | Controlled integration | Real ROOT native receipt, not model prose | Accepted source authority produces an executed typed readback |
| Source mismatch in a new draft | Controlled functional; real filesystem and focused tool execution | Independently call the public function before/after repair | Wrong value rejected, exact focused correction executed, correct value observed |
| Favicon versus real application errors | Real-browser regression using existing Chromium | Actual page/network/console observations | Five contributor cases executed, including real errors remaining failures |

The live literal success used fingerprint `dba0ee...`; the subsequent repair-selection correction produced `51d600...`, used by the final greeting and broad regression. This is a staged verification record, not a claim that both live attempts ran on identical bytes.

## H. Additional Successful Tests

| Check | Exact command / selector | Observed result |
|---|---|---|
| Final combined regression | `python -X utf8 -m unittest discover -s tests -q`, with `HIVO_TEST_BROWSER_EXECUTABLE` pointing to an existing Chromium | **1901 run; OK; 4 existing skips**, exit 0 |
| Focused source/impact/verification repair | `python -X utf8 -m unittest discover -s tests -q -k adaptive_architecture -k level1_native_verification -k verification_outcome_integrity -k greenfield_impact_lifecycle -k test_python_checks` | 157 run, OK |
| Literal-source/context/clarification integration | `python -X utf8 -m unittest discover -s tests -q -k level1_native_verification -k literal_parser_regression -k greenfield_impact_lifecycle -k verification_outcome_integrity -k requirement_clarification -k context_sufficiency_gate` | 144 run, OK |
| Contributor browser cases | `python -X utf8 -m unittest discover -s tests -p test_browser_implicit_favicon.py -v`, with the existing-browser environment variable | 5 run, OK |
| Public architecture self-test at parser checkpoint | `python -X utf8 mini.py --self-test --no-bootstrap` | PASS, exit 0; source fingerprint recorded separately |
| Public architecture self-test on final merge source | `python -X utf8 mini.py --self-test --no-bootstrap` | PASS, exit 0; fingerprint `51d600...` |

These suites overlap. Their counts must not be summed as unique coverage. Skips are not passes.

## I. Regression and Compatibility Impact

The final combined suite includes contributor functionality and existing main behavior. The four remaining skips are explicit historical legacy scheduler cases in `test_mini.py`: deterministic stage scheduling, the old hidden-stage `TASK_TOO_BROAD` continuation, duplicate continuation/rewrite scheduling, and deterministic stage slices replaced by node contracts.

Earlier combined runs had nine skips because five contributor browser cases require explicit opt-in. The existing Chromium executable was located and those five were subsequently **executed**, both directly and in the final complete suite. No skip was added to obtain a pass.

The initial integration attempts exposed genuine differences and failures:

- The first focused suite failed before coordinated-polarity and feedback reconciliation.
- A full run failed when the new worktree lacked authentic historical output fixtures and had overlapping retry-policy behavior.
- A later run exposed a missing import in the test-only clarification patch; this was repaired rather than ignored.
- `live-literal-01` was interrupted after causal diagnosis; its process exit is unknown, not zero.
- `live-literal-02` failed verification and rolled back.
- `live-greeting-01` failed source/repair acceptance and rolled back; the independent product oracle also failed.

Successful fresh attempts follow documented corrections; failed attempts have not been overwritten or hidden.

The original checkout, user manual-test project, detached historical worktree and stash are outside the edited product scope. Their preservation is checked again before final publication.

## J. Overall Impact

The merged implementation combines source-bound verification and contributor evidence discipline with main's measured execution repairs. It preserves real commit provenance rather than substituting a squash or copied snapshot. The demonstrated outcome is an actual exact-byte file and an independently runnable Python utility, not merely a model completion message.

## K. Remaining Limitations

- This is a bounded integration validation, not a claim that a small local model solves every arbitrary coding request.
- The fresh live set contains one accepted literal case and one accepted greeting case, with earlier failures retained. It is not a statistical reliability benchmark.
- Historical experiment outcomes remain historical; their original failures and limits are not rewritten.
- Host preflight remains authoritative. Local resource or provider failures must still stop execution rather than becoming false success.
- The requested terminal session UI and its independent interactive acceptance are a separate next checkpoint.
- GitHub PR merge status must be verified after authorized publication; local ancestry alone is insufficient.

## L. Evidence and Reproduction

The [sanitized validation record](../reports/integration/karim-pr1/validation.json) contains actual run IDs, source fingerprints, elapsed times, exit codes, exact product expectations, independent observations and failed-attempt dispositions. Original full command records, stdout/stderr, SQLite tool receipts and host reports remain in the private session evidence directory, not in new public raw logs.

From the repository root, using an installed local model and an existing empty workspace:

```powershell
python -X utf8 mini.py --self-test --no-bootstrap
python -X utf8 -m unittest discover -s tests -q
# For the five opt-in browser tests, first set HIVO_TEST_BROWSER_EXECUTABLE
# to the existing Playwright Chromium executable on this machine.
python -X utf8 mini.py --workspace .\output\fresh-empty-workspace --prompt-file .\literal-prompt.txt --no-bootstrap
```

The last command requires creating a **new empty workspace** and a prompt file containing the exact literal request above. Do not reuse historical run directories. The command is a reproduction recipe, not an instruction to rerun an unbounded live batch.

### Report-name collision preservation

| Original main path | Byte-preserved current-tree path | Original SHA-256 |
|---|---|---|
| `reports/experiment18/experiment18-report.md` | [no-tool-exit-report.md](../reports/experiment18/no-tool-exit-report.md) | `822d777844584572473796fd6013c9592381d6aa9ff997a39a47be7b62ab2a35` |
| `reports/experiment19/RUNBOOK.md` | [CONTEXT_CLOSURE_RUNBOOK.md](../reports/experiment19/CONTEXT_CLOSURE_RUNBOOK.md) | `c8372dbe1069e35ccfae0db2215f4b84e0f2d2c6f873094d615d8a3214d00f21` |
| `reports/experiment19/experiment19-report.md` | [context-decision-closure-report.md](../reports/experiment19/context-decision-closure-report.md) | `f6db10458b43dde9dea0ba3378a3a0f01edf65f3db73b293cf02e77a9e76387f` |
| `reports/experiment19/experiment19-results.json` | [context-decision-closure-results.json](../reports/experiment19/context-decision-closure-results.json) | `8e4682ce6d2db3564ec7fd0c39d3e01a2a1751bb235b94fd678b22e09f5a49bf` |

Contributor versions retain their canonical incoming paths and supporting links. A complete all-ref Git bundle was made before integration. The two-parent merge and normal Git history provide commit-level tracing; the collision table provides current-tree report tracing.

## M. Summary for the Team

**Title:** Merge Karim PR #1 while preserving source-to-output verification.

**Why:** the prior local consolidation did not include the actual external PR, and simply choosing conflict sides would discard useful execution or verification behavior.

**What changed:** combined both histories and report workstreams; reconciled context/evidence/impact behavior; repaired literal-source ingestion and independent readback; preserved source assertions and enabled focused correction of source-observed mismatches.

**Functional proof:** fresh local Gemma literal and greeting requests, independently checked bytes/CLI/function results; controlled wrong-byte/authority checks and real browser error classification.

**Additional tests:** final complete suite 1901 run, OK with four pre-existing skips; overlapping focused suites and public self-test are recorded separately.

**Remaining work:** calm persistent-session terminal, final interactive acceptance, final source validation, non-force publication and explicit verification that GitHub marks PR #1 merged.

**Publication state:** this record describes the tested local merge before its containing commit and remote publication. Later milestones must add their actual commit/status evidence without pretending it was known in advance.
