"""Deterministic primitives for Asymmetric Orchestrator-Worker & Scaling Law experiments.

This zero-LLM-call module provides:
1. Canonical decomposition regime validation (`DECOMPOSITION_REGIMES`,
   `validate_decomposition_regime`).
2. Schema-echo tool argument normalization (`unwrap_schema_echo_arguments`) for
   ultra-weak 1.5B-3B worker models that wrap scalar/array arguments in JSON
   Schema property descriptors.
3. Strict code-free external/frontier decomposition plan validation
   (`validate_no_code_leakage`, `load_and_validate_decomposition_plan`) that
   prevents implementation leakage into worker prompts.
4. Formal contract completeness (`kappa`) scoring and verification-gated Dziri
   compositional pass-probability estimation
   (`compute_child_contract_completeness`, `compute_plan_completeness_summary`,
   `predict_compositional_pass_probability`).
"""

from __future__ import annotations

import copy
import json
import math
import posixpath
import re
from pathlib import Path
from typing import Any


PLAN_SCHEMA_VERSION = "1.0"
MAX_PLAN_CHILDREN = 8

DECOMPOSITION_REGIMES: tuple[str, ...] = (
    "auto",
    "monolithic",
    "self_recursive",
    "naive_oversplit",
    "contract_atomic",
)

_SCHEMA_ECHO_ALLOWED_KEYS = frozenset({
    "type",
    "description",
    "title",
    "value",
    "content",
    "default",
    "const",
})
_SCHEMA_ECHO_PAYLOAD_PRIORITY: tuple[str, ...] = (
    "value",
    "content",
    "const",
    "default",
)

_ALLOWED_TOP_LEVEL_PLAN_KEYS = frozenset({
    "schema_version",
    "regime",
    "orchestrator_id",
    "goal",
    "constraints",
    "success_criteria",
    "children",
})
_ALLOWED_CHILD_PLAN_KEYS = frozenset({
    "id",
    "goal",
    "done_when",
    "scope_hint",
    "owned_mutation_paths",
    "read_only_sibling_paths",
    "depends_on",
    "interface_contract",
    "verification_oracles",
})

_ALLOWED_ORACLE_KINDS = frozenset({
    "run_file",
    "run_command",
    "unittest",
    "verify_web_app",
})
_ALLOWED_ORACLE_KEYS = frozenset({
    "kind",
    "target",
    "function",
    "arguments",
    "expected",
    "command",
    "expected_stdout",
    "expected_stdout_contains",
    "expected_exit_code",
    "expected_exports",
    "expected_source_substrings",
})

# Workspace file ownership detection (excludes bare JS library names such as "Three.js")
_BARE_LIBRARY_NAMES = frozenset({
    "three.js",
    "node.js",
    "vue.js",
    "react.js",
    "next.js",
    "nuxt.js",
    "chart.js",
    "p5.js",
    "d3.js",
    "babylon.js",
    "pixi.js",
    "matter.js",
    "anime.js",
})
_CONCRETE_FILE_EXT_RE = re.compile(
    r"(?:^|[\s`'\"(\[,])([A-Za-z0-9_./\\-]+\.(?:py|pyi|js|mjs|cjs|jsx|ts|tsx|html|htm|css|scss|json))(?=$|[\s`'\")\],:;])",
    re.IGNORECASE,
)

# Anti-code-leakage regular expressions
_FENCED_BLOCK_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_PROSE_LIST_PREFIX_RE = re.compile(r"^(?:[-*+]\s+|\d+[.)]\s+[A-Z])")
_PY_COMPOUND_HEADER_RE = re.compile(
    r"^(?:"
    r"(?:async\s+)?def\s+[A-Za-z_]\w*\s*\(.*\)\s*(?:->\s*[^:]+)?\s*:"
    r"|class\s+[A-Za-z_]\w*(?:\s*\(.*\))?\s*:"
    r"|(?:if|elif|for|while|with|except|match|case)\b.+:"
    r"|(?:else|try|finally)\s*:"
    r"|@[A-Za-z_][\w.]*(?:\(.*\))?"
    r")\s*(?:#.*)?$"
)
_IMPORT_EXPORT_LINE_RE = re.compile(
    r"^(?:"
    r"import\s+(?:[A-Za-z_*]|[\"'\{])"
    r"|from\s+[A-Za-z_.][\w.]*\s+import\s+[A-Za-z_*(\\]"
    r"|export\s+(?:default\s+|const\s+|let\s+|var\s+|function\b|async\s+function\b|class\b|\{)"
    r")"
)
_JS_COMPOUND_HEADER_RE = re.compile(
    r"^(?:"
    r"(?:async\s+)?function(?:\s+[A-Za-z_$][\w$]*)?\s*\(.*\)\s*\{"
    r"|(?:const|let|var)\s+[A-Za-z_${\[][\w$,\s{}\[\]:]*="
    r"|(?:if|else\s+if|for|while|switch|catch)\s*\(.*\)\s*\{?"
    r"|(?:else|try|finally)\s*\{"
    r"|class\s+[A-Za-z_$][\w$]*(?:\s+extends\s+[A-Za-z_$.][\w$.]*)?\s*\{"
    r")\s*(?://.*)?$"
)
_CONTROL_FLOW_STMT_RE = re.compile(
    r"^(?:return|yield|raise|throw|break|continue|pass|del|assert|await)\b"
)
_ASSIGNMENT_STMT_RE = re.compile(
    r"^[A-Za-z_$][\w$.\[\]]*(?:\s*,\s*[A-Za-z_$][\w$.\[\]]*)*"
    r"(?:\s*:\s*[A-Za-z_][\w\[\], |.]*)?"
    r"\s*(?:\+|-|\*|/|//|%|\*\*|&|\||\^|<<|>>|\?\?)?=\s*[^=>]"
)
_TOP_LEVEL_CALL_STMT_RE = re.compile(
    r"^(?:print|sys\.exit|os\._exit|console\.(?:log|error|warn)|document\.\w+|window\.\w+)\s*\("
)
_JS_SEMICOLON_STMT_RE = re.compile(
    r"^[A-Za-z_$][\w$.\[\]()]*.*;\s*(?://.*)?$"
)
_INDENTED_CODE_CALL_RE = re.compile(
    r"^[A-Za-z_$][\w$.]*\s*\("
)
_CLOSING_BRACE_ONLY_RE = re.compile(r"^[\}\]\)]+[;,]?\s*(?://.*|#.*)?$")

