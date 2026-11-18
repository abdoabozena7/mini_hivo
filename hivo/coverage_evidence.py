"""Optional, revision-bound coverage evidence for HIVO CORE-4.

Coverage is deliberately an input adapter, not a test runner.  A provider may
collect bounded coverage in a caller-owned sandbox, but CORE-4 never turns a
coverage row into verification or mutation authority.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol

from .project_brain_refs import canonical_hash, normalize_relative_path


COVERAGE_SCHEMA_VERSION = "CORE-4-COVERAGE-EVIDENCE-V1"
COVERAGE_AVAILABLE = "COVERAGE_AVAILABLE"
COVERAGE_NOT_AVAILABLE = "COVERAGE_NOT_AVAILABLE"
COVERAGE_STALE = "STALE_COVERAGE_EVIDENCE"


def _safe_path(value: Any) -> str | None:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ":/" in raw or ".." in raw.split("/"):
        return None
    try:
        return normalize_relative_path(raw)
    except (TypeError, ValueError):
        return None


def _string_tuple(values: Iterable[Any] = ()) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({str(value) for value in values if str(value).strip()}))


def _path_tuple(values: Iterable[Any] = ()) -> tuple[str, ...]:
    if isinstance(values, str):
        values = (values,)
    return tuple(sorted({path for value in values if (path := _safe_path(value))}))


@dataclass(frozen=True)
class CoverageEvidence:
    """Canonical coverage projection with no source-body payloads."""

    coverage_id: str = ""
    subject_identity: str = ""
    revision_identity: str = ""
    status: str = COVERAGE_AVAILABLE
    failing_tests: tuple[str, ...] = ()
    passing_tests: tuple[str, ...] = ()
    files_executed: tuple[str, ...] = ()
    symbols_executed: tuple[str, ...] = ()
    executed_lines: dict[str, tuple[int, ...]] = field(default_factory=dict)
    hit_counts: dict[str, dict[str, int]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "coverage_id", str(self.coverage_id or ""))
        object.__setattr__(self, "subject_identity", str(self.subject_identity or ""))
        object.__setattr__(self, "revision_identity", str(self.revision_identity or ""))
        object.__setattr__(self, "status", str(self.status or COVERAGE_NOT_AVAILABLE))
        object.__setattr__(self, "failing_tests", _string_tuple(self.failing_tests))
        object.__setattr__(self, "passing_tests", _string_tuple(self.passing_tests))
        object.__setattr__(self, "files_executed", _path_tuple(self.files_executed))
        object.__setattr__(self, "symbols_executed", _string_tuple(self.symbols_executed))
        lines: dict[str, tuple[int, ...]] = {}
        for raw_path, raw_lines in dict(self.executed_lines or {}).items():
            path = _safe_path(raw_path)
            if not path:
                continue
            if isinstance(raw_lines, Mapping):
                raw_lines = raw_lines.keys()
            normalized_lines: set[int] = set()
            for line in raw_lines or ():
                try:
                    value = int(line)
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    normalized_lines.add(value)
            lines[path] = tuple(sorted(normalized_lines))
        object.__setattr__(self, "executed_lines", lines)
        counts: dict[str, dict[str, int]] = {}
        for raw_key, raw_value in dict(self.hit_counts or {}).items():
            key = str(raw_key)
            if isinstance(raw_value, Mapping):
                counts[key] = {
                    str(name): max(0, int(value))
                    for name, value in raw_value.items()
                    if str(name).strip()
                }
            elif isinstance(raw_value, (tuple, list)) and len(raw_value) >= 2:
                counts[key] = {"failing": max(0, int(raw_value[0])), "passing": max(0, int(raw_value[1]))}
            else:
                counts[key] = {"failing": max(0, int(raw_value or 0)), "passing": 0}
        object.__setattr__(self, "hit_counts", counts)
        object.__setattr__(self, "metadata", dict(self.metadata or {}))

    @property
    def canonical_hash(self) -> str:
        return canonical_hash(self.to_dict(include_hash=False))

    @property
    def available(self) -> bool:
        return self.status == COVERAGE_AVAILABLE

    @property
    def files(self) -> tuple[str, ...]:
        return self.files_executed

    @property
    def symbols(self) -> tuple[str, ...]:
        return self.symbols_executed

    @classmethod
    def from_value(cls, value: "CoverageEvidence | Mapping[str, Any]") -> "CoverageEvidence":
        if isinstance(value, cls):
            return value
        data = dict(value or {})
        files = data.get("files_executed", data.get("files", data.get("executed_files", ())))
        symbols = data.get("symbols_executed", data.get("symbols", data.get("executed_symbols", ())))
        return cls(
            coverage_id=str(data.get("coverage_id", data.get("id", ""))),
            subject_identity=str(data.get("subject_identity", data.get("subject", ""))),
            revision_identity=str(data.get("revision_identity", data.get("revision", ""))),
            status=str(data.get("status", COVERAGE_AVAILABLE if (files or symbols or data.get("hit_counts")) else COVERAGE_NOT_AVAILABLE)),
            failing_tests=tuple(data.get("failing_tests", data.get("failed_tests", ())) or ()),
            passing_tests=tuple(data.get("passing_tests", data.get("passed_tests", ())) or ()),
            files_executed=tuple(files or ()),
            symbols_executed=tuple(symbols or ()),
            executed_lines=dict(data.get("executed_lines", data.get("lines", {})) or {}),
            hit_counts=dict(data.get("hit_counts", data.get("counts", {})) or {}),
            metadata=dict(data.get("metadata", {}) or {}),
        )

    def to_dict(self, *, include_hash: bool = True) -> dict[str, Any]:
        value: dict[str, Any] = {
            "schema_version": COVERAGE_SCHEMA_VERSION,
            "coverage_id": self.coverage_id,
            "subject_identity": self.subject_identity,
            "revision_identity": self.revision_identity,
            "status": self.status,
            "failing_tests": list(self.failing_tests),
            "passing_tests": list(self.passing_tests),
            "files_executed": list(self.files_executed),
            "symbols_executed": list(self.symbols_executed),
            "executed_lines": {key: list(self.executed_lines[key]) for key in sorted(self.executed_lines)},
            "hit_counts": {key: dict(self.hit_counts[key]) for key in sorted(self.hit_counts)},
            "metadata": dict(self.metadata),
        }
        if include_hash:
            value["canonical_hash"] = canonical_hash(value)
        return value


class CoverageEvidenceProvider(Protocol):
    """Provider contract; implementations are caller-owned and optional."""

    def collect(
        self,
        failing_test_or_check: str,
        subject_identity: str,
        revision_identity: str,
        max_tests: int = 5,
    ) -> CoverageEvidence | Mapping[str, Any] | None:
        ...


def collect_coverage_evidence(
    provider: CoverageEvidenceProvider | Any | None,
    failing_test_or_check: str,
    *,
    subject_identity: str = "",
    revision_identity: str = "",
    max_tests: int = 5,
) -> CoverageEvidence:
    """Collect one bounded, revision-checked coverage projection."""
    if provider is None:
        return CoverageEvidence(
            coverage_id="coverage-unavailable",
            subject_identity=subject_identity,
            revision_identity=revision_identity,
            status=COVERAGE_NOT_AVAILABLE,
        )
    try:
        result = provider.collect(
            str(failing_test_or_check), str(subject_identity), str(revision_identity), max_tests=max(0, int(max_tests))
        )
    except TypeError:
        # Small fake providers often implement the shorter documented shape.
        try:
            result = provider.collect(str(failing_test_or_check), max_tests=max(0, int(max_tests)))
        except TypeError:
            try:
                result = provider.collect(str(failing_test_or_check))
            except Exception:
                return CoverageEvidence(
                    coverage_id="coverage-provider-error",
                    subject_identity=subject_identity,
                    revision_identity=revision_identity,
                    status=COVERAGE_NOT_AVAILABLE,
                    metadata={"provider_error": True},
                )
        except Exception:
            return CoverageEvidence(
                coverage_id="coverage-provider-error",
                subject_identity=subject_identity,
                revision_identity=revision_identity,
                status=COVERAGE_NOT_AVAILABLE,
                metadata={"provider_error": True},
            )
    except Exception:
        return CoverageEvidence(
            coverage_id="coverage-provider-error",
            subject_identity=subject_identity,
            revision_identity=revision_identity,
            status=COVERAGE_NOT_AVAILABLE,
            metadata={"provider_error": True},
        )
    evidence = CoverageEvidence.from_value(result or {})
    if evidence.subject_identity and subject_identity and evidence.subject_identity != subject_identity:
        return CoverageEvidence.from_value({**evidence.to_dict(include_hash=False), "status": COVERAGE_STALE})
    if evidence.revision_identity and revision_identity and evidence.revision_identity != revision_identity:
        return CoverageEvidence.from_value({**evidence.to_dict(include_hash=False), "status": COVERAGE_STALE})
    return evidence


def ochiai_suspiciousness(
    failing_hits: int,
    passing_hits: int,
    *,
    failing_total: int,
    passing_total: int,
) -> float:
    """Return a small, interpretable Ochiai-style suspiciousness value."""
    ef = max(0, int(failing_hits))
    ep = max(0, int(passing_hits))
    nf = max(0, int(failing_total) - ef)
    denominator = math.sqrt(max(0, (ef + nf) * (ef + ep)))
    if denominator <= 0:
        return 0.0
    return round(ef / denominator, 6)


def coverage_hit_counts(evidence: CoverageEvidence, key: str) -> tuple[int, int]:
    """Normalize a candidate key to failing/passing hit counts."""
    row = evidence.hit_counts.get(str(key), {})
    return max(0, int(row.get("failing", row.get("failed", 0)))), max(0, int(row.get("passing", row.get("passed", 0))))


__all__ = [
    "COVERAGE_SCHEMA_VERSION", "COVERAGE_AVAILABLE", "COVERAGE_NOT_AVAILABLE", "COVERAGE_STALE",
    "CoverageEvidence", "CoverageEvidenceProvider", "collect_coverage_evidence",
    "ochiai_suspiciousness", "coverage_hit_counts",
]
