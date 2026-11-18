"""Immutable CORE-5 repair inputs and bounded search budgets.

CORE-5 is deliberately a diagnostic/repair-candidate projection.  These
records bind current evidence and authority, but they never become approval,
verification, Brain truth, or a canonical mutation by themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .diagnostic_hypotheses import DiagnosticHypothesis
from .fault_localization import FaultCandidate, FaultFailureEvidence, FaultLocalizationResult
from .project_brain_refs import TypedReference, canonical_hash
from .task_working_set import TaskWorkingSet


CORE5_SCHEMA_VERSION = "CORE-5-PATCH-CANDIDATE-SEARCH-V1"

DIAGNOSTIC_SUSPECT = "DIAGNOSTIC_SUSPECT"
FINAL_MUTATION_AUTHORIZED = "FINAL_MUTATION_AUTHORIZED"
READ_ONLY_SUPPORT = "READ_ONLY_SUPPORT"
DNT_PROTECTED = "DNT_PROTECTED"


@dataclass(frozen=True)
class PatchSearchBudget:
    """Hard bounds for one provider-free patch search session."""

    max_suspects: int = 3
    max_supporting_symbols: int = 4
    max_candidate_files: int = 6
    max_strategies: int = 4
    max_candidates: int = 8
    max_candidates_per_strategy: int = 3
    max_deterministic_candidates: int = 6
    max_model_candidates: int = 3
    max_targeted_check_candidates: int = 5
    max_v25_5_candidates: int = 3
    max_full_v25_6_candidates: int = 2
    max_syntax_valid_candidates: int = 6
    max_pareto_alternatives: int = 2
    max_source_slices: int = 8
    max_source_characters: int = 24000

    def __post_init__(self) -> None:
        limits = {
            "max_suspects": (1, 16), "max_supporting_symbols": (0, 32),
            "max_candidate_files": (1, 32), "max_strategies": (1, 16),
            "max_candidates": (1, 64), "max_candidates_per_strategy": (1, 16),
            "max_deterministic_candidates": (0, 64), "max_model_candidates": (0, 32),
            "max_targeted_check_candidates": (0, 64), "max_v25_5_candidates": (0, 32),
            "max_full_v25_6_candidates": (0, 8), "max_pareto_alternatives": (0, 8),
            "max_syntax_valid_candidates": (0, 64),
            "max_source_slices": (0, 64), "max_source_characters": (256, 200000),
        }
        for name, (minimum, maximum) in limits.items():
            value = max(minimum, min(maximum, int(getattr(self, name))))
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {
            name: int(getattr(self, name))
            for name in (
                "max_suspects", "max_supporting_symbols", "max_candidate_files",
                "max_strategies", "max_candidates", "max_candidates_per_strategy",
                "max_deterministic_candidates", "max_model_candidates",
                "max_targeted_check_candidates", "max_v25_5_candidates",
                "max_full_v25_6_candidates", "max_pareto_alternatives",
                "max_syntax_valid_candidates",
                "max_source_slices", "max_source_characters",
            )
        }

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    @property
    def max_primary_suspicious_symbols(self) -> int:
        return self.max_suspects

    @property
    def max_total_candidates(self) -> int:
        return self.max_candidates

    @property
    def max_candidates_reaching_targeted_verification(self) -> int:
        return self.max_targeted_check_candidates

    @property
    def max_candidates_reaching_v25_5(self) -> int:
        return self.max_v25_5_candidates

    @property
    def max_candidates_reaching_full_v25_6(self) -> int:
        return self.max_full_v25_6_candidates


CandidateSearchBudget = PatchSearchBudget


def _as_reference(value: Any) -> TypedReference | None:
    try:
        return value if isinstance(value, TypedReference) else TypedReference.from_value(value)
    except (TypeError, ValueError):
        return None


def _references(values: Iterable[Any]) -> tuple[TypedReference, ...]:
    rows: dict[str, TypedReference] = {}
    for value in values:
        ref = _as_reference(value)
        if ref is not None:
            rows[ref.canonical_uri] = ref
    return tuple(rows[key] for key in sorted(rows))


def _candidate_record(candidate: FaultCandidate) -> dict[str, Any]:
    return candidate.to_dict(include_hash=False)


@dataclass(frozen=True)
class RepairTargetSet:
    """Bounded suspect projection; diagnostic suspects remain distinct from authority."""

    primary_suspects: tuple[TypedReference, ...] = ()
    supporting_suspects: tuple[TypedReference, ...] = ()
    candidate_files: tuple[str, ...] = ()
    candidate_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "primary_suspects", _references(self.primary_suspects))
        object.__setattr__(self, "supporting_suspects", _references(self.supporting_suspects))
        object.__setattr__(self, "candidate_files", tuple(sorted({str(item).replace("\\", "/") for item in self.candidate_files if str(item).strip()})))
        object.__setattr__(self, "candidate_ids", tuple(sorted({str(item) for item in self.candidate_ids if str(item).strip()})))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE5_SCHEMA_VERSION,
            "primary_suspects": [item.to_dict() for item in self.primary_suspects],
            "supporting_suspects": [item.to_dict() for item in self.supporting_suspects],
            "candidate_files": list(self.candidate_files),
            "candidate_ids": list(self.candidate_ids),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class RepairEvidencePacket:
    """Small, hash-bound context suitable for a future model candidate hook."""

    repair_id: str
    task_identity: str
    suspect_references: tuple[TypedReference, ...] = ()
    hypothesis_ids: tuple[str, ...] = ()
    failure_ids: tuple[str, ...] = ()
    contracts: tuple[str, ...] = ()
    strategy_hints: tuple[str, ...] = ()
    source_slices: tuple[dict[str, Any], ...] = ()
    experimental_summary: tuple[dict[str, Any], ...] = ()
    authority_summary: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repair_id", str(self.repair_id))
        object.__setattr__(self, "task_identity", str(self.task_identity))
        object.__setattr__(self, "suspect_references", _references(self.suspect_references))
        object.__setattr__(self, "hypothesis_ids", tuple(sorted({str(item) for item in self.hypothesis_ids})))
        object.__setattr__(self, "failure_ids", tuple(sorted({str(item) for item in self.failure_ids})))
        object.__setattr__(self, "contracts", tuple(sorted({str(item)[:600] for item in self.contracts})))
        object.__setattr__(self, "strategy_hints", tuple(sorted({str(item) for item in self.strategy_hints})))
        object.__setattr__(self, "source_slices", tuple(dict(item) for item in self.source_slices))
        object.__setattr__(self, "experimental_summary", tuple(dict(item) for item in self.experimental_summary))
        object.__setattr__(self, "authority_summary", dict(self.authority_summary or {}))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE5_SCHEMA_VERSION,
            "repair_id": self.repair_id,
            "task_identity": self.task_identity,
            "suspect_references": [item.to_dict() for item in self.suspect_references],
            "hypothesis_ids": list(self.hypothesis_ids),
            "failure_ids": list(self.failure_ids),
            "contracts": list(self.contracts),
            "strategy_hints": list(self.strategy_hints),
            "source_slices": list(self.source_slices),
            "experimental_summary": list(self.experimental_summary),
            "authority_summary": dict(self.authority_summary),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class RepairProblem:
    """Canonical repair input composed from CORE-1/2/3/4 evidence."""

    repair_id: str
    task_identity: str
    subject_identity: str
    revision_identity: str
    working_set_identity: str
    fault_localization_identity: str
    target_set: RepairTargetSet = field(default_factory=RepairTargetSet)
    suspect_candidates: tuple[dict[str, Any], ...] = ()
    hypothesis_ids: tuple[str, ...] = ()
    evidence_ledger_identity: str = ""
    failure_evidence: tuple[FaultFailureEvidence, ...] = ()
    contracts: tuple[dict[str, Any], ...] = ()
    invariants: tuple[dict[str, Any], ...] = ()
    authority_context: dict[str, Any] = field(default_factory=dict)
    dnt_context: tuple[str, ...] = ()
    candidate_budget: PatchSearchBudget = field(default_factory=PatchSearchBudget)
    verification_obligations: tuple[dict[str, Any], ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    project_root: str = field(default="", repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "repair_id", str(self.repair_id))
        object.__setattr__(self, "task_identity", str(self.task_identity))
        object.__setattr__(self, "subject_identity", str(self.subject_identity))
        object.__setattr__(self, "revision_identity", str(self.revision_identity))
        object.__setattr__(self, "working_set_identity", str(self.working_set_identity))
        object.__setattr__(self, "fault_localization_identity", str(self.fault_localization_identity))
        if isinstance(self.target_set, RepairTargetSet):
            normalized_target_set = self.target_set
        else:
            target_data = dict(self.target_set or {})
            normalized_target_set = RepairTargetSet(**{
                key: target_data.get(key, ())
                for key in ("primary_suspects", "supporting_suspects", "candidate_files", "candidate_ids")
            })
        object.__setattr__(self, "target_set", normalized_target_set)
        object.__setattr__(self, "suspect_candidates", tuple(dict(item) for item in self.suspect_candidates))
        object.__setattr__(self, "hypothesis_ids", tuple(sorted({str(item) for item in self.hypothesis_ids})))
        object.__setattr__(self, "evidence_ledger_identity", str(self.evidence_ledger_identity or ""))
        object.__setattr__(self, "failure_evidence", tuple(FaultFailureEvidence.from_value(item) for item in self.failure_evidence))
        object.__setattr__(self, "contracts", tuple(dict(item) for item in self.contracts))
        object.__setattr__(self, "invariants", tuple(dict(item) for item in self.invariants))
        object.__setattr__(self, "authority_context", dict(self.authority_context or {}))
        object.__setattr__(self, "dnt_context", tuple(sorted({str(item).replace("\\", "/").lstrip("./") for item in self.dnt_context})))
        if isinstance(self.candidate_budget, Mapping):
            object.__setattr__(self, "candidate_budget", PatchSearchBudget(**dict(self.candidate_budget)))
        object.__setattr__(self, "verification_obligations", tuple(dict(item) for item in self.verification_obligations))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_localization(
        cls,
        localization: FaultLocalizationResult,
        *,
        task_identity: str = "",
        repair_id: str = "",
        working_set: TaskWorkingSet | None = None,
        contracts: Iterable[Mapping[str, Any]] = (),
        invariants: Iterable[Mapping[str, Any]] = (),
        authority_context: Mapping[str, Any] | None = None,
        dnt_context: Iterable[str] = (),
        candidate_budget: PatchSearchBudget | Mapping[str, Any] | None = None,
        verification_obligations: Iterable[Mapping[str, Any]] = (),
        project_root: str = "",
    ) -> "RepairProblem":
        budget = candidate_budget if isinstance(candidate_budget, PatchSearchBudget) else PatchSearchBudget(**dict(candidate_budget or {}))
        candidates = tuple(localization.candidates)
        # CORE-4 may expose both a file fallback and a symbol candidate for
        # one location.  Prefer the more actionable symbol evidence while
        # retaining file suspects as bounded supporting context.
        symbol_candidates = tuple(item for item in candidates if getattr(item, "symbol", None))
        file_candidates = tuple(item for item in candidates if not getattr(item, "symbol", None))
        candidates = symbol_candidates + file_candidates
        primary = candidates[: budget.max_suspects]
        supporting = candidates[budget.max_suspects: budget.max_suspects + budget.max_supporting_symbols]
        selected = primary + supporting
        files: list[str] = []
        for candidate in candidates:
            if candidate.path and candidate.path not in files:
                files.append(candidate.path)
            if len(files) >= budget.max_candidate_files:
                break
        target_set = RepairTargetSet(
            primary_suspects=tuple(item.reference for item in primary if item.reference),
            supporting_suspects=tuple(item.reference for item in supporting if item.reference),
            candidate_files=tuple(files),
            candidate_ids=tuple(item.candidate_id for item in selected),
        )
        rid = str(repair_id or "REPAIR-" + canonical_hash({
            "task": task_identity or localization.request.task_query_identity,
            "subject": localization.request.subject_identity,
            "revision": localization.request.revision_identity,
            "localization": localization.canonical_hash,
        })[:20])
        return cls(
            repair_id=rid,
            task_identity=str(task_identity or localization.request.task_query_identity),
            subject_identity=localization.request.subject_identity,
            revision_identity=localization.request.revision_identity,
            working_set_identity=(working_set.canonical_hash if working_set else localization.request.working_set_identity),
            fault_localization_identity=localization.canonical_hash,
            target_set=target_set,
            suspect_candidates=tuple(_candidate_record(item) for item in selected),
            hypothesis_ids=tuple(item.hypothesis_id for item in localization.hypotheses),
            evidence_ledger_identity=localization.request.evidence_ledger_identity,
            failure_evidence=localization.request.failure_evidence,
            contracts=tuple(dict(item) for item in contracts),
            invariants=tuple(dict(item) for item in invariants),
            authority_context=dict(authority_context or localization.request.authority_context),
            dnt_context=tuple(dnt_context or localization.request.dnt_context),
            candidate_budget=budget,
            verification_obligations=tuple(dict(item) for item in verification_obligations),
            project_root=str(project_root or (working_set and "") or ""),
        )

    @classmethod
    def from_value(cls, value: Any) -> "RepairProblem":
        if isinstance(value, cls):
            return value
        data = dict(value or {})
        return cls(
            repair_id=str(data.get("repair_id", "repair")),
            task_identity=str(data.get("task_identity", data.get("task", ""))),
            subject_identity=str(data.get("subject_identity", data.get("subject", ""))),
            revision_identity=str(data.get("revision_identity", data.get("revision", ""))),
            working_set_identity=str(data.get("working_set_identity", "")),
            fault_localization_identity=str(data.get("fault_localization_identity", data.get("localization_identity", ""))),
            target_set=data.get("target_set", {}),
            suspect_candidates=tuple(data.get("suspect_candidates", ()) or ()),
            hypothesis_ids=tuple(data.get("hypothesis_ids", ()) or ()),
            evidence_ledger_identity=str(data.get("evidence_ledger_identity", "")),
            failure_evidence=tuple(data.get("failure_evidence", ()) or ()),
            contracts=tuple(data.get("contracts", ()) or ()),
            invariants=tuple(data.get("invariants", ()) or ()),
            authority_context=dict(data.get("authority_context", data.get("authority", {})) or {}),
            dnt_context=tuple(data.get("dnt_context", data.get("dnt_paths", ())) or ()),
            candidate_budget=data.get("candidate_budget", PatchSearchBudget()),
            verification_obligations=tuple(data.get("verification_obligations", ()) or ()),
            metadata=dict(data.get("metadata", {}) or {}),
            project_root=str(data.get("project_root", "")),
        )

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def evidence_packet(self) -> RepairEvidencePacket:
        return RepairEvidencePacket(
            repair_id=self.repair_id, task_identity=self.task_identity,
            suspect_references=self.target_set.primary_suspects + self.target_set.supporting_suspects,
            hypothesis_ids=self.hypothesis_ids,
            failure_ids=tuple(item.failure_id for item in self.failure_evidence),
            contracts=tuple(str(item.get("statement", item.get("type", ""))) for item in self.contracts),
            authority_summary={
                "approved_mutation_scope": self.authority_context.get("approved_mutation_scope", ()),
                "dnt_context": self.dnt_context,
            },
        )

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "schema_version": CORE5_SCHEMA_VERSION,
            "repair_id": self.repair_id,
            "task_identity": self.task_identity,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "working_set_identity": self.working_set_identity,
            "fault_localization_identity": self.fault_localization_identity,
            "target_set": self.target_set.to_dict(include_hash=False),
            "suspect_candidates": list(self.suspect_candidates),
            "hypothesis_ids": list(self.hypothesis_ids),
            "evidence_ledger_identity": self.evidence_ledger_identity,
            "failure_evidence": [item.to_dict() for item in self.failure_evidence],
            "contracts": list(self.contracts),
            "invariants": list(self.invariants),
            "authority_context": dict(self.authority_context),
            "dnt_context": list(self.dnt_context),
            "candidate_budget": self.candidate_budget.to_dict(),
            "verification_obligations": list(self.verification_obligations),
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


__all__ = [
    "CORE5_SCHEMA_VERSION", "DIAGNOSTIC_SUSPECT", "FINAL_MUTATION_AUTHORIZED",
    "READ_ONLY_SUPPORT", "DNT_PROTECTED", "PatchSearchBudget", "CandidateSearchBudget",
    "RepairTargetSet", "RepairEvidencePacket", "RepairProblem",
]
