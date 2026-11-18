# Real web and UI validation

## Start and identify the actual application

Discover the repository's documented development/production-like launch command.
Start one owned instance, wait for actual readiness and confirm the browser is
connected to that instance and current build. Do not navigate to an old server
or replay and call it the new implementation. Record URL, mode, source, process
owner and build. Stop only processes started for this task, not unrelated work.

Use the host's real browser tool, an existing test harness or the optional
Playwright driver. Prefer headed mode for a user-visible workflow when supported.
Headless execution can still be real product execution; disclose it and inspect
captured output. Do not claim to have opened a user's visible desktop from a
remote container. Do not bypass browser/admin/sandbox restrictions.

## Inventory and exercise

Create a control/state matrix using `assets/templates/interaction-matrix.md`.
Include required pages, modes, buttons, menus, forms and camera/theme controls.
Check action consequences, not just that selectors exist. Include loading,
empty, validation-error, server-error, disabled and recovery states where relevant.
Exercise desktop and mobile layouts, keyboard focus and navigation, reload,
back/forward, persistence and repeated actions as the task requires.

For a camera switch, verify the selected stream/view actually changes. For a
Save button, verify the real persisted value. For authentication, verify both
allowed and disallowed behavior using test accounts. Do not send real email,
charge money, delete production data or publish just to complete coverage.
Mark actions that require separate authorization accurately.

## Inspect, do not merely capture

Capture states before/after meaningful actions. Inspect the actual image and
trace. Check overflow, clipped text, spacing, contrast, focus and layout at the
selected viewport. Explain why a UI change is needed; do not make random visual
changes from DOM assertions alone. Run the interaction again after editing.

Read console, uncaught errors and failed requests. Intentional validation errors
may be expected, but retain and explicitly match them; do not blanket-ignore
all HTTP 400/500 responses. For end-to-end claims, do not intercept the target
API with a successful fixture. Early fixture-based UI checks are labeled fixture.

## Optional bundled driver

`scripts/browser_probe.py` accepts a JSON journey, performs real Playwright
operations and writes per-step screenshots, trace ZIPs, WebM videos and
`probe.json` into a fresh `PROVE_IT_OUTPUT_DIR`. Run it via `proof.py run`.
It does not start the app, infer your business assertions, inspect screenshots,
or discover every control automatically. The agent must define correct journeys.

Supported actions: `goto`, `click`, `fill`, `press`, `select`, `check`, `uncheck`,
`reload`, `back`, `screenshot`, and outcome assertions `expect_text`, `expect_visible`,
`expect_hidden`, `expect_enabled`, `expect_disabled`, `expect_value`, `expect_count`,
`expect_attribute`, `expect_url_contains`. Selectors must target actual elements.
Use existing richer browser tooling for downloads, dialogs, complex drag-and-drop,
multiple tabs or interaction types not supported by this small driver.

The default host allowlist is localhost/127.0.0.1/::1. Declare extra test hosts
explicitly when required; this is accident prevention, not a security sandbox.
WebSockets, browser internals and page code need host-level network controls for
strong isolation. Use local/test/staging environments, never default production.

Default `headed` is true. Missing displays/browsers/video encoders must fail rather
than silently changing modes or dropping video. Install dependencies through an
approved environment; do not weaken the evidence contract to hide a missing tool.
Allow specific expected error events through `expected_errors`, for example:

```json
{
  "category": "http_errors",
  "match": {"url": "http://127.0.0.1:8765/api/items", "status": 422},
  "min_count": 1,
  "max_count": 1
}
```

This exception is for an intentionally exercised error path, not a general way
to hide failures. Raw events remain in the report.

## Evidence before completion

Require actual UI journey receipts, screenshots/video/trace, real network or
persistence evidence for integration claims, explicit visual inspection and a
final current-source run. A browser driver PASS without a completed visual
review is not enough to claim that the UI design is good.
