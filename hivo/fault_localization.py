"""Deterministic multi-signal fault localization for HIVO CORE-4.

CORE-4 is a diagnostic projection.  It consumes current RepositoryMap and
CORE-2 working-set evidence, optional coverage, Brain references, and the
CORE-3 experimental ledger.  It never authorizes a mutation, promotes Brain
truth, or replaces V25.5/V25.6 verification.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict, deque
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .coverage_evidence import (
    COVERAGE_AVAILABLE,
    COVERAGE_NOT_AVAILABLE,
    COVERAGE_STALE,
    CoverageEvidence,
    CoverageEvidenceProvider,
    collect_coverage_evidence,
    coverage_hit_counts,
    ochiai_suspiciousness,
)
from .diagnostic_hypotheses import DETERMINISTIC_SEED, ELIMINATED, DiagnosticHypothesis
from .experimental_evidence import (
    EVIDENCE_VALID,
    EvidenceItem,
    ExperimentalEvidenceLedger,
    DiagnosticResult,
)
from .lexical_index import LexicalIndex, ensure_lexical_index
from .project_brain_refs import (
    ProjectBrainEntity,
    TypedReference,
    canonical_hash,
    normalize_relative_path,
    query_project_brain,
)
from .repo_intelligence import RepoIntelligenceQuery, search_repository
from .repository_map import RepositoryMap
from .task_working_set import (
    MUTATION_AUTHORIZED,
    READ_ONLY_SUPPORT,
    TaskWorkingSet,
    WorkingSetBudget,
)


# ``DNT_PROTECTED`` is a CORE-4 diagnostic label.  CORE-2 intentionally keeps
# DNT entries read-only; this more specific label makes that protection
# visible without changing the CORE-2 authority vocabulary.
DNT_PROTECTED = "DNT_PROTECTED"

CORE4_SCHEMA_VERSION = "CORE-4-MULTI-SIGNAL-FAULT-LOCALIZATION-V1"

TEST_FAILURE = "TEST_FAILURE"
ASSERTION_FAILURE = "ASSERTION_FAILURE"
RUNTIME_EXCEPTION = "RUNTIME_EXCEPTION"
SYNTAX_FAILURE = "SYNTAX_FAILURE"
VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
ORACLE_FAILURE = "ORACLE_FAILURE"
WORKER_EXECUTION_FAILURE = "WORKER_EXECUTION_FAILURE"
INTEGRATION_FAILURE = "INTEGRATION_FAILURE"
FAILURE_TYPES = (
    TEST_FAILURE, ASSERTION_FAILURE, RUNTIME_EXCEPTION, SYNTAX_FAILURE,
    VERIFICATION_FAILURE, ORACLE_FAILURE, WORKER_EXECUTION_FAILURE,
    INTEGRATION_FAILURE,
)

ERROR_LOCATION_SIGNAL = "ERROR_LOCATION_SIGNAL"
STACK_TRACE_SIGNAL = "STACK_TRACE_SIGNAL"
FAILING_TEST_SIGNAL = "FAILING_TEST_SIGNAL"
TEST_DEPENDENCY_SIGNAL = "TEST_DEPENDENCY_SIGNAL"
COVERAGE_SIGNAL = "COVERAGE_SIGNAL"
GRAPH_PROXIMITY_SIGNAL = "GRAPH_PROXIMITY_SIGNAL"
CHANGE_PROXIMITY_SIGNAL = "CHANGE_PROXIMITY_SIGNAL"
LEXICAL_SIGNAL = "LEXICAL_SIGNAL"
BRAIN_CONTRACT_SIGNAL = "BRAIN_CONTRACT_SIGNAL"
EXPERIMENTAL_EVIDENCE_SIGNAL = "EXPERIMENTAL_EVIDENCE_SIGNAL"
SIGNAL_TYPES = (
    ERROR_LOCATION_SIGNAL, STACK_TRACE_SIGNAL, FAILING_TEST_SIGNAL,
    TEST_DEPENDENCY_SIGNAL, COVERAGE_SIGNAL, GRAPH_PROXIMITY_SIGNAL,
    CHANGE_PROXIMITY_SIGNAL, LEXICAL_SIGNAL, BRAIN_CONTRACT_SIGNAL,
    EXPERIMENTAL_EVIDENCE_SIGNAL,
)

LOW = "LOW"
MEDIUM = "MEDIUM"
HIGH = "HIGH"
VERY_HIGH = "VERY_HIGH"
CONFIDENCE_CLASSES = (LOW, MEDIUM, HIGH, VERY_HIGH)

FOCUS_ON_TOP_SUSPECT = "FOCUS_ON_TOP_SUSPECT"
RUN_DIAGNOSTIC_EXPERIMENTS = "RUN_DIAGNOSTIC_EXPERIMENTS"
EXPAND_WORKING_SET = "EXPAND_WORKING_SET"
COLLECT_COVERAGE = "COLLECT_COVERAGE"
COLLECT_STACK_TRACE = "COLLECT_STACK_TRACE"
INVESTIGATE_FLAKINESS = "INVESTIGATE_FLAKINESS"
INSUFFICIENT_LOCALIZATION_EVIDENCE = "INSUFFICIENT_LOCALIZATION_EVIDENCE"

STALE_FAULT_EVIDENCE = "STALE_FAULT_EVIDENCE"
CURRENT = "CURRENT"

CORE4_METRIC_KEYS = (
    "localization_requests", "candidates_considered", "candidates_ranked",
    "symbol_candidates", "file_fallback_candidates", "stack_frames_parsed",
    "project_stack_frames", "external_stack_frames", "failing_tests_consumed",
    "coverage_tests_run", "coverage_symbols_hit", "graph_nodes_examined",
    "change_items_examined", "lexical_candidates_consumed",
    "brain_contracts_consumed", "experimental_evidence_items_consumed",
    "working_set_expansions", "source_bodies_loaded", "top1_hit", "top3_hit",
    "top5_hit", "known_root_rank_before_experiments",
    "known_root_rank_after_experiments", "candidates_deduped",
    "signals_available", "signals_unavailable", "coverage_executions",
)


def new_core4_metrics() -> dict[str, int]:
    return {key: 0 for key in CORE4_METRIC_KEYS}


def _metric(metrics: dict[str, int], key: str, amount: int = 1) -> None:
    metrics[key] = metrics.get(key, 0) + int(amount)


def _string_tuple(values: Iterable[Any] = ()) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values if str(value).strip()}))


def _mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return dict(data) if isinstance(data, Mapping) else {}
        except Exception:
            return {}
    return {}


def _safe_path(value: Any) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or re.match(r"^[A-Za-z]:/", raw):
        return None
    if ".." in raw.split("/"):
        return None
    try:
        return normalize_relative_path(raw)
    except (TypeError, ValueError):
        return None


def _typed_reference(value: Any) -> TypedReference | None:
    if value is None:
        return None
    try:
        return value if isinstance(value, TypedReference) else TypedReference.from_value(value)
    except (TypeError, ValueError):
        return None


def _typed_references(values: Iterable[Any] = ()) -> tuple[TypedReference, ...]:
    result: dict[str, TypedReference] = {}
    for value in values:
        ref = _typed_reference(value)
        if ref is not None:
            result[ref.canonical_uri] = ref
    return tuple(result[key] for key in sorted(result))


def _failure_type(value: Any) -> str:
    raw = str(value or "INTEGRATION_FAILURE").upper()
    return raw if raw in FAILURE_TYPES else raw


@dataclass(frozen=True)
class FaultFailureEvidence:
    """Canonical diagnostic failure input; prose never becomes authority."""

    failure_id: str
    failure_type: str
    message: str = ""
    references: tuple[TypedReference, ...] = ()
    test_name: str = ""
    error_location: str = ""
    path: str = ""
    line: int | None = None
    column: int | None = None
    symbol: str = ""
    expected: Any = None
    actual: Any = None
    stack_trace: str | tuple[Any, ...] = ""
    subject_identity: str = ""
    revision_identity: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_id", str(self.failure_id or "failure"))
        object.__setattr__(self, "failure_type", _failure_type(self.failure_type))
        object.__setattr__(self, "message", str(self.message or "")[:12000])
        object.__setattr__(self, "test_name", str(self.test_name or ""))
        object.__setattr__(self, "error_location", str(self.error_location or ""))
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "line", int(self.line) if self.line not in (None, "") else None)
        object.__setattr__(self, "column", int(self.column) if self.column not in (None, "") else None)
        object.__setattr__(self, "symbol", str(self.symbol or ""))
        references = list(self.references)
        if self.path:
            references.append({"kind": "symbol", "path": self.path, "symbol": self.symbol} if self.symbol else {"kind": "file", "path": self.path})
        object.__setattr__(self, "references", _typed_references(references))
        object.__setattr__(self, "subject_identity", str(self.subject_identity or ""))
        object.__setattr__(self, "revision_identity", str(self.revision_identity or ""))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @classmethod
    def from_value(cls, value: Any) -> "FaultFailureEvidence":
        if isinstance(value, cls):
            return value
        data = _mapping(value)
        metadata = dict(data.get("metadata", {}) or {})
        location = data.get("error_location", data.get("location", ""))
        if isinstance(location, Mapping):
            merged = dict(location)
            path = data.get("path", merged.get("path", ""))
            line = data.get("line", merged.get("line"))
            column = data.get("column", merged.get("column"))
            symbol = data.get("symbol", merged.get("symbol", ""))
            location_text = str(merged.get("display", ""))
        else:
            path = data.get("path", metadata.get("path", ""))
            line = data.get("line", metadata.get("line"))
            column = data.get("column", metadata.get("column"))
            symbol = data.get("symbol", metadata.get("symbol", ""))
            location_text = str(location or "")
        stack = data.get("stack_trace", metadata.get("stack_trace", data.get("stack", "")))
        references = tuple(data.get("references", ()) or ())
        if path and symbol:
            references = references + ({"kind": "symbol", "path": path, "symbol": symbol},)
        elif path:
            references = references + ({"kind": "file", "path": path},)
        return cls(
            failure_id=str(data.get("failure_id", data.get("id", "failure"))),
            failure_type=str(data.get("failure_type", data.get("source_type", data.get("category", INTEGRATION_FAILURE)))),
            message=str(data.get("message", data.get("error", ""))),
            references=references,
            test_name=str(data.get("test_name", data.get("test", metadata.get("test_name", "")))),
            error_location=location_text,
            path=str(path or ""), line=line, column=column, symbol=str(symbol or ""),
            expected=data.get("expected"), actual=data.get("actual"), stack_trace=stack,
            subject_identity=str(data.get("subject_identity", metadata.get("subject_identity", ""))),
            revision_identity=str(data.get("revision_identity", metadata.get("revision_identity", ""))),
            metadata=metadata,
        )

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": CORE4_SCHEMA_VERSION,
            "failure_id": self.failure_id,
            "failure_type": self.failure_type,
            "message": self.message,
            "references": [ref.to_dict() for ref in self.references],
            "test_name": self.test_name,
            "error_location": self.error_location,
            "path": self.path,
            "line": self.line,
            "column": self.column,
            "symbol": self.symbol,
            "expected": self.expected,
            "actual": self.actual,
            "stack_trace": list(self.stack_trace) if isinstance(self.stack_trace, tuple) else self.stack_trace,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class LocalizationBudget:
    """Hard bounds for one localization request."""

    max_candidates: int = 40
    max_graph_nodes: int = 16
    max_graph_depth: int = 2
    max_coverage_tests: int = 5
    max_coverage_executions: int = 5
    max_working_set_expansions: int = 2
    max_evidence_items: int = 64
    max_stack_frames: int = 64
    top_candidates: int = 10
    max_hypotheses: int = 6
    max_file_fallback_candidates: int = 8
    max_source_bodies: int = 2
    max_search_candidates: int = 64

    def __post_init__(self) -> None:
        limits = {
            "max_candidates": (1, 512), "max_graph_nodes": (0, 256),
            "max_graph_depth": (0, 8), "max_coverage_tests": (0, 64),
            "max_coverage_executions": (0, 64), "max_working_set_expansions": (0, 16),
            "max_evidence_items": (0, 512), "max_stack_frames": (1, 256),
            "top_candidates": (1, 64), "max_hypotheses": (1, 64),
            "max_file_fallback_candidates": (1, 64), "max_source_bodies": (0, 64),
            "max_search_candidates": (1, 512),
        }
        for name, (minimum, maximum) in limits.items():
            value = max(minimum, min(maximum, int(getattr(self, name))))
            object.__setattr__(self, name, value)

    def to_dict(self) -> dict[str, int]:
        return {name: int(getattr(self, name)) for name in (
            "max_candidates", "max_graph_nodes", "max_graph_depth", "max_coverage_tests",
            "max_coverage_executions", "max_working_set_expansions", "max_evidence_items",
            "max_stack_frames", "top_candidates", "max_hypotheses", "max_file_fallback_candidates",
            "max_source_bodies", "max_search_candidates",
        )}

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())


FaultLocalizationBudget = LocalizationBudget


@dataclass(frozen=True)
class FaultLocalizationRequest:
    request_id: str = ""
    task_query_identity: str = ""
    subject_identity: str = ""
    revision_identity: str = ""
    failure_evidence: tuple[FaultFailureEvidence, ...] = ()
    working_set_identity: str = ""
    available_signal_types: tuple[str, ...] = SIGNAL_TYPES
    authority_context: dict[str, Any] = field(default_factory=dict)
    dnt_context: tuple[str, ...] = ()
    budget: LocalizationBudget = field(default_factory=LocalizationBudget)
    evidence_ledger_identity: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw_failures = self.failure_evidence
        if isinstance(raw_failures, (Mapping, FaultFailureEvidence)):
            raw_failures = (raw_failures,)
        object.__setattr__(self, "failure_evidence", tuple(FaultFailureEvidence.from_value(item) for item in (raw_failures or ())))
        object.__setattr__(self, "request_id", str(self.request_id or ""))
        object.__setattr__(self, "task_query_identity", str(self.task_query_identity or ""))
        object.__setattr__(self, "subject_identity", str(self.subject_identity or ""))
        object.__setattr__(self, "revision_identity", str(self.revision_identity or ""))
        object.__setattr__(self, "working_set_identity", str(self.working_set_identity or ""))
        object.__setattr__(self, "available_signal_types", tuple(sorted(set(
            str(item) for item in self.available_signal_types if str(item) in SIGNAL_TYPES
        ))))
        object.__setattr__(self, "authority_context", dict(self.authority_context or {}))
        object.__setattr__(self, "dnt_context", tuple(sorted({str(item).replace("\\", "/").lstrip("./") for item in self.dnt_context if str(item).strip()})))
        if isinstance(self.budget, Mapping):
            object.__setattr__(self, "budget", LocalizationBudget(**dict(self.budget)))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        if not self.request_id:
            object.__setattr__(self, "request_id", "FLR-" + canonical_hash({
                "task": self.task_query_identity,
                "subject": self.subject_identity,
                "revision": self.revision_identity,
                "failures": [item.canonical_hash for item in self.failure_evidence],
            })[:16])
        if not self.evidence_ledger_identity:
            object.__setattr__(self, "evidence_ledger_identity", str(self.metadata.get("evidence_ledger_identity", "")))

    @classmethod
    def from_value(cls, value: Any) -> "FaultLocalizationRequest":
        if isinstance(value, cls):
            return value
        data = _mapping(value)
        raw_failures = data.get("failure_evidence", data.get("failures", ()))
        if isinstance(raw_failures, (Mapping, FaultFailureEvidence)):
            raw_failures = (raw_failures,)
        return cls(
            request_id=str(data.get("request_id", "")),
            task_query_identity=str(data.get("task_query_identity", data.get("query_id", data.get("query", "")))),
            subject_identity=str(data.get("subject_identity", data.get("subject", ""))),
            revision_identity=str(data.get("revision_identity", data.get("revision", ""))),
            failure_evidence=tuple(raw_failures or ()),
            working_set_identity=str(data.get("working_set_identity", "")),
            available_signal_types=tuple(data.get("available_signal_types", SIGNAL_TYPES) or SIGNAL_TYPES),
            authority_context=dict(data.get("authority_context", data.get("authority", {})) or {}),
            dnt_context=tuple(data.get("dnt_context", data.get("dnt_paths", ())) or ()),
            budget=data.get("budget", LocalizationBudget()),
            evidence_ledger_identity=str(data.get("evidence_ledger_identity", "")),
            metadata=dict(data.get("metadata", {}) or {}),
        )

    @classmethod
    def from_failure(cls, failure_evidence: Any, *, task_query_identity: str = "", **kwargs: Any) -> "FaultLocalizationRequest":
        return build_fault_localization_request(task_query_identity, failure_evidence, **kwargs)

    @property
    def failure_type(self) -> str:
        return self.failure_evidence[0].failure_type if self.failure_evidence else INTEGRATION_FAILURE

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": CORE4_SCHEMA_VERSION,
            "request_id": self.request_id,
            "task_query_identity": self.task_query_identity,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "failure_evidence": [item.to_dict() for item in self.failure_evidence],
            "working_set_identity": self.working_set_identity,
            "available_signal_types": list(self.available_signal_types),
            "authority_context": dict(self.authority_context),
            "dnt_context": list(self.dnt_context),
            "budget": self.budget.to_dict(),
            "evidence_ledger_identity": self.evidence_ledger_identity,
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class StackFrame:
    ordinal: int
    path: str
    line: int | None = None
    column: int | None = None
    symbol: str | None = None
    project_internal: bool = False
    external_reason: str = ""
    raw: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "ordinal", max(0, int(self.ordinal)))
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "line", int(self.line) if self.line not in (None, "") else None)
        object.__setattr__(self, "column", int(self.column) if self.column not in (None, "") else None)
        object.__setattr__(self, "symbol", str(self.symbol) if self.symbol else None)
        object.__setattr__(self, "project_internal", bool(self.project_internal))
        object.__setattr__(self, "external_reason", str(self.external_reason or ""))
        object.__setattr__(self, "raw", str(self.raw or "")[:1200])

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict())

    def to_dict(self) -> dict[str, Any]:
        return {
            "ordinal": self.ordinal, "path": self.path, "line": self.line,
            "column": self.column, "symbol": self.symbol,
            "project_internal": self.project_internal, "external_reason": self.external_reason,
            "raw": self.raw,
        }


def _stack_line(value: str) -> tuple[str, int | None, int | None]:
    match = re.search(r"(.+?):(\d+)(?::(\d+))?\)?\s*$", value.strip())
    if not match:
        return value.strip(), None, None
    path = match.group(1).strip(" ()\"'")
    if "(" in path:
        path = path.rsplit("(", 1)[-1].strip()
    if path.startswith("at "):
        path = path[3:].strip()
    return path, int(match.group(2)), int(match.group(3)) if match.group(3) else None


def _project_path(root: Path, raw_path: str, repository_map: RepositoryMap) -> tuple[str, bool, str]:
    raw = str(raw_path or "").strip().replace("\\", "/")
    if not raw:
        return "", False, "missing_path"
    root_resolved = root.resolve()
    try:
        candidate = Path(raw)
        if candidate.is_absolute():
            resolved = candidate.resolve()
            relative = resolved.relative_to(root_resolved).as_posix()
        else:
            relative = _safe_path(raw) or ""
    except (OSError, ValueError):
        return raw, False, "outside_project_root"
    if not relative or relative not in repository_map.files:
        reason = "external_dependency" if any(part.casefold() in {"node_modules", "vendor", "site-packages"} for part in relative.split("/")) else "not_in_repository_map"
        return relative, False, reason
    return relative, True, ""


def _symbol_at(repository_map: RepositoryMap, path: str, line: int | None, hinted: str | None = None) -> dict[str, Any] | None:
    rows = [row for row in repository_map.symbols.values() if str(row.get("path", "")) == path]
    if hinted:
        exact = [row for row in rows if str(row.get("qualified_name", "")) == str(hinted) or str(row.get("symbol_id", "")).endswith("::" + str(hinted))]
        if exact:
            rows = exact
    if line is not None:
        containing = [row for row in rows if int(row.get("start_line", 0) or 0) <= line <= int(row.get("end_line", 0) or 0)]
        if containing:
            return sorted(containing, key=lambda row: (int(row.get("end_line", 0)) - int(row.get("start_line", 0)), str(row.get("symbol_id", ""))))[0]
    return sorted(rows, key=lambda row: str(row.get("symbol_id", "")))[0] if len(rows) == 1 else None


def parse_stack_trace(
    stack_trace: str | Iterable[Any],
    project_root: str | Path,
    repository_map: RepositoryMap | Mapping[str, Any],
    *,
    max_frames: int = 64,
) -> tuple[StackFrame, ...]:
    """Parse common JavaScript/Python stack shapes without reading outside root."""
    current = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map, project_root)
    root = Path(project_root).expanduser().resolve()
    raw_rows = list(stack_trace) if not isinstance(stack_trace, str) else stack_trace.splitlines()
    frames: list[StackFrame] = []
    for ordinal, raw in enumerate(raw_rows[: max(0, int(max_frames))]):
        if isinstance(raw, Mapping):
            raw_text = str(raw.get("raw", raw.get("path", "")))
            raw_path = str(raw.get("path", ""))
            line = raw.get("line")
            column = raw.get("column")
            hinted = raw.get("symbol")
        else:
            raw_text = str(raw).strip()
            if not raw_text:
                continue
            hinted_match = re.search(r"at\s+([^ (]+)\s+\(", raw_text)
            hinted = hinted_match.group(1) if hinted_match else None
            quoted = re.search(r'File\s+["\']([^"\']+)["\']', raw_text)
            if quoted:
                raw_path, line, column = _stack_line(raw_text[raw_text.find(quoted.group(1)):])
                raw_path = quoted.group(1)
            else:
                location = re.search(r"(?:at\s+)?(.+?:\d+(?::\d+)?)\)?\s*$", raw_text)
                raw_path, line, column = _stack_line(location.group(1) if location else raw_text)
        try:
            line = int(line) if line not in (None, "") else None
        except (TypeError, ValueError):
            line = None
        try:
            column = int(column) if column not in (None, "") else None
        except (TypeError, ValueError):
            column = None
        path, internal, reason = _project_path(root, raw_path, current)
        symbol_row = _symbol_at(current, path, line, hinted) if internal else None
        frames.append(StackFrame(
            ordinal=ordinal,
            path=path or raw_path,
            line=line,
            column=column,
            symbol=str(symbol_row.get("qualified_name")) if symbol_row else (str(hinted) if hinted else None),
            project_internal=internal,
            external_reason=reason,
            raw=raw_text,
        ))
    return tuple(frames)


parse_stack_frames = parse_stack_trace


class StackTraceParser:
    """Small reusable parser façade for callers that keep a current map."""

    def __init__(self, project_root: str | Path, repository_map: RepositoryMap | Mapping[str, Any]) -> None:
        self.project_root = project_root
        self.repository_map = repository_map

    def parse(self, stack_trace: str | Iterable[Any], *, max_frames: int = 64) -> tuple[StackFrame, ...]:
        return parse_stack_trace(stack_trace, self.project_root, self.repository_map, max_frames=max_frames)


@dataclass(frozen=True)
class FaultCandidate:
    """A ranked diagnostic suspect; never a mutation or verification claim."""

    candidate_id: str
    reference: TypedReference | None = None
    path: str = ""
    symbol: str | None = None
    candidate_kind: str = "file"
    signal_contributions: dict[str, float] = field(default_factory=dict)
    aggregate_suspiciousness_score: float = 0.0
    rank: int = 0
    confidence_class: str = LOW
    supporting_evidence_ids: tuple[str, ...] = ()
    contradicting_evidence_ids: tuple[str, ...] = ()
    staleness_state: str = CURRENT
    authority_label: str = READ_ONLY_SUPPORT
    evidence_sources: tuple[str, ...] = ()
    matched_terms: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    signal_details: dict[str, tuple[dict[str, Any], ...]] = field(default_factory=dict)
    location_confidence: str = LOW
    causal_suspicion: str = "EVIDENCE_ONLY"

    def __post_init__(self) -> None:
        object.__setattr__(self, "candidate_id", str(self.candidate_id or self.path or "candidate"))
        object.__setattr__(self, "path", str(self.path or "").replace("\\", "/"))
        object.__setattr__(self, "symbol", str(self.symbol) if self.symbol else None)
        object.__setattr__(self, "candidate_kind", str(self.candidate_kind or ("symbol" if self.symbol else "file")))
        ref = _typed_reference(self.reference)
        if ref is None and self.path:
            try:
                ref = TypedReference("symbol", self.path, self.symbol) if self.symbol else TypedReference("file", self.path)
            except ValueError:
                ref = None
        object.__setattr__(self, "reference", ref)
        object.__setattr__(self, "signal_contributions", {
            str(key): round(float(value), 6) for key, value in sorted(dict(self.signal_contributions or {}).items())
        })
        object.__setattr__(self, "aggregate_suspiciousness_score", round(float(self.aggregate_suspiciousness_score), 6))
        object.__setattr__(self, "rank", max(0, int(self.rank)))
        if self.confidence_class not in CONFIDENCE_CLASSES:
            object.__setattr__(self, "confidence_class", LOW)
        object.__setattr__(self, "supporting_evidence_ids", _string_tuple(self.supporting_evidence_ids))
        object.__setattr__(self, "contradicting_evidence_ids", _string_tuple(self.contradicting_evidence_ids))
        object.__setattr__(self, "evidence_sources", _string_tuple(self.evidence_sources))
        object.__setattr__(self, "matched_terms", _string_tuple(self.matched_terms))
        object.__setattr__(self, "reasons", _string_tuple(self.reasons))
        details: dict[str, tuple[dict[str, Any], ...]] = {}
        raw_details = dict(self.signal_details or {})
        for key in sorted(raw_details):
            rows = raw_details[key]
            if isinstance(rows, Mapping):
                rows = (rows,)
            details[str(key)] = tuple(dict(row) for row in (rows or ()) if isinstance(row, Mapping))
        object.__setattr__(self, "signal_details", details)
        object.__setattr__(self, "staleness_state", str(self.staleness_state or CURRENT))
        object.__setattr__(self, "authority_label", str(self.authority_label or READ_ONLY_SUPPORT))
        object.__setattr__(self, "location_confidence", str(self.location_confidence or LOW))
        object.__setattr__(self, "causal_suspicion", str(self.causal_suspicion or "EVIDENCE_ONLY"))

    @property
    def identity(self) -> str:
        return self.candidate_id

    @property
    def score(self) -> float:
        return self.aggregate_suspiciousness_score

    @property
    def candidate_type(self) -> str:
        return self.candidate_kind

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @classmethod
    def from_value(cls, value: Any) -> "FaultCandidate":
        if isinstance(value, cls):
            return value
        data = _mapping(value)
        return cls(
            candidate_id=str(data.get("candidate_id", data.get("identity", data.get("path", "candidate")))),
            reference=data.get("reference"), path=str(data.get("path", "")),
            symbol=data.get("symbol"), candidate_kind=str(data.get("candidate_kind", data.get("candidate_type", "file"))),
            signal_contributions=dict(data.get("signal_contributions", data.get("contributions", {})) or {}),
            aggregate_suspiciousness_score=float(data.get("aggregate_suspiciousness_score", data.get("score", 0.0))),
            rank=int(data.get("rank", 0) or 0), confidence_class=str(data.get("confidence_class", LOW)),
            supporting_evidence_ids=tuple(data.get("supporting_evidence_ids", ()) or ()),
            contradicting_evidence_ids=tuple(data.get("contradicting_evidence_ids", ()) or ()),
            staleness_state=str(data.get("staleness_state", CURRENT)),
            authority_label=str(data.get("authority_label", READ_ONLY_SUPPORT)),
            evidence_sources=tuple(data.get("evidence_sources", ()) or ()),
            matched_terms=tuple(data.get("matched_terms", ()) or ()),
            reasons=tuple(data.get("reasons", ()) or ()),
            signal_details=dict(data.get("signal_details", {}) or {}),
            location_confidence=str(data.get("location_confidence", LOW)),
            causal_suspicion=str(data.get("causal_suspicion", "EVIDENCE_ONLY")),
        )

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": CORE4_SCHEMA_VERSION,
            "candidate_id": self.candidate_id,
            "reference": self.reference.to_dict() if self.reference else None,
            "path": self.path,
            "symbol": self.symbol,
            "candidate_kind": self.candidate_kind,
            "signal_contributions": dict(self.signal_contributions),
            "aggregate_suspiciousness_score": self.aggregate_suspiciousness_score,
            "rank": self.rank,
            "confidence_class": self.confidence_class,
            "supporting_evidence_ids": list(self.supporting_evidence_ids),
            "contradicting_evidence_ids": list(self.contradicting_evidence_ids),
            "staleness_state": self.staleness_state,
            "authority_label": self.authority_label,
            "evidence_sources": list(self.evidence_sources),
            "matched_terms": list(self.matched_terms),
            "reasons": list(self.reasons),
            "signal_details": {key: list(self.signal_details[key]) for key in sorted(self.signal_details)},
            "location_confidence": self.location_confidence,
            "causal_suspicion": self.causal_suspicion,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class FaultLocalizationResult:
    request: FaultLocalizationRequest
    failure_type: str
    signals_available: tuple[str, ...] = ()
    signals_unavailable: tuple[str, ...] = ()
    candidates: tuple[FaultCandidate, ...] = ()
    top_suspects: tuple[str, ...] = ()
    ranking_explanations: tuple[dict[str, Any], ...] = ()
    working_set: TaskWorkingSet | None = None
    working_set_expansions: tuple[dict[str, Any], ...] = ()
    budget_usage: dict[str, int] = field(default_factory=dict)
    coverage_status: str = COVERAGE_NOT_AVAILABLE
    experimental_evidence_status: str = "NOT_PROVIDED"
    unresolved_evidence: tuple[dict[str, Any], ...] = ()
    recommended_next_action: str = INSUFFICIENT_LOCALIZATION_EVIDENCE
    metrics: dict[str, int] = field(default_factory=dict)
    hypotheses: tuple[DiagnosticHypothesis, ...] = ()
    known_root_rank_before_experiments: int = 0
    known_root_rank_after_experiments: int = 0
    canonical_subject_identity: str = ""

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def top_candidates(self) -> tuple[FaultCandidate, ...]:
        return self.candidates[: self.request.budget.top_candidates]

    @property
    def ranked_candidates(self) -> tuple[FaultCandidate, ...]:
        return self.candidates

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": CORE4_SCHEMA_VERSION,
            "request": self.request.to_dict(),
            "failure_type": self.failure_type,
            "signals_available": list(self.signals_available),
            "signals_unavailable": list(self.signals_unavailable),
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "top_suspects": list(self.top_suspects),
            "ranking_explanations": list(self.ranking_explanations),
            "working_set": self.working_set.to_dict() if self.working_set else None,
            "working_set_expansions": list(self.working_set_expansions),
            "budget_usage": dict(self.budget_usage),
            "coverage_status": self.coverage_status,
            "experimental_evidence_status": self.experimental_evidence_status,
            "unresolved_evidence": list(self.unresolved_evidence),
            "recommended_next_action": self.recommended_next_action,
            "metrics": dict(self.metrics),
            "hypotheses": [item.to_dict() for item in self.hypotheses],
            "known_root_rank_before_experiments": self.known_root_rank_before_experiments,
            "known_root_rank_after_experiments": self.known_root_rank_after_experiments,
            "canonical_subject_identity": self.canonical_subject_identity,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    def rerank_with_experimental_evidence(
        self,
        evidence: ExperimentalEvidenceLedger | DiagnosticResult | Mapping[str, Any],
        *,
        hypotheses: Iterable[DiagnosticHypothesis] = (),
    ) -> "FaultLocalizationResult":
        return rerank_with_experimental_evidence(self, evidence, hypotheses=hypotheses)


def _authority_label(path: str, authority: Mapping[str, Any] | None, dnt_paths: Iterable[str]) -> str:
    normalized = str(path or "").replace("\\", "/").lstrip("./")
    dnt = {str(item).replace("\\", "/").lstrip("./") for item in dnt_paths}
    if normalized in dnt:
        return DNT_PROTECTED
    authority = authority or {}
    values: list[Any] = []
    for key in ("do_not_touch", "dnt", "approved_dnt", "approved_do_not_touch"):
        value = authority.get(key)
        if isinstance(value, Mapping):
            values.extend(value.get("paths", value.get("files", ())) or ())
        elif isinstance(value, (list, tuple, set)):
            values.extend(value)
        elif isinstance(value, str):
            values.append(value)
    if normalized in {str(item).replace("\\", "/").lstrip("./") for item in values}:
        return DNT_PROTECTED
    approved = authority.get("approved_mutation_scope", authority.get("mutation_scope", authority.get("authorized_paths", ())))
    if isinstance(approved, str):
        approved = (approved,)
    if isinstance(approved, Mapping):
        approved = approved.get("paths", approved.get("files", ()))
    approved_paths = {str(item).replace("\\", "/").lstrip("./") for item in (approved or ())}
    return MUTATION_AUTHORIZED if normalized in approved_paths else READ_ONLY_SUPPORT


def _current_source_identity(repository_map: RepositoryMap, path: str, symbol: Mapping[str, Any] | None = None) -> str:
    if symbol:
        return str(symbol.get("anchor_hash") or "")
    return str(repository_map.files.get(path, {}).get("content_hash") or "")


def _symbol_row(repository_map: RepositoryMap, path: str, symbol: str | None) -> dict[str, Any] | None:
    if not symbol:
        return None
    rows = [row for row in repository_map.symbols.values() if str(row.get("path")) == path and (
        str(row.get("qualified_name")) == symbol or str(row.get("symbol_id")) == symbol
    )]
    return sorted(rows, key=lambda row: str(row.get("symbol_id", "")))[0] if rows else None


class _CandidateAccumulator:
    """Merge signal observations while capping repetitive families."""

    _caps = {
        ERROR_LOCATION_SIGNAL: 9.0, STACK_TRACE_SIGNAL: 8.0,
        FAILING_TEST_SIGNAL: 8.0, TEST_DEPENDENCY_SIGNAL: 6.0,
        COVERAGE_SIGNAL: 7.0, GRAPH_PROXIMITY_SIGNAL: 6.0,
        CHANGE_PROXIMITY_SIGNAL: 3.0, LEXICAL_SIGNAL: 5.0,
        BRAIN_CONTRACT_SIGNAL: 3.0, EXPERIMENTAL_EVIDENCE_SIGNAL: 6.0,
    }

    def __init__(self, repository_map: RepositoryMap, authority: Mapping[str, Any] | None, dnt_paths: Iterable[str]) -> None:
        self.repository_map = repository_map
        self.authority = authority or {}
        self.dnt_paths = tuple(dnt_paths)
        self.rows: dict[str, dict[str, Any]] = {}
        self.raw_count = 0

    def _identity(self, path: str, symbol: str | None) -> str:
        return f"{path}::symbol::{symbol}" if symbol else path

    def add(
        self,
        *,
        path: str,
        symbol: str | None = None,
        candidate_kind: str = "file",
        signal: str,
        value: float,
        reason: str,
        evidence_id: str = "",
        matched_terms: Iterable[str] = (),
        staleness_state: str = CURRENT,
        signal_detail: Mapping[str, Any] | None = None,
    ) -> str | None:
        safe = _safe_path(path)
        if not safe or safe not in self.repository_map.files:
            return None
        row_symbol = _symbol_row(self.repository_map, safe, symbol)
        if symbol and row_symbol is None:
            # Parsing cannot support a symbol identity; fall back to file evidence.
            symbol = None
            candidate_kind = "file"
        if symbol:
            candidate_kind = "symbol"
        identity = self._identity(safe, symbol)
        self.raw_count += 1
        row = self.rows.setdefault(identity, {
            "candidate_id": identity, "path": safe, "symbol": symbol,
            "candidate_kind": candidate_kind, "contributions": defaultdict(float),
            "details": defaultdict(list), "supporting": set(), "contradicting": set(),
            "sources": set(), "terms": set(), "reasons": set(), "staleness": CURRENT,
            "authority": _authority_label(safe, self.authority, self.dnt_paths),
        })
        cap = float(self._caps.get(signal, 5.0))
        before = float(row["contributions"].get(signal, 0.0))
        after = max(-cap, min(cap, before + float(value)))
        row["contributions"][signal] = after
        row["sources"].add(signal)
        row["terms"].update(str(item) for item in matched_terms if str(item).strip())
        row["reasons"].add(str(reason))
        if evidence_id:
            (row["supporting"] if value >= 0 else row["contradicting"]).add(str(evidence_id))
        if staleness_state == CURRENT:
            row["staleness"] = CURRENT
        elif staleness_state != CURRENT:
            row["staleness"] = str(staleness_state)
        detail = dict(signal_detail or {})
        detail.update({"reason": str(reason), "delta": round(after - before, 6)})
        if evidence_id:
            detail["evidence_id"] = str(evidence_id)
        row["details"][signal].append(detail)
        return identity

    def freeze(self, *, top_limit: int = 10) -> tuple[FaultCandidate, ...]:
        candidates: list[FaultCandidate] = []
        for identity, row in self.rows.items():
            contributions = {key: round(float(value), 6) for key, value in row["contributions"].items() if abs(float(value)) > 0.000001}
            support = {key for key, value in contributions.items() if value > 0}
            contradictions = {key for key, value in contributions.items() if value < 0}
            bonus = min(6.0, max(0.0, 2.0 * (len(support) - 1))) if len(support) > 1 else 0.0
            if bonus:
                contributions["MULTI_SIGNAL_BONUS"] = round(bonus, 6)
            score = round(sum(contributions.values()), 6)
            strong_contradiction = any(contributions.get(key, 0.0) <= -3.0 for key in contradictions)
            if len(support) >= 4 and not strong_contradiction:
                confidence = VERY_HIGH
            elif len(support) >= 3 and not strong_contradiction:
                confidence = HIGH
            elif len(support) >= 2:
                confidence = MEDIUM
            else:
                confidence = LOW
            if row["staleness"] != CURRENT:
                confidence = LOW if confidence == VERY_HIGH else (MEDIUM if confidence == HIGH else confidence)
            location_signal = ERROR_LOCATION_SIGNAL in support or STACK_TRACE_SIGNAL in support
            location_confidence = HIGH if location_signal else (MEDIUM if support else LOW)
            causal = "HIGH" if len(support) >= 3 and not strong_contradiction else ("MEDIUM" if len(support) >= 2 else "EVIDENCE_ONLY")
            try:
                reference = TypedReference("symbol", row["path"], row["symbol"]) if row["symbol"] else TypedReference("file", row["path"])
            except ValueError:
                reference = None
            candidates.append(FaultCandidate(
                candidate_id=identity, reference=reference, path=row["path"], symbol=row["symbol"],
                candidate_kind=row["candidate_kind"], signal_contributions=contributions,
                aggregate_suspiciousness_score=score, confidence_class=confidence,
                supporting_evidence_ids=tuple(sorted(row["supporting"])),
                contradicting_evidence_ids=tuple(sorted(row["contradicting"])),
                staleness_state=row["staleness"], authority_label=row["authority"],
                evidence_sources=tuple(sorted(row["sources"])), matched_terms=tuple(sorted(row["terms"])),
                reasons=tuple(sorted(row["reasons"])),
                signal_details={key: tuple(dict(item) for item in row["details"][key]) for key in sorted(row["details"])},
                location_confidence=location_confidence, causal_suspicion=causal,
            ))
        candidates.sort(key=lambda item: (-item.score, item.candidate_id))
        return tuple(replace(item, rank=index) for index, item in enumerate(candidates[: max(0, int(top_limit))], 1))


def _evidence_current(
    evidence: FaultFailureEvidence,
    request: FaultLocalizationRequest,
) -> bool:
    if evidence.subject_identity and request.subject_identity and evidence.subject_identity != request.subject_identity:
        return False
    if evidence.revision_identity and request.revision_identity and evidence.revision_identity != request.revision_identity:
        return False
    metadata = evidence.metadata
    if metadata.get("staleness_state") in {STALE_FAULT_EVIDENCE, "STALE_REFERENCE", "STALE"}:
        return False
    return True


def _failure_path_symbols(failure: FaultFailureEvidence, repository_map: RepositoryMap) -> tuple[tuple[str, str | None, int | None], ...]:
    values: list[tuple[str, str | None, int | None]] = []
    refs = list(failure.references)
    if failure.path:
        try:
            refs.append(TypedReference("symbol", failure.path, failure.symbol) if failure.symbol else TypedReference("file", failure.path))
        except ValueError:
            pass
    for ref in refs:
        path = _safe_path(ref.path)
        if not path:
            continue
        symbol = ref.symbol
        if path not in repository_map.files:
            continue
        if symbol is None and failure.line is not None:
            row = _symbol_at(repository_map, path, failure.line)
            symbol = str(row.get("qualified_name")) if row else None
        values.append((path, symbol, failure.line))
    # A location string such as src/a.js:10:2 is safe to parse but never read.
    if failure.error_location:
        raw_path, raw_line, _ = _stack_line(failure.error_location)
        path = _safe_path(raw_path)
        if path and path in repository_map.files:
            row = _symbol_at(repository_map, path, raw_line, failure.symbol)
            values.append((path, str(row.get("qualified_name")) if row else failure.symbol or None, raw_line))
    seen: dict[tuple[str, str | None, int | None], None] = {}
    for item in values:
        seen[item] = None
    return tuple(sorted(seen))


def _add_error_location(
    accumulator: _CandidateAccumulator,
    failure: FaultFailureEvidence,
    repository_map: RepositoryMap,
    *,
    evidence_id: str,
) -> bool:
    added = False
    for path, symbol, line in _failure_path_symbols(failure, repository_map):
        if symbol:
            added = bool(accumulator.add(
                path=path, symbol=symbol, signal=ERROR_LOCATION_SIGNAL, value=9.0,
                reason="exact_current_error_location_symbol", evidence_id=evidence_id,
                signal_detail={"path": path, "line": line, "match": "symbol"},
            )) or added
        else:
            added = bool(accumulator.add(
                path=path, signal=ERROR_LOCATION_SIGNAL, value=6.0,
                reason="current_error_location_file", evidence_id=evidence_id,
                signal_detail={"path": path, "line": line, "match": "file"},
            )) or added
        # A nearby symbol is useful evidence, but deliberately weaker than an
        # exact symbol location.
        if line is not None and not symbol:
            row = _symbol_at(repository_map, path, line)
            if row:
                accumulator.add(
                    path=path, symbol=str(row.get("qualified_name")), signal=ERROR_LOCATION_SIGNAL,
                    value=4.0, reason="line_mapped_current_symbol", evidence_id=evidence_id,
                    signal_detail={"path": path, "line": line, "match": "line_symbol"},
                )
    return added


def _add_stack_signal(
    accumulator: _CandidateAccumulator,
    failure: FaultFailureEvidence,
    repository_map: RepositoryMap,
    project_root: Path,
    metrics: dict[str, int],
    *,
    max_frames: int,
) -> tuple[StackFrame, ...]:
    stack = failure.stack_trace or failure.metadata.get("stack_trace", "")
    if not stack:
        return ()
    frames = parse_stack_trace(stack, project_root, repository_map, max_frames=max_frames)
    _metric(metrics, "stack_frames_parsed", len(frames))
    _metric(metrics, "project_stack_frames", sum(frame.project_internal for frame in frames))
    _metric(metrics, "external_stack_frames", sum(not frame.project_internal for frame in frames))
    project_frames = [frame for frame in frames if frame.project_internal]
    for frame in project_frames:
        # Depth is intentionally capped and weak.  It cannot by itself make a
        # stack top a root-cause assertion.
        value = max(1.0, 5.0 - min(4.0, float(frame.ordinal)))
        identity = f"stack:{failure.failure_id}:{frame.ordinal}"
        if frame.symbol and _symbol_row(repository_map, frame.path, frame.symbol):
            accumulator.add(
                path=frame.path, symbol=frame.symbol, signal=STACK_TRACE_SIGNAL, value=value,
                reason="project_stack_frame", evidence_id=identity,
                signal_detail={"ordinal": frame.ordinal, "line": frame.line, "column": frame.column, "top_frame": frame.ordinal == 0},
            )
        else:
            accumulator.add(
                path=frame.path, signal=STACK_TRACE_SIGNAL, value=value * 0.8,
                reason="project_stack_file_frame", evidence_id=identity,
                signal_detail={"ordinal": frame.ordinal, "line": frame.line, "column": frame.column, "top_frame": frame.ordinal == 0},
            )
    return frames


def _test_paths(repository_map: RepositoryMap, failure: FaultFailureEvidence) -> tuple[str, ...]:
    candidates: set[str] = set()
    name = failure.test_name.casefold()
    for path, entry in repository_map.files.items():
        if not entry.get("is_test"):
            continue
        if not name or name in path.casefold() or name in " ".join(entry.get("exports", ())).casefold():
            candidates.add(path)
    for ref in failure.references:
        if ref.kind == "test" and _safe_path(ref.path) in repository_map.files:
            candidates.add(_safe_path(ref.path) or "")
    return tuple(sorted(path for path in candidates if path))


def _add_test_signal(
    accumulator: _CandidateAccumulator,
    failure: FaultFailureEvidence,
    repository_map: RepositoryMap,
    metrics: dict[str, int],
) -> tuple[str, ...]:
    if failure.failure_type not in {TEST_FAILURE, ASSERTION_FAILURE, VERIFICATION_FAILURE, ORACLE_FAILURE, INTEGRATION_FAILURE} and not failure.test_name:
        return ()
    tests = _test_paths(repository_map, failure)
    if not tests:
        return ()
    _metric(metrics, "failing_tests_consumed", len(tests))
    for test_path in tests:
        test_id = f"test:{test_path}"
        accumulator.add(path=test_path, candidate_kind="test", signal=FAILING_TEST_SIGNAL, value=3.0,
                        reason="failing_test_reference", evidence_id=test_id,
                        signal_detail={"test_path": test_path})
        entry = repository_map.files.get(test_path, {})
        for imported in entry.get("imports", ()):
            source = _safe_path(imported.get("resolved_path")) if isinstance(imported, Mapping) else None
            if not source or source not in repository_map.files:
                continue
            accumulator.add(path=source, signal=FAILING_TEST_SIGNAL, value=6.0,
                            reason="failing_test_direct_import", evidence_id=test_id,
                            signal_detail={"test_path": test_path, "relation": "direct_import"})
            accumulator.add(path=source, signal=TEST_DEPENDENCY_SIGNAL, value=3.0,
                            reason="test_dependency_mapping", evidence_id=test_id,
                            signal_detail={"test_path": test_path, "relation": "imports"})
    # The map also has explicit tested_by relationships for source files whose
    # names are not obvious from the test name.
    for path, entry in repository_map.files.items():
        if any(test in tests for test in entry.get("known_tests", ())):
            accumulator.add(path=path, signal=TEST_DEPENDENCY_SIGNAL, value=4.0,
                            reason="tested_by_relationship", evidence_id=f"tested_by:{path}",
                            signal_detail={"tests": list(entry.get("known_tests", ()))})
    return tests


def _add_graph_signal(
    accumulator: _CandidateAccumulator,
    repository_map: RepositoryMap,
    seed_paths: Iterable[str],
    metrics: dict[str, int],
    budget: LocalizationBudget,
) -> None:
    remaining_nodes = max(0, budget.max_graph_nodes - metrics.get("graph_nodes_examined", 0))
    queue: deque[tuple[str, int]] = deque((path, 0) for path in sorted(set(seed_paths)) if path in repository_map.files)
    visited: set[str] = set()
    nodes = 0
    while queue and nodes < remaining_nodes:
        path, distance = queue.popleft()
        if path in visited or distance > budget.max_graph_depth:
            continue
        visited.add(path)
        for edge in repository_map.edges:
            source = str(edge.get("source", ""))
            target = str(edge.get("target", ""))
            kind = str(edge.get("kind", ""))
            neighbor = ""
            relation = kind
            if source == path and target in repository_map.files:
                neighbor = target
            elif target == path and source in repository_map.files and kind in {"depends_on", "imports", "tested_by"}:
                neighbor = source
                relation = "reverse_" + kind
            if not neighbor or neighbor == path or neighbor in visited:
                continue
            nodes += 1
            _metric(metrics, "graph_nodes_examined")
            if repository_map.files.get(neighbor, {}).get("is_test") or "test" in relation:
                accumulator.add(path=neighbor, candidate_kind="test", signal=TEST_DEPENDENCY_SIGNAL,
                                value=max(1.0, 4.0 / (distance + 1)), reason="bounded_test_graph_relation",
                                evidence_id=f"graph:{path}:{neighbor}",
                                signal_detail={"source": path, "relation": relation, "distance": distance + 1})
            else:
                accumulator.add(path=neighbor, candidate_kind="dependency", signal=GRAPH_PROXIMITY_SIGNAL,
                                value=max(1.0, 4.0 / (distance + 1)), reason="bounded_graph_proximity",
                                evidence_id=f"graph:{path}:{neighbor}",
                                signal_detail={"source": path, "relation": relation, "distance": distance + 1})
            if distance + 1 <= budget.max_graph_depth:
                queue.append((neighbor, distance + 1))
            if nodes >= remaining_nodes:
                break


def _add_lexical_signal(
    accumulator: _CandidateAccumulator,
    failure: FaultFailureEvidence,
    repository_map: RepositoryMap,
    project_root: Path,
    lexical_index: LexicalIndex | Mapping[str, Any] | None,
    metrics: dict[str, int],
    budget: LocalizationBudget,
) -> tuple[LexicalIndex, str, int]:
    index, mode = ensure_lexical_index(lexical_index, repository_map, project_root)
    query = " ".join(item for item in (
        failure.message, failure.error_location, failure.symbol, failure.test_name,
        " ".join(str(ref.symbol or ref.path) for ref in failure.references),
    ) if item)
    rows = index.query(query, max_results=min(24, budget.max_candidates))
    _metric(metrics, "lexical_candidates_consumed", len(rows))
    error_tokens = set(re.findall(r"[A-Za-z_$][A-Za-z0-9_$.-]{2,}", failure.message.casefold()))
    for row in rows:
        path = str(row.get("path", ""))
        matched = tuple(row.get("matched_terms", ()))
        reason = "lexical_error_token_match" if error_tokens & set(matched) else "lexical_identifier_match"
        accumulator.add(
            path=path, signal=LEXICAL_SIGNAL, value=min(5.0, max(1.0, float(row.get("score", 0.0)) / 3.0)),
            reason=reason, evidence_id=f"lexical:{path}", matched_terms=matched,
            signal_detail={"score": float(row.get("score", 0.0)), "index_mode": mode},
        )
    return index, mode, len(rows)


def _brain_rows(entities: Iterable[Any], query: str) -> tuple[ProjectBrainEntity, ...]:
    normalized: list[ProjectBrainEntity] = []
    for raw in entities:
        try:
            normalized.append(raw if isinstance(raw, ProjectBrainEntity) else ProjectBrainEntity.from_dict(raw))
        except (TypeError, ValueError):
            continue
    if not normalized:
        return ()
    selected = query_project_brain(normalized, query, max_items=len(normalized), include_stale=True)
    by_id = {entity.entity_id: entity for entity in normalized}
    return tuple(by_id[row["entity_id"]] for row in selected if row.get("entity_id") in by_id)


def _add_brain_signal(
    accumulator: _CandidateAccumulator,
    entities: Iterable[Any],
    query: str,
    repository_map: RepositoryMap,
    metrics: dict[str, int],
) -> None:
    for entity in _brain_rows(entities, query):
        for ref in entity.references:
            path = _safe_path(ref.path)
            if not path or path not in repository_map.files:
                continue
            stale = entity.staleness_state != CURRENT
            value = -1.0 if stale else 2.0
            accumulator.add(
                path=path, symbol=ref.symbol, signal=BRAIN_CONTRACT_SIGNAL, value=value,
                reason="stale_brain_reference_downgraded" if stale else "brain_contract_boundary_reference",
                evidence_id=f"brain:{entity.entity_id}", staleness_state="STALE_REFERENCE" if stale else CURRENT,
                signal_detail={"entity_id": entity.entity_id, "contracts": list(entity.contracts), "invariants": list(entity.invariants)},
            )
            _metric(metrics, "brain_contracts_consumed")


def _change_values(
    change_evidence: Any,
    request: FaultLocalizationRequest,
) -> tuple[tuple[str, ...], tuple[str, ...], str]:
    rows: list[Mapping[str, Any]] = []
    if change_evidence is not None:
        if isinstance(change_evidence, Mapping):
            rows = [change_evidence]
        elif isinstance(change_evidence, (list, tuple)):
            rows = [row for row in change_evidence if isinstance(row, Mapping)]
    metadata = request.metadata
    paths: set[str] = set()
    symbols: set[str] = set()
    source = ""
    for data in rows + [metadata]:
        source = source or str(data.get("source", data.get("provenance", "")))
        for key in ("changed_paths", "paths", "files", "changed_files"):
            values = data.get(key, ())
            if isinstance(values, str):
                values = (values,)
            paths.update(path for value in (values or ()) if (path := _safe_path(value)))
        for key in ("changed_symbols", "symbols"):
            values = data.get(key, ())
            if isinstance(values, str):
                values = (values,)
            symbols.update(str(value) for value in (values or ()) if str(value).strip())
    return tuple(sorted(paths)), tuple(sorted(symbols)), source


def _add_change_signal(
    accumulator: _CandidateAccumulator,
    repository_map: RepositoryMap,
    request: FaultLocalizationRequest,
    change_evidence: Any,
    metrics: dict[str, int],
) -> tuple[str, ...]:
    paths, symbols, source = _change_values(change_evidence, request)
    for path in paths:
        accumulator.add(path=path, signal=CHANGE_PROXIMITY_SIGNAL, value=2.0,
                        reason="known_changed_path_bounded_bonus", evidence_id=f"change:{path}",
                        signal_detail={"source": source or "provided_change_evidence"})
        _metric(metrics, "change_items_examined")
    for identity in symbols:
        if "::" in identity:
            path, symbol = identity.split("::", 1)
        elif "#" in identity:
            path, symbol = identity.split("#", 1)
        else:
            matches = [row for row in repository_map.symbols.values() if str(row.get("qualified_name")) == identity]
            for row in matches:
                accumulator.add(path=str(row.get("path")), symbol=identity, signal=CHANGE_PROXIMITY_SIGNAL,
                                value=2.5, reason="known_changed_symbol_bounded_bonus", evidence_id=f"change:{identity}")
                _metric(metrics, "change_items_examined")
            continue
        path = _safe_path(path)
        if path:
            accumulator.add(path=path, symbol=symbol, signal=CHANGE_PROXIMITY_SIGNAL, value=2.5,
                            reason="known_changed_symbol_bounded_bonus", evidence_id=f"change:{identity}")
            _metric(metrics, "change_items_examined")
    return paths


def _coverage_key_candidates(path: str, symbol: str | None) -> tuple[str, ...]:
    keys = [path]
    if symbol:
        keys.extend((f"{path}::{symbol}", f"{path}#{symbol}", symbol))
    return tuple(dict.fromkeys(keys))


def _add_coverage_signal(
    accumulator: _CandidateAccumulator,
    coverage: CoverageEvidence,
    repository_map: RepositoryMap,
    metrics: dict[str, int],
) -> str:
    if not coverage.available:
        return coverage.status
    failing_total = max(1, len(coverage.failing_tests))
    passing_total = len(coverage.passing_tests)
    hit_keys = set(coverage.hit_counts) | set(coverage.files_executed) | set(coverage.symbols_executed)
    _metric(metrics, "coverage_symbols_hit", len(coverage.symbols_executed))
    for key in sorted(hit_keys):
        failing_hits, passing_hits = coverage_hit_counts(coverage, key)
        if not failing_hits and key in coverage.files_executed:
            failing_hits = failing_total
        suspiciousness = ochiai_suspiciousness(
            failing_hits, passing_hits, failing_total=failing_total, passing_total=passing_total,
        )
        if suspiciousness <= 0 and key not in coverage.files_executed and key not in coverage.symbols_executed:
            continue
        path = key
        symbol = None
        if "::" in key:
            path, symbol = key.split("::", 1)
        elif "#" in key:
            path, symbol = key.split("#", 1)
        elif key not in repository_map.files:
            matches = [row for row in repository_map.symbols.values() if str(row.get("qualified_name")) == key]
            if len(matches) == 1:
                path, symbol = str(matches[0].get("path")), key
        if path not in repository_map.files:
            continue
        value = min(7.0, max(0.5, suspiciousness * 6.0))
        if passing_hits > failing_hits and failing_hits == 0:
            value = -min(3.0, 1.0 + passing_hits / max(1, passing_total))
        accumulator.add(
            path=path, symbol=symbol, signal=COVERAGE_SIGNAL, value=value,
            reason="spectrum_coverage_correlation", evidence_id=f"coverage:{coverage.coverage_id}:{key}",
            signal_detail={"failing_hits": failing_hits, "passing_hits": passing_hits, "suspiciousness": suspiciousness},
        )
    return coverage.status


def _ledger_value(value: Any) -> tuple[ExperimentalEvidenceLedger | None, tuple[DiagnosticHypothesis, ...]]:
    if isinstance(value, DiagnosticResult):
        return value.evidence_ledger, tuple(value.hypotheses_after)
    if isinstance(value, ExperimentalEvidenceLedger):
        return value, ()
    data = _mapping(value)
    if not data:
        return None, ()
    hypotheses = tuple(DiagnosticHypothesis.from_value(item) for item in (data.get("hypotheses_after", data.get("hypotheses", ())) or ()))
    ledger_data = data.get("evidence_ledger", data)
    ledger_map = _mapping(ledger_data)
    entries: list[EvidenceItem] = []
    for raw in ledger_map.get("entries", ()) or ():
        row = _mapping(raw)
        effects = row.get("hypothesis_effects", {})
        if isinstance(effects, Mapping):
            effects_tuple = tuple(sorted((str(key), str(value)) for key, value in effects.items()))
        else:
            effects_tuple = tuple((str(item[0]), str(item[1])) for item in (effects or ()) if isinstance(item, (tuple, list)) and len(item) >= 2)
        try:
            entries.append(EvidenceItem(
                evidence_id=str(row.get("evidence_id", "evidence")),
                experiment_receipt_hash=str(row.get("experiment_receipt_hash", "")),
                hypothesis_effects=effects_tuple,
                strength=str(row.get("strength", "WEAK")),
                provenance=str(row.get("provenance", "CORE3")),
                validity=str(row.get("validity", "INVALID")),
                reason=str(row.get("reason", "")), metadata=dict(row.get("metadata", {}) or {}),
            ))
        except (TypeError, ValueError):
            continue
    if not entries and not ledger_map:
        return None, hypotheses
    return ExperimentalEvidenceLedger(str(ledger_map.get("session_id", "")), tuple(entries)), hypotheses


def _add_experimental_signal(
    accumulator: _CandidateAccumulator,
    evidence: Any,
    request: FaultLocalizationRequest,
    metrics: dict[str, int],
    *,
    hypotheses: Iterable[DiagnosticHypothesis] = (),
) -> tuple[str, str, tuple[DiagnosticHypothesis, ...]]:
    ledger, supplied_hypotheses = _ledger_value(evidence)
    if ledger is None:
        return "NOT_PROVIDED", "", tuple(hypotheses) or supplied_hypotheses
    if ledger.session_id and request.evidence_ledger_identity and ledger.session_id != request.evidence_ledger_identity:
        return STALE_FAULT_EVIDENCE, ledger.ledger_hash, tuple(hypotheses) or supplied_hypotheses
    chosen_hypotheses = tuple(hypotheses) or supplied_hypotheses
    by_id = {item.hypothesis_id: item for item in chosen_hypotheses}
    consumed = 0
    for item in ledger.entries[: request.budget.max_evidence_items]:
        if item.validity != EVIDENCE_VALID:
            continue
        if item.metadata.get("subject_identity") and request.subject_identity and item.metadata.get("subject_identity") != request.subject_identity:
            continue
        if item.metadata.get("revision_identity") and request.revision_identity and item.metadata.get("revision_identity") != request.revision_identity:
            continue
        masking = bool(item.metadata.get("masking_risks") or item.metadata.get("masking_risk")) or item.reason == "guard_regression"
        effects = dict(item.hypothesis_effects)
        for hypothesis_id, effect in effects.items():
            hypothesis = by_id.get(hypothesis_id)
            refs = hypothesis.target_references if hypothesis else ()
            metadata = item.metadata
            if not refs and metadata.get("path"):
                try:
                    refs = (TypedReference("symbol", metadata["path"], metadata.get("symbol")),) if metadata.get("symbol") else (TypedReference("file", metadata["path"]),)
                except ValueError:
                    refs = ()
            effective_effect = str(effect)
            if hypothesis is not None and hypothesis.status == ELIMINATED and effective_effect in {"", "INCONCLUSIVE", "NEUTRAL"}:
                effective_effect = ELIMINATED
            delta = _effect_delta(effective_effect, masking=masking)
            for ref in refs:
                path = _safe_path(ref.path)
                if not path:
                    continue
                accumulator.add(
                    path=path, symbol=ref.symbol, signal=EXPERIMENTAL_EVIDENCE_SIGNAL, value=delta,
                    reason="masking_experiment_neutralized" if masking else f"experimental_{effective_effect.casefold()}",
                    evidence_id=item.evidence_id,
                    signal_detail={"hypothesis_id": hypothesis_id, "effect": effective_effect, "masking_risk": masking},
                    staleness_state=CURRENT,
                )
        consumed += 1
    _metric(metrics, "experimental_evidence_items_consumed", consumed)
    status = "AVAILABLE" if consumed else "AVAILABLE_BUT_UNUSABLE"
    return status, ledger.ledger_hash, chosen_hypotheses


def _enabled(request: FaultLocalizationRequest, signal: str) -> bool:
    return signal in request.available_signal_types


def _failure_query_text(request: FaultLocalizationRequest) -> str:
    parts = [request.task_query_identity]
    for failure in request.failure_evidence:
        parts.extend((failure.message, failure.error_location, failure.test_name, failure.symbol, failure.path))
    return " ".join(str(item) for item in parts if str(item).strip())


def _working_set_paths(working_set: TaskWorkingSet | None) -> set[str]:
    return {str(item.path).replace("\\", "/") for item in (working_set.items if working_set else ()) if getattr(item, "path", "")}


def _seed_from_working_set(
    accumulator: _CandidateAccumulator,
    working_set: TaskWorkingSet | None,
) -> None:
    if working_set is None:
        return
    for item in working_set.items:
        if not item.path or item.role == "CONTRACTS":
            continue
        accumulator.add(
            path=item.path, symbol=item.symbol, candidate_kind="symbol" if item.symbol else "file",
            signal=LEXICAL_SIGNAL, value=0.5, reason="bounded_working_set_seed",
            evidence_id=f"working-set:{item.identity}", staleness_state=item.staleness_state,
            signal_detail={"role": item.role, "working_set_identity": working_set.canonical_hash},
        )


def _rank_for_known_root(candidates: Iterable[FaultCandidate], known: Any) -> int:
    if not known:
        return 0
    values = {str(item).replace("\\", "/") for item in (known if isinstance(known, (list, tuple, set)) else (known,))}
    for candidate in candidates:
        if candidate.candidate_id in values or candidate.path in values or (candidate.symbol and f"{candidate.path}::{candidate.symbol}" in values):
            return candidate.rank
    return 0


def _make_hypotheses(
    candidates: Iterable[FaultCandidate],
    *,
    request: FaultLocalizationRequest,
    max_hypotheses: int,
) -> tuple[DiagnosticHypothesis, ...]:
    ranked = tuple(candidates)
    chosen: list[FaultCandidate] = []
    paths: set[str] = set()
    # First pass favors distinct locations and candidate kinds, which avoids
    # six cosmetic variants of one symbol.
    for candidate in ranked:
        if len(chosen) >= max_hypotheses:
            break
        if candidate.path in paths and len(chosen) < min(3, max_hypotheses):
            continue
        chosen.append(candidate)
        paths.add(candidate.path)
    for candidate in ranked:
        if len(chosen) >= max_hypotheses:
            break
        if candidate not in chosen:
            chosen.append(candidate)
    result: list[DiagnosticHypothesis] = []
    for candidate in chosen:
        ref = candidate.reference
        if ref is None:
            continue
        hid = "H-" + canonical_hash({"request": request.request_id, "candidate": candidate.candidate_id})[:12]
        subject = ref.canonical_uri
        statement = (
            f"Failure may be causally associated with {subject} or its immediate boundary; "
            "this is a ranked diagnostic hypothesis, not a verified root cause."
        )
        result.append(DiagnosticHypothesis(
            hypothesis_id=hid, statement=statement, target_references=(ref,),
            suspect_symbols=(candidate.symbol,) if candidate.symbol else (),
            expected_failure_relationship="candidate_explains_observed_failure",
            source=DETERMINISTIC_SEED, initial_confidence_class="SUSPECT",
            current_evidence_score=int(round(candidate.score)),
            current_evidence_class=candidate.confidence_class,
        ))
    return tuple(result)


def _recommended_action(
    candidates: tuple[FaultCandidate, ...],
    *,
    working_set: TaskWorkingSet | None,
    expansions_used: int,
    budget: LocalizationBudget,
    signals_available: set[str],
    request: FaultLocalizationRequest,
) -> str:
    if not candidates or (candidates[0].score <= 1.0 and len(signals_available) <= 1):
        return EXPAND_WORKING_SET if expansions_used < budget.max_working_set_expansions else RUN_DIAGNOSTIC_EXPERIMENTS
    if (candidates[0].confidence_class in {HIGH, VERY_HIGH} or candidates[0].location_confidence == HIGH) and len(candidates) <= budget.max_candidates:
        return FOCUS_ON_TOP_SUSPECT
    if request.failure_type == TEST_FAILURE and COVERAGE_SIGNAL not in signals_available:
        return COLLECT_COVERAGE
    if request.failure_type in {RUNTIME_EXCEPTION, INTEGRATION_FAILURE} and STACK_TRACE_SIGNAL not in signals_available:
        return COLLECT_STACK_TRACE
    if len(candidates) > 1:
        return RUN_DIAGNOSTIC_EXPERIMENTS
    return INSUFFICIENT_LOCALIZATION_EVIDENCE


def _coerce_request(request: FaultLocalizationRequest | Mapping[str, Any] | str) -> FaultLocalizationRequest:
    if isinstance(request, FaultLocalizationRequest):
        return request
    if isinstance(request, str):
        failure = FaultFailureEvidence(
            failure_id="failure-1", failure_type=INTEGRATION_FAILURE, message=request,
        )
        return FaultLocalizationRequest(task_query_identity=request, failure_evidence=(failure,))
    return FaultLocalizationRequest.from_value(request)


def build_fault_localization_request(
    task_query_identity: str,
    failure_evidence: FaultFailureEvidence | Mapping[str, Any] | Iterable[Any],
    *,
    subject_identity: str = "",
    revision_identity: str = "",
    working_set_identity: str = "",
    available_signal_types: Iterable[str] = SIGNAL_TYPES,
    authority_context: Mapping[str, Any] | None = None,
    dnt_context: Iterable[str] = (),
    budget: LocalizationBudget | Mapping[str, Any] | None = None,
    evidence_ledger_identity: str = "",
    metadata: Mapping[str, Any] | None = None,
    request_id: str = "",
) -> FaultLocalizationRequest:
    if isinstance(failure_evidence, (FaultFailureEvidence, Mapping)):
        failures = (failure_evidence,)
    else:
        failures = tuple(failure_evidence)
    return FaultLocalizationRequest(
        request_id=request_id, task_query_identity=task_query_identity,
        subject_identity=subject_identity, revision_identity=revision_identity,
        failure_evidence=failures, working_set_identity=working_set_identity,
        available_signal_types=tuple(available_signal_types), authority_context=dict(authority_context or {}),
        dnt_context=tuple(dnt_context), budget=budget or LocalizationBudget(),
        evidence_ledger_identity=evidence_ledger_identity, metadata=dict(metadata or {}),
    )


def localize_fault(
    request: FaultLocalizationRequest | Mapping[str, Any] | str | None = None,
    repository_map: RepositoryMap | Mapping[str, Any] | None = None,
    project_root: str | Path | None = None,
    *,
    failure_evidence: FaultFailureEvidence | Mapping[str, Any] | Iterable[Any] | None = None,
    task_query_identity: str = "",
    working_set: TaskWorkingSet | None = None,
    lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
    brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
    coverage_provider: CoverageEvidenceProvider | Any | None = None,
    experimental_evidence: ExperimentalEvidenceLedger | DiagnosticResult | Mapping[str, Any] | None = None,
    hypotheses: Iterable[DiagnosticHypothesis] = (),
    change_evidence: Any = None,
    authority: Mapping[str, Any] | None = None,
    dnt_paths: Iterable[str] = (),
    budget: LocalizationBudget | Mapping[str, Any] | None = None,
    metrics: dict[str, int] | None = None,
) -> FaultLocalizationResult:
    """Localize a bounded suspect set from independent deterministic signals."""
    if request is None:
        if failure_evidence is None:
            raise ValueError("request or failure_evidence is required")
        request = build_fault_localization_request(task_query_identity, failure_evidence)
    if repository_map is None:
        raise ValueError("repository_map is required")
    current = repository_map if isinstance(repository_map, RepositoryMap) else RepositoryMap.from_dict(repository_map, project_root or "")
    root = Path(project_root or current.project_root or ".").expanduser().resolve()
    req = _coerce_request(request)
    if budget is not None:
        req = replace(req, budget=LocalizationBudget(**dict(budget)) if isinstance(budget, Mapping) else budget)
    if authority is not None and authority != req.authority_context:
        req = replace(req, authority_context=dict(authority))
    if dnt_paths:
        req = replace(req, dnt_context=tuple(dnt_paths))
    current_budget = req.budget
    counters = metrics if metrics is not None else new_core4_metrics()
    for key in CORE4_METRIC_KEYS:
        counters.setdefault(key, 0)
    _metric(counters, "localization_requests")
    accum = _CandidateAccumulator(current, req.authority_context, req.dnt_context)
    unresolved: list[dict[str, Any]] = []
    expansions: list[dict[str, Any]] = []
    signals_available: set[str] = set()
    signals_unavailable: set[str] = set()
    coverage_status_result = COVERAGE_NOT_AVAILABLE
    if working_set is None:
        query = RepoIntelligenceQuery.from_task(_failure_query_text(req), subject_identity=req.subject_identity, revision_identity=req.revision_identity)
        retrieved = search_repository(query, current, root, lexical_index=lexical_index, authority=req.authority_context)
        working_set = retrieved.working_set
        if retrieved.working_set is not None:
            req = replace(req, working_set_identity=req.working_set_identity or retrieved.working_set.canonical_hash)
    elif req.working_set_identity and req.working_set_identity != working_set.canonical_hash:
        unresolved.append({"kind": STALE_FAULT_EVIDENCE, "reason": "working_set_identity_mismatch"})
    _seed_from_working_set(accum, working_set)
    failures = tuple(req.failure_evidence)
    for failure in failures:
        if not _evidence_current(failure, req):
            unresolved.append({"failure_id": failure.failure_id, "kind": STALE_FAULT_EVIDENCE, "reason": "failure_subject_or_revision_mismatch"})
            continue
        evidence_id = f"failure:{failure.failure_id}"
        if _enabled(req, ERROR_LOCATION_SIGNAL) and (_failure_path_symbols(failure, current) or failure.error_location):
            if _add_error_location(accum, failure, current, evidence_id=evidence_id):
                signals_available.add(ERROR_LOCATION_SIGNAL)
        elif _enabled(req, ERROR_LOCATION_SIGNAL):
            signals_unavailable.add(ERROR_LOCATION_SIGNAL)
        if _enabled(req, STACK_TRACE_SIGNAL) and (failure.stack_trace or failure.metadata.get("stack_trace")):
            frames = _add_stack_signal(accum, failure, current, root, counters, max_frames=current_budget.max_stack_frames)
            if frames:
                signals_available.add(STACK_TRACE_SIGNAL)
        elif _enabled(req, STACK_TRACE_SIGNAL):
            signals_unavailable.add(STACK_TRACE_SIGNAL)
        if _enabled(req, FAILING_TEST_SIGNAL):
            tests = _add_test_signal(accum, failure, current, counters)
            if tests:
                signals_available.add(FAILING_TEST_SIGNAL)
                signals_available.add(TEST_DEPENDENCY_SIGNAL)
            else:
                signals_unavailable.add(FAILING_TEST_SIGNAL)
        if _enabled(req, LEXICAL_SIGNAL):
            _, _, lexical_count = _add_lexical_signal(accum, failure, current, root, lexical_index, counters, current_budget)
            if lexical_count:
                signals_available.add(LEXICAL_SIGNAL)
            else:
                signals_unavailable.add(LEXICAL_SIGNAL)
        if _enabled(req, COVERAGE_SIGNAL):
            check = failure.test_name or failure.error_location or failure.failure_id
            if coverage_provider is not None and counters.get("coverage_executions", 0) < current_budget.max_coverage_executions:
                coverage = collect_coverage_evidence(
                    coverage_provider, check, subject_identity=req.subject_identity,
                    revision_identity=req.revision_identity, max_tests=current_budget.max_coverage_tests,
                )
                _metric(counters, "coverage_executions")
                _metric(counters, "coverage_tests_run", min(current_budget.max_coverage_tests, len(coverage.failing_tests) + len(coverage.passing_tests)))
            else:
                coverage = CoverageEvidence(
                    coverage_id="coverage-budget-exhausted", subject_identity=req.subject_identity,
                    revision_identity=req.revision_identity, status=COVERAGE_NOT_AVAILABLE,
                )
            coverage_status = coverage.status
            if coverage.available and coverage.subject_identity and req.subject_identity and coverage.subject_identity != req.subject_identity:
                coverage_status = COVERAGE_STALE
            coverage_status_result = coverage_status
            if coverage_status == COVERAGE_AVAILABLE:
                _add_coverage_signal(accum, coverage, current, counters)
                signals_available.add(COVERAGE_SIGNAL)
            else:
                signals_unavailable.add(COVERAGE_SIGNAL)
        if _enabled(req, ORACLE_FAILURE if failure.failure_type == ORACLE_FAILURE else ERROR_LOCATION_SIGNAL) and failure.failure_type in {ORACLE_FAILURE, VERIFICATION_FAILURE}:
            if _add_error_location(accum, failure, current, evidence_id=f"oracle:{failure.failure_id}"):
                signals_available.add(ERROR_LOCATION_SIGNAL)
        if _enabled(req, GRAPH_PROXIMITY_SIGNAL) and accum.rows:
            _add_graph_signal(accum, current, (row["path"] for row in accum.rows.values()), counters, current_budget)
            if counters.get("graph_nodes_examined", 0):
                signals_available.add(GRAPH_PROXIMITY_SIGNAL)
        if _enabled(req, BRAIN_CONTRACT_SIGNAL) and brain_entities:
            before = counters.get("brain_contracts_consumed", 0)
            _add_brain_signal(accum, brain_entities, _failure_query_text(req), current, counters)
            if counters.get("brain_contracts_consumed", 0) > before:
                signals_available.add(BRAIN_CONTRACT_SIGNAL)
        if _enabled(req, CHANGE_PROXIMITY_SIGNAL):
            before = counters.get("change_items_examined", 0)
            _add_change_signal(accum, current, req, change_evidence, counters)
            if counters.get("change_items_examined", 0) > before:
                signals_available.add(CHANGE_PROXIMITY_SIGNAL)
    if _enabled(req, EXPERIMENTAL_EVIDENCE_SIGNAL) and experimental_evidence is not None:
        status, ledger_hash, chosen = _add_experimental_signal(accum, experimental_evidence, req, counters, hypotheses=hypotheses)
        experimental_status = status
        if ledger_hash:
            req = replace(req, evidence_ledger_identity=req.evidence_ledger_identity or ledger_hash)
        if counters.get("experimental_evidence_items_consumed", 0):
            signals_available.add(EXPERIMENTAL_EVIDENCE_SIGNAL)
        else:
            signals_unavailable.add(EXPERIMENTAL_EVIDENCE_SIGNAL)
    else:
        experimental_status = "NOT_PROVIDED"
        if _enabled(req, EXPERIMENTAL_EVIDENCE_SIGNAL):
            signals_unavailable.add(EXPERIMENTAL_EVIDENCE_SIGNAL)
        chosen = tuple(hypotheses)

    signals_unavailable.update(signal for signal in SIGNAL_TYPES if signal not in signals_available and signal not in signals_unavailable)

    # Evidence outside the current bounded working set can justify at most a
    # small CORE-2 expansion.  It never widens authority.
    evidence_paths = {path for failure in failures for path, _, _ in _failure_path_symbols(failure, current)}
    outside = sorted(evidence_paths - _working_set_paths(working_set))
    if outside and len(expansions) < current_budget.max_working_set_expansions:
        expanded_query = RepoIntelligenceQuery.from_task(
            _failure_query_text(req) + " " + " ".join(outside),
            subject_identity=req.subject_identity, revision_identity=req.revision_identity,
        )
        expanded = search_repository(expanded_query, current, root, lexical_index=lexical_index, authority=req.authority_context)
        if expanded.working_set is not None:
            working_set = expanded.working_set
            event = {"reason": "failure evidence pointed outside current TaskWorkingSet", "paths": outside, "working_set_hash": working_set.canonical_hash}
            expansions.append(event)
            _metric(counters, "working_set_expansions")

    # Do not expose an unlimited file fallback alongside symbol-level suspects.
    candidates = accum.freeze(top_limit=current_budget.max_candidates)
    symbol_rows = [item for item in candidates if item.symbol]
    file_rows = [item for item in candidates if not item.symbol]
    if symbol_rows:
        allowed_files = set(item.candidate_id for item in symbol_rows)
        allowed_files.update(item.candidate_id for item in file_rows[: current_budget.max_file_fallback_candidates])
        candidates = tuple(item for item in candidates if item.candidate_id in allowed_files)
        candidates = tuple(replace(item, rank=index) for index, item in enumerate(candidates, 1))
    top = candidates[: current_budget.top_candidates]
    _metric(counters, "candidates_considered", accum.raw_count)
    _metric(counters, "candidates_ranked", len(candidates))
    _metric(counters, "candidates_deduped", len(accum.rows))
    _metric(counters, "symbol_candidates", sum(bool(item.symbol) for item in candidates))
    _metric(counters, "file_fallback_candidates", sum(not item.symbol for item in candidates))
    _metric(counters, "signals_available", len(signals_available))
    _metric(counters, "signals_unavailable", len(signals_unavailable))
    known = req.metadata.get("known_root", req.metadata.get("known_root_candidate", ""))
    before_rank = _rank_for_known_root(candidates, known)
    counters["known_root_rank_before_experiments"] = before_rank
    if before_rank:
        _metric(counters, "top1_hit" if before_rank == 1 else "top3_hit" if before_rank <= 3 else "top5_hit" if before_rank <= 5 else "top1_hit", 1)
    hypotheses_out = _make_hypotheses(top, request=req, max_hypotheses=current_budget.max_hypotheses)
    explanations = tuple({
        "candidate_id": item.candidate_id, "rank": item.rank, "score": item.score,
        "confidence_class": item.confidence_class, "signal_contributions": dict(item.signal_contributions),
        "evidence_sources": list(item.evidence_sources), "reasons": list(item.reasons),
        "supporting_evidence_ids": list(item.supporting_evidence_ids),
        "contradicting_evidence_ids": list(item.contradicting_evidence_ids),
    } for item in top)
    action = _recommended_action(
        candidates, working_set=working_set, expansions_used=len(expansions), budget=current_budget,
        signals_available=signals_available, request=req,
    )
    usage = {
        "candidates_considered": accum.raw_count, "candidates_ranked": len(candidates),
        "graph_nodes": counters.get("graph_nodes_examined", 0),
        "coverage_tests": counters.get("coverage_tests_run", 0),
        "coverage_executions": counters.get("coverage_executions", 0),
        "working_set_expansions": len(expansions),
        "source_bodies_loaded": counters.get("source_bodies_loaded", 0),
        "max_candidates": current_budget.max_candidates, "max_graph_nodes": current_budget.max_graph_nodes,
        "max_coverage_tests": current_budget.max_coverage_tests,
        "max_working_set_expansions": current_budget.max_working_set_expansions,
    }
    return FaultLocalizationResult(
        request=req, failure_type=req.failure_type,
        signals_available=tuple(sorted(signals_available)), signals_unavailable=tuple(sorted(signals_unavailable)),
        candidates=candidates, top_suspects=tuple(item.candidate_id for item in top),
        ranking_explanations=explanations, working_set=working_set,
        working_set_expansions=tuple(expansions), budget_usage=usage,
        coverage_status=coverage_status_result, experimental_evidence_status=experimental_status,
        unresolved_evidence=tuple(unresolved), recommended_next_action=action,
        metrics=dict(counters), hypotheses=hypotheses_out,
        known_root_rank_before_experiments=before_rank,
        canonical_subject_identity=req.subject_identity,
    )


def _effect_delta(effect: str, *, masking: bool) -> float:
    if masking:
        return 0.0
    return {
        "SUPPORTS": 3.0,
        "WEAKENS": -2.0,
        "STRONGLY_WEAKENS": -4.0,
        # CORE-3 normally represents this as hypothesis status, but accepting
        # it as a serialized effect keeps the conservative mapping intact.
        "ELIMINATED": -4.0,
    }.get(str(effect), 0.0)


def _experimental_candidate_deltas(
    result: FaultLocalizationResult,
    evidence: ExperimentalEvidenceLedger | DiagnosticResult | Mapping[str, Any],
    hypotheses: Iterable[DiagnosticHypothesis],
) -> tuple[dict[str, float], dict[str, list[dict[str, Any]]], int, str, tuple[DiagnosticHypothesis, ...]]:
    ledger, supplied = _ledger_value(evidence)
    chosen = tuple(hypotheses) or supplied or result.hypotheses
    if ledger is None:
        return {}, {}, 0, "NOT_PROVIDED", chosen
    if ledger.session_id and result.request.evidence_ledger_identity and ledger.session_id != result.request.evidence_ledger_identity:
        return {}, {}, 0, STALE_FAULT_EVIDENCE, chosen
    by_hypothesis = {item.hypothesis_id: item for item in chosen}
    deltas: dict[str, float] = defaultdict(float)
    details: dict[str, list[dict[str, Any]]] = defaultdict(list)
    consumed = 0
    for item in ledger.entries[: result.request.budget.max_evidence_items]:
        if item.validity != EVIDENCE_VALID:
            continue
        if item.metadata.get("subject_identity") and result.request.subject_identity and item.metadata.get("subject_identity") != result.request.subject_identity:
            continue
        if item.metadata.get("revision_identity") and result.request.revision_identity and item.metadata.get("revision_identity") != result.request.revision_identity:
            continue
        masking = bool(item.metadata.get("masking_risks") or item.metadata.get("masking_risk")) or item.reason == "guard_regression"
        for hid, effect in dict(item.hypothesis_effects).items():
            hypothesis = by_hypothesis.get(hid)
            references = hypothesis.target_references if hypothesis else ()
            metadata = item.metadata
            if not references and metadata.get("candidate_id"):
                matching = [candidate for candidate in result.candidates if candidate.candidate_id == str(metadata["candidate_id"])]
            else:
                matching = [
                    candidate for candidate in result.candidates
                    if any(candidate.path == ref.path and (not ref.symbol or candidate.symbol == ref.symbol) for ref in references)
                ]
            effective_effect = str(effect)
            if hypothesis is not None and hypothesis.status == ELIMINATED and effective_effect in {"", "INCONCLUSIVE", "NEUTRAL"}:
                effective_effect = ELIMINATED
            delta = _effect_delta(effective_effect, masking=masking)
            for candidate in matching:
                deltas[candidate.candidate_id] += delta
                details[candidate.candidate_id].append({
                    "evidence_id": item.evidence_id, "hypothesis_id": hid,
                    "effect": effective_effect, "delta": delta, "masking_risk": masking,
                })
        consumed += 1
    status = "AVAILABLE" if consumed else "AVAILABLE_BUT_UNUSABLE"
    return dict(deltas), dict(details), consumed, status, chosen


def rerank_with_experimental_evidence(
    result: FaultLocalizationResult,
    evidence: ExperimentalEvidenceLedger | DiagnosticResult | Mapping[str, Any],
    *,
    hypotheses: Iterable[DiagnosticHypothesis] = (),
) -> FaultLocalizationResult:
    """Apply new valid CORE-3 evidence without rebuilding repository indexes."""
    deltas, details, consumed, status, chosen = _experimental_candidate_deltas(result, evidence, hypotheses)
    if not deltas and status == "NOT_PROVIDED":
        return result
    updated: list[FaultCandidate] = []
    for candidate in result.candidates:
        delta = float(deltas.get(candidate.candidate_id, 0.0))
        if not delta:
            updated.append(candidate)
            continue
        contributions = dict(candidate.signal_contributions)
        before = float(contributions.get(EXPERIMENTAL_EVIDENCE_SIGNAL, 0.0))
        after = max(-6.0, min(6.0, before + delta))
        contributions[EXPERIMENTAL_EVIDENCE_SIGNAL] = round(after, 6)
        support = {key for key, value in contributions.items() if key != "MULTI_SIGNAL_BONUS" and value > 0}
        contributions["MULTI_SIGNAL_BONUS"] = round(min(6.0, max(0.0, 2.0 * (len(support) - 1))), 6) if len(support) > 1 else 0.0
        score = round(sum(contributions.values()), 6)
        sources = tuple(sorted(set(candidate.evidence_sources) | {EXPERIMENTAL_EVIDENCE_SIGNAL}))
        contradicting = set(candidate.contradicting_evidence_ids)
        supporting = set(candidate.supporting_evidence_ids)
        for row in details.get(candidate.candidate_id, ()):
            if row["delta"] < 0:
                contradicting.add(str(row["evidence_id"]))
            elif row["delta"] > 0:
                supporting.add(str(row["evidence_id"]))
        strong_contradiction = any(value <= -3 for key, value in contributions.items() if key != "MULTI_SIGNAL_BONUS")
        confidence = VERY_HIGH if len(support) >= 4 and not strong_contradiction else HIGH if len(support) >= 3 and not strong_contradiction else MEDIUM if len(support) >= 2 else LOW
        if candidate.staleness_state != CURRENT and confidence == VERY_HIGH:
            confidence = HIGH
        updated.append(replace(
            candidate, signal_contributions=contributions, aggregate_suspiciousness_score=score,
            confidence_class=confidence, evidence_sources=sources,
            supporting_evidence_ids=tuple(sorted(supporting)), contradicting_evidence_ids=tuple(sorted(contradicting)),
            reasons=tuple(sorted(set(candidate.reasons) | {"experimental_evidence_rerank"})),
            signal_details={**candidate.signal_details, EXPERIMENTAL_EVIDENCE_SIGNAL: tuple(
                list(candidate.signal_details.get(EXPERIMENTAL_EVIDENCE_SIGNAL, ())) + details.get(candidate.candidate_id, ())
            )},
            causal_suspicion="HIGH" if len(support) >= 3 and not strong_contradiction else candidate.causal_suspicion,
        ))
    updated.sort(key=lambda item: (-item.score, item.candidate_id))
    ranked = tuple(replace(item, rank=index) for index, item in enumerate(updated, 1))
    top = ranked[: result.request.budget.top_candidates]
    metrics = dict(result.metrics)
    _metric(metrics, "experimental_evidence_items_consumed", consumed)
    metrics["candidates_ranked"] = len(ranked)
    known = result.request.metadata.get("known_root", result.request.metadata.get("known_root_candidate", ""))
    after_rank = _rank_for_known_root(ranked, known)
    metrics["known_root_rank_after_experiments"] = after_rank
    request = result.request
    ledger, _ = _ledger_value(evidence)
    if ledger is not None and not request.evidence_ledger_identity:
        request = replace(request, evidence_ledger_identity=ledger.ledger_hash)
    hypotheses_out = _make_hypotheses(top, request=request, max_hypotheses=request.budget.max_hypotheses)
    explanations = tuple({
        "candidate_id": item.candidate_id, "rank": item.rank, "score": item.score,
        "confidence_class": item.confidence_class, "signal_contributions": dict(item.signal_contributions),
        "evidence_sources": list(item.evidence_sources), "reasons": list(item.reasons),
        "supporting_evidence_ids": list(item.supporting_evidence_ids),
        "contradicting_evidence_ids": list(item.contradicting_evidence_ids),
    } for item in top)
    return replace(
        result, request=request, candidates=ranked, top_suspects=tuple(item.candidate_id for item in top),
        ranking_explanations=explanations, experimental_evidence_status=status,
        metrics=metrics, hypotheses=hypotheses_out, known_root_rank_after_experiments=after_rank,
    )


def seed_hypotheses_from_localization(
    result: FaultLocalizationResult,
    *,
    max_hypotheses: int | None = None,
) -> tuple[DiagnosticHypothesis, ...]:
    """Create bounded, diverse CORE-3 hypotheses from ranked suspects."""
    limit = max_hypotheses if max_hypotheses is not None else result.request.budget.max_hypotheses
    return _make_hypotheses(result.candidates[: result.request.budget.top_candidates], request=result.request, max_hypotheses=max(1, int(limit)))


class FaultLocalizationEngine:
    """Reusable provider-free façade for localization and one explicit rerank."""

    def __init__(
        self,
        repository_map: RepositoryMap | Mapping[str, Any],
        project_root: str | Path | None = None,
        *,
        lexical_index: LexicalIndex | Mapping[str, Any] | None = None,
        brain_entities: Iterable[ProjectBrainEntity | Mapping[str, Any]] = (),
        authority: Mapping[str, Any] | None = None,
        dnt_paths: Iterable[str] = (),
        coverage_provider: CoverageEvidenceProvider | Any | None = None,
        budget: LocalizationBudget | Mapping[str, Any] | None = None,
    ) -> None:
        self.repository_map = repository_map
        self.project_root = project_root
        self.lexical_index = lexical_index
        self.brain_entities = tuple(brain_entities)
        self.authority = dict(authority or {})
        self.dnt_paths = tuple(dnt_paths)
        self.coverage_provider = coverage_provider
        self.budget = budget or LocalizationBudget()

    def localize(self, request: FaultLocalizationRequest | Mapping[str, Any] | str, *, working_set: TaskWorkingSet | None = None, experimental_evidence: Any = None, hypotheses: Iterable[DiagnosticHypothesis] = (), change_evidence: Any = None) -> FaultLocalizationResult:
        return localize_fault(
            request, self.repository_map, self.project_root, working_set=working_set,
            lexical_index=self.lexical_index, brain_entities=self.brain_entities,
            coverage_provider=self.coverage_provider, experimental_evidence=experimental_evidence,
            hypotheses=hypotheses, change_evidence=change_evidence, authority=self.authority,
            dnt_paths=self.dnt_paths, budget=self.budget,
        )

    def rerank(self, result: FaultLocalizationResult, evidence: Any, *, hypotheses: Iterable[DiagnosticHypothesis] = ()) -> FaultLocalizationResult:
        return rerank_with_experimental_evidence(result, evidence, hypotheses=hypotheses)


def _benchmark_rank(candidates: Iterable[FaultCandidate], expected: set[str]) -> int:
    for candidate in candidates:
        if candidate.candidate_id in expected or candidate.path in expected or (candidate.symbol and f"{candidate.path}::{candidate.symbol}" in expected):
            return candidate.rank
    return 0


def benchmark_fault_localization_scenarios(
    scenarios: Iterable[Mapping[str, Any]],
    *,
    repository_map: RepositoryMap | Mapping[str, Any] | None = None,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    """Report small-fixture navigation metrics, never production accuracy."""
    rows: list[dict[str, Any]] = []
    reciprocal: list[float] = []
    top1 = top3 = top5 = 0
    root_rank_deltas: list[int] = []
    incorrect_elimination = 0
    for scenario in scenarios:
        current_map = scenario.get("repository_map", repository_map)
        root = scenario.get("project_root", project_root)
        request = scenario.get("request", scenario.get("failure_evidence", scenario.get("query", "")))
        result = localize_fault(
            request, current_map, root, working_set=scenario.get("working_set"),
            lexical_index=scenario.get("lexical_index"), brain_entities=scenario.get("brain_entities", ()),
            coverage_provider=scenario.get("coverage_provider"),
            hypotheses=scenario.get("hypotheses", ()), change_evidence=scenario.get("change_evidence"),
            authority=scenario.get("authority"), dnt_paths=scenario.get("dnt_paths", ()),
        )
        expected = {str(item).replace("\\", "/") for item in scenario.get("relevant", scenario.get("relevant_candidates", scenario.get("relevant_files", ())))}
        rank = _benchmark_rank(result.candidates, expected)
        after = result
        if scenario.get("experimental_evidence") is not None:
            after = rerank_with_experimental_evidence(
                result, scenario["experimental_evidence"], hypotheses=scenario.get("hypotheses", ()),
            )
        after_rank = _benchmark_rank(after.candidates, expected)
        if scenario.get("experimental_evidence") is not None:
            root_rank_deltas.append(rank - after_rank if rank and after_rank else 0)
            if after_rank == 0 and rank:
                incorrect_elimination += 1
        top1 += rank == 1
        top3 += 1 if rank and rank <= 3 else 0
        top5 += 1 if rank and rank <= 5 else 0
        reciprocal.append(1.0 / rank if rank else 0.0)
        rows.append({
            "name": str(scenario.get("name", "scenario")), "rank": rank,
            "top1": rank == 1, "top3": bool(rank and rank <= 3), "top5": bool(rank and rank <= 5),
            "candidate_count": len(result.candidates),
            "working_set_size": len(result.working_set.items) if result.working_set else 0,
            "source_bodies_loaded": result.metrics.get("source_bodies_loaded", 0),
            "graph_nodes": result.metrics.get("graph_nodes_examined", 0),
            "coverage_tests": result.metrics.get("coverage_tests_run", 0),
            "recommended_next_action": result.recommended_next_action,
            "top_suspects": list(result.top_suspects),
            "rank_after_experiments": after_rank,
        })
    count = max(1, len(rows))
    return {
        "benchmark_kind": "DETERMINISTIC_CORE4_FAULT_LOCALIZATION",
        "scenario_count": len(rows), "Top-1": top1 / count, "Top-3": top3 / count, "Top-5": top5 / count,
        "MRR": sum(reciprocal) / count, "mean_candidate_set_size": sum(row["candidate_count"] for row in rows) / count,
        "mean_working_set_size": sum(row["working_set_size"] for row in rows) / count,
        "mean_source_body_loads": sum(row["source_bodies_loaded"] for row in rows) / count,
        "mean_graph_nodes": sum(row["graph_nodes"] for row in rows) / count,
        "mean_coverage_tests": sum(row["coverage_tests"] for row in rows) / count,
        "root_cause_rank_delta_after_experiments": sum(root_rank_deltas) / max(1, len(root_rank_deltas)),
        "incorrect_elimination_count": incorrect_elimination,
        "scenarios": rows, "provider_calls": 0,
    }


benchmark_fault_localization = benchmark_fault_localization_scenarios
CoverageProvider = CoverageEvidenceProvider


__all__ = [
    "CORE4_SCHEMA_VERSION", "CORE4_METRIC_KEYS", "new_core4_metrics",
    "TEST_FAILURE", "ASSERTION_FAILURE", "RUNTIME_EXCEPTION", "SYNTAX_FAILURE",
    "VERIFICATION_FAILURE", "ORACLE_FAILURE", "WORKER_EXECUTION_FAILURE", "INTEGRATION_FAILURE", "FAILURE_TYPES",
    "ERROR_LOCATION_SIGNAL", "STACK_TRACE_SIGNAL", "FAILING_TEST_SIGNAL", "TEST_DEPENDENCY_SIGNAL",
    "COVERAGE_SIGNAL", "GRAPH_PROXIMITY_SIGNAL", "CHANGE_PROXIMITY_SIGNAL", "LEXICAL_SIGNAL",
    "BRAIN_CONTRACT_SIGNAL", "EXPERIMENTAL_EVIDENCE_SIGNAL", "SIGNAL_TYPES",
    "LOW", "MEDIUM", "HIGH", "VERY_HIGH", "DNT_PROTECTED", "STALE_FAULT_EVIDENCE",
    "FOCUS_ON_TOP_SUSPECT", "RUN_DIAGNOSTIC_EXPERIMENTS", "EXPAND_WORKING_SET", "COLLECT_COVERAGE",
    "COLLECT_STACK_TRACE", "INVESTIGATE_FLAKINESS", "INSUFFICIENT_LOCALIZATION_EVIDENCE",
    "FaultFailureEvidence", "FailureEvidence", "LocalizationBudget", "FaultLocalizationBudget",
    "FaultLocalizationRequest", "StackFrame", "StackTraceParser", "parse_stack_trace", "parse_stack_frames",
    "FaultCandidate", "FaultLocalizationResult", "CoverageEvidence", "CoverageEvidenceProvider",
    "CoverageProvider", "collect_coverage_evidence", "ochiai_suspiciousness", "coverage_hit_counts",
    "build_fault_localization_request", "localize_fault", "seed_hypotheses_from_localization",
    "rerank_with_experimental_evidence", "FaultLocalizationEngine",
    "benchmark_fault_localization_scenarios", "benchmark_fault_localization",
]

FailureEvidence = FaultFailureEvidence
