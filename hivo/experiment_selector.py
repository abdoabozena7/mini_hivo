"""Deterministic experiment models and model-free selection for CORE-3."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .diagnostic_hypotheses import (
    DiagnosticBudget, DiagnosticHypothesis, ELIMINATED, STRONGLY_WEAKENED,
)
from .project_brain_refs import TypedReference, canonical_hash
from .experiment_sandbox import CounterfactualMutationSpec


BASELINE_REPRODUCTION = "BASELINE_REPRODUCTION"
TARGETED_TEST = "TARGETED_TEST"
INPUT_PERTURBATION = "INPUT_PERTURBATION"
DEPENDENCY_STUB = "DEPENDENCY_STUB"
COUNTERFACTUAL_MUTATION = "COUNTERFACTUAL_MUTATION"
OBSERVATION_ONLY = "OBSERVATION_ONLY"
TRACE_OBSERVATION = "TRACE_OBSERVATION"
EXPERIMENT_KINDS = (
    BASELINE_REPRODUCTION, TARGETED_TEST, INPUT_PERTURBATION,
    DEPENDENCY_STUB, COUNTERFACTUAL_MUTATION, OBSERVATION_ONLY, TRACE_OBSERVATION,
)

PROPOSED = "PROPOSED"
SELECTED = "SELECTED"
EXECUTED = "EXECUTED"
SUPPRESSED = "SUPPRESSED"

COST_CHEAP = "CHEAP"
COST_MEDIUM = "MEDIUM"
COST_EXPENSIVE = "EXPENSIVE"
COST_CLASSES = (COST_CHEAP, COST_MEDIUM, COST_EXPENSIVE)
RISK_LOW = "LOW"
RISK_CONTROLLED = "CONTROLLED"
RISK_HIGH = "HIGH"
RISK_CLASSES = (RISK_LOW, RISK_CONTROLLED, RISK_HIGH)


def _refs(values: Iterable[Any]) -> tuple[TypedReference, ...]:
    result: list[TypedReference] = []
    seen: set[str] = set()
    for value in values:
        try:
            ref = value if isinstance(value, TypedReference) else TypedReference.from_value(value)
        except (TypeError, ValueError):
            continue
        if ref.canonical_uri not in seen:
            result.append(ref)
            seen.add(ref.canonical_uri)
    return tuple(sorted(result, key=lambda item: item.canonical_uri))


@dataclass(frozen=True)
class DiagnosticExperiment:
    """An experiment with predictions declared before execution."""

    experiment_id: str
    kind: str
    goal: str
    target_hypothesis_ids: tuple[str, ...] = ()
    target_references: tuple[TypedReference, ...] = ()
    predicted_outcomes: tuple[tuple[str, str], ...] = ()
    intervention_description: str = ""
    verification_checks: tuple[str, ...] = ()
    sandbox_requirements: tuple[str, ...] = ()
    estimated_cost_class: str = COST_CHEAP
    risk_class: str = RISK_LOW
    expected_discrimination_score: int = 0
    status: str = PROPOSED
    mutation_spec: CounterfactualMutationSpec | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    verification_command: str = ""

    def __post_init__(self) -> None:
        if self.kind not in EXPERIMENT_KINDS:
            raise ValueError(f"unsupported experiment kind: {self.kind}")
        if self.estimated_cost_class not in COST_CLASSES:
            raise ValueError(f"unsupported cost class: {self.estimated_cost_class}")
        if self.risk_class not in RISK_CLASSES:
            raise ValueError(f"unsupported risk class: {self.risk_class}")
        object.__setattr__(self, "experiment_id", str(self.experiment_id))
        object.__setattr__(self, "goal", str(self.goal)[:1200])
        object.__setattr__(self, "target_hypothesis_ids", tuple(sorted(set(str(item) for item in self.target_hypothesis_ids))))
        object.__setattr__(self, "target_references", _refs(self.target_references))
        if isinstance(self.predicted_outcomes, Mapping):
            predictions = tuple(self.predicted_outcomes.items())
        else:
            predictions = tuple(self.predicted_outcomes)
        object.__setattr__(self, "predicted_outcomes", tuple(sorted((str(key), str(value)) for key, value in predictions)))
        checks = tuple(self.verification_checks)
        if self.verification_command and not checks:
            checks = (self.verification_command,)
        object.__setattr__(self, "verification_checks", tuple(sorted(set(str(item) for item in checks))))
        object.__setattr__(self, "verification_command", str(self.verification_command))
        object.__setattr__(self, "sandbox_requirements", tuple(sorted(set(str(item) for item in self.sandbox_requirements))))
        object.__setattr__(self, "expected_discrimination_score", max(0, int(self.expected_discrimination_score)))
        object.__setattr__(self, "metadata", dict(self.metadata))

    def prediction_for(self, hypothesis_id: str) -> str | None:
        for key, value in self.predicted_outcomes:
            if key == str(hypothesis_id):
                return value
        return None

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "experiment_id": self.experiment_id,
            "kind": self.kind,
            "goal": self.goal,
            "target_hypothesis_ids": list(self.target_hypothesis_ids),
            "target_references": [ref.to_dict() for ref in self.target_references],
            "predicted_outcomes": {key: value for key, value in self.predicted_outcomes},
            "intervention_description": self.intervention_description,
            "verification_checks": list(self.verification_checks),
            "verification_command": self.verification_command,
            "sandbox_requirements": list(self.sandbox_requirements),
            "estimated_cost_class": self.estimated_cost_class,
            "risk_class": self.risk_class,
            "expected_discrimination_score": self.expected_discrimination_score,
            "status": self.status,
            "mutation_spec": self.mutation_spec.to_dict() if self.mutation_spec else None,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class SelectionDecision:
    selected: DiagnosticExperiment | None
    ranked: tuple[dict[str, Any], ...] = ()
    skipped: tuple[dict[str, Any], ...] = ()
    reason: str = ""

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "selected": self.selected.to_dict() if self.selected else None,
            "ranked": list(self.ranked),
            "skipped": list(self.skipped),
            "reason": self.reason,
        }


def _cost_penalty(cost: str) -> int:
    return {COST_CHEAP: 0, COST_MEDIUM: 2, COST_EXPENSIVE: 6}.get(cost, 6)


def _risk_penalty(risk: str) -> int:
    return {RISK_LOW: 0, RISK_CONTROLLED: 1, RISK_HIGH: 5}.get(risk, 5)


class ExperimentSelector:
    """Ranks experiments without model confidence or provider calls."""

    def rank(
        self,
        experiments: Iterable[DiagnosticExperiment],
        hypotheses: Iterable[DiagnosticHypothesis],
        *,
        executed_hashes: Iterable[str] = (),
    ) -> SelectionDecision:
        available = tuple(experiments)
        active = {
            hypothesis.hypothesis_id: hypothesis
            for hypothesis in hypotheses
            if hypothesis.status not in {ELIMINATED, STRONGLY_WEAKENED}
        }
        executed = set(str(item) for item in executed_hashes)
        ranked: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for experiment in experiments:
            if experiment.canonical_hash in executed:
                skipped.append({"experiment_id": experiment.experiment_id, "reason": "duplicate_experiment"})
                continue
            targeted = [active[key] for key in experiment.target_hypothesis_ids if key in active]
            if not targeted:
                skipped.append({"experiment_id": experiment.experiment_id, "reason": "no_active_hypothesis"})
                continue
            outcomes = {experiment.prediction_for(item.hypothesis_id) for item in targeted}
            outcomes.discard(None)
            discrimination = max(0, len(outcomes) - 1)
            score = (
                (discrimination * 10)
                + (len(targeted) * 2)
                + experiment.expected_discrimination_score
                - _cost_penalty(experiment.estimated_cost_class)
                - _risk_penalty(experiment.risk_class)
            )
            ranked.append({
                "experiment_id": experiment.experiment_id,
                "experiment_hash": experiment.canonical_hash,
                "selector_score": score,
                "active_hypotheses": len(targeted),
                "distinct_predicted_outcomes": len(outcomes),
                "discrimination_score": discrimination,
                "cost_class": experiment.estimated_cost_class,
                "risk_class": experiment.risk_class,
            })
        ranked.sort(key=lambda row: (-row["selector_score"], row["experiment_id"]))
        selected = None
        if ranked:
            chosen_id = ranked[0]["experiment_id"]
            selected = next(item for item in available if item.experiment_id == chosen_id)
            reason = "highest deterministic discrimination adjusted for cost and risk"
        else:
            reason = "no non-duplicate experiment targets an active hypothesis"
        return SelectionDecision(selected=selected, ranked=tuple(ranked), skipped=tuple(skipped), reason=reason)

    def select(
        self,
        experiments: Iterable[DiagnosticExperiment],
        hypotheses: Iterable[DiagnosticHypothesis],
        *,
        executed_hashes: Iterable[str] = (),
    ) -> DiagnosticExperiment | None:
        return self.rank(experiments, hypotheses, executed_hashes=executed_hashes).selected


__all__ = [
    "DiagnosticExperiment", "SelectionDecision", "ExperimentSelector",
    "BASELINE_REPRODUCTION", "TARGETED_TEST", "INPUT_PERTURBATION",
    "DEPENDENCY_STUB", "COUNTERFACTUAL_MUTATION", "OBSERVATION_ONLY", "TRACE_OBSERVATION",
    "EXPERIMENT_KINDS", "PROPOSED", "SELECTED", "EXECUTED", "SUPPRESSED",
    "COST_CHEAP", "COST_MEDIUM", "COST_EXPENSIVE", "RISK_LOW", "RISK_CONTROLLED", "RISK_HIGH",
]
