"""Deterministic hybrid repository intelligence for CORE-2.

CORE-2 is a retrieval and context-construction layer.  It combines the
verified reference Brain and mechanically-derived CORE-1 RepositoryMap with
exact, lexical, graph, test, and optional semantic evidence.  Retrieval
confidence never becomes mutation or verification authority.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .lexical_index import LexicalIndex, ensure_lexical_index
from .project_brain_refs import (
    ProjectBrainEntity,
    TypedReference,
    canonical_hash,
    canonical_json,
    query_project_brain,
)
from .reference_resolution import (
    AMBIGUOUS,
    INVALID_REFERENCE,
    RESOLVED_BUT_CHANGED,
    RESOLVED_CURRENT,
    STALE_REFERENCE,
    TARGET_MISSING,
    EvidenceResolutionRequest,
    ProjectReferenceResolver,
)
from .repository_map import RepositoryMap, _safe_root
from .task_working_set import (
    CONTRACTS,
    DEPENDENCIES,
    PRIMARY,
    SUPPORTING,
    TESTS,
    TaskWorkingSet,
    WorkingSetBudget,
    build_task_working_set,
    expand_working_set,
)


CORE2_SCHEMA_VERSION = "CORE-2-REPO-INTELLIGENCE-V1"
EXACT_PATH = "EXACT_PATH"
EXACT_SYMBOL = "EXACT_SYMBOL"
ERROR_LOCALIZATION = "ERROR_LOCALIZATION"
BEHAVIORAL_QUERY = "BEHAVIORAL_QUERY"
IMPACT_ANALYSIS = "IMPACT_ANALYSIS"
TEST_FAILURE = "TEST_FAILURE"
ARCHITECTURE_QUERY = "ARCHITECTURE_QUERY"
GENERAL_CODE_QUERY = "GENERAL_CODE_QUERY"
SEARCH_INTENTS = (
    EXACT_PATH, EXACT_SYMBOL, ERROR_LOCALIZATION, BEHAVIORAL_QUERY,
    IMPACT_ANALYSIS, TEST_FAILURE, ARCHITECTURE_QUERY, GENERAL_CODE_QUERY,
)
SearchIntent = str

CORE2_METRIC_KEYS = (
    "brain_seed_entities", "brain_refs_considered", "exact_path_queries",
    "exact_symbol_queries", "lexical_queries", "semantic_queries",
    "semantic_queries_skipped", "graph_expansions", "test_expansions",
    "candidate_count_raw", "candidate_count_deduped", "source_bodies_loaded",
    "full_files_loaded", "working_set_files", "working_set_symbols",
    "search_stages_executed", "early_stop_count", "lexical_index_builds",
    "lexical_documents_added", "lexical_documents_removed", "lexical_documents_updated",
    "lexical_terms_updated", "documents_added", "documents_removed",
    "documents_updated", "terms_updated",
)


def new_core2_metrics() -> dict[str, int]:
    return {key: 0 for key in CORE2_METRIC_KEYS}


_STOP_WORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for",
    "from", "how", "if", "in", "is", "it", "of", "on", "or", "should", "the",
    "this", "to", "what", "when", "where", "which", "with", "why", "will",
    "find", "inspect", "locate", "show", "read", "open", "get", "look", "at",
})
_PATH_PATTERN = re.compile(r"(?<![\w])(?:[A-Za-z0-9_.-]+/)+[A-Za-z0-9_.-]+\.[A-Za-z0-9]+")
_TOKEN_PATTERN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.-]*")
_DOTTED_SYMBOL_PATTERN = re.compile(r"\b[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)+\b")
_ERROR_PATTERN = re.compile(r"\b[A-Za-z_$][\w$]*(?:Error|Exception)\s*:\s*[^\n;]+", re.IGNORECASE)


def _unique(values: Iterable[Any], *, limit: int = 128) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _normalise_path_signal(value: str) -> str:
    return str(value or "").strip().replace("\\", "/").rstrip(".,;:")


def extract_query_signals(raw_task_text: str) -> dict[str, tuple[str, ...]]:
    """Extract conservative lexical signals; this is not natural-language understanding."""
    raw = str(raw_task_text or "")
    explicit_paths = _unique(_normalise_path_signal(item) for item in _PATH_PATTERN.findall(raw))
    dotted = _DOTTED_SYMBOL_PATTERN.findall(raw)
    tokens = _TOKEN_PATTERN.findall(raw)
    explicit_symbols: list[str] = list(dotted)
    identifiers: list[str] = []
    for token in tokens:
        clean = token.strip(".,:;()[]{}\"'`")
        if not clean or "/" in clean or clean in explicit_paths:
            continue
        if clean in dotted:
            identifiers.extend(part for part in clean.split(".") if part)
            continue
        has_camel_boundary = bool(re.search(r"[a-z][A-Z]", clean))
        is_identifier = (
            "_" in clean or "$" in clean or has_camel_boundary
            or (clean[:1].isupper() and len(clean) > 2)
        )
        if is_identifier:
            identifiers.append(clean)
            if clean not in explicit_symbols and has_camel_boundary:
                explicit_symbols.append(clean)
    error_strings = [" ".join(match.split()) for match in _ERROR_PATTERN.findall(raw)]
    test_names = [
        token.strip(".,:;()[]{}\"'`") for token in tokens
        if "test" in token.casefold() or "spec" in token.casefold()
    ]
    identifier_terms = {item.casefold() for item in identifiers}
    identifier_terms.update(item.casefold() for item in explicit_symbols)
    behavior_terms = [
        token.casefold().strip(".,:;()[]{}\"'`")
        for token in tokens
        if len(token.strip(".,:;()[]{}\"'`")) >= 3
        and token.casefold() not in _STOP_WORDS
        and token.casefold() not in identifier_terms
        and token.casefold() not in {
            part.casefold()
            for path in explicit_paths
            for part in path.split("/")
        }
        and token not in explicit_paths
        and token not in error_strings
    ]
    return {
        "explicit_paths": _unique(explicit_paths),
        "explicit_symbols": _unique(explicit_symbols),
        "identifiers": _unique(identifiers),
        "error_strings": _unique(error_strings),
        "test_names": _unique(test_names),
        "behavior_terms": _unique(behavior_terms),
    }


def classify_search_intents(raw_task_text: str, signals: Mapping[str, Iterable[str]] | None = None) -> tuple[str, ...]:
    raw = str(raw_task_text or "")
    lowered = raw.casefold()
    value = signals or extract_query_signals(raw)
    intents: list[str] = []
    if value.get("explicit_paths"):
        intents.append(EXACT_PATH)
    if value.get("explicit_symbols") or value.get("identifiers"):
        intents.append(EXACT_SYMBOL)
    if value.get("error_strings") or re.search(r"\b(?:error|exception|traceback|stack trace|failure)\b", lowered):
        intents.append(ERROR_LOCALIZATION)
    if value.get("test_names") or re.search(r"\b(?:test|tests|failing test|spec)\b", lowered):
        intents.append(TEST_FAILURE)
    if re.search(r"\b(?:impact|breaks? if|depends on|dependents|callers|consumers|downstream|affected)\b", lowered):
        intents.append(IMPACT_ANALYSIS)
    if re.search(r"\b(?:architecture|architectural|design|contract|invariant|decision|brain|interface)\b", lowered):
        intents.append(ARCHITECTURE_QUERY)
    if (
        value.get("behavior_terms")
        and (not intents or IMPACT_ANALYSIS in intents)
    ) or re.search(r"\b(?:behavior|behaviour|flow|does|where|how)\b", lowered):
        intents.append(BEHAVIORAL_QUERY)
    if not intents:
        intents.append(GENERAL_CODE_QUERY)
    return tuple(dict.fromkeys(intent for intent in intents if intent in SEARCH_INTENTS))


@dataclass(frozen=True)
class RepoIntelligenceQuery:
    query_id: str = ""
    raw_task_text: str = ""
    explicit_paths: tuple[str, ...] = ()
    explicit_symbols: tuple[str, ...] = ()
    identifiers: tuple[str, ...] = ()
    error_strings: tuple[str, ...] = ()
    test_names: tuple[str, ...] = ()
    behavior_terms: tuple[str, ...] = ()
    requested_detail: int = 2
    budget: WorkingSetBudget = field(default_factory=WorkingSetBudget)
    subject_identity: str = ""
    revision_identity: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.budget, Mapping):
            object.__setattr__(self, "budget", WorkingSetBudget(**dict(self.budget)))
        for name in (
            "explicit_paths", "explicit_symbols", "identifiers", "error_strings",
            "test_names", "behavior_terms",
        ):
            object.__setattr__(self, name, _unique(getattr(self, name)))
        object.__setattr__(self, "raw_task_text", str(self.raw_task_text or "")[:12000])
        object.__setattr__(self, "requested_detail", max(0, min(6, int(self.requested_detail))))
        if not self.query_id:
            seed = {
                "raw_task_text": self.raw_task_text,
                "explicit_paths": list(self.explicit_paths),
                "explicit_symbols": list(self.explicit_symbols),
                "identifiers": list(self.identifiers),
                "error_strings": list(self.error_strings),
                "test_names": list(self.test_names),
                "behavior_terms": list(self.behavior_terms),
                "subject_identity": self.subject_identity,
                "revision_identity": self.revision_identity,
            }
            object.__setattr__(self, "query_id", "QUERY-" + canonical_hash(seed)[:24])

    @classmethod
    def from_task(
        cls,
        raw_task_text: str,
        *,
        query_id: str = "",
        requested_detail: int = 2,
        budget: WorkingSetBudget | None = None,
        subject_identity: str = "",
        revision_identity: str = "",
    ) -> "RepoIntelligenceQuery":
        signals = extract_query_signals(raw_task_text)
        return cls(
            query_id=query_id,
            raw_task_text=raw_task_text,
            requested_detail=requested_detail,
            budget=budget or WorkingSetBudget(),
            subject_identity=subject_identity,
            revision_identity=revision_identity,
            **signals,
        )

    @property
    def intents(self) -> tuple[str, ...]:
        return classify_search_intents(self.raw_task_text, {
            "explicit_paths": self.explicit_paths,
            "explicit_symbols": self.explicit_symbols,
            "identifiers": self.identifiers,
            "error_strings": self.error_strings,
            "test_names": self.test_names,
            "behavior_terms": self.behavior_terms,
        })

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE2_SCHEMA_VERSION,
            "query_id": self.query_id,
            "raw_task_text": self.raw_task_text,
            "explicit_paths": list(self.explicit_paths),
            "explicit_symbols": list(self.explicit_symbols),
            "identifiers": list(self.identifiers),
            "error_strings": list(self.error_strings),
            "test_names": list(self.test_names),
            "behavior_terms": list(self.behavior_terms),
            "requested_detail": self.requested_detail,
            "budget": self.budget.to_dict(),
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "intents": list(self.intents),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class SearchCandidate:
    identity: str
    path: str
    symbol: str | None = None
    candidate_type: str = "file"
    score: float = 0.0
    evidence_sources: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    graph_distance: int | None = None
    brain_reference_support: tuple[str, ...] = ()
    test_support: tuple[str, ...] = ()
    staleness_state: str = "CURRENT"
    confidence_class: str = "SUPPORTING"
    reasons: tuple[str, ...] = ()
    current_source_identity: str | None = None
    authority_label: str = "READ_ONLY_SUPPORT"

    def to_dict(self) -> dict[str, Any]:
        return {
            "identity": self.identity,
            "path": self.path,
            "symbol": self.symbol,
            "candidate_type": self.candidate_type,
            "score": round(float(self.score), 6),
            "evidence_sources": list(self.evidence_sources),
            "matched_terms": list(self.matched_terms),
            "graph_distance": self.graph_distance,
            "brain_reference_support": list(self.brain_reference_support),
            "test_support": list(self.test_support),
            "staleness_state": self.staleness_state,
            "confidence_class": self.confidence_class,
            "reasons": list(self.reasons),
            "current_source_identity": self.current_source_identity,
            "authority_label": self.authority_label,
        }


@dataclass(frozen=True)
class RepoIntelligenceResult:
    query: RepoIntelligenceQuery
    intents: tuple[str, ...]
    routes_attempted: tuple[dict[str, Any], ...] = ()
    routes_skipped: tuple[dict[str, Any], ...] = ()
    candidates: tuple[SearchCandidate, ...] = ()
    working_set: TaskWorkingSet | None = None
    budget_usage: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, int] = field(default_factory=dict)
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    early_stop_reason: str = ""
    semantic_fallback_reason: str = ""

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE2_SCHEMA_VERSION,
            "query": self.query.to_dict(),
            "intents": list(self.intents),
            "routes_attempted": list(self.routes_attempted),
            "routes_skipped": list(self.routes_skipped),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "working_set": self.working_set.to_dict() if self.working_set else None,
            "budget_usage": dict(self.budget_usage),
            "metrics": dict(self.metrics),
            "unresolved_evidence": list(self.unresolved_evidence),
            "early_stop_reason": self.early_stop_reason,
            "semantic_fallback_reason": self.semantic_fallback_reason,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


class SemanticRetriever(Protocol):
    def search(
        self,
        query: RepoIntelligenceQuery,
        repository_map: RepositoryMap,
        budget: WorkingSetBudget,
    ) -> Iterable[Mapping[str, Any]]:
        ...


def _map_value(repository_map: RepositoryMap | Mapping[str, Any]) -> RepositoryMap:
    return repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)


def _metric(metrics: dict[str, int], key: str, amount: int = 1) -> None:
    metrics[key] = metrics.get(key, 0) + int(amount)


def _safe_signal_path(path: str) -> str | None:
    value = str(path or "").strip().replace("\\", "/")
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value) or ".." in value.split("/"):
        return None
    return "/".join(part for part in value.split("/") if part not in ("", "."))


def _authority_label(path: str, authority: Mapping[str, Any] | None) -> str:
    from .task_working_set import authority_label_for_path
    return authority_label_for_path(path, authority)


class _CandidateFusion:
    def __init__(self, repository_map: RepositoryMap, authority: Mapping[str, Any] | None, metrics: dict[str, int]) -> None:
        self.repository_map = repository_map
        self.authority = authority
        self.metrics = metrics
        self.rows: dict[str, dict[str, Any]] = {}

    def add(
        self,
        *,
        path: str,
        symbol: str | None = None,
        candidate_type: str = "file",
        score: float = 0.0,
        source: str,
        reason: str,
        matched_terms: Iterable[str] = (),
        graph_distance: int | None = None,
        brain_reference: str | None = None,
        test_support: str | None = None,
        staleness_state: str = "CURRENT",
        current_source_identity: str | None = None,
    ) -> None:
        normalized_path = str(path or "").replace("\\", "/")
        if not normalized_path:
            return
        identity = (
            f"{normalized_path}::{candidate_type}::{symbol}"
            if symbol else normalized_path
        )
        if not symbol:
            same_path_symbols = [
                key for key, existing in self.rows.items()
                if existing.get("path") == normalized_path and existing.get("symbol")
            ]
            if len(same_path_symbols) == 1:
                identity = same_path_symbols[0]
        _metric(self.metrics, "candidate_count_raw")
        row = self.rows.setdefault(identity, {
            "identity": identity,
            "path": normalized_path,
            "symbol": symbol,
            "candidate_type": candidate_type,
            "score": 0.0,
            "evidence_sources": set(),
            "matched_terms": set(),
            "graph_distance": graph_distance,
            "brain_reference_support": set(),
            "test_support": set(),
            "staleness_state": staleness_state,
            "reasons": set(),
            "current_source_identity": current_source_identity,
            "authority_label": _authority_label(normalized_path, self.authority),
        })
        weights = {
            "brain": 14.0,
            "current_repository": 6.0,
            "exact_path": 100.0,
            "exact_symbol": 96.0,
            "lexical": min(28.0, max(2.0, float(score))),
            "graph": 10.0 / max(1, int(graph_distance or 1)),
            "test": 18.0,
            "semantic": min(20.0, max(1.0, float(score))),
        }
        row["score"] += weights.get(source, float(score))
        row["evidence_sources"].add(source)
        row["reasons"].add(reason)
        row["matched_terms"].update(str(item) for item in matched_terms if str(item))
        if graph_distance is not None:
            if row["graph_distance"] is None or graph_distance < row["graph_distance"]:
                row["graph_distance"] = graph_distance
        if brain_reference:
            row["brain_reference_support"].add(brain_reference)
        if test_support:
            row["test_support"].add(test_support)
        if staleness_state in {STALE_REFERENCE, RESOLVED_BUT_CHANGED} and not row["evidence_sources"] - {"brain"}:
            row["staleness_state"] = staleness_state
        elif source != "brain" and staleness_state == "CURRENT":
            row["staleness_state"] = "CURRENT"
        if current_source_identity and not row["current_source_identity"]:
            row["current_source_identity"] = current_source_identity

    def freeze(self, *, ambiguous_identities: set[str] = set()) -> tuple[SearchCandidate, ...]:
        candidates: list[SearchCandidate] = []
        for identity, row in self.rows.items():
            sources = tuple(sorted(row["evidence_sources"]))
            reasons = set(row["reasons"])
            if len(sources) > 1:
                row["score"] += min(12.0, 4.0 * (len(sources) - 1))
                reasons.add("multi_signal_support")
            if identity in ambiguous_identities and not ({"test", "graph", "exact_path"} & set(sources)):
                confidence = "AMBIGUOUS"
            elif "exact_path" in sources or "exact_symbol" in sources:
                confidence = "EXACT" if len(sources) == 1 else "STRONG"
            elif len(sources) >= 2:
                confidence = "STRONG"
            elif "semantic" in sources:
                confidence = "SEMANTIC"
            else:
                confidence = "SUPPORTING"
            candidates.append(SearchCandidate(
                identity=identity,
                path=row["path"],
                symbol=row["symbol"],
                candidate_type=row["candidate_type"],
                score=round(float(row["score"]), 6),
                evidence_sources=sources,
                matched_terms=tuple(sorted(row["matched_terms"])),
                graph_distance=row["graph_distance"],
                brain_reference_support=tuple(sorted(row["brain_reference_support"])),
                test_support=tuple(sorted(row["test_support"])),
                staleness_state=row["staleness_state"],
                confidence_class=confidence,
                reasons=tuple(sorted(reasons)),
                current_source_identity=row["current_source_identity"],
                authority_label=row["authority_label"],
            ))
        candidates.sort(key=lambda item: (-item.score, item.identity))
        return tuple(candidates)


def _route(routes: list[dict[str, Any]], name: str, reason: str, *, attempted: bool) -> None:
    routes.append({"route": name, "status": "EXECUTED" if attempted else "SKIPPED", "reason": reason})


def _current_source_identity(repository_map: RepositoryMap, path: str, symbol: Mapping[str, Any] | None = None) -> str | None:
    if symbol:
        return str(symbol.get("anchor_hash") or "") or None
    return str(repository_map.files.get(path, {}).get("content_hash") or "") or None


def _path_matches(repository_map: RepositoryMap, signal: str) -> list[str]:
    normalized = _safe_signal_path(signal)
    if not normalized:
        return []
    if normalized in repository_map.files:
        return [normalized]
    basename = Path(normalized).name.casefold()
    return sorted(path for path in repository_map.files if Path(path).name.casefold() == basename or path.endswith("/" + normalized))


def _symbol_matches(repository_map: RepositoryMap, signal: str) -> list[dict[str, Any]]:
    clean = str(signal or "").strip()
    if not clean:
        return []
    short = clean.rsplit(".", 1)[-1]
    rows = [
        row for row in repository_map.symbols.values()
        if str(row.get("qualified_name", "")) in {clean, short}
        or str(row.get("symbol_id", "")).endswith("::" + clean)
    ]
    return sorted(rows, key=lambda row: str(row.get("symbol_id", "")))


def _seed_brain(
    query: RepoIntelligenceQuery,
    repository_map: RepositoryMap,
    project_root: Path,
    brain_entities: tuple[ProjectBrainEntity | Mapping[str, Any], ...],
    fusion: _CandidateFusion,
    metrics: dict[str, int],
    unresolved: list[dict[str, Any]],
) -> None:
    if not brain_entities:
        return
    brain_rows = query_project_brain(brain_entities, query.raw_task_text, max_items=64, include_stale=True, metrics=metrics)
    resolver = ProjectReferenceResolver(repository_map, project_root, brain_entities=brain_entities, metrics=metrics)
    by_id: dict[str, ProjectBrainEntity] = {}
    for raw in brain_entities:
        try:
            entity = raw if isinstance(raw, ProjectBrainEntity) else ProjectBrainEntity.from_dict(raw)
        except (TypeError, ValueError):
            continue
        by_id[entity.entity_id] = entity
    for row in brain_rows:
        entity = by_id.get(str(row.get("entity_id")))
        if entity is None:
            continue
        _metric(metrics, "brain_seed_entities")
        for reference in entity.references:
            _metric(metrics, "brain_refs_considered")
            resolved = resolver.resolve(
                reference,
                request=EvidenceResolutionRequest(reference, requested_level=1, reason="core2_brain_seed"),
                brain_entity=entity,
            )
            if resolved.state in {TARGET_MISSING, INVALID_REFERENCE, AMBIGUOUS}:
                unresolved.append({
                    "reference": reference.to_dict(),
                    "state": resolved.state,
                    "source": "brain",
                })
                continue
            evidence = resolved.evidence
            symbol = evidence.get("symbol") if isinstance(evidence.get("symbol"), Mapping) else None
            metadata = evidence.get("repository_file") if isinstance(evidence.get("repository_file"), Mapping) else {}
            path = str((symbol or metadata).get("path") or reference.path)
            if not path:
                continue
            fusion.add(
                path=path,
                symbol=str(symbol.get("qualified_name")) if symbol else None,
                candidate_type="symbol" if symbol else "file",
                score=0.0,
                source="brain",
                reason="brain_reference_support",
                brain_reference=reference.canonical_uri,
                staleness_state=resolved.state if resolved.state in {STALE_REFERENCE, RESOLVED_BUT_CHANGED} else "CURRENT",
                current_source_identity=_current_source_identity(repository_map, path, symbol),
            )
            if resolved.state in {STALE_REFERENCE, RESOLVED_BUT_CHANGED}:
                fusion.add(
                    path=path,
                    symbol=str(symbol.get("qualified_name")) if symbol else None,
                    candidate_type="symbol" if symbol else "file",
                    score=0.0,
                    source="current_repository",
                    reason="current_repository_precedence_over_stale_brain",
                    staleness_state="CURRENT",
                    current_source_identity=_current_source_identity(repository_map, path, symbol),
                )


def _expand_graph_and_tests(
    repository_map: RepositoryMap,
    fusion: _CandidateFusion,
    seeds: tuple[SearchCandidate, ...],
    budget: WorkingSetBudget,
    metrics: dict[str, int],
) -> None:
    if not seeds or budget.max_graph_nodes <= 0:
        return
    seed_paths = {candidate.path for candidate in seeds[: budget.max_primary_items] if candidate.path}
    queue: list[tuple[str, int]] = [(path, 0) for path in sorted(seed_paths)]
    visited: set[str] = set()
    graph_nodes = 0
    dependency_files = 0
    while queue and graph_nodes < budget.max_graph_nodes:
        path, distance = queue.pop(0)
        if path in visited or distance > budget.max_graph_depth:
            continue
        visited.add(path)
        for edge in repository_map.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            kind = str(edge.get("kind", ""))
            neighbor: str | None = None
            relation = kind
            if source == path and target in repository_map.files:
                neighbor = target
            elif target == path and source in repository_map.files and kind in {"depends_on", "imports", "tested_by"}:
                neighbor = source
                relation = "reverse_" + kind
            if not neighbor or neighbor == path:
                continue
            is_test_neighbor = (
                relation in {"tested_by", "reverse_tested_by"}
                or repository_map.files.get(neighbor, {}).get("is_test")
            )
            if not is_test_neighbor and dependency_files >= budget.max_dependency_files:
                continue
            graph_nodes += 1
            if is_test_neighbor:
                _metric(metrics, "test_expansions")
                fusion.add(
                    path=neighbor, candidate_type="test", score=0.0, source="test",
                    reason="test_mapping", graph_distance=distance + 1,
                    test_support=neighbor,
                    current_source_identity=_current_source_identity(repository_map, neighbor),
                )
            else:
                dependency_files += 1
                _metric(metrics, "graph_expansions")
                fusion.add(
                    path=neighbor, candidate_type="dependency", score=0.0, source="graph",
                    reason="bounded_dependency_expansion", graph_distance=distance + 1,
                    current_source_identity=_current_source_identity(repository_map, neighbor),
                )
            if distance + 1 <= budget.max_graph_depth and neighbor not in visited:
                queue.append((neighbor, distance + 1))
            if graph_nodes >= budget.max_graph_nodes:
                break


def search_repository(
    query: RepoIntelligenceQuery | str | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
    lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
    semantic_retriever: SemanticRetriever | None = None,
    authority: Mapping[str, Any] | None = None,
    budget: WorkingSetBudget | None = None,
    metrics: dict[str, int] | None = None,
    changed_paths: Iterable[str | Path] = (),
    deleted_paths: Iterable[str | Path] = (),
) -> RepoIntelligenceResult:
    """Run cheap-first deterministic repository retrieval and build context."""
    current = _map_value(repository_map)
    root = _safe_root(project_root or current.project_root)
    if isinstance(query, RepoIntelligenceQuery):
        request = query
    elif isinstance(query, Mapping):
        raw = dict(query)
        raw_budget = raw.get("budget")
        query_budget = (
            WorkingSetBudget(**dict(raw_budget))
            if isinstance(raw_budget, Mapping)
            else (budget or WorkingSetBudget())
        )
        request = RepoIntelligenceQuery(
            query_id=str(raw.get("query_id", "")),
            raw_task_text=str(raw.get("raw_task_text", raw.get("query", ""))),
            explicit_paths=tuple(raw.get("explicit_paths", ())),
            explicit_symbols=tuple(raw.get("explicit_symbols", ())),
            identifiers=tuple(raw.get("identifiers", ())),
            error_strings=tuple(raw.get("error_strings", ())),
            test_names=tuple(raw.get("test_names", ())),
            behavior_terms=tuple(raw.get("behavior_terms", ())),
            requested_detail=int(raw.get("requested_detail", 2)),
            budget=budget or query_budget,
            subject_identity=str(raw.get("subject_identity", "")),
            revision_identity=str(raw.get("revision_identity", "")),
        )
    else:
        request = RepoIntelligenceQuery.from_task(str(query), budget=budget)
    if isinstance(budget, Mapping):
        current_budget = WorkingSetBudget(**dict(budget))
    else:
        current_budget = budget or request.budget
    if current_budget != request.budget:
        request = replace(request, budget=current_budget)
    counters = metrics if metrics is not None else new_core2_metrics()
    for key in CORE2_METRIC_KEYS:
        counters.setdefault(key, 0)
    brain_tuple = tuple(brain_entities)
    attempted: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    fusion = _CandidateFusion(current, authority, counters)
    ambiguous_identities: set[str] = set()

    def can_run(stage: str) -> bool:
        if counters.get("search_stages_executed", 0) >= current_budget.max_search_stages:
            skipped.append({"route": stage, "reason": "max_search_stages_reached"})
            return False
        _metric(counters, "search_stages_executed")
        return True

    if can_run("brain_seed"):
        before = len(fusion.rows)
        _seed_brain(request, current, root, brain_tuple, fusion, counters, unresolved)
        _route(attempted, "brain_seed", "verified references are navigation hints", attempted=True)
        if not brain_tuple:
            attempted.pop()
            _route(skipped, "brain_seed", "no Brain entities supplied", attempted=False)
        elif len(fusion.rows) == before:
            attempted[-1]["reason"] = "no relevant current reference resolved"

    exact_paths: list[str] = []
    if request.explicit_paths and can_run("exact_path"):
        _metric(counters, "exact_path_queries", len(request.explicit_paths))
        for signal in request.explicit_paths:
            matches = _path_matches(current, signal)
            if not matches:
                unresolved.append({"signal": signal, "route": EXACT_PATH, "reason": "path_not_found"})
                continue
            exact_paths.extend(matches)
            for path in matches:
                fusion.add(
                    path=path, candidate_type="file", score=0.0, source="exact_path",
                    reason="exact_path_match" if path == _safe_signal_path(signal) else "normalized_path_candidate",
                    current_source_identity=_current_source_identity(current, path),
                )
        _route(attempted, "exact_path", "canonical path and safe basename resolution", attempted=True)
    elif request.explicit_paths:
        _route(skipped, "exact_path", "search-stage budget exhausted", attempted=False)

    exact_symbols: list[dict[str, Any]] = []
    if (request.explicit_symbols or request.identifiers) and can_run("exact_symbol"):
        signals = _unique((*request.explicit_symbols, *request.identifiers))
        _metric(counters, "exact_symbol_queries", len(signals))
        for signal in signals:
            matches = _symbol_matches(current, signal)
            if not matches:
                continue
            if len(matches) > 1:
                for row in matches:
                    ambiguous_identities.add(f"{row.get('path')}::symbol::{row.get('qualified_name')}")
            exact_symbols.extend(matches)
            for row in matches:
                path = str(row.get("path", ""))
                if path:
                    fusion.add(
                        path=path,
                        symbol=str(row.get("qualified_name", "")),
                        candidate_type="symbol",
                        score=0.0,
                        source="exact_symbol",
                        reason="exact_qualified_symbol_match" if str(row.get("qualified_name")) == signal else "exact_unqualified_symbol_match",
                        current_source_identity=_current_source_identity(current, path, row),
                    )
        if not exact_symbols:
            unresolved.extend({"signal": signal, "route": EXACT_SYMBOL, "reason": "symbol_not_found"} for signal in signals)
        _route(attempted, "exact_symbol", "current RepositoryMap symbol index", attempted=True)
    elif request.explicit_symbols or request.identifiers:
        _route(skipped, "exact_symbol", "search-stage budget exhausted", attempted=False)

    exact_count = len(exact_paths) + len(exact_symbols)
    strong_exact = (
        (len(set(exact_paths)) == 1)
        or bool(exact_symbols) and len(exact_symbols) == 1
    )
    needs_lexical = (
        not strong_exact
        or any(intent in request.intents for intent in (ERROR_LOCALIZATION, BEHAVIORAL_QUERY, ARCHITECTURE_QUERY, GENERAL_CODE_QUERY))
    )
    if needs_lexical and can_run("lexical"):
        lexical_metrics: dict[str, int] = {}
        index, mode = ensure_lexical_index(
            lexical_index, current, root,
            changed_paths=changed_paths, deleted_paths=deleted_paths,
            metrics=lexical_metrics,
        )
        if mode in {"cold_build", "safe_rebuild"}:
            _metric(counters, "lexical_index_builds")
        for key, value in lexical_metrics.items():
            if key == "documents_added":
                _metric(counters, "lexical_documents_added", value)
            elif key == "documents_removed":
                _metric(counters, "lexical_documents_removed", value)
            elif key == "documents_updated":
                _metric(counters, "lexical_documents_updated", value)
            elif key in {"terms_updated", "terms_indexed"}:
                _metric(counters, "lexical_terms_updated", value)
        lexical_query = " ".join((
            request.raw_task_text, *request.identifiers, *request.error_strings,
            *request.behavior_terms, *request.test_names,
        ))
        lexical_rows = index.query(lexical_query, max_results=current_budget.max_lexical_results)
        _metric(counters, "lexical_queries")
        for row in lexical_rows:
            path = str(row.get("path", ""))
            matched = tuple(row.get("matched_terms", ()))
            error_tokens = set(" ".join(request.error_strings).casefold().split())
            reason = "error_token_match" if error_tokens & set(matched) else "lexical_token_match"
            candidate_type = "test" if bool(row.get("document", {}).get("is_test")) else "file"
            fusion.add(
                path=path, candidate_type=candidate_type, score=float(row.get("score", 0.0)),
                source="lexical", reason=reason, matched_terms=matched,
                current_source_identity=_current_source_identity(current, path),
            )
        _route(attempted, "lexical", f"inverted index {mode}; query-time source bodies not scanned", attempted=True)
    else:
        reason = "strong_exact_evidence" if strong_exact else "search-stage budget exhausted"
        _route(skipped, "lexical", reason, attempted=False)

    current_candidates = fusion.freeze(ambiguous_identities=ambiguous_identities)
    needs_graph = bool(current_candidates) and (
        IMPACT_ANALYSIS in request.intents or TEST_FAILURE in request.intents
        or request.requested_detail >= 6
    )
    if needs_graph and can_run("graph_and_tests"):
        before = len(fusion.rows)
        _expand_graph_and_tests(current, fusion, current_candidates, current_budget, counters)
        _route(attempted, "graph_and_tests", "bounded dependency and test expansion from seed candidates", attempted=True)
        if len(fusion.rows) == before:
            attempted[-1]["reason"] = "no bounded graph/test neighbors"
    else:
        _route(skipped, "graph_and_tests", "not required by query intent or no seed candidate", attempted=False)

    current_candidates = fusion.freeze(ambiguous_identities=ambiguous_identities)
    lexical_weak = not current_candidates or current_candidates[0].score < 12.0
    semantic_reason = ""
    semantic_needed = (
        semantic_retriever is not None
        and not strong_exact
        and lexical_weak
        and any(intent in request.intents for intent in (BEHAVIORAL_QUERY, ARCHITECTURE_QUERY, GENERAL_CODE_QUERY))
    )
    if semantic_needed and can_run("semantic"):
        semantic_reason = "no strong exact candidate and lexical evidence remained weak"
        _metric(counters, "semantic_queries")
        try:
            semantic_rows = semantic_retriever.search(request, current, current_budget)
        except Exception as exc:
            semantic_rows = ()
            unresolved.append({"route": "semantic", "reason": "semantic_backend_error", "error_type": type(exc).__name__})
        for row in semantic_rows or ():
            if not isinstance(row, Mapping):
                continue
            path = str(row.get("path", ""))
            if path not in current.files:
                continue
            fusion.add(
                path=path, symbol=row.get("symbol"), candidate_type=str(row.get("candidate_type", "file")),
                score=float(row.get("score", 0.0)), source="semantic", reason="semantic_fallback",
                matched_terms=row.get("matched_terms", ()),
                current_source_identity=_current_source_identity(current, path),
            )
        _route(attempted, "semantic", semantic_reason, attempted=True)
    else:
        if semantic_retriever is None:
            skip_reason = "no semantic backend configured"
        elif strong_exact:
            skip_reason = "strong exact evidence; expensive fallback unnecessary"
        elif not lexical_weak:
            skip_reason = "lexical evidence sufficient"
        else:
            skip_reason = "query intent does not require semantic fallback"
        _metric(counters, "semantic_queries_skipped")
        _route(skipped, "semantic", skip_reason, attempted=False)

    candidates = fusion.freeze(ambiguous_identities=ambiguous_identities)
    counters["candidate_count_deduped"] = len(candidates)
    early_stop = ""
    if strong_exact:
        early_stop = "strong_exact_evidence"
        _metric(counters, "early_stop_count")
    elif semantic_retriever is None and lexical_weak:
        early_stop = "bounded_deterministic_routes_exhausted_without_semantic_backend"
    working_set = build_task_working_set(
        request, candidates, repository_map=current, brain_entities=brain_tuple,
        authority=authority, budget=current_budget, unresolved_evidence=unresolved,
    )
    if request.requested_detail >= 3 and working_set.items:
        working_set = expand_working_set(
            working_set, current, root, requested_level=request.requested_detail,
            metrics=counters, brain_entities=brain_tuple,
        )
    counters["working_set_files"] = len(working_set.files)
    counters["working_set_symbols"] = len(working_set.symbols)
    counters["source_bodies_loaded"] = max(
        counters.get("source_bodies_loaded", 0),
        working_set.budget_usage.get("source_bodies_loaded", 0),
    )
    counters["full_files_loaded"] = max(
        counters.get("full_files_loaded", 0),
        working_set.budget_usage.get("full_file_reads", 0),
    )
    budget_usage = {
        **working_set.budget_usage,
        "search_stages_executed": counters.get("search_stages_executed", 0),
        "candidates": len(candidates),
        "semantic_queries": counters.get("semantic_queries", 0),
    }
    return RepoIntelligenceResult(
        query=request,
        intents=request.intents,
        routes_attempted=tuple(attempted),
        routes_skipped=tuple(skipped),
        candidates=candidates,
        working_set=working_set,
        budget_usage=budget_usage,
        metrics=dict(counters),
        unresolved_evidence=tuple(unresolved),
        early_stop_reason=early_stop,
        semantic_fallback_reason=semantic_reason,
    )


def benchmark_repository_navigation(
    cases: Iterable[Mapping[str, Any]],
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
    semantic_retriever: SemanticRetriever | None = None,
    authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate deterministic navigation fixtures, not global model quality."""
    case_results: list[dict[str, Any]] = []
    file_recalls_5: list[float] = []
    file_recalls_10: list[float] = []
    symbol_recalls_5: list[float] = []
    first_ranks: list[int] = []
    for case in cases:
        query = case.get("query", "")
        result = search_repository(
            query, repository_map, project_root,
            lexical_index=lexical_index, brain_entities=brain_entities,
            semantic_retriever=semantic_retriever, authority=authority,
        )
        relevant_files = {str(item).replace("\\", "/") for item in case.get("relevant_files", ())}
        relevant_symbols = {str(item) for item in case.get("relevant_symbols", ())}
        top_files = [candidate.path for candidate in result.candidates[:10]]
        top_symbols = [candidate.identity for candidate in result.candidates[:5] if candidate.symbol]
        file_recalls_5.append(len(relevant_files & set(top_files[:5])) / max(1, len(relevant_files)))
        file_recalls_10.append(len(relevant_files & set(top_files[:10])) / max(1, len(relevant_files)))
        symbol_recalls_5.append(len(relevant_symbols & set(top_symbols[:5])) / max(1, len(relevant_symbols)))
        rank = next((index for index, path in enumerate(top_files, 1) if path in relevant_files), 0)
        if rank:
            first_ranks.append(rank)
        case_results.append({
            "name": case.get("name", "case"),
            "file_recall_at_5": file_recalls_5[-1],
            "file_recall_at_10": file_recalls_10[-1],
            "symbol_recall_at_5": symbol_recalls_5[-1],
            "first_relevant_rank": rank,
            "irrelevant_files_selected": len([path for path in top_files if path not in relevant_files]),
            "source_bodies_loaded": result.metrics.get("source_bodies_loaded", 0),
            "full_files_loaded": result.metrics.get("full_files_loaded", 0),
            "working_set_size": len(result.working_set.items) if result.working_set else 0,
            "search_stages_used": result.metrics.get("search_stages_executed", 0),
        })
    count = max(1, len(case_results))
    return {
        "benchmark_kind": "DETERMINISTIC_REPOSITORY_NAVIGATION",
        "cases": case_results,
        "RelevantFileRecall@5": sum(file_recalls_5) / count,
        "RelevantFileRecall@10": sum(file_recalls_10) / count,
        "RelevantSymbolRecall@5": sum(symbol_recalls_5) / count,
        "first_relevant_rank": sum(first_ranks) / max(1, len(first_ranks)),
        "irrelevant_selected_files": sum(item["irrelevant_files_selected"] for item in case_results) / count,
        "source_bodies_loaded": sum(item["source_bodies_loaded"] for item in case_results),
        "full_files_loaded": sum(item["full_files_loaded"] for item in case_results),
        "average_working_set_size": sum(item["working_set_size"] for item in case_results) / count,
        "average_search_stages": sum(item["search_stages_used"] for item in case_results) / count,
    }


# Discoverable aliases for callers that prefer imperative names.
RepoIntelligenceBudget = WorkingSetBudget
search_repository_intelligence = search_repository
build_repo_intelligence_query = RepoIntelligenceQuery.from_task


__all__ = [
    "CORE2_SCHEMA_VERSION", "CORE2_METRIC_KEYS", "new_core2_metrics",
    "EXACT_PATH", "EXACT_SYMBOL", "ERROR_LOCALIZATION", "BEHAVIORAL_QUERY",
    "IMPACT_ANALYSIS", "TEST_FAILURE", "ARCHITECTURE_QUERY", "GENERAL_CODE_QUERY",
    "SEARCH_INTENTS", "SearchIntent", "extract_query_signals", "classify_search_intents",
    "RepoIntelligenceQuery", "SearchCandidate", "RepoIntelligenceResult",
    "SemanticRetriever", "RepoIntelligenceBudget", "search_repository",
    "search_repository_intelligence", "build_repo_intelligence_query",
    "benchmark_repository_navigation",
]
