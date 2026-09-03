"""Stage 4A approved-plan execution contracts.

This module is deliberately deterministic.  Stage 3 owns the architectural
decisions; this module only snapshots the approved result, compiles bounded
worker responsibilities, validates their dependency graph, and projects one
contract into a fresh model context.  It never reads the repository and never
calls a model.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re

from hivo import impact_planning as stage3
from hivo import execution_invariants as invariant
from hivo.requirements import freeze


# The limits are intentionally independent of the frozen Stage 1-3 limits.
# They bound the execution handoff without changing planning or Worker budgets.
MAX_EXECUTION_CONTRACTS = 16
MAX_PLAN_NODES = 32
MAX_REQUIREMENTS_PER_CONTRACT = 16
MAX_OBLIGATION_TYPES_PER_CONTRACT = 32
MAX_SURFACES_PER_CONTRACT = 32
MAX_INTERFACES_PER_CONTRACT = 16
MAX_PRESERVATION_PER_CONTRACT = 16
MAX_PROHIBITIONS_PER_CONTRACT = 16
MAX_TEST_CHECKS_PER_CONTRACT = 12
MAX_DONE_WHEN_PER_CONTRACT = 12
MAX_DEPENDENCIES_PER_CONTRACT = 16
MAX_REPOSITORY_FACTS_PER_CONTRACT = 16
MAX_SNAPSHOT_REQUIREMENTS = 64
MAX_SNAPSHOT_EVIDENCE = 128
MAX_SNAPSHOT_SURFACES = 128
MAX_SNAPSHOT_PROPOSALS = 8
MAX_PATH_CHARS = 300
MAX_TEXT_CHARS = 900
MAX_REQUIREMENT_TEXT_CHARS = 900
MAX_CONTRACT_CHARS = 14000
MAX_SNAPSHOT_CHARS = 26000
MAX_CONTEXT_CHARS = 14000
# The full hydrated mission is an internal audit/provenance artifact.  It has
# its own generous bound and must not be confused with the model-facing Worker
# context limit owned by the orchestrator.
MAX_HYDRATED_MISSION_CHARS = 26000
WORKER_CONTEXT_RENDERING_VERSION = "v19.3-1"

APPROVED_PLAN = "APPROVED_PLAN"
REPOSITORY_EVIDENCE = "REPOSITORY_EVIDENCE"
SOURCE_REQUIREMENT = "SOURCE_REQUIREMENT"
DERIVED_EXECUTION_CONTRACT = "DERIVED_EXECUTION_CONTRACT"

MUTATION = "MUTATION"
TEST_MUTATION = "TEST_MUTATION"
VERIFY_ONLY = "VERIFY_ONLY"
INTERFACE_REUSE = "INTERFACE_REUSE"
INTEGRATION_CHECK = "INTEGRATION_CHECK"

PLAN_APPROVAL_REQUIRED = "PLAN_APPROVAL_REQUIRED"
APPROVED_PLAN_STALE = "APPROVED_PLAN_STALE"
EXECUTION_CONTRACT_BLOCKED = "EXECUTION_CONTRACT_BLOCKED"
EXECUTION_CONTRACT_TOO_LARGE = "EXECUTION_CONTRACT_TOO_LARGE"
CONTRACT_SCOPE_VIOLATION = "CONTRACT_SCOPE_VIOLATION"
MISSION_CONTRACT_VIOLATION = "MISSION_CONTRACT_VIOLATION"
EXECUTION_GRAPH_INVALID = "EXECUTION_GRAPH_INVALID"
EXECUTION_DEPENDENCY_BLOCKED = "EXECUTION_DEPENDENCY_BLOCKED"
HYDRATED_MISSION_TOO_LARGE = "HYDRATED_MISSION_TOO_LARGE"
WORKER_CONTEXT_TOO_LARGE = "WORKER_CONTEXT_TOO_LARGE"
WORKER_CONTEXT_AUTHORITY_TOO_LARGE = "WORKER_CONTEXT_AUTHORITY_TOO_LARGE"
WORKER_CONTEXT_ADVICE_UNAVAILABLE = "WORKER_CONTEXT_ADVICE_UNAVAILABLE"
# V25.2 mandatory execution-invariant authority.  This is deliberately a
# separate failure from ordinary optional-advice budgeting: preservation
# facts are never silently dropped to fit a Worker packet.
WORKER_EXECUTION_INVARIANT_CONTEXT_OVERFLOW = invariant.EXECUTION_INVARIANT_CONTEXT_OVERFLOW
EXECUTION_INVARIANT_SET_REQUIRED = invariant.EXECUTION_INVARIANT_SET_REQUIRED
EXECUTION_INVARIANT_INVALID = invariant.EXECUTION_INVARIANT_INVALID

# V19.4 structural granularity outcomes.  These are deterministic routing
# observations over an already-approved Execution Contract; they are not
# model decisions and do not become part of the contract authority/hash.
DIRECT_ALLOWED = "DIRECT_ALLOWED"
AMBIGUOUS = "AMBIGUOUS"
DECOMPOSITION_REQUIRED = "DECOMPOSITION_REQUIRED"
STRUCTURAL_DECOMPOSITION_REQUIRED = "STRUCTURAL_DECOMPOSITION_REQUIRED"
STRUCTURAL_FIT_SCHEMA_VERSION = "4B-structural-fit-1"

RESPONSIBILITY_TYPES = (MUTATION, TEST_MUTATION, VERIFY_ONLY, INTERFACE_REUSE, INTEGRATION_CHECK)

_RAW_FORBIDDEN_KEYS = frozenset({
    "raw_impact_planner_output", "raw_impact_map", "raw_impact_challenger_output",
    "raw_challenger_output", "impact_planner_transcript", "impact_challenger_transcript",
    "planner_transcript", "challenger_transcript", "clarification_conversation",
    "repository_scout_transcript", "specifier_transcript", "full_project_brain",
    "full_task_brain", "task_brain", "project_brain", "source_ledger", "impact_map",
    "candidate_impact_map", "validated_challenges", "planning_packet",
})
_PATH_RE = re.compile(
    r"(?:^|[\s'\"`()\[\]{},:;])((?:[A-Za-z]:)?[^\s'\"`()\[\]{},:;]+[/\\][^\s'\"`()\[\]{},:;]+|"
    r"[^\s'\"`()\[\]{},:;]+\.(?:py|pyi|js|mjs|cjs|jsx|ts|tsx|html|htm|css|scss|json|toml|yaml|yml|go|rs|java|c|cpp|h|md|txt))"
)

# ``_PATH_RE`` is intentionally only a lexical candidate extractor.  A slash
# is common in ordinary prose (for example ``pause/resume``), so candidates
# must pass ``classify_code_location_reference`` before they can influence
# semantic scope validation.
_CODE_PATH_EXTENSIONS = frozenset({
    "py", "pyi", "js", "mjs", "cjs", "jsx", "ts", "tsx", "html", "htm",
    "css", "scss", "json", "toml", "yaml", "yml", "go", "rs", "java", "c",
    "cpp", "h", "md", "txt",
})
_WINDOWS_PATH_RE = re.compile(r"^[A-Za-z]:/")
_EXPLICIT_RELATIVE_PATH_RE = re.compile(r"^\.\.?/")


class ExecutionContractError(RuntimeError):
    """A deterministic Stage 4A validation or compilation failure."""

    def __init__(self, code: str, message: str, *, details=None):
        self.code = str(code)
        self.details = list(details or [])
        super().__init__(f"{self.code}: {message}")


class ApprovedPlanSnapshotError(ExecutionContractError):
    """The approved Stage 3 plan cannot become an execution snapshot."""


class ExecutionContractTooLargeError(ExecutionContractError):
    """Required contract authority exceeds a Stage 4A bound."""


class ExecutionGraphError(ExecutionContractError):
    """The compiled contracts do not form an executable approved DAG."""


def _copy(value):
    return copy.deepcopy(value)


def _require_authority_list(value, limit, label):
    """Reject an over-bound authority list instead of clipping it."""
    if value is None:
        return
    if not isinstance(value, (list, tuple)):
        raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, f"{label} must be a list")
    if len(value) > limit:
        raise ExecutionContractTooLargeError(
            EXECUTION_CONTRACT_TOO_LARGE,
            f"{label} bound exceeded ({len(value)} > {limit})",
        )


def _require_authority_text(value, limit, label):
    """Reject a required string that cannot fit its bounded authority slot."""
    if value in (None, ""):
        return
    if len(" ".join(str(value).split())) > limit:
        raise ExecutionContractTooLargeError(
            EXECUTION_CONTRACT_TOO_LARGE,
            f"{label} exceeds its bounded authority length ({limit} characters)",
        )


def _validate_plan_authority_bounds(plan, requirements, evidence, registry):
    """Validate raw Stage 3 authority before any compact projection is made."""
    value = plan if isinstance(plan, dict) else {}
    nodes = list(value.get("approved_change_nodes", []) or [])
    _require_authority_list(nodes, MAX_PLAN_NODES, "approved_change_nodes")
    source_requirements = list(value.get("requirements", []) or []) or list(requirements or [])
    _require_authority_list(source_requirements, MAX_SNAPSHOT_REQUIREMENTS, "snapshot requirements")
    preservation = list(value.get("preservation_only_surfaces", []) or [])
    _require_authority_list(preservation, MAX_PLAN_NODES, "preservation_only_surfaces")
    _require_authority_list(value.get("do_not_touch"), MAX_SURFACES_PER_CONTRACT, "global do_not_touch")
    _require_authority_list(value.get("do_not_touch_surface_ids"), MAX_SURFACES_PER_CONTRACT, "global do_not_touch_surface_ids")
    _require_authority_list(value.get("prohibition_constraints"), MAX_PROHIBITIONS_PER_CONTRACT, "structured prohibitions")
    _require_authority_list(value.get("integration_verification"), MAX_TEST_CHECKS_PER_CONTRACT, "integration_contract")
    _require_authority_list(value.get("new_surface_proposals"), MAX_SNAPSHOT_PROPOSALS, "new_surface_proposals")
    canonical_constraints = value.get("canonical_constraints")
    if canonical_constraints is not None:
        if not isinstance(canonical_constraints, dict):
            raise ExecutionContractError(
                EXECUTION_CONTRACT_BLOCKED,
                "canonical_constraints must be an object",
            )
        for field, limit in (
            ("preservation", MAX_PRESERVATION_PER_CONTRACT * 2),
            ("prohibitions", MAX_PROHIBITIONS_PER_CONTRACT * 2),
        ):
            records = canonical_constraints.get(field, [])
            _require_authority_list(records, limit, f"canonical_constraints.{field}")
            seen_ids = set()
            for index, record in enumerate(records or [], 1):
                if not isinstance(record, dict) or not record.get("constraint_id"):
                    raise ExecutionContractError(
                        EXECUTION_CONTRACT_BLOCKED,
                        f"canonical_constraints.{field}[{index}] requires constraint_id",
                    )
                constraint_id = str(record.get("constraint_id"))
                if constraint_id in seen_ids:
                    raise ExecutionContractError(
                        EXECUTION_CONTRACT_BLOCKED,
                        f"canonical_constraints.{field} contains duplicate constraint_id",
                    )
                seen_ids.add(constraint_id)
                _require_authority_text(record.get("text"), MAX_TEXT_CHARS, f"canonical constraint {constraint_id} text")
                for subfield, sublimit in (
                    ("requirement_ids", MAX_REQUIREMENTS_PER_CONTRACT),
                    ("obligation_ids", MAX_SURFACES_PER_CONTRACT),
                    ("node_ids", MAX_PLAN_NODES),
                    ("surface_ids", MAX_SURFACES_PER_CONTRACT),
                ):
                    _require_authority_list(record.get(subfield), sublimit, f"canonical constraint {constraint_id} {subfield}")
    canonical_verifications = value.get("canonical_verification_contracts")
    if canonical_verifications is not None:
        _require_authority_list(
            canonical_verifications, MAX_TEST_CHECKS_PER_CONTRACT * 2,
            "canonical_verification_contracts",
        )
        for index, record in enumerate(canonical_verifications or [], 1):
            if not isinstance(record, dict) or not record.get("verification_id"):
                raise ExecutionContractError(
                    EXECUTION_CONTRACT_BLOCKED,
                    f"canonical_verification_contracts[{index}] requires verification_id",
                )
            _require_authority_list(record.get("contract"), MAX_TEST_CHECKS_PER_CONTRACT, f"canonical verification {index} contract")
            _require_authority_list(record.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT, f"canonical verification {index} requirement_ids")
            _require_authority_list(record.get("evidence_ids"), MAX_REPOSITORY_FACTS_PER_CONTRACT, f"canonical verification {index} evidence_ids")
            _require_authority_list(record.get("surface_ids"), MAX_SURFACES_PER_CONTRACT, f"canonical verification {index} surface_ids")
            _require_authority_list(record.get("paths"), MAX_SURFACES_PER_CONTRACT, f"canonical verification {index} paths")
            _require_authority_list(record.get("node_ids"), MAX_PLAN_NODES, f"canonical verification {index} node_ids")
            for field in ("contract",):
                for item_index, text in enumerate(record.get(field, []) or [], 1):
                    _require_authority_text(text, MAX_TEXT_CHARS, f"canonical verification {index} {field}[{item_index}]")
    for index, item in enumerate(value.get("do_not_touch", []) or [], 1):
        _require_authority_text(item, MAX_PATH_CHARS, f"global do_not_touch[{index}]")
    for field in ("prohibition_constraints", "integration_verification"):
        for index, item in enumerate(value.get(field, []) or [], 1):
            _require_authority_text(item, MAX_TEXT_CHARS, f"{field}[{index}]")
    for index, proposal in enumerate(value.get("new_surface_proposals", []) or [], 1):
        if len(_json(proposal)) > MAX_TEXT_CHARS * 2:
            raise ExecutionContractTooLargeError(
                EXECUTION_CONTRACT_TOO_LARGE,
                f"new_surface_proposals[{index}] is too large",
            )
    obligation_ledger = value.get("requirement_obligation_ledger")
    if not isinstance(obligation_ledger, dict):
        obligation_ledger = stage3.build_requirement_obligation_ledger(source_requirements)
    for index, item in enumerate(obligation_ledger.get("requirements", []) or [], 1):
        if isinstance(item, dict):
            _require_authority_list(
                item.get("obligation_types"), MAX_OBLIGATION_TYPES_PER_CONTRACT,
                f"obligation ledger requirement {index} obligation_types",
            )
    all_prohibitions = list(value.get("prohibition_constraints", []) or []) + [
        prohibition
        for item in preservation
        for prohibition in list(item.get("prohibition_constraints", []) or [])
    ]
    if len(_unique(all_prohibitions)) > MAX_PROHIBITIONS_PER_CONTRACT:
        raise ExecutionContractTooLargeError(
            EXECUTION_CONTRACT_TOO_LARGE,
            "combined structured prohibitions exceed the snapshot contract bound",
        )

    list_limits = {
        "requirement_ids": MAX_REQUIREMENTS_PER_CONTRACT,
        "impact_ids": MAX_SURFACES_PER_CONTRACT,
        "evidence_ids": MAX_REPOSITORY_FACTS_PER_CONTRACT,
        "surface_ids": MAX_SURFACES_PER_CONTRACT,
        "target_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "inspect_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "interface_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "target_new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "inspect_new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "interfaces_to_reuse": MAX_INTERFACES_PER_CONTRACT,
        "obligation_ids": MAX_SURFACES_PER_CONTRACT,
        "constraint_ids": MAX_PRESERVATION_PER_CONTRACT * 2,
        "verification_ids": MAX_TEST_CHECKS_PER_CONTRACT * 2,
        "source_node_ids": MAX_PLAN_NODES,
        "local_preservation_constraints": MAX_PRESERVATION_PER_CONTRACT,
        "preservation_constraints": MAX_PRESERVATION_PER_CONTRACT,
        "prohibition_constraints": MAX_PROHIBITIONS_PER_CONTRACT,
        "local_test_contract": MAX_TEST_CHECKS_PER_CONTRACT,
        "test_contract": MAX_TEST_CHECKS_PER_CONTRACT,
        "done_when": MAX_DONE_WHEN_PER_CONTRACT,
        "dependencies": MAX_DEPENDENCIES_PER_CONTRACT,
        "do_not_touch": MAX_SURFACES_PER_CONTRACT,
        "candidate_targets": MAX_SURFACES_PER_CONTRACT,
        "target_paths": MAX_SURFACES_PER_CONTRACT,
        "inspect_targets": MAX_SURFACES_PER_CONTRACT,
        "parent_scopes": MAX_SURFACES_PER_CONTRACT,
    }
    path_fields = {
        "candidate_targets", "target_paths", "inspect_targets", "parent_scopes", "do_not_touch",
    }
    for index, node in enumerate(nodes, 1):
        if not isinstance(node, dict):
            raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, f"plan node {index} must be an object")
        _require_authority_text(node.get("node_id"), 120, f"plan node {index} node_id")
        _require_authority_text(node.get("goal"), MAX_TEXT_CHARS, f"plan node {index} goal")
        _require_authority_text(node.get("objective"), MAX_TEXT_CHARS, f"plan node {index} objective")
        for field in ("current_owner", "impact_kind", "necessity_status", "disposition", "provenance"):
            _require_authority_text(node.get(field), MAX_TEXT_CHARS, f"plan node {index} {field}")
        if "closure_metadata" in node and len(_json(node.get("closure_metadata"))) > MAX_TEXT_CHARS * 2:
            raise ExecutionContractTooLargeError(
                EXECUTION_CONTRACT_TOO_LARGE,
                f"plan node {index} closure_metadata is too large",
            )
        for field, limit in list_limits.items():
            if field not in node:
                continue
            _require_authority_list(node.get(field), limit, f"plan node {index} {field}")
            for item_index, item in enumerate(node.get(field) or [], 1):
                if field in path_fields:
                    _require_authority_text(item, MAX_PATH_CHARS, f"plan node {index} {field}[{item_index}]")
                elif isinstance(item, str):
                    _require_authority_text(item, MAX_TEXT_CHARS, f"plan node {index} {field}[{item_index}]")
        _require_authority_list(node.get("new_surface_proposals"), MAX_SNAPSHOT_PROPOSALS, f"plan node {index} new_surface_proposals")
        for item_index, proposal in enumerate(node.get("new_surface_proposals") or [], 1):
            if len(_json(proposal)) > MAX_TEXT_CHARS * 2:
                raise ExecutionContractTooLargeError(
                    EXECUTION_CONTRACT_TOO_LARGE,
                    f"plan node {index} new_surface_proposals[{item_index}] is too large",
                )
    for index, item in enumerate(source_requirements, 1):
        if isinstance(item, dict):
            _require_authority_text(item.get("requirement_id"), 120, f"requirement {index} id")
            _require_authority_text(item.get("text"), MAX_REQUIREMENT_TEXT_CHARS, f"requirement {index} text")
    for index, item in enumerate(preservation, 1):
        if not isinstance(item, dict):
            raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, f"preservation surface {index} must be an object")
        _require_authority_list(item.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT, f"preservation surface {index} requirement_ids")
        _require_authority_list(item.get("evidence_ids"), MAX_REPOSITORY_FACTS_PER_CONTRACT, f"preservation surface {index} evidence_ids")
        _require_authority_list(item.get("preservation_constraints"), MAX_PRESERVATION_PER_CONTRACT, f"preservation surface {index} preservation_constraints")
        _require_authority_list(item.get("prohibition_constraints"), MAX_PROHIBITIONS_PER_CONTRACT, f"preservation surface {index} prohibition_constraints")
        _require_authority_text(item.get("path"), MAX_PATH_CHARS, f"preservation surface {index} path")
        _require_authority_text(item.get("reason"), MAX_TEXT_CHARS, f"preservation surface {index} reason")
        _require_authority_text(item.get("component"), 180, f"preservation surface {index} component")
        for field in ("preservation_constraints", "prohibition_constraints"):
            for item_index, value_item in enumerate(item.get(field, []) or [], 1):
                _require_authority_text(
                    value_item, MAX_TEXT_CHARS,
                    f"preservation surface {index} {field}[{item_index}]",
                )
        preservation_constraints = list(item.get("preservation_constraints", []) or [])
        if item.get("reason"):
            preservation_constraints.append(item.get("reason"))
        if len(_unique(preservation_constraints)) > MAX_PRESERVATION_PER_CONTRACT:
            raise ExecutionContractTooLargeError(
                EXECUTION_CONTRACT_TOO_LARGE,
                f"preservation surface {index} combined constraints exceed the contract bound",
            )

    # Only evidence that is actually referenced by approved plan authority is
    # copied into the task snapshot.  Unrelated repository facts remain out.
    referenced_evidence = {
        str(evidence_id)
        for node in nodes
        for evidence_id in list(node.get("evidence_ids", []) or [])
    }
    referenced_evidence.update(
        str(evidence_id)
        for item in preservation
        for evidence_id in list(item.get("evidence_ids", []) or [])
    )
    _require_authority_list(list(referenced_evidence), MAX_SNAPSHOT_EVIDENCE, "canonical evidence references")
    available_evidence = {
        str(item.get("evidence_id")) for item in list(evidence or [])
        if isinstance(item, dict) and item.get("evidence_id")
    }
    if available_evidence and referenced_evidence - available_evidence:
        raise ExecutionContractError(
            EXECUTION_CONTRACT_BLOCKED,
            "approved plan references repository evidence that is not available",
            details=sorted(referenced_evidence - available_evidence),
        )
    for index, item in enumerate(list(evidence or []), 1):
        if not isinstance(item, dict) or str(item.get("evidence_id")) not in referenced_evidence:
            continue
        _require_authority_text(item.get("path"), MAX_PATH_CHARS, f"evidence {index} path")
        _require_authority_text(item.get("fact"), 360, f"evidence {index} fact")
        _require_authority_text(item.get("symbol") or item.get("component"), 180, f"evidence {index} symbol")

    # Registry records are already bounded by Stage 3, but any referenced
    # surface still has to fit the execution snapshot without truncation.
    referenced_surfaces = {
        str(surface_id)
        for node in nodes
        for surface_id in (
            list(node.get("surface_ids", []) or [])
            + list(node.get("target_surface_ids", []) or [])
            + list(node.get("inspect_surface_ids", []) or [])
            + list(node.get("interface_surface_ids", []) or [])
        )
    }
    referenced_surfaces.update(str(item.get("surface_id") or item.get("canonical_surface_id")) for item in preservation)
    referenced_surfaces.update(str(surface_id) for surface_id in list(value.get("do_not_touch_surface_ids", []) or []))
    if isinstance(registry, dict):
        for index, item in enumerate(registry.get("surfaces", []) or [], 1):
            surface_id = str(item.get("surface_id") or item.get("canonical_surface_id")) if isinstance(item, dict) else ""
            if surface_id not in referenced_surfaces:
                continue
            _require_authority_text(item.get("kind"), 80, f"surface {index} kind")
            _require_authority_text(item.get("role"), 100, f"surface {index} role")
            _require_authority_text(item.get("path"), MAX_PATH_CHARS, f"surface {index} path")
            _require_authority_text(item.get("symbol") or item.get("component"), 180, f"surface {index} symbol")
            _require_authority_list(item.get("symbols"), 8, f"surface {index} symbols")
            _require_authority_list(item.get("evidence_ids"), MAX_REPOSITORY_FACTS_PER_CONTRACT, f"surface {index} evidence_ids")
            for item_index, symbol in enumerate(item.get("symbols", []) or [], 1):
                _require_authority_text(symbol, 180, f"surface {index} symbols[{item_index}]")
    surface_evidence = {}
    for item in (registry or {}).get("surfaces", []) if isinstance(registry, dict) else []:
        if isinstance(item, dict):
            surface_evidence.setdefault(str(item.get("surface_id") or item.get("canonical_surface_id")), [])
            surface_evidence[str(item.get("surface_id") or item.get("canonical_surface_id"))].extend(item.get("evidence_ids", []) or [])
    for node in nodes:
        for surface_id in (
            list(node.get("surface_ids", []) or [])
            + list(node.get("target_surface_ids", []) or [])
            + list(node.get("inspect_surface_ids", []) or [])
            + list(node.get("interface_surface_ids", []) or [])
        ):
            surface_evidence.setdefault(str(surface_id), []).extend(node.get("evidence_ids", []) or [])
    for surface_id, values in surface_evidence.items():
        if surface_id in referenced_surfaces:
            _require_authority_list(
                _unique(values), MAX_REPOSITORY_FACTS_PER_CONTRACT,
                f"surface {surface_id} combined evidence_ids",
            )
    _require_authority_list(list(referenced_surfaces), MAX_SNAPSHOT_SURFACES, "canonical surface references")


def _text(value, limit=MAX_TEXT_CHARS):
    value = " ".join(str(value or "").split())
    limit = max(1, int(limit))
    return value if len(value) <= limit else value[: max(0, limit - 3)] + "..."


def _path(value):
    value = str(value or "").replace("\\", "/").strip()
    return value.lstrip("./") if value.startswith("./") else value


def _unique(values, *, limit=None, text_limit=MAX_TEXT_CHARS, sort=False):
    result = []
    seen = set()
    for value in list(values or []):
        if value in (None, "", [], {}):
            continue
        item = (
            _text(value, text_limit)
            if isinstance(value, str) and text_limit is not None
            else value
        )
        key = json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    if sort:
        result.sort(key=lambda item: str(item))
    return result[:limit] if limit is not None else result


def _ids(values, limit=None):
    # IDs are authority, not prose.  Count/serialized bounds reject overflow;
    # no ID is shortened during a snapshot or contract projection.
    return _unique([str(value).strip() for value in list(values or [])], limit=limit, text_limit=None)


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _serialized_chars(value):
    """Count the stable human-readable JSON artifact used for evidence."""
    return len(json.dumps(value, ensure_ascii=False, default=str))


def deterministic_hash(value):
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _without(value, *keys):
    result = _copy(value if isinstance(value, dict) else {})
    for key in keys:
        result.pop(key, None)
    return result


def approval_record_hash(approval):
    """Hash only stable approval authority, excluding the display timestamp."""
    value = approval if isinstance(approval, dict) else {}
    stable = {
        key: _copy(value.get(key)) for key in (
            "approval_status", "status", "plan_id", "plan_hash", "approval_source",
            "user_revision", "approval_record_hash",
        ) if value.get(key) not in (None, "", [], {})
    }
    stable.pop("approval_record_hash", None)
    return deterministic_hash(stable)


def _approval_status(approval):
    value = approval if isinstance(approval, dict) else {}
    return str(value.get("approval_status") or value.get("status") or "").upper()


def validate_approved_plan(plan, approval, authoritative_task_goal=None, current_plan=None):
    """Validate the user approval against the exact current Stage 3 plan."""
    value = plan if isinstance(plan, dict) else {}
    approved = approval if isinstance(approval, dict) else {}
    current = current_plan if isinstance(current_plan, dict) else value
    errors = []
    status = _approval_status(approved)
    if status != "APPROVED":
        errors.append("approval status is not APPROVED")
        return {
            "valid": False, "code": PLAN_APPROVAL_REQUIRED,
            "status": status or "MISSING", "errors": errors,
            "plan_id": value.get("plan_id"), "plan_hash": value.get("plan_hash"),
        }
    if not value.get("plan_id") or not value.get("plan_hash"):
        errors.append("approved plan identity is incomplete")
    if approved.get("plan_id") != value.get("plan_id"):
        errors.append("approval plan_id does not match current plan")
    if approved.get("plan_hash") != value.get("plan_hash"):
        errors.append("approval plan_hash does not match current plan")
    try:
        current_hash = stage3.plan_content_hash(current)
    except Exception as exc:  # pragma: no cover - defensive envelope guard
        current_hash = ""
        errors.append(f"current plan hash could not be computed: {exc}")
    if current.get("plan_hash") != current_hash:
        errors.append("current canonical plan hash is invalid")
    if value is not current and (
        value.get("plan_id") != current.get("plan_id") or
        value.get("plan_hash") != current.get("plan_hash") or
        stage3.plan_content_hash(value) != current_hash
    ):
        errors.append("approved plan is stale relative to the current canonical plan")
    if authoritative_task_goal is not None and value.get("task_goal") != authoritative_task_goal:
        errors.append("approved plan task goal does not match the authoritative Stage 3 goal")
    if errors:
        code = APPROVED_PLAN_STALE if any(
            phrase in " ".join(errors)
            for phrase in ("hash", "stale", "plan_id", "plan_hash")
        ) else EXECUTION_CONTRACT_BLOCKED
        return {
            "valid": False, "code": code, "status": status,
            "errors": errors[:20], "plan_id": value.get("plan_id"),
            "plan_hash": value.get("plan_hash"), "current_hash": current_hash,
        }
    return {
        "valid": True, "code": None, "status": status, "errors": [],
        "plan_id": value.get("plan_id"), "plan_hash": value.get("plan_hash"),
        "current_hash": current_hash, "approval_hash": approval_record_hash(approved),
    }


def _compact_evidence(evidence):
    result = []
    for item in list(evidence or []):
        if not isinstance(item, dict) or not item.get("evidence_id"):
            continue
        result.append({
            "evidence_id": str(item.get("evidence_id")),
            "category": _text(item.get("category"), 100),
            "fact": _text(item.get("fact"), 360),
            "path": _path(item.get("path")),
            "symbol": _text(item.get("symbol"), 180),
            "line_start": item.get("line_start"),
            "line_end": item.get("line_end"),
            "file_sha256": _text(item.get("file_sha256"), 80),
            "provenance": REPOSITORY_EVIDENCE,
        })
    return result


def _compact_surface(surface):
    value = surface if isinstance(surface, dict) else {}
    surface_id = value.get("surface_id") or value.get("canonical_surface_id")
    return {
        "surface_id": str(surface_id) if surface_id else None,
        "kind": _text(value.get("kind"), 80),
        "role": _text(value.get("role"), 100),
        "path": _path(value.get("path")),
        "symbol": _text(value.get("symbol") or value.get("component"), 180),
        "symbols": _unique(value.get("symbols"), text_limit=180),
        "evidence_ids": _ids(value.get("evidence_ids")),
        "provenance": REPOSITORY_EVIDENCE if value.get("evidence_ids") else APPROVED_PLAN,
    }


def _surface_records(plan, registry):
    records = {}
    if isinstance(registry, dict):
        for item in registry.get("surfaces", []) or []:
            compact = _compact_surface(item)
            if compact.get("surface_id"):
                records[str(compact["surface_id"])] = compact
    for node in list((plan or {}).get("approved_change_nodes", []) or []):
        if not isinstance(node, dict):
            continue
        ids = list(node.get("surface_ids", []) or []) + list(node.get("target_surface_ids", []) or [])
        ids += list(node.get("inspect_surface_ids", []) or []) + list(node.get("interface_surface_ids", []) or [])
        paths = list(node.get("candidate_targets", []) or []) + list(node.get("inspect_targets", []) or [])
        for index, surface_id in enumerate(ids):
            key = str(surface_id)
            current = records.get(key, {"surface_id": key, "evidence_ids": [], "symbols": [], "provenance": APPROVED_PLAN})
            if not current.get("path") and paths:
                current["path"] = _path(paths[0])
            if not current.get("symbol") and node.get("current_owner"):
                current["symbol"] = _text(node.get("current_owner"), 180)
            current["evidence_ids"] = _ids(list(current.get("evidence_ids", [])) + list(node.get("evidence_ids", []) or []))
            records[key] = current
        # A plan can be valid in compatibility mode without a canonical
        # registry.  Preserve its explicit paths as plan-authorized surfaces.
        if not ids:
            for path in paths:
                key = f"PATH:{_path(path)}"
                records.setdefault(key, {
                    "surface_id": key, "kind": "TEST" if "test" in _path(path).casefold() else "OTHER",
                    "role": "APPROVED_PLAN_SURFACE", "path": _path(path), "symbol": _text(node.get("current_owner"), 180),
                    "symbols": [], "evidence_ids": _ids(node.get("evidence_ids")), "provenance": APPROVED_PLAN,
                })
    return records


def _compact_node(node):
    value = node if isinstance(node, dict) else {}
    fields = (
        "node_id", "goal", "objective", "requirement_ids", "impact_ids", "evidence_ids",
        "surface_ids", "target_surface_ids", "inspect_surface_ids", "interface_surface_ids",
        "new_surface_proposal_ids", "target_new_surface_proposal_ids", "inspect_new_surface_proposal_ids",
        "new_surface_proposals", "parent_scopes", "current_owner", "interfaces_to_reuse",
        "candidate_targets", "target_paths", "inspect_targets", "mutation_required", "verification_only",
        "local_preservation_constraints", "preservation_constraints", "prohibition_constraints",
        "local_test_contract", "test_contract", "done_when", "dependencies", "do_not_touch",
        "impact_kind", "necessity_status", "disposition", "provenance", "closure_metadata",
    )
    result = {}
    for key in fields:
        if key not in value:
            continue
        item = value.get(key)
        if isinstance(item, str):
            result[key] = _text(item, MAX_TEXT_CHARS)
        elif key in {"candidate_targets", "target_paths", "inspect_targets", "parent_scopes", "do_not_touch"}:
            result[key] = _unique([_path(x) for x in item or []], text_limit=MAX_PATH_CHARS)
        elif isinstance(item, list):
            result[key] = _unique(item, text_limit=MAX_TEXT_CHARS)
        elif isinstance(item, dict):
            result[key] = _copy(item)
        else:
            result[key] = item
    return result


def _compact_requirement(item):
    value = item if isinstance(item, dict) else {}
    return {
        "requirement_id": str(value.get("requirement_id", "")),
        "text": _text(value.get("text"), MAX_REQUIREMENT_TEXT_CHARS),
        "provenance": value.get("provenance") or value.get("source_provenance") or SOURCE_REQUIREMENT,
        "status": str(value.get("status", "active")),
    }


def _requirement_records(plan, requirements):
    values = list((plan or {}).get("requirements", []) or [])
    if not values:
        values = list(requirements or [])
    result = []
    seen = set()
    for item in values:
        compact = _compact_requirement(item)
        if not compact["requirement_id"] or not compact["text"]:
            continue
        if compact["status"].casefold() in {"deferred", "cancelled", "canceled"}:
            continue
        if compact["requirement_id"] in seen:
            continue
        seen.add(compact["requirement_id"])
        result.append(compact)
    return result


def _obligation_records(plan, requirements):
    ledger = (plan or {}).get("requirement_obligation_ledger")
    if not isinstance(ledger, dict):
        ledger = stage3.build_requirement_obligation_ledger(requirements)
    by_id = {str(item.get("requirement_id")): item for item in ledger.get("requirements", []) or [] if isinstance(item, dict)}
    return [{
        "requirement_id": item["requirement_id"],
        "obligation_types": _ids(by_id.get(item["requirement_id"], {}).get("obligation_types", [])),
        "provenance": SOURCE_REQUIREMENT,
    } for item in _requirement_records(plan, requirements)]


def _preservation_records(plan):
    value = plan if isinstance(plan, dict) else {}
    constraints = value.get("canonical_constraints")
    constraint_by_id = {}
    if isinstance(constraints, dict):
        constraint_by_id = {
            str(item.get("constraint_id")): item
            for item in constraints.get("preservation", []) or []
            if isinstance(item, dict) and item.get("constraint_id")
        }
    records = []
    for item in list(value.get("preservation_only_surfaces", []) or []):
        if not isinstance(item, dict):
            continue
        shared_constraints = [
            constraint_by_id[str(identifier)].get("text")
            for identifier in item.get("constraint_ids", []) or []
            if str(identifier) in constraint_by_id
        ]
        shared_prohibitions = {
            str(entry.get("constraint_id")): entry
            for entry in (constraints or {}).get("prohibitions", []) or []
            if isinstance(entry, dict) and entry.get("constraint_id")
        } if isinstance(constraints, dict) else {}
        shared_prohibition_text = [
            shared_prohibitions[str(identifier)].get("text")
            for identifier in item.get("constraint_ids", []) or []
            if str(identifier) in shared_prohibitions
        ]
        records.append({
            "surface_id": item.get("surface_id") or item.get("canonical_surface_id"),
            "path": _path(item.get("path")),
            "component": _text(item.get("component"), 180),
            "requirement_ids": _ids(item.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT),
            "evidence_ids": _ids(item.get("evidence_ids"), MAX_REPOSITORY_FACTS_PER_CONTRACT),
            "constraints": _unique(
                shared_constraints
                + list(item.get("preservation_constraints", []) or [])
                + ([item.get("reason")] if item.get("reason") else []),
                text_limit=MAX_TEXT_CHARS,
            ),
            "prohibitions": _unique(
                shared_prohibition_text + list(item.get("prohibition_constraints", []) or []),
                text_limit=MAX_TEXT_CHARS,
            ),
            "provenance": APPROVED_PLAN,
        })
    return records


def _snapshot_authority(plan, approval, authoritative_task_goal, requirements, evidence, registry,
                        authority_binding=None):
    nodes = [_compact_node(item) for item in list((plan or {}).get("approved_change_nodes", []) or [])]
    surfaces = _surface_records(plan, registry)
    referenced_surface_ids = {
        str(surface_id)
        for node in nodes
        for surface_id in (
            list(node.get("surface_ids", []) or [])
            + list(node.get("target_surface_ids", []) or [])
            + list(node.get("inspect_surface_ids", []) or [])
            + list(node.get("interface_surface_ids", []) or [])
        )
    }
    referenced_surface_ids.update(
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in list((plan or {}).get("preservation_only_surfaces", []) or [])
        if isinstance(item, dict)
    )
    referenced_surface_ids.update(
        str(surface_id) for surface_id in list((plan or {}).get("do_not_touch_surface_ids", []) or [])
    )
    canonical_verifications = list((plan or {}).get("canonical_verification_contracts", []) or [])
    referenced_surface_ids.update(
        str(surface_id)
        for item in canonical_verifications
        if isinstance(item, dict)
        for surface_id in item.get("surface_ids", []) or []
    )
    if referenced_surface_ids:
        surfaces = {
            key: item for key, item in surfaces.items()
            if str(key) in referenced_surface_ids
        }
    reqs = _requirement_records(plan, requirements)
    req_ids = {item["requirement_id"] for item in reqs}
    mutations, tests, reuse = [], [], []
    for node in nodes:
        target = bool(node.get("mutation_required")) and not bool(node.get("verification_only"))
        if target:
            mutations.append({"node_id": node.get("node_id"), "surface_ids": _ids(node.get("target_surface_ids") or node.get("surface_ids")), "paths": _unique([_path(x) for x in node.get("candidate_targets", [])], text_limit=MAX_PATH_CHARS), "requirement_ids": _ids(node.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT)})
        if str(node.get("impact_kind", "")).upper() == "TEST_CHANGE" or str(node.get("disposition", "")).upper() == "TEST_CHANGE":
            tests.append({"node_id": node.get("node_id"), "surface_ids": _ids(node.get("target_surface_ids") or node.get("surface_ids")), "paths": _unique([_path(x) for x in node.get("candidate_targets", [])], text_limit=MAX_PATH_CHARS), "requirement_ids": _ids(node.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT)})
        if (not target and not (str(node.get("impact_kind", "")).upper() == "TEST_CHANGE")) or str(node.get("disposition", "")).upper() in {"INTERFACE_REUSE", "VERIFY_ONLY"}:
            reuse.append({"node_id": node.get("node_id"), "surface_ids": _ids(node.get("inspect_surface_ids") or node.get("surface_ids")), "paths": _unique([_path(x) for x in node.get("inspect_targets", [])], text_limit=MAX_PATH_CHARS), "interfaces": _unique(node.get("interfaces_to_reuse"), limit=MAX_INTERFACES_PER_CONTRACT, text_limit=MAX_TEXT_CHARS), "requirement_ids": _ids(node.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT)})
    preservation = _preservation_records(plan)
    do_not_touch_surface_ids = _ids((plan or {}).get("do_not_touch_surface_ids"), MAX_SURFACES_PER_CONTRACT)
    do_not_touch_paths = _unique([_path(x) for x in (plan or {}).get("do_not_touch", [])], limit=MAX_SURFACES_PER_CONTRACT, text_limit=MAX_PATH_CHARS)
    structured_prohibitions = _unique(
        list((plan or {}).get("prohibition_constraints", []) or [])
        + [value for item in preservation for value in item.get("prohibitions", [])],
        limit=MAX_PROHIBITIONS_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
    )
    canonical_constraints = (plan or {}).get("canonical_constraints")
    if isinstance(canonical_constraints, dict):
        structured_prohibitions = _unique(
            structured_prohibitions
            + [item.get("text") for item in canonical_constraints.get("prohibitions", []) or []
               if isinstance(item, dict)],
            limit=MAX_PROHIBITIONS_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
        )
    evidence_records = _compact_evidence(evidence)
    known_evidence = {item["evidence_id"] for item in evidence_records}
    evidence_ids = _ids(
        [item for node in nodes for item in node.get("evidence_ids", [])]
        + [item for record in preservation for item in record.get("evidence_ids", [])],
        MAX_SNAPSHOT_EVIDENCE,
    )
    evidence_ids = _ids(
        evidence_ids
        + [evidence_id for item in canonical_verifications if isinstance(item, dict)
           for evidence_id in item.get("evidence_ids", []) or []],
        MAX_SNAPSHOT_EVIDENCE,
    )
    evidence_ids = [item for item in evidence_ids if item in known_evidence or not evidence_records]
    approval_record = {
        key: _copy(approval.get(key)) for key in (
            "approval_status", "plan_id", "plan_hash", "approval_source",
            "user_revision", "approved_at",
        ) if approval.get(key) not in (None, "", [], {})
    }
    approval_record.setdefault("approval_status", _approval_status(approval))
    authority = {
        "schema_version": "4A",
        "plan_id": plan.get("plan_id"),
        "plan_hash": plan.get("plan_hash"),
        "approval": {
            "approval_status": _approval_status(approval),
            "plan_id": approval.get("plan_id"),
            "plan_hash": approval.get("plan_hash"),
            "approval_source": approval.get("approval_source"),
        },
        "approval_record": approval_record,
        "approval_hash": approval_record_hash(approval_record),
        "task_goal": authoritative_task_goal if authoritative_task_goal is not None else plan.get("task_goal"),
        "requirements": reqs,
        "requirement_ids": _ids([item["requirement_id"] for item in reqs], MAX_SNAPSHOT_REQUIREMENTS),
        "obligations": _obligation_records(plan, reqs),
        "plan_nodes": nodes,
        "canonical_mutation_surfaces": mutations,
        "canonical_test_surfaces": tests,
        "canonical_reuse_surfaces": reuse,
        "preservation_only_surfaces": preservation,
        "global_do_not_touch_surface_ids": do_not_touch_surface_ids,
        "global_do_not_touch": do_not_touch_paths,
        "structured_prohibitions": structured_prohibitions,
        "integration_contract": _unique((plan or {}).get("integration_verification"), limit=MAX_TEST_CHECKS_PER_CONTRACT, text_limit=MAX_TEXT_CHARS),
        "canonical_evidence_ids": evidence_ids,
        "canonical_evidence": [item for item in evidence_records if item["evidence_id"] in set(evidence_ids)],
        "canonical_surfaces": [surfaces[key] for key in sorted(surfaces)],
        "new_surface_proposals": _unique((plan or {}).get("new_surface_proposals"), limit=MAX_SNAPSHOT_PROPOSALS, text_limit=MAX_TEXT_CHARS),
        "provenance": {
            "plan": APPROVED_PLAN, "repository_evidence": REPOSITORY_EVIDENCE,
            "source_requirements": SOURCE_REQUIREMENT,
            "derived_contract": DERIVED_EXECUTION_CONTRACT,
        },
    }
    # V24.4.5 canonical plans keep repeated preservation and verification
    # material in shared, referenced catalogs.  Carry those catalogs into
    # the immutable execution snapshot so Stage 4 contract compilation has
    # the same authority and test context as the expanded legacy projection.
    if isinstance(plan.get("canonical_constraints"), dict):
        authority["canonical_constraints"] = _copy(plan.get("canonical_constraints"))
    if isinstance(plan.get("canonical_verification_contracts"), list):
        authority["canonical_verification_contracts"] = _copy(
            plan.get("canonical_verification_contracts")
        )
    # Stage 6C-A adds an exact approval proof to the immutable Stage 4
    # snapshot.  The field is optional so the historical V19--V24 APIs keep
    # their original contract shape and compatibility behavior.
    if isinstance(authority_binding, dict):
        authority["approval_binding"] = _copy(authority_binding)
    return authority


def validate_snapshot(snapshot, plan=None, approval=None, authoritative_task_goal=None):
    value = snapshot if isinstance(snapshot, dict) else {}
    errors = []
    if value.get("schema_version") != "4A":
        errors.append("snapshot schema_version must be 4A")
    allowed_top_level = {
        "schema_version", "plan_id", "plan_hash", "approval", "approval_record",
        "approval_hash", "task_goal", "requirements", "requirement_ids", "obligations",
        "plan_nodes", "canonical_mutation_surfaces", "canonical_test_surfaces",
        "canonical_reuse_surfaces", "preservation_only_surfaces",
        "global_do_not_touch_surface_ids", "global_do_not_touch", "structured_prohibitions",
        "integration_contract", "canonical_evidence_ids", "canonical_evidence",
        "canonical_surfaces", "new_surface_proposals", "provenance", "bounds",
        "canonical_constraints", "canonical_verification_contracts",
        "approval_binding",
        "snapshot_hash", "immutable",
    }
    errors.extend(
        f"snapshot contains unapproved field: {key}" for key in value
        if key not in allowed_top_level
    )
    if value.get("immutable") is not True:
        errors.append("snapshot must be marked immutable")
    if not value.get("plan_id") or not value.get("plan_hash"):
        errors.append("snapshot plan identity is required")
    if _approval_status(value.get("approval")) != "APPROVED":
        errors.append("snapshot approval status is not APPROVED")
    snapshot_approval = value.get("approval") if isinstance(value.get("approval"), dict) else {}
    if snapshot_approval.get("plan_id") != value.get("plan_id"):
        errors.append("snapshot approval plan_id does not match snapshot")
    if snapshot_approval.get("plan_hash") != value.get("plan_hash"):
        errors.append("snapshot approval plan_hash does not match snapshot")
    if not isinstance(value.get("approval_record"), dict) or not value.get("approval_hash"):
        errors.append("snapshot approval record/hash is required")
    snapshot_record = value.get("approval_record") if isinstance(value.get("approval_record"), dict) else {}
    for field in ("approval_status", "plan_id", "plan_hash", "approval_source"):
        if field in snapshot_record and snapshot_record.get(field) != snapshot_approval.get(field):
            errors.append(f"snapshot approval_record {field} does not match approval")
    if authoritative_task_goal is not None and value.get("task_goal") != authoritative_task_goal:
        errors.append("snapshot task goal does not match authoritative goal")
    if isinstance(plan, dict) and isinstance(approval, dict):
        approval_result = validate_approved_plan(plan, approval, authoritative_task_goal)
        if not approval_result["valid"]:
            errors.extend(approval_result.get("errors", []))
        if value.get("plan_id") != plan.get("plan_id") or value.get("plan_hash") != plan.get("plan_hash"):
            errors.append("snapshot identity does not match approved plan")
    snapshot_limits = {
        "plan_nodes": MAX_PLAN_NODES,
        "requirements": MAX_SNAPSHOT_REQUIREMENTS,
        "requirement_ids": MAX_SNAPSHOT_REQUIREMENTS,
        "canonical_evidence_ids": MAX_SNAPSHOT_EVIDENCE,
        "canonical_evidence": MAX_SNAPSHOT_EVIDENCE,
        "canonical_surfaces": MAX_SNAPSHOT_SURFACES,
        "global_do_not_touch": MAX_SURFACES_PER_CONTRACT,
        "global_do_not_touch_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "structured_prohibitions": MAX_PROHIBITIONS_PER_CONTRACT,
        "integration_contract": MAX_TEST_CHECKS_PER_CONTRACT,
        "new_surface_proposals": MAX_SNAPSHOT_PROPOSALS,
        "preservation_only_surfaces": MAX_PLAN_NODES,
        "canonical_verification_contracts": MAX_TEST_CHECKS_PER_CONTRACT * 2,
    }
    list_fields = set(snapshot_limits) | {
        "canonical_mutation_surfaces", "canonical_test_surfaces", "canonical_reuse_surfaces",
        "obligations", "canonical_verification_contracts",
    }
    for field in list_fields:
        if field in value and not isinstance(value.get(field), list):
            errors.append(f"snapshot {field} must be a list")
    for field, limit in snapshot_limits.items():
        values = value.get(field)
        if isinstance(values, list) and len(values) > limit:
            errors.append(f"snapshot {field} bound exceeded ({len(values)} > {limit})")
    canonical_constraints = value.get("canonical_constraints")
    if canonical_constraints is not None and not isinstance(canonical_constraints, dict):
        errors.append("snapshot canonical_constraints must be an object")
    elif isinstance(canonical_constraints, dict):
        for field in ("preservation", "prohibitions"):
            records = canonical_constraints.get(field, [])
            if not isinstance(records, list):
                errors.append(f"snapshot canonical_constraints.{field} must be a list")
            elif len(records) > (MAX_PRESERVATION_PER_CONTRACT * 2 if field == "preservation" else MAX_PROHIBITIONS_PER_CONTRACT * 2):
                errors.append(f"snapshot canonical_constraints.{field} bound exceeded")
    plan_nodes = value.get("plan_nodes", [])
    if isinstance(plan_nodes, list):
        node_ids = []
        for index, item in enumerate(plan_nodes, 1):
            if not isinstance(item, dict) or not item.get("node_id"):
                errors.append(f"snapshot plan_nodes[{index}] must carry node_id")
            else:
                node_ids.append(str(item.get("node_id")))
        if len(node_ids) != len(set(node_ids)):
            errors.append("snapshot plan_nodes contain duplicate node_id")
    for field, id_key in (
        ("requirements", "requirement_id"),
        ("canonical_evidence", "evidence_id"),
        ("canonical_surfaces", "surface_id"),
    ):
        values = value.get(field, [])
        if not isinstance(values, list):
            continue
        ids = []
        for index, item in enumerate(values, 1):
            if not isinstance(item, dict) or not item.get(id_key):
                errors.append(f"snapshot {field}[{index}] must carry {id_key}")
            else:
                ids.append(str(item.get(id_key)))
        if len(ids) != len(set(ids)):
            errors.append(f"snapshot {field} contain duplicate {id_key}")
    expected_hash = deterministic_hash(_without(value, "snapshot_hash", "immutable"))
    if value.get("snapshot_hash") != expected_hash:
        errors.append("snapshot hash does not match snapshot content")
    approval_binding = value.get("approval_binding") if isinstance(value.get("approval_binding"), dict) else {}
    if approval_binding:
        bound_plan_hash = approval_binding.get("approved_plan_hash") or approval_binding.get("canonical_plan_hash")
        bound_plan_id = approval_binding.get("approved_plan_id") or approval_binding.get("canonical_plan_id")
        if bound_plan_hash and bound_plan_hash != value.get("plan_hash"):
            errors.append("snapshot approval binding plan hash does not match snapshot")
        if bound_plan_id and bound_plan_id != value.get("plan_id"):
            errors.append("snapshot approval binding plan id does not match snapshot")
    def scan(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).casefold() in _RAW_FORBIDDEN_KEYS:
                    errors.append(f"forbidden raw Stage 3 field: {key}")
                scan(child)
        elif isinstance(item, list):
            for child in item:
                scan(child)
    scan(value)
    if isinstance(value.get("approval_record"), dict):
        expected_approval_hash = approval_record_hash(value["approval_record"])
        if value.get("approval_hash") != expected_approval_hash:
            errors.append("snapshot approval hash does not match approval_record")
    if len(_json(value)) > MAX_SNAPSHOT_CHARS:
        errors.append("snapshot serialized-size bound exceeded")
    return {"valid": not errors, "errors": errors[:20], "serialized_chars": len(_json(value))}


def create_approved_plan_snapshot(plan, approval, authoritative_task_goal=None,
                                  requirements=None, repository_evidence=None,
                                  canonical_surface_registry=None,
                                  authority_binding=None):
    """Create a frozen, whitelisted snapshot only after approval validation."""
    validation = validate_approved_plan(plan, approval, authoritative_task_goal)
    if not validation["valid"]:
        raise ApprovedPlanSnapshotError(validation["code"], "; ".join(validation["errors"]), details=validation["errors"])
    _validate_plan_authority_bounds(
        plan, requirements or [], repository_evidence or [], canonical_surface_registry,
    )
    authority = _snapshot_authority(
        plan, approval, authoritative_task_goal, requirements or [],
        repository_evidence or [], canonical_surface_registry,
        authority_binding=authority_binding,
    )
    authority["bounds"] = {
        "max_execution_contracts": MAX_EXECUTION_CONTRACTS,
        "max_plan_nodes": MAX_PLAN_NODES,
        "max_snapshot_chars": MAX_SNAPSHOT_CHARS,
    }
    authority["snapshot_hash"] = deterministic_hash(authority)
    authority["immutable"] = True
    result = freeze(authority)
    checked = validate_snapshot(result, plan, approval, authoritative_task_goal)
    if not checked["valid"]:
        raise ApprovedPlanSnapshotError(EXECUTION_CONTRACT_BLOCKED, "; ".join(checked["errors"]), details=checked["errors"])
    return result


build_approved_plan_snapshot = create_approved_plan_snapshot
approved_plan_snapshot = create_approved_plan_snapshot
validate_approved_plan_snapshot = validate_snapshot


def snapshot_is_current(snapshot, plan, approval, authoritative_task_goal=None):
    if not isinstance(snapshot, dict):
        return False
    return validate_snapshot(snapshot, plan, approval, authoritative_task_goal).get("valid", False)


def _surface_by_id(snapshot):
    return {str(item.get("surface_id")): item for item in (snapshot or {}).get("canonical_surfaces", []) or [] if isinstance(item, dict) and item.get("surface_id")}


def _node_by_id(snapshot):
    return {str(item.get("node_id")): item for item in (snapshot or {}).get("plan_nodes", []) or [] if isinstance(item, dict) and item.get("node_id")}


def _node_type(node):
    value = node if isinstance(node, dict) else {}
    if bool(value.get("mutation_required")) and not bool(value.get("verification_only")):
        if str(value.get("impact_kind", "")).upper() == "TEST_CHANGE" or str(value.get("disposition", "")).upper() == "TEST_CHANGE":
            return TEST_MUTATION
        return MUTATION
    if str(value.get("impact_kind", "")).upper() == "TEST_CHANGE" or str(value.get("disposition", "")).upper() == "TEST_CHANGE":
        return TEST_MUTATION if value.get("candidate_targets") else VERIFY_ONLY
    if str(value.get("impact_kind", "")).upper() == "INTERFACE_REUSE" or str(value.get("disposition", "")).upper() == "INTERFACE_REUSE":
        return INTERFACE_REUSE
    return VERIFY_ONLY


def _node_paths(node, field):
    return [_path(item) for item in list((node or {}).get(field, []) or []) if _path(item)]


def _matching_preservation(snapshot, requirement_ids):
    wanted = set(str(item) for item in requirement_ids)
    result = []
    for item in (snapshot or {}).get("preservation_only_surfaces", []) or []:
        refs = set(str(value) for value in item.get("requirement_ids", []) or [])
        if not wanted or not refs or wanted.intersection(refs):
            result.append(item)
    return result


def _surface_paths(snapshot, surface_ids):
    by_id = _surface_by_id(snapshot)
    return [_path(by_id[item].get("path")) for item in surface_ids if item in by_id and _path(by_id[item].get("path"))]


def _contract_requirements(snapshot, ids):
    by_id = {str(item.get("requirement_id")): item for item in (snapshot or {}).get("requirements", []) or []}
    return [by_id[item] for item in ids if item in by_id]


def _contract_evidence(snapshot, evidence_ids):
    by_id = {str(item.get("evidence_id")): item for item in (snapshot or {}).get("canonical_evidence", []) or []}
    return [by_id[item] for item in evidence_ids if item in by_id]


def _ensure_limit(value, limit, label):
    if len(value) > limit:
        raise ExecutionContractTooLargeError(
            EXECUTION_CONTRACT_TOO_LARGE,
            f"{label} bound exceeded ({len(value)} > {limit})",
        )
    return value


def _validate_contract_bounds(contract):
    """Validate all contract authority fields without dropping overflow."""
    value = contract if isinstance(contract, dict) else {}
    limits = {
        "plan_node_ids": MAX_PLAN_NODES,
        "owned_plan_node_ids": MAX_PLAN_NODES,
        "attached_plan_node_ids": MAX_PLAN_NODES,
        "requirement_ids": MAX_REQUIREMENTS_PER_CONTRACT,
        "obligation_types": MAX_OBLIGATION_TYPES_PER_CONTRACT,
        "impact_ids": MAX_SURFACES_PER_CONTRACT,
        "canonical_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "repository_evidence_ids": MAX_REPOSITORY_FACTS_PER_CONTRACT,
        "allowed_mutation_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "allowed_mutation_paths": MAX_SURFACES_PER_CONTRACT,
        "allowed_inspection_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "allowed_inspection_paths": MAX_SURFACES_PER_CONTRACT,
        "new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "target_new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "inspect_new_surface_proposal_ids": MAX_SNAPSHOT_PROPOSALS,
        "approved_new_surface_parent_scopes": MAX_SURFACES_PER_CONTRACT,
        "interface_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "interfaces_to_reuse": MAX_INTERFACES_PER_CONTRACT,
        "local_preservation_constraints": MAX_PRESERVATION_PER_CONTRACT,
        "structured_prohibitions": MAX_PROHIBITIONS_PER_CONTRACT,
        "global_do_not_touch_surface_ids": MAX_SURFACES_PER_CONTRACT,
        "global_do_not_touch": MAX_SURFACES_PER_CONTRACT,
        "test_contract": MAX_TEST_CHECKS_PER_CONTRACT,
        "integration_responsibility": MAX_TEST_CHECKS_PER_CONTRACT,
        "done_when": MAX_DONE_WHEN_PER_CONTRACT,
        "dependencies": MAX_DEPENDENCIES_PER_CONTRACT,
        "attached_preservation_surface_ids": MAX_PLAN_NODES,
        "execution_invariant_ids": invariant.MAX_INVARIANTS,
        "execution_invariant_relevant_ids": invariant.MAX_PROJECTED_INVARIANTS,
        "execution_invariants": invariant.MAX_PROJECTED_INVARIANTS,
    }
    for field, limit in limits.items():
        values = value.get(field, [])
        if not isinstance(values, list):
            raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, f"{field} must be a list")
        _ensure_limit(values, limit, field)
    for field in (
        "allowed_mutation_paths", "allowed_inspection_paths", "global_do_not_touch",
        "approved_new_surface_parent_scopes",
    ):
        for index, item in enumerate(value.get(field, []) or [], 1):
            _require_authority_text(item, MAX_PATH_CHARS, f"{field}[{index}]")
    for field in (
        "interfaces_to_reuse", "local_preservation_constraints", "structured_prohibitions",
        "test_contract", "integration_responsibility", "done_when",
    ):
        for index, item in enumerate(value.get(field, []) or [], 1):
            _require_authority_text(item, MAX_TEXT_CHARS, f"{field}[{index}]")
    _require_authority_text(value.get("goal"), MAX_TEXT_CHARS, "contract goal")
    return value


def _build_contract(snapshot, node, contract_id, responsibility_type, attached_nodes=None):
    node = node if isinstance(node, dict) else {}
    attached_nodes = [item for item in (attached_nodes or []) if isinstance(item, dict)]
    all_nodes = [node] + attached_nodes
    node_ids = _ids([item.get("node_id") for item in all_nodes])
    owned_ids = _ids([node.get("node_id")])
    requirement_ids = _ids([value for item in all_nodes for value in item.get("requirement_ids", [])])
    impact_ids = _ids([value for item in all_nodes for value in item.get("impact_ids", [])])
    evidence_ids = _ids([value for item in all_nodes for value in item.get("evidence_ids", [])])
    surface_ids = _ids([
        value for item in all_nodes for value in (
            list(item.get("surface_ids", []) or []) + list(item.get("target_surface_ids", []) or [])
            + list(item.get("inspect_surface_ids", []) or []) + list(item.get("interface_surface_ids", []) or [])
        )
    ])
    target_surface_ids = _ids([value for item in all_nodes for value in item.get("target_surface_ids", [])])
    inspect_surface_ids = _ids([value for item in all_nodes for value in item.get("inspect_surface_ids", [])])
    interface_surface_ids = _ids([value for item in all_nodes for value in item.get("interface_surface_ids", [])])
    new_surface_proposal_ids = _ids([
        value for item in all_nodes for value in (
            list(item.get("new_surface_proposal_ids", []) or [])
            + list(item.get("target_new_surface_proposal_ids", []) or [])
            + list(item.get("inspect_new_surface_proposal_ids", []) or [])
        )
    ], MAX_SNAPSHOT_PROPOSALS)
    target_new_surface_proposal_ids = _ids([
        value for item in all_nodes for value in item.get("target_new_surface_proposal_ids", []) or []
    ], MAX_SNAPSHOT_PROPOSALS)
    inspect_new_surface_proposal_ids = _ids([
        value for item in all_nodes for value in item.get("inspect_new_surface_proposal_ids", []) or []
    ], MAX_SNAPSHOT_PROPOSALS)
    new_surface_parent_scopes = _unique([
        _path(value) for item in all_nodes for value in item.get("parent_scopes", []) or []
    ], text_limit=MAX_PATH_CHARS)
    mutation_paths = _unique([_path(value) for item in all_nodes for value in item.get("candidate_targets", [])], text_limit=MAX_PATH_CHARS)
    inspection_paths = _unique(
        mutation_paths + [_path(value) for item in all_nodes for value in item.get("inspect_targets", [])]
        + _surface_paths(snapshot, inspect_surface_ids + interface_surface_ids),
        text_limit=MAX_PATH_CHARS,
    )
    mutation_paths += [value for value in _surface_paths(snapshot, target_surface_ids) if value not in mutation_paths]
    mutation_paths = _unique(mutation_paths, text_limit=MAX_PATH_CHARS)
    inspection_paths = _unique(mutation_paths + inspection_paths, text_limit=MAX_PATH_CHARS)
    if not mutation_paths and responsibility_type in {MUTATION, TEST_MUTATION}:
        for item in all_nodes:
            for proposal in item.get("new_surface_proposals", []) or []:
                parent_scope = _path(proposal.get("parent_scope")) if isinstance(proposal, dict) else ""
                if parent_scope:
                    mutation_paths.append(parent_scope)
        mutation_paths.extend(new_surface_parent_scopes)
        mutation_paths = _unique(mutation_paths, text_limit=MAX_PATH_CHARS)
        inspection_paths = _unique(mutation_paths + inspection_paths, text_limit=MAX_PATH_CHARS)
    attached_preservation = _matching_preservation(snapshot, requirement_ids)
    canonical_constraints = (snapshot or {}).get("canonical_constraints")
    shared_preservation = []
    shared_prohibitions = []
    if isinstance(canonical_constraints, dict):
        wanted_requirements = set(str(item) for item in requirement_ids)
        shared_preservation = [
            item.get("text") for item in canonical_constraints.get("preservation", []) or []
            if isinstance(item, dict) and item.get("text") and (
                not item.get("requirement_ids")
                or wanted_requirements.intersection(str(value) for value in item.get("requirement_ids", []))
            )
        ]
        shared_prohibitions = [
            item.get("text") for item in canonical_constraints.get("prohibitions", []) or []
            if isinstance(item, dict) and item.get("text") and (
                not item.get("requirement_ids")
                or wanted_requirements.intersection(str(value) for value in item.get("requirement_ids", []))
            )
        ]
    preservation = _unique(
        [value for item in all_nodes for value in (item.get("local_preservation_constraints", []) or item.get("preservation_constraints", []) or [])]
        + [value for item in attached_preservation for value in item.get("constraints", [])],
        # Shared canonical constraints are authority, not advice. They are
        # hydrated once here for the contract that owns the responsibility.
        text_limit=MAX_TEXT_CHARS,
    )
    preservation = _unique(
        preservation + shared_preservation,
        text_limit=MAX_TEXT_CHARS,
    )
    prohibitions = _unique(
        list((snapshot or {}).get("structured_prohibitions", []) or [])
        + [value for item in all_nodes for value in item.get("prohibition_constraints", [])]
        + [value for item in attached_preservation for value in item.get("prohibitions", [])],
        text_limit=MAX_TEXT_CHARS,
    )
    prohibitions = _unique(prohibitions + shared_prohibitions, text_limit=MAX_TEXT_CHARS)
    interfaces = _unique(
        [value for item in all_nodes for value in item.get("interfaces_to_reuse", [])]
        + [_surface_by_id(snapshot).get(item, {}).get("symbol") for item in interface_surface_ids],
        text_limit=MAX_TEXT_CHARS,
    )
    test_contract = _unique(
        [value for item in all_nodes for value in (item.get("local_test_contract", []) or item.get("test_contract", []) or [])],
        text_limit=MAX_TEXT_CHARS,
    )
    shared_verifications = (snapshot or {}).get("canonical_verification_contracts")
    if isinstance(shared_verifications, list):
        node_id_set = {str(item.get("node_id")) for item in all_nodes if item.get("node_id")}
        wanted_requirements = set(str(item) for item in requirement_ids)
        for verification in shared_verifications:
            if not isinstance(verification, dict):
                continue
            verification_requirements = {
                str(item) for item in verification.get("requirement_ids", []) or []
            }
            verification_nodes = {
                str(item) for item in verification.get("node_ids", []) or []
            }
            if (
                not wanted_requirements
                or not verification_requirements
                or wanted_requirements.intersection(verification_requirements)
                or node_id_set.intersection(verification_nodes)
            ):
                test_contract = _unique(
                    test_contract + list(verification.get("contract", []) or []),
                    text_limit=MAX_TEXT_CHARS,
                )
                evidence_ids = _ids(
                    evidence_ids + list(verification.get("evidence_ids", []) or []),
                    MAX_REPOSITORY_FACTS_PER_CONTRACT,
                )
                surface_ids = _ids(
                    surface_ids + list(verification.get("surface_ids", []) or []),
                )
                inspect_surface_ids = _ids(
                    inspect_surface_ids + list(verification.get("surface_ids", []) or []),
                )
        inspection_paths = _unique(
            inspection_paths + _surface_paths(snapshot, inspect_surface_ids),
            text_limit=MAX_PATH_CHARS,
        )
    done_when = _unique(
        [value for item in all_nodes for value in item.get("done_when", [])]
        or [node.get("goal")], text_limit=MAX_TEXT_CHARS,
    )
    if not test_contract and responsibility_type == TEST_MUTATION:
        test_contract = list(done_when)
    all_do_not_touch = _unique((snapshot or {}).get("global_do_not_touch"), limit=MAX_SURFACES_PER_CONTRACT, text_limit=MAX_PATH_CHARS)
    all_do_not_touch_surface_ids = _ids((snapshot or {}).get("global_do_not_touch_surface_ids"), MAX_SURFACES_PER_CONTRACT)
    contract = {
        "execution_contract_id": contract_id,
        "plan_id": snapshot.get("plan_id"), "plan_hash": snapshot.get("plan_hash"),
        "plan_node_ids": node_ids, "owned_plan_node_ids": owned_ids,
        "attached_plan_node_ids": _ids([item.get("node_id") for item in attached_nodes]),
        "goal": _text(node.get("goal") or node.get("objective") or "approved responsibility", MAX_TEXT_CHARS),
        "responsibility_type": responsibility_type,
        "worker_required": responsibility_type in {MUTATION, TEST_MUTATION},
        "requirement_ids": requirement_ids,
        "requirements": _contract_requirements(snapshot, requirement_ids),
        "obligation_types": _ids([value for item in (snapshot or {}).get("obligations", []) if item.get("requirement_id") in requirement_ids for value in item.get("obligation_types", [])]),
        "impact_ids": impact_ids,
        "canonical_surface_ids": surface_ids,
        "repository_evidence_ids": evidence_ids,
        "relevant_repository_facts": _contract_evidence(snapshot, evidence_ids),
        "allowed_mutation_surface_ids": target_surface_ids,
        "allowed_mutation_paths": mutation_paths,
        "allowed_inspection_surface_ids": _ids(target_surface_ids + inspect_surface_ids + interface_surface_ids),
        "allowed_inspection_paths": inspection_paths,
        "new_surface_proposal_ids": new_surface_proposal_ids,
        "target_new_surface_proposal_ids": target_new_surface_proposal_ids,
        "inspect_new_surface_proposal_ids": inspect_new_surface_proposal_ids,
        "approved_new_surface_parent_scopes": new_surface_parent_scopes,
        "interfaces_to_reuse": interfaces,
        "interface_surface_ids": interface_surface_ids,
        "local_preservation_constraints": preservation,
        "structured_prohibitions": prohibitions,
        "global_do_not_touch_surface_ids": all_do_not_touch_surface_ids,
        "global_do_not_touch": all_do_not_touch,
        "test_contract": test_contract,
        "integration_responsibility": _unique((snapshot or {}).get("integration_contract"), text_limit=MAX_TEXT_CHARS),
        "done_when": done_when,
        "dependencies": [],
        "provenance": APPROVED_PLAN,
        "derivation": DERIVED_EXECUTION_CONTRACT,
        "source_provenance": {
            "plan": APPROVED_PLAN, "requirements": SOURCE_REQUIREMENT,
            "repository_facts": REPOSITORY_EVIDENCE,
        },
        "attached_preservation_surface_ids": _ids([item.get("surface_id") for item in attached_preservation if item.get("surface_id")]),
    }
    _validate_contract_bounds(contract)
    contract["contract_hash"] = deterministic_hash(contract)
    if len(_json(contract)) > MAX_CONTRACT_CHARS:
        raise ExecutionContractTooLargeError(EXECUTION_CONTRACT_TOO_LARGE, f"{contract_id} serialized-size bound exceeded")
    return contract


def _compatible_reuse(node, contracts):
    node_refs = set(str(value) for value in node.get("requirement_ids", []) or [])
    node_interfaces = set(str(value) for value in node.get("interface_surface_ids", []) or [])
    node_paths = set(_node_paths(node, "inspect_targets"))
    scores = []
    for contract in contracts:
        if not contract.get("worker_required"):
            continue
        score = 0
        score += 8 * len(node_refs.intersection(contract.get("requirement_ids", [])))
        score += 12 * len(node_interfaces.intersection(contract.get("interface_surface_ids", [])))
        score += 4 * len(node_paths.intersection(contract.get("allowed_inspection_paths", [])))
        score += 2 if contract.get("responsibility_type") == MUTATION else 0
        scores.append((-score, str(contract.get("execution_contract_id")), contract))
    scores.sort(key=lambda item: (item[0], item[1]))
    return scores[0][2] if scores and scores[0][0] < 0 else None


def _approval_binding_for(snapshot, authority_binding=None):
    value = authority_binding if isinstance(authority_binding, dict) else {}
    if not value and isinstance(snapshot, dict) and isinstance(snapshot.get("approval_binding"), dict):
        value = snapshot.get("approval_binding")
    return value if isinstance(value, dict) else {}


def _attach_approval_binding(contract, snapshot, authority_binding=None):
    """Copy only compact V25 authority references into one Stage 4 contract."""
    binding = _approval_binding_for(snapshot, authority_binding)
    if not binding:
        return contract
    fields = {
        "approved_plan_hash": binding.get("approved_plan_hash") or binding.get("canonical_plan_hash") or snapshot.get("plan_hash"),
        "approval_receipt_hash": binding.get("approval_receipt_hash"),
        "execution_authorization_hash": binding.get("execution_authorization_hash"),
        "approved_task_id": binding.get("approved_task_id") or binding.get("task_id"),
        "approved_requirement_ids": _copy(binding.get("approved_requirement_ids") or binding.get("requirement_ids", [])),
        "approved_subject_hash": binding.get("approved_subject_hash") or binding.get("subject_aggregate_hash"),
        "approved_brain_hash": binding.get("approved_brain_hash") or binding.get("brain_hash"),
        "approved_planning_context_hash": binding.get("approved_planning_context_hash") or binding.get("planning_context_hash"),
        "approved_mutation_scope_digest": binding.get("approved_mutation_scope_digest") or binding.get("mutation_scope_digest"),
        "approved_dnt_digest": binding.get("approved_dnt_digest") or binding.get("dnt_digest"),
        "approved_dependency_digest": binding.get("approved_dependency_digest") or binding.get("dependency_digest"),
        "approved_verification_digest": binding.get("approved_verification_digest") or binding.get("verification_contract_digest"),
        "approved_interface_binding_digest": binding.get("approved_interface_binding_digest") or binding.get("interface_binding_digest"),
        "approved_requirement_coverage_digest": binding.get("approved_requirement_coverage_digest") or binding.get("requirement_coverage_digest"),
        "approved_challenger_reconciliation_hash": binding.get("approved_challenger_reconciliation_hash") or binding.get("challenger_reconciliation_hash"),
        "stage4_contract_graph_hash": binding.get("stage4_contract_graph_hash"),
        "stage4_dependency_graph_digest": binding.get("stage4_dependency_graph_digest"),
        "execution_invariant_set_hash": binding.get("execution_invariant_set_hash"),
        "execution_invariant_ids": _copy(binding.get("execution_invariant_ids", [])),
    }
    for key, value in fields.items():
        if value not in (None, "", [], {}):
            contract[key] = value
    contract["approval_binding_hash"] = deterministic_hash({
        key: value for key, value in fields.items() if value not in (None, "", [], {})
    })
    contract["contract_hash"] = deterministic_hash(_without(contract, "contract_hash"))
    return contract


def _attach_execution_invariant_binding(contract, execution_invariant_set):
    """Attach only bounded invariant authority to one compiled contract."""
    set_value = execution_invariant_set if isinstance(execution_invariant_set, dict) else {}
    set_scope = {
        str(item).casefold().rstrip("/")
        for item in (set_value.get("authority") or {}).get("mutation_paths", []) or []
    }
    contract_scope = {
        str(item).casefold().rstrip("/")
        for item in (contract or {}).get("allowed_mutation_paths", []) or []
    }
    scope_relevant = bool(set_scope.intersection(contract_scope))
    checked = invariant.validate_execution_invariant_set(
        execution_invariant_set,
        execution_contract=contract if scope_relevant else None,
    )
    if not checked.get("valid"):
        raise ExecutionContractError(
            str(checked.get("code") or EXECUTION_INVARIANT_INVALID),
            "; ".join(checked.get("errors", [])) or "execution invariant set is invalid",
            details=checked.get("errors", []),
        )
    selected = (
        invariant.relevant_invariants(set_value, contract)
        if scope_relevant else []
    )
    if len(selected) > invariant.MAX_PROJECTED_INVARIANTS:
        raise ExecutionContractError(
            WORKER_EXECUTION_INVARIANT_CONTEXT_OVERFLOW,
            "responsibility-relevant execution invariants exceed the projection bound",
            details=[
                f"relevant_invariants={len(selected)}",
                f"projection_limit={invariant.MAX_PROJECTED_INVARIANTS}",
            ],
        )
    compact = [invariant._compact_invariant(item) for item in selected]
    contract["execution_invariant_set_hash"] = set_value.get("invariant_set_hash")
    contract["execution_invariant_relevant_ids"] = [item.get("invariant_id") for item in compact]
    contract["execution_invariant_ids"] = [item.get("invariant_id") for item in compact]
    projection_core = invariant._projection_core(
        set_value.get("invariant_set_hash"), selected,
    )
    projection_core["projection_hash"] = invariant.canonical_hash(projection_core)
    contract["execution_invariant_projection"] = projection_core
    # Current source facts remain compact repository orientation.  The
    # semantic invariant itself is the authority; this list is not a second
    # mutation scope or a model-generated recommendation.
    facts = list(contract.get("relevant_repository_facts", []) or [])
    existing_fact_keys = {
        (str(item.get("evidence_id")), str(item.get("symbol")), str(item.get("path")))
        for item in facts if isinstance(item, dict)
    }
    # Existing Stage 4 repository facts are preferred.  Only an otherwise
    # empty fact section receives one compact evidence-backed orientation fact;
    # the semantic invariant projection remains the authoritative payload.
    for item in (selected if not facts else []):
        if item.get("type") not in {
            invariant.FUNCTION_SIGNATURE, invariant.RETURN_SHAPE,
            invariant.EXACT_EXISTING_OUTPUT, invariant.CONSUMER_EXPECTATION,
            invariant.INTERFACE_COMPATIBILITY,
        }:
            continue
        refs = [ref for ref in item.get("evidence_refs", []) or [] if isinstance(ref, dict)]
        ref = refs[0] if refs else {}
        fact = {
            "evidence_id": ref.get("evidence_id"),
            "fact": item.get("statement"),
            "path": item.get("path"),
            "symbol": item.get("symbol"),
        }
        key = (str(fact.get("evidence_id")), str(fact.get("symbol")), str(fact.get("path")))
        if key not in existing_fact_keys and len(facts) < 1:
            facts.append(fact)
            existing_fact_keys.add(key)
    contract["relevant_repository_facts"] = facts[:MAX_REPOSITORY_FACTS_PER_CONTRACT]
    contract["contract_hash"] = deterministic_hash(_without(contract, "contract_hash"))
    return contract


def compile_execution_contracts(snapshot, authority_binding=None, execution_invariant_set=None):
    """Compile one minimal bounded contract for each approved mutation/test responsibility."""
    if not isinstance(snapshot, dict) or not snapshot.get("immutable"):
        raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, "an immutable ApprovedPlanSnapshot is required")
    snapshot_validation = validate_snapshot(snapshot)
    if not snapshot_validation.get("valid"):
        raise ExecutionContractError(
            EXECUTION_CONTRACT_BLOCKED,
            "; ".join(snapshot_validation.get("errors", [])) or "ApprovedPlanSnapshot is invalid",
            details=snapshot_validation.get("errors", []),
        )
    nodes = list(snapshot.get("plan_nodes", []) or [])
    if len(nodes) > MAX_PLAN_NODES:
        raise ExecutionContractTooLargeError(EXECUTION_CONTRACT_TOO_LARGE, "approved plan node bound exceeded")
    contracts = []
    assignment = {}
    context_nodes = []
    for node in nodes:
        node_id = str(node.get("node_id", ""))
        if not node_id:
            raise ExecutionContractError(EXECUTION_CONTRACT_BLOCKED, "every approved plan node requires node_id")
        kind = _node_type(node)
        if kind in {MUTATION, TEST_MUTATION}:
            if len(contracts) >= MAX_EXECUTION_CONTRACTS:
                raise ExecutionContractTooLargeError(
                    EXECUTION_CONTRACT_TOO_LARGE,
                    "execution contract count bound exceeded",
                )
            contract_id = f"EXEC-{len(contracts) + 1:03d}"
            contract = _build_contract(snapshot, node, contract_id, kind)
            contracts.append(contract)
            assignment[node_id] = contract_id
        else:
            context_nodes.append(node)
    # Pure reuse is context authority, not an automatic Builder.  Attach it to
    # the most relevant owner contract; only an orphan gets a non-worker
    # VERIFY_ONLY contract.
    for node in context_nodes:
        owner = _compatible_reuse(node, contracts)
        if owner is not None:
            owner["attached_plan_node_ids"] = _ids(list(owner.get("attached_plan_node_ids", [])) + [node.get("node_id")])
            owner["plan_node_ids"] = _ids(list(owner.get("plan_node_ids", [])) + [node.get("node_id")])
            assignment[str(node.get("node_id"))] = owner["execution_contract_id"]
            owner["requirement_ids"] = _ids(list(owner.get("requirement_ids", [])) + list(node.get("requirement_ids", [])))
            owner["requirements"] = _contract_requirements(snapshot, owner["requirement_ids"])
            owner["obligation_types"] = _ids([value for item in snapshot.get("obligations", []) or [] if item.get("requirement_id") in owner["requirement_ids"] for value in item.get("obligation_types", [])])
            owner["impact_ids"] = _ids(list(owner.get("impact_ids", [])) + list(node.get("impact_ids", [])))
            owner["canonical_surface_ids"] = _ids(list(owner.get("canonical_surface_ids", [])) + list(node.get("surface_ids", [])) + list(node.get("inspect_surface_ids", [])) + list(node.get("interface_surface_ids", [])))
            owner["repository_evidence_ids"] = _ids(list(owner.get("repository_evidence_ids", [])) + list(node.get("evidence_ids", [])))
            owner["relevant_repository_facts"] = _contract_evidence(snapshot, owner["repository_evidence_ids"])
            owner["allowed_inspection_surface_ids"] = _ids(list(owner.get("allowed_inspection_surface_ids", [])) + list(node.get("surface_ids", [])) + list(node.get("inspect_surface_ids", [])) + list(node.get("interface_surface_ids", [])))
            owner["allowed_inspection_paths"] = _unique(list(owner.get("allowed_inspection_paths", [])) + _node_paths(node, "inspect_targets") + _surface_paths(snapshot, list(node.get("surface_ids", [])) + list(node.get("inspect_surface_ids", [])) + list(node.get("interface_surface_ids", []))), text_limit=MAX_PATH_CHARS)
            owner["interfaces_to_reuse"] = _unique(
                list(owner.get("interfaces_to_reuse", [])) + list(node.get("interfaces_to_reuse", [])),
                text_limit=MAX_TEXT_CHARS,
            )
            owner["local_preservation_constraints"] = _unique(
                list(owner.get("local_preservation_constraints", []))
                + list(node.get("local_preservation_constraints", []) or node.get("preservation_constraints", []) or []),
                text_limit=MAX_TEXT_CHARS,
            )
            owner["structured_prohibitions"] = _unique(
                list(owner.get("structured_prohibitions", [])) + list(node.get("prohibition_constraints", [])),
                text_limit=MAX_TEXT_CHARS,
            )
            owner["done_when"] = _unique(
                list(owner.get("done_when", [])) + list(node.get("done_when", [])),
                text_limit=MAX_TEXT_CHARS,
            )
            _validate_contract_bounds(owner)
        else:
            if len(contracts) >= MAX_EXECUTION_CONTRACTS:
                raise ExecutionContractTooLargeError(EXECUTION_CONTRACT_TOO_LARGE, "execution contract count bound exceeded")
            contract_id = f"EXEC-{len(contracts) + 1:03d}"
            orphan_type = INTERFACE_REUSE if kind == INTERFACE_REUSE else VERIFY_ONLY
            contract = _build_contract(snapshot, node, contract_id, orphan_type)
            contract["worker_required"] = False
            contract["contract_hash"] = deterministic_hash(_without(contract, "contract_hash"))
            contracts.append(contract)
            assignment[str(node.get("node_id"))] = contract_id
    # A plan may legitimately contain preservation-only authority with no
    # executable or reference node to consume it. Keep it in the graph as a
    # non-worker verification contract rather than letting the responsibility
    # disappear or launching a mutation Worker for it.
    attached_preservation_ids = {
        str(surface_id)
        for contract in contracts
        for surface_id in contract.get("attached_preservation_surface_ids", []) or []
    }
    for preservation_surface in snapshot.get("preservation_only_surfaces", []) or []:
        surface_id = str(
            preservation_surface.get("surface_id")
            or preservation_surface.get("canonical_surface_id")
            or ""
        )
        if not surface_id or surface_id in attached_preservation_ids:
            continue
        if len(contracts) >= MAX_EXECUTION_CONTRACTS:
            raise ExecutionContractTooLargeError(
                EXECUTION_CONTRACT_TOO_LARGE,
                "execution contract count bound exceeded while assigning preservation authority",
            )
        contract_id = f"EXEC-{len(contracts) + 1:03d}"
        synthetic = {
            "node_id": "",
            "goal": f"Verify preservation of {preservation_surface.get('component') or surface_id}.",
            "requirement_ids": list(preservation_surface.get("requirement_ids", []) or []),
            "surface_ids": [surface_id],
            "inspect_surface_ids": [surface_id],
            "inspect_targets": [_path(preservation_surface.get("path"))],
            "mutation_required": False,
            "verification_only": True,
            "impact_kind": "PRESERVATION_ONLY",
        }
        contract = _build_contract(snapshot, synthetic, contract_id, VERIFY_ONLY)
        contracts.append(contract)
        attached_preservation_ids.add(surface_id)
    # Test contracts can inspect the behavior contracts they explicitly depend
    # on, but never inherit their mutation authority.
    by_node = _node_by_id(snapshot)
    for contract in contracts:
        inspect = list(contract.get("allowed_inspection_paths", []))
        for node_id in contract.get("plan_node_ids", []):
            node = by_node.get(str(node_id), {})
            for dependency in node.get("dependencies", []) or []:
                dep_contract_id = assignment.get(str(dependency))
                dep_contract = next((item for item in contracts if item.get("execution_contract_id") == dep_contract_id), None)
                if dep_contract:
                    inspect.extend(dep_contract.get("allowed_mutation_paths", []))
                    contract["canonical_surface_ids"] = _ids(
                        list(contract.get("canonical_surface_ids", []))
                        + list(dep_contract.get("allowed_mutation_surface_ids", []))
                    )
                    contract["allowed_inspection_surface_ids"] = _ids(list(contract.get("allowed_inspection_surface_ids", [])) + list(dep_contract.get("allowed_mutation_surface_ids", [])))
        contract["allowed_inspection_paths"] = _unique(inspect, text_limit=MAX_PATH_CHARS)
    # Rehydrate dependencies from the approved node edges after all context
    # nodes have an owner assignment.
    for contract in contracts:
        dependencies = []
        for node_id in contract.get("owned_plan_node_ids", []):
            node = by_node.get(str(node_id), {})
            for dependency in node.get("dependencies", []) or []:
                mapped = assignment.get(str(dependency))
                if mapped and mapped != contract.get("execution_contract_id") and mapped not in dependencies:
                    dependencies.append(mapped)
        contract["dependencies"] = dependencies
        contract["contract_hash"] = deterministic_hash(_without(contract, "contract_hash"))
        _validate_contract_bounds(contract)
    binding = _approval_binding_for(snapshot, authority_binding)
    bound_invariant_hash = binding.get("execution_invariant_set_hash") if isinstance(binding, dict) else None
    if bound_invariant_hash and execution_invariant_set is None:
        raise ExecutionContractError(
            EXECUTION_INVARIANT_SET_REQUIRED,
            "the approval-bound contract references an execution invariant set that was not supplied",
        )
    if execution_invariant_set is not None:
        supplied_hash = execution_invariant_set.get("invariant_set_hash") if isinstance(execution_invariant_set, dict) else None
        if bound_invariant_hash and supplied_hash != bound_invariant_hash:
            raise ExecutionContractError(
                EXECUTION_INVARIANT_INVALID,
                "execution invariant set does not match the authorized invariant-set hash",
            )
        for contract in contracts:
            _attach_execution_invariant_binding(contract, execution_invariant_set)
    if binding:
        for contract in contracts:
            _attach_approval_binding(contract, snapshot, binding)
    graph_validation = validate_contracts(snapshot, contracts, assignment=assignment)
    if not graph_validation["valid"]:
        raise ExecutionGraphError(EXECUTION_GRAPH_INVALID, "; ".join(graph_validation["errors"]))
    metrics = {
        "execution_contracts_created": len(contracts),
        "execution_contract_mutation": sum(item.get("responsibility_type") == MUTATION for item in contracts),
        "execution_contract_test": sum(item.get("responsibility_type") == TEST_MUTATION for item in contracts),
        "execution_contract_verify_only": sum(item.get("responsibility_type") in {VERIFY_ONLY, INTERFACE_REUSE} for item in contracts),
        "reference_nodes_attached": sum(bool(item.get("attached_plan_node_ids")) for item in contracts),
    }
    return {"status": "ready", "contracts": contracts, "assignment": assignment, "validation": graph_validation, "metrics": metrics}


compile_approved_execution_contracts = compile_execution_contracts
compile_contracts = compile_execution_contracts


def _cycle(nodes_by_id):
    visiting, visited = set(), set()
    def visit(node_id):
        if node_id in visiting:
            return True
        if node_id in visited:
            return False
        visiting.add(node_id)
        for dependency in nodes_by_id.get(node_id, {}).get("dependencies", []) or []:
            if visit(str(dependency)):
                return True
        visiting.remove(node_id)
        visited.add(node_id)
        return False
    return any(visit(node_id) for node_id in nodes_by_id)


def validate_contracts(snapshot, contracts, assignment=None):
    value = snapshot if isinstance(snapshot, dict) else {}
    contracts = list(contracts or [])
    known_nodes = _node_by_id(value)
    known_node_ids = set(known_nodes)
    errors = []
    ids = [str(item.get("execution_contract_id", "")) for item in contracts if isinstance(item, dict)]
    if len(contracts) > MAX_EXECUTION_CONTRACTS:
        errors.append("execution contract count bound exceeded")
    if len(ids) != len(set(ids)):
        errors.append("duplicate execution contract ID")
    ownership = {}
    known_requirement_ids = {
        str(item.get("requirement_id"))
        for item in value.get("requirements", []) or []
        if isinstance(item, dict) and item.get("requirement_id")
    }
    known_surface_ids = {
        str(item.get("surface_id"))
        for item in value.get("canonical_surfaces", []) or []
        if isinstance(item, dict) and item.get("surface_id")
    }
    for field in (
        "canonical_mutation_surfaces", "canonical_test_surfaces", "canonical_reuse_surfaces",
    ):
        known_surface_ids.update(
            str(surface_id)
            for item in value.get(field, []) or []
            if isinstance(item, dict)
            for surface_id in item.get("surface_ids", []) or []
        )
    known_surface_ids.update(
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in value.get("preservation_only_surfaces", []) or []
        if isinstance(item, dict) and (item.get("surface_id") or item.get("canonical_surface_id"))
    )
    known_surface_ids.update(
        str(item) for item in value.get("global_do_not_touch_surface_ids", []) or []
    )
    known_evidence_ids = {
        str(item.get("evidence_id"))
        for item in value.get("canonical_evidence", []) or []
        if isinstance(item, dict) and item.get("evidence_id")
    }
    known_evidence_ids.update(str(item) for item in value.get("canonical_evidence_ids", []) or [])
    known_new_surface_proposal_ids = {
        str(item.get("proposal_id"))
        for item in value.get("new_surface_proposals", []) or []
        if isinstance(item, dict) and item.get("proposal_id")
    }
    global_do_not_touch = {
        _path(item).casefold() for item in value.get("global_do_not_touch", []) or []
    }
    global_do_not_touch_surface_ids = {
        str(item) for item in value.get("global_do_not_touch_surface_ids", []) or []
    }
    known_preservation_surface_ids = {
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in value.get("preservation_only_surfaces", []) or []
        if isinstance(item, dict) and (item.get("surface_id") or item.get("canonical_surface_id"))
    }
    worker_contracts = []
    def scan_forbidden(item):
        if isinstance(item, dict):
            for key, child in item.items():
                if str(key).casefold() in _RAW_FORBIDDEN_KEYS:
                    errors.append(f"forbidden raw Stage 3 field in contract: {key}")
                scan_forbidden(child)
        elif isinstance(item, list):
            for child in item:
                scan_forbidden(child)
    for contract in contracts:
        if not isinstance(contract, dict):
            errors.append("contract must be an object")
            continue
        cid = str(contract.get("execution_contract_id", ""))
        scan_forbidden(contract)
        if not cid or contract.get("plan_id") != value.get("plan_id") or contract.get("plan_hash") != value.get("plan_hash"):
            errors.append(f"{cid}: contract plan identity mismatch")
        if contract.get("contract_hash") != deterministic_hash(_without(contract, "contract_hash")):
            errors.append(f"{cid}: contract hash does not match content")
        approval_binding = _approval_binding_for(value)
        if approval_binding:
            expected_binding_fields = {
                "approved_plan_hash": approval_binding.get("approved_plan_hash") or approval_binding.get("canonical_plan_hash") or value.get("plan_hash"),
                "approval_receipt_hash": approval_binding.get("approval_receipt_hash"),
                "execution_authorization_hash": approval_binding.get("execution_authorization_hash"),
                "approved_task_id": approval_binding.get("approved_task_id") or approval_binding.get("task_id"),
                "approved_requirement_ids": _copy(approval_binding.get("approved_requirement_ids") or approval_binding.get("requirement_ids", [])),
                "approved_subject_hash": approval_binding.get("approved_subject_hash") or approval_binding.get("subject_aggregate_hash"),
                "approved_brain_hash": approval_binding.get("approved_brain_hash") or approval_binding.get("brain_hash"),
                "approved_planning_context_hash": approval_binding.get("approved_planning_context_hash") or approval_binding.get("planning_context_hash"),
                "approved_mutation_scope_digest": approval_binding.get("approved_mutation_scope_digest") or approval_binding.get("mutation_scope_digest"),
                "approved_dnt_digest": approval_binding.get("approved_dnt_digest") or approval_binding.get("dnt_digest"),
                "approved_dependency_digest": approval_binding.get("approved_dependency_digest") or approval_binding.get("dependency_digest"),
                "approved_verification_digest": approval_binding.get("approved_verification_digest") or approval_binding.get("verification_contract_digest"),
                "approved_interface_binding_digest": approval_binding.get("approved_interface_binding_digest") or approval_binding.get("interface_binding_digest"),
                "approved_requirement_coverage_digest": approval_binding.get("approved_requirement_coverage_digest") or approval_binding.get("requirement_coverage_digest"),
                "approved_challenger_reconciliation_hash": approval_binding.get("approved_challenger_reconciliation_hash") or approval_binding.get("challenger_reconciliation_hash"),
                "stage4_contract_graph_hash": approval_binding.get("stage4_contract_graph_hash"),
                "stage4_dependency_graph_digest": approval_binding.get("stage4_dependency_graph_digest"),
                "execution_invariant_set_hash": approval_binding.get("execution_invariant_set_hash"),
                "execution_invariant_ids": _copy(approval_binding.get("execution_invariant_ids", [])),
            }
            for field, expected in expected_binding_fields.items():
                if expected not in (None, "", [], {}) and contract.get(field) != expected:
                    errors.append(f"{cid}: approval binding {field} mismatch")
            expected_binding_hash = deterministic_hash({
                key: item for key, item in {
                    "approved_plan_hash": expected_binding_fields.get("approved_plan_hash"),
                    "approval_receipt_hash": expected_binding_fields.get("approval_receipt_hash"),
                    "execution_authorization_hash": expected_binding_fields.get("execution_authorization_hash"),
                    "approved_task_id": expected_binding_fields.get("approved_task_id"),
                    "approved_requirement_ids": expected_binding_fields.get("approved_requirement_ids"),
                    "approved_subject_hash": expected_binding_fields.get("approved_subject_hash"),
                    "approved_brain_hash": expected_binding_fields.get("approved_brain_hash"),
                    "approved_planning_context_hash": expected_binding_fields.get("approved_planning_context_hash"),
                    "approved_mutation_scope_digest": expected_binding_fields.get("approved_mutation_scope_digest"),
                    "approved_dnt_digest": expected_binding_fields.get("approved_dnt_digest"),
                    "approved_dependency_digest": expected_binding_fields.get("approved_dependency_digest"),
                    "approved_verification_digest": expected_binding_fields.get("approved_verification_digest"),
                    "approved_interface_binding_digest": expected_binding_fields.get("approved_interface_binding_digest"),
                    "approved_requirement_coverage_digest": expected_binding_fields.get("approved_requirement_coverage_digest"),
                    "approved_challenger_reconciliation_hash": expected_binding_fields.get("approved_challenger_reconciliation_hash"),
                    "stage4_contract_graph_hash": expected_binding_fields.get("stage4_contract_graph_hash"),
                    "stage4_dependency_graph_digest": expected_binding_fields.get("stage4_dependency_graph_digest"),
                    "execution_invariant_set_hash": expected_binding_fields.get("execution_invariant_set_hash"),
                    "execution_invariant_ids": expected_binding_fields.get("execution_invariant_ids"),
                }.items() if item not in (None, "", [], {})
            })
            if contract.get("approval_binding_hash") != expected_binding_hash:
                errors.append(f"{cid}: approval binding hash mismatch")
        node_ids = [str(item) for item in contract.get("plan_node_ids", []) or []]
        owned_ids = [str(item) for item in contract.get("owned_plan_node_ids", []) or []]
        if not set(node_ids).issubset(known_node_ids) or not set(owned_ids).issubset(known_node_ids):
            errors.append(f"{cid}: unapproved plan node reference")
        if not set(str(item) for item in contract.get("requirement_ids", []) or []).issubset(known_requirement_ids):
            errors.append(f"{cid}: unapproved requirement reference")
        if not set(str(item) for item in contract.get("canonical_surface_ids", []) or []).issubset(known_surface_ids):
            errors.append(f"{cid}: unapproved canonical surface reference")
        if not set(str(item) for item in contract.get("repository_evidence_ids", []) or []).issubset(known_evidence_ids):
            errors.append(f"{cid}: unapproved repository evidence reference")
        if not set(str(item) for item in contract.get("attached_preservation_surface_ids", []) or []).issubset(known_preservation_surface_ids):
            errors.append(f"{cid}: unapproved preservation surface reference")
        if not set(str(item) for item in contract.get("new_surface_proposal_ids", []) or []).issubset(known_new_surface_proposal_ids):
            errors.append(f"{cid}: unapproved new-surface proposal reference")
        for node_id in node_ids:
            ownership.setdefault(node_id, []).append(cid)
        if {
            _path(item).casefold() for item in contract.get("allowed_mutation_paths", []) or []
        }.intersection(global_do_not_touch):
            errors.append(f"{cid}: mutation scope conflicts with global do_not_touch")
        if set(str(item) for item in contract.get("allowed_mutation_surface_ids", []) or []).intersection(global_do_not_touch_surface_ids):
            errors.append(f"{cid}: mutation scope conflicts with protected surfaces")
        if contract.get("responsibility_type") not in RESPONSIBILITY_TYPES:
            errors.append(f"{cid}: unknown responsibility type")
        if contract.get("execution_invariant_set_hash"):
            if not isinstance(contract.get("execution_invariant_projection"), dict):
                errors.append(f"{cid}: execution invariant projection is missing")
            if not isinstance(contract.get("execution_invariant_relevant_ids"), list):
                errors.append(f"{cid}: execution invariant relevance list is missing")
        expected_worker = contract.get("responsibility_type") in {MUTATION, TEST_MUTATION}
        if bool(contract.get("worker_required")) != expected_worker:
            errors.append(f"{cid}: worker_required does not match responsibility type")
        if not set(_path(item).casefold() for item in contract.get("allowed_mutation_paths", []) or []).issubset(
            set(_path(item).casefold() for item in contract.get("allowed_inspection_paths", []) or [])
        ):
            errors.append(f"{cid}: mutation scope is not included in inspection scope")
        if not set(str(item) for item in contract.get("allowed_mutation_surface_ids", []) or []).issubset(
            set(str(item) for item in contract.get("canonical_surface_ids", []) or [])
        ):
            errors.append(f"{cid}: mutation surfaces are not canonical contract surfaces")
        if not set(str(item) for item in contract.get("allowed_inspection_surface_ids", []) or []).issubset(
            set(str(item) for item in contract.get("canonical_surface_ids", []) or [])
        ):
            errors.append(f"{cid}: inspection surfaces are not canonical contract surfaces")
        responsibility_type = contract.get("responsibility_type")
        for node_id in owned_ids:
            if node_id in known_nodes and _node_type(known_nodes[node_id]) != responsibility_type:
                errors.append(f"{cid}: responsibility type does not match owned plan node {node_id}")
        try:
            _validate_contract_bounds(contract)
        except ExecutionContractError as exc:
            errors.append(f"{cid}: {exc}")
        if expected_worker:
            worker_contracts.append(contract)
            if not global_do_not_touch.issubset(
                {_path(item).casefold() for item in contract.get("global_do_not_touch", []) or []}
            ):
                errors.append(f"{cid}: global do_not_touch was not propagated")
            if not global_do_not_touch_surface_ids.issubset(
                set(str(item) for item in contract.get("global_do_not_touch_surface_ids", []) or [])
            ):
                errors.append(f"{cid}: protected surface IDs were not propagated")
        if len(_json(contract)) > MAX_CONTRACT_CHARS:
            errors.append(f"{cid}: contract serialized-size bound exceeded")
    if assignment:
        for node_id, cid in assignment.items():
            if node_id not in known_node_ids or cid not in ids:
                errors.append(f"assignment references unknown responsibility: {node_id}->{cid}")
    for node_id, owners in ownership.items():
        if len(owners) != 1:
            errors.append(f"approved responsibility {node_id} has duplicate ownership")
    required_ids = {
        str(node.get("node_id")) for node in known_nodes.values()
        if _node_type(node) in {MUTATION, TEST_MUTATION}
    }
    represented_owned = {str(item) for contract in contracts for item in contract.get("owned_plan_node_ids", []) or []}
    if required_ids - represented_owned:
        errors.append("approved executable responsibility is missing")
    for node_id, node in known_nodes.items():
        if _node_type(node) in {INTERFACE_REUSE, VERIFY_ONLY} and node_id not in ownership:
            errors.append(f"context responsibility {node_id} disappeared")
    for item in value.get("preservation_only_surfaces", []) or []:
        if not isinstance(item, dict):
            continue
        surface_id = str(item.get("surface_id") or item.get("canonical_surface_id") or "")
        if surface_id and not any(
            surface_id in set(str(value) for value in contract.get("attached_preservation_surface_ids", []) or [])
            for contract in contracts
        ):
            errors.append(f"preservation responsibility {surface_id} is unattached")
    required_prohibitions = {
        str(item) for item in value.get("structured_prohibitions", []) or []
    }
    for contract in worker_contracts:
        if not required_prohibitions.issubset(
            set(str(item) for item in contract.get("structured_prohibitions", []) or [])
        ):
            errors.append(f"{contract.get('execution_contract_id')}: structured prohibitions were not propagated")
    return {"valid": not errors, "errors": errors[:30], "contract_count": len(contracts), "owned_node_ids": sorted(ownership)}


def _topological_order(contracts):
    by_id = {str(item.get("execution_contract_id")): item for item in contracts}
    indegree = {key: 0 for key in by_id}
    dependents = {key: [] for key in by_id}
    for cid, item in by_id.items():
        for dependency in item.get("dependencies", []) or []:
            dependency = str(dependency)
            if dependency not in by_id:
                raise ExecutionGraphError(EXECUTION_GRAPH_INVALID, f"{cid}: unknown dependency {dependency}")
            indegree[cid] += 1
            dependents[dependency].append(cid)
    ready = sorted([key for key, value in indegree.items() if value == 0])
    result = []
    while ready:
        current = ready.pop(0)
        result.append(current)
        for dependent in sorted(dependents[current]):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
        ready.sort()
    if len(result) != len(by_id):
        raise ExecutionGraphError(EXECUTION_GRAPH_INVALID, "execution contract dependency cycle detected")
    return result


def build_execution_graph(snapshot, contracts=None):
    if contracts is None:
        compiled = compile_execution_contracts(snapshot)
        contracts = compiled["contracts"]
    validation = validate_contracts(snapshot, contracts)
    if not validation["valid"]:
        raise ExecutionGraphError(EXECUTION_GRAPH_INVALID, "; ".join(validation["errors"]))
    order = _topological_order(contracts)
    graph_nodes = [{
        "execution_contract_id": item.get("execution_contract_id"),
        "contract_hash": item.get("contract_hash"),
        "plan_node_ids": list(item.get("plan_node_ids", []) or []),
        "owned_plan_node_ids": list(item.get("owned_plan_node_ids", []) or []),
        "dependencies": list(item.get("dependencies", []) or []),
        "responsibility_type": item.get("responsibility_type"),
        "worker_required": bool(item.get("worker_required")),
        "attached_preservation_surface_ids": list(item.get("attached_preservation_surface_ids", []) or []),
    } for item in contracts]
    graph = {
        "schema_version": "4A",
        "plan_id": snapshot.get("plan_id"), "plan_hash": snapshot.get("plan_hash"),
        "nodes": graph_nodes, "topological_order": order,
        "integration_responsibility": list(snapshot.get("integration_contract", []) or []),
        "provenance": APPROVED_PLAN,
    }
    approval_binding = _approval_binding_for(snapshot)
    if approval_binding:
        graph["approval_binding"] = _copy(approval_binding)
        graph["approval_binding_hash"] = deterministic_hash(approval_binding)
    graph["graph_hash"] = deterministic_hash(graph)
    return graph


plan_execution_graph = build_execution_graph


def validate_execution_graph(snapshot, graph, contracts=None):
    value = graph if isinstance(graph, dict) else {}
    errors = []
    if value.get("plan_id") != (snapshot or {}).get("plan_id") or value.get("plan_hash") != (snapshot or {}).get("plan_hash"):
        errors.append("graph plan identity mismatch")
    snapshot_binding = _approval_binding_for(snapshot)
    if snapshot_binding:
        if value.get("approval_binding") != snapshot_binding:
            errors.append("graph approval binding does not match the approved snapshot")
        if value.get("approval_binding_hash") != deterministic_hash(snapshot_binding):
            errors.append("graph approval binding hash does not match content")
    expected_hash = deterministic_hash(_without(value, "graph_hash"))
    if value.get("graph_hash") != expected_hash:
        errors.append("graph hash does not match content")
    raw_nodes = value.get("nodes", [])
    nodes = list(raw_nodes or []) if isinstance(raw_nodes, list) else []
    if not isinstance(raw_nodes, list):
        errors.append("graph nodes must be a list")
    if len(nodes) > MAX_EXECUTION_CONTRACTS:
        errors.append("graph contract count bound exceeded")
    if any(not isinstance(item, dict) for item in nodes):
        errors.append("graph nodes must be objects")
    by_id = {str(item.get("execution_contract_id")): item for item in nodes if isinstance(item, dict)}
    if len(by_id) != len(nodes):
        errors.append("graph contains duplicate or missing contract IDs")
    for cid, item in by_id.items():
        dependencies = item.get("dependencies", [])
        if not isinstance(dependencies, list):
            errors.append(f"{cid}: graph dependencies must be a list")
            dependencies = []
        for dependency in dependencies or []:
            if str(dependency) not in by_id:
                errors.append(f"{cid}: unknown dependency {dependency}")
    if _cycle(by_id):
        errors.append("execution graph contains a dependency cycle")
    known_nodes = _node_by_id(snapshot)
    known_node_ids = set(known_nodes)
    graph_ownership = {}
    required_ids = set()
    for node_id, node in known_nodes.items():
        if _node_type(node) in {MUTATION, TEST_MUTATION}:
            required_ids.add(node_id)
    graph_preservation = {
        str(item.get("surface_id") or item.get("canonical_surface_id"))
        for item in (snapshot or {}).get("preservation_only_surfaces", []) or []
        if isinstance(item, dict) and (item.get("surface_id") or item.get("canonical_surface_id"))
    }
    covered_preservation = set()
    for cid, item in by_id.items():
        if not isinstance(item, dict):
            errors.append(f"{cid}: graph node must be an object")
            continue
        node_ids = [str(item_id) for item_id in item.get("plan_node_ids", []) or []]
        owned_ids = [str(item_id) for item_id in item.get("owned_plan_node_ids", []) or []]
        if not set(node_ids).issubset(known_node_ids):
            errors.append(f"{cid}: graph contains an unapproved plan node")
        if not set(owned_ids).issubset(set(node_ids)):
            errors.append(f"{cid}: graph owned plan nodes are not in its coverage")
        responsibility_type = item.get("responsibility_type")
        if responsibility_type not in RESPONSIBILITY_TYPES:
            errors.append(f"{cid}: graph contains an unknown responsibility type")
        if bool(item.get("worker_required")) != (responsibility_type in {MUTATION, TEST_MUTATION}):
            errors.append(f"{cid}: graph worker authority does not match responsibility type")
        if responsibility_type in {MUTATION, TEST_MUTATION}:
            if any(_node_type(known_nodes[node_id]) != responsibility_type for node_id in owned_ids if node_id in known_nodes):
                errors.append(f"{cid}: graph responsibility type does not match owned plan nodes")
        for node_id in node_ids:
            graph_ownership.setdefault(node_id, []).append(cid)
        preserved = {str(surface_id) for surface_id in item.get("attached_preservation_surface_ids", []) or []}
        if not preserved.issubset(graph_preservation):
            errors.append(f"{cid}: graph contains an unapproved preservation surface")
        covered_preservation.update(preserved)
    if required_ids - set(graph_ownership):
        errors.append("graph omits an approved executable responsibility")
    for node_id, owners in graph_ownership.items():
        if len(owners) != 1:
            errors.append(f"graph responsibility {node_id} has duplicate ownership")
    for node_id in known_node_ids:
        if _node_type(known_nodes[node_id]) in {INTERFACE_REUSE, VERIFY_ONLY} and node_id not in graph_ownership:
            errors.append(f"graph omits context responsibility {node_id}")
    if graph_preservation - covered_preservation:
        errors.append("graph omits an approved preservation responsibility")
    if list(value.get("integration_responsibility", []) or []) != list((snapshot or {}).get("integration_contract", []) or []):
        errors.append("graph integration responsibility does not match the approved snapshot")
    if all(isinstance(item, dict) for item in nodes):
        try:
            computed_order = _topological_order(nodes)
            raw_order = value.get("topological_order", [])
            if not isinstance(raw_order, list):
                errors.append("graph topological_order must be a list")
            elif list(raw_order or []) != computed_order:
                errors.append("graph topological order is not deterministic")
        except ExecutionGraphError as exc:
            errors.append(str(exc))
    elif not isinstance(value.get("topological_order", []), list):
        errors.append("graph topological_order must be a list")
    if contracts is not None:
        contract_validation = validate_contracts(snapshot, contracts)
        errors.extend(contract_validation.get("errors", []))
        graph_ids = set(by_id)
        contract_ids = {str(item.get("execution_contract_id")) for item in contracts}
        if graph_ids != contract_ids:
            errors.append("graph contracts do not match compiled contracts")
        for item in contracts:
            graph_node = by_id.get(str(item.get("execution_contract_id")), {})
            if graph_node.get("contract_hash") != item.get("contract_hash"):
                errors.append(f"{item.get('execution_contract_id')}: graph contract hash mismatch")
            if list(graph_node.get("plan_node_ids", []) or []) != list(item.get("plan_node_ids", []) or []):
                errors.append(f"{item.get('execution_contract_id')}: graph plan-node coverage mismatch")
            if list(graph_node.get("owned_plan_node_ids", []) or []) != list(item.get("owned_plan_node_ids", []) or []):
                errors.append(f"{item.get('execution_contract_id')}: graph owned-node coverage mismatch")
            if list(graph_node.get("dependencies", []) or []) != list(item.get("dependencies", []) or []):
                errors.append(f"{item.get('execution_contract_id')}: graph dependency mismatch")
            if graph_node.get("responsibility_type") != item.get("responsibility_type"):
                errors.append(f"{item.get('execution_contract_id')}: graph responsibility type mismatch")
            if bool(graph_node.get("worker_required")) != bool(item.get("worker_required")):
                errors.append(f"{item.get('execution_contract_id')}: graph worker authority mismatch")
            if list(graph_node.get("attached_preservation_surface_ids", []) or []) != list(item.get("attached_preservation_surface_ids", []) or []):
                errors.append(f"{item.get('execution_contract_id')}: graph preservation coverage mismatch")
    reported_order = value.get("topological_order", [])
    if not isinstance(reported_order, list):
        reported_order = []
    return {"valid": not errors, "errors": errors[:30], "topological_order": list(reported_order or [])}


def _structural_unique_ids(value, fields):
    """Read optional structured ownership IDs without interpreting prose."""
    values = []
    for field in fields:
        raw = value.get(field)
        if isinstance(raw, dict):
            raw = list(raw.keys())
        if isinstance(raw, (list, tuple, set)):
            values.extend(str(item).strip() for item in raw if str(item).strip())
    return _unique(values, text_limit=None, sort=True)


def _structural_paths(value, field):
    raw = value.get(field, [])
    if not isinstance(raw, (list, tuple, set)):
        return []
    return _unique(
        [_path(item) for item in raw if _path(item)],
        text_limit=MAX_PATH_CHARS,
        sort=True,
    )


def _structural_path_is_within(path, roots):
    normalized = _path(path).casefold().rstrip("/")
    return any(
        normalized == root or normalized.startswith(root + "/")
        for root in {
            _path(item).casefold().rstrip("/")
            for item in roots
            if _path(item)
        }
    )


def _structural_test_path(path):
    """Recognize test *path structure*, never task prose or keywords."""
    normalized = _path(path).casefold().strip("/")
    if not normalized:
        return False
    parts = normalized.split("/")
    filename = parts[-1]
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return (
        parts[0] in {"test", "tests", "spec", "specs"}
        or filename.startswith(("test_", "spec_"))
        or stem.endswith(("_test", "_spec"))
        or ".test." in filename
        or ".spec." in filename
    )


def analyze_structural_fit(contract):
    """Classify one approved contract before any model Task-Fit call.

    The analyzer consumes only typed/structured Execution Contract authority:
    mutation paths/surfaces, responsibility IDs, obligation counts, and
    completion entries.  It deliberately ignores goals, requirement prose,
    preservation prose, prohibitions, DNT paths, inspection-only paths, and
    interface names.  It never creates child contracts and never calls a
    model.

    ``DIRECT_ALLOWED`` is reserved for one effective mutation owner (or no
    worker mutation).  Two owners remain ``AMBIGUOUS`` so the existing bounded
    Task-Fit model may decide.  A mixed implementation/test mutation or three
    owners with three separate completion entries creates a deterministic
    ``DECOMPOSITION_REQUIRED`` obligation.
    """
    value = contract if isinstance(contract, dict) else {}
    protected_paths = _structural_paths(value, "global_do_not_touch")
    mutation_paths = [
        path for path in _structural_paths(value, "allowed_mutation_paths")
        if not _structural_path_is_within(path, protected_paths)
    ]
    all_mutation_surface_ids = _structural_unique_ids(
        value,
        ("allowed_mutation_surface_ids", "mutation_surface_ids"),
    )
    protected_surface_ids = set(_structural_unique_ids(
        value, ("global_do_not_touch_surface_ids",),
    ))
    mutation_surface_ids = [
        surface_id for surface_id in all_mutation_surface_ids
        if surface_id not in protected_surface_ids
    ]
    explicit_owner_ids = _structural_unique_ids(
        value,
        (
            "distinct_mutation_owners", "mutation_owner_ids", "mutation_owners",
            "owned_mutation_responsibility_ids", "owned_responsibility_ids",
        ),
    )
    # A child contract may inherit the parent's canonical surface IDs while
    # shrinking its actual mutation paths.  Effective mutation paths therefore
    # take precedence for owner counting; surface IDs remain an independent
    # evidence count and are used when a contract has no concrete paths.
    owner_ids = explicit_owner_ids or mutation_paths or mutation_surface_ids
    effective_mutation_surface_count = len(mutation_surface_ids or mutation_paths)

    explicit_test_paths = _structural_paths(value, "test_mutation_paths")
    explicit_test_surface_ids = _structural_unique_ids(
        value, ("test_mutation_surface_ids", "test_surface_ids"),
    )
    test_path_set = set(explicit_test_paths)
    test_path_count = sum(
        1 for path in mutation_paths
        if path in test_path_set or _structural_test_path(path)
    )
    non_test_path_count = max(0, len(mutation_paths) - test_path_count)
    surface_test_count = len(set(mutation_surface_ids).intersection(explicit_test_surface_ids))
    responsibility_type = str(value.get("responsibility_type", "")).upper()
    has_test_mutation = bool(test_path_count or surface_test_count or responsibility_type == TEST_MUTATION)
    has_non_test_mutation = bool(non_test_path_count)
    if explicit_test_surface_ids and set(mutation_surface_ids).difference(explicit_test_surface_ids):
        has_non_test_mutation = True
    if responsibility_type == TEST_MUTATION and not non_test_path_count:
        has_non_test_mutation = False

    requirement_ids = _structural_unique_ids(value, ("requirement_ids",))
    requirements = value.get("requirements", [])
    requirement_count = len(requirement_ids or (
        _unique(requirements, text_limit=MAX_REQUIREMENT_TEXT_CHARS, sort=True)
        if isinstance(requirements, list) else []
    ))
    obligation_types = _structural_unique_ids(value, ("obligation_types",))
    done_when = value.get("done_when", [])
    done_when_count = len(done_when) if isinstance(done_when, list) else 0

    reason_codes = []
    if not mutation_paths and not mutation_surface_ids and not value.get("worker_required"):
        classification = DIRECT_ALLOWED
        reason_codes.append("NO_MUTATION_RESPONSIBILITY")
    elif has_test_mutation and has_non_test_mutation:
        classification = DECOMPOSITION_REQUIRED
        reason_codes.append("MIXED_IMPLEMENTATION_AND_TEST_MUTATION")
    elif len(owner_ids) >= 3 and done_when_count >= 3:
        classification = DECOMPOSITION_REQUIRED
        reason_codes.append("THREE_MUTATION_OWNERS_WITH_SEPARATE_COMPLETION")
    elif len(owner_ids) >= 2:
        classification = AMBIGUOUS
        reason_codes.append("MULTI_OWNER_ATOMICITY_UNCERTAIN")
    else:
        classification = DIRECT_ALLOWED
        reason_codes.append("ONE_MUTATION_OWNER")

    if len(owner_ids) >= 3 and done_when_count >= 3 and "THREE_MUTATION_OWNERS_WITH_SEPARATE_COMPLETION" not in reason_codes:
        reason_codes.append("THREE_MUTATION_OWNERS_WITH_SEPARATE_COMPLETION")
    if classification == DECOMPOSITION_REQUIRED and done_when_count >= 3:
        reason_codes.append("MULTIPLE_COMPLETION_RESPONSIBILITIES")
    if has_test_mutation:
        reason_codes.append("TEST_MUTATION_PRESENT")
    if has_non_test_mutation:
        reason_codes.append("NON_TEST_MUTATION_PRESENT")

    evidence = {
        "schema_version": STRUCTURAL_FIT_SCHEMA_VERSION,
        "execution_contract_id": value.get("execution_contract_id"),
        "contract_hash": value.get("contract_hash"),
        "approved_plan_hash": value.get("plan_hash"),
        "classification": classification,
        "mutation_path_count": len(mutation_paths),
        "mutation_surface_count": effective_mutation_surface_count,
        "owned_responsibility_count": len(owner_ids),
        "requirement_count": requirement_count,
        "obligation_type_count": len(obligation_types),
        "done_when_count": done_when_count,
        "has_test_mutation": has_test_mutation,
        "has_non_test_mutation": has_non_test_mutation,
        "test_mutation": has_test_mutation,
        "non_test_mutation": has_non_test_mutation,
        "test_mutation_path_count": test_path_count,
        "non_test_mutation_path_count": non_test_path_count,
        "distinct_mutation_owners": list(owner_ids),
        "distinct_mutation_owner_count": len(owner_ids),
        "mutation_owner_count": len(owner_ids),
        "completion_responsibility_count": done_when_count,
        "reason_codes": reason_codes,
        "model_calls": 0,
    }
    evidence["structural_fit_hash"] = deterministic_hash(
        _without(evidence, "structural_fit_hash"),
    )
    return evidence


def validate_structural_fit(evidence, contract=None):
    """Validate deterministic structural evidence without changing authority."""
    value = evidence if isinstance(evidence, dict) else {}
    errors = []
    if value.get("classification") not in {
        DIRECT_ALLOWED, AMBIGUOUS, DECOMPOSITION_REQUIRED,
    }:
        errors.append("unknown structural fit classification")
    if value.get("model_calls") != 0:
        errors.append("structural fit analyzer must use zero model calls")
    expected_hash = deterministic_hash(_without(value, "structural_fit_hash"))
    if value.get("structural_fit_hash") != expected_hash:
        errors.append("structural fit hash does not match evidence")
    if isinstance(contract, dict):
        if value.get("execution_contract_id") != contract.get("execution_contract_id"):
            errors.append("structural fit contract identity mismatch")
        if value.get("contract_hash") != contract.get("contract_hash"):
            errors.append("structural fit contract hash mismatch")
    return {"valid": not errors, "errors": errors[:20]}


structural_fit_analyzer = analyze_structural_fit
structural_fit = analyze_structural_fit


def contract_projection(contract, max_chars=MAX_CONTEXT_CHARS):
    """Return only the fields a MissionCompiler/Worker may receive."""
    value = contract if isinstance(contract, dict) else {}
    fields = (
        "execution_contract_id", "contract_hash", "plan_id", "plan_hash", "plan_node_ids",
        "goal", "responsibility_type", "requirement_ids", "requirements", "obligation_types",
        "impact_ids", "canonical_surface_ids", "repository_evidence_ids", "relevant_repository_facts",
        "allowed_mutation_surface_ids", "allowed_mutation_paths", "allowed_inspection_surface_ids",
        "allowed_inspection_paths", "interfaces_to_reuse", "interface_surface_ids",
        "new_surface_proposal_ids", "target_new_surface_proposal_ids",
        "inspect_new_surface_proposal_ids", "approved_new_surface_parent_scopes",
        "local_preservation_constraints", "structured_prohibitions", "global_do_not_touch_surface_ids",
        "global_do_not_touch", "test_contract", "integration_responsibility", "done_when",
        "dependencies", "provenance", "derivation", "source_provenance", "worker_required",
        # Stage 6C-A additive authority references.  They are intentionally
        # projected with the contract so a downstream Worker can never lose
        # the approval proof while receiving its bounded context.
        "approved_plan_hash", "approval_receipt_hash", "execution_authorization_hash",
        "approved_task_id", "approved_requirement_ids", "approved_subject_hash",
        "approved_brain_hash", "approved_planning_context_hash",
        "approved_mutation_scope_digest", "approved_dnt_digest",
        "approved_dependency_digest", "approved_verification_digest",
        "approved_interface_binding_digest", "approved_requirement_coverage_digest",
        "approved_challenger_reconciliation_hash", "stage4_contract_graph_hash",
        "stage4_dependency_graph_digest", "approval_binding_hash",
        # V25.2 deterministic preservation authority.  The full evidence
        # catalog stays internal; only the compact responsibility projection
        # is eligible for Worker context.
        "execution_invariant_set_hash", "execution_invariant_ids",
        "execution_invariant_relevant_ids",
        "execution_invariants", "execution_invariant_projection",
    )
    result = {key: _copy(value.get(key)) for key in fields if key in value}
    encoded = _json(result)
    if len(encoded) > max_chars:
        # Authority is not dropped.  A contract that cannot fit remains a
        # controlled failure instead of becoming an ambiguous model prompt.
        raise ExecutionContractTooLargeError(EXECUTION_CONTRACT_TOO_LARGE, "contract projection exceeds context bound")
    return result


build_execution_contract_projection = contract_projection


def build_worker_contract_context(contract, dependency_summaries=None, max_chars=MAX_CONTEXT_CHARS):
    projection = contract_projection(contract, max_chars=max_chars)
    dependencies = []
    for item in list(dependency_summaries or [])[-MAX_DEPENDENCIES_PER_CONTRACT:]:
        if not isinstance(item, dict):
            continue
        if str(item.get("status", "")).casefold() not in {"done", "verified", "passed"}:
            continue
        dependencies.append({
            "task_id": _text(item.get("task_id"), 100),
            "status": _text(item.get("status"), 40),
            "summary": _text(item.get("summary"), 500),
            "changed_files": _unique([_path(value) for value in item.get("changed_files", [])], limit=12, text_limit=MAX_PATH_CHARS),
        })
    context = {
        "execution_contract": projection,
        "completed_dependencies": dependencies,
        "context_provenance": DERIVED_EXECUTION_CONTRACT,
    }
    if len(_json(context)) > max_chars:
        context["completed_dependencies"] = dependencies[-2:]
    if len(_json(context)) > max_chars:
        raise ExecutionContractTooLargeError(EXECUTION_CONTRACT_TOO_LARGE, "worker contract context exceeds context bound")
    return context


def _path_values(value):
    values = value if isinstance(value, list) else [value]
    found = []
    for item in values:
        text = str(item or "")
        if not text:
            continue
        if re.fullmatch(r"[^\s]+", text) and ("/" in text or "\\" in text or re.search(r"\.[A-Za-z0-9]{1,8}$", text)):
            found.append(_path(text))
            continue
        found.extend(_path(match.group(1)) for match in _PATH_RE.finditer(text))
    return _unique(found, text_limit=MAX_PATH_CHARS)


def _path_is_within(path, scope):
    target = _path(path).casefold().rstrip("/")
    parent = _path(scope).casefold().rstrip("/")
    return bool(target and parent and (target == parent or target.startswith(parent + "/")))


def _mutation_path_allowed(contract, path):
    authority = contract if isinstance(contract, dict) else {}
    target = _path(path).casefold().rstrip("/")
    if not target:
        return False
    if target in {_path(item).casefold().rstrip("/") for item in authority.get("allowed_mutation_paths", []) or []}:
        return True
    if not authority.get("target_new_surface_proposal_ids"):
        return False
    return any(
        _path_is_within(target, scope)
        for scope in authority.get("approved_new_surface_parent_scopes", []) or []
    )


def _inspection_path_allowed(contract, path):
    authority = contract if isinstance(contract, dict) else {}
    target = _path(path).casefold().rstrip("/")
    if not target:
        return False
    allowed = {
        _path(item).casefold().rstrip("/")
        for item in authority.get("allowed_inspection_paths", []) or []
    }
    if target in allowed:
        return True
    if not authority.get("new_surface_proposal_ids"):
        return False
    return any(
        _path_is_within(target, scope)
        for scope in authority.get("approved_new_surface_parent_scopes", []) or []
    )


def _contains_requirement(text, required):
    left = " ".join(str(text or "").casefold().split())
    right = " ".join(str(required or "").casefold().split())
    if not left or not right:
        return False
    if right in left or left in right:
        return True
    left_tokens, right_tokens = set(re.findall(r"[a-z0-9_$-]{3,}", left)), set(re.findall(r"[a-z0-9_$-]{3,}", right))
    return bool(right_tokens) and len(left_tokens.intersection(right_tokens)) / len(right_tokens) >= 0.8


def _mission_protection_values(mission):
    value = mission if isinstance(mission, dict) else {}
    return _unique(
        list(value.get("do_not", []) or []) + list(value.get("invariants", []) or [])
        + list(value.get("preserves", []) or []) + list(value.get("preservation", []) or []),
        text_limit=MAX_TEXT_CHARS,
    )


def validate_mission_against_contract(mission, contract, require_identity=False):
    """Validate model-produced mission claims without granting new authority."""
    value = mission if isinstance(mission, dict) else {}
    authority = contract if isinstance(contract, dict) else {}
    errors = []
    if require_identity or any(key in value for key in ("execution_contract_id", "execution_contract_hash", "approved_plan_hash")):
        if value.get("execution_contract_id") != authority.get("execution_contract_id"):
            errors.append("mission execution_contract_id does not match")
        if value.get("execution_contract_hash") != authority.get("contract_hash"):
            errors.append("mission execution_contract_hash does not match")
        if value.get("approved_plan_hash") != authority.get("plan_hash"):
            errors.append("mission approved plan hash does not match")
    targets = _path_values(value.get("targets", []))
    for item in targets:
        if not _mutation_path_allowed(authority, item):
            errors.append(f"{item}: target is outside contract mutation scope")
    inspection_values = []
    for field in ("inspection_targets", "inspection_refs", "inspect_targets", "allowed_inspection_paths"):
        inspection_values.extend(_path_values(value.get(field, [])))
    for item in inspection_values:
        if not _inspection_path_allowed(authority, item):
            errors.append(f"{item}: inspection reference is outside contract inspection scope")
    for field in ("implementation_plan", "verification_plan", "existing_facts", "interfaces_to_reuse"):
        for item in _path_values(value.get(field, [])):
            if field == "verification_plan":
                if not _inspection_path_allowed(authority, item):
                    errors.append(f"{item}: verification reference is outside contract inspection scope")
            elif field in {"implementation_plan", "existing_facts"} and not _mutation_path_allowed(authority, item) and not _inspection_path_allowed(authority, item):
                errors.append(f"{item}: mission reference is outside contract scope")
    mission_requirement_ids = _ids(value.get("requirement_ids"), MAX_REQUIREMENTS_PER_CONTRACT)
    allowed_requirement_ids = set(str(item) for item in authority.get("requirement_ids", []) or [])
    if not set(mission_requirement_ids).issubset(allowed_requirement_ids):
        errors.append("mission requirements expand the approved requirement set")
    if isinstance(value.get("requirements"), list):
        allowed_text = [item.get("text") for item in authority.get("requirements", []) or []]
        if any(not any(_contains_requirement(item, current) for current in allowed_text) for item in value["requirements"]):
            errors.append("mission contains an unapproved requirement")
    protection = _mission_protection_values(value)
    required_protection = list(authority.get("global_do_not_touch", []) or []) + list(authority.get("structured_prohibitions", []) or [])
    required_preservation = list(authority.get("local_preservation_constraints", []) or [])
    for item in required_protection:
        if not any(_contains_requirement(current, item) for current in protection):
            errors.append("mission removed a contract prohibition/do_not_touch protection")
    for item in required_preservation:
        if not any(_contains_requirement(current, item) for current in protection):
            errors.append("mission removed a mandatory preservation constraint")
    mission_done = list(value.get("done_when", []) or [])
    for item in authority.get("done_when", []) or []:
        if not any(_contains_requirement(current, item) for current in mission_done):
            errors.append("mission done_when does not cover contract completion")
    return {"valid": not errors, "errors": errors[:30]}


MISSION_ADVICE_FIELDS = (
    "objective", "implementation_steps", "inspection_order", "interface_usage",
    "implementation_notes", "verification_notes",
)
MISSION_ADVICE_LIST_FIELDS = (
    "implementation_steps", "inspection_order", "interface_usage",
    "implementation_notes", "verification_notes",
)
MISSION_ADVICE_MAX_ITEMS = 6
MISSION_ADVICE_ITEM_CHARS = 360

# These keys may still appear in a weak model's legacy response.  They are
# explicitly recorded and ignored; none of them can enter hydrated authority.
MISSION_ADVICE_NON_AUTHORITATIVE_FIELDS = frozenset({
    "execution_contract_id", "execution_contract_hash", "contract_hash",
    "approved_plan_id", "approved_plan_hash", "plan_id", "plan_hash",
    "responsibility_type", "requirement_ids", "requirements", "obligation_types",
    "canonical_surface_ids", "surface_ids", "impact_ids", "repository_evidence_ids",
    "allowed_mutation_paths", "allowed_inspection_paths", "mutation_targets",
    "mutation_paths", "targets", "inspection_targets", "inspect_targets",
    "do_not_touch", "global_do_not_touch", "preservation", "preserves",
    "invariants", "preservation_constraints", "prohibitions", "prohibition_constraints",
    "structured_prohibitions", "test_contract",
    "integration_responsibility", "done_when", "dependencies", "dependency_ids",
    "test_file", "test_files", "new_files", "new_surface_proposals",
    "approved_new_surface_parent_scopes", "goal", "goal_anchor", "task",
    "expected_outcome", "existing_facts", "interfaces_to_reuse",
    "interface_surface_ids", "source_provenance", "provenance", "derivation",
})
MISSION_ADVICE_ALIASES = {
    "objective": ("objective", "implementation_objective", "goal_anchor", "task"),
    "implementation_steps": ("implementation_steps", "steps", "implementation_plan", "approach"),
    "inspection_order": ("inspection_order", "inspect_order"),
    "interface_usage": ("interface_usage", "interface_advice", "interfaces_to_reuse"),
    "implementation_notes": ("implementation_notes", "notes", "cautions", "project_specific_quality_rules"),
    "verification_notes": ("verification_notes", "verification_steps", "verification_plan", "checks"),
}

_ADVICE_MUTATION_VERBS = re.compile(
    r"\b(?:add|change|create|delete|edit|implement|modify|move|mutate|patch|refactor|remove|rename|replace|rewrite|set|store|touch|update|write)\w*\b",
    re.IGNORECASE,
)
_ADVICE_SAFE_VERBS = re.compile(
    r"\b(?:call|check|confirm|inspect|invoke|look\s+at|read|reference|review|reuse|use|verify)\w*\b",
    re.IGNORECASE,
)
_ADVICE_NEGATION = re.compile(
    r"(?:\bdo\s+not\b|\bdon['’]t\b|\bmust\s+not\b|\bnever\b|\bavoid\b|\bwithout\b|\binstead\s+of\b|\bno\b)",
    re.IGNORECASE,
)
_ADVICE_DUPLICATE_STATE = re.compile(
    r"\b(?:duplicate|second|another|new)\b[^.!?;]{0,70}\b(?:input|pause|game(?:-state)?|state|owner)\b"
    r"|\b(?:input|pause|game(?:-state)?|state|owner)\b[^.!?;]{0,50}\b(?:duplicate|second|another|new)\b",
    re.IGNORECASE,
)
_ADVICE_NEW_FILE = re.compile(
    r"\b(?:create|add|generate|write)\b[^.!?;]{0,50}\b(?:a\s+)?(?:new\s+)?file\b",
    re.IGNORECASE,
)
_ADVICE_OWNER_CHANGE = re.compile(
    r"\b(?:change|move|replace|shift|transfer)\b[^.!?;]{0,120}\b(?:owner|ownership)\b"
    r"|\b(?:owner|ownership)\b[^.!?;]{0,120}\b(?:change|move|replace|shift|transfer)\b",
    re.IGNORECASE,
)
_ADVICE_CLAUSE_BOUNDARY = re.compile(r"[!?;,]|\.(?=\s|$)")


def mission_advice_schema():
    """Return the small advisory schema used by the one MissionCompiler call."""
    properties = {
        "objective": {"type": "string", "maxLength": MAX_TEXT_CHARS},
    }
    for field in MISSION_ADVICE_LIST_FIELDS:
        properties[field] = {
            "type": "array", "maxItems": MISSION_ADVICE_MAX_ITEMS,
            "items": {"type": "string", "maxLength": MISSION_ADVICE_ITEM_CHARS},
        }
    # Additional properties stay syntactically tolerated so legacy weak-model
    # fields can be observed and rejected deterministically after the call.
    return {
        "type": "object", "properties": properties,
        "required": [], "additionalProperties": True,
    }


def _advice_field_value(raw, field):
    value = raw if isinstance(raw, dict) else {}
    for alias in MISSION_ADVICE_ALIASES.get(field, (field,)):
        if alias in value and value.get(alias) not in (None, "", [], {}):
            return value.get(alias), alias
    return None, None


def _advice_list(value, field):
    if value in (None, "", [], ()):
        return [], []
    values = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else None
    if values is None:
        return [], [f"{field} must be a string or list of strings"]
    errors = []
    if len(values) > MISSION_ADVICE_MAX_ITEMS:
        errors.append(
            f"{field} exceeds the bounded advice list ({len(values)} > {MISSION_ADVICE_MAX_ITEMS})"
        )
    result = []
    for index, item in enumerate(values[:MISSION_ADVICE_MAX_ITEMS], 1):
        if not isinstance(item, str) or not item.strip():
            errors.append(f"{field}[{index}] must be a non-empty string")
            continue
        normalized = " ".join(item.split())
        if len(normalized) > MISSION_ADVICE_ITEM_CHARS:
            errors.append(
                f"{field}[{index}] exceeds the bounded advice length ({MISSION_ADVICE_ITEM_CHARS} characters)"
            )
            continue
        if normalized not in result:
            result.append(normalized)
    return result, errors


def _advice_interface_name(value, canonical):
    text = " ".join(str(value or "").split()).casefold()
    compact = re.sub(r"[()\[\]{}]", "", text)
    for interface in canonical:
        expected = " ".join(str(interface or "").split()).casefold()
        if expected and (expected in text or expected.replace("()", "") in compact):
            return str(interface)
    return None


def _advice_rejected_field(key, value, reason, *, category="non_authoritative"):
    rendered = _json(value)
    if len(rendered) > 500:
        rendered = rendered[:497] + "..."
    return {"field": str(key), "category": category, "reason": str(reason), "value": rendered}


def _advice_negated(text, position):
    prefix = str(text or "")[max(0, int(position) - 70):int(position)]
    # Negation is clause-local.  A prior sentence such as ``Do not modify
    # game.js.`` must not negate a later sentence that modifies another path.
    boundaries = list(_ADVICE_CLAUSE_BOUNDARY.finditer(prefix))
    if boundaries:
        prefix = prefix[boundaries[-1].end():]
    return bool(_ADVICE_NEGATION.search(prefix))


def _advice_mutation_allowed(contract, path):
    normalized = _advice_clean_path(path)
    # Do not let the legacy path normalizer turn a traversal reference into a
    # workspace-relative path before semantic advice is checked.
    if normalized in {"..", ""} or normalized.startswith("../") or "/../" in normalized:
        return False
    return _mutation_path_allowed(contract, normalized)


def _advice_clean_path(path):
    value = str(path or "").strip().rstrip(".,;:!?)]}")
    value = value.replace("\\", "/")
    # ``./src/file`` is a workspace-relative spelling of ``src/file``.  Keep
    # ``../`` intact so a traversal reference cannot become authorized by
    # normalization.
    while value.startswith("./"):
        value = value[2:]
    return value


def _advice_known_repository_paths(contract):
    """Collect path evidence already present in the current contract."""
    authority = contract if isinstance(contract, dict) else {}
    values = []
    for field in (
        "allowed_mutation_paths", "allowed_inspection_paths", "global_do_not_touch",
        "approved_new_surface_parent_scopes",
    ):
        values.extend(authority.get(field, []) or [])
    values.extend(
        item.get("path") for item in authority.get("relevant_repository_facts", []) or []
        if isinstance(item, dict)
    )
    return {
        _advice_clean_path(item).casefold()
        for item in values
        if _advice_clean_path(item)
    }


def _advice_known_repository_roots(contract):
    """Return top-level repository directories implied by contract evidence."""
    roots = set()
    for value in _advice_known_repository_paths(contract):
        if value.startswith("/") or _WINDOWS_PATH_RE.match(value) or value.startswith("../"):
            continue
        first = value.split("/", 1)[0].strip()
        if first and first not in {".", ".."}:
            roots.add(first)
    return roots


def _advice_path_is_under_root(path, root):
    target = str(path or "").casefold().rstrip("/")
    parent = str(root or "").casefold().rstrip("/")
    return bool(target and parent and (target == parent or target.startswith(parent + "/")))


def classify_code_location_reference(value, contract=None):
    """Classify one lexical candidate using repository/path evidence.

    A slash alone is intentionally insufficient.  The result is diagnostic
    data only; it never grants mutation authority.
    """
    raw_token = str(value or "").strip().rstrip(".,;:!?)]}")
    token = _advice_clean_path(raw_token)
    if not token:
        return None
    normalized = token.casefold()
    known_paths = _advice_known_repository_paths(contract)
    known_roots = _advice_known_repository_roots(contract)
    suffix = normalized.rsplit("/", 1)[-1]
    extension = suffix.rsplit(".", 1)[-1] if "." in suffix else ""
    basis = None
    if normalized.rstrip("/") in {item.rstrip("/") for item in known_paths}:
        basis = "CANONICAL_PATH"
    elif _WINDOWS_PATH_RE.match(normalized):
        basis = "WINDOWS_PATH"
    elif normalized.startswith("/"):
        basis = "ABSOLUTE_PATH"
    elif _EXPLICIT_RELATIVE_PATH_RE.match(raw_token.replace("\\", "/")):
        basis = "EXPLICIT_RELATIVE_PATH"
    elif extension in _CODE_PATH_EXTENSIONS:
        basis = "FILE_EXTENSION"
    elif any(_advice_path_is_under_root(normalized, root) for root in known_roots):
        basis = "KNOWN_REPOSITORY_ROOT"
    return {
        "text": raw_token,
        "path": token,
        "classification": "CODE_PATH" if basis else "AMBIGUOUS_TEXT",
        "confidence_basis": basis or "BARE_SLASH_COMPOUND",
    }


def _advice_safe_intent(verb):
    value = str(verb or "").casefold()
    if value.startswith(("call", "invoke", "reference", "reuse", "use")):
        return "REUSE"
    return "INSPECTION"


def _advice_action_events(text):
    actions = []
    for match in _ADVICE_MUTATION_VERBS.finditer(text):
        if not _advice_negated(text, match.start()):
            actions.append((match.start(), match.end(), "MUTATION", match.group(0)))
    for match in _ADVICE_SAFE_VERBS.finditer(text):
        actions.append((match.start(), match.end(), _advice_safe_intent(match.group(0)), match.group(0)))
    return sorted(actions, key=lambda item: (item[0], item[1]))


def _advice_local_intent(text, start, end, actions=None):
    """Find intent only in the clause local to one detected candidate."""
    actions = list(actions if actions is not None else _advice_action_events(text))
    previous = [item for item in actions if item[1] <= start]
    candidate = previous[-1] if previous else None
    if candidate is not None:
        between = text[candidate[1]:start]
        if _ADVICE_CLAUSE_BOUNDARY.search(between):
            candidate = None
    if candidate is None:
        following = [item for item in actions if item[0] >= end]
        if following:
            next_candidate = following[0]
            between = text[end:next_candidate[0]]
            if next_candidate[0] - end <= 70 and not _ADVICE_CLAUSE_BOUNDARY.search(between):
                candidate = next_candidate
    return candidate[2] if candidate is not None else "UNKNOWN"


def _advice_path_references(text, contract=None):
    """Return classified path candidates with clause-local semantic intent."""
    source = str(text or "")
    actions = _advice_action_events(source)
    references = []
    for path_match in _PATH_RE.finditer(source):
        reference = classify_code_location_reference(path_match.group(1), contract)
        if reference is None:
            continue
        reference_end = path_match.start(1) + len(reference.get("text", ""))
        reference["intent"] = _advice_local_intent(
            source, path_match.start(1), reference_end, actions,
        )
        references.append(reference)
    return references


def _advice_path_mutation_states(text, contract=None):
    """Preserve the legacy tuple shape for callers while using local intent."""
    return [
        (item["path"], item.get("intent") == "MUTATION")
        for item in _advice_path_references(text, contract)
        if item.get("classification") == "CODE_PATH"
    ]


def _advice_conflict_analysis(advice, contract):
    """Analyze bounded advice without treating prose slash compounds as paths."""
    authority = contract if isinstance(contract, dict) else {}
    errors = []
    path_candidates = []
    path_candidates_rejected = []
    mutation_paths = {
        _path(item).casefold().rstrip("/")
        for item in authority.get("allowed_mutation_paths", []) or []
    }
    inspection_paths = {
        _path(item).casefold().rstrip("/")
        for item in authority.get("allowed_inspection_paths", []) or []
    }
    dnt_paths = {
        _path(item).casefold().rstrip("/")
        for item in authority.get("global_do_not_touch", []) or []
    }
    responsibility = str(authority.get("responsibility_type", ""))
    text_fields = (
        ("objective", advice.get("objective", "")),
        ("implementation_steps", advice.get("implementation_steps", [])),
        ("inspection_order", advice.get("inspection_order", [])),
        ("interface_usage", advice.get("interface_usage", [])),
        ("implementation_notes", advice.get("implementation_notes", [])),
        ("verification_notes", advice.get("verification_notes", [])),
    )
    for field, values in text_fields:
        items = [values] if isinstance(values, str) else list(values or [])
        for item in items:
            text = " ".join(str(item).split())
            if not text:
                continue
            mutation_matches = [match for match in _ADVICE_MUTATION_VERBS.finditer(text) if not _advice_negated(text, match.start())]
            if mutation_matches:
                path_states = _advice_path_references(text, authority)
                path_candidates.extend(path_states)
                for reference in path_states:
                    if reference.get("classification") != "CODE_PATH" or reference.get("intent") != "MUTATION":
                        continue
                    clean_path = reference.get("path", "")
                    normalized_path = clean_path.casefold().rstrip("/")
                    if not normalized_path:
                        continue
                    if normalized_path in dnt_paths:
                        rejected = _copy(reference)
                        rejected["rejection_reason"] = "DNT_PATH_MUTATION"
                        path_candidates_rejected.append(rejected)
                        errors.append(
                            f"{field}: do_not_touch path {clean_path} was given mutation instructions"
                        )
                    elif not _advice_mutation_allowed(authority, clean_path):
                        rejected = _copy(reference)
                        rejected["rejection_reason"] = "UNAPPROVED_PATH_MUTATION"
                        path_candidates_rejected.append(rejected)
                        errors.append(
                            f"{field}: explicit mutation of unapproved path {clean_path}"
                        )
                    elif normalized_path not in mutation_paths and normalized_path in inspection_paths:
                        rejected = _copy(reference)
                        rejected["rejection_reason"] = "INSPECTION_ONLY_PATH_MUTATION"
                        path_candidates_rejected.append(rejected)
                        errors.append(
                            f"{field}: inspection-only path {clean_path} was given mutation instructions"
                        )
                if responsibility not in {MUTATION, TEST_MUTATION}:
                    errors.append(
                        f"{field}: {responsibility} responsibility cannot contain positive mutation instructions"
                    )
                if responsibility == TEST_MUTATION and not path_states and re.search(
                    r"\b(?:source|implementation|application)\b", text, re.IGNORECASE,
                ):
                    errors.append(
                        f"{field}: TEST_MUTATION advice cannot direct source implementation changes"
                    )
            else:
                path_candidates.extend(_advice_path_references(text, authority))
            for match in _ADVICE_DUPLICATE_STATE.finditer(text):
                context_window = text[max(0, match.start() - 70):match.end() + 1]
                if not _advice_negated(text, match.start()) and not _ADVICE_NEGATION.search(context_window):
                    errors.append(
                        f"{field}: advice proposes duplicate or new state/owner creation"
                    )
            for match in _ADVICE_OWNER_CHANGE.finditer(text):
                if not _advice_negated(text, match.start()):
                    errors.append(f"{field}: advice changes verified ownership")
            if _ADVICE_NEW_FILE.search(text) and not authority.get("target_new_surface_proposal_ids"):
                errors.append(f"{field}: advice proposes an unapproved new file")
            if responsibility == TEST_MUTATION and re.search(
                r"\b(?:src/|source\s+file|implementation)\b", text, re.IGNORECASE,
            ) and mutation_matches:
                errors.append(f"{field}: advice conflicts with TEST_MUTATION responsibility")
    return (
        _unique(errors, limit=30, text_limit=MAX_TEXT_CHARS),
        path_candidates,
        path_candidates_rejected,
    )


def _advice_conflicts(advice, contract):
    """Compatibility wrapper returning only semantic conflict messages."""
    return _advice_conflict_analysis(advice, contract)[0]


def sanitize_mission_advice(raw, contract):
    """Validate bounded semantic advice while discarding model authority claims."""
    value = raw if isinstance(raw, dict) else {}
    errors = []
    rejected = []
    recognized = set()
    advice = {"objective": ""}
    for field in MISSION_ADVICE_FIELDS:
        raw_value, alias = _advice_field_value(value, field)
        recognized.update(MISSION_ADVICE_ALIASES.get(field, (field,)))
        if field == "objective":
            if raw_value in (None, ""):
                continue
            if not isinstance(raw_value, str) or not raw_value.strip():
                errors.append("objective must be a non-empty string")
                continue
            normalized = " ".join(raw_value.split())
            if len(normalized) > MAX_TEXT_CHARS:
                errors.append(f"objective exceeds the bounded advice length ({MAX_TEXT_CHARS} characters)")
            else:
                advice[field] = normalized
            continue
        normalized, field_errors = _advice_list(raw_value, field)
        errors.extend(field_errors)
        advice[field] = normalized
        if field == "interface_usage" and normalized:
            canonical = list((contract or {}).get("interfaces_to_reuse", []) or [])
            accepted = []
            for suggestion in normalized:
                match = _advice_interface_name(suggestion, canonical)
                if match and match not in accepted:
                    accepted.append(match)
                elif not match:
                    rejected.append(_advice_rejected_field(
                        field, suggestion, "unknown interface suggestion dropped",
                        category="unknown_optional_interface",
                    ))
            advice[field] = accepted

    if not advice.get("objective"):
        errors.append("semantic advice requires a concise objective")
    for key, item in value.items():
        if key in recognized:
            continue
        if key in MISSION_ADVICE_NON_AUTHORITATIVE_FIELDS:
            rejected.append(_advice_rejected_field(
                key, item, "model field cannot author execution authority",
                category=("non_authoritative_scope" if key in {
                    "mutation_targets", "mutation_paths", "targets", "allowed_mutation_paths",
                    "allowed_inspection_paths", "inspection_targets", "inspect_targets",
                } else "non_authoritative"),
            ))
        else:
            rejected.append(_advice_rejected_field(
                key, item, "unknown optional model field dropped", category="unknown_optional_field",
            ))
    # A recognized legacy alias can still be semantic advice, but its source
    # field must be observable as non-authoritative whenever it could have
    # carried authority in the old rich mission schema.
    legacy_used = {
        alias for field in MISSION_ADVICE_FIELDS
        for alias in MISSION_ADVICE_ALIASES.get(field, ())
        if alias in value and alias != field and value.get(alias) not in (None, "", [], {})
    }
    for key in sorted(legacy_used):
        if key in MISSION_ADVICE_NON_AUTHORITATIVE_FIELDS and not any(
            item.get("field") == key for item in rejected
        ):
            rejected.append(_advice_rejected_field(
                key, value.get(key), "legacy authority-shaped alias retained only as advice",
                category="non_authoritative",
            ))
    if isinstance(contract, dict) and contract:
        conflicts, path_candidates, path_candidates_rejected = _advice_conflict_analysis(advice, contract)
    else:
        conflicts, path_candidates, path_candidates_rejected = [], [], []
    return {
        "valid": bool(isinstance(raw, dict) and not errors and not conflicts),
        "advice": advice,
        "rejected_fields": rejected,
        "semantic_conflicts": conflicts,
        "errors": _unique(errors, limit=30, text_limit=MAX_TEXT_CHARS),
        "semantic_path_candidates": path_candidates,
        "semantic_path_candidates_rejected": path_candidates_rejected,
        "semantic_path_false_positive_avoided": sum(
            1 for item in path_candidates if item.get("classification") != "CODE_PATH"
        ),
        "semantic_mutation_conflicts": conflicts,
    }


def validate_mission_advice_shape(value):
    """Small validator passed to structured_model_call before contract binding."""
    checked = sanitize_mission_advice(value, None)
    return bool(checked.get("valid"))


def _completed_dependency_summaries(values, allowed_ids=None):
    allowed = {str(item) for item in list(allowed_ids or [])}
    result = []
    for item in list(values or []):
        if not isinstance(item, dict):
            continue
        task_id = str(item.get("task_id") or item.get("execution_contract_id") or "")
        status = str(item.get("status", "")).casefold()
        if not task_id or status not in {"done", "verified", "passed"}:
            continue
        if allowed and task_id not in allowed:
            continue
        result.append({
            "task_id": _text(task_id, 100),
            "status": _text(item.get("status"), 40),
            "summary": _text(item.get("summary"), 500),
            "changed_files": _unique(
                [_path(path) for path in item.get("changed_files", []) or []],
                limit=12, text_limit=MAX_PATH_CHARS,
            ),
        })
    if allowed:
        by_id = {}
        for item in result:
            by_id.setdefault(str(item.get("task_id")), item)
        return [
            by_id[dependency_id] for dependency_id in list(allowed_ids or [])
            if dependency_id in by_id
        ][:MAX_DEPENDENCIES_PER_CONTRACT]
    return result[:MAX_DEPENDENCIES_PER_CONTRACT]


def hydrate_worker_mission(contract, advice, dependency_summaries=None):
    """Construct the rich Worker Mission from immutable contract authority."""
    authority = contract if isinstance(contract, dict) else {}
    semantic = advice if isinstance(advice, dict) else {}
    normalized_advice = sanitize_mission_advice(semantic, authority)
    if normalized_advice.get("valid"):
        semantic = normalized_advice.get("advice", {})
    dependencies = _completed_dependency_summaries(
        dependency_summaries, authority.get("dependencies", []) or [],
    )
    hash_payload = {
        "execution_contract_id": authority.get("execution_contract_id"),
        "execution_contract_hash": authority.get("contract_hash"),
        "approved_plan_id": authority.get("plan_id"),
        "approved_plan_hash": authority.get("plan_hash"),
        "implementation_advice": _copy(semantic),
        "completed_dependency_summaries": _copy(dependencies),
    }
    mission_hash = deterministic_hash(hash_payload)
    mission = {
        "mission_id": f"MISSION-{mission_hash[:16].upper()}",
        "mission_hash": mission_hash,
        "execution_contract_id": authority.get("execution_contract_id"),
        "execution_contract_hash": authority.get("contract_hash"),
        "approved_plan_id": authority.get("plan_id"),
        "approved_plan_hash": authority.get("plan_hash"),
        "goal": _copy(authority.get("goal")),
        "responsibility_type": _copy(authority.get("responsibility_type")),
        "plan_node_ids": _copy(authority.get("plan_node_ids", []) or []),
        "requirement_ids": _copy(authority.get("requirement_ids", []) or []),
        "obligation_types": _copy(authority.get("obligation_types", []) or []),
        "requirements": _copy(authority.get("requirements", []) or []),
        "canonical_surface_ids": _copy(authority.get("canonical_surface_ids", []) or []),
        "repository_evidence_ids": _copy(authority.get("repository_evidence_ids", []) or []),
        "allowed_mutation_surface_ids": _copy(authority.get("allowed_mutation_surface_ids", []) or []),
        "allowed_mutation_paths": _copy(authority.get("allowed_mutation_paths", []) or []),
        "allowed_inspection_surface_ids": _copy(authority.get("allowed_inspection_surface_ids", []) or []),
        "allowed_inspection_paths": _copy(authority.get("allowed_inspection_paths", []) or []),
        # The existing Worker event reader uses this alias; it is copied from
        # the contract exactly, not from semantic advice.
        "targets": _copy(authority.get("allowed_mutation_paths", []) or []),
        "interfaces_to_reuse": _copy(authority.get("interfaces_to_reuse", []) or []),
        "interface_surface_ids": _copy(authority.get("interface_surface_ids", []) or []),
        "preservation": _copy(authority.get("local_preservation_constraints", []) or []),
        "prohibitions": _copy(authority.get("structured_prohibitions", []) or []),
        "do_not_touch": _copy(authority.get("global_do_not_touch", []) or []),
        "test_contract": _copy(authority.get("test_contract", []) or []),
        "integration_responsibility": _copy(authority.get("integration_responsibility", []) or []),
        "done_when": _copy(authority.get("done_when", []) or []),
        "dependency_ids": _copy(authority.get("dependencies", []) or []),
        "dependencies": dependencies,
        "implementation_advice": _copy(semantic),
    }
    return mission


def validate_hydrated_worker_mission(mission, contract, dependency_summaries=None):
    """Validate the deterministic hydrated mission against contract authority."""
    value = mission if isinstance(mission, dict) else {}
    authority = contract if isinstance(contract, dict) else {}
    errors = []
    mission_chars = _serialized_chars(value)
    if mission_chars > MAX_HYDRATED_MISSION_CHARS:
        errors.append(
            f"{HYDRATED_MISSION_TOO_LARGE}: hydrated mission exceeds its internal artifact bound "
            f"({mission_chars} > {MAX_HYDRATED_MISSION_CHARS})"
        )
    expected_fields = {
        "mission_id", "mission_hash", "execution_contract_id", "execution_contract_hash",
        "approved_plan_id", "approved_plan_hash", "goal", "responsibility_type",
        "plan_node_ids", "requirement_ids", "obligation_types", "requirements",
        "canonical_surface_ids", "repository_evidence_ids", "allowed_mutation_surface_ids",
        "allowed_mutation_paths", "allowed_inspection_surface_ids", "allowed_inspection_paths",
        "targets", "interfaces_to_reuse", "interface_surface_ids", "preservation",
        "prohibitions", "do_not_touch", "test_contract", "integration_responsibility",
        "done_when", "dependency_ids", "dependencies", "implementation_advice",
    }
    for key in value:
        if key not in expected_fields:
            errors.append(f"hydrated mission contains unexpected field {key}")
    exact_fields = (
        ("execution_contract_id", "execution_contract_id"),
        ("execution_contract_hash", "contract_hash"),
        ("approved_plan_id", "plan_id"),
        ("approved_plan_hash", "plan_hash"),
        ("goal", "goal"),
        ("responsibility_type", "responsibility_type"),
        ("plan_node_ids", "plan_node_ids"),
        ("requirement_ids", "requirement_ids"),
        ("obligation_types", "obligation_types"),
        ("requirements", "requirements"),
        ("canonical_surface_ids", "canonical_surface_ids"),
        ("repository_evidence_ids", "repository_evidence_ids"),
        ("allowed_mutation_surface_ids", "allowed_mutation_surface_ids"),
        ("allowed_inspection_surface_ids", "allowed_inspection_surface_ids"),
        ("allowed_mutation_paths", "allowed_mutation_paths"),
        ("allowed_inspection_paths", "allowed_inspection_paths"),
        ("interfaces_to_reuse", "interfaces_to_reuse"),
        ("interface_surface_ids", "interface_surface_ids"),
        ("preservation", "local_preservation_constraints"),
        ("prohibitions", "structured_prohibitions"),
        ("do_not_touch", "global_do_not_touch"),
        ("test_contract", "test_contract"),
        ("integration_responsibility", "integration_responsibility"),
        ("done_when", "done_when"),
        ("dependency_ids", "dependencies"),
    )
    for mission_field, contract_field in exact_fields:
        if value.get(mission_field) != authority.get(contract_field):
            errors.append(f"{mission_field} does not exactly match contract authority")
    if value.get("targets") != authority.get("allowed_mutation_paths"):
        errors.append("targets do not exactly match contract mutation scope")
    expected_dependencies = _completed_dependency_summaries(
        dependency_summaries, authority.get("dependencies", []) or [],
    ) if dependency_summaries is not None else list(value.get("dependencies", []) or [])
    if value.get("dependencies") != expected_dependencies:
        errors.append("dependencies do not match completed approved dependency summaries")
    required_dependency_ids = [str(item) for item in authority.get("dependencies", []) or []]
    actual_dependency_ids = [
        str(item.get("task_id")) for item in list(value.get("dependencies", []) or [])
        if isinstance(item, dict)
    ]
    if actual_dependency_ids != required_dependency_ids:
        errors.append("mission dependency summaries do not cover exactly the approved dependencies")
    if any(
        str(item.get("task_id")) not in set(required_dependency_ids)
        or str(item.get("status", "")).casefold() not in {"done", "verified", "passed"}
        for item in list(value.get("dependencies", []) or []) if isinstance(item, dict)
    ):
        errors.append("mission contains an unapproved dependency summary")
    advice_check = sanitize_mission_advice(value.get("implementation_advice"), authority)
    if not advice_check.get("valid"):
        errors.extend(f"implementation_advice: {item}" for item in advice_check.get("errors", []))
        errors.extend(f"implementation_advice: {item}" for item in advice_check.get("semantic_conflicts", []))
    elif advice_check.get("rejected_fields") or advice_check.get("advice") != value.get("implementation_advice"):
        errors.append("implementation_advice contains non-authoritative or non-canonical fields")
    hash_payload = {
        "execution_contract_id": authority.get("execution_contract_id"),
        "execution_contract_hash": authority.get("contract_hash"),
        "approved_plan_id": authority.get("plan_id"),
        "approved_plan_hash": authority.get("plan_hash"),
        "implementation_advice": _copy(value.get("implementation_advice", {})),
        "completed_dependency_summaries": _copy(value.get("dependencies", []) or []),
    }
    expected_hash = deterministic_hash(hash_payload)
    if value.get("mission_hash") != expected_hash:
        errors.append("mission hash does not match contract identity, advice, and dependencies")
    if value.get("mission_id") != f"MISSION-{expected_hash[:16].upper()}":
        errors.append("mission_id does not match deterministic mission hash")
    for key in value:
        if str(key).startswith("raw_") or key in {"raw_response", "raw_mission_compiler_output"}:
            errors.append(f"hydrated mission contains raw model field {key}")
    return {
        "valid": not errors,
        "errors": errors[:40],
        "serialized_chars": mission_chars,
        "internal_limit": MAX_HYDRATED_MISSION_CHARS,
    }


def hydrated_worker_mission_chars(mission):
    """Return the serialized size of the full internal mission artifact."""
    return _serialized_chars(mission if isinstance(mission, dict) else {})


_WORKER_CONTEXT_EXCLUDED_STRUCTURES = (
    "full approved plan", "approved plan snapshot", "execution graph",
    "full plan nodes", "obligation ledger", "full Project Brain",
    "full Task Brain", "full Source Ledger", "raw Planner output",
    "raw Challenger output", "raw MissionCompiler output",
)
_WORKER_CONTEXT_INCLUDED_SECTIONS = (
    "identity", "goal", "responsibility", "mutation scope",
    "inspection scope", "interfaces", "requirements", "preservation",
    "prohibitions", "do_not_touch", "test contract", "done_when",
    "dependencies", "repository facts", "implementation advice",
    "execution invariants",
)


def _compact_worker_repository_facts(contract):
    """Keep only the small fact needed to orient this Worker responsibility."""
    result = []
    for item in list((contract or {}).get("relevant_repository_facts", []) or [])[:MAX_REPOSITORY_FACTS_PER_CONTRACT]:
        if not isinstance(item, dict):
            continue
        fact = _text(item.get("fact"), MAX_TEXT_CHARS)
        path = _path(item.get("path"))
        symbol = _text(item.get("symbol"), 240)
        evidence_id = str(item.get("evidence_id") or "")
        if not fact and not path and not symbol:
            continue
        # Deliberately omit line ranges, hashes, provenance objects, and the
        # rest of the full REPOSITORY_EVIDENCE record.  Those remain internal.
        result.append({
            "evidence_id": evidence_id,
            "fact": fact,
            "path": path,
            "symbol": symbol,
        })
    return result


def _worker_context_authority(mission, contract):
    """Build the compact authority portion from the validated contract."""
    value = mission if isinstance(mission, dict) else {}
    authority = contract if isinstance(contract, dict) else {}
    requirements = []
    for item in list(authority.get("requirements", []) or []):
        if isinstance(item, dict):
            requirements.append({
                "requirement_id": str(item.get("requirement_id") or ""),
                "text": str(item.get("text") or ""),
            })
        else:
            requirements.append({"requirement_id": "", "text": str(item or "")})
    result = {
        "mission_id": value.get("mission_id"),
        "mission_hash": value.get("mission_hash"),
        "execution_contract_id": authority.get("execution_contract_id"),
        "execution_contract_hash": authority.get("contract_hash"),
        "approved_plan_id": authority.get("plan_id"),
        "approved_plan_hash": authority.get("plan_hash"),
        "goal": _copy(authority.get("goal")),
        "responsibility_type": _copy(authority.get("responsibility_type")),
        "allowed_mutation_paths": _copy(authority.get("allowed_mutation_paths", []) or []),
        "allowed_inspection_paths": _copy(authority.get("allowed_inspection_paths", []) or []),
        "interfaces_to_reuse": _copy(authority.get("interfaces_to_reuse", []) or []),
        "requirements": requirements,
        "preservation": _copy(authority.get("local_preservation_constraints", []) or []),
        "prohibitions": _copy(authority.get("structured_prohibitions", []) or []),
        "do_not_touch": _copy(authority.get("global_do_not_touch", []) or []),
        "test_contract": _copy(authority.get("test_contract", []) or []),
        "done_when": _copy(authority.get("done_when", []) or []),
        "dependencies": _copy(value.get("dependencies", []) or []),
        "relevant_repository_facts": _compact_worker_repository_facts(authority),
    }
    if authority.get("execution_invariant_set_hash"):
        result.update({
            "execution_invariant_set_hash": authority.get("execution_invariant_set_hash"),
            "execution_invariant_ids": _copy(
                authority.get("execution_invariant_relevant_ids")
                or authority.get("execution_invariant_ids", []) or [],
            ),
            "execution_invariant_relevant_ids": _copy(
                authority.get("execution_invariant_relevant_ids", []) or [],
            ),
            "execution_invariants": _copy(
                authority.get("execution_invariants")
                or (authority.get("execution_invariant_projection", {}) or {}).get("invariants", [])
                or [],
            ),
            "execution_invariant_projection": _copy(
                authority.get("execution_invariant_projection", {}) or {},
            ),
        })
    return result


def _worker_context_advice_items(advice):
    """Return deterministic whole-item semantic advice candidates."""
    value = advice if isinstance(advice, dict) else {}
    result = []
    objective = value.get("objective")
    if objective not in (None, ""):
        result.append(("objective", "objective", objective))
    for field in (
        "implementation_steps", "interface_usage", "verification_notes",
        "implementation_notes", "inspection_order",
    ):
        for index, item in enumerate(list(value.get(field, []) or []), 1):
            result.append((f"{field}[{index}]", field, item))
    return result


def _worker_context_advice_selection_labels(advice, source_advice):
    """Label retained advice against the original full-advice positions."""
    selected = advice if isinstance(advice, dict) else {}
    source = source_advice if isinstance(source_advice, dict) else {}
    labels = []
    if selected.get("objective") not in (None, ""):
        labels.append("objective")
    for field in (
        "implementation_steps", "interface_usage", "verification_notes",
        "implementation_notes", "inspection_order",
    ):
        source_values = list(source.get(field, []) or [])
        cursor = 0
        for item in list(selected.get(field, []) or []):
            try:
                index = source_values.index(item, cursor) + 1
            except ValueError:
                labels.append(f"{field}[?]")
                continue
            labels.append(f"{field}[{index}]")
            cursor = index
    return labels


def _make_worker_context_projection(authority, advice, audit):
    projection = _copy(authority)
    projection["implementation_advice"] = _copy(advice if isinstance(advice, dict) else {})
    projection["projection_audit"] = _copy(audit if isinstance(audit, dict) else {})
    projection["rendering_version"] = WORKER_CONTEXT_RENDERING_VERSION
    projection["worker_context_projection_hash"] = deterministic_hash(
        _without(projection, "worker_context_projection_hash"),
    )
    return projection


def _render_worker_context_projection_lines(projection, *, include_advice=True):
    """Render the model-facing projection without serializing internal JSON."""
    value = projection if isinstance(projection, dict) else {}
    lines = [
        "AUTHORITATIVE CONTRACT (AUTHORITATIVE EXECUTION CONTRACT)",
        "Execution authority is fixed by the validated contract; this context is informational.",
        "IDENTITY:",
        f"- plan: {value.get('approved_plan_id')} / {value.get('approved_plan_hash')}",
        f"- contract: {value.get('execution_contract_id')} / {value.get('execution_contract_hash')}",
        f"- mission: {value.get('mission_id')} / {value.get('mission_hash')}",
        "GOAL:",
        str(value.get("goal") or "(none)"),
        "RESPONSIBILITY:",
        f"{value.get('responsibility_type') or '(none)'}",
    ]

    def add_list(title, values, formatter=None):
        lines.append(f"{title}:")
        values = list(values or [])
        if not values:
            lines.append("- (none)")
            return
        for item in values:
            lines.append("- " + (formatter(item) if formatter else str(item)))

    add_list("MAY MODIFY", value.get("allowed_mutation_paths"))
    add_list("MAY INSPECT", value.get("allowed_inspection_paths"))
    add_list("REUSE", value.get("interfaces_to_reuse"))
    add_list(
        "REQUIREMENTS",
        value.get("requirements"),
        lambda item: (
            f"{item.get('requirement_id')}: {item.get('text')}"
            if isinstance(item, dict) else str(item)
        ),
    )
    add_list("MUST PRESERVE", value.get("preservation"))
    add_list("MUST NOT DO", value.get("prohibitions"))
    add_list("DO NOT MODIFY", value.get("do_not_touch"))
    add_list("TEST CONTRACT", value.get("test_contract"))
    add_list("DONE WHEN", value.get("done_when"))
    add_list(
        "COMPLETED DEPENDENCIES",
        value.get("dependencies"),
        lambda item: (
            f"{item.get('task_id')} [{item.get('status')}]: {item.get('summary')}"
            + (f" (changed: {', '.join(item.get('changed_files', []) or [])})"
               if item.get("changed_files") else "")
            if isinstance(item, dict) else str(item)
        ),
    )
    add_list(
        "VERIFIED REPOSITORY FACTS",
        value.get("relevant_repository_facts"),
        lambda item: (
            f"{item.get('evidence_id')}: {item.get('fact')}"
            + (f" [{item.get('path')}; {item.get('symbol')}]"
               if item.get("path") or item.get("symbol") else "")
            if isinstance(item, dict) else str(item)
        ),
    )
    if value.get("execution_invariant_set_hash"):
        try:
            invariant_lines = invariant.render_worker_execution_invariant_projection(
                value.get("execution_invariant_projection", {}) or {},
                max_chars=MAX_CONTEXT_CHARS,
            )
        except invariant.ExecutionInvariantError as exc:
            raise ExecutionContractError(
                exc.code, str(exc), details=getattr(exc, "details", []),
            ) from exc
        lines.extend(invariant_lines.splitlines())
    if include_advice:
        advice = value.get("implementation_advice")
        if isinstance(advice, dict) and advice:
            lines.append("IMPLEMENTATION ADVICE:")
            if advice.get("objective"):
                lines.append(f"- Objective: {advice['objective']}")
            labels = {
                "implementation_steps": "Step",
                "interface_usage": "Interface",
                "verification_notes": "Verify",
                "implementation_notes": "Note",
                "inspection_order": "Inspect",
            }
            for field in (
                "implementation_steps", "interface_usage", "verification_notes",
                "implementation_notes", "inspection_order",
            ):
                for item in list(advice.get(field, []) or []):
                    lines.append(f"- {labels[field]}: {item}")
        else:
            lines.extend(("IMPLEMENTATION ADVICE:", "- (none)"))
    return lines


def render_worker_context_projection(projection, max_chars=MAX_CONTEXT_CHARS):
    """Render exactly the bounded Worker context represented by a projection."""
    limit = MAX_CONTEXT_CHARS if max_chars is None else max(1, int(max_chars))
    rendered = "\n".join(_render_worker_context_projection_lines(projection))
    if len(rendered) > limit:
        raise ExecutionContractError(
            WORKER_CONTEXT_TOO_LARGE,
            f"rendered Worker context exceeds its bound ({len(rendered)} > {limit})",
        )
    return rendered


def _worker_context_audit(
    *, full_mission_chars, required_authority_chars,
    required_authority_serialized_chars, optional_advice_chars_before,
    optional_advice_chars_retained, final_projection_chars,
    rendered_context_chars, context_limit, retained, dropped,
):
    return {
        "full_mission_chars": int(full_mission_chars),
        "required_authority_chars": int(required_authority_chars),
        "required_authority_serialized_chars": int(required_authority_serialized_chars),
        "optional_advice_chars_before_projection": int(optional_advice_chars_before),
        "optional_advice_chars_retained": int(optional_advice_chars_retained),
        "final_projection_chars": int(final_projection_chars),
        "rendered_context_chars": int(rendered_context_chars),
        "context_limit": int(context_limit),
        # Counts keep the projection itself compact.  The exact labels are
        # retained in the orchestration evidence/cache alongside this object.
        "optional_items_retained": len(list(retained)),
        "optional_items_dropped": len(list(dropped)),
        "authority_items_dropped": 0,
        "authority_overflow": False,
        "included_sections": list(_WORKER_CONTEXT_INCLUDED_SECTIONS),
        "excluded_internal_structures": list(_WORKER_CONTEXT_EXCLUDED_STRUCTURES),
    }


def build_worker_context_projection(
    mission, contract, dependency_summaries=None, max_chars=MAX_CONTEXT_CHARS,
):
    """Project one validated rich mission into a deterministic Worker context."""
    value = mission if isinstance(mission, dict) else {}
    authority = contract if isinstance(contract, dict) else {}
    limit = MAX_CONTEXT_CHARS if max_chars is None else max(1, int(max_chars))
    mission_chars = hydrated_worker_mission_chars(value)
    if mission_chars > MAX_HYDRATED_MISSION_CHARS:
        raise ExecutionContractError(
            HYDRATED_MISSION_TOO_LARGE,
            f"hydrated mission exceeds its internal artifact bound ({mission_chars} > {MAX_HYDRATED_MISSION_CHARS})",
        )
    mission_check = validate_hydrated_worker_mission(
        value, authority, dependency_summaries,
    )
    if not mission_check.get("valid"):
        raise ExecutionContractError(
            MISSION_CONTRACT_VIOLATION,
            "; ".join(mission_check.get("errors", [])) or "full hydrated mission is invalid",
        )

    authority_projection = _worker_context_authority(value, authority)
    full_advice = _copy(value.get("implementation_advice", {}) or {})
    advice_candidates = _worker_context_advice_items(full_advice)
    all_labels = [item[0] for item in advice_candidates]
    optional_advice_chars_before = _serialized_chars(full_advice)
    empty_audit = _worker_context_audit(
        full_mission_chars=mission_chars,
        required_authority_chars=0,
        required_authority_serialized_chars=0,
        optional_advice_chars_before=optional_advice_chars_before,
        optional_advice_chars_retained=0,
        final_projection_chars=0,
        rendered_context_chars=0,
        context_limit=limit,
        retained=[], dropped=[],
    )
    required_projection = _make_worker_context_projection(
        authority_projection, {}, empty_audit,
    )
    required_rendered = "\n".join(
        _render_worker_context_projection_lines(required_projection, include_advice=False),
    )
    required_rendered_chars = len(required_rendered)
    required_serialized_chars = _serialized_chars(required_projection)
    # Only the deterministic textual rendering is sent to the Worker.  The
    # structured projection is an internal auditable artifact and may remain
    # richer than the model-facing character budget.
    if required_rendered_chars > limit:
        overflow_code = (
            WORKER_EXECUTION_INVARIANT_CONTEXT_OVERFLOW
            if authority_projection.get("execution_invariant_set_hash")
            else WORKER_CONTEXT_AUTHORITY_TOO_LARGE
        )
        raise ExecutionContractError(
            overflow_code,
            "required Worker authority cannot fit without dropping authority",
            details=[
                f"required_rendered_chars={required_rendered_chars}",
                f"required_projection_chars={required_serialized_chars}",
                f"context_limit={limit}",
            ],
        )

    retained = []
    dropped = []

    def advice_from_labels(labels):
        selected = {}
        for label, field, item in advice_candidates:
            if label == "objective":
                if label in labels:
                    selected["objective"] = item
                continue
            if label not in labels:
                continue
            selected.setdefault(field, []).append(item)
        return selected

    def candidate_projection(labels):
        selected_advice = advice_from_labels(labels)
        future_dropped = [label for label in all_labels if label not in labels]
        audit = _worker_context_audit(
            full_mission_chars=mission_chars,
            required_authority_chars=required_rendered_chars,
            required_authority_serialized_chars=required_serialized_chars,
            optional_advice_chars_before=optional_advice_chars_before,
            optional_advice_chars_retained=_serialized_chars(selected_advice),
            final_projection_chars=0,
            rendered_context_chars=0,
            context_limit=limit,
            retained=list(labels), dropped=future_dropped,
        )
        return _make_worker_context_projection(
            authority_projection, selected_advice, audit,
        )

    for label, _field, _item in advice_candidates:
        proposed = retained + [label]
        candidate = candidate_projection(proposed)
        try:
            candidate_rendered = render_worker_context_projection(candidate, limit)
            candidate_fits = len(candidate_rendered) <= limit
        except ExecutionContractError as exc:
            if exc.code != WORKER_CONTEXT_TOO_LARGE:
                raise
            candidate_fits = False
        if candidate_fits:
            retained = proposed
        else:
            dropped.append(label)

    if not retained:
        raise ExecutionContractError(
            WORKER_CONTEXT_ADVICE_UNAVAILABLE,
            "required authority fits but no validated semantic advice item fits",
            details=[f"context_limit={limit}"],
        )

    # Finalize the audit fields after selection.  A tiny fixed-point loop keeps
    # the recorded serialized/rendered sizes equal to the final artifact.
    while True:
        dropped = [label for label in all_labels if label not in retained]
        selected_advice = advice_from_labels(retained)
        audit = _worker_context_audit(
            full_mission_chars=mission_chars,
            required_authority_chars=required_rendered_chars,
            required_authority_serialized_chars=required_serialized_chars,
            optional_advice_chars_before=optional_advice_chars_before,
            optional_advice_chars_retained=_serialized_chars(selected_advice),
            final_projection_chars=0,
            rendered_context_chars=0,
            context_limit=limit,
            retained=retained, dropped=dropped,
        )
        projection = _make_worker_context_projection(
            authority_projection, selected_advice, audit,
        )
        for _ in range(5):
            rendered = render_worker_context_projection(projection, limit)
            projection["projection_audit"]["final_projection_chars"] = _serialized_chars(projection)
            projection["projection_audit"]["rendered_context_chars"] = len(rendered)
            projection["worker_context_projection_hash"] = deterministic_hash(
                _without(projection, "worker_context_projection_hash"),
            )
            updated_chars = _serialized_chars(projection)
            updated_rendered_chars = len(rendered)
            if (
                projection["projection_audit"]["final_projection_chars"] == updated_chars
                and projection["projection_audit"]["rendered_context_chars"] == updated_rendered_chars
            ):
                break
        if len(rendered) <= limit:
            return projection
        if len(retained) <= 1:
            raise ExecutionContractError(
                WORKER_CONTEXT_TOO_LARGE,
                "Worker context projection exceeds its bound after deterministic budgeting",
                details=[f"context_limit={limit}"],
            )
        # Drop the lowest-priority whole advice item; authority is never
        # removed by this loop.
        retained.pop()


def _projection_forbidden_keys(value, path="projection"):
    forbidden = set(_RAW_FORBIDDEN_KEYS) | {
        "approved_plan_snapshot", "snapshot", "execution_graph", "graph",
        "full_plan", "plan_nodes", "obligation_ledger", "raw_response",
        "raw_mission_compiler_output", "file_sha256", "line_start", "line_end",
        "provenance", "source_provenance",
    }
    found = []
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).casefold() in {str(entry).casefold() for entry in forbidden}:
                found.append(f"{path}.{key}")
            found.extend(_projection_forbidden_keys(item, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            found.extend(_projection_forbidden_keys(item, f"{path}[{index}]"))
    return found


def validate_worker_context_projection(
    projection, mission, contract, dependency_summaries=None,
    max_chars=MAX_CONTEXT_CHARS,
):
    """Validate the compact projection without making it an authority source."""
    value = projection if isinstance(projection, dict) else {}
    authority = contract if isinstance(contract, dict) else {}
    full_mission = mission if isinstance(mission, dict) else {}
    limit = MAX_CONTEXT_CHARS if max_chars is None else max(1, int(max_chars))
    errors = []
    mission_check = validate_hydrated_worker_mission(
        full_mission, authority, dependency_summaries,
    )
    if not mission_check.get("valid"):
        errors.extend(f"full mission: {item}" for item in mission_check.get("errors", []))
    expected_authority = _worker_context_authority(full_mission, authority)
    expected_keys = set(expected_authority) | {
        "implementation_advice", "projection_audit", "rendering_version",
        "worker_context_projection_hash",
    }
    for key in sorted(set(value) - expected_keys):
        errors.append(f"projection contains unexpected field {key}")
    for key, expected in expected_authority.items():
        if value.get(key) != expected:
            errors.append(f"projection authority field {key} does not match the contract")
    if value.get("mission_hash") != full_mission.get("mission_hash"):
        errors.append("projection does not reference the full mission hash")
    if value.get("execution_contract_hash") != authority.get("contract_hash"):
        errors.append("projection does not reference the contract hash")
    if value.get("approved_plan_hash") != authority.get("plan_hash"):
        errors.append("projection does not reference the approved plan hash")
    if value.get("rendering_version") != WORKER_CONTEXT_RENDERING_VERSION:
        errors.append("projection rendering version is not current")

    advice = value.get("implementation_advice")
    full_advice = full_mission.get("implementation_advice", {})
    if not isinstance(advice, dict):
        errors.append("projection implementation_advice must be an object")
        advice = {}
    if isinstance(full_advice, dict):
        if advice.get("objective") not in (None, "") and advice.get("objective") != full_advice.get("objective"):
            errors.append("projection objective is not accepted full-mission advice")
        for field in MISSION_ADVICE_LIST_FIELDS:
            selected = list(advice.get(field, []) or [])
            source = list(full_advice.get(field, []) or [])
            cursor = 0
            for item in selected:
                try:
                    cursor = source.index(item, cursor) + 1
                except ValueError:
                    errors.append(f"projection advice {field} contains an item not in the full mission")
                    break

    audit = value.get("projection_audit")
    if not isinstance(audit, dict):
        errors.append("projection_audit is required")
        audit = {}
    if audit.get("authority_items_dropped", 0) != 0:
        errors.append("projection dropped required authority")
    if value.get("execution_invariant_set_hash"):
        invariant_projection = value.get("execution_invariant_projection")
        if not isinstance(invariant_projection, dict):
            errors.append("execution invariant projection is missing")
        else:
            if invariant_projection.get("execution_invariant_set_hash") != value.get("execution_invariant_set_hash"):
                errors.append("execution invariant projection set hash is stale")
            if invariant_projection.get("invariant_ids") != value.get("execution_invariant_ids"):
                errors.append("execution invariant projection ids do not match contract")
            if invariant_projection.get("mandatory_drops") != 0:
                errors.append("mandatory execution invariants were dropped")
            expected_invariant_projection_hash = invariant.canonical_hash(
                invariant._without(invariant_projection, "projection_hash"),
            )
            if invariant_projection.get("projection_hash") != expected_invariant_projection_hash:
                errors.append("execution invariant projection hash is invalid")
            try:
                invariant.render_worker_execution_invariant_projection(
                    invariant_projection, max_chars=limit,
                )
            except invariant.ExecutionInvariantError as exc:
                errors.append(str(exc))
    forbidden = _projection_forbidden_keys(value)
    if forbidden:
        errors.extend(f"projection contains forbidden internal field {item}" for item in forbidden[:20])
    expected_hash = deterministic_hash(_without(value, "worker_context_projection_hash"))
    if value.get("worker_context_projection_hash") != expected_hash:
        errors.append("worker context projection hash is invalid")

    serialized_chars = _serialized_chars(value)
    try:
        rendered = render_worker_context_projection(value, limit)
    except ExecutionContractError as exc:
        rendered = ""
        errors.append(str(exc))
    rendered_chars = len(rendered)
    if audit.get("final_projection_chars") not in (None, serialized_chars):
        errors.append("projection audit final_projection_chars is stale")
    if audit.get("rendered_context_chars") not in (None, rendered_chars):
        errors.append("projection audit rendered_context_chars is stale")
    all_labels = [item[0] for item in _worker_context_advice_items(full_advice)]
    selected_labels = _worker_context_advice_selection_labels(advice, full_advice)
    if audit.get("optional_items_retained") not in (None, len(selected_labels)):
        errors.append("projection audit retained advice is stale")
    expected_dropped = [label for label in all_labels if label not in selected_labels]
    if audit.get("optional_items_dropped") not in (None, len(expected_dropped)):
        errors.append("projection audit dropped advice is stale")
    return {
        "valid": not errors,
        "errors": errors[:40],
        "serialized_chars": serialized_chars,
        "rendered_chars": rendered_chars,
        "required_authority_chars": audit.get("required_authority_chars", 0),
        "optional_advice_chars": audit.get("optional_advice_chars_retained", 0),
        "optional_items_dropped": len(expected_dropped),
        "authority_items_dropped": audit.get("authority_items_dropped", 0),
    }


def normalize_mission_for_contract(mission, contract, *, task_goal=None):
    """Restore mandatory authority from the immutable contract before Worker handoff."""
    value = _copy(mission if isinstance(mission, dict) else {})
    authority = contract if isinstance(contract, dict) else {}
    value["execution_contract_id"] = authority.get("execution_contract_id")
    value["execution_contract_hash"] = authority.get("contract_hash")
    value["approved_plan_id"] = authority.get("plan_id")
    value["approved_plan_hash"] = authority.get("plan_hash")
    value["targets"] = list(value.get("targets", []) or [])
    value["done_when"] = _unique(
        list(authority.get("done_when", []) or []) + list(value.get("done_when", []) or []),
        limit=MAX_DONE_WHEN_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
    )
    value["do_not"] = _unique(
        list(authority.get("global_do_not_touch", []) or [])
        + list(authority.get("structured_prohibitions", []) or [])
        + list(value.get("do_not", []) or []),
        limit=MAX_PROHIBITIONS_PER_CONTRACT + MAX_SURFACES_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
    )
    value["invariants"] = _unique(
        list(authority.get("local_preservation_constraints", []) or [])
        + list(value.get("invariants", []) or []),
        limit=MAX_PRESERVATION_PER_CONTRACT + MAX_PROHIBITIONS_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
    )
    value["interfaces_to_reuse"] = _unique(
        list(authority.get("interfaces_to_reuse", []) or [])
        + list(value.get("interfaces_to_reuse", []) or []),
        limit=MAX_INTERFACES_PER_CONTRACT, text_limit=MAX_TEXT_CHARS,
    )
    value["inspection_targets"] = _unique(
        list(authority.get("allowed_inspection_paths", []) or [])
        + list(value.get("inspection_targets", []) or []),
        limit=MAX_SURFACES_PER_CONTRACT, text_limit=MAX_PATH_CHARS,
    )
    if task_goal:
        value.setdefault("task", task_goal)
    return value


def tool_scope(contract, path, *, mutation=True):
    authority = contract if isinstance(contract, dict) else {}
    target = _path(path)
    normalized = target.casefold()
    if not target:
        return {"allowed": False, "code": CONTRACT_SCOPE_VIOLATION, "reason": "empty or invalid path"}
    if mutation:
        allowed = {
            _path(item).casefold().rstrip("/")
            for item in authority.get("allowed_mutation_paths", []) or []
        }
        inspect_only = {
            _path(item).casefold().rstrip("/")
            for item in authority.get("allowed_inspection_paths", []) or []
        } - allowed
        protected = {_path(item).casefold() for item in authority.get("global_do_not_touch", []) or []}
        if any(normalized == item.rstrip("/") or normalized.startswith(item.rstrip("/") + "/") for item in protected):
            return {"allowed": False, "code": CONTRACT_SCOPE_VIOLATION, "reason": "path is protected by do_not_touch", "path": target}
        if not _mutation_path_allowed(authority, target):
            return {"allowed": False, "code": CONTRACT_SCOPE_VIOLATION, "reason": "path is outside allowed mutation scope", "path": target, "allowed_paths": sorted(allowed), "inspection_only": sorted(inspect_only)}
        return {"allowed": True, "path": target}
    allowed = {
        _path(item).casefold().rstrip("/")
        for item in authority.get("allowed_inspection_paths", []) or []
    }
    if not _inspection_path_allowed(authority, target):
        return {"allowed": False, "code": CONTRACT_SCOPE_VIOLATION, "reason": "path is outside allowed inspection scope", "path": target, "allowed_paths": sorted(allowed)}
    return {"allowed": True, "path": target}


mutation_scope_check = tool_scope
validate_tool_scope = tool_scope


def validate_child_contract(parent, child, *, other_contract_ids=None):
    """Validate contract-local decomposition; children may only shrink authority."""
    parent = parent if isinstance(parent, dict) else {}
    child = child if isinstance(child, dict) else {}
    errors = []
    if child.get("execution_contract_id") != parent.get("execution_contract_id"):
        errors.append("child must inherit parent execution_contract_id")
    for key in ("plan_id", "plan_hash"):
        if child.get(key) != parent.get(key):
            errors.append(f"child must inherit {key}")
    if child.get("contract_hash") != parent.get("contract_hash"):
        errors.append("child must inherit parent contract_hash")
    if not set(str(item) for item in child.get("plan_node_ids", []) or []).issubset(
        set(str(item) for item in parent.get("plan_node_ids", []) or [])
    ):
        errors.append("child plan_node_ids expand parent authority")
    if not set(str(item) for item in child.get("owned_plan_node_ids", []) or []).issubset(
        set(str(item) for item in parent.get("owned_plan_node_ids", []) or [])
    ):
        errors.append("child owned_plan_node_ids expand parent authority")
    if other_contract_ids and set(str(item) for item in child.get("plan_node_ids", []) or []).intersection(other_contract_ids):
        errors.append("child attempts cross-contract scope stealing")
    for child_field, parent_field in (
        ("allowed_mutation_surface_ids", "allowed_mutation_surface_ids"),
        ("allowed_mutation_paths", "allowed_mutation_paths"),
        ("allowed_inspection_surface_ids", "allowed_inspection_surface_ids"),
        ("allowed_inspection_paths", "allowed_inspection_paths"),
        ("requirement_ids", "requirement_ids"),
        ("done_when", "done_when"),
    ):
        if child_field == "allowed_mutation_paths":
            if any(not _mutation_path_allowed(parent, item) for item in child.get(child_field, []) or []):
                errors.append(f"child {child_field} expands parent authority")
            continue
        if child_field == "allowed_inspection_paths":
            if any(not _inspection_path_allowed(parent, item) for item in child.get(child_field, []) or []):
                errors.append(f"child {child_field} expands parent authority")
            continue
        parent_values = {str(item).casefold() for item in parent.get(parent_field, []) or []}
        child_values = {str(item).casefold() for item in child.get(child_field, []) or []}
        if not child_values.issubset(parent_values):
            errors.append(f"child {child_field} expands parent authority")
    for field in (
        "new_surface_proposal_ids", "target_new_surface_proposal_ids",
        "inspect_new_surface_proposal_ids", "approved_new_surface_parent_scopes",
    ):
        parent_values = {str(item).casefold() for item in parent.get(field, []) or []}
        child_values = {str(item).casefold() for item in child.get(field, []) or []}
        if not child_values.issubset(parent_values):
            errors.append(f"child {field} expands parent authority")
    for field in ("local_preservation_constraints", "structured_prohibitions", "global_do_not_touch", "global_do_not_touch_surface_ids", "interfaces_to_reuse"):
        parent_values = set(str(item) for item in parent.get(field, []) or [])
        child_values = set(str(item) for item in child.get(field, []) or [])
        if not parent_values.issubset(child_values):
            errors.append(f"child removed mandatory {field}")
    parent_done = list(parent.get("done_when", []) or [])
    child_done = list(child.get("done_when", []) or [])
    if any(
        not any(_contains_requirement(item, required) for required in parent_done)
        for item in child_done
    ):
        errors.append("child done_when expands parent authority")
    try:
        _validate_contract_bounds(child)
    except ExecutionContractError as exc:
        errors.append(str(exc))
    return {"valid": not errors, "errors": errors[:20]}


def child_contract(parent, proposal, *, restore_protections=True):
    """Create a bounded child projection from a parent execution contract."""
    parent = parent if isinstance(parent, dict) else {}
    proposal = proposal if isinstance(proposal, dict) else {}
    child = _copy(parent)
    child["is_child"] = True
    child["parent_execution_contract_id"] = parent.get("execution_contract_id")
    child["child_id"] = proposal.get("child_id")
    child["plan_node_ids"] = _ids(
        proposal.get("plan_node_ids") or parent.get("plan_node_ids")
    )
    child["owned_plan_node_ids"] = _ids(
        proposal.get("owned_plan_node_ids") or child.get("plan_node_ids")
    )
    child["allowed_mutation_paths"] = _unique(proposal.get("allowed_mutation_paths") or proposal.get("scope_hint") or parent.get("allowed_mutation_paths"), text_limit=MAX_PATH_CHARS)
    child["allowed_mutation_surface_ids"] = _ids(proposal.get("allowed_mutation_surface_ids") or parent.get("allowed_mutation_surface_ids"))
    child["allowed_inspection_paths"] = _unique(proposal.get("allowed_inspection_paths") or parent.get("allowed_inspection_paths"), text_limit=MAX_PATH_CHARS)
    child["allowed_inspection_surface_ids"] = _ids(proposal.get("allowed_inspection_surface_ids") or parent.get("allowed_inspection_surface_ids"))
    child["requirement_ids"] = _ids(proposal.get("requirement_ids") or parent.get("requirement_ids"))
    child["done_when"] = _unique(proposal.get("done_when") or parent.get("done_when"), text_limit=MAX_TEXT_CHARS)
    if restore_protections:
        for field in ("local_preservation_constraints", "structured_prohibitions", "global_do_not_touch", "global_do_not_touch_surface_ids", "interfaces_to_reuse"):
            child[field] = _copy(parent.get(field, []))
    else:
        for field in ("local_preservation_constraints", "structured_prohibitions", "global_do_not_touch", "global_do_not_touch_surface_ids", "interfaces_to_reuse"):
            child[field] = _copy(proposal.get(field, []))
    child["contract_hash"] = parent.get("contract_hash")
    return child


def validate_child_specs(parent, specs, other_contract_ids=None):
    """Validate compact model decomposition specs without accepting expansion."""
    safe = []
    rejected = []
    for index, spec in enumerate(list(specs or []), 1):
        raw = spec if isinstance(spec, dict) else {}
        invalid = []
        requested_mutation_paths = list(raw.get("scope_hint") or raw.get("allowed_mutation_paths") or [])
        requested_inspection_paths = list(raw.get("inspection_targets") or raw.get("allowed_inspection_paths") or [])
        invalid.extend(
            str(item) for item in requested_mutation_paths
            if not _mutation_path_allowed(parent, item)
        )
        invalid.extend(
            str(item) for item in requested_inspection_paths
            if not _inspection_path_allowed(parent, item)
        )
        requested_nodes = set(str(item) for item in raw.get("plan_node_ids", []) or [])
        parent_nodes = set(str(item) for item in parent.get("plan_node_ids", []) or [])
        invalid.extend(sorted(requested_nodes - parent_nodes))
        requested_requirements = set(str(item) for item in raw.get("requirement_ids", []) or [])
        parent_requirements = set(str(item) for item in parent.get("requirement_ids", []) or [])
        invalid.extend(sorted(requested_requirements - parent_requirements))
        requested_mutation_surfaces = set(str(item) for item in raw.get("allowed_mutation_surface_ids", []) or [])
        parent_mutation_surfaces = set(str(item) for item in parent.get("allowed_mutation_surface_ids", []) or [])
        invalid.extend(sorted(requested_mutation_surfaces - parent_mutation_surfaces))
        requested_inspection_surfaces = set(str(item) for item in raw.get("allowed_inspection_surface_ids", []) or [])
        parent_inspection_surfaces = set(str(item) for item in parent.get("allowed_inspection_surface_ids", []) or [])
        invalid.extend(sorted(requested_inspection_surfaces - parent_inspection_surfaces))
        if invalid:
            rejected.append({
                "spec": _copy(raw),
                "errors": ["child proposal expands approved contract scope: " + ", ".join(invalid[:12])],
            })
            continue
        proposal = {
            "execution_contract_id": parent.get("execution_contract_id"),
            "plan_id": parent.get("plan_id"), "plan_hash": parent.get("plan_hash"),
            "plan_node_ids": raw.get("plan_node_ids") or parent.get("owned_plan_node_ids", []),
            "allowed_mutation_paths": raw.get("scope_hint") or raw.get("allowed_mutation_paths") or parent.get("allowed_mutation_paths", []),
            "allowed_inspection_paths": raw.get("inspection_targets") or raw.get("allowed_inspection_paths") or parent.get("allowed_inspection_paths", []),
            "allowed_mutation_surface_ids": raw.get("allowed_mutation_surface_ids") or parent.get("allowed_mutation_surface_ids", []),
            "allowed_inspection_surface_ids": raw.get("allowed_inspection_surface_ids") or parent.get("allowed_inspection_surface_ids", []),
            "requirement_ids": raw.get("requirement_ids") or parent.get("requirement_ids", []),
            "done_when": raw.get("done_when") or parent.get("done_when", []),
            "child_id": f"CHILD-{index:03d}",
        }
        child = child_contract(parent, proposal)
        result = validate_child_contract(parent, child, other_contract_ids=other_contract_ids)
        if not result["valid"] or not str(raw.get("goal", "")).strip():
            rejected.append({"spec": _copy(raw), "errors": result.get("errors", []) or ["child goal is required"]})
            continue
        child["goal"] = _text(raw.get("goal"), MAX_TEXT_CHARS)
        child["objective"] = child["goal"]
        child["done_when"] = _unique(raw.get("done_when") or child.get("done_when"), limit=MAX_DONE_WHEN_PER_CONTRACT, text_limit=MAX_TEXT_CHARS)
        child["scope_hint"] = list(child.get("allowed_mutation_paths", []))
        safe.append(child)
    parent_done = list(parent.get("done_when", []) or [])
    if safe and any(
        not any(
            _contains_requirement(child_item, required)
            for child in safe
            for child_item in child.get("done_when", []) or []
        )
        for required in parent_done
    ):
        rejected.append({
            "spec": {"children": [_copy(item) for item in safe]},
            "errors": ["child decomposition dropped an approved done_when obligation"],
        })
        safe = []
    return {"valid": bool(safe) and not rejected, "children": safe, "rejected": rejected}


# Public V25.2 aliases keep the execution-contract module as the stable
# Stage 4 import seam while the parser/reconciler remains independently
# testable in ``hivo.execution_invariants``.
ExecutionInvariantSet = invariant.ExecutionInvariantSet
WorkerExecutionInvariantProjection = invariant.WorkerExecutionInvariantProjection
ExecutionInvariantError = invariant.ExecutionInvariantError
build_execution_invariant_set = invariant.build_execution_invariant_set
extract_execution_invariant_set = invariant.extract_execution_invariant_set
validate_execution_invariant_set = invariant.validate_execution_invariant_set
build_worker_execution_invariant_projection = invariant.build_worker_execution_invariant_projection
validate_worker_execution_invariant_projection = invariant.validate_worker_execution_invariant_projection
render_worker_execution_invariant_projection = invariant.render_worker_execution_invariant_projection
canonical_invariant_set_hash = invariant.canonical_invariant_set_hash


__all__ = [name for name in globals() if not name.startswith("_")]