# Contract completeness (kappa) structural indicator patterns
_CALLABLE_SIGNATURE_RE = re.compile(r"\b([A-Za-z_$][\w$.]*)\(([^\n]{0,240})\)")
_CLI_FLAG_RE = re.compile(r"(?:^|[\s`'\"(\[,])--[A-Za-z0-9][A-Za-z0-9_-]*")
_CLASS_OR_BRIDGE_RE = re.compile(
    r"(?:\bclass\s+[A-Z][A-Za-z0-9_]*\b|\bwindow\.[A-Za-z_$][\w$]*\b|\bAGENT_GAME\b)"
)
_DOM_ID_CONTRACT_RE = re.compile(r"(?:^|[\s`'\"(\[,])#([A-Za-z][A-Za-z0-9_-]{2,})\b")
_HEX_COLOR_RE = re.compile(r"^[0-9a-fA-F]{3}(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{5})?$")

_IO_TYPE_TOKEN_RE = re.compile(
    r"(?:->|=>"
    r"|\b(?:dict|list|tuple|set|frozenset|float|int|str|bool|bytes|None"
    r"|Optional|Sequence|Mapping|Iterable|Callable"
    r"|number|string|boolean|Array|Object|Promise|Record)\b"
    r"|\bJSON\b)",
)
_NONEMPTY_BRACE_SCHEMA_RE = re.compile(r"\{\s*['\"A-Za-z_][^}]*\}")

_EDGE_OR_ERROR_INVARIANT_RE = re.compile(
    r"(?:"
    r"\b[A-Za-z_]*Error\b"
    r"|\b[A-Za-z_]*Exception\b"
    r"|<=|>=|!="
    r"|\b0\b"
    r"|\b(?:empty|invalid|exit|exits|raises|raise|negative|paused|overlap|overlapping"
    r"|zero|nonzero|non-zero|boundary|clamp|clamped|missing|malformed|duplicate|cycle"
    r"|timeout|fallback|reject|rejects)\b"
    r")",
    re.IGNORECASE,
)

_EXECUTABLE_ORACLE_RE = re.compile(
    r"\b(?:"
    r"unittest|pytest|run_file|run_command|verify_web_app"
    r"|returns|prints|exits|renders|raises|outputs|asserts"
    r")\b",
    re.IGNORECASE,
)


def validate_decomposition_regime(regime: str) -> str:
    """Validate and normalize an experimental decomposition regime identifier."""
    if not isinstance(regime, str):
        raise ValueError(
            f"Decomposition regime must be a str, got {type(regime).__name__}."
        )
    normalized = regime.strip().lower()
    if normalized not in DECOMPOSITION_REGIMES:
        raise ValueError(
            f"Invalid decomposition regime {regime!r}; expected one of {DECOMPOSITION_REGIMES}."
        )
    return normalized


def _extract_tool_properties(tool_definition: dict[str, Any]) -> dict[str, Any]:
    """Extract parameter properties dict from inner or OpenAI-wrapped tool definitions."""
    parameters = tool_definition.get("parameters")
    if not isinstance(parameters, dict):
        fn_block = tool_definition.get("function")
        if isinstance(fn_block, dict):
            parameters = fn_block.get("parameters")
    if isinstance(parameters, dict):
        props = parameters.get("properties")
        return props if isinstance(props, dict) else {}
    if tool_definition.get("type") == "object" and isinstance(tool_definition.get("properties"), dict):
        return tool_definition["properties"]
    return {}


