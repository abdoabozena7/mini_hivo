"""Deterministic V25.4 remediation for an uncovered behavior obligation.

The objects in this module are planning and verification authority, not
execution authority.  A caller must provide the proposed observable and the
direct oracle explicitly; this module never invents an API, a test, or a
provider action.  The direct oracle executes a verifier-generated temporary
probe outside the subject workspace and therefore cannot be edited by a
Worker.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable

from hivo import execution_contracts as stage4
from hivo import execution_invariants as invariant
from hivo import impact_planning as planning
from hivo import verification_obligation_coverage as coverage
from hivo.requirements import freeze


SCHEMA_VERSION = "25.4-VERIFICATION-GAP-REMEDIATION-1"
CONTRACT_SCHEMA_VERSION = "25.4-BEHAVIOR-OBSERVABLE-CONTRACT-1"
ORACLE_SCHEMA_VERSION = "25.4-DIRECT-BEHAVIOR-ORACLE-1"
APPROVAL_SUMMARY_SCHEMA_VERSION = "25.4-REVISED-PLAN-APPROVAL-SUMMARY-1"

VERIFICATION_GAP_REMEDIATION_VALID = "VERIFICATION_GAP_REMEDIATION_VALID"
VERIFICATION_GAP_REMEDIATION_INVALID = "VERIFICATION_GAP_REMEDIATION_INVALID"
VERIFICATION_OBLIGATION_UNCOVERED = coverage.VERIFICATION_OBLIGATION_UNCOVERED
EXECUTION_VERIFICATION_READY = coverage.EXECUTION_VERIFICATION_READY
PLAN_APPROVAL_REQUIRED = "PLAN_APPROVAL_REQUIRED"
STAGE4_CONTRACTABILITY_PASS = "STAGE4_CONTRACTABILITY_PASS"
OLD_APPROVAL_NOT_APPLICABLE_TO_REVISED_PLAN = "OLD_APPROVAL_NOT_APPLICABLE_TO_REVISED_PLAN"
HIVO_VERIFIER = "HIVO_VERIFIER"
ADDITIVE_EXPORT = "ADDITIVE_EXPORT"
DIRECT = coverage.DIRECT
FOCUSED_TEST = coverage.FOCUSED_TEST
BEHAVIOR_CHANGE = coverage.BEHAVIOR_CHANGE
RESOLVED = coverage.RESOLVED
PASS = "PASS"
FAIL = "FAIL"

MAX_PATH_CHARS = 300
MAX_SYMBOL_CHARS = 240
MAX_TEXT_CHARS = 900
MAX_PLAN_CHARS = planning.MAX_PLAN_CHARS
MAX_ORACLE_TIMEOUT_SECONDS = 60


class VerificationGapRemediationError(ValueError):
    """A deterministic remediation/proposal/oracle validation failure."""

    def __init__(self, code: str, message: str, details: Iterable[Any] | None = None):
        self.code = str(code)
        self.details = list(details or [])
        super().__init__(f"{self.code}: {message}")


class _FrozenRecord(dict):
    """JSON-shaped immutable record with ordinary mapping access."""

    def _immutable(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError("V25.4 remediation records are immutable")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _immutable

    def __ior__(self, _other: Any) -> Any:
        self._immutable()

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[str, Any]:
        result = {copy.deepcopy(key, memo): copy.deepcopy(value, memo) for key, value in self.items()}
        memo[id(self)] = result
        return result


class BehaviorObservableContract(_FrozenRecord):
    """Immutable explicit additive-observable proposal."""


class DirectBehaviorOracleSpec(_FrozenRecord):
    """Immutable verifier-owned executable behavior oracle specification."""


class VerificationGapRemediationProposal(_FrozenRecord):
    """Immutable proposal that has no approval or mutation authority."""


class RevisedPlanApprovalSummary(_FrozenRecord):
    """Immutable compact semantic payload for a future approval decision."""


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


def _freeze_record(record_type: type[_FrozenRecord], value: dict[str, Any]) -> _FrozenRecord:
    result = record_type()
    dict.__init__(result, ((key, freeze(item)) for key, item in value.items()))
    return result


def _text(value: Any, limit: int = MAX_TEXT_CHARS) -> str:
    text = " ".join(str(value or "").split())
    return text[: max(0, int(limit))]


def _path(value: Any) -> str:
    result = _text(value, MAX_PATH_CHARS).replace("\\", "/")
    while result.startswith("./"):
        result = result[2:]
    return result.rstrip("/")


def _symbol(value: Any) -> str:
    return _text(value, MAX_SYMBOL_CHARS)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        item = _text(value)
        if item and item not in seen:
            result.append(item)
            seen.add(item)
    return result


def _json_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str))


def _normalise_export(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return {
            "kind": _text(value.get("kind"), 80),
            "path": _path(value.get("path")),
            "symbol": _symbol(value.get("symbol")),
        }
    if isinstance(value, (list, tuple)) and len(value) >= 2:
        return {"kind": ADDITIVE_EXPORT, "path": _path(value[0]), "symbol": _symbol(value[1])}
    return {"kind": "", "path": "", "symbol": ""}


def _normalise_state_source(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"owner": "", "interface": ""}
    return {
        "owner": _symbol(value.get("owner")),
        "interface": _text(value.get("interface"), MAX_TEXT_CHARS),
    }


def _normalise_expectation(value: Any, *, paused: bool = False) -> dict[str, Any]:
    if not isinstance(value, dict):
        value = {"equals": value} if value is not None else {}
    result: dict[str, Any] = {
        "return_type": _text(value.get("return_type") or value.get("type"), 100),
        "non_empty": bool(value.get("non_empty")) if "non_empty" in value else paused,
    }
    if "equals" in value:
        result["equals"] = value.get("equals")
    return result


def _normalise_legacy(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {"symbol": "", "signature": "", "return_type": "", "outputs": [], "change_authorized": True}
    outputs = value.get("outputs")
    if outputs is None:
        outputs = value.get("expected_outputs", [])
    return {
        "symbol": _symbol(value.get("symbol")),
        "signature": _text(value.get("signature"), MAX_TEXT_CHARS),
        "return_type": _text(value.get("return_type") or value.get("type"), 100),
        "outputs": list(outputs) if isinstance(outputs, (list, tuple)) else [],
        "change_authorized": bool(value.get("change_authorized")),
    }


def _contract_payload(value: dict[str, Any]) -> dict[str, Any]:
    return _without(value, "contract_hash")


def behavior_observable_contract_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_contract_payload(value))


def build_behavior_observable_contract(
    *,
    contract_id: str,
    target_path: str,
    symbol: str,
    signature: str,
    export: dict[str, Any] | tuple[str, str] | list[str],
    state_source: dict[str, Any],
    running: dict[str, Any] | str,
    paused: dict[str, Any] | None,
    legacy_interface: dict[str, Any],
    new_state_owner: bool = False,
    worker_mutable: bool = False,
) -> BehaviorObservableContract:
    value = {
        "schema_version": CONTRACT_SCHEMA_VERSION,
        "contract_id": _text(contract_id, 180),
        "target_path": _path(target_path),
        "symbol": _symbol(symbol),
        "signature": _text(signature, MAX_TEXT_CHARS),
        "export": _normalise_export(export),
        "state_source": _normalise_state_source(state_source),
        "new_state_owner": bool(new_state_owner),
        "running": _normalise_expectation(running),
        "paused": _normalise_expectation(paused, paused=True),
        "legacy_interface": _normalise_legacy(legacy_interface),
        "worker_mutable": bool(worker_mutable),
        "contract_hash": "",
    }
    value["contract_hash"] = behavior_observable_contract_hash(value)
    checked = validate_behavior_observable_contract(value)
    if not checked["valid"]:
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            "; ".join(checked["errors"]), checked["errors"],
        )
    return _freeze_record(BehaviorObservableContract, value)


def validate_behavior_observable_contract(value: Any) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    errors: list[str] = []
    if record.get("schema_version") != CONTRACT_SCHEMA_VERSION:
        errors.append("observable contract schema version is invalid")
    for field in ("contract_id", "target_path", "symbol", "signature"):
        if not _text(record.get(field)):
            errors.append(f"observable contract {field} is required")
    target_path = _path(record.get("target_path"))
    exported = record.get("export") if isinstance(record.get("export"), dict) else {}
    if exported.get("kind") != ADDITIVE_EXPORT:
        errors.append("observable contract must authorize an additive export")
    if _path(exported.get("path")) != target_path:
        errors.append("observable export path must equal the approved target path")
    if _symbol(exported.get("symbol")) != _symbol(record.get("symbol")):
        errors.append("observable export symbol must equal the observable symbol")
    state_source = record.get("state_source") if isinstance(record.get("state_source"), dict) else {}
    if not _symbol(state_source.get("owner")) or not _text(state_source.get("interface")):
        errors.append("observable state source owner and interface are required")
    if record.get("new_state_owner") is not False:
        errors.append("observable contract cannot introduce a new state owner")
    if record.get("worker_mutable") is not False:
        errors.append("observable contract must be immutable during Worker execution")
    for name in ("running", "paused"):
        expectation = record.get(name) if isinstance(record.get(name), dict) else {}
        if expectation.get("return_type") != "primitive string":
            errors.append(f"{name} observable must return a primitive string")
        if name == "running":
            if not isinstance(expectation.get("equals"), str):
                errors.append("running observable must declare a string equality")
            if expectation.get("non_empty") is not False:
                errors.append("running observable must declare non-empty=false")
        elif expectation.get("non_empty") is not True:
            errors.append("paused observable must declare non-empty=true")
    legacy = record.get("legacy_interface") if isinstance(record.get("legacy_interface"), dict) else {}
    if not _symbol(legacy.get("symbol")) or not _text(legacy.get("signature")):
        errors.append("legacy interface symbol and signature are required")
    if legacy.get("return_type") != "primitive string":
        errors.append("legacy interface must remain a primitive string")
    if not isinstance(legacy.get("outputs"), list) or not legacy.get("outputs"):
        errors.append("legacy interface outputs are required")
    elif any(not isinstance(item, str) for item in legacy.get("outputs", [])):
        errors.append("legacy interface outputs must be strings")
    if legacy.get("change_authorized") is not False:
        errors.append("legacy interface replacement is not authorized")
    expected_hash = behavior_observable_contract_hash(record)
    if record.get("contract_hash") != expected_hash:
        errors.append("observable contract hash does not match content")
    return {
        "valid": not errors,
        "status": VERIFICATION_GAP_REMEDIATION_VALID if not errors else VERIFICATION_GAP_REMEDIATION_INVALID,
        "errors": errors[:40],
        "contract_hash": record.get("contract_hash"),
        "serialized_chars": _json_size(record),
    }


def _oracle_payload(value: dict[str, Any]) -> dict[str, Any]:
    return _without(value, "oracle_hash")


def direct_behavior_oracle_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_oracle_payload(value))


def _normalise_legacy_assertions(value: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        outputs = item.get("outputs") if isinstance(item.get("outputs"), list) else item.get("expected_outputs", [])
        result.append({
            "symbol": _symbol(item.get("symbol")),
            "signature": _text(item.get("signature"), MAX_TEXT_CHARS),
            "return_type": _text(item.get("return_type") or item.get("type"), 100),
            "outputs": list(outputs) if isinstance(outputs, (list, tuple)) else [],
            "preserve": item.get("preserve") is not False,
        })
    return result


def build_direct_behavior_oracle_spec(
    *,
    oracle_id: str,
    obligation_id: str,
    target_module_path: str,
    target_symbol: str,
    function_signature: str,
    controller_module_path: str,
    controller_symbol: str,
    state_query_symbol: str,
    toggle_symbol: str,
    running_expectation: dict[str, Any],
    paused_expectation: dict[str, Any],
    legacy_compatibility: list[dict[str, Any]],
    source_plan_reference: dict[str, Any],
    observable_contract_hash: str,
    oracle_type: str = FOCUSED_TEST,
    mandatory: bool = True,
    applicable: bool = True,
    execution_spec: dict[str, Any] | None = None,
    oracle_artifact_paths: list[str] | None = None,
    oracle_owner: str = HIVO_VERIFIER,
    worker_mutable: bool = False,
) -> DirectBehaviorOracleSpec:
    execution = _copy(execution_spec) if isinstance(execution_spec, dict) else {
        "runner": "node",
        "probe_kind": "HIVO_VERIFIER_DYNAMIC_MODULE_PROBE",
        "generated_outside_workspace": True,
        "timeout_seconds": 20,
        "command_template": ["node", "<generated_probe>", "<generated_spec>"],
    }
    value = {
        "schema_version": ORACLE_SCHEMA_VERSION,
        "oracle_id": _text(oracle_id, 180),
        "obligation_id": _text(obligation_id, 180),
        "oracle_type": _text(oracle_type, 100).upper(),
        "coverage_relationship": DIRECT,
        "target_module_path": _path(target_module_path),
        "target_symbol": _symbol(target_symbol),
        "function_signature": _text(function_signature, MAX_TEXT_CHARS),
        "controller_module_path": _path(controller_module_path),
        "controller_symbol": _symbol(controller_symbol),
        "state_query_symbol": _symbol(state_query_symbol),
        "toggle_symbol": _symbol(toggle_symbol),
        "running_expectation": _normalise_expectation(running_expectation),
        "paused_expectation": _normalise_expectation(paused_expectation, paused=True),
        "legacy_compatibility": _normalise_legacy_assertions(legacy_compatibility),
        "observable_contract_hash": _text(observable_contract_hash, 100),
        "mandatory": bool(mandatory),
        "applicable": bool(applicable),
        "oracle_owner": _text(oracle_owner, 100),
        "worker_mutable": bool(worker_mutable),
        "oracle_artifact_paths": [_path(item) for item in (oracle_artifact_paths or []) if _path(item)],
        "execution_spec": execution,
        "source_plan_reference": {
            "plan_id": _text((source_plan_reference or {}).get("plan_id"), 180),
            "plan_hash": _text((source_plan_reference or {}).get("plan_hash"), 100),
        },
        "checks": [
            {"kind": "EXPORT_CALLABLE", "symbol": _symbol(target_symbol)},
            {"kind": "RUNNING_PRIMITIVE_STRING", "equals": _copy((running_expectation or {}).get("equals"))},
            {"kind": "PAUSED_PRIMITIVE_STRING_NON_EMPTY", "non_empty": True},
            {"kind": "LEGACY_PRIMITIVE_STRING_OUTPUTS", "assertions": _normalise_legacy_assertions(legacy_compatibility)},
            {"kind": "STATE_SOURCE_IS_SUPPLIED_CONTROLLER", "owner": _symbol(controller_symbol)},
        ],
        "oracle_hash": "",
    }
    value["oracle_hash"] = direct_behavior_oracle_hash(value)
    checked = validate_direct_behavior_oracle_spec(value)
    if not checked["valid"]:
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            "; ".join(checked["errors"]), checked["errors"],
        )
    return _freeze_record(DirectBehaviorOracleSpec, value)


def _contains_forbidden_source_only(value: Any) -> bool:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).casefold()
    forbidden = (
        "source_presence", "source-only", "source_only", "literal_present",
        "worker_prose", "test_name_only", "file_contains",
    )
    return any(marker in encoded for marker in forbidden)


def validate_direct_behavior_oracle_spec(value: Any, observable_contract: Any = None) -> dict[str, Any]:
    record = value if isinstance(value, dict) else {}
    errors: list[str] = []
    if record.get("schema_version") != ORACLE_SCHEMA_VERSION:
        errors.append("direct oracle schema version is invalid")
    for field in (
        "oracle_id", "obligation_id", "target_module_path", "target_symbol",
        "function_signature", "controller_module_path", "controller_symbol",
        "state_query_symbol", "toggle_symbol",
    ):
        if not _text(record.get(field)):
            errors.append(f"direct oracle {field} is required")
    if record.get("oracle_type") not in {FOCUSED_TEST, coverage.INTEGRATION_TEST}:
        errors.append("direct oracle type must be focused or integration")
    if record.get("coverage_relationship") != DIRECT:
        errors.append("direct oracle must have DIRECT coverage relationship")
    if record.get("mandatory") is not True:
        errors.append("direct oracle must be mandatory")
    if record.get("applicable") is not True:
        errors.append("direct oracle must be applicable")
    if record.get("oracle_owner") != HIVO_VERIFIER:
        errors.append("direct oracle must be owned by the HIVO verifier")
    if record.get("worker_mutable") is not False:
        errors.append("direct oracle must not be Worker mutable")
    if record.get("oracle_artifact_paths") not in ([], None):
        errors.append("direct oracle artifacts must be outside Worker mutation authority")
    execution = record.get("execution_spec") if isinstance(record.get("execution_spec"), dict) else {}
    if execution.get("runner") != "node":
        errors.append("direct oracle execution runner must be node")
    if not execution.get("generated_outside_workspace"):
        errors.append("direct oracle probe must be generated outside the subject workspace")
    if not _text(execution.get("probe_kind")):
        errors.append("direct oracle probe kind is required")
    command_template = execution.get("command_template")
    if not isinstance(command_template, list) or not command_template or str(command_template[0]).casefold() != "node":
        errors.append("direct oracle command must be a bounded node command")
    try:
        timeout = int(execution.get("timeout_seconds", 20))
        if timeout < 1 or timeout > MAX_ORACLE_TIMEOUT_SECONDS:
            errors.append("direct oracle timeout is outside its bound")
    except (TypeError, ValueError):
        errors.append("direct oracle timeout is invalid")
    running = record.get("running_expectation") if isinstance(record.get("running_expectation"), dict) else {}
    paused = record.get("paused_expectation") if isinstance(record.get("paused_expectation"), dict) else {}
    if running.get("return_type") != "primitive string" or not isinstance(running.get("equals"), str):
        errors.append("direct oracle running expectation must be a primitive string equality")
    if running.get("non_empty") is not False:
        errors.append("direct oracle running expectation must be empty/non-empty=false")
    if paused.get("return_type") != "primitive string" or paused.get("non_empty") is not True:
        errors.append("direct oracle paused expectation must be a non-empty primitive string")
    legacy = record.get("legacy_compatibility")
    if not isinstance(legacy, list) or not legacy:
        errors.append("direct oracle legacy compatibility assertions are required")
    else:
        for item in legacy:
            if not isinstance(item, dict) or not item.get("symbol") or item.get("return_type") != "primitive string" or not item.get("outputs") or item.get("preserve") is not True:
                errors.append("direct oracle legacy assertions must preserve primitive-string outputs")
    ref = record.get("source_plan_reference") if isinstance(record.get("source_plan_reference"), dict) else {}
    if not ref.get("plan_id") or not ref.get("plan_hash"):
        errors.append("direct oracle source plan reference is required")
    if not _text(record.get("observable_contract_hash"), 100):
        errors.append("direct oracle observable-contract binding is required")
    if _contains_forbidden_source_only(record):
        errors.append("source-presence-only or Worker-prose oracle is not a direct behavior oracle")
    checks = record.get("checks")
    if not isinstance(checks, list) or not any(isinstance(item, dict) and item.get("kind") == "EXPORT_CALLABLE" for item in checks):
        errors.append("direct oracle executable export check is missing")
    if not any(isinstance(item, dict) and item.get("kind") == "RUNNING_PRIMITIVE_STRING" for item in _as_list(checks)):
        errors.append("direct oracle running check is missing")
    if not any(isinstance(item, dict) and item.get("kind") == "PAUSED_PRIMITIVE_STRING_NON_EMPTY" for item in _as_list(checks)):
        errors.append("direct oracle paused check is missing")
    if not any(isinstance(item, dict) and item.get("kind") == "LEGACY_PRIMITIVE_STRING_OUTPUTS" for item in _as_list(checks)):
        errors.append("direct oracle legacy check is missing")
    expected_checks = [
        {"kind": "EXPORT_CALLABLE", "symbol": _symbol(record.get("target_symbol"))},
        {
            "kind": "RUNNING_PRIMITIVE_STRING",
            "equals": _copy(running.get("equals")),
        },
        {"kind": "PAUSED_PRIMITIVE_STRING_NON_EMPTY", "non_empty": True},
        {
            "kind": "LEGACY_PRIMITIVE_STRING_OUTPUTS",
            "assertions": _normalise_legacy_assertions(legacy),
        },
        {
            "kind": "STATE_SOURCE_IS_SUPPLIED_CONTROLLER",
            "owner": _symbol(record.get("controller_symbol")),
        },
    ]
    if checks != expected_checks:
        errors.append("direct oracle executable checks do not match its declared semantics")
    if isinstance(observable_contract, dict):
        contract_check = validate_behavior_observable_contract(observable_contract)
        if not contract_check["valid"]:
            errors.extend(f"observable contract: {item}" for item in contract_check["errors"])
        elif record.get("observable_contract_hash") != observable_contract.get("contract_hash"):
            errors.append("direct oracle observable-contract hash does not match contract")
        if _path(record.get("target_module_path")) != _path(observable_contract.get("target_path")):
            errors.append("direct oracle target does not match observable contract")
        if _symbol(record.get("target_symbol")) != _symbol(observable_contract.get("symbol")):
            errors.append("direct oracle symbol does not match observable contract")
    expected_hash = direct_behavior_oracle_hash(record)
    if record.get("oracle_hash") != expected_hash:
        errors.append("direct oracle hash does not match content")
    return {
        "valid": not errors,
        "status": VERIFICATION_GAP_REMEDIATION_VALID if not errors else VERIFICATION_GAP_REMEDIATION_INVALID,
        "errors": errors[:50],
        "oracle_hash": record.get("oracle_hash"),
        "serialized_chars": _json_size(record),
    }


def _proposal_payload(value: dict[str, Any]) -> dict[str, Any]:
    return _without(value, "proposal_hash")


def remediation_proposal_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_proposal_payload(value))


def approval_summary_hash(value: dict[str, Any]) -> str:
    return canonical_hash(_without(value, "summary_hash"))


def _plan_mutation_paths(plan: dict[str, Any]) -> set[str]:
    result: set[str] = set()
    for node in _as_list(plan.get("approved_change_nodes")):
        if not isinstance(node, dict) or not node.get("mutation_required") or node.get("verification_only"):
            continue
        for path in _as_list(node.get("candidate_targets")) + _as_list(node.get("target_paths")):
            if _path(path):
                result.add(_path(path).casefold())
    return result


def _plan_dnt_paths(plan: dict[str, Any]) -> set[str]:
    return {_path(item).casefold() for item in _as_list(plan.get("do_not_touch")) if _path(item)}


def _affected_surface(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        paths = [_path(item) for item in _as_list(value.get("paths") or value.get("path")) if _path(item)]
        surfaces = _unique_strings(value.get("surface_ids") or value.get("surface_id"))
    else:
        paths = [_path(item) for item in _as_list(value) if _path(item)]
        surfaces = []
    return {"paths": paths, "surface_ids": surfaces}


def build_verification_gap_remediation_proposal(
    *,
    proposal_id: str,
    old_plan_id: str,
    old_plan_hash: str,
    v25_3_coverage_hash: str,
    uncovered_obligation_id: str,
    obligation_type: str,
    proposed_observable_contract: BehaviorObservableContract | dict[str, Any],
    proposed_direct_oracle: DirectBehaviorOracleSpec | dict[str, Any],
    affected_mutation_surface: dict[str, Any] | list[str] | str,
    preservation_references: list[Any],
    proposal_provenance: str = VERIFICATION_OBLIGATION_UNCOVERED,
) -> VerificationGapRemediationProposal:
    contract = _copy(proposed_observable_contract)
    oracle = _copy(proposed_direct_oracle)
    value = {
        "schema_version": SCHEMA_VERSION,
        "proposal_id": _text(proposal_id, 180),
        "proposal_type": "EXPLICIT_BEHAVIOR_OBSERVABLE_REMEDIATION",
        "old_plan_id": _text(old_plan_id, 180),
        "old_plan_hash": _text(old_plan_hash, 100),
        "v25_3_coverage_hash": _text(v25_3_coverage_hash, 100),
        "uncovered_obligation_id": _text(uncovered_obligation_id, 180),
        "obligation_type": _text(obligation_type, 100).upper(),
        "proposed_observable_contract": contract,
        "proposed_direct_oracle": oracle,
        "affected_mutation_surface": _affected_surface(affected_mutation_surface),
        "preservation_references": _unique_strings(preservation_references),
        "proposal_provenance": _text(proposal_provenance, 180),
        "execution_authority": False,
        "fresh_approval_required": True,
        "worker_mutable": False,
        "proposal_hash": "",
    }
    value["proposal_hash"] = remediation_proposal_hash(value)
    return _freeze_record(VerificationGapRemediationProposal, value)


def validate_verification_gap_remediation_proposal(
    proposal: Any,
    *,
    old_plan: dict[str, Any] | None = None,
    current_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = proposal if isinstance(proposal, dict) else {}
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("remediation proposal schema version is invalid")
    for field in (
        "proposal_id", "old_plan_id", "old_plan_hash", "v25_3_coverage_hash",
        "uncovered_obligation_id", "proposal_provenance",
    ):
        if not _text(value.get(field)):
            errors.append(f"remediation proposal {field} is required")
    if value.get("obligation_type") != BEHAVIOR_CHANGE:
        errors.append("remediation proposal must target a behavior-change obligation")
    if value.get("proposal_type") != "EXPLICIT_BEHAVIOR_OBSERVABLE_REMEDIATION":
        errors.append("remediation proposal type is invalid")
    if value.get("execution_authority") is not False:
        errors.append("remediation proposal is not execution authority")
    if value.get("fresh_approval_required") is not True:
        errors.append("remediation proposal must require fresh approval")
    if value.get("worker_mutable") is not False:
        errors.append("remediation proposal must be immutable")
    contract = value.get("proposed_observable_contract")
    contract_check = validate_behavior_observable_contract(contract)
    errors.extend(f"observable contract: {item}" for item in contract_check["errors"])
    oracle = value.get("proposed_direct_oracle")
    oracle_check = validate_direct_behavior_oracle_spec(oracle, contract)
    errors.extend(f"direct oracle: {item}" for item in oracle_check["errors"])
    if isinstance(contract, dict) and isinstance(oracle, dict):
        if oracle.get("obligation_id") != value.get("uncovered_obligation_id"):
            errors.append("direct oracle must bind the uncovered obligation")
        if oracle.get("observable_contract_hash") != contract.get("contract_hash"):
            errors.append("direct oracle must bind the proposed observable contract")
    affected = value.get("affected_mutation_surface") if isinstance(value.get("affected_mutation_surface"), dict) else {}
    affected_paths = {_path(item).casefold() for item in _as_list(affected.get("paths")) if _path(item)}
    affected_surfaces = {_text(item).casefold() for item in _as_list(affected.get("surface_ids")) if _text(item)}
    if not affected_paths:
        errors.append("affected mutation surface is required")
    if not _as_list(value.get("preservation_references")):
        errors.append("preservation references are required")
    if isinstance(old_plan, dict):
        if value.get("old_plan_id") != old_plan.get("plan_id"):
            errors.append("proposal old plan ID does not match source plan")
        if value.get("old_plan_hash") != old_plan.get("plan_hash"):
            errors.append("proposal old plan hash does not match source plan")
        if planning.plan_content_hash(old_plan) != old_plan.get("plan_hash"):
            errors.append("source plan hash is invalid")
        allowed = _plan_mutation_paths(old_plan)
        dnt = _plan_dnt_paths(old_plan)
        allowed_surfaces = {
            _text(surface_id).casefold()
            for node in _as_list(old_plan.get("approved_change_nodes"))
            if isinstance(node, dict) and node.get("mutation_required") and not node.get("verification_only")
            for surface_id in _as_list(node.get("target_surface_ids") or node.get("surface_ids"))
            if _text(surface_id)
        }
        if not affected_paths.issubset(allowed):
            errors.append("remediation surface is outside approved mutation scope")
        if affected_paths.intersection(dnt):
            errors.append("remediation surface overlaps DNT")
        if affected_surfaces and allowed_surfaces and not affected_surfaces.issubset(allowed_surfaces):
            errors.append("remediation surface identity is outside approved mutation scope")
        if isinstance(contract, dict) and _path(contract.get("target_path")).casefold() not in allowed:
            errors.append("observable target is outside approved mutation scope")
        if isinstance(oracle, dict) and _path(oracle.get("target_module_path")).casefold() not in allowed:
            errors.append("oracle target is outside approved mutation scope")
        oracle_ref = oracle.get("source_plan_reference") if isinstance(oracle, dict) and isinstance(oracle.get("source_plan_reference"), dict) else {}
        if oracle_ref and (
            oracle_ref.get("plan_id") != old_plan.get("plan_id")
            or oracle_ref.get("plan_hash") != old_plan.get("plan_hash")
        ):
            errors.append("oracle source plan reference does not match source plan")
    if isinstance(current_coverage, dict):
        if current_coverage.get("coverage_hash") != value.get("v25_3_coverage_hash"):
            errors.append("proposal coverage hash does not match V25.3 artifact")
        if current_coverage.get("status") != VERIFICATION_OBLIGATION_UNCOVERED:
            errors.append("proposal source coverage is not the uncovered-obligation state")
        if value.get("uncovered_obligation_id") not in set(current_coverage.get("uncovered_obligation_ids", []) or []):
            errors.append("proposal does not target the exact uncovered obligation")
    if remediation_proposal_hash(value) != value.get("proposal_hash"):
        errors.append("remediation proposal hash does not match content")
    return {
        "valid": not errors,
        "status": VERIFICATION_GAP_REMEDIATION_VALID if not errors else VERIFICATION_GAP_REMEDIATION_INVALID,
        "code": None if not errors else VERIFICATION_GAP_REMEDIATION_INVALID,
        "errors": errors[:60],
        "proposal_hash": value.get("proposal_hash"),
    }


def _compact_contract_for_plan(contract: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_id": contract.get("contract_id"),
        "target_path": contract.get("target_path"),
        "symbol": contract.get("symbol"),
        "signature": contract.get("signature"),
        "export": contract.get("export"),
        "state_source": contract.get("state_source"),
        "new_state_owner": contract.get("new_state_owner"),
        "running": contract.get("running"),
        "paused": contract.get("paused"),
        "legacy_interface": contract.get("legacy_interface"),
        "worker_mutable": contract.get("worker_mutable", False),
        "contract_hash": contract.get("contract_hash"),
    }


def _compact_oracle_for_plan(oracle: dict[str, Any]) -> dict[str, Any]:
    return {
        "oracle_id": oracle.get("oracle_id"),
        "obligation_id": oracle.get("obligation_id"),
        "oracle_type": oracle.get("oracle_type"),
        "coverage_relationship": oracle.get("coverage_relationship"),
        "target_module_path": oracle.get("target_module_path"),
        "target_symbol": oracle.get("target_symbol"),
        "mandatory": oracle.get("mandatory"),
        "applicable": oracle.get("applicable"),
        "oracle_owner": oracle.get("oracle_owner"),
        "worker_mutable": oracle.get("worker_mutable"),
        "observable_contract_hash": oracle.get("observable_contract_hash"),
        "oracle_hash": oracle.get("oracle_hash"),
    }


def validate_revised_plan_authority(revised_plan: dict[str, Any]) -> dict[str, Any]:
    """Validate the V25.4 artifacts retained by a revised canonical plan."""
    plan = revised_plan if isinstance(revised_plan, dict) else {}
    errors: list[str] = []
    contracts = _as_list(plan.get("behavior_observable_contracts"))
    oracles = _as_list(plan.get("direct_behavior_oracles"))
    if len(contracts) != 1:
        errors.append("revised plan must retain exactly one behavior observable contract")
    if len(oracles) != 1:
        errors.append("revised plan must retain exactly one direct behavior oracle")
    observable = contracts[0] if contracts and isinstance(contracts[0], dict) else {}
    if observable.get("schema_version") == CONTRACT_SCHEMA_VERSION:
        observable_check = validate_behavior_observable_contract(observable)
        errors.extend(f"observable contract: {item}" for item in observable_check["errors"])
    else:
        # The canonical plan carries the same contract in its bounded compact
        # form; the immutable full artifact remains in the remediation
        # proposal and is hash-bound below.
        for field in (
            "contract_id", "target_path", "symbol", "signature", "contract_hash",
        ):
            if not _text(observable.get(field)):
                errors.append(f"compact observable contract {field} is required")
        exported = observable.get("export") if isinstance(observable.get("export"), dict) else {}
        if exported.get("kind") != ADDITIVE_EXPORT:
            errors.append("compact observable contract must authorize an additive export")
        if _path(exported.get("path")) != _path(observable.get("target_path")):
            errors.append("compact observable export path mismatch")
        state_source = observable.get("state_source") if isinstance(observable.get("state_source"), dict) else {}
        if not _symbol(state_source.get("owner")) or not _text(state_source.get("interface")):
            errors.append("compact observable state source is incomplete")
        if observable.get("new_state_owner") is not False or observable.get("worker_mutable") is not False:
            errors.append("compact observable may not add state or Worker mutability")
        for name, non_empty in (("running", False), ("paused", True)):
            expectation = observable.get(name) if isinstance(observable.get(name), dict) else {}
            if expectation.get("return_type") != "primitive string" or expectation.get("non_empty") is not non_empty:
                errors.append(f"compact observable {name} expectation is invalid")
        legacy = observable.get("legacy_interface") if isinstance(observable.get("legacy_interface"), dict) else {}
        if (
            not _symbol(legacy.get("symbol"))
            or legacy.get("return_type") != "primitive string"
            or not legacy.get("outputs")
            or legacy.get("change_authorized") is not False
        ):
            errors.append("compact observable legacy interface is invalid")
    oracle = oracles[0] if oracles and isinstance(oracles[0], dict) else {}
    for field in (
        "oracle_id", "obligation_id", "oracle_type", "coverage_relationship",
        "target_module_path", "target_symbol", "observable_contract_hash",
        "oracle_hash", "oracle_owner",
    ):
        if not _text(oracle.get(field)):
            errors.append(f"revised plan direct oracle {field} is required")
    if oracle.get("oracle_type") not in {FOCUSED_TEST, coverage.INTEGRATION_TEST}:
        errors.append("revised plan direct oracle type is invalid")
    if oracle.get("coverage_relationship") != DIRECT:
        errors.append("revised plan direct oracle must be DIRECT")
    if oracle.get("mandatory") is not True or oracle.get("applicable") is not True:
        errors.append("revised plan direct oracle must be mandatory and applicable")
    if oracle.get("oracle_owner") != HIVO_VERIFIER or oracle.get("worker_mutable") is not False:
        errors.append("revised plan direct oracle must be immutable HIVO authority")
    if observable and oracle.get("observable_contract_hash") != observable.get("contract_hash"):
        errors.append("revised plan direct oracle does not bind its observable contract")
    if observable and (
        _path(oracle.get("target_module_path")) != _path(observable.get("target_path"))
        or _symbol(oracle.get("target_symbol")) != _symbol(observable.get("symbol"))
    ):
        errors.append("revised plan direct oracle target does not match its observable")
    verification_records = [
        item for item in _as_list(plan.get("canonical_verification_contracts"))
        if isinstance(item, dict)
        and item.get("oracle_id") == oracle.get("oracle_id")
    ]
    if len(verification_records) != 1:
        errors.append("revised plan must retain one direct-oracle verification record")
    elif oracle:
        record = verification_records[0]
        if record.get("oracle_id") != oracle.get("oracle_id"):
            errors.append("V25.4 verification record oracle identity mismatch")
        if record.get("oracle_hash") != oracle.get("oracle_hash"):
            errors.append("V25.4 verification record oracle hash mismatch")
        if record.get("mandatory") is not True or record.get("approved") is not True:
            errors.append("V25.4 verification record must be approved and mandatory")
        binding = (record.get("obligation_bindings") or [{}])[0]
        if binding.get("obligation_id") != oracle.get("obligation_id") or binding.get("coverage_relationship") != DIRECT:
            errors.append("V25.4 verification record must directly bind the oracle obligation")
    revision = plan.get("verification_authority_revision")
    if not isinstance(revision, dict):
        errors.append("revised plan verification-authority provenance is required")
    elif revision.get("reason") != VERIFICATION_OBLIGATION_UNCOVERED:
        errors.append("revised plan remediation reason is invalid")
    summary = plan.get("verification_obligation_coverage_summary")
    if not isinstance(summary, dict) or summary.get("status") != EXECUTION_VERIFICATION_READY or summary.get("verification_ready") is not True:
        errors.append("revised plan verification coverage summary is not ready")
    if plan.get("approval_boundary") != PLAN_APPROVAL_REQUIRED or plan.get("terminal_state") != PLAN_APPROVAL_REQUIRED:
        errors.append("revised plan approval boundary is invalid")
    if plan.get("approval_required") is not True or plan.get("approval_granted") is not False:
        errors.append("revised plan must require fresh approval and remain unapproved")
    return {
        "valid": not errors,
        "status": VERIFICATION_GAP_REMEDIATION_VALID if not errors else VERIFICATION_GAP_REMEDIATION_INVALID,
        "errors": errors[:80],
    }


def build_revised_plan_approval_summary(
    revised_plan: dict[str, Any],
    proposal: VerificationGapRemediationProposal | dict[str, Any],
    coverage_artifact: dict[str, Any],
) -> RevisedPlanApprovalSummary:
    """Produce the compact payload a user would approve next.

    This summary is descriptive and immutable.  It carries no approval
    event, receipt, authorization, or mutation capability.
    """
    plan = revised_plan if isinstance(revised_plan, dict) else {}
    proposed = proposal if isinstance(proposal, dict) else {}
    observable = proposed.get("proposed_observable_contract")
    oracle = proposed.get("proposed_direct_oracle")
    requirements = [
        {
            "requirement_id": _text(item.get("requirement_id"), 180),
            "text": _text(item.get("text"), MAX_TEXT_CHARS),
        }
        for item in _as_list(plan.get("requirements"))
        if isinstance(item, dict) and item.get("requirement_id")
    ]
    atomic = [
        item for item in _as_list((coverage_artifact or {}).get("atomic_obligations"))
        if isinstance(item, dict) and item.get("obligation_id")
    ]
    uncovered = _unique_strings(
        (coverage_artifact or {}).get("uncovered_obligation_ids", [])
    )
    required_count = len(atomic)
    covered_count = max(0, required_count - len(uncovered))
    value = {
        "schema_version": APPROVAL_SUMMARY_SCHEMA_VERSION,
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "requirements": requirements,
        "mutation_scope": _copy(proposed.get("affected_mutation_surface", {})),
        "do_not_touch": _unique_strings(plan.get("do_not_touch", [])),
        "dependencies": _copy(plan.get("dependencies", [])),
        "additive_observable": _compact_contract_for_plan(observable or {}),
        "direct_verification_oracle": _compact_oracle_for_plan(oracle or {}),
        "verification_coverage": {
            "status": (coverage_artifact or {}).get("status"),
            "verification_ready": (coverage_artifact or {}).get("verification_ready") is True,
            "covered": covered_count,
            "required": required_count,
            "coverage_hash": (coverage_artifact or {}).get("coverage_hash"),
        },
        "legacy_render_status_preserved": (
            _copy((observable or {}).get("legacy_interface"))
            if isinstance(observable, dict) else {}
        ),
        "fresh_approval_required": plan.get("fresh_approval_required") is True,
        "approval_required": plan.get("approval_required") is True,
        "approval_granted": plan.get("approval_granted") is True,
        "terminal_state": plan.get("terminal_state"),
        "summary_hash": "",
    }
    value["summary_hash"] = approval_summary_hash(value)
    return _freeze_record(RevisedPlanApprovalSummary, value)


def _new_verification_record(
    contract: dict[str, Any], oracle: dict[str, Any], *,
    requirement_id: str, node_id: str, surface_id: str,
    verification_id: str | None = None,
) -> dict[str, Any]:
    return {
        "verification_id": verification_id or "VERIFICATION-DIRECT",
        "contract": [
            f"{oracle.get('target_module_path')} direct oracle {contract.get('symbol')}; "
            f"legacy"
        ],
        "node_ids": [node_id],
        "provenance": planning.DERIVED_PLAN_DECISION,
        "requirement_ids": [requirement_id],
        "surface_ids": [surface_id],
        "oracle_type": oracle.get("oracle_type"),
        "oracle_id": oracle.get("oracle_id"),
        "oracle_hash": oracle.get("oracle_hash"),
        "target": oracle.get("target_module_path"),
        "approved": True,
        "mandatory": True,
        "authority_source": HIVO_VERIFIER,
        "obligation_bindings": [{
            "obligation_id": oracle.get("obligation_id"),
            "coverage_relationship": DIRECT,
            "coverage_strength": coverage.STRONG,
            "mandatory": True,
            "applicable": True,
            "semantic_binding": {
                "observable": contract.get("symbol"),
                "assertion": "primitive strings",
                "expected_behavior": "running empty; paused non-empty; legacy",
            },
        }],
    }


def _revision_metadata(old_plan: dict[str, Any], current_coverage: dict[str, Any], proposal: dict[str, Any], oracle: dict[str, Any]) -> dict[str, Any]:
    return {
        "old_plan_id": old_plan.get("plan_id"),
        "old_plan_hash": old_plan.get("plan_hash"),
        "v25_3_coverage_hash": current_coverage.get("coverage_hash"),
        "uncovered_obligation_id": proposal.get("uncovered_obligation_id"),
        "remediation_proposal_hash": proposal.get("proposal_hash"),
        "direct_behavior_oracle_hash": oracle.get("oracle_hash"),
        "reason": VERIFICATION_OBLIGATION_UNCOVERED,
    }


def _remove_redundant_plan_fields(value: dict[str, Any]) -> list[str]:
    """Remove only exact upstream projections when the canonical bound is tight."""
    removed: list[str] = []
    # These are copied artifacts, while their authoritative identities remain
    # in upstream_bindings, the requirement ledger, and the canonical plan
    # decision records.  The removal is deterministic and is performed only
    # to make room for the new verification authority; it never truncates a
    # semantic record.
    for field in (
        "verified_planning_context", "planning_provenance", "provenance", "bounds",
        # These are bounded copies of upstream authority. Their identities
        # remain available through canonical nodes, ledgers, and
        # upstream_bindings, while the revised plan reserves space for the
        # executable verification semantics.
        "challenger_reconciliation", "evidence_refs", "interfaces_to_reuse",
        "mutation_surface_ids", "interface_surface_ids",
        "planning_mode", "project_mode", "canonical_surface_registry_version", "version",
    ):
        if planning._json_size(value) <= MAX_PLAN_CHARS:
            break
        if field in value:
            value.pop(field, None)
            removed.append(field)
    return removed


def revise_canonical_plan_from_verification_gap(
    old_plan: dict[str, Any],
    current_coverage: dict[str, Any],
    proposal: VerificationGapRemediationProposal | dict[str, Any],
    *,
    requirements: list[dict[str, Any]] | None = None,
    repository_evidence: list[dict[str, Any]] | None = None,
    surface_registry: dict[str, Any] | None = None,
    authoritative_task_goal: str | None = None,
) -> dict[str, Any]:
    proposal_check = validate_verification_gap_remediation_proposal(
        proposal, old_plan=old_plan, current_coverage=current_coverage,
    )
    if not proposal_check["valid"]:
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            "; ".join(proposal_check["errors"]), proposal_check["errors"],
        )
    value = _copy(old_plan)
    contract = _copy(proposal["proposed_observable_contract"])
    oracle = _copy(proposal["proposed_direct_oracle"])
    old_contracts = _copy(value.get("canonical_verification_contracts", []))
    oracle_id = oracle.get("oracle_id")
    if any(
        isinstance(item, dict) and item.get("oracle_id") == oracle_id
        for item in old_contracts
    ):
        raise VerificationGapRemediationError(VERIFICATION_GAP_REMEDIATION_INVALID, "source plan already contains the V25.4 verification record")
    node = next(
        item for item in _as_list(value.get("approved_change_nodes"))
        if isinstance(item, dict) and item.get("mutation_required") and not item.get("verification_only")
    )
    requirement_id = str((node.get("requirement_ids") or value.get("requirements", [{}])[0].get("requirement_id"))[0])
    surface_id = str((node.get("target_surface_ids") or node.get("surface_ids") or [""])[0])
    node_id = str(node.get("node_id"))
    new_record = _new_verification_record(
        contract, oracle, requirement_id=requirement_id, node_id=node_id, surface_id=surface_id,
        verification_id=f"VERIFICATION-{len(old_contracts) + 1:03d}",
    )
    value["canonical_verification_contracts"] = old_contracts + [new_record]
    value["behavior_observable_contracts"] = [_compact_contract_for_plan(contract)]
    value["direct_behavior_oracles"] = [_compact_oracle_for_plan(oracle)]
    value["verification_authority_revision"] = _revision_metadata(value, current_coverage, proposal, oracle)
    value["verification_obligation_coverage_summary"] = {
        "status": EXECUTION_VERIFICATION_READY,
        "verification_ready": True,
        "required_obligation_count": len([
            item for item in current_coverage.get("atomic_obligations", [])
            if item.get("obligation_id")
        ]),
        "covered_obligation_count": len([
            item for item in current_coverage.get("atomic_obligations", [])
            if item.get("obligation_id")
        ]) - len(current_coverage.get("uncovered_obligation_ids", []) or []),
    }
    value["approval_boundary"] = PLAN_APPROVAL_REQUIRED
    value["terminal_state"] = PLAN_APPROVAL_REQUIRED
    value["approval_required"] = True
    value["approval_granted"] = False
    value["fresh_approval_required"] = True
    removed = _remove_redundant_plan_fields(value)
    if planning._json_size(value) > MAX_PLAN_CHARS:
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            f"revised canonical plan exceeds bound ({planning._json_size(value)} > {MAX_PLAN_CHARS})",
        )
    value = planning.finalize_plan_identity(value)
    # A full Stage 3 replay is not performed here.  When the caller supplies
    # the already-verified inputs, run the ordinary deterministic plan gate on
    # the resulting canonical representation.
    if requirements is not None and repository_evidence is not None:
        checked = planning.validate_change_plan(
            value, requirements, repository_evidence,
            project_mode=planning.EXISTING_PROJECT,
            surface_registry=surface_registry,
            obligation_ledger=value.get("requirement_obligation_ledger"),
            authoritative_task_goal=authoritative_task_goal,
        )
        if not checked.get("valid"):
            raise VerificationGapRemediationError(
                VERIFICATION_GAP_REMEDIATION_INVALID,
                "; ".join(checked.get("errors", [])), checked.get("errors", []),
            )
    return value


def compact_observable_contract(value: dict[str, Any]) -> dict[str, Any]:
    return _compact_contract_for_plan(value)


def compact_direct_behavior_oracle(value: dict[str, Any]) -> dict[str, Any]:
    return _compact_oracle_for_plan(value)


def build_revised_verification_contracts(
    revised_plan: dict[str, Any],
    proposal: dict[str, Any],
) -> list[dict[str, Any]]:
    """Return canonical verification authority without changing the plan."""
    contracts = _copy(revised_plan.get("canonical_verification_contracts", []))
    oracle = proposal.get("proposed_direct_oracle") if isinstance(proposal, dict) else {}
    if not any(
        isinstance(item, dict) and item.get("oracle_id") == (oracle or {}).get("oracle_id")
        for item in contracts
    ):
        raise VerificationGapRemediationError(VERIFICATION_GAP_REMEDIATION_INVALID, "revised plan lacks its direct behavior verification")
    return contracts


def compile_revised_plan_contractability(
    revised_plan: dict[str, Any],
    *,
    requirements: list[dict[str, Any]] | None = None,
    repository_evidence: list[dict[str, Any]] | None = None,
    surface_registry: dict[str, Any] | None = None,
    authoritative_task_goal: str | None = None,
    execution_invariant_set: dict[str, Any] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile Stage 4 structure from an unapproved plan for inspection.

    The returned contracts and graph are deliberately marked ineligible.  No
    receipt, approval event, or ``ApprovedExecutionAuthorization`` is created
    by this function.
    """
    value = revised_plan if isinstance(revised_plan, dict) else {}
    errors: list[str] = []
    if requirements is not None and repository_evidence is not None:
        plan_check = planning.validate_change_plan(
            value, requirements, repository_evidence,
            project_mode=planning.EXISTING_PROJECT,
            surface_registry=surface_registry,
            obligation_ledger=value.get("requirement_obligation_ledger"),
            authoritative_task_goal=authoritative_task_goal,
        )
        if not plan_check.get("valid"):
            errors.extend(plan_check.get("errors", []))
    if value.get("approval_granted") is True:
        errors.append("contractability input must be unapproved")
    if value.get("approval_required") is not True or value.get("terminal_state") != PLAN_APPROVAL_REQUIRED:
        errors.append("revised plan must stop at PLAN_APPROVAL_REQUIRED")
    revised_authority_check = validate_revised_plan_authority(value)
    if not revised_authority_check.get("valid"):
        errors.extend(revised_authority_check.get("errors", []))
    if verification_obligation_coverage is not None:
        coverage_check = coverage.validate_verification_obligation_coverage(
            verification_obligation_coverage, plan=value,
        )
        if not coverage_check.get("valid"):
            errors.extend(coverage_check.get("errors", []))
        elif coverage_check.get("status") != EXECUTION_VERIFICATION_READY:
            errors.append("verification obligation coverage is not complete")
    if errors:
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            "; ".join(errors), errors,
        )
    snapshot = stage4.create_plan_contractability_snapshot(
        value,
        authoritative_task_goal=authoritative_task_goal,
        requirements=requirements or value.get("requirements", []),
        repository_evidence=repository_evidence or [],
        canonical_surface_registry=surface_registry,
    )
    compiled = stage4.compile_execution_contracts(
        snapshot,
        execution_invariant_set=execution_invariant_set,
        verification_obligation_coverage=verification_obligation_coverage,
        contractability_only=True,
    )
    graph = stage4.build_execution_graph(snapshot, compiled.get("contracts", []))
    graph_check = stage4.validate_execution_graph(
        snapshot, graph, compiled.get("contracts", []),
    )
    if not graph_check.get("valid"):
        raise VerificationGapRemediationError(
            VERIFICATION_GAP_REMEDIATION_INVALID,
            "; ".join(graph_check.get("errors", [])), graph_check.get("errors", []),
        )
    return {
        "status": STAGE4_CONTRACTABILITY_PASS,
        "snapshot": snapshot,
        "contracts": compiled.get("contracts", []),
        "assignment": compiled.get("assignment", {}),
        "graph": graph,
        "validation": graph_check,
        "execution_eligible": False,
        "approval_required": True,
        "approval_granted": False,
        "authorization": None,
        "model_calls": 0,
        "worker_calls": 0,
    }


