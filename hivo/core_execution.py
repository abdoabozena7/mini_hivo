"""Provider-free execution state and budgets for the integrated Core pipeline.

This module contains only integration bookkeeping.  It deliberately does not
own approval, mutation, verification, Brain truth, or any Core algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .project_brain_refs import canonical_hash


CORE_INTEGRATION_SCHEMA_VERSION = "HIVO-CORE-INTEGRATION-V1"

# Execution modes.
BUILD = "BUILD"
MAINTAIN = "MAINTAIN"
DIAGNOSE = "DIAGNOSE"
REPAIR = "REPAIR"
EXECUTION_MODES = (BUILD, MAINTAIN, DIAGNOSE, REPAIR)
WORKING_SET_FIRST = "WORKING_SET_FIRST"

# Execution phases.
INITIALIZING = "INITIALIZING"
CONTEXT_BUILDING = "CONTEXT_BUILDING"
PLANNING = "PLANNING"
GENERATING = "GENERATING"
LOCALIZING = "LOCALIZING"
EXPERIMENTING = "EXPERIMENTING"
PATCH_SEARCHING = "PATCH_SEARCHING"
CANDIDATE_SELECTED = "CANDIDATE_SELECTED"
CANONICAL_APPLYING = "CANONICAL_APPLYING"
VERIFYING = "VERIFYING"
INDEX_UPDATING = "INDEX_UPDATING"
PROMOTABLE = "PROMOTABLE"
COMPLETE = "COMPLETE"
BLOCKED = "BLOCKED"
EXECUTION_PHASES = (
    INITIALIZING, CONTEXT_BUILDING, PLANNING, GENERATING, LOCALIZING,
    EXPERIMENTING, PATCH_SEARCHING, CANDIDATE_SELECTED, CANONICAL_APPLYING,
    VERIFYING, INDEX_UPDATING, PROMOTABLE, COMPLETE, BLOCKED,
)

# Structured integration failures.  Component-specific status values are
# retained in component results; these values describe the routing boundary.
CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
LOCALIZATION_INSUFFICIENT = "LOCALIZATION_INSUFFICIENT"
DIAGNOSTIC_INCONCLUSIVE = "DIAGNOSTIC_INCONCLUSIVE"
NO_VIABLE_PATCH = "NO_VIABLE_PATCH"
PATCH_VERIFICATION_FAILED = "PATCH_VERIFICATION_FAILED"
GENERATION_UNIT_FAILED = "GENERATION_UNIT_FAILED"
CONTRACT_FAILURE = "CONTRACT_FAILURE"
INTEGRATION_FAILURE = "INTEGRATION_FAILURE"
AUTHORITY_BLOCKED = "AUTHORITY_BLOCKED"
DNT_BLOCKED = "DNT_BLOCKED"
BUDGET_REACHED = "BUDGET_REACHED"
FINAL_VERIFICATION_FAILED = "FINAL_VERIFICATION_FAILED"
PROVIDER_FAILURE = "PROVIDER_FAILURE"
STALE_CONTEXT = "STALE_CONTEXT"
FAILURE_CATEGORIES = (
    CONTEXT_INSUFFICIENT, LOCALIZATION_INSUFFICIENT,
    DIAGNOSTIC_INCONCLUSIVE, NO_VIABLE_PATCH, PATCH_VERIFICATION_FAILED,
    GENERATION_UNIT_FAILED, CONTRACT_FAILURE, INTEGRATION_FAILURE,
    AUTHORITY_BLOCKED, DNT_BLOCKED, BUDGET_REACHED,
    FINAL_VERIFICATION_FAILED, PROVIDER_FAILURE, STALE_CONTEXT,
)

# Bounded next actions.
NEXT_COMPLETE = "COMPLETE"
NEXT_NEEDS_MODEL_PROPOSAL = "NEEDS_MODEL_PROPOSAL"
NEXT_EXPAND_CONTEXT = "EXPAND_CONTEXT"
NEXT_RUN_DIAGNOSTICS = "RUN_DIAGNOSTICS"
NEXT_SEARCH_ALTERNATE_PATCH = "SEARCH_ALTERNATE_PATCH"
NEXT_REPAIR_GENERATED_UNIT = "REPAIR_GENERATED_UNIT"
NEXT_RESOLVE_CONTRACT = "RESOLVE_CONTRACT"
NEXT_REQUEST_BROADER_AUTHORITY = "REQUEST_BROADER_AUTHORITY"
NEXT_INVESTIGATE_FLAKINESS = "INVESTIGATE_FLAKINESS"
NEXT_FINAL_VERIFICATION_REQUIRED = "FINAL_VERIFICATION_REQUIRED"
NEXT_BUDGET_REACHED = "BUDGET_REACHED"
NEXT_BLOCKED = "BLOCKED"
NEXT_ACTIONS = (
    NEXT_COMPLETE, NEXT_NEEDS_MODEL_PROPOSAL, NEXT_EXPAND_CONTEXT,
    NEXT_RUN_DIAGNOSTICS, NEXT_SEARCH_ALTERNATE_PATCH,
    NEXT_REPAIR_GENERATED_UNIT, NEXT_RESOLVE_CONTRACT,
    NEXT_REQUEST_BROADER_AUTHORITY, NEXT_INVESTIGATE_FLAKINESS,
    NEXT_FINAL_VERIFICATION_REQUIRED, NEXT_BUDGET_REACHED, NEXT_BLOCKED,
)


def _plain(value: Any) -> Any:
    """Convert Core objects to bounded canonical data without introspection leaks."""
    if hasattr(value, "to_dict") and callable(value.to_dict):
        try:
            return value.to_dict(include_hash=False)
        except TypeError:
            return value.to_dict()
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if isinstance(value, set):
        return sorted(_plain(item) for item in value)
    return value


def _freeze(value: Any) -> Any:
    """Recursively freeze integration-owned containers for result/state safety."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return frozenset(_freeze(item) for item in value)
    return value


