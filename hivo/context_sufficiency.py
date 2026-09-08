"""Bounded worker context-sufficiency and evidence-completion gate.

The Stage 4 worker packet remains the initial context.  This module adds only
the small repair loop that lets a Worker identify a missing semantic fact and
ask for that fact before it can mutate the workspace.  It is intentionally
provider-agnostic: callers supply the narrow evidence provider, while this
module owns request validation, bounds, stable goal anchoring, deduplication,
contradiction handling, and the mutation authorization decision.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import re
from typing import Any, Callable, Iterable, Mapping


# Lifecycle labels are local to a Worker attempt.  They do not replace the
# repository's task/approval/verification lifecycle.
PREPARING_CONTEXT = "PREPARING_CONTEXT"
CONTEXT_SUFFICIENT = "CONTEXT_SUFFICIENT"
CONTEXT_INSUFFICIENT = "CONTEXT_INSUFFICIENT"
REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
MUTATION_ALLOWED = "MUTATION_ALLOWED"

CONTEXT_STATUS_SUFFICIENT = "sufficient"
CONTEXT_STATUS_INSUFFICIENT = "insufficient"
CONTEXT_INSUFFICIENT_FAILURE = "CONTEXT_INSUFFICIENT"
CONTEXT_EVIDENCE_PROVIDER_UNAVAILABLE = "CONTEXT_EVIDENCE_PROVIDER_UNAVAILABLE"
CONTEXT_EVIDENCE_REQUEST_INVALID = "CONTEXT_EVIDENCE_REQUEST_INVALID"

# These are deliberately small.  They limit semantic completion, not the
# existing Worker tool-step, retry, or model context-window budgets.
MAX_CONTEXT_COMPLETION_ROUNDS = 3
MAX_EVIDENCE_REQUESTS_PER_ROUND = 3
MAX_CONTEXT_EVIDENCE_ITEMS = 12
MAX_CONTEXT_EVIDENCE_CHARS = 4200
MAX_CONTEXT_EVIDENCE_ITEM_CHARS = 700
MAX_CONTEXT_EVIDENCE_SOURCE_CHARS = 240
MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS = 320
MAX_CONTEXT_EVIDENCE_FACTS = 8
MAX_CONTEXT_EVIDENCE_FACT_CHARS = 320
# There can be at most three requests per round across three rounds; keep one
# compact coverage record for every possible request without exceeding the
# existing twelve-item working-evidence ceiling.
MAX_CONTEXT_SEMANTIC_RESOLUTIONS = 12
MAX_CONTEXT_REASON_CHARS = 420
MAX_CONTEXT_ANCHOR_LIST_ITEMS = 8
MAX_CONTEXT_ANCHOR_ITEM_CHARS = 360

EVIDENCE_REQUEST_KINDS = frozenset({
    "callers",
    "consumers",
    "contract",
    "authoritative_contract",
    "interface",
    "definition",
    "schema",
    "tests",
    "state_transition",
    "invariant",
    "sibling_implementation",
    "downstream_impact",
    "return_expectation",
    "caller_expectation",
    "callee_dependency",
    "test_expectation",
    "type_or_schema",
    "state_invariant",
    "symbol_definition",
    "export_or_public_surface",
    "configuration_dependency",
})
_VAGUE_WORDS = frozenset({
    "more_context",
    "context",
    "everything",
    "repository",
    "read_repository",
    "all_related_files",
    "related_files",
    "whole_module",
    "all_files",
    "anything",
})
_VAGUE_PHRASES = (
    "more context",
    "whole module",
    "all related files",
    "everything about",
    "read the repository",
    "all related code",
    "entire repository",
    "all files",
)
_GENERIC_REASONS = {
    "need more context",
    "need more information",
    "to understand",
    "for context",
    "need context",
    "not enough context",
}
_AUTHORITATIVE_KINDS = frozenset({
    "contract", "authoritative_contract", "interface", "definition", "schema", "tests",
    "callers", "consumers", "return_expectation",
})
_SEMANTIC_REQUEST_KEY_ALIASES = {
    "authoritative_contract": "contract",
    "interface": "contract",
    "consumers": "caller_expectation",
    "callers": "caller_expectation",
    "return_expectation": "caller_expectation",
    "tests": "test_expectation",
    "schema": "type_or_schema",
    "invariant": "state_invariant",
    "definition": "symbol_definition",
}


class ContextSufficiencyError(ValueError):
    """A worker sufficiency decision or targeted request is not usable."""


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _text(value: Any, limit: int) -> str:
    value = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _unique(values: Iterable[Any], *, limit: int, text_limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in _list(values):
        item = _text(value, text_limit)
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
        if len(result) >= max(0, int(limit)):
            break
    return result


def _bounded_facts(value: Any) -> list[str]:
    return _unique(
        value,
        limit=MAX_CONTEXT_EVIDENCE_FACTS,
        text_limit=MAX_CONTEXT_EVIDENCE_FACT_CHARS,
    )


def _resolution_status(value: Any) -> str:
    status = str(value or "").strip().casefold()
    return status if status in {"resolved", "partial", "unresolved", "conflicting"} else ""


def _merge_resolution_status(current: Any, incoming: Any) -> str:
    """Merge coverage conservatively; any unresolved input stays pending."""
    statuses = {_resolution_status(current), _resolution_status(incoming)}
    statuses.discard("")
    if "conflicting" in statuses:
        return "conflicting"
    if "unresolved" in statuses:
        return "unresolved"
    if "partial" in statuses:
        return "partial"
    return "resolved" if statuses else ""


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _normalize_kind(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().casefold()).strip("_")


def _semantic_request_key_kind(value: Any) -> str:
    kind = _normalize_kind(value)
    return _SEMANTIC_REQUEST_KEY_ALIASES.get(kind, kind)


def _normalize_anchor(anchor: Mapping[str, Any] | None, *, local_task: Any = None) -> dict[str, Any]:
    value = anchor if isinstance(anchor, Mapping) else {}
    return {
        # These fields are copied once and never replaced by evidence.  The
        # Worker can see them again after each completion round.
        "root_goal": _text(value.get("root_goal") or value.get("root_goal_anchor"), MAX_CONTEXT_REASON_CHARS)
        or _text(value.get("goal"), MAX_CONTEXT_REASON_CHARS),
        "parent_goal": _text(value.get("parent_goal") or value.get("parent_goal_anchor"), MAX_CONTEXT_REASON_CHARS),
        "local_task": _text(value.get("local_task") or value.get("task") or local_task, MAX_CONTEXT_REASON_CHARS),
        # A semantic work group is a bounded, stable extension of the existing
        # goal anchor.  Evidence completion may replace working evidence, but
        # it must not replace this group-level intent or invariant.
        "group_goal": _text(value.get("group_goal") or value.get("semantic_group_goal"), MAX_CONTEXT_REASON_CHARS),
        "group_invariant": _text(
            value.get("group_invariant") or value.get("semantic_group_invariant"),
            MAX_CONTEXT_REASON_CHARS,
        ),
        "requirements": _unique(
            value.get("requirements") or value.get("authoritative_requirements"),
            limit=MAX_CONTEXT_ANCHOR_LIST_ITEMS,
            text_limit=MAX_CONTEXT_ANCHOR_ITEM_CHARS,
        ),
        "constraints": _unique(
            value.get("constraints") or value.get("invariants"),
            limit=MAX_CONTEXT_ANCHOR_LIST_ITEMS,
            text_limit=MAX_CONTEXT_ANCHOR_ITEM_CHARS,
        ),
        "allowed_inspection_paths": _unique(
            value.get("allowed_inspection_paths"),
            limit=16,
            text_limit=240,
        ),
    }


def _anchor_identity(anchor: Mapping[str, Any]) -> str:
    return canonical_hash(anchor)


def context_sufficiency_schema() -> dict[str, Any]:
    """Return the machine-readable Worker decision schema."""
    return {
        "type": "object",
        "properties": {
            "context_status": {
                "type": "string",
                "enum": [CONTEXT_STATUS_SUFFICIENT, CONTEXT_STATUS_INSUFFICIENT],
            },
            "reason": {"type": "string", "maxLength": MAX_CONTEXT_REASON_CHARS},
            "needed_evidence": {
                "type": "array",
                "maxItems": MAX_EVIDENCE_REQUESTS_PER_ROUND,
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {"type": "string"},
                        "target": {"type": "string"},
                        "why": {"type": "string", "maxLength": MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS},
                    },
                    "required": ["kind", "target", "why"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["context_status"],
        "additionalProperties": False,
    }


def validate_evidence_request(request: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate one narrow semantic request and return its canonical form."""
    value = request if isinstance(request, Mapping) else {}
    kind = _normalize_kind(value.get("kind"))
    target = _text(value.get("target"), 180)
    why = _text(value.get("why"), MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS)
    errors: list[str] = []
    if kind not in EVIDENCE_REQUEST_KINDS:
        errors.append(f"kind must be one of {sorted(EVIDENCE_REQUEST_KINDS)}")
    if not target:
        errors.append("target is required and must identify one symbol, path, contract, or transition")
    target_lower = target.casefold()
    if target_lower in _VAGUE_WORDS or any(phrase in target_lower for phrase in _VAGUE_PHRASES):
        errors.append("target is broad; identify one symbol, path, contract, caller, test, or transition")
    if len(target) > 180:
        errors.append("target is too long")
    if len(why) < 12 or why.casefold() in _GENERIC_REASONS:
        errors.append("why must explain the concrete semantic decision this evidence resolves")
    if errors:
        return {"valid": False, "errors": errors[:8], "request": None}
    return {
        "valid": True,
        "errors": [],
        "request": {"kind": kind, "target": target, "why": why},
    }


