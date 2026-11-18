"""Reference-based Project Brain entities for CORE-1.

The pre-CORE Brain stores verified semantic facts.  This module adds a small,
typed reference layer without turning that Brain into a source-code cache.
Everything here is deterministic and deliberately independent of providers,
workers, approval, and mutation code.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from typing import Any, Iterable, Mapping
from urllib.parse import parse_qs, urlencode


PROJECT_BRAIN_ENTITY_SCHEMA_VERSION = "CORE-1-BRAIN-V2"
REFERENCE_KINDS = ("file", "symbol", "test", "graph", "decision")
ENTITY_KINDS = (
    "MODULE", "FILE", "SYMBOL", "SERVICE", "INTERFACE", "DATA_MODEL",
    "TEST_AREA", "ARCHITECTURE_DECISION", "CONTRACT",
)
STALENESS_STATES = ("CURRENT", "STALE_REFERENCE", "UNKNOWN")
MAX_ENTITY_SUMMARY_CHARS = 2400
MAX_ENTITY_FIELD_CHARS = 1200
MAX_REFERENCE_COUNT = 64
MAX_SOURCE_HASHES = 128
_FORBIDDEN_SOURCE_KEYS = frozenset({
    "source", "source_text", "body", "full_file", "file_body", "snapshot",
    "raw_source", "raw_content", "repository_snapshot", "entire_file",
})

CORE1_METRIC_KEYS = (
    "cold_index_files_scanned",
    "incremental_files_reparsed",
    "incremental_edges_recomputed",
    "brain_entities_examined",
    "references_resolved",
    "references_not_resolved",
    "stale_references_detected",
    "source_bodies_loaded",
    "duplicate_source_bodies_suppressed",
    "full_file_reads_requested",
)


def new_core1_metrics() -> dict[str, int]:
    """Return an independent zeroed metric set for one operation or replay."""
    return {key: 0 for key in CORE1_METRIC_KEYS}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    )


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _normalise_component(value: str, *, label: str) -> str:
    normalized = str(value or "").strip().replace("\\", "/")
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    if "\x00" in normalized:
        raise ValueError(f"{label} contains a NUL")
    return normalized


def normalize_relative_path(value: str) -> str:
    """Normalize a repository-relative path and reject traversal/absolute paths."""
    normalized = _normalise_component(value, label="path")
    if normalized.startswith(("/", "//")) or re.match(r"^[A-Za-z]:/", normalized):
        raise ValueError("reference path must be relative")
    parts: list[str] = []
    for part in normalized.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("reference path traversal is not allowed")
        parts.append(part)
    if not parts:
        raise ValueError("reference path must identify a target")
    return "/".join(parts)


@dataclass(frozen=True)
class TypedReference:
    """Canonical, typed pointer into repository or architectural evidence."""

    kind: str
    path: str = ""
    symbol: str | None = None
    anchor_hash: str | None = None
    verified_revision: str | None = None

    def __post_init__(self) -> None:
        kind = str(self.kind or "").strip().casefold().removesuffix("://")
        if kind not in REFERENCE_KINDS:
            raise ValueError(f"unsupported reference kind: {self.kind}")
        object.__setattr__(self, "kind", kind)
        raw_path = str(self.path or "").strip()
        if kind == "symbol" and not raw_path:
            path = ""
        else:
            path = _normalise_component(raw_path, label="reference path")
        if kind in {"file", "symbol", "test"}:
            if path:
                path = normalize_relative_path(path)
            elif kind != "symbol":
                raise ValueError("reference path must identify a target")
        else:
            # Graph/decision identities are names, not filesystem paths, but
            # still reject path-like authority escapes.
            if path.startswith(("/", "//")) or ".." in path.split("/"):
                raise ValueError("graph/decision reference must be a safe identity")
            path = path.replace("\\", "/")
        object.__setattr__(self, "path", path)
        if kind == "symbol" and not str(self.symbol or "").strip():
            raise ValueError("symbol reference requires a symbol identity")
        if kind != "symbol" and self.symbol is not None:
            raise ValueError("only symbol references may carry a symbol")
        if self.symbol is not None:
            symbol = _normalise_component(self.symbol, label="symbol")
            if "\x00" in symbol or "\n" in symbol:
                raise ValueError("invalid symbol identity")
            object.__setattr__(self, "symbol", symbol)
        if self.anchor_hash is not None:
            anchor = str(self.anchor_hash).strip().lower()
            if anchor and not re.fullmatch(r"[0-9a-f]{8,128}", anchor):
                raise ValueError("anchor_hash must be hexadecimal")
            object.__setattr__(self, "anchor_hash", anchor or None)
        if self.verified_revision is not None:
            revision = str(self.verified_revision).strip()
            if len(revision) > 240:
                raise ValueError("verified_revision is too long")
            object.__setattr__(self, "verified_revision", revision or None)

    @property
    def canonical_uri(self) -> str:
        query_values = {
            key: value for key, value in (
                ("anchor_hash", self.anchor_hash),
                ("verified_revision", self.verified_revision),
            ) if value
        }
        query = "?" + urlencode(query_values) if query_values else ""
        if self.kind == "symbol":
            return f"symbol://{self.path}{query}#{self.symbol}"
        return f"{self.kind}://{self.path}{query}"

    @property
    def identity(self) -> str:
        return self.canonical_uri

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "symbol": self.symbol,
            "anchor_hash": self.anchor_hash,
            "verified_revision": self.verified_revision,
            "canonical_uri": self.canonical_uri,
        }

    @classmethod
    def from_uri(cls, value: str) -> "TypedReference":
        raw = str(value or "").strip()
        if "://" not in raw:
            raise ValueError("reference URI must have a typed scheme")
        kind, remainder = raw.split("://", 1)
        kind = kind.casefold()
        if kind == "symbol":
            if "#" not in remainder:
                raise ValueError("symbol reference URI requires #symbol")
            path_query, symbol = remainder.split("#", 1)
        else:
            path_query, symbol = remainder, None
        if "?" in path_query:
            path, raw_query = path_query.split("?", 1)
            query = parse_qs(raw_query, keep_blank_values=False)
            anchor = (query.get("anchor_hash") or [None])[0]
            revision = (query.get("verified_revision") or [None])[0]
        else:
            path, anchor, revision = path_query, None, None
        return cls(kind, path, symbol, anchor, revision)

    @classmethod
    def from_value(cls, value: Any) -> "TypedReference":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            return cls.from_uri(value)
        if isinstance(value, Mapping):
            data = dict(value)
            data.pop("canonical_uri", None)
            return cls(
                str(data.get("kind", "")),
                str(data.get("path", "")),
                data.get("symbol"),
                data.get("anchor_hash"),
                data.get("verified_revision"),
            )
        raise ValueError("reference must be a typed URI or object")


def _reject_source_duplication(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("Brain entity nesting is too deep")
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized_key = str(key).casefold().replace("-", "_")
            if normalized_key in _FORBIDDEN_SOURCE_KEYS:
                raise ValueError("Project Brain entities cannot store source bodies")
            _reject_source_duplication(item, depth=depth + 1)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _reject_source_duplication(item, depth=depth + 1)
    elif isinstance(value, str) and len(value) > 12000:
        raise ValueError("Project Brain entity field is too large")


@dataclass(frozen=True)
class ProjectBrainEntity:
    """Small semantic entity whose repository details are represented by refs."""

    entity_id: str
    entity_kind: str
    name: str
    summary: str
    contracts: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    references: tuple[TypedReference, ...] = ()
    verified_subject_identity: str = ""
    verified_revision_identity: str = ""
    verified_source_hashes: tuple[tuple[str, str], ...] = ()
    created_from_verified_evidence: bool = False
    staleness_state: str = "CURRENT"
    schema_version: str = PROJECT_BRAIN_ENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        entity_id = _normalise_component(self.entity_id, label="entity_id")
        kind = str(self.entity_kind or "").strip().upper()
        if kind not in ENTITY_KINDS:
            raise ValueError(f"unsupported entity kind: {self.entity_kind}")
        name = _normalise_component(self.name, label="name")
        summary = str(self.summary or "").strip()
        if len(summary) > MAX_ENTITY_SUMMARY_CHARS:
            raise ValueError("Brain entity summary is too long")
        if self.staleness_state not in STALENESS_STATES:
            raise ValueError(f"unsupported staleness state: {self.staleness_state}")
        if not str(self.schema_version or "").strip():
            raise ValueError("schema_version is required")
        contracts = tuple(str(item).strip() for item in self.contracts if str(item).strip())
        invariants = tuple(str(item).strip() for item in self.invariants if str(item).strip())
        if any(len(item) > MAX_ENTITY_FIELD_CHARS for item in contracts + invariants):
            raise ValueError("Brain contract/invariant is too long")
        references = tuple(TypedReference.from_value(item) for item in self.references)
        if len(references) > MAX_REFERENCE_COUNT:
            raise ValueError("too many Brain references")
        source_hashes = self.verified_source_hashes
        if isinstance(source_hashes, Mapping):
            source_hashes = tuple(sorted(
                (normalize_relative_path(str(path)), str(digest).lower())
                for path, digest in source_hashes.items()
            ))
        else:
            source_hashes = tuple(sorted(
                (normalize_relative_path(str(path)), str(digest).lower()) for path, digest in source_hashes
            ))
        if len(source_hashes) > MAX_SOURCE_HASHES:
            raise ValueError("too many verified source hashes")
        if any(not path or not digest for path, digest in source_hashes):
            raise ValueError("verified source hashes must be non-empty")
        object.__setattr__(self, "entity_id", entity_id)
        object.__setattr__(self, "entity_kind", kind)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "contracts", contracts)
        object.__setattr__(self, "invariants", invariants)
        object.__setattr__(self, "references", references)
        object.__setattr__(self, "verified_source_hashes", source_hashes)
        _reject_source_duplication(self.to_dict())

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def with_staleness(self, state: str = "STALE_REFERENCE") -> "ProjectBrainEntity":
        """Return a marked copy; durable storage is never changed implicitly."""
        return replace(self, staleness_state=state)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_id": self.entity_id,
            "entity_kind": self.entity_kind,
            "name": self.name,
            "summary": self.summary,
            "contracts": list(self.contracts),
            "invariants": list(self.invariants),
            "references": [reference.to_dict() for reference in self.references],
            "verified_subject_identity": self.verified_subject_identity,
            "verified_revision_identity": self.verified_revision_identity,
            "verified_source_hashes": {
                path: digest for path, digest in self.verified_source_hashes
            },
            "created_from_verified_evidence": bool(self.created_from_verified_evidence),
            "staleness_state": self.staleness_state,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ProjectBrainEntity":
        data = dict(value)
        _reject_source_duplication(data)
        return cls(
            entity_id=str(data.get("entity_id", "")),
            entity_kind=str(data.get("entity_kind", "")),
            name=str(data.get("name", "")),
            summary=str(data.get("summary", "")),
            contracts=tuple(data.get("contracts", []) or []),
            invariants=tuple(data.get("invariants", []) or []),
            references=tuple(data.get("references", []) or []),
            verified_subject_identity=str(data.get("verified_subject_identity", "")),
            verified_revision_identity=str(data.get("verified_revision_identity", "")),
            verified_source_hashes=data.get("verified_source_hashes", {}) or {},
            created_from_verified_evidence=bool(data.get("created_from_verified_evidence", False)),
            staleness_state=str(data.get("staleness_state", "CURRENT")),
            schema_version=str(data.get("schema_version", PROJECT_BRAIN_ENTITY_SCHEMA_VERSION)),
        )

    @classmethod
    def from_legacy_record(cls, record: Mapping[str, Any]) -> "ProjectBrainEntity":
        """Read an old verified-fact record without changing its durable shape."""
        raw_fact = record.get("fact", record)
        fact = dict(raw_fact) if isinstance(raw_fact, Mapping) else {"fact": str(raw_fact)}
        record_id = str(record.get("record_id") or record.get("id") or "legacy-record")
        fact_text = str(fact.get("fact") or fact.get("summary") or fact.get("text") or "")
        category = str(fact.get("category") or "CONTRACT").upper()
        kind = category if category in ENTITY_KINDS else "CONTRACT"
        refs: list[TypedReference] = []
        for value in fact.get("references", []) or []:
            try:
                refs.append(TypedReference.from_value(value))
            except ValueError:
                continue
        durability = str(record.get("durability_class") or fact.get("durability_class") or "")
        verified = bool(
            fact.get("verified") is True
            or record.get("verified") is True
            or durability in {"DURABLE_VERIFIED", "STATE_BOUND_VERIFIED"}
        )
        return cls(
            entity_id=record_id,
            entity_kind=kind,
            name=str(fact.get("name") or fact.get("field") or category),
            summary=fact_text[:MAX_ENTITY_SUMMARY_CHARS],
            contracts=tuple(str(item) for item in fact.get("contracts", []) or []),
            invariants=tuple(str(item) for item in fact.get("invariants", []) or []),
            references=tuple(refs),
            verified_subject_identity=str(
                record.get("subject_state_hash") or fact.get("subject_state_hash") or ""
            ),
            verified_revision_identity=str(fact.get("verified_revision_identity") or ""),
            verified_source_hashes=fact.get("verified_source_hashes", {}) or {},
            created_from_verified_evidence=verified,
            staleness_state="CURRENT" if record.get("status", "ACTIVE") == "ACTIVE" else "STALE_REFERENCE",
            schema_version="CORE-1-BRAIN-V2-FROM-LEGACY",
        )


def validate_project_brain_entity(entity: ProjectBrainEntity | Mapping[str, Any]) -> dict[str, Any]:
    """Validate an entity at the durable boundary without persisting anything."""
    try:
        normalized = entity if isinstance(entity, ProjectBrainEntity) else ProjectBrainEntity.from_dict(entity)
        if not normalized.created_from_verified_evidence:
            return {
                "valid": False,
                "status": "UNVERIFIED_BRAIN_ENTITY",
                "entity": normalized.to_dict(),
            }
        return {
            "valid": True,
            "status": "VERIFIED_BRAIN_ENTITY",
            "entity": normalized.to_dict(),
            "entity_hash": normalized.canonical_hash,
        }
    except (TypeError, ValueError) as exc:
        return {"valid": False, "status": "INVALID_BRAIN_ENTITY", "error": str(exc)}


def create_project_brain_entity(**kwargs: Any) -> ProjectBrainEntity:
    """Construct a durable-eligible entity only from explicitly verified input."""
    if kwargs.get("created_from_verified_evidence") is not True:
        raise ValueError("CORE-1 durable entities require verified evidence")
    return ProjectBrainEntity(**kwargs)


def normalize_legacy_brain_record(record: Mapping[str, Any]) -> ProjectBrainEntity:
    """Canonical in-memory V2 view for a legacy record; durable data is untouched."""
    return ProjectBrainEntity.from_legacy_record(record)


def mark_reference_stale(entity: ProjectBrainEntity | Mapping[str, Any]) -> ProjectBrainEntity:
    normalized = entity if isinstance(entity, ProjectBrainEntity) else ProjectBrainEntity.from_dict(entity)
    return normalized.with_staleness("STALE_REFERENCE")


def query_project_brain(
    entities: Iterable[ProjectBrainEntity | Mapping[str, Any]],
    query: str = "",
    *,
    max_items: int = 8,
    include_stale: bool = False,
    metrics: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Return bounded semantic projections; references remain unresolved."""
    counters = metrics if metrics is not None else new_core1_metrics()
    query_tokens = set(re.findall(r"[\w.-]{2,}", str(query).casefold()))
    rows: list[dict[str, Any]] = []
    for item in entities:
        counters["brain_entities_examined"] = counters.get("brain_entities_examined", 0) + 1
        try:
            entity = item if isinstance(item, ProjectBrainEntity) else ProjectBrainEntity.from_dict(item)
        except (TypeError, ValueError):
            continue
        if not include_stale and entity.staleness_state != "CURRENT":
            continue
        searchable = " ".join((entity.name, entity.summary, *entity.contracts, *entity.invariants)).casefold()
        overlap = sum(1 for token in query_tokens if token in searchable)
        rows.append({
            "entity_id": entity.entity_id,
            "entity_kind": entity.entity_kind,
            "name": entity.name,
            "summary": entity.summary,
            "contracts": list(entity.contracts),
            "invariants": list(entity.invariants),
            "references": [reference.to_dict() for reference in entity.references],
            "verified_subject_identity": entity.verified_subject_identity,
            "verified_revision_identity": entity.verified_revision_identity,
            "staleness_state": entity.staleness_state,
            "relevance": overlap * 5 + (1 if entity.staleness_state == "CURRENT" else 0),
        })
    rows.sort(key=lambda row: (int(row["relevance"]), row["name"], row["entity_id"]), reverse=True)
    for row in rows:
        row.pop("relevance", None)
    return rows[: max(0, int(max_items))]


# Small aliases make the data model easy to discover while preserving one
# implementation and one canonical representation.
Reference = TypedReference
BrainEntity = ProjectBrainEntity
create_brain_entity = create_project_brain_entity


__all__ = [
    "PROJECT_BRAIN_ENTITY_SCHEMA_VERSION", "REFERENCE_KINDS", "ENTITY_KINDS",
    "STALENESS_STATES", "CORE1_METRIC_KEYS", "new_core1_metrics",
    "canonical_json", "canonical_hash", "normalize_relative_path",
    "TypedReference", "Reference", "ProjectBrainEntity", "BrainEntity",
    "validate_project_brain_entity", "create_project_brain_entity", "create_brain_entity",
    "normalize_legacy_brain_record", "mark_reference_stale", "query_project_brain",
]
