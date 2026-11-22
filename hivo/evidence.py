"""Deterministic interpretation of tool evidence."""

import hashlib
import json
import re


VERIFICATION_TOOLS = frozenset({"run_file", "run_command", "verify_web_app"})
MUTATION_TOOLS = frozenset({"write_file", "edit_file", "edit_file_range"})


def structured_verification_outcome(payload: dict) -> str | None:
    statuses = {
        str(payload[key]).strip().upper()
        for key in ("verification_status", "status", "result")
        if payload.get(key) is not None and str(payload[key]).strip()
    }
    if payload.get("passed") is False or statuses & {"FAIL", "FAILED", "FAILURE"}:
        return "FAIL"
    if statuses - {"PASS", "PASSED", "SUCCESS", "SUCCEEDED"}:
        return None
    return "PASS" if statuses or payload.get("passed") is True else None


def project_tool_evidence_result(tool: str, result: object, limit: int = 1600) -> str:
    """Bound display text without turning clipped verification JSON into proof.

    Outcome, profile and identity fields are retained exactly or explicitly
    unavailable. Full tool output remains in the tool transcript/event store.
    """
    if tool not in VERIFICATION_TOOLS:
        return str(result)[:limit]
    text = json.dumps(result, ensure_ascii=False) if isinstance(result, dict) else str(result)
    try:
        payload = result if isinstance(result, dict) else json.loads(text)
    except (TypeError, ValueError):
        payload = None
    if len(text) <= limit:
        return text
    summary = {"evidence_summary": True,
               "source_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}
    if isinstance(payload, dict):
        # No shortened identifiers, targets or required-interaction sets.
        for key in (
            "passed", "verification_status", "status", "environment_error", "syntax_failure",
            "resolved_entrypoint", "entry_path", "requested_from_node", "verification_profile",
            "interaction_checks", "authority_id", "verification_id", "oracle_id", "oracle_hash",
            "receipt_identity", "receipt_channel", "execution_channel", "route_type",
            "authority_type", "plan_id", "plan_hash", "coverage_hash", "subject_hash",
        ):
            if key in payload:
                summary[key] = payload[key]
        if isinstance(payload.get("result"), (str, bool, int)):
            summary["result"] = payload["result"]
        if isinstance(payload.get("failures"), list):
            summary["failures"] = [
                {"code": f.get("code"), "evidence": str(f.get("evidence", ""))[:160]}
                for f in payload["failures"] if isinstance(f, dict)
            ]
    else:
        # Only an explicit command exit receipt can certify long plain output.
        receipt = re.match(r"^\[exit_code=(\d+)\]", text.strip(), re.I)
        if receipt:
            summary["passed"] = int(receipt.group(1)) == 0 and not result_failed(text)
            summary["exit_code"] = int(receipt.group(1))
        else:
            summary.update(verification_status="NOT_RUN", evidence_error="UNSTRUCTURED_VERIFICATION_OUTPUT")
    encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    if len(encoded) <= limit:
        return encoded
    # Oversized proof is not made weaker until it passes. Keep failure, or
    # declare unavailable rather than dropping required facts from a pass.
    fallback = {"verification_status": "NOT_RUN", "evidence_error": "VERIFICATION_EVIDENCE_OVERFLOW",
                "source_sha256": summary["source_sha256"]}
    if isinstance(payload, dict) and structured_verification_outcome(payload) == "FAIL":
        fallback.update(passed=False, verification_status="FAIL")
    return json.dumps(fallback, separators=(",", ":"))


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
    if isinstance(result, dict):
        outcome = structured_verification_outcome(result)
        if outcome == "FAIL" or result.get("environment_error") is True:
            return True
        if outcome == "PASS":
            return False
    elif text.startswith("{"):
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            payload = None
        if isinstance(payload, dict):
            outcome = structured_verification_outcome(payload)
            if outcome == "FAIL" or payload.get("environment_error") is True:
                return True
            if outcome == "PASS":
                return False
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
        "invalid line range", "exact replacement(s), found", "exact text not found",
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


def _verification_payload(result):
    if isinstance(result, dict):
        return result
    try:
        value = json.loads(str(result))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def _verification_evidence_key(item, payload):
    tool, target = str(item.get("tool", "")), str(item.get("target", "-"))
    profile = payload.get("verification_profile")
    browser = tool == "verify_web_app" or isinstance(profile, dict)
    identity = tuple(
        str(payload.get(key) or item.get(key) or "")
        for key in ("authority_id", "verification_id", "oracle_id", "oracle_hash")
    )
    return (tool, target, str(item.get("role") or "") if browser else "",
            json.dumps(profile, sort_keys=True) if browser else "", identity)


def _is_comparable_executed_pass(result, payload):
    if payload:
        return not payload.get("environment_error") and structured_verification_outcome(payload) == "PASS"
    text = str(result).strip()
    return not result_failed(result) and bool(re.match(r"^\[exit_code=0\](?:\s|$)", text, re.I))


def latest_verification_evidence(evidence: list[dict]) -> list[dict]:
    """Keep each latest observation and any comparable failure it did not resolve."""
    latest = {}
    outstanding = {}
    for index, item in enumerate(evidence):
        tool = str(item.get("tool", ""))
        result = item.get("result", "")
        if tool not in VERIFICATION_TOOLS or result_not_applicable(result):
            continue
        payload = _verification_payload(result)
        key = _verification_evidence_key(item, payload)
        latest[key] = index
        if result_is_tool_rejection(result) or payload.get("environment_error") is True:
            continue
        if _is_comparable_executed_pass(result, payload):
            outstanding.pop(key, None)
            if tool in {"verify_web_app", "run_file"} and isinstance(payload.get("verification_profile"), dict):
                role_str = str(item.get("role") or "")
                identity = key[4]
                for old_key, old_idx in list(outstanding.items()):
                    if (old_key[0], old_key[1], old_key[2], old_key[4]) == (tool, str(item.get("target", "-")), role_str, identity):
                        old_payload = _verification_payload(evidence[old_idx].get("result", ""))
                        if old_payload.get("syntax_failure") is True:
                            outstanding.pop(old_key, None)
                            latest.pop(old_key, None)
        elif result_failed(result):
            outstanding[key] = index
    kept = set(latest.values()) | set(outstanding.values())
    return [item for index, item in enumerate(evidence) if index in kept]


def _role_neutral_verification_key(item, payload):
    tool, target = str(item.get("tool", "")), str(item.get("target", "-"))
    profile = payload.get("verification_profile")
    browser = tool == "verify_web_app" or isinstance(profile, dict)
    identity = tuple(
        str(payload.get(key) or item.get(key) or "")
        for key in ("authority_id", "verification_id", "oracle_id", "oracle_hash")
    )
    return (tool, target, json.dumps(profile, sort_keys=True) if browser else "", identity)


def current_verification_evidence(evidence: list[dict]) -> list[dict]:
    """Old proof cannot certify changed bytes; failing obligations need a comparable rerun."""
    last_mutation = -1
    for index, item in enumerate(evidence):
        if item.get("tool") in MUTATION_TOOLS:
            result = item.get("result", "")
            if not result_failed(result) and not result_not_applicable(result):
                last_mutation = index
    if last_mutation < 0:
        return list(evidence)
    post_mutation_falsifier_passes = set()
    for index, item in enumerate(evidence):
        if index <= last_mutation or str(item.get("tool", "")) not in VERIFICATION_TOOLS:
            continue
        if str(item.get("role") or "") != "Falsifier":
            continue
        res = item.get("result", "")
        if result_not_applicable(res) or result_is_tool_rejection(res):
            continue
        payload = _verification_payload(res)
        if _is_comparable_executed_pass(res, payload):
            post_mutation_falsifier_passes.add(_role_neutral_verification_key(item, payload))
    unresolved = {
        id(item)
        for item in unresolved_tool_failures(evidence)
        if not (
            evidence.index(item) < last_mutation
            and str(item.get("role") or "") == "Builder"
            and _role_neutral_verification_key(item, _verification_payload(item.get("result", "")))
            in post_mutation_falsifier_passes
        )
    }
    return [
        item for index, item in enumerate(evidence)
        if index > last_mutation or item.get("tool") not in VERIFICATION_TOOLS or id(item) in unresolved
    ]


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
    evidence = current_verification_evidence(evidence)
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