@dataclass(frozen=True)
class CoreExecutionBudget:
    """Hard integration bounds; component budgets remain independently active."""

    max_core_stages: int = 16
    max_working_set_expansions: int = 2
    max_diagnostic_rounds: int = 2
    max_patch_search_sessions: int = 2
    max_generation_units: int = 64
    max_provider_requests: int = 64
    max_full_verification_attempts: int = 2
    max_candidate_feedback_rounds: int = 1
    max_context_files: int = 16
    max_context_source_characters: int = 24000

    def __post_init__(self) -> None:
        limits = {
            "max_core_stages": (1, 128),
            "max_working_set_expansions": (0, 32),
            "max_diagnostic_rounds": (0, 16),
            "max_patch_search_sessions": (0, 16),
            "max_generation_units": (1, 256),
            "max_provider_requests": (0, 512),
            "max_full_verification_attempts": (0, 16),
            "max_candidate_feedback_rounds": (0, 8),
            "max_context_files": (1, 128),
            "max_context_source_characters": (256, 200000),
        }
        for name, (minimum, maximum) in limits.items():
            value = max(minimum, min(maximum, int(getattr(self, name))))
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in (
                "max_core_stages", "max_working_set_expansions",
                "max_diagnostic_rounds", "max_patch_search_sessions",
                "max_generation_units", "max_provider_requests",
                "max_full_verification_attempts", "max_candidate_feedback_rounds",
                "max_context_files", "max_context_source_characters",
            )
        }

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())


CoreBudget = CoreExecutionBudget


_ALLOWED_TRANSITIONS: dict[str, tuple[str, ...]] = {
    INITIALIZING: (CONTEXT_BUILDING, PLANNING, BLOCKED),
    CONTEXT_BUILDING: (PLANNING, LOCALIZING, PATCH_SEARCHING, BLOCKED, COMPLETE),
    PLANNING: (GENERATING, CONTEXT_BUILDING, BLOCKED),
    GENERATING: (VERIFYING, INDEX_UPDATING, BLOCKED),
    LOCALIZING: (EXPERIMENTING, PATCH_SEARCHING, CONTEXT_BUILDING, BLOCKED, COMPLETE),
    EXPERIMENTING: (LOCALIZING, PATCH_SEARCHING, BLOCKED),
    PATCH_SEARCHING: (CANDIDATE_SELECTED, LOCALIZING, EXPERIMENTING, BLOCKED, COMPLETE),
    CANDIDATE_SELECTED: (CANONICAL_APPLYING, PATCH_SEARCHING, BLOCKED),
    CANONICAL_APPLYING: (VERIFYING, INDEX_UPDATING, BLOCKED),
    VERIFYING: (CANONICAL_APPLYING, INDEX_UPDATING, PROMOTABLE, BLOCKED),
    INDEX_UPDATING: (PROMOTABLE, BLOCKED),
    PROMOTABLE: (COMPLETE, BLOCKED),
    COMPLETE: (),
    BLOCKED: (),
}


