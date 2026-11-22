"""Deterministic output-quality rubrics and browser/Three.js failure diagnostics."""

from __future__ import annotations

import re
from typing import Any

from hivo.playbooks import classify_project


_SEMANTIC_CONTRACT_FIELDS = (
    "goal",
    "original_goal",
    "requirements",
    "constraints",
    "success_criteria",
    "done_when",
    "allowed_mutation_paths",
    "target_paths",
    "entrypoint",
    "verification_target",
    "integration_test_target",
)

_THREEJS_OR_3D_PATTERNS = (
    re.compile(r"\bthree\.?js\b", re.IGNORECASE),
    re.compile(r"\bthree/addons\b", re.IGNORECASE),
    re.compile(r"\bthree\.module\.js\b", re.IGNORECASE),
    re.compile(r"\bwebgl2?\b", re.IGNORECASE),
    re.compile(r"(?<![0-9a-f])\b3d\b(?![0-9a-f])", re.IGNORECASE),
    re.compile(r"\borbitcontrols\b", re.IGNORECASE),
    re.compile(
        r"\b(?:perspectivecamera|orthographiccamera|webglrenderer|"
        r"meshstandardmaterial|meshphongmaterial|boxgeometry|spheregeometry|buffergeometry)\b",
        re.IGNORECASE,
    ),
    re.compile(r"ثلاثي(?:ة)?\s+الأبعاد"),
)

_QUALITY_RUBRICS: dict[str, str] = {
    "threejs_3d": (
        "FINISHING & QUALITY CONTRACT [threejs_3d]:\n"
        '1. Importmap (~135 lines, no comments): `<script type="importmap">` before `<script type="module">`: '
        '{"imports":{"three":"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js",'
        '"three/addons/":"https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}\n'
        "2. r160 & Init: `BoxGeometry`, `SphereGeometry`, `CylinderGeometry`, `TorusGeometry`, `GridHelper` "
        "(no `Geometry`/`*BufferGeometry`), cam `(0,9,14)`, starfield, `AmbientLight`+`DirectionalLight`, "
        "`emissive`, `renderer.setSize(window.innerWidth, window.innerHeight)` + `updateProjectionMatrix()`. "
        "Start `requestAnimationFrame(animate)` in `init()`, ALWAYS calling `renderer.render(scene, camera)` "
        "even when `paused` (no early `return`); respawn at radius `>= 4` via `Math.hypot`.\n"
        "3. HUD: `html, body { margin: 0; height: 100%; overflow: hidden; }` (no `console.error`); "
        "1 top flex bar (`display:flex;justify-content:space-between`) or corners (`top-left`,`top-right`,`bottom-center`,`bottom-right`).\n"
        "4. Bridge: `window.AGENT_GAME` in `init()`: `getState()` (`{status,score,best,player,position,tick}`, "
        "no `Object3D`), `start()`, `restart()` (score=0), `move(direction)` (`position`/`player`), "
        "`forceCollect()`, `forceCollision()` (`'gameover'`), `forceWin()` (`'won'`; freeze won/gameover)."
    ),
    "web_game": (
        "FINISHING & QUALITY CONTRACT [web_game]:\n"
        "1. Canvas & Layout: Render a visible `<canvas>` with explicit non-zero size (>=64x64px; "
        "`html, body { margin: 0; height: 100%; }`), non-empty `<title>`, and zero console/page/network errors. "
        'Never use bare ES module imports without `<script type="importmap">`.\n'
        "2. Visual HUD & Controls: Provide a readable HTML HUD showing title, live score/status, controls legend, "
        "Start/Restart buttons, and visible mobile touch buttons (`[data-direction]`) at 390x844 when requested.\n"
        "3. Gameplay Loop: Keep input, clamped-dt state update, collision/scoring transitions, and render cleanly "
        "separated so repeated `restart()` never stacks duplicate loops or listeners.\n"
        "4. Deterministic Bridge: Expose `window.AGENT_GAME` synchronously on startup with `getState()` "
        "returning `{status, score, player, position, tick}`, `start()`, `restart()`, `move(direction)` "
        "deterministically updating `position`/`player`, plus `forceCollect()`/`forceCollision()`/`forceWin()` when relevant."
    ),
    "web_app": (
        "FINISHING & QUALITY CONTRACT [web_app]:\n"
        "1. Structure & Validity: Include a non-empty `<title>`, semantic accessible controls (`<button>`, "
        "explicitly labeled `<input>` fields with sensible `min`/`max` validation), and zero console/page/404 errors.\n"
        "2. State & Persistence: Wire real interactive state updates (start/pause/reset or CRUD flows), "
        "keyboard `Enter` activation on primary controls, and `localStorage` persistence surviving reload when requested.\n"
        "3. Responsive & Motion Polish: Ensure 390px mobile viewport has visible controls with zero horizontal "
        "overflow (`box-sizing: border-box`), and honor `@media (prefers-reduced-motion: reduce)` by disabling "
        "non-trivial transition/animation durations."
    ),
    "cli": (
        "FINISHING & QUALITY CONTRACT [cli]:\n"
        "1. Clean CLI Contract: Separate `argparse` flag parsing, pure domain logic, and deterministic stdout/stderr output.\n"
        "2. Exit Codes & Errors: `--help` and valid runs must exit `0`; invalid arguments, missing files, or bad inputs "
        "must print concise actionable diagnostics to `stderr` and exit non-zero without raw tracebacks.\n"
        "3. Edge Cases: Handle empty inputs, boundary counts, and UTF-8 text/paths deterministically."
    ),
    "api": (
        "FINISHING & QUALITY CONTRACT [api]:\n"
        "1. Explicit HTTP Contracts: Validate request payloads/params up front, returning structured `400`/`422` JSON "
        "errors on invalid input and accurate status codes (`200`/`201`/`204`/`404`) without unhandled `500` tracebacks.\n"
        "2. Testable Boundaries: Keep route handlers thin over deterministic domain/storage logic and verify both "
        "happy-path and invalid-input requests."
    ),
    "general": (
        "FINISHING & QUALITY CONTRACT [general]:\n"
        "1. Complete Delivery: Ship runnable, self-contained code with zero `TODO`/placeholder stubs or dead imports.\n"
        "2. Clear Boundaries & Verification: Keep module interfaces cohesive, handle empty/boundary/invalid inputs "
        "explicitly, and verify observable outputs against exact task requirements."
    ),
}

