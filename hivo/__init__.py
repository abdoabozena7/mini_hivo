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
]
