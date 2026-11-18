"""V24 Stage 6B verified-state-aware planning boundary.

This module is deliberately a deterministic adapter between the V23
``FreshTaskBrain`` and the existing Stage 3 planning implementation.  It
does not create authority, refresh verification, write the Project Brain, or
introduce another model role.  The returned planning context is a bounded
projection whose source hashes make it possible to reject a plan when the
source state changes before the approval boundary.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any, Iterable

from hivo.integration_gate import canonical_hash
from hivo.project_understanding import REPOSITORY_EVIDENCE
from hivo.reentry import (
    AUTHORITY_IMPLEMENTATION_DRIFT,
    CONFIRMED_CONSISTENT,
    CONFIRMED_DRIFT,
    CURRENT_DURABLE_AUTHORITY,
    CURRENT_VERIFIED,
    FRESH_TASK_BRAIN_TYPE,
    NEW_REQUIREMENT_VS_CURRENT_ARCHITECTURE,
    NOT_EVALUABLE,
    NOT_RELEVANT,
    STALE_VERIFIED,
    validate_fresh_task_brain,
    validate_reentry_context,
)


SCHEMA_VERSION = "V24.6B"
VERIFIED_PLANNING_CONTEXT_TYPE = "VerifiedPlanningContext"

VERIFIED_STATE_REENTRY = "VERIFIED_STATE_REENTRY"
INITIAL_PROJECT_PLANNING = "INITIAL_PROJECT_PLANNING"

PLANNING_CONTEXT_READY = "PLANNING_CONTEXT_READY"
PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE = (
    "PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE"
)
PLANNING_CONTEXT_INVALID = "PLANNING_CONTEXT_INVALID"
PLANNING_CONTEXT_STALE = "PLANNING_CONTEXT_STALE"

PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE = "PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE"
UNAUTHORIZED_AUTHORITY_CHANGE = "UNAUTHORIZED_AUTHORITY_CHANGE"
CONFIRMED_DRIFT_NOT_ADDRESSED = "CONFIRMED_DRIFT_NOT_ADDRESSED"
MANDATORY_AUTHORITY_DROPPED = "MANDATORY_AUTHORITY_DROPPED"

MAX_REQUIREMENTS = 24
MAX_AUTHORITY = 32
MAX_FACTS = 32
MAX_REPOSITORY_EVIDENCE = 16
MAX_STALE_WARNINGS = 16
MAX_CONFLICTS = 16
MAX_INTERFACES = 16
MAX_PROHIBITIONS = 16
MAX_AUDIT_ITEMS = 32
MAX_CONTEXT_CHARS = 24_000
MAX_RENDERED_CONTEXT_CHARS = 9_000

_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_transcript", "private_reasoning", "raw_worker_output", "raw_content",
    "worker_output", "model_output", "mission_compiler_output", "task_fit_output",
    "decomposer_output", "raw_model_output", "raw_model_transcript",
    "falsifier_output", "strategy_output", "strategy_text", "repair_output",
    "repair_speculation", "old_task_brain", "completed_task_brain",
})

_PROHIBITION_RE = re.compile(
    r"\b(?:do not|don't|must not|never|no duplicate|sole|only|preserv(?:e|ing)|"
    r"retain|remain|without breaking)\b",
    re.IGNORECASE,
)
_OWNER_ACTION_RE = re.compile(
    r"\b(?:add|create|introduce|make|move|migrate|transfer|replace|change)\b"
    r".{0,100}\b(?:owner|ownership|pause[- ]state|state owner|state)\b",
    re.IGNORECASE,
)
_OWNER_TOKEN_RE = re.compile(
    r"\b[A-Z][A-Za-z0-9_]*(?:Controller|View|Manager|State|Service|Owner|Store|Router)\b"
)
STRUCTURED_SURFACE_RELATIONS = frozenset({
    "CURRENT_IMPLEMENTATION_SURFACE",
    "CURRENT_BEHAVIOR_OWNER",
    "CURRENT_RENDER_SURFACE",
    "CURRENT_INTERFACE_IMPLEMENTATION",
    "CURRENT_TEST",
    "CURRENT_STATE_OWNER",
    "TEST_TO_SOURCE_IMPORT",
    "PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW",
    "PRESERVE_BEHAVIOR:MOVEMENT_INPUT",
    "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER",
    "USER_FACING_PAUSE_INDICATOR",
})


def _without(value: dict[str, Any], key: str) -> dict[str, Any]:
    return {name: item for name, item in value.items() if name != key}


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _compact(value: Any, limit: int = 700) -> str:
    text = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _list(value: Any) -> list[Any]:
    if isinstance(value, (list, tuple)):
        return list(value)
    if value in (None, "") or isinstance(value, (dict, set)):
        return []
    return [value]


def _unique_strings(values: Iterable[Any], limit: int = 24, chars: int = 260) -> list[str]:
    result: list[str] = []
    for value in values or []:
        text = _compact(value, chars)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _safe(value: Any, *, depth: int = 0, limit: int = 900) -> Any:
    """Keep the projection bounded and reject private/history-shaped keys."""
    if depth > 5:
        return _compact(value, limit)
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).casefold() in _PRIVATE_KEYS:
                continue
            result[str(key)] = _safe(item, depth=depth + 1, limit=limit)
        return result
    if isinstance(value, list):
        return [_safe(item, depth=depth + 1, limit=limit) for item in value[:32]]
    if isinstance(value, tuple):
        return [_safe(item, depth=depth + 1, limit=limit) for item in value[:32]]
    if isinstance(value, str):
        return _compact(value, limit)
    return value


def _contains_private(value: Any) -> bool:
    if isinstance(value, dict):
        return any(
            str(key).casefold() in _PRIVATE_KEYS or _contains_private(item)
            for key, item in value.items()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_private(item) for item in value)
    return False


def _fact_dict(item: dict) -> dict:
    fact = item.get("fact")
    return fact if isinstance(fact, dict) else {}


def _fact_text(item: dict) -> str:
    fact = _fact_dict(item)
    if fact:
        return _compact(
            fact.get("fact") or fact.get("text") or fact.get("description")
            or fact.get("value") or item.get("fact_summary"),
            520,
        )
    return _compact(item.get("fact_summary") or item.get("text") or item.get("fact"), 520)


def _structured_relation_names(item: Any) -> list[str]:
    value = item if isinstance(item, dict) else {}
    pending = []
    for key in ("structured_relations", "structured_relation", "semantic_relations"):
        raw = value.get(key)
        if isinstance(raw, (list, tuple, set)):
            pending.extend(raw)
        elif isinstance(raw, str):
            pending.append(raw)
    result = []
    while pending:
        raw = pending.pop(0)
        if isinstance(raw, (list, tuple, set)):
            pending[0:0] = list(raw)
            continue
        if not isinstance(raw, str):
            continue
        name = raw.strip().upper()
        if name in STRUCTURED_SURFACE_RELATIONS and name not in result:
            result.append(name)
    return result[:8]


_CANONICAL_FACT_RELATIONS = {
    "escape flows through the existing pause interface": "PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW",
    "movement behavior remains intact": "PRESERVE_BEHAVIOR:MOVEMENT_INPUT",
    "statusview reflects pausecontroller running and paused state": "CURRENT_RENDER_SURFACE",
    "pausecontroller remains the sole pause-state owner": "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER",
}


def _fact_structured_relations(item: Any) -> list[str]:
    """Recover only exact known fact identities from current Brain records."""
    value = item if isinstance(item, dict) else {}
    result = _structured_relation_names(value)
    normalized = " ".join(_fact_text(value).casefold().rstrip(".").split())
    relation = _CANONICAL_FACT_RELATIONS.get(normalized)
    if relation and relation not in result:
        result.append(relation)
    if relation == "CURRENT_RENDER_SURFACE" and "USER_FACING_PAUSE_INDICATOR" not in result:
        result.append("USER_FACING_PAUSE_INDICATOR")
    return result[:8]


def _entry(
    text: Any,
    provenance: str,
    *,
    requirement_ids: Iterable[Any] = (),
    evidence_ids: Iterable[Any] = (),
    **extra: Any,
) -> dict:
    result = {
        "text": _compact(text, 520),
        "provenance": provenance,
        "requirement_ids": _unique_strings(requirement_ids, 12, 100),
        "evidence_ids": _unique_strings(evidence_ids, 12, 100),
    }
    result.update({key: _safe(value) for key, value in extra.items() if value not in (None, "", [], {})})
    return result


def _requirement_projection(items: Any) -> list[dict]:
    result = []
    for item in _list(items)[:MAX_REQUIREMENTS]:
        if not isinstance(item, dict):
            continue
        requirement_id = _compact(item.get("requirement_id") or item.get("id"), 120)
        text = _compact(item.get("text") or item.get("requirement") or item.get("goal"), 900)
        if not requirement_id or not text:
            continue
        value = {
            "requirement_id": requirement_id,
            "text": text,
            "provenance": item.get("provenance", "USER_STATED"),
            "authority": item.get("authority", "USER/REQUIREMENT"),
            "status": "active",
        }
        for key in (
            "category", "authority_change", "authority_change_authorized",
            "allows_authority_change", "change_authority", "explicit_authority_change",
            "structured_relation", "authority_relation", "relation",
        ):
            if key in item:
                value[key] = _safe(item[key])
        result.append(value)
    return result


def _record_projection(item: Any, *, provenance: str = "PROJECT_BRAIN") -> dict:
    value = item if isinstance(item, dict) else {}
    fact = _fact_dict(value)
    result = {
        "record_id": _compact(value.get("record_id") or value.get("fact_hash"), 180),
        "fact_hash": _compact(value.get("fact_hash"), 100),
        "text": _fact_text(value),
        "classification": value.get("classification"),
        "durability_class": value.get("durability_class"),
        "provenance": provenance,
    }
    for key in (
        "category", "field", "kind", "authority", "path", "symbol", "requirement_id",
        "result", "subject_state_hash", "dependency_paths", "evidence_refs",
        "authority_relation", "structured_relation", "owner", "owner_entity",
    ):
        if key in value:
            result[key] = _safe(value[key])
        elif key in fact:
            result[key] = _safe(fact[key])
    relations = _fact_structured_relations(value)
    if relations:
        result["structured_relations"] = relations
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def _repository_projection(item: Any) -> dict:
    value = item if isinstance(item, dict) else {}
    result = {
        "evidence_id": _compact(value.get("evidence_id"), 100),
        "category": _compact(value.get("category"), 100),
        "path": _compact(value.get("path"), 220),
        "symbol": _compact(value.get("symbol"), 180) or None,
        "fact": _compact(value.get("fact"), 360),
        "source_kind": value.get("source_kind"),
        "evidence_type": value.get("evidence_type"),
        "provenance": value.get("provenance", REPOSITORY_EVIDENCE),
        "line_start": value.get("line_start"),
        "line_end": value.get("line_end"),
        "file_sha256": _compact(value.get("file_sha256"), 100),
        "support": _compact(value.get("support"), 220),
    }
    for key in (
        "structured_relation", "structured_relations", "repository_relation",
        "source_links", "linked_from_paths", "link_depth", "owner", "owner_entity",
    ):
        if key in value:
            result[key] = _safe(value[key])
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def _conflict_projection(item: Any) -> dict:
    value = item if isinstance(item, dict) else {}
    result = {
        "conflict_id": _compact(value.get("conflict_id"), 180),
        "kind": _compact(value.get("kind"), 120),
        "provenance": "REENTRY",
    }
    for key in (
        "authority_record_id", "authority_record_ids", "authority_fact_hash",
        "authority_relation", "repository_evidence_id", "repository_evidence_ids",
        "repository_relation", "drift_classification", "drift_conflict_key",
        "requirement_id", "current_record_id", "current_fact_hash", "resolution",
    ):
        if key in value:
            result[key] = _safe(value[key])
    text = value.get("authority_fact") or value.get("repository_fact") or value.get("reason")
    if text:
        result["text"] = _compact(text, 520)
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def _stable_conflict_key(item: dict) -> str:
    """Derive one identity for one authority/repository contradiction."""
    value = item if isinstance(item, dict) else {}
    explicit = value.get("drift_conflict_key")
    if explicit:
        return _compact(explicit, 220)
    return canonical_hash({
        "kind": value.get("kind"),
        "authority_record_id": value.get("authority_record_id"),
        "authority_fact_hash": value.get("authority_fact_hash"),
        "authority_relation": value.get("authority_relation"),
        "repository_evidence_ids": sorted(str(item) for item in value.get("repository_evidence_ids", []) or []),
        "repository_relation": value.get("repository_relation"),
    })[:32]


def _stale_projection(item: Any) -> dict:
    value = item if isinstance(item, dict) else {}
    result = {
        "record_id": _compact(value.get("record_id") or value.get("fact_hash"), 180),
        "fact_hash": _compact(value.get("fact_hash"), 100),
        "classification": STALE_VERIFIED,
        "fact_summary": _compact(value.get("fact_summary") or value.get("text"), 520),
        "stale_reason": _compact(value.get("stale_reason") or value.get("reason"), 420),
        "changed_dependency_paths": _unique_strings(value.get("changed_dependency_paths", []), 16, 220),
        "dependency_paths": _unique_strings(value.get("dependency_paths", []), 16, 220),
        "provenance": "PROJECT_BRAIN",
    }
    return {key: item for key, item in result.items() if item not in (None, "", [], {})}


def _authority_change_flag(item: dict) -> bool:
    for key in (
        "authority_change_authorized", "allows_authority_change",
        "change_authority", "explicit_authority_change",
    ):
        if item.get(key) is True:
            return True
    change = item.get("authority_change")
    if isinstance(change, dict):
        if any(change.get(key) is True for key in ("authorized", "explicit", "requested")):
            return True
        if change.get("from") and change.get("to") and change.get("type") in {
            "AUTHORITY_CHANGE", "OWNERSHIP_CHANGE", "STATE_OWNERSHIP_CHANGE",
        }:
            return True
    return False


def _authority_change_authorized(requirements: Iterable[dict]) -> bool:
    return any(_authority_change_flag(item) for item in requirements if isinstance(item, dict))


def _is_mandatory_authority_item(item: dict) -> bool:
    """Identify authority/prohibition constraints, not every durable fact."""
    value = item if isinstance(item, dict) else {}
    category = str(value.get("category") or "").casefold()
    field = str(value.get("field") or "").casefold()
    text = str(value.get("text") or _fact_text(value) or "")
    if category in {
        "verified_prohibitions", "verified_state_ownership", "state_ownership",
        "authority", "current_authority", "ownership",
    }:
        return True
    if field in {
        "owner", "current_owner", "state_ownership", "current_state_ownership",
        "do_not_touch", "global_do_not_touch", "prohibition_constraints",
    }:
        return True
    return bool(re.search(
        r"\b(?:sole|only|owner|ownership|do not|must not|never)\b",
        text, re.IGNORECASE,
    ))


def _authority_relations(values: Iterable[Any]) -> list[dict]:
    """Read only explicit structured relations; never parse arbitrary prose."""
    result = []
    for raw in values or []:
        item = raw if isinstance(raw, dict) else {}
        candidates = [
            item.get("structured_relation"), item.get("authority_relation"),
            item.get("repository_relation"), item.get("relation"), item,
        ]
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            subject = candidate.get("subject") or candidate.get("domain")
            predicate = candidate.get("predicate") or candidate.get("relationship")
            obj = candidate.get("object") or candidate.get("owner") or candidate.get("owner_entity")
            if subject and predicate and obj:
                relation = {
                    "subject": _compact(subject, 120),
                    "predicate": _compact(predicate, 120),
                    "object": _compact(obj, 160),
                }
                if relation not in result:
                    result.append(relation)
                break
    return result[:MAX_AUTHORITY]


def _text_tokens(value: Any) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-z0-9_]{3,}", str(value or ""))
        if token.casefold() not in {"the", "and", "for", "with", "current", "must", "should"}
    }


def _dedupe_by_identity(values: Iterable[dict], keys: tuple[str, ...]) -> list[dict]:
    result = []
    seen = set()
    for value in values or []:
        if not isinstance(value, dict):
            continue
        identity = tuple(
            json.dumps(value.get(key), ensure_ascii=False, sort_keys=True, default=str)
            if isinstance(value.get(key), (list, dict, tuple))
            else str(value.get(key) or "")
            for key in keys
        )
        if not any(identity) or identity in seen:
            continue
        seen.add(identity)
        result.append(value)
    return result


def _make_requirements_ledger(requirements: list[dict]) -> dict:
    """Preserve the FreshTaskBrain IDs without invoking Stage 1 extraction."""
    return {
        "version": 1,
        "immutable": True,
        "requirements": copy.deepcopy(requirements[:MAX_REQUIREMENTS]),
        "confirmed_requirements": [],
        "limits": {"max_requirements": MAX_REQUIREMENTS},
        "provenance": "VERIFIED_STATE_REENTRY",
    }


def _empty_model_accounting() -> dict[str, int]:
    return {
        "planning_context_compiler": 0,
        "planning_readiness": 0,
        "verified_reentry_planning": 0,
        "gemma_total": 0,
    }


def _invalid_context(errors: Iterable[Any], *, project_id: Any = None, task_id: Any = None) -> dict:
    return {
        "status": PLANNING_CONTEXT_INVALID,
        "valid": False,
        "project_id": _compact(project_id, 180),
        "task_id": _compact(task_id, 180),
        "errors": _unique_strings(errors, 20, 420),
        "model_calls": 0,
        "model_call_accounting": _empty_model_accounting(),
    }


def _fresh_source(value: Any) -> tuple[dict, dict | None]:
    if not isinstance(value, dict):
        return {}, None
    if value.get("artifact_type") == FRESH_TASK_BRAIN_TYPE:
        return value, None
    nested = value.get("task_brain")
    context = value.get("reentry_context")
    if isinstance(nested, dict):
        return nested, context if isinstance(context, dict) else None
    return value, context if isinstance(context, dict) else None


def _source_validity(fresh: dict, reentry_context: dict | None, expected_project_id: str | None) -> list[str]:
    errors = []
    checked = validate_fresh_task_brain(fresh)
    errors.extend(checked.get("errors", []))
    project_id = str(fresh.get("project_id") or "")
    task_id = str(fresh.get("task_id") or "")
    if expected_project_id is not None and project_id != str(expected_project_id):
        errors.append("FreshTaskBrain project does not match the requested project")
    if not str(fresh.get("reentry_hash") or "").strip():
        errors.append("FreshTaskBrain re-entry provenance is missing")
    provenance = fresh.get("provenance") if isinstance(fresh.get("provenance"), dict) else {}
    if provenance.get("old_task_brain_reused") is not False:
        errors.append("FreshTaskBrain does not prove that the old Task Brain was excluded")
    if provenance.get("private_execution_material_loaded") is not False:
        errors.append("FreshTaskBrain does not prove private execution material was excluded")
    if provenance.get("automatic_reverification") is not False:
        errors.append("FreshTaskBrain does not prove automatic re-verification was disabled")
    if _contains_private(fresh):
        errors.append("FreshTaskBrain contains forbidden history or private execution material")
    if reentry_context is not None:
        checked_context = validate_reentry_context(reentry_context)
        errors.extend(checked_context.get("errors", []))
        if reentry_context.get("project_id") != project_id:
            errors.append("ReentryContext project does not match FreshTaskBrain")
        if reentry_context.get("new_task_id") != task_id:
            errors.append("ReentryContext task does not match FreshTaskBrain")
        if reentry_context.get("reentry_hash") != fresh.get("reentry_hash"):
            errors.append("FreshTaskBrain is not bound to the supplied ReentryContext")
    return list(dict.fromkeys(str(item) for item in errors if str(item).strip()))[:24]


def compile_verified_planning_context(
    fresh_task_brain: dict,
    reentry_context: dict | None = None,
    *,
    expected_project_id: str | None = None,
    current_repository_evidence: Iterable[dict] | None = None,
) -> dict:
    """Compile one bounded immutable planning projection with zero model calls."""
    fresh, nested_context = _fresh_source(fresh_task_brain)
    if reentry_context is None:
        reentry_context = nested_context
    errors = _source_validity(fresh, reentry_context, expected_project_id)
    if errors:
        return _invalid_context(errors, project_id=fresh.get("project_id"), task_id=fresh.get("task_id"))

    requirements = _requirement_projection(fresh.get("new_requirements", []))
    if not requirements:
        return _invalid_context(
            ["FreshTaskBrain contains no current user requirement"],
            project_id=fresh.get("project_id"), task_id=fresh.get("task_id"),
        )
    reentry_repository_evidence = (
        reentry_context.get("current_repository_evidence", [])
        if isinstance(reentry_context, dict) else []
    )
    repo_source = list(
        current_repository_evidence
        if current_repository_evidence is not None
        else (
            fresh.get("current_repository_evidence", [])
            or reentry_repository_evidence
            or []
        )
    )
    repo = [_repository_projection(item) for item in repo_source if isinstance(item, dict)]
    repo = [item for item in repo if item.get("evidence_id") and item.get("fact")]
    current_facts = [
        _record_projection(item, provenance="PROJECT_BRAIN")
        for item in list(fresh.get("current_verified_facts", []) or [])[:MAX_FACTS]
        if isinstance(item, dict)
        and item.get("classification") in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY}
    ]
    stale = [
        _stale_projection(item)
        for item in list(fresh.get("stale_verified_facts", []) or [])[:MAX_STALE_WARNINGS]
        if isinstance(item, dict)
    ]
    drift_audit = [
        _safe(item) for item in list(fresh.get("authority_drift_audit", []) or [])[:MAX_AUDIT_ITEMS]
        if isinstance(item, dict)
    ]
    not_evaluable = [
        item for item in drift_audit if item.get("classification") == NOT_EVALUABLE
    ]

    audit_by_identity = {
        (
            str(item.get("authority_record_id") or ""),
            tuple(sorted(str(ref) for ref in item.get("evidence_refs", []) or [])),
        ): item
        for item in drift_audit
    }
    confirmed_conflicts = []
    for raw in list(fresh.get("conflicts", []) or [])[:MAX_CONFLICTS * 2]:
        if not isinstance(raw, dict):
            continue
        kind = raw.get("kind")
        if kind == AUTHORITY_IMPLEMENTATION_DRIFT:
            authority_id = str(raw.get("authority_record_id") or "")
            evidence_refs = tuple(sorted(str(ref) for ref in raw.get("repository_evidence_ids", []) or []))
            matching = [
                item for (record_id, refs), item in audit_by_identity.items()
                if record_id == authority_id and (
                    not evidence_refs or set(evidence_refs).issubset(set(refs))
                )
            ]
            if not matching:
                matching = [
                    item for item in drift_audit
                    if item.get("classification") == CONFIRMED_DRIFT
                    and item.get("authority_record_id") == authority_id
                ]
            if not any(item.get("classification") == CONFIRMED_DRIFT for item in matching):
                continue
        if kind in {STALE_VERIFIED, "STALE_VERIFIED_EVIDENCE"}:
            continue
        if raw.get("drift_classification") == NOT_EVALUABLE:
            continue
        projected = _conflict_projection(raw)
        if kind == AUTHORITY_IMPLEMENTATION_DRIFT:
            projected["drift_conflict_key"] = _stable_conflict_key(raw)
        confirmed_conflicts.append(projected)
    deduplicated_conflicts = []
    seen_conflicts = set()
    duplicate_conflicts_suppressed = 0
    for item in confirmed_conflicts:
        identity = (
            item.get("kind"),
            item.get("drift_conflict_key") or item.get("conflict_id")
            or canonical_hash(item),
            item.get("requirement_id"),
        )
        if identity in seen_conflicts:
            duplicate_conflicts_suppressed += 1
            continue
        seen_conflicts.add(identity)
        deduplicated_conflicts.append(item)
    confirmed_conflicts = deduplicated_conflicts[:MAX_CONFLICTS]

    current_fact_by_id = {
        str(item.get("record_id")): item
        for item in current_facts
        if isinstance(item, dict) and item.get("record_id")
    }
    durable_authority = []
    for item in list(fresh.get("current_durable_authority", []) or [])[:MAX_AUTHORITY]:
        if not isinstance(item, dict):
            continue
        projected = _record_projection(item, provenance="PROJECT_BRAIN")
        # Older bounded FreshTaskBrain projections can retain the durable
        # record identity while dropping its descriptive fields. Recover the
        # already-current descriptive projection from the same fresh brain;
        # never invent authority or consult repository prose here.
        if not projected.get("text"):
            matching = current_fact_by_id.get(str(projected.get("record_id") or ""))
            if isinstance(matching, dict):
                recovered = copy.deepcopy(matching)
                recovered.update(projected)
                projected = recovered
        durable_authority.append(projected)
    desired_authority = [
        _entry(
            item.get("text"), item.get("provenance", "USER_STATED"),
            requirement_ids=[item.get("requirement_id")],
            authority=item.get("authority", "USER/REQUIREMENT"),
            authority_scope="NEW_REQUIREMENT",
            structured_relation=item.get("structured_relation") or item.get("authority_relation") or item.get("relation"),
        )
        for item in requirements
    ]
    current_authority = _dedupe_by_identity(
        [*desired_authority, *durable_authority], ("text", "record_id", "requirement_ids"),
    )[:MAX_AUTHORITY]

    prohibition_sources = []
    for item in [*requirements, *current_facts, *durable_authority]:
        text = item.get("text") or _fact_text(item)
        if _PROHIBITION_RE.search(str(text or "")):
            prohibition_sources.append(_entry(
                text, item.get("provenance", "PROJECT_BRAIN"),
                requirement_ids=item.get("requirement_ids", []),
                evidence_ids=item.get("evidence_ids", []),
                category=item.get("category"), path=item.get("path"),
                symbol=item.get("symbol"), field=item.get("field"),
            ))
    prohibitions = _dedupe_by_identity(prohibition_sources, ("text", "requirement_ids"))[:MAX_PROHIBITIONS]

    interfaces = []
    for item in repo:
        if str(item.get("category") or "").upper() == "CURRENT_INTERFACE":
            interfaces.append(_entry(
                item.get("fact"), REPOSITORY_EVIDENCE,
                evidence_ids=[item.get("evidence_id")], path=item.get("path"),
                symbol=item.get("symbol"), category=item.get("category"),
                structured_relation=item.get("structured_relation"),
                structured_relations=item.get("structured_relations"),
            ))
    for item in current_facts:
        if str(item.get("category") or "").casefold() in {"verified_interfaces", "interfaces", "interface"}:
            interfaces.append(_entry(
                item.get("text"), "PROJECT_BRAIN",
                evidence_ids=item.get("evidence_refs", []), path=item.get("path"),
                symbol=item.get("symbol"), category=item.get("category"),
            ))
    interfaces = _dedupe_by_identity(interfaces, ("text", "evidence_ids"))[:MAX_INTERFACES]

    source_project_brain_hash = (
        reentry_context.get("project_brain_hash") if isinstance(reentry_context, dict) else None
    )
    source_repository_fingerprint = (
        (reentry_context or {}).get("repository_dependency_fingerprint", {}).get("fingerprint")
        if isinstance(reentry_context, dict) else None
    )
    if not source_repository_fingerprint:
        source_repository_fingerprint = (fresh.get("repository_observation") or {}).get("inventory_fingerprint")
    context_repository_evidence = repo[:MAX_REPOSITORY_EVIDENCE]
    context = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": VERIFIED_PLANNING_CONTEXT_TYPE,
        "status": "COMPILED",
        "valid": True,
        "project_id": fresh.get("project_id"),
        "task_id": fresh.get("task_id"),
        "planning_mode": VERIFIED_STATE_REENTRY,
        "task_goal": _compact(
            (fresh.get("task_goal") or {}).get("text")
            if isinstance(fresh.get("task_goal"), dict)
            else fresh.get("task_goal"),
            900,
        ),
        "new_requirements": requirements,
        "current_authority": current_authority,
        "current_verified_facts": current_facts,
        "current_repository_evidence": context_repository_evidence,
        "stale_evidence_warnings": stale,
        "stale_warnings": copy.deepcopy(stale),
        "confirmed_conflicts": confirmed_conflicts,
        "duplicate_conflicts_suppressed": duplicate_conflicts_suppressed,
        "authority_drift_audit": copy.deepcopy(drift_audit[:MAX_AUDIT_ITEMS]),
        "not_evaluable_audit": not_evaluable[:MAX_AUDIT_ITEMS],
        "prohibitions": prohibitions,
        "dnt": copy.deepcopy(prohibitions),
        "interfaces": interfaces,
        "source_reentry_hash": fresh.get("reentry_hash"),
        "source_task_brain_hash": fresh.get("task_brain_hash"),
        "source_project_brain_hash": source_project_brain_hash,
        "source_promotion_hashes": _unique_strings(fresh.get("source_promotion_hashes", []), 48, 100),
        "source_repository_evidence_hash": canonical_hash(context_repository_evidence),
        "source_repository_fingerprint": source_repository_fingerprint,
        "source_provenance": {
            "source": "deterministic_verified_state_reentry",
            "project_brain_read_only": True,
            "old_task_brain_excluded": True,
            "raw_history_excluded": True,
            "automatic_reverification": False,
            "execution_started": False,
            "model_calls": 0,
            "duplicate_conflicts_suppressed": duplicate_conflicts_suppressed,
        },
        "source_priority": [
            "NEW_REQUIREMENT", "CURRENT_AUTHORITY", "CURRENT_VERIFIED",
            "CURRENT_REPOSITORY_EVIDENCE", "CONFIRMED_DRIFT", "STALE_WARNING",
            "OPAQUE_PROVENANCE",
        ],
        "bounds": {
            "max_serialized_chars": MAX_CONTEXT_CHARS,
            "max_rendered_chars": MAX_RENDERED_CONTEXT_CHARS,
            "max_requirements": MAX_REQUIREMENTS,
            "max_authority": MAX_AUTHORITY,
            "max_current_facts": MAX_FACTS,
            "max_repository_evidence": MAX_REPOSITORY_EVIDENCE,
            "max_stale_warnings": MAX_STALE_WARNINGS,
            "max_conflicts": MAX_CONFLICTS,
            "mandatory_authority_drops": 0,
            "dropped_optional_items": [],
        },
        "model_calls": 0,
        "model_call_accounting": _empty_model_accounting(),
    }
    if _contains_private(context):
        return _invalid_context(
            ["compiled planning context contains forbidden history"],
            project_id=fresh.get("project_id"), task_id=fresh.get("task_id"),
        )
    if _json_size(context) > MAX_CONTEXT_CHARS:
        # Only optional direct repository evidence can be trimmed here.  The
        # current requirement, authority, facts, warnings, and conflicts are
        # never silently dropped.
        while _json_size(context) > MAX_CONTEXT_CHARS and context["current_repository_evidence"]:
            context["current_repository_evidence"].pop()
            context["bounds"]["dropped_optional_items"].append("current_repository_evidence")
        if _json_size(context) > MAX_CONTEXT_CHARS:
            return _invalid_context(
                ["mandatory verified planning authority exceeds the deterministic bound"],
                project_id=fresh.get("project_id"), task_id=fresh.get("task_id"),
            )
    context["source_repository_evidence_hash"] = canonical_hash(
        context["current_repository_evidence"]
    )
    context["planning_context_hash"] = planning_context_hash(context)
    context["context_hash"] = context["planning_context_hash"]
    checked = validate_verified_planning_context(context)
    if not checked.get("valid"):
        return _invalid_context(
            checked.get("errors", []), project_id=fresh.get("project_id"), task_id=fresh.get("task_id"),
        )
    return context


build_verified_planning_context = compile_verified_planning_context
compile_planning_context = compile_verified_planning_context


def planning_context_hash(context: dict | None) -> str:
    value = context if isinstance(context, dict) else {}
    material = _without(value, "planning_context_hash")
    material.pop("context_hash", None)
    return canonical_hash(material)


def validate_verified_planning_context(
    context: dict | None,
    *,
    fresh_task_brain: dict | None = None,
    reentry_context: dict | None = None,
    current_repository_evidence: Iterable[dict] | None = None,
    expected_project_id: str | None = None,
) -> dict:
    value = context if isinstance(context, dict) else {}
    errors = []
    if value.get("artifact_type") != VERIFIED_PLANNING_CONTEXT_TYPE:
        errors.append("wrong VerifiedPlanningContext artifact type")
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("wrong VerifiedPlanningContext schema version")
    if not str(value.get("project_id") or "").strip() or not str(value.get("task_id") or "").strip():
        errors.append("project_id and task_id are required")
    if value.get("planning_mode") != VERIFIED_STATE_REENTRY:
        errors.append("verified planning mode is required")
    if value.get("valid") is not True:
        errors.append("VerifiedPlanningContext is not marked valid")
    if not str(value.get("task_goal") or "").strip():
        errors.append("planning task goal is required")
    if value.get("planning_context_hash") != planning_context_hash(value):
        errors.append("planning context hash does not match canonical contents")
    for field in (
        "new_requirements", "current_authority", "current_verified_facts",
        "current_repository_evidence", "stale_evidence_warnings", "confirmed_conflicts",
        "stale_warnings", "not_evaluable_audit", "prohibitions", "dnt", "interfaces",
        "authority_drift_audit", "source_promotion_hashes",
    ):
        if not isinstance(value.get(field), list):
            errors.append(f"{field} must be a list")
    if not value.get("new_requirements"):
        errors.append("new requirements are missing")
    for key in ("source_reentry_hash", "source_task_brain_hash"):
        if not str(value.get(key) or "").strip():
            errors.append(f"{key} is required")
    if int(value.get("model_calls", 0) or 0) != 0:
        errors.append("planning context contains model calls")
    accounting = value.get("model_call_accounting")
    if not isinstance(accounting, dict) or any(int(item or 0) != 0 for item in accounting.values()):
        errors.append("planning context model-call accounting is not zero")
    provenance = value.get("source_provenance") if isinstance(value.get("source_provenance"), dict) else {}
    for key, expected in (
        ("project_brain_read_only", True), ("old_task_brain_excluded", True),
        ("raw_history_excluded", True), ("automatic_reverification", False),
        ("execution_started", False), ("model_calls", 0),
    ):
        if provenance.get(key) != expected:
            errors.append(f"planning provenance {key} is invalid")
    for fact in value.get("current_verified_facts", []) or []:
        if not isinstance(fact, dict) or fact.get("classification") not in {CURRENT_VERIFIED, CURRENT_DURABLE_AUTHORITY}:
            errors.append("stale or superseded fact entered current verified state")
            break
    for warning in value.get("stale_evidence_warnings", []) or []:
        if not isinstance(warning, dict) or warning.get("classification") != STALE_VERIFIED:
            errors.append("stale warning classification is invalid")
            break
    for audit in value.get("authority_drift_audit", []) or []:
        if not isinstance(audit, dict) or audit.get("classification") not in {
            CONFIRMED_CONSISTENT, CONFIRMED_DRIFT, NOT_EVALUABLE, NOT_RELEVANT,
        }:
            errors.append("authority drift audit classification is invalid")
            break
    if value.get("dnt") != value.get("prohibitions"):
        errors.append("DNT and prohibition projection diverged")
    if value.get("stale_warnings") != value.get("stale_evidence_warnings"):
        errors.append("stale warning projections diverged")
    if value.get("context_hash") != value.get("planning_context_hash"):
        errors.append("context hash alias does not match planning context hash")
    if _contains_private(value):
        errors.append("planning context contains forbidden history or private material")
    if _json_size(value) > int((value.get("bounds") or {}).get("max_serialized_chars", MAX_CONTEXT_CHARS)):
        errors.append("planning context serialized-size bound exceeded")
    if expected_project_id is not None and str(value.get("project_id")) != str(expected_project_id):
        errors.append("planning context project mismatch")
    if fresh_task_brain is not None:
        fresh, nested = _fresh_source(fresh_task_brain)
        fresh_check = validate_fresh_task_brain(fresh)
        errors.extend(fresh_check.get("errors", []))
        if fresh.get("task_brain_hash") != value.get("source_task_brain_hash"):
            errors.append("planning context source Task Brain hash mismatch")
        if fresh.get("reentry_hash") != value.get("source_reentry_hash"):
            errors.append("planning context source ReentryContext hash mismatch")
        del nested
    if reentry_context is not None:
        checked_context = validate_reentry_context(reentry_context)
        errors.extend(checked_context.get("errors", []))
        if reentry_context.get("reentry_hash") != value.get("source_reentry_hash"):
            errors.append("planning context source re-entry hash mismatch")
    if current_repository_evidence is not None:
        current_hash = canonical_hash([
            _repository_projection(item) for item in current_repository_evidence
            if isinstance(item, dict)
        ][:MAX_REPOSITORY_EVIDENCE])
        if current_hash != value.get("source_repository_evidence_hash"):
            errors.append(PLANNING_CONTEXT_STALE)
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(str(item) for item in errors))[:24],
        "serialized_chars": _json_size(value),
        "model_calls": 0,
    }


def assess_planning_context_readiness(
    context: dict | None,
    *,
    required_current_evidence_ids: Iterable[Any] | None = None,
    current_repository_evidence: Iterable[dict] | None = None,
) -> dict:
    """Return a zero-model readiness decision without triggering re-verification."""
    checked = validate_verified_planning_context(
        context, current_repository_evidence=current_repository_evidence,
    )
    if not checked.get("valid"):
        return {
            "status": PLANNING_CONTEXT_STALE if PLANNING_CONTEXT_STALE in checked.get("errors", []) else PLANNING_CONTEXT_INVALID,
            "ready": False,
            "reason": checked.get("errors", [PLANNING_CONTEXT_INVALID])[0],
            "errors": checked.get("errors", []),
            "model_calls": 0,
        }
    value = context
    requirements = value.get("new_requirements", [])
    current_facts = value.get("current_verified_facts", [])
    repo = value.get("current_repository_evidence", [])
    if not requirements:
        return {
            "status": PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE,
            "ready": False,
            "reason": "no current user requirement is available",
            "model_calls": 0,
        }
    required = {str(item) for item in (required_current_evidence_ids or []) if str(item).strip()}
    available = {
        str(item.get("evidence_id")) for item in repo if isinstance(item, dict)
    }
    available.update(
        str(item.get("record_id")) for item in current_facts if isinstance(item, dict)
    )
    missing = sorted(required - available)
    if missing:
        return {
            "status": PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE,
            "ready": False,
            "reason": "critical current planning evidence is unavailable",
            "missing_current_evidence_ids": missing[:16],
            "model_calls": 0,
        }
    # Existing-project Stage 3 planning cannot safely derive canonical
    # surfaces from Project Brain prose alone. Require at least one bounded
    # current repository observation; absence is an explicit readiness
    # failure, never an invitation to rediscover or reverify automatically.
    if not repo:
        return {
            "status": PLANNING_CONTEXT_INSUFFICIENT_CURRENT_EVIDENCE,
            "ready": False,
            "reason": "current repository evidence is unavailable for existing-project planning",
            "model_calls": 0,
        }
    return {
        "status": PLANNING_CONTEXT_READY,
        "ready": True,
        "reason": "bounded current evidence is available for planning",
        "current_verified_count": len(current_facts),
        "current_repository_evidence_count": len(repo),
        "stale_warning_count": len(value.get("stale_evidence_warnings", []) or []),
        "confirmed_conflict_count": len(value.get("confirmed_conflicts", []) or []),
        "model_calls": 0,
    }


planning_context_readiness = assess_planning_context_readiness
assess_verified_planning_readiness = assess_planning_context_readiness


def build_stage3_task_brain(context: dict) -> dict:
    """Build the narrow Stage 3 adapter; no old Task Brain is hydrated."""
    value = context if isinstance(context, dict) else {}
    requirements = value.get("new_requirements", []) or []
    repo = value.get("current_repository_evidence", []) or []

    def repo_entry(item: dict) -> dict:
        return _entry(
            item.get("fact"), REPOSITORY_EVIDENCE,
            requirement_ids=[], evidence_ids=[item.get("evidence_id")],
            path=item.get("path"), symbol=item.get("symbol"), category=item.get("category"),
            line_start=item.get("line_start"), line_end=item.get("line_end"),
            file_sha256=item.get("file_sha256"), support=item.get("support"),
            structured_relation=item.get("structured_relation"),
            structured_relations=item.get("structured_relations"),
            source_links=item.get("source_links"),
            linked_from_paths=item.get("linked_from_paths"),
            link_depth=item.get("link_depth"),
        )

    repository_entries = [repo_entry(item) for item in repo if isinstance(item, dict)]
    owner_entries = [
        item for item in repository_entries
        if str(item.get("category") or "").upper() in {"CURRENT_OWNER", "CURRENT_STATE_OWNER", "CURRENT_BEHAVIOR"}
    ]
    state_entries = [
        item for item in repository_entries
        if str(item.get("category") or "").upper() == "CURRENT_STATE_OWNER"
    ]
    interface_entries = [
        item for item in repository_entries
        if str(item.get("category") or "").upper() == "CURRENT_INTERFACE"
    ]
    test_entries = [
        item for item in repository_entries
        if str(item.get("category") or "").upper() == "CURRENT_TEST"
    ]
    dependency_entries = [
        item for item in repository_entries
        if str(item.get("category") or "").upper() == "CURRENT_DEPENDENCY"
    ]
    current_facts = value.get("current_verified_facts", []) or []
    project_facts = []
    for item in current_facts:
        if isinstance(item, dict) and _fact_text(item):
            project_facts.append(_entry(
                _fact_text(item), "PROJECT_BRAIN",
                requirement_ids=item.get("requirement_ids", []),
                evidence_ids=item.get("evidence_refs", []),
                path=item.get("path"), symbol=item.get("symbol"),
                category=item.get("category"),
                structured_relations=item.get("structured_relations"),
            ))
    durable = value.get("current_authority", []) or []
    dnt = value.get("dnt", []) or []
    preservation = [
        _entry(
            item.get("text"), item.get("provenance", "PROJECT_BRAIN"),
            requirement_ids=item.get("requirement_ids", []), evidence_ids=item.get("evidence_ids", []),
            path=item.get("path"), symbol=item.get("symbol"),
            category=item.get("category"), field=item.get("field"),
        )
        for item in dnt if isinstance(item, dict) and item.get("text")
    ]
    confirmed_conflicts = [
        _entry(
            f"{item.get('kind')}: {item.get('text') or item.get('resolution') or 'confirmed conflict'}",
            "CONFIRMED_DRIFT" if item.get("kind") == AUTHORITY_IMPLEMENTATION_DRIFT else "REENTRY",
            evidence_ids=item.get("repository_evidence_ids", []),
            conflict_id=item.get("conflict_id"), kind=item.get("kind"),
        )
        for item in value.get("confirmed_conflicts", []) or []
        if isinstance(item, dict)
    ]
    stale_warnings = [
        _entry(
            f"STALE_WARNING: {item.get('fact_summary') or item.get('stale_reason')}",
            "STALE_WARNING", evidence_ids=[item.get("record_id")],
            record_id=item.get("record_id"), classification=STALE_VERIFIED,
            changed_dependency_paths=item.get("changed_dependency_paths", []),
        )
        for item in value.get("stale_evidence_warnings", []) or []
        if isinstance(item, dict)
    ]
    requirement_ledger = _make_requirements_ledger(requirements)
    return {
        "version": 1,
        "task_id": value.get("task_id"),
        "task_goal": {
            "text": _compact(value.get("task_goal") or requirements[0].get("text") or value.get("task_id"), 900),
            "provenance": "USER_STATED",
            "requirement_ids": [item.get("requirement_id") for item in requirements],
        },
        "project_mode": "EXISTING_PROJECT",
        "source_requirement_ids": [item.get("requirement_id") for item in requirements],
        "user_confirmed_decisions": [],
        "relevant_project_brain_projection": project_facts[:32],
        "repository_evidence_ids": [item.get("evidence_id") for item in repo if isinstance(item, dict)],
        "current_owners": owner_entries[:16],
        "current_state_ownership": state_entries[:16],
        "current_interfaces": interface_entries[:16],
        "relevant_dependencies": dependency_entries[:16],
        "relevant_tests": test_entries[:8],
        "preservation_constraints": preservation[:16],
        "derived_task_assumptions": [],
        "open_questions": [],
        "acceptance_conditions": [],
        "known_non_goals": [],
        "evidence_index": copy.deepcopy(repository_entries[:16]),
        "confirmed_conflicts": confirmed_conflicts[:MAX_CONFLICTS],
        "authority_drift_audit": copy.deepcopy((value.get("authority_drift_audit") or [])[:MAX_AUDIT_ITEMS]),
        "stale_evidence_warnings": stale_warnings[:MAX_STALE_WARNINGS],
        "verified_planning_context_hash": value.get("planning_context_hash"),
        "source_task_brain_hash": value.get("source_task_brain_hash"),
        "source_reentry_hash": value.get("source_reentry_hash"),
        "planning_mode": VERIFIED_STATE_REENTRY,
        "requirement_obligation_ledger": requirement_ledger,
        "prohibitions": [item.get("text") for item in preservation if item.get("text")],
        "dnt": [item.get("text") for item in preservation if item.get("text")],
    }


def build_planning_contract(context: dict) -> dict:
    """Create the existing Stage 3 contract envelope from current context."""
    value = context if isinstance(context, dict) else {}
    requirements = copy.deepcopy(value.get("new_requirements", []) or [])
    goal = _compact(
        value.get("task_goal") or next(
            (item.get("text") for item in requirements if isinstance(item, dict) and item.get("text")),
            "verified-state-aware existing-project task",
        ),
        1_200,
    )
    ledger = _make_requirements_ledger(requirements)
    source_contract = {
        "root_goal": goal,
        "source_requirement_ledger": copy.deepcopy(ledger),
        "user_stated_requirements": copy.deepcopy(requirements),
        "user_confirmed_requirements": [],
        "derived_assumptions": [],
        "clarification_questions": [],
        "clarification_answers": [],
        "interaction_style": "LOW_FRICTION",
    }
    return {
        "status": "ready",
        "goal": goal,
        "original_goal": goal,
        "requirements": [item.get("text") for item in requirements],
        "constraints": [item.get("text") for item in value.get("dnt", []) if isinstance(item, dict)]
        if value.get("dnt") and isinstance(value.get("dnt")[0], dict) else [
            item.get("text") for item in value.get("prohibitions", []) if isinstance(item, dict)
        ],
        "success_criteria": ["valid bounded plan reaches the user approval boundary"],
        "source_requirement_ledger": ledger,
        "source_contract": source_contract,
        "user_confirmed_requirements": [],
        "derived_assumptions": [],
        "project_id": value.get("project_id"),
        "planning_mode": VERIFIED_STATE_REENTRY,
        "verified_planning_context_hash": value.get("planning_context_hash"),
    }


def attach_plan_binding(plan: dict, context: dict) -> dict:
    """Attach only hashes/provenance to a Stage 3 plan before identity hashing."""
    result = copy.deepcopy(plan if isinstance(plan, dict) else {})
    value = context if isinstance(context, dict) else {}
    result["planning_mode"] = VERIFIED_STATE_REENTRY
    result["verified_planning_context"] = {
        "source_reentry_hash": value.get("source_reentry_hash"),
        "source_task_brain_hash": value.get("source_task_brain_hash"),
        "planning_context_hash": value.get("planning_context_hash"),
        "source_project_brain_hash": value.get("source_project_brain_hash"),
        "source_repository_evidence_hash": value.get("source_repository_evidence_hash"),
        "source_promotion_hashes": _unique_strings(value.get("source_promotion_hashes", []), 48, 100),
    }
    provenance = [
        {"source": "NEW_REQUIREMENT", "ids": [item.get("requirement_id") for item in value.get("new_requirements", [])]},
        {"source": "CURRENT_AUTHORITY", "ids": [item.get("record_id") for item in value.get("current_authority", []) if item.get("record_id")]},
        {"source": "CURRENT_VERIFIED", "ids": [item.get("record_id") for item in value.get("current_verified_facts", [])]},
        {"source": "CURRENT_REPOSITORY_EVIDENCE", "ids": [item.get("evidence_id") for item in value.get("current_repository_evidence", [])]},
        {"source": "CONFIRMED_DRIFT", "ids": [item.get("conflict_id") for item in value.get("confirmed_conflicts", [])]},
        {"source": "STALE_WARNING", "ids": [item.get("record_id") for item in value.get("stale_evidence_warnings", [])]},
    ]
    prohibition_paths = sorted({
        str(item.get("path")).replace("\\", "/")
        for item in value.get("prohibitions", []) or []
        if isinstance(item, dict) and item.get("path")
    })
    if prohibition_paths:
        # Paths are bounded locators, not semantic guesses. They make the
        # immutable DNT projection visible to the plan validator without
        # copying the full Task/Project Brain into the plan.
        provenance.append({"source": "PROHIBITION", "paths": prohibition_paths[:MAX_PROHIBITIONS]})
    result["planning_provenance"] = provenance
    return result


def _plan_text(plan: dict) -> str:
    return json.dumps(plan if isinstance(plan, dict) else {}, ensure_ascii=False, sort_keys=True, default=str)


def _plan_reference_ids(plan: dict) -> set[str]:
    found = set()
    def visit(value: Any, key: str = ""):
        if isinstance(value, dict):
            for name, item in value.items():
                visit(item, str(name))
        elif isinstance(value, list):
            for item in value:
                visit(item, key)
        elif isinstance(value, (str, int, float)) and key.casefold() in {
            "evidence_ids", "repository_evidence_ids", "current_verified_fact_ids",
            "verified_fact_ids", "stale_evidence_refs", "current_state_refs",
            "justification_refs", "record_id", "fact_hash", "conflict_ids",
            "confirmed_conflict_ids", "authority_record_ids",
        }:
            found.add(str(value))
    visit(plan)
    return found


def _plan_provenance_has(plan: dict, source: str) -> bool:
    encoded = _plan_text(plan)
    return source.casefold() in encoded.casefold()


def _plan_authority_change(plan: dict) -> bool:
    if not isinstance(plan, dict):
        return False
    for key in (
        "authority_change", "authority_change_obligation", "authority_transition",
        "owner_change", "ownership_change", "proposed_owner", "target_owner",
        "new_owner", "state_owner_change",
    ):
        if plan.get(key) not in (None, "", [], {}, False):
            return True
    for node in plan.get("approved_change_nodes", []) or plan.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        for key in (
            "authority_change", "authority_change_obligation", "authority_transition",
            "owner_change", "ownership_change", "proposed_owner", "target_owner",
            "new_owner", "state_owner_change",
        ):
            if node.get(key) not in (None, "", [], {}, False):
                return True
        text = " ".join(str(node.get(key, "")) for key in ("goal", "objective", "candidate_change", "action"))
        if _OWNER_ACTION_RE.search(text):
            return True
    return False


def _plan_explicit_transition(plan: dict) -> bool:
    encoded = _plan_text(plan).casefold()
    return any(token in encoded for token in (
        "authority_change", "authority transition", "ownership_change",
        "owner_change", "current_authority_transition",
    ))


def _owner_candidates(context: dict) -> tuple[set[str], list[dict]]:
    values = [
        *context.get("current_repository_evidence", []),
        *context.get("current_verified_facts", []),
        *context.get("current_authority", []),
    ]
    owners = set()
    relations = _authority_relations(values)
    for item in values:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category") or "").upper()
        if category not in {"CURRENT_STATE_OWNER", "CURRENT_OWNER", "VERIFIED_STATE_OWNERSHIP", "STATE_OWNERSHIP"}:
            continue
        for key in ("owner", "owner_entity", "symbol"):
            raw = item.get(key)
            if raw:
                owners.update(_OWNER_TOKEN_RE.findall(str(raw)))
                if re.fullmatch(r"[A-Za-z_$][\w$]*", str(raw)):
                    owners.add(str(raw))
    owners.update(relation["object"] for relation in relations)
    return {item.casefold() for item in owners if item}, relations


def _authorized_transition_target(requirements: Iterable[dict]) -> set[str]:
    targets = set()
    for item in requirements or []:
        if not isinstance(item, dict) or not _authority_change_flag(item):
            continue
        change = item.get("authority_change") if isinstance(item.get("authority_change"), dict) else item
        for key in ("to", "target_owner", "new_owner", "object"):
            if change.get(key):
                targets.add(str(change[key]).casefold())
    return targets


def _plan_owner_names(plan: dict) -> set[str]:
    result = set()
    values = [plan]
    values.extend(item for item in plan.get("approved_change_nodes", []) or [] if isinstance(item, dict))
    for item in values:
        # ``current_owner`` is descriptive evidence, not a proposed
        # authority transition. Treating it as a candidate would turn an
        # ordinary reuse plan into a false unauthorized migration.
        for key in ("proposed_owner", "target_owner", "new_owner", "owner"):
            raw = item.get(key)
            if raw:
                result.update(str(raw).casefold() for raw in _OWNER_TOKEN_RE.findall(str(raw)))
                if re.fullmatch(r"[A-Za-z_$][\w$]*", str(raw)):
                    result.add(str(raw).casefold())
    return result


def validate_verified_plan(
    plan: dict | None,
    context: dict | None,
    *,
    requirements: Iterable[dict] | None = None,
    current_repository_evidence: Iterable[dict] | None = None,
) -> dict:
    """Validate V24 source binding and safety in addition to the Stage 3 gate."""
    value = plan if isinstance(plan, dict) else {}
    planning = context if isinstance(context, dict) else {}
    errors = []
    context_check = validate_verified_planning_context(
        planning, current_repository_evidence=current_repository_evidence,
    )
    if not context_check.get("valid"):
        errors.extend(context_check.get("errors", []))
    binding = value.get("verified_planning_context") if isinstance(value.get("verified_planning_context"), dict) else {}
    if value.get("planning_mode") != VERIFIED_STATE_REENTRY:
        errors.append("plan does not record VERIFIED_STATE_REENTRY")
    for key in (
        "source_reentry_hash", "source_task_brain_hash", "planning_context_hash",
        "source_project_brain_hash", "source_repository_evidence_hash",
    ):
        if binding.get(key) != planning.get(key):
            errors.append(f"plan source binding mismatch: {key}")
    if binding.get("source_promotion_hashes", []) != planning.get("source_promotion_hashes", []):
        errors.append("plan source binding mismatch: source_promotion_hashes")
    stale_ids = {
        str(item.get(key)) for item in planning.get("stale_evidence_warnings", []) or []
        for key in ("record_id", "fact_hash") if item.get(key)
    }
    stale_ids.update(
        str(ref) for item in planning.get("stale_evidence_warnings", []) or []
        for ref in item.get("evidence_refs", []) or []
    )
    if stale_ids.intersection(_plan_reference_ids(value)):
        errors.append(PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE)
    if any(
        str(item.get("provenance", "")).upper() == "STALE_WARNING"
        and str(item.get("use", "")).upper() in {"CURRENT_PROOF", "AUTHORITY", "PASS"}
        for item in value.get("planning_provenance", []) or [] if isinstance(item, dict)
    ):
        errors.append(PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE)

    reqs = _requirement_projection(list(requirements or planning.get("new_requirements", []) or []))
    req_ids = {str(item.get("requirement_id")) for item in reqs}
    covered = set()
    for record in value.get("coverage", []) or []:
        if isinstance(record, dict) and record.get("status") != "UNASSIGNED":
            covered.add(str(record.get("requirement_id")))
    for node in value.get("approved_change_nodes", []) or value.get("nodes", []) or []:
        if isinstance(node, dict):
            covered.update(str(item) for item in node.get("requirement_ids", []) or [])
    missing = sorted(req_ids - covered)
    if missing:
        errors.append(f"requirement coverage is incomplete: {', '.join(missing[:8])}")

    mandatory = [
        item for item in planning.get("current_authority", []) or []
        if isinstance(item, dict)
        and (
            item.get("authority_scope") == "NEW_REQUIREMENT"
            or _is_mandatory_authority_item(item)
        )
    ]
    plan_text = _plan_text(value).casefold()
    mandatory_dropped = []
    for item in mandatory:
        text = str(item.get("text") or _fact_text(item) or "")
        relation = _authority_relations([item])
        present = bool(relation and all(
            str(part).casefold() in plan_text
            for relation_item in relation for part in relation_item.values()
        )) or (text and len(_text_tokens(text).intersection(_text_tokens(plan_text))) >= 2)
        if not present:
            mandatory_dropped.append(item.get("record_id") or item.get("requirement_id") or text[:80])
    if mandatory_dropped:
        errors.append(MANDATORY_AUTHORITY_DROPPED)

    # A confirmed drift is a current conflict, not permission to rewrite
    # authority.  Require a bounded explicit reference when one exists.
    conflict_ids = {
        str(item.get("conflict_id")) for item in planning.get("confirmed_conflicts", []) or []
        if isinstance(item, dict) and item.get("conflict_id")
    }
    referenced_conflicts = _plan_reference_ids(value)
    unaddressed = sorted(conflict_ids - referenced_conflicts)
    if unaddressed and planning.get("confirmed_conflicts"):
        errors.append(CONFIRMED_DRIFT_NOT_ADDRESSED)

    owner_names, relations = _owner_candidates(planning)
    authority_change = _plan_authority_change(value)
    authorized = _authority_change_authorized(reqs)
    if authority_change and not authorized:
        errors.append(UNAUTHORIZED_AUTHORITY_CHANGE)
    if authority_change and authorized and not _plan_explicit_transition(value):
        errors.append("explicit authority-changing plan obligation is missing")
    if relations and authority_change and authorized:
        allowed_targets = _authorized_transition_target(reqs)
        proposed = _plan_owner_names(value)
        if allowed_targets and proposed and not proposed.intersection(allowed_targets):
            errors.append("plan authority transition target is not authorized")
    if owner_names and not authorized:
        proposed = _plan_owner_names(value)
        changed = proposed - owner_names
        if changed and (authority_change or _OWNER_ACTION_RE.search(plan_text)):
            errors.append(UNAUTHORIZED_AUTHORITY_CHANGE)

    if relations and not authorized:
        for relation in relations:
            if str(relation.get("object") or "").casefold() not in plan_text:
                errors.append("CURRENT_AUTHORITY_REUSE_MISSING")
                break

    preservation_requirements = [
        item for item in reqs
        if isinstance(item, dict) and re.search(
            r"\b(?:preserv|retain|remain|without breaking|must not|do not)\b",
            str(item.get("text") or ""), re.IGNORECASE,
        )
    ]
    for requirement in preservation_requirements:
        terms = _text_tokens(requirement.get("text"))
        if len(terms.intersection(_text_tokens(plan_text))) < 2:
            errors.append("PRESERVATION_REQUIREMENT_NOT_REPRESENTED")
            break

    prohibited_paths = {
        str(item.get("path")).replace("\\", "/")
        for item in planning.get("prohibitions", []) or []
        if isinstance(item, dict) and item.get("path") and re.search(
            r"\b(?:do not|don't|must not|never)\b",
            str(item.get("text") or ""), re.IGNORECASE,
        )
    }
    proposed_paths = set()
    for node in value.get("approved_change_nodes", []) or value.get("nodes", []) or []:
        if not isinstance(node, dict):
            continue
        proposed_paths.update(
            str(item).replace("\\", "/")
            for key in ("candidate_targets", "target_paths")
            for item in node.get(key, []) or []
        )
    if prohibited_paths.intersection(proposed_paths):
        errors.append("PLAN_VIOLATES_DO_NOT_TOUCH")

    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(str(item) for item in errors))[:24],
        "model_calls": 0,
        "mandatory_authority_drops": len(mandatory_dropped),
        "stale_evidence_blocks": sum(item == PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE for item in errors),
        "authority_change_blocks": sum(item == UNAUTHORIZED_AUTHORITY_CHANGE for item in errors),
        "confirmed_conflicts": len(planning.get("confirmed_conflicts", []) or []),
        "provenance_checked": True,
    }


validate_verified_planning_plan = validate_verified_plan
validate_plan_against_verified_context = validate_verified_plan


def run_verified_planning_self_test() -> dict:
    """Small deterministic V24 architecture self-test; never calls a model."""
    relation = {
        "subject": "PAUSE_STATE", "predicate": "owner", "object": "PauseController",
    }
    base = {
        "artifact_type": FRESH_TASK_BRAIN_TYPE,
        "schema_version": "V23.6A",
        "project_id": "self-test-project",
        "task_id": "self-test-task",
        "task_goal": {"text": "Add a pause indicator", "provenance": "USER_STATED"},
        "authority": [],
        "new_requirements": [{
            "requirement_id": "REQ-001", "text": "Add a pause indicator while preserving PauseController ownership.",
            "provenance": "USER_STATED", "authority": "USER/REQUIREMENT", "status": "CURRENT",
        }],
        "current_verified_facts": [{
            "record_id": "FACT-001", "fact_hash": "f" * 64,
            "fact": {"fact": "PauseController owns pause state", "category": "verified_state_ownership", "authority": "USER/REQUIREMENT", "structured_relation": relation},
            "classification": CURRENT_DURABLE_AUTHORITY, "project_id": "self-test-project",
        }],
        "current_durable_authority": [], "current_repository_evidence": [{
            "evidence_id": "REPO-001", "category": "CURRENT_STATE_OWNER", "path": "src/pause_controller.js",
            "symbol": "PauseController", "fact": "PauseController owns pause state", "support": "structured owner record",
            "evidence_type": "DIRECT_OBSERVATION", "provenance": REPOSITORY_EVIDENCE,
            "source_kind": "JS", "line_start": 1, "line_end": 1, "file_sha256": "a" * 64,
            "structured_relation": relation,
        }],
        "stale_verified_facts": [], "superseded_facts": [], "conflicts": [],
        "source_promotion_hashes": [], "authority_drift_audit": [],
        "reentry_hash": "r" * 64,
        "provenance": {
            "model_calls": 0, "old_task_brain_reused": False,
            "private_execution_material_loaded": False, "automatic_reverification": False,
        },
        "bounds": {"serialized_chars": 0}, "model_calls": 0,
    }
    base["task_brain_hash"] = canonical_hash({key: item for key, item in base.items() if key != "task_brain_hash"})
    # The V23 validator permits a larger set of fields but requires the exact
    # canonical hash above; the deterministic controls below exercise V24's
    # source and plan safety independent of model output.
    context = compile_verified_planning_context(base)
    context_before_packet_compilation = copy.deepcopy(context)
    def rehash(value):
        value["task_brain_hash"] = canonical_hash({
            key: item for key, item in value.items() if key != "task_brain_hash"
        })
        return value

    valid_plan = attach_plan_binding({
        "task_goal": "Add a pause indicator while preserving PauseController ownership.",
        "coverage": [{
            "requirement_id": "REQ-001", "status": "ASSIGNED", "node_ids": ["NODE-001"],
        }],
        "approved_change_nodes": [{
            "node_id": "NODE-001", "requirement_ids": ["REQ-001"],
            "goal": "Add the indicator through PauseController.togglePause.",
            "evidence_ids": ["REPO-001"], "done_when": ["the requirement is covered"],
        }],
    }, context)
    valid_plan_check = validate_verified_plan(valid_plan, context)

    drift = copy.deepcopy(base)
    drift["conflicts"] = [{
        "conflict_id": "DRIFT-SELF-TEST", "kind": AUTHORITY_IMPLEMENTATION_DRIFT,
        "authority_record_id": "FACT-001", "authority_fact_hash": "f" * 64,
        "authority_relation": relation,
        "repository_evidence_ids": ["REPO-001"],
        "repository_relation": {
            "subject": "PAUSE_STATE", "predicate": "owner", "object": "StatusView",
        },
        "drift_classification": CONFIRMED_DRIFT,
    }]
    drift["authority_drift_audit"] = [{
        "authority_record_id": "FACT-001", "evidence_refs": ["REPO-001"],
        "classification": CONFIRMED_DRIFT,
    }]
    drift_context = compile_verified_planning_context(rehash(drift))

    unknown = copy.deepcopy(base)
    unknown["conflicts"] = copy.deepcopy(drift["conflicts"])
    unknown["authority_drift_audit"] = [{
        "authority_record_id": "FACT-001", "evidence_refs": ["REPO-001"],
        "classification": NOT_EVALUABLE,
    }]
    unknown_context = compile_verified_planning_context(rehash(unknown))

    stale = copy.deepcopy(base)
    stale["stale_verified_facts"] = [{
        "record_id": "STALE-SELF-TEST", "fact_hash": "s" * 64,
        "classification": STALE_VERIFIED, "fact_summary": "stale proof",
    }]
    stale_context = compile_verified_planning_context(rehash(stale))
    stale_plan = copy.deepcopy(valid_plan)
    stale_plan["approved_change_nodes"][0]["evidence_ids"].append("STALE-SELF-TEST")
    stale_plan = attach_plan_binding(stale_plan, stale_context)
    stale_plan_check = validate_verified_plan(stale_plan, stale_context)

    # V24.1 packet compiler checks are deliberately local and synthetic: the
    # self-test exercises exact rendering and provider-boundary decisions
    # without importing the provider, starting Gemma, or mutating the full
    # VerifiedPlanningContext artifact.
    from hivo import impact_planning as impact

    decision_frame_self_test = impact.impact_decision_frame_self_test()

    stage3_brain = build_stage3_task_brain(context)
    stage3_requirements = context.get("new_requirements", [])
    stage3_evidence = context.get("current_repository_evidence", [])
    stage3_registry = impact.build_canonical_surface_registry(stage3_brain, stage3_evidence)
    role_render = lambda value: "IMPACT PLANNER PACKET:\n" + impact._compact_json(value)
    live_packet = impact.build_canonical_planning_packet(
        stage3_brain, stage3_requirements, stage3_evidence,
        surface_registry=stage3_registry,
        role="ImpactPlanner", render=role_render, base_render=role_render,
        verified_planning_context=context,
    )
    live_role_packet = live_packet.get("role_packet", {})
    live_core = live_packet.get("canonical_mandatory_planning_core", {})
    live_core_check = impact.validate_canonical_mandatory_planning_core(live_core)
    fan_in_payload = {
        "requirements": [{
            "requirement_id": "REQ-FANIN",
            "text": "Keep PauseController as the pause-state owner.",
        }],
        "current_authority": [
            {
                "record_id": "AUTH-FANIN",
                "text": "Keep PauseController as the pause-state owner.",
                "structured_relation": relation,
            },
            {
                "record_id": "REPO-FANIN",
                "fact": "Keep PauseController as the pause-state owner.",
                "structured_relation": relation,
            },
        ],
        "preservation_constraints": [{
            "record_id": "PRES-FANIN",
            "text": "Keep PauseController as the pause-state owner.",
        }],
    }
    fan_in_core = impact.build_canonical_mandatory_planning_core(fan_in_payload)
    fan_in_refs = {
        reference
        for provenance in fan_in_core.get("provenance_map", {}).values()
        for reference in provenance.get("source_references", [])
    }
    live_packet_validation = impact.validate_planning_packet(
        live_packet, registry=stage3_registry, requirements=stage3_requirements,
    )

    optional_overflow = impact.build_planning_role_packet(
        "ImpactPlanner",
        {"required": "R" * 20, "supporting": []},
        [
            {"item_id": "OPTIONAL-HIGH", "priority": 90, "path": ("supporting",),
             "index": 0, "value": {"text": "high-priority current evidence"}},
            {"item_id": "OPTIONAL-LOW", "priority": 10, "path": ("supporting",),
             "index": 1, "value": {"text": "L" * 160}},
        ],
        hard_limit=90, render=lambda value: impact._compact_json(value),
    )
    mandatory_overflow = impact.build_planning_role_packet(
        "ImpactPlanner", {"required": "M" * 180}, [], hard_limit=80,
        render=lambda value: "ENV:\n" + impact._compact_json(value),
    )
    stale_packet = impact.build_canonical_planning_packet(
        build_stage3_task_brain(stale_context), stale_context.get("new_requirements", []),
        stale_context.get("current_repository_evidence", []),
        surface_registry=impact.build_canonical_surface_registry(
            build_stage3_task_brain(stale_context), stale_context.get("current_repository_evidence", []),
        ), role="ImpactPlanner", render=role_render, base_render=role_render,
        verified_planning_context=stale_context,
    )
    drift_brain = build_stage3_task_brain(drift_context)
    drift_evidence = drift_context.get("current_repository_evidence", [])
    drift_packet = impact.build_canonical_planning_packet(
        drift_brain, drift_context.get("new_requirements", []), drift_evidence,
        surface_registry=impact.build_canonical_surface_registry(drift_brain, drift_evidence),
        role="ImpactPlanner", render=role_render, base_render=role_render,
        verified_planning_context=drift_context,
    )
    checks = {
        "compiler_zero_model": context.get("model_calls") == 0,
        "context_compiled": context.get("status") == "COMPILED" and context.get("valid") is True,
        "context_hash_deterministic": (
            planning_context_hash(context) == context.get("planning_context_hash")
            if context.get("planning_context_hash") else True
        ),
        "readiness_current_evidence": assess_planning_context_readiness(context).get("ready") is True,
        "valid_plan_reaches_approval_boundary": valid_plan_check.get("valid") is True,
        "true_structured_drift_retained": (
            len(drift_context.get("confirmed_conflicts", [])) == 1
            and drift_context.get("model_calls") == 0
        ),
        "unknown_evidence_not_conflict": (
            not unknown_context.get("confirmed_conflicts")
            and len(unknown_context.get("not_evaluable_audit", [])) == 1
        ),
        "stale_evidence_plan_blocked": (
            stale_plan_check.get("valid") is False
            and PLAN_RELIES_ON_STALE_VERIFIED_EVIDENCE in stale_plan_check.get("errors", [])
        ),
        "live_packet_fits_exact_limit": (
            live_packet.get("packet_complete") is True
            and live_role_packet.get("rendered_chars", 0) <= impact.MAX_PLANNER_CONTEXT_CHARS
            and live_packet_validation.get("valid") is True
        ),
        "live_packet_mandatory_drops_zero": (
            live_role_packet.get("mandatory_drops", []) == []
        ),
        "live_packet_provider_boundary_reachable": (
            live_role_packet.get("exact_model_input") == live_role_packet.get("rendered_packet")
            and live_role_packet.get("accounting", {}).get("matches_exact_render") is True
        ),
        "canonical_mandatory_core_valid": live_core_check.get("valid") is True,
        "canonical_mandatory_core_zero_model": (
            live_core.get("metrics", {}).get("planning_core_model_calls") == 0
            and live_core_check.get("model_calls") == 0
        ),
        "canonical_mandatory_core_hash_deterministic": (
            live_core.get("mandatory_core_hash") == impact.canonical_mandatory_core_hash(live_core)
        ),
        "canonical_mandatory_core_coverage_complete": (
            live_core.get("mandatory_semantic_coverage_rate") == 1.0
            and all(
                item.get("represented")
                and item.get("source_provenance_retained")
                and (
                    not item.get("model_semantic_required")
                    or item.get("model_semantic_represented")
                )
                for item in live_core.get("mandatory_semantic_coverage", [])
            )
        ),
        "canonical_mandatory_core_fan_in_provenance": (
            len(fan_in_core.get("semantic_units", [])) < len(fan_in_core.get("mandatory_semantic_coverage", []))
            and {"AUTH-FANIN", "REPO-FANIN", "PRES-FANIN"}.issubset(fan_in_refs)
        ),
        "current_vs_desired_structured_audit": (
            impact.audit_current_vs_desired_representation(live_packet.get("packet", {})).get("valid") is True
        ),
        "live_packet_exact_render_is_audited_input": (
            live_role_packet.get("rendered_chars") == len(live_role_packet.get("exact_model_input", ""))
            and live_role_packet.get("rendered_chars") == len(live_role_packet.get("rendered_packet", ""))
        ),
        "verified_planning_context_unchanged_by_packet_compilation": (
            context == context_before_packet_compilation
        ),
        "optional_overflow_trims_to_complete": (
            optional_overflow.get("packet_complete") is True
            and "OPTIONAL-LOW" in optional_overflow.get("optional_items_dropped_ids", [])
            and optional_overflow.get("mandatory_drops", []) == []
        ),
        "mandatory_overflow_fails_closed": (
            mandatory_overflow.get("status") == impact.PLANNING_PACKET_MANDATORY_OVERFLOW
            and mandatory_overflow.get("packet_complete") is False
            and mandatory_overflow.get("mandatory_drops", []) == []
        ),
        "stale_warning_not_promoted": (
            all(
                item.get("classification") == "STALE_WARNING"
                for item in stale_packet.get("packet", {}).get("stale_evidence_warnings", [])
            )
            and not any(
                item.get("record_id") == "STALE-SELF-TEST"
                for item in stale_packet.get("packet", {}).get("current_verified_facts", [])
            )
        ),
        "confirmed_drift_retained_in_packet": bool(
            drift_packet.get("packet", {}).get("confirmed_conflicts")
        ),
        "impact_decision_frame_architecture": decision_frame_self_test.get("passed") is True,
    }
    return {
        "passed": all(checks.values()), "checks": checks, "model_calls": 0,
        "diagnostics": {
            "context_hash": context.get("planning_context_hash"),
            "drift_conflicts": len(drift_context.get("confirmed_conflicts", [])),
            "unknown_audits": len(unknown_context.get("not_evaluable_audit", [])),
            "stale_plan_errors": stale_plan_check.get("errors", []),
            "live_packet": {
                "rendered_chars": live_role_packet.get("rendered_chars"),
                "hard_limit_chars": live_role_packet.get("hard_limit_chars"),
                "mandatory_drops": live_role_packet.get("mandatory_drops", []),
                "packet_hash": live_role_packet.get("packet_hash"),
            },
            "optional_dropped": optional_overflow.get("optional_items_dropped_ids", []),
            "mandatory_overflow_status": mandatory_overflow.get("status"),
            "impact_decision_frame": decision_frame_self_test.get("diagnostics", {}),
        },
    }