def _spec_declared_types(spec: dict[str, Any]) -> list[str]:
    """Collect normalized JSON-Schema primitive/container type names allowed by `spec`."""
    declared: list[str] = []
    raw_type = spec.get("type")
    if isinstance(raw_type, str):
        declared.append(raw_type.strip().lower())
    elif isinstance(raw_type, list):
        for item in raw_type:
            if isinstance(item, str):
                declared.append(item.strip().lower())

    for combinator in ("anyOf", "oneOf"):
        branches = spec.get(combinator)
        if isinstance(branches, list):
            for branch in branches:
                if isinstance(branch, dict):
                    for sub_t in _spec_declared_types(branch):
                        if sub_t not in declared:
                            declared.append(sub_t)
    return declared


def _candidate_matches_schema_type(
    declared_types: list[str],
    echo_type: str,
    candidate: Any,
) -> bool:
    """Return True iff `echo_type` and Python runtime type of `candidate` match `declared_types`."""
    for target_type in declared_types:
        if target_type == "string":
            if echo_type == "string" and type(candidate) is str:
                return True
        elif target_type == "integer":
            if echo_type in {"integer", "number"} and type(candidate) is int:
                return True
        elif target_type == "number":
            if echo_type in {"number", "integer"} and type(candidate) in (int, float):
                return True
        elif target_type == "boolean":
            if echo_type == "boolean" and type(candidate) is bool:
                return True
        elif target_type == "array":
            if echo_type == "array" and isinstance(candidate, list):
                return True
    return False


def unwrap_schema_echo_arguments(
    args: Any,
    tool_definition: dict[str, Any] | None,
) -> tuple[Any, bool]:
    """Unwrap JSON-Schema property wrappers echoed inside tool arguments by 1.5B-3B models.

    Returns ``(normalized_args, was_unwrapped)`` without ever mutating ``args`` in place.
    Genuine nested ``dict`` values (or parameters whose schema accepts ``object``) are
    preserved untouched.
    """
    if not isinstance(args, dict) or not isinstance(tool_definition, dict):
        return args, False

    properties = _extract_tool_properties(tool_definition)
    if not properties or not args:
        return args, False

    unwrapped_updates: dict[str, Any] = {}
    for key, val in args.items():
        spec = properties.get(key)
        if not isinstance(spec, dict) or not isinstance(val, dict) or not val:
            continue

        # Never unwrap when the parameter schema legitimately accepts JSON objects.
        declared_types = _spec_declared_types(spec)
        if not declared_types or "object" in declared_types:
            continue

        if not set(val.keys()).issubset(_SCHEMA_ECHO_ALLOWED_KEYS):
            continue

        raw_echo_type = val.get("type")
        if type(raw_echo_type) is not str or not raw_echo_type.strip():
            continue
        echo_type = raw_echo_type.strip().lower()

        payload_key: str | None = None
        for candidate_key in _SCHEMA_ECHO_PAYLOAD_PRIORITY:
            if candidate_key in val:
                payload_key = candidate_key
                break
        if payload_key is None:
            continue

        candidate = val[payload_key]
        if _candidate_matches_schema_type(declared_types, echo_type, candidate):
            unwrapped_updates[key] = (
                copy.deepcopy(candidate) if isinstance(candidate, list) else candidate
            )

    if not unwrapped_updates:
        return args, False

    normalized = dict(args)
    normalized.update(unwrapped_updates)
    return normalized, True


def _is_pure_json_document(text: str) -> bool:
    """Return True if `text` is a standalone JSON object/array data example."""
    stripped = text.strip()
    if not stripped or stripped[0] not in "{[":
        return False
    try:
        parsed = json.loads(stripped)
    except Exception:
        return False
    return isinstance(parsed, (dict, list))


def _is_code_statement_line(line: str, *, in_active_code_run: bool = False) -> bool:
    """Classify whether one line is a Python/JS implementation statement (not prose/signature)."""
    stripped = line.strip()
    if not stripped:
        return False
    if _PROSE_LIST_PREFIX_RE.match(stripped):
        return False

    indent_width = len(line) - len(line.lstrip(" \t"))
    is_indented = indent_width >= 2

    if _PY_COMPOUND_HEADER_RE.match(stripped):
        return True
    if _IMPORT_EXPORT_LINE_RE.match(stripped):
        return True
    if _JS_COMPOUND_HEADER_RE.match(stripped):
        return True
    if _TOP_LEVEL_CALL_STMT_RE.match(stripped):
        return True
    if _ASSIGNMENT_STMT_RE.match(stripped):
        return True
    if _JS_SEMICOLON_STMT_RE.match(stripped):
        return True

    if _CONTROL_FLOW_STMT_RE.match(stripped):
        # Indented control-flow statements or explicit code-shaped return/raise statements.
        if is_indented or in_active_code_run:
            return True
        if re.match(
            r"^(?:return\s+[\w\[\(\{'\"-]|raise\s+[A-Z]\w*|throw\s+new\s+|assert\s+.+|pass$|break$|continue$)",
            stripped,
        ):
            return True

    if is_indented and in_active_code_run:
        if _INDENTED_CODE_CALL_RE.match(stripped):
            return True
        if stripped.startswith(("#", "//")):
            return True
        if re.match(r"^['\"A-Za-z_$][\w$'\"]*\s*:\s*.+", stripped) or stripped.endswith(","):
            return True

    if in_active_code_run and _CLOSING_BRACE_ONLY_RE.match(stripped):
        return True

    return False


