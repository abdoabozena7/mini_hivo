"""Experiment 8: bind a verified child handoff to its existing evidence."""

import copy
import json
import os
from pathlib import Path
import tempfile

from hivo.integration_gate import canonical_hash, create_verified_child_receipt
from hivo.integration_gate import validate_verified_child_receipt
from hivo.integration_gate import _artifact_from_inputs, _aggregation_from_inputs
from hivo.integration_gate import fingerprint_dependency_paths
from hivo.verification_routing import requires_execution_verification_closure
from hivo import evidence_compatibility as semantic_evidence


def create_atomic_child_receipt(task, result, *, verification_aggregation=None,
                                verification_applicability=None, **kwargs):
    artifact = _artifact_from_inputs(task, result, verification_applicability)
    aggregation = copy.deepcopy(_aggregation_from_inputs(result, verification_aggregation))
    # A required-set inventory is not itself an executed closure. Legacy
    # syntax/browser routes have no authority-bound closure to supply.
    inventory = aggregation.get("required_execution_verification_set") or {}
    legacy_inventory = all(
        str(route.get("authority_id", "")).startswith("UNRESOLVED-ROUTE-")
        and not route.get("authority_type") and not route.get("oracle_id")
        for route in inventory.get("routes", []) if isinstance(route, dict)
    )
    if (legacy_inventory and not requires_execution_verification_closure(artifact)
            and not requires_execution_verification_closure(aggregation)
            and not isinstance(aggregation.get("execution_verification_closure"), dict)):
        aggregation.pop("required_execution_verification_set", None)
    semantic = aggregation.get("semantic_browser_evidence")
    if semantic is not None:
        evidence = list(kwargs.get("verification_evidence") or result.get("verification_evidence") or [])
        for assessment in semantic.values():
            evidence.extend({"tool": r["provenance"]["tool"], "target": r["target"], "result": {
                "passed": r["result"] == "PASS", "canonical_record_hash": r["record_hash"],
                "requirement_id": r["requirement_id"], "obligation_id": r["obligation_id"]}}
                for r in assessment["canonical_evidence_records"])
        kwargs["verification_evidence"] = evidence
    receipt = create_verified_child_receipt(
        task, result, verification_aggregation=aggregation,
        verification_applicability=verification_applicability, **kwargs,
    )
    contract = task.get("execution_contract") if isinstance(task.get("execution_contract"), dict) else {}
    receipt["covered_node_ids"] = list(
        (receipt.get("coverage") or {}).get("owned_plan_node_ids")
        or (receipt.get("coverage") or {}).get("plan_node_ids") or []
    )
    receipt["requirement_ids"] = list(
        contract.get("requirement_ids") or task.get("plan_requirement_ids") or []
    )
    receipt["verification_evidence_hash"] = canonical_hash(receipt.get("verification_evidence", []))
    receipt["subject_after_hash"] = receipt.get("verified_subject_state_hash")
    receipt["contract_hash"] = (receipt.get("authority") or {}).get("execution_contract_hash")
    if semantic is not None:
        receipt["semantic_browser_evidence"] = copy.deepcopy(semantic)
        receipt["semantic_requirements"] = copy.deepcopy(contract.get("requirements", []))
        receipt["semantic_evidence_hash"] = canonical_hash(semantic)
    receipt["receipt_hash"] = canonical_hash({
        key: value for key, value in receipt.items() if key != "receipt_hash"
    })
    return receipt


def validate_atomic_child_receipt(receipt, *, workspace=None, expected_contract_hash=None,
                                  expected_node_ids=None, expected_requirement_ids=None,
                                  expected_requirements=None):
    checked = validate_verified_child_receipt(receipt, workspace=workspace)
    value = receipt if isinstance(receipt, dict) else {}
    errors = list(checked.get("errors", []))
    if value.get("verified") is not True:
        errors.append("child verification did not produce a verified receipt")
    if not value.get("child_id"):
        errors.append("missing child id")
    if not value.get("covered_node_ids") or value.get("covered_node_ids") != list(
        (value.get("coverage") or {}).get("owned_plan_node_ids")
        or (value.get("coverage") or {}).get("plan_node_ids") or []
    ):
        errors.append("covered node ids do not match receipt coverage")
    if not value.get("requirement_ids"):
        errors.append("missing requirement ids")
    if value.get("verification_evidence_hash") != canonical_hash(value.get("verification_evidence", [])):
        errors.append("verification evidence hash mismatch")
    if not value.get("verification_evidence"):
        errors.append("missing verification evidence")
    if not value.get("subject_after_hash") or value.get("subject_after_hash") != value.get("verified_subject_state_hash"):
        errors.append("subject after hash mismatch")
    if not value.get("contract_hash") or value.get("contract_hash") != (value.get("authority") or {}).get("execution_contract_hash"):
        errors.append("contract hash mismatch")
    if expected_contract_hash and value.get("contract_hash") != expected_contract_hash:
        errors.append("receipt contract differs from approved child contract")
    if expected_node_ids and not set(expected_node_ids).issubset(value.get("covered_node_ids") or []):
        errors.append("approved node coverage missing")
    if expected_requirement_ids and not set(expected_requirement_ids).issubset(value.get("requirement_ids") or []):
        errors.append("approved requirement coverage missing")
    if "semantic_browser_evidence" in value:
        semantic = value["semantic_browser_evidence"]
        requirements = expected_requirements if expected_requirements is not None else value.get("semantic_requirements", [])
        if value.get("semantic_evidence_hash") != canonical_hash(semantic) or not semantic:
            errors.append("semantic evidence hash or inventory is invalid")
        browser_targets = {r.get("target") for r in value.get("verification_routes", []) if r.get("kind") == "BROWSER"}
        for target, assessment in semantic.items():
            records = assessment.get("canonical_evidence_records", [])
            claims = assessment.get("required_claims", [])
            if target not in browser_targets or not claims or not records:
                errors.append("semantic browser target has no bound claims/evidence")
                continue
            subject = fingerprint_dependency_paths(workspace, claims[0]["subject_paths"])
            expected_claims = semantic_evidence.required_claims(
                requirements, contract_hash=value.get("contract_hash"), child_id=value.get("child_id"), target=target,
                subject_hash=subject["hash"], subject_paths=[p["path"] for p in subject["paths"]],
            )
            if claims != expected_claims:
                errors.append("semantic claim identity differs from approved requirements/current subject")
            checked_semantic = semantic_evidence.assess(expected_claims, records, required_requirement_ids=value.get("requirement_ids", []))
            if checked_semantic["status"] != "PASS" or assessment.get("status") != "PASS":
                errors.append("semantic evidence does not cover every required assertion")
    return {"valid": not errors, "verified": not errors, "errors": errors,
            "fresh": checked.get("fresh")}


def persist_atomic_child_receipt(receipt, workspace):
    checked = validate_atomic_child_receipt(receipt, workspace=workspace)
    if not checked["valid"]:
        raise ValueError("invalid verified child receipt: " + "; ".join(checked["errors"]))
    directory = Path(workspace) / ".agent_evidence" / "verified_child_receipts"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / (receipt["receipt_hash"] + ".json")
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=directory,
                                     suffix=".tmp", delete=False) as stream:
        temporary = Path(stream.name)
        json.dump(receipt, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    return str(destination)
