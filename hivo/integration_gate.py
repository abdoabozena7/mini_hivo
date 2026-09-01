"""Deterministic V21 verified-child integration gate.

Stage 5B is deliberately separate from the model client, Worker transcripts,
and the existing Stage 4 authority objects.  A child receipt is a derived
evidence record, never a new authority record.  The readiness gate consumes
only the validated child plan, terminal child state, receipts, and bounded
file fingerprints.  Parent integration is a second evidence boundary: child
passes can make a parent eligible, but they cannot make the parent verified.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable


SCHEMA_VERSION = "V21.5B"
RECEIPT_TYPE = "VerifiedChildReceipt"
PARENT_RECEIPT_TYPE = "ParentVerificationReceipt"

READY = "READY"
NOT_READY = "NOT_READY"
INTEGRATION_NOT_READY = "INTEGRATION_NOT_READY"
INTEGRATION_FAILED = "INTEGRATION_FAILED"

NOT_READY_CHILD_FAILURE = "NOT_READY_CHILD_FAILURE"
NOT_READY_CHILD_UNVERIFIED = "NOT_READY_CHILD_UNVERIFIED"
NOT_READY_STALE_EVIDENCE = "INTEGRATION_NOT_READY_STALE_EVIDENCE"
NOT_READY_STALE_RECEIPT = "INTEGRATION_NOT_READY_STALE_RECEIPT"
NOT_READY_COVERAGE_GAP = "NOT_READY_COVERAGE_GAP"
NOT_READY_STALE_AUTHORITY = "INTEGRATION_NOT_READY_STALE_AUTHORITY"
NOT_READY_PROVENANCE_VIOLATION = "INTEGRATION_NOT_READY_PROVENANCE_VIOLATION"

INTEGRATION_EVIDENCE_UNAVAILABLE = "INTEGRATION_EVIDENCE_UNAVAILABLE"
PARENT_VERIFIED = "PARENT_VERIFIED"
PARENT_NOT_VERIFIED = "PARENT_NOT_VERIFIED"
REQUIRED_INTEGRATION_TARGET_UNRESOLVED = "REQUIRED_INTEGRATION_TARGET_UNRESOLVED"

SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"

_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_transcript", "private_reasoning", "raw_worker_output", "raw_content",
})
_PATH_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".css", ".go", ".h", ".html", ".htm", ".java",
    ".js", ".jsx", ".json", ".mjs", ".cjs", ".py", ".rs", ".ts", ".tsx",
    ".toml", ".yaml", ".yml",
})
_IMPORT_RE = re.compile(
    r"(?:import\s+(?:[^;]*?\s+from\s+)?|export\s+[^;]*?\s+from\s+|require\s*\(|import\s*\()"
    r"[\"']([^\"']+)[\"']",
    re.IGNORECASE,
)
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_$])(?:\.{0,2}/)?[A-Za-z0-9_./\\-]+\.(?:c|cc|cpp|css|go|h|html?|java|js|jsx|json|mjs|cjs|py|rs|ts|tsx|toml|ya?ml)"
    r"(?![A-Za-z0-9_$])",
    re.IGNORECASE,
)


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def canonical_hash(value: Any) -> str:
    """Hash canonical JSON; dictionary insertion order never affects identity."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


deterministic_hash = canonical_hash


def _compact(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _unique_strings(values: Iterable[Any], limit: int = 120) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("path") or value.get("target") or value.get("id") or ""
        text = str(value or "").strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _provenance_violation_counts(*sources: dict | None) -> dict[str, int]:
    """Read existing structured violation markers without interpreting prose broadly."""
    counts = {"unauthorized_mutations": 0, "scope_violations": 0, "dnt_violations": 0}
    for source in sources:
        if not isinstance(source, dict):
            continue
        counts["unauthorized_mutations"] = max(
            counts["unauthorized_mutations"],
            int(source.get("unauthorized_mutations", 0) or source.get("unauthorized_mutation_count", 0) or 0),
        )
        counts["scope_violations"] = max(
            counts["scope_violations"],
            int(source.get("scope_violations", 0) or source.get("out_of_scope_mutations", 0) or 0),
        )
        counts["dnt_violations"] = max(
            counts["dnt_violations"],
            int(source.get("dnt_violations", 0) or source.get("do_not_touch_violations", 0) or 0),
        )
        records = []
        for key in ("mutation_failures", "failure_evidence", "failure_diagnosis"):
            value = source.get(key)
            records.extend(value if isinstance(value, list) else [value] if isinstance(value, dict) else [])
        for record in records:
            text = json.dumps(record, ensure_ascii=False, default=str).upper()
            if "UNAUTHORIZED_MUTATION" in text or "UNAUTHORIZED PERSIST" in text:
                counts["unauthorized_mutations"] = max(counts["unauthorized_mutations"], 1)
            if "OUT_OF_SCOPE" in text or "SCOPE_VIOLATION" in text or "CONTRACT_SCOPE_VIOLATION" in text:
                counts["scope_violations"] = max(counts["scope_violations"], 1)
            if "DO_NOT_TOUCH" in text or "DNT_VIOLATION" in text:
                counts["dnt_violations"] = max(counts["dnt_violations"], 1)
        failure_type = str(source.get("failure_type") or source.get("orchestration_failure") or "").upper()
        if "UNAUTHORIZED" in failure_type:
            counts["unauthorized_mutations"] = max(counts["unauthorized_mutations"], 1)
        if "SCOPE" in failure_type:
            counts["scope_violations"] = max(counts["scope_violations"], 1)
        if "DO_NOT_TOUCH" in failure_type or failure_type == "DNT":
            counts["dnt_violations"] = max(counts["dnt_violations"], 1)
    return counts


def _root_path(workspace: str | os.PathLike | None) -> Path | None:
    if workspace is None:
        return None
    try:
        root = Path(workspace).resolve()
    except (OSError, ValueError):
        return None
    return root if root.is_dir() else root


def normalize_path(value: Any, workspace: str | os.PathLike | None = None) -> str:
    """Return a safe workspace-relative POSIX path where possible."""
    raw = str(value or "").strip().replace("\\", "/")
    if not raw:
        return ""
    root = _root_path(workspace)
    candidate = Path(raw)
    if root is not None and candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root).as_posix()
        except (OSError, ValueError):
            return ""
    while raw.startswith("./"):
        raw = raw[2:]
    raw = os.path.normpath(raw).replace("\\", "/")
    if raw in {".", ""} or raw == ".." or raw.startswith("../"):
        return ""
    return raw.lstrip("/")


