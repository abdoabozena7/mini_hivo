"""Deterministic V22 Stage 5C verified-state promotion.

This module is the boundary between execution evidence and durable project
memory.  It deliberately consumes only the V21 parent receipt, the approved
contract, and bounded integration evidence.  It never calls a model and it
never stores a Worker transcript, planner advice, or an unvalidated claim.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from hivo.integration_gate import (
    PARENT_RECEIPT_TYPE,
    PARENT_VERIFIED,
    PASS,
    SCHEMA_VERSION as V21_SCHEMA_VERSION,
    SKIPPED_NOT_APPLICABLE,
    canonical_hash,
    fingerprint_dependency_paths,
    receipt_contains_private_transcript,
    validate_verified_child_receipt,
)


SCHEMA_VERSION = "V22.5C"
CANDIDATE_TYPE = "PromotionCandidate"
PROMOTION_RECEIPT_TYPE = "PromotionReceipt"

PROMOTION_ELIGIBLE = "PROMOTION_ELIGIBLE"
PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED = "PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED"
PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT = "PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT"
PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE = "PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE"
PROMOTION_NOT_ELIGIBLE_AUTHORITY = "PROMOTION_NOT_ELIGIBLE_AUTHORITY"
PROMOTION_NOT_ELIGIBLE_PROVENANCE = "PROMOTION_NOT_ELIGIBLE_PROVENANCE"
PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION = "PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION"
PROMOTION_CONFLICT = "PROMOTION_CONFLICT"
PROMOTION_STORAGE_UNAVAILABLE = "PROMOTION_STORAGE_UNAVAILABLE"
PROMOTED = "PROMOTED"
ALREADY_PROMOTED = "ALREADY_PROMOTED"
NO_OP = "NO_OP"

DURABLE_VERIFIED = "DURABLE_VERIFIED"
STATE_BOUND_VERIFIED = "STATE_BOUND_VERIFIED"
EPHEMERAL_EXECUTION = "EPHEMERAL_EXECUTION"
VERIFIED_EXECUTION_FACT = "VERIFIED_EXECUTION_FACT"
VERIFIED_INTEGRATION_FACT = "VERIFIED_INTEGRATION_FACT"

MAX_CANDIDATE_FACTS = 48
MAX_FACT_CHARS = 900
MAX_FACT_EVIDENCE_REFS = 24
MAX_ARTIFACT_REFS = 24
MAX_PROJECT_BRAIN_RECORDS = 256

_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_transcript", "private_reasoning", "raw_worker_output", "raw_content",
    "worker_output", "model_output", "mission_compiler_output", "task_fit_output",
    "decomposer_output", "decomposer_prose", "raw_model_output", "raw_model_transcript",
    "falsifier_output", "strategy_output", "strategy_text", "repair_output",
    "repair_speculation",
})
_PRIVATE_MARKERS = (
    "chain_of_thought", "private reasoning", "raw worker transcript",
    "raw_worker_output", "worker output", "worker transcript", "worker said done", "model output",
    "model transcript", "raw model", "missioncompiler", "mission compiler output",
    "decomposer", "task-fit", "task fit", "falsifier", "strategy text",
    "strategy output", "strategy transcript", "repair speculation", "repairer output",
    "repair transcript", "repair output",
)
_FACT_FIELDS = {
    "verified_facts": (
        "verified_facts", "facts", "verified_behaviors", "state_ownership",
        "current_state_ownership", "verified_state_ownership", "verified_invariants",
        "invariants",
    ),
    "verified_interfaces": (
        "verified_interfaces", "verified_interface_behaviors", "interfaces",
        "interfaces_to_reuse", "interface_contracts",
    ),
    "verified_preservations": (
        "verified_preservations", "preservations", "preservation_only_surfaces",
        "local_preservation_constraints", "preservation_constraints", "preserve",
        "preserves",
    ),
    "verified_prohibitions": (
        "verified_prohibitions", "prohibitions", "prohibition_constraints",
        "structured_prohibitions", "global_do_not_touch", "do_not_touch",
    ),
}
_ALLOWED_FACT_KEYS = frozenset({
    "fact", "text", "id", "requirement_id", "field", "kind", "category", "path",
    "paths", "symbol", "authority", "provenance", "source", "verified", "approved",
    "authority_source", "subject", "predicate", "object", "value", "description", "name",
    "evidence_hash", "evidence_hashes",
    "conflict_key", "dependency_paths", "evidence_refs", "evidence", "durability_class",
    "subject_state_hash", "fact_hash", "semantic_hash", "record_id", "supersedes", "result",
})
_FACT_CATEGORY_ORDER = (
    "verified_facts", "verified_interfaces", "verified_preservations", "verified_prohibitions",
    "verified_tests",
)
_ALLOWED_CANDIDATE_KEYS = frozenset({
    "schema_version", "artifact_type", "candidate_id", "project_id", "parent_id",
    "source", "subject_state_hash", "subject_state_paths", "artifact_refs",
    "supersedes", "provenance", "fact_count", "candidate_hash", "authority_change",
} | set(_FACT_CATEGORY_ORDER))


class PromotionEligibilityError(ValueError):
    """Raised only when an explicitly requested promotion is ineligible."""

    def __init__(self, status: str, details: dict | None = None):
        self.status = str(status)
        self.details = copy.deepcopy(details or {})
        super().__init__(self.status)


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _compact(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _unique_strings(values: Iterable[Any], limit: int = 120, chars: int = 240) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("path") or value.get("target") or value.get("id") or value.get("fact") or ""
        text = _compact(value, chars).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _bounded_value(value: Any, limit: int = MAX_FACT_CHARS) -> Any:
    if isinstance(value, str):
        return _compact(value, limit)
    if isinstance(value, dict):
        return {
            str(key): _bounded_value(item, min(limit, 260))
            for key, item in list(value.items())[:16]
            if not _private_key(key)
        }
    if isinstance(value, (list, tuple, set)):
        return [_bounded_value(item, min(limit, 260)) for item in list(value)[:16]]
    return value


def _private_key(key: Any) -> bool:
    normalized = str(key).casefold().replace("-", "_")
    if normalized == "raw_worker_transcript_included":
        return False
    if normalized in _PRIVATE_KEYS:
        return True
    return any(marker in normalized for marker in (
        "transcript", "chain_of_thought", "private_reasoning", "raw_worker",
        "raw_model", "worker_output", "model_output", "missioncompiler",
        "mission_compiler", "decomposer", "task_fit", "falsifier", "strategy_output",
        "repair_output", "repair_speculation",
    ))


def contains_forbidden_transcript(value: Any) -> bool:
    """Return true for private/raw execution content, including nested data."""
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() == "raw_worker_transcript_included" and item is not False:
                return True
            if _private_key(key):
                return True
            if contains_forbidden_transcript(item):
                return True
        return False
    if isinstance(value, (list, tuple, set)):
        return any(contains_forbidden_transcript(item) for item in value)
    if isinstance(value, str):
        lower = value.casefold()
        return any(marker in lower for marker in _PRIVATE_MARKERS)
    return False


def _path_from_value(value: Any) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            for key in ("path", "target", "file", "entrypoint"):
                result.extend(_path_from_value(item.get(key)))
            continue
        text = str(item or "").strip().replace("\\", "/")
        if not text:
            continue
        if re.search(r"\.(?:c|cc|cpp|css|go|h|html?|java|js|jsx|json|mjs|cjs|py|rs|ts|tsx|toml|ya?ml)$", text, re.I):
            result.append(text.lstrip("./"))
    return _unique_strings(result, 48, 220)


def _subject_paths(receipt: dict) -> list[str]:
    fingerprint = receipt.get("subject_state")
    if not isinstance(fingerprint, dict):
        fingerprint = receipt.get("verified_subject_state")
    return _unique_strings(
        (
            item.get("path") for item in (fingerprint or {}).get("paths", [])
            if isinstance(item, dict) and item.get("path")
        ), 48, 220,
    )


def _subject_state_match(receipt: dict, workspace: str | Path | None) -> dict:
    stored = receipt.get("subject_state")
    if not isinstance(stored, dict):
        stored = receipt.get("verified_subject_state")
    if not isinstance(stored, dict) or not stored.get("hash"):
        return {"fresh": False, "reason": "MISSING_SUBJECT_STATE", "stale_paths": []}
    if workspace is None:
        return {"fresh": False, "reason": "MISSING_WORKSPACE", "stale_paths": []}
    current = fingerprint_dependency_paths(workspace, _subject_paths(receipt))
    stored_records = {
        str(item.get("path")): item for item in stored.get("paths", []) if isinstance(item, dict)
    }
    current_records = {
        str(item.get("path")): item for item in current.get("paths", []) if isinstance(item, dict)
    }
    stale_paths = sorted(
        path for path in set(stored_records) | set(current_records)
        if stored_records.get(path) != current_records.get(path)
    )
    return {
        "fresh": bool(stored.get("hash") == current.get("hash") and not stale_paths),
        "stored_hash": stored.get("hash"), "current_hash": current.get("hash"),
        "stale_paths": stale_paths, "fingerprint": current,
        "reason": None if stored.get("hash") == current.get("hash") and not stale_paths
        else "SUBJECT_STATE_CHANGED",
    }


def _parse_evidence_result(value: Any) -> tuple[str | None, bool]:
    if isinstance(value, dict):
        if value.get("verification_status") == SKIPPED_NOT_APPLICABLE or value.get("result") == SKIPPED_NOT_APPLICABLE:
            return None, False
        if value.get("passed") is True:
            return PASS, True
        if value.get("passed") is False:
            return "FAIL", True
    text = str(value or "")
    if re.search(r"\[exit_code=0\]", text, re.I) or re.search(r"\b(?:pass|passed|success|succeeded)\b", text, re.I):
        return PASS, True
    if re.search(r"\[exit_code=[1-9]\d*\]", text, re.I) or re.search(r"\b(?:fail|failed|failure|syntaxerror|assertionerror)\b", text, re.I):
        return "FAIL", True
    return None, False


def _integration_evidence_passes(route: dict, evidence: Iterable[dict]) -> bool:
    if not isinstance(route, dict) or route.get("required") is not True or route.get("applicable") is not True:
        return False
    if route.get("result") != PASS:
        return False
    target = str(route.get("target") or "").replace("\\", "/").casefold()
    for item in evidence or []:
        if not isinstance(item, dict) or item.get("tool") not in {"run_file", "run_command", "verify_web_app"}:
            continue
        if route.get("kind") != "BROWSER" and item.get("tool") == "verify_web_app":
            continue
        text = " ".join(str(item.get(key, "")) for key in ("target", "path", "command", "result")).replace("\\", "/").casefold()
        if target and target not in text:
            continue
        state, actual = _parse_evidence_result(item.get("result"))
        if actual and state == PASS:
            return True
    return False


def _receipt_map(receipts: Any) -> dict[str, dict]:
    if isinstance(receipts, dict):
        if receipts.get("child_id"):
            return {str(receipts.get("child_id")): receipts}
        return {str(key): item for key, item in receipts.items() if isinstance(item, dict)}
    return {
        str(item.get("child_id")): item for item in (receipts or [])
        if isinstance(item, dict) and item.get("child_id")
    }


def _parent_status(parent: dict | None, receipt: dict | None) -> str:
    value = parent if isinstance(parent, dict) else {}
    record = receipt if isinstance(receipt, dict) else {}
    return str(
        value.get("integration_result") or value.get("parent_status")
        or record.get("receipt_status") or record.get("status") or ""
    ).upper()


def _violation_counts(*sources: dict | None, authority_valid: bool = True,
                      unauthorized_mutations: int = 0, scope_violations: int = 0,
                      dnt_violations: int = 0) -> dict[str, int]:
    counts = {
        "unauthorized_mutations": max(0, int(unauthorized_mutations or 0)),
        "scope_violations": max(0, int(scope_violations or 0)),
        "dnt_violations": max(0, int(dnt_violations or 0)),
    }
    for source in sources:
        if not isinstance(source, dict):
            continue
        counts["unauthorized_mutations"] = max(
            counts["unauthorized_mutations"], int(source.get("unauthorized_mutations", 0) or source.get("unauthorized_mutation_count", 0) or 0),
        )
        counts["scope_violations"] = max(
            counts["scope_violations"], int(source.get("scope_violations", 0) or source.get("out_of_scope_mutations", 0) or 0),
        )
        counts["dnt_violations"] = max(
            counts["dnt_violations"], int(source.get("dnt_violations", 0) or source.get("do_not_touch_violations", 0) or 0),
        )
        failure_type = str(source.get("failure_type") or source.get("orchestration_failure") or "").upper()
        if "UNAUTHORIZED" in failure_type:
            counts["unauthorized_mutations"] = max(counts["unauthorized_mutations"], 1)
        if "SCOPE" in failure_type:
            counts["scope_violations"] = max(counts["scope_violations"], 1)
        if "DO_NOT_TOUCH" in failure_type or failure_type == "DNT":
            counts["dnt_violations"] = max(counts["dnt_violations"], 1)
    if not authority_valid:
        counts["authority_invalid"] = 1
    return counts


def _authority_is_stale(*sources: dict | None) -> bool:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("authority_stale", "stale_authority", "approved_plan_stale", "plan_stale"):
            if source.get(key) is True:
                return True
        status = str(source.get("authority_status") or source.get("execution_status") or "").upper()
        if "STALE" in status:
            return True
    return False


def _expected_child_contracts(parent_contract: dict, child_receipts: Any) -> dict[str, dict]:
    result: dict[str, dict] = {}
    plan = parent_contract.get("validated_child_plan") or parent_contract.get("validated_children") or parent_contract.get("child_plan")
    if isinstance(plan, dict):
        plan = plan.get("children") or plan.get("required_children") or plan.get("nodes") or []
    for item in plan if isinstance(plan, (list, tuple)) else []:
        if not isinstance(item, dict):
            continue
        child_id = str(item.get("child_id") or item.get("task_id") or item.get("id") or "")
        if child_id:
            result[child_id] = item
    for child_id, item in _receipt_map(child_receipts).items():
        if isinstance(item.get("task"), dict):
            result.setdefault(child_id, item["task"])
        elif isinstance(item.get("execution_contract"), dict):
            result.setdefault(child_id, item["execution_contract"])
    return result


def _required_child_ids(parent_receipt: dict, parent_contract: dict, child_receipts: Any) -> list[str]:
    plan = parent_contract.get("validated_child_plan") or parent_contract.get("validated_children") or parent_contract.get("child_plan")
    entries: list[Any] = []
    if isinstance(plan, dict):
        entries = plan.get("children") or plan.get("required_children") or plan.get("nodes") or []
    elif isinstance(plan, (list, tuple)):
        entries = list(plan)
    if entries:
        ids = [str(item.get("child_id") or item.get("task_id") or item.get("id") or "") for item in entries if isinstance(item, dict) and item.get("required") is not False and item.get("optional") is not True]
        return sorted({item for item in ids if item})
    refs = parent_receipt.get("child_receipts") or []
    ids = [str(item.get("child_id") or item.get("task_id") or "") for item in refs if isinstance(item, dict)]
    if not ids:
        ids = list(_receipt_map(child_receipts))
    return sorted({item for item in ids if item})


def validate_parent_verification_receipt(
    parent_receipt: dict | None,
    *,
    parent: dict | None = None,
    parent_result: dict | None = None,
    parent_contract: dict | None = None,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    authority_valid: bool = True,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
) -> dict:
    """Validate the V21 parent receipt and its current subject before promotion."""
    value = parent_receipt if isinstance(parent_receipt, dict) else {}
    contract = parent_contract if isinstance(parent_contract, dict) else {}
    parent_value = parent if isinstance(parent, dict) else {}
    parent_result_value = parent_result if isinstance(parent_result, dict) else {}
    errors: list[str] = []
    stale_receipt = False
    stale_subject = False
    if value.get("artifact_type") != PARENT_RECEIPT_TYPE:
        errors.append("wrong parent receipt artifact type")
    if value.get("schema_version") != V21_SCHEMA_VERSION:
        errors.append("wrong parent receipt schema version")
    if value.get("receipt_hash") != canonical_hash(_without(value, "receipt_hash")):
        errors.append("parent receipt hash does not match canonical contents")
        stale_receipt = True
    if value.get("verified") is not True or value.get("receipt_status") != PARENT_VERIFIED:
        errors.append("parent is not PARENT_VERIFIED")
    allowed_parent_states = {"PARENT_VERIFIED", "DONE", "VERIFIED", "SUCCESS", "PASS", "COMPLETED"}
    for source in (parent_value, parent_result if isinstance(parent_result, dict) else {}):
        for key in ("integration_result", "parent_status", "status"):
            state = str(source.get(key) or "").upper()
            if state and state not in allowed_parent_states:
                errors.append("parent result is not PARENT_VERIFIED")
                break
    if contract.get("contract_hash") is not None and value.get("parent_contract_hash") != contract.get("contract_hash"):
        errors.append("parent contract hash mismatch")
    if contract.get("plan_hash") is not None and value.get("plan_hash") != contract.get("plan_hash"):
        errors.append("parent plan hash mismatch")
    expected_parent_id = (
        parent_value.get("id") or parent_value.get("task_id")
        or parent_result_value.get("id") or parent_result_value.get("task_id")
        or contract.get("execution_contract_id")
    )
    if expected_parent_id and value.get("parent_id") and str(value.get("parent_id")) != str(expected_parent_id):
        errors.append("parent id mismatch")
    if receipt_contains_private_transcript(value) or contains_forbidden_transcript(value):
        errors.append("parent receipt contains private or raw provenance")
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    if provenance.get("raw_worker_transcript_included") is not False or int(provenance.get("model_calls", 0) or 0) != 0:
        errors.append("parent receipt provenance is not deterministic")
    counts = _violation_counts(
        value, parent_value, parent_result_value, contract, authority_valid=authority_valid,
        unauthorized_mutations=unauthorized_mutations,
        scope_violations=scope_violations, dnt_violations=dnt_violations,
    )
    if counts.get("authority_invalid") or _authority_is_stale(
        contract, parent_value, value, parent_result_value,
    ):
        errors.append("authority is invalid or stale")
    if counts["unauthorized_mutations"] or counts["scope_violations"] or counts["dnt_violations"]:
        errors.append("provenance or scope violation")

    subject = _subject_state_match(value, workspace)
    if not subject.get("fresh"):
        stale_subject = True
        errors.append("parent subject state is stale")

    receipt_by_id = _receipt_map(child_receipts)
    expected_contracts = _expected_child_contracts(contract, child_receipts)
    required_ids = _required_child_ids(value, contract, child_receipts)
    listed_refs = {
        str(item.get("child_id") or item.get("task_id")): item
        for item in value.get("child_receipts", []) or [] if isinstance(item, dict)
    }
    listed_hashes = [item.get("receipt_hash") for item in value.get("child_receipts", []) or [] if isinstance(item, dict)]
    if listed_hashes != list(value.get("child_receipt_hashes", []) or []):
        errors.append("parent child receipt hash list mismatch")
        stale_receipt = True
    validated_child_ids: list[str] = []
    for child_id in required_ids:
        receipt = receipt_by_id.get(child_id)
        ref = listed_refs.get(child_id)
        if not isinstance(receipt, dict) or not isinstance(ref, dict):
            errors.append(f"missing required child receipt: {child_id}")
            continue
        if ref.get("receipt_hash") != receipt.get("receipt_hash"):
            errors.append(f"child receipt hash mismatch: {child_id}")
            stale_receipt = True
            continue
        expected = expected_contracts.get(child_id, {})
        execution_contract = expected.get("execution_contract") if isinstance(expected.get("execution_contract"), dict) else expected
        checked = validate_verified_child_receipt(
            receipt, workspace=workspace,
            expected_authority={
                "execution_contract_id": expected.get("execution_contract_id") or execution_contract.get("execution_contract_id"),
                "contract_hash": expected.get("contract_hash") or execution_contract.get("contract_hash"),
                "plan_hash": expected.get("plan_hash") or execution_contract.get("plan_hash"),
                "parent_contract_hash": contract.get("contract_hash"),
            },
        )
        if not checked.get("valid") or receipt.get("verified") is not True:
            errors.append(f"invalid required child receipt: {child_id}")
            if checked.get("stale_paths") or not checked.get("fresh"):
                stale_receipt = True
            continue
        validated_child_ids.append(child_id)
    for child_id, ref in listed_refs.items():
        if child_id not in required_ids or child_id in validated_child_ids:
            continue
        receipt = receipt_by_id.get(child_id)
        if not isinstance(receipt, dict) or ref.get("receipt_hash") != receipt.get("receipt_hash"):
            errors.append(f"invalid listed child receipt: {child_id}")
            stale_receipt = True
    routes = [item for item in value.get("integration_route_results", []) or [] if isinstance(item, dict)]
    if not routes:
        routes = [item for item in value.get("integration_routes", []) or [] if isinstance(item, dict)]
    evidence = [item for item in value.get("integration_evidence", []) or [] if isinstance(item, dict)]
    required_routes = [item for item in routes if item.get("required") is True and item.get("applicable") is True]
    if not required_routes:
        errors.append("no required parent integration route")
    for route in required_routes:
        if route.get("result") != PASS or not _integration_evidence_passes(route, evidence):
            errors.append("required parent integration evidence is not a real PASS")
    for route in routes:
        if route.get("kind") == "BROWSER" and route.get("required") is False and route.get("applicable") is False:
            if route.get("result") != SKIPPED_NOT_APPLICABLE:
                errors.append("optional browser route is not SKIPPED_NOT_APPLICABLE")
            continue
        if route.get("required") is True and not route.get("target"):
            errors.append("required integration target is unresolved")
    result = {
        "valid": not errors,
        "eligible": not errors,
        "errors": list(dict.fromkeys(errors))[:40],
        "parent_status": _parent_status(parent_result_value or parent_value, value),
        "parent_verification_hash": value.get("receipt_hash"),
        "required_child_ids": required_ids,
        "validated_child_ids": validated_child_ids,
        "subject_state": subject,
        "stale_receipt": bool(stale_receipt),
        "stale_subject_state": bool(stale_subject),
        "required_integration_routes": copy.deepcopy(required_routes),
        "integration_evidence": copy.deepcopy(evidence[:MAX_ARTIFACT_REFS]),
        "violations": counts,
        "model_calls": 0,
    }
    return result


validate_parent_receipt = validate_parent_verification_receipt


def assess_promotion_eligibility(
    parent: dict | None = None,
    parent_receipt: dict | None = None,
    parent_contract: dict | None = None,
    *,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    authority_valid: bool = True,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
    parent_result: dict | None = None,
) -> dict:
    """Run the zero-model promotion eligibility gate."""
    receipt = parent_receipt if isinstance(parent_receipt, dict) else {}
    parent_value = parent if isinstance(parent, dict) else {}
    validation = validate_parent_verification_receipt(
        receipt, parent=parent_value, parent_contract=parent_contract,
        child_receipts=child_receipts, workspace=workspace,
        authority_valid=authority_valid,
        unauthorized_mutations=unauthorized_mutations,
        scope_violations=scope_violations, dnt_violations=dnt_violations,
        parent_result=parent_result,
    )
    if validation.get("valid"):
        status = PROMOTION_ELIGIBLE
    elif receipt.get("verified") is not True or receipt.get("receipt_status") != PARENT_VERIFIED:
        status = PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED
    elif validation.get("stale_subject_state"):
        status = PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE
    elif validation.get("stale_receipt"):
        status = PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT
    elif validation.get("violations", {}).get("authority_invalid") or _authority_is_stale(
        parent_contract or {}, parent_value, receipt, parent_result,
    ):
        status = PROMOTION_NOT_ELIGIBLE_AUTHORITY
    elif any(validation.get("violations", {}).get(key, 0) for key in ("unauthorized_mutations", "scope_violations", "dnt_violations")):
        status = PROMOTION_NOT_ELIGIBLE_SCOPE_VIOLATION
    elif any("provenance" in str(error).casefold() for error in validation.get("errors", [])):
        status = PROMOTION_NOT_ELIGIBLE_PROVENANCE
    else:
        status = PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED
    return {
        "eligible": bool(validation.get("valid")),
        "status": status,
        "promotion_status": status,
        "parent_status": validation.get("parent_status"),
        "parent_verification_hash": receipt.get("receipt_hash"),
        "receipt_validation": validation,
        "model_calls": 0,
    }


promotion_eligibility_gate = assess_promotion_eligibility
check_promotion_eligibility = assess_promotion_eligibility


def _fact_semantic_material(fact: dict) -> dict:
    return {
        "category": fact.get("category"),
        "field": fact.get("field"),
        "fact": fact.get("fact"),
        "authority": fact.get("authority"),
        "conflict_key": fact.get("conflict_key"),
    }


def _fact_conflict_key(fact: dict, category: str | None = None, field: str | None = None) -> str:
    explicit = str(fact.get("conflict_key") or "").strip()
    if explicit:
        return _compact(explicit, 220)
    category = str(category or fact.get("category") or "verified_facts")
    field = str(field or fact.get("field") or "fact")
    if field.casefold() in {
        "owner", "current_owner", "state_ownership", "current_state_ownership",
        "verified_state_ownership", "status_owner",
    }:
        # These are singleton authority surfaces.  A changed owner must enter
        # the explicit conflict/supersession path instead of becoming a new
        # unrelated fact merely because its text changed.
        return _compact(f"{category}:{field}", 320)
    text = re.sub(r"\s+", " ", str(fact.get("fact") or "").casefold()).strip()
    # A contract may contain multiple interfaces or preservation constraints.
    # Their semantic keys coexist by default; callers can opt into a stricter
    # conflict domain with an explicit conflict_key.
    return _compact(f"{category}:{field}:{text}", 320)


def _authority_value(value: Any) -> str:
    text = str(value or "").strip().upper().replace("_", "/")
    if text in {"USER", "USER/STATED", "USER/CONFIRMED", "USER/REQUIREMENT", "REQUIREMENT"}:
        return "USER/REQUIREMENT"
    if text == "VERIFIED/EVIDENCE":
        return "VERIFIED/EVIDENCE"
    # Promotion cannot elevate derived/model advice into project authority.
    return "USER/REQUIREMENT"


def _fact_value(value: Any) -> tuple[str, dict]:
    if isinstance(value, dict):
        if contains_forbidden_transcript(value):
            return "", {}
        text = value.get("fact") or value.get("text") or value.get("value") or value.get("description")
        if text is None:
            text = value.get("name") or value.get("symbol") or value.get("path")
        if text is None and any(key in value for key in ("subject", "predicate", "object")):
            text = json.dumps({
                key: value.get(key) for key in ("subject", "predicate", "object") if key in value
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        allowed = {
            str(key): _bounded_value(item, 260)
            for key, item in value.items()
            if str(key) in _ALLOWED_FACT_KEYS and str(key) not in {"fact_hash", "semantic_hash", "record_id"}
        }
        return _compact(text, MAX_FACT_CHARS), allowed
    return _compact(value, MAX_FACT_CHARS), {}


def _normalize_fact(
    value: Any,
    *,
    category: str,
    field: str,
    subject_state_hash: str,
    evidence_refs: Iterable[Any],
    dependency_paths: Iterable[Any],
    source: str,
    durability_class: str = STATE_BOUND_VERIFIED,
) -> dict | None:
    text, structured = _fact_value(value)
    if not text or contains_forbidden_transcript(value):
        return None
    if any(marker in text.casefold() for marker in _PRIVATE_MARKERS):
        return None
    provenance_text = " ".join(str(structured.get(key, "")) for key in ("authority", "provenance", "source")).upper()
    if any(marker in provenance_text for marker in ("DERIVED", "MODEL", "WORKER", "ADVICE", "DECOMPOSER", "FALSIFIER", "STRATEGY", "REPAIR")):
        return None
    explicit_conflict = structured.get("conflict_key")
    fact: dict[str, Any] = {
        "category": str(category),
        "field": str(field),
        "fact": text,
        "authority": _authority_value(structured.get("authority")),
        "authority_source": (
            "approved_requirement_field"
            if _authority_value(structured.get("authority")) == "USER/REQUIREMENT"
            else "verified_parent_verification_receipt"
        ),
        "source": str(source),
        "verified": True,
        "approved": True,
        "evidence_refs": _unique_strings(evidence_refs, MAX_FACT_EVIDENCE_REFS, 220),
        "dependency_paths": _unique_strings(dependency_paths, 48, 220),
        "subject_state_hash": str(subject_state_hash or ""),
        "durability_class": str(durability_class),
    }
    for key in (
        "requirement_id", "path", "symbol", "kind", "id", "subject", "predicate",
        "object", "evidence_hash", "evidence_hashes", "result",
    ):
        if structured.get(key) not in (None, ""):
            fact[key] = _bounded_value(structured[key], 220)
    if explicit_conflict:
        fact["conflict_key"] = _compact(explicit_conflict, 220)
    else:
        fact["conflict_key"] = _fact_conflict_key(fact, category, field)
    fact["semantic_hash"] = canonical_hash(_fact_semantic_material(fact))
    fact["fact_hash"] = canonical_hash(_without(fact, "fact_hash"))
    return fact


def _authority_values(contract: dict) -> Iterable[tuple[str, str, Any]]:
    sources = [contract]
    nested = contract.get("source_contract") if isinstance(contract.get("source_contract"), dict) else None
    if nested:
        sources.append(nested)
    for source in sources:
        for category, fields in _FACT_FIELDS.items():
            for field in fields:
                value = source.get(field)
                if value is None:
                    continue
                for item in _as_list(value):
                    yield category, field, item


def _evidence_refs(value: dict, artifact_refs: Iterable[Any] | None = None) -> list[str]:
    refs = [f"parent:{value.get('receipt_hash')}" if value.get("receipt_hash") else "parent:verification"]
    refs.extend(str(item) for item in artifact_refs or [])
    return _unique_strings(refs, MAX_ARTIFACT_REFS, 220)


def _build_candidate(
    parent: dict | None,
    parent_receipt: dict | None,
    parent_contract: dict | None,
    *,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    project_id: str = "default",
    artifact_refs: Iterable[Any] | None = None,
    supersedes: Iterable[Any] | None = None,
    authority_change: dict | None = None,
) -> dict:
    parent_value = parent if isinstance(parent, dict) else {}
    receipt = parent_receipt if isinstance(parent_receipt, dict) else {}
    contract = parent_contract if isinstance(parent_contract, dict) else {}
    subject_hash = str((receipt.get("subject_state") or {}).get("hash") or "")
    subject_paths = _subject_paths(receipt)
    evidence_refs = _unique_strings(
        [
            *_evidence_refs(receipt, artifact_refs),
            *[
                f"child_receipt:{item}" for item in receipt.get("child_receipt_hashes", []) or []
                if str(item).strip()
            ],
        ],
        MAX_ARTIFACT_REFS, 220,
    )
    categories: dict[str, list[dict]] = {category: [] for category in _FACT_CATEGORY_ORDER}
    seen_semantic: set[str] = set()
    for category, field, value in _authority_values(contract):
        fact = _normalize_fact(
            value, category=category, field=field, subject_state_hash=subject_hash,
            evidence_refs=[*evidence_refs, "integration:parent-required"], dependency_paths=subject_paths,
            source="approved_requirement_contract",
            durability_class=DURABLE_VERIFIED,
        )
        if not fact or fact["semantic_hash"] in seen_semantic:
            continue
        seen_semantic.add(fact["semantic_hash"])
        categories[category].append(fact)

    routes = [item for item in receipt.get("integration_route_results", []) or [] if isinstance(item, dict)]
    if not routes:
        routes = [item for item in receipt.get("integration_routes", []) or [] if isinstance(item, dict)]
    integration_evidence = [item for item in receipt.get("integration_evidence", []) or [] if isinstance(item, dict)]
    for index, route in enumerate(routes):
        if route.get("kind") == "BROWSER":
            # Browser skip/pass is a routing observation, never a promoted fact.
            continue
        if not _integration_evidence_passes(route, integration_evidence):
            continue
        fact = _normalize_fact(
            {
                "fact": (
                    f"Required {route.get('kind', 'integration')} verification passed"
                    f" on {route.get('target') or '(target recorded in parent receipt)'}"
                ),
                "kind": VERIFIED_INTEGRATION_FACT,
                "authority": "VERIFIED/EVIDENCE",
                "path": route.get("target"),
                "result": PASS,
                "evidence_hash": canonical_hash({
                    "route": route,
                    "result": PASS,
                }),
                "conflict_key": f"integration:{route.get('kind')}:{route.get('target')}",
            },
            category="verified_tests", field="integration_test_evidence",
            subject_state_hash=subject_hash, evidence_refs=[*evidence_refs, f"integration:{index}"],
            dependency_paths=[*subject_paths, *_path_from_value(route.get("target"))],
            source="verified_parent_integration_evidence", durability_class=STATE_BOUND_VERIFIED,
        )
        if fact and fact["semantic_hash"] not in seen_semantic:
            seen_semantic.add(fact["semantic_hash"])
            categories["verified_tests"].append(fact)

    for category in categories:
        categories[category].sort(key=lambda item: (str(item.get("field")), str(item.get("semantic_hash"))))
        categories[category] = categories[category][:MAX_CANDIDATE_FACTS]
    all_facts = [fact for category in _FACT_CATEGORY_ORDER for fact in categories[category]]
    source = {
        "parent_verification_hash": receipt.get("receipt_hash"),
        "parent_contract_hash": contract.get("contract_hash"),
        "plan_hash": contract.get("plan_hash") or receipt.get("plan_hash"),
        "child_receipt_hashes": sorted(str(item) for item in receipt.get("child_receipt_hashes", []) or []),
        "authority_preserved": True,
        "approved_authority_change": bool(isinstance(authority_change, dict) and authority_change.get("approved") is True),
    }
    if isinstance(authority_change, dict) and authority_change.get("approved") is True:
        source["authority_change"] = _bounded_value(authority_change, 500)
    candidate: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": CANDIDATE_TYPE,
        "candidate_id": "",
        "project_id": str(project_id or "default"),
        "parent_id": parent_value.get("id") or parent_value.get("task_id") or receipt.get("parent_id"),
        "source": source,
        "subject_state_hash": subject_hash,
        "subject_state_paths": subject_paths,
        "artifact_refs": _unique_strings(artifact_refs or [], MAX_ARTIFACT_REFS, 220),
        **categories,
        "supersedes": _unique_strings(supersedes or [], MAX_ARTIFACT_REFS, 220),
        "provenance": {
            "source": "deterministic_verified_parent_receipt",
            "model_calls": 0,
            "raw_worker_transcript_included": False,
            "authority_escalation": False,
            "cross_project_memory": False,
            "strategy_learning": False,
            "auto_reverification": False,
        },
    }
    if isinstance(authority_change, dict) and authority_change.get("approved") is True:
        candidate["authority_change"] = _bounded_value(authority_change, 700)
    candidate["fact_count"] = len(all_facts)
    candidate["candidate_hash"] = _candidate_identity_hash(candidate)
    candidate["candidate_id"] = f"candidate-{candidate['candidate_hash'][:24]}"
    # candidate_id is display metadata and is excluded from the identity, so
    # the hash prefix remains stable and self-consistent.
    return copy.deepcopy(candidate)


def validate_promotion_candidate(
    candidate: dict | None,
    *,
    parent: dict | None = None,
    parent_receipt: dict | None = None,
    parent_contract: dict | None = None,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    project_id: str = "default",
    authority_valid: bool = True,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
    parent_result: dict | None = None,
) -> dict:
    """Validate a candidate again immediately before any durable write."""
    value = candidate if isinstance(candidate, dict) else {}
    errors: list[str] = []
    unknown_candidate_keys = set(value) - set(_ALLOWED_CANDIDATE_KEYS)
    if unknown_candidate_keys:
        errors.append("promotion candidate contains an unapproved field")
    if value.get("artifact_type") != CANDIDATE_TYPE:
        errors.append("wrong promotion candidate artifact type")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong promotion candidate schema version")
    if value.get("candidate_hash") != _candidate_identity_hash(value):
        errors.append("promotion candidate hash does not match canonical contents")
    if value.get("candidate_hash") and value.get("candidate_id") != (
        f"candidate-{str(value.get('candidate_hash'))[:24]}"
    ):
        errors.append("promotion candidate id does not match its hash")
    if str(value.get("project_id") or "default") != str(project_id or "default"):
        errors.append("promotion candidate project mismatch")
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    if int(provenance.get("model_calls", 0) or 0) != 0 or provenance.get("raw_worker_transcript_included") is not False:
        errors.append("promotion candidate provenance is not deterministic")
    if provenance.get("authority_escalation") is True or provenance.get("cross_project_memory") is True:
        errors.append("promotion candidate attempts authority or project escalation")
    if contains_forbidden_transcript(value):
        errors.append("promotion candidate contains private or raw execution content")
    eligibility = assess_promotion_eligibility(
        parent, parent_receipt, parent_contract, child_receipts=child_receipts,
        workspace=workspace, authority_valid=authority_valid,
        unauthorized_mutations=unauthorized_mutations,
        scope_violations=scope_violations, dnt_violations=dnt_violations,
        parent_result=parent_result,
    )
    receipt = parent_receipt if isinstance(parent_receipt, dict) else {}
    contract = parent_contract if isinstance(parent_contract, dict) else {}
    source = value.get("source") if isinstance(value.get("source"), dict) else {}
    for field, expected in (
        ("parent_verification_hash", receipt.get("receipt_hash")),
        ("parent_contract_hash", contract.get("contract_hash")),
        ("plan_hash", contract.get("plan_hash") or receipt.get("plan_hash")),
    ):
        if expected is not None and source.get(field) != expected:
            errors.append(f"promotion source mismatch: {field}")
    if source.get("child_receipt_hashes") != sorted(str(item) for item in receipt.get("child_receipt_hashes", []) or []):
        errors.append("promotion child receipt source mismatch")
    if value.get("subject_state_hash") != (receipt.get("subject_state") or {}).get("hash"):
        errors.append("promotion subject state binding mismatch")
    try:
        expected_candidate = _fix_candidate_identity(_build_candidate(
            parent, parent_receipt, parent_contract,
            child_receipts=child_receipts, workspace=workspace,
            project_id=str(value.get("project_id") or "default"),
            artifact_refs=value.get("artifact_refs", []),
            supersedes=value.get("supersedes", []),
            authority_change=value.get("authority_change")
            if isinstance(value.get("authority_change"), dict) else None,
        ))
        for category in _FACT_CATEGORY_ORDER:
            if value.get(category) != expected_candidate.get(category):
                errors.append(f"promotion candidate coverage mismatch: {category}")
    except Exception:
        errors.append("promotion candidate coverage could not be deterministically reconstructed")
    total = 0
    has_integration = False
    for category in _FACT_CATEGORY_ORDER:
        facts = value.get(category)
        if not isinstance(facts, list):
            errors.append(f"candidate category is not a list: {category}")
            continue
        if len(facts) > MAX_CANDIDATE_FACTS:
            errors.append(f"candidate category exceeds bound: {category}")
        for fact in facts[:MAX_CANDIDATE_FACTS]:
            if not isinstance(fact, dict):
                errors.append("candidate fact is not structured")
                continue
            total += 1
            if fact.get("category") != category:
                errors.append("candidate fact category does not match its container")
            if set(fact) - _ALLOWED_FACT_KEYS:
                errors.append("candidate fact contains an unapproved field")
            if fact.get("verified") is not True or fact.get("approved") is not True:
                errors.append("candidate fact is not verified and approved")
            if fact.get("authority") not in {"USER/REQUIREMENT", "VERIFIED/EVIDENCE"}:
                errors.append("candidate fact authority is invalid")
            if fact.get("durability_class") not in {DURABLE_VERIFIED, STATE_BOUND_VERIFIED}:
                errors.append("candidate fact durability class is invalid")
            if len(str(fact.get("fact", ""))) > MAX_FACT_CHARS or not str(fact.get("fact", "")).strip():
                errors.append("candidate fact is empty or over bound")
            if not _unique_strings(fact.get("evidence_refs", []), MAX_FACT_EVIDENCE_REFS, 220):
                errors.append("candidate fact has no evidence reference")
            if fact.get("subject_state_hash") != value.get("subject_state_hash"):
                errors.append("candidate fact subject binding mismatch")
            if fact.get("fact_hash") != canonical_hash(_without(fact, "fact_hash")):
                errors.append("candidate fact hash mismatch")
            if fact.get("semantic_hash") != canonical_hash(_fact_semantic_material(fact)):
                errors.append("candidate fact semantic hash mismatch")
            if str(fact.get("kind", "")).upper() == "BROWSER" or "browser" in str(fact.get("field", "")).casefold():
                if fact.get("result") == PASS or "passed" in str(fact.get("fact", "")).casefold():
                    errors.append("browser PASS cannot be promoted as a fact")
            if fact.get("category") == "verified_tests" and fact.get("field") == "integration_test_evidence" and fact.get("durability_class") == STATE_BOUND_VERIFIED:
                has_integration = True
    if int(value.get("fact_count", total) or 0) != total:
        errors.append("candidate fact count mismatch")
    if total > MAX_CANDIDATE_FACTS * len(_FACT_CATEGORY_ORDER):
        errors.append("candidate exceeds total fact bound")
    if not has_integration:
        errors.append("candidate has no real required integration evidence fact")
    if not eligibility.get("eligible"):
        errors.append(f"promotion eligibility denied: {eligibility.get('status')}")
    return {
        "valid": not errors,
        "eligible": bool(eligibility.get("eligible") and not errors),
        "errors": list(dict.fromkeys(errors))[:60],
        "fact_count": total,
        "has_required_integration_evidence": has_integration,
        "eligibility": eligibility,
        "model_calls": 0,
    }


def build_promotion_candidate(
    parent: dict | None = None,
    parent_receipt: dict | None = None,
    parent_contract: dict | None = None,
    *,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    project_id: str = "default",
    artifact_refs: Iterable[Any] | None = None,
    supersedes: Iterable[Any] | None = None,
    authority_change: dict | None = None,
) -> dict:
    return _build_candidate(
        parent, parent_receipt, parent_contract,
        child_receipts=child_receipts, workspace=workspace, project_id=project_id,
        artifact_refs=artifact_refs, supersedes=supersedes,
        authority_change=authority_change,
    )


def create_promotion_candidate(*args, **kwargs) -> dict:
    parent = kwargs.get("parent") if "parent" in kwargs else (args[0] if args else None)
    receipt = kwargs.get("parent_receipt") if "parent_receipt" in kwargs else (args[1] if len(args) > 1 else None)
    contract = kwargs.get("parent_contract") if "parent_contract" in kwargs else (args[2] if len(args) > 2 else None)
    gate = assess_promotion_eligibility(
        parent, receipt, contract,
        child_receipts=kwargs.get("child_receipts"), workspace=kwargs.get("workspace"),
        authority_valid=kwargs.get("authority_valid", True),
        unauthorized_mutations=kwargs.get("unauthorized_mutations", 0),
        scope_violations=kwargs.get("scope_violations", 0), dnt_violations=kwargs.get("dnt_violations", 0),
        parent_result=kwargs.get("parent_result"),
    )
    if not gate.get("eligible"):
        raise PromotionEligibilityError(gate["status"], gate)
    candidate = build_promotion_candidate(
        parent, receipt, contract,
        child_receipts=kwargs.get("child_receipts"),
        workspace=kwargs.get("workspace"), project_id=kwargs.get("project_id", "default"),
        artifact_refs=kwargs.get("artifact_refs"), supersedes=kwargs.get("supersedes"),
        authority_change=kwargs.get("authority_change"),
    )
    checked = validate_promotion_candidate(
        candidate, parent=parent, parent_receipt=receipt, parent_contract=contract,
        child_receipts=kwargs.get("child_receipts"), workspace=kwargs.get("workspace"),
        project_id=kwargs.get("project_id", "default"),
        authority_valid=kwargs.get("authority_valid", True),
        unauthorized_mutations=kwargs.get("unauthorized_mutations", 0),
        scope_violations=kwargs.get("scope_violations", 0), dnt_violations=kwargs.get("dnt_violations", 0),
        parent_result=kwargs.get("parent_result"),
    )
    if not checked.get("valid"):
        raise PromotionEligibilityError(PROMOTION_NOT_ELIGIBLE_PROVENANCE, checked)
    return candidate


derive_promotion_candidate = build_promotion_candidate
candidate_from_verified_parent = build_promotion_candidate


def _candidate_identity_hash(value: dict) -> str:
    """Candidate identity excludes its display id and self-referential hash."""
    return canonical_hash({
        key: item for key, item in value.items()
        if key not in {"candidate_hash", "candidate_id"}
    })


def _fix_candidate_identity(candidate: dict) -> dict:
    value = copy.deepcopy(candidate)
    value["candidate_hash"] = _candidate_identity_hash(value)
    value["candidate_id"] = f"candidate-{value['candidate_hash'][:24]}"
    return value


def build_task_brain_completion(
    *,
    task_id: str,
    parent_verification_hash: str,
    promotion_hash: str,
    subject_state_hash: str,
    artifact_refs: Iterable[Any] | None = None,
    project_brain_record_ids: Iterable[Any] | None = None,
) -> dict:
    """Return a compact pointer from the temporary Task Brain to durable facts."""
    pointer: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "task_id": str(task_id),
        "terminal_state": "VERIFIED_AND_PROMOTED",
        "parent_verification_hash": str(parent_verification_hash or ""),
        "promotion_hash": str(promotion_hash or ""),
        "subject_state_hash": str(subject_state_hash or ""),
        "artifact_refs": _unique_strings(artifact_refs or [], MAX_ARTIFACT_REFS, 220),
        "project_brain_record_ids": _unique_strings(project_brain_record_ids or [], MAX_PROJECT_BRAIN_RECORDS, 180),
    }
    pointer["completion_hash"] = canonical_hash(pointer)
    return pointer


def _promotion_result_denied(gate: dict) -> dict:
    status = str(gate.get("status") or PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED)
    return {
        "promotion_status": status,
        "status": status,
        "eligible": False,
        "candidate": None,
        "promotion_receipt": None,
        "receipt_validation": copy.deepcopy(gate.get("receipt_validation", {})),
        "model_calls": 0,
        "task_brain_completion": None,
    }


def promote_verified_parent(
    parent: dict | None = None,
    parent_receipt: dict | None = None,
    parent_contract: dict | None = None,
    *,
    parent_result: dict | None = None,
    child_receipts: Any = None,
    workspace: str | Path | None = None,
    project_id: str = "default",
    store: Any = None,
    task_id: str | None = None,
    artifact_refs: Iterable[Any] | None = None,
    supersedes: Iterable[Any] | None = None,
    authority_change: dict | None = None,
    authority_valid: bool = True,
    unauthorized_mutations: int = 0,
    scope_violations: int = 0,
    dnt_violations: int = 0,
) -> dict:
    """Promote a valid parent receipt using one atomic store operation."""
    gate = assess_promotion_eligibility(
        parent, parent_receipt, parent_contract, child_receipts=child_receipts,
        workspace=workspace, authority_valid=authority_valid,
        unauthorized_mutations=unauthorized_mutations,
        scope_violations=scope_violations, dnt_violations=dnt_violations,
        parent_result=parent_result,
    )
    if not gate.get("eligible"):
        return _promotion_result_denied(gate)
    if store is None:
        return {
            "promotion_status": PROMOTION_STORAGE_UNAVAILABLE,
            "status": PROMOTION_STORAGE_UNAVAILABLE, "eligible": True,
            "candidate": None, "promotion_receipt": None,
            "receipt_validation": gate.get("receipt_validation", {}), "model_calls": 0,
            "task_brain_completion": None,
        }
    candidate = build_promotion_candidate(
        parent, parent_receipt, parent_contract,
        child_receipts=child_receipts, workspace=workspace, project_id=project_id,
        artifact_refs=artifact_refs, supersedes=supersedes,
        authority_change=authority_change,
    )
    candidate = _fix_candidate_identity(candidate)
    checked = validate_promotion_candidate(
        candidate, parent=parent, parent_receipt=parent_receipt,
        parent_contract=parent_contract, child_receipts=child_receipts,
        workspace=workspace, project_id=project_id, authority_valid=authority_valid,
        unauthorized_mutations=unauthorized_mutations,
        scope_violations=scope_violations, dnt_violations=dnt_violations,
        parent_result=parent_result,
    )
    if not checked.get("valid"):
        return {
            "promotion_status": PROMOTION_NOT_ELIGIBLE_PROVENANCE,
            "status": PROMOTION_NOT_ELIGIBLE_PROVENANCE, "eligible": False,
            "candidate": candidate, "promotion_receipt": None,
            "candidate_validation": checked, "receipt_validation": gate.get("receipt_validation", {}),
            "model_calls": 0, "task_brain_completion": None,
        }
    completion_base = None
    if task_id:
        completion_base = {
            "task_id": str(task_id),
            "artifact_refs": _unique_strings(artifact_refs or [], MAX_ARTIFACT_REFS, 220),
        }
    try:
        committed = store.commit_verified_promotion(candidate, task_completion=completion_base)
    except Exception as exc:
        # A persistence failure cannot turn a verified parent into a promoted
        # one.  The store transaction rolls back before this boundary returns.
        return {
            "promotion_status": PROMOTION_STORAGE_UNAVAILABLE,
            "status": PROMOTION_STORAGE_UNAVAILABLE, "eligible": True,
            "candidate": candidate, "promotion_receipt": None,
            "error": _compact(exc, 300), "model_calls": 0,
            "task_brain_completion": None,
        }
    result = dict(committed if isinstance(committed, dict) else {})
    result.setdefault("candidate", candidate)
    result.setdefault("receipt_validation", gate.get("receipt_validation", {}))
    result["candidate_validation"] = checked
    result["model_calls"] = 0
    return result


promote_parent_verified_state = promote_verified_parent
promote_verified_state = promote_verified_parent


def mark_state_bound_fact_stale(
    store: Any,
    current_subject_state_hash: str | None = None,
    changed_paths: Iterable[Any] | None = None,
    *,
    project_id: str = "default",
) -> dict:
    """Mark state-bound records stale without re-verification or model calls."""
    if store is None or not hasattr(store, "mark_stale_verified_facts"):
        return {"marked_stale": 0, "model_calls": 0}
    return store.mark_stale_verified_facts(
        current_subject_state_hash=current_subject_state_hash,
        changed_paths=changed_paths, project_id=project_id,
    )


def run_verified_state_promotion_self_test() -> dict:
    """Exercise the V22 boundary with a tiny filesystem-only fixture."""
    from tempfile import TemporaryDirectory

    from hivo.integration_gate import (
        aggregate_parent_integration,
        assess_integration_readiness,
        create_verified_child_receipt,
    )
    from hivo.memory import MemoryStore

    checks: dict[str, bool] = {}
    diagnostics: dict[str, Any] = {}
    try:
        with TemporaryDirectory(prefix="hivo_v22_promotion_selftest_") as tmp:
            root = Path(tmp)
            for relative, content in {
                "src/a.js": "export const a = 1;\n",
                "src/b.js": "export const b = 1;\n",
                "tests/a.test.js": "test('a', () => true);\n",
                "tests/b.test.js": "test('b', () => true);\n",
                "tests/integration.test.js": "test('integration', () => true);\n",
            }.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            contract = {
                "contract_hash": "PARENT-CONTRACT",
                "plan_hash": "PARENT-PLAN",
                "execution_contract_id": "PARENT",
                "project_id": "self-test-project",
                "validated_child_plan": [
                    {"child_id": "A", "required": True, "execution_contract_id": "EXEC-A", "contract_hash": "CONTRACT-A", "plan_hash": "PARENT-PLAN", "plan_node_ids": ["NODE-A"], "owned_plan_node_ids": ["NODE-A"]},
                    {"child_id": "B", "required": True, "execution_contract_id": "EXEC-B", "contract_hash": "CONTRACT-B", "plan_hash": "PARENT-PLAN", "plan_node_ids": ["NODE-B"], "owned_plan_node_ids": ["NODE-B"]},
                ],
                "state_ownership": ["PauseController owns pause state"],
                "interfaces_to_reuse": ["PauseController.togglePause()"],
                "preservation_constraints": ["movement behavior remains intact"],
                "structured_prohibitions": ["do not create a second state owner"],
                "integration_routes": [
                    {"kind": "INTEGRATION_TEST", "required": True, "applicable": True, "target": "tests/integration.test.js", "result": "PENDING"},
                    {"kind": "BROWSER", "required": False, "applicable": False, "target": None, "result": SKIPPED_NOT_APPLICABLE},
                ],
            }
            parent = {"id": "PARENT", "goal": "integrate verified responsibilities", "integration_routes": copy.deepcopy(contract["integration_routes"])}
            pairs = []
            receipts: dict[str, dict] = {}
            for child_id, source, focused in (("A", "src/a.js", "tests/a.test.js"), ("B", "src/b.js", "tests/b.test.js")):
                child_contract = {
                    "execution_contract_id": f"EXEC-{child_id}",
                    "contract_hash": f"CONTRACT-{child_id}",
                    "plan_hash": "PARENT-PLAN",
                    "allowed_mutation_paths": [source],
                    "plan_node_ids": [f"NODE-{child_id}"],
                    "owned_plan_node_ids": [f"NODE-{child_id}"],
                }
                task = {
                    "id": child_id, "parent": "PARENT", "status": "done",
                    "execution_contract_id": f"EXEC-{child_id}",
                    "execution_contract_hash": f"CONTRACT-{child_id}",
                    "approved_plan_hash": "PARENT-PLAN",
                    "execution_contract": child_contract,
                    "plan_node_ids": [f"NODE-{child_id}"],
                    "owned_plan_node_ids": [f"NODE-{child_id}"],
                    "done_when": [f"{child_id} verified"],
                }
                routes = [
                    {"kind": "FOCUSED_TEST", "required": True, "applicable": True, "target": focused, "result": "PASS"},
                    {"kind": "SYNTAX_STATIC_GATE", "required": True, "applicable": True, "target": source, "result": "PASS"},
                    {"kind": "BROWSER", "required": False, "applicable": False, "target": None, "result": SKIPPED_NOT_APPLICABLE},
                ]
                aggregation = {
                    "passed": True, "evidence_available": True, "failure_codes": [],
                    "actual_passes": [copy.deepcopy(routes[0]), copy.deepcopy(routes[1])],
                    "actual_failures": [], "skipped_not_applicable": [copy.deepcopy(routes[2])],
                    "verification_routes": routes,
                }
                result = {
                    "status": "done", "summary": f"{child_id} passed",
                    "gate": {"verification_aggregation": aggregation},
                    "builder": {"status": "done", "tool_evidence": [{"tool": "run_command", "target": f"node {focused}", "result": "[exit_code=0] focused test passed"}]},
                }
                receipt = create_verified_child_receipt(
                    task, result, parent_id="PARENT", parent_contract=contract, workspace=root,
                )
                pairs.append((task, result))
                receipts[child_id] = receipt
            readiness = assess_integration_readiness(
                parent, pairs, receipts, parent_contract=contract,
                validated_child_plan=contract["validated_child_plan"], workspace=root,
            )
            integrated = aggregate_parent_integration(
                parent, contract, readiness,
                [{"tool": "run_command", "target": "node tests/integration.test.js", "result": "[exit_code=0] integration passed"}],
                workspace=root,
            )
            store = MemoryStore(root)
            promoted = promote_verified_parent(
                parent, integrated.get("parent_verification_receipt"), contract,
                child_receipts=receipts, workspace=root, project_id="self-test-project",
                store=store, task_id="PARENT", artifact_refs=["self-test:integration"],
            )
            repeated = promote_verified_parent(
                parent, integrated.get("parent_verification_receipt"), contract,
                child_receipts=receipts, workspace=root, project_id="self-test-project",
                store=store, task_id="PARENT", artifact_refs=["self-test:integration"],
            )
            valid_receipt = integrated.get("parent_verification_receipt")
            unverified_receipt = copy.deepcopy(valid_receipt)
            unverified_receipt["verified"] = False
            unverified = promote_verified_parent(
                parent, unverified_receipt, contract,
                child_receipts=receipts, workspace=root, project_id="unverified-parent",
                store=store, task_id="PARENT",
            )
            tampered_receipt = copy.deepcopy(valid_receipt)
            tampered_receipt["plan_hash"] = "TAMPERED-PLAN"
            tampered = promote_verified_parent(
                parent, tampered_receipt, contract,
                child_receipts=receipts, workspace=root, project_id="tampered-receipt",
                store=store, task_id="PARENT",
            )
            conflict_contract = copy.deepcopy(contract)
            conflict_contract["state_ownership"] = ["StatusView owns pause state"]
            conflict_before = store.project_brain_hash("self-test-project")
            conflict = promote_verified_parent(
                parent, valid_receipt, conflict_contract,
                child_receipts=receipts, workspace=root, project_id="self-test-project",
                store=store, task_id="PARENT-CONFLICT",
            )
            conflict_after = store.project_brain_hash("self-test-project")
            diagnostics["promotion_status"] = promoted.get("promotion_status")
            diagnostics["promotion_error"] = promoted.get("error")
            diagnostics["candidate_validation"] = (promoted.get("candidate_validation") or {}).get("errors", [])
            diagnostics["receipt_validation"] = (promoted.get("receipt_validation") or {}).get("errors", [])
            diagnostics["candidate"] = {
                "hash": (promoted.get("candidate") or {}).get("candidate_hash"),
                "fact_count": (promoted.get("candidate") or {}).get("fact_count"),
            }
            checks["parent_receipt_verified"] = integrated.get("status") == PARENT_VERIFIED
            checks["promotion_succeeded"] = promoted.get("promotion_status") == PROMOTED
            checks["zero_model_calls"] = all(
                int(promoted.get(key, 0) or 0) == 0
                for key in ("model_calls",)
            ) and int((promoted.get("candidate_validation") or {}).get("model_calls", 0) or 0) == 0
            checks["browser_not_promoted"] = not any(
                str(item.get("kind", "")).upper() == "BROWSER"
                for category in _FACT_CATEGORY_ORDER
                for item in (promoted.get("candidate") or {}).get(category, []) or []
            )
            checks["idempotent"] = repeated.get("promotion_status") == ALREADY_PROMOTED and repeated.get("project_brain_before_hash") == repeated.get("project_brain_after_hash")
            checks["unverified_parent_denied"] = (
                unverified.get("promotion_status") == PROMOTION_NOT_ELIGIBLE_PARENT_UNVERIFIED
                and unverified.get("candidate") is None
                and store.project_brain_snapshot("unverified-parent")["records"] == []
            )
            checks["tampered_receipt_denied"] = (
                tampered.get("promotion_status") == PROMOTION_NOT_ELIGIBLE_STALE_RECEIPT
                and tampered.get("candidate") is None
                and store.project_brain_snapshot("tampered-receipt")["records"] == []
            )
            checks["conflict_denied_without_authority"] = (
                conflict.get("promotion_status") == PROMOTION_CONFLICT
                and conflict_before == conflict_after
            )
            before_stale = copy.deepcopy(integrated.get("parent_verification_receipt"))
            (root / "src" / "a.js").write_text("export const a = 2;\n", encoding="utf-8")
            stale = assess_promotion_eligibility(
                parent, before_stale, contract, child_receipts=receipts, workspace=root,
            )
            checks["stale_subject_denied"] = stale.get("status") == PROMOTION_NOT_ELIGIBLE_STALE_SUBJECT_STATE
            checks["no_html_fixture"] = not (root / "index.html").exists()
    except Exception as exc:
        return {"passed": False, "checks": {**checks, "exception_free": False}, "diagnostics": diagnostics, "error": _compact(exc, 500), "model_calls": 0}
    checks["exception_free"] = True
    return {"passed": all(checks.values()), "checks": checks, "diagnostics": diagnostics, "model_calls": 0}


__all__ = [name for name in globals() if not name.startswith("_")]
