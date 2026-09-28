"""Experiment 13: optional semantic rescue, with independent receipt binding.

Unknown metadata cannot defeat a successful legacy check. Explicit foreign
identity is different: it cannot become authoritative proof via a legacy match.
The focused-test aggregator is deliberately unchanged (Experiment 14).
"""

import copy
import json
from pathlib import Path
import shlex

from hivo import evidence_compatibility as semantic
from hivo import verification_routing as routing


def assess(claims, records, *, required_requirement_ids):
    result = semantic.assess(claims, records, required_requirement_ids=required_requirement_ids)
    result["metadata_status"] = "AVAILABLE" if records else "UNKNOWN"
    result["observed_evidence_records"] = copy.deepcopy(records)
    return result


def fallback_assessments(legacy, assessments, browser_result):
    """Only rescue failed legacy matching; never rescue an actual browser FAIL."""
    selected, decisions = {}, []
    for route in legacy["verification_routes"]:
        if route.get("kind") != routing.BROWSER or route.get("authority_id") or route.get("authority_type") or route.get("oracle_id"):
            continue
        target = str(route.get("target"))
        assessment = (assessments or {}).get(target, {})
        metadata = assessment.get("metadata_status", "AVAILABLE" if assessment.get("canonical_evidence_records") else "UNKNOWN")
        decision = "CURRENT" if route.get("result") == routing.PASS else "LEGACY_UNCHANGED"
        if (decision != "CURRENT" and metadata == "AVAILABLE" and assessment.get("status") == routing.PASS
                and isinstance(browser_result, dict) and browser_result.get("passed") is True):
            selected[target] = assessment
            decision = "SEMANTIC_RESCUE"
        decisions.append({"kind":route["kind"], "target":target, "current_result":route.get("result"),
                          "metadata_status":metadata, "decision":decision})
    return selected, decisions


def _payload(value):
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (ValueError, TypeError):
        return {}


def proof_bindings(routes, evidence, browser_result):
    """Keep declared identity before legacy receipt projection drops metadata."""
    bindings = []
    for route in routes:
        if not route.get("required") or not route.get("applicable") or route.get("kind") not in {routing.BROWSER, routing.FOCUSED_TEST}:
            continue
        if route.get("authority_id") or route.get("authority_type") or route.get("oracle_id"):
            continue
        candidates = [e for e in evidence if routing._evidence_matches(route, e)
                      and routing._parse_result(e.get("result"))[0] == routing.PASS]
        if route["kind"] == routing.BROWSER and isinstance(browser_result, dict) and browser_result.get("passed") is True:
            candidates.append({"tool":"controller_browser", "target":browser_result.get("resolved_entrypoint"), "result":browser_result})
        for item in candidates:
            payload = _payload(item.get("result"))
            bindings.append({"kind":route["kind"], "expected_target":route.get("target"),
                "expected_behavior":route.get("behavior") or ("focused_test:"+str(route.get("target")) if route["kind"] == routing.FOCUSED_TEST else None),
                "tool":item.get("tool"), "target":item.get("target"),
                "observed_target":payload.get("resolved_entrypoint") or payload.get("entry_path"),
                "requirement_id":item.get("requirement_id", payload.get("requirement_id")),
                "requirement_ids":item.get("requirement_ids", payload.get("requirement_ids")),
                "behavior":item.get("behavior", payload.get("behavior")),
                "result_hash":semantic.canonical_hash(item.get("result"))})
    return bindings


def _targets(value, workspace):
    if not isinstance(value, str):
        return set()
    try:
        tokens = [value, *shlex.split(value, posix=False)]
    except ValueError:
        tokens = [value]
    paths = set()
    for token in tokens:
        token = token.strip('"\'')
        if workspace and Path(token).is_absolute():
            try:
                token = Path(token).resolve().relative_to(Path(workspace).resolve()).as_posix()
            except ValueError:
                continue
        identity = semantic.target_identity(token)
        if identity:
            paths.add(identity)
    return paths


def binding_errors(bindings, requirements, *, workspace=None):
    required = {r["requirement_id"] for r in requirements if r.get("requirement_id")}
    names = {c["assertion"]["name"] for c in semantic.required_claims(requirements, contract_hash="", child_id="",
             target="surface.html", subject_hash="", subject_paths=[])}
    errors = []
    for item in bindings:
        rid, rids = item.get("requirement_id"), item.get("requirement_ids")
        if (rid is not None and rid not in required) or (rids is not None and (not isinstance(rids, list) or not set(rids).issubset(required))):
            errors.append("declared evidence requirement differs from approved requirements")
        target = semantic.target_identity(item.get("expected_target"))
        observed = item.get("observed_target") or item.get("target")
        if observed and target not in _targets(observed, workspace):
            errors.append("declared evidence target differs from required verification target")
        behavior = item.get("behavior")
        if behavior is not None:
            allowed = names if item["kind"] == routing.BROWSER else {item.get("expected_behavior")}
            if behavior not in allowed:
                errors.append("declared evidence behavior is not bound to required verification")
    return list(dict.fromkeys(errors))