def _safe_workspace_path(workspace: str | os.PathLike, relative: str) -> Path:
    root = Path(workspace).expanduser().resolve()
    target = (root / _path(relative)).resolve()
    if root == target or root not in target.parents:
        raise VerificationGapRemediationError(VERIFICATION_GAP_REMEDIATION_INVALID, "oracle path escapes workspace")
    return target


def _probe_source() -> str:
    # All fixture-specific names and values are supplied through the JSON
    # specification.  The probe only implements generic observable checks.
    return r'''
const fs = require('fs');
const path = require('path');

function check(condition, name, detail) {
  return { name, passed: Boolean(condition), detail: detail || null };
}

function main() {
  const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
  const target = require(path.resolve(spec.workspace, spec.target_module_path));
  const controllerModule = require(path.resolve(spec.workspace, spec.controller_module_path));
  const Controller = controllerModule[spec.controller_symbol];
  const checks = [];
  const exported = target[spec.target_symbol];
  checks.push(check(typeof exported === 'function', 'export_callable', spec.target_symbol));
  if (typeof exported !== 'function' || typeof Controller !== 'function') {
    return checks;
  }
  const controller = new Controller();
  const query = controller[spec.state_query_symbol];
  const toggle = controller[spec.toggle_symbol];
  checks.push(check(typeof query === 'function', 'state_query_callable', spec.state_query_symbol));
  checks.push(check(typeof toggle === 'function', 'toggle_callable', spec.toggle_symbol));
  if (typeof query !== 'function' || typeof toggle !== 'function') {
    return checks;
  }
  const runningResult = exported(controller);
  checks.push(check(typeof runningResult === 'string', 'running_primitive_string', typeof runningResult));
  checks.push(check(runningResult === spec.running_expectation.equals, 'running_expected_value', runningResult));
  const runningState = query.call(controller);
  toggle.call(controller);
  const pausedState = query.call(controller);
  const pausedResult = exported(controller);
  checks.push(check(runningState !== pausedState, 'supplied_controller_state_changes', { runningState, pausedState }));
  checks.push(check(typeof pausedResult === 'string', 'paused_primitive_string', typeof pausedResult));
  checks.push(check(typeof pausedResult === 'string' && pausedResult.length > 0, 'paused_non_empty', pausedResult));
  checks.push(check(pausedState === true || pausedState !== runningState, 'state_source_is_supplied_controller', pausedState));
  const independentController = new Controller();
  const independentResult = exported(independentController);
  checks.push(check(
    typeof independentResult === 'string' && independentResult === spec.running_expectation.equals,
    'independent_controller_uses_own_state',
    independentResult,
  ));
  for (const assertion of (spec.legacy_compatibility || [])) {
    const legacy = target[assertion.symbol];
    checks.push(check(typeof legacy === 'function', 'legacy_export_callable:' + assertion.symbol, assertion.symbol));
    if (typeof legacy !== 'function') continue;
    const fresh = new Controller();
    const before = legacy(fresh);
    checks.push(check(typeof before === 'string', 'legacy_running_primitive_string:' + assertion.symbol, typeof before));
    if (assertion.outputs && assertion.outputs.length > 0) {
      checks.push(check(assertion.outputs.includes(before), 'legacy_running_output:' + assertion.symbol, before));
    }
    fresh[spec.toggle_symbol]();
    const after = legacy(fresh);
    checks.push(check(typeof after === 'string', 'legacy_paused_primitive_string:' + assertion.symbol, typeof after));
    if (assertion.outputs && assertion.outputs.length > 1) {
      checks.push(check(assertion.outputs.includes(after), 'legacy_paused_output:' + assertion.symbol, after));
    }
  }
  return checks;
}

try {
  const checks = main();
  const passed = checks.length > 0 && checks.every(item => item.passed);
  process.stdout.write('HIVO_ORACLE_RESULT:' + JSON.stringify({ passed, checks }) + '\n');
  process.exitCode = passed ? 0 : 1;
} catch (error) {
  process.stdout.write('HIVO_ORACLE_RESULT:' + JSON.stringify({ passed: false, checks: [], error: String(error && error.stack || error) }) + '\n');
  process.exitCode = 1;
}
'''