def validate_no_code_leakage(text: str) -> list[str]:
    """Inspect `text` for leaked multi-line implementation code; return violation descriptions."""
    if not isinstance(text, str):
        raise ValueError(f"Expected text to be str, got {type(text).__name__}.")
    if not text.strip():
        return []

    violations: list[str] = []

    # 1. Fenced code blocks (` ``` `) with >= 4 lines.
    for match in _FENCED_BLOCK_RE.finditer(text):
        full_block = match.group(0)
        inner_body = match.group(1)
        total_lines = len(full_block.splitlines())
        inner_nonempty = [ln for ln in inner_body.splitlines() if ln.strip()]
        if len(inner_nonempty) >= 4 or (total_lines >= 4 and len(inner_nonempty) >= 2):
            if not _is_pure_json_document(inner_body):
                violations.append(
                    f"fenced code block with {max(len(inner_nonempty), total_lines)} lines (>= 4)"
                )

    # 2. >= 4 consecutive lines of Python/JS implementation statements.
    if _is_pure_json_document(text):
        return violations

    lines = text.splitlines()
    streak_count = 0
    streak_first_line = ""
    bridged_blank = False

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            # Allow at most a single blank line inside an active code block without resetting,
            # provided the following line continues the implementation statements.
            if (
                streak_count > 0
                and not bridged_blank
                and idx + 1 < len(lines)
                and _is_code_statement_line(lines[idx + 1], in_active_code_run=True)
            ):
                bridged_blank = True
                continue
            streak_count = 0
            streak_first_line = ""
            bridged_blank = False
            continue

        if _is_code_statement_line(line, in_active_code_run=(streak_count > 0)):
            if streak_count == 0:
                streak_first_line = stripped[:60]
            streak_count += 1
            bridged_blank = False
            if streak_count == 4:
                violations.append(
                    f">= 4 consecutive implementation statement lines starting at {streak_first_line!r}"
                )
        else:
            streak_count = 0
            streak_first_line = ""
            bridged_blank = False

        # 3. Single-line semicolon-packed implementation code (>= 4 statements on one line).
        if stripped.count(";") >= 3:
            semi_clauses = [seg.strip() for seg in stripped.split(";") if seg.strip()]
            code_clauses = sum(
                1
                for seg in semi_clauses
                if _is_code_statement_line(seg, in_active_code_run=True)
                or bool(
                    re.match(
                        r"^(?:const|let|var|import|export|function|return|if|for|while| document\.|window\.)",
                        seg,
                    )
                )
            )
            if code_clauses >= 4:
                violations.append(
                    f"single-line semicolon-packed implementation ({code_clauses} statements) starting at {stripped[:60]!r}"
                )

    return violations


def _assert_no_code_leakage_in_value(value: Any, field_label: str) -> None:
    """Recursively enforce anti-code-leakage on string, list, or dict plan fields."""
    if value is None:
        return
    if isinstance(value, str):
        violations = validate_no_code_leakage(value)
        if violations:
            raise ValueError(
                f"Decomposition plan rejected: code leakage detected in {field_label} "
                f"({'; '.join(violations)})."
            )
        return
    if isinstance(value, list):
        for idx, item in enumerate(value):
            _assert_no_code_leakage_in_value(item, f"{field_label}[{idx}]")
        if all(isinstance(item, str) for item in value) and len(value) >= 4:
            # Guard against line-by-line code arrays smuggled inside list fields.
            joined_violations = validate_no_code_leakage("\n".join(value))
            if joined_violations:
                raise ValueError(
                    f"Decomposition plan rejected: code leakage detected across {field_label} "
                    f"({'; '.join(joined_violations)})."
                )
        return
    if isinstance(value, dict):
        for k, v in value.items():
            if isinstance(k, str):
                _assert_no_code_leakage_in_value(k, f"{field_label}.<key>")
            _assert_no_code_leakage_in_value(v, f"{field_label}.{k}")


def _validate_str_list(
    raw_val: Any,
    field_name: str,
    *,
    allow_empty: bool,
) -> list[str]:
    if not isinstance(raw_val, list):
        raise ValueError(f"{field_name} must be a list of strings.")
    cleaned: list[str] = []
    for idx, item in enumerate(raw_val):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{field_name}[{idx}] must be a non-empty string.")
        cleaned.append(item.strip())
    if not allow_empty and not cleaned:
        raise ValueError(f"{field_name} must be a non-empty list of strings.")
    return cleaned


