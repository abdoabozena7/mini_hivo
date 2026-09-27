"""Deterministic verifier preflight and failure attribution for Experiment 6."""

import json
import os
import re
import shutil
from pathlib import Path


TEST_FAILED = "TEST_FAILED"
VERIFIER_UNAVAILABLE = "VERIFIER_UNAVAILABLE"
VERIFICATION_NOT_APPLICABLE = "VERIFICATION_NOT_APPLICABLE"
READY = "READY"


def preflight_command(parts, workspace, *, platform=None, which=None):
    """Resolve an allowlisted command without changing its requested operation."""
    platform = os.name if platform is None else platform
    which = shutil.which if which is None else which
    parts = list(parts)
    executable = Path(parts[0]).stem.casefold()
    if executable == "npm" and len(parts) > 1 and parts[1] in {"test", "run"}:
        package_path = Path(workspace) / "package.json"
        if not package_path.is_file():
            return {"status": VERIFICATION_NOT_APPLICABLE,
                    "reason": "package.json is absent", "command": parts}
        try:
            package = json.loads(package_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            return {"status": VERIFIER_UNAVAILABLE,
                    "reason": f"package.json cannot be read: {exc}", "command": parts}
        script = "test" if parts[1] == "test" else (parts[2] if len(parts) > 2 else "")
        if not script or not isinstance(package.get("scripts"), dict) or not package["scripts"].get(script):
            return {"status": VERIFICATION_NOT_APPLICABLE,
                    "reason": f"package.json has no {script or 'requested'} script", "command": parts}
    candidates = [parts[0]]
    if platform == "nt" and executable in {"npm", "npx"}:
        candidates = [executable + ".cmd", executable + ".exe"]
    resolved = next((match for name in candidates if (match := which(name))), None)
    if not resolved:
        return {"status": VERIFIER_UNAVAILABLE,
                "reason": f"executable {parts[0]} is unavailable", "command": parts}
    if executable in {"npm", "npx"}:
        node_candidates = ["node.exe", "node"] if platform == "nt" else ["node"]
        if not any(which(name) for name in node_candidates):
            return {"status": VERIFIER_UNAVAILABLE,
                    "reason": "Node.js executable is unavailable", "command": parts,
                    "resolved_executable": resolved}
    return {"status": READY, "reason": "executable resolved",
            "command": [resolved, *parts[1:]], "resolved_executable": resolved}


def command_result(result, *, launch_error=None):
    if launch_error is not None:
        return {"status": VERIFIER_UNAVAILABLE, "reason": str(launch_error)}
    return {"status": TEST_FAILED if result.returncode else "PASS",
            "exit_code": result.returncode}


def _preexisting_bridge_missing(transaction, workspace, path):
    if not transaction or not workspace:
        return False
    target = (Path(workspace) / path).resolve()
    snapshot = transaction.get("files", {}).get(str(target))
    if not snapshot or not snapshot.get("existed") or snapshot.get("content") is None:
        return False
    return b"AGENT_GAME" not in snapshot["content"]


def classify_observation(item, *, transaction=None, workspace=None):
    """Classify one verification observation; unknown failures remain defects."""
    tool = str(item.get("tool", ""))
    if tool not in {"run_command", "run_file", "verify_web_app"}:
        return None
    raw = str(item.get("result", ""))
    lower = raw.casefold()
    if lower.startswith(("error: command refused:", "error: tool ",
                         "error: malformed tool call:")):
        return None
    if lower.startswith("[not_applicable]"):
        return VERIFICATION_NOT_APPLICABLE
    if "verifier_unavailable" in lower or re.search(r"\[winerror 2\]|required interpreter/compiler not found", lower):
        return VERIFIER_UNAVAILABLE
    if raw.startswith("{"):
        try:
            payload = json.loads(raw)
        except ValueError:
            payload = None
        if isinstance(payload, dict):
            return classify_browser_result(payload, transaction=transaction,
                                           workspace=workspace)
    match = re.search(r"\[exit_code=(\d+)\]", lower)
    if match:
        return TEST_FAILED if int(match.group(1)) else "PASS"
    if lower.startswith(("error:", "tool error:", "compile error:", "traceback")):
        return TEST_FAILED
    return "PASS"


def classify_browser_result(result, *, transaction=None, workspace=None):
    if result.get("environment_error") is True:
        return VERIFIER_UNAVAILABLE
    if result.get("passed") is True:
        return "PASS"
    failures = result.get("failures") or []
    codes = {str(item.get("code")) for item in failures if isinstance(item, dict)}
    checks = result.get("interaction_checks") or []
    if ("missing_game_bridge" in codes
            and codes <= {"missing_game_bridge", "missing_interaction"}
            and not checks
            and _preexisting_bridge_missing(
                transaction, workspace,
                result.get("resolved_entrypoint") or result.get("entry_path") or "",
            )):
        return VERIFIER_UNAVAILABLE
    return TEST_FAILED


def classify_failed_gate(gate, builder, falsifier, browser, *, transaction=None, workspace=None):
    """Return a non-defect blocker only when no executable defect was seen."""
    if gate.get("passed"):
        return None
    permitted_checks = {"executable_failures", "executable_verification",
                        "browser_contract", "verification_evidence", "verification_aggregation"}
    if any(item.get("name") not in permitted_checks
           for item in gate.get("deterministic_failures", []) if isinstance(item, dict)):
        return None
    observations = [item for source in (builder, falsifier) if isinstance(source, dict)
                    for key in ("tool_evidence", "verification_evidence")
                    for item in source.get(key, []) or [] if isinstance(item, dict)]
    statuses = [classify_observation(item, transaction=transaction, workspace=workspace)
                for item in observations]
    if isinstance(browser, dict) and browser.get("verification_status") != "SKIPPED_NOT_APPLICABLE":
        statuses.append(classify_browser_result(browser, transaction=transaction,
                                                workspace=workspace))
    statuses = [status for status in statuses if status]
    if TEST_FAILED in statuses:
        return None
    if VERIFIER_UNAVAILABLE in statuses:
        return VERIFIER_UNAVAILABLE
    if VERIFICATION_NOT_APPLICABLE in statuses or not statuses:
        return VERIFICATION_NOT_APPLICABLE
    return None
