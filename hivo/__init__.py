"""Core policies for the Mini Hivo coding orchestrator.

The executable remains ``mini.py`` for backwards compatibility.  This package
contains policy and state-free components that can be tested without Ollama or
a browser.
"""

from .model_policy import GEMMA_MODEL, SingleModelPolicy
from .memory import MemoryStore
from .playbooks import build_execution_stages, classify_project
from .projects import ProjectStore
from .project_brain_refs import (
    ProjectBrainEntity, TypedReference, create_project_brain_entity,
    mark_reference_stale, normalize_legacy_brain_record,
)
from .repository_map import RepositoryMap, build_repository_map, incremental_reindex
from .reference_resolution import (
    EvidenceResolutionRequest, ProjectReferenceResolver, ResolvedEvidence,
)
from .lexical_index import (
    LexicalIndex, build_lexical_index, incremental_lexical_update,
)
from .task_working_set import (
    TaskWorkingSet, WorkingSetBudget, WorkingSetItem, build_task_working_set,
    expand_working_set,
)
from .repo_intelligence import (
    RepoIntelligenceQuery, SearchCandidate, RepoIntelligenceResult,
    RepoIntelligenceBudget, search_repository, benchmark_repository_navigation,
    SearchIntent, classify_search_intents, extract_query_signals,
)
from .diagnostic_hypotheses import (
    DiagnosticBudget, DiagnosticFailureEvidence, DiagnosticHypothesis,
    DiagnosticSession, seed_hypotheses,
)
from .experiment_selector import DiagnosticExperiment, ExperimentSelector, SelectionDecision
from .experiment_sandbox import (
    CounterfactualMutationSpec, ExperimentalSandbox, ProbePermission,
    classify_probe_permission, canonical_subject_hash, subject_tree_snapshot,
)
from .experimental_evidence import (
    BaselineReceipt, DiagnosticResult, EvidenceItem, ExperimentReceipt,
    ExperimentalEvidenceEngine, ExperimentalEvidenceLedger, VerificationResult,
    generate_test_failure_experiments, generate_error_location_experiments,
    generate_dependency_stub_experiment, generate_input_perturbation_experiment,
    session_from_recovery_failure, benchmark_diagnostic_scenarios,
)
from .coverage_evidence import (
    CoverageEvidence, CoverageEvidenceProvider, COVERAGE_AVAILABLE,
    COVERAGE_NOT_AVAILABLE, COVERAGE_STALE, collect_coverage_evidence,
    ochiai_suspiciousness,
)
from .fault_localization import (
    FaultFailureEvidence, FailureEvidence, LocalizationBudget,
    FaultLocalizationBudget, FaultLocalizationRequest, StackFrame, StackTraceParser,
    FaultCandidate, FaultLocalizationResult, FaultLocalizationEngine,
    parse_stack_trace, parse_stack_frames, build_fault_localization_request,
    localize_fault, seed_hypotheses_from_localization,
    rerank_with_experimental_evidence, benchmark_fault_localization_scenarios,
    benchmark_fault_localization, TEST_FAILURE, ASSERTION_FAILURE,
    RUNTIME_EXCEPTION, SYNTAX_FAILURE, VERIFICATION_FAILURE, ORACLE_FAILURE,
    WORKER_EXECUTION_FAILURE, INTEGRATION_FAILURE, ERROR_LOCATION_SIGNAL,
    STACK_TRACE_SIGNAL, FAILING_TEST_SIGNAL, TEST_DEPENDENCY_SIGNAL,
    COVERAGE_SIGNAL, GRAPH_PROXIMITY_SIGNAL, CHANGE_PROXIMITY_SIGNAL,
    LEXICAL_SIGNAL, BRAIN_CONTRACT_SIGNAL, EXPERIMENTAL_EVIDENCE_SIGNAL,
    LOW, MEDIUM, HIGH, VERY_HIGH, DNT_PROTECTED,
)
from .repair_problem import (
    CORE5_SCHEMA_VERSION, DIAGNOSTIC_SUSPECT, FINAL_MUTATION_AUTHORIZED,
    READ_ONLY_SUPPORT as CORE5_READ_ONLY_SUPPORT, DNT_PROTECTED as CORE5_DNT_PROTECTED,
    PatchSearchBudget, CandidateSearchBudget, RepairTargetSet, RepairEvidencePacket,
    RepairProblem,
)
from .mutation_strategy import (
    EXACT_VALUE_CHANGE, CONDITION_CHANGE, EXPORT_IMPORT_REPAIR,
    FUNCTION_LOCAL_REWRITE, SMALL_INSERTION, SMALL_DELETION, CALLSITE_ADJUSTMENT,
    DEPENDENCY_CONFIGURATION_CHANGE, MULTI_LOCATION_SINGLE_FILE_CHANGE,
    MULTI_FILE_BOUNDED_CHANGE, UNKNOWN_STRUCTURAL_CHANGE, STRATEGY_CLASSES,
    StrategyDecision, MutationStrategyRouter, route_mutation_strategies,
)
from .patch_candidates import (
    DETERMINISTIC_OPERATOR, REPAIR_TEMPLATE, EXPERIMENT_DERIVED, MODEL_PROPOSED,
    USER_PROPOSED, PROPOSED, STALE_BASE, AUTHORITY_BLOCKED, SYNTAX_INVALID,
    TARGET_FAILED, GUARD_REGRESSION, REGRESSION_RISK, CONTRACT_CONFLICT, V25_5_REJECTED,
    V25_6_FAILED, VIABLE, VERIFIED, PatchOperation, PatchRepresentation,
    STALE_PATCH_BASE, SYNTAX_INVALID_CANDIDATE, PatchCandidate, PatchCandidateReceipt, CandidateFailureEvidence,
    ModelPatchCandidateProvider, generate_deterministic_candidates,
    generate_experiment_derived_candidate, normalize_model_candidates, generate_patch_candidates,
)
from .patch_search import (
    PatchSearchResult, PatchSearchEngine, search_patch_candidates,
    apply_selected_patch_candidate, update_repository_indexes_after_application,
    benchmark_patch_search_scenarios, VERIFIED_CANDIDATE, BEST_VIABLE_CANDIDATE,
    APPLY_SELECTED_CANDIDATE, NO_VIABLE_PATCH_CANDIDATE, PATCH_SEARCH_BUDGET_REACHED,
)

