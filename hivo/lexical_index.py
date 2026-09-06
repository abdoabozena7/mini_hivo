"""Deterministic incremental lexical retrieval for CORE-2.

The index stores token postings and document metadata, never source bodies.
It is deliberately independent of providers and can be rebuilt safely when
its repository-map identity no longer matches the current subject.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from .project_brain_refs import canonical_hash, canonical_json, normalize_relative_path
from .repository_map import RepositoryMap, _safe_existing_file, _safe_relative, _safe_root


LEXICAL_INDEX_SCHEMA_VERSION = "CORE-2-LEXICAL-INDEX-V1"
MAX_LEXICAL_SOURCE_BYTES = 2_000_000
TOKEN_PATTERN = re.compile(r"[A-Za-z_$][A-Za-z0-9_$.-]{1,}")


def normalize_term(value: str) -> str:
    return str(value or "").strip().casefold()


def tokenize(value: str) -> tuple[str, ...]:
    return tuple(normalize_term(token) for token in TOKEN_PATTERN.findall(str(value or "")))


def _map_value(repository_map: RepositoryMap | Mapping[str, Any]) -> RepositoryMap:
    return repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)


def _document_metadata(repository_map: RepositoryMap, path: str) -> dict[str, Any]:
    entry = repository_map.files.get(path, {})
    symbols = [
        symbol for symbol in repository_map.symbols.values()
        if symbol.get("path") == path
    ]
    symbols.sort(key=lambda row: str(row.get("symbol_id", "")))
    metadata = " ".join([
        path,
        str(entry.get("module_identity", "")),
        " ".join(str(item) for item in entry.get("exports", [])),
        " ".join(str(item.get("specifier", "")) for item in entry.get("imports", [])),
        " ".join(str(item) for item in entry.get("known_tests", [])),
        " ".join(str(item.get("qualified_name", "")) for item in symbols),
        " ".join(str(item.get("signature", "")) for item in symbols),
    ])
    return {
        "path": path,
        "content_hash": entry.get("content_hash", ""),
        "size": entry.get("size", 0),
        "is_test": bool(entry.get("is_test")),
        "language": entry.get("language", ""),
        "metadata_terms": sorted(set(tokenize(metadata))),
        "symbol_ids": sorted(str(item.get("symbol_id", "")) for item in symbols),
    }


def _read_indexable_text(root: Path, path: str) -> str:
    file_path = _safe_existing_file(root, path)
    if file_path is None:
        return ""
    try:
        if file_path.stat().st_size > MAX_LEXICAL_SOURCE_BYTES:
            return ""
        return file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _term_counts(repository_map: RepositoryMap, root: Path, path: str) -> Counter[str]:
    metadata = _document_metadata(repository_map, path)
    text = " ".join(metadata["metadata_terms"])
    return Counter(tokenize(text) + tokenize(_read_indexable_text(root, path)))


@dataclass
class LexicalIndex:
    """A mutable index whose serialized form is deterministic and metadata-only."""

    project_root: str = field(repr=False, default="")
    repository_map_hash: str = ""
    index_revision: str = ""
    documents: dict[str, dict[str, Any]] = field(default_factory=dict)
    postings: dict[str, dict[str, int]] = field(default_factory=dict)
    schema_version: str = LEXICAL_INDEX_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.project_root:
            self.project_root = str(Path(self.project_root).expanduser().resolve())
        self.documents = {
            str(path).replace("\\", "/"): dict(value)
            for path, value in self.documents.items()
        }
        self.postings = {
            normalize_term(term): {str(path): int(count) for path, count in values.items()}
            for term, values in self.postings.items()
        }

    @property
    def document_count(self) -> int:
        return len(self.documents)

    @property
    def logical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @property
    def index_hash(self) -> str:
        return self.logical_hash

    def is_current(self, repository_map: RepositoryMap | Mapping[str, Any]) -> bool:
        current = _map_value(repository_map)
        return (
            self.repository_map_hash == current.logical_hash
            and self.index_revision == current.index_revision
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "repository_map_hash": self.repository_map_hash,
            "index_revision": self.index_revision,
            "documents": {
                path: self.documents[path]
                for path in sorted(self.documents)
            },
            "postings": {
                term: {
                    path: self.postings[term][path]
                    for path in sorted(self.postings[term])
                }
                for term in sorted(self.postings)
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any], project_root: str | Path = "") -> "LexicalIndex":
        data = dict(value)
        return cls(
            project_root=str(project_root),
            repository_map_hash=str(data.get("repository_map_hash", "")),
            index_revision=str(data.get("index_revision", "")),
            documents=dict(data.get("documents", {}) or {}),
            postings=dict(data.get("postings", {}) or {}),
            schema_version=str(data.get("schema_version", LEXICAL_INDEX_SCHEMA_VERSION)),
        )

    def _remove_document(self, path: str) -> set[str]:
        old = self.documents.pop(path, None)
        if not old:
            return set()
        changed_terms = set(str(term) for term in old.get("term_counts", {}))
        for term in list(changed_terms):
            posting = self.postings.get(term, {})
            posting.pop(path, None)
            if not posting:
                self.postings.pop(term, None)
        return changed_terms

    def _add_document(self, repository_map: RepositoryMap, root: Path, path: str) -> set[str]:
        if path not in repository_map.files:
            return set()
        counts = _term_counts(repository_map, root, path)
        metadata = _document_metadata(repository_map, path)
        self.documents[path] = {
            **metadata,
            "term_counts": dict(sorted(counts.items())),
        }
        changed_terms = set(counts)
        for term, count in counts.items():
            self.postings.setdefault(term, {})[path] = int(count)
        return changed_terms

    def query(
        self,
        query: str | Iterable[str],
        *,
        max_results: int = 24,
    ) -> list[dict[str, Any]]:
        raw_terms = tokenize(query if isinstance(query, str) else " ".join(str(item) for item in query))
        terms = tuple(dict.fromkeys(raw_terms))
        if not terms:
            return []
        scores: dict[str, float] = {}
        matched: dict[str, set[str]] = {}
        document_total = max(1, len(self.documents))
        for term in terms:
            posting = self.postings.get(term, {})
            document_frequency = max(1, len(posting))
            inverse_document_frequency = math.log((document_total + 1) / document_frequency) + 1.0
            for path, frequency in posting.items():
                scores[path] = scores.get(path, 0.0) + float(frequency) * inverse_document_frequency
                matched.setdefault(path, set()).add(term)
        rows: list[dict[str, Any]] = []
        for path, score in scores.items():
            document = self.documents.get(path, {})
            rows.append({
                "path": path,
                "score": round(score, 6),
                "matched_terms": sorted(matched.get(path, set())),
                "document": {
                    key: document.get(key)
                    for key in ("content_hash", "size", "is_test", "language", "symbol_ids")
                },
                "reason": "lexical_token_match",
            })
        rows.sort(key=lambda row: (-float(row["score"]), row["path"]))
        return rows[: max(0, int(max_results))]


def build_lexical_index(
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    metrics: dict[str, int] | None = None,
) -> LexicalIndex:
    current = _map_value(repository_map)
    root = _safe_root(project_root or current.project_root)
    index = LexicalIndex(
        project_root=str(root),
        repository_map_hash=current.logical_hash,
        index_revision=current.index_revision,
    )
    for path in sorted(current.files):
        index._add_document(current, root, path)
        if metrics is not None:
            metrics["documents_added"] = metrics.get("documents_added", 0) + 1
            metrics["documents_indexed"] = metrics.get("documents_indexed", 0) + 1
    if metrics is not None:
        metrics["terms_indexed"] = len(index.postings)
    return index


def incremental_lexical_update(
    lexical_index: LexicalIndex | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    changed_paths: Iterable[str | Path] = (),
    deleted_paths: Iterable[str | Path] = (),
    metrics: dict[str, int] | None = None,
) -> LexicalIndex:
    current = _map_value(repository_map)
    root = _safe_root(project_root or current.project_root)
    index = lexical_index if isinstance(lexical_index, LexicalIndex) else LexicalIndex.from_dict(lexical_index, root)
    updated = LexicalIndex.from_dict(index.to_dict(), root)
    changed_terms: set[str] = set()
    normalized_changes = {_safe_relative(root, path) for path in changed_paths}
    normalized_deletions = {_safe_relative(root, path) for path in deleted_paths}
    for path in sorted(normalized_deletions):
        if path in updated.documents:
            changed_terms.update(updated._remove_document(path))
            if metrics is not None:
                metrics["documents_removed"] = metrics.get("documents_removed", 0) + 1
    for path in sorted(normalized_changes):
        entry = current.files.get(path)
        if entry is None:
            if path in updated.documents:
                changed_terms.update(updated._remove_document(path))
                if metrics is not None:
                    metrics["documents_removed"] = metrics.get("documents_removed", 0) + 1
            continue
        if updated.documents.get(path, {}).get("content_hash") == entry.get("content_hash"):
            continue
        existed = path in updated.documents
        changed_terms.update(updated._remove_document(path))
        changed_terms.update(updated._add_document(current, root, path))
        if metrics is not None:
            key = "documents_updated" if existed else "documents_added"
            metrics[key] = metrics.get(key, 0) + 1
    updated.repository_map_hash = current.logical_hash
    updated.index_revision = current.index_revision
    if metrics is not None:
        metrics["terms_updated"] = len(changed_terms)
    return updated


def ensure_lexical_index(
    lexical_index: LexicalIndex | Mapping[str, Any] | None,
    repository_map: RepositoryMap | Mapping[str, Any],
    project_root: str | Path | None = None,
    *,
    changed_paths: Iterable[str | Path] = (),
    deleted_paths: Iterable[str | Path] = (),
    metrics: dict[str, int] | None = None,
) -> tuple[LexicalIndex, str]:
    current = _map_value(repository_map)
    if lexical_index is None:
        return build_lexical_index(current, project_root, metrics=metrics), "cold_build"
    index = lexical_index if isinstance(lexical_index, LexicalIndex) else LexicalIndex.from_dict(lexical_index, project_root or current.project_root)
    if index.is_current(current):
        return index, "current"
    if changed_paths or deleted_paths:
        return incremental_lexical_update(
            index, current, project_root,
            changed_paths=changed_paths, deleted_paths=deleted_paths, metrics=metrics,
        ), "incremental_update"
    return build_lexical_index(current, project_root, metrics=metrics), "safe_rebuild"


def lexical_index_hash(index: LexicalIndex | Mapping[str, Any]) -> str:
    current = index if isinstance(index, LexicalIndex) else LexicalIndex.from_dict(index)
    return current.logical_hash


__all__ = [
    "LEXICAL_INDEX_SCHEMA_VERSION", "MAX_LEXICAL_SOURCE_BYTES", "LexicalIndex",
    "normalize_term", "tokenize", "build_lexical_index", "incremental_lexical_update",
    "ensure_lexical_index", "lexical_index_hash",
]