def _validate_acyclic_dependencies(children: list[dict[str, Any]]) -> None:
    known_ids = {child["id"] for child in children}
    adj: dict[str, list[str]] = {child["id"]: [] for child in children}
    for child in children:
        cid = child["id"]
        for dep in child["depends_on"]:
            if dep not in known_ids:
                raise ValueError(
                    f"Child {cid!r} depends_on unknown sibling id {dep!r}."
                )
            if dep == cid:
                raise ValueError(f"Child {cid!r} cannot depend on itself.")
            adj[cid].append(dep)

    # Cycle check via 3-color DFS (0 = unvisited, 1 = visiting, 2 = visited)
    state: dict[str, int] = {cid: 0 for cid in known_ids}
    for start in children:
        start_id = start["id"]
        if state[start_id] != 0:
            continue
        stack: list[tuple[str, int]] = [(start_id, 0)]
        state[start_id] = 1
        while stack:
            node, edge_idx = stack[-1]
            neighbors = adj[node]
            if edge_idx < len(neighbors):
                stack[-1] = (node, edge_idx + 1)
                nxt = neighbors[edge_idx]
                if state[nxt] == 1:
                    raise ValueError(
                        f"Dependency cycle detected involving child {nxt!r}."
                    )
                if state[nxt] == 0:
                    state[nxt] = 1
                    stack.append((nxt, 0))
            else:
                state[node] = 2
                stack.pop()


