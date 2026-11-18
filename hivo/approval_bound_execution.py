"""Deterministic Stage 6C-B execution lifecycle glue.

This module deliberately does not own a Worker loop, a verifier, or a memory
promotion implementation.  It validates the immutable V25 authority proof,
captures the execution subject, dispatches through the existing Worker
entrypoint supplied by ``mini.py``, and hands evidence to the existing Stage
5 routing boundaries.
"""

from __future__ import annotations

import copy
import hashlib
import inspect
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable

from hivo import approval_authority as stage6c
from hivo import execution_contracts as stage4
from hivo import execution_invariants as stage6c_invariants
from hivo import impact_planning as stage3
from hivo import integration_gate
from hivo import verification_obligation_coverage as verification_coverage
from hivo import verification_routing


SCHEMA_VERSION = "6C-B"

# Healthy lifecycle states.  ``status`` remains the ordinary orchestration
# status (done/failed); these labels are the auditable terminal/state-machine
# facts and are never collapsed into Worker DONE.
APPROVAL_BOUND_EXECUTION_STARTED = "APPROVAL_BOUND_EXECUTION_STARTED"
WORKER_EXECUTION_COMPLETED = "WORKER_EXECUTION_COMPLETED"
MUTATION_SCOPE_VALIDATED = "MUTATION_SCOPE_VALIDATED"
VERIFICATION_PASSED = "VERIFICATION_PASSED"
INTEGRATION_VERIFIED = "INTEGRATION_VERIFIED"
VERIFIED_STATE_PROMOTED = "VERIFIED_STATE_PROMOTED"
APPROVED_EXECUTION_VERIFIED_AND_PROMOTED = "APPROVED_EXECUTION_VERIFIED_AND_PROMOTED"
POST_PROMOTION_REENTRY_READY = "POST_PROMOTION_REENTRY_READY"

# Fail-closed lifecycle states.
WORKER_AUTHORIZATION_INVALID = "WORKER_AUTHORIZATION_INVALID"
WORKER_OUTPUT_INVALID = "WORKER_OUTPUT_INVALID"
WORKER_NO_APPROVED_MUTATION = "WORKER_NO_APPROVED_MUTATION"
UNAUTHORIZED_MUTATION = "UNAUTHORIZED_MUTATION"
DNT_VIOLATION = "DNT_VIOLATION"
VERIFICATION_FAILED = "VERIFICATION_FAILED"
INTEGRATION_FAILED = "INTEGRATION_FAILED"
PROMOTION_PRECONDITION_FAILED = "PROMOTION_PRECONDITION_FAILED"
PROMOTION_FAILED = "PROMOTION_FAILED"
POST_PROMOTION_REENTRY_FAILED = "POST_PROMOTION_REENTRY_FAILED"


_IGNORED_DIRECTORIES = frozenset({
    ".git", ".hivo", ".agent_runs", ".agent_backups", ".codex",
    "node_modules", "__pycache__", ".pytest_cache",
})
_PATH_RE = re.compile(
    r"(?<![A-Za-z0-9_])(?:[A-Za-z0-9_.-]+[\\/])+[A-Za-z0-9_.-]+\.(?:js|mjs|cjs|ts|tsx|py|json|html|htm|css)",
    re.IGNORECASE,
)


def _copy(value: Any) -> Any:
    return copy.deepcopy(value)


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _path(value: Any) -> str:
    text = str(value or "").replace("\\", "/")
    while text.startswith("./"):
        text = text[2:]
    return text.lstrip("/")