def _file_record(root: Path | None, relative: str) -> dict[str, Any]:
    record: dict[str, Any] = {"path": relative, "exists": False, "sha256": None, "size": 0}
    if root is None:
        return record
    path = root / relative
    try:
        if not path.is_file():
            return record
        data = path.read_bytes()
    except OSError:
        return record
    record.update({"exists": True, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)})
    return record


def fingerprint_dependency_paths(
    workspace: str | os.PathLike | None,
    dependency_paths: Iterable[Any] | None,
) -> dict[str, Any]:
    """Fingerprint only the bounded files relevant to one child receipt."""
    root = _root_path(workspace)
    paths = sorted({
        normalized for normalized in (
            normalize_path(item, workspace) for item in (dependency_paths or [])
        ) if normalized
    }, key=str.casefold)
    records = [_file_record(root, path) for path in paths]
    payload = {"schema_version": SCHEMA_VERSION, "paths": records}
    return {**payload, "hash": canonical_hash(payload)}


build_evidence_dependency_fingerprint = fingerprint_dependency_paths
subject_state_fingerprint = fingerprint_dependency_paths


def _path_like_values(value: Any, workspace: str | os.PathLike | None = None) -> list[str]:
    found: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            for key in ("path", "target", "entrypoint", "file"):
                found.extend(_path_like_values(item.get(key), workspace))
            continue
        text = str(item or "")
        direct = normalize_path(text, workspace)
        if direct and not re.search(r"\s", text) and Path(direct).suffix.casefold() in _PATH_SUFFIXES:
            found.append(direct)
        for match in _PATH_RE.finditer(text):
            normalized = normalize_path(match.group(0), workspace)
            if normalized:
                found.append(normalized)
    return _unique_strings(found)


def _read_local_imports(root: Path | None, relative: str) -> list[str]:
    if root is None:
        return []
    path = root / relative
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    result: list[str] = []
    for raw in _IMPORT_RE.findall(text):
        if not str(raw).startswith((".", "/")):
            continue
        base = (path.parent / str(raw)).resolve()
        candidates = [base]
        if not base.suffix:
            candidates.extend(base.with_suffix(suffix) for suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".py"))
            candidates.append(base / "index.js")
        for candidate in candidates:
            try:
                if candidate.is_file():
                    result.append(candidate.relative_to(root).as_posix())
                    break
            except (OSError, ValueError):
                continue
    return _unique_strings(result)


def derive_evidence_dependency_paths(
    child_task: dict | None = None,
    child_result: dict | None = None,
    verification_aggregation: dict | None = None,
    verification_evidence: Iterable[dict] | None = None,
    *,
    workspace: str | os.PathLike | None = None,
    mutation_paths: Iterable[Any] | None = None,
    dependency_paths: Iterable[Any] | None = None,
) -> list[str]:
    """Derive a conservative but evidence-scoped dependency set.

    Mutation surfaces are always included.  Inspection-only paths are not
    included merely because a child was allowed to read them; they enter only
    when a route/evidence record names them or the caller marks them as a
    relevant integration surface.  Local imports from named evidence files
    are followed so a shared test dependency makes a receipt stale when its
    other input changes.
    """
    task = child_task if isinstance(child_task, dict) else {}
    result = child_result if isinstance(child_result, dict) else {}
    aggregation = verification_aggregation if isinstance(verification_aggregation, dict) else {}
    values: list[Any] = []
    values.extend(_as_list(mutation_paths))
    values.extend(_as_list(dependency_paths))
    for source in (task, result, aggregation):
        for key in (
            "changed_files", "mutation_paths", "allowed_mutation_paths",
            "verification_dependency_paths", "evidence_dependency_paths",
            "relevant_inspection_paths", "integration_surfaces",
        ):
            if key in source:
                values.extend(_as_list(source.get(key)))

    routes = aggregation.get("verification_routes", [])
    if not routes:
        artifact = result.get("verification_applicability")
        if isinstance(artifact, dict):
            routes = artifact.get("verification_routes", [])
        elif isinstance(task.get("verification_applicability"), dict):
            routes = task["verification_applicability"].get("verification_routes", [])
    for route in routes or []:
        if isinstance(route, dict):
            values.extend(_path_like_values(route.get("target"), workspace))
            values.extend(_path_like_values(route.get("requested_from_node"), workspace))

    evidence = [item for item in (verification_evidence or []) if isinstance(item, dict)]
    for item in evidence:
        for key in ("target", "path", "entrypoint", "file", "command"):
            values.extend(_path_like_values(item.get(key), workspace))
        # A tool result may be a command string containing the relevant test;
        # only lexical file-shaped tokens are admitted.
        values.extend(_path_like_values(item.get("result"), workspace))

    initial = _unique_strings(
        normalize_path(item, workspace) for item in values if normalize_path(item, workspace)
    )
    root = _root_path(workspace)
    expanded = list(initial)
    seen = set(initial)
    # Follow imports from evidence/route files only.  This is bounded and does
    # not turn the entire repository into a dependency fingerprint.
    queue = list(initial)
    while queue and len(expanded) < 120:
        current = queue.pop(0)
        for imported in _read_local_imports(root, current):
            imported = normalize_path(imported, workspace)
            if imported and imported not in seen:
                seen.add(imported)
                expanded.append(imported)
                queue.append(imported)
    return sorted(set(expanded), key=str.casefold)[:120]


def _safe_projection(value: Any, depth: int = 0) -> Any:
    """Copy audit-safe data while excluding model/private transcript fields."""
    if depth > 4:
        return _compact(value, 300)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.casefold() in _PRIVATE_KEYS:
                continue
            result[key_text] = _safe_projection(item, depth + 1)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_projection(item, depth + 1) for item in list(value)[:24]]
    if isinstance(value, str):
        return _compact(value, 900)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _compact(value, 300)


