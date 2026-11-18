"""Bounded semantic validation for candidate task decompositions.

The existing decomposer remains responsible for proposing child missions.  This
module is the small deterministic refinement layer which decides whether those
missions are independently verifiable or must travel as one semantic work
group.  It consumes typed, provenance-backed ProjectWorldModel facts; it does
not build a repository-wide graph and it never stores worker reasoning.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

# Importing the relation constants in one place keeps this module compatible
# with the existing World Model without introducing a second fact vocabulary.
from .project_world_model import (
    CALLS,
    CONFLICTING,
    DECLARES_FIELD,
    DECLARES_TYPE,
    DEFINED_IN,
    DEPENDS_ON,
    EXPORTED_BY,
    EXPORTS,
    EXPECTS_RETURN_SHAPE,
    HAS_INVARIANT,
    IMPLEMENTS_CONTRACT,
    IMPORTS,
    MAX_WORLD_MODEL_PROVENANCE,
    PARTIAL,
    READS_CONFIG,
    READS_FIELD,
    RETURNS_TYPE,
    SIBLING_OF,
    STALE,
    TEST_ASSERTS_BEHAVIOR_OF,
    TESTED_BY,
    TRANSITIONS,
    VERIFIED,
)


SEMANTIC_COUPLING_SCHEMA_VERSION = "HIVO-SEMANTIC-COUPLING-V1"

# Coupling kinds are intentionally separate from ordinary execution edges.
SHARED_CONTRACT = "SHARED_CONTRACT"
SHARED_STATE_TRANSITION = "SHARED_STATE_TRANSITION"
SHARED_INVARIANT = "SHARED_INVARIANT"
PRODUCER_CONSUMER = "PRODUCER_CONSUMER"
TYPE_SCHEMA_COUPLING = "TYPE_SCHEMA_COUPLING"
PUBLIC_SURFACE_COUPLING = "PUBLIC_SURFACE_COUPLING"
ORDER_DEPENDENT = "ORDER_DEPENDENT"
VERIFICATION_COUPLING = "VERIFICATION_COUPLING"
CONFIGURATION_COUPLING = "CONFIGURATION_COUPLING"

INDEPENDENT = "INDEPENDENT"
GROUP = "GROUP"
MERGE_REQUIRED = "MERGE_REQUIRED"
BLOCKED = "BLOCKED"

ANALYSIS_VALIDATED = "VALIDATED"
ANALYSIS_PARTIAL = "PARTIAL"
ANALYSIS_CONFLICTING = "CONFLICTING"

# These are deliberately smaller than the existing repository/evidence caps.
# The resolver should answer a decomposition question from a local semantic
# neighborhood, not turn decomposition into recursive repository crawling.
MAX_SEMANTIC_COUPLING_HOPS = 2
MAX_SEMANTIC_COUPLING_FACTS_PER_CHILD = 8
MAX_SEMANTIC_COUPLING_CHILDREN = 16
MAX_SEMANTIC_COUPLING_GROUPS = 8
MAX_SEMANTIC_GROUP_MEMBERS = 8
MAX_SEMANTIC_GROUP_FACTS = 12
MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS = 6
MAX_SEMANTIC_REPLAN_ATTEMPTS = 2
MAX_SEMANTIC_REASON_CHARS = 420
MAX_SEMANTIC_GOAL_CHARS = 520
MAX_SEMANTIC_INVARIANT_CHARS = 360

SEMANTIC_COUPLING_KINDS = (
    SHARED_CONTRACT,
    SHARED_STATE_TRANSITION,
    SHARED_INVARIANT,
    PRODUCER_CONSUMER,
    TYPE_SCHEMA_COUPLING,
    PUBLIC_SURFACE_COUPLING,
    ORDER_DEPENDENT,
    VERIFICATION_COUPLING,
    CONFIGURATION_COUPLING,
)

_RELATION_AUTHORITY = {
    IMPLEMENTS_CONTRACT: 120,
    DECLARES_TYPE: 118,
    DECLARES_FIELD: 116,
    RETURNS_TYPE: 112,
    EXPECTS_RETURN_SHAPE: 108,
    TEST_ASSERTS_BEHAVIOR_OF: 106,
    CALLS: 102,
    READS_FIELD: 100,
    TRANSITIONS: 100,
    HAS_INVARIANT: 100,
    EXPORTS: 98,
    EXPORTED_BY: 98,
    READS_CONFIG: 96,
    DEPENDS_ON: 92,
    IMPORTS: 90,
    TESTED_BY: 88,
    DEFINED_IN: 84,
    SIBLING_OF: 72,
}

AUTHORITY_RANKING = {
    "authoritative_specification": 130,
    "public_contract_or_schema": 120,
    "direct_behavior_test": 106,
    "actual_consumer_expectation": 102,
    "implementation": 84,
    "sibling_or_related_implementation": 72,
    "comment_or_indirect_mention": 20,
}

_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "before", "by", "change",
    "changes", "child", "children", "complete", "completion", "contract",
    "create", "current", "define", "declaration", "do", "ensure", "existing",
    "for", "from", "goal", "implement", "implementation", "in", "into", "is",
    "keep", "local", "make", "module", "of", "one", "parent", "preserve",
    "public", "return", "same", "schema", "semantic", "state", "task", "the",
    "then", "this", "to", "transition", "type", "update", "use", "using",
    "verify", "verification", "with", "without", "work", "worker", "and",
    "add", "added", "change", "changed", "changes", "fix", "fixed", "migrate",
    "migrated", "modify", "modified", "remove", "removed", "replace", "replaced",
    "first", "second", "half", "part", "piece", "portion", "branch", "condition",
    "guard", "unrelated",
})

_CONTRACT_RELATIONS = frozenset({
    IMPLEMENTS_CONTRACT, RETURNS_TYPE, DECLARES_TYPE, DECLARES_FIELD,
    EXPECTS_RETURN_SHAPE,
})
_CONSUMER_RELATIONS = frozenset({CALLS, READS_FIELD, EXPECTS_RETURN_SHAPE})
_TYPE_RELATIONS = frozenset({
    RETURNS_TYPE, DECLARES_TYPE, DECLARES_FIELD, IMPLEMENTS_CONTRACT,
})
_PUBLIC_RELATIONS = frozenset({EXPORTS, EXPORTED_BY, IMPORTS})
_TEST_RELATIONS = frozenset({TEST_ASSERTS_BEHAVIOR_OF, TESTED_BY})


def _text(value: Any, limit: int) -> str:
    cleaned = " ".join(str(value or "").split())
    return cleaned if len(cleaned) <= limit else cleaned[: max(0, limit - 3)] + "..."


def _unique(values: Iterable[Any], *, limit: int, item_limit: int = 220) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value, item_limit)
        key = item.casefold()
        if not item or key in seen:
            continue
        result.append(item)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def _tokens(value: Any) -> list[str]:
    raw = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", str(value or ""))
    result: list[str] = []
    seen: set[str] = set()
    for token in raw:
        key = token.casefold()
        if len(token) < 2 or key in _STOPWORDS or key in seen:
            continue
        seen.add(key)
        result.append(token)
    return result


def _alias_forms(value: Any) -> set[str]:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return set()
    forms: set[str] = {text.casefold()}
    for candidate in (
        text.rsplit("/", 1)[-1],
        text.rsplit("::", 1)[-1],
        text.rsplit(".", 1)[-1],
        text.split(":", 1)[0],
        Path(text).stem,
    ):
        if candidate:
            forms.add(candidate.casefold())
    for token in _tokens(text):
        forms.add(token.casefold())
    return forms


def _matches(value: Any, aliases: set[str]) -> bool:
    if not aliases:
        return False
    return bool(_alias_forms(value) & aliases)


def _normalise_relation(value: Any) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "").strip()).strip("_").upper()


def _normalise_state(value: Any) -> str:
    return str(value or VERIFIED).strip().upper()


def _fact_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Mapping):
        return dict(value)
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        try:
            result = to_dict()
        except Exception:
            return None
        return dict(result) if isinstance(result, Mapping) else None
    return None


def _fact_key(fact: Mapping[str, Any]) -> tuple[str, ...]:
    return (
        str(fact.get("fact_id", "")),
        str(fact.get("subject", "")).casefold(),
        _normalise_relation(fact.get("relation")),
        str(fact.get("object", "")).casefold(),
        _normalise_state(fact.get("state")),
    )


def _fact_authority(fact: Mapping[str, Any]) -> int:
    explicit = fact.get("authority_score")
    try:
        score = int(explicit)
    except (TypeError, ValueError):
        tier = str(fact.get("authority_tier", "MEDIUM")).upper()
        score = {"HIGH": 100, "MEDIUM": 60, "LOW": 20}.get(tier, 60)
    relation = _normalise_relation(fact.get("relation"))
    return score + _RELATION_AUTHORITY.get(relation, 0)


def _fact_source(fact: Mapping[str, Any]) -> dict[str, Any]:
    provenance = fact.get("provenance")
    if isinstance(provenance, Mapping):
        sources = [dict(provenance)]
    elif isinstance(provenance, list):
        sources = [dict(item) for item in provenance if isinstance(item, Mapping)]
    else:
        sources = []
    sources = sources[:MAX_WORLD_MODEL_PROVENANCE]
    try:
        authority_score = int(fact.get("authority_score", 0) or 0)
    except (TypeError, ValueError):
        authority_score = 0
    return {
        "fact_id": str(fact.get("fact_id", "")),
        "subject": _text(fact.get("subject"), 180),
        "relation": _normalise_relation(fact.get("relation")),
        "object": _text(fact.get("object"), 220),
        "state": _normalise_state(fact.get("state")),
        "authority_tier": str(fact.get("authority_tier", "MEDIUM")),
        "authority_score": authority_score,
        "provenance": sources,
    }


def _is_verified(fact: Mapping[str, Any]) -> bool:
    provenance = fact.get("provenance")
    has_provenance = bool(
        isinstance(provenance, Mapping)
        or (isinstance(provenance, (list, tuple)) and any(
            isinstance(item, Mapping) and item for item in provenance
        ))
    )
    return _normalise_state(fact.get("state")) == VERIFIED and has_provenance


def _public_child(child: Mapping[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in child.items()
        if not str(key).startswith("_")
    }


def _as_values(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _normalise_child(value: Any, index: int) -> dict[str, Any]:
    if isinstance(value, Mapping):
        child = dict(value)
    elif hasattr(value, "__dict__"):
        child = dict(vars(value))
    else:
        child = {"goal": str(value or "")}
    child_id = (
        child.get("child_id") or child.get("id") or child.get("task_id")
        or f"child_{index}"
    )
    child["id"] = str(child_id)
    child["goal"] = _text(child.get("goal") or child.get("objective") or child.get("description"), 900)
    child["done_when"] = _unique(
        _as_values(child.get("done_when") or child.get("success_criteria")),
        limit=8, item_limit=320,
    )
    child["scope_hint"] = _unique(
        _as_values(child.get("scope_hint") or child.get("paths") or child.get("files")),
        limit=8, item_limit=180,
    )
    raw_targets: list[Any] = []
    for key in ("targets", "symbols", "target", "symbol", "module", "path", "file", "files", "paths"):
        raw_targets.extend(_as_values(child.get(key)))
    explicit_targets = _unique(raw_targets, limit=8, item_limit=180)
    # Keep symbol-like goal terms ahead of paths/scope hints.  Approved plan
    # nodes commonly carry mutation paths, but the World Model is keyed by
    # semantic symbols; preserving both makes the bounded lookup useful for
    # those nodes without turning it into repository-wide search.
    goal_targets = _unique(_tokens(child["goal"]), limit=8, item_limit=180)
    targets = _unique(
        [*goal_targets, *explicit_targets, *child["scope_hint"], *child["done_when"]],
        limit=8, item_limit=180,
    )
    child["targets"] = targets
    child["verification_targets"] = _unique(
        _as_values(
            child.get("verification_targets") or child.get("verification")
            or child.get("tests") or child.get("required_tests")
        ),
        limit=MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS, item_limit=220,
    )
    child["dependencies"] = _unique(
        _as_values(child.get("dependencies") or child.get("depends_on")),
        limit=8, item_limit=120,
    )
    child["_aliases"] = set().union(*(_alias_forms(item) for item in child["targets"]))
    if not child["_aliases"]:
        child["_aliases"] = _alias_forms(child["id"])
    return child


def _source_facts_for_child(
    world_model: Any,
    child: Mapping[str, Any],
    *,
    max_hops: int,
    max_facts: int,
) -> list[dict[str, Any]]:
    if world_model is None:
        return []
    targets = list(child.get("targets", []) or [])
    if not targets:
        targets = list(child.get("_aliases", set()))[:4]
    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    neighborhood = getattr(world_model, "neighborhood", None)
    if callable(neighborhood):
        for target in targets[:4]:
            try:
                view = neighborhood(
                    target,
                    max_hops=max_hops,
                    max_facts=max_facts,
                    include_states=(VERIFIED, PARTIAL, CONFLICTING, STALE),
                )
            except TypeError:
                try:
                    view = neighborhood(target, max_hops=max_hops, max_facts=max_facts)
                except Exception:
                    continue
            except Exception:
                continue
            values = view.get("facts", []) if isinstance(view, Mapping) else []
            for value in values or []:
                fact = _fact_dict(value)
                if fact is None:
                    continue
                key = _fact_key(fact)
                if key in seen:
                    continue
                seen.add(key)
                rows.append(fact)
    if not rows:
        values = getattr(world_model, "facts", None)
        if callable(values):
            try:
                values = values()
            except Exception:
                values = []
        if isinstance(values, Iterable) and not isinstance(values, (str, bytes, Mapping)):
            for value in values:
                fact = _fact_dict(value)
                if fact is None or not (
                    _matches(fact.get("subject"), child.get("_aliases", set()))
                    or _matches(fact.get("object"), child.get("_aliases", set()))
                ):
                    continue
                key = _fact_key(fact)
                if key not in seen:
                    seen.add(key)
                    rows.append(fact)
    rows.sort(key=lambda item: (-_fact_authority(item), _fact_key(item)))
    return rows[:max_facts]


def _dependency_edges(value: Any) -> set[tuple[str, str]]:
    edges: set[tuple[str, str]] = set()
    if isinstance(value, Mapping):
        for target, sources in value.items():
            for source in _as_values(sources):
                if isinstance(source, Mapping):
                    source = source.get("id") or source.get("child_id") or source.get("source")
                if source:
                    edges.add((str(source), str(target)))
        raw_edges = value.get("edges")
        if raw_edges is not None:
            edges.update(_dependency_edges(raw_edges))
    else:
        for row in _as_values(value):
            if isinstance(row, (list, tuple)) and len(row) >= 2:
                edges.add((str(row[0]), str(row[1])))
                continue
            if not isinstance(row, Mapping):
                continue
            source = row.get("source") or row.get("from") or row.get("dependency")
            target = row.get("target") or row.get("to") or row.get("dependent")
            if source and target:
                edges.add((str(source), str(target)))
    return edges


def _transition_states(value: Any) -> tuple[str, ...]:
    text = str(value or "")
    pieces = re.split(r"\s*(?:->|→|=>|to)\s*", text, flags=re.IGNORECASE)
    if len(pieces) < 2:
        return ()
    return tuple(_text(piece, 90).casefold() for piece in pieces if _text(piece, 90))


def _meaningful_verification(child: Mapping[str, Any]) -> bool:
    if child.get("verification_targets"):
        return True
    text = " ".join(
        [child.get("goal", ""), *list(child.get("done_when", []) or [])]
    ).casefold()
    return bool(re.search(r"\b(test|assert|verify|validation|acceptance|integration)\w*\b", text))


def _shared_verification_target(
    left: Mapping[str, Any],
    right: Mapping[str, Any],
    parent_targets: Iterable[Any] | None = None,
) -> bool:
    """Return true only when one concrete target is assigned to both children."""
    left_targets = {
        str(item).casefold()
        for item in list(left.get("verification_targets", []) or [])
        if str(item).strip()
    }
    right_targets = {
        str(item).casefold()
        for item in list(right.get("verification_targets", []) or [])
        if str(item).strip()
    }
    if left_targets & right_targets:
        return True
    # A parent-level target can establish coupling only when it names both
    # local semantic targets.  A generic parent test target is insufficient;
    # otherwise every unrelated child in a parent with one test would group.
    shared_parent_targets = [str(item) for item in (parent_targets or ()) if str(item).strip()]
    left_aliases = set(left.get("_aliases", set()))
    right_aliases = set(right.get("_aliases", set()))
    for target in shared_parent_targets:
        aliases = _alias_forms(target)
        if aliases & left_aliases and aliases & right_aliases:
            return True
    return False


def _shared_source_subject(rows_a: Iterable[Mapping[str, Any]], rows_b: Iterable[Mapping[str, Any]], relations: set[str]) -> bool:
    subjects_a = {
        str(row.get("subject", "")).casefold()
        for row in rows_a if _normalise_relation(row.get("relation")) in relations
    }
    subjects_b = {
        str(row.get("subject", "")).casefold()
        for row in rows_b if _normalise_relation(row.get("relation")) in relations
    }
    return bool(subjects_a & subjects_b)


def _fact_touches_pair(fact: Mapping[str, Any], aliases_a: set[str], aliases_b: set[str]) -> bool:
    subject = fact.get("subject")
    object_value = fact.get("object")
    return (
        (_matches(subject, aliases_a) and _matches(object_value, aliases_b))
        or (_matches(subject, aliases_b) and _matches(object_value, aliases_a))
    )


def _evidence_rows(rows: Iterable[Mapping[str, Any]], limit: int = MAX_SEMANTIC_GROUP_FACTS) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for row in sorted(rows, key=lambda item: (-_fact_authority(item), _fact_key(item))):
        key = _fact_key(row)
        if key in seen:
            continue
        seen.add(key)
        selected.append(_fact_source(row))
        if len(selected) >= limit:
            break
    return selected


def _minimal_evidence_rows(kind: str, rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Choose the smallest structural witness for one coupling kind."""
    ordered = sorted(rows, key=lambda item: (-_fact_authority(item), _fact_key(item)))
    if not ordered:
        return []
    relation_limits = {
        PRODUCER_CONSUMER: ((CALLS, 1), (READS_FIELD, 1), (EXPECTS_RETURN_SHAPE, 1)),
        SHARED_CONTRACT: tuple((relation, 1) for relation in (
            IMPLEMENTS_CONTRACT, DECLARES_TYPE, DECLARES_FIELD, RETURNS_TYPE,
            EXPECTS_RETURN_SHAPE, CALLS, READS_FIELD,
        )),
        TYPE_SCHEMA_COUPLING: tuple((relation, 1) for relation in _TYPE_RELATIONS),
        PUBLIC_SURFACE_COUPLING: tuple((relation, 1) for relation in _PUBLIC_RELATIONS),
        SHARED_STATE_TRANSITION: ((TRANSITIONS, 2),),
        SHARED_INVARIANT: ((HAS_INVARIANT, 1),),
        CONFIGURATION_COUPLING: ((READS_CONFIG, 1),),
        VERIFICATION_COUPLING: tuple((relation, 1) for relation in _TEST_RELATIONS),
        MERGE_REQUIRED: ((TRANSITIONS, 2),),
    }.get(kind)
    if not relation_limits:
        return ordered[:2]
    selected: list[Mapping[str, Any]] = []
    seen: set[tuple[str, ...]] = set()
    for relation, limit in relation_limits:
        matches = [
            item for item in ordered
            if _normalise_relation(item.get("relation")) == relation
        ]
        for item in matches[:limit]:
            key = _fact_key(item)
            if key not in seen:
                selected.append(item)
                seen.add(key)
    if not selected:
        selected = ordered[:2]
    return selected[:MAX_SEMANTIC_GROUP_FACTS]


