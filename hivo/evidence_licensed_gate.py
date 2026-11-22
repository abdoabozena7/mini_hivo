"""Deterministic Evidence-Licensed Granularity & Tool-Contract Recovery Gate.

Implements Mini Hivo's *Before You Split* controller decision policy with zero
model dependencies.  Before a capability-based split or termination is licensed,
attributable interaction, range/freshness, syntax, or browser-module defects
receive one bounded correction attempt within unchanged authority, while
permission, approval, scope, and global resource boundaries stop immediately.
"""

from __future__ import annotations

import copy
import json
import re
from typing import Any


SCHEMA_VERSION = "EVIDENCE-LICENSED-GATE-1"

# Observed Failure Episode Classes
SCHEMA_CONTRACT_FAILURE = "SCHEMA_CONTRACT_FAILURE"
STALE_TARGET_OR_RANGE = "STALE_TARGET_OR_RANGE"
SYNTAX_REJECTED_MUTATION = "SYNTAX_REJECTED_MUTATION"
BROWSER_MODULE_OR_RUNTIME_DEFECT = "BROWSER_MODULE_OR_RUNTIME_DEFECT"
PERMISSION_OR_SCOPE_DENIAL = "PERMISSION_OR_SCOPE_DENIAL"
RESOURCE_OR_BUDGET_LIMIT = "RESOURCE_OR_BUDGET_LIMIT"
CAPABILITY_OR_BREADTH_CANDIDATE = "CAPABILITY_OR_BREADTH_CANDIDATE"
UNATTRIBUTED_NON_PROGRESS = "UNATTRIBUTED_NON_PROGRESS"

OBSERVED_EPISODE_CLASSES = frozenset({
    SCHEMA_CONTRACT_FAILURE,
    STALE_TARGET_OR_RANGE,
    SYNTAX_REJECTED_MUTATION,
    BROWSER_MODULE_OR_RUNTIME_DEFECT,
    PERMISSION_OR_SCOPE_DENIAL,
    RESOURCE_OR_BUDGET_LIMIT,
    CAPABILITY_OR_BREADTH_CANDIDATE,
    UNATTRIBUTED_NON_PROGRESS,
})

ATTRIBUTABLE_CORRECTION_CLASSES = frozenset({
    SCHEMA_CONTRACT_FAILURE,
    STALE_TARGET_OR_RANGE,
    SYNTAX_REJECTED_MUTATION,
    BROWSER_MODULE_OR_RUNTIME_DEFECT,
})

IMMEDIATE_STOP_CLASSES = frozenset({
    PERMISSION_OR_SCOPE_DENIAL,
    RESOURCE_OR_BUDGET_LIMIT,
})

# Licensing Decisions
STOP_IMMEDIATELY = "STOP_IMMEDIATELY"
REQUIRE_SAME_AUTHORITY_CORRECTION = "REQUIRE_SAME_AUTHORITY_CORRECTION"
LICENSE_GRANULARITY_CHANGE = "LICENSE_GRANULARITY_CHANGE"
HOLD_TERMINAL_FAILURE = "HOLD_TERMINAL_FAILURE"

LICENSING_DECISIONS = frozenset({
    STOP_IMMEDIATELY,
    REQUIRE_SAME_AUTHORITY_CORRECTION,
    LICENSE_GRANULARITY_CHANGE,
    HOLD_TERMINAL_FAILURE,
})

MAX_CORRECTION_BRIEF_CHARS = 1380
MAX_EXTRACTED_TOOL_CALLS = 8

_MUTATION_TOOLS = frozenset({"write_file", "edit_file", "edit_file_range"})

_PERMISSION_EXACT_CODES = frozenset({
    "PLAN_APPROVAL_REQUIRED",
    "USER_REAPPROVAL_REQUIRED",
    "APPROVAL_REQUIRED",
    "APPROVAL_REQUEST_INVALID",
    "APPROVED_PLAN_STALE",
    "WORKER_AUTHORIZATION_INVALID",
    "EXECUTION_CONTRACT_BLOCKED",
    "EXECUTION_CONTRACT_INVALID",
    "EXECUTION_CONTRACT_TOO_LARGE",
    "EXECUTION_GRAPH_INVALID",
    "AUTHORITY_CHANGE_REQUIRED",
    "PERMISSION_DENIED",
    "AUTHORIZATION_DENIED",
    "SCOPE_VIOLATION",
    "SAFETY_VIOLATION",
    "SAFETY_REJECTED_MUTATION",
    "UNEXPECTED_AND_OUT_OF_SCOPE",
    "UNAPPROVED_SCOPE_EXPANSION",
    "APPROVAL_MUTATION_SCOPE_MISMATCH",
    "CONTRACT_SCOPE_VIOLATION",
    "EXECUTION_AUTHORIZATION_BLOCKED",
    "EXECUTION_INVARIANT_MUTATION_VIOLATION",
    "CONTEXT_SUFFICIENCY_REQUIRED",
    "IMPACT_REQUIRED",
    "IMPACT_INVALID",
    "IMPACT_VERIFICATION_FAILED",
    "PRE_VERIFICATION_RECOVERY_BLOCKED_AUTHORITY",
    "PRE_VERIFICATION_RECOVERY_BLOCKED_DRIFT",
    "EXTERNAL_UNAUTHORIZED_DRIFT",
    "INVALID_AUTHORIZED_EXECUTION_DESCENDANT",
    "USER_CANCELLED",
    "CANCELLED",
    "CANCELED",
})

_RESOURCE_EXACT_CODES = frozenset({
    "ENVIRONMENT_ERROR",
    "ENVIRONMENT_FAILURE",
    "PROVIDER_FAILURE",
    "PROVIDER_ERROR",
    "TRANSPORT_ERROR",
    "OLLAMA_ERROR",
    "TIMEOUT",
    "TIMED_OUT",
    "DEADLINE_EXCEEDED",
    "RUN_BUDGET_EXHAUSTED",
    "GLOBAL_BUDGET_EXHAUSTED",
    "PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER",
    "PRE_VERIFICATION_RECOVERY_BLOCKED_BUDGET",
})

_SCHEMA_EXACT_CODES = frozenset({
    "MUTATION_ARGUMENT_RETRIES_EXHAUSTED",
    "TOOL_ARGUMENT_REJECTED",
    "STRUCTURED_OUTPUT_INVALID",
    "CONTEXT_DECISION_INVALID",
    "MALFORMED_TOOL_CALL",
    "INVALID_TOOL_ARGUMENTS",
})

_SYNTAX_EXACT_CODES = frozenset({
    "SYNTAX_INVALID_MUTATION",
    "SYNTAX_REJECTED_MUTATION",
    "SYNTAX_VALIDATION_FAILED",
})

_STALE_OR_RANGE_EXACT_CODES = frozenset({
    "STALE_TARGET",
    "MISSING_TARGET",
    "TARGET_LOCATOR_STALE",
    "MUTATION_TARGET_UNRESOLVED",
    "INVALID_LINE_RANGE",
})

_BROWSER_DEFECT_CODES = frozenset({
    "zero_size_canvas",
    "canvas_zero_size",
    "missing_canvas",
    "missing_game_bridge",
    "missing_bridge_method",
    "console_errors",
    "page_errors",
    "bare_module_specifier",
    "module_resolution_error",
    "runtime_error",
})

_PROSE_EXCLUSION_PATTERNS = re.compile(
    r"\b(?:"
    r"for\s+example|example\s*:|e\.g\.|such\s+as|sample\s+call|hypothetical|"
    r"would\s+look\s+like|do\s+not|don't|will\s+not|won't|cannot|can't|"
    r"instead\s+of|not\s+calling|without\s+calling|already\s+completed"
    r")\b",
    re.IGNORECASE,
)

_SINGLE_FENCED_JSON_RE = re.compile(
    r"```(?:([A-Za-z0-9_-]+)(?:[ \t]*\r?\n|[ \t]+)|[ \t]*\r?\n)?([\s\S]*?)[ \t]*\r?\n?```"
)


def _is_strict_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _clean_text(value: Any, limit: int = 500) -> str:
    if value is None:
        return ""
    compact = " ".join(str(value).strip().split())
    return compact[:limit]