def validate_sufficiency_decision(decision: Mapping[str, Any] | None) -> dict[str, Any]:
    """Validate the small Worker decision before it changes gate state."""
    value = decision if isinstance(decision, Mapping) else {}
    allowed = {"context_status", "reason", "needed_evidence"}
    errors = [f"unexpected field: {key}" for key in value if key not in allowed]
    status = str(value.get("context_status") or "").strip().casefold()
    reason = _text(value.get("reason"), MAX_CONTEXT_REASON_CHARS)
    raw_requests = value.get("needed_evidence", [])
    if raw_requests is None:
        raw_requests = []
    if not isinstance(raw_requests, list):
        errors.append("needed_evidence must be a list")
        raw_requests = []
    if status not in {CONTEXT_STATUS_SUFFICIENT, CONTEXT_STATUS_INSUFFICIENT}:
        errors.append("context_status must be 'sufficient' or 'insufficient'")
    if status == CONTEXT_STATUS_INSUFFICIENT and not reason:
        errors.append("insufficient context requires a reason")
    if len(raw_requests) > MAX_EVIDENCE_REQUESTS_PER_ROUND:
        errors.append("needed_evidence exceeds the per-round bound")
    requests: list[dict[str, str]] = []
    for index, request in enumerate(raw_requests[:MAX_EVIDENCE_REQUESTS_PER_ROUND], 1):
        checked = validate_evidence_request(request)
        if not checked["valid"]:
            errors.extend(f"needed_evidence[{index}]: {item}" for item in checked["errors"])
        elif checked.get("request"):
            requests.append(checked["request"])
    if status == CONTEXT_STATUS_INSUFFICIENT and not requests:
        errors.append("insufficient context requires at least one targeted evidence request")
    return {
        "valid": not errors,
        "errors": errors[:20],
        "decision": {
            "context_status": status,
            "reason": reason,
            "needed_evidence": requests,
        } if not errors else None,
    }


