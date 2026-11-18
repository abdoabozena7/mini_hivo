"""Discover existing browser observables and exercise a game through real input.

No source file, application global, or persistent test bridge is created here.
"""

import re
import uuid


_TERMINAL_LOSS = {"gameover", "game-over", "lost", "dead"}
_TERMINAL_WIN = {"won", "win", "complete", "completed"}


def requested_key(requirement):
    text = str(requirement or "")
    match = re.search(r"\b([a-z0-9])\s*(?:-|\s)\s*key\b", text, re.IGNORECASE)
    if not match:
        match = re.search(r"\bkey\s+['\"]?([a-z0-9])\b", text, re.IGNORECASE)
    return match.group(1).lower() if match else None


def discover_game_surface(page):
    """Rank only live globals whose own value is a stateful app interface."""
    inventory = page.evaluate(r"""() => {
        const candidates = [];
        for (const name of Object.getOwnPropertyNames(window)) {
            let descriptor;
            try { descriptor = Object.getOwnPropertyDescriptor(window, name); } catch (_) { continue; }
            const value = descriptor && descriptor.value;
            if (!value || typeof value !== 'object' || typeof value.getState !== 'function') continue;
            let state;
            try { state = value.getState(); } catch (_) { continue; }
            if (!state || typeof state !== 'object') continue;
            const methods = ['start', 'restart', 'move', 'step', 'forceCollision', 'forceWin']
                .filter((method) => typeof value[method] === 'function');
            if (!methods.length) continue;
            const stateKeys = Object.keys(state).slice(0, 20);
            const score = (name === 'AGENT_GAME' ? 100 : 0) +
                (stateKeys.includes('status') ? 20 : 0) +
                (stateKeys.includes('score') ? 10 : 0) + methods.length;
            candidates.push({name, methods, stateKeys, score});
        }
        const controls = Array.from(document.querySelectorAll('button, [role="button"]'))
            .slice(0, 20).map((element) => ({
                tag: element.tagName.toLowerCase(),
                id: element.id || null,
                text: (element.textContent || '').trim().slice(0, 70),
                dataMove: element.getAttribute('data-move'),
            }));
        const actionFunctions = Object.getOwnPropertyNames(window).filter((name) => {
            const descriptor = Object.getOwnPropertyDescriptor(window, name);
            return descriptor && descriptor.writable && typeof descriptor.value === 'function' &&
                /restart|reset|pause|resume/i.test(name);
        }).slice(0, 20);
        return {candidates, actionFunctions, dom: {
            canvasCount: document.querySelectorAll('canvas').length,
            controls,
            liveRegions: document.querySelectorAll('[aria-live], [role="status"]').length,
        }};
    }""")
    candidates = sorted(inventory.get("candidates", []),
                        key=lambda item: (-item["score"], item["name"]))[:5]
    selected = candidates[0] if candidates else None
    return {"surface_type": ("official_test" if selected and selected["name"] == "AGENT_GAME"
                             else "existing_app_hook" if selected else "unavailable"),
            "selected": selected, "candidates": candidates,
            "action_functions": inventory.get("actionFunctions", []),
            "dom": inventory.get("dom", {})}


def _invoke(page, name, method):
    return page.evaluate("([name, method]) => window[name][method]()", [name, method])


def _state(page, name):
    return page.evaluate("name => window[name].getState()", name)


def _status(state):
    return str((state or {}).get("status", "")).casefold()


def _position_changed(before, after):
    before, after = before or {}, after or {}
    return (before.get("player") != after.get("player")
            or before.get("position") != after.get("position")
            or before.get("score") != after.get("score"))


def _check(name, passed, **evidence):
    return {"name": name, "executed": True, "passed": bool(passed), **evidence}


def _dom_game_state(page):
    """Read only visible terminal/status and score markers from the page."""
    return page.evaluate(r"""() => {
        const visible = (element) => {
            const style = getComputedStyle(element);
            const rect = element.getBoundingClientRect();
            return style.display !== 'none' && style.visibility !== 'hidden' &&
                Number(style.opacity) > .5 && rect.width > 0 && rect.height > 0;
        };
        const markers = Array.from(document.querySelectorAll(
            '[data-state], [role="status"], [aria-live], [id*="result" i], [class*="result" i], ' +
            '[id*="game-over" i], [class*="game-over" i]'
        )).filter(visible).slice(0, 20);
        const terminal = markers.some((element) => {
            const value = `${element.getAttribute('data-state') || ''} ${element.textContent || ''}`;
            return /game\s*over|you\s*win|victory|\bwon\b|\blost\b|close\s*call/i.test(value);
        });
        const scoreElement = document.querySelector('[data-score], #score');
        const scoreText = scoreElement ? (scoreElement.textContent || '').trim() : null;
        const score = scoreText !== null && /^\d+$/.test(scoreText) ? Number(scoreText) : null;
        return {terminal, score, visibleMarkerCount: markers.length};
    }""")