BROWSER_CANVAS_QUALITY_JS = r"""() => {
    const isVisible = (el) => {
        if (!el) return false;
        let cur = el;
        while (cur && cur.nodeType === 1) {
            const style = window.getComputedStyle(cur);
            if (!style || style.display === 'none' || style.visibility === 'hidden' || parseFloat(style.opacity || '1') <= 0) {
                return false;
            }
            cur = cur.parentElement;
        }
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    };
    const canvases = Array.from(document.querySelectorAll('canvas'));
    let maxWidth = 0;
    let maxHeight = 0;
    let visibleCount = 0;
    for (const canvas of canvases) {
        const hidden = !isVisible(canvas);
        const rect = canvas.getBoundingClientRect();
        const bufferOk = (typeof canvas.width !== 'number' || canvas.width > 0)
            && (typeof canvas.height !== 'number' || canvas.height > 0);
        const width = (!hidden && bufferOk) ? Math.round(rect.width) : 0;
        const height = (!hidden && bufferOk) ? Math.round(rect.height) : 0;
        if (width > 0 && height > 0) {
            visibleCount += 1;
            if (width > maxWidth) maxWidth = width;
            if (height > maxHeight) maxHeight = height;
        }
    }
    const hasImportMap = Boolean(document.querySelector('script[type="importmap" i]'));
    const controlSelector = (
        'button, input:not([type="hidden"]), select, textarea, '
        + '[role="button"], [data-direction], [data-move], [data-action], a[href]'
    );
    const interactiveControlCount = Array.from(document.querySelectorAll(controlSelector)).filter(isVisible).length;
    const ignoredHudTags = new Set(['CANVAS', 'SCRIPT', 'STYLE', 'LINK', 'META', 'NOSCRIPT', 'SVG', 'PATH', 'BR', 'HR']);
    const hudRoleSelector = (
        '[aria-live], [role="status"], [id*="hud" i], [class*="hud" i], '
        + '[id*="score" i], [class*="score" i], [id*="status" i], [class*="status" i], '
        + '[id*="overlay" i], [class*="overlay" i]'
    );
    const hudElements = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (ignoredHudTags.has(el.tagName) || !isVisible(el)) return false;
        const hasDirectText = Array.from(el.childNodes).some(
            (node) => node.nodeType === 3 && (node.textContent || '').trim().length > 0
        );
        return hasDirectText || el.matches(hudRoleSelector);
    });
    const overlapControls = Array.from(
        document.querySelectorAll('button, input:not([type="hidden"]), select, [role="button"]')
    ).filter(isVisible);
    const vw = window.innerWidth || document.documentElement.clientWidth || 1024;
    const vh = window.innerHeight || document.documentElement.clientHeight || 768;
    const positionedHudBlocks = Array.from(document.querySelectorAll('body *')).filter((el) => {
        if (ignoredHudTags.has(el.tagName) || !isVisible(el)) return false;
        const style = window.getComputedStyle(el);
        if (!style || (style.position !== 'fixed' && style.position !== 'absolute')) return false;
        const rect = el.getBoundingClientRect();
        return rect.width >= 20 && rect.height >= 14 && rect.width < vw * 0.92 && rect.height < vh * 0.85;
    });
    const hudCandidates = Array.from(new Set([...positionedHudBlocks, ...overlapControls]));
    const labelFor = (el) => {
        if (el.id) return `#${el.id}`;
        if (el.getAttribute('data-direction')) return `[data-direction="${el.getAttribute('data-direction')}"]`;
        if (el.classList && el.classList.length > 0) return `.${el.classList[0]}`;
        const txt = (el.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 14);
        const tag = el.tagName.toLowerCase();
        return txt ? `${tag}("${txt}")` : tag;
    };
    const isSharedBarParent = (parent) => {
        if (!parent) return false;
        const ps = window.getComputedStyle(parent);
        const disp = (ps && ps.display) || '';
        const cls = parent.getAttribute ? (parent.getAttribute('class') || '') : '';
        return disp.includes('flex') || disp.includes('grid')
            || /bar|controls|buttons|actions|group/i.test(`${parent.id || ''} ${cls}`);
    };
    let hudOverlapCount = 0;
    const hudOverlaps = [];
    for (let i = 0; i < hudCandidates.length; i += 1) {
        const a = hudCandidates[i];
        const ra = a.getBoundingClientRect();
        for (let j = i + 1; j < hudCandidates.length; j += 1) {
            const b = hudCandidates[j];
            if (a === b || a.contains(b) || b.contains(a)) continue;
            const rb = b.getBoundingClientRect();
            if (a.parentElement && a.parentElement === b.parentElement && isSharedBarParent(a.parentElement)) {
                if (Math.min(ra.right, rb.right) <= Math.max(ra.left, rb.left)
                    || Math.min(ra.bottom, rb.bottom) <= Math.max(ra.top, rb.top)) {
                    continue;
                }
            }
            const ix = Math.min(ra.right, rb.right) - Math.max(ra.left, rb.left);
            const iy = Math.min(ra.bottom, rb.bottom) - Math.max(ra.top, rb.top);
            if (ix > 6 && iy > 6 && (ix * iy) >= 48) {
                hudOverlapCount += 1;
                if (hudOverlaps.length < 4) {
                    hudOverlaps.push(`${labelFor(a)} vs ${labelFor(b)}`);
                }
            }
        }
    }
    const hasWebGL = canvases.some((c) => {
        try { return Boolean(c.getContext('webgl2') || c.getContext('webgl')); }
        catch { return false; }
    });
    return {
        count: canvases.length,
        maxWidth,
        maxHeight,
        visibleCount,
        hasImportMap,
        hasWebGL,
        hudElementCount: hudElements.length,
        interactiveControlCount,
        hudOverlapCount,
        hudOverlaps,
    };
}"""

