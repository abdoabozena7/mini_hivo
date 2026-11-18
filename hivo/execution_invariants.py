"""Deterministic execution-time preservation invariants.

This module is intentionally small and provider-free.  It turns already
approved repository evidence into a bounded, immutable set of current
interface facts.  The parser is conservative: unsupported or ambiguous
JavaScript is an observation that cannot become Worker authority.

The module does not decide what a change should look like and it never grants
mutation authority.  It only makes the current facts that a bounded Worker
must preserve explicit before the first provider generation.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable

from hivo.requirements import freeze


SCHEMA_VERSION = "25.2-EXECUTION-INVARIANTS-1"
FUNCTION_SIGNATURE = "FUNCTION_SIGNATURE"
RETURN_SHAPE = "RETURN_SHAPE"
EXACT_EXISTING_OUTPUT = "EXACT_EXISTING_OUTPUT"
CONSUMER_EXPECTATION = "CONSUMER_EXPECTATION"
INTERFACE_COMPATIBILITY = "INTERFACE_COMPATIBILITY"
STATE_OWNER = "STATE_OWNER"
REQUIRED_INTERFACE_REUSE = "REQUIRED_INTERFACE_REUSE"
DNT_PRESERVATION = "DNT_PRESERVATION"

INVARIANT_TYPES = (
    FUNCTION_SIGNATURE,
    RETURN_SHAPE,
    EXACT_EXISTING_OUTPUT,
    CONSUMER_EXPECTATION,
    INTERFACE_COMPATIBILITY,
    STATE_OWNER,
    REQUIRED_INTERFACE_REUSE,
    DNT_PRESERVATION,
)

PRESERVE = "PRESERVE"
CHANGE_AUTHORIZED = "CHANGE_AUTHORIZED"
NOT_APPLICABLE = "NOT_APPLICABLE"
CHANGE_NOT_AUTHORIZED = "NOT_AUTHORIZED"
CHANGE_AUTHORITY_GRANTED = "AUTHORIZED"

VALID = "VALID"
UNSUPPORTED = "UNSUPPORTED"
CONFLICT = "CONFLICT"
STALE = "STALE"

EXECUTION_INVARIANT_EVIDENCE_CONFLICT = "EXECUTION_INVARIANT_EVIDENCE_CONFLICT"
EXECUTION_INVARIANT_UNSUPPORTED = "EXECUTION_INVARIANT_UNSUPPORTED"
EXECUTION_INVARIANT_INVALID = "EXECUTION_INVARIANT_INVALID"
EXECUTION_INVARIANT_SET_REQUIRED = "EXECUTION_INVARIANT_SET_REQUIRED"
EXECUTION_INVARIANT_CONTEXT_OVERFLOW = "WORKER_EXECUTION_INVARIANT_CONTEXT_OVERFLOW"
REAPPROVAL_REQUIRED = "REAPPROVAL_REQUIRED"

MAX_INVARIANTS = 24
MAX_PROJECTED_INVARIANTS = 16
MAX_EVIDENCE_BINDINGS = 32
MAX_CONSUMER_EXPECTATIONS = 24
MAX_OUTPUTS = 16
MAX_TEXT = 900
MAX_PATH = 300
MAX_SYMBOL = 240
MAX_CONTEXT_CHARS = 4200


class ExecutionInvariantError(ValueError):
    """A deterministic fail-closed invariant construction/validation error."""

    def __init__(self, code: str, message: str, details: Iterable[Any] | None = None):
        super().__init__(message)
        self.code = str(code)
        self.details = list(details or [])


class _FrozenRecord(dict):
    """JSON-shaped immutable record with normal mapping access."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("execution invariant records are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other: Any) -> Any:
        self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


class ExecutionInvariantSet(_FrozenRecord):
    """Immutable canonical current-interface fact set."""


class WorkerExecutionInvariantProjection(_FrozenRecord):
    """Immutable compact model-facing projection of execution invariants."""


PRECOMMIT_SCHEMA_VERSION = "25.5-PRECOMMIT-EXECUTION-INVARIANT-1"
EXECUTION_INVARIANT_MUTATION_VIOLATION = "EXECUTION_INVARIANT_MUTATION_VIOLATION"
PRECOMMIT_ALLOWED = "PASS"
PRECOMMIT_DNT_VIOLATION = "DNT_VIOLATION"


class PreCommitInvariantAudit(_FrozenRecord):
    """Immutable evidence for one candidate mutation before filesystem commit."""


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
    return str(value or "").strip()[:limit]


def _path(value: Any) -> str:
    result = _text(value, MAX_PATH).replace("\\", "/")
    while result.startswith("./"):
        result = result[2:]
    return result.rstrip("/")


def _symbol(value: Any) -> str:
    return _text(value, MAX_SYMBOL)


def _unique(values: Iterable[Any], limit: int | None = None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _text(value)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
        if limit is not None and len(result) >= limit:
            break
    return result


def _norm_values(values: Iterable[Any]) -> list[str]:
    return _unique(values, MAX_OUTPUTS)


def _line(text: str, offset: int) -> int:
    return text.count("\n", 0, max(0, offset)) + 1


def _freeze_record(record_type: type[_FrozenRecord], value: dict[str, Any]) -> _FrozenRecord:
    result = record_type()
    dict.__init__(result, ((key, freeze(item)) for key, item in value.items()))
    return result


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":")))


def _metric_is_zero(value: Any) -> bool:
    try:
        return int(value or 0) == 0
    except (TypeError, ValueError, OverflowError):
        return False


def _mask_non_code(source: str) -> str:
    """Mask comments and string bodies while keeping code positions stable."""
    chars = list(source)
    index = 0
    length = len(source)
    state = "code"
    quote = ""
    while index < length:
        current = source[index]
        following = source[index + 1] if index + 1 < length else ""
        if state == "code":
            if current == "/" and following == "/":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "line_comment"
                continue
            if current == "/" and following == "*":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "block_comment"
                continue
            if current in {"'", '"', "`"}:
                quote = current
                chars[index] = " "
                index += 1
                state = "string"
                continue
            index += 1
            continue
        if state == "line_comment":
            if current == "\n":
                state = "code"
            else:
                chars[index] = " "
            index += 1
            continue
        if state == "block_comment":
            if current == "*" and following == "/":
                chars[index] = chars[index + 1] = " "
                index += 2
                state = "code"
            else:
                if current != "\n":
                    chars[index] = " "
                index += 1
            continue
        # JavaScript template literals are treated conservatively as opaque
        # strings.  A template expression is therefore not mistaken for a
        # deterministic return fact.
        if current == "\\":
            if current != "\n":
                chars[index] = " "
            if index + 1 < length and source[index + 1] != "\n":
                chars[index + 1] = " "
                index += 2
            else:
                index += 1
            continue
        if current == quote:
            chars[index] = " "
            index += 1
            state = "code"
            continue
        if current != "\n":
            chars[index] = " "
        index += 1
    return "".join(chars)


def _balanced_end(source: str, opening: int, open_char: str = "{", close_char: str = "}") -> int | None:
    if opening < 0 or opening >= len(source) or source[opening] != open_char:
        return None
    depth = 0
    index = opening
    masked = _mask_non_code(source)
    while index < len(source):
        char = masked[index]
        if char == open_char:
            depth += 1
        elif char == close_char:
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _split_top_level(source: str, delimiter: str = ",") -> list[str]:
    """Split a short JS expression without interpreting its values."""
    masked = _mask_non_code(source)
    result: list[str] = []
    start = 0
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{",
    }
    for index, char in enumerate(masked):
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
            else:
                return []
        elif char == delimiter and not stack:
            result.append(source[start:index].strip())
            start = index + 1
    result.append(source[start:].strip())
    return result


def _scan_expression_end(source: str, start: int) -> int:
    masked = _mask_non_code(source)
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{",
    }
    index = start
    while index < len(source):
        char = masked[index]
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
        elif char == ";" and not stack:
            return index
        elif char == "\n" and not stack:
            return index
        index += 1
    return len(source)


def _decode_js_string(expression: str) -> str | None:
    value = expression.strip()
    if len(value) < 2 or value[0] not in {"'", '"'} or value[-1] != value[0]:
        return None
    body = value[1:-1]

    def unicode_replace(match: re.Match[str]) -> str:
        try:
            return chr(int(match.group(1), 16))
        except ValueError:
            return match.group(0)

    body = re.sub(r"\\u([0-9a-fA-F]{4})", unicode_replace, body)
    replacements = {
        "\\n": "\n", "\\r": "\r", "\\t": "\t", "\\b": "\b",
        "\\f": "\f", "\\v": "\v", "\\\\": "\\", "\\'": "'", '\\"': '"',
    }
    for old, new in replacements.items():
        body = body.replace(old, new)
    if "`" in body:
        return body
    return body


def _top_level_ternary(expression: str) -> tuple[str, str, str] | None:
    masked = _mask_non_code(expression)
    stack: list[str] = []
    pairs = {")": "(", "]": "[", "}": "{",
    }
    question = None
    nested_questions = 0
    for index, char in enumerate(masked):
        if char in "([{":
            stack.append(char)
        elif char in ")]}":
            if stack and stack[-1] == pairs[char]:
                stack.pop()
        elif not stack and char == "?":
            if question is None:
                question = index
            else:
                nested_questions += 1
        elif not stack and char == ":" and question is not None:
            if nested_questions:
                nested_questions -= 1
            else:
                return (
                    expression[:question].strip(),
                    expression[question + 1:index].strip(),
                    expression[index + 1:].strip(),
                )
    return None


def _return_expression_facts(expression: str) -> dict[str, Any]:
    value = expression.strip()
    ternary = _top_level_ternary(value)
    branches = [value]
    if ternary is not None:
        branches = [ternary[1], ternary[2]]
    literals = []
    shapes = []
    for branch in branches:
        decoded = _decode_js_string(branch)
        if decoded is not None:
            shapes.append("primitive string")
            literals.append(decoded)
            continue
        if branch.startswith("{") and branch.endswith("}"):
            shapes.append("object")
            continue
        if branch.startswith("[") and branch.endswith("]"):
            shapes.append("array")
            continue
        if re.fullmatch(r"(?:true|false|null|undefined|-?\d+(?:\.\d+)?)", branch):
            shapes.append("primitive non-string")
            continue
        shapes.append("unsupported")
    return {
        "shapes": _unique(shapes, MAX_OUTPUTS),
        "literals": _norm_values(literals),
        "expression": _text(value, MAX_TEXT),
    }


