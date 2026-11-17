"""Controller-owned browser responsibility projections, not mutation authority.

Only recognized game child assignments on the ordinary greenfield route are
narrowed. Unknown assignments retain full-source verification. Root verification
retains the complete source contract. Existing approved-contract routes opt out.
"""
import copy
from dataclasses import replace
import re

from hivo.verification import infer_web_profile


PATTERNS = {
    "keyboard_movement": r"\b(?:movement|move|keyboard|arrow|wasd|input handling|start)\b",
    "collection_updates_state": r"\b(?:collect(?:s|ing|ion)?|scoring|score increases|pickup)\b",
    "collision_game_over": r"\b(?:collision|collid\w*|obstacle|game[- ]over)\b",
    "restart_resets_state": r"\b(?:restart|reset(?:s)? (?:the )?round)\b",
    "score_persistence": r"\b(?:persist\w*|localstorage|best score|high score)\b",
    "touch_control": r"\b(?:touch|mobile controls)\b",
    "goal_win_state": r"\b(?:win(?:ning)?|won|100 points|delivery complete)\b",
}
# Recognize complete declared clauses, not any sentence containing one keyword.
# Unknown conjunctions fall back to the full source obligations. In particular,
# 'freeze movement and scoring' is a terminal duty, not collection ownership.
CLAUSES = {
    "keyboard_movement": r"(?:keyboard|player) movement works(?: inside arena bounds)?\.?",
    "collection_updates_state": r"(?:collecting coins|coin collection) updates (?:the )?score\.?",
    "collision_game_over": r"(?:obstacle collision (?:causes|triggers) game over|game over freezes movement and scoring)\.?",
    "restart_resets_state": r"restart resets (?:the )?round\.?",
    "score_persistence": r"(?:best|high) score persists across reload\.?",
    "touch_control": r"touch controls work\.?",
    "goal_win_state": r"winning stops movement and scoring\.?",
}
FOUNDATION = re.compile(
    r"(?:the )?(?:standalone )?(?:page|html|document|canvas|title) "
    r"(?:has (?:a )?title and (?:a )?canvas|"
    r"(?:loads|opens|renders)(?: correctly| without (?:browser|page) errors)?|is visible)\.?", re.I)


def _strings(values):
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v.strip()]


def scope_contract(task, contract, source_contract):
    """Copy a verification-only projection; never alter task/gate authority."""
    result = copy.deepcopy(contract or {})
    result.pop("child_browser_scope", None)
    result.pop("browser_root_contract", None)
    result.pop("browser_fallback_contract", None)
    full_source = {key: copy.deepcopy(source_contract[key]) for key in
                   ("goal", "original_goal", "requirements", "success_criteria", "constraints")
                   if isinstance(source_contract, dict) and key in source_contract}
    if (task.get("execution_contract_id") or task.get("execution_contract_child")
            or result.get("execution_contract_id") or result.get("execution_contract_child")):
        return result
    if str(task.get("id")) == "ROOT":
        if isinstance(source_contract, dict) and source_contract:
            result["browser_root_contract"] = full_source
            result["verification_requirements"] = list(dict.fromkeys(
                _strings(result.get("verification_requirements", [])) + _strings(source_contract.get("requirements", []))))
        return result
    # Production make_task uses "parent"; parent_id is a legacy fixture/ledger
    # spelling. An explicit canonical value wins, including None at a root.
    parent = task.get("parent") if "parent" in task else task.get("parent_id")
    conflicting_parent = ("parent" in task and "parent_id" in task
                          and task.get("parent") != task.get("parent_id"))
    if not parent or task.get("children") or task.get("kind") == "integration":
        return result
    if not _strings(full_source.get("requirements")):
        return result  # Do not narrow without a retained authoritative root.
    kind = infer_web_profile(task.get("goal", ""), source_contract or {}, classification_policy="field_scoped").kind
    if kind != "game":
        return result
    result["browser_fallback_contract"] = full_source
    if conflicting_parent:
        return result  # Ambiguous lineage must not reduce verification duties.
    conditions = _strings(task.get("done_when"))
    if not conditions or len(conditions) != len(task.get("done_when", [])):
        return result
    if re.search(r"\b(?:complete|entire|all requirements)\b", str(task.get("goal", "")), re.I):
        return result
    required = set()
    bridge = False
    for condition in conditions:
        names = {name for name, pattern in CLAUSES.items() if re.fullmatch(pattern, condition.strip(), re.I)}
        explicit_bridge = bool(re.fullmatch(r"expose AGENT_GAME with getState\(\)\.?", condition.strip(), re.I))
        if not names and not explicit_bridge and not FOUNDATION.fullmatch(condition.strip()):
            return result  # Unsupported prose cannot silently reduce checks.
        required.update(names)
        bridge = bridge or explicit_bridge
    # Explicit actions in the local goal also belong to this child; product
    # names ('Coin Courier') and generic 'game state' are not behavior claims.
    for name, pattern in PATTERNS.items():
        if re.search(pattern, str(task.get("goal", "")), re.I):
            required.add(name)
    result["child_browser_scope"] = {
        "version": 1, "task_id": str(task.get("id")), "goal": task.get("goal", ""),
        "requirements": conditions, "kind": kind,
        "required_interactions": sorted(required), "require_game_bridge": bridge or bool(required),
    }
    return result


