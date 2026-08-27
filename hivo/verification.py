"""Contract-aware browser verification policies."""

from dataclasses import asdict, dataclass
import json
import re


@dataclass(frozen=True)
class WebVerificationProfile:
    kind: str
    require_title: bool
    require_canvas: bool
    require_game_bridge: bool
    required_interactions: tuple[str, ...]


def infer_web_profile(task_text: str, contract: dict | None = None) -> WebVerificationProfile:
    combined = f"{task_text} {json.dumps(contract or {}, ensure_ascii=False)}".lower()
    game = any(word in combined for word in ("game", "3d", "webgl", "three.js", "hovercraft"))
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
    return WebVerificationProfile(
        kind="game" if game else "web",
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
    if profile.require_canvas and int(runtime.get("canvasCount") or 0) < 1:
        fail("missing_canvas", "a 3D/game contract requires at least one rendered canvas")
    bridge = runtime.get("gameBridge") or runtime.get("debugState")
    if profile.require_game_bridge and not bridge:
        fail("missing_game_bridge", "window.__AGENT_GAME__ verification bridge is unavailable")

    interactions = {str(item.get("name")): item for item in snapshot.get("interaction_checks") or []}
    for name in profile.required_interactions:
        check = interactions.get(name)
        if not check:
            fail("missing_interaction", f"required browser interaction did not run: {name}")
        elif not check.get("passed"):
            fail("failed_interaction", f"browser interaction failed: {name}")

    return {
        **snapshot,
        "passed": not failures,
        "failures": failures,
        "verification_profile": asdict(profile),
    }