def _reason(kind: str, rows: Iterable[Mapping[str, Any]], fallback: str) -> str:
    row = next(iter(sorted(rows, key=lambda item: (-_fact_authority(item), _fact_key(item)))), None)
    if row is None:
        return _text(fallback, MAX_SEMANTIC_REASON_CHARS)
    source = _fact_source(row)
    provenance = source.get("provenance") or [{}]
    identity = provenance[0].get("source_identity") or provenance[0].get("path") or "repository evidence"
    return _text(
        f"{kind} is established by {source['subject']} {source['relation']} "
        f"{source['object']} ({identity}); the children share this semantic boundary.",
        MAX_SEMANTIC_REASON_CHARS,
    )


@dataclass(frozen=True)
class SemanticCoupling:
    """One evidence-backed relationship between candidate children."""

    children: tuple[str, ...]
    kind: str
    reason: str
    required_handling: str = GROUP
    evidence: tuple[dict[str, Any], ...] = ()
    state: str = VERIFIED

    def to_dict(self) -> dict[str, Any]:
        return {
            "children": list(self.children),
            "kind": self.kind,
            "reason": _text(self.reason, MAX_SEMANTIC_REASON_CHARS),
            "required_handling": self.required_handling,
            "state": self.state,
            "evidence": [dict(item) for item in self.evidence[:MAX_SEMANTIC_GROUP_FACTS]],
        }


