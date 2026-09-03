"""Deterministic, contract-local verification applicability and aggregation.

Stage 5A deliberately keeps this module independent from the model client and
from the browser executor.  It answers two different questions for a bounded
child responsibility:

* is a verification mechanism applicable to this child and repository?
* is that mechanism required by this child contract?

The module returns ordinary dictionaries so the existing run ledger can retain
the artifact without changing the Stage 4 authority objects.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Iterable


FOCUSED_TEST = "FOCUSED_TEST"
SYNTAX_STATIC_GATE = "SYNTAX_STATIC_GATE"
BROWSER = "BROWSER"

# Route authority is deliberately separate from the legacy ``kind`` field.
# ``kind`` remains compatible with the existing Stage 5 aggregator, while the
# fields below make the execution authority and resolution decision explicit.
APPROVED_VERIFICATION_CONTRACT = "APPROVED_VERIFICATION_CONTRACT"
APPROVED_FOCUSED_TEST = "APPROVED_FOCUSED_TEST"
DIRECT_ORACLE = "DIRECT_ORACLE"
DETERMINISTIC_SYSTEM_SAFETY_CHECK = "DETERMINISTIC_SYSTEM_SAFETY_CHECK"
OPTIONAL_CAPABILITY = "OPTIONAL_CAPABILITY"
STAGE5A_COMMAND = "STAGE5A_COMMAND"
DIRECT_ORACLE_EXECUTION = "DIRECT_ORACLE_EXECUTION"

EXACT_APPROVED_TARGET = "EXACT_APPROVED_TARGET"
DETERMINISTIC_CONTRACT_TARGET = "DETERMINISTIC_CONTRACT_TARGET"
DETERMINISTIC_SYSTEM_TARGET = "DETERMINISTIC_SYSTEM_TARGET"
SUPPORTED_TARGET_DISCOVERY = "SUPPORTED_TARGET_DISCOVERY"
UNRESOLVED = "UNRESOLVED"

PASS = "PASS"
FAIL = "FAIL"
PENDING = "PENDING"
SKIPPED_NOT_APPLICABLE = "SKIPPED_NOT_APPLICABLE"
BLOCKED_REQUIRED_TARGET_MISSING = "BLOCKED_REQUIRED_TARGET_MISSING"
VERIFICATION_EVIDENCE_UNAVAILABLE = "VERIFICATION_EVIDENCE_UNAVAILABLE"
VERIFICATION_TARGET_UNRESOLVED = "VERIFICATION_TARGET_UNRESOLVED"
REQUIRED_VERIFICATION_TARGET_UNRESOLVED = "REQUIRED_VERIFICATION_TARGET_UNRESOLVED"

SUPPORTED_TARGET_PRESENT = "SUPPORTED_TARGET_PRESENT"
NO_SUPPORTED_BROWSER_TARGET = "NO_SUPPORTED_BROWSER_TARGET"
EXPLICIT_BROWSER_REQUIREMENT = "EXPLICIT_BROWSER_REQUIREMENT"
FOCUSED_TEST_PRESENT = "FOCUSED_TEST_PRESENT"
CONTRACT_REQUIRES_TEST = "CONTRACT_REQUIRES_TEST"
VERIFIER_NOT_REQUIRED = "VERIFIER_NOT_REQUIRED"
SUPPORTED_SOURCE_PRESENT = "SUPPORTED_SOURCE_PRESENT"
CONTRACT_REQUIRES_SYNTAX = "CONTRACT_REQUIRES_SYNTAX"
AMBIGUOUS_SUPPORTED_TARGET = "AMBIGUOUS_SUPPORTED_TARGET"
TEST_TARGET_PRESENT = "TEST_TARGET_PRESENT"

_HTML_SUFFIXES = frozenset({".html", ".htm"})
_SOURCE_SUFFIXES = frozenset({
    ".c", ".cc", ".cpp", ".cxx", ".css", ".go", ".html", ".htm", ".java",
    ".js", ".jsx", ".mjs", ".cjs", ".json", ".py", ".rs", ".ts", ".tsx",
    ".toml", ".yaml", ".yml",
})
_TEST_MARKERS = re.compile(
    r"(?:^|[\\/_.-])(?:test|tests|spec|specs)(?:[\\/_.-]|$)|\b(?:pytest|unittest|jest|vitest|mocha|focused test|test suite)\b",
    re.IGNORECASE,
)
_BROWSER_REQUIREMENT_PATTERNS = (
    re.compile(r"\bbrowser(?:[- ]?(?:visible|rendered|ui|verification|check|behavior))?\b", re.I),
    re.compile(r"\b(?:web app|web application|web page|frontend|front-end|html|dom|playwright|chromium|canvas|webgl)\b", re.I),
    re.compile(r"\buser interface\b|\bui behavior\b|\bui verification\b|\brender(?:ed|ing)? in (?:the )?browser\b", re.I),
    re.compile(r"\b(?:responsive layout|responsive ui|touch control|visible countdown|visible clock)\b", re.I),
    re.compile(r"\b(?:game|timer|countdown|pomodoro)\b", re.I),
)
_EXPLICIT_BROWSER_PATTERNS = (
    re.compile(r"\bbrowser(?:[- ]?(?:visible|rendered|ui|verification|check|behavior))?\b", re.I),
    re.compile(r"\b(?:web app|web application|web page|frontend|front-end|html|dom|playwright|chromium|canvas|webgl)\b", re.I),
    re.compile(r"\buser interface\b|\bui behavior\b|\bui verification\b|\brender(?:ed|ing)? in (?:the )?browser\b", re.I),
    re.compile(r"\b(?:responsive layout|responsive ui|touch control|visible countdown|visible clock)\b", re.I),
)

_MAX_ROUTES = 3
_MAX_FILES = 120
_MAX_REFS = 12
_MAX_REASON_CODES = 6
_MAX_TEXT = 260
_SYNTAX_EVIDENCE_MARKERS = re.compile(
    r"(?:--check|\b(?:py_compile|compileall|syntax(?:\s+check)?|static(?:\s+check)?|lint|typecheck)\b)",
    re.IGNORECASE,
)


class VerificationRouteBinding(dict):
    """Mutable, JSON-safe canonical binding for one Stage 5A route.

    The class intentionally adds no behavior to ``dict``.  It is a named
    shape for callers and keeps old route consumers compatible with ordinary
    dictionaries while making authority metadata impossible to confuse with
    generic capability discovery.
    """


def _route_identity(value: dict[str, Any]) -> dict[str, Any]:
    """Return only the stable fields that define route identity."""
    command_identity = value.get("command_identity")
    if not command_identity:
        command_identity = value.get("command_spec_identity") or value.get("command")
    if not command_identity:
        command_identity = value.get("oracle_spec_identity")
    return {
        "authority_id": str(value.get("authority_id") or value.get("verification_id") or ""),
        "authority_type": str(value.get("authority_type") or ""),
        "authority_source": str(value.get("authority_source") or ""),
        "kind": str(value.get("kind") or ""),
        "route_type": str(value.get("route_type") or value.get("kind") or ""),
        "execution_channel": str(value.get("execution_channel") or ""),
        "target": _path(value.get("target")) if value.get("target") else None,
        "command": str(value.get("command") or ""),
        "command_identity": str(command_identity or ""),
        "required": bool(value.get("required")),
        "applicable": bool(value.get("applicable")),
        "resolution_mode": str(value.get("resolution_mode") or ""),
    }


def canonical_route_hash(route: dict[str, Any] | None) -> str:
    """Hash the stable authority/target/command identity of a route."""
    return _json_hash(_route_identity(route if isinstance(route, dict) else {}))


def _copy_route_list(value: Any, limit: int = _MAX_REFS) -> list[str]:
    result: list[str] = []
    for item in _as_list(value):
        text = _compact(item, 180)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _compact(value: Any, limit: int = _MAX_TEXT) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _strings(value: Any, limit: int = 12) -> list[str]:
    result = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("text") or item.get("path") or item.get("fact") or ""
        text = _compact(item)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _path(value: Any) -> str:
    return str(value or "").replace("\\", "/").lstrip("./")


def _is_test_path(value: Any) -> bool:
    path = _path(value)
    name = Path(path).name.casefold()
    parts = {part.casefold() for part in Path(path).parts}
    return "tests" in parts or "test" in parts or name.startswith("test_") or ".test." in name or ".spec." in name


def _is_source_path(value: Any) -> bool:
    return Path(_path(value)).suffix.casefold() in _SOURCE_SUFFIXES


def _is_html_path(value: Any) -> bool:
    return Path(_path(value)).suffix.casefold() in _HTML_SUFFIXES


def _unique_paths(values: Iterable[Any], limit: int = _MAX_FILES) -> list[str]:
    result = []
    seen = set()
    for raw in values:
        value = _path(raw)
        if not value or value.casefold() in seen:
            continue
        seen.add(value.casefold())
        result.append(value)
        if len(result) >= limit:
            break
    return result


def _json_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def deterministic_hash(value: Any) -> str:
    """Return the stable metadata hash used by route artifacts."""
    return _json_hash(value)


def _child_contract(task: dict, contract: dict) -> tuple[dict, bool]:
    nested = task.get("execution_contract_child") if isinstance(task, dict) else None
    if isinstance(nested, dict):
        return nested, True
    if isinstance(contract, dict):
        return contract, False
    return {}, False


def _local_test_contract(task: dict, source: dict, has_child: bool) -> list[str]:
    """Select test obligations without copying a broad parent into siblings."""
    explicit = task.get("local_test_contract") or task.get("test_contract")
    if explicit:
        return _strings(explicit)
    if has_child:
        # Stage 4 child projections currently inherit the immutable parent
        # ``test_contract`` field.  Treat it as local only when the child is a
        # test responsibility or its own completion/scope explicitly names a
        # test.  This keeps input/view siblings from receiving identical test
        # obligations merely because they share a parent contract.
        child_paths = _strings(source.get("allowed_mutation_paths")) + _strings(task.get("scope_hint"))
        child_text = " ".join(_strings(task.get("goal")) + _strings(task.get("done_when")))
        responsibility = str(source.get("responsibility_type", "")).casefold()
        if responsibility not in {"test_mutation", "test", "test_change"} and not (
            any(_is_test_path(item) for item in child_paths) or _TEST_MARKERS.search(child_text)
        ):
            return []
    return _strings(source.get("local_test_contract") or source.get("test_contract"))


def _source_facts(repository_snapshot: dict | None, repository_evidence: Any, workspace: str | os.PathLike | None) -> dict:
    snapshot = repository_snapshot if isinstance(repository_snapshot, dict) else {}
    files = []
    for item in _as_list(snapshot.get("files")):
        files.append(item.get("path") if isinstance(item, dict) else item)
    tests = _strings(snapshot.get("tests"), _MAX_FILES)
    entrypoints = [
        item for item in _strings(snapshot.get("entrypoints"), _MAX_FILES)
        if _is_html_path(item)
    ]
    evidence = _as_list(repository_evidence)
    if isinstance(repository_evidence, dict):
        evidence = [repository_evidence]
    for item in evidence:
        if not isinstance(item, dict):
            continue
        value = item.get("path") or item.get("target") or item.get("entrypoint")
        if value:
            files.append(value)
            if _is_test_path(value):
                tests.append(_path(value))
            if _is_html_path(value):
                entrypoints.append(_path(value))
    root = Path(workspace).resolve() if workspace else None
    if root and root.is_dir():
        try:
            for current, dirs, names in os.walk(root):
                dirs[:] = sorted(name for name in dirs if name not in {".git", ".hivo", ".agent_runs", "node_modules", "__pycache__"})
                for name in sorted(names):
                    candidate = Path(current) / name
                    try:
                        relative = candidate.relative_to(root).as_posix()
                    except ValueError:
                        continue
                    if relative.startswith((".agent_", ".hivo/")):
                        continue
                    files.append(relative)
                    if _is_test_path(relative):
                        tests.append(relative)
                    if _is_html_path(relative):
                        entrypoints.append(relative)
                    if len(files) >= _MAX_FILES:
                        break
                if len(files) >= _MAX_FILES:
                    break
        except OSError:
            pass
    files = _unique_paths(files)
    tests = _unique_paths(tests)
    entrypoints = _unique_paths(entrypoints)
    return {"files": files, "tests": tests, "entrypoints": entrypoints}


def _references_from_text(text: str, candidates: list[str]) -> list[str]:
    lower = text.casefold()
    return [candidate for candidate in candidates if candidate.casefold() in lower]


def _positive_browser_text(text: str) -> str:
    """Remove explicit negative browser phrases before signal matching."""
    return re.sub(
        r"\b(?:non[- ]browser|non[- ]web|no\s+(?:browser|web|html)(?:\s+(?:entrypoint|target|verification|check|testing))?|without\s+browser|not\s+(?:a\s+)?browser|(?:browser|web|ui)(?:\s+(?:verification|check|testing))?\s+(?:is\s+)?not\s+(?:required|needed|applicable))\b",
        " ", str(text or ""), flags=re.IGNORECASE,
    )


def _default_browser_resolution(workspace: str | os.PathLike | None, evidence: dict) -> dict:
    """Small fallback resolver used outside mini.py; production passes V8's resolver."""
    root = Path(workspace).resolve() if workspace else None
    facts = evidence.get("repository_facts", {}) if isinstance(evidence, dict) else {}
    candidates = _unique_paths(
        item for item in facts.get("entrypoints", []) if _is_html_path(item)
    )
    if root and root.is_dir():
        candidates = []
        try:
            for current, dirs, names in os.walk(root):
                dirs[:] = sorted(name for name in dirs if name not in {".git", ".hivo", ".agent_runs", "node_modules", "__pycache__"})
                for name in sorted(names):
                    if Path(name).suffix.casefold() not in _HTML_SUFFIXES:
                        continue
                    path = Path(current) / name
                    try:
                        candidates.append(path.relative_to(root).as_posix())
                    except ValueError:
                        continue
                    if len(candidates) >= _MAX_FILES:
                        break
                if len(candidates) >= _MAX_FILES:
                    break
        except OSError:
            pass
    candidates = _unique_paths(candidates)
    requested = _path(evidence.get("requested_from_node"))
    if requested and _is_html_path(requested):
        if (root and (root / requested).is_file()) or requested in candidates:
            return {"resolution_status": "RESOLVED", "resolution_source": "requested_html", "resolved_entrypoint": requested}
    if requested and not _is_html_path(requested):
        matches = []
        for html in candidates:
            if not root:
                continue
            try:
                content = (root / html).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if re.search(r"(?:src|href)\s*=\s*['\"][^'\"]*" + re.escape(requested) + r"['\"]", content, re.I):
                matches.append(html)
        if len(matches) == 1:
            return {"resolution_status": "RESOLVED", "resolution_source": "asset_reference", "resolved_entrypoint": matches[0]}
        if len(matches) > 1:
            return {"resolution_status": VERIFICATION_TARGET_UNRESOLVED, "resolution_source": "ambiguous_asset_references", "resolved_entrypoint": None, "candidates": matches[:8]}
    root_html = [item for item in candidates if "/" not in item]
    if len(root_html) == 1:
        return {"resolution_status": "RESOLVED", "resolution_source": "unique_root_html", "resolved_entrypoint": root_html[0]}
    if "index.html" in {item.casefold() for item in candidates}:
        selected = next(item for item in candidates if item.casefold() == "index.html")
        return {"resolution_status": "RESOLVED", "resolution_source": "conventional_index_html", "resolved_entrypoint": selected}
    return {
        "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
        "resolution_source": "ambiguous_html_candidates" if candidates else "missing_html_entrypoint",
        "resolved_entrypoint": None,
        "candidates": candidates[:8],
    }