def _normalize_initial_evidence(item: Any, index: int) -> dict[str, Any] | None:
    if not isinstance(item, Mapping):
        return None
    source = _text(item.get("source_identity") or item.get("source") or item.get("path"), MAX_CONTEXT_EVIDENCE_SOURCE_CHARS)
    excerpt = _text(
        item.get("excerpt") or item.get("fact") or item.get("text") or item.get("content"),
        MAX_CONTEXT_EVIDENCE_ITEM_CHARS,
    )
    symbol = _text(item.get("symbol") or item.get("component"), 180)
    if not source and not excerpt and not symbol:
        return None
    evidence_id = _text(item.get("evidence_id"), 120) or f"INITIAL-{index:03d}"
    return {
        "evidence_id": evidence_id,
        "kind": _normalize_kind(item.get("kind") or item.get("category") or "initial") or "initial",
        "target": _text(item.get("target") or symbol or source, 180),
        "source_identity": source,
        "symbol": symbol,
        "excerpt": excerpt,
        "purpose": _text(item.get("purpose") or "initial bounded evidence packet", MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS),
        "provenance": _text(item.get("provenance") or "INITIAL_EVIDENCE_PACKET", 100),
        "claim_key": _text(item.get("claim_key"), 180),
        "claim_value": _text(item.get("claim_value"), MAX_CONTEXT_EVIDENCE_ITEM_CHARS),
        "authoritative": bool(item.get("authoritative")),
        "resolves_conflict": bool(item.get("resolves_conflict")),
        "semantic_request_kind": _text(item.get("semantic_request_kind"), 80),
        "resolution_status": _resolution_status(item.get("resolution_status")),
        "facts_established": _bounded_facts(item.get("facts_established")),
        "authority_tier": _text(item.get("authority_tier"), 40),
        "authority_score": _integer(item.get("authority_score", 0)),
        "relationship": _text(item.get("relationship"), 120),
        "source_kind": _text(item.get("source_kind"), 120),
        "role": _text(item.get("role"), 120),
        "_request_key": "initial:" + evidence_id,
        "_origin": "initial",
    }


def _normalize_provider_evidence(item: Any, request: Mapping[str, str], index: int) -> dict[str, Any] | None:
    value = item if isinstance(item, Mapping) else {}
    source = _text(
        value.get("source_identity") or value.get("source") or value.get("path") or value.get("file"),
        MAX_CONTEXT_EVIDENCE_SOURCE_CHARS,
    )
    excerpt = _text(
        value.get("excerpt") or value.get("fact") or value.get("text") or value.get("content"),
        MAX_CONTEXT_EVIDENCE_ITEM_CHARS,
    )
    symbol = _text(value.get("symbol") or value.get("component"), 180)
    if not source and not excerpt and not symbol:
        return None
    kind = _normalize_kind(value.get("kind") or request.get("kind")) or request.get("kind", "evidence")
    target = _text(value.get("target") or request.get("target"), 180)
    purpose = _text(value.get("purpose") or request.get("why"), MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS)
    evidence_id = _text(value.get("evidence_id"), 120)
    identity = {
        "kind": kind,
        "target": target,
        "source_identity": source,
        "symbol": symbol,
        "excerpt": excerpt,
        "claim_key": _text(value.get("claim_key"), 180),
        "claim_value": _text(value.get("claim_value"), MAX_CONTEXT_EVIDENCE_ITEM_CHARS),
    }
    evidence_id = evidence_id or "COMPLETION-" + canonical_hash(identity)[:16].upper()
    slot_kind = _normalize_kind(
        value.get("semantic_request_kind") or value.get("kind") or request.get("kind")
    )
    if slot_kind == "authoritative_contract":
        slot_kind = "contract"
    request_key = (
        f"{slot_kind}:{target}:{source}:{symbol}:"
        f"{_text(value.get('claim_key'), 180)}"
    )
    if not source and not symbol and not value.get("claim_key"):
        request_key += ":" + canonical_hash(excerpt)[:16]
    return {
        "evidence_id": evidence_id,
        "kind": kind,
        "target": target,
        "source_identity": source,
        "symbol": symbol,
        "excerpt": excerpt,
        "purpose": purpose,
        "provenance": _text(value.get("provenance") or "TARGETED_CONTEXT_COMPLETION", 100),
        "claim_key": _text(value.get("claim_key"), 180),
        "claim_value": _text(value.get("claim_value"), MAX_CONTEXT_EVIDENCE_ITEM_CHARS),
        "authoritative": bool(value.get("authoritative")),
        "resolves_conflict": bool(value.get("resolves_conflict")),
        "contradiction": _text(value.get("contradiction") or value.get("conflict"), MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS),
        "semantic_request_kind": _text(value.get("semantic_request_kind"), 80),
        "resolution_status": _resolution_status(value.get("resolution_status")),
        "facts_established": _bounded_facts(value.get("facts_established")),
        "authority_tier": _text(value.get("authority_tier"), 40),
        "authority_score": _integer(value.get("authority_score", 0)),
        "relationship": _text(value.get("relationship"), 120),
        "source_kind": _text(value.get("source_kind"), 120),
        "role": _text(value.get("role"), 120),
        "_request_key": request_key,
        "_origin": "completion",
    }