@dataclass(frozen=True)
class CoreExecutionState:
    execution_id: str
    mode: str
    subject_identity: str
    revision_identity: str
    authority_identity: str
    current_phase: str = INITIALIZING
    phases_visited: tuple[str, ...] = (INITIALIZING,)
    working_set_identity: str = ""
    diagnostic_identity: str = ""
    localization_identity: str = ""
    patch_search_identity: str = ""
    generation_plan_identity: str = ""
    checkpoint_identity: str = ""
    budget_usage: dict[str, int] = field(default_factory=dict)
    verification_state: dict[str, Any] = field(default_factory=dict)
    authority_state: dict[str, Any] = field(default_factory=dict)
    terminal_reason: str = ""

    def __post_init__(self) -> None:
        mode = str(self.mode).upper()
        if mode not in EXECUTION_MODES:
            raise ValueError(f"unsupported Core execution mode: {mode}")
        if self.current_phase not in EXECUTION_PHASES:
            raise ValueError(f"unsupported Core execution phase: {self.current_phase}")
        history = tuple(self.phases_visited or (INITIALIZING,))
        if history[-1] != self.current_phase:
            history = history + (self.current_phase,)
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "phases_visited", history)
        object.__setattr__(self, "budget_usage", _freeze({str(k): int(v) for k, v in dict(self.budget_usage or {}).items()}))
        object.__setattr__(self, "verification_state", _freeze(dict(self.verification_state or {})))
        object.__setattr__(self, "authority_state", _freeze(dict(self.authority_state or {})))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE_INTEGRATION_SCHEMA_VERSION,
            "execution_id": self.execution_id,
            "mode": self.mode,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "authority_identity": self.authority_identity,
            "current_phase": self.current_phase,
            "phases_visited": list(self.phases_visited),
            "working_set_identity": self.working_set_identity,
            "diagnostic_identity": self.diagnostic_identity,
            "localization_identity": self.localization_identity,
            "patch_search_identity": self.patch_search_identity,
            "generation_plan_identity": self.generation_plan_identity,
            "checkpoint_identity": self.checkpoint_identity,
            "budget_usage": dict(self.budget_usage),
            "verification_state": _plain(self.verification_state),
            "authority_state": _plain(self.authority_state),
            "terminal_reason": self.terminal_reason,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    def with_updates(self, **changes: Any) -> "CoreExecutionState":
        return replace(self, **changes)

    def transition(self, phase: str, **updates: Any) -> "CoreExecutionState":
        phase = str(phase)
        if phase not in EXECUTION_PHASES:
            raise ValueError(f"unsupported Core execution phase: {phase}")
        if phase != self.current_phase and phase not in _ALLOWED_TRANSITIONS.get(self.current_phase, ()):
            raise ValueError(f"invalid Core phase transition: {self.current_phase} -> {phase}")
        if self.current_phase == PATCH_SEARCHING and phase == PROMOTABLE:
            raise ValueError("patch search cannot become promotable without application and verification")
        if phase == PROMOTABLE and not bool(dict(updates.get("verification_state", self.verification_state)).get("full_v25_6_passed", False)):
            raise ValueError("promotable state requires full V25.6 verification")
        history = self.phases_visited if phase == self.current_phase else self.phases_visited + (phase,)
        return replace(self, current_phase=phase, phases_visited=history, **updates)