def _resolve_browser_target(
    workspace: str | os.PathLike | None,
    evidence: dict,
    resolver: Callable[[Any, dict], Any] | None,
) -> dict:
    try:
        raw = resolver(workspace, evidence) if resolver else _default_browser_resolution(workspace, evidence)
    except Exception as exc:  # a resolver failure is conservative, not a model route
        return {
            "resolution_status": VERIFICATION_TARGET_UNRESOLVED,
            "resolution_source": "resolver_error",
            "resolved_entrypoint": None,
            "resolver_error": _compact(exc),
        }
    if isinstance(raw, str):
        if raw == VERIFICATION_TARGET_UNRESOLVED:
            return {"resolution_status": VERIFICATION_TARGET_UNRESOLVED, "resolution_source": "resolver", "resolved_entrypoint": None}
        return {"resolution_status": "RESOLVED", "resolution_source": "resolver", "resolved_entrypoint": _path(raw)}
    if not isinstance(raw, dict):
        return {"resolution_status": VERIFICATION_TARGET_UNRESOLVED, "resolution_source": "invalid_resolver_result", "resolved_entrypoint": None}
    details = dict(raw)
    resolved = details.get("resolved_entrypoint")
    details["resolved_entrypoint"] = _path(resolved) if resolved else None
    details.setdefault("resolution_status", "RESOLVED" if details.get("resolved_entrypoint") else VERIFICATION_TARGET_UNRESOLVED)
    details.setdefault("resolution_source", "resolver")
    return details


