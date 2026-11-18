"""A bounded, provenance-backed semantic model for one HIVO project.

The model is deliberately small.  It stores atomic repository facts and their
source fingerprints; it does not store prompts, worker reasoning, or natural
language project summaries.  The semantic evidence resolver is the authority
for discovering facts.  This module only provides a shared, invalidatable
store and a compact neighborhood projection.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping


WORLD_MODEL_SCHEMA_VERSION = "HIVO-PROJECT-WORLD-MODEL-V1"

VERIFIED = "VERIFIED"
PARTIAL = "PARTIAL"
CONFLICTING = "CONFLICTING"
STALE = "STALE"
SEMANTIC_STATES = (VERIFIED, PARTIAL, CONFLICTING, STALE)

# Atomic relation names.  They intentionally describe repository structure,
# not an LLM's interpretation of it.
DEFINED_IN = "DEFINED_IN"
CALLS = "CALLS"
IMPORTS = "IMPORTS"
EXPORTS = "EXPORTS"
RETURNS_TYPE = "RETURNS_TYPE"
IMPLEMENTS_CONTRACT = "IMPLEMENTS_CONTRACT"
EXPORTED_BY = "EXPORTED_BY"
TESTED_BY = "TESTED_BY"
TEST_ASSERTS_BEHAVIOR_OF = "TEST_ASSERTS_BEHAVIOR_OF"
READS_FIELD = "READS_FIELD"
DECLARES_FIELD = "DECLARES_FIELD"
DECLARES_TYPE = "DECLARES_TYPE"
DEPENDS_ON = "DEPENDS_ON"
READS_CONFIG = "READS_CONFIG"
TRANSITIONS = "TRANSITIONS"
HAS_INVARIANT = "HAS_INVARIANT"
SIBLING_OF = "SIBLING_OF"
EXPECTS_RETURN_SHAPE = "EXPECTS_RETURN_SHAPE"
MODULE_CONTAINS = "MODULE_CONTAINS"

RELATION_TYPES = (
    DEFINED_IN,
    CALLS,
    IMPORTS,
    EXPORTS,
    RETURNS_TYPE,
    IMPLEMENTS_CONTRACT,
    EXPORTED_BY,
    TESTED_BY,
    TEST_ASSERTS_BEHAVIOR_OF,
    READS_FIELD,
    DECLARES_FIELD,
    DECLARES_TYPE,
    DEPENDS_ON,
    READS_CONFIG,
    TRANSITIONS,
    HAS_INVARIANT,
    SIBLING_OF,
    EXPECTS_RETURN_SHAPE,
    MODULE_CONTAINS,
)

# These limits are local to the shared model and its projection.  The
# ContextSufficiencyGate still owns the Worker evidence budget.
MAX_WORLD_MODEL_FACTS = 256
MAX_WORLD_MODEL_PROVENANCE = 4
MAX_WORLD_MODEL_HOPS = 2
MAX_WORLD_MODEL_FACTS_PER_PROJECTION = 12
MAX_WORLD_MODEL_PROJECTION_FACTS = 4
MAX_WORLD_MODEL_REVALIDATION_TARGETS = 6
MAX_WORLD_MODEL_SOURCE_BYTES = 8_000_000
MAX_WORLD_MODEL_EXCERPT_CHARS = 650

_AUTHORITY_SCORES = {"HIGH": 100, "MEDIUM": 60, "LOW": 20}
_SINGLE_VALUED_RELATIONS = frozenset({
    RETURNS_TYPE, IMPLEMENTS_CONTRACT, EXPECTS_RETURN_SHAPE, TRANSITIONS,
})
_RELATION_ALIASES = {
    "defined": DEFINED_IN,
    "defined_in": DEFINED_IN,
    "definition": DEFINED_IN,
    "calls": CALLS,
    "call": CALLS,
    "imports": IMPORTS,
    "import": IMPORTS,
    "exports": EXPORTS,
    "export": EXPORTS,
    "returns": RETURNS_TYPE,
    "returns_type": RETURNS_TYPE,
    "implements": IMPLEMENTS_CONTRACT,
    "implements_contract": IMPLEMENTS_CONTRACT,
    "exported_by": EXPORTED_BY,
    "tested_by": TESTED_BY,
    "test_asserts_behavior_of": TEST_ASSERTS_BEHAVIOR_OF,
    "asserts_behavior_of": TEST_ASSERTS_BEHAVIOR_OF,
    "reads_field": READS_FIELD,
    "declares_field": DECLARES_FIELD,
    "declares_type": DECLARES_TYPE,
    "depends_on": DEPENDS_ON,
    "dependency": DEPENDS_ON,
    "reads_config": READS_CONFIG,
    "transitions": TRANSITIONS,
    "state_transition": TRANSITIONS,
    "has_invariant": HAS_INVARIANT,
    "invariant": HAS_INVARIANT,
    "sibling_of": SIBLING_OF,
    "expects_return_shape": EXPECTS_RETURN_SHAPE,
    "module_contains": MODULE_CONTAINS,
}
_RELATION_ALIASES.update({item.casefold(): item for item in RELATION_TYPES})


def _clean(value: Any, limit: int = 300) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _normalise_relation(value: Any) -> str:
    raw = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().casefold()).strip("_")
    return _RELATION_ALIASES.get(raw, str(value or "").strip().upper())


def _normalise_state(value: Any) -> str:
    state = str(value or VERIFIED).strip().upper()
    return state if state in SEMANTIC_STATES else PARTIAL


def _source_identity_parts(value: Any) -> tuple[str, str]:
    """Split ``relative/path.py:line`` without confusing Windows drives."""
    text = str(value or "").replace("\\", "/").strip()
    match = re.match(r"^(.*?)(?::(\d+)(?:-(\d+))?)?$", text)
    if not match:
        return text, ""
    path, first, last = match.groups()
    if first:
        return path, f"line {first}" + (f"-{last}" if last else "")
    return path, ""


def _stable_project_identity(root: Path, project_id: Any = None) -> str:
    root_key = str(root).casefold()
    digest = hashlib.sha256(root_key.encode("utf-8")).hexdigest()[:24]
    prefix = _clean(project_id, 100) if project_id else "workspace"
    return f"{prefix}:{digest}"


def _fingerprint(path: Path) -> str | None:
    try:
        if not path.is_file():
            return None
        digest = hashlib.sha256()
        remaining = MAX_WORLD_MODEL_SOURCE_BYTES
        with path.open("rb") as handle:
            while remaining > 0:
                block = handle.read(min(1024 * 1024, remaining))
                if not block:
                    break
                digest.update(block)
                remaining -= len(block)
        if remaining == 0:
            # Large files are not valid provenance sources for this small
            # model.  They remain available to the ordinary resolver.
            return None
        return digest.hexdigest()
    except OSError:
        return None


def _fact_identifier(project_identity: str, subject: str, relation: str, object_value: str) -> str:
    payload = "|".join((project_identity, subject.casefold(), relation, object_value.casefold()))
    return "WM-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:20].upper()


def _canonical_kind(value: Any) -> str:
    raw = re.sub(r"[^a-z0-9_]+", "_", str(value or "").strip().casefold()).strip("_")
    aliases = {
        "contract": "CONTRACT",
        "authoritative_contract": "CONTRACT",
        "interface": "CONTRACT",
        "caller": "CALLER_EXPECTATION",
        "callers": "CALLER_EXPECTATION",
        "caller_expectation": "CALLER_EXPECTATION",
        "consumers": "CALLER_EXPECTATION",
        "return_expectation": "CALLER_EXPECTATION",
        "callee_dependency": "CALLEE_DEPENDENCY",
        "tests": "TEST_EXPECTATION",
        "test_expectation": "TEST_EXPECTATION",
        "type_or_schema": "TYPE_OR_SCHEMA",
        "schema": "TYPE_OR_SCHEMA",
        "state_invariant": "STATE_INVARIANT",
        "invariant": "STATE_INVARIANT",
        "state_transition": "STATE_TRANSITION",
        "symbol_definition": "SYMBOL_DEFINITION",
        "definition": "SYMBOL_DEFINITION",
        "sibling_implementation": "SIBLING_IMPLEMENTATION",
        "export_or_public_surface": "EXPORT_OR_PUBLIC_SURFACE",
        "configuration_dependency": "CONFIGURATION_DEPENDENCY",
    }
    return aliases.get(raw, raw.upper())


@dataclass
class ProjectWorldFact:
    fact_id: str
    project_identity: str
    subject: str
    relation: str
    object: str
    state: str
    provenance: list[dict[str, Any]] = field(default_factory=list)
    authority_tier: str = "MEDIUM"
    authority_score: int = 60
    semantic_kinds: list[str] = field(default_factory=list)
    source_fingerprints: dict[str, str] = field(default_factory=dict)
    prior_state: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "project_identity": self.project_identity,
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "state": self.state,
            "provenance": [dict(item) for item in self.provenance[:MAX_WORLD_MODEL_PROVENANCE]],
            "authority_tier": self.authority_tier,
            "authority_score": self.authority_score,
            "semantic_kinds": list(self.semantic_kinds),
            "source_fingerprints": dict(self.source_fingerprints),
        }


class ProjectWorldModel:
    """One bounded semantic memory shared by Workers in one project/run."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        project_id: str | None = None,
        repository_map: Any = None,
        max_facts: int = MAX_WORLD_MODEL_FACTS,
    ) -> None:
        self.project_root = Path(project_root).expanduser().resolve()
        if not self.project_root.is_dir():
            raise ValueError(f"project root is not a directory: {project_root}")
        self.project_id = _clean(project_id, 100) if project_id else None
        self.project_identity = _stable_project_identity(self.project_root, project_id)
        self.repository_map = repository_map if self._map_belongs_to_root(repository_map) else None
        self.max_facts = max(1, min(MAX_WORLD_MODEL_FACTS, int(max_facts)))
        self._facts: dict[str, ProjectWorldFact] = {}
        self.modules: dict[str, dict[str, Any]] = {}
        self.symbols: dict[str, dict[str, Any]] = {}
        self._seeded_map_revision = ""
        self.stats: dict[str, int] = {
            "facts_stored": 0,
            "facts_reused": 0,
            "facts_invalidated": 0,
            "facts_stale": 0,
            "facts_revalidated": 0,
            "facts_rejected": 0,
            "conflicts": 0,
            "projections": 0,
            "projection_facts": 0,
        }
        self._seed_from_repository_map(self.repository_map)

    @property
    def facts(self) -> list[ProjectWorldFact]:
        return list(self._facts.values())

    @property
    def fact_count(self) -> int:
        return len(self._facts)

    def matches_project(self, project_root: str | Path, project_id: Any = None) -> bool:
        """Check both workspace root and optional caller-supplied project id."""
        try:
            root = Path(project_root).expanduser().resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            return False
        return self.project_identity == _stable_project_identity(root, project_id)

    def attach_repository_map(self, repository_map: Any) -> None:
        if repository_map is not None and not self._map_belongs_to_root(repository_map):
            return
        if repository_map is not None:
            old_files = self._map_value("files", {})
            new_files = (
                repository_map.get("files", {})
                if isinstance(repository_map, Mapping)
                else getattr(repository_map, "files", {})
            )
            if isinstance(old_files, Mapping) and isinstance(new_files, Mapping):
                changed = []
                for path in set(old_files) | set(new_files):
                    old_hash = (old_files.get(path) or {}).get("content_hash") if isinstance(old_files.get(path), Mapping) else None
                    new_hash = (new_files.get(path) or {}).get("content_hash") if isinstance(new_files.get(path), Mapping) else None
                    if old_hash != new_hash:
                        changed.append(path)
                self.invalidate_paths(changed)
            self.repository_map = repository_map
            self._seed_from_repository_map(repository_map)

    def _map_belongs_to_root(self, repository_map: Any) -> bool:
        """Reject a concrete map from another workspace before seeding it."""
        if repository_map is None:
            return True
        raw_root = (
            repository_map.get("project_root")
            if isinstance(repository_map, Mapping)
            else getattr(repository_map, "project_root", None)
        )
        if not raw_root:
            # RepositoryMap.to_dict intentionally omits its absolute root;
            # relative metadata remains safe because source fingerprints are
            # checked against this model's canonical project root.
            return True
        try:
            return Path(raw_root).expanduser().resolve() == self.project_root
        except (OSError, RuntimeError, TypeError, ValueError):
            return False

    def _map_value(self, key: str, default: Any = None) -> Any:
        current = self.repository_map
        if isinstance(current, Mapping):
            return current.get(key, default)
        return getattr(current, key, default)

    def _seed_from_repository_map(self, repository_map: Any) -> None:
        """Import only deterministic map metadata; source bodies stay out."""
        if repository_map is None:
            return
        revision = str(
            repository_map.get("index_revision", "")
            if isinstance(repository_map, Mapping)
            else getattr(repository_map, "index_revision", "")
        )
        if revision and revision == self._seeded_map_revision:
            return
        files = self._map_value("files", {})
        symbols = self._map_value("symbols", {})
        if not isinstance(files, Mapping):
            return
        if not revision:
            revision = hashlib.sha256(json.dumps(
                sorted(
                    (str(path), str((entry or {}).get("content_hash", "")))
                    for path, entry in files.items()
                    if isinstance(entry, Mapping)
                ), sort_keys=True,
            ).encode("utf-8")).hexdigest()
        current_paths = {str(path).replace("\\", "/") for path in files}
        self.modules = {
            path: value for path, value in self.modules.items() if path in current_paths
        }
        if isinstance(symbols, Mapping):
            current_symbol_ids = {str(key) for key in symbols}
            self.symbols = {
                key: value for key, value in self.symbols.items() if key in current_symbol_ids
            }
        name_counts: dict[str, int] = {}
        if isinstance(symbols, Mapping):
            for row in symbols.values():
                if isinstance(row, Mapping) and row.get("qualified_name"):
                    name_counts[str(row["qualified_name"]).casefold()] = name_counts.get(
                        str(row["qualified_name"]).casefold(), 0
                    ) + 1
        for path, entry in files.items():
            relative = str(path).replace("\\", "/")
            if not isinstance(entry, Mapping):
                continue
            self.modules[relative] = {
                "module": str(entry.get("module_identity") or Path(relative).stem),
                "path": relative,
                "exports": [str(item) for item in list(entry.get("exports", []) or [])[:16]],
            }
            source = {
                "path": relative,
                "location": "file metadata",
                "evidence_kind": "repository_map",
                "source_hash": entry.get("content_hash"),
                "excerpt": "repository map metadata for " + relative,
            }
            for export in list(entry.get("exports", []) or [])[:16]:
                self.add_fact(relative, EXPORTS, str(export), source,
                              authority_tier="HIGH", authority_score=100,
                              semantic_kind="EXPORT_OR_PUBLIC_SURFACE")
                self.add_fact(str(export), EXPORTED_BY, relative, source,
                              authority_tier="HIGH", authority_score=100,
                              semantic_kind="EXPORT_OR_PUBLIC_SURFACE")
            for imported in list(entry.get("imports", []) or [])[:16]:
                if isinstance(imported, Mapping) and imported.get("resolved_path"):
                    self.add_fact(relative, IMPORTS, str(imported["resolved_path"]), source,
                                  authority_tier="HIGH", authority_score=100,
                                  semantic_kind="CALLEE_DEPENDENCY")
                    self.add_fact(relative, DEPENDS_ON, str(imported["resolved_path"]), source,
                                  authority_tier="HIGH", authority_score=100,
                                  semantic_kind="CALLEE_DEPENDENCY")
            for test_path in list(entry.get("known_tests", []) or [])[:8]:
                self.add_fact(relative, TESTED_BY, str(test_path), source,
                              authority_tier="HIGH", authority_score=100,
                              semantic_kind="TEST_EXPECTATION")
        if isinstance(symbols, Mapping):
            for symbol_id, row in symbols.items():
                if not isinstance(row, Mapping):
                    continue
                relative = str(row.get("path", "")).replace("\\", "/")
                name = _clean(row.get("qualified_name"), 180)
                if not relative or not name:
                    continue
                self.symbols[str(symbol_id)] = dict(row)
                subject = name if name_counts.get(name.casefold(), 0) == 1 else f"{relative}::{name}"
                source = {
                    "path": relative,
                    "location": f"line {int(row.get('start_line', 1) or 1)}",
                    "evidence_kind": "repository_map_symbol",
                    "source_hash": self.modules.get(relative, {}).get("content_hash")
                    or self._map_file_content_hash(relative),
                    "excerpt": _clean(row.get("signature"), MAX_WORLD_MODEL_EXCERPT_CHARS),
                }
                self.add_fact(subject, DEFINED_IN, relative, source,
                              authority_tier="HIGH", authority_score=100,
                              semantic_kind="SYMBOL_DEFINITION")
                module_path = relative
                self.add_fact(module_path, MODULE_CONTAINS, subject, source,
                              authority_tier="HIGH", authority_score=100,
                              semantic_kind="SYMBOL_DEFINITION")
        self._seeded_map_revision = revision or "attached"

    def _map_file_content_hash(self, relative: str) -> str | None:
        files = self._map_value("files", {})
        entry = files.get(relative, {}) if isinstance(files, Mapping) else {}
        return entry.get("content_hash") if isinstance(entry, Mapping) else None

    def _relative_path(self, raw: Any) -> str | None:
        text = str(raw or "").strip()
        if not text:
            return None
        candidate = Path(text)
        if not candidate.is_absolute():
            candidate = self.project_root / text
        try:
            return candidate.resolve().relative_to(self.project_root).as_posix()
        except (OSError, ValueError):
            return None

    def _provenance_path(self, item: Mapping[str, Any]) -> tuple[str | None, str]:
        explicit = item.get("path") or item.get("file")
        location = _clean(item.get("location") or item.get("line") or "", 80)
        if explicit:
            path, parsed_location = _source_identity_parts(explicit)
            return self._relative_path(path), location or parsed_location
        source = item.get("source_identity") or item.get("source") or item.get("source_path")
        path, parsed_location = _source_identity_parts(source)
        return self._relative_path(path), location or parsed_location

    def _normalise_provenance(
        self,
        provenance: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None,
        *,
        requested_state: str,
    ) -> tuple[list[dict[str, Any]], dict[str, str]]:
        if isinstance(provenance, Mapping):
            raw_items = [provenance]
        else:
            raw_items = list(provenance or [])
        result: list[dict[str, Any]] = []
        fingerprints: dict[str, str] = {}
        for raw in raw_items[:MAX_WORLD_MODEL_PROVENANCE]:
            if not isinstance(raw, Mapping):
                continue
            path, parsed_location = self._provenance_path(raw)
            if not path:
                continue
            source = self.project_root / path
            current_hash = _fingerprint(source)
            supplied_hash = str(raw.get("source_hash") or raw.get("content_hash") or "")
            if requested_state in {VERIFIED, PARTIAL, CONFLICTING}:
                if current_hash is None:
                    continue
                if supplied_hash and supplied_hash != current_hash:
                    # The evidence was already stale when it was offered to
                    # the model.  It cannot establish a current fact.
                    continue
            source_hash = supplied_hash or current_hash
            if source_hash:
                fingerprints[path] = source_hash
            location = _clean(raw.get("location") or parsed_location or "", 80)
            identity = f"{path}:{location.replace('line ', '')}" if location else path
            result.append({
                "path": path,
                "location": location,
                "source_identity": identity,
                "evidence_kind": _clean(
                    raw.get("evidence_kind") or raw.get("source_kind") or raw.get("role") or "repository_evidence",
                    120,
                ),
                "evidence_id": _clean(raw.get("evidence_id") or "", 120),
                "excerpt": _clean(raw.get("excerpt") or raw.get("text") or "", MAX_WORLD_MODEL_EXCERPT_CHARS),
                "source_hash": source_hash,
            })
        return result, fingerprints

    def _current_source_hash(self, relative: str) -> str | None:
        return _fingerprint(self.project_root / relative)

    def _scope_paths(self, allowed_paths: Iterable[str | Path] | None) -> set[str] | None:
        if allowed_paths is None:
            return None
        result: set[str] = set()
        for raw in allowed_paths:
            candidate = self._relative_path(raw)
            if not candidate:
                continue
            path = self.project_root / candidate
            if path.is_dir():
                prefix = "" if candidate in {"", "."} else candidate.rstrip("/") + "/"
                result.add("dir:" + prefix.casefold())
            else:
                result.add(candidate.casefold())
        return result

    def _facts_in_scope(self, facts: Iterable[ProjectWorldFact], allowed_paths: Iterable[str | Path] | None) -> list[ProjectWorldFact]:
        scope = self._scope_paths(allowed_paths)
        if scope is None:
            return list(facts)
        return [
            fact for fact in facts
            if any(
                str(item.get("path", "")).casefold() in scope
                or any(
                    marker.startswith("dir:")
                    and str(item.get("path", "")).casefold().startswith(marker[4:])
                    for marker in scope
                )
                for item in fact.provenance
            )
        ]

    def _fact_sources_current(self, fact: ProjectWorldFact) -> bool:
        if not fact.provenance:
            return False
        for path, expected in fact.source_fingerprints.items():
            current = self._current_source_hash(path)
            if current is None or (expected and expected != current):
                return False
        return True

    def _mark_stale(self, fact: ProjectWorldFact) -> bool:
        if fact.state == STALE:
            return False
        fact.prior_state = fact.state
        fact.state = STALE
        self.stats["facts_invalidated"] += 1
        self.stats["facts_stale"] += 1
        return True

    def refresh_currentness(self) -> int:
        changed = 0
        for fact in self._facts.values():
            if fact.state in {VERIFIED, PARTIAL, CONFLICTING} and not self._fact_sources_current(fact):
                changed += int(self._mark_stale(fact))
        return changed

    def add_fact(
        self,
        subject: Any,
        relation: Any,
        object_value: Any,
        provenance: Mapping[str, Any] | Iterable[Mapping[str, Any]] | None,
        *,
        state: str = VERIFIED,
        authority_tier: str = "MEDIUM",
        authority_score: int | None = None,
        semantic_kind: str | None = None,
    ) -> ProjectWorldFact | None:
        subject_text = _clean(subject, 220)
        relation_text = _normalise_relation(relation)
        object_text = _clean(object_value, 220)
        requested_state = _normalise_state(state)
        if not subject_text or relation_text not in RELATION_TYPES or not object_text:
            self.stats["facts_rejected"] += 1
            return None
        normalised_provenance, fingerprints = self._normalise_provenance(
            provenance, requested_state=requested_state,
        )
        if not normalised_provenance:
            # No source means no project fact, including no speculative
            # PARTIAL note.  The caller can retain an unresolved resolver
            # result outside the model.
            self.stats["facts_rejected"] += 1
            return None
        if requested_state == VERIFIED and not fingerprints:
            self.stats["facts_rejected"] += 1
            return None
        tier = str(authority_tier or "MEDIUM").upper()
        if tier not in _AUTHORITY_SCORES:
            tier = "MEDIUM"
        score = int(authority_score if authority_score is not None else _AUTHORITY_SCORES[tier])
        score = max(0, min(120, score))
        semantic = _canonical_kind(semantic_kind) if semantic_kind else ""
        fact_id = _fact_identifier(self.project_identity, subject_text, relation_text, object_text)
        existing = self._facts.get(fact_id)
        if existing is not None:
            for item in normalised_provenance:
                if item not in existing.provenance:
                    existing.provenance.append(item)
            existing.provenance = existing.provenance[:MAX_WORLD_MODEL_PROVENANCE]
            existing.source_fingerprints.update(fingerprints)
            if semantic and semantic not in existing.semantic_kinds:
                existing.semantic_kinds.append(semantic)
            previous_score = existing.authority_score
            existing.authority_score = max(existing.authority_score, score)
            if score > previous_score:
                existing.authority_tier = tier
            if existing.state == STALE and requested_state == VERIFIED:
                existing.state = VERIFIED
                existing.prior_state = None
            elif existing.state != CONFLICTING and requested_state == CONFLICTING:
                existing.state = CONFLICTING
            elif existing.state == PARTIAL and requested_state == VERIFIED:
                existing.state = VERIFIED
            return existing

        fact = ProjectWorldFact(
            fact_id=fact_id,
            project_identity=self.project_identity,
            subject=subject_text,
            relation=relation_text,
            object=object_text,
            state=requested_state,
            provenance=normalised_provenance,
            authority_tier=tier,
            authority_score=score,
            semantic_kinds=[semantic] if semantic else [],
            source_fingerprints=fingerprints,
        )

        # Current, high-authority incompatible claims are both preserved as a
        # conflict.  Stale sources and low-authority lexical hints never make
        # a current fact conflicting.
        incompatible = [
            item for item in self._facts.values()
            if item.subject.casefold() == subject_text.casefold()
            and item.relation == relation_text
            and relation_text in _SINGLE_VALUED_RELATIONS
            and item.object.casefold() != object_text.casefold()
            and item.state in {VERIFIED, CONFLICTING}
            and item.authority_score >= 80
            and self._fact_sources_current(item)
            and requested_state == VERIFIED
            and score >= 80
        ]
        if incompatible:
            fact.state = CONFLICTING
            for item in incompatible:
                item.state = CONFLICTING
                item.prior_state = None
            self.stats["conflicts"] += 1
        self._facts[fact_id] = fact
        self.stats["facts_stored"] += 1
        while len(self._facts) > self.max_facts:
            removable = next(
                (key for key, item in self._facts.items() if item.state in {STALE, PARTIAL}),
                next(iter(self._facts)),
            )
            self._facts.pop(removable, None)
        return fact

    def invalidate_paths(self, changed_paths: Iterable[str | Path]) -> list[str]:
        changed: set[str] = set()
        for raw in changed_paths or []:
            relative = self._relative_path(raw)
            if relative:
                changed.add(relative.casefold())
        invalidated = []
        for fact in self._facts.values():
            sources = {str(item.get("path", "")).casefold() for item in fact.provenance}
            if sources & changed and self._mark_stale(fact):
                invalidated.append(fact.fact_id)
        return invalidated

    def restore_paths(self, restored_paths: Iterable[str | Path]) -> list[str]:
        """Re-enable only facts whose exact source fingerprint was restored."""
        restored: set[str] = set()
        for raw in restored_paths or []:
            relative = self._relative_path(raw)
            if relative:
                restored.add(relative.casefold())
        revalidated = []
        for fact in self._facts.values():
            if fact.state != STALE:
                continue
            if not restored.intersection({str(item.get("path", "")).casefold() for item in fact.provenance}):
                continue
            if self._fact_sources_current(fact):
                fact.state = fact.prior_state or VERIFIED
                fact.prior_state = None
                revalidated.append(fact.fact_id)
                self.stats["facts_revalidated"] += 1
        return revalidated

    def stale_facts_for_paths(self, changed_paths: Iterable[str | Path]) -> list[ProjectWorldFact]:
        paths = {
            relative.casefold() for raw in changed_paths or []
            if (relative := self._relative_path(raw))
        }
        return [
            fact for fact in self._facts.values()
            if fact.state == STALE
            and paths.intersection({str(item.get("path", "")).casefold() for item in fact.provenance})
        ][:MAX_WORLD_MODEL_REVALIDATION_TARGETS]

    def _entity_matches(self, fact: ProjectWorldFact, target: str) -> bool:
        target_text = str(target or "").strip().casefold()
        if not target_text:
            return False
        values = (fact.subject.casefold(), fact.object.casefold())
        if target_text in values:
            return True
        target_leaf = re.split(r"[./\\: ]+", target_text)[-1]
        return any(
            target_leaf and (
                value == target_leaf
                or value.startswith(target_leaf + ":")
                or value.startswith(target_leaf + " ")
                or value.endswith("." + target_leaf)
                or value.endswith("/" + target_leaf)
                or f"::{target_leaf}" in value
            )
            for value in values
        )

    def neighborhood(
        self,
        target: Any,
        *,
        relation_types: Iterable[str] | None = None,
        max_hops: int = MAX_WORLD_MODEL_HOPS,
        max_facts: int = MAX_WORLD_MODEL_FACTS_PER_PROJECTION,
        include_states: Iterable[str] = (VERIFIED,),
    ) -> dict[str, Any]:
        self.refresh_currentness()
        allowed_states = {_normalise_state(item) for item in include_states}
        relations = {
            _normalise_relation(item) for item in (relation_types or RELATION_TYPES)
        }
        hop_limit = max(0, min(MAX_WORLD_MODEL_HOPS, int(max_hops)))
        fact_limit = max(1, min(MAX_WORLD_MODEL_FACTS_PER_PROJECTION, int(max_facts)))
        candidates = [
            fact for fact in self._facts.values()
            if fact.state in allowed_states and fact.relation in relations
        ]
        frontier = {str(target or "").strip().casefold()}
        selected: list[tuple[int, ProjectWorldFact]] = []
        seen_ids: set[str] = set()
        for hop in range(hop_limit + 1):
            next_frontier: set[str] = set()
            for fact in candidates:
                if fact.fact_id in seen_ids or not any(
                    self._entity_matches(fact, entity) for entity in frontier
                ):
                    continue
                seen_ids.add(fact.fact_id)
                selected.append((hop, fact))
                next_frontier.update((fact.subject.casefold(), fact.object.casefold()))
            if len(selected) >= fact_limit or hop == hop_limit or not next_frontier:
                break
            frontier = next_frontier
        selected.sort(key=lambda pair: (
            pair[0], -pair[1].authority_score, pair[1].relation,
            pair[1].subject.casefold(), pair[1].object.casefold(), pair[1].fact_id,
        ))
        facts = [fact for _hop, fact in selected[:fact_limit]]
        return {
            "project_identity": self.project_identity,
            "target": _clean(target, 220),
            "facts": facts,
            "fact_dicts": [fact.to_dict() for fact in facts],
            "hops": max((hop for hop, fact in selected[:fact_limit]), default=0),
            "max_hops": hop_limit,
            "max_facts": fact_limit,
        }

    def _request_fact_selection(self, kind: str, target: str, facts: list[ProjectWorldFact]) -> list[ProjectWorldFact]:
        requirements = {
            "CONTRACT": ({RETURNS_TYPE, IMPLEMENTS_CONTRACT, DECLARES_TYPE, DECLARES_FIELD, EXPECTS_RETURN_SHAPE}, 1),
            "CALLER_EXPECTATION": ({CALLS}, 1),
            "TEST_EXPECTATION": ({TEST_ASSERTS_BEHAVIOR_OF, TESTED_BY}, 1),
            "TYPE_OR_SCHEMA": ({DECLARES_TYPE, DECLARES_FIELD, RETURNS_TYPE}, 1),
            "STATE_TRANSITION": ({TRANSITIONS}, 1),
            "STATE_INVARIANT": ({HAS_INVARIANT}, 1),
            "SYMBOL_DEFINITION": ({DEFINED_IN}, 1),
            "SIBLING_IMPLEMENTATION": ({SIBLING_OF}, 1),
            "EXPORT_OR_PUBLIC_SURFACE": ({EXPORTED_BY, EXPORTS}, 1),
            "CALLEE_DEPENDENCY": ({DEPENDS_ON, IMPORTS}, 1),
            "CONFIGURATION_DEPENDENCY": ({READS_CONFIG}, 1),
        }
        required, _minimum = requirements.get(kind, (set(), 1))
        relevant = [fact for fact in facts if self._entity_matches(fact, target)]
        if kind == "CALLER_EXPECTATION":
            calls = [fact for fact in relevant if fact.relation == CALLS]
            expectations = [fact for fact in relevant if fact.relation in {
                READS_FIELD, EXPECTS_RETURN_SHAPE, TEST_ASSERTS_BEHAVIOR_OF,
            }]
            # A call and an expectation are only a complete caller slot when
            # they describe the same consumer.  Pairing the first lexical
            # call with an unrelated caller's field access would create a
            # plausible-looking but unsupported semantic bundle.
            for call in calls:
                paired = [
                    item for item in expectations
                    if item.subject.casefold() == call.subject.casefold()
                ]
                if paired:
                    return [call, *paired[:2]][:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]
            return (calls[:1] + expectations[:2])[:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]
        selected = [fact for fact in relevant if fact.relation in required]
        if not selected and kind == "CONTRACT":
            selected = [fact for fact in relevant if fact.relation == DEFINED_IN]
        return selected[:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]

    def _conflicts_for(self, facts: Iterable[ProjectWorldFact]) -> list[dict[str, Any]]:
        groups: dict[tuple[str, str], list[ProjectWorldFact]] = {}
        for fact in facts:
            if fact.state != CONFLICTING:
                continue
            groups.setdefault((fact.subject.casefold(), fact.relation), []).append(fact)
        result = []
        for (subject, relation), rows in groups.items():
            distinct_values = {row.object.casefold() for row in rows}
            if len(distinct_values) < 2:
                continue
            result.append({
                "subject": subject,
                "relation": relation,
                "values": sorted({row.object for row in rows}),
                "fact_ids": [row.fact_id for row in rows[:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]],
                "provenance": [
                    provenance
                    for row in rows[:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]
                    for provenance in row.provenance[:1]
                ][:MAX_WORLD_MODEL_PROVENANCE],
            })
        return result[:4]

    def _evidence_item(
        self, fact: ProjectWorldFact, target: str, status: str, request_kind: str = "",
    ) -> dict[str, Any]:
        source = fact.provenance[0] if fact.provenance else {}
        identity = source.get("source_identity") or source.get("path") or "unknown-source"
        fact_text = f"{fact.subject} {fact.relation} {fact.object} (source: {identity})"
        return {
            "evidence_id": "WORLD-" + fact.fact_id.removeprefix("WM-"),
            "kind": _kind_to_gate(request_kind or "", fact, target),
            "semantic_request_kind": request_kind or (fact.semantic_kinds[0] if fact.semantic_kinds else ""),
            "target": _clean(target, 180),
            "source_identity": identity,
            "symbol": fact.subject,
            "excerpt": source.get("excerpt", "") or fact_text,
            "purpose": "verified project fact reused from the bounded World Model",
            "provenance": "PROJECT_WORLD_MODEL",
            "source_kind": source.get("evidence_kind", "repository_evidence"),
            "role": fact.relation,
            "relation": fact.relation,
            "authoritative": status == "resolved" and fact.state == VERIFIED and fact.authority_score >= 80,
            "authority_tier": fact.authority_tier,
            "authority_score": fact.authority_score,
            "relationship": fact.relation,
            "claim_key": f"{fact.subject}.{fact.relation}",
            "claim_value": fact.object,
            "facts_established": [fact_text],
            "resolution_status": status,
            "world_model_fact_id": fact.fact_id,
            "world_model_reused": True,
        }

    def resolve_request(
        self,
        request: Mapping[str, Any] | None,
        *,
        max_facts: int = MAX_WORLD_MODEL_FACTS_PER_PROJECTION,
        allowed_paths: Iterable[str | Path] | None = None,
    ) -> dict[str, Any]:
        """Return a cached bundle only when typed facts cover the request."""
        value = request if isinstance(request, Mapping) else {}
        kind = _canonical_kind(value.get("kind"))
        target = _clean(value.get("target"), 180)
        fact_limit = max(1, min(MAX_WORLD_MODEL_FACTS_PER_PROJECTION, int(max_facts)))
        neighborhood = self.neighborhood(
            target, max_hops=MAX_WORLD_MODEL_HOPS,
            max_facts=fact_limit, include_states=(VERIFIED, CONFLICTING),
        )
        facts = self._facts_in_scope(neighborhood["facts"], allowed_paths)
        # A mutation can stale one side of a prior conflict.  Once only one
        # current authoritative value remains, it is safe to re-enable that
        # value; two current incompatible values remain conflicting below.
        conflict_groups: dict[tuple[str, str], list[ProjectWorldFact]] = {}
        for fact in facts:
            if fact.state == CONFLICTING:
                conflict_groups.setdefault((fact.subject.casefold(), fact.relation), []).append(fact)
        for rows in conflict_groups.values():
            if len({row.object.casefold() for row in rows}) == 1:
                for fact in rows:
                    fact.state = VERIFIED
                    fact.prior_state = None
                    self.stats["facts_revalidated"] += 1
        conflicts = self._conflicts_for(facts)
        if conflicts:
            status = "conflicting"
            selected = [fact for fact in facts if fact.state == CONFLICTING]
        else:
            selected = self._request_fact_selection(kind, target, [fact for fact in facts if fact.state == VERIFIED])
            required = {
                "CONTRACT": {RETURNS_TYPE, IMPLEMENTS_CONTRACT, DECLARES_TYPE, DECLARES_FIELD, EXPECTS_RETURN_SHAPE},
                "CALLER_EXPECTATION": {CALLS, READS_FIELD, EXPECTS_RETURN_SHAPE, TEST_ASSERTS_BEHAVIOR_OF},
                "TEST_EXPECTATION": {TEST_ASSERTS_BEHAVIOR_OF, TESTED_BY},
                "TYPE_OR_SCHEMA": {DECLARES_TYPE, DECLARES_FIELD, RETURNS_TYPE},
                "STATE_TRANSITION": {TRANSITIONS},
                "STATE_INVARIANT": {HAS_INVARIANT},
                "SYMBOL_DEFINITION": {DEFINED_IN},
                "SIBLING_IMPLEMENTATION": {SIBLING_OF},
                "EXPORT_OR_PUBLIC_SURFACE": {EXPORTED_BY, EXPORTS},
                "CALLEE_DEPENDENCY": {DEPENDS_ON, IMPORTS},
                "CONFIGURATION_DEPENDENCY": {READS_CONFIG},
            }.get(kind, set())
            covered = {fact.relation for fact in selected}
            caller_pairs = any(
                fact.relation == CALLS
                and any(
                    other.subject.casefold() == fact.subject.casefold()
                    and other.relation in {READS_FIELD, EXPECTS_RETURN_SHAPE, TEST_ASSERTS_BEHAVIOR_OF}
                    for other in selected
                )
                for fact in selected
            )
            sufficient = (
                (kind == "CALLER_EXPECTATION" and caller_pairs)
                or (kind != "CALLER_EXPECTATION" and bool(covered & required))
            )
            status = "resolved" if sufficient else ("partial" if selected else "unresolved")
        self.stats["facts_reused"] += int(status == "resolved")
        if status == "conflicting":
            self.stats["conflicts"] += 1
        evidence = [
            self._evidence_item(fact, target, status, kind)
            for fact in selected[:fact_limit]
        ]
        facts_established = [
            item for evidence_item in evidence
            for item in evidence_item.get("facts_established", [])
        ][:MAX_WORLD_MODEL_FACTS_PER_PROJECTION]
        return {
            "request_kind": kind,
            "gate_request_kind": {
                "CONTRACT": "contract",
                "CALLER_EXPECTATION": "callers",
                "TEST_EXPECTATION": "tests",
                "TYPE_OR_SCHEMA": "schema",
                "STATE_TRANSITION": "state_transition",
                "STATE_INVARIANT": "invariant",
                "SYMBOL_DEFINITION": "definition",
                "SIBLING_IMPLEMENTATION": "sibling_implementation",
                "EXPORT_OR_PUBLIC_SURFACE": "export_or_public_surface",
                "CALLEE_DEPENDENCY": "callee_dependency",
                "CONFIGURATION_DEPENDENCY": "configuration_dependency",
            }.get(kind, "evidence"),
            "target": target,
            "resolution_status": status,
            "facts_established": facts_established,
            "evidence": evidence,
            "provenance": [
                {"fact_id": fact.fact_id, **fact.provenance[0]}
                for fact in selected[:fact_limit] if fact.provenance
            ],
            "conflicts": conflicts,
            "candidates_considered": len(facts),
            "candidate_files_considered": len({
                item.get("path") for fact in selected for item in fact.provenance if item.get("path")
            }),
            "relationship_hops": neighborhood.get("hops", 0),
            "max_relationship_hops": MAX_WORLD_MODEL_HOPS,
            "max_evidence_items": fact_limit,
            "structural_search": True,
            "fallback_used": False,
            "resolver": "PROJECT_WORLD_MODEL",
            "world_model_reused": status == "resolved",
            "world_model_status": status,
        }

    def update_from_resolution(self, resolution: Mapping[str, Any] | None) -> dict[str, Any]:
        """Persist only source-backed atomic relations from resolver output."""
        value = resolution if isinstance(resolution, Mapping) else {}
        status = str(value.get("resolution_status") or "unresolved").casefold()
        kind = _canonical_kind(value.get("request_kind"))
        target = _clean(value.get("target"), 180)
        stored: list[str] = []
        rejected = 0
        evidence = value.get("evidence") if isinstance(value.get("evidence"), list) else []
        for item in evidence:
            if not isinstance(item, Mapping):
                continue
            role = str(item.get("role") or "").casefold()
            source = {
                "source_identity": item.get("source_identity"),
                "excerpt": item.get("excerpt"),
                "evidence_id": item.get("evidence_id"),
                "evidence_kind": item.get("source_kind") or role,
                "authority_tier": item.get("authority_tier"),
            }
            item_state = CONFLICTING if status == "conflicting" else (
                VERIFIED if status == "resolved" and bool(item.get("authoritative")) else PARTIAL
            )
            specs: list[tuple[str, str, str, str]] = []
            source_subject = _clean(item.get("consumer_symbol") or item.get("source_symbol") or "", 180)
            if not source_subject:
                source_subject = _source_identity_parts(item.get("source_identity"))[0] or target
            claim = _clean(item.get("claim_value"), 220)
            if role == "symbol_definition":
                path = _source_identity_parts(item.get("source_identity"))[0]
                specs.append((target, DEFINED_IN, path or source_subject, VERIFIED))
            elif role == "implementation":
                path = _source_identity_parts(item.get("source_identity"))[0]
                specs.append((target, DEFINED_IN, path or source_subject, VERIFIED))
            elif role == "contract_declaration":
                declared_type = re.search(
                    r"declared return type\s+([A-Za-z_][A-Za-z0-9_.]*)",
                    " ".join(item.get("facts_established", []) or []),
                    re.IGNORECASE,
                )
                contract_value = claim or "declared contract"
                specs.append((target, IMPLEMENTS_CONTRACT, contract_value, item_state))
                if declared_type:
                    claim = declared_type.group(1)
                if claim:
                    specs.append((target, RETURNS_TYPE, claim, item_state))
            elif role == "type_schema":
                specs.append((target, DECLARES_TYPE, target, item_state))
                field_names = re.findall(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*:", str(item.get("excerpt") or ""))
                for field_name in field_names[:3]:
                    specs.append((target, DECLARES_FIELD, field_name, item_state))
            elif role in {"caller_expectation", "test_direct"}:
                specs.append((source_subject, CALLS, target, VERIFIED if status in {"resolved", "conflicting"} else PARTIAL))
                if role == "test_direct":
                    specs.append((target, TESTED_BY, source_subject, item_state))
                    specs.append((source_subject, TEST_ASSERTS_BEHAVIOR_OF, target, item_state))
                if claim:
                    specs.append((source_subject, EXPECTS_RETURN_SHAPE, f"{target}: {claim}", item_state))
                    field_match = re.search(r"field\s+([A-Za-z_][A-Za-z0-9_]*)", claim, re.IGNORECASE)
                    if field_match:
                        specs.append((source_subject, READS_FIELD, f"{target}:{field_match.group(1)}", item_state))
            elif role == "public_export":
                path = _source_identity_parts(item.get("source_identity"))[0]
                specs.append((target, EXPORTED_BY, path or source_subject, item_state))
            elif role == "callee_dependency":
                match = re.search(r"\b(?:calls|depends on)\s+([A-Za-z_$][A-Za-z0-9_$]*)", " ".join(item.get("facts_established", []) or []), re.IGNORECASE)
                if match:
                    specs.append((target, DEPENDS_ON, match.group(1), item_state))
            elif role == "configuration_dependency":
                specs.append((target, READS_CONFIG, claim or source_subject, item_state))
            elif role == "state_transition":
                specs.append((target, TRANSITIONS, claim or "guarded state transition", item_state))
            elif role == "state_invariant":
                specs.append((target, HAS_INVARIANT, claim or "guarded invariant", item_state))
            elif role == "sibling_implementation":
                match = re.search(r"implementation\s+([A-Za-z_$][A-Za-z0-9_$]*)", " ".join(item.get("facts_established", []) or []), re.IGNORECASE)
                if match:
                    specs.append((target, SIBLING_OF, match.group(1), item_state))
            for subject, relation, object_value, fact_state in specs:
                fact = self.add_fact(
                    subject, relation, object_value, source,
                    state=fact_state,
                    authority_tier=str(item.get("authority_tier") or ("HIGH" if item.get("authoritative") else "MEDIUM")),
                    authority_score=int(item.get("authority_score", 0) or 0) or None,
                    semantic_kind=kind,
                )
                if fact is None:
                    rejected += 1
                else:
                    stored.append(fact.fact_id)
        return {
            "stored_fact_ids": list(dict.fromkeys(stored))[:MAX_WORLD_MODEL_FACTS_PER_PROJECTION],
            "facts_stored": len(set(stored)),
            "facts_rejected": rejected,
            "resolution_status": status,
            "request_kind": kind,
            "target": target,
        }

    def projection_for_target(
        self,
        target: Any,
        *,
        max_hops: int = MAX_WORLD_MODEL_HOPS,
        max_facts: int = MAX_WORLD_MODEL_PROJECTION_FACTS,
        allowed_paths: Iterable[str | Path] | None = None,
    ) -> dict[str, Any]:
        result = self.neighborhood(
            target, max_hops=max_hops,
            max_facts=min(max_facts, MAX_WORLD_MODEL_FACTS_PER_PROJECTION),
            include_states=(VERIFIED, CONFLICTING),
        )
        scoped_facts = self._facts_in_scope(result["facts"], allowed_paths)
        self.stats["projections"] += 1
        self.stats["projection_facts"] += len(scoped_facts[:max_facts])
        return {
            "project_identity": self.project_identity,
            "target": _clean(target, 180),
            "facts": [fact.to_dict() for fact in scoped_facts[:max_facts]],
            "hops": result["hops"],
            "max_hops": result["max_hops"],
            "max_facts": result["max_facts"],
        }

    def projection_for_task(
        self,
        task_text: Any,
        *,
        max_facts: int = MAX_WORLD_MODEL_PROJECTION_FACTS,
        allowed_paths: Iterable[str | Path] | None = None,
    ) -> dict[str, Any]:
        text = str(task_text or "")
        tokens = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", text)
        candidates = []
        for token in tokens:
            if "_" in token or "$" in token or token.isupper():
                if token.casefold() not in {item.casefold() for item in candidates}:
                    candidates.append(token)
        candidates.extend(token for token in tokens if token not in candidates and len(token) > 5)
        for candidate in candidates[:12]:
            view = self.projection_for_target(
                candidate, max_facts=max_facts, allowed_paths=allowed_paths,
            )
            if view["facts"]:
                return view
        return {
            "project_identity": self.project_identity,
            "target": "",
            "facts": [],
            "hops": 0,
            "max_hops": MAX_WORLD_MODEL_HOPS,
            "max_facts": max_facts,
        }

    def evidence_for_task(
        self,
        task_text: Any,
        *,
        max_facts: int = MAX_WORLD_MODEL_PROJECTION_FACTS,
        allowed_paths: Iterable[str | Path] | None = None,
    ) -> list[dict[str, Any]]:
        """Return a complete cached semantic slot, never a raw model dump."""
        view = self.projection_for_task(
            task_text, max_facts=max_facts, allowed_paths=allowed_paths,
        )
        target = view.get("target")
        if not target:
            return []
        relation_set = {str(item.get("relation")) for item in view.get("facts", []) if isinstance(item, Mapping)}
        kinds = []
        if CALLS in relation_set and relation_set.intersection({READS_FIELD, EXPECTS_RETURN_SHAPE, TEST_ASSERTS_BEHAVIOR_OF}):
            kinds.append("CALLER_EXPECTATION")
        if relation_set.intersection({RETURNS_TYPE, IMPLEMENTS_CONTRACT, DECLARES_TYPE, DECLARES_FIELD}):
            kinds.append("CONTRACT")
        if relation_set.intersection({TEST_ASSERTS_BEHAVIOR_OF, TESTED_BY}):
            kinds.append("TEST_EXPECTATION")
        for kind in kinds:
            result = self.resolve_request(
                {"kind": kind, "target": target}, allowed_paths=allowed_paths,
            )
            if result.get("resolution_status") in {"resolved", "conflicting"}:
                return list(result.get("evidence", []) or [])[:max_facts]
        return []

    def revalidation_targets(self, changed_paths: Iterable[str | Path]) -> list[dict[str, Any]]:
        result = []
        for fact in self.stale_facts_for_paths(changed_paths):
            kind = fact.semantic_kinds[0] if fact.semantic_kinds else "SYMBOL_DEFINITION"
            target = fact.subject
            if kind == "CALLER_EXPECTATION" and fact.relation == CALLS:
                target = fact.object
            elif kind == "CALLER_EXPECTATION" and fact.relation in {READS_FIELD, EXPECTS_RETURN_SHAPE}:
                target = fact.object.split(":", 1)[0]
            elif kind == "TEST_EXPECTATION" and fact.relation == TEST_ASSERTS_BEHAVIOR_OF:
                target = fact.object
            result.append({
                "target": target,
                "relation": fact.relation,
                "semantic_kind": kind,
                "fact_id": fact.fact_id,
            })
        return result

    def snapshot(self) -> dict[str, Any]:
        self.refresh_currentness()
        return {
            "schema_version": WORLD_MODEL_SCHEMA_VERSION,
            "project_identity": self.project_identity,
            "project_root": str(self.project_root),
            "fact_count": len(self._facts),
            "facts": [fact.to_dict() for fact in list(self._facts.values())[:self.max_facts]],
            "stats": dict(self.stats),
            "bounds": {
                "max_facts": self.max_facts,
                "max_hops": MAX_WORLD_MODEL_HOPS,
                "max_projection_facts": MAX_WORLD_MODEL_FACTS_PER_PROJECTION,
            },
        }


def _kind_to_gate(request_kind: str, fact: ProjectWorldFact, target: str) -> str:
    kind = request_kind or (fact.semantic_kinds[0] if fact.semantic_kinds else "evidence")
    return {
        "CONTRACT": "contract",
        "CALLER_EXPECTATION": "callers",
        "TEST_EXPECTATION": "tests",
        "TYPE_OR_SCHEMA": "schema",
        "STATE_TRANSITION": "state_transition",
        "STATE_INVARIANT": "invariant",
        "SYMBOL_DEFINITION": "definition",
        "EXPORT_OR_PUBLIC_SURFACE": "export_or_public_surface",
        "CALLEE_DEPENDENCY": "callee_dependency",
        "CONFIGURATION_DEPENDENCY": "configuration_dependency",
    }.get(kind, "evidence")


__all__ = [
    "WORLD_MODEL_SCHEMA_VERSION", "VERIFIED", "PARTIAL", "CONFLICTING", "STALE",
    "DEFINED_IN", "CALLS", "IMPORTS", "EXPORTS", "RETURNS_TYPE", "IMPLEMENTS_CONTRACT",
    "EXPORTED_BY", "TESTED_BY", "TEST_ASSERTS_BEHAVIOR_OF", "READS_FIELD", "DECLARES_FIELD",
    "DECLARES_TYPE", "DEPENDS_ON", "READS_CONFIG", "TRANSITIONS", "HAS_INVARIANT",
    "SIBLING_OF", "EXPECTS_RETURN_SHAPE", "MODULE_CONTAINS", "RELATION_TYPES", "MAX_WORLD_MODEL_FACTS",
    "MAX_WORLD_MODEL_HOPS", "MAX_WORLD_MODEL_FACTS_PER_PROJECTION", "MAX_WORLD_MODEL_PROJECTION_FACTS",
    "MAX_WORLD_MODEL_REVALIDATION_TARGETS", "ProjectWorldFact", "ProjectWorldModel",
]
