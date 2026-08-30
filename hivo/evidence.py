"""Deterministic interpretation of tool evidence."""

import json
import re


VERIFICATION_TOOLS = frozenset({"run_file", "run_command", "verify_web_app"})
MUTATION_TOOLS = frozenset({"write_file", "edit_file", "edit_file_range"})


def result_not_applicable(result: object) -> bool:
    return str(result).strip().lower().startswith("[not_applicable]")


def result_is_tool_rejection(result: object) -> bool:
    """Identify orchestrator/sandbox refusal, not a failure inside the app."""
    lower = str(result).strip().lower()
    return lower.startswith((
        "error: command refused:",
        "error: tool ",
        "error: falsifier is read-only",
        "error: repairer may only",
        "error: malformed tool call:",
    ))


def result_failed(result: object) -> bool:
    text = str(result).strip()
    lower = text.lower()
    if text.startswith("{"):
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict) and payload.get("passed") is False:
            return True
    if lower.startswith((
        "error:", "error writing file:", "error reading file:",
        "tool error:", "compile error:", "traceback",
    )):
        return True
    exit_code = re.search(r"\[exit_code=(\d+)\]", lower)
    if exit_code and int(exit_code.group(1)) != 0:
        return True
    concrete_failures = re.search(r"\b([1-9]\d*)\s+(?:failed|failure|failures)\b", lower)
    if concrete_failures:
        return True
    if re.search(r"\bfailures?\s*[:=]\s*[1-9]\d*\b", lower):
        return True
    if '"passed": false' in lower or "'passed': false" in lower:
        return True
    return any(term in lower for term in ("syntaxerror", "assertionerror", "uncaught exception"))


def mutation_failure_record(tool: object, target: object, result: object, role: object = None) -> dict | None:
    """Classify one deterministic failed source mutation without copying its payload."""
    tool_name = str(tool)
    if tool_name not in MUTATION_TOOLS or not result_failed(result):
        return None
    text = " ".join(str(result).strip().split())
    lower = text.casefold()
    if any(marker in lower for marker in (
        "syntax validation failed", "syntaxerror", "parse error", "unexpected token",
        "unexpected identifier",
    )):
        category = "SYNTAX_INVALID_MUTATION"
    elif any(marker in lower for marker in (
        "outside the workspace", "outside workspace", "command refused", "forbidden mutation",
        "not allowed", "repairer cannot", "unavailable for role", "unavailable under the active",
    )):
        category = "SAFETY_REJECTED_MUTATION"
    elif any(marker in lower for marker in (
        "error writing file:", "error reading file:", "backup failed", "i/o error",
        "oserror", "operating system error", "permission denied",
    )):
        category = "ENVIRONMENT_FAILURE"
    elif any(marker in lower for marker in (
        "file does not exist", "target does not exist", "no such file or directory",
        "missing target",
    )):
        category = "MISSING_TARGET"
    elif any(marker in lower for marker in (
        "invalid line range", "exact replacement(s), found 0", "exact text not found",
        "stale target", "stale context", "context does not match", "patch context",
    )):
        category = "STALE_TARGET"
    else:
        category = "INVALID_MUTATION"
    record = {
        "kind": "mutation_failure",
        "tool": tool_name,
        "category": category,
        "target": " ".join(str(target).strip().split())[:240],
        "deterministic": True,
        "status": "FAIL",
        "summary": text[:700],
        "count": 1,
    }
    if role is not None:
        record["role"] = str(role)
    return record


def latest_verification_evidence(evidence: list[dict]) -> list[dict]:
    """Keep only the newest executable verification per tool and target."""
    latest: dict[tuple[str, str], tuple[int, dict]] = {}
    for index, item in enumerate(evidence):
        tool = str(item.get("tool", ""))
        if tool not in VERIFICATION_TOOLS or result_not_applicable(item.get("result", "")):
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
                if result_failed(item.get("result", ""))
                and not result_is_tool_rejection(item.get("result", ""))]
    failures.extend(item for item in evidence
                    if item.get("tool") == "malformed"
                    and not result_is_tool_rejection(item.get("result", "")))
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