def _route(kind: str, required: bool, applicable: bool, target: str | None, reason_codes: Iterable[str], evidence_refs: Iterable[str], result: str = PENDING, **extra: Any) -> dict:
    value = {
        "kind": kind,
        "required": bool(required),
        "applicable": bool(applicable),
        "target": _path(target) if target else None,
        "reason_codes": list(dict.fromkeys(str(item) for item in reason_codes if item))[:_MAX_REASON_CODES],
        "evidence_refs": list(dict.fromkeys(str(item) for item in evidence_refs if item))[:_MAX_REFS],
        "result": result,
    }
    value.update(extra)
    return value


def _authority_id(authority: dict[str, Any] | None) -> str:
    value = authority if isinstance(authority, dict) else {}
    return str(value.get("verification_id") or value.get("oracle_id") or "")


def is_direct_oracle_authority(authority: dict[str, Any] | None) -> bool:
    """Recognize the plan-owned direct oracle without relying on oracle_type."""
    value = authority if isinstance(authority, dict) else {}
    route_type = str(value.get("route_type") or "").casefold()
    authority_type = str(value.get("authority_type") or "").casefold()
    authority_source = str(value.get("authority_source") or "").casefold()
    return bool(
        route_type == DIRECT_ORACLE.casefold()
        or authority_type == DIRECT_ORACLE.casefold()
        or value.get("oracle_id")
        or value.get("oracle_hash")
        or authority_source in {"hivo_verifier", "direct_oracle"}
    )


def _path_values(value: Any) -> list[str]:
    values: list[str] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            item = item.get("path") or item.get("target") or item.get("file")
        if isinstance(item, (str, os.PathLike)):
            candidate = _path(item)
            if candidate and _is_source_path(candidate):
                values.append(candidate)
    return values


def _authority_target_candidates(
    authority: dict[str, Any] | None,
    test_files: Iterable[str] | None = None,
    *,
    direct: bool | None = None,
) -> tuple[list[str], bool]:
    """Return structurally named authority targets and whether they are upstream."""
    value = authority if isinstance(authority, dict) else {}
    direct = is_direct_oracle_authority(value) if direct is None else bool(direct)
    candidates: list[str] = []
    explicit_keys = (
        "target", "approved_target", "test_target", "test_path",
        "requested_target", "target_path", "target_module_path", "oracle_target",
    )
    collection_keys = ("targets", "approved_targets", "paths", "target_paths")
    for key in explicit_keys + collection_keys:
        candidates.extend(_path_values(value.get(key)))
    # Direct oracles own their module target.  They never fall through to
    # test-file discovery, even when their oracle_type happens to be
    # FOCUSED_TEST.
    if direct:
        return _unique_paths(candidates), bool(candidates)
    test_values = _unique_paths(test_files or [])
    for text in _strings(value.get("contract")):
        candidates.extend(
            path for path in test_values
            if path.casefold() in text.casefold()
        )
    return _unique_paths(candidates), bool(candidates)