def extract_source_contract(source_text: str, symbol: str, *, path: str = "", source_hash: str = "") -> dict[str, Any]:
    """Extract one simple function's current return contract.

    The target symbol is supplied by approved structured authority.  The
    extractor never searches for a fixture-specific name or output literal.
    """
    source = str(source_text or "")
    target = _symbol(symbol)
    if not source or not target:
        return {"status": UNSUPPORTED, "code": EXECUTION_INVARIANT_UNSUPPORTED, "errors": ["source and symbol are required"]}
    masked = _mask_non_code(source)
    pattern = re.compile(
        rf"\bfunction\s+{re.escape(target)}\s*\(([^)]*)\)\s*\{{",
        re.MULTILINE,
    )
    matches = list(pattern.finditer(masked))
    if len(matches) != 1:
        return {
            "status": UNSUPPORTED,
            "code": EXECUTION_INVARIANT_UNSUPPORTED,
            "errors": [f"expected exactly one supported function declaration for {target}"],
        }
    match = matches[0]
    opening = masked.find("{", match.start(), match.end())
    closing = _balanced_end(source, opening)
    if opening < 0 or closing is None:
        return {"status": UNSUPPORTED, "code": EXECUTION_INVARIANT_UNSUPPORTED, "errors": ["function body is not balanced"]}
    parameters = [item.strip() for item in match.group(1).split(",") if item.strip()]
    signature = f"{target}({', '.join(parameters)})"
    body = source[opening + 1:closing]
    body_masked = _mask_non_code(body)
    returns = []
    for return_match in re.finditer(r"\breturn\b", body_masked):
        start = return_match.end()
        end = _scan_expression_end(body, start)
        expression = body[start:end].strip()
        if not expression:
            return {
                "status": UNSUPPORTED,
                "code": EXECUTION_INVARIANT_UNSUPPORTED,
                "errors": ["return without a deterministic expression"],
            }
        facts = _return_expression_facts(expression)
        returns.append({
            **facts,
            "line_start": _line(source, opening + 1 + return_match.start()),
            "line_end": _line(source, opening + 1 + max(return_match.start(), end - 1)),
        })
    if not returns:
        return {
            "status": UNSUPPORTED,
            "code": EXECUTION_INVARIANT_UNSUPPORTED,
            "errors": ["no deterministic return expression found"],
        }
    shapes = _unique((shape for item in returns for shape in item.get("shapes", [])), MAX_OUTPUTS)
    literals = _norm_values(value for item in returns for value in item.get("literals", []))
    if len(shapes) != 1 or shapes[0] == "unsupported":
        return {
            "status": UNSUPPORTED,
            "code": EXECUTION_INVARIANT_UNSUPPORTED,
            "errors": ["return shape is unsupported or ambiguous"],
            "returns": returns,
        }
    return {
        "status": VALID,
        "symbol": target,
        "path": _path(path),
        "signature": signature,
        "parameters": parameters,
        "return_shape": shapes[0],
        "output_literals": literals,
        "returns": returns,
        "line_start": _line(source, match.start()),
        "line_end": _line(source, closing),
        "source_hash": _text(source_hash, 128),
        "derivation": "DETERMINISTIC_SOURCE_CONTRACT_EXTRACTION",
    }


def _find_matching_call(source: str, opening: int) -> int | None:
    return _balanced_end(source, opening, "(", ")")


def _call_symbol_in_expression(expression: str, symbol: str) -> bool:
    masked = _mask_non_code(expression)
    return re.search(rf"\b{re.escape(symbol)}\s*\(", masked) is not None


def _literal_from_expression(expression: str) -> str | None:
    return _decode_js_string(expression.strip())


def extract_consumer_expectations(source_text: str, symbol: str, *, path: str = "", evidence_id: str = "", source_hash: str = "") -> dict[str, Any]:
    """Extract assertions structurally bound to ``symbol(...)``.

    A literal is evidence only when it is the expected-value argument of a
    supported assertion whose actual expression calls the target symbol.
    """
    source = str(source_text or "")
    target = _symbol(symbol)
    if not source or not target:
        return {"status": UNSUPPORTED, "code": EXECUTION_INVARIANT_UNSUPPORTED, "errors": ["consumer source and symbol are required"], "expectations": []}
    masked = _mask_non_code(source)
    expectations: list[dict[str, Any]] = []
    assertion_pattern = re.compile(r"\bassert\s*\.\s*(equal|strictEqual|deepEqual)\s*\(", re.MULTILINE)
    for match in assertion_pattern.finditer(masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _find_matching_call(source, opening)
        if closing is None:
            continue
        arguments = _split_top_level(source[opening + 1:closing])
        if len(arguments) < 2 or not _call_symbol_in_expression(arguments[0], target):
            continue
        expected = _literal_from_expression(arguments[1])
        if expected is None:
            continue
        expectations.append({
            "symbol": target,
            "expected": expected,
            "assertion": f"assert.{match.group(1)}",
            "path": _path(path),
            "evidence_id": _text(evidence_id, 160),
            "source_hash": _text(source_hash, 128),
            "line_start": _line(source, match.start()),
            "line_end": _line(source, closing),
            "derivation": "DETERMINISTIC_CONSUMER_EXPECTATION_EXTRACTION",
        })
    # Also support the common expect(actual).toBe(expected) form without
    # broadening the accepted semantics to arbitrary test prose.
    expect_pattern = re.compile(r"\bexpect\s*\(", re.MULTILINE)
    for match in expect_pattern.finditer(masked):
        opening = masked.find("(", match.start(), match.end())
        closing = _find_matching_call(source, opening)
        if closing is None or not _call_symbol_in_expression(source[opening + 1:closing], target):
            continue
        suffix = masked[closing + 1:]
        method = re.match(r"\s*\.\s*(toBe|toEqual)\s*\(", suffix)
        if method is None:
            continue
        expected_opening = closing + 1 + method.end() - 1
        expected_closing = _find_matching_call(source, expected_opening)
        if expected_closing is None:
            continue
        expected = _literal_from_expression(source[expected_opening + 1:expected_closing])
        if expected is None:
            continue
        expectations.append({
            "symbol": target,
            "expected": expected,
            "assertion": f"expect.{method.group(1)}",
            "path": _path(path),
            "evidence_id": _text(evidence_id, 160),
            "source_hash": _text(source_hash, 128),
            "line_start": _line(source, match.start()),
            "line_end": _line(source, expected_closing),
            "derivation": "DETERMINISTIC_CONSUMER_EXPECTATION_EXTRACTION",
        })
    if len(expectations) > MAX_CONSUMER_EXPECTATIONS:
        return {
            "status": UNSUPPORTED,
            "code": EXECUTION_INVARIANT_UNSUPPORTED,
            "errors": ["consumer expectation bound exceeded"],
            "expectations": expectations[:MAX_CONSUMER_EXPECTATIONS],
        }
    return {
        "status": VALID if expectations else UNSUPPORTED,
        "code": None if expectations else EXECUTION_INVARIANT_UNSUPPORTED,
        "errors": [] if expectations else ["no structurally bound consumer expectation found"],
        "expectations": expectations,
    }


def _evidence_records(value: Any) -> list[dict[str, Any]]:
    candidates: list[Any] = []
    if isinstance(value, dict):
        for key in ("repository_evidence", "evidence", "current_repository_evidence"):
            if isinstance(value.get(key), list):
                candidates.extend(value[key])
        registry = value.get("registry")
        if isinstance(registry, dict) and isinstance(registry.get("surfaces"), list):
            candidates.extend(registry["surfaces"])
        if not candidates and isinstance(value.get("selected"), list):
            candidates.extend(value["selected"])
    elif isinstance(value, (list, tuple)):
        candidates.extend(value)
    result: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        identifiers = []
        direct_identifier = _text(item.get("evidence_id") or item.get("id"), 160)
        if direct_identifier:
            identifiers.append(direct_identifier)
        elif isinstance(item.get("evidence_ids"), list):
            identifiers.extend(_text(identifier, 160) for identifier in item.get("evidence_ids", []))
        for identifier in _unique(identifiers):
            normalized = _copy(item)
            normalized["evidence_id"] = identifier
            normalized["path"] = _path(normalized.get("path") or normalized.get("verified_path"))
            normalized["symbol"] = _symbol(normalized.get("symbol") or normalized.get("verified_symbol"))
            previous = result.get(identifier)
            if previous is None or len(json.dumps(normalized, default=str)) > len(json.dumps(previous, default=str)):
                result[identifier] = normalized
    return list(result.values())


def _contract_and_plan_records(contract: Any, plan: Any) -> list[dict[str, Any]]:
    result = []
    for value in (contract, plan):
        if not isinstance(value, dict):
            continue
        for key in ("relevant_repository_facts", "repository_evidence"):
            if isinstance(value.get(key), list):
                result.extend(item for item in value[key] if isinstance(item, dict))
        for node in value.get("approved_change_nodes", []) or []:
            if isinstance(node, dict):
                result.append(node)
    return result


def _mutation_paths(contract: Any, plan: Any) -> list[str]:
    values = []
    if isinstance(contract, dict):
        values.extend(contract.get("allowed_mutation_paths", []) or [])
    if isinstance(plan, dict):
        values.extend(plan.get("mutation_scope", {}).get("paths", []) if isinstance(plan.get("mutation_scope"), dict) else [])
        for node in plan.get("approved_change_nodes", []) or []:
            if isinstance(node, dict) and bool(node.get("mutation_required")) and not bool(node.get("verification_only")):
                values.extend(node.get("candidate_targets", []) or [])
    return _unique(_path(value) for value in values)


def _inspection_paths(contract: Any, plan: Any) -> list[str]:
    values = []
    if isinstance(contract, dict):
        values.extend(contract.get("allowed_inspection_paths", []) or [])
    if isinstance(plan, dict):
        for node in plan.get("approved_change_nodes", []) or []:
            if isinstance(node, dict):
                values.extend(node.get("inspect_targets", []) or [])
    return _unique(_path(value) for value in values)


def _allowed_interface_change(value: Any, symbol: str, path: str) -> bool:
    """Read only explicit structured interface-change authority."""
    if not isinstance(value, dict):
        return False
    structured_keys = (
        "authorized_interface_changes", "interface_change_authority",
        "authorized_return_shape_changes", "return_shape_change_authority",
        "interface_changes", "change_authorizations",
    )
    for key in structured_keys:
        entries = value.get(key)
        if isinstance(entries, bool):
            if entries:
                return True
            continue
        if isinstance(entries, dict):
            entries = [entries]
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, str):
                if entry.casefold() in {"authorized", "change_authorized", "allow", "true"}:
                    return True
                continue
            if not isinstance(entry, dict):
                continue
            entry_symbol = _symbol(entry.get("symbol") or entry.get("function") or entry.get("interface"))
            entry_path = _path(entry.get("path") or entry.get("source_path"))
            applies = (not entry_symbol or entry_symbol == symbol or symbol in entry_symbol)
            applies = applies and (not entry_path or entry_path == path)
            decision = entry.get("authorized")
            if decision is None:
                decision = entry.get("allow")
            if decision is None:
                decision = entry.get("status") or entry.get("classification")
            if applies and (decision is True or _text(decision).casefold() in {"authorized", "change_authorized", "allow", "true"}):
                return True
    for node in value.get("approved_change_nodes", []) or []:
        if isinstance(node, dict) and _allowed_interface_change(node, symbol, path):
            return True
    return False


def _approved_texts(plan: Any, contract: Any) -> list[str]:
    values: list[Any] = []
    for value in (plan, contract):
        if not isinstance(value, dict):
            continue
        for key in ("goal", "task_goal", "integration_verification", "requirements", "done_when", "test_contract"):
            candidate = value.get(key)
            if isinstance(candidate, list):
                values.extend(candidate)
            elif candidate not in (None, ""):
                values.append(candidate)
        for node in value.get("approved_change_nodes", []) or []:
            if isinstance(node, dict):
                values.extend(node.get("goal", "") for _ in [0])
                values.extend(node.get("done_when", []) or [])
        ledger = value.get("requirement_obligation_ledger")
        if isinstance(ledger, dict):
            values.extend(
                obligation.get("text") or obligation.get("meaning")
                for requirement in ledger.get("requirements", []) or []
                if isinstance(requirement, dict)
                for obligation in requirement.get("obligations", []) or []
                if isinstance(obligation, dict)
            )
    return [_text(item).casefold() for item in values if _text(item)]


