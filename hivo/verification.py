"""Contract-aware browser verification policies."""

from dataclasses import asdict, dataclass
import json
import re

from hivo.quality_rubric import diagnose_browser_failures


GAME_BRIDGE_NAME = "AGENT_GAME"
GAME_BRIDGE_EXPRESSION = f"window.{GAME_BRIDGE_NAME}"


@dataclass(frozen=True)
class WebVerificationProfile:
    kind: str
    require_title: bool
    require_canvas: bool
    require_game_bridge: bool
    required_interactions: tuple[str, ...]


_INTERACTION_EXPECTATIONS = {
    "keyboard_movement": "Calling window.AGENT_GAME.start() then move('up') (or ArrowUp) must observably change getState().player or getState().position.",
    "collection_updates_state": "window.AGENT_GAME.forceCollect() must increment getState().score, getState().collected, or getState().energy.",
    "collision_game_over": "window.AGENT_GAME.forceCollision() must set getState().status to 'gameover' (or 'game-over'/'game_over').",
    "restart_resets_state": "window.AGENT_GAME.restart() must reset getState().score to 0 and set status out of gameover (e.g. 'playing' or 'ready').",
    "goal_win_state": "window.AGENT_GAME.forceWin() must unconditionally transition getState().status to 'won' (even right after restart()).",
    "score_persistence": "Best score must be persisted in localStorage and exposed as numeric getState().best across page reload.",
    "touch_control": "At 390x844 mobile viewport, a visible touch control ([data-direction] or .touch-controls button) must update getState() on click.",
    "timer_start_changes_visible_time": "Start must make the visible MM:SS countdown decrease under an advanced browser clock.",
    "timer_pause_freezes_visible_time": "Pause must freeze the already-started visible countdown without resetting it.",
    "timer_reset_restores_visible_time": "Reset must restore the configured phase duration and remain usable after Start/Pause.",
    "timer_phase_switches_and_counts_session": (
        "After one complete displayed focus duration, the visible phase label must change to Break and a dedicated "
        "visible label such as 'Completed Sessions: 0' must increment to 1. A current-session ordinal inside status "
        "text is not a completed-session counter."
    ),
    "timer_duration_configuration": (
        "Provide at least two visible numeric duration inputs. Applying a valid Focus value must update the visible "
        "clock, and a value below a positive min bound must fail native validity."
    ),
    "settings_persistence": "A changed visible numeric setting must survive change/blur, optional Save/Apply, and reload.",
    "keyboard_activation": "Focusing the primary Start button and pressing Enter must activate it.",
    "responsive_no_overflow": "At 390px width, controls must remain visible with no horizontal overflow.",
    "reduced_motion": "prefers-reduced-motion must disable non-trivial animation and transition motion.",
}


def interaction_expectations(profile: WebVerificationProfile) -> tuple[str, ...]:
    """Human-readable contract observables for a weak builder before it edits."""
    return tuple(
        _INTERACTION_EXPECTATIONS[name]
        for name in profile.required_interactions
        if name in _INTERACTION_EXPECTATIONS
    )


def _profile_semantic_text(task_text: str, contract: dict | None) -> str:
    """Project-type evidence only; authority IDs, hashes and provenance are data."""
    source = contract if isinstance(contract, dict) else {}
    parts = [str(task_text or "")]
    for field in ("goal", "original_goal", "requirements", "success_criteria",
                  "allowed_mutation_paths", "allowed_inspection_paths", "target_paths",
                  "integration_test_target", "verification_target", "entrypoint"):
        value = source.get(field)
        values = value if isinstance(value, (list, tuple)) else [value]
        for item in values:
            if isinstance(item, dict) and field in {"requirements", "success_criteria"}:
                item = item.get("text")
            if isinstance(item, str):
                parts.append(item)
    return " ".join(parts).lower()


