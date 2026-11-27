# Controlled browser harness

2026-11-27. [Verified scope and evidence](worklogs/rodina/2026-11-27_browser-harness-portability/REPORT.md). This harness uses scripted provider decisions and real local tools/browser; it never establishes live-model reliability.

Browser selection order: explicit `--browser-executable`; installed Playwright Chromium bundle; PATH Chromium/Chrome/Edge; standard installed Chrome/Edge locations. An explicit invalid choice is an error, not permission to silently substitute another browser. A real headless protocol launch validates compatibility before the fixture is generated. No dependency or browser installation is automatic.

A fresh run directory records `source-at-start.json`, `browser-provenance.json`, results and optional private packet captures. Provenance includes the exact executable path, selection source and actual browser version. Missing/failed browser startup records UNAVAILABLE and a non-success result before provider construction/project generation. Successful startup does not waive child behavioral checks or read-only parent verification.

```powershell
# Run from repository root with existing dependencies. Pick a NEW output directory.
.venv/Scripts/python.exe -B -X utf8 scripts/provider_controller_functional.py --worker-context 4096 --expect-compact-success --capture-packets --output-dir output/my-new-controlled-run
# Optional: --browser-executable 'path to an installed compatible executable'
```

Preserve raw output privately. A negative fixture uses `--variant inert`; its expected outcome is functional rejection and rollback, never a working application. Root success is justified only when all assigned source obligations and current artifact checks pass.