def _is_additive_change(plan: Any, contract: Any) -> bool:
    texts = _approved_texts(plan, contract)
    return any(
        "additive" in item
        or ("additional" in item and ("indicator" in item or "output" in item or "behavior" in item))
        or "without breaking" in item
        or "preserv" in item and ("existing" in item or "current" in item)
        for item in texts
    )


def _record_matches_path(record: dict[str, Any], paths: set[str]) -> bool:
    return _path(record.get("path") or record.get("verified_path")) in paths


def _record_is_source(record: dict[str, Any]) -> bool:
    kind = _text(record.get("source_kind") or record.get("kind") or record.get("category")).casefold()
    return kind in {"source", "owner", "current_owner", "current_interface", "interface"} or bool(record.get("file_sha256")) and not kind == "test"


def _record_is_test(record: dict[str, Any]) -> bool:
    kind = _text(record.get("source_kind") or record.get("kind") or record.get("category")).casefold()
    path = _path(record.get("path") or record.get("verified_path"))
    return kind in {"test", "current_test"} or "/test" in path or path.startswith("test")


def _read_subject_file(root: Any, path: str, source_files: dict[str, Any] | None = None) -> tuple[str | None, bytes | None, str | None]:
    normalized = _path(path)
    if isinstance(source_files, dict):
        for key, value in source_files.items():
            if _path(key) != normalized:
                continue
            if isinstance(value, bytes):
                return value.decode("utf-8"), value, None
            return str(value), str(value).encode("utf-8"), None
    if root is None:
        return None, None, "subject root is required"
    try:
        base = Path(root).expanduser().resolve()
        candidate = (base / normalized).resolve()
        if not candidate.is_relative_to(base):
            return None, None, "subject path escapes the approved root"
        raw = candidate.read_bytes()
        return raw.decode("utf-8"), raw, None
    except (OSError, UnicodeError, RuntimeError, ValueError) as exc:
        return None, None, str(exc)


def _source_hash(record: dict[str, Any], raw: bytes) -> str:
    observed = hashlib.sha256(raw).hexdigest()
    declared = _text(record.get("file_sha256"), 128)
    return observed if not declared else declared


def _evidence_binding(record: dict[str, Any], *, role: str, source_hash: str, location: dict[str, Any] | None = None, derivation: str = "") -> dict[str, Any]:
    path = _path(record.get("path") or record.get("verified_path"))
    symbol = _symbol(record.get("symbol") or record.get("verified_symbol"))
    binding = {
        "evidence_id": _text(record.get("evidence_id") or record.get("id"), 160),
        "role": _text(role, 80),
        "path": path,
        "symbol": symbol,
        "file_sha256": _text(source_hash or record.get("file_sha256"), 128),
        "derivation": _text(derivation or "DETERMINISTIC_REPOSITORY_EVIDENCE", 160),
    }
    if isinstance(location, dict):
        binding["location"] = {
            key: int(location[key]) for key in ("line_start", "line_end")
            if isinstance(location.get(key), int)
        }
    elif isinstance(record.get("line_start"), int) or isinstance(record.get("line_end"), int):
        binding["location"] = {
            key: int(record[key]) for key in ("line_start", "line_end")
            if isinstance(record.get(key), int)
        }
    return binding


def _invariant_id(kind: str, symbol: str, path: str) -> str:
    return "INV-" + canonical_hash({"type": kind, "symbol": symbol, "path": path})[:16].upper()


def _compact_invariant(item: dict[str, Any]) -> dict[str, Any]:
    value = item if isinstance(item, dict) else {}
    result = {
        "invariant_id": _text(value.get("invariant_id"), 160),
        "type": _text(value.get("type"), 80),
        "symbol": _symbol(value.get("symbol") or (value.get("subject") or {}).get("symbol")),
        "path": _path(value.get("path") or (value.get("subject") or {}).get("path")),
        "statement": _text(value.get("statement"), MAX_TEXT),
        "classification": _text(value.get("classification"), 80),
        "change_authorization": _text(value.get("change_authorization"), 80),
    }
    subject = value.get("subject") if isinstance(value.get("subject"), dict) else {}
    for key in ("signature", "return_shape", "owner", "interface"):
        if value.get(key) not in (None, ""):
            result[key] = _text(value.get(key), MAX_TEXT)
        elif subject.get(key) not in (None, ""):
            result[key] = _text(subject.get(key), MAX_TEXT)
    outputs = value.get("existing_outputs") or value.get("output_literals")
    if outputs:
        result["existing_outputs"] = _norm_values(outputs)
    consumers = value.get("consumers")
    if isinstance(consumers, list):
        grouped: dict[str, list[str]] = {}
        for item in consumers[:MAX_CONSUMER_EXPECTATIONS]:
            if not isinstance(item, dict):
                continue
            consumer_path = _path(item.get("path"))
            expected = _text(item.get("expected"), MAX_TEXT)
            if consumer_path and expected and expected not in grouped.setdefault(consumer_path, []):
                grouped[consumer_path].append(expected)
        result["consumers"] = [
            {
                "path": consumer_path,
                "expected": values[0] if len(values) == 1 else values,
            }
            for consumer_path, values in grouped.items()
        ]
    if value.get("additive") is True:
        result["additive"] = True
    return result


def _make_invariant(kind: str, *, symbol: str = "", path: str = "", statement: str = "", value: Any = None,
                    evidence_refs: list[dict[str, Any]] | None = None, classification: str = PRESERVE,
                    change_authorization: str = CHANGE_NOT_AUTHORIZED, **extra: Any) -> dict[str, Any]:
    record = {
        "invariant_id": _invariant_id(kind, symbol, path),
        "type": kind,
        "symbol": _symbol(symbol),
        "path": _path(path),
        "statement": _text(statement),
        "value": _copy(value),
        "classification": classification,
        "change_authorization": change_authorization,
        "confidence": "HIGH",
        "evidence_refs": _copy(evidence_refs or []),
        "derivation": "DETERMINISTIC_EXECUTION_INVARIANT_DERIVATION",
    }
    refs = record["evidence_refs"]
    record["source_evidence_ids"] = [
        ref.get("evidence_id") for ref in refs
        if isinstance(ref, dict) and ref.get("role") in {"SOURCE", "STATE_OWNER", "REQUIRED_INTERFACE", "DNT"}
    ]
    record["consumer_evidence_ids"] = [
        ref.get("evidence_id") for ref in refs
        if isinstance(ref, dict) and ref.get("role") == "CONSUMER"
    ]
    source_hashes = [
        ref.get("file_sha256") for ref in refs
        if isinstance(ref, dict) and ref.get("file_sha256")
    ]
    if source_hashes:
        record["source_hash"] = source_hashes[0]
    record.update(_copy(extra))
    return record


def _set_hash_payload(value: Any) -> dict[str, Any]:
    return _without(value, "invariant_set_hash")


def canonical_invariant_set_hash(value: Any) -> str:
    return canonical_hash(_set_hash_payload(value))


def _error_set(status: str, code: str, errors: list[str], *, authority: dict[str, Any] | None = None) -> ExecutionInvariantSet:
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "code": code,
        "errors": list(errors[:20]),
        "invariants": [],
        "invariant_ids": [],
        "evidence_bindings": [],
        "authority": _copy(authority or {}),
        "model_calls": 0,
        "worker_calls": 0,
        "invariant_set_hash": "",
    }
    result["invariant_set_hash"] = canonical_invariant_set_hash(result)
    return _freeze_record(ExecutionInvariantSet, result)