def compact_verification_evidence(evidence: Iterable[dict] | None, limit: int = 16) -> list[dict]:
    """Retain executable evidence facts, never raw Worker results/transcripts."""
    projected: list[dict] = []
    for item in list(evidence or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        value: dict[str, Any] = {}
        for key in (
            "tool", "target", "path", "status", "passed", "verification_status",
            "failure_type", "result", "summary", "source", "kind",
        ):
            if key in item and str(key).casefold() not in _PRIVATE_KEYS:
                value[key] = _safe_projection(item[key])
        if value:
            projected.append(value)
    return projected


def _route_projection(route: dict) -> dict:
    keys = (
        "kind", "required", "applicable", "target", "result", "reason_codes",
        "evidence_refs", "resolution_status", "resolution_source", "requested_from_node",
    )
    return {key: _safe_projection(route.get(key)) for key in keys if key in route}


def _artifact_from_inputs(task: dict, result: dict, explicit: dict | None) -> dict:
    if isinstance(explicit, dict):
        return explicit
    for source in (result, task):
        artifact = source.get("verification_applicability")
        if isinstance(artifact, dict):
            return artifact
        gate = source.get("gate")
        if isinstance(gate, dict) and isinstance(gate.get("verification_applicability"), dict):
            return gate["verification_applicability"]
    return {}


def _aggregation_from_inputs(result: dict, explicit: dict | None) -> dict:
    if isinstance(explicit, dict):
        return explicit
    gate = result.get("gate")
    if isinstance(gate, dict) and isinstance(gate.get("verification_aggregation"), dict):
        return gate["verification_aggregation"]
    if isinstance(result.get("verification_aggregation"), dict):
        return result["verification_aggregation"]
    return {}


def _required_route_pass(aggregation: dict, kind: str | Iterable[str]) -> bool:
    kinds = {kind} if isinstance(kind, str) else {str(item) for item in kind}
    return any(
        isinstance(item, dict)
        and item.get("kind") in kinds
        and item.get("required") is True
        and item.get("applicable") is True
        # ``actual_passes`` is the Stage 5A positive evidence set.  A route
        # that remains PENDING is not real successful verification evidence.
        and item.get("result") == PASS
        for item in aggregation.get("actual_passes", []) or []
    )


def _receipt_verification_decision(
    task: dict,
    result: dict,
    artifact: dict,
    aggregation: dict,
    *,
    authority_valid: bool,
    unauthorized_mutations: int,
    scope_violations: int,
    dnt_violations: int,
) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if str(result.get("status", task.get("status", ""))).casefold() not in {"done", "completed", "verified"}:
        reasons.append("CHILD_NOT_TERMINALLY_VERIFIED")
    if not authority_valid:
        reasons.append("STALE_OR_INVALID_AUTHORITY")
    if unauthorized_mutations or scope_violations or dnt_violations:
        reasons.append("UNAUTHORIZED_MUTATION_OR_PROVENANCE_VIOLATION")
    if aggregation.get("passed") is not True:
        reasons.append("STAGE5A_VERIFICATION_NOT_PASSED")
    failure_codes = {str(item) for item in aggregation.get("failure_codes", []) or []}
    if INTEGRATION_EVIDENCE_UNAVAILABLE in failure_codes or "VERIFICATION_EVIDENCE_UNAVAILABLE" in failure_codes:
        reasons.append("VERIFICATION_EVIDENCE_UNAVAILABLE")
    if any("UNRESOLVED" in item or "TARGET_MISSING" in item for item in failure_codes):
        reasons.append("REQUIRED_VERIFICATION_TARGET_UNRESOLVED")
    if any(
        isinstance(item, dict) and item.get("required") and item.get("result") == FAIL
        for item in aggregation.get("actual_failures", []) or []
    ):
        reasons.append("REQUIRED_VERIFICATION_FAILED")

    routes = [item for item in aggregation.get("verification_routes", []) or [] if isinstance(item, dict)]
    focused_routes = [
        item for item in routes
        if item.get("kind") in {"FOCUSED_TEST", "FOCUSED_TEST_ROUTE"}
        and item.get("required") and item.get("applicable")
    ]
    if focused_routes and not _required_route_pass(
        aggregation, {"FOCUSED_TEST", "FOCUSED_TEST_ROUTE"},
    ):
        reasons.append("REQUIRED_FOCUSED_TEST_NOT_PASSED")
    required_syntax = [
        item for item in routes
        if item.get("kind") in {"SYNTAX_STATIC_GATE", "SYNTAX", "STATIC"}
        and item.get("required") and item.get("applicable")
    ]
    if any(item.get("result") in {FAIL, "BLOCKED_REQUIRED_TARGET_MISSING"} for item in required_syntax):
        reasons.append("REQUIRED_SYNTAX_STATIC_FAILED")
    # An aggregation with no required actual pass is never a receipt, even if
    # an optional browser result happened to be positive.
    if not aggregation.get("evidence_available") and not aggregation.get("actual_passes"):
        reasons.append("NO_REAL_REQUIRED_VERIFICATION_EVIDENCE")
    return not reasons, list(dict.fromkeys(reasons))


def create_verified_child_receipt(
    child_task: dict | None = None,
    child_result: dict | None = None,
    *,
    parent_id: str | None = None,
    parent_contract: dict | None = None,
    verification_applicability: dict | None = None,
    verification_aggregation: dict | None = None,
    verification_evidence: Iterable[dict] | None = None,
    workspace: str | os.PathLike | None = None,
    mutation_paths: Iterable[Any] | None = None,
    dependency_paths: Iterable[Any] | None = None,
    authority_valid: bool = True,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
) -> dict:
    """Derive one immutable-in-content child receipt from Stage 5A evidence."""
    task = child_task if isinstance(child_task, dict) else {}
    result = child_result if isinstance(child_result, dict) else {}
    artifact = _artifact_from_inputs(task, result, verification_applicability)
    aggregation = _aggregation_from_inputs(result, verification_aggregation)
    evidence = [item for item in (verification_evidence or []) if isinstance(item, dict)]
    if not evidence:
        for source in (result, result.get("builder", {}), result.get("falsifier", {})):
            if isinstance(source, dict):
                evidence.extend(item for item in source.get("tool_evidence", []) or [] if isinstance(item, dict))
    child_id = str(task.get("id") or task.get("task_id") or result.get("child_id") or "UNKNOWN")
    contract = task.get("execution_contract") if isinstance(task.get("execution_contract"), dict) else task
    contract = contract if isinstance(contract, dict) else {}
    parent_contract = parent_contract if isinstance(parent_contract, dict) else {}
    dependency_list = derive_evidence_dependency_paths(
        task, result, aggregation, evidence, workspace=workspace,
        mutation_paths=mutation_paths or contract.get("allowed_mutation_paths", []),
        dependency_paths=dependency_paths,
    )
    fingerprint = fingerprint_dependency_paths(workspace, dependency_list)
    detected_violations = _provenance_violation_counts(task, result)
    unauthorized_mutations = max(int(unauthorized_mutations or 0), detected_violations["unauthorized_mutations"])
    scope_violations = max(int(scope_violations or 0), detected_violations["scope_violations"])
    dnt_violations = max(int(dnt_violations or 0), detected_violations["dnt_violations"])
    routes = [
        _route_projection(item)
        for item in aggregation.get("verification_routes", []) or []
        if isinstance(item, dict)
    ]
    if not routes and isinstance(artifact, dict):
        routes = [
            _route_projection(item)
            for item in artifact.get("verification_routes", []) or []
            if isinstance(item, dict)
        ]
    safe_evidence = compact_verification_evidence(evidence)
    verified, reasons = _receipt_verification_decision(
        task, result, artifact, aggregation,
        authority_valid=authority_valid,
        unauthorized_mutations=int(unauthorized_mutations or 0),
        scope_violations=int(scope_violations or 0),
        dnt_violations=int(dnt_violations or 0),
    )
    coverage = {
        "plan_node_ids": _unique_strings(
            list(task.get("plan_node_ids", []) or []) + list(contract.get("plan_node_ids", []) or [])
        ),
        "owned_plan_node_ids": _unique_strings(
            list(task.get("owned_plan_node_ids", []) or []) + list(contract.get("owned_plan_node_ids", []) or [])
        ),
        "responsibility_units": _unique_strings(
            list(task.get("responsibility_units", []) or [])
            + list(task.get("done_when", []) or [])
            + list(contract.get("done_when", []) or [])
        ),
    }
    browser_routes = [item for item in routes if item.get("kind") == "BROWSER"]
    browser_invoked = any(str(item.get("tool", "")) == "verify_web_app" for item in safe_evidence)
    authority = {
        "execution_contract_id": contract.get("execution_contract_id") or task.get("execution_contract_id"),
        "execution_contract_hash": contract.get("contract_hash") or task.get("execution_contract_hash"),
        "plan_id": contract.get("plan_id") or task.get("approved_plan_id"),
        "plan_hash": contract.get("plan_hash") or task.get("approved_plan_hash"),
        "parent_contract_hash": parent_contract.get("contract_hash") or parent_contract.get("execution_contract_hash"),
    }
    mutation_surface = sorted({
        normalized for normalized in (
            normalize_path(item, workspace)
            for item in (mutation_paths or contract.get("allowed_mutation_paths", []) or [])
        ) if normalized
    }, key=str.casefold)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECEIPT_TYPE,
        "child_id": child_id,
        "parent_id": str(parent_id if parent_id is not None else task.get("parent") or "") or None,
        "verified": bool(verified),
        "receipt_status": "VERIFIED" if verified else "UNVERIFIED",
        "verification_status": "passed" if verified else "failed",
        "terminal_child_status": str(result.get("status", task.get("status", "unknown"))),
        "verification_failure_reasons": reasons,
        "child_authority_hash": canonical_hash(authority),
        "authority": authority,
        "parent_contract_hash": authority.get("parent_contract_hash"),
        "plan_hash": authority.get("plan_hash"),
        "mutation_paths": mutation_surface,
        "verification_applicability_hash": artifact.get("verification_applicability_hash"),
        "verification_routes_hash": artifact.get("verification_routes_hash"),
        "verification_routes": routes,
        "browser": {
            "required": any(item.get("required") is True for item in browser_routes),
            "applicable": any(item.get("applicable") is True for item in browser_routes),
            "resolved_target": next((item.get("target") for item in browser_routes if item.get("target")), None),
            "result": next((item.get("result") for item in browser_routes), SKIPPED_NOT_APPLICABLE),
            "verifier_invoked": browser_invoked,
        },
        "verification_aggregation": {
            "passed": bool(aggregation.get("passed") is True),
            "evidence_available": bool(aggregation.get("evidence_available")),
            "failure_codes": _unique_strings(aggregation.get("failure_codes", [])),
            "actual_passes": [_route_projection(item) for item in aggregation.get("actual_passes", []) or [] if isinstance(item, dict)],
            "actual_failures": [_route_projection(item) for item in aggregation.get("actual_failures", []) or [] if isinstance(item, dict)],
            "skipped_not_applicable": [_route_projection(item) for item in aggregation.get("skipped_not_applicable", []) or [] if isinstance(item, dict)],
        },
        "verification_evidence": safe_evidence,
        "required_evidence": safe_evidence,
        "coverage": coverage,
        "verified_subject_state_hash": fingerprint.get("hash"),
        "verified_subject_state": fingerprint,
        "evidence_dependency_fingerprint": fingerprint,
        "provenance": {
            "source": "deterministic_stage5a_verified_semantics",
            "model_calls": 0,
            "raw_worker_transcript_included": False,
            "memory_promotion": False,
        },
    }
    payload["receipt_hash"] = canonical_hash(payload)
    return copy.deepcopy(payload)


