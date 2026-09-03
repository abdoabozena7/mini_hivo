"""Stage 6C-A approval-bound execution authorization.

This module owns the small, deterministic boundary between a validated
``PLAN_APPROVAL_REQUIRED`` result and an execution-eligible Stage 4 graph.
It deliberately has no model, Worker, repository-mutation, or Project Brain
write path.  The persisted Stage 6B replay helper below is read-only.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from hivo import impact_planning as stage3
from hivo import execution_invariants as invariant
from hivo.requirements import freeze


SCHEMA_VERSION = "6C-A"
PLAN_APPROVAL_REQUIRED = "PLAN_APPROVAL_REQUIRED"
APPROVAL_REQUEST_READY = "APPROVAL_REQUEST_READY"
APPROVAL_RECORDED = "APPROVAL_RECORDED"
APPROVAL_INVALID = "APPROVAL_INVALID"
APPROVAL_STALE = "APPROVAL_STALE"
REAPPROVAL_REQUIRED = "REAPPROVAL_REQUIRED"
EXECUTION_AUTHORIZATION_READY = "EXECUTION_AUTHORIZATION_READY"
EXECUTION_AUTHORIZATION_BLOCKED = "EXECUTION_AUTHORIZATION_BLOCKED"

EXPLICIT_USER_APPROVAL = "EXPLICIT_USER_APPROVAL"
TEST_EXPLICIT_USER_APPROVAL = "TEST_EXPLICIT_USER_APPROVAL"

APPROVAL_PLAN_HASH_MISMATCH = "APPROVAL_PLAN_HASH_MISMATCH"
PLAN_HASH_MISMATCH = "PLAN_HASH_MISMATCH"
APPROVAL_REQUIREMENT_MISMATCH = "APPROVAL_REQUIREMENT_MISMATCH"
APPROVAL_SUBJECT_STALE = "APPROVAL_SUBJECT_STALE"
APPROVAL_BRAIN_STALE = "APPROVAL_BRAIN_STALE"
APPROVAL_PLANNING_CONTEXT_MISMATCH = "APPROVAL_PLANNING_CONTEXT_MISMATCH"
APPROVAL_SOURCE_BINDING_MISMATCH = "APPROVAL_SOURCE_BINDING_MISMATCH"
APPROVAL_MUTATION_SCOPE_MISMATCH = "APPROVAL_MUTATION_SCOPE_MISMATCH"
APPROVAL_DNT_MISMATCH = "APPROVAL_DNT_MISMATCH"
APPROVAL_DEPENDENCY_MISMATCH = "APPROVAL_DEPENDENCY_MISMATCH"
APPROVAL_VERIFICATION_MISMATCH = "APPROVAL_VERIFICATION_MISMATCH"
APPROVAL_INTERFACE_MISMATCH = "APPROVAL_INTERFACE_MISMATCH"
APPROVAL_RECONCILIATION_MISMATCH = "APPROVAL_RECONCILIATION_MISMATCH"
APPROVAL_AUTHORITY_CONSTRAINT_MISMATCH = "APPROVAL_AUTHORITY_CONSTRAINT_MISMATCH"
APPROVAL_FRESHNESS_MISMATCH = "APPROVAL_FRESHNESS_MISMATCH"
APPROVAL_CONTRACTABILITY_MISMATCH = "APPROVAL_CONTRACTABILITY_MISMATCH"
APPROVAL_RECEIPT_INVALID = "APPROVAL_RECEIPT_INVALID"
APPROVAL_TASK_MISMATCH = "APPROVAL_TASK_MISMATCH"
APPROVAL_REQUEST_INVALID = "APPROVAL_REQUEST_INVALID"
EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH = "EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH"
APPROVAL_DNT_VIOLATION = "APPROVAL_DNT_VIOLATION"
APPROVAL_AUTHORITY_CHANGE = "APPROVAL_AUTHORITY_CHANGE"
EXECUTION_INVARIANT_SET_REQUIRED = invariant.EXECUTION_INVARIANT_SET_REQUIRED
EXECUTION_INVARIANT_INVALID = invariant.EXECUTION_INVARIANT_INVALID

_BINDING_FIELDS = (
    "task_id", "requirement_ids", "canonical_plan_id", "canonical_plan_hash",
    "planning_mode", "brain_hash", "subject_aggregate_hash",
    "planning_context_hash", "impact_decision_frame_hash",
    "impact_decision_choice_hash", "impact_map_hash",
    "challenger_reconciliation_hash", "mutation_scope_digest", "dnt_digest",
    "dependency_digest", "verification_contract_digest", "interface_binding_digest",
    "requirement_coverage_digest", "source_bindings", "authority_constraints",
)

_RECEIPT_FIELDS = (
    "approval_id", "approval_request_hash", "canonical_plan_id",
    "canonical_plan_hash", "approved_mutation_scope_digest", "approved_dnt_digest",
    "approved_dependency_digest", "approved_verification_digest",
    "approved_interface_binding_digest", "approved_requirement_coverage_digest",
    "approved_brain_hash", "approved_subject_aggregate_hash",
    "approved_planning_context_hash", "approved_source_bindings",
    "approved_requirement_ids", "approved_task_id", "approval_source",
    "approval_event_reference", "receipt_hash", "status", "schema_version",
)


class ApprovalAuthorityError(ValueError):
    """A deterministic fail-closed approval-boundary error."""

    def __init__(self, code: str, message: str, details: Iterable[Any] | None = None):
        super().__init__(message)
        self.code = str(code)
        self.details = list(details or [])


class ApprovalRequestError(ApprovalAuthorityError):
    pass


class ApprovalReceiptError(ApprovalAuthorityError):
    pass


class ExecutionAuthorizationError(ApprovalAuthorityError):
    pass


def canonical_hash(value: Any) -> str:
    """Return the stable compact-JSON SHA-256 used by this authority layer."""
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


deterministic_hash = canonical_hash


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _without(value: Any, *keys: str) -> dict[str, Any]:
    result = _copy(value) if isinstance(value, dict) else {}
    for key in keys:
        result.pop(key, None)
    return result


def _text(value: Any) -> str:
    return str(value or "").strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _sorted_strings(values: Iterable[Any]) -> list[str]:
    return sorted({_text(item) for item in values if _text(item)}, key=lambda item: (item.casefold(), item))


def _ordered_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _freeze(value: Any) -> Any:
    return freeze(_copy(value))


def _get(mapping: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return default


def _context(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    candidate = _get(state, "verified_planning_context", "planning_context", default=None)
    if not isinstance(candidate, dict):
        candidate = _get(plan, "verified_planning_context", "planning_context", default={})
    return candidate if isinstance(candidate, dict) else {}


def _upstream(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    candidate = _get(state, "upstream_bindings", default=None)
    if not isinstance(candidate, dict):
        candidate = _get(plan, "upstream_bindings", default={})
    return candidate if isinstance(candidate, dict) else {}


def _source_fingerprint(plan: dict[str, Any], state: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "subject_fingerprint", "source_repository_fingerprint", default=None)
    if not isinstance(value, dict):
        value = _get(context, "source_repository_fingerprint", default=None)
    if not isinstance(value, dict):
        value = _get(plan, "source_repository_fingerprint", default=None)
    return value if isinstance(value, dict) else {}


def _subject_hash(plan: dict[str, Any], state: dict[str, Any], context: dict[str, Any]) -> str:
    fingerprint = _source_fingerprint(plan, state, context)
    return _text(_get(
        state, "subject_aggregate_hash", "subject_hash", "current_subject_hash",
        default=_get(fingerprint, "hash", default=_get(context, "subject_aggregate_hash", default="")),
    ))


def _brain_hash(plan: dict[str, Any], state: dict[str, Any], context: dict[str, Any], upstream: dict[str, Any]) -> str:
    return _text(_get(
        state, "brain_hash", "project_brain_hash", "source_project_brain_hash",
        default=_get(context, "source_project_brain_hash", default=_get(upstream, "source_project_brain_hash", default="")),
    ))


def _planning_context_hash(plan: dict[str, Any], state: dict[str, Any], context: dict[str, Any], upstream: dict[str, Any]) -> str:
    return _text(_get(
        state, "planning_context_hash", default=_get(
            context, "planning_context_hash", "context_hash", default=_get(upstream, "planning_context_hash", default=""),
        ),
    ))


def _requirements(plan: dict[str, Any], state: dict[str, Any]) -> list[dict[str, Any]]:
    value = _get(state, "requirements", default=None)
    if not isinstance(value, list):
        value = plan.get("requirements", [])
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _requirement_ids(plan: dict[str, Any], state: dict[str, Any]) -> list[str]:
    return _sorted_strings(item.get("requirement_id") for item in _requirements(plan, state))


def _plan_hash(plan: dict[str, Any]) -> str:
    supplied = _text(plan.get("plan_hash"))
    try:
        computed = stage3.plan_content_hash(plan)
    except Exception:
        computed = ""
    if supplied and computed and supplied == computed:
        return supplied
    return supplied


def _verification_records(plan: dict[str, Any], state: dict[str, Any]) -> list[Any]:
    value = _get(state, "canonical_verification_contracts", "verification_contracts", default=None)
    if not isinstance(value, list):
        value = plan.get("canonical_verification_contracts")
    if not isinstance(value, list):
        value = plan.get("verification_contracts")
    return _copy(value) if isinstance(value, list) else []


def _reconciliation(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "challenger_reconciliation", "reconciliation", default=None)
    if not isinstance(value, dict):
        value = plan.get("challenger_reconciliation", {})
    return value if isinstance(value, dict) else {}


def _mutation_scope(plan: dict[str, Any]) -> dict[str, Any]:
    records = []
    for node in _as_list(plan.get("approved_change_nodes")):
        if not isinstance(node, dict):
            continue
        if not bool(node.get("mutation_required")) or bool(node.get("verification_only")):
            continue
        paths = _ordered_unique(
            list(node.get("candidate_targets", []) or [])
            + list(node.get("target_paths", []) or [])
        )
        surfaces = _sorted_strings(
            list(node.get("target_surface_ids", []) or [])
            or list(node.get("surface_ids", []) or [])
        )
        records.append({
            "node_id": _text(node.get("node_id")),
            "surface_ids": surfaces,
            "paths": sorted(paths, key=lambda item: (item.casefold(), item)),
            "requirement_ids": _sorted_strings(node.get("requirement_ids", [])),
        })
    records.sort(key=lambda item: item["node_id"])
    return {
        "nodes": records,
        "surface_ids": sorted({item for row in records for item in row["surface_ids"]}),
        "paths": sorted({item for row in records for item in row["paths"]}, key=lambda item: (item.casefold(), item)),
    }


def _dnt(plan: dict[str, Any]) -> dict[str, Any]:
    constraints = plan.get("canonical_constraints") if isinstance(plan.get("canonical_constraints"), dict) else {}
    prohibitions = constraints.get("prohibitions", []) if isinstance(constraints, dict) else []
    prohibition_text = [
        item.get("text") for item in _as_list(prohibitions)
        if isinstance(item, dict) and item.get("text")
    ]
    return {
        "paths": sorted(_ordered_unique(plan.get("do_not_touch", [])), key=lambda item: (item.casefold(), item)),
        "surface_ids": _sorted_strings(plan.get("do_not_touch_surface_ids", [])),
        "prohibitions": sorted(_ordered_unique(prohibition_text), key=lambda item: (item.casefold(), item)),
    }


def _dependencies(plan: dict[str, Any]) -> dict[str, Any]:
    records = []
    missing = False
    for node in _as_list(plan.get("approved_change_nodes")):
        if not isinstance(node, dict):
            continue
        if "dependencies" not in node:
            missing = True
        records.append({
            "node_id": _text(node.get("node_id")),
            "dependencies": _ordered_unique(node.get("dependencies", [])),
            "dependencies_present": "dependencies" in node,
        })
    records.sort(key=lambda item: item["node_id"])
    return {"nodes": records, "unknown": missing}


def _state_dependencies(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "dependencies", "dependency_graph", default=None)
    if isinstance(value, dict) and ("nodes" in value or "unknown" in value):
        return _copy(value)
    if isinstance(value, list):
        records = []
        for item in value:
            if isinstance(item, dict):
                records.append({
                    "node_id": _text(item.get("node_id")),
                    "dependencies": _ordered_unique(item.get("dependencies", [])),
                    "dependencies_present": "dependencies" in item,
                })
        records.sort(key=lambda item: item["node_id"])
        return {"nodes": records, "unknown": any("dependencies_present" not in item for item in records)}
    return _dependencies(plan)


def _interfaces(plan: dict[str, Any]) -> dict[str, Any]:
    node_records = []
    derived_symbols = []
    for node in _as_list(plan.get("approved_change_nodes")):
        if not isinstance(node, dict):
            continue
        if node.get("current_owner"):
            derived_symbols.append(node.get("current_owner"))
        node_records.append({
            "node_id": _text(node.get("node_id")),
            "interfaces": _sorted_strings(node.get("interfaces_to_reuse", [])),
            "surface_ids": _sorted_strings(node.get("interface_surface_ids", [])),
        })
    node_records.sort(key=lambda item: item["node_id"])
    return {
        "interfaces": _sorted_strings(plan.get("interfaces_to_reuse", [])),
        "surface_ids": _sorted_strings(plan.get("interface_surface_ids", [])),
        "derived_symbols": _sorted_strings(derived_symbols),
        "nodes": node_records,
    }


def _state_interfaces(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "interface_binding", "interfaces", default=None)
    if isinstance(value, dict) and ("interfaces" in value or "nodes" in value):
        return _copy(value)
    if value is not None or "interfaces_to_reuse" in state or "interface_surface_ids" in state:
        return {
            "interfaces": _sorted_strings(_as_list(_get(state, "interfaces_to_reuse", default=value if value is not None else []))),
            "surface_ids": _sorted_strings(_get(state, "interface_surface_ids", default=[])),
            "derived_symbols": _sorted_strings(_get(state, "derived_interface_symbols", default=[])),
            "nodes": [],
        }
    return _interfaces(plan)


def _state_dnt(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "dnt", "do_not_touch", default=None)
    if isinstance(value, dict):
        return _copy(value)
    if value is not None or "do_not_touch_surface_ids" in state:
        return {
            "paths": sorted(_ordered_unique(_as_list(value if value is not None else [])), key=lambda item: (item.casefold(), item)),
            "surface_ids": _sorted_strings(_get(state, "do_not_touch_surface_ids", default=[])),
            "prohibitions": sorted(_ordered_unique(_get(state, "prohibitions", default=[])), key=lambda item: (item.casefold(), item)),
        }
    return _dnt(plan)


def _state_scope(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "mutation_scope", "executable_mutation_scope", default=None)
    return _copy(value) if isinstance(value, dict) else _mutation_scope(plan)


def _coverage(plan: dict[str, Any], state: dict[str, Any], requirement_ids: list[str]) -> dict[str, Any]:
    value = _get(state, "coverage", default=None)
    if not isinstance(value, list):
        value = plan.get("coverage", [])
    rows = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        rows.append({
            "requirement_id": _text(item.get("requirement_id")),
            "status": _text(item.get("status")),
            "semantic_state": _text(item.get("semantic_state")),
            "node_ids": _sorted_strings(item.get("node_ids", [])),
            "impact_ids": _sorted_strings(item.get("impact_ids", [])),
            "obligation_ids": _sorted_strings(item.get("obligation_ids", [])),
            "obligation_types": _sorted_strings(item.get("obligation_types", [])),
        })
    rows.sort(key=lambda item: item["requirement_id"])
    return {"requirement_ids": list(requirement_ids), "coverage": rows}


class _FrozenRecord(dict):
    """Immutable JSON-shaped top-level record with normal mapping access."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("approval authority records are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other: Any) -> Any:
        self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


