"""Bounded generation units, evidence packets and candidate artifacts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .project_blueprint import ModuleContract, ProjectBlueprint
from .project_brain_refs import canonical_hash, normalize_relative_path


INTERFACE_UNIT = "INTERFACE_UNIT"
SCHEMA_UNIT = "SCHEMA_UNIT"
IMPLEMENTATION_UNIT = "IMPLEMENTATION_UNIT"
ADAPTER_UNIT = "ADAPTER_UNIT"
API_BOUNDARY_UNIT = "API_BOUNDARY_UNIT"
TEST_UNIT = "TEST_UNIT"
CONFIGURATION_UNIT = "CONFIGURATION_UNIT"
INTEGRATION_UNIT = "INTEGRATION_UNIT"
GENERATION_UNIT_TYPES = (
    INTERFACE_UNIT, SCHEMA_UNIT, IMPLEMENTATION_UNIT, ADAPTER_UNIT,
    API_BOUNDARY_UNIT, TEST_UNIT, CONFIGURATION_UNIT, INTEGRATION_UNIT,
)

PLANNED = "PLANNED"
BLOCKED = "BLOCKED"
READY = "READY"
GENERATING = "GENERATING"
CANDIDATE_READY = "CANDIDATE_READY"
SYNTAX_REJECTED = "SYNTAX_REJECTED"
CONTRACT_REJECTED = "CONTRACT_REJECTED"
TEST_REJECTED = "TEST_REJECTED"
IMPLEMENTED_UNTESTED = "IMPLEMENTED_UNTESTED"
UNIT_VERIFIED = "UNIT_VERIFIED"
INTEGRATION_BLOCKED = "INTEGRATION_BLOCKED"
FAILED = "FAILED"
GENERATION_UNIT_STATUSES = (
    PLANNED, BLOCKED, READY, GENERATING, CANDIDATE_READY, SYNTAX_REJECTED,
    CONTRACT_REJECTED, TEST_REJECTED, IMPLEMENTED_UNTESTED, UNIT_VERIFIED,
    INTEGRATION_BLOCKED, FAILED,
)

NEW_ARTIFACT = "NEW_ARTIFACT"
EXISTING_MODIFICATION = "EXISTING_MODIFICATION"
ARTIFACT_KINDS = (NEW_ARTIFACT, EXISTING_MODIFICATION)


def _texts(values: Iterable[Any] | None, *, limit: int = 128) -> tuple[str, ...]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        text = str(value or "").strip()
        if text and text not in seen:
            result.append(text)
            seen.add(text)
        if len(result) >= limit:
            break
    return tuple(result)


def _maps(values: Iterable[Any] | None, *, limit: int = 128) -> tuple[dict[str, Any], ...]:
    rows: list[dict[str, Any]] = []
    for value in values or ():
        if isinstance(value, Mapping):
            rows.append({str(key): value[key] for key in sorted(value, key=str)})
        else:
            rows.append({"value": str(value)})
        if len(rows) >= limit:
            break
    rows.sort(key=lambda row: canonical_hash(row))
    return tuple(rows)


def _safe_paths(values: Iterable[Any] | None, *, limit: int = 128) -> tuple[str, ...]:
    paths: set[str] = set()
    for value in values or ():
        paths.add(normalize_relative_path(str(value)))
        if len(paths) >= limit:
            break
    return tuple(sorted(paths))


def _reject_body_keys(value: Any, *, depth: int = 0) -> None:
    if depth > 10:
        raise ValueError("generation evidence is too deeply nested")
    forbidden = {"source", "source_text", "body", "full_file", "repository_snapshot", "entire_file"}
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key).casefold().replace("-", "_") in forbidden:
                raise ValueError("generation evidence packets cannot contain source bodies")
            _reject_body_keys(item, depth=depth + 1)
    elif isinstance(value, (tuple, list, set)):
        for item in value:
            _reject_body_keys(item, depth=depth + 1)


@dataclass(frozen=True)
class GenerationUnit:
    unit_id: str
    module_id: str
    purpose: str
    unit_type: str = IMPLEMENTATION_UNIT
    contract_ids: tuple[str, ...] = ()
    target_paths: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()
    inputs: tuple[dict[str, Any], ...] = ()
    required_tests: tuple[str, ...] = ()
    provider_requirements: tuple[str, ...] = ()
    source_budget: int = 12000
    authority_scope: tuple[str, ...] = ()
    status: str = PLANNED
    artifact_kind: str = NEW_ARTIFACT
    metadata: tuple[dict[str, Any], ...] = ()

    def __post_init__(self) -> None:
        unit_id = str(self.unit_id or "").strip()
        module_id = str(self.module_id or "").strip()
        purpose = str(self.purpose or "").strip()
        unit_type = str(self.unit_type or IMPLEMENTATION_UNIT).upper()
        status = str(self.status or PLANNED).upper()
        artifact_kind = str(self.artifact_kind or NEW_ARTIFACT).upper()
        if not unit_id or not module_id or not purpose:
            raise ValueError("unit_id, module_id and purpose are required")
        if unit_type not in GENERATION_UNIT_TYPES:
            raise ValueError(f"unsupported generation unit type: {unit_type}")
        if status not in GENERATION_UNIT_STATUSES:
            raise ValueError(f"unsupported generation unit status: {status}")
        if artifact_kind not in ARTIFACT_KINDS:
            raise ValueError(f"unsupported artifact kind: {artifact_kind}")
        object.__setattr__(self, "unit_id", unit_id)
        object.__setattr__(self, "module_id", module_id)
        object.__setattr__(self, "purpose", purpose[:4000])
        object.__setattr__(self, "unit_type", unit_type)
        object.__setattr__(self, "contract_ids", _texts(self.contract_ids))
        object.__setattr__(self, "target_paths", _safe_paths(self.target_paths))
        object.__setattr__(self, "dependencies", _texts(self.dependencies))
        object.__setattr__(self, "inputs", _maps(self.inputs))
        object.__setattr__(self, "required_tests", _texts(self.required_tests))
        object.__setattr__(self, "provider_requirements", _texts(self.provider_requirements))
        object.__setattr__(self, "source_budget", max(256, min(200000, int(self.source_budget))))
        object.__setattr__(self, "authority_scope", _safe_paths(self.authority_scope))
        object.__setattr__(self, "status", status)
        object.__setattr__(self, "artifact_kind", artifact_kind)
        object.__setattr__(self, "metadata", _maps(self.metadata))
        _reject_body_keys(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "unit_id": self.unit_id,
            "module_id": self.module_id,
            "purpose": self.purpose,
            "unit_type": self.unit_type,
            "contract_ids": list(self.contract_ids),
            "target_paths": list(self.target_paths),
            "dependencies": list(self.dependencies),
            "inputs": list(self.inputs),
            "required_tests": list(self.required_tests),
            "provider_requirements": list(self.provider_requirements),
            "source_budget": self.source_budget,
            "authority_scope": list(self.authority_scope),
            "status": self.status,
            "artifact_kind": self.artifact_kind,
            "metadata": list(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "GenerationUnit":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("generation unit must be an object")
        return cls(
            unit_id=str(value.get("unit_id", value.get("id", ""))),
            module_id=str(value.get("module_id", "")),
            purpose=str(value.get("purpose", value.get("summary", ""))),
            unit_type=str(value.get("unit_type", IMPLEMENTATION_UNIT)),
            contract_ids=tuple(value.get("contract_ids", ()) or ()),
            target_paths=tuple(value.get("target_paths", value.get("paths", ())) or ()),
            dependencies=tuple(value.get("dependencies", ()) or ()),
            inputs=tuple(value.get("inputs", ()) or ()),
            required_tests=tuple(value.get("required_tests", value.get("tests", ())) or ()),
            provider_requirements=tuple(value.get("provider_requirements", ()) or ()),
            source_budget=int(value.get("source_budget", 12000)),
            authority_scope=tuple(value.get("authority_scope", value.get("authorized_paths", ())) or ()),
            status=str(value.get("status", PLANNED)),
            artifact_kind=str(value.get("artifact_kind", NEW_ARTIFACT)),
            metadata=tuple(value.get("metadata", ()) or ()),
        )


@dataclass(frozen=True)
class GenerationEvidencePacket:
    unit_id: str
    purpose: str
    contract: dict[str, Any]
    interfaces: tuple[dict[str, Any], ...] = ()
    schemas: tuple[dict[str, Any], ...] = ()
    direct_dependencies: tuple[dict[str, Any], ...] = ()
    invariants: tuple[str, ...] = ()
    tests: tuple[dict[str, Any], ...] = ()
    path_constraints: tuple[str, ...] = ()
    style_constraints: tuple[str, ...] = ()
    source_references: tuple[dict[str, Any], ...] = ()
    authority: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, int] = field(default_factory=dict)
    blueprint_identity: str = ""
    revision_identity: str = ""
    repository_revision: str = ""
    contract_hashes: tuple[tuple[str, str], ...] = ()
    schema_version: str = "CORE-6-GENERATION-EVIDENCE-PACKET-V1"

    def __post_init__(self) -> None:
        if not str(self.unit_id or "").strip():
            raise ValueError("packet unit_id is required")
        object.__setattr__(self, "unit_id", str(self.unit_id).strip())
        object.__setattr__(self, "purpose", str(self.purpose or "")[:4000])
        object.__setattr__(self, "contract", dict(self.contract or {}))
        object.__setattr__(self, "interfaces", _maps(self.interfaces, limit=24))
        object.__setattr__(self, "schemas", _maps(self.schemas, limit=24))
        object.__setattr__(self, "direct_dependencies", _maps(self.direct_dependencies, limit=24))
        object.__setattr__(self, "invariants", _texts(self.invariants, limit=64))
        object.__setattr__(self, "tests", _maps(self.tests, limit=24))
        object.__setattr__(self, "path_constraints", _texts(self.path_constraints, limit=64))
        object.__setattr__(self, "style_constraints", _texts(self.style_constraints, limit=32))
        object.__setattr__(self, "source_references", _maps(self.source_references, limit=24))
        object.__setattr__(self, "authority", {str(key): value for key, value in sorted((self.authority or {}).items(), key=lambda item: str(item[0]))})
        object.__setattr__(self, "budget", {str(key): max(0, int(value)) for key, value in sorted((self.budget or {}).items(), key=lambda item: str(item[0]))})
        object.__setattr__(self, "contract_hashes", tuple(sorted((str(key), str(value)) for key, value in self.contract_hashes)))
        _reject_body_keys(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def packet_id(self) -> str:
        return self.canonical_hash[:24]

    @property
    def contract_identity(self) -> str:
        return self.contract_hashes[0][1] if self.contract_hashes else ""

    @property
    def dependencies(self) -> tuple[dict[str, Any], ...]:
        return self.direct_dependencies

    @property
    def source_refs(self) -> tuple[dict[str, Any], ...]:
        return self.source_references

    def is_stale(
        self,
        blueprint: ProjectBlueprint | Mapping[str, Any] | None = None,
        *,
        repository_revision: str | None = None,
        contract_hashes: Mapping[str, str] | None = None,
    ) -> bool:
        if blueprint is not None and ProjectBlueprint.from_value(blueprint).canonical_hash != self.blueprint_identity:
            return True
        if repository_revision is not None and str(repository_revision) != self.repository_revision:
            return True
        if contract_hashes is not None and tuple(sorted((str(k), str(v)) for k, v in contract_hashes.items())) != self.contract_hashes:
            return True
        return False

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": self.schema_version,
            "unit_id": self.unit_id,
            "purpose": self.purpose,
            "contract": self.contract,
            "interfaces": list(self.interfaces),
            "schemas": list(self.schemas),
            "direct_dependencies": list(self.direct_dependencies),
            "invariants": list(self.invariants),
            "tests": list(self.tests),
            "path_constraints": list(self.path_constraints),
            "style_constraints": list(self.style_constraints),
            "source_references": list(self.source_references),
            "authority": self.authority,
            "budget": self.budget,
            "blueprint_identity": self.blueprint_identity,
            "revision_identity": self.revision_identity,
            "repository_revision": self.repository_revision,
            "contract_hashes": {key: value for key, value in self.contract_hashes},
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class GeneratedArtifactCandidate:
    candidate_id: str
    unit_id: str
    provider_id: str = "deterministic"
    artifact_kind: str = NEW_ARTIFACT
    target_paths: tuple[str, ...] = ()
    content: dict[str, str] = field(default_factory=dict)
    patch_representation: dict[str, Any] = field(default_factory=dict)
    base_source_hashes: tuple[tuple[str, str], ...] = ()
    contract_hashes: tuple[tuple[str, str], ...] = ()
    packet_id: str = ""
    complexity: int = 0
    status: str = CANDIDATE_READY
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        candidate_id = str(self.candidate_id or "").strip()
        unit_id = str(self.unit_id or "").strip()
        kind = str(self.artifact_kind or NEW_ARTIFACT).upper()
        if not candidate_id or not unit_id:
            raise ValueError("candidate_id and unit_id are required")
        if kind not in ARTIFACT_KINDS:
            raise ValueError(f"unsupported candidate artifact kind: {kind}")
        content: dict[str, str] = {}
        for path, body in (self.content or {}).items():
            content[normalize_relative_path(str(path))] = str(body)
        object.__setattr__(self, "candidate_id", candidate_id)
        object.__setattr__(self, "unit_id", unit_id)
        object.__setattr__(self, "provider_id", str(self.provider_id or "deterministic"))
        object.__setattr__(self, "artifact_kind", kind)
        object.__setattr__(self, "content", {key: content[key] for key in sorted(content)})
        object.__setattr__(self, "target_paths", tuple(sorted(set(_safe_paths(self.target_paths) + tuple(content)))))
        object.__setattr__(self, "patch_representation", dict(self.patch_representation or {}))
        object.__setattr__(self, "base_source_hashes", tuple(sorted((str(k), str(v)) for k, v in self.base_source_hashes)))
        object.__setattr__(self, "contract_hashes", tuple(sorted((str(k), str(v)) for k, v in self.contract_hashes)))
        object.__setattr__(self, "complexity", max(0, int(self.complexity)))
        object.__setattr__(self, "status", str(self.status or CANDIDATE_READY).upper())
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def artifact_paths(self) -> tuple[str, ...]:
        return self.target_paths

    @property
    def files(self) -> dict[str, str]:
        return dict(self.content)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "candidate_id": self.candidate_id,
            "unit_id": self.unit_id,
            "provider_id": self.provider_id,
            "artifact_kind": self.artifact_kind,
            "target_paths": list(self.target_paths),
            "content": dict(self.content),
            "patch_representation": self.patch_representation,
            "base_source_hashes": {key: value for key, value in self.base_source_hashes},
            "contract_hashes": {key: value for key, value in self.contract_hashes},
            "packet_id": self.packet_id,
            "complexity": self.complexity,
            "status": self.status,
            "metadata": self.metadata,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class ContractValidationResult:
    valid: bool
    status: str
    messages: tuple[str, ...] = ()
    required_exports: tuple[str, ...] = ()
    found_exports: tuple[str, ...] = ()
    missing_interfaces: tuple[str, ...] = ()
    forbidden_dependencies: tuple[str, ...] = ()
    target_path_errors: tuple[str, ...] = ()
    dependency_errors: tuple[str, ...] = ()

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "valid": self.valid,
            "status": self.status,
            "messages": list(self.messages),
            "required_exports": list(self.required_exports),
            "found_exports": list(self.found_exports),
            "missing_interfaces": list(self.missing_interfaces),
            "forbidden_dependencies": list(self.forbidden_dependencies),
            "target_path_errors": list(self.target_path_errors),
            "dependency_errors": list(self.dependency_errors),
        }


@dataclass(frozen=True)
class GenerationUnitReceipt:
    unit_id: str
    status: str
    candidate_id: str = ""
    contract_receipt_hash: str = ""
    test_receipt_hash: str = ""
    verification_hash: str = ""
    subject_identity: str = ""
    repo_map_hash: str = ""
    lexical_index_hash: str = ""
    messages: tuple[str, ...] = ()

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "unit_id": self.unit_id, "status": self.status, "candidate_id": self.candidate_id,
            "contract_receipt_hash": self.contract_receipt_hash, "test_receipt_hash": self.test_receipt_hash,
            "verification_hash": self.verification_hash, "subject_identity": self.subject_identity,
            "repo_map_hash": self.repo_map_hash, "lexical_index_hash": self.lexical_index_hash,
            "messages": list(self.messages),
        }


class CodeGenerationProvider(Protocol):
    """Optional provider seam.  Providers receive one bounded packet only."""

    provider_id: str

    def generate(
        self,
        packet: GenerationEvidencePacket,
        candidate_budget: int = 1,
    ) -> Iterable[GeneratedArtifactCandidate]:
        ...


def build_generation_evidence_packet(
    blueprint: ProjectBlueprint,
    unit: GenerationUnit,
    *,
    contract: ModuleContract | Mapping[str, Any] | None = None,
    repository_revision: str = "",
    authority: Mapping[str, Any] | None = None,
    direct_dependencies: Iterable[Mapping[str, Any]] = (),
    tests: Iterable[Mapping[str, Any]] = (),
    source_references: Iterable[Mapping[str, Any]] = (),
    source_budget: int | None = None,
) -> GenerationEvidencePacket:
    current_contract = ModuleContract.from_value(contract) if contract is not None else next(
        (item for item in blueprint.module_contracts if item.module_id == unit.module_id),
        ModuleContract(unit.module_id, unit.module_id, unit.purpose),
    )
    interfaces = [schema.to_dict(include_hash=False) for schema in blueprint.interfaces if schema.schema_id in current_contract.public_interfaces]
    schemas = [schema.to_dict(include_hash=False) for schema in blueprint.schemas if schema.schema_id in current_contract.public_interfaces]
    packet = GenerationEvidencePacket(
        unit_id=unit.unit_id,
        purpose=unit.purpose,
        contract=current_contract.to_dict(include_hash=False),
        interfaces=interfaces,
        schemas=schemas,
        direct_dependencies=tuple(direct_dependencies),
        invariants=tuple(blueprint.global_invariants) + tuple(current_contract.invariants),
        tests=tuple(tests),
        path_constraints=tuple(unit.target_paths) + tuple(unit.authority_scope),
        style_constraints=tuple(blueprint.generation_constraints),
        source_references=tuple(source_references),
        authority=dict(authority or {}),
        budget={"max_source_characters": int(source_budget or unit.source_budget), "max_candidates": 1},
        blueprint_identity=blueprint.canonical_hash,
        revision_identity=blueprint.revision_identity,
        repository_revision=str(repository_revision),
        contract_hashes=((current_contract.module_id, current_contract.canonical_hash),),
    )
    if sum(len(str(row)) for row in packet.source_references) > packet.budget.get("max_source_characters", 0):
        raise ValueError("generation evidence packet exceeds source-reference budget")
    return packet


# Friendly aliases for external callers.
GenerationEvidence = GenerationEvidencePacket
GeneratedCandidate = GeneratedArtifactCandidate


__all__ = [
    "INTERFACE_UNIT", "SCHEMA_UNIT", "IMPLEMENTATION_UNIT", "ADAPTER_UNIT", "API_BOUNDARY_UNIT",
    "TEST_UNIT", "CONFIGURATION_UNIT", "INTEGRATION_UNIT", "GENERATION_UNIT_TYPES",
    "PLANNED", "BLOCKED", "READY", "GENERATING", "CANDIDATE_READY", "SYNTAX_REJECTED",
    "CONTRACT_REJECTED", "TEST_REJECTED", "IMPLEMENTED_UNTESTED", "UNIT_VERIFIED",
    "INTEGRATION_BLOCKED", "FAILED", "GENERATION_UNIT_STATUSES", "NEW_ARTIFACT",
    "EXISTING_MODIFICATION", "ARTIFACT_KINDS", "GenerationUnit", "GenerationEvidencePacket",
    "GenerationEvidence", "GeneratedArtifactCandidate", "GeneratedCandidate", "ContractValidationResult",
    "GenerationUnitReceipt", "CodeGenerationProvider", "build_generation_evidence_packet",
]