def build_execution_invariant_set(execution_contract: dict[str, Any] | None = None,
                                  contract: dict[str, Any] | None = None,
                                  approved_plan: dict[str, Any] | None = None,
                                  plan: dict[str, Any] | None = None,
                                  source_root: str | Path | None = None,
                                  workspace: str | Path | None = None,
                                  repository_evidence: Any = None,
                                  source_files: dict[str, Any] | None = None) -> ExecutionInvariantSet:
    """Build a bounded invariant set from approved authority and live subject.

    ``execution_contract``/``approved_plan`` identify the target and scope;
    evidence records identify the files and symbols.  Literal output facts
    are accepted only when the deterministic source parser and a structurally
    bound consumer assertion both support them.
    """
    authority_contract = execution_contract if isinstance(execution_contract, dict) else contract if isinstance(contract, dict) else {}
    authority_plan = approved_plan if isinstance(approved_plan, dict) else plan if isinstance(plan, dict) else {}
    root = source_root if source_root is not None else workspace
    evidence = _evidence_records(repository_evidence)
    if not evidence:
        evidence = _evidence_records(authority_contract)
    if not evidence:
        evidence = _evidence_records(authority_plan)
    mutation_paths = set(_mutation_paths(authority_contract, authority_plan))
    inspection_paths = set(_inspection_paths(authority_contract, authority_plan))
    if not mutation_paths:
        return _error_set(UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED, ["approved mutation target is missing"])

    allowed_evidence_ids = {
        _text(item)
        for value in (authority_contract, authority_plan)
        for item in (value.get("repository_evidence_ids", []) if isinstance(value, dict) else []) or []
        if _text(item)
    }
    candidates = [
        item for item in evidence
        if _record_is_source(item)
        and _record_matches_path(item, mutation_paths)
        and (not allowed_evidence_ids or _text(item.get("evidence_id")) in allowed_evidence_ids)
    ]
    # A structured plan node can supply the symbol, but it cannot supply the
    # source return fact.  It is used only to narrow an already approved path.
    target_symbols = {
        _symbol(item.get("current_owner") or item.get("symbol"))
        for item in _contract_and_plan_records(authority_contract, authority_plan)
        if isinstance(item, dict)
        and _path(item.get("path") or (item.get("candidate_targets") or [""])[0]) in mutation_paths
        and _symbol(item.get("current_owner") or item.get("symbol"))
    }
    if target_symbols:
        candidates = [item for item in candidates if not _symbol(item.get("symbol")) or _symbol(item.get("symbol")) in target_symbols]
    pairs = {
        (_path(item.get("path")), _symbol(item.get("symbol")))
        for item in candidates
        if _path(item.get("path")) and _symbol(item.get("symbol"))
    }
    if len(pairs) != 1:
        return _error_set(UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED, ["approved target source is absent or ambiguous"])
    target_path, target_symbol = next(iter(pairs))
    source_records = [
        item for item in candidates
        if (_path(item.get("path")), _symbol(item.get("symbol"))) == (target_path, target_symbol)
    ]
    source_record = source_records[0]
    source_text, source_raw, source_error = _read_subject_file(root, target_path, source_files)
    if source_error or source_text is None or source_raw is None:
        return _error_set(UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED, [f"cannot read approved source: {source_error or 'missing source'}"])
    observed_source_hash = hashlib.sha256(source_raw).hexdigest()
    for source_evidence in source_records:
        declared_source_hash = _text(source_evidence.get("file_sha256"), 128)
        if declared_source_hash and declared_source_hash != observed_source_hash:
            return _error_set(STALE, REAPPROVAL_REQUIRED, [f"source evidence hash is stale for {target_path}"], authority={"stale_paths": [target_path]})
    source_hash = observed_source_hash
    source_contract = extract_source_contract(
        source_text, target_symbol, path=target_path, source_hash=source_hash,
    )
    if source_contract.get("status") != VALID:
        return _error_set(UNSUPPORTED, source_contract.get("code") or EXECUTION_INVARIANT_UNSUPPORTED, source_contract.get("errors", []))

    consumer_records = [
        item for item in evidence
        if _record_is_test(item)
        and _path(item.get("path")) in inspection_paths
        and (not allowed_evidence_ids or _text(item.get("evidence_id")) in allowed_evidence_ids)
    ]
    # Direct source links are a legitimate bounded way to find consumers even
    # when a plan's inspection path list is compact.
    linked_paths = {
        _path(link.get("from"))
        for link in source_record.get("source_links", []) or []
        if isinstance(link, dict) and _path(link.get("from"))
    }
    if linked_paths:
        consumer_records.extend(
            item for item in evidence
            if _record_is_test(item) and _path(item.get("path")) in linked_paths
            and item not in consumer_records
        )
    consumer_records = list({
        _text(item.get("evidence_id")): item for item in consumer_records if _text(item.get("evidence_id"))
    }.values())
    if len(consumer_records) > MAX_CONSUMER_EXPECTATIONS:
        return _error_set(
            UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
            ["consumer evidence bound exceeded"],
        )
    all_expectations: list[dict[str, Any]] = []
    consumer_bindings: list[dict[str, Any]] = []
    stale_paths: list[str] = []
    for record in consumer_records:
        consumer_path = _path(record.get("path"))
        text, raw, error = _read_subject_file(root, consumer_path, source_files)
        if error or text is None or raw is None:
            continue
        observed_hash = hashlib.sha256(raw).hexdigest()
        declared_hash = _text(record.get("file_sha256"), 128)
        if declared_hash and declared_hash != observed_hash:
            stale_paths.append(consumer_path)
            continue
        extracted = extract_consumer_expectations(
            text, target_symbol, path=consumer_path,
            evidence_id=_text(record.get("evidence_id"), 160), source_hash=observed_hash,
        )
        if extracted.get("status") == VALID:
            all_expectations.extend(extracted.get("expectations", []))
            consumer_bindings.append(_evidence_binding(
                record, role="CONSUMER", source_hash=observed_hash,
                derivation="DETERMINISTIC_CONSUMER_EXPECTATION_EXTRACTION",
            ))
    if stale_paths:
        return _error_set(STALE, REAPPROVAL_REQUIRED, ["consumer evidence hashes are stale"], authority={"stale_paths": sorted(set(stale_paths))})
    if not all_expectations:
        return _error_set(UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED, ["approved consumers do not expose a supported assertion bound to the target symbol"])
    expected_values = _norm_values(item.get("expected") for item in all_expectations)
    source_values = _norm_values(source_contract.get("output_literals", []))
    if not set(expected_values).issubset(set(source_values)):
        return _error_set(CONFLICT, EXECUTION_INVARIANT_EVIDENCE_CONFLICT, ["source outputs and consumer expectations disagree"])
    interface_change_authorized = _allowed_interface_change(authority_plan, target_symbol, target_path) or _allowed_interface_change(authority_contract, target_symbol, target_path)
    classification = CHANGE_AUTHORIZED if interface_change_authorized else PRESERVE
    change_authorization = CHANGE_AUTHORITY_GRANTED if interface_change_authorized else CHANGE_NOT_AUTHORIZED
    source_refs = [
        _evidence_binding(
            source_evidence, role="SOURCE", source_hash=source_hash,
            location={"line_start": source_contract.get("line_start"), "line_end": source_contract.get("line_end")},
            derivation="DETERMINISTIC_SOURCE_CONTRACT_EXTRACTION",
        )
        for source_evidence in source_records
    ]
    invariants: list[dict[str, Any]] = []
    invariants.append(_make_invariant(
        FUNCTION_SIGNATURE, symbol=target_symbol, path=target_path,
        statement=f"{source_contract['signature']} is the current function signature.",
        value={"signature": source_contract["signature"], "parameters": source_contract["parameters"]},
        evidence_refs=source_refs, classification=classification,
        change_authorization=change_authorization, signature=source_contract["signature"],
        subject={"symbol": target_symbol, "path": target_path, "signature": source_contract["signature"]},
    ))
    invariants.append(_make_invariant(
        RETURN_SHAPE, symbol=target_symbol, path=target_path,
        statement=f"{target_symbol} currently returns a {source_contract['return_shape']}.",
        value={"return_shape": source_contract["return_shape"]},
        evidence_refs=source_refs, classification=classification,
        change_authorization=change_authorization, return_shape=source_contract["return_shape"],
        subject={"symbol": target_symbol, "path": target_path, "return_shape": source_contract["return_shape"]},
    ))
    invariants.append(_make_invariant(
        EXACT_EXISTING_OUTPUT, symbol=target_symbol, path=target_path,
        statement=f"Existing compatible outputs of {target_symbol} are the observed source literals.",
        value={"outputs": source_values}, output_literals=source_values,
        existing_outputs=source_values, evidence_refs=source_refs,
        classification=classification, change_authorization=change_authorization,
        subject={"symbol": target_symbol, "path": target_path},
    ))
    consumer_value = [
        {"path": item.get("path"), "expected": item.get("expected"), "line_start": item.get("line_start"), "line_end": item.get("line_end")}
        for item in all_expectations
    ]
    invariants.append(_make_invariant(
        CONSUMER_EXPECTATION, symbol=target_symbol, path=target_path,
        statement=f"Existing consumers depend on the current {source_contract['return_shape']} contract of {target_symbol}.",
        value={"expectations": consumer_value}, consumers=consumer_value,
        evidence_refs=consumer_bindings, classification=classification,
        change_authorization=change_authorization,
        return_shape=source_contract["return_shape"],
        subject={"symbol": target_symbol, "path": target_path},
    ))
    additive = _is_additive_change(authority_plan, authority_contract)
    compatibility_statement = (
        f"Preserve the existing {source_contract['return_shape']} contract of {target_symbol}; "
        "the approved plan does not authorize replacing its return shape."
        if not interface_change_authorized else
        f"The approved plan explicitly authorizes changing the current interface contract of {target_symbol}."
    )
    invariants.append(_make_invariant(
        INTERFACE_COMPATIBILITY, symbol=target_symbol, path=target_path,
        statement=compatibility_statement,
        value={"return_shape": source_contract["return_shape"], "outputs": source_values, "additive": additive},
        existing_outputs=source_values, evidence_refs=source_refs + consumer_bindings,
        classification=classification, change_authorization=change_authorization,
        additive=bool(additive and not interface_change_authorized),
        subject={"symbol": target_symbol, "path": target_path, "return_shape": source_contract["return_shape"]},
    ))

    state_owner_records = [
        item for item in evidence
        if _text(item.get("role") or item.get("task_relevance_role") or item.get("category")).casefold() in {"state_owner", "owner"}
        and "state_owner" in " ".join(str(x).casefold() for x in item.get("structured_relations", []) or [])
    ]
    if not state_owner_records:
        state_owner_records = [
            item for item in evidence
            if "preserve_ownership" in " ".join(str(x).casefold() for x in item.get("structured_relations", []) or [])
        ]
    if state_owner_records:
        owner = state_owner_records[0]
        owner_name = _symbol(owner.get("symbol") or owner.get("verified_symbol"))
        owner_path = _path(owner.get("path") or owner.get("verified_path"))
        owner_text, owner_raw, owner_error = _read_subject_file(root, owner_path, source_files)
        owner_hash = hashlib.sha256(owner_raw).hexdigest() if owner_raw is not None else _text(owner.get("file_sha256"), 128)
        if owner_error is None and owner_raw is not None and owner.get("file_sha256") and owner.get("file_sha256") != owner_hash:
            return _error_set(STALE, REAPPROVAL_REQUIRED, [f"state-owner evidence hash is stale for {owner_path}"])
        invariants.append(_make_invariant(
            STATE_OWNER, symbol=owner_name, path=owner_path,
            statement=f"{owner_name} remains the current state owner.",
            value={"owner": owner_name}, owner=owner_name,
            evidence_refs=[_evidence_binding(owner, role="STATE_OWNER", source_hash=owner_hash)],
        ))

    interface_records = [
        item for item in evidence
        if _text(item.get("symbol") or item.get("verified_symbol"))
        and _text(item.get("symbol") or item.get("verified_symbol")) in {
            _text(interface) for interface in (authority_contract.get("interfaces_to_reuse", []) if isinstance(authority_contract, dict) else []) or []
        }
    ]
    if isinstance(authority_contract, dict):
        for interface in _unique(authority_contract.get("interfaces_to_reuse", [])):
            interface_record = next((item for item in interface_records if _text(item.get("symbol")) == interface), None)
            if interface_record is None:
                return _error_set(
                    UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
                    [f"required interface evidence is absent: {interface}"],
                )
            interface_path = _path(interface_record.get("path"))
            interface_text, interface_raw, interface_error = _read_subject_file(
                root, interface_path, source_files,
            )
            if interface_error or interface_raw is None:
                return _error_set(
                    UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
                    [f"required interface cannot be read: {interface}"],
                )
            interface_hash = hashlib.sha256(interface_raw).hexdigest()
            if interface_record.get("file_sha256") and interface_record.get("file_sha256") != interface_hash:
                return _error_set(
                    STALE, REAPPROVAL_REQUIRED,
                    [f"required interface evidence hash is stale: {interface}"],
                )
            refs = [_evidence_binding(
                interface_record, role="REQUIRED_INTERFACE", source_hash=interface_hash,
            )]
            invariants.append(_make_invariant(
                REQUIRED_INTERFACE_REUSE, symbol=interface,
                path=_path(interface_record.get("path")) if interface_record else "",
                statement=f"Reuse the approved existing interface {interface}.",
                value={"interface": interface}, interface=interface,
                evidence_refs=refs,
            ))

    dnt_paths = []
    dnt_surfaces = []
    if isinstance(authority_contract, dict):
        dnt_paths.extend(_path(item) for item in authority_contract.get("global_do_not_touch", []) or [])
        dnt_surfaces.extend(_text(item, 160) for item in authority_contract.get("global_do_not_touch_surface_ids", []) or [])
    if isinstance(authority_plan, dict):
        dnt_paths.extend(_path(item) for item in authority_plan.get("do_not_touch", []) or [])
    dnt_paths = _unique(dnt_paths)
    for dnt_path in dnt_paths:
        dnt_record = next((item for item in evidence if _path(item.get("path")) == dnt_path), None)
        if dnt_record is None:
            return _error_set(
                UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
                [f"DNT evidence is absent: {dnt_path}"],
            )
        refs = []
        if dnt_record:
            text, raw, error = _read_subject_file(root, dnt_path, source_files)
            if raw is not None:
                observed = hashlib.sha256(raw).hexdigest()
                if dnt_record.get("file_sha256") and dnt_record.get("file_sha256") != observed:
                    return _error_set(STALE, REAPPROVAL_REQUIRED, [f"DNT evidence hash is stale for {dnt_path}"])
                refs = [_evidence_binding(dnt_record, role="DNT", source_hash=observed)]
            else:
                refs = [_evidence_binding(dnt_record, role="DNT", source_hash=_text(dnt_record.get("file_sha256"), 128))]
        if not refs:
            return _error_set(
                UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
                [f"DNT evidence cannot be read: {dnt_path}"],
            )
        invariants.append(_make_invariant(
            DNT_PRESERVATION, path=dnt_path,
            statement=f"Do not modify {dnt_path}.",
            value={"path": dnt_path, "surface_ids": dnt_surfaces},
            evidence_refs=refs,
        ))

    # The taxonomy is intentionally fixed and the set is bounded before it is
    # frozen.  Duplicate evidence records are fanned into one invariant.
    deduped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in invariants:
        key = (item.get("type", ""), item.get("symbol", ""), item.get("path", ""))
        existing = deduped.get(key)
        if existing is None:
            deduped[key] = item
        else:
            refs = existing.setdefault("evidence_refs", [])
            for ref in item.get("evidence_refs", []) or []:
                if ref not in refs and len(refs) < MAX_EVIDENCE_BINDINGS:
                    refs.append(ref)
    invariants = list(deduped.values())
    if len(invariants) > MAX_INVARIANTS:
        return _error_set(
            UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
            ["execution invariant bounds exceeded"], authority=authority,
        )
    evidence_bindings: list[dict[str, Any]] = []
    for item in invariants:
        for ref in item.get("evidence_refs", []) or []:
            if ref not in evidence_bindings:
                evidence_bindings.append(_copy(ref))
    if len(evidence_bindings) > MAX_EVIDENCE_BINDINGS:
        return _error_set(
            UNSUPPORTED, EXECUTION_INVARIANT_UNSUPPORTED,
            ["execution evidence bounds exceeded"], authority=authority,
        )
    authority = {
        "mutation_paths": sorted(mutation_paths),
        "inspection_paths": sorted(inspection_paths),
        "dnt_paths": dnt_paths,
        "dnt_surface_ids": dnt_surfaces,
        "new_owner_symbols": [],
        "required_interfaces": _unique(authority_contract.get("interfaces_to_reuse", []) if isinstance(authority_contract, dict) else []),
    }
    result = {
        "schema_version": SCHEMA_VERSION,
        "status": VALID,
        "code": None,
        "errors": [],
        "invariants": invariants,
        "invariant_ids": [item.get("invariant_id") for item in invariants],
        "evidence_bindings": evidence_bindings,
        "authority": authority,
        "source_subject": {
            "paths": sorted({ref.get("path") for ref in evidence_bindings if ref.get("path")}),
            "hashes": sorted({ref.get("file_sha256") for ref in evidence_bindings if ref.get("file_sha256")}),
        },
        "model_calls": 0,
        "worker_calls": 0,
        "derivation": "DETERMINISTIC_VERIFIED_REPOSITORY_EVIDENCE",
        "invariant_set_hash": "",
    }
    result["invariant_set_hash"] = canonical_invariant_set_hash(result)
    return _freeze_record(ExecutionInvariantSet, result)