class PlanApprovalRequest(_FrozenRecord):
    """Exact, immutable candidate presented to the explicit approval boundary."""


class ExplicitUserApprovalEvent(_FrozenRecord):
    """Opaque caller-supplied approval event; no user identity is invented."""


class PlanApprovalReceipt(_FrozenRecord):
    """Immutable proof that one explicit event approved one request."""


class PreExecutionApprovalRevalidation(_FrozenRecord):
    """Immutable comparison of approved authority to the current state."""


class ApprovedExecutionAuthorization(_FrozenRecord):
    """Immutable execution eligibility proof; it does not execute anything."""


def _freeze_record(record_type: type[_FrozenRecord], value: dict[str, Any]) -> _FrozenRecord:
    result = record_type()
    dict.__init__(result, ((key, _freeze(item)) for key, item in value.items()))
    return result


def _authority_constraints(plan: dict[str, Any], state: dict[str, Any]) -> dict[str, Any]:
    value = _get(state, "authority_constraints", "constraints", default=None)
    if not isinstance(value, dict):
        value = plan.get("authority_constraints", {})
    value = value if isinstance(value, dict) else {}
    proposals = _get(state, "new_surface_proposals", default=plan.get("new_surface_proposals", []))
    proposal_refs = []
    for item in _as_list(proposals):
        if isinstance(item, dict):
            proposal_refs.append({
                "proposal_id": _text(item.get("proposal_id")),
                "parent_scope": _text(item.get("parent_scope")),
                "hash": canonical_hash(item),
            })
        else:
            proposal_refs.append({"proposal_id": _text(item), "hash": canonical_hash(item)})
    return {
        "declared": _copy(value),
        "new_surface_proposals": sorted(proposal_refs, key=lambda item: item.get("proposal_id", "")),
        "new_owner": bool(value.get("NEW_OWNER") or value.get("new_owner")),
        "owner_migration": bool(value.get("OWNER_MIGRATION") or value.get("owner_migration")),
        "authority_change": bool(value.get("AUTHORITY_CHANGE") or value.get("authority_change")),
    }