def execute_direct_behavior_oracle(
    spec: DirectBehaviorOracleSpec | dict[str, Any],
    workspace: str | os.PathLike,
    *,
    observable_contract: BehaviorObservableContract | dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = spec if isinstance(spec, dict) else {}
    checked = validate_direct_behavior_oracle_spec(value, observable_contract)
    if not checked["valid"]:
        return {
            "status": FAIL,
            "valid": False,
            "code": VERIFICATION_GAP_REMEDIATION_INVALID,
            "errors": checked["errors"],
            "model_calls": 0,
            "worker_calls": 0,
        }
    try:
        target = _safe_workspace_path(workspace, value["target_module_path"])
        controller = _safe_workspace_path(workspace, value["controller_module_path"])
    except VerificationGapRemediationError as exc:
        return {"status": FAIL, "valid": False, "code": exc.code, "errors": [str(exc)], "model_calls": 0, "worker_calls": 0}
    with tempfile.TemporaryDirectory(prefix="hivo_v25_4_direct_oracle_") as temp:
        temp_root = Path(temp)
        spec_path = temp_root / "oracle_spec.json"
        probe_path = temp_root / "oracle_probe.js"
        runtime_spec = {
            "workspace": str(Path(workspace).expanduser().resolve()),
            "target_module_path": _path(value["target_module_path"]),
            "target_symbol": value["target_symbol"],
            "controller_module_path": _path(value["controller_module_path"]),
            "controller_symbol": value["controller_symbol"],
            "state_query_symbol": value["state_query_symbol"],
            "toggle_symbol": value["toggle_symbol"],
            "running_expectation": _copy(value["running_expectation"]),
            "legacy_compatibility": _copy(value["legacy_compatibility"]),
        }
        spec_path.write_text(json.dumps(runtime_spec, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        probe_path.write_text(_probe_source(), encoding="utf-8")
        command = ["node", str(probe_path), str(spec_path)]
        try:
            completed = subprocess.run(
                command,
                cwd=str(Path(workspace).expanduser().resolve()),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=int(value.get("execution_spec", {}).get("timeout_seconds", 20)),
                check=False,
            )
            stdout = completed.stdout or ""
            stderr = completed.stderr or ""
            marker = "HIVO_ORACLE_RESULT:"
            payload = None
            for line in reversed(stdout.splitlines()):
                if line.startswith(marker):
                    try:
                        payload = json.loads(line[len(marker):])
                    except ValueError:
                        payload = None
                    break
            passed = bool(payload and payload.get("passed") is True and completed.returncode == 0)
            return {
                "status": PASS if passed else FAIL,
                "valid": passed,
                "oracle_id": value.get("oracle_id"),
                "oracle_hash": value.get("oracle_hash"),
                "command": command,
                "exit_code": completed.returncode,
                "stdout": stdout,
                "stderr": stderr,
                "checks": (payload or {}).get("checks", []),
                "error": (payload or {}).get("error"),
                "generated_probe_outside_workspace": True,
                "model_calls": 0,
                "worker_calls": 0,
            }
        except (OSError, subprocess.SubprocessError) as exc:
            return {
                "status": FAIL,
                "valid": False,
                "oracle_id": value.get("oracle_id"),
                "oracle_hash": value.get("oracle_hash"),
                "command": command,
                "exit_code": None,
                "stdout": "",
                "stderr": str(exc),
                "checks": [],
                "generated_probe_outside_workspace": True,
                "model_calls": 0,
                "worker_calls": 0,
            }


def build_direct_behavior_oracle_record(value: dict[str, Any]) -> dict[str, Any]:
    """Return the V25.3-compatible canonical verification record."""
    oracle = value.get("proposed_direct_oracle") if isinstance(value, dict) else {}
    contract = value.get("proposed_observable_contract") if isinstance(value, dict) else {}
    requirement_id = str(value.get("uncovered_obligation_id") or oracle.get("obligation_id") or "")
    return _new_verification_record(
        contract, oracle, requirement_id=requirement_id,
        node_id=str(value.get("node_id") or "NODE-002"),
        surface_id=str(value.get("surface_id") or ""),
    )


__all__ = [
    "BehaviorObservableContract", "DirectBehaviorOracleSpec",
    "VerificationGapRemediationProposal", "RevisedPlanApprovalSummary",
    "VerificationGapRemediationError",
    "SCHEMA_VERSION", "CONTRACT_SCHEMA_VERSION", "ORACLE_SCHEMA_VERSION",
    "APPROVAL_SUMMARY_SCHEMA_VERSION",
    "VERIFICATION_GAP_REMEDIATION_VALID", "VERIFICATION_GAP_REMEDIATION_INVALID",
    "VERIFICATION_OBLIGATION_UNCOVERED", "EXECUTION_VERIFICATION_READY",
    "PLAN_APPROVAL_REQUIRED", "OLD_APPROVAL_NOT_APPLICABLE_TO_REVISED_PLAN",
    "STAGE4_CONTRACTABILITY_PASS",
    "HIVO_VERIFIER", "ADDITIVE_EXPORT", "DIRECT", "FOCUSED_TEST", "BEHAVIOR_CHANGE",
    "PASS", "FAIL", "canonical_hash", "deterministic_hash",
    "behavior_observable_contract_hash", "direct_behavior_oracle_hash",
    "remediation_proposal_hash", "approval_summary_hash",
    "build_behavior_observable_contract",
    "validate_behavior_observable_contract", "build_direct_behavior_oracle_spec",
    "validate_direct_behavior_oracle_spec", "build_verification_gap_remediation_proposal",
    "validate_verification_gap_remediation_proposal",
    "revise_canonical_plan_from_verification_gap", "build_revised_verification_contracts",
    "build_revised_plan_approval_summary", "build_approval_summary",
    "compact_observable_contract", "compact_direct_behavior_oracle",
    "execute_direct_behavior_oracle", "build_direct_behavior_oracle_record",
]


build_approval_summary = build_revised_plan_approval_summary
