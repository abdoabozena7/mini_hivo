"""Bounded pre-mutation impact contracts.

This module is deliberately a small controller-side contract layer.  It does
not plan a project-wide blast radius and it does not store model reasoning.
The contract is a compact, typed description of the semantic surface that a
single Worker is allowed to change, the facts it must preserve, and the
observations that make the change complete.

All source-backed semantic observations retain provenance.  The module is
duck-typed at the World Model boundary so the existing ProjectWorldModel can
be used without creating a second graph or persistence system.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping


PRE_MUTATION_IMPACT_SCHEMA_VERSION = "HIVO-PRE-MUTATION-IMPACT-V1"

# Impact categories.  They are intentionally narrower than a general change
# planner: each category names a semantic question the post-mutation audit can
# answer from bounded repository observations.
DIRECT_IMPLEMENTATION = "DIRECT_IMPLEMENTATION"
PUBLIC_CONTRACT = "PUBLIC_CONTRACT"
CALLER_CONSUMER = "CALLER_CONSUMER"
TYPE_SCHEMA = "TYPE_SCHEMA"
STATE_TRANSITION = "STATE_TRANSITION"
EXPORT_PUBLIC_SURFACE = "EXPORT_PUBLIC_SURFACE"
TEST_BEHAVIOR = "TEST_BEHAVIOR"
CONFIGURATION = "CONFIGURATION"
INVARIANT = "INVARIANT"
DEPENDENCY = "DEPENDENCY"
SIDE_EFFECT = "SIDE_EFFECT"

IMPACT_CATEGORIES = (
    DIRECT_IMPLEMENTATION, PUBLIC_CONTRACT, CALLER_CONSUMER, TYPE_SCHEMA,
    STATE_TRANSITION, EXPORT_PUBLIC_SURFACE, TEST_BEHAVIOR, CONFIGURATION,
    INVARIANT, DEPENDENCY, SIDE_EFFECT,
)

# Typed comparison outcomes.
EXPECTED_AND_OBSERVED = "EXPECTED_AND_OBSERVED"
EXPECTED_BUT_MISSING = "EXPECTED_BUT_MISSING"
UNEXPECTED_BUT_RELATED = "UNEXPECTED_BUT_RELATED"
UNEXPECTED_AND_OUT_OF_SCOPE = "UNEXPECTED_AND_OUT_OF_SCOPE"
PRESERVATION_VIOLATED = "PRESERVATION_VIOLATED"
UNRESOLVED = "UNRESOLVED"
CONFLICTING = "CONFLICTING"

IMPACT_ACCEPTED = "IMPACT_CONTRACT_ACCEPTED"
IMPACT_INCOMPLETE = "IMPACT_CONTRACT_INCOMPLETE"
IMPACT_CONFLICT = "IMPACT_CONTRACT_CONFLICT"
IMPACT_REQUIRED = "IMPACT_CONTRACT_REQUIRED"
IMPACT_INVALID = "IMPACT_CONTRACT_INVALID"
IMPACT_STALE = "IMPACT_CONTRACT_STALE"
IMPACT_VERIFICATION_FAILED = "IMPACT_CONTRACT_VERIFICATION_FAILED"
IMPACT_REPLAN_REQUIRED = "IMPACT_CONTRACT_REPLAN_REQUIRED"
IMPACT_PASSED = "IMPACT_CONTRACT_PASSED"
IMPACT_FAILED = "IMPACT_CONTRACT_FAILED"

SATISFIED = "SATISFIED"
FAILED = "FAILED"
NOT_APPLICABLE = "NOT_APPLICABLE"

# Small explicit limits.  They are independent of the existing 4,200
# character Worker context and never increase it.
MAX_IMPACT_TARGETS = 12
MAX_IMPACT_OBLIGATIONS = 10
MAX_IMPACT_PRESERVATIONS = 8
MAX_EXPECTED_RELATION_DELTAS = 8
MAX_IMPACT_EVIDENCE_ITEMS = 6
MAX_IMPACT_ACTUAL_TARGETS = 16
MAX_IMPACT_CHANGED_PATHS = 12
MAX_IMPACT_REVISIONS = 2
# Public spelling used by callers that describe this as a contract revision
# budget.  Keep the internal name for compatibility with the implementation.
MAX_IMPACT_CONTRACT_REVISIONS = MAX_IMPACT_REVISIONS
MAX_PRESERVATIONS = MAX_IMPACT_PRESERVATIONS
MAX_IMPACT_NEIGHBORHOOD_FACTS = 12
MAX_IMPACT_PROJECTION_CHARS = 1200
MAX_IMPACT_TEXT = 420
MAX_IMPACT_PATH = 300
MAX_IMPACT_SOURCE_EXCERPT = 520


def canonical_hash(value: Any) -> str:
    """Return a stable digest for a JSON-shaped controller artifact."""

    return hashlib.sha256(
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _text(value: Any, limit: int = MAX_IMPACT_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _path(value: Any) -> str:
    text = _text(value, MAX_IMPACT_PATH).replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _workspace_relative_path(value: Any, workspace: str | Path | None = None) -> str:
    """Return a stable project-relative path when a workspace is known.

    Transaction snapshots use absolute filesystem keys while execution
    contracts use repository-relative paths.  Impact comparison must compare
    those two representations as one path; it must not turn the absolute
    snapshot path into an accidental out-of-scope mutation.
    """

    text = _path(value)
    if not text or workspace is None:
        return text
    try:
        root = Path(workspace).expanduser().resolve()
        candidate = Path(str(value)).expanduser()
        if candidate.is_absolute():
            resolved = candidate.resolve()
            if resolved == root:
                return ""
            if root in resolved.parents:
                return resolved.relative_to(root).as_posix()
    except (OSError, RuntimeError, TypeError, ValueError):
        pass
    return text


def _unique(values: Iterable[Any], limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        key = item.casefold()
        if item and key not in seen:
            result.append(item)
            seen.add(key)
        if len(result) >= limit:
            break
    return result


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return copy.deepcopy(dict(value))
    if isinstance(value, PreMutationImpactContract):
        return value.to_dict()
    return {}


def _source_ref(value: Any, *, fallback: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Normalize a bounded provenance reference without retaining source blobs."""

    raw = value if isinstance(value, Mapping) else {}
    fallback = fallback if isinstance(fallback, Mapping) else {}
    identity = raw.get("source_identity") or raw.get("source") or raw.get("file")
    path = raw.get("path") or raw.get("source_path")
    if not path and identity:
        identity_text = str(identity).replace("\\", "/")
        path = re.split(r":(?:line\s*)?\d+(?:-\d+)?$", identity_text, maxsplit=1)[0]
    path = _path(path or fallback.get("path"))
    identity = _text(identity or path or fallback.get("source_identity") or "", 220)
    location = _text(raw.get("location") or raw.get("line") or fallback.get("location") or "", 80)
    evidence_kind = _text(
        raw.get("evidence_kind") or raw.get("source_kind") or raw.get("kind")
        or fallback.get("evidence_kind") or "controller_evidence", 100,
    )
    result = {
        "source_identity": identity or "controller:impact-contract",
        "path": path,
        "location": location,
        "evidence_kind": evidence_kind,
        "evidence_id": _text(raw.get("evidence_id") or fallback.get("evidence_id") or "", 120),
        "authority_tier": _text(raw.get("authority_tier") or fallback.get("authority_tier") or "MEDIUM", 20).upper(),
        "authority_score": int(raw.get("authority_score") or fallback.get("authority_score") or 60),
    }
    excerpt = raw.get("excerpt") or raw.get("text") or fallback.get("excerpt")
    if excerpt:
        result["excerpt"] = _text(excerpt, MAX_IMPACT_SOURCE_EXCERPT)
    source_hash = raw.get("source_hash") or raw.get("content_hash") or fallback.get("source_hash")
    if source_hash:
        result["source_hash"] = _text(source_hash, 120)
    return result


def _source_refs(values: Any, *, fallback: Mapping[str, Any] | None = None, limit: int = MAX_IMPACT_EVIDENCE_ITEMS) -> list[dict[str, Any]]:
    if isinstance(values, Mapping):
        values = [values]
    elif isinstance(values, str):
        values = [{"source_identity": values}]
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in list(values or [])[:limit]:
        reference = _source_ref(item, fallback=fallback)
        identity = (reference.get("source_identity") or "").casefold()
        location = str(reference.get("location") or "").casefold()
        key = identity + "|" + location
        if key in seen:
            continue
        seen.add(key)
        result.append(reference)
    return result


def _authority_source(text: str, *, task_id: Any = None) -> dict[str, Any]:
    return _source_ref({
        "source_identity": "controller:approved-task-contract",
        "location": str(task_id or "task"),
        "evidence_kind": "approved_task_contract",
        "authority_tier": "HIGH",
        "authority_score": 100,
        "excerpt": _text(text, MAX_IMPACT_SOURCE_EXCERPT),
    })


def _fact_attr(fact: Any, key: str, default: Any = None) -> Any:
    if isinstance(fact, Mapping):
        return fact.get(key, default)
    return getattr(fact, key, default)


def _fact_state(fact: Any) -> str:
    return str(_fact_attr(fact, "state", "") or "").upper()


def _fact_dict(fact: Any) -> dict[str, Any]:
    if isinstance(fact, Mapping):
        return copy.deepcopy(dict(fact))
    to_dict = getattr(fact, "to_dict", None)
    if callable(to_dict):
        try:
            return copy.deepcopy(to_dict())
        except Exception:
            pass
    return {
        "fact_id": _fact_attr(fact, "fact_id", ""),
        "subject": _fact_attr(fact, "subject", ""),
        "relation": _fact_attr(fact, "relation", ""),
        "object": _fact_attr(fact, "object", ""),
        "state": _fact_state(fact),
        "provenance": copy.deepcopy(_fact_attr(fact, "provenance", []) or []),
        "authority_score": _fact_attr(fact, "authority_score", 0),
    }


def _current_world_facts(world_model: Any, targets: Iterable[str] = ()) -> list[dict[str, Any]]:
    if world_model is None:
        return []
    refresh = getattr(world_model, "refresh_currentness", None)
    if callable(refresh):
        try:
            refresh()
        except Exception:
            pass
    facts: list[Any] = []
    raw_facts = getattr(world_model, "facts", None)
    if callable(raw_facts):
        try:
            raw_facts = raw_facts()
        except Exception:
            raw_facts = []
    if isinstance(raw_facts, Iterable) and not isinstance(raw_facts, (str, bytes, Mapping)):
        facts.extend(list(raw_facts))
    target_values = [str(item).casefold() for item in targets if str(item or "").strip()]
    result = []
    for raw in facts:
        row = _fact_dict(raw)
        state = str(row.get("state") or "").upper()
        if state not in {"VERIFIED", "CONFLICTING", "STALE"}:
            continue
        if target_values:
            subject = str(row.get("subject") or "").casefold()
            obj = str(row.get("object") or "").casefold()
            if not any(target in {subject, obj} or target in subject or target in obj for target in target_values):
                continue
        result.append(row)
    return result


