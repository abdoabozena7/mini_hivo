"""Experiment 14: exact suite binding or complete executed browser claims.

An approved suite path identifies its obligation without invented semantic
metadata. Generic test markers, path substrings and a page-load PASS do not.
This module changes aggregation only; the independent receipt gate is intact.
"""

from pathlib import Path
import re
import shlex

from hivo import evidence_compatibility as semantic, evidence_monotonic


def _path(value, workspace):
    if not isinstance(value, str) or not value.strip():
        return None
    value = value.strip().strip('"\'')
    if workspace and Path(value).is_absolute():
        try:
            value = Path(value).resolve().relative_to(Path(workspace).resolve()).as_posix()
        except ValueError:
            return None
    return semantic.target_identity(value)


def target(value, tool, workspace=None):
    """Parse a file invocation, never search stdout or arbitrary command args."""
    if tool != "run_command":
        return _path(value, workspace)
    if not isinstance(value, str):
        return None
    try:
        tokens = [t.strip('"\'') for t in shlex.split(value, posix=False)]
    except ValueError:
        return None
    if len(tokens) != 2:
        return None
    executable = Path(tokens[0]).name.casefold()
    if executable not in {"node", "node.exe", "python", "python.exe", "python3", "pytest", "pytest.exe"}:
        return None
    if tokens[1].startswith("-"):
        return None
    return _path(tokens[1], workspace)


def identity_errors(route, item, context, claims=()):
    payload = evidence_monotonic._payload(item.get("result"))
    expected_target = _path(route.get("target"), context.get("workspace"))
    errors = []
    tool = item.get("tool")
    if tool not in {"run_file", "run_command", "verify_web_app", "controller_browser"}:
        errors.append("unsupported evidence provenance")
    if route["kind"] == "FOCUSED_TEST":
        result = item.get("result")
        executed = isinstance(result, str) and re.search(r"\[exit_code=-?\d+\]", result) is not None
        executed = executed or (isinstance(payload.get("exit_code"), int)
                                and not isinstance(payload.get("exit_code"), bool)
                                and payload.get("executed") is True)
        if not executed:
            errors.append("native execution result UNKNOWN")
    observed = item.get("target") or item.get("path") or item.get("command")
    if not expected_target or target(observed, tool, context.get("workspace")) != expected_target:
        errors.append("target missing or different")
    for key in ("path", "command"):
        if item.get(key) and target(item[key], "run_command" if key == "command" else "run_file", context.get("workspace")) != expected_target:
            errors.append("conflicting target identity")
    for key in ("resolved_entrypoint", "entry_path"):
        if payload.get(key) and _path(payload[key], context.get("workspace")) != expected_target:
            errors.append("observed surface differs")
    required = set(context.get("requirement_ids") or [c["requirement_id"] for c in claims])
    names = {c["assertion"]["name"] for c in claims}
    behavior = route.get("behavior") or "focused_test:" + str(route.get("target"))
    for source in (item, payload):
        if "requirement_id" in source and source["requirement_id"] not in required:
            errors.append("requirement missing or different")
        if "requirement_ids" in source:
            ids = source["requirement_ids"]
            if not isinstance(ids, list) or not ids or any(r not in required for r in ids):
                errors.append("requirements missing or different")
        if "behavior" in source and source["behavior"] not in (names if route["kind"] == "BROWSER" else {behavior}):
            errors.append("behavior missing or different")
        if "obligation_id" in source and (not route.get("obligation_id") or source["obligation_id"] != route["obligation_id"]):
            errors.append("obligation missing or different")
        provenance = source.get("provenance")
        if provenance is not None and (not isinstance(provenance, dict) or provenance.get("executed") is not True
                or provenance.get("source") not in {"controller_tool_result", "controller_child_browser"}
                or provenance.get("tool") != tool):
            errors.append("unbound execution provenance")
    return list(dict.fromkeys(errors))


def matches(route, item, context):
    """Known authority/oracle routes are handled by the original exact matcher."""
    if route["kind"] != "FOCUSED_TEST":
        return False
    return not identity_errors(route, item, context)


def browser_assessments(artifact, evidence, browser, assessments, context):
    selected, decisions = {}, []
    for route in artifact.get("verification_routes", []):
        if route.get("kind") != "BROWSER" or route.get("authority_id") or route.get("authority_type") or route.get("oracle_id"):
            continue
        if not route.get("target") or (not route.get("required") and not route.get("applicable")):
            continue
        key = str(route.get("target"))
        inventory = (assessments or {}).get(key, {})
        claims = inventory.get("required_claims", [])
        records = inventory.get("observed_evidence_records", inventory.get("canonical_evidence_records", []))
        errors = []
        if not claims:
            errors.append("required browser claim identity UNKNOWN")
        if not isinstance(browser, dict) or browser.get("passed") is not True:
            errors.append("fresh browser PASS unavailable")
        else:
            witness = {"tool":"controller_browser", "target":browser.get("resolved_entrypoint") or browser.get("entry_path"), "result":browser}
            errors.extend(identity_errors(route, witness, context, claims))
        # Preserve declared contradictions instead of laundering them through
        # controller PASS or a cached semantic summary.
        for item in evidence:
            if item.get("tool") in {"verify_web_app", "run_file"}:
                errors.extend(identity_errors(route, item, context, claims))
        if records:
            if any(r.get("provenance", {}).get("tool") not in {"run_file", "verify_web_app", "controller_browser"} for r in records):
                errors.append("unsupported canonical provenance")
        elif claims and isinstance(browser, dict):
            # Missing extra inventory is UNKNOWN; a complete native payload can
            # still prove every required assertion through deterministic binding.
            records = semantic.normalize_browser_result(browser, claims, tool="controller_browser",
                source="controller_child_browser", subject_before_hash=claims[0]["subject_hash"],
                subject_after_hash=claims[0]["subject_hash"])
        checked = evidence_monotonic.assess(claims, records,
            required_requirement_ids=context.get("requirement_ids") or inventory.get("required_requirement_ids", []))
        if claims and isinstance(browser, dict):
            fresh = semantic.normalize_browser_result(browser, claims, tool="controller_browser",
                source="controller_child_browser", subject_before_hash=claims[0]["subject_hash"],
                subject_after_hash=claims[0]["subject_hash"])
            if semantic.assess(claims, fresh, required_requirement_ids=checked["required_requirement_ids"])["status"] != "PASS":
                errors.append("fresh behavior does not cover required assertions")
        if errors:
            checked["status"] = "PENDING"
        selected[key] = checked
        decisions.append({"target":key,"result":checked["status"], "reasons":list(dict.fromkeys(errors)),
                          "inventory_status":inventory.get("metadata_status", "UNKNOWN")})
    return selected, decisions