build_verified_child_receipt = create_verified_child_receipt


def receipt_freshness(
    receipt: dict | None,
    workspace: str | os.PathLike | None,
    *,
    current_dependency_paths: Iterable[Any] | None = None,
) -> dict:
    value = receipt if isinstance(receipt, dict) else {}
    stored = value.get("evidence_dependency_fingerprint")
    if not isinstance(stored, dict):
        return {"fresh": False, "reason": "MISSING_DEPENDENCY_FINGERPRINT", "stale_paths": []}
    paths = current_dependency_paths
    if paths is None:
        paths = [item.get("path") for item in stored.get("paths", []) if isinstance(item, dict)]
    current = fingerprint_dependency_paths(workspace, paths)
    stored_records = {
        str(item.get("path")): item for item in stored.get("paths", []) if isinstance(item, dict)
    }
    current_records = {
        str(item.get("path")): item for item in current.get("paths", []) if isinstance(item, dict)
    }
    stale_paths = sorted(
        (
            path for path in set(stored_records) | set(current_records)
            if stored_records.get(path) != current_records.get(path)
        ),
        key=str.casefold,
    )
    fresh = stored.get("hash") == current.get("hash") and not stale_paths
    return {
        "fresh": bool(fresh), "stale_paths": stale_paths,
        "stored_hash": stored.get("hash"), "current_hash": current.get("hash"),
        "fingerprint": current,
        "reason": None if fresh else "DEPENDENCY_STATE_CHANGED",
    }


verify_receipt_freshness = receipt_freshness