@dataclass(frozen=True)
class CoreProviderRequest:
    """Auditable future provider boundary; no provider call is performed here."""

    request_id: str
    role: str
    execution_id: str
    mode: str
    operation_identity: str
    evidence_packet_hash: str
    subject_identity: str
    revision_identity: str
    authority_identity: str

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE_INTEGRATION_SCHEMA_VERSION,
            "request_id": self.request_id, "role": self.role,
            "execution_id": self.execution_id, "mode": self.mode,
            "operation_identity": self.operation_identity,
            "evidence_packet_hash": self.evidence_packet_hash,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "authority_identity": self.authority_identity,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class CoreExecutionResult:
    execution_id: str
    mode: str
    status: str
    state: CoreExecutionState
    phases_visited: tuple[str, ...] = ()
    component_results: dict[str, Any] = field(default_factory=dict)
    provider_accounting: dict[str, int] = field(default_factory=dict)
    budget_usage: dict[str, int] = field(default_factory=dict)
    canonical_mutations: tuple[str, ...] = ()
    verification_state: dict[str, Any] = field(default_factory=dict)
    index_updates: dict[str, Any] = field(default_factory=dict)
    brain_updates: tuple[str, ...] = ()
    failure_evidence: tuple[dict[str, Any], ...] = ()
    recommended_next_action: str = NEXT_BLOCKED
    metrics: dict[str, Any] = field(default_factory=dict)
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    source_unchanged: bool = True
    reason: str = ""

    def __post_init__(self) -> None:
        if self.mode not in EXECUTION_MODES:
            raise ValueError(f"unsupported Core result mode: {self.mode}")
        if self.recommended_next_action not in NEXT_ACTIONS:
            raise ValueError(f"unsupported Core next action: {self.recommended_next_action}")
        object.__setattr__(self, "phases_visited", tuple(self.phases_visited or self.state.phases_visited))
        object.__setattr__(self, "component_results", _freeze(dict(self.component_results or {})))
        object.__setattr__(self, "provider_accounting", _freeze({str(k): int(v) for k, v in dict(self.provider_accounting or {}).items()}))
        object.__setattr__(self, "budget_usage", _freeze({str(k): int(v) for k, v in dict(self.budget_usage or {}).items()}))
        object.__setattr__(self, "verification_state", _freeze(dict(self.verification_state or {})))
        object.__setattr__(self, "index_updates", _freeze(dict(self.index_updates or {})))
        object.__setattr__(self, "brain_updates", tuple(str(item) for item in self.brain_updates))
        object.__setattr__(self, "failure_evidence", _freeze(tuple(dict(item) for item in self.failure_evidence)))
        object.__setattr__(self, "metrics", _freeze(dict(self.metrics or {})))
        object.__setattr__(self, "unresolved_evidence", _freeze(tuple(dict(item) for item in self.unresolved_evidence)))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE_INTEGRATION_SCHEMA_VERSION,
            "execution_id": self.execution_id, "mode": self.mode,
            "status": self.status, "state": self.state.to_dict(),
            "phases_visited": list(self.phases_visited),
            "component_results": _plain(self.component_results),
            "provider_accounting": dict(self.provider_accounting),
            "budget_usage": dict(self.budget_usage),
            "canonical_mutations": list(self.canonical_mutations),
            "verification_state": _plain(self.verification_state),
            "index_updates": _plain(self.index_updates),
            "brain_updates": list(self.brain_updates),
            "failure_evidence": _plain(self.failure_evidence),
            "recommended_next_action": self.recommended_next_action,
            "metrics": _plain(self.metrics),
            "unresolved_evidence": _plain(self.unresolved_evidence),
            "source_unchanged": self.source_unchanged,
            "reason": self.reason,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def new_core_metrics() -> dict[str, int]:
    """Create stable integration metric keys with zero-valued counters."""
    return {
        "core_executions": 0, "build_executions": 0, "maintenance_executions": 0,
        "diagnose_executions": 0, "repair_executions": 0,
        "working_sets_created": 0, "working_set_expansions": 0,
        "localization_runs": 0, "diagnostic_sessions": 0, "diagnostic_cycles": 0,
        "experiments_executed": 0, "patch_search_sessions": 0,
        "patch_candidates_generated": 0, "generation_units_processed": 0,
        "provider_requests": 0, "full_verification_runs": 0,
        "successful_repairs": 0, "failed_repairs": 0, "canonical_mutations": 0,
        "repository_map_incremental_updates": 0, "lexical_incremental_updates": 0,
        "verified_brain_updates": 0, "budget_stops": 0,
        "provider_requests_per_build_unit": 0, "provider_requests_per_repair": 0,
        "deterministic_repairs_without_provider": 0, "deterministic_diagnostic_steps": 0,
        "model_candidates_rejected": 0, "model_candidates_accepted": 0,
        "model_candidates_verified": 0, "mean_working_set_files": 0,
        "mean_working_set_source_characters": 0, "mean_generation_packet_characters": 0,
        "mean_repair_packet_characters": 0, "full_repository_context_loads": 0,
        "legacy_exploration_operations_avoided": 0, "initial_culprit_rank": 0,
        "post_experiment_culprit_rank": 0, "experiments_to_narrow": 0,
        "wrong_top1_recoveries": 0, "masking_risks_detected": 0,
        "one_shot_success": 0, "bounded_patch_search_success": 0,
        "patch_search_recovery_lift": 0, "v25_6_attempts": 0,
        "checkpoint_reuse": 0, "unnecessary_regeneration": 0,
        "authority_violations": 0, "dnt_violations": 0,
        "false_verified_states": 0, "false_promotions": 0,
        "canonical_mutations_before_selection_or_verification": 0,
        "core_stages": 0, "provider_calls": 0, "fake_provider_calls": 0,
        "full_verification_attempts": 0, "candidate_failure_feedback_rounds": 0,
        "core_autonomy_lift": 0,
    }