def load_and_validate_decomposition_plan(
    plan_source: dict[str, Any] | str | Path,
) -> dict[str, Any]:
    """Load, normalize, and validate an external/frontier code-free decomposition plan packet."""
    if isinstance(plan_source, dict):
        raw_plan = copy.deepcopy(plan_source)
    elif isinstance(plan_source, (str, Path)):
        if isinstance(plan_source, str) and not plan_source.strip():
            raise ValueError("Decomposition plan file path must be non-empty.")
        plan_path = Path(plan_source)
        if not plan_path.is_file():
            raise ValueError(f"Decomposition plan file not found: {plan_path}")
        try:
            raw_plan = json.loads(plan_path.read_text(encoding="utf-8-sig"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON in decomposition plan {plan_path}: {exc}") from exc
        if not isinstance(raw_plan, dict):
            raise ValueError("Decomposition plan JSON root must be an object.")
    else:
        raise ValueError(
            f"plan_source must be a dict, str path, or Path, got {type(plan_source).__name__}."
        )

    # Enforce anti-code-leakage across any extra metadata fields without breaking
    # benign benchmark/harness annotations (e.g. task_id, notes).
    for extra_top_key in set(raw_plan.keys()) - _ALLOWED_TOP_LEVEL_PLAN_KEYS:
        _assert_no_code_leakage_in_value(raw_plan[extra_top_key], extra_top_key)

    schema_version = raw_plan.get("schema_version")
    if not isinstance(schema_version, str) or schema_version.strip() != PLAN_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported or missing schema_version {schema_version!r}; expected {PLAN_SCHEMA_VERSION!r}."
        )

    regime = validate_decomposition_regime(raw_plan.get("regime"))  # type: ignore[arg-type]

    orchestrator_id = raw_plan.get("orchestrator_id")
    if not isinstance(orchestrator_id, str) or not orchestrator_id.strip():
        raise ValueError("orchestrator_id must be a non-empty string.")
    orchestrator_id = orchestrator_id.strip()

    goal = raw_plan.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise ValueError("Root goal must be a non-empty string.")
    _assert_no_code_leakage_in_value(goal, "goal")
    goal = goal.strip()

    raw_constraints = raw_plan.get("constraints")
    constraints = (
        []
        if raw_constraints is None
        else _validate_str_list(raw_constraints, "constraints", allow_empty=True)
    )
    _assert_no_code_leakage_in_value(raw_constraints, "constraints")

    raw_criteria = raw_plan.get("success_criteria")
    success_criteria = (
        []
        if raw_criteria is None
        else _validate_str_list(raw_criteria, "success_criteria", allow_empty=True)
    )
    _assert_no_code_leakage_in_value(raw_criteria, "success_criteria")

    raw_children = raw_plan.get("children")
    if not isinstance(raw_children, list) or not (1 <= len(raw_children) <= MAX_PLAN_CHILDREN):
        raise ValueError(
            f"children must be a list of 1..{MAX_PLAN_CHILDREN} child specs."
        )

    normalized_children: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for idx, raw_child in enumerate(raw_children, start=1):
        if not isinstance(raw_child, dict):
            raise ValueError(f"children[{idx - 1}] must be a dict.")

        for extra_child_key in set(raw_child.keys()) - _ALLOWED_CHILD_PLAN_KEYS:
            _assert_no_code_leakage_in_value(
                raw_child[extra_child_key],
                f"children[{idx - 1}].{extra_child_key}",
            )

        raw_id = raw_child.get("id")
        if raw_id is None:
            child_id = str(idx)
        elif isinstance(raw_id, str) and raw_id.strip():
            child_id = raw_id.strip()
        else:
            raise ValueError(f"children[{idx - 1}].id must be a non-empty string when provided.")

        if child_id in seen_ids:
            raise ValueError(f"Duplicate child id {child_id!r} in decomposition plan.")
        seen_ids.add(child_id)

        raw_child_goal = raw_child.get("goal")
        if not isinstance(raw_child_goal, str) or not raw_child_goal.strip():
            raise ValueError(f"children[{idx - 1}].goal must be a non-empty string.")
        _assert_no_code_leakage_in_value(raw_child_goal, f"children[{idx - 1}].goal")
        child_goal = raw_child_goal.strip()

        raw_done_when = raw_child.get("done_when")
        _assert_no_code_leakage_in_value(raw_done_when, f"children[{idx - 1}].done_when")
        done_when = _validate_str_list(
            raw_done_when,
            f"children[{idx - 1}].done_when",
            allow_empty=False,
        )

        raw_owned = raw_child.get("owned_mutation_paths")
        owned_mutation_paths = (
            []
            if raw_owned is None
            else _validate_str_list(
                raw_owned,
                f"children[{idx - 1}].owned_mutation_paths",
                allow_empty=True,
            )
        )

        raw_scope_hint = raw_child.get("scope_hint")
        scope_hint = (
            list(owned_mutation_paths)
            if raw_scope_hint is None
            else _validate_str_list(
                raw_scope_hint,
                f"children[{idx - 1}].scope_hint",
                allow_empty=True,
            )
        )

        raw_ro = raw_child.get("read_only_sibling_paths")
        read_only_sibling_paths = (
            []
            if raw_ro is None
            else _validate_str_list(
                raw_ro,
                f"children[{idx - 1}].read_only_sibling_paths",
                allow_empty=True,
            )
        )

        raw_deps = raw_child.get("depends_on")
        depends_on = (
            []
            if raw_deps is None
            else _validate_str_list(
                raw_deps,
                f"children[{idx - 1}].depends_on",
                allow_empty=True,
            )
        )

        raw_ic = raw_child.get("interface_contract")
        if raw_ic is not None and not isinstance(raw_ic, (str, dict)):
            raise ValueError(
                f"children[{idx - 1}].interface_contract must be a str or dict when provided."
            )
        _assert_no_code_leakage_in_value(raw_ic, f"children[{idx - 1}].interface_contract")
        interface_contract = (
            raw_ic.strip() if isinstance(raw_ic, str) else copy.deepcopy(raw_ic)
        )

        raw_oracles = raw_child.get("verification_oracles")
        verification_oracles: list[dict[str, Any]] = []
        if raw_oracles is not None:
            if not isinstance(raw_oracles, list):
                raise ValueError(
                    f"children[{idx - 1}].verification_oracles must be a list of oracle dicts."
                )
            for o_idx, raw_o in enumerate(raw_oracles):
                if not isinstance(raw_o, dict):
                    raise ValueError(
                        f"children[{idx - 1}].verification_oracles[{o_idx}] must be a dict."
                    )
                extra_o_keys = set(raw_o.keys()) - _ALLOWED_ORACLE_KEYS
                if extra_o_keys:
                    raise ValueError(
                        f"Unsupported oracle keys {sorted(extra_o_keys)} in "
                        f"children[{idx - 1}].verification_oracles[{o_idx}]."
                    )
                kind = str(raw_o.get("kind") or "").strip().lower()
                if kind not in _ALLOWED_ORACLE_KINDS:
                    raise ValueError(
                        f"Invalid oracle kind {kind!r} in children[{idx - 1}].verification_oracles[{o_idx}]."
                    )
                _assert_no_code_leakage_in_value(
                    raw_o,
                    f"children[{idx - 1}].verification_oracles[{o_idx}]",
                )
                if "target" in raw_o and raw_o["target"] is not None:
                    if not isinstance(raw_o["target"], str) or not raw_o["target"].strip():
                        raise ValueError(
                            f"Oracle 'target' in children[{idx - 1}].verification_oracles[{o_idx}] must be a non-empty str."
                        )
                if "function" in raw_o and raw_o["function"] is not None:
                    if not isinstance(raw_o["function"], str) or not raw_o["function"].strip():
                        raise ValueError(
                            f"Oracle 'function' in children[{idx - 1}].verification_oracles[{o_idx}] must be a non-empty str."
                        )
                if "arguments" in raw_o and raw_o["arguments"] is not None and not isinstance(raw_o["arguments"], list):
                    raise ValueError(
                        f"Oracle 'arguments' in children[{idx - 1}].verification_oracles[{o_idx}] must be a list."
                    )
                if "expected_exit_code" in raw_o and raw_o["expected_exit_code"] is not None:
                    eec = raw_o["expected_exit_code"]
                    if isinstance(eec, bool) or not (isinstance(eec, int) or eec == "nonzero"):
                        raise ValueError(
                            f"Oracle 'expected_exit_code' in children[{idx - 1}].verification_oracles[{o_idx}] "
                            "must be an int or 'nonzero'."
                        )
                for str_field in ("expected_stdout", "expected_stdout_contains"):
                    if str_field in raw_o and raw_o[str_field] is not None and not isinstance(raw_o[str_field], str):
                        raise ValueError(
                            f"Oracle {str_field!r} in children[{idx - 1}].verification_oracles[{o_idx}] must be a str."
                        )
                for list_field in ("expected_exports", "expected_source_substrings"):
                    if list_field in raw_o and raw_o[list_field] is not None:
                        val_lf = raw_o[list_field]
                        if (
                            not isinstance(val_lf, list)
                            or not val_lf
                            or any(not isinstance(item, str) or not item.strip() for item in val_lf)
                        ):
                            raise ValueError(
                                f"Oracle {list_field!r} in children[{idx - 1}].verification_oracles[{o_idx}] "
                                "must be a non-empty list of non-empty strings."
                            )
                        if not isinstance(raw_o.get("target"), str) or not raw_o["target"].strip():
                            raise ValueError(
                                f"Oracle with {list_field!r} in children[{idx - 1}].verification_oracles[{o_idx}] "
                                "requires explicit non-empty 'target'."
                            )
                if kind in {"run_file", "unittest", "verify_web_app"}:
                    target = raw_o.get("target")
                    if not isinstance(target, str) or not target.strip():
                        raise ValueError(
                            f"Oracle kind {kind!r} requires non-empty 'target' string."
                        )
                elif kind == "run_command":
                    cmd_str = raw_o.get("command")
                    if not isinstance(cmd_str, str) or not cmd_str.strip():
                        raise ValueError(
                            "Oracle kind 'run_command' requires non-empty 'command' string."
                        )
                norm_o = copy.deepcopy(raw_o)
                norm_o["kind"] = kind
                verification_oracles.append(norm_o)

        normalized_children.append({
            "id": child_id,
            "goal": child_goal,
            "done_when": done_when,
            "scope_hint": scope_hint,
            "owned_mutation_paths": owned_mutation_paths,
            "read_only_sibling_paths": read_only_sibling_paths,
            "depends_on": depends_on,
            "interface_contract": interface_contract,
            "verification_oracles": verification_oracles,
        })

    _validate_acyclic_dependencies(normalized_children)

    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "regime": regime,
        "orchestrator_id": orchestrator_id,
        "goal": goal,
        "constraints": constraints,
        "success_criteria": success_criteria,
        "children": normalized_children,
    }