_INTERACTION_REPAIR_HINTS: dict[str, str] = {
    "keyboard_movement": (
        "Fix `keyboard_movement`: ensure `window.AGENT_GAME.move(direction)` (e.g. `'up'`) and `ArrowUp`/WASD "
        "handlers work after `start()` and observably update `getState().position`, `getState().player`, or `getState().score`."
    ),
    "collection_updates_state": (
        "Fix `collection_updates_state`: expose `window.AGENT_GAME.forceCollect()` and ensure collecting an item "
        "increments `getState().score`, `getState().collected`, or `getState().energy`."
    ),
    "collision_game_over": (
        "Fix `collision_game_over`: expose `window.AGENT_GAME.forceCollision()` and set `getState().status` "
        "to `'gameover'` (or `'game-over'`/`'lost'`/`'dead'`) on obstacle collision."
    ),
    "restart_resets_state": (
        "Fix `restart_resets_state`: expose `window.AGENT_GAME.restart()` so `getState().score` resets to `0` "
        "and `getState().status` leaves `'gameover'` for `'playing'` or `'ready'`."
    ),
    "goal_win_state": (
        "Fix `goal_win_state`: expose `window.AGENT_GAME.forceWin()` and transition `getState().status` "
        "to `'won'` (or `'win'`/`'completed'`) when the win condition triggers."
    ),
    "score_persistence": (
        "Fix `score_persistence`: persist best score in `localStorage` (guarded with try/catch) and include "
        "`best` in `window.AGENT_GAME.getState()` before and after reload."
    ),
    "touch_control": (
        "Fix `touch_control`: render visible touch controls at 390x844 viewport (e.g. `[data-direction=\"up\"]` "
        "or `.touch-controls button`) that observably update `window.AGENT_GAME.getState()` on click."
    ),
    "timer_start_changes_visible_time": (
        "Fix `timer_start_changes_visible_time`: clicking Start must decrement the visible `MM:SS` countdown clock."
    ),
    "timer_pause_freezes_visible_time": (
        "Fix `timer_pause_freezes_visible_time`: clicking Pause must freeze the visible `MM:SS` countdown without resetting it."
    ),
    "timer_reset_restores_visible_time": (
        "Fix `timer_reset_restores_visible_time`: clicking Reset must restore the configured initial focus duration."
    ),
    "timer_phase_switches_and_counts_session": (
        "Fix `timer_phase_switches_and_counts_session`: completing a focus countdown must switch visible phase text "
        "to Break and increment a dedicated visible `Completed Sessions: N` counter."
    ),
    "timer_duration_configuration": (
        "Fix `timer_duration_configuration`: provide >=2 visible `<input type=\"number\" min=\"1\">` duration inputs "
        "whose valid change updates the visible `MM:SS` clock and rejects `< min` via `checkValidity()`."
    ),
    "settings_persistence": (
        "Fix `settings_persistence`: save updated numeric input values to `localStorage` on change/save and restore on reload."
    ),
    "keyboard_activation": (
        "Fix `keyboard_activation`: focusing the Start `<button>` and pressing `Enter` must toggle/activate it."
    ),
    "responsive_no_overflow": (
        "Fix `responsive_no_overflow`: eliminate horizontal overflow (`scrollWidth <= innerWidth`) and keep buttons visible at 390x844."
    ),
    "reduced_motion": (
        "Fix `reduced_motion`: add `@media (prefers-reduced-motion: reduce) { *, *::before, *::after "
        "{ animation-duration: 0.001ms !important; transition-duration: 0.001ms !important; } }`."
    ),
}