def target_key(value):
    return str(value or "").replace("\\", "/").removeprefix("./").casefold()


def scoped_profile(goal, contract, *, classification_policy="current", completed_profiles=None, target=None):
    """Select obligations; completed prior behaviors remain fresh check duties."""
    contract = contract or {}
    full = copy.deepcopy(contract)
    root_source = contract.get("browser_root_contract")
    source = root_source or contract.get("browser_fallback_contract")
    if isinstance(source, dict):
        # Add original requirements rather than replacing the current duties.
        full.update(source)
        for field in ("requirements", "success_criteria", "constraints"):
            full[field] = list(dict.fromkeys(_strings(contract.get(field, [])) + _strings(source.get(field, []))))
    profile = infer_web_profile(goal, full, classification_policy=classification_policy)
    scope = contract.get("child_browser_scope")
    if (not root_source and isinstance(scope, dict) and scope.get("version") == 1
            and scope.get("kind") == "game" and scope.get("goal") == contract.get("goal")
            and scope.get("task_id") == str(contract.get("task_id"))
            and scope.get("requirements") == contract.get("requirements")
            and bool(_strings(scope.get("requirements")))
            and isinstance(scope.get("require_game_bridge"), bool)
            and isinstance(scope.get("required_interactions"), list)
            and all(name in PATTERNS for name in scope["required_interactions"])):
        profile = replace(profile, kind="game", require_canvas=True,
                          require_game_bridge=scope["require_game_bridge"],
                          required_interactions=tuple(scope["required_interactions"]))
    previous = (completed_profiles or {}).get(target_key(target))
    if isinstance(previous, dict) and previous.get("kind") == profile.kind:
        profile = replace(profile,
            require_title=profile.require_title or previous.get("require_title", False),
            require_canvas=profile.require_canvas or previous.get("require_canvas", False),
            require_game_bridge=profile.require_game_bridge or previous.get("require_game_bridge", False),
            required_interactions=tuple(dict.fromkeys(profile.required_interactions + tuple(previous.get("required_interactions", [])))))
    return profile


def retain_committed_profile(registry, result):
    """Record only accepted child outcomes; Worker 'done' alone is insufficient."""
    browser = result.get("browser") or {}
    if (result.get("status") != "done" or (result.get("gate") or {}).get("passed") is not True
            or browser.get("passed") is not True or not isinstance(result.get("changed_files"), (list, tuple))):
        return
    profile = browser.get("verification_profile")
    target = browser.get("resolved_entrypoint") or browser.get("entry_path")
    if not target or not isinstance(profile, dict) or profile.get("kind") != "game":
        return
    # Never delete older duties if a caller supplies a smaller profile.
    prior = registry.get(target_key(target), {})
    retained = copy.deepcopy(profile)
    retained["required_interactions"] = list(dict.fromkeys(
        list(prior.get("required_interactions", [])) + list(profile.get("required_interactions", []))))
    for flag in ("require_title", "require_canvas", "require_game_bridge"):
        retained[flag] = bool(profile.get(flag) or prior.get(flag))
    registry[target_key(target)] = retained