@dataclass(frozen=True)
class SemanticWorkGroup:
    """Stable metadata shared by children that are one semantic unit."""

    group_id: str
    goal: str
    invariant: str
    member_ids: tuple[str, ...]
    coupling_types: tuple[str, ...]
    verification_targets: tuple[str, ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()
    status: str = "PLANNED"

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "goal": _text(self.goal, MAX_SEMANTIC_GOAL_CHARS),
            "invariant": _text(self.invariant, MAX_SEMANTIC_INVARIANT_CHARS),
            "member_ids": list(self.member_ids[:MAX_SEMANTIC_GROUP_MEMBERS]),
            "coupling_types": list(self.coupling_types),
            "verification_targets": list(self.verification_targets[:MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS]),
            "evidence": [dict(item) for item in self.evidence[:MAX_SEMANTIC_GROUP_FACTS]],
            "status": self.status,
            "verification_required": True,
        }


def _group_id(parent_goal: str, member_ids: Iterable[str], kinds: Iterable[str]) -> str:
    payload = json.dumps({
        "goal": _text(parent_goal, MAX_SEMANTIC_GOAL_CHARS),
        "members": sorted(str(item) for item in member_ids),
        "kinds": sorted(str(item) for item in kinds),
    }, sort_keys=True, separators=(",", ":"))
    return "SG-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12].upper()


