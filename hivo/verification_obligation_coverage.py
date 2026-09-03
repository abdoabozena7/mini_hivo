"""Deterministic verification-obligation coverage for V25.3.

This module owns the small piece of authority that was missing between the
approved verification contracts and Stage 5.  It answers a deliberately
narrow question: which exact atomic obligation does an already-approved
verification oracle independently establish?

It never calls a provider, reads Worker prose, creates a test, or grants
mutation authority.  Source and test inspection is conservative and is used
only to establish preservation relationships.  A new behavior obligation is
covered only by an explicit, approved oracle binding that names an externally
observable assertion.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Iterable

from hivo import execution_invariants as invariant
from hivo import impact_planning as planning
from hivo.requirements import freeze


SCHEMA_VERSION = "25.3-VERIFICATION-OBLIGATION-COVERAGE-1"

EXECUTION_VERIFICATION_READY = "EXECUTION_VERIFICATION_READY"
VERIFICATION_OBLIGATION_UNCOVERED = "VERIFICATION_OBLIGATION_UNCOVERED"
VERIFICATION_OBLIGATION_COVERAGE_INVALID = "VERIFICATION_OBLIGATION_COVERAGE_INVALID"
VERIFICATION_OBLIGATION_COVERAGE_REQUIRED = "VERIFICATION_OBLIGATION_COVERAGE_REQUIRED"
VERIFICATION_OBLIGATION_COVERAGE_MISMATCH = "VERIFICATION_OBLIGATION_COVERAGE_MISMATCH"
REAPPROVAL_REQUIRED = "REAPPROVAL_REQUIRED"

FOCUSED_TEST = "FOCUSED_TEST"
INTEGRATION_TEST = "INTEGRATION_TEST"
SYNTAX_CHECK = "SYNTAX_CHECK"
DETERMINISTIC_AUTHORITY_VALIDATOR = "DETERMINISTIC_AUTHORITY_VALIDATOR"
DETERMINISTIC_DNT_VALIDATOR = "DETERMINISTIC_DNT_VALIDATOR"
DETERMINISTIC_INTERFACE_VALIDATOR = "DETERMINISTIC_INTERFACE_VALIDATOR"
DETERMINISTIC_STATE_VALIDATOR = "DETERMINISTIC_STATE_VALIDATOR"

ORACLE_TYPES = (
    FOCUSED_TEST,
    INTEGRATION_TEST,
    SYNTAX_CHECK,
    DETERMINISTIC_AUTHORITY_VALIDATOR,
    DETERMINISTIC_DNT_VALIDATOR,
    DETERMINISTIC_INTERFACE_VALIDATOR,
    DETERMINISTIC_STATE_VALIDATOR,
)

DIRECT = "DIRECT"
PRESERVATION = "PRESERVATION"
SUPPORTING = "SUPPORTING"
NOT_COVERING = "NOT_COVERING"
COVERAGE_RELATIONSHIPS = (DIRECT, PRESERVATION, SUPPORTING, NOT_COVERING)

STRONG = "STRONG"
SUPPORTING_STRENGTH = "SUPPORTING"
WEAK = "WEAK"
COVERAGE_STRENGTHS = (STRONG, SUPPORTING_STRENGTH, WEAK)

COVERED = "COVERED"
UNCOVERED = "UNCOVERED"
NOT_APPLICABLE = "NOT_APPLICABLE"
RESOLVED = "RESOLVED"
UNRESOLVED = "UNRESOLVED"
STALE = "STALE"

BEHAVIOR_CHANGE = "BEHAVIOR_CHANGE"
PRESERVATION_OBLIGATION = "PRESERVATION"

MAX_OBLIGATIONS = 64
MAX_ORACLES = 64
MAX_COVERAGE_BINDINGS = 128
MAX_REQUIREMENTS = 32
MAX_REFS = 32
MAX_PATHS = 32
MAX_TEXT = 900

_TEST_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])((?:src|tests?)/[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*\.[A-Za-z0-9]+)",
    re.IGNORECASE,
)
_RENDER_CALL_RE = re.compile(r"\brenderStatus\s*\(", re.IGNORECASE)
_LEGACY_RENDER_ASSERT_RE = re.compile(
    r"assert\s*\.\s*(?:equal|strictEqual|deepEqual)\s*\(\s*renderStatus\s*\([^)]*\)\s*,\s*(['\"])(Paused|Running)\1",
    re.IGNORECASE,
)
_ESCAPE_CALL_RE = re.compile(
    r"handleInput\s*\(\s*\{\s*key\s*:\s*(['\"])Escape\1",
    re.IGNORECASE,
)
_PAUSE_ASSERT_RE = re.compile(
    r"(?:type\s*:\s*(['\"])pause\1|isPaused\s*\(\s*\)\s*,\s*(?:true|false))",
    re.IGNORECASE,
)
_MOVEMENT_CALL_RE = re.compile(
    r"handleInput\s*\(\s*\{\s*key\s*:\s*(['\"])(?:ArrowUp|ArrowDown|ArrowLeft|ArrowRight)\1",
    re.IGNORECASE,
)
_MOVE_ASSERT_RE = re.compile(
    r"(?:type\s*:\s*(['\"])move\1|direction\s*:|position\s*:\s*\{)",
    re.IGNORECASE,
)


class VerificationObligationCoverageError(ValueError):
    """A deterministic coverage artifact cannot be trusted."""

    def __init__(self, code: str, message: str, details: Iterable[Any] | None = None):
        self.code = str(code)
        self.details = list(details or [])
        super().__init__(f"{self.code}: {message}")


class _FrozenRecord(dict):
    """JSON-shaped immutable record with ordinary mapping access."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("verification-obligation coverage records are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other: Any) -> Any:
        self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


class VerificationObligationCoverage(_FrozenRecord):
    """Immutable canonical coverage authority and readiness decision."""


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


deterministic_hash = canonical_hash


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _without(value: Any, *keys: str) -> dict[str, Any]:
    result = _copy(value) if isinstance(value, dict) else {}
    for key in keys:
        result.pop(key, None)
    return result


def _text(value: Any, limit: int = MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(0, int(limit))]


def _path(value: Any) -> str:
    result = _text(value, 300).replace("\\", "/")
    while result.startswith("./"):
        result = result[2:]
    return result.rstrip("/")


