"""Contract-first project design primitives for HIVO CORE-6.

The objects in this module describe a project before source is generated.  They
are deliberately metadata-only: a blueprint can describe contracts, paths and
invariants, but it can never contain source bodies or grant write authority.
All identities are deterministic so plans and checkpoints can be compared
without a provider or a Worker.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .project_brain_refs import canonical_hash, canonical_json, normalize_relative_path


CORE6_BLUEPRINT_SCHEMA_VERSION = "CORE-6-PROJECT-BLUEPRINT-V1"
REQUIREMENT_CATEGORIES = (
    "FUNCTIONAL", "API", "DATA", "SECURITY", "PERFORMANCE", "RELIABILITY",
    "OBSERVABILITY", "TESTABILITY", "DEPLOYMENT", "ARCHITECTURAL",
)
ARCHITECTURE_STYLES = ("MODULAR", "LAYERED", "HEXAGONAL", "SERVICE", "MONOLITH", "CUSTOM")
CONTRACT_STATUSES = ("PLANNED", "VERIFIED", "DRIFTED", "FAILED")


def _texts(values: Iterable[Any] | None, *, limit: int = 256) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if text and text not in seen:
            seen.add(text)
            result.append(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _maps(values: Iterable[Any] | None, *, limit: int = 256) -> tuple[dict[str, Any], ...]:
    result: list[dict[str, Any]] = []
    for value in values or ():
        if isinstance(value, Mapping):
            result.append({str(key): value[key] for key in sorted(value, key=str)})
        else:
            result.append({"value": str(value)})
        if len(result) >= limit:
            break
    result.sort(key=canonical_json)
    return tuple(result)


def _safe_paths(values: Iterable[Any] | None, *, limit: int = 128) -> tuple[str, ...]:
    paths: set[str] = set()
    for value in values or ():
        paths.add(normalize_relative_path(str(value)))
        if len(paths) >= limit:
            break
    return tuple(sorted(paths))


def _reject_source_bodies(value: Any, *, depth: int = 0) -> None:
    if depth > 12:
        raise ValueError("blueprint nesting is too deep")
    forbidden = {
        "source", "source_text", "body", "content", "raw_source", "full_file",
        "file_body", "repository_snapshot", "entire_file", "patch", "source_code",
    }
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold().replace("-", "_") in forbidden:
                raise ValueError("ProjectBlueprint cannot contain source bodies")
            _reject_source_bodies(item, depth=depth + 1)
    elif isinstance(value, (tuple, list, set)):
        for item in value:
            _reject_source_bodies(item, depth=depth + 1)


@dataclass(frozen=True)
class ProjectRequirement:
    requirement_id: str
    category: str
    summary: str
    acceptance_criteria: tuple[str, ...] = ()
    priority: int = 50
    module_hints: tuple[str, ...] = ()
    nonfunctional_constraints: tuple[str, ...] = ()
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        requirement_id = str(self.requirement_id or "").strip()
        category = str(self.category or "").strip().upper()
        summary = str(self.summary or "").strip()
        if not requirement_id or not summary:
            raise ValueError("requirement_id and summary are required")
        if category not in REQUIREMENT_CATEGORIES:
            raise ValueError(f"unsupported requirement category: {category}")
        object.__setattr__(self, "requirement_id", requirement_id)
        object.__setattr__(self, "category", category)
        object.__setattr__(self, "summary", summary[:4000])
        object.__setattr__(self, "acceptance_criteria", _texts(self.acceptance_criteria))
        object.__setattr__(self, "priority", max(0, min(100, int(self.priority))))
        object.__setattr__(self, "module_hints", _texts(self.module_hints))
        object.__setattr__(self, "nonfunctional_constraints", _texts(self.nonfunctional_constraints))
        object.__setattr__(self, "provenance", _texts(self.provenance))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "requirement_id": self.requirement_id,
            "category": self.category,
            "summary": self.summary,
            "acceptance_criteria": list(self.acceptance_criteria),
            "priority": self.priority,
            "module_hints": list(self.module_hints),
            "nonfunctional_constraints": list(self.nonfunctional_constraints),
            "provenance": list(self.provenance),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "ProjectRequirement":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("requirement must be an object")
        return cls(
            requirement_id=str(value.get("requirement_id", value.get("id", ""))),
            category=str(value.get("category", "FUNCTIONAL")),
            summary=str(value.get("summary", "")),
            acceptance_criteria=tuple(value.get("acceptance_criteria", value.get("acceptance", ())) or ()),
            priority=int(value.get("priority", 50)),
            module_hints=tuple(value.get("module_hints", value.get("modules", ())) or ()),
            nonfunctional_constraints=tuple(value.get("nonfunctional_constraints", ()) or ()),
            provenance=tuple(value.get("provenance", ()) or ()),
        )


@dataclass(frozen=True)
class InterfaceSchema:
    """A deterministic interface or data schema identity, not a source body."""

    schema_id: str
    name: str
    kind: str = "INTERFACE"
    input_fields: tuple[dict[str, Any], ...] = ()
    output_fields: tuple[dict[str, Any], ...] = ()
    required_fields: tuple[str, ...] = ()
    optional_fields: tuple[str, ...] = ()
    version: str = "1"
    metadata: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        schema_id = str(self.schema_id or "").strip()
        name = str(self.name or "").strip()
        if not schema_id or not name:
            raise ValueError("schema_id and name are required")
        kind = str(self.kind or "INTERFACE").strip().upper()
        if kind not in {"INTERFACE", "DATA", "EVENT", "API", "CONFIGURATION"}:
            raise ValueError(f"unsupported schema kind: {kind}")
        object.__setattr__(self, "schema_id", schema_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "input_fields", _maps(self.input_fields))
        object.__setattr__(self, "output_fields", _maps(self.output_fields))
        object.__setattr__(self, "required_fields", _texts(self.required_fields))
        object.__setattr__(self, "optional_fields", _texts(self.optional_fields))
        object.__setattr__(self, "version", str(self.version or "1").strip())
        object.__setattr__(self, "metadata", _maps(self.metadata))
        _reject_source_bodies(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def identity(self) -> str:
        return f"{self.schema_id}@{self.version}"

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_id": self.schema_id,
            "name": self.name,
            "kind": self.kind,
            "input_fields": list(self.input_fields),
            "output_fields": list(self.output_fields),
            "required_fields": list(self.required_fields),
            "optional_fields": list(self.optional_fields),
            "version": self.version,
            "metadata": list(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "InterfaceSchema":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("schema must be an object")
        return cls(
            schema_id=str(value.get("schema_id", value.get("id", ""))),
            name=str(value.get("name", "")),
            kind=str(value.get("kind", "INTERFACE")),
            input_fields=tuple(value.get("input_fields", ()) or ()),
            output_fields=tuple(value.get("output_fields", ()) or ()),
            required_fields=tuple(value.get("required_fields", ()) or ()),
            optional_fields=tuple(value.get("optional_fields", ()) or ()),
            version=str(value.get("version", "1")),
            metadata=tuple(value.get("metadata", ()) or ()),
        )


@dataclass(frozen=True)
class ModuleContract:
    module_id: str
    name: str
    responsibility: str
    public_interfaces: tuple[str, ...] = ()
    inputs: tuple[dict[str, Any], ...] = ()
    outputs: tuple[dict[str, Any], ...] = ()
    owned_state: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    forbidden_dependencies: tuple[str, ...] = ()
    invariants: tuple[str, ...] = ()
    failure_semantics: tuple[str, ...] = ()
    test_obligations: tuple[str, ...] = ()
    api_stability: str = "STABLE"
    target_paths: tuple[str, ...] = ()
    generation_status: str = "PLANNED"
    requirement_ids: tuple[str, ...] = ()
    metadata: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        module_id = str(self.module_id or "").strip()
        name = str(self.name or "").strip()
        responsibility = str(self.responsibility or "").strip()
        if not module_id or not name or not responsibility:
            raise ValueError("module_id, name and responsibility are required")
        status = str(self.generation_status or "PLANNED").upper()
        if status not in CONTRACT_STATUSES:
            raise ValueError(f"unsupported contract status: {status}")
        object.__setattr__(self, "module_id", module_id)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "responsibility", responsibility[:4000])
        object.__setattr__(self, "public_interfaces", _texts(self.public_interfaces))
        object.__setattr__(self, "inputs", _maps(self.inputs))
        object.__setattr__(self, "outputs", _maps(self.outputs))
        object.__setattr__(self, "owned_state", _texts(self.owned_state))
        object.__setattr__(self, "dependencies", _texts(self.dependencies))
        object.__setattr__(self, "forbidden_dependencies", _texts(self.forbidden_dependencies))
        object.__setattr__(self, "invariants", _texts(self.invariants))
        object.__setattr__(self, "failure_semantics", _texts(self.failure_semantics))
        object.__setattr__(self, "test_obligations", _texts(self.test_obligations))
        object.__setattr__(self, "api_stability", str(self.api_stability or "STABLE").upper())
        object.__setattr__(self, "target_paths", _safe_paths(self.target_paths))
        object.__setattr__(self, "generation_status", status)
        object.__setattr__(self, "requirement_ids", _texts(self.requirement_ids))
        object.__setattr__(self, "metadata", _maps(self.metadata))
        _reject_source_bodies(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def contract_id(self) -> str:
        return self.module_id

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "module_id": self.module_id,
            "name": self.name,
            "responsibility": self.responsibility,
            "public_interfaces": list(self.public_interfaces),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "owned_state": list(self.owned_state),
            "dependencies": list(self.dependencies),
            "forbidden_dependencies": list(self.forbidden_dependencies),
            "invariants": list(self.invariants),
            "failure_semantics": list(self.failure_semantics),
            "test_obligations": list(self.test_obligations),
            "api_stability": self.api_stability,
            "target_paths": list(self.target_paths),
            "generation_status": self.generation_status,
            "requirement_ids": list(self.requirement_ids),
            "metadata": list(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "ModuleContract":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("module contract must be an object")
        return cls(
            module_id=str(value.get("module_id", value.get("id", ""))),
            name=str(value.get("name", value.get("module_id", ""))),
            responsibility=str(value.get("responsibility", value.get("summary", ""))),
            public_interfaces=tuple(value.get("public_interfaces", value.get("interfaces", ())) or ()),
            inputs=tuple(value.get("inputs", ()) or ()),
            outputs=tuple(value.get("outputs", ()) or ()),
            owned_state=tuple(value.get("owned_state", ()) or ()),
            dependencies=tuple(value.get("dependencies", ()) or ()),
            forbidden_dependencies=tuple(value.get("forbidden_dependencies", ()) or ()),
            invariants=tuple(value.get("invariants", ()) or ()),
            failure_semantics=tuple(value.get("failure_semantics", ()) or ()),
            test_obligations=tuple(value.get("test_obligations", ()) or ()),
            api_stability=str(value.get("api_stability", "STABLE")),
            target_paths=tuple(value.get("target_paths", ()) or ()),
            generation_status=str(value.get("generation_status", "PLANNED")),
            requirement_ids=tuple(value.get("requirement_ids", ()) or ()),
            metadata=tuple(value.get("metadata", ()) or ()),
        )


@dataclass(frozen=True)
class ProjectBlueprint:
    project_id: str
    project_type: str = "APPLICATION"
    requirements: tuple[ProjectRequirement, ...] = ()
    architecture_style: str = "MODULAR"
    module_contracts: tuple[ModuleContract, ...] = ()
    module_declarations: tuple[dict[str, Any], ...] = ()
    shared_contracts: tuple[str, ...] = ()
    interfaces: tuple[InterfaceSchema, ...] = ()
    schemas: tuple[InterfaceSchema, ...] = ()
    external_dependencies: tuple[str, ...] = ()
    external_deps: tuple[str, ...] = ()
    global_invariants: tuple[str, ...] = ()
    test_strategy: tuple[str, ...] = ()
    generation_constraints: tuple[str, ...] = ()
    subject_identity: str = ""
    root_identity: str = ""
    revision_identity: str = ""
    schema_version: str = CORE6_BLUEPRINT_SCHEMA_VERSION
    metadata: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        project_id = str(self.project_id or "").strip()
        if not project_id:
            raise ValueError("project_id is required")
        style = str(self.architecture_style or "MODULAR").upper()
        if style not in ARCHITECTURE_STYLES:
            raise ValueError(f"unsupported architecture style: {style}")
        requirements = tuple(ProjectRequirement.from_value(item) for item in self.requirements)
        contracts = tuple(ModuleContract.from_value(item) for item in self.module_contracts)
        interfaces = tuple(InterfaceSchema.from_value(item) for item in self.interfaces)
        schemas = tuple(InterfaceSchema.from_value(item) for item in self.schemas)
        for label, rows, key in (
            ("requirement", requirements, lambda item: item.requirement_id),
            ("module", contracts, lambda item: item.module_id),
            ("interface", interfaces, lambda item: item.schema_id),
            ("schema", schemas, lambda item: item.schema_id),
        ):
            identities = [key(item) for item in rows]
            if len(identities) != len(set(identities)):
                raise ValueError(f"duplicate {label} identity")
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "project_type", str(self.project_type or "APPLICATION").upper())
        object.__setattr__(self, "architecture_style", style)
        object.__setattr__(self, "requirements", tuple(sorted(requirements, key=lambda item: item.requirement_id)))
        object.__setattr__(self, "module_contracts", tuple(sorted(contracts, key=lambda item: item.module_id)))
        declarations = _maps(self.module_declarations)
        if not declarations:
            declarations = tuple({"module_id": item.module_id, "name": item.name, "target_paths": list(item.target_paths)} for item in contracts)
        object.__setattr__(self, "module_declarations", declarations)
        object.__setattr__(self, "shared_contracts", _texts(self.shared_contracts))
        object.__setattr__(self, "interfaces", tuple(sorted(interfaces, key=lambda item: item.schema_id)))
        object.__setattr__(self, "schemas", tuple(sorted(schemas, key=lambda item: item.schema_id)))
        object.__setattr__(self, "external_dependencies", _texts(tuple(self.external_dependencies) + tuple(self.external_deps)))
        object.__setattr__(self, "external_deps", tuple(self.external_dependencies))
        object.__setattr__(self, "global_invariants", _texts(self.global_invariants))
        object.__setattr__(self, "test_strategy", _texts(self.test_strategy))
        object.__setattr__(self, "generation_constraints", _texts(self.generation_constraints))
        object.__setattr__(self, "subject_identity", str(self.subject_identity or ""))
        object.__setattr__(self, "root_identity", str(self.root_identity or ""))
        object.__setattr__(self, "revision_identity", str(self.revision_identity or ""))
        object.__setattr__(self, "schema_version", str(self.schema_version or CORE6_BLUEPRINT_SCHEMA_VERSION))
        object.__setattr__(self, "metadata", _maps(self.metadata))
        _reject_source_bodies(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def blueprint_id(self) -> str:
        return self.project_id

    @property
    def modules(self) -> tuple[ModuleContract, ...]:
        return self.module_contracts

    @property
    def contract_hashes(self) -> dict[str, str]:
        return {contract.module_id: contract.canonical_hash for contract in self.module_contracts}

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "project_id": self.project_id,
            "project_type": self.project_type,
            "requirements": [item.to_dict() for item in self.requirements],
            "architecture_style": self.architecture_style,
            "module_contracts": [item.to_dict() for item in self.module_contracts],
            "module_declarations": list(self.module_declarations),
            "shared_contracts": list(self.shared_contracts),
            "interfaces": [item.to_dict() for item in self.interfaces],
            "schemas": [item.to_dict() for item in self.schemas],
            "external_dependencies": list(self.external_dependencies),
            "global_invariants": list(self.global_invariants),
            "test_strategy": list(self.test_strategy),
            "generation_constraints": list(self.generation_constraints),
            "subject_identity": self.subject_identity,
            "root_identity": self.root_identity,
            "revision_identity": self.revision_identity,
            "metadata": list(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "ProjectBlueprint":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("blueprint must be an object")
        contracts = value.get("module_contracts", value.get("modules", ())) or ()
        return cls(
            project_id=str(value.get("project_id", value.get("blueprint_id", ""))),
            project_type=str(value.get("project_type", "APPLICATION")),
            requirements=tuple(value.get("requirements", ()) or ()),
            architecture_style=str(value.get("architecture_style", "MODULAR")),
            module_contracts=tuple(contracts),
            module_declarations=tuple(value.get("module_declarations", ()) or ()),
            shared_contracts=tuple(value.get("shared_contracts", ()) or ()),
            interfaces=tuple(value.get("interfaces", ()) or ()),
            schemas=tuple(value.get("schemas", ()) or ()),
            external_dependencies=tuple(value.get("external_dependencies", ()) or ()),
            external_deps=tuple(value.get("external_deps", ()) or ()),
            global_invariants=tuple(value.get("global_invariants", ()) or ()),
            test_strategy=tuple(value.get("test_strategy", ()) or ()),
            generation_constraints=tuple(value.get("generation_constraints", ()) or ()),
            subject_identity=str(value.get("subject_identity", "")),
            root_identity=str(value.get("root_identity", "")),
            revision_identity=str(value.get("revision_identity", "")),
            schema_version=str(value.get("schema_version", CORE6_BLUEPRINT_SCHEMA_VERSION)),
            metadata=tuple(value.get("metadata", ()) or ()),
        )


def blueprint_identity(value: ProjectBlueprint | Mapping[str, Any]) -> str:
    return ProjectBlueprint.from_value(value).canonical_hash


def contract_identity(value: ModuleContract | Mapping[str, Any]) -> str:
    return ModuleContract.from_value(value).canonical_hash


def schema_identity(value: InterfaceSchema | Mapping[str, Any]) -> str:
    return InterfaceSchema.from_value(value).canonical_hash


# Discoverable aliases used by callers that distinguish API and data schemas.
ProjectInterface = InterfaceSchema
DataSchema = InterfaceSchema
ContractSchema = InterfaceSchema


__all__ = [
    "CORE6_BLUEPRINT_SCHEMA_VERSION", "REQUIREMENT_CATEGORIES", "ARCHITECTURE_STYLES",
    "CONTRACT_STATUSES", "ProjectRequirement", "InterfaceSchema", "ProjectInterface",
    "DataSchema", "ContractSchema", "ModuleContract", "ProjectBlueprint",
    "blueprint_identity", "contract_identity", "schema_identity",
]
