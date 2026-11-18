"""Deterministic mutation-strategy routing for HIVO CORE-5.

Routing is intentionally a small, explainable projection of CORE-4 evidence.
It chooses *candidate-generation operators* only; it never authorizes a
mutation, declares a diagnosis true, or replaces V25.5/V25.6.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from .project_brain_refs import canonical_hash


EXACT_VALUE_CHANGE = "EXACT_VALUE_CHANGE"
CONDITION_CHANGE = "CONDITION_CHANGE"
EXPORT_IMPORT_REPAIR = "EXPORT_IMPORT_REPAIR"
FUNCTION_LOCAL_REWRITE = "FUNCTION_LOCAL_REWRITE"
SMALL_INSERTION = "SMALL_INSERTION"
SMALL_DELETION = "SMALL_DELETION"
CALLSITE_ADJUSTMENT = "CALLSITE_ADJUSTMENT"
DEPENDENCY_CONFIGURATION_CHANGE = "DEPENDENCY_CONFIGURATION_CHANGE"
MULTI_LOCATION_SINGLE_FILE_CHANGE = "MULTI_LOCATION_SINGLE_FILE_CHANGE"
MULTI_FILE_BOUNDED_CHANGE = "MULTI_FILE_BOUNDED_CHANGE"
UNKNOWN_STRUCTURAL_CHANGE = "UNKNOWN_STRUCTURAL_CHANGE"

STRATEGY_CLASSES = (
    EXACT_VALUE_CHANGE, CONDITION_CHANGE, EXPORT_IMPORT_REPAIR,
    FUNCTION_LOCAL_REWRITE, SMALL_INSERTION, SMALL_DELETION,
    CALLSITE_ADJUSTMENT, DEPENDENCY_CONFIGURATION_CHANGE,
    MULTI_LOCATION_SINGLE_FILE_CHANGE, MULTI_FILE_BOUNDED_CHANGE,
    UNKNOWN_STRUCTURAL_CHANGE,
)


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            result = value.to_dict()
            return dict(result) if isinstance(result, Mapping) else {}
        except Exception:
            return {}
    return {}


@dataclass(frozen=True)
class StrategyDecision:
    candidate_id: str
    strategies: tuple[str, ...]
    reasons: tuple[str, ...] = ()
    signals: tuple[str, ...] = ()
    authority_label: str = "READ_ONLY_SUPPORT"

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "candidate_id": self.candidate_id,
            "strategies": list(self.strategies),
            "reasons": list(self.reasons),
            "signals": list(self.signals),
            "authority_label": self.authority_label,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


def _candidate_value(candidate: Any) -> dict[str, Any]:
    return _mapping(candidate)


def _failure_values(problem: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for failure in getattr(problem, "failure_evidence", ()) or ():
        result.append(_mapping(failure.to_dict() if hasattr(failure, "to_dict") else failure))
    return result


class MutationStrategyRouter:
    """Route a bounded suspect to deterministic candidate operators."""

    def __init__(self, *, max_strategies: int = 4) -> None:
        self.max_strategies = max(1, int(max_strategies))

    def route(self, problem: Any, candidate: Any | None = None) -> StrategyDecision:
        if candidate is None:
            candidate = (getattr(problem, "suspect_candidates", ()) or ({},))[0]
        value = _candidate_value(candidate)
        metadata: dict[str, Any] = {}
        metadata.update(_mapping(getattr(problem, "metadata", {})))
        for failure in _failure_values(problem):
            metadata.update(_mapping(failure.get("metadata", {})))
            for key in ("expected", "actual", "expected_text", "actual_text", "condition_text", "replacement_text", "duplicate_text", "operations", "target_path", "export", "import"):
                if failure.get(key) is not None:
                    metadata.setdefault(key, failure.get(key))
        for contract in getattr(problem, "contracts", ()) or ():
            contract_value = _mapping(contract)
            metadata.update({key: contract_value[key] for key in ("export_callable", "expected_external", "owner", "condition", "behavior") if contract_value.get(key) is not None})
            metadata.setdefault("contract_text", " ".join(str(value) for value in contract_value.values()))
        metadata.update(_mapping(value.get("metadata", {})))
        text = " ".join(str(metadata.get(key, "")) for key in metadata).casefold()
        failure_type = " ".join(str(item.get("failure_type", "")) for item in _failure_values(problem)).casefold()
        path = str(value.get("path", "")).replace("\\", "/")
        symbol = str(value.get("symbol", ""))
        reasons: list[str] = []
        signals: list[str] = []
        strategies: list[str] = []

        def add(strategy: str, reason: str, signal: str = "") -> None:
            if strategy not in strategies and strategy in STRATEGY_CLASSES:
                strategies.append(strategy)
            if reason not in reasons:
                reasons.append(reason)
            if signal and signal not in signals:
                signals.append(signal)

        if metadata.get("operations") and isinstance(metadata.get("operations"), (list, tuple)):
            operation_count = len(metadata["operations"])
            add(MULTI_FILE_BOUNDED_CHANGE if operation_count > 1 and len({str(_mapping(item).get("path", "")) for item in metadata["operations"]}) > 1 else MULTI_LOCATION_SINGLE_FILE_CHANGE,
                "bounded_operations_are_explicit", "explicit_operations")
        if any(key in metadata for key in ("export", "import", "missing_export", "missing_import", "export_callable", "expected_external")) or "export" in text or "import" in text:
            add(EXPORT_IMPORT_REPAIR, "export_or_import_signal", "module_boundary")
        if any(key in metadata for key in ("condition_text", "condition", "predicate", "branch")) or any(term in text for term in ("condition", "branch", "predicate", "if ")):
            add(CONDITION_CHANGE, "condition_signal", "condition")
        if any(key in metadata for key in ("expected_text", "actual_text", "expected", "actual", "replacement")):
            add(EXACT_VALUE_CHANGE, "explicit_value_pair", "expected_actual")
        if any(key in metadata for key in ("duplicate_text", "duplicate", "remove")) or "duplicate" in text:
            add(SMALL_DELETION, "duplicate_or_removal_signal", "deletion")
        if any(term in text for term in ("callsite", "call site", "caller", "argument")):
            add(CALLSITE_ADJUSTMENT, "callsite_signal", "callsite")
        if any(term in text for term in ("dependency", "configuration", "config", "package")) or path.endswith(("package.json", "pyproject.toml", "requirements.txt")):
            add(DEPENDENCY_CONFIGURATION_CHANGE, "dependency_configuration_signal", "dependency")
        localized_signal = any(term in text for term in ("function", "localized", "body", "callee")) or any(
            term in failure_type for term in ("syntax", "assertion", "runtime", "verification")
        )
        if symbol and not strategies and localized_signal:
            add(FUNCTION_LOCAL_REWRITE, "localized_symbol_candidate", "symbol")
        if any(term in failure_type for term in ("syntax", "assertion", "runtime", "verification")) and symbol:
            add(FUNCTION_LOCAL_REWRITE, "localized_failure_symbol", "failure_location")
        if metadata.get("insertion") or "insert" in text or "add " in text:
            add(SMALL_INSERTION, "insertion_signal", "insertion")

        if len(str(metadata.get("target_paths", "")).split(",")) > 1:
            add(MULTI_FILE_BOUNDED_CHANGE, "bounded_multi_file_target", "multiple_targets")
        if not strategies:
            add(UNKNOWN_STRUCTURAL_CHANGE, "no_deterministic_structural_signal", "unknown")
        if len(strategies) > self.max_strategies:
            strategies = strategies[: self.max_strategies]
        return StrategyDecision(
            candidate_id=str(value.get("candidate_id", value.get("identity", value.get("path", "candidate")))),
            strategies=tuple(strategies), reasons=tuple(reasons), signals=tuple(signals),
            authority_label=str(value.get("authority_label", "READ_ONLY_SUPPORT")),
        )

    def route_problem(self, problem: Any, candidates: Iterable[Any] | None = None) -> tuple[StrategyDecision, ...]:
        rows = candidates if candidates is not None else getattr(problem, "suspect_candidates", ())
        decisions = [self.route(problem, item) for item in rows]
        unique: dict[str, StrategyDecision] = {}
        for item in decisions:
            unique.setdefault(item.candidate_id, item)
        return tuple(unique[key] for key in sorted(unique))


def route_mutation_strategies(problem: Any, candidate: Any, *, max_strategies: int = 4) -> StrategyDecision:
    return MutationStrategyRouter(max_strategies=max_strategies).route(problem, candidate)


__all__ = [
    "EXACT_VALUE_CHANGE", "CONDITION_CHANGE", "EXPORT_IMPORT_REPAIR",
    "FUNCTION_LOCAL_REWRITE", "SMALL_INSERTION", "SMALL_DELETION",
    "CALLSITE_ADJUSTMENT", "DEPENDENCY_CONFIGURATION_CHANGE",
    "MULTI_LOCATION_SINGLE_FILE_CHANGE", "MULTI_FILE_BOUNDED_CHANGE",
    "UNKNOWN_STRUCTURAL_CHANGE", "STRATEGY_CLASSES", "StrategyDecision",
    "MutationStrategyRouter", "route_mutation_strategies",
]
