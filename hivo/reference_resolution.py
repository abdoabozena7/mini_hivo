"""Lazy, progressive resolution of CORE-1 Project Brain references."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .project_brain_refs import (
    ProjectBrainEntity,
    TypedReference,
    canonical_hash,
    new_core1_metrics,
)
from .repository_map import RepositoryMap, _safe_existing_file, _safe_root


RESOLVED_CURRENT = "RESOLVED_CURRENT"
RESOLVED_BUT_CHANGED = "RESOLVED_BUT_CHANGED"
STALE_REFERENCE = "STALE_REFERENCE"
TARGET_MISSING = "TARGET_MISSING"
AMBIGUOUS = "AMBIGUOUS"
INVALID_REFERENCE = "INVALID_REFERENCE"
RESOLUTION_STATES = (
    RESOLVED_CURRENT, RESOLVED_BUT_CHANGED, STALE_REFERENCE,
    TARGET_MISSING, AMBIGUOUS, INVALID_REFERENCE,
)
MIN_EVIDENCE_LEVEL = 0
MAX_EVIDENCE_LEVEL = 6


@dataclass(frozen=True)
class EvidenceResolutionRequest:
    target: TypedReference | str | Mapping[str, Any]
    requested_level: int = 1
    reason: str = "on_demand_reference_resolution"
    max_files: int = 8
    max_symbols: int = 24
    max_characters: int = 12000

    def __post_init__(self) -> None:
        object.__setattr__(self, "target", TypedReference.from_value(self.target))
        level = max(MIN_EVIDENCE_LEVEL, min(MAX_EVIDENCE_LEVEL, int(self.requested_level)))
        object.__setattr__(self, "requested_level", level)
        object.__setattr__(self, "reason", str(self.reason or "on_demand_reference_resolution")[:240])
        object.__setattr__(self, "max_files", max(1, min(64, int(self.max_files))))
        object.__setattr__(self, "max_symbols", max(1, min(128, int(self.max_symbols))))
        object.__setattr__(self, "max_characters", max(256, min(100000, int(self.max_characters))))

    def to_dict(self) -> dict[str, Any]:
        return {
            "target": self.target.to_dict(),
            "requested_level": self.requested_level,
            "reason": self.reason,
            "max_files": self.max_files,
            "max_symbols": self.max_symbols,
            "max_characters": self.max_characters,
        }


@dataclass(frozen=True)
class ResolvedEvidence:
    state: str
    reference: TypedReference | None
    evidence: dict[str, Any] = field(default_factory=dict)
    provenance: dict[str, Any] = field(default_factory=dict)
    candidates: tuple[dict[str, Any], ...] = ()
    requested_level: int = 0
    staleness_state: str = "CURRENT"
    duplicate_source_body_suppressed: bool = False

    @property
    def current_repository_wins(self) -> bool:
        return bool(self.provenance.get("repository_map"))

    @property
    def resolution_state(self) -> str:
        return self.state

    @property
    def current_evidence(self) -> dict[str, Any]:
        return self.evidence

    @property
    def source_body(self) -> str | None:
        value = self.evidence.get("source_body")
        return value if isinstance(value, str) else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "reference": self.reference.to_dict() if self.reference else None,
            "evidence": self.evidence,
            "provenance": self.provenance,
            "candidates": list(self.candidates),
            "requested_level": self.requested_level,
            "staleness_state": self.staleness_state,
            "duplicate_source_body_suppressed": self.duplicate_source_body_suppressed,
        }


def _file_metadata(entry: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: entry.get(key)
        for key in (
            "path", "language", "content_hash", "size", "module_identity",
            "top_level_symbols", "imports", "exports", "known_tests", "index_revision", "is_test",
        )
        if key in entry
    }


class ProjectReferenceResolver:
    """Resolve one requested reference at one explicit evidence level."""

    def __init__(
        self,
        repository_map: RepositoryMap | Mapping[str, Any],
        project_root: str | Path | None = None,
        *,
        brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] | None = None,
        metrics: dict[str, int] | None = None,
    ) -> None:
        self.repository_map = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map, project_root or "")
        self.project_root = _safe_root(project_root or self.repository_map.project_root)
        self.brain_entities = tuple(brain_entities or ())
        self.metrics = metrics if metrics is not None else new_core1_metrics()
        self._loaded_source_keys: set[str] = set()
        self._loaded_file_paths: set[str] = set()
        self._source_cache: dict[str, str] = {}

    def _result(
        self,
        state: str,
        reference: TypedReference | None,
        *,
        request: EvidenceResolutionRequest | None = None,
        evidence: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
        candidates: Iterable[dict[str, Any]] = (),
        stale: bool = False,
        duplicate: bool = False,
    ) -> ResolvedEvidence:
        if state in {RESOLVED_CURRENT, RESOLVED_BUT_CHANGED, STALE_REFERENCE}:
            self.metrics["references_resolved"] = self.metrics.get("references_resolved", 0) + 1
        else:
            self.metrics["references_not_resolved"] = self.metrics.get("references_not_resolved", 0) + 1
        if stale:
            self.metrics["stale_references_detected"] = self.metrics.get("stale_references_detected", 0) + 1
        return ResolvedEvidence(
            state=state, reference=reference, evidence=evidence or {}, provenance=provenance or {},
            candidates=tuple(candidates), requested_level=request.requested_level if request else 0,
            staleness_state="STALE_REFERENCE" if stale else "CURRENT",
            duplicate_source_body_suppressed=duplicate,
        )

    def _brain_for_reference(self, reference: TypedReference) -> ProjectBrainEntity | None:
        for item in self.brain_entities:
            try:
                entity = item if isinstance(item, ProjectBrainEntity) else ProjectBrainEntity.from_dict(item)
            except (TypeError, ValueError):
                continue
            if any(ref.canonical_uri == reference.canonical_uri for ref in entity.references):
                return entity
        return None

    def _provenance(self, entity: ProjectBrainEntity | None) -> dict[str, Any]:
        return {
            "brain": {
                "entity_id": entity.entity_id,
                "knowledge": "verified_semantic_projection",
            } if entity else None,
            "repository_map": {
                "logical_hash": self.repository_map.logical_hash,
                "index_revision": self.repository_map.index_revision,
                "knowledge": "mechanically_derived_current_metadata",
            },
            "source": "not_loaded",
        }

    def _resolve_symbol_candidates(self, reference: TypedReference) -> list[dict[str, Any]]:
        qualified = str(reference.symbol or "")
        if not reference.path:
            return [
                row for row in self.repository_map.symbols.values()
                if row.get("qualified_name") == qualified
            ]
        exact_id = f"{reference.path}::function::{qualified}"
        exact_class = f"{reference.path}::class::{qualified}"
        exact_constant = f"{reference.path}::constant::{qualified}"
        direct = [
            self.repository_map.symbols[symbol_id]
            for symbol_id in (exact_id, exact_class, exact_constant)
            if symbol_id in self.repository_map.symbols
        ]
        if direct:
            return direct
        return [
            row for row in self.repository_map.symbols.values()
            if row.get("path") == reference.path and row.get("qualified_name") == qualified
        ]

    def _read_source(self, relative: str) -> str | None:
        if relative in self._source_cache:
            return self._source_cache[relative]
        path = _safe_existing_file(self.project_root, relative)
        if path is None:
            return None
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None
        self._source_cache[relative] = text
        return text

    def _add_symbol_detail(
        self,
        evidence: dict[str, Any],
        provenance: dict[str, Any],
        symbol: Mapping[str, Any],
        request: EvidenceResolutionRequest,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        evidence["symbol"] = dict(symbol)
        if request.requested_level < 3:
            return evidence, provenance, False
        source_key = str(symbol.get("symbol_id") or f"{symbol.get('path')}::{symbol.get('qualified_name')}")
        if source_key in self._loaded_source_keys:
            evidence["source_body"] = None
            provenance["source"] = "duplicate_suppressed"
            self.metrics["duplicate_source_bodies_suppressed"] = self.metrics.get("duplicate_source_bodies_suppressed", 0) + 1
            return evidence, provenance, True
        text = self._read_source(str(symbol.get("path", "")))
        if text is None:
            return evidence, provenance, False
        lines = text.splitlines()
        start = max(1, int(symbol.get("start_line", 1) or 1))
        end = max(start, int(symbol.get("end_line", start) or start))
        body = "\n".join(lines[start - 1:min(end, len(lines))])
        body = body[:request.max_characters]
        evidence["source_body"] = body
        provenance["source"] = "current_repository_symbol_body"
        self._loaded_source_keys.add(source_key)
        self.metrics["source_bodies_loaded"] = self.metrics.get("source_bodies_loaded", 0) + 1
        if request.requested_level >= 4:
            evidence["enclosing_file_slice"] = body
        return evidence, provenance, False

    def _add_full_file_detail(
        self,
        evidence: dict[str, Any],
        provenance: dict[str, Any],
        path: str,
        request: EvidenceResolutionRequest,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        if request.requested_level < 5:
            return evidence, provenance, False
        if path in self._loaded_file_paths:
            evidence["full_file"] = None
            provenance["source"] = "duplicate_suppressed"
            self.metrics["duplicate_source_bodies_suppressed"] = self.metrics.get("duplicate_source_bodies_suppressed", 0) + 1
            return evidence, provenance, True
        text = self._read_source(path)
        if text is None:
            return evidence, provenance, False
        evidence["full_file"] = text[:request.max_characters]
        provenance["source"] = "current_repository_full_file"
        self._loaded_file_paths.add(path)
        self.metrics["source_bodies_loaded"] = self.metrics.get("source_bodies_loaded", 0) + 1
        self.metrics["full_file_reads_requested"] = self.metrics.get("full_file_reads_requested", 0) + 1
        return evidence, provenance, False

    def _add_neighborhood(self, evidence: dict[str, Any], target_path: str, request: EvidenceResolutionRequest) -> None:
        if request.requested_level < 6:
            return
        neighbors: list[dict[str, Any]] = []
        for edge in self.repository_map.edges:
            if edge.get("source") == target_path:
                neighbor = edge.get("target")
                if neighbor in self.repository_map.files:
                    neighbors.append(_file_metadata(self.repository_map.files[neighbor]))
            elif edge.get("target") == target_path and edge.get("source") in self.repository_map.files:
                neighbors.append(_file_metadata(self.repository_map.files[edge["source"]]))
        unique: dict[str, dict] = {row.get("path", ""): row for row in neighbors if row.get("path")}
        evidence["dependency_test_neighborhood"] = [unique[key] for key in sorted(unique)[:request.max_files]]

    def resolve(
        self,
        reference: TypedReference | str | Mapping[str, Any],
        request: EvidenceResolutionRequest | None = None,
        *,
        brain_entity: ProjectBrainEntity | Mapping[str, Any] | None = None,
    ) -> ResolvedEvidence:
        try:
            typed = TypedReference.from_value(reference)
        except (TypeError, ValueError):
            return self._result(INVALID_REFERENCE, None, request=request)
        if request is None:
            request = EvidenceResolutionRequest(typed, requested_level=1)
        elif request.target.canonical_uri != typed.canonical_uri:
            request = EvidenceResolutionRequest(
                typed, requested_level=request.requested_level, reason=request.reason,
                max_files=request.max_files, max_symbols=request.max_symbols,
                max_characters=request.max_characters,
            )
        entity: ProjectBrainEntity | None
        if brain_entity is not None:
            try:
                entity = brain_entity if isinstance(brain_entity, ProjectBrainEntity) else ProjectBrainEntity.from_dict(brain_entity)
            except (TypeError, ValueError):
                entity = None
        else:
            entity = self._brain_for_reference(typed)
        provenance = self._provenance(entity)
        if request.requested_level == 0:
            if entity:
                evidence = {
                    "brain_entity": {
                        "entity_id": entity.entity_id, "entity_kind": entity.entity_kind,
                        "name": entity.name, "summary": entity.summary,
                        "contracts": list(entity.contracts), "invariants": list(entity.invariants),
                    }
                }
            else:
                evidence = {"reference": typed.to_dict()}
            return self._result(RESOLVED_CURRENT, typed, request=request, evidence=evidence, provenance=provenance)

        target_path = typed.path if typed.kind in {"file", "symbol", "test"} else None
        entry = self.repository_map.files.get(target_path) if target_path else None
        symbol: dict[str, Any] | None = None
        if typed.kind == "symbol":
            candidates = self._resolve_symbol_candidates(typed)
            if len(candidates) > 1:
                return self._result(AMBIGUOUS, typed, request=request, provenance=provenance, candidates=candidates)
            symbol = dict(candidates[0]) if candidates else None
            if symbol:
                entry = self.repository_map.files.get(str(symbol.get("path")))
        elif typed.kind == "test" and (not entry or not entry.get("is_test")):
            entry = None
        elif typed.kind == "graph":
            graph_candidates = [
                row for row in self.repository_map.symbols.values()
                if row.get("qualified_name") == typed.path or row.get("symbol_id") == typed.path
            ]
            if len(graph_candidates) > 1:
                return self._result(AMBIGUOUS, typed, request=request, provenance=provenance, candidates=graph_candidates)
            if graph_candidates:
                symbol = dict(graph_candidates[0])
                entry = self.repository_map.files.get(str(symbol.get("path")))
        if entry is None:
            return self._result(TARGET_MISSING, typed, request=request, provenance=provenance)

        evidence: dict[str, Any] = {"repository_file": _file_metadata(entry)}
        current_anchor = str(entry.get("content_hash", ""))
        if symbol:
            evidence, provenance, duplicate = self._add_symbol_detail(evidence, provenance, symbol, request)
            current_anchor = str(symbol.get("anchor_hash", current_anchor))
        else:
            duplicate = False
        evidence, provenance, full_duplicate = self._add_full_file_detail(
            evidence, provenance, str(entry.get("path", typed.path)), request,
        )
        duplicate = duplicate or full_duplicate
        self._add_neighborhood(evidence, str(entry.get("path", typed.path)), request)
        expected_anchor = typed.anchor_hash
        changed = bool(expected_anchor and expected_anchor != current_anchor)
        expected_file_hash = None
        if entity and target_path:
            for path, digest in entity.verified_source_hashes:
                if path.replace("\\", "/").lstrip("./") == target_path:
                    expected_file_hash = digest
                    break
        if expected_file_hash and str(entry.get("content_hash", "")) != expected_file_hash:
            changed = True
        if target_path and target_path in self.repository_map.invalidated_references:
            changed = True
        if symbol and str(symbol.get("symbol_id", "")) in self.repository_map.invalidated_references:
            changed = True
        if typed.verified_revision and typed.verified_revision != self.repository_map.index_revision:
            changed = True
        stale = bool(entity and entity.staleness_state == STALE_REFERENCE) or (changed and entity is not None)
        if stale:
            provenance["source"] = provenance.get("source", "not_loaded")
            provenance["stale_reason"] = "verified_reference_anchor_or_revision_changed"
            state = STALE_REFERENCE
        elif changed:
            state = RESOLVED_BUT_CHANGED
            provenance["stale_reason"] = "reference_anchor_or_revision_changed"
        else:
            state = RESOLVED_CURRENT
        return self._result(
            state, typed, request=request, evidence=evidence, provenance=provenance,
            stale=stale or changed, duplicate=duplicate,
        )

    def request_project_evidence(
        self,
        request: EvidenceResolutionRequest,
        *,
        brain_entity: ProjectBrainEntity | Mapping[str, Any] | None = None,
    ) -> ResolvedEvidence:
        return self.resolve(request.target, request=request, brain_entity=brain_entity)


def resolve_project_reference(
    reference: TypedReference | str | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path,
    *,
    request: EvidenceResolutionRequest | None = None,
    brain_entity: ProjectBrainEntity | Mapping[str, Any] | None = None,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] | None = None,
    metrics: dict[str, int] | None = None,
) -> ResolvedEvidence:
    resolver = ProjectReferenceResolver(
        repository_map, project_root, brain_entities=brain_entities, metrics=metrics,
    )
    return resolver.resolve(reference, request=request, brain_entity=brain_entity)


def request_project_evidence(
    resolver_or_reference: ProjectReferenceResolver | TypedReference | str | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any] | None = None,
    project_root: str | Path | None = None,
    *,
    request: EvidenceResolutionRequest | None = None,
    level: int | None = None,
    brain_entity: ProjectBrainEntity | Mapping[str, Any] | None = None,
    metrics: dict[str, int] | None = None,
) -> ResolvedEvidence:
    if isinstance(resolver_or_reference, ProjectReferenceResolver):
        resolver = resolver_or_reference
        reference = request.target if request is not None else None
        if reference is None:
            raise ValueError("request is required when passing a resolver")
        return resolver.resolve(reference, request=request, brain_entity=brain_entity)
    if repository_map is None or project_root is None:
        raise ValueError("repository_map and project_root are required")
    if request is None:
        request = EvidenceResolutionRequest(resolver_or_reference, requested_level=level or 1)
    return resolve_project_reference(
        resolver_or_reference, repository_map, project_root,
        request=request, brain_entity=brain_entity, metrics=metrics,
    )


__all__ = [
    "RESOLVED_CURRENT", "RESOLVED_BUT_CHANGED", "STALE_REFERENCE", "TARGET_MISSING",
    "AMBIGUOUS", "INVALID_REFERENCE", "RESOLUTION_STATES", "EvidenceResolutionRequest",
    "ResolvedEvidence", "ProjectReferenceResolver", "resolve_project_reference",
    "request_project_evidence",
]
