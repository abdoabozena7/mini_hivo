"""Provider-free V26 autonomous-recovery foundations.

This module is deliberately a narrow authority boundary.  It converts
deterministic execution evidence into a bounded recovery decision and a
fresh, clean mission.  It does not call a model, mutate the user's
workspace, create approval, or implement a production-code fix.

The one dispatch function is an injected architecture seam.  A later stage
may connect the same weak Worker capability to it; V26 only proves that the
seam is reachable and that its authority and attempt accounting are bounded.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import json
import os
import re
import shutil
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Callable, Iterable

from hivo import execution_invariants
from hivo import integration_gate
from hivo import promotion
from hivo import reentry
from hivo import verification_routing
from hivo.requirements import freeze


SCHEMA_VERSION = "V26-RECOVERY-FOUNDATION-1"
RECOVERY_FAILURE_ENVELOPE = "RecoveryFailureEnvelope"
RECOVERY_FAILURE_EVIDENCE = "RecoveryFailureEvidence"
VERIFICATION_FAILURE = "VERIFICATION_FAILURE"
WORKER_EXECUTION_FAILURE = "WORKER_EXECUTION_FAILURE"
RECOVERY_AUTHORITY_DELTA = "RecoveryAuthorityDelta"
AUTHORIZED_EXECUTION_LINEAGE = "AuthorizedExecutionLineage"
APPROVED_RECOVERY_AUTHORIZATION = "ApprovedRecoveryAuthorization"
RECOVERY_MISSION = "RecoveryMission"
RECOVERY_WORKER_PACKET = "RecoveryWorkerPacket"

HARNESS_RECOVERABLE = "HARNESS_RECOVERABLE"
WORKER_RECOVERABLE = "WORKER_RECOVERABLE"
AUTHORITY_CHANGE_REQUIRED = "AUTHORITY_CHANGE_REQUIRED"
CAPABILITY_FLOOR = "CAPABILITY_FLOOR"
NON_RECOVERABLE_ARCHITECTURE_FAILURE = "NON_RECOVERABLE_ARCHITECTURE_FAILURE"
RECOVERY_CLASSIFICATION_UNCERTAIN = "RECOVERY_CLASSIFICATION_UNCERTAIN"

# V26.5 makes the source of a failed execution an explicit tagged union.
# These blockers are reporting/classification states, not new authority and
# are intentionally separate from the existing recoverable classes.
PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER = "PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER"
PRE_VERIFICATION_RECOVERY_BLOCKED_HARNESS = "PRE_VERIFICATION_RECOVERY_BLOCKED_HARNESS"
PRE_VERIFICATION_RECOVERY_BLOCKED_AUTHORITY = "PRE_VERIFICATION_RECOVERY_BLOCKED_AUTHORITY"
PRE_VERIFICATION_RECOVERY_BLOCKED_DRIFT = "PRE_VERIFICATION_RECOVERY_BLOCKED_DRIFT"
PRE_VERIFICATION_RECOVERY_BLOCKED_NO_LEGAL_SPACE = "PRE_VERIFICATION_RECOVERY_BLOCKED_NO_LEGAL_SPACE"
PRE_VERIFICATION_RECOVERY_BLOCKED_BUDGET = "PRE_VERIFICATION_RECOVERY_BLOCKED_BUDGET"
PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE = "PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE"
PRE_VERIFICATION_RECOVERY_EVIDENCE_INCOMPLETE = "PRE_VERIFICATION_RECOVERY_EVIDENCE_INCOMPLETE"
RECOVERY_REQUIRED_BUT_NOT_DISPATCHABLE = "RECOVERY_REQUIRED_BUT_NOT_DISPATCHABLE"
RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN = "RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN"
RECOVERY_REQUIRED_CLASSIFIED = "RECOVERY_REQUIRED_CLASSIFIED"
RECOVERY_REQUIRED_AUTHORITY_CHANGE = "RECOVERY_REQUIRED_AUTHORITY_CHANGE"
RECOVERY_REQUIRED_DISPATCHED = "RECOVERY_REQUIRED_DISPATCHED"
RECOVERY_COMPLETED = "RECOVERY_COMPLETED"

RECOVERY_AUTHORIZATION_READY = "RECOVERY_AUTHORIZATION_READY"
RECOVERY_AUTHORIZATION_BLOCKED = "RECOVERY_AUTHORIZATION_BLOCKED"
RECOVERY_MISSION_READY = "RECOVERY_MISSION_READY"
RECOVERY_MISSION_BLOCKED = "RECOVERY_MISSION_BLOCKED"
RECOVERY_ELIGIBLE = "RECOVERY_ELIGIBLE"
RECOVERY_BLOCKED = "RECOVERY_BLOCKED"
RECOVERY_DISPATCHED = "RECOVERY_DISPATCHED"
RECOVERY_DISPATCH_BLOCKED = "RECOVERY_DISPATCH_BLOCKED"
RECOVERY_DISPATCH_CALLBACK_REQUIRED = "RECOVERY_DISPATCH_CALLBACK_REQUIRED"
RECOVERY_DISPATCH_ALREADY_USED = "RECOVERY_DISPATCH_ALREADY_USED"
RECOVERY_CALLBACK_FAILED = "RECOVERY_CALLBACK_FAILED"
RECOVERY_BUDGET_EXHAUSTED = "RECOVERY_BUDGET_EXHAUSTED"
RECOVERY_ATTEMPT_READY = "RECOVERY_ATTEMPT_READY"
AUTHORIZED_EXECUTION_DESCENDANT = "AUTHORIZED_EXECUTION_DESCENDANT"
INVALID_AUTHORIZED_EXECUTION_DESCENDANT = "INVALID_AUTHORIZED_EXECUTION_DESCENDANT"
EXTERNAL_UNAUTHORIZED_DRIFT = "EXTERNAL_UNAUTHORIZED_DRIFT"

USER_REAPPROVAL_REQUIRED = "USER_REAPPROVAL_REQUIRED"

MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS = 1
RECOVERY_WORKER_PACKET_MAX_CHARS = 4200
MAX_RECOVERY_WORKER_PACKET_CHARS = RECOVERY_WORKER_PACKET_MAX_CHARS

# V26.3 is deliberately narrower than the older adaptive planning/search
# machinery in ``mini.py``.  These constants describe one recovery Worker
# changing its local mutation mechanism once after deterministic stagnation.
MAX_RECOVERY_STRATEGY_SWITCHES = 1
RECOVERY_STRATEGY_FAILURE_PATTERN = "RecoveryStrategyFailurePattern"
RECOVERY_MUTATION_STRATEGY = "RecoveryMutationStrategy"
RECOVERY_STRATEGY_DIVERSIFICATION_DECISION = "RecoveryStrategyDiversificationDecision"
RECOVERY_STRATEGY_EPOCH_START = "RecoveryStrategyEpochStart"
RECOVERY_STRATEGY_EPOCH_TERMINAL = "RecoveryStrategyEpochTerminal"
RECOVERY_STRATEGY_SEARCH_SUMMARY = "RecoveryStrategySearchSummary"

SYNTAX_INVALID_MUTATION = "SYNTAX_INVALID_MUTATION"
RECOVERY_STRATEGY_STAGNATION_DETECTED = "RECOVERY_STRATEGY_STAGNATION_DETECTED"
NO_SWITCH_REQUIRED = "NO_SWITCH_REQUIRED"
STRATEGY_SWITCH_READY = "STRATEGY_SWITCH_READY"
STRATEGY_SWITCH_UNAVAILABLE = "STRATEGY_SWITCH_UNAVAILABLE"
STRATEGY_SWITCH_BLOCKED_AUTHORITY = "STRATEGY_SWITCH_BLOCKED_AUTHORITY"
STRATEGY_SWITCH_BUDGET_EXHAUSTED = "STRATEGY_SWITCH_BUDGET_EXHAUSTED"
STRATEGY_SWITCH_NOT_EVALUABLE = "STRATEGY_SWITCH_NOT_EVALUABLE"
RECOVERY_STRATEGY_SEARCH_EXHAUSTED = "RECOVERY_STRATEGY_SEARCH_EXHAUSTED"
RECOVERY_STRATEGY_COMMITTED = "RECOVERY_STRATEGY_COMMITTED"
RECOVERY_STRATEGY_EPOCH_0 = 0
RECOVERY_STRATEGY_EPOCH_1 = 1
RECOVERY_STRATEGY_STAGNATION_THRESHOLD = 2

# V26.4 keeps all adaptation local to one recovery Worker lifecycle.  These
# bounds are deliberately independent from the V26.3 strategy-switch budget.
RECOVERY_V264_SCHEMA_VERSION = "V26.4-RECOVERY-ADAPTATION-1"
RECOVERY_V265_SCHEMA_VERSION = "V26.5-RECOVERY-FAILURE-EVIDENCE-1"
MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS = 1
MAX_RECOVERY_EPOCH_REANCHORS = 1
MAX_RECOVERY_COMPLETION_REPAIRS = 1

RECOVERY_TOOL_CONTRACT_FAILURE_PATTERN = "RecoveryToolContractFailurePattern"
RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENT = "RecoveryToolContractGuidanceEvent"
RECOVERY_EPOCH_REANCHOR = "RecoveryEpochReanchor"
RECOVERY_EPOCH_REANCHOR_EVENT = "RecoveryEpochReanchorEvent"
RECOVERY_COMPLETION_CONTRACT_REPAIR = "RecoveryCompletionContractRepair"
RECOVERY_COMPLETION_REPAIR_EVENT = "RecoveryCompletionRepairEvent"

# V26.6 adds one independent, execution-local response to a different
# failure predicate: the Worker keeps inspecting the unchanged subject but
# never invokes any currently legal behavior-changing mutation mechanism.
# This is deliberately not a strategy epoch transition and does not consume
# any V26.3/V26.4 adaptation budget.
RECOVERY_V266_SCHEMA_VERSION = "V26.6-RECOVERY-NO-MUTATION-SEARCH-1"
RECOVERY_NO_MUTATION_SEARCH_INTERACTION = "RecoveryNoMutationSearchInteraction"
RECOVERY_NO_MUTATION_SEARCH_PATTERN = "RecoveryNoMutationSearchPattern"
RECOVERY_MUTATION_PATH_REORIENTATION = "RecoveryMutationPathReorientation"
RECOVERY_MUTATION_PATH_REORIENTATION_EVENT = "RecoveryMutationPathReorientationEvent"
RECOVERY_NO_MUTATION_SEARCH_STAGNATION = "RECOVERY_NO_MUTATION_SEARCH_STAGNATION"
RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED = "RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED"
RECOVERY_NO_MUTATION_SEARCH_RESET = "RECOVERY_NO_MUTATION_SEARCH_RESET"
RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED = "RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED"
RECOVERY_NO_MUTATION_SEARCH_BLOCKED = "RECOVERY_NO_MUTATION_SEARCH_BLOCKED"
RECOVERY_NO_MUTATION_SEARCH_PROGRESS = "RECOVERY_NO_MUTATION_SEARCH_PROGRESS"
MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION = 4
MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS = 1

# The current Worker loop spends one normal step on the continuation that
# follows a reorientation and needs one further step to select a mutation.
# Completion/handoff is not an additional mutation authority or provider
# budget; it remains owned by the existing completion/V25.6 lifecycle.  The
# smallest deterministic floor that preserves those opportunities is 3.
MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION = 3
RECOVERY_MUTATION_PATH_REORIENTATION_SAFETY_FLOOR = (
    MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION
)
MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS = (
    MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION
)

EDIT_EXACT_MATCH_AMBIGUOUS = "EDIT_EXACT_MATCH_AMBIGUOUS"
SUPPRESSED_STRATEGY_TOOL_REQUESTED = "SUPPRESSED_STRATEGY_TOOL_REQUESTED"
TOOL_CONTRACT_STAGNATION_DETECTED = "TOOL_CONTRACT_STAGNATION_DETECTED"
TOOL_CONTRACT_FEEDBACK_ONLY = "TOOL_CONTRACT_FEEDBACK_ONLY"
TOOL_CONTRACT_GUIDANCE_BUDGET_EXHAUSTED = "TOOL_CONTRACT_GUIDANCE_BUDGET_EXHAUSTED"
STRATEGY_EPOCH_CONTEXT_STALE_OR_IGNORED = "STRATEGY_EPOCH_CONTEXT_STALE_OR_IGNORED"
RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED = "RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED"
COMPLETION_CONTRACT_REPAIR_READY = "COMPLETION_CONTRACT_REPAIR_READY"
RECOVERY_COMPLETION_REPAIR_BUDGET_EXHAUSTED = "RECOVERY_COMPLETION_REPAIR_BUDGET_EXHAUSTED"
WORKER_OUTPUT_INVALID = "WORKER_OUTPUT_INVALID"
WORKER_NO_APPROVED_MUTATION = "WORKER_NO_APPROVED_MUTATION"

LIVE3_APPROVAL_ID = "APPROVAL-21A7FCFDBFB22CB9"
LIVE3_APPROVAL_RECEIPT_HASH = "b94af87ad1847cd277a5f671dedcd276827c137219504cd9f3b0361360f194a3"
LIVE3_PLAN_ID = "PLAN-5E9D01B255C2"
LIVE3_PLAN_HASH = "5e9d01b255c23753eafa3fa76160b91b8b92486506580ffaf11f582b9522115a"
LIVE3_VERIFICATION_DIGEST = "98a8ed7513a7f3da21a3e5062712890ad2f499c390070e7cbaa3f57b2b655b51"
LIVE3_COVERAGE_HASH = "6bab7c0383a56446d00c6681675366b020a17f524d5bb46b9349ff9c03a85402"
LIVE3_ORACLE_HASH = "f1ccdc309c31709f3bc589b184a7f3d252de408f0b8da2e2ad908109f079b140"
LIVE3_INVARIANT_HASH = "257c9d474539fdc74cfb7a6ca088bdf3431013f8e844af45c6d9e95bb7f73424"
LIVE3_BRAIN_HASH = "8eac670a83eeddb30528ebd3ad5032dabc6f6d1a3fb97b65b4600964b1b434bb"
LIVE3_BASELINE_SUBJECT_HASH = "c00fc37444dc64f0f6aecbcd57a5972ddfb9fed495f2ce2ba39be7db1150bbac"
LIVE3_FAILED_SUBJECT_HASH = "43b44d673d0aa49d7a17c9c617e83f7086bc530e0b14740c01d64f03c8e01e0d"

_PRIVATE_KEYS = frozenset({
    "messages", "thinking", "chain_of_thought", "reasoning", "transcript",
    "raw_worker_output", "worker_output", "model_output", "raw_output",
    "raw_worker_transcript", "prompt_history", "generation_history",
    "conversation", "chat_history", "worker_messages", "provider_messages",
})
_PROSE_KEYS = frozenset({"summary", "explanation", "commentary", "narrative"})
_KNOWN_HARNESS_CODES = frozenset({
    "RUNNER_INVOCATION_FAILURE",
    "RUNNER_MATERIALIZATION_FAILURE",
    "TEMPORARY_PATH_FAILURE",
    "TOOL_INVOCATION_FAILURE",
    "PROVIDER_TRANSPORT_RECOVERABLE",
    "HARNESS_FAILURE",
})
_DIMENSIONS = (
    "new_requirements",
    "removed_requirements",
    "new_mutation_paths",
    "removed_mutation_paths",
    "dnt_changes",
    "ownership_changes",
    "interface_semantic_changes",
    "dependency_changes",
    "verification_authority_changes",
    "oracle_changes",
    "invariant_changes",
    "approved_behavior_changes",
)


class _FrozenRecord(dict):
    """JSON-shaped immutable record with ordinary mapping access."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("V26 recovery records are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other: Any) -> Any:
        self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


class RecoveryFailureEnvelope(_FrozenRecord):
    """Immutable deterministic evidence for one failed execution."""


class RecoveryFailureEvidence(_FrozenRecord):
    """Immutable tagged evidence describing the source of a failure."""


class VerificationFailureEvidence(RecoveryFailureEvidence):
    """A failure established by the V25.6 verification authority."""


class WorkerExecutionFailureEvidence(RecoveryFailureEvidence):
    """A Worker lifecycle failure before a verified completion."""


class RecoveryAuthorityDelta(_FrozenRecord):
    """Immutable comparison between approved authority and recovery needs."""


class AuthorizedExecutionLineage(_FrozenRecord):
    """Immutable proof that a failed subject descends from approved execution."""


class ApprovedRecoveryAuthorization(_FrozenRecord):
    """Immutable continuation authority derived from unchanged user authority."""


class RecoveryMission(_FrozenRecord):
    """Fresh bounded continuation mission, not a new plan."""


class RecoveryWorkerPacket(_FrozenRecord):
    """Fresh bounded Worker-facing context projection."""


class RecoveryStrategyFailurePattern(_FrozenRecord):
    """Immutable evidence for one same-strategy mutation-failure sequence."""


class RecoveryMutationStrategy(_FrozenRecord):
    """Immutable local mutation-tool projection for one recovery epoch."""


class RecoveryStrategyDiversificationDecision(_FrozenRecord):
    """Immutable decision to keep or switch a recovery mutation strategy."""


class RecoveryToolContractFailurePattern(_FrozenRecord):
    """Immutable evidence for one deterministic tool-contract failure run."""


class RecoveryToolContractGuidanceEvent(_FrozenRecord):
    """Immutable, bounded model-visible tool-contract guidance."""


class RecoveryEpochReanchor(_FrozenRecord):
    """Immutable same-Worker re-anchoring of the current strategy epoch."""


class RecoveryEpochReanchorEvent(RecoveryEpochReanchor):
    """Compatibility spelling for the canonical re-anchor event."""


class RecoveryCompletionContractRepair(_FrozenRecord):
    """Immutable one-shot completion-contract repair opportunity."""


class RecoveryCompletionRepairEvent(RecoveryCompletionContractRepair):
    """Compatibility spelling for the canonical completion repair event."""


class RecoveryNoMutationSearchPattern(_FrozenRecord):
    """Immutable evidence for one bounded no-mutation search window."""


class RecoveryNoMutationSearchInteraction(_FrozenRecord):
    """Immutable projection of one counted Worker search interaction."""


class RecoveryMutationPathReorientation(_FrozenRecord):
    """Immutable same-Worker, execution-local mutation-path reorientation."""


class RecoveryMutationPathReorientationEvent(RecoveryMutationPathReorientation):
    """Compatibility spelling for the canonical V26.6 reorientation event."""


def canonical_hash(value: Any) -> str:
    """Return the compact deterministic SHA-256 used by V26 artifacts."""
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


deterministic_hash = canonical_hash


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _freeze_record(record_type: type[_FrozenRecord], value: dict[str, Any]) -> _FrozenRecord:
    result = record_type()
    dict.__init__(result, ((key, freeze(_copy(item))) for key, item in value.items()))
    return result


def _text(value: Any, limit: int = 900) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(0, limit - 3)] + "..."


def _path(value: Any) -> str:
    text = str(value or "").replace("\\", "/").strip()
    while text.startswith("./"):
        text = text[2:]
    return text.rstrip("/")


def _list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _unique_strings(value: Any, *, paths: bool = False, limit: int = 120, chars: int = 300) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in _list(value):
        item = _path(item) if paths else _text(item, chars)
        if item and item.casefold() not in seen:
            result.append(item)
            seen.add(item.casefold())
        if len(result) >= limit:
            break
    return result


def _get(value: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(value, dict):
        return default
    for key in keys:
        if key in value and value.get(key) not in (None, ""):
            return value.get(key)
    return default


def _without(value: Any, *keys: str) -> dict[str, Any]:
    result = _copy(value) if isinstance(value, dict) else {}
    for key in keys:
        result.pop(key, None)
    return result


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def _safe_int(value: Any, default: int = -1) -> int:
    """Parse bounded-record integers without allowing malformed evidence to raise."""
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


# ---------------------------------------------------------------------------
# V26.5 explicit failure-source contract
# ---------------------------------------------------------------------------

_FAILURE_EVIDENCE_COMMON_FIELDS = (
    "schema_version", "artifact_type", "failure_source", "source_variant",
    "execution_id", "worker_result_status", "subject_before_hash",
    "subject_after_hash", "current_subject_hash", "commit_count", "commit",
    "filesystem_changed", "worker_prose_authority",
)

_WORKER_EXECUTION_EVIDENCE_FIELDS = (
    "worker_terminal_code", "failure_detail", "actual_worker_lifecycle", "worker_lifecycle_count",
    "provider_health", "provider_handoff_valid", "execution_related",
    "verified_successful_completion", "completed", "completion_attempted",
    "completion_status", "v25_6_executed", "subject_known",
    "subject_unchanged", "lineage_status", "unknown_manual_drift", "scope_valid",
    "dnt_valid", "plan_unchanged", "approval_unchanged", "brain_valid",
    "brain_unchanged", "promoted", "authority_delta_empty",
    "legal_solution_space_available", "full_verification_universe_available",
    "recovery_budget_available", "provider_failure", "harness_failure",
    "v25_5_authority_valid", "approved_mutation_count", "changed_paths",
    "verification_obligation_ids", "coverage_status", "missing_coverage_ids",
    "plan_id", "plan_hash", "approval_id", "approval_receipt_hash",
    "execution_invariant_set_hash", "promotion_status", "lineage_evidence_ref",
)

_VERIFICATION_EVIDENCE_FIELDS = (
    "authority_id", "oracle_id", "oracle_hash", "failed_check", "detail",
    "verification_status", "verification_executed", "v25_6_executed",
    "verification_receipt_identity", "verification_digest", "coverage_hash",
    "plan_id", "plan_hash", "approval_id", "approval_receipt_hash",
    "execution_invariant_set_hash",
)

_WORKER_EVIDENCE_MIXING_KEYS = frozenset({
    "authority_id", "oracle_id", "oracle_hash", "failed_check", "detail",
    "failed_verification", "failed_verification_authority_ids",
    "verification_receipt", "verification_receipts", "verification_evidence",
    "verified_child_receipt", "execution_verification_closure",
    "execution_verification_closure_hash", "failed_verification_closure_hash",
})

_VERIFICATION_EVIDENCE_MIXING_KEYS = frozenset({
    "worker_terminal_code", "actual_worker_lifecycle", "provider_health",
    "provider_handoff_valid", "execution_related", "legal_solution_space_available",
})


def _pick(value: Any, source: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Pick an explicit argument or an alias without treating False as absent."""
    if value is not None:
        return value
    for key in keys:
        if key in source:
            return source[key]
    return default


def _failure_evidence_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_without(value, "canonical_hash", "failure_evidence_hash"))


def _failure_evidence_source(value: Any) -> dict[str, Any] | None:
    """Extract only an explicit V26.5 failure variant from a source object."""
    if not isinstance(value, dict):
        return None
    if value.get("artifact_type") == RECOVERY_FAILURE_EVIDENCE:
        return _copy(value)
    nested = value.get("failure_evidence")
    if isinstance(nested, dict) and (
        nested.get("artifact_type") == RECOVERY_FAILURE_EVIDENCE
        or nested.get("failure_source") in {VERIFICATION_FAILURE, WORKER_EXECUTION_FAILURE}
    ):
        return _copy(nested)
    if value.get("failure_source") in {VERIFICATION_FAILURE, WORKER_EXECUTION_FAILURE}:
        return _copy(value)
    return None


def build_verification_failure_evidence(
    execution_id: str | dict[str, Any],
    *,
    authority_id: str | None = None,
    oracle_id: str | None = None,
    oracle_hash: str | None = None,
    failed_check: str | None = None,
    detail: str | None = None,
    verification_status: str = "FAIL",
    subject_before_hash: str | None = None,
    subject_after_hash: str | None = None,
    current_subject_hash: str | None = None,
    worker_result_status: str = "failed",
    verification_receipt_identity: str | None = None,
    verification_digest: str | None = None,
    coverage_hash: str | None = None,
    plan_id: str | None = None,
    plan_hash: str | None = None,
    approval_id: str | None = None,
    approval_receipt_hash: str | None = None,
    execution_invariant_set_hash: str | None = None,
    **kwargs: Any,
) -> VerificationFailureEvidence:
    """Build the verification-backed member of the V26.5 failure union.

    This projection contains only deterministic verification facts.  It is
    kept separate from the pre-verification Worker-execution member so a
    missing V25.6 receipt can never be interpreted as a failed receipt.
    """
    source = _copy(execution_id) if isinstance(execution_id, dict) else _copy(kwargs)
    execution = (
        _text(source.get("execution_id"), 180)
        if isinstance(execution_id, dict)
        else _text(execution_id, 180)
    )
    authority = _text(_pick(authority_id, source, "verification_id", default="VERIFICATION-004"), 180)
    oracle = _text(_pick(oracle_id, source, default="ORACLE-PAUSE-INDICATOR"), 180)
    oracle_digest = _text(
        _pick(oracle_hash, source, "oracle_digest", default=LIVE3_ORACLE_HASH),
        128,
    )
    before = _text(
        _pick(subject_before_hash, source, "subject_before", default=LIVE3_BASELINE_SUBJECT_HASH),
        128,
    )
    after = _text(
        _pick(subject_after_hash, source, "subject_after", "current_subject_hash", default=before),
        128,
    )
    current = _text(
        _pick(current_subject_hash, source, default=after),
        128,
    )
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V265_SCHEMA_VERSION,
        "artifact_type": RECOVERY_FAILURE_EVIDENCE,
        "failure_source": VERIFICATION_FAILURE,
        "source_variant": VERIFICATION_FAILURE,
        "execution_id": execution,
        "authority_id": authority,
        "oracle_id": oracle,
        "oracle_hash": oracle_digest,
        "failed_check": _text(_pick(failed_check, source, "check", default="verification_failure"), 180),
        "detail": _text(_pick(detail, source, "target_symbol", default="deterministic verification failure"), 360),
        "verification_status": _text(_pick(verification_status, source, default="FAIL"), 80) or "FAIL",
        "verification_executed": True,
        "v25_6_executed": True,
        "verification_receipt_identity": _text(
            _pick(
                verification_receipt_identity,
                source,
                "receipt_identity", "verification_receipt_id",
                default="deterministic_failed_verification_receipt",
            ),
            220,
        ) or "deterministic_failed_verification_receipt",
        "verification_digest": _text(
            _pick(verification_digest, source, default=LIVE3_VERIFICATION_DIGEST),
            128,
        ) or LIVE3_VERIFICATION_DIGEST,
        "coverage_hash": _text(
            _pick(coverage_hash, source, default=LIVE3_COVERAGE_HASH),
            128,
        ) or LIVE3_COVERAGE_HASH,
        "plan_id": _text(_pick(plan_id, source, default=LIVE3_PLAN_ID), 160) or LIVE3_PLAN_ID,
        "plan_hash": _text(_pick(plan_hash, source, default=LIVE3_PLAN_HASH), 128) or LIVE3_PLAN_HASH,
        "approval_id": _text(_pick(approval_id, source, default=LIVE3_APPROVAL_ID), 160) or LIVE3_APPROVAL_ID,
        "approval_receipt_hash": _text(
            _pick(approval_receipt_hash, source, default=LIVE3_APPROVAL_RECEIPT_HASH),
            128,
        ) or LIVE3_APPROVAL_RECEIPT_HASH,
        "execution_invariant_set_hash": _text(
            _pick(execution_invariant_set_hash, source, "invariant_hash", default=LIVE3_INVARIANT_HASH),
            128,
        ) or LIVE3_INVARIANT_HASH,
        "worker_result_status": _text(_pick(worker_result_status, source, default="failed"), 120) or "failed",
        "subject_before_hash": before,
        "subject_after_hash": after,
        "current_subject_hash": current,
        "subject_unchanged": before == after,
        "commit_count": 0,
        "commit": False,
        "filesystem_changed": False,
        "worker_prose_authority": 0,
        "evidence_basis": "deterministic_failed_verification_receipt",
        "canonical_hash": "",
    }
    value["canonical_hash"] = _failure_evidence_hash(value)
    value["failure_evidence_hash"] = value["canonical_hash"]
    return _freeze_record(VerificationFailureEvidence, value)  # type: ignore[return-value]


def build_worker_execution_failure_evidence(
    execution_id: str | dict[str, Any],
    *,
    terminal_code: str | None = None,
    terminal_state: str | None = None,
    failure_type: str | None = None,
    worker_result_status: str | None = None,
    subject_before_hash: str | None = None,
    subject_after_hash: str | None = None,
    current_subject_hash: str | None = None,
    worker_lifecycle_started: bool | None = None,
    provider_health: str | None = None,
    provider_handoff_valid: bool | None = None,
    execution_related: bool | None = None,
    verified_successful_completion: bool | None = None,
    v25_6_executed: bool | None = None,
    subject_known: bool | None = None,
    subject_unchanged: bool | None = None,
    lineage_status: str | None = None,
    unknown_manual_drift: bool | None = None,
    scope_valid: bool | None = None,
    dnt_valid: bool | None = None,
    plan_unchanged: bool | None = None,
    approval_unchanged: bool | None = None,
    brain_valid: bool | None = None,
    brain_unchanged: bool | None = None,
    promoted: bool | None = None,
    authority_delta_empty: bool | None = None,
    legal_solution_space_available: bool | None = None,
    full_verification_universe_available: bool | None = None,
    recovery_budget_available: bool | None = None,
    provider_failure: bool | None = None,
    harness_failure: bool | None = None,
    v25_5_authority_valid: bool | None = None,
    verification_obligation_ids: Iterable[str] | None = None,
    allowed_mutation_paths: Iterable[str] | None = None,
    authority_delta: dict[str, Any] | None = None,
    worker_lifecycle_count: int | None = None,
    commit_count: int | None = None,
    commit: bool | None = None,
    filesystem_changed: bool | None = None,
    failure_detail: str | None = None,
    completed: bool | None = None,
    completion_attempted: bool | None = None,
    completion_status: str | None = None,
    approved_mutation_count: int | None = None,
    changed_paths: Iterable[str] | None = None,
    coverage_status: str | None = None,
    missing_coverage_ids: Iterable[str] | None = None,
    plan_id: str | None = None,
    plan_hash: str | None = None,
    approval_id: str | None = None,
    approval_receipt_hash: str | None = None,
    execution_invariant_set_hash: str | None = None,
    promotion_status: str | None = None,
    lineage_evidence_ref: str | None = None,
    **kwargs: Any,
) -> WorkerExecutionFailureEvidence:
    """Build complete pre-verification Worker execution evidence.

    Defaults are deterministic values for constructing provider-free
    fixtures.  Evidence loaded from an external run should be passed with
    every required field present; the validator rejects omitted/null fields.
    Unknown keyword material is deliberately ignored so private model
    reasoning cannot enter the durable record.
    """
    source = _copy(execution_id) if isinstance(execution_id, dict) else _copy(kwargs)
    execution = (
        _text(source.get("execution_id"), 180)
        if isinstance(execution_id, dict)
        else _text(execution_id, 180)
    )
    terminal = _text(
        _pick(terminal_code, source, "terminal_state", "failure_type", "execution_failure_code",
              default=WORKER_NO_APPROVED_MUTATION),
        180,
    ) or WORKER_NO_APPROVED_MUTATION
    status = _text(_pick(worker_result_status, source, default="failed"), 120) or "failed"
    before = _text(
        _pick(subject_before_hash, source, "subject_before", "pre_subject_hash",
              default=LIVE3_BASELINE_SUBJECT_HASH),
        128,
    )
    after = _text(
        _pick(subject_after_hash, source, "subject_after", "post_subject_hash",
              default=_pick(current_subject_hash, source, default=before)),
        128,
    )
    current = _text(
        _pick(current_subject_hash, source, default=after),
        128,
    )
    unchanged = _pick(
        subject_unchanged,
        source,
        default=before == after,
    )
    lifecycle = _pick(
        worker_lifecycle_started,
        source,
        "actual_worker_lifecycle", "actual_worker_lifecycle_started",
        default=True,
    )
    health = _pick(provider_health, source, default=None)
    if health is None and "provider_healthy" in source:
        health = "HEALTHY" if source.get("provider_healthy") is True else "UNHEALTHY"
    health = _text(health, 80) or "HEALTHY"
    provider_handoff = _pick(
        provider_handoff_valid,
        source,
        "valid_provider_handoff",
        default=True,
    )
    execution_flag = _pick(execution_related, source, default=True)
    verified_completion = _pick(
        verified_successful_completion,
        source,
        default=None,
    )
    if verified_completion is None:
        no_verified_alias = _pick(
            None,
            source,
            "no_verified_completion",
            "no_verified_successful_completion",
            default=None,
        )
        verified_completion = (
            not bool(no_verified_alias)
            if no_verified_alias is not None
            else False
        )
    verified_completion = bool(verified_completion)
    no_verified = not verified_completion
    v25_6 = _pick(v25_6_executed, source, default=False)
    known_subject = _pick(subject_known, source, "known_subject", default=True)
    lineage = _text(
        _pick(lineage_status, source, "known_lineage", default=AUTHORIZED_EXECUTION_DESCENDANT),
        120,
    ) or AUTHORIZED_EXECUTION_DESCENDANT
    drift = _pick(unknown_manual_drift, source, "unknown_drift", default=False)
    scope_ok = _pick(scope_valid, source, "scope_pass", default=True)
    dnt_ok = _pick(dnt_valid, source, "dnt_pass", default=True)
    plan_ok = _pick(plan_unchanged, source, default=True)
    approval_ok = _pick(approval_unchanged, source, default=True)
    brain_ok = _pick(brain_valid, source, default=True)
    brain_same = _pick(brain_unchanged, source, default=True)
    promoted_flag = _pick(promoted, source, default=False)
    raw_delta = _pick(authority_delta, source, default={})
    delta_empty = _pick(authority_delta_empty, source, default=None)
    if delta_empty is None:
        delta_empty = not bool(raw_delta)
    legal_space = _pick(
        legal_solution_space_available,
        source,
        "legal_solution_space",
        default=True,
    )
    full_universe = _pick(
        full_verification_universe_available,
        source,
        "full_verification_universe",
        default=True,
    )
    budget = _pick(
        recovery_budget_available,
        source,
        default=True,
    )
    provider_failed = _pick(provider_failure, source, default=False)
    harness_failed = _pick(harness_failure, source, default=False)
    v25_5_ok = _pick(v25_5_authority_valid, source, "v25_5_valid", default=True)
    obligations = _unique_strings(
        _pick(verification_obligation_ids, source, "full_verification_authority_ids",
              "required_verification_authority_ids", default=(
                  "VERIFICATION-001", "VERIFICATION-002", "VERIFICATION-003", "VERIFICATION-004",
              )),
        limit=64,
        chars=180,
    )
    missing_coverage = _unique_strings(
        _pick(missing_coverage_ids, source, "not_run_obligation_ids", default=obligations),
        limit=64,
        chars=180,
    )
    mutation_paths = _unique_strings(
        _pick(allowed_mutation_paths, source, "legal_mutation_paths", default=("src/status_view.js",)),
        paths=True,
        limit=32,
    )
    delta_projection = _safe_projection(raw_delta)
    lifecycle_count = _safe_int(
        _pick(worker_lifecycle_count, source, default=1 if bool(lifecycle) else 0),
        0,
    )
    observed_commit_count = max(0, _safe_int(
        _pick(commit_count, source, default=0),
        0,
    ))
    observed_commit = bool(_pick(
        commit,
        source,
        default=observed_commit_count > 0,
    ))
    observed_filesystem_change = bool(_pick(
        filesystem_changed,
        source,
        default=observed_commit,
    ))
    completed_flag = bool(_pick(completed, source, "worker_completed", default=False))
    completion_attempt_flag = bool(_pick(
        completion_attempted,
        source,
        "completion_attempt",
        default=False,
    ))
    completion_state = _text(
        _pick(
            completion_status,
            source,
            "completion_state",
            default="COMPLETED" if completed_flag else "NOT_REACHED",
        ),
        120,
    ) or "NOT_REACHED"
    approved_mutations = max(0, _safe_int(
        _pick(approved_mutation_count, source, default=0),
        0,
    ))
    observed_changed_paths = _unique_strings(
        _pick(changed_paths, source, "changed_files", default=()),
        paths=True,
        limit=64,
    )
    observed_plan_id = _text(_pick(plan_id, source, default=LIVE3_PLAN_ID), 160) or LIVE3_PLAN_ID
    observed_plan_hash = _text(_pick(plan_hash, source, default=LIVE3_PLAN_HASH), 128) or LIVE3_PLAN_HASH
    observed_approval_id = _text(_pick(approval_id, source, default=LIVE3_APPROVAL_ID), 160) or LIVE3_APPROVAL_ID
    observed_approval_receipt_hash = _text(
        _pick(approval_receipt_hash, source, default=LIVE3_APPROVAL_RECEIPT_HASH),
        128,
    ) or LIVE3_APPROVAL_RECEIPT_HASH
    observed_invariant_hash = _text(
        _pick(execution_invariant_set_hash, source, "invariant_hash", default=LIVE3_INVARIANT_HASH),
        128,
    ) or LIVE3_INVARIANT_HASH
    observed_promotion_status = _text(
        _pick(promotion_status, source, default="NOT_REACHED"),
        120,
    ) or "NOT_REACHED"
    observed_lineage_ref = _text(
        _pick(
            lineage_evidence_ref,
            source,
            default="lineage:authorized-execution-descendant",
        ),
        220,
    ) or "lineage:authorized-execution-descendant"
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V265_SCHEMA_VERSION,
        "artifact_type": RECOVERY_FAILURE_EVIDENCE,
        "failure_source": WORKER_EXECUTION_FAILURE,
        "source_variant": WORKER_EXECUTION_FAILURE,
        "execution_id": execution,
        "worker_terminal_code": terminal,
        "execution_failure_code": terminal,
        "failure_type": terminal,
        "failure_detail": _text(
            _pick(failure_detail, source, "diagnostic", default=terminal),
            700,
        ),
        "worker_result_status": status,
        "actual_worker_lifecycle": bool(lifecycle),
        "worker_lifecycle_started": bool(lifecycle),
        "worker_lifecycle_count": lifecycle_count,
        "provider_health": health,
        "provider_healthy": health == "HEALTHY",
        "provider_handoff_valid": bool(provider_handoff),
        "valid_provider_handoff": bool(provider_handoff),
        "execution_related": bool(execution_flag),
        "verified_successful_completion": verified_completion,
        "no_verified_successful_completion": bool(no_verified),
        "completed": completed_flag,
        "completion_attempted": completion_attempt_flag,
        "completion_status": completion_state,
        "v25_6_executed": bool(v25_6),
        "no_v25_6_claim": not bool(v25_6),
        "subject_known": bool(known_subject),
        "subject_unchanged": bool(unchanged),
        "lineage_status": lineage,
        "known_lineage": lineage == AUTHORIZED_EXECUTION_DESCENDANT,
        "unknown_manual_drift": bool(drift),
        "scope_valid": bool(scope_ok),
        "dnt_valid": bool(dnt_ok),
        "dnt_digest": _text(_pick(None, source, "dnt_digest", default=""), 128),
        "plan_unchanged": bool(plan_ok),
        "approval_unchanged": bool(approval_ok),
        "brain_valid": bool(brain_ok),
        "brain_unchanged": bool(brain_same),
        "brain_before_hash": _text(
            _pick(None, source, "brain_before_hash", default=LIVE3_BRAIN_HASH), 128
        ) or LIVE3_BRAIN_HASH,
        "brain_after_hash": _text(
            _pick(None, source, "brain_after_hash", default=LIVE3_BRAIN_HASH), 128
        ) or LIVE3_BRAIN_HASH,
        "promoted": bool(promoted_flag),
        "authority_delta_empty": bool(delta_empty),
        "authority_delta": delta_projection,
        "legal_solution_space_available": bool(legal_space),
        "legal_solution_space": bool(legal_space),
        "legal_mutation_paths": mutation_paths,
        "full_verification_universe_available": bool(full_universe),
        "full_verification_universe": bool(full_universe),
        "verification_obligation_ids": obligations,
        "recovery_budget_available": bool(budget),
        "provider_failure": bool(provider_failed),
        "harness_failure": bool(harness_failed),
        "not_provider_or_harness_failure": not bool(provider_failed or harness_failed),
        "v25_5_authority_valid": bool(v25_5_ok),
        "approved_mutation_count": approved_mutations,
        "changed_paths": observed_changed_paths,
        "coverage_status": _text(
            _pick(coverage_status, source, default="AVAILABLE_NOT_EXECUTED"),
            160,
        ) or "AVAILABLE_NOT_EXECUTED",
        "missing_coverage_ids": missing_coverage,
        "plan_id": observed_plan_id,
        "plan_hash": observed_plan_hash,
        "approval_id": observed_approval_id,
        "approval_receipt_hash": observed_approval_receipt_hash,
        "execution_invariant_set_hash": observed_invariant_hash,
        "promotion_status": observed_promotion_status,
        "lineage_evidence_ref": observed_lineage_ref,
        "execution_failure_detail": _text(
            _pick(failure_detail, source, "diagnostic", default=terminal),
            700,
        ),
        "subject_before_hash": before,
        "subject_after_hash": after,
        "current_subject_hash": current,
        "commit_count": observed_commit_count,
        "commit": observed_commit,
        "filesystem_changed": observed_filesystem_change,
        "worker_prose_authority": 0,
        "verification_obligation_evidence_executed": False,
        "allowed_mutation_paths": mutation_paths,
        "canonical_hash": "",
    }
    value["canonical_hash"] = _failure_evidence_hash(value)
    value["failure_evidence_hash"] = value["canonical_hash"]
    return _freeze_record(WorkerExecutionFailureEvidence, value)  # type: ignore[return-value]


def build_recovery_failure_evidence(
    source_or_execution_id: str | dict[str, Any] | None = None,
    *,
    failure_source: str | None = None,
    execution_id: str | None = None,
    **kwargs: Any,
) -> RecoveryFailureEvidence:
    """Dispatch to one explicit member of the V26.5 failure-source union."""
    source = _copy(source_or_execution_id) if isinstance(source_or_execution_id, dict) else _copy(kwargs)
    if isinstance(source_or_execution_id, str) and source_or_execution_id in {
        VERIFICATION_FAILURE, WORKER_EXECUTION_FAILURE,
    }:
        failure_source = failure_source or source_or_execution_id
    elif execution_id is None:
        execution_id = _text(source_or_execution_id, 180)
    selected = failure_source if failure_source is not None else source.get("failure_source")
    selected = _text(selected, 120)
    execution = execution_id or source.get("execution_id") or "EXECUTION-UNKNOWN"
    source.pop("execution_id", None)
    if selected == WORKER_EXECUTION_FAILURE:
        return build_worker_execution_failure_evidence(execution, **source)
    if selected == VERIFICATION_FAILURE:
        return build_verification_failure_evidence(execution, **source)
    # Preserve an invalid explicit tag as an immutable record so the
    # validator/classifier can fail closed instead of silently changing its
    # meaning to a different variant.
    invalid = {
        "schema_version": RECOVERY_V265_SCHEMA_VERSION,
        "artifact_type": RECOVERY_FAILURE_EVIDENCE,
        "failure_source": selected,
        "source_variant": selected,
        "execution_id": _text(execution, 180),
        "canonical_hash": "",
    }
    invalid["canonical_hash"] = _failure_evidence_hash(invalid)
    invalid["failure_evidence_hash"] = invalid["canonical_hash"]
    return _freeze_record(RecoveryFailureEvidence, invalid)  # type: ignore[return-value]


def validate_recovery_failure_evidence(
    evidence: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate the explicit tagged union with no null/implicit variant."""
    value = evidence if isinstance(evidence, dict) else {}
    errors: list[str] = []
    expected_hash = _failure_evidence_hash(value) if value else None
    if value.get("schema_version") != RECOVERY_V265_SCHEMA_VERSION:
        errors.append("failure evidence schema version is invalid")
    if value.get("artifact_type") != RECOVERY_FAILURE_EVIDENCE:
        errors.append("failure evidence artifact type is invalid")
    if value.get("canonical_hash") != expected_hash or value.get("failure_evidence_hash") != expected_hash:
        errors.append("failure evidence hash is invalid")
    for key in _FAILURE_EVIDENCE_COMMON_FIELDS:
        if key not in value or value.get(key) in (None, ""):
            errors.append(f"failure evidence field is missing: {key}")
    source = value.get("failure_source")
    if source not in {VERIFICATION_FAILURE, WORKER_EXECUTION_FAILURE}:
        errors.append("failure evidence source variant is invalid")
    if value.get("source_variant") != source:
        errors.append("failure evidence source variant is inconsistent")
    if value.get("worker_prose_authority") != 0:
        errors.append("failure evidence grants Worker prose authority")
    for key in ("commit_count",):
        if key in value and _safe_int(value.get(key), -1) < 0:
            errors.append(f"failure evidence field is invalid: {key}")
    if source == WORKER_EXECUTION_FAILURE:
        for key in _WORKER_EXECUTION_EVIDENCE_FIELDS:
            if key not in value or value.get(key) is None:
                errors.append(f"Worker execution evidence field is missing: {key}")
        for key in _WORKER_EVIDENCE_MIXING_KEYS:
            if key in value and value.get(key) not in (None, "", [], {}, False):
                errors.append(f"Worker execution evidence mixes verification field: {key}")
        bool_fields = (
            "actual_worker_lifecycle", "provider_handoff_valid", "execution_related",
            "verified_successful_completion", "v25_6_executed", "subject_known",
            "subject_unchanged", "unknown_manual_drift", "scope_valid", "dnt_valid",
            "plan_unchanged", "approval_unchanged", "brain_valid", "brain_unchanged",
            "promoted", "authority_delta_empty", "legal_solution_space_available",
            "full_verification_universe_available", "recovery_budget_available",
            "provider_failure", "harness_failure", "v25_5_authority_valid", "commit",
            "filesystem_changed",
        )
        for key in bool_fields:
            if key in value and not isinstance(value.get(key), bool):
                errors.append(f"Worker execution evidence boolean field is invalid: {key}")
        if _safe_int(value.get("worker_lifecycle_count"), -1) < 0:
            errors.append("Worker execution lifecycle count is invalid")
        for key in ("approved_mutation_count", "commit_count"):
            if not isinstance(value.get(key), int) or isinstance(value.get(key), bool) or value.get(key) < 0:
                errors.append(f"Worker execution evidence count is invalid: {key}")
        for key in ("changed_paths", "verification_obligation_ids", "missing_coverage_ids"):
            if not isinstance(value.get(key), list):
                errors.append(f"Worker execution evidence list is invalid: {key}")
        for key in (
            "worker_terminal_code", "failure_detail", "provider_health",
            "completion_status", "coverage_status", "plan_id", "plan_hash",
            "approval_id", "approval_receipt_hash", "execution_invariant_set_hash",
            "promotion_status", "lineage_evidence_ref",
        ):
            if not isinstance(value.get(key), str) or not value.get(key).strip():
                errors.append(f"Worker execution evidence text is invalid: {key}")
        # Negative policy values (provider failure, lineage drift, an
        # unsupported terminal, or a commit) are still valid observations.
        # They must reach the classifier so it can emit an auditable blocker;
        # only malformed/missing structure is an evidence-validation error.
    elif source == VERIFICATION_FAILURE:
        for key in _VERIFICATION_EVIDENCE_FIELDS:
            if key not in value or value.get(key) in (None, ""):
                errors.append(f"verification failure evidence field is missing: {key}")
        for key in _VERIFICATION_EVIDENCE_MIXING_KEYS:
            if key in value and value.get(key) not in (None, "", [], {}, False):
                errors.append(f"verification failure evidence mixes execution field: {key}")
        for key in ("verification_executed", "v25_6_executed"):
            if value.get(key) is not True:
                errors.append(f"verification failure evidence field is not true: {key}")
        for key in (
            "authority_id", "oracle_id", "oracle_hash", "failed_check", "detail",
            "verification_status", "verification_receipt_identity", "verification_digest",
            "coverage_hash", "plan_id", "plan_hash", "approval_id",
            "approval_receipt_hash", "execution_invariant_set_hash",
        ):
            if not isinstance(value.get(key), str) or not value.get(key).strip():
                errors.append(f"verification failure evidence text is invalid: {key}")
    if contains_forbidden_recovery_transcript(value):
        errors.append("failure evidence contains Worker-private transcript")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:60],
        "failure_source": source,
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


validate_failure_source_evidence = validate_recovery_failure_evidence
validate_failure_evidence = validate_recovery_failure_evidence
create_recovery_failure_evidence = build_recovery_failure_evidence
create_worker_execution_failure_evidence = build_worker_execution_failure_evidence
create_verification_failure_evidence = build_verification_failure_evidence


def classify_edit_exact_match_ambiguity(result: Any) -> dict[str, Any] | None:
    """Extract the generic exact-replacement contract error from tool output.

    The classifier intentionally knows nothing about the requested feature or
    source language. It only recognizes the deterministic contract emitted by
    the existing edit_file tool.
    """
    text = " ".join(str(result or "").strip().split())
    match = re.search(
        r"\bexpected\s+(\d+)\s+exact\s+replacement(?:\(s\)|s?)\s*,\s*found\s+(\d+)\b",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    expected = _safe_int(match.group(1), -1)
    actual = _safe_int(match.group(2), -1)
    if expected < 0 or actual < 0 or expected == actual:
        return None
    return {
        "failure_class": EDIT_EXACT_MATCH_AMBIGUOUS,
        "normalized_error_class": EDIT_EXACT_MATCH_AMBIGUOUS,
        "expected_replacements": expected,
        "actual_matches": actual,
        "diagnostic": _text(text, 900),
        "commit": False,
        "filesystem_changed": False,
    }


def _v264_subject_pair(
    state: dict[str, Any],
    subject_identity_before: Any = None,
    subject_identity_after: Any = None,
    subject_unchanged: bool | None = None,
) -> tuple[str | None, str | None, bool]:
    before = _strategy_subject_identity(
        subject_identity_before
        if subject_identity_before is not None
        else state.get("current_subject_hash")
    )
    after = _strategy_subject_identity(
        subject_identity_after if subject_identity_after is not None else before
    )
    unchanged = before == after if subject_unchanged is None else bool(subject_unchanged)
    return before, after, unchanged


def build_recovery_tool_contract_failure_pattern(
    recovery_execution_id: str,
    *,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    tool: str = "edit_file",
    target_path: str | None = None,
    failure_class: str = EDIT_EXACT_MATCH_AMBIGUOUS,
    normalized_error_class: str | None = None,
    failure_count: int = 1,
    subject_identity_before: Any = None,
    subject_identity_after: Any = None,
    subject_unchanged: bool | None = None,
    commit_count: int = 0,
    active_tool_schema_hash: str | None = None,
    active_legal_mutation_mechanisms: Iterable[str] | None = None,
    expected_replacements: int | None = None,
    actual_matches: int | None = None,
    deterministic_diagnostic: Any = "",
    **kwargs: Any,
) -> RecoveryToolContractFailurePattern:
    """Build immutable, generic evidence for one repeated tool mistake."""
    before = _strategy_subject_identity(
        subject_identity_before if subject_identity_before is not None
        else kwargs.get("subject_before")
    )
    after = _strategy_subject_identity(
        subject_identity_after if subject_identity_after is not None
        else kwargs.get("subject_after", before)
    )
    unchanged = before == after if subject_unchanged is None else bool(subject_unchanged)
    expected = expected_replacements
    actual = actual_matches
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V264_SCHEMA_VERSION,
        "artifact_type": RECOVERY_TOOL_CONTRACT_FAILURE_PATTERN,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "strategy_epoch": _safe_int(strategy_epoch, RECOVERY_STRATEGY_EPOCH_0),
        "tool": _text(tool, 120),
        "target_path": _path(target_path),
        "target": _path(target_path),
        "mechanism": _text(tool, 120),
        "failure_class": _text(failure_class, 160),
        "normalized_error_class": _text(
            normalized_error_class or failure_class, 160
        ),
        "failure_count": max(0, _safe_int(failure_count, 0)),
        "subject_identity_before": before,
        "subject_identity_after": after,
        "subject_identity": after or before,
        "subject_unchanged": unchanged,
        "commit_count": max(0, _safe_int(commit_count, 0)),
        "commit": bool(commit_count),
        "filesystem_changed": bool(commit_count),
        "active_tool_schema_hash": _text(active_tool_schema_hash, 128) or None,
        "active_legal_mutation_mechanisms": _unique_strings(
            active_legal_mutation_mechanisms
            if active_legal_mutation_mechanisms is not None
            else kwargs.get("active_legal_mutation_mechanisms", []),
            limit=24,
        ),
        "expected_replacements": (
            max(0, _safe_int(expected, 0)) if expected is not None else None
        ),
        "actual_matches": (
            max(0, _safe_int(actual, 0)) if actual is not None else None
        ),
        "deterministic_diagnostic": _text(deterministic_diagnostic, 900),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryToolContractFailurePattern, value)  # type: ignore[return-value]


def validate_recovery_tool_contract_failure_pattern(
    pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    value = pattern if isinstance(pattern, dict) else {}
    expected_hash = (
        canonical_hash(_without(value, "canonical_hash")) if value else None
    )
    errors: list[str] = []
    if value.get("schema_version") != RECOVERY_V264_SCHEMA_VERSION:
        errors.append("tool-contract failure pattern schema version is invalid")
    if value.get("artifact_type") != RECOVERY_TOOL_CONTRACT_FAILURE_PATTERN:
        errors.append("tool-contract failure pattern artifact type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("tool-contract failure pattern hash is invalid")
    for key in (
        "recovery_execution_id",
        "tool",
        "target_path",
        "failure_class",
        "normalized_error_class",
    ):
        if not value.get(key):
            errors.append(f"tool-contract failure pattern is missing {key}")
    if _safe_int(value.get("strategy_epoch"), -1) not in {
        RECOVERY_STRATEGY_EPOCH_0,
        RECOVERY_STRATEGY_EPOCH_1,
    }:
        errors.append("tool-contract failure pattern epoch is invalid")
    if _safe_int(value.get("failure_count"), -1) < 1:
        errors.append("tool-contract failure count is invalid")
    if _safe_int(value.get("commit_count"), -1) != 0:
        errors.append("tool-contract failure pattern contains a commit")
    if value.get("commit") is not False:
        errors.append("tool-contract failure pattern commit flag is invalid")
    if value.get("filesystem_changed") is not False:
        errors.append("tool-contract failure pattern changed the filesystem")
    if value.get("subject_unchanged") is True and (
        value.get("subject_identity_before") != value.get("subject_identity_after")
    ):
        errors.append("unchanged tool-contract pattern has different subjects")
    if value.get("worker_prose_authority") != 0:
        errors.append("tool-contract failure pattern grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_tool_contract_guidance(
    pattern: dict[str, Any],
    *,
    active_legal_mutation_mechanisms: Iterable[str] | None = None,
    match_locations: Iterable[Any] | None = None,
    max_chars: int = 1600,
) -> str:
    """Render one bounded, patch-free escalation for repeated ambiguity."""
    value = pattern if isinstance(pattern, dict) else {}
    mechanisms = _unique_strings(
        active_legal_mutation_mechanisms
        if active_legal_mutation_mechanisms is not None
        else value.get("active_legal_mutation_mechanisms", []),
        limit=16,
        chars=120,
    )
    expected = value.get("expected_replacements")
    actual = value.get("actual_matches")
    text = (
        "TOOL CONTRACT GUIDANCE\n"
        f"{value.get('tool') or 'edit_file'} rejected the request for "
        f"{value.get('target_path') or '(unknown target)'}: the selected old "
        f"fragment matched {actual if actual is not None else '(unknown)'} "
        f"locations, but exactly {expected if expected is not None else '(unknown)'} "
        "replacement(s) were required.\n"
        "The filesystem was unchanged. The selected old fragment is not unique "
        "enough. Re-read the relevant enclosing block and choose a uniquely "
        "identifying old fragment before retrying.\n"
        f"Active legal mutation mechanisms: {', '.join(mechanisms) or '(none)'}.\n"
        "Continue the SAME RecoveryMission; choose the implementation. No code "
        "patch is prescribed."
    )
    locations = _unique_strings(match_locations, limit=8, chars=120)
    if locations:
        text += "\nBounded match locations: " + ", ".join(locations)
    return _text(text, max(256, int(max_chars)))


def build_recovery_tool_contract_guidance_event(
    pattern: dict[str, Any],
    guidance: str,
    *,
    guidance_ordinal: int = 1,
    subject_identity: Any = None,
) -> RecoveryToolContractGuidanceEvent:
    value = pattern if isinstance(pattern, dict) else {}
    text = _text(guidance, 1600)
    event: dict[str, Any] = {
        "schema_version": RECOVERY_V264_SCHEMA_VERSION,
        "artifact_type": RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENT,
        "recovery_execution_id": value.get("recovery_execution_id"),
        "strategy_epoch": _safe_int(value.get("strategy_epoch"), 0),
        "tool": value.get("tool"),
        "target_path": value.get("target_path"),
        "failure_pattern_hash": value.get("canonical_hash"),
        "guidance_class": TOOL_CONTRACT_STAGNATION_DETECTED,
        "failure_class": value.get("failure_class"),
        "normalized_error_class": value.get("normalized_error_class"),
        "failure_count": _safe_int(value.get("failure_count"), 0),
        "commit_count": _safe_int(value.get("commit_count"), 0),
        "active_tool_schema_hash": value.get("active_tool_schema_hash"),
        "active_legal_mutation_mechanisms": _unique_strings(
            value.get("active_legal_mutation_mechanisms", []), limit=24
        ),
        "guidance_ordinal": max(1, _safe_int(guidance_ordinal, 1)),
        "model_visible_guidance": text,
        "model_visible_guidance_hash": canonical_hash(text),
        "subject_identity": _strategy_subject_identity(
            subject_identity
            if subject_identity is not None
            else value.get("subject_identity_after")
        ),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    event["canonical_hash"] = canonical_hash(_without(event, "canonical_hash"))
    return _freeze_record(RecoveryToolContractGuidanceEvent, event)  # type: ignore[return-value]


def validate_recovery_tool_contract_guidance_event(
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    value = event if isinstance(event, dict) else {}
    expected_hash = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != RECOVERY_V264_SCHEMA_VERSION:
        errors.append("tool-contract guidance schema version is invalid")
    if value.get("artifact_type") != RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENT:
        errors.append("tool-contract guidance artifact type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("tool-contract guidance hash is invalid")
    for key in ("recovery_execution_id", "failure_pattern_hash", "model_visible_guidance"):
        if not value.get(key):
            errors.append(f"tool-contract guidance is missing {key}")
    if value.get("model_visible_guidance_hash") != canonical_hash(
        value.get("model_visible_guidance", "")
    ):
        errors.append("tool-contract guidance hash is invalid")
    if value.get("worker_prose_authority") != 0:
        errors.append("tool-contract guidance grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def observe_recovery_tool_contract_failure(
    state: dict[str, Any] | None,
    *,
    tool: str = "edit_file",
    target_path: str | None = None,
    result: Any = "",
    failure_class: str | None = None,
    normalized_error_class: str | None = None,
    expected_replacements: int | None = None,
    actual_matches: int | None = None,
    subject_identity_before: Any = None,
    subject_identity_after: Any = None,
    subject_unchanged: bool | None = None,
    active_tool_schema_hash: str | None = None,
    active_legal_mutation_mechanisms: Iterable[str] | None = None,
    match_locations: Iterable[Any] | None = None,
    commit_count: int = 0,
) -> dict[str, Any]:
    """Record contract failure and escalate at most once per Worker."""
    current = _copy(state) if isinstance(state, dict) else {}
    current.setdefault("tool_contract_failure_patterns", [])
    current.setdefault("tool_contract_guidance_events", [])
    current.setdefault("tool_contract_guidance_events_used", 0)
    current.setdefault("last_tool_contract_failure_key", None)
    current.setdefault("tool_contract_failure_count", 0)
    current.setdefault("last_tool_contract_failure_pattern", None)
    current.setdefault("last_tool_contract_guidance", "")
    classification = classify_edit_exact_match_ambiguity(result)
    if (
        classification is None
        and failure_class is None
        and normalized_error_class is None
        and not commit_count
    ):
        return {
            "state": current,
            "pattern": None,
            "status": None,
            "guidance": "",
            "feedback": "",
            "guidance_event": None,
            "escalated": False,
            "failure_count": 0,
            "recognized": False,
        }
    if classification:
        failure_class = failure_class or classification["failure_class"]
        normalized_error_class = normalized_error_class or classification["normalized_error_class"]
        if expected_replacements is None:
            expected_replacements = classification["expected_replacements"]
        if actual_matches is None:
            actual_matches = classification["actual_matches"]
    failure_class = failure_class or EDIT_EXACT_MATCH_AMBIGUOUS
    normalized_error_class = normalized_error_class or failure_class
    before, after, unchanged = _v264_subject_pair(
        current,
        subject_identity_before,
        subject_identity_after,
        subject_unchanged,
    )
    epoch = _safe_int(current.get("strategy_epoch", 0), 0)
    execution = current.get("recovery_execution_id") or "RECOVERY-EXEC-UNKNOWN"
    target = _path(target_path or current.get("target_path"))
    key = (
        _text(execution, 160),
        epoch,
        _text(tool, 120).casefold(),
        target.casefold(),
        _text(normalized_error_class, 160).casefold(),
        before,
        after,
        bool(unchanged),
    )
    same = tuple(current.get("last_tool_contract_failure_key") or ()) == key
    count = (
        max(0, _safe_int(current.get("tool_contract_failure_count"), 0)) + 1
        if same and not commit_count
        else 1
    )
    if commit_count:
        count = 0
    pattern = build_recovery_tool_contract_failure_pattern(
        execution,
        strategy_epoch=epoch,
        tool=tool,
        target_path=target,
        failure_class=failure_class,
        normalized_error_class=normalized_error_class,
        failure_count=count,
        subject_identity_before=before,
        subject_identity_after=after,
        subject_unchanged=unchanged,
        commit_count=commit_count,
        active_tool_schema_hash=active_tool_schema_hash,
        active_legal_mutation_mechanisms=active_legal_mutation_mechanisms,
        expected_replacements=expected_replacements,
        actual_matches=actual_matches,
        deterministic_diagnostic=(
            classification.get("diagnostic") if classification else result
        ),
    )
    current["tool_contract_failure_count"] = count
    current["last_tool_contract_failure_key"] = None if commit_count else key
    current["last_tool_contract_failure_pattern"] = pattern
    current["tool_contract_failure_patterns"] = (
        list(current.get("tool_contract_failure_patterns", [])) + [pattern]
    )[-16:]
    guidance = ""
    guidance_event = None
    escalated = False
    if (
        count >= RECOVERY_STRATEGY_STAGNATION_THRESHOLD
        and not commit_count
        and _safe_int(current.get("tool_contract_guidance_events_used"), 0)
        < MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS
    ):
        guidance = build_recovery_tool_contract_guidance(
            {
                **dict(pattern),
                "active_legal_mutation_mechanisms": list(
                    active_legal_mutation_mechanisms
                    if active_legal_mutation_mechanisms is not None
                    else current.get("available_legal_mechanisms", [])
                ),
            },
            active_legal_mutation_mechanisms=active_legal_mutation_mechanisms,
            match_locations=match_locations,
        )
        guidance_event = build_recovery_tool_contract_guidance_event(
            pattern,
            guidance,
            guidance_ordinal=_safe_int(
                current.get("tool_contract_guidance_events_used"), 0
            ) + 1,
            subject_identity=after,
        )
        current["tool_contract_guidance_events"] = (
            list(current.get("tool_contract_guidance_events", [])) + [guidance_event]
        )[-MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS:]
        current["tool_contract_guidance_events_used"] = (
            _safe_int(current.get("tool_contract_guidance_events_used"), 0) + 1
        )
        current["last_tool_contract_guidance"] = guidance
        escalated = True
        status = TOOL_CONTRACT_STAGNATION_DETECTED
    elif count >= RECOVERY_STRATEGY_STAGNATION_THRESHOLD and not commit_count:
        status = TOOL_CONTRACT_GUIDANCE_BUDGET_EXHAUSTED
        current["terminal_state"] = TOOL_CONTRACT_GUIDANCE_BUDGET_EXHAUSTED
    else:
        status = TOOL_CONTRACT_FEEDBACK_ONLY
    return {
        "state": current,
        "pattern": pattern,
        "status": status,
        "guidance": guidance,
        "feedback": _text(result, 1600),
        "guidance_event": guidance_event,
        "escalated": escalated,
        "failure_count": count,
        "recognized": True,
    }


observe_tool_contract_failure = observe_recovery_tool_contract_failure
record_recovery_tool_contract_failure = observe_recovery_tool_contract_failure


def reset_recovery_tool_contract_failure_pattern(
    state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Reset only the consecutive tool-contract sequence for this Worker.

    The immutable pattern/guidance history is retained for evidence.  A
    different tool, target, subject, epoch, commit, or other intervening
    action must not let two non-consecutive ambiguities trigger escalation.
    """
    current = _copy(state) if isinstance(state, dict) else {}
    current["tool_contract_failure_count"] = 0
    current["last_tool_contract_failure_key"] = None
    current["last_tool_contract_failure_pattern"] = None
    return current


reset_tool_contract_failure_pattern = reset_recovery_tool_contract_failure_pattern


def _recovery_strategy_suppressed_tools(state: dict[str, Any]) -> list[str]:
    strategy = state.get("current_strategy")
    values = state.get("suppressed_mutation_mechanisms", [])
    if isinstance(strategy, dict):
        values = list(values or []) + list(
            strategy.get("suppressed_mutation_mechanisms", []) or []
        )
    return _unique_strings(values, limit=24, chars=120)


def build_suppressed_strategy_tool_feedback(
    *,
    requested_tool: str,
    strategy_epoch: int,
    active_legal_mutation_mechanisms: Iterable[str] | None = None,
    suppressed_tools: Iterable[str] | None = None,
    target_path: str | None = None,
    subject_identity: Any = None,
    max_chars: int = 1400,
) -> str:
    legal = _unique_strings(active_legal_mutation_mechanisms, limit=16, chars=120)
    suppressed = _unique_strings(suppressed_tools, limit=16, chars=120)
    return _text(
        "SUPPRESSED STRATEGY TOOL REQUEST\n"
        f"Requested tool: {_text(requested_tool, 120)}\n"
        f"Target: {_path(target_path)}\n"
        f"Current strategy epoch: {int(strategy_epoch)}\n"
        "The requested mutation mechanism was legal in a prior epoch but is "
        "unavailable in the current strategy epoch. The filesystem and "
        f"subject identity ({_strategy_subject_identity(subject_identity) or 'unknown'}) "
        "are unchanged.\n"
        f"Suppressed mechanisms: {', '.join(suppressed) or '(none)'}\n"
        f"Active legal mutation mechanisms: {', '.join(legal) or '(none)'}\n"
        "Continue the SAME RecoveryMission using the current tool contract.",
        max(256, int(max_chars)),
    )


def build_recovery_epoch_reanchor_context(
    state: dict[str, Any],
    *,
    requested_tool: str,
    latest_feedback: Any = "",
    base_context: Any = "",
    remaining_tool_steps: int | None = None,
    max_chars: int = 1800,
) -> str:
    """Build a fresh current-epoch projection without old transcript."""
    value = state if isinstance(state, dict) else {}
    strategy = value.get("current_strategy") if isinstance(value.get("current_strategy"), dict) else {}
    legal = _unique_strings(
        strategy.get("allowed_mutation_mechanisms")
        or value.get("available_legal_mechanisms", []),
        limit=16,
        chars=120,
    )
    suppressed = _recovery_strategy_suppressed_tools(value)
    mission_id = (
        value.get("recovery_mission_id")
        or value.get("mission_id")
        or "same RecoveryMission"
    )
    remaining = (
        max(0, _safe_int(remaining_tool_steps, 0))
        if remaining_tool_steps is not None
        else value.get("remaining_tool_steps", "unchanged")
    )
    refresh = value.get("current_source_refresh")
    if isinstance(refresh, dict):
        source_refresh = (
            f"status={_text(refresh.get('status'), 80) or 'unknown'}, "
            f"target={_path(refresh.get('target_path') or value.get('target_path'))}, "
            f"source_sha256={_text(refresh.get('source_sha256'), 128) or 'unavailable'}"
        )
    else:
        source_refresh = (
            "status=REFRESHED" if value.get("current_source_refreshed") is True
            else "status=not recorded"
        )
    text = (
        "RECOVERY EPOCH RE-ANCHOR\n"
        f"RecoveryMission: {_text(mission_id, 160)}\n"
        f"Recovery execution: {_text(value.get('recovery_execution_id'), 160)}\n"
        f"Strategy epoch: {_safe_int(value.get('strategy_epoch'), 0)}\n"
        f"Target: {_path(value.get('target_path'))}\n"
        f"Current subject identity: {_strategy_subject_identity(value.get('current_subject_hash')) or 'unknown'}\n"
        f"Requested suppressed tool: {_text(requested_tool, 120)}\n"
        f"Suppressed mechanisms: {', '.join(suppressed) or '(none)'}\n"
        f"Active legal mutation mechanisms: {', '.join(legal) or '(none)'}\n"
        f"Current-source refresh: {source_refresh}\n"
        f"Latest deterministic feedback: {_text(latest_feedback, 500)}\n"
        f"Remaining normal tool steps: {remaining}\n"
        "Use only the current epoch contract. Continue the SAME RecoveryMission; "
        "no implementation patch is prescribed."
    )
    if base_context:
        text = "MISSION ANCHOR:\n" + _text(base_context, 800) + "\n\n" + text
    return _text(text, max(256, int(max_chars)))


def build_recovery_epoch_reanchor_event(
    state: dict[str, Any],
    *,
    reason: str,
    active_tool_schema_hash: str | None = None,
    suppressed_tools: Iterable[str] | None = None,
    legal_tools: Iterable[str] | None = None,
    context_projection: Any = "",
    reanchor_ordinal: int = 1,
) -> RecoveryEpochReanchorEvent:
    value = state if isinstance(state, dict) else {}
    context = _text(context_projection, 1800)
    event: dict[str, Any] = {
        "schema_version": RECOVERY_V264_SCHEMA_VERSION,
        "artifact_type": RECOVERY_EPOCH_REANCHOR_EVENT,
        "recovery_execution_id": value.get("recovery_execution_id"),
        "strategy_epoch": _safe_int(value.get("strategy_epoch"), 0),
        "reason": _text(reason, 420),
        "active_tool_schema_hash": _text(active_tool_schema_hash, 128) or None,
        "suppressed_tools": _unique_strings(suppressed_tools, limit=24, chars=120),
        "legal_tools": _unique_strings(legal_tools, limit=24, chars=120),
        "subject_identity": _strategy_subject_identity(value.get("current_subject_hash")),
        "recovery_mission_id": value.get("recovery_mission_id") or value.get("mission_id"),
        "recovery_authorization_id": (
            (value.get("recovery_authorization") or {}).get("authorization_id")
            if isinstance(value.get("recovery_authorization"), dict)
            else None
        ),
        "recovery_authorization_hash": (
            (value.get("recovery_authorization") or {}).get("authorization_hash")
            if isinstance(value.get("recovery_authorization"), dict)
            else None
        ),
        "context_projection": context,
        "context_projection_hash": canonical_hash(context),
        "reanchor_ordinal": max(1, _safe_int(reanchor_ordinal, 1)),
        "strategy_switch_count": _safe_int(value.get("strategy_switch_count"), 0),
        "recovery_attempt_index": _safe_int(value.get("recovery_attempt_index"), 1),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    event["canonical_hash"] = canonical_hash(_without(event, "canonical_hash"))
    return _freeze_record(RecoveryEpochReanchorEvent, event)  # type: ignore[return-value]


def validate_recovery_epoch_reanchor_event(
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    value = event if isinstance(event, dict) else {}
    expected_hash = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != RECOVERY_V264_SCHEMA_VERSION:
        errors.append("epoch re-anchor schema version is invalid")
    if value.get("artifact_type") != RECOVERY_EPOCH_REANCHOR_EVENT:
        errors.append("epoch re-anchor artifact type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("epoch re-anchor hash is invalid")
    for key in (
        "recovery_execution_id",
        "reason",
        "context_projection",
        "context_projection_hash",
    ):
        if not value.get(key):
            errors.append(f"epoch re-anchor is missing {key}")
    if value.get("context_projection_hash") != canonical_hash(
        value.get("context_projection", "")
    ):
        errors.append("epoch re-anchor context hash is invalid")
    authorization = value.get("recovery_authorization_id")
    authorization_hash = value.get("recovery_authorization_hash")
    if authorization is not None and not authorization_hash:
        errors.append("epoch re-anchor authorization hash is missing")
    if _safe_int(value.get("reanchor_ordinal"), 0) < 1:
        errors.append("epoch re-anchor ordinal is invalid")
    if value.get("worker_prose_authority") != 0:
        errors.append("epoch re-anchor grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def observe_suppressed_strategy_tool_request(
    state: dict[str, Any] | None,
    *,
    requested_tool: str,
    target_path: str | None = None,
    active_tool_schema_hash: str | None = None,
    active_legal_mutation_mechanisms: Iterable[str] | None = None,
    subject_identity: Any = None,
    latest_feedback: Any = "",
    base_context: Any = "",
    remaining_tool_steps: int | None = None,
) -> dict[str, Any]:
    """Handle stale prior-epoch tool requests without changing the epoch."""
    current = _copy(state) if isinstance(state, dict) else {}
    suppressed = _recovery_strategy_suppressed_tools(current)
    requested = _text(requested_tool, 120)
    if requested.casefold() not in {item.casefold() for item in suppressed}:
        return {
            "state": current,
            "recognized": False,
            "status": None,
            "feedback": "",
            "reanchored": False,
            "event": None,
        }
    current.setdefault("suppressed_tool_request_count", 0)
    current.setdefault("last_suppressed_tool_request_key", None)
    current.setdefault("suppressed_tool_requests", [])
    current.setdefault("epoch_reanchors", [])
    current.setdefault("epoch_reanchors_used", 0)
    execution = current.get("recovery_execution_id") or "RECOVERY-EXEC-UNKNOWN"
    epoch = _safe_int(current.get("strategy_epoch"), 0)
    subject = _strategy_subject_identity(
        subject_identity
        if subject_identity is not None
        else current.get("current_subject_hash")
    )
    strategy = current.get("current_strategy") if isinstance(
        current.get("current_strategy"), dict
    ) else {}
    key = (
        _text(execution, 160),
        epoch,
        requested.casefold(),
        _path(target_path or current.get("target_path")).casefold(),
        subject,
        _text(strategy.get("canonical_hash"), 128),
    )
    same = tuple(current.get("last_suppressed_tool_request_key") or ()) == key
    count = _safe_int(current.get("suppressed_tool_request_count"), 0) + 1 if same else 1
    current["suppressed_tool_request_count"] = count
    current["last_suppressed_tool_request_key"] = key
    request_evidence = {
        "artifact_type": "RecoverySuppressedStrategyToolRequest",
        "recovery_execution_id": execution,
        "strategy_epoch": epoch,
        "requested_tool": requested,
        "target_path": _path(target_path or current.get("target_path")),
        "subject_identity": subject,
        "subject_unchanged": True,
        "commit_count": 0,
        "filesystem_changed": False,
        "request_count": count,
        "active_tool_schema_hash": _text(active_tool_schema_hash, 128) or None,
        "suppressed_tools": suppressed,
        "canonical_hash": "",
    }
    request_evidence["canonical_hash"] = canonical_hash(
        _without(request_evidence, "canonical_hash")
    )
    current["suppressed_tool_requests"] = (
        list(current.get("suppressed_tool_requests", [])) + [request_evidence]
    )[-16:]
    legal = _unique_strings(
        active_legal_mutation_mechanisms
        if active_legal_mutation_mechanisms is not None
        else strategy.get("allowed_mutation_mechanisms", [])
        or current.get("available_legal_mechanisms", []),
        limit=16,
        chars=120,
    )
    if count < RECOVERY_STRATEGY_STAGNATION_THRESHOLD:
        feedback = build_suppressed_strategy_tool_feedback(
            requested_tool=requested,
            strategy_epoch=epoch,
            active_legal_mutation_mechanisms=legal,
            suppressed_tools=suppressed,
            target_path=target_path or current.get("target_path"),
            subject_identity=subject,
        )
        return {
            "state": current,
            "recognized": True,
            "status": SUPPRESSED_STRATEGY_TOOL_REQUESTED,
            "feedback": feedback,
            "reanchored": False,
            "event": request_evidence,
            "request_count": count,
        }
    if _safe_int(current.get("epoch_reanchors_used"), 0) >= MAX_RECOVERY_EPOCH_REANCHORS:
        current["terminal_state"] = RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED
        return {
            "state": current,
            "recognized": True,
            "status": RECOVERY_EPOCH_REANCHOR_BUDGET_EXHAUSTED,
            "feedback": (
                "The bounded recovery epoch re-anchor budget is exhausted. "
                "The suppressed strategy tool remains unavailable; the Worker "
                "cannot continue with an obsolete tool contract."
            ),
            "reanchored": False,
            "event": request_evidence,
            "request_count": count,
        }
    context = build_recovery_epoch_reanchor_context(
        current,
        requested_tool=requested,
        latest_feedback=latest_feedback,
        base_context=base_context,
        remaining_tool_steps=remaining_tool_steps,
    )
    current["epoch_reanchors_used"] = _safe_int(
        current.get("epoch_reanchors_used"), 0
    ) + 1
    reanchor = build_recovery_epoch_reanchor_event(
        current,
        reason=STRATEGY_EPOCH_CONTEXT_STALE_OR_IGNORED,
        active_tool_schema_hash=active_tool_schema_hash,
        suppressed_tools=suppressed,
        legal_tools=legal,
        context_projection=context,
        reanchor_ordinal=current["epoch_reanchors_used"],
    )
    current["epoch_reanchors"] = (
        list(current.get("epoch_reanchors", [])) + [reanchor]
    )[-MAX_RECOVERY_EPOCH_REANCHORS:]
    current["last_epoch_reanchor"] = reanchor
    current["last_epoch_reanchor_context"] = context
    return {
        "state": current,
        "recognized": True,
        "status": STRATEGY_EPOCH_CONTEXT_STALE_OR_IGNORED,
        "feedback": context,
        "reanchored": True,
        "event": reanchor,
        "request_count": count,
    }


observe_suppressed_tool_request = observe_suppressed_strategy_tool_request
record_suppressed_strategy_tool_request = observe_suppressed_strategy_tool_request
reanchor_recovery_epoch = observe_suppressed_strategy_tool_request
recovery_strategy_suppressed_tools = _recovery_strategy_suppressed_tools
build_recovery_epoch_reanchor = build_recovery_epoch_reanchor_event
observe_recovery_epoch_reanchor = observe_suppressed_strategy_tool_request


def validate_recovery_completion_contract(
    completion_payload: dict[str, Any] | None,
    *,
    required_completion_fields: Iterable[str] | None = None,
    required_coverage_ids: Iterable[str] | None = None,
    verification_handoff_ready: bool | None = None,
) -> dict[str, Any]:
    """Validate shape only; never promote Worker self-reported verification."""
    payload = completion_payload if isinstance(completion_payload, dict) else {}
    fields = _unique_strings(
        required_completion_fields
        if required_completion_fields is not None
        else payload.get("required_completion_fields", []),
        limit=32,
        chars=160,
    )
    coverage_required = _unique_strings(
        required_coverage_ids
        if required_coverage_ids is not None
        else payload.get("required_coverage_ids", []),
        limit=64,
        chars=160,
    )
    missing_fields = [
        field for field in fields
        if field not in payload or payload.get(field) in (None, "", [], {})
    ]
    coverage = payload.get("coverage_ids")
    if coverage is None:
        coverage = payload.get("coverage")
    if coverage is None and isinstance(payload.get("execution_verification_closure"), dict):
        coverage = payload["execution_verification_closure"].get("covered_ids", [])
    covered = set(_unique_strings(coverage, limit=128, chars=160))
    missing_coverage = [item for item in coverage_required if item not in covered]
    invalid_fields = [
        field for field in fields
        if field in payload and payload.get(field) is False
    ]
    handoff = (
        verification_handoff_ready
        if verification_handoff_ready is not None
        else payload.get("verification_handoff_ready")
    )
    return {
        "valid": not missing_fields and not missing_coverage and not invalid_fields,
        "missing_completion_fields": missing_fields,
        "missing_coverage_ids": missing_coverage,
        "invalid_completion_fields": invalid_fields,
        "required_completion_fields": fields,
        "required_coverage_ids": coverage_required,
        "verification_handoff_ready": bool(handoff) if handoff is not None else False,
        "worker_self_report_non_authoritative": True,
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_completion_contract(
    *,
    required_completion_fields: Iterable[str] | None = None,
    required_coverage_ids: Iterable[str] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Build the bounded shape contract used at the recovery completion seam.

    This is deliberately a contract projection, not a verification receipt.
    The default fields name the existing lifecycle handoff objects; a Worker
    cannot satisfy them by self-reporting because downstream V25.6 and
    integration gates still create and validate the authoritative receipts.
    """
    fields = _unique_strings(
        required_completion_fields
        if required_completion_fields is not None
        else ("verified_child_receipt", "worker_execution", "execution_verification_closure"),
        limit=32,
        chars=160,
    )
    coverage = _unique_strings(
        required_coverage_ids if required_coverage_ids is not None else ("NODE-002",),
        limit=64,
        chars=160,
    )
    return {
        "schema_version": RECOVERY_V264_SCHEMA_VERSION,
        "artifact_type": "RecoveryCompletionContract",
        "enabled": bool(enabled),
        "required_completion_fields": fields,
        "required_coverage_ids": coverage,
        "worker_self_report_non_authoritative": True,
        "worker_prose_authority": 0,
    }


def build_recovery_completion_contract_repair(
    recovery_execution_id: str,
    *,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    recovery_mission_id: str | None = None,
    recovery_authorization_id: str | None = None,
    recovery_authorization_hash: str | None = None,
    current_subject_identity: Any = None,
    missing_completion_fields: Iterable[str] | None = None,
    missing_coverage_ids: Iterable[str] | None = None,
    verification_handoff_ready: bool = False,
    remaining_tool_steps: int = 0,
    repair_ordinal: int = 1,
    child_status: Any = "failed",
    completed: bool = False,
    failure_type: Any = WORKER_OUTPUT_INVALID,
    model_visible_feedback: Any = "",
) -> RecoveryCompletionContractRepair:
    feedback = _text(model_visible_feedback, 1600)
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V264_SCHEMA_VERSION,
        "artifact_type": RECOVERY_COMPLETION_REPAIR_EVENT,
        "repair_type": RECOVERY_COMPLETION_CONTRACT_REPAIR,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "strategy_epoch": _safe_int(strategy_epoch, 0),
        "recovery_mission_id": _text(recovery_mission_id, 160) or None,
        "recovery_authorization_id": _text(recovery_authorization_id, 160) or None,
        "recovery_authorization_hash": _text(recovery_authorization_hash, 128) or None,
        "current_subject_identity": _strategy_subject_identity(current_subject_identity),
        "missing_completion_fields": _unique_strings(
            missing_completion_fields, limit=32, chars=160
        ),
        "missing_coverage_ids": _unique_strings(
            missing_coverage_ids, limit=64, chars=160
        ),
        "verification_handoff_ready": bool(verification_handoff_ready),
        "remaining_tool_steps": max(0, _safe_int(remaining_tool_steps, 0)),
        "repair_ordinal": max(1, _safe_int(repair_ordinal, 1)),
        "child_status": _text(child_status, 120),
        "completed": bool(completed),
        "failure_type": _text(failure_type, 160),
        "model_visible_feedback": feedback,
        "model_visible_feedback_hash": canonical_hash(feedback),
        "worker_self_report_non_authoritative": True,
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryCompletionRepairEvent, value)  # type: ignore[return-value]


def build_recovery_completion_repair_feedback(
    validation: dict[str, Any],
    *,
    remaining_tool_steps: int,
    current_subject_identity: Any = None,
    max_chars: int = 1500,
) -> str:
    value = validation if isinstance(validation, dict) else {}
    missing_fields = _unique_strings(
        value.get("missing_completion_fields", []), limit=16, chars=160
    )
    missing_coverage = _unique_strings(
        value.get("missing_coverage_ids", []), limit=24, chars=160
    )
    return _text(
        "COMPLETION CONTRACT REPAIR\n"
        "Completion was rejected because the current Worker result is not "
        "structurally ready for the existing lifecycle.\n"
        f"Missing completion components: {', '.join(missing_fields) or '(none)'}\n"
        f"Unresolved coverage IDs: {', '.join(missing_coverage) or '(none)'}\n"
        f"Verification handoff ready: {bool(value.get('verification_handoff_ready'))}\n"
        f"Current project subject identity: "
        f"{_strategy_subject_identity(current_subject_identity) or 'unchanged/unknown'}\n"
        f"Remaining normal tool steps: {max(0, int(remaining_tool_steps))}\n"
        "Continue the SAME RecoveryMission and earn the missing deterministic "
        "evidence. Do not self-certify verification or promotion.",
        max(256, int(max_chars)),
    )


def validate_recovery_completion_repair_event(
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    value = event if isinstance(event, dict) else {}
    expected_hash = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != RECOVERY_V264_SCHEMA_VERSION:
        errors.append("completion repair schema version is invalid")
    if value.get("artifact_type") not in {
        RECOVERY_COMPLETION_CONTRACT_REPAIR,
        RECOVERY_COMPLETION_REPAIR_EVENT,
    }:
        errors.append("completion repair artifact type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("completion repair hash is invalid")
    for key in ("recovery_execution_id", "model_visible_feedback"):
        if not value.get(key):
            errors.append(f"completion repair is missing {key}")
    if value.get("model_visible_feedback_hash") != canonical_hash(
        value.get("model_visible_feedback", "")
    ):
        errors.append("completion repair feedback hash is invalid")
    if value.get("worker_prose_authority") != 0:
        errors.append("completion repair grants Worker prose authority")
    if value.get("worker_self_report_non_authoritative") is not True:
        errors.append("completion repair does not reject Worker self-certification")
    if value.get("recovery_authorization_id") and not value.get(
        "recovery_authorization_hash"
    ):
        errors.append("completion repair authorization hash is missing")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def observe_recovery_completion_attempt(
    state: dict[str, Any] | None,
    *,
    completion_payload: dict[str, Any] | None = None,
    required_completion_fields: Iterable[str] | None = None,
    required_coverage_ids: Iterable[str] | None = None,
    verification_handoff_ready: bool | None = None,
    remaining_tool_steps: int = 0,
    child_status: Any = "failed",
    completed: bool = False,
    failure_type: Any = WORKER_OUTPUT_INVALID,
) -> dict[str, Any]:
    """Offer exactly one same-Worker contract repair while budget remains."""
    current = _copy(state) if isinstance(state, dict) else {}
    current.setdefault("completion_repairs_used", 0)
    current.setdefault("completion_repair_events", [])
    current.setdefault("last_completion_repair", None)
    validation = validate_recovery_completion_contract(
        completion_payload,
        required_completion_fields=required_completion_fields,
        required_coverage_ids=required_coverage_ids,
        verification_handoff_ready=verification_handoff_ready,
    )
    if validation.get("valid"):
        return {
            "state": current,
            "status": "COMPLETION_CONTRACT_VALID",
            "repair": False,
            "terminal_state": None,
            "validation": validation,
            "event": None,
            "feedback": "",
        }
    remaining = max(0, _safe_int(remaining_tool_steps, 0))
    used = _safe_int(current.get("completion_repairs_used"), 0)
    if remaining <= 0 or used >= MAX_RECOVERY_COMPLETION_REPAIRS:
        terminal = (
            RECOVERY_COMPLETION_REPAIR_BUDGET_EXHAUSTED
            if used >= MAX_RECOVERY_COMPLETION_REPAIRS
            else WORKER_OUTPUT_INVALID
        )
        current["terminal_state"] = terminal
        return {
            "state": current,
            "status": terminal,
            "repair": False,
            "terminal_state": terminal,
            "validation": validation,
            "event": None,
            "feedback": "",
        }
    feedback = build_recovery_completion_repair_feedback(
        validation,
        remaining_tool_steps=remaining,
        current_subject_identity=current.get("current_subject_hash"),
    )
    execution = current.get("recovery_execution_id") or "RECOVERY-EXEC-UNKNOWN"
    epoch = _safe_int(current.get("strategy_epoch"), 0)
    event = build_recovery_completion_contract_repair(
        execution,
        strategy_epoch=epoch,
        recovery_mission_id=current.get("recovery_mission_id") or current.get("mission_id"),
        recovery_authorization_id=(
            (current.get("recovery_authorization") or {}).get("authorization_id")
            if isinstance(current.get("recovery_authorization"), dict)
            else None
        ),
        recovery_authorization_hash=(
            (current.get("recovery_authorization") or {}).get("authorization_hash")
            if isinstance(current.get("recovery_authorization"), dict)
            else None
        ),
        current_subject_identity=current.get("current_subject_hash"),
        missing_completion_fields=validation.get("missing_completion_fields"),
        missing_coverage_ids=validation.get("missing_coverage_ids"),
        verification_handoff_ready=validation.get("verification_handoff_ready", False),
        remaining_tool_steps=remaining,
        repair_ordinal=used + 1,
        child_status=child_status,
        completed=completed,
        failure_type=failure_type,
        model_visible_feedback=feedback,
    )
    current["completion_repairs_used"] = used + 1
    current["completion_repair_events"] = (
        list(current.get("completion_repair_events", [])) + [event]
    )[-MAX_RECOVERY_COMPLETION_REPAIRS:]
    current["last_completion_repair"] = event
    return {
        "state": current,
        "status": COMPLETION_CONTRACT_REPAIR_READY,
        "repair": True,
        "terminal_state": None,
        "validation": validation,
        "event": event,
        "feedback": feedback,
    }


observe_completion_attempt = observe_recovery_completion_attempt
record_recovery_completion_attempt = observe_recovery_completion_attempt
build_completion_contract_repair = build_recovery_completion_contract_repair
build_recovery_completion_repair_event = build_recovery_completion_contract_repair
validate_recovery_completion_contract_repair = validate_recovery_completion_repair_event


def _strategy_schema_list(value: Any) -> list[Any]:
    """Normalize either an OpenAI tools list or a single schema envelope."""
    if value is None:
        return []
    if isinstance(value, dict):
        for key in ("tools", "tool_schemas", "schemas", "functions"):
            candidate = value.get(key)
            if isinstance(candidate, (list, tuple)):
                return list(candidate)
        if "function" in value or "name" in value:
            return [value]
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return []


def _strategy_subject_identity(value: Any) -> str | None:
    """Return the canonical subject identity used by strategy evidence."""
    if isinstance(value, dict):
        value = _get(
            value, "subject_hash", "canonical_subject_hash", "current_subject_hash",
            "current_failed_subject_hash", "hash",
        )
    if value in (None, ""):
        return None
    return _text(value, 128)


def _strategy_tool_name(value: Any) -> str:
    if isinstance(value, dict):
        function = value.get("function") if isinstance(value.get("function"), dict) else {}
        return str(function.get("name") or value.get("name") or "").strip()
    return str(value or "").strip()


def _strategy_tool_description(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    function = value.get("function") if isinstance(value.get("function"), dict) else value
    return str(function.get("description") or "").strip()


def _strategy_tool_metadata(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    function = value.get("function") if isinstance(value.get("function"), dict) else value
    metadata: dict[str, Any] = {}
    for container in (value.get("metadata"), value.get("x-hivo"), function):
        if isinstance(container, dict):
            for key, item in container.items():
                metadata.setdefault(str(key), item)
    for key in (
        "mutation", "mutation_mechanism", "hivo_mutation_mechanism",
        "authority_required", "requires_existing_target", "existing_target_protected",
        "creates_new_only", "existing_target_policy",
    ):
        if key in function:
            metadata[key] = function.get(key)
    return metadata


def _strategy_is_mutation_tool(value: Any) -> bool:
    name = _strategy_tool_name(value).casefold()
    if name in {"write_file", "edit_file", "edit_file_range"}:
        return True
    metadata = _strategy_tool_metadata(value)
    if (
        metadata.get("mutation") is True
        or metadata.get("mutation_mechanism")
        or metadata.get("hivo_mutation_mechanism")
    ):
        return True
    description = _strategy_tool_description(value).casefold()
    return bool(
        "mutation mechanism" in description
        or "replace" in description and "file" in description
        or "edit" in description and "file" in description
        or "create a new file" in description
    )


def _strategy_authority_paths(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    paths: list[Any] = []
    for key in (
        "allowed_mutation_paths", "approved_mutation_paths", "approved_targets",
        "allowed_paths", "authorized_mutation_paths", "allowed_targets",
        "mutation_targets", "approved_mutation_scope", "approved_scope",
        "execution_scope", "paths", "scope", "mutation_scope",
    ):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            candidate = (
                candidate.get("paths")
                or candidate.get("allowed_paths")
                or candidate.get("approved_mutation_paths")
                or candidate.get("targets")
            )
        if isinstance(candidate, (list, tuple, set, frozenset)):
            paths.extend(candidate)
        elif candidate not in (None, "") and key not in {"scope", "mutation_scope"}:
            paths.append(candidate)
    return _unique_strings(paths, paths=True, limit=80)


def _strategy_dnt_paths(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    paths: list[Any] = []
    for key in ("dnt_paths", "do_not_touch", "dnt", "approved_dnt", "dnt_scope"):
        candidate = value.get(key)
        if isinstance(candidate, dict):
            candidate = candidate.get("paths") or candidate.get("dnt_paths") or candidate.get("targets")
        if isinstance(candidate, (list, tuple, set, frozenset)):
            paths.extend(candidate)
        elif candidate not in (None, "") and key not in {"dnt", "approved_dnt"}:
            paths.append(candidate)
    return _unique_strings(paths, paths=True, limit=80)


def _strategy_path_allowed(target: Any, paths: Iterable[Any]) -> bool:
    target_value = _path(target).casefold()
    if not target_value:
        return False
    normalized = [_path(item).casefold() for item in paths if _path(item)]
    if not normalized:
        return True
    return any(
        target_value == item or target_value.startswith(item.rstrip("/") + "/")
        for item in normalized
    )


def _strategy_authority_allows_target(
    target: Any,
    authority: dict[str, Any] | None,
    dnt: dict[str, Any] | None,
) -> tuple[bool, str]:
    authority = authority if isinstance(authority, dict) else {}
    dnt = dnt if isinstance(dnt, dict) else {}
    target_value = _path(target)
    if authority.get("allowed") is False or authority.get("mutation_allowed") is False:
        return False, "mutation authority is blocked"
    if authority.get("authority_sufficient") is False or authority.get("scope_allowed") is False:
        return False, "mutation authority is insufficient"
    if authority.get("authority_delta_empty") is False or authority.get("user_reapproval_required") is True:
        return False, "the strategy would require new user authority"
    if authority.get("requires_dnt_change") is True:
        return False, "the strategy requires a DNT change"
    allowed_paths = _strategy_authority_paths(authority)
    if allowed_paths and not _strategy_path_allowed(target_value, allowed_paths):
        return False, "target is outside the approved mutation scope"
    dnt_paths = _strategy_dnt_paths(dnt) or _strategy_dnt_paths(authority)
    if dnt_paths and _strategy_path_allowed(target_value, dnt_paths):
        return False, "target is inside the DNT scope"
    return True, "approved mutation scope permits the target"


def discover_legal_recovery_mutation_mechanisms(
    tool_schemas: Iterable[dict[str, Any]] | None = None,
    *,
    target: str | None = None,
    target_path: str | None = None,
    target_state: dict[str, Any] | None = None,
    mutation_authority: dict[str, Any] | None = None,
    authority: dict[str, Any] | None = None,
    dnt: dict[str, Any] | None = None,
    execution_invariant_set: Any = None,
    precommit_gate: Any = None,
) -> list[str]:
    """Derive legal mutation mechanisms from the actual Worker tool schema.

    This function intentionally does not define an edit-file fallback table.
    It projects the supplied schema through target authority, DNT, existing
    file protection, and the existing precommit gate.  The production tool
    names are recognized only as the schema's existing mutation mechanisms;
    custom schema metadata can expose additional mechanisms without changing
    this recovery policy.
    """
    schemas = _strategy_schema_list(tool_schemas)
    target_value = _path(target_path or target)
    if not target_value:
        return []
    state = target_state if isinstance(target_state, dict) else {}
    authority_value = mutation_authority if isinstance(mutation_authority, dict) else (
        authority if isinstance(authority, dict) else {}
    )
    dnt_value = dnt if isinstance(dnt, dict) else {}
    allowed, _reason = _strategy_authority_allows_target(target_value, authority_value, dnt_value)
    if not allowed:
        return []
    if execution_invariant_set is not None:
        if isinstance(execution_invariant_set, dict):
            status = str(execution_invariant_set.get("status", "")).casefold()
            if (
                execution_invariant_set.get("allowed") is False
                or execution_invariant_set.get("valid") is False
                or status in {"invalid", "fail", "failed", "blocked", "rejected"}
            ):
                return []
        elif execution_invariant_set is False:
            return []
    if callable(precommit_gate):
        try:
            gate_result = precommit_gate(target_value)
        except TypeError:
            try:
                gate_result = precommit_gate()
            except Exception:
                return []
        except Exception:
            return []
        if isinstance(gate_result, dict):
            if gate_result.get("allowed") is False or gate_result.get("valid") is False:
                return []
        elif gate_result is False:
            return []

    exists = bool(state.get("exists") or state.get("present") or state.get("current_source") is not None)
    protected = bool(
        state.get("protected") or state.get("user_owned") or state.get("verified")
        or state.get("existing_file_protected")
    )
    legal: list[str] = []
    for schema in schemas:
        name = _strategy_tool_name(schema)
        if not name or not _strategy_is_mutation_tool(schema):
            continue
        metadata = _strategy_tool_metadata(schema)
        description = _strategy_tool_description(schema).casefold()
        if (
            metadata.get("requires_existing_target") is True
            or metadata.get("existing_target_policy") == "required"
        ) and not exists:
            continue
        if metadata.get("creates_new_only") is True and exists:
            continue
        if metadata.get("existing_target_protected") is True and not protected:
            continue
        # Existing production write_file semantics explicitly protect an
        # existing user/verified file.  This is derived from its schema
        # contract, while edit_file/edit_file_range remain available.
        if exists and protected and name.casefold() == "write_file":
            continue
        if (
            exists and protected and "existing" in description and "protected" in description
            and name.casefold() == "write_file"
        ):
            continue
        if name.casefold() not in {item.casefold() for item in legal}:
            legal.append(name)
    return legal


def project_recovery_tool_schemas(
    tool_schemas: Iterable[dict[str, Any]] | None,
    strategy: dict[str, Any] | None = None,
    *,
    suppressed_mechanisms: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    """Apply one local recovery-epoch suppression to a tool projection."""
    suppressed = {
        str(item).casefold() for item in (
            suppressed_mechanisms
            if suppressed_mechanisms is not None
            else ((strategy or {}).get("suppressed_mutation_mechanisms", []) if isinstance(strategy, dict) else [])
        )
    }
    allowed = {
        str(item).casefold()
        for item in ((strategy or {}).get("allowed_mutation_mechanisms", [])
                     if isinstance(strategy, dict) else [])
    }
    result: list[dict[str, Any]] = []
    for schema in _strategy_schema_list(tool_schemas):
        name = _strategy_tool_name(schema)
        if name and name.casefold() in suppressed:
            continue
        # A strategy's allowed set is a local legal mutation projection. It
        # filters only mutation tools; inspection and verification tools stay
        # visible. An empty set means the caller supplied no legal projection
        # and preserves the ordinary role schema for compatibility.
        if allowed and _strategy_is_mutation_tool(schema) and name.casefold() not in allowed:
            continue
        result.append(_copy(schema))
    return result


recovery_tool_schema_projection = project_recovery_tool_schemas
project_recovery_tools = project_recovery_tool_schemas


# ---------------------------------------------------------------------------
# V26.6 bounded no-mutation search control
# ---------------------------------------------------------------------------

_RECOVERY_MUTATION_MECHANISM_NAMES = frozenset({
    "write_file", "edit_file", "edit_file_range",
})


RECOVERY_TOOL_INTENT_ACTIVE_MUTATION = "ACTIVE_MUTATION_MECHANISM"
RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION = "SUPPRESSED_STRATEGY_MUTATION_MECHANISM"
RECOVERY_TOOL_INTENT_ACTIVE_NON_MUTATION = "ACTIVE_NON_MUTATION_TOOL"
RECOVERY_TOOL_INTENT_UNAVAILABLE = "UNAVAILABLE_OR_UNKNOWN_TOOL"


def is_recovery_mutation_mechanism(value: Any) -> bool:
    """Return whether a Worker-selected tool is a recognized mutation path."""
    name = _strategy_tool_name(value).casefold()
    if name in _RECOVERY_MUTATION_MECHANISM_NAMES:
        return True
    return isinstance(value, dict) and _strategy_is_mutation_tool(value)


def classify_recovery_tool_intent(
    value: Any,
    *,
    active_tool_schema: Iterable[Any] | None = None,
    suppressed_mutation_mechanisms: Iterable[Any] | None = None,
    known_mutation_mechanisms: Iterable[Any] | None = None,
) -> str:
    """Classify a Worker tool request using the current runtime projection.

    The legacy ``is_recovery_mutation_mechanism`` predicate answers a static
    question about a tool name.  V26.6 reset semantics need a runtime answer:
    a name is an active mutation only when it is present in the current
    model-visible schema.  A missing name can still be a suppressed mutation
    only when the current strategy explicitly records that known mutation
    mechanism as suppressed.  Everything else is unavailable/unknown.
    """
    name = _strategy_tool_name(value).casefold()
    if not name:
        return RECOVERY_TOOL_INTENT_UNAVAILABLE

    active_matches = [
        schema for schema in _strategy_schema_list(active_tool_schema)
        if _strategy_tool_name(schema).casefold() == name
    ]
    if active_matches:
        if any(_strategy_is_mutation_tool(schema) for schema in active_matches):
            return RECOVERY_TOOL_INTENT_ACTIVE_MUTATION
        return RECOVERY_TOOL_INTENT_ACTIVE_NON_MUTATION

    known_names = set(_RECOVERY_MUTATION_MECHANISM_NAMES)
    known_candidates = _strategy_schema_list(known_mutation_mechanisms)
    if known_mutation_mechanisms is not None and not known_candidates:
        if isinstance(known_mutation_mechanisms, (str, bytes)):
            known_candidates = [known_mutation_mechanisms]
        else:
            try:
                known_candidates = list(known_mutation_mechanisms)
            except TypeError:
                known_candidates = [known_mutation_mechanisms]
    for candidate in known_candidates:
        candidate_name = _strategy_tool_name(candidate).casefold()
        # This argument is already an authoritative mutation-mechanism
        # projection from the active strategy.  Keep custom mechanisms
        # schema-dependent instead of requiring a lexical built-in name.
        if candidate_name:
            known_names.add(candidate_name)

    suppressed_candidates = _strategy_schema_list(suppressed_mutation_mechanisms)
    if suppressed_mutation_mechanisms is not None and not suppressed_candidates:
        if isinstance(suppressed_mutation_mechanisms, (str, bytes)):
            suppressed_candidates = [suppressed_mutation_mechanisms]
        else:
            try:
                suppressed_candidates = list(suppressed_mutation_mechanisms)
            except TypeError:
                suppressed_candidates = [suppressed_mutation_mechanisms]
    suppressed_names = {
        _strategy_tool_name(candidate).casefold()
        for candidate in suppressed_candidates
        if _strategy_tool_name(candidate)
    }
    if name in suppressed_names and name in known_names:
        return RECOVERY_TOOL_INTENT_SUPPRESSED_MUTATION
    return RECOVERY_TOOL_INTENT_UNAVAILABLE


def _v266_authority_explicitly_blocks(state: dict[str, Any]) -> bool:
    """Detect explicit authority failure without guessing from missing fields."""
    authority = state.get("recovery_authorization")
    if not isinstance(authority, dict):
        return False
    if authority.get("status") in {
        RECOVERY_AUTHORIZATION_BLOCKED,
        RECOVERY_BLOCKED,
        AUTHORITY_CHANGE_REQUIRED,
    }:
        return True
    return bool(
        authority.get("allowed") is False
        or authority.get("mutation_allowed") is False
        or authority.get("authority_sufficient") is False
        or authority.get("scope_allowed") is False
        or authority.get("authority_delta_empty") is False
        or authority.get("user_reapproval_required") is True
        or authority.get("requires_dnt_change") is True
    )


def _v266_legal_mechanisms(
    state: dict[str, Any],
    legal_mutation_mechanisms: Iterable[str] | None = None,
) -> list[str]:
    if legal_mutation_mechanisms is not None:
        return _unique_strings(legal_mutation_mechanisms, limit=24, chars=120)
    # An explicitly empty active set is an authoritative no-legal-space
    # result. Do not fall back to the strategy's original set in that case.
    if "available_legal_mechanisms" in state and state.get(
        "available_legal_mechanisms"
    ) == []:
        return []
    strategy = state.get("current_strategy")
    if isinstance(strategy, dict) and strategy.get("allowed_mutation_mechanisms"):
        return _unique_strings(
            strategy.get("allowed_mutation_mechanisms"), limit=24, chars=120
        )
    return _unique_strings(
        state.get("available_legal_mechanisms", []), limit=24, chars=120
    )


def _v266_legal_space_identity(legal: Iterable[str]) -> str:
    return canonical_hash(sorted({str(item).casefold() for item in legal}))


def _v266_state_bool(
    state: dict[str, Any],
    key: str,
    default: bool = True,
    *fallback_keys: str,
) -> bool:
    if key in state:
        return bool(state.get(key))
    for fallback in fallback_keys:
        if fallback in state:
            return bool(state.get(fallback))
    return bool(default)


def initialize_recovery_no_mutation_search_state(
    state: dict[str, Any] | None,
    *,
    legal_mutation_mechanisms: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Add bounded V26.6 state to one existing recovery Worker state.

    The function is intentionally additive.  It preserves the RecoveryMission,
    authorization, strategy epoch, and all pre-existing V26.3/V26.4 state.
    """
    current = _copy(state) if isinstance(state, dict) else {}
    legal = _v266_legal_mechanisms(current, legal_mutation_mechanisms)
    current.setdefault("no_mutation_search_interaction_count", 0)
    current.setdefault("no_mutation_search_window_key", None)
    current.setdefault("no_mutation_search_window_first_event_id", None)
    current.setdefault("no_mutation_search_pattern", None)
    current.setdefault("no_mutation_search_patterns", [])
    current.setdefault("no_mutation_search_interaction_events", [])
    current.setdefault("no_mutation_search_reset_reason", None)
    current.setdefault("no_mutation_search_window_ordinal", 1)
    current.setdefault("mutation_path_reorientations_used", 0)
    current.setdefault("max_mutation_path_reorientations", MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS)
    current.setdefault("mutation_path_reorientation_events", [])
    current.setdefault("last_mutation_path_reorientation", None)
    current.setdefault("last_mutation_path_reorientation_context", "")
    current.setdefault("no_mutation_search_exhausted", False)
    current.setdefault("no_mutation_search_exhaustion_evidence", None)
    current.setdefault("no_mutation_search_terminal_state", None)
    current.setdefault("recovery_mission_unresolved", True)
    current.setdefault("provider_healthy", True)
    current.setdefault("provider_harness_blocked", False)
    current.setdefault("authority_unchanged", True)
    current.setdefault("scope_valid", True)
    current.setdefault("dnt_valid", True)
    current.setdefault("current_target_known", bool(current.get("target_path")))
    current.setdefault("legal_mutation_space_identity", _v266_legal_space_identity(legal))
    return current


def reset_recovery_no_mutation_search_state(
    state: dict[str, Any] | None,
    *,
    reason: str = "state_changed",
) -> dict[str, Any]:
    """Reset only the active V26.6 search window, retaining immutable history."""
    current = initialize_recovery_no_mutation_search_state(state)
    current["no_mutation_search_interaction_count"] = 0
    current["no_mutation_search_window_key"] = None
    current["no_mutation_search_window_first_event_id"] = None
    current["no_mutation_search_reset_reason"] = _text(reason, 160)
    current["no_mutation_search_window_ordinal"] = max(
        1, _safe_int(current.get("no_mutation_search_window_ordinal"), 1)
    ) + 1
    current["legal_mutation_space_identity"] = _v266_legal_space_identity(
        _v266_legal_mechanisms(current)
    )
    return current


def build_recovery_no_mutation_search_interaction(
    recovery_execution_id: str,
    *,
    event_id: str,
    tool_name: str,
    recovery_attempt_index: int = 1,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    target_path: str | None = None,
    subject_identity: Any = None,
    interaction_count: int = 1,
    tool_steps_used: int = 0,
    tool_steps_remaining: int = 0,
) -> RecoveryNoMutationSearchInteraction:
    """Build one bounded counted-interaction projection for external tracing."""
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V266_SCHEMA_VERSION,
        "artifact_type": RECOVERY_NO_MUTATION_SEARCH_INTERACTION,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "recovery_attempt_index": max(1, _safe_int(recovery_attempt_index, 1)),
        "strategy_epoch": max(0, _safe_int(strategy_epoch, 0)),
        "event_id": _text(event_id, 180),
        "tool_name": _text(tool_name, 120),
        "target_path": _path(target_path),
        "subject_identity": _strategy_subject_identity(subject_identity),
        "interaction_count": max(1, _safe_int(interaction_count, 1)),
        "tool_steps_used": max(0, _safe_int(tool_steps_used, 0)),
        "tool_steps_remaining": max(0, _safe_int(tool_steps_remaining, 0)),
        "mutation_attempt": False,
        "commit_count": 0,
        "subject_unchanged": True,
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryNoMutationSearchInteraction, value)  # type: ignore[return-value]


def validate_recovery_no_mutation_search_interaction(
    interaction: dict[str, Any] | None,
) -> dict[str, Any]:
    value = interaction if isinstance(interaction, dict) else {}
    errors: list[str] = []
    expected = canonical_hash(_without(value, "canonical_hash")) if value else None
    if value.get("schema_version") != RECOVERY_V266_SCHEMA_VERSION:
        errors.append("no-mutation interaction schema version is invalid")
    if value.get("artifact_type") != RECOVERY_NO_MUTATION_SEARCH_INTERACTION:
        errors.append("no-mutation interaction artifact type is invalid")
    if value.get("canonical_hash") != expected:
        errors.append("no-mutation interaction hash is invalid")
    for key in (
        "recovery_execution_id", "event_id", "tool_name", "target_path",
        "subject_identity", "interaction_count",
    ):
        if value.get(key) in (None, "", []):
            errors.append(f"no-mutation interaction is missing {key}")
    if value.get("mutation_attempt") is not False:
        errors.append("no-mutation interaction contains a mutation attempt")
    if _safe_int(value.get("commit_count"), -1) != 0:
        errors.append("no-mutation interaction contains a commit")
    if value.get("subject_unchanged") is not True:
        errors.append("no-mutation interaction subject is not unchanged")
    if value.get("worker_prose_authority") != 0:
        errors.append("no-mutation interaction grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_no_mutation_search_pattern(
    recovery_execution_id: str,
    *,
    recovery_attempt_index: int = 1,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    target_path: str | None = None,
    subject_identity: Any = None,
    legal_mutation_mechanisms: Iterable[str] | None = None,
    interaction_count: int = 0,
    mutation_attempts: int = 0,
    commit_count: int = 0,
    provider_healthy: bool = True,
    provider_harness_blocked: bool = False,
    tool_steps_used: int = 0,
    tool_steps_remaining: int = 0,
    first_interaction_event_id: str | None = None,
    latest_interaction_event_id: str | None = None,
    behavior_changing_mission_unresolved: bool = True,
    current_target_known: bool = True,
    subject_unchanged: bool = True,
    scope_valid: bool = True,
    dnt_valid: bool = True,
    authority_unchanged: bool = True,
    legal_mutation_space_available: bool = True,
    threshold: int = MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION,
    **kwargs: Any,
) -> RecoveryNoMutationSearchPattern:
    """Build immutable, deterministic evidence for a no-mutation window."""
    legal = _unique_strings(legal_mutation_mechanisms, limit=24, chars=120)
    target = _path(target_path)
    subject = _strategy_subject_identity(subject_identity)
    value: dict[str, Any] = {
        "schema_version": RECOVERY_V266_SCHEMA_VERSION,
        "artifact_type": RECOVERY_NO_MUTATION_SEARCH_PATTERN,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "recovery_attempt_index": max(1, _safe_int(recovery_attempt_index, 1)),
        "strategy_epoch": max(0, _safe_int(strategy_epoch, 0)),
        "target_path": target,
        "subject_identity": subject,
        "legal_mutation_mechanisms": legal,
        "legal_mutation_space_identity": _v266_legal_space_identity(legal),
        "interaction_count": max(0, _safe_int(interaction_count, 0)),
        "threshold": max(1, _safe_int(threshold, MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION)),
        "mutation_attempts": max(0, _safe_int(mutation_attempts, 0)),
        "commit_count": max(0, _safe_int(commit_count, 0)),
        "provider_healthy": bool(provider_healthy),
        "provider_harness_blocked": bool(provider_harness_blocked),
        "tool_steps_used": max(0, _safe_int(tool_steps_used, 0)),
        "tool_steps_remaining": max(0, _safe_int(tool_steps_remaining, 0)),
        "first_interaction_event_id": _text(first_interaction_event_id, 180) or None,
        "latest_interaction_event_id": _text(latest_interaction_event_id, 180) or None,
        "behavior_changing_mission_unresolved": bool(behavior_changing_mission_unresolved),
        "current_target_known": bool(current_target_known),
        "subject_unchanged": bool(subject_unchanged),
        "scope_valid": bool(scope_valid),
        "dnt_valid": bool(dnt_valid),
        "authority_unchanged": bool(authority_unchanged),
        "legal_mutation_space_available": bool(legal_mutation_space_available),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    # Ignore unknown keyword arguments intentionally.  Callers may carry
    # external trace metadata, but it is never allowed to enter the
    # authoritative pattern without an explicit bounded field above.
    del kwargs
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryNoMutationSearchPattern, value)  # type: ignore[return-value]


def validate_recovery_no_mutation_search_pattern(
    pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    value = pattern if isinstance(pattern, dict) else {}
    errors: list[str] = []
    expected_hash = canonical_hash(_without(value, "canonical_hash")) if value else None
    if value.get("schema_version") != RECOVERY_V266_SCHEMA_VERSION:
        errors.append("no-mutation search pattern schema version is invalid")
    if value.get("artifact_type") != RECOVERY_NO_MUTATION_SEARCH_PATTERN:
        errors.append("no-mutation search pattern artifact type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("no-mutation search pattern hash is invalid")
    for key in (
        "recovery_execution_id", "target_path", "subject_identity",
        "legal_mutation_mechanisms", "interaction_count", "threshold",
        "first_interaction_event_id", "latest_interaction_event_id",
    ):
        if value.get(key) in (None, "", []):
            errors.append(f"no-mutation search pattern is missing {key}")
    if _safe_int(value.get("interaction_count"), 0) < 1:
        errors.append("no-mutation search pattern interaction count is invalid")
    if _safe_int(value.get("mutation_attempts"), -1) != 0:
        errors.append("no-mutation search pattern contains a mutation attempt")
    if _safe_int(value.get("commit_count"), -1) != 0:
        errors.append("no-mutation search pattern contains a commit")
    if not value.get("provider_healthy"):
        errors.append("no-mutation search pattern provider is unhealthy")
    if value.get("provider_harness_blocked"):
        errors.append("no-mutation search pattern has a provider/harness blocker")
    if not value.get("legal_mutation_space_available"):
        errors.append("no-mutation search pattern has no legal mutation space")
    if value.get("worker_prose_authority") != 0:
        errors.append("no-mutation search pattern grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def detect_recovery_no_mutation_search_stagnation(
    pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    value = pattern if isinstance(pattern, dict) else {}
    valid = validate_recovery_no_mutation_search_pattern(value)
    threshold = max(
        1,
        _safe_int(
            value.get("threshold"),
            MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION,
        ),
    )
    detected = bool(
        valid.get("valid")
        and _safe_int(value.get("interaction_count"), 0) >= threshold
        and value.get("behavior_changing_mission_unresolved") is True
        and value.get("current_target_known") is True
        and value.get("subject_unchanged") is True
        and value.get("scope_valid") is True
        and value.get("dnt_valid") is True
        and value.get("authority_unchanged") is True
    )
    return {
        "detected": detected,
        "status": RECOVERY_NO_MUTATION_SEARCH_STAGNATION if detected else RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED,
        "threshold": threshold,
        "interaction_count": _safe_int(value.get("interaction_count"), 0),
        "canonical_hash": value.get("canonical_hash"),
        "valid": bool(valid.get("valid")),
        "errors": list(valid.get("errors", [])),
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_mutation_path_reorientation_context(
    state: dict[str, Any] | None,
    *,
    pattern: dict[str, Any] | None = None,
    target_path: str | None = None,
    legal_mutation_mechanisms: Iterable[str] | None = None,
    current_source_hash: Any = None,
    max_chars: int = 1800,
) -> str:
    """Build bounded model-visible state without patch or transcript content."""
    value = state if isinstance(state, dict) else {}
    target = _path(target_path or value.get("target_path"))
    legal = _v266_legal_mechanisms(value, legal_mutation_mechanisms)
    subject = _strategy_subject_identity(
        value.get("current_subject_hash")
    ) or _strategy_subject_identity((pattern or {}).get("subject_identity"))
    mission = _text(
        value.get("recovery_mission_id") or value.get("mission_id") or "same RecoveryMission",
        160,
    )
    source_hash = _strategy_subject_identity(current_source_hash)
    if source_hash is None:
        refresh = value.get("current_source_refresh")
        if isinstance(refresh, dict):
            source_hash = _text(refresh.get("source_sha256"), 128) or None
    contract = value.get("completion_contract") if isinstance(value.get("completion_contract"), dict) else {}
    coverage = _unique_strings(
        contract.get("required_coverage_ids") or contract.get("coverage_ids", []),
        limit=16,
        chars=120,
    )
    text = (
        "RECOVERY MUTATION-PATH REORIENTATION\n"
        "The behavior-changing RecoveryMission remains unresolved.\n"
        "No approved mutation has been attempted in the current recovery search window.\n"
        f"RecoveryMission: {mission}\n"
        f"Authorized mutation target: {target or '(unknown)'}\n"
        f"Current legal mutation mechanisms: {', '.join(legal) or '(none)'}\n"
        f"Current subject is unchanged: {'yes' if subject else 'unknown'}"
        f" ({subject or 'unknown'})\n"
        "Scope and DNT remain unchanged.\n"
        "The approved plan and approval remain unchanged; no new approval is requested.\n"
        "Full verification remains required before completion or handoff.\n"
        f"Current strategy epoch: {_safe_int(value.get('strategy_epoch'), 0)}\n"
        f"Remaining normal tool steps: {max(0, _safe_int(value.get('remaining_tool_steps'), 0))}\n"
    )
    if source_hash:
        text += f"Current source identity: {source_hash}\n"
    if coverage:
        text += f"Required verification coverage remains: {', '.join(coverage)}\n"
    text += "Continue the SAME RecoveryMission (the same RecoveryMission) using the current source and approved authority."
    return _text(text, max(256, int(max_chars)))


def build_recovery_mutation_path_reorientation_event(
    state: dict[str, Any] | None,
    *,
    trigger_pattern: dict[str, Any],
    target_path: str | None = None,
    subject_identity: Any = None,
    legal_mutation_mechanisms: Iterable[str] | None = None,
    tool_steps_used: int = 0,
    tool_steps_remaining: int = 0,
    reorientation_ordinal: int = 1,
    model_visible_context: Any = "",
    active_tool_schema_hash: str | None = None,
) -> RecoveryMutationPathReorientationEvent:
    value = state if isinstance(state, dict) else {}
    legal = _v266_legal_mechanisms(value, legal_mutation_mechanisms)
    context = _text(model_visible_context, 1800)
    event: dict[str, Any] = {
        "schema_version": RECOVERY_V266_SCHEMA_VERSION,
        "artifact_type": RECOVERY_MUTATION_PATH_REORIENTATION_EVENT,
        "reorientation_type": RECOVERY_MUTATION_PATH_REORIENTATION,
        "recovery_execution_id": value.get("recovery_execution_id"),
        "recovery_attempt_index": _safe_int(value.get("recovery_attempt_index"), 1),
        "recovery_mission_id": value.get("recovery_mission_id") or value.get("mission_id"),
        "recovery_authorization_id": (
            (value.get("recovery_authorization") or {}).get("authorization_id")
            if isinstance(value.get("recovery_authorization"), dict) else None
        ),
        "recovery_authorization_hash": (
            (value.get("recovery_authorization") or {}).get("authorization_hash")
            if isinstance(value.get("recovery_authorization"), dict) else None
        ),
        "plan_id": (
            (value.get("recovery_authorization") or {}).get("plan_id")
            or (value.get("recovery_authorization") or {}).get("parent_plan_id")
            if isinstance(value.get("recovery_authorization"), dict) else None
        ),
        "plan_hash": (
            (value.get("recovery_authorization") or {}).get("plan_hash")
            or (value.get("recovery_authorization") or {}).get("parent_plan_hash")
            if isinstance(value.get("recovery_authorization"), dict) else None
        ),
        "approval_receipt_hash": (
            (value.get("recovery_authorization") or {}).get("approval_receipt_hash")
            or (value.get("recovery_authorization") or {}).get("approval_hash")
            if isinstance(value.get("recovery_authorization"), dict) else None
        ),
        "strategy_epoch": _safe_int(value.get("strategy_epoch"), 0),
        "strategy_switch_count": _safe_int(value.get("strategy_switch_count"), 0),
        "trigger_pattern_hash": (trigger_pattern or {}).get("canonical_hash"),
        "target_path": _path(target_path or value.get("target_path")),
        "subject_identity": _strategy_subject_identity(
            subject_identity if subject_identity is not None else value.get("current_subject_hash")
        ),
        "legal_mutation_mechanisms": legal,
        "legal_mutation_space_identity": _v266_legal_space_identity(legal),
        "active_tool_schema_hash": _text(active_tool_schema_hash, 128) or None,
        "tool_steps_used": max(0, _safe_int(tool_steps_used, 0)),
        "tool_steps_remaining": max(0, _safe_int(tool_steps_remaining, 0)),
        "reorientation_ordinal": max(1, _safe_int(reorientation_ordinal, 1)),
        "reorientation_budget_max": MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        "reorientation_budget_used": max(0, _safe_int(value.get("mutation_path_reorientations_used"), 0)),
        "model_visible_context": context,
        "model_visible_context_hash": canonical_hash(context),
        "same_recovery_worker": True,
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    event["canonical_hash"] = canonical_hash(_without(event, "canonical_hash"))
    return _freeze_record(RecoveryMutationPathReorientationEvent, event)  # type: ignore[return-value]


def validate_recovery_mutation_path_reorientation_event(
    event: dict[str, Any] | None,
) -> dict[str, Any]:
    value = event if isinstance(event, dict) else {}
    errors: list[str] = []
    expected_hash = canonical_hash(_without(value, "canonical_hash")) if value else None
    if value.get("schema_version") != RECOVERY_V266_SCHEMA_VERSION:
        errors.append("V26.6 reorientation schema version is invalid")
    if value.get("artifact_type") != RECOVERY_MUTATION_PATH_REORIENTATION_EVENT:
        errors.append("V26.6 reorientation artifact type is invalid")
    if value.get("reorientation_type") != RECOVERY_MUTATION_PATH_REORIENTATION:
        errors.append("V26.6 reorientation type is invalid")
    if value.get("canonical_hash") != expected_hash:
        errors.append("V26.6 reorientation hash is invalid")
    for key in (
        "recovery_execution_id", "target_path", "subject_identity",
        "legal_mutation_mechanisms", "trigger_pattern_hash",
        "model_visible_context", "model_visible_context_hash",
    ):
        if value.get(key) in (None, "", []):
            errors.append(f"V26.6 reorientation is missing {key}")
    if value.get("model_visible_context_hash") != canonical_hash(
        value.get("model_visible_context", "")
    ):
        errors.append("V26.6 reorientation context hash is invalid")
    if value.get("same_recovery_worker") is not True:
        errors.append("V26.6 reorientation is not bound to the same Worker")
    if _safe_int(value.get("reorientation_ordinal"), 0) != 1:
        errors.append("V26.6 reorientation ordinal exceeds the one-shot budget")
    if _safe_int(value.get("reorientation_budget_max"), -1) != MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS:
        errors.append("V26.6 reorientation budget changed")
    if value.get("worker_prose_authority") != 0:
        errors.append("V26.6 reorientation grants Worker prose authority")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_visible_context_hash": value.get("model_visible_context_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def observe_recovery_no_mutation_search_interaction(
    state: dict[str, Any] | None,
    *,
    tool_name: str | None = None,
    tool: str | None = None,
    target_path: str | None = None,
    subject_identity: Any = None,
    subject_unchanged: bool | None = None,
    event_id: str | None = None,
    recognized_tool: bool = True,
    mutation_attempt: bool | None = None,
    committed: bool = False,
    commit_count: int = 0,
    recovery_active: bool = True,
    behavior_changing_mission_unresolved: bool | None = None,
    current_target_known: bool | None = None,
    legal_mutation_mechanisms: Iterable[str] | None = None,
    strategy_epoch: int | None = None,
    provider_healthy: bool | None = None,
    provider_harness_blocked: bool | None = None,
    authority_unchanged: bool | None = None,
    scope_valid: bool | None = None,
    dnt_valid: bool | None = None,
    remaining_tool_steps: int | None = None,
    tool_steps_used: int | None = None,
    terminal_state: Any = None,
    completion_attempt: bool = False,
    empty_response: bool = False,
    active_tool_schema_hash: str | None = None,
    base_context: Any = "",
    current_source_hash: Any = None,
    safety_floor: int = MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION,
) -> dict[str, Any]:
    """Observe one Worker interaction and, at most once, reorient mutation search.

    Every gate is fail-closed.  The returned state is a mutable orchestration
    copy; all pattern and event records stored in it are immutable records.
    """
    current = initialize_recovery_no_mutation_search_state(
        state, legal_mutation_mechanisms=legal_mutation_mechanisms
    )
    name = _text(tool_name or tool, 120)
    execution = _text(current.get("recovery_execution_id"), 160)
    attempt = max(1, _safe_int(current.get("recovery_attempt_index"), 1))
    epoch = max(
        0,
        _safe_int(
            strategy_epoch if strategy_epoch is not None else current.get("strategy_epoch"),
            0,
        ),
    )
    target = _path(
        current.get("target_path") if target_path is None else target_path
    )
    if target_path is not None:
        current["target_path"] = target
        current["current_target_known"] = bool(target)
    subject = _strategy_subject_identity(
        subject_identity if subject_identity is not None
        else current.get("current_subject_hash")
    )
    legal = _v266_legal_mechanisms(current, legal_mutation_mechanisms)
    current["available_legal_mechanisms"] = legal
    current["legal_mutation_space_identity"] = _v266_legal_space_identity(legal)
    if behavior_changing_mission_unresolved is None:
        behavior_changing_mission_unresolved = _v266_state_bool(
            current, "recovery_mission_unresolved", True,
        )
    if current_target_known is None:
        current_target_known = bool(target)
    if provider_healthy is None:
        provider_healthy = _v266_state_bool(current, "provider_healthy", True)
    if provider_harness_blocked is None:
        provider_harness_blocked = _v266_state_bool(
            current, "provider_harness_blocked", False,
        )
    if authority_unchanged is None:
        authority_unchanged = _v266_state_bool(current, "authority_unchanged", True)
    if scope_valid is None:
        scope_valid = _v266_state_bool(current, "scope_valid", True)
    if dnt_valid is None:
        dnt_valid = _v266_state_bool(current, "dnt_valid", True)
    lifecycle_active = _v266_state_bool(
        current, "worker_lifecycle_active", True, "recovery_worker_active"
    )
    lineage = current.get("lineage")
    lineage_valid = not isinstance(lineage, dict) or (
        lineage.get("valid") is not False
        and str(lineage.get("status", "")).casefold()
        not in {"invalid", "blocked", "drift", "unknown"}
    )
    if subject_unchanged is None:
        subject_unchanged = bool(subject)
    if mutation_attempt is None:
        mutation_attempt = (
            is_recovery_mutation_mechanism(name)
            or name.casefold() in {item.casefold() for item in legal}
        )
    if remaining_tool_steps is None:
        remaining_tool_steps = _safe_int(current.get("remaining_tool_steps"), -1)
    if tool_steps_used is None:
        tool_steps_used = _safe_int(current.get("tool_steps_used"), 0)
    remaining = _safe_int(remaining_tool_steps, -1)
    used_steps = max(0, _safe_int(tool_steps_used, 0))
    current["remaining_tool_steps"] = remaining
    current["tool_steps_used"] = used_steps

    def _result(status: str, **extra: Any) -> dict[str, Any]:
        result = {
            "state": current,
            "status": status,
            "counted": False,
            "interaction_count": _safe_int(
                current.get("no_mutation_search_interaction_count"), 0
            ),
            "pattern": current.get("no_mutation_search_pattern"),
            "reoriented": False,
            "event": None,
            "feedback": "",
            "exhausted": bool(current.get("no_mutation_search_exhausted")),
            "reset": False,
            "model_calls": 0,
            "worker_calls": 0,
        }
        result.update(extra)
        return result

    # A recognized mutation invocation owns the next adaptation decision even
    # when the candidate later fails syntax/V25.5/transaction/commit gates.
    if bool(mutation_attempt) or bool(committed) or _safe_int(commit_count, 0) > 0:
        current = reset_recovery_no_mutation_search_state(
            current, reason="mutation_attempt_or_commit"
        )
        current["current_subject_hash"] = subject or current.get("current_subject_hash")
        return {
            **_result(RECOVERY_NO_MUTATION_SEARCH_RESET),
            "state": current,
            "reset": True,
            "reset_reason": "mutation_attempt_or_commit",
        }

    # Empty provider responses and structured completion attempts remain
    # ordinary Worker-runtime evidence but are never search interactions.
    if empty_response or completion_attempt or not name or not recognized_tool:
        reason = (
            "empty_response" if empty_response else
            "completion_attempt" if completion_attempt else
            "unrecognized_tool" if not recognized_tool else "no_tool"
        )
        current["last_non_counted_search_reason"] = reason
        return _result(RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED, reason=reason)

    # These are eligibility predicates, not Worker prose.  Failure is fail
    # closed and clears the active window so stale search evidence cannot
    # cross a provider, authority, subject, or terminal boundary.
    blockers: list[str] = []
    if not recovery_active or not lifecycle_active:
        blockers.append("recovery_inactive")
    if not lineage_valid:
        blockers.append("lineage_invalid")
    if not behavior_changing_mission_unresolved:
        blockers.append("mission_resolved")
    if not current_target_known or not target:
        blockers.append("target_unknown")
    if not subject:
        blockers.append("subject_unknown")
    if not legal:
        blockers.append("no_legal_mutation_space")
    if not provider_healthy:
        blockers.append("provider_unhealthy")
    if provider_harness_blocked:
        blockers.append("provider_or_harness_blocked")
    if not authority_unchanged:
        blockers.append("authority_changed")
    if _v266_authority_explicitly_blocks(current):
        blockers.append("authority_blocked")
    if not scope_valid:
        blockers.append("scope_invalid")
    if not dnt_valid:
        blockers.append("dnt_invalid")
    subject_changed = not subject_unchanged
    if terminal_state not in (None, "") or current.get("terminal_state") not in (None, ""):
        blockers.append("terminal_state")
    if remaining < max(0, _safe_int(safety_floor, MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION)):
        blockers.append("insufficient_remaining_budget")
    if blockers:
        current = reset_recovery_no_mutation_search_state(
            current, reason=";".join(blockers)
        )
        current["last_no_mutation_search_blockers"] = blockers[:16]
        return {
            **_result(RECOVERY_NO_MUTATION_SEARCH_BLOCKED),
            "state": current,
            "blockers": blockers[:16],
            "reason": blockers[0],
            "reset": True,
        }

    # A changed subject starts a new window. The current non-mutating
    # interaction may be the first observation in that window, but it can
    # never inherit the old subject's count.
    if subject_changed:
        current["current_subject_hash"] = subject
        current = reset_recovery_no_mutation_search_state(
            current, reason="subject_changed"
        )
        current["current_subject_hash"] = subject

    authority_identity = _get(
        current, "authority_state_identity", "recovery_authorization_hash",
        "authority_hash", default="",
    )
    if not authority_identity and isinstance(
        current.get("recovery_authorization"), dict
    ):
        authority = current["recovery_authorization"]
        authority_identity = (
            authority.get("authorization_hash")
            or authority.get("plan_hash")
            or canonical_hash({
                key: authority.get(key)
                for key in (
                    "authorization_id", "plan_id", "approval_receipt_hash",
                    "verification_digest", "authority_delta_empty",
                    "user_reapproval_required",
                )
                if key in authority
            })
        )
    window_key = (
        execution, attempt, epoch, target.casefold(), subject,
        _v266_legal_space_identity(legal), _text(authority_identity, 160),
    )
    previous_key = tuple(current.get("no_mutation_search_window_key") or ())
    if previous_key != window_key:
        current["no_mutation_search_interaction_count"] = 0
        current["no_mutation_search_window_first_event_id"] = None
        current["no_mutation_search_window_key"] = window_key
        current["no_mutation_search_window_ordinal"] = max(
            1, _safe_int(current.get("no_mutation_search_window_ordinal"), 1)
        )
    count = max(
        0,
        _safe_int(current.get("no_mutation_search_interaction_count"), 0),
    ) + 1
    current["no_mutation_search_interaction_count"] = count
    event_value = _text(event_id, 180) or (
        f"{execution}:search:{max(1, _safe_int(current.get('no_mutation_search_window_ordinal'), 1))}:{count}"
    )
    if not current.get("no_mutation_search_window_first_event_id"):
        current["no_mutation_search_window_first_event_id"] = event_value
    pattern = build_recovery_no_mutation_search_pattern(
        execution,
        recovery_attempt_index=attempt,
        strategy_epoch=epoch,
        target_path=target,
        subject_identity=subject,
        legal_mutation_mechanisms=legal,
        interaction_count=count,
        mutation_attempts=0,
        commit_count=0,
        provider_healthy=bool(provider_healthy),
        provider_harness_blocked=bool(provider_harness_blocked),
        tool_steps_used=used_steps,
        tool_steps_remaining=max(0, remaining),
        first_interaction_event_id=current.get("no_mutation_search_window_first_event_id"),
        latest_interaction_event_id=event_value,
        behavior_changing_mission_unresolved=bool(behavior_changing_mission_unresolved),
        current_target_known=bool(current_target_known),
        subject_unchanged=True,
        scope_valid=bool(scope_valid),
        dnt_valid=bool(dnt_valid),
        authority_unchanged=bool(authority_unchanged),
        legal_mutation_space_available=True,
    )
    current["no_mutation_search_pattern"] = pattern
    current["no_mutation_search_patterns"] = (
        list(current.get("no_mutation_search_patterns", [])) + [pattern]
    )[-32:]
    interaction = build_recovery_no_mutation_search_interaction(
        execution,
        event_id=event_value,
        tool_name=name,
        recovery_attempt_index=attempt,
        strategy_epoch=epoch,
        target_path=target,
        subject_identity=subject,
        interaction_count=count,
        tool_steps_used=used_steps,
        tool_steps_remaining=max(0, remaining),
    )
    current["no_mutation_search_interaction_events"] = (
        list(current.get("no_mutation_search_interaction_events", [])) + [interaction]
    )[-32:]
    if count < MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION:
        return _result(
            RECOVERY_NO_MUTATION_SEARCH_PROGRESS,
            counted=True,
            interaction_count=count,
            pattern=pattern,
            interaction=interaction,
        )

    detected = detect_recovery_no_mutation_search_stagnation(pattern)
    if not detected.get("detected"):
        return _result(
            RECOVERY_NO_MUTATION_SEARCH_NOT_COUNTED,
            counted=True,
            interaction_count=count,
            pattern=pattern,
            interaction=interaction,
        )

    used = max(0, _safe_int(current.get("mutation_path_reorientations_used"), 0))
    maximum = min(
        MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        max(0, _safe_int(
            current.get("max_mutation_path_reorientations"),
            MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        )),
    )
    if used >= maximum:
        if not current.get("no_mutation_search_exhausted"):
            exhaustion = {
                "artifact_type": RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED,
                "recovery_execution_id": execution,
                "recovery_attempt_index": attempt,
                "strategy_epoch": epoch,
                "pattern_hash": pattern.get("canonical_hash"),
                "interaction_count": count,
                "reorientations_used": used,
                "reorientation_budget": maximum,
                "target_path": target,
                "subject_identity": subject,
                "worker_prose_authority": 0,
                "canonical_hash": "",
            }
            exhaustion["canonical_hash"] = canonical_hash(
                _without(exhaustion, "canonical_hash")
            )
            current["no_mutation_search_exhaustion_evidence"] = _freeze_record(
                RecoveryNoMutationSearchPattern, exhaustion
            )
            current["no_mutation_search_exhausted"] = True
            current["no_mutation_search_terminal_state"] = RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED
        return _result(
            RECOVERY_NO_MUTATION_SEARCH_EXHAUSTED,
            counted=True,
            interaction_count=count,
            pattern=pattern,
            interaction=interaction,
            exhausted=True,
            adaptation_budget_exhausted=True,
        )

    # A reorientation starts a fresh local search window.  The triggering
    # pattern remains immutable evidence; the counter itself does not leak
    # into the next window or across an epoch/Worker boundary.
    current_for_context = _copy(current)
    current_for_context["remaining_tool_steps"] = max(0, remaining)
    context = build_recovery_mutation_path_reorientation_context(
        current_for_context,
        pattern=pattern,
        target_path=target,
        legal_mutation_mechanisms=legal,
        current_source_hash=current_source_hash,
    )
    current["mutation_path_reorientations_used"] = used + 1
    current["last_mutation_path_reorientation_context"] = context
    event = build_recovery_mutation_path_reorientation_event(
        current,
        trigger_pattern=pattern,
        target_path=target,
        subject_identity=subject,
        legal_mutation_mechanisms=legal,
        tool_steps_used=used_steps,
        tool_steps_remaining=max(0, remaining),
        reorientation_ordinal=used + 1,
        model_visible_context=context,
        active_tool_schema_hash=active_tool_schema_hash,
    )
    current["mutation_path_reorientation_events"] = (
        list(current.get("mutation_path_reorientation_events", [])) + [event]
    )[-MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS:]
    current["last_mutation_path_reorientation"] = event
    current["no_mutation_search_interaction_count"] = 0
    current["no_mutation_search_window_key"] = None
    current["no_mutation_search_window_first_event_id"] = None
    current["no_mutation_search_window_ordinal"] = max(
        1, _safe_int(current.get("no_mutation_search_window_ordinal"), 1)
    ) + 1
    current["no_mutation_search_reset_reason"] = "reorientation"
    return {
        **_result(RECOVERY_NO_MUTATION_SEARCH_STAGNATION),
        "state": current,
        "counted": True,
        "interaction_count": count,
        "pattern": pattern,
        "interaction": interaction,
        "reoriented": True,
        "event": event,
        "feedback": context,
        "exhausted": False,
        "reorientation_ordinal": used + 1,
    }


# Compatibility/discoverability spellings for callers that use the V26.6
# nouns directly.  They all retain the same immutable records and one-shot
# state machine; none creates a new Worker or changes authority.
observe_recovery_no_mutation_search = observe_recovery_no_mutation_search_interaction
evaluate_recovery_no_mutation_search = observe_recovery_no_mutation_search_interaction
decide_recovery_no_mutation_search = observe_recovery_no_mutation_search_interaction
record_recovery_no_mutation_search_interaction = observe_recovery_no_mutation_search_interaction
record_recovery_no_mutation_search = observe_recovery_no_mutation_search_interaction
detect_no_mutation_search_stagnation = detect_recovery_no_mutation_search_stagnation
build_recovery_mutation_path_reorientation = build_recovery_mutation_path_reorientation_event
build_mutation_path_reorientation = build_recovery_mutation_path_reorientation_event
validate_recovery_mutation_path_reorientation = validate_recovery_mutation_path_reorientation_event
reset_no_mutation_search_state = reset_recovery_no_mutation_search_state


def build_recovery_strategy_failure_pattern(
    recovery_execution_id: str,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    target_path: str | None = None,
    mutation_mechanism: str | None = None,
    failure_class: str = SYNTAX_INVALID_MUTATION,
    failure_count: int = 1,
    commit_count: int = 0,
    subject_identity_before: Any = None,
    subject_identity_after: Any = None,
    subject_unchanged: bool | None = None,
    latest_deterministic_diagnostic: Any = "",
    available_legal_mechanisms: Iterable[str] | None = None,
    **kwargs: Any,
) -> RecoveryStrategyFailurePattern:
    """Create immutable canonical evidence for one failure sequence."""
    strategy_epoch = kwargs.get("epoch", strategy_epoch)
    target_path = target_path or kwargs.get("target") or kwargs.get("path")
    mutation_mechanism = mutation_mechanism or kwargs.get("mechanism") or kwargs.get("tool")
    failure_class = kwargs.get("failure_type") or kwargs.get("category") or failure_class
    before = _strategy_subject_identity(
        subject_identity_before if subject_identity_before is not None else kwargs.get("subject_before")
    )
    after = _strategy_subject_identity(
        subject_identity_after if subject_identity_after is not None else kwargs.get("subject_after")
    )
    if subject_unchanged is None:
        subject_unchanged = (before == after) if before is not None or after is not None else True
    count = max(0, _safe_int(
        kwargs.get(
            "consecutive_failure_count",
            kwargs.get("consecutive_failures", failure_count),
        ) or 0,
        0,
    ))
    commits = max(0, _safe_int(commit_count or kwargs.get("commits", 0) or 0, 0))
    mechanisms = available_legal_mechanisms
    if mechanisms is None:
        mechanisms = kwargs.get("available_mechanisms") or kwargs.get("legal_alternatives") or []
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_STRATEGY_FAILURE_PATTERN,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "strategy_epoch": _safe_int(strategy_epoch, RECOVERY_STRATEGY_EPOCH_0),
        "target_path": _path(target_path),
        "target": _path(target_path),
        "mutation_mechanism": _text(mutation_mechanism, 120),
        "mechanism": _text(mutation_mechanism, 120),
        "failure_class": _text(failure_class, 120),
        "failure_count": count,
        "consecutive_failure_count": count,
        "commit_count": commits,
        "subject_identity_before": before,
        "subject_identity_after": after,
        "subject_before": before,
        "subject_after": after,
        "subject_unchanged": bool(subject_unchanged),
        "latest_deterministic_diagnostic": _text(latest_deterministic_diagnostic, 900),
        "latest_diagnostic": _text(latest_deterministic_diagnostic, 900),
        "available_legal_mechanisms": _unique_strings(mechanisms, limit=24),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryStrategyFailurePattern, value)  # type: ignore[return-value]


build_recovery_failure_pattern = build_recovery_strategy_failure_pattern
create_recovery_strategy_failure_pattern = build_recovery_strategy_failure_pattern
RecoveryFailurePattern = RecoveryStrategyFailurePattern


def validate_recovery_strategy_failure_pattern(
    pattern: dict[str, Any] | None,
) -> dict[str, Any]:
    value = pattern if isinstance(pattern, dict) else {}
    expected = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("strategy failure pattern schema version is invalid")
    if value.get("artifact_type") != RECOVERY_STRATEGY_FAILURE_PATTERN:
        errors.append("strategy failure pattern artifact type is invalid")
    if value.get("canonical_hash") != expected:
        errors.append("strategy failure pattern hash is invalid")
    for key in ("recovery_execution_id", "target_path", "mutation_mechanism", "failure_class"):
        if not value.get(key):
            errors.append(f"strategy failure pattern is missing {key}")
    failure_count = _safe_int(value.get("failure_count"), -1)
    commit_count = _safe_int(value.get("commit_count"), -1)
    epoch = _safe_int(value.get("strategy_epoch"), -1)
    if epoch not in {RECOVERY_STRATEGY_EPOCH_0, RECOVERY_STRATEGY_EPOCH_1}:
        errors.append("strategy failure pattern epoch is invalid")
    if failure_count < 0:
        errors.append("strategy failure count is invalid")
    if commit_count < 0:
        errors.append("strategy commit count is invalid")
    if value.get("worker_prose_authority") != 0:
        errors.append("strategy failure pattern grants Worker prose authority")
    if value.get("subject_unchanged") is True and value.get("subject_identity_before") != value.get("subject_identity_after"):
        errors.append("unchanged strategy pattern has different subject identities")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_mutation_strategy(
    recovery_execution_id: str,
    strategy_epoch: int = RECOVERY_STRATEGY_EPOCH_0,
    target_path: str | None = None,
    allowed_mutation_mechanisms: Iterable[str] | None = None,
    suppressed_mutation_mechanisms: Iterable[str] | None = None,
    source_subject_identity: Any = None,
    transition_reason: str = "initial recovery strategy",
    recovery_authorization: dict[str, Any] | None = None,
    **kwargs: Any,
) -> RecoveryMutationStrategy:
    """Create one stable strategy identity without changing authority."""
    auth = recovery_authorization if isinstance(recovery_authorization, dict) else {}
    strategy_epoch = kwargs.get("epoch", strategy_epoch)
    target_path = target_path or kwargs.get("target") or kwargs.get("path")
    allowed = _unique_strings(
        allowed_mutation_mechanisms if allowed_mutation_mechanisms is not None else kwargs.get("allowed_tools", []),
        limit=24,
    )
    suppressed = _unique_strings(
        suppressed_mutation_mechanisms if suppressed_mutation_mechanisms is not None else kwargs.get("suppressed_tools", []),
        limit=24,
    )
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_MUTATION_STRATEGY,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "strategy_epoch": _safe_int(strategy_epoch, RECOVERY_STRATEGY_EPOCH_0),
        "target_path": _path(target_path),
        "target": _path(target_path),
        "allowed_mutation_mechanisms": allowed,
        "suppressed_mutation_mechanisms": suppressed,
        "current_mutation_mechanism": _text(
            kwargs.get("current_mutation_mechanism") or kwargs.get("mechanism"), 120
        ) or None,
        "source_subject_identity": _strategy_subject_identity(source_subject_identity),
        "transition_reason": _text(transition_reason, 900),
        "recovery_authorization_id": auth.get("authorization_id") or kwargs.get("recovery_authorization_id"),
        "recovery_authorization_hash": auth.get("authorization_hash") or kwargs.get("recovery_authorization_hash"),
        "plan_hash": auth.get("plan_hash") or kwargs.get("plan_hash"),
        "approval_receipt_hash": auth.get("approval_receipt_hash") or kwargs.get("approval_receipt_hash"),
        "recovery_attempt_index": max(1, _safe_int(kwargs.get("recovery_attempt_index", 1) or 1, 1)),
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryMutationStrategy, value)  # type: ignore[return-value]


build_recovery_strategy = build_recovery_mutation_strategy
create_recovery_mutation_strategy = build_recovery_mutation_strategy


def validate_recovery_mutation_strategy(
    strategy: dict[str, Any] | None,
) -> dict[str, Any]:
    value = strategy if isinstance(strategy, dict) else {}
    expected = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("recovery mutation strategy schema version is invalid")
    if value.get("artifact_type") != RECOVERY_MUTATION_STRATEGY:
        errors.append("recovery mutation strategy artifact type is invalid")
    if value.get("canonical_hash") != expected:
        errors.append("recovery mutation strategy hash is invalid")
    for key in ("recovery_execution_id", "target_path", "allowed_mutation_mechanisms"):
        if key not in value:
            errors.append(f"recovery mutation strategy is missing {key}")
    if value.get("worker_prose_authority") != 0:
        errors.append("recovery mutation strategy grants Worker prose authority")
    epoch = _safe_int(value.get("strategy_epoch"), -1)
    if epoch not in {RECOVERY_STRATEGY_EPOCH_0, RECOVERY_STRATEGY_EPOCH_1}:
        errors.append("recovery strategy epoch is invalid")
    suppressed = {str(item).casefold() for item in value.get("suppressed_mutation_mechanisms", []) or []}
    if suppressed.intersection({str(item).casefold() for item in value.get("allowed_mutation_mechanisms", []) or []}):
        errors.append("suppressed mutation mechanism remains allowed")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def decide_recovery_strategy_diversification(
    failure_pattern: dict[str, Any] | None,
    *,
    current_strategy: dict[str, Any] | None = None,
    recovery_authorization: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    available_legal_mechanisms: Iterable[str] | None = None,
    recovery_execution_id: str | None = None,
    current_subject_hash: Any = None,
    strategy_switch_count: int = 0,
    max_strategy_switches: int = MAX_RECOVERY_STRATEGY_SWITCHES,
    authority_delta: dict[str, Any] | None = None,
    alternative_requires_authority: bool = False,
    **kwargs: Any,
) -> RecoveryStrategyDiversificationDecision:
    """Decide whether one local mutation-strategy switch is authorized."""
    current_strategy = current_strategy or kwargs.get("strategy")
    recovery_authorization = recovery_authorization or kwargs.get("authorization")
    if available_legal_mechanisms is None:
        available_legal_mechanisms = kwargs.get("available_alternatives")
    recovery_execution_id = recovery_execution_id or kwargs.get("execution_id")
    if current_subject_hash is None:
        current_subject_hash = kwargs.get("current_subject")
    strategy_switch_count = kwargs.get("switch_count", strategy_switch_count)
    max_strategy_switches = kwargs.get("max_switches", max_strategy_switches)
    pattern = failure_pattern if isinstance(failure_pattern, dict) else {}
    strategy = current_strategy if isinstance(current_strategy, dict) else {}
    auth = recovery_authorization if isinstance(recovery_authorization, dict) else {}
    lineage_value = lineage if isinstance(lineage, dict) else {}
    pattern_check = validate_recovery_strategy_failure_pattern(pattern)
    alternatives = _unique_strings(
        available_legal_mechanisms
        if available_legal_mechanisms is not None
        else pattern.get("available_legal_mechanisms", []),
        limit=24,
    )
    current_mechanism = _text(
        pattern.get("mutation_mechanism") or pattern.get("mechanism")
        or strategy.get("current_mutation_mechanism"), 120,
    )
    strategy_mechanism = _text(strategy.get("current_mutation_mechanism"), 120)
    mechanism_ok = not strategy_mechanism or strategy_mechanism.casefold() == current_mechanism.casefold()
    suppressed = {
        str(item).casefold() for item in strategy.get("suppressed_mutation_mechanisms", []) or []
    }
    alternatives = [
        item for item in alternatives
        if item.casefold() != current_mechanism.casefold()
        and item.casefold() not in suppressed
    ]
    epoch = _safe_int(pattern.get("strategy_epoch", strategy.get("strategy_epoch", 0)) or 0, -1)
    strategy_epoch = _safe_int(strategy.get("strategy_epoch"), epoch)
    switch_count = max(0, _safe_int(strategy_switch_count or 0, 0))
    maximum = min(
        MAX_RECOVERY_STRATEGY_SWITCHES,
        max(0, _safe_int(max_strategy_switches, MAX_RECOVERY_STRATEGY_SWITCHES)),
    )
    reasons: list[str] = []
    state = STRATEGY_SWITCH_NOT_EVALUABLE
    ready = False
    subject = _strategy_subject_identity(current_subject_hash)
    pattern_subject = _strategy_subject_identity(pattern.get("subject_identity_after"))
    subject_ok = pattern.get("subject_unchanged") is True
    if subject is not None and pattern_subject is not None:
        subject_ok = subject_ok and subject == pattern_subject
    strategy_subject = _strategy_subject_identity(strategy.get("source_subject_identity"))
    if subject is not None and strategy_subject is not None:
        subject_ok = subject_ok and subject == strategy_subject
    execution_ok = not recovery_execution_id or (
        recovery_execution_id == pattern.get("recovery_execution_id")
        and (
            not strategy.get("recovery_execution_id")
            or recovery_execution_id == strategy.get("recovery_execution_id")
        )
    )
    pattern_target = _path(pattern.get("target_path") or pattern.get("target"))
    strategy_target = _path(strategy.get("target_path") or strategy.get("target"))
    target_ok = not strategy_target or pattern_target.casefold() == strategy_target.casefold()
    epoch_ok = strategy_epoch == epoch
    stagnation = bool(
        pattern_check.get("valid")
        and pattern.get("failure_class") == SYNTAX_INVALID_MUTATION
        and pattern.get("subject_unchanged") is True
        and _safe_int(pattern.get("commit_count"), -1) == 0
        and _safe_int(pattern.get("failure_count"), -1) >= RECOVERY_STRATEGY_STAGNATION_THRESHOLD
    )
    authority_ok = True
    if authority_delta is not None and isinstance(authority_delta, dict) and authority_delta.get("empty") is not True:
        authority_ok = False
        reasons.append("authority delta is not empty")
    if auth:
        if auth.get("status") == RECOVERY_AUTHORIZATION_BLOCKED or auth.get("user_reapproval_required") is True:
            authority_ok = False
            reasons.append("recovery authorization is blocked or requires reapproval")
        if auth.get("authority_delta_empty") is False:
            authority_ok = False
            reasons.append("recovery authorization has a non-empty authority delta")
        for auth_key, strategy_key in (
            ("authorization_id", "recovery_authorization_id"),
            ("authorization_hash", "recovery_authorization_hash"),
            ("plan_hash", "plan_hash"),
            ("approval_receipt_hash", "approval_receipt_hash"),
        ):
            expected = auth.get(auth_key)
            bound = strategy.get(strategy_key)
            if expected not in (None, "") and bound not in (None, "") and expected != bound:
                authority_ok = False
                reasons.append(f"recovery authorization binding changed: {auth_key}")
    if lineage_value and (
        lineage_value.get("valid") is False
        or lineage_value.get("status") == INVALID_AUTHORIZED_EXECUTION_DESCENDANT
    ):
        authority_ok = False
        reasons.append("authorized execution lineage is invalid")
    if alternative_requires_authority:
        authority_ok = False
        reasons.append("the available alternative requires new authority")

    if not pattern_check.get("valid"):
        reasons.append("failure pattern is invalid")
    elif not execution_ok:
        reasons.append("recovery execution identity changed")
    elif not target_ok:
        reasons.append("recovery target changed")
    elif not epoch_ok:
        reasons.append("recovery strategy epoch changed")
    elif not mechanism_ok:
        reasons.append("recovery mutation mechanism changed")
    elif pattern.get("failure_class") != SYNTAX_INVALID_MUTATION:
        reasons.append("failure class is outside the V26.3 syntax trigger")
    elif not subject_ok:
        reasons.append("subject was not unchanged across the failure sequence")
    elif _safe_int(pattern.get("commit_count", 0) or 0, 0) != 0:
        reasons.append("a mutation commit occurred in the sequence")
    elif _safe_int(pattern.get("failure_count", 0) or 0, 0) < RECOVERY_STRATEGY_STAGNATION_THRESHOLD:
        state = NO_SWITCH_REQUIRED
        reasons.append("stagnation threshold has not been reached")
    elif not authority_ok:
        state = STRATEGY_SWITCH_BLOCKED_AUTHORITY
    elif switch_count >= maximum:
        state = STRATEGY_SWITCH_BUDGET_EXHAUSTED
        reasons.append("the bounded strategy-switch budget is exhausted")
    elif not alternatives:
        state = STRATEGY_SWITCH_UNAVAILABLE
        reasons.append("no unused legal mutation mechanism is available")
    else:
        state = STRATEGY_SWITCH_READY
        ready = True
        reasons.append("one unused legal mutation mechanism is available")
    next_epoch = epoch + 1 if ready else epoch
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_STRATEGY_DIVERSIFICATION_DECISION,
        "decision": state,
        "status": state,
        "stagnation_detected": stagnation,
        "switch_allowed": ready,
        "recovery_execution_id": pattern.get("recovery_execution_id") or recovery_execution_id,
        "current_strategy_epoch": epoch,
        "next_strategy_epoch": next_epoch,
        "strategy_switch_count": switch_count,
        "max_strategy_switches": maximum,
        "current_mutation_mechanism": current_mechanism,
        "selected_alternative": alternatives[0] if ready else None,
        "available_legal_mechanisms": alternatives,
        "pattern_hash": pattern.get("canonical_hash"),
        "recovery_authorization_id": auth.get("authorization_id"),
        "recovery_authorization_hash": auth.get("authorization_hash"),
        "authority_delta_empty": authority_delta.get("empty") if isinstance(authority_delta, dict) else auth.get("authority_delta_empty", True),
        "USER_REAPPROVAL_REQUIRED": False if authority_ok else True,
        "reasons": list(dict.fromkeys(reasons))[:12],
        "worker_prose_authority": 0,
        "canonical_hash": "",
    }
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash"))
    return _freeze_record(RecoveryStrategyDiversificationDecision, value)  # type: ignore[return-value]


decide_recovery_strategy = decide_recovery_strategy_diversification
evaluate_recovery_strategy = decide_recovery_strategy_diversification
build_recovery_strategy_diversification_decision = decide_recovery_strategy_diversification
create_recovery_strategy_diversification_decision = decide_recovery_strategy_diversification


def validate_recovery_strategy_diversification_decision(
    decision: dict[str, Any] | None,
) -> dict[str, Any]:
    """Validate one immutable local switch decision without executing it."""
    value = decision if isinstance(decision, dict) else {}
    expected = canonical_hash(_without(value, "canonical_hash")) if value else None
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("strategy decision schema version is invalid")
    if value.get("artifact_type") != RECOVERY_STRATEGY_DIVERSIFICATION_DECISION:
        errors.append("strategy decision artifact type is invalid")
    if value.get("canonical_hash") != expected:
        errors.append("strategy decision hash is invalid")
    allowed_states = {
        NO_SWITCH_REQUIRED,
        STRATEGY_SWITCH_READY,
        STRATEGY_SWITCH_UNAVAILABLE,
        STRATEGY_SWITCH_BLOCKED_AUTHORITY,
        STRATEGY_SWITCH_BUDGET_EXHAUSTED,
        STRATEGY_SWITCH_NOT_EVALUABLE,
    }
    if value.get("decision") not in allowed_states:
        errors.append("strategy decision state is invalid")
    if value.get("worker_prose_authority") != 0:
        errors.append("strategy decision grants Worker prose authority")
    current_epoch = _safe_int(value.get("current_strategy_epoch"), -1)
    next_epoch = _safe_int(value.get("next_strategy_epoch"), -1)
    if current_epoch not in {RECOVERY_STRATEGY_EPOCH_0, RECOVERY_STRATEGY_EPOCH_1}:
        errors.append("current strategy epoch is invalid")
    if next_epoch not in {RECOVERY_STRATEGY_EPOCH_0, RECOVERY_STRATEGY_EPOCH_1}:
        errors.append("next strategy epoch is invalid")
    switch_count = _safe_int(value.get("strategy_switch_count"), -1)
    maximum = _safe_int(value.get("max_strategy_switches"), -1)
    if switch_count < 0 or maximum < 0 or maximum > MAX_RECOVERY_STRATEGY_SWITCHES:
        errors.append("strategy-switch budget is invalid")
    if value.get("decision") == STRATEGY_SWITCH_READY:
        if value.get("switch_allowed") is not True or not value.get("selected_alternative"):
            errors.append("ready decision has no selected alternative")
        if next_epoch != current_epoch + 1:
            errors.append("ready decision does not advance exactly one epoch")
    if value.get("decision") != STRATEGY_SWITCH_READY and value.get("switch_allowed") is True:
        errors.append("non-ready decision allows a switch")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "canonical_hash": value.get("canonical_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


validate_recovery_strategy_decision = validate_recovery_strategy_diversification_decision
validate_strategy_diversification_decision = validate_recovery_strategy_diversification_decision


def detect_recovery_strategy_stagnation(pattern: dict[str, Any] | None) -> dict[str, Any]:
    value = pattern if isinstance(pattern, dict) else {}
    valid = validate_recovery_strategy_failure_pattern(value)
    detected = bool(
        valid.get("valid")
        and value.get("failure_class") == SYNTAX_INVALID_MUTATION
        and _safe_int(value.get("failure_count", 0) or 0, 0) >= RECOVERY_STRATEGY_STAGNATION_THRESHOLD
        and _safe_int(value.get("commit_count", 0) or 0, 0) == 0
        and value.get("subject_unchanged") is True
    )
    return {
        "status": RECOVERY_STRATEGY_STAGNATION_DETECTED if detected else NO_SWITCH_REQUIRED,
        "detected": detected,
        "threshold": RECOVERY_STRATEGY_STAGNATION_THRESHOLD,
        "pattern_hash": value.get("canonical_hash"),
        "validation": valid,
        "model_calls": 0,
        "worker_calls": 0,
    }


def build_recovery_strategy_transition_feedback(
    pattern: dict[str, Any],
    decision: dict[str, Any],
    strategy: dict[str, Any],
    *,
    current_source_refreshed: bool = True,
    current_source_identity: Any = None,
    max_chars: int = 1800,
) -> str:
    """Render bounded transition facts, never a code patch or Worker prose."""
    pattern = pattern if isinstance(pattern, dict) else {}
    decision = decision if isinstance(decision, dict) else {}
    strategy = strategy if isinstance(strategy, dict) else {}
    remaining = decision.get("available_legal_mechanisms", []) or []
    text = (
        "RECOVERY STRATEGY TRANSITION\n"
        "The previous mutation mechanism repeatedly produced deterministic "
        "syntax-invalid candidates.\n"
        f"Target: {pattern.get('target_path') or pattern.get('target') or '(unknown)'}\n"
        f"Previous mechanism: {pattern.get('mutation_mechanism') or pattern.get('mechanism') or '(unknown)'}\n"
        f"Last deterministic error: {_text(pattern.get('latest_deterministic_diagnostic') or pattern.get('latest_diagnostic'), 420)}\n"
        f"Filesystem: {'unchanged' if pattern.get('subject_unchanged') else 'changed/unknown'}\n"
        f"Current source: {'refreshed/current' if current_source_refreshed else 'refresh unavailable'}\n"
        "Previous mechanism: temporarily exhausted for this strategy epoch\n"
        f"Remaining legal mutation mechanisms: {', '.join(map(str, remaining)) or '(none)'}\n"
        f"Strategy epoch: {int(decision.get('next_strategy_epoch', strategy.get('strategy_epoch', 1)) or 1)}\n"
        "Continue the SAME RecoveryMission. Choose the implementation; no code patch is prescribed."
    )
    if current_source_identity not in (None, ""):
        text += f"\nCurrent source identity: {_strategy_subject_identity(current_source_identity)}"
    return _text(text, max(256, int(max_chars)))


def refresh_recovery_strategy_source(
    state: dict[str, Any] | None,
    *,
    workspace: str | os.PathLike[str] | Path | None = None,
    target_path: str | None = None,
) -> dict[str, Any]:
    """Refresh current target metadata without injecting source content."""
    value = _copy(state) if isinstance(state, dict) else {}
    target = _path(target_path or value.get("target_path") or value.get("target"))
    result: dict[str, Any] = {
        "status": "REFRESHED",
        "target_path": target,
        "source_sha256": None,
        "source_chars": None,
        "source_available": False,
    }
    if workspace is not None and target:
        root = Path(workspace).resolve()
        try:
            path = (root / target).resolve()
            path.relative_to(root)
            payload = path.read_bytes()
        except (OSError, RuntimeError, ValueError):
            result["status"] = "REFRESH_UNAVAILABLE"
        else:
            result.update({
                "source_sha256": hashlib.sha256(payload).hexdigest(),
                "source_chars": len(payload.decode("utf-8", errors="replace")),
                "source_available": True,
            })
    value["current_source_refresh"] = result
    value["current_source_refreshed"] = result["status"] == "REFRESHED"
    return value


def create_recovery_strategy_state(
    recovery_execution_id: str,
    *,
    target_path: str,
    tool_schemas: Iterable[dict[str, Any]] | None = None,
    target_state: dict[str, Any] | None = None,
    current_subject_hash: Any = None,
    recovery_authorization: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    mutation_authority: dict[str, Any] | None = None,
    dnt: dict[str, Any] | None = None,
    execution_invariant_set: Any = None,
    precommit_gate: Any = None,
    available_legal_mechanisms: Iterable[str] | None = None,
    max_strategy_switches: int = MAX_RECOVERY_STRATEGY_SWITCHES,
    recovery_mission_id: str | None = None,
    completion_contract: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Initialize mutable orchestration state for one recovery Worker."""
    legal = (
        _unique_strings(available_legal_mechanisms, limit=24)
        if available_legal_mechanisms is not None
        else discover_legal_recovery_mutation_mechanisms(
            tool_schemas,
            target=target_path,
            target_state=target_state,
            mutation_authority=mutation_authority,
            authority=recovery_authorization,
            dnt=dnt,
            execution_invariant_set=execution_invariant_set,
            precommit_gate=precommit_gate,
        )
    )
    auth = recovery_authorization if isinstance(recovery_authorization, dict) else {}
    strategy = build_recovery_mutation_strategy(
        recovery_execution_id,
        strategy_epoch=RECOVERY_STRATEGY_EPOCH_0,
        target_path=target_path,
        allowed_mutation_mechanisms=legal,
        suppressed_mutation_mechanisms=[],
        source_subject_identity=current_subject_hash,
        recovery_authorization=auth,
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "recovery_execution_id": _text(recovery_execution_id, 160),
        "recovery_attempt_index": 1,
        "recovery_mission_id": _text(recovery_mission_id, 160) if recovery_mission_id else None,
        "strategy_epoch": RECOVERY_STRATEGY_EPOCH_0,
        "strategy_switch_count": 0,
        "max_strategy_switches": min(
            MAX_RECOVERY_STRATEGY_SWITCHES,
            max(0, _safe_int(max_strategy_switches, MAX_RECOVERY_STRATEGY_SWITCHES)),
        ),
        "target_path": _path(target_path),
        "current_subject_hash": _strategy_subject_identity(current_subject_hash),
        "target_state": _copy(target_state or {}),
        "recovery_authorization": _copy(auth),
        "lineage": _copy(lineage or {}),
        "mutation_authority": _copy(mutation_authority or {}),
        "dnt": _copy(dnt or {}),
        "current_strategy": strategy,
        "available_legal_mechanisms": legal,
        "suppressed_mutation_mechanisms": [],
        "consecutive_failure_count": 0,
        "last_failure_key": None,
        "last_failure_pattern": None,
        "strategy_failure_patterns": [],
        "strategy_switch_decisions": [],
        "strategy_epoch_starts": [{
            "artifact_type": RECOVERY_STRATEGY_EPOCH_START,
            "strategy_epoch": RECOVERY_STRATEGY_EPOCH_0,
            "recovery_execution_id": _text(recovery_execution_id, 160),
            "strategy_hash": strategy.get("canonical_hash"),
        }],
        "strategy_epoch_terminals": [],
        "strategy_search_summary": {
            "artifact_type": RECOVERY_STRATEGY_SEARCH_SUMMARY,
            "recovery_execution_id": _text(recovery_execution_id, 160),
            "switch_count": 0,
            "strategy_epochs": [RECOVERY_STRATEGY_EPOCH_0],
            "terminal_state": None,
        },
        "terminal_state": None,
        "current_source_refreshed": False,
        # V26.4 local tool-contract adaptation state.  These counters are
        # execution-local and intentionally do not participate in the
        # cross-run Brain or the V26.3 strategy-switch budget.
        "tool_contract_failure_count": 0,
        "last_tool_contract_failure_key": None,
        "last_tool_contract_failure_pattern": None,
        "tool_contract_failure_patterns": [],
        "tool_contract_guidance_events_used": 0,
        "tool_contract_guidance_events": [],
        "last_tool_contract_guidance": "",
        "suppressed_tool_request_count": 0,
        "last_suppressed_tool_request_key": None,
        "suppressed_tool_requests": [],
        "epoch_reanchors_used": 0,
        "epoch_reanchors": [],
        "last_epoch_reanchor": None,
        "last_epoch_reanchor_context": "",
        "completion_repairs_used": 0,
        "completion_repair_events": [],
        "last_completion_repair": None,
        "completion_contract": _copy(completion_contract or {}),
        # V26.6 execution-local no-mutation search control.  These fields are
        # independent of the V26.3 strategy and V26.4 adaptation budgets.
        "no_mutation_search_interaction_count": 0,
        "no_mutation_search_window_key": None,
        "no_mutation_search_window_first_event_id": None,
        "no_mutation_search_pattern": None,
        "no_mutation_search_patterns": [],
        "no_mutation_search_interaction_events": [],
        "no_mutation_search_reset_reason": None,
        "no_mutation_search_window_ordinal": 1,
        "mutation_path_reorientations_used": 0,
        "max_mutation_path_reorientations": MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        "mutation_path_reorientation_events": [],
        "last_mutation_path_reorientation": None,
        "last_mutation_path_reorientation_context": "",
        "no_mutation_search_exhausted": False,
        "no_mutation_search_exhaustion_evidence": None,
        "no_mutation_search_terminal_state": None,
        "recovery_mission_unresolved": True,
        "provider_healthy": True,
        "provider_harness_blocked": False,
        "authority_unchanged": True,
        "scope_valid": True,
        "dnt_valid": True,
        "current_target_known": bool(target_path),
        "legal_mutation_space_identity": _v266_legal_space_identity(legal),
    }


initialize_recovery_strategy_state = create_recovery_strategy_state
create_recovery_strategy_controller = create_recovery_strategy_state


def _strategy_failure_key(
    recovery_execution_id: Any,
    strategy_epoch: Any,
    target: Any,
    mechanism: Any,
    failure_class: Any,
    subject_before: Any,
    subject_after: Any,
    subject_unchanged: Any,
) -> tuple[Any, ...]:
    return (
        _text(recovery_execution_id, 160), int(strategy_epoch or 0), _path(target).casefold(),
        _text(mechanism, 120).casefold(), _text(failure_class, 120).casefold(),
        _strategy_subject_identity(subject_before), _strategy_subject_identity(subject_after),
        bool(subject_unchanged),
    )


def observe_recovery_mutation(
    state: dict[str, Any] | None,
    *,
    target_path: str | None = None,
    target: str | None = None,
    mutation_mechanism: str | None = None,
    mechanism: str | None = None,
    failure_class: str = SYNTAX_INVALID_MUTATION,
    diagnostic: Any = "",
    subject_identity_before: Any = None,
    subject_identity_after: Any = None,
    subject_unchanged: bool | None = None,
    committed: bool = False,
    commit_count: int = 0,
    available_legal_mechanisms: Iterable[str] | None = None,
    tool_schemas: Iterable[dict[str, Any]] | None = None,
    target_state: dict[str, Any] | None = None,
    authority_delta: dict[str, Any] | None = None,
    alternative_requires_authority: bool = False,
) -> dict[str, Any]:
    """Record one mutation result and optionally enter epoch 1."""
    current = _copy(state) if isinstance(state, dict) else {}
    # Any recognized mutation invocation owns the no-mutation search window,
    # including a candidate that later fails syntax, V25.5, transaction, or
    # commit validation.  Keep the reset here as well as at the Worker seam
    # so provider-free callers cannot accidentally carry a stale V26.6 count.
    current = reset_recovery_no_mutation_search_state(
        current, reason="mutation_observation"
    )
    execution_id = current.get("recovery_execution_id") or "RECOVERY-EXEC-UNKNOWN"
    epoch = _safe_int(current.get("strategy_epoch", 0) or 0, RECOVERY_STRATEGY_EPOCH_0)
    target_value = _path(target_path or target or current.get("target_path"))
    mechanism_value = _text(mutation_mechanism or mechanism, 120)
    before = _strategy_subject_identity(
        subject_identity_before if subject_identity_before is not None else current.get("current_subject_hash")
    )
    after = _strategy_subject_identity(
        subject_identity_after if subject_identity_after is not None else before
    )
    if subject_unchanged is None:
        subject_unchanged = before == after
    key = _strategy_failure_key(
        execution_id, epoch, target_value, mechanism_value, failure_class, before, after, subject_unchanged,
    )
    previous_key = tuple(current.get("last_failure_key") or ())
    previous_count = max(0, _safe_int(current.get("consecutive_failure_count", 0) or 0, 0))
    same_sequence = bool(not committed and previous_key == key)
    count = previous_count + 1 if same_sequence else (0 if committed else 1)
    if committed:
        count = 0
    mechanisms = available_legal_mechanisms
    if mechanisms is None:
        mechanisms = current.get("available_legal_mechanisms", [])
    if tool_schemas is not None:
        derived = discover_legal_recovery_mutation_mechanisms(
            tool_schemas,
            target=target_value,
            target_state=target_state or current.get("target_state"),
            mutation_authority=current.get("mutation_authority"),
            authority=current.get("recovery_authorization"),
            dnt=current.get("dnt"),
        )
        mechanisms = derived
    pattern = build_recovery_strategy_failure_pattern(
        execution_id,
        strategy_epoch=epoch,
        target_path=target_value,
        mutation_mechanism=mechanism_value,
        failure_class=failure_class,
        failure_count=count,
        commit_count=commit_count,
        subject_identity_before=before,
        subject_identity_after=after,
        subject_unchanged=subject_unchanged,
        latest_deterministic_diagnostic=diagnostic,
        available_legal_mechanisms=mechanisms,
    )
    strategy = current.get("current_strategy") if isinstance(current.get("current_strategy"), dict) else {}
    decision = decide_recovery_strategy_diversification(
        pattern,
        current_strategy=strategy,
        recovery_authorization=current.get("recovery_authorization"),
        lineage=current.get("lineage"),
        available_legal_mechanisms=mechanisms,
        recovery_execution_id=execution_id,
        current_subject_hash=after,
        strategy_switch_count=max(0, _safe_int(current.get("strategy_switch_count", 0) or 0, 0)),
        max_strategy_switches=min(
            MAX_RECOVERY_STRATEGY_SWITCHES,
            max(0, _safe_int(
                current.get("max_strategy_switches", MAX_RECOVERY_STRATEGY_SWITCHES) or 0,
                0,
            )),
        ),
        authority_delta=authority_delta,
        alternative_requires_authority=alternative_requires_authority,
    )
    current["consecutive_failure_count"] = count
    current["last_failure_key"] = key if not committed else None
    current["last_failure_pattern"] = pattern
    current.setdefault("strategy_failure_patterns", []).append(pattern)
    current.setdefault("strategy_switch_decisions", []).append(decision)
    current["strategy_failure_patterns"] = current["strategy_failure_patterns"][-16:]
    current["strategy_switch_decisions"] = current["strategy_switch_decisions"][-16:]
    switched = decision.get("decision") == STRATEGY_SWITCH_READY and epoch == RECOVERY_STRATEGY_EPOCH_0
    transition_feedback = ""
    if switched:
        selected = decision.get("selected_alternative")
        new_epoch = _safe_int(decision.get("next_strategy_epoch", epoch + 1) or epoch + 1, epoch + 1)
        new_allowed = [
            item for item in _unique_strings(mechanisms, limit=24)
            if item.casefold() != mechanism_value.casefold()
        ]
        new_strategy = build_recovery_mutation_strategy(
            execution_id,
            strategy_epoch=new_epoch,
            target_path=target_value,
            allowed_mutation_mechanisms=new_allowed,
            suppressed_mutation_mechanisms=[mechanism_value],
            source_subject_identity=after,
            current_mutation_mechanism=selected,
            transition_reason=(
                f"{RECOVERY_STRATEGY_STAGNATION_DETECTED}: switch from {mechanism_value} "
                f"to unused legal mechanism {selected}"
            ),
            recovery_authorization=current.get("recovery_authorization"),
            recovery_attempt_index=current.get("recovery_attempt_index", 1),
        )
        current["strategy_epoch"] = new_epoch
        current["strategy_switch_count"] = min(
            MAX_RECOVERY_STRATEGY_SWITCHES,
            max(0, _safe_int(current.get("strategy_switch_count", 0) or 0, 0)) + 1,
        )
        current["current_strategy"] = new_strategy
        current["suppressed_mutation_mechanisms"] = [mechanism_value]
        current["consecutive_failure_count"] = 0
        current["last_failure_key"] = None
        current["current_subject_hash"] = after
        current = reset_recovery_no_mutation_search_state(
            current, reason="strategy_epoch_change"
        )
        transition_feedback = build_recovery_strategy_transition_feedback(
            pattern,
            decision,
            new_strategy,
            current_source_refreshed=bool(current.get("current_source_refreshed", True)),
            current_source_identity=after,
        )
        current["last_transition_feedback"] = transition_feedback
        current.setdefault("strategy_epoch_starts", []).append({
            "artifact_type": RECOVERY_STRATEGY_EPOCH_START,
            "strategy_epoch": new_epoch,
            "recovery_execution_id": execution_id,
            "strategy_hash": new_strategy.get("canonical_hash"),
            "transition_reason": new_strategy.get("transition_reason"),
        })
    elif (
        epoch >= RECOVERY_STRATEGY_EPOCH_1
        and decision.get("stagnation_detected")
        and decision.get("decision") in {
            STRATEGY_SWITCH_BUDGET_EXHAUSTED,
            STRATEGY_SWITCH_UNAVAILABLE,
            STRATEGY_SWITCH_BLOCKED_AUTHORITY,
        }
    ):
        current["terminal_state"] = RECOVERY_STRATEGY_SEARCH_EXHAUSTED
        current.setdefault("strategy_epoch_terminals", []).append({
            "artifact_type": RECOVERY_STRATEGY_EPOCH_TERMINAL,
            "recovery_execution_id": execution_id,
            "strategy_epoch": epoch,
            "terminal_state": RECOVERY_STRATEGY_SEARCH_EXHAUSTED,
            "decision": decision.get("decision"),
            "pattern_hash": pattern.get("canonical_hash"),
        })
    if committed and epoch >= RECOVERY_STRATEGY_EPOCH_1:
        already_closed = any(
            isinstance(item, dict)
            and item.get("strategy_epoch") == epoch
            and item.get("terminal_state") == RECOVERY_STRATEGY_COMMITTED
            for item in current.get("strategy_epoch_terminals", [])
        )
        if not already_closed:
            current.setdefault("strategy_epoch_terminals", []).append({
                "artifact_type": RECOVERY_STRATEGY_EPOCH_TERMINAL,
                "recovery_execution_id": execution_id,
                "strategy_epoch": epoch,
                "terminal_state": RECOVERY_STRATEGY_COMMITTED,
                "decision": RECOVERY_STRATEGY_COMMITTED,
                "pattern_hash": pattern.get("canonical_hash"),
            })
    if committed and after is not None:
        current["current_subject_hash"] = after
    current["strategy_search_summary"] = {
        "artifact_type": RECOVERY_STRATEGY_SEARCH_SUMMARY,
        "recovery_execution_id": execution_id,
        "switch_count": max(0, _safe_int(current.get("strategy_switch_count", 0) or 0, 0)),
        "strategy_epochs": sorted({
            _safe_int(item.get("strategy_epoch", 0) or 0, 0)
            for item in current.get("strategy_epoch_starts", []) if isinstance(item, dict)
        }),
        "terminal_state": current.get("terminal_state"),
        "last_outcome": (
            RECOVERY_STRATEGY_COMMITTED
            if committed and epoch >= RECOVERY_STRATEGY_EPOCH_1
            else current.get("terminal_state")
        ),
        "failure_pattern_count": len(current.get("strategy_failure_patterns", [])),
        "decision_count": len(current.get("strategy_switch_decisions", [])),
        "worker_prose_authority": 0,
    }
    return {
        "state": current,
        "pattern": pattern,
        "stagnation": detect_recovery_strategy_stagnation(pattern),
        "decision": decision,
        "switched": switched,
        "transition_feedback": transition_feedback,
        "terminal_state": current.get("terminal_state"),
        "strategy": current.get("current_strategy"),
    }


observe_recovery_mutation_result = observe_recovery_mutation
record_recovery_mutation_observation = observe_recovery_mutation


def recovery_strategy_state_projection(state: dict[str, Any] | None) -> dict[str, Any]:
    """Return bounded internal strategy evidence without model transcript."""
    value = state if isinstance(state, dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "recovery_execution_id": value.get("recovery_execution_id"),
        "recovery_attempt_index": value.get("recovery_attempt_index", 1),
        "recovery_mission_id": value.get("recovery_mission_id") or value.get("mission_id"),
        "current_subject_hash": _strategy_subject_identity(
            value.get("current_subject_hash")
        ),
        "strategy_epoch": value.get("strategy_epoch", 0),
        "strategy_switch_count": value.get("strategy_switch_count", 0),
        "max_strategy_switches": value.get("max_strategy_switches", MAX_RECOVERY_STRATEGY_SWITCHES),
        "current_strategy": _safe_projection(value.get("current_strategy") or {}),
        "suppressed_mutation_mechanisms": list(value.get("suppressed_mutation_mechanisms", []) or []),
        "last_failure_pattern": _safe_projection(value.get("last_failure_pattern") or {}),
        "last_decision": _safe_projection((value.get("strategy_switch_decisions") or [{}])[-1]),
        "last_transition_feedback": _text(value.get("last_transition_feedback"), 1800),
        "strategy_epoch_starts": _safe_projection((value.get("strategy_epoch_starts") or [])[-4:]),
        "strategy_epoch_terminals": _safe_projection((value.get("strategy_epoch_terminals") or [])[-4:]),
        "strategy_search_summary": _safe_projection(value.get("strategy_search_summary") or {}),
        "tool_contract_failure_count": value.get("tool_contract_failure_count", 0),
        "last_tool_contract_failure_pattern": _safe_projection(
            value.get("last_tool_contract_failure_pattern") or {}
        ),
        "tool_contract_guidance_events_used": value.get(
            "tool_contract_guidance_events_used", 0
        ),
        "tool_contract_guidance_events": _safe_projection(
            (value.get("tool_contract_guidance_events") or [])[-1:]
        ),
        "suppressed_tool_request_count": value.get("suppressed_tool_request_count", 0),
        "suppressed_tool_requests": _safe_projection(
            (value.get("suppressed_tool_requests") or [])[-4:]
        ),
        "epoch_reanchors_used": value.get("epoch_reanchors_used", 0),
        "epoch_reanchors": _safe_projection((value.get("epoch_reanchors") or [])[-1:]),
        "last_epoch_reanchor_context": _text(
            value.get("last_epoch_reanchor_context"), 1800
        ),
        "completion_repairs_used": value.get("completion_repairs_used", 0),
        "completion_repair_events": _safe_projection(
            (value.get("completion_repair_events") or [])[-1:]
        ),
        "completion_contract": _safe_projection(
            value.get("completion_contract") or {}
        ),
        "no_mutation_search_interaction_count": value.get(
            "no_mutation_search_interaction_count", 0
        ),
        "no_mutation_search_threshold": MAX_RECOVERY_NO_MUTATION_SEARCH_INTERACTIONS_BEFORE_REORIENTATION,
        "no_mutation_search_safety_floor": MIN_RECOVERY_TOOL_STEPS_FOR_MUTATION_PATH_REORIENTATION,
        "no_mutation_search_pattern": _safe_projection(
            value.get("no_mutation_search_pattern") or {}
        ),
        "no_mutation_search_patterns": _safe_projection(
            (value.get("no_mutation_search_patterns") or [])[-4:]
        ),
        "no_mutation_search_interaction_events": _safe_projection(
            (value.get("no_mutation_search_interaction_events") or [])[-4:]
        ),
        "mutation_path_reorientations_used": value.get(
            "mutation_path_reorientations_used", 0
        ),
        "max_mutation_path_reorientations": value.get(
            "max_mutation_path_reorientations",
            MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        ),
        "mutation_path_reorientation_events": _safe_projection(
            (value.get("mutation_path_reorientation_events") or [])[-1:]
        ),
        "last_mutation_path_reorientation_context": _text(
            value.get("last_mutation_path_reorientation_context"), 1800
        ),
        "no_mutation_search_exhausted": bool(
            value.get("no_mutation_search_exhausted", False)
        ),
        "no_mutation_search_exhaustion_evidence": _safe_projection(
            value.get("no_mutation_search_exhaustion_evidence") or {}
        ),
        "no_mutation_search_terminal_state": value.get(
            "no_mutation_search_terminal_state"
        ),
        "terminal_state": value.get("terminal_state"),
        "worker_prose_authority": 0,
    }


def validate_recovery_strategy_state(state: dict[str, Any] | None) -> dict[str, Any]:
    """Validate the mutable orchestration envelope for one recovery Worker."""
    value = state if isinstance(state, dict) else {}
    errors: list[str] = []
    execution_id = value.get("recovery_execution_id")
    if not execution_id:
        errors.append("recovery strategy state is missing execution identity")
    attempt = _safe_int(value.get("recovery_attempt_index"), -1)
    if attempt != 1:
        errors.append("recovery strategy state does not bind attempt 1")
    epoch = _safe_int(value.get("strategy_epoch"), -1)
    if epoch not in {RECOVERY_STRATEGY_EPOCH_0, RECOVERY_STRATEGY_EPOCH_1}:
        errors.append("recovery strategy state epoch is invalid")
    switches = _safe_int(value.get("strategy_switch_count"), -1)
    maximum = _safe_int(value.get("max_strategy_switches"), -1)
    if switches < 0 or switches > MAX_RECOVERY_STRATEGY_SWITCHES:
        errors.append("recovery strategy switch count is invalid")
    if maximum < 0 or maximum > MAX_RECOVERY_STRATEGY_SWITCHES:
        errors.append("recovery strategy switch budget is invalid")
    if switches > maximum >= 0:
        errors.append("recovery strategy switch count exceeds its budget")
    for key, maximum_value, label in (
        (
            "tool_contract_guidance_events_used",
            MAX_RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENTS,
            "tool-contract guidance",
        ),
        ("epoch_reanchors_used", MAX_RECOVERY_EPOCH_REANCHORS, "epoch re-anchor"),
        (
            "completion_repairs_used",
            MAX_RECOVERY_COMPLETION_REPAIRS,
            "completion repair",
        ),
        (
            "mutation_path_reorientations_used",
            MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
            "mutation-path reorientation",
        ),
    ):
        counter = _safe_int(value.get(key, 0), -1)
        if counter < 0 or counter > maximum_value:
            errors.append(f"{label} budget is invalid")
    v266_max = _safe_int(
        value.get(
            "max_mutation_path_reorientations",
            MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS,
        ),
        -1,
    )
    if v266_max < 0 or v266_max > MAX_RECOVERY_MUTATION_PATH_REORIENTATIONS:
        errors.append("mutation-path reorientation budget is invalid")
    if (
        _safe_int(value.get("mutation_path_reorientations_used", 0), 0)
        > v266_max >= 0
    ):
        errors.append("mutation-path reorientation count exceeds its budget")
    pattern = value.get("no_mutation_search_pattern")
    if isinstance(pattern, dict) and pattern:
        pattern_check = validate_recovery_no_mutation_search_pattern(pattern)
        if not pattern_check.get("valid"):
            errors.append("last no-mutation search pattern is invalid")
    event = value.get("last_mutation_path_reorientation")
    if isinstance(event, dict) and event:
        event_check = validate_recovery_mutation_path_reorientation_event(event)
        if not event_check.get("valid"):
            errors.append("last mutation-path reorientation is invalid")
    strategy = value.get("current_strategy")
    strategy_check = validate_recovery_mutation_strategy(strategy)
    if not strategy_check.get("valid"):
        errors.append("current recovery mutation strategy is invalid")
    elif strategy.get("recovery_execution_id") != execution_id:
        errors.append("current strategy execution identity changed")
    if isinstance(strategy, dict) and _safe_int(strategy.get("strategy_epoch"), -1) != epoch:
        errors.append("current strategy epoch does not match state epoch")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:32],
        "strategy_hash": strategy.get("canonical_hash") if isinstance(strategy, dict) else None,
        "model_calls": 0,
        "worker_calls": 0,
    }


def validate_recovery_strategy(value: dict[str, Any] | None) -> dict[str, Any]:
    """Validate either a strategy record or its mutable recovery state."""
    if isinstance(value, dict):
        artifact_type = value.get("artifact_type")
        if artifact_type == RECOVERY_STRATEGY_FAILURE_PATTERN:
            return validate_recovery_strategy_failure_pattern(value)
        if artifact_type == RECOVERY_MUTATION_STRATEGY:
            return validate_recovery_mutation_strategy(value)
        if artifact_type == RECOVERY_STRATEGY_DIVERSIFICATION_DECISION:
            return validate_recovery_strategy_diversification_decision(value)
        if artifact_type == RECOVERY_TOOL_CONTRACT_FAILURE_PATTERN:
            return validate_recovery_tool_contract_failure_pattern(value)
        if artifact_type == RECOVERY_TOOL_CONTRACT_GUIDANCE_EVENT:
            return validate_recovery_tool_contract_guidance_event(value)
        if artifact_type == RECOVERY_EPOCH_REANCHOR_EVENT:
            return validate_recovery_epoch_reanchor_event(value)
        if artifact_type == RECOVERY_COMPLETION_CONTRACT_REPAIR:
            return validate_recovery_completion_repair_event(value)
        if artifact_type == RECOVERY_COMPLETION_REPAIR_EVENT:
            return validate_recovery_completion_repair_event(value)
        if artifact_type == RECOVERY_NO_MUTATION_SEARCH_PATTERN:
            return validate_recovery_no_mutation_search_pattern(value)
        if artifact_type == RECOVERY_NO_MUTATION_SEARCH_INTERACTION:
            return validate_recovery_no_mutation_search_interaction(value)
        if artifact_type == RECOVERY_MUTATION_PATH_REORIENTATION_EVENT:
            return validate_recovery_mutation_path_reorientation_event(value)
    return validate_recovery_strategy_state(value)


validate_recovery_strategy_controller = validate_recovery_strategy_state


# Compatibility spellings keep the V26.3 surface discoverable without
# coupling callers to one internal noun for the same deterministic records.
build_strategy_failure_pattern = build_recovery_strategy_failure_pattern
build_strategy_mutation = build_recovery_mutation_strategy
derive_legal_recovery_mutation_mechanisms = discover_legal_recovery_mutation_mechanisms
project_recovery_tool_schema = project_recovery_tool_schemas
recovery_strategy_stagnation = detect_recovery_strategy_stagnation


def _is_private_key(key: Any) -> bool:
    lowered = str(key).casefold()
    return lowered in _PRIVATE_KEYS or any(token in lowered for token in (
        "chain_of_thought", "private_reason", "generation_history", "prompt_history",
    ))


def contains_forbidden_recovery_transcript(value: Any) -> bool:
    """Return whether a recovery artifact contains private Worker history."""
    if isinstance(value, dict):
        for key, item in value.items():
            if _is_private_key(key):
                return True
            if contains_forbidden_recovery_transcript(item):
                return True
        return False
    if isinstance(value, (list, tuple, set, frozenset)):
        return any(contains_forbidden_recovery_transcript(item) for item in value)
    if isinstance(value, str):
        lowered = value.casefold()
        return any(token in lowered for token in (
            "chain_of_thought", "private reasoning", "raw worker transcript",
        ))
    return False


def _safe_projection(value: Any, *, depth: int = 0, max_depth: int = 5) -> Any:
    """Copy JSON-shaped evidence while removing Worker-private material."""
    if depth > max_depth:
        return None
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if _is_private_key(key):
                continue
            if str(key).casefold() in {"raw_content", "raw_prompt", "provider_response"}:
                continue
            result[str(key)] = _safe_projection(item, depth=depth + 1, max_depth=max_depth)
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_safe_projection(item, depth=depth + 1, max_depth=max_depth) for item in list(value)[:120]]
    if isinstance(value, str):
        return _text(value, 900)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _text(value, 300)


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _artifact_directory(root: str | os.PathLike[str] | Path) -> Path:
    path = Path(root).expanduser().resolve()
    if path.name.casefold() == "artifacts":
        return path
    return path / "artifacts"


def load_live3_recovery_evidence(
    artifact_root: str | os.PathLike[str] | Path | None = None,
) -> dict[str, Any]:
    """Load live-3 evidence read-only and expose convenient projections.

    The loader never writes the marker, subject, artifacts, or Brain.  Raw
    artifacts are returned only for diagnostic callers; builders below select
    deterministic fields and never copy Worker prose into recovery context.
    """
    if artifact_root is None:
        artifact_root = (
            Path(__file__).resolve().parents[1]
            / "output"
            / "hivo-v25-6-stage6c-b-verification-closure-live-3"
        )
    artifacts_dir = _artifact_directory(artifact_root)
    names = (
        "accepted_legal_mutations.json",
        "direct_behavior_oracle_result.json",
        "direct_oracle.json",
        "execution_start_receipt.json",
        "execution_start_receipt_validation.json",
        "final_authorization_audit.json",
        "final_run_report.json",
        "historical_immutability.json",
        "precommit_invariant_audits.json",
        "stage5a_route_bindings.json",
        "stage5b_integration.json",
        "stage5c_promotion.json",
        "subject_manifest_after.json",
        "subject_manifest_before.json",
        "verification_coverage.json",
        "verification_runner_evidence.json",
        "worker_execution.json",
        "worker_result.json",
        "working_brain_after.json",
        "working_brain_before.json",
    )
    artifacts = {
        name: _read_json(artifacts_dir / name)
        for name in names
        if (artifacts_dir / name).is_file()
    }
    final_report = artifacts.get("final_run_report.json") if isinstance(artifacts.get("final_run_report.json"), dict) else {}
    run_state = final_report.get("run_state") if isinstance(final_report.get("run_state"), dict) else {}
    worker_result = artifacts.get("worker_result.json") if isinstance(artifacts.get("worker_result.json"), dict) else {}
    return {
        "source_kind": "LIVE3_READ_ONLY",
        "artifact_root": str(Path(artifact_root).resolve()),
        "artifacts_directory": str(artifacts_dir),
        "artifacts": artifacts,
        "run_state": run_state,
        "approval_request": run_state.get("approval_request"),
        "approval_receipt": run_state.get("approval_receipt"),
        "execution_authorization": run_state.get("execution_authorization"),
        "approved_change_plan": run_state.get("approved_change_plan"),
        "execution_contracts": run_state.get("execution_contracts"),
        "stage5b_parent_contract": run_state.get("stage5b_parent_contract"),
        "stage5c_parent_contract": run_state.get("stage5c_parent_contract"),
        "execution_start_receipt": artifacts.get("execution_start_receipt.json"),
        "worker_execution": artifacts.get("worker_execution.json"),
        "worker_result": worker_result,
        "verification_applicability": (
            worker_result.get("verification_applicability")
            if isinstance(worker_result.get("verification_applicability"), dict)
            else artifacts.get("stage5a_route_bindings.json")
        ),
        "verification_evidence": (
            worker_result.get("verification_evidence")
            if isinstance(worker_result.get("verification_evidence"), list)
            else artifacts.get("verification_runner_evidence.json")
        ),
        "verification_coverage": artifacts.get("verification_coverage.json"),
        "precommit_invariant_audits": artifacts.get("precommit_invariant_audits.json"),
        "stage5b_integration": artifacts.get("stage5b_integration.json"),
        "stage5c_promotion": artifacts.get("stage5c_promotion.json"),
        "working_brain_before": artifacts.get("working_brain_before.json"),
        "working_brain_after": artifacts.get("working_brain_after.json"),
    }


read_live3_recovery_evidence = load_live3_recovery_evidence


def _source_parts(source: Any) -> dict[str, Any]:
    if isinstance(source, (str, os.PathLike, Path)):
        return load_live3_recovery_evidence(source)
    if isinstance(source, dict):
        if isinstance(source.get("artifacts"), dict):
            merged = _copy(source)
            artifacts = merged["artifacts"]
            def artifact_value(stem: str) -> Any:
                return artifacts.get(stem) if stem in artifacts else artifacts.get(stem + ".json")
            merged.setdefault("execution_start_receipt", artifact_value("execution_start_receipt"))
            merged.setdefault("worker_execution", artifact_value("worker_execution"))
            merged.setdefault("worker_result", artifact_value("worker_result"))
            merged.setdefault("verification_coverage", artifact_value("verification_coverage"))
            merged.setdefault("precommit_invariant_audits", artifact_value("precommit_invariant_audits"))
            merged.setdefault("stage5b_integration", artifact_value("stage5b_integration"))
            merged.setdefault("stage5c_promotion", artifact_value("stage5c_promotion"))
            merged.setdefault("working_brain_before", artifact_value("working_brain_before"))
            merged.setdefault("working_brain_after", artifact_value("working_brain_after"))
            return merged
        return _copy(source)
    return {}


def _projection_from_run_state(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            return value
    run_state = data.get("run_state")
    if isinstance(run_state, dict):
        for key in keys:
            value = run_state.get(key)
            if isinstance(value, dict):
                return value
    return {}


def _deterministic_evidence_records(data: dict[str, Any]) -> list[dict[str, Any]]:
    worker_result = data.get("worker_result") if isinstance(data.get("worker_result"), dict) else {}
    evidence = data.get("verification_evidence")
    if not isinstance(evidence, list):
        evidence = worker_result.get("verification_evidence")
    if not isinstance(evidence, list):
        evidence = (
            (data.get("artifacts") or {}).get("verification_runner_evidence")
            if isinstance(data.get("artifacts"), dict)
            else []
        )
    records: list[dict[str, Any]] = []
    allowed = {
        "verification_id", "authority_id", "oracle_id", "route_type",
        "execution_channel", "target", "command", "result", "receipt_status",
        "receipt_valid", "receipt_identity", "receipt_hash", "source",
        "evidence_id", "valid", "passed",
    }
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        record = {
            key: _safe_projection(value)
            for key, value in item.items()
            if key in allowed
        }
        if isinstance(item.get("result"), dict):
            record["result"] = {
                key: _safe_projection(value)
                for key, value in item["result"].items()
                if key in {
                    "passed", "verification_status", "oracle_id", "oracle_hash",
                    "verification_id", "authority_id", "exit_code", "valid",
                    "checks", "route_type", "execution_channel",
                }
            }
        if record:
            records.append(record)
    return records[:24]


def _failed_verification_projection(
    data: dict[str, Any],
    closure: dict[str, Any],
) -> dict[str, Any]:
    failed_ids = _unique_strings(
        closure.get("failed_authorities")
        or closure.get("failed_verification_authority_ids")
        or [],
        limit=24,
    )
    records = _deterministic_evidence_records(data)
    direct_result = None
    for item in records:
        result = item.get("result")
        if (
            item.get("authority_id") in failed_ids
            or item.get("verification_id") in failed_ids
            or item.get("oracle_id") == "ORACLE-PAUSE-INDICATOR"
            or (isinstance(result, dict) and result.get("oracle_id") == "ORACLE-PAUSE-INDICATOR")
        ):
            direct_result = result if isinstance(result, dict) else item
            break
    direct_result = direct_result if isinstance(direct_result, dict) else {}
    checks = direct_result.get("checks") if isinstance(direct_result.get("checks"), list) else []
    failed_check = None
    detail = None
    for check in checks:
        if isinstance(check, dict) and check.get("passed") is False:
            failed_check = _text(check.get("name"), 160)
            detail = _text(check.get("detail"), 240)
            break
    authority_id = failed_ids[0] if failed_ids else _text(
        direct_result.get("authority_id") or direct_result.get("verification_id"), 160,
    )
    oracle_id = _text(
        direct_result.get("oracle_id") or (
            "ORACLE-PAUSE-INDICATOR" if authority_id == "VERIFICATION-004" else ""
        ),
        180,
    )
    return {
        "authority_id": authority_id,
        "verification_id": authority_id,
        "oracle_id": oracle_id,
        "oracle_hash": _text(
            direct_result.get("oracle_hash")
            or (LIVE3_ORACLE_HASH if oracle_id == "ORACLE-PAUSE-INDICATOR" else ""),
            128,
        ),
        "failed_check": failed_check or (
            "export_callable" if oracle_id == "ORACLE-PAUSE-INDICATOR" else None
        ),
        "check": failed_check or (
            "export_callable" if oracle_id == "ORACLE-PAUSE-INDICATOR" else None
        ),
        "detail": detail or (
            "renderPauseIndicator" if oracle_id == "ORACLE-PAUSE-INDICATOR" else None
        ),
        "target_symbol": detail or (
            "renderPauseIndicator" if oracle_id == "ORACLE-PAUSE-INDICATOR" else None
        ),
        "status": "FAIL",
        "execution_channel": _text(
            direct_result.get("execution_channel") or "DIRECT_ORACLE_EXECUTION",
            120,
        ),
        "evidence_basis": "deterministic_failed_verification_receipt",
    }


def _scope_projection(data: dict[str, Any], worker_execution: dict[str, Any]) -> dict[str, Any]:
    worker_result = data.get("worker_result") if isinstance(data.get("worker_result"), dict) else {}
    audit = worker_result.get("mutation_audit")
    if not isinstance(audit, dict):
        audit = {}
    changed = _unique_strings(
        audit.get("changed_paths") or worker_execution.get("changed_paths") or [],
        paths=True,
    )
    out_of_scope = _unique_strings(audit.get("out_of_scope_paths") or [], paths=True)
    violations = int(
        audit.get("scope_violations", 0)
        or audit.get("unauthorized_mutations", 0)
        or len(out_of_scope)
        or 0
    )
    return {
        "status": "PASS" if violations == 0 else "FAIL",
        "passed": violations == 0,
        "changed_paths": changed,
        "out_of_scope_paths": out_of_scope,
        "scope_violations": violations,
        "unauthorized_mutations": int(audit.get("unauthorized_mutations", 0) or 0),
        "committed_paths": changed,
        "evidence_basis": "deterministic_mutation_scope_audit",
    }


def _dnt_projection(data: dict[str, Any], worker_execution: dict[str, Any]) -> dict[str, Any]:
    worker_result = data.get("worker_result") if isinstance(data.get("worker_result"), dict) else {}
    audit = worker_result.get("mutation_audit") if isinstance(worker_result.get("mutation_audit"), dict) else {}
    dnt_paths = _unique_strings(
        audit.get("dnt_changed_paths") or worker_execution.get("dnt_changed_paths") or [],
        paths=True,
    )
    return {
        "status": "PASS" if not dnt_paths and int(audit.get("dnt_violations", 0) or 0) == 0 else "FAIL",
        "passed": not dnt_paths and int(audit.get("dnt_violations", 0) or 0) == 0,
        "changed_paths": dnt_paths,
        "dnt_violations": int(audit.get("dnt_violations", 0) or 0),
        "dnt_digest": _text(
            worker_execution.get("dnt_digest")
            or data.get("execution_authorization", {}).get("dnt_digest")
            if isinstance(data.get("execution_authorization"), dict)
            else "",
            128,
        ),
        "evidence_basis": "deterministic_do_not_touch_audit",
    }


def _precommit_projection(data: dict[str, Any]) -> dict[str, Any]:
    audits = data.get("precommit_invariant_audits")
    audits = audits if isinstance(audits, list) else []
    accepted = [
        item for item in audits
        if isinstance(item, dict) and item.get("allowed") is True
    ]
    hashes = _unique_strings(
        [item.get("canonical_hash") for item in accepted],
        limit=24,
    )
    authority_hash = next(
        (
            _text(item.get("authority_set_hash"), 128)
            for item in accepted
            if item.get("authority_set_hash")
        ),
        "",
    )
    return {
        "status": "PASS" if accepted else "UNKNOWN",
        "passed": bool(accepted),
        "audit_count": len(audits),
        "accepted_count": len(accepted),
        "rejected_count": max(0, len(audits) - len(accepted)),
        "receipt_hashes": hashes,
        "authority_set_hash": authority_hash or LIVE3_INVARIANT_HASH,
        "model_calls": 0,
        "worker_calls": 0,
        "evidence_basis": "V25.5_PreCommitExecutionInvariantGate",
    }


def _brain_projection(data: dict[str, Any]) -> tuple[str, str, bool]:
    before = data.get("working_brain_before") if isinstance(data.get("working_brain_before"), dict) else {}
    after = data.get("working_brain_after") if isinstance(data.get("working_brain_after"), dict) else {}
    before_hash = _text(before.get("logical_hash"), 128) or LIVE3_BRAIN_HASH
    after_hash = _text(after.get("logical_hash"), 128) or before_hash
    return before_hash, after_hash, before_hash == after_hash


def _coverage_projection(data: dict[str, Any], closure: dict[str, Any]) -> dict[str, Any]:
    coverage = data.get("verification_coverage")
    coverage = coverage if isinstance(coverage, dict) else {}
    execution_time = (
        (data.get("worker_result") or {}).get("execution_time_coverage")
        if isinstance(data.get("worker_result"), dict)
        else None
    )
    if not isinstance(execution_time, dict):
        execution_time = closure.get("execution_time_obligation_closure")
    execution_time = execution_time if isinstance(execution_time, dict) else {}
    return {
        "coverage_hash": _text(
            coverage.get("coverage_hash")
            or closure.get("coverage_hash")
            or LIVE3_COVERAGE_HASH,
            128,
        ),
        "coverage_status": _text(
            coverage.get("coverage_status") or coverage.get("status"),
            160,
        ),
        "failed_obligation_ids": _unique_strings(
            execution_time.get("failed_obligation_ids") or [],
            limit=32,
        ),
        "not_run_obligation_ids": _unique_strings(
            execution_time.get("not_run_obligation_ids") or [],
            limit=32,
        ),
        "all_required_passed": execution_time.get("all_required_passed") is True,
        "verification_ready": coverage.get("verification_ready") is True,
    }


def build_recovery_failure_envelope(
    source: Any = None,
    *,
    artifact_root: str | os.PathLike[str] | Path | None = None,
    failure_evidence: dict[str, Any] | None = None,
) -> RecoveryFailureEnvelope:
    """Build the immutable deterministic failure envelope.

    Passing a path reads that path read-only.  The function intentionally
    selects receipts and structured status fields instead of copying the raw
    Worker result or chat.
    """
    if artifact_root is not None:
        source = artifact_root
    elif source is None:
        # A tagged variant is an overlay on deterministic execution evidence;
        # it is not itself a replacement for the authority/subject source.
        source = (
            failure_evidence
            if isinstance(failure_evidence, dict)
            and not (
                failure_evidence.get("artifact_type") == RECOVERY_FAILURE_EVIDENCE
                or failure_evidence.get("failure_source") in {VERIFICATION_FAILURE, WORKER_EXECUTION_FAILURE}
            )
            else load_live3_recovery_evidence()
        )
    data = _source_parts(source)
    explicit_failure_evidence = (
        _failure_evidence_source(failure_evidence)
        or _failure_evidence_source(data)
    )
    artifacts = data.get("artifacts") if isinstance(data.get("artifacts"), dict) else {}
    worker_execution = data.get("worker_execution")
    if not isinstance(worker_execution, dict):
        worker_execution = artifacts.get("worker_execution") if isinstance(artifacts.get("worker_execution"), dict) else {}
    worker_result = data.get("worker_result")
    if not isinstance(worker_result, dict):
        worker_result = artifacts.get("worker_result") if isinstance(artifacts.get("worker_result"), dict) else {}
    start_receipt = data.get("execution_start_receipt")
    if not isinstance(start_receipt, dict):
        start_receipt = artifacts.get("execution_start_receipt") if isinstance(artifacts.get("execution_start_receipt"), dict) else {}
    authorization = _projection_from_run_state(data, "execution_authorization")
    plan = _projection_from_run_state(data, "approved_change_plan")
    approval_receipt = _projection_from_run_state(data, "approval_receipt")
    approval_request = _projection_from_run_state(data, "approval_request")
    contract = _projection_from_run_state(
        data,
        "stage5b_parent_contract",
        "stage5c_parent_contract",
        "approval_bound_parent_contract",
    )
    execution_contracts = data.get("execution_contracts")
    if not isinstance(execution_contracts, list):
        execution_contracts = data.get("run_state", {}).get("execution_contracts", []) if isinstance(data.get("run_state"), dict) else []
    worker_contract = execution_contracts[0] if execution_contracts and isinstance(execution_contracts[0], dict) else contract
    closure = worker_result.get("execution_verification_closure")
    if not isinstance(closure, dict):
        closure = {}
    aggregation = worker_result.get("verification_aggregation")
    if not isinstance(aggregation, dict):
        aggregation = {}
    required_set = aggregation.get("required_execution_verification_set")
    if not isinstance(required_set, dict):
        required_set = {}
    scope = _scope_projection(data, worker_execution)
    dnt = _dnt_projection(data, worker_execution)
    precommit = _precommit_projection(data)
    before_brain, after_brain, brain_unchanged = _brain_projection(data)
    coverage = _coverage_projection(data, closure)
    failed_verification = _failed_verification_projection(data, closure)
    failed_ids = _unique_strings(
        closure.get("failed_authorities")
        or ([failed_verification["authority_id"]] if failed_verification.get("authority_id") else []),
        limit=24,
    )
    execution_id = _text(
        (explicit_failure_evidence or {}).get("execution_id")
        or worker_execution.get("worker_run_id")
        or worker_execution.get("execution_id")
        or start_receipt.get("execution_start_id")
        or worker_contract.get("execution_contract_id"),
        180,
    )
    approval_id = _text(
        approval_receipt.get("approval_id")
        or authorization.get("approval_id"),
        160,
    ) or LIVE3_APPROVAL_ID
    approval_receipt_hash = _text(
        start_receipt.get("approval_receipt_hash")
        or worker_execution.get("approval_receipt_hash")
        or approval_receipt.get("receipt_hash"),
        128,
    ) or LIVE3_APPROVAL_RECEIPT_HASH
    plan_id = _text(
        plan.get("plan_id")
        or authorization.get("canonical_plan_id")
        or start_receipt.get("canonical_plan_id"),
        160,
    ) or LIVE3_PLAN_ID
    plan_hash = _text(
        plan.get("plan_hash")
        or authorization.get("canonical_plan_hash")
        or start_receipt.get("canonical_plan_hash"),
        128,
    ) or LIVE3_PLAN_HASH
    authorization_hash = _text(
        authorization.get("authorization_hash")
        or start_receipt.get("authorization_hash")
        or worker_execution.get("authorization_hash"),
        128,
    )
    authorization_id = _text(authorization.get("authorization_id"), 160)
    contract_id = _text(
        worker_execution.get("execution_contract_id")
        or worker_result.get("execution_contract_id")
        or worker_contract.get("execution_contract_id"),
        160,
    )
    contract_hash = _text(
        worker_execution.get("execution_contract_hash")
        or worker_contract.get("contract_hash"),
        128,
    )
    subject_before = _text(
        worker_execution.get("pre_subject_hash")
        or worker_execution.get("pre_worker_subject_hash")
        or start_receipt.get("pre_subject_hash"),
        128,
    ) or LIVE3_BASELINE_SUBJECT_HASH
    subject_after = _text(
        worker_execution.get("post_subject_hash")
        or worker_execution.get("current_subject_hash"),
        128,
    ) or LIVE3_FAILED_SUBJECT_HASH
    if explicit_failure_evidence is None:
        # Legacy V25.6-backed envelopes are promoted into the explicit
        # verification member only when the source carries an actual failed
        # verification identity.  Missing receipts never imply this variant.
        if failed_ids and failed_verification.get("authority_id"):
            explicit_failure_evidence = build_verification_failure_evidence(
                execution_id,
                authority_id=failed_verification.get("authority_id"),
                oracle_id=failed_verification.get("oracle_id"),
                oracle_hash=failed_verification.get("oracle_hash"),
                failed_check=failed_verification.get("failed_check"),
                detail=failed_verification.get("detail"),
                verification_status=failed_verification.get("status") or "FAIL",
                subject_before_hash=subject_before,
                subject_after_hash=subject_after,
                current_subject_hash=subject_after,
                worker_result_status=worker_result.get("status") or "failed",
            )
        else:
            explicit_failure_evidence = build_recovery_failure_evidence(
                execution_id,
                failure_source="",
            )
    source_is_worker_execution = (
        explicit_failure_evidence.get("failure_source") == WORKER_EXECUTION_FAILURE
    )
    if source_is_worker_execution:
        subject_before = _text(
            explicit_failure_evidence.get("subject_before_hash"),
            128,
        ) or subject_before
        subject_after = _text(
            explicit_failure_evidence.get("subject_after_hash")
            or explicit_failure_evidence.get("current_subject_hash"),
            128,
        ) or subject_before
        # A pre-verification Worker terminal is explicitly a no-commit
        # state.  Never carry a prior verification closure or failed receipt
        # into this variant.
        failed_ids = []
        failed_verification = {}
        closure = {}
        aggregation = {}
        precommit = {
            "status": "PASS" if explicit_failure_evidence.get("v25_5_authority_valid") is True else "UNKNOWN",
            "passed": explicit_failure_evidence.get("v25_5_authority_valid") is True,
            "audit_count": 0,
            "accepted_count": 1 if explicit_failure_evidence.get("v25_5_authority_valid") is True else 0,
            "rejected_count": 0,
            "receipt_hashes": [],
            "authority_set_hash": LIVE3_INVARIANT_HASH,
            "model_calls": 0,
            "worker_calls": 0,
            "evidence_basis": "V25.5_Approved_Authority_Binding",
        }
        coverage = {
            "coverage_hash": _text(
                authorization.get("verification_obligation_coverage_hash")
                or start_receipt.get("verification_obligation_coverage_hash"),
                128,
            ) or LIVE3_COVERAGE_HASH,
            "coverage_status": "AVAILABLE_NOT_EXECUTED",
            "failed_obligation_ids": [],
            "not_run_obligation_ids": _unique_strings(
                explicit_failure_evidence.get("verification_obligation_ids"),
                limit=32,
            ),
            "all_required_passed": False,
            "verification_ready": explicit_failure_evidence.get("full_verification_universe_available") is True,
        }
        before_brain = _text(
            explicit_failure_evidence.get("brain_before_hash"),
            128,
        ) or before_brain
        after_brain = _text(
            explicit_failure_evidence.get("brain_after_hash"),
            128,
        ) or before_brain
        brain_unchanged = (
            explicit_failure_evidence.get("brain_unchanged") is True
            and before_brain == after_brain
        )
        scope = {
            "status": "PASS" if explicit_failure_evidence.get("scope_valid") is True else "FAIL",
            "passed": explicit_failure_evidence.get("scope_valid") is True,
            "changed_paths": [],
            "out_of_scope_paths": [],
            "scope_violations": 0,
            "unauthorized_mutations": 0,
            "committed_paths": [],
            "evidence_basis": "deterministic_worker_execution_scope_contract",
        }
        dnt = {
            "status": "PASS" if explicit_failure_evidence.get("dnt_valid") is True else "FAIL",
            "passed": explicit_failure_evidence.get("dnt_valid") is True,
            "changed_paths": [],
            "dnt_violations": 0,
            "dnt_digest": _text(
                explicit_failure_evidence.get("dnt_digest"), 128
            ),
            "evidence_basis": "deterministic_worker_execution_dnt_contract",
        }
    mutation_manifest = {
        "changed_paths": scope["changed_paths"],
        "created_paths": _unique_strings(worker_execution.get("created_paths") or [], paths=True),
        "deleted_paths": _unique_strings(worker_execution.get("deleted_paths") or [], paths=True),
        "committed_paths": scope["committed_paths"],
        "execution_id": execution_id,
        "scope_status": scope["status"],
        "dnt_status": dnt["status"],
        "evidence_basis": "deterministic_worker_execution_and_mutation_audit",
    }
    stage5b = data.get("stage5b_integration")
    stage5b = stage5b if isinstance(stage5b, dict) else {}
    stage5c = data.get("stage5c_promotion")
    stage5c = stage5c if isinstance(stage5c, dict) else {}
    promotion_status = _text(
        stage5c.get("promotion_status")
        or stage5c.get("status")
        or "NOT_REACHED",
        160,
    ) or "NOT_REACHED"
    if promotion_status.casefold() in {"none", "null"}:
        promotion_status = "NOT_REACHED"
    required_set_hash = _text(
        closure.get("required_execution_verification_set_hash")
        or required_set.get("set_hash"),
        128,
    )
    verification_digest = _text(
        closure.get("verification_digest")
        or authorization.get("verification_digest")
        or start_receipt.get("verification_digest"),
        128,
    ) or LIVE3_VERIFICATION_DIGEST
    envelope: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_FAILURE_ENVELOPE,
        "source_kind": data.get("source_kind") or "DETERMINISTIC_EXECUTION_EVIDENCE",
        "failure_source": explicit_failure_evidence.get("failure_source"),
        "failure_evidence": _safe_projection(explicit_failure_evidence),
        "failure_evidence_hash": explicit_failure_evidence.get("canonical_hash"),
        "execution_id": execution_id,
        "failed_execution_id": execution_id,
        "execution_start_id": _text(start_receipt.get("execution_start_id"), 180),
        "plan_id": plan_id,
        "plan_hash": plan_hash,
        "approval_id": approval_id,
        "approval_receipt_hash": approval_receipt_hash,
        "execution_authorization_id": authorization_id,
        "execution_authorization_hash": authorization_hash,
        "execution_start_receipt": _safe_projection({
            key: value for key, value in start_receipt.items()
            if key in {
                "schema_version", "artifact_type", "status", "execution_start_id",
                "authorization_hash", "approval_receipt_hash", "canonical_plan_id",
                "canonical_plan_hash", "execution_contract_id", "execution_contract_hash",
                "stage4_contract_hash", "pre_worker_subject_hash", "pre_subject_hash",
                "pre_worker_brain_hash", "pre_brain_hash", "authorized_mutation_scope",
                "mutation_scope_digest", "dnt_digest", "verification_digest",
                "dependency_digest", "interface_binding_digest", "receipt_hash",
                "verification_obligation_coverage_hash",
                "verification_obligation_coverage_status",
                "verification_obligation_coverage_ready",
                "verification_obligation_uncovered_ids",
            }
        }),
        "worker_contract_id": contract_id,
        "worker_contract_hash": contract_hash,
        "execution_contract_id": contract_id,
        "execution_contract_hash": contract_hash,
        "worker_result_status": (
            _text(explicit_failure_evidence.get("worker_result_status"), 120)
            if source_is_worker_execution
            else _text(worker_result.get("status"), 120) or "failed"
        ),
        "worker_terminal_state": (
            _text(explicit_failure_evidence.get("worker_terminal_code"), 160)
            if source_is_worker_execution
            else _text(worker_result.get("terminal_state"), 160)
        ),
        "subject_before_hash": subject_before,
        "subject_after_hash": subject_after,
        "current_subject_hash": subject_after,
        "committed_mutation_manifest": mutation_manifest,
        "approved_mutation_scope": _safe_projection(
            authorization.get("approved_mutation_scope")
            or {"paths": scope["committed_paths"]},
        ),
        "scope_audit": scope,
        "scope": scope,
        "approved_dnt": _safe_projection(
            authorization.get("approved_dnt")
            or {"paths": _approved_dnt_paths(authorization)},
        ),
        "dnt_audit": dnt,
        "dnt": dnt,
        "approved_interface_binding": _safe_projection(
            authorization.get("approved_interface_binding") or {},
        ),
        "approved_verification_authority_ids": _approved_verification_ids(authorization),
        "execution_invariant_set_hash": _text(
            authorization.get("execution_invariant_set_hash")
            or contract.get("execution_invariant_set_hash")
            or (contract.get("execution_invariant_projection") or {}).get("execution_invariant_set_hash")
            if isinstance(contract.get("execution_invariant_projection"), dict)
            else "",
            128,
        ) or LIVE3_INVARIANT_HASH,
        "precommit_audit_summary": precommit,
        "verification_digest": verification_digest,
        "coverage_hash": coverage["coverage_hash"],
        "verification_coverage": coverage,
        "required_execution_verification_set_hash": required_set_hash,
        "execution_verification_closure_hash": (
            "" if source_is_worker_execution else _text(closure.get("closure_hash"), 128)
        ),
        "execution_verification_closure": _safe_projection({
            "schema_version": closure.get("schema_version"),
            "artifact_type": closure.get("artifact_type"),
            "all_required_passed": closure.get("all_required_passed") is True,
            "required_authority_ids": closure.get("required_authority_ids", []),
            "failed_authorities": closure.get("failed_authorities", []),
            "missing_authorities": closure.get("missing_authorities", []),
            "not_run_authorities": closure.get("not_run_authorities", []),
            "invalid_authorities": closure.get("invalid_authorities", []),
            "closure_hash": closure.get("closure_hash"),
        }) if not source_is_worker_execution else {},
        "failed_verification_authority_ids": failed_ids,
        "failed_authority_ids": failed_ids,
        "failed_verification": failed_verification,
        "missing_authority_ids": _unique_strings(
            closure.get("missing_authorities") or closure.get("missing_authority_ids") or [],
            limit=24,
        ),
        "pending_authority_ids": _unique_strings(
            closure.get("not_run_authorities") or closure.get("pending_authority_ids") or [],
            limit=24,
        ),
        "invalid_authority_ids": _unique_strings(
            closure.get("invalid_authorities") or closure.get("invalid_authority_ids") or [],
            limit=24,
        ),
        "execution_time_failed_obligations": coverage["failed_obligation_ids"],
        "execution_time_coverage": coverage,
        "required_authority_ids": _unique_strings(
            (
                explicit_failure_evidence.get("verification_obligation_ids")
                if source_is_worker_execution
                else (
                    closure.get("required_authority_ids")
                    or required_set.get("required_authority_ids")
                    or []
                )
            ),
            limit=48,
        ),
        "stage5b_status": _text(
            stage5b.get("integration_result") or stage5b.get("status") or "INTEGRATION_NOT_READY",
            160,
        ) or "INTEGRATION_NOT_READY",
        "promotion_status": promotion_status,
        "brain_before_hash": before_brain,
        "brain_after_hash": after_brain,
        "brain_unchanged": brain_unchanged,
        "brain_status": "UNCHANGED" if brain_unchanged else "CHANGED",
        "worker_prose_authority": 0,
        "worker_prose_excluded": True,
        "deterministic_evidence_provenance": [
            "execution_start_receipt",
            "worker_execution_receipt",
            "mutation_scope_audit",
            "dnt_audit",
            "V25.5_PreCommitExecutionInvariantGate",
            "V25.6_ExecutionVerificationClosure",
            "working_brain_before_after",
        ],
        "verification_evidence_projection": (
            [] if source_is_worker_execution else _deterministic_evidence_records(data)
        ),
        "canonical_failure_envelope_hash": "",
        "canonical_hash": "",
        "failure_envelope_hash": "",
    }
    envelope_hash = canonical_hash(
        _without(envelope, "canonical_failure_envelope_hash", "failure_envelope_hash", "canonical_hash"),
    )
    envelope["canonical_failure_envelope_hash"] = envelope_hash
    envelope["canonical_hash"] = envelope_hash
    envelope["failure_envelope_hash"] = envelope_hash
    return _freeze_record(RecoveryFailureEnvelope, envelope)  # type: ignore[return-value]


create_recovery_failure_envelope = build_recovery_failure_envelope
load_live3_recovery_failure_envelope = lambda artifact_root=None: build_recovery_failure_envelope(artifact_root)


def validate_recovery_failure_envelope(envelope: dict[str, Any] | None) -> dict[str, Any]:
    value = envelope if isinstance(envelope, dict) else {}
    errors: list[str] = []
    expected = canonical_hash(
        _without(value, "canonical_failure_envelope_hash", "failure_envelope_hash", "canonical_hash"),
    ) if value else None
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("recovery failure envelope schema is invalid")
    if value.get("artifact_type") != RECOVERY_FAILURE_ENVELOPE:
        errors.append("recovery failure envelope artifact type is invalid")
    if (
        value.get("canonical_failure_envelope_hash") != expected
        or value.get("canonical_hash") != expected
        or value.get("failure_envelope_hash") != expected
    ):
        errors.append("recovery failure envelope hash is invalid")
    for field in (
        "execution_id", "plan_id", "plan_hash", "approval_id",
        "approval_receipt_hash", "subject_before_hash", "current_subject_hash",
        "execution_invariant_set_hash", "verification_digest", "coverage_hash",
    ):
        if not value.get(field):
            errors.append(f"recovery failure envelope field is missing: {field}")
    failure_evidence = value.get("failure_evidence")
    variant_check = None
    if isinstance(failure_evidence, dict):
        variant_check = validate_recovery_failure_evidence(failure_evidence)
        if not variant_check.get("valid"):
            errors.extend(
                f"failure evidence: {item}"
                for item in variant_check.get("errors", [])[:24]
            )
        if value.get("failure_source") != failure_evidence.get("failure_source"):
            errors.append("recovery failure envelope source variant is inconsistent")
        if value.get("failure_evidence_hash") != failure_evidence.get("canonical_hash"):
            errors.append("recovery failure envelope evidence hash is invalid")
        # The new execution-failure member is fully bound to the envelope.
        # Legacy verification-backed envelopes retain their historical flat
        # projection surface, which callers may re-project when replaying an
        # older receipt (without changing the explicit receipt itself).
        if failure_evidence.get("failure_source") == WORKER_EXECUTION_FAILURE:
            for field in (
                "execution_id", "worker_result_status", "subject_before_hash",
                "subject_after_hash", "current_subject_hash",
            ):
                if value.get(field) != failure_evidence.get(field):
                    errors.append(f"recovery failure envelope evidence binding is invalid: {field}")
            for field in (
                "plan_id", "plan_hash", "approval_id", "approval_receipt_hash",
                "execution_invariant_set_hash",
            ):
                if value.get(field) != failure_evidence.get(field):
                    errors.append(f"recovery failure envelope evidence binding is invalid: {field}")
        if failure_evidence.get("failure_source") == WORKER_EXECUTION_FAILURE:
            if value.get("failed_verification_authority_ids"):
                errors.append("Worker execution failure must not contain failed verification authority IDs")
            if value.get("failed_verification"):
                errors.append("Worker execution failure must not contain a failed verification projection")
            if value.get("execution_verification_closure_hash"):
                errors.append("Worker execution failure must not contain a verification closure hash")
            if value.get("execution_verification_closure"):
                errors.append("Worker execution failure must not contain a verification closure")
            if value.get("worker_terminal_state") != failure_evidence.get("worker_terminal_code"):
                errors.append("Worker execution terminal does not match failure evidence")
            if value.get("current_subject_hash") != failure_evidence.get("current_subject_hash"):
                errors.append("Worker execution subject does not match failure evidence")
        elif failure_evidence.get("failure_source") == VERIFICATION_FAILURE:
            if not value.get("failed_verification_authority_ids"):
                errors.append("failed verification authority identity is missing")
    elif not value.get("failed_verification_authority_ids"):
        # Envelopes written before V26.5 retain their original strict
        # verification-backed contract.  Missing the new tag is not a reason
        # to infer an execution failure.
        errors.append("failed verification authority identity is missing")
    if value.get("worker_prose_authority") != 0:
        errors.append("Worker prose must have zero recovery authority")
    if value.get("worker_prose_excluded") is not True:
        errors.append("Worker prose exclusion is not recorded")
    if contains_forbidden_recovery_transcript(value):
        errors.append("recovery failure envelope contains Worker-private transcript")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:40],
        "worker_prose_authority": 0,
        "worker_prose_excluded": value.get("worker_prose_excluded") is True,
        "failure_source": value.get("failure_source"),
        "failure_evidence_validation": variant_check,
        "model_calls": 0,
        "worker_calls": 0,
    }


def _authority_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    for key in (
        "approved_recovery_authorization", "execution_authorization",
        "authorization", "approved_authority", "authority",
    ):
        nested = value.get(key)
        if isinstance(nested, dict):
            return nested
    return value


def _approved_paths(authority: dict[str, Any]) -> list[str]:
    scope = authority.get("approved_mutation_scope")
    if not isinstance(scope, dict):
        scope = authority.get("mutation_scope") if isinstance(authority.get("mutation_scope"), dict) else {}
    contract = authority.get("execution_contract") if isinstance(authority.get("execution_contract"), dict) else {}
    return _unique_strings(
        list(scope.get("paths", []) or [])
        + list(authority.get("allowed_mutation_paths", []) or [])
        + list(contract.get("allowed_mutation_paths", []) or []),
        paths=True,
    )


def _approved_dnt_paths(authority: dict[str, Any]) -> list[str]:
    dnt = authority.get("approved_dnt")
    if isinstance(dnt, dict):
        return _unique_strings(dnt.get("paths", []) or [], paths=True)
    if isinstance(dnt, (list, tuple, set, frozenset)):
        return _unique_strings(dnt, paths=True)
    return _unique_strings(authority.get("global_do_not_touch") or authority.get("do_not_touch") or [], paths=True)


def _approved_requirements(authority: dict[str, Any]) -> list[str]:
    plan = authority.get("approved_change_plan") if isinstance(authority.get("approved_change_plan"), dict) else {}
    values = authority.get("approved_requirements") or authority.get("requirements") or plan.get("requirements") or []
    result: list[str] = []
    for item in _list(values):
        if isinstance(item, dict):
            item = item.get("requirement_id") or item.get("text") or item.get("id")
        text = _text(item, 360)
        if text and text not in result:
            result.append(text)
    return result[:64]


def _approved_verification_ids(authority: dict[str, Any]) -> list[str]:
    values = authority.get("approved_verification_contracts") or authority.get("verification_authority_ids") or []
    result: list[str] = []
    for item in _list(values):
        if isinstance(item, dict):
            item = item.get("authority_id") or item.get("verification_id") or item.get("id")
        text = _text(item, 180)
        if text and text not in result:
            result.append(text)
    return result[:64]


def _approved_oracle_ids(authority: dict[str, Any]) -> list[str]:
    values = authority.get("approved_verification_contracts") or authority.get("direct_behavior_oracles") or []
    result: list[str] = []
    for item in _list(values):
        if isinstance(item, dict):
            for key in ("oracle_id", "id", "authority_id"):
                text = _text(item.get(key), 180)
                if text and ("ORACLE" in text.upper() or key == "oracle_id"):
                    if text not in result:
                        result.append(text)
        else:
            text = _text(item, 180)
            if "ORACLE" in text.upper() and text not in result:
                result.append(text)
    return result[:64]


def _proposal_values(proposal: dict[str, Any], *keys: str) -> list[Any]:
    values: list[Any] = []
    for key in keys:
        if key in proposal:
            values.extend(_list(proposal.get(key)))
    return values


def _add_delta_record(
    dimensions: dict[str, list[dict[str, Any]]],
    dimension: str,
    *,
    requested: Any = None,
    approved: Any = None,
    reason: str,
    authority: str,
) -> None:
    record = {
        "dimension": dimension,
        "requested": _safe_projection(requested),
        "approved": _safe_projection(approved),
        "reason": _text(reason, 420),
        "authority": _text(authority, 160),
    }
    encoded = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    if not any(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str) == encoded
        for item in dimensions[dimension]
    ):
        dimensions[dimension].append(record)


def build_recovery_authority_delta(
    approved_authority: dict[str, Any] | None = None,
    recovery_need: dict[str, Any] | None = None,
    *,
    proposal: dict[str, Any] | None = None,
) -> RecoveryAuthorityDelta:
    """Compare requested recovery needs with approved authority."""
    authority = _authority_source(approved_authority or {})
    need = proposal if isinstance(proposal, dict) else (
        recovery_need if isinstance(recovery_need, dict) else {}
    )
    approved_scope = _approved_paths(authority)
    approved_dnt = _approved_dnt_paths(authority)
    approved_requirements = _approved_requirements(authority)
    approved_verification = _approved_verification_ids(authority)
    approved_oracles = _approved_oracle_ids(authority)
    dimensions = {name: [] for name in _DIMENSIONS}

    requested_paths = _unique_strings(
        _proposal_values(
            need,
            "required_mutation_paths", "mutation_paths", "new_mutation_paths",
        )
        + (
            (need.get("mutation_scope") or {}).get("paths", [])
            if isinstance(need.get("mutation_scope"), dict)
            else []
        ),
        paths=True,
    )
    for path in requested_paths:
        if path.casefold() not in {item.casefold() for item in approved_scope}:
            _add_delta_record(
                dimensions,
                "new_mutation_paths",
                requested=path,
                approved=approved_scope,
                reason="recovery requires a mutation path outside the approved mutation scope",
                authority="APPROVED_MUTATION_SCOPE",
            )
    for path in _unique_strings(_proposal_values(need, "removed_mutation_paths", "remove_paths"), paths=True):
        if path.casefold() in {item.casefold() for item in approved_scope} or path:
            _add_delta_record(
                dimensions,
                "removed_mutation_paths",
                requested=path,
                approved=approved_scope,
                reason="recovery proposal removes an approved mutation path",
                authority="APPROVED_MUTATION_SCOPE",
            )

    dnt_requested = (
        need.get("requires_dnt_change") is True
        or need.get("dnt_change") not in (None, False, "", [], {})
        or bool(_proposal_values(need, "dnt_paths", "required_dnt_paths", "do_not_touch_change"))
    )
    if dnt_requested:
        _add_delta_record(
            dimensions,
            "dnt_changes",
            requested=(
                need.get("dnt_change")
                or _proposal_values(need, "dnt_paths", "required_dnt_paths", "do_not_touch_change")
                or True
            ),
            approved=approved_dnt,
            reason="recovery requires changing or overriding the approved do-not-touch boundary",
            authority="APPROVED_DNT",
        )

    for value in _proposal_values(need, "new_requirements", "added_requirements", "required_new_requirements"):
        _add_delta_record(
            dimensions,
            "new_requirements",
            requested=value,
            approved=approved_requirements,
            reason="recovery requires a new user requirement",
            authority="APPROVED_REQUIREMENTS",
        )
    for value in _proposal_values(need, "removed_requirements", "dropped_requirements"):
        _add_delta_record(
            dimensions,
            "removed_requirements",
            requested=value,
            approved=approved_requirements,
            reason="recovery removes an approved requirement",
            authority="APPROVED_REQUIREMENTS",
        )

    ownership = _proposal_values(
        need,
        "ownership_changes", "owner_migration", "new_owner", "ownership",
    )
    if need.get("owner_migration") or need.get("new_owner") or ownership:
        _add_delta_record(
            dimensions,
            "ownership_changes",
            requested=ownership or {"owner_migration": True},
            approved=(
                authority.get("approved_interface_binding")
                or authority.get("state_ownership")
                or authority.get("execution_invariant_set_hash")
            ),
            reason="recovery changes the approved state-owner relationship",
            authority="EXECUTION_INVARIANTS.STATE_OWNER",
        )

    interface_changes = _proposal_values(
        need,
        "interface_semantic_changes", "breaking_interface",
        "interface_change", "renderStatus_return_type_change",
        "new_interface", "interface_semantics",
    )
    if any(value not in (None, False, "", [], {}) for value in interface_changes):
        _add_delta_record(
            dimensions,
            "interface_semantic_changes",
            requested=interface_changes,
            approved=authority.get("approved_interface_binding") or authority.get("interface_binding_digest"),
            reason="recovery changes an approved interface semantic or preserved return shape",
            authority="EXECUTION_INVARIANTS.INTERFACE_COMPATIBILITY",
        )

    dependency_changes = _proposal_values(
        need,
        "dependency_changes", "new_dependencies", "removed_dependencies",
        "dependency_authority",
    )
    if dependency_changes:
        _add_delta_record(
            dimensions,
            "dependency_changes",
            requested=dependency_changes,
            approved=authority.get("approved_dependencies") or authority.get("dependency_digest"),
            reason="recovery introduces a dependency authority change",
            authority="APPROVED_DEPENDENCIES",
        )

    verification_changes = _proposal_values(
        need,
        "verification_authority_changes", "verification_changes",
        "verification_weakening", "ignore_verification",
        "remove_verification_authority", "removed_verification_authorities",
    )
    if any(value not in (None, False, "", [], {}) for value in verification_changes):
        _add_delta_record(
            dimensions,
            "verification_authority_changes",
            requested=verification_changes,
            approved=approved_verification,
            reason="recovery weakens or changes a required verification authority",
            authority="V25.6.REQUIRED_EXECUTION_VERIFICATION_SET",
        )

    oracle_changes = _proposal_values(
        need, "oracle_changes", "oracle_change", "new_oracle", "removed_oracle",
    )
    if oracle_changes:
        _add_delta_record(
            dimensions,
            "oracle_changes",
            requested=oracle_changes,
            approved=approved_oracles or authority.get("verification_digest"),
            reason="recovery changes the approved direct behavior oracle",
            authority="APPROVED_DIRECT_ORACLE",
        )

    invariant_changes = _proposal_values(
        need, "invariant_changes", "invariant_change",
        "remove_invariant", "change_authorized_invariant",
    )
    if invariant_changes:
        _add_delta_record(
            dimensions,
            "invariant_changes",
            requested=invariant_changes,
            approved=authority.get("execution_invariant_set_hash"),
            reason="recovery changes a hard execution invariant",
            authority="V25.5_EXECUTION_INVARIANT_SET",
        )

    behavior_changes = _proposal_values(
        need,
        "approved_behavior_changes", "different_approved_behavior",
        "new_behavior", "behavior_change",
    )
    if behavior_changes:
        _add_delta_record(
            dimensions,
            "approved_behavior_changes",
            requested=behavior_changes,
            approved=authority.get("approved_behavior") or authority.get("plan_hash"),
            reason="recovery changes the approved product behavior",
            authority="APPROVED_PLAN",
        )

    if need.get("authority_change") or need.get("requires_authority_change"):
        _add_delta_record(
            dimensions,
            "approved_behavior_changes",
            requested=need.get("authority_change") or True,
            approved="unchanged authority",
            reason="recovery proposal explicitly requests a new authority decision",
            authority="USER_APPROVAL",
        )

    changed_dimensions = [
        dimension for dimension in _DIMENSIONS
        if dimensions[dimension]
    ]
    flattened = [
        item for dimension in _DIMENSIONS for item in dimensions[dimension]
    ]
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_AUTHORITY_DELTA,
        "empty": not bool(flattened),
        "requires_user_reapproval": bool(flattened),
        "user_reapproval_required": bool(flattened),
        "changed_dimensions": changed_dimensions,
        "dimensions": dimensions,
        "changes": flattened,
        "approved_scope": approved_scope,
        "approved_dnt": approved_dnt,
        "approved_requirements": approved_requirements,
        "approved_verification_authority_ids": approved_verification,
        "approved_oracle_ids": approved_oracles,
        "canonical_hash": "",
    }
    for dimension in _DIMENSIONS:
        # Keep the dimension names first-class as well as under dimensions;
        # this makes machine consumers explicit without requiring UI parsing.
        value[dimension] = dimensions[dimension]
    value["authority_change_required"] = bool(flattened)
    value["canonical_hash"] = canonical_hash(_without(value, "canonical_hash", "authority_delta_hash"))
    value["authority_delta_hash"] = value["canonical_hash"]
    return _freeze_record(RecoveryAuthorityDelta, value)  # type: ignore[return-value]


analyze_recovery_authority_delta = build_recovery_authority_delta
compare_recovery_authority = build_recovery_authority_delta


def validate_recovery_authority_delta(delta: dict[str, Any] | None) -> dict[str, Any]:
    value = delta if isinstance(delta, dict) else {}
    expected = canonical_hash(_without(value, "canonical_hash", "authority_delta_hash")) if value else None
    errors: list[str] = []
    if value.get("artifact_type") != RECOVERY_AUTHORITY_DELTA:
        errors.append("recovery authority delta artifact type is invalid")
    if value.get("canonical_hash") != expected or value.get("authority_delta_hash") != expected:
        errors.append("recovery authority delta hash is invalid")
    dimensions = value.get("dimensions")
    if not isinstance(dimensions, dict):
        errors.append("recovery authority delta dimensions are missing")
    else:
        expected_changed = [name for name in _DIMENSIONS if dimensions.get(name)]
        if value.get("changed_dimensions") != expected_changed:
            errors.append("recovery authority delta changed-dimension projection is invalid")
        if bool(value.get("empty")) != (not any(dimensions.get(name) for name in _DIMENSIONS)):
            errors.append("recovery authority delta empty projection is invalid")
    if bool(value.get("requires_user_reapproval")) != bool(not value.get("empty")):
        errors.append("recovery authority delta reapproval projection is invalid")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:40],
        "empty": bool(value.get("empty")),
        "user_reapproval_required": bool(value.get("user_reapproval_required")),
        "model_calls": 0,
    }


def _known_worker_failure(envelope: dict[str, Any]) -> bool:
    failed = envelope.get("failed_verification") if isinstance(envelope.get("failed_verification"), dict) else {}
    return bool(
        failed.get("authority_id")
        and failed.get("oracle_id")
        and failed.get("failed_check")
        and failed.get("detail")
        and envelope.get("worker_result_status") in {"failed", "FAIL", "VERIFICATION_FAILED"}
    )


def _worker_execution_policy(
    envelope: dict[str, Any],
    evidence: dict[str, Any],
    delta: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate the closed pre-verification eligibility predicate.

    The terminal label is only one input.  Every other predicate is explicit
    evidence so a generic Worker failure, provider outage, or missing receipt
    cannot become an autonomous recovery authority by implication.
    """
    scope = envelope.get("scope_audit") if isinstance(envelope.get("scope_audit"), dict) else {}
    dnt = envelope.get("dnt_audit") if isinstance(envelope.get("dnt_audit"), dict) else {}
    brain_clean = (
        envelope.get("brain_unchanged") is True
        and envelope.get("promotion_status") in {
            None, "", "NOT_REACHED", "INTEGRATION_NOT_READY", "INTEGRATION_FAILED",
        }
    )
    checks: dict[str, bool] = {
        "actual_worker_lifecycle": evidence.get("actual_worker_lifecycle") is True
        and _safe_int(evidence.get("worker_lifecycle_count"), 0) == 1,
        "provider_healthy": evidence.get("provider_health") == "HEALTHY"
        and evidence.get("provider_failure") is False,
        "valid_provider_handoff": evidence.get("provider_handoff_valid") is True,
        "worker_execution_failure": evidence.get("execution_related") is True
        and evidence.get("worker_terminal_code") == WORKER_NO_APPROVED_MUTATION
        and evidence.get("worker_result_status") in {"failed", "FAIL", "VERIFICATION_FAILED"},
        "no_verified_successful_completion": evidence.get("verified_successful_completion") is False,
        "v25_6_not_executed": evidence.get("v25_6_executed") is False,
        "subject_known": evidence.get("subject_known") is True,
        "subject_unchanged": evidence.get("subject_unchanged") is True
        and evidence.get("subject_before_hash") == evidence.get("subject_after_hash")
        and evidence.get("current_subject_hash") == evidence.get("subject_after_hash")
        and envelope.get("subject_before_hash") == envelope.get("current_subject_hash"),
        "known_lineage": evidence.get("lineage_status") == AUTHORIZED_EXECUTION_DESCENDANT,
        "no_unknown_manual_drift": evidence.get("unknown_manual_drift") is False,
        "scope_pass": evidence.get("scope_valid") is True and scope.get("passed") is True,
        "dnt_pass": evidence.get("dnt_valid") is True and dnt.get("passed") is True,
        "plan_unchanged": evidence.get("plan_unchanged") is True
        and bool(envelope.get("plan_id") and envelope.get("plan_hash")),
        "approval_unchanged": evidence.get("approval_unchanged") is True
        and bool(envelope.get("approval_id") and envelope.get("approval_receipt_hash")),
        "plan_binding": evidence.get("plan_id") == envelope.get("plan_id")
        and evidence.get("plan_hash") == envelope.get("plan_hash"),
        "approval_binding": evidence.get("approval_id") == envelope.get("approval_id")
        and evidence.get("approval_receipt_hash") == envelope.get("approval_receipt_hash"),
        "invariant_binding": evidence.get("execution_invariant_set_hash")
        == envelope.get("execution_invariant_set_hash"),
        "brain_valid": evidence.get("brain_valid") is True
        and evidence.get("brain_unchanged") is True
        and brain_clean,
        "not_promoted": evidence.get("promoted") is False and brain_clean
        and evidence.get("promotion_status") in {
            None, "", "NOT_REACHED", "INTEGRATION_NOT_READY", "INTEGRATION_FAILED",
        },
        "authority_delta_empty": evidence.get("authority_delta_empty") is True
        and delta.get("empty") is True,
        "legal_solution_space": evidence.get("legal_solution_space_available") is True
        and bool(evidence.get("legal_mutation_paths")),
        "full_verification_universe_available": evidence.get("full_verification_universe_available") is True
        and bool(evidence.get("verification_obligation_ids")),
        "recovery_budget_available": evidence.get("recovery_budget_available") is True,
        "not_harness_failure": evidence.get("harness_failure") is False,
        "no_approved_mutation": evidence.get("approved_mutation_count") == 0
        and evidence.get("changed_paths") == [],
        "commit_free": evidence.get("commit_count") == 0
        and evidence.get("commit") is False
        and evidence.get("filesystem_changed") is False,
        "v25_5_authority_valid": evidence.get("v25_5_authority_valid") is True,
    }
    return {
        "checks": checks,
        "eligible": all(checks.values()),
        "complete": all(
            key in evidence and evidence.get(key) is not None
            for key in _WORKER_EXECUTION_EVIDENCE_FIELDS
        ),
        "failure_source": WORKER_EXECUTION_FAILURE,
        "worker_terminal_code": evidence.get("worker_terminal_code"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def evaluate_preverification_recovery_eligibility(
    envelope: dict[str, Any] | None,
    *,
    authority_delta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Public deterministic audit of the V26.5 execution-failure predicate."""
    value = envelope if isinstance(envelope, dict) else {}
    evidence = value.get("failure_evidence") if isinstance(value.get("failure_evidence"), dict) else {}
    delta = authority_delta if isinstance(authority_delta, dict) else build_recovery_authority_delta(value, {})
    variant_check = validate_recovery_failure_evidence(evidence)
    policy = _worker_execution_policy(value, evidence, delta) if evidence else {
        "checks": {}, "eligible": False, "complete": False,
        "failure_source": value.get("failure_source"),
        "model_calls": 0, "worker_calls": 0,
    }
    policy["variant_valid"] = variant_check.get("valid") is True
    policy["eligible"] = bool(policy.get("eligible")) and policy["variant_valid"]
    policy["variant_validation"] = variant_check
    return policy


assess_preverification_recovery_eligibility = evaluate_preverification_recovery_eligibility


def _worker_execution_blocker(policy: dict[str, Any]) -> tuple[str | None, list[str]]:
    checks = policy.get("checks") if isinstance(policy.get("checks"), dict) else {}
    if not policy.get("complete") or not policy.get("variant_valid"):
        return PRE_VERIFICATION_RECOVERY_EVIDENCE_INCOMPLETE, [
            "pre-verification Worker execution evidence is incomplete or invalid",
        ]
    if not checks.get("provider_healthy") or not checks.get("valid_provider_handoff"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_PROVIDER, [
            "provider health or the provider handoff is not valid",
        ]
    if not checks.get("actual_worker_lifecycle") or not checks.get("not_harness_failure"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_HARNESS, [
            "the Worker lifecycle is not established independently of harness failure",
        ]
    if not checks.get("authority_delta_empty"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_AUTHORITY, [
            "recovery would require a non-empty authority delta",
        ]
    if not checks.get("known_lineage") or not checks.get("no_unknown_manual_drift") or not checks.get("subject_unchanged"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_DRIFT, [
            "the failed subject or execution lineage is not deterministically bound",
        ]
    if not checks.get("legal_solution_space") or not checks.get("full_verification_universe_available"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_NO_LEGAL_SPACE, [
            "no legal solution space or complete verification universe is available",
        ]
    if not checks.get("recovery_budget_available"):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_BUDGET, [
            "the autonomous recovery attempt budget is exhausted",
        ]
    if not all(checks.values()):
        return PRE_VERIFICATION_RECOVERY_BLOCKED_INCOMPLETE, [
            "one or more pre-verification eligibility predicates failed",
        ]
    return None, []


def classify_recovery_failure(
    envelope: dict[str, Any] | None,
    *,
    approved_authority: dict[str, Any] | None = None,
    recovery_need: dict[str, Any] | None = None,
    recovery_attempt_history: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Classify only from bounded deterministic evidence."""
    value = envelope if isinstance(envelope, dict) else {}
    envelope_check = validate_recovery_failure_envelope(value)
    delta = build_recovery_authority_delta(approved_authority or value, recovery_need or {})
    reasons: list[str] = []
    evidence_basis: list[str] = []
    classification = RECOVERY_CLASSIFICATION_UNCERTAIN
    worker_policy: dict[str, Any] | None = None
    failure_evidence = value.get("failure_evidence") if isinstance(value.get("failure_evidence"), dict) else {}
    failure_source = value.get("failure_source") or failure_evidence.get("failure_source")
    if (
        failure_source == WORKER_EXECUTION_FAILURE
        and failure_evidence.get("authority_delta_empty") is False
        and delta.get("empty") is True
    ):
        # Preserve an explicitly observed authority change even when the
        # caller did not separately pass a recovery proposal.  The evidence
        # cannot silently turn a non-empty delta into an empty one.
        delta = build_recovery_authority_delta(
            approved_authority or value,
            {"authority_change": True},
        )
    if value.get("brain_unchanged") is False or value.get("promotion_status") not in {
        None, "", "NOT_REACHED", "INTEGRATION_NOT_READY", "INTEGRATION_FAILED",
    }:
        classification = NON_RECOVERABLE_ARCHITECTURE_FAILURE
        reasons.append("failed state is not a clean pre-promotion Brain baseline")
        evidence_basis.append("working_brain_before_after")
    elif not envelope_check.get("valid"):
        reasons.append("failure envelope validation is incomplete")
        evidence_basis.append("failure_envelope_validation")
    elif not delta.get("empty"):
        classification = AUTHORITY_CHANGE_REQUIRED
        reasons.extend(
            str(item.get("reason"))
            for item in delta.get("changes", [])[:8]
            if isinstance(item, dict) and item.get("reason")
        )
        evidence_basis.append("recovery_authority_delta")
    else:
        if failure_source == WORKER_EXECUTION_FAILURE:
            worker_policy = evaluate_preverification_recovery_eligibility(
                value,
                authority_delta=delta,
            )
            blocker, blocker_reasons = _worker_execution_blocker(worker_policy)
            if worker_policy.get("eligible") is True:
                classification = WORKER_RECOVERABLE
                reasons.extend([
                    "supported WORKER_NO_APPROVED_MUTATION ended the Worker before any verified completion",
                    "provider handoff was healthy and the failure is execution-related",
                    "the approved scope, DNT, plan, approval, Brain, and lineage remain unchanged",
                    "the full V25.6 verification universe remains mandatory for continuation",
                ])
                evidence_basis.extend([
                    "RecoveryFailureEvidence:WORKER_EXECUTION_FAILURE",
                    "WORKER_NO_APPROVED_MUTATION",
                    "pre_verification_eligibility_predicate",
                ])
            else:
                classification = blocker or RECOVERY_CLASSIFICATION_UNCERTAIN
                reasons.extend(blocker_reasons)
                evidence_basis.extend([
                    "RecoveryFailureEvidence:WORKER_EXECUTION_FAILURE",
                    "pre_verification_eligibility_predicate",
                ])
        else:
            failure_code = _text(
                value.get("failure_code")
                or value.get("harness_failure_code")
                or value.get("execution_failure_code"),
                160,
            )
            harness_unchanged = (
                value.get("subject_before_hash") == value.get("subject_after_hash")
                and value.get("scope_audit", {}).get("passed") is True
                and value.get("dnt_audit", {}).get("passed") is True
            )
            history = [item for item in (recovery_attempt_history or []) if isinstance(item, dict)]
            floor_evidence = value.get("capability_floor_evidence")
            if (
                isinstance(floor_evidence, dict)
                and floor_evidence.get("legal_solution_space_available") is True
                and floor_evidence.get("contexts_valid") is True
                and floor_evidence.get("tools_available") is True
                and floor_evidence.get("authority_sufficient") is True
                and int(floor_evidence.get("clean_failed_recovery_count", 0) or 0) >= 2
            ) or (
                len(history) >= 2
                and all(item.get("clean") is True for item in history[-2:])
            ):
                classification = CAPABILITY_FLOOR
                reasons.append("bounded evidence records repeated clean failures with legal authority available")
                evidence_basis.append("bounded_capability_floor_evidence")
            elif failure_code in _KNOWN_HARNESS_CODES and harness_unchanged:
                classification = HARNESS_RECOVERABLE
                reasons.append("known system-owned execution mechanics failed while approved semantics and subject remained unchanged")
                evidence_basis.extend(["harness_failure_code", "mutation_scope_audit", "dnt_audit"])
            elif _known_worker_failure(value):
                classification = WORKER_RECOVERABLE
                reasons.extend([
                    "mandatory verification failure identifies an incomplete implementation",
                    "approved mutation scope and DNT audits remain passing",
                    "the failed obligation is already inside the approved verification authority",
                    "no authority-bearing change is present in the recovery delta",
                ])
                evidence_basis.extend([
                    "failed_verification_receipt",
                    "mutation_scope_audit",
                    "dnt_audit",
                    "V25.6_ExecutionVerificationClosure",
                ])
            else:
                reasons.append("deterministic evidence does not establish a legal recovery class")
                evidence_basis.append("insufficient_failure_evidence")
    if classification == RECOVERY_CLASSIFICATION_UNCERTAIN:
        user_reapproval = bool(not delta.get("empty"))
    else:
        user_reapproval = bool(classification == AUTHORITY_CHANGE_REQUIRED or not delta.get("empty"))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "RecoveryClassification",
        "classification": classification,
        "recovery_class": classification,
        "recoverable": classification in {HARNESS_RECOVERABLE, WORKER_RECOVERABLE},
        "authority_delta": delta,
        "authority_delta_empty": bool(delta.get("empty")),
        "USER_REAPPROVAL_REQUIRED": user_reapproval,
        "user_reapproval_required": user_reapproval,
        "reasons": list(dict.fromkeys(reasons))[:12],
        "evidence_basis": list(dict.fromkeys(evidence_basis))[:12],
        "failure_envelope_valid": envelope_check.get("valid") is True,
        "failure_source": failure_source,
        "failure_source_provenance": {
            "variant": failure_source,
            "explicit": isinstance(value.get("failure_evidence"), dict),
            "authority": "deterministic evidence only",
        },
        "preverification_eligibility": worker_policy,
        "blocker": classification if classification not in {
            RECOVERY_CLASSIFICATION_UNCERTAIN, HARNESS_RECOVERABLE,
            WORKER_RECOVERABLE, AUTHORITY_CHANGE_REQUIRED, CAPABILITY_FLOOR,
            NON_RECOVERABLE_ARCHITECTURE_FAILURE,
        } else None,
        "model_calls": 0,
        "worker_calls": 0,
    }


classify_recovery = classify_recovery_failure
classify_failure_for_recovery = classify_recovery_failure
build_recovery_classification = classify_recovery_failure
create_recovery_classification = classify_recovery_failure


def _receipt(value: dict[str, Any], hash_field: str = "receipt_hash") -> dict[str, Any]:
    result = _copy(value)
    result[hash_field] = canonical_hash(_without(result, hash_field))
    return result


def build_authorized_execution_lineage(
    envelope: dict[str, Any] | None,
    *,
    authorization: dict[str, Any] | None = None,
    worker_contract: dict[str, Any] | None = None,
) -> AuthorizedExecutionLineage:
    """Bind baseline, approved execution receipts, failed subject, and closure."""
    value = envelope if isinstance(envelope, dict) else {}
    auth = _authority_source(authorization or value)
    contract = worker_contract if isinstance(worker_contract, dict) else {}
    mutation = _receipt({
        "artifact_type": "AuthorizedMutationReceipt",
        "execution_id": value.get("execution_id"),
        "execution_start_id": value.get("execution_start_id"),
        "changed_paths": _copy((value.get("committed_mutation_manifest") or {}).get("changed_paths", [])),
        "created_paths": _copy((value.get("committed_mutation_manifest") or {}).get("created_paths", [])),
        "deleted_paths": _copy((value.get("committed_mutation_manifest") or {}).get("deleted_paths", [])),
        "committed_paths": _copy((value.get("committed_mutation_manifest") or {}).get("committed_paths", [])),
        "scope_status": (value.get("scope_audit") or {}).get("status"),
        "scope_passed": (value.get("scope_audit") or {}).get("passed") is True,
        "source": "authorized_worker_execution_lifecycle",
    })
    scope = _receipt({
        "artifact_type": "AuthorizedMutationScopeReceipt",
        "approved_paths": _approved_paths(auth) or _unique_strings(
            (value.get("committed_mutation_manifest") or {}).get("committed_paths", []),
            paths=True,
        ),
        "observed_paths": _copy((value.get("scope_audit") or {}).get("changed_paths", [])),
        "out_of_scope_paths": _copy((value.get("scope_audit") or {}).get("out_of_scope_paths", [])),
        "passed": (value.get("scope_audit") or {}).get("passed") is True,
        "scope_digest": auth.get("mutation_scope_digest"),
        "source": "V25.1_approval_bound_execution_scope_audit",
    })
    dnt = _receipt({
        "artifact_type": "AuthorizedDNTReceipt",
        "approved_paths": _approved_dnt_paths(auth),
        "changed_paths": _copy((value.get("dnt_audit") or {}).get("changed_paths", [])),
        "dnt_violations": (value.get("dnt_audit") or {}).get("dnt_violations", 0),
        "passed": (value.get("dnt_audit") or {}).get("passed") is True,
        "dnt_digest": (value.get("dnt_audit") or {}).get("dnt_digest") or auth.get("dnt_digest"),
        "source": "V25.1_approval_bound_execution_dnt_audit",
    })
    precommit = value.get("precommit_audit_summary") if isinstance(value.get("precommit_audit_summary"), dict) else {}
    precommit_receipts = [
        _receipt({
            "artifact_type": "PreCommitInvariantReceipt",
            "source_receipt_hash": receipt_hash,
            "authority_set_hash": precommit.get("authority_set_hash") or value.get("execution_invariant_set_hash"),
            "allowed": precommit.get("passed") is True,
            "source": "V25.5_PreCommitExecutionInvariantGate",
        })
        for receipt_hash in _unique_strings(precommit.get("receipt_hashes") or [], limit=24)
    ]
    start = value.get("execution_start_receipt") if isinstance(value.get("execution_start_receipt"), dict) else {}
    start_binding = _receipt({
        "artifact_type": "ExecutionStartBinding",
        "execution_start_id": value.get("execution_start_id") or start.get("execution_start_id"),
        "execution_start_receipt_hash": start.get("receipt_hash"),
        "authorization_hash": value.get("execution_authorization_hash") or auth.get("authorization_hash"),
        "approval_receipt_hash": value.get("approval_receipt_hash") or auth.get("approval_receipt_hash"),
        "plan_id": value.get("plan_id") or auth.get("canonical_plan_id"),
        "plan_hash": value.get("plan_hash") or auth.get("canonical_plan_hash"),
        "worker_contract_id": value.get("worker_contract_id") or contract.get("execution_contract_id"),
        "worker_contract_hash": value.get("worker_contract_hash") or contract.get("contract_hash"),
        "pre_subject_hash": value.get("subject_before_hash"),
        "pre_brain_hash": value.get("brain_before_hash"),
    }, hash_field="binding_hash")
    lineage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": AUTHORIZED_EXECUTION_LINEAGE,
        "status": AUTHORIZED_EXECUTION_DESCENDANT,
        "subject_drift": AUTHORIZED_EXECUTION_DESCENDANT,
        "original_approved_subject_hash": value.get("subject_before_hash"),
        "original_subject_hash": value.get("subject_before_hash"),
        "approved_baseline_subject_hash": value.get("subject_before_hash"),
        "current_failed_subject_hash": value.get("current_subject_hash") or value.get("subject_after_hash"),
        "current_subject_hash": value.get("current_subject_hash") or value.get("subject_after_hash"),
        "resulting_subject_hash": value.get("current_subject_hash") or value.get("subject_after_hash"),
        "execution_id": value.get("execution_id"),
        "execution_start_id": value.get("execution_start_id") or start.get("execution_start_id"),
        "approval_id": value.get("approval_id"),
        "approval_receipt_hash": value.get("approval_receipt_hash"),
        "execution_authorization_id": value.get("execution_authorization_id") or auth.get("authorization_id"),
        "execution_authorization_hash": value.get("execution_authorization_hash") or auth.get("authorization_hash"),
        "plan_id": value.get("plan_id") or auth.get("canonical_plan_id"),
        "plan_hash": value.get("plan_hash") or auth.get("canonical_plan_hash"),
        "worker_contract_id": value.get("worker_contract_id") or contract.get("execution_contract_id"),
        "worker_contract_hash": value.get("worker_contract_hash") or contract.get("contract_hash"),
        "mutation_receipt": mutation,
        "scope_receipt": scope,
        "dnt_receipt": dnt,
        "precommit_invariant_receipts": precommit_receipts,
        "execution_start_binding": start_binding,
        "failure_source": value.get("failure_source")
        or ((value.get("failure_evidence") or {}).get("failure_source")
            if isinstance(value.get("failure_evidence"), dict) else None),
        "failure_evidence_hash": (
            (value.get("failure_evidence") or {}).get("canonical_hash")
            if isinstance(value.get("failure_evidence"), dict) else None
        ),
        "execution_failure_code": (
            (value.get("failure_evidence") or {}).get("worker_terminal_code")
            if isinstance(value.get("failure_evidence"), dict)
            and (value.get("failure_evidence") or {}).get("failure_source") == WORKER_EXECUTION_FAILURE
            else None
        ),
        "failed_verification_closure_hash": value.get("execution_verification_closure_hash"),
        "failed_verification_authority_ids": _copy(value.get("failed_verification_authority_ids", [])),
        "verification_digest": value.get("verification_digest"),
        "coverage_hash": value.get("coverage_hash"),
        "execution_invariant_set_hash": value.get("execution_invariant_set_hash"),
        "brain_before_hash": value.get("brain_before_hash"),
        "brain_after_hash": value.get("brain_after_hash"),
        "brain_unchanged": value.get("brain_unchanged") is True,
        "valid": True,
        "promotion_status": value.get("promotion_status") or "NOT_REACHED",
        "canonical_lineage_hash": "",
    }
    lineage["canonical_lineage_hash"] = canonical_hash(_without(lineage, "canonical_lineage_hash", "lineage_hash"))
    lineage["lineage_hash"] = lineage["canonical_lineage_hash"]
    lineage["canonical_hash"] = lineage["canonical_lineage_hash"]
    return _freeze_record(AuthorizedExecutionLineage, lineage)  # type: ignore[return-value]


create_authorized_execution_lineage = build_authorized_execution_lineage
build_execution_lineage = build_authorized_execution_lineage


def _validate_hashed_record(record: Any, hash_field: str) -> bool:
    if not isinstance(record, dict):
        return False
    expected = canonical_hash(_without(record, hash_field))
    return record.get(hash_field) == expected


def validate_authorized_execution_lineage(
    lineage: dict[str, Any] | None,
    *,
    current_subject_hash: str | None = None,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = lineage if isinstance(lineage, dict) else {}
    errors: list[str] = []
    expected = canonical_hash(
        _without(value, "canonical_lineage_hash", "lineage_hash", "canonical_hash"),
    ) if value else None
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("authorized execution lineage schema is invalid")
    if value.get("artifact_type") != AUTHORIZED_EXECUTION_LINEAGE:
        errors.append("authorized execution lineage artifact type is invalid")
    if (
        value.get("canonical_lineage_hash") != expected
        or value.get("lineage_hash") != expected
        or value.get("canonical_hash") != expected
    ):
        errors.append("authorized execution lineage hash is invalid")
    for record, field, label in (
        (value.get("mutation_receipt"), "receipt_hash", "mutation receipt"),
        (value.get("scope_receipt"), "receipt_hash", "scope receipt"),
        (value.get("dnt_receipt"), "receipt_hash", "DNT receipt"),
        (value.get("execution_start_binding"), "binding_hash", "execution-start binding"),
    ):
        if not _validate_hashed_record(record, field):
            errors.append(f"{label} is invalid")
    for item in value.get("precommit_invariant_receipts", []) or []:
        if not _validate_hashed_record(item, "receipt_hash"):
            errors.append("precommit invariant receipt is invalid")
    expected_current = _text(current_subject_hash, 128) if current_subject_hash else _text(
        value.get("current_failed_subject_hash") or value.get("resulting_subject_hash"),
        128,
    )
    if expected_current != value.get("resulting_subject_hash"):
        errors.append("current subject is not the lineage-bound failed subject")
        subject_drift = EXTERNAL_UNAUTHORIZED_DRIFT
    else:
        subject_drift = AUTHORIZED_EXECUTION_DESCENDANT
    if value.get("original_approved_subject_hash") != value.get("approved_baseline_subject_hash"):
        errors.append("approved baseline subject binding is inconsistent")
    if value.get("brain_unchanged") is not True:
        errors.append("failed execution Brain is not a clean unchanged baseline")
    scope = value.get("scope_receipt") if isinstance(value.get("scope_receipt"), dict) else {}
    dnt = value.get("dnt_receipt") if isinstance(value.get("dnt_receipt"), dict) else {}
    if scope.get("passed") is not True or scope.get("out_of_scope_paths"):
        errors.append("authorized mutation scope is not valid")
    if dnt.get("passed") is not True or dnt.get("changed_paths"):
        errors.append("authorized DNT receipt is not valid")
    if isinstance(envelope, dict):
        bindings = (
            ("current_failed_subject_hash", envelope.get("current_subject_hash")),
            ("failed_verification_closure_hash", envelope.get("execution_verification_closure_hash")),
            ("verification_digest", envelope.get("verification_digest")),
            ("coverage_hash", envelope.get("coverage_hash")),
            ("execution_invariant_set_hash", envelope.get("execution_invariant_set_hash")),
        )
        for field, expected_value in bindings:
            if expected_value not in (None, "") and value.get(field) != expected_value:
                errors.append(f"lineage binding is invalid: {field}")
        envelope_source = envelope.get("failure_source")
        if envelope_source:
            if value.get("failure_source") != envelope_source:
                errors.append("lineage binding is invalid: failure_source")
            envelope_evidence = envelope.get("failure_evidence")
            if isinstance(envelope_evidence, dict) and envelope_evidence.get("canonical_hash"):
                if value.get("failure_evidence_hash") != envelope_evidence.get("canonical_hash"):
                    errors.append("lineage binding is invalid: failure_evidence_hash")
            if envelope_source == WORKER_EXECUTION_FAILURE and value.get("execution_failure_code") != (
                envelope_evidence.get("worker_terminal_code") if isinstance(envelope_evidence, dict) else None
            ):
                errors.append("lineage binding is invalid: execution_failure_code")
        if value.get("execution_id") != envelope.get("execution_id"):
            errors.append("lineage execution identity is invalid")
    if errors and subject_drift == AUTHORIZED_EXECUTION_DESCENDANT and current_subject_hash and current_subject_hash != value.get("resulting_subject_hash"):
        subject_drift = EXTERNAL_UNAUTHORIZED_DRIFT
    valid = not errors
    return {
        "valid": valid,
        "status": AUTHORIZED_EXECUTION_DESCENDANT if valid else INVALID_AUTHORIZED_EXECUTION_DESCENDANT,
        "subject_drift": subject_drift if not valid or subject_drift == EXTERNAL_UNAUTHORIZED_DRIFT else AUTHORIZED_EXECUTION_DESCENDANT,
        "external_unauthorized_drift": subject_drift == EXTERNAL_UNAUTHORIZED_DRIFT,
        "errors": list(dict.fromkeys(errors))[:60],
        "canonical_lineage_hash": value.get("canonical_lineage_hash"),
        "model_calls": 0,
        "worker_calls": 0,
    }


validate_execution_lineage = validate_authorized_execution_lineage


def decide_recovery_eligibility(
    envelope: dict[str, Any] | None,
    classification: dict[str, Any] | str | None = None,
    *,
    authority_delta: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    current_subject_hash: str | None = None,
    authorization: dict[str, Any] | None = None,
    attempt_accounting: dict[str, Any] | None = None,
    recovery_budget_available: bool | None = None,
) -> dict[str, Any]:
    value = envelope if isinstance(envelope, dict) else {}
    classified = classification if isinstance(classification, dict) else None
    class_name = (
        classified.get("classification")
        if classified is not None
        else _text(classification, 160)
    )
    if not class_name:
        classified = classify_recovery_failure(value, approved_authority=authorization or value)
        class_name = classified.get("classification")
    delta = authority_delta if isinstance(authority_delta, dict) else (
        classified.get("authority_delta") if isinstance(classified, dict) and isinstance(classified.get("authority_delta"), dict)
        else build_recovery_authority_delta(authorization or value, {})
    )
    delta_check = validate_recovery_authority_delta(delta)
    lineage_check = (
        validate_authorized_execution_lineage(
            lineage,
            current_subject_hash=current_subject_hash,
            envelope=value,
        )
        if lineage is not None
        else {"valid": False, "errors": ["authorized execution lineage is missing"], "status": INVALID_AUTHORIZED_EXECUTION_DESCENDANT}
    )
    envelope_check = validate_recovery_failure_envelope(value)
    failure_evidence = value.get("failure_evidence") if isinstance(value.get("failure_evidence"), dict) else {}
    explicit_worker_failure = value.get("failure_source") == WORKER_EXECUTION_FAILURE
    execution_policy = (
        evaluate_preverification_recovery_eligibility(value, authority_delta=delta)
        if explicit_worker_failure else None
    )
    if recovery_budget_available is None:
        if isinstance(attempt_accounting, dict):
            recovery_budget_available = bool(
                can_start_recovery_attempt(attempt_accounting, attempt_index=1).get("allowed")
            )
        else:
            recovery_budget_available = True
    if execution_policy is not None:
        execution_policy["checks"]["recovery_budget_available"] = bool(
            execution_policy.get("checks", {}).get("recovery_budget_available")
            and recovery_budget_available
        )
        execution_policy["eligible"] = bool(
            execution_policy.get("eligible") and recovery_budget_available
        )
    checks = {
        "existing_approval_valid": bool(value.get("approval_id") and value.get("approval_receipt_hash") and value.get("plan_hash")),
        "plan_unchanged": bool(value.get("plan_id") and value.get("plan_hash")),
        "failure_verified": (
            bool(execution_policy and execution_policy.get("eligible"))
            if explicit_worker_failure
            else bool(value.get("failed_verification_authority_ids"))
            and value.get("worker_terminal_state") == "VERIFICATION_FAILED"
        ),
        "lineage_valid": lineage_check.get("valid") is True,
        "authority_delta_empty": delta.get("empty") is True and delta_check.get("valid") is True,
        "current_subject_matches_lineage": (
            lineage_check.get("subject_drift") == AUTHORIZED_EXECUTION_DESCENDANT
            and not lineage_check.get("external_unauthorized_drift")
        ),
        "brain_not_promoted": value.get("brain_unchanged") is True and value.get("promotion_status") in {
            "NOT_REACHED", "INTEGRATION_NOT_READY", "INTEGRATION_FAILED", None, "",
        },
        "scope_unchanged": value.get("scope_audit", {}).get("passed") is True,
        "dnt_unchanged": value.get("dnt_audit", {}).get("passed") is True,
        "verification_authority_unchanged": not any(
            item.get("dimension") == "verification_authority_changes"
            for item in delta.get("changes", []) if isinstance(item, dict)
        ),
        "invariants_unchanged": not any(
            item.get("dimension") == "invariant_changes"
            for item in delta.get("changes", []) if isinstance(item, dict)
        ),
        "failure_envelope_valid": envelope_check.get("valid") is True,
    }
    if execution_policy is not None:
        checks.update({
            f"preverification_{key}": bool(passed)
            for key, passed in (execution_policy.get("checks") or {}).items()
        })
        checks["failure_source_explicit"] = explicit_worker_failure
        checks["no_fake_verification_receipt"] = not any(
            value.get(key)
            for key in (
                "failed_verification_authority_ids", "execution_verification_closure_hash",
                "execution_verification_closure",
            )
        )
    recoverable_class = class_name in {HARNESS_RECOVERABLE, WORKER_RECOVERABLE}
    eligible = recoverable_class and all(checks.values())
    user_reapproval = bool(not delta.get("empty"))
    reasons: list[str] = []
    if not recoverable_class:
        reasons.append(f"recovery class is not autonomously eligible: {class_name}")
    for key, passed in checks.items():
        if not passed:
            reasons.append(f"eligibility prerequisite failed: {key}")
    if user_reapproval:
        reasons.append("recovery authority delta requires new user authority")
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "RecoveryEligibilityDecision",
        "status": RECOVERY_ELIGIBLE if eligible else RECOVERY_BLOCKED,
        "eligible": eligible,
        "dispatch_allowed": eligible,
        "classification": class_name,
        "authority_delta": delta,
        "authority_delta_empty": delta.get("empty") is True,
        "USER_REAPPROVAL_REQUIRED": user_reapproval,
        "user_reapproval_required": user_reapproval,
        "checks": checks,
        "lineage_validation": lineage_check,
        "failure_envelope_validation": envelope_check,
        "failure_source": value.get("failure_source"),
        "preverification_eligibility": execution_policy,
        "recovery_budget_available": bool(recovery_budget_available),
        "reasons": list(dict.fromkeys(reasons))[:40],
        "model_calls": 0,
        "worker_calls": 0,
    }


assess_recovery_eligibility = decide_recovery_eligibility
recovery_eligibility_decision = decide_recovery_eligibility
build_recovery_eligibility = decide_recovery_eligibility


def derive_recovery_reporting_state(
    *,
    initial_verification_passed: bool = False,
    initial_worker_succeeded: bool = False,
    recovery_required: bool | None = None,
    classification: dict[str, Any] | str | None = None,
    eligibility: dict[str, Any] | None = None,
    recovery_dispatched: bool = False,
    recovery_completed: bool = False,
) -> dict[str, Any]:
    """Project a safe external-finalizer state without granting authority.

    ``RECOVERY_NOT_REQUIRED`` is reserved for a verified initial success.
    A failed initial Worker with uncertain or blocked recovery remains
    explicitly recoverable-as-a-reporting-state, never a silent success.
    """
    required = (
        bool(recovery_required)
        if recovery_required is not None
        else not bool(initial_verification_passed or initial_worker_succeeded)
    )
    class_name = (
        classification.get("classification")
        if isinstance(classification, dict)
        else _text(classification, 180)
    )
    eligible = bool(isinstance(eligibility, dict) and eligibility.get("eligible") is True)
    if not required:
        state = "RECOVERY_NOT_REQUIRED"
    elif recovery_completed:
        state = RECOVERY_COMPLETED
    elif recovery_dispatched:
        state = RECOVERY_REQUIRED_DISPATCHED
    elif class_name == RECOVERY_CLASSIFICATION_UNCERTAIN or not class_name:
        state = RECOVERY_REQUIRED_CLASSIFICATION_UNCERTAIN
    elif class_name == AUTHORITY_CHANGE_REQUIRED or (
        isinstance(eligibility, dict)
        and eligibility.get("user_reapproval_required") is True
    ):
        state = RECOVERY_REQUIRED_AUTHORITY_CHANGE
    elif not eligible:
        state = RECOVERY_REQUIRED_BUT_NOT_DISPATCHABLE
    else:
        state = RECOVERY_REQUIRED_CLASSIFIED
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "RecoveryReportingState",
        "state": state,
        "recovery_required": required,
        "initial_verification_passed": bool(initial_verification_passed),
        "initial_worker_succeeded": bool(initial_worker_succeeded),
        "classification": class_name,
        "eligibility": "ELIGIBLE" if eligible else "BLOCKED_OR_UNKNOWN",
        "recovery_dispatched": bool(recovery_dispatched),
        "recovery_completed": bool(recovery_completed),
        "worker_prose_authority": 0,
        "model_calls": 0,
        "worker_calls": 0,
    }


project_recovery_reporting_state = derive_recovery_reporting_state
classify_recovery_reporting_state = derive_recovery_reporting_state


def build_approved_recovery_authorization(
    envelope: dict[str, Any] | None,
    *,
    classification: dict[str, Any] | str | None = None,
    authority_delta: dict[str, Any] | None = None,
    lineage: dict[str, Any] | None = None,
    eligibility: dict[str, Any] | None = None,
    approved_authority: dict[str, Any] | None = None,
) -> ApprovedRecoveryAuthorization:
    value = envelope if isinstance(envelope, dict) else {}
    auth = _authority_source(approved_authority or value)
    classified = classification if isinstance(classification, dict) else (
        classify_recovery_failure(value, approved_authority=auth)
        if classification is None
        else {"classification": classification}
    )
    delta = authority_delta if isinstance(authority_delta, dict) else classified.get("authority_delta")
    if not isinstance(delta, dict):
        delta = build_recovery_authority_delta(auth, {})
    lineage_value = lineage if isinstance(lineage, dict) else build_authorized_execution_lineage(value, authorization=auth)
    lineage_check = validate_authorized_execution_lineage(lineage_value, envelope=value)
    decision = eligibility if isinstance(eligibility, dict) else decide_recovery_eligibility(
        value,
        classified,
        authority_delta=delta,
        lineage=lineage_value,
        authorization=auth,
    )
    ready = decision.get("eligible") is True
    approved_scope = value.get("committed_mutation_manifest", {}).get("committed_paths", [])
    if not approved_scope:
        approved_scope = _approved_paths(auth)
    approved_dnt = _approved_dnt_paths(auth)
    verification_ids = _approved_verification_ids(auth)
    if not verification_ids:
        verification_ids = _unique_strings(
            value.get("failed_verification_authority_ids", [])
            or value.get("required_authority_ids", [])
            or (
                (value.get("failure_evidence") or {}).get("verification_obligation_ids", [])
                if isinstance(value.get("failure_evidence"), dict) else []
            ),
            limit=64,
        )
    failure_source = value.get("failure_source")
    execution_failure = value.get("failure_evidence") if isinstance(value.get("failure_evidence"), dict) else {}
    authorization_value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": APPROVED_RECOVERY_AUTHORIZATION,
        "status": RECOVERY_AUTHORIZATION_READY if ready else RECOVERY_AUTHORIZATION_BLOCKED,
        "recovery_authorization_status": RECOVERY_AUTHORIZATION_READY if ready else RECOVERY_AUTHORIZATION_BLOCKED,
        "terminal_state": RECOVERY_AUTHORIZATION_READY if ready else RECOVERY_AUTHORIZATION_BLOCKED,
        "authorization_id": "",
        "authorization_hash": "",
        "derived_from_existing_approval": True,
        "new_user_approval_created": False,
        "user_reapproval_required": bool(decision.get("USER_REAPPROVAL_REQUIRED")),
        "USER_REAPPROVAL_REQUIRED": bool(decision.get("USER_REAPPROVAL_REQUIRED")),
        "approval_id": value.get("approval_id"),
        "approval_receipt_hash": value.get("approval_receipt_hash"),
        "parent_execution_authorization_id": value.get("execution_authorization_id"),
        "parent_execution_authorization_hash": value.get("execution_authorization_hash"),
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "approved_plan_id": value.get("plan_id"),
        "approved_plan_hash": value.get("plan_hash"),
        "failed_execution_id": value.get("execution_id"),
        "failed_worker_contract_id": value.get("worker_contract_id"),
        "failed_worker_contract_hash": value.get("worker_contract_hash"),
        "failure_envelope_hash": value.get("canonical_failure_envelope_hash"),
        "failure_source": failure_source,
        "execution_failure_code": (
            execution_failure.get("worker_terminal_code")
            if failure_source == WORKER_EXECUTION_FAILURE else None
        ),
        "verification_was_executed": failure_source == VERIFICATION_FAILURE,
        "no_fake_verification_receipt": failure_source != WORKER_EXECUTION_FAILURE
        or not value.get("failed_verification_authority_ids"),
        "failure_classification": classified.get("classification"),
        "authority_delta_hash": delta.get("canonical_hash") or delta.get("authority_delta_hash"),
        "authority_delta_empty": delta.get("empty") is True,
        "lineage_hash": lineage_value.get("canonical_lineage_hash"),
        "lineage_status": lineage_check.get("status"),
        "current_failed_subject_hash": value.get("current_subject_hash"),
        "current_brain_hash": value.get("brain_after_hash"),
        "approved_mutation_scope": {
            "paths": _unique_strings(approved_scope, paths=True),
            "digest": auth.get("mutation_scope_digest"),
        },
        "approved_scope": {
            "paths": _unique_strings(approved_scope, paths=True),
            "digest": auth.get("mutation_scope_digest"),
        },
        "approved_dnt": {
            "paths": approved_dnt,
            "digest": auth.get("dnt_digest"),
        },
        "do_not_touch": approved_dnt,
        "approved_interface_binding": _safe_projection(
            auth.get("approved_interface_binding") or value.get("approved_interface_binding") or {
                "preserve": ["renderStatus primitive string", "PauseController ownership"],
            },
        ),
        "verification_authority_ids": verification_ids,
        "verification_digest": value.get("verification_digest") or auth.get("verification_digest"),
        "coverage_hash": value.get("coverage_hash") or auth.get("verification_obligation_coverage_hash"),
        "execution_invariant_set_hash": value.get("execution_invariant_set_hash") or auth.get("execution_invariant_set_hash"),
        "scope_unchanged": value.get("scope_audit", {}).get("passed") is True,
        "dnt_unchanged": value.get("dnt_audit", {}).get("passed") is True,
        "verification_authority_unchanged": delta.get("empty") is True,
        "invariants_unchanged": delta.get("empty") is True,
        "eligibility_status": decision.get("status"),
        "blocking_reasons": _copy(decision.get("reasons", [])),
        "canonical_recovery_authorization_hash": "",
    }
    authorization_value["authorization_id"] = "RECOVERY-AUTH-" + canonical_hash(
        _without(authorization_value, "authorization_id", "authorization_hash", "canonical_recovery_authorization_hash"),
    )[:24].upper()
    authorization_value["authorization_hash"] = canonical_hash(
        _without(authorization_value, "authorization_hash", "canonical_recovery_authorization_hash"),
    )
    authorization_value["canonical_recovery_authorization_hash"] = authorization_value["authorization_hash"]
    return _freeze_record(ApprovedRecoveryAuthorization, authorization_value)  # type: ignore[return-value]


authorize_recovery = build_approved_recovery_authorization
create_approved_recovery_authorization = build_approved_recovery_authorization
create_recovery_authorization = build_approved_recovery_authorization


def validate_approved_recovery_authorization(
    authorization: dict[str, Any] | None,
    *,
    envelope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = authorization if isinstance(authorization, dict) else {}
    expected = canonical_hash(_without(value, "authorization_hash", "canonical_recovery_authorization_hash")) if value else None
    errors: list[str] = []
    if value.get("artifact_type") != APPROVED_RECOVERY_AUTHORIZATION:
        errors.append("approved recovery authorization artifact type is invalid")
    if value.get("authorization_hash") != expected or value.get("canonical_recovery_authorization_hash") != expected:
        errors.append("approved recovery authorization hash is invalid")
    if value.get("status") == RECOVERY_AUTHORIZATION_READY:
        for key in ("approval_id", "approval_receipt_hash", "plan_hash", "lineage_hash", "failure_envelope_hash"):
            if not value.get(key):
                errors.append(f"ready recovery authorization is missing {key}")
        if value.get("user_reapproval_required") is not False:
            errors.append("ready recovery authorization requires user reapproval")
        if value.get("authority_delta_empty") is not True:
            errors.append("ready recovery authorization has a non-empty authority delta")
    if isinstance(envelope, dict):
        for key, expected_value in (
            ("plan_hash", envelope.get("plan_hash")),
            ("approval_receipt_hash", envelope.get("approval_receipt_hash")),
            ("current_failed_subject_hash", envelope.get("current_subject_hash")),
        ):
            if expected_value not in (None, "") and value.get(key) != expected_value:
                errors.append(f"recovery authorization binding is invalid: {key}")
    return {
        "valid": not errors,
        "ready": value.get("status") == RECOVERY_AUTHORIZATION_READY and not errors,
        "errors": list(dict.fromkeys(errors))[:40],
        "model_calls": 0,
        "worker_calls": 0,
    }


def _preservation_constraints(value: dict[str, Any], authorization: dict[str, Any]) -> list[str]:
    constraints = [
        "preserve the approved renderStatus primitive string interface",
        "preserve PauseController as the pause-state owner",
        "preserve the approved Escape and movement behavior",
    ]
    dnt = authorization.get("approved_dnt") if isinstance(authorization.get("approved_dnt"), dict) else {}
    for path in dnt.get("paths", []) or []:
        constraints.append(f"do not modify {_path(path)}")
    interfaces = authorization.get("approved_interface_binding")
    if isinstance(interfaces, dict):
        text = json.dumps(interfaces, ensure_ascii=False, sort_keys=True, default=str)
        if "PauseController.togglePause" in text:
            constraints.append("reuse PauseController.togglePause")
    return list(dict.fromkeys(constraints))[:12]


def build_recovery_mission(
    envelope: dict[str, Any] | None,
    authorization: dict[str, Any] | None = None,
    *,
    classification: dict[str, Any] | str | None = None,
    attempt_index: int = 1,
    recovery_budget: int = MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS,
) -> RecoveryMission:
    value = envelope if isinstance(envelope, dict) else {}
    auth = authorization if isinstance(authorization, dict) else {}
    class_name = (
        classification.get("classification")
        if isinstance(classification, dict)
        else (_text(classification, 160) if classification else auth.get("failure_classification"))
    )
    ready = (
        auth.get("status") == RECOVERY_AUTHORIZATION_READY
        and class_name in {None, HARNESS_RECOVERABLE, WORKER_RECOVERABLE}
        and 0 < int(attempt_index or 0) <= int(recovery_budget or 0)
    )
    failure_source = value.get("failure_source")
    execution_evidence = value.get("failure_evidence") if isinstance(value.get("failure_evidence"), dict) else {}
    worker_execution_failure = failure_source == WORKER_EXECUTION_FAILURE
    failed = value.get("failed_verification") if isinstance(value.get("failed_verification"), dict) else {}
    failed_authorities = _unique_strings(
        [] if worker_execution_failure else (
            value.get("failed_verification_authority_ids") or [failed.get("authority_id")]
        ),
        limit=24,
    )
    failed_obligations = _unique_strings(
        [] if worker_execution_failure else value.get("execution_time_failed_obligations") or [],
        limit=32,
    )
    recovery_execution_id = f"RECOVERY-{value.get('worker_contract_id') or value.get('execution_id') or 'EXEC'}-R{int(attempt_index or 1)}"
    if worker_execution_failure:
        objective = (
            "Continue the approved task after the Worker ended with the "
            f"execution terminal {execution_evidence.get('worker_terminal_code') or WORKER_NO_APPROVED_MUTATION} "
            "before a verified completion or V25.6 execution. Re-establish "
            "an approved mutation and earn the complete existing verification "
            "obligations while preserving every approved behavior, scope, DNT, "
            "interface, ownership, invariant, and authority. Choose the "
            "implementation; this mission does not prescribe a code patch."
        )
    else:
        objective = (
            "Satisfy the failed mandatory verification authority "
            f"{failed.get('authority_id') or 'identified authority'}"
            f" / {failed.get('oracle_id') or 'identified oracle'}"
            f" for the failed {failed.get('failed_check') or 'verification condition'}"
            f" ({failed.get('detail') or 'deterministic failed detail'}), "
            "while preserving every approved behavior, scope, DNT, interface, "
            "ownership, invariant, and verification authority. Choose the "
            "implementation; this mission does not prescribe a code patch."
        )
    mission: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_MISSION,
        "status": RECOVERY_MISSION_READY if ready else RECOVERY_MISSION_BLOCKED,
        "mission_id": "",
        "parent_plan_id": value.get("plan_id"),
        "parent_plan_hash": value.get("plan_hash"),
        "plan_id": value.get("plan_id"),
        "plan_hash": value.get("plan_hash"),
        "approval_id": value.get("approval_id"),
        "approval_receipt_hash": value.get("approval_receipt_hash"),
        "approval_hash": value.get("approval_receipt_hash"),
        "parent_execution_id": value.get("execution_id"),
        "recovery_execution_id": recovery_execution_id,
        "failed_worker_contract_id": value.get("worker_contract_id"),
        "failed_worker_contract_hash": value.get("worker_contract_hash"),
        "failure_envelope_hash": value.get("canonical_failure_envelope_hash"),
        "failure_classification": class_name,
        "failure_source": failure_source,
        "execution_failure_code": (
            execution_evidence.get("worker_terminal_code") if worker_execution_failure else None
        ),
        "worker_execution_failure": _safe_projection(execution_evidence) if worker_execution_failure else {},
        "no_fake_verification_authority": worker_execution_failure,
        "verification_required_before_completion": True,
        "failed_verification_authorities": failed_authorities,
        "failed_verification": {} if worker_execution_failure else _safe_projection(failed),
        "failed_obligations": failed_obligations,
        "required_verification_obligations": _unique_strings(
            execution_evidence.get("verification_obligation_ids")
            if worker_execution_failure else value.get("required_authority_ids"),
            limit=48,
        ),
        "current_failed_subject_hash": value.get("current_subject_hash"),
        "current_failed_subject": {"subject_hash": value.get("current_subject_hash")},
        "authorized_mutation_scope": _safe_projection(auth.get("approved_mutation_scope") or {
            "paths": _unique_strings(
                (value.get("committed_mutation_manifest") or {}).get("committed_paths", []),
                paths=True,
            ),
        }),
        "scope": _safe_projection(auth.get("approved_mutation_scope") or {
            "paths": _unique_strings(
                (value.get("committed_mutation_manifest") or {}).get("committed_paths", []),
                paths=True,
            ),
        }),
        "dnt": _safe_projection(auth.get("approved_dnt") or {"paths": _approved_dnt_paths(auth)}),
        "do_not_touch": _unique_strings(
            (auth.get("approved_dnt") or {}).get("paths", [])
            if isinstance(auth.get("approved_dnt"), dict)
            else _approved_dnt_paths(auth),
            paths=True,
        ),
        "interfaces": _safe_projection(auth.get("approved_interface_binding") or {}),
        "preservation_constraints": _preservation_constraints(value, auth),
        "execution_invariant_set_hash": value.get("execution_invariant_set_hash"),
        "verification_digest": value.get("verification_digest"),
        "coverage_hash": value.get("coverage_hash"),
        "verification_authority_ids": _unique_strings(
            auth.get("verification_authority_ids")
            or (
                execution_evidence.get("verification_obligation_ids")
                if worker_execution_failure else failed_authorities
            ),
            limit=48,
        ),
        "recovery_objective": _text(objective, 1200),
        "recovery_attempt_index": int(attempt_index or 1),
        "recovery_budget": int(recovery_budget or MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS),
        "fresh_context": True,
        "historical_transcript_included": False,
        "historical_generation_count": 0,
        "new_plan_created": False,
        "new_approval_created": False,
        "new_requirement_ledger_created": False,
        "replanning_required": False,
        "worker_prose_authority": 0,
        "canonical_mission_hash": "",
    }
    mission["mission_id"] = "RECOVERY-MISSION-" + canonical_hash(
        _without(mission, "mission_id", "canonical_mission_hash"),
    )[:24].upper()
    mission["canonical_mission_hash"] = canonical_hash(_without(mission, "canonical_mission_hash"))
    return _freeze_record(RecoveryMission, mission)  # type: ignore[return-value]


create_recovery_mission = build_recovery_mission
fresh_recovery_mission = build_recovery_mission


def _packet_body(mission: dict[str, Any], authorization: dict[str, Any]) -> dict[str, Any]:
    failed = mission.get("failed_verification") if isinstance(mission.get("failed_verification"), dict) else {}
    execution_failure = mission.get("worker_execution_failure") if isinstance(mission.get("worker_execution_failure"), dict) else {}
    execution_failure_source = mission.get("failure_source") == WORKER_EXECUTION_FAILURE
    execution_failure_packet = {
        key: _safe_projection(execution_failure.get(key))
        for key in (
            "worker_terminal_code", "provider_health", "provider_handoff_valid",
            "execution_related", "verified_successful_completion", "v25_6_executed",
            "subject_known", "subject_unchanged", "lineage_status",
            "unknown_manual_drift", "scope_valid", "dnt_valid", "plan_unchanged",
            "approval_unchanged", "brain_valid", "brain_unchanged", "promoted",
            "authority_delta_empty", "legal_solution_space_available",
            "full_verification_universe_available", "recovery_budget_available",
            "provider_failure", "harness_failure", "v25_5_authority_valid",
            "verification_obligation_ids", "execution_failure_detail",
        )
        if key in execution_failure
    }
    approved_scope = mission.get("authorized_mutation_scope") if isinstance(mission.get("authorized_mutation_scope"), dict) else {}
    dnt = mission.get("dnt") if isinstance(mission.get("dnt"), dict) else {}
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": RECOVERY_WORKER_PACKET,
        "packet_id": "",
        "mission_id": mission.get("mission_id"),
        "recovery_execution_id": mission.get("recovery_execution_id"),
        "parent_execution_id": mission.get("parent_execution_id"),
        "plan_id": mission.get("parent_plan_id"),
        "plan_hash": mission.get("parent_plan_hash"),
        "approval_id": mission.get("approval_id"),
        "approval_receipt_hash": mission.get("approval_receipt_hash"),
        "recovery_authorization_id": authorization.get("authorization_id"),
        "recovery_authorization_hash": authorization.get("authorization_hash"),
        "current_failed_subject_hash": mission.get("current_failed_subject_hash"),
        "failure_source": mission.get("failure_source"),
        "execution_failure": execution_failure_packet if execution_failure_source else {},
        "failed_verification": {} if execution_failure_source else {
            "authority_id": failed.get("authority_id"),
            "oracle_id": failed.get("oracle_id"),
            "oracle_hash": failed.get("oracle_hash"),
            "failed_check": failed.get("failed_check"),
            "detail": failed.get("detail"),
        },
        "failed_authority_ids": mission.get("failed_verification_authorities", []),
        "failed_obligation_ids": mission.get("failed_obligations", []),
        "required_verification_obligations": mission.get("required_verification_obligations", []),
        "authorized_mutation_paths": _unique_strings(approved_scope.get("paths", []), paths=True),
        "do_not_touch_paths": _unique_strings(dnt.get("paths", []), paths=True),
        "preserve": mission.get("preservation_constraints", []),
        "interfaces": _safe_projection(mission.get("interfaces") or {}),
        "execution_invariant_set_hash": mission.get("execution_invariant_set_hash"),
        "verification_digest": mission.get("verification_digest"),
        "coverage_hash": mission.get("coverage_hash"),
        "attempt_index": mission.get("recovery_attempt_index"),
        "recovery_budget": mission.get("recovery_budget"),
        "worker_role": "same weak Builder capability in a fresh execution context",
        "implementation_choice": "choose a legal implementation; do not assume a prescribed patch",
        "no_new_authority": True,
        "worker_prose_authority": 0,
        "historical_transcript_included": False,
        "historical_generation_count": 0,
        "model_calls": 0,
        "real_worker_calls": 0,
    }


def build_recovery_worker_packet(
    mission: dict[str, Any],
    authorization: dict[str, Any] | None = None,
    *,
    max_chars: int = RECOVERY_WORKER_PACKET_MAX_CHARS,
) -> RecoveryWorkerPacket:
    """Build a fresh packet and enforce the 4200-character bound."""
    value = mission if isinstance(mission, dict) else {}
    auth = authorization if isinstance(authorization, dict) else {}
    limit = max(1, int(max_chars or RECOVERY_WORKER_PACKET_MAX_CHARS))
    packet = _packet_body(value, auth)
    packet["packet_id"] = "RECOVERY-PACKET-" + canonical_hash(
        _without(packet, "packet_id", "packet_hash", "canonical_packet_hash", "packet_chars"),
    )[:24].upper()
    packet["packet_hash"] = canonical_hash(_without(packet, "packet_hash", "canonical_packet_hash", "packet_chars"))
    packet["canonical_packet_hash"] = packet["packet_hash"]
    packet["packet_chars"] = _json_size(packet)
    packet["packet_size_chars"] = packet["packet_chars"]
    # The exact size fields can change their own digit count.  Converge before
    # trimming optional fields so the reported size is exact.
    for _ in range(4):
        size = _json_size(packet)
        packet["packet_chars"] = size
        packet["packet_size_chars"] = size
    optional_trim_order = (
        "interfaces", "preserve", "failed_obligation_ids", "coverage_hash",
        "verification_digest", "execution_invariant_set_hash",
    )
    if _json_size(packet) > limit:
        for key in optional_trim_order:
            if _json_size(packet) <= limit:
                break
            if key == "preserve":
                packet[key] = list(packet[key])[:3]
            elif key == "failed_obligation_ids":
                packet[key] = list(packet[key])[:4]
            else:
                packet[key] = _text(packet.get(key), 160)
        for _ in range(4):
            size = _json_size(packet)
            packet["packet_chars"] = size
            packet["packet_size_chars"] = size
    if _json_size(packet) > limit:
        # Mandatory fields are compact by construction.  Preserve them and
        # return an explicit bounded failure rather than silently dropping
        # authority evidence.
        packet["status"] = RECOVERY_MISSION_BLOCKED
        packet["packet_overflow"] = True
        packet["packet_overflow_chars"] = _json_size(packet)
    else:
        packet["status"] = "RECOVERY_WORKER_PACKET_READY"
        packet["packet_overflow"] = False
    packet["max_chars"] = limit
    for _ in range(4):
        size = _json_size(packet)
        packet["packet_chars"] = size
        packet["packet_size_chars"] = size
    # A caller can request an artificially tiny limit.  The canonical V26
    # limit is 4200 and is the contract used by normal recovery.
    packet["bounded"] = _json_size(packet) <= limit
    packet["context_clean"] = not contains_forbidden_recovery_transcript(packet)
    packet["canonical_packet_hash"] = canonical_hash(
        _without(packet, "packet_hash", "canonical_packet_hash", "packet_chars", "packet_size_chars"),
    )
    packet["packet_hash"] = packet["canonical_packet_hash"]
    for _ in range(3):
        size = _json_size(packet)
        packet["packet_chars"] = size
        packet["packet_size_chars"] = size
    return _freeze_record(RecoveryWorkerPacket, packet)  # type: ignore[return-value]


create_recovery_worker_packet = build_recovery_worker_packet
build_fresh_recovery_worker_packet = build_recovery_worker_packet


def validate_recovery_worker_packet(
    packet: dict[str, Any] | None,
    *,
    max_chars: int = RECOVERY_WORKER_PACKET_MAX_CHARS,
) -> dict[str, Any]:
    value = packet if isinstance(packet, dict) else {}
    size = _json_size(value)
    limit = max(1, int(max_chars or RECOVERY_WORKER_PACKET_MAX_CHARS))
    errors: list[str] = []
    expected_hash = canonical_hash(
        _without(value, "packet_hash", "canonical_packet_hash", "packet_chars", "packet_size_chars"),
    ) if value else None
    if value.get("artifact_type") != RECOVERY_WORKER_PACKET:
        errors.append("recovery Worker packet artifact type is invalid")
    if value.get("packet_hash") != expected_hash or value.get("canonical_packet_hash") != expected_hash:
        errors.append("recovery Worker packet hash is invalid")
    if size > limit or value.get("bounded") is not True:
        errors.append("recovery Worker packet exceeds its bound")
    if value.get("context_clean") is not True or contains_forbidden_recovery_transcript(value):
        errors.append("recovery Worker packet is not context-clean")
    if value.get("worker_prose_authority") != 0:
        errors.append("Worker prose has non-zero packet authority")
    for key in ("plan_hash", "approval_receipt_hash", "current_failed_subject_hash"):
        if not value.get(key):
            errors.append(f"recovery Worker packet is missing {key}")
    if value.get("failure_source") == WORKER_EXECUTION_FAILURE:
        if not value.get("execution_failure"):
            errors.append("execution-failure Worker packet is missing execution evidence")
        if value.get("failed_verification") not in ({}, None):
            errors.append("execution-failure Worker packet contains a verification receipt projection")
    elif not value.get("failed_verification"):
        errors.append("recovery Worker packet is missing failed verification evidence")
    return {
        "valid": not errors,
        "errors": list(dict.fromkeys(errors))[:40],
        "packet_chars": size,
        "max_chars": limit,
        "model_calls": 0,
        "worker_calls": 0,
    }


def create_recovery_attempt_accounting(
    *,
    max_attempts: int = MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS,
    initial_worker_attempt: int = 0,
) -> dict[str, Any]:
    maximum = max(0, int(max_attempts))
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "RecoveryAttemptAccounting",
        "initial_worker_attempt": int(initial_worker_attempt),
        "max_autonomous_worker_recovery_attempts": maximum,
        "recovery_attempts_started": 0,
        "recovery_attempts_completed": 0,
        "recovery_callback_calls": 0,
        "real_worker_calls": 0,
        "worker_calls": 0,
        "gemma_calls": 0,
        "model_calls": 0,
        "status": RECOVERY_ATTEMPT_READY if maximum else RECOVERY_BUDGET_EXHAUSTED,
        "history": [],
    }


def can_start_recovery_attempt(
    accounting: dict[str, Any] | None,
    *,
    attempt_index: int = 1,
) -> dict[str, Any]:
    value = accounting if isinstance(accounting, dict) else create_recovery_attempt_accounting()
    maximum = int(value.get("max_autonomous_worker_recovery_attempts", 0) or 0)
    started = int(value.get("recovery_attempts_started", 0) or 0)
    allowed = int(attempt_index or 0) == started + 1 and started < maximum and int(attempt_index or 0) <= maximum
    return {
        "allowed": allowed,
        "status": RECOVERY_ATTEMPT_READY if allowed else RECOVERY_BUDGET_EXHAUSTED,
        "attempt_index": int(attempt_index or 0),
        "attempts_started": started,
        "max_attempts": maximum,
        "model_calls": 0,
        "worker_calls": 0,
    }


def consume_recovery_attempt(
    accounting: dict[str, Any] | None,
    *,
    attempt_index: int = 1,
    outcome: str | None = None,
) -> dict[str, Any]:
    value = _copy(accounting) if isinstance(accounting, dict) else create_recovery_attempt_accounting()
    decision = can_start_recovery_attempt(value, attempt_index=attempt_index)
    if not decision["allowed"]:
        value["status"] = RECOVERY_BUDGET_EXHAUSTED
        value["budget_exhausted"] = True
        return value
    value["recovery_attempts_started"] = int(value.get("recovery_attempts_started", 0) or 0) + 1
    value["recovery_attempts_completed"] = int(value.get("recovery_attempts_completed", 0) or 0) + 1
    value["status"] = "RECOVERY_ATTEMPT_COMPLETED"
    value["budget_exhausted"] = value["recovery_attempts_started"] >= int(
        value.get("max_autonomous_worker_recovery_attempts", 0) or 0,
    )
    history = value.get("history") if isinstance(value.get("history"), list) else []
    history.append({
        "attempt_index": int(attempt_index),
        "outcome": _text(outcome, 160),
        "clean": True,
        "legal_solution_space_available": True,
        "context_valid": True,
        "authority_sufficient": True,
    })
    value["history"] = history[-8:]
    return value


record_recovery_attempt = consume_recovery_attempt


def _callback_call(
    callback: Callable[..., Any],
    available: dict[str, Any],
) -> Any:
    """Call a seam once while supporting positional test callbacks."""
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        # Signature introspection can fail for opaque callables.  This is one
        # call only; an exception from the callback is never retried.
        return callback(**available)
    parameters = signature.parameters
    if any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
        return callback(**available)
    if all(name in parameters for name in available):
        return callback(**available)
    positional = [
        available["mission"],
        available["authorization"],
        available["current_subject"],
        available["execution_invariant_set"],
        available["dnt"],
        available["verification_authority"],
    ]
    return callback(*positional)


def dispatch_recovery_worker(
    mission: dict[str, Any] | None,
    authorization: dict[str, Any] | None,
    current_subject: Any,
    execution_invariant_set: Any,
    dnt: Any,
    verification_authority: Any,
    callback: Callable[..., Any] | None = None,
    *,
    worker_callback: Callable[..., Any] | None = None,
    accounting: dict[str, Any] | None = None,
    attempt_accounting: dict[str, Any] | None = None,
    attempt_index: int = 1,
) -> dict[str, Any]:
    """Reach an injected recovery seam exactly once; never a real Worker."""
    mission_value = mission if isinstance(mission, dict) else {}
    auth_value = authorization if isinstance(authorization, dict) else {}
    callback = callback or worker_callback
    counters = accounting if isinstance(accounting, dict) else (
        attempt_accounting if isinstance(attempt_accounting, dict) else create_recovery_attempt_accounting()
    )
    decision = can_start_recovery_attempt(counters, attempt_index=attempt_index)
    base = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "RecoveryDispatchResult",
        "status": RECOVERY_DISPATCH_BLOCKED,
        "attempt_index": int(attempt_index),
        "recovery_dispatch_count": 0,
        "recovery_callback_calls": 0,
        "injected_recovery_worker_seam": "NOT_REACHED",
        "real_worker_calls": 0,
        "worker_calls": 0,
        "gemma_calls": 0,
        "model_calls": 0,
        "attempt_accounting": counters,
    }
    if mission_value.get("status") != RECOVERY_MISSION_READY or auth_value.get("status") != RECOVERY_AUTHORIZATION_READY:
        base["reason"] = "recovery mission or authorization is not ready"
        return base
    if not decision.get("allowed"):
        base["status"] = RECOVERY_BUDGET_EXHAUSTED
        base["reason"] = "the single autonomous recovery attempt is already consumed"
        counters["status"] = RECOVERY_BUDGET_EXHAUSTED
        return base
    if not callable(callback):
        base["status"] = RECOVERY_DISPATCH_CALLBACK_REQUIRED
        base["reason"] = "V26 requires an injected architecture callback"
        return base
    available = {
        "mission": mission_value,
        "authorization": auth_value,
        "current_subject": current_subject,
        "execution_invariant_set": execution_invariant_set,
        "dnt": dnt,
        "verification_authority": verification_authority,
    }
    # Reserve the budget before calling so a callback cannot cause a second
    # callback through re-entry or an exception path.
    counters["recovery_attempts_started"] = int(counters.get("recovery_attempts_started", 0) or 0) + 1
    counters["recovery_callback_calls"] = int(counters.get("recovery_callback_calls", 0) or 0) + 1
    counters["status"] = "RECOVERY_ATTEMPT_RUNNING"
    callback_result: Any = None
    try:
        callback_result = _callback_call(callback, available)
        status = RECOVERY_DISPATCHED
    except Exception as exc:  # one seam call, fail closed
        status = RECOVERY_CALLBACK_FAILED
        callback_result = {"callback_error": _text(exc, 360)}
    counters["recovery_attempts_completed"] = int(counters.get("recovery_attempts_completed", 0) or 0) + 1
    counters["status"] = "RECOVERY_ATTEMPT_COMPLETED"
    counters["budget_exhausted"] = counters["recovery_attempts_started"] >= int(
        counters.get("max_autonomous_worker_recovery_attempts", MAX_AUTONOMOUS_WORKER_RECOVERY_ATTEMPTS) or 0,
    )
    result = dict(base)
    result.update({
        "status": status,
        "recovery_dispatch_count": 1,
        "recovery_callback_calls": 1,
        "injected_recovery_worker_seam": "REACHED_ONCE",
        "callback_result": _safe_projection(callback_result),
        "attempt_accounting": counters,
    })
    return result


dispatch_injected_recovery_worker = dispatch_recovery_worker
dispatch_recovery_worker_seam = dispatch_recovery_worker


def _live3_obligation_evidence(data: dict[str, Any]) -> list[dict[str, Any]]:
    audits = data.get("precommit_invariant_audits")
    audits = audits if isinstance(audits, list) else []
    accepted = next(
        (item for item in reversed(audits) if isinstance(item, dict) and item.get("allowed") is True),
        {},
    )
    audit_hash = _text(accepted.get("canonical_hash"), 128) or canonical_hash({"v25_5": LIVE3_INVARIANT_HASH})
    return [{
        "authority_id": "INVARIANT-STATE-OWNER",
        "oracle_id": "INVARIANT-STATE-OWNER",
        "result": {"passed": True, "verification_status": verification_routing.PASS},
        "receipt_identity": "PRECOMMIT-AUDIT-" + audit_hash.upper(),
        "receipt_hash": audit_hash,
        "receipt_channel": "PRECOMMIT_EXECUTION_INVARIANT_GATE",
        "execution_channel": "PRECOMMIT_EXECUTION_INVARIANT_GATE",
        "receipt_valid": True,
        "source": "V25.5_PreCommitExecutionInvariantGate",
        "authority_set_hash": LIVE3_INVARIANT_HASH,
        "evidence_hash": audit_hash,
    }]


def _recovery_verification_evidence(
    data: dict[str, Any],
    *,
    passed: bool,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    applicability = data.get("verification_applicability")
    if not isinstance(applicability, dict):
        applicability = {}
    applicability = _copy(applicability)
    applicability.update({
        "plan_id": applicability.get("plan_id") or LIVE3_PLAN_ID,
        "plan_hash": applicability.get("plan_hash") or LIVE3_PLAN_HASH,
        "verification_digest": applicability.get("verification_digest") or LIVE3_VERIFICATION_DIGEST,
        "verification_obligation_coverage_hash": (
            applicability.get("verification_obligation_coverage_hash") or LIVE3_COVERAGE_HASH
        ),
    })
    evidence = _copy(data.get("verification_evidence") or [])
    if not isinstance(evidence, list):
        evidence = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        if (
            result.get("oracle_id") == "ORACLE-PAUSE-INDICATOR"
            or item.get("oracle_id") == "ORACLE-PAUSE-INDICATOR"
            or item.get("verification_id") == "VERIFICATION-004"
        ):
            result["passed"] = bool(passed)
            result["verification_status"] = verification_routing.PASS if passed else verification_routing.FAIL
            if passed:
                result["checks"] = [
                    {"name": "export_callable", "passed": True, "detail": "renderPauseIndicator"},
                ]
    return applicability, evidence


def _copy_live3_subject_to_workspace(root: Path, artifact_root: Path) -> None:
    source_root = Path(artifact_root)
    subject_paths = (
        "src/input.js", "src/pause_controller.js", "src/status_view.js",
        "tests/input.test.js", "tests/pause_flow.integration.test.js",
        "tests/status_view.test.js",
    )
    for relative in subject_paths:
        source = source_root / relative
        target = root / relative
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _default_injected_callback(
    *,
    success: bool,
    data: dict[str, Any],
    workspace: Path,
) -> Callable[..., dict[str, Any]]:
    def callback(
        mission: dict[str, Any],
        authorization: dict[str, Any],
        current_subject: Any,
        execution_invariant_set: Any,
        dnt: Any,
        verification_authority: Any,
    ) -> dict[str, Any]:
        subject_hash = _text(
            current_subject.get("subject_hash")
            if isinstance(current_subject, dict)
            else current_subject,
            128,
        ) or LIVE3_FAILED_SUBJECT_HASH
        if success:
            # This marker is only in a TemporaryDirectory owned by the
            # provider-free replay.  It is not a production implementation
            # and does not prescribe the Worker code fix.
            target = workspace / "src" / "status_view.js"
            if target.is_file():
                target.write_text(
                    target.read_text(encoding="utf-8") + "\n// injected legal recovery subject\n",
                    encoding="utf-8",
                )
            resulting_hash = canonical_hash({
                "parent_failed_subject_hash": subject_hash,
                "recovery_execution_id": mission.get("recovery_execution_id"),
                "changed_paths": ["src/status_view.js"],
                "temporary_subject": True,
            })
        else:
            resulting_hash = subject_hash
        applicability, evidence = _recovery_verification_evidence(data, passed=success)
        return {
            "status": "passed" if success else "failed",
            "terminal_state": "RECOVERY_VERIFICATION_READY" if success else "VERIFICATION_FAILED",
            "subject": {
                "subject_hash": resulting_hash,
                "workspace": str(workspace),
                "changed_paths": ["src/status_view.js"] if success else [],
                "created_paths": [],
                "deleted_paths": [],
            },
            "verification_applicability": applicability,
            "verification_evidence": evidence,
            "execution_obligation_evidence": _live3_obligation_evidence(data),
            "verification_obligation_coverage": _copy(data.get("verification_coverage") or {}),
            "precommit_status": "PASS" if success else "NOT_REACHED",
            "injected_architecture_only": True,
            "worker_prose_excluded": True,
            "model_calls": 0,
            "real_worker_calls": 0,
            "worker_calls": 0,
        }
    return callback


def _build_recovery_stage5b(
    *,
    callback_result: dict[str, Any],
    mission: dict[str, Any],
    data: dict[str, Any],
    workspace: Path,
) -> dict[str, Any]:
    from hivo import integration_gate as stage5b

    verification = callback_result.get("verification") if isinstance(callback_result.get("verification"), dict) else {}
    aggregation = verification.get("aggregation") if isinstance(verification.get("aggregation"), dict) else {}
    applicability = callback_result.get("verification_applicability") if isinstance(callback_result.get("verification_applicability"), dict) else {}
    evidence = callback_result.get("verification_evidence") if isinstance(callback_result.get("verification_evidence"), list) else []
    base_contract = _compact_recovery_parent_contract(data, mission)
    parent_contract = _copy(base_contract)
    parent_contract["execution_contract_id"] = "RECOVERY-PARENT"
    parent_contract["contract_hash"] = canonical_hash({
        "base_contract_hash": base_contract.get("contract_hash"),
        "recovery_parent": True,
        "mission_id": mission.get("mission_id"),
    })
    parent_contract["plan_hash"] = mission.get("parent_plan_hash")
    child_id = mission.get("recovery_execution_id")
    child_contract = _copy(base_contract)
    child_contract["execution_contract_id"] = child_id
    child_contract["contract_hash"] = canonical_hash({
        "base_contract_hash": base_contract.get("contract_hash"),
        "recovery_child": child_id,
    })
    child_contract["plan_hash"] = mission.get("parent_plan_hash")
    child_contract["allowed_mutation_paths"] = ["src/status_view.js"]
    parent_contract["validated_child_plan"] = [{
        "child_id": child_id,
        "required": True,
        "execution_contract_id": child_id,
        "contract_hash": child_contract["contract_hash"],
        "plan_hash": mission.get("parent_plan_hash"),
        "plan_node_ids": list(child_contract.get("plan_node_ids", []) or []) or ["RECOVERY-NODE"],
        "owned_plan_node_ids": list(child_contract.get("owned_plan_node_ids", []) or []) or ["RECOVERY-NODE"],
    }]
    parent_contract["integration_routes"] = [{
        "kind": "INTEGRATION_TEST",
        "required": True,
        "applicable": True,
        "target": "tests/pause_flow.integration.test.js",
        "result": stage5b.PENDING,
    }]
    parent = {
        "id": "RECOVERY-PARENT",
        "goal": mission.get("recovery_objective"),
        "integration_routes": _copy(parent_contract["integration_routes"]),
    }
    task = {
        "id": child_id,
        "parent": "RECOVERY-PARENT",
        "status": "done",
        "execution_contract_id": child_id,
        "execution_contract_hash": child_contract["contract_hash"],
        "approved_plan_hash": mission.get("parent_plan_hash"),
        "execution_contract": child_contract,
        "plan_node_ids": list(child_contract.get("plan_node_ids", []) or []) or ["RECOVERY-NODE"],
        "owned_plan_node_ids": list(child_contract.get("owned_plan_node_ids", []) or []) or ["RECOVERY-NODE"],
        "done_when": ["recovery verification passed"],
    }
    child_result = {
        "status": "done",
        "gate": {"verification_aggregation": aggregation},
        "verification_applicability": applicability,
        "verification_aggregation": aggregation,
        "verification_evidence": evidence,
        "builder": {"status": "done", "tool_evidence": evidence},
    }
    receipt = stage5b.create_verified_child_receipt(
        task,
        child_result,
        parent_id="RECOVERY-PARENT",
        parent_contract=parent_contract,
        verification_applicability=applicability,
        verification_aggregation=aggregation,
        verification_evidence=evidence,
        workspace=workspace,
        mutation_paths=["src/status_view.js"] if callback_result.get("subject", {}).get("changed_paths") else [],
    )
    pairs = [(task, child_result)]
    readiness = stage5b.assess_integration_readiness(
        parent,
        pairs,
        {child_id: receipt},
        parent_contract=parent_contract,
        validated_child_plan=parent_contract["validated_child_plan"],
        workspace=workspace,
        parent_verification_applicability=applicability,
    )
    integration_evidence = [{
        "tool": "run_command",
        "target": "node tests/pause_flow.integration.test.js",
        "result": "[exit_code=0] injected deterministic integration evidence",
    }]
    integrated = stage5b.aggregate_parent_integration(
        parent,
        parent_contract,
        readiness,
        integration_evidence,
        workspace=workspace,
    )
    return {
        "parent": parent,
        "parent_contract": parent_contract,
        "child_contract": child_contract,
        "task": task,
        "child_result": child_result,
        "child_receipt": receipt,
        "child_receipts": {child_id: receipt},
        "readiness": readiness,
        "integration": integrated,
        "status": integrated.get("status"),
        "integration_result": integrated.get("integration_result") or integrated.get("status"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def _run_stage5a_recovery(
    callback_result: dict[str, Any],
    mission: dict[str, Any],
    data: dict[str, Any],
) -> dict[str, Any]:
    applicability = callback_result.get("verification_applicability")
    evidence = callback_result.get("verification_evidence")
    if not isinstance(applicability, dict):
        applicability = {}
    if not isinstance(evidence, list):
        evidence = []
    passed = callback_result.get("status") == "passed"
    aggregation = verification_routing.aggregate_verification_evidence(
        applicability,
        evidence,
        execution_obligation_evidence=callback_result.get("execution_obligation_evidence"),
        verification_obligation_coverage=callback_result.get("verification_obligation_coverage"),
    )
    return {
        "status": verification_routing.PASS if aggregation.get("passed") else verification_routing.FAIL,
        "passed": aggregation.get("passed") is True,
        "expected_callback_outcome": passed,
        "verification_applicability": applicability,
        "verification_evidence": evidence,
        "aggregation": aggregation,
        "execution_verification_closure": aggregation.get("execution_verification_closure"),
        "execution_time_coverage": aggregation.get("execution_time_coverage"),
        "model_calls": 0,
        "worker_calls": 0,
    }


def _compact_recovery_parent_contract(data: dict[str, Any], mission: dict[str, Any]) -> dict[str, Any]:
    """Project only the contract fields needed by the V21/V22 seams.

    The live contract is intentionally large.  Recovery integration should
    prove the downstream boundaries, not smuggle the entire planning ledger
    into a temporary Task Brain.
    """
    source = _projection_from_run_state(
        data,
        "stage5b_parent_contract",
        "stage5c_parent_contract",
        "approval_bound_parent_contract",
    )
    return {
        "contract_hash": source.get("contract_hash") or LIVE3_PLAN_HASH,
        "plan_hash": mission.get("parent_plan_hash"),
        "plan_id": mission.get("parent_plan_id"),
        "execution_contract_id": source.get("execution_contract_id") or "EXEC-001",
        "project_id": "hivo-v22-stage5c-fresh-receipts-live-1",
        "allowed_mutation_paths": ["src/status_view.js"],
        "allowed_inspection_paths": [
            "src/status_view.js",
            "src/pause_controller.js",
            "src/input.js",
            "tests/input.test.js",
            "tests/pause_flow.integration.test.js",
            "tests/status_view.test.js",
        ],
        "global_do_not_touch": ["src/pause_controller.js"],
        "interfaces_to_reuse": ["PauseController.togglePause"],
        "state_ownership": ["PauseController owns pause state"],
        "preservation_constraints": [
            "renderStatus remains a primitive string",
            "preserve Escape and movement behavior",
        ],
        "structured_prohibitions": [
            "Do not modify src/pause_controller.js",
            "PauseController remains the sole pause-state owner",
        ],
        "requirements": [{
            "requirement_id": "REQ-PAUSE-INDICATOR",
            "text": "Extend the approved pause flow without changing preserved behavior",
            "provenance": "USER_STATED",
        }],
        "done_when": ["recovery verification and integration pass"],
        "plan_node_ids": list(source.get("plan_node_ids", []) or []) or ["NODE-002"],
        "owned_plan_node_ids": list(source.get("owned_plan_node_ids", []) or []) or ["NODE-002"],
        "execution_invariant_set_hash": mission.get("execution_invariant_set_hash") or LIVE3_INVARIANT_HASH,
        "execution_invariant_ids": list(source.get("execution_invariant_ids", []) or []),
        "verification_obligation_coverage_hash": mission.get("coverage_hash") or LIVE3_COVERAGE_HASH,
        "approved_verification_digest": mission.get("verification_digest") or LIVE3_VERIFICATION_DIGEST,
        "integration_responsibility": ["preserve the approved pause behavior"],
        "test_contract": ["tests/pause_flow.integration.test.js"],
        "responsibility_type": "MUTATION",
        "worker_required": True,
    }


def _compact_recovery_reentry_view(store: Any, project_id: str) -> Any:
    """Expose a bounded read-only Brain projection to the re-entry seam."""
    try:
        snapshot = store.project_brain_snapshot(project_id, include_inactive=True)
    except Exception:
        snapshot = {"project_id": project_id, "records": []}
    records = snapshot.get("records", []) if isinstance(snapshot, dict) else []
    selected: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        fact = record.get("fact") if isinstance(record.get("fact"), dict) else {}
        text = json.dumps(fact, ensure_ascii=False, default=str).casefold()
        if any(token in text for token in ("pause", "renderstatus", "state_owner", "do_not_touch", "movement")):
            selected.append(_copy(record))
    selected = selected[:3]

    class ReadOnlyRecoveryBrainView:
        workspace = getattr(store, "workspace", None)

        def project_brain_snapshot(self, requested: str, *, include_inactive: bool = True) -> dict[str, Any]:
            return {
                "project_id": requested,
                "records": _copy(selected) if requested == project_id else [],
            }

        def get_task_brain_completion(self, requested: str, task_id: str) -> Any:
            reader = getattr(store, "get_task_brain_completion", None)
            return reader(requested, task_id) if callable(reader) else None

    return ReadOnlyRecoveryBrainView()


def run_provider_free_recovery_replay(
    artifact_root: str | os.PathLike[str] | Path | None = None,
    *,
    worker_callback: Callable[..., Any] | None = None,
    callback: Callable[..., Any] | None = None,
    outcome: str = "failure",
    succeed: bool | None = None,
    attempt_accounting: dict[str, Any] | None = None,
    failure_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the bounded V26 architecture replay without a provider or Worker."""
    positive = bool(succeed) if succeed is not None else str(outcome).casefold() in {
        "success", "succeed", "pass", "positive", "recovered",
    }
    data = load_live3_recovery_evidence(artifact_root)
    envelope = build_recovery_failure_envelope(
        data,
        failure_evidence=failure_evidence,
    )
    envelope_check = validate_recovery_failure_envelope(envelope)
    authorization_source = data.get("execution_authorization") if isinstance(data.get("execution_authorization"), dict) else {}
    classification = classify_recovery_failure(envelope, approved_authority=authorization_source)
    delta = classification.get("authority_delta")
    lineage = build_authorized_execution_lineage(envelope, authorization=authorization_source)
    lineage_check = validate_authorized_execution_lineage(lineage, envelope=envelope)
    eligibility = decide_recovery_eligibility(
        envelope,
        classification,
        authority_delta=delta,
        lineage=lineage,
        current_subject_hash=envelope.get("current_subject_hash"),
        authorization=authorization_source,
    )
    recovery_authorization = build_approved_recovery_authorization(
        envelope,
        classification=classification,
        authority_delta=delta,
        lineage=lineage,
        eligibility=eligibility,
        approved_authority=authorization_source,
    )
    mission = build_recovery_mission(
        envelope,
        recovery_authorization,
        classification=classification,
        attempt_index=1,
    )
    packet = build_recovery_worker_packet(mission, recovery_authorization)
    accounting = attempt_accounting if isinstance(attempt_accounting, dict) else create_recovery_attempt_accounting()
    artifact_base = Path(data.get("artifact_root") or artifact_root or Path(__file__).resolve().parents[1]).resolve()
    with TemporaryDirectory(prefix="hivo_v26_recovery_replay_") as temporary:
        workspace = Path(temporary) / "subject"
        workspace.mkdir(parents=True, exist_ok=True)
        _copy_live3_subject_to_workspace(workspace, artifact_base)
        brain_source = artifact_base / "working_brain" / ".hivo" / "memory.sqlite3"
        if not brain_source.is_file():
            brain_source = Path(__file__).resolve().parents[1] / "output" / "hivo-v22-stage5c-fresh-receipts-live-1" / ".hivo" / "memory.sqlite3"
        brain_target = workspace / ".hivo" / "memory.sqlite3"
        if brain_source.is_file():
            brain_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(brain_source, brain_target)
        current_subject = {
            "subject_hash": envelope.get("current_subject_hash"),
            "workspace": str(workspace),
            "changed_paths": (envelope.get("committed_mutation_manifest") or {}).get("committed_paths", []),
        }
        callback_to_use = callback or worker_callback
        if not callable(callback_to_use):
            callback_to_use = _default_injected_callback(success=positive, data=data, workspace=workspace)
        invariant_set = (
            (_projection_from_run_state(data, "stage5b_parent_contract").get("execution_invariant_projection"))
            or {"execution_invariant_set_hash": envelope.get("execution_invariant_set_hash")}
        )
        dnt = (
            authorization_source.get("approved_dnt")
            if isinstance(authorization_source.get("approved_dnt"), dict)
            else {"paths": _approved_dnt_paths(authorization_source)}
        )
        verification_authority = {
            "authority_ids": _unique_strings(
                authorization_source.get("approved_verification_contracts")
                or envelope.get("failed_verification_authority_ids"),
                limit=48,
            ),
            "verification_digest": envelope.get("verification_digest"),
            "coverage_hash": envelope.get("coverage_hash"),
        }
        dispatch = dispatch_recovery_worker(
            mission,
            recovery_authorization,
            current_subject,
            invariant_set,
            dnt,
            verification_authority,
            callback_to_use,
            accounting=accounting,
            attempt_index=1,
        )
        callback_result = dispatch.get("callback_result")
        callback_result = callback_result if isinstance(callback_result, dict) else {}
        if dispatch.get("status") == RECOVERY_DISPATCHED:
            callback_result = _copy(callback_result)
            callback_result.setdefault("subject", current_subject)
        stage5a = _run_stage5a_recovery(callback_result, mission, data) if dispatch.get("status") == RECOVERY_DISPATCHED else {
            "status": verification_routing.FAIL,
            "passed": False,
            "aggregation": {},
            "model_calls": 0,
            "worker_calls": 0,
        }
        if dispatch.get("status") == RECOVERY_DISPATCHED:
            # The dispatch result is intentionally a public, scrubbed
            # projection.  Attach the deterministic V25.6 aggregation here
            # for the Stage 5B receipt builder; no Worker prose is added.
            callback_result["verification"] = {
                "aggregation": _copy(stage5a.get("aggregation") or {}),
            }
        stage5b = None
        stage5c = None
        reentry_result = None
        brain_before = LIVE3_BRAIN_HASH
        brain_after = brain_before
        if stage5a.get("passed") is True and dispatch.get("status") == RECOVERY_DISPATCHED:
            stage5b = _build_recovery_stage5b(
                callback_result=callback_result,
                mission=mission,
                data=data,
                workspace=workspace,
            )
            if stage5b.get("status") == integration_gate.PARENT_VERIFIED:
                from hivo.memory import MemoryStore

                store = MemoryStore(workspace)
                project_id = "hivo-v22-stage5c-fresh-receipts-live-1"
                brain_before = store.project_brain_hash(project_id)
                integrated = stage5b.get("integration") or {}
                stage5c = promotion.promote_verified_parent(
                    stage5b["parent"],
                    integrated.get("parent_verification_receipt"),
                    stage5b["parent_contract"],
                    child_receipts=stage5b.get("child_receipts"),
                    workspace=workspace,
                    project_id=project_id,
                    store=store,
                    task_id=mission.get("recovery_execution_id"),
                    artifact_refs=["v26:injected-recovery-replay"],
                )
                brain_after = store.project_brain_hash(project_id)
                if stage5c.get("promotion_status") == promotion.PROMOTED:
                    reentry_result = reentry.run_verified_state_reentry(
                        _compact_recovery_reentry_view(store, project_id),
                        project_id,
                        "V26-RECOVERY-REENTRY",
                        "Continue the approved pause-indicator task.",
                        workspace=workspace,
                        relevant_paths=["src/status_view.js", "src/pause_controller.js"],
                        previous_task_id=mission.get("recovery_execution_id"),
                        previous_task_completion=stage5c.get("task_brain_completion"),
                        promotion_provenance={
                            "source": "V26_INJECTED_RECOVERY_REPLAY",
                            "promotion_status": stage5c.get("promotion_status"),
                        },
                    )
        if dispatch.get("status") == RECOVERY_DISPATCHED and not positive:
            # Attempt 2 is explicitly evaluated and blocked by the one-attempt
            # budget.  It does not call the callback.
            second_dispatch = dispatch_recovery_worker(
                mission,
                recovery_authorization,
                current_subject,
                invariant_set,
                dnt,
                verification_authority,
                callback_to_use,
                accounting=accounting,
                attempt_index=2,
            )
        else:
            second_dispatch = {
                "status": "NOT_ATTEMPTED",
                "recovery_dispatch_count": 0,
                "recovery_callback_calls": 0,
                "injected_recovery_worker_seam": "NOT_REACHED",
            }
        # The public result contains no temporary path or raw callback chat.
        result = {
            "schema_version": SCHEMA_VERSION,
            "artifact_type": "ProviderFreeRecoveryReplay",
            "status": (
                "RECOVERY_REPLAY_PROMOTED"
                if reentry_result and reentry_result.get("status") == reentry.REENTRY_READY
                else "RECOVERY_REPLAY_VERIFICATION_FAILED"
                if stage5a.get("passed") is not True
                else "RECOVERY_REPLAY_INTEGRATION_FAILED"
                if not stage5b or stage5b.get("status") != integration_gate.PARENT_VERIFIED
                else "RECOVERY_REPLAY_PROMOTION_FAILED"
                if not stage5c or stage5c.get("promotion_status") != promotion.PROMOTED
                else "RECOVERY_REPLAY_REENTRY_FAILED"
            ),
            "positive_injected_outcome": positive,
            "failure_envelope": envelope,
            "failure_envelope_validation": envelope_check,
            "classification": classification,
            "authority_delta": delta,
            "lineage": lineage,
            "lineage_validation": lineage_check,
            "eligibility": eligibility,
            "recovery_authorization": recovery_authorization,
            "recovery_authorization_validation": validate_approved_recovery_authorization(
                recovery_authorization,
                envelope=envelope,
            ),
            "recovery_mission": mission,
            "recovery_worker_packet": packet,
            "recovery_worker_packet_validation": validate_recovery_worker_packet(packet),
            "dispatch": dispatch,
            "stage5a": stage5a,
            "stage5b": stage5b,
            "stage5c": stage5c,
            "reentry": reentry_result,
            "second_dispatch": second_dispatch,
            "brain_before_hash": brain_before,
            "brain_after_hash": brain_after,
            "brain_unchanged": brain_before == brain_after,
            "historical_brain_unchanged": True,
            "historical_live3_read_only": True,
            "new_approval_created": False,
            "new_plan_created": False,
            "new_requirement_ledger_created": False,
            "gemma_calls": 0,
            "model_calls": 0,
            "real_worker_calls": 0,
            "worker_calls": 0,
            "recovery_callback_calls": dispatch.get("recovery_callback_calls", 0),
            "recovery_dispatch_count": dispatch.get("recovery_dispatch_count", 0),
            "attempt_accounting": accounting,
            "provider_free": True,
            "injected_architecture_only": True,
        }
        return result


run_injected_recovery_replay = run_provider_free_recovery_replay
run_recovery_replay = run_provider_free_recovery_replay


def run_recovery_architecture_self_test(
    artifact_root: str | os.PathLike[str] | Path | None = None,
) -> dict[str, Any]:
    """Exercise V26 positive and negative recovery paths provider-free."""
    checks: dict[str, bool] = {}
    diagnostics: dict[str, Any] = {}
    try:
        positive = run_provider_free_recovery_replay(artifact_root, outcome="success")
        negative = run_provider_free_recovery_replay(artifact_root, outcome="failure")
        envelope = positive["failure_envelope"]
        delta = positive["authority_delta"]
        mission = positive["recovery_mission"]
        packet = positive["recovery_worker_packet"]
        checks.update({
            "live3_envelope_valid": positive["failure_envelope_validation"].get("valid") is True,
            "live3_classification_worker_recoverable": positive["classification"].get("classification") == WORKER_RECOVERABLE,
            "live3_authority_delta_empty": delta.get("empty") is True,
            "live3_no_reapproval": positive["eligibility"].get("USER_REAPPROVAL_REQUIRED") is False,
            "lineage_valid": positive["lineage_validation"].get("valid") is True,
            "mission_ready": mission.get("status") == RECOVERY_MISSION_READY,
            "packet_bounded": positive["recovery_worker_packet_validation"].get("valid") is True,
            "positive_stage5a": positive["stage5a"].get("passed") is True,
            "positive_stage5b": (positive.get("stage5b") or {}).get("status") == integration_gate.PARENT_VERIFIED,
            "positive_stage5c": (positive.get("stage5c") or {}).get("promotion_status") == promotion.PROMOTED,
            "positive_reentry": (positive.get("reentry") or {}).get("status") == reentry.REENTRY_READY,
            "negative_stage5a_fails": negative["stage5a"].get("passed") is not True,
            "negative_brain_unchanged": negative.get("brain_unchanged") is True,
            "negative_budget_exhausted": (
                negative.get("second_dispatch", {}).get("status") == RECOVERY_BUDGET_EXHAUSTED
            ),
            "negative_no_third_seam": negative.get("recovery_callback_calls") == 1,
            "zero_provider_calls": all(
                int(positive.get(key, 0) or 0) == 0
                for key in ("gemma_calls", "model_calls", "real_worker_calls", "worker_calls")
            ) and all(
                int(negative.get(key, 0) or 0) == 0
                for key in ("gemma_calls", "model_calls", "real_worker_calls", "worker_calls")
            ),
            "historical_live3_read_only": positive.get("historical_live3_read_only") is True,
            "worker_prose_zero": envelope.get("worker_prose_authority") == 0 and packet.get("worker_prose_authority") == 0,
        })
        diagnostics.update({
            "positive_status": positive.get("status"),
            "negative_status": negative.get("status"),
            "positive_stage5a_status": positive.get("stage5a", {}).get("status"),
            "positive_stage5b_status": (positive.get("stage5b") or {}).get("status"),
            "positive_stage5c_status": (positive.get("stage5c") or {}).get("promotion_status"),
            "positive_reentry_status": (positive.get("reentry") or {}).get("status"),
            "negative_second_dispatch": negative.get("second_dispatch"),
            "packet_chars": packet.get("packet_chars"),
            "packet_max_chars": packet.get("max_chars"),
        })
    except Exception as exc:
        checks["exception_free"] = False
        diagnostics["exception"] = _text(exc, 600)
    else:
        checks["exception_free"] = True
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "diagnostics": diagnostics,
        "gemma_calls": 0,
        "model_calls": 0,
        "real_worker_calls": 0,
        "worker_calls": 0,
    }


run_stage6c_b_recovery_self_test = run_recovery_architecture_self_test
run_v26_recovery_self_test = run_recovery_architecture_self_test
recovery_architecture_self_test = run_recovery_architecture_self_test


__all__ = [name for name in globals() if not name.startswith("_")]