extract_execution_invariant_set = build_execution_invariant_set
construct_execution_invariant_set = build_execution_invariant_set
build_invariant_set = build_execution_invariant_set
create_execution_invariant_set = build_execution_invariant_set


def validate_execution_invariant_set(invariant_set: Any, *, execution_contract: dict[str, Any] | None = None,
                                     contract: dict[str, Any] | None = None,
                                     source_root: str | Path | None = None,
                                     workspace: str | Path | None = None,
                                     source_files: dict[str, Any] | None = None,
                                     require_current_subject: bool = False) -> dict[str, Any]:
    value = invariant_set if isinstance(invariant_set, dict) else {}
    authority_contract = execution_contract if isinstance(execution_contract, dict) else contract if isinstance(contract, dict) else {}
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("invariant set schema version is invalid")
    if value.get("status") != VALID:
        errors.append(str(value.get("code") or EXECUTION_INVARIANT_INVALID))
    if value.get("invariant_set_hash") != canonical_invariant_set_hash(value):
        errors.append("invariant set hash does not match content")
    if not _metric_is_zero(value.get("model_calls", 0)):
        errors.append("invariant construction contains model calls")
    if not _metric_is_zero(value.get("worker_calls", 0)):
        errors.append("invariant construction contains Worker calls")
    invariants = value.get("invariants") if isinstance(value.get("invariants"), list) else []
    if len(invariants) > MAX_INVARIANTS:
        errors.append("invariant count bound exceeded")
    evidence_catalog = value.get("evidence_bindings") if isinstance(value.get("evidence_bindings"), list) else []
    if len(evidence_catalog) > MAX_EVIDENCE_BINDINGS:
        errors.append("evidence binding count bound exceeded")
    ids = [str(item.get("invariant_id")) for item in invariants if isinstance(item, dict)]
    if len(ids) != len(set(ids)):
        errors.append("duplicate invariant id")
    if value.get("invariant_ids") != ids:
        errors.append("invariant_ids do not match invariants")
    by_semantic_key: dict[tuple[str, str, str], str] = {}
    for item in invariants:
        if not isinstance(item, dict):
            errors.append("invariant must be an object")
            continue
        if item.get("type") not in INVARIANT_TYPES:
            errors.append(f"unsupported invariant type: {item.get('type')}")
        if item.get("classification") not in {PRESERVE, CHANGE_AUTHORIZED, NOT_APPLICABLE}:
            errors.append(f"invalid invariant classification: {item.get('invariant_id')}")
        refs = item.get("evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(f"invariant lacks evidence refs: {item.get('invariant_id')}")
        elif len(refs) > MAX_EVIDENCE_BINDINGS:
            errors.append(f"invariant evidence ref bound exceeded: {item.get('invariant_id')}")
        for ref in refs or []:
            if not isinstance(ref, dict) or not _text(ref.get("evidence_id")) or not _text(ref.get("file_sha256")):
                errors.append(f"invariant evidence binding is incomplete: {item.get('invariant_id')}")
        if isinstance(item.get("consumers"), list) and len(item.get("consumers")) > MAX_CONSUMER_EXPECTATIONS:
            errors.append(f"consumer expectation bound exceeded: {item.get('invariant_id')}")
        if item.get("type") == EXACT_EXISTING_OUTPUT and not item.get("output_literals"):
            errors.append(f"output invariant has no deterministically derived values: {item.get('invariant_id')}")
        semantic_key = (
            _text(item.get("type")), _symbol(item.get("symbol")), _path(item.get("path")),
        )
        semantic_value = canonical_hash({
            key: item.get(key) for key in (
                "signature", "return_shape", "output_literals", "existing_outputs",
                "consumers", "owner", "interface", "classification",
                "change_authorization", "additive",
            ) if key in item
        })
        previous_value = by_semantic_key.get(semantic_key)
        if previous_value is not None and previous_value != semantic_value:
            errors.append(f"conflicting invariant semantics: {item.get('invariant_id')}")
        else:
            by_semantic_key[semantic_key] = semantic_value
    binding_ids = {
        _text(item.get("evidence_id")) for item in value.get("evidence_bindings", []) or []
        if isinstance(item, dict) and _text(item.get("evidence_id"))
    }
    for item in invariants:
        for ref in item.get("evidence_refs", []) or []:
            if isinstance(ref, dict) and _text(ref.get("evidence_id")) not in binding_ids:
                errors.append(f"invariant evidence ref is missing from binding catalog: {item.get('invariant_id')}")
    observed_contract_paths = set(_mutation_paths(authority_contract, {}))
    set_paths = set((value.get("authority") or {}).get("mutation_paths", []) or [])
    if observed_contract_paths and set_paths != observed_contract_paths:
        errors.append("invariant set changes mutation scope")
    contract_dnt = set(_path(item) for item in authority_contract.get("global_do_not_touch", []) or []) if isinstance(authority_contract, dict) else set()
    set_dnt = set(_path(item) for item in (value.get("authority") or {}).get("dnt_paths", []) or [])
    if contract_dnt and set_dnt != contract_dnt:
        errors.append("invariant set weakens or changes DNT")
    if (value.get("authority") or {}).get("new_owner_symbols"):
        errors.append("invariant set introduces a new owner")
    root = source_root if source_root is not None else workspace
    if require_current_subject or root is not None or source_files is not None:
        source_contract_cache: dict[tuple[str, str], dict[str, Any]] = {}
        consumer_expectation_cache: dict[tuple[str, str], dict[str, Any]] = {}
        for ref in value.get("evidence_bindings", []) or []:
            if not isinstance(ref, dict) or not ref.get("path"):
                continue
            text, raw, error = _read_subject_file(root, ref.get("path"), source_files)
            if error or raw is None:
                errors.append(f"current evidence cannot be read: {ref.get('path')}")
                continue
            if hashlib.sha256(raw).hexdigest() != ref.get("file_sha256"):
                errors.append(f"current evidence is stale: {ref.get('path')}")
        for item in invariants:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            item_symbol = _symbol(item.get("symbol"))
            item_path = _path(item.get("path"))
            if item_type in {
                FUNCTION_SIGNATURE, RETURN_SHAPE, EXACT_EXISTING_OUTPUT,
                INTERFACE_COMPATIBILITY,
            } and item_symbol and item_path:
                cache_key = (item_path, item_symbol)
                parsed = source_contract_cache.get(cache_key)
                if parsed is None:
                    text, raw, error = _read_subject_file(root, item_path, source_files)
                    if error or text is None:
                        errors.append(f"invariant source cannot be read: {item_path}")
                        continue
                    parsed = extract_source_contract(
                        text, item_symbol, path=item_path,
                        source_hash=hashlib.sha256(raw or b"").hexdigest(),
                    )
                    source_contract_cache[cache_key] = parsed
                if parsed.get("status") != VALID:
                    errors.append(f"invariant symbol does not resolve: {item_symbol}")
                    continue
                if item_type == FUNCTION_SIGNATURE and item.get("signature") != parsed.get("signature"):
                    errors.append(f"function signature evidence does not match: {item.get('invariant_id')}")
                if item_type == RETURN_SHAPE and item.get("return_shape") != parsed.get("return_shape"):
                    errors.append(f"return shape evidence does not match: {item.get('invariant_id')}")
                if item_type == EXACT_EXISTING_OUTPUT and _norm_values(item.get("output_literals", [])) != _norm_values(parsed.get("output_literals", [])):
                    errors.append(f"output evidence does not match source: {item.get('invariant_id')}")
            if item_type == CONSUMER_EXPECTATION:
                for consumer in item.get("consumers", []) or []:
                    if not isinstance(consumer, dict):
                        errors.append(f"consumer binding is malformed: {item.get('invariant_id')}")
                        continue
                    consumer_path = _path(consumer.get("path"))
                    if not consumer_path:
                        errors.append(f"consumer binding lacks path: {item.get('invariant_id')}")
                        continue
                    cache_key = (consumer_path, item_symbol)
                    parsed = consumer_expectation_cache.get(cache_key)
                    if parsed is None:
                        text, raw, error = _read_subject_file(root, consumer_path, source_files)
                        if error or text is None:
                            errors.append(f"consumer source cannot be read: {consumer_path}")
                            continue
                        parsed = extract_consumer_expectations(text, item_symbol, path=consumer_path)
                        consumer_expectation_cache[cache_key] = parsed
                    actual_values = {
                        str(expectation.get("expected"))
                        for expectation in parsed.get("expectations", []) or []
                        if isinstance(expectation, dict)
                    }
                    expected = consumer.get("expected")
                    expected_values = set(str(item) for item in expected) if isinstance(expected, list) else {str(expected)}
                    if parsed.get("status") != VALID or not expected_values.issubset(actual_values):
                        errors.append(f"consumer binding does not resolve: {consumer_path}")
    return {
        "valid": not errors,
        "status": VALID if not errors else EXECUTION_INVARIANT_INVALID,
        "code": None if not errors else (REAPPROVAL_REQUIRED if any("stale" in item for item in errors) else EXECUTION_INVARIANT_INVALID),
        "errors": errors[:40],
        "invariant_set_hash": value.get("invariant_set_hash"),
        "model_calls": 0,
    }


validate_invariant_set = validate_execution_invariant_set


def relevant_invariants(invariant_set: Any, contract: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    value = invariant_set if isinstance(invariant_set, dict) else {}
    items = [item for item in value.get("invariants", []) or [] if isinstance(item, dict)]
    if not isinstance(contract, dict):
        return items
    paths = set(_path(item) for item in contract.get("allowed_mutation_paths", []) or [])
    inspect = set(_path(item) for item in contract.get("allowed_inspection_paths", []) or [])
    interfaces = set(_text(item) for item in contract.get("interfaces_to_reuse", []) or [])
    selected = []
    for item in items:
        item_path = _path(item.get("path"))
        item_symbol = _symbol(item.get("symbol"))
        consumers = {
            _path(consumer.get("path")) for consumer in item.get("consumers", []) or []
            if isinstance(consumer, dict)
        }
        relevant = (
            item_path in paths
            or bool(consumers.intersection(inspect))
            or item.get("type") in {STATE_OWNER, REQUIRED_INTERFACE_REUSE, DNT_PRESERVATION}
            or item_symbol in interfaces
        )
        if relevant:
            selected.append(item)
    return selected


def _precommit_path(value: Any) -> str:
    return _path(value).casefold()


def _precommit_source(value: Any) -> tuple[str | None, bytes | None, str | None]:
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8"), value, None
        except UnicodeError as exc:
            return None, None, str(exc)
    if value is None:
        return None, None, "source content is required"
    text = str(value)
    return text, text.encode("utf-8"), None


def _precommit_lookup(
    path: str,
    *,
    target_path: str,
    target_content: str,
    workspace: str | Path | None,
    source_files: dict[str, Any] | None,
) -> tuple[str | None, bytes | None, str | None]:
    normalized = _precommit_path(path)
    if normalized == _precommit_path(target_path):
        return _precommit_source(target_content)
    if isinstance(source_files, dict):
        for key, value in source_files.items():
            if _precommit_path(key) == normalized:
                return _precommit_source(value)
    return _read_subject_file(workspace, _path(path), source_files=None)


def _precommit_compact(value: Any, limit: int = 700) -> Any:
    """Keep audit observations bounded without hiding their semantic kind."""
    if isinstance(value, dict):
        return {
            str(key): _precommit_compact(item, limit=limit)
            for key, item in list(sorted(value.items(), key=lambda pair: str(pair[0])))[:16]
        }
    if isinstance(value, (list, tuple)):
        return [_precommit_compact(item, limit=limit) for item in list(value)[:16]]
    if isinstance(value, str):
        return _text(value, limit)
    return value


def _precommit_value(item: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if item.get(key) not in (None, "", []):
            return item.get(key)
    nested = item.get("value") if isinstance(item.get("value"), dict) else {}
    for key in keys:
        if nested.get(key) not in (None, "", []):
            return nested.get(key)
    subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
    for key in keys:
        if subject.get(key) not in (None, "", []):
            return subject.get(key)
    return default


def _precommit_expected_outputs(item: dict[str, Any]) -> list[str]:
    values = _precommit_value(item, "output_literals", "existing_outputs", default=None)
    if values is None:
        nested = item.get("value") if isinstance(item.get("value"), dict) else {}
        values = nested.get("outputs", [])
    if isinstance(values, (str, bytes)):
        values = [values]
    return _norm_values(values if isinstance(values, (list, tuple, set)) else [])


def _precommit_violation(
    item: dict[str, Any],
    reason: str,
    *,
    expected: Any = None,
    observed: Any = None,
) -> dict[str, Any]:
    return {
        "invariant_id": _text(item.get("invariant_id"), 160),
        "type": _text(item.get("type"), 80),
        "symbol": _symbol(item.get("symbol")),
        "path": _path(item.get("path")),
        "classification": _text(item.get("classification"), 80),
        "reason": _text(reason, 500),
        "expected": _precommit_compact(expected),
        "observed": _precommit_compact(observed),
    }


def _precommit_has_declaration(source: str, symbol: str) -> bool:
    target = _symbol(symbol)
    if not target or "." in target:
        return False
    masked = _mask_non_code(source)
    return re.search(
        rf"\b(?:class|function|const|let|var)\s+{re.escape(target)}\b", masked,
    ) is not None


def _precommit_interface_token(interface: str) -> str:
    value = _symbol(interface)
    if "." in value:
        value = value.rsplit(".", 1)[-1]
    value = re.sub(r"\(.*\)$", "", value).strip()
    return value


def _precommit_has_interface(source: str, interface: str) -> bool:
    token = _precommit_interface_token(interface)
    if not token or not re.fullmatch(r"[A-Za-z_$][\w$]*", token):
        return False
    masked = _mask_non_code(source)
    return re.search(rf"\b{re.escape(token)}\s*(?:\(|[:=])", masked) is not None


def _precommit_expected_consumer_values(item: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    for consumer in item.get("consumers", []) or []:
        if not isinstance(consumer, dict):
            continue
        expected = consumer.get("expected")
        values.extend(expected if isinstance(expected, list) else [expected])
    return _norm_values(values)


def _precommit_consumer_paths(item: dict[str, Any]) -> set[str]:
    return {
        _precommit_path(consumer.get("path"))
        for consumer in item.get("consumers", []) or []
        if isinstance(consumer, dict) and _path(consumer.get("path"))
    }


def _precommit_applicable(
    invariant_set: dict[str, Any],
    contract: dict[str, Any] | None,
    target_path: str,
) -> list[dict[str, Any]]:
    selected = relevant_invariants(invariant_set, contract if isinstance(contract, dict) else None)
    target = _precommit_path(target_path)
    result = []
    for item in selected:
        item_path = _precommit_path(item.get("path"))
        if item_path == target or target in _precommit_consumer_paths(item):
            result.append(item)
    result.sort(key=lambda item: (
        _text(item.get("invariant_id"), 160),
        _text(item.get("type"), 80),
        _path(item.get("path")),
    ))
    return result


def _precommit_authority_errors(
    invariant_set: Any,
    *,
    contract: dict[str, Any] | None,
    authorization: dict[str, Any] | None,
) -> list[str]:
    value = invariant_set if isinstance(invariant_set, dict) else {}
    errors: list[str] = []
    if not value:
        return ["execution invariant set is required"]
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("execution invariant set schema version is invalid")
    if value.get("status") != VALID:
        errors.append(str(value.get("code") or EXECUTION_INVARIANT_INVALID))
    if value.get("invariant_set_hash") != canonical_invariant_set_hash(value):
        errors.append("execution invariant set hash does not match content")
    if not _metric_is_zero(value.get("model_calls", 0)):
        errors.append("execution invariant set contains model calls")
    if not _metric_is_zero(value.get("worker_calls", 0)):
        errors.append("execution invariant set contains Worker calls")
    checked = validate_execution_invariant_set(
        value, execution_contract=contract if isinstance(contract, dict) else None,
    )
    if not checked.get("valid"):
        errors.extend(str(item) for item in checked.get("errors", [])[:20])
    if isinstance(contract, dict):
        contract_hash = _text(contract.get("execution_invariant_set_hash"), 128)
        if contract_hash and contract_hash != value.get("invariant_set_hash"):
            errors.append("execution contract is not bound to the supplied invariant set")
        contract_ids = contract.get("execution_invariant_ids")
        if contract_ids and list(contract_ids) != list(value.get("invariant_ids", []) or []):
            errors.append("execution contract invariant IDs do not match the supplied set")
    if isinstance(authorization, dict):
        auth_hash = _text(authorization.get("execution_invariant_set_hash"), 128)
        if not auth_hash:
            errors.append("current execution authorization has no invariant-set binding")
        elif auth_hash != value.get("invariant_set_hash"):
            errors.append("current execution authorization is not bound to the supplied invariant set")
        auth_ids = authorization.get("execution_invariant_ids")
        if auth_ids is not None and list(auth_ids) != list(value.get("invariant_ids", []) or []):
            errors.append("current execution authorization invariant IDs do not match the supplied set")
    return list(dict.fromkeys(errors))[:40]


def _precommit_semantic_violations(
    item: dict[str, Any],
    *,
    target_path: str,
    target_content: str,
    pre_content: str | None = None,
    workspace: str | Path | None,
    source_files: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    item_type = _text(item.get("type"), 80)
    item_path = _path(item.get("path"))
    target = _precommit_path(target_path)
    item_target = _precommit_path(item_path)
    if item_type == DNT_PRESERVATION:
        return [_precommit_violation(
            item, "candidate target is inside a do-not-touch surface",
            expected="target remains unmodified", observed=target_path,
        )]
    if item_target != target and item_type not in {CONSUMER_EXPECTATION}:
        return []

    if item_type == CONSUMER_EXPECTATION and target in _precommit_consumer_paths(item):
        consumer_source, _raw, error = _precommit_lookup(
            target_path, target_path=target_path, target_content=target_content,
            workspace=workspace, source_files=source_files,
        )
        if error or consumer_source is None:
            return [_precommit_violation(
                item, "candidate consumer semantics could not be extracted",
                expected=_precommit_expected_consumer_values(item), observed=error or "missing consumer source",
            )]
        parsed = extract_consumer_expectations(
            consumer_source, _symbol(item.get("symbol")), path=target_path,
        )
        actual = _norm_values(
            expectation.get("expected")
            for expectation in parsed.get("expectations", []) or []
            if isinstance(expectation, dict)
        )
        expected = _precommit_expected_consumer_values(item)
        if parsed.get("status") != VALID or not set(expected).issubset(set(actual)):
            return [_precommit_violation(
                item, "preserved consumer expectation is absent from the candidate",
                expected=expected, observed={"status": parsed.get("status"), "expected": actual},
            )]
        return []

    if item_type in {FUNCTION_SIGNATURE, RETURN_SHAPE, EXACT_EXISTING_OUTPUT,
                     INTERFACE_COMPATIBILITY, CONSUMER_EXPECTATION}:
        candidate_source, _raw, error = _precommit_lookup(
            item_path, target_path=target_path, target_content=target_content,
            workspace=workspace, source_files=source_files,
        )
        if error or candidate_source is None:
            return [_precommit_violation(
                item, "candidate source semantics could not be extracted",
                expected=_precommit_value(item, "signature", "return_shape", "output_literals", "existing_outputs"),
                observed=error or "missing candidate source",
            )]
        parsed = extract_source_contract(
            candidate_source, _symbol(item.get("symbol")), path=item_path,
        )
        if parsed.get("status") != VALID:
            return [_precommit_violation(
                item, "candidate source semantic extraction is unsupported",
                expected={
                    "signature": _precommit_value(item, "signature"),
                    "return_shape": _precommit_value(item, "return_shape"),
                    "outputs": _precommit_expected_outputs(item),
                },
                observed={"status": parsed.get("status"), "errors": parsed.get("errors", [])},
            )]
        violations: list[dict[str, Any]] = []
        if item_type == FUNCTION_SIGNATURE:
            expected = _precommit_value(item, "signature")
            if expected and parsed.get("signature") != expected:
                violations.append(_precommit_violation(
                    item, "preserved callable signature changed",
                    expected=expected, observed=parsed.get("signature"),
                ))
        elif item_type == RETURN_SHAPE:
            expected = _precommit_value(item, "return_shape")
            if expected and parsed.get("return_shape") != expected:
                violations.append(_precommit_violation(
                    item, "preserved return shape changed",
                    expected=expected, observed=parsed.get("return_shape"),
                ))
        elif item_type == EXACT_EXISTING_OUTPUT:
            expected = _precommit_expected_outputs(item)
            observed = _norm_values(parsed.get("output_literals", []))
            if expected != observed:
                violations.append(_precommit_violation(
                    item, "preserved exact outputs changed",
                    expected=expected, observed=observed,
                ))
        elif item_type == INTERFACE_COMPATIBILITY:
            expected_shape = _precommit_value(item, "return_shape")
            expected_outputs = _precommit_expected_outputs(item)
            observed = {
                "return_shape": parsed.get("return_shape"),
                "outputs": _norm_values(parsed.get("output_literals", [])),
            }
            if expected_shape and parsed.get("return_shape") != expected_shape:
                violations.append(_precommit_violation(
                    item, "preserved interface return shape changed",
                    expected={"return_shape": expected_shape}, observed=observed,
                ))
            if expected_outputs and observed["outputs"] != expected_outputs:
                violations.append(_precommit_violation(
                    item, "preserved interface outputs changed",
                    expected={"outputs": expected_outputs}, observed=observed,
                ))
        elif item_type == CONSUMER_EXPECTATION:
            expected = _precommit_expected_consumer_values(item)
            observed = _norm_values(parsed.get("output_literals", []))
            if not set(expected).issubset(set(observed)):
                violations.append(_precommit_violation(
                    item, "preserved consumer expectation is not produced",
                    expected=expected, observed=observed,
                ))
        return violations

    if item_type == STATE_OWNER:
        owner = _symbol(_precommit_value(item, "owner") or item.get("symbol"))
        if not _precommit_has_declaration(target_content, owner):
            violations = [_precommit_violation(
                item, "preserved state owner declaration is absent",
                expected=owner, observed="owner declaration not found",
            )]
        else:
            violations = []
        # This is intentionally limited to newly introduced class names in
        # the already-bound owner file.  It catches a second state-holder
        # declaration without attempting a new whole-repository ownership
        # analysis.
        if pre_content is not None:
            previous_classes = set(re.findall(
                r"\bclass\s+([A-Za-z_$][\w$]*)\b", _mask_non_code(pre_content),
            ))
            candidate_classes = set(re.findall(
                r"\bclass\s+([A-Za-z_$][\w$]*)\b", _mask_non_code(target_content),
            ))
            new_classes = sorted(candidate_classes - previous_classes)
            if new_classes:
                violations.append(_precommit_violation(
                    item, "candidate introduces a new class beside the preserved state owner",
                    expected=sorted(previous_classes), observed=sorted(candidate_classes),
                ))
        return violations

    if item_type == REQUIRED_INTERFACE_REUSE:
        interface = _symbol(_precommit_value(item, "interface") or item.get("symbol"))
        if not _precommit_has_interface(target_content, interface):
            return [_precommit_violation(
                item, "required existing interface is not reused",
                expected=interface, observed="required interface token not found",
            )]
        return []
    return []


def canonical_precommit_invariant_audit_hash(value: Any) -> str:
    """Return the canonical hash of a pre-commit audit without its self-hash."""
    return canonical_hash(_without(value, "canonical_hash"))


def _build_precommit_audit(
    *,
    candidate_mutation_id: str,
    path: str,
    pre_state_hash: str,
    candidate_hash: str,
    applicable: list[dict[str, Any]],
    violations: list[dict[str, Any]],
    status: str,
    authority_set_hash: str,
    authority_errors: list[str] | None = None,
) -> PreCommitInvariantAudit:
    classifications = {
        _text(item.get("invariant_id"), 160): _text(item.get("classification"), 80)
        for item in applicable
    }
    preserve_ids = sorted(
        invariant_id for invariant_id, classification in classifications.items()
        if classification == PRESERVE
    )
    authorized_ids = sorted(
        invariant_id for invariant_id, classification in classifications.items()
        if classification == CHANGE_AUTHORIZED
    )
    payload = {
        "schema_version": PRECOMMIT_SCHEMA_VERSION,
        "artifact_type": "PRECOMMIT_EXECUTION_INVARIANT_AUDIT",
        "candidate_mutation_id": _text(candidate_mutation_id, 160),
        "path": _path(path),
        "pre_state_hash": _text(pre_state_hash, 128),
        "candidate_hash": _text(candidate_hash, 128),
        "applicable_invariant_ids": [
            _text(item.get("invariant_id"), 160) for item in applicable
        ],
        "classifications": classifications,
        "preserve_invariant_ids": preserve_ids,
        "change_authorized_invariant_ids": authorized_ids,
        "violations": sorted(
            [_copy(item) for item in violations],
            key=lambda item: (
                _text(item.get("invariant_id"), 160),
                _text(item.get("type"), 80),
                _text(item.get("reason"), 500),
            ),
        ),
        "status": status,
        "allowed": status == PRECOMMIT_ALLOWED,
        "authority_set_hash": _text(authority_set_hash, 128),
        "authority_errors": list(authority_errors or [])[:20],
        "model_calls": 0,
        "worker_calls": 0,
        "canonical_hash": "",
    }
    payload["canonical_hash"] = canonical_precommit_invariant_audit_hash(payload)
    return _freeze_record(PreCommitInvariantAudit, payload)


class PreCommitExecutionInvariantGate:
    """Compare a candidate mutation with already-bound preserved semantics."""

    def __init__(self, invariant_set: Any, *, contract: dict[str, Any] | None = None,
                 authorization: dict[str, Any] | None = None,
                 workspace: str | Path | None = None,
                 source_files: dict[str, Any] | None = None):
        self.invariant_set = invariant_set
        self.contract = contract if isinstance(contract, dict) else None
        self.authorization = authorization if isinstance(authorization, dict) else None
        self.workspace = workspace
        self.source_files = source_files

    def evaluate(
        self,
        path: str,
        candidate_content: Any,
        original_content: Any = None,
        *,
        pre_state_bytes: bytes | None = None,
        mutation_id: str | None = None,
        candidate_files: dict[str, Any] | None = None,
    ) -> PreCommitInvariantAudit:
        target_path = _path(path)
        candidate_text, candidate_raw, candidate_error = _precommit_source(candidate_content)
        if candidate_text is None or candidate_raw is None:
            candidate_text = ""
            candidate_raw = b""
        pre_state_available = False
        if pre_state_bytes is not None:
            pre_raw = bytes(pre_state_bytes)
            pre_state_available = True
        else:
            _pre_text, pre_raw, _pre_error = _precommit_source(original_content)
            pre_state_available = _pre_text is not None and pre_raw is not None
            if _pre_text is None or pre_raw is None:
                _looked_up_text, looked_up_raw, _looked_up_error = _read_subject_file(
                    self.workspace, target_path, self.source_files,
                )
                if looked_up_raw is not None:
                    pre_state_available = True
                    pre_raw = looked_up_raw
        pre_raw = pre_raw or b""
        pre_hash = hashlib.sha256(pre_raw).hexdigest()
        candidate_hash = hashlib.sha256(candidate_raw).hexdigest()
        authority_errors = _precommit_authority_errors(
            self.invariant_set, contract=self.contract, authorization=self.authorization,
        )
        value = self.invariant_set if isinstance(self.invariant_set, dict) else {}
        set_hash = _text(value.get("invariant_set_hash"), 128)
        applicable = _precommit_applicable(value, self.contract, target_path) if not authority_errors else []
        merged_files: dict[str, Any] = {}
        if isinstance(self.source_files, dict):
            merged_files.update(self.source_files)
        if isinstance(candidate_files, dict):
            merged_files.update(candidate_files)
        violations: list[dict[str, Any]] = []
        if candidate_error:
            violations.append({
                "invariant_id": "PRECOMMIT-CANDIDATE",
                "type": "CANDIDATE_CONTENT",
                "symbol": "",
                "path": target_path,
                "classification": PRESERVE,
                "reason": _text(candidate_error, 500),
                "expected": "UTF-8 candidate content",
                "observed": "candidate content could not be decoded",
            })
        if not pre_state_available and any(
            _text(item.get("classification"), 80) == PRESERVE for item in applicable
        ):
            violations.append({
                "invariant_id": "PRECOMMIT-PRESTATE",
                "type": "PRE_STATE",
                "symbol": "",
                "path": target_path,
                "classification": PRESERVE,
                "reason": "pre-state content is required for semantic comparison",
                "expected": "existing target content",
                "observed": "missing pre-state content",
            })
        if authority_errors:
            violations.append({
                "invariant_id": "PRECOMMIT-AUTHORITY",
                "type": "AUTHORIZATION_BOUND_INVARIANT_SET",
                "symbol": "",
                "path": target_path,
                "classification": PRESERVE,
                "reason": "; ".join(authority_errors),
                "expected": "current authorization-bound valid invariant set",
                "observed": {"invariant_set_hash": set_hash},
            })
        dnt_target = any(
            item.get("type") == DNT_PRESERVATION
            and _precommit_path(item.get("path")) == _precommit_path(target_path)
            for item in applicable
        )
        if dnt_target and not authority_errors:
            violations.append({
                "invariant_id": next(
                    _text(item.get("invariant_id"), 160)
                    for item in applicable if item.get("type") == DNT_PRESERVATION
                ),
                "type": DNT_PRESERVATION,
                "symbol": "",
                "path": target_path,
                "classification": PRESERVE,
                "reason": "candidate target is inside a do-not-touch surface",
                "expected": "target remains unmodified",
                "observed": target_path,
            })
        if not authority_errors and not dnt_target and pre_state_available and candidate_text is not None:
            for item in applicable:
                if _text(item.get("classification"), 80) != PRESERVE:
                    continue
                pre_content, _pre_item_raw, _pre_item_error = _read_subject_file(
                    self.workspace, _path(item.get("path")), self.source_files,
                )
                violations.extend(_precommit_semantic_violations(
                    item, target_path=target_path, target_content=candidate_text,
                    pre_content=pre_content,
                    workspace=self.workspace, source_files=merged_files,
                ))
        status = (
            EXECUTION_INVARIANT_MUTATION_VIOLATION
            if violations else PRECOMMIT_ALLOWED
        )
        if dnt_target and not authority_errors:
            status = PRECOMMIT_DNT_VIOLATION
        default_id = "MUTATION-" + canonical_hash({
            "path": target_path, "pre_state_hash": pre_hash,
            "candidate_hash": candidate_hash,
        })[:24].upper()
        return _build_precommit_audit(
            candidate_mutation_id=mutation_id or default_id,
            path=target_path,
            pre_state_hash=pre_hash,
            candidate_hash=candidate_hash,
            applicable=applicable,
            violations=violations,
            status=status,
            authority_set_hash=set_hash,
            authority_errors=authority_errors,
        )

    check = evaluate
    validate = evaluate

    def __call__(self, path: str, candidate_content: Any, original_content: Any = None, **kwargs: Any) -> PreCommitInvariantAudit:
        return self.evaluate(path, candidate_content, original_content, **kwargs)


def format_precommit_invariant_feedback(audit: Any) -> str:
    value = audit if isinstance(audit, dict) else {}
    violations = value.get("violations", []) if isinstance(value.get("violations"), list) else []
    details = []
    for item in violations[:3]:
        if not isinstance(item, dict):
            continue
        expected = _text(json.dumps(
            _precommit_compact(item.get("expected")),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        ), 170)
        observed = _text(json.dumps(
            _precommit_compact(item.get("observed")),
            ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str,
        ), 170)
        details.append(
            f"{item.get('invariant_id')}:{item.get('type')}"
            f"[{item.get('classification')}] {_text(item.get('reason'), 120)}"
            f" expected={expected} observed={observed}"
        )
    if not details:
        details.append("none")
    return (
        "error: mutation rejected before commit; "
        f"candidate_mutation_id={value.get('candidate_mutation_id')}; "
        f"path={value.get('path')}; pre_hash={value.get('pre_state_hash')}; "
        f"candidate_hash={value.get('candidate_hash')}; "
        f"applicable_invariants={','.join(str(item) for item in value.get('applicable_invariant_ids', []) or []) or 'none'}; "
        f"classifications={json.dumps(value.get('classifications', {}), sort_keys=True, separators=(',', ':'))}; "
        f"violations={'; '.join(details)}; status={value.get('status')}; "
        f"canonical_hash={value.get('canonical_hash')}"
    )


def validate_precommit_invariant_audit(audit: Any) -> dict[str, Any]:
    value = audit if isinstance(audit, dict) else {}
    expected = canonical_precommit_invariant_audit_hash(value) if value else ""
    actual = _text(value.get("canonical_hash"), 128)
    return {
        "valid": bool(value) and bool(actual) and actual == expected,
        "status": PRECOMMIT_ALLOWED if bool(value) and actual == expected else EXECUTION_INVARIANT_INVALID,
        "errors": [] if bool(value) and actual == expected else ["pre-commit audit hash does not match content"],
        "canonical_hash": actual,
    }


def precommit_execution_invariant_gate(
    invariant_set: Any,
    path: str,
    candidate_content: Any,
    *,
    original_content: Any = None,
    contract: dict[str, Any] | None = None,
    authorization: dict[str, Any] | None = None,
    workspace: str | Path | None = None,
    source_files: dict[str, Any] | None = None,
    pre_state_bytes: bytes | None = None,
    mutation_id: str | None = None,
) -> PreCommitInvariantAudit:
    return PreCommitExecutionInvariantGate(
        invariant_set, contract=contract, authorization=authorization,
        workspace=workspace, source_files=source_files,
    ).evaluate(
        path, candidate_content, original_content,
        pre_state_bytes=pre_state_bytes, mutation_id=mutation_id,
    )


evaluate_candidate_mutation = precommit_execution_invariant_gate
validate_candidate_preservation = precommit_execution_invariant_gate
candidate_semantic_preservation_check = precommit_execution_invariant_gate
run_precommit_execution_invariant_gate = precommit_execution_invariant_gate
precommit_gate = precommit_execution_invariant_gate


def _projection_core(set_hash: str, items: list[dict[str, Any]]) -> dict[str, Any]:
    compact = [_compact_invariant(item) for item in items]
    return {
        "schema_version": SCHEMA_VERSION,
        "execution_invariant_set_hash": _text(set_hash, 128),
        "invariant_ids": [item.get("invariant_id") for item in compact],
        "invariants": compact,
        "mandatory": True,
        "mandatory_drops": 0,
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_worker_execution_invariant_projection(invariant_set: Any, contract: dict[str, Any] | None = None,
                                                *, max_chars: int = MAX_CONTEXT_CHARS) -> WorkerExecutionInvariantProjection:
    checked = validate_execution_invariant_set(invariant_set, execution_contract=contract)
    if not checked.get("valid"):
        raise ExecutionInvariantError(
            str(checked.get("code") or EXECUTION_INVARIANT_INVALID),
            "; ".join(checked.get("errors", [])) or "execution invariant set is invalid",
            checked.get("errors", []),
        )
    value = invariant_set if isinstance(invariant_set, dict) else {}
    items = relevant_invariants(value, contract)
    if not items:
        raise ExecutionInvariantError(EXECUTION_INVARIANT_UNSUPPORTED, "no responsibility-relevant execution invariants are available")
    if len(items) > MAX_PROJECTED_INVARIANTS:
        raise ExecutionInvariantError(
            EXECUTION_INVARIANT_CONTEXT_OVERFLOW,
            f"relevant Worker execution invariant count exceeds its bound ({len(items)} > {MAX_PROJECTED_INVARIANTS})",
        )
    result = _projection_core(value.get("invariant_set_hash"), items)
    result["projection_hash"] = canonical_hash(result)
    rendered = render_worker_execution_invariant_projection(result, max_chars=max_chars)
    result["rendered_chars"] = len(rendered)
    result["provider_facing_hash"] = canonical_hash(rendered)
    if len(rendered) > max_chars:
        raise ExecutionInvariantError(
            EXECUTION_INVARIANT_CONTEXT_OVERFLOW,
            f"mandatory Worker execution invariants exceed context bound ({len(rendered)} > {max_chars})",
        )
    return _freeze_record(WorkerExecutionInvariantProjection, result)


project_worker_execution_invariants = build_worker_execution_invariant_projection


def _format_outputs(values: list[Any]) -> str:
    return ", ".join(json.dumps(str(value), ensure_ascii=False) for value in values[:MAX_OUTPUTS])


def render_worker_execution_invariant_projection(projection: Any, *, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    value = projection if isinstance(projection, dict) else {}
    lines = ["CURRENT EXECUTION INVARIANTS — AUTHORITATIVE"]
    for item in value.get("invariants", []) or []:
        if not isinstance(item, dict):
            continue
        kind = item.get("type")
        symbol = _symbol(item.get("symbol"))
        path = _path(item.get("path"))
        subject = f"{symbol}" + (f" ({path})" if path else "")
        if kind == FUNCTION_SIGNATURE:
            lines.append(f"- {item.get('signature') or symbol} is the current function signature.")
        elif kind == RETURN_SHAPE:
            lines.append(f"- {symbol} currently returns a {item.get('return_shape') or 'known'}.")
        elif kind == EXACT_EXISTING_OUTPUT:
            outputs = item.get("existing_outputs") or []
            lines.append(f"- Existing compatible outputs of {symbol} are {_format_outputs(outputs)}.")
        elif kind == CONSUMER_EXPECTATION:
            outputs = item.get("existing_outputs") or []
            contract_word = "string" if item.get("return_shape") == "primitive string" or outputs else "current"
            lines.append(f"- Existing consumers depend on the {contract_word} contract of {symbol}.")
            for consumer in item.get("consumers", [])[:MAX_CONSUMER_EXPECTATIONS]:
                if isinstance(consumer, dict):
                    expected = consumer.get("expected")
                    expected_values = expected if isinstance(expected, list) else [expected]
                    lines.append(f"  - {consumer.get('path')}: {_format_outputs(expected_values)}")
        elif kind == INTERFACE_COMPATIBILITY:
            if item.get("classification") == CHANGE_AUTHORIZED:
                lines.append(f"- The approved plan explicitly authorizes changing the current interface contract of {symbol}.")
            else:
                lines.append(f"- Preserve the existing compatible contract of {symbol}; the approved plan does not authorize replacing its return shape.")
            if item.get("additive"):
                lines.append("- Implement the approved new behavior additively without breaking existing consumers.")
        elif kind == STATE_OWNER:
            lines.append(f"- {item.get('owner') or symbol} remains the current state owner.")
        elif kind == REQUIRED_INTERFACE_REUSE:
            lines.append(f"- Reuse the approved existing interface {item.get('interface') or symbol}.")
        elif kind == DNT_PRESERVATION:
            lines.append(f"- Do not modify {path or subject}.")
    lines.append("IMPLEMENTATION CHOICE: Worker chooses an implementation satisfying these invariants.")
    lines.append("- Invariants are mandatory; MAY MODIFY scope is separate.")
    rendered = "\n".join(lines)
    if len(rendered) > max(1, int(max_chars)):
        raise ExecutionInvariantError(
            EXECUTION_INVARIANT_CONTEXT_OVERFLOW,
            f"mandatory Worker execution invariants exceed context bound ({len(rendered)} > {max_chars})",
        )
    return rendered


render_worker_invariant_projection = render_worker_execution_invariant_projection


def validate_worker_execution_invariant_projection(projection: Any, invariant_set: Any,
                                                   contract: dict[str, Any] | None = None,
                                                   *, max_chars: int = MAX_CONTEXT_CHARS) -> dict[str, Any]:
    value = projection if isinstance(projection, dict) else {}
    errors = []
    checked_set = validate_execution_invariant_set(invariant_set, execution_contract=contract)
    if not checked_set.get("valid"):
        errors.extend(checked_set.get("errors", []))
    expected = _projection_core(
        (invariant_set or {}).get("invariant_set_hash") if isinstance(invariant_set, dict) else "",
        relevant_invariants(invariant_set, contract),
    )
    if value.get("execution_invariant_set_hash") != expected.get("execution_invariant_set_hash"):
        errors.append("projection invariant-set hash mismatch")
    if value.get("invariant_ids") != expected.get("invariant_ids"):
        errors.append("projection invariant ids mismatch")
    if value.get("invariants") != expected.get("invariants"):
        errors.append("projection invariant semantics mismatch")
    if value.get("mandatory_drops") != 0:
        errors.append("mandatory execution invariants were dropped")
    if not _metric_is_zero(value.get("model_calls", 0)):
        errors.append("Worker invariant projection contains model calls")
    if not _metric_is_zero(value.get("worker_calls", 0)):
        errors.append("Worker invariant projection contains Worker calls")
    if value.get("projection_hash") != canonical_hash(_without(value, "projection_hash", "rendered_chars", "provider_facing_hash")):
        errors.append("projection hash mismatch")
    try:
        rendered = render_worker_execution_invariant_projection(value, max_chars=max_chars)
    except ExecutionInvariantError as exc:
        rendered = ""
        errors.append(str(exc))
    if value.get("rendered_chars") not in (None, len(rendered)):
        errors.append("projection rendered size is stale")
    if value.get("provider_facing_hash") not in (None, canonical_hash(rendered)):
        errors.append("provider-facing invariant hash mismatch")
    return {
        "valid": not errors,
        "status": VALID if not errors else EXECUTION_INVARIANT_INVALID,
        "errors": errors[:40],
        "rendered_chars": len(rendered),
        "mandatory_drops": value.get("mandatory_drops", 0),
        "model_calls": 0,
    }


validate_worker_invariant_projection = validate_worker_execution_invariant_projection


__all__ = [name for name in globals() if not name.startswith("_")]
