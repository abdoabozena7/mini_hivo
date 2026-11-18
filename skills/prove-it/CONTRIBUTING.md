# Contributing to Prove It

Welcome. Propose behavior changes with a concrete failure example and an observable acceptance criterion, not just more instructions or test count.

## Before a PR

1. Explain the failure mode and which real agent workflows it affects.
2. Keep `SKILL.md` concise; put domain-specific expansions under `references/`.
3. Prefer an executable verifier for deterministic invariants; don't invent permission bypasses.
4. Add a regression which would have failed before your change, and include a safe negative control where useful.
5. Run `python -m unittest discover -s tests -p 'test_*.py'` and the skill validator.
6. Update `CHANGELOG.md` and `VERSION` for releases. Clearly distinguish local harness tests from real hosted-agent acceptance.

Do not publish tokens, recordings, user source files or private screenshots. Use sanitized reproducible examples.