def validate_verified_child_receipt(
    receipt: dict | None,
    *,
    workspace: str | os.PathLike | None = None,
    expected_authority: dict | None = None,
    check_freshness: bool = True,
) -> dict:
    value = receipt if isinstance(receipt, dict) else {}
    errors: list[str] = []
    if value.get("artifact_type") != RECEIPT_TYPE:
        errors.append("wrong receipt artifact type")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong receipt schema version")
    expected_hash = canonical_hash(_without(value, "receipt_hash")) if value else None
    if value.get("receipt_hash") != expected_hash:
        errors.append("receipt hash does not match canonical contents")
    if value.get("verified") is True and value.get("receipt_status") != "VERIFIED":
        errors.append("verified receipt has a non-verified status")
    authority = value.get("authority") if isinstance(value.get("authority"), dict) else {}
    if value.get("child_authority_hash") != canonical_hash(authority):
        errors.append("child authority hash does not match receipt authority")
    subject_state = value.get("verified_subject_state")
    if isinstance(subject_state, dict) and value.get("verified_subject_state_hash") != subject_state.get("hash"):
        errors.append("verified subject state hash does not match subject state")
    expected = expected_authority if isinstance(expected_authority, dict) else {}
    for left, right in (
        ("execution_contract_id", "execution_contract_id"),
        ("execution_contract_hash", "contract_hash"),
        ("plan_hash", "plan_hash"),
        ("parent_contract_hash", "parent_contract_hash"),
    ):
        if right in expected and expected.get(right) is not None and authority.get(left) != expected.get(right):
            errors.append(f"receipt authority mismatch: {left}")
    freshness = (
        receipt_freshness(value, workspace)
        if check_freshness else {"fresh": True, "stale_paths": [], "reason": None}
    )
    if check_freshness and not freshness.get("fresh"):
        errors.append("receipt evidence dependency fingerprint is stale")
    return {
        "valid": not errors,
        "verified": bool(value.get("verified") is True and not errors),
        "fresh": bool(freshness.get("fresh")),
        "errors": errors[:30],
        "stale_paths": list(freshness.get("stale_paths", [])),
        "freshness": freshness,
    }


def _child_id(item: dict) -> str:
    return str(item.get("child_id") or item.get("task_id") or item.get("id") or "")


def _child_pair(item: Any) -> tuple[dict, dict]:
    if isinstance(item, (list, tuple)) and len(item) >= 2:
        task = item[0] if isinstance(item[0], dict) else {}
        result = item[1] if isinstance(item[1], dict) else {}
        return task, result
    if not isinstance(item, dict):
        return {}, {"status": "failed"}
    if isinstance(item.get("task"), dict) or isinstance(item.get("result"), dict):
        return item.get("task", {}) if isinstance(item.get("task"), dict) else {}, item.get("result", {}) if isinstance(item.get("result"), dict) else {}
    if isinstance(item.get("child_task"), dict) or isinstance(item.get("child_result"), dict):
        return item.get("child_task", {}) if isinstance(item.get("child_task"), dict) else {}, item.get("child_result", {}) if isinstance(item.get("child_result"), dict) else {}
    return item, item


def derive_required_child_set(
    parent: dict | None,
    *,
    validated_child_plan: Iterable[dict] | dict | None = None,
    children: Iterable[Any] | None = None,
) -> dict:
    """Derive mandatory child IDs from validated plan coverage, never receipts."""
    value = parent if isinstance(parent, dict) else {}
    plan = validated_child_plan
    if plan is None:
        for key in ("validated_child_plan", "validated_children", "child_plan", "child_coverage"):
            if value.get(key) is not None:
                plan = value.get(key)
                break
    plan_supplied = plan is not None
    entries: list[dict] = []
    if isinstance(plan, dict):
        for key in ("children", "required_children", "coverage", "nodes"):
            if isinstance(plan.get(key), list):
                entries = [item for item in plan[key] if isinstance(item, dict)]
                break
        if not entries and plan.get("child_id"):
            entries = [plan]
    elif isinstance(plan, (list, tuple, set)):
        entries = [item for item in plan if isinstance(item, dict)]
    if not entries and not plan_supplied:
        for item in children or []:
            task, result = _child_pair(item)
            candidate = dict(task)
            candidate.setdefault("child_id", _child_id(task) or _child_id(result))
            if task.get("optional") is True or task.get("required") is False:
                candidate["required"] = False
            if task.get("execution_contract_id") or task.get("execution_contract_child") or task.get("validated") is True:
                entries.append(candidate)
    required: list[dict] = []
    excluded: list[str] = []
    for entry in entries:
        child_id = _child_id(entry)
        if not child_id:
            continue
        if entry.get("required") is False or entry.get("optional") is True:
            excluded.append(child_id)
            continue
        required.append(entry)
    required.sort(key=lambda item: _child_id(item))
    ids = [_child_id(item) for item in required]
    duplicate_ids = sorted({item for item in ids if ids.count(item) > 1})
    coverage_ids: list[str] = []
    for entry in required:
        coverage_ids.extend(_unique_strings(
            list(entry.get("owned_plan_node_ids", []) or [])
            or list(entry.get("plan_node_ids", []) or [])
            or list(entry.get("coverage_ids", []) or [])
        ))
    duplicate_coverage = sorted({item for item in coverage_ids if coverage_ids.count(item) > 1})
    return {
        "required": required,
        "required_child_ids": ids,
        "optional_child_ids": sorted(set(excluded)),
        "duplicate_child_ids": duplicate_ids,
        "required_coverage_ids": sorted(set(coverage_ids)),
        "duplicate_coverage_ids": duplicate_coverage,
        "source": "validated_child_plan" if plan is not None else "validated_child_contracts",
    }


def _receipt_map(receipts: Any) -> dict[str, dict]:
    if isinstance(receipts, dict):
        if receipts.get("child_id"):
            return {str(receipts.get("child_id")): receipts}
        return {str(key): item for key, item in receipts.items() if isinstance(item, dict)}
    return {
        str(item.get("child_id")): item
        for item in (receipts or [])
        if isinstance(item, dict) and item.get("child_id")
    }


def _status_for_child(task: dict, result: dict) -> str:
    return str(result.get("status") or task.get("status") or "PENDING").upper()


def _is_failure_status(task: dict, result: dict) -> bool:
    status = _status_for_child(task, result)
    failure_type = str(result.get("failure_type") or result.get("orchestration_failure") or "").upper()
    return status in {"FAILED", "FAIL", "TOO_BROAD"} or failure_type in {
        "TASK_TOO_BROAD", "MISSION_COMPILER_REJECTED", "MISSION_COMPILATION_FAILURE",
        "ORCHESTRATION_FAILURE", "IMPLEMENTATION_ERROR", "REQUIRED_VERIFICATION_FAILED",
        "REQUIRED_VERIFICATION_TARGET_UNRESOLVED", "VERIFICATION_TARGET_UNRESOLVED",
    }


