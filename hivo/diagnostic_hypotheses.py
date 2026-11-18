"""Deterministic diagnostic sessions and hypothesis evidence for CORE-3.

The objects in this module are diagnostic projections.  They deliberately do
not represent Project Brain truth, mutation authority, or verification.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Iterable, Mapping

from .project_brain_refs import TypedReference, canonical_hash


CORE3_SCHEMA_VERSION = "CORE-3-EXPERIMENTAL-EVIDENCE-V1"

READY = "READY"
BASELINE_UNSTABLE = "BASELINE_UNSTABLE"
ACTIVE = "ACTIVE"
EVIDENCE_SUFFICIENT = "EVIDENCE_SUFFICIENT"
BUDGET_REACHED = "BUDGET_REACHED"
INCONCLUSIVE = "INCONCLUSIVE"
BLOCKED = "BLOCKED"
CLOSED = "CLOSED"
SESSION_STATUSES = (
    READY, BASELINE_UNSTABLE, ACTIVE, EVIDENCE_SUFFICIENT,
    BUDGET_REACHED, INCONCLUSIVE, BLOCKED, CLOSED,
)

DETERMINISTIC_SEED = "DETERMINISTIC_SEED"
MODEL_PROPOSED = "MODEL_PROPOSED"
USER_PROVIDED = "USER_PROVIDED"
RECOVERY_DERIVED = "RECOVERY_DERIVED"
TEST_DERIVED = "TEST_DERIVED"
HYPOTHESIS_SOURCES = (
    DETERMINISTIC_SEED, MODEL_PROPOSED, USER_PROVIDED,
    RECOVERY_DERIVED, TEST_DERIVED,
)

HYPOTHESIS_ACTIVE = "ACTIVE"
SUPPORTED = "SUPPORTED"
WEAKENED = "WEAKENED"
STRONGLY_WEAKENED = "STRONGLY_WEAKENED"
HYPOTHESIS_INCONCLUSIVE = "INCONCLUSIVE"
ELIMINATED = "ELIMINATED"
HYPOTHESIS_STATUSES = (
    HYPOTHESIS_ACTIVE, SUPPORTED, WEAKENED, STRONGLY_WEAKENED,
    HYPOTHESIS_INCONCLUSIVE, ELIMINATED,
)

SUPPORTS = "SUPPORTS"
WEAKENS = "WEAKENS"
STRONGLY_WEAKENS = "STRONGLY_WEAKENS"
NEUTRAL = "NEUTRAL"
EFFECT_INCONCLUSIVE = "INCONCLUSIVE"
HYPOTHESIS_EFFECTS = (SUPPORTS, WEAKENS, STRONGLY_WEAKENS, NEUTRAL, EFFECT_INCONCLUSIVE)

WEAK = "WEAK"
MODERATE = "MODERATE"
STRONG = "STRONG"
EVIDENCE_STRENGTHS = (WEAK, MODERATE, STRONG)


@dataclass(frozen=True)
class DiagnosticBudget:
    """Hard bounds for one diagnostic session."""

    max_total_experiments: int = 6
    max_counterfactual_mutations: int = 3
    max_baseline_confirmations: int = 2
    max_targeted_tests: int = 10
    max_guard_tests_per_experiment: int = 3
    max_active_hypotheses: int = 8
    max_deterministic_seeds: int = 6
    max_working_set_expansions: int = 2
    timeout_seconds: int = 30

    def __post_init__(self) -> None:
        limits = {
            "max_total_experiments": (1, 64),
            "max_counterfactual_mutations": (0, 32),
            "max_baseline_confirmations": (0, 8),
            "max_targeted_tests": (0, 128),
            "max_guard_tests_per_experiment": (0, 16),
            "max_active_hypotheses": (1, 64),
            "max_deterministic_seeds": (1, 64),
            "max_working_set_expansions": (0, 16),
            "timeout_seconds": (1, 600),
        }
        for name, (minimum, maximum) in limits.items():
            value = max(minimum, min(maximum, int(getattr(self, name))))
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in (
                "max_total_experiments", "max_counterfactual_mutations",
                "max_baseline_confirmations", "max_targeted_tests",
                "max_guard_tests_per_experiment", "max_active_hypotheses",
                "max_deterministic_seeds", "max_working_set_expansions",
                "timeout_seconds",
            )
        }


def _reference(value: Any) -> TypedReference | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, TypedReference) else TypedReference.from_value(value)
    except (TypeError, ValueError):
        return None


def _references(values: Iterable[Any]) -> tuple[TypedReference, ...]:
    result: list[TypedReference] = []
    seen: set[str] = set()
    for value in values:
        ref = _reference(value)
        if ref is not None and ref.canonical_uri not in seen:
            result.append(ref)
            seen.add(ref.canonical_uri)
    return tuple(sorted(result, key=lambda item: item.canonical_uri))


@dataclass(frozen=True)
class DiagnosticFailureEvidence:
    """Structured failure input; prose is retained as evidence, not authority."""

    failure_id: str
    source_type: str
    expected_outcome: str = "TARGET_TEST_FAILS"
    observed_outcome: str = ""
    message: str = ""
    references: tuple[TypedReference, ...] = ()
    test_name: str = ""
    error_location: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_id", str(self.failure_id))
        object.__setattr__(self, "source_type", str(self.source_type))
        object.__setattr__(self, "expected_outcome", str(self.expected_outcome))
        object.__setattr__(self, "observed_outcome", str(self.observed_outcome))
        object.__setattr__(self, "message", str(self.message)[:4000])
        object.__setattr__(self, "references", _references(self.references))
        object.__setattr__(self, "test_name", str(self.test_name))
        object.__setattr__(self, "error_location", str(self.error_location))
        object.__setattr__(self, "metadata", dict(self.metadata))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE3_SCHEMA_VERSION,
            "failure_id": self.failure_id,
            "source_type": self.source_type,
            "expected_outcome": self.expected_outcome,
            "observed_outcome": self.observed_outcome,
            "message": self.message,
            "references": [ref.to_dict() for ref in self.references],
            "test_name": self.test_name,
            "error_location": self.error_location,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: "DiagnosticFailureEvidence | Mapping[str, Any]") -> "DiagnosticFailureEvidence":
        if isinstance(value, cls):
            return value
        if hasattr(value, "to_dict"):
            data = dict(value.to_dict())
        else:
            data = dict(value)
        return cls(
            failure_id=str(data.get("failure_id", "failure")),
            source_type=str(data.get("source_type", "UNKNOWN")),
            expected_outcome=str(data.get("expected_outcome", "TARGET_TEST_FAILS")),
            observed_outcome=str(data.get("observed_outcome", "")),
            message=str(data.get("message", "")),
            references=tuple(data.get("references", ()) or ()),
            test_name=str(data.get("test_name", "")),
            error_location=str(data.get("error_location", "")),
            metadata=dict(data.get("metadata", {}) or {}),
        )


@dataclass(frozen=True)
class DiagnosticHypothesis:
    hypothesis_id: str
    statement: str
    target_references: tuple[TypedReference, ...] = ()
    suspect_symbols: tuple[str, ...] = ()
    expected_failure_relationship: str = "candidate_explains_observed_failure"
    source: str = DETERMINISTIC_SEED
    initial_confidence_class: str = "SUSPECT"
    current_evidence_score: int = 0
    current_evidence_class: str = "UNRESOLVED"
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    status: str = HYPOTHESIS_ACTIVE

    def __post_init__(self) -> None:
        if self.source not in HYPOTHESIS_SOURCES:
            raise ValueError(f"unsupported hypothesis source: {self.source}")
        if self.status not in HYPOTHESIS_STATUSES:
            raise ValueError(f"unsupported hypothesis status: {self.status}")
        object.__setattr__(self, "hypothesis_id", str(self.hypothesis_id))
        object.__setattr__(self, "statement", str(self.statement)[:1200])
        object.__setattr__(self, "target_references", _references(self.target_references))
        object.__setattr__(self, "suspect_symbols", tuple(sorted(set(str(item) for item in self.suspect_symbols))))
        object.__setattr__(self, "supporting_evidence_ids", tuple(sorted(set(str(item) for item in self.supporting_evidence_ids))))
        object.__setattr__(self, "contradicting_evidence_ids", tuple(sorted(set(str(item) for item in self.contradicting_evidence_ids))))
        object.__setattr__(self, "current_evidence_score", int(self.current_evidence_score))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE3_SCHEMA_VERSION,
            "hypothesis_id": self.hypothesis_id,
            "statement": self.statement,
            "target_references": [ref.to_dict() for ref in self.target_references],
            "suspect_symbols": list(self.suspect_symbols),
            "expected_failure_relationship": self.expected_failure_relationship,
            "source": self.source,
            "initial_confidence_class": self.initial_confidence_class,
            "current_evidence_score": self.current_evidence_score,
            "current_evidence_class": self.current_evidence_class,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "status": self.status,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: "DiagnosticHypothesis | Mapping[str, Any]") -> "DiagnosticHypothesis":
        if isinstance(value, cls):
            return value
        data = dict(value)
        return cls(
            hypothesis_id=str(data.get("hypothesis_id", "hypothesis")),
            statement=str(data.get("statement", "")),
            target_references=tuple(data.get("target_references", ()) or ()),
            suspect_symbols=tuple(data.get("suspect_symbols", ()) or ()),
            expected_failure_relationship=str(data.get("expected_failure_relationship", "candidate_explains_observed_failure")),
            source=str(data.get("source", DETERMINISTIC_SEED)),
            initial_confidence_class=str(data.get("initial_confidence_class", "SUSPECT")),
            current_evidence_score=int(data.get("current_evidence_score", 0)),
            current_evidence_class=str(data.get("current_evidence_class", "UNRESOLVED")),
            supporting_evidence_ids=tuple(data.get("supporting_evidence_ids", ()) or ()),
            contradicting_evidence_ids=tuple(data.get("contradicting_evidence_ids", ()) or ()),
            status=str(data.get("status", HYPOTHESIS_ACTIVE)),
        )


@dataclass(frozen=True)
class DiagnosticSession:
    session_id: str
    task_query_identity: str
    subject_identity: str
    revision_identity: str
    working_set_identity: str
    failure_evidence: tuple[DiagnosticFailureEvidence, ...] = ()
    authority_context: dict[str, Any] = field(default_factory=dict)
    dnt_context: tuple[str, ...] = ()
    experiment_budget: DiagnosticBudget = field(default_factory=DiagnosticBudget)
    hypotheses: tuple[DiagnosticHypothesis, ...] = ()
    evidence_ledger_identity: str = ""
    status: str = READY
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.status not in SESSION_STATUSES:
            raise ValueError(f"unsupported diagnostic session status: {self.status}")
        object.__setattr__(self, "session_id", str(self.session_id))
        object.__setattr__(self, "task_query_identity", str(self.task_query_identity))
        object.__setattr__(self, "subject_identity", str(self.subject_identity))
        object.__setattr__(self, "revision_identity", str(self.revision_identity))
        object.__setattr__(self, "working_set_identity", str(self.working_set_identity))
        object.__setattr__(self, "failure_evidence", tuple(DiagnosticFailureEvidence.from_value(item) for item in self.failure_evidence))
        object.__setattr__(self, "hypotheses", tuple(DiagnosticHypothesis.from_value(item) for item in self.hypotheses))
        object.__setattr__(self, "dnt_context", tuple(sorted(set(str(item).replace("\\", "/") for item in self.dnt_context))))
        object.__setattr__(self, "authority_context", dict(self.authority_context))
        object.__setattr__(self, "metadata", dict(self.metadata))
        if not self.evidence_ledger_identity:
            object.__setattr__(self, "evidence_ledger_identity", canonical_hash({"session_id": self.session_id, "schema": CORE3_SCHEMA_VERSION}))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE3_SCHEMA_VERSION,
            "session_id": self.session_id,
            "task_query_identity": self.task_query_identity,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "working_set_identity": self.working_set_identity,
            "failure_evidence": [item.to_dict() for item in self.failure_evidence],
            "authority_context": dict(self.authority_context),
            "dnt_context": list(self.dnt_context),
            "experiment_budget": self.experiment_budget.to_dict(),
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "evidence_ledger_identity": self.evidence_ledger_identity,
            "status": self.status,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    def with_updates(self, **changes: Any) -> "DiagnosticSession":
        return replace(self, **changes)


def _candidate_reference(candidate: Any) -> TypedReference | None:
    if isinstance(candidate, Mapping):
        path = str(candidate.get("path", ""))
        symbol = candidate.get("symbol") or candidate.get("qualified_name")
        kind = str(candidate.get("candidate_type", "file"))
    else:
        path = str(getattr(candidate, "path", ""))
        symbol = getattr(candidate, "symbol", None)
        kind = str(getattr(candidate, "candidate_type", "file"))
    if not path:
        return None
    if symbol:
        kind = "symbol"
    elif kind in {"test", "test_file"}:
        kind = "test"
    else:
        kind = "file"
    return _reference({"kind": kind, "path": path, "symbol": symbol} if kind == "symbol" else {"kind": kind, "path": path})


def _candidate_identity(candidate: Any) -> str:
    if isinstance(candidate, Mapping):
        return str(candidate.get("identity") or candidate.get("path") or "")
    return str(getattr(candidate, "identity", getattr(candidate, "path", "")))


def seed_hypotheses(
    failure_evidence: DiagnosticFailureEvidence | Mapping[str, Any] | Iterable[Any],
    working_set: Any = None,
    *,
    max_seeds: int = 6,
    task_query_identity: str = "",
) -> tuple[DiagnosticHypothesis, ...]:
    """Create bounded suspect hypotheses from structured evidence and CORE-2 candidates."""
    if isinstance(failure_evidence, (DiagnosticFailureEvidence, Mapping)):
        failures = (DiagnosticFailureEvidence.from_value(failure_evidence),)
    else:
        failures = tuple(DiagnosticFailureEvidence.from_value(item) for item in failure_evidence)
    candidates = tuple(getattr(working_set, "items", ()) or ())
    rows: list[tuple[str, str, TypedReference, str]] = []
    for failure in failures:
        for ref in failure.references:
            rows.append((ref.canonical_uri, f"Failure evidence points to {ref.canonical_uri}", ref, failure.source_type))
        location = str(failure.error_location or failure.metadata.get("symbol", ""))
        if location and not any(location in statement for _, statement, _, _ in rows):
            rows.append((f"location:{location}", f"Failure location {location} is a suspect diagnostic boundary", TypedReference("file", location) if "/" in location or "." in location else TypedReference("symbol", "", location), DETERMINISTIC_SEED))
    for item in candidates:
        ref = _candidate_reference(item)
        if ref is None:
            continue
        identity = _candidate_identity(item) or ref.canonical_uri
        role = str(getattr(item, "role", "SUPPORTING"))
        statement = f"The current {role.lower()} reference {ref.canonical_uri} may explain the observed failure"
        rows.append((identity, statement, ref, TEST_DERIVED if role == "TESTS" else DETERMINISTIC_SEED))
    seen: set[str] = set()
    result: list[DiagnosticHypothesis] = []
    for identity, statement, ref, source in rows:
        if identity in seen or len(result) >= max(1, int(max_seeds)):
            continue
        seen.add(identity)
        hid = f"H-{canonical_hash({'identity': identity, 'query': task_query_identity})[:12]}"
        result.append(DiagnosticHypothesis(
            hypothesis_id=hid,
            statement=statement,
            target_references=(ref,),
            suspect_symbols=(ref.symbol,) if ref.symbol else (),
            source=source if source in HYPOTHESIS_SOURCES else DETERMINISTIC_SEED,
        ))
    return tuple(result)


def _strength_delta(strength: str) -> int:
    return {WEAK: 1, MODERATE: 2, STRONG: 3}.get(strength, 1)


def classify_effect(
    predicted_outcome: str | None,
    observed_outcome: str,
    *,
    valid: bool,
    masking_risk: bool = False,
) -> str:
    if not valid or masking_risk:
        return EFFECT_INCONCLUSIVE
    if not predicted_outcome:
        return NEUTRAL
    if str(predicted_outcome) == str(observed_outcome):
        return SUPPORTS
    if observed_outcome in {"EXECUTION_INVALID", "BASELINE_UNSTABLE", "TARGET_TEST_FAILS"}:
        return STRONGLY_WEAKENS if predicted_outcome in {"TARGET_TEST_PASSES", "FAILURE_DISAPPEARS"} else WEAKENS
    return WEAKENS


def apply_hypothesis_effect(
    hypothesis: DiagnosticHypothesis,
    effect: str,
    *,
    evidence_id: str,
    strength: str = MODERATE,
) -> DiagnosticHypothesis:
    """Apply an evidence effect without ever creating a proven truth state."""
    if effect not in HYPOTHESIS_EFFECTS:
        raise ValueError(f"unsupported hypothesis effect: {effect}")
    if effect == SUPPORTS:
        score = hypothesis.current_evidence_score + _strength_delta(strength)
        status = SUPPORTED if score >= 2 else HYPOTHESIS_ACTIVE
        evidence_class = STRONG if score >= 5 else (MODERATE if score >= 2 else WEAK)
        return replace(
            hypothesis, current_evidence_score=score, current_evidence_class=evidence_class,
            status=status, supporting_evidence_ids=tuple(sorted(set(hypothesis.supporting_evidence_ids + (evidence_id,)))),
        )
    if effect == STRONGLY_WEAKENS:
        score = hypothesis.current_evidence_score - max(2, _strength_delta(strength))
        status = ELIMINATED if score <= -5 else STRONGLY_WEAKENED
        evidence_class = STRONG if score <= -4 else MODERATE
        return replace(
            hypothesis, current_evidence_score=score, current_evidence_class=evidence_class,
            status=status, contradicting_evidence_ids=tuple(sorted(set(hypothesis.contradicting_evidence_ids + (evidence_id,)))),
        )
    if effect == WEAKENS:
        score = hypothesis.current_evidence_score - _strength_delta(strength)
        status = STRONGLY_WEAKENED if score <= -3 else WEAKENED
        evidence_class = MODERATE if score <= -2 else WEAK
        return replace(
            hypothesis, current_evidence_score=score, current_evidence_class=evidence_class,
            status=status, contradicting_evidence_ids=tuple(sorted(set(hypothesis.contradicting_evidence_ids + (evidence_id,)))),
        )
    if effect == EFFECT_INCONCLUSIVE:
        # Invalid or masked probes do not change causal belief.  The ledger
        # records the inconclusive event separately.
        return hypothesis
    return hypothesis


__all__ = [
    "CORE3_SCHEMA_VERSION", "DiagnosticBudget", "DiagnosticFailureEvidence",
    "DiagnosticHypothesis", "DiagnosticSession", "seed_hypotheses",
    "classify_effect", "apply_hypothesis_effect", "READY", "BASELINE_UNSTABLE",
    "ACTIVE", "EVIDENCE_SUFFICIENT", "BUDGET_REACHED", "INCONCLUSIVE", "BLOCKED", "CLOSED",
    "DETERMINISTIC_SEED", "MODEL_PROPOSED", "USER_PROVIDED", "RECOVERY_DERIVED", "TEST_DERIVED",
    "HYPOTHESIS_ACTIVE", "SUPPORTED", "WEAKENED", "STRONGLY_WEAKENED", "HYPOTHESIS_INCONCLUSIVE", "ELIMINATED",
    "SUPPORTS", "WEAKENS", "STRONGLY_WEAKENS", "NEUTRAL", "EFFECT_INCONCLUSIVE",
    "WEAK", "MODERATE", "STRONG",
]