def build_verification_route_binding(
    route: dict[str, Any] | None,
    *,
    authority: dict[str, Any] | None = None,
    authority_id: str | None = None,
    authority_type: str | None = None,
    authority_source: str | None = None,
    authority_provenance: Any = None,
    route_type: str | None = None,
    execution_channel: str | None = None,
    resolution_mode: str | None = None,
    candidate_targets: Iterable[Any] | None = None,
    selected_target: str | None = None,
    approved_target: str | None = None,
    command: str | None = None,
    command_identity: str | None = None,
    provenance_refs: Iterable[Any] | None = None,
    responsibility_key: str | None = None,
) -> VerificationRouteBinding:
    """Enrich a compatible route with immutable-authority routing metadata."""
    value = dict(route) if isinstance(route, dict) else {}
    record = authority if isinstance(authority, dict) else {}
    direct = is_direct_oracle_authority(record) if record else (
        str(route_type or "").casefold() == DIRECT_ORACLE.casefold()
    )
    resolved_authority_id = str(
        authority_id or _authority_id(record) or value.get("authority_id") or ""
    )
    if not authority_type:
        authority_type = (
            DIRECT_ORACLE if direct else APPROVED_VERIFICATION_CONTRACT
        ) if record else value.get("authority_type")
    if not authority_source:
        authority_source = (
            str(record.get("authority_source") or "HIVO_VERIFIER")
            if direct and record else
            str(record.get("authority_source") or APPROVED_VERIFICATION_CONTRACT)
            if record else str(value.get("authority_source") or "")
        )
    if authority_provenance is None and record:
        authority_provenance = record.get("provenance") or record.get("authority_provenance")
    if not route_type:
        route_type = DIRECT_ORACLE if direct else value.get("kind")
    if not execution_channel:
        execution_channel = DIRECT_ORACLE_EXECUTION if direct else STAGE5A_COMMAND
    if not resolution_mode:
        resolution_mode = value.get("resolution_mode") or UNRESOLVED
    if command is not None:
        value["command"] = str(command)
    if command_identity is None:
        command_identity = value.get("command_identity") or value.get("command_spec_identity")
    if command_identity is None and value.get("command"):
        command_identity = value.get("command")
    if command_identity is None and direct:
        command_identity = "oracle:%s:%s" % (
            str(record.get("oracle_id") or resolved_authority_id),
            str(record.get("oracle_hash") or ""),
        )
    if command_identity is None:
        target = _path(selected_target or value.get("target"))
        suffix = Path(target).suffix.casefold()
        if value.get("kind") == FOCUSED_TEST:
            command_identity = (
                f"node {target}" if suffix in {".js", ".mjs", ".cjs"}
                else f"python {target}" if suffix == ".py"
                else f"run {target}"
            ) if target else ""
        else:
            command_identity = f"{value.get('kind') or route_type}:{target}"
    if candidate_targets is None:
        candidate_targets = value.get("candidate_targets") or value.get("candidates") or []
    candidates = _unique_paths(candidate_targets)
    selected = _path(selected_target or value.get("selected_target") or value.get("target")) or None
    approved = _path(approved_target or value.get("approved_target")) or None
    if approved and approved not in candidates:
        candidates = _unique_paths(list(candidates) + [approved])
    refs = _copy_route_list(
        list(value.get("provenance_refs", []) or [])
        + list(provenance_refs or [])
    )
    authority_refs = _copy_route_list(record.get("evidence_ids", [])) if record else []
    if authority_refs:
        refs = _copy_route_list(refs + [f"authority:{item}" for item in authority_refs])
    value.update({
        "verification_id": record.get("verification_id") if record else value.get("verification_id"),
        "oracle_id": record.get("oracle_id") if record else value.get("oracle_id"),
        "authority_id": resolved_authority_id or None,
        "authority_type": authority_type,
        "authority_source": authority_source or None,
        "authority_provenance": authority_provenance,
        "route_type": route_type,
        "execution_channel": execution_channel,
        "resolution_mode": resolution_mode,
        "candidate_targets": candidates,
        "selected_target": selected,
        "approved_target": approved,
        "command_identity": str(command_identity or ""),
        "provenance_refs": refs,
        "authority_ids": _copy_route_list(
            list(value.get("authority_ids", []) or [])
            + ([resolved_authority_id] if resolved_authority_id else [])
        ),
        "responsibility_key": responsibility_key or value.get("responsibility_key") or (
            f"{resolved_authority_id}:{route_type}" if resolved_authority_id else f"{route_type}"
        ),
    })
    # A binding is allowed to have no target only when it explicitly carries
    # the fail-closed unresolved mode.  Validation enforces the authority
    # rules; hashing remains useful for both resolved and unresolved cards.
    route_hash = canonical_route_hash(value)
    value["canonical_hash"] = route_hash
    value["route_id"] = "ROUTE-" + route_hash[:24].upper()
    return VerificationRouteBinding(value)


def _route_semantic_key(route: dict[str, Any]) -> tuple[str, ...]:
    command_identity = route.get("command_identity") or route.get("command_spec_identity") or route.get("command") or ""
    return (
        str(route.get("responsibility_key") or route.get("kind") or ""),
        str(route.get("route_type") or route.get("kind") or ""),
        _path(route.get("target")) if route.get("target") else "",
        str(command_identity),
    )


def deduplicate_verification_routes(
    routes: Iterable[dict[str, Any]] | None,
) -> list[VerificationRouteBinding | dict[str, Any]]:
    """Fan in identical semantic routes while preserving all provenance refs."""
    result: list[VerificationRouteBinding | dict[str, Any]] = []
    positions: dict[tuple[str, ...], int] = {}
    for raw in routes or []:
        if not isinstance(raw, dict):
            continue
        route = dict(raw)
        key = _route_semantic_key(route)
        if key not in positions:
            result.append(route)
            positions[key] = len(result) - 1
            continue
        index = positions[key]
        existing = dict(result[index])
        # Exact authority wins over discovery for the same semantic route.
        modes = {str(existing.get("resolution_mode") or ""), str(route.get("resolution_mode") or "")}
        if EXACT_APPROVED_TARGET in modes and existing.get("resolution_mode") != EXACT_APPROVED_TARGET:
            base = dict(route)
            base["result"] = existing.get("result", route.get("result", PENDING))
            existing = base
        elif existing.get("resolution_mode") != EXACT_APPROVED_TARGET and route.get("resolution_mode") == EXACT_APPROVED_TARGET:
            base = dict(route)
            base["result"] = existing.get("result", route.get("result", PENDING))
            existing = base
        for field in ("evidence_refs", "provenance_refs", "candidate_targets", "authority_ids", "source_verification_contract_ids"):
            merged = _copy_route_list(
                list(existing.get(field, []) or []) + list(route.get(field, []) or [])
            )
            if merged:
                existing[field] = merged
        for field in ("authority_id", "authority_type", "authority_source", "authority_provenance"):
            if route.get(field) and existing.get(field) != route.get(field):
                existing.setdefault("merged_" + field + "s", [])
                existing["merged_" + field + "s"] = _copy_route_list(
                    list(existing.get("merged_" + field + "s", []) or [])
                    + [existing.get(field), route.get(field)]
                )
        result[index] = existing
    return result


