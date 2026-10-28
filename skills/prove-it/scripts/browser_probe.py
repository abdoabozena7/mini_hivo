#!/usr/bin/env python3
"""Execute explicit browser journeys and preserve real screenshots, trace and video.

Requires Playwright and an installed browser. No application is started here.
Only loopback navigation is allowed unless the plan explicitly allows a host.
This tool observes behavior; screenshots still need actual visual inspection.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urljoin, urlsplit


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if not os.environ.get("PROVE_IT_OUTPUT_DIR"):
        parser.error("Run through proof.py run so artifacts have a fresh, source-bound directory")
    output = Path(os.environ["PROVE_IT_OUTPUT_DIR"]).resolve()
    output.mkdir(parents=True, exist_ok=True)
    report = {"schema": 1, "run_id": os.environ.get("PROVE_IT_RUN_ID"), "started_at": stamp(),
              "passed": False, "assertion_count": 0, "page_errors": [], "console_errors": [],
              "request_failures": [], "http_errors": [], "steps": [], "errors": []}
    browser = None
    contexts = []
    try:
        plan = json.loads(args.plan.read_text(encoding="utf-8-sig"))
        base_url = plan["base_url"]
        allowed = set(plan.get("allow_hosts", ["localhost", "127.0.0.1", "::1"]))
        if urlsplit(base_url).hostname not in allowed:
            raise ValueError("base_url host is not in allow_hosts; do not test production by accident")
        if plan.get("environment") not in {"local", "test", "staging"}:
            raise ValueError("Declare environment as local/test/staging; production is not a default target")
        scenarios = plan.get("scenarios", [])
        if not scenarios: raise ValueError("No browser scenarios were defined")
        report["environment"] = plan["environment"]
        report["headed"] = plan.get("headed", True)
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            launch = {"headless": not plan.get("headed", True)}
            if plan.get("executable_path"): launch["executable_path"] = plan["executable_path"]
            browser = pw.chromium.launch(**launch)
            for si, scenario in enumerate(scenarios):
                name = re.sub(r"[^a-zA-Z0-9_-]", "-", scenario.get("name", f"scenario-{si}"))
                viewport = scenario.get("viewport", {"width": 1440, "height": 900})
                video_dir = output / "videos" / f"{si:02d}-{name}"
                context = browser.new_context(viewport=viewport, record_video_dir=str(video_dir),
                                              record_video_size=viewport)
                contexts.append(context)
                # Do not allow an accidental redirect or subresource request to a different host.
                def route_request(route):
                    host = urlsplit(route.request.url).hostname
                    if route.request.url.startswith(("data:", "blob:")) or host in allowed:
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")
                context.route("**/*", route_request)
                context.tracing.start(screenshots=True, snapshots=True, sources=False)
                page = context.new_page()
                page.set_default_timeout(plan.get("timeout_ms", 10000))
                page.on("pageerror", lambda exc: report["page_errors"].append(str(exc)))
                page.on("console", lambda msg: report["console_errors"].append(msg.text) if msg.type == "error" else None)
                page.on("requestfailed", lambda req: report["request_failures"].append({"url": req.url.split("?")[0], "failure": req.failure}))
                page.on("response", lambda response: report["http_errors"].append({"url": response.url.split("?")[0], "status": response.status}) if response.status >= 400 else None)
                steps = scenario.get("steps", [])
                if not steps: raise ValueError(f"Scenario {name} contains no steps")
                screenshot_dir = output / "screens" / f"{si:02d}-{name}"
                screenshot_dir.mkdir(parents=True, exist_ok=True)
                scenario_failed = False
                from playwright.sync_api import expect
                for index, step in enumerate(steps):
                    action = step["action"]
                    entry = {"scenario": name, "index": index, "action": action,
                             "selector": step.get("selector"), "at": stamp(), "passed": False}
                    locator = page.locator(step["selector"]) if step.get("selector") else None
                    try:
                        if action == "goto":
                            url = urljoin(base_url, step.get("path", "/"))
                            if urlsplit(url).hostname not in allowed: raise ValueError("Navigation host not approved")
                            response = page.goto(url, wait_until="domcontentloaded")
                            if response and response.status >= 400: raise AssertionError(f"Navigation HTTP {response.status}")
                        elif action == "click": locator.click()
                        elif action == "fill": locator.fill(step["value"])
                        elif action == "press": locator.press(step["key"])
                        elif action == "select": locator.select_option(step["value"])
                        elif action == "check": locator.check()
                        elif action == "uncheck": locator.uncheck()
                        elif action == "reload": page.reload(wait_until="domcontentloaded")
                        elif action == "back": page.go_back(wait_until="domcontentloaded")
                        elif action == "expect_text":
                            if step.get("exact", True): expect(locator).to_have_text(step["value"])
                            else: expect(locator).to_contain_text(step["value"])
                        elif action == "expect_visible": expect(locator).to_be_visible()
                        elif action == "expect_hidden": expect(locator).to_be_hidden()
                        elif action == "expect_enabled": expect(locator).to_be_enabled()
                        elif action == "expect_disabled": expect(locator).to_be_disabled()
                        elif action == "expect_value": expect(locator).to_have_value(step["value"])
                        elif action == "expect_count": expect(locator).to_have_count(step["value"])
                        elif action == "expect_attribute": expect(locator).to_have_attribute(step["name"], step["value"])
                        elif action == "expect_url_contains": expect(page).to_have_url(re.compile(re.escape(step["value"])))
                        elif action == "screenshot": pass
                        else: raise ValueError(f"Unsupported action: {action}")
                        if action.startswith("expect_"): report["assertion_count"] += 1
                        entry["passed"] = True
                    except Exception as exc:
                        entry["error"] = str(exc)
                        report["errors"].append(f"{name}, step {index}, {action}: {exc}")
                        scenario_failed = True
                    finally:
                        shot = screenshot_dir / f"{index:03d}-{action}.png"
                        try:
                            page.screenshot(path=str(shot), full_page=True)
                            entry["screenshot"] = shot.relative_to(output).as_posix()
                        except Exception as exc:
                            entry["capture_error"] = str(exc)
                            report["errors"].append("Screenshot capture failed: " + str(exc))
                        entry["url"] = page.url.split("?")[0]
                        report["steps"].append(entry)
                    if scenario_failed: break
                trace_path = output / "traces" / f"{si:02d}-{name}.zip"
                trace_path.parent.mkdir(parents=True, exist_ok=True)
                context.tracing.stop(path=str(trace_path))
                context.close(); contexts.remove(context)
            browser.close(); browser = None
        if report["assertion_count"] == 0: report["errors"].append("No successful outcome assertion executed")
        # Expected HTTP/console errors are still retained. Allow-list deliberately in the
        # surrounding contract when testing an error flow; do not erase them here.
        if report["page_errors"]: report["errors"].append("Unhandled browser page errors occurred")
        expected = plan.get("expected_errors", [])
        counts = [0 for _ in expected]
        for category in ("console_errors", "request_failures", "http_errors"):
            for event in report[category]:
                allowed_error = False
                for ei, rule in enumerate(expected):
                    if rule.get("category") != category: continue
                    match = rule.get("match")
                    matches = (event == match) if isinstance(event, str) else (
                        isinstance(match, dict) and bool(match) and all(event.get(k) == v for k, v in match.items()))
                    if matches and counts[ei] < rule.get("max_count", 1):
                        counts[ei] += 1; allowed_error = True; break
                if not allowed_error:
                    report["errors"].append("Unexpected " + category + ": " + str(event))
        for ei, rule in enumerate(expected):
            if counts[ei] < rule.get("min_count", 0):
                report["errors"].append("Expected error was not exercised: " + str(rule))
        report["expected_error_counts"] = counts
        report["passed"] = not report["errors"]
    except Exception as exc:
        report["errors"].append(f"Browser execution failed: {type(exc).__name__}: {exc}")
    finally:
        for context in contexts:
            try: context.close()
            except Exception: pass
        if browser:
            try: browser.close()
            except Exception: pass
        report["ended_at"] = stamp()
        (output / "probe.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"passed": report["passed"], "assertions": report["assertion_count"],
                          "evidence": str(output), "errors": report["errors"]}, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
