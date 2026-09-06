"""Immutable patch representations and bounded deterministic candidate generation.

The objects in this module are proposals for sandbox evaluation.  They are
not writes, approvals, verification receipts, or Brain updates.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol

from .experiment_sandbox import validate_source_syntax
from .project_brain_refs import TypedReference, canonical_hash
from .mutation_strategy import (
    CONDITION_CHANGE, EXACT_VALUE_CHANGE, EXPORT_IMPORT_REPAIR,
    FUNCTION_LOCAL_REWRITE, MULTI_FILE_BOUNDED_CHANGE,
    MULTI_LOCATION_SINGLE_FILE_CHANGE, SMALL_DELETION, SMALL_INSERTION,
)

DNT_PROTECTED = "DNT_PROTECTED"


DETERMINISTIC_OPERATOR = "DETERMINISTIC_OPERATOR"
REPAIR_TEMPLATE = "REPAIR_TEMPLATE"
EXPERIMENT_DERIVED = "EXPERIMENT_DERIVED"
MODEL_PROPOSED = "MODEL_PROPOSED"
USER_PROPOSED = "USER_PROPOSED"
PROVENANCE_VALUES = (DETERMINISTIC_OPERATOR, REPAIR_TEMPLATE, EXPERIMENT_DERIVED, MODEL_PROPOSED, USER_PROPOSED)

PROPOSED = "PROPOSED"
STALE_BASE = "STALE_BASE"
STALE_PATCH_BASE = STALE_BASE
AUTHORITY_BLOCKED = "AUTHORITY_BLOCKED"
SYNTAX_INVALID = "SYNTAX_INVALID"
TARGET_FAILED = "TARGET_FAILED"
GUARD_REGRESSION = "GUARD_REGRESSION"
REGRESSION_RISK = GUARD_REGRESSION
CONTRACT_CONFLICT = "CONTRACT_CONFLICT"
V25_5_REJECTED = "V25_5_REJECTED"
V25_6_FAILED = "V25_6_FAILED"
SYNTAX_INVALID_CANDIDATE = SYNTAX_INVALID
VIABLE = "VIABLE"
VERIFIED = "VERIFIED"
STATUS_VALUES = (PROPOSED, STALE_BASE, AUTHORITY_BLOCKED, SYNTAX_INVALID, TARGET_FAILED, GUARD_REGRESSION, CONTRACT_CONFLICT, V25_5_REJECTED, V25_6_FAILED, VIABLE, VERIFIED)

EXACT_REPLACEMENT = "EXACT_REPLACEMENT"
INSERTION = "INSERTION"
DELETION = "DELETION"
FUNCTION_REPLACEMENT = "FUNCTION_REPLACEMENT"
MULTI_OPERATION = "MULTI_OPERATION"

_FORBIDDEN = frozenset({".git", ".agent_runs", ".agent_evidence", ".hivo", "output", "node_modules", "__pycache__"})


def _safe_path(path: Any) -> str:
    value = str(path or "").replace("\\", "/").strip()
    if not value or value.startswith("/") or re.match(r"^[A-Za-z]:/", value):
        raise ValueError("patch path must be relative")
    parts = tuple(item for item in value.split("/") if item)
    if ".." in parts or any(item in _FORBIDDEN for item in parts):
        raise ValueError("patch path escapes or targets a protected area")
    return "/".join(parts)


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _map(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return dict(data) if isinstance(data, Mapping) else {}
        except Exception:
            return {}
    return {}


@dataclass(frozen=True)
class PatchOperation:
    path: str
    operation: str = EXACT_REPLACEMENT
    expected_text: str = ""
    replacement: str = ""
    expected_file_hash: str = ""
    symbol: str = ""
    anchor_hash: str = ""
    line_start: int | None = None
    line_end: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", _safe_path(self.path))
        object.__setattr__(self, "operation", str(self.operation or EXACT_REPLACEMENT))
        object.__setattr__(self, "expected_text", str(self.expected_text or ""))
        object.__setattr__(self, "replacement", str(self.replacement or ""))
        object.__setattr__(self, "expected_file_hash", str(self.expected_file_hash or "").lower())
        object.__setattr__(self, "anchor_hash", str(self.anchor_hash or "").lower())
        object.__setattr__(self, "symbol", str(self.symbol or ""))
        if self.line_start is not None:
            object.__setattr__(self, "line_start", max(1, int(self.line_start)))
        if self.line_end is not None:
            object.__setattr__(self, "line_end", max(1, int(self.line_end)))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "path": self.path, "operation": self.operation,
            "expected_text": self.expected_text, "replacement": self.replacement,
            "expected_file_hash": self.expected_file_hash, "symbol": self.symbol,
            "anchor_hash": self.anchor_hash, "line_start": self.line_start, "line_end": self.line_end,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "PatchOperation":
        if isinstance(value, cls):
            return value
        data = _map(value)
        return cls(
            path=data.get("path", data.get("target_path", "")),
            operation=data.get("operation", data.get("kind", EXACT_REPLACEMENT)),
            expected_text=data.get("expected_text", data.get("expected_anchor", data.get("old", ""))),
            replacement=data.get("replacement", data.get("new", data.get("temporary_replacement", ""))),
            expected_file_hash=data.get("expected_file_hash", data.get("base_file_hash", data.get("current_hash", ""))),
            symbol=data.get("symbol", ""), anchor_hash=data.get("anchor_hash", ""),
            line_start=data.get("line_start"), line_end=data.get("line_end"),
        )

    def apply(self, text: str) -> tuple[str, str]:
        operation = self.operation.upper()
        if self.anchor_hash and self.expected_text and _text_hash(self.expected_text) != self.anchor_hash:
            return text, "anchor hash does not match the expected source anchor"
        if self.expected_text:
            count = text.count(self.expected_text)
            if count != 1:
                return text, f"expected exact anchor count 1, found {count}"
        if operation in {EXACT_REPLACEMENT, "REPLACE", FUNCTION_REPLACEMENT}:
            if not self.expected_text:
                return text, "exact replacement requires an anchor"
            return text.replace(self.expected_text, self.replacement, 1), ""
        if operation in {INSERTION, "INSERT"}:
            if self.expected_text:
                return text.replace(self.expected_text, self.expected_text + self.replacement, 1), ""
            return text + self.replacement, ""
        if operation in {DELETION, "DELETE"}:
            if not self.expected_text:
                return text, "deletion requires an anchor"
            return text.replace(self.expected_text, "", 1), ""
        return text, f"unsupported patch operation: {self.operation}"


@dataclass(frozen=True)
class PatchRepresentation:
    operations: tuple[PatchOperation, ...]
    representation_kind: str = MULTI_OPERATION

    def __post_init__(self) -> None:
        ops = tuple(item if isinstance(item, PatchOperation) else PatchOperation.from_value(item) for item in self.operations)
        object.__setattr__(self, "operations", ops)
        object.__setattr__(self, "representation_kind", str(self.representation_kind or MULTI_OPERATION))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return tuple(sorted({item.path for item in self.operations}))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"representation_kind": self.representation_kind, "operations": [item.to_dict(include_hash=False) for item in self.operations]}
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "PatchRepresentation":
        if isinstance(value, cls):
            return value
        data = _map(value)
        raw = data.get("operations", ())
        if isinstance(raw, Mapping):
            raw = (raw,)
        return cls(tuple(PatchOperation.from_value(item) for item in (raw or ())), str(data.get("representation_kind", MULTI_OPERATION)))


@dataclass(frozen=True)
class PatchCandidate:
    candidate_id: str
    target_path: str
    target_symbol: str = ""
    strategy: str = "UNKNOWN_STRUCTURAL_CHANGE"
    provenance: str = DETERMINISTIC_OPERATOR
    representation: PatchRepresentation = field(default_factory=lambda: PatchRepresentation(()))
    base_subject_hash: str = ""
    base_revision_identity: str = ""
    target_authority: str = "READ_ONLY_SUPPORT"
    hypothesis_ids: tuple[str, ...] = ()
    evidence_sources: tuple[str, ...] = ()
    generator_id: str = ""
    status: str = PROPOSED
    score: float = 0.0
    complexity: int = 0
    reasons: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)
    # Compatibility/detail fields make the canonical model explicit without
    # changing the compact constructor used by existing callers.
    repair_id: str = ""
    generator: str = ""
    target_paths: tuple[str, ...] = ()
    target_symbols: tuple[str, ...] = ()
    changed_ranges: tuple[dict[str, Any], ...] = ()
    candidate_source_hash: str = ""
    score_contributions: dict[str, float] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "target_path", _safe_path(self.target_path))
        object.__setattr__(self, "target_symbol", str(self.target_symbol or ""))
        object.__setattr__(self, "provenance", self.provenance if self.provenance in PROVENANCE_VALUES else DETERMINISTIC_OPERATOR)
        object.__setattr__(self, "representation", self.representation if isinstance(self.representation, PatchRepresentation) else PatchRepresentation.from_value(self.representation))
        object.__setattr__(self, "hypothesis_ids", tuple(sorted({str(item) for item in self.hypothesis_ids})))
        object.__setattr__(self, "evidence_sources", tuple(sorted({str(item) for item in self.evidence_sources})))
        object.__setattr__(self, "status", self.status if self.status in STATUS_VALUES else PROPOSED)
        object.__setattr__(self, "complexity", max(0, int(self.complexity or len(self.representation.operations))))
        object.__setattr__(self, "score", round(float(self.score or 0.0), 6))
        object.__setattr__(self, "reasons", tuple(sorted({str(item) for item in self.reasons})))
        object.__setattr__(self, "metadata", dict(self.metadata or {}))
        object.__setattr__(self, "repair_id", str(self.repair_id or ""))
        object.__setattr__(self, "generator", str(self.generator or self.generator_id or self.provenance))
        paths = tuple(sorted({str(item).replace("\\", "/") for item in (self.target_paths or self.representation.changed_paths)}))
        object.__setattr__(self, "target_paths", paths or (self.target_path,))
        raw_symbols = self.target_symbols or ((self.target_symbol,) if self.target_symbol else ())
        object.__setattr__(self, "target_symbols", tuple(sorted({str(item) for item in raw_symbols})))
        object.__setattr__(self, "changed_ranges", tuple(dict(item) for item in (self.changed_ranges or ())))
        object.__setattr__(self, "candidate_source_hash", str(self.candidate_source_hash or self.base_subject_hash))
        object.__setattr__(self, "score_contributions", {
            str(key): round(float(value), 6) for key, value in sorted(dict(self.score_contributions or {}).items())
        })

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def logical_hash(self) -> str:
        return canonical_hash({"base_subject_hash": self.base_subject_hash, "representation": self.representation.to_dict(include_hash=False)})

    @property
    def changed_paths(self) -> tuple[str, ...]:
        return self.representation.changed_paths

    def with_status(self, status: str, *, score: float | None = None, reasons: Iterable[str] = ()) -> "PatchCandidate":
        data = self.to_dict(include_hash=False)
        data["status"] = status
        if score is not None:
            data["score"] = score
        data["reasons"] = list(self.reasons) + list(reasons)
        return PatchCandidate.from_value(data)

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "candidate_id": self.candidate_id, "target_path": self.target_path,
            "target_symbol": self.target_symbol, "strategy": self.strategy,
            "provenance": self.provenance, "representation": self.representation.to_dict(include_hash=False),
            "base_subject_hash": self.base_subject_hash, "base_revision_identity": self.base_revision_identity,
            "target_authority": self.target_authority, "hypothesis_ids": list(self.hypothesis_ids),
            "evidence_sources": list(self.evidence_sources), "generator_id": self.generator_id,
            "status": self.status, "score": self.score, "complexity": self.complexity,
            "reasons": list(self.reasons), "metadata": dict(self.metadata),
            "repair_id": self.repair_id, "generator": self.generator,
            "target_paths": list(self.target_paths), "target_symbols": list(self.target_symbols),
            "changed_ranges": list(self.changed_ranges), "candidate_source_hash": self.candidate_source_hash,
            "score_contributions": dict(self.score_contributions),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value

    @classmethod
    def from_value(cls, value: Any) -> "PatchCandidate":
        if isinstance(value, cls):
            return value
        data = _map(value)
        representation = data.get("representation", data.get("patch", {}))
        return cls(
            candidate_id=str(data.get("candidate_id", data.get("id", "candidate"))),
            target_path=data.get("target_path", data.get("path", "")),
            target_symbol=str(data.get("target_symbol", data.get("symbol", ""))),
            strategy=str(data.get("strategy", "UNKNOWN_STRUCTURAL_CHANGE")),
            provenance=str(data.get("provenance", DETERMINISTIC_OPERATOR)),
            representation=PatchRepresentation.from_value(representation),
            base_subject_hash=str(data.get("base_subject_hash", data.get("subject_hash", ""))),
            base_revision_identity=str(data.get("base_revision_identity", data.get("revision_identity", ""))),
            target_authority=str(data.get("target_authority", data.get("authority_label", "READ_ONLY_SUPPORT"))),
            hypothesis_ids=tuple(data.get("hypothesis_ids", ()) or ()), evidence_sources=tuple(data.get("evidence_sources", ()) or ()),
            generator_id=str(data.get("generator_id", data.get("generator", ""))), status=str(data.get("status", PROPOSED)),
            score=float(data.get("score", 0.0) or 0.0), complexity=int(data.get("complexity", 0) or 0),
            reasons=tuple(data.get("reasons", ()) or ()), metadata=dict(data.get("metadata", {}) or {}),
            repair_id=str(data.get("repair_id", "")), generator=str(data.get("generator", data.get("generator_id", ""))),
            target_paths=tuple(data.get("target_paths", ()) or ()), target_symbols=tuple(data.get("target_symbols", ()) or ()),
            changed_ranges=tuple(data.get("changed_ranges", ()) or ()), candidate_source_hash=str(data.get("candidate_source_hash", "")),
            score_contributions=dict(data.get("score_contributions", {}) or {}),
        )


@dataclass(frozen=True)
class PatchCandidateReceipt:
    candidate_id: str
    candidate_hash: str
    status: str
    base_subject_hash: str
    sandbox_subject_hash: str = ""
    changed_paths: tuple[str, ...] = ()
    syntax: dict[str, Any] = field(default_factory=dict)
    targeted_checks: dict[str, Any] = field(default_factory=dict)
    guard_checks: dict[str, Any] = field(default_factory=dict)
    contract_checks: dict[str, Any] = field(default_factory=dict)
    v25_5: dict[str, Any] = field(default_factory=dict)
    v25_6: dict[str, Any] = field(default_factory=dict)
    violations: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    canonical_audit_hash: str = ""
    provider_calls: int = 0
    sandbox_identity: str = ""
    diff_size: int = 0
    validity: str = ""

    @property
    def candidate_identity(self) -> str:
        return self.candidate_id

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {
            "candidate_id": self.candidate_id, "candidate_hash": self.candidate_hash, "status": self.status,
            "base_subject_hash": self.base_subject_hash, "sandbox_subject_hash": self.sandbox_subject_hash,
            "changed_paths": list(self.changed_paths), "syntax": dict(self.syntax),
            "targeted_checks": dict(self.targeted_checks), "guard_checks": dict(self.guard_checks),
            "contract_checks": dict(self.contract_checks), "v25_5": dict(self.v25_5), "v25_6": dict(self.v25_6),
            "violations": list(self.violations), "evidence": list(self.evidence),
            "canonical_audit_hash": self.canonical_audit_hash, "provider_calls": self.provider_calls,
            "sandbox_identity": self.sandbox_identity, "diff_size": self.diff_size, "validity": self.validity,
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


@dataclass(frozen=True)
class CandidateFailureEvidence:
    candidate_id: str
    status: str
    stage: str
    reason: str
    violations: tuple[str, ...] = ()
    subject_hash: str = ""
    target_path: str = ""
    canonical_hash_value: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    strategy: str = ""
    changed_paths: tuple[str, ...] = ()
    source_anchors: tuple[dict[str, Any], ...] = ()
    syntax_diagnostic: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_value(cls, value: Any) -> "CandidateFailureEvidence":
        if isinstance(value, cls):
            return value
        data = _map(value)
        return cls(
            candidate_id=str(data.get("candidate_id", "candidate")), status=str(data.get("status", "FAILED")),
            stage=str(data.get("stage", "evaluation")), reason=str(data.get("reason", "")),
            violations=tuple(data.get("violations", ()) or ()), subject_hash=str(data.get("subject_hash", "")),
            target_path=str(data.get("target_path", "")), canonical_hash_value=str(data.get("canonical_hash_value", "")),
            details=dict(data.get("details", {}) or {}), strategy=str(data.get("strategy", "")),
            changed_paths=tuple(data.get("changed_paths", ()) or ()), source_anchors=tuple(data.get("source_anchors", ()) or ()),
            syntax_diagnostic=dict(data.get("syntax_diagnostic", {}) or {}),
        )

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value = {"candidate_id": self.candidate_id, "status": self.status, "stage": self.stage, "reason": self.reason, "violations": list(self.violations), "subject_hash": self.subject_hash, "target_path": self.target_path, "canonical_hash_value": self.canonical_hash_value, "details": dict(self.details), "strategy": self.strategy, "changed_paths": list(self.changed_paths), "source_anchors": list(self.source_anchors), "syntax_diagnostic": dict(self.syntax_diagnostic)}
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


class ModelPatchCandidateProvider(Protocol):
    def generate(self, repair_problem: Any, selected_source_evidence: Mapping[str, Any], *, limit: int) -> Iterable[Any]: ...

    def propose(self, problem: Any, context: Mapping[str, Any], *, limit: int) -> Iterable[Any]: ...


def _read(root: Path, path: str) -> str:
    target = (root / _safe_path(path)).resolve()
    try:
        target.relative_to(root.resolve())
        # Preserve physical newline bytes so generated exact anchors remain
        # valid in Windows CRLF repositories and their copied sandboxes.
        return target.read_bytes().decode("utf-8", errors="replace")
    except (OSError, ValueError):
        return ""


def _base_candidate(problem: Any, record: Mapping[str, Any], strategy: str, operation: PatchOperation, *, provenance: str = DETERMINISTIC_OPERATOR, generator: str = "operator", reasons: Iterable[str] = ()) -> PatchCandidate:
    candidate_seed = {
        "record": dict(record), "strategy": strategy,
        "operation": operation.to_dict(include_hash=False), "generator": generator,
    }
    return PatchCandidate(
        candidate_id=f"C5-{canonical_hash(candidate_seed)[:20]}",
        target_path=operation.path, target_symbol=str(record.get("symbol", "")), strategy=strategy,
        provenance=provenance, representation=PatchRepresentation((operation,), operation.operation),
        base_subject_hash=str(getattr(problem, "subject_identity", "")), base_revision_identity=str(getattr(problem, "revision_identity", "")),
        target_authority=str(record.get("authority_label", record.get("target_authority", "READ_ONLY_SUPPORT"))),
        hypothesis_ids=tuple(getattr(problem, "hypothesis_ids", ())), evidence_sources=tuple(record.get("evidence_sources", ())),
        generator_id=generator, reasons=tuple(reasons), metadata={"source_candidate_id": record.get("candidate_id", "")},
        repair_id=str(getattr(problem, "repair_id", "")), generator=generator,
        candidate_source_hash=str(getattr(problem, "subject_identity", "")),
        score=float(record.get("score", record.get("aggregate_suspiciousness_score", 0.0)) or 0.0),
        score_contributions={
            "localization_support": float(record.get("score", record.get("aggregate_suspiciousness_score", 0.0)) or 0.0),
            "evidence_source_count": float(len(record.get("evidence_sources", ()) or ())),
        },
    )


def _candidate_file_hash(root: Path, path: str) -> str:
    target = root / _safe_path(path)
    try:
        return hashlib.sha256(target.read_bytes()).hexdigest()
    except OSError:
        return ""


def _operation(path: str, text: str, replacement: str, *, operation: str = EXACT_REPLACEMENT, symbol: str = "", root: Path | None = None) -> PatchOperation:
    return PatchOperation(path, operation, text, replacement, _candidate_file_hash(root, path) if root else "", symbol=symbol, anchor_hash=_text_hash(text) if text else "")


def generate_deterministic_candidates(problem: Any, root: str | Path, record: Mapping[str, Any], strategy: str) -> tuple[PatchCandidate, ...]:
    """Generate only structurally anchored, bounded operators."""
    root_path = Path(root).expanduser().resolve()
    path = str(record.get("path", record.get("target_path", ""))).replace("\\", "/")
    if not path:
        return ()
    text = _read(root_path, path)
    if not text:
        return ()
    symbol = str(record.get("symbol", record.get("target_symbol", "")))
    metadata: dict[str, Any] = {}
    metadata.update(_map(getattr(problem, "metadata", {})))
    metadata.update(_map(record.get("metadata", {})))
    for failure in getattr(problem, "failure_evidence", ()) or ():
        value = _map(failure.to_dict() if hasattr(failure, "to_dict") else failure)
        metadata.update({key: value[key] for key in value if value.get(key) is not None and key not in metadata})
        metadata.update(_map(value.get("metadata", {})))
    for contract in getattr(problem, "contracts", ()) or ():
        value = _map(contract)
        for key in ("export", "import", "missing_export", "missing_import", "export_callable", "expected_external", "expected_text", "actual_text"):
            if value.get(key) is not None:
                metadata.setdefault(key, value.get(key))
    candidates: list[PatchCandidate] = []
    def add(op: PatchOperation, why: str, *, source: str = DETERMINISTIC_OPERATOR, generator: str = "operator") -> None:
        if op.expected_text and op.expected_text not in text:
            return
        candidates.append(_base_candidate(problem, record, strategy, op, provenance=source, generator=generator, reasons=(why,)))

    if strategy == EXACT_VALUE_CHANGE:
        old = metadata.get("expected_text", metadata.get("expected", ""))
        new = metadata.get("actual_text", metadata.get("actual", metadata.get("replacement", "")))
        if old is not None and new is not None and isinstance(old, str) and isinstance(new, str) and old and old != new and text.count(old) == 1:
            add(_operation(path, old, new, symbol=symbol, root=root_path), "exact_expected_actual_pair")
    if strategy == CONDITION_CHANGE:
        old = metadata.get("condition_text", metadata.get("condition", metadata.get("expected_text", "")))
        new = metadata.get("replacement_text", metadata.get("replacement", metadata.get("actual_text", "")))
        if not old and isinstance(metadata.get("expected"), bool) and isinstance(metadata.get("actual"), bool):
            expected_bool = "true" if metadata["expected"] else "false"
            actual_bool = "true" if metadata["actual"] else "false"
            if text.count(expected_bool) == 1:
                old, new = expected_bool, actual_bool
        if isinstance(old, str) and isinstance(new, str) and old and new and old != new and text.count(old) == 1:
            add(_operation(path, old, new, symbol=symbol, root=root_path), "anchored_condition_change")
    if strategy == EXPORT_IMPORT_REPAIR:
        if symbol and re.search(rf"\b(?:function|class|const|let|var)\s+{re.escape(symbol)}\b", text) and symbol not in re.findall(r"(?:export\s+\{|module\.exports\s*=|exports\.)[^\n]*", text):
            if "module.exports" in text:
                anchor = next((line for line in text.splitlines(True) if "module.exports" in line), "")
                if anchor:
                    line = anchor.rstrip("\n")
                    object_match = re.search(r"module\.exports\s*=\s*\{([^}]*)\}", line)
                    if object_match:
                        members = object_match.group(1).strip()
                        replacement_line = line[:object_match.start(1)] + (members + ", " if members else "") + symbol + line[object_match.end(1):]
                        add(_operation(path, anchor, replacement_line + ("\n" if anchor.endswith("\n") else ""), symbol=symbol, root=root_path), "missing_commonjs_export_object")
                    else:
                        add(_operation(path, anchor, line + f"\nmodule.exports.{symbol} = {symbol};" + ("\n" if anchor.endswith("\n") else ""), symbol=symbol, root=root_path), "missing_commonjs_export_assignment")
            elif re.search(r"\bexport\s", text):
                add(_operation(path, "", f"\nexport {{ {symbol} }};\n", operation=INSERTION, symbol=symbol, root=root_path), "missing_named_export")
            else:
                add(_operation(path, "", f"\nmodule.exports.{symbol} = {symbol};\n", operation=INSERTION, symbol=symbol, root=root_path), "missing_commonjs_export")
    if strategy in {FUNCTION_LOCAL_REWRITE, SMALL_INSERTION} and symbol:
        match = re.search(rf"((?:export\s+)?function\s+{re.escape(symbol)}\s*\([^)]*\)\s*\{{)([^}}]*)(\}})", text, re.S)
        insertion = metadata.get("insertion", metadata.get("insertion_text", metadata.get("replacement", "")))
        if match and isinstance(insertion, str) and insertion:
            body = match.group(0)
            add(_operation(path, body, body[:-1] + "\n" + insertion + "\n}", operation=FUNCTION_REPLACEMENT, symbol=symbol, root=root_path), "localized_function_insertion")
    if strategy == SMALL_DELETION:
        duplicate = metadata.get("duplicate_text", "")
        if not duplicate:
            declarations = re.findall(r"(?m)^(?:export\s+)?function\s+([A-Za-z_$][\w$]*)\s*\([^\n]*\)\s*\{[^}]*\}\s*\n?", text)
            for name in sorted(set(declarations)):
                block_rows = re.findall(rf"(?m)^(?:export\s+)?function\s+{re.escape(name)}\s*\([^\n]*\)\s*\{{[^}}]*\}}\s*\n?", text)
                if len(block_rows) >= 2:
                    duplicate = block_rows[0]
                    break
        if isinstance(duplicate, str) and duplicate and text.count(duplicate) >= 2:
            add(_operation(path, duplicate, "", operation=DELETION, symbol=symbol, root=root_path), "remove_one_duplicate")
    operations = metadata.get("operations")
    if strategy in {MULTI_LOCATION_SINGLE_FILE_CHANGE, MULTI_FILE_BOUNDED_CHANGE} and isinstance(operations, (list, tuple)):
        parsed = tuple(PatchOperation.from_value(item) for item in operations)
        if parsed and all(item.path in getattr(problem, "target_set", {}).candidate_files if hasattr(getattr(problem, "target_set", None), "candidate_files") else True for item in parsed):
            candidates.append(PatchCandidate(
                candidate_id=f"C5-{canonical_hash([item.to_dict(include_hash=False) for item in parsed])[:20]}",
                target_path=parsed[0].path, target_symbol=symbol, strategy=strategy, provenance=DETERMINISTIC_OPERATOR,
                representation=PatchRepresentation(parsed, MULTI_OPERATION), base_subject_hash=str(getattr(problem, "subject_identity", "")),
                base_revision_identity=str(getattr(problem, "revision_identity", "")), target_authority=str(record.get("authority_label", "READ_ONLY_SUPPORT")),
                hypothesis_ids=tuple(getattr(problem, "hypothesis_ids", ())), evidence_sources=tuple(record.get("evidence_sources", ())),
                generator_id="explicit_operations", reasons=("bounded_explicit_operations",),
            ))
    return tuple(candidates)


def generate_experiment_derived_candidate(problem: Any, root: str | Path, record: Mapping[str, Any]) -> PatchCandidate | None:
    metadata = _map(getattr(problem, "metadata", {}))
    metadata.update(_map(record.get("metadata", {})))
    path = metadata.get("target_path", record.get("path", ""))
    old = metadata.get("expected_anchor", metadata.get("expected_text", ""))
    new = metadata.get("replacement", metadata.get("replacement_text", ""))
    if not path or not old or not isinstance(new, str):
        return None
    op = _operation(str(path), str(old), new, symbol=str(record.get("symbol", "")), root=Path(root).resolve())
    return _base_candidate(problem, record, FUNCTION_LOCAL_REWRITE, op, provenance=EXPERIMENT_DERIVED, generator="experiment_ledger", reasons=("new_candidate_bound_to_current_source",))


def normalize_model_candidates(values: Iterable[Any], problem: Any) -> tuple[PatchCandidate, ...]:
    result: list[PatchCandidate] = []
    for value in values:
        data = _map(value)
        try:
            candidate = PatchCandidate.from_value({**data, "provenance": MODEL_PROPOSED, "target_authority": data.get("target_authority", data.get("authority_label", "READ_ONLY_SUPPORT"))})
        except (TypeError, ValueError):
            continue
        result.append(candidate)
    return tuple(result)


def generate_patch_candidates(problem: Any, root: str | Path, *, strategies: Iterable[str] | None = None, max_candidates: int | None = None) -> tuple[PatchCandidate, ...]:
    """Small direct generator seam used by planners and provider-free tests.

    The full bounded cascade lives in :class:`hivo.patch_search.PatchSearchEngine`;
    this helper only performs deterministic proposal generation.
    """
    from .mutation_strategy import MutationStrategyRouter
    budget = getattr(problem, "candidate_budget", None)
    limit = int(max_candidates or getattr(budget, "max_candidates", 8))
    router = MutationStrategyRouter(max_strategies=int(getattr(budget, "max_strategies", 4)))
    result: list[PatchCandidate] = []
    for record in tuple(getattr(problem, "suspect_candidates", ()) or ())[: int(getattr(budget, "max_suspects", 3))]:
        decision = router.route(problem, record)
        selected = tuple(strategies) if strategies is not None else decision.strategies
        for strategy in selected:
            for candidate in generate_deterministic_candidates(problem, root, record, strategy):
                if len(result) >= limit:
                    return tuple(result)
                result.append(candidate)
    return tuple(result)


__all__ = [
    "DNT_PROTECTED",
    "DETERMINISTIC_OPERATOR", "REPAIR_TEMPLATE", "EXPERIMENT_DERIVED", "MODEL_PROPOSED", "USER_PROPOSED",
    "PROPOSED", "STALE_BASE", "AUTHORITY_BLOCKED", "SYNTAX_INVALID", "TARGET_FAILED", "GUARD_REGRESSION", "CONTRACT_CONFLICT", "V25_5_REJECTED", "V25_6_FAILED", "VIABLE", "VERIFIED", "STATUS_VALUES",
    "STALE_PATCH_BASE", "REGRESSION_RISK", "SYNTAX_INVALID_CANDIDATE",
    "EXACT_REPLACEMENT", "INSERTION", "DELETION", "FUNCTION_REPLACEMENT", "MULTI_OPERATION",
    "PatchOperation", "PatchRepresentation", "PatchCandidate", "PatchCandidateReceipt", "CandidateFailureEvidence", "ModelPatchCandidateProvider",
    "generate_deterministic_candidates", "generate_experiment_derived_candidate", "normalize_model_candidates",
    "generate_patch_candidates",
]
