"""Bounded, progressive task context for CORE-2.

The working set is a transient retrieval projection.  It is not Brain truth,
not verification evidence, and not an authorization object.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from .project_brain_refs import ProjectBrainEntity, TypedReference, canonical_hash
from .reference_resolution import EvidenceResolutionRequest, ProjectReferenceResolver
from .repository_map import RepositoryMap


PRIMARY = "PRIMARY"
SUPPORTING = "SUPPORTING"
TESTS = "TESTS"
CONTRACTS = "CONTRACTS"
DEPENDENCIES = "DEPENDENCIES"
UNRESOLVED_EVIDENCE = "UNRESOLVED_EVIDENCE"
WORKING_SET_BUDGET_REACHED = "WORKING_SET_BUDGET_REACHED"
WORKING_SET_READY = "WORKING_SET_READY"
READ_ONLY_SUPPORT = "READ_ONLY_SUPPORT"
MUTATION_AUTHORIZED = "MUTATION_AUTHORIZED"


@dataclass(frozen=True)
class WorkingSetBudget:
    """Conservative bounds shared by routing and working-set construction."""

    max_primary_items: int = 6
    max_supporting_items: int = 10
    max_tests: int = 6
    max_files: int = 16
    max_symbols: int = 32
    max_source_characters: int = 24000
    max_full_file_reads: int = 2
    max_search_stages: int = 5
    max_graph_depth: int = 1
    max_graph_nodes: int = 12
    max_dependency_files: int = 8
    max_candidates: int = 64
    max_lexical_results: int = 24

    def __post_init__(self) -> None:
        limits = {
            "max_primary_items": (1, 64),
            "max_supporting_items": (1, 128),
            "max_tests": (0, 64),
            "max_files": (1, 256),
            "max_symbols": (1, 512),
            "max_source_characters": (256, 200000),
            "max_full_file_reads": (0, 32),
            "max_search_stages": (1, 8),
            "max_graph_depth": (0, 4),
            "max_graph_nodes": (0, 128),
            "max_dependency_files": (0, 128),
            "max_candidates": (1, 512),
            "max_lexical_results": (1, 256),
        }
        for name, (minimum, maximum) in limits.items():
            value = max(minimum, min(maximum, int(getattr(self, name))))
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in (
                "max_primary_items", "max_supporting_items", "max_tests", "max_files",
                "max_symbols", "max_source_characters", "max_full_file_reads",
                "max_search_stages", "max_graph_depth", "max_graph_nodes",
                "max_dependency_files", "max_candidates", "max_lexical_results",
            )
        }


@dataclass(frozen=True)
class WorkingSetItem:
    identity: str
    role: str
    path: str = ""
    symbol: str | None = None
    reason_selected: str = ""
    evidence_sources: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    current_source_identity: str | None = None
    detail_level: int = 1
    staleness_state: str = "CURRENT"
    ranking: dict[str, Any] = field(default_factory=dict)
    authority_label: str = READ_ONLY_SUPPORT
    evidence: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "identity", str(self.identity))
        object.__setattr__(self, "role", str(self.role))
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "symbol", str(self.symbol) if self.symbol else None)
        object.__setattr__(self, "evidence_sources", tuple(sorted(set(str(item) for item in self.evidence_sources))))
        object.__setattr__(self, "matched_terms", tuple(sorted(set(str(item) for item in self.matched_terms))))
        object.__setattr__(self, "detail_level", max(0, min(6, int(self.detail_level))))
        object.__setattr__(self, "ranking", dict(self.ranking))
        object.__setattr__(self, "evidence", dict(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "role": self.role,
            "path": self.path,
            "symbol": self.symbol,
            "reason_selected": self.reason_selected,
            "evidence_sources": list(self.evidence_sources),
            "matched_terms": list(self.matched_terms),
            "current_source_identity": self.current_source_identity,
            "detail_level": self.detail_level,
            "staleness_state": self.staleness_state,
            "ranking": self.ranking,
            "authority_label": self.authority_label,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class TaskWorkingSet:
    query_id: str
    subject_identity: str
    revision_identity: str
    items: tuple[WorkingSetItem, ...] = ()
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    budget: WorkingSetBudget = field(default_factory=WorkingSetBudget)
    budget_usage: dict[str, int] = field(default_factory=dict)
    status: str = WORKING_SET_READY
    expansion_history: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "items", tuple(self.items))
        object.__setattr__(self, "unresolved_evidence", tuple(dict(item) for item in self.unresolved_evidence))
        object.__setattr__(self, "budget_usage", {str(k): int(v) for k, v in self.budget_usage.items()})
        object.__setattr__(self, "expansion_history", tuple(dict(item) for item in self.expansion_history))

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted({item.path for item in self.items if item.path}))

    @property
    def symbols(self) -> tuple[str, ...]:
        return tuple(sorted({item.identity for item in self.items if item.symbol}))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "query_id": self.query_id,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "items": [item.to_dict() for item in self.items],
            "unresolved_evidence": list(self.unresolved_evidence),
            "budget": self.budget.to_dict(),
            "budget_usage": dict(self.budget_usage),
            "status": self.status,
            "expansion_history": list(self.expansion_history),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def _authority_paths(authority: Mapping[str, Any] | None, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(authority, Mapping):
        return set()
    values: list[Any] = []
    for key in keys:
        value = authority.get(key)
        if isinstance(value, Mapping):
            values.extend(value.get("paths", value.get("files", [])) or [])
        elif isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif isinstance(value, str):
            values.append(value)
    return {str(value).replace("\\", "/").lstrip("./") for value in values if str(value).strip()}


def authority_label_for_path(path: str, authority: Mapping[str, Any] | None = None) -> str:
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    dnt = _authority_paths(authority, ("do_not_touch", "dnt", "approved_dnt", "approved_do_not_touch"))
    if normalized in dnt:
        return READ_ONLY_SUPPORT
    approved = _authority_paths(authority, (
        "approved_mutation_scope", "mutation_scope", "authorized_paths",
        "approved_scope", "mutation_targets", "approved_mutation_targets",
    ))
    return MUTATION_AUTHORIZED if normalized in approved else READ_ONLY_SUPPORT


def _candidate_dict(candidate: Any) -> dict[str, Any]:
    if isinstance(candidate, Mapping):
        return dict(candidate)
    if hasattr(candidate, "to_dict"):
        value = candidate.to_dict()
        return dict(value) if isinstance(value, Mapping) else {}
    return {}


def _role_for_candidate(candidate: Mapping[str, Any], *, primary_count: int, budget: WorkingSetBudget) -> str | None:
    kind = str(candidate.get("candidate_type", candidate.get("kind", "file"))).casefold()
    path = str(candidate.get("path", ""))
    if kind in {"test", "test_file"} or "/tests/" in f"/{path.casefold()}/" or path.casefold().startswith("test_"):
        return TESTS
    sources = {str(item) for item in candidate.get("evidence_sources", [])}
    if "test" in sources or "test_mapping" in sources:
        return TESTS
    if kind in {"dependency", "dependency_file"} or "graph" in sources or "dependency" in sources:
        return DEPENDENCIES
    if kind in {"contract", "architecture", "brain"}:
        return CONTRACTS
    return PRIMARY if primary_count < budget.max_primary_items else SUPPORTING


def build_task_working_set(
    query: Any,
    candidates: Iterable[Any] = (),
    *,
    repository_map: RepositoryMap | Mapping[str, Any] | None = None,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
    authority: Mapping[str, Any] | None = None,
    budget: WorkingSetBudget | None = None,
    unresolved_evidence: Iterable[Mapping[str, Any]] = (),
) -> TaskWorkingSet:
    """Build a bounded context projection without loading source bodies."""
    if hasattr(query, "candidates") and hasattr(query, "query"):
        result = query
        if not candidates:
            candidates = tuple(getattr(result, "candidates", ()) or ())
        if not unresolved_evidence:
            unresolved_evidence = tuple(getattr(result, "unresolved_evidence", ()) or ())
        query = getattr(result, "query")
    if isinstance(budget, Mapping):
        current_budget = WorkingSetBudget(**dict(budget))
    else:
        current_budget = budget or WorkingSetBudget()
    query_id = str(getattr(query, "query_id", "") or (query.get("query_id", "") if isinstance(query, Mapping) else ""))
    subject = str(getattr(query, "subject_identity", "") or (query.get("subject_identity", "") if isinstance(query, Mapping) else ""))
    revision = str(getattr(query, "revision_identity", "") or (query.get("revision_identity", "") if isinstance(query, Mapping) else ""))
    selected: list[WorkingSetItem] = []
    identities: set[str] = set()
    file_paths: set[str] = set()
    symbol_ids: set[str] = set()
    role_counts = {PRIMARY: 0, SUPPORTING: 0, TESTS: 0, CONTRACTS: 0, DEPENDENCIES: 0}
    skipped = 0
    candidate_rows = [_candidate_dict(item) for item in candidates]
    candidate_rows.sort(key=lambda row: (-float(row.get("score", 0.0)), str(row.get("identity", row.get("path", "")))))
    if len(candidate_rows) > current_budget.max_candidates:
        skipped += len(candidate_rows) - current_budget.max_candidates
    for candidate in candidate_rows[: current_budget.max_candidates]:
        identity = str(candidate.get("identity") or candidate.get("candidate_id") or candidate.get("symbol_id") or candidate.get("path") or "")
        if not identity or identity in identities:
            continue
        path = str(candidate.get("path", "")).replace("\\", "/")
        symbol = candidate.get("symbol") or candidate.get("qualified_name")
        if path and path not in file_paths and len(file_paths) >= current_budget.max_files:
            skipped += 1
            continue
        if symbol and identity not in symbol_ids and len(symbol_ids) >= current_budget.max_symbols:
            skipped += 1
            continue
        role = _role_for_candidate(candidate, primary_count=role_counts[PRIMARY], budget=current_budget)
        if role == TESTS and role_counts[TESTS] >= current_budget.max_tests:
            skipped += 1
            continue
        if role == SUPPORTING and role_counts[SUPPORTING] >= current_budget.max_supporting_items:
            skipped += 1
            continue
        item = WorkingSetItem(
            identity=identity,
            role=role or UNRESOLVED_EVIDENCE,
            path=path,
            symbol=str(symbol) if symbol else None,
            reason_selected=str(candidate.get("reason_selected") or ";".join(candidate.get("reasons", ())) or "ranked_retrieval_candidate"),
            evidence_sources=tuple(candidate.get("evidence_sources", ())),
            matched_terms=tuple(candidate.get("matched_terms", ())),
            current_source_identity=candidate.get("current_source_identity") or candidate.get("content_hash"),
            detail_level=int(candidate.get("detail_level", 1) or 1),
            staleness_state=str(candidate.get("staleness_state", "CURRENT")),
            ranking={
                "score": float(candidate.get("score", 0.0)),
                "confidence_class": candidate.get("confidence_class", "SUPPORTING"),
                "graph_distance": candidate.get("graph_distance"),
            },
            authority_label=authority_label_for_path(path, authority),
        )
        selected.append(item)
        identities.add(identity)
        if path:
            file_paths.add(path)
        if symbol:
            symbol_ids.add(identity)
        role_counts[item.role] = role_counts.get(item.role, 0) + 1

    # Preserve verified contracts as compact metadata, never source text.
    for raw in brain_entities:
        try:
            entity = raw if isinstance(raw, ProjectBrainEntity) else ProjectBrainEntity.from_dict(raw)
        except (TypeError, ValueError):
            continue
        identity = f"brain://{entity.entity_id}"
        if identity in identities or role_counts[CONTRACTS] >= current_budget.max_supporting_items:
            continue
        selected.append(WorkingSetItem(
            identity=identity,
            role=CONTRACTS,
            reason_selected="verified_brain_contract_summary",
            evidence_sources=("brain_reference",),
            current_source_identity=entity.verified_revision_identity,
            detail_level=0,
            staleness_state=entity.staleness_state,
            ranking={"score": 0.0, "confidence_class": "CONTEXT"},
            authority_label=READ_ONLY_SUPPORT,
            evidence={
                "entity_id": entity.entity_id,
                "name": entity.name,
                "summary": entity.summary,
                "contracts": list(entity.contracts),
                "invariants": list(entity.invariants),
            },
        ))
        identities.add(identity)
        role_counts[CONTRACTS] += 1

    status = WORKING_SET_BUDGET_REACHED if skipped else WORKING_SET_READY
    usage = {
        "items": len(selected),
        "files": len(file_paths),
        "symbols": len(symbol_ids),
        "primary_items": role_counts[PRIMARY],
        "supporting_items": role_counts[SUPPORTING],
        "tests": role_counts[TESTS],
        "contracts": role_counts[CONTRACTS],
        "dependencies": role_counts[DEPENDENCIES],
        "skipped_candidates": skipped,
        "source_characters": 0,
        "full_file_reads": 0,
    }
    unresolved = tuple(dict(item) for item in unresolved_evidence)
    if skipped:
        unresolved = unresolved + ({"reason": "working_set_budget", "skipped_candidates": skipped},)
    return TaskWorkingSet(
        query_id=query_id,
        subject_identity=subject,
        revision_identity=revision,
        items=tuple(selected),
        unresolved_evidence=unresolved,
        budget=current_budget,
        budget_usage=usage,
        status=status,
    )


def _reference_for_item(item: WorkingSetItem) -> TypedReference | None:
    if not item.path:
        return None
    if item.symbol:
        kind = "symbol"
        return TypedReference(kind=kind, path=item.path, symbol=item.symbol)
    return TypedReference(kind="file", path=item.path)


def expand_working_set(
    working_set: TaskWorkingSet,
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path,
    *,
    requested_level: int,
    metrics: dict[str, int] | None = None,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
) -> TaskWorkingSet:
    """Escalate selected entries only, reusing CORE-1 lazy resolution."""
    level = max(0, min(6, int(requested_level)))
    resolver = ProjectReferenceResolver(
        repository_map, project_root, brain_entities=brain_entities, metrics=metrics,
    )
    items: list[WorkingSetItem] = []
    usage = dict(working_set.budget_usage)
    history = list(working_set.expansion_history)
    for item in working_set.items:
        reference = _reference_for_item(item)
        if reference is None or item.role == CONTRACTS:
            items.append(item)
            continue
        if item.detail_level >= level and (
            isinstance(item.evidence.get("source_body"), str)
            or isinstance(item.evidence.get("full_file"), str)
        ):
            items.append(replace(
                item,
                evidence={
                    **item.evidence,
                    "provenance": {
                        **dict(item.evidence.get("provenance", {})),
                        "source": "duplicate_suppressed",
                    },
                },
            ))
            history.append({
                "identity": item.identity,
                "requested_level": level,
                "resolved_state": item.evidence.get("resolution_state", "RESOLVED_CURRENT"),
                "duplicate_source_body_suppressed": True,
            })
            continue
        requested = level
        if requested >= 5 and usage.get("full_file_reads", 0) >= working_set.budget.max_full_file_reads:
            requested = 4
        request = EvidenceResolutionRequest(
            reference, requested_level=requested, reason="core2_working_set_detail_escalation",
            max_files=working_set.budget.max_files,
            max_symbols=working_set.budget.max_symbols,
            max_characters=working_set.budget.max_source_characters,
        )
        resolved = resolver.resolve(reference, request=request)
        evidence = dict(resolved.evidence)
        source_body = evidence.get("source_body")
        if isinstance(source_body, str):
            remaining = max(0, working_set.budget.max_source_characters - usage.get("source_characters", 0))
            evidence["source_body"] = source_body[:remaining]
            usage["source_characters"] = usage.get("source_characters", 0) + len(evidence["source_body"])
            usage["source_bodies_loaded"] = usage.get("source_bodies_loaded", 0) + 1
        if isinstance(evidence.get("full_file"), str):
            usage["full_file_reads"] = usage.get("full_file_reads", 0) + 1
        items.append(replace(
            item,
            detail_level=resolved.requested_level,
            staleness_state=resolved.staleness_state,
            evidence={**evidence, "resolution_state": resolved.state, "provenance": resolved.provenance},
        ))
        history.append({
            "identity": item.identity,
            "requested_level": requested,
            "resolved_state": resolved.state,
            "duplicate_source_body_suppressed": resolved.duplicate_source_body_suppressed,
        })
    if usage.get("source_characters", 0) >= working_set.budget.max_source_characters:
        status = WORKING_SET_BUDGET_REACHED
    else:
        status = working_set.status
    return replace(
        working_set,
        items=tuple(items),
        budget_usage=usage,
        status=status,
        expansion_history=tuple(history),
    )


__all__ = [
    "PRIMARY", "SUPPORTING", "TESTS", "CONTRACTS", "DEPENDENCIES",
    "UNRESOLVED_EVIDENCE", "WORKING_SET_BUDGET_REACHED", "WORKING_SET_READY",
    "READ_ONLY_SUPPORT", "MUTATION_AUTHORIZED", "WorkingSetBudget", "WorkingSetItem",
    "TaskWorkingSet", "authority_label_for_path", "build_task_working_set",
    "expand_working_set",
]
