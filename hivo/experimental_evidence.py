"""Provider-free experimental evidence engine for CORE-3.

This module orchestrates bounded diagnostic probes.  It never commits, edits
the canonical project, writes Project Brain, promotes a candidate, or claims
formal root-cause proof.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from threading import Thread
from typing import Any, Callable, Iterable, Mapping

from .diagnostic_hypotheses import (
    ACTIVE, BASELINE_UNSTABLE, BLOCKED, BUDGET_REACHED, CLOSED,
    DETERMINISTIC_SEED, DiagnosticBudget, DiagnosticFailureEvidence,
    DiagnosticHypothesis, DiagnosticSession, EFFECT_INCONCLUSIVE,
    ELIMINATED, EVIDENCE_SUFFICIENT, HYPOTHESIS_ACTIVE, INCONCLUSIVE,
    MODERATE, READY, STRONG, STRONGLY_WEAKENED, SUPPORTED, WEAK,
    apply_hypothesis_effect, classify_effect, seed_hypotheses,
)
from .experiment_sandbox import (
    DNT_PROTECTED, EXPERIMENTAL_PROBE_BLOCKED_DNT, INVALID_INTERVENTION,
    CounterfactualMutationSpec, ExperimentalSandbox, SandboxMutationResult,
    canonical_subject_hash, subject_tree_snapshot,
)
from .experiment_selector import (
    BASELINE_REPRODUCTION, COUNTERFACTUAL_MUTATION, DEPENDENCY_STUB,
    DiagnosticExperiment, ExperimentSelector, INPUT_PERTURBATION,
    OBSERVATION_ONLY, TARGETED_TEST,
)
from .project_brain_refs import TypedReference, canonical_hash
from .task_working_set import TaskWorkingSet


FAILURE_PERSISTS = "FAILURE_PERSISTS"
FAILURE_DISAPPEARS = "FAILURE_DISAPPEARS"
FAILURE_CHANGES = "FAILURE_CHANGES"
TARGET_TEST_PASSES = "TARGET_TEST_PASSES"
TARGET_TEST_FAILS = "TARGET_TEST_FAILS"
GUARD_TEST_FAILS = "GUARD_TEST_FAILS"
NO_OBSERVABLE_CHANGE = "NO_OBSERVABLE_CHANGE"
EXECUTION_INVALID = "EXECUTION_INVALID"
OUTCOMES = (
    FAILURE_PERSISTS, FAILURE_DISAPPEARS, FAILURE_CHANGES,
    TARGET_TEST_PASSES, TARGET_TEST_FAILS, GUARD_TEST_FAILS,
    NO_OBSERVABLE_CHANGE, EXECUTION_INVALID,
)

BASELINE_REPRODUCED = "BASELINE_REPRODUCED"
BASELINE_NOT_REPRODUCED = "BASELINE_NOT_REPRODUCED"
BASELINE_UNSTABLE_STATUS = "BASELINE_UNSTABLE"

MASKING_RISK = "MASKING_RISK"
EVIDENCE_VALID = "VALID"
EVIDENCE_INVALID = "INVALID"

FOCUSED_REPAIR = "FOCUSED_REPAIR"
RUN_ANOTHER_EXPERIMENT = "RUN_ANOTHER_EXPERIMENT"
EXPAND_WORKING_SET = "EXPAND_WORKING_SET"
INVESTIGATE_FLAKINESS = "INVESTIGATE_FLAKINESS"
INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"

PROVENANCE_BASELINE = "BASELINE"
PROVENANCE_TARGET_TEST = "TARGET_TEST"
PROVENANCE_GUARD_TEST = "GUARD_TEST"
PROVENANCE_COUNTERFACTUAL = "COUNTERFACTUAL"
PROVENANCE_INPUT_PERTURBATION = "INPUT_PERTURBATION"
PROVENANCE_DEPENDENCY_STUB = "DEPENDENCY_STUB"
PROVENANCE_OBSERVATION = "OBSERVATION"

Runner = Callable[[Path, str], Any]


def _as_outcome(value: Any) -> tuple[str, bool, dict[str, Any]]:
    if isinstance(value, VerificationResult):
        return value.outcome, bool(value.passed), dict(value.details)
    if isinstance(value, Mapping):
        outcome = str(value.get("outcome", ""))
        passed = bool(value.get("passed", outcome in {TARGET_TEST_PASSES, FAILURE_DISAPPEARS}))
        details = dict(value.get("details", {}) or {})
        return outcome or (TARGET_TEST_PASSES if passed else TARGET_TEST_FAILS), passed, details
    if isinstance(value, bool):
        return (TARGET_TEST_PASSES if value else TARGET_TEST_FAILS), value, {}
    if value is None:
        return EXECUTION_INVALID, False, {"reason": "runner returned None"}
    text = str(value)
    return text, text in {TARGET_TEST_PASSES, FAILURE_DISAPPEARS}, {}


@dataclass(frozen=True)
class VerificationResult:
    check_id: str
    passed: bool
    outcome: str
    details: dict[str, Any] = field(default_factory=dict)
    is_guard: bool = False
    provider_calls: int = 0

    def __post_init__(self) -> None:
        if self.outcome not in OUTCOMES and not self.outcome.startswith("BASELINE"):
            object.__setattr__(self, "outcome", str(self.outcome))
        object.__setattr__(self, "check_id", str(self.check_id))
        object.__setattr__(self, "details", dict(self.details))
        object.__setattr__(self, "provider_calls", max(0, int(self.provider_calls)))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "check_id": self.check_id,
            "passed": self.passed,
            "outcome": self.outcome,
            "details": dict(self.details),
            "is_guard": self.is_guard,
            "provider_calls": self.provider_calls,
        }

    @classmethod
    def from_value(cls, value: Any, *, check_id: str, is_guard: bool = False) -> "VerificationResult":
        outcome, passed, details = _as_outcome(value)
        if isinstance(value, VerificationResult):
            return replace(value, check_id=check_id, is_guard=is_guard)
        return cls(check_id=check_id, passed=passed, outcome=outcome, details=details, is_guard=is_guard)


@dataclass(frozen=True)
class BaselineReceipt:
    session_id: str
    expected_outcome: str
    observed_outcome: str
    status: str
    sandbox_identity: str
    canonical_subject_identity_before: str
    canonical_subject_identity_after: str
    verification_results: tuple[VerificationResult, ...] = ()
    confirmation_count: int = 0
    provider_calls: int = 0
    model_calls: int = 0
    canonical_source_unchanged: bool = True
    reason: str = ""

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "session_id": self.session_id,
            "expected_outcome": self.expected_outcome,
            "observed_outcome": self.observed_outcome,
            "status": self.status,
            "sandbox_identity": self.sandbox_identity,
            "canonical_subject_identity_before": self.canonical_subject_identity_before,
            "canonical_subject_identity_after": self.canonical_subject_identity_after,
            "verification_results": [item.to_dict() for item in self.verification_results],
            "confirmation_count": self.confirmation_count,
            "provider_calls": self.provider_calls,
            "model_calls": self.model_calls,
            "canonical_source_unchanged": self.canonical_source_unchanged,
            "reason": self.reason,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class ExperimentReceipt:
    experiment: DiagnosticExperiment
    baseline_receipt_hash: str
    sandbox_identity: str
    canonical_subject_identity_before: str
    canonical_subject_identity_after: str
    intervention_hash: str = ""
    syntax_result: dict[str, Any] = field(default_factory=dict)
    targeted_verification_results: tuple[VerificationResult, ...] = ()
    guard_verification_results: tuple[VerificationResult, ...] = ()
    observed_outcome: str = EXECUTION_INVALID
    provider_calls: int = 0
    model_calls: int = 0
    filesystem_mutation_audit: dict[str, Any] = field(default_factory=dict)
    validity: str = EVIDENCE_INVALID
    invalid_reason: str = ""
    cost_metadata: dict[str, Any] = field(default_factory=dict)
    hypothesis_effects: tuple[tuple[str, str], ...] = ()
    masking_risks: tuple[str, ...] = ()

    @property
    def status(self) -> str:
        if self.validity == EVIDENCE_VALID:
            return EVIDENCE_VALID
        if self.invalid_reason == EXPERIMENTAL_PROBE_BLOCKED_DNT:
            return EXPERIMENTAL_PROBE_BLOCKED_DNT
        return INVALID_INTERVENTION

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "experiment": self.experiment.to_dict(),
            "baseline_receipt_hash": self.baseline_receipt_hash,
            "sandbox_identity": self.sandbox_identity,
            "canonical_subject_identity_before": self.canonical_subject_identity_before,
            "canonical_subject_identity_after": self.canonical_subject_identity_after,
            "intervention_hash": self.intervention_hash,
            "syntax_result": dict(self.syntax_result),
            "targeted_verification_results": [item.to_dict() for item in self.targeted_verification_results],
            "guard_verification_results": [item.to_dict() for item in self.guard_verification_results],
            "observed_outcome": self.observed_outcome,
            "provider_calls": self.provider_calls,
            "model_calls": self.model_calls,
            "filesystem_mutation_audit": dict(self.filesystem_mutation_audit),
            "validity": self.validity,
            "invalid_reason": self.invalid_reason,
            "cost_metadata": dict(self.cost_metadata),
            "hypothesis_effects": {key: value for key, value in self.hypothesis_effects},
            "masking_risks": list(self.masking_risks),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    experiment_receipt_hash: str
    hypothesis_effects: tuple[tuple[str, str], ...]
    strength: str
    provenance: str
    validity: str
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "evidence_id": self.evidence_id,
            "experiment_receipt_hash": self.experiment_receipt_hash,
            "hypothesis_effects": {key: value for key, value in self.hypothesis_effects},
            "strength": self.strength,
            "provenance": self.provenance,
            "validity": self.validity,
            "reason": self.reason,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class ExperimentalEvidenceLedger:
    session_id: str
    entries: tuple[EvidenceItem, ...] = ()

    @property
    def ledger_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def canonical_hash(self) -> str:
        return self.ledger_hash

    def add(self, item: EvidenceItem) -> "ExperimentalEvidenceLedger":
        return replace(self, entries=self.entries + (item,))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"session_id": self.session_id, "entries": [item.to_dict() for item in self.entries]}
        if include_hash:
            value["ledger_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class DiagnosticResult:
    session: DiagnosticSession
    status: str
    baseline_receipt: BaselineReceipt | None
    hypotheses_before: tuple[DiagnosticHypothesis, ...]
    hypotheses_after: tuple[DiagnosticHypothesis, ...]
    experiments_considered: tuple[DiagnosticExperiment, ...] = ()
    experiments_executed: tuple[ExperimentReceipt, ...] = ()
    evidence_ledger: ExperimentalEvidenceLedger = field(default_factory=lambda: ExperimentalEvidenceLedger(""))
    best_current_suspects: tuple[str, ...] = ()
    eliminated_hypotheses: tuple[str, ...] = ()
    strongly_weakened_hypotheses: tuple[str, ...] = ()
    budget_usage: dict[str, int] = field(default_factory=dict)
    working_set_expansions: tuple[dict[str, Any], ...] = ()
    masking_risks: tuple[dict[str, Any], ...] = ()
    canonical_subject_unchanged: bool = True
    recommended_next_action: str = INSUFFICIENT_EVIDENCE
    timeline: tuple[dict[str, Any], ...] = ()
    metrics: dict[str, int] = field(default_factory=dict)

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "session": self.session.to_dict(),
            "status": self.status,
            "baseline_receipt": self.baseline_receipt.to_dict() if self.baseline_receipt else None,
            "hypotheses_before": [item.to_dict() for item in self.hypotheses_before],
            "hypotheses_after": [item.to_dict() for item in self.hypotheses_after],
            "experiments_considered": [item.to_dict() for item in self.experiments_considered],
            "experiments_executed": [item.to_dict() for item in self.experiments_executed],
            "evidence_ledger": self.evidence_ledger.to_dict(),
            "best_current_suspects": list(self.best_current_suspects),
            "eliminated_hypotheses": list(self.eliminated_hypotheses),
            "strongly_weakened_hypotheses": list(self.strongly_weakened_hypotheses),
            "budget_usage": dict(self.budget_usage),
            "working_set_expansions": list(self.working_set_expansions),
            "masking_risks": list(self.masking_risks),
            "canonical_subject_unchanged": self.canonical_subject_unchanged,
            "recommended_next_action": self.recommended_next_action,
            "timeline": list(self.timeline),
            "metrics": dict(self.metrics),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def new_core3_metrics() -> dict[str, int]:
    return {
        key: 0 for key in (
            "diagnostic_sessions", "baseline_runs", "baseline_confirmations",
            "baseline_unstable", "hypotheses_seeded", "hypotheses_active_peak",
            "experiments_proposed", "experiments_selected", "experiments_executed",
            "counterfactual_mutations", "targeted_tests_run", "guard_tests_run",
            "invalid_interventions", "masking_risks", "hypotheses_supported",
            "hypotheses_weakened", "hypotheses_eliminated", "working_set_expansions",
            "duplicate_experiments_suppressed", "diagnostic_budget_reached",
            "canonical_files_changed", "provider_calls", "experiments_to_primary_suspect",
            "hypotheses_pruned_per_experiment", "targeted_tests_per_session",
            "counterfactuals_per_session", "working_set_files_touched",
            "sandbox_files_materialized", "sandbox_bytes_materialized",
        )
    }


def _metric(metrics: dict[str, int], key: str, amount: int = 1) -> None:
    metrics[key] = metrics.get(key, 0) + int(amount)


def _runner_result(
    runner: Runner | None,
    sandbox_root: Path,
    check_id: str,
    *,
    is_guard: bool = False,
    timeout_seconds: int = 30,
) -> VerificationResult:
    if runner is None:
        return VerificationResult(check_id, False, EXECUTION_INVALID, {"reason": "no bounded verification runner"}, is_guard=is_guard)
    holder: dict[str, Any] = {}

    def invoke() -> None:
        try:
            holder["value"] = runner(sandbox_root, check_id)
        except Exception as exc:  # pragma: no cover - exercised by focused timeout/exception fixtures
            holder["error"] = exc

    thread = Thread(target=invoke, name="hivo-core3-diagnostic-check", daemon=True)
    thread.start()
    thread.join(timeout=max(1, int(timeout_seconds)))
    if thread.is_alive():
        return VerificationResult(check_id, False, EXECUTION_INVALID, {"reason": "timeout", "timeout_seconds": int(timeout_seconds)}, is_guard=is_guard)
    if "error" in holder:
        exc = holder["error"]
        return VerificationResult(check_id, False, EXECUTION_INVALID, {"reason": "runner_exception", "error_type": type(exc).__name__}, is_guard=is_guard)
    return VerificationResult.from_value(holder.get("value"), check_id=check_id, is_guard=is_guard)


def _observed_outcome(target: tuple[VerificationResult, ...], guards: tuple[VerificationResult, ...]) -> tuple[str, tuple[str, ...]]:
    if not target:
        return EXECUTION_INVALID, ()
    if any(not result.passed and result.outcome == EXECUTION_INVALID for result in target + guards):
        return EXECUTION_INVALID, ()
    masking: list[str] = []
    if any(not result.passed for result in guards):
        masking.append("guard_regression")
    if target[0].passed:
        if masking:
            return TARGET_TEST_PASSES, tuple(masking)
        return TARGET_TEST_PASSES, ()
    if any(result.outcome == FAILURE_CHANGES for result in target):
        return FAILURE_CHANGES, tuple(masking)
    return TARGET_TEST_FAILS, tuple(masking)


def _provenance_for(kind: str) -> str:
    return {
        COUNTERFACTUAL_MUTATION: PROVENANCE_COUNTERFACTUAL,
        INPUT_PERTURBATION: PROVENANCE_INPUT_PERTURBATION,
        DEPENDENCY_STUB: PROVENANCE_DEPENDENCY_STUB,
        TARGETED_TEST: PROVENANCE_TARGET_TEST,
    }.get(kind, PROVENANCE_OBSERVATION)


class ExperimentalEvidenceEngine:
    """Bounded diagnostic orchestration independent of Worker/provider execution."""

    def __init__(
        self,
        canonical_root: str | Path,
        *,
        repository_map: Any = None,
        working_set: TaskWorkingSet | None = None,
        authority: Mapping[str, Any] | None = None,
        dnt_paths: Iterable[str] = (),
        budget: DiagnosticBudget | Mapping[str, Any] | None = None,
        runner: Runner | None = None,
        selector: ExperimentSelector | None = None,
    ) -> None:
        self.canonical_root = Path(canonical_root).expanduser().resolve()
        if not self.canonical_root.is_dir():
            raise ValueError("canonical diagnostic root must be a directory")
        self.repository_map = repository_map
        self.working_set = working_set
        self.authority = dict(authority or {})
        self.dnt_paths = tuple(str(item).replace("\\", "/") for item in dnt_paths)
        self.budget = DiagnosticBudget(**dict(budget)) if isinstance(budget, Mapping) else (budget or DiagnosticBudget())
        self.runner = runner
        self.selector = selector or ExperimentSelector()
        self.metrics = new_core3_metrics()
        self.ledger: ExperimentalEvidenceLedger | None = None
        self._executed_hashes: set[str] = set()
        self._working_set_expansions: list[dict[str, Any]] = []

    def create_session(
        self,
        task_query_identity: str,
        failure_evidence: DiagnosticFailureEvidence | Mapping[str, Any] | Iterable[Any],
        *,
        session_id: str = "",
        subject_identity: str = "",
        revision_identity: str = "",
        hypotheses: Iterable[DiagnosticHypothesis] | None = None,
        status: str = READY,
    ) -> DiagnosticSession:
        if isinstance(failure_evidence, (DiagnosticFailureEvidence, Mapping)):
            failures = (DiagnosticFailureEvidence.from_value(failure_evidence),)
        else:
            failures = tuple(DiagnosticFailureEvidence.from_value(item) for item in failure_evidence)
        working_identity = self.working_set.canonical_hash if self.working_set else ""
        chosen = tuple(hypotheses or seed_hypotheses(failures, self.working_set, max_seeds=self.budget.max_deterministic_seeds, task_query_identity=task_query_identity))
        chosen = chosen[: self.budget.max_active_hypotheses]
        if not session_id:
            session_id = f"DS-{canonical_hash({'query': task_query_identity, 'failure': [item.canonical_hash for item in failures]})[:12]}"
        session = DiagnosticSession(
            session_id=session_id,
            task_query_identity=task_query_identity,
            subject_identity=subject_identity,
            revision_identity=revision_identity,
            working_set_identity=working_identity,
            failure_evidence=failures,
            authority_context=self.authority,
            dnt_context=self.dnt_paths,
            experiment_budget=self.budget,
            hypotheses=chosen,
            status=status,
        )
        self.ledger = ExperimentalEvidenceLedger(session.evidence_ledger_identity)
        _metric(self.metrics, "diagnostic_sessions")
        _metric(self.metrics, "hypotheses_seeded", len(chosen))
        self.metrics["hypotheses_active_peak"] = max(self.metrics.get("hypotheses_active_peak", 0), len(chosen))
        return session

    def run_baseline(
        self,
        session: DiagnosticSession,
        *,
        check_id: str = "target",
        expected_outcome: str | None = None,
        runner: Runner | None = None,
        confirmation_runner: Runner | None = None,
    ) -> BaselineReceipt:
        expected = expected_outcome or (session.failure_evidence[0].expected_outcome if session.failure_evidence else TARGET_TEST_FAILS)
        active_runner = runner or self.runner
        before = canonical_subject_hash(self.canonical_root)
        results: list[VerificationResult] = []
        with ExperimentalSandbox(self.canonical_root, session_id=session.session_id, authority=self.authority, dnt_paths=self.dnt_paths) as sandbox:
            first = _runner_result(active_runner, sandbox.sandbox_root, check_id, timeout_seconds=self.budget.timeout_seconds)
            results.append(first)
            sandbox_identity = sandbox.sandbox_identity
            _metric(self.metrics, "baseline_runs")
            self.metrics["sandbox_files_materialized"] += sandbox.sandbox_files_materialized
            self.metrics["sandbox_bytes_materialized"] += sandbox.sandbox_bytes_materialized
            observed = first.outcome
            confirmation_count = 0
            if (confirmation_runner is not None or observed != expected) and self.budget.max_baseline_confirmations > 0:
                confirm = _runner_result(confirmation_runner or active_runner, sandbox.sandbox_root, check_id, timeout_seconds=self.budget.timeout_seconds)
                results.append(confirm)
                confirmation_count = 1
                _metric(self.metrics, "baseline_confirmations")
                if confirm.outcome != observed:
                    status = BASELINE_UNSTABLE_STATUS
                    _metric(self.metrics, "baseline_unstable")
                    reason = "bounded baseline confirmation disagreed with first result"
                elif observed == expected:
                    status = BASELINE_REPRODUCED
                    reason = "baseline matched expected failure outcome"
                else:
                    status = BASELINE_NOT_REPRODUCED
                    reason = "baseline consistently differed from expected evidence"
            elif observed == expected:
                status = BASELINE_REPRODUCED
                reason = "baseline matched expected failure outcome"
            else:
                status = BASELINE_NOT_REPRODUCED
                reason = "baseline did not reproduce expected failure"
            unchanged_inside = sandbox.canonical_unchanged()
        after = canonical_subject_hash(self.canonical_root)
        return BaselineReceipt(
            session_id=session.session_id, expected_outcome=expected, observed_outcome=observed,
            status=status, sandbox_identity=sandbox_identity,
            canonical_subject_identity_before=before,
            canonical_subject_identity_after=after,
            verification_results=tuple(results), confirmation_count=confirmation_count,
            provider_calls=sum(item.provider_calls for item in results), model_calls=0,
            canonical_source_unchanged=before == after and unchanged_inside, reason=reason,
        )

    def execute_experiment(
        self,
        session: DiagnosticSession,
        experiment: DiagnosticExperiment,
        baseline: BaselineReceipt,
        *,
        runner: Runner | None = None,
    ) -> ExperimentReceipt:
        before = canonical_subject_hash(self.canonical_root)
        target_results: list[VerificationResult] = []
        guard_results: list[VerificationResult] = []
        mutation_result: SandboxMutationResult | None = None
        invalid_reason = ""
        masking: tuple[str, ...] = ()
        with ExperimentalSandbox(self.canonical_root, session_id=session.session_id, authority=self.authority, dnt_paths=self.dnt_paths) as sandbox:
            _metric(self.metrics, "sandbox_files_materialized", sandbox.sandbox_files_materialized)
            _metric(self.metrics, "sandbox_bytes_materialized", sandbox.sandbox_bytes_materialized)
            if experiment.mutation_spec is not None:
                _metric(self.metrics, "counterfactual_mutations")
                mutation_result = sandbox.apply_mutation(experiment.mutation_spec)
                if not mutation_result.valid or mutation_result.status != "EXPERIMENTAL_MUTATION_APPLIED":
                    invalid_reason = mutation_result.reason or mutation_result.status
                elif mutation_result.syntax is None or not mutation_result.syntax.valid:
                    invalid_reason = "syntax validation failed"
                if mutation_result.status == EXPERIMENTAL_PROBE_BLOCKED_DNT:
                    invalid_reason = EXPERIMENTAL_PROBE_BLOCKED_DNT
                if invalid_reason:
                    _metric(self.metrics, "invalid_interventions")
            if not invalid_reason:
                checks = tuple(experiment.verification_checks)
                if checks:
                    target_results.append(_runner_result(runner or self.runner, sandbox.sandbox_root, checks[0], timeout_seconds=self.budget.timeout_seconds))
                    _metric(self.metrics, "targeted_tests_run")
                else:
                    invalid_reason = "targeted verification was not specified"
                guard_names = tuple(experiment.metadata.get("guard_checks", ()) or ())[: self.budget.max_guard_tests_per_experiment]
                for check in guard_names:
                    guard_results.append(_runner_result(runner or self.runner, sandbox.sandbox_root, str(check), is_guard=True, timeout_seconds=self.budget.timeout_seconds))
                    _metric(self.metrics, "guard_tests_run")
                observed, masking = _observed_outcome(tuple(target_results), tuple(guard_results))
            else:
                observed = EXECUTION_INVALID
            if observed == EXECUTION_INVALID and not invalid_reason:
                invalid_reason = "target verification unavailable or invalid"
            sandbox_identity = sandbox.sandbox_identity
            mutation_hash = mutation_result.intervention_hash if mutation_result else ""
            syntax_result = mutation_result.syntax.to_dict() if mutation_result and mutation_result.syntax else {}
            sandbox_changed = bool(mutation_result and mutation_result.filesystem_changed)
            canonical_inside = sandbox.canonical_unchanged()
        after = canonical_subject_hash(self.canonical_root)
        canonical_unchanged = before == after and canonical_inside
        if not canonical_unchanged:
            _metric(self.metrics, "canonical_files_changed")
            invalid_reason = invalid_reason or "canonical subject changed during diagnostic execution"
        if masking:
            _metric(self.metrics, "masking_risks")
        validity = EVIDENCE_VALID if not invalid_reason and canonical_unchanged else EVIDENCE_INVALID
        if validity == EVIDENCE_INVALID and not invalid_reason:
            invalid_reason = "experiment did not produce a valid observation"
        return ExperimentReceipt(
            experiment=experiment, baseline_receipt_hash=baseline.canonical_hash,
            sandbox_identity=sandbox_identity, canonical_subject_identity_before=before,
            canonical_subject_identity_after=after, intervention_hash=mutation_hash,
            syntax_result=syntax_result,
            targeted_verification_results=tuple(target_results),
            guard_verification_results=tuple(guard_results), observed_outcome=observed,
            provider_calls=sum(item.provider_calls for item in target_results + guard_results),
            filesystem_mutation_audit={
                "sandbox_changed": sandbox_changed,
                "canonical_unchanged": canonical_unchanged,
                "canonical_mutation_allowed": False,
                "git_commit_attempted": False,
            }, validity=validity, invalid_reason=invalid_reason,
            cost_metadata={"cost_class": experiment.estimated_cost_class},
            masking_risks=masking,
        )

    def _update_from_receipt(
        self,
        hypotheses: tuple[DiagnosticHypothesis, ...],
        receipt: ExperimentReceipt,
    ) -> tuple[tuple[DiagnosticHypothesis, ...], EvidenceItem]:
        effects: list[tuple[str, str]] = []
        strength = STRONG if receipt.validity == EVIDENCE_VALID and not receipt.masking_risks else WEAK
        for hypothesis in hypotheses:
            predicted = receipt.experiment.prediction_for(hypothesis.hypothesis_id)
            effect = classify_effect(
                predicted, receipt.observed_outcome,
                valid=receipt.validity == EVIDENCE_VALID,
                masking_risk=bool(receipt.masking_risks),
            )
            if hypothesis.hypothesis_id in receipt.experiment.target_hypothesis_ids:
                effects.append((hypothesis.hypothesis_id, effect))
        evidence_id = f"E-{receipt.canonical_hash[:12]}"
        item = EvidenceItem(
            evidence_id=evidence_id,
            experiment_receipt_hash=receipt.canonical_hash,
            hypothesis_effects=tuple(sorted(effects)),
            strength=strength,
            provenance=_provenance_for(receipt.experiment.kind),
            validity=receipt.validity,
            reason=("guard_regression" if receipt.masking_risks else (receipt.invalid_reason or "prediction evaluated against observed outcome")),
            metadata={"observed_outcome": receipt.observed_outcome, "masking_risks": list(receipt.masking_risks)},
        )
        updated: list[DiagnosticHypothesis] = []
        for hypothesis in hypotheses:
            effect = dict(effects).get(hypothesis.hypothesis_id)
            if effect is None:
                updated.append(hypothesis)
                continue
            revised = apply_hypothesis_effect(hypothesis, effect, evidence_id=evidence_id, strength=strength)
            updated.append(revised)
            if effect == "SUPPORTS":
                _metric(self.metrics, "hypotheses_supported")
            elif effect in {"WEAKENS", "STRONGLY_WEAKENS"}:
                _metric(self.metrics, "hypotheses_weakened")
            if revised.status == ELIMINATED and hypothesis.status != ELIMINATED:
                _metric(self.metrics, "hypotheses_eliminated")
        return tuple(updated), replace(item, hypothesis_effects=tuple(sorted(effects)))

    def run(
        self,
        session: DiagnosticSession,
        experiments: Iterable[DiagnosticExperiment],
        *,
        baseline_check: str = "target",
        expected_baseline_outcome: str | None = None,
        runner: Runner | None = None,
        confirmation_runner: Runner | None = None,
    ) -> DiagnosticResult:
        considered = tuple(experiments)
        _metric(self.metrics, "experiments_proposed", len(considered))
        baseline = self.run_baseline(
            session, check_id=baseline_check, expected_outcome=expected_baseline_outcome,
            runner=runner, confirmation_runner=confirmation_runner,
        )
        hypotheses_before = tuple(session.hypotheses)
        hypotheses = hypotheses_before
        if baseline.status != BASELINE_REPRODUCED:
            status = BASELINE_UNSTABLE if baseline.status == BASELINE_UNSTABLE_STATUS else BLOCKED
            action = INVESTIGATE_FLAKINESS if baseline.status == BASELINE_UNSTABLE_STATUS else INSUFFICIENT_EVIDENCE
            return self._result(session, status, baseline, hypotheses_before, hypotheses, considered, (), action, ())
        self.ledger = self.ledger or ExperimentalEvidenceLedger(session.evidence_ledger_identity)
        executed: list[ExperimentReceipt] = []
        timeline: list[dict[str, Any]] = []
        status = ACTIVE
        while len(executed) < self.budget.max_total_experiments:
            used_mutations = sum(item.experiment.mutation_spec is not None for item in executed)
            used_targeted = sum(len(item.targeted_verification_results) for item in executed)
            eligible = tuple(
                item for item in considered
                if item.kind != BASELINE_REPRODUCTION
                and not (item.mutation_spec is not None and used_mutations >= self.budget.max_counterfactual_mutations)
                and not (item.verification_checks and used_targeted >= self.budget.max_targeted_tests)
            )
            decision = self.selector.rank(eligible, hypotheses, executed_hashes=self._executed_hashes)
            _metric(self.metrics, "duplicate_experiments_suppressed", sum(item.get("reason") == "duplicate_experiment" for item in decision.skipped))
            if decision.selected is None:
                break
            experiment = decision.selected
            _metric(self.metrics, "experiments_selected")
            receipt = self.execute_experiment(session, experiment, baseline, runner=runner)
            self._executed_hashes.add(experiment.canonical_hash)
            executed.append(receipt)
            _metric(self.metrics, "experiments_executed")
            if receipt.validity == EVIDENCE_INVALID:
                _metric(self.metrics, "invalid_interventions")
            hypotheses, evidence = self._update_from_receipt(hypotheses, receipt)
            self.ledger = self.ledger.add(evidence)
            timeline.append({
                "ordinal": len(executed),
                "experiment_id": experiment.experiment_id,
                "experiment_hash": experiment.canonical_hash,
                "target_hypotheses": list(experiment.target_hypothesis_ids),
                "intervention": experiment.intervention_description,
                "observed_outcome": receipt.observed_outcome,
                "hypothesis_effects": dict(evidence.hypothesis_effects),
                "remaining_active_hypotheses": [item.hypothesis_id for item in hypotheses if item.status not in {ELIMINATED, STRONGLY_WEAKENED}],
                "budget_remaining": self.budget.max_total_experiments - len(executed),
            })
            if self._evidence_sufficient(hypotheses, executed):
                status = EVIDENCE_SUFFICIENT
                break
        if status == ACTIVE:
            if len(executed) >= self.budget.max_total_experiments:
                status = BUDGET_REACHED
                _metric(self.metrics, "diagnostic_budget_reached")
            else:
                status = INCONCLUSIVE
        action = self._recommended_action(status, hypotheses, executed)
        if status == BUDGET_REACHED:
            action = RUN_ANOTHER_EXPERIMENT
        return self._result(session, status, baseline, hypotheses_before, hypotheses, considered, tuple(executed), action, tuple(timeline))

    def _evidence_sufficient(self, hypotheses: tuple[DiagnosticHypothesis, ...], executed: list[ExperimentReceipt]) -> bool:
        valid_nonmasking = [item for item in executed if item.validity == EVIDENCE_VALID and not item.masking_risks]
        supported = [item for item in hypotheses if item.status == SUPPORTED]
        alternatives = [item for item in hypotheses if item.status not in {SUPPORTED, ELIMINATED, STRONGLY_WEAKENED}]
        return bool(valid_nonmasking and supported and not alternatives and len(hypotheses) > 1)

    def _recommended_action(self, status: str, hypotheses: tuple[DiagnosticHypothesis, ...], executed: list[ExperimentReceipt]) -> str:
        if status == EVIDENCE_SUFFICIENT:
            return FOCUSED_REPAIR
        if any(item.masking_risks for item in executed):
            return INSUFFICIENT_EVIDENCE
        if status == BASELINE_UNSTABLE:
            return INVESTIGATE_FLAKINESS
        if any(item.status not in {ELIMINATED, STRONGLY_WEAKENED} for item in hypotheses):
            return RUN_ANOTHER_EXPERIMENT
        return INSUFFICIENT_EVIDENCE

    def _result(
        self,
        session: DiagnosticSession,
        status: str,
        baseline: BaselineReceipt | None,
        before: tuple[DiagnosticHypothesis, ...],
        after: tuple[DiagnosticHypothesis, ...],
        considered: tuple[DiagnosticExperiment, ...],
        executed: tuple[ExperimentReceipt, ...],
        action: str,
        timeline: tuple[dict[str, Any], ...],
    ) -> DiagnosticResult:
        best = tuple(item.hypothesis_id for item in sorted(after, key=lambda item: (-item.current_evidence_score, item.hypothesis_id)) if item.status not in {ELIMINATED, STRONGLY_WEAKENED})
        eliminated = tuple(item.hypothesis_id for item in after if item.status == ELIMINATED)
        weakened = tuple(item.hypothesis_id for item in after if item.status == STRONGLY_WEAKENED)
        self.metrics["experiments_to_primary_suspect"] = len(executed) if any(item.status == SUPPORTED for item in after) else 0
        self.metrics["hypotheses_pruned_per_experiment"] = int(sum(item.status in {ELIMINATED, STRONGLY_WEAKENED} for item in after) / max(1, len(executed)))
        self.metrics["targeted_tests_per_session"] = sum(len(item.targeted_verification_results) for item in executed)
        self.metrics["counterfactuals_per_session"] = sum(item.experiment.mutation_spec is not None for item in executed)
        self.metrics["working_set_files_touched"] = len(self.working_set.files) if self.working_set else 0
        canonical_unchanged = all(item.filesystem_mutation_audit.get("canonical_unchanged", False) for item in executed) and (baseline.canonical_source_unchanged if baseline else True)
        updated_session = session.with_updates(hypotheses=after, status=status)
        masking = tuple({"experiment_id": item.experiment.experiment_id, "risk": MASKING_RISK, "reasons": list(item.masking_risks)} for item in executed if item.masking_risks)
        usage = {
            "experiments": len(executed),
            "counterfactual_mutations": sum(item.experiment.mutation_spec is not None for item in executed),
            "baseline_confirmations": baseline.confirmation_count if baseline else 0,
            "targeted_tests": sum(len(item.targeted_verification_results) for item in executed),
            "guard_tests": sum(len(item.guard_verification_results) for item in executed),
            "max_total_experiments": self.budget.max_total_experiments,
        }
        return DiagnosticResult(
            session=updated_session, status=status, baseline_receipt=baseline,
            hypotheses_before=before, hypotheses_after=after,
            experiments_considered=considered, experiments_executed=executed,
            evidence_ledger=self.ledger or ExperimentalEvidenceLedger(session.evidence_ledger_identity),
            best_current_suspects=best[: self.budget.max_active_hypotheses],
            eliminated_hypotheses=eliminated, strongly_weakened_hypotheses=weakened,
            budget_usage=usage, working_set_expansions=tuple(self._working_set_expansions),
            masking_risks=masking, canonical_subject_unchanged=canonical_unchanged,
            recommended_next_action=action, timeline=timeline, metrics=dict(self.metrics),
        )

    def request_working_set_expansion(
        self,
        query: str | Mapping[str, Any],
        *,
        lexical_index: Any = None,
    ) -> TaskWorkingSet | None:
        """Request bounded CORE-2 expansion only when evidence justifies it."""
        if self.repository_map is None or len(self._working_set_expansions) >= self.budget.max_working_set_expansions:
            return None
        from .repo_intelligence import search_repository
        result = search_repository(
            query, self.repository_map, self.canonical_root,
            lexical_index=lexical_index, authority=self.authority,
        )
        if result.working_set is None:
            return None
        self.working_set = result.working_set
        event = {
            "reason": "diagnostic evidence requested bounded repository context",
            "query": str(query),
            "working_set_hash": result.working_set.canonical_hash,
            "files": list(result.working_set.files),
            "budget_impact": dict(result.working_set.budget_usage),
        }
        self._working_set_expansions.append(event)
        _metric(self.metrics, "working_set_expansions")
        self.metrics["working_set_files_touched"] = len(result.working_set.files)
        return result.working_set


def generate_test_failure_experiments(
    session: DiagnosticSession,
    *,
    target_check: str,
    guard_checks: Iterable[str] = (),
    mutation_specs: Iterable[CounterfactualMutationSpec] = (),
) -> tuple[DiagnosticExperiment, ...]:
    """Generate bounded deterministic experiments; predictions precede execution."""
    hypotheses = tuple(session.hypotheses)
    guard = tuple(str(item) for item in guard_checks)
    experiments: list[DiagnosticExperiment] = []
    experiments.append(DiagnosticExperiment(
        experiment_id="E-BASELINE-1", kind=BASELINE_REPRODUCTION,
        goal="Reproduce the structured failure before causal probes",
        target_hypothesis_ids=tuple(item.hypothesis_id for item in hypotheses),
        target_references=tuple(ref for item in hypotheses for ref in item.target_references),
        predicted_outcomes=tuple((item.hypothesis_id, TARGET_TEST_FAILS) for item in hypotheses),
        intervention_description="no intervention; isolated baseline reproduction",
        verification_checks=(target_check,), verification_command=target_check,
        sandbox_requirements=("isolated_copy",), estimated_cost_class="CHEAP", risk_class="LOW",
    ))
    for index, hypothesis in enumerate(hypotheses):
        experiments.append(DiagnosticExperiment(
            experiment_id=f"E-TARGET-{index + 1}", kind=TARGETED_TEST,
            goal=f"Observe the target check around {hypothesis.hypothesis_id}",
            target_hypothesis_ids=(hypothesis.hypothesis_id,),
            target_references=hypothesis.target_references,
            predicted_outcomes=((hypothesis.hypothesis_id, TARGET_TEST_FAILS),),
            intervention_description="no intervention; run the named target check",
            verification_checks=(target_check,), sandbox_requirements=("isolated_copy",),
            estimated_cost_class="CHEAP", risk_class="LOW",
            expected_discrimination_score=0, metadata={"guard_checks": guard},
        ))
    for index, spec in enumerate(mutation_specs):
        predictions = tuple((hypothesis.hypothesis_id, TARGET_TEST_PASSES) for hypothesis in hypotheses if hypothesis.hypothesis_id in spec.hypothesis_ids)
        experiments.append(DiagnosticExperiment(
            experiment_id=f"E-PROBE-{index + 1}", kind=COUNTERFACTUAL_MUTATION,
            goal=spec.reason or "bounded counterfactual probe",
            target_hypothesis_ids=tuple(key for key, _ in predictions), target_references=(spec.target_reference,),
            predicted_outcomes=predictions, intervention_description="temporary anchored sandbox mutation",
            verification_checks=(target_check,), sandbox_requirements=("isolated_copy", "syntax_validation"),
            estimated_cost_class="MEDIUM", risk_class="CONTROLLED", expected_discrimination_score=1,
            mutation_spec=spec, metadata={"guard_checks": guard},
        ))
    return tuple(experiments)


def generate_dependency_stub_experiment(
    session: DiagnosticSession,
    *,
    check: str,
    stub_description: str,
    predicted_outcomes: Mapping[str, str],
    target_references: Iterable[TypedReference] = (),
) -> DiagnosticExperiment:
    return DiagnosticExperiment(
        experiment_id=f"E-DEPENDENCY-{canonical_hash({'session': session.session_id, 'stub': stub_description})[:10]}",
        kind=DEPENDENCY_STUB, goal="Discriminate dependency output from consumer behavior",
        target_hypothesis_ids=tuple(sorted(str(key) for key in predicted_outcomes)),
        target_references=tuple(target_references), predicted_outcomes=tuple(predicted_outcomes.items()),
        intervention_description=stub_description, verification_checks=(check,),
        sandbox_requirements=("isolated_copy", "dependency_seam"), estimated_cost_class="MEDIUM",
        risk_class="CONTROLLED",
    )


def generate_input_perturbation_experiment(
    session: DiagnosticSession,
    *,
    check: str,
    description: str,
    predicted_outcomes: Mapping[str, str],
    target_references: Iterable[TypedReference] = (),
) -> DiagnosticExperiment:
    return DiagnosticExperiment(
        experiment_id=f"E-INPUT-{canonical_hash({'session': session.session_id, 'description': description})[:10]}",
        kind=INPUT_PERTURBATION, goal="Discriminate input-sensitive hypotheses",
        target_hypothesis_ids=tuple(sorted(str(key) for key in predicted_outcomes)),
        target_references=tuple(target_references), predicted_outcomes=tuple(predicted_outcomes.items()),
        intervention_description=description, verification_checks=(check,),
        sandbox_requirements=("isolated_copy",), estimated_cost_class="MEDIUM", risk_class="CONTROLLED",
    )


def session_from_recovery_failure(
    engine: ExperimentalEvidenceEngine,
    recovery_failure: Mapping[str, Any] | DiagnosticFailureEvidence,
    *,
    task_query_identity: str = "recovery-failure",
    **kwargs: Any,
) -> DiagnosticSession:
    failure = DiagnosticFailureEvidence.from_value(recovery_failure)
    if failure.source_type in {"", "UNKNOWN"}:
        failure = replace(failure, source_type="RECOVERY_DERIVED")
    return engine.create_session(task_query_identity, failure, **kwargs)


def benchmark_diagnostic_scenarios(scenarios: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Run deterministic diagnostic scenarios and report architecture metrics.

    ``known_hypothesis_id`` is used only after execution for fixture scoring;
    it is never supplied to the selector or engine as decision authority.
    """
    reports: list[dict[str, Any]] = []
    for scenario in scenarios:
        engine = scenario["engine"]
        session = scenario["session"]
        before_ids = [item.hypothesis_id for item in session.hypotheses]
        result = engine.run(
            session, scenario.get("experiments", ()),
            baseline_check=str(scenario.get("baseline_check", "target")),
            expected_baseline_outcome=scenario.get("expected_baseline_outcome"),
            runner=scenario.get("runner"),
            confirmation_runner=scenario.get("confirmation_runner"),
        )
        known = str(scenario.get("known_hypothesis_id", ""))
        after_ids = [str(item) for item in result.best_current_suspects]
        reports.append({
            "name": str(scenario.get("name", "scenario")),
            "status": result.status,
            "known_root_cause_rank_before": (before_ids.index(known) + 1) if known in before_ids else 0,
            "known_root_cause_rank_after": (after_ids.index(known) + 1) if known in after_ids else 0,
            "hypotheses_pruned": len(result.eliminated_hypotheses) + len(result.strongly_weakened_hypotheses),
            "experiments_executed": len(result.experiments_executed),
            "counterfactuals_used": sum(item.experiment.mutation_spec is not None for item in result.experiments_executed),
            "masking_risks_caught": len(result.masking_risks),
            "incorrect_eliminations": int(scenario.get("known_eliminated", "") in result.eliminated_hypotheses),
            "canonical_source_mutations": int(not result.canonical_subject_unchanged),
        })
    return {
        "benchmark_kind": "DETERMINISTIC_DIAGNOSTIC_ARCHITECTURE",
        "scenarios": reports,
        "provider_calls": 0,
        "model_calls": 0,
    }