def _extract_semantic_text(contract_or_text: dict[str, Any] | str | None) -> str:
    if contract_or_text is None:
        return ""
    if isinstance(contract_or_text, str):
        return contract_or_text
    if not isinstance(contract_or_text, dict):
        return str(contract_or_text)
    parts: list[str] = []
    for field in _SEMANTIC_CONTRACT_FIELDS:
        raw = contract_or_text.get(field)
        if raw is None:
            continue
        items = raw if isinstance(raw, (list, tuple)) else (raw,)
        for item in items:
            if isinstance(item, dict):
                text = item.get("text") or item.get("description") or item.get("goal")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
            elif isinstance(item, str) and item.strip():
                parts.append(item)
    return " ".join(parts)


def detect_threejs_or_3d(contract_or_text: dict[str, Any] | str | None) -> bool:
    """Return True when contract or goal text targets Three.js, WebGL, or 3D browser scenes/games."""
    text = _extract_semantic_text(contract_or_text)
    if not text:
        return False
    return any(pattern.search(text) for pattern in _THREEJS_OR_3D_PATTERNS)


def detect_quality_domain(contract: dict[str, Any] | None, task_goal: str = "") -> str:
    """Map task contract/goal to one quality rubric domain."""
    if detect_threejs_or_3d(contract) or detect_threejs_or_3d(task_goal):
        return "threejs_3d"
    merged: dict[str, Any] = {}
    if isinstance(contract, dict):
        merged.update(contract)
    combined_goal = " ".join(
        part for part in (str(merged.get("goal") or "").strip(), str(task_goal or "").strip()) if part
    )
    merged["goal"] = combined_goal
    for list_field in ("requirements", "constraints"):
        values = merged.get(list_field)
        if isinstance(values, (list, tuple)):
            merged[list_field] = [
                item.get("text", "") if isinstance(item, dict) else str(item)
                for item in values
            ]
    project_kind = classify_project(merged)
    if project_kind in {"web_game", "web_app", "cli", "api"}:
        return project_kind
    return "general"