def _contains_concrete_workspace_file(candidates: list[Any]) -> bool:
    for entry in candidates:
        if not isinstance(entry, str):
            continue
        text = entry.strip()
        if not text or "://" in text:
            continue
        for match in _CONCRETE_FILE_EXT_RE.finditer(text):
            token = match.group(1).replace("\\", "/").strip("/")
            if not token or token.startswith("."):
                continue
            norm = posixpath.normpath(token)
            if norm.startswith("../") or norm == "..":
                continue
            if "/" not in norm and norm.lower() in _BARE_LIBRARY_NAMES:
                continue
            return True
    return False


def _flatten_interface_contract_text(interface_contract: Any) -> str:
    if interface_contract is None:
        return ""
    if isinstance(interface_contract, str):
        return interface_contract
    if isinstance(interface_contract, dict):
        if not interface_contract:
            return ""
        return json.dumps(interface_contract, ensure_ascii=False, sort_keys=True)
    return str(interface_contract)


def _has_callable_or_cli_or_dom_signature(combined_text: str) -> bool:
    if _CLI_FLAG_RE.search(combined_text):
        return True
    if _CLASS_OR_BRIDGE_RE.search(combined_text):
        return True
    for match in _CALLABLE_SIGNATURE_RE.finditer(combined_text):
        inner = match.group(2).strip()
        # Exclude English plural parentheticals like "file(s)" or "match(es)".
        if inner.lower() in {"s", "es"}:
            continue
        return True
    for dom_match in _DOM_ID_CONTRACT_RE.finditer(combined_text):
        dom_id = dom_match.group(1)
        if not _HEX_COLOR_RE.match(dom_id):
            return True
    return False


def _has_io_type_or_schema(combined_text: str, interface_contract: Any) -> bool:
    if isinstance(interface_contract, dict) and bool(interface_contract):
        return True
    if _IO_TYPE_TOKEN_RE.search(combined_text):
        return True
    if _NONEMPTY_BRACE_SCHEMA_RE.search(combined_text):
        return True
    return False


