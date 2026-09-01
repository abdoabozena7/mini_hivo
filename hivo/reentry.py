"""V23 Stage 6A freshness-aware verified-state re-entry.

This module is deliberately a read-only boundary between the V22 verified
Project Brain and a new task.  It does not plan, execute, re-verify, promote,
or call a model.  The Project Brain remains the durable source of previously
verified state; the ReentryContext is a deterministic reconciliation; and the
FreshTaskBrain is a bounded task-local projection of that reconciliation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Iterable

from hivo.integration_gate import (
    canonical_hash,
    fingerprint_dependency_paths,
    normalize_path,
)
from hivo.project_understanding import (
    DIRECT_OBSERVATION,
    REPOSITORY_EVIDENCE,
    REPOSITORY_EVIDENCE_UNAVAILABLE,
    REPOSITORY_EMPTY,
    REPOSITORY_RECONNAISSANCE_COMPLETE,
    REPOSITORY_RECONNAISSANCE_FAILED,
    run_repository_reconnaissance,
    validate_repository_evidence,
    inventory_repository,
)
from hivo.promotion import (
    DURABLE_VERIFIED,
    STATE_BOUND_VERIFIED,
    contains_forbidden_transcript,
)


SCHEMA_VERSION = "V23.6A"
REENTRY_CONTEXT_TYPE = "ReentryContext"
FRESH_TASK_BRAIN_TYPE = "FreshTaskBrain"

CURRENT_VERIFIED = "CURRENT_VERIFIED"
CURRENT_DURABLE_AUTHORITY = "CURRENT_DURABLE_AUTHORITY"
STALE_VERIFIED = "STALE_VERIFIED"
SUPERSEDED = "SUPERSEDED"
CONFLICTED = "CONFLICTED"
NOT_RELEVANT = "NOT_RELEVANT"

# V23.1 authority-vs-repository conformance classifications.  These are
# deterministic evidence states, not model judgments: an absent or
# unstructured observation cannot establish a contradiction.
CONFIRMED_CONSISTENT = "CONFIRMED_CONSISTENT"
CONFIRMED_DRIFT = "CONFIRMED_DRIFT"
NOT_EVALUABLE = "NOT_EVALUABLE"

REENTRY_READY = "REENTRY_READY"
REENTRY_RECONCILED = "REENTRY_RECONCILED"
REENTRY_PROJECT_ID_MISMATCH = "REENTRY_PROJECT_ID_MISMATCH"
REENTRY_MEMORY_UNAVAILABLE = "REENTRY_MEMORY_UNAVAILABLE"
REENTRY_REPOSITORY_UNAVAILABLE = "REENTRY_REPOSITORY_UNAVAILABLE"
REENTRY_INVALID_INPUT = "REENTRY_INVALID_INPUT"
REENTRY_TASK_BRAIN_INVALID = "REENTRY_TASK_BRAIN_INVALID"

AUTHORITY_IMPLEMENTATION_DRIFT = "AUTHORITY_IMPLEMENTATION_DRIFT"
NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE = "NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE"
STALE_VERIFIED_EVIDENCE = "STALE_VERIFIED_EVIDENCE"
INVALID_AUTHORITY_PROVENANCE = "INVALID_AUTHORITY_PROVENANCE"
INVALID_VERIFIED_RECORD = "INVALID_VERIFIED_RECORD"
CONTRADICTORY_ACTIVE_AUTHORITY = "CONTRADICTORY_ACTIVE_AUTHORITY"

ACTIVE = "ACTIVE"
STALE = "STALE"
SUPERSEDED_RECORD = "SUPERSEDED"

MAX_PROJECT_BRAIN_RECORDS = 256
MAX_CURRENT_VERIFIED_FACTS = 32
MAX_CURRENT_AUTHORITY = 24
MAX_STALE_FACTS = 24
MAX_SUPERSEDED_FACTS = 24
MAX_CURRENT_REPOSITORY_EVIDENCE = 12
MAX_CONFLICTS = 16
MAX_CLASSIFICATION_REFS = 32
MAX_PROMOTION_HASHES = 48
MAX_REENTRY_CONTEXT_CHARS = 40_000
MAX_TASK_BRAIN_CHARS = 10_000
MAX_TASK_BRAIN_FACTS = 24
MAX_TASK_BRAIN_AUTHORITY = 24
MAX_TASK_BRAIN_EVIDENCE = 12
MAX_TASK_BRAIN_STALE = 12
MAX_TASK_BRAIN_SUPERSEDED = 12
MAX_TASK_BRAIN_CONFLICTS = 12
MAX_AUTHORITY_DRIFT_AUDIT = 32
MAX_TASK_BRAIN_DRIFT_AUDIT = 16

_MODEL_CALL_ROLES = (
    "reentry", "freshness_reconciliation", "relevance_selection",
    "task_brain_bootstrap", "gemma_total",
)

_USER_AUTHORITY = frozenset({
    "USER", "USER/STATED", "USER/CONFIRMED", "USER/REQUIREMENT", "REQUIREMENT",
})
_VERIFIED_AUTHORITY = frozenset({"VERIFIED/EVIDENCE", "VERIFIED", "EVIDENCE"})
_VALID_RECORD_STATUSES = frozenset({ACTIVE, STALE, SUPERSEDED_RECORD})
_VALID_DURABILITY = frozenset({DURABLE_VERIFIED, STATE_BOUND_VERIFIED})
_ALLOWED_FACT_KEYS = frozenset({
    "fact", "text", "id", "requirement_id", "field", "kind", "category", "path",
    "paths", "symbol", "authority", "provenance", "source", "verified", "approved",
    "authority_source", "subject", "predicate", "object", "value", "description", "name",
    "domain", "relationship", "relation", "owner", "owner_entity", "structured_relation",
    "authority_relation", "repository_relation",
    "evidence_hash", "evidence_hashes", "conflict_key", "dependency_paths", "evidence_refs",
    "evidence", "durability_class", "subject_state_hash", "fact_hash", "semantic_hash",
    "record_id", "supersedes", "result", "dependency_fingerprints", "subject_state",
})
_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_transcript", "private_reasoning", "raw_worker_output", "raw_content",
    "worker_output", "model_output", "mission_compiler_output", "task_fit_output",
    "decomposer_output", "raw_model_output", "raw_model_transcript", "falsifier_output",
    "strategy_output", "strategy_text", "repair_output", "repair_speculation",
})
_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "from", "that", "this", "into", "onto", "while",
    "must", "should", "have", "has", "are", "was", "will", "not", "new", "task",
    "current", "existing", "preserve", "preserving", "continue", "behavior", "change",
})
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_$])(?:\.{0,2}/)?[A-Za-z0-9_./\\-]+\.(?:c|cc|cpp|css|go|h|html?|java|js|jsx|json|mjs|cjs|py|rs|ts|tsx|toml|ya?ml)"
    r"(?![A-Za-z0-9_$])",
    re.IGNORECASE,
)
_HASH_RE = re.compile(r"\b[0-9a-f]{64}\b", re.IGNORECASE)
_OWNER_ENTITY_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9_]*(?:Controller|View|Manager|State|Service|Owner|Store|Router)\b"
)


def _zero_model_call_accounting() -> dict[str, int]:
    return {role: 0 for role in _MODEL_CALL_ROLES}


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _compact(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":")))


def _tokens(value: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for token in re.findall(r"[a-z0-9_$.-]{2,}", str(value or "").casefold()):
        if token in _STOP_WORDS or token in seen:
            continue
        seen.add(token)
        result.append(token)
    return result[:48]


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _unique_strings(values: Iterable[Any], limit: int = 48, chars: int = 260) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if isinstance(value, dict):
            value = value.get("path") or value.get("target") or value.get("id") or value.get("text") or ""
        text = _compact(value, chars).strip()
        if not text or text.casefold() in seen:
            continue
        seen.add(text.casefold())
        result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe_value(value: Any, *, depth: int = 0, limit: int = 900) -> Any:
    """Copy a bounded JSON value after the caller has rejected private data."""
    if depth > 4:
        return _compact(value, 160)
    if isinstance(value, str):
        return _compact(value, limit)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key in list(value)[:32]:
            if str(key).casefold() in _PRIVATE_KEYS:
                continue
            result[str(key)] = _safe_value(value[key], depth=depth + 1, limit=min(limit, 320))
        return result
    if isinstance(value, (list, tuple, set)):
        return [_safe_value(item, depth=depth + 1, limit=min(limit, 320)) for item in list(value)[:48]]
    return value


def _normalize_paths(values: Any, workspace: str | Path | None = None) -> list[str]:
    result: list[str] = []
    for value in _as_list(values):
        if isinstance(value, dict):
            value = value.get("path") or value.get("target") or value.get("file") or ""
        raw = str(value or "").strip()
        if not raw:
            continue
        normalized = normalize_path(raw, workspace)
        if not normalized and workspace is None:
            normalized = raw.replace("\\", "/").lstrip("./")
            if normalized in {"", ".", ".."} or normalized.startswith("../"):
                normalized = ""
        if normalized:
            result.append(normalized)
    return _unique_strings(result, 64, 220)


def _normalize_authority(value: Any) -> str:
    text = str(value or "").strip().upper().replace("_", "/")
    if text in _USER_AUTHORITY:
        return "USER/REQUIREMENT"
    if text in _VERIFIED_AUTHORITY:
        return "VERIFIED/EVIDENCE"
    return ""


def _is_user_provenance(value: Any) -> bool:
    text = str(value or "").strip().upper().replace("_", "/")
    return text in _USER_AUTHORITY or text in {"USER", "REQUIREMENT"}


def _normalize_requirements(
    requirements: Any,
    task_goal: str | None = None,
) -> tuple[list[dict], list[dict]]:
    values = _as_list(requirements)
    if not values and str(task_goal or "").strip():
        values = [task_goal]
    normalized: list[dict] = []
    invalid: list[dict] = []
    for index, value in enumerate(values, 1):
        if isinstance(value, dict):
            text = value.get("text") or value.get("requirement") or value.get("goal") or value.get("fact")
            requirement_id = value.get("requirement_id") or value.get("id") or f"REENTRY-REQ-{index:03d}"
            provenance = value.get("provenance", "USER_STATED")
            authority = value.get("authority", "USER/REQUIREMENT")
        else:
            text = value
            requirement_id = f"REENTRY-REQ-{index:03d}"
            provenance = "USER_STATED"
            authority = "USER/REQUIREMENT"
        text = _compact(text, 900).strip()
        item = {
            "requirement_id": _compact(requirement_id, 120),
            "text": text,
            "provenance": "USER_STATED" if _is_user_provenance(provenance) else _compact(provenance, 80),
            "authority": _normalize_authority(authority),
            "status": "CURRENT",
        }
        if not text or not item["requirement_id"] or not _is_user_provenance(provenance) or item["authority"] != "USER/REQUIREMENT":
            invalid.append({
                "requirement_id": item["requirement_id"],
                "reason_code": INVALID_AUTHORITY_PROVENANCE if text else "EMPTY_REQUIREMENT",
                "provenance": item["provenance"],
            })
            continue
        normalized.append(item)
    return normalized[:MAX_CURRENT_AUTHORITY], invalid[:MAX_CONFLICTS]


def _normalize_current_authority(value: Any) -> tuple[list[dict], list[dict]]:
    values = _as_list(value)
    accepted: list[dict] = []
    invalid: list[dict] = []
    for index, item in enumerate(values, 1):
        if isinstance(item, dict):
            text = item.get("text") or item.get("fact") or item.get("requirement") or item.get("value")
            provenance = item.get("provenance", "USER_STATED")
            authority = item.get("authority", "USER/REQUIREMENT")
            requirement_id = item.get("requirement_id") or item.get("id") or f"REENTRY-AUTH-{index:03d}"
        else:
            text = item
            provenance = "USER_STATED"
            authority = "USER/REQUIREMENT"
            requirement_id = f"REENTRY-AUTH-{index:03d}"
        if not str(text or "").strip() or not _is_user_provenance(provenance) or _normalize_authority(authority) != "USER/REQUIREMENT":
            invalid.append({
                "authority_id": _compact(requirement_id, 120),
                "reason_code": INVALID_AUTHORITY_PROVENANCE,
            })
            continue
        accepted.append({
            "authority_id": _compact(requirement_id, 120),
            "text": _compact(text, 900),
            "provenance": "USER_STATED" if str(provenance).upper() == "USER_STATED" else "USER_CONFIRMED",
            "authority": "USER/REQUIREMENT",
            "status": "CURRENT",
        })
    return accepted[:MAX_CURRENT_AUTHORITY], invalid[:MAX_CONFLICTS]


def _fact_semantic_material(fact: dict) -> dict:
    return {
        "category": fact.get("category"),
        "field": fact.get("field"),
        "fact": fact.get("fact"),
        "authority": fact.get("authority"),
        "conflict_key": fact.get("conflict_key"),
    }


def _safe_record(record: dict, *, classification: str | None = None, reason: str | None = None) -> dict:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    result = {
        "record_id": _compact(record.get("record_id"), 180),
        "project_id": _compact(record.get("project_id"), 180),
        "fact_hash": _compact(record.get("fact_hash"), 100),
        "semantic_hash": _compact(record.get("semantic_hash"), 100),
        "conflict_key": _compact(record.get("conflict_key"), 320),
        "fact": _safe_value(fact),
        "durability_class": _compact(record.get("durability_class"), 80),
        "subject_state_hash": _compact(record.get("subject_state_hash"), 100),
        "status": _compact(record.get("status"), 40),
        "supersedes": _unique_strings(record.get("supersedes", []), 24, 180),
        "superseded_by": _compact(record.get("superseded_by"), 180) or None,
        "provenance": _safe_value(record.get("provenance", {}), limit=320),
    }
    if classification:
        result["classification"] = classification
    if reason:
        result["classification_reason"] = _compact(reason, 420)
    return result


def _record_hash_valid(record: dict) -> bool:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    if not fact:
        return False
    fact_hash = str(record.get("fact_hash") or "")
    if not fact_hash or fact.get("fact_hash") != fact_hash:
        return False
    if canonical_hash(_without(fact, "fact_hash")) != fact_hash:
        return False
    semantic_hash = str(record.get("semantic_hash") or "")
    if not semantic_hash or fact.get("semantic_hash") != semantic_hash:
        return False
    return canonical_hash(_fact_semantic_material(fact)) == semantic_hash


def _validate_stored_record(
    record: Any,
    project_id: str,
) -> tuple[bool, str]:
    if not isinstance(record, dict):
        return False, "record is not structured"
    if str(record.get("project_id") or "") != str(project_id):
        return False, "PROJECT_ID_MISMATCH"
    if str(record.get("status") or "") not in _VALID_RECORD_STATUSES:
        return False, "invalid stored record status"
    if str(record.get("durability_class") or "") not in _VALID_DURABILITY:
        return False, "invalid durability class"
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    if not fact or contains_forbidden_transcript(record):
        return False, "record contains forbidden or private provenance"
    if set(fact) - _ALLOWED_FACT_KEYS:
        return False, "fact contains an unapproved field"
    if fact.get("verified") is not True or fact.get("approved") is not True:
        return False, "record is not verified and approved"
    if fact.get("durability_class") != record.get("durability_class"):
        return False, "durability binding mismatch"
    if fact.get("subject_state_hash") != record.get("subject_state_hash"):
        return False, "subject-state binding mismatch"
    authority = _normalize_authority(fact.get("authority"))
    if not authority:
        return False, "invalid fact authority"
    authority_source = str(fact.get("authority_source") or "")
    if authority == "USER/REQUIREMENT" and authority_source not in {
        "approved_requirement_field", "approved_user_requirement", "user_requirement",
    }:
        return False, "invalid authority provenance for user fact"
    if authority == "VERIFIED/EVIDENCE" and authority_source not in {
        "verified_parent_verification_receipt", "verified_evidence", "verified_integration_evidence",
    }:
        return False, "invalid authority provenance for evidence fact"
    provenance = record.get("provenance") if isinstance(record.get("provenance"), dict) else {}
    if int(provenance.get("model_calls", 0) or 0) != 0:
        return False, "record provenance contains model calls"
    if provenance.get("raw_worker_transcript_included") is not False:
        return False, "record provenance is not transcript-free"
    if provenance.get("authority_escalation") is True or provenance.get("cross_project_memory") is True:
        return False, "record provenance escalates authority or project scope"
    if not str(provenance.get("source") or "").strip():
        return False, "record provenance source is missing"
    dependencies = fact.get("dependency_paths", [])
    if dependencies is not None and not isinstance(dependencies, list):
        return False, "dependency binding is not a list"
    if not _record_hash_valid(record):
        return False, "record fact or semantic hash does not match canonical contents"
    return True, "record hash, authority, and provenance are valid"


def _superseded_by_other(record: dict, records: list[dict]) -> bool:
    record_ids = {str(record.get("record_id") or ""), str(record.get("fact_hash") or "")}
    if not any(record_ids):
        return False
    for candidate in records:
        if candidate is record:
            continue
        if str(candidate.get("status") or "") == SUPERSEDED_RECORD:
            continue
        refs = {
            str(item) for item in _as_list(candidate.get("supersedes")) if str(item).strip()
        }
        candidate_fact = candidate.get("fact") if isinstance(candidate.get("fact"), dict) else {}
        refs.update(str(item) for item in _as_list(candidate_fact.get("supersedes")) if str(item).strip())
        if refs.intersection(record_ids):
            return True
    return False


def _contradictory_active_authority(record: dict, records: list[dict]) -> bool:
    """Fail closed when active authority records contradict without a link."""
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    if _normalize_authority(fact.get("authority")) != "USER/REQUIREMENT":
        return False
    conflict_key = str(record.get("conflict_key") or fact.get("conflict_key") or "").strip()
    semantic_hash = str(record.get("semantic_hash") or fact.get("semantic_hash") or "")
    record_id = str(record.get("record_id") or "")
    if not conflict_key or not semantic_hash:
        return False
    for candidate in records:
        if not isinstance(candidate, dict) or candidate is record:
            continue
        if str(candidate.get("status") or "") != ACTIVE:
            continue
        candidate_fact = candidate.get("fact") if isinstance(candidate.get("fact"), dict) else {}
        if _normalize_authority(candidate_fact.get("authority")) != "USER/REQUIREMENT":
            continue
        candidate_key = str(candidate.get("conflict_key") or candidate_fact.get("conflict_key") or "").strip()
        candidate_semantic = str(candidate.get("semantic_hash") or candidate_fact.get("semantic_hash") or "")
        candidate_id = str(candidate.get("record_id") or "")
        if candidate_key == conflict_key and candidate_semantic != semantic_hash and candidate_id != record_id:
            # The durable snapshot does not expose a trustworthy creation
            # order.  Without an explicit supersession/authority-change link,
            # neither contradictory record may be silently selected as truth.
            return True
    return False


def _freshness_for_record(record: dict, workspace: str | Path | None) -> dict:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    dependencies = _normalize_paths(fact.get("dependency_paths", []), workspace)
    stored_hash = str(record.get("subject_state_hash") or "")
    current = fingerprint_dependency_paths(workspace, dependencies)
    fresh = bool(dependencies and stored_hash and current.get("hash") == stored_hash)
    expected_paths = []
    for source in (record, fact):
        state = source.get("subject_state") if isinstance(source, dict) else None
        if isinstance(state, dict):
            expected_paths.extend(state.get("paths", []) or [])
    changed_paths: list[str] = []
    if expected_paths:
        expected_by_path = {
            str(item.get("path")): item for item in expected_paths if isinstance(item, dict) and item.get("path")
        }
        for item in current.get("paths", []) or []:
            if not isinstance(item, dict):
                continue
            before = expected_by_path.get(str(item.get("path")))
            if before and (
                before.get("exists") != item.get("exists")
                or before.get("sha256") != item.get("sha256")
            ):
                changed_paths.append(str(item.get("path")))
        changed_paths.extend(
            str(item.get("path")) for item in expected_paths
            if isinstance(item, dict) and str(item.get("path")) not in {str(p.get("path")) for p in current.get("paths", []) if isinstance(p, dict)}
        )
    elif not fresh and dependencies:
        # V22 records persist the aggregate subject hash and dependency set.
        # If the old per-file details are not available, the bounded and
        # conservative explanation names only the bound dependency set.
        changed_paths = list(dependencies)
    return {
        "fresh": fresh,
        "dependency_paths": dependencies,
        "stored_subject_state_hash": stored_hash,
        "current_subject_state_hash": current.get("hash"),
        "current_subject_state": current,
        "changed_dependency_paths": _unique_strings(changed_paths, 48, 220),
        "reason_code": "SUBJECT_STATE_MATCH" if fresh else "SUBJECT_STATE_CHANGED_OR_UNBOUND",
        "model_calls": 0,
    }


def _extract_paths_from_text(value: Any) -> list[str]:
    return _unique_strings(
        match.group(0).replace("\\", "/").lstrip("./") for match in _PATH_RE.finditer(str(value or ""))
    )


def _record_relevance(record: dict, query_terms: set[str], requested_paths: set[str]) -> tuple[int, bool]:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    encoded = json.dumps({
        "fact": fact.get("fact"), "field": fact.get("field"), "category": fact.get("category"),
        "path": fact.get("path"), "symbol": fact.get("symbol"),
        "dependency_paths": fact.get("dependency_paths", []),
        "requirement_id": fact.get("requirement_id"),
    }, ensure_ascii=False, default=str).casefold()
    score = sum(4 for term in query_terms if term in encoded)
    fact_paths = set(_normalize_paths(fact.get("dependency_paths", [])))
    fact_paths.update(_normalize_paths(fact.get("path")))
    path_overlap = fact_paths.intersection(requested_paths)
    score += len(path_overlap) * 8
    category = str(fact.get("category") or "")
    field = str(fact.get("field") or "")
    text = str(fact.get("fact") or "")
    authority = _normalize_authority(fact.get("authority"))
    mandatory = bool(
        category == "verified_prohibitions"
        or re.search(r"\b(?:do not|must not|never|sole|only)\b", text, re.IGNORECASE)
    )
    if authority == "USER/REQUIREMENT" and mandatory:
        score += 100
    elif authority == "USER/REQUIREMENT" and field.casefold() in {
        "state_ownership", "current_state_ownership", "owner", "current_owner", "interfaces_to_reuse",
    }:
        score += 34
    elif category in {"verified_interfaces", "verified_preservations"}:
        score += 12
    if str(fact.get("path") or "").casefold() in requested_paths:
        score += 20
    return score, bool(score > 0)


def _evidence_relevance(record: dict, query_terms: set[str], requested_paths: set[str]) -> int:
    encoded = json.dumps(record, ensure_ascii=False, default=str).casefold()
    score = sum(4 for term in query_terms if term in encoded)
    path = str(record.get("path") or "").replace("\\", "/").lstrip("./").casefold()
    if path in requested_paths:
        score += 12
    if record.get("category") in {"CURRENT_STATE_OWNER", "CURRENT_OWNER", "CURRENT_INTERFACE"}:
        score += 8
    return score


def _public_classification(
    record: dict,
    classification: str,
    reason_code: str,
    reason: str,
    *,
    relevance_score: int = 0,
    relevant: bool = False,
    accepted_as_current: bool = False,
    freshness: dict | None = None,
) -> dict:
    result = {
        "record_id": _compact(record.get("record_id"), 180),
        "fact_hash": _compact(record.get("fact_hash"), 100),
        "project_id": _compact(record.get("project_id"), 180),
        "stored_status": _compact(record.get("status"), 40),
        "durability_class": _compact(record.get("durability_class"), 80),
        "classification": classification,
        "reason_code": _compact(reason_code, 100),
        "reason": _compact(reason, 420),
        "relevance_score": int(relevance_score),
        "relevant": bool(relevant),
        "accepted_as_current": bool(accepted_as_current),
    }
    if freshness is not None:
        result["freshness"] = {
            "fresh": bool(freshness.get("fresh")),
            "dependency_paths": _unique_strings(freshness.get("dependency_paths", []), 48, 220),
            "stored_subject_state_hash": freshness.get("stored_subject_state_hash"),
            "current_subject_state_hash": freshness.get("current_subject_state_hash"),
            "changed_dependency_paths": _unique_strings(freshness.get("changed_dependency_paths", []), 48, 220),
            "reason_code": freshness.get("reason_code"),
        }
    return result


def _extract_promotion_hashes(values: Iterable[Any]) -> list[str]:
    hashes: list[str] = []
    for value in values:
        if isinstance(value, dict):
            values_to_scan = [value.get("promotion_hash"), value.get("parent_verification_hash"), value.get("candidate_hash")]
            values_to_scan.extend(value.get("evidence_refs", []) or [])
            values_to_scan.extend(value.get("artifact_refs", []) or [])
        else:
            values_to_scan = [value]
        for candidate in values_to_scan:
            text = str(candidate or "")
            for match in _HASH_RE.findall(text):
                hashes.append(match.casefold())
    return _unique_strings(hashes, MAX_PROMOTION_HASHES, 100)


def _compact_completion_pointer(pointer: Any) -> dict | None:
    if not isinstance(pointer, dict) or contains_forbidden_transcript(pointer):
        return None
    allowed = {
        "schema_version", "task_id", "terminal_state", "parent_verification_hash", "promotion_hash",
        "subject_state_hash", "artifact_refs", "project_brain_record_ids", "completion_hash",
    }
    result = {key: _safe_value(pointer[key], limit=260) for key in allowed if key in pointer}
    if not result.get("task_id"):
        return None
    result["artifact_refs"] = _unique_strings(result.get("artifact_refs", []), 12, 180)
    result["project_brain_record_ids"] = _unique_strings(result.get("project_brain_record_ids", []), 24, 180)
    return result


def _repository_observation(
    workspace: str | Path | None,
    task_goal: str,
    requirements: list[dict],
    supplied: Any,
) -> dict:
    """Get bounded Stage 2 direct observations without a scout/model call."""
    if supplied is not None:
        if isinstance(supplied, dict):
            values = supplied.get("evidence", [])
            supplied_status = supplied.get("status", "PROVIDED")
        else:
            values = supplied
            supplied_status = "PROVIDED"
        supplied_available = True
        supplied_error = None
        if isinstance(supplied, dict):
            supplied_available = bool(supplied.get("available", True))
            supplied_error = supplied.get("error")
        accepted: list[dict] = []
        rejected = 0
        for item in _as_list(values):
            if not isinstance(item, dict) or not validate_repository_evidence(item, workspace):
                rejected += 1
                continue
            accepted.append(copy.deepcopy(item))
        accepted = accepted[:MAX_CURRENT_REPOSITORY_EVIDENCE]
        available = supplied_available and supplied_status not in {
            REPOSITORY_EVIDENCE_UNAVAILABLE, REPOSITORY_RECONNAISSANCE_FAILED,
        }
        return {
            "status": supplied_status,
            "available": available,
            "evidence": accepted,
            "rejected_count": rejected,
            "model_calls": 0,
            "read_only": True,
            "source": "caller_supplied_stage2_evidence",
            "error": _compact(supplied_error, 400) if supplied_error else None,
        }
    try:
        root = Path(workspace).resolve() if workspace is not None else None
        if root is None or not root.is_dir():
            return {
                "status": REPOSITORY_EVIDENCE_UNAVAILABLE,
                "available": False,
                "evidence": [],
                "model_calls": 0,
                "read_only": True,
                "error": "workspace is not an accessible directory",
            }
        inventory = inventory_repository(root)
        recon = run_repository_reconnaissance(
            root,
            " ".join([task_goal, *[item.get("text", "") for item in requirements]]),
            requirements,
            inventory=inventory,
            scout_selector=None,
        )
        evidence = [
            copy.deepcopy(item) for item in recon.get("evidence", []) or []
            if validate_repository_evidence(item, root)
        ][:MAX_CURRENT_REPOSITORY_EVIDENCE]
        status = recon.get("status")
        available = status in {
            REPOSITORY_RECONNAISSANCE_COMPLETE, REPOSITORY_EMPTY,
        }
        return {
            "status": status,
            "available": available,
            "evidence": evidence,
            "inventory_fingerprint": inventory.get("fingerprint"),
            "workspace_fingerprint_before": recon.get("workspace_fingerprint_before"),
            "workspace_fingerprint_after": recon.get("workspace_fingerprint_after"),
            "operations": [
                {
                    "operation": item.get("operation"),
                    "path": item.get("path"),
                }
                for item in (recon.get("operations", []) or [])[:24]
                if isinstance(item, dict)
            ],
            "errors": [str(item)[:300] for item in (recon.get("errors", []) or [])[:8]],
            "model_calls": 0,
            "read_only": bool(recon.get("read_only", True)),
            "source": "stage2_bounded_repository_reconnaissance",
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return {
            "status": REPOSITORY_RECONNAISSANCE_FAILED,
            "available": False,
            "evidence": [],
            "model_calls": 0,
            "read_only": True,
            "error": _compact(exc, 400),
        }


def inspect_current_repository(
    workspace: str | Path | None,
    task_goal: str = "",
    new_requirements: Any = None,
    *,
    current_repository_evidence: Any = None,
) -> dict:
    """Public read-only Stage 2 evidence adapter used by re-entry callers."""
    requirements, _invalid = _normalize_requirements(new_requirements, task_goal)
    return _repository_observation(
        workspace, _compact(task_goal, 900), requirements, current_repository_evidence,
    )


def validate_project_identity(
    project_id: str,
    project_brain: dict | list | None,
    *,
    expected_project_id: str | None = None,
) -> dict:
    """Validate the project boundary before any verified record is consumed."""
    requested = str(project_id or "").strip()
    expected = str(expected_project_id or requested).strip()
    snapshot_id = project_brain.get("project_id") if isinstance(project_brain, dict) else None
    errors: list[str] = []
    if not requested:
        errors.append("project_id is required")
    if expected and requested != expected:
        errors.append("requested project identity does not match expected identity")
    if snapshot_id is not None and str(snapshot_id) != requested:
        errors.append("Project Brain project identity does not match current project")
    return {
        "valid": not errors,
        "project_id": requested,
        "expected_project_id": expected,
        "brain_project_id": snapshot_id,
        "errors": errors[:8],
        "model_calls": 0,
    }


def _snapshot_records(project_id: str, project_brain: dict | list | None) -> tuple[dict, list[dict], list[str]]:
    if isinstance(project_brain, dict):
        snapshot_id = project_brain.get("project_id", project_id)
        values = project_brain.get("records", [])
    elif isinstance(project_brain, list):
        snapshot_id = project_id
        values = project_brain
    else:
        snapshot_id = project_id
        values = []
    errors: list[str] = []
    if not isinstance(values, list):
        errors.append("Project Brain records are not a list")
        values = []
    snapshot = {"project_id": str(snapshot_id), "records": copy.deepcopy(values[:MAX_PROJECT_BRAIN_RECORDS])}
    if len(values) > MAX_PROJECT_BRAIN_RECORDS:
        errors.append("Project Brain record bound exceeded")
    return snapshot, [item for item in values[:MAX_PROJECT_BRAIN_RECORDS] if isinstance(item, dict)], errors


def _conflict(kind: str, **values: Any) -> dict:
    base = {"kind": kind, **values}
    conflict_id = f"REENTRY-CONFLICT-{canonical_hash(base)[:16]}"
    return {
        "conflict_id": conflict_id,
        "kind": kind,
        **{
            key: _safe_value(value, limit=520)
            for key, value in values.items()
            if value not in (None, "", [], {})
        },
        "model_calls": 0,
    }


def _deduplicate_conflicts(values: Iterable[dict]) -> list[dict]:
    result: list[dict] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, dict):
            continue
        key = str(value.get("conflict_id") or canonical_hash(value))
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result[:MAX_CONFLICTS]


def _owner_entities(text: Any, symbol: Any = None) -> set[str]:
    result = {item.casefold() for item in _OWNER_ENTITY_RE.findall(str(text or ""))}
    symbol_text = str(symbol or "")
    result.update(item.casefold() for item in _OWNER_ENTITY_RE.findall(symbol_text))
    if symbol_text and re.fullmatch(r"[A-Za-z_$][\w$]*", symbol_text):
        result.add(symbol_text.casefold())
    return result


def _domain_tokens(text: Any) -> set[str]:
    base = {
        token for token in _tokens(text)
        if token not in {"owner", "owns", "ownership", "state", "sole", "current", "implementation"}
    }
    # Treat ``pause-state`` and ``pause state`` as the same observed domain
    # without introducing semantic interpretation or a model call.
    base.update(
        part for token in list(base) for part in token.split("-")
        if len(part) >= 3 and part not in _STOP_WORDS
    )
    return base


_STRUCTURED_OWNER_PREDICATES = frozenset({
    "owner", "owns", "ownership", "state_owner", "state_ownership", "sole_owner",
})
_OWNER_RELATION_EXPRESSION_RE = re.compile(
    r"^\s*(?:owner|owns|ownership|state[_ -]?owner)\s*\(\s*"
    r"([A-Za-z0-9_$.-]+)\s*\)\s*(?:=|:|->|is)\s*"
    r"([A-Za-z_$][A-Za-z0-9_$.-]*)\s*\.?\s*$",
    re.IGNORECASE,
)


def _normalize_relation_atom(value: Any) -> str:
    """Normalize one explicit relation atom without interpreting source text."""
    text = " ".join(str(value or "").split()).strip(" .,:;")
    if not text or "/" in text or "\\" in text or _HASH_RE.fullmatch(text):
        return ""
    text = re.sub(r"[\s-]+", "_", text)
    if not re.fullmatch(r"[A-Za-z0-9_$][A-Za-z0-9_$.:]*", text):
        return ""
    return text.casefold()


def _normalize_relation_predicate(value: Any) -> str:
    text = " ".join(str(value or "").split()).strip(" .,:;").casefold()
    text = re.sub(r"[\s-]+", "_", text)
    return "OWNER" if text in _STRUCTURED_OWNER_PREDICATES else ""


def _make_structured_owner_relation(subject: Any, predicate: Any, owner: Any) -> dict | None:
    normalized_subject = _normalize_relation_atom(subject)
    normalized_predicate = _normalize_relation_predicate(predicate)
    normalized_owner = _normalize_relation_atom(owner)
    if not normalized_subject or not normalized_predicate or not normalized_owner:
        return None
    return {
        "subject": normalized_subject,
        "predicate": normalized_predicate,
        "object": normalized_owner,
    }


def _parse_owner_relation_expression(value: Any) -> dict | None:
    match = _OWNER_RELATION_EXPRESSION_RE.fullmatch(str(value or ""))
    if not match:
        return None
    return _make_structured_owner_relation(match.group(1), "OWNER", match.group(2))


def _structured_owner_relation_from_mapping(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None

    subject = (
        value.get("subject")
        or value.get("domain")
        or value.get("resource")
        or value.get("state")
    )
    predicate = (
        value.get("predicate")
        or value.get("relationship")
        or value.get("relation_type")
        or value.get("relation")
    )
    owner_key = next(
        (key for key in ("object", "owner", "owner_entity", "implementation_owner", "target", "value")
         if value.get(key) not in (None, "")),
        None,
    )
    owner = value.get(owner_key) if owner_key else None
    if subject not in (None, "") and owner not in (None, ""):
        # An explicit ``owner``/``object`` field is sufficient to identify the
        # relation when no separate predicate field was supplied.  Generic
        # symbols and filenames are never used here.
        normalized_predicate = predicate or ("OWNER" if owner_key in {"owner", "owner_entity", "implementation_owner"} else "")
        relation = _make_structured_owner_relation(subject, normalized_predicate, owner)
        if relation is not None:
            return relation
    return None


def _structured_owner_relation(value: Any) -> dict | None:
    """Read only an explicit ownership relation from structured evidence.

    Stage 2 observations intentionally contain compact descriptive prose and
    symbols.  Those fields are useful repository evidence, but they do not
    prove an ownership relationship.  This parser therefore accepts explicit
    relation fields or one strict canonical expression and never falls back to
    filenames, symbols, comments, or arbitrary source snippets.
    """
    if isinstance(value, str):
        return _parse_owner_relation_expression(value)
    if not isinstance(value, dict):
        return None

    relation = _structured_owner_relation_from_mapping(value)
    if relation is not None:
        return relation
    for key in (
        "structured", "structured_relation", "authority_relation", "repository_relation",
        "ownership", "relation", "relationship", "structured_fact",
    ):
        nested = value.get(key)
        if isinstance(nested, dict):
            relation = _structured_owner_relation_from_mapping(nested)
            if relation is not None:
                return relation
        elif isinstance(nested, str):
            relation = _parse_owner_relation_expression(nested)
            if relation is not None:
                return relation
    for key in ("structured_fact", "fact"):
        candidate = value.get(key)
        if isinstance(candidate, str):
            relation = _parse_owner_relation_expression(candidate)
            if relation is not None:
                return relation
    return None


def _authority_fact_mentions_ownership(fact: dict) -> bool:
    relation = _structured_owner_relation(fact)
    if relation is not None:
        return True
    field = str(fact.get("field") or "").casefold()
    fact_text = str(fact.get("fact") or "")
    return bool(
        field in {"owner", "current_owner", "state_ownership", "current_state_ownership"}
        or re.search(r"\b(?:owner|owns|ownership|sole|only|state[- ]owner)\b", fact_text, re.IGNORECASE)
    )


def _authority_drift_audit_entry(
    record: dict,
    fact: dict,
    classification: str,
    reason_code: str,
    evidence_ids: Iterable[Any],
    *,
    authority_relation: dict | None = None,
    repository_relations: Iterable[dict] | None = None,
    conflict_emitted: bool = False,
) -> dict:
    entry = {
        "authority_record_id": _compact(record.get("record_id") or record.get("fact_hash"), 180),
        "evidence_refs": _unique_strings(evidence_ids, 16, 120),
        "classification": classification,
        "reason_code": _compact(reason_code, 120),
        "conflict_emitted": bool(conflict_emitted),
    }
    # The required audit fields remain present for every evaluated fact.  The
    # descriptive kind is useful when a relation was actually evaluated, but
    # omitting it for unknown/non-relevant records keeps the bounded context
    # safe for large Project Brains.
    if classification not in {NOT_EVALUABLE, NOT_RELEVANT}:
        entry["authority_fact_kind"] = _compact(
            fact.get("kind") or fact.get("field") or fact.get("category"), 120,
        )
    if authority_relation is not None:
        entry["authority_relation"] = copy.deepcopy(authority_relation)
    relations = [copy.deepcopy(item) for item in (repository_relations or []) if isinstance(item, dict)]
    if relations:
        entry["repository_relations"] = relations[:8]
    return entry


def _empty_authority_drift_metrics() -> dict[str, int]:
    return {
        "authority_drift_checks": 0,
        "authority_drift_confirmed": 0,
        "authority_drift_consistent": 0,
        "authority_drift_not_evaluable": 0,
        "authority_drift_conflicts_emitted": 0,
        "authority_drift_duplicate_conflicts_suppressed": 0,
    }


def classify_authority_repository_drift(
    current_records: list[dict],
    repository_evidence: list[dict],
) -> dict:
    """Classify authority conformance from explicit structured evidence only."""
    metrics = _empty_authority_drift_metrics()
    conflicts: list[dict] = []
    audits: list[dict] = []
    audit_by_record_id: dict[str, dict] = {}
    conflict_groups: dict[tuple[str, str, str], list[dict]] = {}

    owner_categories = {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_BEHAVIOR"}
    owner_observations: list[tuple[dict, dict | None]] = []
    for item in repository_evidence or []:
        if not isinstance(item, dict):
            continue
        relation = _structured_owner_relation(item)
        if str(item.get("category") or "") in owner_categories or relation is not None:
            owner_observations.append((item, relation))

    for record in current_records or []:
        if not isinstance(record, dict):
            continue
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        if _normalize_authority(fact.get("authority")) != "USER/REQUIREMENT":
            continue
        metrics["authority_drift_checks"] += 1
        authority_relation = _structured_owner_relation(fact)
        authority_like = _authority_fact_mentions_ownership(fact)
        evidence_ids = [item.get("evidence_id") for item, _relation in owner_observations]
        record_id = str(record.get("record_id") or record.get("fact_hash") or "")

        if not authority_like:
            classification = NOT_RELEVANT
            reason_code = "AUTHORITY_FACT_NOT_OWNER_RELATION"
            audit = _authority_drift_audit_entry(
                record, fact, classification, reason_code, evidence_ids,
            )
            audits.append(audit)
            audit_by_record_id[record_id] = audit
            continue

        if authority_relation is None:
            classification = NOT_EVALUABLE
            reason_code = "AUTHORITY_RELATION_NOT_STRUCTURED"
            metrics["authority_drift_not_evaluable"] += 1
            audit = _authority_drift_audit_entry(
                record, fact, classification, reason_code, evidence_ids,
            )
            audits.append(audit)
            audit_by_record_id[record_id] = audit
            continue

        structured_observations = [
            (item, relation) for item, relation in owner_observations if relation is not None
        ]
        if not owner_observations:
            classification = NOT_EVALUABLE
            reason_code = "NO_CURRENT_OWNER_EVIDENCE"
            metrics["authority_drift_not_evaluable"] += 1
            audit = _authority_drift_audit_entry(
                record, fact, classification, reason_code, evidence_ids,
                authority_relation=authority_relation,
            )
            audits.append(audit)
            audit_by_record_id[record_id] = audit
            continue
        if not structured_observations:
            classification = NOT_EVALUABLE
            reason_code = "CURRENT_OWNER_EVIDENCE_NOT_STRUCTURED"
            metrics["authority_drift_not_evaluable"] += 1
            audit = _authority_drift_audit_entry(
                record, fact, classification, reason_code, evidence_ids,
                authority_relation=authority_relation,
            )
            audits.append(audit)
            audit_by_record_id[record_id] = audit
            continue

        matching = [
            (item, relation) for item, relation in structured_observations
            if relation["subject"] == authority_relation["subject"]
            and relation["predicate"] == authority_relation["predicate"]
        ]
        matching_evidence_ids = [item.get("evidence_id") for item, _relation in matching]
        matching_relations = [relation for _item, relation in matching]
        if not matching:
            classification = NOT_RELEVANT
            reason_code = "NO_MATCHING_STRUCTURED_OWNER_RELATION"
            audit = _authority_drift_audit_entry(
                record, fact, classification, reason_code, evidence_ids,
                authority_relation=authority_relation,
                repository_relations=matching_relations,
            )
            audits.append(audit)
            audit_by_record_id[record_id] = audit
            continue

        mismatches = [
            (item, relation) for item, relation in matching
            if relation["object"] != authority_relation["object"]
        ]
        if mismatches:
            classification = CONFIRMED_DRIFT
            reason_code = "STRUCTURED_OWNER_RELATION_CONTRADICTS"
            metrics["authority_drift_confirmed"] += 1
            for item, relation in mismatches:
                group_key = (
                    authority_relation["subject"],
                    authority_relation["predicate"],
                    relation["object"],
                )
                conflict_groups.setdefault(group_key, []).append({
                    "record": record,
                    "fact": fact,
                    "authority_relation": authority_relation,
                    "observation": item,
                    "repository_relation": relation,
                })
        else:
            classification = CONFIRMED_CONSISTENT
            reason_code = "STRUCTURED_OWNER_RELATION_AGREES"
            metrics["authority_drift_consistent"] += 1
        audit = _authority_drift_audit_entry(
            record, fact, classification, reason_code, matching_evidence_ids,
            authority_relation=authority_relation,
            repository_relations=matching_relations,
            conflict_emitted=classification == CONFIRMED_DRIFT,
        )
        audits.append(audit)
        audit_by_record_id[record_id] = audit

    for group_key in sorted(conflict_groups, key=lambda value: tuple(str(item) for item in value)):
        rows = sorted(
            conflict_groups[group_key],
            key=lambda row: (
                str(row["record"].get("record_id") or row["record"].get("fact_hash") or ""),
                str(row["observation"].get("evidence_id") or ""),
            ),
        )
        authority_ids = sorted({
            str(row["record"].get("record_id") or row["record"].get("fact_hash") or "")
            for row in rows
        })
        evidence_ids = sorted({
            str(row["observation"].get("evidence_id") or "") for row in rows
        })
        first = rows[0]
        stable_key = canonical_hash({
            "kind": AUTHORITY_IMPLEMENTATION_DRIFT,
            "authority_relation": first["authority_relation"],
            "repository_relation": first["repository_relation"],
        })
        conflict = _conflict(
            AUTHORITY_IMPLEMENTATION_DRIFT,
            authority_record_id=authority_ids[0] if authority_ids else None,
            authority_record_ids=authority_ids,
            authority_fact_hash=first["record"].get("fact_hash"),
            authority_fact=_compact(first["fact"].get("fact"), 420),
            authority_relation=first["authority_relation"],
            repository_evidence_id=evidence_ids[0] if evidence_ids else None,
            repository_evidence_ids=evidence_ids,
            repository_fact=_compact(first["observation"].get("fact"), 420),
            repository_path=first["observation"].get("path"),
            repository_relation=first["repository_relation"],
            drift_classification=CONFIRMED_DRIFT,
            drift_conflict_key=stable_key,
            resolution="RETAIN_AUTHORITY_AND_SURFACE_DRIFT",
            authority_rewritten=False,
        )
        # The identity is based on the contradiction itself, not on which
        # projection or duplicate authority record happened to be selected.
        conflict["conflict_id"] = f"REENTRY-CONFLICT-{canonical_hash({
            "kind": AUTHORITY_IMPLEMENTATION_DRIFT,
            "drift_conflict_key": stable_key,
        })[:16]}"
        conflicts.append(conflict)
        for authority_id in authority_ids:
            audit = audit_by_record_id.get(authority_id)
            if audit is not None:
                audit.setdefault("conflict_ids", []).append(conflict["conflict_id"])
                audit["conflict_emitted"] = True
        metrics["authority_drift_duplicate_conflicts_suppressed"] += max(0, len(authority_ids) - 1)
        metrics["authority_drift_duplicate_conflicts_suppressed"] += max(0, len(evidence_ids) - 1)

    metrics["authority_drift_conflicts_emitted"] = len(conflicts[:MAX_CONFLICTS])
    return {
        "conflicts": conflicts[:MAX_CONFLICTS],
        "audit": audits[:MAX_AUTHORITY_DRIFT_AUDIT],
        "metrics": metrics,
        "model_calls": 0,
    }


def _new_requirement_conflicts(
    requirements: list[dict],
    current_records: list[dict],
) -> list[dict]:
    conflicts: list[dict] = []
    for requirement in requirements:
        req_text = str(requirement.get("text") or "")
        req_lower = req_text.casefold()
        requirement_entities = _owner_entities(req_text)
        ownership_language = bool(re.search(
            r"\b(?:owner|owns|ownership|sole|only|pause[- ]state|state[- ]owner)\b",
            req_text,
            re.IGNORECASE,
        ))
        ownership_change = bool(
            re.search(r"\b(?:move|transfer|relocate|reassign|change|switch)\b", req_lower)
            and re.search(r"\b(?:owner|ownership|pause[- ]state|state[- ]owner|state ownership)\b", req_lower)
        )
        for record in current_records:
            fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
            fact_text = str(fact.get("fact") or "")
            fact_lower = fact_text.casefold()
            current_entities = _owner_entities(fact_text, fact.get("symbol"))
            owner_entity_change = bool(
                ownership_language and requirement_entities and current_entities
                and not requirement_entities.intersection(current_entities)
            )
            if (ownership_change or owner_entity_change) and re.search(
                r"\b(?:owner|owns|sole|pause[- ]state|state[- ]owner)\b", fact_lower,
            ):
                conflicts.append(_conflict(
                    NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE,
                    requirement_id=requirement.get("requirement_id"),
                    requirement_text=req_text,
                    current_record_id=record.get("record_id"),
                    current_fact_hash=record.get("fact_hash"),
                    current_fact=_compact(fact_text, 420),
                    authority_precedence="USER_REQUIREMENT",
                    requested_change="new user requirement is a requested change, not completed state",
                    current_state_preserved=True,
                    resolution="PLANNING_REQUIRED",
                ))
                break
            if re.search(r"\b(?:remove|delete|retire|replace)\b", req_lower) and re.search(
                r"\b(?:do not|must not|never|preserve|sole|only)\b", fact_lower,
            ):
                shared = set(_tokens(req_text)).intersection(_tokens(fact_text))
                if shared:
                    conflicts.append(_conflict(
                        NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE,
                        requirement_id=requirement.get("requirement_id"),
                        requirement_text=req_text,
                        current_record_id=record.get("record_id"),
                        current_fact_hash=record.get("fact_hash"),
                        current_fact=_compact(fact_text, 420),
                        authority_precedence="USER_REQUIREMENT",
                        current_state_preserved=True,
                        resolution="PLANNING_REQUIRED",
                    ))
                    break
    return conflicts


def _authority_repo_drift(current_records: list[dict], repository_evidence: list[dict]) -> list[dict]:
    """Compatibility projection returning only confirmed drift conflicts."""
    return classify_authority_repository_drift(current_records, repository_evidence).get("conflicts", [])


def _authority_entries(
    requirements: list[dict],
    current_records: list[dict],
    explicit_authority: list[dict],
) -> list[dict]:
    result: list[dict] = []
    for item in [*requirements, *explicit_authority]:
        result.append(copy.deepcopy(item))
    # Current durable authority is carried in its own bounded field.  Keeping
    # the top-level authority list focused on newly supplied user authority
    # prevents three copies of every promoted fact in the ReentryContext.
    del current_records
    deduped: list[dict] = []
    seen: set[str] = set()
    for item in result:
        key = f"{item.get('authority_id') or item.get('requirement_id')}|{item.get('text')}"
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped[:MAX_CURRENT_AUTHORITY]


def _build_stale_warning(record: dict, freshness: dict, reason: str) -> dict:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    return {
        "record_id": record.get("record_id"),
        "fact_hash": record.get("fact_hash"),
        "classification": STALE_VERIFIED,
        "previously_verified": fact.get("verified") is True,
        "fact_summary": _compact(fact.get("fact"), 420),
        "durability_class": record.get("durability_class"),
        "subject_state_hash": record.get("subject_state_hash"),
        "stale_reason": _compact(reason, 420),
        "changed_dependency_paths": _unique_strings(freshness.get("changed_dependency_paths", []), 48, 220),
        "dependency_paths": _unique_strings(freshness.get("dependency_paths", []), 48, 220),
        "provenance": _safe_value(record.get("provenance", {}), limit=300),
    }


def _build_superseded_reference(record: dict, reason: str = "record is superseded history") -> dict:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    return {
        "record_id": record.get("record_id"),
        "fact_hash": record.get("fact_hash"),
        "classification": SUPERSEDED,
        "fact_summary": _compact(fact.get("fact"), 420),
        "superseded_by": record.get("superseded_by"),
        "reason": _compact(reason, 320),
        "provenance": _safe_value(record.get("provenance", {}), limit=300),
    }


def _classification_ref(value: dict) -> dict:
    result = {
        key: _safe_value(value[key], limit=220)
        for key in (
            "record_id", "classification", "reason_code", "relevance_score", "relevant",
            "accepted_as_current",
        )
        if key in value
    }
    freshness = value.get("freshness")
    if isinstance(freshness, dict):
        result["freshness"] = {
            "fresh": bool(freshness.get("fresh")),
            "changed_dependency_paths": _unique_strings(freshness.get("changed_dependency_paths", []), 12, 120),
            "reason_code": _compact(freshness.get("reason_code"), 100),
        }
    return result


def _public_repository_observation(observation: dict, evidence: list[dict]) -> dict:
    return {
        "status": observation.get("status"),
        "available": bool(observation.get("available")),
        "source": observation.get("source"),
        "evidence_count": len(evidence),
        "rejected_count": int(observation.get("rejected_count", 0) or 0),
        "inventory_fingerprint": observation.get("inventory_fingerprint"),
        "workspace_fingerprint_before": observation.get("workspace_fingerprint_before"),
        "workspace_fingerprint_after": observation.get("workspace_fingerprint_after"),
        "read_only": bool(observation.get("read_only", True)),
        "errors": [str(item)[:300] for item in (observation.get("errors", []) or [])[:8]],
        "operations": [copy.deepcopy(item) for item in (observation.get("operations", []) or [])[:24]],
    }


def _reconcile_internal(
    project_id: str,
    project_brain: dict | list | None,
    workspace: str | Path | None,
    *,
    task_goal: str = "",
    new_requirements: Any = None,
    current_repository_evidence: Any = None,
    current_authority: Any = None,
    relevant_paths: Iterable[Any] | None = None,
    previous_task_completion: dict | None = None,
    promotion_provenance: dict | None = None,
) -> tuple[dict, dict[str, dict]]:
    identity = validate_project_identity(project_id, project_brain)
    if not identity.get("valid"):
        return {
            "status": REENTRY_PROJECT_ID_MISMATCH,
            "ready": False,
            "project_id": project_id,
            "identity_validation": identity,
            "model_calls": 0,
        }, {}
    requested_project = str(project_id)
    snapshot, records, snapshot_errors = _snapshot_records(requested_project, project_brain)
    if snapshot_errors and "Project Brain records are not a list" in snapshot_errors:
        return {
            "status": REENTRY_MEMORY_UNAVAILABLE,
            "ready": False,
            "project_id": requested_project,
            "errors": snapshot_errors[:8],
            "model_calls": 0,
        }, {}
    requirements, invalid_requirements = _normalize_requirements(new_requirements, task_goal)
    explicit_authority, invalid_authority = _normalize_current_authority(current_authority)
    observation = _repository_observation(
        workspace, _compact(task_goal, 900), requirements, current_repository_evidence,
    )
    if not observation.get("available"):
        return {
            "status": REENTRY_REPOSITORY_UNAVAILABLE,
            "ready": False,
            "project_id": requested_project,
            "identity_validation": identity,
            "repository_observation": _public_repository_observation(observation, []),
            "errors": [observation.get("error") or observation.get("status") or "current repository unavailable"],
            "model_calls": 0,
        }, {}

    query_text = " ".join([task_goal, *[item.get("text", "") for item in requirements]])
    query_terms = set(_tokens(query_text))
    requested_path_set = set(_normalize_paths(relevant_paths, workspace))
    requested_path_set.update(path.casefold() for path in _extract_paths_from_text(query_text))
    classifications: list[dict] = []
    valid_records: dict[str, dict] = {}
    invalid_records: list[dict] = []
    for record in records:
        valid, reason = _validate_stored_record(record, requested_project)
        if not valid:
            if reason == "PROJECT_ID_MISMATCH":
                classification = NOT_RELEVANT
                code = "PROJECT_ID_MISMATCH"
            else:
                classification = CONFLICTED
                code = INVALID_VERIFIED_RECORD if "authority" not in reason else INVALID_AUTHORITY_PROVENANCE
            classifications.append(_public_classification(
                record, classification, code, reason, relevant=False, accepted_as_current=False,
            ))
            invalid_records.append(record)
            continue
        record_id = str(record.get("record_id") or record.get("fact_hash") or "")
        if not record_id or record_id in valid_records:
            classifications.append(_public_classification(
                record, CONFLICTED, INVALID_VERIFIED_RECORD,
                "record identity is missing or duplicated", relevant=False, accepted_as_current=False,
            ))
            continue
        valid_records[record_id] = record

    current_records: list[dict] = []
    stale_records: list[dict] = []
    superseded_records: list[dict] = []
    contradictory_authority_records: list[dict] = []
    classified_by_id: dict[str, dict] = {}
    freshness_by_id: dict[str, dict] = {}
    for record in records:
        record_id = str(record.get("record_id") or record.get("fact_hash") or "")
        if record_id not in valid_records:
            continue
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        status = str(record.get("status") or "")
        if status == SUPERSEDED_RECORD or _superseded_by_other(record, records):
            classification = SUPERSEDED
            reason_code = "STORED_SUPERSEDED" if status == SUPERSEDED_RECORD else "EXPLICIT_SUPERSEDING_RECORD"
            reason = "record remains historical provenance and is not current truth"
            superseded_records.append(record)
            score, relevant = _record_relevance(record, query_terms, requested_path_set)
            item = _public_classification(
                record, classification, reason_code, reason,
                relevance_score=score, relevant=relevant, accepted_as_current=False,
            )
            classifications.append(item)
            classified_by_id[record_id] = item
            continue
        if _contradictory_active_authority(record, records):
            classification = CONFLICTED
            reason_code = CONTRADICTORY_ACTIVE_AUTHORITY
            reason = "active authority conflict has no explicit supersession or approved authority-change link"
            contradictory_authority_records.append(record)
            score, relevant = _record_relevance(record, query_terms, requested_path_set)
            item = _public_classification(
                record, classification, reason_code, reason,
                relevance_score=score, relevant=relevant, accepted_as_current=False,
            )
            classifications.append(item)
            classified_by_id[record_id] = item
            continue
        freshness = None
        durability = str(record.get("durability_class") or "")
        if status == STALE:
            classification = STALE_VERIFIED
            reason_code = "STORED_STALE"
            reason = "previously verified record is explicitly stale; no re-verification was attempted"
            stale_records.append(record)
        elif durability == STATE_BOUND_VERIFIED:
            freshness = _freshness_for_record(record, workspace)
            freshness_by_id[record_id] = freshness
            if freshness.get("fresh"):
                classification = CURRENT_VERIFIED
                reason_code = "STATE_BOUND_SUBJECT_CURRENT"
                reason = "state-bound dependency and subject-state binding match current repository state"
                current_records.append(record)
            else:
                classification = STALE_VERIFIED
                reason_code = "STATE_BOUND_SUBJECT_STALE"
                reason = "relevant dependency or subject-state binding changed; record is historical only"
                stale_records.append(record)
        else:
            classification = CURRENT_DURABLE_AUTHORITY
            reason_code = "DURABLE_AUTHORITY_CURRENT"
            reason = "durable authority remains current because identity and authority provenance are valid"
            current_records.append(record)
        score, relevant = _record_relevance(record, query_terms, requested_path_set)
        item = _public_classification(
            record, classification, reason_code, reason,
            relevance_score=score, relevant=relevant,
            accepted_as_current=classification in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY},
            freshness=freshness,
        )
        classifications.append(item)
        classified_by_id[record_id] = item

    # Keep only relevant current records in the task-facing projection, while
    # making the mandatory prohibition/authority priority explicit.
    current_ranked: list[tuple[int, int, str, dict]] = []
    for record in current_records:
        record_id = str(record.get("record_id") or "")
        item = classified_by_id.get(record_id, {})
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        mandatory = 1 if (
            fact.get("category") == "verified_prohibitions"
            or re.search(r"\b(?:do not|must not|never|sole|only)\b", str(fact.get("fact") or ""), re.IGNORECASE)
        ) else 0
        score = int(item.get("relevance_score", 0) or 0)
        if not item.get("relevant") and not mandatory:
            continue
        current_ranked.append((-mandatory, -score, record_id, record))
    current_ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    selected_current = [row[3] for row in current_ranked[:MAX_CURRENT_VERIFIED_FACTS]]
    selected_current_ids = {str(item.get("record_id") or "") for item in selected_current}
    for item in classifications:
        if item.get("classification") in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY}:
            item["accepted_as_current"] = item.get("record_id") in selected_current_ids
            if item.get("record_id") not in selected_current_ids:
                item["relevant"] = False
                item["reason_code"] = "OUTSIDE_TASK_BRAIN_BOUND"

    stale_ranked: list[tuple[int, str, dict, dict | None]] = []
    for record in stale_records:
        record_id = str(record.get("record_id") or "")
        item = classified_by_id.get(record_id, {})
        score = int(item.get("relevance_score", 0) or 0)
        if item.get("relevant") or score > 0:
            stale_ranked.append((-score, record_id, record, freshness_by_id.get(record_id)))
    stale_ranked.sort(key=lambda row: (row[0], row[1]))
    selected_stale = [
        _build_stale_warning(record, freshness or {},
                             "relevant state-bound dependency changed" if freshness else "record was stored stale")
        for _score, _record_id, record, freshness in stale_ranked[:MAX_STALE_FACTS]
    ]
    superseded_ranked = []
    for record in superseded_records:
        record_id = str(record.get("record_id") or "")
        item = classified_by_id.get(record_id, {})
        if item.get("relevant") or int(item.get("relevance_score", 0) or 0) > 0:
            superseded_ranked.append((
                -int(item.get("relevance_score", 0) or 0), record_id, record,
            ))
    superseded_ranked.sort(key=lambda row: (row[0], row[1]))
    selected_superseded = [
        _build_superseded_reference(record)
        for _score, _record_id, record in superseded_ranked[:MAX_SUPERSEDED_FACTS]
    ]

    selected_paths: set[str] = set(requested_path_set)
    for record in selected_current:
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        selected_paths.update(path.casefold() for path in _normalize_paths(fact.get("dependency_paths", []), workspace))
        selected_paths.update(path.casefold() for path in _normalize_paths(fact.get("path"), workspace))
    valid_evidence = [
        item for item in observation.get("evidence", []) or []
        if isinstance(item, dict) and validate_repository_evidence(item, workspace)
    ]
    evidence_ranked = [
        (-_evidence_relevance(item, query_terms, selected_paths), str(item.get("path") or ""), item)
        for item in valid_evidence
    ]
    evidence_ranked.sort(key=lambda row: (row[0], row[1], str(row[2].get("evidence_id") or "")))
    selected_evidence = [row[2] for row in evidence_ranked[:MAX_CURRENT_REPOSITORY_EVIDENCE]]

    conflicts = []
    conflicts.extend(_conflict(
        INVALID_AUTHORITY_PROVENANCE,
        authority_id=item.get("authority_id") or item.get("requirement_id"),
        reason="current authority was rejected because its provenance is not user authority",
        consumed_as_current=False,
    ) for item in invalid_authority)
    conflicts.extend(_conflict(
        INVALID_AUTHORITY_PROVENANCE,
        requirement_id=item.get("requirement_id"),
        reason="new requirement was rejected because its provenance is not user authority",
        consumed_as_current=False,
    ) for item in invalid_requirements)
    authority_requirements = [
        {
            "requirement_id": item.get("authority_id"),
            "text": item.get("text"),
            "provenance": item.get("provenance"),
            "authority": item.get("authority"),
        }
        for item in explicit_authority
    ]
    conflicts.extend(_new_requirement_conflicts(
        [*requirements, *authority_requirements], selected_current,
    ))
    authority_drift = classify_authority_repository_drift(selected_current, selected_evidence)
    conflicts.extend(authority_drift.get("conflicts", []))
    conflicts.extend(_conflict(
        CONTRADICTORY_ACTIVE_AUTHORITY,
        record_id=record.get("record_id"),
        conflict_key=(record.get("conflict_key") or (record.get("fact") or {}).get("conflict_key")),
        reason="contradictory active authority was retained only as an unresolved conflict",
        current_truth=False,
        resolution="REQUIRE_EXPLICIT_AUTHORITY_CHANGE_OR_SUPERSESSION",
    ) for record in contradictory_authority_records)
    for warning in selected_stale:
        conflicts.append(_conflict(
            STALE_VERIFIED_EVIDENCE,
            record_id=warning.get("record_id"),
            fact_hash=warning.get("fact_hash"),
            reason=warning.get("stale_reason"),
            changed_dependency_paths=warning.get("changed_dependency_paths", []),
            current_truth=False,
        ))
    conflicts = _deduplicate_conflicts(conflicts)

    all_dependency_paths: set[str] = set()
    for record in valid_records.values():
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        all_dependency_paths.update(_normalize_paths(fact.get("dependency_paths", []), workspace))
    dependency_fingerprint = fingerprint_dependency_paths(workspace, sorted(all_dependency_paths))
    source_hashes: list[str] = []
    for record in valid_records.values():
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        source_hashes.extend(_extract_promotion_hashes([fact, record.get("provenance", {})]))
    source_hashes.extend(_extract_promotion_hashes([previous_task_completion or {}, promotion_provenance or {}]))
    source_hashes = _unique_strings(source_hashes, MAX_PROMOTION_HASHES, 100)
    authority = _authority_entries(requirements, selected_current, explicit_authority)
    classification_counts: dict[str, int] = {}
    for item in classifications:
        classification = str(item.get("classification") or "UNKNOWN")
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
    current_public = []
    for record in selected_current:
        projected = _task_record_projection(_safe_record(
            record,
            classification=classified_by_id.get(str(record.get("record_id") or ""), {}).get("classification"),
        ))
        current_public.append(projected)
    current_authority_records = [
        item for item in selected_current
        if _normalize_authority((item.get("fact") or {}).get("authority")) == "USER/REQUIREMENT"
    ]
    classification_refs = [
        _classification_ref(item) for item in classifications[:MAX_CLASSIFICATION_REFS]
    ]
    metrics = {
        "verified_reentry_attempts": 1,
        "project_brain_records_considered": len(records),
        "project_brain_records_current": sum(
            1 for item in classifications if item.get("classification") in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY} and item.get("accepted_as_current")
        ),
        "project_brain_records_stale": sum(1 for item in classifications if item.get("classification") == STALE_VERIFIED),
        "project_brain_records_superseded": sum(1 for item in classifications if item.get("classification") == SUPERSEDED),
        "project_brain_records_relevant": sum(1 for item in classifications if item.get("relevant")),
        "project_brain_records_excluded": sum(1 for item in classifications if not item.get("relevant") or not item.get("accepted_as_current")),
        "reentry_conflicts": len(conflicts),
        **copy.deepcopy(authority_drift.get("metrics", _empty_authority_drift_metrics())),
        "task_brain_bootstraps": 0,
        "reentry_model_calls": 0,
        "freshness_model_calls": 0,
        "relevance_model_calls": 0,
        "task_brain_bootstrap_model_calls": 0,
        "automatic_reverification_attempts": 0,
    }
    public_observation = _public_repository_observation(observation, selected_evidence)
    reconciliation = {
        "status": REENTRY_RECONCILED,
        "ready": True,
        "schema_version": SCHEMA_VERSION,
        "project_id": requested_project,
        "project_brain_hash": canonical_hash(snapshot),
        "project_brain_record_ids_considered": [
            _compact(item.get("record_id") or item.get("fact_hash"), 180) for item in records
        ][:MAX_PROJECT_BRAIN_RECORDS],
        "record_classifications": classification_refs,
        "record_classification_count": len(classifications),
        "record_classification_counts": dict(sorted(classification_counts.items())),
        "record_classifications_truncated": len(classifications) > MAX_CLASSIFICATION_REFS,
        "authority_drift_audit": copy.deepcopy(authority_drift.get("audit", [])),
        "authority": authority,
        "current_verified_facts": current_public,
        "current_durable_authority": [
            _task_authority_projection(_safe_record(record, classification=CURRENT_DURABLE_AUTHORITY))
            for record in current_authority_records[:MAX_CURRENT_AUTHORITY]
        ],
        "stale_verified_facts": selected_stale,
        "superseded_facts": selected_superseded,
        "current_repository_evidence": [
            _repository_record_projection(item) for item in selected_evidence
        ],
        "repository_observation": public_observation,
        "repository_dependency_fingerprint": {
            "dependency_paths": sorted(all_dependency_paths, key=str.casefold),
            "fingerprint": dependency_fingerprint,
            "model_calls": 0,
        },
        "new_requirements": requirements,
        "new_requirements_hash": canonical_hash(requirements),
        "invalid_authority_inputs": [*invalid_requirements, *invalid_authority],
        "conflicts": conflicts,
        "source_promotion_hashes": source_hashes,
        "source_promotion_provenance": _safe_value(promotion_provenance or {}, limit=400),
        "continuation_provenance": _compact_completion_pointer(previous_task_completion),
        "metrics": metrics,
        "model_call_accounting": _zero_model_call_accounting(),
        "model_calls": 0,
        "provenance": {
            "source": "deterministic_v22_verified_project_brain_reconciliation",
            "model_calls": 0,
            "project_brain_read_only": True,
            "automatic_reverification": False,
            "old_task_brain_loaded": False,
            "private_execution_material_loaded": False,
        },
    }
    return reconciliation, valid_records


def reconcile_verified_project_brain(
    project_id: str,
    project_brain: dict | list | None,
    workspace: str | Path | None,
    *,
    task_goal: str = "",
    new_requirements: Any = None,
    current_repository_evidence: Any = None,
    current_authority: Any = None,
    relevant_paths: Iterable[Any] | None = None,
    previous_task_completion: dict | None = None,
    promotion_provenance: dict | None = None,
) -> dict:
    """Reconcile one Project Brain snapshot without changing durable state."""
    result, _records = _reconcile_internal(
        project_id, project_brain, workspace,
        task_goal=task_goal, new_requirements=new_requirements,
        current_repository_evidence=current_repository_evidence,
        current_authority=current_authority, relevant_paths=relevant_paths,
        previous_task_completion=previous_task_completion,
        promotion_provenance=promotion_provenance,
    )
    return result


reconcile_project_brain = reconcile_verified_project_brain
reconcile_verified_state = reconcile_verified_project_brain


def _context_hash_material(context: dict) -> dict:
    return {
        key: value for key, value in context.items()
        if key not in {"reentry_hash", "context_hash", "task_brain_hash"}
    }


def validate_reentry_context(context: dict | None) -> dict:
    value = context if isinstance(context, dict) else {}
    errors: list[str] = []
    if value.get("artifact_type") != REENTRY_CONTEXT_TYPE:
        errors.append("wrong ReentryContext artifact type")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong ReentryContext schema version")
    if not str(value.get("project_id") or "").strip() or not str(value.get("new_task_id") or "").strip():
        errors.append("project_id and new_task_id are required")
    if value.get("reentry_hash") != canonical_hash(_context_hash_material(value)):
        errors.append("reentry hash does not match canonical contents")
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    if int(value.get("model_calls", 0) or 0) != 0 or int(provenance.get("model_calls", 0) or 0) != 0:
        errors.append("ReentryContext contains model calls")
    if provenance.get("project_brain_read_only") is not True:
        errors.append("Project Brain read-only provenance is missing")
    if provenance.get("automatic_reverification") is not False:
        errors.append("automatic re-verification is not disabled")
    accounting = value.get("model_call_accounting")
    if not isinstance(accounting, dict) or any(
        int(accounting.get(role, 0) or 0) != 0 for role in _MODEL_CALL_ROLES
    ):
        errors.append("model-call accounting is not zero for every role")
    for key in (
        "authority", "current_verified_facts", "stale_verified_facts", "superseded_facts",
        "current_repository_evidence", "new_requirements", "conflicts", "source_promotion_hashes",
        "authority_drift_audit",
    ):
        if not isinstance(value.get(key), list):
            errors.append(f"{key} must be a list")
    if value.get("new_requirements_hash") != canonical_hash(value.get("new_requirements", [])):
        errors.append("new requirement hash does not match canonical requirements")
    for record in value.get("current_verified_facts", []) or []:
        if not isinstance(record, dict):
            errors.append("current verified fact is not structured")
            continue
        if record.get("classification") not in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY}:
            errors.append("stale or superseded fact entered current verified set")
        if record.get("project_id") != value.get("project_id"):
            errors.append("current fact project mismatch")
    if contains_forbidden_transcript(value):
        errors.append("ReentryContext contains private or raw transcript content")
    if _json_size(value) > MAX_REENTRY_CONTEXT_CHARS:
        errors.append("ReentryContext serialized-size bound exceeded")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:20],
        "serialized_chars": _json_size(value),
        "model_calls": 0,
    }


def build_reentry_context(
    project_id: str,
    new_task_id: str,
    project_brain: dict | list | None,
    workspace: str | Path | None,
    *,
    task_goal: str = "",
    new_requirements: Any = None,
    current_repository_evidence: Any = None,
    current_authority: Any = None,
    relevant_paths: Iterable[Any] | None = None,
    previous_task_completion: dict | None = None,
    promotion_provenance: dict | None = None,
) -> dict:
    """Create one bounded deterministic ReentryContext."""
    reconciliation, _records = _reconcile_internal(
        project_id, project_brain, workspace,
        task_goal=task_goal, new_requirements=new_requirements,
        current_repository_evidence=current_repository_evidence,
        current_authority=current_authority, relevant_paths=relevant_paths,
        previous_task_completion=previous_task_completion,
        promotion_provenance=promotion_provenance,
    )
    if not reconciliation.get("ready"):
        return {
            "status": reconciliation.get("status", REENTRY_INVALID_INPUT),
            "ready": False,
            "project_id": str(project_id or ""),
            "new_task_id": str(new_task_id or ""),
            "error": reconciliation.get("errors") or reconciliation.get("identity_validation", {}).get("errors", []),
            "reconciliation": reconciliation,
            "model_calls": 0,
        }
    context = {
        "status": REENTRY_RECONCILED,
        "ready": True,
        "schema_version": SCHEMA_VERSION,
        "artifact_type": REENTRY_CONTEXT_TYPE,
        "project_id": str(project_id),
        "new_task_id": _compact(new_task_id, 180),
        "task_goal": _compact(task_goal, 900),
        "authority": copy.deepcopy(reconciliation.get("authority", [])),
        "current_verified_facts": [
            _task_record_projection(item)
            for item in reconciliation.get("current_verified_facts", []) or []
            if isinstance(item, dict)
        ],
        "current_durable_authority": [
            _task_authority_projection(item) if isinstance(item.get("fact"), dict) else copy.deepcopy(item)
            for item in reconciliation.get("current_durable_authority", []) or []
            if isinstance(item, dict)
        ],
        "stale_verified_facts": copy.deepcopy(reconciliation.get("stale_verified_facts", [])),
        "superseded_facts": copy.deepcopy(reconciliation.get("superseded_facts", [])),
        "current_repository_evidence": copy.deepcopy(reconciliation.get("current_repository_evidence", [])),
        "repository_observation": copy.deepcopy(reconciliation.get("repository_observation", {})),
        "repository_dependency_fingerprint": copy.deepcopy(reconciliation.get("repository_dependency_fingerprint", {})),
        "new_requirements": copy.deepcopy(reconciliation.get("new_requirements", [])),
        "new_requirements_hash": reconciliation.get("new_requirements_hash"),
        "conflicts": copy.deepcopy(reconciliation.get("conflicts", [])),
        "source_promotion_hashes": copy.deepcopy(reconciliation.get("source_promotion_hashes", [])),
        "continuation_provenance": copy.deepcopy(reconciliation.get("continuation_provenance")),
        "source_promotion_provenance": copy.deepcopy(reconciliation.get("source_promotion_provenance", {})),
        "project_brain_hash": reconciliation.get("project_brain_hash"),
        "project_brain_record_ids_considered": copy.deepcopy(reconciliation.get("project_brain_record_ids_considered", [])),
        "record_classifications": copy.deepcopy(reconciliation.get("record_classifications", [])),
        "record_classification_count": reconciliation.get("record_classification_count", 0),
        "record_classification_counts": copy.deepcopy(reconciliation.get("record_classification_counts", {})),
        "record_classifications_truncated": bool(reconciliation.get("record_classifications_truncated", False)),
        "authority_drift_audit": copy.deepcopy(reconciliation.get("authority_drift_audit", [])),
        "metrics": copy.deepcopy(reconciliation.get("metrics", {})),
        "model_call_accounting": copy.deepcopy(reconciliation.get("model_call_accounting", _zero_model_call_accounting())),
        "model_calls": 0,
        "provenance": {
            "source": "deterministic_verified_state_reentry",
            "model_calls": 0,
            "project_brain_read_only": True,
            "automatic_reverification": False,
            "old_task_brain_loaded": False,
            "private_execution_material_loaded": False,
            "execution_started": False,
            "stage6b_invoked": False,
        },
    }
    context["reentry_hash"] = canonical_hash(_context_hash_material(context))
    context["context_hash"] = context["reentry_hash"]
    checked = validate_reentry_context(context)
    if not checked.get("valid"):
        return {
            "status": REENTRY_INVALID_INPUT,
            "ready": False,
            "project_id": str(project_id),
            "new_task_id": _compact(new_task_id, 180),
            "error": checked.get("errors", []),
            "validation": checked,
            "model_calls": 0,
        }
    return context


create_reentry_context = build_reentry_context


def _task_fact_score(record: dict, context: dict) -> tuple[int, int]:
    query_terms = set(_tokens(" ".join([
        str(context.get("task_goal") or ""),
        *[str(item.get("text") or "") for item in context.get("new_requirements", []) or [] if isinstance(item, dict)],
    ])))
    paths = set(_normalize_paths(context.get("repository_dependency_fingerprint", {}).get("dependency_paths", [])))
    score, _relevant = _record_relevance(record, query_terms, paths)
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    mandatory = 1 if (
        fact.get("category") == "verified_prohibitions"
        or re.search(r"\b(?:do not|must not|never|sole|only)\b", str(fact.get("fact") or ""), re.IGNORECASE)
    ) else 0
    return mandatory, score


def _trim_task_brain(brain: dict) -> dict:
    bounds = brain.setdefault("bounds", {})
    trimmed: dict[str, int] = {}
    # Leave room for the final canonical task_brain_hash and validation
    # metadata, which are appended after the content projection is trimmed.
    target_chars = max(1_000, MAX_TASK_BRAIN_CHARS - 512)
    trim_order = (
        # Stale records are safety-relevant history: keep their warning in a
        # fresh Task Brain whenever the bounded projection can retain it.
        # Remove optional repository/conflict material and duplicate authority
        # projections before reducing current facts, and trim stale history
        # only as the final bounded fallback.
        "superseded_facts", "current_repository_evidence", "authority_drift_audit", "conflicts",
        "current_durable_authority", "current_verified_facts", "stale_verified_facts",
    )
    while _json_size(brain) > target_chars:
        removed = False
        for field in trim_order:
            values = brain.get(field)
            if not isinstance(values, list) or not values:
                continue
            # Preserve explicit authority/prohibition facts when shrinking.
            if field in {"current_verified_facts", "current_durable_authority"}:
                removable = [
                    index for index, item in enumerate(values)
                    if not (
                        isinstance(item, dict)
                        and isinstance(item.get("fact"), dict)
                        and (
                            item["fact"].get("category") == "verified_prohibitions"
                            or _normalize_authority(item["fact"].get("authority")) == "USER/REQUIREMENT"
                            and re.search(r"\b(?:do not|must not|sole|only|owner|ownership)\b", str(item["fact"].get("fact") or ""), re.IGNORECASE)
                        )
                    )
                ]
                if not removable:
                    continue
                values.pop(removable[-1])
            else:
                values.pop()
            trimmed[field] = trimmed.get(field, 0) + 1
            removed = True
            break
        if not removed:
            break
    if trimmed:
        bounds["truncated"] = True
        bounds["trimmed"] = trimmed
    bounds["serialized_chars"] = _json_size(brain)
    return brain


def _task_record_projection(record: dict, *, include_project: bool = True) -> dict:
    """Keep the verified identity and enough evidence locators for one task."""
    value = copy.deepcopy(record) if isinstance(record, dict) else {}
    fact = value.get("fact") if isinstance(value.get("fact"), dict) else {}
    state_bound = value.get("durability_class") == STATE_BOUND_VERIFIED
    compact_fact: dict[str, Any] = {}
    keep_fact_keys = (
        "category", "field", "fact", "authority", "path", "symbol", "requirement_id",
        "kind", "result", "evidence_hash",
    )
    for key in keep_fact_keys:
        if key in fact:
            compact_fact[key] = _safe_value(
                fact[key], limit=140 if key == "fact" else 140,
            )
    if state_bound:
        compact_fact["dependency_paths"] = _unique_strings(
            fact.get("dependency_paths", []), 6, 100,
        )
        compact_fact["evidence_refs"] = _unique_strings(
            fact.get("evidence_refs", []), 2, 100,
        )
    result = {
        "record_id": _compact(value.get("record_id"), 180),
        "fact": compact_fact,
        "classification": value.get("classification"),
    }
    # The durable record id is the task-local identity for ordinary facts;
    # retain the full fact hash where a state-bound subject must be refreshed
    # or where the ReentryContext itself carries the full record reference.
    if include_project or state_bound:
        result["fact_hash"] = _compact(value.get("fact_hash"), 100)
    if include_project or state_bound:
        result["durability_class"] = _compact(value.get("durability_class"), 80)
    if include_project:
        result["project_id"] = _compact(value.get("project_id"), 180)
    if state_bound:
        result["subject_state_hash"] = _compact(value.get("subject_state_hash"), 100)
    if value.get("supersedes"):
        result["supersedes"] = _unique_strings(value.get("supersedes", []), 4, 140)
    if state_bound and value.get("provenance"):
        result["promotion_provenance"] = {
            "source": _compact((value.get("provenance") or {}).get("source"), 180),
            "model_calls": int((value.get("provenance") or {}).get("model_calls", 0) or 0),
        }
    return result


def _task_authority_projection(record: dict) -> dict:
    fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
    return {
        "record_id": record.get("record_id"),
        "fact_hash": record.get("fact_hash"),
        "text": _compact(fact.get("fact"), 220),
        "field": fact.get("field"),
        "category": fact.get("category"),
        "authority": _normalize_authority(fact.get("authority")),
        "provenance": "PROJECT_BRAIN",
        "status": "CURRENT",
    }


def _repository_record_projection(record: dict) -> dict:
    """Retain direct-observation identity without copying source snippets."""
    result = {
        "evidence_id": _compact(record.get("evidence_id"), 100),
        "category": _compact(record.get("category"), 100),
        "path": _compact(record.get("path"), 220),
        "symbol": _compact(record.get("symbol"), 180) or None,
        "fact": _compact(record.get("fact"), 300),
        "source_kind": _compact(record.get("source_kind"), 80),
        "evidence_type": record.get("evidence_type"),
        "provenance": record.get("provenance"),
        "line_start": record.get("line_start"),
        "line_end": record.get("line_end"),
        "file_sha256": _compact(record.get("file_sha256"), 100),
        "support": _compact(record.get("support"), 180),
    }
    relation = _structured_owner_relation(record)
    if relation is not None:
        result["structured_relation"] = relation
    return result


def validate_fresh_task_brain(task_brain: dict | None) -> dict:
    value = task_brain if isinstance(task_brain, dict) else {}
    errors: list[str] = []
    if value.get("artifact_type") != FRESH_TASK_BRAIN_TYPE:
        errors.append("wrong FreshTaskBrain artifact type")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong FreshTaskBrain schema version")
    if not str(value.get("project_id") or "").strip() or not str(value.get("task_id") or "").strip():
        errors.append("project_id and task_id are required")
    goal = value.get("task_goal")
    if not isinstance(goal, dict) or not str(goal.get("text") or "").strip() or goal.get("provenance") != "USER_STATED":
        errors.append("task_goal must be a USER_STATED entry")
    if value.get("task_brain_hash") != canonical_hash({key: item for key, item in value.items() if key != "task_brain_hash"}):
        errors.append("Task Brain hash does not match canonical contents")
    provenance = value.get("provenance") if isinstance(value.get("provenance"), dict) else {}
    if int(value.get("model_calls", 0) or 0) != 0 or int(provenance.get("model_calls", 0) or 0) != 0:
        errors.append("Task Brain contains model calls")
    if provenance.get("old_task_brain_reused") is not False or provenance.get("private_execution_material_loaded") is not False:
        errors.append("old Task Brain or private execution material was reused")
    for field in (
        "authority", "new_requirements", "current_verified_facts", "current_durable_authority",
        "current_repository_evidence", "stale_verified_facts", "superseded_facts", "conflicts",
        "source_promotion_hashes", "authority_drift_audit",
    ):
        if not isinstance(value.get(field), list):
            errors.append(f"{field} must be a list")
    for fact in value.get("current_verified_facts", []) or []:
        if not isinstance(fact, dict) or fact.get("classification") not in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY}:
            errors.append("stale/superseded fact appears as current")
            break
        if fact.get("project_id") is not None and fact.get("project_id") != value.get("project_id"):
            errors.append("Task Brain fact project mismatch")
            break
    bounds = value.get("bounds") if isinstance(value.get("bounds"), dict) else {}
    if int(bounds.get("serialized_chars", 0) or 0) > MAX_TASK_BRAIN_CHARS:
        errors.append("Task Brain serialized-size bound exceeded")
    if _json_size(value) > MAX_TASK_BRAIN_CHARS:
        errors.append("Task Brain serialized-size bound exceeded")
    if contains_forbidden_transcript(value):
        errors.append("Task Brain contains private or raw transcript content")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:20],
        "serialized_chars": _json_size(value),
        "model_calls": 0,
    }


def build_fresh_task_brain(
    context: dict,
    *,
    task_goal: str | None = None,
) -> dict:
    """Build a new bounded Task Brain; the prior Task Brain is never hydrated."""
    checked_context = validate_reentry_context(context)
    if not checked_context.get("valid"):
        return {
            "status": REENTRY_TASK_BRAIN_INVALID,
            "valid": False,
            "errors": checked_context.get("errors", []),
            "model_calls": 0,
        }
    goal_text = _compact(task_goal if task_goal is not None else context.get("task_goal"), 900)
    current = [item for item in context.get("current_verified_facts", []) or [] if isinstance(item, dict)]
    ranked = []
    for index, item in enumerate(current):
        mandatory, score = _task_fact_score(item, context)
        ranked.append((-mandatory, -score, index, item))
    ranked.sort(key=lambda row: (row[0], row[1], row[2]))
    selected_current = [row[3] for row in ranked[:MAX_TASK_BRAIN_FACTS]]
    mandatory_ids = {
        item.get("record_id") for item in selected_current
        if isinstance(item.get("fact"), dict) and (
            item["fact"].get("category") == "verified_prohibitions"
            or re.search(r"\b(?:do not|must not|sole|only|owner|ownership)\b", str(item["fact"].get("fact") or ""), re.IGNORECASE)
        )
    }
    # If the general relevance cap were ever lowered, restore mandatory
    # authority records deterministically before optional facts.
    for item in current:
        if item.get("record_id") in mandatory_ids or item.get("record_id") in {entry.get("record_id") for entry in selected_current}:
            continue
        if isinstance(item.get("fact"), dict) and item["fact"].get("category") == "verified_prohibitions":
            selected_current.append(item)
    selected_current = selected_current[:MAX_TASK_BRAIN_FACTS]
    selected_ids = {item.get("record_id") for item in selected_current}
    selected_authority = [
        item for item in context.get("current_durable_authority", []) or []
        if isinstance(item, dict) and item.get("record_id") in selected_ids
    ]
    selected_current = [_task_record_projection(item, include_project=False) for item in selected_current]
    if not selected_authority:
        selected_authority = [
            item for item in selected_current
            if isinstance(item.get("fact"), dict)
            and _normalize_authority(item["fact"].get("authority")) == "USER/REQUIREMENT"
        ][:MAX_TASK_BRAIN_AUTHORITY]
    else:
        selected_authority = [_task_authority_projection(item) for item in selected_authority]
    brain = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": FRESH_TASK_BRAIN_TYPE,
        "project_id": context.get("project_id"),
        "task_id": context.get("new_task_id"),
        "task_goal": {
            "text": goal_text,
            "provenance": "USER_STATED",
            "requirement_ids": [item.get("requirement_id") for item in context.get("new_requirements", []) or [] if isinstance(item, dict)][:MAX_TASK_BRAIN_AUTHORITY],
        },
        "authority": copy.deepcopy(context.get("authority", []))[:MAX_TASK_BRAIN_AUTHORITY],
        "new_requirements": copy.deepcopy(context.get("new_requirements", []))[:MAX_TASK_BRAIN_AUTHORITY],
        "current_verified_facts": copy.deepcopy(selected_current),
        "current_durable_authority": copy.deepcopy(selected_authority),
        "current_repository_evidence": copy.deepcopy(context.get("current_repository_evidence", []))[:MAX_TASK_BRAIN_EVIDENCE],
        "stale_verified_facts": copy.deepcopy(context.get("stale_verified_facts", []))[:MAX_TASK_BRAIN_STALE],
        "superseded_facts": copy.deepcopy(context.get("superseded_facts", []))[:MAX_TASK_BRAIN_SUPERSEDED],
        "conflicts": copy.deepcopy(context.get("conflicts", []))[:MAX_TASK_BRAIN_CONFLICTS],
        "authority_drift_audit": copy.deepcopy(context.get("authority_drift_audit", []))[:MAX_TASK_BRAIN_DRIFT_AUDIT],
        "source_promotion_hashes": _unique_strings(context.get("source_promotion_hashes", []), MAX_PROMOTION_HASHES, 100),
        "continuation_provenance": copy.deepcopy(context.get("continuation_provenance")),
        "reentry_hash": context.get("reentry_hash"),
        "provenance": {
            "source": "deterministic_fresh_task_brain_bootstrap",
            "model_calls": 0,
            "old_task_brain_reused": False,
            "old_task_brain_mutable": False,
            "private_execution_material_loaded": False,
            "private_execution_material_included": False,
            "automatic_reverification": False,
            "project_brain_mutated": False,
            "execution_started": False,
        },
        "bounds": {
            "max_serialized_chars": MAX_TASK_BRAIN_CHARS,
            "max_current_verified_facts": MAX_TASK_BRAIN_FACTS,
            "max_authority": MAX_TASK_BRAIN_AUTHORITY,
            "max_repository_evidence": MAX_TASK_BRAIN_EVIDENCE,
            "max_stale_facts": MAX_TASK_BRAIN_STALE,
            "max_superseded_facts": MAX_TASK_BRAIN_SUPERSEDED,
            "max_conflicts": MAX_TASK_BRAIN_CONFLICTS,
            "max_authority_drift_audit": MAX_TASK_BRAIN_DRIFT_AUDIT,
            "truncated": False,
        },
        "model_calls": 0,
    }
    brain = _trim_task_brain(brain)
    brain["task_brain_hash"] = canonical_hash({key: item for key, item in brain.items() if key != "task_brain_hash"})
    checked = validate_fresh_task_brain(brain)
    if not checked.get("valid"):
        return {
            "status": REENTRY_TASK_BRAIN_INVALID,
            "valid": False,
            "errors": checked.get("errors", []),
            "task_brain": brain,
            "model_calls": 0,
        }
    return brain


bootstrap_task_brain = build_fresh_task_brain
build_task_brain_from_reentry = build_fresh_task_brain
bootstrap_fresh_task_brain = build_fresh_task_brain
create_fresh_task_brain = build_fresh_task_brain


def run_verified_state_reentry(
    store: Any,
    project_id: str,
    new_task_id: str,
    task_goal: str = "",
    *,
    new_requirements: Any = None,
    workspace: str | Path | None = None,
    current_repository_evidence: Any = None,
    current_authority: Any = None,
    relevant_paths: Iterable[Any] | None = None,
    previous_task_id: str | None = None,
    previous_task_completion: dict | None = None,
    promotion_provenance: dict | None = None,
) -> dict:
    """Run the V23 re-entry boundary and stop after a fresh Task Brain."""
    requested_project = str(project_id or "").strip()
    if not requested_project or not str(new_task_id or "").strip():
        return {
            "status": REENTRY_INVALID_INPUT,
            "ready": False,
            "errors": ["project_id and new_task_id are required"],
            "model_calls": 0,
        }
    if store is None or not hasattr(store, "project_brain_snapshot"):
        return {
            "status": REENTRY_MEMORY_UNAVAILABLE,
            "ready": False,
            "project_id": requested_project,
            "errors": ["verified Project Brain read API is unavailable"],
            "model_calls": 0,
        }
    root = workspace
    if root is None:
        root = getattr(store, "workspace", None)
    try:
        snapshot = store.project_brain_snapshot(requested_project, include_inactive=True)
    except Exception as exc:
        return {
            "status": REENTRY_MEMORY_UNAVAILABLE,
            "ready": False,
            "project_id": requested_project,
            "errors": [f"verified Project Brain read failed: {_compact(exc, 420)}"],
            "model_calls": 0,
        }
    if not isinstance(snapshot, (dict, list)):
        return {
            "status": REENTRY_MEMORY_UNAVAILABLE,
            "ready": False,
            "project_id": requested_project,
            "errors": ["verified Project Brain read returned no structured snapshot"],
            "model_calls": 0,
        }
    identity = validate_project_identity(requested_project, snapshot)
    if not identity.get("valid"):
        return {
            "status": REENTRY_PROJECT_ID_MISMATCH,
            "ready": False,
            "project_id": requested_project,
            "identity_validation": identity,
            "model_calls": 0,
        }
    pointer = previous_task_completion
    if pointer is None and previous_task_id:
        try:
            pointer = store.get_task_brain_completion(requested_project, previous_task_id)
        except Exception as exc:
            return {
                "status": REENTRY_MEMORY_UNAVAILABLE,
                "ready": False,
                "project_id": requested_project,
                "errors": [f"completion-pointer read failed: {_compact(exc, 420)}"],
                "model_calls": 0,
            }
    context = build_reentry_context(
        requested_project, new_task_id, snapshot, root,
        task_goal=task_goal, new_requirements=new_requirements,
        current_repository_evidence=current_repository_evidence,
        current_authority=current_authority, relevant_paths=relevant_paths,
        previous_task_completion=pointer,
        promotion_provenance=promotion_provenance,
    )
    if not context.get("ready"):
        return {
            "status": context.get("status", REENTRY_INVALID_INPUT),
            "ready": False,
            "project_id": requested_project,
            "new_task_id": new_task_id,
            "reentry_context": context,
            "model_calls": 0,
        }
    brain = build_fresh_task_brain(context, task_goal=task_goal or context.get("task_goal"))
    if not brain.get("artifact_type"):
        return {
            "status": REENTRY_TASK_BRAIN_INVALID,
            "ready": False,
            "project_id": requested_project,
            "new_task_id": new_task_id,
            "reentry_context": context,
            "task_brain": brain,
            "model_calls": 0,
        }
    context["metrics"]["task_brain_bootstraps"] = 1
    context["metrics"]["task_brain_bootstrap_model_calls"] = 0
    context["reentry_hash"] = canonical_hash(_context_hash_material(context))
    context["context_hash"] = context["reentry_hash"]
    # The hash is intentionally recomputed after the bootstrap metric is
    # recorded, then the fresh Task Brain points at that final context hash.
    brain["reentry_hash"] = context["reentry_hash"]
    brain["task_brain_hash"] = canonical_hash({key: item for key, item in brain.items() if key != "task_brain_hash"})
    context_check = validate_reentry_context(context)
    brain_check = validate_fresh_task_brain(brain)
    if not context_check.get("valid") or not brain_check.get("valid"):
        return {
            "status": REENTRY_TASK_BRAIN_INVALID,
            "ready": False,
            "project_id": requested_project,
            "new_task_id": new_task_id,
            "reentry_context": context,
            "task_brain": brain,
            "context_validation": context_check,
            "task_brain_validation": brain_check,
            "model_calls": 0,
        }
    return {
        "status": REENTRY_READY,
        "ready": True,
        "project_id": requested_project,
        "new_task_id": str(new_task_id),
        "reentry_context": context,
        "task_brain": brain,
        "metrics": copy.deepcopy(context.get("metrics", {})),
        "model_call_accounting": copy.deepcopy(
            context.get("model_call_accounting", _zero_model_call_accounting())
        ),
        "model_calls": 0,
        "execution_started": False,
        "next_stage": "STOP_AFTER_FRESH_TASK_BRAIN",
        "project_brain_mutated": False,
        "project_brain_read_only": True,
        "read_only": True,
        "automatic_reverification": False,
        "verification_calls": 0,
        "stage6b_invoked": False,
    }


reenter_verified_state = run_verified_state_reentry
run_stage6a_reentry = run_verified_state_reentry


def _selftest_record(
    *,
    project_id: str,
    record_id: str,
    fact_text: str,
    category: str,
    field: str,
    durability: str,
    subject_hash: str,
    dependency_paths: list[str],
    authority: str = "USER/REQUIREMENT",
    authority_source: str = "approved_requirement_field",
    status: str = ACTIVE,
    supersedes: list[str] | None = None,
) -> dict:
    fact = {
        "category": category,
        "field": field,
        "fact": fact_text,
        "authority": authority,
        "authority_source": authority_source,
        "source": "approved_requirement_contract" if authority == "USER/REQUIREMENT" else "verified_parent_integration_evidence",
        "verified": True,
        "approved": True,
        "evidence_refs": ["parent:" + subject_hash],
        "dependency_paths": dependency_paths,
        "subject_state_hash": subject_hash,
        "durability_class": durability,
        "conflict_key": f"{category}:{field}:{fact_text.casefold()}",
    }
    fact["semantic_hash"] = canonical_hash(_fact_semantic_material(fact))
    fact["fact_hash"] = canonical_hash(_without(fact, "fact_hash"))
    return {
        "record_id": record_id,
        "project_id": project_id,
        "fact_hash": fact["fact_hash"],
        "semantic_hash": fact["semantic_hash"],
        "conflict_key": fact["conflict_key"],
        "fact": fact,
        "durability_class": durability,
        "subject_state_hash": subject_hash,
        "status": status,
        "supersedes": supersedes or [],
        "superseded_by": None,
        "provenance": {
            "source": "deterministic_verified_parent_receipt",
            "model_calls": 0,
            "raw_worker_transcript_included": False,
            "authority_escalation": False,
            "cross_project_memory": False,
        },
    }


def run_verified_state_reentry_self_test() -> dict:
    """Exercise fresh, stale, conflict, drift, and cross-project re-entry.

    The self-test uses a deterministic temporary filesystem and a read-only
    fake store.  It intentionally does not invoke the V22 promotion boundary,
    a Worker, a verifier, or Gemma; it tests the Stage 6A boundary itself.
    """
    checks: dict[str, bool] = {}
    diagnostics: dict[str, Any] = {}
    try:
        with TemporaryDirectory(prefix="hivo_v23_reentry_selftest_") as tmp:
            root = Path(tmp)
            files = {
                "src/input.js": "export class InputManager { handleEscape() {} }\n",
                "src/pause_controller.js": "export class PauseController { togglePause() {} }\n",
                "src/status_view.js": "export class StatusView { render() {} }\n",
                "tests/pause_flow.integration.test.js": "test('pause', () => true);\n",
            }
            for relative, content in files.items():
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding="utf-8")
            dependencies = list(files)
            subject = fingerprint_dependency_paths(root, dependencies)
            project_id = "self-test-project"
            records = [
                _selftest_record(
                    project_id=project_id, record_id="verified-durable-owner",
                    fact_text="PauseController remains the sole pause-state owner.",
                    category="verified_facts", field="state_ownership", durability=DURABLE_VERIFIED,
                    subject_hash=subject["hash"], dependency_paths=dependencies,
                ),
                _selftest_record(
                    project_id=project_id, record_id="verified-durable-dnt",
                    fact_text="Do not modify src/pause_controller.js.",
                    category="verified_prohibitions", field="do_not_touch", durability=DURABLE_VERIFIED,
                    subject_hash=subject["hash"], dependency_paths=dependencies,
                ),
                _selftest_record(
                    project_id=project_id, record_id="verified-state-integration",
                    fact_text="Required integration verification passed.",
                    category="verified_tests", field="integration_test_evidence", durability=STATE_BOUND_VERIFIED,
                    subject_hash=subject["hash"], dependency_paths=dependencies,
                    authority="VERIFIED/EVIDENCE", authority_source="verified_parent_verification_receipt",
                ),
                _selftest_record(
                    project_id=project_id, record_id="verified-unrelated",
                    fact_text="Unrelated deployment policy is retained separately.",
                    category="verified_facts", field="deployment_policy", durability=DURABLE_VERIFIED,
                    subject_hash=subject["hash"], dependency_paths=["README.md"],
                ),
            ]
            snapshot = {"project_id": project_id, "records": records}

            class ReadOnlyStore:
                workspace = root

                def project_brain_snapshot(self, requested, *, include_inactive=True):
                    if requested != project_id:
                        return {"project_id": requested, "records": []}
                    return copy.deepcopy(snapshot)

                def get_task_brain_completion(self, requested, task_id):
                    if requested == project_id and task_id == "OLD":
                        return {
                            "schema_version": "V22.5C", "task_id": "OLD",
                            "terminal_state": "VERIFIED_AND_PROMOTED",
                            "promotion_hash": "a" * 64,
                            "parent_verification_hash": "b" * 64,
                            "subject_state_hash": subject["hash"],
                            "artifact_refs": ["opaque:receipt"],
                            "project_brain_record_ids": ["verified-durable-owner"],
                            "completion_hash": "c" * 64,
                        }
                    return None

            store = ReadOnlyStore()
            fresh = run_verified_state_reentry(
                store, project_id, "NEW", "Continue pause behavior.",
                workspace=root, previous_task_id="OLD",
            )
            unchanged_brain = fresh.get("task_brain", {})
            checks["fresh_ready"] = fresh.get("status") == REENTRY_READY
            checks["fresh_state_current"] = any(
                item.get("record_id") == "verified-state-integration"
                for item in unchanged_brain.get("current_verified_facts", [])
            )
            checks["fresh_task_is_new"] = unchanged_brain.get("task_id") == "NEW" and unchanged_brain.get("provenance", {}).get("old_task_brain_reused") is False
            checks["fresh_relevance_excludes_unrelated"] = not any(
                item.get("record_id") == "verified-unrelated"
                for item in unchanged_brain.get("current_verified_facts", [])
            )
            checks["fresh_zero_model"] = fresh.get("model_calls") == 0 and fresh.get("metrics", {}).get("reentry_model_calls") == 0
            checks["fresh_no_execution"] = fresh.get("execution_started") is False
            checks["fresh_brain_read_only"] = fresh.get("project_brain_mutated") is False
            checks["unchanged_no_unsupported_drift"] = not any(
                item.get("kind") == AUTHORITY_IMPLEMENTATION_DRIFT
                for item in (fresh.get("reentry_context") or {}).get("conflicts", [])
            )
            checks["unknown_conformance_not_fake_drift"] = all(
                item.get("classification") in {NOT_EVALUABLE, NOT_RELEVANT}
                for item in (fresh.get("reentry_context") or {}).get("authority_drift_audit", [])
            )
            fresh_hash = fresh.get("reentry_context", {}).get("reentry_hash")

            (root / "README.tmp").write_text("unrelated\n", encoding="utf-8")
            unrelated = run_verified_state_reentry(
                store, project_id, "UNRELATED", "Continue pause behavior.", workspace=root,
            )
            checks["unrelated_does_not_stale_state"] = "verified-state-integration" not in {
                item.get("record_id") for item in unrelated.get("task_brain", {}).get("stale_verified_facts", [])
            }

            comment_changed = root / "src" / "input.js"
            comment_changed.write_text(
                comment_changed.read_text(encoding="utf-8") + "// stage6a stale-evidence probe\n",
                encoding="utf-8",
            )
            comment_probe = run_verified_state_reentry(
                store, project_id, "COMMENT-ONLY", "Continue pause behavior.", workspace=root,
            )
            comment_context = comment_probe.get("reentry_context", {})
            checks["comment_only_state_bound_stale"] = "verified-state-integration" in {
                item.get("record_id") for item in comment_probe.get("task_brain", {}).get("stale_verified_facts", [])
            }
            checks["comment_only_no_semantic_drift"] = not any(
                item.get("kind") == AUTHORITY_IMPLEMENTATION_DRIFT
                for item in comment_context.get("conflicts", [])
            )

            changed = root / "src" / "input.js"
            changed.write_text("export class InputManager { changed() {} }\n", encoding="utf-8")
            stale = run_verified_state_reentry(
                store, project_id, "STALE", "Continue pause behavior.", workspace=root,
            )
            stale_context = stale.get("reentry_context", {})
            stale_brain = stale.get("task_brain", {})
            stale_ids = {item.get("record_id") for item in stale_brain.get("stale_verified_facts", [])}
            checks["stale_ready"] = stale.get("status") == REENTRY_READY
            checks["stale_excluded_from_current"] = "verified-state-integration" not in {
                item.get("record_id") for item in stale_brain.get("current_verified_facts", [])
            }
            checks["stale_warning_retained"] = "verified-state-integration" in stale_ids
            checks["stale_no_reverification"] = stale.get("verification_calls") == 0 and stale.get("metrics", {}).get("automatic_reverification_attempts") == 0
            checks["relevant_change_changes_hash"] = fresh_hash != stale_context.get("reentry_hash")

            conflict = run_verified_state_reentry(
                store, project_id, "CONFLICT", "Move pause-state ownership away from PauseController.", workspace=root,
            )
            conflict_context = conflict.get("reentry_context", {})
            checks["new_requirement_conflict"] = any(
                item.get("kind") == NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE
                for item in conflict_context.get("conflicts", [])
            )
            checks["conflict_preserves_state"] = any(
                item.get("record_id") == "verified-durable-owner"
                for item in conflict.get("task_brain", {}).get("current_verified_facts", [])
            )

            structured_authority = copy.deepcopy(records[0])
            structured_authority["record_id"] = "structured-authority"
            structured_authority["fact"]["fact"] = "owner(PAUSE_STATE) = PauseController"
            structured_before = copy.deepcopy(structured_authority)
            structured_consistent = classify_authority_repository_drift(
                [structured_authority],
                [{
                    "evidence_id": "REPO-SELF-CONSISTENT",
                    "category": "CURRENT_STATE_OWNER",
                    "fact": "owner(PAUSE_STATE) = PauseController",
                }],
            )
            structured_drift = classify_authority_repository_drift(
                [structured_authority],
                [{
                    "evidence_id": "REPO-SELF-DRIFT",
                    "category": "CURRENT_STATE_OWNER",
                    "fact": "owner(PAUSE_STATE) = StatusView",
                }],
            )
            unknown_conformance = classify_authority_repository_drift(
                [structured_authority],
                [{
                    "evidence_id": "REPO-SELF-UNKNOWN",
                    "category": "CURRENT_INTERFACE",
                    "fact": "PauseController.togglePause is a current interface",
                }],
            )
            checks["structured_consistency_confirmed"] = (
                structured_consistent.get("audit", [{}])[0].get("classification") == CONFIRMED_CONSISTENT
                and not structured_consistent.get("conflicts")
            )
            checks["structured_drift_confirmed_once"] = (
                structured_drift.get("audit", [{}])[0].get("classification") == CONFIRMED_DRIFT
                and len(structured_drift.get("conflicts", [])) == 1
            )
            checks["structured_drift_keeps_authority_immutable"] = structured_authority == structured_before
            checks["structured_unknown_not_evaluable"] = (
                unknown_conformance.get("audit", [{}])[0].get("classification") == NOT_EVALUABLE
                and not unknown_conformance.get("conflicts")
            )
            cross = build_reentry_context(
                "other-project", "CROSS", {"project_id": project_id, "records": records}, root,
                task_goal="Continue pause behavior.",
            )
            checks["cross_project_excluded"] = cross.get("status") == REENTRY_PROJECT_ID_MISMATCH

            diagnostics.update({
                "fresh_reentry_hash": fresh_hash,
                "stale_reentry_hash": stale_context.get("reentry_hash"),
                "fresh_status": fresh.get("status"),
                "stale_status": stale.get("status"),
                "fresh_errors": fresh.get("errors") or fresh.get("task_brain_validation", {}).get("errors", []),
                "stale_errors": stale.get("errors") or stale.get("task_brain_validation", {}).get("errors", []),
                "fresh_context_validation": fresh.get("context_validation", {}),
                "fresh_task_brain_validation": fresh.get("task_brain_validation", {}),
                "stale_context_validation": stale.get("context_validation", {}),
                "stale_task_brain_validation": stale.get("task_brain_validation", {}),
                "fresh_task_brain_errors": (fresh.get("task_brain") or {}).get("errors", []),
                "stale_task_brain_errors": (stale.get("task_brain") or {}).get("errors", []),
                "comment_probe_metrics": comment_probe.get("metrics", {}),
                "fresh_authority_drift_audit": (fresh.get("reentry_context") or {}).get("authority_drift_audit", []),
                "comment_authority_drift_audit": comment_context.get("authority_drift_audit", []),
                "structured_consistent": structured_consistent,
                "structured_drift": structured_drift,
                "structured_unknown": unknown_conformance,
                "fresh_keys": sorted(fresh),
                "stale_keys": sorted(stale),
                "fresh_context_status": (fresh.get("reentry_context") or {}).get("status"),
                "stale_context_status": (stale.get("reentry_context") or {}).get("status"),
                "fresh_reentry_context_error": (fresh.get("reentry_context") or {}).get("error"),
                "stale_reentry_context_error": (stale.get("reentry_context") or {}).get("error"),
                "fresh_forbidden_fields": [
                    key for key, value in (fresh.get("reentry_context") or {}).items()
                    if contains_forbidden_transcript(value)
                ],
                "fresh_current_ids": [
                    item.get("record_id") for item in unchanged_brain.get("current_verified_facts", [])
                ],
                "fresh_stale_ids": [
                    item.get("record_id") for item in unchanged_brain.get("stale_verified_facts", [])
                ],
                "fresh_classifications": (fresh.get("reentry_context") or {}).get("record_classifications", []),
                "conflict_count": len(conflict_context.get("conflicts", [])),
            })
    except Exception as exc:
        diagnostics["exception"] = _compact(exc, 500)
        checks["exception_free"] = False
    else:
        checks["exception_free"] = True
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "diagnostics": diagnostics,
        "model_calls": 0,
    }


run_stage6a_self_test = run_verified_state_reentry_self_test
verified_state_reentry_self_test = run_verified_state_reentry_self_test


__all__ = [name for name in globals() if not name.startswith("_")]
