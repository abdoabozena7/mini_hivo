# Experiment 22 — Verification status fail-closed integration

Preregistered 8 November 2026. Parent checkpoint: Experiment 21, `56b328d197af56c706f1b4a980baceb6ab5ed20d`. New branch: `codex/experiment22-verification-integrity`.

## Question

Can the open PR #9 verification-integrity changes and PR #10 child-scoped verification changes be integrated on the current Experiment 21 baseline while ensuring an unrecognized explicit verification status cannot be promoted to PASS by a `passed: true` field?

## Fixed inputs

- Current baseline: Experiment 21 `56b328d197af56c706f1b4a980baceb6ab5ed20d`.
- PR #9 head reviewed: `af5ed5dded24f2ae8f3bdc10e60eb9362efd0563`.
- PR #10 head reviewed: `156c616a3a678b803d3e695dcb8386dae040960d`.
- PR #10 includes the shared PR #9 verification-integrity implementation; the production changes to `hivo/evidence.py` and `hivo/verification_routing.py` are identical across the two heads. PR #10 adds the child-scope module, orchestration wiring, and its regression suite.
- PRs #9 and #10 were based on `f842fb8fb6e63e3064891d26ee0b24981e55c847`, an ancestor of the current baseline.
- PRs #11 and #12 were separately reviewed as retrospective documentation proposals; they are not treated as PR #9/#10 source changes or as experiment arms.

## Hypothesis

When a structured receipt contains an explicit unrecognized state such as `ERROR`, `BLOCKED`, or `WARN`, the parser must not treat a simultaneous `passed: true` as proof. Conflicting explicit statuses also cannot produce PASS. Explicit failure remains failure; recognized success and legacy statusless boolean receipts remain supported.

## Procedure

1. Reproduce the reported contradiction against the PR #10 parser: `_parse_result({"status": "ERROR", "passed": True})` returned `("PASS", True)`.
2. Integrate PR #10 in a clean worktree from the fixed Experiment 21 baseline. Preserve the existing Experiment 20 report and results; archive PR #10's colliding report/results under distinct names.
3. Parse every non-empty `verification_status`, `status`, and `result` field. Any explicit failure or `passed: false` yields FAIL. Pending, skipped, missing, unknown, or conflicting non-failure states are unavailable, never PASS. PASS requires recognized, mutually consistent success states, or a statusless `passed: true`.
4. Add regression cases for unknown states, encoded JSON, conflicting status fields, explicit failure, and supported success receipts.
5. Run the 13 selected verification-integrity and child-scope suites with both live model entry points patched to fail if called. Record each suite's expected and observed method count, interpreter, package versions, and normalized source hashes.
6. Review PR #11/#12 documentation scope and current-main claims; do not merge stale retrospective text into the experiment.

## Acceptance criteria

- The original contradictory receipt no longer parses as PASS.
- Explicit failure remains FAIL, while the supported success receipt forms remain PASS.
- All 13 selected suites pass at their declared counts.
- No source/test merge conflicts remain; report-name collisions are preserved without overwriting existing Experiment 20 history.
- The report distinguishes selected offline regression evidence from full-suite, live-provider, and end-to-end outcomes.