def _neighborhood_facts(world_model: Any, target: str, *, max_facts: int = MAX_IMPACT_NEIGHBORHOOD_FACTS) -> list[dict[str, Any]]:
    if world_model is None:
        return []
    neighborhood = getattr(world_model, "neighborhood", None)
    if callable(neighborhood):
        try:
            result = neighborhood(target, max_hops=2, max_facts=max_facts, include_states=("VERIFIED", "CONFLICTING"))
            rows = result.get("facts", []) if isinstance(result, Mapping) else []
            return [_fact_dict(item) for item in list(rows or [])[:max_facts]]
        except Exception:
            return []
    return _current_world_facts(world_model, [target])[:max_facts]


def _kind_for_goal(text: str) -> str:
    lowered = str(text or "").casefold()
    if any(token in lowered for token in ("state", "transition", "idle", "running", "complete")):
        return STATE_TRANSITION
    if any(token in lowered for token in ("schema", "type", "return contract", "return shape")):
        return TYPE_SCHEMA
    if any(token in lowered for token in ("export", "public api", "public surface")):
        return EXPORT_PUBLIC_SURFACE
    if any(token in lowered for token in ("config", "configuration", "environment variable")):
        return CONFIGURATION
    if any(token in lowered for token in ("invariant", "must preserve", "preserve")):
        return INVARIANT
    if any(token in lowered for token in ("caller", "consumer", "downstream")):
        return CALLER_CONSUMER
    if any(token in lowered for token in ("contract", "interface", "producer")):
        return PUBLIC_CONTRACT
    return DIRECT_IMPLEMENTATION


def _identifier_candidates(text: str) -> list[str]:
    values = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*(?:\.[A-Za-z_$][A-Za-z0-9_$]*)?", str(text or ""))
    ignored = {"change", "update", "modify", "implement", "preserve", "behavior", "public", "return", "value", "type", "state", "task"}
    return _unique((item for item in values if item.casefold() not in ignored and len(item) > 2), MAX_IMPACT_TARGETS)