__all__ = [
    "GEMMA_MODEL", "MemoryStore", "ProjectStore", "SingleModelPolicy",
    "build_execution_stages", "classify_project",
    "ProjectBrainEntity", "TypedReference", "RepositoryMap", "build_repository_map",
    "incremental_reindex", "EvidenceResolutionRequest", "ProjectReferenceResolver",
    "ResolvedEvidence", "create_project_brain_entity", "mark_reference_stale",
    "normalize_legacy_brain_record", "LexicalIndex", "build_lexical_index",
    "incremental_lexical_update", "TaskWorkingSet", "WorkingSetBudget",
    "WorkingSetItem", "build_task_working_set", "expand_working_set",
    "RepoIntelligenceQuery", "SearchCandidate", "RepoIntelligenceResult",
    "RepoIntelligenceBudget", "search_repository", "benchmark_repository_navigation",
    "SearchIntent", "classify_search_intents", "extract_query_signals",
    "DiagnosticBudget", "DiagnosticFailureEvidence", "DiagnosticHypothesis",
    "DiagnosticSession", "seed_hypotheses", "DiagnosticExperiment",
    "ExperimentSelector", "SelectionDecision", "CounterfactualMutationSpec",
    "ExperimentalSandbox", "ProbePermission", "classify_probe_permission",
    "canonical_subject_hash", "subject_tree_snapshot", "BaselineReceipt",
    "DiagnosticResult", "EvidenceItem", "ExperimentReceipt",
    "ExperimentalEvidenceEngine", "ExperimentalEvidenceLedger", "VerificationResult",
    "generate_test_failure_experiments", "generate_error_location_experiments",
    "generate_dependency_stub_experiment", "generate_input_perturbation_experiment",
    "session_from_recovery_failure", "benchmark_diagnostic_scenarios",
    "CoverageEvidence", "CoverageEvidenceProvider", "COVERAGE_AVAILABLE",
    "COVERAGE_NOT_AVAILABLE", "COVERAGE_STALE", "collect_coverage_evidence",
    "ochiai_suspiciousness", "FaultFailureEvidence", "FailureEvidence",
    "LocalizationBudget", "FaultLocalizationBudget", "FaultLocalizationRequest",
    "StackFrame", "StackTraceParser", "FaultCandidate", "FaultLocalizationResult",
    "FaultLocalizationEngine", "parse_stack_trace", "parse_stack_frames",
    "build_fault_localization_request", "localize_fault",
    "seed_hypotheses_from_localization", "rerank_with_experimental_evidence",
    "benchmark_fault_localization_scenarios", "benchmark_fault_localization",
    "TEST_FAILURE", "ASSERTION_FAILURE", "RUNTIME_EXCEPTION", "SYNTAX_FAILURE",
    "VERIFICATION_FAILURE", "ORACLE_FAILURE", "WORKER_EXECUTION_FAILURE",
    "INTEGRATION_FAILURE", "ERROR_LOCATION_SIGNAL", "STACK_TRACE_SIGNAL",
    "FAILING_TEST_SIGNAL", "TEST_DEPENDENCY_SIGNAL", "COVERAGE_SIGNAL",
    "GRAPH_PROXIMITY_SIGNAL", "CHANGE_PROXIMITY_SIGNAL", "LEXICAL_SIGNAL",
    "BRAIN_CONTRACT_SIGNAL", "EXPERIMENTAL_EVIDENCE_SIGNAL", "LOW", "MEDIUM",
    "HIGH", "VERY_HIGH", "DNT_PROTECTED",
    "CORE5_SCHEMA_VERSION", "DIAGNOSTIC_SUSPECT", "FINAL_MUTATION_AUTHORIZED",
    "CORE5_READ_ONLY_SUPPORT", "CORE5_DNT_PROTECTED", "PatchSearchBudget",
    "CandidateSearchBudget", "RepairTargetSet", "RepairEvidencePacket", "RepairProblem",
    "EXACT_VALUE_CHANGE", "CONDITION_CHANGE", "EXPORT_IMPORT_REPAIR",
    "FUNCTION_LOCAL_REWRITE", "SMALL_INSERTION", "SMALL_DELETION", "CALLSITE_ADJUSTMENT",
    "DEPENDENCY_CONFIGURATION_CHANGE", "MULTI_LOCATION_SINGLE_FILE_CHANGE",
    "MULTI_FILE_BOUNDED_CHANGE", "UNKNOWN_STRUCTURAL_CHANGE", "STRATEGY_CLASSES",
    "StrategyDecision", "MutationStrategyRouter", "route_mutation_strategies",
    "DETERMINISTIC_OPERATOR", "REPAIR_TEMPLATE", "EXPERIMENT_DERIVED", "MODEL_PROPOSED",
    "USER_PROPOSED", "PROPOSED", "STALE_BASE", "AUTHORITY_BLOCKED", "SYNTAX_INVALID",
    "TARGET_FAILED", "GUARD_REGRESSION", "CONTRACT_CONFLICT", "V25_5_REJECTED",
    "V25_6_FAILED", "VIABLE", "VERIFIED", "STALE_PATCH_BASE", "REGRESSION_RISK", "SYNTAX_INVALID_CANDIDATE", "PatchOperation", "PatchRepresentation",
    "PatchCandidate", "PatchCandidateReceipt", "CandidateFailureEvidence",
    "ModelPatchCandidateProvider", "generate_deterministic_candidates",
    "generate_experiment_derived_candidate", "normalize_model_candidates", "generate_patch_candidates",
    "PatchSearchResult", "PatchSearchEngine", "search_patch_candidates",
    "apply_selected_patch_candidate", "update_repository_indexes_after_application",
    "benchmark_patch_search_scenarios", "VERIFIED_CANDIDATE", "BEST_VIABLE_CANDIDATE",
    "APPLY_SELECTED_CANDIDATE", "NO_VIABLE_PATCH_CANDIDATE", "PATCH_SEARCH_BUDGET_REACHED",
]