def _group_invariant(kinds: Iterable[str], supplied: Iterable[Any] | None = None) -> str:
    supplied_text = _unique(supplied or (), limit=1, item_limit=MAX_SEMANTIC_INVARIANT_CHARS)
    if supplied_text:
        return supplied_text[0]
    values = set(kinds)
    if SHARED_STATE_TRANSITION in values:
        return "The complete state-transition chain preserves its required preconditions and final outcome."
    if PUBLIC_SURFACE_COUPLING in values:
        return "The implementation, public export surface, and public consumers remain compatible."
    if TYPE_SCHEMA_COUPLING in values:
        return "The declared type/schema and every participating behavior agree on one shape."
    if CONFIGURATION_COUPLING in values:
        return "The code and configuration agree on the same required runtime behavior."
    if SHARED_INVARIANT in values:
        return "Every participating child preserves the shared repository invariant."
    if VERIFICATION_COUPLING in values:
        return "The shared acceptance evidence passes for the combined behavioral change."
    return "All participating producers, declarations, and consumers agree on the same semantic contract."


def _group_goal(parent_goal: str, children: Iterable[Mapping[str, Any]]) -> str:
    targets = []
    for child in children:
        targets.extend(list(child.get("targets", []) or []))
    target_text = ", ".join(_unique(targets, limit=4, item_limit=100)) or "the coupled behavior"
    parent = _text(parent_goal, 260) or "the parent change"
    return _text(f"Keep {target_text} semantically coherent while completing: {parent}", MAX_SEMANTIC_GOAL_CHARS)


