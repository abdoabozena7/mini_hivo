"""Deterministic interpretation of tool evidence."""

import re


VERIFICATION_TOOLS = frozenset({"run_file", "run_command", "verify_web_app"})


def result_failed(result: object) -> bool:
    text = str(result).strip()
    lower = text.lower()
    if lower.startswith(("error:", "tool error:", "compile error:", "traceback")):
        return True
    exit_code = re.search(r"\[exit_code=(\d+)\]", lower)
    if exit_code and int(exit_code.group(1)) != 0:
        return True
    if '"passed": false' in lower or "'passed': false" in lower:
        return True
    return any(term in lower for term in ("syntaxerror", "assertionerror", "uncaught exception"))


def latest_verification_evidence(evidence: list[dict]) -> list[dict]:
    """Keep only the newest executable verification per tool and target."""
    latest: dict[tuple[str, str], tuple[int, dict]] = {}
    for index, item in enumerate(evidence):
        tool = str(item.get("tool", ""))
        if tool not in VERIFICATION_TOOLS:
            continue
        key = (tool, str(item.get("target", "-")))
        latest[key] = (index, item)
    return [item for _index, item in sorted(latest.values(), key=lambda pair: pair[0])]


def unresolved_tool_failures(evidence: list[dict]) -> list[dict]:
    """Return failures that are still true at the newest verification point.

    Failed exact edits are recoverable control-flow events: they do not change
    a file and must not poison a later successful executable verification.
    """
    failures = [item for item in latest_verification_evidence(evidence)
                if result_failed(item.get("result", ""))]
    failures.extend(item for item in evidence if item.get("tool") == "malformed")
    return failures


def evidence_for_review(evidence: list[dict], limit: int = 8) -> list[dict]:
    """Project raw history into current, non-misleading review evidence."""
    latest_ids = {id(item) for item in latest_verification_evidence(evidence)}
    projected = []
    for item in evidence:
        tool = item.get("tool")
        if tool in VERIFICATION_TOOLS and id(item) not in latest_ids:
            continue
        if tool not in VERIFICATION_TOOLS and result_failed(item.get("result", "")):
            continue
        projected.append(item)
    return projected[-limit:]