def _unique(values: Iterable[Any], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _text(value, 300)
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _freeze_record(record_type: type[_FrozenRecord], value: dict[str, Any]) -> _FrozenRecord:
    result = record_type()
    dict.__init__(result, ((key, freeze(item)) for key, item in value.items()))
    return result


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _requirement_ids(plan: dict[str, Any], ledger: dict[str, Any]) -> list[str]:
    result = []
    for item in _as_list(plan.get("requirements")):
        if isinstance(item, dict) and item.get("requirement_id"):
            result.append(str(item["requirement_id"]))
    for item in _as_list(ledger.get("requirements")):
        if isinstance(item, dict) and item.get("requirement_id"):
            result.append(str(item["requirement_id"]))
    return _unique(result, MAX_REQUIREMENTS)


def _ledger_value(plan: dict[str, Any], supplied: Any) -> dict[str, Any]:
    if isinstance(supplied, dict):
        return _copy(supplied)
    for key in ("requirement_obligation_ledger", "obligation_ledger", "atomic_obligation_ledger"):
        candidate = plan.get(key)
        if isinstance(candidate, dict):
            return _copy(candidate)
    requirements = plan.get("requirements", []) if isinstance(plan, dict) else []
    return _copy(planning.build_requirement_obligation_ledger(requirements))


def _atomic_obligations(ledger: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for requirement in _as_list(ledger.get("requirements")):
        if not isinstance(requirement, dict):
            continue
        requirement_id = _text(requirement.get("requirement_id"), 160)
        for obligation in _as_list(requirement.get("obligations")):
            if not isinstance(obligation, dict):
                continue
            obligation_id = _text(obligation.get("obligation_id"), 180)
            if not obligation_id or obligation_id in seen:
                continue
            seen.add(obligation_id)
            obligation_type = _text(obligation.get("obligation_type"), 100).upper()
            mandatory = obligation.get("mandatory") is not False and obligation.get("optional") is not True
            applicability = _text(obligation.get("applicability"), 60).upper() or "REQUIRED"
            records.append({
                "obligation_id": obligation_id,
                "requirement_id": _text(obligation.get("requirement_id"), 160) or requirement_id,
                "obligation_type": obligation_type,
                "meaning": _text(obligation.get("meaning") or obligation.get("text")),
                "text": _text(obligation.get("text") or obligation.get("meaning")),
                "structured_relations": _unique(obligation.get("structured_relations", []), 16),
                "mandatory": mandatory,
                "optional": not mandatory,
                "applicability": applicability,
                "provenance": _text(obligation.get("provenance") or requirement.get("source_provenance"), 160),
            })
    return records[:MAX_OBLIGATIONS]


def _all_evidence(repository_evidence: Any) -> list[dict[str, Any]]:
    if isinstance(repository_evidence, dict):
        if isinstance(repository_evidence.get("repository_evidence"), list):
            repository_evidence = repository_evidence["repository_evidence"]
        else:
            repository_evidence = [repository_evidence]
    return [item for item in _as_list(repository_evidence) if isinstance(item, dict)]


def _evidence_by_path(repository_evidence: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for item in _all_evidence(repository_evidence):
        path = _path(item.get("path") or item.get("verified_path"))
        if path:
            result.setdefault(path.casefold(), []).append(item)
    return result


def _candidate_paths(repository_evidence: Any, source_root: str | Path | None, source_files: dict[str, Any] | None) -> list[str]:
    paths = [
        _path(item.get("path"))
        for item in _all_evidence(repository_evidence)
        if _path(item.get("path"))
    ]
    if isinstance(source_files, dict):
        paths.extend(_path(item) for item in source_files if _path(item))
    if source_root is not None:
        try:
            root = Path(source_root).expanduser().resolve()
            if root.is_dir():
                for current, dirs, names in os.walk(root):
                    dirs[:] = [name for name in dirs if name not in {".git", ".hivo", "node_modules", "__pycache__"}]
                    for name in names:
                        try:
                            paths.append((Path(current) / name).relative_to(root).as_posix())
                        except ValueError:
                            continue
        except (OSError, RuntimeError, TypeError, ValueError):
            pass
    return _unique(paths, MAX_PATHS * 8)


def _read_source(path: str, source_root: str | Path | None, source_files: dict[str, Any] | None) -> tuple[str, str]:
    normalized = _path(path)
    if isinstance(source_files, dict):
        for key, value in source_files.items():
            if _path(key).casefold() == normalized.casefold() and isinstance(value, str):
                return value, RESOLVED
    if source_root is not None and normalized:
        try:
            root = Path(source_root).expanduser().resolve()
            target = (root / normalized).resolve()
            if root == target or root not in target.parents:
                return "", UNRESOLVED
            if target.is_file():
                return target.read_text(encoding="utf-8", errors="replace"), RESOLVED
        except (OSError, RuntimeError, UnicodeError, ValueError):
            return "", UNRESOLVED
    return "", UNRESOLVED


def _sha256_source(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _target_status(
    path: str,
    *,
    source_root: str | Path | None,
    source_files: dict[str, Any] | None,
    evidence_by_path: dict[str, list[dict[str, Any]]],
    declared_status: Any = None,
) -> tuple[str, str, str]:
    declared = _text(declared_status, 80).upper()
    if declared in {NOT_APPLICABLE, "NOT-APPLICABLE"}:
        return NOT_APPLICABLE, "declared_not_applicable", ""
    if declared in {STALE, "STALE_EVIDENCE"}:
        return STALE, "declared_stale", ""
    if declared in {UNRESOLVED, "UNRESOLVED_TARGET", "MISSING"}:
        return UNRESOLVED, "declared_unresolved", ""
    source, status = _read_source(path, source_root, source_files)
    if status != RESOLVED:
        return UNRESOLVED, "target_not_resolved", ""
    current_hash = _sha256_source(source)
    expected = {
        _text(item.get("file_sha256"), 100).casefold()
        for item in evidence_by_path.get(_path(path).casefold(), [])
        if _text(item.get("file_sha256"), 100)
    }
    if expected and current_hash.casefold() not in expected:
        return STALE, "repository_evidence_hash_mismatch", current_hash
    return RESOLVED, "deterministic_target_resolution", current_hash


def _paths_from_contract(record: dict[str, Any], candidates: list[str]) -> list[str]:
    paths = []
    for key in ("path", "target", "requested_target"):
        if _path(record.get(key)):
            paths.append(_path(record.get(key)))
    for key in ("paths", "targets", "test_paths"):
        paths.extend(_path(item) for item in _as_list(record.get(key)) if _path(item))
    text = " ".join(_text(item) for item in _as_list(record.get("contract")))
    text += " " + _text(record.get("description"))
    for candidate in candidates:
        if candidate.casefold() in text.casefold():
            paths.append(candidate)
    for match in _TEST_PATH_RE.finditer(text):
        paths.append(_path(match.group(1)))
    return _unique(paths, MAX_PATHS)


def _nested_oracle(record: dict[str, Any]) -> dict[str, Any]:
    result = _copy(record)
    for key in ("oracle", "verification_oracle", "oracle_record"):
        child = record.get(key)
        if isinstance(child, dict):
            merged = _copy(child)
            merged.update(result)
            result = merged
    return result


def _test_semantics(source: str) -> dict[str, Any]:
    legacy = list(_LEGACY_RENDER_ASSERT_RE.finditer(source or ""))
    escape_calls = list(_ESCAPE_CALL_RE.finditer(source or ""))
    movement_calls = list(_MOVEMENT_CALL_RE.finditer(source or ""))
    pause_assertions = list(_PAUSE_ASSERT_RE.finditer(source or ""))
    move_assertions = list(_MOVE_ASSERT_RE.finditer(source or ""))
    return {
        "calls_render_status": bool(_RENDER_CALL_RE.search(source or "")),
        "legacy_render_assertions": [item.group(2) for item in legacy],
        "escape_calls": len(escape_calls),
        "escape_assertions": len(pause_assertions),
        "movement_calls": len(movement_calls),
        "movement_assertions": len(move_assertions),
        "escape_preservation": bool(escape_calls and pause_assertions),
        "movement_preservation": bool(movement_calls and move_assertions),
        "legacy_render_preservation": bool(legacy),
    }


def _oracle_type(record: dict[str, Any], path: str, source: str) -> str:
    explicit = _text(record.get("oracle_type") or record.get("type"), 100).upper()
    if explicit in ORACLE_TYPES:
        return explicit
    if Path(path).suffix.casefold() in {".js", ".mjs", ".cjs", ".py"} and "--check" in _text(record.get("command")):
        return SYNTAX_CHECK
    semantics = _test_semantics(source)
    if semantics["calls_render_status"] and semantics["escape_preservation"] and semantics["movement_preservation"]:
        return INTEGRATION_TEST
    return FOCUSED_TEST


def _route_for(routes: Any, kind: str, target: str) -> dict[str, Any] | None:
    values = routes.get("verification_routes", []) if isinstance(routes, dict) else routes
    for route in _as_list(values):
        if not isinstance(route, dict):
            continue
        route_kind = _text(route.get("kind"), 100).upper()
        normalized_kind = SYNTAX_CHECK if route_kind in {"SYNTAX_STATIC_GATE", SYNTAX_CHECK} else route_kind
        if normalized_kind != kind:
            continue
        route_target = _path(route.get("target"))
        if route_target.casefold() == _path(target).casefold():
            return route
    return None


def _explicit_bindings(record: dict[str, Any], default_oracle_id: str) -> list[dict[str, Any]]:
    values = []
    for key in ("obligation_bindings", "coverage_bindings", "bindings"):
        candidate = record.get(key)
        if candidate is not None:
            values.extend(_as_list(candidate))
    result = []
    for item in values:
        if isinstance(item, str):
            result.append({"obligation_id": item, "oracle_id": default_oracle_id})
        elif isinstance(item, dict):
            value = _copy(item)
            value.setdefault("oracle_id", default_oracle_id)
            result.append(value)
    return result


def _semantic_binding(value: dict[str, Any]) -> dict[str, Any]:
    semantic = value.get("semantic_binding")
    if isinstance(semantic, dict):
        return _copy(semantic)
    for key in ("assertion", "assertions", "behavior_assertion", "expected_behavior", "observable_behavior"):
        if key in value:
            return {key: _copy(value.get(key))}
    return {}


def _direct_behavior_assertion(binding: dict[str, Any]) -> bool:
    semantic = _semantic_binding(binding)
    if not semantic:
        return False
    if binding.get("direct_behavior") is False:
        return False
    forbidden = {
        "source_presence", "source_changed", "literal_present", "worker_prose",
        "legacy_regression", "source-only", "source_only", "test_name_only",
    }
    semantic_text = _json(semantic).casefold()
    if forbidden.intersection(str(key).casefold() for key in semantic):
        return False
    if any(marker in semantic_text for marker in forbidden):
        return False
    if re.search(
        r"\b(?:source|file|test\s+name)\b.{0,48}\b(?:contain|include|literal|presence|exist|match)\b",
        semantic_text,
        re.IGNORECASE,
    ):
        return False
    if not any(token in semantic_text for token in (
        "observable", "assertion", "expected_behavior", "visible", "indicator",
    )):
        return False
    return len(semantic) >= 1


def _structural_preservation_binding(
    obligation: dict[str, Any], oracle: dict[str, Any], semantics: dict[str, Any],
) -> list[dict[str, Any]]:
    relations = set(str(item) for item in obligation.get("structured_relations", []) or [])
    result = []
    if "PRESERVE_BEHAVIOR:ESCAPE_PAUSE_FLOW" in relations and semantics.get("escape_preservation"):
        result.append({
            "obligation_id": obligation.get("obligation_id"),
            "oracle_id": oracle.get("oracle_id"),
            "coverage_relationship": PRESERVATION,
            "coverage_strength": STRONG,
            "mandatory": True,
            "applicable": True,
            "semantic_binding": {
                "structural_relation": "test assertion invokes handleInput with Escape and checks pause result/state",
                "called_symbol": "handleInput",
                "action": "Escape",
            },
            "evidence_refs": list(oracle.get("evidence_refs", []) or []),
        })
    if "PRESERVE_BEHAVIOR:MOVEMENT_INPUT" in relations and semantics.get("movement_preservation"):
        result.append({
            "obligation_id": obligation.get("obligation_id"),
            "oracle_id": oracle.get("oracle_id"),
            "coverage_relationship": PRESERVATION,
            "coverage_strength": STRONG,
            "mandatory": True,
            "applicable": True,
            "semantic_binding": {
                "structural_relation": "test assertion invokes handleInput with an Arrow key and checks move result/position",
                "called_symbol": "handleInput",
                "action": "movement",
            },
            "evidence_refs": list(oracle.get("evidence_refs", []) or []),
        })
    return result


def _normalise_oracle(
    record: dict[str, Any], *, candidates: list[str], source_root: str | Path | None,
    source_files: dict[str, Any] | None, evidence_by_path: dict[str, list[dict[str, Any]]],
    applicability: Any,
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    value = _nested_oracle(record)
    verification_id = _text(value.get("verification_id") or value.get("oracle_id"), 180)
    paths = _paths_from_contract(value, candidates)
    target = _path(value.get("target") or (paths[0] if paths else ""))
    source, source_status = _read_source(target, source_root, source_files)
    oracle_id = _text(value.get("oracle_id") or verification_id, 180)
    if not oracle_id:
        oracle_id = "ORACLE-" + canonical_hash({"verification_id": verification_id, "target": target})[:16].upper()
    oracle_type = _oracle_type(value, target, source)
    if oracle_type not in ORACLE_TYPES:
        oracle_type = FOCUSED_TEST
    evidence_refs = _unique(value.get("evidence_refs") or value.get("evidence_ids") or [], MAX_REFS)
    if not evidence_refs:
        for item in evidence_by_path.get(target.casefold(), []):
            if item.get("evidence_id"):
                evidence_refs.append(str(item["evidence_id"]))
    declared_status = value.get("target_status") or value.get("resolution_status")
    target_status, resolution_reason, source_hash = _target_status(
        target, source_root=source_root, source_files=source_files,
        evidence_by_path=evidence_by_path, declared_status=declared_status,
    ) if target else (UNRESOLVED, "target_missing", "")
    route = _route_for(applicability, oracle_type, target)
    explicit_applicable = value.get("applicable") if isinstance(value.get("applicable"), bool) else None
    if route is not None:
        route_applicable = route.get("applicable") is True and bool(route.get("target"))
        if route.get("result") == "SKIPPED_NOT_APPLICABLE":
            route_applicable = False
        if explicit_applicable is None:
            explicit_applicable = route_applicable
        if route.get("resolution_status") in {"VERIFICATION_TARGET_UNRESOLVED", UNRESOLVED}:
            target_status = UNRESOLVED
            resolution_reason = "applicability_target_unresolved"
    applicable = bool(explicit_applicable) if explicit_applicable is not None else target_status == RESOLVED
    if target_status != RESOLVED:
        applicable = False
    mandatory = value.get("mandatory") if isinstance(value.get("mandatory"), bool) else value.get("required") is not False
    approved = value.get("approved") is not False
    oracle = {
        "oracle_id": oracle_id,
        "verification_id": verification_id or None,
        "oracle_type": oracle_type,
        "target": target or None,
        "target_status": target_status,
        "resolution_reason": resolution_reason,
        "source_hash": source_hash or None,
        "paths": paths[:MAX_PATHS],
        "command": _text(value.get("command"), 600) or None,
        "contract_refs": _unique(value.get("contract_refs") or ([verification_id] if verification_id else []), MAX_REFS),
        "evidence_refs": evidence_refs[:MAX_REFS],
        "approved": approved,
        "mandatory": bool(mandatory),
        "applicable": bool(applicable),
        "authority_source": _text(
            value.get("authority_source") or "APPROVED_VERIFICATION_CONTRACT",
            180,
        ),
        "derived_deterministically": True,
        "source_status": source_status,
    }
    semantics = _test_semantics(source) if oracle_type in {FOCUSED_TEST, INTEGRATION_TEST} else {}
    bindings = _explicit_bindings(value, oracle_id)
    return oracle, bindings, semantics


def _make_validator_oracle(
    oracle_id: str, oracle_type: str, target: str | None, *, evidence_refs: Iterable[Any] = (),
    applicable: bool = True, mandatory: bool = True, authority_source: str,
    validation: str,
) -> dict[str, Any]:
    return {
        "oracle_id": oracle_id,
        "verification_id": None,
        "oracle_type": oracle_type,
        "target": _path(target) or None,
        "target_status": RESOLVED if applicable else UNRESOLVED,
        "resolution_reason": validation,
        "source_hash": None,
        "paths": [_path(target)] if _path(target) else [],
        "command": None,
        "contract_refs": [],
        "evidence_refs": _unique(evidence_refs, MAX_REFS),
        "approved": True,
        "mandatory": bool(mandatory),
        "applicable": bool(applicable),
        "authority_source": authority_source,
        "derived_deterministically": True,
        "source_status": RESOLVED if applicable else UNRESOLVED,
    }


def _invariant_by_type(value: dict[str, Any], kind: str) -> list[dict[str, Any]]:
    return [
        item for item in _as_list(value.get("invariants"))
        if isinstance(item, dict) and _text(item.get("type"), 100).upper() == kind
    ]


def _obligation_map(obligations: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(item.get("obligation_id")): item for item in obligations if item.get("obligation_id")}


def _binding_record(
    raw: dict[str, Any], oracle: dict[str, Any], obligation: dict[str, Any],
    *, reason: str | None = None,
) -> dict[str, Any]:
    relationship = _text(
        raw.get("coverage_relationship") or raw.get("relationship") or raw.get("coverage_type"),
        80,
    ).upper() or NOT_COVERING
    if relationship not in COVERAGE_RELATIONSHIPS:
        relationship = NOT_COVERING
    strength = _text(raw.get("coverage_strength") or raw.get("strength"), 80).upper()
    if strength not in COVERAGE_STRENGTHS:
        strength = STRONG if relationship in {DIRECT, PRESERVATION} else SUPPORTING_STRENGTH
    semantic = _semantic_binding(raw)
    if not semantic and raw.get("semantic_binding") is not None:
        semantic = {"invalid": _copy(raw.get("semantic_binding"))}
    valid_direct = relationship == DIRECT and (
        obligation.get("obligation_type") != BEHAVIOR_CHANGE
        or (
            oracle.get("oracle_type") in {FOCUSED_TEST, INTEGRATION_TEST}
            and _direct_behavior_assertion(raw)
        )
    )
    if relationship == DIRECT and obligation.get("obligation_type") == BEHAVIOR_CHANGE and not valid_direct:
        reason = reason or (
            "direct behavior binding requires an applicable focused/integration "
            "oracle with an explicit observable assertion"
        )
    oracle_applicable = oracle.get("applicable") is True and oracle.get("target_status") == RESOLVED
    valid = (
        oracle.get("approved") is True
        and oracle_applicable
        and raw.get("applicable", True) is not False
        and raw.get("mandatory", oracle.get("mandatory", True)) is not False
        and relationship != NOT_COVERING
        and (relationship != DIRECT or valid_direct)
    )
    if not valid and reason is None:
        if oracle.get("approved") is not True:
            reason = "oracle is not approved authority"
        elif not oracle_applicable:
            reason = "oracle target is not applicable/resolved"
        elif raw.get("mandatory", oracle.get("mandatory", True)) is False:
            reason = "optional oracle cannot satisfy a mandatory obligation"
        else:
            reason = "binding is not a valid coverage relationship"
    return {
        "coverage_id": "COV-" + canonical_hash({
            "obligation_id": obligation.get("obligation_id"),
            "oracle_id": oracle.get("oracle_id"),
            "relationship": relationship,
            "semantic": semantic,
        })[:18].upper(),
        "task_id": raw.get("task_id"),
        "requirement_id": obligation.get("requirement_id"),
        "obligation_id": obligation.get("obligation_id"),
        "obligation_type": obligation.get("obligation_type"),
        "oracle_id": oracle.get("oracle_id"),
        "oracle_type": oracle.get("oracle_type"),
        "evidence_refs": _unique(raw.get("evidence_refs") or oracle.get("evidence_refs", []), MAX_REFS),
        "contract_refs": _unique(raw.get("contract_refs") or oracle.get("contract_refs", []), MAX_REFS),
        "target": oracle.get("target"),
        "target_status": oracle.get("target_status"),
        "coverage_relationship": relationship,
        "coverage_strength": strength,
        "mandatory": bool(raw.get("mandatory", obligation.get("mandatory", True))),
        "oracle_mandatory": bool(oracle.get("mandatory")),
        "applicable": bool(oracle.get("applicable")) and raw.get("applicable", True) is not False,
        "approved": oracle.get("approved") is True,
        "valid": bool(valid),
        "satisfies": bool(valid and relationship in {DIRECT, PRESERVATION}),
        "semantic_binding": semantic,
        "validation_reason": reason,
    }


def _coverage_state(obligation: dict[str, Any], bindings: list[dict[str, Any]]) -> dict[str, Any]:
    obligation_id = obligation.get("obligation_id")
    relevant = [item for item in bindings if item.get("obligation_id") == obligation_id]
    if obligation.get("obligation_type") == BEHAVIOR_CHANGE:
        satisfying = [
            item for item in relevant
            if item.get("satisfies")
            and item.get("coverage_relationship") == DIRECT
            and item.get("oracle_type") in {FOCUSED_TEST, INTEGRATION_TEST}
            and item.get("mandatory") is True
            and item.get("oracle_mandatory") is True
            and item.get("applicable") is True
            and item.get("target_status") == RESOLVED
        ]
        required_relationship = DIRECT
    else:
        satisfying = [
            item for item in relevant
            if item.get("satisfies")
            and item.get("coverage_relationship") == PRESERVATION
            and item.get("mandatory") is True
            and item.get("oracle_mandatory") is True
            and item.get("applicable") is True
            and item.get("target_status") == RESOLVED
        ]
        required_relationship = PRESERVATION
    mandatory = obligation.get("mandatory") is not False
    state = COVERED if satisfying else UNCOVERED
    return {
        "obligation_id": obligation_id,
        "requirement_id": obligation.get("requirement_id"),
        "obligation_type": obligation.get("obligation_type"),
        "meaning": obligation.get("meaning"),
        "mandatory": mandatory,
        "required_relationship": required_relationship,
        "coverage_state": state,
        "satisfying_oracle_ids": _unique((item.get("oracle_id") for item in satisfying), MAX_ORACLES),
        "coverage_ids": _unique((item.get("coverage_id") for item in relevant), MAX_COVERAGE_BINDINGS),
        "observed_relationships": _unique((item.get("coverage_relationship") for item in relevant), 8),
        "reason": None if satisfying or not mandatory else (
            "no mandatory applicable DIRECT oracle explicitly validates the new behavior"
            if obligation.get("obligation_type") == BEHAVIOR_CHANGE
            else "no mandatory applicable preservation oracle validates this obligation"
        ),
    }


def _normalise_contracts(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        for key in (
            "approved_verification_contracts", "canonical_verification_contracts",
            "verification_contracts", "verification_oracles", "oracle_records",
        ):
            if isinstance(value.get(key), list):
                value = value[key]
                break
    return [item for item in _as_list(value) if isinstance(item, dict)]


def _mutation_paths(execution_contract: dict[str, Any] | None, plan: dict[str, Any]) -> list[str]:
    if isinstance(execution_contract, dict):
        paths = _unique(execution_contract.get("allowed_mutation_paths", []), MAX_PATHS)
        if paths:
            return paths
    for node in _as_list(plan.get("approved_change_nodes")):
        if isinstance(node, dict):
            paths = _unique(node.get("candidate_targets", []), MAX_PATHS)
            if paths:
                return paths
    return []


def _build_raw_coverage(
    plan: dict[str, Any], ledger: dict[str, Any], obligations: list[dict[str, Any]],
    *, task_id: str, verification_contracts: Any, execution_contract: dict[str, Any] | None,
    execution_invariant_set: dict[str, Any] | None, repository_evidence: Any,
    source_root: str | Path | None, source_files: dict[str, Any] | None,
    verification_applicability: Any, explicit_oracles: Any, explicit_bindings: Any,
) -> dict[str, Any]:
    evidence_by_path = _evidence_by_path(repository_evidence)
    candidates = _candidate_paths(repository_evidence, source_root, source_files)
    approved_contract_records = _normalise_contracts(verification_contracts)
    approved_verification_ids = {
        _text(item.get("verification_id") or item.get("oracle_id"), 180)
        for item in approved_contract_records
        if _text(item.get("verification_id") or item.get("oracle_id"), 180)
    }
    contracts = list(approved_contract_records)
    # Extra oracle records are accepted only when the caller identifies them
    # as approved verification authority.  In particular, merely finding a
    # test file in the repository cannot silently enlarge the approved set.
    for item in _normalise_contracts(explicit_oracles):
        candidate = _copy(item)
        identity = _text(candidate.get("verification_id") or candidate.get("oracle_id"), 180)
        source = _text(candidate.get("authority_source"), 180).upper()
        approved_extra = (
            candidate.get("approved") is True
            and (
                identity in approved_verification_ids
                or candidate.get("approved_verification_authority") is True
                or source.startswith("APPROVED_")
            )
        )
        if not approved_extra:
            candidate["approved"] = False
        contracts.append(candidate)
    oracle_records: list[dict[str, Any]] = []
    raw_bindings: list[dict[str, Any]] = []
    semantics_by_oracle: dict[str, dict[str, Any]] = {}
    seen_oracles: set[str] = set()
    for record in contracts:
        oracle, bindings, semantics = _normalise_oracle(
            record, candidates=candidates, source_root=source_root,
            source_files=source_files, evidence_by_path=evidence_by_path,
            applicability=verification_applicability,
        )
        if oracle["oracle_id"] in seen_oracles:
            # Multiple approved contract references are a fan-in to one
            # oracle identity; preserve the first identity and merge refs.
            existing = next(item for item in oracle_records if item.get("oracle_id") == oracle["oracle_id"])
            existing["contract_refs"] = _unique(
                list(existing.get("contract_refs", [])) + list(oracle.get("contract_refs", [])), MAX_REFS,
            )
            existing["evidence_refs"] = _unique(
                list(existing.get("evidence_refs", [])) + list(oracle.get("evidence_refs", [])), MAX_REFS,
            )
            raw_bindings.extend(bindings)
            continue
        seen_oracles.add(oracle["oracle_id"])
        oracle_records.append(oracle)
        raw_bindings.extend(bindings)
        semantics_by_oracle[oracle["oracle_id"]] = semantics

    # Syntax is the existing deterministic Stage 5A route for an approved
    # source mutation.  It is represented for coverage accounting but can
    # never become a DIRECT behavior oracle.
    syntax_paths = _mutation_paths(execution_contract, plan)
    for path in syntax_paths:
        oracle_id = "SYNTAX-" + _path(path).replace("/", "_").replace(".", "_").upper()
        if oracle_id in seen_oracles:
            continue
        target_status, reason, source_hash = _target_status(
            path, source_root=source_root, source_files=source_files,
            evidence_by_path=evidence_by_path,
        )
        route = _route_for(verification_applicability, SYNTAX_CHECK, path)
        applicable = target_status == RESOLVED
        if route is not None:
            applicable = applicable and route.get("applicable") is True and route.get("result") != "SKIPPED_NOT_APPLICABLE"
        oracle_records.append({
            "oracle_id": oracle_id,
            "verification_id": None,
            "oracle_type": SYNTAX_CHECK,
            "target": path,
            "target_status": target_status,
            "resolution_reason": reason,
            "source_hash": source_hash or None,
            "paths": [path],
            "command": f"node --check {path}" if Path(path).suffix.casefold() in {".js", ".mjs", ".cjs"} else None,
            "contract_refs": ["STAGE5A-SYNTAX-ROUTE"],
            "evidence_refs": _unique(
                [item.get("evidence_id") for item in evidence_by_path.get(path.casefold(), []) if item.get("evidence_id")],
                MAX_REFS,
            ),
            "approved": True,
            "mandatory": True,
            "applicable": applicable,
            "authority_source": "STAGE5A_DETERMINISTIC_ROUTE",
            "derived_deterministically": True,
            "source_status": target_status,
        })
        seen_oracles.add(oracle_id)

    # Existing V25.2 deterministic facts are preservation validators.  They
    # are not behavior oracles and are intentionally not projected to Worker.
    invariant_check = invariant.validate_execution_invariant_set(
        execution_invariant_set,
        execution_contract=execution_contract if isinstance(execution_contract, dict) else None,
        source_root=source_root,
        require_current_subject=source_root is not None,
    ) if isinstance(execution_invariant_set, dict) else {"valid": False, "errors": ["execution invariant set missing"]}
    if invariant_check.get("valid"):
        state_items = _invariant_by_type(execution_invariant_set, invariant.STATE_OWNER)
        for item in state_items[:1]:
            refs = list(item.get("source_evidence_ids", []) or []) + [
                ref.get("evidence_id") for ref in item.get("evidence_refs", []) or [] if isinstance(ref, dict)
            ]
            oid = "INVARIANT-STATE-OWNER"
            oracle_records.append(_make_validator_oracle(
                oid, DETERMINISTIC_STATE_VALIDATOR, item.get("path"),
                evidence_refs=refs, authority_source="V25.2_EXECUTION_INVARIANT_SET",
                validation="validated STATE_OWNER invariant",
            ))
            raw_bindings.append({
                "oracle_id": oid,
                "obligation_id": next((item.get("obligation_id") for item in obligations if item.get("obligation_type") == PRESERVATION_OBLIGATION and "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER" in set(item.get("structured_relations", []))), None),
                "coverage_relationship": PRESERVATION,
                "coverage_strength": STRONG,
                "mandatory": True,
                "applicable": True,
                "semantic_binding": {"validator": "STATE_OWNER", "owner": item.get("owner") or "PauseController"},
                "evidence_refs": refs,
            })
        interface_items = _invariant_by_type(execution_invariant_set, invariant.REQUIRED_INTERFACE_REUSE)
        if interface_items:
            item = interface_items[0]
            oid = "INVARIANT-INTERFACE-REUSE"
            refs = list(item.get("source_evidence_ids", []) or [])
            oracle_records.append(_make_validator_oracle(
                oid, DETERMINISTIC_INTERFACE_VALIDATOR, item.get("path"),
                evidence_refs=refs, authority_source="V25.2_EXECUTION_INVARIANT_SET",
                validation="validated REQUIRED_INTERFACE_REUSE invariant",
            ))
            owner_id = next((item.get("obligation_id") for item in obligations if item.get("obligation_type") == PRESERVATION_OBLIGATION and "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER" in set(item.get("structured_relations", []))), None)
            if owner_id:
                raw_bindings.append({
                    "oracle_id": oid, "obligation_id": owner_id,
                    "coverage_relationship": SUPPORTING, "coverage_strength": SUPPORTING_STRENGTH,
                    "mandatory": True, "applicable": True,
                    "semantic_binding": {"validator": "REQUIRED_INTERFACE_REUSE", "interface": item.get("interface")},
                    "evidence_refs": refs,
                })
        dnt_items = _invariant_by_type(execution_invariant_set, invariant.DNT_PRESERVATION)
        if dnt_items:
            item = dnt_items[0]
            oid = "INVARIANT-DNT-PRESERVATION"
            refs = list(item.get("source_evidence_ids", []) or [])
            oracle_records.append(_make_validator_oracle(
                oid, DETERMINISTIC_DNT_VALIDATOR, item.get("path"),
                evidence_refs=refs, authority_source="V25.2_EXECUTION_INVARIANT_SET",
                validation="validated DNT_PRESERVATION invariant",
            ))
            owner_id = next((item.get("obligation_id") for item in obligations if item.get("obligation_type") == PRESERVATION_OBLIGATION and "PRESERVE_OWNERSHIP:PAUSE_STATE_OWNER" in set(item.get("structured_relations", []))), None)
            if owner_id:
                raw_bindings.append({
                    "oracle_id": oid, "obligation_id": owner_id,
                    "coverage_relationship": SUPPORTING, "coverage_strength": SUPPORTING_STRENGTH,
                    "mandatory": True, "applicable": True,
                    "semantic_binding": {"validator": "DNT_PRESERVATION", "path": item.get("path")},
                    "evidence_refs": refs,
                })

    obligation_map = _obligation_map(obligations)
    # Explicit approved bindings are the only route to DIRECT behavior
    # coverage.  A binding without an explicit semantic assertion is retained
    # as an invalid/non-covering audit record rather than upgraded by guessing.
    for raw in list(raw_bindings) + [_copy(item) for item in _as_list(explicit_bindings) if isinstance(item, dict)]:
        oracle_id = _text(raw.get("oracle_id"), 180)
        obligation_id = _text(raw.get("obligation_id"), 180)
        oracle = next((item for item in oracle_records if item.get("oracle_id") == oracle_id), None)
        obligation = obligation_map.get(obligation_id)
        if not isinstance(oracle, dict) or not isinstance(obligation, dict):
            continue
        if not raw.get("evidence_refs"):
            raw["evidence_refs"] = oracle.get("evidence_refs", [])

    # Build derived preservation bindings after explicit records so one oracle
    # may cover two preservation obligations through two separate structural
    # records.  The records are never fanned into one ambiguous obligation.
    for oracle in oracle_records:
        if oracle.get("oracle_type") not in {FOCUSED_TEST, INTEGRATION_TEST}:
            continue
        semantics = semantics_by_oracle.get(oracle.get("oracle_id"), {})
        for obligation in obligations:
            if obligation.get("obligation_type") != PRESERVATION_OBLIGATION:
                continue
            raw_bindings.extend(_structural_preservation_binding(obligation, oracle, semantics))
    # Legacy render assertions are retained as SUPPORTING evidence for the
    # behavior-change obligation.  They establish the old interface only;
    # they can never satisfy its DIRECT requirement.
    for oracle in oracle_records:
        if oracle.get("oracle_type") not in {FOCUSED_TEST, INTEGRATION_TEST}:
            continue
        semantics = semantics_by_oracle.get(oracle.get("oracle_id"), {})
        if not semantics.get("legacy_render_preservation"):
            continue
        for obligation in obligations:
            if obligation.get("obligation_type") != BEHAVIOR_CHANGE:
                continue
            raw_bindings.append({
                "obligation_id": obligation.get("obligation_id"),
                "oracle_id": oracle.get("oracle_id"),
                "coverage_relationship": SUPPORTING,
                "coverage_strength": SUPPORTING_STRENGTH,
                "mandatory": True,
                "applicable": True,
                "semantic_binding": {
                    "structural_relation": "legacy renderStatus assertion proves existing status output only",
                    "called_symbol": "renderStatus",
                    "legacy_outputs": semantics.get("legacy_render_assertions", []),
                },
                "evidence_refs": oracle.get("evidence_refs", []),
            })

    final_bindings: list[dict[str, Any]] = []
    for raw in raw_bindings:
        if not isinstance(raw, dict):
            continue
        oracle_id = _text(raw.get("oracle_id"), 180)
        obligation_id = _text(raw.get("obligation_id"), 180)
        oracle = next((item for item in oracle_records if item.get("oracle_id") == oracle_id), None)
        obligation = obligation_map.get(obligation_id)
        if not isinstance(oracle, dict) or not isinstance(obligation, dict):
            continue
        final_bindings.append(_binding_record(raw, oracle, obligation))
    # Stable fan-in: duplicate logical bindings are one record; separate
    # oracle-to-obligation relationships remain separate records.
    unique_bindings: list[dict[str, Any]] = []
    seen_binding_keys: set[tuple[Any, ...]] = set()
    for binding in final_bindings:
        key = (
            binding.get("obligation_id"), binding.get("oracle_id"),
            binding.get("coverage_relationship"), _json(binding.get("semantic_binding", {})),
        )
        if key in seen_binding_keys:
            continue
        seen_binding_keys.add(key)
        unique_bindings.append(binding)
    obligation_coverage = [_coverage_state(item, unique_bindings) for item in obligations]
    uncovered = [
        {
            "obligation_id": item.get("obligation_id"),
            "requirement_id": item.get("requirement_id"),
            "obligation_type": item.get("obligation_type"),
            "meaning": item.get("meaning"),
            "required_oracle_class": item.get("required_relationship"),
            "required_relationship": item.get("required_relationship"),
            "missing_oracle_ids": [],
            "reason": item.get("reason"),
        }
        for item in obligation_coverage
        if item.get("mandatory") and item.get("coverage_state") != COVERED
    ]
    requirement_coverage = _copy(plan.get("coverage", []))
    status = EXECUTION_VERIFICATION_READY if not uncovered else VERIFICATION_OBLIGATION_UNCOVERED
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "coverage_status": status,
        "verification_ready": status == EXECUTION_VERIFICATION_READY,
        "code": None if status == EXECUTION_VERIFICATION_READY else VERIFICATION_OBLIGATION_UNCOVERED,
        "task_id": task_id,
        "plan_id": _text(plan.get("plan_id"), 180),
        "plan_hash": _text(plan.get("plan_hash"), 100),
        "requirement_ids": _requirement_ids(plan, ledger),
        "requirement_coverage": requirement_coverage,
        "requirement_coverage_digest": canonical_hash(requirement_coverage),
        "atomic_obligations": obligations,
        "obligation_ids": [item.get("obligation_id") for item in obligations],
        "oracle_records": oracle_records[:MAX_ORACLES],
        "verification_oracles": oracle_records[:MAX_ORACLES],
        "coverage_bindings": unique_bindings[:MAX_COVERAGE_BINDINGS],
        "obligation_coverage": obligation_coverage,
        "uncovered_obligations": uncovered,
        "uncovered_obligation_ids": [item.get("obligation_id") for item in uncovered],
        "invented_oracles": [],
        "new_behavior_oracle_count": sum(
            1 for item in unique_bindings
            if item.get("obligation_type") == BEHAVIOR_CHANGE
            and item.get("coverage_relationship") == DIRECT
            and item.get("oracle_type") in {FOCUSED_TEST, INTEGRATION_TEST}
            and item.get("valid")
        ),
        "model_calls": 0,
        "worker_calls": 0,
        "planner_calls": 0,
        "challenger_calls": 0,
        "reviser_calls": 0,
        "repairer_calls": 0,
        "authority_provenance": "APPROVED_VERIFICATION_CONTRACTS_PLUS_DETERMINISTIC_VALIDATORS",
    }
    artifact["coverage_hash"] = canonical_hash(_without(artifact, "coverage_hash"))
    return artifact


def build_verification_obligation_coverage(
    plan: dict[str, Any] | None = None,
    *,
    approved_plan: dict[str, Any] | None = None,
    requirement_obligation_ledger: dict[str, Any] | None = None,
    obligation_ledger: dict[str, Any] | None = None,
    atomic_obligation_ledger: dict[str, Any] | None = None,
    verification_contracts: Any = None,
    approved_verification_contracts: Any = None,
    execution_contract: dict[str, Any] | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
    repository_evidence: Any = None,
    source_root: str | Path | None = None,
    source_files: dict[str, Any] | None = None,
    verification_applicability: Any = None,
    verification_oracles: Any = None,
    oracle_records: Any = None,
    approved_verification_oracles: Any = None,
    coverage_bindings: Any = None,
    verification_obligation_bindings: Any = None,
    task_id: str | None = None,
    **_kwargs: Any,
) -> VerificationObligationCoverage:
    """Build immutable coverage authority from already-approved records.

    The keyword aliases intentionally make the seam usable by Stage 4/5
    adapters without changing their existing record shapes.  Unknown fields
    are ignored; they can never create authority or an oracle.
    """
    value = approved_plan if isinstance(approved_plan, dict) else plan if isinstance(plan, dict) else {}
    supplied_ledger = requirement_obligation_ledger
    if supplied_ledger is None:
        supplied_ledger = obligation_ledger
    if supplied_ledger is None:
        supplied_ledger = atomic_obligation_ledger
    ledger = _ledger_value(value, supplied_ledger)
    obligations = _atomic_obligations(ledger)
    if not obligations:
        raise VerificationObligationCoverageError(
            VERIFICATION_OBLIGATION_COVERAGE_INVALID,
            "approved plan has no atomic requirement obligations",
        )
    contracts = approved_verification_contracts
    if contracts is None:
        contracts = verification_contracts
    if contracts is None:
        contracts = (
            value.get("canonical_verification_contracts")
            or value.get("verification_contracts")
            or []
        )
    task = _text(
        task_id or value.get("task_id")
        or (execution_contract or {}).get("approved_task_id")
        or (execution_invariant_set or {}).get("task_id")
        or "UNKNOWN-TASK",
        180,
    )
    extras = verification_oracles
    if extras is None:
        extras = oracle_records
    if extras is None:
        extras = approved_verification_oracles
    bindings = coverage_bindings
    if bindings is None:
        bindings = verification_obligation_bindings
    artifact = _build_raw_coverage(
        value, ledger, obligations, task_id=task, verification_contracts=contracts,
        execution_contract=execution_contract, execution_invariant_set=execution_invariant_set,
        repository_evidence=repository_evidence, source_root=source_root,
        source_files=source_files, verification_applicability=verification_applicability,
        explicit_oracles=extras, explicit_bindings=bindings,
    )
    checked = validate_verification_obligation_coverage(
        artifact, plan=value, execution_contract=execution_contract,
        execution_invariant_set=execution_invariant_set, source_root=source_root,
        source_files=source_files,
    )
    if not checked.get("valid"):
        raise VerificationObligationCoverageError(
            str(checked.get("code") or VERIFICATION_OBLIGATION_COVERAGE_INVALID),
            "; ".join(checked.get("errors", [])) or "coverage artifact is invalid",
            checked.get("errors", []),
        )
    return _freeze_record(VerificationObligationCoverage, artifact)


def _required_state_for(artifact: dict[str, Any]) -> dict[str, Any]:
    return {
        str(item.get("obligation_id")): item
        for item in _as_list(artifact.get("obligation_coverage"))
        if isinstance(item, dict) and item.get("obligation_id")
    }


def validate_verification_obligation_coverage(
    coverage: VerificationObligationCoverage | dict[str, Any] | None,
    *,
    plan: dict[str, Any] | None = None,
    execution_contract: dict[str, Any] | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
    source_root: str | Path | None = None,
    source_files: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate the artifact and recompute its mandatory readiness decision."""
    value = coverage if isinstance(coverage, dict) else {}
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("coverage schema version is invalid")
    if not _text(value.get("task_id"), 180):
        errors.append("coverage task_id is missing")
    if not _text(value.get("coverage_hash"), 100):
        errors.append("coverage hash is missing")
    elif value.get("coverage_hash") != canonical_hash(_without(value, "coverage_hash")):
        errors.append("coverage hash does not match canonical content")
    try:
        model_calls = int(value.get("model_calls", 0) or 0)
    except (TypeError, ValueError):
        model_calls = -1
    if model_calls != 0:
        errors.append("coverage artifact contains model calls or an invalid model-call count")
    for key in ("worker_calls", "planner_calls", "challenger_calls", "reviser_calls", "repairer_calls"):
        try:
            role_calls = int(value.get(key, 0) or 0)
        except (TypeError, ValueError):
            role_calls = -1
        if role_calls != 0:
            errors.append("coverage artifact contains non-deterministic role calls or an invalid role-call count")
    obligations = [item for item in _as_list(value.get("atomic_obligations")) if isinstance(item, dict)]
    obligation_ids = [str(item.get("obligation_id")) for item in obligations if item.get("obligation_id")]
    if len(obligation_ids) != len(set(obligation_ids)):
        errors.append("atomic obligation IDs are duplicated")
    if len(obligations) > MAX_OBLIGATIONS:
        errors.append("atomic obligation bound exceeded")
    oracle_records = [item for item in _as_list(value.get("oracle_records")) if isinstance(item, dict)]
    if len(oracle_records) > MAX_ORACLES:
        errors.append("verification oracle bound exceeded")
    oracle_ids = [str(item.get("oracle_id")) for item in oracle_records if item.get("oracle_id")]
    if len(oracle_ids) != len(set(oracle_ids)):
        errors.append("verification oracle IDs are duplicated")
    if any(item.get("oracle_type") not in ORACLE_TYPES for item in oracle_records):
        errors.append("verification oracle type is outside the approved taxonomy")
    mutable_targets = {
        _path(item)
        for item in _as_list((execution_contract or {}).get("allowed_mutation_paths"))
        if _path(item)
    }
    mutable_targets = {item.casefold() for item in mutable_targets}
    if source_root is not None:
        for oracle in oracle_records:
            target = _path(oracle.get("target"))
            expected_hash = _text(oracle.get("source_hash"), 100)
            if (
                not target
                or oracle.get("target_status") != RESOLVED
                or not expected_hash
                or (
                    oracle.get("oracle_type") == SYNTAX_CHECK
                    and target.casefold() in mutable_targets
                )
            ):
                continue
            current_source, current_status = _read_source(
                target, source_root, source_files,
            )
            if current_status != RESOLVED:
                errors.append(f"verification oracle target became unresolved: {target}")
            elif _sha256_source(current_source).casefold() != expected_hash.casefold():
                errors.append(f"verification oracle evidence became stale: {target}")
    bindings = [item for item in _as_list(value.get("coverage_bindings")) if isinstance(item, dict)]
    if len(bindings) > MAX_COVERAGE_BINDINGS:
        errors.append("coverage binding bound exceeded")
    known_obligations = set(obligation_ids)
    known_oracles = set(oracle_ids)
    for item in bindings:
        if item.get("obligation_id") not in known_obligations:
            errors.append("coverage binding references an unknown obligation")
        if item.get("oracle_id") not in known_oracles:
            errors.append("coverage binding references an unknown oracle")
        if item.get("coverage_relationship") not in COVERAGE_RELATIONSHIPS:
            errors.append("coverage binding relationship is invalid")
        if item.get("coverage_strength") not in COVERAGE_STRENGTHS:
            errors.append("coverage binding strength is invalid")
        if (
            item.get("valid") is True
            and item.get("coverage_relationship") == DIRECT
            and item.get("obligation_type") == BEHAVIOR_CHANGE
        ):
            if (
                item.get("oracle_type") not in {FOCUSED_TEST, INTEGRATION_TEST}
                or not _direct_behavior_assertion(item)
            ):
                errors.append(
                    "behavior DIRECT binding lacks an approved focused/integration "
                    "oracle with explicit observable semantic evidence"
                )
        if item.get("valid") is True and not (
            item.get("approved") is True
            and item.get("applicable") is True
            and item.get("target_status") == RESOLVED
        ):
            errors.append("valid coverage binding is not approved, applicable, and resolved")
    states = _required_state_for(value)
    if set(states) != set(obligation_ids):
        errors.append("obligation coverage state does not match atomic obligation set")
    computed_uncovered = [
        item.get("obligation_id") for item in states.values()
        if item.get("mandatory") and item.get("coverage_state") != COVERED
    ]
    stored_uncovered = [str(item) for item in value.get("uncovered_obligation_ids", []) or []]
    if computed_uncovered != stored_uncovered:
        errors.append("uncovered obligation list does not match coverage states")
    expected_status = EXECUTION_VERIFICATION_READY if not computed_uncovered else VERIFICATION_OBLIGATION_UNCOVERED
    if value.get("status") != expected_status or value.get("coverage_status") != expected_status:
        errors.append("coverage readiness status does not match mandatory coverage")
    if bool(value.get("verification_ready")) != (expected_status == EXECUTION_VERIFICATION_READY):
        errors.append("verification_ready does not match coverage status")
    if plan is not None:
        expected_plan_id = _text(plan.get("plan_id"), 180)
        expected_plan_hash = _text(plan.get("plan_hash"), 100)
        if expected_plan_id and value.get("plan_id") != expected_plan_id:
            errors.append("coverage plan_id does not match approved plan")
        if expected_plan_hash and value.get("plan_hash") != expected_plan_hash:
            errors.append("coverage plan_hash does not match approved plan")
        expected_ledger = _ledger_value(plan, None)
        expected_ids = {item.get("obligation_id") for item in _atomic_obligations(expected_ledger)}
        if expected_ids and set(obligation_ids) != expected_ids:
            errors.append("coverage atomic obligations do not match approved plan ledger")
    if execution_contract is not None:
        bound_hash = execution_contract.get("verification_obligation_coverage_hash")
        bound_status = execution_contract.get("verification_obligation_coverage_status")
        if bound_hash not in (None, "") and bound_hash != value.get("coverage_hash"):
            errors.append("coverage does not match execution contract hash")
        if bound_status not in (None, "") and bound_status != value.get("coverage_status"):
            errors.append("coverage does not match execution contract status")
    if execution_invariant_set is not None and source_root is not None:
        check = invariant.validate_execution_invariant_set(
            execution_invariant_set, execution_contract=execution_contract,
            source_root=source_root, require_current_subject=True,
        )
        if not check.get("valid"):
            errors.append("bound execution invariant set is not valid/current")
    return {
        "valid": not errors,
        "status": value.get("status") if not errors else VERIFICATION_OBLIGATION_COVERAGE_INVALID,
        "code": None if not errors else VERIFICATION_OBLIGATION_COVERAGE_INVALID,
        "errors": errors[:40],
        "coverage_hash": value.get("coverage_hash"),
        "verification_ready": value.get("verification_ready") is True and not errors,
        "uncovered_obligation_ids": stored_uncovered,
    }


def canonical_verification_obligation_coverage_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_without(value, "coverage_hash"))


canonical_coverage_hash = canonical_verification_obligation_coverage_hash
build_verification_coverage = build_verification_obligation_coverage
validate_verification_coverage = validate_verification_obligation_coverage


def coverage_is_ready(value: dict[str, Any] | None) -> bool:
    return isinstance(value, dict) and value.get("status") == EXECUTION_VERIFICATION_READY and value.get("verification_ready") is True


def coverage_summary(value: dict[str, Any] | None) -> dict[str, Any]:
    artifact = value if isinstance(value, dict) else {}
    return {
        "status": artifact.get("status"),
        "coverage_hash": artifact.get("coverage_hash"),
        "obligation_count": len(_as_list(artifact.get("atomic_obligations"))),
        "covered_obligation_ids": [
            item.get("obligation_id") for item in _as_list(artifact.get("obligation_coverage"))
            if isinstance(item, dict) and item.get("coverage_state") == COVERED
        ],
        "uncovered_obligation_ids": list(artifact.get("uncovered_obligation_ids", []) or []),
        "direct_behavior_oracle_count": int(artifact.get("new_behavior_oracle_count", 0) or 0),
        "model_calls": int(artifact.get("model_calls", 0) or 0),
        "worker_calls": int(artifact.get("worker_calls", 0) or 0),
    }


__all__ = [
    "VerificationObligationCoverage", "VerificationObligationCoverageError",
    "SCHEMA_VERSION", "EXECUTION_VERIFICATION_READY",
    "VERIFICATION_OBLIGATION_UNCOVERED", "VERIFICATION_OBLIGATION_COVERAGE_INVALID",
    "VERIFICATION_OBLIGATION_COVERAGE_REQUIRED", "VERIFICATION_OBLIGATION_COVERAGE_MISMATCH",
    "FOCUSED_TEST", "INTEGRATION_TEST", "SYNTAX_CHECK",
    "DETERMINISTIC_AUTHORITY_VALIDATOR", "DETERMINISTIC_DNT_VALIDATOR",
    "DETERMINISTIC_INTERFACE_VALIDATOR", "DETERMINISTIC_STATE_VALIDATOR",
    "ORACLE_TYPES", "DIRECT", "PRESERVATION", "SUPPORTING", "NOT_COVERING",
    "COVERAGE_RELATIONSHIPS", "STRONG", "SUPPORTING_STRENGTH", "WEAK",
    "COVERED", "UNCOVERED", "NOT_APPLICABLE", "RESOLVED", "UNRESOLVED", "STALE",
    "build_verification_obligation_coverage", "build_verification_coverage",
    "validate_verification_obligation_coverage", "validate_verification_coverage",
    "canonical_hash", "canonical_coverage_hash", "canonical_verification_obligation_coverage_hash",
    "coverage_is_ready", "coverage_summary",
]