class SemanticCouplingAnalyzer:
    """Analyze and refine one bounded candidate decomposition."""

    def __init__(
        self,
        world_model: Any = None,
        *,
        max_hops: int = MAX_SEMANTIC_COUPLING_HOPS,
        max_facts_per_child: int = MAX_SEMANTIC_COUPLING_FACTS_PER_CHILD,
        max_children: int = MAX_SEMANTIC_COUPLING_CHILDREN,
        max_groups: int = MAX_SEMANTIC_COUPLING_GROUPS,
        max_replan_attempts: int = MAX_SEMANTIC_REPLAN_ATTEMPTS,
    ) -> None:
        self.world_model = world_model
        self.max_hops = max(0, min(MAX_SEMANTIC_COUPLING_HOPS, int(max_hops)))
        self.max_facts_per_child = max(1, min(MAX_SEMANTIC_COUPLING_FACTS_PER_CHILD, int(max_facts_per_child)))
        self.max_children = max(2, min(MAX_SEMANTIC_COUPLING_CHILDREN, int(max_children)))
        self.max_groups = max(1, min(MAX_SEMANTIC_COUPLING_GROUPS, int(max_groups)))
        self.max_replan_attempts = max(0, min(MAX_SEMANTIC_REPLAN_ATTEMPTS, int(max_replan_attempts)))

    def _facts(self, children: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
        return {
            child["id"]: _source_facts_for_child(
                self.world_model, child,
                max_hops=self.max_hops,
                max_facts=self.max_facts_per_child,
            )
            for child in children
        }

    @staticmethod
    def _conflicting_rows(facts: Mapping[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        seen: set[tuple[str, ...]] = set()
        for values in facts.values():
            for fact in values:
                if _normalise_state(fact.get("state")) != CONFLICTING:
                    continue
                key = _fact_key(fact)
                if key not in seen:
                    rows.append(fact)
                    seen.add(key)
        return _evidence_rows(rows, limit=MAX_SEMANTIC_GROUP_FACTS)

    def analyze(
        self,
        parent_goal: Any = "",
        candidate_children: Iterable[Any] | None = None,
        *,
        known_dependencies: Any = None,
        requirements: Iterable[Any] | None = None,
        invariants: Iterable[Any] | None = None,
        verification_targets: Iterable[Any] | None = None,
        parent_task: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if isinstance(parent_goal, Mapping) and parent_task is None:
            parent_task = parent_goal
            parent_goal = parent_task.get("goal", "")
        parent_goal = _text(parent_goal, MAX_SEMANTIC_GOAL_CHARS)
        requirement_values = _as_values(requirements)
        invariant_values = _as_values(invariants)
        verification_values = _as_values(verification_targets)
        children = [
            _normalise_child(value, index)
            for index, value in enumerate(list(candidate_children or [])[: self.max_children], 1)
        ]
        dependencies = _dependency_edges(known_dependencies)
        facts_by_child = self._facts(children)
        all_facts = []
        for values in facts_by_child.values():
            all_facts.extend(values)
        conflicts = self._conflicting_rows(facts_by_child)
        partial_rows = _evidence_rows(
            [row for row in all_facts if _normalise_state(row.get("state")) in {PARTIAL, STALE}],
            limit=MAX_SEMANTIC_GROUP_FACTS,
        )
        records: list[SemanticCoupling] = []
        record_keys: set[tuple[tuple[str, ...], str]] = set()
        group_edges: dict[tuple[str, str], set[str]] = {}
        merge_pairs: set[tuple[str, str]] = set()

        def add_record(
            left: Mapping[str, Any], right: Mapping[str, Any], kind: str,
            reason: str, rows: Iterable[Mapping[str, Any]], *,
            handling: str = GROUP,
        ) -> None:
            ids = tuple(sorted((str(left["id"]), str(right["id"]))))
            key = (ids, kind)
            if key in record_keys:
                return
            evidence = tuple(_evidence_rows(
                _minimal_evidence_rows(kind, rows),
                limit=MAX_SEMANTIC_GROUP_FACTS,
            ))
            records.append(SemanticCoupling(
                ids, kind, reason, handling, evidence,
                CONFLICTING if conflicts else VERIFIED,
            ))
            record_keys.add(key)
            if handling == GROUP and kind != ORDER_DEPENDENT:
                group_edges.setdefault(ids, set()).add(kind)
            if handling == MERGE_REQUIRED:
                merge_pairs.add(ids)

        for index, left in enumerate(children):
            left_rows = facts_by_child.get(left["id"], [])
            for right in children[index + 1:]:
                right_rows = facts_by_child.get(right["id"], [])
                pair_rows = [
                    row for row in all_facts
                    if _is_verified(row)
                    and _fact_touches_pair(row, left.get("_aliases", set()), right.get("_aliases", set()))
                ]
                direct_relations = {_normalise_relation(row.get("relation")) for row in pair_rows}

                producer_consumer_rows = [
                    row for row in pair_rows if _normalise_relation(row.get("relation")) in _CONSUMER_RELATIONS
                ]
                if producer_consumer_rows:
                    add_record(
                        left, right, PRODUCER_CONSUMER,
                        _reason(PRODUCER_CONSUMER, producer_consumer_rows,
                                "one candidate consumes the other candidate's behavior"),
                        producer_consumer_rows,
                    )

                contract_rows = [
                    row for row in pair_rows if _normalise_relation(row.get("relation")) in _CONTRACT_RELATIONS
                ]
                contract_terms = " ".join(
                    [str(value or "") for value in (
                        left.get("goal", ""), right.get("goal", ""), *requirement_values
                    )]
                ).casefold()
                if contract_rows or (producer_consumer_rows and re.search(r"\b(contract|return|shape|schema|type|field)\w*\b", contract_terms)):
                    add_record(
                        left, right, SHARED_CONTRACT,
                        _reason(SHARED_CONTRACT, contract_rows or producer_consumer_rows,
                                "the producer and consumer share a behavioral contract"),
                        contract_rows or producer_consumer_rows,
                    )

                type_rows = [
                    row for row in pair_rows if _normalise_relation(row.get("relation")) in _TYPE_RELATIONS
                ]
                # A schema/type child often connects through the type name,
                # not directly through the producer symbol.  Join verified
                # typed facts whose object/subject is shared by both local
                # neighborhoods, still within this bounded pair.
                if not type_rows:
                    for left_row in left_rows:
                        if not _is_verified(left_row) or _normalise_relation(left_row.get("relation")) not in _TYPE_RELATIONS:
                            continue
                        for right_row in right_rows:
                            if not _is_verified(right_row) or _normalise_relation(right_row.get("relation")) not in _TYPE_RELATIONS:
                                continue
                            if _alias_forms(left_row.get("object")) & _alias_forms(right_row.get("object")):
                                type_rows.extend((left_row, right_row))
                if type_rows:
                    add_record(
                        left, right, TYPE_SCHEMA_COUPLING,
                        _reason(TYPE_SCHEMA_COUPLING, type_rows,
                                "the children participate in one declared type or schema"),
                        type_rows,
                    )

                public_signal = bool(re.search(
                    r"\b(public|export|api|surface|barrel|re-?export|__all__)\w*\b",
                    " ".join(str(value or "") for value in (
                        parent_goal, left.get("goal", ""), right.get("goal", ""),
                    )).casefold(),
                ))
                public_rows = [
                    row for row in pair_rows
                    if _normalise_relation(row.get("relation")) in {EXPORTS, EXPORTED_BY}
                    or (
                        _normalise_relation(row.get("relation")) == IMPORTS
                        and public_signal
                    )
                ]
                if public_rows:
                    add_record(
                        left, right, PUBLIC_SURFACE_COUPLING,
                        _reason(PUBLIC_SURFACE_COUPLING, public_rows,
                                "the children share a public export/import surface"),
                        public_rows,
                    )

                invariant_rows = [
                    row for row in pair_rows if _normalise_relation(row.get("relation")) == HAS_INVARIANT
                ]
                if not invariant_rows:
                    left_invariants = [row for row in left_rows if _normalise_relation(row.get("relation")) == HAS_INVARIANT and _is_verified(row)]
                    right_invariants = [row for row in right_rows if _normalise_relation(row.get("relation")) == HAS_INVARIANT and _is_verified(row)]
                    for left_row in left_invariants:
                        for right_row in right_invariants:
                            if _alias_forms(left_row.get("object")) & _alias_forms(right_row.get("object")):
                                invariant_rows.extend((left_row, right_row))
                if invariant_rows:
                    add_record(
                        left, right, SHARED_INVARIANT,
                        _reason(SHARED_INVARIANT, invariant_rows,
                                "both children must preserve one repository invariant"),
                        invariant_rows,
                    )

                config_rows = [
                    row for row in pair_rows if _normalise_relation(row.get("relation")) == READS_CONFIG
                ]
                if not config_rows:
                    left_config = [row for row in left_rows if _normalise_relation(row.get("relation")) == READS_CONFIG and _is_verified(row)]
                    right_config = [row for row in right_rows if _normalise_relation(row.get("relation")) == READS_CONFIG and _is_verified(row)]
                    for left_row in left_config:
                        for right_row in right_config:
                            if _alias_forms(left_row.get("object")) & _alias_forms(right_row.get("object")):
                                config_rows.extend((left_row, right_row))
                if config_rows:
                    add_record(
                        left, right, CONFIGURATION_COUPLING,
                        _reason(CONFIGURATION_COUPLING, config_rows,
                                "both children define one configuration-dependent behavior"),
                        config_rows,
                    )

                left_transition_rows = [
                    row for row in left_rows
                    if _is_verified(row) and _normalise_relation(row.get("relation")) == TRANSITIONS
                ]
                right_transition_rows = [
                    row for row in right_rows
                    if _is_verified(row) and _normalise_relation(row.get("relation")) == TRANSITIONS
                ]
                transition_rows = left_transition_rows + right_transition_rows
                transition_chain = False
                for first in left_transition_rows:
                    first_states = _transition_states(first.get("object"))
                    for second in right_transition_rows:
                        second_states = _transition_states(second.get("object"))
                        if first_states and second_states and first_states[-1] == second_states[0]:
                            transition_chain = True
                            break
                    if transition_chain:
                        break
                if not transition_chain:
                    for first in right_transition_rows:
                        first_states = _transition_states(first.get("object"))
                        for second in left_transition_rows:
                            second_states = _transition_states(second.get("object"))
                            if first_states and second_states and first_states[-1] == second_states[0]:
                                transition_chain = True
                                break
                        if transition_chain:
                            break
                parent_transition_terms = re.search(
                    r"[A-Za-z0-9_$]+\s*(?:->|→|=>|to)\s*[A-Za-z0-9_$]+\s*(?:->|→|=>|to)",
                    parent_goal, re.IGNORECASE,
                )
                if transition_chain or (
                    left_transition_rows and right_transition_rows and parent_transition_terms
                ):
                    add_record(
                        left, right, SHARED_STATE_TRANSITION,
                        _reason(SHARED_STATE_TRANSITION, transition_rows,
                                "the children jointly define one state-transition chain"),
                        transition_rows,
                    )

                verification_rows = [
                    row for row in all_facts
                    if _is_verified(row) and _normalise_relation(row.get("relation")) in _TEST_RELATIONS
                ]
                shared_verification_target = _shared_verification_target(
                    left, right, verification_values,
                )
                if (
                    _shared_source_subject(left_rows, right_rows, set(_TEST_RELATIONS))
                    or any(
                        _matches(row.get("object"), left.get("_aliases", set()))
                        and _matches(row.get("object"), right.get("_aliases", set()))
                        for row in verification_rows
                    )
                    or shared_verification_target
                ):
                    # The final clause intentionally requires a concrete
                    # shared verification target supplied by the caller; lack
                    # of local tests alone never creates a group.
                    if verification_rows or shared_verification_target:
                        add_record(
                            left, right, VERIFICATION_COUPLING,
                            _reason(VERIFICATION_COUPLING, verification_rows,
                                    "one acceptance target verifies both children together"),
                            verification_rows,
                        )

                same_target = bool(left.get("_aliases", set()) & right.get("_aliases", set()))
                micro_text = " ".join([left.get("goal", ""), right.get("goal", "")]).casefold()
                micro_split = bool(re.search(
                    r"\b(half|part|piece|portion|branch|condition|guard|first|second|same\s+(?:function|method)|insep(?:arable|arably))\b",
                    micro_text,
                ))
                local_verification = _meaningful_verification(left) or _meaningful_verification(right)
                if same_target and (micro_split or transition_rows) and not local_verification:
                    merge_rows = transition_rows or pair_rows or left_rows + right_rows
                    add_record(
                        left, right, MERGE_REQUIRED,
                        _reason(MERGE_REQUIRED, merge_rows,
                                "the proposed children are inseparable halves without independent verification"),
                        merge_rows,
                        handling=MERGE_REQUIRED,
                    )

                # An execution dependency alone is deliberately not a semantic
                # group.  It is annotated only when an independent semantic
                # coupling was already proven above.
                if (
                    (str(left["id"]), str(right["id"])) in dependencies
                    or (str(right["id"]), str(left["id"])) in dependencies
                ) and any(
                    record.children == tuple(sorted((left["id"], right["id"])))
                    and record.kind != ORDER_DEPENDENT
                    for record in records
                ):
                    add_record(
                        left, right, ORDER_DEPENDENT,
                        "existing execution ordering is retained alongside a proven semantic relationship.",
                        pair_rows,
                    )

        status = ANALYSIS_VALIDATED
        classification = INDEPENDENT
        accepted = True
        if conflicts:
            status = ANALYSIS_CONFLICTING
            classification = BLOCKED
            accepted = False
        elif merge_pairs:
            classification = MERGE_REQUIRED
            accepted = False
        elif group_edges:
            classification = GROUP
        elif partial_rows:
            # Stale/partial neighborhoods are useful diagnostics, never
            # sufficient evidence for a strong semantic grouping decision.
            status = ANALYSIS_PARTIAL
        elif all_facts and re.search(
            r"\b(contract|return|shape|schema|type|field|transition|invariant|public|export|configuration)\w*\b",
            parent_goal.casefold(),
        ) and not any(
            _normalise_relation(row.get("relation")) in {
                *set(_CONTRACT_RELATIONS), CALLS, READS_FIELD, TRANSITIONS,
                HAS_INVARIANT, *set(_PUBLIC_RELATIONS), READS_CONFIG,
            }
            for row in all_facts if _is_verified(row)
        ):
            # Definitions/implementation snippets can be current and
            # provenance-backed while still failing to establish the
            # requested semantic boundary.
            status = ANALYSIS_PARTIAL

        # Build connected components from proven non-order coupling.  The
        # component is the semantic unit; scheduling edges remain separate.
        adjacency: dict[str, set[str]] = {child["id"]: set() for child in children}
        for (left_id, right_id), kinds in group_edges.items():
            if not kinds:
                continue
            adjacency.setdefault(left_id, set()).add(right_id)
            adjacency.setdefault(right_id, set()).add(left_id)
        groups: list[dict[str, Any]] = []
        visited: set[str] = set()
        child_by_id = {child["id"]: child for child in children}
        for child_id in sorted(adjacency):
            if child_id in visited or not adjacency.get(child_id):
                continue
            stack = [child_id]
            component: list[str] = []
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                component.append(current)
                stack.extend(sorted(adjacency.get(current, set()), reverse=True))
            component = sorted(component)[:MAX_SEMANTIC_GROUP_MEMBERS]
            component_set = set(component)
            component_records = [
                record for record in records
                if record.required_handling == GROUP
                and set(record.children).issubset(component_set)
                and record.kind != ORDER_DEPENDENT
            ]
            kinds = tuple(sorted({record.kind for record in component_records}))
            evidence = tuple(
                item for record in component_records
                for item in record.evidence
            )
            member_children = [child_by_id[item] for item in component if item in child_by_id]
            group = SemanticWorkGroup(
                _group_id(parent_goal, component, kinds),
                _group_goal(parent_goal, member_children),
                _group_invariant(kinds, invariants),
                tuple(component), kinds,
                tuple(_unique(
                    [*verification_values]
                    + [target for child in member_children for target in child.get("verification_targets", [])],
                    limit=MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS,
                    item_limit=220,
                )),
                tuple(_evidence_rows(evidence, limit=MAX_SEMANTIC_GROUP_FACTS)),
            )
            groups.append(group.to_dict())
            if len(groups) >= self.max_groups:
                break

        # Annotate a copy, never mutate the decomposer's candidate objects.
        group_by_member: dict[str, dict[str, Any]] = {
            member: group for group in groups for member in group.get("member_ids", [])
        }
        projected_children = []
        for child in children:
            projected = _public_child(child)
            group = group_by_member.get(child["id"])
            if group:
                projected.update({
                    "semantic_group_id": group["group_id"],
                    "semantic_group_goal": group["goal"],
                    "semantic_group_invariant": group["invariant"],
                    "semantic_group_members": list(group["member_ids"]),
                    "semantic_group_coupling_types": list(group["coupling_types"]),
                    "semantic_group_verification_targets": list(group["verification_targets"]),
                    "semantic_group_required": True,
                    "semantic_group_status": "PLANNED",
                })
            projected_children.append(projected)

        return {
            "schema_version": SEMANTIC_COUPLING_SCHEMA_VERSION,
            "status": status,
            "classification": classification,
            "accepted": accepted,
            "parent_goal": parent_goal,
            "children": projected_children,
            "couplings": [record.to_dict() for record in records],
            "groups": groups[: self.max_groups],
            "independent_children": [
                child["id"] for child in projected_children
                if not child.get("semantic_group_id")
            ],
            "merge_required": [list(pair) for pair in sorted(merge_pairs)],
            "conflicts": conflicts,
            "partial_evidence": partial_rows,
            "bounds": {
                "max_relationship_hops": self.max_hops,
                "max_facts_per_child": self.max_facts_per_child,
                "max_children": self.max_children,
                "max_groups": self.max_groups,
                "max_group_members": MAX_SEMANTIC_GROUP_MEMBERS,
                "max_group_facts": MAX_SEMANTIC_GROUP_FACTS,
                "max_replan_attempts": self.max_replan_attempts,
            },
            "world_model_project_identity": getattr(self.world_model, "project_identity", None),
        }

    def refine_decomposition(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Return a plan and deterministically merge unsafe micro-splits."""
        plan = self.analyze(*args, **kwargs)
        if plan.get("classification") != MERGE_REQUIRED or not plan.get("merge_required"):
            return {"plan": plan, "children": list(plan.get("children", []) or []), "refined": False}

        plan["replan_attempts"] = 0
        plan["max_replan_attempts"] = self.max_replan_attempts
        if self.max_replan_attempts < 1:
            # An unsafe split must never fall through to execution merely
            # because deterministic refinement has exhausted its budget.
            plan["accepted"] = False
            plan["replan_exhausted"] = True
            return {
                "plan": plan,
                "children": list(plan.get("children", []) or []),
                "refined": False,
                "replan_exhausted": True,
            }

        children = [dict(item) for item in plan.get("children", []) or []]
        by_id = {str(item.get("id")): item for item in children}
        merged_ids: set[str] = set()
        for pair in plan.get("merge_required", [])[:MAX_SEMANTIC_COUPLING_GROUPS]:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                continue
            left_id, right_id = sorted((str(pair[0]), str(pair[1])))
            left = by_id.get(left_id)
            right = by_id.get(right_id)
            if not left or not right or right_id in merged_ids:
                continue
            left["goal"] = _text(
                f"{left.get('goal', '')}; complete the inseparable semantic portion also owned by {right_id}",
                900,
            )
            for key in ("done_when", "scope_hint", "targets", "verification_targets", "dependencies"):
                left[key] = _unique(
                    [*list(left.get(key, []) or []), *list(right.get(key, []) or [])],
                    limit=8 if key != "verification_targets" else MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS,
                    item_limit=320 if key == "done_when" else 220,
                )
            left["merged_from"] = _unique(
                [*list(left.get("merged_from", []) or []), left_id, right_id],
                limit=MAX_SEMANTIC_GROUP_MEMBERS, item_limit=120,
            )
            left["semantic_merge_required"] = True
            left["semantic_merge_reason"] = _text(
                "Merged before execution because the candidate split had no independent semantic verification.",
                MAX_SEMANTIC_REASON_CHARS,
            )
            merged_ids.add(right_id)
        refined_children = [child for child in children if str(child.get("id")) not in merged_ids]
        refined_plan = dict(plan)
        refined_plan["status"] = ANALYSIS_VALIDATED
        refined_plan["classification"] = GROUP if plan.get("groups") else INDEPENDENT
        refined_plan["accepted"] = True
        refined_plan["refined"] = True
        refined_plan["replan_attempts"] = 1
        refined_plan["max_replan_attempts"] = self.max_replan_attempts
        refined_plan["refined_from_classification"] = MERGE_REQUIRED
        refined_plan["children"] = refined_children
        refined_plan["merged_child_ids"] = sorted(merged_ids)
        return {"plan": refined_plan, "children": refined_children, "refined": True}


def analyze_semantic_coupling(
    parent_goal: Any,
    candidate_children: Iterable[Any],
    *,
    world_model: Any = None,
    project_world_model: Any = None,
    known_dependencies: Any = None,
    requirements: Iterable[Any] | None = None,
    invariants: Iterable[Any] | None = None,
    verification_targets: Iterable[Any] | None = None,
    **limits: Any,
) -> dict[str, Any]:
    """Functional entry point used by deterministic callers and tests."""
    model = world_model if world_model is not None else project_world_model
    return SemanticCouplingAnalyzer(model, **limits).analyze(
        parent_goal,
        candidate_children,
        known_dependencies=known_dependencies,
        requirements=requirements,
        invariants=invariants,
        verification_targets=verification_targets,
    )


def refine_semantic_decomposition(
    parent_goal: Any,
    candidate_children: Iterable[Any],
    *,
    world_model: Any = None,
    project_world_model: Any = None,
    known_dependencies: Any = None,
    requirements: Iterable[Any] | None = None,
    invariants: Iterable[Any] | None = None,
    verification_targets: Iterable[Any] | None = None,
    **limits: Any,
) -> dict[str, Any]:
    model = world_model if world_model is not None else project_world_model
    return SemanticCouplingAnalyzer(model, **limits).refine_decomposition(
        parent_goal,
        candidate_children,
        known_dependencies=known_dependencies,
        requirements=requirements,
        invariants=invariants,
        verification_targets=verification_targets,
    )


def _model_facts_for_group(group: Mapping[str, Any], world_model: Any) -> list[dict[str, Any]]:
    if world_model is None:
        return []
    refresh = getattr(world_model, "refresh_currentness", None)
    if callable(refresh):
        try:
            refresh()
        except Exception:
            # The normal mutation lifecycle performs invalidation explicitly;
            # a best-effort refresh here must never make verification crash.
            pass
    values = getattr(world_model, "facts", None)
    if callable(values):
        try:
            values = values()
        except Exception:
            values = []
    rows: list[dict[str, Any]] = []
    required_fact_ids = {
        str(item.get("fact_id"))
        for item in list(group.get("evidence", []) or [])
        if isinstance(item, Mapping) and item.get("fact_id")
    }
    member_aliases = set().union(*(_alias_forms(item) for item in group.get("member_ids", []) or ()))
    for value in values or ():
        fact = _fact_dict(value)
        if fact is None:
            continue
        if required_fact_ids and str(fact.get("fact_id")) in required_fact_ids:
            rows.append(fact)
            continue
        if member_aliases and not (
            _matches(fact.get("subject"), member_aliases)
            or _matches(fact.get("object"), member_aliases)
        ):
            continue
        rows.append(fact)
    return rows


def verify_semantic_group(
    group: Mapping[str, Any] | None,
    *,
    child_results: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None = None,
    world_model: Any = None,
    current_facts: Iterable[Any] | None = None,
    verification_runner: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Perform bounded group completion checks after member execution.

    The existing verification/recovery machinery remains the owner of file and
    test execution.  This function adds the semantic completion predicate:
    every member must succeed, required current facts must still be usable, and
    an injected/existing verifier must not report failure.
    """
    value = dict(group) if isinstance(group, Mapping) else {}
    member_ids = [str(item) for item in list(value.get("member_ids", []) or [])[:MAX_SEMANTIC_GROUP_MEMBERS]]
    results: dict[str, Any] = {}
    if isinstance(child_results, Mapping):
        results = {str(key): item for key, item in child_results.items()}
    else:
        for item in child_results or ():
            if not isinstance(item, Mapping):
                continue
            task = item.get("task") if isinstance(item.get("task"), Mapping) else item
            result = item.get("result") if isinstance(item.get("result"), Mapping) else item
            child_id = task.get("id") if isinstance(task, Mapping) else item.get("id")
            if child_id:
                results[str(child_id)] = result
    failed = [
        child_id for child_id in member_ids
        if str((results.get(child_id) or {}).get("status", "")).casefold()
        not in {"done", "success", "succeeded", "verified", "passed", "complete"}
    ]
    if failed:
        return {
            "status": "INCOMPLETE",
            "passed": False,
            "group_id": value.get("group_id"),
            "failure_type": "SEMANTIC_GROUP_MEMBER_FAILURE",
            "reason": f"semantic group members are not all successful: {', '.join(failed[:4])}",
            "failed_members": failed,
            "member_ids": member_ids,
        }

    rows = [_fact_dict(item) for item in (current_facts or ())]
    rows = [item for item in rows if item is not None]
    if not rows:
        rows = _model_facts_for_group(value, world_model)
    conflicts = [
        row for row in rows
        if _normalise_state(row.get("state")) == CONFLICTING
    ]
    if conflicts:
        return {
            "status": "FAILED",
            "passed": False,
            "group_id": value.get("group_id"),
            "failure_type": "SEMANTIC_GROUP_CONFLICT",
            "reason": "current authoritative facts conflict; semantic completion cannot be claimed",
            "conflicts": _evidence_rows(conflicts, limit=MAX_SEMANTIC_GROUP_FACTS),
            "member_ids": member_ids,
        }

    non_current = [row for row in rows if not _is_verified(row)]
    if non_current:
        return {
            "status": "FAILED",
            "passed": False,
            "group_id": value.get("group_id"),
            "failure_type": "SEMANTIC_GROUP_EVIDENCE_STALE",
            "reason": "group evidence is partial, stale, or lacks repository provenance",
            "evidence": _evidence_rows(non_current, limit=MAX_SEMANTIC_GROUP_FACTS),
            "member_ids": member_ids,
        }

    required_fact_ids = {
        str(item.get("fact_id"))
        for item in list(value.get("evidence", []) or [])
        if isinstance(item, Mapping) and item.get("fact_id")
    }
    if required_fact_ids and rows:
        current_ids = {
            str(item.get("fact_id")) for item in rows
            if _normalise_state(item.get("state")) == VERIFIED
        }
        missing = sorted(required_fact_ids - current_ids)
        if missing:
            return {
                "status": "FAILED",
                "passed": False,
                "group_id": value.get("group_id"),
                "failure_type": "SEMANTIC_GROUP_EVIDENCE_STALE",
                "reason": "one or more coupling facts are stale or no longer current",
                "missing_fact_ids": missing[:MAX_SEMANTIC_GROUP_FACTS],
                "member_ids": member_ids,
            }

    if value.get("verification_required", True) and not rows and verification_runner is None:
        return {
            "status": "FAILED",
            "passed": False,
            "group_id": value.get("group_id"),
            "failure_type": "SEMANTIC_GROUP_VERIFICATION_UNAVAILABLE",
            "reason": "no current semantic evidence or group verifier is available",
            "member_ids": member_ids,
        }

    if verification_runner is not None:
        try:
            observed = verification_runner(value, results)
        except TypeError:
            observed = verification_runner(value)
        except Exception as exc:
            return {
                "status": "FAILED",
                "passed": False,
                "group_id": value.get("group_id"),
                "failure_type": "SEMANTIC_GROUP_VERIFIER_ERROR",
                "reason": _text(str(exc), MAX_SEMANTIC_REASON_CHARS),
                "member_ids": member_ids,
            }
        if isinstance(observed, Mapping):
            if observed.get("passed") is False or str(observed.get("status", "")).upper() in {"FAILED", "FAIL", "BLOCKED"}:
                result = dict(observed)
                result.setdefault("status", "FAILED")
                result["passed"] = False
                result.setdefault("group_id", value.get("group_id"))
                result.setdefault("failure_type", "SEMANTIC_GROUP_VERIFICATION_FAILED")
                result.setdefault("member_ids", member_ids)
                return result
        elif observed is False:
            return {
                "status": "FAILED",
                "passed": False,
                "group_id": value.get("group_id"),
                "failure_type": "SEMANTIC_GROUP_VERIFICATION_FAILED",
                "reason": "group-level semantic verification rejected the combined change",
                "member_ids": member_ids,
            }

    return {
        "status": "COMPLETE",
        "passed": True,
        "group_id": value.get("group_id"),
        "member_ids": member_ids,
        "coupling_types": list(value.get("coupling_types", []) or [])[:MAX_SEMANTIC_GROUP_FACTS],
        "facts_checked": len(rows),
        "verification_targets": list(value.get("verification_targets", []) or [])[:MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS],
    }


def benchmark_semantic_coupling_scenarios(
    scenarios: Iterable[Mapping[str, Any]],
    *,
    analyzer: SemanticCouplingAnalyzer | None = None,
) -> dict[str, Any]:
    """Measure deterministic coupling classifications without invented metrics."""
    engine = analyzer or SemanticCouplingAnalyzer()
    counts = {
        "candidate_decompositions": 0,
        "correctly_independent_children": 0,
        "semantic_groups_detected": 0,
        "merge_required_cases_detected": 0,
        "false_positive_groups": 0,
        "missed_known_couplings": 0,
        "group_verification_failures_caught": 0,
        "total_group_members": 0,
    }
    sizes: list[int] = []
    for scenario in scenarios:
        if not isinstance(scenario, Mapping):
            continue
        counts["candidate_decompositions"] += 1
        plan = engine.analyze(
            scenario.get("parent_goal", scenario.get("goal", "")),
            scenario.get("children", scenario.get("candidate_children", [])),
            known_dependencies=scenario.get("known_dependencies"),
            requirements=scenario.get("requirements"),
            invariants=scenario.get("invariants"),
            verification_targets=scenario.get("verification_targets"),
        )
        expected = str(scenario.get("expected", "")).upper()
        groups = list(plan.get("groups", []) or [])
        counts["semantic_groups_detected"] += len(groups)
        counts["merge_required_cases_detected"] += int(plan.get("classification") == MERGE_REQUIRED)
        for group in groups:
            size = len(group.get("member_ids", []) or [])
            sizes.append(size)
            counts["total_group_members"] += size
        if expected == INDEPENDENT:
            if not groups and plan.get("classification") == INDEPENDENT:
                counts["correctly_independent_children"] += len(plan.get("children", []) or [])
            counts["false_positive_groups"] += int(bool(groups))
        elif expected in {GROUP, MERGE_REQUIRED}:
            found = bool(groups) if expected == GROUP else plan.get("classification") == MERGE_REQUIRED
            counts["missed_known_couplings"] += int(not found)
        if scenario.get("verification_failure") and groups:
            result = verify_semantic_group(groups[0], child_results=scenario.get("child_results"), verification_runner=lambda *_: False)
            counts["group_verification_failures_caught"] += int(not result.get("passed"))
    counts["average_group_size"] = (
        round(sum(sizes) / len(sizes), 3) if sizes else 0.0
    )
    return counts


__all__ = [
    "SEMANTIC_COUPLING_SCHEMA_VERSION",
    "SHARED_CONTRACT", "SHARED_STATE_TRANSITION", "SHARED_INVARIANT",
    "PRODUCER_CONSUMER", "TYPE_SCHEMA_COUPLING", "PUBLIC_SURFACE_COUPLING",
    "ORDER_DEPENDENT", "VERIFICATION_COUPLING", "CONFIGURATION_COUPLING",
    "INDEPENDENT", "GROUP", "MERGE_REQUIRED", "BLOCKED",
    "ANALYSIS_VALIDATED", "ANALYSIS_PARTIAL", "ANALYSIS_CONFLICTING",
    "SEMANTIC_COUPLING_KINDS", "AUTHORITY_RANKING",
    "MAX_SEMANTIC_COUPLING_HOPS", "MAX_SEMANTIC_COUPLING_FACTS_PER_CHILD",
    "MAX_SEMANTIC_COUPLING_CHILDREN", "MAX_SEMANTIC_COUPLING_GROUPS",
    "MAX_SEMANTIC_GROUP_MEMBERS", "MAX_SEMANTIC_GROUP_FACTS",
    "MAX_SEMANTIC_GROUP_VERIFICATION_TARGETS", "MAX_SEMANTIC_REPLAN_ATTEMPTS",
    "SemanticCoupling", "SemanticWorkGroup", "SemanticCouplingAnalyzer",
    "analyze_semantic_coupling", "refine_semantic_decomposition",
    "verify_semantic_group", "benchmark_semantic_coupling_scenarios",
]