def generate_error_location_experiments(
    session: DiagnosticSession,
    *,
    observation_check: str = "observe_target_location",
) -> tuple[DiagnosticExperiment, ...]:
    return tuple(
        DiagnosticExperiment(
            experiment_id=f"E-OBS-{index + 1}", kind=OBSERVATION_ONLY,
            goal=f"Observe typed failure reference {hypothesis.hypothesis_id}",
            target_hypothesis_ids=(hypothesis.hypothesis_id,), target_references=hypothesis.target_references,
            predicted_outcomes=((hypothesis.hypothesis_id, NO_OBSERVABLE_CHANGE),),
            intervention_description="metadata-only observation", verification_checks=(observation_check,),
            estimated_cost_class="CHEAP", risk_class="LOW",
        ) for index, hypothesis in enumerate(session.hypotheses)
    )


__all__ = [
    "FAILURE_PERSISTS", "FAILURE_DISAPPEARS", "FAILURE_CHANGES", "TARGET_TEST_PASSES",
    "TARGET_TEST_FAILS", "GUARD_TEST_FAILS", "NO_OBSERVABLE_CHANGE", "EXECUTION_INVALID",
    "BASELINE_REPRODUCED", "BASELINE_NOT_REPRODUCED", "BASELINE_UNSTABLE_STATUS", "MASKING_RISK",
    "EVIDENCE_VALID", "EVIDENCE_INVALID", "FOCUSED_REPAIR", "RUN_ANOTHER_EXPERIMENT",
    "EXPAND_WORKING_SET", "INVESTIGATE_FLAKINESS", "INSUFFICIENT_EVIDENCE",
    "VerificationResult", "BaselineReceipt", "ExperimentReceipt", "EvidenceItem",
    "ExperimentalEvidenceLedger", "DiagnosticResult", "new_core3_metrics",
    "ExperimentalEvidenceEngine", "generate_test_failure_experiments", "generate_error_location_experiments",
    "generate_dependency_stub_experiment", "generate_input_perturbation_experiment",
    "session_from_recovery_failure", "benchmark_diagnostic_scenarios",
]