def quality_rubric_context(contract: dict[str, Any] | None, task_goal: str = "") -> str:
    """Return a compact (<1,300 chars) domain-tailored FINISHING & QUALITY CONTRACT."""
    domain = detect_quality_domain(contract, task_goal)
    return _QUALITY_RUBRICS[domain][:1299]


def build_six_angle_qa_checklist(domain: str = "general") -> str:
    """Return a compact (<=600 chars) HarrTest-inspired 6-angle adversarial QA checklist."""
    key = (str(domain or "general").strip().lower() or "general")[:20]
    visual_focus = (
        "separate HUD corners (0 overlap); `init()` renders scene while `paused`"
        if key in {"threejs_3d", "web_game"}
        else "clean layout with 0 control overlap or horizontal overflow"
    )
    hygiene_focus = (
        "`restart()` resets state with a single `requestAnimationFrame` loop"
        if key in {"threejs_3d", "web_game"}
        else "idempotent reset without duplicate timers or listeners"
    )
    checklist = (
        f"SIX-ANGLE QA CHECKLIST [{key}]:\n"
        "1. Functionality: Required actions/transitions observably update state.\n"
        "2. Preservation: Existing contracts, controls, and invariants remain intact.\n"
        "3. Interface/DOM Binding: Referenced IDs, imports, and `AGENT_GAME` hooks match.\n"
        "4. Error/Input Resilience: 0 console/page/404 errors; guard storage & inputs.\n"
        f"5. Visual/HUD Non-Overlap & Initial Render: Ensure {visual_focus}.\n"
        f"6. State Reset & Single-RAF Hygiene: Ensure {hygiene_focus}."
    )
    return checklist[:600]


def _string_errors(items: Any) -> list[str]:
    if not isinstance(items, (list, tuple)):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, dict):
            text = str(item.get("text") or item.get("evidence") or item.get("message") or "").strip()
        else:
            text = str(item or "").strip()
        if text:
            out.append(text)
    return out