def _normalize_target(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = " ".join(value.strip().split())
    if not cleaned or cleaned == "-":
        return None
    return cleaned[:240]


def _normalize_tool(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned == "-":
        return None
    return cleaned[:80]


def _append_unique(items: list[str], value: Any) -> None:
    if not isinstance(value, str):
        return
    cleaned = value.strip()
    if cleaned and cleaned not in items:
        items.append(cleaned[:120])


def _is_permission_code(code: str) -> bool:
    upper = code.strip().upper()
    return (
        upper in _PERMISSION_EXACT_CODES
        or upper.startswith("IMPACT_CONTRACT_")
        or upper.startswith("APPROVAL_")
        or upper.startswith("PERMISSION_")
    )


def _is_permission_text(text: str, *, from_mutation_or_gate: bool = False) -> bool:
    lower = text.casefold()
    if any(phrase in lower for phrase in (
        "outside the workspace",
        "outside workspace",
        "escapes workspace",
        "unauthorized mutation",
        "unauthorized target",
        "unauthorized path",
        "forbidden mutation",
        "disallowed mutation",
        "disallowed target",
        "not in allowed_mutation_paths",
        "unexpected_and_out_of_scope",
        "outside the accepted impact mutation paths",
        "unapproved_scope_expansion",
        "not an approved mutation target",
        "approval_mutation_scope_mismatch",
        "outside the approval-bound contract",
        "contract_scope_violation",
        "outside the approved execution-contract",
        "execution_authorization_blocked",
        "execution_invariant_mutation_violation",
        "context_sufficiency_required",
        "do-not-touch",
        "dnt violation",
        "plan approval required",
        "approval required",
        "user reapproval required",
        "worker_authorization_invalid",
        "impact contract rejected",
        "pre-mutation impact contract was not accepted",
        "pre-mutation impact contract did not match",
    )):
        return True
    if from_mutation_or_gate and any(phrase in lower for phrase in (
        "repairer cannot replace files with write_file",
        "write_file cannot replace an existing user-owned or verified file",
        "unavailable for role",
        "unavailable under the active",
        "not allowed",
    )):
        return True
    return False


def _is_resource_text(text: str) -> bool:
    lower = text.casefold()
    return any(phrase in lower for phrase in (
        "run_budget_exhausted",
        "global budget exhausted",
        "run budget exhausted",
        "deadline exceeded",
        "timed out",
        "timeout expired",
        "request timeout",
        "connection refused",
        "provider unavailable",
        "provider failure",
        "ollama request failed",
        "error writing file:",
        "error reading file:",
        "i/o error",
        "operating system error",
    ))


def _is_run_level_budget_exhausted(leaf_result: dict, task: dict) -> tuple[bool, str | None]:
    failure_type = str(leaf_result.get("failure_type") or "").strip().upper()
    exec_outcome = str(leaf_result.get("execution_outcome") or "").strip().upper()
    status = str(leaf_result.get("status") or "").strip().casefold()
    summary_lower = str(leaf_result.get("summary") or "").casefold()

    if failure_type in {"RUN_BUDGET_EXHAUSTED", "GLOBAL_BUDGET_EXHAUSTED"}:
        return True, failure_type
    if exec_outcome in {"RUN_BUDGET_EXHAUSTED", "GLOBAL_BUDGET_EXHAUSTED"}:
        return True, exec_outcome
    if leaf_result.get("run_budget_exhausted") is True or task.get("run_budget_exhausted") is True:
        return True, "RUN_BUDGET_EXHAUSTED"
    if str(leaf_result.get("budget_scope") or leaf_result.get("budget_level") or "").casefold() in {"run", "global"}:
        return True, "RUN_BUDGET_EXHAUSTED"
    if any(marker in summary_lower for marker in (
        "run_budget_exhausted",
        "run budget",
        "global budget",
        "max_model_calls",
        "max_tool_calls",
        "max_elapsed_seconds",
    )):
        return True, "RUN_BUDGET_EXHAUSTED"

    if status == "budget_exhausted":
        is_leaf_step_budget = (
            failure_type == "EXECUTION_BUDGET_EXHAUSTED"
            or exec_outcome == "EXECUTION_BUDGET_EXHAUSTED"
            or "step budget" in summary_lower
            or "tool-step budget" in summary_lower
            or "focused execution ended" in summary_lower
            or ("step_budget" in leaf_result and "tool_steps_used" in leaf_result)
        )
        if not is_leaf_step_budget:
            return True, "RUN_BUDGET_EXHAUSTED"
    return False, None


def _is_step_budget_exhausted(leaf_result: dict) -> bool:
    failure_type = str(leaf_result.get("failure_type") or "").strip().upper()
    exec_outcome = str(leaf_result.get("execution_outcome") or "").strip().upper()
    summary_lower = str(leaf_result.get("summary") or "").casefold()
    if (
        failure_type == "EXECUTION_BUDGET_EXHAUSTED"
        or exec_outcome == "EXECUTION_BUDGET_EXHAUSTED"
        or leaf_result.get("step_budget_exhausted") is True
        or "tool-step budget" in summary_lower
        or "step budget" in summary_lower
    ):
        return True
    step_budget = leaf_result.get("step_budget")
    steps_used = leaf_result.get("tool_steps_used")
    if _is_strict_int(step_budget) and _is_strict_int(steps_used) and step_budget > 0 and steps_used >= step_budget:
        return True
    builder = leaf_result.get("builder")
    if isinstance(builder, dict):
        b_budget = builder.get("step_budget")
        b_used = builder.get("tool_steps_used")
        if _is_strict_int(b_budget) and _is_strict_int(b_used) and b_budget > 0 and b_used >= b_budget:
            return True
    return False


def _tool_result_succeeded_mutation(tool_name: str, result_value: Any) -> bool:
    if tool_name not in _MUTATION_TOOLS:
        return False
    if isinstance(result_value, dict):
        if result_value.get("applied") is True or str(result_value.get("status") or "").upper() == "PASS":
            return True
        return False
    text = str(result_value or "").strip().casefold()
    if not text or text.startswith(("error:", "tool error:")):
        return False
    return text.startswith(("wrote file:", "edited file:", "edited lines "))


def _had_valid_mutations(leaf_result: dict) -> bool:
    if leaf_result.get("had_valid_mutations") is True:
        return True
    valid_count = leaf_result.get("valid_mutations")
    if _is_strict_int(valid_count) and valid_count > 0:
        return True
    for container in (leaf_result, leaf_result.get("builder")):
        if not isinstance(container, dict):
            continue
        changed = container.get("changed_files")
        if isinstance(changed, (list, tuple)) and any(str(p).strip() for p in changed):
            return True
        progress = container.get("worker_progress")
        if isinstance(progress, dict) and progress.get("first_legal_mutation") is not None:
            return True
        grounding = container.get("mutation_grounding")
        if isinstance(grounding, dict) and grounding.get("first_applied_mutation_step") is not None:
            return True
        for ev_key in ("tool_evidence", "execution_evidence"):
            ev_list = container.get(ev_key)
            if not isinstance(ev_list, list):
                continue
            for item in ev_list:
                if not isinstance(item, dict):
                    continue
                tool = str(item.get("tool") or "").strip()
                if item.get("applied") is True and tool in _MUTATION_TOOLS:
                    return True
                if _tool_result_succeeded_mutation(tool, item.get("result")):
                    return True
    return False


def _has_positive_scope_evidence(leaf_result: dict, task: dict) -> bool:
    valid_sources = {
        "task_fit",
        "fit",
        "fit_assessment",
        "fresh_fit",
        "fresh_fit_reassessment",
        "scope_assessment",
        "decomposition",
        "decomposition_analysis",
    }
    for container in (leaf_result, task):
        if not isinstance(container, dict):
            continue
        if container.get("positive_scope_evidence") is True:
            return True
        for list_key in (
            "scope_evidence",
            "responsibilities",
            "substantial_responsibilities",
            "independent_subsystems",
        ):
            values = container.get(list_key)
            if isinstance(values, (list, tuple)) and sum(1 for v in values if str(v).strip()) >= 2:
                return True
        for dict_key in (
            "scope_assessment",
            "fit_assessment",
            "fresh_fit_assessment",
            "fit_after_execution",
            "fit_before_execution",
            "fit_decision",
            "task_fit",
            "scope_provenance",
            "task_too_broad_provenance",
            "provenance",
        ):
            sub = container.get(dict_key)
            if isinstance(sub, dict):
                decision = str(sub.get("decision") or sub.get("fit_decision") or "").strip().casefold()
                if decision == "split":
                    return True
        resplit = container.get("resplit")
        if isinstance(resplit, dict) and isinstance(resplit.get("fit_decision"), dict):
            if str(resplit["fit_decision"].get("decision") or "").strip().casefold() == "split":
                return True
        source_name = str(container.get("source") or container.get("source_kind") or "").strip().casefold().replace("-", "_")
        decision = str(container.get("decision") or container.get("fit_decision") or "").strip().casefold()
        if source_name in valid_sources and decision == "split":
            return True
    return False


def _classify_mutation_text(tool_name: str | None, text: str) -> tuple[str | None, str | None]:
    lower = text.casefold()
    if (
        any(phrase in lower for phrase in (
            "incomplete or truncated ",
            "tool_argument_rejected",
            "invalid edit_file",
            "invalid write_file",
            "invalid edit_file_range",
            "invalid argument type",
            "invalid argument types",
            "malformed edit_file",
            "malformed write_file",
            "malformed edit_file_range",
            "malformed tool call",
            "arguments must be one json object",
            "arguments must be an object",
            "unexpected field(s):",
            "must be string",
            "must be integer",
            "must be int",
            "must be str",
        ))
        or re.search(
            r"\bmissing(?::|\s+required)?\s+(?:field\s+|argument\s+|parameter\s+)?['\"]?(?:path|start_line|end_line|old|new|content|command)\b",
            lower,
        )
        or re.search(r"\bmissing required (?:field|argument|parameter)", lower)
    ):
        return SCHEMA_CONTRACT_FAILURE, "TOOL_ARGUMENT_REJECTED"

    if any(phrase in lower for phrase in (
        "syntax validation failed",
        "syntaxerror",
        "parse error",
        "unexpected token",
        "unexpected identifier",
    )) and (tool_name in _MUTATION_TOOLS or tool_name is None or "syntax validation failed" in lower):
        return SYNTAX_REJECTED_MUTATION, "SYNTAX_INVALID_MUTATION"

    if any(phrase in lower for phrase in (
        "file does not exist",
        "target does not exist",
        "no such file or directory",
        "missing target",
        "missing_target",
    )):
        return STALE_TARGET_OR_RANGE, "MISSING_TARGET"

    if (
        any(phrase in lower for phrase in (
            "invalid line range",
            "exact text not found",
            "found 0",
            "0 matches",
            "multiple matches",
            "stale target",
            "stale_target",
            "stale context",
            "target_locator_stale",
            "context does not match",
            "requested range is too broad for a pre-existing file",
        ))
        or re.search(r"expected\s+\d+\s+exact\s+replacement\(s\),\s+found\s+\d+", lower)
        or re.search(r"\bfound\s+\d+\s+matches\b", lower)
    ):
        code = "INVALID_LINE_RANGE" if "invalid line range" in lower else "STALE_TARGET"
        return STALE_TARGET_OR_RANGE, code

    return None, None


def _extract_browser_defect(leaf_result: dict) -> tuple[bool, str | None, str | None, list[str], str]:
    codes: list[str] = []
    snippets: list[str] = []
    earliest_tool: str | None = None
    earliest_target: str | None = None

    def note_source(tool_val: Any, target_val: Any) -> None:
        nonlocal earliest_tool, earliest_target
        if earliest_tool is None:
            earliest_tool = _normalize_tool(tool_val)
        if earliest_target is None:
            earliest_target = _normalize_target(target_val)

    def inspect_browser_payload(payload: dict, default_tool: str = "verify_web_app", target_hint: Any = None) -> None:
        if payload.get("environment_error") is True or payload.get("syntax_failure") is True:
            return
        target_candidate = (
            target_hint
            or payload.get("entry_path")
            or payload.get("resolved_entrypoint")
            or payload.get("path")
            or payload.get("target")
        )
        runtime_state = payload.get("runtime_state")
        if isinstance(runtime_state, dict):
            if runtime_state.get("zeroSizeCanvas") is True or (
                _is_strict_int(runtime_state.get("canvasCount"))
                and runtime_state["canvasCount"] >= 1
                and (
                    runtime_state.get("canvasWidth") == 0
                    or runtime_state.get("canvasHeight") == 0
                    or runtime_state.get("width") == 0
                    or runtime_state.get("height") == 0
                )
            ):
                note_source(default_tool, target_candidate)
                _append_unique(codes, "zero_size_canvas")
                snippets.append("rendered canvas has zero dimensions")

        failures = payload.get("failures")
        if isinstance(failures, list):
            for failure in failures:
                if not isinstance(failure, dict):
                    continue
                code = str(failure.get("code") or "").strip()
                evidence_text = _clean_text(failure.get("evidence"), 220)
                code_lower = code.casefold()
                ev_lower = evidence_text.casefold()
                if code_lower in _BROWSER_DEFECT_CODES or any(marker in ev_lower for marker in (
                    "failed to resolve module specifier",
                    "referenceerror",
                    "typeerror",
                    "zero_size_canvas",
                    "zero-size canvas",
                    "missing_game_bridge",
                    "verification bridge is unavailable",
                    "missing bridge method",
                )) or ("agent_game" in ev_lower and any(m in ev_lower for m in ("is not a function", "undefined", "missing", "unavailable"))):
                    note_source(default_tool, target_candidate)
                    _append_unique(codes, code or "browser_runtime_defect")
                    if "failed to resolve module specifier" in ev_lower:
                        _append_unique(codes, "bare_module_specifier")
                    elif "missing bridge method" in ev_lower or ("agent_game" in ev_lower and "is not a function" in ev_lower):
                        _append_unique(codes, "missing_bridge_method")
                    if evidence_text:
                        snippets.append(evidence_text)

        for err_key in ("console_errors", "page_errors"):
            err_items = payload.get(err_key)
            if isinstance(err_items, list) and err_items:
                for entry in err_items:
                    text = _clean_text(entry if not isinstance(entry, dict) else entry.get("text") or entry, 220)
                    if not text:
                        continue
                    lower = text.casefold()
                    note_source(default_tool, target_candidate)
                    if "failed to resolve module specifier" in lower:
                        _append_unique(codes, "bare_module_specifier")
                    elif "referenceerror" in lower:
                        _append_unique(codes, "ReferenceError")
                    elif "typeerror" in lower:
                        _append_unique(codes, "TypeError")
                    elif "syntaxerror" in lower or "cannot use import statement outside a module" in lower:
                        _append_unique(codes, "browser_module_syntax_error")
                    else:
                        _append_unique(codes, err_key)
                    snippets.append(text)

    browser = leaf_result.get("browser")
    if isinstance(browser, dict):
        inspect_browser_payload(browser, default_tool="verify_web_app")

    gate = leaf_result.get("gate")
    if isinstance(gate, dict):
        for list_key in ("deterministic_failures", "checks"):
            checks = gate.get(list_key)
            if not isinstance(checks, list):
                continue
            for item in checks:
                if not isinstance(item, dict):
                    continue
                if list_key == "checks" and str(item.get("status") or "").upper() not in {"FAIL", "FAILED"}:
                    continue
                code = str(item.get("code") or item.get("name") or "").strip()
                ev_text = _clean_text(item.get("evidence") or item.get("summary") or item.get("result"), 220)
                lower = f"{code} {ev_text}".casefold()
                if code.casefold() in _BROWSER_DEFECT_CODES or any(marker in lower for marker in (
                    "failed to resolve module specifier",
                    "uncaught referenceerror",
                    "referenceerror:",
                    "uncaught typeerror",
                    "typeerror:",
                    "zero_size_canvas",
                    "zero-size canvas",
                    "missing_game_bridge",
                    "verification bridge is unavailable",
                    "missing bridge method",
                )):
                    note_source(item.get("tool") or "verify_web_app", item.get("target") or item.get("path"))
                    _append_unique(codes, code or "browser_runtime_defect")
                    if ev_text:
                        snippets.append(ev_text)

    builder_obj = leaf_result.get("builder") if isinstance(leaf_result.get("builder"), dict) else {}
    for container in (leaf_result, builder_obj):
        for ev_key in ("failure_evidence", "tool_evidence", "execution_evidence"):
            ev_list = container.get(ev_key)
            if not isinstance(ev_list, list):
                continue
            for item in ev_list:
                if not isinstance(item, dict):
                    continue
                tool = _normalize_tool(item.get("tool"))
                target = item.get("target") or item.get("path")
                code = str(item.get("code") or "").strip()
                raw_result = item.get("result")
                if isinstance(raw_result, dict):
                    inspect_browser_payload(raw_result, default_tool=tool or "verify_web_app", target_hint=target)
                    continue
                if isinstance(raw_result, str) and raw_result.strip().startswith("{"):
                    try:
                        parsed = json.loads(raw_result)
                    except ValueError:
                        parsed = None
                    if isinstance(parsed, dict) and (
                        tool == "verify_web_app"
                        or "console_errors" in parsed
                        or "page_errors" in parsed
                        or "failures" in parsed
                        or "verification_profile" in parsed
                    ):
                        inspect_browser_payload(parsed, default_tool=tool or "verify_web_app", target_hint=target)
                        continue
                text = _clean_text(item.get("evidence") or raw_result or item.get("summary"), 220)
                lower = f"{code} {text}".casefold()
                if code.casefold() in _BROWSER_DEFECT_CODES or (
                    (tool in {None, "verify_web_app", "browser"} or "browser" in str(item.get("kind") or "").casefold())
                    and (
                        any(marker in lower for marker in (
                            "failed to resolve module specifier",
                            "uncaught referenceerror",
                            "referenceerror:",
                            "uncaught typeerror",
                            "typeerror:",
                            "zero_size_canvas",
                            "zero-size canvas",
                            "missing_game_bridge",
                            "verification bridge is unavailable",
                            "missing bridge method",
                        ))
                        or ("agent_game" in lower and any(m in lower for m in ("is not a function", "undefined", "missing", "unavailable")))
                    )
                ):
                    note_source(tool or "verify_web_app", target)
                    _append_unique(codes, code or "browser_runtime_defect")
                    if text:
                        snippets.append(text)

    summary = _clean_text(leaf_result.get("summary"), 240)
    summary_lower = summary.casefold()
    if any(marker in summary_lower for marker in (
        "failed to resolve module specifier",
        "zero_size_canvas",
        "zero-size canvas",
        "missing_game_bridge",
        "verification bridge is unavailable",
        "missing bridge method",
        "uncaught referenceerror",
        "uncaught typeerror",
    )):
        note_source("verify_web_app", None)
        if "failed to resolve module specifier" in summary_lower:
            _append_unique(codes, "bare_module_specifier")
        elif "zero_size_canvas" in summary_lower or "zero-size canvas" in summary_lower:
            _append_unique(codes, "zero_size_canvas")
        elif "missing_game_bridge" in summary_lower or "verification bridge is unavailable" in summary_lower:
            _append_unique(codes, "missing_game_bridge")
        elif "missing bridge method" in summary_lower:
            _append_unique(codes, "missing_bridge_method")
        else:
            _append_unique(codes, "browser_runtime_defect")
        snippets.append(summary)

    if not codes:
        return False, None, None, [], ""
    detail = snippets[0] if snippets else ", ".join(codes[:3])
    rationale = (
        f"Browser runtime/module verification failed ({', '.join(codes[:4])}): "
        f"{_clean_text(detail, 220)}"
    )
    return True, earliest_tool, earliest_target, codes, rationale


def classify_failure_episode(leaf_result: dict, *, task: dict | None = None) -> dict:
    """Deterministically classify a leaf execution failure episode without inventing causes."""
    result = leaf_result if isinstance(leaf_result, dict) else {}
    task_dict = task if isinstance(task, dict) else {}
    builder = result.get("builder") if isinstance(result.get("builder"), dict) else {}

    status = str(result.get("status") or "").strip()
    failure_type = str(result.get("failure_type") or "").strip()
    terminal_state = str(result.get("terminal_state") or "").strip()
    orchestration_failure = str(result.get("orchestration_failure") or "").strip()
    summary = _clean_text(result.get("summary"), 400)

    def make_episode(
        episode_class: str,
        *,
        earliest_tool: str | None = None,
        earliest_target: str | None = None,
        observed_codes: list[str] | None = None,
        abstained: bool = False,
        rationale: str = "",
    ) -> dict:
        clean_codes: list[str] = []
        for code in observed_codes or []:
            _append_unique(clean_codes, code)
        return {
            "episode_class": episode_class,
            "earliest_tool": _normalize_tool(earliest_tool),
            "earliest_target": _normalize_target(earliest_target),
            "observed_codes": clean_codes,
            "abstained": bool(abstained),
            "rationale": _clean_text(rationale, 420),
        }

    # Gather mutation failure records and evidence items in deterministic order.
    mutation_records: list[dict] = []
    for container in (result, builder):
        raw_muts = container.get("mutation_failures")
        if isinstance(raw_muts, list):
            for item in raw_muts:
                if isinstance(item, dict):
                    mutation_records.append(item)

    evidence_records: list[dict] = []
    for key in ("failure_evidence", "tool_evidence", "execution_evidence"):
        for container in (result, builder):
            raw_ev = container.get(key)
            if isinstance(raw_ev, list):
                for item in raw_ev:
                    if isinstance(item, dict):
                        evidence_records.append(item)

    # 1A. Permission, scope, approval, impact-contract, and authorization boundaries.
    perm_codes: list[str] = []
    perm_tool: str | None = None
    perm_target: str | None = None
    for code_candidate in (failure_type, terminal_state, orchestration_failure, str(result.get("code") or "")):
        if code_candidate and _is_permission_code(code_candidate):
            _append_unique(perm_codes, code_candidate)
    if result.get("approval_required") is True or task_dict.get("approval_required") is True:
        _append_unique(perm_codes, "PLAN_APPROVAL_REQUIRED")
    if result.get("permission_denied") is True:
        _append_unique(perm_codes, "PERMISSION_DENIED")
    if status.casefold() in {"cancelled", "canceled"}:
        _append_unique(perm_codes, "USER_CANCELLED")
    impact_val = result.get("impact_validation")
    if isinstance(impact_val, dict) and impact_val.get("accepted") is False and status.casefold() in {"failed", "blocked"}:
        _append_unique(perm_codes, str(impact_val.get("status") or "IMPACT_CONTRACT_INVALID"))
    for rec in mutation_records + evidence_records:
        cat = str(rec.get("category") or rec.get("code") or "").strip()
        rec_text = _clean_text(rec.get("summary") or rec.get("result") or rec.get("evidence") or rec.get("error"), 300)
        is_mut_or_gate = (
            rec in mutation_records
            or str(rec.get("kind") or "").casefold() in {
                "mutation_failure",
                "impact_contract_validation",
                "orchestration_failure",
                "precommit_invariant",
            }
            or str(rec.get("tool") or "") in _MUTATION_TOOLS
        )
        if (cat and _is_permission_code(cat)) or _is_permission_text(rec_text, from_mutation_or_gate=is_mut_or_gate):
            if perm_tool is None:
                perm_tool = _normalize_tool(rec.get("tool"))
            if perm_target is None:
                perm_target = _normalize_target(rec.get("target") or rec.get("path"))
            _append_unique(perm_codes, cat or "PERMISSION_OR_SCOPE_DENIAL")
    if _is_permission_text(summary, from_mutation_or_gate=True):
        _append_unique(perm_codes, failure_type or "PERMISSION_OR_SCOPE_DENIAL")
    if perm_codes:
        return make_episode(
            PERMISSION_OR_SCOPE_DENIAL,
            earliest_tool=perm_tool,
            earliest_target=perm_target,
            observed_codes=perm_codes,
            abstained=False,
            rationale=(
                f"Authority, permission, scope, or approval boundary blocked execution "
                f"({', '.join(perm_codes[:4])}); retrying or splitting is forbidden."
            ),
        )

    # 1B. Provider, environment, timeout, or global RunBudget boundaries.
    res_codes: list[str] = []
    res_tool: str | None = None
    res_target: str | None = None
    for code_candidate in (failure_type, terminal_state, orchestration_failure, str(result.get("execution_outcome") or "")):
        if code_candidate and code_candidate.strip().upper() in _RESOURCE_EXACT_CODES:
            _append_unique(res_codes, code_candidate)
    if status.casefold() in {"provider_failure", "timeout"}:
        _append_unique(res_codes, status.upper())
    if result.get("provider_error") or builder.get("provider_error"):
        _append_unique(res_codes, "PROVIDER_ERROR")
    if result.get("environment_error") is True or (isinstance(result.get("browser"), dict) and result["browser"].get("environment_error") is True):
        _append_unique(res_codes, "ENVIRONMENT_ERROR")
    if result.get("timed_out") is True or result.get("timeout") is True:
        _append_unique(res_codes, "TIMEOUT")
    run_budget_hit, run_budget_code = _is_run_level_budget_exhausted(result, task_dict)
    if run_budget_hit and run_budget_code:
        _append_unique(res_codes, run_budget_code)
    for rec in mutation_records + evidence_records:
        cat = str(rec.get("category") or rec.get("code") or "").strip()
        rec_kind = str(rec.get("kind") or "").strip().casefold()
        rec_text = _clean_text(rec.get("summary") or rec.get("result") or rec.get("evidence") or rec.get("error"), 300)
        if (
            cat.upper() in _RESOURCE_EXACT_CODES
            or rec.get("environment_error") is True
            or rec_kind in {"provider_failure", "browser_environment"}
            or _is_resource_text(rec_text)
        ):
            if res_tool is None:
                res_tool = _normalize_tool(rec.get("tool"))
            if res_target is None:
                res_target = _normalize_target(rec.get("target") or rec.get("path"))
            _append_unique(res_codes, cat or "RESOURCE_OR_BUDGET_LIMIT")
    if _is_resource_text(summary):
        _append_unique(res_codes, failure_type or "RESOURCE_OR_BUDGET_LIMIT")
    if res_codes:
        return make_episode(
            RESOURCE_OR_BUDGET_LIMIT,
            earliest_tool=res_tool,
            earliest_target=res_target,
            observed_codes=res_codes,
            abstained=False,
            rationale=(
                f"Provider, environment, timeout, or global RunBudget limit reached "
                f"({', '.join(res_codes[:4])}); stop immediately without retrying or splitting."
            ),
        )

    # 2. Check active browser module/runtime defects vs mutation/schema episodes.
    has_browser_defect, browser_tool, browser_target, browser_codes, browser_rationale = _extract_browser_defect(result)
    builder_done = str(builder.get("status") or "").casefold() == "done"
    if has_browser_defect and (
        builder_done
        or failure_type.upper() == "BROWSER_VERIFICATION_STAGNATION"
        or (isinstance(result.get("gate"), dict) and result["gate"].get("passed") is False and failure_type.upper() not in _SCHEMA_EXACT_CODES)
    ):
        codes = list(browser_codes)
        if failure_type:
            _append_unique(codes, failure_type)
        return make_episode(
            BROWSER_MODULE_OR_RUNTIME_DEFECT,
            earliest_tool=browser_tool or "verify_web_app",
            earliest_target=browser_target,
            observed_codes=codes,
            abstained=False,
            rationale=browser_rationale,
        )

    # Collect ordered candidate mutation/interaction observations.
    observations: list[tuple[str, str | None, str | None, str, str]] = []

    if failure_type.upper() in _SCHEMA_EXACT_CODES:
        observations.append((
            SCHEMA_CONTRACT_FAILURE,
            None,
            None,
            failure_type.upper(),
            f"Controller recorded {failure_type.upper()} on tool argument validation.",
        ))
    elif failure_type.upper() in _SYNTAX_EXACT_CODES:
        observations.append((
            SYNTAX_REJECTED_MUTATION,
            None,
            None,
            failure_type.upper(),
            f"Controller recorded {failure_type.upper()} during source validation.",
        ))
    elif failure_type.upper() in _STALE_OR_RANGE_EXACT_CODES:
        observations.append((
            STALE_TARGET_OR_RANGE,
            None,
            None,
            failure_type.upper(),
            f"Controller recorded {failure_type.upper()} on target/range resolution.",
        ))

    for rec in mutation_records:
        tool = _normalize_tool(rec.get("tool"))
        target = _normalize_target(rec.get("target") or rec.get("path"))
        cat = str(rec.get("category") or rec.get("code") or "").strip().upper()
        rec_text = _clean_text(rec.get("summary") or rec.get("error") or rec.get("result"), 300)
        if cat in _SCHEMA_EXACT_CODES:
            observations.append((SCHEMA_CONTRACT_FAILURE, tool, target, cat, rec_text or cat))
            continue
        if cat in _SYNTAX_EXACT_CODES:
            observations.append((SYNTAX_REJECTED_MUTATION, tool, target, cat, rec_text or cat))
            continue
        if cat in _STALE_OR_RANGE_EXACT_CODES:
            observations.append((STALE_TARGET_OR_RANGE, tool, target, cat, rec_text or cat))
            continue
        inferred_cls, inferred_code = _classify_mutation_text(tool, rec_text)
        if inferred_cls and inferred_code:
            observations.append((inferred_cls, tool, target, cat or inferred_code, rec_text))

    for container in (result, builder):
        syn_list = container.get("syntax_validation_failures")
        if isinstance(syn_list, list):
            for syn in syn_list:
                if not isinstance(syn, dict):
                    continue
                target = _normalize_target(syn.get("path") or syn.get("target"))
                tool = _normalize_tool(syn.get("tool")) or "write_file"
                err = _clean_text(syn.get("error") or syn.get("evidence") or "syntax validation failed", 300)
                observations.append((SYNTAX_REJECTED_MUTATION, tool, target, "SYNTAX_VALIDATION_FAILED", err))

    for rec in evidence_records:
        tool = _normalize_tool(rec.get("tool"))
        target = _normalize_target(rec.get("target") or rec.get("path"))
        cat = str(rec.get("category") or rec.get("code") or "").strip().upper()
        rec_text = _clean_text(rec.get("summary") or rec.get("result") or rec.get("evidence") or rec.get("error"), 300)
        if tool == "malformed" or cat in _SCHEMA_EXACT_CODES:
            observations.append((
                SCHEMA_CONTRACT_FAILURE,
                tool,
                target,
                cat or "MALFORMED_TOOL_CALL",
                rec_text or "malformed tool call",
            ))
            continue
        if cat in _SYNTAX_EXACT_CODES or rec.get("syntax_failure") is True:
            observations.append((
                SYNTAX_REJECTED_MUTATION,
                tool,
                target,
                cat or "SYNTAX_INVALID_MUTATION",
                rec_text or "syntax validation failed",
            ))
            continue
        if cat in _STALE_OR_RANGE_EXACT_CODES:
            observations.append((
                STALE_TARGET_OR_RANGE,
                tool,
                target,
                cat,
                rec_text or cat,
            ))
            continue
        if tool in _MUTATION_TOOLS or str(rec.get("kind") or "").casefold() == "mutation_failure":
            inferred_cls, inferred_code = _classify_mutation_text(tool, rec_text)
            if inferred_cls and inferred_code:
                observations.append((inferred_cls, tool, target, inferred_code, rec_text))

    summary_cls, summary_code = _classify_mutation_text(None, summary)
    if summary_cls and summary_code:
        observations.append((summary_cls, None, None, summary_code, summary))

    if observations:
        # Select the earliest concrete attributable observation, filling tool/target
        # from the first matching observation that carries them.
        chosen_class = observations[0][0]
        if failure_type.upper() == "MUTATION_ARGUMENT_RETRIES_EXHAUSTED":
            chosen_class = SCHEMA_CONTRACT_FAILURE
        matching = [obs for obs in observations if obs[0] == chosen_class]
        earliest_tool = next((obs[1] for obs in matching if obs[1] is not None), None)
        earliest_target = next((obs[2] for obs in matching if obs[2] is not None), None)
        codes: list[str] = []
        if failure_type and failure_type.upper() not in {"TASK_TOO_BROAD", "FAILED", "UNKNOWN_FAILURE"}:
            _append_unique(codes, failure_type)
        for obs in matching:
            _append_unique(codes, obs[3])
        detail = next((obs[4] for obs in matching if obs[4]), chosen_class)
        class_labels = {
            SCHEMA_CONTRACT_FAILURE: "Tool schema/argument contract failure",
            SYNTAX_REJECTED_MUTATION: "Syntax validation rejected candidate mutation",
            STALE_TARGET_OR_RANGE: "Stale/missing target or invalid range/match in mutation",
        }
        return make_episode(
            chosen_class,
            earliest_tool=earliest_tool,
            earliest_target=earliest_target,
            observed_codes=codes,
            abstained=False,
            rationale=f"{class_labels.get(chosen_class, chosen_class)}: {_clean_text(detail, 260)}",
        )

    if has_browser_defect:
        codes = list(browser_codes)
        if failure_type:
            _append_unique(codes, failure_type)
        return make_episode(
            BROWSER_MODULE_OR_RUNTIME_DEFECT,
            earliest_tool=browser_tool or "verify_web_app",
            earliest_target=browser_target,
            observed_codes=codes,
            abstained=False,
            rationale=browser_rationale,
        )

    # 3. Genuine breadth / capability candidate: requires positive scope evidence
    # OR focused step budget exhausted after valid applied mutations.
    positive_scope = _has_positive_scope_evidence(result, task_dict)
    step_exhausted = _is_step_budget_exhausted(result)
    valid_mutations = _had_valid_mutations(result)
    is_too_broad_marked = (
        failure_type.upper() == "TASK_TOO_BROAD"
        or status.casefold() == "too_broad"
    )

    if (is_too_broad_marked and positive_scope) or (step_exhausted and (valid_mutations or positive_scope)):
        cap_codes: list[str] = []
        if failure_type:
            _append_unique(cap_codes, failure_type)
        if step_exhausted:
            _append_unique(cap_codes, "STEP_BUDGET_EXHAUSTED")
        if valid_mutations:
            _append_unique(cap_codes, "VALID_MUTATIONS_OBSERVED")
        if positive_scope:
            _append_unique(cap_codes, "POSITIVE_SCOPE_EVIDENCE")
        first_target = None
        changed = result.get("changed_files") or builder.get("changed_files")
        if isinstance(changed, (list, tuple)) and changed:
            first_target = _normalize_target(str(changed[0]))
        why = (
            "positive scope evidence indicates multiple substantial responsibilities"
            if positive_scope and not (step_exhausted and valid_mutations)
            else "focused step budget was exhausted after valid mutations without interaction/schema faults"
        )
        return make_episode(
            CAPABILITY_OR_BREADTH_CANDIDATE,
            earliest_tool=None,
            earliest_target=first_target,
            observed_codes=cap_codes,
            abstained=False,
            rationale=f"Capability or breadth candidate established: {why}.",
        )

    # 4. Abstain rather than inventing model incapacity or spurious breadth.
    unattributed_codes: list[str] = []
    if failure_type:
        _append_unique(unattributed_codes, failure_type)
    elif status:
        _append_unique(unattributed_codes, status.upper())
    first_tool = next((_normalize_tool(r.get("tool")) for r in evidence_records if _normalize_tool(r.get("tool"))), None)
    first_target = next(
        (_normalize_target(r.get("target") or r.get("path")) for r in evidence_records if _normalize_target(r.get("target") or r.get("path"))),
        None,
    )
    return make_episode(
        UNATTRIBUTED_NON_PROGRESS,
        earliest_tool=first_tool,
        earliest_target=first_target,
        observed_codes=unattributed_codes,
        abstained=True,
        rationale=(
            "Classifier abstained: non-progress observed without attributable tool/syntax/browser "
            "faults and without positive scope evidence; do not infer model incapacity or split."
        ),
    )


def license_granularity_decision(
    episode: dict,
    *,
    correction_attempted: bool = False,
    budget_remaining: bool = True,
    approval_bound: bool = False,
    can_split: bool = True,
) -> dict:
    """Apply the *Before You Split* licensing policy to a classified failure episode."""
    ep = episode if isinstance(episode, dict) else {}
    raw_class = str(ep.get("episode_class") or UNATTRIBUTED_NON_PROGRESS).strip()
    episode_class = raw_class if raw_class in OBSERVED_EPISODE_CLASSES else UNATTRIBUTED_NON_PROGRESS
    abstained = bool(ep.get("abstained")) or episode_class == UNATTRIBUTED_NON_PROGRESS

    corr_done = bool(correction_attempted)
    has_budget = bool(budget_remaining)
    is_approval_bound = bool(approval_bound)
    split_possible = bool(can_split)

    def make_decision(
        decision: str,
        *,
        allow_split: bool,
        allow_correction: bool,
        rationale: str,
    ) -> dict:
        return {
            "decision": decision,
            "episode_class": episode_class,
            "allow_split": bool(allow_split),
            "allow_correction": bool(allow_correction),
            "authority_unchanged": True,
            "correction_attempted": corr_done,
            "budget_remaining": has_budget,
            "approval_bound": is_approval_bound,
            "can_split": split_possible,
            "abstained": abstained,
            "rationale": _clean_text(rationale, 420),
        }

    # Safety, permission, scope, approval, and resource/run-budget limits never retry or split.
    if episode_class in IMMEDIATE_STOP_CLASSES or is_approval_bound:
        reason = (
            "Approval boundary active; stop immediately without correction or decomposition."
            if is_approval_bound and episode_class not in IMMEDIATE_STOP_CLASSES
            else f"{episode_class} prohibits retries and granularity changes; stop immediately."
        )
        return make_decision(
            STOP_IMMEDIATELY,
            allow_split=False,
            allow_correction=False,
            rationale=reason,
        )

    # Attributable interaction, range/freshness, syntax, or browser-module defects.
    if episode_class in ATTRIBUTABLE_CORRECTION_CLASSES:
        if not corr_done and has_budget:
            return make_decision(
                REQUIRE_SAME_AUTHORITY_CORRECTION,
                allow_split=False,
                allow_correction=True,
                rationale=(
                    f"{episode_class} requires one bounded same-authority correction "
                    f"and fresh progress observation before any split decision."
                ),
            )
        if corr_done and split_possible and has_budget:
            return make_decision(
                LICENSE_GRANULARITY_CHANGE,
                allow_split=True,
                allow_correction=False,
                rationale=(
                    f"Bounded same-authority correction for {episode_class} was already "
                    f"executed without verified completion; granularity change is now licensed."
                ),
            )
        return make_decision(
            HOLD_TERMINAL_FAILURE,
            allow_split=False,
            allow_correction=False,
            rationale=(
                f"Cannot execute further correction or split for {episode_class} "
                f"(correction_attempted={corr_done}, can_split={split_possible}, budget_remaining={has_budget})."
            ),
        )

    # Genuine scope breadth or post-valid-mutation step-budget candidate.
    if episode_class == CAPABILITY_OR_BREADTH_CANDIDATE:
        if split_possible and has_budget:
            return make_decision(
                LICENSE_GRANULARITY_CHANGE,
                allow_split=True,
                allow_correction=False,
                rationale="Positive breadth/scope evidence supports decomposition within remaining budget.",
            )
        return make_decision(
            HOLD_TERMINAL_FAILURE,
            allow_split=False,
            allow_correction=False,
            rationale=(
                f"Breadth candidate cannot split further "
                f"(can_split={split_possible}, budget_remaining={has_budget}); hold terminal failure."
            ),
        )

    # UNATTRIBUTED_NON_PROGRESS: allow at most one bounded correction; never spuriously split.
    if not corr_done and has_budget:
        return make_decision(
            REQUIRE_SAME_AUTHORITY_CORRECTION,
            allow_split=False,
            allow_correction=True,
            rationale=(
                "Unattributed non-progress: allow one bounded same-authority correction "
                "without claiming model incapacity or splitting."
            ),
        )
    return make_decision(
        HOLD_TERMINAL_FAILURE,
        allow_split=False,
        allow_correction=False,
        rationale=(
            "Unattributed non-progress has no positive scope evidence to license decomposition; "
            "hold honest terminal failure."
        ),
    )


def build_immediate_mutation_hint(
    tool_name: str,
    args: dict | None,
    result_text: str,
    *,
    target_path: str = "",
    target_exists: bool = False,
    target_line_count: int | None = None,
    draft_writable: bool = False,
    repeated_count: int = 1,
) -> str:
    """Build deterministic, zero-guesswork guidance on the first recoverable mutation error."""
    if not _is_strict_int(repeated_count) or repeated_count < 1:
        return ""
    name = str(tool_name or "").strip()
    text = str(result_text or "").strip()
    if not text:
        return ""
    lower = text.casefold()

    # Never emit retry hints for successful mutations, safety/permission refusals, or OS/environment errors.
    if lower.startswith(("wrote file:", "edited file:", "edited lines ")):
        return ""
    if _is_permission_text(text, from_mutation_or_gate=True) or _is_resource_text(text):
        return ""
    if not (
        lower.startswith((
            "error:",
            "tool error:",
            "compile error:",
            "tool_argument_rejected",
            "missing_target",
            "stale_target",
            "syntax_invalid_mutation",
            "invalid_mutation",
        ))
        or any(marker in lower for marker in (
            "syntax validation failed",
            "syntaxerror",
            "parse error",
            "unexpected token",
            "missing",
            "invalid",
            "malformed",
            "truncated",
            "found 0",
            "0 matches",
            "multiple matches",
            "exact replacement",
            "exact text not found",
            "does not exist",
            "missing target",
            "stale",
        ))
    ):
        return ""

    arg_dict = args if isinstance(args, dict) else None
    resolved_path = _clean_text(
        target_path or (arg_dict.get("path") if isinstance(arg_dict, dict) and isinstance(arg_dict.get("path"), str) else ""),
        200,
    )
    valid_line_count = target_line_count if (_is_strict_int(target_line_count) and target_line_count >= 0) else None

    parts: list[str] = []

    if name == "edit_file_range":
        parts.append(
            "TOOL CONTRACT HINT: edit_file_range requires path (str), start_line (1-based int), "
            "end_line (1-based int >= start_line), and new (str). Never guess line numbers."
        )
        if arg_dict is None:
            parts.append("Arguments must be a JSON object supplying path, start_line, end_line, and new.")
        else:
            missing = [
                field for field in ("path", "start_line", "end_line", "new")
                if field not in arg_dict or arg_dict.get(field) is None
            ]
            type_issues: list[str] = []
            if "path" in arg_dict and arg_dict.get("path") is not None and not isinstance(arg_dict.get("path"), str):
                type_issues.append("path must be str")
            if "start_line" in arg_dict and arg_dict.get("start_line") is not None and not _is_strict_int(arg_dict.get("start_line")):
                type_issues.append("start_line must be int")
            if "end_line" in arg_dict and arg_dict.get("end_line") is not None and not _is_strict_int(arg_dict.get("end_line")):
                type_issues.append("end_line must be int")
            if "new" in arg_dict and arg_dict.get("new") is not None and not isinstance(arg_dict.get("new"), str):
                type_issues.append("new must be str")
            if missing:
                parts.append(f"Missing required field(s): {', '.join(missing)}.")
            if type_issues:
                parts.append(f"Invalid field type(s): {'; '.join(type_issues)}.")
        if "invalid line range" in lower:
            parts.append("Requested line range is out of bounds or end_line < start_line; no file was changed.")
        elif any(m in lower for m in ("file does not exist", "missing target", "no such file")):
            label = f"'{resolved_path}'" if resolved_path else "the requested path"
            parts.append(
                f"Target {label} does not currently exist; call list_files() or create a new authorized file with write_file(path, content)."
            )
        elif any(m in lower for m in ("syntax validation failed", "syntaxerror", "unexpected token", "parse error")):
            parts.append(
                "Candidate range edit failed syntax validation and was not applied; check surrounding lines so delimiters and module/script syntax remain valid."
            )

    elif name == "edit_file":
        parts.append(
            "TOOL CONTRACT HINT: edit_file requires path (str), old (str), and new (str), "
            "plus optional expected_replacements (int >= 1, default 1)."
        )
        if arg_dict is None:
            parts.append("Arguments must be a JSON object supplying path, old, and new.")
        else:
            missing = [
                field for field in ("path", "old", "new")
                if field not in arg_dict or arg_dict.get(field) is None
            ]
            type_issues = []
            for str_field in ("path", "old", "new"):
                if str_field in arg_dict and arg_dict.get(str_field) is not None and not isinstance(arg_dict.get(str_field), str):
                    type_issues.append(f"{str_field} must be str")
            if (
                "expected_replacements" in arg_dict
                and arg_dict.get("expected_replacements") is not None
                and not _is_strict_int(arg_dict.get("expected_replacements"))
            ):
                type_issues.append("expected_replacements must be int")
            if missing:
                parts.append(f"Missing required field(s): {', '.join(missing)}.")
            if type_issues:
                parts.append(f"Invalid field type(s): {'; '.join(type_issues)}.")
        match_count = re.search(r"expected\s+(\d+)\s+exact\s+replacement\(s\),\s+found\s+(\d+)", lower)
        if match_count:
            found_n = int(match_count.group(2))
            if found_n == 0:
                parts.append(
                    "Exact snippet 'old' matched 0 times in the current file; read the current file and copy exact verbatim text."
                )
            else:
                parts.append(
                    f"Exact snippet 'old' matched {found_n} locations instead of the expected count; include surrounding context lines in 'old' to match uniquely."
                )
        elif "exact text not found" in lower or "found 0" in lower or "0 matches" in lower:
            parts.append(
                "Exact snippet 'old' matched 0 times in the current file; read the current file and copy exact verbatim text."
            )
        elif "multiple matches" in lower or re.search(r"\bfound\s+([2-9]|\d{2,})\s+matches\b", lower):
            parts.append(
                "Exact snippet 'old' matched multiple locations in the current file; include surrounding context lines in 'old' to match uniquely."
            )
        elif any(m in lower for m in ("file does not exist", "missing target", "no such file")):
            label = f"'{resolved_path}'" if resolved_path else "the requested path"
            parts.append(
                f"Target {label} does not currently exist; call list_files() or create a new authorized file with write_file(path, content)."
            )
        elif any(m in lower for m in ("syntax validation failed", "syntaxerror", "unexpected token", "parse error")):
            parts.append(
                "Candidate replacement failed syntax validation and was not applied; ensure complete valid syntax before retrying."
            )

    elif name == "write_file":
        parts.append("TOOL CONTRACT HINT: write_file requires path (str) and content (str).")
        if arg_dict is None:
            parts.append("Arguments must be a JSON object supplying path and content.")
        else:
            missing = [
                field for field in ("path", "content")
                if field not in arg_dict or arg_dict.get(field) is None
            ]
            type_issues = [
                f"{field} must be str"
                for field in ("path", "content")
                if field in arg_dict and arg_dict.get(field) is not None and not isinstance(arg_dict.get(field), str)
            ]
            if missing:
                parts.append(f"Missing required field(s): {', '.join(missing)}.")
            if type_issues:
                parts.append(f"Invalid field type(s): {'; '.join(type_issues)}.")
        if any(m in lower for m in ("syntax validation failed", "syntaxerror", "unexpected token", "parse error")):
            parts.append(
                "Candidate file content failed syntax validation and was not written; fix the reported syntax error (use <script type=\"module\"> for HTML ES module imports) and provide complete valid source."
            )

    else:
        return ""

    if target_exists and valid_line_count is not None and resolved_path:
        parts.append(
            f"Current file '{resolved_path}' has {valid_line_count} line(s); "
            f"call read_file with start_line/end_line first to inspect exact line numbers."
        )
    elif not target_exists and resolved_path and "does not currently exist" not in " ".join(parts):
        parts.append(f"Current file '{resolved_path}' has exists=False in the workspace.")

    if draft_writable and resolved_path:
        parts.append(
            f"Because '{resolved_path}' is an unverified draft created in this transaction, "
            f"you may also replace it cleanly in one call using write_file(path, content)."
        )

    if repeated_count > 1:
        parts.append(f"Failure count on this target/call: {repeated_count}; do not repeat the identical invalid call.")

    return " ".join(parts)


def build_same_authority_correction_brief(
    episode: dict,
    *,
    target_states: list[dict] | None = None,
    allow_draft_rewrite: bool = False,
) -> str:
    """Build a compact (<1,400 chars) recovery anchor packet for one same-authority correction."""
    ep = episode if isinstance(episode, dict) else {}
    raw_class = str(ep.get("episode_class") or UNATTRIBUTED_NON_PROGRESS).strip()
    episode_class = raw_class if raw_class in OBSERVED_EPISODE_CLASSES else UNATTRIBUTED_NON_PROGRESS
    earliest_tool = _normalize_tool(ep.get("earliest_tool")) or "unspecified"
    earliest_target = _normalize_target(ep.get("earliest_target")) or "unspecified"
    codes = [str(c).strip() for c in (ep.get("observed_codes") or []) if str(c).strip()][:4]
    rationale = _clean_text(ep.get("rationale"), 220)

    guidance_map = {
        SCHEMA_CONTRACT_FAILURE: (
            "Supply all required tool fields with exact types: "
            "edit_file_range(path, start_line, end_line, new), edit_file(path, old, new), "
            "or write_file(path, content). Never guess line numbers; inspect first."
        ),
        STALE_TARGET_OR_RANGE: (
            "Do not assume prior unverified drafts exist. Check exists/lines below: "
            "if exists=False create with write_file(path, content); if exists=True read current lines before editing."
        ),
        SYNTAX_REJECTED_MUTATION: (
            "Previous candidate failed syntax validation and was NOT applied. "
            "Submit complete syntactically valid code (balanced delimiters; <script type=\"module\"> for HTML ES imports)."
        ),
        BROWSER_MODULE_OR_RUNTIME_DEFECT: (
            "Fix browser runtime/module defects: avoid bare ES module specifiers (e.g. 'three') without an importmap "
            "or valid URL/local script, resolve ReferenceError/TypeError, ensure non-zero canvas size, and expose required window.AGENT_GAME bridge methods."
        ),
        UNATTRIBUTED_NON_PROGRESS: (
            "No verified progress was recorded. Inspect current workspace files directly, "
            "perform a grounded in-scope mutation, and run real executable/browser verification."
        ),
    }
    action_text = guidance_map.get(
        episode_class,
        "Inspect current workspace state and execute one valid verified change within scope.",
    )

    state_lines: list[str] = []
    if isinstance(target_states, list) and target_states:
        for item in target_states[:6]:
            if not isinstance(item, dict):
                continue
            path_val = _clean_text(
                item.get("path") or item.get("target") or item.get("target_path") or item.get("file"),
                90,
            )
            if not path_val:
                continue
            exists_raw = item.get("exists", item.get("current_file_exists", False))
            exists = bool(exists_raw)
            raw_lines = item.get("line_count", item.get("lines", item.get("current_file_line_count")))
            line_count = raw_lines if (_is_strict_int(raw_lines) and raw_lines >= 0) else None
            if not exists:
                state_lines.append(
                    f"- {path_val}: exists=False (absent/rolled back; create with write_file before any edit)"
                )
            elif line_count is not None:
                state_lines.append(
                    f"- {path_val}: exists=True, lines={line_count} (inspect exact lines before range/text edit)"
                )
            else:
                state_lines.append(
                    f"- {path_val}: exists=True, lines=unknown (call read_file before editing)"
                )
        if len(target_states) > 6:
            state_lines.append(f"- ... (+{len(target_states) - 6} more target(s); call list_files/read_file)")

    if not state_lines:
        state_lines.append(
            "- (none recorded; call list_files/read_file to verify current workspace files before editing)"
        )

    draft_line = (
        "Draft policy: unverified transaction drafts may be cleanly replaced via write_file(path, content)."
        if allow_draft_rewrite
        else "Draft policy: use write_file only for absent (exists=False) targets; use focused edits after reading for existing files."
    )
    authority_line = (
        "Authority boundary: UNCHANGED (same task scope, allowed paths, approval state, and verification gates; "
        "1 bounded correction attempt; never use echo or fabricated checks as proof)."
    )

    header = (
        f"[SAME-AUTHORITY CORRECTION BRIEF | class={episode_class} | "
        f"tool={earliest_tool} | target={earliest_target}]"
    )
    codes_str = f"Observed codes: {', '.join(codes) if codes else 'none'}."
    why_str = f"Observed defect: {rationale}" if rationale else "Observed defect: interaction/verification failure."

    sections = [
        header,
        f"{codes_str} {why_str}",
        f"Required correction: {action_text}",
        "Current workspace target states:\n" + "\n".join(state_lines),
        draft_line,
        authority_line,
    ]
    brief = "\n".join(sections)
    if len(brief) <= MAX_CORRECTION_BRIEF_CHARS:
        return brief

    # Trim middle variable sections while strictly preserving header, exists states, and authority boundary.
    compact_sections = [
        header,
        f"Observed defect: {_clean_text(rationale, 120)}",
        f"Required correction: {_clean_text(action_text, 200)}",
        "Current workspace target states:\n" + "\n".join(state_lines[:4]),
        draft_line,
        authority_line,
    ]
    compact_brief = "\n".join(compact_sections)
    return compact_brief[:MAX_CORRECTION_BRIEF_CHARS]


def _normalize_single_tool_call_dict(
    item: Any,
    offered: set[str],
) -> dict | None:
    if not isinstance(item, dict) or not item:
        return None

    allowed_outer_keys = {"type", "id", "function", "name", "tool", "arguments", "args", "parameters"}
    if any(str(k) not in allowed_outer_keys for k in item):
        return None
    if "type" in item and item.get("type") not in {None, "function", "tool_call"}:
        return None

    fn_obj = item.get("function")
    if fn_obj is not None and not isinstance(fn_obj, dict):
        return None
    if isinstance(fn_obj, dict):
        allowed_fn_keys = {"name", "arguments", "args", "parameters"}
        if any(str(k) not in allowed_fn_keys for k in fn_obj):
            return None

    outer_name = item.get("name") if "name" in item else item.get("tool")
    if "name" in item and "tool" in item and item.get("name") != item.get("tool"):
        return None
    fn_name = fn_obj.get("name") if isinstance(fn_obj, dict) else None
    if outer_name is not None and fn_name is not None and outer_name != fn_name:
        return None
    chosen_name = fn_name if fn_name is not None else outer_name
    if not isinstance(chosen_name, str) or chosen_name.strip() not in offered:
        return None
    normalized_name = chosen_name.strip()

    arg_candidates: list[Any] = []
    if isinstance(fn_obj, dict):
        for key in ("arguments", "args", "parameters"):
            if key in fn_obj:
                arg_candidates.append(fn_obj[key])
    for key in ("arguments", "args", "parameters"):
        if key in item:
            arg_candidates.append(item[key])

    if not arg_candidates:
        return None
    first_args = arg_candidates[0]
    if not isinstance(first_args, dict):
        return None
    if any(not isinstance(other, dict) or other != first_args for other in arg_candidates[1:]):
        return None

    return {
        "function": {
            "name": normalized_name,
            "arguments": copy.deepcopy(first_args),
        }
    }


def _extract_candidate_json_text(content: str) -> str | None:
    stripped = content.strip()
    if not stripped:
        return None

    # Pure JSON object or JSON array with zero surrounding prose.
    if (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    ):
        return stripped

    # Single fenced JSON block check.
    if "```" not in stripped:
        return None
    matches = list(_SINGLE_FENCED_JSON_RE.finditer(stripped))
    if len(matches) != 1:
        return None
    match = matches[0]
    # Reject stray unmatched triple backticks outside the single matched block.
    prefix = stripped[: match.start()].strip()
    suffix = stripped[match.end() :].strip()
    if "```" in prefix or "```" in suffix:
        return None

    lang = (match.group(1) or "").strip().casefold()
    if lang not in {"", "json", "tool", "tool_call", "tool_calls"}:
        return None

    # Do not extract JSON examples embedded in multi-paragraph or trailing prose.
    if suffix:
        return None
    if prefix:
        if "\n" in prefix or len(prefix) > 64 or _PROSE_EXCLUSION_PATTERNS.search(prefix):
            return None

    body = match.group(2).strip()
    return body if body else None


def extract_text_tool_call_fallback(
    content: str,
    offered_tool_names: set[str] | frozenset[str] | list[str],
) -> list[dict]:
    """Safely extract structured tool calls emitted as JSON text when tool_calls is empty."""
    if not isinstance(content, str) or not content.strip():
        return []
    if not isinstance(offered_tool_names, (set, frozenset, list, tuple)):
        return []
    offered = {
        name.strip()
        for name in offered_tool_names
        if isinstance(name, str) and name.strip()
    }
    if not offered:
        return []

    candidate_json = _extract_candidate_json_text(content)
    if not candidate_json:
        return []

    try:
        parsed = json.loads(candidate_json)
    except (TypeError, ValueError, RecursionError):
        return []

    raw_items: list[Any]
    if isinstance(parsed, dict):
        if set(parsed.keys()) <= {"tool_calls"} and isinstance(parsed.get("tool_calls"), list):
            raw_items = parsed["tool_calls"]
        else:
            raw_items = [parsed]
    elif isinstance(parsed, list):
        raw_items = parsed
    else:
        return []

    if not raw_items or len(raw_items) > MAX_EXTRACTED_TOOL_CALLS:
        return []

    normalized: list[dict] = []
    for item in raw_items:
        call = _normalize_single_tool_call_dict(item, offered)
        if call is None:
            return []
        normalized.append(call)
    return normalized


__all__ = [
    "SCHEMA_VERSION",
    "SCHEMA_CONTRACT_FAILURE",
    "STALE_TARGET_OR_RANGE",
    "SYNTAX_REJECTED_MUTATION",
    "BROWSER_MODULE_OR_RUNTIME_DEFECT",
    "PERMISSION_OR_SCOPE_DENIAL",
    "RESOURCE_OR_BUDGET_LIMIT",
    "CAPABILITY_OR_BREADTH_CANDIDATE",
    "UNATTRIBUTED_NON_PROGRESS",
    "OBSERVED_EPISODE_CLASSES",
    "ATTRIBUTABLE_CORRECTION_CLASSES",
    "IMMEDIATE_STOP_CLASSES",
    "STOP_IMMEDIATELY",
    "REQUIRE_SAME_AUTHORITY_CORRECTION",
    "LICENSE_GRANULARITY_CHANGE",
    "HOLD_TERMINAL_FAILURE",
    "LICENSING_DECISIONS",
    "classify_failure_episode",
    "license_granularity_decision",
    "build_immediate_mutation_hint",
    "build_same_authority_correction_brief",
    "extract_text_tool_call_fallback",
]