def _is_pending_status(task: dict, result: dict) -> bool:
    return _status_for_child(task, result) in {"PENDING", "RUNNING", "DEPENDENCY_BLOCKED", "BLOCKED"}


def _default_integration_routes(parent: dict, parent_contract: dict) -> list[dict]:
    raw = parent.get("integration_routes") or parent_contract.get("integration_routes")
    if isinstance(raw, list) and raw:
        return [_route_projection(item) for item in raw if isinstance(item, dict)]
    target = parent.get("integration_test_target") or parent_contract.get("integration_test_target")
    if not target:
        for value in list(parent.get("integration_verification", []) or []) + list(parent_contract.get("integration_responsibility", []) or []) + list(parent_contract.get("test_contract", []) or []):
            match = _PATH_RE.search(str(value))
            if match:
                target = match.group(0)
                break
    routes = [{
        "kind": "INTEGRATION_TEST", "required": True, "applicable": True,
        "target": normalize_path(target) if target else None, "result": PENDING,
        "reason_codes": ["PARENT_INTEGRATION_RESPONSIBILITY"], "evidence_refs": ["parent:integration"],
    }]
    # Browser applicability is inherited from Stage 5A when supplied; this
    # fallback is intentionally non-applicable and never resolves a target.
    routes.append({
        "kind": "BROWSER", "required": False, "applicable": False,
        "target": None, "result": SKIPPED_NOT_APPLICABLE,
        "reason_codes": ["VERIFIER_NOT_REQUIRED"], "evidence_refs": ["parent:integration"],
    })
    return routes


def _integration_routes_from_applicability(applicability: dict | None, parent: dict, contract: dict) -> list[dict]:
    # An explicit parent integration route is authoritative.  Otherwise use
    # an existing parent/focused test route from the Stage 5A artifact and
    # carry over only its browser applicability.  Child syntax routes are not
    # silently promoted into parent integration evidence.
    explicit = parent.get("integration_routes") or contract.get("integration_routes")
    if isinstance(explicit, list) and explicit:
        return [_route_projection(item) for item in explicit if isinstance(item, dict)]
    artifact_routes = (
        applicability.get("verification_routes", [])
        if isinstance(applicability, dict) else []
    )
    artifact_integration = [
        _route_projection(item) for item in artifact_routes
        if isinstance(item, dict) and item.get("kind") in {"INTEGRATION_TEST", "FOCUSED_TEST", "FOCUSED_TEST_ROUTE"}
    ]
    default_routes = _default_integration_routes(parent, contract)
    routes = artifact_integration or [
        item for item in default_routes if item.get("kind") == "INTEGRATION_TEST"
    ]
    artifact_browser = next(
        (
            _route_projection(item) for item in artifact_routes
            if isinstance(item, dict) and item.get("kind") == "BROWSER"
        ),
        None,
    )
    if artifact_browser is not None:
        routes.append(artifact_browser)
    else:
        routes.append(next(
            (item for item in default_routes if item.get("kind") == "BROWSER"),
            {
                "kind": "BROWSER", "required": False, "applicable": False,
                "target": None, "result": SKIPPED_NOT_APPLICABLE,
            },
        ))
    return routes