def _source_bindings(plan: dict[str, Any], state: dict[str, Any], context: dict[str, Any], upstream: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for source in (upstream, context, state):
        if not isinstance(source, dict):
            continue
        for key, value in source.items():
            normalized = str(key)
            if (
                normalized.endswith("_hash")
                or normalized in {
                    "planning_mode", "source_priority", "source_promotion_hashes",
                    "source_provenance", "project_id", "task_id",
                }
            ) and value not in (None, "", [], {}):
                result[normalized] = _copy(value)
    result["plan_provenance_digest"] = canonical_hash({
        "provenance": plan.get("provenance", {}),
        "planning_provenance": plan.get("planning_provenance", []),
    })
    fingerprint = _source_fingerprint(plan, state, context)
    if fingerprint:
        result["subject_fingerprint_hash"] = _text(fingerprint.get("hash")) or canonical_hash(fingerprint)
    return result


def build_approval_authority_binding(plan: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Derive compact authority references from a canonical plan and state."""
    value = plan if isinstance(plan, dict) else {}
    current = state if isinstance(state, dict) else {}
    context = _context(value, current)
    upstream = _upstream(value, current)
    requirement_ids = _requirement_ids(value, current)
    reconciliation = _reconciliation(value, current)
    scope = _state_scope(value, current)
    dnt = _state_dnt(value, current)
    dependencies = _state_dependencies(value, current)
    verifications = _verification_records(value, current)
    interfaces = _state_interfaces(value, current)
    coverage = _coverage(value, current, requirement_ids)
    source = _source_bindings(value, current, context, upstream)
    binding = {
        "schema_version": SCHEMA_VERSION,
        "task_id": _text(_get(current, "task_id", default=_get(context, "task_id", default=value.get("task_id", "")))),
        "requirement_ids": requirement_ids,
        "requirement_id": requirement_ids[0] if len(requirement_ids) == 1 else "",
        "canonical_plan_id": _text(value.get("plan_id")),
        "canonical_plan_hash": _text(value.get("plan_hash")),
        "planning_mode": _text(_get(current, "planning_mode", default=_get(context, "planning_mode", default=value.get("planning_mode", "")))),
        "brain_hash": _brain_hash(value, current, context, upstream),
        "subject_aggregate_hash": _subject_hash(value, current, context),
        "planning_context_hash": _planning_context_hash(value, current, context, upstream),
        "impact_decision_frame_hash": _text(_get(
            current, "impact_decision_frame_hash", default=upstream.get("impact_decision_frame_hash", ""),
        )),
        "impact_decision_choice_hash": _text(_get(
            current, "impact_decision_choice_hash", default=upstream.get("impact_decision_choice_hash", ""),
        )),
        "impact_map_hash": _text(_get(
            current, "impact_map_hash", "compiled_impact_map_hash", default=upstream.get("impact_map_hash", ""),
        )),
        "challenger_reconciliation_hash": _text(_get(
            current, "challenger_reconciliation_hash", default=reconciliation.get("reconciliation_hash", ""),
        )),
        "mutation_scope": scope,
        "mutation_scope_digest": canonical_hash(scope),
        "dnt": dnt,
        "dnt_digest": canonical_hash(dnt),
        "dependencies": dependencies,
        "dependency_digest": canonical_hash(dependencies),
        "verification_contracts": verifications,
        "verification_contract_digest": canonical_hash(verifications),
        "interface_binding": interfaces,
        "interface_binding_digest": canonical_hash(interfaces),
        "requirement_coverage": coverage,
        "requirement_coverage_digest": canonical_hash(coverage),
        "source_bindings": source,
        "authority_constraints": _authority_constraints(value, current),
        "authority_constraints_digest": canonical_hash(_authority_constraints(value, current)),
        "reconciliation": {
            "hash": _text(reconciliation.get("reconciliation_hash")),
            "open_blocking_count": int(reconciliation.get("open_blocking_count", 0) or 0),
            "open_blocking_challenge_ids": _sorted_strings(reconciliation.get("open_blocking_challenge_ids", [])),
            "applied_effect_challenge_ids": _sorted_strings(reconciliation.get("applied_effect_challenge_ids", [])),
            "suppressed_effect_challenge_ids": _sorted_strings(reconciliation.get("suppressed_effect_challenge_ids", [])),
        },
    }
    # Negative fixtures and live adapters may expose an already-computed
    # current digest instead of duplicating the semantic record.  Treat those
    # values as current observations; never silently fall back to the old
    # approved digest.
    digest_overrides = {
        "mutation_scope_digest": ("current_mutation_scope_digest", "mutation_scope_digest"),
        "dnt_digest": ("current_dnt_digest", "dnt_digest"),
        "dependency_digest": ("current_dependency_digest", "dependency_digest"),
        "verification_contract_digest": ("current_verification_digest", "verification_digest"),
        "interface_binding_digest": ("current_interface_binding_digest", "interface_binding_digest"),
        "requirement_coverage_digest": ("current_requirement_coverage_digest", "requirement_coverage_digest"),
        "challenger_reconciliation_hash": ("current_challenger_reconciliation_hash", "challenger_reconciliation_hash"),
        "planning_context_hash": ("current_planning_context_hash",),
        "brain_hash": ("current_brain_hash",),
        "subject_aggregate_hash": ("current_subject_aggregate_hash",),
    }
    for target, keys in digest_overrides.items():
        observed = _get(current, *keys, default=None)
        if observed not in (None, ""):
            binding[target] = _copy(observed)
    return binding


def _validator_pass(state: dict[str, Any], plan: dict[str, Any]) -> bool:
    candidate = _get(state, "plan_validation", "final_plan_validation", "final_validator", default=None)
    if not isinstance(candidate, dict):
        candidate = _get(plan, "plan_validation", default=None)
    if isinstance(candidate, dict):
        if candidate.get("valid") is True or _text(candidate.get("status")).upper() in {"PASS", "VALID", "READY"}:
            return True
        return False
    return bool(_get(state, "final_plan_validator_pass", "plan_validator_pass", default=False))


def _coverage_pass(plan: dict[str, Any], state: dict[str, Any], requirement_ids: list[str]) -> bool:
    explicit = _get(state, "coverage_complete", "coverage_pass", default=None)
    if explicit is not None:
        return bool(explicit)
    rows = _coverage(plan, state, requirement_ids).get("coverage", [])
    if not requirement_ids or not rows:
        return False
    by_requirement = {str(item.get("requirement_id")): item for item in rows}
    return all(
        isinstance(by_requirement.get(requirement_id), dict)
        and _text(by_requirement[requirement_id].get("status")).upper() in {"COVERED", "COVERED_BY_CHANGE", "PASS", "VALID"}
        for requirement_id in requirement_ids
    )


def _freshness_pass(plan: dict[str, Any], state: dict[str, Any]) -> bool:
    candidate = _get(state, "planning_context_freshness", "freshness", default=None)
    if not isinstance(candidate, dict):
        candidate = _get(plan, "planning_context_freshness", default=None)
    if isinstance(candidate, dict):
        return bool(candidate.get("fresh") is True and (
            candidate.get("context_validation") in (None, {}, True)
            or (isinstance(candidate.get("context_validation"), dict) and candidate["context_validation"].get("valid") is True)
        ))
    return bool(_get(state, "freshness_pass", "planning_context_fresh", default=False))


def _contractability_pass(plan: dict[str, Any], state: dict[str, Any]) -> bool:
    candidate = _get(state, "stage4_contractability_audit", "stage4_contractability", default=None)
    if not isinstance(candidate, dict):
        candidate = _get(plan, "stage4_contractability_audit", "stage4_contractability", default=None)
    if isinstance(candidate, dict):
        return bool(
            candidate.get("contractable") is True
            or candidate.get("valid") is True
            or _text(candidate.get("status")).upper() in {"PASS", "READY", "CONTRACTABLE"}
        ) and candidate.get("stage4_executed") is not True
    return bool(_get(state, "stage4_contractability_pass", default=False))


def _terminal_state(plan: dict[str, Any], state: dict[str, Any]) -> str:
    return _text(_get(
        state, "terminal_state", "approval_boundary", default=_get(plan, "terminal_state", "approval_boundary", default=""),
    ))


def _request_precondition_errors(plan: dict[str, Any], state: dict[str, Any], binding: dict[str, Any]) -> list[dict[str, Any]]:
    errors: list[dict[str, Any]] = []
    plan_hash = _text(plan.get("plan_hash"))
    try:
        computed_hash = stage3.plan_content_hash(plan)
    except Exception:
        computed_hash = ""
    if not _text(plan.get("plan_id")) or not plan_hash:
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "canonical plan identity is incomplete"})
    elif computed_hash != plan_hash:
        errors.append({"code": PLAN_HASH_MISMATCH, "reason": "canonical plan hash is invalid", "expected": computed_hash, "actual": plan_hash})
    if not _validator_pass(state, plan):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "final plan validator is not PASS"})
    if not _coverage_pass(plan, state, binding.get("requirement_ids", [])):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "requirement/obligation coverage is incomplete"})
    if not _freshness_pass(plan, state):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "planning-context freshness is not PASS"})
    if not _contractability_pass(plan, state):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "Stage 4 contractability is not PASS"})
    if _terminal_state(plan, state) != PLAN_APPROVAL_REQUIRED:
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "approval request is not at PLAN_APPROVAL_REQUIRED"})
    reconciliation = binding.get("reconciliation", {})
    if int(reconciliation.get("open_blocking_count", 0) or 0) or reconciliation.get("open_blocking_challenge_ids"):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "blocking Challenger reconciliation concern remains open"})
    required_fields = {
        "task_id": "task identity", "requirement_id": "requirement identity", "planning_mode": "planning mode",
        "brain_hash": "Brain hash", "subject_aggregate_hash": "subject aggregate hash",
        "planning_context_hash": "planning-context hash", "impact_decision_frame_hash": "ImpactDecisionFrame hash",
        "impact_decision_choice_hash": "ImpactPlanner choice hash", "impact_map_hash": "Impact Map hash",
        "challenger_reconciliation_hash": "Challenger reconciliation hash",
    }
    for field, label in required_fields.items():
        if not binding.get(field):
            errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": f"{label} is missing"})
    if not binding.get("verification_contracts"):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "mandatory verification contracts are missing"})
    if binding.get("dependencies", {}).get("unknown"):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "dependency semantics are missing/unknown"})
    if not binding.get("source_bindings"):
        errors.append({"code": APPROVAL_REQUEST_INVALID, "reason": "source/provenance bindings are missing"})
    scope = binding.get("mutation_scope", {}) if isinstance(binding.get("mutation_scope"), dict) else {}
    dnt = binding.get("dnt", {}) if isinstance(binding.get("dnt"), dict) else {}
    if set(_text(item).casefold() for item in scope.get("paths", []) or []).intersection(
        set(_text(item).casefold() for item in dnt.get("paths", []) or [])
    ) or set(_text(item) for item in scope.get("surface_ids", []) or []).intersection(
        set(_text(item) for item in dnt.get("surface_ids", []) or [])
    ):
        errors.append({"code": APPROVAL_DNT_VIOLATION, "reason": "approved mutation scope overlaps protected DNT authority"})
    constraints = binding.get("authority_constraints", {}) if isinstance(binding.get("authority_constraints"), dict) else {}
    if constraints.get("new_owner") or constraints.get("owner_migration") or constraints.get("authority_change"):
        errors.append({"code": APPROVAL_AUTHORITY_CHANGE, "reason": "approval cannot introduce a new authority or owner change"})
    return errors


def create_plan_approval_request(plan: dict[str, Any], state: dict[str, Any] | None = None, **metadata: Any) -> PlanApprovalRequest:
    """Create a request only for a complete, fresh, terminal Stage 6B plan."""
    value = _copy(plan) if isinstance(plan, dict) else {}
    current = _copy(state) if isinstance(state, dict) else {}
    if metadata:
        current.update(_copy(metadata))
    binding = build_approval_authority_binding(value, current)
    errors = _request_precondition_errors(value, current, binding)
    if errors:
        raise ApprovalRequestError(
            errors[0]["code"],
            "; ".join(item["reason"] for item in errors),
            details=errors,
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": APPROVAL_REQUEST_READY,
        "terminal_state": PLAN_APPROVAL_REQUIRED,
        "request_hash": "",
        "binding": binding,
        **{key: _copy(binding.get(key)) for key in _BINDING_FIELDS},
        "canonical_plan_id": binding["canonical_plan_id"],
        "canonical_plan_hash": binding["canonical_plan_hash"],
        "requirement_id": binding.get("requirement_id"),
        "preconditions": {
            "final_plan_validator": "PASS",
            "coverage": "COMPLETE",
            "freshness": "PASS",
            "stage4_contractability": "PASS",
            "terminal_state": PLAN_APPROVAL_REQUIRED,
        },
    }
    record["request_hash"] = canonical_hash(_without(record, "request_hash"))
    return _freeze_record(PlanApprovalRequest, record)


build_plan_approval_request = create_plan_approval_request
make_plan_approval_request = create_plan_approval_request


def validate_plan_approval_request(request: Any) -> dict[str, Any]:
    """Validate request integrity without reading or changing external state."""
    value = request if isinstance(request, dict) else {}
    errors = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("approval request schema version is invalid")
    if value.get("status") != APPROVAL_REQUEST_READY:
        errors.append("approval request is not ready")
    if value.get("terminal_state") != PLAN_APPROVAL_REQUIRED:
        errors.append("approval request terminal state is invalid")
    binding = value.get("binding") if isinstance(value.get("binding"), dict) else {}
    for field in _BINDING_FIELDS:
        if field in value and value.get(field) != binding.get(field):
            errors.append(f"approval request {field} does not match binding")
    if not value.get("request_hash"):
        errors.append("approval request hash is missing")
    elif value.get("request_hash") != canonical_hash(_without(value, "request_hash")):
        errors.append("approval request hash does not match content")
    return {"valid": not errors, "status": APPROVAL_REQUEST_READY if not errors else APPROVAL_INVALID, "errors": errors[:30]}


def make_explicit_user_approval_event(
    request: PlanApprovalRequest | dict[str, Any],
    event_reference: str,
    *,
    source: str = EXPLICIT_USER_APPROVAL,
) -> ExplicitUserApprovalEvent:
    """Build an explicit event from a caller-provided opaque reference."""
    request_hash = _text(request.get("request_hash")) if isinstance(request, dict) else ""
    value = {
        "schema_version": SCHEMA_VERSION,
        "event_type": "PLAN_APPROVAL",
        "action": "APPROVE",
        "approved": True,
        "request_hash": request_hash,
        "event_reference": _text(event_reference),
        "source": _text(source) or EXPLICIT_USER_APPROVAL,
    }
    return _freeze_record(ExplicitUserApprovalEvent, value)


def make_test_explicit_user_approval_event(
    request: PlanApprovalRequest | dict[str, Any],
    event_reference: str = "TEST-EXPLICIT-APPROVAL-001",
) -> ExplicitUserApprovalEvent:
    """Return a deterministic provider-free fixture, never used implicitly."""
    return make_explicit_user_approval_event(
        request, event_reference, source=TEST_EXPLICIT_USER_APPROVAL,
    )


explicit_user_approval_event = make_explicit_user_approval_event
test_explicit_user_approval_event = make_test_explicit_user_approval_event


def _normalize_approval_event(
    request: PlanApprovalRequest | dict[str, Any], approval_event: Any,
    event_reference: str | None = None,
) -> dict[str, Any]:
    if approval_event is None and _text(event_reference):
        approval_event = make_explicit_user_approval_event(request, _text(event_reference))
    value = _copy(approval_event) if isinstance(approval_event, dict) else {}
    if not value:
        raise ApprovalReceiptError(APPROVAL_INVALID, "an explicit user approval event is required")
    if value.get("approved") is not True or _text(value.get("action")).upper() != "APPROVE":
        raise ApprovalReceiptError(APPROVAL_INVALID, "approval event does not explicitly approve the request")
    if _text(value.get("event_reference")) == "":
        raise ApprovalReceiptError(APPROVAL_INVALID, "approval event reference is required")
    if _text(value.get("source")) not in {EXPLICIT_USER_APPROVAL, TEST_EXPLICIT_USER_APPROVAL}:
        raise ApprovalReceiptError(APPROVAL_INVALID, "approval event source is not an explicit approval boundary")
    request_hash = _text(request.get("request_hash")) if isinstance(request, dict) else ""
    if _text(value.get("request_hash")) != request_hash:
        raise ApprovalReceiptError(APPROVAL_REQUEST_INVALID, "approval event is bound to a different request")
    return value


def _receipt_from(request: dict[str, Any], event: dict[str, Any]) -> dict[str, Any]:
    binding = request.get("binding") if isinstance(request.get("binding"), dict) else {}
    event_reference = _text(event.get("event_reference"))
    approval_id = "APPROVAL-" + canonical_hash({
        "approval_request_hash": request.get("request_hash"),
        "approval_event_reference": event_reference,
    })[:16].upper()
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "status": APPROVAL_RECORDED,
        "approval_id": approval_id,
        "approval_request_hash": request.get("request_hash"),
        "canonical_plan_id": binding.get("canonical_plan_id"),
        "canonical_plan_hash": binding.get("canonical_plan_hash"),
        "approved_mutation_scope_digest": binding.get("mutation_scope_digest"),
        "approved_dnt_digest": binding.get("dnt_digest"),
        "approved_dependency_digest": binding.get("dependency_digest"),
        "approved_verification_digest": binding.get("verification_contract_digest"),
        "approved_interface_binding_digest": binding.get("interface_binding_digest"),
        "approved_requirement_coverage_digest": binding.get("requirement_coverage_digest"),
        "approved_brain_hash": binding.get("brain_hash"),
        "approved_subject_aggregate_hash": binding.get("subject_aggregate_hash"),
        "approved_planning_context_hash": binding.get("planning_context_hash"),
        "approved_source_bindings": _copy(binding.get("source_bindings", {})),
        "approved_requirement_ids": _copy(binding.get("requirement_ids", [])),
        "approved_task_id": binding.get("task_id"),
        "approved_authority_constraints_digest": binding.get("authority_constraints_digest"),
        "approved_challenger_reconciliation_hash": binding.get("challenger_reconciliation_hash"),
        "approval_source": EXPLICIT_USER_APPROVAL,
        "approval_event_reference": event_reference,
        "approval_event_source": _text(event.get("source")),
        "receipt_hash": "",
    }
    receipt["receipt_hash"] = canonical_hash(_without(receipt, "receipt_hash"))
    return receipt


def record_plan_approval(
    request: PlanApprovalRequest | dict[str, Any],
    approval_event: ExplicitUserApprovalEvent | dict[str, Any] | None = None,
    *,
    event_reference: str | None = None,
    idempotency_store: dict[str, Any] | None = None,
) -> PlanApprovalReceipt:
    """Record exactly one explicit approval; repeated event recording is idempotent."""
    request_check = validate_plan_approval_request(request)
    if not request_check.get("valid"):
        raise ApprovalReceiptError(APPROVAL_REQUEST_INVALID, "; ".join(request_check.get("errors", [])), request_check.get("errors"))
    event = _normalize_approval_event(request, approval_event, event_reference)
    key = canonical_hash({
        "approval_request_hash": request.get("request_hash"),
        "approval_event_reference": event.get("event_reference"),
    })
    if isinstance(idempotency_store, dict) and key in idempotency_store:
        stored = idempotency_store[key]
        check = validate_plan_approval_receipt(stored, request)
        if check.get("valid"):
            return _freeze_record(PlanApprovalReceipt, _copy(stored))
    receipt = _receipt_from(request, event)
    if isinstance(idempotency_store, dict):
        idempotency_store[key] = _copy(receipt)
    return _freeze_record(PlanApprovalReceipt, receipt)


record_explicit_user_approval = record_plan_approval
create_plan_approval_receipt = record_plan_approval


def validate_plan_approval_receipt(
    receipt: PlanApprovalReceipt | dict[str, Any],
    request: PlanApprovalRequest | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate receipt integrity and, when supplied, its exact request binding."""
    value = receipt if isinstance(receipt, dict) else {}
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("approval receipt schema version is invalid")
    if value.get("status") != APPROVAL_RECORDED:
        errors.append("approval receipt is not recorded")
    if _text(value.get("approval_source")) != EXPLICIT_USER_APPROVAL:
        errors.append("approval receipt source is not EXPLICIT_USER_APPROVAL")
    if not _text(value.get("approval_event_reference")):
        errors.append("approval event reference is missing")
    if not _text(value.get("receipt_hash")):
        errors.append("approval receipt hash is missing")
    elif value.get("receipt_hash") != canonical_hash(_without(value, "receipt_hash")):
        errors.append("approval receipt hash does not match content")
    if isinstance(request, dict):
        if value.get("approval_request_hash") != request.get("request_hash"):
            errors.append("approval receipt request hash does not match request")
        binding = request.get("binding") if isinstance(request.get("binding"), dict) else {}
        expected = {
            "canonical_plan_id": binding.get("canonical_plan_id"),
            "canonical_plan_hash": binding.get("canonical_plan_hash"),
            "approved_mutation_scope_digest": binding.get("mutation_scope_digest"),
            "approved_dnt_digest": binding.get("dnt_digest"),
            "approved_dependency_digest": binding.get("dependency_digest"),
            "approved_verification_digest": binding.get("verification_contract_digest"),
            "approved_interface_binding_digest": binding.get("interface_binding_digest"),
            "approved_requirement_coverage_digest": binding.get("requirement_coverage_digest"),
            "approved_brain_hash": binding.get("brain_hash"),
            "approved_subject_aggregate_hash": binding.get("subject_aggregate_hash"),
            "approved_planning_context_hash": binding.get("planning_context_hash"),
            "approved_requirement_ids": binding.get("requirement_ids"),
            "approved_task_id": binding.get("task_id"),
            "approved_authority_constraints_digest": binding.get("authority_constraints_digest"),
            "approved_challenger_reconciliation_hash": binding.get("challenger_reconciliation_hash"),
        }
        for field, expected_value in expected.items():
            if value.get(field) != expected_value:
                errors.append(f"approval receipt {field} does not match request")
    return {
        "valid": not errors,
        "status": APPROVAL_RECORDED if not errors else APPROVAL_INVALID,
        "code": None if not errors else APPROVAL_RECEIPT_INVALID,
        "errors": errors[:30],
        "approval_id": value.get("approval_id"),
    }


def _receipt_binding_values(receipt: dict[str, Any]) -> dict[str, Any]:
    return {
        "canonical_plan_id": receipt.get("canonical_plan_id"),
        "canonical_plan_hash": receipt.get("canonical_plan_hash"),
        "task_id": receipt.get("approved_task_id"),
        "requirement_ids": _copy(receipt.get("approved_requirement_ids", [])),
        "planning_context_hash": receipt.get("approved_planning_context_hash"),
        "brain_hash": receipt.get("approved_brain_hash"),
        "subject_aggregate_hash": receipt.get("approved_subject_aggregate_hash"),
        "source_bindings": _copy(receipt.get("approved_source_bindings", {})),
        "mutation_scope_digest": receipt.get("approved_mutation_scope_digest"),
        "dnt_digest": receipt.get("approved_dnt_digest"),
        "dependency_digest": receipt.get("approved_dependency_digest"),
        "verification_contract_digest": receipt.get("approved_verification_digest"),
        "interface_binding_digest": receipt.get("approved_interface_binding_digest"),
        "requirement_coverage_digest": receipt.get("approved_requirement_coverage_digest"),
        "authority_constraints_digest": receipt.get("approved_authority_constraints_digest"),
        "challenger_reconciliation_hash": receipt.get("approved_challenger_reconciliation_hash"),
    }


def _mismatch(
    code: str, field: str, approved: Any, current: Any,
) -> dict[str, Any]:
    return {
        "code": code,
        "field": field,
        "approved": _copy(approved),
        "current": _copy(current),
    }


def _current_binding(
    receipt: dict[str, Any], current_plan: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
) -> dict[str, Any]:
    state = _copy(current_state) if isinstance(current_state, dict) else {}
    plan = _copy(current_plan) if isinstance(current_plan, dict) else {}
    if not plan and isinstance(state.get("plan"), dict):
        plan = _copy(state["plan"])
    if not plan:
        # A direct current authority binding is useful for isolated negative
        # fixtures and still remains data-only; no state is refreshed here.
        direct = state.get("authority_binding")
        if isinstance(direct, dict):
            return _copy(direct)
    if not plan:
        return {}
    binding = build_approval_authority_binding(plan, state)
    # Revalidation must detect content tampering even when a caller leaves the
    # old plan_id/plan_hash fields in place.  The current effective identity is
    # therefore derived from the current canonical contents, never trusted from
    # a mutable label alone.
    try:
        computed_hash = stage3.plan_content_hash(plan)
    except Exception:
        computed_hash = ""
    if computed_hash and computed_hash != _text(plan.get("plan_hash")):
        binding["canonical_plan_hash"] = computed_hash
    return binding


def pre_execution_approval_revalidation(
    receipt: PlanApprovalReceipt | dict[str, Any],
    current_plan: dict[str, Any] | None = None,
    current_state: dict[str, Any] | None = None,
    *,
    request: PlanApprovalRequest | dict[str, Any] | None = None,
    **kwargs: Any,
) -> PreExecutionApprovalRevalidation:
    """Compare every approval-bound semantic input with the current state."""
    state = _copy(current_state) if isinstance(current_state, dict) else {}
    state.update(_copy(kwargs))
    value = receipt if isinstance(receipt, dict) else {}
    receipt_check = validate_plan_approval_receipt(value, request)
    if not receipt_check.get("valid"):
        return _freeze_record(PreExecutionApprovalRevalidation, {
            "schema_version": SCHEMA_VERSION,
            "status": APPROVAL_INVALID,
            "terminal_state": EXECUTION_AUTHORIZATION_BLOCKED,
            "valid": False,
            "code": APPROVAL_RECEIPT_INVALID,
            "mismatches": [{"code": APPROVAL_RECEIPT_INVALID, "field": "receipt", "details": receipt_check.get("errors", [])}],
            "errors": receipt_check.get("errors", []),
            "receipt_hash": value.get("receipt_hash"),
        })
    approved = _receipt_binding_values(value)
    current = _current_binding(value, current_plan, state)
    mismatches: list[dict[str, Any]] = []
    if not current:
        mismatches.append(_mismatch(APPROVAL_STALE, "current_state", approved, {}))
    else:
        if approved.get("canonical_plan_id") != current.get("canonical_plan_id"):
            mismatches.append(_mismatch(APPROVAL_PLAN_HASH_MISMATCH, "canonical_plan_id", approved.get("canonical_plan_id"), current.get("canonical_plan_id")))
        if approved.get("canonical_plan_hash") != current.get("canonical_plan_hash"):
            mismatches.append(_mismatch(APPROVAL_PLAN_HASH_MISMATCH, "canonical_plan_hash", approved.get("canonical_plan_hash"), current.get("canonical_plan_hash")))
            mismatches.append(_mismatch(PLAN_HASH_MISMATCH, "canonical_plan_hash", approved.get("canonical_plan_hash"), current.get("canonical_plan_hash")))
        comparisons = (
            ("task_id", APPROVAL_TASK_MISMATCH),
            ("requirement_ids", APPROVAL_REQUIREMENT_MISMATCH),
            ("brain_hash", APPROVAL_BRAIN_STALE),
            ("subject_aggregate_hash", APPROVAL_SUBJECT_STALE),
            ("planning_context_hash", APPROVAL_PLANNING_CONTEXT_MISMATCH),
            ("mutation_scope_digest", APPROVAL_MUTATION_SCOPE_MISMATCH),
            ("dnt_digest", APPROVAL_DNT_MISMATCH),
            ("dependency_digest", APPROVAL_DEPENDENCY_MISMATCH),
            ("verification_contract_digest", APPROVAL_VERIFICATION_MISMATCH),
            ("interface_binding_digest", APPROVAL_INTERFACE_MISMATCH),
            ("requirement_coverage_digest", APPROVAL_REQUIREMENT_MISMATCH),
            ("authority_constraints_digest", APPROVAL_AUTHORITY_CONSTRAINT_MISMATCH),
            ("challenger_reconciliation_hash", APPROVAL_RECONCILIATION_MISMATCH),
            ("source_bindings", APPROVAL_SOURCE_BINDING_MISMATCH),
        )
        for field, code in comparisons:
            if approved.get(field) != current.get(field):
                mismatches.append(_mismatch(code, field, approved.get(field), current.get(field)))
        reconciliation = current.get("reconciliation") if isinstance(current.get("reconciliation"), dict) else {}
        if int(reconciliation.get("open_blocking_count", 0) or 0) or reconciliation.get("open_blocking_challenge_ids"):
            mismatches.append(_mismatch(APPROVAL_RECONCILIATION_MISMATCH, "open_blocking_challenge_ids", [], reconciliation.get("open_blocking_challenge_ids", [])))
        if not _freshness_pass(current_plan or state.get("plan", {}), state):
            mismatches.append(_mismatch(APPROVAL_FRESHNESS_MISMATCH, "freshness", True, False))
        if not _contractability_pass(current_plan or state.get("plan", {}), state):
            mismatches.append(_mismatch(APPROVAL_CONTRACTABILITY_MISMATCH, "stage4_contractability", True, False))
    codes = _ordered_unique(item.get("code") for item in mismatches)
    valid = not mismatches
    return _freeze_record(PreExecutionApprovalRevalidation, {
        "schema_version": SCHEMA_VERSION,
        "status": APPROVAL_RECORDED if valid else REAPPROVAL_REQUIRED,
        "terminal_state": EXECUTION_AUTHORIZATION_READY if valid else REAPPROVAL_REQUIRED,
        "valid": valid,
        "code": None if valid else (codes[0] if codes else REAPPROVAL_REQUIRED),
        "mismatches": mismatches,
        "errors": [f"{item.get('code')}: {item.get('field')}" for item in mismatches],
        "receipt_hash": value.get("receipt_hash"),
        "current_binding": current,
        "approved_binding": approved,
    })


revalidate_pre_execution_approval = pre_execution_approval_revalidation
pre_execution_revalidate = pre_execution_approval_revalidation


def _stage4_binding(
    authorization: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "approved_plan_hash": authorization.get("canonical_plan_hash"),
        "approved_plan_id": authorization.get("canonical_plan_id"),
        "approval_receipt_hash": authorization.get("approval_receipt_hash"),
        "execution_authorization_hash": authorization.get("authorization_hash"),
        "approved_task_id": authorization.get("task_id"),
        "approved_requirement_ids": _copy(authorization.get("requirement_ids", [])),
        "approved_subject_hash": authorization.get("current_subject_hash"),
        "approved_brain_hash": authorization.get("current_brain_hash"),
        "approved_planning_context_hash": authorization.get("planning_context_hash"),
        "approved_mutation_scope_digest": authorization.get("mutation_scope_digest"),
        "approved_dnt_digest": authorization.get("dnt_digest"),
        "approved_dependency_digest": authorization.get("dependency_digest"),
        "approved_verification_digest": authorization.get("verification_digest"),
        "approved_interface_binding_digest": authorization.get("interface_binding_digest"),
        "approved_requirement_coverage_digest": authorization.get("requirement_coverage_digest"),
        "approved_challenger_reconciliation_hash": authorization.get("challenger_reconciliation_hash"),
        "stage4_contract_graph_hash": authorization.get("stage4_contract_graph_hash"),
        "stage4_dependency_graph_digest": authorization.get("stage4_dependency_graph_digest"),
        "execution_invariant_set_hash": authorization.get("execution_invariant_set_hash"),
        "execution_invariant_ids": _copy(authorization.get("execution_invariant_ids", [])),
    }


def _authorization_hash_payload(value: dict[str, Any]) -> dict[str, Any]:
    payload = _without(value, "authorization_hash")
    binding = payload.get("binding")
    if isinstance(binding, dict):
        binding = _copy(binding)
        # The binding carries the hash as a reference; excluding this one
        # self-reference keeps the proof hash canonical and recomputable.
        binding["execution_authorization_hash"] = ""
        payload["binding"] = binding
    return payload


def create_approved_execution_authorization(
    receipt: PlanApprovalReceipt | dict[str, Any],
    revalidation: PreExecutionApprovalRevalidation | dict[str, Any],
    *,
    request: PlanApprovalRequest | dict[str, Any] | None = None,
    stage4_graph: dict[str, Any] | None = None,
    current_state: dict[str, Any] | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
) -> ApprovedExecutionAuthorization:
    """Grant only the immutable, provider-free authority proof after revalidation."""
    receipt_value = receipt if isinstance(receipt, dict) else {}
    revalidation_value = revalidation if isinstance(revalidation, dict) else {}
    receipt_check = validate_plan_approval_receipt(receipt_value, request)
    if not receipt_check.get("valid"):
        raise ExecutionAuthorizationError(APPROVAL_RECEIPT_INVALID, "; ".join(receipt_check.get("errors", [])))
    if revalidation_value.get("valid") is not True or revalidation_value.get("status") not in {APPROVAL_RECORDED, EXECUTION_AUTHORIZATION_READY}:
        raise ExecutionAuthorizationError(
            str(revalidation_value.get("code") or REAPPROVAL_REQUIRED),
            "; ".join(revalidation_value.get("errors", [])) or "pre-execution approval revalidation did not pass",
            revalidation_value.get("mismatches", []),
        )
    binding = revalidation_value.get("current_binding") if isinstance(revalidation_value.get("current_binding"), dict) else {}
    if not binding:
        binding = _receipt_binding_values(receipt_value)
    graph_hash = _text((stage4_graph or {}).get("graph_hash")) if isinstance(stage4_graph, dict) else ""
    if not graph_hash:
        graph_hash = canonical_hash({
            "plan_id": binding.get("canonical_plan_id"),
            "plan_hash": binding.get("canonical_plan_hash"),
            "mutation_scope_digest": binding.get("mutation_scope_digest"),
            "dnt_digest": binding.get("dnt_digest"),
            "dependency_digest": binding.get("dependency_digest"),
            "verification_digest": binding.get("verification_contract_digest"),
            "interface_binding_digest": binding.get("interface_binding_digest"),
        })
    dependency_graph = (stage4_graph or {}).get("nodes", []) if isinstance(stage4_graph, dict) else []
    dependency_digest = canonical_hash([
        {"execution_contract_id": item.get("execution_contract_id"), "dependencies": list(item.get("dependencies", []) or [])}
        for item in dependency_graph if isinstance(item, dict)
    ]) if dependency_graph else binding.get("dependency_digest")
    invariant_hash = ""
    invariant_ids: list[str] = []
    if execution_invariant_set is not None:
        invariant_check = invariant.validate_execution_invariant_set(execution_invariant_set)
        if not invariant_check.get("valid"):
            raise ExecutionAuthorizationError(
                str(invariant_check.get("code") or EXECUTION_INVARIANT_INVALID),
                "; ".join(invariant_check.get("errors", [])) or "execution invariant set is invalid",
                invariant_check.get("errors", []),
            )
        invariant_hash = str(execution_invariant_set.get("invariant_set_hash") or "")
        invariant_ids = [str(item) for item in execution_invariant_set.get("invariant_ids", []) or []]
    elif binding.get("execution_invariant_set_hash"):
        raise ExecutionAuthorizationError(
            EXECUTION_INVARIANT_SET_REQUIRED,
            "current approval-bound authorization references an invariant set that was not supplied",
        )
    record = {
        "schema_version": SCHEMA_VERSION,
        "status": EXECUTION_AUTHORIZATION_READY,
        "terminal_state": EXECUTION_AUTHORIZATION_READY,
        "authorization_id": "",
        "task_id": binding.get("task_id"),
        "requirement_ids": _copy(binding.get("requirement_ids", [])),
        "canonical_plan_id": binding.get("canonical_plan_id"),
        "canonical_plan_hash": binding.get("canonical_plan_hash"),
        "approval_receipt_hash": receipt_value.get("receipt_hash"),
        "current_subject_hash": binding.get("subject_aggregate_hash"),
        "current_brain_hash": binding.get("brain_hash"),
        "planning_context_hash": binding.get("planning_context_hash"),
        "mutation_scope_digest": binding.get("mutation_scope_digest"),
        "dnt_digest": binding.get("dnt_digest"),
        "dependency_digest": binding.get("dependency_digest"),
        "verification_digest": binding.get("verification_contract_digest"),
        "interface_binding_digest": binding.get("interface_binding_digest"),
        "requirement_coverage_digest": binding.get("requirement_coverage_digest"),
        "challenger_reconciliation_hash": binding.get("challenger_reconciliation_hash"),
        "execution_invariant_set_hash": invariant_hash,
        "execution_invariant_ids": invariant_ids,
        "source_bindings": _copy(binding.get("source_bindings", {})),
        "authority_constraints_digest": binding.get("authority_constraints_digest"),
        "approved_mutation_scope": _copy(binding.get("mutation_scope", {})),
        "approved_dnt": _copy(binding.get("dnt", {})),
        "approved_dependencies": _copy(binding.get("dependencies", {})),
        "approved_verification_contracts": _copy(binding.get("verification_contracts", [])),
        "approved_interface_binding": _copy(binding.get("interface_binding", {})),
        "stage4_contract_graph_hash": graph_hash,
        "stage4_dependency_graph_digest": dependency_digest,
        "approval_status": APPROVAL_RECORDED,
        "binding": {},
        "authorization_hash": "",
    }
    record["authorization_id"] = "AUTH-" + canonical_hash({
        "approval_receipt_hash": record["approval_receipt_hash"],
        "canonical_plan_hash": record["canonical_plan_hash"],
        "stage4_contract_graph_hash": graph_hash,
        "execution_invariant_set_hash": invariant_hash,
    })[:16].upper()
    record["binding"] = _stage4_binding(record)
    record["authorization_hash"] = canonical_hash(_authorization_hash_payload(record))
    record["binding"]["execution_authorization_hash"] = record["authorization_hash"]
    return _freeze_record(ApprovedExecutionAuthorization, record)


create_pre_execution_authorization = create_approved_execution_authorization
approved_execution_authorization = create_approved_execution_authorization


def validate_approved_execution_authorization(
    authorization: ApprovedExecutionAuthorization | dict[str, Any],
    receipt: PlanApprovalReceipt | dict[str, Any] | None = None,
    revalidation: PreExecutionApprovalRevalidation | dict[str, Any] | None = None,
    *,
    request: PlanApprovalRequest | dict[str, Any] | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate an authorization object and its optional upstream proofs."""
    value = authorization if isinstance(authorization, dict) else {}
    errors: list[dict[str, Any]] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append({"code": APPROVAL_INVALID, "field": "schema_version"})
    if value.get("status") != EXECUTION_AUTHORIZATION_READY:
        errors.append({"code": EXECUTION_AUTHORIZATION_BLOCKED, "field": "status"})
    if not value.get("authorization_hash") or value.get("authorization_hash") != canonical_hash(_authorization_hash_payload(value)):
        errors.append({"code": APPROVAL_INVALID, "field": "authorization_hash"})
    binding = value.get("binding") if isinstance(value.get("binding"), dict) else {}
    if binding.get("execution_authorization_hash") != value.get("authorization_hash"):
        errors.append({"code": APPROVAL_INVALID, "field": "binding.execution_authorization_hash"})
    for field, binding_field in (
        ("canonical_plan_hash", "approved_plan_hash"),
        ("approval_receipt_hash", "approval_receipt_hash"),
        ("current_subject_hash", "approved_subject_hash"),
        ("current_brain_hash", "approved_brain_hash"),
        ("mutation_scope_digest", "approved_mutation_scope_digest"),
        ("dnt_digest", "approved_dnt_digest"),
        ("dependency_digest", "approved_dependency_digest"),
        ("verification_digest", "approved_verification_digest"),
        ("interface_binding_digest", "approved_interface_binding_digest"),
        ("stage4_contract_graph_hash", "stage4_contract_graph_hash"),
        ("execution_invariant_set_hash", "execution_invariant_set_hash"),
    ):
        if binding.get(binding_field) != value.get(field):
            errors.append({"code": APPROVAL_INVALID, "field": field})
    authorized_invariant_hash = value.get("execution_invariant_set_hash")
    if execution_invariant_set is not None:
        invariant_check = invariant.validate_execution_invariant_set(execution_invariant_set)
        if not invariant_check.get("valid"):
            errors.append({
                "code": invariant_check.get("code") or EXECUTION_INVARIANT_INVALID,
                "field": "execution_invariant_set",
                "details": invariant_check.get("errors", []),
            })
        elif not authorized_invariant_hash or authorized_invariant_hash != execution_invariant_set.get("invariant_set_hash"):
            errors.append({"code": EXECUTION_INVARIANT_INVALID, "field": "execution_invariant_set_hash"})
    elif authorized_invariant_hash:
        # Structural authorization validation remains possible without
        # re-reading the subject.  Stage 4 compilation still requires the
        # exact immutable set so it can project semantic facts to the Worker.
        if value.get("execution_invariant_ids") != binding.get("execution_invariant_ids", []):
            errors.append({"code": APPROVAL_INVALID, "field": "execution_invariant_ids"})
    if isinstance(receipt, dict):
        receipt_check = validate_plan_approval_receipt(receipt, request)
        if not receipt_check.get("valid"):
            errors.append({"code": APPROVAL_RECEIPT_INVALID, "field": "receipt", "details": receipt_check.get("errors", [])})
        elif value.get("approval_receipt_hash") != receipt.get("receipt_hash"):
            errors.append({"code": APPROVAL_RECEIPT_INVALID, "field": "approval_receipt_hash"})
    if isinstance(revalidation, dict):
        if revalidation.get("valid") is not True:
            errors.append({"code": REAPPROVAL_REQUIRED, "field": "revalidation", "details": revalidation.get("mismatches", [])})
        elif value.get("approval_receipt_hash") != revalidation.get("receipt_hash"):
            errors.append({"code": APPROVAL_RECEIPT_INVALID, "field": "revalidation.receipt_hash"})
    return {
        "valid": not errors,
        "status": EXECUTION_AUTHORIZATION_READY if not errors else EXECUTION_AUTHORIZATION_BLOCKED,
        "code": None if not errors else errors[0].get("code"),
        "errors": errors[:30],
        "authorization_hash": value.get("authorization_hash"),
    }


def worker_authorization_gate(
    authorization: ApprovedExecutionAuthorization | dict[str, Any] | None,
    receipt: PlanApprovalReceipt | dict[str, Any] | None = None,
    revalidation: PreExecutionApprovalRevalidation | dict[str, Any] | None = None,
    *,
    request: PlanApprovalRequest | dict[str, Any] | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a gate decision only; this function never invokes a Worker."""
    if not isinstance(authorization, dict):
        return {
            "allowed": False, "status": EXECUTION_AUTHORIZATION_BLOCKED,
            "terminal_state": EXECUTION_AUTHORIZATION_BLOCKED,
            "code": REAPPROVAL_REQUIRED, "errors": ["current execution authorization is missing"],
        }
    checked = validate_approved_execution_authorization(
        authorization, receipt, revalidation, request=request,
        execution_invariant_set=execution_invariant_set,
    )
    if not checked.get("valid"):
        return {
            "allowed": False,
            "status": EXECUTION_AUTHORIZATION_BLOCKED,
            "terminal_state": EXECUTION_AUTHORIZATION_BLOCKED,
            "code": checked.get("code") or REAPPROVAL_REQUIRED,
            "errors": checked.get("errors", []),
            "authorization_hash": authorization.get("authorization_hash"),
        }
    return {
        "allowed": True,
        "status": EXECUTION_AUTHORIZATION_READY,
        "terminal_state": EXECUTION_AUTHORIZATION_READY,
        "code": None,
        "errors": [],
        "authorization_hash": authorization.get("authorization_hash"),
    }


validate_worker_authorization = worker_authorization_gate
worker_gate = worker_authorization_gate


def _contract_authority_fields(authorization: dict[str, Any]) -> dict[str, Any]:
    binding = _stage4_binding(authorization)
    # Stage 4 receives an ordinary mapping.  The values are compact hashes and
    # canonical references, never model transcripts or complete upstream data.
    return binding


def validate_approval_bound_contracts(
    contracts: Iterable[dict[str, Any]] | None,
    authorization: ApprovedExecutionAuthorization | dict[str, Any],
    *,
    plan: dict[str, Any] | None = None,
    graph: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Audit Stage 4 contracts for exact approval-bound authority equality."""
    auth = authorization if isinstance(authorization, dict) else {}
    gate = worker_authorization_gate(auth)
    errors: list[dict[str, Any]] = []
    if not gate.get("allowed"):
        errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": "authorization", "details": gate.get("errors", [])})
    expected = _contract_authority_fields(auth)
    contract_list = [item for item in (contracts or []) if isinstance(item, dict)]
    if not contract_list:
        errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": "contracts", "reason": "no contracts supplied"})
    try:
        from hivo import execution_contracts as stage4
    except ImportError:  # pragma: no cover - package import is available in production
        stage4 = None
    approved_paths: set[str] = set()
    approved_surfaces: set[str] = set()
    approved_dnt_paths: set[str] = set()
    approved_dnt_surfaces: set[str] = set()
    actual_interfaces: set[str] = set()
    actual_verification_texts: set[str] = set()
    for contract in contract_list:
        for field, expected_field in (
            ("plan_hash", "approved_plan_hash"),
            ("approved_plan_hash", "approved_plan_hash"),
            ("approval_receipt_hash", "approval_receipt_hash"),
            ("execution_authorization_hash", "execution_authorization_hash"),
            ("approved_mutation_scope_digest", "approved_mutation_scope_digest"),
            ("approved_dnt_digest", "approved_dnt_digest"),
            ("approved_dependency_digest", "approved_dependency_digest"),
            ("approved_verification_digest", "approved_verification_digest"),
            ("approved_interface_binding_digest", "approved_interface_binding_digest"),
            ("stage4_contract_graph_hash", "stage4_contract_graph_hash"),
            ("execution_invariant_set_hash", "execution_invariant_set_hash"),
        ):
            expected_value = expected.get(expected_field)
            if field == "execution_invariant_set_hash" and expected_value in (None, ""):
                continue
            if contract.get(field) != expected_value:
                errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": field, "contract_id": contract.get("execution_contract_id")})
        approved_paths.update(_text(item).casefold() for item in contract.get("allowed_mutation_paths", []) or [])
        approved_surfaces.update(_text(item) for item in contract.get("allowed_mutation_surface_ids", []) or [])
        approved_dnt_paths.update(_text(item).casefold() for item in contract.get("global_do_not_touch", []) or [])
        approved_dnt_surfaces.update(_text(item) for item in contract.get("global_do_not_touch_surface_ids", []) or [])
        actual_interfaces.update(_text(item) for item in contract.get("interfaces_to_reuse", []) or [])
        actual_verification_texts.update(
            _text(item) for item in contract.get("test_contract", []) or [] if _text(item)
        )
        if stage4 is not None and contract.get("contract_hash") != stage4.deterministic_hash(_without(contract, "contract_hash")):
            errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": "contract_hash", "contract_id": contract.get("execution_contract_id")})
        if set(_text(item).casefold() for item in contract.get("allowed_mutation_paths", []) or []).intersection(
            set(_text(item).casefold() for item in contract.get("global_do_not_touch", []) or [])
        ):
            errors.append({"code": APPROVAL_DNT_VIOLATION, "field": "allowed_mutation_paths", "contract_id": contract.get("execution_contract_id")})
        if set(_text(item) for item in contract.get("allowed_mutation_surface_ids", []) or []).intersection(
            set(_text(item) for item in contract.get("global_do_not_touch_surface_ids", []) or [])
        ):
            errors.append({"code": APPROVAL_DNT_VIOLATION, "field": "allowed_mutation_surface_ids", "contract_id": contract.get("execution_contract_id")})
        if auth.get("execution_invariant_set_hash"):
            if contract.get("execution_invariant_ids") != list(auth.get("execution_invariant_ids", []) or []):
                errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": "execution_invariant_ids", "contract_id": contract.get("execution_contract_id")})
    approved_scope = auth.get("approved_mutation_scope") if isinstance(auth.get("approved_mutation_scope"), dict) else {}
    expected_paths = {_text(item).casefold() for item in approved_scope.get("paths", []) or []}
    expected_surfaces = set(_text(item) for item in approved_scope.get("surface_ids", []) or [])
    if approved_paths != expected_paths:
        errors.append({"code": APPROVAL_MUTATION_SCOPE_MISMATCH, "field": "contract.allowed_mutation_paths", "approved": sorted(expected_paths), "current": sorted(approved_paths)})
    if approved_surfaces != expected_surfaces:
        errors.append({"code": APPROVAL_MUTATION_SCOPE_MISMATCH, "field": "contract.allowed_mutation_surface_ids", "approved": sorted(expected_surfaces), "current": sorted(approved_surfaces)})
    approved_dnt = auth.get("approved_dnt") if isinstance(auth.get("approved_dnt"), dict) else {}
    expected_dnt_paths = {_text(item).casefold() for item in approved_dnt.get("paths", []) or []}
    expected_dnt_surfaces = set(_text(item) for item in approved_dnt.get("surface_ids", []) or [])
    if approved_dnt_paths != expected_dnt_paths or approved_dnt_surfaces != expected_dnt_surfaces:
        errors.append({"code": APPROVAL_DNT_MISMATCH, "field": "contract.global_do_not_touch"})
    approved_interfaces = auth.get("approved_interface_binding") if isinstance(auth.get("approved_interface_binding"), dict) else {}
    expected_interfaces = set(_text(item) for item in approved_interfaces.get("interfaces", []) or [])
    allowed_derived_interfaces = set(_text(item) for item in approved_interfaces.get("derived_symbols", []) or [])
    expected_interface_surfaces = set(_text(item) for item in approved_interfaces.get("surface_ids", []) or [])
    actual_interface_surfaces = {
        _text(item) for contract in contract_list for item in contract.get("interface_surface_ids", []) or []
    }
    if not actual_interfaces.issubset(expected_interfaces | allowed_derived_interfaces) or not expected_interfaces.issubset(actual_interfaces) or actual_interface_surfaces != expected_interface_surfaces:
        errors.append({"code": APPROVAL_INTERFACE_MISMATCH, "field": "contract.interfaces_to_reuse"})
    approved_verifications = auth.get("approved_verification_contracts")
    if isinstance(approved_verifications, list):
        expected_verification_texts = {
            _text(text) for item in approved_verifications if isinstance(item, dict)
            for text in item.get("contract", []) or [] if _text(text)
        }
        if not expected_verification_texts.issubset(actual_verification_texts):
            errors.append({"code": APPROVAL_VERIFICATION_MISMATCH, "field": "contract.test_contract"})
    if plan:
        current_scope = _mutation_scope(plan)
        if _text(plan.get("plan_hash")) != _text(auth.get("canonical_plan_hash")):
            errors.append({"code": APPROVAL_PLAN_HASH_MISMATCH, "field": "plan.plan_hash"})
        if set(_text(item).casefold() for item in current_scope.get("paths", [])) != expected_paths:
            errors.append({"code": APPROVAL_MUTATION_SCOPE_MISMATCH, "field": "plan.mutation_scope"})
        if _dnt(plan) != approved_dnt:
            errors.append({"code": APPROVAL_DNT_MISMATCH, "field": "plan.dnt"})
    if isinstance(graph, dict):
        graph_binding = graph.get("approval_binding") if isinstance(graph.get("approval_binding"), dict) else {}
        if graph_binding and graph_binding != expected:
            errors.append({"code": EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "field": "graph.approval_binding"})
        approved_dependencies = auth.get("approved_dependencies") if isinstance(auth.get("approved_dependencies"), dict) else {}
        approved_dependency_nodes = {
            _text(item.get("node_id")): _ordered_unique(item.get("dependencies", []))
            for item in approved_dependencies.get("nodes", []) or [] if isinstance(item, dict)
        }
        contract_by_id = {
            _text(item.get("execution_contract_id")): item
            for item in contract_list
        }
        contract_to_nodes = {
            _text(item.get("execution_contract_id")): [_text(node_id) for node_id in item.get("plan_node_ids", []) or []]
            for item in graph.get("nodes", []) or [] if isinstance(item, dict)
        }
        actual_dependency_nodes: dict[str, list[str]] = {}
        for graph_node in graph.get("nodes", []) or []:
            if not isinstance(graph_node, dict):
                continue
            dependencies = []
            for dependency_id in graph_node.get("dependencies", []) or []:
                dependency_contract = contract_to_nodes.get(_text(dependency_id), [])
                dependencies.extend(dependency_contract)
            for node_id in graph_node.get("plan_node_ids", []) or []:
                actual_dependency_nodes[_text(node_id)] = _ordered_unique(dependencies)
        if approved_dependency_nodes and actual_dependency_nodes and approved_dependency_nodes != actual_dependency_nodes:
            errors.append({"code": APPROVAL_DEPENDENCY_MISMATCH, "field": "graph.dependencies"})
    return {
        "valid": not errors,
        "status": "ready" if not errors else EXECUTION_AUTHORIZATION_BLOCKED,
        "code": None if not errors else errors[0].get("code"),
        "errors": errors[:40],
        "contract_count": len(contract_list),
    }


def compile_approval_bound_execution_contracts(
    plan: dict[str, Any],
    receipt: PlanApprovalReceipt | dict[str, Any],
    revalidation: PreExecutionApprovalRevalidation | dict[str, Any],
    authorization: ApprovedExecutionAuthorization | dict[str, Any],
    *,
    request: PlanApprovalRequest | dict[str, Any] | None = None,
    requirements: list[dict[str, Any]] | None = None,
    repository_evidence: list[dict[str, Any]] | None = None,
    canonical_surface_registry: dict[str, Any] | None = None,
    authoritative_task_goal: str | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
    execution_invariant_source_root: str | Path | None = None,
) -> dict[str, Any]:
    """Construct Stage 4 contracts from the exact approved plan, read-only."""
    value = plan if isinstance(plan, dict) else {}
    auth = authorization if isinstance(authorization, dict) else {}
    gate = worker_authorization_gate(
        auth, receipt, revalidation, request=request,
        execution_invariant_set=execution_invariant_set,
    )
    if not gate.get("allowed"):
        raise ExecutionAuthorizationError(
            str(gate.get("code") or EXECUTION_AUTHORIZATION_BLOCKED),
            "; ".join(str(item) for item in gate.get("errors", [])) or "execution authorization is not valid",
            gate.get("errors", []),
        )
    if _text(value.get("plan_hash")) != _text(auth.get("canonical_plan_hash")) or _text(value.get("plan_id")) != _text(auth.get("canonical_plan_id")):
        raise ExecutionAuthorizationError(APPROVAL_PLAN_HASH_MISMATCH, "Stage 4 plan identity is not the exact authorized plan")
    try:
        from hivo import execution_contracts as stage4
    except ImportError as exc:  # pragma: no cover
        raise ExecutionAuthorizationError(EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, str(exc)) from exc
    binding = _contract_authority_fields(auth)
    authorized_invariant_hash = _text(auth.get("execution_invariant_set_hash"))
    if authorized_invariant_hash and execution_invariant_set is None:
        raise ExecutionAuthorizationError(
            EXECUTION_INVARIANT_SET_REQUIRED,
            "Stage 4 requires the exact invariant set bound by authorization",
        )
    if execution_invariant_set is not None:
        supplied_invariant_hash = _text(execution_invariant_set.get("invariant_set_hash"))
        if authorized_invariant_hash and supplied_invariant_hash != authorized_invariant_hash:
            raise ExecutionAuthorizationError(
                EXECUTION_INVARIANT_INVALID,
                "execution invariant set does not match current authorization",
            )
        invariant_check = invariant.validate_execution_invariant_set(
            execution_invariant_set,
            source_root=execution_invariant_source_root,
            require_current_subject=execution_invariant_source_root is not None,
        )
        if not invariant_check.get("valid"):
            raise ExecutionAuthorizationError(
                str(invariant_check.get("code") or EXECUTION_INVARIANT_INVALID),
                "; ".join(invariant_check.get("errors", [])) or "execution invariant set is invalid",
                invariant_check.get("errors", []),
            )
    approval = {
        "approval_status": "APPROVED",
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "approval_source": EXPLICIT_USER_APPROVAL,
    }
    if requirements is None:
        requirements = _requirements(value, {})
    evidence = repository_evidence or []
    snapshot = stage4.create_approved_plan_snapshot(
        value, approval, authoritative_task_goal=authoritative_task_goal,
        requirements=requirements, repository_evidence=evidence,
        canonical_surface_registry=canonical_surface_registry,
        authority_binding=binding,
    )
    compiled = stage4.compile_execution_contracts(
        snapshot, authority_binding=binding,
        execution_invariant_set=execution_invariant_set,
    )
    contracts = compiled.get("contracts", [])
    graph = stage4.build_execution_graph(snapshot, contracts)
    graph_check = stage4.validate_execution_graph(snapshot, graph, contracts)
    if not graph_check.get("valid"):
        raise ExecutionAuthorizationError(EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "; ".join(graph_check.get("errors", [])), graph_check.get("errors", []))
    contract_check = validate_approval_bound_contracts(contracts, auth, plan=value, graph=graph)
    if not contract_check.get("valid"):
        raise ExecutionAuthorizationError(EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH, "; ".join(str(item) for item in contract_check.get("errors", [])), contract_check.get("errors", []))
    return {
        "status": EXECUTION_AUTHORIZATION_READY,
        "terminal_state": EXECUTION_AUTHORIZATION_READY,
        "snapshot": snapshot,
        "contracts": contracts,
        "assignment": compiled.get("assignment", {}),
        "graph": graph,
        "validation": graph_check,
        "approval_binding": binding,
        "contract_binding_validation": contract_check,
        "worker_calls": 0,
        "model_calls": 0,
    }


compile_authorized_execution_contracts = compile_approval_bound_execution_contracts
compile_approved_authorized_contracts = compile_approval_bound_execution_contracts


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except (OSError, ValueError, TypeError):
        return _copy(default)


def read_only_project_brain_identity(
    database_path: str | Path,
    project_id: str | None = None,
) -> dict[str, Any]:
    """Read the durable Brain through SQLite read-only mode and never initialize it."""
    target = Path(database_path).expanduser().resolve()
    uri = f"file:{target.as_posix()}?mode=ro"
    records: list[dict[str, Any]] = []
    project = _text(project_id)
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if not project:
            row = connection.execute(
                "SELECT project_id FROM project_brain_facts ORDER BY project_id LIMIT 1",
            ).fetchone()
            project = _text(row[0]) if row else "default"
        rows = connection.execute(
            "SELECT * FROM project_brain_facts WHERE project_id = ? ORDER BY record_id",
            (project,),
        ).fetchall()
        for row in rows:
            def decode(name: str, fallback: Any) -> Any:
                try:
                    value = json.loads(str(row[name]))
                    return value
                except (KeyError, TypeError, ValueError):
                    return _copy(fallback)
            records.append({
                "record_id": _text(row["record_id"]),
                "project_id": _text(row["project_id"]),
                "fact_hash": _text(row["fact_hash"]),
                "semantic_hash": _text(row["semantic_hash"]),
                "conflict_key": _text(row["conflict_key"]),
                "fact": decode("fact_json", {}),
                "durability_class": _text(row["durability_class"]),
                "subject_state_hash": _text(row["subject_state_hash"]),
                "status": _text(row["status"]),
                "supersedes": decode("supersedes_json", []),
                "superseded_by": row["superseded_by"],
                "provenance": decode("provenance_json", {}),
            })
    finally:
        connection.close()
    snapshot = {"project_id": project, "records": records}
    durability_counts: dict[str, int] = {}
    for record in records:
        key = _text(record.get("durability_class"))
        durability_counts[key] = durability_counts.get(key, 0) + 1
    return {
        "project_id": project,
        "logical_hash": canonical_hash(snapshot),
        "record_count": len(records),
        "durability_counts": durability_counts,
        "records": records,
        "read_only": True,
        "writes": 0,
    }


def _live_state(
    artifact_root: Path,
    plan: dict[str, Any],
    context: dict[str, Any],
    freshness: dict[str, Any],
    plan_validation: dict[str, Any],
    contractability: dict[str, Any],
    reconciliation: dict[str, Any],
    brain: dict[str, Any],
) -> dict[str, Any]:
    upstream = plan.get("upstream_bindings", {}) if isinstance(plan.get("upstream_bindings"), dict) else {}
    return {
        "task_id": context.get("task_id"),
        "project_id": context.get("project_id"),
        "planning_mode": context.get("planning_mode") or plan.get("planning_mode"),
        "verified_planning_context": context,
        "planning_context_hash": context.get("planning_context_hash"),
        "brain_hash": brain.get("logical_hash") or context.get("source_project_brain_hash"),
        "subject_aggregate_hash": (context.get("source_repository_fingerprint") or {}).get("hash"),
        "upstream_bindings": upstream,
        "requirements": plan.get("requirements", []),
        "coverage": plan.get("coverage", []),
        "planning_context_freshness": freshness,
        "plan_validation": plan_validation,
        "stage4_contractability_audit": contractability,
        "challenger_reconciliation": reconciliation,
        "terminal_state": PLAN_APPROVAL_REQUIRED,
        "source_repository_fingerprint": context.get("source_repository_fingerprint", {}),
        "brain_identity": {
            "project_id": brain.get("project_id"),
            "logical_hash": brain.get("logical_hash"),
            "record_count": brain.get("record_count"),
        },
        "artifact_root": str(artifact_root),
    }


def run_stage6c_a_live_replay(
    artifact_root: str | Path | None = None,
    *,
    brain_database_path: str | Path | None = None,
    event_reference: str = "TEST-EXPLICIT-APPROVAL-001",
    expected_brain_hash: str | None = None,
) -> dict[str, Any]:
    """Replay the persisted Stage 6B success and stop before execution."""
    if artifact_root is None:
        artifact_root = Path(__file__).resolve().parents[1] / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
    root = Path(artifact_root).expanduser().resolve()
    plan = _read_json(root / "final_plan.json", {})
    context = _read_json(root / "verified_planning_context.json", {})
    freshness = _read_json(root / "planning_context_freshness.json", {})
    plan_validation = _read_json(root / "plan_validation.json", {})
    contractability = _read_json(root / "stage4_contractability_audit.json", {})
    reconciliation = _read_json(root / "challenger_reconciliation.json", plan.get("challenger_reconciliation", {}))
    if brain_database_path is None:
        brain_database_path = root.parent / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
    brain = read_only_project_brain_identity(brain_database_path, context.get("project_id"))
    state = _live_state(root, plan, context, freshness, plan_validation, contractability, reconciliation, brain)
    if expected_brain_hash and brain.get("logical_hash") != expected_brain_hash:
        raise ApprovalRequestError(APPROVAL_REQUEST_INVALID, "read-only Project Brain logical hash does not match the expected frozen identity")
    request = create_plan_approval_request(plan, state)
    event = make_test_explicit_user_approval_event(request, event_reference)
    receipt = record_plan_approval(request, event)
    revalidation = pre_execution_approval_revalidation(receipt, plan, state, request=request)
    authorization = create_approved_execution_authorization(receipt, revalidation, request=request)
    compiled = compile_approval_bound_execution_contracts(
        plan, receipt, revalidation, authorization,
        request=request, requirements=plan.get("requirements", []),
    )
    return {
        "status": EXECUTION_AUTHORIZATION_READY,
        "terminal_state": EXECUTION_AUTHORIZATION_READY,
        # The state is a read-only replay projection used by the subsequent
        # Stage 6C-B last-moment gate.  Returning it does not grant authority,
        # mutate the historical Brain, or change the approval semantics.
        "state": state,
        "approval_request": request,
        "approval_event": event,
        "approval_receipt": receipt,
        "pre_execution_approval_revalidation": revalidation,
        "execution_authorization": authorization,
        "stage4": compiled,
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "worker_calls": 0,
        "builder_calls": 0,
        "model_calls": 0,
        "gemma_generations": 0,
        "subject_mutations": 0,
        "brain_writes": 0,
        "verifier_calls": 0,
        "repairer_calls": 0,
        "promotion_calls": 0,
        "stage6c_execution": 0,
        "stop_before_execution": True,
        "brain_identity": {
            key: brain.get(key) for key in ("project_id", "logical_hash", "record_count", "durability_counts", "read_only", "writes")
        },
    }


def run_stage6c_a_self_test(
    artifact_root: str | Path | None = None,
    *,
    brain_database_path: str | Path | None = None,
) -> dict[str, Any]:
    """Run the provider-free V25 architecture self-test and report checks."""
    if artifact_root is None:
        artifact_root = Path(__file__).resolve().parents[1] / "output" / "hivo-v24-4-6-stage6b-planning-live-1"
    try:
        result = run_stage6c_a_live_replay(
            artifact_root, brain_database_path=brain_database_path,
            expected_brain_hash="8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb",
        )
        checks = {
            "approval_request_ready": result.get("approval_request", {}).get("status") == APPROVAL_REQUEST_READY,
            "explicit_test_event": result.get("approval_event", {}).get("source") == TEST_EXPLICIT_USER_APPROVAL,
            "receipt_recorded": result.get("approval_receipt", {}).get("status") == APPROVAL_RECORDED,
            "revalidation_passed": result.get("pre_execution_approval_revalidation", {}).get("valid") is True,
            "stage4_bound": (result.get("stage4") or {}).get("contract_binding_validation", {}).get("valid") is True,
            "authorization_ready": result.get("status") == EXECUTION_AUTHORIZATION_READY,
            "model_calls_zero": result.get("model_calls") == 0,
            "worker_calls_zero": result.get("worker_calls") == 0,
            "subject_mutations_zero": result.get("subject_mutations") == 0,
            "brain_writes_zero": result.get("brain_writes") == 0,
        }
        return {"passed": all(checks.values()), "status": "PASS" if all(checks.values()) else "FAIL", "checks": checks, "result": result}
    except (ApprovalAuthorityError, OSError, sqlite3.Error, ValueError) as exc:
        return {
            "passed": False, "status": "FAIL",
            "checks": {"replay_exception_free": False},
            "error": str(exc), "model_calls": 0, "worker_calls": 0,
            "subject_mutations": 0, "brain_writes": 0,
        }


replay_stage6c_a = run_stage6c_a_live_replay
run_stage6c_a_authorization_replay = run_stage6c_a_live_replay

# Friendly compatibility aliases for callers that use the nouns from the
# Stage 6C-A specification rather than the longer implementation names.
ApprovalEvent = ExplicitUserApprovalEvent
ExplicitApprovalEvent = ExplicitUserApprovalEvent
PreExecutionAuthorization = ApprovedExecutionAuthorization
create_approval_request = create_plan_approval_request
record_approval = record_plan_approval
create_approval_receipt = record_plan_approval
revalidate_approval = pre_execution_approval_revalidation
create_execution_authorization = create_approved_execution_authorization
validate_execution_authorization = validate_approved_execution_authorization
check_worker_authorization = worker_authorization_gate


__all__ = [
    "SCHEMA_VERSION", "PLAN_APPROVAL_REQUIRED", "APPROVAL_REQUEST_READY", "APPROVAL_RECORDED",
    "APPROVAL_INVALID", "APPROVAL_STALE", "REAPPROVAL_REQUIRED", "EXECUTION_AUTHORIZATION_READY",
    "EXECUTION_AUTHORIZATION_BLOCKED", "EXPLICIT_USER_APPROVAL", "TEST_EXPLICIT_USER_APPROVAL",
    "APPROVAL_PLAN_HASH_MISMATCH", "PLAN_HASH_MISMATCH", "APPROVAL_REQUIREMENT_MISMATCH",
    "APPROVAL_SUBJECT_STALE", "APPROVAL_BRAIN_STALE", "APPROVAL_PLANNING_CONTEXT_MISMATCH",
    "APPROVAL_SOURCE_BINDING_MISMATCH", "APPROVAL_MUTATION_SCOPE_MISMATCH", "APPROVAL_DNT_MISMATCH",
    "APPROVAL_DEPENDENCY_MISMATCH", "APPROVAL_VERIFICATION_MISMATCH", "APPROVAL_INTERFACE_MISMATCH",
    "APPROVAL_RECONCILIATION_MISMATCH", "APPROVAL_RECEIPT_INVALID", "APPROVAL_TASK_MISMATCH",
    "EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH", "ApprovalAuthorityError", "ApprovalRequestError",
    "ApprovalReceiptError", "ExecutionAuthorizationError", "PlanApprovalRequest",
    "ExplicitUserApprovalEvent", "PlanApprovalReceipt", "PreExecutionApprovalRevalidation",
    "ApprovedExecutionAuthorization", "canonical_hash", "deterministic_hash",
    "build_approval_authority_binding", "create_plan_approval_request", "build_plan_approval_request",
    "validate_plan_approval_request", "make_explicit_user_approval_event",
    "make_test_explicit_user_approval_event", "record_plan_approval", "record_explicit_user_approval",
    "ApprovalEvent", "ExplicitApprovalEvent", "PreExecutionAuthorization", "create_approval_request",
    "record_approval", "create_approval_receipt", "revalidate_approval", "create_execution_authorization",
    "validate_execution_authorization", "check_worker_authorization",
    "validate_plan_approval_receipt", "pre_execution_approval_revalidation",
    "revalidate_pre_execution_approval", "create_approved_execution_authorization",
    "validate_approved_execution_authorization", "worker_authorization_gate",
    "validate_approval_bound_contracts", "compile_approval_bound_execution_contracts",
    "read_only_project_brain_identity", "run_stage6c_a_live_replay", "run_stage6c_a_self_test", "replay_stage6c_a",
]
