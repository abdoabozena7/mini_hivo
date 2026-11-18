"""Bounded change-impact and change-island analysis for CORE-6 maintenance."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .project_blueprint import ProjectBlueprint
from .project_brain_refs import canonical_hash, normalize_relative_path
from .repository_map import RepositoryMap


CHANGE_PRIVATE = "PRIVATE_IMPLEMENTATION_CHANGE"
CHANGE_PUBLIC_CONTRACT = "PUBLIC_CONTRACT_CHANGE"
CHANGE_SCHEMA = "SCHEMA_CHANGE"
IMPACT_BUDGET_REACHED = "IMPACT_BUDGET_REACHED"
LARGE_IMPACT_CHANGE = "LARGE_IMPACT_CHANGE"
DIRECT_IMPACT = "DIRECT_IMPACT"
TRANSITIVE_IMPACT = "TRANSITIVE_IMPACT"
TEST_IMPACT = "TEST_IMPACT"
CONTRACT_IMPACT = "CONTRACT_IMPACT"


@dataclass(frozen=True)
class ChangeImpact:
    change_id: str
    changed_paths: tuple[str, ...]
    changed_symbols: tuple[str, ...] = ()
    change_kind: str = CHANGE_PRIVATE
    status: str = "IMPACT_ANALYZED"
    changed_contracts: tuple[str, ...] = ()
    direct_paths: tuple[str, ...] = ()
    transitive_paths: tuple[str, ...] = ()
    affected_units: tuple[str, ...] = ()
    affected_consumers: tuple[str, ...] = ()
    affected_tests: tuple[str, ...] = ()
    affected_brain_references: tuple[str, ...] = ()
    graph_depth: int = 0
    max_depth: int = 2
    max_nodes: int = 24
    max_files: int = 24
    budget_reached: bool = False
    unresolved: tuple[dict[str, Any], ...] = ()
    evidence: tuple[dict[str, Any], ...] = ()

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "change_id": self.change_id,
            "changed_paths": list(self.changed_paths),
            "changed_symbols": list(self.changed_symbols),
            "change_kind": self.change_kind,
            "status": self.status,
            "changed_contracts": list(self.changed_contracts),
            "direct_paths": list(self.direct_paths),
            "transitive_paths": list(self.transitive_paths),
            "affected_units": list(self.affected_units),
            "affected_consumers": list(self.affected_consumers),
            "affected_tests": list(self.affected_tests),
            "affected_brain_references": list(self.affected_brain_references),
            "graph_depth": self.graph_depth,
            "max_depth": self.max_depth,
            "max_nodes": self.max_nodes,
            "max_files": self.max_files,
            "budget_reached": self.budget_reached,
            "unresolved": list(self.unresolved),
            "evidence": list(self.evidence),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class ChangeIsland:
    island_id: str
    root_paths: tuple[str, ...]
    affected_paths: tuple[str, ...]
    affected_units: tuple[str, ...] = ()
    required_contracts: tuple[str, ...] = ()
    required_tests: tuple[str, ...] = ()
    regeneration_allowed: bool = True
    reason: str = "bounded change island"
    authority_labels: tuple[tuple[str, str], ...] = ()
    dnt_boundaries: tuple[str, ...] = ()

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "island_id": self.island_id,
            "root_paths": list(self.root_paths),
            "affected_paths": list(self.affected_paths),
            "affected_units": list(self.affected_units),
            "required_contracts": list(self.required_contracts),
            "required_tests": list(self.required_tests),
            "regeneration_allowed": self.regeneration_allowed,
            "reason": self.reason,
            "authority_labels": {key: value for key, value in self.authority_labels},
            "dnt_boundaries": list(self.dnt_boundaries),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def _normalized_paths(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({normalize_relative_path(str(item)) for item in values if str(item).strip()}))


def _reverse_edges(repository_map: RepositoryMap) -> dict[str, set[str]]:
    reverse: dict[str, set[str]] = {}
    for edge in repository_map.edges:
        source = str(edge.get("source", ""))
        target = str(edge.get("target", ""))
        if source and target:
            reverse.setdefault(target, set()).add(source)
            reverse.setdefault(source, set())
    return reverse


def analyze_change_impact(
    repository_map: RepositoryMap | Mapping[str, Any],
    changed_paths: Iterable[str] = (),
    *,
    changed_symbols: Iterable[str] = (),
    blueprint: ProjectBlueprint | Mapping[str, Any] | None = None,
    change_kind: str = CHANGE_PRIVATE,
    public_contract_changed: bool = False,
    max_depth: int = 2,
    max_nodes: int = 24,
    max_files: int = 24,
) -> ChangeImpact:
    current = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)
    roots = _normalized_paths(changed_paths)
    symbols = tuple(sorted(set(str(item) for item in changed_symbols if str(item).strip())))
    kind = CHANGE_PUBLIC_CONTRACT if public_contract_changed else str(change_kind or CHANGE_PRIVATE).upper()
    reverse = _reverse_edges(current)
    queue: list[tuple[str, int]] = [(path, 0) for path in roots]
    seen: set[str] = set(roots)
    direct: set[str] = set(roots)
    evidence: list[dict[str, Any]] = []
    budget_reached = False
    while queue:
        node, depth = queue.pop(0)
        if depth >= max(0, int(max_depth)):
            continue
        if kind == CHANGE_PRIVATE and depth >= 1:
            # Private implementation changes deliberately remain local by default.
            continue
        for neighbor in sorted(reverse.get(node, ())):
            if neighbor in seen:
                continue
            if len(seen) >= max(1, int(max_nodes)):
                budget_reached = True
                break
            seen.add(neighbor)
            queue.append((neighbor, depth + 1))
            evidence.append({"from": node, "to": neighbor, "depth": depth + 1, "reason": "reverse_dependency"})
        if budget_reached:
            break
    paths = sorted(path for path in seen if "/" in path or path in current.files)
    if len(paths) > max(1, int(max_files)):
        budget_reached = True
        unresolved = tuple({"path": path, "reason": "impact_file_budget"} for path in paths[max_files:])
        paths = paths[:max_files]
    else:
        unresolved = ()
    tests: set[str] = set()
    consumers: set[str] = set()
    for path in paths:
        entry = current.files.get(path, {})
        tests.update(str(item) for item in entry.get("known_tests", []) or [])
        if path not in roots:
            consumers.add(path)
    units: set[str] = set()
    contracts: list[str] = []
    if blueprint is not None:
        current_blueprint = ProjectBlueprint.from_value(blueprint)
        for contract in current_blueprint.module_contracts:
            if any(path in paths for path in contract.target_paths):
                units.add(contract.module_id)
                contracts.append(contract.module_id)
            if kind == CHANGE_PUBLIC_CONTRACT and any(dep in contracts for dep in contract.dependencies):
                units.add(contract.module_id)
    change_id = "CHANGE-" + canonical_hash({"paths": roots, "symbols": symbols, "kind": kind})[:20]
    status = LARGE_IMPACT_CHANGE if budget_reached else "IMPACT_ANALYZED"
    changed_contracts: set[str] = set()
    if blueprint is not None:
        current_blueprint = ProjectBlueprint.from_value(blueprint)
        for contract in current_blueprint.module_contracts:
            if any(path in roots for path in contract.target_paths):
                changed_contracts.add(contract.module_id)
    return ChangeImpact(
        change_id=change_id,
        changed_paths=roots,
        changed_symbols=symbols,
        change_kind=kind,
        status=status,
        changed_contracts=tuple(sorted(changed_contracts)),
        direct_paths=tuple(sorted(direct)),
        transitive_paths=tuple(paths),
        affected_units=tuple(sorted(units)),
        affected_consumers=tuple(sorted(consumers)),
        affected_tests=tuple(sorted(tests))[:max(0, int(max_files))],
        affected_brain_references=tuple(),
        graph_depth=max((int(item.get("depth", 0)) for item in evidence), default=0),
        max_depth=max(0, int(max_depth)),
        max_nodes=max(1, int(max_nodes)),
        max_files=max(1, int(max_files)),
        budget_reached=budget_reached,
        unresolved=unresolved,
        evidence=tuple(evidence),
    )


def build_change_island(
    impact: ChangeImpact,
    *,
    blueprint: ProjectBlueprint | Mapping[str, Any] | None = None,
    island_id: str = "",
) -> ChangeIsland:
    current = ProjectBlueprint.from_value(blueprint) if blueprint is not None else None
    contracts: set[str] = set(impact.affected_units)
    tests: set[str] = set(impact.affected_tests)
    if current is not None:
        for contract in current.module_contracts:
            if contract.module_id in contracts:
                tests.update(contract.test_obligations)
    return ChangeIsland(
        island_id=island_id or "ISLAND-" + impact.canonical_hash[:20],
        root_paths=impact.changed_paths,
        affected_paths=impact.transitive_paths,
        affected_units=tuple(sorted(contracts)),
        required_contracts=tuple(sorted(contracts)),
        required_tests=tuple(sorted(tests)),
        regeneration_allowed=True,
        reason="bounded impact analysis; unrelated units are not regenerated",
        authority_labels=tuple((path, "READ_ONLY_SUPPORT") for path in impact.transitive_paths),
        dnt_boundaries=tuple(),
    )


def detect_contract_drift(
    blueprint: ProjectBlueprint | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    current = ProjectBlueprint.from_value(blueprint)
    repo = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)
    drift: list[dict[str, Any]] = []
    for contract in current.module_contracts:
        for path in contract.target_paths:
            if path not in repo.files:
                drift.append({"module_id": contract.module_id, "path": path, "status": "MISSING_TARGET"})
    return tuple(drift)


def detect_interface_drift(
    blueprint: ProjectBlueprint | Mapping[str, Any],
    repository_map: RepositoryMap | Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Compare declared public interface names with current map metadata."""
    current = ProjectBlueprint.from_value(blueprint)
    repo = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map)
    drift: list[dict[str, Any]] = []
    for contract in current.module_contracts:
        for path in contract.target_paths:
            entry = repo.files.get(path)
            if not entry:
                continue
            exports = {str(item) for item in entry.get("exports", []) or []}
            symbols = {
                str(row.get("qualified_name", "")).split(".")[-1]
                for row in repo.symbols.values()
                if row.get("path") == path
            }
            available = exports | symbols
            missing = sorted(interface for interface in contract.public_interfaces if interface not in available)
            if missing:
                drift.append({"module_id": contract.module_id, "path": path, "missing_interfaces": missing, "status": "INTERFACE_DRIFT"})
    return tuple(drift)


compute_change_impact = analyze_change_impact
contract_drift = detect_contract_drift
interface_drift = detect_interface_drift
GenerationImpactSet = ChangeImpact


__all__ = [
    "CHANGE_PRIVATE", "CHANGE_PUBLIC_CONTRACT", "CHANGE_SCHEMA", "IMPACT_BUDGET_REACHED",
    "LARGE_IMPACT_CHANGE", "DIRECT_IMPACT", "TRANSITIVE_IMPACT", "TEST_IMPACT", "CONTRACT_IMPACT",
    "ChangeImpact", "GenerationImpactSet", "ChangeIsland", "analyze_change_impact", "compute_change_impact", "build_change_island",
    "detect_contract_drift", "detect_interface_drift", "contract_drift", "interface_drift",
]