def assess_integration_readiness(
    parent: dict | None,
    children: Iterable[Any] | None = None,
    receipts: Any = None,
    *,
    parent_contract: dict | None = None,
    validated_child_plan: Iterable[dict] | dict | None = None,
    workspace: str | os.PathLike | None = None,
    parent_verification_applicability: dict | None = None,
    authority_valid: bool = True,
    authority_failure: str | None = None,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
) -> dict:
    """Run the zero-model parent readiness gate."""
    value = parent if isinstance(parent, dict) else {}
    contract = parent_contract if isinstance(parent_contract, dict) else {}
    child_items = list(children or [])
    child_map: dict[str, tuple[dict, dict]] = {}
    for item in child_items:
        task, result = _child_pair(item)
        child_id = _child_id(task) or _child_id(result)
        if child_id:
            child_map[child_id] = (task, result)
    plan = derive_required_child_set(
        value, validated_child_plan=validated_child_plan, children=child_items,
    )
    receipt_by_id = _receipt_map(receipts)
    terminal_statuses = {
        child_id: _status_for_child(*child_map.get(child_id, ({}, {})))
        for child_id in plan["required_child_ids"]
    }
    failures: list[str] = []
    pending: list[str] = []
    missing_receipts: list[str] = []
    stale: list[dict] = []
    invalid_receipts: list[str] = []
    coverage_receipts: list[str] = []
    for child_id in plan["required_child_ids"]:
        task, result = child_map.get(child_id, ({"id": child_id}, {"status": "pending"}))
        if _is_failure_status(task, result):
            failures.append(child_id)
            continue
        if _is_pending_status(task, result):
            pending.append(child_id)
            continue
        receipt = receipt_by_id.get(child_id)
        if not isinstance(receipt, dict):
            missing_receipts.append(child_id)
            continue
        checked = validate_verified_child_receipt(
            receipt, workspace=workspace,
            expected_authority={
                "execution_contract_id": task.get("execution_contract_id") or (task.get("execution_contract") or {}).get("execution_contract_id"),
                "contract_hash": task.get("execution_contract_hash") or (task.get("execution_contract") or {}).get("contract_hash"),
                "plan_hash": task.get("approved_plan_hash") or (task.get("execution_contract") or {}).get("plan_hash"),
                "parent_contract_hash": contract.get("contract_hash"),
            },
        )
        if not checked.get("valid") or receipt.get("verified") is not True:
            if checked.get("stale_paths") or "stale" in " ".join(checked.get("errors", [])).casefold():
                stale.append({"child_id": child_id, "stale_paths": checked.get("stale_paths", []), "errors": checked.get("errors", [])})
            else:
                invalid_receipts.append(child_id)
            continue
        if not checked.get("fresh"):
            stale.append({"child_id": child_id, "stale_paths": checked.get("stale_paths", [])})
        coverage_receipts.extend(
            _unique_strings(
                ((receipt.get("coverage") or {}).get("owned_plan_node_ids", [])
                 or (receipt.get("coverage") or {}).get("plan_node_ids", []))
            )
        )

    missing_coverage = sorted(set(plan["required_coverage_ids"]) - set(coverage_receipts))
    duplicate_coverage = sorted(set(plan["duplicate_coverage_ids"]))
    route_artifact = parent_verification_applicability if isinstance(parent_verification_applicability, dict) else None
    routes = _integration_routes_from_applicability(route_artifact, value, contract)
    route_hash = canonical_hash({
        "schema_version": SCHEMA_VERSION,
        "parent_id": value.get("id") or value.get("task_id"),
        "parent_contract_hash": contract.get("contract_hash"),
        "routes": routes,
    })
    reason = None
    if not authority_valid or authority_failure:
        reason = NOT_READY_STALE_AUTHORITY
    elif unauthorized_mutations or scope_violations or dnt_violations:
        reason = NOT_READY_PROVENANCE_VIOLATION
    elif failures:
        reason = NOT_READY_CHILD_FAILURE
    elif stale:
        reason = NOT_READY_STALE_EVIDENCE
    elif pending or missing_receipts or invalid_receipts:
        reason = NOT_READY_CHILD_UNVERIFIED
    elif plan["duplicate_child_ids"] or duplicate_coverage or missing_coverage:
        reason = NOT_READY_COVERAGE_GAP
    state = READY if reason is None and bool(plan["required_child_ids"]) else NOT_READY
    if not plan["required_child_ids"] and reason is None:
        reason = NOT_READY_COVERAGE_GAP
        state = NOT_READY
    child_receipt_refs = [
        {"child_id": child_id, "receipt_hash": (receipt_by_id.get(child_id) or {}).get("receipt_hash"),
         "verified": (receipt_by_id.get(child_id) or {}).get("verified") is True,
         "dependency_paths": [
             item.get("path") for item in ((receipt_by_id.get(child_id) or {}).get(
                 "evidence_dependency_fingerprint", {}
             ).get("paths", []) or [])
             if isinstance(item, dict) and item.get("path")
         ]}
        for child_id in plan["required_child_ids"]
    ]
    result = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "IntegrationReadinessGate",
        "model_calls": 0,
        "status": state if state == READY else INTEGRATION_NOT_READY,
        "readiness": state,
        "reason": reason,
        "parent_id": str(value.get("id") or value.get("task_id") or ""),
        "parent_contract_hash": contract.get("contract_hash"),
        "required_child_ids": list(plan["required_child_ids"]),
        "optional_child_ids": list(plan["optional_child_ids"]),
        "terminal_child_statuses": terminal_statuses,
        "child_receipts": child_receipt_refs,
        "failures": sorted(failures),
        "pending_children": sorted(pending),
        "missing_receipts": sorted(missing_receipts),
        "unverified_children": sorted(set(invalid_receipts)),
        "stale_evidence": stale,
        "coverage": {
            "source": plan["source"], "required_coverage_ids": plan["required_coverage_ids"],
            "received_coverage_ids": sorted(set(coverage_receipts)),
            "missing_coverage_ids": missing_coverage,
            "duplicate_coverage_ids": duplicate_coverage,
            "complete": not missing_coverage and not duplicate_coverage and not plan["duplicate_child_ids"],
        },
        "freshness": {
            "all_fresh": not stale,
            "stale_child_ids": [item.get("child_id") for item in stale],
            "stale_evidence": stale,
        },
        "integration_routes": routes,
        "integration_routes_hash": route_hash,
        "integration_executor_calls": 0,
        "authority": {
            "valid": bool(authority_valid and not authority_failure),
            "failure": authority_failure,
            "unauthorized_mutations": int(unauthorized_mutations or 0),
            "scope_violations": int(scope_violations or 0),
            "dnt_violations": int(dnt_violations or 0),
        },
    }
    record = _without(result, "readiness_hash")
    result["readiness_hash"] = canonical_hash(record)
    return result


run_integration_readiness_gate = assess_integration_readiness
integration_readiness_gate = assess_integration_readiness


def _parse_execution_result(value: Any) -> tuple[str | None, bool]:
    if isinstance(value, dict):
        if value.get("verification_status") == SKIPPED_NOT_APPLICABLE or value.get("result") == SKIPPED_NOT_APPLICABLE:
            return None, False
        if value.get("passed") is True:
            return PASS, True
        if value.get("passed") is False:
            return FAIL, True
    text = str(value or "")
    try:
        parsed = json.loads(text)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict):
        if parsed.get("verification_status") == SKIPPED_NOT_APPLICABLE or parsed.get("result") == SKIPPED_NOT_APPLICABLE:
            return None, False
        if parsed.get("passed") is True:
            return PASS, True
        if parsed.get("passed") is False:
            return FAIL, True
    if re.search(r"\[exit_code=0\]", text, re.IGNORECASE) or re.search(r"\b(?:pass|passed|success|succeeded)\b", text, re.IGNORECASE):
        return PASS, True
    if re.search(r"\[exit_code=[1-9]\d*\]", text, re.IGNORECASE) or re.search(r"\b(?:fail|failed|failure|syntaxerror|assertionerror)\b", text, re.IGNORECASE):
        return FAIL, True
    return None, False


def _integration_evidence_matches(route: dict, item: dict) -> bool:
    tool = str(item.get("tool", ""))
    if tool not in {"run_file", "run_command", "verify_web_app"}:
        return False
    if route.get("kind") == "BROWSER":
        return tool == "verify_web_app"
    target = str(route.get("target") or "").replace("\\", "/").casefold()
    text = " ".join(str(item.get(key, "")) for key in ("target", "path", "command", "result")).replace("\\", "/").casefold()
    return bool(target and target in text) or (not target and tool in {"run_file", "run_command"})