def diagnose_browser_failures(snapshot: dict[str, Any]) -> list[str]:
    """Translate raw browser errors, canvas metrics, and failed checks into concrete Repairer hints."""
    if not isinstance(snapshot, dict):
        return []

    hints: list[str] = []

    def add_hint(text: str) -> None:
        if text and text not in hints:
            hints.append(text)

    console_errors = _string_errors(snapshot.get("console_errors"))
    page_errors = _string_errors(snapshot.get("page_errors"))
    network_errors = _string_errors(snapshot.get("network_errors"))
    raw_failures = snapshot.get("failures") if isinstance(snapshot.get("failures"), list) else []
    failure_codes = {
        str(item.get("code") or "")
        for item in raw_failures
        if isinstance(item, dict) and item.get("code")
    }
    failure_evidence = [
        str(item.get("evidence") or "")
        for item in raw_failures
        if isinstance(item, dict) and item.get("evidence")
    ]
    all_error_lines = console_errors + page_errors + failure_evidence
    combined_errors = "\n".join(all_error_lines)

    if re.search(r"failed to parse import map|invalid json", combined_errors, re.IGNORECASE):
        add_hint(
            'Fix `<script type="importmap">`: it must contain ONLY strict RFC-8259 JSON '
            '(double-quoted keys/strings, NO `//` comments, and NO trailing commas): '
            '`{"imports": {"three": "https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js"}}`.'
        )

    if re.search(
        r"failed to resolve module specifier|error resolving module specifier|"
        r"bare specifier|relative references must start with",
        combined_errors,
        re.IGNORECASE,
    ):
        add_hint(
            'Add `<script type="importmap">{"imports": {"three": '
            '"https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js", '
            '"three/addons/": "https://cdn.jsdelivr.net/npm/three@0.160.0/examples/jsm/"}}</script>` '
            'in `<head>` BEFORE any `<script type="module">` tag instead of bare module specifiers like `"three"`.'
        )

    if re.search(r"cannot use import statement outside a module", combined_errors, re.IGNORECASE):
        add_hint(
            'Use `<script type="module">` for ES `import` statements and place `<script type="importmap">` before it.'
        )

    legacy_buffer_geoms: list[str] = []
    for match in re.finditer(r"\b(?:THREE\.)?([A-Z][A-Za-z0-9]*)BufferGeometry\b", combined_errors):
        prefix = match.group(1)
        if prefix and prefix not in legacy_buffer_geoms:
            legacy_buffer_geoms.append(prefix)
    for prefix in legacy_buffer_geoms:
        add_hint(
            f"Replace removed legacy `THREE.{prefix}BufferGeometry` with modern Three.js r160 "
            f"`THREE.{prefix}Geometry` (`*BufferGeometry` aliases were removed in r155+)."
        )

    if re.search(r"\bTHREE\.Geometry\b|\bGeometry is not a constructor\b", combined_errors):
        add_hint(
            "Replace removed `THREE.Geometry` with `THREE.BufferGeometry` "
            "(or concrete r160 primitives such as `THREE.BoxGeometry` / `THREE.SphereGeometry`)."
        )

    if re.search(
        r"\bTHREE\.OrbitControls\b.*not a constructor|\bOrbitControls is not defined\b",
        combined_errors,
        re.IGNORECASE,
    ):
        add_hint(
            "Import `OrbitControls` from `'three/addons/controls/OrbitControls.js'` "
            "(mapped in `<script type=\"importmap\">`) instead of referencing `THREE.OrbitControls`."
        )

    if re.search(r"error creating webgl context|webgl.*not supported", combined_errors, re.IGNORECASE):
        add_hint(
            "Wrap `new THREE.WebGLRenderer(...)` in `try/catch` with a graceful canvas fallback so HUD and "
            "`window.AGENT_GAME` still initialize cleanly under constrained headless GPU environments."
        )

    runtime = snapshot.get("runtime_state") if isinstance(snapshot.get("runtime_state"), dict) else {}
    canvas_metrics = runtime.get("canvasMetrics") if isinstance(runtime.get("canvasMetrics"), dict) else None
    canvas_count = int(runtime.get("canvasCount") or (canvas_metrics or {}).get("count") or 0)
    zero_canvas_detected = "zero_size_canvas" in failure_codes or (
        canvas_metrics is not None
        and canvas_count >= 1
        and (
            float(canvas_metrics.get("maxWidth") or 0) < 64
            or float(canvas_metrics.get("maxHeight") or 0) < 64
        )
    )
    if "missing_webgl_context" in failure_codes:
        add_hint(
            "This contract requires real 3D Three.js WebGL rendering (`new THREE.WebGLRenderer()` with "
            "`<script type=\"importmap\">`), NOT a 2D `canvas.getContext('2d')` simulation. Keep the HTML/JS "
            "concise (~145 lines) and render a real Three.js 3D scene."
        )
    if console_errors and not page_errors:
        add_hint(
            "Eliminate `console_errors` (never use `console.error(...)` for gameplay/collision status messages; "
            f"use `console.log(...)` or HUD updates instead): {console_errors[0][:180]}"
        )
    if zero_canvas_detected:
        add_hint(
            "Fix zero-size `<canvas>`: set CSS `html, body { margin: 0; width: 100%; height: 100%; overflow: hidden; }`, "
            "ensure the canvas container has non-zero layout dimensions, and call "
            "`renderer.setSize(window.innerWidth, window.innerHeight)` (or set explicit canvas width/height >= 64px)."
        )

    if "missing_canvas" in failure_codes:
        add_hint(
            "Mount at least one rendered `<canvas>` element into `document.body` synchronously on load "
            "(e.g. `document.body.appendChild(renderer.domElement)`)."
        )

    if "blank_initial_canvas" in failure_codes or (
        canvas_metrics is not None and canvas_metrics.get("initialFrameBlank") is True
    ):
        add_hint(
            "Fix `blank_initial_canvas`: call `renderer.render(scene, camera)` and start "
            "`requestAnimationFrame(animate)` unconditionally inside `init()` so the 3D scene "
            "renders visibly on initial load even while `paused` (before Start is clicked)."
        )

    if "hud_layout_overlap" in failure_codes or (
        canvas_metrics is not None and int(canvas_metrics.get("hudOverlapCount", 0) or 0) > 0
    ):
        overlap_pairs: list[str] = []
        if canvas_metrics is not None and isinstance(canvas_metrics.get("hudOverlaps"), list):
            overlap_pairs = [str(item).strip() for item in canvas_metrics["hudOverlaps"] if str(item).strip()]
        if not overlap_pairs:
            for item in raw_failures:
                if isinstance(item, dict) and item.get("code") == "hud_layout_overlap":
                    ev = str(item.get("evidence") or "").strip()
                    if ":" in ev:
                        ev = ev.split(":", 1)[1].strip()
                    if ev:
                        overlap_pairs.append(ev)
        overlap_detail = ", ".join(overlap_pairs[:4]) if overlap_pairs else "overlapping HUD elements"
        add_hint(
            f"Fix `hud_layout_overlap` ({overlap_detail}): pin each positioned HUD panel to a separate viewport "
            "corner (`top-left`, `top-right`, `bottom-center`, `bottom-right`) or group sibling buttons in one "
            "`display: flex; gap: 8px` bar so HUD/control bounding boxes never intersect."
        )

    if "missing_game_bridge" in failure_codes:
        add_hint(
            "Expose `window.AGENT_GAME = { getState, start, restart, move, forceCollect, forceCollision, forceWin }` "
            "synchronously during initialization (verify no syntax/module error aborted script load), with "
            "`getState()` returning `{ status, score, player, position }`."
        )

    if "missing_title" in failure_codes:
        add_hint("Set a non-empty `<title>...</title>` in `<head>`.")

    if "source_dump" in failure_codes:
        add_hint(
            "Remove raw JavaScript source code or placeholder text from `<body>`; keep code inside `<script>` "
            "tags and render clean HTML UI/HUD elements."
        )

    failed_interactions: list[str] = []
    for item in snapshot.get("interaction_checks") or []:
        if isinstance(item, dict) and not item.get("passed") and item.get("name"):
            name = str(item["name"])
            if name not in failed_interactions:
                failed_interactions.append(name)
    for item in raw_failures:
        if not isinstance(item, dict):
            continue
        if item.get("code") in {"failed_interaction", "missing_interaction"}:
            evidence = str(item.get("evidence") or "")
            if ":" in evidence:
                name = evidence.rsplit(":", 1)[-1].strip()
                if name and name not in failed_interactions:
                    failed_interactions.append(name)
    for name in failed_interactions:
        if name in _INTERACTION_REPAIR_HINTS:
            add_hint(_INTERACTION_REPAIR_HINTS[name])
        else:
            add_hint(f"Ensure required browser interaction `{name}` executes and updates observable state.")

    if network_errors or "network_errors" in failure_codes:
        sample = network_errors[0] if network_errors else "HTTP >= 400 asset response"
        add_hint(
            f"Fix broken network/asset request (`{sample[:140]}`): ensure all referenced local `.js`/`.css`/asset "
            "paths exist relative to the HTML entrypoint or use verified CDN module URLs."
        )

    if not hints and (console_errors or page_errors or raw_failures):
        first_issue = (
            (page_errors[0] if page_errors else "")
            or (console_errors[0] if console_errors else "")
            or (failure_evidence[0] if failure_evidence else "browser verification failed")
        )
        add_hint(f"Resolve uncaught browser failure before re-verifying: {first_issue[:220]}")

    return hints