def _unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = _path(value)
        key = item.casefold()
        if not item or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _without(value: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {key: _copy(item) for key, item in value.items() if key not in keys}


def _root(workspace: str | os.PathLike | None) -> Path | None:
    if workspace is None:
        return None
    try:
        candidate = Path(workspace).expanduser().resolve()
    except (OSError, RuntimeError, TypeError, ValueError):
        return None
    return candidate if candidate.is_dir() else None


def _relative(root: Path, candidate: Path) -> str | None:
    try:
        return candidate.resolve().relative_to(root).as_posix()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_ignored(path: Path, root: Path) -> bool:
    relative = _relative(root, path)
    if not relative:
        return True
    parts = set(Path(relative).parts)
    return bool(parts.intersection(_IGNORED_DIRECTORIES)) or any(
        part.startswith(".agent_") for part in Path(relative).parts
    )


def _file_state(root: Path, relative: str) -> dict[str, Any]:
    target = root / relative
    state: dict[str, Any] = {
        "path": relative,
        "exists": False,
        "sha256": None,
        "size": 0,
    }
    try:
        if not target.is_file():
            return state
        data = target.read_bytes()
    except OSError:
        return state
    state.update({
        "exists": True,
        "sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    })
    return state


def enumerate_execution_subject(workspace: str | os.PathLike | None) -> dict[str, Any]:
    """Return a deterministic file manifest for the supplied execution root."""
    root = _root(workspace)
    records: list[dict[str, Any]] = []
    if root is not None:
        try:
            for current, dirs, names in os.walk(root):
                current_path = Path(current)
                dirs[:] = sorted(
                    name for name in dirs
                    if name not in _IGNORED_DIRECTORIES and not name.startswith(".agent_")
                )
                for name in sorted(names):
                    candidate = current_path / name
                    if _is_ignored(candidate, root):
                        continue
                    relative = _relative(root, candidate)
                    if relative:
                        records.append(_file_state(root, relative))
        except OSError:
            records = []
    records.sort(key=lambda item: str(item.get("path", "")).casefold())
    payload = {"schema_version": SCHEMA_VERSION, "paths": records}
    return {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "EXECUTION_SUBJECT_MANIFEST",
        "workspace": str(root) if root is not None else None,
        "paths": records,
        "hash": stage6c.canonical_hash(payload),
    }


execution_subject_manifest = enumerate_execution_subject


def _record_map(manifest: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    return {
        str(item.get("path")): item
        for item in (manifest or {}).get("paths", []) or []
        if isinstance(item, dict) and item.get("path")
    }


def diff_execution_subject(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> dict[str, Any]:
    """Compare complete before/after manifests, including create/delete."""
    before_map = _record_map(before)
    after_map = _record_map(after)
    changed: list[str] = []
    created: list[str] = []
    deleted: list[str] = []
    for relative in sorted(set(before_map) | set(after_map), key=str.casefold):
        left = before_map.get(relative, {"path": relative, "exists": False, "sha256": None, "size": 0})
        right = after_map.get(relative, {"path": relative, "exists": False, "sha256": None, "size": 0})
        if left == right:
            continue
        changed.append(relative)
        if not left.get("exists") and right.get("exists"):
            created.append(relative)
        elif left.get("exists") and not right.get("exists"):
            deleted.append(relative)

    by_hash_before: dict[str, list[str]] = {}
    by_hash_after: dict[str, list[str]] = {}
    for item in before_map.values():
        if item.get("exists") and item.get("sha256"):
            by_hash_before.setdefault(str(item["sha256"]), []).append(str(item["path"]))
    for item in after_map.values():
        if item.get("exists") and item.get("sha256"):
            by_hash_after.setdefault(str(item["sha256"]), []).append(str(item["path"]))
    renamed: list[dict[str, str]] = []
    for digest in sorted(set(by_hash_before) & set(by_hash_after)):
        removed = sorted(set(by_hash_before[digest]) & set(deleted), key=str.casefold)
        added = sorted(set(by_hash_after[digest]) & set(created), key=str.casefold)
        for old, new in zip(removed, added):
            renamed.append({"from": old, "to": new, "sha256": digest})
    return {
        "before_hash": (before or {}).get("hash"),
        "after_hash": (after or {}).get("hash"),
        "changed_paths": changed,
        "created_paths": created,
        "deleted_paths": deleted,
        "renamed_paths": renamed,
        "changed": bool(changed),
    }


subject_diff = diff_execution_subject


def _subject_paths(
    contract: dict[str, Any],
    authorization: dict[str, Any] | None = None,
    extra_paths: Iterable[Any] | None = None,
) -> list[str]:
    values: list[Any] = list(extra_paths or [])
    values.extend(contract.get("allowed_inspection_paths", []) or [])
    values.extend(contract.get("allowed_mutation_paths", []) or [])
    auth = authorization if isinstance(authorization, dict) else {}
    scope = auth.get("approved_mutation_scope") if isinstance(auth.get("approved_mutation_scope"), dict) else {}
    dnt = auth.get("approved_dnt") if isinstance(auth.get("approved_dnt"), dict) else {}
    values.extend(scope.get("paths", []) or [])
    values.extend(dnt.get("paths", []) or [])
    return sorted(_unique(values), key=str.casefold)


def _workspace_identity(workspace: str | os.PathLike | None, subject_paths: Iterable[Any]) -> dict[str, Any]:
    root = _root(workspace)
    path = str(root) if root is not None else None
    paths = sorted(_unique(subject_paths), key=str.casefold)
    return {
        "path": path,
        "path_hash": stage6c.canonical_hash(path or ""),
        "subject_paths": paths,
        "subject_paths_hash": stage6c.canonical_hash(paths),
    }


def create_execution_start_receipt(
    authorization: dict[str, Any],
    receipt: dict[str, Any],
    plan: dict[str, Any],
    execution_contract: dict[str, Any],
    *,
    pre_subject_hash: str,
    pre_brain_hash: str,
    workspace: str | os.PathLike,
    subject_paths: Iterable[Any] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the one immutable-in-content proof for a Worker start."""
    auth = authorization if isinstance(authorization, dict) else {}
    approval = receipt if isinstance(receipt, dict) else {}
    contract = execution_contract if isinstance(execution_contract, dict) else {}
    paths = sorted(_unique(subject_paths or _subject_paths(contract, auth)), key=str.casefold)
    value: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "artifact_type": "APPROVAL_BOUND_EXECUTION_RECEIPT",
        "status": APPROVAL_BOUND_EXECUTION_STARTED,
        "execution_start_id": "",
        "authorization_hash": auth.get("authorization_hash"),
        "approval_receipt_hash": approval.get("receipt_hash"),
        "canonical_plan_id": auth.get("canonical_plan_id") or plan.get("plan_id"),
        "canonical_plan_hash": auth.get("canonical_plan_hash") or plan.get("plan_hash"),
        "execution_contract_id": contract.get("execution_contract_id"),
        "execution_contract_hash": contract.get("contract_hash"),
        "stage4_contract_hash": contract.get("contract_hash"),
        "pre_worker_subject_hash": str(pre_subject_hash or ""),
        "pre_subject_hash": str(pre_subject_hash or ""),
        "pre_worker_brain_hash": str(pre_brain_hash or ""),
        "pre_brain_hash": str(pre_brain_hash or ""),
        "authorized_mutation_scope": _copy(
            auth.get("approved_mutation_scope")
            if isinstance(auth.get("approved_mutation_scope"), dict)
            else {
                "paths": contract.get("allowed_mutation_paths", []) or [],
                "surface_ids": contract.get("allowed_mutation_surface_ids", []) or [],
            }
        ),
        "mutation_scope_digest": auth.get("mutation_scope_digest"),
        "dnt_digest": auth.get("dnt_digest"),
        "verification_digest": auth.get("verification_digest"),
        "dependency_digest": auth.get("dependency_digest"),
        "interface_binding_digest": auth.get("interface_binding_digest"),
        "workspace_identity": _workspace_identity(workspace, paths),
        "subject_paths": paths,
        "receipt_hash": "",
    }
    if isinstance(verification_obligation_coverage, dict):
        value.update({
            "verification_obligation_coverage_hash": verification_obligation_coverage.get("coverage_hash"),
            "verification_obligation_coverage_status": (
                verification_obligation_coverage.get("coverage_status")
                or verification_obligation_coverage.get("status")
            ),
            "verification_obligation_coverage_ready": (
                verification_obligation_coverage.get("verification_ready") is True
            ),
            "verification_obligation_uncovered_ids": [
                str(item) for item in verification_obligation_coverage.get(
                    "uncovered_obligation_ids", []
                ) or []
            ],
        })
    identity_hash = stage6c.canonical_hash(_without(value, "execution_start_id", "receipt_hash"))
    value["execution_start_id"] = "START-" + identity_hash[:24].upper()
    value["receipt_hash"] = stage6c.canonical_hash(_without(value, "receipt_hash"))
    return value


create_approved_execution_start = create_execution_start_receipt
create_approval_bound_execution_receipt = create_execution_start_receipt


def validate_execution_start_receipt(
    receipt: dict[str, Any] | None,
    *,
    authorization: dict[str, Any] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = receipt if isinstance(receipt, dict) else {}
    errors: list[str] = []
    if value.get("schema_version") != SCHEMA_VERSION:
        errors.append("execution-start receipt schema version is invalid")
    if value.get("artifact_type") != "APPROVAL_BOUND_EXECUTION_RECEIPT":
        errors.append("execution-start receipt artifact type is invalid")
    if value.get("status") != APPROVAL_BOUND_EXECUTION_STARTED:
        errors.append("execution-start receipt status is invalid")
    if not value.get("receipt_hash") or value.get("receipt_hash") != stage6c.canonical_hash(_without(value, "receipt_hash")):
        errors.append("execution-start receipt hash is invalid")
    auth = authorization if isinstance(authorization, dict) else {}
    coverage_bound = bool(auth.get("verification_obligation_coverage_hash"))
    if coverage_bound and verification_obligation_coverage is None:
        errors.append("execution-start receipt requires the exact verification-obligation coverage artifact")
    if verification_obligation_coverage is not None:
        coverage_check = verification_coverage.validate_verification_obligation_coverage(
            verification_obligation_coverage,
        )
        if not coverage_check.get("valid"):
            errors.extend(str(item) for item in coverage_check.get("errors", [])[:10])
        expected = {
            "verification_obligation_coverage_hash": verification_obligation_coverage.get("coverage_hash"),
            "verification_obligation_coverage_status": (
                verification_obligation_coverage.get("coverage_status")
                or verification_obligation_coverage.get("status")
            ),
            "verification_obligation_coverage_ready": (
                verification_obligation_coverage.get("verification_ready") is True
            ),
            "verification_obligation_uncovered_ids": [
                str(item) for item in verification_obligation_coverage.get(
                    "uncovered_obligation_ids", []
                ) or []
            ],
        }
        for field, expected_value in expected.items():
            if value.get(field) != expected_value:
                errors.append(f"execution-start receipt coverage binding is invalid: {field}")
        if coverage_bound and value.get("verification_obligation_coverage_hash") != auth.get(
            "verification_obligation_coverage_hash"
        ):
            errors.append("execution-start receipt coverage hash does not match authorization")
    elif any(
        value.get(field) not in (None, "", [], {})
        for field in (
            "verification_obligation_coverage_hash",
            "verification_obligation_coverage_status",
            "verification_obligation_coverage_ready",
            "verification_obligation_uncovered_ids",
        )
    ):
        errors.append("execution-start receipt contains coverage binding without the exact artifact")
    return {"valid": not errors, "errors": errors[:20], "receipt_hash": value.get("receipt_hash")}


def _binding_state(
    current_state: dict[str, Any] | None,
    *,
    current_subject_hash: str | None = None,
    current_brain_hash: str | None = None,
) -> tuple[dict[str, Any], bool]:
    state = _copy(current_state) if isinstance(current_state, dict) else {}
    direct = isinstance(state.get("authority_binding"), dict) and not any(
        key in state for key in ("verified_planning_context", "planning_context_hash", "upstream_bindings")
    )
    # Fill only an absent field for the revalidation projection.  Never replace
    # a caller-supplied current binding: doing so would turn stale state into a
    # false positive before the explicit approved-vs-observed checks below.
    if current_subject_hash:
        if direct:
            state["authority_binding"].setdefault("subject_aggregate_hash", current_subject_hash)
        else:
            state.setdefault("subject_aggregate_hash", current_subject_hash)
    if current_brain_hash:
        if direct:
            state["authority_binding"].setdefault("brain_hash", current_brain_hash)
        else:
            state.setdefault("brain_hash", current_brain_hash)
    return state, direct


def _brain_hash(
    store: Any,
    project_id: str | None,
    current_state: dict[str, Any] | None,
) -> str | None:
    # An explicit working Brain is an authority input, not an optional hint.
    # Do not fall back to a caller-supplied state projection when a store was
    # supplied but cannot report its durable hash; that would let stale Brain
    # state pass the last-moment gate.
    if store is not None:
        reader = getattr(store, "project_brain_hash", None)
        if not callable(reader):
            return None
        try:
            value = reader(str(project_id or "default"))
            return str(value) if value not in (None, "") else None
        except Exception:
            return None
    if isinstance(current_state, dict):
        if current_state.get("brain_hash"):
            return str(current_state["brain_hash"])
        binding = current_state.get("authority_binding")
        if isinstance(binding, dict) and binding.get("brain_hash"):
            return str(binding["brain_hash"])
    return None


def _project_id(
    authorization: dict[str, Any],
    current_state: dict[str, Any] | None,
    contract: dict[str, Any],
) -> str:
    source = authorization.get("source_bindings") if isinstance(authorization.get("source_bindings"), dict) else {}
    state = current_state if isinstance(current_state, dict) else {}
    return str(
        contract.get("project_id")
        or state.get("project_id")
        or source.get("project_id")
        or "default"
    )


def _authorization_binding_errors(
    authorization: dict[str, Any],
    receipt: dict[str, Any],
    current_binding: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Reject a self-consistent authorization that no longer matches its proof."""
    errors: list[dict[str, Any]] = []
    receipt_fields = (
        ("canonical_plan_id", "canonical_plan_id"),
        ("canonical_plan_hash", "canonical_plan_hash"),
        ("approval_receipt_hash", "receipt_hash"),
        ("current_subject_hash", "approved_subject_aggregate_hash"),
        ("current_brain_hash", "approved_brain_hash"),
        ("planning_context_hash", "approved_planning_context_hash"),
        ("mutation_scope_digest", "approved_mutation_scope_digest"),
        ("dnt_digest", "approved_dnt_digest"),
        ("dependency_digest", "approved_dependency_digest"),
        ("verification_digest", "approved_verification_digest"),
        ("interface_binding_digest", "approved_interface_binding_digest"),
        ("requirement_coverage_digest", "approved_requirement_coverage_digest"),
        ("challenger_reconciliation_hash", "approved_challenger_reconciliation_hash"),
        ("task_id", "approved_task_id"),
        ("requirement_ids", "approved_requirement_ids"),
        ("source_bindings", "approved_source_bindings"),
        ("authority_constraints_digest", "approved_authority_constraints_digest"),
    )
    for auth_field, receipt_field in receipt_fields:
        if authorization.get(auth_field) != receipt.get(receipt_field):
            errors.append({
                "code": stage6c.APPROVAL_RECEIPT_INVALID,
                "field": auth_field,
                "details": "authorization does not match immutable approval receipt",
            })

    if not isinstance(current_binding, dict) or not current_binding:
        return errors
    current_fields = (
        ("canonical_plan_id", "canonical_plan_id"),
        ("canonical_plan_hash", "canonical_plan_hash"),
        ("task_id", "task_id"),
        ("requirement_ids", "requirement_ids"),
        ("planning_context_hash", "planning_context_hash"),
        ("current_subject_hash", "subject_aggregate_hash"),
        ("current_brain_hash", "brain_hash"),
        ("mutation_scope_digest", "mutation_scope_digest"),
        ("dnt_digest", "dnt_digest"),
        ("dependency_digest", "dependency_digest"),
        ("verification_digest", "verification_contract_digest"),
        ("interface_binding_digest", "interface_binding_digest"),
        ("requirement_coverage_digest", "requirement_coverage_digest"),
        ("challenger_reconciliation_hash", "challenger_reconciliation_hash"),
        ("source_bindings", "source_bindings"),
        ("authority_constraints_digest", "authority_constraints_digest"),
        ("approved_mutation_scope", "mutation_scope"),
        ("approved_dnt", "dnt"),
        ("approved_dependencies", "dependencies"),
        ("approved_verification_contracts", "verification_contracts"),
        ("approved_interface_binding", "interface_binding"),
    )
    for auth_field, current_field in current_fields:
        if authorization.get(auth_field) != current_binding.get(current_field):
            errors.append({
                "code": stage6c.EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH,
                "field": auth_field,
                "details": "authorization does not match the current approved binding",
            })
    return errors


def last_moment_authorization_audit(
    *,
    authorization: dict[str, Any] | None,
    receipt: dict[str, Any] | None,
    revalidation: dict[str, Any] | None,
    request: dict[str, Any] | None,
    plan: dict[str, Any] | None,
    current_state: dict[str, Any] | None,
    contracts: Iterable[dict[str, Any]] | None,
    graph: dict[str, Any] | None,
    contract: dict[str, Any],
    workspace: str | os.PathLike | None,
    store: Any = None,
    project_id: str | None = None,
    expected_start_receipt: dict[str, Any] | None = None,
    subject_paths: Iterable[Any] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Repeat the full V25 proof immediately before Worker dispatch."""
    auth = authorization if isinstance(authorization, dict) else {}
    approval = receipt if isinstance(receipt, dict) else {}
    plan_value = plan if isinstance(plan, dict) else {}
    execution_contract = contract if isinstance(contract, dict) else {}
    paths = sorted(_unique(subject_paths or _subject_paths(execution_contract, auth)), key=str.casefold)
    subject_fingerprint = integration_gate.fingerprint_dependency_paths(workspace, paths)
    actual_subject_hash = subject_fingerprint.get("hash")
    actual_brain_hash = _brain_hash(store, project_id, current_state)
    state, direct_binding = _binding_state(
        current_state,
        current_subject_hash=actual_subject_hash,
        current_brain_hash=actual_brain_hash,
    )
    errors: list[dict[str, Any]] = []
    auth_check = stage6c.validate_approved_execution_authorization(
        auth, approval, revalidation, request=request,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    if not auth_check.get("valid"):
        errors.extend(auth_check.get("errors", []))

    # Revalidation proves the supplied state object.  The execution boundary
    # also observes the actual subject and working Brain at this instant; a
    # caller cannot make either one current merely by replaying an old state
    # projection.
    approved_subject_hash = str(auth.get("current_subject_hash") or "")
    if not actual_subject_hash or not approved_subject_hash or str(actual_subject_hash) != approved_subject_hash:
        errors.append({
            "code": stage6c.APPROVAL_SUBJECT_STALE,
            "field": "current_subject_hash",
            "approved": approved_subject_hash,
            "current": actual_subject_hash,
        })
    approved_brain_hash = str(auth.get("current_brain_hash") or "")
    if not actual_brain_hash or not approved_brain_hash or str(actual_brain_hash) != approved_brain_hash:
        errors.append({
            "code": stage6c.APPROVAL_BRAIN_STALE,
            "field": "current_brain_hash",
            "approved": approved_brain_hash,
            "current": actual_brain_hash,
        })

    computed_plan_hash = ""
    try:
        computed_plan_hash = str(stage3.plan_content_hash(plan_value))
    except Exception:
        computed_plan_hash = ""
    if not computed_plan_hash or computed_plan_hash != str(auth.get("canonical_plan_hash") or ""):
        errors.append({
            "code": stage6c.APPROVAL_PLAN_HASH_MISMATCH,
            "field": "current_plan_hash",
            "approved": auth.get("canonical_plan_hash"),
            "current": computed_plan_hash,
        })
    if execution_contract.get("contract_hash") is None:
        errors.append({
            "code": stage6c.EXECUTION_CONTRACT_APPROVAL_BINDING_MISMATCH,
            "field": "contract_hash",
        })

    fresh_revalidation: dict[str, Any] | None = None
    if isinstance(current_state, dict):
        # A full state is required for a fresh binding.  The direct binding
        # form is deliberately supported for isolated negative fixtures.
        fresh_revalidation = stage6c.pre_execution_approval_revalidation(
            approval,
            None if direct_binding else plan_value,
            state,
            request=request,
        )
        if not fresh_revalidation.get("valid"):
            errors.extend(fresh_revalidation.get("mismatches", []))
    elif not isinstance(revalidation, dict) or revalidation.get("valid") is not True:
        errors.append({
            "code": stage6c.REAPPROVAL_REQUIRED,
            "field": "revalidation",
        })
    else:
        fresh_revalidation = _copy(revalidation)

    contract_check = stage6c.validate_approval_bound_contracts(
        list(contracts or [execution_contract]),
        auth,
        plan=plan_value,
        graph=graph,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    if not contract_check.get("valid"):
        errors.extend(contract_check.get("errors", []))
    approved_verification_records = auth.get("approved_verification_contracts")
    if isinstance(approved_verification_records, list):
        approved_verification_texts = {
            _text(text)
            for item in approved_verification_records
            if isinstance(item, dict)
            for text in (item.get("contract", []) or [])
            if _text(text)
        }
        actual_verification_texts = {
            _text(text)
            for text in (execution_contract.get("test_contract", []) or [])
            if _text(text)
        }
        unexpected_verification_texts = sorted(
            actual_verification_texts - approved_verification_texts,
            key=str.casefold,
        )
        if unexpected_verification_texts:
            errors.append({
                "code": stage6c.APPROVAL_VERIFICATION_MISMATCH,
                "field": "contract.test_contract",
                "unexpected": unexpected_verification_texts[:20],
            })

    current_binding = (
        fresh_revalidation.get("current_binding")
        if isinstance(fresh_revalidation, dict)
        and isinstance(fresh_revalidation.get("current_binding"), dict)
        else None
    )
    errors.extend(_authorization_binding_errors(auth, approval, current_binding))

    if expected_start_receipt is not None:
        start_check = validate_execution_start_receipt(
            expected_start_receipt,
            authorization=auth,
            verification_obligation_coverage=verification_obligation_coverage,
        )
        if not start_check.get("valid"):
            errors.extend({"code": "EXECUTION_START_RECEIPT_INVALID", "field": item} for item in start_check.get("errors", []))
        else:
            expected = {
                "authorization_hash": auth.get("authorization_hash"),
                "approval_receipt_hash": approval.get("receipt_hash"),
                "canonical_plan_hash": auth.get("canonical_plan_hash"),
                "execution_contract_hash": execution_contract.get("contract_hash"),
                "pre_worker_subject_hash": expected_start_receipt.get("pre_worker_subject_hash"),
                "pre_worker_brain_hash": expected_start_receipt.get("pre_worker_brain_hash"),
            }
            for field, value in expected.items():
                if expected_start_receipt.get(field) != value:
                    errors.append({"code": "EXECUTION_START_RECEIPT_BINDING_MISMATCH", "field": field})
            if expected_start_receipt.get("pre_worker_subject_hash") != actual_subject_hash:
                errors.append({
                    "code": stage6c.APPROVAL_SUBJECT_STALE,
                    "field": "pre_worker_subject_hash",
                    "approved": expected_start_receipt.get("pre_worker_subject_hash"),
                    "current": actual_subject_hash,
                })
            if actual_brain_hash is not None and expected_start_receipt.get("pre_worker_brain_hash") != actual_brain_hash:
                errors.append({
                    "code": stage6c.APPROVAL_BRAIN_STALE,
                    "field": "pre_worker_brain_hash",
                    "approved": expected_start_receipt.get("pre_worker_brain_hash"),
                    "current": actual_brain_hash,
                })

    state_drift_codes = {
        stage6c.REAPPROVAL_REQUIRED,
        stage6c.APPROVAL_SUBJECT_STALE,
        stage6c.APPROVAL_BRAIN_STALE,
        stage6c.APPROVAL_PLANNING_CONTEXT_MISMATCH,
        stage6c.APPROVAL_SOURCE_BINDING_MISMATCH,
        stage6c.APPROVAL_FRESHNESS_MISMATCH,
        stage6c.APPROVAL_RECONCILIATION_MISMATCH,
        stage6c.APPROVAL_TASK_MISMATCH,
        stage6c.APPROVAL_REQUIREMENT_MISMATCH,
    }
    has_state_drift = any(str(item.get("code")) in state_drift_codes for item in errors if isinstance(item, dict))
    if has_state_drift:
        status = stage6c.REAPPROVAL_REQUIRED
        code = stage6c.REAPPROVAL_REQUIRED
    elif errors:
        status = WORKER_AUTHORIZATION_INVALID
        code = str(errors[0].get("code") or WORKER_AUTHORIZATION_INVALID)
    else:
        status = stage6c.EXECUTION_AUTHORIZATION_READY
        code = None
    return {
        "allowed": not errors,
        "valid": not errors,
        "status": status,
        "terminal_state": status,
        "code": code,
        "errors": errors[:60],
        "authorization": _copy(auth),
        "authorization_validation": auth_check,
        "fresh_revalidation": _copy(fresh_revalidation),
        "contract_validation": contract_check,
        "subject_fingerprint": subject_fingerprint,
        "current_subject_hash": actual_subject_hash,
        "current_brain_hash": actual_brain_hash,
        "subject_paths": paths,
        "project_id": _project_id(auth, current_state, execution_contract),
    }


pre_worker_authorization_audit = last_moment_authorization_audit
validate_last_moment_authorization = last_moment_authorization_audit


def invoke_callback(callback: Callable[..., Any], **available: Any) -> Any:
    """Call a small injected seam without adding a model/provider framework."""
    if not callable(callback):
        raise TypeError("callback must be callable")
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return callback(available.get("worker_context"), available.get("execution_contract"))
    parameters = list(signature.parameters.values())
    if any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters):
        return callback(**available)
    accepted = {
        item.name: available[item.name]
        for item in parameters
        if item.name in available
        and item.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
    }
    if accepted or not parameters:
        missing_required = [
            item for item in parameters
            if item.default is inspect.Parameter.empty
            and item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
            and item.name not in accepted
        ]
        if not missing_required:
            return callback(**accepted)
    positional_values = [
        available.get("worker_context"),
        available.get("execution_contract"),
        available.get("execute_tool"),
    ]
    positional = []
    for item, value in zip(
        [item for item in parameters if item.kind in {inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD}],
        positional_values,
    ):
        positional.append(value)
    return callback(*positional)


def _verification_contract_records(
    authorization: dict[str, Any],
    contract: dict[str, Any],
) -> list[dict[str, Any]]:
    raw = authorization.get("approved_verification_contracts")
    if not isinstance(raw, list) or not raw:
        raw = [{"verification_id": "VERIFICATION-LOCAL", "contract": list(contract.get("test_contract", []) or [])}]
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(raw, 1):
        if isinstance(item, dict):
            texts = item.get("contract")
            if isinstance(texts, str):
                texts = [texts]
            texts = [str(value) for value in (texts or []) if _text(value)]
            verification_id = str(item.get("verification_id") or f"VERIFICATION-{index:03d}")
            # Preserve the complete approved authority card.  The previous
            # adapter projected only ``verification_id`` and ``contract``,
            # which discarded the direct oracle target/spec before routing.
            record = _copy(item)
        else:
            texts = [str(item)] if _text(item) else []
            verification_id = f"VERIFICATION-{index:03d}"
            record = {}
        identity = stage6c.canonical_hash({"verification_id": verification_id, "contract": texts})
        if identity in seen or not texts:
            continue
        seen.add(identity)
        record["verification_id"] = verification_id
        record["contract"] = texts
        records.append(record)
    return records


def _known_test_files(workspace: str | os.PathLike | None, paths: Iterable[Any]) -> list[str]:
    root = _root(workspace)
    values = _unique(paths)
    if root is not None:
        try:
            for current, dirs, names in os.walk(root):
                dirs[:] = [name for name in dirs if name not in _IGNORED_DIRECTORIES and not name.startswith(".agent_")]
                for name in names:
                    relative = _relative(root, Path(current) / name)
                    if relative and ("test" in Path(relative).name.casefold() or "tests" in Path(relative).parts):
                        values.append(relative)
        except OSError:
            pass
    return sorted(_unique(values), key=str.casefold)


def _command_for_route(route: dict[str, Any]) -> str | None:
    if (
        route.get("execution_channel") == verification_routing.DIRECT_ORACLE_EXECUTION
        or route.get("route_type") == verification_routing.DIRECT_ORACLE
    ):
        return None
    target = _path(route.get("target"))
    if not target:
        return None
    suffix = Path(target).suffix.casefold()
    if route.get("kind") == verification_routing.SYNTAX_STATIC_GATE:
        if suffix in {".js", ".mjs", ".cjs"}:
            return f"node --check {target}"
        if suffix == ".py":
            return f"python -m py_compile {target}"
        return None
    if route.get("kind") == verification_routing.FOCUSED_TEST:
        if suffix in {".js", ".mjs", ".cjs"}:
            return f"node {target}"
        if suffix == ".py":
            return f"python {target}"
        return None
    return None


def _default_verification_executor(command: str) -> Any:
    # Keep the existing run_tool executor authoritative.  Importing mini
    # lazily avoids a module cycle while preserving the existing workspace,
    # timeout, and command-safety policy.
    running_module = sys.modules.get("mini") or sys.modules.get("__main__")
    if running_module is not None and callable(getattr(running_module, "run_tool", None)):
        run_tool = running_module.run_tool
    else:
        from mini import run_tool

    return run_tool("run_command", {"command": command}, role="Builder")


def build_stage5a_verification_input(
    *,
    task: dict[str, Any],
    contract: dict[str, Any],
    authorization: dict[str, Any],
    workspace: str | os.PathLike,
    post_subject: dict[str, Any],
    execution_result: dict[str, Any],
    execution_evidence: Iterable[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build Stage 5A artifacts from approved contracts and actual state."""
    records = _verification_contract_records(authorization, contract)
    known_files = [item.get("path") for item in post_subject.get("paths", []) if isinstance(item, dict)]
    known_tests = _known_test_files(workspace, known_files)
    route_artifacts: list[dict[str, Any]] = []
    approved_route_bindings: list[dict[str, Any]] = []
    executable_routes: list[dict[str, Any]] = []
    for record in records:
        artifact = verification_routing.analyze_verification_applicability(
            task,
            contract,
            {"files": known_files, "tests": known_tests, "entrypoints": []},
            test_contract=record.get("contract", []),
            mutation_paths=contract.get("allowed_mutation_paths", []) or [],
            inspection_paths=contract.get("allowed_inspection_paths", []) or [],
            workspace=workspace,
            known_test_files=known_tests,
            execution_evidence=execution_evidence or [],
            approved_verification_authority=record,
        )
        authority_routes = [
            _copy(item) for item in artifact.get("verification_route_bindings", []) or []
            if isinstance(item, dict)
        ]
        route_artifacts.append({
            **_copy(record),
            "verification_id": record.get("verification_id"),
            "contract": _copy(record.get("contract", [])),
            "applicability": _copy(artifact),
            "route_bindings": authority_routes,
            "route_audit": _copy(artifact.get("route_audit", [])),
        })
        approved_route_bindings.extend(authority_routes)
        for route in artifact.get("verification_routes", []) or []:
            if not isinstance(route, dict):
                continue
            # Direct oracles are exact approved bindings but use their own
            # verifier channel; they must never become a generic node command.
            if (
                route.get("execution_channel") == verification_routing.DIRECT_ORACLE_EXECUTION
                or route.get("route_type") == verification_routing.DIRECT_ORACLE
            ):
                continue
            executable_routes.append(_copy(route))
    if not route_artifacts:
        # Local/fallback contracts still receive the old generic behavior,
        # but the result is enriched with the same canonical route shape.
        artifact = verification_routing.analyze_verification_applicability(
            task, contract, {"files": known_files, "tests": known_tests, "entrypoints": []},
            mutation_paths=contract.get("allowed_mutation_paths", []) or [],
            inspection_paths=contract.get("allowed_inspection_paths", []) or [],
            workspace=workspace, known_test_files=known_tests,
            execution_evidence=execution_evidence or [],
        )
        executable_routes = [
            _copy(item) for item in artifact.get("verification_routes", []) or []
            if isinstance(item, dict)
        ]

    # Syntax is a deterministic Stage 5A safety route, not a newly approved
    # verification contract.  Keep it exactly once and give it an explicit
    # system authority so mandatory-route validation cannot accept a generic
    # capability route.
    system_task = _copy(task)
    system_task.update({"goal": [], "done_when": [], "test_contract": [], "local_test_contract": []})
    system_contract = _copy(contract)
    system_contract["test_contract"] = []
    system_artifact = verification_routing.analyze_verification_applicability(
        system_task,
        system_contract,
        {"files": known_files, "tests": known_tests, "entrypoints": []},
        test_contract=[],
        mutation_paths=contract.get("allowed_mutation_paths", []) or [],
        inspection_paths=contract.get("allowed_inspection_paths", []) or [],
        workspace=workspace,
        known_test_files=known_tests,
        execution_evidence=[],
    )
    system_authority_ids: list[str] = []
    system_routes: list[dict[str, Any]] = []
    for route in system_artifact.get("verification_routes", []) or []:
        if not isinstance(route, dict):
            continue
        if route.get("kind") == verification_routing.SYNTAX_STATIC_GATE:
            target = _path(route.get("target"))
            authority_id = "SYSTEM-SYNTAX-" + (target or "UNRESOLVED").replace("/", "_").replace(".", "_").upper()
            system_authority_ids.append(authority_id)
            system_route = _copy(route)
            system_route["target_identity_upstream"] = bool(target)
            system_route["upstream_target_exists"] = bool(target)
            binding = verification_routing.build_verification_route_binding(
                system_route,
                authority_id=authority_id,
                authority_type=verification_routing.DETERMINISTIC_SYSTEM_SAFETY_CHECK,
                authority_source="STAGE5A_DETERMINISTIC_ROUTE",
                authority_provenance="DETERMINISTIC_SYSTEM_SAFETY_CHECK",
                route_type=verification_routing.DETERMINISTIC_SYSTEM_SAFETY_CHECK,
                execution_channel=verification_routing.STAGE5A_COMMAND,
                resolution_mode=verification_routing.DETERMINISTIC_SYSTEM_TARGET,
                candidate_targets=[target] if target else [],
                selected_target=target or None,
                approved_target=None,
                command=_command_for_route(route),
                provenance_refs=["stage5a:deterministic_syntax_safety"],
                responsibility_key=f"system:syntax:{target}",
            )
        else:
            browser_target = _path(route.get("target")) or None
            binding = verification_routing.build_verification_route_binding(
                route,
                authority_type=verification_routing.OPTIONAL_CAPABILITY,
                authority_source="GENERIC_OPTIONAL_CAPABILITY",
                authority_provenance="OPTIONAL_BROWSER_APPLICABILITY",
                route_type=verification_routing.OPTIONAL_CAPABILITY,
                execution_channel=verification_routing.STAGE5A_COMMAND,
                resolution_mode=(
                    verification_routing.SUPPORTED_TARGET_DISCOVERY
                    if browser_target else verification_routing.UNRESOLVED
                ),
                candidate_targets=route.get("candidates", []) or ([browser_target] if browser_target else []),
                selected_target=browser_target,
                command_identity="verify_web_app",
                provenance_refs=["stage5a:optional_browser_capability"],
                responsibility_key="optional:browser",
            )
        system_routes.append(_copy(binding))
    if route_artifacts:
        executable_routes.extend(system_routes)
    merged_routes = verification_routing.deduplicate_verification_routes(executable_routes)
    all_bindings = verification_routing.deduplicate_verification_routes(
        approved_route_bindings + merged_routes,
    )
    route_audit = []
    for route in all_bindings:
        route_audit.append({
            "route_id": route.get("route_id"),
            "verification_id": route.get("verification_id"),
            "oracle_id": route.get("oracle_id"),
            "authority_id": route.get("authority_id"),
            "authority_source": route.get("authority_source"),
            "authority_provenance": route.get("authority_provenance"),
            "required": route.get("required"),
            "applicable": route.get("applicable"),
            "route_type": route.get("route_type"),
            "candidate_targets": list(route.get("candidate_targets", []) or []),
            "selected_target": route.get("selected_target"),
            "target_resolution_reason": route.get("resolution_source"),
            "resolution_mode": route.get("resolution_mode"),
            "evidence_ids": list(route.get("evidence_refs", []) or []),
            "target_identity_existed_upstream": bool(route.get("target_identity_upstream")),
        })
    route_validation = (
        verification_routing.validate_verification_route_bindings(
            all_bindings,
            approved_authorities=records,
            deterministic_system_authorities=system_authority_ids,
        )
        if route_artifacts else {
            "valid": True,
            "legacy_fallback": True,
            "checked_routes": len(all_bindings),
            "mandatory_routes": sum(1 for item in all_bindings if item.get("required") is True),
            "errors": [],
            "model_calls": 0,
        }
    )
    payload = {
        "schema_version": "V20.5A",
        "child_id": str(task.get("id") or contract.get("execution_contract_id") or "UNKNOWN"),
        "model_calls": 0,
        "plan_id": (
            authorization.get("canonical_plan_id")
            or contract.get("plan_id")
            or task.get("approved_plan_id")
        ),
        "plan_hash": (
            authorization.get("canonical_plan_hash")
            or contract.get("plan_hash")
            or task.get("approved_plan_hash")
        ),
        "verification_digest": authorization.get("verification_digest"),
        "verification_obligation_coverage_hash": authorization.get(
            "verification_obligation_coverage_hash"
        ),
        "approved_verification_authority_ids": [
            str(item.get("verification_id") or item.get("oracle_id"))
            for item in records
            if isinstance(item, dict)
            and (item.get("verification_id") or item.get("oracle_id"))
        ],
        "verification_routes": [_copy(item) for item in merged_routes if isinstance(item, dict) and not (
            item.get("route_type") == verification_routing.DIRECT_ORACLE
            or item.get("execution_channel") == verification_routing.DIRECT_ORACLE_EXECUTION
        )],
        "direct_oracle_routes": [
            _copy(item) for item in all_bindings
            if isinstance(item, dict) and (
                item.get("route_type") == verification_routing.DIRECT_ORACLE
                or item.get("execution_channel") == verification_routing.DIRECT_ORACLE_EXECUTION
            )
        ],
        "verification_route_bindings": [_copy(item) for item in all_bindings],
        "approved_verification_route_bindings": [_copy(item) for item in approved_route_bindings],
        "route_audit": route_audit,
        "route_validation": route_validation,
        "repository_evidence": {
            "known_entrypoints": [],
            "known_test_files": known_tests[:20],
            "observed_file_types": sorted({Path(str(item)).suffix.casefold() for item in known_files if Path(str(item)).suffix}),
        },
    }
    payload["verification_applicability_hash"] = stage6c.canonical_hash(payload)
    payload["verification_routes_hash"] = payload["verification_applicability_hash"]
    return {
        "artifact": payload,
        "approved_verification_contracts": route_artifacts,
        "verification_input": {
            "approved_verification_contracts": _copy(route_artifacts),
            "verification_applicability": _copy(payload),
            "verification_route_bindings": _copy(all_bindings),
            "route_audit": _copy(route_audit),
            "post_worker_subject": _copy(post_subject),
            "execution_result": {
                "execution_contract_hash": execution_result.get("execution_contract_hash"),
                "authorization_hash": execution_result.get("authorization_hash"),
                "approval_receipt_hash": execution_result.get("approval_receipt_hash"),
                "changed_paths": list(execution_result.get("changed_paths", []) or []),
            },
        },
    }


def run_stage5a_verification(
    *,
    task: dict[str, Any],
    contract: dict[str, Any],
    authorization: dict[str, Any],
    workspace: str | os.PathLike,
    post_subject: dict[str, Any],
    execution_result: dict[str, Any],
    verification_runner: Callable[..., Any] | None = None,
    execute_command: Callable[[str], Any] | None = None,
    execution_obligation_evidence: Iterable[dict[str, Any]] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Route and execute approved verification contracts through Stage 5A."""
    input_state = build_stage5a_verification_input(
        task=task, contract=contract, authorization=authorization,
        workspace=workspace, post_subject=post_subject,
        execution_result=execution_result,
    )
    artifact = input_state["artifact"]
    if callable(verification_runner):
        callback_result = invoke_callback(
            verification_runner,
            verification_input=input_state["verification_input"],
            verification_applicability=artifact,
            approved_verification_contracts=input_state["approved_verification_contracts"],
            post_worker_subject=post_subject,
            execution_result=execution_result,
            workspace=str(_root(workspace) or workspace),
        )
        if isinstance(callback_result, list):
            evidence = [item for item in callback_result if isinstance(item, dict)]
        elif isinstance(callback_result, dict):
            evidence = []
            for key in ("verification_evidence", "execution_evidence", "tool_evidence", "evidence"):
                if isinstance(callback_result.get(key), list):
                    evidence.extend(item for item in callback_result[key] if isinstance(item, dict))
        else:
            evidence = []
    else:
        executor = execute_command or _default_verification_executor
        evidence = []
        seen_commands: set[str] = set()
        for route in artifact.get("verification_routes", []) or []:
            if not isinstance(route, dict) or route.get("required") is not True or route.get("applicable") is not True:
                continue
            command = _command_for_route(route)
            if not command or command in seen_commands:
                continue
            seen_commands.add(command)
            try:
                result = executor(command)
            except Exception as exc:  # the real executor remains authoritative
                result = f"verification executor error: {exc}"
            evidence.append({
                "tool": "run_command",
                "target": route.get("target"),
                "command": command,
                "result": str(result),
            })
    aggregation = verification_routing.aggregate_verification_evidence(
        artifact, evidence,
        execution_obligation_evidence=execution_obligation_evidence,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    return {
        "status": VERIFICATION_PASSED if aggregation.get("passed") else VERIFICATION_FAILED,
        "passed": bool(aggregation.get("passed")),
        "verification_applicability": artifact,
        "verification_input": input_state["verification_input"],
        "approved_verification_contracts": input_state["approved_verification_contracts"],
        "verification_aggregation": aggregation,
        "execution_verification_closure": aggregation.get("execution_verification_closure"),
        "execution_time_coverage": aggregation.get("execution_time_coverage"),
        "execution_obligation_evidence": aggregation.get("execution_obligation_evidence", []),
        "verification_evidence": evidence,
        "tool_evidence": evidence,
        "model_calls": 0,
    }


def _is_dnt(path: str, dnt_paths: Iterable[Any]) -> bool:
    normalized = _path(path).casefold().rstrip("/")
    return any(
        normalized == _path(item).casefold().rstrip("/")
        or normalized.startswith(_path(item).casefold().rstrip("/") + "/")
        for item in dnt_paths
        if _path(item)
    )


def _is_within(path: str, allowed_paths: Iterable[Any]) -> bool:
    normalized = _path(path).casefold().rstrip("/")
    return any(
        normalized == _path(item).casefold().rstrip("/")
        or normalized.startswith(_path(item).casefold().rstrip("/") + "/")
        for item in allowed_paths
        if _path(item)
    )


def audit_post_worker_mutation(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    contract: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, Any]:
    """Apply exact scope, DNT, creation, deletion, and no-op semantics."""
    diff = diff_execution_subject(before, after)
    changed = list(diff.get("changed_paths", []) or [])
    approved_paths = list(contract.get("allowed_mutation_paths", []) or [])
    auth_scope = authorization.get("approved_mutation_scope") if isinstance(authorization.get("approved_mutation_scope"), dict) else {}
    auth_paths = list(auth_scope.get("paths", []) or [])
    dnt = authorization.get("approved_dnt") if isinstance(authorization.get("approved_dnt"), dict) else {}
    dnt_paths = list(dnt.get("paths", []) or []) or list(contract.get("global_do_not_touch", []) or [])
    dnt_changed = [path for path in changed if _is_dnt(path, dnt_paths)]
    out_of_scope = []
    for path in changed:
        check = stage4.tool_scope(contract, path, mutation=True)
        if not check.get("allowed") or not _is_within(path, auth_paths) or not _is_within(path, approved_paths):
            out_of_scope.append(path)
    worker_required = bool(contract.get("worker_required"))
    behavior_change = str(contract.get("impact_kind") or "").upper() == "BEHAVIOR_CHANGE" or str(contract.get("responsibility_type") or "").upper() in {"MUTATION", "TEST_MUTATION"}
    if dnt_changed:
        status = DNT_VIOLATION
    elif out_of_scope:
        status = UNAUTHORIZED_MUTATION
    elif worker_required and behavior_change and not changed:
        status = WORKER_NO_APPROVED_MUTATION
    else:
        status = MUTATION_SCOPE_VALIDATED
    return {
        "status": status,
        "passed": status == MUTATION_SCOPE_VALIDATED,
        "changed_paths": changed,
        "created_paths": list(diff.get("created_paths", []) or []),
        "deleted_paths": list(diff.get("deleted_paths", []) or []),
        "renamed_paths": list(diff.get("renamed_paths", []) or []),
        "out_of_scope_paths": out_of_scope,
        "dnt_changed_paths": dnt_changed,
        "scope_violations": len(out_of_scope),
        "unauthorized_mutations": len(out_of_scope),
        "dnt_violations": len(dnt_changed),
        "before_subject": _copy(before),
        "after_subject": _copy(after),
    }


post_worker_mutation_audit = audit_post_worker_mutation


def _worker_output_valid(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    status = str(value.get("status", "done")).casefold()
    return status in {"done", "completed", "complete", "success", "worker_execution_completed"}


def _contains_precommit_rejection(value: Any, depth: int = 0) -> bool:
    """Find the deterministic tool rejection without treating it as verification."""
    if depth > 5:
        return False
    if isinstance(value, str):
        return stage6c_invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION in value
    if isinstance(value, dict):
        return any(
            _contains_precommit_rejection(item, depth + 1)
            for item in value.values()
        )
    if isinstance(value, (list, tuple)):
        return any(_contains_precommit_rejection(item, depth + 1) for item in value)
    return False


def execute_approval_bound_worker(
    *,
    task: dict[str, Any],
    contract: dict[str, Any],
    plan: dict[str, Any],
    authorization: dict[str, Any],
    receipt: dict[str, Any],
    revalidation: dict[str, Any],
    request: dict[str, Any],
    current_state: dict[str, Any] | None,
    contracts: Iterable[dict[str, Any]],
    graph: dict[str, Any] | None,
    workspace: str | os.PathLike,
    worker_context: str,
    worker_dispatch: Callable[..., Any],
    verification_runner: Callable[..., Any] | None = None,
    execution_obligation_evidence: Iterable[dict[str, Any]] | Callable[[], Iterable[dict[str, Any]]] | None = None,
    verification_obligation_coverage: dict[str, Any] | None = None,
    execute_command: Callable[[str], Any] | None = None,
    store: Any = None,
    project_id: str | None = None,
    transaction_commit: Callable[[], Any] | None = None,
    transaction_close: Callable[[], Any] | None = None,
    pre_commit_validator: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
    on_start_receipt: Callable[[dict[str, Any]], Any] | None = None,
    on_authorization_block: Callable[[dict[str, Any]], Any] | None = None,
) -> dict[str, Any]:
    """Execute one approved Stage 4 responsibility and stop at Stage 5A."""
    if _root(workspace) is None:
        return {
            "status": "failed",
            "terminal_state": WORKER_AUTHORIZATION_INVALID,
            "failure_type": WORKER_AUTHORIZATION_INVALID,
            "orchestration_failure": WORKER_AUTHORIZATION_INVALID,
            "summary": "an isolated execution workspace is required",
            "worker_calls": 0,
            "model_calls": 0,
        }
    paths = _subject_paths(contract, authorization)
    before = enumerate_execution_subject(workspace)
    pre_subject = integration_gate.fingerprint_dependency_paths(workspace, paths)
    pre_brain = _brain_hash(store, project_id, current_state)
    if pre_brain is None:
        pre_brain = str(
            (current_state or {}).get("brain_hash")
            or ((current_state or {}).get("authority_binding") or {}).get("brain_hash")
            or authorization.get("current_brain_hash")
            or ""
        )
    audit = last_moment_authorization_audit(
        authorization=authorization, receipt=receipt, revalidation=revalidation,
        request=request, plan=plan, current_state=current_state,
        contracts=contracts, graph=graph, contract=contract,
        workspace=workspace, store=store, project_id=project_id,
        subject_paths=paths,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    if not audit.get("allowed"):
        if callable(on_authorization_block):
            on_authorization_block(audit)
        return {
            "status": "blocked",
            "terminal_state": audit.get("terminal_state") or WORKER_AUTHORIZATION_INVALID,
            "failure_type": audit.get("status") or WORKER_AUTHORIZATION_INVALID,
            "orchestration_failure": audit.get("code") or WORKER_AUTHORIZATION_INVALID,
            "summary": "; ".join(str(item) for item in audit.get("errors", [])[:8]) or "last-moment authorization failed",
            "authorization_audit": audit,
            "worker_calls": 0,
            "model_calls": 0,
        }

    start_receipt = create_execution_start_receipt(
        authorization, receipt, plan, contract,
        pre_subject_hash=str(pre_subject.get("hash") or ""),
        pre_brain_hash=str(pre_brain or ""), workspace=workspace,
        subject_paths=paths,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    start_check = validate_execution_start_receipt(
        start_receipt,
        authorization=authorization,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    if not start_check.get("valid"):
        return {
            "status": "blocked", "terminal_state": WORKER_AUTHORIZATION_INVALID,
            "failure_type": WORKER_AUTHORIZATION_INVALID,
            "orchestration_failure": "EXECUTION_START_RECEIPT_INVALID",
            "summary": "; ".join(start_check.get("errors", [])),
            "worker_calls": 0, "model_calls": 0,
        }
    if callable(on_start_receipt):
        on_start_receipt(_copy(start_receipt))

    def immediate_check() -> dict[str, Any]:
        return last_moment_authorization_audit(
            authorization=authorization, receipt=receipt, revalidation=revalidation,
            request=request, plan=plan, current_state=current_state,
            contracts=contracts, graph=graph, contract=contract,
            workspace=workspace, store=store, project_id=project_id,
            expected_start_receipt=start_receipt, subject_paths=paths,
            verification_obligation_coverage=verification_obligation_coverage,
        )

    try:
        worker_raw = invoke_callback(
            worker_dispatch,
            worker_context=worker_context,
            context=worker_context,
            execution_contract=contract,
            contract=contract,
            task=task,
            workspace=str(_root(workspace) or workspace),
            authorization=authorization,
            receipt=receipt,
            start_receipt=start_receipt,
            worker_start_receipt=start_receipt,
            authorization_check=immediate_check,
            execute_tool=None,
            run_tool=None,
        )
    except Exception as exc:
        if callable(transaction_close):
            transaction_close()
        return {
            "status": "failed", "terminal_state": WORKER_OUTPUT_INVALID,
            "failure_type": WORKER_OUTPUT_INVALID,
            "orchestration_failure": WORKER_OUTPUT_INVALID,
            "summary": f"Worker dispatch failed: {exc}",
            "execution_start_receipt": start_receipt,
            "authorization_audit": audit,
            "worker_calls": 1,
            "model_calls": 0,
        }
    after = enumerate_execution_subject(workspace)
    if isinstance(worker_raw, dict) and worker_raw.get("status") == "blocked":
        blocked_state = str(
            worker_raw.get("terminal_state")
            or worker_raw.get("failure_type")
            or worker_raw.get("orchestration_failure")
            or ""
        )
        if blocked_state in {
            stage6c.REAPPROVAL_REQUIRED,
            WORKER_AUTHORIZATION_INVALID,
            stage6c.EXECUTION_AUTHORIZATION_BLOCKED,
        }:
            if callable(transaction_close):
                transaction_close()
            if callable(on_authorization_block):
                on_authorization_block(
                    worker_raw.get("authorization_audit")
                    if isinstance(worker_raw.get("authorization_audit"), dict)
                    else worker_raw
                )
            return {
                "status": "blocked",
                "terminal_state": blocked_state,
                "failure_type": blocked_state,
                "orchestration_failure": worker_raw.get("orchestration_failure") or blocked_state,
                "summary": worker_raw.get("summary") or "last-moment Worker authorization failed",
                "execution_start_receipt": start_receipt,
                "worker_result": _copy(worker_raw),
                "authorization_audit": _copy(worker_raw.get("authorization_audit")),
                "worker_calls": 0,
                "model_calls": 0,
            }
    execution_identity = {
        "execution_contract_hash": contract.get("contract_hash"),
        "authorization_hash": authorization.get("authorization_hash"),
        "approval_receipt_hash": receipt.get("receipt_hash"),
        "pre_subject_hash": pre_subject.get("hash"),
        "post_subject_hash": after.get("hash"),
        "changed_paths": [],
    }
    if not _worker_output_valid(worker_raw):
        if callable(transaction_close):
            transaction_close()
        return {
            "status": "failed", "terminal_state": WORKER_OUTPUT_INVALID,
            "failure_type": WORKER_OUTPUT_INVALID,
            "orchestration_failure": WORKER_OUTPUT_INVALID,
            "summary": "Worker callback did not return a completed structured result",
            "execution_start_receipt": start_receipt,
            "worker_result": _copy(worker_raw) if isinstance(worker_raw, dict) else {"type": type(worker_raw).__name__},
            "worker_calls": 1, "model_calls": 0,
        }
    worker_result = _copy(worker_raw)
    execution_identity["raw_worker_result_ref"] = "worker-result:" + stage6c.canonical_hash(worker_result)[:24]
    mutation_audit = audit_post_worker_mutation(
        before, after, contract=contract, authorization=authorization,
    )
    execution_identity["changed_paths"] = list(mutation_audit.get("changed_paths", []) or [])
    execution_result = {
        "worker_run_id": "WORKER-" + start_receipt["receipt_hash"][:24].upper(),
        "model_provider": worker_result.get("model_provider") or worker_result.get("provider") or "callback",
        "execution_contract_hash": contract.get("contract_hash"),
        "authorization_hash": authorization.get("authorization_hash"),
        "approval_receipt_hash": receipt.get("receipt_hash"),
        "pre_subject_hash": pre_subject.get("hash"),
        "post_subject_hash": after.get("hash"),
        "changed_paths": list(mutation_audit.get("changed_paths", []) or []),
        "created_paths": list(mutation_audit.get("created_paths", []) or []),
        "deleted_paths": list(mutation_audit.get("deleted_paths", []) or []),
        "renamed_paths": list(mutation_audit.get("renamed_paths", []) or []),
        "raw_worker_result_ref": execution_identity["raw_worker_result_ref"],
        "execution_status": WORKER_EXECUTION_COMPLETED,
    }
    if mutation_audit.get("status") != MUTATION_SCOPE_VALIDATED:
        if callable(transaction_close):
            transaction_close()
        precommit_rejection = _contains_precommit_rejection(worker_result)
        # V25.2 callers historically observed VERIFICATION_FAILED for a
        # completed callback whose proposed edit could not produce a verified
        # subject.  Preserve that terminal alias for compatibility while
        # exposing the exact V25.5 failure type and never invoking Stage 5 for
        # a candidate that was rejected before commit.
        terminal_state = VERIFICATION_FAILED if precommit_rejection else mutation_audit.get("status")
        failure_type = (
            stage6c_invariants.EXECUTION_INVARIANT_MUTATION_VIOLATION
            if precommit_rejection else mutation_audit.get("status")
        )
        return {
            "status": "failed",
            "terminal_state": terminal_state,
            "failure_type": failure_type,
            "orchestration_failure": failure_type,
            "summary": failure_type,
            "execution_start_receipt": start_receipt,
            "worker_result": worker_result,
            "execution_result": execution_result,
            "worker_execution": execution_result,
            "mutation_audit": mutation_audit,
            "changed_files": list(mutation_audit.get("changed_paths", []) or []),
            "worker_calls": 1, "model_calls": 0,
            "unauthorized_mutations": mutation_audit.get("unauthorized_mutations", 0),
            "scope_violations": mutation_audit.get("scope_violations", 0),
            "dnt_violations": mutation_audit.get("dnt_violations", 0),
            "precommit_invariant_rejection": precommit_rejection,
        }

    obligation_evidence = (
        execution_obligation_evidence()
        if callable(execution_obligation_evidence)
        else execution_obligation_evidence
    )
    verification = run_stage5a_verification(
        task=task, contract=contract, authorization=authorization,
        workspace=workspace, post_subject=after, execution_result=execution_result,
        verification_runner=verification_runner, execute_command=execute_command,
        execution_obligation_evidence=obligation_evidence,
        verification_obligation_coverage=verification_obligation_coverage,
    )
    if not verification.get("passed"):
        if callable(transaction_close):
            transaction_close()
        return {
            "status": "failed", "terminal_state": VERIFICATION_FAILED,
            "failure_type": VERIFICATION_FAILED,
            "orchestration_failure": VERIFICATION_FAILED,
            "summary": "mandatory approved verification failed",
            "execution_start_receipt": start_receipt,
            "worker_result": worker_result,
            "execution_result": execution_result,
            "worker_execution": execution_result,
            "mutation_audit": mutation_audit,
            "verification": verification,
            "verification_applicability": verification.get("verification_applicability"),
            "verification_input": verification.get("verification_input"),
            "approved_verification_contracts": verification.get("approved_verification_contracts", []),
            "verification_aggregation": verification.get("verification_aggregation"),
            "execution_verification_closure": verification.get("execution_verification_closure"),
            "execution_time_coverage": verification.get("execution_time_coverage"),
            "execution_obligation_evidence": verification.get("execution_obligation_evidence", []),
            "verification_evidence": verification.get("verification_evidence", []),
            "tool_evidence": verification.get("tool_evidence", []),
            "changed_files": list(mutation_audit.get("changed_paths", []) or []),
            "worker_calls": 1, "model_calls": 0,
            "unauthorized_mutations": 0, "scope_violations": 0, "dnt_violations": 0,
        }
    if callable(pre_commit_validator):
        try:
            impact_check = pre_commit_validator(mutation_audit, verification)
        except Exception as exc:
            impact_check = {
                "passed": False,
                "status": "PRE_COMMIT_IMPACT_VALIDATOR_ERROR",
                "failure_type": "PRE_COMMIT_IMPACT_VALIDATOR_ERROR",
                "reason": str(exc),
            }
        if not isinstance(impact_check, dict):
            impact_check = {
                "passed": False,
                "status": "PRE_COMMIT_IMPACT_VALIDATOR_INVALID_RESULT",
                "failure_type": "PRE_COMMIT_IMPACT_VALIDATOR_INVALID_RESULT",
                "reason": "pre-commit impact validator must return a structured result",
            }
        if not impact_check.get("passed"):
            if callable(transaction_close):
                transaction_close()
            return {
                "status": "failed",
                "terminal_state": impact_check.get("failure_type") or impact_check.get("status") or VERIFICATION_FAILED,
                "failure_type": impact_check.get("failure_type") or impact_check.get("status") or VERIFICATION_FAILED,
                "orchestration_failure": impact_check.get("failure_type") or impact_check.get("status") or VERIFICATION_FAILED,
                "summary": "pre-mutation impact contract did not match the approved mutation",
                "execution_start_receipt": start_receipt,
                "worker_result": worker_result,
                "execution_result": execution_result,
                "worker_execution": execution_result,
                "mutation_audit": mutation_audit,
                "verification": verification,
                "verification_applicability": verification.get("verification_applicability"),
                "verification_input": verification.get("verification_input"),
                "verification_aggregation": verification.get("verification_aggregation"),
                "verification_evidence": verification.get("verification_evidence", []),
                "impact_comparison": _copy(impact_check),
                "changed_files": list(mutation_audit.get("changed_paths", []) or []),
                "worker_calls": 1, "model_calls": 0,
            }
    if callable(transaction_commit):
        committed = transaction_commit()
    else:
        committed = list(mutation_audit.get("changed_paths", []) or [])
    integration_routes = []
    for route in verification.get("verification_applicability", {}).get("verification_routes", []) or []:
        if not isinstance(route, dict) or route.get("kind") != verification_routing.FOCUSED_TEST:
            continue
        target = _path(route.get("target"))
        if target and ("integration" in target.casefold() or ".integration." in target.casefold()):
            integration_routes.append({
                "kind": "INTEGRATION_TEST", "required": True, "applicable": True,
                "target": target, "result": verification_routing.PENDING,
                "reason_codes": ["APPROVED_STAGE5A_ROUTE"],
                "evidence_refs": list(route.get("evidence_refs", []) or []),
            })
    if not integration_routes:
        for value in contract.get("integration_responsibility", []) or []:
            matches = [
                _path(match.group(0)) for match in _PATH_RE.finditer(str(value))
            ]
            if matches:
                integration_routes.append({
                    "kind": "INTEGRATION_TEST", "required": True, "applicable": True,
                    "target": matches[0], "result": verification_routing.PENDING,
                    "reason_codes": ["APPROVED_INTEGRATION_RESPONSIBILITY"],
                    "evidence_refs": ["contract:integration_responsibility"],
                })
                break
    integration_routes.append({
        "kind": "BROWSER", "required": False, "applicable": False,
        "target": None, "result": verification_routing.SKIPPED_NOT_APPLICABLE,
        "reason_codes": ["VERIFIER_NOT_REQUIRED"],
        "evidence_refs": ["stage5a:browser_applicability"],
    })
    return {
        "status": "done",
        "terminal_state": VERIFICATION_PASSED,
        "failure_type": None,
        "summary": worker_result.get("summary") or "approved Worker execution verified",
        "execution_start_receipt": start_receipt,
        "worker_result": worker_result,
        "worker_execution": execution_result,
        "execution_result": execution_result,
        "mutation_audit": mutation_audit,
        "verification": verification,
        "verification_applicability": verification.get("verification_applicability"),
        "verification_input": verification.get("verification_input"),
        "approved_verification_contracts": verification.get("approved_verification_contracts", []),
        "verification_aggregation": verification.get("verification_aggregation"),
        "execution_verification_closure": verification.get("execution_verification_closure"),
        "execution_time_coverage": verification.get("execution_time_coverage"),
        "execution_obligation_evidence": verification.get("execution_obligation_evidence", []),
        "verification_evidence": verification.get("verification_evidence", []),
        "tool_evidence": verification.get("tool_evidence", []),
        "impact_comparison": _copy(impact_check) if callable(pre_commit_validator) else None,
        # The mutation audit is the stable public path representation.  The
        # existing transaction helper may return absolute capture paths; keep
        # those implementation details out of Stage 5 provenance.
        "changed_files": list(mutation_audit.get("changed_paths", []) or []),
        "committed_paths": list(committed or []),
        "integration_routes": integration_routes,
        "integration_evidence": list(verification.get("verification_evidence", []) or []),
        "worker_calls": 1,
        "model_calls": 0,
        "execution_status": WORKER_EXECUTION_COMPLETED,
        "verification_status": VERIFICATION_PASSED,
        "mutation_scope_status": MUTATION_SCOPE_VALIDATED,
        "lifecycle_states": [
            APPROVAL_BOUND_EXECUTION_STARTED,
            WORKER_EXECUTION_COMPLETED,
            MUTATION_SCOPE_VALIDATED,
            VERIFICATION_PASSED,
        ],
    }


run_approval_bound_worker = execute_approval_bound_worker
execute_approved_worker = execute_approval_bound_worker


__all__ = [name for name in globals() if not name.startswith("_")]