def _target_record(value: Any, *, default_kind: str = DIRECT_IMPLEMENTATION, required: bool = True, fallback_source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {"target": value}
    target = _text(raw.get("target") or raw.get("symbol") or raw.get("name") or raw.get("path") or "", MAX_IMPACT_PATH)
    path = _path(raw.get("path") or (target if "/" in target or "\\" in target or Path(target).suffix else ""))
    categories = raw.get("categories") or raw.get("category") or raw.get("kind") or default_kind
    if isinstance(categories, str):
        categories = [categories]
    categories = _unique(categories, 4)
    return {
        "target": target,
        "kind": _text(raw.get("kind") or ("path" if path else "symbol"), 50),
        "path": path,
        "categories": categories or [default_kind],
        "required": bool(raw.get("required", required)),
        "aliases": _unique(raw.get("aliases", []) if isinstance(raw.get("aliases"), Iterable) and not isinstance(raw.get("aliases"), str) else [], 6),
        "provenance": _source_refs(
            raw.get("provenance") or raw.get("evidence") or raw.get("sources"),
            fallback=fallback_source,
            limit=3,
        ) or [_source_ref(fallback_source or _authority_source(target))],
    }


def _relation_record(value: Any, *, fallback_source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {"relation": value}
    relation = _text(raw.get("relation") or raw.get("kind") or raw.get("type") or "", 80).upper()
    subject = _text(raw.get("subject") or raw.get("source") or raw.get("from_subject") or "", 180)
    object_value = _text(raw.get("object") or raw.get("target") or raw.get("to") or raw.get("after") or "", 220)
    before = _text(raw.get("before") or raw.get("from") or "", 220)
    after = _text(raw.get("after") or raw.get("to") or object_value, 220)
    result = {
        "subject": subject,
        "relation": relation,
        "object": object_value,
        "before": before,
        "after": after,
        "required": bool(raw.get("required", True)),
        "category": _text(raw.get("category") or raw.get("semantic_kind") or "DEPENDENCY", 80),
        "provenance": _source_refs(raw.get("provenance") or raw.get("evidence") or raw.get("sources"), fallback=fallback_source, limit=3)
        or [_source_ref(fallback_source or _authority_source(f"{subject} {relation} {object_value}"))],
    }
    return result


def _preservation_record(value: Any, *, fallback_source: Mapping[str, Any] | None = None) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {"meaning": value}
    return {
        "id": _text(raw.get("id") or raw.get("name") or raw.get("meaning") or "preservation", 100),
        "meaning": _text(raw.get("meaning") or raw.get("constraint") or raw.get("text") or raw.get("name") or "", MAX_IMPACT_TEXT),
        "target": _text(raw.get("target") or "", 180),
        "required": bool(raw.get("required", True)),
        "provenance": _source_refs(raw.get("provenance") or raw.get("evidence") or raw.get("sources"), fallback=fallback_source, limit=2)
        or [_source_ref(fallback_source or _authority_source(str(raw.get("meaning") or "preservation")))],
    }


def _obligation_record(value: Any, index: int, *, fallback_source: Mapping[str, Any] | None = None, explicit: bool = False) -> dict[str, Any]:
    raw = value if isinstance(value, Mapping) else {"meaning": value}
    meaning = _text(raw.get("meaning") or raw.get("description") or raw.get("text") or raw.get("done_when") or "", MAX_IMPACT_TEXT)
    category = _text(raw.get("category") or raw.get("kind") or "BEHAVIOR", 80).upper()
    return {
        "id": _text(raw.get("id") or f"impact-obligation-{index + 1}", 100),
        "category": category,
        "meaning": meaning,
        "target": _text(raw.get("target") or "", 180),
        "required": bool(raw.get("required", True)),
        "verification_kind": _text(raw.get("verification_kind") or raw.get("evidence_kind") or ("explicit" if explicit else "existing_gate"), 80),
        "mode": _text(raw.get("mode") or ("explicit" if explicit else "controller"), 40).lower(),
        "status": _text(raw.get("status") or UNRESOLVED, 40).upper(),
        "provenance": _source_refs(raw.get("provenance") or raw.get("evidence") or raw.get("sources"), fallback=fallback_source, limit=2)
        or [_source_ref(fallback_source or _authority_source(meaning))],
    }


def _contract_payload(contract: Mapping[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(dict(contract))
    for key in (
        "contract_hash", "contract_id", "status", "validation_status",
        "controller_accepted", "accepted_contract_hash", "authorization_token",
        "authorization_reason", "last_validation",
    ):
        value.pop(key, None)
    return value


def _refresh_contract_hash(contract: dict[str, Any]) -> dict[str, Any]:
    value = copy.deepcopy(contract)
    value["contract_hash"] = canonical_hash(_contract_payload(value))
    value["contract_id"] = "IMPACT-" + value["contract_hash"][:24].upper()
    return value


class PreMutationImpactContract(dict):
    """JSON-shaped typed contract with normal mapping ergonomics."""

    def to_dict(self) -> dict[str, Any]:
        return copy.deepcopy(dict(self))


# Compatibility façade for callers that use the shorter architectural name.
ImpactContract = PreMutationImpactContract


@dataclass(frozen=True)
class ImpactComparison:
    """Small typed façade for callers that prefer an object result."""

    status: str
    passed: bool
    comparisons: tuple[dict[str, Any], ...]
    missing: tuple[dict[str, Any], ...] = ()
    unexpected: tuple[dict[str, Any], ...] = ()
    preservation_violations: tuple[dict[str, Any], ...] = ()
    obligations: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "passed": self.passed,
            "comparisons": [copy.deepcopy(item) for item in self.comparisons],
            "missing": [copy.deepcopy(item) for item in self.missing],
            "unexpected": [copy.deepcopy(item) for item in self.unexpected],
            "preservation_violations": [copy.deepcopy(item) for item in self.preservation_violations],
            "obligations": [copy.deepcopy(item) for item in self.obligations],
        }


def build_pre_mutation_impact_contract(
    task: Mapping[str, Any] | None = None,
    *,
    task_id: Any = None,
    change_intent: Any = None,
    root_goal: Any = None,
    parent_goal: Any = None,
    local_task: Any = None,
    group_goal: Any = None,
    group_invariant: Any = None,
    execution_contract: Mapping[str, Any] | None = None,
    world_model: Any = None,
    expected_targets: Any = None,
    expected_relationship_changes: Any = None,
    required_preservations: Any = None,
    verification_obligations: Any = None,
    forbidden_or_out_of_scope: Any = None,
    evidence: Any = None,
    mutation_required: bool = True,
    strict: bool = True,
    **kwargs: Any,
) -> PreMutationImpactContract:
    """Create a bounded controller candidate from existing task authority.

    The function accepts the existing task/execution-contract shapes rather
    than introducing a new planning input.  Explicit fields win; deterministic
    World Model relations only enrich the local contract neighborhood.
    """

    task_value = _mapping(task)
    execution = _mapping(execution_contract or task_value.get("execution_contract"))
    task_id = task_id or task_value.get("id") or task_value.get("task_id") or execution.get("task_id") or "ROOT"
    local = _text(local_task or task_value.get("goal") or execution.get("goal") or change_intent or "", 800)
    intent_text = _text(change_intent or task_value.get("change_intent") or local, 800)
    kind = _kind_for_goal(intent_text)
    anchor_source = _authority_source(intent_text, task_id=task_id)

    target_values = expected_targets
    if target_values is None:
        target_values = (
            task_value.get("expected_targets")
            or task_value.get("impact_targets")
            or task_value.get("affected_targets")
            or execution.get("expected_targets")
            or execution.get("impact_targets")
            or []
        )
    had_explicit_targets = bool(target_values)
    if isinstance(target_values, (str, Mapping)):
        target_values = [target_values]
    targets = [
        _target_record(item, default_kind=kind, required=True, fallback_source=anchor_source)
        for item in list(target_values or [])[:MAX_IMPACT_TARGETS]
    ]
    allowed_paths = _unique(
        list(task_value.get("allowed_mutation_paths", []) or [])
        + list(execution.get("allowed_mutation_paths", []) or [])
        + list(task_value.get("scope_hint", []) or []),
        MAX_IMPACT_CHANGED_PATHS,
    )
    for allowed in allowed_paths:
        if not any(str(item.get("target", "")).casefold() == allowed.casefold() for item in targets):
            targets.append(_target_record({"target": allowed, "path": allowed, "kind": "path"}, default_kind=DIRECT_IMPLEMENTATION, required=False, fallback_source=anchor_source))
        if len(targets) >= MAX_IMPACT_TARGETS:
            break
    if not targets:
        for candidate in _identifier_candidates(intent_text):
            # A task-derived symbol is a semantic hint when the approved
            # mutation path is already authoritative.  Explicit target records
            # remain required and are audited exactly.
            targets.append(_target_record(candidate, default_kind=kind, required=had_explicit_targets or not allowed_paths, fallback_source=anchor_source))
            if len(targets) >= MAX_IMPACT_TARGETS:
                break

    # A small deterministic neighborhood discovers known consumers, contracts,
    # exports, and state relations.  These are expectations for the contract,
    # not raw context for the Worker.
    primary_targets = [str(item.get("target", "")) for item in targets[:4] if item.get("target")]
    neighborhood: list[dict[str, Any]] = []
    for target in primary_targets[:4]:
        neighborhood.extend(_neighborhood_facts(world_model, target))
    seen_fact_ids: set[str] = set()
    neighborhood = [
        fact for fact in neighborhood
        if (fact.get("fact_id") or (fact.get("subject"), fact.get("relation"), fact.get("object"))) not in seen_fact_ids
        and not seen_fact_ids.add(fact.get("fact_id") or (fact.get("subject"), fact.get("relation"), fact.get("object")))
    ][:MAX_IMPACT_NEIGHBORHOOD_FACTS]
    target_folded = {item.casefold() for item in primary_targets}
    consumer_subjects: set[str] = set()
    for fact in neighborhood:
        if str(fact.get("state") or "").upper() != "VERIFIED":
            continue
        relation = str(fact.get("relation") or "").upper()
        subject = str(fact.get("subject") or "")
        object_value = str(fact.get("object") or "")
        if relation == "CALLS" and object_value.casefold() in target_folded:
            consumer_subjects.add(subject)
            if kind in {PUBLIC_CONTRACT, TYPE_SCHEMA, CALLER_CONSUMER, DIRECT_IMPLEMENTATION}:
                targets.append(_target_record({
                    "target": subject, "kind": "symbol", "category": CALLER_CONSUMER,
                    "required": False, "provenance": fact.get("provenance", []),
                }, default_kind=CALLER_CONSUMER, required=False, fallback_source=anchor_source))
        if relation in {"RETURNS_TYPE", "IMPLEMENTS_CONTRACT", "EXPECTS_RETURN_SHAPE", "DECLARES_TYPE", "DECLARES_FIELD", "READS_FIELD", "EXPORTS", "EXPORTED_BY", "TRANSITIONS", "HAS_INVARIANT", "READS_CONFIG", "DEPENDS_ON", "IMPORTS"}:
            neighborhood_source = (fact.get("provenance") or [anchor_source])[0]
            if relation in {"RETURNS_TYPE", "IMPLEMENTS_CONTRACT", "EXPECTS_RETURN_SHAPE"} and kind in {PUBLIC_CONTRACT, TYPE_SCHEMA, DIRECT_IMPLEMENTATION}:
                pass
            # The relation is retained below as an expected/preserved fact; do
            # not turn every neighbor into a mutation target.
    # Deduplicate bounded target records by target/path.
    deduped_targets: list[dict[str, Any]] = []
    target_keys: set[str] = set()
    for item in targets:
        key = (str(item.get("target") or "").casefold(), str(item.get("path") or "").casefold())
        if not key[0] or key in target_keys:
            continue
        target_keys.add(key)
        deduped_targets.append(item)
    targets = deduped_targets[:MAX_IMPACT_TARGETS]

    relation_values = expected_relationship_changes
    if relation_values is None:
        relation_values = (
            task_value.get("expected_relationship_changes")
            or task_value.get("expected_relation_changes")
            or task_value.get("semantic_delta")
            or execution.get("expected_relationship_changes")
            or []
        )
    if isinstance(relation_values, (str, Mapping)):
        relation_values = [relation_values]
    relations = [_relation_record(item, fallback_source=anchor_source) for item in list(relation_values or [])[:MAX_EXPECTED_RELATION_DELTAS]]

    preservation_values = required_preservations
    if preservation_values is None:
        preservation_values = (
            task_value.get("required_preservations")
            or task_value.get("local_preservation_constraints")
            or task_value.get("preservation_constraints")
            or execution.get("local_preservation_constraints")
            or []
        )
    if isinstance(preservation_values, (str, Mapping)):
        preservation_values = [preservation_values]
    if group_invariant or task_value.get("semantic_group_invariant"):
        preservation_values = list(preservation_values or []) + [{
            "id": "semantic-group-invariant",
            "meaning": group_invariant or task_value.get("semantic_group_invariant"),
            "provenance": [anchor_source],
        }]
    preservations = [_preservation_record(item, fallback_source=anchor_source) for item in list(preservation_values or [])[:MAX_IMPACT_PRESERVATIONS]]

    obligation_values = verification_obligations
    explicit_obligations = obligation_values is not None or bool(task_value.get("verification_obligations") or execution.get("verification_obligations"))
    if obligation_values is None:
        obligation_values = task_value.get("verification_obligations") or execution.get("verification_obligations")
    if obligation_values is None:
        obligation_values = (
            task_value.get("test_contract")
            or execution.get("test_contract")
            or task_value.get("done_when")
            or execution.get("requirements")
            or []
        )
    if isinstance(obligation_values, (str, Mapping)):
        obligation_values = [obligation_values]
    obligations = [
        _obligation_record(item, index, fallback_source=anchor_source, explicit=explicit_obligations)
        for index, item in enumerate(list(obligation_values or [])[:MAX_IMPACT_OBLIGATIONS])
    ]
    if mutation_required and not obligations:
        obligations = [_obligation_record({
            "id": "controller-post-state",
            "category": "POST_STATE",
            "meaning": "the bounded intended semantic change is observable after mutation",
            "required": True,
        }, 0, fallback_source=anchor_source, explicit=False)]

    forbidden_values = forbidden_or_out_of_scope
    if forbidden_values is None:
        forbidden_values = (
            task_value.get("forbidden_or_out_of_scope")
            or task_value.get("global_do_not_touch")
            or execution.get("global_do_not_touch")
            or []
        )
    if isinstance(forbidden_values, (str, Mapping)):
        forbidden_values = [forbidden_values]
    forbidden = []
    for item in list(forbidden_values or [])[:MAX_IMPACT_CHANGED_PATHS]:
        raw = item if isinstance(item, Mapping) else {"target": item}
        forbidden.append({
            "target": _text(raw.get("target") or raw.get("path") or raw.get("meaning") or "", MAX_IMPACT_PATH),
            "path": _path(raw.get("path") or raw.get("target") or ""),
            "meaning": _text(raw.get("meaning") or raw.get("reason") or "out of scope", MAX_IMPACT_TEXT),
            "provenance": _source_refs(raw.get("provenance") or raw.get("evidence"), fallback=anchor_source, limit=2) or [anchor_source],
        })

    relation_expectations = relations
    if not relation_expectations:
        # Preserve current semantic topology as compact evidence when the
        # request explicitly changes a contract/public/state boundary.
        for fact in neighborhood:
            if str(fact.get("state") or "").upper() != "VERIFIED":
                continue
            relation = str(fact.get("relation") or "").upper()
            if relation not in {"CALLS", "READS_FIELD", "EXPECTS_RETURN_SHAPE", "RETURNS_TYPE", "EXPORTS", "EXPORTED_BY", "TRANSITIONS", "HAS_INVARIANT", "DECLARES_TYPE", "DECLARES_FIELD", "READS_CONFIG"}:
                continue
            relation_expectations.append(_relation_record({
                "subject": fact.get("subject"), "relation": relation, "object": fact.get("object"),
                "before": fact.get("object"), "after": fact.get("object"), "required": False,
                "category": kind, "provenance": fact.get("provenance", []),
            }, fallback_source=anchor_source))
            if len(relation_expectations) >= MAX_EXPECTED_RELATION_DELTAS:
                break

    raw_evidence = evidence
    if raw_evidence is None:
        raw_evidence = task_value.get("evidence") or execution.get("relevant_repository_facts") or []
    if isinstance(raw_evidence, (str, Mapping)):
        raw_evidence = [raw_evidence]
    evidence_refs = _source_refs(raw_evidence, fallback=anchor_source, limit=MAX_IMPACT_EVIDENCE_ITEMS)
    for fact in neighborhood:
        for provenance in list(fact.get("provenance", []) or [])[:1]:
            evidence_refs.extend(_source_refs(provenance, limit=1))
            if len(evidence_refs) >= MAX_IMPACT_EVIDENCE_ITEMS:
                break
        if len(evidence_refs) >= MAX_IMPACT_EVIDENCE_ITEMS:
            break
    evidence_refs = _source_refs(evidence_refs, limit=MAX_IMPACT_EVIDENCE_ITEMS)

    contract = PreMutationImpactContract({
        "schema_version": PRE_MUTATION_IMPACT_SCHEMA_VERSION,
        "task_id": _text(task_id, 160),
        "change_intent": {
            "text": intent_text,
            "category": kind,
            "required": bool(mutation_required),
            "provenance": [anchor_source],
        },
        "root_goal": _text(root_goal or task_value.get("root_goal") or "", 700),
        "parent_goal": _text(parent_goal or task_value.get("parent_goal") or "", 700),
        "local_task": local,
        "group_goal": _text(group_goal or task_value.get("semantic_group_goal") or "", 700),
        "group_invariant": _text(group_invariant or task_value.get("semantic_group_invariant") or "", 500),
        "expected_targets": targets,
        "expected_relationship_changes": relation_expectations[:MAX_EXPECTED_RELATION_DELTAS],
        "required_preservations": preservations,
        "verification_obligations": obligations[:MAX_IMPACT_OBLIGATIONS],
        "forbidden_or_out_of_scope": forbidden,
        "authorized_mutation_paths": allowed_paths,
        "evidence": evidence_refs,
        "revision": 0,
        "mutation_required": bool(mutation_required),
        "strict": bool(strict),
        "status": IMPACT_INCOMPLETE,
        "validation_status": IMPACT_INCOMPLETE,
        "controller_accepted": False,
        "bounds": {
            "max_targets": MAX_IMPACT_TARGETS,
            "max_obligations": MAX_IMPACT_OBLIGATIONS,
            "max_preservations": MAX_IMPACT_PRESERVATIONS,
            "max_relationship_deltas": MAX_EXPECTED_RELATION_DELTAS,
            "max_revisions": MAX_IMPACT_REVISIONS,
        },
    })
    return PreMutationImpactContract(_refresh_contract_hash(contract))


create_pre_mutation_impact_contract = build_pre_mutation_impact_contract
build_impact_contract = build_pre_mutation_impact_contract


def _target_tokens(value: Any) -> set[str]:
    return {item.casefold() for item in re.findall(r"[A-Za-z0-9_$./\\:-]+", str(value or "")) if item}


def _semantic_name_covered(name: Any, values: Iterable[Any]) -> bool:
    """Match a symbol name without treating arbitrary prose as coverage."""

    needle = str(name or "").strip().casefold()
    if not needle:
        return False
    escaped = re.escape(needle)
    for raw in values or []:
        candidate = str(raw or "").strip().casefold()
        if not candidate:
            continue
        if candidate == needle:
            return True
        leaf = re.split(r"[./\\: ]+", candidate)[-1]
        if leaf == needle:
            return True
        if re.search(r"(?<![a-z0-9_$])" + escaped + r"(?![a-z0-9_$])", candidate):
            return True
    return False


def _target_matches(target: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    expected_values = [target.get("target"), target.get("path"), *(target.get("aliases", []) or [])]
    actual_values = [actual.get("target"), actual.get("path"), *(actual.get("aliases", []) or [])]
    expected_tokens = _target_tokens(" ".join(str(item or "") for item in expected_values))
    actual_tokens = _target_tokens(" ".join(str(item or "") for item in actual_values))
    if not expected_tokens or not actual_tokens:
        return False
    if expected_tokens.intersection(actual_tokens):
        return True
    expected_text = str(target.get("target") or target.get("path") or "").replace("\\", "/").casefold()
    actual_text = str(actual.get("target") or actual.get("path") or "").replace("\\", "/").casefold()
    return bool(expected_text and actual_text and (expected_text.endswith(actual_text) or actual_text.endswith(expected_text)))


def _target_observed(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    world_model: Any = None,
) -> bool:
    """Match a changed file to a symbol only through known structure.

    A file edit is not, by itself, proof that an arbitrary symbol changed.
    When a bounded World Model definition/export relation connects the symbol
    to that file, the changed-file observation can establish the target slot.
    Otherwise callers may provide an explicit changed-symbol observation.
    """

    if _target_matches(expected, actual):
        return True
    if world_model is None:
        return False
    expected_target = str(expected.get("target") or expected.get("symbol") or "")
    actual_path = _path(actual.get("path") or actual.get("target") or "")
    if not expected_target or not actual_path:
        return False
    for fact in _current_world_facts(world_model, [expected_target]):
        relation = str(fact.get("relation") or "").upper()
        subject = str(fact.get("subject") or "")
        object_value = str(fact.get("object") or "")
        if relation == "DEFINED_IN":
            if subject.casefold() == expected_target.casefold() and _allowed_path(actual_path, [object_value]):
                return True
        elif relation == "MODULE_CONTAINS":
            if object_value.casefold() == expected_target.casefold() and _allowed_path(actual_path, [subject]):
                return True
        elif relation == "EXPORTED_BY":
            if subject.casefold() == expected_target.casefold() and _allowed_path(actual_path, [object_value]):
                return True
    return False


def _paths_related(path: str, target: Mapping[str, Any], world_model: Any = None) -> bool:
    path_folded = _path(path).casefold()
    if not path_folded:
        return False
    target_path = _path(target.get("path") or target.get("target") or "").casefold()
    if target_path and (path_folded == target_path or path_folded.endswith(target_path) or target_path.endswith(path_folded)):
        return True
    neighborhood = _neighborhood_facts(world_model, str(target.get("target") or ""), max_facts=MAX_IMPACT_NEIGHBORHOOD_FACTS)
    return any(
        path_folded == _path(item.get("object") or "").casefold()
        or path_folded == _path(item.get("subject") or "").casefold()
        for item in neighborhood
    )


def _allowed_path(path: str, allowed: Iterable[Any]) -> bool:
    path_folded = _path(path).casefold()
    if not path_folded:
        return False
    for raw in allowed or []:
        value = _path(raw).casefold()
        if value and (path_folded == value or path_folded.startswith(value.rstrip("/") + "/") or value.startswith(path_folded + "/")):
            return True
    return False


def _evidence_rows(values: Any) -> list[dict[str, Any]]:
    if isinstance(values, Mapping):
        values = [values]
    result = []
    for item in list(values or [])[:MAX_IMPACT_EVIDENCE_ITEMS * 2]:
        if not isinstance(item, Mapping):
            continue
        result.append(copy.deepcopy(dict(item)))
    return result


def _verification_evidence_satisfies(obligation: Mapping[str, Any], rows: list[dict[str, Any]], verification_result: Mapping[str, Any] | None) -> bool:
    if isinstance(verification_result, Mapping) and verification_result.get("passed") is True:
        if obligation.get("mode") == "controller":
            return True
    target_tokens = _target_tokens(obligation.get("target") or obligation.get("meaning") or "")
    for row in rows:
        if row.get("passed") is False or str(row.get("status") or "").upper() in {"FAIL", "FAILED", "ERROR"}:
            continue
        row_text = " ".join(str(row.get(key) or "") for key in ("tool", "target", "result", "summary", "evidence", "meaning"))
        if obligation.get("mode") == "controller" and row_text:
            return True
        if target_tokens and target_tokens.intersection(_target_tokens(row_text)):
            if any(token in row_text.casefold() for token in ("pass", "success", "assert", "verified", "ok", "green")):
                return True
    return False


def evaluate_verification_obligations(
    contract: Mapping[str, Any] | None,
    *,
    verification_evidence: Any = None,
    verification_result: Mapping[str, Any] | None = None,
    world_model: Any = None,
) -> list[dict[str, Any]]:
    value = _mapping(contract)
    rows = _evidence_rows(verification_evidence)
    current_facts = _current_world_facts(world_model)
    result = []
    for obligation in list(value.get("verification_obligations", []) or [])[:MAX_IMPACT_OBLIGATIONS]:
        item = copy.deepcopy(dict(obligation)) if isinstance(obligation, Mapping) else _obligation_record(obligation, len(result))
        target = str(item.get("target") or "").casefold()
        relation_covered = False
        if target:
            relation_covered = any(
                target in str(fact.get("subject") or "").casefold()
                or target in str(fact.get("object") or "").casefold()
                for fact in current_facts if str(fact.get("state") or "").upper() == "VERIFIED"
            )
        satisfied = relation_covered or _verification_evidence_satisfies(item, rows, verification_result)
        item["status"] = SATISFIED if satisfied else UNRESOLVED
        item["provenance"] = _source_refs(item.get("provenance"), limit=2)
        result.append(item)
    return result


def validate_pre_mutation_impact_contract(
    contract: Mapping[str, Any] | PreMutationImpactContract | None,
    *,
    world_model: Any = None,
    root_goal: Any = None,
    parent_goal: Any = None,
    local_task: Any = None,
    group_goal: Any = None,
    allowed_mutation_paths: Iterable[Any] | None = None,
    forbidden_paths: Iterable[Any] | None = None,
    require_authoritative_evidence: bool = False,
) -> dict[str, Any]:
    """Validate completeness and current semantic consistency before acceptance."""

    value = _mapping(contract)
    errors: list[dict[str, Any]] = []
    warnings: list[str] = []
    if value.get("schema_version") != PRE_MUTATION_IMPACT_SCHEMA_VERSION:
        errors.append({"code": IMPACT_INVALID, "reason": "impact contract schema version is invalid"})
    if value.get("contract_hash") and value.get("contract_hash") != canonical_hash(_contract_payload(value)):
        errors.append({"code": IMPACT_INVALID, "reason": "impact contract hash is invalid"})
    intent = value.get("change_intent") if isinstance(value.get("change_intent"), Mapping) else {}
    if not _text(intent.get("text") or value.get("local_task")):
        errors.append({"code": IMPACT_INCOMPLETE, "reason": "semantic change intent is missing"})
    targets = [item for item in list(value.get("expected_targets", []) or []) if isinstance(item, Mapping)]
    if not targets and value.get("mutation_required", True):
        errors.append({"code": IMPACT_INCOMPLETE, "reason": "expected mutation target surface is missing"})
    if len(targets) > MAX_IMPACT_TARGETS:
        errors.append({"code": IMPACT_INCOMPLETE, "reason": "expected target bound exceeded"})
    if targets and not any(str(item.get("target") or item.get("path") or "").strip() for item in targets):
        errors.append({"code": IMPACT_INCOMPLETE, "reason": "expected mutation target surface has no concrete target"})
    obligations = [item for item in list(value.get("verification_obligations", []) or []) if isinstance(item, Mapping)]
    if value.get("mutation_required", True) and not obligations:
        errors.append({"code": IMPACT_INCOMPLETE, "reason": "no verification obligation describes completion"})
    for obligation in obligations:
        if not str(obligation.get("meaning") or obligation.get("target") or "").strip():
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "verification obligation has no semantic meaning"})
    for preservation in list(value.get("required_preservations", []) or []):
        if not isinstance(preservation, Mapping):
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "preservation requirement is not structured"})
        elif not str(preservation.get("meaning") or preservation.get("target") or "").strip():
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "preservation requirement has no semantic meaning"})
    for relationship in list(value.get("expected_relationship_changes", []) or []):
        if not isinstance(relationship, Mapping):
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "expected relationship change is not structured"})
        elif not str(
            relationship.get("subject") or relationship.get("relation") or relationship.get("object")
            or relationship.get("after") or ""
        ).strip():
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "expected relationship change is not concrete"})
    for field, expected in (("root_goal", root_goal), ("parent_goal", parent_goal), ("local_task", local_task), ("group_goal", group_goal)):
        if expected not in (None, "") and _text(value.get(field), 900) != _text(expected, 900):
            errors.append({"code": "GOAL_ANCHOR_DRIFT", "field": field, "reason": "impact contract changed a stable goal anchor"})

    effective_allowed = list(allowed_mutation_paths or value.get("authorized_mutation_paths", []) or [])
    effective_forbidden = list(forbidden_paths or []) + [item.get("path") or item.get("target") for item in value.get("forbidden_or_out_of_scope", []) or [] if isinstance(item, Mapping)]
    for target in targets:
        path = target.get("path") or (target.get("target") if target.get("kind") == "path" else "")
        if path and effective_allowed and not _allowed_path(path, effective_allowed):
            errors.append({"code": UNEXPECTED_AND_OUT_OF_SCOPE, "target": target.get("target"), "reason": "expected target is outside authorized mutation paths"})
        if path and _allowed_path(path, effective_forbidden):
            errors.append({"code": UNEXPECTED_AND_OUT_OF_SCOPE, "target": target.get("target"), "reason": "expected target overlaps forbidden scope"})
        if require_authoritative_evidence and not target.get("provenance"):
            errors.append({"code": IMPACT_INCOMPLETE, "target": target.get("target"), "reason": "target has no provenance"})
    for item in targets + obligations + list(value.get("required_preservations", []) or []) + list(value.get("expected_relationship_changes", []) or []):
        if not isinstance(item, Mapping):
            continue
        if not item.get("provenance"):
            errors.append({"code": IMPACT_INCOMPLETE, "reason": "semantic contract item has no provenance", "item": item.get("target") or item.get("meaning") or item.get("relation")})

    stale_provenance = [
        reference for reference in _contract_provenance(value)
        if not _provenance_is_current(reference, world_model)
    ]
    if stale_provenance:
        errors.append({
            "code": IMPACT_STALE,
            "reason": "impact contract relies on source evidence whose fingerprint is no longer current",
            "source_identities": [
                _text(item.get("source_identity") or item.get("path"), 180)
                for item in stale_provenance[:MAX_IMPACT_EVIDENCE_ITEMS]
            ],
        })

    semantic_targets = [str(item.get("target") or "") for item in targets if item.get("target")]
    relevant_facts = _current_world_facts(world_model, semantic_targets[:6])
    stale_facts = [
        fact for fact in relevant_facts
        if str(fact.get("state") or "").upper() == "STALE"
    ]
    if stale_facts:
        errors.append({
            "code": IMPACT_STALE,
            "reason": "relevant World Model facts are stale and must be re-established before impact authorization",
            "fact_ids": [
                str(item.get("fact_id") or "")
                for item in stale_facts[:MAX_IMPACT_NEIGHBORHOOD_FACTS]
            ],
        })
    conflicts = [
        fact for fact in relevant_facts
        if str(fact.get("state") or "").upper() == "CONFLICTING"
    ]
    if conflicts:
        errors.append({
            "code": IMPACT_CONFLICT,
            "reason": "current authoritative World Model facts conflict on the impact surface",
            "fact_ids": [str(item.get("fact_id") or "") for item in conflicts[:MAX_IMPACT_NEIGHBORHOOD_FACTS]],
        })

    # A known producer/consumer surface cannot be omitted from a strict
    # contract migration.  The controller derives this from current typed
    # facts, not from child wording.
    category = str(intent.get("category") or "").upper()
    primary = {str(item.get("target") or "").casefold() for item in targets}
    known_consumers = {
        str(fact.get("subject") or "").casefold()
        for fact in relevant_facts
        if str(fact.get("state") or "").upper() == "VERIFIED"
        and str(fact.get("relation") or "").upper() == "CALLS"
        and str(fact.get("object") or "").casefold() in primary
    }
    if category in {PUBLIC_CONTRACT, TYPE_SCHEMA, CALLER_CONSUMER} and known_consumers:
        covered_consumers = {
            str(item.get("target") or item.get("meaning") or "").casefold()
            for item in targets + obligations + list(value.get("required_preservations", []) or [])
        }
        missing_consumers = sorted(
            item for item in known_consumers
            if not _semantic_name_covered(item, covered_consumers)
        )
        if missing_consumers:
            errors.append({
                "code": EXPECTED_BUT_MISSING,
                "reason": "known consumers of the changed contract are absent from the impact surface",
                "targets": missing_consumers[:MAX_IMPACT_TARGETS],
            })

    if value.get("revision", 0) > MAX_IMPACT_REVISIONS:
        errors.append({"code": IMPACT_REPLAN_REQUIRED, "reason": "impact contract revision bound exceeded"})
    status = IMPACT_CONFLICT if any(item.get("code") == IMPACT_CONFLICT for item in errors) else (
        IMPACT_STALE if stale_provenance or stale_facts else IMPACT_INCOMPLETE if errors else IMPACT_ACCEPTED
    )
    result = {
        "valid": not errors,
        "accepted": False,
        "status": status,
        "errors": errors[:24],
        "warnings": warnings[:8],
        "missing": [item for item in errors if item.get("code") == EXPECTED_BUT_MISSING],
        "conflicts": conflicts[:MAX_IMPACT_NEIGHBORHOOD_FACTS],
        "stale": [
            *stale_provenance[:MAX_IMPACT_EVIDENCE_ITEMS],
            *stale_facts[:MAX_IMPACT_NEIGHBORHOOD_FACTS],
        ][:MAX_IMPACT_EVIDENCE_ITEMS],
        "contract_hash": value.get("contract_hash"),
        "contract": value,
    }
    return result