def _public_evidence(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _copy(item.get(key))
        for key in (
            "evidence_id", "kind", "target", "source_identity", "symbol", "excerpt",
            "purpose", "provenance", "claim_key", "claim_value", "authoritative",
            "resolves_conflict", "contradiction", "semantic_request_kind",
            "resolution_status", "facts_established", "authority_tier",
            "authority_score", "relationship", "source_kind", "role",
        )
        if item.get(key) not in (None, "", False)
    }


def _provider_items(result: Any) -> list[Any]:
    if isinstance(result, Mapping):
        evidence = result.get("evidence")
        if isinstance(evidence, list):
            return evidence
        if isinstance(evidence, Mapping):
            return [evidence]
        if any(key in result for key in ("excerpt", "fact", "text", "source", "path")):
            return [result]
        return []
    if isinstance(result, list):
        return result
    return []


def _provider_resolution(result: Any, request: Mapping[str, str], evidence: list[Mapping[str, Any]]) -> dict[str, Any] | None:
    """Project resolver coverage metadata without copying source bodies."""
    if not isinstance(result, Mapping):
        return None
    source = result.get("semantic_resolution") if isinstance(result.get("semantic_resolution"), Mapping) else result
    status = _resolution_status(source.get("resolution_status"))
    if not status:
        return None
    facts = _bounded_facts(source.get("facts_established"))
    return {
        "request_kind": _text(source.get("request_kind") or request.get("kind"), 80),
        "gate_request_kind": _text(source.get("gate_request_kind") or request.get("kind"), 80),
        "target": _text(source.get("target") or request.get("target"), 180),
        "resolution_status": status,
        "facts_established": facts,
        "conflicts": _copy(source.get("conflicts", []))[:4] if isinstance(source.get("conflicts"), list) else [],
        "evidence_ids": [
            _text(item.get("evidence_id"), 120)
            for item in evidence
            if isinstance(item, Mapping) and item.get("evidence_id")
        ][:MAX_CONTEXT_EVIDENCE_ITEMS],
        "candidates_considered": _integer(source.get("candidates_considered", 0)),
        "candidate_files_considered": _integer(source.get("candidate_files_considered", 0)),
        "relationship_hops": _integer(source.get("relationship_hops", 0)),
    }


def _invoke_provider(provider: Callable[..., Any] | None, request: Mapping[str, str], context: Mapping[str, Any]) -> Any:
    if not callable(provider):
        return None
    try:
        signature = inspect.signature(provider)
    except (TypeError, ValueError):
        return provider(request, context)
    parameters = list(signature.parameters.values())
    if any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters):
        return provider(request=request, context=context)
    accepted = {
        item.name: value
        for item in parameters
        for value in ({"request": request, "context": context}.get(item.name),)
        if item.name in {"request", "context"}
        and item.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    missing = [
        item for item in parameters
        if item.default is inspect.Parameter.empty
        and item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        and item.name not in accepted
    ]
    if not missing:
        return provider(**accepted)
    positional = [request, context]
    return provider(*positional[: len([item for item in parameters if item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}])])