def _parent_receipt(
    parent: dict,
    contract: dict,
    readiness: dict,
    routes: list[dict],
    route_results: list[dict],
    integration_evidence: list[dict],
    workspace: str | os.PathLike | None,
) -> dict:
    child_refs = [
        {"child_id": item.get("child_id"), "receipt_hash": item.get("receipt_hash")}
        for item in readiness.get("child_receipts", []) or []
    ]
    dependency_paths: list[str] = []
    for item in readiness.get("child_receipts", []) or []:
        if isinstance(item, dict):
            dependency_paths.extend(item.get("dependency_paths", []) or [])
    for item in integration_evidence:
        if isinstance(item, dict):
            dependency_paths.extend(
                _path_like_values(
                    [item.get("target"), item.get("path"), item.get("command")],
                    workspace,
                )
            )
    dependency_paths = sorted(set(dependency_paths), key=str.casefold)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": PARENT_RECEIPT_TYPE,
        "parent_id": str(parent.get("id") or parent.get("task_id") or ""),
        "verified": True,
        "receipt_status": PARENT_VERIFIED,
        "parent_contract_hash": contract.get("contract_hash"),
        "plan_hash": contract.get("plan_hash") or parent.get("approved_plan_hash"),
        "readiness_hash": readiness.get("readiness_hash"),
        "child_receipts": child_refs,
        "child_receipt_hashes": [item.get("receipt_hash") for item in child_refs],
        "integration_routes": [_route_projection(item) for item in routes],
        "integration_route_results": [_route_projection(item) for item in route_results],
        "integration_evidence": compact_verification_evidence(integration_evidence),
        "parent_contract_id": contract.get("execution_contract_id") or parent.get("id") or parent.get("task_id"),
        "subject_state": fingerprint_dependency_paths(workspace, dependency_paths),
        "provenance": {
            "source": "deterministic_parent_integration_evidence",
            "model_calls": 0, "raw_worker_transcript_included": False,
            "child_receipts_mutated": False, "memory_promotion": False,
        },
    }
    payload["receipt_hash"] = canonical_hash(payload)
    return copy.deepcopy(payload)


def aggregate_parent_integration(
    parent: dict | None,
    parent_contract: dict | None,
    readiness: dict | None,
    integration_evidence: Iterable[dict] | None = None,
    *,
    workspace: str | os.PathLike | None = None,
) -> dict:
    """Aggregate parent integration evidence after a READY gate only."""
    value = parent if isinstance(parent, dict) else {}
    contract = parent_contract if isinstance(parent_contract, dict) else {}
    gate = readiness if isinstance(readiness, dict) else {}
    evidence = [item for item in (integration_evidence or []) if isinstance(item, dict)]
    if gate.get("readiness") != READY and gate.get("status") != READY:
        return {
            "status": INTEGRATION_NOT_READY, "integration_result": INTEGRATION_NOT_READY,
            "parent_verified": False, "integration_executor_calls": 0,
            "model_calls": 0, "browser_verifier_calls": 0,
            "readiness": copy.deepcopy(gate), "summary": "parent integration was not ready",
        }
    routes = [item for item in gate.get("integration_routes", []) if isinstance(item, dict)]
    route_results: list[dict] = []
    required_passes = []
    required_failures = []
    required_missing = []
    optional_skips = []
    for route in routes:
        route_copy = copy.deepcopy(route)
        if route_copy.get("required") is False and (
            route_copy.get("result") == SKIPPED_NOT_APPLICABLE
            or route_copy.get("applicable") is False
        ):
            route_copy["result"] = SKIPPED_NOT_APPLICABLE
            optional_skips.append(route_copy)
            route_results.append(route_copy)
            continue
        if route_copy.get("required") and not route_copy.get("target"):
            route_copy["result"] = REQUIRED_INTEGRATION_TARGET_UNRESOLVED
            required_missing.append(route_copy)
            route_results.append(route_copy)
            continue
        matched: list[str] = []
        for item in evidence:
            if not _integration_evidence_matches(route_copy, item):
                continue
            state, actual = _parse_execution_result(item.get("result"))
            if actual and state:
                matched.append(state)
        if FAIL in matched:
            route_copy["result"] = FAIL
            if route_copy.get("required") and route_copy.get("applicable"):
                required_failures.append(route_copy)
        elif PASS in matched:
            route_copy["result"] = PASS
            if route_copy.get("required") and route_copy.get("applicable"):
                required_passes.append(route_copy)
        else:
            route_copy["result"] = PENDING
        route_results.append(route_copy)
    if required_missing:
        return {
            "status": INTEGRATION_FAILED, "integration_result": INTEGRATION_FAILED,
            "failure_type": REQUIRED_INTEGRATION_TARGET_UNRESOLVED,
            "parent_verified": False, "integration_executor_calls": 1,
            "model_calls": 0, "browser_verifier_calls": 0,
            "routes": route_results, "required_target_failures": required_missing,
            "optional_skips": optional_skips,
            "integration_evidence": compact_verification_evidence(evidence),
            "summary": "required integration target is unresolved",
        }
    if required_failures:
        return {
            "status": INTEGRATION_FAILED, "integration_result": INTEGRATION_FAILED,
            "parent_verified": False, "integration_executor_calls": 1,
            "model_calls": 0, "browser_verifier_calls": 0,
            "routes": route_results, "required_failures": required_failures,
            "optional_skips": optional_skips,
            "integration_evidence": compact_verification_evidence(evidence),
            "summary": "required integration verification failed",
        }
    required_routes = [item for item in routes if item.get("required") and item.get("applicable")]
    if not required_passes or not required_routes or len(required_passes) < len(required_routes):
        return {
            "status": INTEGRATION_EVIDENCE_UNAVAILABLE,
            "integration_result": INTEGRATION_EVIDENCE_UNAVAILABLE,
            "parent_verified": False, "integration_executor_calls": 1,
            "model_calls": 0, "browser_verifier_calls": 0,
            "routes": route_results, "optional_skips": optional_skips,
            "integration_evidence": compact_verification_evidence(evidence),
            "summary": "no real successful required integration evidence was available",
        }
    receipt = _parent_receipt(value, contract, gate, routes, route_results, evidence, workspace)
    return {
        "status": PARENT_VERIFIED, "integration_result": PARENT_VERIFIED,
        "parent_verified": True, "integration_executor_calls": 1,
        "model_calls": 0, "browser_verifier_calls": 0,
        "routes": route_results, "optional_skips": optional_skips,
        "integration_evidence": compact_verification_evidence(evidence),
        "parent_verification_receipt": receipt,
        "summary": "parent integration verified by real required evidence",
    }


aggregate_integration_evidence = aggregate_parent_integration
run_parent_integration = aggregate_parent_integration


def receipt_contains_private_transcript(value: Any) -> bool:
    """Audit helper used by deterministic tests and report generation."""
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).casefold()
            if key_text in _PRIVATE_KEYS:
                return True
            if key_text in {"raw_worker_transcript_included", "child_receipts_mutated"} and item is not False:
                return True
            if receipt_contains_private_transcript(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(receipt_contains_private_transcript(item) for item in value)
    if isinstance(value, str):
        lower = value.casefold()
        return any(token in lower for token in ("chain_of_thought", "private reasoning", "raw worker transcript"))
    return False


__all__ = [name for name in globals() if not name.startswith("_")]