validate_impact_contract = validate_pre_mutation_impact_contract


def accept_pre_mutation_impact_contract(
    contract: Mapping[str, Any] | PreMutationImpactContract | None,
    *,
    validation: Mapping[str, Any] | None = None,
    world_model: Any = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Stamp controller-only authorization after deterministic validation."""

    value = _mapping(contract)
    # ``validation`` is an observability/short-circuit hint only.  Acceptance
    # is a controller operation, so never trust a Worker-supplied ``valid``
    # bit or an otherwise detached validation object as authorization.
    checked = validate_pre_mutation_impact_contract(
        value, world_model=world_model, **kwargs,
    )
    if not checked.get("valid"):
        return {
            "accepted": False,
            "status": checked.get("status") or IMPACT_INVALID,
            "errors": list(checked.get("errors", []) or []),
            "contract": value,
        }
    accepted = _refresh_contract_hash(value)
    accepted["status"] = IMPACT_ACCEPTED
    accepted["validation_status"] = IMPACT_ACCEPTED
    accepted["controller_accepted"] = True
    accepted["accepted_contract_hash"] = accepted["contract_hash"]
    accepted["authorization_token"] = "IMPACT-AUTH-" + accepted["contract_hash"][:32].upper()
    accepted["authorization_reason"] = "deterministic controller validation passed"
    accepted = PreMutationImpactContract(accepted)
    return {
        "accepted": True,
        "status": IMPACT_ACCEPTED,
        "errors": [],
        "contract": accepted,
        "authorization_token": accepted["authorization_token"],
    }


accept_impact_contract = accept_pre_mutation_impact_contract


def impact_mutation_block_reason(
    contract: Mapping[str, Any] | PreMutationImpactContract | None,
    *,
    required: bool = True,
    world_model: Any = None,
) -> str | None:
    """Return a runtime error when the controller has not unlocked mutation."""

    if not required:
        return None
    value = _mapping(contract)
    if not value:
        return f"error: {IMPACT_REQUIRED}: no controller-accepted pre-mutation impact contract"
    if value.get("controller_accepted") is not True or value.get("status") != IMPACT_ACCEPTED:
        return f"error: {IMPACT_REQUIRED}: pre-mutation impact contract has not passed controller validation"
    expected_hash = canonical_hash(_contract_payload(value))
    if value.get("accepted_contract_hash") != expected_hash or value.get("contract_hash") != expected_hash:
        return f"error: {IMPACT_INVALID}: pre-mutation impact authorization is stale or forged"
    expected_token = "IMPACT-AUTH-" + expected_hash[:32].upper()
    if value.get("authorization_token") != expected_token:
        return f"error: {IMPACT_INVALID}: pre-mutation impact authorization token is stale or forged"
    if world_model is not None:
        validation = validate_pre_mutation_impact_contract(
            value, world_model=world_model,
        )
        if not validation.get("valid"):
            status = validation.get("status") or IMPACT_INVALID
            return f"error: {status}: accepted impact contract is no longer current"
    return None


mutation_authorization_block_reason = impact_mutation_block_reason


def _read_snapshot(path: Any, workspace: str | Path | None = None) -> tuple[bool, bytes | None, str]:
    raw = Path(str(path))
    if not raw.is_absolute() and workspace is not None:
        raw = Path(workspace) / raw
    try:
        resolved = raw.resolve()
        if not resolved.is_file():
            return False, None, _path(path)
        return True, resolved.read_bytes(), _path(path)
    except (OSError, RuntimeError, ValueError):
        return False, None, _path(path)


def _snapshot_value(value: Any) -> tuple[bool, bytes | None]:
    if isinstance(value, Mapping):
        existed = bool(value.get("existed", True))
        content = value.get("content")
    else:
        existed = value is not None
        content = value
    if isinstance(content, bytes):
        return existed, content
    if content is None:
        return existed, None
    return existed, str(content).encode("utf-8")


def _hash_content(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _current_source_hash(path: Path) -> str | None:
    """Hash a bounded provenance source without retaining its contents."""

    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        remaining = 8_000_000
        with path.open("rb") as handle:
            while remaining > 0:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                digest.update(block)
                remaining -= len(block)
        # A source larger than the bounded evidence model is not safe to
        # authenticate from a truncated fingerprint.
        return digest.hexdigest() if remaining > 0 else None
    except OSError:
        return None


def _provenance_is_current(reference: Any, world_model: Any) -> bool:
    """Check source hashes when the project root is available.

    Controller-only provenance deliberately has no source hash and remains a
    valid authority reference.  Repository-backed references, however, must
    still point inside this project's root and match the current bytes.
    """

    if not isinstance(reference, Mapping):
        return False
    expected = str(reference.get("source_hash") or reference.get("content_hash") or "").strip()
    if not expected or world_model is None:
        return True
    root_value = getattr(world_model, "project_root", None)
    raw_path = reference.get("path") or reference.get("source_path")
    if not root_value or not raw_path:
        return True
    try:
        root = Path(root_value).expanduser().resolve()
        candidate = Path(str(raw_path)).expanduser()
        resolved = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if resolved != root and root not in resolved.parents:
            return False
        current = _current_source_hash(resolved)
    except (OSError, RuntimeError, TypeError, ValueError):
        return False
    return bool(current and current == expected)


def _contract_provenance(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Return bounded source references from all semantic contract slots."""

    result: list[dict[str, Any]] = []
    for key in (
        "change_intent", "expected_targets", "expected_relationship_changes",
        "required_preservations", "verification_obligations",
        "forbidden_or_out_of_scope", "evidence",
    ):
        value = contract.get(key)
        rows = value if isinstance(value, list) else [value]
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            provenance = row.get("provenance")
            if isinstance(provenance, Mapping):
                provenance = [provenance]
            for reference in list(provenance or [])[:MAX_IMPACT_EVIDENCE_ITEMS]:
                if isinstance(reference, Mapping):
                    result.append(dict(reference))
                if len(result) >= MAX_IMPACT_EVIDENCE_ITEMS * 8:
                    return result
    return result


def capture_actual_mutation_impact(
    before: Mapping[str, Any] | None = None,
    after: Mapping[str, Any] | None = None,
    *,
    transaction: Mapping[str, Any] | None = None,
    workspace: str | Path | None = None,
    world_model: Any = None,
    changed_paths: Iterable[Any] | None = None,
    observed_targets: Iterable[Any] | None = None,
    observed_relationships: Iterable[Any] | None = None,
    preservation_violations: Iterable[Any] | None = None,
    verification_evidence: Iterable[Any] | None = None,
) -> dict[str, Any]:
    """Capture hashes/identifiers only; never retain an unbounded diff."""

    before_files = dict((before or {}).get("files", before or {})) if isinstance(before, Mapping) else {}
    after_files = dict((after or {}).get("files", after or {})) if isinstance(after, Mapping) else {}
    if isinstance(transaction, Mapping):
        for raw_path, snapshot in dict(transaction.get("files", {}) or {}).items():
            before_files.setdefault(str(raw_path), snapshot)
    # Keep one raw source key per normalized project-relative path.  The
    # transaction ledger can contain absolute keys while the mutation audit
    # normally reports relative keys.
    path_sources: dict[str, str] = {}
    for raw_path in list(before_files) + list(after_files) + list(changed_paths or []):
        normalized = _workspace_relative_path(raw_path, workspace)
        if normalized and normalized.casefold() not in {key.casefold() for key in path_sources}:
            path_sources[normalized] = str(raw_path)
        if len(path_sources) >= MAX_IMPACT_CHANGED_PATHS:
            break
    changed_input = {
        _workspace_relative_path(item, workspace).casefold()
        for item in list(changed_paths or [])
        if _workspace_relative_path(item, workspace)
    }

    def snapshot_for(files: Mapping[str, Any], raw_path: str, normalized: str):
        if raw_path in files:
            return files[raw_path]
        if normalized in files:
            return files[normalized]
        normalized_key = normalized.casefold()
        for key, value in files.items():
            if _workspace_relative_path(key, workspace).casefold() == normalized_key:
                return value
        return None

    records = []
    changed = []
    for path, raw_path in list(path_sources.items())[:MAX_IMPACT_CHANGED_PATHS]:
        old_snapshot = snapshot_for(before_files, raw_path, path)
        old_exists, old_content = _snapshot_value(old_snapshot) if old_snapshot is not None else (None, None)
        new_snapshot = snapshot_for(after_files, raw_path, path)
        if new_snapshot is not None:
            new_exists, new_content = _snapshot_value(new_snapshot)
        else:
            new_exists, new_content, _ = _read_snapshot(raw_path, workspace)
        changed_here = old_exists != new_exists or old_content != new_content
        if path.casefold() in changed_input:
            changed_here = True
        record = {
            "path": path,
            "before": {"existed": old_exists, "sha256": _hash_content(old_content)},
            "after": {"existed": new_exists, "sha256": _hash_content(new_content)},
            "changed": bool(changed_here),
        }
        records.append(record)
        if changed_here:
            changed.append(path)
    targets = []
    for item in list(observed_targets or [])[:MAX_IMPACT_ACTUAL_TARGETS]:
        targets.append(_target_record(item, required=False, fallback_source=_authority_source("observed post-mutation target")))
    changed_path_keys = {str(item.get("path") or "").casefold() for item in records if item.get("changed")}
    # Repository structure can identify symbols whose defining file changed.
    # These are observations for target matching only; they are not promoted
    # to semantic facts and therefore do not bypass post-mutation evidence.
    if world_model is not None and changed_path_keys:
        raw_facts = getattr(world_model, "facts", [])
        if callable(raw_facts):
            try:
                raw_facts = raw_facts()
            except Exception:
                raw_facts = []
        for raw_fact in list(raw_facts or []):
            fact = _fact_dict(raw_fact)
            relation = str(fact.get("relation") or "").upper()
            subject = str(fact.get("subject") or "")
            object_value = str(fact.get("object") or "")
            if relation == "DEFINED_IN" and _path(object_value).casefold() in changed_path_keys and subject:
                targets.append({
                    "target": subject,
                    "kind": "symbol",
                    "path": _path(object_value),
                    "aliases": [],
                    "provenance": [{
                        "source_identity": "mutation-audit:" + _path(object_value),
                        "path": _path(object_value),
                        "location": "changed source",
                        "evidence_kind": "changed_symbol_observation",
                    }],
                })
                if len(targets) >= MAX_IMPACT_ACTUAL_TARGETS:
                    break
    targets.extend({"target": item["path"], "kind": "path", "path": item["path"]} for item in records if item.get("changed"))
    return {
        "changed_paths": _unique(changed, MAX_IMPACT_CHANGED_PATHS),
        "files": records[:MAX_IMPACT_CHANGED_PATHS],
        "observed_targets": targets[:MAX_IMPACT_ACTUAL_TARGETS],
        "observed_relationships": [copy.deepcopy(dict(item)) if isinstance(item, Mapping) else {"relation": str(item)} for item in list(observed_relationships or [])[:MAX_EXPECTED_RELATION_DELTAS]],
        "preservation_violations": [copy.deepcopy(dict(item)) if isinstance(item, Mapping) else {"meaning": str(item)} for item in list(preservation_violations or [])[:MAX_IMPACT_PRESERVATIONS]],
        "verification_evidence": _evidence_rows(verification_evidence),
    }


capture_mutation_impact = capture_actual_mutation_impact


def _relation_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
    for key in ("subject", "relation"):
        expected_value = str(expected.get(key) or "").casefold()
        if expected_value and expected_value != str(actual.get(key) or "").casefold():
            return False
    expected_after = str(expected.get("after") or expected.get("object") or "").casefold()
    actual_after = str(actual.get("after") or actual.get("object") or "").casefold()
    return not expected_after or expected_after == actual_after


def compare_pre_mutation_impact(
    contract: Mapping[str, Any] | PreMutationImpactContract | None,
    actual: Mapping[str, Any] | None = None,
    *,
    world_model: Any = None,
    verification_evidence: Any = None,
    verification_result: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Compare bounded actual mutation/audit observations to the contract."""

    value = _mapping(contract)
    observed = _mapping(actual)
    if not value:
        return {"status": IMPACT_REQUIRED, "passed": False, "failure_type": IMPACT_REQUIRED, "comparisons": []}
    authorization_issue = impact_mutation_block_reason(
        value, required=True, world_model=world_model,
    )
    if authorization_issue:
        # A post-mutation comparison can still be diagnostic, but it is never
        # a successful authorization if the candidate itself was not accepted.
        return {"status": IMPACT_INVALID, "passed": False, "failure_type": IMPACT_INVALID, "reason": authorization_issue, "comparisons": []}
    actual_targets = list(observed.get("observed_targets", []) or [])
    actual_targets.extend({"target": path, "path": path, "kind": "path"} for path in observed.get("changed_paths", []) or [])
    actual_targets = actual_targets[:MAX_IMPACT_ACTUAL_TARGETS]
    comparisons: list[dict[str, Any]] = []
    missing: list[dict[str, Any]] = []
    for expected in list(value.get("expected_targets", []) or [])[:MAX_IMPACT_TARGETS]:
        matches = [
            item for item in actual_targets
            if isinstance(item, Mapping) and _target_observed(expected, item, world_model)
        ]
        if matches or not expected.get("required", True):
            comparisons.append({"kind": "target", "target": expected.get("target"), "status": EXPECTED_AND_OBSERVED if matches else NOT_APPLICABLE, "actual": matches[:2]})
        else:
            row = {"kind": "target", "target": expected.get("target"), "status": EXPECTED_BUT_MISSING, "reason": "required expected target was not observed"}
            comparisons.append(row)
            missing.append(row)

    changed_paths = list(observed.get("changed_paths", []) or [])[:MAX_IMPACT_CHANGED_PATHS]
    expected_paths = [str(item.get("path") or item.get("target") or "") for item in value.get("expected_targets", []) or [] if isinstance(item, Mapping)]
    forbidden = [str(item.get("path") or item.get("target") or "") for item in value.get("forbidden_or_out_of_scope", []) or [] if isinstance(item, Mapping)]
    unexpected_related: list[dict[str, Any]] = []
    out_of_scope: list[dict[str, Any]] = []
    for path in changed_paths:
        if any(_allowed_path(path, [expected]) for expected in expected_paths if expected):
            continue
        if _allowed_path(path, forbidden) or (value.get("authorized_mutation_paths") and not _allowed_path(path, value.get("authorized_mutation_paths", []))):
            row = {"path": path, "status": UNEXPECTED_AND_OUT_OF_SCOPE, "reason": "changed path is outside the accepted impact surface"}
            out_of_scope.append(row)
            comparisons.append(row)
            continue
        related_target = next((target for target in value.get("expected_targets", []) or [] if isinstance(target, Mapping) and _paths_related(path, target, world_model)), None)
        row = {"path": path, "status": UNEXPECTED_BUT_RELATED if related_target else UNEXPECTED_AND_OUT_OF_SCOPE, "reason": "changed path was not predicted by the accepted impact contract", "related_to": related_target.get("target") if related_target else None}
        (unexpected_related if related_target else out_of_scope).append(row)
        comparisons.append(row)

    expected_relations = [item for item in list(value.get("expected_relationship_changes", []) or []) if isinstance(item, Mapping)]
    actual_relations = [item for item in list(observed.get("observed_relationships", []) or []) if isinstance(item, Mapping)]
    relation_query_targets = [
        str(item.get("target") or "")
        for item in value.get("expected_targets", []) or []
        if isinstance(item, Mapping) and item.get("target")
    ]
    relation_query_targets.extend(
        str(item.get(key) or "")
        for item in expected_relations
        for key in ("subject", "object", "after")
        if item.get(key)
    )
    current_facts = _current_world_facts(world_model, relation_query_targets[:MAX_IMPACT_TARGETS])
    current_conflicts = [
        fact for fact in current_facts
        if str(fact.get("state") or "").upper() == "CONFLICTING"
    ]
    for fact in current_conflicts[:MAX_IMPACT_NEIGHBORHOOD_FACTS]:
        comparisons.append({
            "kind": "world_model_conflict",
            "fact_id": fact.get("fact_id"),
            "subject": fact.get("subject"),
            "relation": fact.get("relation"),
            "object": fact.get("object"),
            "status": CONFLICTING,
            "provenance": list(fact.get("provenance", []) or [])[:2],
        })
    for expected in expected_relations[:MAX_EXPECTED_RELATION_DELTAS]:
        matches = [item for item in actual_relations if _relation_matches(expected, item)]
        if not matches:
            matches = [fact for fact in current_facts if str(fact.get("state") or "").upper() == "VERIFIED" and _relation_matches(expected, fact)]
        if matches:
            comparisons.append({"kind": "relationship", "relation": expected.get("relation"), "subject": expected.get("subject"), "status": EXPECTED_AND_OBSERVED, "actual": matches[:2]})
        elif expected.get("required", True):
            row = {"kind": "relationship", "relation": expected.get("relation"), "subject": expected.get("subject"), "status": UNRESOLVED, "reason": "required semantic relationship was not observable"}
            comparisons.append(row)
            missing.append(row)

    preservation_violations = []
    for item in list(observed.get("preservation_violations", []) or [])[:MAX_IMPACT_PRESERVATIONS]:
        row = copy.deepcopy(dict(item)) if isinstance(item, Mapping) else {"meaning": str(item)}
        row["status"] = PRESERVATION_VIOLATED
        preservation_violations.append(row)
        comparisons.append(row)

    obligation_rows = evaluate_verification_obligations(
        value,
        verification_evidence=list(observed.get("verification_evidence", []) or []) + _evidence_rows(verification_evidence),
        verification_result=verification_result,
        world_model=world_model,
    )
    comparisons.extend({"kind": "verification_obligation", "id": item.get("id"), "status": item.get("status")} for item in obligation_rows)
    unresolved_obligations = [item for item in obligation_rows if item.get("required", True) and item.get("status") != SATISFIED]
    conflicts = [item for item in comparisons if item.get("status") == CONFLICTING]
    hard_failure = bool(out_of_scope or preservation_violations)
    # A related-but-unpredicted mutation is not automatically safe.  The
    # controller may revise the contract once, but the raw comparison remains
    # incomplete until that revision is accepted.
    unresolved = bool(missing or unresolved_obligations or unexpected_related)
    if conflicts:
        status = IMPACT_CONFLICT
    elif hard_failure:
        status = IMPACT_FAILED
    elif unresolved:
        status = IMPACT_VERIFICATION_FAILED
    else:
        status = IMPACT_PASSED
    result = {
        "status": status,
        "passed": status == IMPACT_PASSED,
        "failure_type": None if status == IMPACT_PASSED else status,
        "comparisons": comparisons[:MAX_IMPACT_TARGETS + MAX_EXPECTED_RELATION_DELTAS + MAX_IMPACT_OBLIGATIONS + MAX_IMPACT_CHANGED_PATHS],
        "missing": missing[:MAX_IMPACT_TARGETS + MAX_EXPECTED_RELATION_DELTAS],
        "unexpected_related": unexpected_related[:MAX_IMPACT_CHANGED_PATHS],
        "out_of_scope": out_of_scope[:MAX_IMPACT_CHANGED_PATHS],
        "preservation_violations": preservation_violations[:MAX_IMPACT_PRESERVATIONS],
        "obligations": obligation_rows[:MAX_IMPACT_OBLIGATIONS],
        "unresolved_obligations": unresolved_obligations[:MAX_IMPACT_OBLIGATIONS],
        "conflicts": conflicts[:MAX_IMPACT_NEIGHBORHOOD_FACTS],
        "actual_changed_paths": changed_paths,
        "contract_hash": value.get("contract_hash"),
        "revision": value.get("revision", 0),
        "bounded": True,
    }
    return result


compare_impact_contract = compare_pre_mutation_impact
verify_pre_mutation_impact = compare_pre_mutation_impact


def revise_pre_mutation_impact_contract(
    contract: Mapping[str, Any] | PreMutationImpactContract,
    discovered_targets: Iterable[Any],
    *,
    evidence: Iterable[Any] | None = None,
    world_model: Any = None,
    reason: str = "bounded related impact expansion",
    max_revisions: int = MAX_IMPACT_REVISIONS,
) -> dict[str, Any]:
    """Add only bounded, provenance-backed targets related to the contract."""

    value = _mapping(contract)
    revision = int(value.get("revision", 0) or 0)
    if revision >= min(MAX_IMPACT_REVISIONS, int(max_revisions)):
        value["status"] = IMPACT_REPLAN_REQUIRED
        return {"status": IMPACT_REPLAN_REQUIRED, "revised": False, "reason": "impact contract revision bound exhausted", "contract": value}
    rows = list(discovered_targets or [])[:MAX_IMPACT_TARGETS]
    existing = {str(item.get("target") or "").casefold() for item in value.get("expected_targets", []) or [] if isinstance(item, Mapping)}
    anchors = [item for item in value.get("expected_targets", []) or [] if isinstance(item, Mapping)]
    additions = []
    for raw in rows:
        candidate = _target_record(raw, required=True, fallback_source=_authority_source(reason, task_id=value.get("task_id")))
        if not candidate.get("provenance") or all(not item.get("path") and not item.get("source_identity") for item in candidate.get("provenance", [])):
            continue
        key = str(candidate.get("target") or "").casefold()
        if not key or key in existing:
            continue
        related = any(
            _target_matches(anchor, candidate)
            or _paths_related(candidate.get("path") or candidate.get("target"), anchor, world_model)
            for anchor in anchors
        )
        if not related and world_model is not None:
            facts = _neighborhood_facts(world_model, candidate.get("target") or "", max_facts=MAX_IMPACT_NEIGHBORHOOD_FACTS)
            related = any(
                str(fact.get("subject") or "").casefold() in existing
                or str(fact.get("object") or "").casefold() in existing
                for fact in facts if str(fact.get("state") or "").upper() == "VERIFIED"
            )
        if not related:
            value["status"] = IMPACT_REPLAN_REQUIRED
            return {"status": IMPACT_REPLAN_REQUIRED, "revised": False, "reason": "discovered target is not structurally related to the accepted impact surface", "contract": value, "rejected_target": candidate}
        additions.append(candidate)
        existing.add(key)
        if len(value.get("expected_targets", []) or []) + len(additions) >= MAX_IMPACT_TARGETS:
            break
    if not additions:
        value["status"] = IMPACT_REPLAN_REQUIRED
        return {"status": IMPACT_REPLAN_REQUIRED, "revised": False, "reason": "no bounded related target could be added", "contract": value}
    value["expected_targets"] = list(value.get("expected_targets", []) or []) + additions
    value["evidence"] = _source_refs(list(value.get("evidence", []) or []) + list(evidence or []), limit=MAX_IMPACT_EVIDENCE_ITEMS)
    value["revision"] = revision + 1
    value["status"] = IMPACT_INCOMPLETE
    value["validation_status"] = IMPACT_INCOMPLETE
    value["controller_accepted"] = False
    value.pop("accepted_contract_hash", None)
    value.pop("authorization_token", None)
    value["revision_reason"] = _text(reason, 300)
    value = PreMutationImpactContract(_refresh_contract_hash(value))
    return {"status": IMPACT_INCOMPLETE, "revised": True, "contract": value, "added_targets": additions, "revision": value["revision"]}


revise_impact_contract = revise_pre_mutation_impact_contract


def project_impact_contract(contract: Mapping[str, Any] | PreMutationImpactContract | None, *, max_chars: int = MAX_IMPACT_PROJECTION_CHARS) -> dict[str, Any]:
    """Project the minimum stable impact information into Worker context."""

    value = _mapping(contract)
    projection = {
        "contract_id": value.get("contract_id"),
        "contract_hash": value.get("contract_hash"),
        "change_intent": copy.deepcopy(value.get("change_intent", {})),
        "expected_targets": [
            {
                "target": item.get("target"), "kind": item.get("kind"),
                "categories": list(item.get("categories", []) or [])[:3],
                "required": bool(item.get("required", True)),
            }
            for item in list(value.get("expected_targets", []) or [])[:MAX_IMPACT_TARGETS]
            if isinstance(item, Mapping)
        ],
        "expected_relationship_changes": [
            {"subject": item.get("subject"), "relation": item.get("relation"), "object": item.get("object"), "after": item.get("after"), "required": item.get("required", True)}
            for item in list(value.get("expected_relationship_changes", []) or [])[:MAX_EXPECTED_RELATION_DELTAS]
            if isinstance(item, Mapping)
        ],
        "required_preservations": [
            {"id": item.get("id"), "meaning": item.get("meaning"), "required": item.get("required", True)}
            for item in list(value.get("required_preservations", []) or [])[:MAX_IMPACT_PRESERVATIONS]
            if isinstance(item, Mapping)
        ],
        "verification_obligations": [
            {"id": item.get("id"), "category": item.get("category"), "meaning": item.get("meaning"), "required": item.get("required", True)}
            for item in list(value.get("verification_obligations", []) or [])[:MAX_IMPACT_OBLIGATIONS]
            if isinstance(item, Mapping)
        ],
        "forbidden_or_out_of_scope": [
            {"target": item.get("target"), "path": item.get("path"), "meaning": item.get("meaning")}
            for item in list(value.get("forbidden_or_out_of_scope", []) or [])[:MAX_IMPACT_CHANGED_PATHS]
            if isinstance(item, Mapping)
        ],
        "revision": value.get("revision", 0),
        "status": value.get("status"),
    }
    rendered = json.dumps(projection, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    projection["rendered"] = rendered[:max(200, min(MAX_IMPACT_PROJECTION_CHARS, int(max_chars)))]
    projection["bounded"] = len(projection["rendered"]) <= max_chars
    return projection


impact_contract_projection = project_impact_contract


def benchmark_impact_contract_scenarios() -> dict[str, Any]:
    """Run a small deterministic contract-vs-observation benchmark."""

    class _BenchmarkWorldModel:
        """Minimal structural fixture for the related-expansion scenario."""

        def neighborhood(self, target, **_kwargs):
            if str(target) == "src/a.py":
                return {
                    "facts": [{
                        "fact_id": "bench-a-imports-b",
                        "subject": "src/a.py",
                        "relation": "IMPORTS",
                        "object": "src/b.py",
                        "state": "VERIFIED",
                        "provenance": [{
                            "source_identity": "benchmark:src/a.py",
                            "path": "src/a.py",
                            "location": "fixture",
                            "evidence_kind": "import_discovery",
                        }],
                    }],
                    "hops": 1,
                    "bounded": True,
                }
            return {"facts": [], "hops": 0, "bounded": True}

    scenarios = [
        ("direct_pass", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}]}, {"changed_paths": ["src/a.py"], "verification_evidence": [{"status": "PASS", "target": "src/a.py"}]}),
        ("missing_target", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}]}, {"changed_paths": [], "verification_evidence": [{"status": "PASS"}]}),
        ("unrelated_path", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}], "authorized_mutation_paths": ["src/a.py"]}, {"changed_paths": ["src/other.py"]}),
        ("forbidden_path", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}], "forbidden_or_out_of_scope": [{"path": "tests/"}]}, {"changed_paths": ["tests/test_a.py"]}),
        ("preservation_failure", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}]}, {"changed_paths": ["src/a.py"], "preservation_violations": [{"meaning": "public return shape changed"}]}),
        ("second_target", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}, {"target": "src/b.py", "path": "src/b.py", "required": False}]}, {"changed_paths": ["src/a.py"]}),
        ("verification_unresolved", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}], "verification_obligations": [{"id": "test", "meaning": "direct behavior test", "target": "src/a.py"}]}, {"changed_paths": ["src/a.py"]}),
        ("verification_pass", {"expected_targets": [{"target": "src/a.py", "path": "src/a.py"}], "verification_obligations": [{"id": "test", "meaning": "direct behavior test", "target": "src/a.py"}]}, {"changed_paths": ["src/a.py"], "verification_evidence": [{"status": "PASS", "target": "src/a.py", "result": "assert passed"}]}),
        ("config_surface", {"expected_targets": [{"target": "config", "kind": "symbol"}]}, {"observed_targets": [{"target": "config"}], "verification_evidence": [{"status": "PASS"}]}),
        ("no_mutation_required", {"expected_targets": [], "mutation_required": False}, {"changed_paths": []}),
        ("semantic_mismatch", {
            "expected_targets": [{"target": "A", "path": "src/a.py"}],
            "expected_relationship_changes": [{
                "subject": "A", "relation": "RETURNS_TYPE", "object": "NewType",
            }],
        }, {
            "changed_paths": ["src/a.py"],
            "observed_relationships": [{
                "subject": "A", "relation": "RETURNS_TYPE", "object": "OldType",
            }],
        }),
        ("related_expansion", {
            "expected_targets": [{"target": "src/a.py", "path": "src/a.py"}],
        }, {"changed_paths": ["src/a.py", "src/b.py"]}, _BenchmarkWorldModel()),
        ("incomplete_contract", None, {"changed_paths": ["src/a.py"]}),
    ]
    counts = {
        "contracts_evaluated": 0, "accepted_pre_mutation": 0,
        "contracts_rejected_incomplete": 0,
        "expected_impacts_correctly_predicted": 0, "missing_impacts_detected": 0,
        "unexpected_behavior_differences_detected": 0,
        "unrelated_mutations_detected": 0,
        "legitimate_related_expansions_accepted": 0,
        "preservation_violations_caught": 0,
        "unresolved_required_obligations": 0, "incorrect_successful_mutations_allowed": 0,
        "false_positive_out_of_scope_detections": 0, "false_negative_unexpected_mutations": 0,
        "semantic_mismatches_detected": 0,
        "average_expected_targets_per_contract": 0.0,
        "average_contract_revisions": 0.0,
    }
    total_targets = 0
    total_revisions = 0
    for scenario in scenarios:
        _name, fields, actual = scenario[:3]
        world_model = scenario[3] if len(scenario) > 3 else None
        if fields is None:
            # Deliberately incomplete controller input: the benchmark must
            # measure rejection instead of counting an unsupported contract as
            # an accepted mutation plan.
            contract = PreMutationImpactContract({
                "schema_version": PRE_MUTATION_IMPACT_SCHEMA_VERSION,
                "task_id": _name,
                "change_intent": {"text": "bounded impact benchmark", "category": DIRECT_IMPLEMENTATION},
                "expected_targets": [{"target": "src/a.py", "path": "src/a.py", "required": True, "provenance": []}],
                "verification_obligations": [{"id": "post-state", "meaning": "observable result", "required": True, "provenance": []}],
                "mutation_required": True,
            })
        else:
            contract = build_pre_mutation_impact_contract(
                {"id": _name, "goal": "bounded impact benchmark", **fields},
                expected_targets=fields.get("expected_targets"),
                expected_relationship_changes=fields.get("expected_relationship_changes"),
                verification_obligations=fields.get("verification_obligations"),
                mutation_required=fields.get("mutation_required", True),
                forbidden_or_out_of_scope=fields.get("forbidden_or_out_of_scope"),
            )
        # Benchmark candidates use only the deterministic controller source;
        # no model-generated acceptance is involved.
        accepted = accept_pre_mutation_impact_contract(contract, world_model=world_model)
        counts["contracts_evaluated"] += 1
        if not accepted.get("accepted"):
            counts["contracts_rejected_incomplete"] += 1
            continue
        counts["accepted_pre_mutation"] += 1
        accepted_contract = accepted["contract"]
        total_targets += len(accepted_contract.get("expected_targets", []) or [])
        comparison = compare_pre_mutation_impact(
            accepted_contract, actual, world_model=world_model,
            verification_result={"passed": True},
        )
        if comparison.get("passed"):
            counts["expected_impacts_correctly_predicted"] += 1
        if comparison.get("missing"):
            counts["missing_impacts_detected"] += 1
        if any(item.get("kind") == "relationship" for item in comparison.get("missing", [])):
            counts["semantic_mismatches_detected"] += 1
            counts["unexpected_behavior_differences_detected"] += 1
        if comparison.get("out_of_scope"):
            counts["unrelated_mutations_detected"] += 1
        if comparison.get("preservation_violations"):
            counts["preservation_violations_caught"] += 1
        if comparison.get("unresolved_obligations"):
            counts["unresolved_required_obligations"] += 1
        if comparison.get("passed") and (comparison.get("out_of_scope") or comparison.get("preservation_violations")):
            counts["incorrect_successful_mutations_allowed"] += 1
        if comparison.get("out_of_scope") and not actual.get("changed_paths"):
            counts["false_positive_out_of_scope_detections"] += 1
        if actual.get("changed_paths") and not comparison.get("out_of_scope") and any(path == "src/other.py" for path in actual.get("changed_paths", [])):
            counts["false_negative_unexpected_mutations"] += 1
        if comparison.get("unexpected_related"):
            related_path = comparison["unexpected_related"][0].get("path")
            revised = revise_pre_mutation_impact_contract(
                accepted_contract,
                [{"target": related_path, "path": related_path, "provenance": [{
                    "source_identity": "benchmark:" + str(related_path),
                    "path": related_path,
                    "location": "fixture",
                    "evidence_kind": "bounded_related_discovery",
                }]}],
                world_model=world_model,
            )
            if revised.get("revised"):
                total_revisions += 1
                revised_acceptance = accept_pre_mutation_impact_contract(
                    revised["contract"], world_model=world_model,
                )
                if revised_acceptance.get("accepted"):
                    revised_comparison = compare_pre_mutation_impact(
                        revised_acceptance["contract"], actual,
                        world_model=world_model,
                        verification_result={"passed": True},
                    )
                    if revised_comparison.get("passed"):
                        counts["legitimate_related_expansions_accepted"] += 1
    counts["average_expected_targets_per_contract"] = round(total_targets / max(1, counts["accepted_pre_mutation"]), 2)
    counts["average_contract_revisions"] = round(total_revisions / max(1, counts["contracts_evaluated"]), 2)
    counts["scenario_count"] = len(scenarios)
    counts["bounded"] = True
    return counts


benchmark_pre_mutation_impact = benchmark_impact_contract_scenarios


__all__ = [
    "PRE_MUTATION_IMPACT_SCHEMA_VERSION", "DIRECT_IMPLEMENTATION", "PUBLIC_CONTRACT",
    "CALLER_CONSUMER", "TYPE_SCHEMA", "STATE_TRANSITION", "EXPORT_PUBLIC_SURFACE",
    "TEST_BEHAVIOR", "CONFIGURATION", "INVARIANT", "DEPENDENCY", "SIDE_EFFECT",
    "IMPACT_CATEGORIES", "EXPECTED_AND_OBSERVED", "EXPECTED_BUT_MISSING",
    "UNEXPECTED_BUT_RELATED", "UNEXPECTED_AND_OUT_OF_SCOPE", "PRESERVATION_VIOLATED",
    "UNRESOLVED", "CONFLICTING", "IMPACT_ACCEPTED", "IMPACT_INCOMPLETE",
    "IMPACT_CONFLICT", "IMPACT_REQUIRED", "IMPACT_INVALID", "IMPACT_STALE", "IMPACT_VERIFICATION_FAILED",
    "IMPACT_REPLAN_REQUIRED", "IMPACT_PASSED", "IMPACT_FAILED", "SATISFIED", "FAILED",
    "NOT_APPLICABLE", "MAX_IMPACT_TARGETS", "MAX_IMPACT_OBLIGATIONS",
    "MAX_IMPACT_PRESERVATIONS", "MAX_EXPECTED_RELATION_DELTAS", "MAX_IMPACT_EVIDENCE_ITEMS",
    "MAX_IMPACT_ACTUAL_TARGETS", "MAX_IMPACT_CHANGED_PATHS", "MAX_IMPACT_REVISIONS",
    "MAX_IMPACT_CONTRACT_REVISIONS", "MAX_PRESERVATIONS",
    "MAX_IMPACT_NEIGHBORHOOD_FACTS", "MAX_IMPACT_PROJECTION_CHARS", "PreMutationImpactContract",
    "ImpactContract", "ImpactComparison", "canonical_hash", "build_pre_mutation_impact_contract",
    "create_pre_mutation_impact_contract", "build_impact_contract",
    "validate_pre_mutation_impact_contract", "validate_impact_contract",
    "accept_pre_mutation_impact_contract", "accept_impact_contract",
    "impact_mutation_block_reason", "mutation_authorization_block_reason",
    "capture_actual_mutation_impact", "capture_mutation_impact",
    "evaluate_verification_obligations", "compare_pre_mutation_impact",
    "compare_impact_contract", "verify_pre_mutation_impact",
    "revise_pre_mutation_impact_contract", "revise_impact_contract",
    "project_impact_contract", "impact_contract_projection",
    "benchmark_impact_contract_scenarios", "benchmark_pre_mutation_impact",
]
