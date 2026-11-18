"""Deterministic module and GenerationUnit dependency DAG for CORE-6."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, TYPE_CHECKING

from .project_brain_refs import canonical_hash
from .project_blueprint import ModuleContract, ProjectBlueprint

if TYPE_CHECKING:  # pragma: no cover - imports are intentionally acyclic at runtime
    from .generation_units import GenerationUnit


DEPENDS_ON = "DEPENDS_ON"
IMPLEMENTS = "IMPLEMENTS"
PROVIDES_INTERFACE = "PROVIDES_INTERFACE"
CONSUMES_INTERFACE = "CONSUMES_INTERFACE"
OWNS_DATA = "OWNS_DATA"
TESTED_BY = "TESTED_BY"
EDGE_TYPES = (DEPENDS_ON, IMPLEMENTS, PROVIDES_INTERFACE, CONSUMES_INTERFACE, OWNS_DATA, TESTED_BY)

DAG_VALID = "DAG_VALID"
GENERATION_DEPENDENCY_CYCLE = "GENERATION_DEPENDENCY_CYCLE"
GENERATION_PATH_OWNERSHIP_CONFLICT = "GENERATION_PATH_OWNERSHIP_CONFLICT"
GENERATION_FORBIDDEN_DEPENDENCY = "GENERATION_FORBIDDEN_DEPENDENCY"
GENERATION_UNKNOWN_DEPENDENCY = "GENERATION_UNKNOWN_DEPENDENCY"


@dataclass(frozen=True)
class DependencyEdge:
    source: str
    target: str
    edge_type: str = DEPENDS_ON
    reason: str = ""
    required: bool = True
    metadata: tuple[tuple[str, Any], ...] = ()

    def __post_init__(self) -> None:
        if not str(self.source).strip() or not str(self.target).strip():
            raise ValueError("dependency edges require source and target")
        edge_type = str(self.edge_type or DEPENDS_ON).upper()
        if edge_type not in EDGE_TYPES:
            raise ValueError(f"unsupported dependency edge type: {edge_type}")
        object.__setattr__(self, "source", str(self.source).strip())
        object.__setattr__(self, "target", str(self.target).strip())
        object.__setattr__(self, "edge_type", edge_type)
        object.__setattr__(self, "reason", str(self.reason or ""))
        object.__setattr__(self, "metadata", tuple(sorted(((str(k), v) for k, v in self.metadata), key=lambda item: item[0])))

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "target": self.target,
            "edge_type": self.edge_type,
            "reason": self.reason,
            "required": bool(self.required),
            "metadata": {key: value for key, value in self.metadata},
        }


@dataclass(frozen=True)
class DAGValidationResult:
    valid: bool
    status: str
    cycles: tuple[tuple[str, ...], ...] = ()
    conflicts: tuple[dict[str, Any], ...] = ()
    forbidden_dependencies: tuple[dict[str, Any], ...] = ()
    unknown_dependencies: tuple[dict[str, Any], ...] = ()
    topological_order: tuple[str, ...] = ()

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "cycles": [list(cycle) for cycle in self.cycles],
            "conflicts": list(self.conflicts),
            "forbidden_dependencies": list(self.forbidden_dependencies),
            "unknown_dependencies": list(self.unknown_dependencies),
            "topological_order": list(self.topological_order),
        }


@dataclass(frozen=True)
class DependencyDAG:
    nodes: tuple[str, ...]
    edges: tuple[DependencyEdge, ...] = ()
    node_modules: tuple[tuple[str, str], ...] = ()
    node_paths: tuple[tuple[str, tuple[str, ...]], ...] = ()
    validation: DAGValidationResult | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "nodes", tuple(sorted(set(str(item) for item in self.nodes))))
        object.__setattr__(self, "edges", tuple(sorted(self.edges, key=lambda edge: (edge.source, edge.target, edge.edge_type))))
        object.__setattr__(self, "node_modules", tuple(sorted((str(k), str(v)) for k, v in self.node_modules)))
        object.__setattr__(self, "node_paths", tuple(sorted((str(k), tuple(sorted(str(p) for p in paths))) for k, paths in self.node_paths)))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def dependencies(self) -> dict[str, tuple[str, ...]]:
        # An edge source is the prerequisite and target is the dependent unit.
        result = {node: [] for node in self.nodes}
        for edge in self.edges:
            if edge.edge_type in {DEPENDS_ON, CONSUMES_INTERFACE, TESTED_BY}:
                result.setdefault(edge.target, []).append(edge.source)
        return {node: tuple(sorted(values)) for node, values in result.items()}

    def ready_set(self, completed: Iterable[str] = ()) -> tuple[str, ...]:
        done = {str(item) for item in completed}
        dependencies = self.dependencies
        return tuple(sorted(
            node for node in self.nodes
            if node not in done and all(dep in done for dep in dependencies.get(node, ()))
        ))

    def ready_units(self, completed: Iterable[str] = ()) -> tuple[str, ...]:
        return self.ready_set(completed)

    @property
    def dependency_edges(self) -> tuple[DependencyEdge, ...]:
        return self.edges

    @classmethod
    def from_value(cls, value: Any) -> "DependencyDAG":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("dependency DAG must be an object")
        edges = tuple(
            item if isinstance(item, DependencyEdge) else DependencyEdge(
                str(item.get("source", "")), str(item.get("target", "")),
                str(item.get("edge_type", DEPENDS_ON)), str(item.get("reason", "")),
                bool(item.get("required", True)), tuple((item.get("metadata", {}) or {}).items()),
            ) for item in value.get("edges", ()) or ()
        )
        node_modules = tuple((str(key), str(value)) for key, value in (value.get("node_modules", {}) or {}).items())
        node_paths = tuple((str(key), tuple(value or ())) for key, value in (value.get("node_paths", {}) or {}).items())
        validation_value = value.get("validation")
        validation = None
        if isinstance(validation_value, Mapping):
            validation = DAGValidationResult(
                bool(validation_value.get("valid", False)), str(validation_value.get("status", DAG_VALID)),
                tuple(tuple(str(item) for item in cycle) for cycle in validation_value.get("cycles", ()) or ()),
                tuple(validation_value.get("conflicts", ()) or ()),
                tuple(validation_value.get("forbidden_dependencies", ()) or ()),
                tuple(validation_value.get("unknown_dependencies", ()) or ()),
                tuple(str(item) for item in validation_value.get("topological_order", ()) or ()),
            )
        return cls(tuple(value.get("nodes", ()) or ()), edges, node_modules, node_paths, validation)

    def topological_order(self) -> tuple[str, ...]:
        if self.validation and self.validation.topological_order:
            return self.validation.topological_order
        return _topological_order(self.nodes, self.edges)

    def validate(self) -> DAGValidationResult:
        return self.validation or validate_dependency_dag(self)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "nodes": list(self.nodes),
            "edges": [edge.to_dict() for edge in self.edges],
            "node_modules": {key: value for key, value in self.node_modules},
            "node_paths": {key: list(value) for key, value in self.node_paths},
            "validation": self.validation.to_dict() if self.validation else None,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def _as_units(units: Iterable[Any]) -> tuple[Any, ...]:
    return tuple(sorted(tuple(units), key=lambda unit: str(getattr(unit, "unit_id", ""))))


def _topological_order(nodes: Iterable[str], edges: Iterable[DependencyEdge]) -> tuple[str, ...]:
    node_set = set(nodes)
    incoming = {node: set() for node in node_set}
    outgoing = {node: set() for node in node_set}
    for edge in edges:
        if edge.source in node_set and edge.target in node_set and edge.source != edge.target:
            incoming[edge.target].add(edge.source)
            outgoing[edge.source].add(edge.target)
    ready = sorted(node for node, deps in incoming.items() if not deps)
    order: list[str] = []
    while ready:
        node = ready.pop(0)
        order.append(node)
        for target in sorted(outgoing[node]):
            incoming[target].discard(node)
            if not incoming[target] and target not in order and target not in ready:
                ready.append(target)
        ready.sort()
    return tuple(order)


def _find_cycles(nodes: Iterable[str], edges: Iterable[DependencyEdge]) -> tuple[tuple[str, ...], ...]:
    adjacency: dict[str, list[str]] = {node: [] for node in nodes}
    for edge in edges:
        if edge.source in adjacency and edge.target in adjacency:
            adjacency[edge.source].append(edge.target)
    for values in adjacency.values():
        values.sort()
    visiting: set[str] = set()
    visited: set[str] = set()
    stack: list[str] = []
    cycles: set[tuple[str, ...]] = set()

    def visit(node: str) -> None:
        if node in visiting:
            if node in stack:
                cycle = tuple(stack[stack.index(node):] + [node])
                cycles.add(cycle)
            return
        if node in visited:
            return
        visiting.add(node)
        stack.append(node)
        for target in adjacency.get(node, ()):
            visit(target)
        stack.pop()
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacency):
        visit(node)
    return tuple(sorted(cycles))


def validate_dependency_dag(dag: DependencyDAG) -> DAGValidationResult:
    conflicts: list[dict[str, Any]] = []
    owners: dict[str, str] = {}
    for node, paths in dag.node_paths:
        for path in paths:
            prior = owners.get(path)
            if prior and prior != node:
                conflicts.append({"path": path, "owners": sorted({prior, node})})
            owners[path] = node
    cycles = _find_cycles(dag.nodes, dag.edges)
    status = DAG_VALID
    if conflicts:
        status = GENERATION_PATH_OWNERSHIP_CONFLICT
    elif cycles:
        status = GENERATION_DEPENDENCY_CYCLE
    order = _topological_order(dag.nodes, dag.edges)
    return DAGValidationResult(
        valid=not conflicts and not cycles,
        status=status,
        cycles=cycles,
        conflicts=tuple(conflicts),
        topological_order=order,
    )


def build_dependency_dag(
    blueprint: ProjectBlueprint | Mapping[str, Any],
    units: Iterable[Any] = (),
) -> DependencyDAG:
    current = ProjectBlueprint.from_value(blueprint)
    unit_rows = _as_units(units)
    if unit_rows:
        nodes = tuple(str(getattr(unit, "unit_id")) for unit in unit_rows)
        node_modules = {str(getattr(unit, "unit_id")): str(getattr(unit, "module_id", "")) for unit in unit_rows}
        node_paths = {
            str(getattr(unit, "unit_id")): tuple(getattr(unit, "target_paths", ()) or ())
            for unit in unit_rows
        }
        module_units: dict[str, list[str]] = {}
        for unit in unit_rows:
            module_units.setdefault(str(getattr(unit, "module_id", "")), []).append(str(getattr(unit, "unit_id")))
    else:
        nodes = tuple(contract.module_id for contract in current.module_contracts)
        node_modules = {node: node for node in nodes}
        node_paths = {contract.module_id: contract.target_paths for contract in current.module_contracts}
        module_units = {node: [node] for node in nodes}

    edges: list[DependencyEdge] = []
    contract_by_module = {contract.module_id: contract for contract in current.module_contracts}
    for unit in unit_rows:
        unit_id = str(getattr(unit, "unit_id"))
        module_id = str(getattr(unit, "module_id", ""))
        dependencies = tuple(str(item) for item in (getattr(unit, "dependencies", ()) or ()))
        for dependency in dependencies:
            targets = [dependency] if dependency in nodes else module_units.get(dependency, [])
            for source in targets:
                if source != unit_id:
                    edges.append(DependencyEdge(source, unit_id, DEPENDS_ON, reason="unit dependency"))
        contract = contract_by_module.get(module_id)
        if contract:
            for dependency in contract.dependencies:
                targets = [dependency] if dependency in nodes else module_units.get(dependency, [])
                for source in targets:
                    if source != unit_id:
                        edges.append(DependencyEdge(source, unit_id, DEPENDS_ON, reason="contract dependency"))
    # Contract/interface/schema units are foundations.  When a module declares
    # several units, make that ordering explicit even if the caller omitted a
    # redundant dependency edge.  This is local to a module and therefore does
    # not turn the plan into an all-project serialization barrier.
    by_module: dict[str, list[Any]] = {}
    for unit in unit_rows:
        by_module.setdefault(str(getattr(unit, "module_id", "")), []).append(unit)
    foundation_types = {"INTERFACE_UNIT", "SCHEMA_UNIT", "API_BOUNDARY_UNIT"}
    for module_units_for_module in by_module.values():
        foundations = [unit for unit in module_units_for_module if str(getattr(unit, "unit_type", "")) in foundation_types]
        implementations = [unit for unit in module_units_for_module if str(getattr(unit, "unit_type", "")) not in foundation_types]
        for foundation in foundations:
            for implementation in implementations:
                if str(getattr(foundation, "unit_id")) != str(getattr(implementation, "unit_id")):
                    edges.append(DependencyEdge(str(getattr(foundation, "unit_id")), str(getattr(implementation, "unit_id")), DEPENDS_ON, reason="contract/interface foundation"))
    if not unit_rows:
        for contract in current.module_contracts:
            for dependency in contract.dependencies:
                if dependency in nodes and dependency != contract.module_id:
                    edges.append(DependencyEdge(dependency, contract.module_id, DEPENDS_ON, reason="contract dependency"))
    unique = {(edge.source, edge.target, edge.edge_type): edge for edge in edges}
    dag = DependencyDAG(tuple(nodes), tuple(unique.values()), tuple(node_modules.items()), tuple(node_paths.items()))
    validation = validate_dependency_dag(dag)

    # Add deterministic forbidden/unknown diagnostics without changing graph edges.
    forbidden: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for contract in current.module_contracts:
        known_modules = set(contract_by_module)
        for dep in contract.dependencies:
            if dep not in known_modules and dep not in module_units:
                unknown.append({"module_id": contract.module_id, "dependency": dep})
        for dep in contract.forbidden_dependencies:
            if dep in contract.dependencies:
                forbidden.append({"module_id": contract.module_id, "dependency": dep})
    known_nodes = set(nodes) | set(module_units)
    for unit in unit_rows:
        for dependency in tuple(str(item) for item in (getattr(unit, "dependencies", ()) or ())):
            if dependency not in known_nodes:
                unknown.append({"unit_id": str(getattr(unit, "unit_id", "")), "dependency": dependency})
    if forbidden:
        validation = DAGValidationResult(
            False, GENERATION_FORBIDDEN_DEPENDENCY, validation.cycles, validation.conflicts,
            tuple(forbidden), validation.unknown_dependencies, validation.topological_order,
        )
    elif unknown:
        validation = DAGValidationResult(
            False, GENERATION_UNKNOWN_DEPENDENCY, validation.cycles, validation.conflicts,
            validation.forbidden_dependencies, tuple(unknown), validation.topological_order,
        )
    return DependencyDAG(dag.nodes, dag.edges, dag.node_modules, dag.node_paths, validation)


def topological_sort_units(dag: DependencyDAG) -> tuple[str, ...]:
    return dag.topological_order()


def ready_set(dag: DependencyDAG, completed: Iterable[str] = ()) -> tuple[str, ...]:
    return dag.ready_set(completed)


# Name used by some callers that prefer the fully qualified concept.
GenerationDependencyDAG = DependencyDAG


__all__ = [
    "DEPENDS_ON", "IMPLEMENTS", "PROVIDES_INTERFACE", "CONSUMES_INTERFACE", "OWNS_DATA", "TESTED_BY",
    "EDGE_TYPES", "DAG_VALID", "GENERATION_DEPENDENCY_CYCLE", "GENERATION_PATH_OWNERSHIP_CONFLICT",
    "GENERATION_FORBIDDEN_DEPENDENCY", "GENERATION_UNKNOWN_DEPENDENCY", "DependencyEdge",
    "DAGValidationResult", "DependencyDAG", "GenerationDependencyDAG", "build_dependency_dag",
    "validate_dependency_dag", "topological_sort_units", "ready_set",
]