def compute_child_contract_indicators(child_spec: dict[str, Any]) -> dict[str, bool]:
    """Compute the 5 binary structural completeness indicators for one child task spec."""
    if not isinstance(child_spec, dict):
        raise ValueError(f"child_spec must be a dict, got {type(child_spec).__name__}.")

    owned_paths = child_spec.get("owned_mutation_paths")
    scope_hint = child_spec.get("scope_hint")
    owner_candidates: list[Any] = []
    if isinstance(owned_paths, list):
        owner_candidates.extend(owned_paths)
    if isinstance(scope_hint, list):
        owner_candidates.extend(scope_hint)

    goal_text = child_spec.get("goal") if isinstance(child_spec.get("goal"), str) else ""
    raw_done_when = child_spec.get("done_when")
    if isinstance(raw_done_when, list):
        done_when_text = "\n".join(str(item) for item in raw_done_when if isinstance(item, str))
    elif isinstance(raw_done_when, str):
        done_when_text = raw_done_when
    else:
        done_when_text = ""

    interface_contract = child_spec.get("interface_contract")
    ic_text = _flatten_interface_contract_text(interface_contract)
    combined_text = "\n".join(part for part in (goal_text, done_when_text, ic_text) if part)

    has_explicit_file_owner = _contains_concrete_workspace_file(owner_candidates)
    has_callable_or_cli_signature = _has_callable_or_cli_or_dom_signature(combined_text)
    has_io_type_or_schema = _has_io_type_or_schema(combined_text, interface_contract)
    has_edge_or_error_invariant = bool(_EDGE_OR_ERROR_INVARIANT_RE.search(combined_text))
    has_executable_oracle = bool(_EXECUTABLE_ORACLE_RE.search(done_when_text))

    return {
        "has_explicit_file_owner": has_explicit_file_owner,
        "has_callable_or_cli_signature": has_callable_or_cli_signature,
        "has_io_type_or_schema": has_io_type_or_schema,
        "has_edge_or_error_invariant": has_edge_or_error_invariant,
        "has_executable_oracle": has_executable_oracle,
    }


def compute_child_contract_completeness(child_spec: dict[str, Any]) -> float:
    """Return deterministic contract completeness score kappa_j in [0.0, 1.0]."""
    indicators = compute_child_contract_indicators(child_spec)
    matched = sum(1 for present in indicators.values() if present)
    return round(matched / 5.0, 4)


def compute_plan_completeness_summary(children: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize contract completeness (kappa) across all children of a decomposition plan."""
    if not isinstance(children, list):
        raise ValueError(f"children must be a list of dicts, got {type(children).__name__}.")

    k = len(children)
    if k == 0:
        return {
            "num_children": 0,
            "boundary_count": 0,
            "mean_kappa": 0.0,
            "min_kappa": 0.0,
            "child_kappas": [],
        }

    child_kappas = [compute_child_contract_completeness(child) for child in children]
    mean_kappa = round(sum(child_kappas) / k, 4)
    min_kappa = round(min(child_kappas), 4)
    return {
        "num_children": k,
        "boundary_count": max(0, k - 1),
        "mean_kappa": mean_kappa,
        "min_kappa": min_kappa,
        "child_kappas": child_kappas,
    }


def _validate_probability(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a numeric rate in [0.0, 1.0].")
    fval = float(value)
    if not math.isfinite(fval) or fval < 0.0 or fval > 1.0:
        raise ValueError(f"{name} must be within [0.0, 1.0], got {value!r}.")
    return fval


def predict_compositional_pass_probability(
    num_children: int,
    leaf_error_rate: float,
    boundary_mismatch_rate: float,
    verification_recovery_prob: float = 0.0,
) -> float:
    """Verification-gated Dziri et al. (NeurIPS 2023) compositional pass-probability estimator.

    Computes:
        eps_eff = leaf_error_rate * (1 - verification_recovery_prob)
        P_sys   = (1 - eps_eff)^k * (1 - boundary_mismatch_rate)^max(0, k - 1)
    clamped to [0.0, 1.0] and rounded to 6 decimal places.
    """
    if isinstance(num_children, bool) or not isinstance(num_children, int) or num_children < 1:
        raise ValueError(
            f"num_children must be an integer >= 1, got {num_children!r}."
        )

    eps_w = _validate_probability(leaf_error_rate, "leaf_error_rate")
    delta = _validate_probability(boundary_mismatch_rate, "boundary_mismatch_rate")
    recovery = _validate_probability(verification_recovery_prob, "verification_recovery_prob")

    eps_eff = eps_w * (1.0 - recovery)
    leaf_survival = (1.0 - eps_eff) ** num_children
    boundary_survival = (1.0 - delta) ** max(0, num_children - 1)
    prob = max(0.0, min(1.0, leaf_survival * boundary_survival))
    return round(prob, 6)
