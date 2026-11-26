# Mini Hivo — Claude Code Entrypoint (`CLAUDE.md`)

@AGENTS.md

> **Mandatory instruction for Claude Code:** Follow [`AGENTS.md`](AGENTS.md) and its **Mandatory Rule Routing Table** and **Hard Rule Lock** strictly.
> - Before editing any subsystem, read its required file in `dev_rules/` first.
> - **NEVER auto-edit `AGENTS.md`, `CLAUDE.md`, or `dev_rules/*.md`** during normal feature, bugfix, analysis, test, or experiment tasks. Default to silence (`Rule Proposal: None`); emit a structured **Proposed Rule Update (NOT APPLIED)** in the worklog `REPORT.md` and final response only when a strict trigger fires.
> - **Mandatory offline check before finishing:** Any change under `hivo/` or `scripts/` must add/update offline tests (including at least one negative/boundary case) and pass `python scripts/check.py`.
