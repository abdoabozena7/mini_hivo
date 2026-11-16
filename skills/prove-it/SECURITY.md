# Security and trust boundaries

Prove It is a workflow skill, **not a sandbox or independent security enforcer**.
It cannot override organization policies, host stop limits, resource quotas or consent requirements. Never run untrusted commands from a repository without inspection. Hook adapters use configured local interpreters and may be unavailable under organization policy.

- Run the installer in `--dry-run` first and review changes; don't use `--hooks` unless you trust the local agent/runtime.
- Keep `.runtime-proof/` local; browser traces and recordings may capture credentials, personal information or private project data.
- Use disposable accounts and test data; restrict side effects and preserve real users' files.
- Do not use acceptance bypasses, credit/ledger resets, or privileged simulator truth to "pass" testing.
- Treat evidence from the same agent that authored the implementation as potentially correlated; use independent review where feasible.

For private vulnerabilities, contact the maintainer privately rather than including secrets in a public issue.