def infer_web_profile(task_text: str, contract: dict | None = None,
                      *, classification_policy: str = "current") -> WebVerificationProfile:
    if classification_policy == "current":
        combined = f"{task_text} {json.dumps(contract or {}, ensure_ascii=False)}".lower()
    elif classification_policy == "field_scoped":
        combined = _profile_semantic_text(task_text, contract)
    else:
        raise ValueError("unknown verification classification policy")
    game = any(word in combined for word in (
        "game", "3d", "webgl", "three.js", "threejs", "orbitcontrols", "hovercraft",
    ))
    timer = not game and any(word in combined for word in (
        "timer", "countdown", "pomodoro", "focus timer", "مؤقت", "عد تنازلي",
    ))
    required: list[str] = []
    if game:
        required.append("keyboard_movement")
        if any(word in combined for word in ("collision", "barrier", "obstacle", "avoid")):
            required.append("collision_game_over")
        if any(word in combined for word in ("collect", "energy", "pickup", "coin")):
            required.append("collection_updates_state")
        if any(word in combined for word in ("restart", "game-over", "game over", "start state")):
            required.append("restart_resets_state")
        if any(word in combined for word in ("win", "won", "goal", "finish")):
            required.append("goal_win_state")
        if any(word in combined for word in ("best score", "high score", "persist", "localstorage")):
            required.append("score_persistence")
        if any(word in combined for word in ("touch", "mobile", "responsive controls")):
            required.append("touch_control")
    elif timer:
        required.extend((
            "timer_start_changes_visible_time",
            "timer_pause_freezes_visible_time",
            "timer_reset_restores_visible_time",
        ))
        if any(word in combined for word in (
            "configurable", "focus and break durations", "duration setting", "duration settings",
            "sensible validation", "مدة التركيز", "مدة الاستراحة",
        )):
            required.append("timer_duration_configuration")
        if any(word in combined for word in (
            "phase switch", "phase switching", "automatic focus", "automatic break",
            "completed-session", "completed session", "session count", "cycle count",
            "تبديل المرحلة", "الجلسات المكتملة",
        )):
            required.append("timer_phase_switches_and_counts_session")
        if any(word in combined for word in ("persist", "localstorage", "save settings", "حفظ")):
            required.append("settings_persistence")
        if any(word in combined for word in ("keyboard", "accessible", "accessibility", "لوحة المفاتيح")):
            required.append("keyboard_activation")
        if any(word in combined for word in ("responsive", "mobile", "متجاوب")):
            required.append("responsive_no_overflow")
        if any(word in combined for word in ("reduced-motion", "reduced motion", "تقليل الحركة")):
            required.append("reduced_motion")
    return WebVerificationProfile(
        kind="game" if game else "timer" if timer else "web",
        require_title=True,
        require_canvas=game,
        require_game_bridge=game,
        required_interactions=tuple(dict.fromkeys(required)),
    )


def _looks_like_source_dump(text: str) -> bool:
    stripped = text.strip()
    lower = stripped.lower()
    if any(marker in lower for marker in ("placeholder/assumed context", "assumed context", "placeholder")):
        return True
    if stripped.startswith(("//", "/*", "const ", "let ", "function ")):
        return True
    code_signals = sum(bool(re.search(pattern, stripped)) for pattern in (
        r"\bconst\s+\w+\s*=", r"\blet\s+\w+\s*=", r"\bfunction\s+\w+\s*\(", r"=>\s*\{",
    ))
    return code_signals >= 3


def evaluate_web_snapshot(snapshot: dict, profile: WebVerificationProfile) -> dict:
    failures: list[dict[str, str]] = []

    def fail(code: str, evidence: str) -> None:
        failures.append({"code": code, "evidence": evidence})

    for key in ("console_errors", "page_errors", "network_errors"):
        values = snapshot.get(key) or []
        if values:
            fail(key, json.dumps(values, ensure_ascii=False)[:700])

    title = str(snapshot.get("title") or "").strip()
    if profile.require_title and not title:
        fail("missing_title", "document.title is empty")

    text = str(snapshot.get("text") or "")
    if _looks_like_source_dump(text):
        fail("source_dump", "the rendered body looks like source code or placeholder content")

    runtime = snapshot.get("runtime_state") or {}
    canvas_count = int(runtime.get("canvasCount") or 0)
    canvas_metrics = runtime.get("canvasMetrics")
    if profile.require_canvas and canvas_count < 1:
        fail("missing_canvas", "a 3D/game contract requires at least one rendered canvas")
    elif profile.require_canvas and canvas_count >= 1 and isinstance(canvas_metrics, dict):
        max_width = float(canvas_metrics.get("maxWidth") or 0)
        max_height = float(canvas_metrics.get("maxHeight") or 0)
        if max_width < 64 or max_height < 64:
            fail(
                "zero_size_canvas",
                f"rendered canvas dimensions are too small ({max_width:g}x{max_height:g}px; expected >= 64x64px)",
            )
        if (
            canvas_metrics.get("requiresThreeWebGL") is True
            and canvas_metrics.get("hasWebGL") is False
            and not canvas_metrics.get("hasImportMap")
        ):
            fail(
                "missing_webgl_context",
                "a Three.js/3D WebGL contract cannot be satisfied by a 2D canvas without Three.js/WebGL",
            )
    bridge = runtime.get("gameBridge") or runtime.get("debugState")
    if profile.require_game_bridge and not bridge:
        fail("missing_game_bridge", f"{GAME_BRIDGE_EXPRESSION} verification bridge is unavailable")

    interactions = {str(item.get("name")): item for item in snapshot.get("interaction_checks") or []}
    for name in profile.required_interactions:
        check = interactions.get(name)
        if not check:
            fail("missing_interaction", f"required browser interaction did not run: {name}")
        elif not check.get("passed"):
            fail("failed_interaction", f"browser interaction failed: {name}")

    result = {
        **snapshot,
        "passed": not failures,
        "failures": failures,
        "verification_profile": asdict(profile),
    }
    if failures:
        result["repair_hints"] = diagnose_browser_failures(result)
    else:
        result.pop("repair_hints", None)
    return result
