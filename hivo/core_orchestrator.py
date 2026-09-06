"""Provider-free orchestration across HIVO CORE-1 through CORE-6.

The coordinator is intentionally a composition layer.  It selects bounded
Core components and records their evidence, but it never creates approval,
widens authority, treats a candidate as verified, or calls a model directly.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .change_impact import LARGE_IMPACT_CHANGE, analyze_change_impact, build_change_island
from .core_execution import (
    AUTHORITY_BLOCKED, BLOCKED, BUILD, BUDGET_REACHED, CANONICAL_APPLYING,
    COMPLETE, CONTEXT_BUILDING, CONTRACT_FAILURE, CoreBudget, CoreExecutionResult,
    CoreExecutionState, CoreProviderRequest, DIAGNOSE, DIAGNOSTIC_INCONCLUSIVE,
    DNT_BLOCKED, EXECUTION_MODES, EXPERIMENTING, FINAL_VERIFICATION_FAILED,
    GENERATING, GENERATION_UNIT_FAILED, INDEX_UPDATING, INITIALIZING,
    LOCALIZATION_INSUFFICIENT, LOCALIZING, MAINTAIN, NEXT_ACTIONS, NEXT_BLOCKED,
    NEXT_COMPLETE, NEXT_EXPAND_CONTEXT, NEXT_FINAL_VERIFICATION_REQUIRED,
    NEXT_INVESTIGATE_FLAKINESS, NEXT_NEEDS_MODEL_PROPOSAL, NEXT_REPAIR_GENERATED_UNIT,
    NEXT_REQUEST_BROADER_AUTHORITY, NEXT_RESOLVE_CONTRACT, NEXT_RUN_DIAGNOSTICS,
    NEXT_SEARCH_ALTERNATE_PATCH, NEXT_BUDGET_REACHED, NO_VIABLE_PATCH, PATCH_SEARCHING,
    PATCH_VERIFICATION_FAILED, PLANNING, PROMOTABLE, PROVIDER_FAILURE, REPAIR,
    STALE_CONTEXT, VERIFYING, WORKING_SET_FIRST, CANDIDATE_SELECTED,
    INTEGRATION_FAILURE,
    new_core_metrics, core_autonomy_lift,
)
from .experimental_evidence import (
    DiagnosticResult, ExperimentalEvidenceEngine, ExperimentalEvidenceLedger,
)
from .fault_localization import (
    FaultFailureEvidence, FaultLocalizationEngine, FaultLocalizationResult,
    FaultLocalizationRequest, LocalizationBudget, INTEGRATION_FAILURE as CORE4_INTEGRATION_FAILURE,
    RUN_DIAGNOSTIC_EXPERIMENTS, build_fault_localization_request,
)
from .generation_checkpoint import validate_generation_checkpoint
from .generation_units import GenerationEvidencePacket, GeneratedArtifactCandidate, GenerationUnit
from .lexical_index import LexicalIndex, ensure_lexical_index
from .patch_candidates import (
    CandidateFailureEvidence, PatchCandidate, VERIFIED, VIABLE,
)
from .patch_search import (
    PatchSearchResult, apply_selected_patch_candidate, search_patch_candidates,
)
from .project_blueprint import ProjectBlueprint
from .project_brain_refs import (
    ProjectBrainEntity, TypedReference, canonical_hash, create_project_brain_entity,
    mark_reference_stale,
)
from .project_builder import (
    GenerationBudget, ProjectBuilder, ProjectGenerationPlan, GenerationResult,
    GENERATION_COMPLETE, GENERATION_PARTIAL,
)
from .repair_problem import PatchSearchBudget, RepairProblem
from .repo_intelligence import (
    RepoIntelligenceQuery, RepoIntelligenceResult, RepoIntelligenceBudget,
    search_repository,
)
from .repository_map import RepositoryMap, build_repository_map, incremental_reindex
from .task_working_set import TaskWorkingSet, WorkingSetBudget


CORE_INTEGRATION_VERSION = "HIVO-CORE-INTEGRATION-V1"
GENERATION_PROVIDER = "GENERATION_PROVIDER"
PATCH_PROVIDER = "PATCH_PROVIDER"
SEMANTIC_PROVIDER = "SEMANTIC_PROVIDER"
PROVIDER_ROLES = (GENERATION_PROVIDER, PATCH_PROVIDER, SEMANTIC_PROVIDER)

CORE_COMPLETE = "COMPLETE"
CORE_PARTIAL = "PARTIAL"
CORE_BLOCKED = "BLOCKED"


def _generation_failure_category(error: Mapping[str, Any]) -> str:
    """Preserve CORE-6 failure origin at the integration boundary."""
    status = str(error.get("status", "")).upper()
    detail = str(error.get("detail", error.get("reason", ""))).upper()
    text = f"{status} {detail}"
    if "V25_6" in text or "VERIFICATION" in text:
        return FINAL_VERIFICATION_FAILED
    if "V25_5" in text or "AUTHORITY" in text:
        return AUTHORITY_BLOCKED
    if "CONTRACT" in text:
        return CONTRACT_FAILURE
    if "INTEGRATION" in text:
        return INTEGRATION_FAILURE
    if "PROVIDER" in text or "OLLAMA" in text:
        return PROVIDER_FAILURE
    if "BUDGET" in text:
        return BUDGET_REACHED
    return GENERATION_UNIT_FAILED


def _map(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            data = value.to_dict()
        except TypeError:
            data = value.to_dict(include_hash=False)
        return dict(data) if isinstance(data, Mapping) else {}
    return {}


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict(include_hash=False)
        except TypeError:
            return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    return value


def _invoke(callback: Any, *args: Any, **kwargs: Any) -> Any:
    if callback is None:
        return None
    target = callback
    if not callable(target):
        for name in ("validate", "verify", "check", "run", "evaluate"):
            if hasattr(target, name):
                target = getattr(target, name)
                break
    if not callable(target):
        return None
    attempts = (
        lambda: target(*args, **kwargs),
        lambda: target(*args),
        lambda: target(args[0]) if args else target(),
        lambda: target(),
    )
    last: Exception | None = None
    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            last = exc
    return {"passed": False, "reason": f"callback signature rejected: {last}"} if last else None


def _bool_result(value: Any, *, default: bool = False) -> tuple[bool, dict[str, Any]]:
    if isinstance(value, bool):
        return value, {"passed": value}
    if value is None:
        return default, {"status": "NOT_RUN"}
    data = _map(value)
    if data:
        if str(data.get("status", "")).upper() in {"NOT_RUN", "SKIPPED", "NOT_CONFIGURED"}:
            return default, data
        return bool(data.get("passed", data.get("valid", data.get("success", data.get("ok", False))))), data
    return bool(value), {"value": str(value)}


def _safe_root(value: str | Path) -> Path:
    root = Path(value).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Core project root must be an existing directory")
    return root


def _safe_relative(root: Path, value: str | Path) -> str:
    raw = str(value or "").replace("\\", "/").strip()
    if not raw or raw.startswith("/") or (len(raw) > 1 and raw[1] == ":"):
        raise ValueError("project path must be relative")
    parts = tuple(item for item in raw.split("/") if item)
    if ".." in parts or any(item in {".git", ".agent_runs", ".agent_evidence", ".hivo", "output", "node_modules"} for item in parts):
        raise ValueError("project path targets a protected location")
    target = (root / raw).resolve()
    target.relative_to(root.resolve())
    return "/".join(parts)


def _clone_project(root: Path, destination: Path) -> None:
    """Clone a project for a gate, refusing symlink escapes."""
    destination.mkdir(parents=True, exist_ok=True)
    protected = {".git", ".agent_runs", ".agent_evidence", ".hivo", "output", "node_modules", "__pycache__"}
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        relative = current_path.relative_to(root)
        if any(part in protected for part in relative.parts):
            directories[:] = []
            continue
        for directory in directories:
            if (current_path / directory).is_symlink():
                raise ValueError(f"symlink directory is not allowed in Core staging: {current_path / directory}")
        directories[:] = sorted(item for item in directories if item not in protected)
        target_dir = destination / relative
        target_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            source = current_path / name
            if source.is_symlink():
                raise ValueError(f"symlink source is not allowed in Core staging: {source}")
            target = target_dir / name
            shutil.copy2(source, target)


def _copy_changed_files(source_root: Path, target_root: Path, paths: Iterable[str]) -> tuple[str, ...]:
    changed: list[str] = []
    for raw in sorted({str(item).replace("\\", "/") for item in paths}):
        relative = _safe_relative(target_root, raw)
        source = (source_root / relative).resolve()
        target = (target_root / relative).resolve()
        source.relative_to(source_root.resolve())
        target.relative_to(target_root.resolve())
        if not source.is_file():
            raise ValueError(f"staged changed path is missing: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        changed.append(relative)
    return tuple(changed)


def classify_core_task(
    task: str | Mapping[str, Any],
    *,
    project_root: str | Path | None = None,
    explicit_mode: str | None = None,
    blueprint: ProjectBlueprint | Mapping[str, Any] | None = None,
    failure_evidence: Any = None,
    repair_problem: RepairProblem | Mapping[str, Any] | None = None,
) -> str:
    """Classify only explicit deterministic signals; callers may override it."""
    raw = _map(task) if isinstance(task, Mapping) else {}
    selected = explicit_mode or raw.get("mode")
    if selected:
        value = str(selected).upper()
        if value not in EXECUTION_MODES:
            raise ValueError(f"unsupported Core execution mode: {value}")
        return value
    if repair_problem is not None or raw.get("repair_problem") is not None:
        return REPAIR
    if failure_evidence is not None or raw.get("failure_evidence") is not None:
        return DIAGNOSE
    if blueprint is not None or raw.get("blueprint") is not None:
        return BUILD
    return MAINTAIN


class _SemanticAccountingProxy:
    def __init__(self, coordinator: "CoreIntelligenceCoordinator", backend: Any) -> None:
        self.coordinator = coordinator
        self.backend = backend

    def search(self, query: RepoIntelligenceQuery, repository_map: RepositoryMap, budget: Any) -> Iterable[Mapping[str, Any]]:
        if not self.coordinator._consume_provider(SEMANTIC_PROVIDER, query.canonical_hash):
            return ()
        return self.backend.search(query, repository_map, budget)


class ModelPatchCandidateProviderAdapter:
    """Future patch-model adapter receiving only a bounded RepairEvidencePacket."""

    provider_id = "core-patch-provider-adapter"

    def __init__(self, provider: Any, coordinator: "CoreIntelligenceCoordinator") -> None:
        self.provider = provider
        self.coordinator = coordinator
        self.last_request: CoreProviderRequest | None = None

    def generate(self, repair_problem: RepairProblem, selected_source_evidence: Mapping[str, Any], *, limit: int, **kwargs: Any) -> Iterable[Any]:
        packet = repair_problem.evidence_packet
        request = CoreProviderRequest(
            request_id=f"{self.coordinator.execution_id or 'CORE-UNBOUND'}-PATCH-{self.coordinator.provider_request_count + 1}",
            role=PATCH_PROVIDER, execution_id=self.coordinator.execution_id or "CORE-UNBOUND",
            mode=self.coordinator.mode or REPAIR,
            operation_identity=repair_problem.canonical_hash,
            evidence_packet_hash=packet.canonical_hash,
            subject_identity=repair_problem.subject_identity,
            revision_identity=repair_problem.revision_identity,
            authority_identity=self.coordinator.authority_identity,
        )
        self.last_request = request
        if not self.coordinator._consume_provider(PATCH_PROVIDER, packet.canonical_hash):
            return ()
        bounded = dict(selected_source_evidence or {})
        bounded["repair_evidence_packet"] = packet.to_dict()
        bounded["source_slices"] = tuple(bounded.get("source_slices", ()))[:8]
        bounded["contracts"] = tuple(bounded.get("contracts", ()))[:8]
        target = getattr(self.provider, "generate", None) or getattr(self.provider, "propose", None) or self.provider
        if not callable(target):
            return ()
        try:
            return target(repair_problem, bounded, limit=int(limit))
        except TypeError:
            try:
                return target(repair_problem, bounded, int(limit))
            except TypeError:
                return target(repair_problem, bounded)


def adapt_candidate_failure_evidence(
    failure: CandidateFailureEvidence | Mapping[str, Any],
    *,
    subject_identity: str = "",
    revision_identity: str = "",
) -> FaultFailureEvidence:
    """Project CORE-5 failure evidence into CORE-4-compatible evidence."""
    current = failure if isinstance(failure, CandidateFailureEvidence) else CandidateFailureEvidence.from_value(failure)
    return FaultFailureEvidence(
        failure_id=f"candidate:{current.candidate_id}",
        failure_type=CORE4_INTEGRATION_FAILURE,
        message=current.reason,
        path=current.target_path,
        subject_identity=subject_identity or current.subject_hash,
        revision_identity=revision_identity,
        metadata={
            "candidate_id": current.candidate_id,
            "candidate_status": current.status,
            "stage": current.stage,
            "strategy": current.strategy,
            "changed_paths": list(current.changed_paths),
            "candidate_failure_evidence": current.to_dict(),
        },
    )


class CoreIntelligenceCoordinator:
    """Compose CORE-1 through CORE-6 under one bounded execution."""

    def __init__(
        self,
        project_root: str | Path,
        *,
        repository_map: RepositoryMap | Mapping[str, Any] | None = None,
        lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
        brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
        authority: Mapping[str, Any] | None = None,
        dnt_paths: Iterable[str] = (),
        budget: CoreBudget | Mapping[str, Any] | None = None,
        generation_provider: Any = None,
        patch_provider: Any = None,
        semantic_retriever: Any = None,
        diagnostic_engine: ExperimentalEvidenceEngine | None = None,
    ) -> None:
        self.project_root = _safe_root(project_root)
        self.authority = dict(authority or {})
        self.dnt_paths = tuple(sorted({_safe_relative(self.project_root, item) for item in dnt_paths}))
        self.budget = budget if isinstance(budget, CoreBudget) else CoreBudget(**dict(budget or {}))
        self.repository_map = repository_map if isinstance(repository_map, RepositoryMap) else (
            RepositoryMap.from_dict(repository_map, self.project_root) if repository_map is not None else build_repository_map(self.project_root)
        )
        self.lexical_index, _ = ensure_lexical_index(lexical_index, self.repository_map, self.project_root)
        self.brain_entities = tuple(
            item if isinstance(item, ProjectBrainEntity) else ProjectBrainEntity.from_dict(item)
            for item in brain_entities
        )
        if any(not item.created_from_verified_evidence for item in self.brain_entities):
            raise ValueError("Core integration accepts only verified reference-based Brain entities")
        self.generation_provider = generation_provider
        self.patch_provider = patch_provider
        self.semantic_retriever = semantic_retriever
        self.diagnostic_engine = diagnostic_engine
        self.execution_id = ""
        self.mode = ""
        self._execution_subject_identity = ""
        self._state: CoreExecutionState | None = None
        self._metrics: dict[str, Any] = new_core_metrics()
        self._component_results: dict[str, Any] = {}
        self._failure_evidence: list[dict[str, Any]] = []
        self._canonical_mutations: list[str] = []
        self._brain_updates: list[str] = []
        self._provider_requests: list[CoreProviderRequest] = []
        self._budget_usage: dict[str, int] = {}
        self._last_generation_builder: ProjectBuilder | None = None
        self._last_blueprint: ProjectBlueprint | None = None
        self._last_units: tuple[GenerationUnit, ...] = ()
        self._last_search: RepoIntelligenceResult | None = None
        self._last_localization: FaultLocalizationResult | None = None
        self._last_repair_problem: RepairProblem | None = None
        self._last_generation_contexts: dict[str, tuple[str, str, str, str]] = {}
        self._context_budget_exceeded = False

    @property
    def subject_identity(self) -> str:
        from .experiment_sandbox import canonical_subject_hash
        return canonical_subject_hash(self.project_root)

    @property
    def revision_identity(self) -> str:
        return self.repository_map.index_revision

    @property
    def authority_identity(self) -> str:
        return canonical_hash({"authority": self.authority, "dnt": list(self.dnt_paths)})

    @property
    def state(self) -> CoreExecutionState | None:
        return self._state

    @property
    def provider_request_count(self) -> int:
        return len(self._provider_requests)

    def _begin(self, task: str | Mapping[str, Any], mode: str) -> None:
        raw_task = _map(task) if isinstance(task, Mapping) else {"task": str(task)}
        task_text = str(raw_task.get("task", raw_task.get("raw_task_text", task if isinstance(task, str) else "")))
        execution_seed = {
            "task": task_text, "mode": mode, "subject": self.subject_identity,
            "revision": self.revision_identity, "ordinal": self._metrics.get("core_executions", 0) + 1,
        }
        self.execution_id = "CORE-EXEC-" + canonical_hash(execution_seed)[:20]
        self.mode = mode
        self._execution_subject_identity = self.subject_identity
        self._metrics = new_core_metrics()
        self._metrics["core_executions"] = 1
        self._metrics[f"{mode.casefold()}_executions"] = 1
        self._component_results = {}
        self._failure_evidence = []
        self._canonical_mutations = []
        self._brain_updates = []
        self._provider_requests = []
        self._budget_usage = {}
        self._last_search = None
        self._last_localization = None
        self._last_repair_problem = None
        self._last_generation_contexts = {}
        self._context_budget_exceeded = False
        self._state = CoreExecutionState(
            execution_id=self.execution_id, mode=mode,
            subject_identity=self.subject_identity, revision_identity=self.revision_identity,
            authority_identity=self.authority_identity, authority_state={
                "scope_hash": canonical_hash(self.authority), "dnt": list(self.dnt_paths),
                "authority_widening_allowed": False,
            }, verification_state={"required": mode in {BUILD, REPAIR}, "full_v25_6_passed": False},
        )

    def _transition(self, phase: str, **updates: Any) -> bool:
        if self._state is None:
            raise RuntimeError("Core execution has not started")
        if self._budget_usage.get("core_stages", 0) >= self.budget.max_core_stages and phase != BLOCKED:
            self._metrics["budget_stops"] += 1
            self._budget_usage["core_stages"] = self._budget_usage.get("core_stages", 0) + 1
            self._state = self._state.transition(BLOCKED, terminal_reason=BUDGET_REACHED)
            return False
        self._budget_usage["core_stages"] = self._budget_usage.get("core_stages", 0) + 1
        self._metrics["core_stages"] = self._budget_usage["core_stages"]
        if phase != BLOCKED:
            try:
                self._state = self._state.transition(phase, **updates)
            except ValueError:
                self._state = self._state.transition(BLOCKED, terminal_reason=INTEGRATION_FAILURE)
                self._metrics["budget_stops"] += 1
                return False
        else:
            self._state = self._state.transition(BLOCKED, **updates)
        return True

    def _consume_provider(self, role: str, evidence_hash: str) -> bool:
        if self._budget_usage.get("provider_requests", 0) >= self.budget.max_provider_requests:
            self._metrics["budget_stops"] += 1
            return False
        self._budget_usage["provider_requests"] = self._budget_usage.get("provider_requests", 0) + 1
        self._metrics["provider_requests"] = self._budget_usage["provider_requests"]
        request = CoreProviderRequest(
            request_id=f"{self.execution_id or 'CORE-UNBOUND'}-PROVIDER-{len(self._provider_requests) + 1}",
            role=role, execution_id=self.execution_id or "CORE-UNBOUND", mode=self.mode or MAINTAIN,
            operation_identity=evidence_hash, evidence_packet_hash=evidence_hash,
            subject_identity=self.subject_identity, revision_identity=self.revision_identity,
            authority_identity=self.authority_identity,
        )
        self._provider_requests.append(request)
        self._metrics["provider_calls"] = self._metrics.get("provider_calls", 0) + 1
        return True

    def _bounded_v25_6(self, verifier: Any, *args: Any) -> tuple[bool, dict[str, Any]]:
        if verifier is None:
            return False, {"status": "V25_6_REQUIRED"}
        if self._budget_usage.get("full_verification_attempts", 0) >= self.budget.max_full_verification_attempts:
            self._metrics["budget_stops"] += 1
            return False, {"status": BUDGET_REACHED, "reason": "full verification budget"}
        self._budget_usage["full_verification_attempts"] = self._budget_usage.get("full_verification_attempts", 0) + 1
        self._metrics["full_verification_attempts"] = self._budget_usage["full_verification_attempts"]
        self._metrics["v25_6_attempts"] += 1
        self._metrics["full_verification_runs"] += 1
        passed, data = _bool_result(_invoke(verifier, *args), default=False)
        return passed, data

    def _result(
        self,
        *,
        status: str,
        next_action: str,
        reason: str = "",
        verification_state: Mapping[str, Any] | None = None,
        unresolved: Iterable[Mapping[str, Any]] = (),
    ) -> CoreExecutionResult:
        if self._state is None:
            raise RuntimeError("Core execution has not started")
        state = self._state
        verification = dict(verification_state or state.verification_state)
        if verification != state.verification_state:
            state = state.with_updates(verification_state=verification)
            self._state = state
        provider_accounting = {
            "generation_requests": sum(1 for item in self._provider_requests if item.role == GENERATION_PROVIDER),
            "patch_requests": sum(1 for item in self._provider_requests if item.role == PATCH_PROVIDER),
            "semantic_requests": sum(1 for item in self._provider_requests if item.role == SEMANTIC_PROVIDER),
            "total_requests": len(self._provider_requests),
            "fake_provider_calls": sum(1 for item in self._provider_requests if item.role in {GENERATION_PROVIDER, PATCH_PROVIDER, SEMANTIC_PROVIDER}),
        }
        lift = core_autonomy_lift(
            naive_success=False,
            integrated_success=status == CORE_COMPLETE,
            provider_requests=provider_accounting["total_requests"],
        )
        self._metrics["CORE_AUTONOMY_LIFT"] = lift
        self._metrics["core_autonomy_lift"] = int(lift["CORE_AUTONOMY_LIFT"])
        after = self.subject_identity
        before = self._execution_subject_identity or state.subject_identity
        return CoreExecutionResult(
            execution_id=self.execution_id, mode=self.mode, status=status, state=state,
            phases_visited=state.phases_visited, component_results=self._component_results,
            provider_accounting=provider_accounting, budget_usage=dict(self._budget_usage),
            canonical_mutations=tuple(sorted(set(self._canonical_mutations))),
            verification_state=verification, index_updates=dict(self._component_results.get("index_updates", {})),
            brain_updates=tuple(self._brain_updates), failure_evidence=tuple(self._failure_evidence),
            recommended_next_action=next_action, metrics=dict(self._metrics),
            unresolved_evidence=tuple(dict(item) for item in unresolved),
            source_unchanged=before == after, reason=reason,
        )

    def _block(self, category: str, reason: str, *, next_action: str = NEXT_BLOCKED, detail: Mapping[str, Any] | None = None) -> CoreExecutionResult:
        self._failure_evidence.append({"category": category, "reason": reason, "detail": dict(detail or {})})
        if self._state is not None and self._state.current_phase not in {COMPLETE, BLOCKED}:
            self._transition(BLOCKED, terminal_reason=category)
        return self._result(status=CORE_BLOCKED, next_action=next_action, reason=reason)

    def inspect_task_context(
        self,
        task: str | RepoIntelligenceQuery,
        *,
        semantic_retriever: Any = None,
        requested_detail: int | None = None,
    ) -> RepoIntelligenceResult:
        if self._state is None:
            raise RuntimeError("inspect_task_context must be called through an execution or after begin")
        if self._state.current_phase == INITIALIZING:
            self._transition(CONTEXT_BUILDING)
        integration_budget = WorkingSetBudget(
            max_files=self.budget.max_context_files,
            max_source_characters=self.budget.max_context_source_characters,
            max_search_stages=min(5, self.budget.max_core_stages),
            max_full_file_reads=min(2, self.budget.max_context_files),
            max_graph_nodes=min(12, self.budget.max_context_files),
            max_dependency_files=min(8, self.budget.max_context_files),
        )
        query = task if isinstance(task, RepoIntelligenceQuery) else RepoIntelligenceQuery.from_task(
            str(task), subject_identity=self.subject_identity, revision_identity=self.revision_identity,
            budget=integration_budget,
        )
        if isinstance(query, RepoIntelligenceQuery):
            query_budget = query.budget
            query = replace(query, budget=WorkingSetBudget(
                max_primary_items=min(query_budget.max_primary_items, integration_budget.max_primary_items),
                max_supporting_items=min(query_budget.max_supporting_items, integration_budget.max_supporting_items),
                max_tests=min(query_budget.max_tests, integration_budget.max_tests),
                max_files=min(query_budget.max_files, integration_budget.max_files),
                max_symbols=min(query_budget.max_symbols, integration_budget.max_symbols),
                max_source_characters=min(query_budget.max_source_characters, integration_budget.max_source_characters),
                max_full_file_reads=min(query_budget.max_full_file_reads, integration_budget.max_full_file_reads),
                max_search_stages=min(query_budget.max_search_stages, integration_budget.max_search_stages),
                max_graph_depth=min(query_budget.max_graph_depth, integration_budget.max_graph_depth),
                max_graph_nodes=min(query_budget.max_graph_nodes, integration_budget.max_graph_nodes),
                max_dependency_files=min(query_budget.max_dependency_files, integration_budget.max_dependency_files),
                max_candidates=min(query_budget.max_candidates, integration_budget.max_candidates),
                max_lexical_results=min(query_budget.max_lexical_results, integration_budget.max_lexical_results),
            ))
        if requested_detail is not None:
            query = replace(query, requested_detail=max(0, int(requested_detail)))
        if self.budget.max_working_set_expansions <= 0 and query.requested_detail >= 3:
            query = replace(query, requested_detail=2)
        backend = semantic_retriever if semantic_retriever is not None else self.semantic_retriever
        proxy = _SemanticAccountingProxy(self, backend) if backend is not None else None
        search = search_repository(
            query, self.repository_map, self.project_root,
            brain_entities=self.brain_entities, lexical_index=self.lexical_index,
            semantic_retriever=proxy, authority=self.authority,
        )
        self._last_search = search
        self._component_results["core2"] = search
        if search.working_set is not None:
            self._metrics["working_sets_created"] += 1
            self._metrics["mean_working_set_files"] = len(search.working_set.files)
            self._metrics["mean_working_set_source_characters"] = int(search.working_set.budget_usage.get("source_characters_loaded", 0))
            expansion_used = int(bool(search.working_set.expansion_history))
            self._budget_usage["working_set_expansions"] = self._budget_usage.get("working_set_expansions", 0) + max(
                expansion_used, int(search.metrics.get("working_set_expansions", 0))
            )
            self._metrics["working_set_expansions"] = self._budget_usage["working_set_expansions"]
            if self._budget_usage["working_set_expansions"] > self.budget.max_working_set_expansions:
                self._context_budget_exceeded = True
                self._metrics["budget_stops"] += 1
            self._state = self._state.with_updates(working_set_identity=search.working_set.canonical_hash)
        self._metrics["full_repository_context_loads"] = 0
        self._metrics["legacy_exploration_operations_avoided"] += 1
        return search

    def _failure_rows(self, failure_evidence: Any) -> tuple[FaultFailureEvidence, ...]:
        if isinstance(failure_evidence, (FaultFailureEvidence, CandidateFailureEvidence, Mapping)):
            values = (failure_evidence,)
        else:
            values = tuple(failure_evidence or ())
        rows: list[FaultFailureEvidence] = []
        for value in values:
            if isinstance(value, CandidateFailureEvidence):
                row = adapt_candidate_failure(value, subject_identity=self.subject_identity, revision_identity=self.revision_identity)
            else:
                row = FaultFailureEvidence.from_value(value)
            if not row.subject_identity or not row.revision_identity:
                row = replace(
                    row,
                    subject_identity=row.subject_identity or self.subject_identity,
                    revision_identity=row.revision_identity or self.revision_identity,
                )
            rows.append(row)
        return tuple(rows)

    def diagnose_current_failure(
        self,
        task: str,
        failure_evidence: Any,
        *,
        experiments: Iterable[Any] = (),
        runner: Any = None,
        confirmation_runner: Any = None,
        run_experiments: bool | None = None,
    ) -> CoreExecutionResult:
        return self.execute(
            task, mode=DIAGNOSE, failure_evidence=failure_evidence,
            diagnostic_experiments=experiments, diagnostic_runner=runner,
            diagnostic_confirmation_runner=confirmation_runner,
            run_experiments=run_experiments,
        )

    def _should_run_experiments(
        self,
        localization: FaultLocalizationResult,
        *,
        explicit: bool | None,
        candidate_failures: Iterable[CandidateFailureEvidence] = (),
    ) -> tuple[bool, tuple[str, ...]]:
        reasons: list[str] = []
        if explicit is True:
            reasons.append("caller_requested_diagnostics")
        if localization.recommended_next_action == RUN_DIAGNOSTIC_EXPERIMENTS:
            reasons.append("CORE4_recommended_diagnostics")
        candidates = localization.top_candidates
        if len(candidates) >= 2:
            first, second = candidates[0], candidates[1]
            close = abs(float(first.score) - float(second.score)) <= max(1.0, abs(float(first.score)) * 0.15)
            low_confidence = str(first.confidence_class).upper() in {"LOW", "MEDIUM"} or str(second.confidence_class).upper() in {"LOW", "MEDIUM"}
            if close and low_confidence:
                reasons.append("close_low_confidence_top_candidates")
        if localization.unresolved_evidence:
            reasons.append("localization_has_unresolved_evidence")
        if any(item.contradicting_evidence_ids for item in candidates):
            reasons.append("contradictory_localization_evidence")
        failures = tuple(candidate_failures)
        if len(failures) >= 2 and len({item.target_path for item in failures if item.target_path}) > 1:
            reasons.append("candidate_failures_in_multiple_plausible_areas")
        return (bool(reasons) if explicit is not False else False), tuple(sorted(set(reasons)))

    def _localize(
        self,
        task: str,
        failure_evidence: Any,
        working_set: TaskWorkingSet | None,
        *,
        experimental_evidence: Any = None,
        change_evidence: Any = None,
    ) -> FaultLocalizationResult:
        failures = self._failure_rows(failure_evidence)
        request = build_fault_localization_request(
            task, failures, subject_identity=self.subject_identity,
            revision_identity=self.revision_identity,
            working_set_identity=working_set.canonical_hash if working_set else "",
            authority_context=self.authority, dnt_context=self.dnt_paths,
            budget=LocalizationBudget(),
        )
        engine = FaultLocalizationEngine(
            self.repository_map, self.project_root, lexical_index=self.lexical_index,
            brain_entities=self.brain_entities, authority=self.authority,
            dnt_paths=self.dnt_paths, budget=request.budget,
        )
        localization = engine.localize(
            request, working_set=working_set,
            experimental_evidence=experimental_evidence,
            change_evidence=change_evidence,
        )
        self._last_localization = localization
        self._component_results["core4"] = localization
        self._metrics["localization_runs"] += 1
        self._state = self._state.with_updates(localization_identity=localization.canonical_hash)
        return localization

    def _run_diagnostics(
        self,
        task: str,
        failure_evidence: Any,
        working_set: TaskWorkingSet | None,
        experiments: Iterable[Any],
        *,
        runner: Any = None,
        confirmation_runner: Any = None,
    ) -> DiagnosticResult | None:
        if self._budget_usage.get("diagnostic_rounds", 0) >= self.budget.max_diagnostic_rounds:
            self._metrics["budget_stops"] += 1
            return None
        if callable(experiments):
            experiment_values: tuple[Any, ...] | Callable[..., Any] = experiments
        else:
            experiment_values = tuple(experiments or ())
        if not experiment_values:
            return None
        self._budget_usage["diagnostic_rounds"] = self._budget_usage.get("diagnostic_rounds", 0) + 1
        self._metrics["diagnostic_cycles"] += 1
        self._transition(EXPERIMENTING)
        engine = self.diagnostic_engine or ExperimentalEvidenceEngine(
            self.project_root, repository_map=self.repository_map, working_set=working_set,
            authority=self.authority, dnt_paths=self.dnt_paths,
            budget={"max_total_experiments": min(6, max(1, self.budget.max_diagnostic_rounds))},
            runner=runner,
        )
        failures = self._failure_rows(failure_evidence)
        session = engine.create_session(
            task, failures, subject_identity=self.subject_identity,
            revision_identity=self.revision_identity,
        )
        if callable(experiment_values):
            experiment_values = tuple(experiment_values(session))
        result = engine.run(
            session, experiment_values, runner=runner,
            confirmation_runner=confirmation_runner,
        )
        self._component_results["core3"] = result
        self._metrics["diagnostic_sessions"] += 1
        self._metrics["experiments_executed"] += len(result.experiments_executed)
        self._metrics["deterministic_diagnostic_steps"] += len(result.experiments_executed)
        self._metrics["masking_risks_detected"] += len(result.masking_risks)
        self._metrics["experiments_to_narrow"] = len(result.experiments_executed)
        if self._state is not None:
            self._state = self._state.with_updates(diagnostic_identity=result.canonical_hash)
        return result

    def _repair_problem_from_localization(
        self,
        task: str,
        localization: FaultLocalizationResult,
        working_set: TaskWorkingSet | None,
        *,
        blueprint: ProjectBlueprint | None = None,
        candidate_budget: PatchSearchBudget | Mapping[str, Any] | None = None,
    ) -> RepairProblem:
        contracts = ()
        invariants = ()
        if blueprint is not None:
            contracts = tuple(item.to_dict(include_hash=False) for item in blueprint.module_contracts)
            invariants = tuple({"statement": item} for item in blueprint.global_invariants)
        return RepairProblem.from_localization(
            localization, task_identity=task, repair_id=f"{self.execution_id}-REPAIR",
            working_set=working_set, contracts=contracts, invariants=invariants,
            authority_context=self.authority, dnt_context=self.dnt_paths,
            candidate_budget=candidate_budget or PatchSearchBudget(),
            project_root=str(self.project_root),
        )

    def search_repair_candidates(
        self,
        problem: RepairProblem | Mapping[str, Any],
        *,
        targeted_checker: Any = None,
        guard_checker: Any = None,
        contract_checker: Any = None,
        v25_5_gate: Any = None,
        v25_6_verifier: Any = None,
        use_model_provider: bool = True,
    ) -> PatchSearchResult:
        current = problem if isinstance(problem, RepairProblem) else RepairProblem.from_value(problem)
        if current.subject_identity and current.subject_identity != self.subject_identity:
            raise ValueError(STALE_CONTEXT)
        if self._budget_usage.get("patch_search_sessions", 0) >= self.budget.max_patch_search_sessions:
            raise RuntimeError(BUDGET_REACHED)
        self._budget_usage["patch_search_sessions"] = self._budget_usage.get("patch_search_sessions", 0) + 1
        self._metrics["patch_search_sessions"] += 1
        adapter = ModelPatchCandidateProviderAdapter(self.patch_provider, self) if self.patch_provider is not None and use_model_provider else None
        remaining_verification = max(0, self.budget.max_full_verification_attempts - self._budget_usage.get("full_verification_attempts", 0) - 1)
        bounded_problem = current
        if v25_6_verifier is not None:
            bounded_problem = replace(
                current,
                candidate_budget=replace(
                    current.candidate_budget,
                    max_full_v25_6_candidates=min(current.candidate_budget.max_full_v25_6_candidates, remaining_verification),
                ),
            )
        result = search_patch_candidates(
            bounded_problem, self.project_root, targeted_checker=targeted_checker,
            guard_checker=guard_checker, contract_checker=contract_checker,
            v25_5_gate=v25_5_gate,
            v25_6_verifier=(lambda *args: self._bounded_v25_6(v25_6_verifier, *args)[0]) if v25_6_verifier is not None else None,
            model_provider=adapter, repository_map=self.repository_map, lexical_index=self.lexical_index,
        )
        self._last_repair_problem = bounded_problem
        self._component_results["core5"] = result
        self._metrics["provider_requests_per_repair"] = int(self._budget_usage.get("provider_requests", 0))
        self._metrics["patch_candidates_generated"] += len(result.generated_candidates)
        self._metrics["model_candidates_rejected"] += int(result.metrics.get("authority_blocked_candidates", 0))
        self._metrics["model_candidates_accepted"] += int(result.metrics.get("model_candidates", 0))
        if result.winner is not None and result.winner.status == VERIFIED:
            self._metrics["bounded_patch_search_success"] += 1
        if adapter is None and result.winner is not None:
            self._metrics["deterministic_repairs_without_provider"] += 1
        for failure in result.rejected_candidates:
            self._failure_evidence.append({"category": PATCH_VERIFICATION_FAILED, "evidence": failure.to_dict()})
        self._state = self._state.with_updates(patch_search_identity=result.canonical_hash)
        return result

    def _brain_update_for_patch(self, candidate: PatchCandidate) -> tuple[str, ...]:
        changed = set(candidate.changed_paths)
        updated: list[ProjectBrainEntity] = []
        for entity in self.brain_entities:
            entity_paths = {ref.path for ref in entity.references if ref.path}
            updated.append(mark_reference_stale(entity) if entity_paths & changed else entity)
        references = [TypedReference("file", path, verified_revision=self.revision_identity) for path in sorted(changed)]
        if candidate.target_symbol and candidate.target_path:
            references.append(TypedReference("symbol", candidate.target_path, candidate.target_symbol, verified_revision=self.revision_identity))
        entity = create_project_brain_entity(
            entity_id=f"core-integration:{self.execution_id}:{candidate.candidate_id}",
            entity_kind="FILE", name=candidate.target_symbol or candidate.target_path,
            summary="Verified reference-based maintenance update",
            references=tuple(references), contracts=tuple(candidate.hypothesis_ids),
            verified_subject_identity=self.subject_identity,
            verified_revision_identity=self.revision_identity,
            verified_source_hashes={path: self.repository_map.files.get(path, {}).get("content_hash", "") for path in changed},
            created_from_verified_evidence=True,
        )
        updated.append(entity)
        self.brain_entities = tuple(updated)
        self._brain_updates.append(entity.entity_id)
        self._metrics["verified_brain_updates"] += 1
        return (entity.entity_id,)

    def apply_patch_candidate(
        self,
        candidate: PatchCandidate | Mapping[str, Any],
        *,
        v25_5_gate: Any,
        v25_6_verifier: Any,
        selected_candidate_id: str | None = None,
    ) -> dict[str, Any]:
        selected = candidate if isinstance(candidate, PatchCandidate) else PatchCandidate.from_value(candidate)
        if selected_candidate_id and selected.candidate_id != selected_candidate_id:
            return {"applied": False, "status": AUTHORITY_BLOCKED, "reason": "candidate selection identity mismatch"}
        if selected.status not in {VIABLE, VERIFIED}:
            return {"applied": False, "status": NO_VIABLE_PATCH, "reason": "candidate is not viable"}
        if v25_5_gate is None or v25_6_verifier is None:
            return {"applied": False, "status": FINAL_VERIFICATION_FAILED, "reason": "V25.5 and V25.6 are both required"}
        with tempfile.TemporaryDirectory(prefix="hivo_core_patch_stage_") as directory:
            stage = Path(directory) / "subject"
            _clone_project(self.project_root, stage)
            staged = apply_selected_patch_candidate(
                selected, stage, authority=self.authority, dnt_paths=self.dnt_paths,
                expected_subject_hash=self.subject_identity,
                current_revision_identity=self.revision_identity,
                v25_5_gate=v25_5_gate,
            )
            if not staged.get("applied"):
                return {"applied": False, "status": PATCH_VERIFICATION_FAILED, "detail": staged}
            verified, verification = self._bounded_v25_6(v25_6_verifier, selected, stage)
            if not verified:
                self._metrics["failed_repairs"] += 1
                return {"applied": False, "status": FINAL_VERIFICATION_FAILED, "detail": verification}
            changed = _copy_changed_files(stage, self.project_root, selected.changed_paths)
        map_metrics: dict[str, int] = {}
        lexical_metrics: dict[str, int] = {}
        self.repository_map = incremental_reindex(self.repository_map, self.project_root, changed_paths=changed, metrics=map_metrics)
        self.lexical_index = ensure_lexical_index(
            self.lexical_index, self.repository_map, self.project_root,
            changed_paths=changed, metrics=lexical_metrics,
        )[0]
        self._metrics["repository_map_incremental_updates"] += int(map_metrics.get("files_reparsed", map_metrics.get("incremental_files_reparsed", len(changed))))
        self._metrics["lexical_incremental_updates"] += int(lexical_metrics.get("documents_updated", len(changed)))
        self._metrics["canonical_mutations"] += len(changed)
        self._canonical_mutations.extend(changed)
        brain = self._brain_update_for_patch(selected)
        self._metrics["successful_repairs"] += 1
        self._component_results["index_updates"] = {"repo_map": map_metrics, "lexical": lexical_metrics}
        if self._state is not None:
            self._state = self._state.with_updates(
                subject_identity=self.subject_identity,
                revision_identity=self.revision_identity,
            )
        return {
            "applied": True, "status": "VERIFIED_PATCH_APPLIED", "changed_paths": list(changed),
            "verification": verification, "brain_updates": list(brain),
            "subject_identity": self.subject_identity, "repo_map_hash": self.repository_map.logical_hash,
            "lexical_index_hash": self.lexical_index.logical_hash,
        }

    def request_generation_unit_context(self, unit_id: str) -> GenerationEvidencePacket:
        if self._last_generation_builder is None:
            raise ValueError("no generation plan is active")
        unit = self._last_generation_builder.plan.unit_by_id.get(str(unit_id))
        if unit is None:
            raise KeyError(unit_id)
        packet = self._last_generation_builder.build_packet(unit)
        if sum(len(str(item)) for item in packet.to_dict().values()) > self.budget.max_context_source_characters:
            raise ValueError(BUDGET_REACHED)
        self._last_generation_contexts[unit.unit_id] = (
            packet.packet_id, self.subject_identity, self.revision_identity,
            self._last_generation_builder.blueprint.canonical_hash,
        )
        return packet

    def submit_generation_candidate(
        self,
        unit_id: str,
        candidate: GeneratedArtifactCandidate | Mapping[str, Any],
        *,
        apply: bool = False,
        v25_5_validator: Any = None,
        v25_6_verifier: Any = None,
    ) -> dict[str, Any]:
        if self._last_generation_builder is None:
            raise ValueError("no generation plan is active")
        unit = self._last_generation_builder.plan.unit_by_id.get(str(unit_id))
        if unit is None:
            raise KeyError(unit_id)
        current_candidate = candidate if isinstance(candidate, GeneratedArtifactCandidate) else GeneratedArtifactCandidate.from_value(candidate)
        packet_context = self._last_generation_contexts.get(unit.unit_id)
        if packet_context is not None:
            packet_id, packet_subject, packet_revision, packet_blueprint = packet_context
            if (
                self.subject_identity != packet_subject
                or self.revision_identity != packet_revision
                or self._last_generation_builder.blueprint.canonical_hash != packet_blueprint
                or (current_candidate.packet_id and current_candidate.packet_id != packet_id)
            ):
                return {"valid": False, "status": STALE_CONTEXT, "reason": "GenerationEvidencePacket is stale"}
        for path, expected_hash in current_candidate.base_source_hashes:
            target = (self.project_root / path).resolve()
            try:
                target.relative_to(self.project_root.resolve())
            except ValueError:
                return {"valid": False, "status": AUTHORITY_BLOCKED, "reason": f"candidate path escapes project root: {path}"}
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != expected_hash:
                return {"valid": False, "status": STALE_CONTEXT, "reason": f"candidate base source is stale: {path}"}
        from .project_builder import validate_generated_artifact_candidate
        result = validate_generated_artifact_candidate(
            self.project_root, self._last_generation_builder.blueprint, unit, current_candidate,
            authority=self.authority, dnt_paths=self.dnt_paths,
        )
        if apply and result.get("valid"):
            if v25_5_validator is None or v25_6_verifier is None:
                result["application"] = {
                    "applied": False, "status": FINAL_VERIFICATION_FAILED,
                    "reason": "V25.5 and V25.6 are both required for canonical generation application",
                }
                return result
            with tempfile.TemporaryDirectory(prefix="hivo_core_generation_stage_") as directory:
                stage = Path(directory) / "subject"
                _clone_project(self.project_root, stage)
                stage_builder = ProjectBuilder(
                    stage, self._last_generation_builder.blueprint, (unit,),
                    repository_map=build_repository_map(stage),
                    authority=self.authority, dnt_paths=self.dnt_paths,
                    budget=self._last_generation_builder.budget,
                )
                staged = stage_builder.apply_verified_candidate(
                    current_candidate, unit, v25_5_validator=v25_5_validator,
                )
                if not staged.get("applied"):
                    result["application"] = staged
                    return result
                passed, verification = self._bounded_v25_6(v25_6_verifier, current_candidate, stage)
                if not passed:
                    result["application"] = {
                        "applied": False, "status": FINAL_VERIFICATION_FAILED,
                        "verification": verification,
                    }
                    return result
                changed = _copy_changed_files(stage, self.project_root, current_candidate.target_paths)
            map_metrics: dict[str, int] = {}
            lexical_metrics: dict[str, int] = {}
            self.repository_map = incremental_reindex(self.repository_map, self.project_root, changed_paths=changed, metrics=map_metrics)
            self.lexical_index = ensure_lexical_index(
                self.lexical_index, self.repository_map, self.project_root,
                changed_paths=changed, metrics=lexical_metrics,
            )[0]
            self._canonical_mutations.extend(changed)
            self._metrics["canonical_mutations"] += len(changed)
            self._metrics["repository_map_incremental_updates"] += int(map_metrics.get("files_reparsed", len(changed)))
            self._metrics["lexical_incremental_updates"] += int(lexical_metrics.get("documents_updated", len(changed)))
            self._metrics["verified_brain_updates"] += 1
            brain_entity = stage_builder._brain_entity_for_unit(unit, current_candidate)
            if brain_entity is not None:
                self.brain_entities = tuple(item for item in self.brain_entities if item.entity_id != brain_entity.entity_id) + (brain_entity,)
                self._brain_updates.append(brain_entity.entity_id)
            if self._state is not None:
                self._state = self._state.with_updates(
                    subject_identity=self.subject_identity,
                    revision_identity=self.revision_identity,
                )
            result["application"] = {
                "applied": True, "status": "VERIFIED_GENERATION_APPLIED",
                "changed_paths": list(changed), "verification": verification,
                "repo_map_hash": self.repository_map.logical_hash,
                "lexical_index_hash": self.lexical_index.logical_hash,
                "brain_update": brain_entity.entity_id if brain_entity is not None else "",
            }
        return result

    def submit_patch_candidate(
        self,
        candidate: PatchCandidate | Mapping[str, Any],
        *,
        apply: bool = False,
        v25_5_gate: Any = None,
        v25_6_verifier: Any = None,
    ) -> dict[str, Any]:
        """Receive a bounded CORE-5 proposal without granting it authority."""
        selected = candidate if isinstance(candidate, PatchCandidate) else PatchCandidate.from_value(candidate)
        if selected.base_subject_hash and selected.base_subject_hash != self.subject_identity:
            return {"accepted": False, "applied": False, "status": STALE_CONTEXT, "reason": "patch candidate base subject is stale"}
        if not apply:
            return {
                "accepted": True, "applied": False, "verified": False,
                "status": "PROPOSAL_RECEIVED", "candidate_id": selected.candidate_id,
                "authority_label": selected.target_authority,
                "reason": "proposal requires explicit caller application and existing safety gates",
            }
        applied = self.apply_patch_candidate(
            selected, v25_5_gate=v25_5_gate, v25_6_verifier=v25_6_verifier,
            selected_candidate_id=selected.candidate_id,
        )
        return {"accepted": bool(applied.get("applied")), "verified": bool(applied.get("applied")), **applied}

    def legacy_tool_fallback(self, context_result: RepoIntelligenceResult | Mapping[str, Any], fallback: Callable[..., Any] | None = None) -> Any:
        data = _map(context_result)
        unresolved = list(data.get("unresolved_evidence", ()))
        insufficient = str(data.get("early_stop_reason", "")).startswith(CONTEXT_INSUFFICIENT) or any(
            str(item.get("reason", "")) == "context_insufficient" for item in unresolved if isinstance(item, Mapping)
        )
        if insufficient and fallback is not None:
            return fallback()
        return {"status": "CORE_CONTEXT_SUFFICIENT", "fallback_called": False}

    def build(
        self,
        task: str,
        blueprint: ProjectBlueprint | Mapping[str, Any],
        units: Iterable[GenerationUnit | Mapping[str, Any]] | None = None,
        *,
        generation_provider: Any = None,
        authority: Mapping[str, Any] | None = None,
        generation_budget: GenerationBudget | None = None,
        contract_validator: Any = None,
        test_validator: Any = None,
        integration_validator: Any = None,
        v25_5_validator: Any = None,
        v25_6_validator: Any = None,
        checkpoint: Any = None,
    ) -> CoreExecutionResult:
        self._begin(task, BUILD)
        if authority is not None and canonical_hash(dict(authority)) != canonical_hash(self.authority):
            return self._block(AUTHORITY_BLOCKED, "per-execution authority replacement is not permitted", next_action=NEXT_REQUEST_BROADER_AUTHORITY)
        current_blueprint = blueprint if isinstance(blueprint, ProjectBlueprint) else ProjectBlueprint.from_value(blueprint)
        current_units = tuple(item if isinstance(item, GenerationUnit) else GenerationUnit.from_value(item) for item in (units or ()))
        if len(current_units) > self.budget.max_generation_units:
            return self._block(BUDGET_REACHED, "generation unit budget exceeded", next_action=NEXT_BUDGET_REACHED)
        self._last_blueprint, self._last_units = current_blueprint, current_units
        self._transition(PLANNING)
        provider = generation_provider if generation_provider is not None else self.generation_provider
        if provider is None:
            return self._block(PROVIDER_FAILURE, "no generation provider configured", next_action=NEXT_NEEDS_MODEL_PROPOSAL)
        stage_budget = generation_budget or GenerationBudget()
        stage_budget = replace(stage_budget, max_units=min(stage_budget.max_units, self.budget.max_generation_units), max_provider_calls=min(stage_budget.max_provider_calls, self.budget.max_provider_requests))
        self._transition(GENERATING, generation_plan_identity=canonical_hash({"blueprint": current_blueprint.canonical_hash, "units": [item.to_dict() for item in current_units]}))
        before = self.subject_identity
        with tempfile.TemporaryDirectory(prefix="hivo_core_build_stage_") as directory:
            stage = Path(directory) / "subject"
            _clone_project(self.project_root, stage)
            stage_builder = ProjectBuilder(
                stage, current_blueprint, current_units, provider=provider,
                authority=self.authority, dnt_paths=self.dnt_paths,
                budget=stage_budget, brain_entities=self.brain_entities,
            )
            self._last_generation_builder = stage_builder
            generation = stage_builder.generate(
                checkpoint=checkpoint, apply_verified=True,
                contract_validator=contract_validator, test_validator=test_validator,
                integration_validator=integration_validator,
                v25_5_validator=v25_5_validator, v25_6_validator=(lambda *args: self._bounded_v25_6(v25_6_validator, *args)[0]) if v25_6_validator is not None else None,
            )
            self._component_results["core6"] = generation
            self._metrics["generation_units_processed"] += len(generation.plan.units)
            provider_calls = int(generation.metrics.provider_calls)
            self._metrics["provider_requests_per_build_unit"] = provider_calls
            self._metrics["generation_packet_characters"] = int(generation.metrics.source_characters_generated)
            self._metrics["provider_requests"] += provider_calls
            self._budget_usage["provider_requests"] = provider_calls
            for ordinal in range(provider_calls):
                self._provider_requests.append(CoreProviderRequest(
                    request_id=f"{self.execution_id}-GENERATION-{ordinal + 1}",
                    role=GENERATION_PROVIDER, execution_id=self.execution_id, mode=BUILD,
                    operation_identity=generation.plan.canonical_hash,
                    evidence_packet_hash=generation.plan.canonical_hash,
                    subject_identity=before, revision_identity=self.revision_identity,
                    authority_identity=self.authority_identity,
                ))
            self._budget_usage["generation_units"] = len(generation.plan.units)
            self._budget_usage["generation_provider_requests"] = provider_calls
            self._state = self._state.with_updates(
                generation_plan_identity=generation.plan.canonical_hash,
                checkpoint_identity=(generation.checkpoints[-1].canonical_hash if generation.checkpoints else ""),
            )
            if generation.status != GENERATION_COMPLETE or not generation.integration_receipt.get("full_v25_6"):
                self._failure_evidence.extend(
                    {"category": _generation_failure_category(error), "error": dict(error)}
                    for error in generation.errors
                )
                if not generation.errors:
                    self._failure_evidence.append({
                        "category": _generation_failure_category(generation.integration_receipt),
                        "error": dict(generation.integration_receipt),
                    })
                return self._block(
                    _generation_failure_category(generation.integration_receipt)
                    if generation.integration_receipt.get("status") == "V25_6_FAILED"
                    else (_generation_failure_category(generation.errors[0]) if generation.errors else GENERATION_UNIT_FAILED),
                    "CORE-6 generation did not reach verified completion",
                    next_action=NEXT_REPAIR_GENERATED_UNIT,
                )
            self._transition(VERIFYING, verification_state={"required": True, "full_v25_6_passed": True, "staging_subject": stage_builder.subject_hash})
            canonical_builder = ProjectBuilder(
                self.project_root, current_blueprint, current_units,
                repository_map=self.repository_map, lexical_index=self.lexical_index,
                brain_entities=self.brain_entities, authority=self.authority,
                dnt_paths=self.dnt_paths, budget=stage_budget, provider=provider,
            )
            candidate_by_unit = {candidate.unit_id: candidate for candidate in generation.candidates}
            for unit in current_units:
                candidate = candidate_by_unit.get(unit.unit_id)
                if candidate is None:
                    return self._block(GENERATION_UNIT_FAILED, f"missing verified candidate for {unit.unit_id}", next_action=NEXT_REPAIR_GENERATED_UNIT)
                valid, _, _ = canonical_builder._validate_candidate(candidate, unit)
                if not valid or v25_5_validator is None:
                    return self._block(AUTHORITY_BLOCKED, "canonical build requires a valid V25.5 gate", next_action=NEXT_BLOCKED)
                passed, _ = _bool_result(_invoke(v25_5_validator, candidate, unit), default=False)
                if not passed:
                    return self._block(AUTHORITY_BLOCKED, f"V25.5 rejected generated unit {unit.unit_id}", next_action=NEXT_REPAIR_GENERATED_UNIT)
            self._transition(CANONICAL_APPLYING)
            for unit in current_units:
                applied = canonical_builder.apply_verified_candidate(candidate_by_unit[unit.unit_id], unit, v25_5_validator=v25_5_validator)
                if not applied.get("applied"):
                    return self._block(AUTHORITY_BLOCKED, f"canonical application failed for {unit.unit_id}", next_action=NEXT_REPAIR_GENERATED_UNIT, detail=applied)
                self._canonical_mutations.extend(applied.get("changed_paths", ()))
            self._transition(INDEX_UPDATING)
            self.repository_map = canonical_builder.repository_map
            self.lexical_index = canonical_builder.lexical_index
            self._last_generation_builder = canonical_builder
            self.brain_entities = tuple(generation.brain_entities)
            self._metrics["canonical_mutations"] += len(self._canonical_mutations)
            self._metrics["repository_map_incremental_updates"] += len(self._canonical_mutations)
            self._metrics["lexical_incremental_updates"] += len(self._canonical_mutations)
            self._metrics["verified_brain_updates"] += len(generation.brain_entities)
            self._brain_updates.extend(entity.entity_id for entity in generation.brain_entities)
            self._component_results["index_updates"] = {
                "repo_map": {"incremental_updates": len(self._canonical_mutations)},
                "lexical": {"incremental_updates": len(self._canonical_mutations)},
            }
            self._state = self._state.with_updates(
                subject_identity=self.subject_identity,
                revision_identity=self.revision_identity,
            )
            self._transition(PROMOTABLE, verification_state={"required": True, "full_v25_6_passed": True, "canonical_subject": self.subject_identity})
            self._transition(COMPLETE)
            self._metrics["successful_repairs"] += 1
        return self._result(status=CORE_COMPLETE, next_action=NEXT_COMPLETE, verification_state={"required": True, "full_v25_6_passed": True}, reason="verified CORE-6 build completed")

    def maintain(
        self,
        task: str,
        *,
        failure_evidence: Any = None,
        repair_problem: RepairProblem | Mapping[str, Any] | None = None,
        changed_paths: Iterable[str] = (),
        blueprint: ProjectBlueprint | Mapping[str, Any] | None = None,
        public_contract_changed: bool = False,
        dnt_paths: Iterable[str] = (),
        diagnostic_experiments: Iterable[Any] = (),
        diagnostic_runner: Any = None,
        diagnostic_confirmation_runner: Any = None,
        run_experiments: bool | None = None,
        patch_provider: Any = None,
        targeted_checker: Any = None,
        guard_checker: Any = None,
        contract_checker: Any = None,
        v25_5_gate: Any = None,
        v25_6_verifier: Any = None,
        apply_candidate: bool = False,
        selected_candidate_id: str | None = None,
        candidate_feedback_to_diagnostics: bool = True,
    ) -> CoreExecutionResult:
        if dnt_paths:
            self.dnt_paths = tuple(sorted(set(self.dnt_paths) | {
                _safe_relative(self.project_root, item) for item in dnt_paths
            }))
        mode = REPAIR if repair_problem is not None or apply_candidate else (DIAGNOSE if failure_evidence is not None else MAINTAIN)
        self._begin(task, mode)
        self._transition(CONTEXT_BUILDING)
        search = self.inspect_task_context(task)
        if self._context_budget_exceeded:
            return self._block(BUDGET_REACHED, "working-set expansion budget reached", next_action=NEXT_BUDGET_REACHED)
        working_set = search.working_set
        if working_set is None:
            return self._block(CONTEXT_INSUFFICIENT, "CORE-2 did not produce a TaskWorkingSet", next_action=NEXT_EXPAND_CONTEXT)
        if changed_paths:
            current_blueprint = blueprint if isinstance(blueprint, ProjectBlueprint) else (ProjectBlueprint.from_value(blueprint) if blueprint is not None else None)
            impact = analyze_change_impact(
                self.repository_map, changed_paths, blueprint=current_blueprint,
                public_contract_changed=public_contract_changed,
                max_depth=2, max_nodes=64,
            )
            island = build_change_island(impact, blueprint=current_blueprint)
            self._component_results["core6_impact"] = {"impact": impact, "island": island}
            if impact.status == LARGE_IMPACT_CHANGE:
                return self._block(BUDGET_REACHED, "large impact requires explicit bounded expansion", next_action=NEXT_REQUEST_BROADER_AUTHORITY)
        localization: FaultLocalizationResult | None = None
        diagnostic: DiagnosticResult | None = None
        failures = self._failure_rows(failure_evidence) if failure_evidence is not None else ()
        if failures:
            self._failure_evidence.extend(item.to_dict(include_hash=False) for item in failures)
            self._transition(LOCALIZING)
            localization = self._localize(task, failures, working_set)
            self._metrics["initial_culprit_rank"] = localization.known_root_rank_before_experiments
            should_run, trigger_reasons = self._should_run_experiments(localization, explicit=run_experiments)
            self._component_results["diagnostic_trigger"] = {"run": should_run, "reasons": list(trigger_reasons)}
            if should_run:
                diagnostic = self._run_diagnostics(
                    task, failures, working_set, diagnostic_experiments,
                    runner=diagnostic_runner, confirmation_runner=diagnostic_confirmation_runner,
                )
                if diagnostic is not None:
                    self._transition(LOCALIZING)
                    localization = localization.rerank_with_experimental_evidence(diagnostic)
                    self._component_results["core4_reranked"] = localization
                    self._last_localization = localization
                    self._metrics["post_experiment_culprit_rank"] = localization.known_root_rank_after_experiments
                elif not diagnostic_experiments:
                    self._component_results["diagnostic_skipped"] = {"reason": "no bounded experiment set supplied"}
            if mode == DIAGNOSE and repair_problem is None:
                if localization.recommended_next_action == RUN_DIAGNOSTIC_EXPERIMENTS:
                    return self._block(DIAGNOSTIC_INCONCLUSIVE, "localization remains ambiguous", next_action=NEXT_RUN_DIAGNOSTICS)
                self._transition(COMPLETE)
                return self._result(status=CORE_PARTIAL, next_action=NEXT_SEARCH_ALTERNATE_PATCH if localization.candidates else NEXT_EXPAND_CONTEXT, reason="diagnostic/localization result returned; no canonical change was applied")
        current_problem: RepairProblem | None = None
        if repair_problem is not None:
            current_problem = repair_problem if isinstance(repair_problem, RepairProblem) else RepairProblem.from_value(repair_problem)
            if current_problem.subject_identity and current_problem.subject_identity != self.subject_identity:
                return self._block(STALE_CONTEXT, "RepairProblem subject identity is stale", next_action=NEXT_EXPAND_CONTEXT)
        elif localization is not None:
            current_problem = self._repair_problem_from_localization(
                task, localization, working_set,
                blueprint=blueprint if isinstance(blueprint, ProjectBlueprint) else (ProjectBlueprint.from_value(blueprint) if blueprint is not None else None),
            )
        else:
            self._transition(COMPLETE)
            return self._result(status=CORE_COMPLETE, next_action=NEXT_COMPLETE, reason="bounded maintenance context prepared")
        self._transition(PATCH_SEARCHING)
        try:
            if patch_provider is not None:
                self.patch_provider = patch_provider
            patch_result = self.search_repair_candidates(
                current_problem, targeted_checker=targeted_checker, guard_checker=guard_checker,
                contract_checker=contract_checker, v25_5_gate=v25_5_gate,
                v25_6_verifier=v25_6_verifier,
            )
        except RuntimeError as exc:
            return self._block(BUDGET_REACHED, str(exc), next_action=NEXT_BUDGET_REACHED)
        selected = patch_result.winner
        if selected is None:
            if candidate_feedback_to_diagnostics and patch_result.rejected_candidates and localization is not None and self._budget_usage.get("diagnostic_rounds", 0) < self.budget.max_candidate_feedback_rounds:
                self._metrics["candidate_failure_feedback_rounds"] += 1
                self._component_results["candidate_failure_feedback"] = tuple(
                    adapt_candidate_failure(item, subject_identity=self.subject_identity, revision_identity=self.revision_identity)
                    for item in patch_result.rejected_candidates
                )
                self._metrics["failed_repairs"] += 1
                return self._block(NO_VIABLE_PATCH, "patch candidates failed; bounded diagnostic feedback is available", next_action=NEXT_RUN_DIAGNOSTICS)
            return self._block(NO_VIABLE_PATCH, "CORE-5 produced no viable candidate", next_action=NEXT_SEARCH_ALTERNATE_PATCH)
        self._metrics["one_shot_success"] = int(len(patch_result.generated_candidates) == 1 and selected.status == VERIFIED)
        if not apply_candidate:
            self._transition(COMPLETE)
            return self._result(status=CORE_PARTIAL, next_action=NEXT_NEEDS_MODEL_PROPOSAL if selected.status != VERIFIED else NEXT_FINAL_VERIFICATION_REQUIRED, reason="bounded patch candidate search completed without canonical application")
        self._transition(CANDIDATE_SELECTED)
        self._transition(CANONICAL_APPLYING)
        applied = self.apply_patch_candidate(
            selected, v25_5_gate=v25_5_gate, v25_6_verifier=v25_6_verifier,
            selected_candidate_id=selected_candidate_id or selected.candidate_id,
        )
        self._component_results["canonical_application"] = applied
        if not applied.get("applied"):
            category = DNT_BLOCKED if "DNT" in str(applied.get("reason", "")) else AUTHORITY_BLOCKED if applied.get("status") == AUTHORITY_BLOCKED else FINAL_VERIFICATION_FAILED
            return self._block(category, "canonical patch application did not pass all required gates", next_action=NEXT_FINAL_VERIFICATION_REQUIRED, detail=applied)
        self._transition(VERIFYING, verification_state={"required": True, "full_v25_6_passed": True})
        self._transition(INDEX_UPDATING)
        self._transition(PROMOTABLE, verification_state={"required": True, "full_v25_6_passed": True})
        self._transition(COMPLETE)
        return self._result(status=CORE_COMPLETE, next_action=NEXT_COMPLETE, verification_state={"required": True, "full_v25_6_passed": True}, reason="verified CORE-5 maintenance repair completed")

    def repair(self, task: str, **kwargs: Any) -> CoreExecutionResult:
        kwargs["apply_candidate"] = True
        return self.maintain(task, **kwargs)

    def execute(self, task: str | Mapping[str, Any], *, mode: str | None = None, blueprint: Any = None, units: Any = None, failure_evidence: Any = None, repair_problem: Any = None, **kwargs: Any) -> CoreExecutionResult:
        raw = _map(task) if isinstance(task, Mapping) else {}
        text = str(raw.get("task", raw.get("raw_task_text", task if isinstance(task, str) else "")))
        selected_mode = classify_core_task(
            task, project_root=self.project_root, explicit_mode=mode,
            blueprint=blueprint or raw.get("blueprint"), failure_evidence=failure_evidence or raw.get("failure_evidence"),
            repair_problem=repair_problem or raw.get("repair_problem"),
        )
        if selected_mode == BUILD:
            return self.build(text, blueprint or raw.get("blueprint"), units or raw.get("units"), **kwargs)
        if selected_mode == DIAGNOSE:
            return self.maintain(text, failure_evidence=failure_evidence or raw.get("failure_evidence"), **kwargs)
        if selected_mode == REPAIR:
            return self.maintain(text, repair_problem=repair_problem or raw.get("repair_problem"), **kwargs)
        return self.maintain(text, **kwargs)


HivoCoreOrchestrator = CoreIntelligenceCoordinator
CoreOrchestrator = CoreIntelligenceCoordinator


def execute_core_task(project_root: str | Path, task: str | Mapping[str, Any], **kwargs: Any) -> CoreExecutionResult:
    coordinator_kwargs = {
        key: kwargs.pop(key) for key in (
            "repository_map", "lexical_index", "brain_entities", "authority", "dnt_paths", "budget",
            "generation_provider", "patch_provider", "semantic_retriever", "diagnostic_engine",
        ) if key in kwargs
    }
    return CoreIntelligenceCoordinator(project_root, **coordinator_kwargs).execute(task, **kwargs)


def inspect_task_context(project_root: str | Path, task: str, **kwargs: Any) -> RepoIntelligenceResult:
    coordinator = CoreIntelligenceCoordinator(project_root, **{
        key: kwargs.pop(key) for key in ("repository_map", "lexical_index", "brain_entities", "authority", "dnt_paths", "budget", "semantic_retriever") if key in kwargs
    })
    coordinator._begin(task, MAINTAIN)
    return coordinator.inspect_task_context(task, **kwargs)


__all__ = [
    "CORE_INTEGRATION_VERSION", "GENERATION_PROVIDER", "PATCH_PROVIDER", "SEMANTIC_PROVIDER",
    "PROVIDER_ROLES", "CORE_COMPLETE", "CORE_PARTIAL", "CORE_BLOCKED",
    "classify_core_task", "ModelPatchCandidateProviderAdapter",
    "adapt_candidate_failure_evidence", "CoreIntelligenceCoordinator",
    "HivoCoreOrchestrator", "CoreOrchestrator", "execute_core_task", "inspect_task_context",
]