class ContextSufficiencyGate:
    """One bounded, local sufficiency/completion state machine."""

    def __init__(
        self,
        anchor: Mapping[str, Any] | None,
        *,
        initial_evidence: Iterable[Mapping[str, Any]] | None = None,
        evidence_provider: Callable[..., Any] | None = None,
        max_rounds: int = MAX_CONTEXT_COMPLETION_ROUNDS,
        max_requests_per_round: int = MAX_EVIDENCE_REQUESTS_PER_ROUND,
        max_evidence_items: int = MAX_CONTEXT_EVIDENCE_ITEMS,
        max_evidence_chars: int = MAX_CONTEXT_EVIDENCE_CHARS,
    ) -> None:
        self.max_rounds = max(0, int(max_rounds))
        self.max_requests_per_round = max(1, int(max_requests_per_round))
        self.max_evidence_items = max(1, int(max_evidence_items))
        self.max_evidence_chars = max(256, int(max_evidence_chars))
        self.provider = evidence_provider
        self._anchor = _normalize_anchor(anchor)
        self._anchor_hash = _anchor_identity(self._anchor)
        self._evidence: list[dict[str, Any]] = []
        # The provider may establish semantic coverage independently of the
        # Worker wording. Keep one bounded record per request so a partial or
        # conflicting resolver result cannot be promoted by a later
        # context_status=sufficient claim.
        self._semantic_resolutions: dict[str, dict[str, Any]] = {}
        for index, item in enumerate(list(initial_evidence or []), 1):
            normalized = _normalize_initial_evidence(item, index)
            if normalized is not None:
                self._evidence.append(normalized)
                initial_status = normalized.get("resolution_status")
                if initial_status:
                    semantic_kind = _semantic_request_key_kind(
                        normalized.get("semantic_request_kind")
                        or normalized.get("kind")
                        or "initial"
                    )
                    initial_key = f"{semantic_kind}:{normalized.get('target', '')}".casefold()
                    existing = self._semantic_resolutions.get(initial_key)
                    if existing is None:
                        self._semantic_resolutions[initial_key] = {
                            "request_key": initial_key,
                            "request_kind": normalized.get("semantic_request_kind") or normalized.get("kind"),
                            "gate_request_kind": normalized.get("kind"),
                            "target": normalized.get("target"),
                            "resolution_status": initial_status,
                            "facts_established": list(normalized.get("facts_established", []) or []),
                            "conflicts": [],
                            "evidence_ids": [normalized.get("evidence_id")],
                            "candidates_considered": 0,
                            "candidate_files_considered": 0,
                            "relationship_hops": 0,
                        }
                    else:
                        # Multiple initial excerpts for one semantic slot must
                        # not let a later optimistic status erase an earlier
                        # unresolved or conflicting status.
                        existing["resolution_status"] = _merge_resolution_status(
                            existing.get("resolution_status"), initial_status,
                        )
                        existing["facts_established"] = _unique(
                            [
                                *(existing.get("facts_established", []) or []),
                                *(normalized.get("facts_established", []) or []),
                            ],
                            limit=MAX_CONTEXT_EVIDENCE_FACTS,
                            text_limit=MAX_CONTEXT_EVIDENCE_FACT_CHARS,
                        )
                        existing["evidence_ids"] = _unique(
                            [
                                *(existing.get("evidence_ids", []) or []),
                                normalized.get("evidence_id"),
                            ],
                            limit=MAX_CONTEXT_EVIDENCE_ITEMS,
                            text_limit=120,
                        )
        while len(self._semantic_resolutions) > MAX_CONTEXT_SEMANTIC_RESOLUTIONS:
            self._semantic_resolutions.pop(next(iter(self._semantic_resolutions)))
        self._dropped_evidence = 0
        self._round = 0
        self._request_count = 0
        self._history: list[dict[str, Any]] = []
        self._last_evidence: list[dict[str, Any]] = []
        self._contradictions: list[dict[str, Any]] = []
        self._state = PREPARING_CONTEXT
        self._context_status: str | None = None
        self._reason = ""
        self._failure_code: str | None = None
        self._mutation_allowed = False
        self._trim_evidence()
        self._refresh_contradictions()

    @property
    def mutation_allowed(self) -> bool:
        return bool(self._mutation_allowed and self._state == MUTATION_ALLOWED)

    @property
    def state(self) -> str:
        return self._state

    @property
    def anchor(self) -> dict[str, Any]:
        return _copy(self._anchor)

    def _public_requests(self, requests: Iterable[Mapping[str, Any]]) -> list[dict[str, str]]:
        return [{
            "kind": str(item.get("kind", "")),
            "target": str(item.get("target", "")),
            "why": str(item.get("why", "")),
        } for item in requests]

    def _trim_evidence(self) -> None:
        # Keep the initial packet and the newest completion slots where
        # possible.  A repeated semantic request replaces its prior slot.
        seen_slots: set[str] = set()
        deduplicated: list[dict[str, Any]] = []
        for item in self._evidence:
            slot = str(item.get("_request_key") or item.get("evidence_id"))
            if slot in seen_slots:
                for index, previous in enumerate(deduplicated):
                    if str(previous.get("_request_key") or previous.get("evidence_id")) == slot:
                        deduplicated[index] = item
                        break
                continue
            seen_slots.add(slot)
            deduplicated.append(item)
        self._evidence = deduplicated
        while len(self._evidence) > self.max_evidence_items:
            completion_index = next(
                (index for index, item in enumerate(self._evidence) if item.get("_origin") == "completion"),
                None,
            )
            remove_index = completion_index if completion_index is not None else 0
            self._evidence.pop(remove_index)
            self._dropped_evidence += 1
        while self._evidence and self._serialized_evidence_chars() > self.max_evidence_chars:
            completion_index = next(
                (index for index, item in enumerate(self._evidence) if item.get("_origin") == "completion"),
                None,
            )
            if completion_index is None and len(self._evidence) == 1:
                # The item excerpt was already capped; keep the one slot so a
                # provider cannot cause unbounded growth.
                break
            self._evidence.pop(completion_index if completion_index is not None else 0)
            self._dropped_evidence += 1

    def _serialized_evidence_chars(self) -> int:
        return len(json.dumps([_public_evidence(item) for item in self._evidence], ensure_ascii=False, default=str))

    def _refresh_contradictions(self) -> None:
        records: list[dict[str, Any]] = []
        claims: dict[str, dict[str, Any]] = {}
        for item in self._evidence:
            explicit = item.get("contradiction")
            if explicit:
                records.append({
                    "claim_key": item.get("claim_key") or item.get("target"),
                    "reason": _text(explicit, MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS),
                    "evidence_ids": [item.get("evidence_id")],
                })
            claim_key = _text(item.get("claim_key"), 180)
            claim_value = _text(item.get("claim_value"), MAX_CONTEXT_EVIDENCE_ITEM_CHARS)
            if not claim_key or not claim_value:
                continue
            previous = claims.get(claim_key)
            if previous is None:
                claims[claim_key] = {
                    "claim_key": claim_key,
                    "claim_value": claim_value,
                    "evidence_ids": [item.get("evidence_id")],
                }
                continue
            if previous.get("claim_value") == claim_value:
                previous.setdefault("evidence_ids", []).append(item.get("evidence_id"))
                continue
            if item.get("resolves_conflict") and item.get("authoritative"):
                claims[claim_key] = {
                    "claim_key": claim_key,
                    "claim_value": claim_value,
                    "evidence_ids": [item.get("evidence_id")],
                }
                records = [record for record in records if record.get("claim_key") != claim_key]
                continue
            records.append({
                "claim_key": claim_key,
                "reason": "bounded evidence contains conflicting claims",
                "evidence_ids": list(dict.fromkeys(
                    list(previous.get("evidence_ids", [])) + [item.get("evidence_id")]
                )),
                "values": [previous.get("claim_value"), claim_value],
            })
        unique: list[dict[str, Any]] = []
        keys: set[str] = set()
        for record in records:
            key = str(record.get("claim_key") or record.get("reason"))
            if key in keys:
                continue
            keys.add(key)
            unique.append(record)
        self._contradictions = unique[:8]

    def _context_for_provider(self) -> dict[str, Any]:
        return {
            "anchor": self.anchor,
            "anchor_hash": self._anchor_hash,
            "round": self._round,
            "working_evidence": [_public_evidence(item) for item in self._evidence],
            "allowed_inspection_paths": list(self._anchor.get("allowed_inspection_paths", [])),
            "bounds": {
                "max_rounds": self.max_rounds,
                "max_requests_per_round": self.max_requests_per_round,
                "max_evidence_items": self.max_evidence_items,
                "max_evidence_chars": self.max_evidence_chars,
                "max_semantic_resolutions": MAX_CONTEXT_SEMANTIC_RESOLUTIONS,
            },
        }

    def _public_semantic_resolutions(self) -> list[dict[str, Any]]:
        return [_copy(item) for item in list(self._semantic_resolutions.values())[-MAX_CONTEXT_SEMANTIC_RESOLUTIONS:]]

    def _pending_semantic_resolutions(self) -> list[dict[str, Any]]:
        return [
            item for item in self._semantic_resolutions.values()
            if item.get("resolution_status") in {"partial", "unresolved", "conflicting"}
        ]

    def _semantic_followup_requests(self) -> list[dict[str, str]]:
        requests: list[dict[str, str]] = []
        for resolution in self._pending_semantic_resolutions()[: self.max_requests_per_round]:
            status = str(resolution.get("resolution_status") or "unresolved")
            original = _normalize_kind(
                resolution.get("gate_request_kind") or resolution.get("request_kind")
            )
            if status == "conflicting" or original in {
                "contract", "authoritative_contract", "interface", "definition",
                "schema", "type_or_schema",
            }:
                kind = "authoritative_contract"
            elif original in {"tests", "test_expectation"}:
                kind = "tests"
            elif original in {"callers", "consumers", "caller_expectation", "return_expectation"}:
                kind = "callers"
            elif original:
                kind = original
            else:
                kind = "authoritative_contract"
            semantic_kind = _text(
                resolution.get("request_kind") or resolution.get("gate_request_kind") or kind,
                80,
            )
            target = _text(resolution.get("target"), 180)
            requests.append({
                "kind": kind,
                "target": target,
                "why": _text(
                    f"Need authoritative {semantic_kind} evidence for {target}; "
                    f"the semantic resolver marked the prior bundle {status}. "
                    "Do not infer or reconcile the missing fact before mutation.",
                    MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS,
                ),
            })
        return requests

    def _authoritative_conflict_requests(self) -> list[dict[str, str]]:
        requests = []
        for conflict in self._contradictions[: self.max_requests_per_round]:
            target = ""
            evidence_ids = set(conflict.get("evidence_ids", []) or [])
            if evidence_ids:
                target = next(
                    (
                        _text(item.get("symbol") or item.get("target"), 180)
                        for item in self._evidence
                        if item.get("evidence_id") in evidence_ids
                        and (item.get("symbol") or item.get("target"))
                    ),
                    "",
                )
            if not target:
                claim_key = _text(conflict.get("claim_key"), 180)
                target = re.sub(r"\.(?:return_expectation|return_shape)$", "", claim_key)
            target = target or "the conflicting semantic claim"
            requests.append({
                "kind": "authoritative_contract",
                "target": target,
                "why": _text(
                    "Need an authoritative contract, caller, or test to resolve conflicting evidence before choosing a mutation.",
                    MAX_CONTEXT_EVIDENCE_PURPOSE_CHARS,
                ),
            })
        return requests

    def _failure(self, *, reason: str, errors: Iterable[str] = ()) -> dict[str, Any]:
        self._state = CONTEXT_INSUFFICIENT
        self._context_status = CONTEXT_STATUS_INSUFFICIENT
        self._mutation_allowed = False
        self._failure_code = CONTEXT_INSUFFICIENT_FAILURE
        self._reason = _text(reason, MAX_CONTEXT_REASON_CHARS)
        return self._result(
            reason=self._reason,
            errors=list(errors),
            final=True,
            requires_re_evaluation=False,
        )

    def _result(
        self,
        *,
        reason: str | None = None,
        errors: Iterable[str] = (),
        final: bool = False,
        requires_re_evaluation: bool = False,
        new_evidence: Iterable[Mapping[str, Any]] | None = None,
        needed_evidence: Iterable[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        public_evidence = [_public_evidence(item) for item in list(new_evidence or [])]
        while (
            len(public_evidence) > 1
            and len(json.dumps(public_evidence, ensure_ascii=False, default=str)) > self.max_evidence_chars
        ):
            public_evidence.pop(0)
        return {
            "context_status": self._context_status,
            "lifecycle_state": self._state,
            "mutation_allowed": self.mutation_allowed,
            "round": self._round,
            "max_rounds": self.max_rounds,
            "request_count": self._request_count,
            "max_requests_per_round": self.max_requests_per_round,
            "reason": _text(reason if reason is not None else self._reason, MAX_CONTEXT_REASON_CHARS),
            "needed_evidence": self._public_requests(needed_evidence or []),
            "evidence": public_evidence,
            "working_evidence_count": len(self._evidence),
            "working_evidence_chars": self._serialized_evidence_chars(),
            "working_evidence_limit": self.max_evidence_chars,
            "evidence_items_dropped": self._dropped_evidence,
            "contradictions": _copy(self._contradictions),
            "semantic_resolutions": self._public_semantic_resolutions(),
            "errors": [_text(item, MAX_CONTEXT_REASON_CHARS) for item in errors][:12],
            "failure_code": self._failure_code,
            "final": bool(final),
            "requires_re_evaluation": bool(requires_re_evaluation),
            "anchor_hash": self._anchor_hash,
        }

    def _complete_round(self, requests: list[dict[str, str]]) -> dict[str, Any]:
        if self._round >= self.max_rounds:
            return self._failure(
                reason=(
                    f"context completion budget exhausted after {self.max_rounds} round(s); "
                    "the Worker did not establish sufficient semantic evidence"
                ),
            )
        self._round += 1
        self._request_count += len(requests)
        self._state = REQUEST_EVIDENCE
        self._context_status = CONTEXT_STATUS_INSUFFICIENT
        self._mutation_allowed = False
        self._last_evidence = []
        provider_errors: list[str] = []
        for request in requests:
            try:
                raw = _invoke_provider(self.provider, request, self._context_for_provider())
            except Exception as exc:  # provider failures remain bounded evidence failures
                raw = None
                provider_errors.append(f"{request['kind']}:{request['target']}: {exc}")
            items = []
            for index, item in enumerate(_provider_items(raw), 1):
                normalized = _normalize_provider_evidence(item, request, index)
                if normalized is not None:
                    items.append(normalized)
            resolution = _provider_resolution(raw, request, items)
            if resolution is None and raw is None:
                # A provider failure/empty null response is not evidence of
                # sufficiency. Keep the same bounded semantic record used by
                # the resolver so a Worker cannot promote an unavailable
                # completion by claiming it is sufficient.
                resolution = {
                    "request_kind": request.get("kind", ""),
                    "gate_request_kind": request.get("kind", ""),
                    "target": request.get("target", ""),
                    "resolution_status": "unresolved",
                    "facts_established": [],
                    "conflicts": [],
                    "evidence_ids": [],
                    "candidates_considered": 0,
                    "candidate_files_considered": 0,
                    "relationship_hops": 0,
                }
            if resolution is not None:
                resolution_kind = _semantic_request_key_kind(
                    resolution.get("request_kind")
                    or resolution.get("gate_request_kind")
                    or request.get("kind")
                )
                request_key = f"{resolution_kind}:{resolution.get('target', '')}".casefold()
                resolution["request_key"] = request_key
                self._semantic_resolutions.pop(request_key, None)
                self._semantic_resolutions[request_key] = resolution
                while len(self._semantic_resolutions) > MAX_CONTEXT_SEMANTIC_RESOLUTIONS:
                    self._semantic_resolutions.pop(next(iter(self._semantic_resolutions)))
            if not items and raw is None and not callable(self.provider):
                provider_errors.append(
                    f"{request['kind']}:{request['target']}: {CONTEXT_EVIDENCE_PROVIDER_UNAVAILABLE}"
                )
            self._evidence.extend(items)
            self._last_evidence.extend(items)
            self._history.append({
                "round": self._round,
                "kind": request["kind"],
                "target": request["target"],
                "why": request["why"],
                "evidence_ids": [item.get("evidence_id") for item in items],
                "evidence_count": len(items),
                "resolution_status": resolution.get("resolution_status") if resolution else None,
                "resolution_facts_count": len(resolution.get("facts_established", [])) if resolution else 0,
            })
        self._trim_evidence()
        self._refresh_contradictions()
        self._reason = _text(
            "Targeted evidence returned; re-evaluate context sufficiency before any mutation."
            + (" Provider did not resolve every request." if provider_errors else ""),
            MAX_CONTEXT_REASON_CHARS,
        )
        return self._result(
            reason=self._reason,
            errors=provider_errors,
            final=False,
            requires_re_evaluation=True,
            new_evidence=self._last_evidence,
            needed_evidence=requests,
        )

    def evaluate(
        self,
        decision: Mapping[str, Any] | None,
        *,
        evidence_provider: Callable[..., Any] | None = None,
    ) -> dict[str, Any]:
        """Apply one Worker decision and, if needed, complete one evidence round."""
        checked = validate_sufficiency_decision(decision)
        if not checked.get("valid"):
            self._state = PREPARING_CONTEXT
            self._context_status = CONTEXT_STATUS_INSUFFICIENT
            self._mutation_allowed = False
            self._failure_code = None
            self._reason = "The sufficiency decision was invalid; submit the bounded structured decision again."
            return self._result(reason=self._reason, errors=checked.get("errors", []), final=False)
        value = checked["decision"]
        self._failure_code = None
        self._reason = value.get("reason", "")
        self._last_evidence = []
        if evidence_provider is not None:
            self.provider = evidence_provider
        if value["context_status"] == CONTEXT_STATUS_SUFFICIENT:
            self._refresh_contradictions()
            if self._contradictions:
                requests = self._authoritative_conflict_requests()
                if not requests:
                    return self._failure(
                        reason="contradictory evidence remains and no authoritative resolution is available",
                    )
                result = self._complete_round(requests)
                result["reason"] = (
                    "Context cannot be marked sufficient while evidence conflicts; "
                    "requesting authoritative evidence."
                )
                return result
            pending_semantic = self._pending_semantic_resolutions()
            if pending_semantic:
                requests = self._semantic_followup_requests()
                if not requests:
                    return self._failure(
                        reason=(
                            "semantic evidence remains partial or conflicting and no "
                            "bounded authoritative follow-up can resolve it"
                        ),
                    )
                result = self._complete_round(requests)
                result["reason"] = (
                    "Context cannot be marked sufficient while semantic evidence is "
                    "partial, unresolved, or conflicting; requesting a targeted "
                    "authoritative completion."
                )
                return result
            self._context_status = CONTEXT_STATUS_SUFFICIENT
            self._state = MUTATION_ALLOWED
            self._mutation_allowed = True
            self._reason = _text(value.get("reason") or "bounded context is sufficient", MAX_CONTEXT_REASON_CHARS)
            self._history.append({
                "round": self._round,
                "decision": CONTEXT_STATUS_SUFFICIENT,
                "reason": self._reason,
            })
            return self._result(
                reason=self._reason,
                final=True,
                requires_re_evaluation=False,
            )
        requests = value["needed_evidence"]
        if self._round >= self.max_rounds:
            return self._failure(
                reason=(
                    f"context completion budget exhausted after {self.max_rounds} round(s); "
                    "requested semantic evidence remains unresolved"
                ),
            )
        return self._complete_round(requests)

    # These compact read-only projections are useful to the controller and
    # tests without exposing internal mutable fields to the Worker.
    def snapshot(self) -> dict[str, Any]:
        return {
            "state": self._state,
            "context_status": self._context_status,
            "mutation_allowed": self.mutation_allowed,
            "round": self._round,
            "request_count": self._request_count,
            "max_rounds": self.max_rounds,
            "max_requests_per_round": self.max_requests_per_round,
            "anchor": self.anchor,
            "anchor_hash": self._anchor_hash,
            "working_evidence": [_public_evidence(item) for item in self._evidence],
            "working_evidence_count": len(self._evidence),
            "working_evidence_chars": self._serialized_evidence_chars(),
            "working_evidence_limit": self.max_evidence_chars,
            "evidence_items_dropped": self._dropped_evidence,
            "contradictions": _copy(self._contradictions),
            "semantic_resolutions": self._public_semantic_resolutions(),
            "history": _copy(self._history[-self.max_rounds - 1:]),
            "failure_code": self._failure_code,
        }


def mutation_block_reason(gate: ContextSufficiencyGate | None) -> str | None:
    """Return a compact runtime error when a Worker mutates too early."""
    if gate is None or gate.mutation_allowed:
        return None
    if gate.snapshot().get("failure_code") == CONTEXT_INSUFFICIENT_FAILURE:
        return (
            f"error: {CONTEXT_INSUFFICIENT_FAILURE}; Worker mutation is blocked because "
            "the bounded context-sufficiency gate did not pass"
        )
    return (
        "error: CONTEXT_SUFFICIENCY_REQUIRED; Worker must submit a structured "
        "context_sufficiency_check before using a mutating tool"
    )


def feedback_for_result(result: Mapping[str, Any] | None) -> str:
    """Render a small model-facing feedback message without source blobs."""
    value = result if isinstance(result, Mapping) else {}
    status = value.get("context_status")
    if value.get("mutation_allowed"):
        return "CONTEXT_SUFFICIENT: the bounded context gate passed. Mutation tools are now authorized for the current task."
    if value.get("failure_code"):
        return (
            f"{value.get('failure_code')}: stop before mutation. "
            f"{_text(value.get('reason'), MAX_CONTEXT_REASON_CHARS)}"
        )
    if status == CONTEXT_STATUS_INSUFFICIENT:
        requests = value.get("needed_evidence", []) or []
        evidence = value.get("evidence", []) or []
        semantic = value.get("semantic_resolutions", []) or []
        pending = [
            item for item in semantic
            if isinstance(item, Mapping)
            and item.get("resolution_status") in {"partial", "unresolved", "conflicting"}
        ]
        semantic_note = (
            f" semantic_pending={len(pending)}."
            if semantic else ""
        )
        return _text(
            "CONTEXT_INSUFFICIENT: targeted evidence was requested. Re-evaluate sufficiency now; "
            "do not mutate until CONTEXT_SUFFICIENT is returned. "
            f"round={value.get('round')}; requests={len(requests)}; returned_evidence={len(evidence)}."
            + semantic_note,
            900,
        )
    return "CONTEXT_SUFFICIENCY_REQUIRED: submit the structured context_sufficiency_check before mutation."


__all__ = [name for name in globals() if not name.startswith("_")]