def _dom_key_route(page, profile, requirement, surface):
    key = requested_key(requirement)
    required = set(profile.required_interactions)
    if not key or "restart_resets_state" not in required:
        surface["reason"] = "no stateful hook and no supported DOM key requirement"
        return surface, []
    before = _dom_game_state(page)
    if not before["terminal"]:
        surface["reason"] = "terminal precondition is not visible; DOM route cannot establish it safely"
        return surface, []
    instrumented = None
    token = None
    if before["score"] is None:
        candidates = [name for name in surface.get("action_functions", [])
                      if re.search(r"restart|reset", name, re.IGNORECASE)]
        if not candidates:
            surface["reason"] = "DOM route has no score oracle or callable restart/reset function"
            return surface, []
        token = "__hivo_verifier_" + uuid.uuid4().hex
        instrumented = candidates[0]
        installed = page.evaluate(r"""([name, token]) => {
            if (Object.prototype.hasOwnProperty.call(window, token)) return false;
            const original = window[name];
            if (typeof original !== 'function') return false;
            const probe = {name, original, calls: 0};
            window[token] = probe;
            window[name] = function (...args) {
                probe.calls += 1;
                return original.apply(this, args);
            };
            return true;
        }""", [instrumented, token])
        if not installed:
            surface["reason"] = "temporary browser instrumentation could not attach"
            return surface, []
    try:
        page.keyboard.press(key)
        page.wait_for_timeout(150)
        after = _dom_game_state(page)
    finally:
        calls = None
        if token:
            calls = page.evaluate(r"""token => {
                const probe = window[token];
                if (!probe) return null;
                window[probe.name] = probe.original;
                delete window[token];
                return probe.calls;
            }""", token)
    if instrumented:
        passed = calls is not None and calls > 0 and not after["terminal"]
        surface_type = "temporary_instrumentation"
        selected = {"name": instrumented}
    else:
        if after["score"] is None:
            surface["reason"] = "DOM score reset became unobservable after key press"
            return surface, []
        passed = not after["terminal"] and after["score"] == 0
        surface_type = "observable_browser"
        selected = {"name": "DOM"}
    check = _check("restart_resets_state", passed, input=key,
                   before=before, after=after,
                   **({"instrumented_function": instrumented, "call_count": calls} if instrumented else {}))
    surface.update({"surface_type": surface_type, "selected": selected,
                    "required_interactions": sorted(required),
                    "executed_interactions": [check["name"]],
                    "behavior_test_executed": True,
                    "all_required_executed": required <= {check["name"]}})
    return surface, [check]


def run_game_checks(page, profile, requirement):
    """Use the discovered interface for setup/observation, real browser input for action."""
    surface = discover_game_surface(page)
    selected = surface["selected"]
    if not selected:
        return _dom_key_route(page, profile, requirement, surface)
    name = selected["name"]
    methods = set(selected["methods"])
    required = set(profile.required_interactions)
    checks = []
    key = requested_key(requirement)

    if "keyboard_movement" in required and ("restart" in methods or "start" in methods):
        _invoke(page, name, "restart" if "restart" in methods else "start")
        before = _state(page, name)
        page.keyboard.press("ArrowUp")
        page.wait_for_timeout(120)
        after = _state(page, name)
        checks.append(_check("keyboard_movement", _position_changed(before, after),
                             before=before, after=after, input="ArrowUp"))

    if "restart_resets_state" in required:
        if key and {"forceCollision", "forceWin"} <= methods:
            cases = []
            for setup, terminal in (("forceCollision", _TERMINAL_LOSS),
                                    ("forceWin", _TERMINAL_WIN)):
                if "restart" in methods:
                    _invoke(page, name, "restart")
                _invoke(page, name, setup)
                before = _state(page, name)
                setup_valid = _status(before) in terminal
                page.keyboard.press(key)
                page.wait_for_timeout(120)
                after = _state(page, name)
                cases.append({"setup": setup, "precondition_met": setup_valid,
                              "before": before, "after": after,
                              "passed": (setup_valid and _status(after) not in terminal
                                         and after.get("score") == 0
                                         and (after.get("player") or {}).get("row", 0) == 0)})
            checks.append(_check("restart_resets_state", all(item["passed"] for item in cases),
                                 input=key, cases=cases))
        elif not key and {"forceCollision", "restart"} <= methods:
            _invoke(page, name, "forceCollision")
            before = _state(page, name)
            _invoke(page, name, "restart")
            after = _state(page, name)
            checks.append(_check("restart_resets_state",
                                 _status(before) in _TERMINAL_LOSS
                                 and _status(after) not in _TERMINAL_LOSS
                                 and after.get("score") == 0,
                                 before=before, after=after, input="existing restart control"))

    if "goal_win_state" in required and "forceWin" in methods:
        if "restart" in methods:
            _invoke(page, name, "restart")
        _invoke(page, name, "forceWin")
        after = _state(page, name)
        checks.append(_check("goal_win_state", _status(after) in _TERMINAL_WIN,
                             after=after))

    if "touch_control" in required and "restart" in methods:
        _invoke(page, name, "restart")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(120)
        button = page.locator("[data-move='up'], [data-direction='up'], .touch-controls button").first
        if button.count() and button.is_visible():
            before = _state(page, name)
            button.dispatch_event("pointerdown", {"pointerType": "touch", "isPrimary": True})
            page.wait_for_timeout(120)
            after = _state(page, name)
            checks.append(_check("touch_control", _position_changed(before, after),
                                 before=before, after=after, input="pointerdown"))
        else:
            checks.append(_check("touch_control", False, input="pointerdown",
                                 evidence="no visible touch control"))
        page.set_viewport_size({"width": 1440, "height": 900})

    surface["required_interactions"] = sorted(required)
    surface["executed_interactions"] = [item["name"] for item in checks]
    surface["behavior_test_executed"] = bool(checks)
    surface["all_required_executed"] = required <= set(surface["executed_interactions"])
    return surface, checks