def validate_verification_route_bindings(
    routes_or_artifact: Any,
    *,
    approved_authorities: Iterable[dict[str, Any]] | None = None,
    deterministic_system_authorities: Iterable[Any] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate authority, target precedence, expansion, and route hashes."""
    if isinstance(routes_or_artifact, dict):
        routes = routes_or_artifact.get("verification_route_bindings")
        if not isinstance(routes, list):
            routes = routes_or_artifact.get("verification_routes", [])
    else:
        routes = routes_or_artifact or []
    approved_map = {
        _authority_id(item): item for item in (approved_authorities or [])
        if isinstance(item, dict) and _authority_id(item)
    }
    if isinstance(deterministic_system_authorities, dict):
        system_ids = {str(key) for key in deterministic_system_authorities}
    else:
        system_ids = {str(item) for item in (deterministic_system_authorities or [])}
    errors: list[str] = []
    seen: set[tuple[str, ...]] = set()
    mandatory_count = 0
    for index, route in enumerate(routes if isinstance(routes, list) else []):
        if not isinstance(route, dict):
            errors.append(f"route[{index}] is not an object")
            continue
        expected_hash = canonical_route_hash(route)
        if route.get("canonical_hash") != expected_hash:
            errors.append(f"route[{index}] canonical hash is invalid")
        if route.get("required") is not True:
            continue
        mandatory_count += 1
        authority_id = str(route.get("authority_id") or "")
        authority_type = str(route.get("authority_type") or "")
        authority_source = str(route.get("authority_source") or "")
        if not authority_id or not authority_source:
            errors.append(f"route[{index}] mandatory route has no authority provenance")
        known_system = authority_id in system_ids or authority_type == DETERMINISTIC_SYSTEM_SAFETY_CHECK
        authority = approved_map.get(authority_id)
        if not known_system and authority is None:
            errors.append(f"route[{index}] authority {authority_id or '<missing>'} is not approved")
        if authority is not None:
            explicit_targets = _authority_target_candidates(
                authority, route.get("candidate_targets", []),
            )[0]
            upstream_exists = bool(
                route.get("upstream_target_exists")
                or route.get("approved_target")
                or route.get("target_identity_upstream")
            )
            if route.get("resolution_mode") == EXACT_APPROVED_TARGET:
                approved_target = _path(route.get("approved_target") or route.get("target"))
                if not approved_target or (explicit_targets and approved_target not in explicit_targets):
                    errors.append(f"route[{index}] exact approved target does not match authority")
            if route.get("target") is None and upstream_exists:
                errors.append(f"route[{index}] dropped an exact approved target")
            if route.get("target") is None and route.get("resolution_mode") != UNRESOLVED:
                errors.append(f"route[{index}] target-null route is not explicitly unresolved")
        semantic = _route_semantic_key(route)
        authority_semantic = (authority_id,) + semantic
        if authority_semantic in seen:
            errors.append(f"route[{index}] duplicate authority expansion")
        seen.add(authority_semantic)
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors)),
        "checked_routes": len(routes) if isinstance(routes, list) else 0,
        "mandatory_routes": mandatory_count,
        "model_calls": 0,
    }


def _test_target_details(
    test_contract: list[str], test_files: list[str], scope_paths: list[str],
    execution_evidence: Iterable[dict] | None = None,
) -> tuple[str | None, bool, list[str], str]:
    referenced = []
    for text in test_contract:
        referenced.extend(_references_from_text(text, test_files))
    scoped = [path for path in scope_paths if _is_test_path(path) and path in test_files]
    executed = []
    for item in execution_evidence or []:
        if not isinstance(item, dict) or item.get("tool") not in {"run_file", "run_command"}:
            continue
        text = " ".join((str(item.get("target", "")), str(item.get("result", ""))))
        executed.extend(path for path in test_files if path.casefold() in text.casefold())
    if referenced:
        choices = _unique_paths(referenced)
        source = "approved_contract_reference"
    elif scoped:
        choices = _unique_paths(scoped)
        source = "contract_scope"
    elif executed:
        choices = _unique_paths(executed)
        source = "execution_evidence"
    else:
        choices = []
        source = "repository_test_files"
    if len(choices) == 1:
        return choices[0], False, choices, source
    if len(choices) > 1:
        return None, True, choices, "ambiguous_supported_targets"
    if len(test_files) == 1:
        return test_files[0], False, list(test_files), "unique_repository_test"
    return None, bool(test_files), list(test_files), "ambiguous_repository_test_files" if test_files else "missing_repository_test_files"


def _test_target(
    test_contract: list[str], test_files: list[str], scope_paths: list[str],
    execution_evidence: Iterable[dict] | None = None,
) -> tuple[str | None, bool]:
    target, ambiguous, _choices, _source = _test_target_details(
        test_contract, test_files, scope_paths, execution_evidence,
    )
    return target, ambiguous


def _is_focused_test_evidence(item: dict) -> bool:
    if not isinstance(item, dict) or item.get("tool") not in {"run_file", "run_command"}:
        return False
    text = " ".join((str(item.get("target", "")), str(item.get("result", ""))))
    return not (
        item.get("tool") == "run_command" and _SYNTAX_EVIDENCE_MARKERS.search(text)
    ) and bool(_TEST_MARKERS.search(text))


def _approved_authority_artifact(
    *,
    child_id: str,
    authority: dict[str, Any],
    test_contract_values: list[str],
    test_files: list[str],
    scope_paths: list[str],
    execution_evidence: list[dict[str, Any]],
    facts: dict[str, Any],
    observed_file_types: Iterable[str] | None,
) -> dict[str, Any]:
    """Build routes for one already-approved verification authority.

    This branch is intentionally narrower than the generic applicability
    analyzer.  An approved authority answers an execution question; it does
    not open a second capability-discovery question for the same obligation.
    """
    direct = is_direct_oracle_authority(authority)
    authority_id = _authority_id(authority) or f"VERIFICATION-{child_id}"
    required = authority.get("mandatory") if isinstance(authority.get("mandatory"), bool) else authority.get("required") is not False
    explicit_targets, upstream_target = _authority_target_candidates(
        authority, test_files, direct=direct,
    )
    target_records: list[tuple[str | None, bool, list[str], str, bool]] = []
    if direct:
        # A direct oracle owns one immutable module/spec target.  Multiple
        # conflicting direct target fields are an authority defect, not a
        # reason to invoke focused-test discovery.
        if len(explicit_targets) == 1:
            target_records.append((
                explicit_targets[0], False, explicit_targets,
                "approved_direct_oracle_target", True,
            ))
        else:
            target_records.append((
                None, bool(explicit_targets), explicit_targets,
                "missing_or_conflicting_direct_oracle_target", bool(explicit_targets),
            ))
    elif explicit_targets:
        # Multiple distinct paths are legitimate only when the approved
        # authority explicitly names them.  That is deliberate authority
        # fan-out, not generic supported-target discovery.
        for target in explicit_targets:
            target_records.append((
                target, False, explicit_targets,
                "approved_contract_target", True,
            ))
    else:
        target, ambiguous, candidates, source = _test_target_details(
            test_contract_values, test_files, scope_paths, execution_evidence,
        )
        target_records.append((
            target, ambiguous, candidates, source, False,
        ))

    routes: list[VerificationRouteBinding] = []
    for index, (target, ambiguous, candidates, resolution_source, target_is_upstream) in enumerate(target_records, 1):
        if direct:
            route_kind = FOCUSED_TEST
            route_type = DIRECT_ORACLE
            route_authority_type = DIRECT_ORACLE
            channel = DIRECT_ORACLE_EXECUTION
            reason_codes = ["DIRECT_ORACLE_AUTHORITY"]
            if target:
                reason_codes.append(TEST_TARGET_PRESENT)
            if ambiguous:
                reason_codes.append(AMBIGUOUS_SUPPORTED_TARGET)
            mode = EXACT_APPROVED_TARGET if target else UNRESOLVED
            source = str(authority.get("authority_source") or "HIVO_VERIFIER")
        else:
            route_kind = FOCUSED_TEST
            route_type = APPROVED_FOCUSED_TEST
            route_authority_type = APPROVED_VERIFICATION_CONTRACT
            channel = STAGE5A_COMMAND
            reason_codes = [CONTRACT_REQUIRES_TEST]
            if target:
                reason_codes.extend((FOCUSED_TEST_PRESENT, TEST_TARGET_PRESENT))
            elif ambiguous:
                reason_codes.append(AMBIGUOUS_SUPPORTED_TARGET)
            mode = EXACT_APPROVED_TARGET if target_is_upstream and target else (
                SUPPORTED_TARGET_DISCOVERY if target else UNRESOLVED
            )
            source = str(authority.get("authority_source") or APPROVED_VERIFICATION_CONTRACT)
        refs = [f"child:{child_id}", f"approved:{authority_id}"]
        refs.extend(f"authority:{item}" for item in _as_list(authority.get("evidence_ids")))
        if target:
            refs.append(f"repo:test:{target}" if not direct else f"repo:oracle:{target}")
        route = _route(
            route_kind,
            bool(required),
            bool(target),
            target,
            reason_codes,
            refs,
            PENDING if target else BLOCKED_REQUIRED_TARGET_MISSING,
            resolution_status="RESOLVED" if target else VERIFICATION_TARGET_UNRESOLVED,
            resolution_source=resolution_source,
            candidate_targets=candidates,
            selected_target=target,
            approved_target=target if target_is_upstream and target else None,
            authority_target_candidates=explicit_targets,
            upstream_target_exists=bool(target_is_upstream),
            target_identity_upstream=bool(target_is_upstream),
            authority_fanout_index=index if len(target_records) > 1 else None,
            authority_fanout_count=len(target_records),
        )
        # Responsibility identity is semantic, not the approval-card ID.
        # The target and command are already part of the deduplication key, so
        # two approved mechanisms for the same semantic route can fan in while
        # retaining both authority IDs/provenance refs.
        responsibility_key = f"approved:{route_type}"
        binding = build_verification_route_binding(
            route,
            authority=authority,
            authority_type=route_authority_type,
            authority_source=source,
            route_type=route_type,
            execution_channel=channel,
            resolution_mode=mode,
            candidate_targets=candidates,
            selected_target=target,
            approved_target=target if target_is_upstream and target else None,
            provenance_refs=[f"approved:{authority_id}"],
            responsibility_key=responsibility_key,
        )
        routes.append(binding)

    route_audit = []
    for route in routes:
        route_audit.append({
            "route_id": route.get("route_id"),
            "verification_id": authority.get("verification_id"),
            "oracle_id": authority.get("oracle_id"),
            "authority_source": route.get("authority_source"),
            "authority_provenance": authority.get("provenance"),
            "required": route.get("required"),
            "applicable": route.get("applicable"),
            "route_type": route.get("route_type"),
            "candidate_targets": list(route.get("candidate_targets", []) or []),
            "selected_target": route.get("selected_target"),
            "target_resolution_reason": route.get("resolution_source"),
            "resolution_mode": route.get("resolution_mode"),
            "evidence_ids": list(authority.get("evidence_ids", []) or []),
            "target_identity_existed_upstream": bool(route.get("target_identity_upstream")),
        })
    artifact = {
        "schema_version": "V20.5A",
        "child_id": child_id,
        "model_calls": 0,
        "approved_authority": {
            "verification_id": authority.get("verification_id"),
            "oracle_id": authority.get("oracle_id"),
            "authority_source": authority.get("authority_source"),
            "authority_provenance": authority.get("provenance"),
            "direct_oracle": direct,
        },
        "verification_routes": routes,
        "verification_route_bindings": routes,
        "route_audit": route_audit,
        "repository_evidence": {
            "known_entrypoints": facts.get("entrypoints", [])[:20],
            "known_test_files": facts.get("tests", [])[:20],
            "observed_file_types": sorted({str(item).casefold() for item in (observed_file_types or [])}),
        },
    }
    artifact_hash = _json_hash(artifact)
    artifact["verification_applicability_hash"] = artifact_hash
    artifact["verification_routes_hash"] = artifact_hash
    return artifact


def analyze_verification_applicability(
    task: dict | None = None,
    contract: dict | None = None,
    repository_snapshot: dict | None = None,
    *,
    child_responsibility: dict | None = None,
    done_when: Iterable[str] | None = None,
    test_contract: Iterable[str] | None = None,
    mutation_paths: Iterable[str] | None = None,
    inspection_paths: Iterable[str] | None = None,
    canonical_surfaces: Any = None,
    existing_verification_requirements: Iterable[str] | None = None,
    workspace: str | os.PathLike | None = None,
    repository_evidence: Any = None,
    requested_path: str | None = None,
    known_entrypoints: Iterable[str] | None = None,
    known_test_files: Iterable[str] | None = None,
    observed_file_types: Iterable[str] | None = None,
    browser_target_resolver: Callable[[Any, dict], Any] | None = None,
    execution_evidence: Iterable[dict] | None = None,
    approved_verification_authority: dict[str, Any] | None = None,
    approved_verification_contract: dict[str, Any] | None = None,
    authority_record: dict[str, Any] | None = None,
) -> dict:
    """Build one deterministic route artifact using bounded evidence only."""
    task = dict(task) if isinstance(task, dict) else {}
    if isinstance(child_responsibility, dict):
        # The explicit child projection is a convenience for callers that do
        # not carry a full Task object.  It remains a read-only copy.
        merged_task = dict(child_responsibility)
        merged_task.update(task)
        task = merged_task
    contract = contract if isinstance(contract, dict) else {}
    source, has_child = _child_contract(task, contract)
    child_id = str(task.get("id") or task.get("task_id") or source.get("child_id") or "UNKNOWN")

    goal = _strings(task.get("goal"))
    if not goal and not has_child:
        goal = _strings(source.get("goal"))
    done_when_values = _strings(
        task.get("done_when") or source.get("done_when")
        if done_when is None else done_when,
    )
    scope_paths = _unique_paths(
        _as_list(task.get("scope_hint"))
        + _as_list(task.get("allowed_mutation_paths"))
        + _as_list(source.get("allowed_mutation_paths"))
        + _as_list(task.get("allowed_inspection_paths"))
        + _as_list(source.get("allowed_inspection_paths"))
        + _as_list(mutation_paths)
        + _as_list(inspection_paths)
    )
    test_contract_values = _strings(test_contract) if test_contract is not None else _local_test_contract(task, source, has_child)
    responsibility = str(source.get("responsibility_type", ""))
    local_texts = goal + done_when_values + test_contract_values
    verification_requirements = _strings(
        existing_verification_requirements
        if existing_verification_requirements is not None else task.get("existing_verification_requirements")
    )
    verification_requirements += _strings(task.get("verification_requirements"))
    verification_requirements += _strings(task.get("verification_plan"))
    verification_requirements += _strings(task.get("verification"))
    if not has_child:
        local_texts += _strings(source.get("requirements"))
        local_texts += _strings(source.get("success_criteria"))
        local_texts += _strings(source.get("verification_requirements"))
        local_texts += _strings(source.get("existing_verification_requirements"))
        local_texts += _strings(source.get("verification"))
        local_texts += _strings(source.get("verification_plan"))
    local_texts += verification_requirements
    text_bundle = " ".join(local_texts)

    facts = _source_facts(repository_snapshot, repository_evidence, workspace)
    facts["entrypoints"] = _unique_paths(
        list(facts.get("entrypoints", []))
        + [item for item in (known_entrypoints or []) if _is_html_path(item)]
    )
    facts["tests"] = _unique_paths(list(facts.get("tests", [])) + list(known_test_files or []))
    if canonical_surfaces:
        for item in _as_list(canonical_surfaces):
            if not isinstance(item, dict):
                continue
            candidate = item.get("path") or item.get("target") or item.get("entrypoint")
            if candidate:
                candidate = _path(candidate)
                facts["files"] = _unique_paths(facts.get("files", []) + [candidate])
                if _is_html_path(candidate):
                    facts["entrypoints"] = _unique_paths(facts.get("entrypoints", []) + [candidate])
                if _is_test_path(candidate):
                    facts["tests"] = _unique_paths(facts.get("tests", []) + [candidate])
    source_paths = _unique_paths([path for path in scope_paths if _is_source_path(path)])
    test_files = _unique_paths([path for path in facts.get("tests", []) if _is_test_path(path)])
    if not test_files:
        test_files = _unique_paths([path for path in facts.get("files", []) if _is_test_path(path)])

    execution_evidence = [
        item for item in (_as_list(execution_evidence))
        if isinstance(item, dict)
    ]
    approved_authority = (
        approved_verification_authority
        if isinstance(approved_verification_authority, dict) else
        approved_verification_contract
        if isinstance(approved_verification_contract, dict) else
        authority_record
        if isinstance(authority_record, dict) else None
    )
    if approved_authority is not None:
        return _approved_authority_artifact(
            child_id=child_id,
            authority=approved_authority,
            test_contract_values=test_contract_values,
            test_files=test_files,
            scope_paths=scope_paths,
            execution_evidence=execution_evidence,
            facts=facts,
            observed_file_types=observed_file_types,
        )

    positive_browser_text = _positive_browser_text(text_bundle)
    browser_signals = any(pattern.search(positive_browser_text) for pattern in _BROWSER_REQUIREMENT_PATTERNS)
    explicit_browser = any(pattern.search(positive_browser_text) for pattern in _EXPLICIT_BROWSER_PATTERNS)
    requested = _path(requested_path or task.get("requested_from_node") or task.get("browser_target") or "") or None
    if not requested:
        requested = next((path for path in scope_paths if _is_html_path(path)), None)
    if requested and (_is_html_path(requested) or browser_signals):
        browser_signals = True
    browser_evidence_refs = [f"child:{child_id}"]
    if explicit_browser:
        browser_evidence_refs.append("contract:browser_requirement")
    if requested:
        browser_evidence_refs.append(f"contract:requested_target:{requested}")
    if facts.get("entrypoints"):
        browser_evidence_refs.extend(f"repo:entrypoint:{item}" for item in facts["entrypoints"][:4])

    browser_details = None
    if browser_signals:
        browser_details = _resolve_browser_target(
            workspace,
            {"requested_from_node": requested, "repository_facts": facts},
            browser_target_resolver,
        )
    browser_target = browser_details.get("resolved_entrypoint") if browser_details else None
    browser_resolved = bool(browser_details and browser_details.get("resolution_status") == "RESOLVED" and browser_target)
    browser_reasons = []
    if explicit_browser:
        browser_reasons.append(EXPLICIT_BROWSER_REQUIREMENT)
    if browser_resolved:
        browser_reasons.append(SUPPORTED_TARGET_PRESENT)
    elif browser_signals:
        if browser_details and browser_details.get("resolution_source") in {"ambiguous_html_candidates", "ambiguous_asset_references"}:
            browser_reasons.append(AMBIGUOUS_SUPPORTED_TARGET)
        else:
            browser_reasons.append(NO_SUPPORTED_BROWSER_TARGET)
    else:
        browser_reasons.append(VERIFIER_NOT_REQUIRED)
        if not facts.get("entrypoints"):
            browser_reasons.append(NO_SUPPORTED_BROWSER_TARGET)
    if browser_signals:
        browser_route = _route(
            BROWSER, True, True, browser_target, browser_reasons, browser_evidence_refs,
            PENDING if browser_resolved else BLOCKED_REQUIRED_TARGET_MISSING,
            requested_from_node=requested,
            resolution_status=(browser_details or {}).get("resolution_status", VERIFICATION_TARGET_UNRESOLVED),
            resolution_source=(browser_details or {}).get("resolution_source"),
            candidates=(browser_details or {}).get("candidates", [])[:8],
        )
    else:
        browser_route = _route(
            BROWSER, False, False, None, browser_reasons, browser_evidence_refs,
            SKIPPED_NOT_APPLICABLE,
            requested_from_node=requested,
            resolution_status="NOT_APPLICABLE", resolution_source="applicability_analyzer",
        )

    focused_test_evidence = any(
        _is_focused_test_evidence(item)
        for item in execution_evidence
    )
    test_required = (
        bool(test_contract_values)
        or responsibility.casefold() in {"test_mutation", "test", "test_change"}
        or bool(_TEST_MARKERS.search(" ".join(goal + done_when_values)))
        or focused_test_evidence
    )
    test_target, test_ambiguous, test_candidates, test_resolution_source = _test_target_details(
        test_contract_values, test_files, scope_paths, execution_evidence,
    )
    test_reasons = []
    if test_required:
        test_reasons.append(CONTRACT_REQUIRES_TEST)
    if focused_test_evidence:
        test_reasons.append(FOCUSED_TEST_PRESENT)
    if test_target and not focused_test_evidence:
        test_reasons.extend((FOCUSED_TEST_PRESENT, TEST_TARGET_PRESENT))
    elif test_target:
        test_reasons.append(TEST_TARGET_PRESENT)
    elif test_required and test_ambiguous:
        test_reasons.append(AMBIGUOUS_SUPPORTED_TARGET)
    elif not test_required:
        test_reasons.append(VERIFIER_NOT_REQUIRED)
    if test_required:
        test_route = _route(
            FOCUSED_TEST, True, bool(test_target), test_target, test_reasons,
            [f"child:{child_id}", "contract:test_contract" if test_contract_values else "contract:done_when"]
            + ([f"repo:test:{test_target}"] if test_target else []),
            PENDING if test_target else BLOCKED_REQUIRED_TARGET_MISSING,
            resolution_status="RESOLVED" if test_target else VERIFICATION_TARGET_UNRESOLVED,
            resolution_source="deterministic_test_file" if test_target else "missing_or_ambiguous_test_file",
            candidate_targets=test_candidates,
            selected_target=test_target,
            target_resolution_reason=test_resolution_source,
            resolution_mode=SUPPORTED_TARGET_DISCOVERY if test_target else UNRESOLVED,
        )
    else:
        test_route = None

    syntax_paths = [path for path in source_paths if Path(path).suffix.casefold() not in _HTML_SUFFIXES or path in facts.get("files", [])]
    if not syntax_paths:
        syntax_paths = [path for path in source_paths if _is_source_path(path)]
    syntax_required = bool(syntax_paths)
    syntax_route = _route(
        SYNTAX_STATIC_GATE,
        syntax_required,
        syntax_required,
        sorted(syntax_paths, key=str.casefold)[0] if syntax_paths else None,
        [SUPPORTED_SOURCE_PRESENT, CONTRACT_REQUIRES_SYNTAX] if syntax_required else [VERIFIER_NOT_REQUIRED],
        [f"child:{child_id}", "contract:mutation_paths"] if syntax_required else [f"child:{child_id}"],
        PENDING if syntax_required else SKIPPED_NOT_APPLICABLE,
        resolution_status="RESOLVED" if syntax_required else "NOT_APPLICABLE",
        resolution_source="contract_source_paths" if syntax_required else "applicability_analyzer",
    )

    routes = [route for route in (test_route, syntax_route, browser_route) if route is not None][:_MAX_ROUTES]
    artifact = {
        "schema_version": "V20.5A",
        "child_id": child_id,
        "model_calls": 0,
        "verification_routes": routes,
        "repository_evidence": {
            "known_entrypoints": facts.get("entrypoints", [])[:20],
            "known_test_files": facts.get("tests", [])[:20],
            "observed_file_types": sorted({str(item).casefold() for item in (observed_file_types or [])}),
        },
    }
    artifact_hash = _json_hash(artifact)
    artifact["verification_applicability_hash"] = artifact_hash
    artifact["verification_routes_hash"] = artifact_hash
    return artifact


class VerificationApplicabilityAnalyzer:
    """Stateless facade useful to deterministic callers and tests."""

    model_calls = 0

    def analyze(self, *args: Any, **kwargs: Any) -> dict:
        return analyze_verification_applicability(*args, **kwargs)


def _parse_result(value: Any) -> tuple[str | None, bool]:
    if isinstance(value, dict):
        if value.get("verification_status") == SKIPPED_NOT_APPLICABLE or value.get("result") == SKIPPED_NOT_APPLICABLE:
            return None, False
        if value.get("passed") is True:
            return PASS, True
        if value.get("passed") is False:
            return FAIL, True
    text = str(value or "").strip()
    if text.casefold().startswith("[not_applicable]"):
        return None, False
    payload = None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            payload = parsed
    except (TypeError, ValueError):
        pass
    if isinstance(payload, dict):
        if payload.get("verification_status") == SKIPPED_NOT_APPLICABLE or payload.get("result") == SKIPPED_NOT_APPLICABLE:
            return None, False
        if payload.get("passed") is True:
            return PASS, True
        if payload.get("passed") is False:
            return FAIL, True
    if re.search(r"\[exit_code=0\]", text, re.I) or re.search(r"\b(?:pass|passed|success|succeeded)\b", text, re.I):
        return PASS, True
    if re.search(r"\[exit_code=[1-9]\d*\]", text, re.I) or re.search(r"\b(?:fail|failed|failure|syntaxerror|assertionerror)\b", text, re.I):
        return FAIL, True
    return None, False


def _evidence_matches(route: dict, item: dict) -> bool:
    tool = str(item.get("tool", ""))
    if tool not in {"run_file", "run_command", "verify_web_app"}:
        return False
    if route.get("kind") == BROWSER:
        return tool == "verify_web_app"
    text = " ".join((str(item.get("target", "")), str(item.get("result", "")))).casefold()
    target = str(route.get("target") or "").casefold()
    if route.get("kind") == FOCUSED_TEST and not _is_focused_test_evidence(item):
        return False
    if target and target in text:
        return True
    if route.get("kind") == FOCUSED_TEST:
        return True
    if route.get("kind") == SYNTAX_STATIC_GATE:
        return bool(_SYNTAX_EVIDENCE_MARKERS.search(text))
    return False


def aggregate_verification_evidence(
    applicability: dict | None,
    execution_evidence: Iterable[dict] | None = None,
    browser_result: dict | None = None,
) -> dict:
    """Aggregate actual evidence without turning a skip into a pass."""
    artifact = applicability if isinstance(applicability, dict) else {}
    routes = [dict(item) for item in artifact.get("verification_routes", []) if isinstance(item, dict)]
    evidence = [item for item in (execution_evidence or []) if isinstance(item, dict)]
    actual_passes = []
    actual_failures = []
    skipped = []
    required_missing = []
    for route in routes:
        kind = route.get("kind")
        if kind == BROWSER and isinstance(browser_result, dict):
            status = browser_result.get("verification_status")
            if status == SKIPPED_NOT_APPLICABLE:
                route["result"] = SKIPPED_NOT_APPLICABLE
            elif browser_result.get("passed") is True:
                route["result"] = PASS
            elif browser_result.get("passed") is False:
                route["result"] = FAIL
        matched = []
        for item in evidence:
            if not _evidence_matches(route, item):
                continue
            state, actual = _parse_result(item.get("result"))
            if actual:
                matched.append(state)
        if route.get("result") == SKIPPED_NOT_APPLICABLE or (not route.get("applicable") and not route.get("required")):
            route["result"] = SKIPPED_NOT_APPLICABLE
            skipped.append(route)
            continue
        if route.get("required") and not route.get("target"):
            route["result"] = BLOCKED_REQUIRED_TARGET_MISSING
            required_missing.append(route)
            actual_failures.append(route)
            continue
        if FAIL in matched:
            route["result"] = FAIL
            actual_failures.append(route)
        elif PASS in matched or (kind == BROWSER and route.get("result") == PASS):
            route["result"] = PASS
            actual_passes.append(route)
        elif route.get("result") == FAIL:
            actual_failures.append(route)
        else:
            route["result"] = PENDING

    required_routes = [route for route in routes if route.get("required") and route.get("applicable")]
    required_failures = [route for route in actual_failures if route.get("required")]
    usable_required_evidence = [route for route in actual_passes if route.get("required") and route.get("applicable")]
    failures = list(required_failures)
    failure_codes = []
    if required_missing:
        failure_codes.append(REQUIRED_VERIFICATION_TARGET_UNRESOLVED)
    if any(route.get("result") == FAIL for route in required_failures):
        failure_codes.append("REQUIRED_VERIFICATION_FAILED")
    if not usable_required_evidence:
        failure_codes.append(VERIFICATION_EVIDENCE_UNAVAILABLE)
    passed = bool(usable_required_evidence) and not required_failures and not required_missing
    return {
        "child_id": artifact.get("child_id"),
        "verification_routes": routes,
        "actual_passes": actual_passes,
        "actual_failures": actual_failures,
        "skipped_not_applicable": skipped,
        "required_target_failures": required_missing,
        "required_routes": required_routes,
        "failure_codes": list(dict.fromkeys(failure_codes)),
        "evidence_available": bool(usable_required_evidence),
        "passed": passed,
    }


__all__ = [
    "AMBIGUOUS_SUPPORTED_TARGET", "APPROVED_FOCUSED_TEST", "APPROVED_VERIFICATION_CONTRACT",
    "BROWSER", "BLOCKED_REQUIRED_TARGET_MISSING", "CONTRACT_REQUIRES_SYNTAX", "CONTRACT_REQUIRES_TEST",
    "DETERMINISTIC_CONTRACT_TARGET", "DETERMINISTIC_SYSTEM_SAFETY_CHECK", "DETERMINISTIC_SYSTEM_TARGET",
    "DIRECT_ORACLE", "DIRECT_ORACLE_EXECUTION", "EXACT_APPROVED_TARGET", "FAIL", "FOCUSED_TEST",
    "FOCUSED_TEST_PRESENT", "NO_SUPPORTED_BROWSER_TARGET", "OPTIONAL_CAPABILITY", "PASS", "PENDING",
    "REQUIRED_VERIFICATION_TARGET_UNRESOLVED", "SKIPPED_NOT_APPLICABLE", "STAGE5A_COMMAND",
    "SUPPORTED_SOURCE_PRESENT", "SUPPORTED_TARGET_DISCOVERY", "SUPPORTED_TARGET_PRESENT", "SYNTAX_STATIC_GATE",
    "TEST_TARGET_PRESENT", "UNRESOLVED", "VERIFICATION_EVIDENCE_UNAVAILABLE", "VERIFICATION_TARGET_UNRESOLVED",
    "VERIFIER_NOT_REQUIRED", "VerificationApplicabilityAnalyzer", "VerificationRouteBinding",
    "aggregate_verification_evidence", "analyze_verification_applicability", "build_verification_route_binding",
    "canonical_route_hash", "deduplicate_verification_routes", "deterministic_hash",
    "is_direct_oracle_authority", "validate_verification_route_bindings",
]
