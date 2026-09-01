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


def _test_target(
    test_contract: list[str], test_files: list[str], scope_paths: list[str],
    execution_evidence: Iterable[dict] | None = None,
) -> tuple[str | None, bool]:
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
    choices = _unique_paths(referenced or scoped or executed)
    if len(choices) == 1:
        return choices[0], False
    if len(choices) > 1:
        return None, True
    if len(test_files) == 1:
        return test_files[0], False
    return None, bool(test_files)


def _is_focused_test_evidence(item: dict) -> bool:
    if not isinstance(item, dict) or item.get("tool") not in {"run_file", "run_command"}:
        return False
    text = " ".join((str(item.get("target", "")), str(item.get("result", ""))))
    return not (
        item.get("tool") == "run_command" and _SYNTAX_EVIDENCE_MARKERS.search(text)
    ) and bool(_TEST_MARKERS.search(text))


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

    execution_evidence = [
        item for item in (_as_list(execution_evidence))
        if isinstance(item, dict)
    ]
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
    test_target, test_ambiguous = _test_target(
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
    "AMBIGUOUS_SUPPORTED_TARGET", "BROWSER", "BLOCKED_REQUIRED_TARGET_MISSING", "CONTRACT_REQUIRES_SYNTAX",
    "CONTRACT_REQUIRES_TEST", "FAIL", "FOCUSED_TEST", "FOCUSED_TEST_PRESENT", "NO_SUPPORTED_BROWSER_TARGET",
    "PASS", "PENDING", "REQUIRED_VERIFICATION_TARGET_UNRESOLVED", "SKIPPED_NOT_APPLICABLE",
    "SUPPORTED_SOURCE_PRESENT", "SUPPORTED_TARGET_PRESENT", "SYNTAX_STATIC_GATE", "TEST_TARGET_PRESENT",
    "VERIFICATION_EVIDENCE_UNAVAILABLE", "VERIFICATION_TARGET_UNRESOLVED", "VERIFIER_NOT_REQUIRED",
    "VerificationApplicabilityAnalyzer", "aggregate_verification_evidence", "analyze_verification_applicability",
    "deterministic_hash",
]