def core_autonomy_lift(*, naive_success: bool, integrated_success: bool, provider_requests: int = 0) -> dict[str, Any]:
    """Return a fixture KPI, never a real-model performance claim."""
    naive = int(bool(naive_success))
    integrated = int(bool(integrated_success))
    return {
        "CORE_AUTONOMY_LIFT": integrated - naive,
        "naive_first_proposal_success": bool(naive_success),
        "integrated_deterministic_success": bool(integrated_success),
        "provider_requests": int(provider_requests),
        "scope": "provider_free_architecture_fixture_only",
    }


__all__ = [
    "CORE_INTEGRATION_SCHEMA_VERSION", "BUILD", "MAINTAIN", "DIAGNOSE", "REPAIR",
    "EXECUTION_MODES", "WORKING_SET_FIRST", "INITIALIZING", "CONTEXT_BUILDING",
    "PLANNING", "GENERATING", "LOCALIZING", "EXPERIMENTING", "PATCH_SEARCHING",
    "CANDIDATE_SELECTED", "CANONICAL_APPLYING", "VERIFYING", "INDEX_UPDATING",
    "PROMOTABLE", "COMPLETE", "BLOCKED", "EXECUTION_PHASES",
    "CONTEXT_INSUFFICIENT", "LOCALIZATION_INSUFFICIENT", "DIAGNOSTIC_INCONCLUSIVE",
    "NO_VIABLE_PATCH", "PATCH_VERIFICATION_FAILED", "GENERATION_UNIT_FAILED",
    "CONTRACT_FAILURE", "INTEGRATION_FAILURE", "AUTHORITY_BLOCKED", "DNT_BLOCKED",
    "BUDGET_REACHED", "FINAL_VERIFICATION_FAILED", "PROVIDER_FAILURE", "STALE_CONTEXT",
    "FAILURE_CATEGORIES", "NEXT_ACTIONS", "NEXT_COMPLETE", "NEXT_NEEDS_MODEL_PROPOSAL",
    "NEXT_EXPAND_CONTEXT", "NEXT_RUN_DIAGNOSTICS", "NEXT_SEARCH_ALTERNATE_PATCH",
    "NEXT_REPAIR_GENERATED_UNIT", "NEXT_RESOLVE_CONTRACT", "NEXT_REQUEST_BROADER_AUTHORITY",
    "NEXT_INVESTIGATE_FLAKINESS", "NEXT_FINAL_VERIFICATION_REQUIRED", "NEXT_BUDGET_REACHED",
    "NEXT_BLOCKED", "CoreExecutionBudget", "CoreBudget", "CoreExecutionState",
    "CoreProviderRequest", "CoreExecutionResult", "new_core_metrics", "core_autonomy_lift",
]
