"""Contract-first, bounded and incremental project generation for CORE-6.

This module is intentionally provider-neutral.  A provider is an optional
candidate source; it never receives the whole repository and never gains
authority from producing a candidate.  The canonical repository is changed
only by an explicit ``apply_verified_candidate``/``apply_verified`` action.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from .change_impact import ChangeImpact, ChangeIsland, analyze_change_impact, build_change_island
from .experiment_sandbox import ExperimentalSandbox, canonical_subject_hash, validate_source_syntax
from .generation_checkpoint import (
    CHECKPOINT_STALE, GenerationCheckpoint, create_generation_checkpoint,
    validate_generation_checkpoint,
)
from .generation_dag import (
    DAG_VALID, DependencyDAG, GENERATION_DEPENDENCY_CYCLE,
    build_dependency_dag,
)
from .generation_units import (
    ARTIFACT_KINDS, CANDIDATE_READY, CONTRACT_REJECTED, EXISTING_MODIFICATION,
    FAILED, GenerationEvidencePacket, GeneratedArtifactCandidate, GenerationUnit,
    GenerationUnitReceipt, NEW_ARTIFACT, PLANNED, SYNTAX_REJECTED, TEST_REJECTED,
    UNIT_VERIFIED, build_generation_evidence_packet,
)
from .lexical_index import LexicalIndex, ensure_lexical_index, incremental_lexical_update
from .project_blueprint import ModuleContract, ProjectBlueprint
from .project_brain_refs import (
    ProjectBrainEntity, TypedReference, canonical_hash, create_project_brain_entity,
)
from .repository_map import RepositoryMap, _safe_root, build_repository_map, incremental_reindex


CORE6_BUILDER_SCHEMA_VERSION = "CORE-6-LARGE-PROJECT-INCREMENTAL-BUILDER-V1"

PROVIDER_FAILURE = "PROVIDER_FAILURE"
SYNTAX_FAILURE = "SYNTAX_FAILURE"
CONTRACT_FAILURE = "CONTRACT_FAILURE"
UNIT_TEST_FAILURE = "TEST_FAILURE"
DEPENDENCY_FAILURE = "DEPENDENCY_FAILURE"
AUTHORITY_FAILURE = "AUTHORITY_FAILURE"
STALE_EVIDENCE = "STALE_EVIDENCE"
INTEGRATION_FAILURE = "INTEGRATION_FAILURE"
GENERATION_BUDGET_REACHED = "GENERATION_BUDGET_REACHED"
GENERATION_PROVIDER_FAILURE = PROVIDER_FAILURE
STALE_PACKET = STALE_EVIDENCE
BUDGET_FAILURE = GENERATION_BUDGET_REACHED
UNIT_GENERATION_BUDGET_REACHED = GENERATION_BUDGET_REACHED
GENERATION_COMPLETE = "GENERATION_COMPLETE"
GENERATION_PARTIAL = "GENERATION_PARTIAL"
GENERATION_BLOCKED = "GENERATION_BLOCKED"
PROJECT_PLANNED = "PROJECT_PLANNED"
PROJECT_GENERATING = "PROJECT_GENERATING"
PROJECT_VERIFIED = "PROJECT_VERIFIED"
PROJECT_PROMOTABLE = "PROJECT_PROMOTABLE"
PROJECT_REQUIRES_FINAL_VERIFICATION = "PROJECT_REQUIRES_FINAL_VERIFICATION"


def _paths(value: Any) -> tuple[str, ...]:
    if isinstance(value, Mapping):
        value = value.get("paths", value.get("files", ()))
    if isinstance(value, str):
        value = (value,)
    return tuple(sorted({str(item).replace("\\", "/").lstrip("./") for item in value or () if str(item).strip()}))


def _authority_paths(authority: Mapping[str, Any] | None, keys: tuple[str, ...]) -> set[str]:
    if not isinstance(authority, Mapping):
        return set()
    result: set[str] = set()
    for key in keys:
        result.update(_paths(authority.get(key, ())))
    return result


def _safe_target(root: Path, path: str) -> Path:
    raw = str(path or "").replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw) or ".." in raw.split("/"):
        raise ValueError("generation path is outside the repository root")
    target = (root / raw).resolve()
    target.relative_to(root.resolve())
    if any(part in {".git", ".hivo", "output", ".agent_runs", ".agent_evidence", "node_modules"} for part in target.relative_to(root.resolve()).parts):
        raise ValueError("generation path targets a protected directory")
    return target


def _map(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        data = value.to_dict()
        return dict(data) if isinstance(data, Mapping) else {}
    return {}


@dataclass(frozen=True)
class GenerationBudget:
    max_units: int = 64
    max_modules: int = 64
    max_files: int = 256
    max_candidates_per_unit: int = 2
    max_total_candidates: int = 128
    max_total_generated_files: int = 256
    max_provider_calls: int = 64
    max_provider_retries: int = 1
    max_strategy_alternatives: int = 2
    max_integration_checks: int = 128
    max_impact_expansion: int = 64
    max_retries_per_unit: int = 1
    max_source_characters_per_unit: int = 24000
    max_project_source_characters: int = 500000
    max_graph_depth: int = 2
    max_graph_nodes: int = 64
    max_dependency_files: int = 32
    max_full_file_reads: int = 4
    max_checkpoints: int = 64

    def __post_init__(self) -> None:
        limits = {
            "max_units": (1, 10000), "max_modules": (1, 10000), "max_files": (1, 100000),
            "max_candidates_per_unit": (1, 16), "max_total_candidates": (1, 10000),
            "max_total_generated_files": (1, 100000), "max_provider_calls": (0, 10000),
            "max_provider_retries": (0, 8), "max_strategy_alternatives": (1, 16),
            "max_integration_checks": (0, 10000), "max_impact_expansion": (1, 10000),
            "max_retries_per_unit": (0, 8), "max_source_characters_per_unit": (256, 200000),
            "max_project_source_characters": (1024, 5000000), "max_graph_depth": (0, 8),
            "max_graph_nodes": (1, 10000), "max_dependency_files": (1, 10000),
            "max_full_file_reads": (0, 128), "max_checkpoints": (1, 10000),
        }
        for name, (low, high) in limits.items():
            object.__setattr__(self, name, max(low, min(high, int(getattr(self, name)))))

    def to_dict(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in (
            "max_units", "max_modules", "max_files", "max_candidates_per_unit", "max_total_candidates",
            "max_total_generated_files", "max_provider_calls", "max_provider_retries", "max_strategy_alternatives",
            "max_integration_checks", "max_impact_expansion",
            "max_retries_per_unit", "max_source_characters_per_unit", "max_project_source_characters",
            "max_graph_depth", "max_graph_nodes", "max_dependency_files", "max_full_file_reads",
            "max_checkpoints",
        )}


@dataclass(frozen=True)
class ProjectGenerationPlan:
    plan_id: str
    blueprint_identity: str
    units: tuple[GenerationUnit, ...]
    dependency_dag: DependencyDAG
    topological_order: tuple[str, ...]
    ready_units: tuple[str, ...] = ()
    blocked_units: tuple[str, ...] = ()
    completed_units: tuple[str, ...] = ()
    failed_units: tuple[str, ...] = ()
    checkpoints: tuple[str, ...] = ()
    budget: GenerationBudget = field(default_factory=GenerationBudget)
    status: str = PLANNED

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def unit_by_id(self) -> dict[str, GenerationUnit]:
        return {unit.unit_id: unit for unit in self.units}

    def ready_set(self, completed: Iterable[str] = ()) -> tuple[str, ...]:
        return self.dependency_dag.ready_set(completed)

    @property
    def edges(self) -> tuple[Any, ...]:
        return self.dependency_dag.edges

    @classmethod
    def from_value(cls, value: Any) -> "ProjectGenerationPlan":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ValueError("generation plan must be an object")
        budget_value = value.get("budget", {}) or {}
        return cls(
            plan_id=str(value.get("plan_id", "")),
            blueprint_identity=str(value.get("blueprint_identity", "")),
            units=tuple(GenerationUnit.from_value(item) for item in value.get("units", ()) or ()),
            dependency_dag=DependencyDAG.from_value(value.get("dependency_dag", {})),
            topological_order=tuple(value.get("topological_order", ()) or ()),
            ready_units=tuple(value.get("ready_units", ()) or ()),
            blocked_units=tuple(value.get("blocked_units", ()) or ()),
            completed_units=tuple(value.get("completed_units", ()) or ()),
            failed_units=tuple(value.get("failed_units", ()) or ()),
            checkpoints=tuple(value.get("checkpoints", ()) or ()),
            budget=GenerationBudget(**dict(budget_value)) if isinstance(budget_value, Mapping) else GenerationBudget(),
            status=str(value.get("status", PLANNED)),
        )

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "plan_id": self.plan_id,
            "blueprint_identity": self.blueprint_identity,
            "units": [unit.to_dict() for unit in self.units],
            "dependency_dag": self.dependency_dag.to_dict(),
            "topological_order": list(self.topological_order),
            "ready_units": list(self.ready_units),
            "blocked_units": list(self.blocked_units),
            "completed_units": list(self.completed_units),
            "failed_units": list(self.failed_units),
            "checkpoints": list(self.checkpoints),
            "budget": self.budget.to_dict(),
            "status": self.status,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class GenerationMetrics:
    units_planned: int = 0
    units_verified: int = 0
    units_failed: int = 0
    provider_calls: int = 0
    candidates_generated: int = 0
    candidates_rejected: int = 0
    syntax_checks: int = 0
    contract_checks: int = 0
    test_checks: int = 0
    integration_checks: int = 0
    checkpoints_created: int = 0
    repo_map_incremental_updates: int = 0
    lexical_incremental_updates: int = 0
    brain_entities_verified: int = 0
    source_characters_generated: int = 0
    full_file_reads: int = 0
    graph_nodes_considered: int = 0
    unresolved_units: int = 0

    def add(self, **values: int) -> "GenerationMetrics":
        data = self.to_dict()
        for key, value in values.items():
            if key in data:
                data[key] += int(value)
        return GenerationMetrics(**data)

    def to_dict(self) -> dict[str, int]:
        return {
            "units_planned": self.units_planned, "units_verified": self.units_verified,
            "units_failed": self.units_failed, "provider_calls": self.provider_calls,
            "candidates_generated": self.candidates_generated, "candidates_rejected": self.candidates_rejected,
            "syntax_checks": self.syntax_checks, "contract_checks": self.contract_checks,
            "test_checks": self.test_checks, "integration_checks": self.integration_checks,
            "checkpoints_created": self.checkpoints_created, "repo_map_incremental_updates": self.repo_map_incremental_updates,
            "lexical_incremental_updates": self.lexical_incremental_updates, "brain_entities_verified": self.brain_entities_verified,
            "source_characters_generated": self.source_characters_generated, "full_file_reads": self.full_file_reads,
            "graph_nodes_considered": self.graph_nodes_considered, "unresolved_units": self.unresolved_units,
        }


@dataclass(frozen=True)
class GenerationResult:
    plan: ProjectGenerationPlan
    status: str
    unit_receipts: tuple[GenerationUnitReceipt, ...] = ()
    candidates: tuple[GeneratedArtifactCandidate, ...] = ()
    checkpoints: tuple[GenerationCheckpoint, ...] = ()
    errors: tuple[dict[str, Any], ...] = ()
    metrics: GenerationMetrics = field(default_factory=GenerationMetrics)
    repository_map: RepositoryMap | None = None
    lexical_index: LexicalIndex | None = None
    brain_entities: tuple[ProjectBrainEntity, ...] = ()
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    completion_state: str = "VERIFIED_IN_SANDBOX"
    subject_changed: bool = False
    integration_receipt: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE6_BUILDER_SCHEMA_VERSION,
            "plan": self.plan.to_dict(),
            "status": self.status,
            "unit_receipts": [receipt.to_dict() for receipt in self.unit_receipts],
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "checkpoints": [checkpoint.to_dict() for checkpoint in self.checkpoints],
            "errors": list(self.errors),
            "metrics": self.metrics.to_dict(),
            "repository_map_hash": self.repository_map.logical_hash if self.repository_map else "",
            "lexical_index_hash": self.lexical_index.logical_hash if self.lexical_index else "",
            "brain_entities": [entity.to_dict() for entity in self.brain_entities],
            "unresolved_evidence": list(self.unresolved_evidence),
            "completion_state": self.completion_state,
            "subject_changed": self.subject_changed,
            "integration_receipt": self.integration_receipt,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


class GenerationProvider(Protocol):
    provider_id: str

    def generate(self, packet: GenerationEvidencePacket, candidate_budget: int = 1) -> Iterable[Any]:
        ...


class DeterministicFakeProvider:
    """Small provider used only by deterministic tests and architecture controls."""

    provider_id = "deterministic-fake"

    def __init__(self, candidates: Mapping[str, Iterable[Any]] | Iterable[Any] = ()) -> None:
        if isinstance(candidates, Mapping):
            self._candidates = {str(key): tuple(value or ()) for key, value in candidates.items()}
            self._default = ()
        else:
            self._candidates = {}
            self._default = tuple(candidates or ())

    def generate(self, packet: GenerationEvidencePacket, candidate_budget: int = 1) -> tuple[Any, ...]:
        rows = self._candidates.get(packet.unit_id, self._default)
        return tuple(rows)[:max(0, int(candidate_budget))]


FakeGenerationProvider = DeterministicFakeProvider
ProjectGenerationBudget = GenerationBudget


def units_from_blueprint(
    blueprint: ProjectBlueprint | Mapping[str, Any],
    *,
    authority_scope: Iterable[str] = (),
) -> tuple[GenerationUnit, ...]:
    current = ProjectBlueprint.from_value(blueprint)
    scope = tuple(authority_scope)
    rows: list[GenerationUnit] = []
    for contract in current.module_contracts:
        paths = contract.target_paths
        if not paths:
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", contract.module_id)
            paths = (f"generated/{safe_name}.py",)
        rows.append(GenerationUnit(
            unit_id=f"UNIT-{contract.module_id}",
            module_id=contract.module_id,
            purpose=contract.responsibility,
            unit_type="IMPLEMENTATION_UNIT",
            contract_ids=(contract.module_id,),
            target_paths=paths,
            dependencies=contract.dependencies,
            required_tests=contract.test_obligations,
            authority_scope=scope or paths,
        ))
    return tuple(rows)


def build_generation_plan(
    blueprint: ProjectBlueprint | Mapping[str, Any],
    units: Iterable[GenerationUnit | Mapping[str, Any]] | None = None,
    *,
    budget: GenerationBudget | None = None,
) -> ProjectGenerationPlan:
    current = ProjectBlueprint.from_value(blueprint)
    generation_budget = budget or GenerationBudget()
    unit_rows = tuple(GenerationUnit.from_value(item) for item in (units if units is not None else units_from_blueprint(current)))
    unit_limit = min(generation_budget.max_units, generation_budget.max_modules)
    if len(unit_rows) > unit_limit:
        unit_rows = unit_rows[: unit_limit]
    dag = build_dependency_dag(current, unit_rows)
    order = dag.topological_order()
    blocked = tuple(sorted(set(dag.nodes) - set(order))) if dag.validation and not dag.validation.valid else ()
    status = PLANNED if dag.validation and dag.validation.valid else GENERATION_BLOCKED
    plan_id = "PLAN-" + canonical_hash({"blueprint": current.canonical_hash, "units": [unit.to_dict() for unit in unit_rows]})[:24]
    return ProjectGenerationPlan(
        plan_id=plan_id,
        blueprint_identity=current.canonical_hash,
        units=tuple(sorted(unit_rows, key=lambda unit: unit.unit_id)),
        dependency_dag=dag,
        topological_order=order,
        ready_units=dag.ready_set(),
        blocked_units=blocked,
        budget=generation_budget,
        status=status,
    )


def _candidate_from_value(value: Any, *, unit_id: str, provider_id: str, packet_id: str) -> GeneratedArtifactCandidate:
    if isinstance(value, GeneratedArtifactCandidate):
        return value
    row = _map(value)
    content = row.get("content", row.get("files", {}))
    if isinstance(content, (list, tuple)):
        content = {str(item.get("path")): str(item.get("content", "")) for item in content if isinstance(item, Mapping)}
    return GeneratedArtifactCandidate(
        candidate_id=str(row.get("candidate_id", row.get("id", "CANDIDATE-" + canonical_hash(row)[:16]))),
        unit_id=str(row.get("unit_id", unit_id)),
        provider_id=str(row.get("provider_id", provider_id)),
        artifact_kind=str(row.get("artifact_kind", NEW_ARTIFACT)),
        target_paths=tuple(row.get("target_paths", row.get("paths", tuple(content or {}))) or ()),
        content=dict(content or {}),
        patch_representation=dict(row.get("patch_representation", row.get("patch", {})) or {}),
        base_source_hashes=tuple((row.get("base_source_hashes", {}) or {}).items()) if isinstance(row.get("base_source_hashes", {}), Mapping) else tuple(row.get("base_source_hashes", ()) or ()),
        contract_hashes=tuple((row.get("contract_hashes", {}) or {}).items()) if isinstance(row.get("contract_hashes", {}), Mapping) else tuple(row.get("contract_hashes", ()) or ()),
        packet_id=str(row.get("packet_id", packet_id)),
        complexity=int(row.get("complexity", 0)),
        status=str(row.get("status", CANDIDATE_READY)),
        metadata=dict(row.get("metadata", {}) or {}),
    )


def _bool_check(value: Any, *, default: bool = True) -> tuple[bool, dict[str, Any]]:
    if value is None:
        return default, {"status": "NOT_CONFIGURED"}
    if isinstance(value, bool):
        return value, {"passed": value}
    data = _map(value)
    if data:
        return bool(data.get("passed", data.get("valid", data.get("ok", False)))), data
    return bool(value), {"value": str(value)}


def _invoke_callback(callback: Any, *args: Any) -> Any:
    if callback is None:
        return None
    target = callback
    if not callable(target):
        for name in ("validate", "verify", "check", "evaluate", "run"):
            if hasattr(target, name):
                target = getattr(target, name)
                break
    if not callable(target):
        return None
    attempts = [args, args[:2], args[:1], ()]
    last: Exception | None = None
    for call_args in attempts:
        try:
            return target(*call_args)
        except TypeError as exc:
            last = exc
    return {"passed": False, "reason": f"callback signature rejected: {last}"} if last else None


class ProjectBuilder:
    """Bounded generator/maintainer that keeps canonical state isolated by default."""

    def __init__(
        self,
        project_root: str | Path,
        blueprint: ProjectBlueprint | Mapping[str, Any],
        units: Iterable[GenerationUnit | Mapping[str, Any]] | None = None,
        *,
        repository_map: RepositoryMap | Mapping[str, Any] | None = None,
        lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
        brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
        authority: Mapping[str, Any] | None = None,
        dnt_paths: Iterable[str] = (),
        budget: GenerationBudget | None = None,
        provider: GenerationProvider | None = None,
    ) -> None:
        self.project_root = _safe_root(project_root)
        self.blueprint = ProjectBlueprint.from_value(blueprint)
        self.authority = dict(authority or {})
        self.dnt_paths = tuple(_paths(tuple(dnt_paths)))
        self.budget = budget or GenerationBudget()
        self.plan = build_generation_plan(self.blueprint, units, budget=self.budget)
        self.provider = provider
        self.brain_entities = tuple(
            item if isinstance(item, ProjectBrainEntity) else ProjectBrainEntity.from_dict(item)
            for item in brain_entities
        )
        if any(not item.created_from_verified_evidence for item in self.brain_entities):
            raise ValueError("CORE-6 accepts only verified reference-based Brain entities")
        self.repository_map = repository_map if isinstance(repository_map, RepositoryMap) else (
            RepositoryMap.from_dict(repository_map, self.project_root) if repository_map is not None else build_repository_map(self.project_root)
        )
        self.lexical_index, self.lexical_mode = ensure_lexical_index(lexical_index, self.repository_map, self.project_root)
        self.subject_hash = canonical_subject_hash(self.project_root)
        self._checkpoints: list[GenerationCheckpoint] = []
        self._lineage: list[str] = []

    def build_packet(self, unit: GenerationUnit) -> GenerationEvidencePacket:
        contract = next((item for item in self.blueprint.module_contracts if item.module_id == unit.module_id), None)
        dependencies = []
        for dependency in unit.dependencies:
            if dependency in self.repository_map.files:
                dependencies.append({"path": dependency, "content_hash": self.repository_map.files[dependency].get("content_hash", "")})
            else:
                dependencies.append({"module_id": dependency})
        tests = [{"path": path, "role": "required_test"} for path in unit.required_tests]
        return build_generation_evidence_packet(
            self.blueprint,
            unit,
            contract=contract,
            repository_revision=self.repository_map.index_revision,
            authority={"target_paths": list(unit.target_paths), "scope": list(self._generation_scope())},
            direct_dependencies=dependencies,
            tests=tests,
            source_references=tuple({"path": path, "content_hash": self.repository_map.files.get(path, {}).get("content_hash", "")} for path in unit.target_paths if path in self.repository_map.files),
            source_budget=min(unit.source_budget, self.budget.max_source_characters_per_unit),
        )

    def _generation_scope(self) -> set[str]:
        scope = _authority_paths(self.authority, (
            "approved_generation_scope", "generation_scope", "authorized_generation_paths",
            "approved_mutation_scope", "mutation_scope", "authorized_paths", "approved_scope",
        ))
        return scope

    def _dnt(self) -> set[str]:
        result = set(self.dnt_paths)
        result.update(_authority_paths(self.authority, ("dnt", "do_not_touch", "approved_dnt")))
        return result

    def _candidate_authority_errors(self, candidate: GeneratedArtifactCandidate, unit: GenerationUnit) -> tuple[str, ...]:
        errors: list[str] = []
        scope = self._generation_scope()
        dnt = self._dnt()
        for path in candidate.target_paths:
            try:
                _safe_target(self.project_root, path)
            except ValueError as exc:
                errors.append(f"PATH_UNSAFE:{path}:{exc}")
            if path in dnt:
                errors.append(f"DNT_PROTECTED:{path}")
            if unit.target_paths and path not in unit.target_paths:
                errors.append(f"UNIT_PATH_OUTSIDE_DECLARATION:{path}")
            if scope and path not in scope:
                errors.append(f"AUTHORITY_SCOPE_BLOCKED:{path}")
            if not scope and not bool(self.authority.get("allow_generation", False)):
                errors.append(f"GENERATION_AUTHORITY_REQUIRED:{path}")
        return tuple(errors)

    def _validate_contract(self, candidate: GeneratedArtifactCandidate, unit: GenerationUnit) -> tuple[bool, dict[str, Any]]:
        contract = next((item for item in self.blueprint.module_contracts if item.module_id == unit.module_id), None)
        if contract is None:
            return False, {"status": "CONTRACT_MISSING", "messages": [unit.module_id]}
        errors: list[str] = []
        found: list[str] = []
        body = "\n".join(candidate.content.values())
        for interface in contract.public_interfaces:
            if interface in body:
                found.append(interface)
            else:
                errors.append(f"missing_public_interface:{interface}")
        for forbidden in contract.forbidden_dependencies:
            if forbidden and forbidden in body:
                errors.append(f"forbidden_dependency:{forbidden}")
        if not candidate.target_paths:
            errors.append("candidate_has_no_target_path")
        if set(candidate.target_paths) != set(unit.target_paths):
            errors.append("candidate_target_paths_do_not_match_unit")
        return not errors, {
            "status": "CONTRACT_PASS" if not errors else "CONTRACT_REJECTED",
            "messages": errors,
            "required_exports": list(contract.public_interfaces),
            "found_exports": found,
        }

    def _validate_candidate(
        self,
        candidate: GeneratedArtifactCandidate,
        unit: GenerationUnit,
        *,
        contract_validator: Callable[..., Any] | None = None,
        test_validator: Callable[..., Any] | None = None,
    ) -> tuple[bool, str, dict[str, Any]]:
        authority_errors = self._candidate_authority_errors(candidate, unit)
        if authority_errors:
            return False, AUTHORITY_FAILURE, {"status": AUTHORITY_FAILURE, "messages": list(authority_errors)}
        source_chars = sum(len(body) for body in candidate.content.values())
        if source_chars > min(unit.source_budget, self.budget.max_source_characters_per_unit):
            return False, GENERATION_BUDGET_REACHED, {"status": GENERATION_BUDGET_REACHED, "source_characters": source_chars}
        syntax_rows: list[dict[str, Any]] = []
        for path, body in candidate.content.items():
            syntax = validate_source_syntax(path, body)
            syntax_rows.append({"path": path, **syntax.to_dict()})
            if not syntax.valid:
                return False, SYNTAX_FAILURE, {"status": SYNTAX_REJECTED, "syntax": syntax_rows}
        contract_ok, contract_row = self._validate_contract(candidate, unit)
        if contract_validator is not None:
            callback_ok, callback_row = _bool_check(_invoke_callback(contract_validator, candidate, unit, self.blueprint), default=False)
            contract_row["external_validator"] = callback_row
            contract_ok = contract_ok and callback_ok
        if not contract_ok:
            return False, CONTRACT_FAILURE, {"status": CONTRACT_REJECTED, "contract": contract_row, "syntax": syntax_rows}
        if test_validator is not None:
            test_ok, test_row = _bool_check(_invoke_callback(test_validator, candidate, unit, self.project_root), default=False)
            if not test_ok:
                return False, UNIT_TEST_FAILURE, {"status": TEST_REJECTED, "contract": contract_row, "tests": test_row, "syntax": syntax_rows}
        return True, UNIT_VERIFIED, {"status": UNIT_VERIFIED, "contract": contract_row, "syntax": syntax_rows}

    def _sandbox_candidate(self, sandbox: ExperimentalSandbox, candidate: GeneratedArtifactCandidate) -> tuple[bool, str]:
        if sandbox.sandbox_root is None:
            return False, "sandbox_not_active"
        for path, body in candidate.content.items():
            try:
                target = _safe_target(sandbox.sandbox_root, path)
            except ValueError as exc:
                return False, str(exc)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8", newline="")
        return True, "sandbox_candidate_materialized"

    def apply_verified_candidate(
        self,
        candidate: GeneratedArtifactCandidate,
        unit: GenerationUnit,
        *,
        v25_5_validator: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Explicitly apply a verified NEW_ARTIFACT candidate to canonical source."""
        errors = self._candidate_authority_errors(candidate, unit)
        if errors:
            return {"applied": False, "status": AUTHORITY_FAILURE, "errors": list(errors)}
        if candidate.artifact_kind != NEW_ARTIFACT:
            return {"applied": False, "status": "EXISTING_MODIFICATION_REQUIRES_CORE5"}
        if v25_5_validator is None:
            return {"applied": False, "status": "V25_5_REQUIRED", "reason": "canonical application requires the existing V25.5 gate"}
        v25_5_ok, v25_5_row = _bool_check(_invoke_callback(v25_5_validator, candidate, unit), default=False)
        if not v25_5_ok:
            return {"applied": False, "status": "V25_5_REJECTED", "detail": v25_5_row}
        valid, failure, detail = self._validate_candidate(candidate, unit)
        if not valid:
            return {"applied": False, "status": failure, "validation": detail}
        before = canonical_subject_hash(self.project_root)
        for path, body in candidate.content.items():
            target = _safe_target(self.project_root, path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8", newline="")
        changed = tuple(sorted(candidate.content))
        map_metrics: dict[str, int] = {}
        self.repository_map = incremental_reindex(self.repository_map, self.project_root, changed_paths=changed, metrics=map_metrics)
        lexical_metrics: dict[str, int] = {}
        self.lexical_index = incremental_lexical_update(self.lexical_index, self.repository_map, self.project_root, changed_paths=changed, metrics=lexical_metrics)
        self.subject_hash = canonical_subject_hash(self.project_root)
        return {
            "applied": True,
            "status": "APPLIED_VERIFIED_CANDIDATE",
            "changed_paths": list(changed),
            "subject_before": before,
            "subject_after": self.subject_hash,
            "repo_map_hash": self.repository_map.logical_hash,
            "lexical_index_hash": self.lexical_index.logical_hash,
            "map_metrics": map_metrics,
            "lexical_metrics": lexical_metrics,
        }

    def _brain_entity_for_unit(self, unit: GenerationUnit, candidate: GeneratedArtifactCandidate) -> ProjectBrainEntity | None:
        contract = next((item for item in self.blueprint.module_contracts if item.module_id == unit.module_id), None)
        if contract is None:
            return None
        refs_list: list[TypedReference] = [
            TypedReference("file", path, verified_revision=self.repository_map.index_revision)
            for path in candidate.target_paths
        ]
        for interface in contract.public_interfaces:
            if candidate.target_paths:
                refs_list.append(TypedReference("symbol", candidate.target_paths[0], interface, verified_revision=self.repository_map.index_revision))
        for test_path in contract.test_obligations:
            try:
                refs_list.append(TypedReference("test", test_path, verified_revision=self.repository_map.index_revision))
            except ValueError:
                continue
        try:
            refs_list.append(TypedReference("graph", contract.module_id))
        except ValueError:
            pass
        refs = tuple(refs_list)
        hashes = {path: self.repository_map.files.get(path, {}).get("content_hash", "") for path in candidate.target_paths if path in self.repository_map.files}
        return create_project_brain_entity(
            entity_id=f"core6:{self.blueprint.project_id}:{contract.module_id}",
            entity_kind="MODULE",
            name=contract.name,
            summary=contract.responsibility,
            contracts=tuple(contract.public_interfaces) + (contract.canonical_hash,),
            invariants=contract.invariants,
            references=refs,
            verified_subject_identity=self.subject_hash,
            verified_revision_identity=self.repository_map.index_revision,
            verified_source_hashes=hashes,
            created_from_verified_evidence=True,
        )

    def _checkpoint(self, plan: ProjectGenerationPlan, completed: set[str], receipts: Mapping[str, GenerationUnitReceipt], brain_identity: str) -> GenerationCheckpoint | None:
        if len(self._checkpoints) >= self.budget.max_checkpoints:
            return None
        checkpoint = create_generation_checkpoint(
            checkpoint_id=f"CHECKPOINT-{len(self._checkpoints) + 1:04d}",
            blueprint_identity=self.blueprint.canonical_hash,
            plan_identity=plan.canonical_hash,
            completed_units=sorted(completed),
            verified_contracts=sorted(completed),
            subject_hash=self.subject_hash,
            repository_map_hash=self.repository_map.logical_hash,
            lexical_index_identity=self.lexical_index.logical_hash,
            brain_working_identity=brain_identity,
            receipt_hashes={unit_id: receipt.canonical_hash for unit_id, receipt in receipts.items()},
            generation_lineage=tuple(self._lineage),
        )
        self._checkpoints.append(checkpoint)
        return checkpoint

    def generate(
        self,
        *,
        checkpoint: GenerationCheckpoint | Mapping[str, Any] | None = None,
        apply_verified: bool = False,
        contract_validator: Callable[..., Any] | None = None,
        test_validator: Callable[..., Any] | None = None,
        integration_validator: Callable[..., Any] | None = None,
        v25_5_validator: Callable[..., Any] | None = None,
        v25_6_validator: Callable[..., Any] | None = None,
    ) -> GenerationResult:
        if self.plan.status != PLANNED:
            return GenerationResult(self.plan, GENERATION_BLOCKED, errors=({"status": self.plan.dependency_dag.validation.status if self.plan.dependency_dag.validation else GENERATION_BLOCKED},), repository_map=self.repository_map, lexical_index=self.lexical_index)
        if checkpoint is not None:
            validation = validate_generation_checkpoint(
                checkpoint,
                blueprint_identity=self.blueprint.canonical_hash,
                plan_identity=self.plan.canonical_hash,
                subject_hash=self.subject_hash,
                repository_map_hash=self.repository_map.logical_hash,
                lexical_index_identity=self.lexical_index.logical_hash,
            )
            if not validation["valid"]:
                return GenerationResult(self.plan, GENERATION_BLOCKED, errors=({"status": CHECKPOINT_STALE, "reasons": list(validation["reasons"])},), repository_map=self.repository_map, lexical_index=self.lexical_index)
            completed = set(validation["checkpoint"]["completed_units"])
        else:
            completed = set()
        receipts: dict[str, GenerationUnitReceipt] = {}
        candidates: list[GeneratedArtifactCandidate] = []
        errors: list[dict[str, Any]] = []
        metrics = GenerationMetrics(units_planned=len(self.plan.units))
        brain_entities: list[ProjectBrainEntity] = list(self.brain_entities)
        total_source = 0
        total_generated_files = 0
        provider_calls = 0
        total_candidates = 0
        with ExperimentalSandbox(self.project_root, session_id="core6-generation", authority=self.authority, dnt_paths=self.dnt_paths) as sandbox:
            for unit_id in self.plan.topological_order:
                unit = self.plan.unit_by_id[unit_id]
                if unit_id in completed:
                    continue
                if not all(dependency in completed for dependency in self.plan.dependency_dag.dependencies.get(unit_id, ())):
                    errors.append({"unit_id": unit_id, "status": DEPENDENCY_FAILURE, "reason": "dependency not verified"})
                    continue
                if provider_calls >= self.budget.max_provider_calls:
                    errors.append({"unit_id": unit_id, "status": GENERATION_BUDGET_REACHED, "reason": "provider budget"})
                    break
                packet = self.build_packet(unit)
                provider_calls += 1
                metrics = metrics.add(provider_calls=1)
                if self.provider is None:
                    errors.append({"unit_id": unit_id, "status": PROVIDER_FAILURE, "reason": "no generation provider configured"})
                    metrics = metrics.add(units_failed=1)
                    continue
                try:
                    try:
                        raw_candidates = tuple(self.provider.generate(packet, self.budget.max_candidates_per_unit))
                    except TypeError:
                        raw_candidates = tuple(self.provider.generate(packet))
                except Exception as exc:
                    errors.append({"unit_id": unit_id, "status": PROVIDER_FAILURE, "reason": str(exc)})
                    metrics = metrics.add(units_failed=1)
                    continue
                metrics = metrics.add(candidates_generated=len(raw_candidates))
                chosen: GeneratedArtifactCandidate | None = None
                chosen_detail: dict[str, Any] = {}
                for raw_candidate in raw_candidates:
                    if total_candidates >= self.budget.max_total_candidates:
                        errors.append({"unit_id": unit_id, "status": GENERATION_BUDGET_REACHED, "reason": "candidate budget"})
                        break
                    total_candidates += 1
                    candidate = _candidate_from_value(raw_candidate, unit_id=unit.unit_id, provider_id=getattr(self.provider, "provider_id", "provider"), packet_id=packet.packet_id)
                    if candidate.unit_id != unit.unit_id:
                        metrics = metrics.add(candidates_rejected=1)
                        continue
                    ok, status, detail = self._validate_candidate(candidate, unit, contract_validator=contract_validator, test_validator=test_validator)
                    metrics = metrics.add(syntax_checks=len(candidate.content), contract_checks=1, test_checks=1 if test_validator else 0)
                    if not ok:
                        metrics = metrics.add(candidates_rejected=1)
                        errors.append({"unit_id": unit_id, "candidate_id": candidate.candidate_id, "status": status, "detail": detail})
                        continue
                    if candidate.artifact_kind == EXISTING_MODIFICATION:
                        # Existing-file modifications belong to CORE-5's guarded path.
                        errors.append({"unit_id": unit_id, "candidate_id": candidate.candidate_id, "status": "EXISTING_MODIFICATION_REQUIRES_CORE5"})
                        metrics = metrics.add(candidates_rejected=1)
                        continue
                    sandbox_ok, sandbox_reason = self._sandbox_candidate(sandbox, candidate)
                    if not sandbox_ok:
                        metrics = metrics.add(candidates_rejected=1)
                        errors.append({"unit_id": unit_id, "candidate_id": candidate.candidate_id, "status": AUTHORITY_FAILURE, "reason": sandbox_reason})
                        continue
                    chosen = candidate
                    chosen_detail = detail
                    break
                if chosen is None:
                    metrics = metrics.add(units_failed=1)
                    continue
                if total_generated_files + len(chosen.target_paths) > self.budget.max_total_generated_files:
                    errors.append({"unit_id": unit_id, "status": GENERATION_BUDGET_REACHED, "reason": "generated file budget"})
                    metrics = metrics.add(units_failed=1)
                    continue
                candidates.append(chosen)
                total_generated_files += len(chosen.target_paths)
                total_source += sum(len(body) for body in chosen.content.values())
                if total_source > self.budget.max_project_source_characters:
                    errors.append({"unit_id": unit_id, "status": GENERATION_BUDGET_REACHED, "reason": "project source budget"})
                    metrics = metrics.add(units_failed=1)
                    continue
                if apply_verified:
                    apply_result = self.apply_verified_candidate(chosen, unit, v25_5_validator=v25_5_validator)
                    if not apply_result.get("applied"):
                        errors.append({"unit_id": unit_id, "status": apply_result.get("status", AUTHORITY_FAILURE), "detail": apply_result})
                        metrics = metrics.add(units_failed=1)
                        continue
                    metrics = metrics.add(repo_map_incremental_updates=1, lexical_incremental_updates=1)
                    subject_changed = True
                else:
                    subject_changed = False
                if integration_validator is not None:
                    integration_ok, integration_row = _bool_check(_invoke_callback(integration_validator, chosen, unit, self.repository_map), default=False)
                    metrics = metrics.add(integration_checks=1)
                    if not integration_ok:
                        errors.append({"unit_id": unit_id, "status": INTEGRATION_FAILURE, "detail": integration_row})
                        metrics = metrics.add(units_failed=1)
                        continue
                if v25_5_validator is not None:
                    v25_5_ok, v25_5_row = _bool_check(_invoke_callback(v25_5_validator, chosen, unit), default=False)
                    if not v25_5_ok:
                        errors.append({"unit_id": unit_id, "status": "V25_5_REJECTED", "detail": v25_5_row})
                        metrics = metrics.add(units_failed=1)
                        continue
                completed.add(unit_id)
                receipt = GenerationUnitReceipt(
                    unit_id=unit_id, status=UNIT_VERIFIED, candidate_id=chosen.candidate_id,
                    contract_receipt_hash=canonical_hash(chosen_detail.get("contract", {})),
                    test_receipt_hash=canonical_hash(chosen_detail.get("tests", {"status": "NOT_CONFIGURED"})),
                    verification_hash=chosen.canonical_hash,
                    subject_identity=self.subject_hash,
                    repo_map_hash=self.repository_map.logical_hash,
                    lexical_index_hash=self.lexical_index.logical_hash,
                )
                receipts[unit_id] = receipt
                self._lineage.append(receipt.canonical_hash)
                metrics = metrics.add(units_verified=1, source_characters_generated=sum(len(body) for body in chosen.content.values()))
                if apply_verified:
                    entity = self._brain_entity_for_unit(unit, chosen)
                    if entity is not None:
                        brain_entities.append(entity)
                        metrics = metrics.add(brain_entities_verified=1)
                checkpoint = self._checkpoint(self.plan, completed, receipts, canonical_hash([entity.to_dict() for entity in brain_entities]))
                if checkpoint is None:
                    errors.append({"unit_id": unit_id, "status": GENERATION_BUDGET_REACHED, "reason": "checkpoint budget"})
                    metrics = metrics.add(units_failed=1)
                    break
                metrics = metrics.add(checkpoints_created=1)
            final_plan_status = GENERATION_COMPLETE if len(completed) == len(self.plan.units) else (GENERATION_PARTIAL if completed else GENERATION_BLOCKED)
        final_units = tuple(
            replace(unit, status=UNIT_VERIFIED if unit.unit_id in completed else FAILED)
            for unit in self.plan.units
        )
        final_plan = replace(self.plan, units=final_units, completed_units=tuple(sorted(completed)), failed_units=tuple(sorted(set(self.plan.topological_order) - completed)), ready_units=self.plan.dependency_dag.ready_set(completed), checkpoints=tuple(item.checkpoint_id for item in self._checkpoints), status=final_plan_status)
        integration_receipt: dict[str, Any] = {"status": "NOT_RUN", "full_v25_6": False}
        if final_plan_status == GENERATION_COMPLETE and v25_6_validator is not None:
            ok, row = _bool_check(_invoke_callback(v25_6_validator, final_plan, self.repository_map), default=False)
            integration_receipt = {"status": "PASS" if ok else "V25_6_FAILED", "full_v25_6": ok, "detail": row}
            if not ok:
                final_plan_status = GENERATION_PARTIAL
                errors.append({"status": "V25_6_FAILED", "detail": row})
        elif final_plan_status == GENERATION_COMPLETE:
            integration_receipt = {"status": "V25_6_REQUIRED", "full_v25_6": False}
            final_plan_status = GENERATION_PARTIAL
        final_plan = replace(final_plan, status=final_plan_status)
        completion_state = PROJECT_PROMOTABLE if final_plan_status == GENERATION_COMPLETE and integration_receipt.get("full_v25_6") else "VERIFIED_IN_SANDBOX" if not apply_verified else "IMPLEMENTED_UNVERIFIED"
        return GenerationResult(
            plan=final_plan,
            status=final_plan_status,
            unit_receipts=tuple(receipts.values()),
            candidates=tuple(candidates),
            checkpoints=tuple(self._checkpoints),
            errors=tuple(errors),
            metrics=metrics,
            repository_map=self.repository_map,
            lexical_index=self.lexical_index,
            brain_entities=tuple(brain_entities),
            unresolved_evidence=tuple({"unit_id": unit_id, "reason": "not verified"} for unit_id in self.plan.topological_order if unit_id not in completed),
            completion_state=completion_state,
            subject_changed=bool(apply_verified and completed),
            integration_receipt=integration_receipt,
        )

    def maintenance_impact(self, changed_paths: Iterable[str], **kwargs: Any) -> tuple[ChangeImpact, ChangeIsland]:
        impact = analyze_change_impact(self.repository_map, changed_paths, blueprint=self.blueprint, **kwargs)
        return impact, build_change_island(impact, blueprint=self.blueprint)

    def maintenance_context(
        self,
        query: Any,
        *,
        failure_evidence: Any = None,
        repair_problem: Any = None,
        diagnostic_session: Any = None,
        authority: Mapping[str, Any] | None = None,
        dnt_paths: Iterable[str] = (),
    ) -> dict[str, Any]:
        """Expose bounded CORE-2/3/4/5 maintenance seams without applying changes."""
        from .repo_intelligence import search_repository

        search = search_repository(
            query, self.repository_map, self.project_root,
            lexical_index=self.lexical_index, brain_entities=self.brain_entities,
            authority=authority or self.authority,
        )
        result: dict[str, Any] = {
            "search": search, "diagnostics": diagnostic_session, "localization": None, "repair": None,
        }
        if failure_evidence is not None:
            from .fault_localization import localize_fault
            result["localization"] = localize_fault(
                repository_map=self.repository_map, project_root=self.project_root,
                failure_evidence=failure_evidence, working_set=search.working_set,
                lexical_index=self.lexical_index, brain_entities=self.brain_entities,
                authority=authority or self.authority, dnt_paths=tuple(dnt_paths),
            )
        if repair_problem is not None:
            from .patch_search import search_patch_candidates
            result["repair"] = search_patch_candidates(
                repair_problem, self.project_root,
                authority=authority or self.authority, dnt_paths=tuple(dnt_paths),
            )
        return result


def validate_generated_artifact_candidate(
    project_root: str | Path,
    blueprint: ProjectBlueprint | Mapping[str, Any],
    unit: GenerationUnit | Mapping[str, Any],
    candidate: GeneratedArtifactCandidate | Mapping[str, Any],
    *,
    authority: Mapping[str, Any] | None = None,
    dnt_paths: Iterable[str] = (),
    contract_validator: Callable[..., Any] | None = None,
    test_validator: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Public deterministic candidate gate used by provider-free controls."""
    current_unit = GenerationUnit.from_value(unit)
    current_candidate = _candidate_from_value(
        candidate, unit_id=current_unit.unit_id, provider_id="external", packet_id="",
    )
    builder = ProjectBuilder(
        project_root, blueprint, (current_unit,), authority=authority,
        dnt_paths=dnt_paths, provider=DeterministicFakeProvider(),
    )
    valid, status, detail = builder._validate_candidate(
        current_candidate, current_unit,
        contract_validator=contract_validator, test_validator=test_validator,
    )
    return {
        "valid": valid, "status": status, "detail": detail,
        "candidate": current_candidate.to_dict(),
    }


def project_generation_metrics(result: GenerationResult | Mapping[str, Any]) -> dict[str, int]:
    if isinstance(result, GenerationResult):
        return result.metrics.to_dict()
    return dict(_map(result).get("metrics", {}) or {})


def benchmark_generation_scenarios(scenarios: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Run deterministic architecture controls and return navigation metrics.

    Scenarios are explicit test inputs.  This helper never discovers a provider
    and never applies candidates unless the scenario explicitly asks for that
    action.
    """
    rows: list[dict[str, Any]] = []
    for index, scenario in enumerate(scenarios):
        data = dict(scenario)
        builder = ProjectBuilder(
            data["project_root"], data["blueprint"], data.get("units"),
            repository_map=data.get("repository_map"), lexical_index=data.get("lexical_index"),
            authority=data.get("authority"), dnt_paths=data.get("dnt_paths", ()),
            budget=data.get("budget"), provider=data.get("provider"),
        )
        result = builder.generate(
            apply_verified=bool(data.get("apply_verified", False)),
            v25_5_validator=data.get("v25_5_validator"),
            v25_6_validator=data.get("v25_6_validator", lambda *args: True),
        )
        rows.append({
            "scenario_id": str(data.get("scenario_id", f"SCENARIO-{index + 1}")),
            "status": result.status,
            "units": len(result.plan.units),
            "verified_units": result.metrics.units_verified,
            "source_unchanged": not result.subject_changed,
            "metrics": result.metrics.to_dict(),
            "result_hash": result.canonical_hash,
        })
    return tuple(rows)


def generate_project(
    project_root: str | Path,
    blueprint: ProjectBlueprint | Mapping[str, Any],
    units: Iterable[GenerationUnit | Mapping[str, Any]] | None = None,
    **kwargs: Any,
) -> GenerationResult:
    builder = ProjectBuilder(project_root, blueprint, units, **{
        key: kwargs.pop(key) for key in (
            "repository_map", "lexical_index", "brain_entities", "authority", "dnt_paths", "budget", "provider",
        ) if key in kwargs
    })
    return builder.generate(**kwargs)


def build_task_generation_plan(*args: Any, **kwargs: Any) -> ProjectGenerationPlan:
    return build_generation_plan(*args, **kwargs)


__all__ = [
    "CORE6_BUILDER_SCHEMA_VERSION", "PROVIDER_FAILURE", "GENERATION_PROVIDER_FAILURE", "SYNTAX_FAILURE", "CONTRACT_FAILURE",
    "UNIT_TEST_FAILURE", "DEPENDENCY_FAILURE", "AUTHORITY_FAILURE", "STALE_EVIDENCE",
    "INTEGRATION_FAILURE", "STALE_PACKET", "BUDGET_FAILURE", "UNIT_GENERATION_BUDGET_REACHED",
    "GENERATION_BUDGET_REACHED", "GENERATION_COMPLETE", "GENERATION_PARTIAL",
    "GENERATION_BLOCKED", "PROJECT_PLANNED", "PROJECT_GENERATING", "PROJECT_VERIFIED",
    "PROJECT_PROMOTABLE", "PROJECT_REQUIRES_FINAL_VERIFICATION", "GenerationBudget", "ProjectGenerationBudget", "ProjectGenerationPlan", "GenerationMetrics",
    "GenerationResult", "GenerationProvider", "DeterministicFakeProvider", "FakeGenerationProvider",
    "units_from_blueprint", "build_generation_plan", "build_task_generation_plan", "ProjectBuilder",
    "generate_project", "validate_generated_artifact_candidate", "project_generation_metrics",
    "benchmark_generation_scenarios",
]
