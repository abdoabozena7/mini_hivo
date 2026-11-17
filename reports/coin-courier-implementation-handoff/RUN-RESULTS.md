# Recorded Runs 007?009

[Overview](README.md) ? [Validation](VALIDATION-STATUS.md) ? [Next steps](NEXT-STEPS.md)

These are existing results, not new runs. Detailed execution evidence is indexed in the [pinned engineering handoff](https://github.com/tasneem-ahmed05/mini_hivo/blob/5e66d34db1827b814abf98f56b0b77b5ef6f8ee5/reports/coin-courier-runtime-integration/ENGINEERING-HANDOFF.md). Runs 001?006 remain documented by [team PR #2](https://github.com/kareem232003/mini_hivo/pull/2); their chronology is not repeated here.

## Common controls and comparison limits

The original Coin Courier prompt was unchanged (SHA256 `848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256`). Existing Python 3.11.9, local `gemma4:e4b` and Chromium were reused. The CLI used `--prompt-file` through normal ingestion, specification, planning and orchestration, not direct scripted Worker dispatch. This differs from historical interactive input; legitimate unanswered clarification would block.

Policies remained `current` with `field_scoped` verification classification; Worker budget 28, Falsifier budget 8, host canary timeout 180 seconds, ordinary request timeout 600 seconds and external wall cap 2400 seconds. Each attempt used a fresh workspace and captured its source snapshot/configuration. All three host canaries passed per attempt. RAM/model warm state differed, so timing is not a controlled performance comparison. Historical Run-006 used withheld ingestion rewrites; it is not automatically a matched Before arm.

## Outcomes

| Attempt | Implementation delta and actual execution | Stopping point / retained state |
|---|---|---|
| Run-007 | New ingestion corrections plus preserved Worker fixes. Real specification/planning/decomposition/Mission Compiler, Builder dispatch, sufficient context, accepted impact and file writes | False failure from implicit favicon 404; deliberately interrupted for correction. `index.html` and placeholder `game.js` remained. No normal root verdict or transaction acceptance. |
| Run-008 | Tested favicon correction. Builder wrote the same HTML and finished; Falsifier dispatched and finished; basic page checks passed | Required game check failed missing `AGENT_GAME`. Two Repairers were rejected by parent-anchor drift. Pipeline rolled back HTML and attempted another strategy; interrupted for the reproduced handoff defect. Final workspace contained no application files; observer archive retained the HTML. |
| Run-009 | Tested Repairer anchor correction. Real Builder completed nine tools including two writes and one edit; Falsifier completed four tools. Repairer impact acceptance succeeded | Required game route still failed. Repairer made no mutation; a later context decision rejected unsupported evidence kinds. User-requested stop after 1552.266 seconds, exit 1, wall cap not reached. No normal root verdict. |

## Run-009: milestone versus acceptance

Native run `20261021T155855-9d43bc5a` contains 171 events; SQLite records 23 tool events. Native line 36 records first Worker dispatch; line 46 records accepted Builder impact authority; line 85 records Builder completion. Line 108 records Falsifier completion, line 111 required-browser failure, and line 121 accepted Repairer impact authority on the Builder's original contract/hash.

Repairer calls consisted of two context checks, one listing, five reads and two basic page runs: **no Repairer write or edit**. SQLite event 19 returned an invalid structured sufficiency decision with unsupported evidence-kind errors, `insufficient`, `PREPARING_CONTEXT` and mutation disallowed. Exact rejected kind strings are not preserved in that event. This corroborates the Experiment 18A boundary; it does not establish its causal role in earlier stalls.

The final provisional files were:

| File | SHA256 | Interpretation |
|---|---|---|
| `index.html` | `205c14071f143efe3f314b08708ee6cd0e0fa69f657595c8e19f8d59ababbd93` | 14,914-byte partial candidate, identical to earlier HTML |
| `game.js` | `d4bcd9abe74db234c055d29580bb891cf0f04d4fc52a02ee62fb3134f196c3f3` | Placeholder comment and console log |

Run-009 has **zero transaction commits and zero rollbacks**. Persisted provisional writes demonstrate actual authorized Worker implementation progress, not final transaction acceptance. A finished Falsifier and passing basic page loads do not override required-game failure.

## Independent acceptance limits

Existing Run-007 partial observations confirmed Arrow/WASD movement, arena clamping, two physical coin collections awarding +10 each, no idle repeat awards and no page errors. The candidate lacked the required bridge, visible touch controls and usable mobile layout. Obstacle/game-over/win/restart/persistence acceptance was not established. No new independent Run-009 acceptance session occurred.

**Coin Courier was not completed. Full independent application acceptance was not demonstrated.** User-requested termination is an interruption, not a natural success or final failure verdict.
